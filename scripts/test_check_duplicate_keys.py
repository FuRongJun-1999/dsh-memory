#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""重复键守卫的判别力自证（issue #118 / #119）。

三件事：
  [1] **合成语料**断言判别力——DIFF_VALUE 必红、SAME_VALUE 不红、非字面量不误伤、
      多行/嵌套/单引号/\`**\` 展开/数字与元组键各形态都按判据分类；
  [2] **定点变异**（--mutate）——在 \`classify_kind\` / \`const_of\` / \`scan_source\`
      三个不同落点注入，逐条给「变异前 → 变异后」读数（变异必须让预期用例转红）；
  [3] **真实仓复扫**——本仓 DIFF_VALUE 必须为 0（把 #118/#119 的修复钉成回归）。

判据来源：issue #118（安全口径靠书写次序）／#119（映射静默丢失）
＋ 真源 \`scripts/check_duplicate_keys.py\` 的三分类（DIFF/SAME/UNEVAL）。

运行：python -X utf8 scripts/test_check_duplicate_keys.py
      python -X utf8 scripts/test_check_duplicate_keys.py --mutate [--skip-repo]
退出码：0 全绿 / 1 有失败
"""
from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import check_duplicate_keys as C                          # noqa: E402

PASS = FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  · " + str(detail)) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s  · %s" % (name, detail))
    return bool(cond)


#: 合成语料：(名, 源码, 期望分类计数)
SYN = (
    ("D1 DIFF：同键两次取值不同", 'D = {"k": "a", "k": "b"}', {"DIFF_VALUE": 1}),
    ("D2 SAME：同键两次取值相同", 'D = {"k": 1, "k": 1}', {"SAME_VALUE": 1}),
    ("D3 非字面量取值：不误判为 DIFF", "D = {'k': A, 'k': A}", {"UNEVALUABLE": 1}),
    ("D4 键非字面量：不判（不猜测）", 'D = {K1: "a", "k": "b"}', {}),
    ("D5 ** 展开：键不可知，不判", 'D = {**base}\nD2 = {"k": 1}', {}),
    ("D6 多行+单引号+嵌套：外层内层各一处 DIFF",
     "D = {\n    'k': {'n': 1, 'n': 2},\n    'k': {'n': 1},\n}",
     {"DIFF_VALUE": 2}),
    ("D7 同键四次：SAME 一处（不因次数变红）",
     'D = {"k": "x", "k": "x", "k": "x", "k": "x"}', {"SAME_VALUE": 1}),
    ("D8 字面量与非字面量混：MIXED",
     'D = {"k": "a", "k": VAR}', {"MIXED": 1}),
    ("D9 无重复：零条目", 'D = {"a": 1, "b": 2}', {}),
    ("D10 不同 dict 各写一次同键：**不是**同表重复，零条目",
     'D1 = {"k": 1}\nD2 = {"k": 2}', {}),
    ("D11 键为数字/元组字面量：照判",
     'D = {1: "a", 1: "b", (2, 3): "x", (2, 3): "y"}',
     {"DIFF_VALUE": 2}),
)

#: 期望「非空」的用例数（M4 致盲变异时，这些必须**全部**转红；期望空集的用例
#: 在致盲下仍为空、本就该绿——故不能用「全部用例」做期望）。
_NONEMPTY = sum(1 for _n, _s, w in SYN if w)


def _counts(src):
    rows = C.scan_source(src, "<syn>")
    got = {"DIFF_VALUE": 0, "SAME_VALUE": 0, "UNEVALUABLE": 0, "MIXED": 0}
    for r in rows:
        got[r["kind"]] = got.get(r["kind"], 0) + 1
    return {k: v for k, v in got.items() if v}, rows


# 生效条件：无入参；返回 {用例名: (期望, 实得, 是否通过)}——**不打印、不碰全局计数**（供定点变异静默评测）。
def eval_synthetic() -> dict:
    """静默评测合成语料（变异自证专用：变异引起的红不得污染套件计数）。"""
    out = {}
    for name, src, want in SYN:
        got = _counts(src)[0]
        out[name] = (want, got, got == want)
    return out


# 生效条件：label 为前缀；逐条断言并计入全局计数，返回失败用例名列表。
def run_synthetic(label="") -> list:
    bad = []
    for name, (want, got, ok) in eval_synthetic().items():
        if not check(label + name, ok, "期望=%s 实得=%s" % (want, got)):
            bad.append(name)
    return bad


# 生效条件：无入参；扫本仓全部 .py，断言 DIFF_VALUE 归零且无解析失败，返回失败名列表。
def run_repo() -> list:
    bad = []
    n, rows = C.scan_repo(_REPO)
    diffs = [r for r in rows if r["kind"] == "DIFF_VALUE"]
    if not check("R1 真实仓 DIFF_VALUE 归零（#118/#119 修复的回归钉）",
                 not diffs, "扫描 %d 个 .py，DIFF=%d %s"
                 % (n, len(diffs), [C._fmt(r) for r in diffs[:3]])):
        bad.append("R1")
    errs = [r for r in rows if r["kind"] == "PARSE_ERROR"]
    if not check("R2 全仓 .py 均可解析（无 PARSE_ERROR）", not errs,
                 [r["file"] for r in errs[:3]]):
        bad.append("R2")
    return bad


def _with_patch(target, value, fn):
    old = getattr(C, target)
    setattr(C, target, value)
    try:
        return fn()
    finally:
        setattr(C, target, old)


# 生效条件：无入参；在三个落点各注入一次定点变异，断言**预期用例转红**，逐条打印「变异前 → 变异后」；返回失败条数。
def run_mutations() -> int:
    print("\n=== 定点变异自证（变异前 → 变异后）===")
    base = eval_synthetic()
    base_red = [n for n, (_w, _g, ok) in base.items() if not ok]
    print("  [基线] 变异前转红项 = %s（应为空）" % (base_red or "无"))
    bad = 0
    cases = (
        ("M1 classify_kind 恒 SAME_VALUE（DIFF 漏报）",
         "classify_kind", lambda values: C.SAME, "D1 DIFF：同键两次取值不同"),
        ("M2 classify_kind 恒 DIFF_VALUE（SAME 误报）",
         "classify_kind", lambda values: C.DIFF, "D2 SAME：同键两次取值相同"),
        ("M3 const_of 丢掉取值差异（DIFF 退化为 SAME）",
         "const_of", lambda node: (True, "<flattened>"), "D1 DIFF：同键两次取值不同"),
    )
    for label, target, value, must_red in cases:
        got = _with_patch(target, value, eval_synthetic)
        red = [n for n, (_w, _g, ok) in got.items() if not ok]
        hit = must_red in red
        if not check(label, hit, "变异后未命中预期红项 %r" % must_red):
            bad += 1
        print("        变异前：转红项=[] ｜ 变异后：转红项=%d 项 %s ｜ 期望含 %r ⇒ %s"
              % (len(red), red[:3], must_red, "命中" if hit else "未命中"))

    _orig_scan = C.scan_source

    def _blind(src, rel):
        """M4 的致盲实现：只扫顶层子节点、不递归 ⇒ 嵌套 dict 全漏。"""
        import ast as _ast
        try:
            tree = _ast.parse(src)
        except SyntaxError:
            return []
        out = []
        for node in list(_ast.iter_child_nodes(tree)):
            if isinstance(node, _ast.Dict):
                out.extend(_orig_scan(_ast.unparse(node), rel))
        return out

    got4 = _with_patch("scan_source", _blind, eval_synthetic)
    red4 = [n for n, (_w, _g, ok) in got4.items() if not ok]
    hit4 = len(red4) >= _NONEMPTY
    if not check("M4 扫描面致盲（ast.walk → 只回顶层子节点）", hit4,
                 "期望至少 %d 项转红，实得 %d" % (_NONEMPTY, len(red4))):
        bad += 1
    print("        变异前：转红项=[] ｜ 变异后：转红项=%d/%d（期望空集的 %d 项本就该绿）⇒ %s"
          % (len(red4), len(SYN), len(SYN) - _NONEMPTY, "命中" if hit4 else "未命中"))
    print("  变异自证结论：%s" % ("全部按预期转红" if bad == 0
                              else "存在 %d 条未按预期" % bad))
    return bad


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="重复键守卫判别力自证")
    ap.add_argument("--mutate", action="store_true", help="跑定点变异")
    ap.add_argument("--skip-repo", action="store_true", help="跳过全仓复扫（更快）")
    a = ap.parse_args()
    print("[1] 合成语料（判别力）")
    bad = run_synthetic()
    if not a.skip_repo:
        print("[2] 真实仓复扫（回归钉）")
        bad += run_repo()
    rc = 1 if bad else 0
    if a.mutate:
        rc = 1 if (run_mutations() or bad) else 0
    print("\nSUMMARY: 重复键守卫自证：%d 通过，%d 失败%s"
          % (PASS, FAIL, ("；失败项=" + "; ".join(FAILS)) if FAILS else ""))
    return rc


if __name__ == "__main__":
    sys.exit(main())
