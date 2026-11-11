# -*- coding: utf-8 -*-
"""人物档案（画像）抽取——按"公民档案"结构，从会话里**增量补字段**。

判据（使用者 2026-11-12）：按中国公安/人社局的公民档案思路做人物档案（人物画像），会话中不断补充。

字段：基本信息（姓名/年龄/城市）· 身份职业（职业/单位/学历/专业）· 家庭（父/母）。
每条带 {value, t(陈述时刻), ev(来源节点)}，可回溯；merge() 增量合并，旧值进 _history。

语料实证（外测提供的原句）：
    P01 #15  我叫沈知夏，知了的知，夏天的夏，24
    P12 #8   我叫罗杏子，今年38，在南宁，全职带娃，你叫我罗姐就行。
    P16 #1   …我叫祁野，25，在渝中区半坡酒馆做晚班调酒师。
    P17 #13  还没正经跟你说我名字。我叫谈书宁，谈是谈话的谈，书是书本的书…
    P17 #27  明天还得陪我爸谈国华去社区医院开降糖药

由此定下的五条形态（正则按此写，不按教科书）：
  ① 姓名后可能跟**拆字解释**（"谈是谈话的谈…"）⇒ 截断在分隔符前；
  ② 年龄**常常没有"岁"字**（"我叫X，24" / "今年38"）；
  ③ 城市**没有稳定后缀**（"在南宁" / "在渝中区"）⇒ 带行政区后缀 或 「在X，/。」；
  ④ 职业是「做<短语>」或「全职带娃」这类整体短语；
  ⑤ 父母两种形态：「我爸<人名>」与「我妈<状况>」——不硬把状况当人名。

**隐私边界（不做）**：身份证号、证件号、银行卡、手机号、详细住址——命中任一敏感字样则整段不建档。
档案只服务回忆与检索，不服务身份核验。
"""
from __future__ import annotations

import re

_RULES = (
    ("姓名", re.compile(r"(?:我叫|我的名字是|我名字叫|叫我)([\u4e00-\u9fa5]{2,4})(?=[，,。！!；;\s]|$)")),
    ("年龄", re.compile(r"今年(\d{1,2})(?!\d)|(\d{1,2})\s*岁")),
    ("城市", re.compile(r"我(?:住在|住|在)([\u4e00-\u9fa5]{2,6}?(?:市|区|县))"
                        r"|(?:我)?在([\u4e00-\u9fa5]{2,4})(?=[，,。])")),
    ("职业", re.compile(r"做([\u4e00-\u9fa5]{2,8}?(?:师|员|工|手|调酒|设计|护理))"
                        r"|(全职带娃|全职妈妈|全职爸爸)")),
    ("单位", re.compile(r"在([\u4e00-\u9fa5]{2,12}?(?:店|馆|公司|学校|医院|厂|所|局))"
                        r"(?:做|上班|工作)")),
    ("学历", re.compile(r"(本科|大专|硕士|研究生|博士|高中|中专|技校)")),
    ("专业", re.compile(r"([\u4e00-\u9fa5]{2,8})专业")),
    ("父", re.compile(r"我(?:爸|父亲)([\u4e00-\u9fa5]{2,4})(?=[去说来在陪嫌，,。])")),
    ("母", re.compile(r"我(?:妈|母亲)([^，,。；;]{2,12})")),
)

#: 明确 **不采** 的敏感字段（出现即整段拒收）。
FORBIDDEN = ("身份证", "证件号", "银行卡", "手机号", "电话", "详细住址", "门牌")


# 生效条件：text 为正文、ts 为陈述时刻（float）、nid 为来源节点；返回 {字段: {value, t, ev}}
def extract(text, ts=None, nid=""):
    """从一段正文里抽档案字段（确定性；抽不到不写）。"""
    body = str(text or "")
    if any(w in body for w in FORBIDDEN):
        return {}
    out = {}
    for field, rx in _RULES:
        for m in rx.finditer(body):
            grp = next((g for g in m.groups() if g), None)
            if not grp:
                continue
            val = grp.strip()
            if field == "年龄":
                try:
                    n = int(val)
                except ValueError:
                    continue
                if not (1 <= n <= 120):
                    continue
                val = n
            out[field] = {"value": val, "t": ts, "ev": nid}
            break
    # 自我介绍里的**裸数字**也算年龄（「我叫沈知夏，…，24」无「岁」字）。
    # 只在同段已认出姓名时启用，避免把任意数字当年龄。
    if "姓名" in out and "年龄" not in out:
        m2 = re.search(r"[，,]\s*(\d{1,2})\s*(?:[，,。]|$)", body)
        if m2:
            try:
                n2 = int(m2.group(1))
            except ValueError:
                n2 = None
            if n2 and 1 <= n2 <= 120:
                out["年龄"] = {"value": n2, "t": ts, "ev": nid}
    return out


#: 字段的时间可变性：只有这些字段允许「同权重下较新值覆盖」；其余同权重**保留旧值**。
#: 理由（外测实证）：多来源 dossier 合并时，弱证据曾把「姓名/城市」覆盖成错值。
TIME_VARYING = ("年龄",)


# 生效条件：text 为原文；返回该节点作为档案证据的**权重**（3=自我介绍/声明，2=行为句，1=泛提）
def weight_of(text):
    """证据权重：自我介绍最强；含「在/做/住」的行为句次之；其余最弱。"""
    body = str(text or "")
    if re.search(r"(我叫|我的名字是|我名字叫|叫我)[\u4e00-\u9fa5]{2,4}", body):
        return 3
    if re.search(r"(今年\d|\d{1,2}\s*岁|我(?:住在|住|在)|做[\u4e00-\u9fa5]{2,8})", body):
        return 2
    return 1


# 生效条件：old/new 为两条档案 dict；返回合并结果（新值覆盖；旧值进 _history 不丢）
def merge(old, new):
    """档案增量合并：同字段取**较新**的值，旧值保留在 _history。"""
    out = dict(old or {})
    hist = dict(out.get("_history") or {})
    for k, v in (new or {}).items():
        if k.startswith("_"):
            continue
        prev = out.get(k)
        if prev and prev.get("value") == v.get("value"):
            # 同值：仅抬高权重、补 ev_span（不新增历史）
            if (v.get("w") or 0) > (prev.get("w") or 0):
                prev["w"] = v["w"]
            continue
        if prev:
            _pw, _nw = (prev.get("w") or 0), (v.get("w") or 0)
            # 【证据权重】强证据胜；同权重时只有时间可变字段允许较新值覆盖，
            # 其余**保留旧值**——避免「在包里」这类弱证据盖掉自我介绍的姓名/城市。
            if _nw < _pw:
                hist.setdefault(k, []).append(v)
                continue
            if _nw == _pw and k not in TIME_VARYING:
                hist.setdefault(k, []).append(v)
                continue
            hist.setdefault(k, []).append(prev)
        out[k] = v
    if hist:
        out["_history"] = hist
    return out