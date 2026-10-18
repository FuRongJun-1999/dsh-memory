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

import hashlib
import os
import re
import time
from collections import deque

from .fsutil import append_jsonl

MAX_DEPTH_HARD = 64          # 工程硬截断上限（防止畸形数据把遍历拖爆）
MAX_NODES_DEFAULT = 2000     # 单次展开的节点上限

# ---- 模式分离（maintain.separate）参数 -----------------------------------
MAINTAIN_LOG = "_maintain.jsonl"
SEP_MIN_JACCARD = 0.55       # 内容相似度下限（越高＝越像，才值得谈分离）
SEP_MAX_COND_OVERLAP = 0.35  # 条件重合上限（越高＝条件越同，就该合并而非分离）
SEP_MAX_NODES = 400          # 单次扫描节点上限（防 O(N²) 读盘爆炸）
SEP_MAX_PAIRS = 50           # 单次返回/落库的候选对上限


# 生效条件：fm 为假值或 fm.get("subgraph") 取值为假（None/[]/{}/空串）时直接返回 {'nodes': [], 'edges': []}；subgraph 为 list/tuple 时其元素作节点、边记空列表，为 dict 时节点取 sg.get("nodes")（缺键或假值回落 []）、边取 sg.get("edges")（同样回落），为其他类型仍返回空；节点项为 dict 时取 n.get("id")、否则取元素本身，nid 为 None 跳过，仅当 str(nid).strip() 非空且未出现过才追加；边只保留 isinstance(e, dict) 的项；
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
    nodes, seen = [], set()
    for n in raw_nodes:
        nid = n.get("id") if isinstance(n, dict) else n
        if nid is None:
            continue
        nid = str(nid).strip()
        if nid and nid not in seen:
            seen.add(nid)
            nodes.append(nid)
    return {"nodes": nodes, "edges": [e for e in raw_edges if isinstance(e, dict)]}


# 生效条件：当 getattr(cg,"index",None) 的 nodes 字典中存在 nid（entry 非 None）且 "subgraph" in entry 时，返回 {'id': nid, 'subgraph': entry.get("subgraph"), 'edges': entry.get("edges") or []}（subgraph 值为 None 也照样返回）；否则改走 cg.get(nid)，返回 (node or {}).get("frontmatter") or {}，节点不存在或 frontmatter 为假值时得空 dict；
def _fm(cg, nid):
    """取节点 frontmatter：优先索引快照（免 IO），快照缺字段时回退读文件。"""
    entry = ((getattr(cg, "index", None) or {}).get("nodes") or {}).get(nid)
    if entry is not None and "subgraph" in entry:
        return {"id": nid, "subgraph": entry.get("subgraph"),
                "edges": entry.get("edges") or []}
    node = cg.get(nid)
    return (node or {}).get("frontmatter") or {}


# --------------------------------------------------------------------------
# 迁移边适配：源 sqlite 认知图 → md_cg 本地边
# --------------------------------------------------------------------------
# 源库的 `hierarchical` 方向是 **source=父、target=子**（白箱
# `wisdom-book-cloud.db` 全量实测：`source_is_parent=2832`、`target_is_parent=0`）。
# md_cg 的父边约定与其**相反**：`part_of` 表示「本节点是子、target 是父」
# （见下方 children_index）。若把源库 hierarchical 原样搬进来，树会整体倒置；
# 故迁移时翻译成语义等价的 `contains`（本节点是父、target 是子）。
SRC_REL_MAP = {"hierarchical": "contains"}


# 生效条件：rel 先经 str(rel or "").strip().lower() 归一（None/空串得 ""），返回 {'target': str(tgt), 'relation_type': SRC_REL_MAP.get(rel, rel), 'confidence': confidence, 'verified': verified}——归一后的 rel 命中模块常量 SRC_REL_MAP 时用映射值、未命中（含 rel 为空串）时原样保留，confidence/verified 直接透传默认 1.0/0 的实参不做校验；
def normalize_edge(tgt, rel, confidence=1.0, verified=0):
    """源库边 → md_cg 本地边（迁移器专用）。做两件事：

    1) 键名统一为 `relation_type`。`children_index` / `parents_index` 只认
       `relation_type` / `relation`；早期迁移器写的 `"type"` 会被静默忽略
       （`chain.edge_rel` 兼容 `type`，但 `subgraph` 不兼容），使迁入的图不可遍历。
    2) 方向按 `SRC_REL_MAP` 翻译（源库 hierarchical = source 是父）。
    """
    rel = str(rel or "").strip().lower()
    return {"target": str(tgt), "relation_type": SRC_REL_MAP.get(rel, rel),
            "confidence": confidence, "verified": verified}


# 生效条件：pid 为当前节点 id、fm 为 frontmatter；声明子节点与登记层级关系统一产出 (child,parent)，兼容 relation/type/target_id 别名，未知关系/非 dict 边不产出。
def _hierarchy_pairs(pid, fm):
    """Single hierarchy direction/alias source for both indexes and validation."""
    for child in declared(fm)["nodes"]:
        yield child, pid
    edges = fm.get("edges") or []
    if not isinstance(edges, (list, tuple)):
        return
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        rel = str(edge.get("relation_type") or edge.get("relation") or edge.get("type")
                  or "").strip().lower()
        target = edge.get("target") or edge.get("target_id")
        if target is None:
            continue
        target = str(target).strip()
        if rel in ("part_of", "hierarchical"):
            yield pid, target
        elif rel in ("parent_of", "contains"):
            yield target, pid


