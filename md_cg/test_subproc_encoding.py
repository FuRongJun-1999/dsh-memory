# -*- coding: utf-8 -*-
"""test_subproc_encoding.py · 子进程**文本解码口径**的机械守卫（第15条纪律的守卫面）

现场（2026-09-20 取证）：桥的子进程被注入 `PYTHONIOENCODING=utf-8`，其**后代**因此往
管道写 UTF-8；但后代读 `subprocess.run(..., text=True)` 时默认 text 编码取自 locale
（Windows=cp936），两侧口径不一致 → 读线程崩死、子进程诊断静默丢失：

    Exception in thread Thread-N (_readerthread):
    UnicodeDecodeError: 'gbk' codec can't decode byte 0x82 in position 181

两道防线（本守卫管第二道）：
  ① 运行期：桥子进程一律以 `PYTHONUTF8=1` 启动（PEP 540，默认 text 编码=utf-8）；
     见 `src/lib/mdcg_client.ts` 的 `mdcgChildEnv()` 与 `test/python-utf8-mode.test.ts`。
  ② 源码：**任何**文本模式子进程读取都必须显式声明 `encoding=`（配 `errors=`），
     不依赖 locale——脚本/工具也可能被非桥路径启动，那时没有 ① 的保护。

判据：git 跟踪的 .py 文件中，文本模式子进程调用块内未出现 `encoding=` 即违例。
· 文本模式 = `text=True` / `universal_newlines` / `encoding=` / `os.popen`（后者无法声明编码 → 直接违例）。
· 非文本模式（返回 bytes，如 `capture_output=True` 不带 text）与无管道 Popen（DEVNULL）不在此列——
  它们不经过解码器，不存在该缺陷面。

自检：被检查的调用点数低于 FLOOR 视为失败——防止「扫描范围意外为空 → 假绿」。
"""
from __future__ import annotations

import os
import subprocess
import sys

FLOOR = 12          # 本仓文本模式子进程调用点的下限（低于它说明扫描面失效了）
MAX_BLOCK = 25      # 单个调用块的最大行数（括号配平上限）

STARTS = ("subprocess.run(", "subprocess.Popen(", "subprocess.check_output(",
          "subprocess.call(", "subprocess.check_call(", "subprocess.getoutput(",
          "subprocess.getstatusoutput(")
TEXT_MARKERS = ("text=True", "universal_newlines")
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


# 生效条件：lines 为源文件行列表、i 为调用起始行下标；返回从 i 起按括号配平的调用块（最长 MAX_BLOCK 行）。
def _call_block(lines: list[str], i: int) -> str:
    chunk, depth, started = [], 0, False
    for j in range(i, min(len(lines), i + MAX_BLOCK)):
        chunk.append(lines[j])
        depth += lines[j].count("(") - lines[j].count(")")
        if "(" in lines[j]:
            started = True
        if started and depth <= 0:
            break
    return "\n".join(chunk)


# 生效条件：无入参；扫描 git 跟踪的 .py 返回 (违例列表, 受检调用点数, git 可用性)，违例项为 "路径:行号: 首行"。
def scan() -> tuple[list[str], int, bool]:
    files = _tracked_py()
    if files is None:
        return [], 0, False
    bad, checked = [], 0
    for rel in files:
        path = os.path.join(ROOT, rel)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            os_popen = "os.popen(" in line
            if not os_popen and not any(s in line for s in STARTS):
                continue
            block = _call_block(lines, i)
            if os_popen:
                bad.append("%s:%d: %s（os.popen 无法声明编码，改用 subprocess.run）"
                           % (rel, i + 1, line.strip()[:70]))
                continue
            if not (any(m in block for m in TEXT_MARKERS) or "encoding=" in block):
                continue                      # 非文本模式：不经过解码器
            checked += 1
            if "encoding=" not in block:
                bad.append("%s:%d: %s" % (rel, i + 1, line.strip()[:90]))
    return sorted(bad), checked, True


def main() -> int:
    bad, checked, git_ok = scan()
    if not git_ok:
        print("SKIP：git 不可用，无法枚举跟踪文件（本守卫需要 git）")
        return 0
    print("受检文本模式子进程调用点：%d（下限 %d）" % (checked, FLOOR))
    if bad:
        print("✖ 未声明 encoding= 的文本模式调用点 %d 处：" % len(bad))
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
