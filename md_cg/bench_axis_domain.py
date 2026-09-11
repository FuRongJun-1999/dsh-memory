# -*- coding: utf-8 -*-
"""域轴（条件约束）单变量消融 —— 验证 routing 条件路由在 locomo 中文层上的净效应。

## 为什么做这个（先例取证）

四轴消融（`bench_zh_mad.ARMS` a0..a4 → `bench_locomo_zh.cmd_build`）有三处把
条件约束路**排除在外**，叠加起来使其从未被开启过：

1. `build_arm` 注释明写「检索路固定 lexical+entity+graph」——`bucket` 不在其中；
2. `build_arm` 写入用 `layer="contextual"`，而 `BUCKETED_LAYERS = ("knowledge",)`
   （mdcg.py:37）→ `bucket` 字段恒为 None，**连分桶都没发生**；
3. Rust 侧 `retrieval::bucket` 是空壳（`main.rs` 硬编码 `has_context=false`），
   Python 侧 `mdcos._path_bucket` 在 `context is None` 时直接 `return []`。

→ 四轴的全部边际变化只能来自 **entity（裸词 tags）** 与 **graph（edges）** 两路。
实测 a0(91.10%) → a1(32.40%) 的塌陷即裸词 tags 把 `_path_entity`
（判据 `t in query or query in t`，二值、score 恒 1.0）从「恒空」激活为「恒满」——
**不是能力未开，是把信息接进了一条无区分度的端口**。

本系统条件约束的**正确输入**是 tags 的 `domain:` 前缀（`routing.route_key`
优先级 1）；写入侧与查询侧共用 `routing.BIG_DOMAINS` 词表，保证两侧同构
（routing.py 模块头「风险2 的前提」）。

## 实验设计（单变量：四臂只差 tags 内容）

正文 / 层（knowledge）/ 无 edges 完全相同：

| 臂 | tags | bucket |
|---|---|---|
| d0_base | `[]` | orphan |
| d1_bare | 裸词（**与 a1_norm 同源**，复现四轴错法） | orphan |
| d2_dom | `[domain:<域>]` | `<域>` |
| d3_shuf | `[domain:<随机域>]`（保持分布） | `<随机域>` |

检索路：`lexical` | `lexical,bucket` | `lexical,entity` | `lexical,bucket,entity`。
查询侧 context 由 `routing` 同词表分类构造（`big_domain_classify`）。

## 裁决标准

* `d2(lexical,bucket) > d0(lexical)` → 条件约束是**净增益**；
* `d3(lexical,bucket) ≈ d0(lexical)` → 增益来自**正确的域**，而非「有桶就行」（因果对照）；
* `d1(lexical,entity) < d0(lexical)` → 裸词 tags 是**净污染**（复现四轴）。

## 诚实条款

* 语料/题库为既有产物（`corpus567.jsonl` / `questions500.jsonl`），本脚本不改一字；
* 域判定是确定性纯规则（routing 词表，零 LLM），同输入必同输出，可第三方重放；
* 域判定**盲于查询集**：写入侧只读 turn 的 `zh_fields`，不读 question/answer；
* 本语料是**日常生活对话**，14 大域为学科词表 → 落域覆盖有限（实测写入侧 31.0%、
  查询侧 30.6%），故预期增益只作用在有域子集上，不做「全量标题」式宣称。
"""
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (HERE, os.path.join(HERE, "md_cg")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from md_cg import bench_zh_mad as bz        # noqa: E402  复用 a1 的 tags 来源（同源）
from md_cg import eval_common as ec         # noqa: E402
from md_cg import mdcg as mg                # noqa: E402
from md_cg import routing                   # noqa: E402

# 数据集路径解析：优先随仓库公开的 data/benchmarks/locomo-zh-500/，回退本地
# data/external/locomo_zh/（.gitignore 覆盖，含中文层分批中间件，不随仓库公开）。
# 公开目录只含 corpus567/questions500 两个成品文件——本脚本只需这两个，故外部
# 拿到仓库即可跑通（此前硬编码 data/external 会让"公开可复现"落空，见数据集
# README「怎么用」节的复现命令）。
_PUBLIC_DIR = os.path.join(HERE, "data", "benchmarks", "locomo-zh-500")
WORK = (_PUBLIC_DIR if os.path.exists(os.path.join(_PUBLIC_DIR, "corpus567.jsonl"))
        else os.path.join(ec.EXT, "locomo_zh"))
CORPUS567 = os.path.join(WORK, "corpus567.jsonl")
QUESTIONS500 = os.path.join(WORK, "questions500.jsonl")

SEED = 7
ARM_PREFIX = "_md_cg_eval_domax_"           # .gitignore 的 /_md_cg_eval_*/ 已覆盖

ARMS = (("d0_base", "base"), ("d1_bare", "bare"),
        ("d2_dom", "dom"), ("d3_shuf", "shuf"))
PATHSETS = (("lexical",), ("lexical", "bucket"),
            ("lexical", "entity"), ("lexical", "bucket", "entity"),
            ("lexical", "fuzzy"), ("lexical", "fuzzy", "bucket"))


# ------------------------------------------------------------------ 写入侧加工

def body_of(c):
    """正文：与 bench_zh_mad.build_arm 的 a0 臂**逐字一致**（无意图行/无承接行）。"""
    f = c["zh_fields"]
    return "\n".join([
        f"身份：{f['identity']}",
        f"时间：{f['time']}",
        f"摘要：{f['summary']}",
        f"词：{','.join(f['terms'])}",
        "条件：" + "|".join(f"{k}:{v}" for k, v in f["condition"].items()),
        "",
        c["text"],
    ])


def write_domain(c):
    """写入侧域判定：只读 turn 自身的 zh_fields（盲于查询集）。"""
    f = c["zh_fields"]
    terms = list(f["terms"]) + [t for t in str(f["summary"]).split() if t]
    return routing.big_domain_classify(terms)


def query_domain(q):
    """查询侧域判定：与写入侧共用同一份 routing 词表（两侧同构）。"""
    return routing.big_domain_classify(list(mg.expand_query_terms(q["question"])))


def arm_tags(c, mode, df, doms):
    if mode == "base":
        return []
    if mode == "bare":
        # 与 a1_norm 同源：同一函数、同一 df 表 → 严格复现四轴的 tags
        return list(bz.normalize_terms(c, df))
    d = doms.get(c["id"])
    return [f"domain:{d}"] if d else []


def build_domain_arm(corpus, name, mode, df, verbose=True):
    """按臂建库。四臂唯一差异是 tags 内容（layer/正文/edges 全同）。"""
    import shutil
    from md_cg.mdcos import MdCGOS
    root = os.path.join(HERE, ARM_PREFIX + name)
    if os.path.isdir(root):
        shutil.rmtree(root, ignore_errors=True)
    cg = MdCGOS(root, autoflush=500)

    doms = {c["id"]: write_domain(c) for c in corpus}
    if mode == "shuf":
        # 因果对照：把「有域」节点的域整体随机重排（保持域分布不变，
        # 只破坏「域↔节点」的对应关系）→ 若增益消失，则增益来自正确的域。
        present = [d for d in doms.values() if d]
        random.Random(SEED).shuffle(present)
        it = iter(present)
        doms = {k: (next(it) if v else None) for k, v in doms.items()}

    for c in corpus:
        cg.add(c["id"], body_of(c), layer="knowledge",
               tags=arm_tags(c, mode, df, doms),
               eval_src=f"domax:{name}", verification_basis="data")
    cg.flush()
    if verbose:
        h = routing.bucket_health(cg.index["buckets"])
        verdict = "OK" if h["ok"] else "；".join(h["problems"])
        print(f"  桶数={h['buckets']} 最大桶占比={h['max_bucket_share']:.1%} "
              f"单例桶率={h['singleton_ratio']:.1%} 期望扫描={h['expected_scan']:.1%}"
              f" → {verdict}")
    return cg, doms


# ------------------------------------------------------------------ 主流程

def main():
    corpus = list(ec.iter_jsonl(CORPUS567))
    questions = list(ec.iter_jsonl(QUESTIONS500))
    print(f"池 {len(corpus)} 条，题 {len(questions)} 道")

    # 评测口径（与既有公开基准口径一致，否则不可比）
    ec.unlock_global_cap()
    ec.use_jaccard()

    df = bz.build_tables(corpus)
    qctx = {}
    for q in questions:
        d = query_domain(q)
        qctx[q["qid"]] = {"tags": [f"domain:{d}"]} if d else None
    n_ctx = sum(1 for v in qctx.values() if v)
    print(f"查询侧落域 {n_ctx}/{len(questions)} = {n_ctx / len(questions):.1%}")

    def context_of(q):
        return qctx.get(q["qid"])

    out = {"n_pool": len(corpus), "n_q": len(questions),
           "q_with_domain": n_ctx, "seed": SEED, "cells": {}}
    table = {}
    t_all = time.time()
    for name, mode in ARMS:
        print(f"\n== 建库 {name}（mode={mode}）==")
        cg, doms = build_domain_arm(corpus, name, mode, df)
        ec.install_read_cache(cg)
        entries = cg._candidates()

        n_write_dom = sum(1 for v in doms.values() if v)
        # 机制探针（白箱）：各路在本题上的非空数 —— 直接看该路是否真的活
        ne = sum(1 for q in questions if qctx.get(q["qid"])
                 and cg._path_bucket(q["question"], entries, qctx[q["qid"]]))
        nf = sum(1 for q in questions
                 if cg._path_fuzzy(q["question"], entries,
                                   qctx.get(q["qid"]))[0])
        print(f"  写入侧落域 {n_write_dom}/{len(corpus)} = "
              f"{n_write_dom / len(corpus):.1%}；bucket 路非空 {ne}/{n_ctx}；"
              f"fuzzy 路非空 {nf}/{len(questions)}")

        for paths in PATHSETS:
            pk = ",".join(paths)
            rows = ec.evaluate_group(cg, questions, k=5, paths=paths,
                                     context_of=context_of, verbose=False)
            s = ec.summarize(rows, k=5)
            s["write_with_domain"] = n_write_dom
            s["bucket_nonempty"] = ne
            s["bucket_ctx_total"] = n_ctx
            out["cells"][f"{name}|{pk}"] = s
            table[f"{name:<8} {pk:<22}"] = s
            print(f"  {pk:<22} hit@1={s['hit@1']:>6.1%} "
                  f"hit@5={s['hit@5']:>6.1%} MRR={s['mrr']:.4f}")

    ec.print_table(f"域轴单变量消融（池 {len(corpus)} / 题 {len(questions)}，"
                   f"jaccard + GLOBAL_CAP 解除）", table, k=5)
    out["elapsed_s"] = round(time.time() - t_all, 1)
    ec.save_result("axis_domain_locomo_zh.json", out)

    # ---- 裁决摘要 ----
    def cell(a, p):
        return out["cells"].get(f"{a}|{p}", {})

    print("\n== 裁决 ==")
    d0 = cell("d0_base", "lexical")
    d1 = cell("d1_bare", "lexical,entity")
    d2 = cell("d2_dom", "lexical,bucket")
    d3 = cell("d3_shuf", "lexical,bucket")
    if d0 and d1:
        print(f"  1) 裸词 tags（entity 路）   ：hit@1 {d0['hit@1']:.1%} → "
              f"{d1['hit@1']:.1%}（Δ {d1['hit@1'] - d0['hit@1']:+.1%}）")
    if d0 and d2:
        print(f"  2) domain: tags（bucket 路）：hit@1 {d0['hit@1']:.1%} → "
              f"{d2['hit@1']:.1%}（Δ {d2['hit@1'] - d0['hit@1']:+.1%}）")
    if d2 and d3:
        print(f"  3) 打乱域对照（d2 vs d3）  ：hit@1 {d2['hit@1']:.1%} vs "
              f"{d3['hit@1']:.1%}（Δ {d3['hit@1'] - d2['hit@1']:+.1%}）")
    f0 = cell("d0_base", "lexical,fuzzy")
    f2 = cell("d2_dom", "lexical,fuzzy")
    if d0 and f0:
        print(f"  4) 同义查找（fuzzy 路）    ：hit@1 {d0['hit@1']:.1%} → "
              f"{f0['hit@1']:.1%}（Δ {f0['hit@1'] - d0['hit@1']:+.1%}）")
    if f0 and f2:
        print(f"  5) domain: 标签激活 fuzzy 大域亲和：{f0['hit@1']:.1%} → "
              f"{f2['hit@1']:.1%}（Δ {f2['hit@1'] - f0['hit@1']:+.1%}）")
    print(f"  总耗时 {out['elapsed_s']}s")


if __name__ == "__main__":
    main()
