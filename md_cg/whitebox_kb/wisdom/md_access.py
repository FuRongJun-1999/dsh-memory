# -*- coding: utf-8 -*-
"""md 语料统一只读访问层 —— 白箱检索层直查 SQL 的 md 数据源后端。

背景与目标
----------
白箱检索层（`semantic_translate.py` 等）存在 ~8 处深度直查 SQL
（`dex.store.conn.execute("SELECT ... FROM nodes ...")`——KCCS 注释索引、
学科路由、四要素卡递归、知识点对齐）。md 语料是唯一知识来源
（`migrate_wisdom_graph` 导出 + test_p44 三层校验），检索库只是
`build_db_from_md()` 的可重建派生物。本模块把检索层的**知识查询**面
切换到 md 语料直读，SQLite 检索库降级为纯派生缓存（可丢弃）。

设计（零行为分叉的三条保障）
----------------------------
1. **行同构**：md frontmatter → 检索库 nodes 表 16 列，映射逻辑与
   `md_cg/md_whitebox.py::_restore` 逐字段一致（列值序列化同为
   `json.dumps(ensure_ascii=False)`，故 SQL LIKE 子串匹配逐位等价）。
2. **行序复刻**：无 ORDER BY 的 SELECT 在 SQLite 返回插入序；
   本层按 `LAYERS` 权威序 × os.walk 序遍历（= `_restore` 的插入序），
   `fetchone` / `LIMIT 1` 语义等价。
3. **对拍守卫**：`md_cg/test_md_access_parity.py` 把全部真实直查 SQL
   在两个后端上跑，逐行逐列断言相等——分叉即测试红。

范围（诚实边界）
----------------
- 只解释白箱检索层实际使用的 SELECT 子集文法：
  `SELECT <cols|*> FROM nodes [WHERE <conj>] [LIMIT n]`，
  谓词仅 `col = 'x'` / `col LIKE ?` / `col NOT LIKE ?`（AND 连接）。
  超出文法 → `NotImplementedError`（fail-closed，不静默错执行）。
- 写语句一律拒绝（打样阶段）；`increment_access` 类统计写的
  md 真源化属后续增量（写路径裁定：知识写走 mdcg.add）。
- 引擎内部面（`store.query_nodes` / `get_node` 等高层方法）不经本层，
  仍走原库——`aeis_core` 属引擎自有存储，不在本工程范围。

用法
----
    from md_access import MdConn, read_conn

    conn = read_conn(dex)          # WB_MD_DIRECT=1 → MdConn；否则派生库
    row = conn.execute("SELECT id FROM nodes WHERE layer='knowledge' "
                       "AND state_attributes LIKE ? LIMIT 1",
                       ('%"name": "X"%',)).fetchone()

环境开关：`WB_MD_DIRECT=1` 启用 md 直读；`WB_MD_ROOT` 指定 md 语料根
（缺省回落派生库，诚实降级不猜路径）。
"""
from __future__ import annotations

import json
import os
import re

try:  # dsh 部署形态：复用 md_cg 的权威 frontmatter 解析（零解析差异）
    from nodefile import loads as _nf_loads
except ImportError:  # 独立部署形态：白箱自包含解析（对拍测试守卫等价性）
    _nf_loads = None

#: nodes 表 16 列（权威列序，与 aeis_core CREATE TABLE / STNode.from_row 一致）
COLS = ("id", "content", "modality", "spatial_coordinates",
        "temporal_coordinate", "condition_space", "importance",
        "confidence", "layer", "access_count", "last_access",
        "created_at", "tags", "semantic_coordinates", "state_attributes",
        "entity_id")
_COL_IDX = {c: i for i, c in enumerate(COLS)}

#: md 语料层目录权威序（行序 = _restore 插入序的关键；与 mdcg.LAYERS 一致）
LAYERS = ("anchor", "structural", "knowledge", "contextual", "self",
          "rejected", "unresolved", "goals")


# --------------------------------------------------------------------------
# frontmatter 解析
# --------------------------------------------------------------------------

