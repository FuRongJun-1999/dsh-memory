# -*- coding: utf-8 -*-
"""md_cg · 热路径缓存（L0 节点缓存 + query 结果缓存）

【为什么】检索链路每次都跑四路 RRF 融合（约 50ms），但同一 query
短时间内反复调用是常态（agent 对话轮次间、batch 调用等）。热缓存
让重复 query 毫秒级返回，同时 L0 高频节点（session=main）的
frontmatter 读取也从磁盘降为内存命中。

【设计】
  - 节点缓存：LRU dict，key=node_id → value=(frontmatter, body_excerpt)
  - query 缓存：LRU dict，key=(query, k, layer, session, branch, validity, view,
    extra) → value=(results, meta)
    **键必须覆盖全部影响结果的参数**（红线，v14 缺陷 C 的教训）：validity /
    view 之外，`include_work` / `roles` / `paths` / `path_weights` /
    `recall_only` / `fusion` / `judge` / `judge_ranking` / `goal_text` /
    `context` / `early_stop_threshold` 同样改变候选资格与排序，经 `extra`
    整体入键（`_KEYED_EXTRA` 为清单真源）。
    不入键的后果不是「慢」而是**静默错答**：默认查询会返回工作角色节点
    （资格泄漏）、`paths` 口径互相顶替等。
  - 无法稳定规范化的参数（自定义可调用 `query_expand`，见 `_BYPASS_EXTRA`）：
    **非默认值即绕行缓存**（读+写双侧），fail-closed——宁可不用缓存，不可串味。
  - 失效策略：写入时 invalidate 受影响节点 + query 全清（保守策略，
    因为 RRF 融合后一个节点的变动可能影响全局排序）
  - TTL：query 缓存 300s（5 分钟），节点缓存无 TTL（写入即失效）

【边界】
  - 进程内缓存，不跨进程（每个 cg 实例独立）
  - 不改 RRF 核心算法（bench6 600/600 rank 逐位一致是硬约束）
  - 缓存命中时 meta 带 "cached": True 标记

零第三方依赖（D-005）。
"""
from __future__ import annotations

import time
from collections import OrderedDict

#: 节点缓存上限
MAX_NODES = 256
#: query 缓存上限
MAX_QUERIES = 64
#: query 缓存 TTL（秒）
QUERY_TTL = 300.0

#: 进键的「口径参数」清单（**单一真源**）：调用方（mdcos.search_rrf）按此
#: 构造 extra。新增影响结果的检索参数必须同时登记到本清单——漏登即跨口径
#: 串味（v14 缺陷 C：include_work/roles 致资格泄漏、paths 互相顶替）。
_KEYED_EXTRA = ("include_work", "roles", "paths", "path_weights", "recall_only",
                "fusion", "judge", "judge_ranking", "goal_text", "context",
                "early_stop_threshold")
#: 不可稳定规范化的参数（自定义可调用）：非默认即**绕行缓存**（fail-closed）。
_BYPASS_EXTRA = ("query_expand",)


