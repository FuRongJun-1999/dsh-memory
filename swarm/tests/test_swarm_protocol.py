# -*- coding: utf-8 -*-
"""test_swarm_protocol.py · R3 protocol 拓扑验收（v0.7 · 2026-09-13）
覆盖：四角色推导（primary/verifier/arbiter/recorder/worker）/ verifier 子进程
重放 primary 输入逐位复算（recalc_checked=rounds, mismatches=0）/ 复算不改终态 /
混合 topology+gossip 共存。
"""
import io
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
SECRET = "验收密钥-蜂群R3复算"
tmp = tempfile.mkdtemp(prefix="swarm_proto_")
proj = os.path.join(tmp, "proj")
generate_rust_project(SOURCE, proj)
INST = [{"id": f"实例{i}", "role": "x", "trust": 0.1, "symbols": {"信任值": 0.5}}
        for i in range(5)]

# ============ ① protocol 拓扑：四角色推导 + 逐位复算 ============
print("=== ① protocol 四角色 + 逐位复算 ===")
cfg = make_swarm_config(INST,
                        routes=[{"from": "实例0", "event_type": "gossip", "to": "*",
                                 "payload": "@trust", "level": 0}],
                        rounds=5, shared_secret=SECRET, topology="protocol")
wal = os.path.join(tmp, "a.jsonl")
rr = run_swarm(proj, cfg, wal_path=wal)
check("protocol 蜂群运行", rr["ok"], str(rr.get("stderr", ""))[:150])
if rr["ok"]:
    roles = rr["report"]["roles"]
    check("四角色推导正确",
          roles == {"实例0": "primary", "实例1": "verifier", "实例2": "arbiter",
                    "实例3": "recorder", "实例4": "worker"},
          str(roles))
    rec = rr["report"]["recalc"]
    check(f"verifier 每轮逐位复算（checked=5）", rec["checked"] == 5, str(rec))
    check("复算零不一致（确定性 VM：同输入必同终态）", rec["mismatches"] == 0, str(rec))
    check("报告透出 topology=protocol",
          rr["report"]["topology"] == "protocol")
    check("gossip 对账通过（复算与 gossip 共存）",
          rr["report"]["gossip_consistent"] is True)
    v = verify_wal_signatures(wal, SECRET)
    check("WAL 全验签", v["all_valid"], f"bad={v['bad']}")

# ============ ② protocol + 4 实例（recorder 为第 4 实例） ============
print("=== ② 最小 protocol（3 实例：primary/verifier/arbiter） ===")
cfg2 = make_swarm_config(INST[:3], rounds=2, shared_secret=SECRET, topology="protocol")
rr2 = run_swarm(proj, cfg2, wal_path=os.path.join(tmp, "b.jsonl"))
check("三实例 protocol 运行", rr2["ok"], str(rr2.get("stderr", ""))[:150])
if rr2["ok"]:
    roles2 = rr2["report"]["roles"]
    check("三实例角色（无 recorder）",
          roles2 == {"实例0": "primary", "实例1": "verifier", "实例2": "arbiter"},
          str(roles2))
    check("复算 2 轮全过", rr2["report"]["recalc"] == {"checked": 2, "mismatches": 0},
          str(rr2["report"]["recalc"]))

# ============ ③ 非协议拓扑不受影响 ============
print("=== ③ 向后兼容 ===")
cfg3 = make_swarm_config(INST[:2], rounds=2, shared_secret=SECRET)
rr3 = run_swarm(proj, cfg3, wal_path=os.path.join(tmp, "c.jsonl"))
check("mesh 缺省运行", rr3["ok"])
if rr3["ok"]:
    check("非 protocol 拓扑 recalc=0", rr3["report"]["recalc"] == {"checked": 0, "mismatches": 0},
          str(rr3["report"]["recalc"]))

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
