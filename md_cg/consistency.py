# -*- coding: utf-8 -*-
"""md_cg · 节点间自动冲突检测（三级决策：情绪 → 反思 → 递归反思）

理论出处（本仓原文，非外部知识）：

  · **情绪 = 信息差的二阶变化 d²D/dt²**（`docs/智能的公理化基石.md` §十一，:412-510）
    工程端对应 `emotional_bias`（approaching / avoiding / stable），并且原文明确：
    「情绪通道**独立、不参与信任计算**」。故本模块 L0 只做**流程调度**，
    绝不改动 confidence / 资格判定——避免把情绪混进事实判断。

  · **反题 = 预测与事实冲突**（同文档 :529，条件论七操作之一）
    —— L1 一次冲突检测的理论名：新信息与既有条件的「反题」关系。

  · **递归必须受约束**（同文档 :273）：
    「递归必须受到深度、查询次数、节点数、循环检测和信息增益门槛约束。
     若递归没有减少候选空间，就不应继续搜索。」
    —— L2 递归反思的硬约束（本模块按此实现，而非无限展开）。

  · **四态路由** ACCEPT / REJECT / DEFER / BLINDSPOT（同文档 :721；
    `md_cg/mdcg.py` 四态定义）—— L1 的输出语义。

  · **知识飞轮：误差 → 补条件 → 结构更新**（同文档 :725；`mdcg.py:1001`
    `flywheel_step`）—— 冲突**自动**落 unresolved，误差是结构更新的输入。

  · **纪律四要素同构**（`docs/工作纪律_认知图条目_v1.1.json`；
    `consolidate.py` CCG 四要素）—— 「不能违反纪律」= 新内容不得命中纪律节点的
    `negative.reject`（不适用条件）。纪律节点用 tag/前缀识别，不硬编码具体条目。

三级决策（顺序即语义，越靠前越廉价）：

    L0 情绪    ：二阶信号，快速方向调整（approaching / stable / avoiding）——不裁决资格
    L1 反思    ：一次条件级冲突检测（自否定 / 纪律违反 / 条件互斥）→ 四态
    L2 递归反思：L1 未决 → 沿关系链递归找「区分条件」；受深度/节点数/循环/增益门槛约束

冲突自动触发飞轮：verdict ∈ {REJECT, DEFER, BLINDSPOT} 且 auto_flywheel →
    `cg.flywheel_step({query, expected_state:"ACCEPT", actual_state:verdict, missing})`

留痕 `_consistency.jsonl`（append-only）：每条判定可审计「为什么冲突 / 为什么放行」。

诚实边界：本模块是**条件级（结构化）**冲突检测，不是语义蕴含证明。它判断的是
「声明的适用/不适用条件是否互相覆盖」，而非「两句话在逻辑上是否矛盾」。
无法建立可比对路径时返回 BLINDSPOT，不假装确定。
"""
from __future__ import annotations

import json
import os
import time

from .mdcg import expand_query_terms_weighted

# --------------------------------------------------------------------------
# 常量（全部可审计、可调）
# --------------------------------------------------------------------------

LOG_FILE = "_consistency.jsonl"

MAX_SCAN = 200       # 单次检测最多比对的既有节点数（防 O(N) 爆炸）
MAX_DEPTH = 3        # L2 递归深度上限（对齐 :273）
MAX_NODES = 60       # L2 递归展开节点上限（对齐 :273）
MIN_GAIN = 0.15      # 信息增益门槛：候选空间减少比例低于此值即停（对齐 :273）

CLASH_HIGH = 0.6     # 条件互相覆盖阈值 → 明确互斥
CLASH_LOW = 0.35     # 条件部分覆盖阈值 → 待定
SELF_NEGATION = 0.5  # 自否定阈值：负条件被自身正文强命中

EMO_AVOID = 0.70     # 冲突强度 ≥ 此值 → avoiding
EMO_APPROACH = 0.30  # 冲突强度 ≤ 此值 → approaching

