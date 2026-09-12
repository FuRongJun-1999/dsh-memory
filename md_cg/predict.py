# -*- coding: utf-8 -*-
"""生成式预测：候选未来路线（**非必然未来**）。

对齐 AEIS `prediction.py`（PREDICTION-COMPLETION-PLAN-REV1-20260813-001）
四通道预测引擎的通道 3（生成式·因果路线图）+ 通道 4（语义式，经因果过滤门）：

- **D-001** 局部路径生成 + `uncertainty_bound`（候选未来，非必然未来）
- **D-002** 语义邻近过滤门（伪因果防护）：语义候选必须能"说清关系"才准入
- **D-003** 局部线性近似 + `extrapolation_validity`（smooth/jump/unknown）
- **D-004** 评分对齐 2.10 节 T_pred 四维度：
  trend 0.40 · boundary 0.20 · verification 0.25 · balance 0.15
- **D-005** AttentionPolicy 适配器 + 降级路径（无策略时回退边置信度排序）
- **D-006** 命中率动态校准（MIN_SAMPLES=50 · 2.7.2 动态死区）

盲区驱动：`blindspot_id` 指向 unresolved 节点/盲区邻域；声明
`可预测性：unknowable` 的盲区**不生成路线**（结构性不可知）。

与 AEIS 的三处有意差异（代码内均已标注）：
  1. 语义邻近回退到**中文二元组 Jaccard**（AEIS 优先语义坐标，无坐标时同回退）
  2. 命中历史**持久化**在 `_prediction.jsonl`（AEIS 在内存），跨进程可审计
  3. DFS 增加 `path` 防环（AEIS 仅靠 horizon 截断），md 图允许显式环边

纯标准库 · 零外部依赖。
"""
from __future__ import annotations

import hashlib
import os
import re
import time

from .fsutil import append_jsonl, read_jsonl

# ---------------------------------------------------------------- 常量
HORIZON_DEFAULT = 3
MAX_BRANCHES_DEFAULT = 5
HORIZON_HARD = 16
MAX_BRANCHES_HARD = 32

MIN_SAMPLES = 50            # D-006 最低样本量
BASE_HIT_RATE = 0.40        # 基线阈值（工程初值，非协议承诺）
HIT_HISTORY_MAX = 200       # 命中历史滚动窗口
EDGE_BOOST = 0.05           # 命中 → 因果/时序边置信度增量

CAUSAL_BRANCH_TYPES = ("causal", "sequential")
SEMANTIC_TOP_K = 5
SEMANTIC_MIN_SIM = 0.05
SEMANTIC_CONF = 0.4         # 语义诱导候选固定置信度（AEIS 同值）
PREFERENCE_THRESHOLD = 0.5  # D-005 偏好权重准入线

W_TREND = 0.40              # D-004 四维权重（AEIS 2.10 节）
W_BOUNDARY = 0.20
W_VERIFICATION = 0.25
W_BALANCE = 0.15

SORT_KEYS = ("composite", "trend", "verification", "boundary", "balance")
LOG_FILE = "_prediction.jsonl"

# 锚点解析纪律（盲区 → 锚点）：推断脚手架与负记忆都不得充当锚点。
#  - `gap_hint`（待补线索）与 `scene`（情景重构产物）是「推断得出的引子/回放」，
#    本身不构成可起推的事实；尤其 gap_hint 会把盲区描述逐字抄进自己的
#    `# 生效条件`，因而在该盲区的检索里必然排第一，若被当成锚点就形成
#    「线索 → 0 条路线 → 永远 unresolved」的自我污染，learn 重复执行也不再幂等。
#  - `unresolved` / `rejected` 层是负记忆（已否决/未决问题），只能作为覆盖率
#    提示，不能作为起点。
ANCHOR_FETCH_K = 5
ANCHOR_SKIP_TAGS = ("gap_hint", "scene")
ANCHOR_SKIP_LAYERS = ("unresolved", "rejected")


# ---------------------------------------------------------------- 基础

def _nodes(cg):
    return ((getattr(cg, "index", None) or {}).get("nodes") or {})


def log_path(cg):
    return os.path.join(getattr(cg, "root", "."), LOG_FILE)


def _append(cg, rec):
    try:
        append_jsonl(log_path(cg), rec)
    except OSError:
        pass


def _read_log(cg, limit=0):
    try:
        recs = list(read_jsonl(log_path(cg)))
    except (OSError, ValueError):
        recs = []
    if limit and int(limit) > 0:
        recs = recs[-int(limit):]
    return recs


def _hit_history(cg, limit=HIT_HISTORY_MAX):
    """D-006 命中历史（持久化 · 差异 2）：只取 feedback 记录。"""
    return [bool(r.get("hit")) for r in _read_log(cg)
            if r.get("type") == "feedback"][-int(limit):]


def _out_edges(cg, nid):
    """出边（含层级边）：[(target_id, edge_dict)]，复用 chain 邻接缓存。"""
    from . import chain
    return list((chain.adjacency(cg).get(nid) or []))


