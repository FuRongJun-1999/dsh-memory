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

# Beta-Bernoulli 先验强度（等效先验样本数 κ，P-T-73/74 通道贝叶斯）：
# α0 = BASE_HIT_RATE·κ，β0 = (1−BASE_HIT_RATE)·κ。κ 越大小样本越向基线收缩。
# 性质：先验均值 = BASE_HIT_RATE（与 hit_rate() 空历史兜底同值，口径无缝）。
PRIOR_STRENGTH = 20

CAUSAL_BRANCH_TYPES = ("causal", "sequential")
SEMANTIC_TOP_K = 5
SEMANTIC_MIN_SIM = 0.05
SEMANTIC_CONF = 0.4         # 语义诱导候选固定置信度（AEIS 同值）
PREFERENCE_THRESHOLD = 0.5  # D-005 偏好权重准入线

W_TREND = 0.40              # D-004 四维权重（AEIS 2.10 节）
W_BOUNDARY = 0.20
W_VERIFICATION = 0.25
W_BALANCE = 0.15

# D_meta 第五维（opt-in，方案 §2.3）：默认 0 = 不参与 composite、不落键、
# SORT_KEYS 不扩张（默认返回与四维时代逐字节一致，默认零变更纪律）。
# 显式启用：PREDICTION_META_DIM=<权重>（>0 才生效）
#           PREDICTION_META_PROXY=<代理名>（缺省 unmodeled_growth；**只取单一
#           代理**——三代理加权合成违反智能论3.4 DEV-002a）
# 纪律：导入期读一次环境变量，改值须重载模块；catalog().weights 同步扩张。
try:
    W_META = float(os.environ.get("PREDICTION_META_DIM", "0") or 0.0)
except ValueError:          # 非法值按关闭处理：默认零变更优先，不炸导入
    W_META = 0.0
W_META = W_META if W_META > 0 else 0.0
META_PROXY = os.environ.get("PREDICTION_META_PROXY", "unmodeled_growth")

SORT_KEYS = ("composite", "trend", "verification", "boundary", "balance")
if W_META > 0:              # 第五维开启时才扩张排序键（默认零变更）
    SORT_KEYS = SORT_KEYS + ("meta_pressure",)
LOG_FILE = "_prediction.jsonl"


# 生效条件：不适用（无必需形参与分支），恒返回四维权重的自描述 dict；仅当 W_META>0（PREDICTION_META_DIM 显式启用第五维）时追加 meta_pressure 键；
def _weights():
    """自描述权重：默认四维逐字节不变，第五维 opt-in 时同步扩张。"""
    w = {"trend": W_TREND, "boundary": W_BOUNDARY,
         "verification": W_VERIFICATION, "balance": W_BALANCE}
    if W_META > 0:
        w["meta_pressure"] = W_META
    return w

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

# 生效条件：传入 cg 具 index 键且其 'nodes' 为非空映射时返回该映射，否则返回空字典 {}；
def _nodes(cg):
    return ((getattr(cg, "index", None) or {}).get("nodes") or {})


# 生效条件：传入 cg 具 root 属性时返回 root 与模块级常量 LOG_FILE 的路径拼接，缺 root 则以 '.' 拼接；
def log_path(cg):
    return os.path.join(getattr(cg, "root", "."), LOG_FILE)


# 生效条件：传入 cg 与 rec 时向 log_path(cg) 追加一条 JSONL 记录，OSError 被吞掉且无返回值；
def _append(cg, rec):
    try:
        append_jsonl(log_path(cg), rec)
    except OSError:
        pass


# 生效条件：传入 cg 可读出 JSONL 记录时返回记录列表，读取抛 OSError 或 ValueError 时返回 []，limit 为正时仅返回末尾 limit 条；
def _read_log(cg, limit=0):
    try:
        recs = list(read_jsonl(log_path(cg)))
    except (OSError, ValueError):
        recs = []
    if limit and int(limit) > 0:
        recs = recs[-int(limit):]
    return recs


# 生效条件：传入 cg 的留痕中存在 type=='feedback' 的记录时返回其 hit 布尔序列末尾 limit 条（limit 默认常量 HIT_HISTORY_MAX），无此类记录则返回空列表；
def _hit_history(cg, limit=HIT_HISTORY_MAX):
    """D-006 命中历史（持久化 · 差异 2）：只取 feedback 记录。"""
    return [bool(r.get("hit")) for r in _read_log(cg)
            if r.get("type") == "feedback"][-int(limit):]


