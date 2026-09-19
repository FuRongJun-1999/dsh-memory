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
    # 正文引用边（linkref，写入侧自动解析，2026-09-17）：取弱权重——正文提及
    # ≠ 语义相似 ≠ 因果依赖，故与 DEFAULT_EDGE_WEIGHT 同值；显式登记的意义在
    # 「类型已知」（可审计、可按类型调参、可区分于未登记类型的兜底默认）。
    "reference": 0.50,
}
DEFAULT_EDGE_WEIGHT = 0.50

CAUSAL_TYPES = ("causal",)
# 检索默认沿「有语义方向」的关系走：因果 / 时序 / 条件适用
# 注：reference **刻意不入**——正文提及不应进入「前提→结论」条件序列遍历，
# 否则 causal 链会被「提到过」这类无向弱关联稀释（模式分离）。
CHAIN_TYPES_DEFAULT = ("causal", "sequential", "applies_to")

MAX_DEPTH_DEFAULT = 5
MAX_DEPTH_HARD = 64
MAX_NODES_DEFAULT = 500


# 生效条件：edge 为 dict 时按 relation_type→relation→type 顺序取首个真值、非 dict 时 rel 记为 None，两者统一返回 str(rel or "").strip().lower()——键缺失或全为假值时得空串。
def edge_rel(edge):
    """取边的 relation_type（兼容 dict / 字符串两种写法），统一小写。"""
    if isinstance(edge, dict):
        rel = edge.get("relation_type") or edge.get("relation") or edge.get("type")
    else:
        rel = None
    return str(rel or "").strip().lower()


# 生效条件：edge 为 dict 时取 target or target_id（前者假值回落后者），该值非 None 则返回其 str().strip()、为 None 返回 None；edge is None 返回 None；其余（裸字符串等）返回 str(edge).strip() 或空白串时 None。
def edge_target(edge):
    """取边的目标节点 id（兼容 target / target_id / 裸字符串）。"""
    if isinstance(edge, dict):
        t = edge.get("target") or edge.get("target_id")
        return str(t).strip() if t is not None else None
    if edge is None:
        return None
    return str(edge).strip() or None


# 生效条件：base 取 EDGE_WEIGHTS.get(edge_rel(edge), DEFAULT_EDGE_WEIGHT)；edge 为 dict 时 conf 为 float(edge.get("confidence", 1.0))（缺该键得 1.0，值不可转 float 如 None 触发 TypeError/ValueError 时也回落 1.0），非 dict 时 conf 恒为 1.0，返回 round(base * max(0.0, min(1.0, conf)), 6)；
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


# 生效条件：edge 非 dict 时返回 ""；edge 为 dict 时按 ("condition","conditions","条件") 顺序取第一个真值（list/tuple 先以 "；" 连接其中 str(x).strip() 非空的项，连接结果为空则视为假值跳过该键）并返回 str(v).strip()；三键均无真值且 edge.get("condition_space") 为 dict 时返回 condition_space_text(cs, require_full=False)；否则返回 ""；
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
        # 与生效条件**共用同一个**合成入口（缺失槽不写）——杜绝第二套拼法：
        # 旧版在此拼 "k=v；k=v"，与 nodefile 的声明口径各说各话。
        from .nodefile import condition_space_text    # 懒导入，避免循环依赖
        return condition_space_text(cs, require_full=False)
    return ""


# 生效条件：cg.get(nid) 为假值（该节点缺失或为空）时返回 []；否则以 node.get("frontmatter") or {} 与 node.get("content") or "" 调 _declared_conditions，返回其正向条件列表 pos；
def node_conditions(cg, nid):
    """节点自己声明的生效条件（CCG `# 生效条件：` 等三处来源合并）。"""
    node = cg.get(nid)
    if not node:
        return []
    from .mdcos import _declared_conditions        # 懒导入，避免模块级循环依赖
    pos, _neg = _declared_conditions(node.get("frontmatter") or {},
                                     node.get("content") or "")
    return pos


# 生效条件：cg 已有 _chain_adj 且其 [0] 等于 bool(include_hierarchy) 时直接返回缓存的 [1]；否则以 cg.index["nodes"]（无 index 或无该键时视为无节点）逐节点收集 frontmatter.edges 中 edge_target 非空的出边，include_hierarchy 为真时再为 subgraph.nodes 各合成一条 relation_type="part_of"、confidence=1.0 的层级边，仅对有出边的 nid 建表，写回 cg._chain_adj=(bool(include_hierarchy), adj) 后返回 adj；
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


# 生效条件：调用即把 cg._chain_adj 置为 None（赋值抛异常时静默忽略），无返回值；
def invalidate_cache(cg):
    """写入/删除节点后丢弃邻接缓存（与 subgraph.invalidate_cache 成对调用）。"""
    try:
        cg._chain_adj = None
    except Exception:
        pass


# 生效条件：对 adj 的每个 src→[(tgt, e)] 逐条把 (src, e) 追加到 rev[tgt]（同 tgt 多次追加保持出现顺序），adj 为空字典时 rev 为空字典并返回；
def _reverse(adj):
    rev = {}
    for src, outs in adj.items():
        for tgt, e in outs:
            rev.setdefault(tgt, []).append((src, e))
    return rev


# 生效条件：start_id 起步迭代 DFS——max_depth 非 None 时先钳为 max(0, min(int(max_depth), MAX_DEPTH_HARD))，rels 为 (relation_types or ()) 的小写元组（None 或空则不作类型过滤），direction=="in" 时邻接表改用 _reverse(adjacency(cg, include_hierarchy))，每跳要求 rel∈rels（rels 非空时）、tgt 不在 seen、weight*edge_weight(e) ≥ min_weight，链在 max_depth 为 None 或 len(hops+[hop]) ≤ max_depth 时收入、在 max_depth 为 None 或 len(hops+[hop]) < max_depth 时继续下探，首跳且边无显式条件时条件回退 start_id 的 node_conditions，扩展节点数受 max_nodes、收链数受 max_chains 限制，sort=="length" 时按 (depth, -avg_weight) 排序否则按 (-weight, -depth) 排序，返回 chains[:max_chains]；
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
    # 终键 tuple(nodes)：图遍历序取决于邻接结构的枚举序，并列（同 depth/
    # weight/avg_weight）时若无终键，截断结果随索引构建路径漂移。
    if sort == "length":            # 对齐 AEIS infer_causal_paths 的 Occam 偏好
        chains.sort(key=lambda c: (c["depth"], -c["avg_weight"],
                                   tuple(c["nodes"])))
    else:
        chains.sort(key=lambda c: (-c["weight"], -c["depth"],
                                   tuple(c["nodes"])))
    return chains[:max_chains]


# 生效条件：kw 未含 relation_types 时先注入 CAUSAL_TYPES，再以 walk(cg, start_id, **kw) 的每条链逐跳渲染（跳条件为空串则显示「（未声明条件）」），返回 {"start": start_id, "count": 渲染链数, "chains": rendered}；
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


# 生效条件：seeds 为 dict 时取其 items、否则取 list(seeds or [])（假值 seeds 得空列表，返回空 best），逐 (sid, s0) 跳过 sid 为假值或 float(s0) 抛 TypeError/ValueError 的项，对 walk(cg, sid, relation_types, max_depth, max_nodes, max_chains, include_hierarchy) 每条链取 nodes[-1] 为 nid（nid==sid 则跳过）并按 s0*链 weight*decay^depth 对每个 nid 只保留最高分，返回 best；
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