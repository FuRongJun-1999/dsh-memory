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


DUP_REASONS = ("exact_dup", "exact_duplicate", "duplicate", "dedup")


def classify_outcome(out):
    """把 writepipe 返回归类成 (status, detail)。

    E151 修：旧版靠**返回形态**猜结果——`out.get("committed")` 真、或者
    `gate.verdict == "DROP"`，就把这一行记成「幂等去重即成功」。问题有三：
      ① committed 若不是 True（如 "true"、1、dict）也算成功，缺显式校验；
      ② 任何 DROP 都算幂等成功，可 gate 拒收（安全/越权/格式）与 exact_dup
         是两回事，混在一起等于把拒收洗成「已存在」；
      ③ 缺 verdict、或 verdict 大小写不同的返回一律进 failed，形态一变
         「已存在」就翻脸成失败。
    现在：显式看 committed is True；DROP 只在 reason ∈ DUP_REASONS 时算幂等；
    其它 DROP 记 rejected（带原因）；拿不到判定记 failed（带原样返回）。
    """
    if not isinstance(out, dict):
        return "failed", {"error": "返回非 dict：%r" % (out,)[:200]}
    if out.get("committed") is True:
        return "committed", {}
    # 真机读数（2026-10-25 实跑 546 行）：重跑同一行时返回的不是 DROP，而是
    # committed=false + moved_to=review_queue + autonomy.decision=confirm——即
    # 覆写判定发生在 exact_dup 之前，重跑会往审核队列里堆变更单。这既不是
    # 「已存在（幂等）」，也不是「写失败」，必须单列，否则会被洗成其中一边。
    moved = str(out.get("moved_to") or "")
    auto = out.get("autonomy") or {}
    if moved == "review_queue" or str(auto.get("decision") or "") in ("confirm", "defer"):
        return "deferred", {"moved_to": moved or "(未标落点)",
                            "decision": auto.get("decision"),
                            "pid": out.get("pid")}
    gate = out.get("gate") or {}
    verdict = out.get("verdict") or {}
    state = str(gate.get("verdict") or verdict.get("state") or "").upper()
    reason = str(gate.get("reason") or verdict.get("reason")
                 or out.get("reason") or "").lower()
    if state == "DROP":
        if any(reason.startswith(r) for r in DUP_REASONS):
            return "dropped", {"reason": reason}
        return "rejected", {"state": state, "reason": reason or "(未给原因)"}
    return "failed", {"state": state or "(缺 verdict)", "out": str(out)[:300]}


def migrate(cg, rows):
    """逐行迁移：row → 载荷 → writepipe 既有审核链。返回统计。"""
    stats = {"rows": len(rows), "committed": 0, "dropped": 0, "rejected": 0,
             "deferred": 0, "identical": 0, "failed": [], "by_reason": {}}
    for i, row in enumerate(rows):
        try:
            payload = hyperedge.row_from_ledger(row)
            nid = hyperedge.node_id_for(row)
            # 幂等前置判据（E151）：写链在 confirm 档下会把「同 id 覆写」先送审，
            # 于是重跑 546 行会往审核队列堆 546 张变更单，返回里没有 DROP，旧逻辑
            # 只能记成 failed。真正想知道的「这条已经在了」由内容比对直接给。
            existing = cg.get(nid) or {}
            rec_body = (existing.get("content") or "").rstrip("\n")
            pay_body = payload["content"].rstrip("\n")
            # 写链会在正文前补一行 `# 验证方式：…`、并在尾部补换行，故用「载荷正文被
            # 节点正文包含」判同文：node_id 由台账行确定性推出，同 id 且同文即幂等。
            if rec_body and pay_body and pay_body in rec_body:
                stats["identical"] += 1
                continue
            a = {"op": "write", "content_kind": hyperedge.CONTENT_KIND,
                 "content": payload["content"],
                 "node_id": nid,
                 "layer": "knowledge", "tags": ["receipt", "hyperedge"]}
            a.update(payload["frontmatter"])     # fm 键平铺（EXTRA_FM_KEYS 通道）
            out = writepipe.default_pipeline().execute(cg, a)
            status, detail = classify_outcome(out)
            if status == "committed":
                stats["committed"] += 1
            elif status == "dropped":
                stats["dropped"] += 1            # exact_dup：幂等去重即成功
                r = detail.get("reason") or "?"
                stats["by_reason"][r] = stats["by_reason"].get(r, 0) + 1
            elif status == "rejected":
                stats["rejected"] += 1
                stats["failed"].append({"line": i + 2, "row": dict(row),
                                        "rejected": detail})
            elif status == "deferred":
                stats["deferred"] += 1
                stats["failed"].append({"line": i + 2, "row": dict(row),
                                        "deferred": detail})
            else:
                stats["failed"].append({"line": i + 2, "row": dict(row),
                                        "out": detail})
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
            "rejected": stats2.get("rejected", 0),
            "deferred": stats2.get("deferred", 0),
            "identical": stats2.get("identical", 0),
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
        print("迁移① committed=%d dropped=%d rejected=%d deferred=%d identical=%d failed=%d%s"
              % (s1["committed"], s1["dropped"], s1["rejected"], s1["deferred"],
                 s1["identical"], len(s1["failed"]),
                 ("（去重原因 %s）" % json.dumps(s1["by_reason"], ensure_ascii=False))
                 if s1["by_reason"] else ""))
        if s1["failed"]:
            for f in s1["failed"][:5]:
                print("  失败行 L%s：%s" % (f["line"], f.get("error")
                                            or json.dumps(f.get("rejected")
                                                          or f.get("out") or "",
                                                          ensure_ascii=False)[:120]))
        h1 = h1_replay(cg, rows)
        print("H1 全量回放：%d/%d 一致（坏 %d）"
              % (h1["consistent"], h1["checked"], h1["bad_total"]))
        before = _count_hyperedges(cg)
        s2 = migrate(cg, rows)
        h2 = h2_idempotent(cg, rows, before, s2)
        print("H2 幂等重跑：%s（before=%s after=%s recommit=%d redrop=%d"
              " rejected=%d deferred=%d identical=%d refail=%d）"
              % ("OK" if h2["ok"] else "FAIL", h2["before"], h2["after"],
                 h2["recommitted"], h2["redropped"], h2["rejected"],
                 h2["deferred"], h2["identical"], h2["refailed"]))
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
