# -*- coding: utf-8 -*-
"""test_issue127_negated_comparison.py · issue #127 守卫（P0 静默错答）

缺陷（2026-10-12 隔离沙箱实测，非推断）
----------------------------------------
`compiler/lexer.py` 的关键字表**缺**「不小于 / 不大于 / 不等于」三词，于是
`甲 不小于 乙` 被切成 `IDENTIFIER('不')` + `XIAOYU('小于')`；parser 的
`_merge_identifiers` 把「不」并进左操作数 ⇒ 编译成 `甲不 < 乙`——**字面相反**。
六词逐个实测（改前）：

    小于→CMP_LT ✓  大于→CMP_GT ✓  等于→CMP_EQ ✓
    不小于→CMP_LT ✗  不大于→CMP_GT ✗  不等于→CMP_EQ ✗（三条全部与字面相反）

后端**无 bug**：`compiler/compiler.py` 的 `COMP_MAP` 与 `condition_vm.py` 的
`CMP_GE/CMP_LE/CMP_NE` 早已就绪——死的是**前端接线**，即 CMP_GE/CMP_LE/CMP_NE
三条 opcode 全死（`COMP_MAP` 的键从源码表面产生不出来）。

修复（三件一次收口）
--------------------
1. **止血**：`name_checker._check_expression` 的 COMPARISON 分支——左操作数
   形如「以『不』结尾」且比较符为 `<`/`>`/`==` 时，改报「否定比较词当前不支持
   （请改写为 `若 乙 小于 甲 则 …`）」，不再报误导性的「'甲不' 未声明」。
2. **治本**：`lexer` 关键字表加三词（长匹配优先；SORTED_KW 按长度降序，
   「不小于」先于「小于」命中），CJK 断开前瞻补三词（断点落在词首「不」），
   `parser._parse_comparison` 补三个 TokenType → `>=`/`<=`/`!=`。
3. **补断言**：本守卫断言 `COMP_MAP` 的每个中文键都能从源码表面产生。

覆盖
----
A 六词逐个编译 ⇒ 发射指令逐一为 CMP_LT/GT/EQ/GE/LE/NE（含无空格写法）
B 端到端语义：自包含程序 `甲=1；乙=5；丙=0；若 甲 不小于 乙，则 丙=1；`
  ⇒ VM 执行后 `丙 == 0`（1>=5 为假；**字面语义**——修复前是 `1<5` 为真⇒丙=1）
C COMP_MAP 中文键可产生性断言（每条键都能编译出对应 opcode）
D 定点变异（从词法表删掉三词 ⇒ A/B 必红）
E 止血面：残留形态（`不` 与比较词间留空格 ⇒ 词法不再合并成关键字）报
  「否定比较词当前不支持」+ 按运算符回推正确改写词，而非误导性的「'甲不' 未声明」

运行：python -X utf8 -m compiler.tests.test_issue127_negated_comparison
      python -X utf8 -m compiler.tests.test_issue127_negated_comparison --mutate
"""
from __future__ import annotations

import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from compiler import lexer as _lexer
from compiler.compiler import COMP_MAP, compile_source
from compiler.condition_vm import ConditionVM, Opcode

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [OK] " + name)
    else:
        FAIL += 1
        print("  [FAIL] " + name + ("  · " + str(detail) if detail else ""))


# 六词 → 期望 opcode（表面词形 → 后端指令，二者必须一致）
WORDS = (
    ("小于", Opcode.CMP_LT),
    ("大于", Opcode.CMP_GT),
    ("等于", Opcode.CMP_EQ),
    ("不小于", Opcode.CMP_GE),
    ("不大于", Opcode.CMP_LE),
    ("不等于", Opcode.CMP_NE),
)

# COMP_MAP 里的中文键（== / > / < 等符号键由 ASCII 面产生，不属本条）
COMP_MAP_CN = tuple(k for k in COMP_MAP if not k.isascii())


