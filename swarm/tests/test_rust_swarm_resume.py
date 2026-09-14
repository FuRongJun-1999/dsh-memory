# -*- coding: utf-8 -*-
"""test_rust_swarm_resume.py · B1 断点恢复验收（G1 · 心跳任务 2026-09-13）
覆盖：WAL 轮末快照落盘 / 分段跑(2+3)与一次跑(5)终态一致 / 恢复幂等
（已完成轮数≥目标直接聚合）/ 坏尾截断（篡改尾部→从快照恢复）/ 快照行
验签但不计入事件数 / HMAC 全链验签。
"""
import io
import json
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from swarm.rust_codegen import generate_rust_project
from swarm.rust_swarm import make_swarm_config, run_swarm, verify_wal_signatures

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
SECRET = "验收密钥-蜂群B1恢复"

tmp = tempfile.mkdtemp(prefix="swarm_resume_")
proj = os.path.join(tmp, "proj")
gen = generate_rust_project(SOURCE, proj)
check("项目生成", gen["ok"])

CFG = make_swarm_config(
    instances=[
        # 缺陷②修复后：信任值 是内建名（读 trust_value 寄存器）。旧写法同时给
        # trust 与 symbols{信任值} 属「无内建」时期的绕过手段；统一后 symbols 里的
        # 信任值 会归一为寄存器初值并覆盖 trust，故只保留 trust 驱动轨迹（0.9/1.0）。
        {"id": "实例甲", "role": "记录", "trust": 0.1},
        {"id": "实例乙", "role": "验证", "trust": 0.2},
    ],
    routes=[{"from": "实例甲", "event_type": "信任同步", "to": "实例乙",
             "payload": "@trust", "level": 0}],
    rounds=5, shared_secret=SECRET)

# ============ ① 基线：一次跑完 5 轮 ============
print("=== ① 基线：一次跑完 5 轮 ===")
wal_a = os.path.join(tmp, "events_a.jsonl")
rr_a = run_swarm(proj, CFG, wal_path=wal_a)
check("基线运行", rr_a["ok"], str(rr_a.get("stderr", ""))[:150])
fs_a = rr_a["report"]["final_states"] if rr_a["ok"] else {}

# ============ ② 分段跑：2 轮 + 续 3 轮（同一 WAL） ============
print("=== ② 分段跑(2+3) 终态应与一次跑(5) 一致 ===")
wal_b = os.path.join(tmp, "events_b.jsonl")
cfg2 = dict(CFG)
cfg2["rounds"] = 2
rr_b1 = run_swarm(proj, cfg2, wal_path=wal_b)
check("前段 2 轮运行", rr_b1["ok"], str(rr_b1.get("stderr", ""))[:150])
# 快照已落盘：每轮 1 条快照行
with open(wal_b, encoding="utf-8") as f:
    lines_b1 = [json.loads(x) for x in f if x.strip()]
snaps_b1 = [x for x in lines_b1 if x["type"] == "__snapshot__"]
check("每轮末有快照行(2 轮=2 快照)", len(snaps_b1) == 2, str(len(snaps_b1)))
check("快照行记录轮号连续(1,2)",
      [s["round"] for s in snaps_b1] == [1, 2],
      str([s["round"] for s in snaps_b1]))
# 恢复：同一 WAL 补跑到 5 轮
rr_b2 = run_swarm(proj, CFG, wal_path=wal_b)
check("续跑 3 轮运行", rr_b2["ok"], str(rr_b2.get("stderr", ""))[:150])
if rr_b2["ok"] and rr_a["ok"]:
    fs_b = rr_b2["report"]["final_states"]
    check("续跑终态 trust 与一次跑一致(甲 0.9/乙 1.0)",
          abs(fs_b["实例甲"]["trust"] - fs_a["实例甲"]["trust"]) < 1e-9
          and abs(fs_b["实例乙"]["trust"] - fs_a["实例乙"]["trust"]) < 1e-9,
          json.dumps({k: v.get("trust") for k, v in fs_b.items()},
                     ensure_ascii=False))
    check("续跑事件总数 = 基线(事件史含快照, 恢复不丢不重)",
          rr_b2["report"]["events"] == rr_a["report"]["events"],
          f"resume={rr_b2['report']['events']} base={rr_a['report']['events']}")

# ============ ③ 恢复幂等：已完成 ≥ 目标 → 直接聚合不重跑 ============
print("=== ③ 恢复幂等 ===")
rr_b3 = run_swarm(proj, CFG, wal_path=wal_b)
check("重入同 WAL(5/5 完成) 直接聚合成功", rr_b3["ok"])
if rr_b3["ok"]:
    check("幂等报告事件数不变",
          rr_b3["report"]["events"] == rr_b2["report"]["events"])
    check("幂等终态不变",
          abs(rr_b3["report"]["final_states"]["实例乙"]["trust"] - 1.0) < 1e-9)

# ============ ④ 坏尾截断：篡改最后一行 → 从快照恢复 ============
print("=== ④ 坏尾截断（篡改检测） ===")
with open(wal_b, encoding="utf-8") as f:
    good_lines = f.readlines()
tampered = json.loads(good_lines[-1])
tampered["payload"] = "{}"
good_lines[-1] = json.dumps(tampered, ensure_ascii=False) + "\n"
wal_c = os.path.join(tmp, "events_c.jsonl")
with open(wal_c, "w", encoding="utf-8") as f:
    f.writelines(good_lines)
rr_c = run_swarm(proj, CFG, wal_path=wal_c)
check("坏尾后恢复运行成功（截断最后快照，从第 4 轮续跑）", rr_c["ok"])
if rr_c["ok"]:
    fs_c = rr_c["report"]["final_states"]
    check("坏尾恢复终态仍一致(甲 0.9/乙 1.0)",
          abs(fs_c["实例甲"]["trust"] - 0.9) < 1e-9
          and abs(fs_c["实例乙"]["trust"] - 1.0) < 1e-9)

# ============ ⑤ 快照行验签：全链验签通过但不计入事件数 ============
print("=== ⑤ WAL 验签口径 ===")
v = verify_wal_signatures(wal_b, SECRET)
check(f"WAL 全部验签通过(含快照行, verified={v['verified']})", v["all_valid"],
      f"bad={v['bad']}")
with open(wal_b, encoding="utf-8") as f:
    n_snap = sum(1 for x in f if '"__snapshot__"' in x)
check("事件计数不含快照行",
      v["total"] == rr_b2["report"]["events"] - n_snap,
      f"total={v['total']} events={rr_b2['report']['events']} snaps={n_snap}")

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
