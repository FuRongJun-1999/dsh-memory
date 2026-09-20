# -*- coding: utf-8 -*-
"""D_meta 结构性投影（边界压力向量）验证。

断言面：
  A 三代理口径：空库下界 / 逐代理公式复算 / 归一化上界 / **不合成单值**
  B 开关回退臂：MDCG_D_META=0 → 三值 0.0 + enabled=False + 加分退化 0
  C 双 D 落盘：reflect 落 d_meta / d_meta_delta（首条 None）；_compute_d 零变更
  D 第五维 opt-in：默认不落键/不改 composite；显式启用才落键并同步 SORT_KEYS
  E 提案加分：只改 sort_score 与证据，不改 score、不改资格（无信号仍不提案）
  F explore 留痕 meta_outcomes（outcomes 契约不变）+ gain_gate 压力冷却分支
  G self_state：d_meta_trend 幂等 + 状态卡边界压力行
  H MCP 观测面：cg op=metacognition action=d_meta
  I tail_jsonl 原语边界（缺文件 / 窗口 ≤0 / 截断末行 / 尾部窗口等价）

理论：智能论3.4 §2.7.0 DEV-002/002a（D_task ≠ D_meta；不得加权合成单值）。
运行：python -m md_cg.test_d_meta
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import tempfile

from . import autonomy, d_meta, mcp_server, metacognition, predict, self_state
from .fsutil import append_jsonl
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


def _sig(cg, t, query, d2, states):
    append_jsonl(cg.reflection_log,
                 {"t": t, "query": query, "d_prev": 1.0, "d_curr": 1.0,
                  "d_delta": 0.0, "d2": d2, "states": states,
                  "n_results": 3, "feedback": None})


def _root(tmp, name):
    r = os.path.join(tmp, name)
    os.makedirs(r, exist_ok=True)
    return r


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_dmeta_")
    try:
        # ---------- A 三代理口径 ----------
        cg = MdCGOS(_root(tmp, "a"))
        v0 = d_meta.compute(cg)
        ok(v0["enabled"] is True and v0["window"] == d_meta.DEFAULT_WINDOW,
           "A1空库：enabled=True、window=200（总闸默认开启）")
        ok(all(v0[k] == 0.0 for k in d_meta.PROXY_KEYS),
           "A1b空库三代理取下界 0.0（无留痕即无压力，不编造）")
        ok(not any(k in v0 for k in ("d_meta", "composite", "value")),
           "A1c返回结构无单一 D_meta 数值键（DEV-002a 不合成单值）")

        for i in range(20):
            append_jsonl(cg.recent_log, {"i": i})
        for i in range(10):
            append_jsonl(autonomy._explore_log_path(cg), {"i": i, "bids": []})
        p_ev = d_meta.compute(cg)["events_pressure"]
        ok(abs(p_ev - round((20 + 10) / (2 * 200), 4)) < 1e-9,
           f"A2events_pressure 公式复算（(20+10)/(2×200)={p_ev}）")

        cg_full = MdCGOS(_root(tmp, "a_full"))
        for i in range(300):
            append_jsonl(cg_full.recent_log, {"i": i})
            append_jsonl(autonomy._explore_log_path(cg_full), {"i": i})
        ok(d_meta.compute(cg_full)["events_pressure"] == 1.0,
           "A2b两日志各满窗 → 上界 1.0（尾窗只取 window 条、不漏出 [0,1]）")

        stock = d_meta._layer_stock(type("C", (), {"index": {"nodes": {
            "n1": {"layer": "rejected"}, "n2": {"layer": "unresolved"},
            "n3": {"layer": "knowledge"}}}})())
        ok(stock == 2, "A3_layer_stock 只计 rejected/unresolved 层（零正文 IO）")
        ug = d_meta.unmodeled_growth(2, {"total": 2,
                                         "states": {"BLINDSPOT": 1,
                                                    "DEFER": 1}})
        ok(abs(ug - round(0.5 * (2 / d_meta.STOCK_FULL) + 0.5 * 1.0, 4))
           < 1e-9, f"A3bunmodeled_growth 公式复算（{ug}）")
        bv = d_meta.boundary_violation_rate({"total": 4, "states": {
            "REJECT": 1, "BLINDSPOT": 1, "ACCEPT": 2}})
        ok(bv == 0.5, "A3cboundary_violation_rate=(REJECT+BLINDSPOT)/全部")
        ok(d_meta.boundary_violation_rate({"total": 0, "states": {}}) == 0.0,
           "A3d空分布 → 0.0（不除零、不编造）")

        cat = d_meta.catalog()
        ok(len(d_meta.PROXY_KEYS) == 3
           and cat["default_proxy_for_single_value"] == "unmodeled_growth",
           "A4catalog 声明三代理 + 单值只允许指定单一代理")
        ok(any("不合成" in c for c in cat["constraints"]),
           "A4bcatalog 约束含「不合成单一 D_meta 数值」")

        ok(d_meta.pressure({}) == 0.0
           and d_meta.pressure({"unmodeled_growth": 1.7}) == 1.0
           and d_meta.pressure(v0) == 0.0,
           "A5pressure() 只取单一代理且裁剪到 [0,1]（缺键/越界不炸）")
        ok(d_meta.pressure({"events_pressure": 0.3}) == 0.0,
           "A5bpressure() 默认代理为 unmodeled_growth（不跨代理兜底）")
        ok(d_meta.diff(None, v0) is None,
           "A6diff(无前值) → None（首条反思 delta 为 None）")
        dd = d_meta.diff({"unmodeled_growth": 0.1, "events_pressure": 0.4},
                         {"unmodeled_growth": 0.35, "events_pressure": 0.4})
        ok(dd["unmodeled_growth"] == 0.25 and dd["events_pressure"] == 0.0,
           "A6bdiff 逐字段差（缺键按 0.0 处理）")

        # ---------- B 开关回退臂 ----------
        cg_b = MdCGOS(_root(tmp, "b"))
        for i in range(40):
            append_jsonl(cg_b.recent_log, {"i": i})
        _sig(cg_b, 1.0, "反应堆冷却方案", 0.9, {"BLINDSPOT": 2})
        on_v = d_meta.compute(cg_b)
        pr_on = autonomy.proposals(cg_b)
        os.environ["MDCG_D_META"] = "0"
        try:
            off_v = d_meta.compute(cg_b)
            pr_off = autonomy.proposals(cg_b)
            ok(off_v["enabled"] is False
               and all(off_v[k] == 0.0 for k in d_meta.PROXY_KEYS),
               "B1MDCG_D_META=0 → enabled=False、三代理恒 0.0（显式回退）")
            ok("已显式关闭" in off_v["note"],
               "B1b回退臂 note 声明关闭（回退留痕，不是缺键）")
            ok(on_v["enabled"] and on_v["events_pressure"] > 0.0,
               "B1c开启臂同库同数据压力 > 0（对照非空）")
            ok(pr_on["d_meta"]["bonus"] == round(
                autonomy.W_DMETA * d_meta.pressure(on_v), 4),
               "B2开启臂提案加分 = W_DMETA×单代理压力")
            ok(pr_off["d_meta"]["bonus"] == 0.0
               and pr_off["proposals"][0]["d_meta_bonus"] == 0.0,
               "B2b回退臂加分退化 0（回到旧排序）")
            ok(pr_off["proposals"][0]["sort_score"]
               == pr_off["proposals"][0]["score"],
               "B2c回退臂 sort_score == score（逐位回到 ΔD 定价）")
        finally:
            os.environ.pop("MDCG_D_META", None)
        ok(d_meta.compute(cg_b)["enabled"] is True,
           "B3删除环境变量后总闸自动回到开启（默认开启）")

        # ---------- C 双 D 落盘 ----------
        cg_c = MdCGOS(_root(tmp, "c"))
        r1 = cg_c.reflect("反应堆冷却方案", [])
        ok(set(r1.get("d_meta") or {}) == set(d_meta.PROXY_KEYS),
           "C1reflect 落 d_meta 三代理键")
        ok(r1.get("d_meta_delta") is None,
           "C1b首条反思 d_meta_delta=None（无前值不编造差）")
        ok(r1["d_curr"] == 1.0, "C1cresults 为空 → D_task 仍取 1.0（口径零变更）")
        append_jsonl(cg_c.recent_log, {"i": 1})
        r2 = cg_c.reflect("反应堆冷却方案",
                          [("d1", 1, {"state": "ACCEPT"}),
                           ("d2", 0, {"state": "ACCEPT"})])
        ok(r2["d_curr"] == 0.5,
           "C2_compute_d 既有口径不变（1 − 1/2 = 0.5）")
        ok(r2["d_meta_delta"] is not None
           and r2["d_meta_delta"]["events_pressure"]
           == round(r2["d_meta"]["events_pressure"]
                    - r1["d_meta"]["events_pressure"], 4),
           "C2bd_meta_delta = 与上一条反思的逐字段差")
        recs = cg_c.last_d_records()
        ok(len(recs) == 2 and all(0.0 <= recs[-1]["d_meta"][k] <= 1.0
                                  for k in d_meta.PROXY_KEYS),
           "C2c落盘 d_meta 三代理均在 [0,1]")
        os.environ["MDCG_D_META"] = "0"
        try:
            r3 = cg_c.reflect("反应堆冷却方案", [])
            ok(all(r3["d_meta"][k] == 0.0 for k in d_meta.PROXY_KEYS)
               and r3["d_meta_delta"] is None,
               "C3关闭臂 reflect：d_meta 恒 0.0 且 delta=None（回退可审计）")
        finally:
            os.environ.pop("MDCG_D_META", None)

        # ---------- D 第五维 opt-in ----------
        cg_d = MdCGOS(_root(tmp, "d"))
        route = {"confidence": 0.5, "path": []}
        sc_off = predict.score_route(cg_d, route, verification=0.5)
        ok("meta_pressure" not in sc_off
           and len(predict.SORT_KEYS) == 5,
           "D1默认（W_META=0）不落 meta_pressure 键、SORT_KEYS 不扩张")
        ok(set(sc_off) == {"trend", "boundary", "verification", "balance",
                           "composite", "weights"},
           "D1b默认返回键集合与四维时代逐字节一致")
        ok("meta_pressure" not in predict.catalog()["weights"],
           "D1ccatalog().weights 默认仍为四维（防文档漂移）")
        os.environ["PREDICTION_META_DIM"] = "0.2"
        os.environ["PREDICTION_META_PROXY"] = "unmodeled_growth"
        try:
            pred_on = importlib.reload(predict)
            sc_on = pred_on.score_route(cg_d, route, verification=0.5)
            mp = sc_on["meta_pressure"]
            ok("meta_pressure" in sc_on
               and "meta_pressure" in pred_on.SORT_KEYS,
               "D2启用（PREDICTION_META_DIM=0.2）落键并同步 SORT_KEYS")
            ok("meta_pressure" in pred_on.catalog()["weights"],
               "D2bcatalog().weights 同步扩张（自描述不漂移）")
            ok(abs(sc_on["composite"]
                   - round(sc_off["composite"] + 0.2 * mp, 4)) < 1e-9,
               "D2ccomposite = 四维 + W_META×单代理（仍不做三代理加权）")
        finally:
            os.environ.pop("PREDICTION_META_DIM", None)
            os.environ.pop("PREDICTION_META_PROXY", None)
        pred_back = importlib.reload(predict)
        sc_back = pred_back.score_route(cg_d, route, verification=0.5)
        ok("meta_pressure" not in sc_back and len(pred_back.SORT_KEYS) == 5,
           "D3移除环境变量并重载 → 回到四维、键不落（可回退）")

        # ---------- E 提案加分只影响排序 ----------
        cg_e = MdCGOS(_root(tmp, "e"))
        for i in range(30):
            append_jsonl(cg_e.recent_log, {"i": i})
        _sig(cg_e, 1.0, "反应堆冷却方案", 0.9, {"BLINDSPOT": 2})
        _sig(cg_e, 2.0, "周末菜单", 0.05, {})
        _sig(cg_e, 3.0, "零信号查询", 0.0, {})
        pr_e = autonomy.proposals(cg_e, limit=5)
        ps = pr_e["proposals"]
        p0 = ps[0]
        ok(pr_e["n_signals"] == 3 and len(ps) == 2,
           "E1零信号查询不进提案（资格判据先于加分，不编造）")
        raw = (autonomy.W_D2 * p0["d2_abs"]
               + autonomy.W_BLINDSPOT * p0["blindspot"]
               + autonomy.W_DEFER * p0["defer"])
        ok(p0["score"] == round(raw, 4),
           "E1bscore 仍是纯 ΔD 定价（口径零变更）")
        ok(p0["sort_score"] == round(p0["score"] + p0["d_meta_bonus"], 4),
           "E1csort_score = score + D_meta 加分（加分只进排序键）")
        ok("D_meta" in p0["reason"] and "不合成" in p0["reason"],
           "E1dreason 追加 D_meta 证据且声明不合成（可审计）")
        ok("d2" in p0["reason"] and "BLINDSPOT" in p0["reason"],
           "E1ereason 保留 d2/BLINDSPOT 既有子串（契约不破）")
        ok(pr_e["d_meta"]["proxy"] == autonomy.DMETA_PROXY
           and pr_e["d_meta"]["bonus"] == p0["d_meta_bonus"],
           "E2每轮一次计算、循环内复用（各提案加分同值）")
        os.environ["MDCG_D_META"] = "0"
        try:
            pr_e_off = autonomy.proposals(cg_e, limit=5)
            ok([x["sort_score"] for x in pr_e_off["proposals"]]
               == [x["score"] for x in pr_e_off["proposals"]],
               "E3关闭臂：sort_score 退化回 score（旧排序逐位一致）")
        finally:
            os.environ.pop("MDCG_D_META", None)

        # ---------- F explore 留痕 + gain_gate 压力冷却 ----------
        cg_f = MdCGOS(_root(tmp, "f"))
        cg_f.add("k1", "# 功能名：反应堆冷却知识\n"
                       "# 生效条件：问反应堆冷却方案\n"
                       "# 子功能：知识片段\n"
                       "# 执行：陈述知识\n"
                       "# 验证方式：test\n"
                       "# 不适用条件：无\n"
                       "反应堆冷却方案概述。\n",
                 layer="knowledge", verification_basis="test")
        _sig(cg_f, 1.0, "反应堆冷却方案", 0.9, {"BLINDSPOT": 2})
        autonomy.explore(cg_f, actor="test")
        autonomy.explore(cg_f, actor="test")
        with open(autonomy._explore_log_path(cg_f), encoding="utf-8") as fh:
            recs_f = [json.loads(x) for x in fh if x.strip()]
        mo = recs_f[-1].get("meta_outcomes") or {}
        ok(set(mo.get("before") or {}) == set(d_meta.PROXY_KEYS)
           and mo.get("proxy") == autonomy.DMETA_PROXY,
           "F1explore 留痕 meta_outcomes.before 三代理齐备")
        ok(mo.get("delta") is not None,
           "F1b第二轮 delta 非 None（跨轮压力增量 → gain_gate 输入）")
        ok(all(isinstance(v, str)
               for v in (recs_f[-1].get("outcomes") or {}).values()),
           "F2outcomes 值仍为终态字符串（契约不变，停滞集比对不失效）")
        ok(JSON_KEYS_UNCHANGED(recs_f[-1]),
           "F2bmata_outcomes 与 outcomes 并列，未覆盖既有键")

        bid = metacognition._key("反应堆冷却方案")
        cg_g = MdCGOS(_root(tmp, "g"))
        for i, tml in enumerate(["carried", "carried"]):
            append_jsonl(autonomy._explore_log_path(cg_g),
                         {"type": "explore", "t": 1000.0 + i,
                          "actor": "test", "outcomes": {bid: tml},
                          "bids": [bid],
                          "meta_outcomes": {"delta": {"unmodeled_growth": 0.2},
                                            "proxy": autonomy.DMETA_PROXY}})
        g_pressure = autonomy.gain_gate(cg_g, bid, now=1000.0 + 3600.0 + 10.0)
        ok(g_pressure["sigma"] == 0.0 and g_pressure["gain"] == 0
           and "UNDER_PRESSURE" in g_pressure["reason"],
           "F3终态停滞 + 压力仍扩大 → 冷却过期也不放行（新分支）")
        ok(g_pressure.get("meta_rising") is True,
           "F3b新分支留痕 meta_rising=True（可审计）")

        cg_h = MdCGOS(_root(tmp, "h"))
        for i, tml in enumerate(["carried", "carried"]):
            append_jsonl(autonomy._explore_log_path(cg_h),
                         {"type": "explore", "t": 1000.0 + i,
                          "actor": "test", "outcomes": {bid: tml},
                          "bids": [bid]})
        g_plain = autonomy.gain_gate(cg_h, bid, now=1000.0 + 3600.0 + 10.0)
        ok(g_plain["sigma"] == 1.0,
           "F4缺 meta_outcomes 键 → 新分支不触发（冷却过期照旧放行）")
        g_cool = autonomy.gain_gate(cg_h, bid, now=1000.5)
        ok(g_cool["sigma"] == 0.0 and "DEFER_EXHAUSTED" in g_cool["reason"],
           "F4b既有 ② 冷却内口径逐字保持（DEFER_EXHAUSTED）")
        cg_i = MdCGOS(_root(tmp, "i"))
        for i, tml in enumerate(["carried", "carried"]):
            append_jsonl(autonomy._explore_log_path(cg_i),
                         {"type": "explore", "t": 1000.0 + i,
                          "actor": "test", "outcomes": {bid: tml}, "bids": [bid],
                          "meta_outcomes": {"delta": {"unmodeled_growth": 0.0}}})
        ok(autonomy.gain_gate(cg_i, bid,
                              now=1000.0 + 3600.0 + 10.0)["sigma"] == 1.0,
           "F4c压力未扩大（delta=0）→ 不放行条件不成立（只在上升时冷却）")

        # ---------- G self_state 边界压力趋势 ----------
        cg_j = MdCGOS(_root(tmp, "j"))
        pf_empty = self_state._prediction_face(cg_j)
        ok("d_meta_trend" in pf_empty
           and isinstance(pf_empty["d_meta_trend"], float),
           "G1空留痕：d_meta_trend 回落当前单代理值（float，不编造）")
        append_jsonl(cg_j.reflection_log,
                     {"t": 1.0, "query": "q1", "d_curr": 1.0, "d2": 0.1,
                      "states": {}, "n_results": 1,
                      "d_meta": {"events_pressure": 0.0,
                                 "unmodeled_growth": 0.20,
                                 "boundary_violation_rate": 0.0}})
        append_jsonl(cg_j.reflection_log,
                     {"t": 2.0, "query": "q2", "d_curr": 1.0, "d2": 0.1,
                      "states": {}, "n_results": 1,
                      "d_meta": {"events_pressure": 0.0,
                                 "unmodeled_growth": 0.40,
                                 "boundary_violation_rate": 0.0}})
        t1 = self_state._prediction_face(cg_j)["d_meta_trend"]
        t2 = self_state._prediction_face(cg_j)["d_meta_trend"]
        ok(t1 == 0.3 and t1 == t2,
           "G1bd_meta_trend = 近窗口均值（0.2/0.4 → 0.3）且幂等")
        card_in = {"subject": "self:test", "information_gap": {}, "trust": {},
                   "short_term": {}, "emotion": "unknown", "affect": "unknown",
                   "importance_self": 1.0, "important_refs": [], "relations": {},
                   "identity_ref": None, "identity_anchors": 0,
                   "dimensions": {}, "state_ts": 1.0, "state_version": 1,
                   "prediction": {"d_meta_trend": t1, "hit_rate": None,
                                  "samples": 0, "threshold": None,
                                  "reflect": False, "beta_mean": None,
                                  "beta_ci95": None, "ece": None,
                                  "calibration": None}}
        body = self_state._render(card_in)
        ok("D_meta" in body and "边界压力趋势" in body
           and str(t1) in body,
           "G2状态卡新增边界压力行（人可读观测面，含趋势值）")
        self_state.refresh(cg_j, force=True)
        r_b = self_state.refresh(cg_j)
        ok(r_b.get("changed") is False,
           "G2brefresh 幂等：无变化刷新 changed=False（不破 B1/B2/B3）")

        # ---------- H MCP 观测面 ----------
        out = mcp_server._metacognition_call(cg_j, {"action": "d_meta"})
        ok(set(d_meta.PROXY_KEYS) <= set(out) and "enabled" in out,
           "H1cg op=metacognition action=d_meta 返回三代理向量")
        ok(out["note"] == metacognition.d_meta_face(cg_j)["note"]
           or set(out) == set(metacognition.d_meta_face(cg_j)),
           "H1b与 metacognition.d_meta_face 同源（单一实现）")
        wrap = cg_j.metacognition_d_meta(window=50)
        ok(set(wrap) == set(out) and wrap["window"] == 50,
           "H2mdcos 包装 metacognition_d_meta(window) 等价可用")
        ok("d_meta" in (metacognition.catalog().get("faces") or []),
           "H2bcatalog 观测面清单含 d_meta")
        try:
            mcp_server._metacognition_call(cg_j, {"action": "no_such_action"})
            ok(False, "H3未知 action 应抛 ValueError")
        except ValueError:
            ok(True, "H3未知 action 仍抛 ValueError（分派失败闭锁）")

        # ---------- I tail_jsonl 原语边界 ----------
        p = os.path.join(tmp, "tail.jsonl")
        ok(d_meta.tail_jsonl(os.path.join(tmp, "nope.jsonl"), 5) == [],
           "I1文件缺失 → []（不抛异常）")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("\n".join(json.dumps({"i": i}) for i in range(300)) + "\n")
        ok(d_meta.tail_jsonl(p, 0) == [], "I1bwindow<=0 → []（无越界读取）")
        ok([r["i"] for r in d_meta.tail_jsonl(p, 3)] == [297, 298, 299],
           "I2尾部窗口取末 3 条（与全量末 3 条一致）")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write('{"i":1}\n{"i":2}\n{"i":3')      # 末行截断
        ok(len(d_meta.tail_jsonl(p, 50)) == 2,
           "I2b截断末行被丢弃（不猜内容，与 read_jsonl 同语义）")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write('{"i":1}\n{"i":2}')              # 末行无换行但完整
        ok(len(d_meta.tail_jsonl(p, 50)) == 2,
           "I2c末行完整但无换行仍计入（写者未落换行不等于坏行）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nd_meta: {PASS} passed, {FAIL} failed")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    raise SystemExit(1 if FAIL else 0)


def JSON_KEYS_UNCHANGED(rec):
    """explore 留痕既有键集合未被本次改动删除（契约守卫）。"""
    need = {"type", "t", "actor", "apply", "n_proposals", "bids", "outcomes",
            "bypass_gain", "gain_deferred"}
    return need <= set(rec)


if __name__ == "__main__":
    main()
