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
