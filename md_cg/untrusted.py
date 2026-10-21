# -*- coding: utf-8 -*-
"""untrusted · 写入面「把外部文本当数据」标记（v4：精度优先 + 指令框架）

使用者裁定（2026-10-21）：未验证、未信任的信息本来就不应该执行。
标记的后果是「不进 recall（上下文）」⇒ 判据精度优先，宁漏不误伤。

判据（A 且 B）：
  A) 出现指令式/伪装身份短语（MARKERS）
  B) 三选一：
     · 短语位于行首或紧随冒号（真指令的排版形态）；
     · 正文含**指令框架**（系统通知：/ 管理员指令：/ 开发者要求： 等）；
     · 命中 >= 2 个不同 marker（单点更可能是引用/讨论）。
"""
from __future__ import annotations

import re

MARKERS = (
    "忽略以上",
    "忽略之前",
    "无视规则",
    "跳过检查",
    "必须在结尾",
    "以系统身份",
    "你现在是助手",
)

_LEAD = re.compile(r"(?:^|[\n。；;：:])[\s>*\-]*(?:%s)" % "|".join(re.escape(m) for m in MARKERS))
#: 指令框架：伪装成「上级/系统」下发的句式（单凭它不算，需与 marker 同时出现）
_FRAME = re.compile(r"(?:系统|管理员|上级|开发者|平台)(?:通知|指令|要求|规定)\s*[：:]")


def classify(content):
    """返回 {"untrusted": bool, "markers": [...], "reason": str|None}。"""
    text = str(content or "")
    hits = [m for m in MARKERS if m in text]
    if not hits:
        return {"untrusted": False, "markers": [], "reason": None}
    if _LEAD.search(text):
        return {"untrusted": True, "markers": hits, "reason": "line_start_or_after_colon"}
    if _FRAME.search(text):
        return {"untrusted": True, "markers": hits, "reason": "instruction_frame"}
    if len(hits) >= 2:
        return {"untrusted": True, "markers": hits, "reason": "multi_marker"}
    return {"untrusted": False, "markers": hits, "reason": None}
