# -*- coding: utf-8 -*-
"""aeis_core.textutil — 纯文本工具（自 aeis/layered.py 逐字抽取）。

只抽取白箱内核真正使用到的纯函数，避免把 layered.py 的 LLM 路由层
（DeepSeek 接入等非白箱知识库能力）一并带入。
"""
import re as _re


def _bigram_set(text):
    """二元组集合（去非中文/字母数字）。"""
    t = _re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text or "")
    return {t[i:i + 2] for i in range(len(t) - 1)}
