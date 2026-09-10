# -*- coding: utf-8 -*-
"""条件代码图：按注释/接口索引代码，不存完整代码。

设计（2026-09-09；2026-09-10 修订）：
认知图通过「大域」（目录）索引；代码节点存的是**注释与接口**——模块 docstring、
签名、docstring、前置注释；正文一律不复制，用 frontmatter.code_ref 指回源文件。
读取走注释索引，零 LLM，纯 AST（弱提取器除外，见下）。

节点正文必须是 **CCG 6 行**（见 `render`）：非 CCG 正文会被 `judge_qualification`
的第一步（ccg_completeness）直接判 **BLINDSPOT**，节点存进去了也检索不到可用结论。

提取器按后缀注册（`EXTRACTORS`）：
    .py              → AST 提取，precise=True，区间精确到 end_lineno，基底 compiler
    .ts/.tsx/.js/... → 正则弱提取，precise=False，区间为**上界**，基底 other（诚实降级）

区间哈希：每条目带 `hash`（被引用行的 sha1 前 12 位，见 `_region_hash`），
用于后续判断「索引出来的位置是不是已经漂了」——它不是内容寻址，只做变更探测。
"""
from __future__ import annotations

import ast
import hashlib
import os
import re

SKIP_DIRS = ("__pycache__", ".git", ".venv", "venv", "node_modules", ".mypy_cache")
MAX_DOC = 400

LANG_COMPILER = "compiler"
LANG_WEAK = "other"


# --------------------------------------------------------------------------
# Python：AST 提取（精确）
# --------------------------------------------------------------------------
def _doc_of(node):
    return (ast.get_docstring(node, clean=True) or "").strip()[:MAX_DOC]


def _leading_comments(lines, lineno):
    """定义行前的连续注释（# ...）。"""
    out, i = [], lineno - 2
    while i >= 0:
        s = lines[i].strip()
        if s.startswith("#"):
            out.append(s)
            i -= 1
        elif not s and out:
            break
        elif not s:
            i -= 1
        else:
            break
    return list(reversed(out))


def _sig(source, node):
    try:
        seg = ast.get_source_segment(source, node) or ""
    except (ValueError, TypeError):
        seg = ""
    return seg.split("\n", 1)[0].strip()[:200]


def _walk_defs(tree):
    """按**源码顺序**产出 (定义节点, 所属类名)。

    不用 `ast.walk`：它给出的是广度优先、与源码顺序不一致，且丢掉父级归属。
    父级归属是「子功能」与「不适用条件」两项的判定依据（同名方法必须能区分
    是哪个类的），不能省。
    """
    def rec(node, parent):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                yield child, parent
                yield from rec(child, child.name)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield child, parent
                yield from rec(child, parent)
            else:
                yield from rec(child, parent)
    return rec(tree, "")


def _extract_python(source, path):
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError(f"{path}:{exc.lineno}: {exc.msg}") from exc
    lines = source.split("\n")
    items = [{"path": path, "name": os.path.basename(path) or "<module>",
              "kind": "module", "parent": "", "lineno": 1, "end": len(lines),
              "sig": "", "doc": _doc_of(tree), "comments": []}]
    for node, parent in _walk_defs(tree):
        kind = ("class" if isinstance(node, ast.ClassDef)
                else "async_def" if isinstance(node, ast.AsyncFunctionDef)
                else "def")
        items.append({
            "path": path, "name": node.name, "kind": kind, "parent": parent,
            "lineno": node.lineno, "end": getattr(node, "end_lineno", node.lineno),
            "sig": _sig(source, node), "doc": _doc_of(node),
            "comments": _leading_comments(lines, node.lineno)})
    return items


# --------------------------------------------------------------------------
# TS/JS：正则弱提取（不精确，区间为上界）
# --------------------------------------------------------------------------
_JS_DEF = re.compile(
    r"^(?P<indent>[ \t]*)(?:export\s+)?(?:default\s+)?(?:declare\s+)?"
    r"(?:abstract\s+)?(?:async\s+)?"
    r"(?P<kind>class|interface|enum|type|function|const)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)", re.M)
# 这些关键字只在模块作用域（缩进为空）才算对外接口，否则会把函数内的局部
# const 全捞进来，把索引淹掉。
_JS_MODULE_SCOPE_ONLY = ("const", "type", "enum")


