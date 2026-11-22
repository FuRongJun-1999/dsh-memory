# -*- coding: utf-8 -*-
"""bm25 路的 CJK 分词边界探针（issue #999 决策用）。

背景：md_cg/bm25.py 的 _WORDS 正则以「连续汉字段」和「连续非汉字段」两个分支切词，
即 **一段连续汉字 = 一个 token**（不做中文分词）。而 lexical 路是子串匹配（LIKE）。
即 **一段连续汉字 = 一个 token**（不做分词）。而 lexical 路是子串匹配（LIKE）。
因此中文库里 bm25 是否命中，取决于「查询的汉字连续段是否与正文的某段完全一致」。

本探针在真实中文语料（memory-bench-1000）上把这条边界量出来：
  full   查询 = 整条正文      （极限情形：token 完全相同 ⇒ bm25 应当能中）
  prefix 查询 = 前 20 字      （词法路天花板）
  mid    查询 = 正文中部 12 字（真实查询的常态：只说一句中间的话）
  para   查询 = 同义词改写    （泛化说法）

跑法：python -X utf8 -m md_cg.bench_bm25_cjk
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import bench_membench as B

ROOT = B.ROOT + "_cjk"
LEX = ("lexical",)
BM = ("bm25",)


def make_probe_queries(rows, n=120, seed=7):
    import random
    rng = random.Random(seed)
    cand = [r for r in rows if r.get("label") == "signal" and len(r.get("text") or "") >= 40]
    if n and n < len(cand):
        cand = rng.sample(cand, n)
    qs = []
    for r in cand:
        t = r["text"]
        qs.append({"mode": "full", "q": t, "target": r["id"]})
        qs.append({"mode": "prefix", "q": t[:20], "target": r["id"]})
        qs.append({"mode": "mid", "q": t[len(t) // 2: len(t) // 2 + 12], "target": r["id"]})
        para, hits = B.paraphrase(t[:60])
        if hits:
            qs.append({"mode": "para", "q": para[:40], "target": r["id"]})
    return qs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args()
    rows = B.load_rows()
    cg = B.build(ROOT, rows, verbose=True)
    qs = make_probe_queries(rows, n=args.n)
    k = args.k
    print("  探针查询 %d 条" % len(qs))
    print()
    print("%-8s%8s%12s%12s" % ("模式", "题数", "lexical@%d" % k, "bm25@%d" % k))
    print("-" * 42)
    for mode in ("full", "prefix", "mid", "para"):
        sub = [x for x in qs if x["mode"] == mode]
        if not sub:
            continue
        line = "%-8s%8d" % (mode, len(sub))
        for arm in (LEX, BM):
            r = B.run_arm(cg, sub, arm, k=k, fusion="max")
            hit = sum(1 for x in r if 0 < x["rank"] <= k)
            line += "%11.1f%%" % (100.0 * hit / len(sub))
        print(line)
    print("-" * 42)
    print("  读法：full→mid 的落差就是「连续汉字算一个 token」的边界代价。")
    return 0


if __name__ == "__main__":
    sys.exit(main())