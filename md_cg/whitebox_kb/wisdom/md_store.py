# -*- coding: utf-8 -*-
"""MdStore · 智慧之书知识层的 md 真源存储适配器（LayeredStore 读子集等价实现）。

背景（使用者裁定 2026-09-14）
----------------------------
「智慧之书知识源本身就是 md 文档，当前的 sql 导致的黑箱化不能接受」。
md 语料是唯一知识来源（`migrate_wisdom_graph.export()` 导出 + L1-L4
确定性校验），SQLite 检索库只是可重建派生物。此前 `md_access` 已把
检索层直查 SQL 切到 md 直读，但 `ConditionDex` 的 25+ 个 `dex_*`
操作走引擎高层面（`store.get_node / query_nodes / get_*_edges /
search_content`），仍依赖 sqlite——本模块补齐这块：以 md 语料为
真源装载内存图，实现 LayeredStore 被依赖的读子集。

等价性设计（对拍守卫 md_cg/test_wisdom_md_store.py）
----------------------------------------------------
1. **行同构**：节点行直接复用 `md_access._load_rows`（与
   `md_whitebox._restore` 逐字段一致），`STNode.from_row` 权威反序列化。
2. **行序复刻**：遍历序 = (LAYERS 权威序, 相对路径字典序)——与
   sqlite 无 ORDER BY SELECT 的插入序同构，`query_nodes(limit)` 语义等价。
3. **边域还原**：fm.edges（causal/similar 等非层级边）+ fm.subgraph.nodes
   （hierarchical 层级边，source=父）——与派生库 edges 表两大数据源一致；
   未知 relation_type 诚实跳过（宽容读，严格写）。
4. **search_content 复刻**：多词 OR 预筛（含同义词扩展，复用
   `LayeredStore.SYNONYM_GROUPS`；ASCII 折叠对齐 LIKE 大小写语义）→
   原查询 char-bigram 重叠率 + tag bonus → (-sim, -importance, id)
   排序——算法逐行对齐 `LayeredStore.search_content`（v1.17 起
   两侧截断与同分决胜均确定性化：候选池 id 序截断 + id 末键决胜，
   输出不依赖 sqlite 物理插入序 / md 路径字典序的偶然差异）。

诚实边界
--------
- `increment_access`：md 模式下为**进程内统计**（不落盘）。sqlite 版
  同为统计性质（尽力而为、可容忍失败）；P29 使用频次档案跨进程持久化
  属后续增量（写放大与价值须单独裁定）。
- `set_meta`：空操作——md 模式的项目元数据由语料本身承载。
- 写语句不进本层：知识写走 `ConditionDex` 的 md 分支（MdCGOS.add /
  append_edge），观测留痕走 `_perceive`（layer=contextual）。
"""
from __future__ import annotations

import hashlib
import json
import os

from aeis_core import ConditionSpace, EdgeType, MemoryLayer, STEdge, STNode
from aeis_core import LayeredStore  # SYNONYM_GROUPS 同义词表复用
from md_access import MdConn

#: 条件空间缺省声明（脏数据兜底——与 wisdom_book._default_cs 同口径的最简形态）
_CS_FALLBACK = {
    "observation_position": "智慧之书·md 真源语料",
    "observation_tool": "MdStore 内存图装载",
    "time_window": [0.0, 9999999999.0],
    "existence_constraint": "图谱只声称条件化有效性，不声称真理性",
}

#: sqlite LIKE 的 ASCII 大小写不敏感折叠（非 ASCII 字符原样）——
#: 预筛子串匹配与 `LIKE '%t%'` 逐位同构（md_access._like_re 同语义）
_ASCII_FOLD = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _fold(s):
    return s.translate(_ASCII_FOLD)


def _safe_cs(raw):
    """fm.condition_space（dict）→ ConditionSpace；脏数据回落固定声明，不炸读路径。"""
    if isinstance(raw, dict) and raw:
        try:
            return ConditionSpace.from_json(json.dumps(raw, ensure_ascii=False))
        except (ValueError, TypeError):
            pass
    try:
        return ConditionSpace.from_json(json.dumps(_CS_FALLBACK, ensure_ascii=False))
    except (ValueError, TypeError):
        return ConditionSpace()


