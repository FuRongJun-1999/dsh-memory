# -*- coding: utf-8 -*-
"""记忆评审流水线 · 级 2：捆绑（确定性，零写入）。

真源：docs/记忆评审系统_立项设计与施工交接_20260915.md §3 第 2 级。

**同模板组一包一评**：批次报告类节点（「批次N收官记忆」）正文各不相同但同模板，
逐条评审＝重复劳动且立场漂移；成组评审＝一次裁决整组。分组键优先级：

1. ``template`` 模板签名——复用 :func:`writelimit.template_signature`（强信号 ``t:``）；
   长文（≥ MAX_CONTENT）无标题签名时回退**首行骨架**（弱信号 ``h:``）——真源知识节点
   正文多为长文四要素，标题/首行才是同模板流水的载体（该回退只在评审分组内生效，
   不改写侧聚合口径）。
2. ``lineage``  血缘——branch_id / branched_from / derived_from[0]（同源迁移一起看）。
3. ``topic``    标签前缀集合（无标签回退层）。
4. ``batch``    无任何分组特征的孤立候选，按确定性顺序成批（不误聚、不丢弃）。

组内条数 < ``min_group`` 的组降级并入 batch；组内超 ``max_per_bundle`` 切分多包。
包号确定性：``b1_<kind>_<sha1(key)[:8]>_c<idx>``；同一输入两次运行逐字节一致。
"""
from __future__ import annotations

import collections
import hashlib
import os

from .. import conformance as CF
from .. import writelimit as WL

GROUP_TEMPLATE = "template"
GROUP_LINEAGE = "lineage"
GROUP_TOPIC = "topic"
GROUP_BATCH = "batch"


# 生效条件：content 为假值（如空串）时返回 (None, None)；content 为真且 WL.template_signature(content) 返回真值时返回 (s, 'strong')；否则遍历 content.splitlines() 中 strip 后非空的行，遇首个非空行时其 WL._skeleton 长度 ≥ WL.MIN_SKELETON 则返回 ('h:' + sk, 'head')，否则立即返回 (None, None)（不再看后续行），无任何非空行时也返回 (None, None)；
def _sig_of(content: str):
    """模板签名（强/弱）。返回 (sig, kind) 或 (None, None)。"""
    if not content:
        return None, None
    s = WL.template_signature(content)
    if s:
        return s, "strong"
    for line in content.splitlines():
        t = line.strip()
        if not t:
            continue
        sk = WL._skeleton(t)
        if len(sk) >= WL.MIN_SKELETON:
            return "h:" + sk, "head"
        return None, None
    return None, None


# 生效条件：meta（dict）中按 ("branched_from", "branch_id") 顺序取到的首个 v 为真且 str(v) != 'None' 时返回 str(v)；否则 meta.get('derived_from') 为 list/tuple 且非空时返回 str(d[0])；否则其为非空 str 且不等于 '[]' 与 'None' 时返回该 str 本身；以上皆不成立时返回 None；
def _lineage_key(meta: dict):
    for f in ("branched_from", "branch_id"):
        v = meta.get(f)
        if v and str(v) != "None":
            return str(v)
    d = meta.get("derived_from")
    if isinstance(d, (list, tuple)) and d:
        return str(d[0])
    if isinstance(d, str) and d and d not in ("[]", "None"):
        return d
    return None


# 生效条件：meta 为真时先取 sorted(CF._tag_prefixes(meta)) 作为 pref，pref 为空且 tags 有真值元素时改用各 tag 的 str(t).split(':', 1)[0]（跳过假值 tag）集合排序；pref 非空返回 '+'.join(pref)；pref 为空时取 str((meta or {}).get('layer') or '')，该层名非空返回 'layer:' + layer，层名为假值（None/空串/0）则返回 None；
def _topic_key(meta: dict, tags: list):
    pref = sorted(CF._tag_prefixes(meta)) if meta else []
    if not pref and tags:
        pref = sorted({str(t).split(":", 1)[0] for t in tags if t})
    if pref:
        return "+".join(pref)
    layer = str((meta or {}).get("layer") or "")
    return ("layer:" + layer) if layer else None


# 生效条件：content 经 _sig_of 得到的 sig 为真时返回 (GROUP_TEMPLATE, sig, kind)；否则 meta 经 _lineage_key 得到的值非空时返回 (GROUP_LINEAGE, lin, None)；否则 (meta, tags) 经 _topic_key 得到的值非空时返回 (GROUP_TOPIC, top, None)；三者皆不成立时返回 (GROUP_BATCH, 'misc', None)；
def _group_of(meta: dict, tags: list, content: str):
    sig, kind = _sig_of(content)
    if sig:
        return GROUP_TEMPLATE, sig, kind
    lin = _lineage_key(meta)
    if lin:
        return GROUP_LINEAGE, lin, None
    top = _topic_key(meta, tags)
    if top:
        return GROUP_TOPIC, top, None
    return GROUP_BATCH, "misc", None


# 生效条件：root 与 meta 均为真、且 meta.get('path') 经 or '' 再 str 后为非空路径时，把 rel 中的 '\\' 与 '/' 替换为 os.sep 并与 root 拼接，以 encoding='utf-8'、errors='replace' 打开并返回 f.read(int(limit))（limit 为 0 时读 0 字节）；root 或 meta 为假值、rel 为空、或该打开/读取抛 OSError 时返回 None；
def _load_content(root: str, meta: dict, limit: int):
    if not root or not meta:
        return None
    rel = str(meta.get("path") or "")
    if not rel:
        return None
    p = os.path.join(root, rel.replace("\\", os.sep).replace("/", os.sep))
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read(int(limit))
    except OSError:
        return None


