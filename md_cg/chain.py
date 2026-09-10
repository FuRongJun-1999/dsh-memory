# -*- coding: utf-8 -*-
"""关系链 / 因果链遍历：**因果链就是条件链**。

核心命题（AEIS 原始定义）：
    causal = 条件依赖因果：A 是 B 成立/运行的条件（B 依赖 A 成立）；
    方向 = 依赖方向（基础 → 应用）。
    `dex_chain` 沿 causal 边正向展开，每步标注条件，**链 = 条件序列**。

所以「检索沿关系链走」与「回答『什么条件下会发生什么』」是同一件事：
一条 causal 链就是一条「前提 → … → 结论」的条件序列，链上的每一跳都带一个条件。

对齐 AEIS 的遍历参数（不自行发明）：
- 默认 `max_depth=5`（`aeis/core.py:648,789,2070` 三处一致）
- 仅沿**出边**正向展开（依赖方向）
- `visited` 剪枝、`max_nodes` 上限、无后继即收尾
- 每步累积 `conf × edge.weight`（`aeis/prediction.py:147-210`、`wisdom/wisdom_book.py:875`）
- 边类型传播权重 base：causal 0.85 / similar 0.75 / hierarchical 0.70 /
  sequential 0.60 / spatial 0.50（`激活引擎_理论稿_v0.1.md:14`）
- 低可信关系降权不禁止（D-002 伪因果过滤门，`aeis/prediction.py:68-122`）

与 AEIS 的一处有意差异：`infer_causal_paths` 的排序键是 `(路径长度, -平均置信度)`
（`aeis/core.py:789-821`，Occam 偏好短链）；本模块默认按**累积强度**排序，因为检索
关心的是「哪条链最可信」，而非「哪条链最短」。需要对齐 AEIS 时传 `sort="length"`。
"""
from __future__ import annotations

# 边类型 → 传播权重 base（AEIS《激活引擎 v0.1》第 14 行）
EDGE_WEIGHTS = {
    "causal": 0.85,
    "similar": 0.75,
    "hierarchical": 0.70,
    "part_of": 0.70,
    "parent_of": 0.70,
    "applies_to": 0.70,
    "sequential": 0.60,
    "spatial_contains": 0.55,
    "spatial_adjacent": 0.50,
    "spatial_connected": 0.50,
    "correlational": 0.45,
    "cyclic": 0.35,
    "opposite": 0.30,
}
DEFAULT_EDGE_WEIGHT = 0.50

CAUSAL_TYPES = ("causal",)
# 检索默认沿「有语义方向」的关系走：因果 / 时序 / 条件适用
CHAIN_TYPES_DEFAULT = ("causal", "sequential", "applies_to")

MAX_DEPTH_DEFAULT = 5
MAX_DEPTH_HARD = 64
MAX_NODES_DEFAULT = 500


def edge_rel(edge):
    """取边的 relation_type（兼容 dict / 字符串两种写法），统一小写。"""
    if isinstance(edge, dict):
        rel = edge.get("relation_type") or edge.get("relation") or edge.get("type")
    else:
        rel = None
    return str(rel or "").strip().lower()


def edge_target(edge):
    """取边的目标节点 id（兼容 target / target_id / 裸字符串）。"""
    if isinstance(edge, dict):
        t = edge.get("target") or edge.get("target_id")
        return str(t).strip() if t is not None else None
    if edge is None:
        return None
    return str(edge).strip() or None


def edge_weight(edge):
    """边权重 = 类型 base × 边置信度（缺失置信度视为 1.0 的已声明边）。"""
    base = EDGE_WEIGHTS.get(edge_rel(edge), DEFAULT_EDGE_WEIGHT)
    conf = 1.0
    if isinstance(edge, dict):
        try:
            conf = float(edge.get("confidence", 1.0))
        except (TypeError, ValueError):
            conf = 1.0
    return round(base * max(0.0, min(1.0, conf)), 6)


