#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""R-403 / R-407 · 权限映射判据（scripts/check_permission_map.py）

【为什么有它】
审计 P0-1：`mcp_server._MDCG_TOOL_OP` 把 6 个**治理面**工具映射到粗粒度
`read` / `write`，而它们各自的 handler 在 `cg` 面需要专门的 op（`identity` /
`predict` / `causal` / `metacognition` / `whitebox` / `consistency` / `ingest`）。
后果是「工具面闸词弱于规范面」：收窄到 `ops=["read"]` 的可写令牌，走
`cg(op=identity)` 被拒、走 `mdcg_identity` **落盘成功**（实测有 PoC）。

注释里曾声称「`_op_require` 从 op_table 派生，所以结构上不再可写」——但
`_op_require` 对 op 名返回自身、对 `read`/`write` 也返回自身 ⇒ **派生是恒等函数**，
一个字节的保护力都没提供。R-407 把那 6 处改成了规范 op 词。

【判什么】
1. `_MDCG_TOOL_OP` 的每个值 ∈ `op_table._OP_TABLE` 的键 ∪ {read, write}
2. 值为 `read`/`write` 的工具必须在 `COARSE_OK` 里**逐条登记**（真读面 / 真写面），
   新增工具若映射粗粒度词 ⇒ 红 —— 强制人判断「它到底需要哪个 op」
3. 值为规范 op 词的，必须真的存在于 `_OP_TABLE`（防拼错）

【不判什么】
- 不判「映射值是否等于 handler 在 cg 面所需的 op」—— 那需要逐 handler 读代码，
  属人工裁定（审计 T3 的 38 行 op 表已给对照）。本判据只钉住「不许用粗粒度词
  悄悄盖住治理面」。

【退出码】0 = 合规；1 = 有违例；2 = 自身故障
【负控】把 `mdcg_identity` 改回 `"read"` ⇒ 它既不在 COARSE_OK 里、值又不是 op 词 ⇒ 必须红。
【报数三行】数 / 口径 / 反例 见 main() 末尾的打印。
"""
from __future__ import annotations

import argparse
import ast
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MCP = os.path.join(ROOT, "md_cg", "mcp_server.py")
OPT = os.path.join(ROOT, "md_cg", "op_table.py")

#: 允许映射到粗粒度 `read` / `write` 的工具（**真读面 / 真写面**，逐条给理由）。
#: 新增工具要进这张表，先回答「它的 handler 在 cg 面到底需要哪个 op」。
COARSE_OK = {
    # —— 真读面（只读，无副作用）——
    "mdcg_get": "按 id 取节点，只读",
    "mdcg_recall": "召回，只读",
    "mdcg_search": "检索，只读",
    "mdcg_health": "健康探针，只读",
    "mdcg_service_info": "服务自描述，只读（issue #578 已从 open 收窄到 read）",
    "mdcg_watermarks": "水位读取，只读",
    "mdcg_whoami": "身份自描述，只读",
    # —— 真写面（写的是普通节点，不需要治理 op）——
    "mdcg_remember": "普通节点写入，等价 cg(op=write)",
    "mdcg_reflect": "反思写入，等价 cg(op=write)",
    "mdcg_flywheel": "飞轮推进，等价 cg(op=write)",
    "mdcg_mine_fix_pairs": "修复对挖掘，等价 cg(op=write)",
    "mdcg_rejected": "负记忆写入，等价 cg(op=write)",
    "mdcg_unresolved": "未解问题写入，等价 cg(op=write)",
    "mdcg_propose": "入审核队列（不落节点），等价 cg(op=write)",
    # —— 库层另有第二闸兜住（审计 T3 已确认）——
    "mdcg_forget": "库层 _forget_admin 兜住，粗粒度可接受",
    "mdcg_restore": "库层 require_admin 兜住",
    "mdcg_review_decide": "库层 require_op(review) 兜住",
}


def _tool_op_map():
    tree = ast.parse(io.open(MCP, encoding="utf-8").read(), MCP)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_MDCG_TOOL_OP" for t in node.targets):
            out = {}
            for k, v in zip(node.value.keys, node.value.values):
                if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                    out[k.value] = v.value
            return out
    raise SystemExit("✗ 找不到 _MDCG_TOOL_OP")


def _op_keys():
    tree = ast.parse(io.open(OPT, encoding="utf-8").read(), OPT)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_OP_TABLE" for t in node.targets):
            return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    raise SystemExit("✗ 找不到 _OP_TABLE")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    mp = _tool_op_map()
    ops = _op_keys()
    BASE = {"read", "write"}

    bad = []
    coarse = []
    for name, word in sorted(mp.items()):
        if word in BASE:
            if name not in COARSE_OK:
                bad.append((name, word, "映射到粗粒度词但未在 COARSE_OK 里登记理由"))
            else:
                coarse.append(name)
        elif word not in ops:
            bad.append((name, word, "不是 op_table 里登记的 op 词（可能拼错）"))

    print("数：%d 个工具映射 / 规范 op 词 %d 个 / 粗粒度（已登记）%d 个 / **违例 %d**"
          % (len(mp), len(mp) - len(coarse), len(coarse), len(bad)))
    print("口径：值 ∈ _OP_TABLE ∪ {read,write}；粗粒度词必须在 COARSE_OK 里逐条登记；"
          "不判「映射值是否等于 handler 所需 op」（那要逐 handler 读代码，属人工裁定）")
    print("反例：把 `mdcg_identity` 改回 \"read\" ⇒ 未登记 + 值不是 op 词 ⇒ 必红；"
          "但若把它登记进 COARSE_OK，本判据会放行 —— **登记本身就是人的裁定动作**")

    if bad:
        print("\n✗ 违例（%d）：" % len(bad))
        for n, w, why in bad:
            print("   %-26s → %-14s %s" % (n, w, why))
    if not a.quiet:
        print("\n粗粒度但已登记（%d）：" % len(coarse))
        for n in coarse[:8]:
            print("   %-26s %s" % (n, COARSE_OK[n]))
    print("\n结果：%s" % ("PASS" if not bad else "FAIL（%d 处违例）" % len(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:                                   # noqa: BLE001
        print("✗ 自身故障：%s: %s" % (type(e).__name__, e))
        sys.exit(2)
