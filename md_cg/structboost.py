# -*- coding: utf-8 -*-
"""结构信号重排（structboost）——**章节路由 + 元素覆盖**的确定性提升。

bench 读数（hive-memory-bench · 六元素判断题 476 · 行窗切块 · gold=evidence 行号）：

| 配置 | gold@1 | gold@3 | gold@10 |
|---|---:|---:|---:|
| baseline | 49.6% | 71.9% | 92.0% |
| 章节 ×2 | 49.0% | 85.7% | 95.8% |
| **章节 ×2 + 元素 ×1.0** | **52.5%** | **85.7%** | **96.2%** |

两条信号都是**确定性可数**的（与 detrerank 同一纪律）：
  · 章节：题面「第N章」→ 候选正文里的「## 第N章」标题 / tags 里的章号；
  · 元素：题面按 `·`（六元素分隔符）切出的元素，在候选正文中出现的比例。

不做硬过滤：题面可能故意写错章节（负例题），硬滤会把正确证据筛掉 ⇒ 只用**乘性提升**。
"""
from __future__ import annotations

import re

#: 章节命中提升倍数（bench 扫描 1.5/2.0/3.0 结果相同，取中位 2.0）。
CHAPTER_BOOST = 2.0
#: 元素覆盖率提升系数（bench 扫描 0.5/1.0/2.0，1.0 最优：@3 不掉、@1/@10 最高）。
ELEMENT_BOOST = 1.0

_CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
       "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def cn2int(s):
    """中文数字/阿拉伯数字 → int（1..99 够用）；解析不出返回 None。"""
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s in _CN:
        return _CN[s]
    if len(s) == 2 and s[1] == "十":
        return _CN.get(s[0], 0) * 10
    if len(s) == 2 and s[0] == "十":
        return 10 + _CN.get(s[1], 0)
    if len(s) == 3 and s[1] == "十":
        return _CN.get(s[0], 0) * 10 + _CN.get(s[2], 0)
    return None


def query_chapter(query):
    """从查询里取章号（「第N章」/「第N章「标题」」）；没有返回 None。"""
    m = re.search(r"第\s*([一二三四五六七八九十\d]+)\s*章", str(query or ""))
    return cn2int(m.group(1)) if m else None


def node_chapter(node):
    """候选节点的章号：**正文标题优先**，其次 tags。

    为什么正文优先：实测（476 题）tags 里常有与正文不一致的章号（人工打标/批次标签），
    按 tags 优先会让提升打到错的章上——@1 从 0.50 掉到 0.30。
    正文的 `## 第N章` 标题是语料自带的结构，才可信。
    """
    text = str(node.get("content") or "")
    m = re.search(r"^#{1,4}\s*第\s*([一二三四五六七八九十\d]+)\s*章", text, re.M)
    if m:
        return cn2int(m.group(1))
    fm = node.get("frontmatter") or {}
    for tag in (fm.get("tags") or []):
        t = str(tag)
        if t.startswith(CHAPTER_TAG_PREFIX):        # 入库期盖章约定：ch:3
            try:
                return int(t[len(CHAPTER_TAG_PREFIX):])
            except ValueError:
                continue
        got = query_chapter(t)
        if got:
            return got
    return None


def elements(query):
    """六元素：按 `·` 切分，去掉章节标签与过短片段。"""
    parts = [p.strip() for p in str(query or "").split("·") if p.strip()]
    out = []
    for p in parts:
        if query_chapter(p):
            continue
        p = re.sub(r"^[《「【(（]|[》」】)）]$", "", p).strip()
        if len(p) >= 2:
            out.append(p)
    return out


def boost(node, query, chap=0, elems=None):
    """单个候选的提升倍数（确定性；无信号返回 1.0）。

    `chap`：**显式章号**（0 表示「本条不启用章节信号」）。
    这里刻意**不**在函数内重新解析 query——否则调用方用 `chap=None` 关闸时，
    函数又把章号解析回来，闸门形同虚设（实测：gold@1 仍然从 0.50 掉到 0.15）。
    """
    q_chap = chap or None
    es = elements(query) if elems is None else elems
    factor = 1.0
    if q_chap is not None and node_chapter(node) == q_chap:
        factor *= CHAPTER_BOOST
    if es:
        text = str(node.get("content") or "")
        hits = sum(1 for e in es if e in text)
        factor *= 1.0 + ELEMENT_BOOST * (hits / float(len(es)))
    return factor


#: 章节提升的启用前提：候选集中**已知章号**的比例达到此值。
#: 实测（476 题）：仅 23/153 块自带章节标题时启用章节提升，gold@1 从 0.50 掉到 0.16——
#: 因为提升只打在「少数知道章号的块」上，把它们错误地顶到前面。
#: 故候选集里章号信息不足时，**整条章节信号弃用**（而不是半用）。
CHAPTER_MIN_KNOWN = 0.5


def rerank(results, query, k=None):
    """对 [(node, score, ...), ...] 做稳定重排：score × boost，同分按原序（确定性）。

    只在**已召回的候选集内**重排，不改候选集、不做过滤 ⇒ 无召回损失风险。
    章节信号按 `CHAPTER_MIN_KNOWN` 闸门决定是否启用（信息不足则整条弃用）。
    """
    q_chap = query_chapter(query)
    es = elements(query)
    if q_chap is not None and results:
        known = sum(1 for item in results if node_chapter(item[0]) is not None)
        if known / float(len(results)) < CHAPTER_MIN_KNOWN:
            q_chap = 0           # 章号信息不足 ⇒ 弃用章节信号（0 = 关，只留元素信号）
    order = []
    for idx, item in enumerate(results or ()):
        node = item[0]
        try:
            score = float(item[1])
        except (TypeError, ValueError, IndexError):
            score = 0.0
        order.append((score * boost(node, query, q_chap, es), idx, item))
    order.sort(key=lambda t: (-t[0], t[1]))
    out = [t[2] for t in order]
    return out[:k] if k else out


#: 盖章用的 tag 前缀（`ch:3`）。与内容标题同源，避免与人工 tag 混用。
CHAPTER_TAG_PREFIX = "ch:"


def stamp_chapters(nodes):
    """入库期章号盖章：按给定顺序遍历节点，把「最近一次出现的章节标题」写成 tag。

    为什么需要（bench 实测）：行窗切块后 **153 块里只有 23 块自带 `## 第N章` 标题**，
    其余块在查询期无法判知自己属于哪一章 ⇒ 章节提升会打到「章节首块」上，
    gold@1 从 0.50 掉到 0.16。章号必须在**入库期**按文档顺序继承，查询期才有得用。

    nodes: [{"id":..., "content":...}, ...]（有序）；返回 {id: chapter}，并原地把
    `ch:N` 写进 `frontmatter["tags"]`（若给定的是可变 dict）。
    """
    out = {}
    last = None
    for node in nodes or ():
        text = str(node.get("content") or "")
        m = re.search(r"^#{1,4}\s*第\s*([一二三四五六七八九十\d]+)\s*章", text, re.M)
        if m:
            got = cn2int(m.group(1))
            if got:
                last = got
        if last is None:
            continue
        nid = node.get("id")
        out[nid] = last
        fm = node.get("frontmatter")
        if isinstance(fm, dict):
            tags = fm.get("tags")
            if not isinstance(tags, list):
                tags = fm["tags"] = []
            key = "%s%d" % (CHAPTER_TAG_PREFIX, last)
            if key not in tags:
                tags.append(key)
    return out