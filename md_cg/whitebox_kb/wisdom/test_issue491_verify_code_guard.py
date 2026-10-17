# -*- coding: utf-8 -*-
# 功能名：verify_code 的 L2 自校验执行闸（issue #491）
# 生效条件：python -X utf8 -m md_cg.whitebox_kb.wisdom.test_issue491_verify_code_guard [--mutate]；
#           被测面＝md_cg/whitebox_kb/wisdom/code_compose.py::verify_code 的 _guarded_exec 与 _reject_unsafe
# 子功能：A 组＝死循环/超长循环被时间/步数闸中断、while/import* AST 拒绝、合法模板仍通过；
#         B 组＝非 Python 分支的 py_ref 同闸；E 组＝源码钉子
# 执行：--mutate 时就地短路一条判据（撤执行闸 / 超时调极小 / 撤 AST while 拒绝），
#       指定断言须恰好转红
# 不适用条件：不覆盖 C 层阻塞（time.sleep 等，trace 不触发；另案）；
#             不做子进程隔离（本件是执行闸，不是沙箱化）
"""issue #491 守卫：verify_code 的 L2 自校验同进程裸 exec（无超时/步数闸）。

病象（修前）：code_compose.py:715/740 直接 exec py_ref/code，无 __builtins__ 限制、
无超时、无步数闸、无内存闸；一条死循环载荷会让同进程调用方永久挂住。同子系统的
verifier.py 已在 #91 收敛为子进程 + subprocess 超时，code_compose 至今未收。

修复语义：verify_code 的两处 exec 改走 _guarded_exec（sys.settrace 行级回调，
跨平台时间 + 步数闸）；Python 分支与非 Python 分支的 py_ref 都先过 _reject_unsafe
（AST 拒绝 while / import *）。C 层阻塞不在本闸覆盖面（边界如实声明）。
"""
from __future__ import annotations

import ast
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
_SELF = os.path.abspath(__file__)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_CHECKS = []
FAILS = []


def _check(name, cond, detail=""):
    if name not in _CHECKS:
        _CHECKS.append(name)
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


def _run_verify(code, unit=None, lang="python", timeout=5.5):
    """在独立子进程跑 verify_code：修复前死循环会挂住，超时即判红（不拖死守卫）。"""
    unit = unit or {"cases": [], "py_ref": ""}
    script = (
        "import json, sys" + chr(10)
        + "sys.path.insert(0, %r)" % _REPO + chr(10)
        + "from md_cg.whitebox_kb.wisdom import code_compose as cc" + chr(10)
        + "code = %r" % code + chr(10)
        + "unit = json.loads(%r)" % json.dumps(unit, ensure_ascii=False) + chr(10)
        + "ok, checks = cc.verify_code(code, unit, %r)" % lang + chr(10)
        + "print(json.dumps({'ok': ok, 'checks': checks}, ensure_ascii=False))" + chr(10)
    )
    try:
        r = subprocess.run([sys.executable, "-X", "utf8", "-c", script],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, cwd=_REPO)
    except subprocess.TimeoutExpired:
        return "TIMEOUT", None
    try:
        out = json.loads((r.stdout or "").strip().split(chr(10))[-1])
    except Exception:
        out = None
    return r.returncode, out


_SPIN = "for i in iter(int, 1):" + chr(10) + "    pass" + chr(10)
_LONG = "for i in range(10 ** 9):" + chr(10) + "    pass" + chr(10)
_WHILE = "while True:" + chr(10) + "    pass" + chr(10)
_STAR = "from math import *" + chr(10) + chr(10) + "def solve(x):" + chr(10) + "    return x" + chr(10)
_GOOD = "def solve(arr):" + chr(10) + "    return sorted(arr)" + chr(10)


def _assertions():
    print("== A 组：执行闸与 AST 拒绝 ==")
    rc, out = _run_verify(_SPIN)
    _check("A01 ★行：无限迭代（无 while）被时间/步数闸中断（子进程未超时）",
           rc != "TIMEOUT" and out is not None and out.get("ok") is False,
           (rc, out))
    rc2, out2 = _run_verify(_LONG)
    _check("A02 ★行：10**9 次长循环被步数闸中断",
           rc2 != "TIMEOUT" and out2 is not None and out2.get("ok") is False,
           (rc2, out2))
    rc3, out3 = _run_verify(_GOOD, {"cases": [], "py_ref": ""})
    _check("A03 对照：合法模板仍通过（ok=True）",
           rc3 == 0 and out3 is not None and out3.get("ok") is True, (rc3, out3))
    rc4, out4 = _run_verify(_WHILE)
    msg4 = " ".join(str(x) for x in (out4 or {}).get("checks") or [])
    _check("A04 ★行：while 被 AST 前置拒绝（点名 while / issue #491）",
           rc4 != "TIMEOUT" and out4 is not None and out4.get("ok") is False
           and "while" in msg4 and "491" in msg4, (rc4, out4))
    rc5, out5 = _run_verify(_STAR)
    msg5 = " ".join(str(x) for x in (out5 or {}).get("checks") or [])
    _check("A05 对照：import * 被 AST 前置拒绝",
           rc5 != "TIMEOUT" and out5 is not None and out5.get("ok") is False
           and "import *" in msg5, (rc5, out5))

    print("== B 组：非 Python 分支 py_ref 同闸 ==")
    rc6, out6 = _run_verify("fn solve() {}", {"cases": [], "py_ref": _SPIN},
                            lang="rust")
    _check("B01 ★行：rust 分支 py_ref 死循环被同一执行闸中断",
           rc6 != "TIMEOUT" and out6 is not None and out6.get("ok") is False,
           (rc6, out6))

    print("== E 组：源码钉子 ==")

    def _read(rel):
        try:
            with io.open(os.path.join(_REPO, rel), encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return ""

    src = _read("md_cg/whitebox_kb/wisdom/code_compose.py")
    tree = ast.parse(src)
    vf = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "verify_code"), None)
    fs = ast.unparse(vf) if vf else ""
    _check("E01 ★钉子：verify_code 两处 exec 均走 _guarded_exec",
           fs.count("_guarded_exec(") >= 2
           and "exec(" not in fs.replace("_guarded_exec(", ""), fs[:160])
    rf = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_reject_unsafe"), None)
    rfs = ast.unparse(rf) if rf else ""
    _check("E02 ★钉子：_reject_unsafe 拒绝 while 与 import *",
           "ast.While" in rfs and "ImportFrom" in rfs)


