# -*- coding: utf-8 -*-
"""H-3 / H-7 守卫（hive 调度面）：坏 status 不再静默 + 领取上界有界。

## 病灶（本轮 HEAD 读核在位，scheduler.rs 行号为改动前）

**H-3（坏 status 让任务永久静默卡 pending）**
  * 主循环 `let Ok(st) = read_status(&dir) else { continue }`（:214-217）——读失败
    当「正在写入的半成品」，下一拍再看；`recover_orphans` 同款（:302）。两处都
    **没有任何把坏 status 终态化、告警或标记的路径**：任务既不被领取（state 读不出
    来 ≠ pending），也永不被清理（没有任何终态分支够得着它），只在 doctor 里变成
    一个 `unknown`（`cmd_doctor` 把「读不到」压成 unknown，事故与正常时序同形）。
  * 实测复现（本守卫首版手工现场，逐字记录）：手工造截断 status.json + 真 serve，
    4000ms 后 status.json 字节不变、任务目录仍只有 spec+status；`hive poll` 只回
    error 无 state；`hive doctor` 报 `{"state":"unknown","count":1}`。

**H-7（worker 池无界预领取 + claimed 无 pid/心跳）**
  * 主循环一拍把**池内全部** pending 任务 claim 进无界 mpsc 队列——「上界 =
    ceil(N/workers)×timeout_s」**不成立**。实测复现：workers=1、3 条 pending，一拍
    后 `running=1 + claimed=2`，其中 2 条没有 pid/心跳、也没有任何进程在跑，池外
    观察者分不出「在跑」与「排在队里干等」；kill 对未开跑者够不着。

## 修法（本守卫钉死的判据）

**H-3**：`job::read_status_classified` 三态（Ok / Absent / Corrupt）把「文件不在」
  与「文件在但坏」分开；serve 启动 stderr 点名告警 + 周期计数（`CORRUPT_MARK_TICKS`
  拍≈4s）落**独立标记** `status.corrupt.json`（**绝不改写 status.json 本体**）；
  doctor 归独立类别 `corrupt` + `corrupt_jobs` 明细；`doctor --quarantine` 整体
  移入 `jobs/_quarantine/`（退出领取面，可 `--unquarantine` 原路退回）。
  **不做自动终态化**（那会把坏文件静默吞掉，正是本缺陷的反面）。

**H-7**：领取与投递解耦为**有界在飞名额**（`InFlight`，容量 = workers）——主循环
  **先占名额再 claim**，满员即本拍不再领取。不变量：任一时刻 `claimed`+`running`
  的任务数 ≤ workers。选 (a) 而非 (b)（claimed 语义补 pid/心跳）的理由：mpsc 无
  队列内移除语义，若要 kill 够得着「已领取未开跑」还得再加一套取消集合与心跳面，
  而 (b) 并不解决「无界预领取」这个被点名的缺陷本体；(a) 一处改动同时给出上界与
  「claimed 必有名额在手 ⇒ 必在 worker 手边」的结构含义。

## 覆盖面（守卫断言分组）

  A 坏 status 不再静默（真 serve：标记落场 + 启动/周期双告警 + doctor 归类 +
    poll 面的 state，且坏任务既不被领取也不被终态化）
  B status.json 本体**逐字节未被改写**（机械判据；含「健康任务仍被正常改写」的
    零闸变对照，证明「不改」是坏文件专属而非 serve 整体停写）
  C 隔离手段可用且可回退（--quarantine 移出领取面 / 字节不动 / doctor 如实报告 /
    --unquarantine 回池 / 空操作幂等）
  D H-7 上界（实测：峰值 claimed+running ≤ workers、期间确有 pending 残留、
    drain 不退化——全部终态、零 claimed.lock 残留）
  E 端到端两态（真 serve + 桩执行器：干净池全 done；同池混坏 status 时好任务照跑、
    坏任务字节不动、serve 心跳继续前进）

## 运行

  python -X utf8 hive/test_h3_h7_scheduler.py                    # 正向
  python -X utf8 hive/test_h3_h7_scheduler.py --branch-baseline  # 定点变异自证
（退出码 0 = 全绿 / 1 = 有失败 / 2 = 变异锚点漂移 ANCHOR-MISS）

**基线源 = 工作区源码 × 现场编译**：本守卫把 `hive/Cargo.toml` + `hive/src/` 复制到
**系统临时目录**的独立 crate 副本，用独立的 CARGO_TARGET_DIR 编译（零第三方依赖，
全量编译约 5s、增量约 1-3s）。**不写 hive/target/**——在役 serve 正持有
`target/release/hive.exe`（实测 `cargo build --release` 报 os error 5 拒绝访问），
就地编译既不可能也不该做。工作区源码在变异轮中**只读**（改的是临时副本），
故崩溃/中断也不会留下被改的工作区。

临时池一律建在系统临时目录，且 serve 一律显式 `--jobs <临时池>` 并剔净
HIVE_*/MDCG_* 注入面——**绝不碰在役 jobs 池**（`hive/jobs`）。
"""
from __future__ import annotations

