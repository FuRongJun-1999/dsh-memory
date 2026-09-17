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

import json
import os
import time

from . import metacognition, predict
from .fsutil import append_jsonl

#: 信息差评分权重：不确定度二阶差分 |d2|（加速度）×1，
#: BLINDSPOT ×2（资格失败最重）、DEFER ×1（降级但可确认）。
W_D2, W_BLINDSPOT, W_DEFER = 1.0, 2.0, 1.0

EXPLORE_LOG = "_explore.jsonl"

# P-T-40 信息增益门槛（#6/#37 投影）：Value = ΔD·σ(Gain)——
#   score（ΔD 代理）是**定价器**（排序），σ(Gain) 是**筛选器**（资格）。
#   期望/实现分离（智能论 2.9.3）：proposals 端的 σ 由**上一轮 explore 的
#   实现值**（outcomes 留痕）推导——期望值用于决策，实现值用于确认。
GAIN_WINDOW = 2        # 连续 GAIN_WINDOW 次终态无变化 → 视为无增益
GAIN_COOLDOWN = 3600.0 # 冷却秒数：过期后 σ 回 1.0（给探索机会，不永久冻结）
_GAIN_STUCK = ("carried", "unresolved", "unknowable", "no_anchor")


# 生效条件：当 cg 带 root 属性时返回 os.path.join(cg.root, EXPLORE_LOG)，cg 无 root 时回退 '.' 后与模块常量 EXPLORE_LOG 拼接。
def _explore_log_path(cg):
    return os.path.join(getattr(cg, "root", "."), EXPLORE_LOG)


