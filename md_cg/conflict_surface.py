# -*- coding: utf-8 -*-
"""conflict_surface · 检索结果内的「显式矛盾对」暴露（issue：红队实测「冲突记忆不提示」）

判据只收**确定性、可复算**的一类矛盾：

    A 的 `non_applicable_conditions`（不适用条件）文本，作为**≥4 字的连续子串**
    出现在 B 的正文里 ⇒ A 明确排除了 B 所述情形，两者对同一问题给出互斥答案。

为什么不收「同条件不同取值」：仓内评测已把那条判成 S1 FAIL（引擎不覆盖该比对），
属独立设计改动；本模块只做已经能判准的那一类，避免制造假阳性。

纪律对齐：第 4 条根因纪律（先取证不猜测）——只报能给出证据子串的对；
第 5 条验证纪律——无证据即不报（返回空列表，而不是"可能冲突"）。
"""
from __future__ import annotations

MIN_EVIDENCE = 4          # 证据子串最短长度（防单字噪声）
MAX_PAIRS = 5             # 单次最多报几对


def _norm(text: str) -> str:
    return " ".join(str(text or "").split())


def _neg_texts(fm) -> list:
    raw = (fm or {}).get("non_applicable_conditions") or []
    if isinstance(raw, str):
        raw = [raw]
    out = []
    for x in raw:
        s = _norm(x)
        if len(s) >= MIN_EVIDENCE:
            out.append(s)
    return out


def conflicts_among(nodes, limit: int = MAX_PAIRS) -> list:
    """nodes: [节点 dict]（含 id/frontmatter/content）。返回矛盾对列表。"""
    items = []
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        items.append((str(n.get("id") or ""), _neg_texts(n.get("frontmatter")),
                      _norm(n.get("content"))))
    pairs = []
    for a_id, a_negs, _a_body in items:
        for b_id, _b_negs, b_body in items:
            if a_id == b_id or not b_body:
                continue
            for neg in a_negs:
                if neg in b_body:
                    pairs.append({"a": a_id, "b": b_id, "evidence": neg,
                                  "kind": "a_neg_in_b_body"})
                    break
            if len(pairs) >= limit:
                return pairs
    return pairs


from . import value_conflict as _vc
from . import untrusted as _ut


def value_pairs_among(nodes, limit: int = MAX_PAIRS) -> list:
    """同 condition_space 下同名键不同值 —— 复用 value_conflict.compare。"""
    items = []
    for n in nodes or []:
        if isinstance(n, dict):
            items.append((str(n.get("id") or ""), n.get("frontmatter") or {}, _norm(n.get("content"))))
    out = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a_id, a_fm, a_body = items[i]
            b_id, b_fm, b_body = items[j]
            hit = _vc.compare(a_fm, a_body, b_fm, b_body)
            if hit:
                hit["a"], hit["b"] = a_id, b_id
                out.append(hit)
            if len(out) >= limit:
                return out
    return out


def untrusted_among(nodes) -> list:
    """检索结果里命中「伪装系统消息/指令式」的节点（只报案，不改内容）。"""
    out = []
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        r = _ut.classify(n.get("content"))
        if r.get("untrusted"):
            out.append({"id": str(n.get("id") or ""), "markers": r.get("markers")})
    return out


def as_meta(nodes, limit: int = MAX_PAIRS) -> dict:
    """把三类信号包成可直接并进 meta 的字典（空则不产生键）。"""
    meta = {}
    pairs = conflicts_among(nodes, limit=limit)
    if pairs:
        meta["conflicts_among"] = pairs
    vp = value_pairs_among(nodes, limit=limit)
    if vp:
        meta["value_conflicts_among"] = vp
    ut = untrusted_among(nodes)
    if ut:
        meta["untrusted_among"] = ut
    return meta
