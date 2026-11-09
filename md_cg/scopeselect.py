# -*- coding: utf-8 -*-
"""范围选择（scopeselect）——灵枢的**状态追踪式范围锚定**。

bench 读数（rubric92 · 552 断言 · 纯确定性）：
  · 槽位共现推断时间桶：**94.20% top-1**，且**加不加章节号都是 94.20%**（对字面零依赖）；
  · 对照：词面 bigram 排序 90.76%（消融）/ 87.14%（原 query）；
  · 邻近加权（行窗 12/24/40）反而更差（92.0–93.8）⇒ **桶级共现就是最优粒度**。

结论（为什么它该做标准）：
  词面检索问的是「哪段更像这句话」；假题的错元素本身位于别处，词面必然被带走（实测 28/28）。
  共现问的是「这些槽位值是否在同一时间桶里同时出现过」——错元素不在真桶里投票，真假自然分开。

本模块把「桶」泛化为灵枢的两种真实坐标：**日桶**（created_at）与**会话桶**（session）。
"""
from __future__ import annotations

import math
import os
import re

from . import bucketindex as _bi

#: 查询词切分（与检索面同口径：空白与中英标点，长度 ≥2）。
_SPLIT = re.compile(r"[\s,，、;；。！？:：()（）\[\]【】]+")


def terms(query):
    return [t.lower() for t in _SPLIT.split(str(query or "")) if len(t) >= 2]


def _meta_blob(store, nid):
    """桶内节点的**索引元数据**拼成的检索面（不读正文，避免逐节点读盘）。

    代价取舍：只读盘一次建桶的成本不可接受（实测 7.7–281 秒），
    故只用索引里已有的 tags / bucket_zh / role / content_kind / session。
    """
    nodes = (getattr(store, "index", {}) or {}).get("nodes") or {}
    rec = nodes.get(nid)
    if not isinstance(rec, dict):
        return ""
    fm = rec.get("frontmatter")
    if not isinstance(fm, dict) or not fm:
        fm = rec
    parts = []
    for key in ("tags", "bucket_zh", "bucket", "role", "content_kind", "session"):
        val = fm.get(key)
        if isinstance(val, (list, tuple)):
            parts.extend(str(x) for x in val)
        elif val:
            parts.append(str(val))
    return " ".join(parts).lower()


#: 桶词表缓存（按文件 mtime 失效）：1.6MB JSON 每次 _load 要 0.5s，缓存后毫秒级。
_TABLE_CACHE = {"key": None, "table": None}
_SKEL_CACHE = {"key": None, "table": None}


def score_buckets(store, query, max_nodes_per_bucket=None):
    """给每个候选桶打分：词项命中数 × idf（读 `_bucketterms.json`，毫秒级）。

    为什么用预建词表：逐节点读盘实测 7.7–281 秒、读索引元数据也要 3 秒；
    桶词表在**建桶时**顺手落盘（主库 0.36 秒），查询期只做字典运算。
    """
    ts = terms(query)
    root = getattr(store, "root", None) or ""
    path = (root + "/" + _bi.TERMS_FILE) if root else ""
    try:
        st = os.stat(path)
        key = (path, st.st_mtime, st.st_size)
    except OSError:
        key = None
    if _TABLE_CACHE["key"] != key or _TABLE_CACHE["table"] is None:
        _TABLE_CACHE["table"] = _bi._load(store, _bi.TERMS_FILE) or {}
        _TABLE_CACHE["key"] = key
    table = _TABLE_CACHE["table"]
    if not table or not ts:
        return []
    total = max(1, len(table))
    doc_hits = {t: 0 for t in ts}
    for _bucket, bag in table.items():
        for t in ts:
            if t in bag:
                doc_hits[t] += 1
    # 泛词过滤：df 超过 20% 桶的词（CCG 模板词如「功能名」「生效条件」）不参与打分，
    # 否则 idf 虽小但累加后仍会主导排序（实测这些词出现在几乎所有节点里）。
    cut = max(2, int(total * 0.2))
    keep_terms = [t for t in ts if doc_hits.get(t, 0) <= cut] or ts
    scored = []
    for bucket, bag in table.items():
        kind, _, key = str(bucket).partition(':')
        s = 0.0
        for t in keep_terms:
            if t in bag:
                df = max(1, doc_hits[t])
                s += math.log(1.0 + total / df)
        if s > 0:
            scored.append((s, kind, key))
    scored.sort(key=lambda x: (-x[0], x[1], x[2]))
    return scored


def _table_and_df(store, ts):
    """取桶词表 + 每词的 df（多少桶含它）。两条打分路共用。"""
    root = getattr(store, "root", None) or ""
    path = (root + "/" + _bi.TERMS_FILE) if root else ""
    try:
        st = os.stat(path)
        key = (path, st.st_mtime, st.st_size)
    except OSError:
        key = None
    if _TABLE_CACHE["key"] != key or _TABLE_CACHE["table"] is None:
        _TABLE_CACHE["table"] = _bi._load(store, _bi.TERMS_FILE) or {}
        _TABLE_CACHE["key"] = key
    table = _TABLE_CACHE["table"]
    total = max(1, len(table))
    doc_hits = {t: 0 for t in ts}
    for _bucket, bag in table.items():
        for t in ts:
            if t in bag:
                doc_hits[t] += 1
    return table, total, doc_hits


