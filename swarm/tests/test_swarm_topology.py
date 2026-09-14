# -*- coding: utf-8 -*-
"""test_swarm_topology.py · G4a 拓扑枚举+角色推导验收（心跳任务 2026-09-13）
覆盖：三种拓扑角色推导（hierarchical 首实例 queen / centralized coordinator /
mesh 全 peer）/ 缺省向后兼容（未指定保持用户声明）/ 未知拓扑报错 /
gossip 与拓扑共存。
"""
import io
import json
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from swarm.rust_codegen import generate_rust_project
from swarm.rust_swarm import make_swarm_config, run_swarm

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
SECRET = "验收密钥-蜂群G4a拓扑"

tmp = tempfile.mkdtemp(prefix="swarm_topo_")
proj = os.path.join(tmp, "proj")
gen = generate_rust_project(SOURCE, proj)
check("项目生成", gen["ok"])

INST = [
    {"id": "实例甲", "role": "记录", "trust": 0.1},
    {"id": "实例乙", "role": "验证", "trust": 0.2},
    {"id": "实例丙", "role": "观察", "trust": 0.2},
]


def run_topo(topology, tag, routes=None, rounds=1):
    cfg = make_swarm_config(INST, routes=routes, rounds=rounds,
                            shared_secret=SECRET, topology=topology)
    rr = run_swarm(proj, cfg, wal_path=os.path.join(tmp, f"wal_{tag}.jsonl"))
    return rr


# ============ ① hierarchical：首实例 queen ============
print("=== ① hierarchical ===")
rr = run_topo("hierarchical", "hi")
check("hierarchical 运行", rr["ok"], str(rr.get("stderr", ""))[:150])
if rr["ok"]:
    check("拓扑透出 hierarchical", rr["report"]["topology"] == "hierarchical")
    check("角色推导：甲=queen 乙丙=worker",
          rr["report"]["roles"] == {"实例甲": "queen", "实例乙": "worker",
                                    "实例丙": "worker"},
          str(rr["report"]["roles"]))

# ============ ② centralized + mesh ============
print("=== ② centralized / mesh ===")
rr = run_topo("centralized", "ce")
if rr["ok"]:
    check("centralized：甲=coordinator 其余 worker",
          rr["report"]["roles"]["实例甲"] == "coordinator"
          and rr["report"]["roles"]["实例乙"] == "worker")
rr = run_topo("mesh", "me")
if rr["ok"]:
    check("mesh：全部 peer", set(rr["report"]["roles"].values()) == {"peer"})

# ============ ③ 缺省向后兼容 + 未知拓扑报错 ============
print("=== ③ 缺省与校验 ===")
rr = run_topo("", "def")
check("缺省拓扑运行", rr["ok"])
if rr["ok"]:
    check("未指定拓扑：保持用户声明 role",
          rr["report"]["roles"] == {"实例甲": "记录", "实例乙": "验证",
                                    "实例丙": "观察"},
          str(rr["report"]["roles"]))
rr = run_topo("环形", "bad")
check("未知拓扑 → 运行失败（报错）", not rr["ok"],
      str(rr.get("stderr", ""))[-100:])

# ============ ④ hierarchical + gossip 共存 ============
print("=== ④ 拓扑 + gossip 共存 ===")
rr = run_topo("hierarchical", "hg",
              routes=[{"from": "实例乙", "event_type": "gossip", "to": "*",
                       "payload": "@trust", "level": 0}], rounds=2)
check("hierarchical + gossip 运行", rr["ok"], str(rr.get("stderr", ""))[:150])
if rr["ok"]:
    check("角色保持 queen/worker + gossip 水位一致",
          rr["report"]["roles"]["实例甲"] == "queen"
          and rr["report"]["gossip_consistent"] is True
          and rr["report"]["gossip"].get("实例甲") == 2
          and rr["report"]["gossip"].get("实例丙") == 2,
          str(rr["report"]["gossip"]))

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