# 生效条件：已有 _subgraph_children 缓存则原样返回；否则遍历索引节点快照，按 _hierarchy_pairs 去重 (child,parent)，构建 parent→[child] 并缓存。
# 生效条件：cg 的 `_cache_generation` 可调用时取其代际，与上次记录的 `_subgraph_generation` 不同即调用 invalidate_cache(cg) 并更新记录（issue #343：派生面随真源换代——真源变了，派生索引必须失效，否则 cache 那一维会给出旧答案）。
def _ensure_cache_generation(cg):
    """Both directions belong to the same current node snapshot."""
    generation = getattr(cg, "_cache_generation", None)
    if not callable(generation):
        return
    generation = generation()
    if getattr(cg, "_subgraph_generation", None) != generation:
        invalidate_cache(cg)
        cg._subgraph_generation = generation


def children_index(cg):
    """全局正查；声明和边共用单一方向规则，保留首次出现顺序。"""
    _ensure_cache_generation(cg)          # #343 换代守卫
    idx = getattr(cg, "_subgraph_children", None)
    if idx is not None:
        return idx
    idx, pairs = {}, set()
    for pid in list(((getattr(cg, "index", None) or {}).get("nodes") or {}).keys()):
        for child, parent in _hierarchy_pairs(pid, _fm(cg, pid)):
            if (child, parent) in pairs:
                continue
            pairs.add((child, parent))
            idx.setdefault(parent, []).append(child)
    try:
        cg._subgraph_children = idx
    except Exception:
        pass
    return idx


# 生效条件：返回 list(children_index(cg).get(nid) or [])，即 nid 在索引中无键或对应值为空（None/空列表）时得空列表，否则返回其子 id 的浅拷贝列表；
def children(cg, nid):
    """直接子节点 id 列表：`subgraph.nodes` 声明 ∪ 边式父子关系。"""
    return list(children_index(cg).get(nid) or [])


# 生效条件：已有 _subgraph_parents 缓存则原样返回；否则遍历索引节点快照，按 _hierarchy_pairs 去重 (child,parent)，构建 child→[parent] 并缓存。
def parents_index(cg):
    """全局反查；与 children_index 共用规范化后的同一边集合。"""
    _ensure_cache_generation(cg)          # #343 换代守卫
    idx = getattr(cg, "_subgraph_parents", None)
    if idx is not None:
        return idx
    idx, pairs = {}, set()
    for pid in list(((getattr(cg, "index", None) or {}).get("nodes") or {}).keys()):
        for child, parent in _hierarchy_pairs(pid, _fm(cg, pid)):
            if (child, parent) in pairs:
                continue
            pairs.add((child, parent))
            idx.setdefault(child, []).append(parent)
    try:
        cg._subgraph_parents = idx
    except Exception:
        pass
    return idx


# 生效条件：无条件执行——把 cg 的 _subgraph_parents 与 _subgraph_children 依次 setattr 为 None（setattr 抛异常被 except 吞掉后继续下一个），无返回值，与 cg 是否已建有缓存无关；
def invalidate_cache(cg):
    """写入/删除节点后调用，丢弃父子正查/反查缓存。"""
    for attr in ("_subgraph_parents", "_subgraph_children"):
        try:
            setattr(cg, attr, None)
        except Exception:
            pass


# 生效条件：取 parents_index(cg).get(nid) or []，列表非空时返回其首元素，键缺失或值为空/假（None、[]）时返回 None；多父时只返回第一个，不在此处报歧义；
def parent_of(cg, nid):
    """唯一父（多父时返回第一个并置 `ambiguous` 标记由 validate 报出）。"""
    ps = parents_index(cg).get(nid) or []
    return ps[0] if ps else None


