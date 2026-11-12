# -*- coding: utf-8 -*-
"""实体抽取（确定性）——人物 / 地点 / 时间 核心；物品 / 情绪 辅助。

判据（使用者 2026-11-12）：人物·地点·时间·事件是**核心状态**，物品与情绪是**辅助**
（只用于辅助检索，不建跟踪树）。

本模块**不用模型**，全部确定性规则：
  · 人物：自我介绍式（我叫X／叫我X）、称谓式（X阿姨/师傅/姐/哥/老师/编辑）、
          对话式（X说／X问／和X约），以及已有 tags 里的 person: 前缀；
  · 地点：动词后接处所词干（在/去/到/回/从 + X店/馆/院/校/门口/小区/路/街…）；
  · 时间：先按绝对日期正则（YYYY-MM-DD、M月D日），再由调用方用 `reldate` 以陈述时刻换算相对表述；
  · 辅助（物品/情绪）：物品取引号内与「拿/借/寄/买/放」宾语；情绪取小词表。**只作为 facet**，不进状态树。

不适用条件（不猜）：
  · 两字以上才认人名（单字姓名歧义过大）；
  · 「我是X」不认（跟职业/身份混在一起，如「我是面包师」）；
  · 处所词必须命中词尾表，否则不认（宁缺不错）；
  · 本模块**不判断真假/归属关系**，只产出候选，去重与归属由 profiles 层做。
"""
from __future__ import annotations

import re

#: 人物称谓后缀（出现在名字之后）。
_HONORIFIC = ("阿姨", "叔叔", "师傅", "姐", "哥", "老师", "医生", "编辑", "编",
              "总", "老板", "园长", "经理")

#: 处所词尾（地点候选必须以此结尾）。
_PLACE_TAIL = ("店", "馆", "院", "校", "门口", "小区", "路", "街", "市", "省",
               "楼", "层", "公园", "书店", "医院", "学校", "咖啡店", "公司")

#: 情绪小词表（辅助面）。
_EMOTION = ("开心", "高兴", "难过", "累", "烦", "怕", "紧张", "委屈", "生气",
            "踏实", "欣慰", "焦虑", "轻松", "感动")

_NAME = r"[\u4e00-\u9fa5]{2,4}"
_SELF_INTRO = re.compile(r"(?:我叫|我叫作|叫我|名字叫)(" + _NAME + ")")
_HONOR = re.compile(r"([\u4e00-\u9fa5]{1,3})(?:" + "|".join(_HONORIFIC) + ")")
_SPEAK = re.compile(r"(" + _NAME + r")(?:说|讲|问|回|答|笑|提醒|建议)")
_WITH = re.compile(r"(?:和|跟|与)(" + _NAME + r")(?:说好|约|一起|商量|碰面)")
_PLACE = re.compile(r"(?:在|去|到|回|从|来)([\u4e00-\u9fa5]{1,10}?(?:" + "|".join(_PLACE_TAIL) + r"))")
_DATE = re.compile(r"(\d{4}-\d{2}-\d{2}|\d{4}/(\d{1,2})/(\d{1,2})|(\d{1,2})月(\d{1,2})[日号])")
_QUOTED = re.compile(r"[「『“\"]([^」』”\"]{1,20})[」』”\"]")
_OBJ_VERB = re.compile(r"(?:拿|借|寄|买|放|带|送|收)([\u4e00-\u9fa5]{1,8})")

#: 明显不是人名的词（动词/代词/常见名词），避免「他说」「我说」被当人名。
_NOT_NAME = {"他说", "我说", "你说", "她说", "他说", "告诉", "觉得", "知道",
             "今天", "昨天", "明天", "晚上", "上午", "下午", "那边", "这里",
             "我们", "你们", "他们", "自己", "大家", "有人", "别人"}


# 代词/泛称：绝不能当人名（外测实证：曾抽出 profile-person-号你）。
_PRONOUN = {
    "你", "我", "他", "她", "它", "您", "咱", "谁", "这", "那", "其",
    "你们", "我们", "他们", "她们", "它们", "咱们", "大家", "各位",
    "有人", "别人", "自己", "人家", "某人",
}

# 语气/助词：出现在姓名首或尾即判非人名（如「号你」「了吗」）。
_PARTICLE_CHARS = set(
    "了吗呢吧啊呀嘛哦哈欸诶啦咯喔噢得了着过地"
    "你您我他她它这那"
    "说问讲让把给和跟与在是有要就都也还什怎"
)


# 生效条件：name 为候选串；通过（非代词、长度 2-4、纯汉字、非语气助词首尾）返回 True
def gate_name(name):
    """人名闸：代词 / 长度 / 字符类 / 语气助词首尾 四道。宁缺不错。"""
    n = (name or "").strip()
    if not n or n in _PRONOUN or n in _NOT_NAME:
        return False
    if not (2 <= len(n) <= 4):
        return False
    if not all("\u4e00" <= ch <= "\u9fff" for ch in n):
        return False
    if n[0] in _PARTICLE_CHARS or n[-1] in _PARTICLE_CHARS:
        return False
    return True


# 生效条件：items 为候选串集合；返回去重后的有序列表（排除 _NOT_NAME 与空）
def _dedupe(items):
    seen, out = set(), []
    for x in items or []:
        x = (x or "").strip()
        if not x or x in seen or x in _NOT_NAME or len(x) < 2:
            continue
        seen.add(x)
        out.append(x)
    return out


# 生效条件：text 为正文、tags 为节点标签；返回人物候选（自我介绍/称谓/对话/和X约 + person: 标签）
def persons(text, tags=()):
    body = str(text or "")
    got = []
    got += [m.group(1) for m in _SELF_INTRO.finditer(body)]
    got += [m.group(1) for m in _HONOR.finditer(body)]
    got += [m.group(1) for m in _SPEAK.finditer(body)]
    got += [m.group(1) for m in _WITH.finditer(body)]
    for t in tags or []:
        t = str(t)
        for pre in ("person:", "人物:"):
            if t.startswith(pre):
                got.append(t[len(pre):])
    return [n for n in _dedupe(got) if gate_name(n)]


# 生效条件：text 为正文、tags 为节点标签；返回地点候选（动词 + 处所词尾；place: 标签）
def places(text, tags=()):
    body = str(text or "")
    got = [m.group(1) for m in _PLACE.finditer(body)]
    for t in tags or []:
        t = str(t)
        for pre in ("place:", "地点:"):
            if t.startswith(pre):
                got.append(t[len(pre):])
    return _dedupe(got)


# 生效条件：text 为正文；返回正文里出现的**绝对日期**原文串（相对表述由 reldate 另换算）
def dates(text):
    return _dedupe([m.group(0) for m in _DATE.finditer(str(text or ""))])


# 生效条件：text 为正文；返回辅助面 facet {"objects": [...], "emotions": [...]}（**不进状态树**）
def auxiliary(text):
    body = str(text or "")
    objs = [m.group(1) for m in _OBJ_VERB.finditer(body)]
    objs += [m.group(1) for m in _QUOTED.finditer(body)]
    emos = [w for w in _EMOTION if w in body]
    return {"objects": _dedupe(objs), "emotions": _dedupe(emos)}