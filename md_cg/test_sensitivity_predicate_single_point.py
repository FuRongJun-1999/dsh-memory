# -*- coding: utf-8 -*-
"""安全重构 P1 守卫：「是不是加密档」只留一个谓词（crypto.is_encrypted_level）。

病象（14 件派生写降密级 issue 的共同底座之一）：判断散在约 10 个模块，归一化
不一致——postings / writelimit / evidence / forgetting 做了 strip().lower()，
mdcg / mdcos / subgraph / sustain / logref 直接 `in ENCRYPTED_LEVELS`。同一个
" Private" 在一条路径上按加密档保护、在另一条路径上按明文放行。

修法：crypto 新增 normalize_sensitivity / is_encrypted_level 两个函数，各模块一律
调用之；`in ENCRYPTED_LEVELS` 只允许出现在 crypto.py 内部。

守卫三组：
  S 结构：md_cg/*.py（除 crypto.py 与测试）的 AST 中不得出现
          `<x> in/not in <…ENCRYPTED_LEVELS…>` 比较（含模块级别名）。
  P 谓词：缺省口径归一后判；strict=True 不归一（放行判据用）；非 str 恒 False。
  C 调用点：各模块的判据面对写法变体（" Private"）一致按加密档处理。

用法：python -X utf8 -m md_cg.test_sensitivity_predicate_single_point [--mutate]
"""
from __future__ import annotations

import ast
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_RESULTS = []


# 生效条件：记录一条断言结果并打印 PASS/FAIL 行。
def check(name, ok, detail=""):
    _RESULTS.append((bool(ok), name, detail))
    print(("PASS " if ok else "FAIL ") + name + (("  ——" + detail) if (detail and not ok) else ""))


# 生效条件：src 为 Python 源码文本时，返回其中「in/not in 右侧引用了名为 *ENCRYPTED_LEVELS* 的
# 名字或属性」的比较所在行号列表；也把「模块级把 ENCRYPTED_LEVELS 赋给别名后再 in 比较」计入。
def offending_lines(src: str) -> list:
    tree = ast.parse(src)
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _refs_levels(node.value, set()):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    aliases.add(t.id)
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for op, comp in zip(node.ops, node.comparators):
                if isinstance(op, (ast.In, ast.NotIn)) and _refs_levels(comp, aliases):
                    bad.append(node.lineno)
    return bad


# 生效条件：expr 子树中出现名为/属性名为 ENCRYPTED_LEVELS（或 aliases 中的名字）时返回 True。
def _refs_levels(expr, aliases) -> bool:
    for n in ast.walk(expr):
        if isinstance(n, ast.Name) and (n.id.endswith("ENCRYPTED_LEVELS") or n.id in aliases):
            return True
        if isinstance(n, ast.Attribute) and n.attr.endswith("ENCRYPTED_LEVELS"):
            return True
    return False


def s_group():
    print("== S 结构：模块内不得直接 `in ENCRYPTED_LEVELS`")
    hits = {}
    for name in sorted(os.listdir(_HERE)):
        if not name.endswith(".py") or name.startswith("test_") or name == "crypto.py":
            continue
        with open(os.path.join(_HERE, name), encoding="utf-8") as f:
            src = f.read()
        try:
            lines = offending_lines(src)
        except SyntaxError:
            continue
        if lines:
            hits[name] = lines
    check("S1 md_cg 模块无直接 in ENCRYPTED_LEVELS", not hits, repr(hits))
    # 扫描器自身可鉴别（否则 S1 恒绿）
    check("S2 扫描器能抓 `x in crypto.ENCRYPTED_LEVELS`",
          offending_lines("if s in crypto.ENCRYPTED_LEVELS:\n    pass\n") == [1])
    check("S3 扫描器能抓模块级别名",
          offending_lines("_E = set(crypto.ENCRYPTED_LEVELS)\nok = s in _E\n") == [2])
    check("S4 扫描器不误报自描述引用",
          offending_lines("d = {'encrypted_levels': list(crypto.ENCRYPTED_LEVELS)}\n") == [])


