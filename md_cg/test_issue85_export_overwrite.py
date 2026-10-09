# -*- coding: utf-8 -*-
r"""守卫 · #85 建议 3：export 默认不得覆盖已存在文件（2026-10-09 DSH 端实施）。

缺陷（GitHub #85）：_export_call 把 out 直接交给 _write_jsonl（写 out+".tmp" 再
publish 改名）⇒ 传一个**已有文件**的路径即被静默覆盖（issue 实测 ok:true、原文件被覆盖）。

本笔处置：目标已存在即拒，并给出显式逃生口 overwrite=true。
（#85 建议 1「路径白名单默认 fail-closed」与建议 2「ingest 产出过 forbidden」涉默认
策略变更与另一条通路，**另计**；见节点 mem_dsh_brain_85_fixed 的不适用条件。）

判据：
  G1 目标已存在 + 未授权 ⇒ 拒（修前覆盖）
  G2 逃生口 overwrite=true ⇒ 允许覆盖
  G3 目标不存在 ⇒ 正常导出（不误伤常规用法）
运行：python -X utf8 -m md_cg.test_issue85_export_overwrite
退出码：0 全绿 ｜ 1 断言失败
"""
from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


def main():
    from md_cg.mcp_server import _export_call
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal

    d = tempfile.mkdtemp(prefix="p85_")
    root = os.path.join(d, "mem")
    os.makedirs(root, exist_ok=True)
    p = Principal(actor="guard", clearance="secret", can_write=True, can_admin=True,
                  role="designer", auth_mode="local-cli", session="guard")
    cg = MdCGSecure(root, principal=p)
    cg.add("n1", "# 功能名：t\n# 生效条件：t\n# 子功能：t\n# 执行：t\n# 验证方式：t\n# 不适用条件：t\n")
    cg.flush()

    victim = os.path.join(d, "victim.json")
    with open(victim, "w", encoding="utf-8") as f:
        f.write("ORIGINAL-CONTENT")

    # G1 目标已存在 ⇒ 拒
    err = ""
    try:
        _export_call(cg, {"action": "graph", "out": victim})
        err = "(no-raise)"
    except PermissionError as exc:
        err = str(exc)[:80]
    except Exception as exc:
        err = "%s: %s" % (type(exc).__name__, str(exc)[:60])
    body = open(victim, encoding="utf-8").read()
    check("G1 目标已存在 + 未授权 ⇒ 拒且原文件未被改（修前会被覆盖）",
          err != "(no-raise)" and body == "ORIGINAL-CONTENT",
          "err=%s body=%r" % (err, body[:26]))

    # G2 逃生口
    ok2 = False
    try:
        r2 = _export_call(cg, {"action": "graph", "out": victim, "overwrite": True})
        ok2 = bool(r2 and (r2.get("ok") if isinstance(r2, dict) else True))
    except Exception as exc:
        ok2 = "EXC:%s" % type(exc).__name__
    check("G2 overwrite=true ⇒ 允许覆盖（显式逃生口生效）",
          ok2 is True, "ok=%r" % (ok2,))

    # G3 目标不存在 ⇒ 正常
    fresh = os.path.join(d, "fresh.json")
    ok3 = False
    try:
        r3 = _export_call(cg, {"action": "graph", "out": fresh})
        ok3 = os.path.exists(fresh)
    except Exception as exc:
        ok3 = "EXC:%s" % type(exc).__name__
    check("G3 目标不存在 ⇒ 正常导出（不误伤常规用法）", ok3 is True, "exists=%r" % (ok3,))

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
