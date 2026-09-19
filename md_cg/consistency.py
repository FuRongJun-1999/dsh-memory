# -*- coding: utf-8 -*-
"""md_cg · 节点间自动冲突检测（三级决策：情绪 → 反思 → 递归反思）

理论出处（本仓原文，非外部知识）：

  · **情绪 = 信息差的二阶变化 d²D/dt²**（`docs/theory/智能的公理化基石.md` §十一，:412-510）
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

# —— 第二类关系（同条件空间 · 结论槽取值分歧）阈值；均由探针实测标定 ——
# run_probe_samecond.py 实测：同条件 same_cond=1.0 / 异条件空间 0.328 → 0.75 可分
SAME_COND_HIGH = 0.75   # 同侧条件重合 → 判定「同一条件空间」
# 实测结论槽（子功能）：同槽 1.0 / 同主语异属性 0.14 / 异主题 0.0 → 0.6 可分
SLOT_HIGH = 0.6         # 结论槽（功能名/子功能）重合 → 判定「同一件事」
# 实测：逐字重复 1.0 / 同槽不同值 0.61 / 同值异措辞 0.74 → 0.95 只排除逐字重复
CONCLUSION_SAME = 0.95  # 正文几乎逐字相同 → 属「重复」（该合并），不算冲突

EMO_AVOID = 0.70     # 冲突强度 ≥ 此值 → avoiding
EMO_APPROACH = 0.30  # 冲突强度 ≤ 此值 → approaching

# 纪律节点识别（tag 或 id 前缀；不硬编码具体纪律条目）
DISCIPLINE_TAGS = ("discipline", "纪律", "work_discipline", "rule", "规则", "戒律")

VERDICTS = ("ACCEPT", "REJECT", "DEFER", "BLINDSPOT")


# 生效条件：以 verdict 与 reason 构造异常（消息 `[{verdict}] {reason}`），conflicts 传假值（None/空容器等，源码 `conflicts or []`）时 self.conflicts 为 []，传真值时原样保留；
class ConsistencyError(Exception):
    """硬冲突：写入被拒（自否定 / 违反纪律）。"""

# 生效条件：verdict 与 reason 必传并赋给同名属性、拼成异常消息 `[{verdict}] {reason}`；conflicts 为假值（None/空容器等，源码 `conflicts or []`）时 self.conflicts 回落到 []，为真值时原样保留；
    def __init__(self, verdict, reason, conflicts=None):
        self.verdict = verdict
        self.reason = reason
        self.conflicts = conflicts or []
        super().__init__(f"[{verdict}] {reason}")


# --------------------------------------------------------------------------
# 原语：延迟导入 mdcos（避免 mdcg ← mdcos ← consistency 的循环导入）
# --------------------------------------------------------------------------

# 生效条件：无 required 形参，任一调用返回 ( _ccg_field, _declared_conditions, _neg_hit, _weighted_coverage ) 四元组；
def _prims():
    """取 md_cg 已有的条件匹配原语（条件论「反题」的既有实现）。"""
    from .mdcos import (_ccg_field, _declared_conditions, _neg_hit,
                        _weighted_coverage)
    return _ccg_field, _declared_conditions, _neg_hit, _weighted_coverage


# 生效条件：xs 为可迭代对象时，逐项 str(x).strip() 后仅当结果非空且未出现过才加入 out 并返回 out；xs 为 None/False/0 时在 for 处迭代失败（TypeError）；
def _dedup(xs):
    out = []
    for x in xs:
        s = str(x).strip()
        if s and s not in out:
            out.append(s)
    return out


# 生效条件：fm 给出时，遍历 fm.get("edges")（缺键或假值按空列表）中元素，dict 元素按 to→target→node→id 取首个真值、非 dict 元素直接作候选，候选真值时 str(t) 加入 out 并返回；
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


# 生效条件：fm 与 node_id 给出时，若 fm.get("tags")（缺键/假值按空）小写后与 DISCIPLINE_TAGS 有交集，或 str(node_id) 以 "discipline_" 或 "work_discipline" 开头，返回 True；否则返回 False；
def _is_discipline(fm, node_id):
    tags = {str(t).lower() for t in (fm.get("tags") or [])}
    if tags & set(DISCIPLINE_TAGS):
        return True
    return str(node_id).startswith(("discipline_", "work_discipline"))


# --------------------------------------------------------------------------
# 模式分离的支持件（maintain.separate 复用；也供 insight.reconstruct 取线索）
# --------------------------------------------------------------------------

#: 分离边的关系名：两个节点「看起来像，但条件不同，互为不同情境」
SEPARATION_REL = "distinct_from"


# 生效条件：fm 给出时，仅处理 fm.get("edges")（缺键/假值按空）中的 dict 元素，relation_type 或 relation（缺省空串）小写等于 SEPARATION_REL 时，按 target→to→id 取首个真值且未重复则加入 out；
def separation_targets(fm):
    """节点已声明的分离对象（`distinct_from` 出边），用于幂等与去重。"""
    out = []
    for e in (fm.get("edges") or []):
        if not isinstance(e, dict):
            continue
        rel = str(e.get("relation_type") or e.get("relation") or "").strip().lower()
        if rel != SEPARATION_REL:
            continue
        t = e.get("target") or e.get("to") or e.get("id")
        if t and str(t) not in out:
            out.append(str(t))
    return out


# 生效条件：fm 与 content 给出时，以 content（假值按空串）、fm.get("condition_space")、fm.get("non_applicable_conditions") 解析，返回去重后的 (set(pos), set(neg))；
def condition_terms(fm, content):
    """节点声明的（正条件, 负条件）词面集合——分离判定与重构取线索共用。"""
    pos, neg = _new_terms(content or "", fm.get("condition_space"),
                          fm.get("non_applicable_conditions"))
    return set(pos), set(neg)


# 生效条件：pos_a、neg_a、pos_b、neg_b 给出的条件词面小写化后，两侧并集均空时返回 overlap 0.0、distinct False；否则计算交集/并集比并返回 distinct 为 overlap <= CLASH_LOW；
def condition_distinct(pos_a, neg_a, pos_b, neg_b):
    """两组条件是否「实质不同」：任一侧条件词面几乎不重合即为不同情境。

    返回 {'overlap': 覆盖率, 'distinct': bool}。overlap 高 = 条件相同（是重复，
    该合并）；overlap 低 = 条件不同（该分离，避免混为一体）。
    """
    a = {str(x).lower() for x in (set(pos_a) | set(neg_a))}
    b = {str(x).lower() for x in (set(pos_b) | set(neg_b))}
    if not a and not b:
        return {"overlap": 0.0, "distinct": False,
                "note": "双方均未声明条件：无从判定分离（不假装确定）"}
    union = a | b
    overlap = (len(a & b) / float(len(union))) if union else 0.0
    return {"overlap": round(overlap, 4), "distinct": overlap <= CLASH_LOW}


# 生效条件：content、condition_space、non_applicable_conditions 给出时，content 的 `生效条件` 字段与 condition_space 中键不以 `__` 开头且不为 `time_window` 的值并入 pos（list/tuple/set 展平，其他非 None/"" 值 str 化），non_applicable_conditions 各项及 content 的 `不适用条件` 字段值并入 neg，最后 _dedup 返回；
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


# 生效条件：content 与 neg_texts 给出时，neg_texts 中任一短语去掉「不得/禁止/严禁/不能/不可/不要/勿」前缀且长度 >=2 后作为子串出现在 content（假值按空串）中则返回 True，否则 False；
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


# 生效条件：content 为真时按行过滤，跳过 strip 后以 "#" 开头且含全角或半角冒号的行，其余原行以换行连接返回；content 假值按空串返回 ""；
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


# 生效条件：content 给出时（假值按空串）解析 CCG 的 `# 功能名` 与 `# 子功能` 字段并返回两者；
def _slot_text(content):
    """结论槽：CCG 声明的 `# 功能名` / `# 子功能`（结构字段，非正文词面）。

    为什么需要它：L1-c 要判「两条记忆是不是在讲同一件事」，但**词面覆盖率测不了**
    ——探针实测「同属性不同值」0.612 vs「异属性」0.623（负样本反超），
    因为两者与旧正文的通用词重合度相当。CCG 的槽位字段才是「在讲哪件事」的
    结构化代理，与 L1-b 用 condition_space 判「在什么条件下」同构。

    字段缺失 → 返回空串 → L1-c 不触发（保守：无从比对时不假装确定）。
    """
    _ccg_field, _declared, _neg_hit, _cov = _prims()
    return (_ccg_field(content or "", "功能名"),
            _ccg_field(content or "", "子功能"))


# --------------------------------------------------------------------------
# L0 情绪通道（信息差二阶变化）
# --------------------------------------------------------------------------

# 生效条件：conflict_strength 被夹取到 [0,1]（假值按 0.0），prev_strength 为 None 时 d2=0.0，否则 d2=c-夹取后的 prev_strength；按 c>=EMO_AVOID 或 d2>0.2 返回 avoiding，或 c<=EMO_APPROACH 且 d2<=0 返回 approaching，否则 stable；
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


# 生效条件：cg 给出时，若 cg.root 下 LOG_FILE 可读，则逐行解析 JSON 并取 .get("conflict_strength")，返回最后一条可解析记录的该键值（缺键或值为 None 则为 None）；路径不可用或 OSError 返回 None；
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

# 生效条件：以 cg 节点图、seeds 中非空项为初始 frontier、tw_pos/tw_neg 词权，在 d=1..int(max_depth) 每轮先判 frontier 空返回 frontier_exhausted，再逐 nid 处理时若 nodes_visited > max_nodes 先返回 node_budget（可先于同层 discriminators），否则处理完该层后有 discriminators（非 seed_set 节点声明条件与 tw_pos/tw_neg 覆盖 >= CLASH_HIGH）返回 resolved，否则 last_gain < min_gain 返回 gain_below_threshold，循环耗尽返回 depth_exceeded；seeds 假值时 frontier 空，在 d=1 进入循环后由首判返回 frontier_exhausted（depth=0）；
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

# 生效条件：以 cg.index.nodes 为既有节点、content（假值按 ""）经 _new_terms 得 pos/neg 并算 tw_pos/tw_neg，按循环中 hard（自否定或纪律命中）→ divergences（同条件槽且 concl < CONCLUSION_SAME）→ strength ≥ CLASH_HIGH → strength ≥ CLASH_LOW → comparable==0 且 (pos or neg) → 否则 ACCEPT 的顺序定 verdict；DEFER 且 int(depth)>0 且 emo["bias"] != "approaching" 时调 _recursive_reflect 补 recursion，auto_flywheel 且 verdict∈{REJECT,DEFER,BLINDSPOT} 时加 unresolved_id，最后 log 并返回 rec；
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
    # 结论文本词权（结论比对专用）：**去 CCG 声明行**。模板行（`# 功能名` /
    # `# 子功能` 等）在两条节点间逐字相同，若混入会稀释结论覆盖率——实测
    # 逐字重复仅 0.32、同槽不同值 0.61，与异属性（0.62）不可分。去模板才可判。
    tw_content = (expand_query_terms_weighted(_body_text(content))
                  if content else {})
    # 结论槽（CCG 结构字段）——「是否同一件事」的代理，见 _slot_text 说明
    n_fn, n_sb = _slot_text(content)

    conflicts, hard, divergences = [], [], []
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
        # ---- L1-c 同侧比对：第二类关系（同条件空间 · 结论槽取值分歧） ----
        # 与 L1-b 是**两类不同关系**：L1-b 判「条件互斥」（反题），L1-c 判
        # 「同条件 + 同结论槽 + 取值不同」（矛盾）。后者在词面不可判——探针实测
        # 「同属性不同值」正文覆盖率 0.612 反而低于「异属性」0.623，故改用
        # CCG 槽位字段代理「是否同一件事」。
        # 注：必须是独立 if 而非 else——同条件时 c=0，若并入 L1-b 分支会被
        #     `c < CLASH_LOW: continue` 提前跳过，L1-c 永不执行。
        c3 = _cov(tw_pos, " ".join(e_pos)) if (tw_pos and e_pos) else 0.0
        c4 = _cov(tw_neg, " ".join(e_neg)) if (tw_neg and e_neg) else 0.0
        same_cond = max(c3, c4)
        if same_cond >= SAME_COND_HIGH:
            e_fn, e_sb = _slot_text(body)
            slot = max(
                _cov(expand_query_terms_weighted(n_fn), e_fn)
                if (n_fn and e_fn) else 0.0,
                _cov(expand_query_terms_weighted(n_sb), e_sb)
                if (n_sb and e_sb) else 0.0)
            if slot >= SLOT_HIGH:
                # 同口径比对（正文↔正文）；tw_content 已去模板行，见上文
                concl = _cov(tw_content, _body_text(body)) if tw_content else 0.0
                if concl < CONCLUSION_SAME:
                    divergences.append({
                        "type": "same_condition_divergence", "with": nid,
                        "with_layer": e.get("layer"),
                        "detail": ("适用条件与结论槽均重合但取值不同："
                                   "可能是更正（应覆盖旧值）或分歧（应补区分条件）"),
                        "same_condition": round(same_cond, 4),
                        "slot_overlap": round(slot, 4),
                        "conclusion_overlap": round(concl, 4),
                        "slot": (n_fn or n_sb)[:40]})
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
    allc = hard + conflicts + divergences
    if hard:
        verdict = "REJECT"
        reason = "；".join(h["detail"] for h in hard)
    elif divergences:
        verdict = "DEFER"
        reason = "同条件空间下结论槽取值不一致：需裁决是更正还是分支"
        # 两类关系可能同时成立（同条件分歧 vs 某节点 / 条件互斥 vs 另节点）——
        # 若只报 L1-c，跨侧互斥的线索会被掩盖，飞轮收到的缺口就不完整。
        if conflicts:
            reason += f'；另有 {len(conflicts)} 处条件互斥（见 conflicts[]）'
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

    # 同条件取值分歧：L2 递归提供不了「区分条件」（条件本就相同），故缺口是
    # 「取值裁决」而非「补条件」。必须显式落 missing——否则 strength=0 →
    # 情绪 approaching → L2 被跳过 → missing 为空 → 飞轮收不到任何信号。
    if divergences and not missing:
        missing.append({
            "need": "取值裁决（同条件·同结论槽存在多条不同取值）",
            "why": "适用条件与结论槽均重合而正文取值不同："
                   "需确认是「更正」（应覆盖旧值）还是「分支」（应补区分条件）",
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
                                              reason, missing, allc)
    log(cg, rec)
    return rec


# 生效条件：missing 为假值（None/空容器/空串）返回 ""；否则逐项仅取 m.get("need") 真值者，格式化为 `need（why）`（why 缺键用 ""，值为 None 则格式化 "None"），以 "；" 连接；
def _missing_text(missing):
    """结构化缺口 → 一行文本（作为飞轮的 known_clues）。

    修断链：原先 `missing=reason` 把「人话」塞进 missing 字段，而判定器产出的
    [{need, why, conflicts}] 落在 detail 里被 flywheel_step 忽略——上游产出了
    结构，却送不到下游。
    """
    if not missing:
        return ""
    return "；".join(f'{m.get("need", "")}（{m.get("why", "")}）'
                    for m in missing if m.get("need"))


# 生效条件：cg 提供可调用 flywheel_step 时，以 query（假值按空串）前 200 字符、verdict、missing 文本（空则 reason）、conflicts 非 None 则作 detail 否则 missing 调用；结果 dict 的 unresolved_id 真值时返回它，否则回落 id；无 flywheel_step 或异常返回 None；
def _fire_flywheel(cg, query, verdict, reason, missing, conflicts=None):
    """把冲突作为「误差」投给知识飞轮，返回 unresolved 条目 id（失败不阻塞写入）。

    conflicts：冲突现场（含 type / with / same_condition 等数值），供下游生成
    `# 现场：`；missing 只描述「缺什么」，不带现场，故两者都要送。
    """
    step = getattr(cg, "flywheel_step", None)
    if step is None:
        return None
    try:
        r = step({"query": (query or "")[:200], "expected_state": "ACCEPT",
                  "actual_state": verdict,
                  "missing": _missing_text(missing) or reason,
                  "detail": conflicts if conflicts is not None else missing})
        if isinstance(r, dict):
            return r.get("unresolved_id") or r.get("id")
    except Exception:
        return None
    return None


# --------------------------------------------------------------------------
# 留痕 / 统计 / 自描述
# --------------------------------------------------------------------------

# 生效条件：cg 与 rec 给出时，将 rec 序列化为 JSON 行追加到 cg.root 下 LOG_FILE，OSError 被吞掉，返回 rec；
def log(cg, rec):
    """append-only 留痕：每条判定可审计。"""
    p = os.path.join(cg.root, LOG_FILE)
    try:
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return rec


# 生效条件：cg 给出时，若 cg.root 下 LOG_FILE 可读，则逐行解析 JSON（空行/解析失败跳过）；limit 真值时返回 out[-int(limit):][::-1]（int(limit)=0 时为全部倒序），limit 为假值（0/None/""）时返回 out[::-1]；路径不可用或 OSError 返回 []；
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


# 生效条件：逐行 json.loads 计数（不可解析行跳过、OSError 忽略、路径缺失则计数为 0），每行 total 加 1 并按 r.get("verdict")（缺键即 None 键）与 emotional.bias 为真值时的 b 累加，返回 {'records','by_verdict','by_bias','max_scan','max_depth','min_gain'}，后三者取模块常量 MAX_SCAN/MAX_DEPTH/MIN_GAIN；
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


# 生效条件：无 required 形参，调用即返回引用 EMO_AVOID/EMO_APPROACH、VERDICTS、CLASH_HIGH/CLASH_LOW、SAME_COND_HIGH/SLOT_HIGH/CONCLUSION_SAME、MAX_DEPTH/MAX_NODES/MIN_GAIN 等模块级常量的自描述字典；
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
                "checks": ["self_negation", "discipline", "condition_clash",
                           "same_condition_divergence"],
                "relations": {
                    "condition_clash": "跨侧比对（新正↔旧负 / 新负↔旧正）= 条件互斥（反题）",
                    "same_condition_divergence": "同侧比对（新正↔旧正 / 新负↔旧负）"
                                                 "＋ CCG 结论槽 = 同条件空间内的取值分歧（矛盾）",
                },
                "verdicts": list(VERDICTS),
                "thresholds": {"high": CLASH_HIGH, "low": CLASH_LOW,
                               "same_condition": SAME_COND_HIGH, "slot": SLOT_HIGH,
                               "conclusion_same": CONCLUSION_SAME},
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