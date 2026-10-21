# -*- coding: utf-8 -*-
"""answer_spec_anchor.py —— 回答规范锚点层（v1.30 · 规范即机制）

把「条件路由图 + 自然语言编译」作为灵枢的自我锚点（SELF/ANCHOR 层，
no_forget 不可遗忘）：
  1. 每次初始化（Agent 创建）时强制写入锚点——自我层固定加载
  2. build_answer_spec_block() 生成可注入 LLM 的系统提示词块——LLM 续答
     时强制遵守同一套回答规范（条件路由图来源 + 自然语言编译 + 验证）
"""

# 回答规范锚点内容（自我层，不可遗忘）
ANSWER_SPEC_ANCHORS = [
    {
        "content": (
            "我（灵枢）的回答必须走条件路由图：先分析对话条件（_cond_analysis），"
            "依据条件切换到子功能（知识/闲聊/情感/诚实/记忆），知识回答必须来自"
            "graph_retrieve 四路融合的结果（人话+卡导航+条件空间），"
            "不得用关键词直查表（REVERSE_DAILY）绕过条件路由图。"
        ),
        "immutable": True,
    },
    {
        "content": (
            "我（灵枢）的回答必须经过自然语言编译：输出给人看的人话，"
            "不得泄漏知识库内部格式（整卡/括号嵌套/『A』vs『B』的矛盾句式/真相标记）。"
            "每条回答必须通过 verify_answer 三层校验（L1 自然语言格式/"
            "L2 条件路由图来源/L3 边界），未通过即拒绝输出并诚实声明。"
        ),
        "immutable": True,
    },
]

# LLM 系统提示词块（降级续答时强制注入）
ANSWER_SPEC_LLM_BLOCK = """【灵枢回答规范（强制）】
1. 条件路由图优先：先分析用户对话的条件，依据条件切换到子功能。知识类问题必须
   优先尝试白箱条件路由图（graph_retrieve 四路融合），而非直接生成。
2. 自然语言编译：输出必须是给人看的人话。禁止输出知识库内部格式——禁止出现
   「是『A』vs『B』的矛盾——」句式、括号嵌套（X（是…（…））、「真相：」标记。
3. 验证纪律：回答必须可追溯（可指出源自哪条知识、在什么条件下成立）；无把握时
   诚实声明，不编造。"""


def write_answer_spec_anchors(agent) -> dict:
    """把回答规范锚点写入 Agent 的自我层（幂等，已存在则跳过）。
    返回写入结果统计。"""
    written, skipped = 0, 0
    try:
        # 检查是否已存在（按内容前缀去重）——用 MemoryLayer.ANCHOR 枚举
        existing = set()
        try:
            from aeis_core import MemoryLayer as _ML
            nodes = agent.engine.store.query_nodes(layer=_ML.ANCHOR, limit=200)
            for n in nodes or []:
                c = (n.content or "")[:40]
                if c:
                    existing.add(c)
        except Exception:
            existing = set()
        for anchor in ANSWER_SPEC_ANCHORS:
            prefix = anchor["content"][:40]
            if prefix in existing:
                skipped += 1
                continue
            try:
                # 引擎 set_anchor → ANCHOR 层（不可遗忘，IMMUTABLE_LAYERS 保护）。
                # 注意：set_anchor 签名 (content, importance, condition_space)——
                # 无 immutable 参数（ANCHOR 层本身即不可遗忘）。
                agent.engine.set_anchor(
                    anchor["content"],
                    importance=1.0)
                written += 1
            except Exception:
                # 兜底：remember（知识层，带锚点标签）
                try:
                    agent.remember(anchor["content"], importance=1.0,
                                   tags=["锚点", "回答规范", "条件路由图", "自然语言编译"])
                    written += 1
                except Exception:
                    pass
    except Exception:
        pass
    return {"written": written, "skipped": skipped}


def build_answer_spec_block() -> str:
    """生成回答规范注入块（供每次对话/LLM 续答注入）。"""
    return ANSWER_SPEC_LLM_BLOCK
