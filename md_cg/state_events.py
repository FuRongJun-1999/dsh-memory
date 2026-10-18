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
  · **判据单点**（#383，2026-10-14）：`old`/`new` 的「空」＝ `None` **或空白字符串**，
    判据本体只此一处（`is_void`，源模块）；投影侧 `state_slots._is_void` **直接绑定
    本函数**（同一对象，不另立一份），写入口对裸值经 `void_value` 走同一条腿。
    `old` 与 `new` **同空**（含 `""`/全空白串）＝空事件 ⇒ ValueError，且校验先于
    建目录/写盘 ⇒ **零落盘**。

KINDS 五类对齐《角色扮演一致性锚调研 v0.1》§3.4「变迁事件」：
迁移 migration ／ 撤回 retraction ／ 启用 enablement ／ 购买获得 acquisition ／
替换 replacement。「撤回」语义：old 有值而 new 为空（值作废、无新值）；
「启用」：old 空而 new 有值；「迁移/替换」：old 与 new 皆有值。
「空」＝ `None` **或空白字符串**（判据单点 `is_void`）；old 与 new **同空**＝空事件
（既非启用也非撤回）⇒ `append` 拒收，不落任何台账行。
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


#: 调用方可控字段的**逐字段字节上限**（issue #443：无长度约束 ⇒ 审计/台账面 1:1 写入放大）。
#: 取 8192 B：单条状态事件是「一次变迁的记录」，不是正文载体；超限即视为调用方用错面。
#: 与 writepipe.oversize_response 同口径——**拒写而不是截断**（截断后的记录看起来像完整记录，
#: 实际丢了内容 ⇒ 比不记录更坏，与 #523 的「假绿」同族）。
_MAX_FIELD_BYTES = 8192


# 生效条件：name 为字段名、v 为待落盘值；v 的 UTF-8 编码长度不超过 _MAX_FIELD_BYTES 时原样返回，
# 超限时抛 ValueError（消息含字段名、实测字节、上限），**不截断、不静默丢弃**。
def _bounded(name, v):
    if v is None:
        return v
    raw = v if isinstance(v, (bytes, bytearray)) else str(v).encode('utf-8')
    n = len(raw)
    if n > _MAX_FIELD_BYTES:
        raise ValueError(
            f'状态事件字段 {name} 超出上限：{n} B > {_MAX_FIELD_BYTES} B（issue #443；拒写不截断）')
    return v


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


# 生效条件：rec 为台账记录 dict——`rec.get("new")` 为 None，或为字符串且 `str.strip()` 后为空（含全空白串）时返回 True（撤回/值作废）；其余（非 None 且非空白字符串，含数字 0、False、非空串）返回 False；入参非 dict 时按 `.get` 抛 AttributeError（台账读面保证为 dict，不吞错）。
def is_void(rec) -> bool:
    """撤回判据（**全仓唯一单点**）：`rec["new"]` 无值（None 或空白串）＝值作废、无新值。

    #375（2026-10-14）在投影侧把判据从 `new is None` 放宽为「**None 或空白字符串**」；
    #383（2026-10-14）把这**同一条腿**上收到源模块，成为全仓唯一判据本体。入参是
    **台账记录**（行形态）——投影侧 `state_slots._is_void` 绑定本函数（同一对象，
    不另立一份），写入口对裸值经 `void_value` 适配同一条腿。台账行与 `history`
    条目的 `old`/`new` **原值一字不改**（值作废只发生在投影回放里，见 `_replay`）。
    """
    v = rec.get("new")
    if v is None:
        return True
    return isinstance(v, str) and not v.strip()


# 生效条件：v 为待判的**裸值**（写入口的 old/new）——包成记录后走同一单点 `is_void`：v 为 None 或空白字符串时返回 True，其余（含数字 0、False、非空串）返回 False；不复制判据、不改写 v。
def void_value(v) -> bool:
    """写入口的值面适配：裸值 → 同一单点 `is_void`（**不另立第二份判据**）。"""
    return is_void({"new": v})


# 生效条件：subject 与 slot 去空白后必须非空（否则 ValueError）；kind 非 None 时必须属于
# KINDS（否则 ValueError）；old 与 new 不得同时为**空**（None 或空白串，判据单点
# `void_value`，否则 ValueError——校验先于任何建目录/写盘，故零落盘）；通过后在
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
    if void_value(old) and void_value(new):
        raise ValueError("状态事件 old 与 new 不能同时为空（空事件无意义）")
    # issue #443：调用方可控字段逐字段过闸（拒写）。subject/slot 已在上面 strip，仍过闸
    # （strip 只减首尾空白，不约束长度）。old/new 是本次放大的主因（各 1MB ⇒ 单次 2MB）。
    sub = _bounded('subject', sub)
    sl = _bounded('slot', sl)
    old = _bounded('old', old)
    new = _bounded('new', new)
    evidence = _bounded('evidence', evidence)
    actor = _bounded('actor', actor)
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


# 生效条件：ledger_path 不存在时不产出记录；存在时逐行 json.loads（空行跳过；非对象载荷或
# JSON 解析失败按坏行处置——计数+有界样本+stderr 告警后跳过，不中断读）；subject/slot/kind
# **非 None** 时按对应字段过滤（空串亦为合法过滤值）；按落盘序 yield，须消费至尾部才完成全部坏行计数。
def iter_read(cg, subject=None, slot=None, kind=None):
    """逐行读回；过滤、坏行告警与计数与 read 共用此单点。

    调用者须消费完迭代器，才会观察到文件后部的坏行。额外内存只含一行。
    """
    p = ledger_path(cg)
    if not os.path.exists(p):
        return
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
            yield rec


# 生效条件：完整消费 iter_read 后返回列表；limit 为真值时保持原有 out[-int(limit):] 切片语义，含负数；缺失账本返回 []。
def read(cg, subject=None, slot=None, kind=None, limit=0) -> list:
    """读回（可按 subject/slot/kind 过滤；limit=0 不截断）。坏行跳过并记账。"""
    out = list(iter_read(cg, subject=subject, slot=slot, kind=kind))
    if limit:
        out = out[-int(limit):]
    return out
