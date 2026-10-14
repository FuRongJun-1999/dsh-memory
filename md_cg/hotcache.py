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

import os
import time
import math
from collections import OrderedDict

#: 节点缓存上限（env MDCG_HOTCACHE_MAX_NODES 可覆盖——公共评测池 locomo-zh-500
#: 为 567 节点，缺省 256 会持续 LRU 淘汰，issue #28：容量应可配或自适应）
MAX_NODES = 256
#: query 缓存上限（env MDCG_HOTCACHE_MAX_QUERIES 可覆盖）
MAX_QUERIES = 64
#: query 缓存 TTL（秒）
QUERY_TTL = 300.0

#: 进键的「口径参数」清单（**单一真源**）：调用方（mdcos.search_rrf）按此
#: 构造 extra。新增影响结果的检索参数必须同时登记到本清单——漏登即跨口径
#: 串味（v14 缺陷 C：include_work/roles 致资格泄漏、paths 互相顶替）。
_KEYED_EXTRA = ("include_work", "roles", "paths", "path_weights", "recall_only",
                "fusion", "judge", "judge_ranking", "goal_text", "context",
                "early_stop_threshold",
                # 进程级开关快照（见 env_switch_key）：参数面之外还有一类口径来自
                # 环境变量（MDCG_SEMANTIC/MDCG_EN_ATOMS/MDCG_UNIFY_QUERY…），它们
                # 同样改变候选资格与打分。v14 只补了参数面，故另立一键
                # （2026-09-24 修复：同 query 下切开关会命中另一口径的缓存 → 静默错答）。
                "env_switch", "bm25_access",
                # #153（2026-10-12 DSH 端）：**索引代际**。写路径每次索引突变推进
                # 代际（MdCGOS._on_index_mutation）⇒ 键随代际变化 ⇒ 旧代命中自然
                # 失配，无需全清（全清会毁命中率，与 #154 性能面冲突）。
                # 登记纪律同 env_switch：新增一个就登记一个——不登记等于让下一个人
                # 看不出它承重（键用整份 extra，故漏登只影响可读性、不影响正确性）。
                "index_gen",
                # 相对时间锚定：问句解析出的区间（仅开关开且问句含日期时入键；相对写法
                # 「上周二」随当天变化，不入键会跨日命中旧区间的结果）。
                "time_anchor")
#: 不可稳定规范化的参数（自定义可调用）：非默认即**绕行缓存**（fail-closed）。
_BYPASS_EXTRA = ("query_expand",)
#: 影响检索结果的进程级开关（新增一个就登记一个——同 _KEYED_EXTRA 的纪律）。
#: MDCG_CN_GRAMS（v9 N78）：mdcg.cn_recall_grams 每调用读 env（="0" 回退旧行为），
#: 改变 expand_query_terms 召回词集——漏登即运行期翻转后同 query 命中另一口径缓存。
#: MDCG_CHAIN_TYPES / MDCG_TEMPORAL_GAMMA（P3 图检索路，2026-10-01）：前者改「因果路
#: 沿哪些边类型扩散」（改候选集合），后者改「时间路的衰减率」（改路内名次）——两者都
#: 直接改变融合结果，同属「漏登即跨口径串味」的一类。
_ENV_SWITCHES = ("MDCG_SEMANTIC", "MDCG_EN_ATOMS", "MDCG_UNIFY_QUERY",
                 "MDCG_RETRIEVAL_PIPELINE", "MDCG_S7_FRESHNESS",
                 "MDCG_CN_GRAMS", "MDCG_CHAIN_TYPES", "MDCG_TEMPORAL_GAMMA",
                 "MDCG_RRF_CANDIDATES",
                 # issue #197（2026-10-13）：名次可信度的**性质判据**开关。
                 # 开启后在既有名单门之上追加 whole_tie（任意路）与
                 # floor_mass（有下限声明的路）两条弃权分支 ⇒ 直接改变融合
                 # 结果，同属「漏登即跨口径串味」的一类。
                 "MDCG_RANK_CREDIBILITY",
                 # 相对时间锚定（2026-10-14）：开关开 ⇒ 写入侧派生 temporal_anchor、查询侧
                 # 点名日期时追加 time_anchor 路并把区间交集者前置；TZ 改「哪一天」的折算
                 # ⇒ 两者都改变融合结果，同属「漏登即跨口径串味」的一类。
                 "MDCG_TIME_ANCHOR", "MDCG_TIME_ANCHOR_TZ")


# 生效条件：无必需形参；返回 _ENV_SWITCHES 中每个变量名的 (名, 当前取值或 None) 元组（稳定、可哈希，随 query 缓存键一起参与比对）。
def env_switch_key():
    """当前进程级检索开关的快照（进 query 缓存键，防跨口径串味）。"""
    return tuple((name, os.environ.get(name)) for name in _ENV_SWITCHES)


def validity_window(entries, started):
    """Clock interval on which a cold query's whole candidate pool is stable.

    Include every candidate, not just returned Top-K: expiry of a nonwinner
    can change BM25 corpus statistics and therefore the winning rank. Start
    endpoints also invalidate cached qualification metadata; an inverted
    future-start/past-end window changes from not_yet to expired at its start.
    Uncertain/nonfinite endpoints bypass caching. Construction is O(N) only
    on a miss; a hit checks two scalar clock bounds in O(1).
    """
    from . import trust
    deadline = None
    for entry in entries:
        kind, start, end = trust.validity(entry, now=started)
        if kind == "expired":
            return None  # The clock moved while candidates were being read.
        for boundary in (start, end):
            if boundary is None:
                continue
            if not math.isfinite(boundary):
                return None
            if boundary >= started:
                deadline = boundary if deadline is None else min(deadline, boundary)
    return started, deadline


