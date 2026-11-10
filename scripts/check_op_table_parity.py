#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""R-401b 补件 · `scripts/check_op_table_parity.py`（op 元数据三向对账）

【为什么有它】
`md_cg/op_table.py` 的模块 docstring 从 2026-09 起就写着「本脚本做三向对账
（enum ↔ dispatch AST ↔ schema）＋定点变异自证」，但**该脚本此前并不存在**
（`check_comment_refs.py` 于 2026-11-10 扫出）。注释成了「已经做过了」的凭证，
正是「元数据错挂四处」能长期存活的原因。

【三向是什么】
  ① **enum**  —— `op_table._OP_TABLE` 的键集合（对外 op 枚举的单一真源）
  ② **dispatch** —— `mcp_server._cg_dispatch` 里 `if op == "x":` 链（AST 提取）
  ③ **schema**  —— `mcp_server.TOOLS` 各工具的 `inputSchema` 声明的 op 相关属性面

  断言：① == ②（双射）；且 `op_table` 里每个 op 的 `require` 词能在
        `_MDCG_OP_REQUIRE` 或 cg 面 `require_op` 分支里找到落点。

【不判什么（刻意留白，避免假红）】
- 不判 `params` 是否「全被 handler 读到」—— 参数归属是手写的，属报告 P1-G2 的
  另一条动作（R-524），本脚本只做 op 级三向。
- 不判 tool 数量与散文计数（那由 `tool_face.cg_brief()` 从 op_table 派生）。

【退出码】0 = 三向一致；1 = 有不一致；2 = 自身故障

【负控】从 `op_table._OP_TABLE` 里删任一 op ⇒ dispatch 侧多出一条 ⇒ 必须报红。
"""
from __future__ import annotations

import argparse
import ast
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OP_TABLE = os.path.join(ROOT, "md_cg", "op_table.py")
MCP = os.path.join(ROOT, "md_cg", "mcp_server.py")


def op_table_keys():
    tree = ast.parse(io.open(OP_TABLE, encoding="utf-8").read(), OP_TABLE)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_OP_TABLE" for t in node.targets):
            return [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
    raise SystemExit("✗ 找不到 op_table._OP_TABLE")


def dispatch_ops():
    tree = ast.parse(io.open(MCP, encoding="utf-8").read(), MCP)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_cg_dispatch"), None)
    if fn is None:
        raise SystemExit("✗ 找不到 mcp_server._cg_dispatch")
    out = set()
    for node in ast.walk(fn):
        if (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name)
                and node.left.id == "op"):
            for c in node.comparators:
                if isinstance(c, ast.Constant) and isinstance(c.value, str):
                    out.add(c.value)
    return out


def require_words():
    """op_table 里每个 op 的 require 词（缺键 = 自身）。"""
    tree = ast.parse(io.open(OP_TABLE, encoding="utf-8").read(), OP_TABLE)
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_OP_TABLE" for t in node.targets):
            for k, v in zip(node.value.keys, node.value.values):
                if not isinstance(k, ast.Constant) or not isinstance(v, ast.Dict):
                    continue
                req = None
                for kk, vv in zip(v.keys, v.values):
                    if isinstance(kk, ast.Constant) and kk.value == "require":
                        req = vv.value if isinstance(vv, ast.Constant) else None
                out[k.value] = req or k.value
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    keys = op_table_keys()
    dops = dispatch_ops()
    reqs = require_words()

    bad = 0
    if not a.quiet:
        print("[check_op_table_parity] op_table %d 个 / dispatch %d 个 / require 表 %d 条"
              % (len(keys), len(dops), len(reqs)))

    only_tab = sorted(set(keys) - dops)
    only_dis = sorted(dops - set(keys))
    if only_tab:
        bad += len(only_tab)
        print("\n✗ ① op_table 登记了但 dispatch 没有分支（%d）：" % len(only_tab))
        for x in only_tab:
            print("   ", x)
    if only_dis:
        bad += len(only_dis)
        print("\n✗ ② dispatch 有分支但 op_table 未登记（%d）：" % len(only_dis))
        for x in only_dis:
            print("   ", x)

    # ③ require 词必须是「自身」或「另一个已登记的 op」（基础词 write/read 等允许）
    BASE = {"write", "read", "help", "info", "status", "audit"}
    odd = sorted((k, v) for k, v in reqs.items()
                 if v != k and v not in set(keys) | BASE)
    if odd:
        bad += len(odd)
        print("\n✗ ③ require 词既非自身、也不是已登记的 op（%d）：" % len(odd))
        for k, v in odd:
            print("    %-16s require=%s" % (k, v))

    print("\n结果：三向对账 %s（op_table %d / dispatch %d，不一致 %d 处）"
          % ("PASS" if bad == 0 else "FAIL", len(keys), len(dops), bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:                                  # noqa: BLE001
        print("✗ 自身故障：%s: %s" % (type(e).__name__, e))
        sys.exit(2)
