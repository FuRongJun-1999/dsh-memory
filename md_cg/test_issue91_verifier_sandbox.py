# -*- coding: utf-8 -*-
r"""守卫 · #91 whitebox verifier 不得在判定前产生副作用（2026-10-09 DSH 端实施）。

缺陷（GitHub #91）：三处 exec(compile(req.code, ...), ns) 的 ns 未限 __builtins__
⇒ 模块顶层代码在**判定之前**就执行。实测（issue 报告）：
    B_builtin_open()  ok=False  副作用文件已创建=True   ← 判负之前已落盘
另：STDLIB_OK 原含 os/sys/socket/threading；且**无超时**。

本笔处置：①__builtins__ 限白名单（去 open/__import__/eval/exec/compile/…）
          ②STDLIB_OK 去 os/sys/socket/threading。
未处置（见节点）：**超时**（exec 同步阻塞，需子进程方案）；缓存完整性。

判据（真跑 Verifier，临时目录观察副作用）：
  G1 open() 载荷 ⇒ 副作用文件**不得被创建**（修前会创建）
  G2 os 导入 ⇒ L1 层拒（白名单已去 os）
  G3 正常纯函数 ⇒ 仍能校验通过（不误伤）
  G4 SAFE_NS 的 builtins 白名单**不含**危险名（open/__import__/eval/exec/compile）
运行：python -X utf8 -m md_cg.test_issue91_verifier_sandbox
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
    from md_cg.whitebox_kb.wisdom import verifier as V

    d = tempfile.mkdtemp(prefix="p91_")
    victim = os.path.join(d, "SIDE_EFFECT_CREATED.txt")
    # 载荷：模块顶层就在判定前执行（#91 的 B_builtin_open 同款）
    payload = (
        "def f(x):\n"
        "    return x\n\n"
        "open(r'%s', 'w').write('pwned')\n" % victim
    )
    req = V.VerifyRequest(task="unit", code=payload)
    try:
        res = V.Verifier().verify(req)
        ok = res.ok if hasattr(res, "ok") else (res or {}).get("ok")
    except Exception as exc:
        ok = "EXC:%s" % type(exc).__name__
    check("G1 open() 载荷 ⇒ 副作用文件不得被创建（修前会创建）",
          not os.path.exists(victim),
          "ok=%r exists=%r" % (ok, os.path.exists(victim)))

    # G2 os 导入 ⇒ L1 拒
    req2 = V.VerifyRequest(task="unit", code="import os\n\ndef f(x):\n    return x\n")
    try:
        r2 = V.Verifier().verify(req2)
        ev = str(getattr(r2, "reason", "") or getattr(r2, "evidence", "") or "")
        ok2 = getattr(r2, "ok", None)
    except Exception as exc:
        ev, ok2 = "EXC:%s" % type(exc).__name__, None
    check("G2 import os ⇒ 被拒（白名单已去 os）",
          (ok2 is False) or ("非标准库" in ev) or ("os" in ev and ok2 is not True),
          "ok=%r ev=%s" % (ok2, ev[:70]))

    # G3 正常纯函数仍可校验
    # 注：必须带中文注释——「规范符合性」一层（条件论 R1）要求函数/类有中文注释，
    # 否则 ok=False。那是**既有判据**，与本笔的沙箱加固无关（首版守卫即栽在此，
    # 误把 R1 判负当成自己的改动造成的误伤）。
    req3 = V.VerifyRequest(
        task="unit",
        code="# 加一\ndef f(x):\n    \"\"\"加一。\"\"\"\n    return x + 1\n",
        cases=[(1, 2)])
    try:
        r3 = V.Verifier().verify(req3)
        check("G3 正常纯函数仍通过（不误伤）", getattr(r3, "ok", None) is True,
              "ok=%r" % (getattr(r3, "ok", None),))
    except Exception as exc:
        check("G3 正常纯函数仍通过（不误伤）", False, repr(exc)[:70])

    # G5（**绕开 L1 的直接判据**）：把载荷直接 exec 进 SAFE_NS()，验证 open 不可用。
    # 为什么需要它：G1 走 verify() 全流程，而**L1 语法层可能先拒**某些载荷 ⇒
    # 即使把 SAFE_NS 退回空 dict（变异），文件也不会被创建 ⇒ G1 判据**恒真**、
    # 变异不点名（本笔实测：变异后 G1 仍 PASS，只点了 G4b）。本条直接打在
    # 执行命名空间上，才对该加固有判别力。
    victim2 = os.path.join(d, "SIDE_EFFECT_VIA_EXEC.txt")
    payload2 = "open(r'%s', 'w').write('x')" % victim2
    ns5 = V.SAFE_NS()
    blocked = False
    try:
        exec(compile(payload2, "<g5>", "exec"), ns5)   # noqa: S102 —— 守卫自身的有意调用
    except NameError:
        blocked = True
    except Exception:
        blocked = True
    check("G5 直接 exec 进 SAFE_NS ⇒ open 不可用且无副作用",
          blocked and (not os.path.exists(victim2)),
          "blocked=%r exists=%r" % (blocked, os.path.exists(victim2)))

    # G4 SAFE_NS 白名单不含危险名
    ns = V.SAFE_NS()
    b = ns.get("__builtins__") or {}
    danger = [k for k in ("open", "__import__", "eval", "exec", "compile",
                          "globals", "locals", "vars", "input") if k in b]
    check("G4 SAFE_NS 不含危险内建", not danger, "越界=%r" % (danger,))
    check("G4b SAFE_NS 保留常用纯函数（len/range/sorted 在）",
          all(k in b for k in ("len", "range", "sorted")), "")

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