# 纪律节点识别（tag 或 id 前缀；不硬编码具体纪律条目）
DISCIPLINE_TAGS = ("discipline", "纪律", "work_discipline", "rule", "规则", "戒律")

VERDICTS = ("ACCEPT", "REJECT", "DEFER", "BLINDSPOT")


class ConsistencyError(Exception):
    """硬冲突：写入被拒（自否定 / 违反纪律）。"""

    def __init__(self, verdict, reason, conflicts=None):
        self.verdict = verdict
        self.reason = reason
        self.conflicts = conflicts or []
        super().__init__(f"[{verdict}] {reason}")


# --------------------------------------------------------------------------
# 原语：延迟导入 mdcos（避免 mdcg ← mdcos ← consistency 的循环导入）
# --------------------------------------------------------------------------

def _prims():
    """取 md_cg 已有的条件匹配原语（条件论「反题」的既有实现）。"""
    from .mdcos import (_ccg_field, _declared_conditions, _neg_hit,
                        _weighted_coverage)
    return _ccg_field, _declared_conditions, _neg_hit, _weighted_coverage


def _dedup(xs):
    out = []
    for x in xs:
        s = str(x).strip()
        if s and s not in out:
            out.append(s)
    return out


def _edge_targets(fm):
    """节点声明的出边目标（兼容 dict / str 两种形态）。"""
    out = []
    for e in (fm.get("edges") or []):
        if isinstance(e, dict):
            t = e.get("to") or e.get("target") or e.get("node") or e.get("id")
        else:
            t = e
        if t:
            out.append(str(t))
    return out


def _is_discipline(fm, node_id):
    tags = {str(t).lower() for t in (fm.get("tags") or [])}
    if tags & set(DISCIPLINE_TAGS):
        return True
    return str(node_id).startswith(("discipline_", "work_discipline"))


def _new_terms(content, condition_space, non_applicable_conditions):
    """新节点声明的（正条件, 负条件）——与既有节点同口径解析。"""
    _ccg_field, _declared, _neg_hit, _cov = _prims()
    pos, neg = [], []
    v = _ccg_field(content or "", "生效条件")
    if v:
        pos.append(v)
    for k, val in (condition_space or {}).items():
        if str(k).startswith("__") or k == "time_window":
            continue
        if isinstance(val, (list, tuple, set)):
            pos.extend(str(x) for x in val)
        elif val not in (None, ""):
            pos.append(str(val))
    neg.extend(str(x) for x in (non_applicable_conditions or []))
    v2 = _ccg_field(content or "", "不适用条件")
    if v2:
        neg.append(v2)
    return _dedup(pos), _dedup(neg)


def _ban_hit(content, neg_texts):
    """纪律禁令命中：去掉「不得/禁止/…」前缀后，短语是否**整体出现**在正文中。

    比词袋匹配更严格——纪律条目通常是精确的禁令短语，用子串命中可避免
    「生产」这类子词把无关内容误判为违纪（假阳性会毁掉纪律的可信度）。
    """
    for x in (neg_texts or []):
        s = str(x).strip()
        for p in ("不得", "禁止", "严禁", "不能", "不可", "不要", "勿"):
            if s.startswith(p):
                s = s[len(p):].strip()
                break
        if len(s) >= 2 and s in (content or ""):
            return True
    return False


def _body_text(content):
    """去掉 CCG 声明行（`# 字段：值`）后的正文。

    自否定看的是「正文/生效条件是否与不适用条件矛盾」，不能把节点自己声明的
    `# 不适用条件：X` 当成 X 出现在正文里——否则**每个**声明了不适用条件的
    正常节点都会被误判为自相矛盾（真实 CCG 条目普遍带该字段）。
    """
    out = []
    for line in (content or "").splitlines():
        s = line.strip()
        if s.startswith("#") and ("：" in s or ":" in s):
            continue
        out.append(line)
    return "\n".join(out)


