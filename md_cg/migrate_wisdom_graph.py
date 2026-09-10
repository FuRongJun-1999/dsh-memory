# -*- coding: utf-8 -*-
"""md_cg · 白箱知识图 → md 原生图导出（对照实验）

目的：回答「图查询是否必须依赖 db？md 文档 + frontmatter 引用能否承载？」
白箱 `whitebox_kb/wisdom/wisdom-book-cloud.db`：nodes 4355 / edges 2948
（hierarchical 2832 · similar 71 · causal 45）。本模块把这张图原样导出为
md 认知图，再做**确定性**等价校验（不调 LLM、不依赖概率指标）。

映射（两个既有方向缺陷都在此绕开）
----------------------------------
1) 白箱 `hierarchical` 实测是 source(父) → target(子)（2832/2832 与
   `nodes.state_attributes.parent_card` 对齐），而 md_cg `subgraph.declared()`
   把 hierarchical 当 `part_of`（本节点是子）——口径相反，直接导会树倒置。
2) `subgraph.parents_index` 对 `part_of` 的处理与 `children_index` 相反
   （前者把 part_of 与 contains 并进同一分支），用 part_of 边会让
   `parent_of` / `roots()` / 溯源全算错（实测 PARENT_OF_C2=None）。

故本导出器**只用「父节点声明 subgraph.nodes」表达层级**——该分支在
children_index 与 parents_index 中解释一致且可逆。非层级边原样落到
`frontmatter.edges`，键名用 `relation_type`（subgraph/chain 只认
relation_type/relation，写 `type` 会静默丢边，`migrate_aeis` 即踩此坑）。

用法
----
    python -m md_cg.migrate_wisdom_graph --db <sqlite> --root <md_root> [选项]
    --limit N | --dry-run | --verify-only
"""
from __future__ import annotations

import collections
import json
import os
import sqlite3
import sys
import time

from .mdcos import MdCGOS

LEVEL_REL = "hierarchical"          # 白箱层级关系（source=父，target=子）
EXPORT_LAYER = "knowledge"          # 白箱 nodes.layer 实测全为 knowledge
_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(_HERE, "whitebox_kb", "wisdom", "wisdom-book-cloud.db")
DEFAULT_ROOT = os.path.join(os.path.dirname(_HERE), "_md_cg_wisdom_graph")


def _norm_text(s):
    """统一换行：md 按 LF 存，源库常含 CRLF，不规范化会造成假失败。"""
    if not s:
        return s or ""
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _j(v, default):
    if v is None or v == "":
        return default
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (ValueError, TypeError):
        return default


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _connect(db):
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def load_nodes(db, limit=None):
    con = _connect(db)
    con.row_factory = sqlite3.Row
    sql = "SELECT * FROM nodes ORDER BY created_at"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = [dict(r) for r in con.execute(sql)]
    con.close()
    return rows


def load_graph(db):
    """返回 (children_of, relations_of)。

    children_of:  {父 id: [子 id...]}    —— hierarchical（source=父）
    relations_of: {源 id: [边字典...]}   —— similar / causal 等非层级边
    """
    con = _connect(db)
    children, relations = collections.defaultdict(list), collections.defaultdict(list)
    for src, tgt, rel, cs, conf, weight, ver in con.execute(
            "SELECT source_id, target_id, relation_type, condition_space, "
            "confidence, weight, verified FROM edges"):
        src, tgt = str(src), str(tgt)
        rel = (rel or "").strip()
        if rel == LEVEL_REL:
            children[src].append(tgt)
            continue
        e = {"target": tgt, "relation_type": rel,
             "confidence": _f(conf, 0.7), "verified": int(ver or 0)}
        cs_j = _j(cs, None)
        if cs_j:
            e["condition_space"] = cs_j
        if weight is not None:
            e["weight"] = _f(weight, 1.0)
        relations[src].append(e)
    con.close()
    return children, relations


# --------------------------------------------------------------------------
# 写：sqlite → md
# --------------------------------------------------------------------------

