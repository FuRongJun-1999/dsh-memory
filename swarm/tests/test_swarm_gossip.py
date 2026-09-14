# -*- coding: utf-8 -*-
"""test_swarm_gossip.py · G3b gossip 广播+水位对账验收（B3 甲案 · 心跳任务 2026-09-13）
覆盖：Route.to_id="*" fan-out（除源外全部实例）/ gossip 水位记账 /
gossip_consistent 对账 / gossip 不影响既有单播路由。
"""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from swarm.rust_codegen import generate_rust_project
from swarm.rust_swarm import (aggregate_health_python, make_swarm_config,
                             run_swarm, verify_wal_signatures)

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
SECRET = "验收密钥-蜂群G3b传播"

tmp = tempfile.mkdtemp(prefix="swarm_gossip_")
proj = os.path.join(tmp, "proj")
gen = generate_rust_project(SOURCE, proj)
check("项目生成", gen["ok"])

# ============ ① gossip 广播：3 实例，甲 gossip 至乙丙 ============
print("=== ① gossip 广播（3 实例 × 3 轮） ===")
cfg = make_swarm_config(
    instances=[
        {"id": "实例甲", "role": "源", "trust": 0.1},
        {"id": "实例乙", "role": "peer", "trust": 0.2},
        {"id": "实例丙", "role": "peer", "trust": 0.2},
    ],
    routes=[{"from": "实例甲", "event_type": "gossip", "to": "*",
             "payload": "@trust", "level": 0}],
    rounds=3, shared_secret=SECRET)
rr = run_swarm(proj, cfg, wal_path=os.path.join(tmp, "events.jsonl"))
check("gossip 蜂群运行", rr["ok"], str(rr.get("stderr", ""))[:150])
if rr["ok"]:
    rep = rr["report"]
    g = rep.get("gossip", {})
    check("gossip 水位：乙=丙=3（每轮广播 1 条×3 轮）",
          g.get("实例乙") == 3 and g.get("实例丙") == 3, str(g))
    check("gossip 不自环（甲不在水位表）", "实例甲" not in g, str(list(g)))
    check("gossip_consistent=true（覆盖一致）",
          rep.get("gossip_consistent") is True)
    fs = rep["final_states"]
    check("乙丙在第 2/3 轮实际收到 gossip（已收消息数=1）",
          fs["实例乙"]["symbols"].get("已收消息数") == 1
          and fs["实例丙"]["symbols"].get("已收消息数") == 1,
          str({k: v["symbols"].get("已收消息数") for k, v in fs.items()}))
    # G5 修正回归：纯源实例（无 gossip 入边）coverage=1.0，health 不应被误降
    check("纯源实例 health 满分（coverage 语义修正回归）",
          abs(rep["health"]["实例甲"]["score"] - 1.0) < 1e-9,
          str(rep["health"]["实例甲"]["score"]))

# ============ ② gossip 与单播路由共存 ============
print("=== ② gossip 与单播共存 ===")
cfg2 = make_swarm_config(
    instances=[
        {"id": "实例甲", "role": "源", "trust": 0.1},
        {"id": "实例乙", "role": "peer", "trust": 0.2},
        {"id": "实例丙", "role": "peer", "trust": 0.2},
    ],
    routes=[{"from": "实例甲", "event_type": "gossip", "to": "*",
             "payload": "@trust", "level": 0},
            {"from": "实例乙", "event_type": "定向", "to": "实例丙",
             "payload": "@trust", "level": 0}],
    rounds=2, shared_secret=SECRET)
rr2 = run_swarm(proj, cfg2, wal_path=os.path.join(tmp, "events2.jsonl"))
check("混合路由运行", rr2["ok"], str(rr2.get("stderr", ""))[:150])
if rr2["ok"]:
    rep2 = rr2["report"]
    # 丙的收件箱：轮 2 = gossip(甲) + 定向(乙) → 同轮 2 from 不覆盖
    # gossip 水位：乙=丙 各 2；对账一致
    check("混合路由 gossip 水位一致",
          rep2["gossip"].get("实例乙") == 2 and rep2["gossip"].get("实例丙") == 2
          and rep2["gossip_consistent"] is True,
          str(rep2["gossip"]))
    check("混合路由事件数 = gossip 4 + 定向 2 + ACK 2 + 快照 2",
          rep2["events"] == 4 + 2 + 2 + 2,
          str(rep2["events"]))
v = verify_wal_signatures(os.path.join(tmp, "events2.jsonl"), SECRET)
check("混合路由 WAL 全验签", v["all_valid"], f"bad={v['bad']}")

# ============ ③ 无 gossip 路由 → 对账默认一致 ============
print("=== ③ 无 gossip 默认对账 ===")
cfg3 = make_swarm_config(
    instances=[{"id": "实例甲", "role": "w", "trust": 0.1, "symbols": {}}],
    routes=[], rounds=1, shared_secret=SECRET)
rr3 = run_swarm(proj, cfg3, wal_path=os.path.join(tmp, "events3.jsonl"))
check("无 gossip 运行", rr3["ok"])
if rr3["ok"]:
    check("gossip 空表 + consistent=true（未启用语义）",
          rr3["report"]["gossip"] == {}
          and rr3["report"]["gossip_consistent"] is True)

# ============ ④ G3c：全网互 gossip 水位对账 + coverage 接入 integrity ============
print("=== ④ G3c 全网互 gossip + coverage 因子 ===")
cfg4 = make_swarm_config(
    instances=[
        {"id": "实例甲", "role": "peer", "trust": 0.1},
        {"id": "实例乙", "role": "peer", "trust": 0.2},
        {"id": "实例丙", "role": "peer", "trust": 0.2},
    ],
    routes=[{"from": i, "event_type": "gossip", "to": "*",
             "payload": "@trust", "level": 0}
            for i in ("实例甲", "实例乙", "实例丙")],
    rounds=3, shared_secret=SECRET)
rr4 = run_swarm(proj, cfg4, wal_path=os.path.join(tmp, "events4.jsonl"))
check("全网互 gossip 运行", rr4["ok"], str(rr4.get("stderr", ""))[:150])
if rr4["ok"]:
    rep4 = rr4["report"]
    # 每实例每轮收到其他 2 实例各 1 条 gossip → 实收 = 2×3 = 6（投递记账含末轮）
    check("全网互 gossip 水位一致（各=6）且对账 true",
          all(rep4["gossip"].get(i) == 6 for i in ("实例甲", "实例乙", "实例丙"))
          and rep4["gossip_consistent"] is True,
          str(rep4["gossip"]))
    check("coverage=1.0 → integrity 不降（score=1.0）",
          all(abs(rep4["health"][i]["score"] - 1.0) < 1e-9
              for i in rep4["health"]))
# coverage 降级公式（Python 参照单测：缺收一半 → integrity 减半）
h = aggregate_health_python(
    {"甲": [True, True]},
    gossip_coverage={"甲": 0.5})
check("coverage=0.5 → integrity=0.5、score=0.9（0.4+0.2+0.2+0.2×0.5）",
      abs(h["甲"]["integrity_rate"] - 0.5) < 1e-9
      and abs(h["甲"]["score"] - 0.9) < 1e-9,
      f"ir={h['甲']['integrity_rate']} score={h['甲']['score']:.4f}")

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
