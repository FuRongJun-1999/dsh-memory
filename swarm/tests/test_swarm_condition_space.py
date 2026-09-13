# -*- coding: utf-8 -*-
"""test_swarm_condition_space.py · R2 条件空间卡验收（v0.7 · 2026-09-13）
覆盖：四要素齐备运行 + space_id 随快照持久 + 报告透出 / 缺要素拒绝（负路由）/
不带卡向后兼容。
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
SECRET = "验收密钥-蜂群R2条件空间"
CS = {"space_id": "swarm-acceptance-v1",
      "observation_position": "协调器视角（轮末聚合）",
      "observation_tool": "WAL 验签 + watermark 对账",
      "time_window": "2026-09-13 起验收周期",
      "existence_constraint": "单机多进程，纯 std 零依赖"}

tmp = tempfile.mkdtemp(prefix="swarm_cs_")
proj = os.path.join(tmp, "proj")
generate_rust_project(SOURCE, proj)
INST = [{"id": "实例甲", "role": "peer", "trust": 0.1, "symbols": {"信任值": 0.5}},
        {"id": "实例乙", "role": "peer", "trust": 0.2, "symbols": {"信任值": 0.5}}]

# ============ ① 四要素齐备：运行 + space_id 持久 ============
print("=== ① 四要素齐备 ===")
cfg = make_swarm_config(INST, rounds=2, shared_secret=SECRET, condition_space=CS)
wal = os.path.join(tmp, "a.jsonl")
rr = run_swarm(proj, cfg, wal_path=wal)
check("带条件空间卡运行", rr["ok"], str(rr.get("stderr", ""))[:150])
if rr["ok"]:
    check("报告透出 condition_space",
          rr["report"].get("condition_space") == CS["space_id"],
          str(rr["report"].get("condition_space")))
    with open(wal, encoding="utf-8") as f:
        snaps = [json.loads(x) for x in f if '"__snapshot__"' in x]
    check("space_id 随快照持久（切换日志不可遗忘载体）",
          all(s["payload"].get("cs") == CS["space_id"] for s in snaps),
          str([s["payload"].get("cs") for s in snaps]))
    v = verify_wal_signatures(wal, SECRET)
    check("含 cs 字段的快照行全验签（payload 扩展不动签名契约）", v["all_valid"])

# ============ ② 缺要素拒绝（负路由） ============
print("=== ② 缺要素拒绝 ===")
bad_cs = {k: v for k, v in CS.items() if k != "existence_constraint"}
cfg2 = make_swarm_config(INST, rounds=1, shared_secret=SECRET, condition_space=bad_cs)
rr2 = run_swarm(proj, cfg2, wal_path=os.path.join(tmp, "b.jsonl"))
check("缺 existence_constraint → 拒绝运行", not rr2["ok"],
      str(rr2.get("stderr", ""))[-120:])

# ============ ③ 不带卡向后兼容 ============
print("=== ③ 不带卡向后兼容 ===")
cfg3 = make_swarm_config(INST, rounds=1, shared_secret=SECRET)
rr3 = run_swarm(proj, cfg3, wal_path=os.path.join(tmp, "c.jsonl"))
check("不带卡运行", rr3["ok"])
if rr3["ok"]:
    check("报告无 condition_space 字段", "condition_space" not in rr3["report"])

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
