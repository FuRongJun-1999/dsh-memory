# -*- coding: utf-8 -*-
"""跨轮状态聚合（读取策略改造 A 项）——**聚合实现单点**。

病灶（Ornn8 2026-11-07 终局报告）：「上次聊灯箱进行到哪一步」的答案状态散在轮9 与轮20
两条里，检索给了直接相关的一条，**拼不出完整状态**。报告结论：这不是存储失败，
是**读取策略**失败——原文全在库里，缺的是「同话题多轮合并给出」的组装方式。

设计边界（三条，都为了不越界）：
  1. **不改排序、不改打分**——纯后处理，输入是已装好的 pack；
  2. **不自造 state**——state 只从条目既有 metadata 读（issue #111 同一条纪律）；
  3. **不判重、不判对错**——同一话题的多条就是多条，按时间排好交给调用方判断。
"""
from __future__ import annotations

import os
import re

#: 无 tag 命中的分组键（不输出——没有话题名的聚合只是噪声）
UNTAGGED = "__untagged__"

def _tagfallback(pack_blob=None) -> bool:
    """tag 召回兜底开关（**调用期**读环境，缺省关）。

    为什么不在 import 期固化：模块级常量一旦固化，进程内再也切不回来，
    测试与运行时行为会不一致（#111 同源的「隐式状态」问题）。
    """
    return os.environ.get("MDCG_TOPIC_AGG_TAGFALLBACK", "0").strip() == "1"


def _terms(text: str) -> list:
    """查询/正文的分词（与检索面同口径：按空白与中英标点切，长度 ≥2）。"""
    return [t.lower() for t in re.split(r"[\s,，、;；。！？:：()（）\[\]【】]+", text or "")
            if len(t) >= 2]


#: 泛词判据（**确定性词形规则**，不看语料统计）。
#: 为什么不看「命中占比」：查询本身就把含该词的条目筛出来了，占比恒 ≈1，
#: 那样会连「灯箱」都判成泛词（实测：8 话题全被闸掉，兜底等于没开）。
#: 判据改为：中文词长 < MIN_TERM_LEN 且 不在 STOPWORDS ⇒ 视为泛词。
MIN_TERM_LEN = 3

#: 跨轮闸：组内时间跨度（秒）小于此值 ⇒ 不是「跨轮」，不输出。
#: 批量灌库（同一秒写入）的节点会集中命中，那不是状态演变。
MIN_SPAN_SECONDS = 30.0
STOPWORDS = frozenset(
    "文件 内容 问题 时间 方法 状态 加载 好的 可以 这个 那个 我们 你们 他们 什么 怎么"
    "已经 还是 就是 因为 所以 但是 而且 如果 虽然 然后 现在 之后 之前 一样 一些 这样".split()
)


def _term_too_general(term: str, pack_blob=None) -> bool:
    """词项是否过泛（确定性词形规则）：短词且非停用词表之外的具体词。"""
    t = (term or "").strip()
    if not t:
        return True
    if re.fullmatch(r"[A-Za-z0-9_]+", t):
        return len(t) < MIN_TERM_LEN
    if len(t) >= MIN_TERM_LEN:
        return False
    return t in STOPWORDS


def _entry_topic(entry, query_terms, pack_blob=None) -> str:
    """条目的聚合键：tags 里与 query 有交集的第一个 tag；无交集则 UNTAGGED。"""
    fm = entry.get("frontmatter") or {}
    tags = [str(t) for t in (fm.get("tags") or []) if str(t).strip()]
    for tag in tags:
        tl = tag.lower()
        if any(t in tl or tl in t for t in query_terms):
            return tag
    # tag 召回兜底（MDCG_TOPIC_AGG_TAGFALLBACK=1，缺省关）：
    # 实测（bench/e2e/corpus 175 轮）聚合组只在「tag 恰好命中话题」时成立，
    # 无 tag 覆盖的对话几乎全归 UNTAGGED ⇒ 聚合形同未启用。
    # 兜底口径：条目**正文**里出现某个 query 词项，就用该词项当组名——
    # 仍是确定性词面判据（不用相似度），且只在显式开启时生效，以免改变既有行为。
    if _tagfallback(pack_blob):
        text = str(entry.get("content") or "").lower()
        for term in query_terms:
            # 特异性闸：命中该词项的条目占比 > GENERAL_TERM_RATIO 视为泛词，不作组名。
            # 动机（bench 实测）：无闸时 8 个话题聚出 77 个成员（≈每话题 9.6 条），
            # 「文件」「内容」这类泛词会把不相关条目也拉进同一组——聚合反而制造噪声。
            if not term or term not in text:
                continue
            if _term_too_general(term, pack_blob):
                continue
            return term
    return UNTAGGED


def aggregate(pack, query, min_members: int = 2, max_groups: int = 5) -> list:
    """把 pack 按话题聚合成状态时间线。

    返回 [{topic, count, ids, timeline: [{id, state, t, snippet}]}]，按成员数降序。
    只输出成员数 ≥ min_members 的组（单条没有「跨轮」可言）。
    """
    terms = _terms(query)
    groups = {}
    blob = [str(e.get("content") or "").lower() for e in (pack or ())]
    for entry in pack or ():
        topic = _entry_topic(entry, terms, blob)
        if topic == UNTAGGED:
            continue
        fm = entry.get("frontmatter") or {}
        meta = entry.get("metadata") or {}
        t = fm.get("created_at") or fm.get("valid_from") or 0
        try:
            t = float(t)
        except (TypeError, ValueError):
            t = 0.0
        snippet = str(entry.get("content") or "")
        # 取正文里第一行「# 功能名：…」（有则用，无则首 60 字）。
        # 注意：内容里可能是**字面**的 \n 序列（不是换行），故同时按两种分隔切。
        m = re.search(r"#\s*功能名[：:]\s*(.+)", snippet)
        label = m.group(1) if m else snippet
        for sep in ("\\n", "\n", "\r", "\t", " #"):
            label = label.split(sep)[0]
        label = label.strip()[:60]
        groups.setdefault(topic, []).append({
            "id": entry.get("id"),
            "state": meta.get("state"),      # 只读既有字段，不自造
            "t": t,
            "label": label,
        })
    out = []
    for topic, members in groups.items():
        if len(members) < min_members:
            continue
        # 跨轮闸：**至少两个不同时间点**才算「跨轮状态」。
        # 动机（bench 实测）：兜底开启后单话题一次聚到 10 条（整个 pack 一组），
        # 那是「同一个时间点的一堆材料」，不是「状态在时间上演变」——
        # 对「上次聊到哪一步」这类问题毫无帮助，反而挤占预算。
        if (max(m["t"] for m in members) - min(m["t"] for m in members)) < MIN_SPAN_SECONDS:
            continue
        members.sort(key=lambda x: x["t"])       # 时间正序 = 状态演变顺序
        out.append({
            "topic": topic,
            "count": len(members),
            "ids": [m["id"] for m in members],
            "timeline": members,
        })
    out.sort(key=lambda g: (-g["count"], g["topic"]))
    return out[:max_groups]