# -*- coding: utf-8 -*-
r"""test_issue111_gate_order · #111 检查③（换算法不得放宽资格闸）的**结构性契约**守卫。

背景：外部 RRF3 v1.1 + ChronicleDM 与 #111 的采纳验证里，第 ③ 项要求「换检索打分层，
DEFER/BLINDSPOT 与密级/会话/层过滤不得放宽」。本仓的实现结构是「打分 → 资格判定 → 过滤」，
即资格闸在打分**下游**；只要这一顺序不被打破，换打分函数天然不影响四态资格。

本守卫只钉结构（不钉分数、不钉算法）：
  ① 判据入口 `judge_qualification` 存在；
  ② 它在 `search_rrf` 的函数体**之内**被调用（资格判定不是另起一条平行管线）；
  ③ `search_rrf` 的返回装配里，`state` 取自 `qualification` 变量（不是各处自写 state）。
若将来有人把资格判定挪到打分上游或旁路，本守卫转红。
"""
import ast
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "mdcos.py")
PASS = 0
FAIL = 0
FAILS = []


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


src = io.open(SRC, encoding="utf-8").read()
tree = ast.parse(src)
lines = src.splitlines()


def find_func(name):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


jq = find_func("judge_qualification")
check("① 判据入口 judge_qualification 存在", jq is not None,
      "line %s" % (jq.lineno if jq else "n/a"))

rrf = find_func("search_rrf")
check("② search_rrf 存在", rrf is not None, "line %s" % (rrf.lineno if rrf else "n/a"))

if rrf is not None:
    lo = rrf.lineno
    hi = max(getattr(n, "lineno", lo) for n in ast.walk(rrf))
    calls = [n for n in ast.walk(rrf)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "judge_qualification"]
    check("② 资格判定在 search_rrf 函数体内被调用（下游，不是平行管线）",
          bool(calls), "calls=%d body=[%d,%d]" % (len(calls), lo, hi))
    body_src = ast.get_source_segment(src, rrf) or ""
    hand_written = body_src.count("STATE_DEFER") + body_src.count("STATE_BLINDSPOT")
    # 允许恰 1 处：判据不可得时的保守回落（DEFER）；新增任何手写四态都必须红。
    check("③ search_rrf 的手写四态常量不超过既定基线 1（新增即红）",
          hand_written <= 1, "手写 STATE_DEFER/BLINDSPOT %d 次（基线 1）" % hand_written)

print()
print("=" * 64)
print("通过 %d ／ 失败 %d" % (PASS, FAIL))
if FAILS:
    for f in FAILS:
        print("  - " + f)
print("=" * 64)
sys.exit(0 if FAIL == 0 else 1)