# 生效条件：传入 cg 与 nid 时返回邻接表中 nid 的出边列表 [(目标 id, 边字典)]，该键无出边则为 []；
def _out_edges(cg, nid):
    """出边（含层级边）：[(target_id, edge_dict)]，复用 chain 邻接缓存。"""
    from . import chain
    return list((chain.adjacency(cg).get(nid) or []))


# 生效条件：传入 cg 与 nid 时返回邻接表中所有以 nid 为目标的源节点集合，无入边则为空集；
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


# 生效条件：传入 edge 的 'confidence' 可转 float 时返回裁剪到 [0.0,1.0] 的值，取键失败或转换抛 AttributeError/TypeError/ValueError 时返回 1.0；
def _edge_conf(edge):
    try:
        return max(0.0, min(1.0, float(edge.get("confidence", 1.0))))
    except (AttributeError, TypeError, ValueError):
        return 1.0


# ---------------------------------------------------------------- D-002 过滤门

# 生效条件：causal_link 成立条件为 a_id 的出边中存在目标 b_id 且其关系类型属于模块级常量 CAUSAL_BRANCH_TYPES，成立返回 True，否则返回 False；
def has_causal_link(cg, a_id, b_id):
    """直接因果/时序边：A → B 已声明（直通，无需过滤）。"""
    from . import chain
    for tgt, e in _out_edges(cg, a_id):
        if tgt == b_id and chain.edge_rel(e) in CAUSAL_BRANCH_TYPES:
            return True
    return False


# 生效条件：传入 cg、a_id、b_id 时，a_id 与 b_id 的入边来源集合交集非空返回 True，交集为空返回 False；
def has_structural_pattern(cg, a_id, b_id):
    """结构模式：A、B 共享父节点（可解释的间接关联 → 伪因果豁免）。"""
    return bool(_in_sources(cg, a_id) & _in_sources(cg, b_id))


# 生效条件：cg 具 attention_policy 且非 None、且 get_weights() 返回可取值的映射时返回 float(weights.get(node_id, 0.0))，策略缺失、取权重抛异常或转换失败时返回 0.0；
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


# 生效条件：cg/a_id/b_id 下 has_causal_link 成立返回 (True,'causal_link')，否则 has_structural_pattern 成立返回 (True,'structural_pattern')，否则 preference_weight(cg,b_id) 大于常量 PREFERENCE_THRESHOLD 返回 (True,'preference_weight')，三者皆不成立返回 (False,'rejected_semantic_only')；
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

# 生效条件：cg.get(node_id) 的 content 去空后非空时以前 200 字符检索，返回相似度不低于常量 SEMANTIC_MIN_SIM 且非自身的至多 k 个 (nid, similarity)；content 为空或检索抛异常时返回 []；
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

# 生效条件：传入 cg 与 node_id 时，其出边中关系类型属于常量 CAUSAL_BRANCH_TYPES 者直通为 causal 候选，semantic 为真时再并入经 causal_gate 放行的语义邻近候选，按 confidence 降序、node_id 升序返回；
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

# 生效条件：conf 可转 float 时裁剪到 [0,1] 得 c，按 base=1-c 返回 confidence=c 与裁剪到 [0,1] 的 [c-base*0.5, c+base*0.5] 区间，转换失败则按 c=0.0 计算；
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


# 生效条件：传入 cg 与 path 且 path 非空时，返回其中 tags 含 'boundary' 或 has_neg_conditions，或 content 匹配「不适用|不确定|边界|盲区」的节点占比；path 为空返回 0.0；
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


# 生效条件：传入 route 时返回其 sources 与 relations 去重并集大小除以 4.0 且上限 1.0 的值，两键皆缺时返回 0.0；
def _branch_diversity(route):
    """balance 维：路径覆盖的推理通道维度数 / 4。

    AEIS 用语义坐标的维度数；md_cg 无语义坐标 → 用「来源通道
    （causal / semantic_induced）+ 边关系类型」作维度，保持 /4.0 归一化，
    语义仍是「防单一偏好主导」。
    """
    dims = set(route.get("sources") or []) | set(route.get("relations") or [])
    return round(min(1.0, len(dims) / 4.0), 4)


