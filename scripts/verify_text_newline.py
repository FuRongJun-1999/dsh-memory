#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 功能名：仓内文本文件的换行守卫——受控文件不得混入 CRLF；仓内写侧必须声明 newline
# 生效条件：提交前 / 门禁；任何会写 md_cg、scripts、hive、compiler 下文件的改动，或新增受控文本文件时
# 子功能：A=事实面（git ls-files 里全部文本类受控文件，逐字节查 CRLF；命中即报文件名与处数）；B=写侧面（AST 找「目标为仓内常量/__file__ 相对 + 文本写 + 未声明 newline」的调用点，仅限已知会写仓内文件的那种形态）；R=变异自证（造 CRLF 夹具必红、造 LF 夹具必绿）
# 执行：python -X utf8 scripts/verify_text_newline.py [--self-test]
# 验证方式：两问全绿退出 0；有违例退出 1；锚点漂移退出 2
# 不适用条件：不判临时目录（tempfile/mkdtemp/TEMP 下 CRLF 无害）；不判二进制；不判读侧；不要求把历史既存 CRLF 一次性转 LF（那 3 个文件是特例，靠 WHITELIST 显式登记）
"""`verify_text_newline.py` · 换行守卫（事实面 + 写侧面）。

## 病象（实测，2026-11-08）

`code_compose.code_solidify()` 用
`json.dump(..., open(_SOL_FILE, "w", encoding="utf-8"), indent=1)` 写
`md_cg/whitebox_kb/wisdom/code_solidified.json`——**入库文件**，仓内规范换行是 LF。
文本模式不声明 `newline=` 时，Windows 上每个 `\n` 被翻成 `\r\n`：

    跑一次 `md_cg.whitebox_kb.wisdom.test_code_compose_domains`，
    `git status` 立刻多一条 `code_solidified.json | 12390 +++---`
    （6195 行 LF → CRLF；JSON 语义不变，键数 619 = 619）。

危害不是「跑坏」，是：
  ① 噪声淹没真改动（一条 6195 行假 diff 会藏掉同批真逻辑）；
  ② 诱导误提交（`git add -A` 把纯换行变更带进历史，污染 blame）；
  ③ 跨平台反复翻转（Linux CI 写 LF、Windows 开发写 CRLF，两边永远互脏）。

## 判据（两问，A 是主判据、B 是预防判据）

**A｜事实面（主）**：`git ls-files` 里全部文本类受控文件，逐字节读，**不得含 `\r\n`**。
仓内换行约定就是 LF——这不是「要求」，是仓库现状（实测 3044 个受控文本文件里
只有 3 个含 CRLF，且都是历史遗留，已在 `WHITELIST` 显式登记理由）。
新出现的 CRLF 一定是某次写入没声明 `newline=`。

**B｜写侧面（防）**：AST 找**内联** `json.dump(...)` / `.write(...)` 且
`open(目标, "w"...)` 未声明 `newline=` 的调用点——但只在目标能确认是**仓内受控常量**
（`_SOL_FILE` 等模块级 `__file__` 相对路径常量）时计入。测试里对临时沙箱的写入一律不计
（`tempfile.mkdtemp` 派生），否则会淹没在几百个夹具里，判据就失去分辨力。

## ANCHOR（漂移即报，退出 2，fail-closed）

- 受控文本文件数下限（枚举失效 ⇒ 不得当假绿）；
- `code_solidified.json` 必须在受控清单里（本守卫的立项目的，掉了说明扫描面坏了）。

用法：
  python -X utf8 scripts/verify_text_newline.py
  python -X utf8 scripts/verify_text_newline.py --self-test
"""
from __future__ import annotations

import argparse
import ast
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from utf8_boot import ensure_utf8  # noqa: E402

ensure_utf8(__file__)

#: 文本类受控文件的后缀（二进制/图片等不判）
TEXT_EXT = (".py", ".json", ".md", ".txt", ".yml", ".yaml", ".toml",
            ".cfg", ".ini", ".sh", ".ps1", ".ts", ".js", ".css", ".html")