def edge_condition(edge):
    """边的条件标注：条件链上「这一跳在什么条件下成立」。"""
    if not isinstance(edge, dict):
        return ""
    for key in ("condition", "conditions", "条件"):
        v = edge.get(key)
        if isinstance(v, (list, tuple)):
            v = "；".join(str(x) for x in v if str(x).strip())
        if v:
            return str(v).strip()
    cs = edge.get("condition_space")
    if isinstance(cs, dict):
        parts = []
        for k, v in cs.items():
            if v in (None, "", [], {}):
                continue
            parts.append(f"{k}={v}")
        return "；".join(parts)
    return ""


def node_conditions(cg, nid):
    """节点自己声明的生效条件（CCG `# 生效条件：` 等三处来源合并）。"""
    node = cg.get(nid)
    if not node:
        return []
    from .mdcos import _declared_conditions        # 懒导入，避免模块级循环依赖
    pos, _neg = _declared_conditions(node.get("frontmatter") or {},
                                     node.get("content") or "")
    return pos


def adjacency(cg, include_hierarchy=True):
    """出邻接表：nid → [(target_id, edge_dict)]。

    来源两处：
      1. 节点 frontmatter.edges（关系边，含 relation_type）
      2. 节点 frontmatter.subgraph.nodes（层级边，合成 part_of）
    只读索引快照，不读文件正文；结果缓存在 `cg._chain_adj`。
    """
    cached = getattr(cg, "_chain_adj", None)
    if cached is not None and cached[0] == bool(include_hierarchy):
        return cached[1]
    from . import subgraph as _sg
    nodes = ((getattr(cg, "index", None) or {}).get("nodes") or {})
    adj = {}
    for nid in nodes:
        fm = _sg._fm(cg, nid)
        out = []
        for e in (fm.get("edges") or []):
            tgt = edge_target(e)
            if tgt:
                out.append((tgt, e if isinstance(e, dict) else {"target": tgt}))
        if include_hierarchy:
            for ch in _sg.declared(fm)["nodes"]:
                out.append((ch, {"target": ch, "relation_type": "part_of",
                                 "confidence": 1.0, "verified": 0}))
        if out:
            adj[nid] = out
    try:
        cg._chain_adj = (bool(include_hierarchy), adj)
    except Exception:
        pass
    return adj


def invalidate_cache(cg):
    """写入/删除节点后丢弃邻接缓存（与 subgraph.invalidate_cache 成对调用）。"""
    try:
        cg._chain_adj = None
    except Exception:
        pass


def _reverse(adj):
    rev = {}
    for src, outs in adj.items():
        for tgt, e in outs:
            rev.setdefault(tgt, []).append((src, e))
    return rev


