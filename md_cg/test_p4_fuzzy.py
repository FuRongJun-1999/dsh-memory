# -*- coding: utf-8 -*-
"""md_cg · P4 验收：分级隶属度 + LLM 查询侧扩展 + fuzzy RRF 路径

运行：python -m md_cg.test_p4_fuzzy

验证口径（对齐「只新增、不改既有语义」）：
  1. 分级隶属度：membership / IDF 加权大域打分 / 域相似度，且老二值实现不变
  2. LLM 查询侧扩展：llm / whitebox / whitebox_fallback 三态 + 缓存
  3. fuzzy 路径：作为**第 5 路**接入 RRF，默认路径不含它（基线不受影响）
"""
from __future__ import annotations

import shutil
import sys
import tempfile

from . import routing
from .mdcg import (expand_query_terms, expand_query_terms_weighted,
                   expand_query_terms_llm, SYNONYM_GROUPS,
                   SYNONYM_GROUPS_WEIGHTED)
from .mdcos import MdCGOS, _term_degree, _weighted_coverage

PASS = FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


CCG = ("# 功能名：{n}\n# 生效条件：{c}\n# 子功能：{s}\n# 执行：{e}\n"
       "# 验证方式：test\n# 不适用条件：{neg}\n\n{body}\n")


def mk(n, cond, body, neg="其它"):
    return CCG.format(n=n, c=cond, s=body[:20], e=body, neg=neg, body=body)


