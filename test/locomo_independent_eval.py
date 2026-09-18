#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LoCoMo 第三方独立评测（验证灵枢能力）  v2

第三方性边界（严格遵守）：
  · 不 import / 不调用灵枢任何 bench_* 评测脚本；
  · 数据装载、查询循环、命中判定(hit@k)、MRR、基线、分题型统计 —— 全部本文件独立实现；
  · 被测对象仅限灵枢自身组件：
        md_cg.mdcg.MdCG            （检索引擎）
        md_cg.semantic.en_normalizer（标准归一化器）
        md_cg.lexicon 字级原子库     （标准词表真源）
  · 本人不实现任何"替被测系统干活"的匹配算法（不自建 Jaccard 检索器），
    否则测出的数字无法归因于灵枢。

arm 说明（doc 侧 / query 侧）：
  A_zh5      doc=中文五槽层 zh                 query=中文关键词   ← 灵枢中文写入加工面
  B_en_raw   doc=LoCoMo 英文原文 text          query=中文关键词   ← 零归一对照（下界）
  C_en_norm  doc=英文原文经灵枢标准归一化       query=中文关键词   ← 【用户点名要测的】标准归一化
  D_bi       doc=zh ∪ 英文归一词               query=中文关键词   ← 灵枢主路线 doc 侧口径（MdCG 引擎跑）
  Z_zh5_en   doc=zh, 但 query=英文原问题        —— 数据集未提供英文问句，跳过
  F_sem      doc=英文原文 + semantic=归一原子（MDCG_SEMANTIC=1）  ← 写入侧归一者正统落地形态
  R_random   随机排序下界
