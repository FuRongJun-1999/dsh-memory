# -*- coding: utf-8 -*-
"""守卫 · issue #749 知识层准入（默认情景层 + 知识层劝告/可升级为强制降级）。

设计（两档，默认劝告）：
  · 劝告（默认）：显式 knowledge 但看起来不像知识 ⇒ 不改变写入，回执带 layer_warning（不静默）；
  · 强制（MDCG_KNOWLEDGE_GATE=enforce）：降级 contextual 并带 layer_downgraded；
  · LLM 主路径 mdcg_remember 的默认层本来就是 contextual（未声明时）。

为什么默认不改写：cg(op=write)/显式 knowledge 是专家面；默认篡改会改变冲突检测语义（#294 实测）。
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
             "结论：在引入新结构时，若不能自证降熵，则不应引入。\n")


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
    print("issue #749：知识层准入")
    print("=" * 70)

    os.environ.pop("MDCG_KNOWLEDGE_GATE", None)
    # 白箱口径三条硬判据（使用者 2026-11-13 口述：无英文 / 无数字 / 规则语法）
    _wb_ok = "在受力条件下，材料会发生塑性变形"
    ok(layer_gate.whitebox_reasons(_wb_ok) == [], "W1 纯中文 + 规则句 ⇒ 通过",
       layer_gate.whitebox_reasons(_wb_ok))
    _wb_en = "Load 条件下材料会变形"
    ok(any("英文" in x for x in layer_gate.whitebox_reasons(_wb_en)),
       "W2 含英文词 ⇒ 拒（并指明词）", layer_gate.whitebox_reasons(_wb_en))
    _wb_num = "在受力条件下材料会发生 3 类塑性变形"
    ok(any("数字" in x for x in layer_gate.whitebox_reasons(_wb_num)),
       "W3 含阿拉伯数字 ⇒ 拒（具体数值属情景）", layer_gate.whitebox_reasons(_wb_num))
    _wb_cmp = "道歉=认错+悔意+改正行动"
    ok(layer_gate.whitebox_reasons(_wb_cmp) == [],
       "W4 A=B+C 压缩句 ⇒ 视为规则语法（白箱知识综述的既有形态）",
       layer_gate.whitebox_reasons(_wb_cmp))
    _wb_plain = "他昨天买了本书"
    ok(any("规则语法" in x for x in layer_gate.whitebox_reasons(_wb_plain)),
       "W5 无规则句 ⇒ 拒（非学科通用内容）", layer_gate.whitebox_reasons(_wb_plain))

    ok(bool(layer_gate.judge(EPISODIC)[1]), "G1 情景句被判不入知识层（含原因）",
       layer_gate.judge(EPISODIC))
    ok(layer_gate.judge(KNOWLEDGE) == (True, []), "G2 合规知识放行",
       layer_gate.judge(KNOWLEDGE))

    g1, n1 = mcp_server._layer_gate_apply({"layer": "knowledge", "content": EPISODIC})
    ok(g1.get("layer") == "knowledge" and (n1 or {}).get("mode") == "advisory",
       "L1 默认劝告：不改 layer，只给 advisory 理由", (g1.get("layer"), n1))
    g2, n2 = mcp_server._layer_gate_apply({"layer": "knowledge", "content": KNOWLEDGE})
    ok(g2.get("layer") == "knowledge" and n2 is None, "L2 合规知识：无提示", (g2.get("layer"), n2))
    g3, n3 = mcp_server._layer_gate_apply({"layer": "contextual", "content": EPISODIC})
    ok(n3 is None, "L3 情景层：不干预")

    os.environ["MDCG_KNOWLEDGE_GATE"] = "enforce"
    g4, n4 = mcp_server._layer_gate_apply({"layer": "knowledge", "content": EPISODIC})
    ok(g4.get("layer") == "contextual" and (n4 or {}).get("mode") == "enforce",
       "L4 enforce 档：强制降级 contextual", (g4.get("layer"), n4))
    os.environ.pop("MDCG_KNOWLEDGE_GATE", None)

    cg = MdCGOS(tempfile.mkdtemp(prefix="i749_"), actor="test")
    r_k = mcp_server.call_tool(cg, "mdcg_remember",
                               {"content": KNOWLEDGE, "layer": "knowledge"})
    nid_k = (r_k or {}).get("node_id") or (r_k or {}).get("id")
    ok(bool(nid_k) and layer_of(cg, nid_k) == "knowledge",
       "K2 remember 合规知识落 knowledge", (r_k, nid_k))
    ok(not (r_k or {}).get("layer_warning"), "K2b 合规知识回执无 layer_warning")

    r_e = mcp_server.call_tool(cg, "mdcg_remember",
                               {"content": EPISODIC, "layer": "knowledge"})
    ok((r_e or {}).get("layer_warning", {}).get("mode") == "advisory",
       "K3 情景句 + knowledge ⇒ 回执带 layer_warning（不静默）", r_e)

    r_d = mcp_server.call_tool(cg, "mdcg_remember", {"content": KNOWLEDGE})
    nid_d = (r_d or {}).get("node_id") or (r_d or {}).get("id")
    ok(bool(nid_d) and layer_of(cg, nid_d) == "contextual",
       "K4 未声明 layer ⇒ 默认 contextual（LLM 主路径默认情景层）", (r_d, nid_d))

    os.environ["MDCG_KNOWLEDGE_GATE"] = "enforce"
    r_f = mcp_server.call_tool(cg, "mdcg_remember",
                               {"content": EPISODIC, "layer": "knowledge"})
    nid_f = (r_f or {}).get("node_id") or (r_f or {}).get("id")
    ok(bool(nid_f) and layer_of(cg, nid_f) == "contextual",
       "K5 enforce 档：情景句降到 contextual", (r_f, nid_f))
    os.environ.pop("MDCG_KNOWLEDGE_GATE", None)

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())