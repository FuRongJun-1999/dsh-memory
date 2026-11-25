# -*- coding: utf-8 -*-
"""覆盖缺口与认证位（issue #1005 第 2 条）。

问题：锚点没捞到、预算截断，recall 也会照常返回一个「看起来完整」的 pack，
调用方没有任何信号去说「我不确定」。

本模块只做**廉价的判读**：不额外检索、不读盘，只看装包结果自带的信号，
给出 gaps 与 certified。三条缺口码（闭集，issue #1005 原文）：

- anchor_missing：一条都没装进来（或装了但全是零分旁系）⇒ 本次检索没锚到东西
- budget_truncated：有条目因预算/超长被跳过，或在预算边界上被裁 ⇒ 材料被截短
- raw_not_included：pack 里有材料但**没有一条是原话轮次**（全是派生卡/摘要/状态卡）
  ⇒ 正是「卡进了 pack、源轮次没进」那种「答案缺原句」

certified = 三条都没有。**未认证不等于错**，只表示「该自己判断材料够不够」。
"""
from __future__ import annotations

import re

#: 派生条目的 id 前缀（情景层资料卡：profile-role / profile-event / ...）
DERIVED_PREFIXES = ("profile-",)

# ===== 槽位：触发词（query 侧）× 证据词（pack 侧）=====
# issue #1005（2026-11-24 测评端实测）：真实失败题是「我全名咋写」「爸妈退休前各干什么」这类
# **槽位型提问**——不含日期/数字/专名，所以实体级判据在 179 题上命中 0/179。
# 这里改为槽位级：query 命中某个槽位的触发词，就在 pack 正文里找该槽位的**证据词**；
# 找不到就报 `miss_slots`（**不是** coverage_gaps，不上调认证位——避免把语义改写误判成缺口）。
#
# 单一真源：`mdcos._profile_candidates` 的槽位卡注入也从这里取词表。
#: 三列：(槽位名, 触发词, 对应资料卡种类 role/place)——第三列供 mdcos 注入槽位卡用
SLOT_TRIGGERS = (
    ("姓名", ("全名", "名字", "姓名", "叫什么", "咋写"), "role"),
    ("家庭", ("爸妈", "父母", "家里", "家人", "父亲", "母亲"), "role"),
    ("职业", ("职业", "干什么", "做啥", "上班", "工作"), "role"),
    ("学历", ("学历", "上学", "读书", "毕业"), "role"),
    ("年龄", ("多大", "年龄", "几岁"), "role"),
    ("城市", ("城市", "住哪", "住在", "什么地方"), "place"),
)

#: 证据词（pack 侧）：出现任意一个，就认为该槽位有材料
SLOT_EVIDENCE = {
    "姓名": ("叫", "名字", "姓名", "全名"),
    "家庭": ("爸", "妈", "父母", "家里", "父亲", "母亲", "家人"),
    "职业": ("工作", "职业", "上班", "单位", "干", "做"),
    "学历": ("学", "毕业", "学历", "学校", "专业"),
    "年龄": ("岁", "年龄"),
    "城市": ("住", "城市", "地方", "区", "县"),
}
#: skipped 里属于「被预算裁掉」的 reason（其余 reason 是资格/摘录类，不算覆盖缺口）
BUDGET_REASONS = ("oversize_or_over_budget", "budget_exhausted")


def is_derived(entry) -> bool:
    """该条目是不是**派生**材料（档案/摘要/状态卡）而非原话轮次。"""
    if not isinstance(entry, dict):
        return True
    if str(entry.get("id") or "").startswith(DERIVED_PREFIXES):
        return True
    md = entry.get("metadata") or {}
    fm = entry.get("frontmatter") or {}
    for src in (md, fm):
        if src.get("derived_from") or src.get("derived_relation") or src.get("source"):
            return True
    return False


def _query_terms(query: str):
    """查询词成分：CJK 二元组 + 拉丁词（长度 >= 3）。用于「有没有锚到内容」这一步判读。"""
    q = (query or "").strip().casefold()
    if not q:
        return set()
    terms = set()
    for run in re.findall(r"[\u3400-\u9fff\uf900-\ufaff]+", q):
        if len(run) <= 2:
            terms.add(run)
        else:
            terms.update(run[i:i + 2] for i in range(len(run) - 1))
    for w in re.findall(r"[a-z0-9_]{3,}", q):
        terms.add(w)
    return terms


