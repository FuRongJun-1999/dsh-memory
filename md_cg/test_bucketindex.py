# -*- coding: utf-8 -*-
"""日桶 / 会话桶索引守卫（bucketindex + bucketscope）。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from md_cg import bucketindex as bi  # noqa: E402
from md_cg import bucketscope as bs  # noqa: E402
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
    print("日桶 / 会话桶（bucketindex + bucketscope）")
    print("=" * 66)
    ts = time.mktime(time.strptime("2026-11-08 10:00:00", "%Y-%m-%d %H:%M:%S"))
    ok(bi.day_of(ts) == "2026-11-08", "B1 day_of 解析", bi.day_of(ts))
    ok(bi.day_of("不是时间") is None, "B1b 非法输入返回 None")

    root = tempfile.mkdtemp(prefix="bi_")
    g = MdCGOS(root, actor="test")
    ccg = ("# 功能名：{n}\n# 生效条件：c\n# 子功能：s\n# 执行：e\n"
           "# 验证方式：test\n# 不适用条件：无\n\n{body}\n")
    g.add("d1", ccg.format(n="甲", s="w", e="1", body="索引 陈旧 问题"),
          created_at=ts, session="sess_A")
    g.add("d2", ccg.format(n="乙", s="w", e="2", body="索引 迁移 记录"),
          created_at=ts + 3600, session="sess_A")
    g.add("d3", ccg.format(n="丙", s="w", e="3", body="无关 内容"),
          created_at=ts, session=None)
    stats = bi.build(g, write=True)
    ok(stats["nodes"] == 3 and stats["unattributed"] == 1,
       "B2 建桶：节点数 3 且 unattributed 计 1", stats)
    ok(os.path.exists(os.path.join(root, bi.DAYS_FILE)), "B2b _days.json 落盘")
    ok(sorted(bi.day_ids(g, "2026-11-08")) == ["d1", "d2", "d3"],
       "B3 日桶命中当天的 3 条", bi.day_ids(g, "2026-11-08"))
    ok(sorted(bi.session_ids(g, "sess_A")) == ["d1", "d2"],
       "B3b 会话桶只含该会话 2 条", bi.session_ids(g, "sess_A"))

    hit = bs.day_scope(g, "索引", "2026-11-08", cap=5)
    ok(len(hit or []) == 2, "B4 日桶召回按词面筛选（2 条含「索引」）",
       len(hit or []))
    ok(bs.session_scope(g, "索引", bi.UNATTRIBUTED) is None,
       "B5 unattributed 明确拒绝（不冒充会话）")
    ok(bs.day_scope(g, "索引", "1999-01-01") is None, "B6 不存在的桶返回 None")

    r1 = bs.day_scope(g, "索引", "2026-11-08", cap=5)
    r2 = bs.day_scope(g, "索引", "2026-11-08", cap=5)
    ok([x[0]["id"] for x in r1] == [x[0]["id"] for x in r2], "B7 确定性")
    ok(bs.MAX_SCAN == 800, "B8 扫描预算常量固定（快/全取舍显式）", bs.MAX_SCAN)

    print()
    print("bucketindex：%d 项失败" % len(FAILS) if FAILS else "bucketindex：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())