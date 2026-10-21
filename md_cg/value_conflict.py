# -*- coding: utf-8 -*-
"""value_conflict · 同条件不同取值判据（红队缺口 C1）

仓内评测 AGI七维评分报告 L4 段已把这条判成 S1 FAIL：同条件空间下把数值改掉，
被判定 ACCEPT/无冲突。本模块只做这一条，且只收能给出证据的形态：

  两个节点 condition_space 逐位相等且非空，正文里出现同名键的不同数值。

键形态：键名（2-12 字中文/字母/下划线）+ 可选分隔符 + 数值。
确定、可复算、无 LLM。条件空间不等或为空一律不比。
"""
from __future__ import annotations

import re

_PAIR = re.compile(r"([\u4e00-\u9fa5A-Za-z_][\u4e00-\u9fa5A-Za-z0-9_]{1,11})\s*[=:：]?\s*(\d+(?:\.\d+)?)")


def pairs(text):
    out = {}
    for m in _PAIR.finditer(str(text or "")):
        k, v = m.group(1), m.group(2)
        if k not in out:
            out[k] = v
    return out


def _norm_cs(cs):
    if not cs:
        return ""
    if isinstance(cs, dict):
        items = sorted((str(k), str(v)) for k, v in cs.items())
        return ";".join("%s=%s" % (k, v) for k, v in items)
    return str(cs)


def compare(a_fm, a_content, b_fm, b_content):
    ca = _norm_cs((a_fm or {}).get("condition_space"))
    cb = _norm_cs((b_fm or {}).get("condition_space"))
    if not ca or not cb or ca != cb:
        return None
    pa, pb = pairs(a_content), pairs(b_content)
    diffs = [k for k in pa if k in pb and pa[k] != pb[k]]
    if not diffs:
        return None
    k = diffs[0]
    return {"kind": "same_condition_diff_value", "slot": k,
            "a_value": pa[k], "b_value": pb[k], "condition_space": ca}


def find_in(content, fm, existing):
    for nid, efm, econtent in existing or []:
        hit = compare(fm, content, efm, econtent)
        if hit:
            hit["with"] = str(nid)
            return hit
    return None
