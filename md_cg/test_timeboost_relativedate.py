# -*- coding: utf-8 -*-
"""相对日期解析守卫（timeboost.query_dates）——Ornn8 六人物 714 题的短板项。

背景（2026-11-10 外部测评）：相对日期 19/44=43%、时间题 27/48=56%，是全部短板所在。
根因之一是解析面只有「今天/昨天/前天」三词，且 MDCG_TIME_BOOST 默认 0。
"""
from __future__ import annotations

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import timeboost as tb  # noqa: E402

FAILS = []
NOW = time.mktime(time.strptime("2026-11-10 12:00:00", "%Y-%m-%d %H:%M:%S"))


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:160])
        FAILS.append(name)


def main():
    print("=" * 66)
    print("相对日期解析（timeboost.query_dates）")
    print("=" * 66)
    one = [
        ("今天", "2026-11-10"),
        ("昨天", "2026-11-09"),
        ("前天", "2026-11-08"),
        ("大前天", "2026-11-07"),
        ("三天前", "2026-11-07"),
        ("十天前", "2026-10-31"),
        ("二十天前", "2026-10-21"),
        ("12天前", "2026-10-29"),
        ("上周三的约定", "2026-11-04"),
        ("这周五去哪", "2026-11-13"),
        ("11月8日的安排", "2026-11-08"),
        ("2026-11-08 的记录", "2026-11-08"),
    ]
    for text, want in one:
        got = sorted(tb.query_dates(text, NOW))
        ok(got == [want], "T1 %s → %s" % (text, want), got)

    wk = sorted(tb.query_dates("上周我们聊了什么", NOW))
    ok(len(wk) == 7 and wk[0] == "2026-11-02" and wk[-1] == "2026-11-08",
       "T2 上周 → 7 天（周一..周日）", wk)
    mo = sorted(tb.query_dates("上个月的房租", NOW))
    ok(len(mo) == 31 and mo[0] == "2026-10-01" and mo[-1] == "2026-10-31",
       "T3 上个月 → 10 月整月", (len(mo), mo[:1], mo[-1:]))
    ok(tb.query_dates("随便聊聊", NOW) == set(), "T4 无日期词 → 空集（不猜）")
    ok(tb.query_dates("上周三", NOW) and len(tb.query_dates("上周三", NOW)) == 1,
       "T5 「上周三」只取单日，不扩成整周", sorted(tb.query_dates("上周三", NOW)))
    # 时钟必须显式：同一 query 在不同 now 下结果不同 ⇒ 证明没有内部 time.time()
    other = NOW - 7 * 86400
    ok(tb.query_dates("三天前", NOW) != tb.query_dates("三天前", other), "T6 时钟由调用方注入（可回放）")

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())