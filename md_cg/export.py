# -*- coding: utf-8 -*-
"""md_cg · 全库导出（P0 · export op）

把整库认知图导出为「可搬运、可灾备」的结构化数据。

设计约束（D-005 零第三方依赖，只用标准库）：
- **流式**写 JSONL：逐节点处理，不把整库读进内存（真实库 4500+ 节点）。
- 先写 `<out>.tmp` 再 `os.replace` 改名：流式的同时保证「要么完整、要么无」。
- 只导出 md 单一真相源的**内容**；索引等派生物不入导出（删了可重建）。
- 可见性由 `cg.get` 决定：无密钥 / 越权 → 跳过并计数，绝不静默丢弃。
- 密级默认导出明文（调用方须先通过 `require_admin` 授权）；可选 redact 脱敏。

对外只有 `run(cg, action, **kw)` 一个入口，action ∈ EXPORT_ACTIONS。
"""
from __future__ import annotations

import json
import os
import time

SCHEMA = 1
EXPORT_ACTIONS = ("graph", "nodes", "slice", "stat")

# 导出行的字段（顺序即 JSON 键顺序，便于 diff 与人工核对）
_ROW_KEYS = ("id", "layer", "path", "tags", "importance", "confidence",
             "condition_space", "non_applicable_conditions", "verification_basis",
             "created_at", "edges", "protected", "sensitivity", "content")


def _default_out(cg, kind: str) -> str:
    """默认导出路径：`<root>/export_<kind>_<ts>.jsonl`（可搬运、可灾备）。"""
    ts = time.strftime("%Y%m%d_%H%M%S")
    return os.path.join(cg.root, f"export_{kind}_{ts}.jsonl")


def _row(cg, nid: str, entry: dict, include_content: bool = True):
    """索引条目 → 导出行（回读节点拿到 frontmatter + 正文）。

    返回 None 表示不可读（无密钥 / 越权）——由调用方计数，不静默。
    """
    node = cg.get(nid)
    if node is None:
        return None
    fm = node.get("frontmatter") or {}
    row = {
        "id": nid,
        "layer": fm.get("layer") or entry.get("layer"),
        "path": entry.get("path"),
        "tags": list(fm.get("tags") or []),
        "importance": fm.get("importance"),
        "confidence": fm.get("confidence"),
        "condition_space": fm.get("condition_space"),
        "non_applicable_conditions": list(fm.get("non_applicable_conditions") or []),
        "verification_basis": fm.get("verification_basis"),
        "created_at": fm.get("created_at"),
        "edges": list(fm.get("edges") or []),
        "protected": bool(entry.get("protected")),
        "sensitivity": fm.get("sensitivity"),
    }
    if include_content:
        row["content"] = node.get("content") or ""
    return {k: row[k] for k in _ROW_KEYS if k in row}


def _iter_entries(cg, layer=None, since=None, until=None, tag=None,
                  ids=None, limit=None):
    """按条件遍历索引条目（不读文件，保证筛选阶段零 IO）。

    排序键 = (created_at, id)：稳定、可重现，便于灾备 diff。
    """
    nodes = (cg.index.get("nodes") or {})
    if ids:
        picked = [(nid, nodes[nid]) for nid in ids if nid in nodes]
    else:
        picked = list(nodes.items())
    picked.sort(key=lambda kv: (float(kv[1].get("created_at") or 0), kv[0]))
    n = 0
    for nid, e in picked:
        if layer and (e.get("layer") or "") != layer:
            continue
        if tag and tag not in (e.get("tags") or []):
            continue
        ca = float(e.get("created_at") or 0)
        if since is not None and ca < float(since):
            continue
        if until is not None and ca > float(until):
            continue
        yield nid, e
        n += 1
        if limit and n >= int(limit):
            return


def _write_jsonl(cg, out_path: str, entries, include_content: bool = True):
    """流式写 JSONL（tmp + 原子改名）。返回统计 dict。"""
    out_path = os.path.abspath(out_path)
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = out_path + ".tmp"
    written = skipped = 0
    by_layer = {}
    t0 = time.time()
    with open(tmp, "w", encoding="utf-8") as f:
        for nid, e in entries:
            row = _row(cg, nid, e, include_content=include_content)
            if row is None:
                skipped += 1           # 不可读：计数上报，不静默丢
                continue
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            written += 1
            lay = row.get("layer") or "?"
            by_layer[lay] = by_layer.get(lay, 0) + 1
            if written % 500 == 0:
                f.flush()              # 定期刷盘，控制缓冲区
    os.replace(tmp, out_path)          # 流式 + 原子：要么完整、要么无
    return {"ok": True, "out": out_path, "written": written,
            "skipped_unreadable": skipped, "by_layer": by_layer,
            "bytes": os.path.getsize(out_path),
            "elapsed_ms": round((time.time() - t0) * 1000, 1)}