# --------------------------------------------------------------------------
# L0 情绪通道（信息差二阶变化）
# --------------------------------------------------------------------------

def emotional_bias(conflict_strength, prev_strength=None):
    """L0：把冲突强度映射为情绪倾向（approaching / stable / avoiding）。

    对齐 `智能的公理化基石.md` §十一：情绪是**信息差的二阶变化** d²D/dt²。
    这里的工程代理：
      · 一阶 d1  = conflict_strength（新信息与既有结构的相斥程度）
      · 二阶 d2  = 本次 d1 − 上次 d1（用留痕里的上一条强度作基线）
      · d2 > 0 → 信息差在**扩大**（越来越不顺）→ avoiding
      · d2 < 0 → 信息差在**收敛**（越来越顺）   → approaching

    重要（原文强制）：情绪通道**独立、不参与信任/资格计算**，
    只影响「是否升级到递归反思」的调度决策。
    """
    c = max(0.0, min(1.0, float(conflict_strength or 0.0)))
    if prev_strength is None:
        d2 = 0.0
    else:
        d2 = c - max(0.0, min(1.0, float(prev_strength)))
    if c >= EMO_AVOID or d2 > 0.2:
        bias = "avoiding"
    elif c <= EMO_APPROACH and d2 <= 0:
        bias = "approaching"
    else:
        bias = "stable"
    return {"bias": bias, "conflict_strength": round(c, 4),
            "d2": round(d2, 4),
            "note": "情绪通道独立，不参与信任/资格计算（智能论 §十一）"}


def _last_strength(cg):
    """上一条留痕的冲突强度（二阶差分的基线）。流式读，不载全量。"""
    p = os.path.join(cg.root, LOG_FILE)
    if not os.path.exists(p):
        return None
    last = None
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    last = json.loads(line).get("conflict_strength")
                except (ValueError, TypeError):
                    pass
    except OSError:
        return None
    return last


# --------------------------------------------------------------------------
# L2 递归反思（受深度 / 节点数 / 循环 / 增益门槛约束）
# --------------------------------------------------------------------------

def _recursive_reflect(cg, seeds, tw_pos, tw_neg, max_depth=MAX_DEPTH,
                       max_nodes=MAX_NODES, min_gain=MIN_GAIN):
    """递归反思：沿关系链找「区分条件」，每层检查信息增益。

    收敛条件（任一）：
      · 找到区分节点（其负条件排除新节点 / 其正条件与新负条件互斥）→ resolved
      · 增益 < min_gain（候选空间没变少，继续搜没意义，对齐 :273）→ 停
      · 超深度 / 超节点预算 / 循环检测命中 → 停
    """
    _ccg_field, _declared, _neg_hit, _cov = _prims()
    seed_set = {s for s in (seeds or []) if s}
    visited, frontier, trace = set(), [s for s in (seeds or []) if s], []
    nodes_visited, last_gain = 0, 0.0
    for d in range(1, int(max_depth) + 1):
        if not frontier:
            return {"resolved_by": [], "depth": d - 1, "nodes_visited": nodes_visited,
                    "gain": last_gain, "stopped_by": "frontier_exhausted",
                    "trace": trace}
        nxt, discriminators = [], []
        for nid in frontier:
            if nid in visited:
                continue
            visited.add(nid)
            nodes_visited += 1
            if nodes_visited > max_nodes:
                return {"resolved_by": [], "depth": d,
                        "nodes_visited": nodes_visited, "gain": last_gain,
                        "stopped_by": "node_budget", "trace": trace}
            node = cg.get(nid) or {}
            fm = node.get("frontmatter") or {}
            body = node.get("content") or ""
            e_pos, e_neg = _declared(fm, body)
            # 冲突源（seed）自身不是区分条件：它与新节点的关系正是待分辨的
            # 冲突本身，把它当作「已分辨」会制造假的 resolved（增益虚高 1.0）。
            if nid not in seed_set:
                if e_neg and tw_pos and _cov(tw_pos, " ".join(e_neg)) >= CLASH_HIGH:
                    discriminators.append(nid)
                elif e_pos and tw_neg and _cov(tw_neg, " ".join(e_pos)) >= CLASH_HIGH:
                    discriminators.append(nid)
            nxt.extend(_edge_targets(fm))
        if discriminators:
            return {"resolved_by": discriminators, "depth": d,
                    "nodes_visited": nodes_visited, "gain": 1.0,
                    "stopped_by": "resolved", "trace": trace}
        fresh = [x for x in dict.fromkeys(nxt) if x not in visited]
        last_gain = len(fresh) / float(max(1, len(frontier)))
        trace.append({"depth": d, "frontier": len(frontier),
                      "fresh": len(fresh), "gain": round(last_gain, 4)})
        if last_gain < min_gain:
            return {"resolved_by": [], "depth": d, "nodes_visited": nodes_visited,
                    "gain": round(last_gain, 4),
                    "stopped_by": "gain_below_threshold", "trace": trace}
        frontier = fresh
    return {"resolved_by": [], "depth": int(max_depth),
            "nodes_visited": nodes_visited, "gain": round(last_gain, 4),
            "stopped_by": "depth_exceeded", "trace": trace}


