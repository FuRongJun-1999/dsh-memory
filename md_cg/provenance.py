# -*- coding: utf-8 -*-
"""派生溯源（G8）：新增节点常态化建链 + 悬空可检出。

回答「这个节点**从哪来**」——与 `md_cg.links` 刻意分层：
  · `links.py`   = 跨节点信任（「我信你多少」，P_trust，落 `~/.mdcg/_links.json`）；
  · 本模块        = 节点派生关系（「它由谁派生」，落 `<root>/_link.jsonl`）。
两者都叫「链接」，但一个管**信任状态**、一个管**演进血缘**，不可混用。

存储形态（对齐「md 单一真相源 + 派生索引可重建」）：
  · 权威声明在节点 frontmatter（`derived_from` / `derived_relation`）；
  · `<root>/_link.jsonl` 是 **append-only 派生台账**（快查用，可由 frontmatter 重建）；
  · 建链失败写 `<root>/_link.jsonl.fail`（降级留痕）。

三条纪律（对齐 G8 裁定 §六）：
  1. **只对新增节点常态化建链，历史不回填**——`rebuild_ledger` 只重放 frontmatter
     里**已经声明**的关系，不为历史节点发明任何边（当前库历史声明为 0 → 重建为空）；
  2. **建链失败不得阻断写入**——`record()` 永不抛（best-effort），失败降级为告警 +
     失败台账留痕，节点写入照常提交；
  3. **巡检只读**——`check()` 检出悬空边（目标/子节点不在索引内）但**不自动删边**，
     关系事实去留由人处置。

零第三方依赖。
"""
from __future__ import annotations

import json
import os
import time

from . import trust as _trust
from .fsutil import FileLock, append_jsonl, atomic_write, read_jsonl

LEDGER_NAME = "_link.jsonl"
FAIL_SUFFIX = ".fail"
LEDGER_ENV = "MDCG_LINK_FILE"
SCHEMA = 1

#: 允许的派生关系（显式枚举，避免「自由字符串」把血缘写成噪声）
RELATIONS = ("derived_from", "split_from", "extracted_from",
             "merged_from", "refined_from", "source")
DEFAULT_RELATION = "derived_from"

#: frontmatter 里承载派生声明的字段（写路径只读这两处，不猜）
FM_FIELD = "derived_from"
FM_REL_FIELD = "derived_relation"

_LOCK_TIMEOUT = 2.0


class ProvenanceError(Exception):
    """派生溯源错误。写路径侧一律由 `record()` 兜住，不向上抛。"""


# --------------------------------------------------------------------------
# 路径 / 规范化
# --------------------------------------------------------------------------

# 生效条件：path 为真值时返回 path；否则 os.environ.get(LEDGER_ENV) 为非空真值时返回该环境变量值；否则返回 os.path.join(root, LEDGER_NAME)。
def ledger_file(root: str, path: str = None) -> str:
    """台账路径：显式 → MDCG_LINK_FILE → <root>/_link.jsonl。"""
    return path or os.environ.get(LEDGER_ENV) or os.path.join(root, LEDGER_NAME)


# 生效条件：传入 root（path 为真值则以其为准，否则由 ledger_file 的回落决定落点）时返回 ledger_file(root, path) 结果拼接 FAIL_SUFFIX。
def fail_log_file(root: str, path: str = None) -> str:
    """降级留痕路径（台账写不进时的「本该建的边」）。"""
    return ledger_file(root, path) + FAIL_SUFFIX


# 生效条件：value 为 None 返回 []；否则 list/tuple/set 逐个元素、其他类型视作单元素，元素经 str(x).strip() 后非空且未出现过才保留（重复只留首次）。
def as_list(value) -> list:
    """把单值 / 序列统一成去重、去空白的字符串列表。"""
    if value is None:
        return []
    items = list(value) if isinstance(value, (list, tuple, set)) else [value]
    out = []
    for x in items:
        s = str(x).strip()
        if s and s not in out:
            out.append(s)
    return out


