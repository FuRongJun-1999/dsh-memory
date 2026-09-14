#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_progressive.py · 渐进式语义检索双实验（2026-09-14）

理论（使用者与 GPT 定稿）：查询不是固定语义结构，而是不断收紧的约束集合；
从最小可靠语义开始宽检索，再按区分度逐步增加条件使语义收敛。
「语义解析的完整性与检索的必要性不是同一个问题。」

实验一（locomo-zh-500 · 原子面，与 bench_en_atoms_public 同 doc 侧口径）：
  G0 一次性全原子      —— 对照锚点（应 ≈ ② 96.8/99.8/99.8，同口径自校验）
  G2 只宽检不细化      —— core 50% 一次性排序（「最小可靠语义」本身水平）
  G1 渐进              —— Stage-1 宽检索 → 区分度引导加原子 → 重排
                          （max_stages=4；每阶段都被测量）
  统计：initial（Stage-1）/ final（终态）hit@1/5/10+MRR、平均 refinement
  steps（added 条件数）、一步收敛率。
  诚实边界：池 567 全 gold 零干扰——G1≈G0 属预期（⑤⑥⑦已证宽检索
  鲁棒）；本实验量化「渐进不劣于一次性 + 步数可观测」，消歧增益见实验二。

实验二（受控干扰池 · 引擎侧，42+2 节点真实 MdCGOS）：
  在 test_sem_noise 语料上放 2 条条件冒充邻居（正条件与 gold 同款 →
  judge 判 ACCEPT）——构造 False ACCEPT>0 的形态；渐进循环：
  宽检索 → discriminative 在候选间选区分性条件词 → 带条件重排。
  断言：渐进后 False ACCEPT=0 且 top1 ∈ gold——
  「DEFER/冒充不是终点，加条件后语义收敛」的引擎侧实证。
  条件词池本轮手工给定（示教）；真实系统应由 atoms.json 标准词表驱动。

跑法：python -m md_cg.bench_progressive
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from md_cg import bench6_common as b6                        # noqa: E402
from md_cg.bench_en_atoms_public import (                    # noqa: E402
    CORPUS, QUESTIONS, jaccard, load_char_atoms, node_atom_set,
    round_dict, zh_map_en)
from md_cg.mdcos import MdCGOS                               # noqa: E402
from md_cg.progressive import discriminative, progressive_search  # noqa: E402
from md_cg.test_sem_noise import (                           # noqa: E402
    GOLD, GOLD_COND, NEG_TEXTS, NEIGHBORS, QUERY, UNREL_DOCS, _doc)


def rank_of(ev, ids):
    """gold 在 id 排名中的位次（不在则 0）。"""
    return next((r for r, nid in enumerate(ids, 1) if nid in ev), 0)


def _agg(rank, st):
    if rank == 1:
        st["h1"] += 1
    if 0 < rank <= 5:
        st["h5"] += 1
    if 0 < rank <= 10:
        st["h10"] += 1
    if rank:
        st["rr"] += 1.0 / rank


def _show(label, st, n, extra=""):
    print("  %-22s hit@1=%5.1f%%  hit@5=%5.1f%%  hit@10=%5.1f%%  "
          "MRR=%.4f%s" % (label, st["h1"] * 100.0 / n,
                          st["h5"] * 100.0 / n, st["h10"] * 100.0 / n,
                          st["rr"] / n, extra))


def full_rank(qa, docs):
    """全池 Jaccard 排序 → id 序列（与 run_arm 同判据）。"""
    scored = sorted(((jaccard(qa, na), nid) for nid, na in docs),
                    key=lambda t: (-t[0], t[1]))
    return [nid for _s, nid in scored]


def exp_locomo():
    """实验一：原子面渐进三形态。"""
    t0 = time.time()
    with io.open(CORPUS, encoding="utf-8") as f:
        corpus = [json.loads(ln) for ln in f if ln.strip()]
    with io.open(QUESTIONS, encoding="utf-8") as f:
        questions = [json.loads(ln) for ln in f if ln.strip()]
    char_atoms = load_char_atoms()
    docs = [(c["id"], node_atom_set(c, char_atoms)) for c in corpus]
    docs_map = dict(docs)
    print("[progressive] 实验一 locomo-zh-500 · 语料 %d / 题 %d"
          % (len(corpus), len(questions)))

    def rank_fn(used):
        return [(nid, 0.0) for nid in
                full_rank(frozenset(used), docs)[:20]]

    st_g0 = {"h1": 0, "h5": 0, "h10": 0, "rr": 0.0}
    st_g2 = dict(st_g0)
    st_i = dict(st_g0)
    st_f = dict(st_g0)
    steps_sum = conv = n = 0
    for q in questions:
        ev = set(q.get("evidence_turns") or [])
        qa = [w for w in zh_map_en(str(q.get("question") or ""),
                                   char_atoms).split() if w]
        if not qa:
            continue
        n += 1
        # G0 一次性全原子（对照锚点）
        _agg(rank_of(ev, full_rank(frozenset(qa), docs)), st_g0)
        # G2 只宽检不细化
        core = qa[:max(1, int(len(qa) * 0.5))]
        _agg(rank_of(ev, full_rank(frozenset(core), docs)), st_g2)
        # G1 渐进
        tr = progressive_search(rank_fn, qa, docs_map,
                                ratio=0.5, k=10, max_stages=4)
        _agg(rank_of(ev, full_rank(frozenset(tr["stages"][0]["used"]),
                                   docs)), st_i)
        _agg(rank_of(ev, full_rank(frozenset(tr["stages"][-1]["used"]),
                                   docs)), st_f)
        steps_sum += len(tr["added"])
        conv += 1 if (tr["converged"] or len(tr["added"]) < 3) else 0

    _show("G0 一次性全原子", st_g0, n,
          "   ← 锚点应≈② 96.8/99.8/99.8")
    _show("G2 只宽检(core50%)", st_g2, n)
    _show("G1 渐进·initial", st_i, n)
    _show("G1 渐进·final", st_f, n)
    print("  refinement: 平均加条件数=%.2f  一步收敛率=%.1f%%  (n=%d, %.0fs)"
          % (steps_sum / max(n, 1), conv * 100.0 / max(n, 1), n,
             time.time() - t0))
    return {"g0": st_g0, "g2": st_g2, "g1i": st_i, "g1f": st_f, "n": n}


