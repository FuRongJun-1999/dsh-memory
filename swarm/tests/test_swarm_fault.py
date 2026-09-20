# -*- coding: utf-8 -*-
"""test_swarm_fault.py · G5 实例级容错验收（心跳任务 2026-09-13）
透明容错口径：运行中强杀两个 --serve 实例子进程 → 协调器同线程重建重跑该轮
（轮次号幂等）→ 蜂群无感完成，终态/水位/对账与无故障基线一致。
说明：重试仍失败的 dead 分支已实现（outcomes 记 None、uptime 降、蜂群继续），
单机下确定性触发需在重建后的极窄时序窗内二次击杀，留长稳/跨机验证。
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from swarm.rust_codegen import generate_rust_project
from swarm.rust_swarm import make_swarm_config, build_rust_exe, run_swarm, verify_wal_signatures

pass_n = fail_n = 0


def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')


SOURCE = """问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：
1。道 新信任路径；
2。德 0.3；
3。若 信任值 大于 0.2，则 德 0.5；
4。止。
"""
SECRET = "验收密钥-蜂群G5容错"
ROUNDS = 6000

tmp = tempfile.mkdtemp(prefix="swarm_fault_")
proj = os.path.join(tmp, "proj")
gen = generate_rust_project(SOURCE, proj)
check("项目生成", gen["ok"])

INST = [{"id": f"实例{i}", "role": "peer", "trust": 0.1} for i in range(6)]
CFG = make_swarm_config(INST,
                        routes=[{"from": "实例0", "event_type": "gossip", "to": "*",
                                 "payload": "@trust", "level": 0}],
                        rounds=ROUNDS, shared_secret=SECRET)
exe = build_rust_exe(proj)

# ============ ① 基线：无故障一次跑 ============
print("=== ① 基线（无故障） ===")
wal_a = os.path.join(tmp, "a.jsonl")
rr_a = run_swarm(proj, CFG, wal_path=wal_a)
check("基线运行", rr_a["ok"], str(rr_a.get("stderr", ""))[:150])

# ============ ② 运行中强杀两个 --serve 实例 → 蜂群无感完成 ============
print("=== ② 运行中强杀两个实例子进程 ===")
wal_b = os.path.join(tmp, "b.jsonl")
cfg_path = os.path.join(proj, "swarm_fault.json")
with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump(CFG, f, ensure_ascii=False)
subprocess.run(["powershell", "-NoProfile", "-Command", "1"],
               capture_output=True, timeout=30)  # 预热 PowerShell
p = subprocess.Popen([exe, "swarm", "--config", cfg_path, "--wal", wal_b],
                     cwd=proj, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
time.sleep(1.0)  # 6000 轮约 3-4s，1s 时杀留足窗口
killed = []
for _ in range(2):
    q = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"(Get-CimInstance Win32_Process -Filter \"ParentProcessId={p.pid}\" "
         f"| Where-Object {{ $_.CommandLine -like '*--serve*' }}).ProcessId"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    pids = [x.strip() for x in q.stdout.split() if x.strip().isdigit()]
    pids = [x for x in pids if x not in killed]
    if pids and p.poll() is None:
        subprocess.run(["taskkill", "/PID", pids[0], "/F"],
                       capture_output=True, timeout=15)
        killed.append(pids[0])
    time.sleep(0.2)
check(f"强杀了 {len(killed)} 个实例子进程", len(killed) >= 1, str(killed))
_, _se = p.communicate(timeout=180)
check("蜂群完成（退出码 0，未被故障击穿）", p.returncode == 0, str(p.returncode))

# ============ ③ 透明性：容错后终态/验签与基线一致 ============
print("=== ③ 透明性比对 ===")
rr_b = run_swarm(proj, CFG, wal_path=wal_b)  # WAL 已完成 → 幂等聚合拿报告
check("重入幂等聚合", rr_b["ok"])
v_b = verify_wal_signatures(wal_b, SECRET)
check(f"WAL 全验签通过（{v_b['total']} 条）", v_b["all_valid"], f"bad={v_b['bad']}")
if rr_a["ok"] and rr_b["ok"]:
    fa = rr_a["report"]["final_states"]
    fb = rr_b["report"]["final_states"]
    check("六实例终态与基线一致（trust 逐项相等）",
          all(abs(fa[k]["trust"] - fb[k]["trust"]) < 1e-9 for k in fa),
          str({k: fb[k]["trust"] for k in fb}))
    check("gossip 水位一致（对账通过）",
          rr_b["report"]["gossip_consistent"] is True)
    check("健康评分满分（重试成功即透明）",
          all(abs(h["score"] - 1.0) < 1e-9
              for h in rr_b["report"]["health"].values()),
          str({k: round(v["score"], 4) for k, v in rr_b["report"]["health"].items()}))

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
