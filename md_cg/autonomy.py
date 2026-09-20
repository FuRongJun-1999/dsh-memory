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

from . import d_meta, metacognition, predict
from .fsutil import append_jsonl

#: 信息差评分权重：不确定度二阶差分 |d2|（加速度）×1，
#: BLINDSPOT ×2（资格失败最重）、DEFER ×1（降级但可确认）。
W_D2, W_BLINDSPOT, W_DEFER = 1.0, 2.0, 1.0

#: D_meta 排序加分（方案 §2.4，**默认生效**）：D_meta 只进**排序键**，
#: 不改 `score`（ΔD 定价器口径不变）、不改资格判据（score>0 才是资格）、
#: 也不改 σ(Gain) 筛选（#37 价值链）。加分取**单一指定代理**（DMETA_PROXY），
#: 禁三代理加权合成（智能论3.4 DEV-002a）。`MDCG_D_META=0` → compute()
#: 返回 enabled=False → 加分退化 0（回到旧排序）。
#: 口径诚实标注：本轮取库侧 query 无关代理 → 同轮全部提案加分同值 → **当前
#: 口径下排序不变**；区分性待 query-relative 口径（`_neg_coverage`）在
#: reflect 侧落盘后自然生效（不提前编造区分性）。
W_DMETA = 0.1
DMETA_PROXY = "unmodeled_growth"

EXPLORE_LOG = "_explore.jsonl"

# P-T-40 信息增益门槛（#6/#37 投影）：Value = ΔD·σ(Gain)——
#   score（ΔD 代理）是**定价器**（排序），σ(Gain) 是**筛选器**（资格）。
#   期望/实现分离（智能论 2.9.3）：proposals 端的 σ 由**上一轮 explore 的
#   实现值**（outcomes 留痕）推导——期望值用于决策，实现值用于确认。
GAIN_WINDOW = 2        # 连续 GAIN_WINDOW 次终态无变化 → 视为无增益
GAIN_COOLDOWN = 3600.0 # 冷却秒数：过期后 σ 回 1.0（给探索机会，不永久冻结）
_GAIN_STUCK = ("carried", "unresolved", "unknowable", "no_anchor")


# 生效条件：cg 无 root 属性时以 '.' 作为 os.path.join 的第一参数，有 root 属性时始终使用 cg.root 的值（即使为 None，也会传入 os.path.join 导致报错），再与模块常量 EXPLORE_LOG 拼接。
def _explore_log_path(cg):
    return os.path.join(getattr(cg, "root", "."), EXPLORE_LOG)


