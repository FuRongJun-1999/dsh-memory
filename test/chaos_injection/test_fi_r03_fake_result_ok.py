# -*- coding: utf-8 -*-
"""FI-R03 · S6/S4 说谎者候选 → 静默改写：伪造 result.json ok=true 被采信。
（批次53 修复复测：P11 完整性锚落地，本格由 EXPECTED_GAP 转 pass）

原缺口基线（v1.0 实测，登记 NEW/P11-待建）：classify_result（scheduler.rs）只读
盘面 error 字段——无 error 即 done；能写 result.json 的组件可伪造 ok=true 产物
0.4s 内被采信（公理 2：判据落在「组件说成功」而非端到端）。

修复面（批次53）：提交面解析到锚密钥（hive 既有配置/令牌面 env 链
HIVE_ORCH_TOKEN → HIVE_ORCH_TOKEN_FILE → HIVE_API_KEY，keyres.rs）即在
status.json 落 result_nonce（任务声明锚预期）；serve 拉起执行器时注入
HIVE_RESULT_ANCHOR（HMAC-SHA256(密钥, "hive-result-anchor-v1|" +
sha256hex(spec.json 字节) + "|" + nonce)，hmac.rs 唯一公式实现），执行器
（exec.py / exec_cmd.py 契约）原样回写 result_anchor；classify_result 采信
done 前校验——锚缺失 → needs_review（不自动采信）、锚不匹配 → error（拒绝
采信）、无 nonce 的旧格式任务维持旧判据（向后兼容）。

本格注入（全部临时目录 + 哑令牌，不触真实令牌库）：
  A 锚预期任务 + 伪造 ok=true 无锚（原 FI-R03 注入形态）→ needs_review；
  B 锚预期任务 + 攻击者独立重实现公式（正确公式、**错钥**）伪造锚 → error；
  C 锚预期任务 + rerun_on_recover 逃生门 + 伪造无锚 → 更名留痕重投，重跑的
    诚实执行器带锚落地 → done（可疑产物不终局，M1×P11 组合）；
  D 诚实对照：真实 submit（哑锚密钥 env → 锚预期）→ exec_cmd 回写锚 → done
    （诚实链路语义不变）；
  E 向后兼容对照：无密钥提交（显式移除三键）→ result_anchor=off → done。
"""
import hashlib
import hmac as _hmac
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

FAKE_CONTENT = "伪造内容-CHAOS-FI-R03-端到端判据未验证"
# 哑锚密钥（仅本 case 临时面；提交与 serve 两侧同值——模拟已配置的部署）
DUMMY_KEY = "chaos-fi-r03-dummy-anchor-key"
KEY_ENV = {"HIVE_ORCH_TOKEN": DUMMY_KEY}
# 对照组显式移除三把锚密钥键（防宿主机 env 差异引入不确定性）
NO_KEY_ENV = {"HIVE_ORCH_TOKEN": None, "HIVE_ORCH_TOKEN_FILE": None,
              "HIVE_API_KEY": None}
ANCHOR_DOMAIN = "hive-result-anchor-v1"


def forge_anchor_wrong_key(spec_path: str, nonce: str) -> str:
    """攻击者视角独立重实现锚公式（Python hmac/hashlib）——但只有错钥。
    正确公式 + 错误密钥 = 锚不匹配 → error（P11 判据面不可伪造的直证）。"""
    with open(spec_path, "rb") as f:
        spec_sha = hashlib.sha256(f.read()).hexdigest()
    msg = f"{ANCHOR_DOMAIN}|{spec_sha}|{nonce}".encode()
    return _hmac.new(b"attacker-guess-key", msg, hashlib.sha256).hexdigest()


