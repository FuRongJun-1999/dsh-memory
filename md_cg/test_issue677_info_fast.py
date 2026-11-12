# -*- coding: utf-8 -*-
"""issue #677（B）：`cg(op=info)` 拆快/慢——诊断面不得因大库拖到 60s。

病灶：info 原先一次性跑 health_os + 理论/链接/策略/代校验；MCP stdio 串行 ⇒ 慢 info 挡住后续
请求（含写入应答），客户端 60s 超时。修法：缺省只回内存态快照；全量诊断走 full=true。
"""
from __future__ import annotations

import json
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


def _call(cg, **a):
    r = mcp_server.call_tool(cg, "cg", a)
    if isinstance(r, dict) and "content" in r:
        return json.loads(r["content"][0]["text"])
    return r


BODY = "# 功能名：t\n# 生效条件：x\n# 子功能：y\n# 执行：z\n# 验证方式：test\n# 不适用条件：无\n\nbody"


def main():
    print("=" * 68)
    print("issue #677 B · op=info 快/慢拆分")
    print("=" * 68)
    tmp = tempfile.mkdtemp(prefix="iss677b_")
    cg = MdCGOS(os.path.join(tmp, "r"), autoflush=1)
    try:
        cg.add("n1", BODY, layer="knowledge")
        cg.flush()
        _orig = cg.health_os

        def _boom(*_a, **_k):
            raise AssertionError("快照模式不得调用 health_os")

        cg.health_os = _boom
        fast = _call(cg, op="info")
        ok(isinstance(fast, dict) and fast.get("full") is False, "I1 缺省 full=false", fast)
        ok("flush_state" in fast and "node_count" in fast, "I1b 含内存态字段", list(fast)[:8])
        ok("os" not in fast, "I3 缺省不含慢面（health_os 的 os 段）", list(fast)[:12])
        ok("theory" in fast and "write_policy" in fast,
           "I3b 既有诊断键仍在（兼容）", [k for k in fast if k in ("theory", "write_policy")])
        cg.health_os = lambda *a, **k: {"health_marker": 1}
        full = _call(cg, op="info", full=True)
        ok(isinstance(full, dict) and full.get("full") is True, "I2 full=true", full)
        ok(full.get("health_marker") == 1, "I2b 慢面被调用并并入", full.get("health_marker"))
        cg.health_os = _orig
    finally:
        try:
            cg.close()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("issue #677 B：%d 项失败" % len(FAILS) if FAILS else "issue #677 B：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())