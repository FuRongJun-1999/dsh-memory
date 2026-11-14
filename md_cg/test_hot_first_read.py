# -*- coding: utf-8 -*-
"""守卫 · 热层优先读路径（2026-11-14 使用者裁定：默认走热层，够不着才查主库）。

断言：
  R1 热层命中且够强 ⇒ `source == "hot"`，且不查主库（无需索引扫描即可返回）
  R2 热层未命中 ⇒ 回落主库（不返回 source=hot，行为与改前一致）
  R3 `hot_first=false` ⇒ 强制主库（即使热层有货）
  R4 热层缺失 ⇒ 回落主库且不抛错（派生物缺失不得拖垮读路径）
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import hottier, mcp_server  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:160])
        FAILS.append(name)


def main():
    print("=" * 70)
    print("热层优先读路径")
    print("=" * 70)

    cg = MdCGOS(tempfile.mkdtemp(prefix="hot_r_"), actor="test")
    cg.add("self_a", "灵枢自我锚点：身份=灵枢；价值观=白箱纪律，不猜测", layer="self")
    cg.add("old_one", "很久以前的旧知识：老版本号的构建约定", layer="knowledge", importance=0.2)
    cg.flush()

    # R4：热层缺失时回落主库且不抛错
    res = mcp_server.call_tool(cg, "cg", {"op": "read", "query": "灵枢", "k": 5})
    ok(isinstance(res, dict) and res.get("source") != "hot",
       "R4 热层缺失 ⇒ 回落主库（不抛错）", str(res)[:120])

    hottier.build(cg)
    r1 = mcp_server.call_tool(cg, "cg", {"op": "read", "query": "灵枢 价值观", "k": 5})
    ok(r1.get("source") == "hot" and (r1.get("items") or [{}])[0].get("id") == "self_a",
       "R1 热层命中 ⇒ 直答（不查主库）", str(r1)[:160])
    ok((r1.get("meta") or {}).get("hot_first", {}).get("used") is True,
       "R1b meta 如实标注 hot_first.used", r1.get("meta"))

    r2 = mcp_server.call_tool(cg, "cg", {"op": "read", "query": "老版本号 构建约定", "k": 5})
    ok(r2.get("source") != "hot", "R2 热层未命中 ⇒ 回落主库", str(r2)[:140])

    r3 = mcp_server.call_tool(cg, "cg", {"op": "read", "query": "灵枢 价值观", "k": 5,
                                           "hot_first": False})
    ok(r3.get("source") != "hot", "R3 hot_first=false ⇒ 强制主库", str(r3)[:140])

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())