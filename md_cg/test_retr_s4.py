# -*- coding: utf-8 -*-
"""S4 层级激活优先级探针（脚本式，exit code 定成败）。

用法：python -X utf8 -m md_cg.test_retr_s4
覆盖：
- layer_boosts 解析（默认副本 / 部分覆盖 / 非法项忽略 / 负值夹 0）
- 默认关：无 gates 键；关→开→关 结果一致
- 子开关未设（总开关开）→ S4 不生效
- 层级加成生效：同内容不同层 → anchor/self > structural > knowledge > contextual
- 自定义 MDCG_LAYER_BOOST 改变次序；分数上限仍 1.0
- 只改排序不拉回被门控剔除的节点；幂等（重复检索 / 索引重建）
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mdcg import MdCG, layer_boosts, LAYER_BOOST_DEFAULT  # noqa: E402

passed = 0
failed = 0
TEXT = "阿尔法 贝塔 伽马 德尔塔"
# 查询只与正文部分重叠（sim≈0.5），否则精确匹配会把分数顶到 1.0、层级加成看不出来
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


def main():
    # ---- 1) 解析器 ----
    check("默认表副本（不共享引用）",
          layer_boosts("") == LAYER_BOOST_DEFAULT
          and layer_boosts("") is not LAYER_BOOST_DEFAULT)
    bo = layer_boosts("anchor=0.3,zzz=1,contextual=abc,knowledge=-5")
    check("部分覆盖 + 非法项忽略 + 负值夹 0",
          bo["anchor"] == 0.3 and bo["contextual"] == LAYER_BOOST_DEFAULT["contextual"]
          and bo["knowledge"] == 0.0 and "zzz" in bo, str(bo))

    # ---- 2) 建库：同内容、不同层 ----
    root = tempfile.mkdtemp(prefix="retr_s4_")
    cg = MdCG(root)
    for layer in ("anchor", "self", "structural", "knowledge", "contextual"):
        cg.add("n_" + layer, TEXT, layer)
    cg.flush()

    old = _setenv(MDCG_RETRIEVAL_PIPELINE=None, MDCG_GATE_S4_LAYER=None,
                  MDCG_LAYER_BOOST=None)
    r_off, m_off = cg.search(QUERY, k=10, judge=False, record=False)
    snap_off = _scores(r_off)
    check("默认关：meta 不含 gates 键", "gates" not in m_off,
          str(sorted(m_off.keys())))
    check("默认关：同内容各层分数相同（无加成）",
          len(set(snap_off.values())) == 1 and 0 < max(snap_off.values()) < 1.0,
          str(snap_off))

    # 2b 子开关未设（总开关开、S1/S2 显式关）→ S4 不生效
    _setenv(MDCG_RETRIEVAL_PIPELINE="1", MDCG_GATE_S4_LAYER=None,
            MDCG_LAYER_BOOST=None, MDCG_GATE_S1_DOMAIN="0",
            MDCG_GATE_S2_COND="0")
    r_x, m_x = cg.search(QUERY, k=10, judge=False, record=False)
    check("子开关未设：S4 不生效",
          "s4" not in (m_x.get("gates") or {}) and _scores(r_x) == snap_off,
          str(m_x.get("gates")))

    # ---- 3) S4 开：层级次序 ----
    _setenv(MDCG_RETRIEVAL_PIPELINE="1", MDCG_GATE_S4_LAYER="1",
            MDCG_LAYER_BOOST=None, MDCG_GATE_S1_DOMAIN="0",
            MDCG_GATE_S2_COND="0")
    r4, m4 = cg.search(QUERY, k=10, judge=False, record=False)
    sc = _scores(r4)
    g4 = (m4.get("gates") or {}).get("s4") or {}
    check("S4 审计含 boosts/layers", bool(g4.get("boosts")) and bool(g4.get("layers")),
          str(g4)[:160])
    check("anchor/self > structural > knowledge > contextual",
          sc["n_anchor"] > sc["n_structural"] > sc["n_knowledge"] > sc["n_contextual"]
          and sc["n_self"] == sc["n_anchor"],
          str(sc))
    check("加成上限：分数不超过 1.0", max(sc.values()) <= 1.0 + 1e-9, str(sc))

    # ---- 4) 自定义加成表改变次序 ----
    _setenv(MDCG_LAYER_BOOST="contextual=0.5,knowledge=0.0,anchor=0.0,self=0.0,structural=0.0")
    r5, _m5 = cg.search(QUERY, k=10, judge=False, record=False)
    sc5 = _scores(r5)
    check("自定义加成：contextual 升到首位",
          sc5["n_contextual"] > sc5["n_anchor"], str(sc5))

    # ---- 5) 只改排序，不拉回被门控剔除的节点 ----
    _setenv(MDCG_LAYER_BOOST=None, MDCG_GATE_S2_COND="1",
            MDCG_GATE_S1_DOMAIN="0")
    # 注意：本段临时改了 S1/S2，出段后必须还原，否则幂等段的 gates 不可比
    root2 = tempfile.mkdtemp(prefix="retr_s4g_")
    cgg = MdCG(root2)
    cgg.add("g_ok", TEXT, "knowledge",
            condition_space={"observation_position": "工程 结构"})
    cgg.add("g_no", TEXT, "anchor",
            condition_space={"observation_position": "医学 疾病"})
    cgg.flush()
    r6, m6 = cgg.search("阿尔法", k=10, judge=False, record=False,
                        context={"observation_position": "工程 结构"})
    ids6 = [r[0]["id"] for r in r6]
    check("S2 拦掉的节点不因 S4 加成回归",
          "g_no" not in ids6 and "g_ok" in ids6, str(ids6) + " " + str(m6.get("gates")))
    _setenv(MDCG_GATE_S2_COND=None, MDCG_GATE_S1_DOMAIN="0")

    # ---- 6) 幂等：重复检索 / 索引重建 ----
    r7, m7 = cg.search(QUERY, k=10, judge=False, record=False)
    check("S4 幂等：重复检索同口径",
          _scores(r7) == sc and (m7.get("gates") or {}) == (m4.get("gates") or {}),
          str(_scores(r7)))
    cg.rebuild_index()
    r8, m8 = cg.search(QUERY, k=10, judge=False, record=False)
    check("S4 幂等：索引重建后同口径",
          _scores(r8) == sc and (m8.get("gates") or {}) == (m4.get("gates") or {}),
          str(_scores(r8)))

    # ---- 7) 默认口径等价（关→开→关）----
    _setenv(MDCG_RETRIEVAL_PIPELINE=None, MDCG_GATE_S4_LAYER=None,
            MDCG_LAYER_BOOST=None, MDCG_GATE_S2_COND=None, MDCG_GATE_S1_DOMAIN=None)
    r9, m9 = cg.search(QUERY, k=10, judge=False, record=False)
    check("默认口径等价：关→开→关 首末一致",
          _scores(r9) == snap_off and "gates" not in m9, str(_scores(r9)))
    _restore(old)

    print("\ntest_retr_s4: %d 通过 / %d 失败" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