def _parse_node_text(text):
    """md 节点文本 → (fm dict, content str)。

    有 nodefile 用权威实现；否则解析单行 YAML 简形（`key: value`，
    值用 json.loads 全覆盖 dict/list/数字/null/带引号字符串，
    失败回落原样字符串）。
    """
    if _nf_loads is not None:
        return _nf_loads(text)
    fm, content = {}, text
    if text.startswith("---"):
        lines = text.split("\n")
        try:
            end = lines.index("---", 1)
        except ValueError:
            return fm, content
        for line in lines[1:end]:
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip()
            if not k:
                continue
            try:
                fm[k] = json.loads(v)
            except (ValueError, TypeError):
                fm[k] = v
        content = "\n".join(lines[end + 1:])
        if content.startswith("\n"):
            content = content[1:]
    return fm, content


def _load_rows(root, layers):
    """md 语料 → 16 列行元组列表。

    列映射与 `md_whitebox._restore` 逐字段一致。行序规范（两处统一）：
    **(LAYERS 序, 相对路径字典序)**——`os.walk` 在 Windows 上顺序无保证，
    显式排序才有确定性；`md_whitebox._restore` 按同一规范排列插入序，
    故 MdConn 与派生库的行序结构性一致。
    """
    decorated = []
    layer_ord = {name: i for i, name in enumerate(layers)}
    for layer in layers:
        base = os.path.join(root, layer)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, files in os.walk(base):
            for fn in files:
                if not fn.endswith(".md"):
                    continue
                try:
                    with open(os.path.join(dirpath, fn),
                              encoding="utf-8") as f:
                        text = f.read()
                except OSError:
                    continue
                fm, content = _parse_node_text(text)
                nid = fm.get("id") or fn[:-3]
                rel = os.path.relpath(os.path.join(dirpath, fn),
                                      root).replace("\\", "/")

                def _js(v, default="{}"):
                    if v is None or v == "":
                        return default
                    if isinstance(v, str):
                        return v
                    try:
                        return json.dumps(v, ensure_ascii=False)
                    except (TypeError, ValueError):
                        return default

                def _f(v, default=0.0):
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        return default

                decorated.append((layer_ord.get(layer, 99), rel, (
                    str(nid),
                    content or "",
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
                    _js(fm.get("state_attributes")),
                    fm.get("entity_id"),
                )))
    decorated.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in decorated]


# --------------------------------------------------------------------------
# SQL 子集解释器
# --------------------------------------------------------------------------

_LIKE_CACHE = {}


def _like_re(pattern):
    """SQL LIKE 模式 → 全匹配正则（% 任意串 / _ 任一字符，
    ASCII 大小写不敏感——对齐 SQLite 默认 LIKE 语义）。"""
    rx = _LIKE_CACHE.get(pattern)
    if rx is None:
        parts = []
        for ch in pattern:
            if ch == "%":
                parts.append("[\\s\\S]*")
            elif ch == "_":
                parts.append("[\\s\\S]")
            else:
                parts.append(re.escape(ch))
        rx = re.compile("".join(parts) + r"\Z", re.IGNORECASE)
        _LIKE_CACHE[pattern] = rx
    return rx


def _cmp_like(value, pattern, negate):
    """SQLite 三值 LIKE 语义：NULL 参与 → 未选中（NOT LIKE 同）。"""
    if value is None or pattern is None:
        return False
    hit = bool(_like_re(pattern).match(str(value)))
    return (not hit) if negate else hit


_SELECT_RE = re.compile(
    r"\s*SELECT\s+(?P<cols>.+?)\s+FROM\s+nodes"
    r"(?:\s+WHERE\s+(?P<where>.+?))?"
    r"(?:\s+LIMIT\s+(?P<limit>\d+))?\s*\Z",
    re.I | re.S)
_TERM_RE = re.compile(
    r"\s*(?P<col>[a-z_]+)\s*"
    r"(?P<op>NOT\s+LIKE|LIKE|=)\s*"
    r"(?P<val>\?|'[^']*')\s*(?:AND|$)", re.I)


class _Cursor:
    """结果集：fetchone / fetchall / 迭代（与 sqlite3.Cursor 子集兼容）。"""

    def __init__(self, rows):
        self._rows = rows
        self._i = 0

    def fetchone(self):
        if self._i >= len(self._rows):
            return None
        r = self._rows[self._i]
        self._i += 1
        return r

    def fetchall(self):
        out = self._rows[self._i:]
        self._i = len(self._rows)
        return list(out)

    def __iter__(self):
        return iter(self._rows)