def _in_sources(cg, nid):
    """入边来源集合（父节点）：用于 D-002「共同父节点」结构模式判定。"""
    from . import chain
    adj = chain.adjacency(cg)
    srcs = set()
    for src, outs in adj.items():
        for tgt, _e in outs:
            if tgt == nid:
                srcs.add(src)
    return srcs


def _edge_conf(edge):
    try:
        return max(0.0, min(1.0, float(edge.get("confidence", 1.0))))
    except (AttributeError, TypeError, ValueError):
        return 1.0


# ---------------------------------------------------------------- D-002 过滤门

def has_causal_link(cg, a_id, b_id):
    """直接因果/时序边：A → B 已声明（直通，无需过滤）。"""
    from . import chain
    for tgt, e in _out_edges(cg, a_id):
        if tgt == b_id and chain.edge_rel(e) in CAUSAL_BRANCH_TYPES:
            return True
    return False


def has_structural_pattern(cg, a_id, b_id):
    """结构模式：A、B 共享父节点（可解释的间接关联 → 伪因果豁免）。"""
    return bool(_in_sources(cg, a_id) & _in_sources(cg, b_id))


def preference_weight(cg, node_id):
    """D-005：AttentionPolicy 适配器（duck-typed `get_weights()`）。

    md_cg 默认无策略 → 0.0（对齐 AEIS：attention_policy=None 时该准入
    条件不生效，只靠因果链/结构模式两道门）。
    """
    pol = getattr(cg, "attention_policy", None)
    if pol is None:
        return 0.0
    try:
        weights = pol.get_weights() or {}
    except Exception:
        return 0.0
    try:
        return float(weights.get(node_id, 0.0))
    except (TypeError, ValueError):
        return 0.0


def causal_gate(cg, a_id, b_id):
    """D-002 伪因果过滤门 → (准入?, 理由)。

    语义邻近候选必须满足其一，否则视为「说不出关系的伪因果」而拒绝：
      1. 已有因果/时序边（直通）
      2. 共同父节点（结构模式）
      3. 偏好权重 > 0.5（D-005 策略显式授权）
    """
    if has_causal_link(cg, a_id, b_id):
        return True, "causal_link"
    if has_structural_pattern(cg, a_id, b_id):
        return True, "structural_pattern"
    if preference_weight(cg, b_id) > PREFERENCE_THRESHOLD:
        return True, "preference_weight"
    return False, "rejected_semantic_only"


# ---------------------------------------------------------------- 语义邻近

def semantic_neighbors(cg, node_id, k=SEMANTIC_TOP_K):
    """语义邻近候选：[(node_id, similarity)]。

    差异 1：AEIS 优先语义坐标（protocol/hierarchy/condition 三维），无坐标
    时回退 `char_bigram_jaccard`；md_cg 无坐标，直接用检索器的二元组打分
    实现该回退路径（非新算法）。
    """
    node = cg.get(node_id) or {}
    text = (node.get("content") or "").strip()
    if not text:
        return []
    try:
        results, _meta = cg.search(text[:200], k=int(k) + 3,
                                   record=False, judge=False)
    except Exception:
        return []
    out = []
    for item in results:
        if isinstance(item, (tuple, list)):
            nd, score = item[0], float(item[1])
        else:
            nd, score = item, 0.0
        if not isinstance(nd, dict):
            continue
        nid = nd.get("id")
        if not nid:
            p = str(nd.get("path") or "")
            nid = os.path.basename(p)[:-3] if p.endswith(".md") else None
        if not nid or nid == node_id or score < SEMANTIC_MIN_SIM:
            continue
        out.append((nid, round(score, 4)))
        if len(out) >= int(k):
            break
    return out


# ---------------------------------------------------------------- D-001 分支

def branch_candidates(cg, node_id, semantic=True):
    """D-001 局部分支候选：因果/时序边直通 + 语义邻近（经 D-002 门）。"""
    from . import chain
    cands, seen = [], set()
    for tgt, e in _out_edges(cg, node_id):
        if tgt in seen:
            continue
        rel = chain.edge_rel(e)
        if rel not in CAUSAL_BRANCH_TYPES:
            continue
        seen.add(tgt)
        cands.append({"node_id": tgt, "confidence": _edge_conf(e),
                      "source": "causal", "relation_type": rel,
                      "condition": chain.edge_condition(e) or ""})
    if semantic:
        for tgt, sim in semantic_neighbors(cg, node_id):
            if tgt in seen:
                continue
            ok, why = causal_gate(cg, node_id, tgt)
            if not ok:
                continue
            seen.add(tgt)
            cands.append({"node_id": tgt, "confidence": SEMANTIC_CONF,
                          "source": "semantic_induced", "relation_type": why,
                          "condition": "", "similarity": sim})
    cands.sort(key=lambda c: (-c["confidence"], c["node_id"]))
    return cands


