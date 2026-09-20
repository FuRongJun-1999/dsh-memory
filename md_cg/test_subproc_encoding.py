# -*- coding: utf-8 -*-
"""test_subproc_encoding.py · 子进程**文本解码口径**的机械守卫（第15条纪律的守卫面）

现场（2026-09-20 取证）：桥的子进程被注入 `PYTHONIOENCODING=utf-8`，其**后代**因此往
管道写 UTF-8；但后代读子进程输出时默认 text 编码取自 locale（Windows=cp936），两侧
口径不一致 → 读线程崩死、子进程诊断静默丢失：

    Exception in thread Thread-N (_readerthread):
    UnicodeDecodeError: 'gbk' codec can't decode byte 0x82 in position 181

两道防线（本守卫管第二道）：
  ① 运行期：桥子进程一律以 `PYTHONUTF8=1` 启动（PEP 540，默认 text 编码=utf-8）；
     见 `src/lib/mdcg_client.ts` 的 `mdcgChildEnv()` 与 `test/python-utf8-mode.test.ts`。
  ② 源码：**任何**文本模式子进程读取都必须显式声明 `encoding=`（配 `errors=`），
     不依赖 locale——脚本/工具也可能被非桥路径启动，那时没有 ① 的保护。

判据（**AST 判定，非文本窗口**——2026-09-20 改进）：以 `ast` 解析每个 git 跟踪的 .py，
对**真实的调用节点**判定：
· 子进程调用 = `subprocess.<run|Popen|check_output|call|check_call|getoutput|getstatusoutput>`
  （含 `import subprocess as sp` 与 `from subprocess import run` 两种别名形态）
· 文本模式 = 调用处出现 `text=<非 False>` / `universal_newlines=<非 False>` / `encoding=`
· 违例 = 文本模式却无 `encoding=` 实参；`**kwargs` 透传且**该调用确有管道**
  （`capture_output` 或 stdout/stderr=PIPE）而无 `encoding=` 报「不可判定」——口径无法
  确认即不合格，须显式声明；`os.popen` 直接违例（该 API 无法声明编码）。
  注：DEVNULL/日志文件豁免**仅适用于 `**kwargs` 透传分支**（口径无法确认时的收敛：
  有管道才判）；显式 `text=True` 时即使输出落 DEVNULL **仍判违例**——守卫的取向是
  「口径无法确认即不合格」，宁可保守（2026-09-20 v15-7 口径澄清：头注原写「输出落
  DEVNULL/日志文件且无管道的 Popen 不判」未限定分支，与实现不符）。
> 之所以不用文本窗口：窗口会把**字符串字面量与文档样例**当调用（守卫曾因此自伤，
> 把自身源码里的 `"os.popen("` 字串判为违例）——AST 只认语法意义上的调用，无此缺陷。

自检：被检查的文本模式调用点低于 FLOOR 视为失败——防止「扫描范围意外为空 → 假绿」。
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys

FLOOR = 12          # 本仓文本模式子进程调用点的下限（低于它说明扫描面失效了）
SUB_FUNCS = {"run", "Popen", "check_output", "call", "check_call",
             "getoutput", "getstatusoutput"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# 生效条件：无入参；返回仓根下 git 跟踪的 .py 相对路径列表（git 不可用时返回 None，调用方据此跳过并说明）。
def _tracked_py() -> list[str] | None:
    try:
        r = subprocess.run(["git", "-C", ROOT, "ls-files", "*.py"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except OSError:
        return None
    if r.returncode != 0:
        return None
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


# 生效条件：v 为 ast 常量节点时按其布尔取反判定；非常量（变量/表达式）一律按 True 保守处理。
def _truthy(v: ast.AST | None) -> bool:
    if isinstance(v, ast.Constant):
        return bool(v.value)
    return True


class _Scanner(ast.NodeVisitor):
    """单文件扫描器：先收别名导入，再按 AST 调用节点判文本模式与 encoding 声明。"""

    def __init__(self, rel: str, bad: list[str]) -> None:
        self.rel = rel
        self.bad = bad
        self.sub_aliases: set[str] = set()
        self.func_aliases: dict[str, str] = {}
        self.checked = 0

    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            if a.name == "subprocess":
                self.sub_aliases.add(a.asname or "subprocess")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "subprocess":
            for a in node.names:
                if a.name in SUB_FUNCS:
                    self.func_aliases[a.asname or a.name] = a.name
        self.generic_visit(node)

    # 生效条件：node.func 为 subprocess.<func> / 别名 / os.popen 三种形态之一时返回 (kind, funcname)，否则 None。
    def _callee(self, node: ast.Call) -> tuple[str, str] | None:
        f = node.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            base = f.value.id
            if base in self.sub_aliases and f.attr in SUB_FUNCS:
                return ("subprocess", f.attr)
            if base == "os" and f.attr == "popen":
                return ("os", "popen")
        if isinstance(f, ast.Name) and f.id in self.func_aliases:
            return ("subprocess", self.func_aliases[f.id])
        return None

    # 生效条件：kws 为调用处关键字实参表；capture_output 为真或 stdout/stderr 取 PIPE 时返回 True（该调用确有管道）。
    @staticmethod
    def _piped(kws: dict[str, ast.AST]) -> bool:
        if "capture_output" in kws and _truthy(kws.get("capture_output")):
            return True
        for key in ("stdout", "stderr"):
            v = kws.get(key)
            if isinstance(v, ast.Attribute) and v.attr == "PIPE":
                return True
            if isinstance(v, ast.Name) and v.id == "PIPE":
                return True
        return False

    def visit_Call(self, node: ast.Call) -> None:
        callee = self._callee(node)
        if callee is not None:
            kind, fname = callee
            if kind == "os":
                self.bad.append("%s:%d: os.popen(...)（该 API 无法声明编码，"
                                "改用 subprocess.run）" % (self.rel, node.lineno))
            else:
                kws = {k.arg: k.value for k in node.keywords if k.arg is not None}
                has_star = any(k.arg is None for k in node.keywords)
                text_mode = ("encoding" in kws
                             or ("text" in kws and _truthy(kws.get("text")))
                             or ("universal_newlines" in kws
                                 and _truthy(kws.get("universal_newlines"))))
                if text_mode:
                    self.checked += 1
                    if "encoding" not in kws:
                        self.bad.append(
                            "%s:%d: subprocess.%s(...) 文本模式未声明 encoding="
                            % (self.rel, node.lineno, fname))
                elif has_star and self._piped(kws):
                    # **kwargs 透传且确有管道：口径不可判定（可能被调用方注入 text=True）→ 不合格。
                    # **kwargs 透传但无管道（输出落 DEVNULL/日志文件）不判——不经过解码器，无该缺陷面。
                    # 注意豁免**只管这一支**：显式 text=True 即使落 DEVNULL 也走上一支判违例（v15-7）。
                    self.bad.append(
                        "%s:%d: subprocess.%s(..., **kwargs) 无法确认编码口径，"
                        "须显式声明 encoding=" % (self.rel, node.lineno, fname))
        self.generic_visit(node)


# 生效条件：无入参；扫描 git 跟踪的 .py 返回 (违例列表, 受检文本模式调用点数, git 可用性)。
def scan() -> tuple[list[str], int, bool]:
    files = _tracked_py()
    if files is None:
        return [], 0, False
    bad: list[str] = []
    checked = 0
    for rel in files:
        path = os.path.join(ROOT, rel)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                src = fh.read()
        except OSError:
            continue
        try:
            tree = ast.parse(src, filename=rel)
        except SyntaxError:
            bad.append("%s:0: 语法错误，无法 AST 判定（守卫拒绝在未解析文件上放行）" % rel)
            continue
        sc = _Scanner(rel, bad)
        sc.visit(tree)
        checked += sc.checked
    return sorted(bad), checked, True


def main() -> int:
    bad, checked, git_ok = scan()
    if not git_ok:
        print("SKIP：git 不可用，无法枚举跟踪文件（本守卫需要 git）")
        return 0
    print("受检文本模式子进程调用点：%d（下限 %d）" % (checked, FLOOR))
    if bad:
        print("✖ 不合格的文本模式调用点 %d 处：" % len(bad))
        for b in bad:
            print("   ", b)
        print("修法：补 encoding=\"utf-8\", errors=\"replace\"（不依赖 locale）")
        return 1
    if checked < FLOOR:
        print("✖ 受检调用点 %d < 下限 %d——扫描面失效（文件枚举/判据坏了），"
              "不得视为通过" % (checked, FLOOR))
        return 1
    print("✔ 全部调用点均显式声明 encoding=（子进程文本解码不依赖 locale）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