# 生效条件：rel 为假值（None/空串）或 str(rel).strip().lower() 后为空白的串（如 "   "）时 r 回落 default（默认常量 DEFAULT_RELATION）；r 不在 RELATIONS 内（含回落后的 default 本身非法）即抛 ProvenanceError，否则返回该小写串。
def normalize_relation(rel, default: str = DEFAULT_RELATION) -> str:
    """严格校验关系名；非法抛 `ProvenanceError`（显式 API 用）。"""
    r = str(rel or "").strip().lower()
    if not r:
        r = default
    if r not in RELATIONS:
        raise ProvenanceError(f"未知派生关系：{rel}（允许：{RELATIONS}）")
    return r


# 生效条件：normalize_relation(rel, default) 抛 ProvenanceError（含 rel 为假值/仅空白且 default 非法时）则原样返回 default；否则返回该调用的返回值。
def coerce_relation(rel, default: str = DEFAULT_RELATION) -> str:
    """宽松兜底：非法关系名回退默认值（**写路径用，保证永不阻断写入**）。"""
    try:
        return normalize_relation(rel, default)
    except ProvenanceError:
        return default


# 生效条件：child 或 parent 为假值或仅空白使 str(x or "").strip() 为空、或二者 strip 后相等（自环）时返回 None；否则返回含 schema/t/child/parent/rel/batch/actor 的 dict，note 为真值时才附上并截断到 200 字符。
def make_edge(child, parent, *, relation=DEFAULT_RELATION, batch=None,
              actor="system", note=None, t=None):
    """构造一条派生边；自环 / 空端点返回 None（**不产生无意义边**）。"""
    c, p = str(child or "").strip(), str(parent or "").strip()
    if not c or not p or c == p:
        return None
    edge = {"schema": SCHEMA,
            "t": float(t if t is not None else time.time()),
            "child": c, "parent": p, "rel": coerce_relation(relation),
            "batch": batch, "actor": actor}
    if note:
        edge["note"] = str(note)[:200]
    return edge


# 生效条件：对 as_list(parents) 的每个父项调用 make_edge，只保留返回非 None 的边，全部被丢弃时返回空列表。
def edges_for(child, parents, **kw) -> list:
    """`(child, [parents]) → [edge]`：空端点 / 自环自动丢弃。"""
    out = []
    for p in as_list(parents):
        e = make_edge(child, p, **kw)
        if e:
            out.append(e)
    return out


# --------------------------------------------------------------------------
# 写：台账追加（record 为写路径唯一入口，永不抛）
# --------------------------------------------------------------------------

# 生效条件：edges 为 None/空/全为假元素时返回 0；否则在 FileLock(p, timeout=_LOCK_TIMEOUT) 内逐条 append_jsonl，抛 OSError 时转抛 ProvenanceError，成功返回 len(edges)。
def append(root: str, edges, *, path: str = None) -> int:
    """台账追加（加锁串行，防 Windows 并发交错丢边）。IO 失败抛 `ProvenanceError`。"""
    edges = [e for e in (edges or []) if e]
    if not edges:
        return 0
    p = ledger_file(root, path)
    try:
        os.makedirs(os.path.dirname(os.path.abspath(p)) or ".", exist_ok=True)
        with FileLock(p, timeout=_LOCK_TIMEOUT):
            for e in edges:
                append_jsonl(p, e)
    except OSError as exc:
        raise ProvenanceError(f"派生台账写入失败：{p}（{exc}）") from exc
    return len(edges)


