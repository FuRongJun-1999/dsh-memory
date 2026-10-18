# -*- coding: utf-8 -*-
# 功能名：德/知足 非有限数闸——inf/nan 不得进入信任寄存器（编译期 + 运行期双闸，issue #435）
# 生效条件：python -X utf8 -m compiler.tests.test_issue435_finite_trust [--mutate]；被测面＝compiler/compiler.py 的 _finite_operand 与 compiler/condition_vm.py 的 is_finite_number（STORE_NAME 写闸 / DE / ZHIZU / reset 初值闸）
# 子功能：A 组＝11 个 inf/nan 形态在编译期全部 ok=False（德 与 知足 双指令）；B 组＝运行期四个注入/执行面（run(trust=inf/nan)、symbols 注入、STORE_NAME 写、DE 参数、ZHIZU 阈值）全部结构化 VMBuiltinError("type")；K 组＝非恒真对照（0.1/0.5/0/1/-0.5 逐位不变、德 0.1 后等式比较仍 halt、有限数相加不误拒）；E 组＝源码面锚点（两处判据单点在场）
# 执行：--mutate 时把 is_finite_number 回退为纯 isinstance 判据（缺陷形态），运行期红项必须转红；再把 _finite_operand 回退为裸 float()，编译期红项必须转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下两档红项集合须与预期逐项相符
# 不适用条件：不判 Rust 侧 vm.rs 的同族判据（本仓 Rust 面另行处置）；不判 pbc 序列化对 inf 的 8 字节保真（那是格式事实，不是判据缺陷）；不判符号注入信任分量「非数值丢弃」的既有 N270 语义（本守卫只追加非有限值同丢弃）
"""issue #435 守卫：float() 接受 'inf'/'nan' ⇒ 「必须是数值」闸被穿透。

修前实测：'德 inf' -> ok=True errors=[] trust=inf；'德 nan' 同。运行期 NaN 破坏
比较自反性（若 信任值 等于 信任值 恒假 ⇒ 止 永不触发）、inf 恒超阈值。
修法：编译期 _finite_operand（math.isfinite）+ 运行期 is_finite_number 单点
（reset 初值 / STORE_NAME 写闸 / DE 累积 / ZHIZU 阈值），两闸同口径。
"""
import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import compiler.compiler as C
import compiler.condition_vm as M
from compiler.compiler import compile_source
from compiler.condition_vm import ConditionVM, Opcode

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


_INF_NAN = ["inf", "INF", "Inf", "Infinity", "infinity", "nan", "NaN",
            "NAN", "-inf", "-nan", "+inf"]

print("== A 组：编译期——11 个 inf/nan 形态（德 / 知足 双指令） ==")
for instr in ("德", "知足"):
    for form in _INF_NAN:
        src = f"{instr} {form}"
        t, pair = _try(lambda s=src: compile_source(s))
        good = (t == "" and pair[1]["ok"] is False
                and any("有限" in e for e in pair[1]["errors"]))
        check(f"A {src!r} 被拒且报文点名非有限数", good,
              (t, pair[1]["errors"] if t == "" else ""))

print("== B 组：运行期——注入/写/执行四个面结构化拒 ==")
for tag, trust in [("B01", float("inf")), ("B02", float("nan")),
                   ("B03", -float("inf"))]:
    t, _e = _try(lambda v=trust: ConditionVM().run([(Opcode.ZHI, None)], trust=v))
    check(f"{tag} run(trust={trust!r}) 结构化 VMBuiltinError(type)",
          t == "VMBuiltinError" and getattr(_e, "kind", None) == "type",
          (t, getattr(_e, "kind", None)))

for tag, val in [("B04", float("inf")), ("B05", float("nan"))]:
    t, _e = _try(lambda v=val: ConditionVM().run(
        [(Opcode.ZHI, None)], symbols={"信任值": v}))
    check(f"{tag} symbols 注入 {val!r} 同拒",
          t == "VMBuiltinError" and getattr(_e, "kind", None) == "type",
          (t, getattr(_e, "kind", None)))

for tag, val in [("B06", float("inf")), ("B07", float("nan"))]:
    t, _e = _try(lambda v=val: ConditionVM().run(
        [(Opcode.PUSH_CONST, v), (Opcode.STORE_NAME, "信任值"),
         (Opcode.ZHI, None)]))
    check(f"{tag} STORE_NAME 写 {val!r} 结构化拒",
          t == "VMBuiltinError" and getattr(_e, "kind", None) == "type",
          (t, getattr(_e, "kind", None)))

for tag, val in [("B08", float("inf")), ("B09", float("nan"))]:
    t, _e = _try(lambda v=val: ConditionVM().run(
        [(Opcode.DE, v), (Opcode.ZHI, None)]))
    check(f"{tag} DE 参数 {val!r} 结构化拒（篡改 .pbc 面）",
          t == "VMBuiltinError" and getattr(_e, "kind", None) == "type",
          (t, getattr(_e, "kind", None)))

