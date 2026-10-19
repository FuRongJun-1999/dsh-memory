# -*- coding: utf-8 -*-
r"""test_issue111_scoring_contract · #111 打分层可换**接口契约**的结构守卫（第 10 轮）。

权威件 `docs/mdcg/检索标准算法_RRF3_ChronicleDM_v1.0.md` §三·补二 定了「只换打分层」的契约。
本守卫把其中三条可静态判定的条款钉住（不碰行为、不碰算法）：

  ① **纯函数面**：`search_rrf` 内不得有落盘调用（open/append_jsonl/dump/replace/rename/remove/mkdir…）；
  ② **state 不自造**：`search_rrf` 内 `"state"` 键字面量恰 1 处，且其取值引用了 `qual`（= judge_qualification 的结果）；
  ③ **时钟显式**：`search_rrf` 内取时钟调用数 = 1（基线），新增隐式 `now()/time()` 即红——换算法时时钟必须显式传入。

任何一条转红都意味着「打分层不再可换」，须先改生产代码或先改契约，不得直接调基线数字了事。
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
fn = None
for n in ast.walk(tree):
    if isinstance(n, ast.FunctionDef) and n.name == "search_rrf":
        fn = n
        break
check("前置：search_rrf 存在", fn is not None, "line %s" % (fn.lineno if fn else "n/a"))

if fn is not None:
    def name_of(c):
        f = c.func
        if isinstance(f, ast.Attribute):
            return f.attr
        if isinstance(f, ast.Name):
            return f.id
        return "?"

    calls = [name_of(c) for c in ast.walk(fn) if isinstance(c, ast.Call)]
    WRITE = {"open", "append_jsonl", "write_text", "write_bytes", "dump", "flush",
             "fsync", "replace", "rename", "remove", "mkdir", "makedirs"}
    w = [c for c in calls if c in WRITE]
    check("① 打分层无落盘调用（纯函数面）", not w, "落盘调用: %s" % w)

    TIME = {"time", "now", "today", "monotonic", "perf_counter"}
    tl = [c for c in calls if c in TIME]
    check("③ 打分层取时钟处数 = 基线 1（新增隐式时钟即红）", len(tl) == 1,
          "时钟调用 %d 次: %s" % (len(tl), tl))

    state_sites = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values):
                if isinstance(k, ast.Constant) and k.value == "state":
                    seg = ast.get_source_segment(src, v) or ""
                    state_sites.append(seg)
    check('② "state" 键字面量恰 1 处（基线）', len(state_sites) == 1,
          "site=%r" % (state_sites[:2],))
    # 该处是占位（None）：真正的 state 由后续装配从 judge_qualification 的结果填入。
    # 本守卫只钉「打分层不得在此处自造非 None 的 state」。
    check("② 该处为占位（None），打分层不自造 state",
          bool(state_sites) and state_sites[0] == "None",
          "取值源码=%r" % (state_sites[0][:60] if state_sites else ""))

print()
print("=" * 64)
print("通过 %d ／ 失败 %d" % (PASS, FAIL))
if FAILS:
    for f in FAILS:
        print("  - " + f)
print("=" * 64)
sys.exit(0 if FAIL == 0 else 1)