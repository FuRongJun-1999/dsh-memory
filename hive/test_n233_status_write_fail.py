# -*- coding: utf-8 -*-
"""N233 守卫（hive 调度面 · worker 终态/心跳状态改写**不得静默失败**）。

## 病灶（2026-10-05 缺陷挖掘，读码 + 本守卫实测）

`scheduler.rs::run_job` 的 worker 终态改写与心跳改写都用 `let _ = job::patch_status(...)`
/ `let _ = job::heartbeat(...)` **吞错**（无重试、无告警、无留痕）：

  * 瞬态失败（Windows 读者瞬态句柄 WinError 5/32 之类）：一次失败即放弃——
    result.json 已在位而 state 永不落终态；poll/doctor 恒报 claimed/running；
    下游经 `deps_gate` 对非 done 上游**永久悬置**，只有 serve 重启由
    `recover_orphans` 收敛；
  * 永久失败（status.json 只读/盘满）：连重启也改不动，且**零信号**——
    故障完全不可见。

与同文件 N191 已确立的「状态改写**不得吞错**」（主循环领取面：改写失败即回滚领取锁
并 stderr 告警，见 scheduler.rs 领取段注释 + judgment_surface::claim_rollback_*）
自相矛盾：同一条纪律在 worker 面被 `let _` 抹掉。

## 修法（本守卫钉死的判据）

  ① **瞬态自愈**：终态写入走 H-4 已确立的**有界退避重试**单点（`retry_spawn`
     ——同一实现，不另造第二份重试判据）；重试后成功也必须留痕（attempts>1 →
     serve stderr 一行），不静默消化。
  ② **永久失败不静默**：重试耗尽 → serve stderr 显式告警（点名 job_id/state/原因）
     + 落**独立标记文件** `status.writefail.json`（H-3 `status.corrupt.json` 同款：
     旁证文件，**绝不改写 status.json 本体**）——盘面只读时状态物理上写不进去，
     能做的正是「让失败可发现」，这不是终态化的替代品。
  ③ **心跳失败不静默**：首次失败告警一行（后续每拍重试，不刷屏）。

## 覆盖面（真 serve × 临时池 × 只读注入；全程系统临时目录，不触在役 serve/池）

  A 永久只读：终态写入重试耗尽 → 标记文件落场 + stderr 告警点名；state 如实非终态
  A' 标记文件字段齐备（job_id/kind/state/error/detected_ts），且 status.json 本体
     **逐字节未被改写**（旁证不改本体）
  B 瞬态只读（结果产出后 ~2.5s 解除）：无需重启 serve 即**自愈**收敛到 done
    （修前：一次失败即吞 → 永久 claimed/running）
  C 零回归：无注入时（干净池）任务照常 done、且**不落**标记文件

## 运行

  python -X utf8 -m hive.test_n233_status_write_fail    # 退出码 0 = 全绿

只读注入用 `attrib +R`（与 judgment_surface::claim_rollback_on_status_write_failure
同法：Windows 上 rename 覆盖只读目标 = WinError 5，实测确定性失败）；非 Windows
平台本组无法构造该注入，如实打印 SKIP 并跳过（不计红）。
编译/serve/池夹具复用 `hive/test_h3_h7_scheduler.py` 同名单点。
"""
from __future__ import annotations

import json
import os
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

from hive import test_h3_h7_scheduler as H  # noqa: E402 —— 夹具单点复用

MARK = "status.writefail.json"
TERMINAL = {"done", "error", "timeout", "killed", "needs_review"}

# 桩执行器：睡 3s 再写产物（给只读注入留出确定窗口）
SLOW_EXEC = r"""
import sys, json, os, time
d = sys.argv[1]
with open(os.path.join(d, "spec.json"), encoding="utf-8") as f:
    json.load(f)
time.sleep(3)
with open(os.path.join(d, "result.json"), "w", encoding="utf-8") as f:
    json.dump({"ok": True, "content": "n233-stub"}, f, ensure_ascii=False)
"""


