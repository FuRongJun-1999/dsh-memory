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

def ledger_file(root: str, path: str = None) -> str:
    """台账路径：显式 → MDCG_LINK_FILE → <root>/_link.jsonl。"""
    return path or os.environ.get(LEDGER_ENV) or os.path.join(root, LEDGER_NAME)


def fail_log_file(root: str, path: str = None) -> str:
    """降级留痕路径（台账写不进时的「本该建的边」）。"""
    return ledger_file(root, path) + FAIL_SUFFIX


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


def normalize_relation(rel, default: str = DEFAULT_RELATION) -> str:
    """严格校验关系名；非法抛 `ProvenanceError`（显式 API 用）。"""
    r = str(rel or "").strip().lower()
    if not r:
        r = default
    if r not in RELATIONS:
        raise ProvenanceError(f"未知派生关系：{rel}（允许：{RELATIONS}）")
    return r


def coerce_relation(rel, default: str = DEFAULT_RELATION) -> str:
    """宽松兜底：非法关系名回退默认值（**写路径用，保证永不阻断写入**）。"""
    try:
        return normalize_relation(rel, default)
    except ProvenanceError:
        return default


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

def load(root: str, *, path: str = None) -> list:
    """读台账（跳过坏行；只取有端点的记录）。"""
    out = []
    for r in read_jsonl(ledger_file(root, path)):
        if isinstance(r, dict) and r.get("child") and r.get("parent"):
            out.append(r)
    return out


def _dedupe(rows):
    out, seen = [], set()
    for r in rows:
        key = (r.get("child"), r.get("parent"), r.get("rel"))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


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


def all_edges(cg, *, path: str = None) -> list:
    """台账 ∪ 索引声明（台账优先，按边去重）。"""
    return _dedupe(load(cg.root, path=path) + index_edges(cg))


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
