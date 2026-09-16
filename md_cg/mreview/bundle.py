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


def _topic_key(meta: dict, tags: list):
    pref = sorted(CF._tag_prefixes(meta)) if meta else []
    if not pref and tags:
        pref = sorted({str(t).split(":", 1)[0] for t in tags if t})
    if pref:
        return "+".join(pref)
    layer = str((meta or {}).get("layer") or "")
    return ("layer:" + layer) if layer else None


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


def _chunks(ids: list, size: int) -> list:
    size = max(1, int(size))
    return [ids[i:i + size] for i in range(0, len(ids), size)]


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
