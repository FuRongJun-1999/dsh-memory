# -*- coding: utf-8 -*-
"""信息差驱动的自主探索闭环（提案 → 验证 → 回写）。

定位（待办 2「信息差驱动的自动化/自主化」的最小实现）：
  灵枢已有全部零件——d2 信号在反思日志持续产生（mdcg.reflect L1097），
  盲区聚类按 states 聚合（metacognition.blindspots），盲区→路线假设→五态
  终判→gap_hint 回写齐备（predict.learn_blindspots）——**缺口只在触发器**：
  信号在记录，无人在听。本模块把四段焊成一条自动链：

      信号（reflection: d2 加速度 + BLINDSPOT/DEFER 计数）
        → 提案（proposals：信息差评分排序，证据随提案留痕）
        → 验证（predict.learn_blindspots 五态终判：unknowable / no_anchor /
                unresolved / carried / resolved——诚实优先，绝不编造）
        → 回写（apply=True 时 carried/unresolved 落 contextual 的 gap_hint，
                节点 id 由盲区键派生 ⇒ 幂等）

  资格纪律：提案由**条件证据**（信息差信号）授予，不由相似度授予；
  score 只做排序不做资格——score<=0（无任何信号）即不提案。
  回写边界：gap_hint 是「待补线索」非事实断言（predict._write_gap 同源）。
  opt-in：explore 只被显式调用（或 mdcos insight act="explore"）触发，
  默认链路零行为变更。
"""
from __future__ import annotations

import os
import time

from . import metacognition, predict
from .fsutil import append_jsonl

#: 信息差评分权重：不确定度二阶差分 |d2|（加速度）×1，
#: BLINDSPOT ×2（资格失败最重）、DEFER ×1（降级但可确认）。
W_D2, W_BLINDSPOT, W_DEFER = 1.0, 2.0, 1.0

EXPLORE_LOG = "_explore.jsonl"


def _explore_log_path(cg):
    return os.path.join(getattr(cg, "root", "."), EXPLORE_LOG)


def proposals(cg, window: int = 200, limit: int = 3) -> dict:
    """从反思日志聚合信息差信号，产出排序后的探索提案。

    每条提案携带证据明细（d2 之和/绝对值和、BLINDSPOT/DEFER 计数、样本数），
    排序键 = W_D2*Σ|d2| + W_BLINDSPOT*BLINDSPOT + W_DEFER*DEFER。
    无信号的查询不产生提案（不编造探索价值）。
    """
    recs = metacognition._reflections(cg)[-int(window):]
    agg = {}
    for r in recs:
        q = str(r.get("query") or "").strip()
        if not q:
            continue
        k = metacognition._key(q)
        a = agg.setdefault(k, {"query": q, "d2_sum": 0.0, "d2_abs": 0.0,
                               "blindspot": 0, "defer": 0, "samples": 0,
                               "last_t": 0.0})
        d2 = r.get("d2")
        if isinstance(d2, (int, float)):
            a["d2_sum"] = round(a["d2_sum"] + float(d2), 6)
            a["d2_abs"] = round(a["d2_abs"] + abs(float(d2)), 6)
        st = r.get("states") or {}
        try:
            a["blindspot"] += int(st.get("BLINDSPOT") or 0)
            a["defer"] += int(st.get("DEFER") or 0)
        except (TypeError, ValueError):
            pass
        a["samples"] += 1
        a["last_t"] = max(a["last_t"], float(r.get("t") or 0.0))

    out = []
    for a in agg.values():
        score = (W_D2 * a["d2_abs"] + W_BLINDSPOT * a["blindspot"]
                 + W_DEFER * a["defer"])
        if score <= 0:
            continue                       # 无信息差信号 → 不提案（不编造）
        a = dict(a)
        a["score"] = round(score, 4)
        a["reason"] = ("信息差信号：Σ|d2|=%s（Σd2=%s）+ BLINDSPOT×%d + DEFER×%d"
                       "（近 %d 次反思）"
                       % (a["d2_abs"], a["d2_sum"], a["blindspot"],
                          a["defer"], a["samples"]))
        out.append(a)
    out.sort(key=lambda x: (-x["score"], -x["last_t"]))
    return {"ok": True, "proposals": out[:max(1, int(limit))],
            "n_signals": len(agg)}


def explore(cg, apply: bool = False, limit: int = 3, window: int = 200,
            actor: str = "autonomy") -> dict:
    """最小探索闭环：提案 → 逐盲区五态验证 →（apply）回写待补线索。

    每个提案交给 predict.learn_blindspots（blindspot_id 用盲区键口径，
    与 find_blindspot 的 cluster 匹配同构）；终态与回写结果原样汇总，
    并在 _explore.jsonl 留痕（提案级证据 + 触发者，可审计可复放）。
    """
    pr = proposals(cg, window=window, limit=limit)
    steps = []
    for p in pr["proposals"]:
        bid = metacognition._key(p["query"])
        try:
            res = predict.learn_blindspots(cg, blindspot_id=bid, apply=apply,
                                           actor=actor)
            one = (res.get("steps") or [{}])[0]
            step = {"blindspot_id": bid,
                    "terminal": one.get("terminal"),
                    "routes": one.get("routes"),
                    "written": one.get("written"),
                    "hint": one.get("hint", "")}
        except Exception as exc:               # noqa: BLE001
            step = {"blindspot_id": bid, "terminal": "error",
                    "error": "%s: %s" % (type(exc).__name__, exc)}
        steps.append({"proposal": p, **step})
    rec = {"type": "explore", "t": time.time(), "actor": actor,
           "apply": bool(apply), "n_proposals": len(steps),
           "bids": [s["blindspot_id"] for s in steps]}
    try:
        append_jsonl(_explore_log_path(cg), rec)
    except OSError:
        pass
    return {"ok": True, "action": "explore", "apply": bool(apply),
            "proposals": pr["proposals"], "steps": steps,
            "n_signals": pr["n_signals"],
            "note": ("提案=信息差信号排序（证据随附）；终态五态由 "
                     "learn_blindspots 诚实判定；apply=True 仅落地 "
                     "carried/unresolved 的 gap_hint 待补线索（幂等）")}