# 生效条件：route 的 'confs' 长度不少于 2 时，相邻差绝对值最大值不超过 0.35 返回 'smooth' 否则 'jump'；长度不足 2 或无可算步长返回 'unknown'；
def extrapolation_validity(route):
    """D-003：局部线性外推有效性（smooth / jump / unknown）。"""
    confs = route.get("confs") or []
    if len(confs) < 2:
        return "unknown"
    steps = [confs[i] - confs[i + 1] for i in range(len(confs) - 1)]
    if not steps:
        return "unknown"
    return "smooth" if max(abs(s) for s in steps) <= 0.35 else "jump"


# 生效条件：传入 cg 且 _hit_history(cg) 非空时返回其命中占比，序列为空时返回模块级常量 BASE_HIT_RATE；
def hit_rate(cg):
    """历史命中率（无样本 → 基线 0.40，对齐 D-006）。"""
    h = _hit_history(cg)
    if not h:
        return BASE_HIT_RATE
    return round(sum(1 for x in h if x) / len(h), 4)


# ---------------------------------------------------------------- P-T-73/74 通道贝叶斯

# 生效条件：传入 hits 序列时以 base*prior_k 与 (1-base)*prior_k 为先验（prior_k 默认常量 PRIOR_STRENGTH、base 默认常量 BASE_HIT_RATE），按命中数 k 与总数 n 返回 alpha/beta/mean/std/ci95/samples/hits；hits 为空即为纯先验，mean 等于 base；
def beta_posterior(hits, prior_k=PRIOR_STRENGTH, base=BASE_HIT_RATE):
    """Beta-Bernoulli 后验（纯函数）：命中序列 → 后验参数与区间。

    置信度≠可信度（P-T-73/74）：`hit_rate` 是滑动计数（小样本过度自信：
    n=5 全命中 → 1.0）；后验均值 = (α0+k)/(α0+β0+n) 随样本量向基线收缩
    （n=5 全命中 → 0.52），诚实反映「证据还很少」。置信度的动态死区
    （dynamic_hit_threshold）不动——本函数只提供**更诚实的可信度估计面**，
    默认链路零行为变更。

    返回：{alpha, beta, mean, std, ci95, samples, hits}；
    空序列 → 先验（mean=base，与 hit_rate 空历史兜底同值）。
    ci95 用正态近似 mean±1.96σ（零依赖；样本大时近似良好，小样本区间
    偏窄，故另带 samples 供阅读方自判权重）。
    """
    a0 = float(base) * float(prior_k)
    b0 = (1.0 - float(base)) * float(prior_k)
    xs = [bool(x) for x in (hits or [])]
    k = sum(1 for x in xs if x)
    n = len(xs)
    a, b = a0 + k, b0 + (n - k)
    mean = a / (a + b)
    var = (a * b) / ((a + b) ** 2 * (a + b + 1.0))
    std = var ** 0.5
    return {"alpha": round(a, 4), "beta": round(b, 4),
            "mean": round(mean, 4), "std": round(std, 4),
            "ci95": [round(max(0.0, mean - 1.96 * std), 4),
                     round(min(1.0, mean + 1.96 * std), 4)],
            "samples": n, "hits": k}


# 生效条件：传入 cg 时把 type=='feedback' 的记录按 channel 字段（缺失归 'unlabeled'）分组为 {channel: [hit...]}，仅取末尾 limit 条（limit 默认常量 HIT_HISTORY_MAX）；
def channel_history(cg, limit=HIT_HISTORY_MAX):
    """feedback 留痕按通道分组（P-T-74 通道级可信度）→ {channel: [hit...]}。

    通道 = 预测发出的面（feedback 的 `channel` 参数，如 "causal"/"semantic"）。
    早期留痕无 channel 字段 → 归 "unlabeled"（诚实标注，不冒充分通道）。
    """
    out = {}
    for r in _read_log(cg, limit=limit):
        if r.get("type") != "feedback":
            continue
        ch = str(r.get("channel") or "unlabeled")
        out.setdefault(ch, []).append(bool(r.get("hit")))
    return out


# 生效条件：channel 非 None 时返回该通道（无记录即先验）的 beta_posterior 并附 channel 键，channel 为 None 时返回 {'all': 全量后验, 'channels': 各通道后验}；
def channel_posterior(cg, channel=None, limit=HIT_HISTORY_MAX):
    """通道级后验查询：channel=None → 全量+分通道；channel=str → 单通道。"""
    hist = channel_history(cg, limit=limit)
    if channel is not None:
        ch = str(channel)
        post = beta_posterior(hist.get(ch) or [])
        post["channel"] = ch
        return post
    all_hits = [x for hits in hist.values() for x in hits]
    return {"all": beta_posterior(all_hits),
            "channels": {ch: beta_posterior(hits)
                         for ch, hits in sorted(hist.items())}}


