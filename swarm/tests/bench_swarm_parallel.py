# -*- coding: utf-8 -*-
"""bench_swarm_parallel.py · B2 轮内并行加速比基准（G2 · C1 口径可复跑产物）
口径：同一项目、无路由（轮内实例完全独立）。对比
  串行参照 = 1 实例 × MEASURE_ROUNDS 轮 总耗时 × N（理论串行墙钟）
  并行实际 = N 实例 × MEASURE_ROUNDS 轮 总耗时
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

── 第三轮（2026-11-08，issue #831）：把测量周期拉离噪声区 ────────────
#302 的「多次采样取中位」做得对，但**放错了地方**：它只增加样本数，没有改变
每个样本本身的信噪比。CI 实测（run 42464773464，同一 commit）：

    串行参照 30 ms（⇒ 单实例中位仅 3.75 ms）
    逐次加速比 4.09× 1.69× 0.69× 4.56× 0.31×
    ⇒ 反推 tN 落在 6.6~96.8 ms，**极差 14.7×**

十几个毫秒的任务里，进程唤醒与 CPU 抢占的固定开销压过实际载荷，tN 的分布
没有稳定中心 —— 中位数落在哪一侧取决于当轮调度。此时中位口径**稳定地翻车**，
而且它翻出来的是「运气」，不是「代码退化」。

根治不是换聚合函数（实测本机对同一批样本做 4000 次 bootstrap，中位/先中位
再除/MAD 截尾三种口径翻盘率都是 0 —— 它们在本机一样好，差别只在 CI 那种
噪声压顶的场景，而那时**没有一种聚合能救**）。根治是让单次测量本身就稳：

    R = 4  → tN 极差 1.84×，中位 3.32×
    R = 40 → tN 极差 1.4~1.6×，中位 3.70~4.34×，最差一次 2.81×

故引入 MEASURE_ROUNDS = 40（**只影响测量，不改载荷语义**），REPS 同步 5→9。
阈值**仍是 2×，未放宽**；判定**仍是中位数**，未改成 best-of（#302 对
best-of 的反对理由依然成立，故 best 与 tN 极差只作诊断读数打印）。
代价：一轮约 2s，相对 cargo 预热可接受。
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
#: 载荷轮数（**语义常量**，与 #302 基线逐位一致，G1d 钉住它）。
#: 注意：它不是实际测量的轮数——见下方 MEASURE_ROUNDS（#831）。
N, R = 8, 4

#: 测量用的轮数（2026-11-08，issue #831）。**与载荷语义无关**，只为把测量
#: 周期拉离调度噪声区。
#:
#: 病根：R=4 时单实例只要 ~3.75ms（CI 实测串行参照 30ms / 8），并行侧 tN
#: 在 6.6~96.8ms 之间摆动（**极差 14.7×**）。十几个毫秒的任务里，进程唤醒
#: 与 CPU 抢占的固定开销占了主导，中位数落在哪一侧纯看当轮调度——此时
#: 任何固定阈值断言都会翻车，且**翻不出「代码退化了」这个结论**（它翻的
#: 是运气）。实测同一批样本把轮数从 4 提到 40：tN 极差 1.84×→1.4~1.6×，
#: 中位加速比 3.32×→3.70~4.34×，且最差一次仍有 2.81×（阈值 2.0）。
#: 代价：一轮 9 次采样约 2s，相对 cargo 预热可接受。
MEASURE_ROUNDS = 40

#: 采样重复次数（issue #302）：每次采一对 (t1, tN)，逐次算加速比后取中位数。
#: 2026-11-08（issue #831）由 5 提到 9：5 次时中位数=第 3 小，只要 3 个样本被
#: 拖累就翻盘；9 次时中位数是第 5 小，需 5 个样本同时被拖累才能翻盘。代价约
#: 9×(t1+tN) ≈ 0.6s，相对 cargo 预热仍可忽略。
REPS = 9
#: 加速比下限（**未放宽**，与旧口径逐位一致）。
THRESHOLD = 2.0


def speedup_of(t1, tN, n=N):
    """单次观测的加速比 = 串行参照 (t1×N) / 并行实际 tN。"""
    return (t1 * n) / tN


def robust_speedup(pairs, n=N):
    """多次观测的**稳健**加速比：逐次加速比的**中位数**（理由见文件头注释）。"""
    return statistics.median([speedup_of(a, b, n) for a, b in pairs])


def best_speedup(pairs, n=N):
    """最好一次观测的加速比（只作**读数**展示，不参与判定）。"""
    return max(speedup_of(a, b, n) for a, b in pairs)


def noise_ratio(pairs):
    """并行侧 tN 的极差（max/min）——只作诊断读数，不参与判定。"""
    tNs = [b for _, b in pairs]
    lo = min(tNs)
    return (max(tNs) / lo) if lo > 0 else float("inf")


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
            routes=[], rounds=MEASURE_ROUNDS, shared_secret=SECRET)
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
          % (MEASURE_ROUNDS, statistics.median(t1s) * 1000, min(t1s) * 1000,
             max(t1s) * 1000, max(t1s) / min(t1s)))
    print("%d 实例 %d 轮: 中位 %.0f ms（%.0f~%.0f ms，极差 %.2f×）"
          % (N, MEASURE_ROUNDS, statistics.median(tNs) * 1000, min(tNs) * 1000,
             max(tNs) * 1000, max(tNs) / min(tNs)))
    print("串行参照 (%d×单实例中位): %.0f ms" % (N, statistics.median(t1s) * N * 1000))
    print("逐次加速比: %s" % "  ".join("%.2f×" % x for x in ratios))
    print("稳健加速比(中位): %.2f×  （理论上限 ~%d×，管道往返阻塞 IO）" % (speedup, N))
    print("每轮每实例摊薄: %.1f ms"
          % (statistics.median(tNs) / (N * MEASURE_ROUNDS) * 1000))

    ok = verdict(speedup)
    print()
    # 诊断读数（2026-11-08，issue #831）：best 与 tN 极差只**展示**，不改判定。
    # 刻意不用 best 参与判定——#302 已论证「只看 best 等于偷偷放宽阈值」。
    print("（读数）最好一次 %.2f× / 并行侧 tN 极差 %.2f×"
          % (best_speedup(pairs), noise_ratio(pairs)))
    print("[%s] 稳健加速比 %.2f× > %.1f（%d 次采样取中位）"
          % ("✓" if ok else "✘", speedup, THRESHOLD, REPS))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
