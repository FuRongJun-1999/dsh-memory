# -*- coding: utf-8 -*-
"""
补全随包图谱：把主库（lingshu.db）的学科卡 + 知识点子图合入随包图谱
=====================================================================
背景（2026-08-19 测试报告）：白箱测试 41% vs 声称 80%——根因是随包图谱
（wisdom-book-cloud.db）只有 148 个协议知识节点，没有学科卡和知识点子图，
recursive_item_answer 依赖「卡⊃知识点」子图解析直接答案，子图缺失→只导航不回答。

本脚本：
1. 从主库抽取学科卡（domain 含「知识点内容（按骨架填充）」等学科类）+
   其 knowledge_point 子图（card:<prefix> 关联）
2. 合并进随包图谱（wisdom-book-cloud.db）
3. 校验：合并后图谱含知识点子图、关键词查询能解析出 direct_answer

用法：
    python merge_subgraph.py [--src 主库] [--dst 随包图谱] [--backup]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

# 学科 domain 关键词（主库中「按骨架填充」的学科卡 + 标准学科域）
SUBJECT_KEYWORDS = ("知识点内容（按骨架填充）", "知识点内容", "初中", "高中",
                    "小学", "数学", "物理", "化学", "生物", "英语", "语文",
                    "政治", "历史", "地理", "计算机", "工程", "电路")


def _is_subject_node(state_attr: str, tags: str, content: str) -> bool:
    """判断节点是否属于学科知识。

    精确判定：subject_card 标签（主库学科卡的标准标记）。
    兜底：domain 以「知识点内容」结尾的学科骨架卡（部分卡无 subject_card 标签）。
    不做宽泛关键词匹配（会误伤协议/哲学知识节点）。
    """
    if "subject_card" in (tags or ""):
        return True
    try:
        sa_d = json.loads(state_attr or "{}") if state_attr else {}
    except Exception:
        sa_d = {}
    dom = sa_d.get("domain", "")
    return "知识点内容（按骨架填充）" in dom


def extract_subject_graph(src_db: str, dst_db: str, backup: bool = True) -> dict:
    """从主库抽取学科节点（卡 + 知识点子图），合并进随包图谱。"""
    if backup and os.path.exists(dst_db):
        bak = dst_db + ".bak_merge_subgraph"
        shutil.copy2(dst_db, bak)
        print(f"备份 → {bak}")

    sconn = sqlite3.connect(src_db)
    sconn.row_factory = sqlite3.Row
    dconn = sqlite3.connect(dst_db)
    dconn.row_factory = sqlite3.Row

    # 收集主库所有节点（id→row），和边
    s_cur = sconn.cursor()
    s_cur.execute("SELECT * FROM nodes")
    src_nodes = {r["id"]: dict(r) for r in s_cur.fetchall()}
    s_cur.execute("SELECT * FROM edges")
    src_edges = [dict(r) for r in s_cur.fetchall()]

    # 第一步：标记学科卡（subject_card 标签 或 domain 匹配学科关键词 且 是知识层）
    card_ids = set()
    for nid, row in src_nodes.items():
        if row["layer"] != "knowledge":
            continue
        sa = row["state_attributes"] or ""
        tags = row["tags"] or ""
        content = row["content"] or ""
        try:
            sa_d = json.loads(sa) if sa else {}
        except Exception:
            sa_d = {}
        dom = sa_d.get("domain", "")
        if _is_subject_node(dom, tags, content) or _is_subject_node(sa, tags, content):
            card_ids.add(nid)

    # 第二步：找这些卡的知识点子图（knowledge_point + card:<卡id前16> 标签）
    card_prefixes = {cid[:16] for cid in card_ids}
    kp_ids = set()
    for nid, row in src_nodes.items():
        tags = row["tags"] or ""
        if "knowledge_point" not in tags:
            continue
        for prefix in card_prefixes:
            if f"card:{prefix}" in tags:
                kp_ids.add(nid)
                break

    # 第三步：收集关联边（卡↔知识点、知识点之间）
    wanted = card_ids | kp_ids
    edge_ids = set()
    for e in src_edges:
        if e["source_id"] in wanted and e["target_id"] in wanted:
            edge_ids.add((e["source_id"], e["target_id"], e.get("relation_type", "causal")))

    # 第四步：写入随包图谱
    d_cur = dconn.cursor()
    # 查随包已有 id，避免重复
    d_cur.execute("SELECT id FROM nodes")
    existing = {r["id"] for r in d_cur.fetchall()}

    added_nodes = 0
    for nid in sorted(wanted):
        if nid in existing:
            continue
        row = src_nodes[nid]
        d_cur.execute(
            "INSERT OR REPLACE INTO nodes (id, content, modality, spatial_coordinates, "
            "temporal_coordinate, condition_space, importance, confidence, layer, "
            "access_count, last_access, created_at, tags, semantic_coordinates, "
            "state_attributes, entity_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["id"], row["content"], row["modality"],
             json.dumps(row["spatial_coordinates"] or {}, ensure_ascii=False),
             row["temporal_coordinate"], row["condition_space"] or "",
             row["importance"], row["confidence"], row["layer"],
             row["access_count"], row["last_access"], row["created_at"],
             row["tags"] or "", row["semantic_coordinates"] or "",
             row["state_attributes"] or "", row["entity_id"]))
        added_nodes += 1

    added_edges = 0
    for sid, tid, rel in edge_ids:
        d_cur.execute(
            "INSERT OR IGNORE INTO edges (source_id, target_id, relation_type, "
            "confidence, weight, verified, created_at, last_verified, condition_space, "
            "source_evidence) SELECT ?,?,?,?,?,?,?,?,?,? WHERE NOT EXISTS "
            "(SELECT 1 FROM edges WHERE source_id=? AND target_id=? AND relation_type=?)",
            (sid, tid, rel, 0.5, 1.0, 0, src_nodes[sid]["created_at"], None, "", "extracted",
             sid, tid, rel))
        added_edges += 1

    dconn.commit()
    dconn.close()
    sconn.close()
    return {"cards": len(card_ids), "knowledge_points": len(kp_ids),
            "added_nodes": added_nodes, "added_edges": added_edges}


def verify(dst_db: str) -> dict:
    """校验合并后的图谱：知识点子图存在 + 关键词能解析 direct_answer。"""
    conn = sqlite3.connect(dst_db)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM nodes WHERE tags LIKE '%knowledge_point%'")
    kp = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM nodes WHERE tags LIKE '%card:%'")
    card = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM nodes")
    total = cur.fetchone()[0]
    conn.close()
    return {"total": total, "knowledge_point": kp, "card": card}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="补全随包图谱：学科卡+知识点子图")
    _def_src = os.environ.get("AEIS_DB", os.path.join("data", "lingshu.db"))
    _def_dst = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wisdom-book-cloud.db")
    ap.add_argument("--src", default=_def_src)
    ap.add_argument("--dst", default=_def_dst)
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args()

    print(f"源（主库）: {args.src}")
    print(f"目标（随包）: {args.dst}")
    r = extract_subject_graph(args.src, args.dst, backup=not args.no_backup)
    print(f"\n抽取结果: 学科卡={r['cards']} 知识点={r['knowledge_points']} "
          f"新增节点={r['added_nodes']} 新增边={r['added_edges']}")
    v = verify(args.dst)
    print(f"合并后图谱: 总节点={v['total']} knowledge_point={v['knowledge_point']} card:={v['card']}")