# 生效条件：传入 cg 与 route 时，trend 取 route 的 confidence、boundary 取 _boundary_consistency(cg, route['path'])、verification 缺省时取 hit_rate(cg)、balance 取 _branch_diversity(route)，并按 W_TREND/W_BOUNDARY/W_VERIFICATION/W_BALANCE 加权返回 composite；仅当 W_META>0（PREDICTION_META_DIM 显式启用第五维）时才额外取 d_meta.pressure(d_meta.compute(cg), META_PROXY) 作第五维、落 meta_pressure 键、把 W_META*meta_pressure 计入 composite，关闭时返回键集合与 composite 逐字节不变；
def score_route(cg, route, verification=None):
    """D-004 T_pred 四维评分 + **D_meta 第五维（opt-in）**。

    `verification` 跨路线共享（来自命中率）。第五维 `meta_pressure` 取
    **单一指定代理**（`PREDICTION_META_PROXY`，缺省 `unmodeled_growth`）——
    **不做三代理加权合成**（智能论3.4 §2.7.0 DEV-002a）。默认权重 0：
    不落键、不改 composite、SORT_KEYS 不扩张（默认零变更纪律）。
    """
    trend = float(route.get("confidence") or 0.0)
    boundary = _boundary_consistency(cg, route.get("path") or [])
    ver = float(verification if verification is not None else hit_rate(cg))
    balance = _branch_diversity(route)
    composite = (W_TREND * trend + W_BOUNDARY * boundary
                 + W_VERIFICATION * ver + W_BALANCE * balance)
    out = {"trend": round(trend, 4), "boundary": boundary,
           "verification": round(ver, 4), "balance": balance,
           "composite": round(composite, 4), "weights": _weights()}
    if W_META > 0:                     # 第五维 opt-in：默认不落键
        from . import d_meta          # 惰性导入：叶子只读模块，防循环
        mp = d_meta.pressure(d_meta.compute(cg), META_PROXY)
        out["meta_pressure"] = mp
        out["composite"] = round(composite + W_META * mp, 4)
    return out


# ---------------------------------------------------------------- 盲区驱动

# 生效条件：blindspot_id 去空后非空且能取到盲区报表时，匹配 unresolved 的 node_id 返回 kind='unresolved'，否则匹配 items 的 query 或其 _key 相等返回 kind='blindspot_cluster'，均未命中或取报表抛异常返回 None；
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


# 生效条件：blindspot 的 description 中匹配到「可预测性：X」时返回 X 去除空白并小写，未匹配则返回 'predictable'；
def predictability(blindspot):
    """可预测性：盲区可显式声明 `# 可预测性：unknowable`。

    未声明 → predictable（默认按局部不可知原理生成候选，不宣称必然）。
    """
    txt = str((blindspot or {}).get("description") or "")
    m = re.search(r"可预测性[：:]\s*(\S+)", txt)
    return m.group(1).strip().lower() if m else "predictable"


