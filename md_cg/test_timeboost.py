# -*- coding: utf-8 -*-
"""时间桶重排（timeboost）守卫——主库「章节 = 写入日期」版结构信号。"""
from __future__ import annotations

import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from md_cg import timeboost as tb  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

FAILS = []
NOW = 1794139000.0


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:180])
        FAILS.append(name)


def node(nid, body, ts):
    return {"id": nid, "content": body, "frontmatter": {"created_at": ts}}


def main():
    print("=" * 66)
    print("时间桶重排（timeboost）")
    print("=" * 66)
    d = tb.query_dates("2026-11-08 那天做了什么", NOW)
    ok(d == {"2026-11-08"}, "T1 完整日期解析", d)
    ok(tb.query_dates("11月8日 的记录", NOW) == {"2026-11-08"},
       "T2 月日解析（年份取 now）", tb.query_dates("11月8日", NOW))
    ok(len(tb.query_dates("今天写了什么", NOW)) == 1, "T3 相对词解析（今天）")
    ok(tb.query_dates("浏览器 面板 白屏", NOW) == set(), "T4 无日期 ⇒ 空集合（不猜）")

    ts_a = time.mktime(time.strptime("2026-11-08 12:00:00", "%Y-%m-%d %H:%M:%S"))
    ts_b = time.mktime(time.strptime("2026-10-01 12:00:00", "%Y-%m-%d %H:%M:%S"))
    ok(tb.node_date(node("x", "c", ts_a)) == "2026-11-08", "T5 候选日期取自 created_at")

    pool = [(node("old", "无关" + "z" * 40, ts_b), 0.9, {}, []),
            (node("new", "无关" + "y" * 40, ts_a), 0.5, {}, [])]
    same = tb.rerank(pool, "浏览器 面板", NOW)
    ok([x[0]["id"] for x in same] == ["old", "new"],
       "T6 无日期查询 ⇒ 原序（零变更）", [x[0]["id"] for x in same])
    ranked = tb.rerank(pool, "2026-11-08 那天", NOW)
    ok(ranked[0][0]["id"] == "new", "T7 命中日期被提升", [x[0]["id"] for x in ranked])
    again = tb.rerank(pool, "2026-11-08 那天", NOW)
    ok([x[0]["id"] for x in ranked] == [x[0]["id"] for x in again], "T8 确定性")

    os.environ.pop("MDCG_TIME_BOOST", None)
    os.environ["MDCG_RECENT_TAIL"] = "0"
    os.environ["MDCG_TOPIC_AGG"] = "0"
    g = MdCGOS(tempfile.mkdtemp(prefix="tbg_"), actor="test")
    ccg = ("# 功能名：{n}\n# 生效条件：语料\n# 子功能：s\n# 执行：e\n"
           "# 验证方式：bench\n# 不适用条件：无\n\n{body}\n")
    g.add("n_old", ccg.format(n="旧", s="w", e="1", body="话题乙 内容"), created_at=ts_b)
    g.add("n_new", ccg.format(n="新", s="w", e="2", body="话题乙 内容"), created_at=ts_a)
    _r0, m0 = g.search_rrf("话题乙", k=5, now=NOW)
    ok(m0.get("time_boost") is False, "T9a 缺省关（meta.time_boost=False）", m0.get("time_boost"))
    os.environ["MDCG_TIME_BOOST"] = "1"
    try:
        _r1, m1 = g.search_rrf("2026-11-08 话题乙", k=5, now=NOW)
        ok(m1.get("time_boost") is True, "T9b 开启后 meta.time_boost=True")
    finally:
        os.environ.pop("MDCG_TIME_BOOST", None)
        os.environ.pop("MDCG_RECENT_TAIL", None)
        os.environ.pop("MDCG_TOPIC_AGG", None)

    print()
    print("timeboost：%d 项失败" % len(FAILS) if FAILS else "timeboost：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())