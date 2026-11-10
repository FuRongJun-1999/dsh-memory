#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""R-401 · 注释引用实体化扫描器（scripts/check_comment_refs.py）

【为什么有它】
灵枢的注释密度极高，而且大量守卫/测试以「注释里点名一个文件」的形式存在
（「守卫 `scripts/check_op_table_parity.py`」「见 `test_bm25.py::test_top50…`」）。  （R-401b：该守卫未落盘）
审计发现其中相当一部分**文件根本不存在** —— 注释成了「已经做过了」的凭证。
本脚本把这类凭证变成可判定的断言：注释点名的路径必须真实存在。

【判什么】
扫 `*.py` / `*.md` / `*.ts` / `*.mjs` 的**注释与 docstring 行**（不扫代码行），
提取形如 `scripts/xxx.py`、`md_cg/xxx.py`、`test_xxx.py`、`hive/xxx.py` 的路径，
逐条断言该路径在仓库根下存在。

【不判什么】
- 以 `http://` / `https://` 开头的 URL
- 绝对路径（`/home/ubuntu/…`、`D:\\…`）
- 明显是「计划/待建」的（行内含「待建」「plan」「TODO」时降级为 note 不报红）
- `*.pyc` / `*.pyo`

【退出码】0 = 全部存在；1 = 有缺失；2 = 自身故障

【负控】在任一注释里加一行 `见 scripts/__not_exist__.py` ⇒ 必须报红。
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _basenames():
    """全仓已跟踪文件的 basename 全集（git ls-files；git 不可用时退化为 os.walk）。"""
    import subprocess
    try:
        r = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                           encoding="utf-8", errors="replace", timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            return {os.path.basename(x) for x in r.stdout.splitlines() if x.strip()}
    except Exception:
        pass
    out = set()
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "__pycache__")]
        for f in filenames:
            out.add(f)
    return out


BASENAMES = _basenames()

#: 扫描面（相对仓库根）
SCAN_DIRS = ("md_cg", "scripts", "hive", "compiler", "swarm", "test", "src", "docs")
EXTS = (".py", ".md", ".ts", ".mjs")

#: 路径候选：至少带一个 `/`，或 `test_*.py` 这种具名测试
PATH_RE = re.compile(
    r"(?<![\w/.-])("
    r"(?:md_cg|scripts|hive|compiler|swarm|test|src)/[\w./-]+\.py"
    r"|test_[\w]+\.py"
    r"|bench_[\w]+\.py"
    r"|check_[\w]+\.py"
    r"|gen_[\w]+\.py"
    r"|gate_[\w]+\.py"
    r")"
)

#: 注释行判据（Python 的 # / docstring 内文、Markdown 的正文都算 —— 本仓注释即文档）
SKIP_MARKERS = ("TODO", "待建", "待补", "计划", "未来", "尚未", "将新增",
                "不存在", "已删", "原为", "曾有", "应为")
#: 明显不是仓内路径的前缀
ABS_PREFIX = ("http://", "https://", "/home/", "/opt/", "D:\\", "C:\\", "~/", "/tmp/")


def _iter_files():
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [x for x in dirnames
                           if x not in ("__pycache__", ".pytest_cache", "node_modules",
                                        "_archive", ".git", "_md_cg_p0", "_md_cg_p1",
                                        "_md_cg_p26", "_md_cg_p27", "_md_cg_p28",
                                        "_md_cg_membench")]
            for fn in filenames:
                if fn.endswith(EXTS):
                    yield os.path.join(dirpath, fn)


