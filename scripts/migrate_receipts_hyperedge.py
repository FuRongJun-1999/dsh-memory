# -*- coding: utf-8 -*-
"""回执台账 → 超边迁移（第四阶段计划批次 B）。

把 hive/interop/_receipts_ledger.tsv（六列回执台账）逐行迁入认知图为
hyperedge 节点（一行 = 一条超边），走 writepipe 既有审核链（audit 闸经
hyperedge 回放比对验证器裁决），并当场跑回放验收：

  H1 全量回放  逐节点 payload_from_node 重建六列 ↔ 原 TSV 行逐字段一致
  H2 幂等      重跑迁移不产生重复节点（同 id 覆写或 exact_dup DROP）
  H3 检索可见  content_kind=hyperedge 枚举数 == 迁移数 + 词面检索命中

用法（仓库根）：
    python scripts/migrate_receipts_hyperedge.py                # 默认临时库验收
    python scripts/migrate_receipts_hyperedge.py --root <库根>  # 迁入指定库
    python scripts/migrate_receipts_hyperedge.py --json out.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import audit as audit_mod          # noqa: E402
from md_cg import hyperedge, writepipe        # noqa: E402
from md_cg.mdcos import MdCGSecure            # noqa: E402
from md_cg.security import Principal          # noqa: E402

DEFAULT_LEDGER = os.path.join(_REPO, "hive", "interop", "_receipts_ledger.tsv")


def load_rows(ledger_path):
    """TSV → List[dict]（六列；短行右侧补空列，表头行跳过）。"""
    with open(ledger_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        header = next(reader)
        rows = []
        for parts in reader:
            if not parts or not any(p.strip() for p in parts):
                continue
            if len(parts) < len(header):
                parts = parts + [""] * (len(header) - len(parts))
            rows.append({k: v for k, v in zip(header, parts)})
    missing = [c for c in hyperedge.LEDGER_COLUMNS if c not in header]
    if missing:
        raise ValueError("台账表头缺列：%s（fail-closed）" % missing)
    return rows


def migrate(cg, rows):
    """逐行迁移：row → 载荷 → writepipe 既有审核链。返回统计。"""
    stats = {"rows": len(rows), "committed": 0, "dropped": 0, "failed": []}
    for i, row in enumerate(rows):
        try:
            payload = hyperedge.row_from_ledger(row)
            a = {"op": "write", "content_kind": hyperedge.CONTENT_KIND,
                 "content": payload["content"],
                 "node_id": hyperedge.node_id_for(row),
                 "layer": "knowledge", "tags": ["receipt", "hyperedge"]}
            a.update(payload["frontmatter"])     # fm 键平铺（EXTRA_FM_KEYS 通道）
            out = writepipe.default_pipeline().execute(cg, a)
            if out.get("committed"):
                stats["committed"] += 1
            elif (out.get("gate") or {}).get("verdict") == "DROP" \
                    or (out.get("verdict") or {}).get("state") == "DROP":
                stats["dropped"] += 1            # exact_dup：幂等去重即成功
            else:
                stats["failed"].append({"line": i + 2, "row": dict(row),
                                        "out": str(out)[:300]})
        except Exception as exc:  # noqa: BLE001
            stats["failed"].append({"line": i + 2, "row": dict(row),
                                    "error": repr(exc)})
    return stats


def h1_replay(cg, rows):
    """H1 全量回放：节点反解六列 ↔ 原 TSV 行逐字段一致 + 验证器 ACCEPT。"""
    bad = []
    for i, row in enumerate(rows):
        nid = hyperedge.node_id_for(row)
        rec = cg.get(nid)
        if not rec:
            bad.append({"line": i + 2, "node_id": nid, "error": "节点缺失"})
            continue
        try:
            rebuilt = hyperedge.rows_from_fm(rec.get("frontmatter") or {})
        except ValueError as exc:
            bad.append({"line": i + 2, "node_id": nid, "error": str(exc)})
            continue
        expect = {c: (row.get(c) or "").strip() for c in hyperedge.LEDGER_COLUMNS}
        diffs = [c for c in hyperedge.LEDGER_COLUMNS if rebuilt[c] != expect[c]]
        if diffs:
            bad.append({"line": i + 2, "node_id": nid, "diffs": diffs,
                        "rebuilt": rebuilt, "expect": expect})
            continue
        v = hyperedge.verify_payload(hyperedge.payload_from_node(rec))
        if v["state"] != "ACCEPT":
            bad.append({"line": i + 2, "node_id": nid, "verdict": str(v)[:200]})
    return {"checked": len(rows), "consistent": len(rows) - len(bad),
            "bad": bad[:20], "bad_total": len(bad)}


def h2_idempotent(cg, rows, before_count, stats2):
    """H2 幂等：重跑后节点数不变、无 REJECT/DEFER 失败、回放仍一致。"""
    after_count = _count_hyperedges(cg)
    return {"before": before_count, "after": after_count,
            "recommitted": stats2["committed"], "redropped": stats2["dropped"],
            "refailed": len(stats2["failed"]),
            "ok": (before_count == after_count and not stats2["failed"])}


def _hit_node(h):
    """search 命中元素兼容两形态：dict 节点或 (node, score, qual) 元组。"""
    if isinstance(h, dict):
        return h
    if isinstance(h, (tuple, list)):
        for x in h:
            if isinstance(x, dict) and ("frontmatter" in x or "content" in x
                                        or "id" in x):
                return x
    return {}


def h3_visible(cg, rows):
    """H3 检索可见：枚举数对账 + 词面命中冒烟（commit 与 verify_id 各一）。"""
    n_enum = _count_hyperedges(cg)
    probes = {}
    for col in ("commit", "verify_id"):
        token = next(((r.get(col) or "").strip()
                      for r in reversed(rows) if (r.get(col) or "").strip()), "")
        if token:
            hits, _meta = cg.search(token)
            probes[col] = {"token": token, "hits": len(hits),
                           "in_top10": any(
                               (_hit_node(h).get("frontmatter") or
                                _hit_node(h)).get("content_kind")
                               == hyperedge.CONTENT_KIND
                               for h in hits[:10])}
    return {"enumerated": n_enum, "expected": len(rows),
            "count_ok": n_enum == len(rows), "probes": probes,
            "ok": n_enum == len(rows) and all(
                p["in_top10"] for p in probes.values())}


def _count_hyperedges(cg):
    n = 0
    for nid in list(cg.index.get("nodes", {})):
        fm = (cg.get(nid) or {}).get("frontmatter") or {}
        if fm.get("content_kind") == hyperedge.CONTENT_KIND:
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description="回执台账 → 超边迁移（批次 B）")
    ap.add_argument("--ledger", default=DEFAULT_LEDGER, help="台账 TSV 路径")
    ap.add_argument("--root", default=None,
                    help="认知图库根（缺省临时库，验收用完即弃形态）")
    ap.add_argument("--json", default=None, help="验收结果 JSON 落盘路径")
    args = ap.parse_args()

    rows = load_rows(args.ledger)
    print("台账 %s：%d 数据行（表头 1 行已跳过）" % (args.ledger, len(rows)))

    root = args.root or tempfile.mkdtemp(prefix="receipts_hyperedge_")
    p = Principal(tenant="default", actor="migrate_receipts", role="designer",
                  can_write=True, can_admin=True)
    cg = MdCGSecure(root, principal=p)
    hyperedge.register(audit_mod)     # 回放比对验证器注入（否则 audit DEFER）
    try:
        s1 = migrate(cg, rows)
        print("迁移① committed=%d dropped=%d failed=%d"
              % (s1["committed"], s1["dropped"], len(s1["failed"])))
        if s1["failed"]:
            for f in s1["failed"][:5]:
                print("  失败行 L%s：%s" % (f["line"], f.get("error")
                                            or f.get("out", "")[:120]))
        h1 = h1_replay(cg, rows)
        print("H1 全量回放：%d/%d 一致（坏 %d）"
              % (h1["consistent"], h1["checked"], h1["bad_total"]))
        before = _count_hyperedges(cg)
        s2 = migrate(cg, rows)
        h2 = h2_idempotent(cg, rows, before, s2)
        print("H2 幂等重跑：%s（before=%s after=%s recommit=%d redrop=%d"
              " refail=%d）" % ("OK" if h2["ok"] else "FAIL", h2["before"],
                               h2["after"], h2["recommitted"], h2["redropped"],
                               h2["refailed"]))
        h1b = h1_replay(cg, rows)
        h2["replay_ok"] = h1b["bad_total"] == 0
        h3 = h3_visible(cg, rows)
        print("H3 检索可见：%s（枚举 %d/%d；探针 %s）"
              % ("OK" if h3["ok"] else "FAIL", h3["enumerated"],
                 h3["expected"], json.dumps(h3["probes"], ensure_ascii=False)))

        all_ok = (not s1["failed"]) and h1["bad_total"] == 0 \
            and h2["ok"] and h2["replay_ok"] and h3["ok"]
        print("\n验收判定：%s（root=%s）" % ("PASS" if all_ok else "FAIL", root))
        if args.json:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump({"ledger": args.ledger, "root": root,
                           "migrate1": s1, "h1": h1, "h2": h2, "h3": h3,
                           "all_ok": all_ok},
                          f, ensure_ascii=False, indent=2, default=str)
            print("结果已落盘：%s" % args.json)
        return 0 if all_ok else 1
    finally:
        cg.close()


if __name__ == "__main__":
    sys.exit(main())
