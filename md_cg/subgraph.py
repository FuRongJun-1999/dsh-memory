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

from .fsutil import append_jsonl

MAX_DEPTH_HARD = 64          # 工程硬截断上限（防止畸形数据把遍历拖爆）
MAX_NODES_DEFAULT = 2000     # 单次展开的节点上限

# ---- 模式分离（maintain.separate）参数 -----------------------------------
MAINTAIN_LOG = "_maintain.jsonl"
SEP_MIN_JACCARD = 0.55       # 内容相似度下限（越高＝越像，才值得谈分离）
SEP_MAX_COND_OVERLAP = 0.35  # 条件重合上限（越高＝条件越同，就该合并而非分离）
SEP_MAX_NODES = 400          # 单次扫描节点上限（防 O(N²) 读盘爆炸）
SEP_MAX_PAIRS = 50           # 单次返回/落库的候选对上限


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


# --------------------------------------------------------------------------
# 迁移边适配：源 sqlite 认知图 → md_cg 本地边
# --------------------------------------------------------------------------
# 源库的 `hierarchical` 方向是 **source=父、target=子**（白箱
# `wisdom-book-cloud.db` 全量实测：`source_is_parent=2832`、`target_is_parent=0`）。
# md_cg 的父边约定与其**相反**：`part_of` 表示「本节点是子、target 是父」
# （见下方 children_index）。若把源库 hierarchical 原样搬进来，树会整体倒置；
# 故迁移时翻译成语义等价的 `contains`（本节点是父、target 是子）。
SRC_REL_MAP = {"hierarchical": "contains"}


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
            # 兼容历史语料：早期迁移器把关系类型写在 `type` 键（`migrate.py:43`、
            # `migrate_aeis.py:99`），写侧已按 `normalize_edge` 修正，读侧一并容错。
            rel = str(e.get("relation_type") or e.get("relation") or e.get("type")
                      or "").strip().lower()
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
            rel = str(e.get("relation_type") or e.get("relation") or e.get("type")
                      or "").strip().lower()
            tgt = e.get("target") or e.get("target_id")
            if tgt is None:
                continue
            tgt = str(tgt).strip()
            # 与 children_index 逐字对称，只是方向取反：
            #   part_of / hierarchical → 本节点是子，故 target 是本节点的父
            #   parent_of / contains   → 本节点是父，故本节点是 target 的父
            if rel in ("part_of", "hierarchical"):
                idx.setdefault(pid, [])
                if tgt not in idx[pid]:
                    idx[pid].append(tgt)
            elif rel in ("parent_of", "contains"):
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

def _node_terms_and_grams(cg, nid):
    """读取节点并返回 (payload 二元组, 正条件词面, 负条件词面)；不可读返回 None。"""
    from . import consistency, forgetting
    from .mdcg import bigrams          # 惰性导入：避开 mdcg↔subgraph 循环
    node = cg.get(nid)
    if not node:
        return None
    fm = node.get("frontmatter") or {}
    content = node.get("content") or ""
    grams = bigrams(forgetting.payload(content))
    pos, neg = consistency.condition_terms(fm, content)
    return {"grams": grams, "pos": pos, "neg": neg, "layer": fm.get("layer")}


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
    pool = [nid for nid, e in nodes.items()
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


def _uniq_terms(term_sets, limit=99):
    seen = []
    for s in term_sets:
        for t in sorted(s or ()):
            if t not in seen:
                seen.append(t)
    return seen[:limit]


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


def _condition_space(cg, anchor_ids, declared_terms=None):
    """合成锚点群的条件空间：共同条件 / 个别条件 / 不适用条件 / 逐锚点明细。"""
    from . import consistency
    pos_sets, neg_sets, per = [], [], {}
    for nid in anchor_ids:
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
            "declared": list(declared_terms or []), "per_anchor": per}


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

    pool = [nid for nid, e in nodes.items()
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
        if sid not in nodes:
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
                   verification_basis="other", reconstructed_from=list(anchor_ids),
                   clues=list(clue_terms), confidence=confidence,
                   actor=actor)
            append_jsonl(os.path.join(cg.root, MAINTAIN_LOG), {
                "t": time.time(), "action": "reconstruct", "scene": sid,
                "anchors": list(anchor_ids), "clues": clue_terms,
                "common": cs["common"], "confidence": confidence, "actor": actor})
            invalidate_cache(cg)
            written = True
        out["scene_id"] = sid
        out["scene_written"] = written
    return out
