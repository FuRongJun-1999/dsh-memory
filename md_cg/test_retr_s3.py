# -*- coding: utf-8 -*-
"""S3 图扩散激活探针（脚本式，exit code 定成败）。

用法：python -X utf8 -m md_cg.test_retr_s3
覆盖：
- 默认关：不落 gates 键、结果与开启前后（关→开→关）一致
- S3 开：沿 edges 双向扩散出候选（TIER_SPREAD），seeds/expanded 审计计数正确
- hops 控制扩散半径；decay 控制跳数衰减（A > B > C 分数序）
- 未过 S2 门控的邻居不得被扩散引入
- 无 edges → expanded=0/reason=no_edges，并落回原 T2/T3 路径（召回不丢）
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mdcg import MdCG, TIER_SPREAD  # noqa: E402

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


def _build(root, edges=True, pos_b=None):
    cg = MdCG(root)
    cg.add("A", "工程 结构 应力 梁 截面", "knowledge", importance=0.5,
           condition_space={"observation_position": "工程 结构"})
    cg.add("B", "qxzq 与检索词无交集", "knowledge", importance=0.5,
           condition_space={"observation_position": pos_b or "工程 结构"})
    cg.add("C", "ppyx 另一段无交集文本", "knowledge", importance=0.5,
           condition_space={"observation_position": "工程 结构"})
    cg.add("D", "孤立节点 无任何边", "knowledge", importance=0.5,
           condition_space={"observation_position": "工程 结构"})
    if edges:
        cg.append_edge("A", {"target": "B", "relation_type": "related"})
        cg.append_edge("B", {"target": "C", "relation_type": "related"})
    cg.flush()
    return cg


def _score_of(results, nid):
    for r in results:
        if r[0]["id"] == nid:
            return r[1]
    return None


def main():
    root = tempfile.mkdtemp(prefix="retr_s3_")
    cg = _build(root)

    # ---- 1) 默认关 ----
    old = _setenv(MDCG_RETRIEVAL_PIPELINE=None, MDCG_GATE_S1_DOMAIN=None,
                  MDCG_GATE_S2_COND=None, MDCG_GATE_S3_SPREAD=None)
    r_off, meta_off = cg.search("工程 应力", k=5, judge=False, record=False)
    check("默认关：meta 不含 gates 键", "gates" not in meta_off,
          str(sorted(meta_off.keys())))
    snap_off = [(r[0]["id"], round(float(r[1]), 6)) for r in r_off]

    # 1b 总开关开、S1/S2 显式关、S3 子开关未设 → S3 必须仍为关（显式 =1 才生效）
    _setenv(MDCG_RETRIEVAL_PIPELINE="1", MDCG_GATE_S1_DOMAIN="0",
            MDCG_GATE_S2_COND="0", MDCG_GATE_S3_SPREAD=None)
    r_m, m_m = cg.search("工程 应力", k=5, judge=False, record=False)
    check("S3 子开关未设：不生效（无 gates / 结果不变）",
          "gates" not in m_m
          and [(r[0]["id"], round(float(r[1]), 6)) for r in r_m] == snap_off,
          str(m_m.get("gates")) + " " + str([r[0]["id"] for r in r_m]))

    # ---- 2) S3 开（S1/S2 关），hops=1 ----
    _setenv(MDCG_RETRIEVAL_PIPELINE="1", MDCG_GATE_S1_DOMAIN="0",
            MDCG_GATE_S2_COND="0", MDCG_GATE_S3_SPREAD="1",
            MDCG_SPREAD_HOPS="1", MDCG_SPREAD_DECAY="0.5",
            MDCG_SPREAD_GAIN="0.2")
    r1, m1 = cg.search("工程 应力", k=5, judge=False, record=False)
    s3 = (m1.get("gates") or {}).get("s3") or {}
    check("S3 命中种子=1", s3.get("seeds") == 1, str(s3))
    check("S3 hops=1 扩散出 1 个邻居", s3.get("expanded") == 1, str(s3))
    check("S3 tier 为扩散层", m1.get("tier") == TIER_SPREAD, str(m1.get("tier")))
    check("S3 邻居 B 进入结果", _score_of(r1, "B") is not None,
          str([r[0]["id"] for r in r1]))
    check("S3 未连通的 D 不进入", _score_of(r1, "D") is None,
          str([r[0]["id"] for r in r1]))

    # ---- 3) hops=2 扩散到 C，且衰减有序 A > B > C ----
    _setenv(MDCG_SPREAD_HOPS="2")
    r2, m2 = cg.search("工程 应力", k=5, judge=False, record=False)
    s3 = (m2.get("gates") or {}).get("s3") or {}
    check("S3 hops=2 扩散出 2 个", s3.get("expanded") == 2, str(s3))
    sa, sb, sc = _score_of(r2, "A"), _score_of(r2, "B"), _score_of(r2, "C")
    check("S3 衰减有序 A>B>C",
          sa is not None and sb is not None and sc is not None
          and sa > sb > sc, "A=%s B=%s C=%s" % (sa, sb, sc))

    # ---- 4) 未过 S2 门控的邻居不得被扩散引入（部分被拦，避免全滤回退掩盖不变量）----
    rroot = tempfile.mkdtemp(prefix="retr_s3g_")
    rg = MdCG(rroot)
    rg.add("A", "工程 结构 应力", "knowledge",
           condition_space={"observation_position": "工程 结构"})
    rg.add("B", "qxzq 无交集", "knowledge",
           condition_space={"observation_position": "医学 疾病"})
    rg.append_edge("A", {"target": "B", "relation_type": "related"})
    rg.flush()
    _setenv(MDCG_GATE_S2_COND="1")
    r3, m3 = rg.search("工程 应力", k=5, judge=False, record=False,
                       context={"observation_position": "工程 结构"})
    g3 = m3.get("gates") or {}
    ids3 = [r[0]["id"] for r in r3]
    check("S2 确实拦掉了 B", (g3.get("s2") or {}).get("dropped") == 1,
          str(g3.get("s2")))
    check("扩散不得引入被 S2 拦掉的邻居 B",
          "B" not in ids3 and (g3.get("s3") or {}).get("expanded", 0) == 0,
          str(ids3) + " " + str(g3.get("s3")))
    _setenv(MDCG_GATE_S2_COND="0")

    # ---- 5) 无 edges → 不扩散且落回原路径 ----
    root2 = tempfile.mkdtemp(prefix="retr_s3n_")
    cg2 = _build(root2, edges=False)
    r4, m4 = cg2.search("工程 应力", k=5, judge=False, record=False)
    s3 = (m4.get("gates") or {}).get("s3") or {}
    check("无 edges：expanded=0 且 reason=no_edges",
          s3.get("expanded") == 0 and s3.get("reason") == "no_edges", str(s3))
    check("无 edges：落回原路径且召回不丢",
          _score_of(r4, "A") is not None and m4.get("tier") != TIER_SPREAD,
          str(m4.get("tier")))

    # ---- 5b) 幂等：重复检索 / 索引重建后同口径 ----
    _setenv(MDCG_RETRIEVAL_PIPELINE="1", MDCG_GATE_S1_DOMAIN="0",
            MDCG_GATE_S2_COND="0", MDCG_GATE_S3_SPREAD="1",
            MDCG_SPREAD_HOPS="2", MDCG_SPREAD_DECAY="0.5",
            MDCG_SPREAD_GAIN="0.2")
    _snap = lambda rs: [(r[0]["id"], round(float(r[1]), 6)) for r in rs]
    ra, ma = cg.search("工程 应力", k=5, judge=False, record=False)
    rb, mb = cg.search("工程 应力", k=5, judge=False, record=False)
    check("S3 幂等：重复检索同口径",
          _snap(ra) == _snap(rb)
          and (ma.get("gates") or {}) == (mb.get("gates") or {}),
          str(_snap(ra)) + " vs " + str(_snap(rb)))
    cg.rebuild_index()
    rc, mc = cg.search("工程 应力", k=5, judge=False, record=False)
    check("S3 幂等：索引重建后同口径",
          _snap(rc) == _snap(ra)
          and (mc.get("gates") or {}) == (ma.get("gates") or {}),
          str(_snap(rc)) + " vs " + str(_snap(ra)))

    # ---- 6) 默认口径等价（关→开→关）----
    _setenv(MDCG_RETRIEVAL_PIPELINE=None, MDCG_GATE_S1_DOMAIN=None,
            MDCG_GATE_S2_COND=None, MDCG_GATE_S3_SPREAD=None,
            MDCG_SPREAD_HOPS=None, MDCG_SPREAD_DECAY=None,
            MDCG_SPREAD_GAIN=None)
    r_off2, meta_off2 = cg.search("工程 应力", k=5, judge=False, record=False)
    snap_off2 = [(r[0]["id"], round(float(r[1]), 6)) for r in r_off2]
    check("默认口径等价：关→开→关 首末一致", snap_off == snap_off2,
          str(snap_off) + " vs " + str(snap_off2))
    check("默认关：meta 仍不含 gates 键", "gates" not in meta_off2,
          str(sorted(meta_off2.keys())))
    _restore(old)

    print("\ntest_retr_s3: %d 通过 / %d 失败" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
