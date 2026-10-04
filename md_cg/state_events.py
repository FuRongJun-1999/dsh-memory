# -*- coding: utf-8 -*-
"""状态事件账本（append-only）——多主体世界模型 L0「事件必记账」的最小承载。

背景（对齐评估 v0.1，§2 L0）：CD-WHALE-01（鲸娘语料 731 轮）的六类缺陷全部落在
「迁移/撤回/启用/来源」四个**状态操作**上（属性记得住、状态记不住）；CTP-P5
回放的敏感性边界一证明「现行侧若只有状态陈述（T2）而无事件记录（T1），设施回滚
只能判 DEFER」——故「事件必记账」是状态链（基线→变更→后续引用）与退役/否定
语义的前置（跨切纪律 1）。

设计约束（对齐评估 v0.1 复核修订后的口径）：
  · **append-only**：`_recent.jsonl` 为窗口滚动面（`DEFAULT_RECENT_WINDOW=200`，
    `roll_recent` 超限即截断），不可作一等记录；本账本只追加、不读改写、不截断。
  · **单一真源**：事件是源、槽位现值是投影（未来 L2 寄存器由本账本物化；
    落盘位置与 `_evolution` 台账/审计同级：`<root>/_state_events.jsonl`）。
  · **五元结构**：主体 subject ／ 槽位 slot ／ 旧值 old → 新值 new ／ 轮或序号
    seq ／ 出处 evidence（＋ kind 五类变迁事件 ＋ actor 断言者 ＋ t 时间戳）。

KINDS 五类对齐《角色扮演一致性锚调研 v0.1》§3.4「变迁事件」：
迁移 migration ／ 撤回 retraction ／ 启用 enablement ／ 购买获得 acquisition ／
替换 replacement。「撤回」语义：old 有值而 new 为空（值作废、无新值）；
「启用」：old 空而 new 有值；「迁移/替换」：old 与 new 皆有值。
分类本身不进判据（记账不判语义），只作检索面标签。
"""
from __future__ import annotations

import json
import os
import sys
import time

from .fsutil import FileLock

#: 账本文件名（库根下，与 `_recent.jsonl`/`_write_2pc.jsonl` 同级）。
STATE_EVENTS_NAME = "_state_events.jsonl"

#: 五类变迁事件（角色扮演一致性锚调研 v0.1 §3.4）。
KINDS = ("migration", "retraction", "enablement", "acquisition", "replacement")

#: 坏行容忍记账（容忍 ≠ 静默——本仓 N225 已确立的判据：跳过要可观测）。
BAD_ROWS = 0            # 累计**跳过动作次数**（同一坏行每次 read 均计一次；非按行去重）
_BAD_ROW_SAMPLES = []   # 有界样本：(行号, 行首 80 字符, 异常类型名)
_BAD_ROW_SAMPLE_CAP = 8


def _note_bad_row(lineno: int, line: str, exc: Exception):
    global BAD_ROWS
    BAD_ROWS += 1
    if len(_BAD_ROW_SAMPLES) < _BAD_ROW_SAMPLE_CAP:
        _BAD_ROW_SAMPLES.append((lineno, line[:80], type(exc).__name__))
    sys.stderr.write(
        f"[state_events] 跳过坏行（第 {lineno} 行，累计 {BAD_ROWS}）："
        f"{type(exc).__name__}: {exc}\n")


# 生效条件：cg 可解析出 root 时，返回 os.path.join(cg.root, STATE_EVENTS_NAME)。
def ledger_path(cg) -> str:
    return os.path.join(cg.root, STATE_EVENTS_NAME)


# 生效条件：subject 与 slot 去空白后必须非空（否则 ValueError）；kind 非 None 时必须属于
# KINDS（否则 ValueError）；old 与 new 不得同时为 None（否则 ValueError）；通过后在
# FileLock(ledger_path) 内以追加模式写一行 JSON（ensure_ascii=False，flush+fsync），
# 返回落盘记录 dict（不改任何既有文件、不读改写、不截断）。
def append(cg, subject, slot, old=None, new=None, kind=None, seq=None,
           evidence="", actor="", extra=None) -> dict:
    """追加一条状态事件（append-only；跨进程锁；崩溃不留半截文件）。"""
    sub = str(subject or "").strip()
    sl = str(slot or "").strip()
    if not sub:
        raise ValueError("状态事件必须声明主体（subject）")
    if not sl:
        raise ValueError("状态事件必须声明槽位（slot）")
    if kind is not None and kind not in KINDS:
        raise ValueError(f"未知变迁事件类型：{kind}（允许：{KINDS}）")
    if old is None and new is None:
        raise ValueError("状态事件 old 与 new 不能同时为空（空事件无意义）")
    rec = {
        "t": time.time(),
        "subject": sub,
        "slot": sl,
        "old": old,
        "new": new,
        "kind": kind,
        "seq": seq,
        "evidence": str(evidence or ""),
        "actor": str(actor or ""),
    }
    if extra:
        rec.update(extra)
    p = ledger_path(cg)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with FileLock(p):
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
    return rec


# 生效条件：ledger_path 不存在时返回 []；存在时逐行 json.loads（空行跳过；非对象载荷或
# JSON 解析失败按坏行处置——计数+有界样本+stderr 告警后跳过，不中断读）；subject/slot/kind
# **非 None** 时按对应字段过滤（空串亦为合法过滤值，2026-10-05 复核口径钉正）；limit 为
# 真值时只保留最后 limit 条；返回记录列表（落盘序）。
def read(cg, subject=None, slot=None, kind=None, limit=0) -> list:
    """读回（可按 subject/slot/kind 过滤；limit=0 不截断）。坏行跳过并记账。"""
    p = ledger_path(cg)
    out = []
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if not isinstance(rec, dict):
                    raise ValueError("行载荷非对象")
            except Exception as e:  # noqa: BLE001 —— 容忍≠静默：记账后跳过
                _note_bad_row(i, line, e)
                continue
            if subject is not None and rec.get("subject") != subject:
                continue
            if slot is not None and rec.get("slot") != slot:
                continue
            if kind is not None and rec.get("kind") != kind:
                continue
            out.append(rec)
    if limit:
        out = out[-int(limit):]
    return out