def _run_assertions():
    global FAILS
    FAILS = []
    del _CHECKS[:]
    _assertions()
    print("通过 %d / 失败 %d" % (len(_CHECKS) - len(FAILS), len(FAILS)))
    return len(FAILS)


def _subprocess_fail_names():
    import glob
    for _pat in (os.path.join(_REPO, "md_cg", "__pycache__", "mdcos.*.pyc"),
                 os.path.join(_REPO, "md_cg", "whitebox_kb", "wisdom", "__pycache__",
                              "code_compose.*.pyc")):
        for _pyc in glob.glob(_pat):
            try:
                os.remove(_pyc)
            except OSError:
                pass
    r = subprocess.run([sys.executable, "-X", "utf8", _SELF, "--assert-only"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=_REPO, timeout=120)
    names = set(re.findall(r"(?m)^\s*FAIL\s+([A-Z]\d+)", r.stdout or ""))
    return names, (r.stdout or "") + (r.stderr or "")


_ARMS = {
    "M1": (
        "md_cg/whitebox_kb/wisdom/code_compose.py",
        "    old = sys.gettrace()" + chr(10)
        + "    sys.settrace(_trace)" + chr(10)
        + "    try:" + chr(10)
        + "        exec(code, ns)" + chr(10)
        + "    finally:" + chr(10)
        + "        sys.settrace(old)" + chr(10),
        "    exec(code, ns)" + chr(10),
        {"A01", "A02", "B01"},
    ),
    "M2": (
        "md_cg/whitebox_kb/wisdom/code_compose.py",
        "VERIFY_MAX_STEPS = 200_000" + chr(10),
        "VERIFY_MAX_STEPS = 0" + chr(10),
        {"A03"},
    ),
    "M3": (
        "md_cg/whitebox_kb/wisdom/code_compose.py",
        "        if isinstance(n, ast.While):" + chr(10)
        + "            return \"✗ L1 执行闸：模板单元不得使用 while（issue #491）\"" + chr(10),
        "        if False:" + chr(10)
        + "            return \"✗ L1 执行闸：模板单元不得使用 while（issue #491）\"" + chr(10),
        {"A04", "E02"},
    ),
}


def _mutate(argv):
    want = ""
    for a in argv:
        if a == "--mutate":
            want = want or "ALL"
        elif a.startswith("--mutate="):
            want = a.split("=", 1)[1]
    if not want:
        return 0
    ids = sorted(_ARMS) if want == "ALL" else [want]
    red = 0
    for mid in ids:
        if mid not in _ARMS:
            print("[ANCHOR-MISS] %s：未登记该变异臂" % mid)
            return 2
        rel, old, new, expect = _ARMS[mid]
        target = os.path.join(_REPO, *rel.split("/"))
        with open(target, "rb") as fh:
            orig = fh.read()
        try:
            text = orig.decode("utf-8")
            nl = chr(13) + chr(10) if (chr(13) + chr(10)) in text else chr(10)
            norm = text.replace(chr(13) + chr(10), chr(10))
            _cnt = norm.count(old)
            if _cnt != 1:
                print("[ANCHOR-MISS] %s：锚点命中 %d 次（期望 1）" % (mid, _cnt))
                return 2
            with open(target, "wb") as fh:
                fh.write(norm.replace(old, new).replace(chr(10), nl).encode("utf-8"))
            actual, out = _subprocess_fail_names()
            if actual == expect:
                print("[MUTATE-OK]   %s：指定断言转红 %s" % (mid, sorted(actual)))
            else:
                print("[MUTATE-FAIL] %s：期望红 %s，实际红 %s"
                      % (mid, sorted(expect), sorted(actual)))
                for line in out.splitlines():
                    if line.strip().startswith("FAIL"):
                        print("    " + line)
                red += 1
        finally:
            with open(target, "wb") as fh:
                fh.write(orig)
    print("反证结果：%d 条变异，%s" % (len(ids), "全部恰好命中" if red == 0 else "%d 条未命中" % red))
    return 1 if red else 0


if __name__ == "__main__":
    _f = _run_assertions()
    if "--assert-only" in sys.argv:
        sys.exit(1 if _f else 0)
    _m = _mutate(sys.argv[1:])
    sys.exit(1 if (_f or _m) else 0)