# 生效条件：给定 root/path/child/parents/relation/reason/code 即恒返回 {'ok': False, 'added': 0, 'edges': [], 'degraded': True, 'degrade_code': code, 'reason': reason}，其中写 fail_log_file 台账的异常被 except Exception 吞掉。
def _degrade(root: str, path, child, parents, relation, reason,
             code: str) -> dict:
    """降级留痕：把「本该建的边」记进 .fail 台账（自身也 best-effort）。"""
    rec = {"t": time.time(), "code": code, "child": str(child or ""),
           "parents": as_list(parents), "rel": str(relation or ""),
           "reason": str(reason)[:300]}
    try:
        append_jsonl(fail_log_file(root, path), rec)
    except Exception:                                  # noqa: BLE001
        pass
    return {"ok": False, "added": 0, "edges": [], "degraded": True,
            "degrade_code": code, "reason": reason}


# 生效条件：edges_for 抛异常时经 _degrade(code='bad_edge') 返回；edges 为空时返回 {'ok': True, 'added': 0, 'edges': [], 'reason': 'no_parents'}；append 抛 ProvenanceError 或其他异常时经 _degrade(code='ledger_io') 返回；其余返回 {'ok': True, 'added': n, 'edges': edges, 'ledger': …}，恒不向外抛。
def record(root: str, child, parents, *, relation=DEFAULT_RELATION,
           batch=None, actor="system", note=None, path: str = None) -> dict:
    """写路径建链入口：**永不抛**（G8 硬约束：建链失败不得阻断节点写入）。

    返回 `{ok, added, edges, ...}`；失败时 `ok=False` + `degraded=True` 且已写
    `.fail` 留痕。调用方**不得**因本函数返回 False 而回滚节点。
    """
    try:
        edges = edges_for(child, parents, relation=relation, batch=batch,
                          actor=actor, note=note)
    except Exception as exc:                           # noqa: BLE001
        return _degrade(root, path, child, parents, relation,
                        f"{type(exc).__name__}: {exc}", "bad_edge")
    if not edges:
        return {"ok": True, "added": 0, "edges": [], "reason": "no_parents"}
    try:
        n = append(root, edges, path=path)
    except ProvenanceError as exc:
        return _degrade(root, path, child, parents, relation, str(exc),
                        "ledger_io")
    except Exception as exc:                           # noqa: BLE001
        return _degrade(root, path, child, parents, relation,
                        f"{type(exc).__name__}: {exc}", "ledger_io")
    return {"ok": True, "added": n, "edges": edges,
            "ledger": ledger_file(root, path)}


# --------------------------------------------------------------------------
# 读：台账 / 索引 / 悬空巡检
# --------------------------------------------------------------------------

# 生效条件：遍历 read_jsonl(ledger_file(root, path))，仅收录 isinstance(r, dict) 且 r.get("child") 与 r.get("parent") 均为真值（键缺失或值为假即丢弃）的记录。
def load(root: str, *, path: str = None) -> list:
    """读台账（跳过坏行；只取有端点的记录）。"""
    out = []
    for r in read_jsonl(ledger_file(root, path)):
        if isinstance(r, dict) and r.get("child") and r.get("parent"):
            out.append(r)
    return out


# 生效条件：rows 中每行按 (r.get("child"), r.get("parent"), r.get("rel")) 三元组判重，仅首次出现的行保留，按原顺序返回去重列表。
def _dedupe(rows):
    out, seen = [], set()
    for r in rows:
        key = (r.get("child"), r.get("parent"), r.get("rel"))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


# 生效条件：child/parent/relation/batch 各为真值时才做对应等值过滤（假值或 None 不过滤），去重后 limit 为真值时返回 out[:int(limit)]，limit 为 None 或 0 时返回全部 out。
def edges(root: str, *, child=None, parent=None, relation=None, batch=None,
          limit: int = None, path: str = None) -> list:
    """按端点 / 关系 / 批次过滤台账边（只读，去重，保持写入顺序）。"""
    out = []
    for r in load(root, path=path):
        if child and r.get("child") != child:
            continue
        if parent and r.get("parent") != parent:
            continue
        if relation and r.get("rel") != relation:
            continue
        if batch and r.get("batch") != batch:
            continue
        out.append(r)
    out = _dedupe(out)
    return out[:int(limit)] if limit else out