# --------------------------------------------------------------------------
# 主入口：三级决策
# --------------------------------------------------------------------------

def check(cg, content, layer=None, condition_space=None,
          non_applicable_conditions=None, tags=None, exclude=None,
          limit=MAX_SCAN, depth=MAX_DEPTH, auto_flywheel=False,
          query=None):
    """节点间自动冲突检测（L0 情绪 → L1 反思 → L2 递归反思）。

    返回完整判据（可审计）：
      verdict / reason / conflict_strength / emotional / conflicts[] /
      recursion{} / missing[] / unresolved_id（若触发飞轮）

    verdict：
      ACCEPT    无冲突，或新节点未声明条件（无从冲突）
      REJECT    硬冲突：自否定 / 违反纪律
      DEFER     条件互斥但可能可分辨（交给 L2 递归或飞轮）
      BLINDSPOT 有条件声明，但既有节点全无声明 → 无法建立比对路径（不假装确定）
    """
    _ccg_field, _declared, _neg_hit, _cov = _prims()
    content = content or ""
    pos, neg = _new_terms(content, condition_space, non_applicable_conditions)
    tw_pos = expand_query_terms_weighted(" ".join(pos)) if pos else {}
    tw_neg = expand_query_terms_weighted(" ".join(neg)) if neg else {}
    tw_content = expand_query_terms_weighted(content) if content else {}

    conflicts, hard = [], []
    strength, scanned, comparable = 0.0, 0, 0

    # ---- L1-a 自否定：自己的负条件排除自己的生效条件/正文 ----
    body = _body_text(content)
    if neg and (_ban_hit(" ".join(pos), neg) or _ban_hit(body, neg)):
        hard.append({"type": "self_negation", "with": None,
                     "detail": "不适用条件命中自身生效条件/正文：条件自相矛盾",
                     "score": 1.0})
        strength = 1.0
    elif neg and _cov(tw_neg, body) >= SELF_NEGATION:
        hard.append({"type": "self_negation", "with": None,
                     "detail": "负条件与正文强相关：条件与结论互斥",
                     "score": round(_cov(tw_neg, body), 4)})
        strength = max(strength, round(_cov(tw_neg, body), 4))

    # ---- L1-b 与既有节点的条件级比对（反题） ----
    nodes = ((getattr(cg, "index", None) or {}).get("nodes") or {})
    seeds = []
    for nid, e in nodes.items():
        if exclude and nid == exclude:
            continue
        if layer and e.get("layer") != layer:
            continue
        if scanned >= int(limit):
            break
        scanned += 1
        node = cg.get(nid) or {}
        fm = node.get("frontmatter") or {}
        body = node.get("content") or ""
        e_pos, e_neg = _declared(fm, body)
        if not e_pos and not e_neg:
            continue
        comparable += 1
        # 纪律违反：**正文行为**命中纪律节点的不适用条件（negative.reject）
        # —— 这是「不能违反纪律」，与「条件互斥」是两回事：前者看做了什么，
        #    后者看声明的条件是否互相覆盖。
        if _is_discipline(fm, nid) and e_neg and _ban_hit(content, e_neg):
            hard.append({"type": "discipline", "with": nid,
                         "with_layer": e.get("layer"),
                         "detail": "命中纪律节点的不适用条件（negative.reject）",
                         "score": 1.0})
            seeds.append(nid)
            strength = 1.0
            continue
        c1 = _cov(tw_pos, " ".join(e_neg)) if (tw_pos and e_neg) else 0.0
        c2 = _cov(tw_neg, " ".join(e_pos)) if (tw_neg and e_pos) else 0.0
        c = max(c1, c2)
        if c < CLASH_LOW:
            continue
        conflicts.append({
            "type": "condition_clash", "with": nid,
            "with_layer": e.get("layer"),
            "detail": ("新节点适用条件落在既有节点不适用区"
                       if c1 >= c2 else "新节点不适用条件覆盖既有节点适用区"),
            "score": round(c, 4),
            "pos_side": _dedup(pos)[:6], "neg_side": _dedup(neg)[:6]})
        seeds.append(nid)
        strength = max(strength, c)

    # ---- L0 情绪（独立通道，只调度不裁决） ----
    emo = emotional_bias(strength, _last_strength(cg))

    # ---- L1 四态判定 ----
    recursion = None
    missing = []
    allc = hard + conflicts
    if hard:
        verdict = "REJECT"
        reason = "；".join(h["detail"] for h in hard)
    elif strength >= CLASH_HIGH:
        verdict = "DEFER"
        reason = "条件互斥：需补区分条件后才能判定"
    elif strength >= CLASH_LOW:
        verdict = "DEFER"
        reason = "条件部分覆盖：待确认是否互斥"
    elif comparable == 0 and (pos or neg):
        verdict = "BLINDSPOT"
        reason = "既有节点均未声明条件：无法建立比对路径"
    else:
        verdict = "ACCEPT"
        reason = "无冲突"

    # ---- L2 递归反思（仅对 DEFER，且情绪未指向 approaching 的快速放行） ----
    if verdict == "DEFER" and int(depth) > 0 and emo["bias"] != "approaching":
        recursion = _recursive_reflect(cg, seeds, tw_pos, tw_neg,
                                       max_depth=int(depth))
        if recursion["stopped_by"] == "resolved":
            # 找到区分条件 → 冲突可分辨，降级为待定（不直接放行，留人工/飞轮）
            reason = f'{reason}；已找到区分条件 {recursion["resolved_by"][:3]}'
        else:
            missing.append({
                "need": "区分条件",
                "why": f'递归反思停止于 {recursion["stopped_by"]}'
                       f'（深度 {recursion["depth"]}，增益 {recursion["gain"]}）',
                "conflicts": [c["with"] for c in allc if c.get("with")][:5]})

    rec = {"t": time.time(), "layer": layer, "verdict": verdict,
           "reason": reason, "conflict_strength": round(strength, 4),
           "emotional": emo, "conflicts": allc, "recursion": recursion,
           "missing": missing, "scanned": scanned, "comparable": comparable,
           "pos": pos[:6], "neg": neg[:6],
           "actor": getattr(cg, "actor", "unknown")}

    # ---- 冲突自动触发飞轮（误差 → 补条件 → 结构更新） ----
    if auto_flywheel and verdict in ("REJECT", "DEFER", "BLINDSPOT"):
        rec["unresolved_id"] = _fire_flywheel(cg, query or content, verdict,
                                              reason, missing)
    log(cg, rec)
    return rec


