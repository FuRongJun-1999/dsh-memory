# -*- coding: utf-8 -*-
"""sqlite 认知图 → md 目录 迁移（P1，附等价校验）

用法：
    python -m md_cg.migrate <sqlite.db> <md_root> [--limit N]

校验：节点数等价 + 全量 content/tags/importance 字段等价（不是抽样——迁移是
一次性的，抽样漏掉的错误后面没有第二次机会发现）。
"""
import os
import sys
import json
import sqlite3
import collections

from .mdcg import MdCG
from . import routing, subgraph


# 生效条件：v 为假值（None、空串等）时直接返回 default，否则 v 被 json.loads 成功解析时返回解析结果，抛出 ValueError 或 TypeError 时仍返回 default。
def _j(v, default):
    if not v:
        return default
    try:
        return json.loads(v)
    except (ValueError, TypeError):
        return default


# 生效条件：db 为 sqlite3.connect 可打开的库且 limit 为假值（None、0、空串）时返回 nodes 全表行的 dict 列表；limit 为真值时先 int(limit) 并追加 " limit N" 子句后返回其结果。
def load_nodes(db, limit=None):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    sql = "select * from nodes"
    if limit:
        sql += f" limit {int(limit)}"
    return [dict(r) for r in c.execute(sql)]


# 生效条件：db 可连接且能查询其 edges 表时，返回以 source_id 分组的 defaultdict(list)，每个 source_id 对应 target_id、relation_type、confidence、verified 经 subgraph.normalize_edge 规范化后的边列表。
def load_edges(db):
    """读源库边，规范化为 md_cg 本地边（键名 `relation_type`、方向按 SRC_REL_MAP）。

    早期此处写 `"type"` 键，而 `subgraph` 索引只认 `relation_type`/`relation`，
    导致迁入的边静默不可遍历 —— 见 `subgraph.normalize_edge`。
    """
    c = sqlite3.connect(db)
    out = collections.defaultdict(list)
    for src, tgt, rel, conf, ver in c.execute(
            "select source_id, target_id, relation_type, confidence, verified from edges"):
        out[src].append(subgraph.normalize_edge(tgt, rel, conf, ver))
    return out


# 生效条件：db、root 给定后按 load_nodes(db, limit) 的 rows 逐行 add 到 MdCG(root) 并 flush，再对每行按 cg.get 取不到→"missing"、content 去尾换行不等→"content"、tags 不等→"tags"、importance 差>1e-9→"importance"、edges 长度不等→"edges" 的 elif 顺序累计 report.field_mismatches，verbose 为真值时额外打印 report JSON，最终返回 (cg, report)。
def migrate(db, root, limit=None, verbose=True):
    rows = load_nodes(db, limit)
    edges = load_edges(db)
    cg = MdCG(root, autoflush=500)
    for r in rows:
        cg.add(
            r["id"], r["content"] or "",
            layer=r.get("layer") or "knowledge",
            tags=_j(r.get("tags"), []),
            condition_space=_j(r.get("condition_space"), {}),
            importance=r.get("importance") if r.get("importance") is not None else 0.5,
            confidence=r.get("confidence") if r.get("confidence") is not None else 0.6,
            edges=edges.get(r["id"], []),
            created_at=r.get("created_at") or 0,
            modality=r.get("modality") or "text",
            temporal=r.get("temporal_coordinate"),
            spatial=_j(r.get("spatial_coordinates"), None),
            semantic_coordinates=_j(r.get("semantic_coordinates"), {}),
            state_attributes=_j(r.get("state_attributes"), {}),
            entity_id=r.get("entity_id"),
        )
    cg.flush()

    # ---- 等价校验（全量，非抽样）----
    bad = []
    for r in rows:
        got = cg.get(r["id"])
        if not got:
            bad.append((r["id"], "missing"))
            continue
        fm = got["frontmatter"]
        if got["content"].rstrip("\n") != (r["content"] or "").rstrip("\n"):
            bad.append((r["id"], "content"))
        elif fm.get("tags") != _j(r.get("tags"), []):
            bad.append((r["id"], "tags"))
        elif abs(float(fm.get("importance") or 0) - float(r.get("importance") or 0)) > 1e-9:
            bad.append((r["id"], "importance"))
        elif len(fm.get("edges") or []) != len(edges.get(r["id"], [])):
            bad.append((r["id"], "edges"))

    report = {
        "sqlite_nodes": len(rows),
        "md_nodes": len(cg.index["nodes"]),
        "count_equal": len(rows) == len(cg.index["nodes"]),
        "field_mismatches": len(bad),
        "samples": bad[:5],
        "edges_total": sum(len(v) for v in edges.values()),
        "health": cg.health(),
    }
    if verbose:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return cg, report


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    lim = None
    if "--limit" in sys.argv:
        lim = int(sys.argv[sys.argv.index("--limit") + 1])
    migrate(sys.argv[1], sys.argv[2], lim)
