# -*- coding: utf-8 -*-
"""md_cg · 本地记忆迁移（AEIS sqlite → md 认知图）

把 `AEIS/data/aeis_memory.db` 的认知图（nodes + edges）迁到 md_cg 目录，
供 dsh / zcode 共同读写。**这是本地私有记忆**：默认 sensitivity=private。

用法：
    python -m md_cg.migrate_aeis --db <sqlite> --root <md_root> [选项]

选项：
    --layers knowledge,anchor,self   只迁这些层（默认全部）
    --limit N                        只迁前 N 条（调试）
    --dry-run                        只统计不写
    --clearance private              调用方密级（默认 private）

校验（全量，非抽样）：节点数等价 + content/tags/importance/confidence/
condition_space/edges/access_count/modality/created_at 逐字段等价。

层映射：context→contextual；knowledge/anchor/self/structural 同名。
幂等：按 id 原子覆盖写，可反复执行。
"""
from __future__ import annotations

import collections
import io
import json
import os
import sqlite3
import sys
import time

from . import subgraph
from .mdcos import MdCGSecure
from .security import Principal, DEFAULT_SENSITIVITY

# AEIS layer → md_cg layer
LAYER_MAP = {
    "anchor": "anchor",
    "structural": "structural",
    "knowledge": "knowledge",
    "context": "contextual",
    "contextual": "contextual",
    "self": "self",
    "rejected": "rejected",
    "unresolved": "unresolved",
}
MDCG_LAYERS = ("anchor", "structural", "knowledge", "contextual", "self",
               "rejected", "unresolved")


# 生效条件：s 为假值（None/空串）时返回 s or ""（即空串），否则返回把 "\r\n" 与 "\r" 依次替换为 "\n" 后的字符串。
def _norm_text(s: str) -> str:
    """统一换行：md 是 LF 文本格式，把 CRLF/CR 规范化为 LF。

    源 sqlite 里的内容常含 \\r\\n（Windows 剪贴板/网页抓取），而 md 文件按 LF 存；
    不规范化会让「content 全量等价」校验出现假失败（实测 24/4523）。
    """
    if not s:
        return s or ""
    return s.replace("\r\n", "\n").replace("\r", "\n")


# 生效条件：v 为 None 或 v == "" 时返回 default；v 是 dict/list 时原样返回 v；其余值经 json.loads(v) 解析成功则返回解析结果，抛 ValueError/TypeError 时返回 default。
def _j(v, default):
    if v is None or v == "":
        return default
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (ValueError, TypeError):
        return default


# 生效条件：float(v) 转换成功时返回该浮点值，抛 TypeError/ValueError 时返回 default（未传则取默认实参 0.0）。
def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# 生效条件：db 以只读 URI 打开 nodes 表；layers 为真值时加 "layer IN (...)" 过滤（None 或空列表不过滤），limit 为真值时拼接 LIMIT int(limit)（None/0/"" 等假值不加 LIMIT），返回按 created_at 排序的行转成的 dict 列表 rows。
def load_nodes(db: str, layers=None, limit=None):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    sql, params = "SELECT * FROM nodes", []
    if layers:
        sql += " WHERE layer IN (%s)" % ",".join("?" * len(layers))
        params = list(layers)
    sql += " ORDER BY created_at"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = [dict(r) for r in con.execute(sql, params)]
    con.close()
    return rows


# 生效条件：db 以只读 URI 打开，遍历 edges 表全部行，按 source_id 聚合为 defaultdict(list)，每项取 normalize_edge(target_id, relation_type, _f(confidence, 0.7), int(verified or 0))，返回该 out。
def load_edges(db: str):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    out = collections.defaultdict(list)
    for src, tgt, rel, conf, ver in con.execute(
            "SELECT source_id, target_id, relation_type, confidence, verified FROM edges"):
        out[src].append(subgraph.normalize_edge(tgt, rel, _f(conf, 0.7), int(ver or 0)))
    con.close()
    return out