def _leading_js_comments(lines, lineno, lookback=25):
    """定义行前的连续行注释块，或紧邻的 /** ... */ 块。"""
    out, i = [], lineno - 2
    while i >= 0 and len(out) < lookback:
        s = lines[i].strip()
        if not s and out:
            break
        if s.endswith("*/"):
            block = []
            j = i
            while j >= 0 and len(out) + len(block) < lookback:
                block.append(lines[j].strip())
                if lines[j].strip().startswith("/*"):
                    break
                j -= 1
            out.extend(block)
            break
        if s.startswith("//"):
            out.append(s)
            i -= 1
            continue
        if not s:
            i -= 1
            continue
        break
    return list(reversed(out))


def _extract_weak(source, path):
    """正则弱提取：返回条目，`end` 为**上界**（到下一个定义之前），不保证精确。"""
    lines = source.split("\n")
    items = [{"path": path, "name": os.path.basename(path) or "<module>",
              "kind": "module", "parent": "", "lineno": 1, "end": len(lines),
              "sig": "", "doc": "", "comments": []}]
    hits = []
    for m in _JS_DEF.finditer(source):
        kind, name = m.group("kind"), m.group("name")
        if kind in _JS_MODULE_SCOPE_ONLY and m.group("indent"):
            continue
        lineno = source.count("\n", 0, m.start()) + 1
        hits.append((lineno, kind, name, m.group(0).strip()))
    for idx, (lineno, kind, name, sig) in enumerate(hits):
        end = (hits[idx + 1][0] - 1) if idx + 1 < len(hits) else len(lines)
        items.append({
            "path": path, "name": name, "kind": kind, "parent": "",
            "lineno": lineno, "end": max(lineno, end), "sig": sig[:200],
            "doc": "", "comments": _leading_js_comments(lines, lineno)})
    return items


# --------------------------------------------------------------------------
# 提取器注册表
# --------------------------------------------------------------------------
EXTRACTORS = {
    ".py": ("py", _extract_python, True, LANG_COMPILER),
    ".ts": ("ts", _extract_weak, False, LANG_WEAK),
    ".tsx": ("tsx", _extract_weak, False, LANG_WEAK),
    ".js": ("js", _extract_weak, False, LANG_WEAK),
    ".mjs": ("js", _extract_weak, False, LANG_WEAK),
    ".cjs": ("js", _extract_weak, False, LANG_WEAK),
}
SUFFIX = tuple(sorted(EXTRACTORS))


def region_hash(lines, lineno, end):
    """被引用行的 sha1 前 12 位（变更探测用，非内容寻址）。

    必须是**唯一**定义：索引侧与回读侧（`op=ref`）共用同一个函数。
    两侧各写一份哈希算法，漂移检测就会悄悄失效（永远 hash_match=True）。
    """
    seg = "\n".join(lines[max(0, lineno - 1):max(0, end)])
    return hashlib.sha1(seg.encode("utf-8")).hexdigest()[:12]


def extract(source, path="", suffix=None):
    """抽取一个文件的条目；按后缀分派提取器。语法错误抛 ValueError。

    产出条目带 `lang` / `precise` / `hash`，供 `render` 与 frontmatter.code_ref 使用。
    """
    ext = suffix or os.path.splitext(path)[1].lower()
    if ext not in EXTRACTORS:
        # 不静默降级成 Python 解析：那会把「没有提取器」伪装成「语法错误」，
        # 让调用方误以为是源码的问题。直接报缺提取器，由 index_dir 收进 errors。
        raise ValueError(f"无提取器（suffix={ext or '<none>'}）")
    lang, fn, precise, basis = EXTRACTORS[ext]
    lines = source.split("\n")
    items = fn(source, path)
    for it in items:
        it["lang"] = lang
        it["precise"] = precise
        it["basis"] = basis
        it["hash"] = region_hash(lines, it["lineno"], it["end"])
    return items


