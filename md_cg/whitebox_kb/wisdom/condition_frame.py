# -*- coding: utf-8 -*-
"""灵枢 · 条件识别引擎（意图理解 = 反向七操作）

设计者洞察：「条件的识别，这就是意图理解。对条件论7种操作的反向使用。
从结果推原因，看是否成立。然后继续推进识别精度。」

统一框架：输入文本（结果）→ 条件结构解析（反向七操作）→ 验证器
→ ConditionFrame 输出（各通路消费）。

七操作反向映射：
  识别 ← 文本隐含条件空间（情绪/自我/知识/行动）
  分离 ← 复合句分离（转折/让步）
  逆转 ← 否定（条件取反）
  组合 ← 多条件并存
  筛选 ← 主导条件识别
  循环 ← 解读验证（递归检查自洽）

用法：
  cf = parse_conditions(text)   # 返回 ConditionFrame
  cf.dominant                   # 主导条件
"""
import sys

# 条件空间类型
SPACE_EMOTION = "情绪"
SPACE_SELF = "自我"
SPACE_KNOWLEDGE = "知识"
SPACE_ACTION = "行动"

# 转折结构词（条件边界标记）
TURN_STRONG = ["但是", "但", "不过", "然而", "可是", "却", "只是"]
TURN_CONCESSIVE = ["虽然", "尽管", "虽说", "即便", "即使", "哪怕"]

# 自我指向词（自省条件空间触发）
SELF_WORDS = ["你", "自己", "我", "我们"]

import re as _re


class ConditionFrame:
    """条件识别结果：文本 → 条件空间结构。"""

    def __init__(self, text, conditions=None, structure=None,
                 dominant=None, verified=False, fallback=None,
                 segments=None):
        """条件帧：文本片段 + 条件列表 + 结构标记 + 主方向 + 校验态（fallback 为降级文本）。"""
        self.text = text
        self.conditions = conditions or []   # [{space,type,evidence,role}]
        self.structure = structure            # concession/negative/direct/emotion/self/knowledge/none
        self.dominant = dominant              # 主导条件 type
        self.verified = verified              # 解读是否成立
        self.fallback = fallback              # 验证失败降级
        self.segments = segments or {}        # 原始分段 {pre, post}（消费端用）

    def to_dict(self):
        """序列化为摘要字典（text 截断至 40 字符防刷屏）。"""
        return {
            "text": self.text[:40],
            "conditions": self.conditions,
            "structure": self.structure,
            "dominant": self.dominant,
            "verified": self.verified,
            "fallback": self.fallback,
        }


def _split_turn(text):
    """分离复合条件（反向·分离操作）：返回 {structure, pre, post, turn_word} 或 None。"""
    msg = text.strip()
    # 让步：虽然 A，但 B
    for c in TURN_CONCESSIVE:
        if c in msg:
            idx = msg.find(c) + len(c)
            for t in TURN_STRONG:
                ti = msg.find(t, idx)
                if ti >= 0:
                    pre = msg[idx:ti].strip().strip("，,。 ")
                    post = msg[ti + len(t):].strip()
                    if post:
                        return {"structure": "concession", "pre": pre,
                                "post": post, "turn_word": t}
    # 直接转折：A，但 B
    for t in TURN_STRONG:
        if t in msg:
            idx = msg.find(t)
            pre = msg[:idx].strip().strip("，,。 ")
            post = msg[idx + len(t):].strip()
            if pre and post and len(post) >= 2:
                return {"structure": "direct", "pre": pre, "post": post,
                        "turn_word": t}
    # 否定转折：不是 A，是/而是 B
    m = _re.search(r'不是([^，。,.]{1,12})[，,]?(?:而是|就是|是)([^，。,.]{1,20})', msg)
    if m:
        return {"structure": "negative", "pre": m.group(1), "post": m.group(2),
                "turn_word": "而是"}
    return None


def _detect_emotion(text):
    """识别情绪条件空间（复用 chat_engine 语义情感检测）。"""
    try:
        from chat_engine import _detect_emotion_semantic
        r = _detect_emotion_semantic(text)
        if r:
            return {"space": SPACE_EMOTION, "type": r["label"],
                    "evidence": 0.8, "role": "条件"}
    except Exception:
        pass
    return None


