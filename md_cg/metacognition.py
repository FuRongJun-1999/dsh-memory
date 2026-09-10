# -*- coding: utf-8 -*-
"""独立元认知（Metacognition）——观察自身认知过程的二阶单元。

理论出处（本仓原文，非外部知识）
------------------------------
· **情绪 = 信息差的二阶变化 d²D/dt²**（`docs/智能的公理化基石.md` §十一，:412-510）：
      「情绪不是状态本身，而是状态变化的变化」。元认知正是对认知过程做
      二阶观测的单元：一阶 = 检索结果好坏，二阶 = 认知状态在如何变化。
· **情感 = 信任的二阶变化 d²T/dt²**（同文档 :469-508）。
· **五大单元**（同文档 :540-556）：反思单元=新 / 验证单元=稳。
      元认知是这两条通道的**外部观察者**，自身不产出裁决。
· **推论三 局部不可知**（同文档 :277-288）：
      「知道什么不知道，同样属于知识」——盲区地图是法定输出，不是失败记录。
· **信任 P_trust / P_gap**（同文档 :393-408）。
· **导航税**（`docs/智能的认知过程.md`:84-86）：维持认知过程一致性需要显式
      状态记录——元认知就是付这笔税的单元。

独立性的三重含义（本模块的硬约束）
--------------------------------
1. **不参与裁决**：只读留痕与索引，**不写** confidence / 资格 / 召回打分。
   对齐 `consistency.py` L0 情绪通道纪律：「独立通道，不参与信任计算」。
2. **独立留痕**：`_metacognition.jsonl`（append-only，每条可审计）。
3. **独立入口**：`report` / `self_check` 可被 MCP / Agent 单独调用。

四个观测面
----------
    trace        信息差轨迹 D(t) → dD/dt（方向）→ d²D/dt²（情绪）
    calibration  自信校准：期望正确率 vs 实际验证通过率（过度自信/过度保守）
    blindspots   盲区地图：反复 BLINDSPOT 的查询邻域 + 未解问题
    trust        P_gap（信息差置信）+ P_trust（验证稳定置信）+ d²T/dt²（情感）

诚实边界
--------
· 所有指标都是**留痕的聚合**，不是对「智能」的断言；样本不足返回
  `insufficient_data`，不编造数值。
· 建议是**确定性模板**（非 LLM 生成），每条都带触发它的证据（可复核）。
· 元认知**不修改事实层**——它只建议，执行权归调用方 / verify / forgetting。
"""

from __future__ import annotations

import os
import time
from collections import Counter

from .fsutil import append_jsonl, read_jsonl

LOG_FILE = "_metacognition.jsonl"

# ---- 阈值（全部可审计、可调）----
GAP_OVERCONFIDENT = 0.15     # 过度自信：期望 - 实际 > 此值
GAP_UNDERCONFIDENT = -0.15   # 过度保守：期望 - 实际 < 此值
BLINDSPOT_DENSE = 0.30       # 盲区密集：BLINDSPOT 占比 >= 此值
D_LOW = 0.10                 # P_gap：D_norm < 此值视为「信息差已收敛」
MIN_SAMPLES = 5              # 样本不足 → insufficient_data
D2_EMOTION = 0.05            # 二阶变化显著阈值
BINS = ((0.0, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01))


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

def _emotion(d2: float) -> str:
    """情绪：d²D/dt² 的符号（智能论 §十一）。"""
    if d2 > D2_EMOTION:
        return "avoiding"        # 信息差加速扩大
    if d2 < -D2_EMOTION:
        return "approaching"     # 信息差加速收敛
    return "stable"


def _key(q, n: int = 16) -> str:
    """查询归一化键（用于盲区聚合 / 相似匹配）。"""
    s = "".join(ch for ch in str(q or "").lower() if ch.isalnum())
    return s[:n] or "(empty)"


def _bigrams(s) -> set:
    s = "".join(ch for ch in str(s or "") if ch.strip())
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _jaccard(a, b) -> float:
    A, B = _bigrams(a), _bigrams(b)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def _log(cg, rec: dict) -> dict:
    """独立留痕（append-only）。失败不阻塞主流程。"""
    rec = dict(rec)
    rec.setdefault("t", time.time())
    try:
        append_jsonl(os.path.join(cg.root, LOG_FILE), rec)
    except OSError:
        pass
    return rec


def _reflections(cg) -> list:
    path = getattr(cg, "reflection_log", "") or os.path.join(
        cg.root, "_reflection.jsonl")
    return list(read_jsonl(path))


