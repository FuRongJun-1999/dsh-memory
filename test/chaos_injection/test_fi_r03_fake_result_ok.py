# -*- coding: utf-8 -*-
"""FI-R03 · S6/S4 说谎者候选 → 静默改写：伪造 result.json ok=true 被采信。

判据：T4 静默错误支配 / T12 端到端 / 公理 2（v0.1：能写 result.json 的组件
就能直写满足判据的假产物）。注入：临时 jobs 目录手工搭任务现场（目录名须 h
前缀——list_jobs 过滤规则 job.rs:192-204）+ spec.json + status(state=claimed)
+ 伪造 result.json {"ok":true,"content":"伪造内容"}，启真实 serve 即跑
recover_orphans（scheduler.rs:257-294 claimed 分支），classify_result
（:475-495）只读盘面 error 字段——无 error 字段即判 done。

理论预期（已知缺口基线，EXPECTED_GAP）：双双不拦——终态判据落在「组件说
成功」（盘面 ok/无 error）而非端到端原文/committed 上；0.4s 粒度轮询内被采信
state→done，poll 面展示伪造内容，零拦截。verify_runner 的 passed>0 门
（hive/verify_runner.py:161-166）约束的是「验证器执行过套件」，不约束盘面
已有产物真伪；其 REPO 硬指向真仓（verify_runner.py:26）无法临时重定向——
该半边以读码为据、未实跑（源断言在案）。本格输入 P11 完整性锚（判据面不可
伪造）与 M1 逃生门 rerun_on_recover（scheduler.rs:261-270 已在位）组合设计。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

FAKE_CONTENT = "伪造内容-CHAOS-FI-R03-端到端判据未验证"


def main() -> int:
    case = harness.Case("FI-R03", "伪造 result.json ok=true：终态判据被静默改写")
    try:
        jobs = case.tmpdir("r03_jobs")
        job_id = f"h{int(time.time()*1000)}_deadbeef"  # h 前缀过 list_jobs 过滤
        job_dir = os.path.join(jobs, job_id)
        os.makedirs(job_dir)
        with open(os.path.join(job_dir, "spec.json"), "w", encoding="utf-8") as f:
            json.dump({"model": "cmd", "user_prompt": "chaos-r03-fake"}, f)
        now_ms = time.time() * 1000
        with open(os.path.join(job_dir, "status.json"), "w", encoding="utf-8") as f:
            json.dump({"job_id": job_id, "state": "claimed",
                       "created_ts": now_ms, "started_ts": now_ms,
                       "heartbeat_ts": now_ms, "elapsed_s": 0.0,
                       "timeout_s": 60, "model": "cmd", "pid": None,
                       "error": None}, f)
        # ── 注入：伪造产物（说谎者写面——不跑任何真实执行）──
        with open(os.path.join(job_dir, "result.json"), "w", encoding="utf-8") as f:
            json.dump({"ok": True, "content": FAKE_CONTENT,
                       "usage": {"total_tokens": 1}, "model": "cmd"}, f)

        case.check("list_jobs 过滤规则在位（h 前缀，job.rs:192-204）",
                   'name.starts_with("h")' in harness.src("hive/src/job.rs"),
                   "手搭现场目录名合法（结构性入场无阻）")
        case.check("classify_result 只读盘面 error 字段（scheduler.rs:480-489）",
                   '.get("error")' in harness.src("hive/src/scheduler.rs")
                   and '("done".into(), None)' in harness.src("hive/src/scheduler.rs"),
                   "无 error 字段即 done——判据落在「组件说成功」")

        # ── 启真实 serve（--workers 0 → clamp 1；recover_orphans 启动即跑）──
        serve = harness.hive_spawn_serve(jobs, workers=0)
        case.track_proc(serve)
        t0 = time.time()
        state, st = harness.wait_state(job_dir, {"done", "error"}, timeout_s=10,
                                       poll_s=0.4)
        elapsed = time.time() - t0

        case.check(f"0.4s 粒度轮询内被采信 state=done（实测 {elapsed:.1f}s）",
                   state == "done", f"state={state} error={st.get('error')}")
        rc, out = harness.hive_poll(jobs, job_id)
        poll_view = json.loads(out.splitlines()[0]) if out.strip() else {}
        view = poll_view.get("job") or {}  # poll 单查形态：{"ok":..,"job":{...}}
        head = (view.get("result") or {}).get("content_head", "")
        case.check("poll 观测面展示伪造内容（零拦截、零告警）",
                   rc == 0 and view.get("state") == "done"
                   and FAKE_CONTENT in head,
                   f"content_head={head[:40]}")
        case.check("全程无任何 error 标注（T4 静默：错误信号不在场）",
                   view.get("error") is None
                   and (view.get("result") or {}).get("content_truncated") is not None,
                   "盘面自洽——说谎者产物被当真源")

        # verify_runner 半边：读码为据（REPO 硬指向真仓无法临时重定向）
        vr = harness.src("hive/verify_runner.py")
        case.check("verify_runner passed>0 门只约束套件执行过（读码 :161-166）",
                   "passed > 0" in vr and "suite_ok" in vr,
                   "不约束盘面已有产物真伪——该半边未实跑，如实标注")
        case.check("verify_runner REPO 硬指向真仓（读码 :26，故无法临时重定向实跑）",
                   "REPO = os.path.dirname(HERE)" in vr, "verify_runner.py:26")

        # 逃生门在位性（组合方案输入）：spec 显式 rerun_on_recover 可拒采信旧产物
        case.check("M1 逃生门 rerun_on_recover 在位（scheduler.rs:261/:299）",
                   "spec_rerun_on_recover" in harness.src("hive/src/scheduler.rs"),
                   "但缺省=false——默认路径仍采信伪造产物")

        case.note("缺口基线（EXPECTED_GAP，登记 NEW/P11-待建）：能写 result.json "
                  "的组件即可直写满足判据的假产物（公理 2）——终态判据面缺完整性锚；"
                  "修复方向=P11 判据面不可伪造（如产物签名/端到端 committed 判据）"
                  "+ M1 逃生门组合")
        verdict = "gap" if not case.fails else "fail"
        return case.finish(verdict, expected="gap")
    finally:
        case.cleanup()


if __name__ == "__main__":
    sys.exit(main())
