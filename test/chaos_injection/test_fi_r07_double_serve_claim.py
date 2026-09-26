# -*- coding: utf-8 -*-
"""FI-R07 · S3 并发（重复投递）→ 双 serve 竞争同一任务：claim 原子锁恰好一次
+ 提交面 content-hash 幂等键。

判据：T7 幂等必要性 + D6（N 次投递效果=1 次执行）。注入：临时 jobs 目录
submit 1 条 exec_cmd 任务（命令体向池外哨兵文件追加计数——执行痕迹的确定性
观测面），同时拉起两个真实 hive serve（第二个 --force 越过单实例守卫，
HIVE_EXEC_PY=exec_cmd.py）竞争领取；任务终态后再留 0.5s 重复执行窗。
判据面：hive/src/job.rs claim=create_new 原子锁、new_job_id、
scheduler.rs claim 失败即静默跳过。

主观测（回归守卫，pass）：恰好一个 done、单份 result.json、哨兵计数=1
（败者走 claim=false 路径不产生第二次执行）。
守卫面（批次53 幂等键落地，P0-2 次观测结案转守卫）：spec canonical json
sha256（hive/src/json.rs::to_canonical_string 键序/空白不敏感 × hmac::sha256）
为 content_hash——同哈希**活跃**任务（pending/claimed/running）存在时重复
submit 返回既有 job_id + deduplicated=true 不新建；不同 spec → 不同 job；
任务完成后重提 → 新建（重跑语义不变）；无 content_hash 的旧格式任务不参与
去重（向后兼容）。

历史基线（批次52 实测，已结案）：修复前同 spec 重复 submit 得两个不同
job_id/两任务目录（提交面无 content-hash 幂等键，v0.3 矩阵「T2/T7 幂等🟡」
另一面），本批次随幂等键落地转绿。
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

        # ── 注入：双 serve 先就位 → 后投递（重复投递面=两扫描循环竞争同一任务）──
        # 时序依据：recover_orphans 是 serve **启动时点**行为——先投递再拉第二个
        # serve 会让其启动恢复扫掉首个 serve 的在飞任务（批次53 实测踩坑：
        # "serve 中断：任务执行被重置"）；双活稳态后投递，竞争纯粹落在
        # claimed.lock 原子锁上，恢复语义零参与。
        s1 = harness.hive_spawn_serve(jobs, workers=1)
        case.track_proc(s1)
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
        time.sleep(0.8)  # s2 启动恢复（空池）扫完的余量，此后投递

        rc, out = harness.hive_submit(jobs, {
            "model": "cmd", "user_prompt": "chaos-r07-race",
            "command": [sys.executable, "-c", cmd],
            "timeout_s": 60,
        })
        job_id = json.loads(out.splitlines()[0]).get("job_id", "")
        job_dir = os.path.join(jobs, job_id)
        case.check("submit 成功（rc=0）", rc == 0 and job_id.startswith("h"),
                   f"id={job_id}")

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

        # ── 守卫面（批次53 幂等键）：同 spec 重复 submit → 同 job_id ──
        # 先停双 serve（重复投递观测已完成）：无执行器在场 → dup 任务保持
        # pending，幂等判定确定性成立（不被「已终态」时序抖动污染）。
        s1.kill()
        s1.wait(timeout=10)
        s2.kill()
        s2.wait(timeout=10)
        case.check("双 serve 已停（守卫面确定性前置）",
                   s1.poll() is not None and s2.poll() is not None, "")
        spec_dup = {"model": "cmd", "user_prompt": "chaos-r07-dup",
                    "command": [sys.executable, "-c", "print('dup')"],
                    "timeout_s": 60}
        rc2a, out2a = harness.hive_submit(jobs, spec_dup)
        ja = json.loads(out2a.splitlines()[0])
        ida = ja.get("job_id", "")
        case.check("守卫①：首次提交新建（deduplicated=false + content_hash 透出）",
                   rc2a == 0 and ja.get("deduplicated") is False
                   and ida.startswith("h")
                   and len(ja.get("content_hash", "")) == 64,
                   f"id={ida} dedup={ja.get('deduplicated')}")
        rc2b, out2b = harness.hive_submit(jobs, spec_dup)
        jb = json.loads(out2b.splitlines()[0])
        case.check("守卫②：同 spec 重复提交 → 同 job_id + deduplicated=true（不新建）",
                   rc2b == 0 and jb.get("deduplicated") is True
                   and jb.get("job_id") == ida,
                   f"{ja.get('job_id')} vs {jb.get('job_id')} dedup={jb.get('deduplicated')}")
        dup_dirs = []
        for n in os.listdir(jobs):
            sp = os.path.join(jobs, n, "spec.json")
            if os.path.isfile(sp):
                with open(sp, encoding="utf-8") as f:
                    if json.load(f).get("user_prompt") == "chaos-r07-dup":
                        dup_dirs.append(n)
        case.check("守卫③：池内同内容任务目录恰 1 份（幂等=零重复任务）",
                   len(dup_dirs) == 1, f"dup_dirs={dup_dirs}")
        rc2c, out2c = harness.hive_submit(jobs, {**spec_dup,
                                                 "user_prompt": "chaos-r07-dup-不同内容"})
        jc = json.loads(out2c.splitlines()[0])
        case.check("守卫④：不同 spec → 不同 job（deduplicated=false）",
                   rc2c == 0 and jc.get("deduplicated") is False
                   and jc.get("job_id") != ida,
                   f"{ida} vs {jc.get('job_id')}")
        # 守卫⑤：终态不拦重跑——按文件协议把 dup 任务置 done（宿主侧合法操作）
        # 后重提同 spec → 必须新建（重跑语义不变）
        st_path = os.path.join(jobs, ida, "status.json")
        with open(st_path, encoding="utf-8") as f:
            st = json.load(f)
        st["state"] = "done"
        with open(st_path, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
        rc2d, out2d = harness.hive_submit(jobs, spec_dup)
        jd = json.loads(out2d.splitlines()[0])
        case.check("守卫⑤：任务完成后重提 → 新建（deduplicated=false，重跑语义不变）",
                   rc2d == 0 and jd.get("deduplicated") is False
                   and jd.get("job_id") != ida,
                   f"old={ida} new={jd.get('job_id')}")
        case.check("守卫⑥：幂等键在源码（find_active_by_hash × canonical sha256）",
                   "find_active_by_hash" in harness.src("hive/src/main.rs")
                   and "to_canonical_string" in harness.src("hive/src/main.rs")
                   and "deduplicated" in harness.src("hive/src/main.rs"),
                   "批次53 落地 hive/src/main.rs cmd_submit")

        case.note("守卫面口径（P0-2 次观测结案，批次53）：幂等键=spec canonical "
                  "json sha256（键序/空白不敏感）；只拦**活跃**任务（pending/"
                  "claimed/running），终态不拦=重跑语义不变；无 content_hash 的"
                  "旧格式任务不参与去重（向后兼容）；v0 边界=MCP Python 提交面"
                  "（hive_mcp/mcp_server.py:_submit 独立实现）未纳入本面、并发"
                  "双提 nanosec 竞窗不设锁（v0 最小面，如实声明）")

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