import contextlib
import io
import json
import os
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
for _p in (_REPO, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# H-3/H-7 的常量镜像（判据值来自源码；守卫按下表断言，源码漂移即本条失败）：
MARKER = "status.corrupt.json"
QUARANTINE = "_quarantine"
CORRUPT_MARK_TICKS = 10
POLL_MS = 400

STUB_EXEC = r"""
import sys, json, time, os
d = sys.argv[1]
with open(os.path.join(d, "spec.json"), encoding="utf-8") as f:
    spec = json.load(f)
time.sleep(float(spec.get("user_prompt") or 0))
r = {"ok": True, "content": "h3h7-guard-stub", "completed": True}
with open(os.path.join(d, "result.json"), "w", encoding="utf-8") as f:
    json.dump(r, f, ensure_ascii=False)
"""

PASS, FAIL = 0, 0
FAILS = []
_CURRENT = ["?"]
_GROUP_FAILS = {}
_TMP_ROOTS = []
_PERSIST_ROOTS = []      # 只在本进程收尾时清理（编译副本须跨变异轮存活）
_PROCS = []
_CTX = {}
_BUILD = {"dir": None, "target": None, "exe": None, "log": ""}


# 生效条件：把 PASS/FAIL/失败名单/分组失败数清零并解除当前组名（每次完整跑套件前
# 调用；--branch-baseline 每个变异轮都要一次干净基线）。夹具缓存一并清空——
# 变异轮必须用**变异后的二进制**重跑全部夹具。
def _reset_counters():
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    _GROUP_FAILS.clear()
    _CURRENT[0] = "?"
    _CTX.clear()


# 生效条件：group 为非空字符串时设为当前组名并在 _GROUP_FAILS 开出该组条目（未开则
# 记 0）；重复调用同名组只是切换当前组，不清零已有计数。
def begin(group: str):
    _CURRENT[0] = group
    _GROUP_FAILS.setdefault(group, 0)


# 生效条件：cond 为真记一条通过并打印；为假把 FAIL 与当前组失败数各 +1、把 name
# 追加进 FAILS 并打印 detail。
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [ok] %s" % name)
        return True
    FAIL += 1
    _GROUP_FAILS[_CURRENT[0]] = _GROUP_FAILS.get(_CURRENT[0], 0) + 1
    FAILS.append(name)
    print("  [FAIL] %s  %s" % (name, detail))
    return False


# 生效条件：fn 为无参回调时调用它取条件值——回调抛异常即判红并把异常类型与消息写进
# detail（**不中断整组**，保证「变异下红项数 == 该组断言数」这一精确口径成立）；
# fn 正常返回则按返回值真假记账；detail 传 callable 时在同一保护下求值。
def check_fn(name, fn, detail=""):
    if callable(detail):
        try:
            detail = detail()
        except Exception as exc:          # noqa: BLE001
            detail = "detail 求值抛 %s: %s" % (type(exc).__name__, exc)
    try:
        cond = bool(fn())
        extra = detail
    except Exception as exc:              # noqa: BLE001 —— 红态正是抛异常
        cond = False
        extra = "回调抛 %s: %s（%s）" % (type(exc).__name__, exc, detail)
    return check(name, cond, extra)


# 生效条件：新建系统临时目录（prefix 前缀）并登记进 _TMP_ROOTS（收尾统一清理）。
def _tmpdir(prefix: str) -> str:
    p = tempfile.mkdtemp(prefix=prefix)
    _TMP_ROOTS.append(p)
    return p


# 生效条件：无入参——对 _PROCS 每个仍存活的 serve 先 taskkill /T /F（Windows 须收
# 进程树，否则桩执行器子进程成孤儿），再 rmtree 掉 _TMP_ROOTS 全部临时根；
# 幂等，收尾不再抛。
def _cleanup():
    for p in _PROCS:
        try:
            if p.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                                   capture_output=True, text=True,
                                   encoding="utf-8", errors="replace")
                else:
                    p.terminate()
                with contextlib.suppress(Exception):
                    p.wait(timeout=10)
        except Exception:                 # noqa: BLE001 —— 收尾尽力而为
            pass
    del _PROCS[:]
    for d in _TMP_ROOTS:
        shutil.rmtree(d, ignore_errors=True)
    del _TMP_ROOTS[:]


# 生效条件：无入参——清理 _PERSIST_ROOTS（编译副本与目标目录）。**只在进程收尾调用**：
# 变异轮之间必须留着副本（否则下一轮的 _patch/增量编译无源可改），故不得混进 _cleanup。
def _cleanup_persist():
    for d in _PERSIST_ROOTS:
        shutil.rmtree(d, ignore_errors=True)
    del _PERSIST_ROOTS[:]


# --------------------------------------------------------------- 编译面（临时副本）

# 生效条件：无入参——首次调用时把 hive/Cargo.toml(+Cargo.lock) + hive/src 复制进
# 系统临时目录的独立 crate 副本，返回 (crate_dir, target_dir, exe_path, log)。
# 复制而非就地编译：在役 serve 持有 hive/target/release/hive.exe（写不进去），
# 且变异轮改的是副本、工作区源码只读。
def _build_env():
    if _BUILD["exe"]:
        return _BUILD
    root = tempfile.mkdtemp(prefix="h3h7_build_")
    _PERSIST_ROOTS.append(root)          # 跨变异轮存活：_cleanup 不碰它
    crate = os.path.join(root, "crate")
    os.makedirs(crate)
    shutil.copy2(os.path.join(_HERE, "Cargo.toml"), os.path.join(crate, "Cargo.toml"))
    lock = os.path.join(_HERE, "Cargo.lock")
    if os.path.isfile(lock):
        shutil.copy2(lock, os.path.join(crate, "Cargo.lock"))
    shutil.copytree(os.path.join(_HERE, "src"), os.path.join(crate, "src"))
    _BUILD["dir"] = crate
    _BUILD["target"] = os.path.join(root, "target")
    _BUILD["exe"] = os.path.join(
        root, "target", "release", "hive.exe" if os.name == "nt" else "hive")
    return _BUILD


# 生效条件：crate 副本就位时调 cargo build --release（CARGO_TARGET_DIR 指向独立
# 目标目录，cwd=crate 副本）——返回 (ok, 日志尾)；cargo 不在 PATH 返回 (False, 原因)。
def _cargo_build():
    env = dict(os.environ)
    env["CARGO_TARGET_DIR"] = _BUILD["target"]
    env["PYTHONUTF8"] = "1"
    if shutil.which("cargo") is None:
        return False, "cargo 不在 PATH（本守卫需要 rust 工具链现场编译）"
    try:
        p = subprocess.run(["cargo", "build", "--release"],
                           cwd=_BUILD["dir"], env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=600)
    except Exception as exc:              # noqa: BLE001
        return False, "cargo 调用异常: %s: %s" % (type(exc).__name__, exc)
    _BUILD["log"] = ((p.stdout or "") + (p.stderr or ""))[-1500:]
    return p.returncode == 0, _BUILD["log"]


