# -*- coding: utf-8 -*-
"""`sleep_scrub_apply` 四处口径统一守卫（R-546，2026-11-10）。

缺陷（审计 P3 语义）：同一个开关在四个地方被描述，其中一处说反了 ——
`sleep.iterate()` 的 docstring 写「缺省只在副本上盘点（不落盘）」，而
`sleep_scrub_apply()` 的 docstring、`SLEEP_ENV_DEFAULTS["scrub_apply"]="1"` 与
`sustain._tick_sleep` 的 docstring 都说「缺省开」，实测值（env 未设）也是 True。
更糟的是 `iterate(scrub_apply: bool = False)` 的**形参缺省**与真源相反：
不传参就静默变成只盘点，而声明处还写着「缺省开」。

修法：文本统一为「缺省开」；`iterate` 形参缺省改 `None` 并回落 `sleep_scrub_apply()`
——**声明的缺省必须等于实测的缺省**。

契约（本文件即其守卫）：

  【1】env 矩阵：未设 / "" / "1" ⇒ True；"0" / "false" / "False" ⇒ False。
  【2】`iterate()` 不传 `scrub_apply` ⇒ 走 env 值（env=1 时 dry_run=False；
      env=0 时 dry_run=True）。
  【3】四处文本同向：不得出现「缺省/默认 + 关」的说法，且必须写明「缺省开」。

运行：python -m md_cg.test_sleep_scrub_default
"""
from __future__ import annotations

import io
import os
import re

from . import consolidate, scrub, sleep

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
    old = os.environ.get("MDCG_SLEEP_SCRUB_APPLY")
    if val is None:
        os.environ.pop("MDCG_SLEEP_SCRUB_APPLY", None)
    else:
        os.environ["MDCG_SLEEP_SCRUB_APPLY"] = val
    try:
        return fn()
    finally:
        if old is None:
            os.environ.pop("MDCG_SLEEP_SCRUB_APPLY", None)
        else:
            os.environ["MDCG_SLEEP_SCRUB_APPLY"] = old


def _slice(text, start_marker, end_marker):
    i = text.index(start_marker)
    j = text.index(end_marker, i)
    return text[i:j]


def main():
    print("[1] env 矩阵（实测值）")
    for val, want in ((None, True), ("", True), ("1", True),
                      ("0", False), ("false", False), ("False", False)):
        got = _with_env(val, sleep.sleep_scrub_apply)
        ok(got is want, "G1 env=%r ⇒ %s" % (val, want))

    print("[2] iterate() 不传参时走 env（不是静默 False）")
    seen = {}

    class _FakeCG:
        def close(self):
            pass

    orig = (sleep._open_cg, consolidate.induce_memories,
            consolidate.promote_memories, scrub.sweep)
    sleep._open_cg = lambda _p: _FakeCG()
    consolidate.induce_memories = lambda cg, apply=True: {"written": 0}
    consolidate.promote_memories = lambda p, apply=True: {"written": 0}
    def _sweep(cg, dry_run=True):
        seen["dry_run"] = dry_run
        return {"dry_run": dry_run, "audit": {}, "n_high_medium": 0,
                "decontaminate": {}}

    scrub.sweep = _sweep
    try:
        seen.clear()
        _with_env("1", lambda: sleep.iterate("x"))
        ok(seen.get("dry_run") is False, "G2a env=1 ⇒ 不传参也真实落盘（dry_run=False）")
        seen.clear()
        _with_env("0", lambda: sleep.iterate("x"))
        ok(seen.get("dry_run") is True, "G2b env=0 ⇒ 只盘点（dry_run=True）")
        seen.clear()
        sleep.iterate("x", scrub_apply=True)
        ok(seen.get("dry_run") is False, "G2c 显式传参仍优先于 env")
    finally:
        (sleep._open_cg, consolidate.induce_memories,
         consolidate.promote_memories, scrub.sweep) = orig

    print("[3] 四处文本同向")
    sp = io.open(os.path.join(HERE, "sleep.py"), encoding="utf-8").read()
    su = io.open(os.path.join(HERE, "sustain.py"), encoding="utf-8").read()
    sites = [
        ("sleep.sleep_scrub_apply docstring",
         _slice(sp, "def sleep_scrub_apply", "return sleep_env(")),
        ("sleep.iterate docstring",
         _slice(sp, "def iterate(", "from . import consolidate")),
        ("sleep.SLEEP_ENV_DEFAULTS 行",
         _slice(sp, '"scrub_apply": "1"', '"scrub_apply": "1"') or ""),
        ("sustain._tick_sleep docstring",
         _slice(su, "def _tick_sleep", "self.sleep_round += 1")),
    ]
    # 缺省表那一行单独取整行
    sites[2] = ("sleep.SLEEP_ENV_DEFAULTS 行",
                next(ln for ln in sp.splitlines() if '"scrub_apply": "1"' in ln))
    bad_dir = re.compile(r"(缺省|默认)[^，。；）]{0,6}(关|False|false|不落盘)")
    good_dir = re.compile(r"(缺省|默认)[^，。；）]{0,6}开|缺省 `\"1\"`|缺省开")
    for name, text in sites:
        ok(bad_dir.search(text) is None, "G3a %s 不含「缺省关/不落盘」" % name)
        ok(good_dir.search(text) is not None, "G3b %s 写明缺省开" % name)

    print("\ntest_sleep_scrub_default: %d 通过 / %d 失败" % (PASSED, FAILED))
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