# ---------------------------------------------------------------- D-003 / D-004

def _uncertainty(conf):
    """D-001 不确定带：base=1-conf，上下界 = conf ± base*0.5（AEIS 同式）。"""
    try:
        c = max(0.0, min(1.0, float(conf)))
    except (TypeError, ValueError):
        c = 0.0
    base = 1.0 - c
    return {"confidence": round(c, 4),
            "lower": round(max(0.0, c - base * 0.5), 4),
            "upper": round(min(1.0, c + base * 0.5), 4),
            "method": "linear_local_approx"}


def _boundary_consistency(cg, path):
    """boundary 维：路径节点是否声明了适用边界/不确定条件（0-1）。"""
    if not path:
        return 0.0
    hit = 0
    for nid in path:
        e = _nodes(cg).get(nid) or {}
        tags = set(e.get("tags") or [])
        if "boundary" in tags or e.get("has_neg_conditions"):
            hit += 1
            continue
        node = cg.get(nid) or {}
        if re.search(r"不适用|不确定|边界|盲区", node.get("content") or ""):
            hit += 1
    return round(hit / len(path), 4)


def _branch_diversity(route):
    """balance 维：路径覆盖的推理通道维度数 / 4。

    AEIS 用语义坐标的维度数；md_cg 无语义坐标 → 用「来源通道
    （causal / semantic_induced）+ 边关系类型」作维度，保持 /4.0 归一化，
    语义仍是「防单一偏好主导」。
    """
    dims = set(route.get("sources") or []) | set(route.get("relations") or [])
    return round(min(1.0, len(dims) / 4.0), 4)


def extrapolation_validity(route):
    """D-003：局部线性外推有效性（smooth / jump / unknown）。"""
    confs = route.get("confs") or []
    if len(confs) < 2:
        return "unknown"
    steps = [confs[i] - confs[i + 1] for i in range(len(confs) - 1)]
    if not steps:
        return "unknown"
    return "smooth" if max(abs(s) for s in steps) <= 0.35 else "jump"


def hit_rate(cg):
    """历史命中率（无样本 → 基线 0.40，对齐 D-006）。"""
    h = _hit_history(cg)
    if not h:
        return BASE_HIT_RATE
    return round(sum(1 for x in h if x) / len(h), 4)


def score_route(cg, route, verification=None):
    """D-004 T_pred 四维评分（verification 跨路线共享，来自命中率）。"""
    trend = float(route.get("confidence") or 0.0)
    boundary = _boundary_consistency(cg, route.get("path") or [])
    ver = float(verification if verification is not None else hit_rate(cg))
    balance = _branch_diversity(route)
    composite = (W_TREND * trend + W_BOUNDARY * boundary
                 + W_VERIFICATION * ver + W_BALANCE * balance)
    return {"trend": round(trend, 4), "boundary": boundary,
            "verification": round(ver, 4), "balance": balance,
            "composite": round(composite, 4),
            "weights": {"trend": W_TREND, "boundary": W_BOUNDARY,
                        "verification": W_VERIFICATION, "balance": W_BALANCE}}


# ---------------------------------------------------------------- 盲区驱动

def find_blindspot(cg, blindspot_id):
    """按 id 定位盲区：unresolved 节点优先，其次盲区邻域（按 query 键）。"""
    from . import metacognition
    bid = str(blindspot_id or "").strip()
    if not bid:
        return None
    try:
        bs = metacognition.blindspots(cg)
    except Exception:
        return None
    for u in bs.get("unresolved") or []:
        if u.get("node_id") == bid:
            return {"id": bid, "kind": "unresolved",
                    "description": u.get("content") or ""}
    for it in bs.get("items") or []:
        q = str(it.get("query") or "")
        if q == bid or metacognition._key(q) == bid:
            return {"id": bid, "kind": "blindspot_cluster", "description": q,
                    "blindspot": it.get("blindspot"),
                    "defer": it.get("defer")}
    return None


def predictability(blindspot):
    """可预测性：盲区可显式声明 `# 可预测性：unknowable`。

    未声明 → predictable（默认按局部不可知原理生成候选，不宣称必然）。
    """
    txt = str((blindspot or {}).get("description") or "")
    m = re.search(r"可预测性[：:]\s*(\S+)", txt)
    return m.group(1).strip().lower() if m else "predictable"


