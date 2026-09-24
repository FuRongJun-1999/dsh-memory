# -*- coding: utf-8 -*-
"""test_swarm_inbox_delivery.py · 收件箱投递保真回归（2026-09-25）
红守卫两条（修复前必红）：
  #1 protocol 拓扑：发给 verifier 的自身收件箱每轮被『顺延一轮』直至
     rounds+1 消亡——从未投递、从未 ACK、水位永不推进（swarm.rs 旧
     759-774 段）。修复后：到达轮即消费记账（ACK+水位；载荷不进复算
     输入，复算逐位一致性不受影响）。
  #2 同轮同源多条路由在收件箱处以来源为单值 key 互相覆盖——第二条
     insert 静默丢弃第一条载荷，但 WAL 两条事件均已签名落盘（审计
     留痕与实际投递不符）。修复后：逐条追加，已收消息数如实计数。
场景函数化（scenario_a/b）供红演示驱动复用（换旧 swarm.rs 重跑）。
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
    print(f'[{"✓" if ok else "✗"}] {name}{" — " + detail if detail else ""}')


SOURCE = """问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：
1。道 新信任路径；
2。德 0.3；
3。若 信任值 大于 0.2，则 德 0.5；
4。止。
"""
SECRET = "验收密钥-收件箱投递2026-09-25"


def _wal_events(wal):
    evs = []
    with open(wal, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                evs.append(json.loads(line))
    return evs


def scenario_a(proj, tmp):
    """#2 同轮同源多路由：两条 甲→乙 路由，载荷不覆盖、计数如实。"""
    print("=== ① 同轮同源双路由（mesh）===")
    cfg = make_swarm_config(
        instances=[{"id": "实例甲", "trust": 0.1}, {"id": "实例乙", "trust": 0.2}],
        routes=[{"from": "实例甲", "event_type": "载荷A", "to": "实例乙",
                 "payload": "11", "level": 0},
                {"from": "实例甲", "event_type": "载荷B", "to": "实例乙",
                 "payload": "22", "level": 0}],
        rounds=2, shared_secret=SECRET)
    rr = run_swarm(proj, cfg, wal_path=os.path.join(tmp, "a.jsonl"))
    check("双路由蜂群运行", rr["ok"], str(rr.get("stderr", ""))[:150])
    if not rr["ok"]:
        return
    evs = _wal_events(rr["wal"])
    routed = [e for e in evs if e["to"] == "实例乙" and e["type"] != "__snapshot__"]
    # WAL 两条事件每轮均已签名落盘（旧代码也过——正是『留痕与投递不符』的留痕侧）
    check("WAL 路由事件 2 轮 × 2 条 = 4（留痕侧）", len(routed) == 4, str(len(routed)))
    payloads = {(e["type"], str(e["payload"])) for e in routed}
    check("两种载荷均在 WAL 留痕", payloads == {("载荷A", "11"), ("载荷B", "22")},
          str(payloads))
    # 判别器：乙第 2 轮实收消息数（旧代码覆盖后 = 1，修复后 = 2）
    fs = rr["report"]["final_states"]
    got = fs["实例乙"]["symbols"].get("已收消息数")
    check("乙实收消息数 = 2（旧实现同源覆盖后仅 1）", got == 2, str(got))
    v = verify_wal_signatures(rr["wal"], SECRET)
    check("WAL 全验签", v["all_valid"], f"bad={v['bad']}")


def scenario_b(proj, tmp):
    """#1 protocol：发给 verifier 的自身收件箱不丢失（ACK+水位）。"""
    print("=== ② protocol 发往 verifier 的消息不丢失 ===")
    cfg = make_swarm_config(
        instances=[{"id": "实例0", "trust": 0.1}, {"id": "实例1", "trust": 0.1},
                   {"id": "实例2", "trust": 0.1}],
        routes=[{"from": "实例2", "event_type": "核验请求", "to": "实例1",
                 "payload": "7", "level": 0}],
        rounds=3, shared_secret=SECRET, topology="protocol")
    rr = run_swarm(proj, cfg, wal_path=os.path.join(tmp, "b.jsonl"))
    check("protocol 蜂群运行", rr["ok"], str(rr.get("stderr", ""))[:150])
    if not rr["ok"]:
        return
    evs = _wal_events(rr["wal"])
    routed = [e for e in evs if e["to"] == "实例1" and e["type"] != "__snapshot__"]
    check("WAL 发往 verifier 的路由事件 3 条（每轮 1 条）", len(routed) == 3,
          str(len(routed)))
    # 判别器 1：verifier 的 ACK（旧实现 0 条——顺延至消亡从未回执；
    # 修复后轮 2、3 各 1 条；轮 3 产出落 rounds+1 属蜂群收尾固有语义）
    acks = [e for e in evs if e["type"] == "ACK" and e["from"] == "实例1"]
    check("verifier ACK = 2（轮 2、3；旧实现恒 0）", len(acks) == 2, str(len(acks)))
    # 判别器 2：verifier 消费水位推进（旧实现键缺失/恒 0）
    wm = rr["report"]["watermarks"].get("实例1", 0)
    check("verifier 消费水位 > 0（旧实现永不推进）", wm > 0, str(wm))
    # 复算不受影响：verifier 执行输入仍是 primary 输入（载荷未混入）
    rec = rr["report"]["recalc"]
    check("复算 3 轮全过（修复不破坏逐位复算）",
          rec == {"checked": 3, "mismatches": 0}, str(rec))
    v = verify_wal_signatures(rr["wal"], SECRET)
    check("WAL 全验签", v["all_valid"], f"bad={v['bad']}")


if __name__ == "__main__":
    tmp = tempfile.mkdtemp(prefix="swarm_inbox_")
    proj = os.path.join(tmp, "proj")
    gen = generate_rust_project(SOURCE, proj)
    check("项目生成", gen["ok"])
    if gen["ok"]:
        scenario_a(proj, tmp)
        scenario_b(proj, tmp)
    print(f"\n{pass_n} passed, {fail_n} failed")
    sys.exit(1 if fail_n else 0)