# 生效条件：以 (getattr(cg, "index", None) or {}).get("nodes") or {} 遍历（缺失时视作空）；prefix 为真值时仅保留 str(nid).startswith(prefix) 的节点，输出经 _dedupe 去重。
def index_edges(cg, *, prefix: str = None) -> list:
    """从**索引快照**恢复派生边（零读文件）——台账丢失/未重建时的只读兜底。"""
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    out = []
    for nid, e in nodes.items():
        if prefix and not str(nid).startswith(prefix):
            continue
        rel = coerce_relation((e or {}).get(FM_REL_FIELD))
        for p in as_list((e or {}).get(FM_FIELD)):
            out.append({"schema": SCHEMA, "child": nid, "parent": p, "rel": rel,
                        "batch": (e or {}).get("derived_batch"), "actor": None,
                        "origin": "index"})
    return _dedupe(out)


# 生效条件：给定 cg 即返回 _dedupe(load(cg.root, path=path) + index_edges(cg))，台账记录在前、按边去重。
def all_edges(cg, *, path: str = None) -> list:
    """台账 ∪ 索引声明（台账优先，按边去重）。"""
    return _dedupe(load(cg.root, path=path) + index_edges(cg))


# 生效条件：include_index 为真值时取 all_edges(cg, path=path)、为假时取 load(cg.root, path=path)，对 child/parent 不在 cg 索引节点键集合中的边记为 dangling 并列出 missing；返回 ok=not dangling，dangling 仅取 int(limit)（默认 20）项，不写盘。
def check(cg, *, path: str = None, limit: int = 20,
          include_index: bool = True) -> dict:
    """只读巡检：检出**悬空派生边**（端点不在索引内）。**不删边、不写盘**。

    `ok=False` 仅表示「有悬空」，不代表巡检失败；`checked=True` 恒成立。
    """
    known = set((getattr(cg, "index", None) or {}).get("nodes") or {})
    rows = all_edges(cg, path=path) if include_index else load(cg.root, path=path)
    dangling = []
    for e in rows:
        missing = []
        if e.get("child") not in known:
            missing.append("child")
        if e.get("parent") not in known:
            missing.append("parent")
        if missing:
            dangling.append({"child": e.get("child"), "parent": e.get("parent"),
                             "rel": e.get("rel"), "missing": missing,
                             "batch": e.get("batch"), "t": e.get("t"),
                             "origin": e.get("origin") or "ledger"})
    dangling.sort(key=lambda r: (r.get("child") or "", r.get("parent") or ""))
    ledger = ledger_file(cg.root, path)
    return {"ok": not dangling, "checked": True, "root": cg.root,
            "ledger": ledger, "ledger_exists": os.path.exists(ledger),
            "edges": len(rows), "nodes": len(known),
            "dangling": dangling[:int(limit)], "dangling_count": len(dangling),
            "readonly": True,
            "note": "只读巡检：悬空边仅检出并报告，不自动删除（关系事实由人处置）"}


# 生效条件：apply 为假值（默认 False）时只返回 dry_run 报表（written=0、sample=es[:5]）；apply 为真值时把 index_edges(cg) 的边写入 ledger_file(cg.root, path) 并返回 written=len(es)。
def rebuild_ledger(cg, *, apply: bool = False, path: str = None) -> dict:
    """按 frontmatter 重建台账——**只重放已声明的边，不发明任何边**。

    历史节点未声明派生关系 → 重建结果为空，正合「历史不回填」。
    默认 dry_run（只出报表）。
    """
    es = index_edges(cg)
    if not apply:
        return {"ok": True, "dry_run": True, "edges": len(es),
                "written": 0, "sample": es[:5],
                "note": "预演：未写盘；只重放 frontmatter 已声明的关系"}
    body = "".join(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n"
                   for e in es)
    p = ledger_file(cg.root, path)
    atomic_write(p, body)
    return {"ok": True, "dry_run": False, "edges": len(es),
            "written": len(es), "ledger": p}


