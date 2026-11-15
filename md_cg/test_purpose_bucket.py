# -*- coding: utf-8 -*-
"""守卫 · 用途副键（goal-caf158e5 第②步）：纯增量，不改既有桶键与词表。"""
from __future__ import annotations

import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import bucketindex  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:160])
        FAILS.append(name)


def main():
    cg = MdCGOS(tempfile.mkdtemp(prefix="pb_"), actor="t")
    cg.add("n1", "维护用例", layer="contextual", tags=["用途:修缺陷"])
    cg.add("n2", "扮演用例", layer="contextual", tags=["用途:扮演"])
    cg.add("n3", "无用途用例", layer="contextual", tags=[])
    cg.add("n4", "项目用例", layer="contextual", tags=["项目:天元45", "用途:修缺陷"])
    cg.flush()

    out = bucketindex.build(cg, write=False)
    ok("purposes" in out, "P1 返回体含 purposes 计数", out)
    ok(out.get("purposes") == 2, "P2 两条带用途标签 ⇒ 计数 2", out.get("purposes"))
    ok("days" in out and "sessions" in out, "P3 既有键仍在（纯增量）", list(out))
    ok(out.get("unattributed", 0) >= 1, "P4 无会话归属仍记 unattributed（未归属不建会话桶）", out)
    ok(out.get("projects") == 1, "P5 项目副键计数（主归属=项目）", out.get("projects"))
    ok(out.get("purposes") == 2, "P6 项目标签同时带用途 ⇒ 两者独立计数", (out.get("purposes"), out.get("projects")))

    # P7 负例：既无项目也无用途标签时，两侧计数必须为 0（不得凭空造桶）
    cg2 = MdCGOS(tempfile.mkdtemp(prefix="pb2_"), actor="t")
    cg2.add("m1", "无任何分类标签", layer="contextual", tags=["随便"])
    cg2.flush()
    out2 = bucketindex.build(cg2, write=False)
    ok(out2.get("purposes") == 0 and out2.get("projects") == 0,
       "P7 无项目/用途标签 ⇒ 两副键计数为 0（不凭空造桶）", out2)

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