# 生效条件：max_depth 非 None 时先 max(0, min(int(max_depth), MAX_DEPTH_HARD)) 收敛；max_nodes 非 None 时 int() 收敛（nan/inf 抛 ValueError/OverflowError，不得解除上界）；以 nid 为根迭代 BFS（deque.popleft），已入 seen 的节点跳过，len(seen) >= max_nodes（max_nodes 传 0 时首次循环即成立）置 truncated=True 并 break，depth >= max_depth 且邻接非空时置 truncated=True 并 continue，否则按 children_index 顺序把未出现过的 (ch,cur) 追加 part_of 边并入队；返回前只保留两端均已 admit 的边；返回 {'root','nodes','paths','edges','n_nodes','n_edges','truncated'}；
def expand(cg, nid, max_depth=None, max_nodes=MAX_NODES_DEFAULT):
    """按最短层级展开子树（迭代 BFS，防递归深度爆栈）。

    返回 `{"root","nodes","paths","edges","n_nodes","n_edges","truncated"}`；
    `paths` 为 `节点 id → "根/子/孙"` 层级路径（flatten 后仍可定位来源）。
    边为 `part_of(child→parent)`，与 AEIS flatten 的方向一致。

    v0.9.0 起改为 BFS：① 共享子节点按最短层级登记路径；② 节点预算耗尽时不预拷贝宽邻接表；
    ③ 返回前只保留两端均已 admit 的边（边闭合，不把未 admit 的子节点留在边里）。
    """
    if max_depth is not None:
        max_depth = max(0, min(int(max_depth), MAX_DEPTH_HARD))
    if max_nodes is not None:
        max_nodes = int(max_nodes)   # v0.9.0：nan/inf 预算必须结构化拒绝（int() 抛 ValueError/OverflowError），不得解除上界
    seen, edges, truncated = {}, [], False
    seen_edges = set()
    queue = deque([(nid, 0, nid)])
    while queue:
        cur, depth, path = queue.popleft()
        if cur in seen:
            continue
        if len(seen) >= max_nodes:
            truncated = True
            break
        seen[cur] = path
        adjacency = children_index(cg).get(cur) or ()
        if max_depth is not None and depth >= max_depth:
            if adjacency:
                truncated = True
            continue
        for ch in adjacency:
            key = (ch, cur)
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append({"source": ch, "target": cur,
                              "relation_type": "part_of",
                              "confidence": 1.0, "verified": 0})
            if ch not in seen:
                # 预算守卫必须在入队前：已 admit + 在飞 达上界即停，既不超预算，也不预扫整份宽邻接；
                # 已登记的边在返回前按 admit 面过滤（下面那行），不会留下指向未 admit 节点的边。
                if len(seen) + len(queue) >= max_nodes:
                    truncated = True
                    break
                queue.append((ch, depth + 1, f"{path}/{ch}"))
    edges = [e for e in edges if e["source"] in seen and e["target"] in seen]
    return {"root": nid, "nodes": list(seen.keys()), "paths": seen,
            "edges": edges, "n_nodes": len(seen), "n_edges": len(edges),
            "truncated": truncated}


# 生效条件：先调用 expand(cg, nid, max_depth=max_depth, max_nodes=max_nodes)，对其中每条边复制一份并追加 source/target 互换、relation_type="parent_of"、confidence/verified 沿用原边 .get(…,1.0/0) 的反向边；返回 root=nid、nodes=ex["nodes"]、paths=ex["paths"]、n_nodes=ex["n_nodes"]、n_edges=双边后条数、truncated=ex["truncated"]；
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


# 生效条件：known 取 cg.index 的 nodes 键集合，仅当 parents_index(cg).get(nid) or [] 为空（键缺失或空列表）的 nid 才视为树根，返回其排序后的 id 列表；
def roots(cg):
    """无父节点（树根）的 id 列表。"""
    known = set(((getattr(cg, "index", None) or {}).get("nodes") or {}).keys())
    pmap = parents_index(cg)
    return sorted(nid for nid in known if not (pmap.get(nid) or []))


# 生效条件：parent 为 child→首父 映射；逐分量记忆化链尾，返回 node→None（无环）或 (cycle_tuple,entry_offset)，不递归、不重复上溯已解析尾链。
def _cycle_entries(parent):
    """O(V) functional-parent analysis; cycle report bytes are a separate cost."""
    resolved = {}
    for start in parent:
        if start in resolved:
            continue
        path, positions, cur = [], {}, start
        while cur is not None and cur not in positions and cur not in resolved:
            positions[cur] = len(path)
            path.append(cur)
            cur = parent.get(cur)
        if cur in positions:
            cycle = tuple(path[positions[cur]:])
            for offset, node in enumerate(cycle):
                resolved[node] = (cycle, offset)
        inherited = resolved.get(cur)
        for node in reversed(path):
            if node in resolved:
                inherited = resolved[node]
            else:
                resolved[node] = inherited
    return resolved


# 生效条件：max_scan 只限源节点处理数，以全节点快照判断悬空端点；层级关系统一经 _hierarchy_pairs，报告自环/悬空/多父，再检查首父投影的环；保留旧声明图的报告顺序、路径和 limit*4 缓冲上限。
def validate(cg, limit=50, max_scan=None):
    """声明和边使用同一层级模型；有多父即报错，环沿首父投影诊断。"""
    all_known = list(((getattr(cg, "index", None) or {}).get("nodes") or {}).keys())
    known = all_known
    if max_scan:
        known = known[:int(max_scan)]
    known_set = set(all_known)
    parent, issues, seen_pairs = {}, [], set()

    # 生效条件：仅缓冲前 limit*4 条问题，保持旧报告计数与截断口径。
    def _issue(**kw):
        if len(issues) < limit * 4:
            issues.append(kw)

    for pid in known:
        fm = _fm(cg, pid)
        if fm.get("edges") is not None and not isinstance(fm["edges"], (list, tuple)):
            _issue(id=pid, issue="invalid_edges")
        for child, par in _hierarchy_pairs(pid, fm):
            if (child, par) in seen_pairs:
                continue
            seen_pairs.add((child, par))
            if child == par:
                _issue(id=par, issue="self_loop", child=child)
                continue
            if child not in known_set:
                _issue(id=par, issue="dangling_child", child=child)
            if par not in known_set:
                _issue(id=child, issue="dangling_parent", parent=par)
            prev = parent.get(child)
            if prev is not None and prev != par:
                _issue(id=child, issue="multi_parent", parents=sorted({prev, par}))
            else:
                parent[child] = par
    if len(issues) < limit * 4:
        resolved = _cycle_entries(parent)
        for nid in known:
            if len(issues) >= limit * 4:
                break
            info = resolved.get(nid)
            if info is not None:
                cycle, offset = info
                rotation = cycle[offset:] + cycle[:offset]
                _issue(id=rotation[0], issue="cycle", path=list(rotation) + [rotation[0]])
    return {"scanned": len(known), "issues": len(issues),
            "items": issues[:limit], "truncated": len(issues) > limit}


