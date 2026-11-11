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
    # 【外测 2026-11-12】档案不能只是当前身份快照——这 19 题要的是经历/家庭**序列**。
    ("经历", "list", False, "职业经历序列，每项 {单位, 职位, 从, 到}；原文只给部分就只填部分"),
    ("家庭", "list", False, "家庭成员序列，每项 {关系, 姓名, 职业}"),
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


#: 关系词别名（**只对「家庭」项的「关系」分量**生效）：LLM 惯写「母/父」，语料多写「妈/爸」。
#: 这是**确定性白名单**，不是放松复核——白名单外的写法仍然拒收。
RELATION_ALIASES = {
    "母": ("妈妈", "妈", "母亲", "老娘"),
    "父": ("爸爸", "爸", "父亲", "老爷子"),
    "妻": ("妻子", "老婆", "媳妇"),
    "夫": ("丈夫", "老公"),
    "子": ("儿子",),
    "女": ("女儿",),
    "兄": ("哥哥", "哥"),
    "姐": ("姐姐", "姐"),
}


# 生效条件：k 为分量名、v 为值、text 为原文；命中（含关系白名单）返回 True
def _part_in_source(k, v, text):
    """分量复核：普通分量走 span_of；「关系」分量额外接受别名白名单。"""
    if span_of(v, text) is not None:
        return True
    if k == "关系":
        for alias in RELATION_ALIASES.get(str(v), ()):
            if span_of(alias, text) is not None:
                return True
    return False


#: 地名后缀（值必须带其一，或在已知地名词典里）。
PLACE_SUFFIX = ("市", "区", "县", "路", "街", "镇", "州", "村", "岛", "港")
#: 已知地名（可扩展；用于「南宁」「江北」这类无后缀写法）。
PLACE_KNOWN = ("南宁", "江北", "渝中", "半坡", "江北市", "渝中区")


# 生效条件：v 为城市候选值；形如地名（后缀命中或词典命中）返回 True
def is_place(v):
    """城市值校验：挡「外出包里 / 包里 / 家里」这类方位短语。"""
    s = str(v or "").strip()
    if not s:
        return False
    if any(s.endswith(x) for x in PLACE_SUFFIX):
        return True
    return any(x in s for x in PLACE_KNOWN)


# 生效条件：item 为表项（dict，可能含 _raw）；text 为原文；返回证据片段或 None
def _evidence_of(item, text):
    """取证据片段：优先用调用方给的 _raw（原文摘录），否则返回 None。

    为什么必须支持 _raw（外测 502 次填表：947 次 no_item_in_source）：
      LLM 会把「做过一年学徒」归一成 职位=学徒、「江北那家咖啡店」写成 单位=江北咖啡店——
      值对、字面不同。按值做子串匹配必然失败，按**证据片段**匹配应当通过。
      复核对象 = 证据（必须真的出现在原文），而不是归一化后的值：既保住防幻觉
      （_raw 不在原文 ⇒ 拒收），又不逼 LLM 逐字复制。
    """
    raw = (item or {}).get("_raw") if isinstance(item, dict) else None
    if raw:
        return str(raw) if span_of(raw, text) is not None else None
    return None

# 生效条件：filled 为 LLM 填的表（dict）、text 为原文；返回 (accepted, rejected)
def verify(filled, text):
    from . import dossier as _dos
    """逐字段复核：命中保留并给 ev_span；未命中拒收并给原因。"""
    accepted, rejected = {}, []
    for k, v in (filled or {}).items():
        if k not in FIELDS:
            rejected.append({"field": k, "value": v, "reason": "field_not_in_schema"})
            continue
        if v is None or v == "":
            continue
        # 【序列型】逐项复核：每项的字符串分量都要能在原文找到，否则丢该项
        if k in _dos.LIST_FIELDS and isinstance(v, list):
            _kept = []
            for _it in v:
                if not isinstance(_it, dict):
                    continue
                # 【B 方案】项自带 _raw 原文片段且能在原文找到 ⇒ 接受该项（结构化改写允许）
                _raw = _it.get("_raw")
                if isinstance(_raw, str) and _raw.strip() and span_of(_raw, text) is not None:
                    _kept.append(_it)
                    continue
                _item_raw = _it.get("_raw")
                if _item_raw:
                    _ok_item = span_of(_item_raw, text) is not None
                else:
                    _ok_item = all(_part_in_source(_k2, x, text)
                                   for _k2, x in _it.items()
                                   if x not in (None, "") and _k2 != "_raw")
                if _ok_item:
                    _kept.append(_it)
            if not _kept:
                rejected.append({"field": k, "value": v, "reason": "no_item_in_source"})
                continue
            accepted[k] = {"value": _kept, "ev_span": ""}
            continue
        _val = v.get("value") if isinstance(v, dict) else v
        _raw_span = _evidence_of(v, text)
        span = _raw_span or span_of(_val, text)
        if span is None:
            rejected.append({"field": k, "value": _val, "reason": "not_in_source"})
            continue
        # 字段级形态校验（目前只对城市）：原文有 ≠ 是地名
        if k == "城市" and not is_place(_val):
            rejected.append({"field": k, "value": _val, "reason": "not_a_place"})
            continue
        accepted[k] = {"value": _val, "ev_span": span}
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
