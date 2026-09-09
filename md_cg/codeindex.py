# -*- coding: utf-8 -*-
"""条件代码图：按注释/接口索引代码，不存完整代码。

设计（2026-09-09）：认知图通过「大域」（目录）索引；代码节点存的是
**注释与接口**——模块 docstring、def/class 签名、docstring、前置注释；
正文一律不复制，用 code_ref 指回源文件。读取走注释索引，零 LLM，纯 AST。

节点正文（可被 search 命中的注释块）：
    # path::symbol (kind, L12-L30)
    # def foo(x: int) -> str
    # 前置注释
    # doc: <docstring 首段>
"""
from __future__ import annotations

import ast
import os

SUFFIX = (".py",)
SKIP_DIRS = ("__pycache__", ".git", ".venv", "venv", "node_modules", ".mypy_cache")
MAX_DOC = 400


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


def extract(source, path=""):
    """抽取一个文件的注释/接口条目；语法错误抛 ValueError。"""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError(f"{path}:{exc.lineno}: {exc.msg}") from exc
    lines = source.split("\n")
    items = [{"path": path, "name": os.path.basename(path) or "<module>",
              "kind": "module", "lineno": 1, "end": len(lines),
              "sig": "", "doc": _doc_of(tree), "comments": []}]
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
            continue
        kind = ("class" if isinstance(node, ast.ClassDef)
                else "async_def" if isinstance(node, ast.AsyncFunctionDef)
                else "def")
        items.append({
            "path": path, "name": node.name, "kind": kind,
            "lineno": node.lineno, "end": getattr(node, "end_lineno", node.lineno),
            "sig": _sig(source, node), "doc": _doc_of(node),
            "comments": _leading_comments(lines, node.lineno)})
    return items


def render(item):
    """条目 → 可索引的注释块（认知图存的正文，不含实现）。"""
    parts = ["# %s::%s (%s, L%s-L%s)" % (item["path"], item["name"],
                                         item["kind"], item["lineno"], item["end"])]
    if item.get("sig"):
        parts.append("# " + item["sig"])
    for c in item.get("comments") or []:
        parts.append("# " + c.lstrip("#").strip())
    if item.get("doc"):
        parts.append("# doc: " + item["doc"].replace("\n", " ")[:MAX_DOC])
    return "\n".join(parts)


def node_id(item):
    """稳定 id：path::name 的短哈希（重复索引幂等）。"""
    import hashlib
    key = (item["path"] + "::" + item["name"]).encode("utf-8")
    return "code_" + hashlib.sha1(key).hexdigest()[:12]


def index_dir(root, patterns=None, max_files=500, max_items=2000):
    """按大域（目录）遍历代码，产出 (items, errors)。零 LLM。"""
    pats = tuple(patterns or SUFFIX)
    items, errors, files = [], [], 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            if not fn.endswith(pats):
                continue
            if files >= max_files or len(items) >= max_items:
                return items, errors
            files += 1
            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, root).replace("\\", "/")
            try:
                with open(fp, encoding="utf-8") as f:
                    src = f.read()
                items.extend(extract(src, rel))
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                errors.append(f"{rel}: {exc}")
    return items, errors
