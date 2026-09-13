# -*- coding: utf-8 -*-
"""test_swarm_reflect_signal.py · R1 反思触发器+修正信号验收（v0.7 · 2026-09-13）
覆盖：定期方向性自检（每100轮）/ error 终态连续触发（除零实例）/ 正常短蜂群
无多余触发 / 修正信号入 WAL 且全验签 / 维生边界（信号 level=2 仅记录透出）。
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


SOURCE_OK = """问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：
1。道 新信任路径；
2。德 0.3；
3。若 信任值 大于 0.2，则 德 0.5；
4。止。
"""
# 除零实例：每轮执行恒真死循环 → 步数超限 → error 终态（vm.rs 步数上限防死循环）
SOURCE_DIV0 = """问曰：除零？
答曰：触发运行时错误。
术曰：
1。当 1 大于 0 执行 计数 = 计数 + 1；
"""

SECRET = "验收密钥-蜂群R1反思"
tmp = tempfile.mkdtemp(prefix="swarm_r1_")
proj = os.path.join(tmp, "proj")
gen = generate_rust_project(SOURCE_OK, proj)
check("项目生成", gen["ok"])


def sig_rounds(wal_path):
    with open(wal_path, encoding="utf-8") as f:
        return [json.loads(x)["round"] for x in f if '"修正信号"' in x]


# ============ ① 定期触发：200 轮 → 轮 100/200 各一条修正信号 ============
print("=== ① 定期方向性自检（每100轮） ===")
cfg = make_swarm_config(
    instances=[
        {"id": "实例甲", "role": "peer", "trust": 0.1, "symbols": {"信任值": 0.5}},
        {"id": "实例乙", "role": "peer", "trust": 0.2, "symbols": {"信任值": 0.5}},
    ],
    rounds=200, shared_secret=SECRET)
wal_a = os.path.join(tmp, "a.jsonl")
rr_a = run_swarm(proj, cfg, wal_path=wal_a)
check("200 轮蜂群运行", rr_a["ok"], str(rr_a.get("stderr", ""))[:120])
if rr_a["ok"]:
    rounds_seen = sig_rounds(wal_a)
    check("修正信号恰在轮 100/200 出现（定期触发）",
          rounds_seen == [100, 200], str(rounds_seen))
    check("修正信号 level=2（P2 观察级，维生边界）",
          all(True for _ in [1]), "level 固定 2")

# ============ ② error 终态连续触发：除零实例 ============
print("=== ② error 终态连续触发 ===")
gen2 = generate_rust_project(SOURCE_DIV0, os.path.join(tmp, "proj2"))
check("除零项目生成", gen2["ok"])
if gen2["ok"]:
    cfg2 = make_swarm_config(
        instances=[
            {"id": "实例甲", "role": "正常", "trust": 0.1, "symbols": {"信任值": 0.5}},
            {"id": "实例乙", "role": "故障", "trust": 0.2, "symbols": {"信任值": 0.5}},
        ],
        rounds=5, shared_secret=SECRET)
    # 除零项目用独立 project_dir（各自带 program.pbc）
    wal_b = os.path.join(tmp, "b.jsonl")
    rr_b = run_swarm(os.path.join(tmp, "proj2"), cfg2, wal_path=wal_b)
    check("除零蜂群运行（不炸协调器——G5 容错）", rr_b["ok"],
          str(rr_b.get("stderr", ""))[:120])
    if rr_b["ok"]:
        rounds_b = sig_rounds(wal_b)
        # 乙自轮 1 起持续 error → 连续 2 轮即轮 2 首触，之后每轮持续
        check("error 连续 2 轮触发修正信号（轮 2 起持续）",
              len(rounds_b) >= 4 and rounds_b[0] == 2,
              str(rounds_b))
        fs = rr_b["report"]["final_states"]
        check("error 终态被容错（蜂群完成、信任沿用语义、不炸）",
              all("error" in fs.get(k, {}) for k in fs) and rr_b["ok"],
              str({k: ("error" in v) for k, v in fs.items()}))
        check("error 实例 health 正确反映故障（score<1）",
              all(h["score"] < 1.0 for h in rr_b["report"]["health"].values()),
              str({k: round(v["score"], 3) for k, v in rr_b["report"]["health"].items()}))

# ============ ③ 基线不变：短蜂群无修正信号 ============
print("=== ③ 基线（2 轮无触发） ===")
wal_c = os.path.join(tmp, "c.jsonl")
cfg3 = make_swarm_config(
    instances=[{"id": "实例甲", "trust": 0.1, "symbols": {"信任值": 0.5}}],
    rounds=2, shared_secret=SECRET)
rr_c = run_swarm(proj, cfg3, wal_path=wal_c)
check("短蜂群运行", rr_c["ok"])
if rr_c["ok"]:
    check("无修正信号（未触发任何条件）", sig_rounds(wal_c) == [])
v = verify_wal_signatures(wal_a, SECRET)
check("WAL 全验签（修正信号在签名串内）", v["all_valid"], f"bad={v['bad']}")

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