def anchor_from_description(cg, description):
    """盲区描述 → 锚点节点（检索器打分，与 AEIS 的 LIKE→坐标回退同构）。

    只取**首个可用候选**：按标签/层过滤掉推断脚手架（`gap_hint`/`scene`）与
    负记忆（`unresolved`/`rejected`），其余按检索名次顺延。过滤理由见上方常量注释。
    候选全被过滤时返回 None（等价「无锚点」），由调用方按 no_anchor 处理，
    而不是硬凑一个不可起推的节点。
    """
    q = str(description or "").strip()
    if not q:
        return None
    try:
        results, _meta = cg.search(q, k=ANCHOR_FETCH_K, record=False, judge=False)
    except Exception:
        return None
    for item in results:
        nd = item[0] if isinstance(item, (tuple, list)) else item
        if not isinstance(nd, dict):
            continue
        fm = nd.get("frontmatter") or {}
        path = str(nd.get("path") or "")
        layer = str(fm.get("layer") or path.split("/")[0])
        if layer in ANCHOR_SKIP_LAYERS:
            continue
        if set(ANCHOR_SKIP_TAGS) & set(fm.get("tags") or []):
            continue
        nid = nd.get("id")
        if not nid:
            nid = os.path.basename(path)[:-3] if path.endswith(".md") else None
        if not nid:
            continue
        # 兜底：fs 派生的 id 可能是相对路径（如 unresolved/bs_x.md），归一为裸节点名
        if "/" in str(nid) and str(nid).endswith(".md"):
            nid = os.path.basename(str(nid))[:-3]
        return nid
    return None


# ---------------------------------------------------------------- 路线生成

def _label(cg, nid):
    node = cg.get(nid) or {}
    for line in (node.get("content") or "").splitlines():
        s = line.strip()
        if s:
            return re.sub(r"^#\s*", "", s)[:60]
    return nid


def _generate(cg, start_id, horizon, max_branches, semantic=True):
    """D-001 局部路径 DFS 生成候选未来（差异 3：增加 path 防环）。"""
    start_id = str(start_id or "").strip()
    if not start_id or start_id not in _nodes(cg):
        return {"status": "start_not_found", "start_id": start_id,
                "routes": [], "meta": {"reason": "节点不存在"}}
    horizon = max(1, min(int(horizon), HORIZON_HARD))
    max_branches = max(1, min(int(max_branches), MAX_BRANCHES_HARD))
    ver = hit_rate(cg)
    out = []

    def dfs(cur, path, confs, conds, sources, relations, depth):
        if depth >= horizon:
            return
        for cand in branch_candidates(cg, cur, semantic=semantic)[:max_branches]:
            nid = cand["node_id"]
            if nid in path:
                continue
            n_confs = confs + [cand["confidence"]]
            conf = 1.0
            for c in n_confs:
                conf *= c
            n_path = path + [nid]
            out.append({"path": n_path, "confidence": round(conf, 4),
                        "confs": n_confs,
                        "conditions": conds + [cand["condition"]],
                        "sources": sources + [cand["source"]],
                        "relations": relations + [cand["relation_type"]],
                        "last_source": cand["source"]})
            dfs(nid, n_path, n_confs, conds + [cand["condition"]],
                sources + [cand["source"]], relations + [cand["relation_type"]],
                depth + 1)

    dfs(start_id, [start_id], [], [], [], [], 0)
    for r in out:
        r["uncertainty_bound"] = _uncertainty(r["confidence"])
        r["extrapolation_validity"] = extrapolation_validity(r)
        r["score"] = score_route(cg, r, verification=ver)
        r["path_labels"] = [_label(cg, n) for n in r["path"]]
    return {"status": "ok", "start_id": start_id, "routes": out,
            "meta": {"horizon": horizon, "max_branches": max_branches,
                     "n_routes": len(out), "hit_rate": ver,
                     "note": "候选未来，非必然未来（D-001）",
                     "generated_at": time.time()}}


def _finalize(cg, res, sort, limit, log_type="predict_routes"):
    """排序 / 限流 / 留痕（预测本身可审计）。"""
    if sort not in SORT_KEYS:
        sort = "composite"
    res["routes"].sort(key=lambda r: (-float(r["score"].get(sort) or 0.0),
                                      r["path"]))
    if limit and int(limit) > 0:
        res["routes"] = res["routes"][:int(limit)]
    res["meta"]["sort"] = sort
    res["meta"]["n_returned"] = len(res["routes"])
    _append(cg, {"type": log_type, "t": time.time(),
                 "start_id": res.get("start_id"),
                 "blindspot_id": res["meta"].get("blindspot_id"),
                 "n_routes": res["meta"]["n_routes"],
                 "horizon": res["meta"]["horizon"], "sort": sort})
    return res


def routes(cg, start_id=None, blindspot_id=None, horizon=HORIZON_DEFAULT,
           max_branches=MAX_BRANCHES_DEFAULT, sort="composite", limit=0,
           semantic=True):
    """生成候选未来路线（D-001 ~ D-005）。

    start_id     起点节点 id
    blindspot_id 盲区驱动（unresolved 节点 id / 盲区邻域键）
    horizon      最大前推步数（默认 3）
    max_branches 每步最大分支数（默认 5）
    sort         composite | trend | verification | boundary | balance
    """
    if blindspot_id:
        return routes_from_blindspot(cg, blindspot_id, horizon=horizon,
                                     max_branches=max_branches, sort=sort,
                                     limit=limit, semantic=semantic)
    if not start_id:
        return {"status": "no_start", "routes": [],
                "meta": {"reason": "缺少 start_id 或 blindspot_id"}}
    res = _generate(cg, start_id, horizon, max_branches, semantic)
    if res.get("status") != "ok":
        return res
    return _finalize(cg, res, sort, limit)


