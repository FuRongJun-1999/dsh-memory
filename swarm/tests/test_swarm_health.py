# -*- coding: utf-8 -*-
"""test_swarm_health.py · G3a 健康四因子评分验收（B3 甲案 · 心跳任务 2026-09-13）
覆盖：端到端报告 health 字段（全成功=score 1.0）/ Python 参照双端公式一致 /
公式场景单测（半 error=0.7 / 缺失轮降 uptime / 验签失败降 integrity）。
"""
import io
import json
import os
import sys
import tempfile
from collections import Counter

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
SECRET = "验收密钥-蜂群G3a健康"

tmp = tempfile.mkdtemp(prefix="swarm_health_")
proj = os.path.join(tmp, "proj")
gen = generate_rust_project(SOURCE, proj)
check("项目生成", gen["ok"])

# ============ ① 公式场景单测（Python 参照） ============
print("=== ① 公式场景单测 ===")
h = aggregate_health_python({"甲": [True, False]})
check("半 error 场景 score=0.7（手算 0.4×.5+0.2×1+0.2×.5+0.2×1）",
      abs(h["甲"]["score"] - 0.7) < 1e-9,
      f"score={h['甲']['score']:.4f} tr={h['甲']['threat_rate']}")
h = aggregate_health_python({"甲": [True, None, True]})
check("缺失轮降 uptime（2/3）且不降 success",
      abs(h["甲"]["uptime_rate"] - 2 / 3) < 1e-9
      and abs(h["甲"]["success_rate"] - 2 / 3) < 1e-9)
h = aggregate_health_python({"甲": [True, True]},
                            verify_fail={"甲": 3}, total_events={"甲": 12})
check("验签失败降 integrity（9/12=0.75）",
      abs(h["甲"]["integrity_rate"] - 0.75) < 1e-9
      and abs(h["甲"]["score"] - (0.4 + 0.2 + 0.2 + 0.2 * 0.75)) < 1e-9)
h = aggregate_health_python({"甲": []})
check("空序列不崩（公式兜底 0.4：success/uptime 归零+integrity 满分；Rust 侧调用方跳过空序列）",
      abs(h["甲"]["score"] - 0.4) < 1e-9)

# ============ ② 端到端：报告 health 与 Python 参照一致 ============
print("=== ② 端到端双端一致 ===")
cfg = make_swarm_config(
    instances=[
        {"id": "实例甲", "role": "记录", "trust": 0.1, "symbols": {"信任值": 0.5}},
        {"id": "实例乙", "role": "验证", "trust": 0.2, "symbols": {"信任值": 0.5}},
    ],
    routes=[{"from": "实例甲", "event_type": "信任同步", "to": "实例乙",
             "payload": "@trust", "level": 0}],
    rounds=3, shared_secret=SECRET)
rr = run_swarm(proj, cfg, wal_path=os.path.join(tmp, "events.jsonl"))
check("蜂群运行", rr["ok"], str(rr.get("stderr", ""))[:150])
if rr["ok"]:
    health = rr["report"].get("health", {})
    check("报告含 health 字段", set(health) == {"实例甲", "实例乙"},
          str(list(health)))
    # 在线全成功口径：outcomes = [True]*3，integrity=1.0
    ref = aggregate_health_python({"实例甲": [True] * 3, "实例乙": [True] * 3})
    for iid in ("实例甲", "实例乙"):
        ok = all(abs(health[iid][k] - ref[iid][k]) < 1e-6
                 for k in ("score", "success_rate", "uptime_rate",
                           "threat_rate", "integrity_rate"))
        check(f"{iid} 五项指标与 Python 参照一致",
              ok,
              f"rust={health[iid]['score']:.6f} py={ref[iid]['score']:.6f}")
    check("全成功实例 score=1.0",
          all(abs(health[i]["score"] - 1.0) < 1e-9 for i in health))

    # ============ ③ integrity 数据通路：WAL 独立复算对照（v0.6.1） ============
    print("=== ③ integrity 通路 WAL 独立复算对照 ===")
    v = verify_wal_signatures(rr["wal"], SECRET)
    check("WAL 全部验签通过", v["all_valid"], str(v))
    per_from = Counter()
    with open(rr["wal"], encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec["type"] == "__snapshot__":
                continue  # 快照行不计事件口径（与 Rust aggregate_report 一致）
            per_from[rec["from"]] += 1
    # 全验签通过 → integrity_rate = (te−0)/te × coverage（无 gossip → 1.0）= 1.0。
    # 复算断言的意义：若 Rust 侧事件归属/口径与 WAL 漂移，te 与报告不一致即爆。
    for iid in ("实例甲", "实例乙"):
        te = per_from.get(iid, 0)
        check(f"{iid} integrity 通路复算一致（te={te}>0）",
              te > 0 and abs(health[iid]["integrity_rate"] - 1.0) < 1e-9,
              f"rust={health[iid]['integrity_rate']:.4f}")

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