def walk(cg, start_id, relation_types=CAUSAL_TYPES, max_depth=MAX_DEPTH_DEFAULT,
         direction="out", max_nodes=MAX_NODES_DEFAULT, min_weight=0.0,
         max_chains=200, include_hierarchy=True, sort="strength"):
    """从 start_id 沿关系链展开，返回链列表（每条链 = 一段条件序列）。

    返回的每条链：
        {"start","nodes","hops","conditions","weight","depth","avg_weight"}
        hops[i] = {"from","to","relation_type","weight","condition"}
        conditions[i] = 第 i 跳的条件（边条件优先，回退起点节点声明的生效条件）
    """
    if max_depth is not None:
        max_depth = max(0, min(int(max_depth), MAX_DEPTH_HARD))
    rels = tuple(str(r).lower() for r in (relation_types or ()))
    adj = adjacency(cg, include_hierarchy=include_hierarchy)
    if direction == "in":
        adj = _reverse(adj)

    chains = []
    # 迭代 DFS：栈元素 = (当前节点, 已访问集合, hops, weight)
    stack = [(start_id, frozenset([start_id]), [], 1.0)]
    visited_nodes = 0
    while stack and len(chains) < max_chains and visited_nodes < max_nodes:
        cur, seen, hops, weight = stack.pop()
        visited_nodes += 1
        outs = adj.get(cur) or []
        extended = False
        for tgt, e in outs:
            rel = edge_rel(e)
            if rels and rel not in rels:
                continue
            if tgt in seen:
                continue
            w = edge_weight(e)
            nw = weight * w
            if nw < min_weight:
                continue
            cond = edge_condition(e)
            if not cond and not hops:          # 首跳无显式条件 → 用起点节点声明的条件
                conds = node_conditions(cg, start_id)
                cond = "；".join(conds) if conds else ""
            hop = {"from": cur, "to": tgt, "relation_type": rel,
                   "weight": w, "condition": cond}
            nhop = hops + [hop]
            if max_depth is None or len(nhop) <= max_depth:
                chains.append({
                    "start": start_id, "nodes": [start_id] + [h["to"] for h in nhop],
                    "hops": nhop,
                    "conditions": [h["condition"] for h in nhop],
                    "weight": round(nw, 6), "depth": len(nhop),
                    "avg_weight": round(nw ** (1.0 / len(nhop)), 6),
                })
            extended = True
            if max_depth is None or len(nhop) < max_depth:
                stack.append((tgt, seen | {tgt}, nhop, nw))
        if not extended and not hops:
            continue
    if sort == "length":            # 对齐 AEIS infer_causal_paths 的 Occam 偏好
        chains.sort(key=lambda c: (c["depth"], -c["avg_weight"]))
    else:
        chains.sort(key=lambda c: (-c["weight"], -c["depth"]))
    return chains[:max_chains]


def explain(cg, start_id, **kw):
    """人类可读的链式解释：「什么条件下 → 发生什么」。"""
    kw.setdefault("relation_types", CAUSAL_TYPES)
    chains = walk(cg, start_id, **kw)
    rendered = []
    for c in chains:
        steps = []
        for h in c["hops"]:
            cond = h["condition"] or "（未声明条件）"
            steps.append({"条件": cond, "关系": h["relation_type"],
                          "置信": h["weight"], "结果": h["to"]})
        rendered.append({"链": c["nodes"], "条件序列": c["conditions"],
                         "累积置信": c["weight"], "跳数": c["depth"],
                         "步骤": steps})
    return {"start": start_id, "count": len(rendered), "chains": rendered}


def expand_from_seeds(cg, seeds, relation_types=CHAIN_TYPES_DEFAULT,
                      max_depth=MAX_DEPTH_DEFAULT, decay=0.9,
                      max_nodes=MAX_NODES_DEFAULT, max_chains=500,
                      include_hierarchy=True):
    """检索用：从带分数的种子出发沿链扩散。

    `seeds`: `{node_id: score}` 或 `[(node_id, score)]`。
    每个节点保留**最强**的一条链：
        score = 种子分 × 链累积权重 × decay^跳数
    返回 `{nid: {"score","chain","depth","conditions"}}`；种子本身不在返回里。
    """
    if isinstance(seeds, dict):
        seed_items = list(seeds.items())
    else:
        seed_items = list(seeds or [])
    best = {}
    for sid, s0 in seed_items:
        if not sid:
            continue
        try:
            s0 = float(s0)
        except (TypeError, ValueError):
            continue
        for c in walk(cg, sid, relation_types=relation_types,
                      max_depth=max_depth, max_nodes=max_nodes,
                      max_chains=max_chains,
                      include_hierarchy=include_hierarchy):
            nid = c["nodes"][-1]
            if nid == sid:
                continue
            sc = s0 * c["weight"] * (decay ** c["depth"])
            cur = best.get(nid)
            if cur is None or sc > cur["score"]:
                best[nid] = {"score": round(sc, 6), "chain": c,
                             "depth": c["depth"], "conditions": c["conditions"]}
    return best