def routes_from_blindspot(cg, blindspot_id, horizon=HORIZON_DEFAULT,
                          max_branches=MAX_BRANCHES_DEFAULT, sort="composite",
                          limit=0, semantic=True):
    """盲区驱动的生成式预测（v1.10）。"""
    bs = find_blindspot(cg, blindspot_id)
    if bs is None:
        return {"status": "blindspot_not_found", "blindspot_id": blindspot_id,
                "routes": [], "meta": {"reason": "未找到该盲区"}}
    if predictability(bs) == "unknowable":
        return {"status": "unpredictable", "reason": "structural_unknowability",
                "blindspot": bs, "routes": [],
                "meta": {"note": "盲区声明不可预测 → 不生成路线（拒绝编造）"}}
    anchor = anchor_from_description(cg, bs.get("description") or "")
    if not anchor:
        return {"status": "no_anchor", "blindspot": bs, "routes": [],
                "meta": {"reason": "盲区描述检索不到锚点节点"}}
    res = _generate(cg, anchor, horizon, max_branches, semantic)
    res["blindspot"] = bs
    if res.get("status") != "ok":
        return res
    res["meta"]["blindspot_id"] = blindspot_id
    res["meta"]["anchor"] = anchor
    return _finalize(cg, res, sort, limit, log_type="predict_routes_blindspot")


# ---------------------------------------------------------------- D-006 反馈闭环

_SAFE_LAYERS = ("knowledge", "contextual", "structural")


def _edge_target(edge):
    return edge.get("target") or edge.get("to") or edge.get("dst")


def _boost_incoming(cg, node_id, delta=EDGE_BOOST, actor="predict"):
    """命中 → 指向该节点的因果/时序边置信度 +delta。

    只改普通层（knowledge/contextual/structural）：self/anchor/rejected/
    unresolved/goals 带专用 frontmatter，整体重写会丢字段。
    """
    from . import chain
    changed = []
    for src, outs in list(chain.adjacency(cg).items()):
        if not any(tgt == node_id and chain.edge_rel(e) in CAUSAL_BRANCH_TYPES
                   for tgt, e in outs):
            continue
        node = cg.get(src)
        if not node:
            continue
        fm = node.get("frontmatter") or {}
        if fm.get("layer") not in _SAFE_LAYERS:
            continue
        edges, touched = [dict(e) for e in (fm.get("edges") or [])], False
        for ed in edges:
            if _edge_target(ed) != node_id:
                continue
            if chain.edge_rel(ed) not in CAUSAL_BRANCH_TYPES:
                continue
            old, new = _edge_conf(ed), min(1.0, _edge_conf(ed) + float(delta))
            if new != old:
                ed["confidence"] = round(new, 4)
                touched = True
        if not touched:
            continue
        # add() 会**重建** frontmatter：未显式传回的字段会被重置或丢失。
        # 尤其 sensitivity 缺省为 DEFAULT_SENSITIVITY("internal")——直接回写等于
        # 把 private/secret 节点**降级**；modality/created_at/证据计数同理。
        # 故除被覆盖的字段外，整表透传（actor 已单独传，避免重复关键字）。
        skip = {"id", "layer", "tags", "condition_space", "importance",
                "confidence", "edges", "verification_basis",
                "non_applicable_conditions", "actor", "path"}
        keep = {k: v for k, v in fm.items() if k not in skip}
        try:
            cg.add(src, node.get("content") or "",
                   layer=fm.get("layer") or "knowledge",
                   tags=fm.get("tags"),
                   condition_space=fm.get("condition_space"),
                   importance=fm.get("importance", 0.5),
                   confidence=fm.get("confidence", 0.6), edges=edges,
                   verification_basis=fm.get("verification_basis"),
                   non_applicable_conditions=fm.get("non_applicable_conditions"),
                   override=True, actor=actor, **keep)
            changed.append(src)
        except Exception:
            continue
    if changed:
        chain.invalidate_cache(cg)
    return changed


def dynamic_hit_threshold(cg, limit=HIT_HISTORY_MAX):
    """D-006 命中率动态校准（2.7.2 动态死区）。

    样本 < MIN_SAMPLES 不触发反思（小样本噪声）；阈值 = max(BASE, mean-2σ)。
    """
    h = _hit_history(cg, limit=limit)
    n = len(h)
    if n < MIN_SAMPLES:
        return {"threshold": BASE_HIT_RATE, "samples": n,
                "min_samples": MIN_SAMPLES, "reflect": False,
                "note": f"样本不足（{n}/{MIN_SAMPLES}），不触发反思"}
    mean = sum(1 for x in h if x) / n
    var = sum(((1.0 if x else 0.0) - mean) ** 2 for x in h) / n
    std = var ** 0.5
    th = max(BASE_HIT_RATE, mean - 2 * std)
    low = mean < th
    return {"threshold": round(th, 4), "samples": n, "mean": round(mean, 4),
            "std": round(std, 4), "min_samples": MIN_SAMPLES,
            "reflect": low,
            "note": "命中率低于动态阈值 → 建议反思（D-006）" if low
                    else "命中率正常"}