def render(item):
    """条目 → CCG 6 行正文（可被 search 命中，不含实现）。

    **必须渲染成 CCG 格式**，这是本模块最容易踩的坑：
    `judge_qualification` 第一步就查 `ccg_completeness` 的 5 要素
    （功能名 / 子功能 / 执行 / 验证方式 / 不适用条件），缺任一即**直接判
    BLINDSPOT**，后面的「verification_basis 缺失才 DEFER」根本走不到——
    即便 frontmatter 已正确填了 verification_basis。改造前本函数只产
    `# path::name` / `# sig` / `# doc:` 这类非 CCG 行，于是**所有代码节点
    恒定 BLINDSPOT**：存得进、判不了、检索不到（与「目标节点的 CCG 渲染」
    是同一策略，见 mdcg.py 的对应注释）。
    """
    name = item["name"]
    kind = item["kind"]
    path = item["path"]
    parent = item.get("parent") or ""
    top = path.split("/")[0] or "."
    doc = (item.get("doc") or "").replace("\n", " ").strip()
    comments = [c.lstrip("#").strip() for c in (item.get("comments") or [])]
    sub = doc or (comments[0] if comments else "") or f"{kind} 定义在 {path}，无注释"
    sig = (item.get("sig") or "").strip() or "（模块级，无签名）"
    if item.get("precise", True):
        basis = (f"{LANG_COMPILER}（AST 已解析，区间精确："
                 f"{path} L{item['lineno']}-L{item['end']}）")
    else:
        basis = (f"{LANG_WEAK}（正则弱提取，未过编译器；区间为**上界**，"
                 f"以 op=ref 回读为准：{path} L{item['lineno']}-L{item['end']}）")
    lines = [
        f"# 功能名：{name}（{kind}）",
        f"# 生效条件：大域={top}；检索「{name}」或路径「{path}」时",
        f"# 子功能：{parent + '.' if parent else ''}{sub[:MAX_DOC]}",
        f"# 执行：{sig}",
        f"# 验证方式：{basis}",
        "# 不适用条件：其它大域的**同名**符号（同名不同域时以 path 区分；"
        f"本条目属于 {path}）",
        f"# 位置：{path}:{item['lineno']}-{item['end']}"
        f"（{item.get('lang')}，precise={bool(item.get('precise', True))}）",
    ]
    lines.extend("# " + c for c in comments)
    return "\n".join(lines)


def node_id(item):
    """稳定 id：path::name 的短哈希（重复索引幂等）。"""
    key = (item["path"] + "::" + item["name"]).encode("utf-8")
    return "code_" + hashlib.sha1(key).hexdigest()[:12]


def index_dir(root, patterns=None, max_files=500, max_items=2000):
    """按大域（目录）遍历代码，产出 `(items, errors, stats)`。零 LLM。

    `stats["truncated"]` 必须显式上报——截断**不再是静默的**：改造前达到上限
    直接 `return`，调用方只看到 `indexed`/`error_count`，**索引不全却不告警**，
    于是「不完整」被当成「完整」用。同时上报 `skipped_suffixes`：扫到但没被
    索引的后缀要能看见，否则「不漏召回」这句话无法审计。
    """
    pats = tuple(patterns or SUFFIX)
    items, errors, files = [], [], 0
    seen_suffix = set()
    stats = {"root": root, "patterns": list(pats), "files": 0, "truncated": False,
             "truncated_reason": "", "max_files": max_files, "max_items": max_items,
             "skipped_suffixes": []}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            ext = os.path.splitext(fn)[1].lower()
            seen_suffix.add(ext)
            if not fn.lower().endswith(pats):
                continue
            if files >= max_files or len(items) >= max_items:
                stats["truncated"] = True
                stats["truncated_reason"] = (
                    f"files={files}>=max_files={max_files}"
                    if files >= max_files else
                    f"items={len(items)}>=max_items={max_items}")
                stats["files"] = files
                stats["skipped_suffixes"] = sorted(
                    s for s in seen_suffix if s and s not in pats)[:12]
                return items, errors, stats
            files += 1
            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, root).replace("\\", "/")
            try:
                with open(fp, encoding="utf-8") as f:
                    src = f.read()
                got = extract(src, rel)
                items.extend(got)
                if len(items) >= max_items:
                    # 单文件就可能越限：越限即记截断并立刻停，不装看不见、
                    # 也不继续往下扫（继续扫只会让「截断」这件事更不明显）。
                    stats["truncated"] = True
                    stats["truncated_reason"] = (
                        f"items={len(items)}>=max_items={max_items}")
                    stats["files"] = files
                    stats["skipped_suffixes"] = sorted(
                        s for s in seen_suffix if s and s not in pats)[:12]
                    return items, errors, stats
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                errors.append(f"{rel}: {exc}")
    stats["files"] = files
    stats["skipped_suffixes"] = sorted(s for s in seen_suffix if s and s not in pats)[:12]
    return items, errors, stats
