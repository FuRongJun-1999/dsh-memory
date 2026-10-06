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

import os

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

#: 边类型集可配（P3-causal，2026-10-01）：逗号分隔，大小写不敏感。
#: 动因（设计稿 §6.2 / 交接单）——**叙事/文档语料里没有 causal 边**：按章切出来
#: 的 doc_ref 库里只有 `reference`（弱权重 0.5，上方注释明写刻意不入默认集）与
#: 父章节结构边（`part_of`）。边类型集若写死，因果路在这类库上**恒空**，等于
#: 没接。故做成 env 可配，缺省仍是 `CHAIN_TYPES_DEFAULT`（缺省行为一字不变）。
#: 约束（不得违反）：本处**只从既有 `EDGE_WEIGHTS` 里挑子集**——不新造边类型、
#: 不写第二份权重表；未登记的形态一律剔除（剔除即回落缺省，而不是按
#: `DEFAULT_EDGE_WEIGHT` 静默走一条没人登记过的边）。
#:
#: **可配面边界（P3 遗留 ④ 如实降级声明，2026-10-01）**：契约 S3 的不变量原文是
#: 「边方向/关系类型权重可配」，实测只有前一半做成了可配，后一半**不可配**：
#:   · **类型集**：可配（本 env）；
#:   · **权重**：沿用**唯一表** `EDGE_WEIGHTS`（仓内「真源唯一」纪律——禁止
#:     第二份边权表；要调权重改表，不引入第二处口径）；
#:   · **方向**：固定为**依赖方向（出边）**（`walk(direction="out")` 为缺省，
#:     `adjacency` 建的是出邻接；`direction="in"` 存在但不在检索路上用）。
#: ⇒ 对 S3 ④ 属**部分满足**，不得表述为「全满足」。
CHAIN_TYPES_ENV = "MDCG_CHAIN_TYPES"

MAX_DEPTH_DEFAULT = 5
MAX_DEPTH_HARD = 64
MAX_NODES_DEFAULT = 500


# 生效条件：environ（缺省 os.environ）里 CHAIN_TYPES_ENV 为真值时按逗号切分、逐项 strip().lower()、只保留 EDGE_WEIGHTS 里登记过的形态；结果为空（未设 / 全是不认识的名字 / 只有空项）时回落 CHAIN_TYPES_DEFAULT。返回小写元组（顺序 = env 声明序）。
def chain_types_from_env(environ=None):
    """关系链边类型集的**唯一读取点**（检索 chain 路与显式调用方共用）。

    形态与 `MDCG_SPREAD_DECAY` 同款：env 缺失 / 非法 → 回落缺省，不抛异常。
    """
    raw = (environ or os.environ).get(CHAIN_TYPES_ENV)
    if not raw:
        return CHAIN_TYPES_DEFAULT
    kept = tuple(t for t in (str(x).strip().lower() for x in str(raw).split(","))
                 if t in EDGE_WEIGHTS)
    return kept or CHAIN_TYPES_DEFAULT


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