def _cmp_ops(code):
    """取字节码里的比较指令序列。"""
    return [op for op, _arg in code
            if op in (Opcode.CMP_EQ, Opcode.CMP_NE, Opcode.CMP_GT,
                      Opcode.CMP_LT, Opcode.CMP_GE, Opcode.CMP_LE)]


def _prog(word, spaced=True):
    """自包含程序：声明 甲/乙 后作比较。"""
    sep = " " if spaced else ""
    return ("甲 = 1；\n乙 = 5；\n丙 = 0；\n"
            f"若 甲{sep}{word}{sep}乙，则 丙 = 1；")


# ---------------------------------------------------------------- A 六词逐编译
def g_a():
    print("== A 六词逐个编译 ⇒ 发射指令与字面一致 ==")
    for word, want in WORDS:
        code, res = compile_source(_prog(word))
        ok = res.get("ok") is True and _cmp_ops(code) == [want]
        check(f"A 比较词「{word}」⇒ {want.name}",
              ok, f"ok={res.get('ok')} errors={res.get('errors')[:1]} "
                  f"ops={[o.name for o in _cmp_ops(code or [])]}")
    # 无空格写法（词法断点落在词首「不」）——同一判据
    for word, want in WORDS:
        code, res = compile_source(_prog(word, spaced=False))
        ok = res.get("ok") is True and _cmp_ops(code) == [want]
        check(f"A 无空格「甲{word}乙」⇒ {want.name}",
              ok, f"ok={res.get('ok')} errors={res.get('errors')[:1]} "
                  f"ops={[o.name for o in _cmp_ops(code or [])]}")


# ---------------------------------------------------------------- B 端到端语义
def g_b():
    print("== B 端到端语义：甲=1, 乙=5, 「甲 不小于 乙」⇒ 丙==0（字面） ==")
    src = "甲 = 1；\n乙 = 5；\n丙 = 0；\n若 甲 不小于 乙，则 丙 = 1；"
    code, res = compile_source(src)
    check("B1 程序编译通过", res.get("ok") is True, res.get("errors"))
    if res.get("ok"):
        state = ConditionVM().run(code)
        syms = state.get("symbols") or {}
        check("B2 ★ VM 执行后 丙 == 0（1>=5 为假；修复前是 1<5 为真⇒丙=1）",
              syms.get("丙") == 0, f"丙={syms.get('丙')!r} symbols={syms}")
    # 正对照：不小于成立时确实置 1（闸不滥杀）
    src2 = "甲 = 5；\n乙 = 1；\n丙 = 0；\n若 甲 不小于 乙，则 丙 = 1；"
    code2, res2 = compile_source(src2)
    if res2.get("ok"):
        state2 = ConditionVM().run(code2)
        check("B3 正对照：5 不小于 1 为真 ⇒ 丙 == 1",
              (state2.get("symbols") or {}).get("丙") == 1,
              (state2.get("symbols") or {}).get("丙"))
    else:
        check("B3 正对照程序可编译", False, res2.get("errors"))


# ---------------------------------------------------------------- C 键可产生性
def g_c():
    print("== C COMP_MAP 每个中文键都可从源码表面产生 ==")
    for key in COMP_MAP_CN:
        want = COMP_MAP[key]
        code, res = compile_source(_prog(key))
        ok = res.get("ok") is True and _cmp_ops(code) == [want]
        check(f"C COMP_MAP['{key}'] 可由源码产生 ⇒ {want.name}",
              ok, f"ok={res.get('ok')} errors={res.get('errors')[:1]}")
    check("C0 COMP_MAP 至少含六条中文键",
          len(COMP_MAP_CN) >= 6, COMP_MAP_CN)
    # C1 不变式：断开前瞻集合必须是关键字表的子集——否则 CJK 分支词首 break、
    # 主循环匹配不到 ⇒ 分词死循环（本轮定点变异实测踩到，故单列断言）。
    orphans = [w for w in _lexer.CJK_BREAK_WORDS if w not in _lexer.KEYWORDS]
    check("C1 CJK_BREAK_WORDS ⊆ KEYWORDS（防分词死循环）",
          not orphans, f"非关键字={orphans}")


