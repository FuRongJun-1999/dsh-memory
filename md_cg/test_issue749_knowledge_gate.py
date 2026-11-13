# -*- coding: utf-8 -*-
"""守卫 · issue #749 知识层准入（默认情景层；知识层要过闸）。

使用者裁定（2026-11-13）：LLM 默认把该写情景层的内容写进知识层；知识层必须是
重要的/结论性的/理论的/可验证的/通用的内容。

判据（确定性）：① CCG 六要素齐备；② 无相对时间指代；③ 非即时状态句。
不通过 ⇒ 降级 contextual 并在回执带 layer_downgraded（不静默）；force_layer=true 越过。

注意：cg(op=write) 走审核队列（节点不立即落盘），故落盘断言走 mdcg_remember；
「默认层/降级」的判据面用闸函数本身（_layer_gate_apply）的单点测试。
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import layer_gate, mcp_server  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

FAILS = []
EPISODIC = "今天加班到十点，路上还下雨，累"
KNOWLEDGE = ("# 功能名：降熵定理\n# 生效条件：系统引入新结构时\n# 子功能：判定新结构是否降低熵\n"
             "# 执行：比较结构引入前后的熵\n# 验证方式：可复算的熵差\n# 不适用条件：无结构变更\n\n"
             "结论：新结构必须自证降熵，否则不应引入。\n")


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:170])
        FAILS.append(name)


def layer_of(cg, nid):
    node = cg.get(nid) or {}
    path = str(node.get("path") or "")
    if path:
        return path.split("/")[0]
    return (node.get("frontmatter") or {}).get("layer")


def main():
    print("=" * 70)
    print("issue #749：知识层准入闸")
    print("=" * 70)

    ok(bool(layer_gate.judge(EPISODIC)[1]), "G1 情景句被判不入知识层（含原因）",
       layer_gate.judge(EPISODIC))
    ok(layer_gate.judge(KNOWLEDGE) == (True, []), "G2 合规知识放行",
       layer_gate.judge(KNOWLEDGE))

    g1, n1 = mcp_server._layer_gate_apply({"layer": "knowledge", "content": EPISODIC})
    ok(g1.get("layer") == "contextual" and bool(n1),
       "L1 闸：情景句+knowledge ⇒ 降级并给原因", (g1.get("layer"), n1))
    g2, n2 = mcp_server._layer_gate_apply({"layer": "knowledge", "content": KNOWLEDGE})
    ok(g2.get("layer") == "knowledge" and n2 is None,
       "L2 闸：合规知识放行（不改层）", (g2.get("layer"), n2))
    g3, n3 = mcp_server._layer_gate_apply({"layer": "contextual", "content": EPISODIC})
    ok(g3.get("layer") == "contextual" and n3 is None, "L3 闸：情景层原样放行（不干预）")
    g4, n4 = mcp_server._layer_gate_apply({"layer": "knowledge", "content": EPISODIC,
                                           "force_layer": True})
    ok(g4.get("layer") == "knowledge" and n4 is None, "L4 闸：force_layer 越过（显式）")

    cg = MdCGOS(tempfile.mkdtemp(prefix="i749_"), actor="test")

    r_k = mcp_server.call_tool(cg, "mdcg_remember",
                               {"content": KNOWLEDGE, "layer": "knowledge"})
    nid_k = (r_k or {}).get("node_id") or (r_k or {}).get("id")
    ok(bool(nid_k) and layer_of(cg, nid_k) == "knowledge",
       "K2 remember 合规知识落 knowledge", (r_k, nid_k))

    r_e = mcp_server.call_tool(cg, "mdcg_remember",
                               {"content": EPISODIC, "layer": "knowledge"})
    nid_e = (r_e or {}).get("node_id") or (r_e or {}).get("id")
    ok(bool(nid_e) and layer_of(cg, nid_e) == "contextual",
       "K3 remember 情景句 + knowledge ⇒ 降级 contextual", (r_e, nid_e))

    r_d = mcp_server.call_tool(cg, "mdcg_remember", {"content": KNOWLEDGE})
    nid_d = (r_d or {}).get("node_id") or (r_d or {}).get("id")
    ok(bool(nid_d) and layer_of(cg, nid_d) == "contextual",
       "K4 未声明 layer ⇒ 默认 contextual", (r_d, nid_d))

    r1 = mcp_server.call_tool(cg, "cg", {"op": "write", "node_id": "k1",
                                             "content": EPISODIC, "layer": "knowledge"})
    ok(isinstance(r1, dict) and bool(r1.get("layer_downgraded")),
       "K5 工具面 write 降级回执带 layer_downgraded（不静默）", r1)

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())