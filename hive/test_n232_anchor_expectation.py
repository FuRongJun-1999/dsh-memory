# -*- coding: utf-8 -*-
"""N232 守卫（hive 调度面 · P11 锚预期**可判定性**）：锚预期不可判定时不得回落旧判据 done。

## 病灶（2026-10-05 缺陷挖掘 + 独立复核实测，隔离 serve + 哑令牌 + 系统临时池）

`scheduler.rs::verify_result_anchor` 在「status 不可读」或「status 无 `result_nonce`」
时**一律** `return AnchorVerdict::Pass` → `classify_result` 判 done。于是：

  * 「旧格式任务（本就无锚预期）」与「锚预期被抹除（nonce 被删）」在盘面**同形**，
    旧码把两者并作一态，直接采信 done；
  * 写 result.json 的执行器与 status.json 同处一个 job 目录、无写保护——无钥
    攻击者抹掉 status 的 `result_nonce` 即把伪造产物从 needs_review 降级为 done。

复核者实测：同一份伪造 `{ok:true}` 产物只差 status 是否带 nonce——A 带 nonce →
needs_review（锚缺失）；B 抹 nonce → **done**；C state=running 且抹 nonce → **done**。

## 修法（本守卫钉死的判据：锚预期只有两种来源，都不得与「旧格式」混同）

  ① **本进程内存事实优先**（live 面）：serve 亲手拉起过该任务时，「是否注入锚」由
     spawn 期决策（内存，盘面写者够不着）决定——已注入锚的任务必须回写一致锚，
     盘面 nonce 被抹也救不了它（→ MissingAnchor → needs_review）。
  ② **恢复面 fail-closed**（`recover_orphans` 无内存事实可比，只有盘面可依）：
     **持密钥 serve** 下「无 nonce 记录 / status 不可读」= 锚预期**不可判定**
     （旧格式与抹除同形）→ 不自动采信（needs_review）；**无密钥 serve** 锚判据
     整体未启用 → 旧格式基线零变更（done），此即判据的兼容边界。

## 覆盖面（真 serve × 临时池 × 哑锚密钥；全程系统临时目录，不触在役 serve/池/令牌）

  A 恢复面·锚预期被抹（state=claimed）→ needs_review（修前 done）
  B 恢复面·锚预期被抹（state=running）→ needs_review（修前 done）
  C 恢复面·带 nonce 的伪造产物（原 FI-R03 形态）→ needs_review（两态皆绿：回归）
  D 恢复面·**无密钥** serve + 旧格式任务 → done（两态皆绿：兼容基线零变更）
  E live 面·执行器运行期抹 nonce 再写伪造产物 → needs_review（修前 done）
  F 正常面·诚实链路（submit 锚预期 → exec_cmd.py 回写锚）→ done（两态皆绿：零回归）

## 运行

  python -X utf8 -m hive.test_n232_anchor_expectation      # 退出码 0 = 全绿

编译/serve/池夹具复用 `hive/test_h3_h7_scheduler.py` 的同名单点（crate 副本在系统
临时目录独立编译、CARGO_TARGET_DIR 独立——不写 hive/target/，不碰在役二进制）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for _p in (_REPO, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

# 夹具单点复用（编译副本 / 剔净注入面的 env / serve 拉起与清理 / 临时根登记）
from hive import test_h3_h7_scheduler as H  # noqa: E402

# 哑锚密钥（非真凭据；与判据面的密钥链键名同源，值仅本守卫临时面）
DUMMY_KEY = "n232-guard-dummy-anchor-key"
NONCE = "0f" * 8
TERMINAL = {"done", "error", "timeout", "killed", "needs_review"}

# live 面攻击桩：拉起后**抹掉 status 的 result_nonce** 再写伪造产物，并保持 running
# 一拍以上（让 serve 的心跳把「无 nonce 的 status」照原样回写，攻击面稳定）。
TAMPER_EXEC = r"""
import sys, json, os, time
d = sys.argv[1]
with open(os.path.join(d, "spec.json"), encoding="utf-8") as f:
    json.load(f)
sp = os.path.join(d, "status.json")
try:
    with open(sp, encoding="utf-8") as f:
        st = json.load(f)
except Exception:
    st = {}
st.pop("result_nonce", None)          # 无钥降级攻击：抹除锚预期记录
with open(sp, "w", encoding="utf-8") as f:
    json.dump(st, f, ensure_ascii=False)
with open(os.path.join(d, "result.json"), "w", encoding="utf-8") as f:
    json.dump({"ok": True, "content": "伪造内容-N232-E"}, f, ensure_ascii=False)