# 生效条件：check(cg, path=path, limit=3) 成功时返回 edges/dangling/ledger/exists/sample（悬空边 child->parent）；该调用抛任何异常时被 except Exception 吞掉并返回 {}。
def summary(cg, *, path: str = None) -> dict:
    """轻量摘要（只读；失败不抛，避免拖垮 health_os / 常驻循环）。"""
    try:
        rep = check(cg, path=path, limit=3)
        return {"edges": rep["edges"], "dangling": rep["dangling_count"],
                "ledger": rep["ledger"], "exists": rep["ledger_exists"],
                "sample": [f"{r['child']}->{r['parent']}"
                           for r in rep["dangling"]]}
    except Exception:                                  # noqa: BLE001
        return {}


# 生效条件：root 为真值时 ledger 字段取 ledger_file(root)，否则取常量 LEDGER_NAME；其余自描述字段（SCHEMA、RELATIONS、DEFAULT_RELATION、FM_FIELD/FM_REL_FIELD 等）恒定返回。
def catalog(root: str = None) -> dict:
    """自描述（供 MCP catalog / 人工核对）。"""
    return {
        "layer": "派生溯源（G8）",
        "question": "这个节点从哪来（演进血缘）",
        "ledger": ledger_file(root) if root else LEDGER_NAME,
        "schema": SCHEMA,
        "relations": list(RELATIONS),
        "default_relation": DEFAULT_RELATION,
        "fm_fields": [FM_FIELD, FM_REL_FIELD],
        "discipline": {"incremental_only": True, "no_backfill": True,
                       "never_block_write": True, "patrol_readonly": True},
        "distinct_from": ("links.py = 跨节点信任 P_trust（_links.json）；"
                          "本层 = 节点派生关系（_link.jsonl）"),
    }


# --------------------------------------------------------------------------
# 读：三元组反查原语（阶段二 4.2 · find_entity_contexts 式）
# --------------------------------------------------------------------------
# 术语映射（**同一件事，勿新造第二套字段**）：三元组 `subject / predicate /
# object` 在本层就是派生边的 `child / rel / parent`——即节点写入时声明的
# `derived_from` 关系。不另建 subject/predicate/object 参数字面量，理由有二：
#   ① `cg` 工具面是**扁平 schema**，`subject` 已被 `identity`（`subject:<id>`
#      主体语义）与 `link.evidence`（证据主体）占用，同名异义会把两处口径搅在一起；
#   ② `edges()` 已是唯一谓词载体（child/parent/relation/batch 四键），反查只是它的
#      **只读超集**——另造一套参数必然分叉。
# 与 `edges()` 的三处**有意**差异（不是漂移）：
#   · 时间轴缺省 `observed`（边只有记录时刻 `t`，见 FIND_DEFAULT_AXIS）；
#   · 默认排序 `desc`（按 `t` 新→旧）且 `limit` 缺省 50、上限 500（分页原语，
#     不给「静默全量倾倒」）；
#   · 加 `aggregation`（分页前全集分桶）与 `expand_nodes`（端点摘要，索引级零读盘）。

#: 排序方向（封闭枚举，拒收未知名——与 `trust.TIME_OPERATORS` 同风格）
ORDERINGS = ("desc", "asc")
#: 聚合维度（封闭枚举）：按谓词 / 对象端 / 主体端分桶
AGGREGATIONS = ("by_relation", "by_parent", "by_child")
#: 聚合维度 → 边字段（谓词在边上叫 `rel`；聚合名沿用三元组术语命名）
_AGG_FIELD = {"by_relation": "rel", "by_parent": "parent", "by_child": "child"}
#: 反查缺省时间轴：派生边只有一个时刻字段 `t`（写入时刻，观察轴），
#: **效力轴字段根本不存在**。与 `mdcg.search` 缺省 `effective` **有意不同**：
#: 那里 `effective_from/until` 是可选声明（多数节点没写），沿用 fail-open 不会
#: 出错；这里若缺省 `effective`，则「给了时间条件却恒不过滤」——把静默 no-op
#: 当成了「没有匹配」，属无法复算的错答。
FIND_DEFAULT_AXIS = "observed"
DEFAULT_FIND_LIMIT = 50
MAX_FIND_LIMIT = 500
#: `expand_nodes=True` 时透出的索引字段白名单（只读索引快照，**零读节点文件**）
EXPAND_FIELDS = ("layer", "tags", "importance", "writer", "session",
                 "derived_from", "derived_relation", "derived_batch",
                 "temporal", "time_window", "condition_space")