def export(db=DEFAULT_DB, root=DEFAULT_ROOT, limit=None, dry_run=False,
           verbose=True):
    rows = load_nodes(db, limit)
    children, relations = load_graph(db)
    ids = {r["id"] for r in rows}
    name = os.path.basename(db)
    # 只保留两端都存在的边：悬空子会让 validate 报 dangling_child。
    # 预先算好（dry-run 也要如实统计），循环内直接取用。
    kids_map = {nid: [c for c in children.get(nid, []) if c in ids] for nid in ids}
    rels_map = {nid: [e for e in relations.get(nid, []) if e["target"] in ids]
                for nid in ids}
    n_edges_kept = sum(len(v) for v in kids_map.values())
    n_dangling = sum(len(children.get(nid, [])) for nid in ids) - n_edges_kept

    if not dry_run:
        cg = MdCGOS(root, actor="migrate-wisdom", autoflush=500)
        t0 = time.time()
        for i, r in enumerate(rows, 1):
            nid = r["id"]
            kids, rels = kids_map[nid], rels_map[nid]
            kw = {"subgraph": {"nodes": kids}} if kids else {}
            cg.add(
                nid, _norm_text(r.get("content") or ""),
                layer=EXPORT_LAYER,
                override=True,                      # 整库受控写入：按 id 幂等覆盖
                tags=_j(r.get("tags"), []),
                condition_space=_j(r.get("condition_space"), {}),
                importance=_f(r.get("importance"), 0.5),
                confidence=_f(r.get("confidence"), 0.6),
                edges=rels,
                created_at=_f(r.get("created_at"), 0),
                modality=r.get("modality") or "text",
                semantic_coordinates=_j(r.get("semantic_coordinates"), {}),
                state_attributes=_j(r.get("state_attributes"), {}),
                entity_id=r.get("entity_id"),
                access_count=int(r.get("access_count") or 0),
                last_access=_f(r.get("last_access"), 0),
                verification_basis="data",
                # legacy 标记：白箱正文非 CCG 五要素形态，资格判定据此判 DEFER
                # （可检索、待补条件）而非 BLINDSPOT。
                ccg_exempt=True,
                migrated_from=name,
                **kw)
            if verbose and i % 1000 == 0:
                print(f"    …已写入 {i}/{len(rows)}（{time.time()-t0:.0f}s）", flush=True)
        cg.flush()
        cg.rebuild_index()          # 落 subgraph/edges 进索引快照，供图遍历免读盘
        cg.close()

    rep = {"db": db, "root": root, "dry_run": dry_run,
           "sqlite_nodes": len(rows), "hier_edges_kept": n_edges_kept,
           "dangling_children": n_dangling,
           "rel_edges_kept": sum(len(v) for v in rels_map.values())}
    if not dry_run:
        rep["verify"] = verify(db, root, verbose=verbose)
        rep["ok"] = bool(rep["verify"]["ok"])
    if verbose:
        print(json.dumps(rep, ensure_ascii=False, indent=2), flush=True)
    return rep


# --------------------------------------------------------------------------
# 校验：md 侧 vs sqlite 侧（逐节点全量，不抽样）
# --------------------------------------------------------------------------

def verify(db=DEFAULT_DB, root=DEFAULT_ROOT, verbose=True):
    from . import subgraph as sg

    cg = MdCGOS(root)
    md_ids = set(cg.index["nodes"])
    children_db, relations_db = load_graph(db)
    nodes_db = {r["id"]: r for r in load_nodes(db)}
    ids = md_ids & set(nodes_db)

    # ---- L1 结构等价：子集合 / 父节点 / 树根 ----
    child_bad, parent_bad = [], []
    md_children, md_parents = {}, {}
    for nid in ids:
        want_ch = {c for c in children_db.get(nid, []) if c in md_ids}
        got_ch = set(sg.children(cg, nid))
        md_children[nid] = got_ch
        if want_ch != got_ch:
            child_bad.append({"id": nid, "db": sorted(want_ch), "md": sorted(got_ch)})
        # 反查父：db 侧由 hierarchical 边推出（白箱父边唯一）
        want_p = {p for p, cs in children_db.items() if nid in cs and p in md_ids}
        got_p = set(sg.parents_index(cg).get(nid) or [])
        md_parents[nid] = got_p
        if want_p != got_p:
            parent_bad.append({"id": nid, "db": sorted(want_p), "md": sorted(got_p)})

    roots_db = sorted(nid for nid in ids if not (md_parents[nid] or []))
    roots_md = sorted(set(sg.roots(cg)) & ids)

    # ---- L2 关系等价：非层级边 target 集合 ----
    rel_bad = []
    for nid in ids:
        want = sorted({e["target"] for e in relations_db.get(nid, []) if e["target"] in md_ids})
        fm = cg.get(nid)["frontmatter"]
        got = sorted({str(e.get("target")) for e in (fm.get("edges") or [])
                      if isinstance(e, dict) and e.get("target")})
        if want != got:
            rel_bad.append({"id": nid, "db": want, "md": got})

    # ---- L3 字段等价 ----
    def _cs_same(a, b):
        """md 写入侧按条件论纪律自动补 time_window（`mdcg.add` 的观测时间窗），
        比对时剔除该槽——它是有意增强，不是迁移失真。"""
        a, b = dict(_j(a, {}) or {}), dict(_j(b, {}) or {})
        a.pop("time_window", None)
        b.pop("time_window", None)
        return a == b

    field_bad, tw_added = [], 0
    for nid in ids:
        fm = cg.get(nid)["frontmatter"]
        r = nodes_db[nid]
        if "time_window" not in _j(r.get("condition_space"), {}):
            tw_added += 1
        checks = (
            ("condition_space", not _cs_same(fm.get("condition_space"), r.get("condition_space"))),
            ("tags", _j(fm.get("tags"), []) != _j(r.get("tags"), [])),
            ("importance", abs(_f(fm.get("importance")) - _f(r.get("importance"))) > 1e-9),
            ("confidence", abs(_f(fm.get("confidence")) - _f(r.get("confidence"))) > 1e-9),
            ("modality", (fm.get("modality") or "text") != (r.get("modality") or "text")),
        )
        for name, bad in checks:
            if bad:
                field_bad.append({"id": nid, "field": name})
                break

    out = {
        "db": db, "root": root,
        "nodes": {"db": len(nodes_db), "md": len(md_ids),
                  "missing": sorted(set(nodes_db) - md_ids)[:5],
                  "n_missing": len(set(nodes_db) - md_ids)},
        "L1_hierarchy": {
            "md_edges": sum(len(v) for v in md_children.values()),
            "child_mismatch": len(child_bad), "parent_mismatch": len(parent_bad),
            "samples": (child_bad[:3] + parent_bad[:3]),
            "roots_db": len(roots_db), "roots_md": len(roots_md),
            "roots_equal": roots_db == roots_md,
        },
        "L2_relations": {"mismatch": len(rel_bad), "samples": rel_bad[:3]},
        "L3_fields": {"mismatch": len(field_bad), "samples": field_bad[:3],
                      "time_window_added_by_discipline": tw_added},
        "tree_validate": sg.validate(cg, limit=5),
    }
    out["ok"] = (not out["nodes"]["n_missing"] and not child_bad and not parent_bad
                 and not rel_bad and not field_bad and out["L1_hierarchy"]["roots_equal"]
                 and out["tree_validate"]["issues"] == 0)
    cg.close()
    if verbose:
        print(json.dumps({k: v for k, v in out.items() if k != "tree_validate"},
                         ensure_ascii=False, indent=2), flush=True)
    return out


