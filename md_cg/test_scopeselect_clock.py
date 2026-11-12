# -*- coding: utf-8 -*-
"""逻辑时钟注入守卫：`pick_scopes(..., now=)` 必须真的决定相对日期的解析。

背景（2026-11-10 测评反馈）：`scopeselect.pick_scopes` 早先内部取真实 `time.time()`，
外部复测把逻辑时间推进到题干 `now` 时，「三天前」永远按真实今天解析 ⇒ 时间类增益测不出来。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import bucketindex as bi  # noqa: E402
from md_cg import scopeselect as ss  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

CCG = ('# 功能名：{n}\n# 生效条件：c\n# 子功能：s\n# 执行：e\n'
       '# 验证方式：test\n# 不适用条件：无\n\n{body}\n')
FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:160])
        FAILS.append(name)


def main():
    print("=" * 66)
    print("逻辑时钟注入（pick_scopes now=）")
    print("=" * 66)
    root = tempfile.mkdtemp(prefix="clock_")
    g = MdCGOS(root, actor="test")
    # 两个日子各放一条：2026-04-15（逻辑今天）与 2026-04-12（逻辑三天前）
    d_today = time.mktime(time.strptime("2026-04-15 10:00:00", "%Y-%m-%d %H:%M:%S"))
    d_back = time.mktime(time.strptime("2026-04-12 10:00:00", "%Y-%m-%d %H:%M:%S"))
    g.add("n_today", CCG.format(n="今天那条", s="w", e="1", body="行程 安排 今天"),
          created_at=d_today, session="s")
    g.add("n_back", CCG.format(n="三天前那条", s="w", e="2", body="行程 安排 三天前"),
          created_at=d_back, session="s")
    bi.build(g, write=True, with_content=True)

    logical = time.mktime(time.strptime("2026-04-15 12:00:00", "%Y-%m-%d %H:%M:%S"))
    picked = ss.pick_scopes(g, "三天前说了什么行程", session=None, limit=3, now=logical)
    days = [k for kind, k, _s in picked if kind == "day"]
    ok(days and days[0] == "2026-04-12",
       "C1 now=2026-04-15 时「三天前」→ 2026-04-12", days)

    real = time.time()
    picked2 = ss.pick_scopes(g, "三天前说了什么行程", session=None, limit=3)
    days2 = [k for kind, k, _s in picked2 if kind == "day"]
    ok(days2[:1] != ["2026-04-12"],
       "C2 不传 now 时回落真实时钟（结果不同于逻辑时钟那条）", days2[:2])

    picked3 = ss.pick_scopes(g, "三天前说了什么行程", session=None, limit=3, now=logical)
    ok(picked3 == picked, "C3 同一 now 两次调用结果一致（确定性）")

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())