def _lexical_hit(items, query) -> bool:
    """pack 里有没有条目真的含查询词成分（廉价、只看已装好的正文）。"""
    terms = _query_terms(query)
    if not terms:
        return True                      # 无成分可判（空查询/纯符号）：不据此报缺口
    for e in items:
        body = str(e.get("content") or e.get("content_dated") or "").casefold()
        if not body:
            continue
        for term in terms:
            if term in body:
                return True
    return False


def gaps(pack, skipped=None, used=None, budget=None, extra=None,
         query=None, baseline=None):
    """返回 (gaps, certified)。gaps 形如 [{"code":..., "detail":...}]。

    query/baseline 用于判「锚点有没有真捞到」：RRF 给每个被召回条目一个单路基准分
    （1/(K+1)），所以**光看分数 > 0 不能证明锚到了**——一条查询完全不搭界的库也会
    返回一堆 1/61 量级的旁系。判据取两者合取：无查询词成分 **且** 最高分处于单路
    基准量级，才报 anchor_missing。
    """
    items = [e for e in (pack or []) if isinstance(e, dict)]
    out = []
    if not items:
        out.append({"code": "anchor_missing",
                    "detail": "pack 为空：本次检索没有装进任何条目"})
    else:
        scores = []
        for e in items:
            try:
                scores.append(float(e.get("score") or 0.0))
            except (TypeError, ValueError):
                continue
        _top = max(scores) if scores else 0.0
        if scores and _top <= 0.0:
            out.append({"code": "anchor_missing",
                        "detail": "pack 内全部条目得分 <= 0：只有词法旁系，没有可用锚点"})
        elif not _lexical_hit(items, query) and (
                baseline is None or _top <= float(baseline) * 1.0005):
            out.append({"code": "anchor_missing",
                        "detail": "pack 内无一条目含查询词成分，且最高分 %.6f 处于单路基准量级"
                                  "（可能只拿到旁系；回答前请自行核对是否答非所问）" % _top})
        if not any(not is_derived(e) for e in items):
            out.append({"code": "raw_not_included",
                        "detail": "pack 全是派生材料（档案/摘要/状态卡），没有原话轮次"})
    cut = [s for s in (skipped or [])
           if isinstance(s, dict) and str(s.get("reason") or "") in BUDGET_REASONS]
    if cut:
        out.append({"code": "budget_truncated",
                    "detail": "%d 条因预算/超长被跳过（例：%s）"
                              % (len(cut), str(cut[0].get("id") or "?")[:60])})
    elif (used is not None and budget is not None
          and float(budget) > 0 and float(used) >= float(budget)):
        out.append({"code": "budget_truncated",
                    "detail": "已用满预算（%s/%s），后续条目未装入" % (used, budget)})
    for extra_gap in (extra or []):
        if isinstance(extra_gap, dict) and extra_gap.get("code"):
            out.append(extra_gap)
    return out, not out


def slot_gaps(pack, query):
    """槽位级「这项没材料」信号（issue #1005，2026-11-24）。**独立于 coverage_gaps**。

    动机：测评端 27/27 道真实失败题都报 `coverage_certified=True`——现有 anchor_missing
    要求「无词面命中 **且** 分数贴基准」，而真实失败是「有少量词面重合、但必需要素缺失」，
    两个条件都不满足 ⇒ 这个信号在最该报警的地方从不报警。

    这里补的是**不同的问题**：不问「整体像不像答非所问」，只问「query 点名的那个槽位，
    pack 里有没有它的一丁点材料」。没有就如实说这一项没有——但**不升级为缺口、不动认证位**：
    槽位判断是弱信号，语义改写时容易误报，让它只做「我不确定」的提示。

    返回 [{"slot": 槽位名, "detail": 说明}]，无命中槽位或材料齐备时返回 []。
    """
    q = str(query or "")
    if not q:
        return []
    hit = [s for s, words, _k in SLOT_TRIGGERS if any(w in q for w in words)]
    if not hit:
        return []
    body = "\n".join(
        str((e or {}).get("content") or (e or {}).get("content_dated") or "")
        for e in (pack or []))
    if not body:
        return [{"slot": s, "detail": "pack 为空，没有「%s」这一项的材料" % s} for s in hit]
    out = []
    for slot in hit:
        ev = SLOT_EVIDENCE.get(slot) or ()
        if ev and not any(w in body for w in ev):
            out.append({"slot": slot,
                        "detail": "材料里没有「%s」这一项（回答前先说明这点不确定）" % slot})
    return out
