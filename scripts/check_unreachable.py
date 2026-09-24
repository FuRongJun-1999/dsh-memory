#!/usr/bin/env python3
"""全仓 unreachable 死代码扫描（批次 34，V21 报告流程建议）。

判据：控制流终止语句（return / raise / break / continue）之后，同一 block
内仍有后续语句 → 后继不可达。

能拦两族已发缺陷（报告定案）：
  · s5 负记忆覆盖段（批次 31：防御 continue 后整段缩进错位，检索抑制静默
    失效——test_retr_s5 8/17，两平台同红）；
  · V21-4 run_channel_b 主体（批次 26：沙箱段插入函数体内，主体落到
    return 之后——111 行 → 7 行，通道 B 整条流水线静默消失）。

生效条件：扫描 md_cg/scripts/hive/src（py 面）全部 .py；任一文件 ast.parse
失败计 FAIL（语法坏）；命中 unreachable 计 FAIL 并打印 文件:行(终止语句类型)
→ 后继行(类型)；零命中 PASS。排除 _pycache_/node_modules/.git。
"""
import ast
import sys
from pathlib import Path

TERMINALS = (ast.Return, ast.Raise, ast.Break, ast.Continue)
ROOTS = ("md_cg", "scripts", "hive", "src")
SKIP_DIRS = {"__pycache__", "node_modules", ".git", "target"}


def scan_block(body, path, hits):
    for i, stmt in enumerate(body[:-1]):          # 末语句无后继
        if isinstance(stmt, TERMINALS):
            nxt = body[i + 1]
            hits.append((path, stmt.lineno, type(stmt).__name__,
                         nxt.lineno, type(nxt).__name__))


def scan_tree(tree, path, hits):
    for node in ast.walk(tree):
        for attr in ("body", "orelse", "finalbody"):
            block = getattr(node, attr, None)
            if isinstance(block, list):
                scan_block(block, path, hits)


def main() -> int:
    hits, parse_fail = [], []
    count = 0
    for root in ROOTS:
        for p in Path(root).rglob("*.py"):
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            count += 1
            try:
                scan_tree(ast.parse(p.read_text(encoding="utf-8"), str(p)),
                          str(p), hits)
            except SyntaxError as e:
                parse_fail.append(f"{p}: {e}")
    for pf in parse_fail:
        print(f"[SYNTAX] {pf}")
    for path, l1, t1, l2, t2 in hits:
        print(f"[UNREACHABLE] {path}:{l1}({t1}) -> :{l2}({t2}) 后继不可达")
    print(f"unreachable 扫描：{count} 文件，命中 {len(hits)}，"
          f"语法失败 {len(parse_fail)}")
    return 1 if (hits or parse_fail) else 0


if __name__ == "__main__":
    sys.exit(main())