def _detect_self(text):
    """识别自我指向条件空间（复用 chat_engine 自省分类）。"""
    if not any(w in text for w in SELF_WORDS):
        return None
    try:
        from chat_engine import _classify_self_topic
        topic = _classify_self_topic(text)
        if topic:
            return {"space": SPACE_SELF, "type": topic,
                    "evidence": 0.7, "role": "条件"}
    except Exception:
        pass
    return None


def parse_conditions(text):
    """主入口：文本 → ConditionFrame（反向七操作：分离→识别→组合→筛选→验证）。"""
    msg = (text or "").strip()
    if not msg:
        return ConditionFrame(text, structure="none", verified=False)

    # 1. 分离（反向·分离操作）：复合句 → 分段
    turn = _split_turn(msg)
    conditions = []

    if turn:
        # 2. 对每段做条件识别（反向·识别）
        pre_cond = _detect_emotion(turn["pre"]) or _detect_self(turn["pre"])
        post_cond = _detect_emotion(turn["post"]) or _detect_self(turn["post"]) \
            or {"space": SPACE_ACTION, "type": "意图",
                "evidence": 0.6, "role": "主导"}
        if pre_cond:
            pre_cond["role"] = "让步" if turn["structure"] == "concession" else "前置"
            conditions.append(pre_cond)
        if post_cond:
            post_cond["role"] = "主导"
            conditions.append(post_cond)
        structure = turn["structure"]
        dominant = post_cond["type"] if post_cond else None
        frame = ConditionFrame(text, conditions, structure, dominant,
                               verified=bool(conditions),
                               segments={"pre": turn["pre"], "post": turn["post"]})
    else:
        # 单条件：识别情绪/自我/知识
        emo = _detect_emotion(msg)
        if emo:
            conditions.append(emo)
            structure, dominant = "emotion", emo["type"]
            frame = ConditionFrame(text, conditions, structure, dominant,
                                   verified=True)
        else:
            self_c = _detect_self(msg)
            if self_c:
                conditions.append(self_c)
                structure, dominant = "self", self_c["type"]
                frame = ConditionFrame(text, conditions, structure, dominant,
                                       verified=True)
            else:
                # 默认：知识/行动条件（交给检索消费）
                conditions.append({"space": SPACE_KNOWLEDGE, "type": "知识查询",
                                   "evidence": 0.5, "role": "主导"})
                frame = ConditionFrame(text, conditions, "knowledge", "知识查询",
                                       verified=False)

    # 3. 验证（反向·循环操作）：解读自洽性
    frame.verified = _verify(frame)
    if not frame.verified:
        # 验证失败 → 降级：情绪解读不成立时，尝试自我/知识解读
        if frame.structure == "emotion":
            self_c = _detect_self(frame.text)
            if self_c:
                frame.structure = "self"
                frame.dominant = self_c["type"]
                frame.conditions = [self_c]
                frame.verified = True
            else:
                frame.structure = "knowledge"
                frame.dominant = "知识查询"
                frame.conditions = [{"space": SPACE_KNOWLEDGE,
                                     "type": "知识查询", "evidence": 0.5,
                                     "role": "主导"}]
                frame.verified = False
                frame.fallback = "情绪解读未通过验证，降级为知识查询"
        else:
            frame.fallback = "条件解读未通过验证，降级为通用回应"
    return frame


