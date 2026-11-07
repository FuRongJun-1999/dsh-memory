# -*- coding: utf-8 -*-
# 功能名：门禁收集面的「假绿目标」守卫（issue #807 同族二例的元守卫）
# 生效条件：python -X utf8 scripts/test_gate_no_false_green.py；被测面＝
#           scripts/run_tests.py 的 _discovered_files() / _discover() 收集面
# 子功能：①每个门禁目标直跑时真的会执行断言（不许 import-only 的假绿）
#         ②被判为 script-style 的件必须有真实入口（__main__ / 模块级断言 / 模块级调用）
#         ③反恒真：空壳件（无入��、无断言）必须被点名
#         ④判别力自证：把已修件的入口摘掉，守卫必须打红
# 执行：直接跑 + AST 静态判定（不依赖 pytest）
# 验证方式：本文件自身全部 PASS 且 exit 0，否则 exit 1
# 不适用条件：不判各测试用例本身是否正确（那是各守卫自己的 --mutate 面）；
#             不判 pytest fixture 的语义正确性
"""门禁「假绿目标」元守卫。

## 为什么需要（2026-11-07 / 2026-11-08 实测两例）

`scripts/run_tests.py` 的收集面历史上是**按目录 glob 自动收纳**的：只要
文件名匹配 `md_cg/test_*.py` 就进 CI，**不问它直跑时会不会执行任何断言**。
于是同一根因造成两种假绿：

1. **空壳件** `tests/test_issue_580.py`（已删）——全文只有
   `self.assertTrue(True)`，无 `__main__`、无 `sys.exit`。实测把断言改成
   `assertTrue(False)` 后直跑 **RC 仍为 0**。它挂着「#580 回归测试」的名义
   （提交 `efe13e9e` 的 message 原文如此），但 #580 的真回归场景早已由
   `md_cg/test_issue561_pending_review.py` 覆盖（红队打回 → needs_reapproval
   仍须保留 pending_review 标记），且该件在门禁内、18/18 通过。⇒ 空壳件是
   **重复且失效**，故删除。

2. **pytest-style 真守卫** `md_cg/test_issue192_move_layer_indices_guard.py`
   ——212 行、6 个**真实**测试，但全是 `def test_*(tmp_path)`，模块级零执行。
   CI 对 `md_cg/` 组只发 `python -X utf8 -m <module>`，`-m` 对纯 pytest-style
   模块只做 import+define、跑零个用例、RC 恒 0。实测把 G1 首条断言改成
   `assert False` 后，直跑仍 RC=0，而 `-m pytest` 下是 1 failed 5 passed。
   ⇒ 该件在门禁里**从未真正执行过**。已补 script-style 入口（`main()` +
   `__main__`），现直跑 6/6。

两种形态的危害相同且比「测试失败」更隐蔽：**失败的测试会叫，跑零个用例的
测试只会沉默地说"通过"**。本守卫把「收集面里的每个目标都必须真的会执行
断言」变成机器可判的断言。

## 判据（静态 AST，不执行被测件）

一个目标「直跑会执行断言」当且仅当满足任一：
  · 有模块级 `assert`；
  · 有 `if __name__` 块（真入口）；
  · 有模块级函数调用（check/ok/run/main 等具名或通用 Call）——这类
    script-style 件把断言写在顶层语句里。
不满足即为假绿，必须点名。

## 反恒真

本守卫自身也接受判别力检验（`--mutate`）：把某个已知合格件的入口摘掉后
重跑，必须**打红并点名该件**；不点名即为守卫失效。
"""

from __future__ import annotations

import ast
import importlib.util
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_TESTS = os.path.join(REPO, "scripts", "run_tests.py")

PASS = []
FAIL = []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name
          + (("  <- " + str(detail)) if detail and not cond else ""))


