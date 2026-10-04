# -*- coding: utf-8 -*-
"""幽灵引用检查器（A2 落地）：短语层标记 + id 层降级告警——**只标记、不拒收**。

背景（多主体世界模型对齐 v0.1 §2 L1「转引不得升级」）：CD-WHALE-01（鲸娘语料
731 轮）发现 C 的现实形态是**自然语言回指**（「上次的香薰蜡烛」「明明讲过的那
件事」）——被引对象在库里没有任何记录，引用悬空且无任何防线（探针读数：
短语层零痕迹、id 层「目标晚于自身」零告警）。本模块补两条**标记级**防线：

  ① 短语层：正文以回指短语（「上次的」「之前说的」「明明讲过」）指代一个
     在句内**无可解析出处**（句内无库内 id）的对象时，产出幽灵引用短语清单
     ——写入链把它落 `fm.uncertain_refs` 并在出口告警；**不拒收**（回指是
     现实写作的常态，拒收会把正常记忆挡在门外；标记让「不确定」可被后续
     裁决与检索看见）。
  ② id 层：正文引用了一个库内目标，但本文档声明的生效起点（valid_from /
     effective_from）**早于**目标创建时刻——「引用了当时尚不存在的目标」。
     产出 late_refs 告警清单；同样**不改建边判定、不拒收**。

判据边界（如实）：
  · 句级判定：短语所在**句子**（[。！？；\n] 为界）内无库内 id ⇒ 幽灵；
    跨句引用（一句短语、邻句 id）不消解标记——保守方向是「宁标勿漏」。
  · 仅写链（MCP op=write）路径生效（与 linkref 同界）；库层直调 cg.add
    不经检测。
  · 短语表保守（明确的时间/人称回指词），**不含**「那条/那根」这类泛指示词
    （误报率高，标记面宁可窄）；误报后果 = fm 多一个标记。
  · 检测面**不查源节点 id 形态**（不同于 linkref 的 is_linkable_source
    门槛）：标记是**内容属性**——无论节点 id 是否合规，正文里的无出处回指
    都值得标记；建边是**图属性**，才需要形态门槛（防图污染）。两者有意
    不同界。**late 面例外**：它消费 linkref 解析出的 targets，源 id 不合
    形态 ⇒ 无 targets ⇒ late 静默不查（与 linkref 同界，2026-10-05 复核
    info-④ 登记）。
"""
from __future__ import annotations

import re

__all__ = ["PHRASES", "SENTENCE_SPLIT_RE", "find_ghost_phrases", "late_targets",
           "check"]

#: 回指短语表（时间回指 + 人称回指；CD-WHALE-01 发现 C 的词形采样，
#: 对齐评估 v0.1 §2 L1 的「上次的/之前的/明明讲过」三例）。
PHRASES = (
    "上次的", "上次说", "上次买", "上次那", "上次提",
    "之前的", "之前说", "之前买", "之前那", "之前提",
    "明明讲过", "明明说过", "明明说", "明明提",
    "刚才说", "刚才的", "前述的", "先前说", "早先的",
    "你说的", "我说过的", "你提过的",
)

#: 句界（句级判定的切分面）。保留句子文本、丢弃界符。
SENTENCE_SPLIT_RE = re.compile(r"[。！？；\n]+")


def find_ghost_phrases(text, known=None) -> list:
    """短语层检测：返回**无可解析出处**的回指短语列表（去重保序）。

    known —— 库内节点 id 集合（白名单）。句内含形态合法**且在册**的 id 即
    视为「有出处」（该句非幽灵）；传 None 时降级为只判形态（保守少报）。
    """
    if not text:
        return []
    from . import linkref
    out = []
    seen = set()
    for sent in SENTENCE_SPLIT_RE.split(str(text)):
        hits = [p for p in PHRASES if p in sent]
        if not hits:
            continue
        # 句内子串去重（最长优先）：「明明说过」同时命中「明明说过」与
        # 「明明说」——同一现象的一个更长粒度标记即可（复核 info-2：
        # 冗余双标记挤占 cap 16）。跨句不去重（不同句各自独立）。
        hits = [p for p in hits
                if not any(p != q and p in q for q in hits)]
        # 句内是否有可解析出处：id 形态命中 + （调用方给了 known 时）在册。
        refs = linkref.extract_refs(sent, known=known)
        if refs:
            continue
        for p in hits:
            if p not in seen:
                seen.add(p)
                out.append(p)
    return out


def late_targets(cg, targets, own_from) -> list:
    """id 层检测：目标创建时刻晚于本文档声明的生效起点 ⇒「目标晚于自身」。

    targets  —— linkref 解析出的引用目标 id 列表（ctx["linkref_targets"]）。
    own_from —— 本文档声明的生效起点（valid_from / effective_from）；缺省
                None 表示未声明时间轴，此时不做检查（写入 created_at=now，
                「目标晚于自身」结构上不可能）。

    返回 [{target, target_created, own_from}]（cap 10，保序）。
    """
    if own_from is None or not targets:
        return []
    try:
        own = float(own_from)
    except (TypeError, ValueError):
        return []
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    out = []
    for tid in targets:
        tid = str(tid)
        e = nodes.get(tid) or {}
        tc = e.get("created_at")
        if tc is None:
            rec = cg.get(tid) or {}
            tc = ((rec.get("frontmatter")) or {}).get("created_at")
        try:
            tc = float(tc)
        except (TypeError, ValueError):
            continue
        if tc > own:
            out.append({"target": tid, "target_created": tc, "own_from": own})
            if len(out) >= 10:
                break
    return out


# 生效条件：总是返回 {"ghost_phrases": [...], "late_refs": [...]} 两键 dict（各可为空列表）；
# 内部对 text 做短语层检测（known 取 cg 索引键集合），对 ctx 已解析的 linkref 目标做 id 层检测；
# 不做任何落盘/短路（纯读）。
def check(cg, text, linkref_targets=None, own_from=None) -> dict:
    """组合检测（纯读，无副作用）：供写入链闸调用。"""
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    known = set(nodes.keys())
    return {
        "ghost_phrases": find_ghost_phrases(text, known=known),
        "late_refs": late_targets(cg, linkref_targets or [], own_from),
    }
