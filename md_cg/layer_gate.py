# -*- coding: utf-8 -*-
"""知识层准入闸（issue #749）——知识层只收「重要的、结论性的、理论的、可验证的、通用的」内容。

使用者裁定（2026-11-13）：
> 目前使用灵枢的 LLM 会默认把该写入情景层的内容写入到知识层，这是不应该的。
> 知识层必须是重要的、结论性的、理论的、可验证的、通用的知识，至少能符合一类学科通用内容。

为什么需要确定性闸而不是靠提示词：
  · 默认层一改，LLM 只要显式写 `layer="knowledge"` 就能绕过提示词；
  · 本仓纪律（第 3 条白箱）要求「条件判断交给确定性机制，LLM 只提供候选」。

判据（确定性、可解释、宁可降级不误杀）：
  ① **CCG 六要素**：知识要可验证 ⇒ 缺要素的不是知识而是片段（沿用 nodefile.CCG_REQUIRED）；
  ② **会话语境标记**：出现「今天/昨天/刚才/今早/上周」等**相对时间指代** ⇒ 这是情景叙述；
  ③ **即时状态句**：整条只是第一人称此刻的感受/动作（「我累了」「刚吃完饭」）⇒ 情景。

处置：不通过 ⇒ **降级到 contextual**（情景层），并在回执里给出 `layer_downgraded` 与原因清单
（不静默、不丢弃）。调用方可用 `force_layer=True` 显式越过（越权可审计）。

不适用条件：
  · 学科性无法机械判定——本闸只挡「明显是情景的」，不负责认定「确实通用」；
  · 已带 CCG 六要素且无相对时间指代的条目一律放行（宁放过不误杀）。
"""
from __future__ import annotations

import re

#: 会话语境的时间指代（出现即判情景倾向）
RELATIVE_TIME = re.compile(
    r"(今天|昨天|前天|今晚|今早|刚才|刚刚|上周|下周|本周|这周|上个月|这个月|今天早上|"
    r"今儿|昨儿|前天晚上|刚才那|这会儿|那会儿)"
)

#: 纯即时状态/动作（整条只有这些，没有结论性内容）
INSTANT_STATE = re.compile(
    r"^\s*(我|咱|我们)?\s*(好?累|好?困|好?饿|吃饱|吃了|睡了|起床|洗了|出门|上班|下班|忙完)"
)


# 生效条件：text 为待判内容；返回 (是否可入知识层, 原因列表)
def judge(text):
    """知识层准入判定。返回 (ok, reasons)；reasons 为空表示放行。"""
    body = str(text or "")
    reasons = []
    from . import nodefile as _nf
    missing = [f for f in _nf.CCG_REQUIRED if f not in body]
    if missing:
        reasons.append("缺 CCG 要素：" + ",".join(missing))
    m = RELATIVE_TIME.search(body)
    if m:
        reasons.append("含会话语境时间指代：%s" % m.group(1))
    if INSTANT_STATE.match(body.strip()):
        reasons.append("即时状态句（非结论性）")
    return (not reasons), reasons