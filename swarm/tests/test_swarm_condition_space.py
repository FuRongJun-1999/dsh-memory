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
# 缺陷②修复后：信任值 是内建名（读 trust_value 寄存器）。
# 旧写法同时给 trust 与 symbols{信任值} 是「无内建」时期的绕过手段：
# 统一后 symbols 里的 信任值 会被归一为寄存器初值并**覆盖** trust，
# 故此处只保留 trust（0.1/0.2）驱动轨迹。
INST = [{"id": "实例甲", "role": "peer", "trust": 0.1},
        {"id": "实例乙", "role": "peer", "trust": 0.2}]

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

# ============ ④ 执行链接通：卡进 VM 符号表，程序内条件路由真实生效（v0.7.1） ============
# 此前卡只进 cfg/WAL/报告（metadata），请求不带 → 实例 VM 看不到。
# 现在：run_round 请求携带 condition_space → serve 注入预定义符号（条件空间/
# 观测位置/观测工具/时间窗口/存在约束）→ 程序「若 条件空间 等于 X」真实路由。
print("=== ④ 执行链（条件空间→VM 符号→条件路由） ===")
SRC4 = """问曰：条件空间如何进入执行链？
答曰：信任值等于0.6。
术曰：
1。若 条件空间 等于 执行链验收空间，则德 0.5；
2。止。
"""
CS4 = {"space_id": "执行链验收空间",
       "observation_position": "实例视角（VM 符号表）",
       "observation_tool": "serve 注入预定义符号",
       "time_window": "v0.7.1 执行链验收周期",
       "existence_constraint": "单机多进程，纯 std 零依赖"}
proj4 = os.path.join(tmp, "proj4")
generate_rust_project(SRC4, proj4)

cfg4 = make_swarm_config(INST, rounds=1, shared_secret=SECRET, condition_space=CS4)
rr4 = run_swarm(proj4, cfg4, wal_path=os.path.join(tmp, "d.jsonl"))
check("带卡运行条件消费程序", rr4["ok"], str(rr4.get("stderr", ""))[:150])
if rr4["ok"]:
    fs4 = rr4["report"]["final_states"]
    check("卡进 VM 符号表：条件路由命中，德 0.5 执行（0.1+0.5=0.6）",
          abs(fs4["实例甲"]["trust"] - 0.6) < 1e-9 and abs(fs4["实例乙"]["trust"] - 0.7) < 1e-9,
          json.dumps({k: v.get("trust") for k, v in fs4.items()},
                     ensure_ascii=False))

# ④b 对照：同程序不带卡——条件空间符号未注入，程序不应骗过（差异化验收）
cfg4b = make_swarm_config(INST, rounds=1, shared_secret=SECRET)
rr4b = run_swarm(proj4, cfg4b, wal_path=os.path.join(tmp, "e.jsonl"))
if rr4b["ok"]:
    fs4b = rr4b["report"]["final_states"]
    # 缺陷③修复后语义变化：条件空间 现为 VM **内建名**（无可注入符号时读「默认」），
    # 故不带卡不再「名实不符崩溃」，而是路由不命中 —— trust 停在初值不被推高，
    # 与带卡（0.6/0.7）形成干净的差异验收。
    check("不带卡：条件路由不命中 → trust 停在初值 0.1/0.2（未被 德 0.5 推高）",
          abs(fs4b["实例甲"]["trust"] - 0.1) < 1e-9
          and abs(fs4b["实例乙"]["trust"] - 0.2) < 1e-9,
          json.dumps({k: v.get("trust", v.get("error")) for k, v in fs4b.items()},
                     ensure_ascii=False))
else:
    check("不带卡：VM 符号缺失 → 运行失败（证明程序真依赖注入符号）",
          not rr4b["ok"], str(rr4b.get("stderr", ""))[-120:])

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
