# -*- coding: utf-8 -*-
"""S5 负记忆抑制探针（脚本式，exit code 定成败）。

用法：python -X utf8 -m md_cg.test_retr_s5
覆盖：
- 默认关：无 gates 键；关→开→关 结果一致
- 子开关未设（总开关开）→ S5 不生效
- 重叠抑制：与 rejected 节点词面高度重叠的正候选 → w × (1-λ)
- 相邻抑制：与 rejected 节点有边相连（文本不重叠）的正候选同样被抑制
- 无关候选不被抑制；λ 可配（0=不抑制，1=压到 0 且不低于 0）
- 阈值真的在过滤：部分重叠候选在 thr=0.6 下不抑制、thr=0.4 下被抑制
- 负记忆条目在 S5 开时不再与正候选同权（1.0 → 1-λ）
- 无负记忆命中时不落 s5 审计；幂等（重复检索 / 索引重建）
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mdcg import MdCG  # noqa: E402

passed = 0
failed = 0
TEXT = "阿尔法 贝塔 伽马 德尔塔"
# neg 文本必须与 pos_overlap 高度重叠（jaccard ≥ 0.5），否则重叠支路测不出来
NEGTEXT = "阿尔法 贝塔 伽马 德尔塔 否决样本"
QUERY = "阿尔法 泽塔"


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


def _scores(results):
    return {r[0]["id"]: round(float(r[1]), 6) for r in results}


def _build(root):
    cg = MdCG(root)
    # 三个正候选都含查询词（都会成为 T2 命中），差别只在「与负记忆的关系」：
    #   pos_overlap：词面高度重叠（重叠支路）
    #   pos_edge   ：文本不重叠但有边指向负记忆（相邻支路）
    #   pos_clean  ：既无重叠也无边（不应被抑制）
    cg.add("pos_overlap", TEXT, "knowledge")
    cg.add("pos_edge", "泽塔 量子 比特 纠缠", "knowledge")
    cg.add("pos_clean", "泽塔 海流 洋流 潮汐", "knowledge")
    #   pos_mid    ：与负记忆部分重叠（包含度≈0.5）→ 用来验证阈值真的在过滤
    cg.add("pos_mid", "阿尔法 贝塔 海流 洋流", "knowledge")
    cg.add("h_rej", NEGTEXT, "rejected")
    cg.append_edge("pos_edge", {"target": "h_rej", "relation_type": "related"})
    cg.flush()
    return cg


def main():
    root = tempfile.mkdtemp(prefix="retr_s5_")
    cg = _build(root)

    # ---- 1) 默认关 ----
    old = _setenv(MDCG_RETRIEVAL_PIPELINE=None, MDCG_GATE_S5_NEG=None,
                  MDCG_NEG_LAMBDA=None, MDCG_NEG_SIM=None,
                  MDCG_GATE_S1_DOMAIN=None, MDCG_GATE_S2_COND=None)
    r_off, m_off = cg.search(QUERY, k=10, judge=False, record=False)
    base = _scores(r_off)
    check("默认关：meta 不含 gates 键", "gates" not in m_off,
          str(sorted(m_off.keys())))
    check("默认关：负记忆条目与正候选同权（1.0）",
          base.get("rejected/h_rej.md") == 1.0, str(base))

    # ---- 2) 子开关未设（总开关开、S1/S2 显式关）→ S5 不生效 ----
    _setenv(MDCG_RETRIEVAL_PIPELINE="1", MDCG_GATE_S5_NEG=None,
            MDCG_GATE_S1_DOMAIN="0", MDCG_GATE_S2_COND="0")
    r_x, m_x = cg.search(QUERY, k=10, judge=False, record=False)
    check("子开关未设：S5 不生效",
          "s5" not in (m_x.get("gates") or {}) and _scores(r_x) == base,
          str(m_x.get("gates")))

    # ---- 3) S5 开：重叠 + 相邻抑制，无关候选不动 ----
    _setenv(MDCG_GATE_S5_NEG="1", MDCG_NEG_LAMBDA="0.5", MDCG_NEG_SIM="0.5")
    r5, m5 = cg.search(QUERY, k=10, judge=False, record=False)
    sc5 = _scores(r5)
    g5 = (m5.get("gates") or {}).get("s5") or {}
    check("S5 审计：λ/threshold/抑制数",
          g5.get("lambda") == 0.5 and g5.get("threshold") == 0.5
          and g5.get("suppressed", 0) >= 2, str(g5))
    _sup = set(g5.get("suppressed_ids") or [])
    check("重叠候选被抑制（×0.5）",
          abs(sc5.get("pos_overlap", -1) - base["pos_overlap"] * 0.5) < 1e-9
          and "pos_overlap" in _sup,
          "%s vs %s  sup=%s" % (sc5.get("pos_overlap"), base.get("pos_overlap"), sorted(_sup)))
    check("相邻候选被抑制（文本不重叠也生效）",
          abs(sc5.get("pos_edge", -1) - base["pos_edge"] * 0.5) < 1e-9
          and "pos_edge" in _sup,
          "%s vs %s  sup=%s" % (sc5.get("pos_edge"), base.get("pos_edge"), sorted(_sup)))
    check("无关候选不被抑制",
          sc5.get("pos_clean") == base.get("pos_clean")
          and "pos_clean" not in _sup,
          "%s vs %s  sup=%s" % (sc5.get("pos_clean"), base.get("pos_clean"), sorted(_sup)))
    check("负记忆条目不再同权（1.0 → 0.5）",
          sc5.get("rejected/h_rej.md") == 0.5, str(sc5.get("rejected/h_rej.md")))

    # ---- 4) λ 可配：0=不抑制；1=压到 0 且 ≥0 ----
    _setenv(MDCG_NEG_LAMBDA="0")
    r0, _m0 = cg.search(QUERY, k=10, judge=False, record=False)
    check("λ=0：不抑制", _scores(r0) == base, str(_scores(r0)))
    _setenv(MDCG_NEG_LAMBDA="1")
    r1, _m1 = cg.search(QUERY, k=10, judge=False, record=False)
    sc1 = _scores(r1)
    check("λ=1：压到 0 且不为负",
          sc1["pos_overlap"] == 0.0 and sc1["pos_edge"] == 0.0
          and min(sc1.values()) >= 0.0, str(sc1))

    # ---- 5) 阈值真的在过滤：部分重叠候选（包含度≈0.5）在 0.6 下不抑制、0.4 下被抑制 ----
    _setenv(MDCG_NEG_LAMBDA="0.5", MDCG_NEG_SIM="0.6")
    r2, m2 = cg.search(QUERY, k=10, judge=False, record=False)
    sc2 = _scores(r2)
    sup2 = set(((m2.get("gates") or {}).get("s5") or {}).get("suppressed_ids") or [])
    check("thr=0.6：部分重叠不抑制、完全重叠仍抑制",
          sc2["pos_mid"] == base["pos_mid"]
          and "pos_mid" not in sup2 and "pos_overlap" in sup2,
          str(sc2) + " " + str(sorted(sup2)))
    _setenv(MDCG_NEG_SIM="0.4")
    r3, m3 = cg.search(QUERY, k=10, judge=False, record=False)
    sc3 = _scores(r3)
    sup3 = set(((m3.get("gates") or {}).get("s5") or {}).get("suppressed_ids") or [])
    check("thr=0.4：部分重叠也被抑制",
          abs(sc3["pos_mid"] - base["pos_mid"] * 0.5) < 1e-9
          and "pos_mid" in sup3,
          str(sc3) + " " + str(sorted(sup3)))

    # ---- 5b) 配置的 λ 必须真的生效（含审计）----
    _setenv(MDCG_NEG_LAMBDA="0.25", MDCG_NEG_SIM="0.5")
    r4, m4 = cg.search(QUERY, k=10, judge=False, record=False)
    sc4 = _scores(r4)
    g4 = (m4.get("gates") or {}).get("s5") or {}
    check("λ=0.25：负记忆条目 0.75 且审计记 0.25",
          sc4.get("rejected/h_rej.md") == 0.75 and g4.get("lambda") == 0.25,
          "%s %s" % (sc4.get("rejected/h_rej.md"), g4))

    # ---- 6) 无负记忆命中：不落 s5 审计 ----
    r3, m3 = cg.search("西格玛 欧米伽", k=10, judge=False, record=False)
    check("无负记忆命中：不落 s5 审计",
          "s5" not in (m3.get("gates") or {}), str(m3.get("gates")))

    # ---- 7) 幂等：重复检索 / 索引重建 ----
    _setenv(MDCG_NEG_LAMBDA="0.5", MDCG_NEG_SIM="0.5")
    ra, ma = cg.search(QUERY, k=10, judge=False, record=False)
    rb, mb = cg.search(QUERY, k=10, judge=False, record=False)
    check("S5 幂等：重复检索同口径",
          _scores(ra) == _scores(rb)
          and (ma.get("gates") or {}) == (mb.get("gates") or {}), str(_scores(ra)))
    cg.rebuild_index()
    rc, mc = cg.search(QUERY, k=10, judge=False, record=False)
    check("S5 幂等：索引重建后同口径",
          _scores(rc) == _scores(ra)
          and (mc.get("gates") or {}) == (ma.get("gates") or {}), str(_scores(rc)))

    # ---- 8) 默认口径等价（关→开→关）----
    _setenv(MDCG_RETRIEVAL_PIPELINE=None, MDCG_GATE_S5_NEG=None,
            MDCG_NEG_LAMBDA=None, MDCG_NEG_SIM=None,
            MDCG_GATE_S1_DOMAIN=None, MDCG_GATE_S2_COND=None)
    r9, m9 = cg.search(QUERY, k=10, judge=False, record=False)
    check("默认口径等价：关→开→关 首末一致",
          _scores(r9) == base and "gates" not in m9, str(_scores(r9)))
    _restore(old)

    print("\ntest_retr_s5: %d 通过 / %d 失败" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