# ==========================================================================
# 模式分离（maintain.separate）
# ==========================================================================
#
# 问题：两条记忆**内容高度相似但生效条件不同**。若放任不管，检索会把它们混为
# 一体——按 A 的条件召回、却拿到 B 的结论。海马体的做法是 pattern separation：
# 把相似但情境不同的表征拆开，各挂各的条件线索。
#
# 本层的工程兑现（保守、可逆、幂等）：
#   · 不动正文（不制造第二份真相），只加**对称分离边** `distinct_from`；
#   · 边携带 reason + 判定分量，供后续重构/审计追溯；
#   · 条件**相同**的相似对**不是**分离候选（那是重复，该走 MERGE）。

# issue #164：派生节点（概念归纳 / 情景重构）必须带密级，密级 = 来源锚点最高档；
# 判不了（缺 / 非法）fail-closed 不生成。加密档（crypto.ENCRYPTED_LEVELS）只抄
# id 不抄条件词——判据读 frontmatter 明文，不依赖 cg.get 是否已解密。
def _sensitivity_of(fm):
    """从 frontmatter 读合法密级；缺/非法返回 None（不猜测）。"""
    from . import security as _sec
    s = (fm or {}).get("sensitivity")
    if s is None:
        return _sec.DEFAULT_SENSITIVITY
    try:
        _sec._rank(str(s))
        return str(s)
    except Exception:
        return None


def node_sensitivity(cg, nid):
    """读节点密级：优先索引快照（元数据明文），回退读文件；判不了返回 None。"""
    e = ((getattr(cg, "index", None) or {}).get("nodes") or {}).get(nid)
    if e is not None and e.get("sensitivity") is not None:
        return _sensitivity_of(e)
    node = cg.get(nid)
    if not node:
        return None
    return _sensitivity_of(node.get("frontmatter") or {})


def derive_sensitivity(cg, nids):
    """派生节点密级 = 来源锚点最高档；任一来源判不了 → None（fail-closed）。"""
    from . import security as _sec
    best = None
    for nid in nids:
        s = node_sensitivity(cg, nid)
        if s is None:
            return None
        if best is None or _sec._rank(s) > _sec._rank(best):
            best = s
    return best


# 生效条件：cg.get(nid) 为假值（None/{}）时返回 None；否则取 fm=node.get("frontmatter") or {}、content=node.get("content") or ""，返回 {'grams': bigrams(forgetting.payload(content)), 'pos','neg': consistency.condition_terms(fm, content) 的结果, 'layer': fm.get("layer"), 'sensitivity': _sensitivity_of(fm)}；加密档返回 grams/pos/neg 为空集、encrypted=True，不抄条件词；
def _node_terms_and_grams(cg, nid):
    """读取节点并返回 (payload 二元组, 正条件词面, 负条件词面)；不可读返回 None。"""
    from . import consistency, forgetting, crypto
    from .mdcg import bigrams          # 惰性导入：避开 mdcg↔subgraph 循环
    e = ((getattr(cg, "index", None) or {}).get("nodes") or {}).get(nid)
    if e is not None and e.get("sensitivity") is not None:
        sens = _sensitivity_of(e)
        if sens is None:
            return {"grams": set(), "pos": set(), "neg": set(),
                    "layer": e.get("layer"), "sensitivity": None,
                    "unjudgeable": True}
        if crypto.is_encrypted_level(sens):   # v0.9.0：加密档判定走单点谓词
            return {"grams": set(), "pos": set(), "neg": set(),
                    "layer": e.get("layer"), "sensitivity": sens,
                    "encrypted": True}
    node = cg.get(nid)
    if not node:
        return None
    fm = node.get("frontmatter") or {}
    content = node.get("content") or ""
    sens = _sensitivity_of(fm)
    if crypto.is_encrypted_level(sens):   # v0.9.0：加密档判定走单点谓词
        return {"grams": set(), "pos": set(), "neg": set(),
                "layer": fm.get("layer"), "sensitivity": sens, "encrypted": True}
    grams = bigrams(forgetting.payload(content))
    pos, neg = consistency.condition_terms(fm, content)
    return {"grams": grams, "pos": pos, "neg": neg, "layer": fm.get("layer"),
            "sensitivity": sens}


