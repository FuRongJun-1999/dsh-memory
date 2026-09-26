#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生产 search T2/T3 重打分守卫（v7 N51 留档复测·修复，缺陷迭代第 14 轮）。

缺陷形态（缺陷报告/v9.md:111 留档，600 节点临时库实测逐位复现）：
  生产 MdCGOS.search 的 try_stage（mdcos.py）无 scored 形参——T2/T3 均为
  「打分截断后又对 picked 重打」：cut_by_relevance(hits, self._score(hits))
  之后 try_stage(hits) 内部再 _score 一遍；T3 再对 picked 重打。实测无交集
  查询 _score 恰 4 调、per-call docs=[0,0,600,500]、共打分 1100 文档——
  500/1100≈45% 打分工作量冗余（GLOBAL_CAP=500）。基类 try_stage 早有
  scored=None 形参（mdcg.py P2-4，批次 31，reach 分支已用）未回移生产覆写。

修复口径：生产 try_stage 照基类 P2-4 模板补 scored=None 形参；T2 hits 腿
（截断打分结果经 doc_key 键表回填）与 T3 picked 腿、reach hits_r 腿一并
透传——同一 _score 纯函数（单次 search 内 docs/q/qb/pool_cfg 均不变），
透传不改变任何分值与输出。

本守卫（调用计数/复杂度断言形态，非时间阈值）：
  T3 段（无交集查询，600 节点）：_score 恰 2 调、per-call [0,600]、共 600
     文档（旧实现 4 调 [0,0,600,500]=1100 → 红）；tier/scanned/结果规模
     不变；
  T2 段（有交集查询）：_score 恰 1 调、共 600 文档（旧实现 2 调
     [600,500]=1100 → 红）；
  纯度段：对计数包装记录的每笔 (docs, scored) 复算 _score 逐位相等
     （透传值 ≡ 现算值——不改结果的直接证据）；
  确定性段：同查询连跑两轮结果 id 序与分值逐位一致。

运行：python -m md_cg.test_retr_score_once
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mdcos import MdCGOS              # noqa: E402

PASS = 0
FAIL = 0
FAILS = []

N = 600
QUERY_MISS = "完全无交集查询词项甲乙丙"       # LIKE 零命中 → T3 全量兜底
QUERY_HIT = "蜂群调度"                      # 有交集 → T2 命中


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")


def build_lib(root):
    cg = MdCGOS(root)
    for i in range(N):
        cg.add("mem_%04d" % i,
               "# 功能名：打分样本 %d\n# 正文：%s 节点 %d" % (i, QUERY_HIT, i),
               layer="knowledge")
    cg.flush()
    return cg


def count_score(cg, fn):
    """包装实例 _score：记录每笔 (docs 数, scored)；另存 docs 引用于旁表。"""
    calls = []            # [docs_n]
    pairs = []            # [(docs, scored)]
    real = MdCGOS._score

    def _spy(self, docs, *a, **kw):
        out = real(self, docs, *a, **kw)
        calls.append(len(docs))
        # 记录时拷贝：_emit 会对 scored 列表原地排序（记录引用会被事后变更）
        pairs.append((list(docs), list(out)))
        return out

    cg._score = _spy.__get__(cg, MdCGOS)
    try:
        return fn(), calls, pairs
    finally:
        del cg._score                     # 还原类属性查找