class HotCache:
    """进程内热路径缓存。

    使用 OrderedDict 实现 LRU 语义：
    - get 命中时 move_to_end（最近使用放尾）
    - put 满时 popitem(last=False)（淘汰头=最久未用）
    """

    def __init__(self, *, max_nodes=MAX_NODES, max_queries=MAX_QUERIES,
                 query_ttl=QUERY_TTL):
        self._nodes: OrderedDict = OrderedDict()
        self._queries: OrderedDict = OrderedDict()
        self._max_nodes = max_nodes
        self._max_queries = max_queries
        self._query_ttl = query_ttl
        # 统计
        self._stats = {"node_hits": 0, "node_misses": 0,
                       "query_hits": 0, "query_misses": 0,
                       "invalidations": 0}

    # ---------- 节点缓存 ----------

    def get_node(self, node_id: str):
        """返回 (frontmatter, body_excerpt) 或 None（未缓存）。"""
        entry = self._nodes.get(node_id)
        if entry is None:
            self._stats["node_misses"] += 1
            return None
        self._stats["node_hits"] += 1
        self._nodes.move_to_end(node_id)
        return entry

    def put_node(self, node_id: str, frontmatter: dict, body_excerpt: str = ""):
        """写入/更新节点缓存。"""
        self._nodes[node_id] = (dict(frontmatter), body_excerpt)
        self._nodes.move_to_end(node_id)
        while len(self._nodes) > self._max_nodes:
            self._nodes.popitem(last=False)

    def invalidate_node(self, node_id: str):
        """失效单个节点。"""
        self._nodes.pop(node_id, None)

    # ---------- query 缓存 ----------

    @staticmethod
    def _canon(v):
        """参数值 → 可哈希、稳定、跨调用一致的键片段（递归规范化容器）。"""
        if v is None or isinstance(v, (bool, int, float, str, bytes)):
            return v
        if isinstance(v, (list, tuple)):
            return tuple(HotCache._canon(x) for x in v)
        if isinstance(v, (set, frozenset)):
            return tuple(sorted((HotCache._canon(x) for x in v), key=repr))
        if isinstance(v, dict):
            return tuple(sorted((str(k), HotCache._canon(x))
                                for k, x in v.items()))
        # 其余（含自定义对象/可调用）：repr 含内存地址 → 每次不同 →
        # 缓存永不命中（等价绕行），是**安全侧**失败（不串味）。
        return ("repr", repr(v))

    @staticmethod
    def _query_key(query, k, layer, session, branch, validity=None,
                   view=None, extra=None):
        # 键必须覆盖全部影响结果的参数（正确性缺陷，非优化项）：
        # validity（不过滤/排已过期）、view（角色视图）、extra（口径参数，
        # 见 _KEYED_EXTRA）任一不入键都会串结果。
        return (query, k, layer or None, session or None, branch or None,
                bool(validity) or None, view or None,
                HotCache._canon(extra) if extra else None)

    def get_query(self, query, k=20, layer=None, session=None, branch=None,
                  validity=None, view=None, extra=None):
        """返回 (results, meta) 或 None（未缓存/过期）。"""
        key = self._query_key(query, k, layer, session, branch, validity,
                              view, extra)
        entry = self._queries.get(key)
        if entry is None:
            self._stats["query_misses"] += 1
            return None
        ts, results, meta = entry
        if time.time() - ts > self._query_ttl:
            self._queries.pop(key, None)
            self._stats["query_misses"] += 1
            return None
        self._stats["query_hits"] += 1
        self._queries.move_to_end(key)
        return results, dict(meta)

    def put_query(self, query, results, meta, k=20, layer=None,
                  session=None, branch=None, validity=None, view=None,
                  extra=None):
        """写入/更新 query 缓存。"""
        key = self._query_key(query, k, layer, session, branch, validity,
                              view, extra)
        self._queries[key] = (time.time(), list(results), dict(meta))
        self._queries.move_to_end(key)
        while len(self._queries) > self._max_queries:
            self._queries.popitem(last=False)

    def invalidate_all_queries(self):
        """清空全部 query 缓存（写入时保守全清）。"""
        n = len(self._queries)
        self._queries.clear()
        if n:
            self._stats["invalidations"] += 1

    def invalidate_node_and_queries(self, node_id: str):
        """失效节点 + 全清 query（节点变动可能影响全局排序）。"""
        self.invalidate_node(node_id)
        self.invalidate_all_queries()

    # ---------- 全局 ----------

    def clear(self):
        """清空全部缓存。"""
        self._nodes.clear()
        self._queries.clear()

    def stats(self):
        """返回统计信息。"""
        s = dict(self._stats)
        s["node_cache_size"] = len(self._nodes)
        s["query_cache_size"] = len(self._queries)
        return s


#: 进程级默认实例（每个 cg 实例可独立持有，也可共享此单例）
_DEFAULT = None


def default_cache():
    """进程级默认热缓存单例。"""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = HotCache()
    return _DEFAULT


def attach(cg):
    """给 cg 实例挂热缓存（幂等：已挂则不重复）。"""
    if not hasattr(cg, "_hotcache") or cg._hotcache is None:
        cg._hotcache = HotCache()
    return cg._hotcache


def get(cg):
    """取 cg 实例的热缓存（未挂返回 None）。"""
    return getattr(cg, "_hotcache", None)


def invalidate(cg, node_id: str = None):
    """写入后失效（节点 + query 全清）。node_id=None 时全清。"""
    hc = get(cg)
    if hc is None:
        return
    if node_id:
        hc.invalidate_node_and_queries(node_id)
    else:
        hc.clear()