def _verify(frame):
    """验证解读是否成立（反向·循环操作）：条件与文本语义匹配。

    R2 升级：双通道验证——
      通道1 规则（主观信号/谈论 vs 表达）
      通道2 bge 语义（条件类型原型 vs 文本神经相似度）
    两通道都通过才 verified；任一不通过 → 降级换解。

    关键区分：『表达情绪』vs『谈论情绪/客观陈述』。
    - 「你觉得快乐是什么」是谈论情绪（问定义）→ 情绪解读不成立，转自我
    - 「今天天气不错」是客观陈述 → 情绪解读不成立
    """
    if frame.structure == "emotion":
        # 通道1：规则（主观信号 vs 谈论）
        # 主观信号：第一人称「我」或「描述自身状态的表达」（蔫了/提不起/转不动）
        subjective = any(w in frame.text for w in ["我好", "我", "感觉", "觉得",
                                                    "今天", "我有点", "我了",
                                                    "蔫", "提不起", "转不动",
                                                    "整个人", "都", "心里",
                                                    "胸口", "脑子"])
        # 直接情绪表达词（v1.16：无第一人称的感叹/自述也算主观——
        # 「太开心了！」「心情不好」没有「我」，但显然是情绪表达）
        direct_emo = any(w in frame.text for w in [
            "开心", "高兴", "兴奋", "快乐", "太好了", "太开心",
            "好累", "累了", "疲惫", "没劲", "躺平",
            "焦虑", "烦躁", "不安", "心慌", "紧张", "担心", "怕",
            "难过", "伤心", "想哭", "难受", "郁闷", "emo", "破防", "心情不好",
            "生气", "气死", "恼火", "愤怒",
            "孤独", "寂寞", "孤单", "没人陪",
            "心情", "情绪", "好难过", "好烦", "烦",
        ])
        talking = any(w in frame.text for w in ["什么是", "是什么", "你怎么",
                                                 "你觉得", "看起来",
                                                 "区别", "不同"])
        # v1.17 修复（三类专项测试）：「我今天气死我了」中「天气」是
        # 「今天」+「气死」的字面拼接误伤（'天'+'气' 恰好相邻）——
        # 「天气」从 talking 初始化移除，仅在下述确认词（真谈天气）时
        # 才视为 talking 信号，避免「今天气死我了」被误判成谈天气而
        # 否决情绪解读（生气 → 降级成知识查询 → 答天气）。
        if "天气" in frame.text and any(w in frame.text for w in
                                        ["下雨", "晴", "阴", "气温", "温度",
                                         "天气好", "天气真", "天气不错",
                                         "今天天气", "天气预报"]):
            talking = True
        if talking and not any(w in frame.text for w in ["我好", "我有点", "我特别"]):
            return False
        # 通道2：bge 语义——情绪原型 vs 文本神经相似度
        # v1.16：规则强信号（第一人称或直接情绪词）时不否决——
        # 词表/第一人称已高置信，「有点焦虑怕自己做不好」bge 可能 <0.45
        # 但规则已明确表达焦虑，不应降级成自省/知识。
        if subjective or direct_emo:
            return True
        return _emotion_sem_verify(frame.text, frame.dominant)
    if frame.structure in ("self", "knowledge"):
        return True
    if frame.structure in ("concession", "direct", "negative"):
        return bool(frame.dominant)
    return False


_EMO_VERIFY_CACHE = None


def _emotion_sem_verify(text, label):
    """bge 语义验证：文本与该情绪原型的神经相似度 ≥ 阈值。
    与 _detect_emotion_semantic 同源（复用 chat_engine 的原型）。"""
    global _EMO_VERIFY_CACHE
    try:
        import numpy as _np
        from chat_engine import EMOTION_PROTOTYPES, EMOTION_PROTO_LABELS
        from neural_retrieve import NeuralRetriever
        nr = NeuralRetriever()
        if _EMO_VERIFY_CACHE is None:
            _EMO_VERIFY_CACHE = {
                k: _np.mean([nr.embed(s) for s in v if nr.embed(s) is not None], axis=0)
                for k, v in EMOTION_PROTOTYPES.items()
                if any(nr.embed(s) is not None for s in v)
            }
        # label → 原型 key（EMOTION_PROTO_LABELS 映射 label→原型key）
        proto_key = None
        for pk, (lab, _pf) in EMOTION_PROTO_LABELS.items():
            if lab == label:
                proto_key = pk
                break
        if proto_key is None or proto_key not in _EMO_VERIFY_CACHE:
            return True  # 无原型 → 不否决（规则通道已判）
        vec = nr.embed(text)
        if vec is None:
            return True
        pv = _EMO_VERIFY_CACHE[proto_key]
        sim = float(_np.dot(vec, pv) / (
            _np.linalg.norm(vec) * _np.linalg.norm(pv) + 1e-9))
        return sim >= 0.45
    except Exception:
        return True  # bge 不可用 → 不否决（规则通道兜底）


# ---------------- 自测 ----------------
SELF_TEST = [
    "虽然累，但想学点东西",
    "我不是不想做，是不知道怎么开始",
    "我今天好累",
    "你觉得快乐是什么",
    "水为什么烧开",
    "今天天气不错",
]

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for t in SELF_TEST:
        f = parse_conditions(t)
        print(f"\n【{t}】")
        d = f.to_dict()
        print(f"  结构: {d['structure']} | 主导: {d['dominant']} | 成立: {d['verified']}")
        for c in d["conditions"]:
            print(f"    [{c['space']}] {c['type']} ({c['role']}, ev={c['evidence']})")
