# -*- coding: utf-8 -*-
"""value_conflict · 同条件不同取值判据（红队缺口 C1；v2 收窄）

v1 实测教训：自由正则从正文抽「键=数值」，真实库 400 节点 400/400 全命中
（时间戳 T17:38、索引行「执行：1」都被当键值对）⇒ 必然大量假阳性。

v2 口径：
  ① 首选**声明面** frontmatter 的 value_slots（dict，如 {"连接池": 32}）；
     两侧都声明且同名槽位取值不同 ⇒ 冲突（确定、零假阳性）。
  ② 启发式正则仅当 allow_heuristic=True 时参与，默认关。
"""
from __future__ import annotations

import re

_HEUR = re.compile(r"([\u4e00-\u9fa5]{2,12})\s*[=:：]?\s*(\d+(?:\.\d+)?)(?![\d:])")

SLOT_KEYS = ("value_slots", "values")


def declared_slots(fm):
    for k in SLOT_KEYS:
        v = (fm or {}).get(k)
        if isinstance(v, dict) and v:
            return {str(a): str(b) for a, b in v.items()}
    return {}


def heuristic_slots(text):
    out = {}
    for m in _HEUR.finditer(str(text or "")):
        k, v = m.group(1), m.group(2)
        if k not in out:
            out[k] = v
    return out


def _norm_cs(cs):
    if not cs:
        return ""
    if isinstance(cs, dict):
        return ";".join("%s=%s" % (k, v) for k, v in sorted((str(k), str(v)) for k, v in cs.items()))
    return str(cs)


def compare(a_fm, a_content, b_fm, b_content, allow_heuristic=False):
    ca = _norm_cs((a_fm or {}).get("condition_space"))
    cb = _norm_cs((b_fm or {}).get("condition_space"))
    if not ca or not cb or ca != cb:
        return None
    pa, pb = declared_slots(a_fm), declared_slots(b_fm)
    if not pa or not pb:
        if not allow_heuristic:
            return None
        pa = pa or heuristic_slots(a_content)
        pb = pb or heuristic_slots(b_content)
    diffs = [k for k in pa if k in pb and pa[k] != pb[k]]
    if not diffs:
        return None
    k = diffs[0]
    return {"kind": "same_condition_diff_value", "slot": k,
            "a_value": pa[k], "b_value": pb[k], "condition_space": ca}


def find_in(content, fm, existing, allow_heuristic=False):
    for nid, efm, econtent in existing or []:
        hit = compare(fm, content, efm, econtent, allow_heuristic=allow_heuristic)
        if hit:
            hit["with"] = str(nid)
            return hit
    return None
