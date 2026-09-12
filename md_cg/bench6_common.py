# -*- coding: utf-8 -*-
"""六系统横评（bench6）口径层：唯一真源。

六家（灵枢/mem0/Graphiti/GraphRAG/Letta/纯向量RAG）输入同一份英文原始语料；
灵枢按用户指定"跳过结构化"，复用题库现成中文层叠加英文原文。
本模块只固化口径（抽样/池/双查询词面），指标与排名一律复用 eval_common。

诚实边界（报告须原样引用）：
  * 池全为 gold 证据 → 池内零干扰，指标是**上界**，非端到端记忆能力。
  * question_zh 是中文关键词串而非自然语言问句 → 评检索命中，非 QA。
  * n=100 时题级 CV≈8.3%（VERSION.json 记 n=500 时 CV 3.7%，容量减半 √5 放大）
    → 家间差距小于约 16% 不可下结论。

跑法：
    python -m md_cg.bench6_common [--force]
"""
from __future__ import annotations

import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (HERE, os.path.join(HERE, "md_cg")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from md_cg import eval_common as ec       # noqa: E402

DATA = os.path.join(HERE, "data", "benchmarks", "locomo-zh-500")
CORPUS567 = os.path.join(DATA, "corpus567.jsonl")
QUESTIONS500 = os.path.join(DATA, "questions500.jsonl")
# 英文原问句（上游 LoCoMo 派生副本，不入库）；可用 BENCH6_EN_QUESTIONS 覆盖
EN_QUESTIONS = (os.environ.get("BENCH6_EN_QUESTIONS")
                or os.path.join(HERE, "data", "external", "locomo_zh", "raw_questions.jsonl"))

OUT = os.path.join(ec.RESULTS, "bench6")
POOL_JSONL = os.path.join(OUT, "pool.jsonl")
QUESTIONS_JSONL = os.path.join(OUT, "questions.jsonl")
MANIFEST = os.path.join(OUT, "manifest.json")

N_QUESTIONS = 100
SEED = 7007          # 二级抽样专用；与 VERSION.json 的 500 题 seed=7 区分开
K = 5

BOUNDARIES = [
    "池全为 gold 证据 → 池内零干扰，指标是上界而非端到端记忆能力",
    "question_zh 是中文关键词串而非自然语言问句 → 评检索命中，非 QA",
    "无答案文本，无法评答案质量",
    "n=100 时题级命中率 CV≈8.3%（n=500 时 3.7%，容量减半 √5 放大）→ 家间差距 <16% 不可下结论",
]


def stratified_sample(rows, n=N_QUESTIONS, seed=SEED):
    """按 qtype 比例分层抽样（最大余额法）。

    不用 random.sample(rows, n)：小比例题型（open_domain 4.4%）在 n=100 时
    期望仅 4.4 题，随机抽会在 0~8 间抖动，题型构成随种子漂移，横向对比的
    题型归因就不稳。最大余额法锁定每型题数，使「六家 × 同题型」可比。
    """
    by = {}
    for r in rows:
        by.setdefault(r["qtype"], []).append(r)
    total = len(rows)
    exact = {qt: n * len(g) / total for qt, g in by.items()}
    quota = {qt: int(v) for qt, v in exact.items()}
    rest = n - sum(quota.values())
    order = sorted(exact.items(), key=lambda kv: (-(kv[1] - int(kv[1])), kv[0]))
    for qt, _ in order[:rest]:
        quota[qt] += 1
    out = []
    for qt in sorted(by):
        g, take = by[qt], min(quota[qt], len(by[qt]))
        out.extend(random.Random("%d:%s" % (seed, qt)).sample(g, take))
    out.sort(key=lambda r: r["qid"])
    return out, quota


def build_pool(sample, corpus_by_id):
    """池 = 抽中题的 gold 引用 turn 去重。返回 (pool, dangling)。

    悬空引用是数据集已知现象（VERSION.json 记 scene_3_q_58 →
    scene_3_session_10_turn_19 不在池中）。逐条记录而非静默丢弃，
    使第三方可按同一规则复算池条数。
    """
    pool_ids, dangling = set(), []
    for q in sample:
        miss = [t for t in q["evidence_turns"] if t not in corpus_by_id]
        if miss:
            dangling.append({"qid": q["qid"], "missing": miss})
        pool_ids.update(t for t in q["evidence_turns"] if t in corpus_by_id)
    return [corpus_by_id[i] for i in sorted(pool_ids)], dangling


def ingest_text_en(c):
    """六家共用的英文写入文本：原始陈述 + 会话时间。

    与 ec.lc_turn_text 同构（text + [时间]，使时间类问题的词法路可召回日期词），
    只是字段名换成 date。刻意**不**套用 ec.lc_turn_text：后者读 r["title"]，
    而 locomo-zh-500 语料行用的是 r["date"]（"01:14 PM on Thursday 25 May, 2023"），
    直接套用会静默丢掉全部时间信息。
    """
    text = str(c.get("text") or "").strip()
    date = str(c.get("date") or "").strip()
    return "%s [%s]" % (text, date) if date else text


def turn_rec(c):
    """池行 → 落盘行（六家共用的英文侧视图）。"""
    return {"id": c["id"], "speaker": c.get("speaker") or "",
            "date": c.get("date") or "", "text": c.get("text") or "",
            "ingest": ingest_text_en(c)}


def align_queries(sample, en_by_qid):
    """中英双查询词面按 qid join，断言 evidence_turns 逐字一致。

    断言不是形式主义：两套查询若 qrels 不一致，「中英对照」就退化成
    「两套题的对照」，任何差异都无法归因到语言。缺英问句直接报错不跳过。
    """
    out = []
    for q in sample:
        en = en_by_qid.get(q["qid"])
        if en is None:
            raise KeyError("英文侧缺 qid=%s（中英题集不同源，评测作废）" % q["qid"])
        if list(en["evidence_turns"]) != list(q["evidence_turns"]):
            raise AssertionError("qid=%s 中英 qrels 不一致" % q["qid"])
        out.append({"qid": q["qid"], "qtype": q["qtype"],
                    "question_zh": q["question"], "question_en": en["question"],
                    "evidence_turns": list(q["evidence_turns"])})
    return out


def rank_of(ids, evidence):
    """首个证据 id 的排名（1-based；未命中 0）。

    复用 ec.first_evidence_rank：把 id 列表适配成其结果四元组形状
    （r[0]["id"]），而非重写判据——六家排名与公开基准逐字同源。
    """
    res = [({"id": x}, 0.0) for x in ids]
    return ec.first_evidence_rank(res, set(evidence))


def rows_from_hits(questions, hits_by_qid, k=K):
    """把任一家的 id 列表统一转成 ec.summarize 的明细行。

    hits_by_qid: {qid: [id, ...]}（按相关性降序；不足 k 条亦合法）。
    top1_score 仅用于占位——竞品分数与 cg 分数不同量纲、不可比，
    故本次不引用 summarize 的 score_p10/p50（拒答线），只取命中类指标。
    """
    rows = []
    for q in questions:
        ids = list(hits_by_qid.get(q["qid"]) or [])[:k]
        rows.append({"qid": q["qid"], "qtype": q["qtype"],
                     "rank": rank_of(ids, q["evidence_turns"]),
                     "top1_score": 1.0 if ids else 0.0, "n_res": len(ids)})
    return rows


def prepare(force=False, verbose=True):
    """固化口径层产物（幂等）。返回 manifest。"""
    if not force and os.path.exists(MANIFEST) and os.path.exists(QUESTIONS_JSONL):
        with open(MANIFEST, encoding="utf-8") as f:
            man = json.load(f)
        if verbose:
            print("[bench6] 复用已固化口径：%s（题 %d / 池 %d）"
                  % (OUT, man["queries"]["n"], man["pool"]["n"]))
        return man

    os.makedirs(OUT, exist_ok=True)
    rows = list(ec.iter_jsonl(QUESTIONS500))
    corpus = list(ec.iter_jsonl(CORPUS567))
    corpus_by_id = {c["id"]: c for c in corpus}
    en_by_qid = {r["qid"]: r for r in ec.iter_jsonl(EN_QUESTIONS)}

    sample, quota = stratified_sample(rows)
    pool, dangling = build_pool(sample, corpus_by_id)
    questions = align_queries(sample, en_by_qid)

    with open(POOL_JSONL, "w", encoding="utf-8") as f:
        for c in pool:
            f.write(json.dumps(turn_rec(c), ensure_ascii=False) + "\n")
    with open(QUESTIONS_JSONL, "w", encoding="utf-8") as f:
        for q in questions:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    actual = {}
    for q in questions:
        actual[q["qtype"]] = actual.get(q["qtype"], 0) + 1
    man = {
        "name": "bench6", "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "arms": ["lingshu", "mem0", "graphiti", "graphrag", "letta", "vector_rag"],
        "source": {"questions": QUESTIONS500, "corpus": CORPUS567, "en": EN_QUESTIONS},
        "sampling": {"method": "stratified_proportional_by_qtype_max_remainder",
                     "seed": SEED, "n_target": N_QUESTIONS, "k": K,
                     "quota": quota, "actual": dict(sorted(actual.items()))},
        "pool": {"n": len(pool), "dangling": dangling},
        "queries": {"n": len(questions), "langs": ["zh", "en"]},
        "boundaries": BOUNDARIES,
    }
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=2)

    if verbose:
        print("[bench6] 口径已固化：%s" % OUT)
        print("  题型配额 %s → 实际 %s" % (quota, man["sampling"]["actual"]))
        print("  池条数 %d；悬空引用 %d 条 %s" % (len(pool), len(dangling), dangling))
        print("  中英双查询 %d 题（qrels 已断言逐字一致）" % len(questions))
    return man


def load():
    """读回已固化的口径层产物。六家适配器只经此取题与池。"""
    man = json.load(open(MANIFEST, encoding="utf-8"))
    return {"questions": list(ec.iter_jsonl(QUESTIONS_JSONL)),
            "pool": list(ec.iter_jsonl(POOL_JSONL)), "manifest": man}


if __name__ == "__main__":
    prepare(force="--force" in sys.argv)