def _fire_flywheel(cg, query, verdict, reason, missing):
    """把冲突作为「误差」投给知识飞轮，返回 unresolved 条目 id（失败不阻塞写入）。"""
    step = getattr(cg, "flywheel_step", None)
    if step is None:
        return None
    try:
        r = step({"query": (query or "")[:200], "expected_state": "ACCEPT",
                  "actual_state": verdict, "missing": reason,
                  "detail": missing})
        if isinstance(r, dict):
            return r.get("unresolved_id") or r.get("id")
    except Exception:
        return None
    return None


# --------------------------------------------------------------------------
# 留痕 / 统计 / 自描述
# --------------------------------------------------------------------------

def log(cg, rec):
    """append-only 留痕：每条判定可审计。"""
    p = os.path.join(cg.root, LOG_FILE)
    try:
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return rec


def history(cg, limit=100):
    """最近冲突判定留痕（倒序）。"""
    p = os.path.join(cg.root, LOG_FILE)
    if not os.path.exists(p):
        return []
    out = []
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except (ValueError, TypeError):
                    pass
    except OSError:
        return []
    return out[-int(limit):][::-1] if limit else out[::-1]


def summary(cg):
    """冲突面汇总（流式计数，供 health 审计）。"""
    p = os.path.join(cg.root, LOG_FILE)
    by_verdict, by_bias, total = {}, {}, 0
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    total += 1
                    v = r.get("verdict")
                    by_verdict[v] = by_verdict.get(v, 0) + 1
                    b = (r.get("emotional") or {}).get("bias")
                    if b:
                        by_bias[b] = by_bias.get(b, 0) + 1
        except OSError:
            pass
    return {"records": total, "by_verdict": by_verdict, "by_bias": by_bias,
            "max_scan": MAX_SCAN, "max_depth": MAX_DEPTH,
            "min_gain": MIN_GAIN}


