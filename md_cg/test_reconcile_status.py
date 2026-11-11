# -*- coding: utf-8 -*-
"""对账三态可观测守卫（R-544，2026-11-10）。

缺陷（审计 P2 生命周期）：`_reconcile` 的三种情况在盘面**完全不可区分**——
干净库不写留痕、被 `MDCG_RECONCILE=0` 关掉什么都不写、从来没跑过同样什么都没有。
于是「对账到底有没有在工作」只能靠读代码猜。

修法：每次进入 `reconcile_state` 都落一枚 **aux 目录**（`sustain.net_dir()`）下的
单文件戳（原子覆写、不增长），`reconcile.status()` 读它给出四读数；
`sustain.diagnose()` 把它并进体检结论。库根仍保持「干净库零写盘」。

契约（本文件即其守卫）：

  【1】从未跑过 ⇒ `never_run`（无戳）。
  【2】`MDCG_RECONCILE=0` ⇒ `disabled`（**不是** clean）。
  【3】开着且 diff 全零 ⇒ `clean`；有 diff ⇒ `dirty` 且三类计数如实。
  【4】`diagnose()` 透出 `reconcile` 段，disabled/never_run 各出一条 info 项。
  【5】库根零写盘性质不变：干净库跑完仍无 `_reconcile.jsonl`。

运行：python -m md_cg.test_reconcile_status
"""
from __future__ import annotations

import os
import shutil
import tempfile

from . import nodefile, reconcile, sustain
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


def _mk(root, nid):
    os.makedirs(os.path.join(root, "knowledge"), exist_ok=True)
    with open(os.path.join(root, "knowledge", nid + ".md"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write(nodefile.dumps({"id": nid, "layer": "knowledge",
                                "modality": "text", "importance": 0.5,
                                "confidence": 0.6, "tags": []},
                               "# 功能名：%s\n\n正文。\n" % nid))


def main():
    tmp = tempfile.mkdtemp(prefix="recstat_")
    old_dir = os.environ.get("MDCG_SUSTAIN_DIR")
    old_sw = os.environ.get("MDCG_RECONCILE")
    os.environ["MDCG_SUSTAIN_DIR"] = os.path.join(tmp, "sustain")
    try:
        root = os.path.join(tmp, "lib")
        _mk(root, "rs1")
        cg = MdCGOS(root)
        cg.rebuild_index()

        print("[1] 从未跑过")
        ok(reconcile.status()["state"] == "never_run", "G1a 无戳 ⇒ never_run")
        ok(not os.path.exists(os.path.join(tmp, "sustain",
                                           "heartbeat.reconcile.stamp")),
           "G1b 前提：确实没有戳")

        print("[2] 被关掉")
        os.environ["MDCG_RECONCILE"] = "0"
        try:
            rep = reconcile.reconcile_state(cg, apply=True)
        finally:
            os.environ.pop("MDCG_RECONCILE", None)
        ok(rep.get("skipped") is True, "G2a 关闭时直接跳过")
        st = reconcile.status()
        ok(st["state"] == "disabled", "G2b 读数 = disabled（不是 clean，也不是 never_run）")
        ok("MDCG_RECONCILE=0" in (st["detail"] or ""), "G2c detail 点明是被谁关的")

        print("[3] 干净 / 有 diff")
        rep = reconcile.reconcile_state(cg, apply=True)
        ok(rep["ghost_entries"] == [] and rep["hash_drift"] == [],
           "G3a 前提：干净库三类全零")
        st = reconcile.status()
        ok(st["state"] == "clean", "G3b 干净 ⇒ clean")
        ok(not os.path.exists(os.path.join(root, "_reconcile.jsonl")),
           "G3c 库根零写盘性质不变（无留痕文件）")

        os.remove(os.path.join(root, "knowledge", "rs1.md"))   # 造真幽灵
        rep = reconcile.reconcile_state(cg, apply=True)
        st = reconcile.status()
        ok(st["state"] == "dirty", "G4a 有 diff ⇒ dirty")
        ok(st["ghost"] == 1 and st["applied"] is True,
           "G4b 计数与「是否已修」如实（ghost=%s applied=%s）"
           % (st.get("ghost"), st.get("applied")))

        print("[4] diagnose 透出")
        d = sustain.diagnose(cg)
        ok("reconcile" in d and d["reconcile"]["state"] in reconcile.STATES,
           "G5a diagnose 带 reconcile 段")
        os.environ["MDCG_RECONCILE"] = "0"
        try:
            reconcile.reconcile_state(cg, apply=True)
        finally:
            os.environ.pop("MDCG_RECONCILE", None)
        d2 = sustain.diagnose(cg)
        codes = [i["code"] for i in d2["issues"]]
        ok("reconcile_disabled" in codes, "G5b disabled 在体检里是一条可读结论")
        ok(d2["reconcile"]["state"] == "disabled", "G5c 体检读数与 status() 同源")
    finally:
        if old_dir is None:
            os.environ.pop("MDCG_SUSTAIN_DIR", None)
        else:
            os.environ["MDCG_SUSTAIN_DIR"] = old_dir
        if old_sw is not None:
            os.environ["MDCG_RECONCILE"] = old_sw
        shutil.rmtree(tmp, ignore_errors=True)

    print("\ntest_reconcile_status: %d 通过 / %d 失败" % (PASSED, FAILED))
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