def _nodes(cg) -> dict:
    return (getattr(cg, "index", None) or {}).get("nodes") or {}


def _fm(cg, nid) -> dict:
    node = cg.get(nid) or {}
    return node.get("frontmatter") or {}


# --------------------------------------------------------------------------
# 观测面 1：信息差轨迹（D / dD / d²D）
# --------------------------------------------------------------------------

def trace(cg, window: int = 50) -> dict:
    """信息差轨迹：D(t) → dD/dt（方向）→ d²D/dt²（情绪）。

    数据源：`_reflection.jsonl`（reflect() 的留痕），不新增计算负担。
    """
    recs = [r for r in _reflections(cg)
            if isinstance(r.get("d_curr"), (int, float))]
    if not recs:
        return {"ok": False, "reason": "insufficient_data", "n": 0,
                "note": "无反思留痕：先调用 reflect() 才有轨迹"}
    tail = recs[-int(window):] if window else recs
    ds = [float(r["d_curr"]) for r in tail]
    n = len(ds)
    d1 = (ds[-1] - ds[0]) / max(1, n - 1)
    d2 = float(tail[-1].get("d2") or 0.0)
    states = Counter()
    for r in tail:
        for k, v in (r.get("states") or {}).items():
            try:
                states[str(k)] += int(v or 0)
            except (TypeError, ValueError):
                continue
    total = sum(states.values()) or 1
    return {
        "ok": True, "n": n,
        "d_current": round(ds[-1], 4),
        "d_mean": round(sum(ds) / n, 4),
        "d_min": round(min(ds), 4),
        "d_max": round(max(ds), 4),
        "d1": round(d1, 4),
        "d2": round(d2, 4),
        "emotion": _emotion(d2),
        "trend": ("converging" if d1 < -0.01 else
                  "diverging" if d1 > 0.01 else "flat"),
        "states": dict(states),
        "state_rates": {k: round(v / total, 4) for k, v in states.items()},
        "d_series": [round(x, 4) for x in ds[-20:]],
    }


# --------------------------------------------------------------------------
# 观测面 2：自信校准（期望正确率 vs 实际验证通过率）
# --------------------------------------------------------------------------

def calibration(cg, max_scan: int = 2000) -> dict:
    """自信校准：我说的可信吗？

    期望正确率 = 节点 confidence 均值；
    实际正确率 = Σ正例 / Σ(正例+负例)（来自 evidence_log 的聚合计数）。
    gap > 0 → 过度自信；gap < 0 → 过度保守。
    ECE = Σ(证据占比 × |桶内实际 - 桶内自信|)（期望校准误差）。
    """
    keys = [f"{lo:g}-{hi:g}" for lo, hi in BINS]
    buckets = {k: {"n": 0, "conf_sum": 0.0, "pos": 0, "neg": 0} for k in keys}
    exp_sum = 0.0
    used = 0
    total_pos = total_neg = 0
    for nid, e in _nodes(cg).items():
        if used >= int(max_scan):
            break
        if int(e.get("evidence_count") or 0) <= 0:
            continue
        fm = _fm(cg, nid)
        pos = int(fm.get("positive_evidence") or 0)
        neg = int(fm.get("negative_evidence") or 0)
        if pos + neg <= 0:
            continue
        conf = float(fm.get("confidence", 0.6))
        used += 1
        exp_sum += conf
        total_pos += pos
        total_neg += neg
        for lo, hi in BINS:
            if lo <= conf < hi:
                b = buckets[f"{lo:g}-{hi:g}"]
                b["n"] += 1
                b["conf_sum"] += conf
                b["pos"] += pos
                b["neg"] += neg
                break
    if used == 0:
        return {"ok": False, "reason": "insufficient_data", "n_nodes": 0,
                "note": "无带证据的节点：先 verify() 积累验证记录"}
    expected = exp_sum / used
    actual = total_pos / max(1, total_pos + total_neg)
    gap = expected - actual
    bins = []
    ece = 0.0
    total_ev = total_pos + total_neg
    for k in keys:
        b = buckets[k]
        if b["n"] == 0:
            continue
        n_ev = b["pos"] + b["neg"]
        conf_b = b["conf_sum"] / b["n"]
        acc_b = (b["pos"] / n_ev) if n_ev else None
        bins.append({"bin": k, "n_nodes": b["n"], "n_evidence": n_ev,
                     "confidence": round(conf_b, 4),
                     "accuracy": None if acc_b is None else round(acc_b, 4)})
        if n_ev and total_ev:
            ece += (n_ev / total_ev) * abs(conf_b - acc_b)
    if used < MIN_SAMPLES:
        verdict = "insufficient_data"
    elif gap > GAP_OVERCONFIDENT:
        verdict = "overconfident"
    elif gap < GAP_UNDERCONFIDENT:
        verdict = "underconfident"
    else:
        verdict = "calibrated"
    return {
        "ok": True, "n_nodes": used,
        "n_evidence": total_ev,
        "expected_accuracy": round(expected, 4),
        "actual_accuracy": round(actual, 4),
        "gap": round(gap, 4),
        "ece": round(ece, 4),
        "verdict": verdict,
        "bins": bins,
    }


