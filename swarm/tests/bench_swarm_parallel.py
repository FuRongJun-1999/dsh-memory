# -*- coding: utf-8 -*-
"""bench_swarm_parallel.py · B2 轮内并行加速比基准（G2 · C1 口径可复跑产物）
口径：同一项目、无路由（轮内实例完全独立）。对比
  串行参照 = 1 实例 × R 轮 总耗时 × N（理论串行墙钟）
  并行实际 = N 实例 × R 轮 总耗时
加速比 = 串行参照 / 并行实际。BSP 超步并行期望接近 N（管道往返是阻塞 IO）。
产出：本脚本 stdout（可复跑）；断言**稳健**加速比 > 2（宽松下限）。

── 判定口径（2026-10-14，issue #302）────────────────────────────────
旧口径是**单样本**墙钟比 + 2× 硬阈值：t1 与 tN 各只测一次，噪声直接进判定。
issue #302 实测同一 commit 同一机器在 1.69×~3.64× 之间波动、跨越阈值。单样本
毫秒级基准本身抖动幅度就足以跨越 2×，故旧口径**不是**「防环境抖动误报」，而是
把抖动直接接到了退出码上。

现口径：**REPS 次交替采样**（每次先测 t1 再测 tN —— 交替是为了让同一段负载同时
落在分子与分母上，而不是只砸中一侧），逐次算加速比，取**中位数**判定。中位数对
单次离群不敏感，故单侧抖动不再翻盘；同时阈值**未放宽**（仍 2×）。

为何取中位数而非均值/最小值：均值仍被单次离群拖动；最小值（best-of）会系统性
抬高估计——分子取最小、分母取最小 ⇒ 高估加速比，等于偷偷放宽阈值。

诚实边界（功率面）：中位数也意味着**单次**真实回退会被多数正常样本盖住 —— 这是
换取稳定性的代价，不是「修好了」。持续回退仍会被判红（多数样本位移）。若需恢复
对单次回退的敏感性，应改趋势判据（与本地上次快照比不劣化），属验收口径变更。

另注：调度侧已把本件列入 run_tests._SERIAL_ONLY（并行跑自动 SKIP、串行正常跑）——
那是针对「与其它测试抢 CPU」这一**独立的、量级更大**的噪声源；本件改的是**单样本**
这一构造面。两者互补，故 _SERIAL_ONLY 保持不动。
"""
import io
import os
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from swarm.rust_codegen import generate_rust_project
from swarm.rust_swarm import make_swarm_config, run_swarm

SOURCE = """问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：
1。道 新信任路径；
2。德 0.3；
3。若 信任值 大于 0.2，则 德 0.5；
4。止。
"""
SECRET = "基准密钥-蜂群B2并行"
N, R = 8, 4

#: 采样重复次数（issue #302）：每次采一对 (t1, tN)，逐次算加速比后取中位数。
#: 5 次的代价约 5×(t1+tN) ≈ 0.3s，相对 cargo 预热可忽略。
REPS = 5
#: 加速比下限（**未放宽**，与旧口径逐位一致）。
THRESHOLD = 2.0


def speedup_of(t1, tN, n=N):
    """单次观测的加速比 = 串行参照 (t1×N) / 并行实际 tN。"""
    return (t1 * n) / tN


def robust_speedup(pairs, n=N):
    """多次观测的**稳健**加速比：逐次加速比的**中位数**（理由见文件头注释）。"""
    return statistics.median([speedup_of(a, b, n) for a, b in pairs])


def verdict(speedup, threshold=THRESHOLD):
    """判定：加速比**严格大于**下限。边界值本身不算过（与旧口径 > 一致）。"""
    return speedup > threshold


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    tmp = tempfile.mkdtemp(prefix="swarm_bench_")
    proj = os.path.join(tmp, "proj")
    gen = generate_rust_project(SOURCE, proj)
    assert gen["ok"], gen

    def bench(n_inst, tag):
        cfg = make_swarm_config(
            instances=[{"id": "实例%d" % i, "role": "worker", "trust": 0.1}
                       for i in range(n_inst)],
            routes=[], rounds=R, shared_secret=SECRET)
        t0 = time.perf_counter()
        rr = run_swarm(proj, cfg, wal_path=os.path.join(tmp, "wal_%s.jsonl" % tag))
        dt = time.perf_counter() - t0
        assert rr["ok"], rr.get("stderr", "")[-300:]
        return dt

    # 预热（首次 cargo build 排除在计时外）
    bench(1, "warmup")

    # 交替采样：每一轮先 t1 后 tN，使同一段负载同时落在分子与分母上
    pairs = []
    for i in range(REPS):
        t1 = bench(1, "serial%d" % i)
        tN = bench(N, "parallel%d" % i)
        pairs.append((t1, tN))
        print("第 %d 次: 单实例 %.0f ms / %d 实例 %.0f ms / 加速比 %.2f×"
              % (i + 1, t1 * 1000, N, tN * 1000, speedup_of(t1, tN)))

    t1s = [a for a, _ in pairs]
    tNs = [b for _, b in pairs]
    ratios = [speedup_of(a, b) for a, b in pairs]
    speedup = robust_speedup(pairs)
    print()
    print("单实例 %d 轮: 中位 %.0f ms（%.0f~%.0f ms，极差 %.2f×）"
          % (R, statistics.median(t1s) * 1000, min(t1s) * 1000, max(t1s) * 1000,
             max(t1s) / min(t1s)))
    print("%d 实例 %d 轮: 中位 %.0f ms（%.0f~%.0f ms，极差 %.2f×）"
          % (N, R, statistics.median(tNs) * 1000, min(tNs) * 1000, max(tNs) * 1000,
             max(tNs) / min(tNs)))
    print("串行参照 (%d×单实例中位): %.0f ms" % (N, statistics.median(t1s) * N * 1000))
    print("逐次加速比: %s" % "  ".join("%.2f×" % x for x in ratios))
    print("稳健加速比(中位): %.2f×  （理论上限 ~%d×，管道往返阻塞 IO）" % (speedup, N))
    print("每轮每实例摊薄: %.1f ms" % (statistics.median(tNs) / (N * R) * 1000))

    ok = verdict(speedup)
    print()
    print("[%s] 稳健加速比 %.2f× > %.1f（%d 次采样取中位）"
          % ("✓" if ok else "✘", speedup, THRESHOLD, REPS))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