t, _e = _try(lambda: ConditionVM().run(
    [(Opcode.ZHIZU, (float("nan"), 2)), (Opcode.ZHI, None)]))
check("B10 ZHIZU 阈值 nan 结构化拒（比较恒假会静默跳过早退）",
      t == "VMBuiltinError" and getattr(_e, "kind", None) == "type",
      (t, getattr(_e, "kind", None)))

t, _e = _try(lambda: ConditionVM().run(
    [(Opcode.DE, 1e308), (Opcode.DE, 1e308), (Opcode.ZHI, None)]))
check("B11 有限+有限溢出成 inf 亦结构化拒（累积后复核）",
      t == "VMBuiltinError" and getattr(_e, "kind", None) == "type",
      (t, getattr(_e, "kind", None)))

# ---- 复核意见 1：超出 float 范围的 int 不得变成裸 OverflowError ----
print("== B' 组：大整数（复核意见 1）——判据必须是全函数 ==")
_HUGE = 10 ** 400
t, res = _try(lambda: M.is_finite_number(_HUGE))
check("B12 is_finite_number(10**400) 不抛异常且为 True（int 恒有限）",
      t == "" and res is True, (t, res))
for tag, fn in [
        ("B13 run(trust=10**400)", lambda: ConditionVM().run(
            [(Opcode.ZHI, None)], trust=_HUGE)),
        ("B14 symbols 注入 10**400", lambda: ConditionVM().run(
            [(Opcode.ZHI, None)], symbols={"信任值": _HUGE})),
        ("B15 STORE_NAME 写 10**400", lambda: ConditionVM().run(
            [(Opcode.PUSH_CONST, _HUGE), (Opcode.STORE_NAME, "信任值"),
             (Opcode.ZHI, None)])),
        ("B16 ZHIZU 阈值 10**400", lambda: ConditionVM().run(
            [(Opcode.ZHIZU, (_HUGE, 2)), (Opcode.ZHI, None)])),
]:
    t, st = _try(fn)
    # ZHIZU 那一路不改寄存器（阈值不可达，止 照常执行），其余三路把大整数
    # 落到 trust 寄存器——两种都要求「不抛裸异常且语义与修前一致」。
    want = 0.0 if tag.startswith("B16") else _HUGE
    check(f"{tag} 不抛裸异常且被接受（与修前可用性一致）",
          t == "" and st["trust"] == want, (t, st if t == "" else ""))
t, _e = _try(lambda: ConditionVM().run(
    [(Opcode.DE, _HUGE), (Opcode.ZHI, None)]))
check("B17 DE 大整数（与 float 相加会 OverflowError）转结构化 VMBuiltinError",
      t == "VMBuiltinError" and getattr(_e, "kind", None) == "type",
      (t, getattr(_e, "kind", None)))
t, _e = _try(lambda: C._finite_operand(_HUGE, 1, "德"))
check("B18 编译期 _finite_operand(10**400) 抛 SyntaxError（float() 的 OverflowError 被捕获）",
      t == "SyntaxError" and "有限数值" in str(_e), (t, str(_e)[:80]))

print("== K 组：非恒真对照（合法值不误伤） ==")
for tag, src, want in [("K01", "德 0.5", 0.5), ("K02", "德 0", 0.0),
                       ("K03", "德 1", 1.0), ("K04", "德 -0.5", -0.5),
                       ("K05", "知足 0.7", None)]:
    t, pair = _try(lambda s=src: compile_source(s))
    good = t == "" and pair[1]["ok"] is True
    if want is not None:
        good = good and pair[0] == [(Opcode.DE, want)]
    check(f"{tag} {src!r} 仍编译成功且值逐位不变", good,
          (t, pair if t == "" else ""))

_code = [(Opcode.DE, 0.1), (Opcode.LOAD_NAME, "信任值"),
         (Opcode.LOAD_NAME, "信任值"), (Opcode.CMP_EQ, None),
         (Opcode.JUMP_IF_FALSE, 7), (Opcode.ZHI, None), (Opcode.JUMP, 7)]
t, st = _try(lambda: ConditionVM().run(_code, trust=0.0))
check("K06 德 0.1 后等式自反仍成立（止 触发，halt='halt'）",
      t == "" and st["halt"] == "halt" and st["trust"] == 0.1,
      (t, st if t == "" else ""))

for tag, val in [("K07", 0.5), ("K08", 0), ("K09", -0.25)]:
    t, st = _try(lambda v=val: ConditionVM().run([(Opcode.ZHI, None)], trust=v))
    check(f"{tag} run(trust={val!r}) 合法初值不受影响",
          t == "" and st["trust"] == val, (t, st if t == "" else ""))

print("== E 组：源码面锚点（两处判据单点在场） ==")
_csrc = open(os.path.join(_REPO, "compiler", "compiler.py"),
             encoding="utf-8").read()
_vsrc = open(os.path.join(_REPO, "compiler", "condition_vm.py"),
             encoding="utf-8").read()
