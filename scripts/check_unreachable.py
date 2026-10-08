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
失败、或含非 UTF-8 字节（解码失败，N261）计 FAIL（语法坏）；命中 unreachable 计 FAIL 并打印 文件:行(终止语句类型)
→ 后继行(类型)；零命中 PASS。排除 _pycache_/node_modules/.git。
判据面 = 文件系统走查 ∩ **git 追踪面**：被 gitignore 的本地产物（如 `hive/jobs/`、
`md_cg/_md_cg_eval_*/` 运行态）不在 CI 干净克隆里，纳入即「本地红 / CI 绿」分裂；
git 不可用/非仓 ⇒ 打印 `[降级]` 并退化为原文件系统走查（读数须按降级看待）。
"""
import ast
import os
import subprocess
import sys
from pathlib import Path

TERMINALS = (ast.Return, ast.Raise, ast.Break, ast.Continue)
ROOTS = ("md_cg", "scripts", "hive", "src")
SKIP_DIRS = {"__pycache__", "node_modules", ".git", "target"}
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tracked_rels():
    """git 追踪面（仓根相对 · posix 分隔）集合；git 不可用/非仓 ⇒ None（调用方降级）。

    按「是否被 git 追踪」这个**性质**判，不逐个硬编码排除目录（`.tmp`/`hive/jobs`
    只是当前污染源；将来在扫描子树内新建任何 gitignore 目录都被同一判据挡住）。
    """
    try:
        proc = subprocess.run(["git", "-C", _REPO, "ls-files", "-z"],
                              capture_output=True, check=True)
    except Exception:                                  # noqa: BLE001 —— 兜底见下
        return None
    return {p.replace("\\", "/") for p in
            proc.stdout.decode("utf-8", "replace").split("\0") if p}


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
    tracked = _tracked_rels()
    if tracked is None:
        print("[降级] git 不可用：扫描面退化为文件系统走查"
              "（可能与 CI 干净克隆不一致）")
    for root in ROOTS:
        for p in Path(root).rglob("*.py"):
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            if tracked is not None and p.as_posix() not in tracked:
                continue                    # 非追踪件不入判据面
            count += 1
            try:
                scan_tree(ast.parse(p.read_text(encoding="utf-8"), str(p)),
                          str(p), hits)
            except (SyntaxError, UnicodeDecodeError) as e:  # N261：解码失败计 FAIL
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