def feedback(cg, predicted_node_id, actual_node_id=None, hit=None, note="",
             actor="predict", sync_self=True):
    """预测反馈（D-006）：hit → 边置信度 +0.05；miss → 登记 rejected。

    `hit` 未显式给出时按 `predicted == actual` 判定。

    `sync_self`（默认 True）：反馈后**回写自我模型**——刷新自我状态卡的
    「预测校准」面，形成「预测 → 事实 → 误差 → 自我更新」闭环。
    自我模型是二阶观测，其刷新失败不阻塞一阶反馈结果。
    """
    pred = str(predicted_node_id or "").strip()
    act = str(actual_node_id or "").strip() or pred
    if hit is None:
        hit = (pred == act)
    hit = bool(hit)
    _append(cg, {"type": "feedback", "t": time.time(), "predicted": pred,
                 "actual": act, "hit": hit, "note": str(note or "")[:200]})
    out = {"ok": True, "hit": hit, "predicted": pred, "actual": act}
    if hit:
        out["boosted"] = _boost_incoming(cg, act, EDGE_BOOST, actor=actor)
    else:
        try:
            out["rejected_id"] = cg.add_rejected(
                hypothesis=f"预测未命中：{pred} → {act}",
                reason=str(note or "实际走向不同"),
                verification_basis="data", tags=["prediction", "miss"])
        except Exception as exc:                              # pragma: no cover
            out["rejected_error"] = str(exc)
    out.update(dynamic_hit_threshold(cg))
    # 闭环：预测误差 → 自我模型更新。延迟导入避免与 self_state 的循环依赖，
    # 且自我模型刷新属于二阶观测，失败不阻塞一阶反馈结果。
    if sync_self:
        try:
            from . import self_state
            out["self_state"] = self_state.refresh(cg, actor=actor)
        except Exception as exc:                          # pragma: no cover
            out["self_state_error"] = str(exc)
    return out


# ---------------------------------------------------------------- P2 盲区学习闭环

LEARN_LOG = "_learn.jsonl"
LEARN_MAX_STEPS = 8


def learn_log_path(cg):
    return os.path.join(getattr(cg, "root", "."), LEARN_LOG)


def _learn_append(cg, rec):
    try:
        append_jsonl(learn_log_path(cg), rec)
    except Exception:                              # noqa: BLE001
        pass


def _is_settled(cg, nid):
    """终点是否已达「可判定」态：知识层 ∧ CCG 五要素齐全。"""
    nid = str(nid or "").strip()
    if not nid:
        return False
    try:
        node = cg.get(nid) or {}
    except Exception:                              # noqa: BLE001
        return False
    fm = node.get("frontmatter") or {}
    if fm.get("layer") != "knowledge":
        return False
    try:
        from . import consolidate
        content = node.get("content") or ""
        return all(consolidate._has_ccg_line(content, k)
                   for k in consolidate.CCG_REQUIRED)
    except Exception:                              # noqa: BLE001
        return False


def _terminal_node(route):
    path = list((route or {}).get("path") or [])
    return path[-1] if path else None


def _write_gap(cg, bid, step, actor):
    """把待补线索写成 contextual 的 ``gap_hint`` 节点（幂等，非事实断言）。"""
    nid = "gap_%s" % hashlib.sha1(bid.encode("utf-8")).hexdigest()[:10]
    try:
        if cg.get(nid):
            return None
    except Exception:                              # noqa: BLE001
        pass
    content = ("# 功能名：盲区补全线索\n"
               "# 生效条件：%s\n"
               "# 子功能：为盲区补上条件/路径（待补，非既有事实）\n"
               "# 执行：%s\n"
               "# 不适用条件：结构性不可知\n"
               % (step.get("description") or bid, step.get("hint") or ""))
    try:
        cg.add(nid, content, layer="contextual",
               tags=["gap_hint", "learn"], importance=0.3,
               verification_basis="data", actor=actor,
               gap_blindspot=bid, gap_terminal=step.get("terminal"))
        return nid
    except Exception as exc:                       # noqa: BLE001
        step["write_error"] = "%s: %s" % (type(exc).__name__, exc)
        return None


