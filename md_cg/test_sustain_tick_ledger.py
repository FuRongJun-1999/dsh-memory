# -*- coding: utf-8 -*-
"""六档「最近成功时刻」台账守卫（R-545，2026-11-10）。

缺陷（审计 P2 生命周期）：`_sustain` 的六档只有 `last_tick_done`（**最后一档**的单值）
——「心跳还在跳、但某档三个月没成功过」这种形态在读数面完全不可见：心跳戳新鲜，
看起来一切正常。

修法：`_wrap_tick` 在每档成功时记 `last_ok_ts[档名]`，随心跳戳一起落盘（跨重启可读）；
`tick_ledger()` 把「每档多久没成功过」算成可判的账（超期口径与 `_stale_tick` 同源）；
`status()` 出 `ticks` / `ticks_overdue` / `ticks_never_ok`；`diagnose()` 真超期给
**warning**（不许被新鲜心跳掩盖），「从没成功过」只给 info（新进程正常形态）。

契约（本文件即其守卫）：

  【1】`tick_ledger` 三态：新鲜 → 不超期；过阈值 → overdue；台账里没有 → 视为超期但
      `last_ok_ts=None`（与「真超期」在读数上可区分）。
  【2】`_wrap_tick` 成功才记账，失败不记账（失败已有 `last_tick_error`）。
  【3】台账随心跳戳落盘：进程重启后从戳里读得回。
  【4】`status()` 三个字段齐备且口径正确。
  【5】`diagnose()`：真超期 → warning `tick_overdue`；全空 → info `tick_never_ok`。

运行：python -m md_cg.test_sustain_tick_ledger
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time

from . import sustain as S
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


class _FakeCG:
    def __init__(self, root):
        self.root = root


def main():
    tmp = tempfile.mkdtemp(prefix="tickled_")
    old_dir = os.environ.get("MDCG_SUSTAIN_DIR")
    os.environ["MDCG_SUSTAIN_DIR"] = os.path.join(tmp, "sustain")
    try:
        ivs = {"beat": 300.0, "heal": 1800.0, "scrub": 3600.0,
               "evolve": 86400.0, "tidy": 21600.0, "sleep": 86400.0}

        print("[1] tick_ledger 三态")
        now = time.time()
        led = S.tick_ledger({"beat": now}, ivs)
        ok(led["beat"]["overdue"] is False, "G1a 新鲜成功 ⇒ 不超期")
        ok(led["beat"]["age_s"] is not None and led["beat"]["age_s"] < 60,
           "G1b age_s 是实测年龄")
        old = S.tick_ledger({"scrub": now - 10 * 86400.0}, ivs)
        ok(old["scrub"]["overdue"] is True, "G1c 十天没成功 ⇒ overdue")
        ok(old["scrub"]["last_ok_ts"] is not None, "G1d 真超期仍保留 last_ok_ts")
        never = S.tick_ledger({}, ivs)
        ok(all(v["last_ok_ts"] is None and v["overdue"] for v in never.values()),
           "G1e 台账里没有 ⇒ last_ok_ts=None（与真超期可区分）")
        bad = S.tick_ledger({"beat": "abc"}, ivs)
        ok(bad["beat"]["last_ok_ts"] is None, "G1f 非法 ts 按「没有」处理，不抛")

        print("[2] _wrap_tick 成功才记账")
        root = os.path.join(tmp, "lib")
        os.makedirs(os.path.join(root, "knowledge"), exist_ok=True)
        cg = MdCGOS(root)
        loop = S.SustainLoop(_FakeCG(root), name="tickled", auto_sleep=False,
                             auto_scrub=False, auto_evolve=False)
        loop._wrap_ticks()
        loop._tick_heal = loop._wrap_tick("heal", lambda *a, **k: None)
        loop._tick_heal()
        ok("heal" in loop.last_ok_ts, "G2a 成功档记账")
        ok("scrub" not in loop.last_ok_ts, "G2b 未跑过的档不入账")

        def _boom(*a, **k):
            raise RuntimeError("boom")

        loop._tick_scrub = loop._wrap_tick("scrub", _boom)
        loop._tick_scrub()
        ok("scrub" not in loop.last_ok_ts, "G2c 失败档不记账（失败另有 last_tick_error）")
        ok((loop.last_tick_error or {}).get("name") == "scrub",
           "G2d 失败仍留 last_tick_error（容忍≠静默）")

        print("[3] 台账随心跳戳落盘（跨重启可读）")
        loop._flush_progress()
        st = S.read_stamp("tickled")
        ok(isinstance(st, dict) and "heal" in (st.get("last_ok_ts") or {}),
           "G3a 戳里有 last_ok_ts")
        ok(isinstance(st.get("tick_intervals"), dict) and "beat" in st["tick_intervals"],
           "G3b 戳里有各档 interval（跨进程可判超期）")
        loop2 = S.SustainLoop(_FakeCG(root), name="tickled", auto_sleep=False,
                              auto_scrub=False, auto_evolve=False)
        s2 = loop2.status()
        ok("heal" in (s2.get("ticks") or {}), "G3c 新实例从戳里读回台账")

        print("[4] status 三字段")
        ok("ticks" in s2 and "ticks_overdue" in s2 and "ticks_never_ok" in s2,
           "G4a ticks / ticks_overdue / ticks_never_ok 齐备")
        ok("scrub" in s2["ticks_never_ok"], "G4b 失败过的档进 never_ok（不冒充健康）")

        print("[5] diagnose 超期变色")
        S.write_stamp("tickled", task_running=False, root=root,
                      last_ok_ts={"beat": time.time(), "scrub": time.time() - 9e5},
                      tick_intervals=ivs)
        d = S.diagnose(cg, name="tickled", check_evolution=False,
                       check_provenance=False)
        codes = [i["code"] for i in d["issues"]]
        ok("tick_overdue" in codes, "G5a 真超期 ⇒ warning tick_overdue")
        od = next(i for i in d["issues"] if i["code"] == "tick_overdue")
        ok(od["severity"] == "warning" and "scrub" in od["sample"],
           "G5b 点名的就是 scrub 档且严重度=warning")
        ok(d["ticks"] and d["ticks"]["beat"]["overdue"] is False,
           "G5c 体检同时给出全量台账（不只看超期那几档）")

        S.write_stamp("tickled", task_running=False, root=root,
                      last_ok_ts={}, tick_intervals=ivs)
        d2 = S.diagnose(cg, name="tickled", check_evolution=False,
                        check_provenance=False)
        codes2 = [i["code"] for i in d2["issues"]]
        ok("tick_never_ok" in codes2 and "tick_overdue" not in codes2,
           "G5d 全空 ⇒ 只有 info tick_never_ok（新进程不被打红）")
    finally:
        if old_dir is None:
            os.environ.pop("MDCG_SUSTAIN_DIR", None)
        else:
            os.environ["MDCG_SUSTAIN_DIR"] = old_dir
        shutil.rmtree(tmp, ignore_errors=True)

    print("\ntest_sustain_tick_ledger: %d 通过 / %d 失败" % (PASSED, FAILED))
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