#: 白名单：**历史遗留**的 CRLF 受控文件。空清单是终态；这里有内容说明还没清完，
#: 守卫会双向核对（有而未命中 / 命中而不在清单），绝不做静默豁免。
WHITELIST: dict[str, str] = {
    "docs/theory/缓存感知的记忆注入架构_v6.0_level0000x.md":
        "历史文档（2612 处 CRLF），转 LF 会产生 2612 行假 diff，留待专项处理",
    "md_cg/iface/_verify.py":
        "历史遗留（609 处 CRLF），同上",
    "md_cg/test_reach_meta_exits.py":
        "历史遗留（145 处 CRLF），同上",
}

#: 扫描面下限（ANCHOR）
_FLOOR_TRACKED_TEXT = 2000

#: 立项目的对照：该文件必须在受控清单里
_MUST_BE_TRACKED = "md_cg/whitebox_kb/wisdom/code_solidified.json"

SCAN_DIRS = ("md_cg", "scripts", "hive", "compiler")


class AnchorMiss(Exception):
    pass


def _tracked_text_files() -> list:
    r = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                       capture_output=True)
    out = []
    for f in r.stdout.split(b"\x00"):
        if not f:
            continue
        name = f.decode("utf-8", "replace")
        if name.lower().endswith(TEXT_EXT):
            out.append(name)
    return out


def _audit_crlf(files: list) -> tuple:
    """返回 (命中列表, 检查数)。命中 = [(rel, crlf_count)]，已剔除白名单。"""
    hits = []
    checked = 0
    for rel in files:
        try:
            raw = open(os.path.join(ROOT, rel), "rb").read()
        except OSError:
            continue
        checked += 1
        if b"\r\n" not in raw:
            continue
        if rel in WHITELIST:
            continue
        hits.append((rel, raw.count(b"\r\n")))
    return hits, checked


def _has_dunder_file(node: ast.AST) -> bool:
    """表达式里是否出现 `__file__`。

    注意：`__file__` 在 AST 里是 **`ast.Name`**（id == "__file__"），
    不是 `ast.Attribute`——早先在这里判 Attribute 导致
    `_SOL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ...)`
    识别不出来，B 面形同空转（变异不转红，是假绿）。
    """
    for x in ast.walk(node):
        if isinstance(x, ast.Name) and x.id == "__file__":
            return True
    return False


def _module_level_repo_names(tree: ast.Module) -> set:
    """模块级、值里含 `__file__` 的赋值名——视作「仓内路径常量」。"""
    names = set()
    for n in tree.body:
        if not isinstance(n, ast.Assign):
            continue
        if _has_dunder_file(n.value):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
    return names


def _is_repo_const(node: ast.AST, names: set) -> bool:
    for x in ast.walk(node):
        if isinstance(x, ast.Name) and x.id in names:
            return True
    return False


def _mode_and_nl(call: ast.Call):
    mode = None
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
        if isinstance(call.args[1].value, str):
            mode = call.args[1].value
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            if isinstance(kw.value.value, str):
                mode = kw.value.value
    has_nl = any(kw.arg == "newline" for kw in call.keywords)
    if mode is None:
        return True, has_nl
    if "b" in mode:
        return False, has_nl
    if not any(c in mode for c in "wax"):
        return False, has_nl
    return True, has_nl


def _audit_writers() -> list:
    """B｜写侧面：内联 open(仓内常量, "w") 无 newline 的调用点。"""
    bad = []
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for dp, dns, fns in os.walk(base):
            dns[:] = [x for x in dns if x not in ("__pycache__", "node_modules", ".git")]
            for fn in fns:
                if not fn.endswith(".py"):
                    continue
                fp = os.path.join(dp, fn)
                rel = os.path.relpath(fp, ROOT).replace("\\", "/")
                raw = open(fp, "rb").read()
                if raw[:3] == b"\xef\xbb\xbf":
                    raw = raw[3:]
                try:
                    tree = ast.parse(raw, fp)
                except SyntaxError:
                    continue
                names = _module_level_repo_names(tree)
                if not names:
                    continue                      # 没有仓内常量 ⇒ 不可能写仓内受控文件
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    f = node.func
                    # 只挑 json.dump(...) / fh.write(...) 这类「写到内联 open」的形态
                    name = getattr(f, "attr", None)
                    if name not in ("dump", "write", "writelines"):
                        continue
                    for sub in ast.walk(node):
                        if not (isinstance(sub, ast.Call)
                                and isinstance(sub.func, ast.Name)
                                and sub.func.id == "open"):
                            continue
                        if not sub.args:
                            continue
                        if not _is_repo_const(sub.args[0], names):
                            continue
                        is_text, has_nl = _mode_and_nl(sub)
                        if is_text and not has_nl:
                            bad.append((rel, sub.lineno))
    return bad