def learn_blindspots(cg, blindspot_id=None, limit=LEARN_MAX_STEPS,
                     horizon=HORIZON_DEFAULT, max_branches=MAX_BRANCHES_DEFAULT,
                     apply=False, actor="insight", **extra):
    """盲区学习闭环（P2）：盲区 → 路线假设 → 终态判定 → 登记。

    终态五态（诚实优先，绝不编造）：

    - ``unknowable`` 盲区声明结构性不可知 → 不生成路线；
    - ``no_anchor``  描述检索不到锚点 → 无法起推；
    - ``unresolved`` 无任何可用路线 → 回填为待补线索；
    - ``carried``    有路线但终点未达可判定态 → 记为待验证假设；
    - ``resolved``   有路线且终点已在「知识层 + 五要素齐全」→ 认定补全。

    ``apply=True`` 时把 carried/unresolved 落成 contextual 的 ``gap_hint`` 节点
    （待补线索，非既有事实）；节点 id 由盲区 id 派生 ⇒ 重复执行幂等。
    """
    from . import metacognition
    if blindspot_id:
        one = find_blindspot(cg, blindspot_id)
        if not one:
            return {"ok": False, "action": "learn", "status": "not_found",
                    "reason": "未找到盲区：%s" % blindspot_id, "steps": [],
                    "summary": {}}
        items = [one]
    else:
        # 注意：metacognition.blindspots 返回的是**报表 dict**，不是条目列表。
        # 必须显式取 unresolved（未解问题，含 node_id/content）与 items（盲区聚类，
        # 含 query/blindspot/defer）两段，并归一成 find_blindspot 的同构条目，
        # 否则 list(dict) 只会拿到键名并在 dict(it) 处崩溃。
        try:
            blind = metacognition.blindspots(cg) or {}
        except Exception:                          # noqa: BLE001
            blind = {}
        items = []
        for it in (blind.get("items") or []):
            q = str(it.get("query") or "").strip()
            if not q:
                continue
            items.append({"id": q, "kind": "blindspot_cluster", "description": q,
                          "blindspot": it.get("blindspot"), "defer": it.get("defer")})
        for u in (blind.get("unresolved") or []):
            nid = str(u.get("node_id") or "").strip()
            if not nid:
                continue
            items.append({"id": nid, "kind": "unresolved",
                          "description": u.get("content") or ""})
    steps, written = [], []
    summary = {"unknowable": 0, "no_anchor": 0, "unresolved": 0,
               "carried": 0, "resolved": 0}
    for it in items[:max(1, int(limit))]:
        bs = dict(it or {})
        bid = str(bs.get("id") or bs.get("query") or "").strip()
        desc = str(bs.get("description") or bs.get("query") or bid)
        pred = predictability(bs)
        step = {"blindspot_id": bid, "description": desc[:200],
                "predictability": pred, "routes": 0, "terminal": None,
                "terminal_node": None, "hint": "", "written": None}
        if pred == "unknowable":
            step["terminal"] = "unknowable"
            step["hint"] = "盲区声明结构性不可知：不生成路线（拒绝编造）"
        else:
            res = (routes_from_blindspot(cg, bid, horizon=horizon,
                                         max_branches=max_branches, limit=3)
                   if bid else {"status": "no_start", "routes": []})
            rts = list(res.get("routes") or [])
            step["routes"] = len(rts)
            if res.get("status") in ("no_start", "no_anchor",
                                     "blindspot_not_found", "unpredictable"):
                step["terminal"] = "no_anchor"
                step["hint"] = "无可检索锚点：需先补描述或入口条件"
            elif not rts:
                step["terminal"] = "unresolved"
                step["hint"] = "无可用路线：需补因果边或放宽检索条件"
            else:
                settled = [r for r in rts if _is_settled(cg, _terminal_node(r))]
                if settled:
                    step["terminal"] = "resolved"
                    step["terminal_node"] = _terminal_node(settled[0])
                    step["hint"] = "已存在通往「知识层 + 五要素齐全」终点的路线"
                else:
                    step["terminal"] = "carried"
                    step["terminal_node"] = _terminal_node(rts[0])
                    step["hint"] = "路线终点未达可判定态：记为待验证假设"
        summary[step["terminal"]] = summary.get(step["terminal"], 0) + 1
        if apply and step["terminal"] in ("carried", "unresolved") and bid:
            step["written"] = _write_gap(cg, bid, step, actor)
            if step["written"]:
                written.append(step["written"])
        steps.append(step)
        rec = {"type": "learn_step", "t": time.time(), "actor": actor}
        rec.update(step)
        _learn_append(cg, rec)
    return {"ok": True, "action": "learn", "apply": bool(apply),
            "steps": steps, "summary": summary, "written": written,
            "note": ("apply=True：carried/unresolved 已落 gap_hint 待补线索；"
                     "resolved 仅表示已有可判定终点，未改动任何事实层节点")}