def _bi_bucket_order(bucket):
    """桶序（同日/同会话按 key 升序）——只用于平局裁决，越小越优先。"""
    return str(bucket)


def cooc_bucket_scores(store, query, min_terms=2, min_term_len=2):
    """**槽位共现打分（bench 同口径）**：桶得分 = 「查询里的短词」在该桶文本骨架里
    出现的**个数**（子串语义），idf 仅作平局裁决。

    为什么必须是子串而不是整词：bench（`bench_state_track.py`，99.28%）用
    `value in chapter_text` 判共现；生产若按标点切整句再整词匹配，实测只有 34%；
    换成汉字 n-gram 也只有 73.5%——**只有子串语义能对齐**，故按桶落一份文本骨架。
"""
    ts = [t for t in terms(query) if len(t) >= min_term_len]
    if not ts:
        return []
    skel = _skel_table(store)
    table, total, _doc = _table_and_df(store, ts)
    if not skel:
        return []
    df = {t: sum(1 for _b, blob in skel.items() if t in blob) for t in ts}
    keys = [t for t in ts if df.get(t, 0) > 0]
    # 稀有词不足时的**降档**：外测发现「江北回声那回」「我最早说…」这类题只有 1 个强实体、
    # 没有日期词，min_terms=2 会直接返回空 ⇒ 上层回落「最近 14 天」⇒ 老锚点必被排除。
    # 故仅剩 1 个稀有词时仍按它打分（仍要 hit ≥ 该词数，不会凭空造证据）。
    if not keys:
        return []
    if len(keys) < min_terms:
        min_terms = len(keys)
    scored = []
    for bucket, blob in skel.items():
        kind, _, key = str(bucket).partition(':')
        hit = sum(1 for t in keys if t in blob)
        if hit < min_terms:
            continue
        # 平局规则与 bench 对齐：**同分取桶序最早**（bench 是取章号最小）。
        # 早先用 idf 和做平局裁决，实测把 top-1 从 99.28% 压到 94.20%。
        scored.append((float(hit), _bi_bucket_order(str(bucket)), kind, key))
    # 注意：不能 sort 再 reverse——那会把平局裁决的桶序也一起翻转（实测 94% vs 99%）。
    scored.sort(key=lambda x: (-x[0], x[1], x[2]))
    return [(h, k, kk) for h, _t, k, kk in scored]


def _skel_table(store):
    """读桶文本骨架（`_bucketskel.json`），带 mtime 缓存。"""
    root = getattr(store, "root", None) or ""
    path = (root + "/" + _bi.SKEL_FILE) if root else ""
    try:
        st = os.stat(path)
        key = (path, st.st_mtime, st.st_size)
    except OSError:
        key = None
    if _SKEL_CACHE["key"] != key or _SKEL_CACHE["table"] is None:
        _SKEL_CACHE["table"] = _bi._load(store, _bi.SKEL_FILE) or {}
        _SKEL_CACHE["key"] = key
    return _SKEL_CACHE["table"]


def pick_scopes(store, query, session=None, limit=3, now=None):
    """选范围：**声明优先**（会话 > 显式日期），否则按共现打分取前 limit 个桶。

    声明优先的理由：声明是任务的一部分（「那天」「本会话」是用户给定的范围），
    必须当过滤用；共现只在**没有声明**时才作为推断手段。
    """
    picked = []
    sid = str(session or "")
    if sid and sid != _bi.UNATTRIBUTED and _bi.session_ids(store, sid):
        picked.append(("session", sid, 1.0))
    try:
        from . import timeboost as _tb
        # 逻辑时钟必须由调用方注入（#111 契约同纪律）：早先取真实 time.time()，
        # 外部复测把逻辑时间推进到题干 now 时，「三天前」永远指向错的那一天，
        # 时间类增益根本测不出来（2026-11-10 测评反馈 + 修）。
        _now = now if now is not None else __import__("time").time()
        for day in sorted(_tb.query_dates(query, _now), reverse=True):
            if _bi.day_ids(store, day):
                picked.append(("day", day, 1.0))
    except Exception:          # noqa: BLE001 —— 日期解析失败不影响共现推断
        pass
    if len(picked) < limit:
        ranked = score_buckets(store, query)
        if os.environ.get("MDCG_SCOPESEL_COOC", "1") == "1":
            ranked = cooc_bucket_scores(store, query) or ranked
        for s, kind, key in ranked:
            if (kind, key) in [(k, kk) for _x, k, kk in picked]:
                continue
            picked.append((kind, key, s))
            if len(picked) >= limit:
                break
    return picked[:limit]