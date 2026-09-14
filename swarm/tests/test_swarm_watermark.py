# -*- coding: utf-8 -*-
"""test_swarm_watermark.py · G4b 版本化信箱验收（心跳任务 2026-09-13）
覆盖：全局单调 seq / 实例消费水位 watermark / ACK 携带 seq（进 HMAC 签名串）/
恢复场景 seq 不断档（分段跑与一次跑 global_seq 相等）。
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
SECRET = "验收密钥-蜂群G4b水位"

tmp = tempfile.mkdtemp(prefix="swarm_wm_")
proj = os.path.join(tmp, "proj")
gen = generate_rust_project(SOURCE, proj)
check("项目生成", gen["ok"])


def cfg_of(rounds):
    return make_swarm_config(
        instances=[
            {"id": "实例甲", "role": "源", "trust": 0.1},
            {"id": "实例乙", "role": "peer", "trust": 0.2},
            {"id": "实例丙", "role": "peer", "trust": 0.2},
        ],
        routes=[{"from": "实例甲", "event_type": "gossip", "to": "*",
                 "payload": "@trust", "level": 0},
                {"from": "实例乙", "event_type": "定向", "to": "实例丙",
                 "payload": "@trust", "level": 0}],
        rounds=rounds, shared_secret=SECRET)


# ============ ① 基线：一次跑 4 轮，水位=全局 seq ============
print("=== ① 水位与全局 seq ===")
wal_a = os.path.join(tmp, "a.jsonl")
rr = run_swarm(proj, cfg_of(4), wal_path=wal_a)
check("蜂群运行", rr["ok"], str(rr.get("stderr", ""))[:150])
if rr["ok"]:
    rep = rr["report"]
    wm = rep["watermarks"]
    check("报告含全局 seq（>0）", rep["global_seq"] > 0, str(rep["global_seq"]))
    # 甲无入边 → 无收件箱不 ACK → 不进水位表（get 默认 0）；丙入边 2 条水位最高
    check("甲无入边不进水位表（语义水位=0）", wm.get("实例甲", 0) == 0, str(wm))
    check("乙丙水位>0 且 丙>乙（丙入边 gossip+定向）",
          wm.get("实例乙", 0) > 0 and wm.get("实例丙", 0) > wm.get("实例乙", 0),
          str(wm))

# ============ ② 恢复单调性：分段跑(2+2) global_seq = 一次跑(4) ============
print("=== ② 恢复场景 seq 不断档 ===")
wal_b = os.path.join(tmp, "b.jsonl")
cfg2 = dict(cfg_of(2))
rr_b1 = run_swarm(proj, cfg2, wal_path=wal_b)
check("前段 2 轮", rr_b1["ok"])
rr_b2 = run_swarm(proj, cfg_of(4), wal_path=wal_b)
check("续跑至 4 轮", rr_b2["ok"])
if rr_b2["ok"] and rr["ok"]:
    check("分段跑 global_seq = 一次跑（恢复后 seq 单调不断档）",
          rr_b2["report"]["global_seq"] == rr["report"]["global_seq"],
          f"resume={rr_b2['report']['global_seq']} base={rr['report']['global_seq']}")
    check("分段跑水位 = 一次跑",
          rr_b2["report"]["watermarks"] == rr["report"]["watermarks"],
          str(rr_b2["report"]["watermarks"]))
    # ACK payload 含 seq（WAL 行 payload 里有 "seq" 键）
    with open(wal_b, encoding="utf-8") as f:
        ack_seqs = [json.loads(x)["payload"].get("seq")
                    for x in f if '"ACK"' in x]
    check("ACK payload 携带 seq", all(s is not None for s in ack_seqs),
          str(ack_seqs[:5]))
v = verify_wal_signatures(wal_b, SECRET)
check("WAL 全验签（ACK seq 在签名串内受保护）", v["all_valid"], f"bad={v['bad']}")

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