def catalog():
    """自描述：三级决策 + 四态 + 递归约束（供 MCP / 文档对照验证）。"""
    return {
        "levels": {
            "L0_emotion": {
                "theory": "情绪 = 信息差二阶变化 d²D/dt²（智能论 §十一）",
                "outputs": ["approaching", "stable", "avoiding"],
                "constraint": "独立通道，不参与信任/资格计算，只做流程调度",
                "thresholds": {"avoid": EMO_AVOID, "approach": EMO_APPROACH},
            },
            "L1_reflect": {
                "theory": "反题 = 预测与事实冲突（条件论七操作）",
                "checks": ["self_negation", "discipline", "condition_clash"],
                "verdicts": list(VERDICTS),
                "thresholds": {"high": CLASH_HIGH, "low": CLASH_LOW},
            },
            "L2_recursive_reflect": {
                "theory": "递归受深度/节点数/循环/信息增益门槛约束（智能论 :273）",
                "max_depth": MAX_DEPTH, "max_nodes": MAX_NODES,
                "min_gain": MIN_GAIN,
                "stop_reasons": ["resolved", "gain_below_threshold",
                                 "depth_exceeded", "node_budget",
                                 "frontier_exhausted"],
            },
        },
        "auto_flywheel": {
            "theory": "知识飞轮：误差 → 补条件 → 结构更新（智能论 :725）",
            "triggers_on": ["REJECT", "DEFER", "BLINDSPOT"],
        },
        "discipline_detection": {"tags": list(DISCIPLINE_TAGS),
                                 "id_prefixes": ["discipline_", "work_discipline"]},
        "honest_boundary": "条件级（结构化）冲突检测，非语义蕴含证明；无法比对时 BLINDSPOT",
    }
