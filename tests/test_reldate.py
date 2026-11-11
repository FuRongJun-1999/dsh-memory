# -*- coding: utf-8 -*-
"""reldate 守卫：相对日期绝对化的**确定性**（含 #875 三位天数回归）。

#875：`_NDAY` 早先为 `\d{1,2}` 且**无左边界**——「120天前」跳过首位匹配成「20天前」，
把 20 交给换算器 ⇒ 交付**确定但错误**的日期（120天前 标成 2026-10-22，应为 2026-07-14）。
本模块的价值就在「确定性」，给出错日期比不标注更坏，故本守卫把三类都钉住：
  ① 天数完整捕获（1–3 位）+ 范围闸；
  ② 中文数字不被截断（「一百二十天前」不得被当「二十天前」）；
  ③ 非时间用法不被误标（「以上周四为准」「以下月份」）。
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import reldate  # noqa: E402

FAILS = []
STAMP = time.mktime(time.strptime("2026-11-11 12:00:00", "%Y-%m-%d %H:%M:%S"))
BASE = _dt.date(2026, 11, 11)


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:170])
        FAILS.append(name)


def main():
    print("=" * 70)
    print("reldate：确定性（#875 回归 + 边界）")
    print("=" * 70)

    # ---- R1 天数完整捕获（#875 主体）----
    for days in (1, 20, 99, 120, 365):
        want = (BASE - _dt.timedelta(days=days)).isoformat()
        got = reldate.annotate("%d天前完成交稿" % days, STAMP)
        ok(got == "%d天前（%s）完成交稿" % (days, want), "R1 %d 天前 ⇒ %s" % (days, want), got)
    ok(reldate.annotate("3天后", STAMP) == "3天后（%s）" % (BASE + _dt.timedelta(days=3)).isoformat(),
       "R2 天数向前（3天后）")

    # ---- R3 范围闸：超范围不标注（宁缺不错）----
    ok(reldate.annotate("4000天前", STAMP) == "4000天前", "R3 超范围（>3660）不标注",
       reldate.annotate("4000天前", STAMP))

    # ---- R4 中文数字不被截断 ----
    ok(reldate.annotate("一百二十天前", STAMP) == "一百二十天前",
       "R4 「一百二十天前」不得被当「二十天前」", reldate.annotate("一百二十天前", STAMP))
    ok(reldate.annotate("三天前", STAMP) == "三天前（%s）" % (BASE - _dt.timedelta(days=3)).isoformat(),
       "R5 中文数字正常换算（三天前）")

    # ---- R6 非时间用法不被误标 ----
    ok(reldate.annotate("以上周四为准", STAMP) == "以上周四为准", "R6a 「以上周四为准」不标注")
    ok(reldate.annotate("以下月份再说", STAMP) == "以下月份再说", "R6b 「以下月份」不标注")
    ok(reldate.annotate("上周四", STAMP).startswith("上周四（2026-11-05）"), "R6c 「上周四」正常标注")

    # ---- R7 原有用例不回归 ----
    ok(reldate.annotate("上周五是芸青的生日", STAMP) == "上周五（2026-11-06）是芸青的生日",
       "R7a 上周五 ⇒ 2026-11-06")
    ok(reldate.annotate("上周五（2026-11-06）", STAMP) == "上周五（2026-11-06）", "R7b 幂等")
    ok(reldate.annotate("周五", STAMP) == "周五", "R7c 裸「周五」不标")
    ok(reldate.annotate("上周五", None) == "上周五", "R7d 锚点缺失原样返回")

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())