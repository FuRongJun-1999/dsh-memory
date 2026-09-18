# -*- coding: utf-8 -*-
"""S1b 细口径桶收敛探针（脚本式，exit code 定成败）。

用法：python -X utf8 -m md_cg.test_retr_s1b
覆盖：
- bucket_key_readable：'cond_感知系统_d94e90d2' → '感知系统'；orphan/空 → ''；无哈希段保持
- 默认关：无 gates 键；关→开→关 结果一致；子开关未设不生效
- S1b 开：query 侧推断出候选桶 → 候选收敛（out < in）、**orphan/无桶恒留兜底**、不引入任何新节点
- 命中不到任何桶 → no_key_match 且不收敛（回退）
- topk / min_sim 可配（topk=0 关闭；min_sim=1.0 只认完全同名键）
- 幂等：重复检索 / 索引重建后同口径
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import routing  # noqa: E402
from md_cg.mdcg import MdCG  # noqa: E402

passed = 0
failed = 0
QUERY = "感知系统 记忆 检索"


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


def _ids(results):
    return sorted(r[0]["id"] for r in results)


def _build(root):
    cg = MdCG(root)
    cg.add("s1", "感知系统 记忆 节点 检索", "knowledge", tags=["domain:感知系统"])
    cg.add("s2", "感知系统 缓存 命中", "knowledge", tags=["domain:感知系统"])
    cg.add("g1", "图数据库 遍历 邻接", "knowledge", tags=["domain:图数据库"])
    cg.add("o1", "感知系统 但无域标签（落 orphan）", "knowledge")
    cg.add("c1", "感知系统 情境层（不参与分桶）", "contextual")
    cg.flush()
    return cg


def main():
    # ---- 1) key 解析 ----
    check("bucket_key_readable 剥离哈希",
          routing.bucket_key_readable("cond_感知系统_d94e90d2") == "感知系统")
    check("bucket_key_readable orphan/空 → ''",
          routing.bucket_key_readable("orphan") == ""
          and routing.bucket_key_readable("") == ""
          and routing.bucket_key_readable(None) == "")
    check("bucket_key_readable 无哈希段保持",
          routing.bucket_key_readable("cond_letta-code") == "letta-code")

    root = tempfile.mkdtemp(prefix="retr_s1b_")
    cg = _build(root)
    b_sense = [e.get("bucket") for e in cg.index["nodes"].values()
               if e.get("path", "").endswith("s1.md")][0]
    check("写入侧确实落了桶", bool(b_sense) and b_sense != "orphan", str(b_sense))

    # ---- 2) 默认关 ----
    old = _setenv(MDCG_RETRIEVAL_PIPELINE=None, MDCG_GATE_S1B_BUCKET=None,
                  MDCG_GATE_S1_DOMAIN=None, MDCG_GATE_S2_COND=None,
                  MDCG_BUCKET_TOPK=None, MDCG_BUCKET_MIN_SIM=None)
    r_off, m_off = cg.search(QUERY, k=10, judge=False, record=False)
    base = _ids(r_off)
    check("默认关：meta 不含 gates 键", "gates" not in m_off,
          str(sorted(m_off.keys())))

    # ---- 3) 子开关未设 → 不生效 ----
    _setenv(MDCG_RETRIEVAL_PIPELINE="1", MDCG_GATE_S1_DOMAIN="0",
            MDCG_GATE_S2_COND="0", MDCG_GATE_S1B_BUCKET=None)
    r_x, m_x = cg.search(QUERY, k=10, judge=False, record=False)
    check("子开关未设：S1b 不生效",
          "s1b" not in (m_x.get("gates") or {}) and _ids(r_x) == base,
          str(m_x.get("gates")))

    # ---- 4) S1b 开：桶收敛 + orphan 兜底 + 不引入新节点 ----
    _setenv(MDCG_GATE_S1B_BUCKET="1", MDCG_BUCKET_TOPK="1", MDCG_BUCKET_MIN_SIM="0.34")
    r1, m1 = cg.search(QUERY, k=10, judge=False, record=False)
    g1 = (m1.get("gates") or {}).get("s1b") or {}
    ids1 = _ids(r1)
    check("S1b 推断出感知系统桶",
          g1.get("keys") == [b_sense], str(g1))
    check("S1b 收敛：out < in", g1.get("out", 99) < g1.get("in", 0), str(g1))
    check("S1b 收敛后不引入任何新节点（⊆ 默认关结果集）",
          set(ids1) <= set(base), str(ids1) + " vs " + str(base))
    check("S1b 保留 orphan 兜底节点", "o1" in ids1, str(ids1))
    check("S1b 丢弃异桶节点", "g1" not in ids1, str(ids1))

    # ---- 5) 命中不到桶 → 回退不收敛 ----
    r2, m2 = cg.search("完全无关的词 词组", k=10, judge=False, record=False)
    g2 = (m2.get("gates") or {}).get("s1b") or {}
    check("无键命中：no_key_match 且不收敛",
          g2.get("reason") == "no_key_match" and g2.get("in") == g2.get("in")
          and "out" not in g2, str(g2))

    # ---- 6) topk / min_sim 可配 ----
    _setenv(MDCG_BUCKET_TOPK="0")
    r3, m3 = cg.search(QUERY, k=10, judge=False, record=False)
    g3 = (m3.get("gates") or {}).get("s1b") or {}
    check("topk=0：关闭且候选不变",
          g3.get("reason") == "disabled_by_topk" and _ids(r3) == base, str(g3))
    _setenv(MDCG_BUCKET_TOPK="2", MDCG_BUCKET_MIN_SIM="0.0")
    r4, m4 = cg.search(QUERY, k=10, judge=False, record=False)
    g4 = (m4.get("gates") or {}).get("s1b") or {}
    check("topk=2 + min_sim=0：取到 2 个桶",
          len(g4.get("keys") or []) == 2, str(g4))
    _setenv(MDCG_BUCKET_TOPK="1", MDCG_BUCKET_MIN_SIM="1.0")
    r5, m5 = cg.search("感知", k=10, judge=False, record=False)
    g5 = (m5.get("gates") or {}).get("s1b") or {}
    check("min_sim=1.0：部分匹配不入选", g5.get("reason") == "no_key_match", str(g5))
    _setenv(MDCG_BUCKET_MIN_SIM="0.34")
    r6, m6 = cg.search("感知", k=10, judge=False, record=False)
    g6 = (m6.get("gates") or {}).get("s1b") or {}
    check("min_sim=0.34：部分匹配（感知→感知系统 0.5）入选",
          g6.get("keys") == [b_sense], str(g6))

    # ---- 7) 幂等 ----
    _setenv(MDCG_BUCKET_TOPK="1", MDCG_BUCKET_MIN_SIM="0.34")
    ra, ma = cg.search(QUERY, k=10, judge=False, record=False)
    rb, mb = cg.search(QUERY, k=10, judge=False, record=False)
    check("S1b 幂等：重复检索同口径",
          _ids(ra) == _ids(rb)
          and (ma.get("gates") or {}).get("s1b") == (mb.get("gates") or {}).get("s1b"))
    cg.rebuild_index()
    rc, mc = cg.search(QUERY, k=10, judge=False, record=False)
    check("S1b 幂等：索引重建后同口径",
          _ids(rc) == _ids(ra)
          and (mc.get("gates") or {}).get("s1b") == (ma.get("gates") or {}).get("s1b"))

    # ---- 8) 默认口径等价 ----
    _setenv(MDCG_RETRIEVAL_PIPELINE=None, MDCG_GATE_S1B_BUCKET=None,
            MDCG_GATE_S1_DOMAIN=None, MDCG_GATE_S2_COND=None,
            MDCG_BUCKET_TOPK=None, MDCG_BUCKET_MIN_SIM=None)
    r9, m9 = cg.search(QUERY, k=10, judge=False, record=False)
    check("默认口径等价：关→开→关 首末一致",
          _ids(r9) == base and "gates" not in m9, str(_ids(r9)))
    _restore(old)

    print("\ntest_retr_s1b: %d 通过 / %d 失败" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