# ---------------------------------------------------------------- E 止血面
def g_e():
    print("== E 止血面：残留形态报「否定比较词当前不支持」+ 正确改写词 ==")
    cases = (("小于", "不小于"), ("大于", "不大于"), ("等于", "不等于"))
    for op_word, want_word in cases:
        src = ("甲 = 1；\n乙 = 5；\n丙 = 0；\n"
               f"若 甲不 {op_word} 乙，则 丙 = 1；")
        _code, res = compile_source(src)
        errs = " | ".join(res.get("errors") or [])
        check(f"E 「甲不 {op_word} 乙」报否定比较词不支持（非「甲不 未声明」）",
              res.get("ok") is False
              and "否定比较词当前不支持" in errs
              and "未声明" not in errs,
              errs)
        check(f"E 「甲不 {op_word} 乙」改写词回推为「{want_word}」",
              f"甲 {want_word}" in errs, errs)


# ---------------------------------------------------------------- D 定点变异
def _mutate_lexer(drop=("不小于", "不大于", "不等于")):
    """从词法表删掉指定词（还原为缺陷形态），返回还原器。

    直接改 lexer 模块全局（KEYWORDS / KEYWORD_MAP / SORTED_KW / CJK_BREAK_WORDS）
    ——tokenize 在调用期读这些全局，故 in-process 生效且不落盘、不改源文件。
    **必须同步回退 CJK_BREAK_WORDS**：若只在词法表里删词而断开前瞻集合仍含该词，
    CJK 分支会在词首 break、主循环又匹配不到 ⇒ 分词死循环（`_segment` 的
    `ident` 为空且 i 不前进）——本守卫已把这层不变式单列为 C1 断言。
    """
    saved_kw = set(_lexer.KEYWORDS)
    saved_map = dict(_lexer.KEYWORD_MAP)
    saved_sorted = _lexer.SORTED_KW
    saved_break = _lexer.CJK_BREAK_WORDS

    def restore():
        _lexer.KEYWORDS.clear()
        _lexer.KEYWORDS.update(saved_kw)
        _lexer.KEYWORD_MAP.clear()
        _lexer.KEYWORD_MAP.update(saved_map)
        _lexer.SORTED_KW = saved_sorted
        _lexer.CJK_BREAK_WORDS = saved_break

    try:
        for w in drop:
            _lexer.KEYWORDS.discard(w)
            _lexer.KEYWORD_MAP.pop(w, None)
        _lexer.SORTED_KW = sorted(_lexer.KEYWORDS, key=len, reverse=True)
        _lexer.CJK_BREAK_WORDS = tuple(
            w for w in saved_break if w not in drop)
    except Exception:
        restore()
        raise
    return restore


def _run_all_silent():
    """跑 A/B/C 组（静默），返回失败数——供变异自证复用。"""
    global PASS, FAIL
    sp, sf = PASS, FAIL
    PASS, FAIL = 0, 0
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            g_a()
            g_b()
            g_c()
            g_e()
        return FAIL
    finally:
        PASS, FAIL = sp, sf


def _mutate_mode():
    clean = _run_all_silent()
    print(f"  未变异基线：红项={clean}"
          + ("" if clean == 0 else "  ← 基线即红，变异核验无意义"))
    restore = _mutate_lexer()
    try:
        mutated = _run_all_silent()
    finally:
        restore()
    after = _run_all_silent()
    ok = (clean == 0 and mutated > 0 and after == 0)
    print(f"  变异「词法表删掉 不小于/不大于/不等于」→ 红项={mutated}"
          f"（应 > 0）；还原后红项={after}（应 0）")
    print("\n定点变异自证：" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    if "--mutate" in sys.argv:
        print("!! 定点变异模式：抽掉三词，A/B/C 应转红\n")
        return _mutate_mode()
    g_a()
    g_b()
    g_c()
    g_e()
    print(f"\n通过 {PASS} / 失败 {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
