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


def pick_scopes(store, query, session=None, limit=3):
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
        for day in sorted(_tb.query_dates(query, __import__("time").time()), reverse=True):
            if _bi.day_ids(store, day):
                picked.append(("day", day, 1.0))
    except Exception:          # noqa: BLE001 —— 日期解析失败不影响共现推断
        pass
    if len(picked) < limit:
        for s, kind, key in score_buckets(store, query):
            if (kind, key) in [(k, kk) for _x, k, kk in picked]:
                continue
            picked.append((kind, key, s))
            if len(picked) >= limit:
                break
    return picked[:limit]