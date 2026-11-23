# -*- coding: utf-8 -*-
"""LongMemEval-S 上的路径集 A/B：lexical 六路 vs bm25 六路（issue #999 复现）。

与 bench_pathset_bm25 的分工：那个跑仓库自带的 memory-bench-1000（查询是原文片段，
五臂 self@1 全 100%，**饱和**，测不出路径差异）；本脚本跑 LongMemEval-S 真实问答语料，
GT 是 has_answer 的证据 turn，不会有饱和问题。

口径与官方 retrieval 一致的部分：
  * 只索引 user turn（转换器已过滤）；
  * GT = answer_session_ids 内 has_answer 的 turn；
  * 跳过 `_abs` 与无 GT 题（转换器已做）。
与官方不同、必须声明的一点：
  * 官方每题只在自己的 haystack 里检索；本脚本**建一个全局库**（所有题的所有 session
    去重后入库），因此每题会看到别题的 session 当干扰项 —— 比官方更难。
    所以报两组指标：raw（全局口径，可直接横向比臂）与 own（只数本题 haystack 内的
    返回，逼近官方口径但对 top-K 有截断惩罚）。

跑法：
    python -X utf8 -m md_cg.bench_lme_pathset_ab --limit 120
    python -X utf8 -m md_cg.bench_lme_pathset_ab            # 全量
"""
import argparse
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mdcos import MdCGOS

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(HERE, "data", "external", "longmemeval")
LM_Q = os.path.join(EXT, "lme_s_questions.jsonl")
LM_H = os.path.join(EXT, "lme_s_haystack.jsonl")
ROOT = os.path.join(HERE, "_md_cg_eval_lme_ab")

RECALL_DEFAULT = ("lexical", "bucket", "entity", "graph", "chain", "temporal")
WITH_BM25 = ("bm25", "bucket", "entity", "graph", "chain", "temporal")
BM25_ONLY = ("bm25",)
LEX_ONLY = ("lexical",)

# node_id -> session id（own 口径过滤用；比从 id 反解子串稳）
SESS_OF = {}


def query_of(item):
    return item["question"]


def load_jsonl(path):
    with io.open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def build(rows, rebuild=False):
    cg = MdCGOS(ROOT, autoflush=500)
    have = set(cg.index["nodes"])
    n_new = 0
    t0 = time.perf_counter()
    skipped = 0
    for r in rows:
        if r["id"] in have:
            continue
        if not (r.get("text") or "").strip():
            skipped += 1      # issue #644：空白节点不许入库
            continue
        cg.add(r["id"], r["text"], layer="contextual",
               tags=["lme-session:%s" % (r.get("session") or "")],
               importance=0.5, verification_basis="data",
               lme_session=r.get("session"), lme_date=r.get("date"))
        n_new += 1
    cg.flush()
    print("  建库：新增 %d（跳过空白 %d），库内 %d 节点，%.1fs"
          % (n_new, skipped, len(cg.index["nodes"]), time.perf_counter() - t0))
    return cg


def run(cg, qs, query_of, arm, k=10):
    """一臂一次跑完，raw / own 两种口径**同一次检索**算出来（省一半时间）。

    raw：直接在返回 top-K 上判命中（全局库口径，别题 session 会占名额）；
    own：先把「不属于本题 haystack」的返回剔掉再判（逼近官方逐题检索口径）。
    """
    hits = {"raw": {5: 0, 10: 0}, "own": {5: 0, 10: 0}}
    t0 = time.perf_counter()
    for item in qs:
        res, _meta = cg.search_rrf(query_of(item), k=k, paths=arm,
                                   judge=False, record=False, fusion="max")
        ids = [r[0]["id"] for r in res]
        own_ids = set(item.get("haystack_sessions") or [])
        ids_own = [i for i in ids if SESS_OF.get(i) in own_ids]
        ev = set(item["evidence_turns"])
        for scope, seq in (("raw", ids), ("own", ids_own)):
            for kk in (5, 10):
                if ev & set(seq[:kk]):
                    hits[scope][kk] += 1
    n = max(1, len(qs))
    dt = (time.perf_counter() - t0) / n
    return ({s: {kk: hits[s][kk] / n for kk in (5, 10)} for s in hits}, dt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--k", type=int, default=10)
    args = ap.parse_args()
    if not (os.path.exists(LM_Q) and os.path.exists(LM_H)):
        print("缺少 %s 或 %s —— 先跑 scripts/gen_longmemeval_eval_data.py" % (LM_Q, LM_H))
        return 2
    qs = load_jsonl(LM_Q)
    corpus = load_jsonl(LM_H)
    SESS_OF.update({r["id"]: r.get("session") for r in corpus})
    if args.limit:
        qs = qs[: args.limit]
    print("题 %d ｜语料 user turn %d" % (len(qs), len(corpus)))
    cg = build(corpus)
    arms = [("缺省六路（lexical）", RECALL_DEFAULT),
            ("换 bm25（建议 1）", WITH_BM25),
            ("bm25 单路", BM25_ONLY),
            ("lexical 单路", LEX_ONLY)]
    print()
    print("%-22s%10s%10s%10s%10s%10s" % ("臂", "R@5 raw", "R@10 raw", "R@5 own", "R@10 own", "ms/题"))
    print("-" * 74)
    out = {}
    for name, arm in arms:
        sc, dt1 = run(cg, qs, query_of, arm, k=args.k)
        raw, own = sc["raw"], sc["own"]
        out[name] = (raw, own)
        print("%-22s%9.1f%%%9.1f%%%9.1f%%%9.1f%%%10.1f"
              % (name, 100 * raw[5], 100 * raw[10], 100 * own[5], 100 * own[10], dt1 * 1000))
    print("-" * 74)
    d = out["换 bm25（建议 1）"][1][5] - out["缺省六路（lexical）"][1][5]
    print("  Δ(R@5 own) = %+.1f pp（bm25 六路 − lexical 六路）" % (100 * d))
    return 0


if __name__ == "__main__":
    sys.exit(main())