# 生效条件：无参——确保临时副本已编译出可执行件，返回 exe 路径；编译失败返回 None
# （调用方按前置缺失判红并给出 cargo 日志尾）。
def _exe():
    _build_env()
    if os.path.isfile(_BUILD["exe"]):
        return _BUILD["exe"]
    ok, log = _cargo_build()
    if ok and os.path.isfile(_BUILD["exe"]):
        return _BUILD["exe"]
    print("  !! 编译失败：%s" % log)
    return None


# ------------------------------------------------------------- 定点变异（临时副本上）

# 生效条件：rel_path（相对 crate 副本，如 "src/scheduler.rs"）的源码中 anchor 出现
# **恰好一次**时替换为 new 并写回，返回还原回调；出现 0 次或 >1 次返回 None
# （调用方按锚点漂移 ANCHOR-MISS 处置——不唯一即不可定点，宁红不猜）。
# 字节级读写：不翻译行尾，避免 CRLF 源码在替换/还原中被悄悄改写。
def _patch(rel_path: str, anchor: str, new: str):
    p = os.path.join(_BUILD["dir"], rel_path)
    try:
        with open(p, "rb") as f:
            src_b = f.read()
    except OSError:
        return None
    try:
        src = src_b.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if src.count(anchor) != 1:
        return None
    with open(p, "wb") as f:
        f.write(src.replace(anchor, new).encode("utf-8"))

    def _restore():
        with open(p, "wb") as f2:
            f2.write(src_b)

    return _restore


# ------------------------------------------------------------------ CLI / 池夹具

# 生效条件：无入参——剔净全部 HIVE_*/MDCG_* 注入面的 env（防夹具外的真实池被误指向），
# 另加 PYTHONUTF8=1；所有 CLI 调用共用。
def _env():
    e = {k: v for k, v in os.environ.items()
         if not k.startswith("HIVE_") and not k.startswith("MDCG_")}
    e["PYTHONUTF8"] = "1"
    return e


# 生效条件：exe 与 argv 尾给定——跑一次 CLI，返回 (rc, stdout, stderr)；调用异常
# 归成 (-1, "", 原因) 使断言计数稳定（红一条而非崩一组）。
def _cli(exe, args, timeout=60):
    try:
        p = subprocess.run([exe] + args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=_env(),
                           cwd=_REPO, timeout=timeout)
    except Exception as exc:              # noqa: BLE001
        return -1, "", "调用异常 %s: %s" % (type(exc).__name__, exc)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


# 生效条件：stdout 末行可解析为 JSON 对象时返回该对象，否则返回 {}（CLI 统一单行
# JSON 输出；解析失败即判据缺失，由断言侧判红）。
def _cli_json(exe, args, timeout=60):
    rc, out, err = _cli(exe, args, timeout)
    try:
        v = json.loads(out.splitlines()[-1])
        return v if isinstance(v, dict) else {}
    except (ValueError, IndexError):
        return {}


# 生效条件：tmp 下建 jobs 池并写桩执行器——返回 (jobs_dir, stub_py)。
def _pool(tmp: str, name: str = "jobs"):
    jobs = os.path.join(tmp, name)
    os.makedirs(jobs, exist_ok=True)
    stub = os.path.join(tmp, "stub_exec.py")
    if not os.path.isfile(stub):
        with open(stub, "w", encoding="utf-8") as f:
            f.write(STUB_EXEC)
    return jobs, stub


# 生效条件：jobs/jid 给定——写 spec.json + **截断的** status.json（合法 JSON 前缀
# 后截断，模拟断电/半写），返回 status.json 的原始字节（逐字节判据的基准）。
def _make_corrupt(jobs: str, jid: str, sleep_s: str = "0"):
    d = os.path.join(jobs, jid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "spec.json"), "w", encoding="utf-8") as f:
        json.dump({"model": "guard-model", "user_prompt": sleep_s,
                   "timeout_s": 60}, f)
    raw = ('{"job_id":"%s","state":"pen' % jid).encode("utf-8")
    with open(os.path.join(d, "status.json"), "wb") as f:
        f.write(raw)
    return raw


# 生效条件：jobs/jid 给定——写 spec.json + 合法 status.json(state=pending)，
# 返回 status.json 的原始字节。
def _make_pending(jobs: str, jid: str, sleep_s: str = "0"):
    d = os.path.join(jobs, jid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "spec.json"), "w", encoding="utf-8") as f:
        json.dump({"model": "guard-model", "user_prompt": sleep_s,
                   "timeout_s": 60}, f)
    raw = json.dumps({"job_id": jid, "state": "pending"}).encode("utf-8")
    with open(os.path.join(d, "status.json"), "wb") as f:
        f.write(raw)
    return raw


# 生效条件：路径给定——返回原始字节；读不到返回 None（判据侧把 None 记成红）。
def _raw(path: str):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


