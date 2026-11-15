# -*- coding: utf-8 -*-
"""守卫 · 用途标签（goal-caf158e5 第②步）：身份派生，不靠关键词，无身份不猜。"""
from __future__ import annotations

import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import mcp_server  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:160])
        FAILS.append(name)


def tags_of(cg, nid):
    n = cg.get(nid) or {}
    fm = n.get("frontmatter") or {}
    return list(fm.get("tags") or (n.get("tags") or []))


def main():
    cg = MdCGOS(tempfile.mkdtemp(prefix="tag_"), actor="test")

    r1 = mcp_server.call_tool(cg, "mdcg_remember", {
        "content": "# 功能名：用途标签用例\n# 生效条件：测试\n# 子功能：x\n# 执行：y\n# 验证方式：z\n# 不适用条件：无\n\n正文",
        "session": "s5.dsh.maintainer.D_4_ai.1791340000.3f9a2b7c1d05",
        "tags": ["测试"],
    })
    nid1 = (r1 or {}).get("node_id") or (r1 or {}).get("id")
    tg1 = tags_of(cg, nid1) if nid1 else []
    ok(any(t.startswith("用途:") for t in tg1), "T1 维护身份 ⇒ 写入带用途标签", tg1)
    ok("用途:修缺陷" in tg1, "T1b 具体用途来自身份派生", tg1)

    # 验证单元要求的关键反例：正文塞满别的用途词，标签仍须由身份决定
    _body4 = ("# 功能名：关键词反例\n# 生效条件：测试\n# 子功能：修缺陷 扮演 做验证 做审计"
              "\n# 执行：y\n# 验证方式：z\n# 不适用条件：无\n\n修缺陷 扮演 做验证 做审计 日常")
    r4 = mcp_server.call_tool(cg, "mdcg_remember", {
        "content": _body4,
        "session": "s5.dsh.designer.D_4_ai.1791340000.dddddddddddd",
        "tags": ["测试"],
    })
    nid4 = (r4 or {}).get("node_id") or (r4 or {}).get("id")
    tg4 = tags_of(cg, nid4) if nid4 else []
    ok("用途:做设计" in tg4 and not any(t in tg4 for t in ("用途:修缺陷", "用途:扮演")),
       "T4 正文塞满别的用途词 ⇒ 标签仍由身份决定（不靠关键词）", tg4)

    r2 = mcp_server.call_tool(cg, "mdcg_remember", {
        "content": "# 功能名：旧形态标识用例\n# 生效条件：测试\n# 子功能：x\n# 执行：y\n# 验证方式：z\n# 不适用条件：无\n\n正文",
        "session": "session-abc123",
        "tags": ["测试"],
    })
    nid2 = (r2 or {}).get("node_id") or (r2 or {}).get("id")
    tg2 = tags_of(cg, nid2) if nid2 else []
    ok(not any(t.startswith("用途:") for t in tg2), "T2 旧形态标识 ⇒ 不出用途标签（不猜）", tg2)

    r3 = mcp_server.call_tool(cg, "mdcg_remember", {
        "content": "# 功能名：扮演身份用例\n# 生效条件：测试\n# 子功能：x\n# 执行：y\n# 验证方式：z\n# 不适用条件：无\n\n正文",
        "session": "s5.dsh.roleplay.D_4_ai.1791340000.3f9a2b7c1d05",
        "tags": ["测试"],
    })
    nid3 = (r3 or {}).get("node_id") or (r3 or {}).get("id")
    tg3 = tags_of(cg, nid3) if nid3 else []
    ok("用途:扮演" in tg3, "T3 扮演身份 ⇒ 用途=扮演", tg3)

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
