# -*- coding: utf-8 -*-
"""状态事件保守抽取（会话轮 → 台账）——每轮写入链的第二步，**生产方在此**。

# 功能名：会话轮的保守状态抽取（用户轮 → 状态事件台账）
# 生效条件：每轮写 `_recent` 窗口之后，对**同一轮**用户发言调 `extract_and_record`；
#   开关 `MDCG_STATE_EXTRACT` 缺省开（`=0` 关）。
# 子功能：① 只抽用户轮 ② 两条高精度规则（地点·所在迁移 / 情感·偏好）③ 同值去重
#   ④ evidence/actor 可甄别 ⑤ 开关。
# 执行：`extract_turn(text, role, subject)` 纯函数给候选；`extract_and_record(cg, …)`
#   落台账（经 `state_events.append` 单点）。
# 验证方式：`md_cg/test_state_extract.py`（原 `scripts/test_state_extract.py`）。
# 不适用条件：不做计划族抽取（任务走任务台账）；不做语义消歧（`not_fact` 等）；
#   不做助手轮（助手自述不复盖真值）。

**为什么本体在 `md_cg/` 而非 `scripts/`（2026-11-02，本仓真实缺陷修复）**：
本模块此前落在 `scripts/state_extract.py`，而 `package.json` 的 `files` 白名单
只发 `scripts/workspace_index.py` ⇒ **随包发布物里根本没有本模块**。实测
`npm pack --dry-run --ignore-scripts` 的发货清单 1791 件中 `scripts/` 仅 1 件，
`state_extract.py` / `sync_zcode_session.py` 双双 MISSING。后果：装机侧
（`~/.dsh/profiles/*/node_modules/@furongjun1999/dsh-memory/`）没有抽取器，
`sync_zcode_session._load_state_extract()` 无从装载 ⇒ **每轮记账链在装机环境里
是断的**，生产台账 `_state_events.jsonl` 长期 `events=0`（实测）。
`md_cg/` 整目录在 `files` 白名单内且已随包发货，故把**生产方**移到此地；
`scripts/state_extract.py` 保留为**薄垫片**（只 re-export，不含第二份判据），
既有 import 路径与 `sync_zcode_session` 的装载点逐字不变。

使用者 2026-10-06 架构裁定：「把这个功能作为会话的 10 轮信息写入，并在写入 mdcg
的时候做处理……每次写入异步加了一些过程，但是好处是得到了可维护的状态，同时具备
了认知图和语义时空图，原始信息的关系追溯。」

定位（与写窗口同一条链路的第二步）：
  `sync_zcode_session` 每轮把原文写 `_recent` 窗口 → **本件对同一轮做保守抽取**
  → 命中者 append 进状态台账（`state_events.append` 的库层单点）→ `state_slots`
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


#: 否定前缀（#169）：不/没/无/别（可隔空格、可套「太/怎么」）——
#: 出现在正面谓词之前即判负；口径「宁可漏，不可误」：前缀位有否定标记就不作正面记。
_NEG_PREFIX_RE = re.compile(r"[不没无别]\s*(?:怎么|太)*")


def _neg_polarity(match_text: str, pred: str) -> bool:
    """极性判定：谓词自带否定（讨厌/不喜欢）或前缀位出现否定标记 => 负面。取首次出现（find）：谓词在宾语中再现时不误判。"""
    if not pred:
        return False                      # 非情感规则（无 p 组）：不带极性
    if pred in ("讨厌", "不喜欢"):
        return True
    idx = match_text.find(pred)
    if idx <= 0:
        return False
    return bool(_NEG_PREFIX_RE.search(match_text[:idx]))


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
        neg = _neg_polarity(m.group(0), m.groupdict().get("p") or "")
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
    from . import state_events as _se
    from . import state_slots as _ss
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
