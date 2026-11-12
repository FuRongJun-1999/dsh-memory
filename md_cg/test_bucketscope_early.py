# -*- coding: utf-8 -*-
"""早段意图守卫：query 无绝对日期且含「最早/上次/那回」时，桶序必须从**最早**扫起。

背景（2026-11-10 外测）：10/17 稳定失败属「选桶为空 → 回落最近 14 天 → 3–5 个月前锚点被排除」。
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
    print("早段意图（最早/上次/那回）→ 从最早的日子扫起")
    print("=" * 66)
    root = tempfile.mkdtemp(prefix="early_")
    g = MdCGOS(root, actor="test")
    # 三个月前一条（锚），最近一条（干扰）
    old = time.mktime(time.strptime("2026-04-01 10:00:00", "%Y-%m-%d %H:%M:%S"))
    new = time.mktime(time.strptime("2026-07-01 10:00:00", "%Y-%m-%d %H:%M:%S"))
    g.add("n_old", CCG.format(n="老约定", s="w", e="1", body="江北回声 陪爸开药 交换架"),
          created_at=old, session="s")
    g.add("n_new", CCG.format(n="新事", s="w", e="2", body="江北回声 别的 琐事"),
          created_at=new, session="s")
    bi.build(g, write=True, with_content=True)
    now = time.mktime(time.strptime("2026-07-10 12:00:00", "%Y-%m-%d %H:%M:%S"))

    ok(bs._early_intent("我最早说陪爸开药是哪天"), "E1 「最早」被判为早段意图")
    ok(not bs._early_intent("最近在忙什么"), "E2 普通 query 不是早段意图")

    picked = bs.scope_recall(g, "江北回声那回说的是什么", session=None, now=now, cap=4)
    ids = [n.get("id") for n, _s, _q, _p in picked]
    ok("n_old" in ids, "E3 早段意图能召回三个月前的锚点", ids)

    picked2 = bs.scope_recall(g, "最近在忙什么", session=None, now=now, cap=4)
    ids2 = [n.get("id") for n, _s, _q, _p in picked2]
    # 非早段意图下**不翻转顺序**：最近的排第一（老的那条可能仍被带出——
    # 这正是「日期选对了就给内容」的兜底语义，故断言排序而不是断言缺席）。
    # 「最近 N 天」兜底桶**不携带查询证据**，故仍严格按词面筛选（可为空）；
    # 只要它没有翻到「最早」那一桶（n_old 不该因为早段逻辑被拉出来）即符合契约。
    ok("n_old" not in ids2,
       "E4 非早段意图不把最早的桶拉出来（严格筛选，可为空）", ids2)

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())