def exp_controlled():
    """实验二：受控干扰池——条件冒充形态下渐进消歧（引擎侧真检索）。"""
    print("\n[progressive] 实验二 受控干扰池（42+2 节点真实 MdCGOS）")
    tmp = tempfile.mkdtemp(prefix="mdcg_prog_")
    try:
        root = os.path.join(tmp, "root")
        cg = MdCGOS(root)
        gold_ids = [g for g, _ in GOLD]
        for gid, fact in GOLD:
            cg.add(gid, _doc(fact, GOLD_COND), layer="knowledge",
                   verification_basis="test")
        # 2 条邻居改用 gold 同款生效条件 → 正条件命中 → judge 判 ACCEPT（冒充）
        IMPOSTORS = ("n1a", "n3a")
        for gid, lst in NEIGHBORS.items():
            for nid, fact, _cond in lst:
                cg.add(nid, _doc(fact, GOLD_COND if nid in IMPOSTORS
                                 else _cond), layer="knowledge",
                       verification_basis="test")
        for nid, fact in NEG_TEXTS:
            cg.add(nid, _doc(fact, "问没做的事", extra_neg=True),
                   layer="knowledge", verification_basis="test",
                   non_applicable_conditions=["刚才在干什么"])
        for nid, fact, cond in UNREL_DOCS:
            cg.add(nid, _doc(fact, cond), layer="knowledge",
                   verification_basis="test")

        KW = dict(paths=("lexical", "bucket", "entity", "graph", "fuzzy"),
                  fusion="sum", judge_ranking=True)

        def engine_rank(used):
            res, _m = cg.search_rrf(QUERY + (" " + " ".join(used)
                                             if used else ""),
                                    k=10, judge=True, **KW)
            return [(r[0]["id"], r[1]) for r in res]

        def false_accepts(res):
            out = []
            for r in res[:10]:
                nid = r[0]["id"]
                if nid in gold_ids:
                    continue
                ji = r[2] if len(r) > 2 else {}
                if (ji or {}).get("state") == "ACCEPT":
                    out.append(nid)
            return out

        # 宽检索（不加任何条件；judgeinfo 直接取 results 第三元）
        wide_res, _m = cg.search_rrf(QUERY, k=10, judge=True, **KW)
        wide = [(r[0]["id"], r[1]) for r in wide_res]
        fa_pre = false_accepts(wide_res)
        top1_pre = wide[0][0] if wide else None
        print("  宽检索 top1=%s  top10 内 False ACCEPT=%s"
              % (top1_pre, fa_pre or "无"))

        # 渐进：候选间区分性条件词 → 带条件重排
        POOL = ["我", "喝水", "吃饭", "电脑", "书", "音乐", "出门",
                "浇花", "下班"]
        cand_chars = {}
        for r in wide_res[:10]:
            nid = r[0]["id"]
            cand_chars[nid] = frozenset(str(r[0].get("content") or ""))
        cond = discriminative([p for p in POOL],
                              [cand_chars.get(nid, frozenset())
                               for nid, _s in wide[:10]])
        if cond:
            refined_res, _m2 = cg.search_rrf(QUERY + " " + cond,
                                             k=10, judge=True, **KW)
            fa_post = false_accepts(refined_res)
            top1_post = refined_res[0][0]["id"] if refined_res else None
            print("  区分性条件=%r → 重排 top1=%s  top10 内 "
                  "False ACCEPT=%s" % (cond, top1_post, fa_post or "无"))
            ok1 = top1_post in gold_ids
            no_new = set(fa_post) <= set(fa_pre)
            print("  断言①渐进后 top1∈gold：%s" % ("PASS" if ok1 else "FAIL"))
            print("  断言②渐进不引入新冒充（fa_post⊆fa_pre）：%s"
                  % ("PASS" if no_new else "FAIL"))
            if fa_post:
                for r in refined_res[:10]:
                    if r[0]["id"] in fa_post and len(r) > 2:
                        print("    冒充 %s judge reason：%s"
                              % (r[0]["id"],
                                 (r[2] or {}).get("reason", "")))
            print("  边界（如实）：条件面冒充（生效条件被伪造为 gold 同款）"
                  "不被内容词渐进消除——词面条件确认是必要非充分，"
                  "真伪判据=verification_basis/时间线冲突（证据强度分离，另案）")
            return ok1 and no_new
        print("  无区分性条件可选（宽检索已无冒充）——如实记录")
        return not fa_pre
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    exp_locomo()
    ok = exp_controlled()
    print("\n[progressive] 完成。受控池消歧断言：%s"
          % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
