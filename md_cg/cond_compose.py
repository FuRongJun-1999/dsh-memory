# -*- coding: utf-8 -*-
"""白箱条件填充器：把 cond_facts 的事实按 LLM 模板填成「功能级生效条件」（确定性、零 LLM）。

# 功能名：生效条件白箱填充
# 生效条件：已取得模板（md_cg/cond_template.json，由 LLM 产出并留痕）且有 cond_facts 事实时；用于批量生成候选注释文本
# 子功能：按模板槽位 symbol/required/optional/externals/guards/returns/doc 组句；externals 剔除 import 来源与内置名；证据不足按模板规则输出 BLINDSPOT
# 执行：python -X utf8 -m md_cg.cond_compose <file>... [--terse] [--json]；库内调用 compose_file(path)
# 验证方式：md_cg/test_cond_compose.py；生成文本须过 condition_anchor.judge（ANCHORED 或 BLINDSPOT，不得 WEAK/REJECT_META）
# 不适用条件：①本器只按事实填模板，**不新增语义**；证据不足即 BLINDSPOT ②--terse 会省略空槽位（与模板逐字填充不同，属受控偏离，见 README）③模板变更须同步本器槽位
"""
from __future__ import annotations

import ast
import builtins
import json
import os
import sys

from . import condition_anchor, cond_facts

BUILTINS = set(dir(builtins))
TPL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cond_template.json")


def load_template(path=None):
    return json.load(open(path or TPL_PATH, encoding="utf-8"))


def import_names(path):
    """该文件里 import 进来的名字（这些不是「状态来源」，是固定依赖，不进条件）。"""
    names = set()
    try:
        tree = ast.parse(open(path, encoding="utf-8", errors="replace").read())
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                names.add(a.asname or a.name)
    return names


def module_constants(path):
    """模块级常量名（顶层赋值目标）——它们是真正的『状态来源』，函数/类定义不算。"""
    consts = set()
    try:
        tree = ast.parse(open(path, encoding="utf-8", errors="replace").read())
    except SyntaxError:
        return consts
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    consts.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            consts.add(node.target.id)
    return consts - import_names(path)


def explained_guards(rec, allowed):
    """只保留「早退式」且标识符全部可解释的守卫（模板校验清单第 6/9 条）。"""
    out = []
    for g in rec.get("guards") or []:
        if not g.get("early"):
            continue
        ids = set(__import__("re").findall(r"[A-Za-z_][A-Za-z0-9_]*", g.get("cond") or ""))
        if any(i not in allowed and i not in BUILTINS and i not in ("self", "cls") for i in ids):
            continue
        out.append(g)
    return out


def compose(rec, imports=None, terse=True, consts=None):
    """按模板把一条事实填成中文生效条件；terse=True 省略空槽位。"""
    imports = imports or set()
    consts = consts or set()
    name = rec["name"]
    required = list(rec.get("required") or [])
    optional = list(rec.get("optional") or [])
    # 外部名只保留「模块级常量」——它们才是可陈述的状态来源（函数与 import 不是条件）
    externals = [x for x in (rec.get("externals") or []) if x in consts]
    allowed = set(required) | {o["name"] for o in optional} | set(externals)
    guards = explained_guards(rec, allowed)
    returns = list(rec.get("returns") or [])
    doc = (rec.get("doc_head") or "").strip()
    # 模板规则：必需与外部锚点皆无 → BLINDSPOT（不可判，不猜）
    if not required and not externals:
        return "BLINDSPOT：缺证据（无必需形参且无体内外部名锚点）"
    parts = []
    if required:
        parts.append("必须提供实参 " + "、".join(required))
    elif not terse:
        parts.append("无必需实参")
    if optional:
        parts.append("可选 " + "、".join("%s=%s" % (o["name"], o["default"] or "None") for o in optional) + " 可省略")
    elif not terse:
        parts.append("无显式可选实参")
    if externals:
        parts.append("体内引用 " + "、".join(externals) + " 需已定义")
    for g in guards:
        if g["kind"] == "if":
            parts.append("当 " + g["cond"] + " 成立")
        elif g["kind"] == "assert":
            parts.append("断言 " + g["cond"] + " 成立")
        else:
            parts.append("可能抛出 " + (g["cond"] or "异常"))
    if returns:
        parts.append("返回 " + " 或 ".join(returns[:2]))
    head = "调用 " + name + " 时" if rec.get("kind") != "class" else "构造/使用 " + name + " 时"
    body_text = head + "，" + "；".join(parts)
    if doc:
        # 不截断半个词：超长时在最近的句读处收口（校验器 C9 曾抓出 'option' ≠ 'referenced'）
        short = doc if len(doc) <= 120 else doc[:120].rsplit("。", 1)[0] + "。"
        body_text += "；功能：" + short.rstrip("。")
    return body_text + "。"


def compose_symbol(path, rec, terse=True):
    """生成并**当场过门禁**（condition_anchor.judge），返回条件与裁决。"""
    imports = import_names(path)
    consts = module_constants(path)
    cond = compose(rec, imports=imports, terse=terse, consts=consts)
    lines = open(path, encoding="utf-8", errors="replace").read().split(chr(10))
    seg = chr(10).join(lines[max(0, rec["lineno"] - 1): rec["end"]])
    verdict = condition_anchor.judge(cond, seg)
    return {"name": rec["name"], "kind": rec["kind"], "lineno": rec["lineno"],
            "end": rec["end"], "condition": cond, "gate": verdict["verdict"],
            "anchors": verdict["anchors"]}


def compose_file(path, terse=True):
    out = []
    for rec in cond_facts.file_facts(path):
        out.append(compose_symbol(path, rec, terse=terse))
    return out


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    terse = "--terse" in argv
    as_json = "--json" in argv
    files = [a for a in argv if not a.startswith("--")]
    rows = []
    for f in files:
        for r in compose_file(f, terse=terse):
            r["path"] = f
            rows.append(r)
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    stat = {}
    for r in rows:
        stat[r["gate"]] = stat.get(r["gate"], 0) + 1
    for r in rows:
        print("[" + r["gate"] + "] " + r["path"] + ":" + str(r["lineno"]) + " " + r["name"])
        print("    " + r["condition"][:200])
    print("STAT " + json.dumps(stat, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())