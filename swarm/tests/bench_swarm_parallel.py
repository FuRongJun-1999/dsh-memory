# -*- coding: utf-8 -*-
"""bench_swarm_parallel.py · B2 轮内并行加速比基准（G2 · C1 口径可复跑产物）
口径：同一项目、无路由（轮内实例完全独立）。对比
  串行参照 = 1 实例 × R 轮 总耗时 × N（理论串行墙钟）
  并行实际 = N 实例 × R 轮 总耗时
加速比 = 串行参照 / 并行实际。BSP 超步并行期望接近 N（管道往返是阻塞 IO）。
产出：本脚本 stdout（可复跑）；断言加速比 > 2（宽松下限防环境抖动误报）。
"""
import io
import json
import os
import sys
import tempfile
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
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

tmp = tempfile.mkdtemp(prefix="swarm_bench_")
proj = os.path.join(tmp, "proj")
gen = generate_rust_project(SOURCE, proj)
assert gen["ok"], gen

def bench(n_inst, tag):
    cfg = make_swarm_config(
        instances=[{"id": f"实例{i}", "role": "worker", "trust": 0.1} for i in range(n_inst)],
        routes=[], rounds=R, shared_secret=SECRET)
    t0 = time.perf_counter()
    rr = run_swarm(proj, cfg, wal_path=os.path.join(tmp, f"wal_{tag}.jsonl"))
    dt = time.perf_counter() - t0
    assert rr["ok"], rr.get("stderr", "")[-300:]
    return dt

# 预热（首次 cargo build 排除在计时外）
bench(1, "warmup")

t1 = bench(1, "serial")
tN = bench(N, "parallel")
serial_ref = t1 * N
speedup = serial_ref / tN
print(f"单实例 {R} 轮: {t1*1000:.0f} ms")
print(f"{N} 实例 {R} 轮: {tN*1000:.0f} ms")
print(f"串行参照 ({N}×{t1*1000:.0f}ms): {serial_ref*1000:.0f} ms")
print(f"加速比: {speedup:.2f}×  （理论上限 ~{N}×，管道往返阻塞 IO）")
print(f"每轮每实例摊薄: {tN/(N*R)*1000:.1f} ms")

ok = speedup > 2
print(f"\n[{'✓' if ok else '✘'}] 加速比 > 2（宽松下限）")
sys.exit(0 if ok else 1)
