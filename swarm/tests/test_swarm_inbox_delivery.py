# -*- coding: utf-8 -*-
"""test_swarm_inbox_delivery.py · 收件箱投递保真回归（2026-09-25 / N243·N247 2026-10-05）
红守卫四条（修复前必红）：
  #1 protocol 拓扑：发给 verifier 的自身收件箱每轮被『顺延一轮』直至
     rounds+1 消亡——从未投递、从未 ACK、水位永不推进（swarm.rs 旧
     759-774 段）。修复后：到达轮即消费记账（ACK+水位；载荷不进复算
     输入，复算逐位一致性不受影响）。
  #2 同轮同源多条路由在收件箱处以来源为单值 key 互相覆盖——第二条
     insert 静默丢弃第一条载荷，但 WAL 两条事件均已签名落盘（审计
     留痕与实际投递不符）。修复后：逐条追加，已收消息数如实计数。
  #3 N243：收件箱以 JSON **数组**形态注入 symbols，而 serve 侧
     to_vm_value 对 List/Obj 落 `_ => None` 臂被静默跳过——符号「收件箱」
     从未进实例 VM 符号表（程序一引用即「名实不符」），WAL/ACK/水位却照记
     已投递，载荷只完整留在 WAL。修复后：协调器侧按 condition_space 同口径
     用 serde_json_like::escape 序列化为 JSON **文本**注入（serve 走 Str 臂），
     载荷逐字节保留在符号内。
  #4 N247：收件箱逐条编串时 `from` **裸插**——实例 id 来自用户 config、
     无校验，含 `"`/`\\` 时整条请求行被击穿，serve 回「请求 JSON 非法」的
     error 对象被 run_round 当合法终态吞下、CLI 仍 rc=0。修复后：`from` 与
     condition_space 同口径走 serde_json_like::escape 单点。
场景函数化（scenario_a/b/c/d）供红演示驱动复用（换旧 swarm.rs 重跑）。
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


def scenario_c(proj, tmp):
    """#3 N243：收件箱（结构化数组）必须真进实例 VM 符号表。

    判别器只看终态符号表本身（不是源码文本，也不是 WAL 留痕）——
    「留痕照记已投递、符号表却没有收件箱」正是本缺陷的错位。
    """
    print("=== ③ 收件箱进实例符号表（N243）===")
    cfg = make_swarm_config(
        instances=[{"id": "实例甲", "trust": 0.1}, {"id": "实例乙", "trust": 0.2}],
        routes=[{"from": "实例甲", "event_type": "载荷A", "to": "实例乙",
                 "payload": "11", "level": 0},
                {"from": "实例甲", "event_type": "载荷B", "to": "实例乙",
                 "payload": "22", "level": 0}],
        rounds=2, shared_secret=SECRET)
    rr = run_swarm(proj, cfg, wal_path=os.path.join(tmp, "c.jsonl"))
    check("双路由蜂群运行", rr["ok"], str(rr.get("stderr", ""))[:150])
    if not rr["ok"]:
        return
    fs = rr["report"]["final_states"]
    sym = fs["实例乙"]["symbols"]
    raw = sym.get("收件箱")
    check("乙符号表含「收件箱」（旧实现 List 被 serve 静默丢弃 → 键缺失）",
          raw is not None, f"keys={sorted(sym)}")
    # 载荷逐字节保真：JSON 文本重新解析后须与原路由载荷同值
    msgs = json.loads(raw) if isinstance(raw, str) else None
    check("收件箱 = JSON 文本且两条载荷逐字节保真",
          msgs == [{"from": "实例甲", "payload": "11"},
                   {"from": "实例甲", "payload": "22"}], str(raw))
    check("未收消息实例不带收件箱键（不误注入）",
          "收件箱" not in fs["实例甲"]["symbols"],
          str(sorted(fs["实例甲"]["symbols"])))


def scenario_d(proj, tmp):
    """#4 N247：来源标识（实例 id）含引号/反斜杠时，请求信封不得被击穿。

    缺陷：收件箱逐条编串时 `from` **裸插**（同函数 condition_space 五要素早已
    走 serde_json_like::escape 单点）——实例 id 来自用户 config、无校验，含 `"`
    时整条请求行 JSON 结构被击穿，serve 回「请求 JSON 非法」的 error 对象，
    而 run_round 把它当合法终态吞下、CLI 仍 rc=0（静默错误：载荷从未进任何
    符号表，实例终态却是「正常收尾」）。
    判别器看终态符号表本身 + WAL 全验签（留痕面）。
    """
    print("=== ④ 来源标识含引号/反斜杠（N247）===")
    hostile = '实"例\\甲'          # 双引号 + 反斜杠：裸插即击穿 JSON
    cfg = make_swarm_config(
        instances=[{"id": hostile, "trust": 0.1}, {"id": "收方", "trust": 0.2}],
        routes=[{"from": hostile, "event_type": "定向", "to": "收方",
                 "payload": "11", "level": 0}],
        rounds=2, shared_secret=SECRET)
    rr = run_swarm(proj, cfg, wal_path=os.path.join(tmp, "d.jsonl"))
    check("蜂群运行（旧实现：目标实例请求 JSON 非法 → error 终态而 CLI 仍 rc=0）",
          rr["ok"], str(rr.get("stderr", ""))[:150])
    if not rr["ok"]:
        return
    fs = rr["report"]["final_states"]
    st = fs.get("收方") or {}
    check("收方终态无 error（旧实现：信封击穿 → 「请求 JSON 非法」）",
          "error" not in st, str(st.get("error"))[:120])
    raw = st.get("symbols", {}).get("收件箱")
    msgs = json.loads(raw) if isinstance(raw, str) else None
    check("来源标识逐字节保真（引号/反斜杠经 escape 单点往返）",
          msgs == [{"from": hostile, "payload": "11"}], str(raw))
    check("WAL 全验签（留痕面：from/to 已走 escape，行仍是合法 JSON）",
          verify_wal_signatures(rr["wal"], SECRET)["all_valid"])


if __name__ == "__main__":
    tmp = tempfile.mkdtemp(prefix="swarm_inbox_")
    proj = os.path.join(tmp, "proj")
    gen = generate_rust_project(SOURCE, proj)
    check("项目生成", gen["ok"])
    if gen["ok"]:
        scenario_a(proj, tmp)
        scenario_b(proj, tmp)
        scenario_c(proj, tmp)
        scenario_d(proj, tmp)
    print(f"\n{pass_n} passed, {fail_n} failed")
    sys.exit(1 if fail_n else 0)
