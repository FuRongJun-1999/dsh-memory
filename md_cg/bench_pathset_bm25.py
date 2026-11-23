# -*- coding: utf-8 -*-
"""路径选择 A/B：lexical 路 vs bm25 路（issue #999 实测）。

issue #999 的论点：mdcg_recall 缺省六路里只有 lexical 这一条词法路，而更强的
bm25 路留在 opt-in 后面。本脚本在**同一库、同一查询集、同一融合口径**下把
路径集当作唯一自变量，如实报指标与延迟——不做预设结论。

数据：data/memory-bench-1000.jsonl（真实库分层抽样，250 signal / 400 noise / 350 unlabeled）
查询：复用 bench_membench.make_queries 的四种确定性模式（orig/head/para/drop）
指标：self@1 / self@K / MRR / sigP@K / noiseP@K + 每题平均耗时
融合：缺省 max（与 mcp_server.recall_fusion_default 的缺省态一致）

跑法：
    python -X utf8 -m md_cg.bench_pathset_bm25 --n 250
    python -X utf8 -m md_cg.bench_pathset_bm25 --n 60 --rebuild
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import bench_membench as B

ROOT_B = B.ROOT + "_pathset"

# 当前 mdcg_recall 缺省六路（mdcos.search_rrf 的缺省集，paths=None 时生效）
RECALL_DEFAULT = ("lexical", "bucket", "entity", "graph", "chain", "temporal")
# issue 建议 1：把 lexical 换成 bm25
WITH_BM25 = ("bm25", "bucket", "entity", "graph", "chain", "temporal")
# 消融：单路
LEX_ONLY = ("lexical",)
BM25_ONLY = ("bm25",)
# 消融：bm25 + lexical 同时在场（issue 报告 0.7589 < 0.8234）
MIXED = ("bm25", "lexical", "bucket", "entity", "graph", "chain", "temporal")

ARMS = [
    ("缺省六路（lexical）", RECALL_DEFAULT),
    ("换 bm25（建议 1）", WITH_BM25),
    ("lexical 单路", LEX_ONLY),
    ("bm25 单路", BM25_ONLY),
    ("bm25+lexical 混合", MIXED),
]


def _pct(x):
    return "%.1f%%" % (100.0 * x) if x is not None else "-"


def _run_timed(cg, qs, arm, k):
    t0 = time.perf_counter()
    rows = B.run_arm(cg, qs, arm, k=k, fusion="max")
    dt = time.perf_counter() - t0
    return rows, dt / max(1, len(rows))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=250)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()
    k = args.k

    rows = B.load_rows()
    t0 = time.perf_counter()
    cg = B.build(ROOT_B, rows, verbose=True)
    print("  建库耗时 %.1fs" % (time.perf_counter() - t0))
    qs = B.make_queries(rows, n=args.n)
    print("  查询 %d 条（signal 抽样 %d × 四模式）" % (len(qs), args.n))

    results = []
    for name, arm in ARMS:
        detail, avg_ms = _run_timed(cg, qs, arm, k)
        s = B.summarize(detail, k=k)
        results.append((name, arm, s, avg_ms, detail))
        print("  跑完 %-18s %.1f ms/查询" % (name, avg_ms * 1000))

    print()
    print("路径集 A/B（max 融合，Top-%d，n=%d）" % (k, len(qs)))
    print("%-22s%9s%9s%8s%8s%8s%10s" % ("臂", "self@1", "self@%d" % k, "MRR", "sigP", "noiseP", "ms/查询"))
    print("-" * 76)
    for name, arm, s, avg_ms, _ in results:
        print("%-22s%9s%9s%8.3f%8s%8s%10.1f" % (
            name, _pct(s["self@1"]), _pct(s["self@%d" % k]), s["mrr"],
            _pct(s["sigP"]), _pct(s["noiseP"]), avg_ms * 1000))
    print("-" * 76)

    # 分模式（orig/head/para/drop）——para 是词法最容易失手的模式
    print()
    print("分模式 self@%d" % k)
    modes = ["orig", "head", "para", "drop"]
    print("%-22s" % "臂" + "".join("%9s" % m for m in modes))
    print("-" * 58)
    for name, arm, _s, _ms, detail in results:
        line = "%-22s" % name
        for m in modes:
            sub = [r for r in detail if r["mode"] == m]
            if not sub:
                line += "%9s" % "-"
                continue
            hit = sum(1 for r in sub if 0 < r["rank"] <= k)
            line += "%9s" % _pct(hit / len(sub))
        print(line)
    print("-" * 58)

    # 显著性：缺省六路 vs 换 bm25（配对 bootstrap，复用 bench_membench）
    base = results[0][4]
    new = results[1][4]
    try:
        B.print_sig(base, new, qs, k=k)
    except Exception as e:
        print("  显著性检验跳过：%s" % type(e).__name__, str(e)[:80])
    return 0


if __name__ == "__main__":
    sys.exit(main())