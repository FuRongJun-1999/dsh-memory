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


# 生效条件：给定 cg 与 kind 即返回 os.path.join(cg.root, f"export_{kind}_{当前 %Y%m%d_%H%M%S 时间戳}.jsonl")，无任何前置校验或分支。
def _default_out(cg, kind: str) -> str:
    """默认导出路径：`<root>/export_<kind>_<ts>.jsonl`（可搬运、可灾备）。"""
    ts = time.strftime("%Y%m%d_%H%M%S")
    return os.path.join(cg.root, f"export_{kind}_{ts}.jsonl")


# 生效条件：cg.get(nid) 为 None 时返回 None；否则以 fm = node.get("frontmatter") or {}（缺键或假值回落空 dict）与 entry 组装行，layer 取 fm 的 layer、为假值时回落 entry.get("layer")，include_content 为真值时追加 content = node.get("content") or ""，最终只保留 _ROW_KEYS 中实际存在的键。
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


# 生效条件：源为 cg.index 的 nodes（缺 "nodes" 键或假值回落空 dict）——ids 为真值时只取其中确实在 nodes 里的 id，否则取全部——按 (float(created_at or 0), id) 排序后逐个产出同时满足 layer（为真时须 (e.layer or "") == layer）、tag（为真时须在 e.tags or [] 中）、since/until（非 None 时按 float 比较 created_at）的条目，limit 为真值且已产出 n 条并 n >= int(limit) 时停止（limit 为 0 或 None 不设上限）。
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


# 生效条件：将 entries 逐条经 _row 转换后写入 out_path（先 makedirs 其父目录、写 out_path + ".tmp"、结束后 os.replace 为 out_path），_row 返回 None 的条目只累加 skipped_unreadable 而不写入，其余写入并累加 written 及 by_layer（row 的 layer 缺键或假值记为 "?"）；include_content 透传给 _row 决定行是否含正文；返回含 ok/out/written/skipped_unreadable/by_layer/bytes/elapsed_ms 的统计 dict。
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


# 生效条件：out 为假值（None/空串）时回落为 _default_out(cg, "graph")，以 _iter_entries(cg, layer=layer, limit=limit) 为条目流调用 _write_jsonl(include_content=include_content)，再补 action="graph" 与 note 后返回该结果 dict。
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


# 生效条件：ids 先按 [str(i) for i in (ids or []) if str(i).strip()] 规整，规整结果为空（ids 为 None/空容器/全空白项）时返回 {'ok': False, 'error': 'ids 不能为空'}；否则 out 为假值时回落为 _default_out(cg, "nodes")，以 _iter_entries(cg, ids=ids) 为条目流调用 _write_jsonl(include_content=include_content)，再补 action="nodes"、requested=len(ids)、missing=索引 keys 与 ids 的差集排序后返回。
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


# 生效条件：out 为假值（None/空串）时回落为 _default_out(cg, "slice")，以 _iter_entries(cg, layer=layer, since=since, until=until, tag=tag, limit=limit) 为条目流调用 _write_jsonl(include_content=include_content)，再补 action="slice" 与记录 layer/since/until/tag 的 filter 后返回。
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


# 生效条件：只读 cg.index 的 nodes（缺 "nodes" 键或假值回落空 dict），逐条统计 layer（缺键或假值记 "?"）、verification_basis（缺键或假值记 "(未声明)"）、tags 计数（按计数降序取前 15）、protected 与 has_neg_conditions 为真值的条目数，以及 created_at 为真值时的 min/max（全为 0 或缺键时二者均为 None），返回含 total/by_layer/by_verification_basis/protected/with_non_applicable/top_tags/time_range/note 的 dict。
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
    top_tags = sorted(by_tag.items(),
                      key=lambda kv: (-kv[1], str(kv[0])))[:15]
    return {"ok": True, "action": "stat", "total": len(nodes),
            "by_layer": by_layer, "by_verification_basis": by_basis,
            "protected": protected, "with_non_applicable": with_neg,
            "top_tags": [{"tag": t, "n": n} for t, n in top_tags],
            "time_range": {"min": t_min, "max": t_max},
            "note": ("只读索引统计（零 IO）。sensitivity 不入索引快照，"
                     "如需密级分布请用 graph 导出后统计。")}


# 生效条件：act = (action or "graph").strip().lower()（action 为 None/空串等假值时取 "graph"）——act 为 "graph"/"nodes"/"slice"/"stat" 时分别转调 export_graph/export_nodes/export_slice/export_stat（out、layer、limit、since、until、tag、ids 取自 kw 对应键，include_content 取 kw.get("include_content", True)），其它 act 值抛 ValueError。
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