# 生效条件：pool 初取 cg.index 的 nodes 键，layer 为假值（None/""）时不按层过滤、否则只留 e.get("layer")==layer 的 nid，ids 为真值时只留 str(x) 属于该集合的 nid；pool 排序后 truncated=len(pool)>int(max_nodes)、并截为前 int(max_nodes) 个；只有 _node_terms_and_grams 返回非 None 且 grams 非空的节点进 cache；对 cache 键两两比较——无公共 bigram 跳过、jaccard 小于 float(min_jaccard) 跳过、condition_distinct 的 distinct 为假或 overlap > float(max_cond_overlap) 跳过，其余成候选并按 (-jaccard,a,b) 排序；返回 scanned、compared、candidates=out[:int(limit)]、total_candidates、truncated、note；
def separation_pairs(cg, layer=None, ids=None, max_nodes=SEP_MAX_NODES,
                     min_jaccard=SEP_MIN_JACCARD,
                     max_cond_overlap=SEP_MAX_COND_OVERLAP,
                     limit=SEP_MAX_PAIRS):
    """找出「内容高度相似、条件却不同」的节点对（模式分离候选）。

    返回 {scanned, compared, candidates:[{a,b,jaccard,cond_overlap,distinct,reason}],
          truncated, note}。只读，不写盘。
    """
    from . import consistency
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    pool = [nid for nid, e in list(nodes.items())
            if (not layer or e.get("layer") == layer)]
    if ids:
        want = {str(x) for x in ids}
        pool = [nid for nid in pool if nid in want]
    pool.sort()
    truncated = len(pool) > int(max_nodes)
    pool = pool[:int(max_nodes)]
    cache = {}
    for nid in pool:
        got = _node_terms_and_grams(cg, nid)
        if got and got["grams"]:
            cache[nid] = got
    keys = sorted(cache.keys())
    out, compared = [], 0
    for i in range(len(keys)):
        gi = cache[keys[i]]["grams"]
        for j in range(i + 1, len(keys)):
            gj = cache[keys[j]]["grams"]
            inter = len(gi & gj)
            if not inter:
                continue
            compared += 1
            jac = inter / float(len(gi | gj) or 1)
            if jac < float(min_jaccard):
                continue
            a, b = keys[i], keys[j]
            cd = consistency.condition_distinct(
                cache[a]["pos"], cache[a]["neg"],
                cache[b]["pos"], cache[b]["neg"])
            if not cd["distinct"] or cd["overlap"] > float(max_cond_overlap):
                continue                       # 条件相同 → 是重复，不是分离
            out.append({
                "a": a, "b": b,
                "a_layer": cache[a]["layer"], "b_layer": cache[b]["layer"],
                "jaccard": round(jac, 4), "cond_overlap": cd["overlap"],
                "reason": (f"内容相似 {jac:.2f} 但条件重合仅 {cd['overlap']:.2f}"
                           f"（相似而不同情境，需分离）"),
                "a_conditions": sorted(cache[a]["pos"] | cache[a]["neg"])[:6],
                "b_conditions": sorted(cache[b]["pos"] | cache[b]["neg"])[:6],
            })
    out.sort(key=lambda x: (-x["jaccard"], x["a"], x["b"]))
    return {"scanned": len(keys), "compared": compared,
            "candidates": out[:int(limit)],
            "total_candidates": len(out), "truncated": truncated,
            "note": "只读候选；apply=True 才写分离边"}


# 生效条件：batch 为假值（None 或空串）时回落到 time.strftime("%Y%m%d-%H%M%S")；按 (a,b)、(b,a) 两向处理：cg.get(src) 为假值跳过，dst 已出现在 consistency.separation_targets(fm) 中跳过，否则往 fm["edges"] 追加 distinct_from 边、向 fm["pattern_separated_from"] 追加 dst，按 os.path.join(cg.root, e.get("path") or f"{src}.md") 调 cg._write_node 写盘并追加 MAINTAIN_LOG 行，src 记入 written；返回 {'a','b','written','batch'}；
def mark_separated(cg, a, b, reason="", actor="maintain", batch=None):
    """写入 (a↔b) 对称 `distinct_from` 边（幂等：已存在则不重复写）。"""
    from . import consistency
    batch = batch or time.strftime("%Y%m%d-%H%M%S")
    written = []
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    for src, dst in ((a, b), (b, a)):
        node = cg.get(src)
        if not node:
            continue
        fm = node.get("frontmatter") or {}
        edges = list(fm.get("edges") or [])
        if dst in consistency.separation_targets(fm):
            continue
        edges.append({"target": dst, "relation_type": consistency.SEPARATION_REL,
                      "reason": reason, "created_at": time.time(),
                      "confidence": 1.0, "verified": 0})
        fm["edges"] = edges
        sep = list(fm.get("pattern_separated_from") or [])
        if dst not in sep:
            sep.append(dst)
        fm["pattern_separated_from"] = sep
        e = nodes.get(src) or {}
        path = os.path.join(cg.root, e.get("path") or f"{src}.md")
        cg._write_node(src, path, fm, node.get("content") or "")
        if e:
            e["edges"] = edges
        written.append(src)
        append_jsonl(os.path.join(cg.root, MAINTAIN_LOG), {
            "t": time.time(), "action": "separate", "batch": batch,
            "from": src, "to": dst, "reason": reason, "actor": actor})
    return {"a": a, "b": b, "written": written, "batch": batch}