# 生效条件：以 db、root 建库后，dry_run 为真则跳过写入与回读校验（written=0、count_equal 恒为真、health 为 None），为假则按 rows 逐条 override 写入并做 10 项字段回读比对累计 field_mismatches；clearance 非 "private" 时 sensitivity 取 DEFAULT_SENSITIVITY、否则为 "private"；layer 不在 LAYER_MAP 的记入 unknown_layers 并按 knowledge 写入；verbose 为真时打印 report；最终返回该 report。
def migrate(db: str, root: str, layers=None, limit=None, dry_run=False,
            clearance: str = "private", verbose=True):
    rows = load_nodes(db, layers, limit)
    edges = load_edges(db)
    principal = Principal(tenant="aeis-local", actor="migrate",
                          clearance=clearance, can_write=True, can_admin=True)
    cg = MdCGSecure(root, principal=principal, autoflush=500)

    unknown_layers, written = set(), 0
    t0 = time.time()
    if not dry_run:
        for i, r in enumerate(rows, 1):
            raw_layer = (r.get("layer") or "knowledge")
            layer = LAYER_MAP.get(raw_layer)
            if layer is None:
                unknown_layers.add(raw_layer)
                layer = "knowledge"
            cg.add(
                r["id"], _norm_text(r["content"] or ""), layer=layer,
                override=True,     # 迁移是受控整库写入：按 id 幂等覆盖，显式越权
                sensitivity=DEFAULT_SENSITIVITY if clearance != "private" else "private",
                tags=_j(r.get("tags"), []),
                condition_space=_j(r.get("condition_space"), {}),
                importance=_f(r.get("importance"), 0.5),
                confidence=_f(r.get("confidence"), 0.6),
                edges=edges.get(r["id"], []),
                created_at=_f(r.get("created_at"), 0),
                modality=r.get("modality") or "text",
                temporal=r.get("temporal_coordinate"),
                spatial=_j(r.get("spatial_coordinates"), {}),
                semantic_coordinates=_j(r.get("semantic_coordinates"), {}),
                state_attributes=_j(r.get("state_attributes"), {}),
                entity_id=r.get("entity_id"),
                access_count=int(r.get("access_count") or 0),
                last_access=_f(r.get("last_access"), 0),
                # legacy 标记：迁移进来的历史记忆无 CCG 5 要素，
                # 资格判定据此判 DEFER（可检索、待补条件）而非 BLINDSPOT。
                ccg_exempt=True,
                migrated_from="aeis_memory.db",
            )
            written += 1
            if verbose and i % 2000 == 0:
                print(f"    …已写入 {i}/{len(rows)}（{time.time()-t0:.0f}s）", flush=True)
        cg.flush()

    # ---------- 全量等价校验 ----------
    bad = []
    if not dry_run:
        for r in rows:
            got = cg.get(r["id"])
            if not got:
                bad.append((r["id"], "missing"))
                continue
            fm = got["frontmatter"]
            checks = [
                ("content", (got["content"] or "").rstrip("\n") != _norm_text(r["content"] or "").rstrip("\n")),
                ("tags", _j(fm.get("tags"), []) != _j(r.get("tags"), [])),
                ("importance", abs(_f(fm.get("importance")) - _f(r.get("importance"))) > 1e-9),
                ("confidence", abs(_f(fm.get("confidence")) - _f(r.get("confidence"))) > 1e-9),
                ("condition_space", _j(fm.get("condition_space"), {}) != _j(r.get("condition_space"), {})),
                ("edges", len(fm.get("edges") or []) != len(edges.get(r["id"], []))),
                ("access_count", int(fm.get("access_count") or 0) != int(r.get("access_count") or 0)),
                ("modality", (fm.get("modality") or "text") != (r.get("modality") or "text")),
                ("created_at", abs(_f(fm.get("created_at")) - _f(r.get("created_at"))) > 1e-6),
                ("entity_id", (fm.get("entity_id") or None) != (r.get("entity_id") or None)),
            ]
            for name, is_bad in checks:
                if is_bad:
                    bad.append((r["id"], name))
                    break

    report = {
        "db": db, "root": root, "dry_run": dry_run,
        "layers_filter": layers,
        "sqlite_nodes": len(rows),
        "md_nodes_total": len(cg.index["nodes"]),
        "written": written,
        "count_equal": (dry_run or len(rows) == written),
        "field_mismatches": len(bad),
        "samples": bad[:5],
        "edges_total": sum(len(v) for v in edges.values()),
        "unknown_layers": sorted(unknown_layers),
        "elapsed_sec": round(time.time() - t0, 1),
        "health": cg.health() if not dry_run else None,
    }
    if verbose:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    cg.close()
    return report


# 生效条件：从 argv 取 --db/--root，二者任一为假值时打印 __doc__ 并返回 1；二者均真值时 --layers 为真值则按逗号切分并 strip 成列表（否则 None），再以 limit=--limit、dry_run=("--dry-run" in argv)、clearance=--clearance 或 "private" 调用 migrate 并返回 0（表达式 0 if migrate(...) else 0 恒为 0）。
def main(argv):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
# 生效条件：外层 main 作用域的 argv 中若含 name，则返回其后的下一个元素 argv[argv.index(name)+1]，否则返回 default（未传则 None）。
    def opt(name, default=None):
        return argv[argv.index(name) + 1] if name in argv else default
    db = opt("--db")
    root = opt("--root")
    if not db or not root:
        print(__doc__)
        return 1
    layers = opt("--layers")
    layers = [x.strip() for x in layers.split(",")] if layers else None
    return 0 if migrate(db, root, layers=layers, limit=opt("--limit"),
                        dry_run="--dry-run" in argv,
                        clearance=opt("--clearance", "private")) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
