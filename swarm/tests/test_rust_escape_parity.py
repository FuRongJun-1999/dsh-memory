# -*- coding: utf-8 -*-
"""test_rust_escape_parity.py · 写/读转义集同集（N245）

缺陷：写侧 `serde_json_like::escape` 对 <0x20 控制字符产 `\\uXXXX`、对回车产
`\\r`，而读侧三处（swarm.rs `ps` / serve.rs `parse_str` / main.rs
`parse_json_string`）只认 `\\" \\\\ \\n \\t` ⇒ 集合不相容，三面后果皆静默/拒服务：
  ①载荷含制表符（escape 产 `\\u0009`）时实例侧请求解析失败、目标实例终态恒为
    error，而协调器 rc=0 照发 ACK、水位照推进；
  ②WAL 载荷含 `\\u0009` 时提交点扫描首行即断 → 合法 WAL 被误标 `.corrupt-<ts>`
    并从轮 1 重跑（破坏「同 project+同 WAL 重入即续跑」幂等契约；WAL 本身是
    合法 JSON、Python 侧验签 all_valid=True）；
  ③配置含标准 `\\r` 转义 → 整蜂群「配置 JSON 非法」exit 2（`--symbols` 同面）。

本守卫走产品通路（真蜂群 + 同 WAL 分段重入 + 二进制入参），断言三面皆不再现。
纯行为断言（不做源码文本匹配）。
"""
import io
import json
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from swarm.rust_codegen import build_and_run, generate_rust_project
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
3。止。
"""
SECRET = "验收密钥-N245转义同集"
TAB_PAYLOAD = "上\t下"      # 制表符：escape 产 \u0009（旧读侧认不出）
CR_PAYLOAD = "左\r右"       # 回车：escape 产 \r（旧读侧认不出）


def cfg_tab(rounds):
    return make_swarm_config(
        instances=[{"id": "实例甲", "trust": 0.1}, {"id": "实例乙", "trust": 0.2}],
        routes=[{"from": "实例甲", "event_type": "含制表符", "to": "实例乙",
                 "payload": TAB_PAYLOAD, "level": 0}],
        rounds=rounds, shared_secret=SECRET)


def scenario_tab(proj, tmp):
    """① 含制表符的值：实例须正常执行（旧实现：请求行解析失败 → 终态 error）。

    两个入口都钉：
      · `初始符号` 原样注入请求（写侧 stringify 产 `\\u0009`）——今天仍在线；
      · 路由载荷（经收件箱）——N243 把整段收件箱 JSON 文本再 escape 一次，
        故该入口目前被双重转义遮蔽；保留断言以防回退后再暴露。
    """
    print("=== ① 含制表符（\\u0009）===")
    # ①a 初始符号（原样注入，判断力所在）
    cfg_sym = make_swarm_config(
        instances=[{"id": "实例甲", "trust": 0.1,
                    "symbols": {"含制表": TAB_PAYLOAD}},
                   {"id": "实例乙", "trust": 0.2}],
        routes=[], rounds=1, shared_secret=SECRET)
    rr_sym = run_swarm(proj, cfg_sym, wal_path=os.path.join(tmp, "sym.jsonl"))
    check("①a 含制表符符号的蜂群运行", rr_sym["ok"], str(rr_sym.get("stderr", ""))[:150])
    if rr_sym["ok"]:
        st = rr_sym["report"]["final_states"]["实例甲"]
        check("①a 甲终态无 error（旧实现：请求行解析失败 → 终态恒为 error）",
              "error" not in st, str(st.get("error"))[:120])
        check("①a 符号值逐字节保真（经请求 JSON 往返）",
              st.get("symbols", {}).get("含制表") == TAB_PAYLOAD,
              repr(st.get("symbols", {}).get("含制表")))

    # ①b 路由载荷（经收件箱）
    rr = run_swarm(proj, cfg_tab(2), wal_path=os.path.join(tmp, "tab.jsonl"))
    check("①b 蜂群运行", rr["ok"], str(rr.get("stderr", ""))[:150])
    if not rr["ok"]:
        return
    st = rr["report"]["final_states"]["实例乙"]
    check("①b 乙终态无 error", "error" not in st, str(st.get("error"))[:120])
    msgs = None
    raw = st.get("symbols", {}).get("收件箱")
    if isinstance(raw, str):
        try:
            msgs = json.loads(raw)
        except json.JSONDecodeError:
            msgs = None
    check("①b 制表符载荷逐字节保真（经 JSON 文本往返）",
          msgs == [{"from": "实例甲", "payload": TAB_PAYLOAD}], str(raw))


def scenario_wal_reentry(proj, tmp):
    """② 同 WAL 分段重入：含 \\u0009 的载荷不得让提交点丢失。"""
    print("=== ② 同 WAL 分段重入（提交点不得被误判为零提交）===")
    wal_base = os.path.join(tmp, "base.jsonl")
    rr_base = run_swarm(proj, cfg_tab(3), wal_path=wal_base)
    check("基线 3 轮运行", rr_base["ok"], str(rr_base.get("stderr", ""))[:150])
    wal = os.path.join(tmp, "reentry.jsonl")
    rr1 = run_swarm(proj, cfg_tab(1), wal_path=wal)
    check("前段 1 轮运行", rr1["ok"], str(rr1.get("stderr", ""))[:150])
    rr3 = run_swarm(proj, cfg_tab(3), wal_path=wal)
    check("续跑 2 轮运行", rr3["ok"], str(rr3.get("stderr", ""))[:150])
    if not rr3["ok"]:
        return
    arch = sorted(f for f in os.listdir(tmp) if ".corrupt-" in f)
    check("合法 WAL 不得被归档 .corrupt-*（旧实现：首行即断 → 零提交 → 归档）",
          not arch, str(arch))
    check("WAL 全验签（WAL 本身是合法 JSON，Python 侧独立复核）",
          verify_wal_signatures(wal, SECRET)["all_valid"])
    if rr_base["ok"]:
        check("续跑事件史 = 一次跑基线（未从轮 1 重跑）",
              rr3["report"]["events"] == rr_base["report"]["events"],
              f"resume={rr3['report']['events']} base={rr_base['report']['events']}")


def scenario_cr(proj, tmp):
    """③ 配置含标准 \\r 转义：整蜂群不得 exit 2；`--symbols` 同面。"""
    print("=== ③ 配置/入参含 \\r 转义 ===")
    cfg = make_swarm_config(
        instances=[{"id": "实例甲", "trust": 0.1}, {"id": "实例乙", "trust": 0.2}],
        routes=[{"from": "实例甲", "event_type": "含回车", "to": "实例乙",
                 "payload": CR_PAYLOAD, "level": 0}],
        rounds=2, shared_secret=SECRET)
    rr = run_swarm(proj, cfg, wal_path=os.path.join(tmp, "cr.jsonl"))
    check("配置含 \\r 蜂群运行（旧实现：配置 JSON 非法 → exit 2）",
          rr["ok"], str(rr.get("stderr", ""))[:150])
    if rr["ok"]:
        st = rr["report"]["final_states"]["实例乙"]
        check("乙终态无 error 且回车载荷逐字节保真",
              "error" not in st
              and json.loads(st["symbols"]["收件箱"]) ==
              [{"from": "实例甲", "payload": CR_PAYLOAD}],
              str(st.get("error") or st["symbols"].get("收件箱")))
    # 第三条读侧（main.rs parse_json_string，--symbols 入参）
    st = build_and_run(proj, symbols={"含制表": TAB_PAYLOAD, "含回车": CR_PAYLOAD})
    check("--symbols 含 \\r/制表符可解析（旧实现：不支持的转义 → exit 2）",
          st.get("ok") and st["state"]["symbols"].get("含回车") == CR_PAYLOAD
          and st["state"]["symbols"].get("含制表") == TAB_PAYLOAD,
          str(st.get("stderr") or st.get("state", {}).get("symbols"))[:150])


if __name__ == "__main__":
    tmp = tempfile.mkdtemp(prefix="rust_escape_")
    proj = os.path.join(tmp, "proj")
    gen = generate_rust_project(SOURCE, proj)
    check("项目生成", gen["ok"])
    if gen["ok"]:
        scenario_tab(proj, tmp)
        scenario_wal_reentry(proj, tmp)
        scenario_cr(proj, tmp)
    print(f"\n{pass_n} passed, {fail_n} failed")
    sys.exit(1 if fail_n else 0)
