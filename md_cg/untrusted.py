# -*- coding: utf-8 -*-
"""untrusted · 写入面「把外部文本当数据」标记（红队缺口 C2；v2 收窄）"""
from __future__ import annotations

MARKERS = (
    "忽略以上",
    "忽略之前",
    "无视规则",
    "跳过检查",
    "必须在结尾",
    "以系统身份",
    "你现在是助手",
)


def classify(content):
    text = str(content or "")
    hits = [m for m in MARKERS if m in text]
    return {"untrusted": bool(hits), "markers": hits}
