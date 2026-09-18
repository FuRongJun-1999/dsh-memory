# -*- coding: utf-8 -*-
"""S6 一致性交叉验证探针（脚本式，exit code 定成败）。

用法：python -X utf8 -m md_cg.test_retr_s6
覆盖：
- 默认关：无 gates 键；关→开→关 结果一致
- 子开关未设（总开关开）→ S6 不生效
- S6 开：top-k 逐个给出赛道/依据许可/断言条数；**结果与排序完全不变**
- 点名规则：赛道已定 ∧ 声明依据不被该赛道许可 → 进 flagged；已许可或赛道未定 → 不点名
- 只读：不产生 _crosscheck.jsonl；幂等（重复检索 / 索引重建）
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import crosscheck as cc  # noqa: E402
from md_cg.mdcg import MdCG  # noqa: E402

passed = 0
failed = 0
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


def _snap(results):
    return [(r[0]["id"], round(float(r[1]), 6)) for r in results]


def _build(root):
    sci = cc.allowed_basis("science")
    hum = cc.allowed_basis("humanities")
    sci_basis = sci[0] if sci else "reproducible"
    hum_basis = hum[0] if hum else "consistency"
    cg = MdCG(root)
    # 赛道已定 + 依据不被许可 → 应点名
    cg.add("d_sci_bad", "阿尔法 贝塔 应力 截面", "knowledge",
           track="science", verification_basis=hum_basis)
    # 赛道已定 + 依据被许可 → 不点名
    cg.add("d_sci_ok", "阿尔法 伽马 应力 材料", "knowledge",
           track="science", verification_basis=sci_basis)
    cg.add("d_hum_ok", "阿尔法 德尔塔 文本 修辞", "knowledge",
           track="humanities", verification_basis=hum_basis)
    # 赛道未定 + 无依据 → 不点名
    cg.add("d_und", "阿尔法 泽塔 无赛道标记", "knowledge")
    cg.flush()
    return cg, sci_basis, hum_basis


def main():
    root = tempfile.mkdtemp(prefix="retr_s6_")
    cg, sci_basis, hum_basis = _build(root)

    # ---- 1) 默认关 ----
    old = _setenv(MDCG_RETRIEVAL_PIPELINE=None, MDCG_GATE_S6_CROSSCHECK=None,
                  MDCG_GATE_S1_DOMAIN=None, MDCG_GATE_S2_COND=None)
    r_off, m_off = cg.search(QUERY, k=10, judge=False, record=False)
    base = _snap(r_off)
    check("默认关：meta 不含 gates 键", "gates" not in m_off,
          str(sorted(m_off.keys())))

    # ---- 2) 子开关未设 → 不生效 ----
    _setenv(MDCG_RETRIEVAL_PIPELINE="1", MDCG_GATE_S6_CROSSCHECK=None,
            MDCG_GATE_S1_DOMAIN="0", MDCG_GATE_S2_COND="0")
    r_x, m_x = cg.search(QUERY, k=10, judge=False, record=False)
    check("子开关未设：S6 不生效",
          "s6" not in (m_x.get("gates") or {}) and _snap(r_x) == base,
          str(m_x.get("gates")))

    # ---- 3) S6 开：审计齐备且**排序不变** ----
    _setenv(MDCG_RETRIEVAL_PIPELINE="1", MDCG_GATE_S6_CROSSCHECK="1",
            MDCG_GATE_S1_DOMAIN="0", MDCG_GATE_S2_COND="0")
    r6, m6 = cg.search(QUERY, k=10, judge=False, record=False)
    g6 = (m6.get("gates") or {}).get("s6") or {}
    check("S6 审计：checked/by_track/rows 齐备",
          g6.get("checked") == len(r6) and bool(g6.get("by_track"))
          and len(g6.get("rows") or []) == len(r6), str(g6)[:200])
    check("S6 不改排序（结果与默认关逐条一致）", _snap(r6) == base,
          str(_snap(r6)) + " vs " + str(base))

    # ---- 4) 点名规则 ----
    flagged = {f["id"] for f in (g6.get("flagged") or [])}
    rows = {row["id"]: row for row in (g6.get("rows") or [])}
    check("未许可依据被点名（science + 文科依据）",
          "d_sci_bad" in flagged, str(sorted(flagged)))
    check("已许可依据不点名（science/理科依据 与 humanities/文科依据）",
          "d_sci_ok" not in flagged and "d_hum_ok" not in flagged,
          str(sorted(flagged)))
    check("赛道未定不点名",
          rows.get("d_und", {}).get("track") == "undetermined"
          and "d_und" not in flagged, str(rows.get("d_und")))
    check("赛道判定正确",
          rows.get("d_sci_bad", {}).get("track") == "science"
          and rows.get("d_hum_ok", {}).get("track") == "humanities",
          str({k: v.get("track") for k, v in rows.items()}))

    # ---- 5) 只读：不产生核对留痕 ----
    check("S6 只读：无 _crosscheck.jsonl",
          not os.path.exists(os.path.join(root, "_crosscheck.jsonl")))

    # ---- 6) 幂等：重复检索 / 索引重建 ----
    ra, ma = cg.search(QUERY, k=10, judge=False, record=False)
    rb, mb = cg.search(QUERY, k=10, judge=False, record=False)
    check("S6 幂等：重复检索同口径",
          (ma.get("gates") or {}).get("s6") == (mb.get("gates") or {}).get("s6")
          and _snap(ra) == _snap(rb))
    cg.rebuild_index()
    rc, mc = cg.search(QUERY, k=10, judge=False, record=False)
    check("S6 幂等：索引重建后同口径",
          (mc.get("gates") or {}).get("s6") == (ma.get("gates") or {}).get("s6")
          and _snap(rc) == _snap(ra))

    # ---- 7) 默认口径等价 ----
    _setenv(MDCG_RETRIEVAL_PIPELINE=None, MDCG_GATE_S6_CROSSCHECK=None,
            MDCG_GATE_S1_DOMAIN=None, MDCG_GATE_S2_COND=None)
    r9, m9 = cg.search(QUERY, k=10, judge=False, record=False)
    check("默认口径等价：关→开→关 首末一致",
          _snap(r9) == base and "gates" not in m9, str(_snap(r9)))
    _restore(old)

    print("\ntest_retr_s6: %d 通过 / %d 失败" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
