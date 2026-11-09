# -*- coding: utf-8 -*-
"""conflict_surface · 检索结果内的「显式矛盾对」暴露（红队缺口 B/C）

判据只收能给出证据的一类矛盾：

    A 的 non_applicable_conditions（**整条**文本，长度 >= MIN_EVIDENCE）
    作为连续子串出现在 B 的正文里 ⇒ A 排除了 B 所述情形（双向都查）。

边界（经反思单元审计后收窄，见 PR 讨论）：
  · 只比正文，不比声明面（B 的 negs 在反向检查里作为 A 的角色参与）；
  · 节点缺 id 时按**序号**区分，不因空串相等而整对跳过；
  · 三类信号各自有上限，输出体积有界；
  · 启发式（value_conflict 的正则退路）默认关，须显式 allow_heuristic=True。

纪律对齐：第 4 条（只报能给出证据的）、第 5 条（无证据即不报）。
"""
from __future__ import annotations

from . import untrusted as _ut
from . import value_conflict as _vc

MIN_EVIDENCE = 4          # 证据子串最短长度（防单字噪声）
MAX_PAIRS = 5             # 每类信号单次最多报几条


def _norm(text) -> str:
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


def _items(nodes):
    """[(key, id, negs, body)]；id 缺失时用序号补齐键，避免空串互撞。"""
    out = []
    for i, n in enumerate(nodes or []):
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id") or "")
        out.append(("#%d" % i, nid, _neg_texts(n.get("frontmatter")), _norm(n.get("content"))))
    return out


def conflicts_among(nodes, limit: int = MAX_PAIRS) -> list:
    """双向查「A 的 neg 出现在 B 正文」；返回 [{a,b,evidence,kind}]。

    只在 i<j 的组合上做两个方向，避免 (A,B) 与 (B,A) 两条循环把同一对报两遍。
    """
    items = _items(nodes)
    pairs = []
    for i in range(len(items)):
        _ka, a_id, a_negs, a_body = items[i]
        for j in range(i + 1, len(items)):
            _kb, b_id, b_negs, b_body = items[j]
            if b_body:
                for neg in a_negs:
                    if neg in b_body:
                        pairs.append({"a": a_id, "b": b_id, "evidence": neg,
                                      "kind": "a_neg_in_b_body"})
                        break
            if a_body:
                for neg in b_negs:
                    if neg in a_body:
                        pairs.append({"a": b_id, "b": a_id, "evidence": neg,
                                      "kind": "b_neg_in_a_body"})
                        break
            if len(pairs) >= limit:
                return pairs
    return pairs


def value_pairs_among(nodes, limit: int = MAX_PAIRS, allow_heuristic: bool = False) -> list:
    """同 condition_space 下同名键不同值（默认只认声明面 value_slots）。"""
    items = []
    for i, n in enumerate(nodes or []):
        if isinstance(n, dict):
            items.append((str(n.get("id") or ""), n.get("frontmatter") or {}, _norm(n.get("content"))))
    out = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a_id, a_fm, a_body = items[i]
            b_id, b_fm, b_body = items[j]
            hit = _vc.compare(a_fm, a_body, b_fm, b_body, allow_heuristic=allow_heuristic)
            if hit:
                hit["a"], hit["b"] = a_id, b_id
                out.append(hit)
            if len(out) >= limit:
                return out
    return out


def untrusted_among(nodes, limit: int = MAX_PAIRS) -> list:
    """检索结果里命中「伪装系统消息/指令式」的节点（只报案，不改内容）。"""
    out = []
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        r = _ut.classify(n.get("content"))
        if r.get("untrusted"):
            out.append({"id": str(n.get("id") or ""), "markers": r.get("markers")})
        if len(out) >= limit:
            break
    return out


def as_meta(nodes, limit: int = MAX_PAIRS, allow_heuristic: bool = False) -> dict:
    """把三类信号包成可直接并进 meta 的字典（空则不产生键；三类各自有上限）。"""
    meta = {}
    pairs = conflicts_among(nodes, limit=limit)
    if pairs:
        meta["conflicts_among"] = pairs
    vp = value_pairs_among(nodes, limit=limit, allow_heuristic=allow_heuristic)
    if vp:
        meta["value_conflicts_among"] = vp
    ut = untrusted_among(nodes, limit=limit)
    if ut:
        meta["untrusted_among"] = ut
    return meta