"""
import json, os, random, shutil, sys, tempfile, time
from collections import defaultdict

REPO = "/root/lingshu-test/repo"
DATA = os.path.join(REPO, "data/benchmarks/locomo-zh-500")
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "md_cg/semantic"))

# F_sem 需要 MDCG_SEMANTIC=1，必须在 import mdcg 之前设定
SEM = "--semantic" in sys.argv
if SEM:
    os.environ["MDCG_SEMANTIC"] = "1"

from md_cg.mdcg import MdCG
import en_normalizer

ARMS_MAIN = [
    ("A_zh5",     lambda r: r.get("zh") or ""),
    ("B_en_raw",  lambda r: r.get("text") or ""),
    ("C_en_norm", lambda r: norm_atoms(r.get("text") or "")),
    ("D_bi",      lambda r: ((r.get("zh") or "") + " " + norm_atoms(r.get("text") or ""))),
]


# 生效条件：传入的 text 先经 en_normalizer.normalize_en_query(text) 归一（返回词条列表即 " ".join(terms) 返回），该调用及其解包一旦抛任何 Exception 则原样返回 text。
def norm_atoms(text):
    """灵枢标准归一化：英文 → 中文语义原子序列（en_normalizer 正身）。"""
    try:
        terms, _ = en_normalizer.normalize_en_query(text)
        return " ".join(terms)
    except Exception:
        return text


# 生效条件：以 os.path.join(DATA,"corpus567.jsonl") 与 os.path.join(DATA,"questions500.jsonl") 逐行读取、仅对 line.strip() 为真的行做 json.loads 分别追加，返回 (corpus, qs) 两列表（无入参，故始终执行该双文件读取）。
def load():
    corpus, qs = [], []
    with open(os.path.join(DATA, "corpus567.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                corpus.append(json.loads(line))
    with open(os.path.join(DATA, "questions500.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                qs.append(json.loads(line))
    return corpus, qs


# 生效条件：build(rows,field_fn,root,semantic=False) 先按 root 是否存在决定是否 shutil.rmtree，再逐行 content=field_fn(r) or ""（假值回落空串，strip 后为空则改记“（空）”）、node_id=r["id"] 调 cg.add；semantic 为真时额外传 semantic=norm_atoms(r.get("text") or "")，首次 cg.add 抛 TypeError 则弹出 semantic 重试（重试异常不再捕获），其它 Exception 被静默跳过，最后返回 cg。
def build(rows, field_fn, root, semantic=False):
    if os.path.exists(root):
        shutil.rmtree(root)
    cg = MdCG(root)
    for r in rows:
        content = field_fn(r) or ""
        if not content.strip():
            content = "（空）"
        kw = dict(node_id=r["id"], content=content, layer="knowledge",
                  verification_basis="data", on_conflict="record")
        if semantic:
            kw["semantic"] = norm_atoms(r.get("text") or "")
        try:
            cg.add(**kw)
        except TypeError:
            kw.pop("semantic", None)
            cg.add(**kw)
        except Exception:
            pass
    return cg


# 生效条件：仅当 nd 是 dict 且按 ("id","node_id","nid","name") 顺序 nd.get(k) 取到的首个值是 str 时返回该字符串，nd 非 dict 或这些键取值均非 str 时返回 None。
def node_id_of(nd):
    if isinstance(nd, dict):
        for k in ("id", "node_id", "nid", "name"):
            v = nd.get(k)
            if isinstance(v, str):
                return v
    return None


# 生效条件：evaluate(cg,qs,k=20) 只统计 gold=set(q.get("evidence_turns") or []) 非空的题，逐题以 cg.search(q["question"], k=k) 取结果（该调用抛任何异常即按 results=[] 计），用 node_id_of 抽取 id 后在结果下标上定 rank，按 rank 累计 hit@1/hit@5/hit@10 与 MRR、未命中 id 记入 miss_ranks，最终用题数 n 作分母输出 hit1/hit5/hit10/mrr（n 为 0 时该除法会除零）及按 qtype 分组明细，返回 out。
def evaluate(cg, qs, k=20):
    """独立判定：rank / hit@k / MRR 全部自己算，不使用灵枢任何评测函数。"""
    n = 0
    h1 = h5 = h10 = 0
    mrr = 0.0
    per_qtype = defaultdict(lambda: dict(n=0, h1=0, h5=0, h10=0, mrr=0.0))
    miss_ranks = []
    nres = []
    for q in qs:
        gold = set(q.get("evidence_turns") or [])
        if not gold:
            continue
        try:
            results, _meta = cg.search(q["question"], k=k)
        except Exception:
            results = []
        nres.append(len(results))
        ids = []
        for item in results:
            nd = item[0] if isinstance(item, (list, tuple)) else item
            i = node_id_of(nd)
            if i:
                ids.append(i)
        rank = 0
        for i, i_d in enumerate(ids):
            if i_d in gold:
                rank = i + 1
                break
        qt = q.get("qtype") or "?"
        d = per_qtype[qt]
        n += 1
        d["n"] += 1
        if rank == 1:
            h1 += 1; d["h1"] += 1
        if 0 < rank <= 5:
            h5 += 1; d["h5"] += 1
        if 0 < rank <= 10:
            h10 += 1; d["h10"] += 1
        if rank:
            mrr += 1.0 / rank
            d["mrr"] += 1.0 / rank
        else:
            miss_ranks.append(q["qid"])
    out = dict(n=n, hit1=h1 / n, hit5=h5 / n, hit10=h10 / n, mrr=mrr / n,
               miss=miss_ranks, avg_nres=sum(nres) / max(len(nres), 1))
    out["qtype"] = {k2: dict(n=v["n"], hit1=v["h1"] / v["n"], hit10=v["h10"] / v["n"],
                             mrr=v["mrr"] / v["n"]) for k2, v in per_qtype.items()}
    return out


# 生效条件：main() 以 sys.argv[1:] 中首个非 "--" 开头参数经 int 作 only（无此类参数则 30），用 load() 得 corpus/qs_all 并取 qs=qs_all[:only]，arms 由模块常量 SEM 为真取 [("F_sem",...)）否则取 ARMS_MAIN，每个 arm 各自 tempfile.mkdtemp 后 build(corpus, fn, root, semantic=SEM)、evaluate(cg, qs)、打印并写 /tmp/locomo_res_{name}.json、再 rmtree（SEM 或 only>=100 时另打印各 qtype 明细），末尾以 random.seed(7) 在打乱后的 allids[:20] 上算随机下界；该函数无返回。
def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    only = int(args[0]) if args else 30
    corpus, qs_all = load()
    qs = qs_all[:only]
    print(f"语料 {len(corpus)} 条 · 题目 {len(qs_all)} 题 · 本次 {len(qs)} 题"
          f" · MDCG_SEMANTIC={os.environ.get('MDCG_SEMANTIC','0')}\n")

    arms = [("F_sem", lambda r: r.get("text") or "")] if SEM else ARMS_MAIN

    print(f"{'arm':10} {'hit@1':>8} {'hit@5':>8} {'hit@10':>8} {'MRR':>8} {'均返回':>7} {'耗时':>7}")
    print("-" * 68)
    allres = {}
    for name, fn in arms:
        root = tempfile.mkdtemp(prefix=f"mdcg_{name}_")
        t0 = time.time()
        cg = build(corpus, fn, root, semantic=SEM)
        m = evaluate(cg, qs)
        dt = time.time() - t0
        allres[name] = m
        print(f"{name:10} {m['hit1']*100:7.1f}% {m['hit5']*100:7.1f}% "
              f"{m['hit10']*100:7.1f}% {m['mrr']:8.4f} {m['avg_nres']:7.1f} {dt:6.1f}s")
        if SEM or only >= 100:
            for qt, d in sorted(m["qtype"].items()):
                print(f"    ├ {qt:20} n={d['n']:3d}  hit@1 {d['hit1']*100:5.1f}%  "
                      f"hit@10 {d['hit10']*100:5.1f}%  MRR {d['mrr']:.4f}")
        with open(f"/tmp/locomo_res_{name}.json", "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=1)
        shutil.rmtree(root, ignore_errors=True)

    # ---- 随机下界（独立实现）----
    random.seed(7)
    allids = [r["id"] for r in corpus]
    h1 = h5 = h10 = 0; mrr = 0.0
    for q in qs:
        gold = set(q.get("evidence_turns") or [])
        if not gold:
            continue
        order = allids[:]
        random.shuffle(order)
        rank = 0
        for i, i_d in enumerate(order[:20]):
            if i_d in gold:
                rank = i + 1
                break
        if rank == 1: h1 += 1
        if 0 < rank <= 5: h5 += 1
        if 0 < rank <= 10: h10 += 1
        if rank: mrr += 1.0 / rank
    n = len(qs)
    print(f"{'R_random':10} {h1/n*100:7.1f}% {h5/n*100:7.1f}% {h10/n*100:7.1f}% {mrr/n:8.4f}")
    print()


if __name__ == "__main__":
    main()