# 生效条件：pairs 为 None 时调 separation_pairs 取 candidates 与 meta（scanned/compared/truncated/total_candidates），否则 cands=list(pairs) 且 meta 中 scanned/compared 记 0、truncated 记 False、total_candidates=len(cands)；apply 为真值时先生成统一 batch=time.strftime(...)，逐个候选调 mark_separated(..., batch=batch)，written 非空且 cg 有 rebuild_index 时调 cg.rebuild_index()、否则调 invalidate_cache(cg)，apply 为假值时不写盘；返回 ok、action='separate'、dry_run=not apply、layer、candidates、written、written_count、elapsed_ms、log 与 meta、note；
def separate_run(cg, layer=None, pairs=None, apply=False, ids=None,
                 min_jaccard=SEP_MIN_JACCARD, limit=SEP_MAX_PAIRS,
                 actor="maintain"):
    """模式分离：扫描相似但条件不同的节点对，按需写入对称分离边。

    apply=False（默认）只出候选报表（对应计划「可预演」）。
    """
    t0 = time.time()
    if pairs is None:
        rep = separation_pairs(cg, layer=layer, ids=ids,
                               min_jaccard=min_jaccard, limit=limit)
        cands = rep["candidates"]
        meta = {k: rep[k] for k in ("scanned", "compared", "truncated",
                                    "total_candidates")}
    else:
        cands = list(pairs)
        meta = {"scanned": 0, "compared": 0, "truncated": False,
                "total_candidates": len(cands)}
    written = []
    if apply:
        batch = time.strftime("%Y%m%d-%H%M%S")
        for c in cands:
            written.append(mark_separated(cg, c["a"], c["b"],
                                          reason=c.get("reason", ""),
                                          actor=actor, batch=batch))
        if written and hasattr(cg, "rebuild_index"):
            cg.rebuild_index()          # 边写盘后重建索引 + 清子图缓存
        else:
            invalidate_cache(cg)
    return {"ok": True, "action": "separate", "dry_run": not apply,
            "layer": layer, "candidates": cands, "written": written,
            "written_count": len(written), "elapsed_ms": int((time.time() - t0) * 1000),
            "log": MAINTAIN_LOG, **meta,
            "note": ("dry-run：未写盘；apply=True 才写分离边" if not apply
                     else f"已写 {len(written)} 对对称分离边")}


# ==========================================================================
# 情景重构（insight.reconstruct）
# ==========================================================================
#
# 问题：记忆被检索回来时，往往只剩一条「结论」，它当时**为什么成立**（生效条件 /
# 不适用条件 / 同行情境）已经散落在相邻节点里。情景重构做的就是：由给定线索
# （词面 / 节点 id）反推当时的**条件空间**，把散落的场景要素重新聚在一起。
#
# 与检索（read/route）的区别：检索按「当前查询」做资格判定；重构按「线索」做
# **条件空间复原**，输出条件结构而非排序结果，用于回答「这件事成立于什么条件」。
#
# 诚实边界：
#   · 重构是条件空间的**近似重建**，不是事件回放（输出显式标注）；
#   · 定位不到任何锚点时判 blindspot，**不得凭空编造条件空间**。

RECON_MIN_SCORE = 0.15        # 词面命中下限（低于此不算锚点）
RECON_MAX_NODES = 80          # 单次扫描节点上限（防 O(N) 读盘爆炸）
RECON_MAX_ANCHORS = 12        # 锚点上限
RECON_NEIGHBOR_LIMIT = 24     # 每锚点取的邻居上限
RECON_COMMON_SHARE = 0.5      # 共同条件判定：≥ 半数锚点共享
RECON_SCENE_PREFIX = "scene_"


# 生效条件：clues 为 None 时返回 []；clues 为 str 时包装成单元素列表；逐项取 str(c or "").strip().lower()，空串跳过，整串去重入 out，再按 re.split(r"[\s,，、;；/|]+") 切词、去重后追加；返回 out；
def _clue_terms(clues):
    """线索归一化：字符串 / 列表 → 去重词面（保留整串 + 切分后的词）。"""
    if clues is None:
        return []
    if isinstance(clues, str):
        clues = [clues]
    out = []
    for c in clues:
        s = str(c or "").strip().lower()
        if not s:
            continue
        if s not in out:
            out.append(s)
        for w in re.split(r"[\s,，、;；/|]+", s):
            w = w.strip()
            if w and w not in out:
                out.append(w)
    return out


# 生效条件：term_sets 为假值（None/[]）时返回 []；否则对每个集合的 set(s or ()) 统计词面出现次数，need = max(2, int(len(term_sets)*RECON_COMMON_SHARE) 向上取整)，返回出现次数 >= need 的词面排序列表（阈值取自模块常量 RECON_COMMON_SHARE）；
def _shared_terms(term_sets):
    """出现在 ≥ RECON_COMMON_SHARE 比例集合中的词面（且至少 2 个集合共享）。"""
    if not term_sets:
        return []
    cnt = {}
    for s in term_sets:
        for t in set(s or ()):
            cnt[t] = cnt.get(t, 0) + 1
    need = max(2, int(len(term_sets) * RECON_COMMON_SHARE) + (1 if len(term_sets) * RECON_COMMON_SHARE % 1 else 0))
    return sorted(t for t, c in cnt.items() if c >= need)


# 生效条件：按 term_sets 原顺序遍历每个集合的 sorted(s or ())，首次出现的词面追加到 seen，返回 seen[:limit]（limit 默认 99，传 0 时切片为空列表，无 or 回落）；
def _uniq_terms(term_sets, limit=99):
    seen = []
    for s in term_sets:
        for t in sorted(s or ()):
            if t not in seen:
                seen.append(t)
    return seen[:limit]