# 生效条件：cg 已有 _chain_adj 且其 [0] 等于 bool(include_hierarchy)、[1] 等于可见性闸存在位、[2] 等于 bool(skip_archived) 时直接返回缓存的 [3]；否则以 cg.index["nodes"]（无 index 或无该键时视为无节点）逐节点收集 frontmatter.edges 中 edge_target 非空的出边（skip_archived=False 时该轮退役过滤整体旁路——维护面全量口径），include_hierarchy 为真时再为 subgraph.nodes 各合成一条 relation_type="part_of"、confidence=1.0 的层级边，仅对有出边的 nid 建表，写回 cg._chain_adj=(bool(include_hierarchy), 闸存在位, bool(skip_archived), adj) 后返回 adj；skip_archived=True（缺省）时 lifecycle.is_archived 为真的节点出边整体不入表、指向退役目标的边（含层级合成边）截断（判据单点 lifecycle.is_archived，缺键=active fail-open；退役不删除、可显式恢复）；cg 提供 _chain_visible(nid) 谓词（读隔离，MdCGSecure 注入）时不可见 nid 的出边整体不入表、指向不可见目标的边（含层级合成边）截断——不可见节点 id、其边条件与下游拓扑对调用方不存在（walk/explain/causal_path/expand_from_seeds 全部消费者同闸）；
def adjacency(cg, include_hierarchy=True, skip_archived=True):
    """出邻接表：nid → [(target_id, edge_dict)]。

    来源两处：
      1. 节点 frontmatter.edges（关系边，含 relation_type）
      2. 节点 frontmatter.subgraph.nodes（层级边，合成 part_of）

    **代价口径（P3 遗留 ⑥ 如实降级声明，2026-10-01）**：本函数**不读正文**
    （`subgraph._fm` 优先走索引快照，条目带 `subgraph` 键即零 IO），但其构建是
    **O(N) 索引条目级**——`for nid in nodes` 遍历的是**全部索引节点**
    （`cg.index["nodes"]`），不是「只碰种子邻域」。故契约 S3「不走全表」这一句
    对**本函数不成立**，正确表述是「不读正文；邻接构建为 O(N) 索引条目级」。
    代价读数（`scripts/p2p4_probe.py` R7，400 条目确定性小库）：冷建 ~0.24ms、
    缓存命中 ~1µs；缓存键 `(include_hierarchy, 闸存在位, skip_archived)` 存于
    `cg._chain_adj`，写入/删除后由 `invalidate_cache` 作废。
    （可选硬化路径 (b1)：在索引快照的**边集合**上增量构建邻接——本轮未做，
    如需做见 P3 遗留 B 的二选一。）

    只读索引快照，不读文件正文；结果缓存在 `cg._chain_adj`。

    读隔离（2026-09-25）：cg._chain_visible(nid) 谓词在位（MdCGSecure 注入，
    = 索引有条目 ∧ _readable）时按其过滤——不可见节点不入表、指向不可见
    目标的边截断；谓词缺席（基类）行为零变化。缓存键含闸存在位；闸语义
    实例内稳定（_readable 绑定档判定恒用 principal.session，见 mdcos
    _readable），同一实例不会跨身份串台。

    退役纪律（《秤》v2.1 §5.2；2026-10-06 接线）：`skip_archived=True`（缺省）时
    archived 节点出边整体不入表、指向 archived 目标的边截断——`cg(op=causal,
    action=chain)` 等**读/预测面**（chain()／predict.*）由此不再扩散进退役节点；
    **维护面显式旁路**：`scrub`（去污染抽查，按度数排序的维护写面）传
    `skip_archived=False` 取全量表——退役节点仍可被抽查（判据面 = 默认读/注入
    面必消费、维护/管理面直读，见运维文档 §九.5 面的判据）。判据单点
    `lifecycle.is_archived`（缺键=active fail-open）。
    """
    cached = getattr(cg, "_chain_adj", None)
    vis = getattr(cg, "_chain_visible", None)
    vis_on = vis is not None
    if (cached is not None and cached[0] == bool(include_hierarchy)
            and cached[1] == vis_on
            and cached[2] == bool(skip_archived)):
        return cached[3]
    from . import subgraph as _sg
    from . import lifecycle as _lc
    nodes = ((getattr(cg, "index", None) or {}).get("nodes") or {})
    adj = {}
    for nid in list(nodes):
        if skip_archived and _lc.is_archived(nodes.get(nid)):
            continue          # 退役节点：其出边与条件整体不入表（不解析 fm）
        if vis is not None and not vis(nid):
            continue          # 不可见节点：其出边与条件整体不可见（不解析 fm）
        fm = _sg._fm(cg, nid)
        out = []
        for e in (fm.get("edges") or []):
            tgt = edge_target(e)
            if tgt:
                if skip_archived and _lc.is_archived(nodes.get(tgt)):
                    continue  # 拓扑边界：指向退役目标的边径直截断
                if vis is not None and not vis(tgt):
                    continue  # 拓扑边界：指向不可见目标的边对调用方不存在
                out.append((tgt, e if isinstance(e, dict) else {"target": tgt}))
        if include_hierarchy:
            for ch in _sg.declared(fm)["nodes"]:
                if skip_archived and _lc.is_archived(nodes.get(ch)):
                    continue
                if vis is not None and not vis(ch):
                    continue
                out.append((ch, {"target": ch, "relation_type": "part_of",
                                 "confidence": 1.0, "verified": 0}))
        if out:
            adj[nid] = out
    try:
        cg._chain_adj = (bool(include_hierarchy), vis_on, bool(skip_archived), adj)
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