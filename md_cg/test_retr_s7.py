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
import time

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


# 生效条件：无条件建一个带 edges 的库（A 词法命中，B/C 无词面交集但沿边可达，D 孤立）并返回 cg。
def _build_edges(root):
    cg = MdCG(root)
    cg.add("A", "工程 结构 应力 梁 截面", "knowledge", importance=0.5,
           condition_space={"observation_position": "工程 结构"})
    cg.add("B", "qxzq 与检索词无交集", "knowledge", importance=0.5,
           condition_space={"observation_position": "工程 结构"})
    cg.add("C", "ppyx 另一段无交集文本", "knowledge", importance=0.5,
           condition_space={"observation_position": "工程 结构"})
    cg.add("D", "孤立节点 无任何边", "knowledge", importance=0.5,
           condition_space={"observation_position": "工程 结构"})
    cg.append_edge("A", {"target": "B", "relation_type": "related"})
    cg.append_edge("B", {"target": "C", "relation_type": "related"})
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
    check("T3 用例：窄化后命中不足而全量有命中（用例有效，非自证）",
          len(r0) > 0 and 0 < g.get("cands", 0) < len(r0),
          "full_hits=%d s7=%s" % (len(r0), g))
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
          str(gn.get("reason") or "").endswith("no_index")
          and gn.get("fallback") == "full_scan", str(gn))

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

    # ---- 11) 组合语义：S7 只是 T2 的加速器，不得缩小 S3 的可达域 ----
    root3 = tempfile.mkdtemp(prefix="retr_s7s3_")
    cg3 = _build_edges(root3)
    postings.build(cg3)
    _setenv(MDCG_RETRIEVAL_PIPELINE="1", MDCG_GATE_S1_DOMAIN="0", MDCG_GATE_S1B_BUCKET="0",
            MDCG_GATE_S2_COND="0", MDCG_GATE_S3_SPREAD="1", MDCG_GATE_S7_POSTINGS=None)
    r3a, m3a = cg3.search("工程 应力", k=5, judge=False, record=False)
    g3a = (m3a.get("gates") or {}).get("s3") or {}
    _setenv(MDCG_GATE_S7_POSTINGS="1")
    r3b, m3b = cg3.search("工程 应力", k=5, judge=False, record=False)
    g3b = (m3b.get("gates") or {}).get("s3") or {}
    check("组合：S3 单独生效时确实扩散（用例有效）",
          g3a.get("expanded") == 2 and m3a.get("tier") == "T2b_spread_activation",
          str(g3a) + " tier=" + str(m3a.get("tier")))
    check("组合：S7+S3 的扩散规模与结果均不退化",
          g3b.get("expanded") == g3a.get("expanded") and _snap(r3b) == _snap(r3a),
          str(g3b) + " vs " + str(g3a) + " / " + str(_snap(r3b)) + " vs " + str(_snap(r3a)))

    # ---- 12) 并列同分：次序必须与全表一致（候选集是过滤，不是重排）----
    root4 = tempfile.mkdtemp(prefix="retr_s7tie_")
    cg4 = MdCG(root4)
    for nid in ("t1", "t2", "t3"):
        cg4.add(nid, "并列 重复 内容", "knowledge", importance=0.5)
    cg4.flush()
    postings.build(cg4)
    _setenv(MDCG_RETRIEVAL_PIPELINE="1", MDCG_GATE_S1_DOMAIN="0", MDCG_GATE_S1B_BUCKET="0",
            MDCG_GATE_S2_COND="0", MDCG_GATE_S7_POSTINGS=None)
    rt0, _mt0 = cg4.search("重复 内容", k=5, judge=False, record=False)
    _setenv(MDCG_GATE_S7_POSTINGS="1")
    rt1, mt1 = cg4.search("重复 内容", k=5, judge=False, record=False)
    gt = (mt1.get("gates") or {}).get("s7") or {}
    check("并列同分：次序与全表一致（保持索引原序，不受集合迭代序影响）",
          len(rt0) == 3 and _snap(rt1) == _snap(rt0),
          str(_snap(rt1)) + " vs " + str(_snap(rt0)) + " " + str(gt))

    # ---- 13) 快照过期：节点被改写后必须回退全量（宁可慢，不可丢召回）----
    root5 = tempfile.mkdtemp(prefix="retr_s7stale_")
    cg5 = _build(root5)
    postings.build(cg5)
    _setenv(MDCG_RETRIEVAL_PIPELINE="1", MDCG_GATE_S7_POSTINGS="1",
            MDCG_GATE_S1_DOMAIN="0", MDCG_GATE_S1B_BUCKET="0", MDCG_GATE_S2_COND="0",
            MDCG_S7_FRESHNESS=None)
    _r5, _m5 = cg5.search("阿尔法", k=10, judge=False, record=False)
    check("快照新鲜：stale_reason 为空",
          postings.stale_reason(root5, cg5.index["nodes"]) == "",
          postings.stale_reason(root5, cg5.index["nodes"]))
    # 改写已有节点（节点数不变 → 只可能是目录 mtime 变化）
    cg5.add("n1", "阿尔法 贝塔 伽马 追加", "knowledge")
    cg5.flush()
    _sr = postings.stale_reason(root5, cg5.index["nodes"])
    check("改写后：指纹判定过期（dir_touched）", _sr == "dir_touched", _sr)
    _setenv(MDCG_GATE_S7_POSTINGS=None)
    rs0, ms0 = cg5.search("追加", k=10, judge=False, record=False)
    _setenv(MDCG_GATE_S7_POSTINGS="1")
    rs1, ms1 = cg5.search("追加", k=10, judge=False, record=False)
    gs5 = (ms1.get("gates") or {}).get("s7") or {}
    check("过期：reason 记 stale_index 并回退全量、结果与全表一致",
          str(gs5.get("reason") or "").startswith("stale_index:")
          and gs5.get("fallback") == "full_scan" and _snap(rs1) == _snap(rs0),
          str(gs5) + " / " + str(_snap(rs1)) + " vs " + str(_snap(rs0)))
    # 新增节点（节点数变化）
    cg5.add("n9", "阿尔法 新增节点", "knowledge")
    cg5.flush()
    check("新增节点：指纹判定过期（node_count_changed）",
          postings.stale_reason(root5, cg5.index["nodes"]) == "node_count_changed",
          postings.stale_reason(root5, cg5.index["nodes"]))
    # 重建后重新新鲜
    postings.build(cg5)
    _r6, m6 = cg5.search("阿尔法", k=10, judge=False, record=False)
    check("重建后恢复新鲜并重新窄化",
          postings.stale_reason(root5, cg5.index["nodes"]) == ""
          and (m6.get("gates") or {}).get("s7", {}).get("cands") is not None,
          str((m6.get("gates") or {}).get("s7")))
    # skip 开关：仅供离线对照，跳过指纹后仍窄化
    _setenv(MDCG_S7_FRESHNESS="skip")
    cg5.add("n9", "阿尔法 新增节点 又改", "knowledge")
    cg5.flush()
    _r7, m7 = cg5.search("阿尔法", k=10, judge=False, record=False)
    g7 = (m7.get("gates") or {}).get("s7") or {}
    check("skip 开关：跳过指纹校验后仍走候选窄化（改动路径可见）",
          g7.get("cands") is not None and g7.get("fallback") is None, str(g7))
    # ---- 13b) 组合语义（S7×MDCG_SEMANTIC）：语义路开启时不窄化 ----
    root8 = tempfile.mkdtemp(prefix="retr_s7sem_")
    cg8 = MdCG(root8)
    cg8.add("s1", "阿尔法 贝塔", "knowledge", semantic="阿尔法", verification_basis="test")
    cg8.add("s2", "qxzq 与查询无词面交集", "knowledge", semantic="阿尔法", verification_basis="test")
    cg8.flush()
    postings.build(cg8)
    _setenv(MDCG_RETRIEVAL_PIPELINE="1", MDCG_GATE_S7_POSTINGS="1",
            MDCG_GATE_S1_DOMAIN="0", MDCG_GATE_S1B_BUCKET="0", MDCG_GATE_S2_COND="0",
            MDCG_S7_FRESHNESS=None, MDCG_SEMANTIC="1")
    _rr0, mm0 = cg8.search("阿尔法", k=10, judge=False, record=False)
    _setenv(MDCG_GATE_S7_POSTINGS=None)
    _rr_off, mm_off = cg8.search("阿尔法", k=10, judge=False, record=False)
    gs8 = (mm0.get("gates") or {}).get("s7") or {}
    check("语义路开：S7 不窄化（reason=semantic_on）且扫描量等于全量",
          gs8.get("reason") == "semantic_on" and gs8.get("fallback") == "full_scan"
          and mm0.get("scanned") == mm_off.get("scanned"),
          str(gs8) + " scanned=%s vs %s" % (mm0.get("scanned"), mm_off.get("scanned")))
    check("语义路开：无词面交集的语义节点仍入池（不漏召回）",
          _snap(_rr0) == _snap(_rr_off)
          and any(x[0]["id"] == "s2" for x in _rr0),
          str(_snap(_rr0)) + " vs " + str(_snap(_rr_off)))
    _setenv(MDCG_SEMANTIC=None)

    # ---- 14) 抽样构建（limit）不得留下看似新鲜的快照 ----
    root6 = tempfile.mkdtemp(prefix="retr_s7part_")
    cg6 = _build(root6)
    st6 = postings.build(cg6, limit=2)
    check("抽样构建：stats 标 partial 且不写 snapshot",
          st6.get("partial") is True and "snapshot" not in st6
          and postings.stale_reason(root6, cg6.index["nodes"]) == "no_snapshot",
          str({k: st6.get(k) for k in ("partial", "snapshot", "nodes")})
          + " / " + postings.stale_reason(root6, cg6.index["nodes"]))
    _setenv(MDCG_RETRIEVAL_PIPELINE="1", MDCG_GATE_S7_POSTINGS="1",
            MDCG_GATE_S1_DOMAIN="0", MDCG_GATE_S1B_BUCKET="0", MDCG_GATE_S2_COND="0",
            MDCG_S7_FRESHNESS=None)
    rp1, mp1 = cg6.search("阿尔法", k=10, judge=False, record=False)
    gp1 = (mp1.get("gates") or {}).get("s7") or {}
    check("抽样构建：检索一律回退全量（不静默漏召回）",
          gp1.get("fallback") == "full_scan"
          and str(gp1.get("reason") or "").endswith("no_snapshot"),
          str(gp1))
    # ---- 15) 根级节点：快照按**文件** mtime 记账（不依赖根目录 mtime）----
    # 背景（独立复核 REJECT 第 3 条）：根目录里也躺着我们自己的 _postings*.json，
    # 若用「根目录 mtime」判定，则快照刚建就被自己的写入改旧。故根级节点路径
    # （path 无目录）改为逐文件记 mtime。
    root7 = tempfile.mkdtemp(prefix="retr_s7root_")
    _dst = os.path.join(root7, "r1.md")
    with open(_dst, "w", encoding="utf-8") as f:
        f.write("---\nid: r1\nlayer: knowledge\n---\n根级节点\n")
    _fake = {"r1": {"path": "r1.md", "layer": "knowledge"}}
    _snap7 = postings.snapshot(root7, _fake)
    _meta7 = {"schema": postings.SCHEMA, "snapshot": _snap7}
    check("根级节点：快照记 file_mtimes、不记根目录（dir_mtimes 无空键）",
          _snap7.get("file_mtimes", {}).get("r1.md") is not None
          and "" not in (_snap7.get("dir_mtimes") or {}),
          str(_snap7)[:200])
    with open(postings.postings_path(root7), "w", encoding="utf-8") as f:
        f.write("{}")
    with open(postings.meta_path(root7), "w", encoding="utf-8") as f:
        f.write("{}")
    check("根级节点：自身派生文件写入后快照仍新鲜（不自判过期）",
          postings.stale_reason(root7, _fake, _meta7) == "",
          postings.stale_reason(root7, _fake, _meta7))
    os.utime(_dst, (time.time() + 5, time.time() + 5))
    check("根级节点：被改写后判过期（root_file_touched）",
          postings.stale_reason(root7, _fake, _meta7) == "root_file_touched",
          postings.stale_reason(root7, _fake, _meta7))
    # ---- 16) CLI 输出：不得打印快照指纹本体（上千个目录键）----
    import io
    import contextlib
    from md_cg import build_postings as _bp
    root9 = tempfile.mkdtemp(prefix="retr_s7cli_")
    _build(root9)
    _buf = io.StringIO()
    with contextlib.redirect_stdout(_buf):
        _rc1 = _bp.main(["--root", root9])
        _rc2 = _bp.main(["--root", root9, "--if-stale"])
        _rc3 = _bp.main(["--root", root9, "--stats"])
    _out = _buf.getvalue()
    check("CLI 三条路径返回 0 且输出无 snapshot 本体（只报 dirs 规模）",
          _rc1 == 0 and _rc2 == 0 and _rc3 == 0
          and "dir_mtimes" not in _out and "file_mtimes" not in _out
          and '"dirs"' in _out,
          _out[:300])
    check("CLI --if-stale 第二次调用报 fresh 不重建",
          '"reason": "fresh"' in _out and '"rebuilt": false' in _out,
          _out[-200:])
    _restore(old)

    print("\ntest_retr_s7: %d 通过 / %d 失败" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())