# -*- coding: utf-8 -*-
"""FI-R06 · S3 并发（通道交错）→ 消息乱序：WAL 行序交换 + submit 依赖 fail-fast。

两半观测（ask 指定）：
  ① swarm 半边：同一 3 行合法签名 fixture 行序交换（seq=3 行在前）后验签——
     swarm/rust_swarm.py:100-151 验签无次序判据 → 预期 all_valid=True
     （乱序不可检，同 FI-R05 缺口基线，EXPECTED_GAP）。
  ② hive 半边：hive.exe submit 一条 depends_on=["h_notexist_0000"] 的 spec 到
     临时 jobs——hive/src/main.rs:231-245 提交侧依赖完整 fail-fast → 预期 rc=1
     「依赖不完整: …（任务不存在，先提交上游任务）」且 jobs 目录未建任务
     （结构性防御有效：job_id 时间序+提交侧 fail-fast 使「引用未来任务」
     不可能成环，scheduler.rs:535-537 deps_gate 注释在案）。

判据：T2（乱序在失效集内）+ A2 逻辑时序（墙钟仅展示，次序靠 job_id 时间序
结构性保证）。case verdict 取 gap（swarm 半边缺口主导；hive 半边拦截为
pass 面断言同格共存）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

from swarm.rust_swarm import verify_wal_signatures  # noqa: E402

SECRET = "chaos-fi-r06-哑密钥"


def main() -> int:
    case = harness.Case("FI-R06", "WAL 行乱序不可检 + submit 依赖 fail-fast 拦截")
    try:
        # ── ① swarm 半边：行序交换 ──
        tmp = case.tmpdir("r06_wal")
        wal = os.path.join(tmp, "events.jsonl")
        lines = harness.make_wal_fixture(wal, SECRET)
        base = verify_wal_signatures(wal, SECRET)
        case.check("基线 3/3 verified（fixture 正确）",
                   base["verified"] == 3 and base["all_valid"] is True,
                   json.dumps(base, ensure_ascii=False))
        with open(wal, "w", encoding="utf-8", newline="") as f:
            f.write(lines[2])  # seq=3 行提到最前
            f.write(lines[0])
            f.write(lines[1])
        after = verify_wal_signatures(wal, SECRET)
        case.check("①行序交换后 all_valid=True（乱序不可检——缺口基线复现）",
                   after["total"] == 3 and after["bad"] == 0
                   and after["all_valid"] is True,
                   json.dumps(after, ensure_ascii=False))

        # ── ② hive 半边：依赖 fail-fast ──
        jobs = case.tmpdir("r06_jobs")
        rc, out = harness.hive_submit(jobs, {
            "model": "cmd", "user_prompt": "chaos-r06-dep",
            "command": [sys.executable, "-c", "print('never')"],
            "timeout_s": 60,
            "depends_on": ["h_notexist_0000"],
        })
        out1 = out.splitlines()[0] if out.strip() else ""
        case.check("②submit rc=1（fail-fast 拒绝，红=预期拦截）", rc == 1,
                   f"rc={rc} out={out1[:80]}")
        case.check("②错误文案点名「依赖不完整/任务不存在」",
                   "依赖不完整" in out and "任务不存在" in out,
                   out1[:120])
        left = [n for n in os.listdir(jobs) if n.startswith("h")]
        case.check("②jobs 目录未建任务（拒绝发生在进队列前）", left == [],
                   f"残留={left}")
        case.check("②无环性结构性在位（scheduler.rs deps_gate 注释：时间序）",
                   "无环性由 job_id 时间序结构性保证"
                   in harness.src("hive/src/scheduler.rs"),
                   "引用未来任务不可能成环")

        case.note("四可判定（swarm 半边，D4）：乱序可发现=False（all_valid=True "
                  "零信号）/可隔离=False/可追溯=False；可恢复=部分（Rust 重放以"
                  "水位/快照提交点承担时序语义，Python 审计面不覆盖——诚实记录）。"
                  "hive 半边四可全 True：拒收信号明确（可发现）、不建任务（可隔离/"
                  "可恢复）、文案点名依赖 id（可追溯）")
        case.note("缺口登记：同 FI-R05 根因——验签面无 seq 连续性/次序判据"
                  "（P0-2 待建，登记 NEW/P0-2）；两口径：①gap（swarm 审计面）"
                  "+②拦截有效（hive 提交面）")
        verdict = "gap" if not case.fails else "fail"
        return case.finish(verdict, expected="gap")
    finally:
        case.cleanup()


if __name__ == "__main__":
    sys.exit(main())