# 生效条件：description 去空后非空时以 cg.search 取常量 ANCHOR_FETCH_K 个候选，跳过 layer 属常量 ANCHOR_SKIP_LAYERS 或 tags 命中常量 ANCHOR_SKIP_TAGS 者，返回首个出边非空的合格节点 id，否则降级返回首个合格候选 id；description 为空、检索抛异常或候选全被过滤返回 None；
def anchor_from_description(cg, description):
    """盲区描述 → 锚点节点（检索器打分，与 AEIS 的 LIKE→坐标回退同构）。

    择锚规则：候选池内**可起推者优先**——出边非空是路线生成的必要条件，无出边的
    节点只能靠语义回退硬凑路线，起点语义即失真。**全部不可起推时才降级**为首个合格
    候选（诚实降级：宁可标注锚点弱，不假装有锚）。
    动机（实测）：同分并列时检索序不可依赖——「正题节点」与其「同名+近义描述」变体
    词法分可完全相同（各自都为 1.0），纯按检索名次取首位会漂到无出边的近义变体上。

    过滤与择锚分两关：先按标签/层过滤掉推断脚手架（`gap_hint`/`scene`）与负记忆
    （`unresolved`/`rejected`），再在剩余候选里按**可起推资格**择优——出边非空者
    立即采纳，无出边者记为降级候选继续后看，全池无可起推者才降级取首个合格候选。
    候选全被过滤时返回 None（等价「无锚点」），由调用方按 no_anchor 处理。
    邻接表不可用（chain 取表异常）时退回「取首个合格候选」——辅助判据故障不应
    让整条预测链失效（兜底优先于择优）。
    """
    q = str(description or "").strip()
    if not q:
        return None
    try:
        results, _meta = cg.search(q, k=ANCHOR_FETCH_K, record=False, judge=False)
    except Exception:
        return None
    try:
        from . import chain
        out_edges = chain.adjacency(cg)
    except Exception:
        out_edges = None
    fallback = None
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
        # 可起推资格：出边非空是路线生成的必要条件；不可起推者只作降级候选。
        if out_edges is None or out_edges.get(nid):
            return nid
        if fallback is None:
            fallback = nid
    return fallback


# ---------------------------------------------------------------- 路线生成

# 生效条件：cg.get(nid) 的 content 含非空行时返回首行去掉开头 '#' 后的前 60 字符，否则返回 nid；
def _label(cg, nid):
    node = cg.get(nid) or {}
    for line in (node.get("content") or "").splitlines():
        s = line.strip()
        if s:
            return re.sub(r"^#\s*", "", s)[:60]
    return nid


# 生效条件：start_id 去空后非空且存在于 _nodes(cg) 时，horizon 裁剪到 [1, HORIZON_HARD]、max_branches 裁剪到 [1, MAX_BRANCHES_HARD] 后 DFS，返回 status='ok' 及带 uncertainty_bound/extrapolation_validity/score/path_labels 的 routes；start_id 为空或不在节点集中返回 status='start_not_found'；
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

# 生效条件：当 depth < horizon（enclosing 上界）时，对 branch_candidates(cg, cur, semantic=semantic) 取前 max_branches 个候选展开——候选 node_id 已在 path 中则 continue 跳过，否则把 cand["confidence"] 连乘（初始 1.0，结果 round 4）连同 conds/sources/relations 各自追加 cand 对应字段后作为一条路径写入外层 out，并以该 node_id、depth+1 递归；depth >= horizon 时直接返回且不产生任何路径。
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


# 生效条件：传入 cg、res、sort、limit 时，sort 不属于常量 SORT_KEYS 则退回 'composite'，按该键排序并在 limit 为正时截断，追加一条 type 为 log_type（默认 'predict_routes'）的留痕后返回 res；
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


# 生效条件：blindspot_id 非空时转交 routes_from_blindspot；否则 start_id 为空返回 status='no_start'，_generate 返回非 ok 则原样返回，ok 则经 _finalize(cg, res, sort, limit) 返回；
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


# 生效条件：find_blindspot 得 None 时返回 status='blindspot_not_found'，其 predictability 为 'unknowable' 时返回 status='unpredictable'，anchor_from_description 无锚点时返回 status='no_anchor'，有锚点则以其 _generate 并在 ok 时经 _finalize（log_type='predict_routes_blindspot'）返回；
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


# 生效条件：传入 edge 时返回其 'target'、'to'、'dst' 中首个非空值，三者皆空则返回 None；
def _edge_target(edge):
    return edge.get("target") or edge.get("to") or edge.get("dst")


# 生效条件：传入 cg 与 node_id 时，仅当存在指向 node_id 的因果/时序边且其源节点 frontmatter 的 layer 属于常量 _SAFE_LAYERS，才把该边 confidence 提升 min(1.0, 原值+delta)（delta 默认常量 EDGE_BOOST）并回写，返回被改源节点列表，无满足者返回空列表；
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


# 生效条件：传入 cg 时若 _hit_history(cg, limit) 样本数少于常量 MIN_SAMPLES，返回 threshold 为常量 BASE_HIT_RATE 且 reflect=False；样本足够则以 max(BASE_HIT_RATE, mean-2σ) 为 threshold，命中均值低于该值时 reflect=True；
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