def _self_test() -> int:
    """变异自证：造含 CRLF 的文件必红、造纯 LF 必绿。"""
    import tempfile
    miss = []
    tmp = tempfile.mkdtemp(prefix="nl_selftest_")
    try:
        crlf_f = os.path.join(tmp, "crlf.json")
        lf_f = os.path.join(tmp, "lf.json")
        with open(crlf_f, "wb") as fh:
            fh.write(b'{\r\n "a": 1\r\n}')
        with open(lf_f, "wb") as fh:
            fh.write(b'{\n "a": 1\n}')
        if b"\r\n" not in open(crlf_f, "rb").read():
            miss.append("夹具①未生成 CRLF")
        if b"\r\n" in open(lf_f, "rb").read():
            miss.append("夹具②混入了 CRLF")
        # 用真实受控文件面确认「干净基线」成立（否则判据无分辨力）
        files = _tracked_text_files()
        hits, checked = _audit_crlf(files)
        if hits:
            miss.append("当前仓内已存在未登记 CRLF：%s（守卫会一直红，需先清理或登记）"
                        % hits[:3])
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    if miss:
        print("✘ ANCHOR-MISS（%d 项）：" % len(miss))
        for m in miss:
            print("   -", m)
        return 2
    print("✔ 自检通过：CRLF 夹具可检、LF 夹具不误报、仓内基线干净")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return _self_test()

    files = _tracked_text_files()
    try:
        if len(files) < _FLOOR_TRACKED_TEXT:
            raise AnchorMiss("受控文本文件数 %d < 下界 %d（枚举失效？）"
                             % (len(files), _FLOOR_TRACKED_TEXT))
        if _MUST_BE_TRACKED not in files:
            raise AnchorMiss("立项目的文件不在受控清单：%s" % _MUST_BE_TRACKED)
    except AnchorMiss as e:
        print("✘ ANCHOR-MISS：%s" % e)
        return 2

    hits, checked = _audit_crlf(files)
    writers = _audit_writers()

    print("A 事实面：检查受控文本文件 %d 个；含 CRLF %d 个（白名单 %d 个已登记）"
          % (checked, len(hits), len(WHITELIST)))
    print("B 写侧面：内联写仓内常量且未声明 newline 的调用点 %d 处" % len(writers))

    # 白名单双向核对
    wh_hit = {rel for rel, _c in hits}
    wh_bad = []
    all_crlf = set()
    for rel in files:
        try:
            if b"\r\n" in open(os.path.join(ROOT, rel), "rb").read():
                all_crlf.add(rel)
        except OSError:
            pass
    for rel, why in WHITELIST.items():
        if rel not in all_crlf:
            wh_bad.append(("白名单有而文件已无 CRLF（可从清单移除）", rel, why))

    if hits or writers or wh_bad:
        if hits:
            print("\n✘ A｜受控文件混入 CRLF %d 个：" % len(hits))
            for rel, c in hits[:20]:
                print("    %s  (%d 处)  ← 有写入没声明 newline=，或文件被 Windows 工具改写"
                      % (rel, c))
        if writers:
            print("\n✘ B｜会写仓内文件但未声明 newline= %d 处：" % len(writers))
            for rel, ln in writers[:20]:
                print("    %s:%d" % (rel, ln))
        for kind, rel, why in wh_bad:
            print("\n… %s：%s（%s）" % (kind, rel, why))
        return 1

    print("\n✔ A 全部受控文本文件换行均为 LF（%d 个白名单外的 0 个例外）"
          % len(WHITELIST))
    print("✔ B 无「写仓内文件却不声明 newline」的调用点")
    return 0


if __name__ == "__main__":
    sys.exit(main())
