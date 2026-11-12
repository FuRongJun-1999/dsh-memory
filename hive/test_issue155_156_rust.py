# -*- coding: utf-8 -*-
"""issue #155① / #156⑥⑦ · Rust 侧守卫（K 组 · task-49）
============================================================================
覆盖（逐条给「行为面」优先、源断言兜底）：

  [1] #155① **领取前**查 kill 标志（scheduler.rs serve 主循环）
      —— pending 任务在**被领取之前**就已带 kill 标志时，执行器必须**从未被拉起**，
      且任务终态直接落 killed。
      判别器 = 哑执行器写下的 SPAWNED.marker：
        修复前 → serve 照常 claim + spawn（marker 出现），~1 拍后才 kill_tree；
        修复后 → marker **永不出现**，state 直接 killed。
  [2] #156⑥ 终态落盘后删除 kill 标志（land_final_status）
        修复前 → kill 文件永久残留；修复后 → 终态落盘即删。
  [3] 对照组：**无** kill 标志的正常任务照旧被拉起（marker 必须出现）
      ——证明 [1] 的闸只拦「已被 kill」的任务，不滥杀正常路径。
  [4] #156⑦ 源断言（unix 臂真实群杀 win32 不可动态验证，同
      test_stop_tree_kill.py 已声明的诚实边界）：
        · spawn_executor 以 process_group(0) 令执行器自成进程组（群杀前提）；
        · kill_tree 的 posix 臂按组发 TERM（kill -TERM -<pgid>）并保留 child.kill 回落；
        · nt 臂 taskkill /T /F 未漂移（同仓口径一致）。

沙箱铁律：全部读写落在 tempfile.mkdtemp() 内；realpath 断言不在 temp 内即**拒跑**；
绝不触碰在役 hive/jobs。哑执行器与哑任务均为本测试自造，不触真实 serve 配置。
运行：python -X utf8 -m hive.test_issue155_156_rust     （0 = 全绿）
环境：HIVE_EXE 可指向别处的 hive 可执行文件（缺省 <hive>/target/release/hive[.exe]）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok] {name}")
        return
    FAIL += 1
    print(f"  [FAIL] {name}  {detail}")


def _default_exe() -> str:
    env = os.environ.get("HIVE_EXE")
    if env:
        return env
    base = os.path.join(_HERE, "target", "release", "hive")
    return base + ".exe" if os.name == "nt" else base


EXE = _default_exe()

# 依赖缺席（裸 clone / CI 无构建产物）⇒ **只跳过依赖二进制的行为面**，
# 源码断言面（[4]）照判并显式打印计数——对齐本仓「裸 clone 不假红」口径
# （同 `scripts/run_tests.py` 的 _dep_db/_dep_mdroot，与 `test_md_access_parity`
#   的「字面量判据前置、SKIP 只覆盖依赖面」范式）。
# 修前形态：H0 直接 FAIL 且 `scenario()` 抛 FileNotFoundError ⇒ 整件 rc=1，CI 必红。
_HAS_EXE = os.path.isfile(EXE)
_SKIP_BEHAVIOR = not _HAS_EXE


def _dep_skip_note(face: str) -> None:
    print(f"  [SKIP] {face}：缺二进制 {EXE}（先 cargo build --release）"
          "——源码断言面 [4] 仍照判")

FAKE_EXEC = (
    "import json, os, sys, time\n"
    "d = sys.argv[1]\n"
    "open(os.path.join(d, 'SPAWNED.marker'), 'w', encoding='utf-8').write('spawned')\n"
    "time.sleep(float(os.environ.get('FAKE_EXEC_SLEEP', '8')))\n"
    "with open(os.path.join(d, 'result.json'), 'w', encoding='utf-8') as f:\n"
    "    json.dump({'ok': True, 'content': 'fake'}, f)\n"
)

SPEC = {"model": "m", "user_prompt": "x", "timeout_s": 60}
_TMP_ROOT = tempfile.gettempdir()


def run(argv, cwd=None, env=None, timeout=180):
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env,
                       shell=False, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def sandbox(tag: str):
    """tempfile 沙箱 + fail-closed 断言（realpath 不在 temp 内即拒跑）。"""
    root = tempfile.mkdtemp(prefix=f"hive_iss155156_{tag}_")
    real = os.path.realpath(root)
    if not real.startswith(os.path.realpath(_TMP_ROOT)):
        raise SystemExit(f"SANDBOX_ASSERT 失败：{real} 不在 {_TMP_ROOT} 内 —— 拒跑")
    jobs = os.path.join(root, "jobs")
    os.makedirs(jobs)
    return root, jobs


def base_env(fake_exec: str) -> dict:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["HIVE_EXEC_PY"] = fake_exec
    # 锚密钥链两环剥离：哑执行器不产 result_anchor，留着会把终态推去 needs_review
    # （与 [1]/[3] 的判据无关，但会让读数不干净）。
    for k in ("HIVE_ORCH_TOKEN", "HIVE_ORCH_TOKEN_FILE"):
        env.pop(k, None)
    return env


def read_state(jdir: str):
    try:
        with open(os.path.join(jdir, "status.json"), encoding="utf-8") as f:
            return (json.load(f) or {}).get("state")
    except (OSError, ValueError):
        return None


def submit_job(jobs: str, env: dict, spec_path: str):
    rc, out = run([EXE, "submit", "--spec", spec_path,
                   "--identity", "dsh端", "--task", "灵枢迭代",
                   "--unit", "记录单元", "--jobs", jobs], env=env)
    job_id = None
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                job_id = json.loads(line).get("job_id")
            except ValueError:
                pass
            if job_id:
                break
    return rc, out, job_id


def scenario(tag: str, with_kill: bool):
    """跑一个哑任务：with_kill=是否在 serve 启动**之前**就写好 kill 标志。"""
    root, jobs = sandbox(tag)
    proc = None
    try:
        fake = os.path.join(root, "fake_exec.py")
        with open(fake, "w", encoding="utf-8") as f:
            f.write(FAKE_EXEC)
        spec_path = os.path.join(root, "spec.json")
        with open(spec_path, "w", encoding="utf-8") as f:
            json.dump(SPEC, f)
        env = base_env(fake)
        env["FAKE_EXEC_SLEEP"] = "8"

        rc, out, job_id = submit_job(jobs, env, spec_path)
        if not job_id:
            return {"error": f"submit 未给出 job_id（rc={rc}）: {out[-400:]}"}
        jdir = os.path.join(jobs, job_id)
        if with_kill:
            with open(os.path.join(jdir, "kill"), "w", encoding="utf-8") as f:
                f.write("")
        marker = os.path.join(jdir, "SPAWNED.marker")

        proc = subprocess.Popen([EXE, "serve", "--jobs", jobs, "--workers", "1"],
                                env=env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, shell=False)
        state, waited = None, 0.0
        deadline = time.time() + 40
        while time.time() < deadline:
            state = read_state(jdir)
            if with_kill and state == "killed":
                break
            if not with_kill and os.path.exists(marker):
                break
            time.sleep(0.2)
            waited += 0.2
        # 收尾前再多给 2s：让「本该被拉起」的路径有机会暴露 marker
        if with_kill:
            time.sleep(2.0)
        triggered = os.path.exists(marker)
        kill_flag_left = os.path.exists(os.path.join(jdir, "kill"))
        return {"job_id": job_id, "state": state, "spawned": triggered,
                "kill_flag_left": kill_flag_left, "waited_s": round(waited, 1),
                "marker": marker}
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(root, ignore_errors=True)


print(f"### 守卫对象 = {EXE}")
if _SKIP_BEHAVIOR:
    _dep_skip_note("行为面 [1][2][3]")
else:
    check("H0 hive 可执行文件在场", True, EXE)

# ------------------------------------------------------------------ [1] #155①
print("[1] #155① 领取前查 kill 标志：pending + 已 kill ⇒ 执行器从未被拉起")
r1 = {"error": "skipped"} if _SKIP_BEHAVIOR else scenario("prekill", with_kill=True)
if "error" in r1:
    if _SKIP_BEHAVIOR:
        _dep_skip_note("[1] #155① 行为面")
    else:
        check("1.0 场景可跑（submit + serve）", False, r1["error"])
else:
    print(f"    读数: {json.dumps(r1, ensure_ascii=False)}")
    check("1.1 终态 = killed", r1["state"] == "killed", f"got state={r1['state']}")
    check("1.2 ★ 执行器**从未被拉起**（SPAWNED.marker 不存在）", not r1["spawned"],
          "marker 出现 ⇒ 领取前闸缺失（旧路径 claim 后照常 spawn）")

# ------------------------------------------------------------- [2] #156⑥
print("[2] #156⑥ 终态落盘后删除 kill 标志")
if "error" in r1:
    if _SKIP_BEHAVIOR:
        _dep_skip_note("[2] #156⑥ 行为面")
    else:
        check("2.0 场景可跑", False, r1["error"])
else:
    check("2.1 kill 标志在终态后已删除", not r1["kill_flag_left"],
          "kill 文件残留 ⇒ 会被后续恢复/重投路径误读为新的 kill 请求")

# ---------------------------------------------------------- [3] 对照组
print("[3] 对照组：无 kill 标志的正常任务照旧被拉起（闸不滥杀）")
r3 = {"error": "skipped"} if _SKIP_BEHAVIOR else scenario("nokill", with_kill=False)
if "error" in r3:
    if _SKIP_BEHAVIOR:
        _dep_skip_note("[3] 对照组行为面")
    else:
        check("3.0 场景可跑", False, r3["error"])
else:
    print(f"    读数: {json.dumps(r3, ensure_ascii=False)}")
    check("3.1 ★ 执行器确被拉起（SPAWNED.marker 在）", r3["spawned"],
          "marker 缺席 ⇒ 正常路径被打死（闸滥杀）")

# --------------------------------------------------- [4] #156⑦ 源断言
print("[4] #156⑦ 源断言：unix 臂群杀 + process_group 前提 + nt 臂未漂移")
try:
    with open(os.path.join(_HERE, "src", "exec.rs"), encoding="utf-8") as f:
        RS = f.read()
    check("4.1 spawn_executor 以 process_group(0) 令执行器自成进程组（群杀前提）",
          "cmd.process_group(0)" in RS, "exec.rs 缺 process_group(0)")
    check("4.2 kill_tree posix 臂按**进程组**发 TERM，且 argv 带 `--` 分隔符",
          '"-TERM", "--"' in RS and 'format!("-{pid}")' in RS,
          "exec.rs posix 臂群杀缺失，或缺 `--`：procps 下无 `--` 的 `-<N>` 走选项/信号解析"
          "（不是负 pid），实测同一 argv 在不同 N 下时通时不通、pgid≥20 静默 no-op 且 rc=0"
          " ⇒ s.success() 为真 ⇒ 回落分支不触发 ⇒ 直接子进程也不被杀")
    check("4.3 直接子进程**无条件**杀（不与群杀成败耦合）",
          "let _ = child.kill();" in RS
          and re.search(r"if\s*!\s*group_signalled\s*\{[^}]*child\.kill", RS) is None
          and "群杀未送达" in RS,
          "回落臂仍与群杀成败耦合：群杀静默 no-op（rc=0）时直接子进程也活；或告警缺失")
    check("4.4 nt 臂 taskkill /T /F 未漂移（同仓口径一致）",
          '"/T", "/F"' in RS, "exec.rs 的 taskkill /T /F 形态丢失")
except OSError as e:
    check("4.0 exec.rs 可读", False, f"{type(e).__name__}: {e}")

if _SKIP_BEHAVIOR:
    print("  跳过范围＝依赖二进制的行为面；源码断言面 [4] 已判 "
          f"{PASS} 条（红 {FAIL} 条）")
print(f"\n结果: {PASS} pass / {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
