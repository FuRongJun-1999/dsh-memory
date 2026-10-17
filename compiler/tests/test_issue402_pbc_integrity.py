# -*- coding: utf-8 -*-
# 功能名：pbc.deserialize 长度判据与 v2 完整性头（issue #402）
# 生效条件：python -X utf8 -m compiler.tests.test_issue402_pbc_integrity [--mutate]；
#           被测面＝compiler/pbc.py::serialize/deserialize 的 v2 头与 _need 单点
# 子功能：A 组＝全截断点遍历（每个 cut 必须结构化报错）、尾部多余字节、旧格式兼容、
#         旧格式参数内截断、CLI 非零退出；E 组＝源码钉子
# 执行：--mutate 时就地短路一条判据（撤长度校验 / 拒旧格式 / 撤 _need），
#       指定断言须恰好转红
# 不适用条件：不做 save_pbc 原子写（issue #402 建议里的第二半，另案）；
#             不覆盖 UTF-8 非法字节的 UnicodeDecodeError 结构化（另案）
"""issue #402 守卫：deserialize 无长度判据 ⇒ 截断件静默执行成错结果。

病象（修前）：deserialize 逐条解析无边界检查：长度前缀串被截断时切片静默给出
更短串、指令表被截断时静默返回更少指令；CLI run/debug 对 cut=26 仍 rc=0 并输出
与完整件不同结果（信任 0.3→0.0、条件空间 '新信任路径'→'新'）。尾部少 1 字节则裸
IndexError 穿透。

修复语义：serialize 输出 v2 头（PBC2 + payload 长度）；deserialize 对 v2 严格校验
「实际长度 == 头部声明」（任何截断含恰好截在指令边界都抛 ValueError），payload 内
逐读点过 _need；旧格式（无头）仍兼容读并靠 _need 挡参数内截断。
"""
from __future__ import annotations

import ast
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SELF = os.path.abspath(__file__)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from compiler import pbc as _pbc  # noqa: E402

# 兼容基线：修复前无 PBC_MAGIC/PBC_HEADER；用 getattr 让守卫在基线上能逐条判红，
# 而不是 import 阶段崩栈。
PBC_MAGIC = getattr(_pbc, "PBC_MAGIC", b"PBC2")
PBC_HEADER = getattr(_pbc, "PBC_HEADER", 8)
deserialize = _pbc.deserialize
serialize = _pbc.serialize

_CHECKS = []
FAILS = []
_CODE = [("DAO", "新信任路径"), ("DE", 0.3), ("ZHIZU", (0.7, 5)),
         ("ZHI", None), ("PUSH", True), ("STORE", "甲")]


def _check(name, cond, detail=""):
    if name not in _CHECKS:
        _CHECKS.append(name)
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


def _err(msg):
    m = str(msg)
    return "截断" in m or "长度不符" in m


def _assertions():
    print("== A 组：v2 完整性与截断遍历 ==")
    data = serialize(_CODE)
    _check("A01 前提：serialize 输出 v2 头且 roundtrip 一致",
           data[:4] == PBC_MAGIC and deserialize(data) == _CODE,
           (data[:8], len(data)))
    bad = []
    for cut in range(1, len(data)):
        try:
            got = deserialize(data[:cut])
            bad.append((cut, "静默返回 %d 条" % len(got)))
        except ValueError as exc:
            if not _err(exc):
                bad.append((cut, "错误信息不含截断/长度不符: %s" % exc))
        except Exception as exc:  # noqa: BLE001
            bad.append((cut, "%s: %s" % (type(exc).__name__, exc)))
    _check("A02 ★行：全部 %d 个截断点均抛结构化 ValueError" % (len(data) - 1),
           not bad, bad[:5])
    try:
        deserialize(data + b"\x00")
        extra_ok = False
    except Exception as exc:  # noqa: BLE001
        extra_ok = isinstance(exc, ValueError) and _err(exc)
    _check("A03 ★行：尾部多余 1 字节 ⇒ 长度不符", extra_ok)
    old = data[PBC_HEADER:]
    try:
        old_ok = deserialize(old) == _CODE
    except Exception:  # noqa: BLE001
        old_ok = False
    _check("A04 对照：旧格式（无头）仍可完整读（向后兼容）", old_ok)
    try:
        deserialize(old[:-1])
        old_trunc_ok = False
    except Exception as exc:  # noqa: BLE001
        old_trunc_ok = isinstance(exc, ValueError) and _err(exc)
    _check("A05 ★行：旧格式参数内截断 ⇒ _need 结构化报错", old_trunc_ok)
    tmp = tempfile.mkdtemp(prefix="iss402_")
    try:
        p = os.path.join(tmp, "cut.pbc")
        with open(p, "wb") as fh:
            fh.write(data[:max(8, len(data) // 2)])
        r = subprocess.run([sys.executable, "-X", "utf8", "-m", "compiler.cli",
                            "run", p], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", cwd=_REPO, timeout=120)
        blob = (r.stdout or "") + (r.stderr or "")
        _check("A06 ★行：CLI run 对截断件 rc!=0 且点名 pbc 截断/长度不符",
               r.returncode != 0 and _err(blob), (r.returncode, blob[-220:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("== E 组：源码钉子 ==")

    def _read(rel):
        try:
            with io.open(os.path.join(_REPO, rel), encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return ""

    src = _read("compiler/pbc.py")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "deserialize"), None)
    fs = ast.unparse(fn) if fn else ""
    _check("E01 ★钉子：deserialize 校验 v2 长度",
           "PBC_HEADER" in fs and "len(data)" in fs, fs[:160])
    _check("E02 ★钉子：_need 单点存在", "def _need(" in src)


def _run_assertions():
    global FAILS
    FAILS = []
    del _CHECKS[:]
    _assertions()
    print("通过 %d / 失败 %d" % (len(_CHECKS) - len(FAILS), len(FAILS)))
    return len(FAILS)


def _subprocess_fail_names():
    r = subprocess.run([sys.executable, "-X", "utf8", _SELF, "--assert-only"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=_REPO, timeout=600)
    names = set(re.findall(r"(?m)^\s*FAIL\s+([A-Z]\d+)", r.stdout or ""))
    return names, (r.stdout or "") + (r.stderr or "")


_ARMS = {
    "M1": (
        "compiler/pbc.py",
        "        if len(data) != PBC_HEADER + n:" + chr(10)
        + "            raise ValueError(" + chr(10)
        + "                \"pbc 长度不符/截断：头部声明 payload %d 字节，实际 %d 字节\"" + chr(10)
        + "                \"（总长 %d）\" % (n, len(data) - PBC_HEADER, len(data)))" + chr(10),
        "        if False:" + chr(10)
        + "            raise ValueError(\"pbc 长度不符/截断\")" + chr(10),
        {"A02"},
    ),
    "M2": (
        "compiler/pbc.py",
        "    return _deserialize_payload(data)" + chr(10),
        "    raise ValueError(\"旧格式不支持\")" + chr(10),
        {"A04", "A05"},
    ),
    "M3": (
        "compiler/pbc.py",
        "    if i + n > len(data):" + chr(10)
        + "        raise ValueError(" + chr(10)
        + "            \"pbc 截断：%s 需要 %d 字节，偏移 %d 处仅剩 %d 字节\"" + chr(10)
        + "            % (what, n, i, len(data) - i))" + chr(10),
        "    if False:" + chr(10)
        + "        raise ValueError(\"pbc 截断\")" + chr(10),
        {"A02", "A05"},
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
