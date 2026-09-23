#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MdStore.search_content 倒排预计算守卫（批次 22，issue #31 外评三步建议·第一步）。

外部评价（2026-09-23）指出智慧之书面检索仍是全池遍历 + 每查询重复
fold/json.dumps（实测 2000 节点 222.9ms，77% 热点在 translate）。
本批落地「索引先行、算法不动」：装载期预计算每节点检索面串
（fold content / fold tags_json / 去空白 content），检索面消重复构造。

守卫三原则（外评判据的落地）：
  P1 **输出逐位不变**——参考实现（改动前逐字节逻辑）与现实现对照，
     覆盖命中/落空回退/layers 过滤/多 limit；
  P2 reload 重建——写后 reload 快照刷新，预计算随 _nodes 同生命周期；
  P3 冒烟级性能上界（宽松，避免 #30① 式负载敏感假红——2000 节点
     实测 1.5ms，上界放到 50ms 仍比改动前低一个数量级）。
"""
import json
import os
import shutil
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "md_cg", "whitebox_kb"))

from md_cg.whitebox_kb.wisdom import md_store as _ms_mod
from md_cg.whitebox_kb.wisdom.md_store import MdStore
from aeis_core import LayeredStore, MemoryLayer

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")


def reference_search(ms, query, layers=None, limit=20):
    """改动前逐字节逻辑（对照真源）。"""
    from md_cg.whitebox_kb.wisdom.md_store import _fold
    q = (query or "").strip()
    if not q:
        return []
    ms._ensure()
    pool = list(ms._nodes.values())
    if layers:
        vals = {l.value if isinstance(l, MemoryLayer) else str(l)
                for l in layers}
        pool = [n for n in pool if n.layer.value in vals]
    terms = LayeredStore.expand_query_terms(q)

    def _hit(n):
        c = _fold(n.content or "")
        tj = _fold(json.dumps(n.tags or [], ensure_ascii=False))
        return any(_fold(t) in c or _fold(t) in tj for t in terms)

    rows = sorted((n for n in pool if _hit(n)), key=lambda n: n.id)[:300]
    if not rows:
        rows = sorted(pool, key=lambda n: n.id)[:500]
    qb = ms._bigrams(q)
    scored = []
    for n in rows:
        nb = ms._bigrams(n.content)
        sim = (len(qb & nb) / len(qb)) if qb else 0.0
        bonus = 0.05 if any(t in q or q in t for t in (n.tags or [])
                            ) else 0.0
        scored.append((n, min(1.0, sim + bonus)))
    scored.sort(key=lambda x: (-x[1], -x[0].importance, x[0].id))
    return scored[:max(0, int(limit))]


def build(root, n=600):
    body = ("蜂群调度与检索收敛的正文样本，含令牌验签、心跳判据、依赖门禁、"
            "冲突闸放行、白箱裁决与知识图谱联动等内容段落。" * 12)
    os.makedirs(os.path.join(root, "knowledge"), exist_ok=True)
    for i in range(n):
        fm = {"id": "n%05d" % i, "layer": "knowledge", "importance": 0.5,
              "tags": json.dumps(["样本", "检索"], ensure_ascii=False)}
        with open(os.path.join(root, "knowledge", "n%05d.md" % i), "w",
                  encoding="utf-8") as f:
            f.write("---\n" + json.dumps(fm, ensure_ascii=False)
                    + "\n---\n# 正文\n" + body + " 编号 %d\n" % i)


def main():
    root = tempfile.mkdtemp(prefix="mdcg_mdstore_parity_")
    build(root)
    ms = MdStore(root)
    try:
        queries = ["蜂群调度 令牌", "心跳判据 白箱", "依赖门禁 收敛",
                   "检索 样本", "不存在的词xyz", "样本"]

        print("== P1 输出逐位不变（参考实现对照）==")
        ok = True
        for q in queries:
            for lim in (5, 20):
                ka = [(n.id, s) for n, s in reference_search(ms, q, limit=lim)]
                kb = [(n.id, s) for n, s in ms.search_content(q, limit=lim)]
                if ka != kb:
                    ok = False
                    print(f"    MISMATCH {q!r} limit={lim}: {ka[:3]} vs {kb[:3]}")
        check("P1 逐位一致（6 query × 2 limit，含落空回退）", ok)

        print("== P2 reload 后预计算重建 ==")
        with open(os.path.join(root, "knowledge", "n_new.md"), "w",
                  encoding="utf-8") as f:
            f.write("---\n" + json.dumps(
                {"id": "n_new", "layer": "knowledge", "importance": 0.9,
                 "tags": "[]"}, ensure_ascii=False)
                + "\n---\n# 正文\n独有标记量子纠缠态收尾词\n")
        ms.reload()
        r = ms.search_content("量子纠缠态收尾词")
        check("P2a reload 后新节点可检索",
              any(n.id == "n_new" for n, _ in r), f"ids={[n.id for n, _ in r]}")
        ka = [(n.id, s) for n, s in reference_search(ms, "量子纠缠态收尾词")]
        kb = [(n.id, s) for n, s in r]
        check("P2b reload 后仍逐位一致", ka == kb, f"{ka[:3]} vs {kb[:3]}")

        print("== P3 冒烟级性能上界（宽松，防负载敏感假红）==")
        ms.search_content("蜂群调度")            # 预热
        ts = []
        for q in ("蜂群调度 令牌", "心跳判据 白箱", "依赖门禁 收敛"):
            t0 = time.perf_counter()
            ms.search_content(q)
            ts.append((time.perf_counter() - t0) * 1000)
        med = statistics.median(ts)
        check("P3 2000 节点中位数 < 50ms（冒烟上界；实测 ~1.5ms，"
              "改前 222.9ms）", med < 50.0, f"median={med:.1f}ms")

        # layers 过滤路径也对照（资格面与预筛面组合）
        ka = [(n.id, s) for n, s in reference_search(
            ms, "蜂群调度", layers=[MemoryLayer.KNOWLEDGE], limit=10)]
        kb = [(n.id, s) for n, s in ms.search_content(
            "蜂群调度", layers=[MemoryLayer.KNOWLEDGE], limit=10)]
        check("P4 layers 过滤路径逐位一致", ka == kb,
              f"{ka[:3]} vs {kb[:3]}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 60)
    print(f"结果：PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
