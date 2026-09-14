# -*- coding: utf-8 -*-
"""test_rust_swarm_kill.py · C1 恢复演练：强杀协调器后重入续跑（心跳任务 2026-09-13）
A6 验收口径第 1 条硬核版：kill 落在任意中途点（含「事件已写、快照未写」的半轮），
重入同 WAL 跑到完成 → 终态/HMAC 链/事件结构与一次跑完一致。
前置加固：B1 回滚规则——快照=提交点，快照后未提交轮次整体回滚（防重放+重跑重复）。
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
from swarm.rust_swarm import (make_swarm_config, run_swarm,
                             verify_wal_signatures)

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
SECRET = "验收密钥-蜂群C1击杀"
ROUNDS = 600  # 每轮 ~8ms：sleep(1.0) 时 K≈120，确保 kill 落在真实中途点

tmp = tempfile.mkdtemp(prefix="swarm_kill_")
proj = os.path.join(tmp, "proj")
gen = generate_rust_project(SOURCE, proj)
check("项目生成", gen["ok"])

CFG = make_swarm_config(
    instances=[
        {"id": "实例甲", "role": "记录", "trust": 0.1},
        {"id": "实例乙", "role": "验证", "trust": 0.2},
        {"id": "实例丙", "role": "观察", "trust": 0.1},
        {"id": "实例丁", "role": "备份", "trust": 0.2},
    ],
    routes=[{"from": "实例甲", "event_type": "信任同步", "to": "实例乙",
             "payload": "@trust", "level": 0}],
    rounds=ROUNDS, shared_secret=SECRET)

# ============ ① 基线：一次跑完（另一 WAL） ============
print("=== ① 基线：一次跑完 ===")
wal_a = os.path.join(tmp, "events_a.jsonl")
rr_a = run_swarm(proj, CFG, wal_path=wal_a)
check("基线运行", rr_a["ok"], str(rr_a.get("stderr", ""))[:150])

# ============ ② 强杀：Popen 启动 → sleep → kill ============
print("=== ② 强杀协调器（中途点不确定=演练真实性） ===")
wal_b = os.path.join(tmp, "events_b.jsonl")
cfg_path = os.path.join(proj, "swarm_kill.json")
with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump(CFG, f, ensure_ascii=False)
exe = None
for cand in (os.path.join(proj, "target", "release", "protocol_vm.exe"),
             os.path.join(proj, "target", "release", "protocol_vm")):
    if os.path.exists(cand):
        exe = cand
        break
check("可执行文件在位", exe is not None, str(exe))
p = subprocess.Popen([exe, "swarm", "--config", cfg_path, "--wal", wal_b],
                     cwd=proj, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
# 轮询等快照轮 ≥50 即杀（B2 并行后每轮 ~1.6ms，固定 sleep 无法确定性命中中途）
target_round = 50
k = 0
while k < target_round and p.poll() is None:
    time.sleep(0.02)
    try:
        with open(wal_b, encoding="utf-8") as f:
            for line in f:
                if '"__snapshot__"' in line:
                    k = json.loads(line)["round"]
    except (FileNotFoundError, json.JSONDecodeError):
        pass
p.kill()
p.wait()
time.sleep(0.5)  # 子实例因管道关闭退场（serve.rs:268）的余量

with open(wal_b, encoding="utf-8") as f:
    lines = [json.loads(x) for x in f if x.strip()]
snaps_k = [x for x in lines if x["type"] == "__snapshot__"]
k = snaps_k[-1]["round"] if snaps_k else 0
check(f"kill 时快照轮 K={k}（1 ≤ K，真实中途点）", k >= 1, f"rows={len(lines)}")

# ============ ③ 重入：同 WAL 跑到完成 ============
print("=== ③ 重入续跑 ===")
rr_b = run_swarm(proj, CFG, wal_path=wal_b)
check("恢复续跑完成", rr_b["ok"], str(rr_b.get("stderr", ""))[:200])

# ============ ④ 结构不变量：kill 恢复 = 基线 ============
print("=== ④ 结构不变量比对 ===")
v_a = verify_wal_signatures(wal_a, SECRET)
v_b = verify_wal_signatures(wal_b, SECRET)
check("kill 恢复 WAL 全验签通过", v_b["all_valid"], f"bad={v_b['bad']}")
check(f"事件计数=基线({v_a['total']})", v_b["total"] == v_a["total"],
      f"a={v_a['total']} b={v_b['total']}")
with open(wal_b, encoding="utf-8") as f:
    snaps_b = [json.loads(x)["round"] for x in f
               if '"__snapshot__"' in x]
check(f"快照轮号连续 1..{ROUNDS}（无重复无缺失）",
      snaps_b == list(range(1, ROUNDS + 1)),
      f"n={len(snaps_b)} head={snaps_b[:3]} tail={snaps_b[-3:]}")
if rr_b["ok"] and rr_a["ok"]:
    fs_a, fs_b = rr_a["report"]["final_states"], rr_b["report"]["final_states"]
    same = all(abs(fs_a[i]["trust"] - fs_b[i]["trust"]) < 1e-9
               for i in fs_a)
    check("四实例终态 trust 与基线一致", same,
          json.dumps({k2: fs_b[k2]["trust"] for k2 in fs_b}))
    check("信任聚合与基线一致(T_avg)",
          abs(rr_a["report"]["trust"]["T_avg"]
              - rr_b["report"]["trust"]["T_avg"]) < 1e-9)
    check("无重复事件(事件总数=基线)",
          rr_b["report"]["events"] == rr_a["report"]["events"],
          f"b={rr_b['report']['events']} a={rr_a['report']['events']}")

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
