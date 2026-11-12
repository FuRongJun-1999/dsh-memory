# -*- coding: utf-8 -*-
"""守卫 · issue #867 域键中间粒度（doc 摄取不再「一文件一桶」）。

病象：`_domain_of` 取整条相对路径（2026-10-21 的修复一，救「少数顶层 + 大量子树」巨桶），
但扁平文件名 + 每日新增的形态下 ⇒ 单例桶 68.8%，与 `bucket_health` 的 >50% 阈值自相矛盾。

修法：只做三件确定性收拢——剥扩展名、`<stem>_YYYY-MM-DD[_hash]` 收成 `<stem>_YYYY-MM`、
纯 UUID 名原样。断言取向：**两条既有不变量都要保住**——
  ① 真实知识树仍按子路径分桶（不得回退到「取首段」）；
  ② 每日文件不再一文件一桶。
"""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import refindex as ri  # noqa: E402
from md_cg import routing  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:170])
        FAILS.append(name)


def dom(path):
    return ri._domain_of({"path": path})


def main():
    print("=" * 70)
    print("issue #867：域键中间粒度")
    print("=" * 70)

    a = dom("diary_2026-10-09_d81bf3e9.md")
    b = dom("diary_2026-10-21_abcd1234.md")
    c = dom("diary_2026-09-28_233d8ddf.md")
    ok(a == b == "diary_2026-10", "G1 同月同日频文件归同一域（收月）", (a, b))
    ok(c == "diary_2026-09", "G2 跨月分开（不同月不同域）", c)
    ok(routing.bucket_dir(routing.normalize_domain(a)) == routing.bucket_dir(routing.normalize_domain(b)),
       "G3 同域 ⇒ 同桶（修前每文件一桶）")

    u = dom("c39b50a3-dff9-46b6-a754-cac2859a676e.md")
    ok(u == "c39b50a3-dff9-46b6-a754-cac2859a676e", "G4 纯 UUID 名原样保留（不收拢，防巨桶）", u)

    deep1 = dom("default-kb/shorinwiki/foo.md")
    deep2 = dom("default-kb/kb/bar.md")
    ok(deep1 != deep2, "G5 真实知识树仍按子路径分域（不回退「取首段」）", (deep1, deep2))
    ok(deep1 == "default-kb/shorinwiki/foo", "G6 只剥扩展名，路径结构保留", deep1)

    ok(dom("notes/weekly.txt") == "notes/weekly", "G7 其它扩展名同样剥除")
    ok(dom("") == "orphan", "G8 空路径仍是 orphan（不回归）")

    # 桶数收缩：20 个日频文件 → 1 个域（修前 20 个域）
    days = ["diary_2026-10-%02d_%08x.md" % (d, d) for d in range(1, 21)]
    keys = {routing.normalize_domain(dom(p)) for p in days}
    ok(len(keys) == 1, "G9 20 个日频文件收成 1 个域（修前 20 个）", keys)

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())