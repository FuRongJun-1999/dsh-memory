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

import re

#: 无 tag 命中的分组键（不输出——没有话题名的聚合只是噪声）
UNTAGGED = "__untagged__"


def _terms(text: str) -> list:
    """查询/正文的分词（与检索面同口径：按空白与中英标点切，长度 ≥2）。"""
    return [t.lower() for t in re.split(r"[\s,，、;；。！？:：()（）\[\]【】]+", text or "")
            if len(t) >= 2]


def _entry_topic(entry, query_terms) -> str:
    """条目的聚合键：tags 里与 query 有交集的第一个 tag；无交集则 UNTAGGED。"""
    fm = entry.get("frontmatter") or {}
    tags = [str(t) for t in (fm.get("tags") or []) if str(t).strip()]
    for tag in tags:
        tl = tag.lower()
        if any(t in tl or tl in t for t in query_terms):
            return tag
    return UNTAGGED


def aggregate(pack, query, min_members: int = 2, max_groups: int = 5) -> list:
    """把 pack 按话题聚合成状态时间线。

    返回 [{topic, count, ids, timeline: [{id, state, t, snippet}]}]，按成员数降序。
    只输出成员数 ≥ min_members 的组（单条没有「跨轮」可言）。
    """
    terms = _terms(query)
    groups = {}
    for entry in pack or ():
        topic = _entry_topic(entry, terms)
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
        members.sort(key=lambda x: x["t"])       # 时间正序 = 状态演变顺序
        out.append({
            "topic": topic,
            "count": len(members),
            "ids": [m["id"] for m in members],
            "timeline": members,
        })
    out.sort(key=lambda g: (-g["count"], g["topic"]))
    return out[:max_groups]