REC_SUBTREE_SQL = (
    "WITH RECURSIVE sub(id) AS (SELECT ? "
    "UNION SELECT e.target_id FROM edges e JOIN sub s ON e.source_id = s.id "
    "WHERE e.relation_type = ?) SELECT id FROM sub")


def bench_graph(db=DEFAULT_DB, root=DEFAULT_ROOT, n_roots=30, verbose=True):
    """L4 子树展开等价 + 森林完整性（回答「图**查询**能否由 md 承担」）。

    L1 已证逐节点邻接等价，递归展开原则上同构；此处**实测**以覆盖
    `subgraph.flatten` 自身的 max_depth / max_nodes 截断与环处理。
    db 侧递归 CTE，md 侧 flatten，两侧都在同一份 md 节点集上取交集比对。

    森林完整性是一条强校验：白箱父边唯一 ⇒ 各根子树互不相交且并集 = 全图。
    有环 / 漏边 / 多父，都会让两侧节点和立刻不一致。
    """
    from . import subgraph as sg

    cg = MdCGOS(root)
    md_ids = set(cg.index["nodes"])
    con = _connect(db)
    roots_md = sorted(set(sg.roots(cg)) & md_ids)

    def _db_subtree(nid):
        return {r[0] for r in con.execute(REC_SUBTREE_SQL, (nid, LEVEL_REL)).fetchall()}

    bad = []
    for nid in roots_md[:n_roots]:
        want = _db_subtree(nid) & md_ids
        got = set(sg.flatten(cg, nid, max_nodes=10 ** 9)["nodes"])
        if want != got:
            bad.append({"root": nid, "db_n": len(want), "md_n": len(got),
                        "only_db": sorted(want - got)[:3],
                        "only_md": sorted(got - want)[:3]})

    n_db = sum(len(_db_subtree(nid) & md_ids) for nid in roots_md)
    n_md = sum(sg.flatten(cg, nid, max_nodes=10 ** 9)["n_nodes"] for nid in roots_md)
    con.close()
    cg.close()

    out = {"roots": len(roots_md), "roots_sampled": min(n_roots, len(roots_md)),
           "subtree_mismatch": len(bad), "samples": bad[:3],
           "forest_nodes_db": n_db, "forest_nodes_md": n_md,
           "total_nodes": len(md_ids),
           "forest_partition_ok": n_db == n_md == len(md_ids)}
    out["ok"] = (not bad) and out["forest_partition_ok"]
    if verbose:
        print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)
    return out


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    def opt(name, default=None):
        return argv[argv.index(name) + 1] if name in argv else default

    db = opt("--db", DEFAULT_DB)
    root = opt("--root", DEFAULT_ROOT)
    if "--verify-only" in argv:
        return 0 if verify(db, root)["ok"] else 1
    if "--bench-graph" in argv:
        return 0 if bench_graph(db, root)["ok"] else 1
    lim = opt("--limit")
    rep = export(db=db, root=root, limit=int(lim) if lim else None,
                 dry_run="--dry-run" in argv)
    if rep.get("dry_run"):
        return 0
    return 0 if rep.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