def main():
    os.environ.pop("MDCG_READ_CACHE", None)
    root = tempfile.mkdtemp(prefix="mdcg_score_once_")
    cg = None
    try:
        cg = build_lib(root)
        cg.search(QUERY_MISS)             # 预热（读缓存装载，非度量面）

        print("== T3 无交集查询：打分恰一次/文档 ==")
        for rep in range(2):
            (res, meta), calls, _ = count_score(
                cg, lambda: cg.search(QUERY_MISS))
            check("T3a rep%d _score 调用数 == 2（旧 4）" % rep,
                  len(calls) == 2, f"calls={calls}")
            check("T3b rep%d per-call docs == [0, 600]（旧 [0,0,600,500]）" % rep,
                  calls == [0, 600], f"calls={calls}")
            check("T3c rep%d 共打分 600 文档（旧 1100，省 45）" % rep,
                  sum(calls) == 600, f"total={sum(calls)}")
            check("T3d rep%d tier/scanned/结果规模不变" % rep,
                  meta.get("tier") == "T3_global_scan"
                  and meta.get("scanned") == N and len(res) == 20,
                  f"tier={meta.get('tier')} scanned={meta.get('scanned')} "
                  f"n={len(res)}")

        print("== T2 有交集查询：打分恰一次/文档 ==")
        for rep in range(2):
            (res, meta), calls, _ = count_score(
                cg, lambda: cg.search(QUERY_HIT))
            check("T2a rep%d _score 调用数 == 1（旧 2）" % rep,
                  len(calls) == 1, f"calls={calls}")
            check("T2b rep%d 共打分 600 文档（旧 1100）" % rep,
                  calls == [600], f"calls={calls}")
            check("T2c rep%d tier 不变（T2_global_like）" % rep,
                  meta.get("tier") == "T2_global_like",
                  f"tier={meta.get('tier')}")

        print("== 纯度：透传 scored ≡ 现算 _score（不改结果的直接证据）==")
        (res, meta), calls, pairs = count_score(
            cg, lambda: cg.search(QUERY_MISS))
        # 与 search 同口径重建 q/qb（mdcos.py:751-773 的打分输入）
        from md_cg.mdcg import bigrams, normalize_en, en_zh_bigrams
        from md_cg.semantic.unify import unify_query
        q_p = unify_query(QUERY_MISS)
        qb_p = bigrams(normalize_en(q_p)) | en_zh_bigrams(q_p)
        pure = True
        for i, (docs, scored) in enumerate(pairs):
            again = MdCGOS._score(cg, docs, q_p, qb_p, None)
            if again != scored:
                pure = False
                print(f"    第{i}笔复算不一致: {len(docs)} docs")
        check("P1a 每笔 (docs→scored) 复算逐位相等（_score 纯函数）", pure)

        print("== 确定性：同查询两轮结果逐位一致 ==")
        r1, m1 = cg.search(QUERY_MISS)
        r2, m2 = cg.search(QUERY_MISS)
        ids1 = [(x[0].get("id"), round(x[1], 12)) for x in r1]
        ids2 = [(x[0].get("id"), round(x[1], 12)) for x in r2]
        check("D1a 两轮结果 id 序与分值逐位一致", ids1 == ids2,
              f"n={len(ids1)}/{len(ids2)}")
        rh1, _ = cg.search(QUERY_HIT)
        rh2, _ = cg.search(QUERY_HIT)
        check("D1b T2 路径两轮结果逐位一致",
              [(x[0].get("id"), round(x[1], 12)) for x in rh1]
              == [(x[0].get("id"), round(x[1], 12)) for x in rh2])

        print("== reach 腿（MDCG_REACH=1）：P2-4 模板形态修复 ==")
        # 相邻缺陷（本轮 stash 取证）：基类 reach 分支旧 _smap 模板对 scored
        # 的 card dict 调 pooling.doc_key（形参须 (entry,fm,content) 三元组）
        # → MDCG_REACH=1 + 命中集非空即 KeyError: 1（HEAD 原生在位）。
        from md_cg.mdcg import MdCG
        os.environ["MDCG_REACH"] = "1"
        try:
            root2 = tempfile.mkdtemp(prefix="mdcg_score_reach_")
            cg2 = MdCGOS(root2)
            for i in range(30):
                cg2.add("rm_%03d" % i,
                        "# 功能名：reach 样本\n# 正文：%s 节点 %d" % (QUERY_HIT, i),
                        layer="knowledge")
            cg2.flush()
            try:
                (res_r, meta_r), calls_r, _ = count_score(
                    cg2, lambda: cg2.search(QUERY_HIT))
                check("R1a 生产 reach 腿不再 KeyError（HEAD 实测崩）且有结果",
                      len(res_r) >= 1, f"n={len(res_r)} tier={meta_r.get('tier')}")
                check("R1b 生产 reach 腿打分 ≤ 2 调（透传无重打）",
                      len(calls_r) <= 2, f"calls={calls_r}")
            finally:
                cg2.close()
                shutil.rmtree(root2, ignore_errors=True)
            root3 = tempfile.mkdtemp(prefix="mdcg_score_reachb_")
            cg3 = MdCG(root3)
            for i in range(30):
                cg3.add("bm_%03d" % i,
                        "# 功能名：reach 样本\n# 正文：%s 节点 %d" % (QUERY_HIT, i),
                        layer="knowledge")
            cg3.flush()
            try:
                res_b, meta_b = cg3.search(QUERY_HIT)
                check("R2a 基类 reach 分支不再 KeyError（stash 取证 HEAD 崩）",
                      len(res_b) >= 1, f"n={len(res_b)} tier={meta_b.get('tier')}")
            finally:
                cg3.close()
                shutil.rmtree(root3, ignore_errors=True)
        finally:
            os.environ.pop("MDCG_REACH", None)
        cg.close()
    finally:
        os.environ.pop("MDCG_READ_CACHE", None)
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 60)
    print(f"结果：PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
