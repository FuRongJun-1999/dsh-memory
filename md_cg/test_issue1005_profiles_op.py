# -*- coding: utf-8 -*-
"""守卫 · issue #1005：`cg(op=profiles)` 是重建资料卡的**工具面入口**。

判据（2026-11-25 使用者裁定「加吧」）：改完抽取规则后，使用者必须能自己让存量卡跟上，
不必找开发者跑脚本。此前 `profiles.build` 只有内部与测试在调，工具面**一个入口都没有**。

本守卫钉住三条：
  1. `cg(op=profiles, dry_run=True)` 只算不写（默认值也是 True）；
  2. `dry_run=False` 才真的落卡；
  3. 重建出的卡里能看见新抽到的字段（把 #1043 的抽取修复与这张卡接上）。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import mcp_server  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

PASSED, FAILED = [], []
BODY = "# 功能名：{n}\n# 生效条件：t\n# 子功能：s\n# 执行：{x}\n# 验证方式：t\n# 不适用条件：无\n"


def ok(cond, name, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + ("" if cond else "  " + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def main():
    T = tempfile.mkdtemp(prefix="prof_build_guard_")
    try:
        cg = MdCGOS(T, actor="t")
        cg.add("n1", BODY.format(n="对话", x="我叫秦渡，打算7月底把兼职广告文案辞了"),
               layer="contextual", tags=["对话"], importance=0.7)
        cg.flush()

        def cards():
            # H-4(a) 纪律：从 cg.index 取回的 nodes 必须**先取快照**再迭代
            # （并发写入会在迭代中改 dict ⇒ RuntimeError）。
            return [n for n in list(cg.index.get("nodes") or {})
                    if str(n).startswith("profile-")]

        dry = mcp_server.call_tool(cg, "cg", {"op": "profiles", "dry_run": True})
        ok(isinstance(dry, dict) and dry.get("dry_run") is True,
           "P1 dry_run=True 回执标 dry_run=true", str(dry)[:100])
        ok(isinstance(dry, dict) and dry.get("written") == 0,
           "P2 dry_run=True 不落卡（written=0）", str(dry)[:100])
        ok(not cards(), "P3 dry_run=True 后索引里没有 profile-* 卡", cards())

        real = mcp_server.call_tool(cg, "cg", {"op": "profiles", "dry_run": False})
        ok(isinstance(real, dict) and real.get("written", 0) >= 1,
           "P4 dry_run=False 真的落卡（written>=1）", str(real)[:120])
        got = cards()
        ok(bool(got), "P5 索引里出现 profile-* 卡", got)
        body = ""
        for c in got:
            body += ((cg.get(c) or {}).get("content") or "")
        ok("兼职广告文案" in body,
           "P6 重建出的卡里含新抽到的职业（#1043 的抽取修复可见）", body[:120])
    finally:
        shutil.rmtree(T, ignore_errors=True)

    print()
    print("profiles 重建入口守卫：%d 通过 / %d 失败" % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())