def _within_window(now, window):
    return now >= window[0] and (window[1] is None or now < window[1])


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
        self._query_windows = {}
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
            # #153（2026-10-12 DSH 端）：键片段用**三元组**（"k", 类型名, str(键)）。
            # 修前是 (str(键), 值) 二元组，两个缺陷：
            #   ① 撞键：`{1: 'x'}` 与 `{'1': 'x'}` 的 canon **逐位相同**
            #      （int 1 与 str '1' 都 str 成 "1"）⇒ 语义不同的入参命中同一
            #      缓存键，静默串结果；
            #   ② 抛异常：`sorted(...)` 对 (str, 值) 二元组排序，键相同则比到
            #      **值**——`_canon({1: None, '1': (1, 2)})` 比 None 与 tuple
            #      ⇒ `TypeError: '<' not supported between instances of
            #      'tuple' and 'NoneType'`，异常从 `search_rrf` 逃出（检索
            #      入口整体 500）。context 是模型可控入参，形态不可信。
            # 故：片段里带 `type(k).__name__` 消撞键；排序键**只取片段**
            # （`key=lambda kv: kv[0]`，全是 str 元组 ⇒ 恒可比，不触值）。
            return tuple(sorted(
                ((("k", type(k).__name__, str(k)), HotCache._canon(x))
                 for k, x in v.items()),
                key=lambda kv: kv[0]))
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
        now = time.time()
        window = self._query_windows.get(key)
        if (now - ts > self._query_ttl
                or (window is not None and not _within_window(now, window))):
            self._queries.pop(key, None)
            self._query_windows.pop(key, None)
            self._stats["query_misses"] += 1
            return None
        self._stats["query_hits"] += 1
        self._queries.move_to_end(key)
        # #153①（2026-10-12 DSH 端）：**出口一律深一层浅拷贝**——修前只
        # `dict(meta)` 拷贝了 meta，`results` 是**缓存内部 list 的引用**：
        # 调用方（检索后处理 / 排序 / 截断 / 上层 append）对返回值的任何原地
        # 修改都会**写回缓存**，下一次命中就拿到被污染的「结果」——别名污染
        # 是静默错答（不是性能问题）。行内元素 dict 同样按引用共享（`bm25`
        # 的 rows 是 `(node_dict, score)`），故逐行浅拷贝、行内 dict 再拷贝。
        return [HotCache._copy_row(r) for r in results], dict(meta)

    @staticmethod
    def _copy_row(row):
        """query 结果行的**浅拷贝**（#153①）：list/tuple 保持原容器类型，
        容器内的 dict 元素另拷一份，其余标量原样。"""
        if isinstance(row, dict):
            return dict(row)
        if isinstance(row, (list, tuple)):
            items = [dict(x) if isinstance(x, dict) else x for x in row]
            return tuple(items) if isinstance(row, tuple) else items
        return row

    def put_query(self, query, results, meta, k=20, layer=None,
                  session=None, branch=None, validity=None, view=None,
                  extra=None, clock_window=None):
        """写入/更新 query 缓存。"""
        key = self._query_key(query, k, layer, session, branch, validity,
                              view, extra)
        now = time.time()
        if clock_window is not None and not _within_window(now, clock_window):
            self._queries.pop(key, None)
            self._query_windows.pop(key, None)
            return
        self._queries[key] = (now, list(results), dict(meta))
        if clock_window is None:
            self._query_windows.pop(key, None)
        else:
            self._query_windows[key] = clock_window
        self._queries.move_to_end(key)
        while len(self._queries) > self._max_queries:
            evicted, _entry = self._queries.popitem(last=False)
            self._query_windows.pop(evicted, None)

    def invalidate_all_queries(self):
        """清空全部 query 缓存（写入时保守全清）。"""
        n = len(self._queries)
        self._queries.clear()
        self._query_windows.clear()
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
        self._query_windows.clear()

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


# 生效条件：cg 传入；已挂（_hotcache 非 None）时幂等返回现有实例；未挂时按 max_nodes/max_queries 显式值构造 HotCache，缺省回落 env MDCG_HOTCACHE_MAX_NODES / MDCG_HOTCACHE_MAX_QUERIES（非整数回落模块级默认），再回落模块级常量；返回挂载的 HotCache。
def attach(cg, *, max_nodes: int = None, max_queries: int = None):
    """给 cg 实例挂热缓存（幂等：已挂则不重复）。

    容量解析优先级：显式入参 > env（MDCG_HOTCACHE_MAX_NODES /
    MDCG_HOTCACHE_MAX_QUERIES）> 模块级常量（issue #28：容量可配，
    大库须调大，否则 LRU 持续淘汰使热缓存形同虚设）。
    """
    if getattr(cg, "_hotcache", None) is not None:
        return cg._hotcache

    def _cap(explicit, env_key, default):
        if explicit is not None:
            return explicit
        raw = os.environ.get(env_key, "").strip()
        if raw:
            try:
                return int(raw)
            except ValueError:
                pass
        return default

    cg._hotcache = HotCache(
        max_nodes=_cap(max_nodes, "MDCG_HOTCACHE_MAX_NODES", MAX_NODES),
        max_queries=_cap(max_queries, "MDCG_HOTCACHE_MAX_QUERIES",
                         MAX_QUERIES))
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
