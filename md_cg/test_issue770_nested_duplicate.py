# -*- coding: utf-8 -*-
"""守卫 · issue #770 存量嵌套根重复的检测与清退。

背景：#769 只防**新增**嵌套根重复（入口按 realpath 拒绝互相包含），存量已双写的
`doc_*` / `code_*` 仍在库里 ⇒ 检索重复返回同一份内容。

判据（三条同时成立才进 plan）：① 同 kind；② 同 realpath 文件；③ 两 root 互相嵌套。
清退只删**内层那套**，且外层 root 已有同 realpath 节点（删完不丢内容）。

断言：
  N1 构造内层+外层双写 ⇒ check 的 nested_duplicate.found ≥ 1（只报告）
  N2 dry_run 只列清单、不删（节点仍在）
  N3 dry_run 与 apply 的清单逐字节一致（同一次遍历）
  N4 apply 只删内层那套，外层节点仍在（不丢内容）
  N5 只有外层一份时 found=0（不误判）
  N6 不同 kind（code vs doc）不算重复（后缀面不相交）
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import mcp_server, refindex  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:170])
        FAILS.append(name)


def _mk(cg, nid, kind, root, path, content="x"):
    ref = {kind: {"root": root, "path": path, "lineno": 1, "end": 2, "hash": "h"}}
    cg.add(nid, content, layer="contextual", tags=[kind.split("_")[0]], **ref)


def main():
    print("=" * 70)
    print("issue #770：存量嵌套根重复")
    print("=" * 70)

    base = tempfile.mkdtemp(prefix="i770_")
    outer = os.path.join(base, "repo")
    inner = os.path.join(base, "repo", "docs")
    os.makedirs(inner, exist_ok=True)
    f = os.path.join(inner, "a.md")
    with open(f, "w", encoding="utf-8") as fh:
        fh.write("hello\n")

    cg = MdCGOS(tempfile.mkdtemp(prefix="i770db_"), actor="test")
    # 双写：外层 repo 与内层 repo/docs 各索引同一物理文件（同 kind=doc）
    _mk(cg, "doc_outer", "doc_ref", outer, f)
    _mk(cg, "doc_inner", "doc_ref", inner, f)

    r1 = mcp_server.call_tool(cg, "cg", {"op": "ref", "action": "check"})
    nd = (r1 or {}).get("nested_duplicate") or {}
    ok((nd.get("found") or 0) >= 1, "N1 check 报出嵌套重复（只报告）", nd)
    ok(bool(cg.get("doc_inner")) and bool(cg.get("doc_outer")),
       "N1b check 不删任何节点（只读）")

    d1 = mcp_server.call_tool(cg, "cg", {"op": "ref", "action": "prune_nested",
                                            "dry_run": True})
    ok((d1 or {}).get("deleted") == 0 and (d1 or {}).get("found", 0) >= 1,
       "N2 dry_run 列出清单但不删", d1)
    ok(bool(cg.get("doc_inner")), "N2b dry_run 后内层节点仍在")

    a1 = mcp_server.call_tool(cg, "cg", {"op": "ref", "action": "prune_nested",
                                            "dry_run": False})
    plan_dry = [x.get("node_id") for x in (d1 or {}).get("plan") or []]
    plan_apply = [x.get("node_id") for x in (a1 or {}).get("plan") or []]
    ok(plan_dry == plan_apply, "N3 dry_run 与 apply 清单逐字节一致",
       (plan_dry, plan_apply))

    ok(not cg.get("doc_inner"), "N4 内层那套被删", (a1 or {}).get("deleted_ids"))
    ok(bool(cg.get("doc_outer")), "N4b 外层节点仍在（删完不丢内容）")

    # N5：只有外层一份 ⇒ 不再报
    r2 = mcp_server.call_tool(cg, "cg", {"op": "ref", "action": "check"})
    ok(((r2 or {}).get("nested_duplicate") or {}).get("found") == 0,
       "N5 只剩外层一份时 found=0（不误判）", (r2 or {}).get("nested_duplicate"))

    # N6：不同 kind 不算重复
    _mk(cg, "code_inner", "code_ref", inner, f)
    r3 = mcp_server.call_tool(cg, "cg", {"op": "ref", "action": "check"})
    nd3 = (r3 or {}).get("nested_duplicate") or {}
    ok(nd3.get("found") == 0, "N6 code vs doc 不同 kind 不判重复", nd3)

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())