# -*- coding: utf-8 -*-
"""信息增益门槛（P-T-40④）+ 价值链筛选（#37）验证。

断言面：
  ① 首探放行：无探索历史 → σ=1.0, gain=None（无证据不否决）
  ② 停滞冷却：连续 2 次终态无变化（DEFER_EXHAUSTED）→ σ=0；冷却过期 → σ=1.0
  ③ 证据不足：仅 1 次记录不冷却；有变化（carried→resolved）→ σ=1.0
  ④ 集成：proposals 端 σ 筛选拦截 → deferred 可审计；enforce_gain=False 放行
  ⑤ explore 留痕 outcomes 实现值（下轮 gain_gate 的裁决输入）
     + meta_outcomes 并列留痕（D_meta 压力，不改 outcomes 值类型）
  ⑥ 预算豁免：bypass_gain=True 冷却中照常探索且留痕 bypass_gain
  ⑦ D_meta 压力冷却：终态停滞且压力仍扩大 → 冷却过期也不放行（新分支）

运行：python -m md_cg.test_gain_gate
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time

from . import autonomy, d_meta, metacognition
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


def _hist(cg, bid, terminals, t0=None, step=5.0):
    t0 = time.time() - 10.0 if t0 is None else t0
    for i, tml in enumerate(terminals):
        append_jsonl(autonomy._explore_log_path(cg),
                     {"type": "explore", "t": t0 + i * step,
                      "actor": "test", "outcomes": {bid: tml}, "bids": [bid]})


def _hist_meta(cg, bid, terminals, delta, t0=None, step=5.0):
    """同 _hist，但并列留 D_meta 跨轮压力增量（新分支的裁决输入）。"""
    t0 = time.time() - 10.0 if t0 is None else t0
    for i, tml in enumerate(terminals):
        append_jsonl(autonomy._explore_log_path(cg),
                     {"type": "explore", "t": t0 + i * step,
                      "actor": "test", "outcomes": {bid: tml}, "bids": [bid],
                      "meta_outcomes": {"delta": {"unmodeled_growth": delta},
                                        "proxy": autonomy.DMETA_PROXY}})


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_gain_")
    try:
        root = os.path.join(tmp, "root")
        os.makedirs(root, exist_ok=True)
        cg = MdCGOS(root)
        bid = metacognition._key("反应堆冷却方案")

        # ---------- ① 首探放行 ----------
        g0 = autonomy.gain_gate(cg, bid, now=250.0)
        ok(g0["sigma"] == 1.0 and g0["gain"] is None,
           "①无探索历史 → σ=1.0, gain=None（Gain 是筛选器，无证据不否决）")

        # ---------- ② 停滞冷却（DEFER_EXHAUSTED） ----------
        _hist(cg, bid, ["carried", "carried"])
        g1 = autonomy.gain_gate(cg, bid, now=time.time())
        ok(g1["sigma"] == 0.0 and g1["gain"] == 0
           and "DEFER_EXHAUSTED" in g1["reason"],
           "②连续 2 次 carried 且冷却内 → σ=0（P-T-40 增益门槛）")
        g2 = autonomy.gain_gate(cg, bid,
                                now=(g1["last_t"] or 0.0) + 3600.0 + 1.0)
        ok(g2["sigma"] == 1.0,
           "②b冷却过期（now>last_t+3600）→ σ=1.0（不永久冻结）")

        # ---------- ③ 证据不足 / 有变化 ----------
        cg2_root = os.path.join(tmp, "root2")
        os.makedirs(cg2_root, exist_ok=True)
        cg2 = MdCGOS(cg2_root)
        _hist(cg2, bid, ["carried"])
        ok(autonomy.gain_gate(cg2, bid, now=250.0)["sigma"] == 1.0,
           "③仅 1 次记录（< GAIN_WINDOW=2）不冷却（证据不足放行）")
        cg3_root = os.path.join(tmp, "root3")
        os.makedirs(cg3_root, exist_ok=True)
        cg3 = MdCGOS(cg3_root)
        _hist(cg3, bid, ["carried", "resolved"])
        g3 = autonomy.gain_gate(cg3, bid, now=250.0)
        ok(g3["sigma"] == 1.0 and g3["gain"] == 1,
           "③b终态有变化（carried→resolved）→ 有增益 σ=1.0")

        # ---------- ④ proposals 集成：σ 筛选拦截 ----------
        cg4_root = os.path.join(tmp, "root4")
        os.makedirs(cg4_root, exist_ok=True)
        cg4 = MdCGOS(cg4_root)
        _sig(cg4, 1.0, "反应堆冷却方案", 0.9, {"BLINDSPOT": 2})
        _hist(cg4, bid, ["carried", "carried"])
        pr = autonomy.proposals(cg4)
        ok(not pr["proposals"] and len(pr["deferred"]) == 1
           and pr["deferred"][0]["status"] == "deferred_exhausted",
           "④冷却中盲区被 σ 筛选拦截 → deferred 可审计（不静默丢弃）")
        ok(pr["deferred"][0]["score"] > 0,
           "④b被拦提案的 ΔD 定价仍在（被拦原因=σ=0 非 score 低）")
        ok("σ(Gain)" in pr["value_chain"],
           "④c价值链口径声明（score 定价排序 + σ 资格筛选）")
        pr2 = autonomy.proposals(cg4, enforce_gain=False)
        ok(len(pr2["proposals"]) == 1 and not pr2["deferred"],
           "④denforce_gain=False 放行（预算豁免入口）")

        # ---------- ⑤ explore 留痕 outcomes ----------
        cg5_root = os.path.join(tmp, "root5")
        os.makedirs(cg5_root, exist_ok=True)
        cg5 = MdCGOS(cg5_root)
        cg5.add("k1", "# 功能名：反应堆冷却知识\n"
                     "# 生效条件：问反应堆冷却方案\n"
                     "# 子功能：知识片段\n"
                     "# 执行：陈述知识\n"
                     "# 验证方式：test\n"
                     "# 不适用条件：无\n"
                     "反应堆冷却方案概述。\n",
               layer="knowledge", verification_basis="test")
        _sig(cg5, 1.0, "反应堆冷却方案", 0.9, {"BLINDSPOT": 2})
        ex = autonomy.explore(cg5, actor="test")
        with open(autonomy._explore_log_path(cg5), encoding="utf-8") as f:
            rec = [__import__("json").loads(x) for x in f if x.strip()][-1]
        ok(rec.get("outcomes") and set(rec["outcomes"]) == set(rec["bids"]),
           "⑤explore 留痕 outcomes（实现值，下轮 gain_gate 裁决输入）")
        ok(all(t in ("unknowable", "no_anchor", "unresolved", "carried",
                     "resolved") for t in rec["outcomes"].values()),
           "⑤b实现值为诚实五态（不编造）")
        ok(rec.get("bypass_gain") is False, "⑤c留痕 bypass_gain=False")
        mo = rec.get("meta_outcomes") or {}
        ok(set(mo.get("before") or {}) == set(d_meta.PROXY_KEYS)
           and mo.get("proxy") == autonomy.DMETA_PROXY,
           "⑤dexplore 留痕 meta_outcomes.before（D_meta 三代理，并列不改 outcomes）")
        ok(all(isinstance(v, str) for v in rec["outcomes"].values()),
           "⑤eoutcomes 值仍为终态字符串（dict 化会使 σ 静默恒 1.0，此处守卫）")

        # ---------- ⑥ 预算豁免 ----------
        cg6_root = os.path.join(tmp, "root6")
        os.makedirs(cg6_root, exist_ok=True)
        cg6 = MdCGOS(cg6_root)
        cg6.add("k1", "# 功能名：反应堆冷却知识\n"
                     "# 生效条件：问反应堆冷却方案\n"
                     "# 子功能：知识片段\n"
                     "# 执行：陈述知识\n"
                     "# 验证方式：test\n"
                     "# 不适用条件：无\n"
                     "反应堆冷却方案概述。\n",
               layer="knowledge", verification_basis="test")
        _sig(cg6, 1.0, "反应堆冷却方案", 0.9, {"BLINDSPOT": 2})
        _hist(cg6, bid, ["carried", "carried"])
        ex2 = autonomy.explore(cg6, actor="test", bypass_gain=True)
        ok(bool(ex2["steps"]) and ex2["steps"][0]["blindspot_id"] == bid,
           "⑥预算豁免：冷却中盲区 bypass_gain=True 仍照常探索（2.9.3.1）")
        with open(autonomy._explore_log_path(cg6), encoding="utf-8") as f:
            rec6 = [__import__("json").loads(x) for x in f if x.strip()][-1]
        ok(rec6.get("bypass_gain") is True,
           "⑥b豁免留痕可审计（bypass_gain=True）")

        # ---------- ⑦ D_meta 压力冷却（新分支） ----------
        cg7_root = os.path.join(tmp, "root7")
        os.makedirs(cg7_root, exist_ok=True)
        cg7 = MdCGOS(cg7_root)
        _hist_meta(cg7, bid, ["carried", "carried"], 0.2)
        g7 = autonomy.gain_gate(cg7, bid, now=time.time() + 3600.0 + 60.0)
        ok(g7["sigma"] == 0.0 and "UNDER_PRESSURE" in g7["reason"],
           "⑦停滞 + 压力仍扩大 → 冷却过期也不放行（DEFER_EXHAUSTED_UNDER_PRESSURE）")
        ok(g7.get("meta_rising") is True,
           "⑦b新分支留痕 meta_rising=True（可审计，不静默冷却）")
        ok(autonomy.gain_gate(cg7, bid, now=time.time())["sigma"] == 0.0,
           "⑦c冷却内仍走既有分支（口径保持，不重复计算）")
        cg8_root = os.path.join(tmp, "root8")
        os.makedirs(cg8_root, exist_ok=True)
        cg8 = MdCGOS(cg8_root)
        _hist_meta(cg8, bid, ["carried", "carried"], 0.0)
        ok(autonomy.gain_gate(cg8, bid,
                              now=time.time() + 3600.0 + 60.0)["sigma"] == 1.0,
           "⑦d压力未扩大（delta=0）→ 冷却过期照旧放行（只在上升时延长）")
        cg9_root = os.path.join(tmp, "root9")
        os.makedirs(cg9_root, exist_ok=True)
        cg9 = MdCGOS(cg9_root)
        _hist(cg9, bid, ["carried", "carried"])
        ok(autonomy.gain_gate(cg9, bid,
                              now=time.time() + 3600.0 + 60.0)["sigma"] == 1.0,
           "⑦e缺 meta_outcomes 键 → 新分支不触发（旧留痕兼容）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\ngain_gate: {PASS} passed, {FAIL} failed")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
