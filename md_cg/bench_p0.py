# -*- coding: utf-8 -*-
"""md 认知图 P0 性能基准 · 把「无 SQL 索引」的代价变成数字

文档第 8 节把性能列为风险但没有数字。这里量化三件事：
  1. T0 条件路由命中（读一个桶）vs T2 全量 LIKE（读全部候选）的差距
     —— 这决定条件路由到底值多少；**命中与未命中必须分开统计**，
     混进一个中位数会互相抵消，看不出任何东西
  2. md 条件路由（按调用方给出的正确情境）vs 朴素全库读盘扫描
     —— 无索引的上界代价；并标注小库上测不准的原因（见下方 caveat）
  3. 写入吞吐 / 索引重建 / compact 耗时

库来源：`md_cg.test_p0` 生成的自建 md 文档记忆库（336 节点）。先跑 test_p0 再跑本基准。
（旧版第 2 节对比 aeis/sqlite 的 search_content；本仓库按「用新的 md 文档记忆库做验证」
改为 md 原生参照，不再依赖外部数据库。）

caveat：336 节点是小库，朴素读盘扫描受 OS 页缓存保护（336 个小文件 ≈ 7 ms），
此时索引收益被低估；结论要到大库（P4 全量切换前）复测才算数。

跑法：python -m md_cg.bench_p0
"""
import os
import sys
import time
import shutil
import statistics

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mdcg import MdCG

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(HERE, "_md_cg_p0")

# (查询词, 该词所属域)：第 2 节用各自的域做情境（模拟「知道情境的调用方」）；
# 第 1 节固定用计算机科学域，故意包含 8 个未命中查询，用来量「路由未命中」的代价。
QUERIES = [("能量守恒", "物理学"), ("二分查找", "计算机科学"), ("细胞呼吸", "生物学"),
           ("贝塞尔不等式", "数学"), ("牛顿第二定律", "物理学"),
           ("光合作用", "生物学"), ("熵增", "物理学"),
           ("内力与截面法", "机械工程"), ("机会成本", "经济学"),
           ("事务隔离", "计算机科学")]


def timeit(fn, repeat=5):
    ts = []
    for _ in range(repeat):
        t = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t) * 1000)
    return statistics.median(ts), min(ts), max(ts)


def main():
    if not os.path.isdir(ROOT):
        print(f"未找到 md 库 {ROOT}，请先跑 python -m md_cg.test_p0")
        return 1
    cg = MdCG(ROOT)
    n = len(cg.index["nodes"])
    print(f"库规模：{n} 节点，{len(cg.index['buckets'])} 条件分区\n")

    # ---- 1. 条件路由 vs 全量（固定情境：命中/未命中的代价分开看）----
    print("[检索延迟] 中位数 ms（5 次）· 固定 context=计算机科学")
    print(f"  {'query':<14}{'带 context':>12}{'无 context':>12}{'加速比':>9}  扫描量  命中层级")
    hit, miss = [], []
    ctx = {"tags": ["domain:计算机科学"]}
    for q, _dom in QUERIES:
        _r0, m0 = cg.search(q, layer="knowledge", k=10, context=ctx, record=False)
        t0 = timeit(lambda: cg.search(q, layer="knowledge", k=10, context=ctx,
                                      record=False))[0]
        t2 = timeit(lambda: cg.search(q, layer="knowledge", k=10, context=None,
                                      record=False))[0]
        (hit if m0["tier"].startswith(("T0", "T1")) else miss).append(t2 / t0 if t0 else 0)
        print(f"  {q:<14}{t0:>11.1f}{t2:>12.1f}{t2/t0 if t0 else 0:>8.1f}x"
              f"  {m0['scanned']:>5}/{n}  {m0['tier']}")
    if hit:
        print(f"  → 路由命中（{len(hit)}/{len(QUERIES)} 查询）中位加速 "
              f"{statistics.median(hit):.1f}x")
    if miss:
        print(f"  → 路由未命中（{len(miss)}/{len(QUERIES)} 查询）中位 "
              f"{statistics.median(miss):.2f}x —— 白付一次桶扫描的代价")
    print()

    # ---- 2. 条件路由（情境正确）vs 全量 vs 朴素全库读盘扫描 ----
    # 朴素参照：每个查询都把全部节点文件读出来做一次子串匹配（无索引的代价上限）
    def brute_force(q):
        hits = []
        for e in cg.index["nodes"].values():
            try:
                with open(os.path.join(ROOT, e["path"]), encoding="utf-8") as f:
                    if q in f.read():
                        hits.append(e["path"])
            except OSError:
                pass
        return hits

    print("[情境正确时的代价对比] 同查询集中位数 ms")
    print(f"  {'query':<14}{'T0 路由':>10}{'T2 全量':>10}{'朴素读盘':>10}{'层级':>6}  扫描量")
    t0s, t2s, bfs = [], [], []
    for q, dom in QUERIES:
        qctx = {"tags": [f"domain:{dom}"]}
        _r, m = cg.search(q, layer="knowledge", k=10, context=qctx, record=False)
        a = timeit(lambda: cg.search(q, layer="knowledge", k=10, context=qctx,
                                     record=False))[0]
        b = timeit(lambda: cg.search(q, layer="knowledge", k=10, context=None,
                                     record=False))[0]
        c = timeit(lambda: brute_force(q))[0]
        t0s.append(a)
        t2s.append(b)
        bfs.append(c)
        print(f"  {q:<14}{a:>10.1f}{b:>10.1f}{c:>10.1f}{m['tier'][:2]:>6}"
              f"  {m['scanned']:>5}/{n}")
    print(f"  中位：T0 路由 {statistics.median(t0s):.1f} ms | T2 全量 "
          f"{statistics.median(t2s):.1f} ms | 朴素全库读盘 {statistics.median(bfs):.1f} ms")
    print(f"  → T0 相对 T2 全量 {statistics.median(t2s)/statistics.median(t0s):.1f}x"
          f"，相对朴素读盘 {statistics.median(bfs)/statistics.median(t0s):.1f}x")
    print("  → 注：小库（336 节点）上朴素读盘被 OS 页缓存保护，索引收益被低估，"
          "大库复测才作数\n")

    # ---- 3. 写入 / 维护 ----
    print("[写入与维护] ms")
    tmp = ROOT + "_bench"
    if os.path.isdir(tmp):
        shutil.rmtree(tmp)
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
    # 基准自己的临时库用完即清，不给工作区留垃圾
    cgw.close()
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    # 用 reconfigure 而非「包一层 TextIOWrapper」：后者在 stdout 重定向到文件时
    # 会在解释器退出阶段丢缓冲（实测只落盘 444 字节），CI 里会看不到结果。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
