# -*- coding: utf-8 -*-
"""嵌套子图（nested subgraph）：结构要素的可递归表示 + flatten。

对齐 AEIS《认知图写入纪律 v1.0》四要素中的第三项：
    subgraph = 内部子内容（可嵌套：子节点 + 边），角色＝结构（可检索/可递归）。

与 AEIS 的两处**有意差异**（都有工程理由，不是简化）：

1) 存储形态：AEIS 把子节点**内联**在父节点 `subgraph.nodes` 里
   （`aeis/image_semantics_cg.py:37-57`）。md_cg 的检索粒度是「节点 = 文件」
   （RRF 按节点召回），内联子节点无法被任何检索路单独命中，会违背「子图可检索」
   这一规范本身。故 md_cg 采用**引用式**：`subgraph.nodes` 存子节点 id，
   子节点各自是独立 `.md`，可被 lexical/entity/chain 等路独立召回。
   同时兼容内联写法（`{"id": ...}` 对象）以承接 AEIS 语料。

2) 递归深度：AEIS 明确「深度上限不是协议常数，数据驱动，= 可分性条件的自然耗尽」
   （`子部件提取_理论稿_v0.4.md:146-150`）。故 `max_depth=None` 表示一直展开到
   自然耗尽（无子节点）；`max_depth=k` 只是工程硬截断，会置 `truncated=True`。

父边唯一（每个节点至多一个 `part_of` 父）——`子部件提取_理论稿_v0.4.md:105`；
违反者由 `validate()` 报 `multi_parent`，对齐「树形不一致 → 退回 DEFER」。
"""
from __future__ import annotations

MAX_DEPTH_HARD = 64          # 工程硬截断上限（防止畸形数据把遍历拖爆）
MAX_NODES_DEFAULT = 2000     # 单次展开的节点上限


def declared(fm):
    """规范化 `frontmatter.subgraph` → `{"nodes": [id...], "edges": [edge...]}`。

    兼容三种写法：
        {"nodes": ["a", "b"], "edges": [...]}     引用式（md_cg 主用）
        ["a", "b"]                                纯 id 列表
        {"nodes": [{"id": "a"}, ...]}             内联式（AEIS 原样，只取 id）
    """
    sg = (fm or {}).get("subgraph")
    if not sg:
        return {"nodes": [], "edges": []}
    if isinstance(sg, (list, tuple)):
        raw_nodes, raw_edges = list(sg), []
    elif isinstance(sg, dict):
        raw_nodes, raw_edges = list(sg.get("nodes") or []), list(sg.get("edges") or [])
    else:
        return {"nodes": [], "edges": []}
    nodes = []
    for n in raw_nodes:
        nid = n.get("id") if isinstance(n, dict) else n
        if nid is None:
            continue
        nid = str(nid).strip()
        if nid and nid not in nodes:
            nodes.append(nid)
    return {"nodes": nodes, "edges": [e for e in raw_edges if isinstance(e, dict)]}


def _fm(cg, nid):
    """取节点 frontmatter：优先索引快照（免 IO），快照缺字段时回退读文件。"""
    entry = ((getattr(cg, "index", None) or {}).get("nodes") or {}).get(nid)
    if entry is not None and "subgraph" in entry:
        return {"id": nid, "subgraph": entry.get("subgraph"),
                "edges": entry.get("edges") or []}
    node = cg.get(nid)
    return (node or {}).get("frontmatter") or {}


def children_index(cg):
    """全局正查：parent_id → [child_id...]（声明式 ∪ 边式，一次 O(N) 后缓存）。"""
    idx = getattr(cg, "_subgraph_children", None)
    if idx is not None:
        return idx
    idx = {}
    for pid in list(((getattr(cg, "index", None) or {}).get("nodes") or {}).keys()):
        fm = _fm(cg, pid)
        for ch in declared(fm)["nodes"]:
            idx.setdefault(pid, [])
            if ch not in idx[pid]:
                idx[pid].append(ch)
        for e in (fm.get("edges") or []):
            if not isinstance(e, dict):
                continue
            rel = str(e.get("relation_type") or e.get("relation") or "").strip().lower()
            tgt = e.get("target") or e.get("target_id")
            if tgt is None:
                continue
            tgt = str(tgt).strip()
            if rel in ("part_of", "hierarchical"):      # 本节点是子，target 是父
                idx.setdefault(tgt, [])
                if pid not in idx[tgt]:
                    idx[tgt].append(pid)
            elif rel in ("parent_of", "contains"):      # 本节点是父，target 是子
                idx.setdefault(pid, [])
                if tgt not in idx[pid]:
                    idx[pid].append(tgt)
    try:
        cg._subgraph_children = idx
    except Exception:
        pass
    return idx


def children(cg, nid):
    """直接子节点 id 列表：`subgraph.nodes` 声明 ∪ 边式父子关系。"""
    return list(children_index(cg).get(nid) or [])