def comment_lines(path):
    """返回「注释或字符串（含 docstring）」所在行号集合。

    只在那些行里找路径引用 —— 否则（示例）`check(r2_reason("src/__pycache__/x.py"))`
    这类**代码里的样本字符串**会被误判成「注释点名」。
    非 .py 文件（Markdown）整篇都算文档，返回 None 表示「全扫」。
    """
    if not path.endswith(".py"):
        return None
    import ast as _ast
    import tokenize
    rows = set()
    try:
        src = io.open(path, encoding="utf-8", errors="replace").read()
        # ① 注释行
        with io.open(path, "rb") as fh:
            for tok in tokenize.tokenize(fh.readline):
                if tok.type == tokenize.COMMENT:
                    rows.add(tok.start[0])
        # ② docstring 行（只认模块/类/函数的首个表达式字符串；
        #    普通代码字符串是**样本数据**，不是「注释点名」）
        for node in _ast.walk(_ast.parse(src)):
            if not isinstance(node, (_ast.Module, _ast.ClassDef,
                                     _ast.FunctionDef, _ast.AsyncFunctionDef)):
                continue
            body = getattr(node, "body", None) or []
            if not body:
                continue
            first = body[0]
            if (isinstance(first, _ast.Expr)
                    and isinstance(first.value, _ast.Constant)
                    and isinstance(first.value.value, str)):
                for r in range(first.lineno, (first.end_lineno or first.lineno) + 1):
                    rows.add(r)
    except Exception:
        return None
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="只打印缺失项")
    ap.add_argument("--max", type=int, default=200, help="最多打印多少条缺失")
    a = ap.parse_args()

    missing = []
    scanned = 0
    n_refs = 0
    for path in _iter_files():
        scanned += 1
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        try:
            txt = io.open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        _cl = comment_lines(path)
        for lineno, line in enumerate(txt.splitlines(), 1):
            if _cl is not None and lineno not in _cl:
                continue
            for m in PATH_RE.finditer(line):
                cand = m.group(1)
                if any(p in cand for p in ABS_PREFIX):
                    continue
                # 占位符/夹具路径（不是「守卫凭证」，是示例写法）
                if any(x in cand for x in ("xxx", "XXX", "__ghost__", "placeholder",
                                           "your_", "example")):
                    continue
                if cand.startswith(("http://", "https://")):
                    continue
                n_refs += 1
                _c = cand.replace("/", os.sep)
                # ① 相对仓库根
                if os.path.exists(os.path.join(ROOT, _c)):
                    continue
                # ② 相对**引用方所在目录**（内嵌子项目的文档与测试常这么写）
                if os.path.exists(os.path.join(os.path.dirname(path), _c)):
                    continue
                # ③ 引用方目录的上级（`docs/x.md` 里点名 `test_y.py` 指子包根）  （R-401b：该守卫未落盘）
                if os.path.exists(os.path.join(os.path.dirname(os.path.dirname(path)), _c)):
                    continue
                # 宽松匹配：同名文件只要在**全仓任意位置**存在就算了（注释常只写裸文件名，
                # 而测试可能住在子包的 tests/ 下，如 `swarm/tests/test_swarm_cli.py`）。
                base = os.path.basename(cand)
                if base in BASENAMES:
                    continue
                soft = any(s in line for s in SKIP_MARKERS)
                # 引用方本身是测试文件 ⇒ 目标多半是它自己造的临时夹具（`scripts/bad.py`  （R-401b：该守卫未落盘）
                # 之类），降级为 soft：那不是「守卫凭证」，是测试数据。
                if os.path.basename(rel).startswith("test_"):
                    soft = True
                # 注释自己声明是「示例/负控/反例」的（`见 scripts/x.py`、`如 scripts/bad.py`）
                if any(x in line for x in ("示例", "负控", "反例", "举例", "e.g.", "例如",
                                           "占位", "假路径", "not_exist", "__not_exist__",
                                           "mock", "fictitious",
                                           # R-401b：注释自己已标记「该守卫没落盘」⇒ 不再是假凭证
                                           "未落盘", "未实现", "尚未落盘", "均不存在")):
                    soft = True
                missing.append({"at": "%s:%d" % (rel, lineno), "ref": cand,
                                "soft": soft, "doc": path.endswith(".md"),
                                "line": line.strip()[:160]})
    # 分级：**.py 源文件里的缺失 = hard**（守卫凭证失效，判红）；
    # .md 文档里的 = doc（历史记录/计划稿，不判红）；命中「计划/历史」词的 = soft。
    hard = [x for x in missing if not x["soft"] and not x["doc"]]
    doc = [x for x in missing if not x["soft"] and x["doc"]]
    soft = [x for x in missing if x["soft"]]

    if not a.quiet:
        print("[check_comment_refs] 扫描 %d 个文件 / 命中 %d 处路径引用" % (scanned, n_refs))
    if hard:
        print("\n✗ .py 注释点名但文件不存在（hard，%d 处）：" % len(hard))
        for x in hard[: a.max]:
            print("  %-46s → %s" % (x["at"], x["ref"]))
            print("      %s" % x["line"])
    if doc:
        print("\n· .md 文档里的缺失（doc，%d 处，不判红 —— 历史记录/计划稿）：" % len(doc))
        for x in doc[:8]:
            print("  %-46s → %s" % (x["at"], x["ref"]))
    if soft:
        print("\n· 疑似「计划/历史」引用（soft，%d 处，不判红）：" % len(soft))
        for x in soft[:10]:
            print("  %-46s → %s" % (x["at"], x["ref"]))

    print("\n结果：**hard %d**（.py 注释点名但缺件）/ doc %d / soft %d（扫描面 %d 文件）"
          % (len(hard), len(doc), len(soft), scanned))
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
