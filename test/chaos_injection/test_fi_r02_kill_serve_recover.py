# -*- coding: utf-8 -*-
"""FI-R02 · S1 硬件/OS（进程消亡）→ 杀进程：serve 运行中强杀后重启恢复。

判据：T0 失效定理①崩溃类（可观测→可恢复）、D4 四可、A4 诚实公理（无产物
诚实标 error 而非伪装 done）。注入：临时 jobs 目录经真实 hive.exe submit 提交
一条 sleep(8) 的 exec_cmd 任务；serve（--jobs 指临时池、HIVE_EXEC_PY=
exec_cmd.py）起跑至 state=running 后 Popen.kill() 硬杀 serve（执行器树成孤儿）；
确认 status 冻结在 running；重启 serve 触发启动即 recover_orphans
（hive/src/scheduler.rs:153/251-339），轮询至终态——判据唯一实现
classify_result（scheduler.rs:475-495，C9 教训勿分叉），running 无产物诚实标
error「serve 中断：任务执行被重置」（scheduler.rs:319-334）。

附带观测点（ask 指定）：孤儿执行器若稍后补写 result.json，与其 error 终态
并存＝N92 同型矛盾态现场（v17.md:39 留档族），如实记录，留待第二轮专项。
全部注入只在临时 jobs 目录 + 自建进程树，测毕 taskkill /T 清理。
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402


def main() -> int:
    case = harness.Case("FI-R02", "杀 serve 后重启：recover_orphans 崩溃恢复")
    jobs = None
    try:
        jobs = case.tmpdir("r02_jobs")
        # ── 搭建：真实 submit 一条 sleep(8) 确定性任务 ──
        rc, out = harness.hive_submit(jobs, {
            "model": "cmd", "user_prompt": "chaos-r02-sleep",
            "command": [sys.executable, "-c", "import time;time.sleep(8)"],
            "timeout_s": 60,
        })
        ok_json = json.loads(out.splitlines()[0]) if out.strip() else {}
        job_id = ok_json.get("job_id", "")
        job_dir = os.path.join(jobs, job_id)
        case.check("submit 成功（rc=0 且 h 前缀 job_id）",
                   rc == 0 and job_id.startswith("h"), f"rc={rc} id={job_id}")

        # ── serve 起跑至 running ──
        serve1 = harness.hive_spawn_serve(jobs, workers=1)
        case.track_proc(serve1)
        state, st = harness.wait_state(job_dir, "running", timeout_s=25)
        case.check("任务进入 running（serve 已领取并拉起执行器）",
                   state == "running", f"state={state}")
        orphan_pid = st.get("pid")
        case.note(f"执行器 pid（将成为孤儿）={orphan_pid}")

        # ── 注入：硬杀 serve（仅单进程；执行器成孤儿）──
        serve1.kill()
        serve1.wait(timeout=10)
        case.check("serve 已被硬杀（poll 回码非 0 或进程消失）",
                   serve1.poll() is not None)
        # status 冻结观测：1.5s 内三次采样仍 running（无人推进）
        frozen = []
        for _ in range(3):
            try:
                frozen.append(harness.read_status(job_dir).get("state"))
            except (OSError, ValueError):
                frozen.append("<unreadable>")
            time.sleep(0.5)
        case.check("杀后 status 冻结在 running（崩溃可发现：心跳停更+状态残留）",
                   frozen == ["running"] * 3, f"采样={frozen}")
        case.check("心跳陈旧化（_serve.json 停更，可发现判据）",
                   (time.time() * 1000
                    - json.load(open(os.path.join(jobs, "_serve.json"),
                                     encoding="utf-8")).get("ts", 0)) > 1000,
                   "ts 不再刷新")

        # ── 恢复：重启 serve → 启动即 recover_orphans ──
        serve2 = harness.hive_spawn_serve(jobs, workers=1, force=True)
        case.track_proc(serve2)
        state2, st2 = harness.wait_state(
            job_dir, {"error", "done", "timeout", "killed"}, timeout_s=20)
        err_text = st2.get("error") or ""
        case.check("重启后达终态（有限步回合法态，D5 自稳定）",
                   state2 in {"error", "done", "timeout", "killed"},
                   f"state={state2}")
        case.check("无产物→诚实标 error「serve 中断：任务执行被重置」（A4）",
                   state2 == "error" and "serve 中断" in err_text
                   and "任务执行被重置" in err_text,
                   f"error={err_text[:60]}")
        case.check("未伪装 done（recover_orphans 无产物分支不采信空面）",
                   state2 != "done", "")
        case.check("判据唯一实现在位（classify_result：勿再分叉，C9 教训）",
                   "勿再分叉" in harness.src("hive/src/scheduler.rs")
                   and "fn classify_result" in harness.src("hive/src/scheduler.rs"),
                   "scheduler.rs:475-495")

        # ── 附带观测点：孤儿执行器稍后补写 result.json（N92 同型矛盾态现场）──
        t_spawn = st.get("started_ts") or 0
        result_appeared = False
        for _ in range(40):  # 至多再等 10s 让孤儿（8s sleep）落盘
            if os.path.isfile(os.path.join(job_dir, "result.json")):
                result_appeared = True
                break
            time.sleep(0.25)
        if result_appeared:
            with open(os.path.join(job_dir, "result.json"), encoding="utf-8") as f:
                r = json.load(f)
            case.note(f"矛盾态现场确认（N92 同型，留待第二轮专项）："
                      f"孤儿执行器补写 result.json ok={r.get('ok')} 与 "
                      f"state=error 并存——poll 面同屏可见 error 终态+成功产物")
        else:
            case.note("孤儿执行器未在观测窗内补写 result.json（窗口或被回收）"
                      "——矛盾态现场本轮未复现，观测点如实记录")
        case.check("四可·可追溯：error 文本点名「serve 中断」（观测面与决策面同源 P9）",
                   "serve 中断" in (st2.get("error") or ""), "")
        # 可隔离/可恢复由终态收敛与 job 级标注承载；可发现由冻结采样+心跳陈旧承载

        verdict = "pass" if not case.fails else "fail"
        return case.finish(verdict, expected="pass")
    finally:
        # 清理：孤儿执行器（若仍在）与重启的 serve 一并树杀
        try:
            if jobs and orphan_pid:
                subprocess.run(["taskkill", "/PID", str(orphan_pid), "/T", "/F"],
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
        except (OSError, NameError, UnboundLocalError):
            pass
        case.cleanup()


if __name__ == "__main__":
    sys.exit(main())
