# -*- coding: utf-8 -*-
"""test_issue436_lexer_line_drift.py · 未闭合字符串不得吞换行（行号漂移守卫）

缺陷（#436）：`compiler/lexer.py` 的 `_read_string` 遇到 `\\n` 时先 `break`，
随后**无条件**执行「跳过结束引号」的 `pos += 1`，把换行当结束引号吃掉，
且 `self.line` 不自增 ⇒ 该行之后**所有** token 的行号系统性偏小，
失真量随未闭合字符串个数**线性累积**，错误定位指向错行。

判据（5 条）：
  A 双未闭合：第二条错误的行号必须是 4（真实行），不得是 3
  B 三连未闭合：`德` 的 token 行号必须是 4，不得是 1
  C 反向对照：全闭合 errors 为空，且 `德` 行号 == 2（不得因修复而漂移）
  D 单未闭合：其后 `德` 行号必须是 2，不得是 1

**子进程隔离**：变异改的是磁盘文件，而本进程若已 `import compiler.lexer`
⇒ 模块缓存会让变异"看不见"（假绿）。故探针一律跑在**新进程**里。

变异自证（`--mutate`）：每条变异必须**恰好点红**，否则判「假守卫」。
"""
import json
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LEXER = os.path.join(_REPO, "compiler", "lexer.py")

# 子进程探针：fresh import，输出 JSON
_CHILD = r'''
import json, os, sys
sys.path.insert(0, sys.argv[1])
from compiler.lexer import tokenize

def line_of(src, text):
    toks, _ = tokenize(src)
    for t in toks:
        if getattr(t, "value", None) == text:
            return t.line
    return None

out = {}
src_a = '\u9053 \u65b0\u8def\u5f84\n"\u7b2c\u4e00\u4e2a\u672a\u95ed\u5408\n\u5fb7 0.5\n"\u7b2c\u4e8c\u4e2a\u672a\u95ed\u5408\n\u6b62 0.2\n'
_la, ea = tokenize(src_a)
out["A"] = bool(ea) and len(ea) > 1 and ea[1].startswith("L4")
out["A_detail"] = ea

src_b = '"a\n"b\n"c\n\u5fb7 0.5\n'
out["B"] = line_of(src_b, "\u5fb7") == 4
out["B_detail"] = line_of(src_b, "\u5fb7")

src_c = '\u9053 \u65b0\u8def\u5f84\n\u5fb7 0.1\n\u6b62 0.2\n'
_lc, ec = tokenize(src_c)
out["C"] = (ec == []) and (line_of(src_c, "\u5fb7") == 2)
out["C_detail"] = [ec, line_of(src_c, "\u5fb7")]

src_d = '"\u672a\u95ed\u5408\n\u5fb7 0.5\n'
out["D"] = line_of(src_d, "\u5fb7") == 2
out["D_detail"] = line_of(src_d, "\u5fb7")

sys.stdout.write(json.dumps(out, ensure_ascii=False))
'''


def _probe():
    r = subprocess.run([sys.executable, "-X", "utf8", "-c", _CHILD, _REPO],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    try:
        return json.loads((r.stdout or "").strip().splitlines()[-1])
    except Exception:
        return {"_err": (r.stdout or "") + (r.stderr or "")}


_NAMES = {
    "A": "A 双未闭合·第二条错误行号=L4",
    "B": "B 三连未闭合·德 行号=4",
    "C": "C 反向·全闭合 errors 空 且 德 行号=2",
    "D": "D 单未闭合·德 行号=2",
}


def run(verbose=True):
    got = _probe()
    red = []
    for k in ("A", "B", "C", "D"):
        ok = bool(got.get(k))
        if not ok:
            red.append(_NAMES[k])
        if verbose:
            det = got.get(f"{k}_detail")
            print(f"  [{'PASS' if ok else 'FAIL'}] {_NAMES[k]}  · 实得 {det!r}")
    if "_err" in got and verbose:
        print(f"  [ERR] 探针失败：{got['_err'][:300]}")
    return red


_MUTS = [
    ("MUT-A 恢复「把换行当结束引号吃掉」",
     "        if not unterminated and self.pos < len(self.source):",
     "        if self.pos < len(self.source):"),
    ("MUT-B unterminated 恒 False（=修复前语义）",
     "                unterminated = True",
     "                unterminated = False"),
]


def main():
    if "--mutate" in sys.argv:
        return _mutate()
    print("未闭合字符串换行守卫（#436）：")
    red = run()
    print(f"\n===== {4 - len(red)}/4 通过 =====")
    if red:
        print("失败项：" + "; ".join(red))
    return 0 if not red else 1


def _mutate():
    src = open(LEXER, encoding="utf-8").read()
    bad = 0
    print("变异测试（每条必须恰好点红）：")
    for name, old, new in _MUTS:
        n = src.count(old)
        if n != 1:
            print(f"  {name}: 锚点命中 {n} 次（应为 1）——跳过")
            bad += 1
            continue
        open(LEXER, "w", encoding="utf-8", newline="\n").write(src.replace(old, new, 1))
        try:
            red = run(verbose=False)
        finally:
            open(LEXER, "w", encoding="utf-8", newline="\n").write(src)
        ok = bool(red)
        print(f"  {name}: {'点红 ✓' if ok else '未点红 ✗ 假守卫'}  (red={red})")
        if not ok:
            bad += 1
    print(f"\n===== {'全绿' if not bad else '失败：存在假守卫'} =====")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
