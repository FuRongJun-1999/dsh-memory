# -*- coding: utf-8 -*-
"""locomo-zh-500 英文侧统一标准真源路复测（2026-09-14）。

背景：统一标准真源语义路（MDCG_SEMANTIC=1，semantic/canonical.py）已在受控
盲测（bench_blind_comp b3_unified 臂）实证「英文原题经 query_atoms 内部归一
（en_normalizer→中文语素→标准原子）直查 fm.semantic 摘要，L2 hit@1=100%」。
本脚本回答开放域问题：真实 locomo 语料 + 500 道英文原题上，统一真源路净效应
多大？en→zh 归一词表覆盖瓶颈多大？

三臂（同题同池，只变 doc 侧正文形态与开关）：

* u0_en_lex  ：doc=英文原文正文（text+[date]），默认词法路——英文 char-bigram
  对英文正文的词法基线（现状跨语答案所在层的对照组）；
* u1_unified ：doc=英文原文正文 + fm.semantic=segment(中文摘要)（AI 写入侧
  归一的规则近似下界），MDCG_SEMANTIC=1，英文原题直查——语义增量 = u1-u0；
* u2_pure_zh ：doc=中文五槽正文（zh）+ fm.semantic 同上，英文原题直查——
  英文 query 对中文正文词法零交集，唯一通路就是归一原子与语义资格层——
  「英文检索路径归一化到统一标准真源」的最强形态。

诚实边界（报告须原样引用）：

* fm.semantic 为规则切分（segment）非 AI 真实归一——下界口径；
* en→zh 归一词表（EN_ZH 手工表）远小于中文原子空间，英文专名/域词保留原文
  → 对中文 doc 零命中——词表覆盖瓶颈按题级 OOV 统计报告；
* 池全为 gold 证据语料（bench6 同源口径）→ 指标是上界而非端到端记忆能力；
* question_en 是英文自然语言问句，中文侧 questions500.question 是关键词串
  → 本测只与自身三臂对照，不与中文口径 94.6/99.2 直接比（题面形态不同）。

跑法：python -m md_cg.bench_unified_en
"""
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (HERE, os.path.join(HERE, "md_cg")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from md_cg import eval_common as ec            # noqa: E402
from md_cg import bench6_common as b6          # noqa: E402  口径/数据源复用
from md_cg.mdcos import MdCGOS                 # noqa: E402
from md_cg.semantic.canonical import semantic_atoms, query_atoms  # noqa: E402

ARM_ROOT = os.path.join(HERE, "_md_cg_eval_unified_en")  # gitignore 已覆盖
K = 10


# 生效条件：传入 root 使 os.path.isdir(root) 为真时先执行 shutil.rmtree(root, ignore_errors=True)、否则跳过，随后遍历 corpus 每项 c，semantic_of 不为 None 且 semantic_of(c) 返回真值时以 semantic=sem 传入，正文按 zh_body 真值取 c.get("zh")、假值取 b6.ingest_text_en(c)，并以 c["id"] 为键 add 后 flush 并 install_read_cache，最终返回 cg；
def build(root, corpus, semantic_of=None, zh_body=False):
    """单库构建：正文形态与 fm.semantic 摘要层是仅有的两个自由度。"""
    if os.path.isdir(root):
        shutil.rmtree(root, ignore_errors=True)
    cg = MdCGOS(root, autoflush=500)
    for c in corpus:
        kw = {}
        if semantic_of is not None:
            sem = semantic_of(c)
            if sem:
                kw["semantic"] = sem
        body = c.get("zh") if zh_body else b6.ingest_text_en(c)
        cg.add(c["id"], body, layer="knowledge",
               eval_src="unified_en", verification_basis="data", **kw)
    cg.flush()
    ec.install_read_cache(cg)
    return cg


# 生效条件：cg 可对 questions 做 evaluate_group 时，按 semantic 设置或清除 MDCG_SEMANTIC，返回词法路 rows 及其按 qtype 汇总的 by_type。
def run_arm(cg, questions, tag, semantic=False):
    if semantic:
        os.environ["MDCG_SEMANTIC"] = "1"
    else:
        os.environ.pop("MDCG_SEMANTIC", None)
    rows = ec.evaluate_group(cg, questions, k=K, paths=("lexical",),
                             judge=False, verbose=False)
    summ = ec.summarize(rows, k=K)
    by_type = {"ALL": summ}
    for qt in sorted({r["qtype"] for r in rows}):
        sub = [r for r in rows if r["qtype"] == qt]
        by_type[qt] = ec.summarize(sub, k=K)
    return rows, by_type


# 生效条件：questions 为真时逐 q 取 q["question"]（缺该键抛 KeyError）经 query_atoms，仅当 atom 含任一满足 "A" <= ch <= "z" 的字符才计入 n_keep，n_tok 为 0 时 keep_ratio 为 0.0、否则 round(n_keep/n_tok,4)，questions 为空时 q_with_keep_ratio 为 0.0、否则 round(n_q_with_keep/len(questions),4)，返回含 n_questions/n_atoms/n_en_keep 的 dict；
def oov_stats(questions):
    """题级 en→zh 归一覆盖统计：英文保留词占比 = 词表覆盖瓶颈的直接量化。"""
    n_tok = n_keep = n_q_with_keep = 0
    for q in questions:
        atoms = query_atoms(q["question"])
        keeps = [a for a in atoms if any("A" <= ch <= "z" for ch in a)]
        n_tok += len(atoms)
        n_keep += len(keeps)
        if keeps:
            n_q_with_keep += 1
    return {"n_questions": len(questions),
            "n_atoms": n_tok,
            "n_en_keep": n_keep,
            "keep_ratio": round(n_keep / n_tok, 4) if n_tok else 0.0,
            "q_with_keep_ratio": round(n_q_with_keep / len(questions), 4)
            if questions else 0.0}


# 生效条件：不适用（无必需形参与模块级常量）
def main():
    t0 = time.time()
    rows500 = list(ec.iter_jsonl(b6.QUESTIONS500))
    corpus = list(ec.iter_jsonl(b6.CORPUS567))
    en_by_qid = {r["qid"]: r for r in ec.iter_jsonl(b6.EN_QUESTIONS)}
    # 全量 500 题（不抽样），中英 qrels 逐字一致断言复用 bench6 口径
    questions = b6.align_queries(rows500, en_by_qid)
    for q in questions:
        q["question"] = q["question_en"]        # 英文原题直查
    print("[unified_en] 题 %d（英文原题全量）/ 语料 %d / k=%d"
          % (len(questions), len(corpus), K))

    ec.unlock_global_cap()
    ec.use_jaccard()

# 生效条件：对 c 先取 (c.get("zh_fields") or {}).get("summary") 再 or "" 并 str().strip()，该值为空时回落为 (c.get("zh") or "") 的 str().strip()，所得 s 非空则返回 " ".join(semantic_atoms(s))、否则返回空串；
    def sem_of(c):
        s = str((c.get("zh_fields") or {}).get("summary") or "").strip()
        if not s:
            s = str(c.get("zh") or "").strip()
        return " ".join(semantic_atoms(s)) if s else ""

    out = {"n_q": len(questions), "n_corpus": len(corpus), "k": K,
           "arms": {}, "oov": oov_stats(questions),
           "semantic_rule": "segment(zh_fields.summary)，OOV 保留——规则近似下界"}

    cg0 = build(os.path.join(ARM_ROOT, "u0"), corpus)               # 英文正文
    cg1 = build(os.path.join(ARM_ROOT, "u1"), corpus, sem_of)       # +semantic
    cg2 = build(os.path.join(ARM_ROOT, "u2"), corpus, sem_of,
                zh_body=True)                                        # 纯中文库
    arms = ((cg0, "u0_en_lex", False),
            (cg1, "u1_unified", True),
            (cg2, "u2_pure_zh", True))
    # CLI：--arms u2,u2c 只跑指定臂（归因探针用）；--out 改结果文件名
    argv = sys.argv[1:]
    only = None
    out_name = "unified_en_baseline.json"
    if "--arms" in argv:
        only = set(argv[argv.index("--arms") + 1].split(","))
        arms = tuple((cg, tag, sem) for cg, tag, sem in arms if tag in only)
    if "--out" in argv:
        out_name = argv[argv.index("--out") + 1]
    if not arms:
        print("[arms] 无匹配臂")
        return
    for cg, tag, sem in arms:
        _rows, by_type = run_arm(cg, questions, tag, semantic=sem)
        out["arms"][tag] = by_type
        mode = ("MDCG_SEMANTIC=1" if sem else "词法默认") + \
               (" + fm.semantic 摘要层" if sem else "")
        print("\n== 臂 %s（%s）==" % (tag, mode))
        for name, s in by_type.items():
            print("  %-18s hit@1=%6.1f%%  hit@%d=%6.1f%%  MRR=%.4f  (n=%d)"
                  % (name, s["hit@1"] * 100, K, s["hit@%d" % K] * 100,
                     s["mrr"], s["n"]))
        if tag == "u2_pure_zh":
            # 归因臂 u2c：中文关键词原题 × 同一纯中文库 × 同一语义路——
            # 钉「语义路机制 + doc 侧摘要」上界。u2c 远高于 u2 → 瓶颈纯在
            # query 侧 en→zh 归一（扩表有效）；u2c 亦低 → 瓶颈在 win6 共现
            # 机制或 doc 侧，扩表无效。
            zh_q = [dict(q, question=q["question_zh"]) for q in questions]
            _rc, by_c = run_arm(cg, zh_q, "u2c", semantic=True)
            out["arms"]["u2c_zh_sem_attribution"] = by_c
            print("== 臂 u2c_zh_sem_attribution（中文题面 × 同库同语义路，归因上界）==")
            for name, s in by_c.items():
                print("  %-18s hit@1=%6.1f%%  hit@%d=%6.1f%%  MRR=%.4f  (n=%d)"
                      % (name, s["hit@1"] * 100, K, s["hit@%d" % K] * 100,
                         s["mrr"], s["n"]))
        cg.close()

    a0, a1, a2 = ((out["arms"].get(t) or {}).get("ALL") for t in
                  ("u0_en_lex", "u1_unified", "u2_pure_zh"))
    if not all((a0, a1, a2)):
        print("[arms] 单臂探针模式，跳过 deltas")
        ec.save_result(out_name, out)
        print("\n[unified_en] 完成（%.1fs），结果已存 %s"
              % (time.time() - t0, out_name))
        return
    out["deltas"] = {
        "u1_minus_u0_hit@1": round(a1["hit@1"] - a0["hit@1"], 4),
        "u1_minus_u0_hit@10": round(a1["hit@%d" % K] - a0["hit@%d" % K], 4),
    }
    out["elapsed_s"] = round(time.time() - t0, 1)
    out["boundaries"] = [
        "池全为 gold 证据语料 → 指标是上界而非端到端记忆能力",
        "fm.semantic=规则切分（segment），非 AI 真实归一 → 下界口径",
        "英文题面为自然问句，中文口径 94.6/99.2 的题面是关键词串——"
        "两口径题面形态不同，不可直接比较",
        "en→zh 归一词表覆盖瓶颈见 out.oov（英文保留词占比）——扩表是明确路径",
        "u2 纯中文库上英文词法零交集 → 该臂成绩全部来自统一真源语义路",
        "u2c 归因臂=中文题面×同库×同语义路 → u2c−u2 差值即 query 侧归一缺口，"
        "u2c 自身即机制+doc 侧上界",
    ]
    ec.save_result(out_name, out)
    print("\n[unified_en] 完成（%.1fs），结果已存 %s" % (out["elapsed_s"], out_name))


if __name__ == "__main__":
    main()