class MdStore:
    """md 语料 → 内存图。实现 LayeredStore 被 `ConditionDex` 依赖的读子集，
    外加 duck `.conn`（返回内部 MdConn，`md_access.read_conn` 零改动兼容）。"""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self._conn = MdConn(self.root)
        self._nodes = None     # {id: STNode}
        self._out = None       # {src_id: [STEdge]}
        self._in = None        # {dst_id: [STEdge]}
        self._access = {}      # {nid: count} 进程内使用频次（诚实边界见模块头）

    # ------------------------------------------------------------------
    # 装载
    # ------------------------------------------------------------------

    def _ensure(self):
        """懒加载：行→STNode，边域→STEdge 双向索引。"""
        if self._nodes is not None:
            return
        nodes = {}
        for r in self._conn._all_rows():
            try:
                row = list(r)
                if isinstance(row[1], str):
                    # md 正文天然以换行结尾——装载归一到 sqlite content 语义
                    # （sqlite 版 content 无尾换行；留痕/展示面不应混入空行）
                    row[1] = row[1].rstrip("\n")
                n = STNode.from_row(tuple(row))
            except (ValueError, TypeError, KeyError):
                continue  # 脏行诚实跳过（不阻断整库装载）
            nodes[n.id] = n
        out, inc = {}, {}

        def _link(src, e):
            ste = self._mk_edge(src, e)
            if ste is None:
                return
            out.setdefault(src, []).append(ste)
            inc.setdefault(ste.target_id, []).append(ste)

        em, cm = self._conn._edge_domain()
        for src, edges in em.items():          # causal/similar 等非层级边
            for e in edges:
                _link(src, e)
        for parent, kids in cm.items():        # hierarchical 层级边（source=父）
            for kid in kids:
                _link(parent, {"target": kid, "relation_type": "hierarchical"})
        self._nodes, self._out, self._in = nodes, out, inc

    @staticmethod
    def _mk_edge(src, e):
        """fm.edges 边 dict → STEdge；未知关系类型/脏字段返回 None（诚实跳过）。"""
        try:
            rel = EdgeType(str(e.get("relation_type") or ""))
        except ValueError:
            return None
        tgt = str(e.get("target") or "")
        if not tgt:
            return None
        eid = "mde_" + hashlib.sha1(
            f"{src}->{tgt}:{rel.value}".encode("utf-8")).hexdigest()[:12]
        return STEdge(
            id=eid, source_id=str(src), target_id=tgt,
            relation_type=rel,
            condition_space=_safe_cs(e.get("condition_space")),
            confidence=float(e.get("confidence", 0.7)),
            weight=float(e.get("weight", 1.0)),
            verified=bool(e.get("verified")),
            source_evidence=str(e.get("source_evidence") or "extracted"))

    def reload(self):
        """丢弃全部缓存——写入方（add_entry/add_relation）落盘后刷新快照。"""
        self._conn.reload()
        self._nodes = self._out = self._in = None

    # ------------------------------------------------------------------
    # LayeredStore 读子集
    # ------------------------------------------------------------------

    def get_node(self, node_id):
        self._ensure()
        return self._nodes.get(str(node_id))

    def query_nodes(self, layer=None, limit=50):
        self._ensure()
        val = layer.value if isinstance(layer, MemoryLayer) else (
            str(layer) if layer else None)
        out = [n for n in self._nodes.values()
               if val is None or n.layer.value == val]
        return out[:max(0, int(limit))]

    def get_outgoing_edges(self, node_id):
        self._ensure()
        return list(self._out.get(str(node_id)) or [])

    def get_incoming_edges(self, node_id):
        self._ensure()
        return list(self._in.get(str(node_id)) or [])

    def search_content(self, query, layers=None, limit=20):
        """复刻 `LayeredStore.search_content`（对拍守卫）：多词 OR 预筛
        （LIKE 子串语义，ASCII 大小写不敏感）→ 落空回退全池 → bigram
        重叠率 + tag bonus → (-sim, -importance, id) 排序截断。

        确定性口径（与权威实现 v1.17 同步）：预筛候选与回退池均按
        **id 升序截断**（对齐 ORDER BY id LIMIT），同分同重要度按 id
        决胜——两侧输出不依赖各自物理序（sqlite 插入序 / md 路径序）。"""
        q = (query or "").strip()
        if not q:
            return []
        self._ensure()
        pool = list(self._nodes.values())
        if layers:
            vals = {l.value if isinstance(l, MemoryLayer) else str(l)
                    for l in layers}
            pool = [n for n in pool if n.layer.value in vals]
        terms = LayeredStore.expand_query_terms(q)

        def _hit(n):
            c = _fold(n.content or "")
            tj = _fold(json.dumps(n.tags or [], ensure_ascii=False))
            return any(_fold(t) in c or _fold(t) in tj for t in terms)

        rows = sorted((n for n in pool if _hit(n)),
                      key=lambda n: n.id)[:300]
        if not rows:
            rows = sorted(pool, key=lambda n: n.id)[:500]
        qb = self._bigrams(q)
        scored = []
        for n in rows:
            nb = self._bigrams(n.content)
            sim = (len(qb & nb) / len(qb)) if qb else 0.0
            bonus = 0.05 if any(t in q or q in t for t in (n.tags or [])
                                ) else 0.0
            scored.append((n, min(1.0, sim + bonus)))
        scored.sort(key=lambda x: (-x[1], -x[0].importance, x[0].id))
        results = scored[:max(0, int(limit))]
        for n, _ in results:
            self.increment_access(n.id)
        return results

    @staticmethod
    def _bigrams(s):
        s = "".join((s or "").split())
        if len(s) <= 1:
            return {s}
        return {s[i:i + 2] for i in range(len(s) - 1)}

    def increment_access(self, node_id):
        """使用频次 +1（进程内统计，不落盘——诚实边界见模块头）。"""
        nid = str(node_id)
        self._access[nid] = self._access.get(nid, 0) + 1

    def access_counts(self):
        """进程内使用频次快照（P29 消费面）。"""
        return dict(self._access)

    # ------------------------------------------------------------------
    # 兼容面
    # ------------------------------------------------------------------

    @property
    def conn(self):
        """duck：`md_access.read_conn(dex)` 回落形态（MdConn 只读直读）。"""
        return self._conn

    def set_meta(self, *_a, **_k):
        """空操作：md 模式的项目元数据由语料本身承载。"""

    def close(self):
        """无连接可关（进程内缓存随实例回收）。"""
