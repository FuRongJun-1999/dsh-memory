# -*- coding: utf-8 -*-
"""FI-R07 · S3 并发（重复投递）→ 双 serve 竞争同一任务：claim 原子锁恰好一次。

判据：T7 幂等必要性 + D6（N 次投递效果=1 次执行）。注入：临时 jobs 目录
submit 1 条 exec_cmd 任务（命令体向池外哨兵文件追加计数——执行痕迹的确定性
观测面），同时拉起两个真实 hive serve（第二个 --force 越过单实例守卫，
HIVE_EXEC_PY=exec_cmd.py）竞争领取；任务终态后再留 0.5s 重复执行窗。
判据面：hive/src/job.rs:123-129 claim=CreateFile create_new 原子锁、
:39-42 new_job_id、scheduler.rs:214-216 claim 失败即静默跳过。

主观测（回归守卫，pass）：恰好一个 done、单份 result.json、哨兵计数=1
（败者走 claim=false 路径不产生第二次执行）。
次观测（P0-2 已知基线记录，不计 verdict）：同 spec 重复 submit 两次得两个
不同 job_id/两任务目录——提交面无 content-hash 幂等键（v0.3 矩阵
「T2/T7 幂等 🟡、P0-2 待建」）。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402


def main() -> int:
    case = harness.Case("FI-R07", "双 serve 竞争领取：claim 原子锁恰好一次")
    try:
        jobs = case.tmpdir("r07_jobs")
        sentinel = os.path.join(case.tmpdir("r07_sentinel"), "exec_trace.txt")
        cmd = (f"open(r'{sentinel}','a',encoding='utf-8').write('x\\n')")

        rc, out = harness.hive_submit(jobs, {
            "model": "cmd", "user_prompt": "chaos-r07-race",
            "command": [sys.executable, "-c", cmd],
            "timeout_s": 60,
        })
        job_id = json.loads(out.splitlines()[0]).get("job_id", "")
        job_dir = os.path.join(jobs, job_id)
        case.check("submit 成功（rc=0）", rc == 0 and job_id.startswith("h"),
                   f"id={job_id}")

        # ── 注入：两个 serve 同时竞争 ──
        s1 = harness.hive_spawn_serve(jobs, workers=1)
        case.track_proc(s1)
        # 等第一个 serve 心跳在位，再 --force 拉第二个（越过单实例守卫的合法入口）
        hb = os.path.join(jobs, "_serve.json")
        for _ in range(40):
            if os.path.isfile(hb):
                break
            time.sleep(0.1)
        s2 = harness.hive_spawn_serve(jobs, workers=1, force=True)
        case.track_proc(s2)
        case.check("双 serve 均在跑（重复投递面成立）",
                   s1.poll() is None and s2.poll() is None,
                   f"pids={s1.pid},{s2.pid}")

        state, st = harness.wait_state(job_dir, {"done", "error", "timeout",
                                                 "killed"}, timeout_s=30)
        time.sleep(0.5)  # 终态后再留 0.5s 重复执行窗

        case.check("主观测①：终态恰为 done（唯一胜者跑完）",
                   state == "done", f"state={state} error={st.get('error')}")
        with open(os.path.join(job_dir, "result.json"), encoding="utf-8") as f:
            result = json.load(f)
        case.check("主观测②：result.json 单份且执行痕迹计数=1（N 投递=1 执行）",
                   result.get("ok") is True
                   and os.path.isfile(sentinel)
                   and open(sentinel, encoding="utf-8").read().count("x") == 1,
                   f"sentinel={open(sentinel, encoding='utf-8').read().count('x') if os.path.isfile(sentinel) else '缺失'}")
        tmp_residue = [n for n in os.listdir(job_dir)
                       if n.startswith("result.json.") and n.endswith(".tmp")]
        case.check("主观测③：无 .tmp 残留、claimed.lock 恰一份（锁未双持痕迹）",
                   tmp_residue == [] and os.path.isfile(os.path.join(job_dir,
                                                                    "claimed.lock")),
                   f"tmp 残留={tmp_residue}")
        case.check("判据面在位：claim=create_new 原子锁（job.rs:123-129）",
                   "create_new(true)" in harness.src("hive/src/job.rs"),
                   "多 serve 竞争只有一胜者")
        case.check("败者路径在位：claim 失败即跳过（scheduler.rs:214-216）",
                   "if !job::claim(&dir) {" in harness.src("hive/src/scheduler.rs"),
                   "静默跳过不损坏数据")

        # ── 次观测：提交面幂等性（P0-2 基线，不改 verdict）──
        rc2a, out2a = harness.hive_submit(jobs, {
            "model": "cmd", "user_prompt": "chaos-r07-dup",
            "command": [sys.executable, "-c", "print('dup')"], "timeout_s": 60})
        rc2b, out2b = harness.hive_submit(jobs, {
            "model": "cmd", "user_prompt": "chaos-r07-dup",
            "command": [sys.executable, "-c", "print('dup')"], "timeout_s": 60})
        ida = json.loads(out2a.splitlines()[0]).get("job_id", "")
        idb = json.loads(out2b.splitlines()[0]).get("job_id", "")
        both_dirs = os.path.isdir(os.path.join(jobs, ida)) and \
            os.path.isdir(os.path.join(jobs, idb))
        case.check("次观测：同 spec 两次 submit → 两个不同 job_id/两任务目录"
                   "（结构性无内容去重——T7 提交面另一面）",
                   rc2a == 0 and rc2b == 0 and ida != idb and both_dirs,
                   f"{ida} vs {idb}")
        case.note("次观测=P0-2 已知基线（不计 verdict）：提交面无 content-hash "
                  "幂等键，重复提交产生重复任务（v0.3 矩阵 T2/T7 幂等🟡、"
                  "P0-2 待建）；领取面以文件系统原子原语吸收重复投递——"
                  "两面对照即本格证据")

        # 四可（领取面）
        case.check("四可（领取面）：可发现/可隔离/可恢复/可追溯",
                   os.path.isfile(sentinel)
                   and open(sentinel, encoding="utf-8").read().count("x") == 1
                   and state == "done",
                   "重复投递零额外执行（无损害即无可发现项需触发）；执行痕迹"
                   "唯一（可追溯）；败者无副作用（可隔离）；终态收敛 done（可恢复）")

        verdict = "pass" if not case.fails else "fail"
        return case.finish(verdict, expected="pass")
    finally:
        case.cleanup()


if __name__ == "__main__":
    sys.exit(main())
