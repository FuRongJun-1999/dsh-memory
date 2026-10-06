#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""state_extract —— 会话轮的**状态事件保守抽取**（挂进每轮写 mdcg 的链路）。

使用者 2026-10-06 架构裁定：「把这个功能作为会话的 10 轮信息写入，并在写入 mdcg
的时候做处理……每次写入异步加了一些过程，但是好处是得到了可维护的状态，同时具备
了认知图和语义时空图，原始信息的关系追溯。」

定位（与写窗口同一条链路的第二步）：
  `sync_zcode_session` 每轮把原文写 `_recent` 窗口 → **本件对同一轮做保守抽取**
  → 命中者 append 进状态台账（`cg(op=state_event)` 的库层单点）→ `state_slots`
  投影/`state_atlas` 视图、`_recent`/转写为原文面——**三层同源、evidence 互指**。
  钩子在轮末以子进程运行（会话外处理、不占模型上下文时间）——即使用者说的「异步」。

保守口径（v1，写入在役库的纪律：**宁可漏，不可误**）：
  ① **只抽用户轮**（真人发言＝事实源；助手自述不复盖真值——沿鲸娘线口径）；
  ② 仅两条**高精度**规则（探针依据：裸词形噪声高者一律不做）：
     · 地点·所在（迁移）：`(我)?(搬家|搬到了?|搬去|现在住在|住在)X`
     · 情感·偏好：`我(最|很|超|不太|不怎么)?(喜欢|爱|讨厌|不喜欢)X`
  ③ **去重**：抽取值与投影现值相同即跳过（防每轮重复记账）；
  ④ 全程可追溯：`evidence` 带 `[auto] session=… turn=… 短证`、`actor="state_extract"`、
     slot 归通用族（可用 op=state_chain 逐条审计），误记可整体甄别/清理；
  ⑤ 开关 `MDCG_STATE_EXTRACT`：**缺省开**（使用者的架构裁定）——`=0` 关闭。

不适用（如实）：工程/技术会话中的"我喜欢这个方案"类语句属**真偏好**（记录无误亦非
无用）；但"我要加个功能"这类任务性语句**不抽**（计划族规则 v1 不做——任务走任务
台账，不走状态台账）。
"""
from __future__ import annotations

import os
import re

#: 抽取主体（默认「我」——本机使用者；env `MDCG_STATE_SUBJECT` 可覆盖）
DEFAULT_SUBJECT = "我"

#: 高精度规则表： (正则, 数值组名, 槽位, kind)
#: 只收「用户轮 + 第一人称持久状态」——逐条都给得出"为什么不会误伤"。
RULES = [
    # 地点·所在（迁移）：搬家/搬到/搬去/现在住在/住在 + 目的地。
    # 「在」单字不入式（"我在看代码"必误伤）；「住」需要完整词形。
    (re.compile(r"(?:我)?(?:搬(?:家|到了|到|去了|去)|现在住(?:在)?|住在)"
                r"(?P<v>[^\s，。！？,；;]{2,12})"),
     "v", "地点·所在", "migration"),
    # 情感·偏好：我(最/很/超/不太/不怎么)?喜欢/爱/讨厌/不喜欢 + 对象。
    (re.compile(r"我(?:最|很|超|不太|不怎么)?(?P<p>喜欢|爱|讨厌|不喜欢)"
                r"(?P<v>[^\s，。！？,；;]{1,10})"),
     "v", "情感·偏好", "acquisition"),
]


def enabled() -> bool:
    """开关：缺省开（使用者裁定）；`MDCG_STATE_EXTRACT=0` 关闭。"""
    return os.environ.get("MDCG_STATE_EXTRACT", "1") != "0"


def _clean_value(val: str) -> str:
    """剥句尾语气助词（了/啦/呀/哦/喔/噢/嘛/呢）——「青岛了」→「青岛」。"""
    return re.sub(r"[了啦呀哦喔噢嘛呢]+$", "", val).strip()


def _short(text: str, n: int = 24) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t[:n]


def extract_turn(text: str, role: str, subject: str = None):
    """单轮抽取（只认用户轮）→ [候选事件 dict, ...]（零命中返回 []）。"""
    subject = subject or os.environ.get("MDCG_STATE_SUBJECT") or DEFAULT_SUBJECT
    if role != "user" or not text:
        return []
    out = []
    for rx, gp, slot, kind in RULES:
        m = rx.search(text)
        if not m:
            continue
        val = _clean_value((m.group(gp) or "").strip())
        if not val:
            continue
        neg = m.groupdict().get("p") in ("讨厌", "不喜欢")
        new = ("不喜欢：" + val) if neg else val
        out.append({"subject": subject, "slot": slot, "new": new, "kind": kind,
                    "match": m.group(0)})
    return out


def extract_and_record(cg, session: str, turn_no, role: str, text: str,
                       subject: str = None) -> int:
    """抽取并 append 进状态台账（去重：与现值相同即跳过）。返回写入条数。

    调用方（每轮同步链）在写 `_recent` 窗口之后调用本函数；任何异常由调用方
    fail-soft 兜住（与既有钩子纪律一致）。
    """
    import sys
    from pathlib import Path
    repo = str(Path(__file__).resolve().parent.parent)
    if repo not in sys.path:
        sys.path.insert(0, repo)
    from md_cg import state_events as _se
    from md_cg import state_slots as _ss
    n = 0
    for ev in extract_turn(text, role, subject):
        cur = _ss.project(cg, subject=ev["subject"], slot=ev["slot"],
                          include_retired=True, history=False)
        live = cur[0].get("value") if cur else None
        if live == ev["new"]:
            continue                      # 现值相同：去重（防每轮重复记账）
        _se.append(cg, ev["subject"], ev["slot"],
                   old=(live if live is not None else None), new=ev["new"],
                   kind=ev["kind"], seq=turn_no,
                   evidence="[auto] session=%s turn=%s %s"
                            % (session, turn_no, _short(text)),
                   actor="state_extract")
        n += 1
    return n
