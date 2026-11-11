# -*- coding: utf-8 -*-
"""写入时信息整理（LLM 填表 + **原文复核**）——规则对自然对话天生失效后的换代方案。

判据（使用者 2026-11-12）：
> 在记忆写入时用 LLM 做一个信息整理。因为规则对多变的自然对话天生失效。
> 我们用**表**做一个确定性内容让 LLM 填写。同时做**原文复核机制**，避免 LLM 的信息整理失误。

分工（本模块只做确定性那半）：
  · **表**（SCHEMA / table_text）：字段名、类型、取值范围由我们定死 —— LLM 只填值，不发明字段；
  · **复核**（verify）：每个填进去的值都必须在**原文里找得到**（归一化子串匹配），
    找不到 ⇒ 拒收（unverified），不进档案；
  · **落地**（apply）：只写通过复核的字段，并记 `ev_span`（原文里命中的片段）+ `ev_node` + `source`；
  · **调用**：LLM 由宿主提供（本模块**不自带模型**），传入 filled 字典即可。

为什么复核必须写死在数据面而不是提示词里：
  外测实证——纯规则会把「在包里」当城市；纯 LLM 则可能写出原文没有的值。
  「值必须在原文出现」是**可机械判定**的，不依赖模型自觉。

不适用条件：
  · 同义改写（原文「二十四」、LLM 填 24）会被判 unverified —— 这是**有意的保守**，
    宁可漏收也不放行（要放行请用别名/规范化表，而不是放松复核）；
  · 数值型字段（年龄）按字符串匹配 + 数值等值两种口径都试，仍失败即拒收。
"""
from __future__ import annotations

import re

#: 表的字段定义（**确定性**：字段名/类型/是否必填/提示语都由这里定）。
SCHEMA = (
    ("姓名", "str", False, "自称或全名，2–4 个汉字"),
    ("年龄", "int", False, "数字，语料常见无「岁」字"),
    ("城市", "str", False, "必须是**地名**（区/市/县/路/街/镇/州 之一，或明确城市名）"),
    ("职业", "str", False, "职业短语，如 全职带娃 / 晚班调酒师"),
    ("单位", "str", False, "工作地点/机构名"),
    ("学历", "str", False, "本科/大专/硕士/研究生/博士/高中/中专/技校"),
    ("专业", "str", False, "专业名"),
    ("父", "str", False, "父亲的名字或职业（原文出现的形式）"),
    ("母", "str", False, "母亲的名字或状况（原文出现的形式）"),
)

#: 允许的字段集合（LLM 填了表外字段 ⇒ 直接丢弃，不让它发明字段）。
FIELDS = tuple(f for f, _t, _r, _h in SCHEMA)


# 生效条件：无参；返回给 LLM 的确定性表模板（字段/类型/必填/提示）
def table_text():
    """生成「让 LLM 填」的表（纯文本，便于贴进提示词）。"""
    lines = ["字段 | 类型 | 必填 | 说明", "--- | --- | --- | ---"]
    for name, typ, req, hint in SCHEMA:
        lines.append("%s | %s | %s | %s" % (name, typ, "是" if req else "否", hint))
    lines.append("")
    lines.append("规则：只填原文**明确出现**的值；原文没有的字段填空字符串；"
                 "不要推断、不要补全、不要换算。")
    return "\n".join(lines)


# 生效条件：text 为原文；返回归一化文本（去空白，全角数字转半角）
def _norm(text):
    s = str(text or "")
    s = re.sub(r"\s+", "", s)
    s = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    return s


# 生效条件：value 为待核值、text 为原文；在原文中可命中（或数值等值）返回命中的片段，否则 None
def span_of(value, text):
    """**原文复核单点**：返回命中片段（用于 ev_span），命中不了返回 None。"""
    if value is None or value == "":
        return None
    nv = _norm(value)
    nt = _norm(text)
    if not nv or not nt:
        return None
    if nv in nt:
        return str(value)
    # 数值字段：24 vs 「24岁」「，24」——数值等值也算命中（但必须是原文的子串形式）
    if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
        if str(int(value)) in nt:
            return str(value)
    return None


# 生效条件：filled 为 LLM 填的表（dict）、text 为原文；返回 (accepted, rejected)
def verify(filled, text):
    """逐字段复核：命中保留并给 ev_span；未命中拒收并给原因。"""
    accepted, rejected = {}, []
    for k, v in (filled or {}).items():
        if k not in FIELDS:
            rejected.append({"field": k, "value": v, "reason": "field_not_in_schema"})
            continue
        if v is None or v == "":
            continue
        span = span_of(v, text)
        if span is None:
            rejected.append({"field": k, "value": v, "reason": "not_in_source"})
            continue
        accepted[k] = {"value": v, "ev_span": span}
    return accepted, rejected


# 生效条件：cg 提供 get；node_id 存在、filled 为 dict；返回 {applied, rejected, dossier}
def apply(cg, node_id, filled, text=None, ts=None, source="llm"):
    """把 LLM 填的表复核后并入档案。

    **不写盘**（无副作用）：返回合并后的 dossier，由调用方在正常写入路径里落盘
    （这样只走一条写链，避免第二套写入面）。
    """
    node = cg.get(node_id) or {}
    if not node:
        return {"ok": False, "error": "node_not_found", "node_id": node_id}
    body = text if text is not None else (node.get("content") or "")
    fm = node.get("frontmatter") or {}
    ts = ts if ts is not None else fm.get("created_at")
    accepted, rejected = verify(filled, body)
    if not accepted:
        return {"ok": True, "applied": {}, "rejected": rejected,
                "dossier": dict(fm.get("dossier") or {}),
                "note": "无可复核字段（全部拒收或空表）"}
    from . import dossier as _dos
    cur = dict(fm.get("dossier") or {})
    incoming = {k: {"value": v["value"], "t": ts, "ev": node_id,
                    "ev_span": v["ev_span"], "source": source}
                for k, v in accepted.items()}
    merged = _dos.merge(cur, incoming)
    return {"ok": True, "applied": accepted, "rejected": rejected, "dossier": merged}
