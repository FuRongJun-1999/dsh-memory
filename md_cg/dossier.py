# -*- coding: utf-8 -*-
"""人物档案（画像）抽取——按"公民档案"的结构，从会话里**增量补字段**。

判据（使用者 2026-11-12）：按中国公安/人社局的公民档案思路，做人物档案（人物画像），
在会话中不断补充。

字段分层（只用会话里**自然出现**的信息，不主动采集）：
  基本信息：姓名 · 别名 · 年龄 · 城市
  身份职业：职业 · 单位 · 学历 · 专业
  家庭关系：父 · 母 · 配偶 · 子女 · 兄弟姐妹（**带人名与职业**）
  偏好忌讳：口味 · 作息 · 忌讳（辅助检索）

**隐私边界（不做）**：身份证号、精确住址、电话、银行卡——即使出现也不入档。
档案字段只服务"回忆/检索"，不服务身份核验。

抽取全部确定性正则，不外接模型；抽不到就不写（宁缺不错）。
每条字段带 `t`（陈述时刻）与 `ev`（来源节点），可回溯、可被更新的值覆盖（旧值进 history）。
"""
from __future__ import annotations

import re

_NAME = r"[\u4e00-\u9fa5]{2,4}"

#: 字段 → 正则（第一人称/第三人称自称句）。
_RULES = (
    ("姓名", re.compile(r"(?:我叫|我的名字是|我名字叫|叫我)(" + _NAME + ")")),
    ("年龄", re.compile(r"(\d{1,2})\s*岁")),
    ("职业", re.compile(r"(?:我是|我在[^，。]{0,8}?做|干的是|做)(" + "|".join([
        "结构设计", "面包师", "烘焙", "调酒", "编辑", "护士", "会计", "设计", "老师",
        "销售", "程序员", "司机", "厨师", "医生", "学徒", "理货员", "钳工",
    ]) + r")")),
    ("单位", re.compile(r"在([\u4e00-\u9fa5]{2,10}?(?:店|馆|公司|学校|医院|厂|所|局))")),
    ("城市", re.compile(r"我(?:住在|住|在)([\u4e00-\u9fa5]{2,6}?(?:市|区|县|城))")),
    ("学历", re.compile(r"(本科|大专|硕士|研究生|博士|高中|中专|技校)")),
    ("专业", re.compile(r"([\u4e00-\u9fa5]{2,8})专业")),
    ("父", re.compile(r"我(?:爸|父亲)(?:原是|是|在)?([^，。]{2,12}?(?:钳工|工人|司机|老师|医生|退休|员工|职员))")),
    ("母", re.compile(r"我(?:妈|母亲)(?:原是|是|在)?([^，。]{2,12}?(?:理货员|工人|老师|医生|退休|员工|职员))")),
)

#: 明确 **不采** 的敏感字段（出现也忽略）。
FORBIDDEN = ("身份证", "证件号", "银行卡", "手机号", "电话", "详细住址", "门牌")


# 生效条件：text 为正文、ts 为陈述时刻（float）、nid 为来源节点；返回 {字段: {value,t,ev}}
def extract(text, ts=None, nid=""):
    """从一段正文里抽档案字段（确定性；抽不到不写）。"""
    body = str(text or "")
    if any(w in body for w in FORBIDDEN):
        # 命中敏感字样 ⇒ 整段不建档（不逐字段过滤，避免漏网）
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
    # 自我介绍里的裸数字也算年龄（语料常见「我叫沈知夏，知了的知，夏天的夏，24」——
    # 没有「岁」字）。只在**同段已认出姓名**时启用，避免把任意数字当年龄。
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


# 生效条件：old/new 为两条档案 dict；返回合并结果（新值覆盖；旧值进 history 不丢）
def merge(old, new):
    """档案增量合并：同字段取**较新**的值，旧值保留在 history。"""
    out = dict(old or {})
    hist = dict(out.get("_history") or {})
    for k, v in (new or {}).items():
        if k.startswith("_"):
            continue
        prev = out.get(k)
        if prev and prev.get("value") == v.get("value"):
            continue
        if prev:
            hist.setdefault(k, []).append(prev)
        out[k] = v
    if hist:
        out["_history"] = hist
    return out