# 生效条件：bigrams(" ".join(clue_terms)) 为空时返回 []；否则遍历 pool，cg.get(nid) 为假值、或 forgetting.payload 后 bigrams 为空、或与 clue_grams 无交集时跳过，否则 jac=inter/len(并集 or 1)、exact 为 clue_terms 中非空且作为子串出现在 body 的个数，score=jac+0.05*exact，仅 score >= RECON_MIN_SCORE 才收录，最终按 (-score, nid) 排序返回；
def _anchor_scores(cg, pool, clue_terms):
    """按词面重合给候选锚点打分（返回 [(nid, score, shared, exact)]，降序）。"""
    from . import forgetting
    from .mdcg import bigrams
    clue_grams = bigrams(" ".join(clue_terms))
    if not clue_grams:
        return []
    scored = []
    for nid in pool:
        node = cg.get(nid)
        if not node:
            continue
        body = forgetting.payload(node.get("content") or "")
        grams = bigrams(body)
        if not grams:
            continue
        inter = len(grams & clue_grams)
        if not inter:
            continue
        jac = inter / float(len(grams | clue_grams) or 1)
        exact = sum(1 for t in clue_terms if t and t in body)
        score = jac + 0.05 * exact
        if score >= RECON_MIN_SCORE:
            scored.append((nid, round(score, 4), inter, exact))
    scored.sort(key=lambda x: (-x[1], x[0]))
    return scored


# 生效条件：对 anchor_ids 中每个 nid 合成条件空间——加密档锚点不读正文条件词（per 记空集、不进 pos_sets/neg_sets），其余取 fm 与 consistency.condition_terms 得 pos/neg，per[nid] 记为 {"effective": sorted(pos)[:8], "non_applicable": sorted(neg)[:8]}；返回 common=_shared_terms(pos_sets)、individual=_uniq_terms(pos_sets) 中不在 common 的项、non_applicable=_uniq_terms(neg_sets)、declared=list(declared_terms or [])、per_anchor=per、sensitivity=derive_sensitivity(cg, anchor_ids)；
def _condition_space(cg, anchor_ids, declared_terms=None):
    """合成锚点群的条件空间：共同条件 / 个别条件 / 不适用条件 / 逐锚点明细。"""
    from . import consistency, crypto
    pos_sets, neg_sets, per = [], [], {}
    for nid in anchor_ids:
        e = ((getattr(cg, "index", None) or {}).get("nodes") or {}).get(nid) or {}
        sens = _sensitivity_of(e)
        if crypto.is_encrypted_level(sens):   # v0.9.0：加密档判定走单点谓词
            per[nid] = {"effective": [], "non_applicable": []}
            continue
        node = cg.get(nid)
        if not node:
            continue
        fm = node.get("frontmatter") or {}
        pos, neg = consistency.condition_terms(fm, node.get("content") or "")
        pos_sets.append(pos)
        neg_sets.append(neg)
        per[nid] = {"effective": sorted(pos)[:8], "non_applicable": sorted(neg)[:8]}
    common = _shared_terms(pos_sets)
    individual = [t for t in _uniq_terms(pos_sets) if t not in common]
    return {"common": common, "individual": individual,
            "non_applicable": _uniq_terms(neg_sets),
            "declared": list(declared_terms or []), "per_anchor": per,
            "sensitivity": derive_sensitivity(cg, anchor_ids)}


