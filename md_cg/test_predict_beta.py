# -*- coding: utf-8 -*-
"""通道贝叶斯后验（P-T-73/74）验证：Beta-Bernoulli 置信更新。

断言面：
  ① 纯函数数学：先验=基线（空历史 mean=0.40）；小样本向基线收缩
    （n=5 全命中 → 0.52，不过度自信到 1.0）；大样本收敛（n=200 → 0.9455）；
    方差闭式与区间对称
  ② 通道分组与留痕：feedback(channel=...) 落 _prediction.jsonl；
    未标注归 "unlabeled"；channel_posterior 分通道/单通道/limit 截断
  ③ 自我模型集成：self_state 预测面带 beta_mean/ci95；正文渲染；留痕字段
  ④ 零回归面：dynamic_hit_threshold/hit_rate 默认行为不变；stats/catalog 增补

运行：python -m md_cg.test_predict_beta
"""
from __future__ import annotations

import json
import os
import tempfile

from . import predict, self_state
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


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_beta_")
    try:
        root = os.path.join(tmp, "root")
        os.makedirs(root, exist_ok=True)
        cg = MdCGOS(root)

        # ---------- ① 纯函数数学 ----------
        p0 = predict.beta_posterior([])
        ok(p0["mean"] == predict.BASE_HIT_RATE and p0["samples"] == 0,
           "①空序列 → 先验（mean=0.40=BASE_HIT_RATE，口径无缝）")
        ok(p0["alpha"] == 8.0 and p0["beta"] == 12.0,
           "①b先验参数 α0=0.4×20=8 β0=12")

        p5 = predict.beta_posterior([True] * 5)
        ok(p5["mean"] == 0.52 and p5["samples"] == 5,
           "①c小样本收缩：n=5 全命中 → mean=0.52（滑动均值会到 1.0 过度自信）")
        ok(0.4 < p5["mean"] < 1.0, "①d证据上拉但不越界")

        p200 = predict.beta_posterior([True] * 200)
        ok(p200["mean"] == 0.9455 and p200["ci95"] == [0.9155, 0.9754],
           "①e大样本收敛：n=200 全命中 → mean=0.9455，CI=[0.9155,0.9754] 收窄")

        p50 = predict.beta_posterior([True] * 50 + [False] * 50)
        ok(p50["mean"] == 0.4833, "①f半对半 n=100 → mean=0.4833（58/120）")
        lo, hi = p50["ci95"]
        ok(lo < p50["mean"] < hi and abs((p50["mean"] - lo) - (hi - p50["mean"])) < 2e-4,
           "①gCI95 对称包住后验均值")

        # ---------- ② 通道分组与留痕 ----------
        for _ in range(3):
            predict.feedback(cg, "n_c", hit=True, channel="causal",
                             sync_self=False, note="t")
        for _ in range(2):
            predict.feedback(cg, "n_s", hit=False, channel="semantic",
                             sync_self=False, note="t")
        predict.feedback(cg, "n_u", hit=True, sync_self=False, note="t")

        hist = predict.channel_history(cg)
        ok(set(hist) == {"causal", "semantic", "unlabeled"},
           "②三通道分组（未标注诚实归 unlabeled）")
        ok(len(hist["causal"]) == 3 and len(hist["semantic"]) == 2
           and len(hist["unlabeled"]) == 1, "②b各通道计数 3/2/1")

        post = predict.channel_posterior(cg)
        ok(post["all"]["samples"] == 6 and post["all"]["hits"] == 4,
           "②c全量后验 samples=6 hits=4")
        ok(post["channels"]["causal"]["mean"] > post["channels"]["semantic"]["mean"],
           "②d通道分离：causal 全命中(0.4783) > semantic 全 miss(0.3636)")
        ok(post["all"]["mean"] == 0.4615,
           "②e全量后验 12/26=0.4615（介于两通道之间）")

        one = predict.channel_posterior(cg, channel="causal")
        ok(one["channel"] == "causal" and one["samples"] == 3
           and one["mean"] == 0.4783, "②f单通道查询（11/23=0.4783）")
        ok(len(predict.channel_history(cg, limit=2)) >= 1,
           "②glimit 截断不崩溃")

        # ---------- ③ 自我模型集成 ----------
        r = self_state.refresh(cg, actor="t_beta")
        pd = (r.get("state") or {}).get("prediction") or {}
        ok(r["ok"] and pd.get("beta_mean") == 0.4615
           and pd.get("beta_ci95"), "③self_state 预测面带后验（beta_mean/ci95）")
        ok(pd.get("hit_rate") == 0.6667,
           "③b滑动 hit_rate 与后验并存（两种估计面，互不替代）")
        st = self_state.snapshot(cg)
        ok(st and st["prediction"]["beta_mean"] == 0.4615, "③c快照可读")
        node = cg.get(self_state.state_node_id())
        ok("后验可信度" in (node.get("content") or ""), "③d正文渲染含后验可信度")
        with open(os.path.join(root, "_self_state.jsonl"), encoding="utf-8") as f:
            tail = [json.loads(x) for x in f if x.strip()][-1]
        ok(tail.get("prediction_beta_mean") == 0.4615,
           "③e留痕字段 prediction_beta_mean")

        # ---------- ④ 零回归面 ----------
        dth = predict.dynamic_hit_threshold(cg)
        ok(dth["samples"] == 6 and dth["reflect"] is False
           and dth["threshold"] == predict.BASE_HIT_RATE,
           "④dynamic_hit_threshold 默认行为不变（样本<50 不触发反思）")
        ok(predict.hit_rate(cg) == 0.6667, "④bhit_rate 滑动口径不变（4/6）")
        stt = predict.stats(cg)
        ok("beta" in stt and stt["beta"]["channels"]["causal"]["samples"] == 3,
           "④cstats 带 beta 通道分解")
        ok(any("P-T-73/74" in k for k in predict.catalog()["decisions"]),
           "④dcatalog 自描述含通道贝叶斯条目")

        print(f"\n测试完成：{PASS} 通过 / {FAIL} 失败")
        if FAILS:
            for f in FAILS:
                print(f"  - {f}")
        print("ALL PASS" if FAIL == 0 else "HAS FAILURES")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