# --------------------------------------------------------------------------
# 观测面 3：盲区地图（我知道我不知道什么）
# --------------------------------------------------------------------------

def blindspots(cg, limit: int = 20, window: int = 200) -> dict:
    """盲区地图：反复 BLINDSPOT / DEFER 的查询邻域 + 未解问题清单。

    智能论推论三：盲区不是失败记录，是知识。因此按**邻域聚合**输出，
    可直接驱动 unresolved 层建节点（补条件）。
    """
    recs = _reflections(cg)[-int(window):]
    agg = {}
    for r in recs:
        st = r.get("states") or {}
        try:
            bad = int(st.get("BLINDSPOT") or 0)
            defer = int(st.get("DEFER") or 0)
        except (TypeError, ValueError):
            continue
        if not bad and not defer:
            continue
        q = str(r.get("query") or "").strip()
        if not q:
            continue
        k = _key(q)
        a = agg.setdefault(k, {"query": q, "blindspot": 0, "defer": 0,
                               "samples": 0, "last_t": 0.0})
        a["blindspot"] += bad
        a["defer"] += defer
        a["samples"] += 1
        a["last_t"] = max(a["last_t"], float(r.get("t") or 0.0))
    items = sorted(agg.values(),
                   key=lambda x: (-x["blindspot"], -x["defer"], -x["last_t"]))
    unresolved = []
    for nid, e in _nodes(cg).items():
        if e.get("layer") == "unresolved":
            unresolved.append({"node_id": nid,
                               "content": str((cg.get(nid) or {}).get("content") or "")[:200]})
    return {
        "ok": True,
        "n_queries": len(agg),
        "items": items[:int(limit)],
        "unresolved": unresolved[:int(limit)],
        "unresolved_count": len(unresolved),
    }


# --------------------------------------------------------------------------
# 观测面 4：信任（P_gap / P_trust / 情感）
# --------------------------------------------------------------------------

def _rate(events) -> float:
    if not events:
        return 0.0
    return sum(1 for v in events if v == "confirmed") / len(events)