# 生效条件：jobs/jid 给定——status.json 可解析为 dict 时返回它，否则 {}。
def _status(jobs: str, jid: str):
    try:
        with open(os.path.join(jobs, jid, "status.json"), encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


# 生效条件：jobs 下以 "h" 开头的目录名集合（= 领取面，与 rust list_jobs 同判据）。
def _job_dirs(jobs: str):
    try:
        names = os.listdir(jobs)
    except OSError:
        return set()
    return {n for n in names
            if n.startswith("h") and os.path.isdir(os.path.join(jobs, n))}


# 生效条件：jobs 与 job_id 给定——池内该任务目录下的文件名集合（读不到 → 空集）。
def _files(jobs: str, jid: str):
    try:
        return set(os.listdir(os.path.join(jobs, jid)))
    except OSError:
        return set()


# 生效条件：pred 无参回调与超时秒数给定——每 interval 轮询 pred 直到真值或超时；
# 返回 pred 的最后一次取值（超时为假）。
def _wait_until(pred, timeout_s: float, interval: float = 0.1):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if pred():
            return True
        time.sleep(interval)
    return bool(pred())


# 生效条件：exe/jobs/stub/workers 给定——以剔净注入面的 env 起 `hive serve`，日志
# 落池根 `_h3h7_serve.log`（非 h 前缀 → 对领取面不可见），登记 Popen 返回。
def _start_serve(exe, jobs, stub, workers=2):
    env = _env()
    env["HIVE_EXEC_PY"] = stub
    env["HIVE_WORKERS"] = str(workers)
    logf = open(os.path.join(jobs, "_h3h7_serve.log"), "ab")
    try:
        p = subprocess.Popen([exe, "serve", "--jobs", jobs,
                              "--workers", str(workers)],
                             stdout=logf, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, env=env, cwd=_REPO)
    finally:
        logf.close()
    _PROCS.append(p)
    return p


# 生效条件：jobs 给定——轮询 _serve.json 心跳（服务进入主循环的判据）；超时 False。
def _wait_serve(jobs, timeout_s: float = 15.0):
    def _ok():
        try:
            with open(os.path.join(jobs, "_serve.json"), encoding="utf-8") as f:
                hb = json.load(f)
            return bool(isinstance(hb, dict) and hb.get("pid"))
        except (OSError, ValueError):
            return False
    return _wait_until(_ok, timeout_s)


# 生效条件：jobs 给定——返回 serve 日志全文（读不到 → 空串）；告警断言读它。
def _serve_log(jobs):
    try:
        with open(os.path.join(jobs, "_h3h7_serve.log"), encoding="utf-8",
                  errors="replace") as f:
            return f.read()
    except OSError:
        return ""


# 生效条件：exe/jobs 给定——返回当前处于 claimed/running 的任务数（有界判据的
# 采样量：H-7 不变量 = 该值 ≤ workers）。
def _in_flight(jobs):
    n = 0
    for jid in _job_dirs(jobs):
        if _status(jobs, jid).get("state") in ("claimed", "running"):
            n += 1
    return n


# 生效条件：exe/jobs 给定——返回 (有无 failed, 说明)，检查 serve 日志里有无 panic。
def _serve_alive_after(jobs):
    txt = _serve_log(jobs)
    bad = [ln for ln in txt.splitlines()
           if "panicked" in ln.lower() or "thread 'main'" in ln]
    return (not bad), (bad[:2] if bad else "")


# --------------------------------------------------------------- A/B 组夹具（真 serve）

# 生效条件：无参——A/B 组夹具：临时池 + 1 条坏 status + 2 条健康 pending + 桩执行器
# + 真实 serve（workers=2）。返回 ctx：corrupt/raw_corrupt/healthy(字典)、marker_in_time、
# 各观测值。exe 缺失时 note 记原因（断言各自判红）。
def _fixture_ab():
    ctx = {"note": "", "corrupt": "h1700000000a01_abcd",
           "healthy": ["h1700000000a02_abcd", "h1700000000a03_abcd"],
           "raw": None, "raw_spec": None, "marker_in_time": False,
           "log": "", "doctor": {}, "poll": {}, "pool_files": set(),
           "healthy_written": False, "alive": True, "alive_note": ""}
    exe = _exe()
    if exe is None:
        ctx["note"] = "编译未产出可执行件（见上方 cargo 日志尾）"
        return ctx
    tmp = _tmpdir("h3h7_ab_")
    jobs, stub = _pool(tmp)
    ctx["raw"] = _make_corrupt(jobs, ctx["corrupt"], "0")
    ctx["raw_spec"] = _raw(os.path.join(jobs, ctx["corrupt"], "spec.json"))
    healthy_raw = {}
    for jid in ctx["healthy"]:
        healthy_raw[jid] = _make_pending(jobs, jid, "1")
    ctx["healthy_raw"] = healthy_raw
    _start_serve(exe, jobs, stub, workers=2)
    if not _wait_serve(jobs):
        ctx["note"] = "serve 心跳未出现（临时池）"
        return ctx
    # 阈值判据：标记必须在「阈值拍 × poll_ms + 余量」内落场
    budget = CORRUPT_MARK_TICKS * POLL_MS / 1000.0 + 8.0
    ctx["marker_in_time"] = _wait_until(
        lambda: os.path.isfile(os.path.join(jobs, ctx["corrupt"], MARKER)), budget)
    # 健康任务跑完（对照面：健康路径必须照常推进）
    _wait_until(lambda: all(_status(jobs, j).get("state") == "done"
                            for j in ctx["healthy"]), 30.0)
    ctx["healthy_written"] = all(
        _raw(os.path.join(jobs, j, "status.json")) != healthy_raw[j]
        for j in ctx["healthy"])
    ctx["pool_files"] = _files(jobs, ctx["corrupt"])
    ctx["log"] = _serve_log(jobs)
    ctx["alive"], ctx["alive_note"] = _serve_alive_after(jobs)
    ctx["doctor"] = _cli_json(exe, ["doctor", "--jobs", jobs])
    ctx["poll"] = _cli_json(exe, ["poll", ctx["corrupt"], "--jobs", jobs])
    ctx["jobs_dir"] = jobs
    ctx["exe"] = exe
    return ctx


def g_a():
    """A 组：坏 status 不再静默（真 serve 全链路观测）。"""
    begin("A")
    ctx = _fixture_ab()
    if ctx["note"]:
        for name in ("A1 标记文件按阈值落场", "A2 标记字段齐备",
                     "A3 serve 启动告警点名坏任务", "A4 serve 周期告警",
                     "A5 坏任务既不被领取也不被终态化", "A6 doctor 归 corrupt 独立类别",
                     "A7 poll 单查 state=corrupt"):
            check(name, False, ctx["note"])
        return
    jobs, cid = ctx["jobs_dir"], ctx["corrupt"]
    marker = os.path.join(jobs, cid, MARKER)
    check("A1 标记文件按阈值落场（%d 拍 × %dms 内）"
          % (CORRUPT_MARK_TICKS, POLL_MS), ctx["marker_in_time"],
          "目录=%s" % sorted(_files(jobs, cid)))
    mk = {}
    with contextlib.suppress(OSError, ValueError):
        with open(marker, encoding="utf-8") as f:
            mk = json.load(f)
    need = ("job_id", "kind", "detected_ts", "first_ts", "ticks",
            "threshold", "last_error")
    check("A2 标记字段齐备（%s）" % "/".join(need),
          isinstance(mk, dict) and all(k in mk for k in need)
          and mk.get("job_id") == cid
          and mk.get("threshold") == CORRUPT_MARK_TICKS
          and int(mk.get("ticks") or 0) >= CORRUPT_MARK_TICKS,
          "marker=%s" % json.dumps(mk, ensure_ascii=False)[:300])
    log = ctx["log"]
    check("A3 serve 启动告警点名坏任务",
          ("启动扫描发现" in log) and (cid in log), "log 尾=%r" % log[-400:])
    check("A4 serve 周期告警（含『告警：任务 %s』与『不可解析』）" % cid,
          ("告警：任务 %s" % cid) in log and "不可解析" in log,
          "log 尾=%r" % log[-400:])
    st = _status(jobs, cid)
    check("A5 坏任务既不被领取也不被终态化（无 claimed.lock / 无 result.json）",
          not os.path.exists(os.path.join(jobs, cid, "claimed.lock"))
          and not os.path.exists(os.path.join(jobs, cid, "result.json")),
          "state=%r files=%s" % (st.get("state"), sorted(_files(jobs, cid))))
    doc = ctx["doctor"]
    states = {s.get("state"): s.get("count")
              for s in (doc.get("task_states") or [])
              if isinstance(s, dict)}
    cj = [j for j in (doc.get("corrupt_jobs") or []) if isinstance(j, dict)]
    hit = [j for j in cj if j.get("job_id") == cid]
    check("A6 doctor 归 corrupt 独立类别 + corrupt_jobs 明细（含 error 与 marker 字段）",
          states.get("corrupt") == 1 and len(hit) == 1
          and "error" in hit[0] and "marker" in hit[0],
          "task_states=%s corrupt_jobs=%s"
          % (json.dumps(states, ensure_ascii=False),
             json.dumps(cj, ensure_ascii=False)[:300]))
    pj = ctx["poll"].get("job") or {}
    check("A7 poll 单查 state=corrupt（不再是无 state 的裸 error）",
          pj.get("state") == "corrupt" and pj.get("job_id") == cid,
          "poll=%s" % json.dumps(pj, ensure_ascii=False)[:250])


def g_b():
    """B 组：status.json 本体**逐字节未被改写**（H-3 的机械判据）。"""
    begin("B")
    ctx = _fixture_ab()
    if ctx["note"]:
        for name in ("B1 坏 status.json 逐字节未变",
                     "B2 标记是独立文件（未写到任务本体路径）",
                     "B3 同目录其他本体（spec.json）逐字节未变",
                     "B4 零闸变对照：健康任务仍被 serve 正常改写"):
            check(name, False, ctx["note"])
        return
    jobs, cid = ctx["jobs_dir"], ctx["corrupt"]
    now = _raw(os.path.join(jobs, cid, "status.json"))
    check("B1 坏 status.json 逐字节未变（serve 跑满阈值后，含落标记之后）",
          now is not None and now == ctx["raw"],
          "orig=%r now=%r" % (ctx["raw"], now))
    marker = _raw(os.path.join(jobs, cid, MARKER))
    check("B2 标记是独立文件（未写到任务本体路径）",
          marker is not None and marker != now
          and MARKER in _files(jobs, cid) and "status.json" in _files(jobs, cid),
          "files=%s" % sorted(_files(jobs, cid)))
    check("B3 同目录其他本体（spec.json）逐字节未变",
          _raw(os.path.join(jobs, cid, "spec.json")) == ctx["raw_spec"],
          "spec 字节=%r" % _raw(os.path.join(jobs, cid, "spec.json")))
    check("B4 零闸变对照：健康任务仍被 serve 正常改写（『不改』是坏文件专属）",
          ctx["healthy_written"]
          and all(_status(jobs, j).get("state") == "done" for j in ctx["healthy"]),
          "healthy=%s" % {j: _status(jobs, j).get("state") for j in ctx["healthy"]})


# -------------------------------------------------------------------- C 组：隔离

def g_c():
    """C 组：隔离手段可用且可回退（--quarantine / --unquarantine / 幂等）。"""
    begin("C")
    ctx = {"note": "", "cid": "h1700000000c01_abcd",
           "healthy": "h1700000000c02_abcd", "raw": None}
    exe = _exe()
    if exe is None:
        ctx["note"] = "编译未产出可执行件"
    if ctx["note"]:
        for name in ("C1 --quarantine 搬家且报数", "C2 隔离件退出领取面",
                     "C3 隔离后 status.json 字节逐字节一致",
                     "C4 doctor 如实报隔离与 corrupt 归零",
                     "C5 --unquarantine 原路退回且字节一致",
                     "C6 空操作幂等（无坏项/无隔离件均 rc=0 count=0）"):
            check(name, False, ctx["note"])
        return
    tmp = _tmpdir("h3h7_c_")
    jobs, _stub = _pool(tmp)
    ctx["raw"] = _make_corrupt(jobs, ctx["cid"])
    _make_pending(jobs, ctx["healthy"], "0")
    face_before = _job_dirs(jobs)

    v = _cli_json(exe, ["doctor", "--jobs", jobs, "--quarantine"])
    qroot = os.path.join(jobs, QUARANTINE)
    check("C1 --quarantine 搬家且报数（rc=0, count=1）",
          v.get("ok") is True and v.get("count") == 1
          and v.get("quarantined") and not v.get("errors"),
          "resp=%s" % json.dumps(v, ensure_ascii=False)[:300])
    face_after = _job_dirs(jobs)
    poll = _cli_json(exe, ["poll", "--jobs", jobs])
    listed = {j.get("job_id") for j in (poll.get("jobs") or [])
              if isinstance(j, dict)}
    check("C2 隔离件退出领取面（池 h 前缀目录与 poll 列表都不含它，也不多出伪装目录）",
          ctx["cid"] not in face_after and face_after == (face_before - {ctx["cid"]})
          and listed == {ctx["healthy"]},
          "池内=%s poll=%s" % (sorted(face_after), sorted(listed)))
    check("C3 隔离后 status.json 字节逐字节一致（搬家不改字节）",
          _raw(os.path.join(qroot, ctx["cid"], "status.json")) == ctx["raw"],
          "隔离区=%s" % (sorted(os.listdir(qroot)) if os.path.isdir(qroot) else "不存在"))
    doc = _cli_json(exe, ["doctor", "--jobs", jobs])
    states = {s.get("state"): s.get("count")
              for s in (doc.get("task_states") or []) if isinstance(s, dict)}
    check("C4 doctor 如实报隔离（quarantined 含它）且 corrupt 计数归零",
          ctx["cid"] in (doc.get("quarantined") or [])
          and states.get("corrupt", 0) == 0,
          "quarantined=%s task_states=%s"
          % (doc.get("quarantined"), json.dumps(states, ensure_ascii=False)))
    v2 = _cli_json(exe, ["doctor", "--jobs", jobs, "--unquarantine"])
    check("C5 --unquarantine 原路退回且字节一致（可回退）",
          v2.get("ok") is True and v2.get("count") == 1
          and ctx["cid"] in _job_dirs(jobs)
          and _raw(os.path.join(jobs, ctx["cid"], "status.json")) == ctx["raw"],
          "resp=%s files=%s" % (json.dumps(v2, ensure_ascii=False)[:200],
                                sorted(_files(jobs, ctx["cid"]))))
    # C6 空操作幂等：用**全新池**取「无坏项/无隔离件」两态，不依赖前几步是否搬家成功
    # （否则一条判据的失败会顺着夹具状态传染，把「恰好命中预期组」的口径搅浑）。
    tmp2 = _tmpdir("h3h7_c6_")
    jobs2, _s2 = _pool(tmp2)
    _make_pending(jobs2, "h1700000000c06_abcd", "0")
    v4 = _cli_json(exe, ["doctor", "--jobs", jobs2, "--quarantine"])
    v5 = _cli_json(exe, ["doctor", "--jobs", jobs2, "--unquarantine"])
    v6 = _cli_json(exe, ["doctor", "--jobs", jobs2, "--quarantine"])
    check("C6 空操作幂等（纯健康池 --quarantine count=0；无隔离件 --unquarantine count=0；"
          "重复执行不误搬且 rc=0）",
          v4.get("ok") is True and v4.get("count") == 0
          and v5.get("ok") is True and v5.get("count") == 0
          and v6.get("count") == 0
          and _job_dirs(jobs2) == {"h1700000000c06_abcd"},
          "搬=%s 退=%s 再搬=%s 池内=%s"
          % (v4.get("count"), v5.get("count"), v6.get("count"),
             sorted(_job_dirs(jobs2))))


# -------------------------------------------------------------------- D 组：H-7 上界

def g_d():
    """D 组：H-7 领取上界（实测 drain 曲线与队列上界）。"""
    begin("D")
    n, workers, sleep_s = 6, 2, 1.5
    ctx = {"note": "", "ids": ["h1700000000d%02d_abcd" % i for i in range(n)]}
    exe = _exe()
    if exe is None:
        ctx["note"] = "编译未产出可执行件"
    if ctx["note"]:
        for name in ("D1 峰值 claimed+running ≤ workers",
                     "D2 有界不是空谈：采样期间确有 pending 残留",
                     "D3 drain 不退化：全部终态 done",
                     "D4 名额闸未破坏 N191 不变量：无 pending+锁悬置，终态后在飞数归零"):
            check(name, False, ctx["note"])
        return
    tmp = _tmpdir("h3h7_d_")
    jobs, stub = _pool(tmp)
    for jid in ctx["ids"]:
        _make_pending(jobs, jid, str(sleep_s))
    _start_serve(exe, jobs, stub, workers=workers)
    if not _wait_serve(jobs):
        for name in ("D1 峰值 claimed+running ≤ workers",
                     "D2 有界不是空谈：采样期间确有 pending 残留",
                     "D3 drain 不退化：全部终态 done",
                     "D4 终态后零 claimed.lock 残留"):
            check(name, False, "serve 心跳未出现（临时池）")
        return
    peak, saw_pending = 0, False
    t0 = time.time()
    while time.time() - t0 < n * sleep_s / workers + 25:
        peak = max(peak, _in_flight(jobs))
        if any(_status(jobs, j).get("state") == "pending" for j in ctx["ids"]):
            saw_pending = True
        if all(_status(jobs, j).get("state") == "done" for j in ctx["ids"]):
            break
        time.sleep(0.04)
    states = {j: _status(jobs, j).get("state") for j in ctx["ids"]}
    check("D1 峰值 claimed+running ≤ workers（实测峰值=%d, workers=%d）"
          % (peak, workers), peak <= workers, "states=%s" % states)
    check("D2 有界不是空谈：采样期间确有 pending 残留（观测到=%s）" % saw_pending,
          saw_pending, "states=%s" % states)
    check("D3 drain 不退化：全部终态 done（上界不伤吞吐）",
          all(v == "done" for v in states.values()), "states=%s" % states)
    # 终态任务的 claimed.lock 本就**不删**（run_job 只写终态；清锁是 recover_orphans
    # 对 claimed/running/pending 的职责——既有行为，非本批判据），故终态残留锁不作断言；
    # 断的是 N191 不变量「锁在手 ⇔ state 已 claimed」未被名额闸破坏：
    # 不得出现 state=pending 却带锁的任务（= 名额闸吞掉投递会留下的悬置形态），
    # 且终态后在飞数归零（名额全部归还，队列排空）。
    stuck = [j for j in ctx["ids"]
             if _status(jobs, j).get("state") == "pending"
             and os.path.exists(os.path.join(jobs, j, "claimed.lock"))]
    check("D4 名额闸未破坏 N191 不变量：无 pending+锁悬置，终态后在飞数归零",
          not stuck and _in_flight(jobs) == 0,
          "stuck=%s in_flight=%d states=%s" % (stuck, _in_flight(jobs), states))


# -------------------------------------------------------------------- E 组：两态端到端

def g_e():
    """E 组：真实 serve + 桩执行器的端到端两态（干净池全 done / 混坏 status 共存）。"""
    begin("E")
    ctx = {"note": "", "clean": ["h1700000000e01_abcd", "h1700000000e02_abcd",
                                 "h1700000000e03_abcd"],
           "corrupt": "h1700000000e04_abcd"}
    exe = _exe()
    if exe is None:
        ctx["note"] = "编译未产出可执行件"
    if ctx["note"]:
        for name in ("E1 干净池端到端全 done（桩产物可读）",
                     "E2a 同池坏 status 字节逐字节不动",
                     "E2b 同池坏 status 不产出 result.json（不被执行）",
                     "E2c 同池健康任务照常全 done（两态共存互不干扰）",
                     "E3 serve 未被坏文件绊死（心跳 ts 持续前进）",
                     "E4 serve 进程零 panic"):
            check(name, False, ctx["note"])
        return
    tmp = _tmpdir("h3h7_e_")
    jobs, stub = _pool(tmp)
    raw = _make_corrupt(jobs, ctx["corrupt"], "0")
    for jid in ctx["clean"]:
        _make_pending(jobs, jid, "0.3")
    _start_serve(exe, jobs, stub, workers=2)
    if not _wait_serve(jobs):
        for name in ("E1 干净池端到端全 done（桩产物可读）",
                     "E2a 同池坏 status 字节逐字节不动",
                     "E2b 同池坏 status 不产出 result.json（不被执行）",
                     "E2c 同池健康任务照常全 done（两态共存互不干扰）",
                     "E3 serve 未被坏文件绊死（心跳 ts 持续前进）",
                     "E4 serve 进程零 panic"):
            check(name, False, "serve 心跳未出现（临时池）")
        return
    ts0 = (_cli_json(exe, ["doctor", "--jobs", jobs]).get("serve") or {}).get("pid")
    hb1 = json.load(open(os.path.join(jobs, "_serve.json"), encoding="utf-8"))
    _wait_until(lambda: all(_status(jobs, j).get("state") == "done"
                            for j in ctx["clean"]), 30.0)
    # 阈值窗内等到标记落场再读字节（**独立夹具的第二检测面**：A/B 共用一个夹具，
    # E 另起一个——「本体不被改写」于是有两处互不依赖的观测量；不等阈值的话
    # E 的窗口短于标记落场时刻，M2 那类「把标记写到本体路径」的变异在此漏网）。
    ctx["marker_in_time"] = _wait_until(
        lambda: os.path.isfile(os.path.join(jobs, ctx["corrupt"], MARKER)),
        CORRUPT_MARK_TICKS * POLL_MS / 1000.0 + 5.0)
    res = {}
    with contextlib.suppress(OSError, ValueError):
        with open(os.path.join(jobs, ctx["clean"][0], "result.json"),
                  encoding="utf-8") as f:
            res = json.load(f)
    check("E1 干净池端到端全 done（桩产物可读）",
          all(_status(jobs, j).get("state") == "done" for j in ctx["clean"])
          and res.get("content") == "h3h7-guard-stub",
          "states=%s result=%s"
          % ({j: _status(jobs, j).get("state") for j in ctx["clean"]},
             json.dumps(res, ensure_ascii=False)[:150]))
    check("E2a 同池坏 status 字节逐字节不动（标记落场之后读出）",
          _raw(os.path.join(jobs, ctx["corrupt"], "status.json")) == raw,
          "now=%r" % _raw(os.path.join(jobs, ctx["corrupt"], "status.json")))
    check("E2b 同池坏 status 不产出 result.json（不被执行）",
          not os.path.exists(os.path.join(jobs, ctx["corrupt"], "result.json")),
          "files=%s" % sorted(_files(jobs, ctx["corrupt"])))
    check("E2c 同池健康任务照常全 done（两态共存互不干扰）",
          all(_status(jobs, j).get("state") == "done" for j in ctx["clean"]))
    hb2 = json.load(open(os.path.join(jobs, "_serve.json"), encoding="utf-8"))
    check("E3 serve 未被坏文件绊死（心跳 ts 持续前进）",
          isinstance(hb2.get("ts"), (int, float))
          and isinstance(hb1.get("ts"), (int, float))
          and hb2.get("ts") > hb1.get("ts") and ts0 == hb2.get("pid"),
          "hb1=%s hb2=%s" % (hb1.get("ts"), hb2.get("ts")))
    ok, note = _serve_alive_after(jobs)
    check("E4 serve 进程零 panic", ok, "note=%s" % note)


_GROUPS = (("A", g_a), ("B", g_b), ("C", g_c), ("D", g_d), ("E", g_e))


# 生效条件：重算计数器后依次跑 A–E 五组（静默与否由 print 决定），返回
# (总失败数, {组名: 失败数} 的副本)；供正常模式与 --branch-baseline 的变异核验共用。
def _run_groups():
    _reset_counters()
    for _name, fn in _GROUPS:
        fn()
    return FAIL, dict(_GROUP_FAILS)


# ---------------- 定点变异自证（--branch-baseline） ----------------
# 变异表：逐处关掉一个判据，守卫**必须转红**，且红项**恰好**落在该判据负责的组、
# 数量等于下表声明值（多一项少一项都报红）。基线源 = **工作区源码 × 临时副本现场
# 编译**（锚点在 hive/src/*.rs 里必须**恰好出现一次**，否则 ANCHOR-MISS 退出 2）。
_MUTATIONS = (
    ("H-3 标记落盘阈值（坏 status 达阈值 → 独立标记）",
     "src/scheduler.rs",
     "if ticks >= CORRUPT_MARK_TICKS {",
     "if false {",
     # B2 同红是**真实耦合**（非噪声）：B2 断「标记是独立文件」，标记不落场自然不成立
     # （B1/B3/B4 三条字节判据仍绿——它们钉的是「不写本体」，不由阈值判据负责）。
     {"A": 2, "B": 1}),
    ("H-3 不覆盖任务本体（标记写的目标路径）",
     "src/job.rs",
     "write_json(&corrupt_mark_path(dir), &v)",
     'write_json(&dir.join("status.json"), &v)',
     {"A": 4, "B": 2, "E": 1}),
    ("H-3 三态分类（Corrupt 与 Absent 不分 → 坏 status 静默）",
     "src/job.rs",
     "        Err(e) => StatusRead::Corrupt(e),",
     "        Err(_) => StatusRead::Absent,",
     {"A": 6, "B": 1, "C": 5}),
    ("H-3 坏 status 扫描单点实现（启动告警 + 隔离判据共用的 scan_corrupt）",
     "src/scheduler.rs",
     "            out.push((id, e));",
     "            let _ = (id, e);",
     {"A": 1, "C": 5}),
    ("H-3 隔离件对领取面不可见（保留区命名非 h 前缀）",
     "src/job.rs",
     'pub const QUARANTINE_DIR: &str = "_quarantine";',
     'pub const QUARANTINE_DIR: &str = "h_quarantine";',
     # C3 同红是**真实耦合**：C3 按契约路径 jobs/_quarantine/<id>/status.json 读隔离件，
     # 保留区一改名就读不到（判据是契约名，不是「随便搬哪儿都算」）。
     {"C": 2}),
    ("H-7 在飞名额闸（先占名额再 claim 的上界）",
     "src/scheduler.rs",
     "if !at_capacity && !inflight.try_acquire() {",
     "if false && !inflight.try_acquire() {",
     {"D": 2}),
)


# 生效条件：无入参——跑定点变异自证：先跑未变异基线（必须零失败），再逐个应用
# _MUTATIONS：锚点缺失/不唯一立即打印 ANCHOR-MISS 并返回 2（fail-closed，不再继续）；
# 每次变异后重编译副本并重跑全部组，红项组与数量必须与声明完全一致，否则计入 bad；
# 全部通过返回 0，存在不符返回 1。
def _branch_baseline() -> int:
    print("!! 定点变异模式：逐处关掉判据，守卫应当转红且**恰好**命中预期组/项数\n")
    if _exe() is None:
        print("  编译未产出可执行件 → 定点变异自证无法进行")
        return 1
    with contextlib.redirect_stdout(io.StringIO()):
        clean_fail, _clean_groups = _run_groups()
    _cleanup()
    print("  未变异基线：失败=%d" % clean_fail)
    if clean_fail:
        print("  基线即失败 → 定点变异自证无意义（先修基线）")
        return 1
    bad = []
    for label, rel, anchor, new, expect in _MUTATIONS:
        restore = _patch(rel, anchor, new)
        if restore is None:
            print("  ANCHOR-MISS %s —— 变异锚点漂移（实现改了却没同步本表；"
                  "锚点须在 %s 中恰好出现一次）" % (label, rel))
            return 2                      # fail-closed：锚点漂移不静默失效
        try:
            ok, log = _cargo_build()
            if not ok:
                print("  关掉「%s」→ 变异件编译失败（无法取红基线）\n%s"
                      % (label, log))
                bad.append(label)
                continue
            with contextlib.redirect_stdout(io.StringIO()):
                got_fail, got_groups = _run_groups()
                got_fails = list(FAILS)
        finally:
            restore()
            _cleanup()                    # 每轮清干净：临时根与活进程不跨轮累积
        hit = {g: n for g, n in got_groups.items() if n}
        if hit == expect and got_fail == sum(expect.values()):
            print("  关掉「%s」→ 红项=%d，命中组=%s（恰好命中预期）"
                  % (label, got_fail, dict(sorted(hit.items()))))
        else:
            print("  关掉「%s」→ 红项=%d，命中组=%s  期望=%s  "
                  "**红基线失效（判别力面不符）**"
                  % (label, got_fail, dict(sorted(hit.items())),
                     dict(sorted(expect.items()))))
            for nm in got_fails:          # 逐条点名：判别力面差在哪，一眼可读
                print("      · %s" % nm)
            bad.append(label)
    # 还原后的副本必须仍能编译（证明还原干净、工作区未被污染）
    ok, log = _cargo_build()
    print("\n  还原后重编译：%s" % ("ok" if ok else "失败\n%s" % log))
    if not ok:
        bad.append("还原后重编译")
    print("\n定点变异自证：%s" % ("PASS（每处判据都有断言把它钉死）"
                                  if not bad else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


# 生效条件：命令行含 --branch-baseline 时走定点变异自证（退出码 0/1/2）；否则依次跑
# A–E 五组打印逐条结果与汇总，全部通过返回 0、存在失败返回 1。
def main() -> int:
    if "--branch-baseline" in sys.argv:
        try:
            return _branch_baseline()
        finally:
            _cleanup()
            _cleanup_persist()
    try:
        _reset_counters()
        for _name, fn in _GROUPS:
            fn()
    finally:
        _cleanup()
        _cleanup_persist()
    print("\n%d passed, %d failed" % (PASS, FAIL))
    if FAILS:
        print("FAILED: " + "、".join(FAILS))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
