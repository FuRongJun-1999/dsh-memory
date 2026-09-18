# -*- coding: utf-8 -*-
"""S1/S2 检索前门控探针（脚本式，exit code 定成败）。

用法：python -X utf8 -m md_cg.test_retr_s1
覆盖：
- routing.domain_terms / classify_text（取词、去重、limit、空值、无信号）
- 写入侧：add() 落 big_domain 且索引快照同口径；无信号节点不写该字段
- 默认关：MDCG_RETRIEVAL_PIPELINE 未设 → gates 为空且 scanned=全量（行为等价）
- S1 开：按域收敛 → gates.s1.dropped>0、scanned 下降
- S2 开：位置明确不匹配 → 丢；信息不足 → 一律放行
- backfill_big_domain：dry-run 不改盘、真跑落盘、二次跑幂等
"""
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import nodefile, routing  # noqa: E402
from md_cg.mdcg import MdCG  # noqa: E402

passed = 0
failed = 0
GONG = "工程 结构 应力 梁 截面 桥梁 材料 机械"
YI = "医学 疾病 诊断 药物 处方 症状 治疗"


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


def _write_raw(root, nid, layer, content, pos=None):
    fm = {"id": nid, "layer": layer, "modality": "text", "importance": 0.5,
          "confidence": 0.6, "condition_space": {"time_window": [0, 10 ** 12]},
          "tags": [], "created_at": 0, "access_count": 0, "last_access": 0,
          "edges": []}
    if pos:
        fm["condition_space"]["observation_position"] = pos
    p = os.path.join(root, layer, nid + ".md")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    io.open(p, "w", encoding="utf-8").write(nodefile.dumps(fm, content))
    return p


def main():
    # ---- 1) routing 侧 ----
    check("domain_terms 空值 -> []", routing.domain_terms("") == [])
    ts = routing.domain_terms("工程 应力 桥梁 " * 3)
    check("domain_terms 去重保序", ts == ["工程", "应力", "桥梁"], str(ts[:4]))
    check("domain_terms limit 生效",
          len(routing.domain_terms("工程 应力 桥梁 材料", limit=2)) == 2)
    check("classify_text 有信号 -> 工程",
          routing.classify_text(GONG) == "工程", str(routing.classify_text(GONG)))
    check("classify_text 无信号 -> None", routing.classify_text("xyzzy zzz") is None)

    # ---- 2) 写入侧 ----
    root = tempfile.mkdtemp(prefix="retr_s1_")
    cg = MdCG(root)
    cg.add("n_gong", GONG + " 坝体受力", "knowledge", importance=0.9)
    cg.add("n_yi", YI, "knowledge", importance=0.5)
    cg.add("n_none", "xyzzy zzz", "knowledge")
    cg.flush()
    check("写入落 big_domain",
          cg.get("n_gong")["frontmatter"].get("big_domain") == "工程")
    check("索引快照同口径",
          cg.index["nodes"]["n_gong"].get("big_domain") == "工程",
          str(cg.index["nodes"]["n_gong"].get("big_domain")))
    check("无信号不写该字段",
          "big_domain" not in (cg.get("n_none")["frontmatter"] or {}))

    # ---- 3) 默认关：行为等价 ----
    old = _setenv(MDCG_RETRIEVAL_PIPELINE=None, MDCG_GATE_S1_DOMAIN=None,
                  MDCG_GATE_S2_COND=None)
    _r, meta = cg.search("工程 应力", k=10, judge=False, record=False)
    check("默认关 gates 为空", meta.get("gates") == {}, str(meta.get("gates")))
    check("默认关 scanned=全量", meta.get("scanned") == 3, str(meta.get("scanned")))

    # ---- 4) S1 开 ----
    _setenv(MDCG_RETRIEVAL_PIPELINE="1", MDCG_GATE_S1_DOMAIN="1",
            MDCG_GATE_S2_COND="0")
    _r, meta = cg.search("工程 应力", k=10, judge=False, record=False)
    s1 = (meta.get("gates") or {}).get("s1") or {}
    check("S1 收敛到工程域", s1.get("domain") == "工程", str(s1))
    check("S1 丢弃异域候选", s1.get("dropped", 0) >= 2, str(s1))
    check("S1 scanned 下降", meta.get("scanned", 99) <= 1, str(meta.get("scanned")))
    _restore(old)

    # ---- 5) S2 门控 ----
    root2 = tempfile.mkdtemp(prefix="retr_s2_")
    _write_raw(root2, "a", "knowledge", GONG, pos="工程 结构")
    _write_raw(root2, "b", "knowledge", YI, pos="医学 疾病")
    cg2 = MdCG(root2)
    cg2.rebuild_index()
    old = _setenv(MDCG_RETRIEVAL_PIPELINE="1", MDCG_GATE_S1_DOMAIN="0",
                  MDCG_GATE_S2_COND="1")
    _r, meta = cg2.search("xyzzy", k=10, judge=False, record=False,
                          context={"observation_position": "工程 结构"})
    s2 = (meta.get("gates") or {}).get("s2") or {}
    check("S2 位置不匹配被门控", s2.get("dropped") == 1, str(s2))
    _r, meta = cg2.search("xyzzy", k=10, judge=False, record=False, context={})
    s2 = (meta.get("gates") or {}).get("s2") or {}
    check("S2 信息不足一律放行", s2.get("dropped") == 0, str(s2))
    _restore(old)

    # ---- 6) backfill ----
    root3 = tempfile.mkdtemp(prefix="retr_bf_")
    _write_raw(root3, "g1", "knowledge", GONG)
    _write_raw(root3, "y1", "knowledge", YI)
    _write_raw(root3, "x1", "knowledge", "xyzzy")
    cg3 = MdCG(root3)
    cg3.rebuild_index()
    st1 = cg3.backfill_big_domain(dry_run=True)
    check("backfill dry-run 统计",
          st1["written"] == 2 and st1["no_signal"] == 1, str(st1))
    check("backfill dry-run 不改盘",
          cg3.get("g1")["frontmatter"].get("big_domain") is None)
    st2 = cg3.backfill_big_domain()
    check("backfill 真跑落盘",
          st2["written"] == 2
          and cg3.get("g1")["frontmatter"].get("big_domain") == "工程", str(st2))
    check("backfill 同步索引",
          cg3.index["nodes"]["y1"].get("big_domain") == "医学")
    st3 = cg3.backfill_big_domain()
    # 幂等口径：二次跑不再写盘（有信号的计入 already，无信号的永远计入 no_signal）
    check("backfill 幂等",
          st3["written"] == 0 and st3["already"] == 2
          and st3["no_signal"] == 1, str(st3))

    print("\ntest_retr_s1: %d 通过 / %d 失败" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
