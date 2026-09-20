# -*- coding: utf-8 -*-
"""md_cg · md 原生知识库的白箱问答（md 做知识库 · 白箱做检索与回答）。

要回答的问题
------------
`md_cg/migrate_wisdom_graph.py` 已把白箱认知图（`wisdom-book-cloud.db`：
nodes 4355 / edges 2948）无损导出为 md 认知图（`_md_cg_wisdom_graph/`），
并以确定性三层校验证明「md 侧与原库逐节点等价」。本模块把结论推进到
**端到端**：这份 md 语料直接当知识库时，白箱的检索与回答能力能否原样复现。

为什么需要「还原」这一步
------------------------
白箱检索层（`whitebox_kb/wisdom/semantic_translate.py`、`chat_engine.py`、
`card_validator.py`、`neural_retrieve.py` 等）并非只调用 `dex` 的高层接口，
历史上**深度直查 SQL**——KCCS 注释索引、学科路由、四要素卡递归、知识点
对齐等 8 处 `dex.store.conn.execute("SELECT ... FROM nodes ...")`。
逐处语法翻译成「读 md」既侵入又易错，还会让两条路径的行为悄悄分叉。

**读路径现已收口到 md 直读访问层**（`whitebox_kb/wisdom/md_access.py`）：
8 处直查统一经 `read_conn(dex)`，`WB_MD_DIRECT=1` 时走 md 语料
（SELECT 子集解释器 + 行同构/行序复刻，对拍守卫
`test_md_access_parity` 逐位一致），否则回落派生库。逐处语法翻译的
教训由「同接口 + 机械对拍」替代：SQL 语义不翻写，数据源切换，
行为分叉由测试红挡住。

故本模块仍把 md 语料还原成**同 schema 的检索库**，作为派生库回落
路径与引擎初始化底座，白箱全部确定性检索逻辑零改动运行：

    md 语料（唯一知识来源）
        │  build_db_from_md()      ← 本模块
        ▼
    检索库（同 schema · 可随时重建的派生物）
        │  WhiteboxEngine          ← 白箱引擎（seed=False，不污染语料）
        │        ↑ read_conn(dex)  ← WB_MD_DIRECT=1 时检索读走 md 直读
        ▼
    回答（route / reply / hits）

保真性依据
----------
md frontmatter 是 `STNode` 的**无损**序列化：`id / layer / tags /
condition_space / semantic_coordinates / state_attributes / importance /
confidence / modality / access_count / last_access / created_at / entity_id`
逐字段对应；正文即 `content`；层级边落在**父节点**的 `subgraph.nodes`
（对应源库 `hierarchical`，source=父），非层级边落在 `edges`
（键名 `relation_type`）。故还原不丢字段、不丢边。

用法
----
    from md_cg.md_whitebox import MdWhitebox

    with MdWhitebox(verbose=True) as wb:
        print(wb.ask("为什么会打雷").get("reply"))

命令行自检：`python -m md_cg.md_whitebox 什么是条件论`
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
#: md 语料默认位置（`migrate_wisdom_graph` 的导出目标）
DEFAULT_ROOT = os.path.join(os.path.dirname(_HERE), "_md_cg_wisdom_graph")


# --------------------------------------------------------------------------
# frontmatter 值 → 列值
# --------------------------------------------------------------------------

# 生效条件：v 为 None 或等于空串时返回 default，v 已是 dict/list 时原样返回 v，否则尝试 json.loads(v)，抛 ValueError/TypeError 时返回 default；
def _j(v, default):
    """frontmatter 值 → Python 对象（已是容器则原样，字符串则尝试 JSON）。"""
    if v is None or v == "":
        return default
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (ValueError, TypeError):
        return default


# 生效条件：v 为 None 或等于空串时返回 default（缺省 "{}"），v 是 str 时原样返回 v，否则 json.dumps(v, ensure_ascii=False)，抛 TypeError/ValueError 时返回 default；
def _js(v, default="{}"):
    """frontmatter 值 → JSON 文本（入 TEXT 列）。"""
    if v is None or v == "":
        return default
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, ensure_ascii=False)
    except (TypeError, ValueError):
        return default


# 生效条件：float(v) 成功即返回该浮点值，抛 TypeError/ValueError 时返回 default（缺省 0.0）；
def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# 生效条件：对 root（缺省 DEFAULT_ROOT）取 os.path.abspath 的 utf-8 字节 sha1 前 12 位为 key，返回系统临时目录下 f"md_cg_native_{key}.db"；
def default_db_path(root=DEFAULT_ROOT):
    """还原库默认位置：系统临时目录。

    还原库是**派生物**（md 是唯一真源），故默认落在临时目录，可随时丢弃重建；
    路径按 `root` 哈希区分，避免不同语料互相覆盖。
    """
    key = hashlib.sha1(os.path.abspath(root).encode("utf-8")).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), f"md_cg_native_{key}.db")


# 生效条件：root 为目录且其下（递归）至少有一个 .md 文件时返回 None，目录缺失返回不存在说明，目录存在但无 .md 返回空壳说明；
def corpus_gap(root=DEFAULT_ROOT):
    """md 语料未就绪的原因（None = 就绪）；**判据单一真源**。

    空壳不算就绪（2026-09-20 v14 缺陷 F）：`MdCGOS(root)` 会 `makedirs(root)`，
    于是任何经 `build_db_from_md`/兄弟测试走一遭的调用都会留下
    `_md_cg_wisdom_graph/` **空目录**——而 runner 的依赖探测与测试模块的
    「组A/组D 是否执行」若只判 `isdir`，就会把空壳误判成「真源就绪」，
    把本该 SKIP 的目标变成 FAIL（旁路执行一次即触发，非构造的极端场景）。
    """
    if not os.path.isdir(root):
        return ("md 语料根不存在：%s（.gitignore 忽略，需本地生成）" % root)
    for _dp, _dn, fs in os.walk(root):
        if any(str(f).endswith(".md") for f in fs):
            return None
    return ("md 语料根为空壳（目录存在但无 .md 文件）：%s"
            "——空壳不算就绪（多为兄弟测试创建的残留）" % root)


# 生效条件：corpus_gap(root) 为 None 时返回 True，否则 False；
def corpus_ready(root=DEFAULT_ROOT) -> bool:
    """md 语料是否就绪（目录存在**且含 .md**）。"""
    return corpus_gap(root) is None


# 生效条件：db_path 能以只读 uri 连接并成功统计 nodes/edges 两表行数时返回 (int(n), int(e))，否则在任一步抛异常时返回 (0, 0)；
def _counts(db_path):
    """(nodes, edges) 计数；不可读返回 (0, 0)。"""
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        n = con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        e = con.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        con.close()
        return int(n), int(e)
    except Exception:
        return 0, 0


# 生效条件：给定 src/tgt/rel/conf/ver 即返回列序对齐 edges 表的 11 元组，id 由 str(src)/str(tgt) 与 rel 拼接，rel 为假值（None/空串）时以 "similar" 参与拼接并 strip().lower()，ver 为假值时 int(ver or 0) 取 0；
def _edge_row(src, tgt, rel, conf, ver):
    """边行（列序对齐 `aeis_core` 的 edges 表）。"""
    src, tgt = str(src), str(tgt)
    rel = str(rel or "similar").strip().lower()
    return (f"e:{src}>{tgt}:{rel}", src, tgt, rel, "{}", conf, 1.0,
            int(ver or 0), 0.0, 0.0, "extracted")


# 生效条件：传入 cg 与 con 时按 (LAYERS 序, 路径字典序) 排序 cg.index["nodes"] 逐条建行，cg.get(nid) 为假值则跳过该节点，子图/边来自节点的 frontmatter，最终 executemany 写入两表并 commit，返回 (nodes 行数, edges 行数)；
def _restore(cg, con, verbose=False):
    """md 语料 → 检索库（nodes / edges 两表）。返回 (n_nodes, n_edges)。

    插入序规范 = **(LAYERS 序, 相对路径字典序)**（与白箱访问层
    `whitebox_kb/wisdom/md_access.py::_load_rows` 同规范）：索引运行时序
    （json 基础序 + 增量日志回放）含历史迁移序噪声且不可复现，
    派生库行序必须由 md 实时状态确定性决定。
    """
    from .mdcg import LAYERS as _md_layers
    _ord = {name: i for i, name in enumerate(_md_layers)}

# 生效条件：nid 的 cg.index["nodes"] 条目（无条目或值为假则视为空 dict）中 path 为真时取其为 p，否则用 layer 或 "zz" 拼 f"{nid}.md"、反斜杠替换为 "/"，返回 (LAYERS 序表的 .get(p 首段, 99), p)；
    def _order_key(nid):
        e = cg.index["nodes"].get(nid) or {}
        p = str(e.get("path")
                or f"{e.get('layer') or 'zz'}/{nid}.md").replace("\\", "/")
        return (_ord.get(p.split("/", 1)[0], 99), p)

    ids = sorted(cg.index["nodes"], key=_order_key)
    n_rows, e_rows = [], []
    for i, nid in enumerate(ids, 1):
        d = cg.get(nid)
        if not d:
            continue
        fm = d.get("frontmatter") or {}
        n_rows.append((
            str(nid),
            d.get("content") or "",
            fm.get("modality") or "text",
            _js(fm.get("spatial")),
            _f(fm.get("temporal"), None),
            _js(fm.get("condition_space")),
            _f(fm.get("importance"), 0.5),
            _f(fm.get("confidence"), 0.6),
            fm.get("layer") or "knowledge",
            int(_f(fm.get("access_count"), 0)),
            _f(fm.get("last_access"), 0),
            _f(fm.get("created_at"), 0),
            _js(fm.get("tags"), "[]"),
            _js(fm.get("semantic_coordinates")),
            _js(_j(fm.get("state_attributes"), {})),
            fm.get("entity_id"),
        ))
        # 层级边：父节点声明的 subgraph.nodes（源库 hierarchical，source=父）
        for c in (_j(fm.get("subgraph"), {}) or {}).get("nodes") or []:
            e_rows.append(_edge_row(nid, c, "hierarchical", 1.0, 1))
        # 非层级边：similar / causal 等
        for e in _j(fm.get("edges"), []) or []:
            if not isinstance(e, dict) or not e.get("target"):
                continue
            e_rows.append(_edge_row(
                nid, e.get("target"),
                e.get("relation_type") or e.get("relation") or "similar",
                _f(e.get("confidence"), 0.7), int(_f(e.get("verified"), 0))))
        if verbose and i % 1500 == 0:
            print(f"[md_whitebox] …已还原 {i}/{len(ids)}", flush=True)

    con.executemany(
        "INSERT OR REPLACE INTO nodes (id, content, modality, spatial_coordinates,"
        " temporal_coordinate, condition_space, importance, confidence, layer,"
        " access_count, last_access, created_at, tags, semantic_coordinates,"
        " state_attributes, entity_id)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", n_rows)
    con.executemany(
        "INSERT OR REPLACE INTO edges (id, source_id, target_id, relation_type,"
        " condition_space, confidence, weight, verified, created_at,"
        " last_verified, source_evidence)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)", e_rows)
    con.commit()
    return len(n_rows), len(e_rows)


# 生效条件：corpus_gap(root) 非 None 即抛 FileNotFoundError（**不建空库、不建目录**）；db_path 为假值（None/空串）时回落 default_db_path(root)，当 not force 且 os.path.exists(db_path) 为真且 _counts 得 nodes>0 时直接返回 {reused: True}，否则删除该路径后以 MdCGOS(root) 与 SpacetimeMemoryEngine 经 _restore 重建并返回 {reused: False}，root 缺省 DEFAULT_ROOT；
def build_db_from_md(root=DEFAULT_ROOT, db_path=None, force=False, verbose=True):
    """把 md 语料还原为白箱检索引擎可用的库（幂等：已存在且非空则复用）。

    返回 `{db, nodes, edges, reused, root}`。

    **fail-closed**（2026-09-20 v14 缺陷 F 根因修复）：语料未就绪即抛
    `FileNotFoundError`，**不建空库、也绝不建空壳目录**——旧实现直接
    `MdCGOS(root)`（内部 `makedirs`），一次误调就在仓根留下
    `_md_cg_wisdom_graph/` 空壳，把兄弟测试的依赖探测从 SKIP 变 FAIL。
    """
    gap = corpus_gap(root)
    if gap:
        raise FileNotFoundError(
            "md 语料真源未就绪：%s\n  生成：python -m md_cg.migrate_wisdom_graph "
            "--db <sqlite 路径> --root %s" % (gap, root))
    from . import whitebox_kb  # noqa: F401 —— 触发平铺导入的 sys.path 引导
    from .mdcos import MdCGOS
    from aeis_core import SpacetimeMemoryEngine

    db_path = os.path.abspath(db_path or default_db_path(root))
    if not force and os.path.exists(db_path):
        n, e = _counts(db_path)
        if n > 0:
            if verbose:
                print(f"[md_whitebox] 复用还原库：{db_path}"
                      f"（nodes={n} edges={e}）", flush=True)
            return {"db": db_path, "nodes": n, "edges": e, "reused": True,
                    "root": root}

    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)

    cg = MdCGOS(root)
    eng = SpacetimeMemoryEngine(db_path=db_path, identity="md原生白箱")
    try:
        n_nodes, n_edges = _restore(cg, eng.store.conn, verbose=verbose)
    finally:
        cg.close()
        eng.close()

    if verbose:
        print(f"[md_whitebox] 还原完成：{db_path}"
              f"（nodes={n_nodes} edges={n_edges}）", flush=True)
    return {"db": db_path, "nodes": n_nodes, "edges": n_edges, "reused": False,
            "root": root}


# --------------------------------------------------------------------------
# 门面：md 语料驱动的白箱问答
# --------------------------------------------------------------------------

# 生效条件：以 root=DEFAULT_ROOT、db_path=None、force_rebuild=False、verbose=False 构造时，__init__ 调用 build_db_from_md 并把 stats["db"] 记为实例 db_path、_engine 置 None；
class MdWhitebox:
    """md 语料驱动的白箱问答。

    知识来自 md 语料（与源库同源但**不依赖源库**），检索与回答走白箱自带
    引擎。`seed=False`：随包种子卡是另一份知识，不该混进 md 语料还原库。
    """

# 生效条件：root 缺省 DEFAULT_ROOT、db_path 缺省 None（交由 build_db_from_md 回落默认路径）、force_rebuild 缺省 False（作为 force 传入）、verbose 缺省 False 时，调用 build_db_from_md 并将 stats["db"] 存入 self.db_path、self._engine 置 None；
    def __init__(self, root=DEFAULT_ROOT, db_path=None, force_rebuild=False,
                 verbose=False):
        self.root = root
        self.stats = build_db_from_md(root, db_path, force=force_rebuild,
                                      verbose=verbose)
        self.db_path = self.stats["db"]
        self._engine = None

    @property
# 生效条件：self._engine 为 None 时以 db_path=self.db_path、seed=False 构造 WhiteboxEngine 并缓存，否则直接返回已缓存实例；
# 生效条件：不适用（无必需形参与模块级常量）
    def engine(self):
        if self._engine is None:
            from .whitebox_kb.engine import WhiteboxEngine
            self._engine = WhiteboxEngine(db_path=self.db_path, seed=False)
        return self._engine

# 生效条件：question 给定（session_id 缺省 "md-whitebox-eval"）时返回 self.engine.chat(question, session_id=session_id) 的结果；
    def ask(self, question, session_id="md-whitebox-eval"):
        """白箱问答。返回含 `route` / `reply` / `hits` 的原始结果。"""
        return self.engine.chat(question, session_id=session_id)

# 生效条件：不适用（无必需形参与模块级常量）
    def close(self):
        if self._engine is not None:
            self._engine.close()
            self._engine = None

# 生效条件：不适用（无必需形参与模块级常量）
    def __enter__(self):
        return self

# 生效条件：不适用（无必需形参与模块级常量）
    def __exit__(self, *exc):
        self.close()
        return False


if __name__ == "__main__":  # 手动自检：python -m md_cg.md_whitebox <问题>
    q = " ".join(sys.argv[1:]) or "什么是条件论"
    with MdWhitebox(verbose=True) as wb:
        res = wb.ask(q)
    print(json.dumps({"question": q, "route": res.get("route"),
                      "reply": res.get("reply"),
                      "hits": (res.get("hits") or [])[:5]},
                     ensure_ascii=False, indent=2))