def export_graph(cg, out: str = None, layer=None, limit=None,
                 include_content: bool = True):
    """全库导出（默认含正文）。"""
    out = out or _default_out(cg, "graph")
    entries = _iter_entries(cg, layer=layer, limit=limit)
    res = _write_jsonl(cg, out, entries, include_content=include_content)
    res["action"] = "graph"
    res["note"] = ("流式导出行=JSONL，一节点一行；不含索引等派生物"
                   "（删了可重建）。skipped_unreadable>0 表示有节点因密钥/越权"
                   "不可读，需用更高权限或原密钥重导。")
    return res


def export_nodes(cg, ids, out: str = None, include_content: bool = True):
    """按 id 列表导出（顺序 = 传入顺序）。"""
    ids = [str(i) for i in (ids or []) if str(i).strip()]
    if not ids:
        return {"ok": False, "error": "ids 不能为空"}
    out = out or _default_out(cg, "nodes")
    entries = _iter_entries(cg, ids=ids)
    res = _write_jsonl(cg, out, entries, include_content=include_content)
    res["action"] = "nodes"
    res["requested"] = len(ids)
    res["missing"] = sorted(set(ids) - set((cg.index.get("nodes") or {}).keys()))
    return res


def export_slice(cg, out: str = None, layer=None, since=None, until=None,
                 tag=None, limit=None, include_content: bool = True):
    """按层 / 时间窗 / 标签切片导出（有界，便于增量搬运）。"""
    out = out or _default_out(cg, "slice")
    entries = _iter_entries(cg, layer=layer, since=since, until=until,
                            tag=tag, limit=limit)
    res = _write_jsonl(cg, out, entries, include_content=include_content)
    res["action"] = "slice"
    res["filter"] = {"layer": layer, "since": since, "until": until, "tag": tag}
    return res


def export_stat(cg):
    """导出前体检：层分布 / 验证基底 / 标签 Top / 时间范围。**只读索引，零 IO**。"""
    nodes = (cg.index.get("nodes") or {})
    by_layer, by_basis, by_tag = {}, {}, {}
    protected = with_neg = 0
    t_min, t_max = None, None
    for _nid, e in nodes.items():
        lay = e.get("layer") or "?"
        by_layer[lay] = by_layer.get(lay, 0) + 1
        b = e.get("verification_basis") or "(未声明)"
        by_basis[b] = by_basis.get(b, 0) + 1
        if e.get("protected"):
            protected += 1
        if e.get("has_neg_conditions"):
            with_neg += 1
        for t in (e.get("tags") or []):
            by_tag[t] = by_tag.get(t, 0) + 1
        ca = float(e.get("created_at") or 0)
        if ca:
            t_min = ca if t_min is None else min(t_min, ca)
            t_max = ca if t_max is None else max(t_max, ca)
    top_tags = sorted(by_tag.items(), key=lambda kv: -kv[1])[:15]
    return {"ok": True, "action": "stat", "total": len(nodes),
            "by_layer": by_layer, "by_verification_basis": by_basis,
            "protected": protected, "with_non_applicable": with_neg,
            "top_tags": [{"tag": t, "n": n} for t, n in top_tags],
            "time_range": {"min": t_min, "max": t_max},
            "note": ("只读索引统计（零 IO）。sensitivity 不入索引快照，"
                     "如需密级分布请用 graph 导出后统计。")}


def run(cg, action: str = "graph", **kw):
    """export op 唯一入口。"""
    act = (action or "graph").strip().lower()
    if act == "graph":
        return export_graph(cg, out=kw.get("out"), layer=kw.get("layer"),
                            limit=kw.get("limit"),
                            include_content=kw.get("include_content", True))
    if act == "nodes":
        return export_nodes(cg, kw.get("ids"), out=kw.get("out"),
                            include_content=kw.get("include_content", True))
    if act == "slice":
        return export_slice(cg, out=kw.get("out"), layer=kw.get("layer"),
                            since=kw.get("since"), until=kw.get("until"),
                            tag=kw.get("tag"), limit=kw.get("limit"),
                            include_content=kw.get("include_content", True))
    if act == "stat":
        return export_stat(cg)
    raise ValueError(f"未知 export action：{action!r}（允许 {EXPORT_ACTIONS}）")
