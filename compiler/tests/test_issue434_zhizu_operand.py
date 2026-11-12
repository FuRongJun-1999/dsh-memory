# -*- coding: utf-8 -*-
# 功能名：知足 阈值位数值闸——非数值操作数不得以裸 ValueError 穿透编译主入口（issue #434）
# 生效条件：python -X utf8 -m compiler.tests.test_issue434_zhizu_operand [--mutate]；被测面＝compiler/compiler.py 的 Compiler._instr ZHIZU 分支与数值闸单点 _finite_operand
# 子功能：A 组＝三个非数值形态（官方示例「知足 验证单元」/abc/情感权重）在 compiler.compile_source 与 pbc.compile_to_pbc 双入口均返回 ok=False 且 errors 非空（无裸 ValueError）；K 组＝非恒真对照（0.7/1/0/0.15 字节码逐位不变、完整五指令程序可编译、德 分支原有结构化错误不回归）；E 组＝源码面锚点（数值闸单点存在、ZHIZU 分支不再直接 float()）
# 执行：--mutate 时把 _finite_operand 换回缺陷形态（裸 float(val)），守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下红项集合须与预期逐项相符
# 不适用条件：不判 api.compile_source（走 codegen 面，本就不调 Compiler._instr——见 #434 正文「守卫盲区实证」）；不判 inf/nan（#435 守卫 test_issue435_finite_trust 覆盖）；不判 Rust 侧
"""issue #434 守卫：知足 的阈值位此前裸 float()，非数值操作数抛 ValueError 穿透。

修前实测：compile_source('知足 验证单元') -> ValueError: could not convert string
to float: '验证单元'（裸栈，无结构化 errors）；pbc.compile_to_pbc 同。同族 德 分支
有 try/except，知足 分支无——两条分支各自复制了一份「转数值」判据。
修法：两分支收口到 _finite_operand 单点（同时承载 #435 的有限性判据）。
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import tempfile

import compiler.compiler as C
from compiler.compiler import compile_source
from compiler.pbc import compile_to_pbc

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


def _try(fn):
    try:
        return "", fn()
    except BaseException as exc:                              # noqa: BLE001
        return type(exc).__name__, exc


print("== A 组：#434 正题——非数值阈值双入口结构化拒绝 ==")
for tag, src in [("A01", "知足 验证单元"), ("A02", "知足 abc"),
                 ("A03", "知足 情感权重")]:
    t, pair = _try(lambda s=src: compile_source(s))
    check(f"{tag} compile_source({src!r}) 不抛裸异常", t == "", t)
    ok = (t == "" and pair is not None and pair[1]["ok"] is False
          and bool(pair[1]["errors"]))
    check(f"{tag} compile_source({src!r}) ok=False 且 errors 非空",
          ok, (t, pair[1]["errors"] if t == "" else ""))

tmp = tempfile.mkdtemp(prefix="u08_434_")
for tag, src in [("A04", "知足 验证单元"), ("A05", "知足 abc")]:
    path = os.path.join(tmp, "x.pbc")
    t, pair = _try(lambda s=src, p=path: compile_to_pbc(s, p))
    check(f"{tag} compile_to_pbc({src!r}) 不抛裸异常", t == "", t)
    check(f"{tag} compile_to_pbc({src!r}) ok=False 且 .pbc 未产出",
          t == "" and pair is not None and pair[1]["ok"] is False
          and not os.path.exists(path),
          (t, pair[1]["errors"] if t == "" else ""))

print("== K 组：非恒真对照（合法值逐位不变、德 分支不回归） ==")
for tag, src, want in [("K01", "知足 0.7", 0.7), ("K02", "知足 1", 1.0),
                       ("K03", "知足 0", 0.0), ("K04", "知足 0.15", 0.15)]:
    t, pair = _try(lambda s=src: compile_source(s))
    good = (t == "" and pair[1]["ok"] is True
            and pair[0] == [(C.Opcode.ZHIZU, (want, 1))])
    check(f"{tag} {src!r} 字节码逐位不变（ZHIZU,({want},1)）", good,
          (t, pair if t == "" else ""))

_t, _pair = _try(lambda: compile_source(
    "问曰：如何验证信任？\n答曰：信任值大于0.7。\n术曰：\n1。道 新信任路径；\n"
    "2。德 0.5；\n3。知足 0.7；\n4。止。\n"))
check("K05 完整五指令程序仍编译成功且指令数=6",
      _t == "" and _pair[1]["ok"] is True and len(_pair[0]) == 6,
      (_t, len(_pair[0]) if _t == "" else ""))

_t, _pair = _try(lambda: compile_source("德 abc"))
check("K06 德 的非数值结构化错误不回归",
      _t == "" and _pair[1]["ok"] is False
      and any("必须是数值" in e for e in _pair[1]["errors"]),
      (_t, _pair[1]["errors"] if _t == "" else ""))

print("== E 组：源码面锚点（判据单点在场） ==")
_src = open(os.path.join(_REPO, "compiler", "compiler.py"),
            encoding="utf-8").read()
# v0.9.0：判据是「两分支都经 _finite_operand 单点」，不是引号风格；源码用单引号，
# 故比较前把两者归一（只归一引号，不归一任何判据内容）。
_src = _src.replace(chr(39), chr(34))
check("E01 数值闸单点 _finite_operand 存在", "def _finite_operand(" in _src, "")
check("E02 ZHIZU 分支经单点取值（不再裸 float(val)）",
      '_finite_operand(val, s.line, "知足")' in _src, "")
check("E03 DE 分支同走单点",
      '_finite_operand(val, s.line, "德")' in _src, "")

if not ("def _finite_operand(" in _src
        and '_finite_operand(val, s.line, "知足")' in _src):
    print("锚点缺失：修复不在源码里（fail-closed）")
    sys.exit(2)


def _mutate_off():
    """把数值闸换回缺陷形态：裸 float(val)（非数值即 ValueError 穿透）。"""
    orig = C._finite_operand
    C._finite_operand = lambda val, line, what: (
        0.0 if val is None else float(val))
    return lambda: setattr(C, "_finite_operand", orig)


if "--mutate" in sys.argv:
    print("\n!! 定点变异：_finite_operand 回退为裸 float(val)")
    restore = _mutate_off()
    try:
        FAILS.clear()
        _t, _pair = _try(lambda: compile_source("知足 验证单元"))
        m1 = not (_t == "" and _pair[1]["ok"] is False)
        _t2, _pair2 = _try(lambda: compile_source("知足 abc"))
        m2 = not (_t2 == "" and _pair2[1]["ok"] is False)
        _t3, _pair3 = _try(lambda: compile_source("知足 情感权重"))
        m3 = not (_t3 == "" and _pair3[1]["ok"] is False)
    finally:
        restore()
    reds = [n for n, r in [("A01", m1), ("A02", m2), ("A03", m3)] if r]
    print("  变异后转红项：", reds)
    ok = set(reds) == {"A01", "A02", "A03"}
    print("定点变异自证：" + ("PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)

print("\n=== #434 守卫: 失败项 %d ===" % len(FAILS))
sys.exit(0 if not FAILS else 1)