# 生效条件：恒返回构造 dict——ref/node_id/proposal_id/origin/layer/role/importance/evidence_count/verification_basis/lifecycle_state 均以 .get 取值（缺键得 None），content_hash 先取 cand.get('content_hash') 为空再取 (meta or {}).get('content_hash')，tags/issue_kinds/evidence 经 or [] 后 list 化，excerpt 取 (content or '')[:int(limit)] 为空时（含 content 为空串或 limit 为 0）为 None；
def _entry(cand: dict, meta: dict, content: str, limit: int) -> dict:
    return {"ref": cand.get("key"), "node_id": cand.get("node_id"),
            "proposal_id": cand.get("proposal_id"), "origin": cand.get("origin"),
            "layer": cand.get("layer"), "tags": list(cand.get("tags") or []),
            "role": (meta or {}).get("role"),
            "importance": (meta or {}).get("importance"),
            "evidence_count": (meta or {}).get("evidence_count"),
            "verification_basis": (meta or {}).get("verification_basis"),
            "lifecycle_state": (meta or {}).get("lifecycle_state"),
            "content_hash": cand.get("content_hash") or (meta or {}).get("content_hash"),
            "issue_kinds": list(cand.get("issue_kinds") or []),
            "evidence": list(cand.get("evidence") or []),
            "excerpt": (content or "")[:int(limit)] or None}


# 生效条件：ids 与 size 为必需形参，size 先经 max(1, int(size))（0、负值或 1 均按 1）作为步长，返回 [ids[i:i + size] for i in range(0, len(ids), size)]；ids 为空（如 [] 或空串）时返回 []；
def _chunks(ids: list, size: int) -> list:
    size = max(1, int(size))
    return [ids[i:i + size] for i in range(0, len(ids), size)]


# 生效条件：candidates（list）为必需输入，nodes 为假值时按 {} 取节点表；逐候选以 c.get('node_id') 查 meta（无 node_id 则 meta 为 {}）、以 c.get('content') or '' 取内容，内容为空且 read_content 为真且 nid 为真时改用 _load_content(root, meta, content_limit) 的结果（再 or ''），并按 int(content_limit) 截断；随后按 _group_of(meta, c.get('tags') or [], content) 分组，非 GROUP_BATCH 且组内 id 数 < int(min_group)（min_group 为 0 时该比较恒不成立，即无降级）的组与既有 GROUP_BATCH 组一并降级，降级集合非空时并入 (GROUP_BATCH, 'misc')、为空则不建该组；再对每组按 int(max_per_bundle) 经 _chunks 切块生成带 entries 的 bundles 与 stats，返回 content_missing 为 contents 中该候选键对应值为假值的候选数；
def bundle(candidates: list, nodes=None, root=None, *, max_per_bundle=50,
           min_group=2, read_content=True, content_limit=3000) -> dict:
    """候选清单 → 待评包（含条目上下文与机械字段，供级 3 装配与级 4 spec）。"""
    nodes = nodes or {}
    bykey = {c.get("key"): c for c in candidates}
    groups, contents = {}, {}
    for c in candidates:
        nid = c.get("node_id")
        meta = (nodes.get(nid) or {}) if nid else {}
        content = c.get("content") or ""
        if not content and read_content and nid:
            content = _load_content(root, meta, content_limit) or ""
        content = (content or "")[:int(content_limit)]
        kind, key, sig_kind = _group_of(meta, c.get("tags") or [], content)
        g = groups.get((kind, key))
        if g is None:
            g = groups[(kind, key)] = {"ids": [], "sig_kind": sig_kind}
        g["ids"].append(c.get("key"))
        contents[c.get("key")] = content

    # 小组降级并入 batch（不误聚、不丢弃）
    demoted = []
    for k in [k for k, g in groups.items()
              if k[0] != GROUP_BATCH and len(g["ids"]) < int(min_group)]:
        demoted += groups.pop(k)["ids"]
    for k in [k for k in groups if k[0] == GROUP_BATCH]:
        demoted += groups.pop(k)["ids"]
    demoted = sorted(demoted)
    if demoted:
        groups[(GROUP_BATCH, "misc")] = {"ids": demoted, "sig_kind": None}

    bundles = []
    for (kind, key) in sorted(groups):
        g = groups[(kind, key)]
        for i, chunk in enumerate(_chunks(sorted(g["ids"]), int(max_per_bundle))):
            bid = "b1_%s_%s_c%d" % (kind, hashlib.sha1(str(key).encode("utf-8")).hexdigest()[:8], i)
            bundles.append({
                "bundle_id": bid, "group_kind": kind, "group_key": str(key),
                "group_sig_kind": g["sig_kind"], "size": len(chunk), "refs": chunk,
                "entries": [_entry(bykey[r], nodes.get(bykey[r].get("node_id") or "") or {},
                                   contents.get(r) or "", content_limit)
                            for r in chunk]})
    stats = {"candidates": len(candidates), "bundles": len(bundles),
             "largest": max([b["size"] for b in bundles] or [0]),
             "by_group_kind": dict(collections.Counter(b["group_kind"] for b in bundles))}
    return {"bundles": bundles, "stats": stats,
            "content_missing": sum(1 for c in candidates
                                   if not contents.get(c.get("key")))}