# 生效条件：给定 cg 与 bid 读取探索留痕，无该 bid 的 outcomes 时返回 gain=None、sigma=1.0，最近 window（默认 GAIN_WINDOW）次终态全属 _GAIN_STUCK 且 now-last_t 小于 cooldown（默认 GAIN_COOLDOWN）时返回 sigma=0.0、gain=0，终态全属 _GAIN_STUCK 但冷却已过、且与该 bid 相关轮次的 meta_outcomes.delta[DMETA_PROXY] 均值大于 0 时同样返回 sigma=0.0、gain=0（压力仍在扩大则不放行），其余返回 sigma=1.0、gain=1；meta_outcomes 键缺失、delta 非字典或其值为非数值的轮次不计入压力均值（缺键即不触发新分支，既有 ①-④ 行为逐字不变）。
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
    terminals, last_t, meta_deltas = [], 0.0, []
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
                    # D_meta 跨轮压力增量（缺键/关闭 → 不计入 → 不触发新分支）
                    mo = r.get("meta_outcomes")
                    dlt = mo.get("delta") if isinstance(mo, dict) else None
                    v = dlt.get(DMETA_PROXY) if isinstance(dlt, dict) else None
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        meta_deltas.append(float(v))
    except OSError:
        pass
    if not terminals:
        return {"sigma": 1.0, "gain": None, "last_t": 0.0,
                "reason": "无探索历史（首探放行：无证据不否决）"}
    recent = terminals[-int(window):]
    stuck = (len(recent) >= int(window)
             and all(t in _GAIN_STUCK for t in recent))
    rising = bool(meta_deltas) and (sum(meta_deltas) / len(meta_deltas)) > 0
    meta_txt = ""
    if rising:
        meta_txt = ("；D_meta 压力均值 %+.4f（%s，近 %d 轮留痕）"
                    % (sum(meta_deltas) / len(meta_deltas), DMETA_PROXY,
                       len(meta_deltas)))
    if stuck and (now - last_t) < float(cooldown):
        return {"sigma": 0.0, "gain": 0, "last_t": round(last_t, 3),
                "reason": ("增益门槛（P-T-40）：连续 %d 次终态无变化 %s → "
                           "DEFER_EXHAUSTED（冷却 %ds 内不再重复探索）%s"
                           % (len(recent), list(recent), int(cooldown),
                              meta_txt))}
    if stuck and rising:
        return {"sigma": 0.0, "gain": 0, "last_t": round(last_t, 3),
                "meta_rising": True,
                "reason": ("增益门槛（P-T-40）：连续 %d 次终态无变化 %s 且 "
                           "D_meta 压力仍在扩大%s → "
                           "DEFER_EXHAUSTED_UNDER_PRESSURE（冷却已过但不放行："
                           "压力扩大而终态停滞 = 重复探索不再产生增益）"
                           % (len(recent), list(recent), meta_txt))}
    return {"sigma": 1.0, "gain": 1, "last_t": round(last_t, 3),
            "reason": "有增益证据或冷却已过"}