def _set_readonly(path: str, ro: bool) -> bool:
    """`attrib +R/-R`（判据同 rust 夹具：Windows 上覆盖只读目标必 WinError 5）。"""
    p = subprocess.run(["attrib", "+R" if ro else "-R", path],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return p.returncode == 0


def _mk_pending(jobs: str, jid: str):
    d = os.path.join(jobs, jid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "spec.json"), "w", encoding="utf-8") as f:
        json.dump({"model": "cmd", "user_prompt": jid, "timeout_s": 60}, f,
                  ensure_ascii=False)
    with open(os.path.join(d, "status.json"), "w", encoding="utf-8") as f:
        json.dump({"job_id": jid, "state": "pending", "created_ts":
                   time.time() * 1000, "started_ts": None, "heartbeat_ts": None,
                   "elapsed_s": 0.0, "timeout_s": 60, "model": None,
                   "pid": None, "error": None}, f, ensure_ascii=False)
    return d


def _status(d: str) -> dict:
    try:
        with open(os.path.join(d, "status.json"), encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def _pool(tmp: str):
    jobs = os.path.join(tmp, "jobs")
    os.makedirs(jobs, exist_ok=True)
    stub = os.path.join(tmp, "slow_exec.py")
    with open(stub, "w", encoding="utf-8") as f:
        f.write(SLOW_EXEC)
    return jobs, stub


def _serve(exe, jobs, stub, tag):
    env = H._env()
    env["HIVE_EXEC_PY"] = stub
    env["HIVE_WORKERS"] = "1"
    logf = open(os.path.join(jobs, "_%s_serve.log" % tag), "ab")
    try:
        p = subprocess.Popen([exe, "serve", "--jobs", jobs, "--workers", "1"],
                             stdout=logf, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, env=env, cwd=_REPO)
    finally:
        logf.close()
    H._PROCS.append(p)
    return p


def _log(jobs: str, tag: str) -> str:
    try:
        with open(os.path.join(jobs, "_%s_serve.log" % tag), encoding="utf-8",
                  errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _wait(pred, timeout_s: float, interval: float = 0.1) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if pred():
            return True
        time.sleep(interval)
    return bool(pred())


def _group_permanent(exe):
    """A/A'：永久只读 → 重试耗尽 → 标记 + 告警（修前：零信号）。"""
    H.begin("N233-永久只读")
    tmp = H._tmpdir("n233_perm_")
    jobs, stub = _pool(tmp)
    d = _mk_pending(jobs, "h1700000000n233a")
    sp = os.path.join(d, "status.json")
    _serve(exe, jobs, stub, "n233a")
    if not H._wait_serve(jobs):
        H.check("N233 前置（永久组）：serve 心跳出现", False, "")
        return
    H.check("A 前置：任务被领取（state 离开 pending）",
            _wait(lambda: _status(d).get("state") in ("claimed", "running"), 15.0),
            "state=%s" % _status(d).get("state"))
    _set_readonly(sp, True)
    # 逐字节基准取「只读就位之后」——本断言的判据是「失败期间写面不得再动本体」，
    # 不是「整个生命周期不变」（领取态改写是正常写面，早于只读注入）。
    raw_before = H._raw(sp)
    try:
        # 重试窗（约 11s）+ 余量
        landed = _wait(lambda: os.path.isfile(os.path.join(d, MARK)), 30.0)
        log = _log(jobs, "n233a")
        mk = {}
        try:
            with open(os.path.join(d, MARK), encoding="utf-8") as f:
                mk = json.load(f)
        except (OSError, ValueError):
            mk = {}
        H.check("A 终态写入重试耗尽后落标记文件（永不静默）", landed,
                "目录=%s" % sorted(_files(d)))
        H.check("A' 标记字段齐备且点名任务与原因",
                mk.get("job_id") == "h1700000000n233a"
                and mk.get("kind") == "status_write_failed"
                and bool(mk.get("state"))
                and bool(mk.get("error"))
                and isinstance(mk.get("detected_ts"), (int, float)),
                "marker=%s" % json.dumps(mk, ensure_ascii=False)[:300])
        H.check("A' status.json 本体逐字节未被改写（旁证文件不改本体）",
                H._raw(sp) == raw_before,
                "before=%d bytes after=%s" % (
                    len(raw_before or b""),
                    len(H._raw(sp) or b"")))
        H.check("A serve stderr 显式告警（点名 job_id 且言明写入失败）",
                "h1700000000n233a" in log and "终态写入失败" in log,
                "log 尾=%r" % log[-300:])
        H.check("A state 如实停在非终态（盘面写不进去就不谎报终态）",
                _status(d).get("state") not in TERMINAL,
                "state=%s" % _status(d).get("state"))
        H.check("A' 重试残留的同名 tmp 已清理（任务目录不留写面垃圾）",
                not any(n.startswith("status.tmp") for n in _files(d)),
                "目录=%s" % sorted(_files(d)))
    finally:
        _set_readonly(sp, False)     # temp 目录须可回收


def _files(d):
    try:
        return set(os.listdir(d))
    except OSError:
        return set()


def _group_transient(exe):
    """B：瞬态只读 → 重试自愈到 done（修前：一次失败即吞 → 永久 claimed/running）。"""
    H.begin("N233-瞬态自愈")
    tmp = H._tmpdir("n233_trans_")
    jobs, stub = _pool(tmp)
    d = _mk_pending(jobs, "h1700000000n233b")
    sp = os.path.join(d, "status.json")
    _serve(exe, jobs, stub, "n233b")
    if not H._wait_serve(jobs):
        H.check("N233 前置（瞬态组）：serve 心跳出现", False, "")
        return
    H.check("B 前置：任务被领取", _wait(
        lambda: _status(d).get("state") in ("claimed", "running"), 15.0),
        "state=%s" % _status(d).get("state"))
    _set_readonly(sp, True)
    try:
        # 产物落场 → 等首次（失败的）终态写入发生 → 解除只读
        wrote = _wait(lambda: os.path.isfile(os.path.join(d, "result.json")), 20.0)
        H.check("B 前置：桩执行器产出 result.json", wrote, "")
        time.sleep(2.5)
        _set_readonly(sp, False)
        healed = _wait(lambda: _status(d).get("state") == "done", 30.0)
        H.check("B 无重启即自愈收敛到 done（有界退避重试吸收瞬态失败）",
                healed, "state=%s" % _status(d).get("state"))
        H.check("B 自愈不落失败标记（重试成功不是事故）",
                not os.path.isfile(os.path.join(d, MARK)),
                "目录=%s" % sorted(_files(d)))
    finally:
        _set_readonly(sp, False)


def _group_clean(exe):
    """C：零回归——干净池照常 done 且不落标记。"""
    H.begin("N233-零回归")
    tmp = H._tmpdir("n233_clean_")
    jobs, stub = _pool(tmp)
    d = _mk_pending(jobs, "h1700000000n233c")
    _serve(exe, jobs, stub, "n233c")
    if not H._wait_serve(jobs):
        H.check("N233 前置（干净组）：serve 心跳出现", False, "")
        return
    ok = _wait(lambda: _status(d).get("state") == "done", 25.0)
    H.check("C 干净池照常 done（零回归）", ok, "state=%s" % _status(d).get("state"))
    H.check("C 未落失败标记", not os.path.isfile(os.path.join(d, MARK)),
            "目录=%s" % sorted(_files(d)))


def main() -> int:
    exe = H._exe()
    if exe is None:
        H.check("N233 前置：crate 副本编译出可执行件", False,
                "见上方 cargo 日志尾（本守卫需要 rust 工具链现场编译）")
        H._cleanup()
        H._cleanup_persist()
        return 1
    try:
        if os.name != "nt":
            print("SKIP：只读注入（attrib +R）仅 Windows 成立——POSIX 的 rename 由"
                  "目录权限决定，本组注入不成立，如实跳过。")
        else:
            _group_permanent(exe)
            _group_transient(exe)
        _group_clean(exe)
    finally:
        H._cleanup()
        H._cleanup_persist()
    print("\n结果: %d fail" % len(H.FAILS))
    return 0 if not H.FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
