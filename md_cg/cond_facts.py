# -*- coding: utf-8 -*-
"""条件事实提取（白箱写注释的原料；确定性、零 LLM）。

# 功能名：符号条件事实提取
# 生效条件：给定一个 Python 源文件路径时；用于「白箱写功能级生效条件」的原料生成与门禁复核
# 子功能：逐符号（函数/类，含嵌套）提取：必需/可选形参及默认值源码、体内引用的外部名、前置守卫（if/assert/raise 的首行）、返回表达式、docstring 摘要、行号区间
# 执行：from md_cg import cond_facts；cond_facts.file_facts(path) -> list[dict]
# 验证方式：md_cg/test_cond_facts.py（对样例源逐字段断言）
# 不适用条件：①只取静态可判定事实，**不解释语义**②动态分派/装饰器改写签名时不保证签名即真实契约（须标 ambiguous）③非 Python 文件不支持
"""
from __future__ import annotations

import ast
import os


# 生效条件：src_lines 与 node 能让 ast.get_source_segment(chr(10).join(src_lines), node) 成功取到片段时返回该源码段，取段为空或抛异常时返回 ""。
def _src_seg(src_lines, node):
    try:
        return ast.get_source_segment(chr(10).join(src_lines), node) or ""
    except Exception:
        return ""


# 生效条件：fn 为函数定义节点时，按其 defaults 与 kw_defaults 切分，返回 (排除 self/cls 的必需形参名列表, 含 name 与 default 源码的可选形参列表)。
def _defaults(fn, src_lines):
    """必需的形参名 + 可选形参 (名, 默认值源码)。"""
    args = list(getattr(fn.args, "posonlyargs", [])) + list(fn.args.args)
    defaults = list(fn.args.defaults)
    n_opt = len(defaults)
    head = args[:len(args) - n_opt] if n_opt else args
    tail = args[len(args) - n_opt:] if n_opt else []
    required = [a.arg for a in head if a.arg not in ("self", "cls")]
    optional = []
    for a, d in zip(tail, defaults):
        optional.append({"name": a.arg, "default": _src_seg(src_lines, d)[:40]})
    for a, d in zip(fn.args.kwonlyargs, fn.args.kw_defaults):
        if d is None:
            required.append(a.arg)
        else:
            optional.append({"name": a.arg, "default": _src_seg(src_lines, d)[:40]})
    return required, optional


# 生效条件：fn 具 body 时，扫描其前 6 条语句中的 If/Assert/Raise 并收集条件源码；If 仅在第 0 条且子树含 Return/Raise 时 early 为 True，Assert 与 Raise 的 early 为 True。
def _guards(fn):
    """前置守卫：函数体前若干语句中的 if/assert/raise（条件源码），代表显式前置契约。"""
    out = []
    body = getattr(fn, "body", []) or []
    for i, st in enumerate(body[:6]):
        if isinstance(st, ast.If):
            # 仅「首条语句 + 体内含 return/raise」才算早退式前置契约；其余是函数内部分支，不是前置条件
            early = (i == 0 and any(isinstance(x, (ast.Return, ast.Raise))
                                    for x in ast.walk(st)))
            out.append({"kind": "if", "cond": _unparse(st.test), "early": early})
        elif isinstance(st, ast.Assert):
            out.append({"kind": "assert", "cond": _unparse(st.test), "early": True})
        elif isinstance(st, ast.Raise):
            out.append({"kind": "raise", "cond": _unparse(st.exc)[:60] if st.exc else "",
                        "early": True})
    return out


# 生效条件：node 能被 ast.unparse 成功解析时返回其源码前 80 字符，抛异常时返回 ""。
def _unparse(node):
    try:
        return ast.unparse(node)[:80]
    except Exception:
    
        return ""


# 生效条件：fn 为函数定义节点时，返回其体内 value 非空的 Return 表达式源码去重后的前 3 项列表 out。
def _returns(fn):
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and node.value is not None:
            s = _unparse(node.value)
            if s and s not in out:
                out.append(s)
        if len(out) >= 3:
            break
    return out


# 生效条件：fn 为函数定义节点时，返回其体内 ast.Name 引用名剔除 fn 的形参名、Store/Del 本地名及嵌套函数/异步函数定义名后取前 12 项的名字列表。
def _externals(fn):
    """体内引用的外部名（剔除形参与本地赋值）——即状态/常量来源。"""
    params = set()
    for a in list(getattr(fn.args, "posonlyargs", [])) + list(fn.args.args) + list(fn.args.kwonlyargs):
        params.add(a.arg)
    if getattr(fn.args, "vararg", None):
        params.add(fn.args.vararg.arg)
    if getattr(fn.args, "kwarg", None):
        params.add(fn.args.kwarg.arg)
    local = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            local.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node is not fn:
            local.add(node.name)
    names = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and node.id not in params and node.id not in local:
            if node.id not in names:
                names.append(node.id)
    return names[:12]


# 生效条件：node 具非空 docstring 时返回其去空白首行的前 100 字符，无 docstring 时返回 ""。
def _doc(node):
    d = ast.get_docstring(node) or ""
    return d.strip().split(chr(10))[0][:100]


# 生效条件：path 指向的内容可按 utf-8 读取且 ast.parse 成功时，返回其中每个 FunctionDef/AsyncFunctionDef/ClassDef 节点的事实列表 out。
def file_facts(path):
    text = open(path, encoding="utf-8", errors="replace").read()
    src_lines = text.split(chr(10))
    tree = ast.parse(text)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        kind = "class" if isinstance(node, ast.ClassDef) else (
            "async_func" if isinstance(node, ast.AsyncFunctionDef) else "func")
        if kind == "class":
            required, optional, guards, returns, externals = [], [], [], [], []
        else:
            required, optional = _defaults(node, src_lines)
            guards = _guards(node)
            returns = _returns(node)
            externals = _externals(node)
        out.append({
            "name": node.name,
            "kind": kind,
            "lineno": getattr(node, "lineno", 0),
            "end": getattr(node, "end_lineno", 0),
            "decorators": [ast.unparse(d)[:40] for d in getattr(node, "decorator_list", [])],
            "required": required,
            "optional": optional,
            "externals": externals,
            "guards": guards,
            "returns": returns,
            "doc_head": _doc(node),
        })
    return out


if __name__ == "__main__":
    import json
    import sys
    for p in sys.argv[1:]:
        for f in file_facts(p):
            print(json.dumps(f, ensure_ascii=False))