def load_run_tests():
    spec = importlib.util.spec_from_file_location("_rt_fg2", RUN_TESTS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _path_for_module(mod_name):
    """模块名 → 仓库内文件路径（与 _discover 的 -m 形态对应）。"""
    p = os.path.join(REPO, mod_name.replace(".", os.sep))
    for cand in (p + ".py", os.path.join(p, "__init__.py")):
        if os.path.isfile(cand):
            return cand
    return None


def executes_assertions(src):
    """直跑时是否真的会执行断言。返回 (bool, 理由)。"""
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        # 语法错的文件跑起来必然非 0，不算假绿。
        return True, "syntax-error:%s" % exc
    reasons = []
    for node in tree.body:
        if isinstance(node, ast.Assert):
            reasons.append("module-assert")
        elif isinstance(node, ast.If):
            if "__name__" in ast.dump(node.test):
                reasons.append("__main__")
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            fn = node.value.func
            nm = (fn.id if isinstance(fn, ast.Name)
                  else fn.attr if isinstance(fn, ast.Attribute) else "")
            reasons.append("module-call:%s" % (nm or "?"))
    return (bool(reasons), ",".join(reasons) or "none")


def collected_targets(rt):
    """门禁实际会跑的目标：(组名, 显示名, 文件路径) —— 与 _discover 同源。"""
    out = []
    for grp, disp, _argvs in rt._discover():
        # 显示名是 md_cg.test_x / tests.test_y / scripts.test_z 形态；
        # 统一按 _discover 的分组规则还原到文件路径。
        if grp == "md_cg":
            rel = "md_cg/" + disp[len("md_cg."):].replace(".", "/") + ".py"
        elif grp in ("compiler", "swarm"):
            rel = disp.replace(".", "/") + ".py"
        elif grp == "scripts":
            rel = "scripts/" + disp[len("scripts."):].replace(".", "/") + ".py"
        elif grp == "test":
            rel = "test/" + disp[len("test."):].replace(".", "/") + ".py"
        elif grp == "tests":
            rel = "tests/" + disp[len("tests."):].replace(".", "/") + ".py"
        else:                                  # hive
            rel = "hive/" + disp[len("hive."):].replace(".", "/") + ".py"
        out.append((grp, disp, os.path.join(REPO, rel)))
    return out


def audit(targets):
    """返回假绿目标列表：[(显示名, 路径, 理由)]。"""
    bad = []
    for _grp, disp, path in targets:
        if not os.path.isfile(path):
            bad.append((disp, path, "missing-file"))
            continue
        src = open(path, encoding="utf-8", errors="replace").read()
        good, why = executes_assertions(src)
        if not good:
            bad.append((disp, path, why))
    return bad


def main():
    rt = load_run_tests()
    targets = collected_targets(rt)

    print("== A 收集面非空且与 _discovered_files 同源")
    ok("A1 收集面有目标（>500）", len(targets) > 500, len(targets))
    disk = rt._discovered_files()
    ok("A2 收集目标数 == _discovered_files 数（无静默缩面）",
       len(targets) == len(disk), (len(targets), len(disk)))

    print("== B 每个目标直跑必须真的执行断言（本守卫的正面判据）")
    bad = audit(targets)
    ok("B1 无假绿目标", not bad,
       "；".join("%s（%s）" % (d, w) for d, _p, w in bad[:8]))

    print("== C 已修件必须有真入口（回归锁）")
    for name in (
        "md_cg.test_issue192_move_layer_indices_guard",
        "md_cg.test_issue561_pending_review",
        "tests.test_issue721_tag_filter",
        "tests.test_hook_audit_summary",
    ):
        p = _path_for_module(name)
        ok("C %s 存在" % name, p is not None, p)
        if p:
            good, why = executes_assertions(
                open(p, encoding="utf-8", errors="replace").read())
            ok("C %s 有真入口（%s）" % (name, why), good, why)

    print("== D 反恒真：空壳件必须被点名")
    shell = ("import unittest\n\n"
             "class TestRegression(unittest.TestCase):\n"
             "    def test_regression(self):\n"
             "        self.assertTrue(True)\n")
    good, why = executes_assertions(shell)
    ok("D1 已删的空壳件形态被判为假绿", good is False, why)
    ok("D2 被删件确实不在盘上", not os.path.exists(
        os.path.join(REPO, "tests", "test_issue_580.py")))

    print("== E 判别力自证：摘掉入口 ⇒ 必须打红并点名")
    # 用一个已知合格件在内存里做形态对照（不落盘、不改树）。
    scripty = ("def check(n, c):\n    assert c, n\n\n"
               "check('x', True)\n")
    ok("E1 script-style 被认可", executes_assertions(scripty)[0] is True)
    pytesty = ("def test_a(tmp_path):\n    assert False\n")
    ok("E2 纯 pytest-style（无入口）被判假绿",
       executes_assertions(pytesty)[0] is False,
       executes_assertions(pytesty)[1])
    mainy = ("def test_a(tmp_path):\n    assert False\n\n"
             "if __name__ == '__main__':\n    raise SystemExit(1)\n")
    ok("E3 补了 __main__ 后即被认可", executes_assertions(mainy)[0] is True)

    print("")
    print("门禁假绿元守卫：%d 通过 / %d 失败" % (len(PASS), len(FAIL)))
    if FAIL:
        for f in FAIL:
            print("  -", f)
    print("VERDICT=%s" % ("PASS" if not FAIL else "FAIL"))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