def trust(cg, window: int = 100, max_scan: int = 2000) -> dict:
    """P_gap（信息差置信）+ P_trust（验证稳定置信）+ d²T/dt²（情感）。

    P_gap   = 近期反思中 D_norm < D_LOW 的比例（信息差已收敛 = 有把握）；
    P_trust = 近期验证事件中 confirmed 的占比（智能论 §十）；
    d²T/dt² = 三段验证通过率差的二阶差分（情感 = 信任的二阶变化）。
    """
    recs = _reflections(cg)
    ds = [float(r["d_curr"]) for r in recs
          if isinstance(r.get("d_curr"), (int, float))]
    recent_d = ds[-int(window):]
    p_gap = (round(sum(1 for d in recent_d if d < D_LOW) / len(recent_d), 4)
             if recent_d else None)

    events = []
    used = 0
    for nid, e in _nodes(cg).items():
        if used >= int(max_scan):
            break
        if int(e.get("evidence_count") or 0) <= 0:
            continue
        used += 1
        for ev in (_fm(cg, nid).get("evidence_log") or []):
            if isinstance(ev, dict) and ev.get("verdict"):
                events.append((float(ev.get("t") or 0.0), str(ev["verdict"])))
    events.sort()
    tail = events[-int(window):] if window else events
    n = len(tail)
    if not n:
        return {"ok": True, "p_gap": p_gap, "p_trust": None,
                "emotion": None, "n_events": 0,
                "note": "无验证留痕：先 verify() 才有信任轨迹"}
    verdicts = [v for _, v in tail]
    p_trust = round(_rate(verdicts), 4)
    seg = max(1, n // 3)
    s1 = _rate(verdicts[:seg])
    s2 = _rate(verdicts[seg:2 * seg]) if n > seg else s1
    s3 = _rate(verdicts[2 * seg:]) if n > 2 * seg else s2
    d1 = s2 - s1
    d2 = (s3 - s2) - (s2 - s1)
    return {
        "ok": True,
        "p_gap": p_gap,
        "p_trust": p_trust,
        "d1": round(d1, 4),
        "d2": round(d2, 4),
        "emotion": _emotion(d2),
        "n_events": n,
        "verdicts": dict(Counter(verdicts)),
    }


# --------------------------------------------------------------------------
# 自报告：汇总 + 确定性建议
# --------------------------------------------------------------------------

def _advise(tr, cal, bs, tt) -> list:
    """确定性建议（非 LLM）：每条都带触发它的证据，可复核。"""
    out = []
    if not tr.get("ok"):
        out.append({"code": "no_trace",
                    "why": "无反思留痕，无法评估认知轨迹",
                    "action": "先调用 reflect() 积累轨迹"})
    else:
        rates = tr.get("state_rates") or {}
        if tr["d2"] > D2_EMOTION:
            out.append({"code": "diverging",
                        "why": f"信息差加速扩大 d²D/dt²={tr['d2']}（emotion={tr['emotion']}）",
                        "action": "回到最近一次 DEFER 的缺失条件，先补条件再扩张"})
        if float(rates.get("BLINDSPOT") or 0) >= BLINDSPOT_DENSE:
            out.append({"code": "blindspot_dense",
                        "why": f"BLINDSPOT 占比 {rates.get('BLINDSPOT')} >= {BLINDSPOT_DENSE}",
                        "action": "为高频盲区邻域建 unresolved 节点，驱动补条件"})
    verdict = cal.get("verdict")
    if verdict == "overconfident":
        out.append({"code": "overconfident",
                    "why": (f"期望正确率 {cal['expected_accuracy']} > 实际 "
                            f"{cal['actual_accuracy']}（gap {cal['gap']}）"),
                    "action": "对高 confidence 节点抽查复核；verify(weakened) 会触发降级"})
    elif verdict == "underconfident":
        out.append({"code": "underconfident",
                    "why": (f"期望正确率 {cal['expected_accuracy']} < 实际 "
                            f"{cal['actual_accuracy']}（gap {cal['gap']}）"),
                    "action": "自信偏低：可适度提升已验证节点的召回权重"})
    if bs.get("unresolved_count", 0) > 0:
        out.append({"code": "open_questions",
                    "why": f"unresolved 层有 {bs['unresolved_count']} 个未解问题",
                    "action": "按 blindspots.items 的顺序优先补条件"})
    if not out:
        out.append({"code": "stable",
                    "why": "轨迹 / 校准 / 盲区 / 信任均在阈值内",
                    "action": "维持当前策略"})
    return out


def report(cg, window: int = 50) -> dict:
    """完整元认知报告（四观测面 + 确定性建议），并独立留痕。"""
    tr = trace(cg, window=window)
    cal = calibration(cg)
    bs = blindspots(cg)
    tt = trust(cg)
    advice = _advise(tr, cal, bs, tt)
    rec = {
        "ok": True,
        "trace": tr,
        "calibration": cal,
        "blindspots": bs,
        "trust": tt,
        "advice": advice,
        "independent": True,
        "note": "元认知只观察不改事实：confidence / 资格 / 召回打分均未被本模块修改",
    }
    _log(cg, {
        "op": "report",
        "n_reflections": tr.get("n"),
        "d_current": tr.get("d_current"),
        "emotion": tr.get("emotion"),
        "calibration_verdict": cal.get("verdict"),
        "gap": cal.get("gap"),
        "unresolved_count": bs.get("unresolved_count"),
        "p_trust": tt.get("p_trust"),
        "advice": [a["code"] for a in advice],
    })
    return rec


def self_check(cg, query: str, k: int = 5, min_sim: float = 0.25) -> dict:
    """元认知闸门：回答之前先自问「我对这件事的认知状态如何」。

    不是检索，而是**对检索的预期**：历史相似查询的轨迹决定了这次该
    直接答、先补条件、还是预先声明盲区。
    """
    q = str(query or "").strip()
    if not q:
        return {"ok": False, "reason": "empty_query"}
    sims = []
    for r in _reflections(cg):
        rq = str(r.get("query") or "")
        if not rq:
            continue
        s = _jaccard(q, rq)
        if s >= min_sim:
            sims.append((s, r))
    sims.sort(key=lambda x: (-x[0], -float(x[1].get("t") or 0)))
    sims = sims[:int(k)]
    hist = []
    bad = defer = acc = 0
    ds = []
    for s, r in sims:
        st = r.get("states") or {}
        b = int(st.get("BLINDSPOT") or 0)
        d = int(st.get("DEFER") or 0)
        a = int(st.get("ACCEPT") or 0)
        bad += b
        defer += d
        acc += a
        if isinstance(r.get("d_curr"), (int, float)):
            ds.append(float(r["d_curr"]))
        hist.append({"query": r.get("query"), "similarity": round(s, 4),
                     "d_curr": r.get("d_curr"), "states": st,
                     "t": r.get("t")})
    n = len(hist)
    if n == 0:
        rec = {"ok": True, "query": q, "prior_attempts": 0,
               "similar_history": [],
               "expected_confidence": None,
               "warning": "no_prior",
               "recommendation": "search_then_decide",
               "note": "无相似历史：按四态判定正常检索"}
        _log(cg, {"op": "self_check", "query": q, "prior_attempts": 0,
                  "recommendation": rec["recommendation"]})
        return rec
    prior_d = sum(ds) / len(ds) if ds else None
    exp_conf = None if prior_d is None else round(max(0.0, 1.0 - prior_d), 4)
    warning = None
    if bad >= max(1, n // 2):
        warning = "blindspot_likely"
        rec_code = "declare_blindspot"
    elif defer >= max(1, n // 2):
        warning = "conditions_missing"
        rec_code = "defer_and_supply_conditions"
    elif acc >= max(1, n // 2) and (prior_d is None or prior_d < 0.5):
        rec_code = "answer"
    else:
        rec_code = "search_then_decide"
    out = {
        "ok": True, "query": q,
        "prior_attempts": n,
        "similar_history": hist,
        "prior_d": None if prior_d is None else round(prior_d, 4),
        "expected_confidence": exp_conf,
        "prior_blindspot": bad,
        "prior_defer": defer,
        "prior_accept": acc,
        "warning": warning,
        "recommendation": rec_code,
    }
    _log(cg, {"op": "self_check", "query": q, "prior_attempts": n,
              "prior_d": out["prior_d"], "warning": warning,
              "recommendation": rec_code})
    return out


# --------------------------------------------------------------------------
# 留痕查询 / 自描述
# --------------------------------------------------------------------------

def history(cg, limit: int = 100) -> dict:
    """元认知留痕（倒序，最新在前）。"""
    recs = list(read_jsonl(os.path.join(cg.root, LOG_FILE)))
    if limit:
        recs = recs[-int(limit):]
    return {"ok": True, "n": len(recs), "records": recs[::-1]}


def summary(cg) -> dict:
    """一句话元认知状态（供 health / OS 面板使用）。"""
    tr = trace(cg, window=20)
    cal = calibration(cg)
    tt = trust(cg, window=50)
    return {
        "n_reflections": tr.get("n", 0),
        "d_current": tr.get("d_current"),
        "emotion": tr.get("emotion"),
        "calibration": cal.get("verdict"),
        "p_trust": tt.get("p_trust"),
        "p_gap": tt.get("p_gap"),
    }


def catalog() -> dict:
    """自描述：元认知的观测面与独立性约束。"""
    return {
        "module": "metacognition",
        "role": "观察自身认知过程的二阶单元（不参与裁决）",
        "theory": {
            "emotion": "d²D/dt²（智能论 §十一）",
            "feeling": "d²T/dt²（同）",
            "units": "五大单元中的反思/验证之外部观察者（§十三）",
            "blindspot": "推论三：局部不可知，盲区即知识",
            "trust": "P_trust / P_gap（§十）",
        },
        "faces": ["trace", "calibration", "blindspots", "trust", "report",
                  "self_check"],
        "constraints": [
            "只读留痕与索引，不写 confidence / 资格 / 召回打分",
            "独立留痕 _metacognition.jsonl（append-only）",
            "建议为确定性模板，非 LLM 生成，每条带证据",
        ],
        "thresholds": {
            "gap_overconfident": GAP_OVERCONFIDENT,
            "gap_underconfident": GAP_UNDERCONFIDENT,
            "blindspot_dense": BLINDSPOT_DENSE,
            "d_low": D_LOW,
            "min_samples": MIN_SAMPLES,
        },
    }
