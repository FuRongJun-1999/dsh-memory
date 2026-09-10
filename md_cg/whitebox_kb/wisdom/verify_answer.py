# -*- coding: utf-8 -*-
"""verify_answer.py —— 回答三层自校验（v1.30 · 规范即机制）

仿 verify_code（代码 L1 结构 / L2 样例 / L3 边界），回答也要有验证：
  L1 结构：自然语言格式（非内部格式/整卡/无括号嵌套泄漏）
  L2 来源：来自条件路由图（带卡导航/条件空间 或 诚实边界/闲聊/情感）
  L3 边界：长度/终止符/无占位残留

任何回答出口必须过 verify_answer——写错会被拒绝（机制，非人肉）。
"""

import re

# 内部格式特征：知识卡整卡的标志性结构
_CARD_MARKERS = [
    (r"是『[^』]{1,12}』vs『[^』]{1,12}』的矛盾[——\-]", "矛盾句式"),
    (r"的真相：", "真相标记"),
    (r"——[^。]{0,10}（是", "括号嵌套展开"),
]
# 括号密度过高 = 内部格式（知识卡层级表示）
_PAREN_DENSITY = 0.08  # 每字括号数阈值（正常中文 >1.5%，内部格式 >>8%）
_MAX_LEN = 300         # 人话回答上限（整卡通常 900-1200 字）
_MIN_LEN = 2

# 合法出口类别（条件路由图规范）
LEGITIMATE_KINDS = {
    "knowledge":  "知识（条件路由图：人话+卡导航+条件空间）",
    "chitchat":   "闲聊（CHITCHAT 表）",
    "honest":     "诚实边界（拒绝/声明无把握）",
    "emotion":    "情感（情感仿真）",
    "memory":     "记忆（回忆）",
    "self":       "自省/自我",
    "trace":      "追溯（依据来源）",
    "role":       "角色",
    "perception": "感知",
    "code":       "代码",
    "task_llm":   "任务转 LLM",
    "llm":        "LLM 续答",
    "converge":   "搜索收敛",
}


def detect_card_format(text: str) -> str | None:
    """检测知识卡内部格式特征。命中返回特征名，否则 None。"""
    if not text:
        return "空回答"
    for pattern, name in _CARD_MARKERS:
        if re.search(pattern, text):
            return name
    # 括号密度（去标点后的（计数 / 总字数）
    parens = text.count("（")
    if parens >= 6 and parens / max(1, len(text)) > _PAREN_DENSITY:
        return f"括号密度过高（{parens}/{len(text)}）"
    return None


def verify_answer(reply: str, meta: dict | None = None) -> tuple[bool, list[str]]:
    """回答三层自校验。

    meta 可选字段：
      kind: 出口类别（knowledge/chitchat/honest/emotion/...）——L2 来源验证
      hits: 条件路由图 hits（knowledge 类要求非空）
      route: 路由标记（self/llm）
    """
    checks: list[str] = []
    ok = True

    # ---- L1 结构：自然语言格式 ----
    if not reply or len(reply.strip()) < _MIN_LEN:
        ok = False
        checks.append(f"✗ L1 空/过短回答")
        return ok, checks
    card = detect_card_format(reply)
    if card:
        ok = False
        checks.append(f"✗ L1 内部格式泄漏：{card}")
    # v1.44 修复（矛盾测试重测）：矛盾实践智慧回答（自律→即时奖励vs延迟
    # 满足、家务→公平感破裂）结构完整 320-500 字，300 字上限误伤。矛盾分析
    # 是手工精写语义确定内容（非整卡 900-1200 字污染）——上限放宽到 500，
    # 仍拦住整卡（900+ 字）。无需检测『矛盾』字样（回答可能不含该词）。
    if len(reply) > 500:
        ok = False
        checks.append(f"✗ L1 超长（{len(reply)}>500，疑似整卡）")
    else:
        checks.append(f"✓ L1 自然语言格式（{len(reply)}字）")

    # ---- L2 来源：出口类别合法 ----
    kind = (meta or {}).get("kind", "knowledge")
    if kind not in LEGITIMATE_KINDS:
        ok = False
        checks.append(f"✗ L2 未知出口类别：{kind}")
    elif kind == "knowledge":
        hits = (meta or {}).get("hits") or []
        if not hits:
            ok = False
            checks.append("✗ L2 knowledge 回答无 hits（未走条件路由图）")
        else:
            # 必须带卡导航或条件空间
            if "可以看「" not in reply and "（这条知识属于" not in reply:
                ok = False
                checks.append("✗ L2 knowledge 回答缺卡导航/条件空间")
            else:
                checks.append(f"✓ L2 条件路由图来源（{len(hits)} hits，带卡导航）")
    else:
        checks.append(f"✓ L2 出口类别 {kind}（{LEGITIMATE_KINDS.get(kind, '?')}）")

    # ---- L3 边界：终止符/占位残留 ----
    if "..." in reply and reply.count("...") > 2:
        ok = False
        checks.append("✗ L3 疑似截断（多处...）")
    if "TODO" in reply or "{fn}" in reply or "占位" in reply:
        ok = False
        checks.append("✗ L3 占位残留")
    if not ok and not checks:
        checks.append("✓ L3 边界通过")
    return ok, checks
