# -*- coding: utf-8 -*-
r"""test_s1_ast_judge · S1 判据的 AST 层加固（issue #560）。

背景：`md_cg/test_sensitivity_predicate_single_point` 的 S1 是**纯文本扫描**。实测（2026-10-19）
把 `x in crypto.ENCRYPTED_LEVELS` 正则替换成语法错误的 `crypto.is_encrypted_level(if x not):` 后，
S1 仍然全绿 —— 文本判据可被「改写」绕过。

本模块补一条**不可绕过的**判据（不改原守卫，纯增量）：
  ① AST：解析 md_cg/*.py，凡 Compare 节点的操作数为 `ENCRYPTED_LEVELS`（Name 或 Attribute）即红；
  ② 不可解析即红：任何一个 md_cg/*.py 无法 ast.parse ⇒ 红（mangling 绕不过这一条）；
  ③ 双向负控：合成样本 `x in crypto.ENCRYPTED_LEVELS` 必须被 AST 抓到；合成样本
     `crypto.is_encrypted_level(if x not):` 必须被判为不可解析 —— 两面都钉，防判据自身失效。

运行：python -X utf8 -m md_cg.test_s1_ast_judge ｜ 退出码 0 全绿 / 1 断言失败
"""
import ast
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

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


def _is_encrypted_ref(node):
    """node 是否解析到 ENCRYPTED_LEVELS（Name 或 a.ENCRYPTED_LEVELS）。"""
    if isinstance(node, ast.Name):
        return node.id == "ENCRYPTED_LEVELS"
    if isinstance(node, ast.Attribute):
        return node.attr == "ENCRYPTED_LEVELS"
    return False


def ast_violations(tree):
    """返回 [(lineno, 源码片段)]：所有对 ENCRYPTED_LEVELS 的成员测试（in / not in）。"""
    exempt = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "is_encrypted_level":
            for sub in ast.walk(node):
                exempt.add(id(sub))
    out = []
    for node in ast.walk(tree):
        if id(node) in exempt:
            continue
        if isinstance(node, ast.Compare):
            if any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
                if node.comparators and _is_encrypted_ref(node.comparators[0]):
                    out.append((getattr(node, "lineno", 0), "in ENCRYPTED_LEVELS"))
    return out


print("== ① AST：md_cg/*.py 无 ENCRYPTED_LEVELS 成员测试 ==")
files = sorted(f for f in os.listdir(HERE) if f.endswith(".py") and not f.startswith("test_"))
unparsable = []
viol = []
for f in files:
    p = os.path.join(HERE, f)
    src = io.open(p, encoding="utf-8", errors="replace").read()
    try:
        tree = ast.parse(src, filename=p)
    except SyntaxError as exc:
        unparsable.append("%s: %s" % (f, exc))
        continue
    for lineno, what in ast_violations(tree):
        viol.append("%s:%d %s" % (f, lineno, what))
check("① 扫过 %d 个非测试模块" % len(files), len(files) > 100, "n=%d" % len(files))
check("① 无 ENCRYPTED_LEVELS 成员测试（豁免单点自身定义体）", not viol, "; ".join(viol[:5]))

print("== ② 不可解析即红（mangling 绕不过本判据）==")
check("② 全部非测试模块可被 ast.parse", not unparsable, "; ".join(unparsable[:3]))

print("== ③ 双向负控 ==")
good = "if x in crypto.ENCRYPTED_LEVELS:\n    pass\n"
good_tree = ast.parse(good)
check("③ 合成样本 x in crypto.ENCRYPTED_LEVELS 被 AST 抓到",
      bool(ast_violations(good_tree)), str(ast_violations(good_tree)))
good2 = "if x not in ENCRYPTED_LEVELS:\n    pass\n"
check("③ 合成样本 not in ENCRYPTED_LEVELS 亦被抓到",
      bool(ast_violations(ast.parse(good2))), "")
mangled = "crypto.is_encrypted_level(if x not):\n    pass\n"
try:
    ast.parse(mangled)
    check("③ 改写形态必须不可解析（文本判据的盲点）", False, "竟然解析成功")
except SyntaxError:
    check("③ 改写形态必须不可解析（文本判据的盲点）", True, "SyntaxError")

print()
print("=" * 64)
print("通过 %d ／ 失败 %d" % (PASS, FAIL))
if FAILS:
    print("失败项：")
    for f in FAILS:
        print("  - " + f)
print("=" * 64)
sys.exit(0 if FAIL == 0 else 1)