time.sleep(2)
"""


def _env_with(extra: dict) -> dict:
    """H._env()（剔净 HIVE_*/MDCG_*）之上叠加 extra；None 值 = 移除。"""
    env = H._env()
    for k, v in extra.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    return env


def _serve(exe, jobs, exec_py, key=None, workers=2, tag="n232"):
    """起真实 serve（--jobs 指临时池）+ 桩执行器；key 非空则注入哑锚密钥。"""
    env = _env_with({"HIVE_EXEC_PY": exec_py, "HIVE_WORKERS": str(workers),
                     "HIVE_ORCH_TOKEN": key})
    logf = open(os.path.join(jobs, "_%s_serve.log" % tag), "ab")
    try:
        p = subprocess.Popen([exe, "serve", "--jobs", jobs,
                              "--workers", str(workers)],
                             stdout=logf, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, env=env, cwd=_REPO)
    finally:
        logf.close()
    H._PROCS.append(p)          # 收尾由 H._cleanup 统一 taskkill /T /F
    return p


def _mk_job(jobs, jid, state, result=None, nonce=None, spec=None, lock=False):
    """手搭任务现场（与判据面 rust 夹具同形：只有盘面、不跑提交面）。"""
    d = os.path.join(jobs, jid)
    os.makedirs(d, exist_ok=True)
    spec = spec if spec is not None else {
        "model": "cmd", "user_prompt": jid, "timeout_s": 60}
    with open(os.path.join(d, "spec.json"), "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False)
    ms = time.time() * 1000
    st = {"job_id": jid, "state": state, "created_ts": ms, "started_ts": ms,
          "heartbeat_ts": ms, "elapsed_s": 0.0, "timeout_s": 60,
          "model": "cmd", "pid": None, "error": None}
    if nonce:
        st["result_nonce"] = nonce
    with open(os.path.join(d, "status.json"), "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    if lock:
        with open(os.path.join(d, "claimed.lock"), "wb"):
            pass
    if result is not None:
        with open(os.path.join(d, "result.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
    return d


def _status(d):
    try:
        with open(os.path.join(d, "status.json"), encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def _wait_terminal(d, timeout_s=12.0):
    """等任务落到终态（done/error/needs_review/…）或超时；返回最终 status。"""
    t0 = time.time()
    st = _status(d)
    while time.time() - t0 < timeout_s:
        st = _status(d)
        if st.get("state") in TERMINAL:
            return st
        time.sleep(0.1)
    return st


def _forged():
    return {"ok": True, "content": "伪造内容-N232", "model": "cmd"}


def _group_restore(exe, key):
    """A–E 组：恢复面（recover_orphans 启动即跑）与 live 面两态对照，同池同 serve。"""
    H.begin("N232-恢复面/live 面")
    tmp = H._tmpdir("n232_restore_")
    jobs, _stub = H._pool(tmp)          # 池 + H 的桩（本组不用它）
    tamper = os.path.join(tmp, "tamper_exec.py")
    with open(tamper, "w", encoding="utf-8") as f:
        f.write(TAMPER_EXEC)

    # A：锚预期被抹（state=claimed，盘面无 nonce）——旧码 done
    a = _mk_job(jobs, "h1700000000n232a", "claimed", _forged(), lock=True)
    # B：同形但 state=running——旧码 done
    b = _mk_job(jobs, "h1700000000n232b", "running", _forged())
    # C：带 nonce 的伪造产物（原 FI-R03 形态）——两态皆 needs_review（回归对照）
    c = _mk_job(jobs, "h1700000000n232c", "claimed", _forged(), nonce=NONCE,
                lock=True)
    # E：live 面——pending + nonce，拉起后由 tamper 桩抹 nonce 并写伪造产物
    e = _mk_job(jobs, "h1700000000n232e", "pending", nonce=NONCE,
                spec={"model": "cmd", "user_prompt": "n232-e",
                      "timeout_s": 60})

    _serve(exe, jobs, tamper, key=key, tag="n232a")
    if not H._wait_serve(jobs):
        H.check("N232 前置：serve 心跳出现", False, "临时池 serve 未进主循环")
        return
    st_a, st_b, st_c, st_e = (_wait_terminal(d, 15.0)
                              for d in (a, b, c, e))

    H.check("A 恢复面：锚预期被抹（claimed+无 nonce）不采信 done",
            st_a.get("state") == "needs_review",
            "state=%s error=%s" % (st_a.get("state"), st_a.get("error")))
    H.check("A 的 error 显式点明锚预期不可判定（非静默）",
            "不可判定" in (st_a.get("error") or ""),
            "error=%r" % (st_a.get("error"),))
    H.check("B 恢复面：锚预期被抹（running+无 nonce）不采信 done",
            st_b.get("state") == "needs_review",
            "state=%s error=%s" % (st_b.get("state"), st_b.get("error")))
    H.check("C 回归：带 nonce 的伪造产物仍按锚缺失拦（needs_review）",
            st_c.get("state") == "needs_review"
            and "产物完整性锚缺失" in (st_c.get("error") or ""),
            "state=%s error=%s" % (st_c.get("state"), st_c.get("error")))
    H.check("E live 面：执行器运行期抹 nonce 也救不了伪造产物（运行态预期在内存）",
            st_e.get("state") == "needs_review",
            "state=%s error=%s" % (st_e.get("state"), st_e.get("error")))
    H.check("E 的 error 点明锚缺失（内存预期优先于盘面抹除）",
            "产物完整性锚缺失" in (st_e.get("error") or ""),
            "error=%r" % (st_e.get("error"),))


def _group_keyless(exe):
    """D 组：无密钥 serve + 旧格式任务 → 旧判据 done（兼容基线零变更）。"""
    H.begin("N232-无密钥基线")
    tmp = H._tmpdir("n232_keyless_")
    jobs, stub = H._pool(tmp)
    d = _mk_job(jobs, "h1700000000n232d", "claimed",
                {"ok": True, "content": "旧格式诚实产物"}, lock=True)
    _serve(exe, jobs, stub, key=None, tag="n232d")
    if not H._wait_serve(jobs):
        H.check("N232 前置（无密钥池）：serve 心跳出现", False, "")
        return
    st = _wait_terminal(d, 15.0)
    H.check("D 无密钥 serve + 旧格式任务 → done（锚判据整体未启用，行为零变更）",
            st.get("state") == "done",
            "state=%s error=%s" % (st.get("state"), st.get("error")))


def _group_honest(exe):
    """F 组：诚实链路端到端——submit（锚预期）→ exec_cmd.py 回写锚 → done。"""
    H.begin("N232-诚实链路零回归")
    tmp = H._tmpdir("n232_honest_")
    jobs, _stub = H._pool(tmp)
    spec = {"model": "cmd", "user_prompt": "n232-f",
            "command": [sys.executable, "-c", "import time; time.sleep(0.3)"],
            "timeout_s": 60}
    sp = os.path.join(tmp, "spec.json")
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False)
    env = _env_with({"HIVE_ORCH_TOKEN": DUMMY_KEY, "PYTHONUTF8": "1",
                     "HIVE_JOB_IDENTITY": "n232守卫", "HIVE_JOB_TASK": "锚预期",
                     "HIVE_JOB_UNIT": "验证单元"})
    p = subprocess.run([exe, "submit", "--spec", sp, "--jobs", jobs],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60, cwd=_REPO, env=env)
    ok = {}
    try:
        ok = json.loads((p.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        ok = {}
    jid = ok.get("job_id") if isinstance(ok, dict) else None
    H.check("F 前置：submit 走锚预期面（result_anchor=on 且 status 落 nonce）",
            p.returncode == 0 and bool(ok.get("result_anchor") == "on")
            and bool(jid),
            "rc=%s resp=%s" % (p.returncode, json.dumps(ok, ensure_ascii=False)[:200]))
    if not jid:
        H.check("F 诚实链路（回写锚）→ done", False, "无 job_id，无法断言")
        return
    d = os.path.join(jobs, jid)
    H.check("F 前置：status 带 result_nonce",
            bool(_status(d).get("result_nonce")), "%s" % sorted(_status(d)))
    _serve(exe, jobs, os.path.join(_HERE, "exec_cmd.py"), key=DUMMY_KEY,
           tag="n232f")
    if not H._wait_serve(jobs):
        H.check("N232 前置（诚实链池）：serve 心跳出现", False, "")
        return
    st = _wait_terminal(d, 25.0)
    H.check("F 诚实执行器（回写锚）照常采信 done（正常链路零回归）",
            st.get("state") == "done",
            "state=%s error=%s" % (st.get("state"), st.get("error")))


def main() -> int:
    exe = H._exe()
    if exe is None:
        H.check("N232 前置：crate 副本编译出可执行件", False,
                "见上方 cargo 日志尾（本守卫需要 rust 工具链现场编译）")
        H._cleanup()
        H._cleanup_persist()
        return 1
    try:
        _group_restore(exe, DUMMY_KEY)
        _group_keyless(exe)
        _group_honest(exe)
    finally:
        H._cleanup()
        H._cleanup_persist()
    print("\n结果: %d fail" % len(H.FAILS))
    return 0 if not H.FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