# 生效条件：value 为 None 或 str(value).strip() 为空时返回 "desc"；小写后命中 ORDERINGS 返回该值；否则抛 ProvenanceError。
def _ordering_of(value) -> str:
    """排序方向归一 → `"desc"` / `"asc"`；未知 → `ProvenanceError`（fail-closed）。"""
    if value is None or not str(value).strip():
        return "desc"
    v = str(value).strip().lower()
    if v not in ORDERINGS:
        raise ProvenanceError(f"未知 ordering {value!r}（允许：{ORDERINGS}）")
    return v


# 生效条件：value 为 None 或 str(value).strip() 为空时返回 None（= 不聚合）；小写后命中 AGGREGATIONS 返回该值；否则抛 ProvenanceError。
def _aggregation_of(value):
    """聚合维度归一 → `None` / `AGGREGATIONS` 之一；未知 → `ProvenanceError`。"""
    if value is None or not str(value).strip():
        return None
    v = str(value).strip().lower()
    if v not in AGGREGATIONS:
        raise ProvenanceError(f"未知 aggregation {value!r}（允许：{AGGREGATIONS}）")
    return v


# 生效条件：axis 为 "observed" 且 edge.get("t") 可经 trust.parse_time 解析时返回 (t, t, False)；axis 非 observed 或 t 不可解析/缺失时返回 (None, None, True)。
def _edge_window(edge, axis: str):
    """边的轴窗口 → `(start, end, missing)`（与 `trust.time_window_of` **同形**）。

    observed 轴：`t`（写入时刻）→ `(t, t, False)`；`t` 缺失（`index_edges` 兜底边
    不带时间）→ `(None, None, True)`。其余轴一律 `(None, None, True)`——边没有效力轴
    声明可读，如实报「不可判定」，由**轴策略**处置（observed fail-closed 剔除并计入
    `axis_missing`；effective fail-open 保留），不在这里悄悄换轴。
    """
    if str(axis) == "observed":
        t = _trust.parse_time((edge or {}).get("t"))
        if t is None:
            return None, None, True
        return t, t, False
    return None, None, True


# 生效条件：start_operator 与 end_operator 均为 None 时返回 "overlap"，否则返回 "endpoint"。
def _mode_of(start_operator, end_operator) -> str:
    """时间过滤模式（与 `trust.window_match` 的显式分叉口径同源，不另立判据）。"""
    return "endpoint" if (start_operator is not None or end_operator is not None) \
        else "overlap"


# 生效条件：nid 不在 (cg.index or {}).get("nodes") or {} 的 dict 条目中（含 cg.index 缺失、条目非 dict）时返回 {'id': nid, 'present': False}；否则返回 {'id','present':True} 并附 EXPAND_FIELDS 中值非 None 的字段。
def _node_digest(cg, nid) -> dict:
    """端点摘要（只读索引快照，**零读节点文件**）；端点缺失 → `present=False`。"""
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    e = nodes.get(nid)
    if not isinstance(e, dict):
        return {"id": nid, "present": False}
    d = {"id": nid, "present": True}
    for k in EXPAND_FIELDS:
        if e.get(k) is not None:
            d[k] = e[k]
    return d