# 生效条件：cg 与 predicted_node_id 给出即执行——predicted_node_id 为假值（None/0/""）时 pred 取空串，actual_node_id 为假值时 act 回落为 pred，hit 为 None 时按 pred==act 判定；hit 为真时 out["boosted"] 取 _boost_incoming(cg, act, EDGE_BOOST, actor=actor)，hit 为假时 out["rejected_id"] 取 cg.add_rejected(...)（该调用抛异常时改记 out["rejected_error"]），随后 out 合并 dynamic_hit_threshold(cg)，sync_self 为真时导入 self_state.refresh(cg, actor=actor) 写 out["self_state"]（抛异常时写 out["self_state_error"]），返回 out。
def feedback(cg, predicted_node_id, actual_node_id=None, hit=None, note="",
             actor="predict", sync_self=True, channel=None):
    """预测反馈（D-006）：hit → 边置信度 +0.05；miss → 登记 rejected。

    `hit` 未显式给出时按 `predicted == actual` 判定。
    `channel`（可选，P-T-74）：预测发出的面（如 "causal"/"semantic"），
    供通道级 Beta-Bernoulli 后验（channel_posterior）按面分层估计可信度；
    不传 → 留痕归 "unlabeled"，不改变任何既有行为。

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
                 "actual": act, "hit": hit, "note": str(note or "")[:200],
                 "channel": (str(channel) if channel else None)})
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


# 生效条件：传入 cg 具 root 属性时返回 root 与模块级常量 LEARN_LOG 的路径拼接，缺 root 则以 '.' 拼接；
def learn_log_path(cg):
    return os.path.join(getattr(cg, "root", "."), LEARN_LOG)


# 生效条件：传入 cg 与 rec 时向 learn_log_path(cg) 追加一条 JSONL 记录，任何异常被吞掉且无返回值；
def _learn_append(cg, rec):
    try:
        append_jsonl(learn_log_path(cg), rec)
    except Exception:                              # noqa: BLE001
        pass


# 生效条件：nid 去空后非空、cg.get(nid) 的 frontmatter layer 等于 'knowledge' 且其 content 含常量 consolidate.CCG_REQUIRED 全部要素行时返回 True，否则返回 False；
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


# 生效条件：传入 route 且其 'path' 非空时返回路径最后一个节点 id，路径为空或 route 为 None 时返回 None；
def _terminal_node(route):
    path = list((route or {}).get("path") or [])
    return path[-1] if path else None


# 生效条件：传入 cg、bid、step、actor 时，cg 中不存在由 bid 的 sha1 派生的 gap 节点 id 则写入 contextual 的 gap_hint 节点并返回该 id；该 id 已存在或 cg.add 抛异常时返回 None；
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


# 生效条件：blindspot_id 给出但 find_blindspot 找不到时返回 ok=False 与 status='not_found'；否则逐条按 unknowable/no_anchor/unresolved/carried/resolved 判定，apply 为真且 cg 可写时才把 carried/unresolved 落成幂等 gap_hint 节点；
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


# 生效条件：传入 cg 时基于 _read_log(cg) 统计 type 以 'predict_routes' 开头的调用数与 n_routes 合计、feedback 样本与命中率（无样本取常量 BASE_HIT_RATE），并附 channel_posterior 与 dynamic_hit_threshold，recent 取末尾 limit 条（limit 默认 20，为 0 时为空）；
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
            "beta": channel_posterior(cg),
            "dynamic": dynamic_hit_threshold(cg),
            "recent": recs[-int(limit):] if limit else []}


# ---------------------------------------------------------------- 因果推理

# 生效条件：传入 cg 与 path 且 path 长度不少于 2 时，对每对相邻节点返回其在邻接表中且关系类型属于常量 CAUSAL_BRANCH_TYPES 的边条件（无匹配则为空串）逐跳列表，path 更短则返回空列表；
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


# 生效条件：a_id 或 b_id 去空后为空时返回 ok=False 与 error='missing_node'；a_id 等于 b_id 返回可达且长度 0；否则仅在常量 CAUSAL_BRANCH_TYPES 边上于 max_depth（下限 1）内 BFS，可达返回路径与逐跳 conditions，不可达返回 reachable=False；
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

# 生效条件：不适用（无必需形参与模块级常量）
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
            "P-T-73/74": "通道贝叶斯后验（Beta-Bernoulli，置信度≠可信度；"
                         "feedback channel 参数 + channel_posterior 查询）",
        },
        "weights": _weights(),            # 第五维 opt-in 时同步扩张（防文档漂移）
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