# 生效条件：以 cg.index["nodes"] 为节点池（layer 为真时只保留 layer 等于该值的节点，池按 max_nodes 截断），由 clues 词项与 ids 收集锚点并截取 limit 个，锚点为空则返回 status="blindspot" 且 condition_space=None，否则返回 status="reconstructed"（neighbors 为真时按链邻接补边并在 max_nodes 内补节点，apply 为真且算出的 scene_id 尚不在 nodes 中时再写入该情境节点并记日志）；
def reconstruct_scene(cg, clues=None, ids=None, conditions=None, layer=None,
                      max_nodes=RECON_MAX_NODES, limit=RECON_MAX_ANCHORS,
                      neighbors=True, apply=False, actor="insight"):
    """情景重构：由线索反推条件空间，还原记忆成立的场景。

    只读（apply=False 默认）；apply=True 额外落一个 `scene_<hash>` 情境节点，
    携带 `reconstructed_from` 锚点与 inferred 边，便于追溯与撤销。

    返回 status ∈ {"reconstructed", "blindspot"}；blindspot 时条件空间为 None，
    不编造（对应计划「诚实边界」）。
    """
    from . import chain
    t0 = time.time()
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    clue_terms = _clue_terms(clues)
    declared = [str(c).strip().lower() for c in (conditions or []) if str(c).strip()]
    want_ids = [str(x) for x in (ids or []) if str(x).strip()]

    # 线索里若直接写了节点 id，也算显式锚点
    for t in clue_terms:
        if t in nodes and t not in want_ids:
            want_ids.append(t)

    pool = [nid for nid, e in list(nodes.items())
            if (not layer or (e or {}).get("layer") == layer)]
    truncated = len(pool) > int(max_nodes)
    pool.sort()
    pool = pool[:int(max_nodes)]

    anchors, missing = [], []
    for nid in want_ids:
        if nid in nodes:
            anchors.append({"node_id": nid, "score": 1.0, "source": "explicit"})
        else:
            missing.append(nid)
    if clue_terms:
        have = {a["node_id"] for a in anchors}
        for nid, score, inter, exact in _anchor_scores(cg, pool, clue_terms):
            if nid in have:
                continue
            anchors.append({"node_id": nid, "score": score, "source": "lexical",
                            "shared_bigrams": inter, "exact_hits": exact})
            have.add(nid)
    anchors = anchors[:int(limit)]

    base = {"ok": True, "action": "reconstruct", "op": "insight",
            "clues": clue_terms, "requested_ids": want_ids, "layer": layer,
            "truncated": truncated, "scanned": len(pool)}

    if not anchors:
        base.update({
            "status": "blindspot", "anchors": [], "nodes": [], "edges": [],
            "condition_space": None,
            "missing": missing or (["锚点"] if clue_terms else ["线索"]),
            "elapsed_ms": int((time.time() - t0) * 1000),
            "note": "线索未能定位任何锚点：判 blindspot，不编造条件空间（诚实边界）"})
        return base

    anchor_ids = [a["node_id"] for a in anchors]
    node_ids, edges = list(anchor_ids), []
    if neighbors:
        adj = {}
        try:
            adj = chain.adjacency(cg)
        except Exception:
            adj = {}
        seen = set(node_ids)
        for nid in anchor_ids:
            outs = (adj.get(nid) or [])[:RECON_NEIGHBOR_LIMIT]
            for tgt, e in outs:
                rel = chain.edge_rel(e)
                edges.append({"from": nid, "to": tgt, "relation": rel,
                              "evidence": (e or {}).get("evidence")})
                if tgt not in seen and len(node_ids) < int(max_nodes):
                    seen.add(tgt)
                    node_ids.append(tgt)

    cs = _condition_space(cg, anchor_ids, declared_terms=declared)
    separated = [nid for nid in anchor_ids
                 if any(e.get("relation") == "distinct_from" for e in edges
                        if e.get("from") == nid)]
    with_conditions = sum(1 for nid in anchor_ids
                          if (cs["per_anchor"].get(nid) or {}).get("effective"))
    confidence = round(
        min(1.0, (sum(a["score"] for a in anchors) / float(len(anchors)))
            * (0.5 + 0.5 * with_conditions / float(len(anchor_ids)))), 4)

    out = dict(base)
    out.update({
        "status": "reconstructed", "anchors": anchors, "nodes": node_ids,
        "edges": edges, "condition_space": cs,
        "signals": {"anchors": len(anchors), "with_conditions": with_conditions,
                    "separated": separated},
        "confidence": confidence,
        "elapsed_ms": int((time.time() - t0) * 1000),
        "note": "条件空间的近似重建（非事件回放）；common=共同生效条件，"
                "individual=个别条件，non_applicable=不适用条件"})

    if apply:
        sid = RECON_SCENE_PREFIX + hashlib.sha1(
            "|".join(sorted(node_ids)).encode("utf-8")).hexdigest()[:10]
        written = False
        sens = cs.get("sensitivity")
        if sens is None:
            append_jsonl(os.path.join(cg.root, MAINTAIN_LOG), {
                "t": time.time(), "action": "reconstruct", "scene": None,
                "anchors": list(anchor_ids), "clues": clue_terms,
                "reason": "sensitivity_not_judgeable", "actor": actor})
        elif sid not in nodes:
            common_txt = "；".join(cs["common"][:6]) or "（未提炼出共同条件）"
            neg_txt = "；".join(cs["non_applicable"][:6]) or "（未判定）"
            body = (
                "# 功能名：情景重构：%s\n"
                "# 生效条件：%s\n"
                "# 子功能：由 %d 个锚点复原的条件空间（锚点：%s）\n"
                "# 执行：由 insight.reconstruct 反推（inferred 近似重建，非事件回放）\n"
                "# 验证方式：待验证（推断结果，需人工/实践核对后方可升格）\n"
                "# 不适用条件：%s\n"
                % ("、".join(clue_terms[:6]) or "线索", common_txt, len(anchor_ids),
                   "、".join(anchor_ids), neg_txt))
            cg.add(sid, body, layer="contextual",
                   tags=["scene", "reconstructed"], importance=0.4,
                   verification_basis="other", sensitivity=sens,
                   reconstructed_from=list(anchor_ids),
                   clues=list(clue_terms), confidence=confidence,
                   actor=actor)
            try:
                from . import security as _sec
                _high = _sec._rank(str(sens)) > _sec._rank(_sec.DEFAULT_SENSITIVITY)
            except Exception:
                _high = False
            if _high:
                append_jsonl(os.path.join(cg.root, MAINTAIN_LOG), {
                    "t": time.time(), "action": "reconstruct", "scene": sid,
                    "anchors": list(anchor_ids), "clues": clue_terms,
                    "common": [], "condition_terms_withheld": True,
                    "confidence": confidence, "actor": actor})
            else:
                append_jsonl(os.path.join(cg.root, MAINTAIN_LOG), {
                    "t": time.time(), "action": "reconstruct", "scene": sid,
                    "anchors": list(anchor_ids), "clues": clue_terms,
                    "common": cs["common"], "confidence": confidence, "actor": actor})
            invalidate_cache(cg)
            written = True
        out["scene_id"] = sid
        out["scene_written"] = written
    return out
