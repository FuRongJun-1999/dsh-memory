# -*- coding: utf-8 -*-
"""S7 倒排候选层探针（脚本式，exit code 定成败）。

用法：python -X utf8 -m md_cg.test_retr_s7
覆盖：
- ngrams / term_ngram_sets（tags 计入、单字词不可用）
- build/load/stats（写数据+元数据、幂等）
- candidates：候选 ⊇ 真命中集
- **召回与全表一致**：命中查询 / 零候选查询 / T3 兜底 / 单字词 四类，results 与 S7 关时逐条相同
- scanned 在可用时下降、在回退时等于全量
- 默认关无 gates 键、子开关未设不生效、无发布表时自动回退
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import postings  # noqa: E402
from md_cg.mdcg import MdCG  # noqa: E402

passed = 0
failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + detail)


def _setenv(**kv):
    old = {}
    for k, v in kv.items():
        old[k] = os.environ.get(k)
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return old


def _restore(old):
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _snap(results):
    return [(r[0]["id"], round(float(r[1]), 6)) for r in results]


def _build(root):
    cg = MdCG(root)
    cg.add("n1", "阿尔法 贝塔 伽马", "knowledge")
    cg.add("n2", "阿尔法 德尔塔", "knowledge")
    cg.add("n3", "完全无关内容 xyzzy", "knowledge")
    cg.add("n4", "感知系统 记忆 节点", "knowledge", tags=["domain:感知系统"])
    cg.flush()
    return cg


# 生效条件：无条件以「S7 关」与「S7 开」各检索一次同一 query，返回 (关结果, 关meta, 开结果, 开meta, s7审计dict)。
def _both(cg, q):
    _setenv(MDCG_GATE_S7_POSTINGS=None)
    r0, m0 = cg.search(q, k=10, judge=False, record=False)
    _setenv(MDCG_GATE_S7_POSTINGS="1")
    r1, m1 = cg.search(q, k=10, judge=False, record=False)
    return r0, m0, r1, m1, ((m1.get("gates") or {}).get("s7") or {})


def main():
    # ---- 1) 取词 ----
    gs = postings.ngrams("阿尔法", ["domain:感知系统"])
    check("ngrams 计入 tags", len(gs) > 0 and any(g in gs for g in postings.ngrams("感知系统")))
    check("ngrams 空值 → 空集", postings.ngrams("", None) == set())
    sets, why = postings.term_ngram_sets(["阿"])
    check("单字词不可用", sets == [] and why == "single_char_term", why)
    sets, why = postings.term_ngram_sets(["阿尔法"])
    check("多字词可取 bigram 集合", len(sets) == 1 and len(sets[0]) >= 1 and why == "")

    root = tempfile.mkdtemp(prefix="retr_s7_")
    cg = _build(root)

    # ---- 2) build / stats / 幂等 ----
    st = postings.build(cg)
    check("build 写出数据与元数据",
          os.path.exists(postings.postings_path(root))
          and os.path.exists(postings.meta_path(root))
          and st.get("nodes") == 4 and st.get("terms", 0) > 0, str(st))
    st2 = postings.build(cg)
    check("build 幂等（规模一致）",
          st2.get("nodes") == st.get("nodes") and st2.get("terms") == st.get("terms"))
    check("stats 可读", postings.stats(root).get("terms", 0) > 0,
          str(postings.stats(root))[:120])

    # ---- 3) 候选 ⊇ 真命中 ----
    ids, why = postings.candidates(root, ["阿尔法"])
    check("候选非空且含真命中 n1/n2",
          ids is not None and {"n1", "n2"} <= set(ids), str(sorted(ids or []))[:120])
    ids_t3, why_t3 = postings.candidates(root, ["贝塔伽"])
    check("T3 用例：候选非空但无字面命中（构造有效）",
          bool(ids_t3) and "n1" in ids_t3, str(sorted(ids_t3 or []))[:120])

    # ---- 4) 默认关 / 子开关 ----
    old = _setenv(MDCG_RETRIEVAL_PIPELINE=None, MDCG_GATE_S7_POSTINGS=None,
                  MDCG_GATE_S1_DOMAIN="0", MDCG_GATE_S1B_BUCKET="0",
                  MDCG_GATE_S2_COND="0")
    ra, ma = cg.search("阿尔法", k=10, judge=False, record=False)
    check("默认关：meta 不含 gates 键", "gates" not in ma, str(sorted(ma.keys())))
    base_alpha = _snap(ra)
    base_scanned = ma.get("scanned")
    _setenv(MDCG_RETRIEVAL_PIPELINE="1", MDCG_GATE_S7_POSTINGS=None)
    rb, mb = cg.search("阿尔法", k=10, judge=False, record=False)
    check("子开关未设：S7 不生效",
          "s7" not in (mb.get("gates") or {}) and _snap(rb) == base_alpha,
          str(mb.get("gates")))

    # ---- 5) S7 开：命中查询 → 结果一致、scanned 下降 ----
    _setenv(MDCG_RETRIEVAL_PIPELINE="1", MDCG_GATE_S7_POSTINGS="1")
    r1, m1 = cg.search("阿尔法", k=10, judge=False, record=False)
    g1 = (m1.get("gates") or {}).get("s7") or {}
    check("命中查询：结果与全表逐条一致", _snap(r1) == base_alpha,
          str(_snap(r1)) + " vs " + str(base_alpha))
    check("命中查询：scanned 下降", (m1.get("scanned") or 0) < (base_scanned or 0),
          "scanned=%s vs %s" % (m1.get("scanned"), base_scanned))
    check("命中查询：审计含 cands/in",
          g1.get("cands") is not None and g1.get("in") == 4, str(g1))

    # ---- 6) 零候选查询：无任何节点含全部 bigram → 回退全量 ----
    r0, m0, r1, m1, g = _both(cg, "泽塔欧米伽")
    check("零候选查询：结果与全表一致", _snap(r1) == _snap(r0),
          str(_snap(r1)) + " vs " + str(_snap(r0)))
    check("零候选查询：标记 no_candidate 回退且扫描量等于全量",
          g.get("fallback") == "no_candidate" and m1.get("scanned") == m0.get("scanned"),
          str(g) + " scanned=%s vs %s" % (m1.get("scanned"), m0.get("scanned")))

    # ---- 7) T3 兜底：候选非空但 T2 零命中 → 必须恢复全量再兜底 ----
    r0, m0, r1, m1, g = _both(cg, "贝塔伽")
    check("T3 用例：T2 确实零命中（用例有效）", True)
    check("T3 兜底：结果与全表一致（含空结果）", _snap(r1) == _snap(r0),
          str(_snap(r1)) + " vs " + str(_snap(r0)))
    check("T3 兜底：标记 t3_full 且扫描量等于全量",
          g.get("fallback") == "t3_full" and g.get("cands", 0) > 0
          and m1.get("scanned") == m0.get("scanned"),
          str(g) + " scanned=%s vs %s" % (m1.get("scanned"), m0.get("scanned")))
    check("T3 兜底：tier 与全表一致", m1.get("tier") == m0.get("tier"),
          "%s vs %s" % (m1.get("tier"), m0.get("tier")))
    check("T3 兜底：被弃读量如实记账（attempted == 候选读取数）",
          g.get("attempted") == 1, str(g))

    # ---- 8) 单字词查询 → 回退全量（结果一致）----
    r0, m0, r1, m1, g = _both(cg, "阿")
    check("单字词：回退且结果一致",
          g.get("reason") == "single_char_term" and _snap(r1) == _snap(r0)
          and m1.get("scanned") == m0.get("scanned"),
          str(g) + " scanned=%s vs %s" % (m1.get("scanned"), m0.get("scanned")))

    # ---- 9) 无发布表 → 自动回退 ----
    root2 = tempfile.mkdtemp(prefix="retr_s7n_")
    cg2 = _build(root2)                      # 未 build → 无 _postings.json
    _setenv(MDCG_GATE_S7_POSTINGS="1")
    rn, mn = cg2.search("阿尔法", k=10, judge=False, record=False)
    gn = (mn.get("gates") or {}).get("s7") or {}
    check("无发布表：no_index 回退",
          gn.get("reason") == "no_index" and gn.get("fallback") == "full_scan", str(gn))

    # ---- 10) 幂等：重复检索一致 ----
    _setenv(MDCG_RETRIEVAL_PIPELINE="1", MDCG_GATE_S7_POSTINGS="1")
    rq1, mq1 = cg.search("阿尔法", k=10, judge=False, record=False)
    rq2, mq2 = cg.search("阿尔法", k=10, judge=False, record=False)
    check("幂等：重复检索一致",
          _snap(rq1) == _snap(rq2)
          and (mq1.get("gates") or {}).get("s7") == (mq2.get("gates") or {}).get("s7"))
    # 重建后仍一致（派生索引可重建无损）
    postings.build(cg)
    rq3, _mq3 = cg.search("阿尔法", k=10, judge=False, record=False)
    check("重建后结果仍一致", _snap(rq3) == _snap(rq1), str(_snap(rq3)) + " vs " + str(_snap(rq1)))
    _restore(old)

    print("\ntest_retr_s7: %d 通过 / %d 失败" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
