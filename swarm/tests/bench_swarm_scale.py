# -*- coding: utf-8 -*-
"""bench_swarm_scale.py · C1 并发规模扫描 + 事件吞吐基准（心跳任务 2026-09-13）
口径（run_swarm 端到端墙钟，含协调器 spawn 实例与 WAL 落盘）：
  ①规模扫描：无路由，实例数 N ∈ {1,4,16,32,64}，R 轮固定 → 每实例每轮摊薄。
    BSP 超步并行下摊薄应近似平稳（线程调度无瓶颈）；退化点即扩展上限证据。
  ②事件吞吐：1 源 fan-out 15 目标（15 路由），每轮 15 路由事件+15 ACK=30 事件，
    R 轮 → events/s（含快照行落盘成本，注明）。
产出：本脚本 stdout（可复跑）。
"""
import io
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
SECRET = "基准密钥-蜂群C1规模"

tmp = tempfile.mkdtemp(prefix="swarm_scale_")
proj = os.path.join(tmp, "proj")
gen = generate_rust_project(SOURCE, proj)
assert gen["ok"], gen

def run(n_inst, routes, rounds, tag):
    cfg = make_swarm_config(
        instances=[{"id": f"实例{i}", "role": "worker", "trust": 0.1} for i in range(n_inst)],
        routes=routes, rounds=rounds, shared_secret=SECRET)
    t0 = time.perf_counter()
    rr = run_swarm(proj, cfg, wal_path=os.path.join(tmp, f"wal_{tag}.jsonl"))
    dt = time.perf_counter() - t0
    assert rr["ok"], rr.get("stderr", "")[-300:]
    return dt, rr["report"]

# 预热（首次 cargo build 排除）
run(1, [], 1, "warmup")

# ============ ① 并发规模扫描 ============
print("=== ① 规模扫描（无路由，R=8 轮，端到端墙钟） ===")
print(f"{'N':>4} {'总耗时ms':>10} {'每实例每轮摊薄ms':>16}")
R = 8
thin = []
for n in (1, 4, 16, 32, 64):
    dt, _ = run(n, [], R, f"scale_{n}")
    per = dt / (n * R) * 1000
    thin.append(per)
    print(f"{n:>4} {dt*1000:>10.0f} {per:>16.2f}")
growth = thin[-1] / thin[0]
print(f"摊薄增长率 (64 vs 1 实例): {growth:.2f}×  （接近 1=线性扩展）")

# ============ ② 事件吞吐（fan-out） ============
print("\n=== ② 事件吞吐（16 实例，1 源 fan-out 15 目标，R=50） ===")
N, R2 = 16, 50
routes = [{"from": "实例0", "event_type": "广播", "to": f"实例{i}",
           "payload": "@trust", "level": 0} for i in range(1, N)]
dt, rep = run(N, routes, R2, "thru")
# 每轮：15 路由事件；ACK 从第 2 轮起（首轮目标无收件箱不 ACK，同旧测试口径）
total_events = len(routes) * R2 + len(routes) * (R2 - 1)
thru = total_events / dt
print(f"端到端 {dt*1000:.0f} ms，事件 {total_events}（路由{len(routes)*R2}+ACK{len(routes)*(R2-1)}，不含快照）")
print(f"吞吐: {thru:.0f} events/s；每轮摊薄 {dt/R2*1000:.1f} ms（含快照 sync_all）")
print(f"事件总数核对: 报告 events={rep['events']}（含 {R2} 快照 → {rep['events']-R2}=={total_events}）")
assert rep["events"] - R2 == total_events, "事件计数不符"

ok = growth < 3.0 and thru > 500
print(f"\n[{'✓' if ok else '✘'}] 扩展健康（摊薄增长<3×）且 吞吐>500 events/s")
print("  ⚠ 性能阈值断言，负载敏感（issue #30①）：套件并行跑时自动跳过"
      "（run_tests --jobs>1 → SKIP），单跑/串行全量才作数——失败先怀疑机器忙，非功能回归")
sys.exit(0 if ok else 1)
