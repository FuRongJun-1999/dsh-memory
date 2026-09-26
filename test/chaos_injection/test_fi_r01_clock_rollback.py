# -*- coding: utf-8 -*-
"""FI-R01 · S9 时间/时钟 → 时钟回拨：serve 心跳新鲜度层拆层观测。

判据：A2 时间不可信（v0.3）/ S9（v0.1 §2.9：心跳新鲜窗壁钟差值
hive/serve_start.py:51/:189 承重面）。注入 = 进程内 mock time.time 回拨/前跳
1 小时，对临时 jobs 目录残留 _serve.json 心跳（pid=死 pid, ts=now-3600s）做
拆层判定：
  ① 新鲜度层单独判（serve_start.py:189 (time.time()*1000-ts) >= FRESH_S*1000）
  ② serve_alive 端到端三层判据（:179-192 新鲜∧pid∧同映像）
  ③ 前跳 +3600 对照（正确判死方向）

理论预期：回拨后新鲜度层被洗白（该层无时钟单调锚——单层失真成立）；
端到端被 pid/同映像层兜住＝P5 分层防御「单层失真不可致命、分层才有判别力」
成立 → verdict=pass。残余风险（如实记录）：若 pid 复用且恰为同映像（v13
实测型），三层全过＝假活——本格是 P1-6「逻辑时钟全域化、墙钟降级展示」
待建面的实证输入。

四可（D4）证据面：status() 的 stale_heartbeat 诊断块（可发现/可隔离/可追溯）
+ serve_alive=False 不挡启动（可恢复，serve_start.py:246 门）。
只动临时 jobs 目录与进程内 mock，测毕清理。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

from hive import serve_start as ss  # noqa: E402


def find_dead_pid(case) -> int:
    pid = 4_000_000 + (int(time.time()) % 100_000)
    while ss.pid_alive(pid):  # 实测该号确无进程（否则换号）
        pid += 1
    case.check("死 pid 探测（pid_alive=False）", not ss.pid_alive(pid), f"pid={pid}")
    return pid


def main() -> int:
    case = harness.Case("FI-R01", "时钟回拨：serve 心跳新鲜度层拆层观测")
    try:
        # 常量口径守卫：两面判活必须同窗（serve_start.py:51 注释约定）
        case.check("FRESH_S=15 与 main.rs FRESH_MS=15000 同值",
                   ss.FRESH_S == 15
                   and "FRESH_MS: f64 = 15_000.0" in harness.src("hive/src/main.rs"),
                   f"python FRESH_S={ss.FRESH_S}")
        case.check("新鲜度层公式在位（:189 壁钟差值）",
                   "time.time() * 1000 - hb.get" in harness.src("hive/serve_start.py"))

        jobs = case.tmpdir("r01_jobs")
        dead_pid = find_dead_pid(case)
        real_now = time.time()
        stale_ts = (real_now - 3600) * 1000.0  # 1 小时前的心跳
        with open(os.path.join(jobs, "_serve.json"), "w", encoding="utf-8") as f:
            json.dump({"pid": dead_pid, "ts": stale_ts, "workers": 2}, f)

        # 真实时钟基线：1h 残留心跳本应判死（age=3600s ≥ 15s）
        real_fresh = (time.time() * 1000 - stale_ts) < ss.FRESH_S * 1000
        case.check("真实时钟下新鲜度层=False（陈旧正确判死）",
                   real_fresh is False,
                   f"age_s={(time.time()*1000-stale_ts)/1000:.0f}")

        def layer1_freshness():
            """复刻 serve_start.py:189 单层判定。"""
            hb = ss.heartbeat(jobs)
            return (time.time() * 1000 - hb.get("ts", 0)) < ss.FRESH_S * 1000

        real_time = time.time
        try:
            # ── 注入①：回拨 1 小时 ──
            time.time = lambda: real_time() - 3600
            fresh_after_rollback = layer1_freshness()
            alive_after_rollback = ss.serve_alive(jobs)
        finally:
            time.time = real_time

        case.check("①回拨后新鲜度层=True（1h 陈旧心跳被洗白——A2 单层失真成立）",
                   fresh_after_rollback is True,
                   "层内无单调锚，全信当次壁钟读数")
        case.check("②回拨后 serve_alive 端到端=False（pid/同映像层兜住，P5 分层成立）",
                   alive_after_rollback is False,
                   f"死 pid={dead_pid} 被第二/三层否决")

        try:
            # ── 注入③：前跳 +3600 对照 ──
            time.time = lambda: real_time() + 3600
            fresh_after_fwd = layer1_freshness()
            alive_after_fwd = ss.serve_alive(jobs)
        finally:
            time.time = real_time
        case.check("③前跳后新鲜度层=False（陈旧判死方向正确）",
                   fresh_after_fwd is False and alive_after_fwd is False,
                   "age≈7200s ≥ 15s → 判死")

        # ── 四可证据面（真实时钟）──
        st = ss.status(jobs)
        sh = st.get("stale_heartbeat") or {}
        case.check("可发现：status() 报 stale_heartbeat（心跳停更可观测）",
                   st.get("alive") is False and sh.get("age_s", 0) > 3000,
                   f"age_s={sh.get('age_s')}")
        case.check("可隔离：诊断块逐层点名（pid_alive/pid_is_self_program/age_s）",
                   sh.get("pid_alive") is False
                   and sh.get("pid_is_self_program") is False
                   and sh.get("pid") == dead_pid,
                   "pid_alive=False, pid_is_self_program=False（层级归因）")
        case.check("可恢复：serve_alive=False 不挡启动（:246 门放行）",
                   ss.serve_alive(jobs) is False
                   and "if serve_alive(jobs):" in harness.src("hive/serve_start.py"),
                   "重启无假存活阻挡")
        case.check("可追溯：stop()/status() 对陈旧心跳如实留痕文案",
                   "存在陈旧心跳" in harness.src("hive/serve_start.py"),
                   ":205 note 口径")

        # 残余风险如实记录（不改 verdict）
        case.note("残余风险：若 pid 被无关进程复用且映像同名（v13 实测型），"
                  "三层全过＝假活——P1-6「逻辑时钟全域化、墙钟降级展示」待建面输入；"
                  "本格实测仅证明「单层失真不致命」的 P5 判别力")
        verdict = "pass" if not case.fails else "fail"
        case.note("观测汇总：回拨→新鲜层True/端到端False；前跳→新鲜层False")
        return case.finish(verdict, expected="pass")
    finally:
        case.cleanup()


if __name__ == "__main__":
    sys.exit(main())