def gain_gate(cg, bid: str, now: float | None = None,
              window: int = GAIN_WINDOW, cooldown: float = GAIN_COOLDOWN) -> dict:
    """信息增益门槛（P-T-40 第四保护投影，纯读无副作用）。

    读上一轮 explore 的**实现值**（_explore.jsonl 的 outcomes 留痕）裁决
    该盲区是否值得再探：
      无历史 → σ=1.0, gain=None（首探放行：Gain 是筛选器，无证据不否决）
      连续 `window` 次终态 ∈ 停滞集且仍在 `cooldown` 内 → σ=0, gain=0
        （**DEFER_EXHAUSTED**：探索无增益，冷却——不编造重复探索的价值）
      其余（有 resolved 变化 / 证据不足 / 冷却已过）→ σ=1.0, gain=1
    `now` 可注入以便测试冷却过期。
    """
    now = time.time() if now is None else float(now)
    terminals, last_t = [], 0.0
    try:
        with open(_explore_log_path(cg), encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                oc = r.get("outcomes") or {}
                if bid in oc:
                    terminals.append(str(oc[bid]))
                    last_t = max(last_t, float(r.get("t") or 0.0))
    except OSError:
        pass
    if not terminals:
        return {"sigma": 1.0, "gain": None, "last_t": 0.0,
                "reason": "无探索历史（首探放行：无证据不否决）"}
    recent = terminals[-int(window):]
    if (len(recent) >= int(window)
            and all(t in _GAIN_STUCK for t in recent)
            and (now - last_t) < float(cooldown)):
        return {"sigma": 0.0, "gain": 0, "last_t": round(last_t, 3),
                "reason": ("增益门槛（P-T-40）：连续 %d 次终态无变化 %s → "
                           "DEFER_EXHAUSTED（冷却 %ds 内不再重复探索）"
                           % (len(recent), list(recent), int(cooldown)))}
    return {"sigma": 1.0, "gain": 1, "last_t": round(last_t, 3),
            "reason": "有增益证据或冷却已过"}


def proposals(cg, window: int = 200, limit: int = 3,
              enforce_gain: bool = True) -> dict:
    """从反思日志聚合信息差信号，产出排序后的探索提案。

    每条提案携带证据明细（d2 之和/绝对值和、BLINDSPOT/DEFER 计数、样本数），
    排序键 = W_D2*Σ|d2| + W_BLINDSPOT*BLINDSPOT + W_DEFER*DEFER。
    无信号的查询不产生提案（不编造探索价值）。

    `enforce_gain`（默认 True）：σ(Gain) 资格筛选（#37 价值链——score 是
    定价器，Gain 是筛选器）。被门槛拦下的提案不静默丢弃，落入 `deferred`
    （reason 留痕可审计）。bypass 场景走 explore(bypass_gain=True)。
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

    out, deferred = [], []
    now = time.time()
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
        if enforce_gain:                   # P-T-40 增益门槛：资格由实现值裁决
            gate = gain_gate(cg, metacognition._key(a["query"]), now=now)
            a["gain_gate"] = gate
            if gate["sigma"] <= 0:
                a["status"] = "deferred_exhausted"
                deferred.append(a)
                continue
        out.append(a)
    out.sort(key=lambda x: (-x["score"], -x["last_t"]))
    return {"ok": True, "proposals": out[:max(1, int(limit))],
            "n_signals": len(agg), "deferred": deferred,
            "value_chain": ("Value=ΔD·σ(Gain)：score 定价排序（ΔD 代理），"
                            "σ(Gain) 资格筛选（实现值=outcomes 留痕）")}


def explore(cg, apply: bool = False, limit: int = 3, window: int = 200,
            actor: str = "autonomy", bypass_gain: bool = False) -> dict:
    """最小探索闭环：提案 → 逐盲区五态验证 →（apply）回写待补线索。

    每个提案交给 predict.learn_blindspots（blindspot_id 用盲区键口径，
    与 find_blindspot 的 cluster 匹配同构）；终态与回写结果原样汇总，
    并在 _explore.jsonl 留痕（提案级证据 + 触发者 + outcomes 实现值，
    可审计可复放——outcomes 是下轮 gain_gate 的裁决输入）。

    P-T-40 递归四保护投影（#6）：
      ①深度：单轮验证，不递归展开（explore 不嵌套调用 explore）；
      ②循环：本轮内同一 blindspot_id 只验证一次（seen 去重）；
      ③增益：proposals 端 σ(Gain) 门槛（DEFER_EXHAUSTED 冷却）；
      ④预算：`limit` 即本轮探索预算；
        `bypass_gain=True` = 2.9.3.1 非任务探索的**显式预算豁免**
        （绕过增益筛选照常探索，留痕 bypass_gain 字段可审计）。
    """
    pr = proposals(cg, window=window, limit=limit, enforce_gain=not bypass_gain)
    steps, outcomes, seen = [], {}, set()
    for p in pr["proposals"]:
        bid = metacognition._key(p["query"])
        if bid in seen:                    # ②循环保护：本轮防重复
            steps.append({"proposal": p, "blindspot_id": bid,
                          "terminal": "skipped",
                          "hint": "循环保护：本轮已验证（P-T-40②）"})
            continue
        seen.add(bid)
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
        outcomes[bid] = step["terminal"]       # ③实现值落痕 → 下轮裁决输入
        steps.append({"proposal": p, **step})
    rec = {"type": "explore", "t": time.time(), "actor": actor,
           "apply": bool(apply), "n_proposals": len(steps),
           "bids": [s["blindspot_id"] for s in steps],
           "outcomes": outcomes,
           "bypass_gain": bool(bypass_gain),
           "gain_deferred": [(d.get("query"), d.get("gain_gate", {}).get("reason"))
                             for d in (pr.get("deferred") or [])]}
    try:
        append_jsonl(_explore_log_path(cg), rec)
    except OSError:
        pass
    return {"ok": True, "action": "explore", "apply": bool(apply),
            "proposals": pr["proposals"], "steps": steps,
            "n_signals": pr["n_signals"], "deferred": pr.get("deferred") or [],
            "note": ("提案=信息差信号排序（score 定价）+ σ(Gain) 门槛（实现值"
                     "裁决资格）；终态五态由 learn_blindspots 诚实判定；"
                     "apply=True 仅落地 carried/unresolved 的 gap_hint 待补"
                     "线索（幂等）；P-T-40 四保护=单轮深度/本轮循环去重/"
                     "增益冷却/预算 limit（bypass_gain 显式豁免可审计）")}