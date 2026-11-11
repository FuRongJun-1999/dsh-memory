# -*- coding: utf-8 -*-
"""预测反馈的 hit 与动态阈值守卫（R-551 / R-552，2026-11-10）。

两个缺陷都在 `md_cg/predict.py`：

  R-551（P1-E1）**hit 恒真**：`act = str(actual_node_id or "").strip() or pred`
  之后判 `hit = (pred == act)` —— 不传 actual 时 act 就是 pred，恒等 ⇒ 每次
  「什么都没观测到」都被记成命中，命中率与阈值校准被灌水。
  修后：没有 actual 就没有命中可言，`hit=None` / `recorded=False`，不 boost、
  不 rejected、不计入命中率。

  R-552（P1-E2）**σ 项代数恒消**：`th = max(BASE, mean-2σ)`，判据 `low = mean < th`
  —— 等价于 `mean < BASE`，σ 根本不参与。修后拿**最近窗口**命中率与动态阈值比，
  σ 才真正决定阈值松紧。

契约（本文件即其守卫）：

  【1】不传 actual、不传 hit ⇒ hit=None、recorded=False、不 boost、不 rejected、
      命中历史条数不变（不记）。
  【2】传 actual 且相等 ⇒ hit=True、boost；不等 ⇒ hit=False、进 rejected。
  【3】显式 hit=True/False 优先（既有调用面不变）。
  【4】`_hit_history` 跳过 hit=None 的记录（未知 ≠ 未命中）。
  【5】σ 项生效：存在样本使「旧判据不反思、新判据反思」，且波动越大阈值越低。

运行：python -m md_cg.test_predict_hit_honest
"""
from __future__ import annotations

import os
import shutil
import tempfile

from . import predict
from .mdcos import MdCGOS

PASSED = FAILED = 0


def ok(cond, name):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print("  [PASS] " + name)
    else:
        FAILED += 1
        print("  [FAIL] " + name)


def _cg(tmp, tag):
    root = os.path.join(tmp, tag)
    os.makedirs(os.path.join(root, "knowledge"), exist_ok=True)
    cg = MdCGOS(root)
    cg.add("pa", "# 功能名：A\n\n正文 A。\n", layer="knowledge")
    cg.add("pb", "# 功能名：B\n\n正文 B。\n", layer="knowledge")
    cg.flush()
    cg.rebuild_index()
    return cg


def main():
    tmp = tempfile.mkdtemp(prefix="predhit_")
    try:
        print("[1] 没有 actual ⇒ 不判命中（R-551）")
        cg = _cg(tmp, "a")
        n0 = len(predict._hit_history(cg, limit=1000))
        fb = predict.feedback(cg, "pa", sync_self=False)
        ok(fb["hit"] is None, "G1a hit=None（修前恒 True）")
        ok(fb["recorded"] is False, "G1b recorded=False")
        ok("boosted" not in fb, "G1c 不 boost")
        ok("rejected_id" not in fb, "G1d 不登记 rejected")
        ok(fb.get("skipped"), "G1e 给出显式跳过理由（不静默）")
        ok(len(predict._hit_history(cg, limit=1000)) == n0,
           "G1f 不计入命中率分母（未知 ≠ 未命中）")

        print("[2] 有 actual ⇒ 照常判定")
        fb2 = predict.feedback(cg, "pa", actual_node_id="pa", sync_self=False)
        ok(fb2["hit"] is True and fb2["recorded"] is True, "G2a 相同 ⇒ hit=True")
        fb3 = predict.feedback(cg, "pa", actual_node_id="pb", sync_self=False)
        ok(fb3["hit"] is False and fb3.get("rejected_id"), "G2b 不同 ⇒ hit=False 且进 rejected")

        print("[3] 显式 hit 优先")
        fb4 = predict.feedback(cg, "pa", hit=True, sync_self=False)
        ok(fb4["hit"] is True, "G3a 显式 hit=True 不被 actual 缺失改写")

        print("[4] _hit_history 跳过 None")
        h = predict._hit_history(cg, limit=1000)
        ok(all(isinstance(x, bool) for x in h) and len(h) == 3,
           "G4 只有三条有判定的记录（G1 那条 None 不在内）（%s）" % (h,))

        print("[5] σ 项真正参与（R-552）")
        # 造 200 条样本（= HIT_HISTORY_MAX）：整体命中率 95%，但最近 20 条只有 50%。
        # 为什么是这个形状：hit 是二值量，σ=sqrt(p(1-p))，只有当 p 很高时
        # mean-2σ 才会浮出 BASE_HIT_RATE=0.4 的地板 —— 那正是「动态死区」该起作用
        # 的地方（高命中率体系里最近一段突然掉下来）。
        cg2 = _cg(tmp, "b")
        hist = [True] * 180 + [True] * 10 + [False] * 10   # 190 True / 10 False
        for i, x in enumerate(hist):
            predict._append(cg2, {"type": "feedback", "t": 1000.0 + i,
                                  "predicted": "pa", "actual": "pa", "hit": x})
        d = predict.dynamic_hit_threshold(cg2)
        old_low = d["mean"] < d["threshold"]          # 修前判据
        ok(d["mean"] >= predict.BASE_HIT_RATE,
           "G5a 前提：全窗均值 %.4f ≥ 基线 %.2f" % (d["mean"], predict.BASE_HIT_RATE))
        ok(old_low is False, "G5b 修前判据（mean < th）在该样本上恒不反思")
        ok(d["reflect"] is True,
           "G5c 修后判据（最近窗口 %.4f < 阈值 %.4f）反思 ⇒ 判据不同"
           % (d["recent_rate"], d["threshold"]))
        ok(d["recent_window"] == predict.RECENT_WINDOW, "G5d 比较对象是最近窗口")

        # 波动越小 ⇒ 阈值越高（σ 参与的直接证据）：200 全命中（σ=0）阈值应贴均值 1.0，
        # 而 190/10（σ=0.218）阈值 ≈ 0.51 —— 两者都浮出地板 0.4，可直接比。
        cg3 = _cg(tmp, "c")
        for i, x in enumerate([True] * 190 + [False] * 10):
            predict._append(cg3, {"type": "feedback", "t": 3000.0 + i,
                                  "predicted": "pa", "actual": "pa", "hit": x})
        d_wide = predict.dynamic_hit_threshold(cg3)
        cg4 = _cg(tmp, "d")
        for i, x in enumerate([True] * 200):
            predict._append(cg4, {"type": "feedback", "t": 4000.0 + i,
                                  "predicted": "pa", "actual": "pa", "hit": x})
        d_narrow = predict.dynamic_hit_threshold(cg4)
        ok(d_narrow["std"] < d_wide["std"] and d_narrow["threshold"] > d_wide["threshold"],
           "G5e 波动更小 ⇒ 阈值更高（σ=%.4f/阈值 %.4f vs σ=%.4f/阈值 %.4f）"
           % (d_narrow["std"], d_narrow["threshold"],
              d_wide["std"], d_wide["threshold"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\ntest_predict_hit_honest: %d 通过 / %d 失败" % (PASSED, FAILED))
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
