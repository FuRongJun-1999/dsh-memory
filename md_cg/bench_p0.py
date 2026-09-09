# -*- coding: utf-8 -*-
"""md 认知图 P0 性能基准 · 把「无 SQL 索引」的代价变成数字

文档第 8 节把性能列为风险但没有数字。这里量化三件事：
  1. T0 条件路由命中（读一个桶）vs T2 全量 LIKE（读全部候选）的差距
     —— 这决定条件路由到底值多少
  2. md 版 vs sqlite 版 search_content 的绝对耗时 —— 这决定 P4 能不能切
  3. 写入吞吐 / 索引重建 / compact 耗时

跑法：python -m md_cg.bench_p0
"""
import os
import io
import sys
import time
import statistics

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mdcg import MdCG

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(HERE, "wisdom-book-cloud-new.db")
ROOT = os.path.join(HERE, "_md_cg_p0")

QUERIES = ["能量守恒", "二分查找", "细胞呼吸", "贝塞尔不等式", "牛顿第二定律",
           "数据结构 排序", "光合作用", "文明礼貌", "内力与截面法", "熵增"]


def timeit(fn, repeat=5):
    ts = []
    for _ in range(repeat):
        t = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t) * 1000)
    return statistics.median(ts), min(ts), max(ts)


def main():
    if not os.path.isdir(ROOT):
        print(f"未找到 md 库 {ROOT}，请先跑 md_cg.test_p0 或 md_cg.migrate")
        return 1
    cg = MdCG(ROOT)
    n = len(cg.index["nodes"])
    print(f"库规模：{n} 节点，{len(cg.index['buckets'])} 条件分区\n")

    # ---- 1. 条件路由 vs 全量 ----
    print("[检索延迟] 中位数 ms（5 次）")
    print(f"  {'query':<14}{'带 context':>12}{'无 context':>12}{'加速比':>9}  扫描量  命中层级")
    hit, miss = [], []
    ctx = {"tags": ["domain:计算机科学"]}
    for q in QUERIES:
        _r0, m0 = cg.search(q, layer="knowledge", k=10, context=ctx, record=False)
        t0 = timeit(lambda: cg.search(q, layer="knowledge", k=10, context=ctx,
                                      record=False))[0]
        t2 = timeit(lambda: cg.search(q, layer="knowledge", k=10, context=None,
                                      record=False))[0]
        (hit if m0["tier"].startswith(("T0", "T1")) else miss).append(t2 / t0 if t0 else 0)
        print(f"  {q:<14}{t0:>11.1f}{t2:>12.1f}{t2/t0 if t0 else 0:>8.1f}x"
              f"  {m0['scanned']:>5}/{n}  {m0['tier']}")
    # 分开汇总：把路由命中与未命中混进一个中位数会互相抵消，看不出任何东西
    if hit:
        print(f"  → 路由命中（{len(hit)}/{len(QUERIES)} 查询）中位加速 "
              f"{statistics.median(hit):.1f}x")
    if miss:
        print(f"  → 路由未命中（{len(miss)}/{len(QUERIES)} 查询）中位 "
              f"{statistics.median(miss):.2f}x —— 白付一次桶扫描的代价")
    print()

    # ---- 2. 与 sqlite 对比 ----
    try:
        from aeis.core import LayeredStore, MemoryLayer
        store = LayeredStore(DB)
        print("[md vs sqlite] 同查询集中位数 ms")
        md_ts, sq_ts = [], []
        for q in QUERIES:
            sq_ts.append(timeit(lambda: store.search_content(
                q, layers=[MemoryLayer.KNOWLEDGE], limit=10))[0])
            md_ts.append(timeit(lambda: cg.search(
                q, layer="knowledge", k=10, context=None, record=False))[0])
        print(f"  sqlite  中位 {statistics.median(sq_ts):7.1f} ms")
        print(f"  md T2   中位 {statistics.median(md_ts):7.1f} ms"
              f"   （{statistics.median(md_ts)/statistics.median(sq_ts):.1f}x sqlite）")
        print(f"  md T0   中位 {statistics.median([timeit(lambda: cg.search(q, layer='knowledge', k=10, context={'tags': ['domain:计算机科学']}, record=False))[0] for q in QUERIES]):7.1f} ms   （条件路由命中时）\n")
    except ImportError:
        print("[SKIP] 无 aeis，跳过 sqlite 对比\n")

    # ---- 3. 写入 / 维护 ----
    print("[写入与维护] ms")
    tmp = ROOT + "_bench"
    cgw = MdCG(tmp, autoflush=200)
    t = time.perf_counter()
    for i in range(500):
        cgw.add(f"b{i}", "基准写入测试内容 " * 10, tags=["domain:bench"])
    cgw.flush()
    dt = (time.perf_counter() - t) * 1000
    print(f"  写入 500 节点        {dt:8.1f} ms  ({500/dt*1000:.0f} 节点/秒)")
    t = time.perf_counter()
    cg.rebuild_index()
    print(f"  重建索引 {n} 节点   {(time.perf_counter()-t)*1000:8.1f} ms")
    t = time.perf_counter()
    cg.access_counts()
    print(f"  聚合访问日志         {(time.perf_counter()-t)*1000:8.1f} ms")
    print(f"\n  基准写入目录：{tmp}（可自行删除）")
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.exit(main())
