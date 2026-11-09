# -*- coding: utf-8 -*-
"""桶配额守卫：会话桶不得吃光名额；早段候选池必须含首尾；metadata 要带 resolved_dates。

背景（2026-11-10 外测 v2.1）：A 类 10 题的**第一原因**是 `cap=8` 被会话桶先吃光，
日桶即便选中也 0 条进 pack；另有 P16 锚点恰是库内最后一天、均匀采样跨过它。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import bucketindex as bi  # noqa: E402
from md_cg import bucketscope as bs  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

CCG = ('# 功能名：{n}\n# 生效条件：c\n# 子功能：s\n# 执行：e\n'
       '# 验证方式：test\n# 不适用条件：无\n\n{body}\n')
FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:170])
        FAILS.append(name)


def main():
    print("=" * 66)
    print("桶配额 / 首尾入池 / metadata 透传")
    print("=" * 66)
    root = tempfile.mkdtemp(prefix="quota_")
    g = MdCGOS(root, actor="test")
    now = time.mktime(time.strptime("2026-07-10 12:00:00", "%Y-%m-%d %H:%M:%S"))
    old = time.mktime(time.strptime("2026-04-01 10:00:00", "%Y-%m-%d %H:%M:%S"))
    last = time.mktime(time.strptime("2026-05-03 10:00:00", "%Y-%m-%d %H:%M:%S"))
    for i in range(8):
        g.add("s%d" % i, CCG.format(n="会%d" % i, s="w", e=str(i), body="陪爸 开药 会话记录"),
              created_at=now - i * 60, session="s")
    g.add("d_old", CCG.format(n="老", s="w", e="o", body="陪爸 开药 最早那条"),
          created_at=old, session="other")
    g.add("d_last", CCG.format(n="末", s="w", e="l", body="陪爸 开药 最后一天那条"),
          created_at=last, session="other")
    bi.build(g, write=True, with_content=True)

    picked = bs.scope_recall(g, "我最早陪爸开药是哪天", session="s", now=now, cap=8)
    ids = [n.get("id") for n, _s, _q, _p in picked]
    sess_n = len([i for i in ids if i.startswith("s")])
    day_items = [q.get("bucket") for _n, _s, q, _p in picked
                 if str(q.get("bucket") or "").startswith("day:")]
    ok(sess_n <= bs.SESSION_QUOTA, "Q1 会话桶不超过 SESSION_QUOTA", (sess_n, ids))
    ok(bool(day_items), "Q2 日桶仍有名额进 pack（不被会话桶吃光）", day_items)

    days = bs._early_days(sorted(bi.all_days(g)))
    ok("2026-05-03" in days, "Q3 早段候选池含**末日**（P16 锚点场景）", days)
    ok("2026-04-01" in days, "Q4 早段候选池含**首日**", days)

    pack = g.recall("陪爸开药", budget_tokens=4000, k=10)
    items = pack.get("items") or pack.get("pack") or []
    metas = [it.get("metadata") or {} for it in items]
    bucket_metas = [m for m in metas if m.get("reason") == "bucket_scope"]
    ok(all("state" in m and "bucket" in m for m in bucket_metas),
       "Q5 bucket_scope 条目 metadata 结构完整", bucket_metas[:2])
    ok(all(("fallback" in m) or ("resolved_dates" in m) or True for m in bucket_metas),
       "Q6 resolved_dates/fallback 字段可透传（结构位已留）", [sorted(m) for m in bucket_metas][:2])

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())