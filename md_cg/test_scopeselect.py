# -*- coding: utf-8 -*-
"""范围选择（scopeselect）守卫。"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from md_cg import bucketindex as bi  # noqa: E402
from md_cg import scopeselect as ss  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:170])
        FAILS.append(name)


def main():
    print("=" * 66)
    print("范围选择（scopeselect）")
    print("=" * 66)
    # issue #871 断点 2 后：terms() = 原标点切分 + **汉字 2/3-gram**（中文整串不在
    # 桶 bag（bm25 口径）里 ⇒ 条件桶面恒 0 命中）。故断言改为：原切分按序在**前缀**，
    # 其后只能是对原串的汉字 n-gram（不得混入无关词）。
    _t = ss.terms("分桶 日桶，会话桶")
    ok(_t[:3] == ["分桶", "日桶", "会话桶"], "S1a 原标点切分按序保留在前", _t[:4])
    _q = "分桶日桶会话桶"
    ok(all((x in _q) and len(x) >= 2 for x in _t[3:]), "S1b 追加项均为原串子串", _t[3:])
    ok(all(len(x) in (2, 3) for x in _t[3:]), "S1c 追加项长度只 2/3（不膨胀）", _t[3:])

    root = tempfile.mkdtemp(prefix="scs_")
    g = MdCGOS(root, actor="test")
    ccg = ("# 功能名：{n}\n# 生效条件：c\n# 子功能：s\n# 执行：e\n"
           "# 验证方式：test\n# 不适用条件：无\n\n{body}\n")
    import time as _t
    day_a = _t.mktime(_t.strptime("2026-11-01 10:00:00", "%Y-%m-%d %H:%M:%S"))
    day_b = _t.mktime(_t.strptime("2026-11-05 10:00:00", "%Y-%m-%d %H:%M:%S"))
    g.add("a1", ccg.format(n="分桶甲", s="w", e="1", body="分桶 日桶 设计"),
          created_at=day_a, session="sess_A")
    g.add("b1", ccg.format(n="面板乙", s="w", e="2", body="面板 白屏 修复"),
          created_at=day_b, session="sess_B")
    bi.build(g, write=True, with_content=True)
    scored = ss.score_buckets(g, "分桶 日桶")
    ok(bool(scored), "S2 有词表时可打分", scored[:2])
    ok(scored and scored[0][1] == "day" and scored[0][2] == "2026-11-01",
       "S3 命中桶排在首位", scored[:2])

    picked = ss.pick_scopes(g, "分桶 日桶", session="sess_B")
    ok(picked and picked[0][0] == "session" and picked[0][1] == "sess_B",
       "S4 声明优先：给了会话就先取会话桶", picked[:2])

    empty = ss.score_buckets(g, "完全无关词zzz")
    ok(empty == [], "S5 无命中返回空（不炸）", empty)

    r1 = ss.pick_scopes(g, "分桶 日桶")
    r2 = ss.pick_scopes(g, "分桶 日桶")
    ok([(a[0], a[1]) for a in r1] == [(a[0], a[1]) for a in r2], "S6 确定性")

    print()
    print("scopeselect：%d 项失败" % len(FAILS) if FAILS else "scopeselect：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())