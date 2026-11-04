# -*- coding: utf-8 -*-
"""issue #677（A）：自动记忆面幂等——`mdcg_remember(dedupe=true)`。

## 病灶
写入是两级提交（节点文件 + 内存索引先落，应答在后），客户端 60s 超时衡量的是「收到应答」。
超时后重试若不自幂等，就会新增一条同内容节点（实测三条，importance 0.86）。

## 修法
`mdcg_remember` 走与 `cg(op=write)` **同一个闸**（`writepipe._gate_dedupe`：同层 + 内容指纹 ⇒ 复用既有 id），
位置在链首（未落盘、未建边、不过闸审计）。缺省关 —— 既有调用方逐位不变。

## 断言
- R1 首次写入：落盘、deduped 不存在；
- R2 同内容再写 + dedupe=true：**不新增**、复用同一 id、deduped=True；
- R3 同内容**不带** dedupe：新增一条（opt-in 语义，既有行为不变）；
- R4 跨层同内容 + dedupe：不短路（跨层是不同语义）。

运行：python -X utf8 -m md_cg.test_issue677_remember_dedupe
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from md_cg import mcp_server   # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:300])
        FAILS.append(name)


BODY = """# 功能名：幂等写入口
# 生效条件：写入超时后重试时
# 子功能：同层内容指纹短路
# 执行：mdcg_remember(dedupe=true)
# 验证方式：节点数不增、id 相同
# 不适用条件：需要另存一份时"""


def _nodes(cg):
    return len((cg.index.get("nodes") or {}))


def main():
    print("=" * 68)
    print("issue #677 A · 自动记忆面幂等（mdcg_remember dedupe）")
    print("=" * 68)
    tmp = tempfile.mkdtemp(prefix="iss677a_")
    cg = MdCGOS(os.path.join(tmp, "r"), autoflush=1)
    try:
        r1 = mcp_server.call_tool(cg, "mdcg_remember", {"content": BODY, "layer": "contextual"})
        d1 = r1 if isinstance(r1, dict) else None
        ok(d1 is not None and d1.get("ok") is True, "R1 首次写入成功", r1)
        ok(not (d1 or {}).get("deduped"), "R1b 首次不带 deduped 标记", d1)
        n1 = _nodes(cg)
        r2 = mcp_server.call_tool(cg, "mdcg_remember", {"content": BODY, "layer": "contextual", "dedupe": True})
        d2 = r2 if isinstance(r2, dict) else None
        ok(d2 is not None and d2.get("deduped") is True, "R2 同内容 + dedupe ⇒ 短路复用", r2)
        ok(_nodes(cg) == n1, "R2b 节点数不增", (_nodes(cg), n1))
        ok((d2 or {}).get("id") == (d1 or {}).get("id"), "R2c 复用同一 id",
           ((d2 or {}).get("id"), (d1 or {}).get("id")))
        r3 = mcp_server.call_tool(cg, "mdcg_remember", {"content": BODY, "layer": "contextual"})
        ok(_nodes(cg) == n1 + 1, "R3 不带 dedupe ⇒ 新增一条（opt-in）", (_nodes(cg), n1))
        r4 = mcp_server.call_tool(cg, "mdcg_remember", {"content": BODY, "layer": "knowledge", "dedupe": True})
        d4 = r4 if isinstance(r4, dict) else None
        ok(not (d4 or {}).get("deduped"), "R4 跨层同内容不短路", r4)
    finally:
        try:
            cg.close()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("issue #677 A：%d 项失败" % len(FAILS) if FAILS else "issue #677 A：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