def p_group():
    print("== P 谓词")
    from md_cg import crypto
    iel, norm = crypto.is_encrypted_level, crypto.normalize_sensitivity
    check("P1 规范写法", iel("private") and iel("secret")
          and not iel("internal") and not iel("restricted") and not iel("public"))
    check("P2 写法变体按加密档（保护方向偏严）",
          iel(" Private") and iel("SECRET\n") and iel("\tprivate "))
    check("P3 非 str / 空串恒 False", not iel(None) and not iel(123) and not iel("")
          and not iel("   "))
    check("P4 strict 不归一（放行方向偏严）",
          iel("private", strict=True) and not iel(" Private", strict=True)
          and not iel(None, strict=True))
    check("P5 normalize 口径", norm(" Private ") == "private" and norm("") is None
          and norm(None) is None and norm(3) is None)


def c_group():
    print("== C 调用点一致性（写法变体 \" Private\"）")
    from md_cg import writelimit, postings, logref, sustain
    v = " Private"
    check("C1 writelimit._is_encrypted_level", writelimit._is_encrypted_level(v))
    check("C2 postings._sealed_node_ids",
          postings._sealed_node_ids({"a": {"sensitivity": v}, "b": {"sensitivity": "internal"}}) == ["a"])
    check("C3 logref._is_enc", logref._is_enc(v) and not logref._is_enc("internal"))

    class _CG:  # sustain 计数面：未解锁实例
        index = {"nodes": {"a": {"sensitivity": v}, "b": {"sensitivity": "secret"},
                           "c": {"sensitivity": "internal"}}}

        def crypto_status(self):
            return {"unlocked": False}
    fn = getattr(sustain, "_locked_nodes", None)
    check("C4 sustain 加密档计数面走谓词", fn is not None and fn(_CG()) == 2,
          "fn=%r" % (fn,))
    # mdcg 落盘闸：变体密级 + 明文正文 + 具备密封能力 ⇒ 必须 fail-closed
    from md_cg import mdcg
    raised = False
    try:
        mdcg._check_sensitivity_landing("n1", v, None, "plain text", has_sealer=True)
    except ValueError:
        raised = True
    except TypeError:
        raised = None
    check("C5 mdcg._check_sensitivity_landing 对变体密级明文落盘 fail-closed", raised is True,
          "raised=%r" % (raised,))


def _mutate():
    """在进程内把谓词改回「不归一」的旧形态，P2/C 组必须转红。"""
    print("!! 定点变异自证")
    from md_cg import crypto
    orig = crypto.is_encrypted_level
    bad = []

    def m1(level, *, strict=False):           # 变异1：去掉归一化
        return isinstance(level, str) and level in crypto.ENCRYPTED_LEVELS

    def m2(level, *, strict=False):           # 变异2：strict 也归一（放行方向放宽）
        return crypto.normalize_sensitivity(level) in crypto.ENCRYPTED_LEVELS
    for desc, fn, expect in (("去归一化", m1, ("P2", "C1", "C2", "C3", "C4", "C5")),
                             ("strict 失效", m2, ("P4",))):
        _RESULTS.clear()
        crypto.is_encrypted_level = fn
        try:
            p_group()
            c_group()
        finally:
            crypto.is_encrypted_level = orig
        reds = [n for ok, n, _ in _RESULTS if not ok]
        hit = [e for e in expect if any(r.startswith(e) for r in reds)]
        ok = len(hit) == len(expect)
        print(("  OK   " if ok else "  MISMATCH ") + "%s 指定命中 %d/%d" % (desc, len(hit), len(expect)))
        if not ok:
            bad.append(desc)
    print("定点变异自证：%s" % ("PASS" if not bad else "FAIL"))
    return 0 if not bad else 1


def main():
    if "--mutate" in sys.argv:
        return _mutate()
    s_group()
    p_group()
    c_group()
    bad = [n for ok, n, _ in _RESULTS if not ok]
    print("\nP1 谓词单点：%d 通过 / %d 失败" % (len(_RESULTS) - len(bad), len(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