# 生效条件：child/parent/relation/batch 各为真值（str(x).strip() 非空）时归一为过滤条件，relation 经 normalize_relation 非法即抛 ProvenanceError；ordering/aggregation 经 _ordering_of/_aggregation_of 非法即抛；offset 为负或 limit<=0 或 limit>MAX_FIND_LIMIT 即抛；时间五参经 trust.check_time_args 校验，why 非空即抛 ProvenanceError；返回 {'ok': True, 'readonly': True, 'op': 'edges', 'triple', 'total', 'matched', 'returned', 'offset', 'limit', 'ordering', 'aggregation', 'edges', 'aggregates', 'nodes_expanded', 'time_filter', 'ledger', 'distinct_from', 'note'}，其中 total=谓词过滤后条数、matched=时间过滤后条数（dropped+matched==total）、edges=按 t 排序后 offset:offset+limit 切片（expand_nodes 时每边附 child_node/parent_node 摘要）、aggregates 为分页前全集分桶（未请求为 None）。
def find_edges(cg, *, child=None, parent=None, relation=None, batch=None,
               start_time=None, end_time=None, start_operator=None,
               end_operator=None, time_axis=None, ordering=None, offset=0,
               limit=None, aggregation=None, expand_nodes: bool = False,
               path: str = None) -> dict:
    """三元组反查（阶段二 4.2）：按**任意端 / 谓词 / 时间**反查派生边（只读）。

    `subject/predicate/object` ≡ `child/rel/parent`（见本节术语映射注释）。

    谓词（`child` / `parent` / `relation` / `batch`）与 `edges()` **同源同义**：
    给了就等值过滤、不给就不过滤。时间条件走 `trust.check_time_args`
    （**与检索共用的唯一校验点**，本层不另写一套），比较语义由
    `trust.window_match` 提供（不给 operator = 区间重叠；给 operator = 端点比较）。

    fail-closed 清单（宁可报错，不静默降级）：
      · `relation` 非 `RELATIONS`（经 `normalize_relation`）；
      · `ordering` / `aggregation` 非各自枚举；
      · `offset < 0`；`limit <= 0` 或 `> MAX_FIND_LIMIT`（**不把 0/负数当「全部」**）；
      · 时间五参非法（未知轴 / 未知算子 / 给了算子缺时间 / start > end）。

    分页与聚合的次序是刻意的：**聚合基于分页前全集**（`matched`），
    否则「先切页再聚合」会给出随 offset 漂移的分桶——不可复算。
    审计块 `time_filter.dropped + matched == total` 由本函数保证。
    """
    # ---- 谓词归一（空/空白 = 不约束，与 edges() 同口径） ------------------
    c_f = str(child).strip() if child is not None and str(child).strip() else None
    p_f = str(parent).strip() if parent is not None and str(parent).strip() else None
    b_f = str(batch).strip() if batch is not None and str(batch).strip() else None
    r_f = normalize_relation(relation) if (relation is not None
                                           and str(relation).strip()) else None
    # ---- 排序 / 分页 / 聚合 入参校验 --------------------------------------
    ord_v = _ordering_of(ordering)
    agg_v = _aggregation_of(aggregation)
    try:
        off = int(offset or 0)
    except (TypeError, ValueError) as exc:
        raise ProvenanceError(f"offset 非法：{offset!r}") from exc
    if off < 0:
        raise ProvenanceError(f"offset 不能为负：{off}")
    lim = DEFAULT_FIND_LIMIT if limit is None else int(limit)
    if lim <= 0:
        raise ProvenanceError(f"limit 必须为正整数（0/负数不当「全部」）：{limit!r}")
    if lim > MAX_FIND_LIMIT:
        raise ProvenanceError(f"limit 超上限 {MAX_FIND_LIMIT}：{lim}")
    # ---- 时间算子：复用唯一校验点，缺省轴按本层语义补 observed -----------
    enabled, axis0, why = _trust.check_time_args(
        start_time=start_time, end_time=end_time,
        start_operator=start_operator, end_operator=end_operator,
        time_axis=time_axis)
    if why:
        raise ProvenanceError(why)
    axis = FIND_DEFAULT_AXIS if time_axis is None else axis0
    q_s = _trust.parse_time(start_time) if enabled else None
    q_e = _trust.parse_time(end_time) if enabled else None

    rows = all_edges(cg, path=path)
    cand = []
    for e in rows:
        if c_f and e.get("child") != c_f:
            continue
        if p_f and e.get("parent") != p_f:
            continue
        if r_f and e.get("rel") != r_f:
            continue
        if b_f and e.get("batch") != b_f:
            continue
        cand.append(e)
    total = len(cand)

    # ---- 时间过滤（候选层：与 trust.filter_by_time 同策略） ---------------
    dropped = missing = 0
    kept = []
    for e in cand:
        if not enabled:
            kept.append(e)
            continue
        cs, ce, miss = _edge_window(e, axis)
        if miss:
            if axis == "observed":                 # 观察轴 fail-closed
                dropped += 1
                missing += 1
                continue
            kept.append(e)                         # 效力轴 fail-open（无效力声明可读）
            continue
        if _trust.window_match(cs, ce, q_s, q_e, start_operator, end_operator):
            kept.append(e)
        else:
            dropped += 1
    if dropped + len(kept) != total:               # 审计不变式（可复算）
        raise ProvenanceError(
            f"审计不变式破缺：dropped({dropped}) + kept({len(kept)}) != total({total})")

    # ---- 排序（t 缺失按 0 计，确定性次级键防抖） --------------------------
    kept.sort(key=lambda e: (float(e.get("t") or 0.0),
                             str(e.get("child") or ""),
                             str(e.get("parent") or "")),
              reverse=(ord_v == "desc"))
    page = kept[off:off + lim]
    if expand_nodes:
        page = [dict(e) for e in page]
        for e in page:
            e["child_node"] = _node_digest(cg, e.get("child"))
            e["parent_node"] = _node_digest(cg, e.get("parent"))

    # ---- 聚合（分页前全集；无分页漂移） ----------------------------------
    aggregates = None
    if agg_v:
        field = _AGG_FIELD[agg_v]
        buckets = {}
        for e in kept:
            k = str(e.get(field) or "")
            b = buckets.get(k)
            if b is None:
                b = buckets[k] = {"key": k, "count": 0, "t_min": None,
                                  "t_max": None, "sample": []}
            b["count"] += 1
            t = e.get("t")
            if t is not None:
                t = float(t)
                b["t_min"] = t if b["t_min"] is None else min(b["t_min"], t)
                b["t_max"] = t if b["t_max"] is None else max(b["t_max"], t)
            if len(b["sample"]) < 3:
                b["sample"].append(f"{e.get('child')}->{e.get('parent')}"
                                   f"({e.get('rel')})")
        aggregates = sorted(buckets.values(), key=lambda b: (-b["count"], b["key"]))

    return {"ok": True, "readonly": True, "op": "edges",
            "triple": {"child": c_f, "relation": r_f, "parent": p_f, "batch": b_f},
            "total": total, "matched": len(kept), "returned": len(page),
            "offset": off, "limit": lim, "ordering": ord_v,
            "aggregation": agg_v, "aggregates": aggregates,
            "nodes_expanded": bool(expand_nodes),
            "edges": page,
            "time_filter": _trust.time_filter_meta(
                axis=axis, mode=_mode_of(start_operator, end_operator),
                start=start_time, end=end_time,
                start_operator=start_operator, end_operator=end_operator,
                dropped=dropped, axis_missing=missing, applied=bool(enabled)),
            "ledger": ledger_file(cg.root, path),
            "distinct_from": "links.py = 跨节点信任 P_trust（_links.json）",
            "note": ("只读：台账 ∪ 索引声明（台账优先，按边去重）；"
                     "聚合基于分页前全集；边时刻字段为 t（观察轴），"
                     "无效力轴字段——真实时间条件请用缺省 time_axis=observed")}