def main():
    # ---------------- 1. 分级隶属度 ----------------
    print("\n【1】分级隶属度（手写隶属函数）")
    check("完全相同 → 隶属度 1.0", routing.membership("物理", "物理") == 1.0)
    check("term 包含 word → 长度比",
          abs(routing.membership("牛顿第二定律", "牛顿") - 2 / 6) < 1e-9,
          f"{routing.membership('牛顿第二定律', '牛顿')}")
    check("word 包含 term → 长度比",
          abs(routing.membership("物理", "高中物理") - 2 / 4) < 1e-9,
          f"{routing.membership('物理', '高中物理')}")
    check("无包含关系 → 0.0", routing.membership("物理", "化学") == 0.0)

    idf_rare = routing.domain_idf("贝塞尔")     # 只覆盖数学
    idf_common = routing.domain_idf("文明")     # 覆盖历史 + 通用（跨域）
    check("IDF：稀有词区分度 > 跨域通用词", idf_rare > idf_common,
          f"贝塞尔={idf_rare:.3f} 文明={idf_common:.3f}")

    w_bd = routing.big_domain_score_weighted({"贝塞尔": 1.0})
    check("IDF 加权大域打分：贝塞尔 → 数学最高",
          max(w_bd, key=lambda d: w_bd[d]) == "数学",
          f"数学={w_bd['数学']:.3f} 物理={w_bd['物理']:.3f}")
    w_bd2 = routing.big_domain_score_weighted({"牛顿第二定律": 1.0})
    check("加权打分为连续值（部分命中→非整数）",
          0 < w_bd2["物理"] < 2 and w_bd2["物理"] != int(w_bd2["物理"]),
          f"物理={w_bd2['物理']:.3f}")
    check("加权收敛 top-1",
          routing.big_domain_classify_weighted({"贝塞尔": 1.0}) == "数学")

    # 老二值实现不变（基线可比性的前提）
    old_scores = routing.big_domain_score_breakdown(["贝塞尔"])
    check("老二值打分仍为整数计数", all(isinstance(v, int) for v in old_scores.values()),
          f"数学={old_scores['数学']}")
    check("老 big_domain_classify 结果不变",
          routing.big_domain_classify(["贝塞尔"]) == "数学")

    check("域相似度：包含 → 长度比",
          abs(routing.domain_similarity("计算机", "计算机科学") - 3 / 5) < 1e-9,
          f"{routing.domain_similarity('计算机', '计算机科学')}")
    check("域相似度：无关 → 0", routing.domain_similarity("物理", "音乐") == 0.0)

    # ---------------- 2. 加权扩展 + LLM 查询侧扩展 ----------------
    print("\n【2】加权扩展 + LLM 查询侧扩展")
    check("加权同义词组与老表组数一致",
          len(SYNONYM_GROUPS_WEIGHTED) == len(SYNONYM_GROUPS),
          f"{len(SYNONYM_GROUPS_WEIGHTED)} vs {len(SYNONYM_GROUPS)}")
    check("组内权重落在 0.3~1.0",
          all(0.3 <= w <= 1.0 for g in SYNONYM_GROUPS_WEIGHTED for w in g.values()))
    check("每组恰有一个 1.0 组心",
          all(sum(1 for v in g.values() if v == 1.0) == 1
              for g in SYNONYM_GROUPS_WEIGHTED))

    tw = expand_query_terms_weighted("图片识别")
    check("加权扩展：整句权重 1.0", tw.get("图片识别") == 1.0)
    check("加权扩展：同义词带权重（图片→图像 0.9）", tw.get("图像") == 0.9, str(tw))
    check("加权扩展：弱相关低权（发现 0.5）", tw.get("发现") == 0.5, str(tw))
    check("老扩展仍返回 list（未改语义）",
          isinstance(expand_query_terms("图片识别"), list))

    # 分级命中（模糊匹配）
    check("整词命中 → 1.0", _term_degree("红按钮", "红按钮控制角色") == 1.0)
    check("部分命中 → 长度比 × 0.5（贝塞尔不等式 vs 贝塞尔公式）",
          abs(_term_degree("贝塞尔不等式", "贝塞尔公式") - 0.5 * 3 / 6) < 1e-9,
          f"{_term_degree('贝塞尔不等式', '贝塞尔公式')}")
    check("部分命中 < 整词命中（模糊路不压倒词法路）",
          _term_degree("红按钮", "蓝按钮") < 1.0,
          f"共享后缀「按钮」={_term_degree('红按钮', '蓝按钮')}")
    check("完全未命中 → 0", _term_degree("红按钮", "天气晴朗") == 0.0)
    check("加权覆盖率 ∈ [0,1]",
          0 <= _weighted_coverage({"红按钮": 1.0, "发现": 0.5}, "红按钮") <= 1.0)

    # LLM 三态
    fake_ok = lambda p: '[{"term": "视觉识别", "weight": 0.8}, {"term": "图片", "weight": 0.5}]'
    out = expand_query_terms_llm("图片", llm_fn=fake_ok)
    check("LLM 扩展：source=llm", out.get("__source__") == "llm", str(out))
    check("LLM 扩展：合并 LLM 词", out.get("视觉识别") == 0.8)
    check("LLM 扩展：不压低白箱精确命中", out.get("图片") == 1.0, f"图片={out.get('图片')}")
    n_calls = []

    def counting(p):
        n_calls.append(1)
        return '[{"term": "视觉识别", "weight": 0.8}]'

    cache = {}
    expand_query_terms_llm("图片", llm_fn=counting, cache=cache)
    expand_query_terms_llm("图片", llm_fn=counting, cache=cache)
    check("LLM 扩展：显式缓存下同 query 只调一次", len(n_calls) == 1, f"调用={len(n_calls)}")

    def boom(_p):
        raise RuntimeError("llm down")

    out_fb = expand_query_terms_llm("图片", llm_fn=boom)
    check("LLM 失败 → 回退白箱", out_fb.get("__source__") == "whitebox_fallback"
          and out_fb.get("图像") == 0.9, str(out_fb)[:80])
    out_wb = expand_query_terms_llm("图片")
    check("无 llm_fn → 纯白箱", out_wb.get("__source__") == "whitebox")
    out_bad = expand_query_terms_llm("图片", llm_fn=lambda p: "抱歉我不能")
    check("LLM 输出非 JSON → 回退白箱",
          out_bad.get("__source__") == "whitebox_fallback")

    # ---------------- 3. fuzzy RRF 路径 ----------------
    print("\n【3】fuzzy 路径接入 RRF（默认不启用）")
    root = tempfile.mkdtemp(prefix="mdcg_fuzzy_")
    try:
        cg = MdCGOS(root, actor="test")
        cg.add("img_strong", mk("图像节点", "问图片", "画面渲染管线"),
               tags=["图像"], condition_space={"observation_position": "视觉知识点（渲染）"})
        cg.add("img_weak", mk("视像节点", "问图片", "画面渲染管线"),
               tags=["视像"], condition_space={"observation_position": "视觉知识点（渲染）"})
        cg.add("math1", mk("贝塞尔不等式", "问贝塞尔", "贝塞尔不等式的证明与推导"),
               tags=["domain:数学"], condition_space={"observation_position": "数学知识点（贝塞尔）"})
        cg.add("noise", mk("无关节点", "问无关", "完全无关的内容"), tags=["其它"])

        # 默认路径不含 fuzzy → 既有行为不变
        res0, meta0 = cg.search_rrf("图片", k=5)
        check("默认 RRF 路径不含 fuzzy",
              "fuzzy" not in meta0.get("paths", {}), str(list(meta0.get("paths", {}))))
        check("默认 RRF meta 仍有 expand_source 字段（值为 None）",
              "expand_source" in meta0 and meta0["expand_source"] is None)

        # 显式启用 fuzzy
        paths5 = ("lexical", "bucket", "entity", "graph", "fuzzy")
        res, meta = cg.search_rrf("图片", k=5, paths=paths5)
        check("fuzzy 路径被记录进 meta", "fuzzy" in meta.get("paths", {}),
              str(meta.get("paths")))
        check("fuzzy 扩展来源标注（白箱）", meta.get("expand_source") == "whitebox",
              str(meta.get("expand_source")))
        prov = meta.get("provenance", {})
        check("结果 provenance 含 fuzzy 路",
              any(any(p["path"] == "fuzzy" for p in prov.get(nid, [])) for nid in prov),
              str({k: [p['path'] for p in v] for k, v in prov.items()})[:160])

        # 分级：强同义词节点分数 > 弱同义词节点（fuzzy 路内）
        fuzzy_scored, _src = cg._path_fuzzy("图片", cg._candidates())
        smap = {n["id"]: s for n, s in fuzzy_scored}
        check("fuzzy 分级：图像(0.9) > 视像(0.6)",
              smap.get("img_strong", 0) > smap.get("img_weak", 0),
              f"图像={smap.get('img_strong')} 视像={smap.get('img_weak')}")
        check("fuzzy 打分 ∈ (0,1]", all(0 < s <= 1.0 for s in smap.values()),
              str({k: round(v, 3) for k, v in smap.items()}))

        # 大域亲和：数学节点在「贝塞尔」查询下获得 fuzzy 分
        fuzzy_math, _ = cg._path_fuzzy("贝塞尔不等式", cg._candidates())
        mids = {n["id"] for n, _ in fuzzy_math}
        check("fuzzy 大域亲和命中数学节点", "math1" in mids, str(mids))

        # 注入 LLM 查询侧扩展 → meta 标注 llm
        llm_expand = lambda q: expand_query_terms_llm(
            q, llm_fn=lambda p: '[{"term": "画面", "weight": 0.9}]')
        res_l, meta_l = cg.search_rrf("图片", k=5, paths=paths5, query_expand=llm_expand)
        check("注入 LLM 扩展 → meta expand_source=llm",
              meta_l.get("expand_source") == "llm", str(meta_l.get("expand_source")))
        check("LLM 扩展后仍有结果", len(res_l) > 0, f"{len(res_l)} 条")

        # recall 透传 paths
        rec = cg.recall("图片", budget_tokens=400, k=5, paths=paths5)
        check("recall 可透传 paths 启用 fuzzy",
              "fuzzy" in rec["meta"].get("paths", {}), str(rec["meta"].get("paths")))
        check("recall 仍遵守预算", rec["tokens_used"] <= rec["budget"],
              f"used={rec['tokens_used']}/{rec['budget']}")

        # 无 context 时 fuzzy 不应因缺 context 报错
        res_nc, meta_nc = cg.search_rrf("贝塞尔", k=5, paths=("fuzzy",))
        check("fuzzy 单路在无 context 下可运行", isinstance(res_nc, list),
              f"{len(res_nc)} 条")
        cg.close()
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 68)
    print(f"通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：" + ", ".join(FAILS))
    print("=" * 68)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