# 生效条件：cg 的反思记录经 metacognition._reflections 取末 int(window) 条切片（window=0 时切片即全量），按非空 query 聚合后仅 score=W_D2*d2_abs+W_BLINDSPOT*blindspot+W_DEFER*defer>0 的项进入 out（**资格判据先于加分**：score<=0 即 continue，D_meta 不构成资格），其中 enforce_gain 为真值时还须 gain_gate(cg, …, now)["sigma"]>0 否则该项标 deferred_exhausted 转入 deferred，enforce_gain 为假值时不做增益筛选全数进入 out；D_meta 加分 W_DMETA*d_meta.pressure(d_meta.compute(cg, window), DMETA_PROXY) 每轮只算一次并在循环内复用，只写入 sort_score 与 reason 证据（不改 score、不改资格、不改 σ），MDCG_D_META 关闭或未启用时该加分为 0.0；最终 out 按 (-sort_score, -last_t) 排序后截取 max(1, int(limit)) 条（limit=0 或负数也返回 1 条）并随 n_signals=len(agg) 返回；
def proposals(cg, window: int = 200, limit: int = 3,
              enforce_gain: bool = True) -> dict:
    """从反思日志聚合信息差信号，产出排序后的探索提案。

    每条提案携带证据明细（d2 之和/绝对值和、BLINDSPOT/DEFER 计数、样本数），
    `score` = W_D2*Σ|d2| + W_BLINDSPOT*BLINDSPOT + W_DEFER*DEFER（**ΔD 定价器，
    口径不变**）；`sort_score` = score + W_DMETA×D_meta 边界压力（排序键）。
    无信号的查询不产生提案（不编造探索价值）——**D_meta 加分不构成资格**：
    `score<=0` 的项在加分之前就被 continue 掉。

    D_meta 只影响**排序**、不改 σ(Gain) 筛选；本轮取库侧 query 无关的单一
    代理（DMETA_PROXY），同轮各提案加分同值，故当前口径下排序不变——
    区分性待 query-relative 口径落盘后自然生效（不提前编造）。

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
    mv = d_meta.compute(cg, window=window)   # 每轮一次、循环内复用（禁 N× 扫描）
    bonus = (round(W_DMETA * d_meta.pressure(mv, DMETA_PROXY), 4)
             if mv.get("enabled") else 0.0)
    for a in agg.values():
        score = (W_D2 * a["d2_abs"] + W_BLINDSPOT * a["blindspot"]
                 + W_DEFER * a["defer"])
        if score <= 0:
            continue                       # 无信息差信号 → 不提案（不编造）
        a = dict(a)
        a["score"] = round(score, 4)       # ΔD 定价器：口径不变
        a["d_meta_bonus"] = bonus          # D_meta 排序加分（只影响排序）
        a["sort_score"] = round(score + bonus, 4)
        a["reason"] = ("信息差信号：Σ|d2|=%s（Σd2=%s）+ BLINDSPOT×%d + DEFER×%d"
                       "（近 %d 次反思）；D_meta 排序加分 +%s（%s=%s，三代理"
                       "不合成；不改资格/σ(Gain)）"
                       % (a["d2_abs"], a["d2_sum"], a["blindspot"],
                          a["defer"], a["samples"], bonus, DMETA_PROXY,
                          d_meta.pressure(mv, DMETA_PROXY)))
        if enforce_gain:                   # P-T-40 增益门槛：资格由实现值裁决
            gate = gain_gate(cg, metacognition._key(a["query"]), now=now)
            a["gain_gate"] = gate
            if gate["sigma"] <= 0:
                a["status"] = "deferred_exhausted"
                deferred.append(a)
                continue
        out.append(a)
    out.sort(key=lambda x: (-x["sort_score"], -x["last_t"]))
    return {"ok": True, "proposals": out[:max(1, int(limit))],
            "n_signals": len(agg), "deferred": deferred,
            "d_meta": {"enabled": bool(mv.get("enabled")), "bonus": bonus,
                       "proxy": DMETA_PROXY},
            "value_chain": ("Value=ΔD·σ(Gain)：score 定价排序（ΔD 代理），"
                            "σ(Gain) 资格筛选（实现值=outcomes 留痕）；"
                            "D_meta 只加排序分、不改资格（DEV-002a）")}


# 生效条件：cg 必需，该符号始终返回 ok=True、action="explore"；其中 bypass_gain 为真值时以 enforce_gain=False 调 proposals、为假值时以 True 调（window/limit 原样透传），逐条提案用 apply/actor 调 predict.learn_blindspots 并把其首个 step 的 terminal 记入 outcomes[bid]，同一 blindspot_id 本轮已见则记为 skipped，调用抛异常则记为 error（"%s: %s" % (type(exc).__name__, exc)），并额外取本轮 d_meta.compute（append 前状态）与上一条 explore 留痕的 meta_outcomes.before，并列写入 meta_outcomes={before, prev_before, delta, proxy, enabled}（**outcomes 值类型不变**），最后 append_jsonl 写 _explore_log_path(cg) 时仅 OSError 被忽略；
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
    mv = d_meta.compute(cg, window=window)      # 本轮 D_meta（append 前状态）
    prev = None
    for r in d_meta.tail_jsonl(_explore_log_path(cg), 1):
        mo = r.get("meta_outcomes") if isinstance(r, dict) else None
        prev = mo.get("before") if isinstance(mo, dict) else None
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
           # D_meta 并列留痕（**outcomes 值类型不变**：终态字符串契约是
           # gain_gate 停滞集比对的前提，改成 dict 会让 σ 静默恒为 1.0）：
           #   before      = 本轮开始时的三代理（含上轮 apply 的效果）
           #   prev_before = 上一条 explore 留痕的 before（无则 None）
           #   delta       = before − prev_before（跨轮压力增量 → gain_gate 输入）
           "meta_outcomes": {
               "before": {k: float(mv.get(k) or 0.0)
                          for k in d_meta.PROXY_KEYS},
               "prev_before": ({k: float(prev.get(k) or 0.0)
                                for k in d_meta.PROXY_KEYS}
                               if isinstance(prev, dict) else None),
               "delta": d_meta.diff(prev, mv),
               "proxy": DMETA_PROXY,
               "enabled": bool(mv.get("enabled"))},
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