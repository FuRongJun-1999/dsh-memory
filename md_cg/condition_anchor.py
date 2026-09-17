# -*- coding: utf-8 -*-
"""条件锚点：判定一条候选「生效条件」是否锚定在该符号的真实输入/状态上（确定性，零 LLM）。

# 功能名：条件锚点机械判据
# 生效条件：给定候选生效条件文本 + 该符号源码片段（含 def/class 定义）时；用于环二候选的机械门禁与抽检
# 子功能：ast 取签名（必需/可选参数）+ 函数体内引用的名字 → 与条件文本标识符求交 → 输出 ANCHORED/WEAK/BLINDSPOT/REJECT_META 四类裁决与锚点清单
# 执行：from md_cg import condition_anchor；condition_anchor.judge(cond, src) -> dict
# 验证方式：md_cg/test_condition_anchor.py（逐分支断言）
# 不适用条件：①只判「锚点是否存在」，**不判语义正确性**（不得据此声称条件正确）②非 Python 源码或无法解析时返回 BLINDSPOT ③无参数且体内无外部引用的符号返回 BLINDSPOT（不可判，不猜测）
"""
from __future__ import annotations

import ast
import re

# 索引元条件话术（合成条件特征）：出现即拒——它们不是功能前置条件
META_MARKS = ("索引元条件", "源文件存在", "全时窗", "本地仓", "仓库存在", "文件存在")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


# 生效条件：tree 为可被 ast.walk 遍历的 AST 时，返回其中首个 FunctionDef/AsyncFunctionDef 节点，无函数而含 ClassDef 时返回该类体的 __init__ 或类自身，否则返回 None。
def _first_def(tree):
    """取片段里第一个函数定义（含 async）；只有类时退其 __init__，再退类本身。"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name == "__init__":
                    return sub
            return node
    return None


# 生效条件：fn 为含 args 的函数定义节点时按 defaults 长度切分，返回 (无默认值且排除 self/cls 的形参名, 有默认值的形参名)；fn 为 ClassDef 时返回 ([], [])。
def signature(fn):
    """返回 (required, optional)：required=无默认值的形参（跳过 self/cls），optional=有默认值者。"""
    if isinstance(fn, ast.ClassDef):
        return [], []
    args = list(getattr(fn.args, "posonlyargs", [])) + list(fn.args.args)
    defaults = list(fn.args.defaults)
    n_opt = len(defaults)
    head = args[:len(args) - n_opt] if n_opt else args
    tail = args[len(args) - n_opt:] if n_opt else []
    required = [a.arg for a in head if a.arg not in ("self", "cls")]
    optional = [a.arg for a in tail]
    for a, d in zip(fn.args.kwonlyargs, fn.args.kw_defaults):
        (optional if d is not None else required).append(a.arg)
    return required, optional


# 生效条件：fn 为函数定义节点时，返回其体内 Load 名字集合剔除 fn 的形参名、Store/Del 本地名及嵌套函数/异步函数定义名后的差集。
def referenced(fn):
    """函数体内引用的名字（剔除形参与本地赋值目标）——代表来自模块/外部的状态与常量。"""
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return set()  # 类（无 __init__）等非函数节点：无「体内引用」语义，返回空集不崩溃
    params = {a.arg for a in list(getattr(fn.args, "posonlyargs", [])) + list(fn.args.args)}
    params |= {a.arg for a in fn.args.kwonlyargs}
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
    names = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            base = node
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name):
                names.add(base.id)
    return names - params - local


# 生效条件：cond 与 src 给定后：若 str(cond) 含 META_MARKS 则返回 REJECT_META；否则解析 src，取 _first_def、signature、referenced，并按 cond 中标识符是否命中 required 或 referenced 得出 ANCHORED（ok=True）、无 required/refs 时 BLINDSPOT、否则 WEAK；prefix/suffix 仅回显不参与判定。
def judge(cond, src, prefix="", suffix=""):
    """判定单条候选条件。返回 dict：verdict/ok/anchors/required/optional/referenced/meta_marks。

    prefix/suffix：编外记录用（如「已声明」），不参与判定，仅回显以便追溯。
    """
    out = {"cond": str(cond or ""), "verdict": "", "ok": False, "anchors": [],
           "required": [], "optional": [], "referenced": [], "meta_marks": [],
           "prefix": prefix, "suffix": suffix, "reason": ""}
    text = str(cond or "")
    hits = [m for m in META_MARKS if m in text]
    if hits:
        out.update(verdict="REJECT_META", ok=False, meta_marks=hits,
                   reason="出现索引元条件话术，非功能前置条件")
        return out
    try:
        tree = ast.parse(str(src or ""))
    except SyntaxError as exc:
        out.update(verdict="BLINDSPOT", reason="源码无法解析：" + str(exc)[:60])
        return out
    fn = _first_def(tree)
    if fn is None:
        out.update(verdict="BLINDSPOT", reason="片段中无函数/类定义")
        return out
    if isinstance(fn, ast.ClassDef):
        _init = None
        for _sub in fn.body:
            if isinstance(_sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and _sub.name == "__init__":
                _init = _sub
                break
        fn = _init if _init is not None else fn
    required, optional = signature(fn)
    refs = referenced(fn)
    mentions = set(IDENT.findall(text))
    strong = sorted(mentions & set(required))
    weak = sorted(mentions & refs)
    anchors = sorted(set(strong) | set(weak))
    out.update(required=required, optional=optional, referenced=sorted(refs), anchors=anchors)
    if strong or weak:
        out.update(verdict="ANCHORED", ok=True,
                   reason="锚定必需参数" if strong else "锚定体内引用（状态/常量）")
        return out
    if not required and not refs:
        out.update(verdict="BLINDSPOT", reason="该符号无参数且无外部引用，条件无从锚定")
        return out
    out.update(verdict="WEAK", reason="条件未锚定任何必需参数或体内引用")
    return out


# 生效条件：pairs 为可逐项解包出 (id, cond, src) 的序列时，对每条调用 judge 并回填 id，返回 {'rows': rows, 'stats': 各 verdict 计数, 'ok': rows 中 ok 为真者个数}。
def judge_batch(pairs):
    """批量入口：pairs=[(id, cond, src), ...] → 汇总统计（供环二流水线调用）。"""
    rows = []
    for pid, cond, src in pairs:
        r = judge(cond, src)
        r["id"] = pid
        rows.append(r)
    stat = {}
    for r in rows:
        stat[r["verdict"]] = stat.get(r["verdict"], 0) + 1
    return {"rows": rows, "stats": stat, "ok": sum(1 for r in rows if r["ok"])}