# -*- coding: utf-8 -*-
"""自治档位「生效面」接线守卫（R-553，2026-11-10）。

缺陷（审计 P1-E3）：`autonomy_modes.settle()` 是设计 §六/§七 的**生效面**，
但全仓**零调用** ⇒ `MDCG_AUTONOMY=full` 时 `mode()` 因「未结算」直接返回 full，
准入读数 R1–R4 一条都没校验：常驻进程里的 full 档等于无条件开放。

修法：`mcp_server` 启动链里调一次 `settle(root=root)`——读数不满足 ⇒ effective
回落 confirm 且启动面逐条告警；非法 env ⇒ fail-closed 拒绝启动。

契约（本文件即其守卫）：

  【1】`MDCG_AUTONOMY=full` 且读数不满足 ⇒ `settle()` 返回 effective=confirm、
      alerts 非空，且 `mode()` 随之回落 confirm（不静默降级）。
  【2】`mcp_server` 的启动链里**真有**这处调用（源码级钉子，防「又变成零调用」）。
  【3】非法 env ⇒ `settle()` fail-closed 抛 AutonomyModeError（不静默降级）。
  【4】plan/confirm 档零 IO 不受影响（回归）。

运行：python -m md_cg.test_autonomy_settle_wiring
"""
from __future__ import annotations

import io
import os
import shutil
import tempfile

from . import autonomy_modes as AM

PASSED = FAILED = 0
HERE = os.path.dirname(os.path.abspath(__file__))


def ok(cond, name):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print("  [PASS] " + name)
    else:
        FAILED += 1
        print("  [FAIL] " + name)


def _with_env(val, fn):
    old = os.environ.get("MDCG_AUTONOMY")
    if val is None:
        os.environ.pop("MDCG_AUTONOMY", None)
    else:
        os.environ["MDCG_AUTONOMY"] = val
    try:
        return fn()
    finally:
        if old is None:
            os.environ.pop("MDCG_AUTONOMY", None)
        else:
            os.environ["MDCG_AUTONOMY"] = old


def main():
    tmp = tempfile.mkdtemp(prefix="autoset_")
    try:
        print("[1] full + 读数不满足 ⇒ 回落 confirm")
        empty = os.path.join(tmp, "empty")
        os.makedirs(empty, exist_ok=True)

        def _run():
            return AM.settle(root=empty, force=True)

        st = _with_env("full", _run)
        ok(st["configured"] == "full", "G1a configured=full")
        ok(st["effective"] == AM.CONFIRM,
           "G1b 读数不满足 ⇒ effective 回落 confirm（%s）" % (st["effective"],))
        ok(bool(st["alerts"]), "G1c 逐条列出缺哪条读数（alerts=%d）" % len(st["alerts"]))
        ok(_with_env("full", AM.mode) == AM.CONFIRM,
           "G1d mode() 随之回落 confirm（结算生效面真起作用）")

        print("[2] 启动链里真有这处调用")
        src = io.open(os.path.join(HERE, "mcp_server.py"), encoding="utf-8").read()
        ok("autonomy_modes as _am" in src and "_am.settle(root=root)" in src,
           "G2a mcp_server 启动链调 settle(root=root)（源码级钉子）")
        ok("自治档位结算" in src, "G2b 回落/异常都有启动面告警文案")

        print("[3] 非法 env ⇒ fail-closed")
        try:
            _with_env("bogus", lambda: AM.settle(root=empty, force=True))
            raised = None
        except AM.AutonomyModeError as e:
            raised = str(e)
        ok(raised is not None, "G3 非法档位抛 AutonomyModeError（不静默降级）")

        print("[4] plan/confirm 零 IO 不受影响")
        st2 = _with_env("confirm", lambda: AM.settle(root=empty, force=True))
        ok(st2["effective"] == AM.CONFIRM and not st2["alerts"],
           "G4a confirm 档零告警（零 IO 路径不变）")
        st3 = _with_env("plan", lambda: AM.settle(root=empty, force=True))
        ok(st3["effective"] == "plan" and not st3["alerts"],
           "G4b plan 档零告警（零 IO 路径不变）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\ntest_autonomy_settle_wiring: %d 通过 / %d 失败" % (PASSED, FAILED))
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
