#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""重复键守卫（issue #118 / #119）：同键两次取值不同 ⇒ 非零退出。

为什么需要：Python 字典字面量**同键后者胜**——先写的那一项被静默丢弃，
其「声明的项」运行期永久不可达；当该键是**安全口径表**时，安全属性更是
完全依赖**书写次序**（重排两行即静默回退）。

实测两例（2026-10-11，本仓）：
  · #118 \`md_cg/mcp_server.py\` 的 \`_MDCG_OP_REQUIRE["mdcg_protect"]\` 被写两次
    （"write" 与 "protect"）；后者胜故运行期口径正确，但重排即让任何 can_write
    角色经工具面 action=snapshot 真落盘 _protected_history。
  · #119 \`md_cg/whitebox_kb/wisdom/\` 下 4 处：源码写着的映射对永久不可达
    （科学方法论 11 项 / 自我认知 3 项 / 冰箱 2 项 / 惯性 1 项）。

判据（AST，不看运行期；运行期已看不到被丢弃的项）：
  · **DIFF_VALUE**  同键两次、两次**字面量取值不同** ⇒ **硬失败**（exit 1）
  · **SAME_VALUE**  同键两次、取值相同 ⇒ 仅告警（死代码，无行为差异）
  · **UNEVALUABLE** 同键两次但取值含非字面量（名字/调用/表达式） ⇒ 列出、不阻断
  · 键本身非字面量（变量/属性/\`**\` 展开）⇒ 不判（不猜测）
  · MIXED 同键下既有字面量又有表达式取值 ⇒ 按 UNEVALUABLE 列出并告警

判据面（issue #177）：R1 = 真实仓 DIFF_VALUE 归零（判据语义与输出文案逐位不变）；
R2 = 全仓可解析性（无 PARSE_ERROR）——两者都在 **git 追踪面**上判：未追踪件（本机临时
探针 / 被 gitignore 的本地产物）不入判据面；git 不可用时**显式**退化为文件系统面并在
输出里标注（绝不静默切换）。未追踪件的可解析性单列一节观察，**不计入 FAIL**。

用法：
    python -X utf8 scripts/check_duplicate_keys.py            # 人类可读
    python -X utf8 scripts/check_duplicate_keys.py --json     # 机器可读
    python -X utf8 scripts/check_duplicate_keys.py --root DIR # 换根（自证测试用）
退出码：0 通过 / 1 有 DIFF_VALUE / 2 环境错误
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)

#: 不看的面（**只用于 git 不可用时的显式退化面**；主判据面 = git 追踪面，见 scan_repo）
SKIP_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "target", ".tmp", "dist", "build", ".venv", "venv",
})

DIFF, SAME, UNEVAL, MIXED = "DIFF_VALUE", "SAME_VALUE", "UNEVALUABLE", "MIXED"


# 生效条件：node 为 ast 表达式节点；可 literal_eval 时返回 (True, 值)，否则 (False, 源码片段)；恒不抛。
def const_of(node):
    """字面量取值。非字面量返回其源码片段（供报告，不参与相等判定）。"""
    try:
        return True, ast.literal_eval(node)
    except Exception:                                       # noqa: BLE001
        try:
            return False, ast.unparse(node)
        except Exception:                                   # noqa: BLE001
            return False, "<unparseable>"


# 生效条件：values 为 [(行号, 是否字面量, 取值), ...]（同键的多次出现，按出现序）；返回 DIFF/SAME/UNEVAL/MIXED 之一——全字面量且取值有异⇒DIFF，全字面量且全同⇒SAME，全非字面量⇒UNEVAL，字面量与非字面量混⇒MIXED。
def classify_kind(values) -> str:
    """同键多次出现的分类（**判据单点**：自证测试按此打桩做定点变异）。"""
    lits = [val for _ln, ok, val in values if ok]
    kinds = {ok for _ln, ok, _v in values}
    if len(kinds) > 1:
        return MIXED
    if len(lits) >= 2 and len({repr(x) for x in lits}) > 1:
        return DIFF
    if len(lits) >= 2:
        return SAME
    return UNEVAL


# 生效条件：src 为 Python 源码文本、rel 为展示用相对路径；解析失败返回 [{"error": ...}]，否则返回该文件全部重复键条目（按出现序）。
def scan_source(src: str, rel: str) -> list:
    """扫一段源码里的重复字面量键。返回条目列表（含分类）。"""
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [{"file": rel, "kind": "PARSE_ERROR", "error": str(exc),
                 "line": getattr(exc, "lineno", 0), "key": None, "values": []}]
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        groups = {}
        for k, v in zip(node.keys, node.values):
            if k is None:                                   # ** 展开：键不可知
                continue
            ok_k, kv = const_of(k)
            if not ok_k:                                    # 键非字面量：不判
                continue
            groups.setdefault(repr(kv), []).append((k.lineno, v))
        for key, items in groups.items():
            if len(items) < 2:
                continue
            vals = [(ln,) + const_of(v) for ln, v in items]
            kind = classify_kind(vals)
            out.append({"file": rel, "key": key, "kind": kind,
                        "lines": [ln for ln, _ok, _v in vals],
                        "values": [{"line": ln, "literal": ok, "value": val}
                                   for ln, ok, val in vals]})
    out.sort(key=lambda r: (r["file"], r["lines"][0]))
    return out


# 生效条件：path 为已存在的 .py；读取/解析异常按 PARSE_ERROR/OSError 条目返回，恒不抛。
def scan_file(path: str, root: str) -> list:
    rel = os.path.relpath(path, root).replace("\\", "/")
    try:
        src = io.open(path, encoding="utf-8").read()
    except OSError as exc:
        return [{"file": rel, "kind": "PARSE_ERROR", "error": str(exc),
                 "line": 0, "key": None, "values": []}]
    return scan_source(src, rel)


#: 判据面（issue #177）：`git` = git 追踪面（真源）；`fs` = git 不可用时的**显式**退化面
SCAN_FACE_GIT, SCAN_FACE_FS = "git", "fs"
SCAN_FACE = SCAN_FACE_GIT
SCAN_FACE_REASON = ""


# 生效条件：root 为目录；返回该基座下 git 追踪面里的 .py 路径（posix 分隔、升序）。调用体例照
# scripts/workspace_index.py::tracked（NUL 分隔取原始路径，规避 core.quotepath 转义）；
# git 未安装 / 非 git 目录 / 返回非 0 ⇒ 返回 None（调用方**显式**降级，绝不静默切换）。
def tracked_py(root: str):
    try:
        p = subprocess.run(["git", "ls-files", "-z"], cwd=root, shell=False,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace",
                           env={**os.environ, "PYTHONUTF8": "1"})
    except OSError:                                          # git 未安装
        return None
    if p.returncode != 0:                                    # 非 git 目录 / 仓库不可用
        return None
    return sorted(x for x in (p.stdout or "").split("\0") if x.endswith(".py"))


# 生效条件：恒返回当前扫描面的一行标注；git 不可用时显式点名退化面，**不得静默切换**。
def scan_face_note() -> str:
    if SCAN_FACE == SCAN_FACE_GIT:
        return "[扫描面] git 追踪面（git ls-files）"
    return "[扫描面] 文件系统（git 不可用）" + (
        "；原因：%s" % SCAN_FACE_REASON if SCAN_FACE_REASON else "")


# 生效条件：root 为目录；返回 (扫描文件数, 条目列表)——返回形状与旧版逐位一致。R2 判据面 =
# **git 追踪面**（issue #177）：未追踪件（本机临时探针 / 被 gitignore 的本地产物）不入判据
# 面——否则「本地恒红（R2）/ CI 绿」分裂会让守卫被忽视，反噬核心判据 R1（真实仓 DIFF=0）。
# git 不可用时**显式**退化到 os.walk 并置 SCAN_FACE=fs（标注见 scan_face_note()）；skip_dirs
# 只作用于退化面（追踪面天然不含 gitignore 面）。
def scan_repo(root: str, skip_dirs=SKIP_DIRS) -> tuple:
    global SCAN_FACE, SCAN_FACE_REASON
    rels = tracked_py(root)
    rows, n = [], 0
    if rels is None:
        SCAN_FACE, SCAN_FACE_REASON = SCAN_FACE_FS, "git ls-files 不可用"
        for dp, dn, fns in os.walk(root):
            dn[:] = [d for d in dn if d not in skip_dirs]
            for f in sorted(fns):
                if f.endswith(".py"):
                    n += 1
                    rows.extend(scan_file(os.path.join(dp, f), root))
        return n, rows
    SCAN_FACE, SCAN_FACE_REASON = SCAN_FACE_GIT, ""
    for rel in rels:
        n += 1
        rows.extend(scan_file(os.path.join(root, rel.replace("/", os.sep)), root))
    return n, rows


# 生效条件：root 为目录；返回 R2 判据读数 {"face","files","tracked","ok"}——扫描面必须是 git
# 追踪面（未追踪件不得入判据面）；git 不可用时 ok=True（退化面已显式标注）；恒不抛。
def scan_face_verdict(root: str) -> dict:
    rels = tracked_py(root)
    n, _rows = scan_repo(root)
    if rels is None:
        return {"face": SCAN_FACE_FS, "files": n, "tracked": None, "ok": True}
    return {"face": SCAN_FACE_GIT, "files": n, "tracked": len(rels),
            "ok": bool(SCAN_FACE == SCAN_FACE_GIT and n == len(rels))}


# 生效条件：root 为目录；返回 [(未追踪 .py 相对路径, 不可解析原因)]——**单列一节报告**：只观察
# 「未追踪件的可解析性」，不进判据面、**不计入 FAIL**（报告方建议 2；issue #177）。git 不可用
# 时返回 []。恒不抛。
def untracked_py_observations(root: str) -> list:
    rels = tracked_py(root)
    if rels is None:
        return []
    seen, out = set(rels), []
    for dp, dn, fns in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in sorted(fns):
            if not f.endswith(".py"):
                continue
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, root).replace("\\", "/")
            if rel in seen:
                continue
            try:
                ast.parse(io.open(full, encoding="utf-8").read())
            except SyntaxError as exc:
                out.append((rel, "解析失败：%s" % exc))
            except (OSError, UnicodeDecodeError) as exc:
                out.append((rel, "读取失败：%s" % exc))
    return sorted(out)


# 生效条件：rows 为 scan_* 的条目列表；按 kind 计数返回 dict（键恒含三分类，缺项为 0）。
def summarize(rows) -> dict:
    got = {DIFF: 0, SAME: 0, UNEVAL: 0, MIXED: 0, "PARSE_ERROR": 0}
    for r in rows:
        got[r["kind"]] = got.get(r["kind"], 0) + 1
    return got


def _fmt(r) -> str:
    vals = " vs ".join(json.dumps(v["value"], ensure_ascii=False)[:120]
                       for v in r["values"])
    return "%s:%s 键=%s 取值=%s" % (r["file"], ",".join(map(str, r["lines"])),
                                    r["key"], vals)


# 生效条件：argv 为 None 时取 sys.argv；--root 缺省=仓根；恒返回 0（无 DIFF_VALUE）/1（有）/2（根不可用）。
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -X utf8 scripts/check_duplicate_keys.py",
                                 description="重复键守卫（issue #118/#119）")
    ap.add_argument("--root", default=_REPO, help="扫描根（缺省=仓根）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--quiet", action="store_true", help="只输出结论行")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.root):
        print("[环境错误] 根目录不可用：%s——fail-closed" % a.root)
        return 2
    n, rows = scan_repo(a.root)
    got = summarize(rows)
    diffs = [r for r in rows if r["kind"] == DIFF]
    if a.json:
        print(json.dumps({"root": a.root, "files": n,
                          "scan_face": scan_face_note(), "counts": got,
                          "diff_value": diffs,
                          "same_value": [r for r in rows if r["kind"] == SAME],
                          "unevaluable": [r for r in rows
                                          if r["kind"] in (UNEVAL, MIXED)],
                          "parse_errors": [r for r in rows
                                           if r["kind"] == "PARSE_ERROR"]},
                         ensure_ascii=False, indent=1))
    else:
        print("=== 重复键守卫（issue #118/#119）===")
        print(scan_face_note())
        print("对象 root=%s；扫描 .py = %d" % (a.root, n))
        print("分类：" + json.dumps(got, ensure_ascii=False))
        if diffs:
            print("\n[FAIL] DIFF_VALUE 重复键 %d 处（同键两次取值不同 ⇒ 先写的项不可达）"
                  % len(diffs))
            for r in diffs:
                print("   - " + _fmt(r))
        for r in rows:
            if r["kind"] == SAME:
                print("[warn] SAME_VALUE（死代码，不阻断）：" + _fmt(r))
        for r in rows:
            if r["kind"] in (UNEVAL, MIXED):
                print("[note] %s（取值非字面量，无法判定）：%s" % (r["kind"], _fmt(r)))
        for r in rows:
            if r["kind"] == "PARSE_ERROR":
                print("[note] 解析失败：%s：%s" % (r["file"], r.get("error")))
        obs = untracked_py_observations(a.root)
        print("")
        print("[观察] 未追踪 .py 的可解析性（单列一节：不进判据面、不阻断、不计入 FAIL）：%d 件"
              % len(obs))
        for _rel, _why in obs:
            print("   - %s：%s" % (_rel, _why))
        print("VERDICT=%s" % ("FAIL" if diffs else "PASS"))
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
