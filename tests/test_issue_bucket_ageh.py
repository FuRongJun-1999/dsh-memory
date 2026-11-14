# -*- coding: utf-8 -*-
"""守卫 · bucketindex.maybe_auto_rebuild 的 age_h 读数（从未重建时的纪元假象）。

缺陷（修复前实测）：
  `last_build_ts()` 在 meta 缺失 / `ts` 为 0 时返回 0.0，而
  `age_h = (time.time() - last_build_ts(store)) / 3600.0`
  于是 "从未重建" 被算成 "自 1970 年至今的小时数"——
  本机实测 `1794589724 / 3600 = 498497.05 h ≈ 56.7 年`。
  读数把这个不存在的历史当成 "很久没重建过"，与真实语义（无历史）相反。

  同一处还有第二个问题：原实现连续调用两次 `last_build_ts(store)`
  （一次算 age_h，一次做判定），两次读盘之间若重建线程写了 meta，
  age_h 与判定基数就不是同一个值。

修复后语义：
  - `last_ts <= 0`（meta 缺失 / ts=0 / 时钟回拨为负）⇒ `age_h is None`（无历史，如实报告）
  - `last_ts > 0` ⇒ 正常小时数，且整个函数只读一次 ts
  - `round(None, 2)` 会抛 TypeError ⇒ 统一走 `_age_round()`

守卫取向：直接用假 store + 真实 `_write_meta`，只断言公开返回值。
"""
from __future__ import annotations

import os
import sys
import tempfile
import shutil
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import bucketindex as bi  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:170])
        FAILS.append(name)


class _FakeStore:
    def __init__(self, root):
        self.root = root


def main():
    print("=" * 70)
    print("bucketindex.maybe_auto_rebuild · age_h 读数（从未重建的纪元假象）")
    print("=" * 70)

    tmp = tempfile.mkdtemp(prefix="ageh_")
    st = _FakeStore(tmp)
    try:
        # A1 从未重建（meta 不存在）—— 原 bug 的触发路径
        r1 = bi.maybe_auto_rebuild(st, interval_h=20, background=False)
        print("  A1 never-built:", r1)
        ok(r1.get("age_h") is None, "A1 从未重建 ⇒ age_h 为 None（不是 498497）",
           r1.get("age_h"))
        ok(r1.get("rebuilt") is True, "A1 从未重建仍应触发重建", r1.get("rebuilt"))

        # A2 100 小时前重建 ⇒ 正常小时数 + 触发重建
        bi._write_meta(st, {"nodes": 1}, time.time() - 3600 * 100)
        r2 = bi.maybe_auto_rebuild(st, interval_h=20, background=False)
        print("  A2 100h-old:", r2)
        ok(r2.get("rebuilt") is True, "A2 超期应重建", r2.get("rebuilt"))
        ok(isinstance(r2.get("age_h"), float) and 99 <= r2["age_h"] <= 101,
           "A2 age_h 应约为 100", r2.get("age_h"))

        # A3 刚重建过 ⇒ fresh，不重建
        bi._write_meta(st, {"nodes": 1}, time.time() - 60)
        r3 = bi.maybe_auto_rebuild(st, interval_h=20, background=False)
        print("  A3 1min-old:", r3)
        ok(r3.get("reason") == "fresh", "A3 未过期应 fresh", r3.get("reason"))
        ok(r3.get("age_h") is not None and r3["age_h"] < 1,
           "A3 age_h 应接近 0", r3.get("age_h"))

        # A4 畸形 meta：ts 恰为 0
        bi._write_meta(st, {"nodes": 1}, 0)
        r4 = bi.maybe_auto_rebuild(st, interval_h=20, background=True)
        print("  A4 ts=0:", r4)
        ok(r4.get("age_h") is None, "A4 ts=0 ⇒ age_h 为 None", r4.get("age_h"))

        # A5 ts 为负（时钟回拨 / 畸形）
        bi._write_meta(st, {"nodes": 1}, -123)
        r5 = bi.maybe_auto_rebuild(st, interval_h=20, background=False)
        print("  A5 ts<0:", r5)
        ok(r5.get("age_h") is None, "A5 ts<0 ⇒ age_h 为 None", r5.get("age_h"))

        # A6 round(None, 2) 不得抛异常
        ok(bi._age_round(None) is None, "A6 _age_round(None) 返回 None 且不抛")
        ok(bi._age_round(1.234) == 1.23, "A6 _age_round(1.234) == 1.23")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 70)
    if FAILS:
        print("失败 %d 项：%s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