def hand_build_anchored_job(jobs: str, tag: str, spec: dict, result: dict,
                            rerun: bool = False):
    """手搭锚预期任务现场：status 带 result_nonce（模拟锚预期提交面）+
    伪造 result.json（说谎者写面——不跑任何真实执行）。返回 (job_id, dir)。"""
    job_id = f"h{int(time.time()*1000)}_{tag}"  # h 前缀过 list_jobs 过滤
    job_dir = os.path.join(jobs, job_id)
    os.makedirs(job_dir)
    if rerun:
        spec = {**spec, "rerun_on_recover": True}
    with open(os.path.join(job_dir, "spec.json"), "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False)
    now_ms = time.time() * 1000
    with open(os.path.join(job_dir, "status.json"), "w", encoding="utf-8") as f:
        json.dump({"job_id": job_id, "state": "claimed",
                   "created_ts": now_ms, "started_ts": now_ms,
                   "heartbeat_ts": now_ms, "elapsed_s": 0.0,
                   "timeout_s": 60, "model": "cmd", "pid": None,
                   "error": None, "result_nonce": "0f" * 8}, f)
    with open(os.path.join(job_dir, "result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    return job_id, job_dir


def main() -> int:
    case = harness.Case("FI-R03", "伪造 result.json ok=true：P11 完整性锚拦截")
    jobs = None
    try:
        jobs = case.tmpdir("r03_jobs")

        # ── 注入搭建：三个手搭伪造现场（A 无锚 / B 错钥伪锚 / C 逃生门）──
        spec_a = {"model": "cmd", "user_prompt": "chaos-r03-fake"}
        fake = {"ok": True, "content": FAKE_CONTENT,
                "usage": {"total_tokens": 1}, "model": "cmd"}
        a_id, a_dir = hand_build_anchored_job(jobs, "aaaa01", spec_a, dict(fake))
        # B：先搭现场拿 spec 字节，再以攻击者重实现公式（错钥）伪造锚写入
        b_id, b_dir = hand_build_anchored_job(jobs, "bbbb02", spec_a, {})
        wrong = forge_anchor_wrong_key(os.path.join(b_dir, "spec.json"), "0f" * 8)
        with open(os.path.join(b_dir, "result.json"), "w", encoding="utf-8") as f:
            json.dump({**fake, "result_anchor": wrong}, f, ensure_ascii=False)
        # C 的 spec 须可诚实重跑（确定性命令）——逃生门重投后由真实执行器带锚落地
        spec_c = {"model": "cmd", "user_prompt": "chaos-r03-rerun",
                  "command": [sys.executable, "-c", "import time;time.sleep(0.2)"]}
        c_id, c_dir = hand_build_anchored_job(jobs, "cccc03", spec_c, dict(fake),
                                              rerun=True)

        # ── 源码断言：判据面锚门与密钥面在位 ──
        sched_src = harness.src("hive/src/scheduler.rs")
        case.check("classify_result 锚门在位（P11：done 前校验，scheduler.rs）",
                   "verify_result_anchor" in sched_src
                   and "AnchorVerdict::Pass => (\"done\".into(), None)" in sched_src,
                   "锚缺失→needs_review / 失配→error / 通过→done")
        case.check("密钥面只取 hive 既有配置/令牌面（keyres.rs env 链，无公开缺省）",
                   all(k in harness.src("hive/src/keyres.rs")
                       for k in ("HIVE_ORCH_TOKEN", "HIVE_ORCH_TOKEN_FILE",
                                 "HIVE_API_KEY"))
                   and "DEFAULT" not in harness.src("hive/src/keyres.rs").upper(),
                   "不新发明密钥来源（对照 config.local 既有键）")
        case.check("锚公式唯一实现绑定 spec 字节+nonce（hmac.rs ANCHOR_DOMAIN）",
                   'ANCHOR_DOMAIN: &str = "hive-result-anchor-v1"'
                   in harness.src("hive/src/hmac.rs"),
                   "N143 教训：无公开缺省常量密钥")

        # ── 启真实 serve（哑锚密钥 → P11 判据生效；recover_orphans 启动即跑）──
        serve = harness.hive_spawn_serve(jobs, workers=0, env_extra=KEY_ENV)
        case.track_proc(serve)
        t0 = time.time()
        state_a, st_a = harness.wait_state(a_dir, {"needs_review", "done", "error"},
                                           timeout_s=10, poll_s=0.2)
        elapsed = time.time() - t0
        case.check(f"伪造 ok=true 无锚不被采信 done（实测 {elapsed:.1f}s，原 0.4s 即 done）",
                   state_a == "needs_review",
                   f"state={state_a} error={st_a.get('error')}")
        case.check("A 的 error 显式点明锚缺失（T4 静默消除：错误信号在场）",
                   "产物完整性锚缺失" in (st_a.get("error") or ""),
                   str(st_a.get("error"))[:80])
        case.check("A 的伪造产物仍留盘可查（可追溯：不销毁证据）",
                   os.path.isfile(os.path.join(a_dir, "result.json")))

        state_b, st_b = harness.wait_state(b_dir, {"error", "done"},
                                           timeout_s=10, poll_s=0.2)
        case.check("错钥伪造锚被拒绝采信（error 终态）",
                   state_b == "error"
                   and "完整性锚校验失败" in (st_b.get("error") or ""),
                   f"state={state_b} error={str(st_b.get('error'))[:80]}")

        # C：逃生门重投 → 重跑的诚实执行器带锚落地 → done + recovered 留痕
        state_c, st_c = harness.wait_state(c_dir, {"done", "error", "needs_review"},
                                           timeout_s=15, poll_s=0.2)
        archived = any(n.startswith("result.json.recovered-")
                       for n in os.listdir(c_dir))
        case.check("rerun_on_recover 逃生门：可疑产物更名留痕并重投（不终局）",
                   state_c == "done" and archived
                   and "result_anchor" in _read_result(c_dir),
                   f"state={state_c} archived={archived}")

        # ── D 诚实对照：真实 submit（锚预期）→ exec_cmd 回写锚 → done ──
        rc, out = harness.hive_submit(jobs, {
            "model": "cmd", "user_prompt": "chaos-r03-honest",
            "command": [sys.executable, "-c", "import time;time.sleep(0.2)"],
            "timeout_s": 60,
        }, env_extra=KEY_ENV)
        ok_json = json.loads(out.splitlines()[0]) if out.strip() else {}
        d_id = ok_json.get("job_id", "")
        case.check("锚预期提交面生效（submit 响应 result_anchor=on 且 status 落 nonce）",
                   rc == 0 and ok_json.get("result_anchor") == "on"
                   and _read_status_field(os.path.join(jobs, d_id), "result_nonce"),
                   f"resp={ {k: ok_json.get(k) for k in ('job_id', 'result_anchor')} }")
        d_dir = os.path.join(jobs, d_id)
        state_d, _ = harness.wait_state(d_dir, {"done", "error", "needs_review",
                                                "timeout"}, timeout_s=20)
        case.check("诚实执行器（回写锚）照常采信 done（正常链路零回归）",
                   state_d == "done", f"state={state_d}")

        # ── E 向后兼容对照：无密钥提交 → 旧格式任务 → 同 serve 照常 done ──
        rc2, out2 = harness.hive_submit(jobs, {
            "model": "cmd", "user_prompt": "chaos-r03-legacy",
            "command": [sys.executable, "-c", "import time;time.sleep(0.2)"],
            "timeout_s": 60,
        }, env_extra=NO_KEY_ENV)
        ok2 = json.loads(out2.splitlines()[0]) if out2.strip() else {}
        e_id = ok2.get("job_id", "")
        case.check("无密钥提交退回旧格式（result_anchor=off，status 无 nonce）",
                   rc2 == 0 and ok2.get("result_anchor") == "off"
                   and not _read_status_field(os.path.join(jobs, e_id),
                                              "result_nonce"),
                   f"resp={ {k: ok2.get(k) for k in ('job_id', 'result_anchor')} }")
        e_dir = os.path.join(jobs, e_id)
        state_e, _ = harness.wait_state(e_dir, {"done", "error", "needs_review",
                                                "timeout"}, timeout_s=20)
        case.check("旧格式任务在锚判据 serve 上维持旧判据 done（向后兼容）",
                   state_e == "done", f"state={state_e}")

        # ── poll 观测面：伪造产物不再以 done 面目示人 ──
        rc3, out3 = harness.hive_poll(jobs, a_id)
        poll_view = json.loads(out3.splitlines()[0]) if out3.strip() else {}
        view = poll_view.get("job") or {}
        case.check("poll 面如实展示 needs_review + error 文本（零静默）",
                   rc3 == 0 and view.get("state") == "needs_review"
                   and "锚缺失" in (view.get("error") or ""),
                   f"state={view.get('state')}")

        # verify_runner 半边：读码为据（REPO 硬指向真仓无法临时重定向实跑）
        vr = harness.src("hive/verify_runner.py")
        case.check("verify_runner passed>0 门只约束套件执行过（读码 :161-166）",
                   "passed > 0" in vr and "suite_ok" in vr,
                   "不约束盘面已有产物真伪——该半边未实跑，如实标注")
        case.check("verify_runner REPO 硬指向真仓（读码 :26，故无法临时重定向实跑）",
                   "REPO = os.path.dirname(HERE)" in vr, "verify_runner.py:26")

        verdict = "pass" if not case.fails else "fail"
        return case.finish(verdict, expected="pass")
    finally:
        case.cleanup()


def _read_result(job_dir: str) -> dict:
    try:
        with open(os.path.join(job_dir, "result.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _read_status_field(job_dir: str, key: str):
    try:
        with open(os.path.join(job_dir, "status.json"), encoding="utf-8") as f:
            return json.load(f).get(key)
    except (OSError, ValueError):
        return None


if __name__ == "__main__":
    sys.exit(main())
