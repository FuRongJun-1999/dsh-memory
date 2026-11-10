# -*- coding: utf-8 -*-
"""候选日桶排序守卫：两端交替池 + 证据优先序（外测 2026-11-11 剩余 6 个锚点）。

两条实测教训：
  ① 池子只取「最早 4 + 末 2」时，锚点在**倒数第三**就压根不在池里；
  ② 即便在池里（末日），升序排到队尾、日名额只有 4–8 个 ⇒ 永远轮不到。
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
    print("候选日桶：两端交替池 + 证据优先序")
    print("=" * 66)
    root = tempfile.mkdtemp(prefix="dayorder_")
    g = MdCGOS(root, actor="test")
    base = time.mktime(time.strptime("2026-04-12 10:00:00", "%Y-%m-%d %H:%M:%S"))
    N = 31
    days = []
    for i in range(N):
        ts = base + i * 86400
        body = "江北回声 陪爸开药 交换架" if i == N - 3 else "日常 闲聊 记录"
        for j in range(3):
            g.add("d%02d_%d" % (i, j), CCG.format(n="x", s="w", e=str(j), body=body),
                  created_at=ts, session="s%02d" % i)
        days.append(time.strftime("%Y-%m-%d", time.localtime(ts)))
    bi.build(g, write=True, with_content=True)
    now = time.mktime(time.strptime("2026-06-10 12:00:00", "%Y-%m-%d %H:%M:%S"))
    q = "我最早陪爸开药是哪天"

    pool = bs._early_days(sorted(bi.all_days(g)))
    ok(days[-3] in pool, "D1 倒数第三天在候选池里（旧版只取末 2 天会漏）", pool[-6:])
    ok(pool[0] == days[-1], "D2 池的顺序**从最末一天开始**（不再升序排队尾）", pool[:4])
    ok(days[0] in pool, "D3 最早那天仍在池里（两端兼顾）", pool[:6])

    ordered = bs._order_by_evidence(g, pool, bs._terms(q))
    ok(ordered[0] == days[-3], "D4 含强实体的那天被证据排到第 1", ordered[:3])

    picked = bs.scope_recall(g, q, session=None, now=now, cap=8)
    buckets = [str(qq.get("bucket")) for _n, _s, qq, _p in picked]
    ok(any(b.endswith(days[-3]) for b in buckets),
       "D5 端到端：倒数第三天的锚点进了 pack", buckets[:4])

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())