def stats(cg, limit=20):
    """预测统计：调用数、生成路线数、反馈样本、命中率、动态阈值。"""
    recs = _read_log(cg)
    calls = [r for r in recs
             if str(r.get("type") or "").startswith("predict_routes")]
    h = [bool(r.get("hit")) for r in recs if r.get("type") == "feedback"]
    return {"ok": True, "calls": len(calls),
            "routes_generated": sum(int(r.get("n_routes") or 0) for r in calls),
            "feedback_samples": len(h), "hits": sum(1 for x in h if x),
            "hit_rate": (round(sum(1 for x in h if x) / len(h), 4) if h
                         else BASE_HIT_RATE),
            "dynamic": dynamic_hit_threshold(cg),
            "recent": recs[-int(limit):] if limit else []}


# ---------------------------------------------------------------- 因果推理

def _path_conditions(cg, path):
    """路径上每跳的边条件（与节点对一一对应）。"""
    from . import chain
    adj = chain.adjacency(cg)
    conds = []
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        cond = ""
        for tgt, e in adj.get(a) or []:
            if tgt == b and chain.edge_rel(e) in CAUSAL_BRANCH_TYPES:
                cond = chain.edge_condition(e) or ""
                break
        conds.append({"from": a, "to": b, "condition": cond})
    return conds


def causal_path(cg, a_id, b_id, max_depth=5):
    """因果路径推理：A 能否沿因果/时序边到达 B（BFS，最短路径）。

    这是 D-002 过滤门的完整语义（不止直接边）：可达 → 可解释的因果关联；
    不可达 → 语义邻近只是共现，不得当作因果用于预测。
    """
    from . import chain
    start, goal = str(a_id or "").strip(), str(b_id or "").strip()
    if not start or not goal:
        return {"ok": False, "error": "missing_node",
                "detail": "需要 a_id 与 b_id"}
    if start == goal:
        return {"ok": True, "reachable": True, "path": [start], "length": 0,
                "conditions": []}
    depth_cap = max(1, int(max_depth))
    adj = chain.adjacency(cg)
    prev = {start: None}
    queue = [(start, 0)]
    while queue:
        cur, d = queue.pop(0)
        if d >= depth_cap:
            continue
        for tgt, e in adj.get(cur) or []:
            if chain.edge_rel(e) not in CAUSAL_BRANCH_TYPES or tgt in prev:
                continue
            prev[tgt] = cur
            if tgt == goal:
                path, node = [], goal
                while node is not None:
                    path.append(node)
                    node = prev[node]
                path.reverse()
                return {"ok": True, "reachable": True, "path": path,
                        "length": len(path) - 1,
                        "conditions": _path_conditions(cg, path)}
            queue.append((tgt, d + 1))
    return {"ok": True, "reachable": False, "path": None, "length": None,
            "max_depth": depth_cap,
            "note": "无因果路径：两者最多只是语义邻近（伪因果防护）"}


# ---------------------------------------------------------------- 自描述

def catalog():
    """决策编号 / 权重 / 校准参数 / 与 AEIS 的差异（供协议对照验证）。"""
    return {
        "module": "predict",
        "theory": "AEIS prediction.py · "
                  "PREDICTION-COMPLETION-PLAN-REV1-20260813-001",
        "channels": ["通道3 生成式（因果路线图）",
                     "通道4 语义式（经 D-002 伪因果过滤门）"],
        "decisions": {
            "D-001": "局部路径生成 + uncertainty_bound（候选未来，非必然未来）",
            "D-002": "语义邻近过滤门：因果链 / 共同父节点 / 偏好权重 > 0.5",
            "D-003": "局部线性近似 + extrapolation_validity（smooth/jump/unknown）",
            "D-004": "T_pred 四维评分 trend/boundary/verification/balance",
            "D-005": "AttentionPolicy 适配器 + 降级（边置信度排序）",
            "D-006": "命中率动态校准（样本 < 50 不触发反思）",
        },
        "weights": {"trend": W_TREND, "boundary": W_BOUNDARY,
                    "verification": W_VERIFICATION, "balance": W_BALANCE},
        "calibration": {"min_samples": MIN_SAMPLES,
                        "base_hit_rate": BASE_HIT_RATE,
                        "edge_boost": EDGE_BOOST,
                        "hit_history_max": HIT_HISTORY_MAX},
        "limits": {"horizon_default": HORIZON_DEFAULT,
                   "horizon_hard": HORIZON_HARD,
                   "max_branches_default": MAX_BRANCHES_DEFAULT,
                   "max_branches_hard": MAX_BRANCHES_HARD},
        "semantic": {"top_k": SEMANTIC_TOP_K, "min_sim": SEMANTIC_MIN_SIM,
                     "induced_confidence": SEMANTIC_CONF},
        "branch_types": list(CAUSAL_BRANCH_TYPES),
        "differs_from_aeis": [
            "语义邻近回退中文二元组 Jaccard（AEIS 优先语义坐标）",
            "命中历史持久化在 _prediction.jsonl（AEIS 在内存）",
            "DFS 增加 path 防环（AEIS 仅靠 horizon 截断）",
        ],
        "actions": ["routes", "routes_from_blindspot", "feedback", "stats",
                    "causal_path", "causal_gate", "catalog"],
    }