class MdConn:
    """md 语料只读连接：`execute(sql, params)` 与 sqlite3.Connection
    的读子集同签名；行源懒加载一次缓存（进程内单例见 `read_conn`）。"""

    def __init__(self, root, layers=None):
        self.root = os.path.abspath(root)
        self._layers = tuple(layers) if layers else LAYERS
        self._rows = None
        self._edge_map = None    # {source_id: [edge_dict, ...]}（fm.edges）
        self._child_map = None   # {parent_id: [child_id, ...]}（subgraph.nodes）

    def _all_rows(self):
        if self._rows is None:
            if not os.path.isdir(self.root):
                raise FileNotFoundError(
                    f"[md_access] md 语料根不存在: {self.root}")
            self._rows = _load_rows(self.root, self._layers)
        return self._rows

    def reload(self):
        """丢弃全部缓存（行 + 边域）——写入方更新语料后刷新快照。"""
        self._rows = None
        self._edge_map = None
        self._child_map = None

    def _edge_domain(self):
        """边域懒加载（第二遍扫描，仅边访问器触发；检索读路径零开销）。

        fm.edges（causal/similar 等非层级边）与 fm.subgraph.nodes（层级边，
        落点=父节点）——与 md_whitebox._restore 还原 edges 表的两大数据源
        一致。
        """
        if self._edge_map is None:
            em, cm = {}, {}
            for layer in self._layers:
                base = os.path.join(self.root, layer)
                if not os.path.isdir(base):
                    continue
                for dirpath, _dirs, files in os.walk(base):
                    for fn in files:
                        if not fn.endswith(".md"):
                            continue
                        try:
                            with open(os.path.join(dirpath, fn),
                                      encoding="utf-8") as f:
                                text = f.read()
                        except OSError:
                            continue
                        fm, _content = _parse_node_text(text)
                        nid = str(fm.get("id") or fn[:-3])
                        edges = fm.get("edges")
                        if isinstance(edges, list) and edges:
                            em[nid] = [e for e in edges
                                       if isinstance(e, dict)]
                        sg = fm.get("subgraph")
                        if isinstance(sg, dict):
                            subs = sg.get("nodes")
                            if isinstance(subs, list) and subs:
                                cm[nid] = [str(x) for x in subs]
            self._edge_map, self._child_map = em, cm
        return self._edge_map, self._child_map

    # -- 边域访问器（SQL 文法保持 nodes-only fail-closed，边查询走窄方法） --

    def has_edge(self, source_id, target_id, relation_type):
        """`SELECT id FROM edges WHERE source_id=? AND target_id=?
        AND relation_type=?` 的等价查询（causal/similar 幂等判重）。"""
        em, _cm = self._edge_domain()
        for e in em.get(str(source_id)) or ():
            if (str(e.get("target") or "") == str(target_id)
                    and str(e.get("relation_type") or "") == str(relation_type)):
                return True
        return False

    def edges_between(self, source_id, target_id, relation_type=None):
        """source→target 的出边 dict 列表（relation_type 可选过滤）。

        供调用侧做边内字段判据（如 separation 边的
        condition_space.observation_position）——文法不扩，判据留调用侧。
        """
        em, _cm = self._edge_domain()
        out = []
        for e in em.get(str(source_id)) or ():
            if str(e.get("target") or "") != str(target_id):
                continue
            if relation_type is not None and str(
                    e.get("relation_type") or "") != str(relation_type):
                continue
            out.append(e)
        return out

    def children_of(self, node_id):
        """层级子节点 id 列表（fm.subgraph.nodes 落点）。"""
        _em, cm = self._edge_domain()
        return list(cm.get(str(node_id)) or [])

    def top_content_match(self, word, exclude_id):
        """`SELECT id FROM nodes WHERE content LIKE ? AND id != ?
        ORDER BY importance DESC, length(content) LIMIT 1` 的等价查询。

        同 key 时保持扫描序优先（与 sqlite rowid 序同构——插入序规范）。
        """
        rx = _like_re("%" + str(word) + "%")
        best = None
        best_key = None
        for r in self._all_rows():
            cid = r[0]
            if cid == exclude_id:
                continue
            c = r[1] or ""
            if not rx.match(c):
                continue
            key = (-(r[6] if r[6] is not None else 0.0), len(c))
            if best_key is None or key < best_key:
                best, best_key = (cid,), key
        return best

    # -- SQL 解析 -----------------------------------------------------------

    def _parse(self, sql):
        m = _SELECT_RE.match(sql.strip().rstrip(";"))
        if not m:
            raise NotImplementedError(
                f"[md_access] SQL 超出只读子集文法（fail-closed）: "
                f"{sql[:120]!r}")
        cols = m.group("cols").strip()
        if cols != "*":
            names = [c.strip() for c in cols.split(",")]
            for c in names:
                if c not in _COL_IDX:
                    raise NotImplementedError(
                        f"[md_access] 未知列 {c!r}（fail-closed）")
            cols = names
        where = m.group("where")
        preds, nparams = [], 0
        if where:
            pos = 0
            while pos < len(where):
                tm = _TERM_RE.match(where, pos)
                if not tm or tm.end() == pos:
                    raise NotImplementedError(
                        f"[md_access] 谓词超文法（fail-closed）: "
                        f"{where[pos:pos + 60]!r}")
                col = tm.group("col").lower()
                if col not in _COL_IDX:
                    raise NotImplementedError(
                        f"[md_access] 谓词列未知 {col!r}（fail-closed）")
                op = tm.group("op").upper()
                val = tm.group("val")
                preds.append((col, op, val, nparams))
                if val == "?":
                    nparams += 1
                pos = tm.end()
        limit = int(m.group("limit")) if m.group("limit") else None
        return cols, preds, nparams, limit

    # -- 执行 ---------------------------------------------------------------

    def execute(self, sql, params=()):
        head = sql.lstrip()[:6].upper()
        if head != "SELECT":
            raise NotImplementedError(
                f"[md_access] 只读访问层拒绝写语句（fail-closed）: "
                f"{sql[:80]!r}")
        params = tuple(params or ())
        cols, preds, nparams, limit = self._parse(sql)
        if len(params) != nparams:
            raise ValueError(
                f"[md_access] 参数个数不符: 期望 {nparams} 实得 {len(params)}")
        idx = _COL_IDX
        rows = self._all_rows()
        out = []
        for r in rows:
            ok = True
            for col, op, val, pi in preds:
                v = r[idx[col]]
                if op == "=":
                    lit = val[1:-1] if val != "?" else str(params[pi])
                    if v is None or str(v) != lit:
                        ok = False
                        break
                else:
                    pat = params[pi] if val == "?" else val[1:-1]
                    if not _cmp_like(v, pat, op == "NOT LIKE"):
                        ok = False
                        break
            if ok:
                out.append(r if cols == "*" else tuple(r[idx[c]]
                                                       for c in cols))
                if limit is not None and len(out) >= limit:
                    break
        return _Cursor(out)

    def close(self):
        self._rows = None


# --------------------------------------------------------------------------
# 检索读路径统一入口
# --------------------------------------------------------------------------

_CONN_CACHE = {}


def _md_conn_or_none():
    """WB 开关生效则返回 MdConn 单例，否则 None（调用方自行回落原路径）。"""
    if os.environ.get("WB_MD_DIRECT") != "1":
        return None
    root = os.environ.get("WB_MD_ROOT") or ""
    if not root or not os.path.isdir(root):
        return None
    conn = _CONN_CACHE.get(root)
    if conn is None:
        conn = _CONN_CACHE[root] = MdConn(root)
    return conn


def read_conn(dex):
    """白箱检索读路径统一入口。

    `WB_MD_DIRECT=1` 且 `WB_MD_ROOT` 指向存在的 md 语料根 → 返回该根的
    MdConn 单例（md 直读）；否则回落 `dex.store.conn`（派生库，
    零行为变更）。缺省回落是**诚实降级**：缺配置时不猜路径。
    """
    conn = _md_conn_or_none()
    if conn is not None:
        return conn
    return dex.store.conn