check("E01 编译期 math.isfinite 判据在场", "math.isfinite(num)" in _csrc, "")
check("E02 运行期 is_finite_number 单点存在",
      "def is_finite_number(" in _vsrc, "")
check("E03 STORE_NAME 写闸经 is_finite_number",
      "if not is_finite_number(_val):" in _vsrc, "")
check("E04 DE 落寄存器前复核", "if not is_finite_number(arg):" in _vsrc, "")

if not ("math.isfinite(num)" in _csrc
        and "def is_finite_number(" in _vsrc):
    print("锚点缺失：修复不在源码里（fail-closed）")
    sys.exit(2)


def _mutate_vm():
    orig = M.is_finite_number
    M.is_finite_number = lambda v: isinstance(v, (int, float))
    return lambda: setattr(M, "is_finite_number", orig)


def _mutate_compiler():
    orig = C._finite_operand

    def legacy(val, line, what):
        if val is None:
            return 0.0
        try:
            return float(val)
        except (TypeError, ValueError):
            raise SyntaxError(f"L{line} {what} 的操作数必须是数值")
    C._finite_operand = legacy
    return lambda: setattr(C, "_finite_operand", orig)


def _vm_reds():
    reds = []
    for tag, fn in [
            ("B01", lambda: ConditionVM().run([(Opcode.ZHI, None)],
                                              trust=float("inf"))),
            ("B04", lambda: ConditionVM().run(
                [(Opcode.ZHI, None)], symbols={"信任值": float("nan")})),
            ("B06", lambda: ConditionVM().run(
                [(Opcode.PUSH_CONST, float("inf")),
                 (Opcode.STORE_NAME, "信任值"), (Opcode.ZHI, None)])),
            ("B08", lambda: ConditionVM().run(
                [(Opcode.DE, float("nan")), (Opcode.ZHI, None)])),
            ("B10", lambda: ConditionVM().run(
                [(Opcode.ZHIZU, (float("nan"), 2)), (Opcode.ZHI, None)])),
    ]:
        t, _ = _try(fn)
        if t != "VMBuiltinError":
            reds.append(tag)
    return reds


def _bigint_reds():
    """复核意见 1 的判别力：把 is_finite_number 换成「isfinite 一把梭」形态。"""
    reds = []
    t, _ = _try(lambda: M.is_finite_number(10 ** 400))
    if t != "":
        reds.append("B12")
    for tag, fn in [
            ("B13", lambda: ConditionVM().run([(Opcode.ZHI, None)],
                                              trust=10 ** 400)),
            ("B14", lambda: ConditionVM().run(
                [(Opcode.ZHI, None)], symbols={"信任值": 10 ** 400})),
            ("B15", lambda: ConditionVM().run(
                [(Opcode.PUSH_CONST, 10 ** 400),
                 (Opcode.STORE_NAME, "信任值"), (Opcode.ZHI, None)])),
            ("B16", lambda: ConditionVM().run(
                [(Opcode.ZHIZU, (10 ** 400, 2)), (Opcode.ZHI, None)])),
    ]:
        t, _ = _try(fn)
        if t != "":
            reds.append(tag)
    return reds


def _compiler_reds():
    reds = []
    for tag, src in [("A 德 inf", "德 inf"), ("A 德 nan", "德 nan"),
                     ("A 知足 inf", "知足 inf")]:
        t, pair = _try(lambda s=src: compile_source(s))
        if not (t == "" and pair[1]["ok"] is False):
            reds.append(tag)
    return reds


def _mutate_vm_isfinite_only():
    """复核意见 1 的缺陷形态：isinstance 且 math.isfinite 一把梭（大整数裸抛）。"""
    orig = M.is_finite_number
    M.is_finite_number = lambda v: isinstance(v, (int, float)) and math.isfinite(v)
    return lambda: setattr(M, "is_finite_number", orig)


if "--mutate" in sys.argv:
    print("\n!! 定点变异 1：is_finite_number 回退为纯 isinstance")
    restore = _mutate_vm()
    try:
        reds1 = _vm_reds()
    finally:
        restore()
    print("  运行期转红项：", reds1)

    print("!! 定点变异 1'：is_finite_number 回退为「isinstance + math.isfinite 一把梭」"
          "（复核意见 1 的形态）")
    restore = _mutate_vm_isfinite_only()
    try:
        reds1b = _bigint_reds()
    finally:
        restore()
    print("  大整数转红项：", reds1b)

    print("!! 定点变异 2：_finite_operand 回退为裸 float()")
    restore = _mutate_compiler()
    try:
        reds2 = _compiler_reds()
    finally:
        restore()
    print("  编译期转红项：", reds2)

    ok = (set(reds1) == {"B01", "B04", "B06", "B08", "B10"}
          and set(reds1b) == {"B12", "B13", "B14", "B15", "B16"}
          and set(reds2) == {"A 德 inf", "A 德 nan", "A 知足 inf"})
    print("定点变异自证：" + ("PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)

print("\n=== #435 守卫: 失败项 %d ===" % len(FAILS))
sys.exit(0 if not FAILS else 1)