def parents_index(cg):
    """全局反查：child_id → [parent_id...]（供 children/validate 复用，一次 O(N)）。"""
    idx = getattr(cg, "_subgraph_parents", None)
    if idx is not None:
        return idx
    idx = {}
    for pid in list(((getattr(cg, "index", None) or {}).get("nodes") or {}).keys()):
        for ch in declared(_fm(cg, pid))["nodes"]:
            idx.setdefault(ch, [])
            if pid not in idx[ch]:
                idx[ch].append(pid)
        for e in (_fm(cg, pid).get("edges") or []):
            if not isinstance(e, dict):
                continue
            rel = str(e.get("relation_type") or "").lower()
            if rel in ("part_of", "contains", "hierarchical") and e.get("target"):
                tgt = str(e["target"])
                idx.setdefault(tgt, [])
                if pid not in idx[tgt]:
                    idx[tgt].append(pid)
    try:
        cg._subgraph_parents = idx
    except Exception:
        pass
    return idx


def invalidate_cache(cg):
    """写入/删除节点后调用，丢弃父子正查/反查缓存。"""
    for attr in ("_subgraph_parents", "_subgraph_children"):
        try:
            setattr(cg, attr, None)
        except Exception:
            pass


def parent_of(cg, nid):
    """唯一父（多父时返回第一个并置 `ambiguous` 标记由 validate 报出）。"""
    ps = parents_index(cg).get(nid) or []
    return ps[0] if ps else None


def expand(cg, nid, max_depth=None, max_nodes=MAX_NODES_DEFAULT):
    """递归展开子树（迭代 DFS，防递归深度爆栈）。

    返回 `{"root","nodes","paths","edges","n_nodes","n_edges","truncated"}`；
    `paths` 为 `节点 id → "根/子/孙"` 层级路径（flatten 后仍可定位来源）。
    边为 `part_of(child→parent)`，与 AEIS flatten 的方向一致。
    """
    if max_depth is not None:
        max_depth = max(0, min(int(max_depth), MAX_DEPTH_HARD))
    seen, edges, truncated = {}, [], False
    seen_edges = set()
    stack = [(nid, 0, nid)]
    while stack:
        cur, depth, path = stack.pop()
        if cur in seen:
            continue
        if len(seen) >= max_nodes:
            truncated = True
            break
        seen[cur] = path
        if max_depth is not None and depth >= max_depth:
            if children(cg, cur):
                truncated = True
            continue
        kids = children(cg, cur)
        for ch in reversed(kids):
            key = (ch, cur)
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append({"source": ch, "target": cur,
                              "relation_type": "part_of",
                              "confidence": 1.0, "verified": 0})
            if ch not in seen:
                stack.append((ch, depth + 1, f"{path}/{ch}"))
    return {"root": nid, "nodes": list(seen.keys()), "paths": seen,
            "edges": edges, "n_nodes": len(seen), "n_edges": len(edges),
            "truncated": truncated}


def flatten(cg, nid, max_depth=None, max_nodes=MAX_NODES_DEFAULT):
    """把嵌套子图摊平成「节点 + 边」，父子生成**对称双边**。

    对齐 AEIS `flatten_image_semantics_graph`（`image_semantics_cg.py:151-173`）：
    每个有父的节点同时产出 `part_of(child→parent)` 与 `parent_of(parent→child)`。
    检索侧因此既能「从父找子」（下钻），也能「从子找父」（溯源）。
    """
    ex = expand(cg, nid, max_depth=max_depth, max_nodes=max_nodes)
    edges = []
    for e in ex["edges"]:
        edges.append(dict(e))
        edges.append({"source": e["target"], "target": e["source"],
                      "relation_type": "parent_of",
                      "confidence": e.get("confidence", 1.0),
                      "verified": e.get("verified", 0)})
    return {"root": nid, "nodes": ex["nodes"], "edges": edges, "paths": ex["paths"],
            "n_nodes": ex["n_nodes"], "n_edges": len(edges),
            "truncated": ex["truncated"]}


def roots(cg):
    """无父节点（树根）的 id 列表。"""
    known = set(((getattr(cg, "index", None) or {}).get("nodes") or {}).keys())
    pmap = parents_index(cg)
    return sorted(nid for nid in known if not (pmap.get(nid) or []))


def validate(cg, limit=50, max_scan=None):
    """树一致性校验：自环 / 悬空子节点 / 多父 / 环。

    对齐 AEIS：父边唯一、拓扑无矛盾、树形不一致 → 该层判定退回 DEFER
    （`子部件提取_理论稿_v0.4.md:105-107`）。
    """
    known = list(((getattr(cg, "index", None) or {}).get("nodes") or {}).keys())
    if max_scan:
        known = known[:int(max_scan)]
    known_set = set(known)
    parent, issues = {}, []

    def _issue(**kw):
        if len(issues) < limit * 4:
            issues.append(kw)

    for pid in known:
        for ch in declared(_fm(cg, pid))["nodes"]:
            if ch == pid:
                _issue(id=pid, issue="self_loop", child=ch)
                continue
            if ch not in known_set:
                _issue(id=pid, issue="dangling_child", child=ch)
            prev = parent.get(ch)
            if prev is not None and prev != pid:
                _issue(id=ch, issue="multi_parent", parents=sorted({prev, pid}))
            else:
                parent[ch] = pid

    # 环检测：沿 parent 指针上溯，遇本路径已访问节点即成环
    for nid in known:
        path, cur = [], nid
        while cur is not None:
            if cur in path:
                _issue(id=cur, issue="cycle", path=path[path.index(cur):] + [cur])
                break
            path.append(cur)
            cur = parent.get(cur)

    return {"scanned": len(known), "issues": len(issues),
            "items": issues[:limit], "truncated": len(issues) > limit}
