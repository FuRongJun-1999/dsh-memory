# -*- coding: utf-8 -*-
"""蜂巢 H-6 守卫 · MCP 面 / 编排面的 spec.depends_on 依赖门禁

缺陷（修复前，本守卫在旧实现上必红）：
仓库根 README 以「I-1 依赖门禁：spec.depends_on 任务 DAG」为卖点，但**只有 CLI
`hive submit` 支持**，两道闸都只长在 CLI 上：
  · 格式闸   `hive/src/spec.rs:203`（`job::valid_job_id`：h 开头且不含路径成分）；
  · 存在性闸 `hive/src/main.rs:289`（`jobs.join(dep).is_dir()`，否则 fail fast）。
而 MCP 工具面 `hive/hive_mcp/mcp_server.py` 的 `_t_spawn` **既不接受也不写**
`depends_on`（入参白名单里没有它，传了即被显式拒绝），`_submit` 也不做任何校验；
编排面 `hive/orch.py::_spawn` 的子 spec 键白名单循环里同样没有 `depends_on`
⇒ **程序化接入（含 orch 派生的子任务）根本无法使用依赖门禁**，唯 CLI 一条路。
调度侧语义本身早已可用且正确（`hive/src/scheduler.rs::deps_gate` 读 spec.json 的
`depends_on`），缺的只是「提交面能把该键写进去」。

修复（判据不分叉，单点实现）：
  ① `mcp_server._t_spawn` 接受 `depends_on`（列表）并在**写 spec 之前**过闸，
     通过后原样写入 spec（保序、不裁剪；显式 `[]` 也落键＝提交方声明「无依赖」）；
  ② 两道闸的**唯一实现** = `mcp_server._dep_gate`：格式判据复用 `_valid_job_id`
     （与 rust `job::valid_job_id` 同口径的唯一实现），存在性判据与 CLI 同为
     「是目录」（同名**文件**不算）；不过闸即 `ok=False` + 可读原因 —— 不写
     spec、不拉 serve、**不静默忽略、不降级为「无依赖」**；
  ③ `hive/orch.py::_spawn` 白名单透传 `depends_on`（显式传值优先、缺省不写），
     并在提交前调**同一个** `_hm._dep_gate`（模型可控参数，闸必须同源）。

守卫构成（组与判据一一对应，「恰好等于该组断言数」才可成立）：
  A  4 条：MCP 面正向 + **真实 serve 的领取时序**——spec.json 落盘含该键 /
     值逐项一致 / 依赖未终态时**不被领取** / 依赖 done 后**才**被领取且终态 done
     （领取时刻不早于依赖 done 的 status.json 落盘时刻）
  B 10 条：MCP 面格式闸逐 id 拒（`../x`、`x123`、`h/../../x`、`..`、`h\\..`、`h:x`、
     `h.%.txt`、`h1_a `、空串、`h..`）——每条断言 ok=False 且原因含「项非法」
  C  2 条：MCP 面存在性闸逐 id 拒（合法格式但目录不存在 / 同名**文件**而非目录）
  D 21 条：**rust/python 逐项对照**——同一批 20 个 depends_on 取值分别喂给
     `hive.exe submit`（rust spec::validate + main.rs 两闸）与 `_t_spawn`
     （python 两面闸），逐项分类必须相等；另 1 条钉「python 侧分类分布非退化」
     （accept / fmt_reject / exist_reject 三态都真实出现过——防闸门被整体关掉
     却因两侧同步退化而看不出）
  E  1 条：格式闸拦截的 `..`（其路径恰是存在的目录）被拒后**池中不新增任务目录**
  E2 1 条：存在性闸拦截的 id 被拒后**池中不新增任务目录**
  F  1 条：**缺省不写**——不传 `depends_on` 时 ok=True 且 spec 无该键
  G  1 条：**非列表即拒**（裸字符串）——ok=False 且原因含「列表」
  H  1 条：`orch._spawn` 透传（桩 `_hm._submit` 捕获子 spec，含 depends_on 且逐项一致）
  I  1 条：`orch._spawn` 缺省不写（不带该参数时子 spec 无该键）

`--branch-baseline` 定点变异自证（与 `md_cg/test_n225_nonobject_load.py` /
`test_neg_condition_hits` 同口径）：逐个关掉一处判据，守卫**必须转红**，且红项
**恰好**落在判据负责的组、数量等于声明的值（多一项少一项都报红）；锚点漂移报
``ANCHOR-MISS`` 并以**退出码 2** fail-closed 停手。基线源 = **工作区源码**
（``inspect.getsource`` 取自当前已加载模块），绝不绑 git HEAD——本仓批次 80/81
教训：基线绑提交那一刻即失效。

隔离纪律（硬边界）：一切实验落在 ``tempfile.mkdtemp`` 的临时 jobs 池上——
A 组拉起的是**临时池专属**的 serve（``--jobs <临时池>``，env 剔净 HIVE_*/MDCG_*），
跑完即杀进程树并 rmtree；**绝不触在役 ~/.hive、在役 jobs 池、在役 serve 与任何
数据根**。提交走进程内 `_t_spawn`（env `HIVE_JOBS_DIR` + `_jobs_dir`/`_ensure_serve`/
`_result_anchor_key` 四处打桩：不拉真 serve、不写锚 nonce——锚链有专门守卫
test_result_anchor_chain），且每次提交前过 `_assert_isolated`（冻结引用解析出的池
必须是本次临时池，否则抛错判红）——变异轮的 exec 副本也逃不出去。**首版实测教训**
（2026-09-29）：`_patch` 曾把变异源码 exec 进 `vars(mod)` 的**快照副本**，变异函数
的 globals 看不见 `mock.patch.object`，提交遂落进在役 jobs 池并由在役 serve 领取；
已改为 exec 进模块 `__dict__`（globals 为活命名空间）+ `_assert_isolated` 双保险。

运行：
  python -X utf8 -m hive.test_h6_mcp_depends_on                    # 正向
  python -X utf8 -m hive.test_h6_mcp_depends_on --branch-baseline  # 定点变异自证
（退出码 0 = 全绿 / 1 = 有失败 / 2 = 变异锚点漂移）
"""
from __future__ import annotations

import contextlib
import inspect
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from unittest import mock

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for _p in (_REPO, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hive_mcp.mcp_server as _hm          # noqa: E402
import orch as _orch                       # noqa: E402

# 真实池解析函数的**冻结引用**（在任何打桩之前取）：隔离自检用它——若解析结果不是
# 本次的临时池，一律拒绝提交（fail-closed）。**绝不允许落到在役 jobs 池**
# （2026-09-29 本守卫首版实测教训：变异轮里 exec 出来的函数副本若拿到的是模块
# 全局的**快照**，`mock.patch.object` 打不上，提交会落进在役池并由在役 serve 领取）。
_REAL_JOBS_DIR = _hm._jobs_dir

HIVE_EXE = os.path.join(_REPO, "hive", "target", "release",
                        "hive.exe" if os.name == "nt" else "hive")

# 桩执行器（与 hive/hive_mcp/smoke_test.py 的 FAKE_EXEC 同构）：user_prompt 当
# 睡眠秒数（0/空 = 立即完成），写完 result.json 退出 0。**不写 result_anchor**，
# 因为本守卫的提交面被打了 _result_anchor_key→None 的桩（任务不带 result_nonce
# ⇒ 锚校验走「旧格式」分支，不引入 needs_review 噪声）。
_STUB_EXEC = r"""
import sys, json, time, os
d = sys.argv[1]
with open(os.path.join(d, "spec.json"), encoding="utf-8") as f:
    spec = json.load(f)
time.sleep(float(spec.get("user_prompt") or 0))
r = {"ok": True, "content": "h6-guard-stub-done", "completed": True}
with open(os.path.join(d, "result.json"), "w", encoding="utf-8") as f:
    json.dump(r, f, ensure_ascii=False)
"""

PASS, FAIL = 0, 0
FAILS = []
_CURRENT = ["?"]
_GROUP_FAILS = {}
_TMP_ROOTS = []        # 每轮清理（变异轮之间不跨轮累积）
_PERSIST_ROOTS = []    # 只在本进程收尾时清理（对照组的池须跨变异轮存活）
_PROCS = []
_RUST_CACHE = {}
_PARITY = {"jobs": None}


# 生效条件：把 PASS/FAIL/失败名单/分组失败数清零并解除当前组名（每次完整跑套件前
# 调用；--branch-baseline 每个变异轮都要一次干净基线）。
def _reset_counters():
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    _GROUP_FAILS.clear()
    _CURRENT[0] = "?"


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
# detail（**不中断整组**，保证「变异下红项数 == 该组断言数」这一精确口径成立）；fn
# 正常返回则按返回值真假记账；detail 传 callable 时在同一保护下求值。
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


# 生效条件：新建系统临时目录（prefix 前缀）并登记进 _TMP_ROOTS（每轮 _cleanup 清理）。
def _tmpdir(prefix: str) -> str:
    p = tempfile.mkdtemp(prefix=prefix)
    _TMP_ROOTS.append(p)
    return p


# 生效条件：无入参——对 _PROCS 每个仍存活的 serve 先 taskkill /T /F（unix 用 kill，
# 与 test/chaos_injection/harness.py 同款：Windows 须收进程树，否则孙进程成孤儿），
# 再 rmtree 掉 _TMP_ROOTS 全部临时根；幂等，收尾不再抛。
def _cleanup():
    for p in _PROCS:
        try:
            if p.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                                   capture_output=True, text=True,
                                   encoding="utf-8", errors="replace")
                else:
                    p.kill()
        except OSError:
            pass
        finally:
            try:
                p.wait(timeout=5)
            except Exception:             # noqa: BLE001
                pass
    del _PROCS[:]
    for d in _TMP_ROOTS:
        shutil.rmtree(d, ignore_errors=True)
    del _TMP_ROOTS[:]


# 生效条件：无入参——清掉 _PERSIST_ROOTS（跨变异轮存活的对照池），进程收尾用。
def _cleanup_persist():
    for d in _PERSIST_ROOTS:
        shutil.rmtree(d, ignore_errors=True)
    del _PERSIST_ROOTS[:]


# ------------------------------------------------------------------ 池与文件辅助

# 生效条件：deps 为 dict、jobs 给定——写 spec.json 到临时 spec 目录（比对裸值：
# 非数组形态也原样写出，与 rust 侧 as_str_vec 的宽松读法构成对照面）。
def _write_spec(spec_dir: str, spec: dict) -> str:
    os.makedirs(spec_dir, exist_ok=True)
    p = os.path.join(spec_dir, "spec.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False)
    return p


# 生效条件：jobs/jid/status.json 可解析为 dict 时返回它，缺失/坏 JSON → {}。
def _read_status(jobs: str, jid: str) -> dict:
    try:
        with open(os.path.join(jobs, jid, "status.json"), encoding="utf-8") as f:
            st = json.load(f)
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


# 生效条件：轮询 jobs/jid/status.json 直到 state ∈ want（str 或集合）——命中即返回
# (state, st)；超时返回最后一次读到的 (state, st)（读不到为 (None, {})）。
def _wait_state(jobs: str, jid: str, want, timeout_s: float, poll_s: float = 0.15):
    if isinstance(want, str):
        want = {want}
    t0 = time.time()
    st = {}
    while time.time() - t0 < timeout_s:
        st = _read_status(jobs, jid)
        if st.get("state") in want:
            return st.get("state"), st
        time.sleep(poll_s)
    st = _read_status(jobs, jid)
    return st.get("state"), st


# 生效条件：jobs 下以 "h" 开头且为目录的名字集合（快照口径：只数任务目录，忽略
# _serve.json/_chaos_serve.log 一类池级文件）。
def _job_dir_names(jobs: str) -> set:
    return {n for n in os.listdir(jobs)
            if n.startswith("h") and os.path.isdir(os.path.join(jobs, n))}


# 生效条件：jobs 给定——返回该路径；解析结果与 jobs 不一致时抛 RuntimeError（隔离
# 面失守，调用方按红处置）。判据走 _REAL_JOBS_DIR（冻结引用）且 env 由 _iso 钉住，
# 故**变异轮里 exec 出来的函数副本**（globals 为快照、看不见 mock.patch）也逃不出去。
def _assert_isolated(jobs: str) -> str:
    got = os.path.abspath(_REAL_JOBS_DIR())
    want = os.path.abspath(jobs)
    if got != want:
        raise RuntimeError("隔离面失守：jobs 解析到 %s，期望临时池 %s —— 拒绝提交"
                           % (got, want))
    return jobs


# 生效条件：jobs 给定——在临时池上进程内提交（env HIVE_JOBS_DIR + _jobs_dir 双钉
# 同一临时池、_ensure_serve 打桩不拉 serve、_result_anchor_key 打桩为 None 以不写锚
# nonce），进入前先过 _assert_isolated，返回 _t_spawn 的响应 dict。
@contextlib.contextmanager
def _iso(jobs: str):
    with mock.patch.dict(os.environ, {"HIVE_JOBS_DIR": jobs}), \
            mock.patch.object(_hm, "_jobs_dir", lambda: jobs), \
            mock.patch.object(_hm, "_ensure_serve",
                              lambda j: {"started": False, "note": "h6-guard-stub"}), \
            mock.patch.object(_hm, "_result_anchor_key", lambda: None):
        _assert_isolated(jobs)
        yield


# 生效条件：jobs 与 args 给定——在隔离形态下调 _t_spawn（见 _iso）。
def _spawn_in(jobs: str, args: dict) -> dict:
    with _iso(jobs):
        return _hm._t_spawn(args)


# 生效条件：jobs 与 args 给定——_spawn_in 的**不抛**包装：异常（含隔离面失守）归成
# {'ok': False, 'error': 'raise:<类型>: <消息>'}，使断言计数稳定（红一条而非崩一组）。
def _spawn_safe(jobs: str, args: dict) -> dict:
    try:
        return _spawn_in(jobs, args)
    except Exception as exc:              # noqa: BLE001 —— 隔离失守/变异态都按红
        return {"ok": False, "error": "raise:%s: %s" % (type(exc).__name__, exc)}


# --------------------------------------------------------------- A 组：真实 serve

# 生效条件：stub_py 给定且 HIVE_EXE 存在——以剔净全部 HIVE_*/MDCG_* 注入面的 env
# 在临时池上起 `hive serve --jobs <池> --workers 1`（HIVE_EXEC_PY=stub），登记
# Popen 返回；EXE 不存在返回 None（调用方按前置缺失判红）。
def _start_serve(jobs: str, stub_py: str):
    if not os.path.isfile(HIVE_EXE):
        return None
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("HIVE_") and not k.startswith("MDCG_")}
    env["HIVE_EXEC_PY"] = stub_py
    env["HIVE_WORKERS"] = "1"
    env["PYTHONUTF8"] = "1"
    logf = open(os.path.join(jobs, "_h6_serve.log"), "ab")
    try:
        p = subprocess.Popen([HIVE_EXE, "serve", "--jobs", jobs, "--workers", "1"],
                             stdout=logf, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, env=env, cwd=_REPO)
    finally:
        logf.close()
    _PROCS.append(p)
    return p


# 生效条件：jobs 给定——轮询 _serve.json 心跳出现且 ts 新鲜（≤10s 视为本进程刚起的
# serve 已进入主循环），命中返回 True；超时 False。
def _wait_serve(jobs: str, timeout_s: float = 10.0) -> bool:
    p = os.path.join(jobs, "_serve.json")
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            with open(p, encoding="utf-8") as f:
                hb = json.load(f)
            if isinstance(hb, dict) and hb.get("pid"):
                return True
        except (OSError, ValueError):
            pass
        time.sleep(0.15)
    return False


# 生效条件：无入参——A 组夹具：临时池 + 桩执行器 + 真实 serve。返回 ctx dict，键：
# ok/dep/child（job_id）、spec（子 job 的 spec.json 内容）、dep_active（依赖在观察
# 窗口内的 state）、child_before（观察窗口内子任务的 state）、child_locked（窗口内
# 是否已有 claimed.lock）、dep_final/child_final（终态）、lock_ts/dep_done_ts、
# note（前置缺失原因，空串 = 前置齐备）。
def _case_real_claim():
    ctx = {"ok_dep": False, "ok_child": False, "dep": None, "child": None,
           "spec": None, "dep_active": None, "child_before": None,
           "child_locked": None, "dep_final": None, "child_final": None,
           "lock_ts": None, "dep_done_ts": None, "note": ""}
    tmp = _tmpdir("h6_real_")
    jobs = os.path.join(tmp, "jobs")
    os.makedirs(jobs)
    stub = os.path.join(tmp, "stub_exec.py")
    with open(stub, "w", encoding="utf-8") as f:
        f.write(_STUB_EXEC)
    if not os.path.isfile(HIVE_EXE):
        ctx["note"] = "未找到 %s（先 cargo build --release）" % HIVE_EXE
        return ctx
    if _start_serve(jobs, stub) is None:
        ctx["note"] = "serve 未能拉起"
        return ctx
    if not _wait_serve(jobs):
        ctx["note"] = "serve 心跳未出现（临时池）"
        return ctx
    # 依赖任务：真任务、user_prompt="4" ⇒ 桩执行器睡 4s，观察窗口内必然未 done
    rd = _spawn_safe(jobs, {"model": "guard-model", "user_prompt": "4",
                          "timeout_s": 60})
    ctx["ok_dep"] = rd.get("ok") is True
    ctx["dep"] = rd.get("job_id")
    if not ctx["dep"]:
        ctx["note"] = "依赖任务提交失败: %s" % json.dumps(rd, ensure_ascii=False)[:200]
        return ctx
    _wait_state(jobs, ctx["dep"], {"claimed", "running"}, 8.0)
    # 子任务：依赖上面那条（尚未终态）
    rc = _spawn_safe(jobs, {"model": "guard-model", "user_prompt": "0",
                          "timeout_s": 60, "depends_on": [ctx["dep"]]})
    ctx["ok_child"] = rc.get("ok") is True
    ctx["child"] = rc.get("job_id")
    if not ctx["child"]:
        ctx["note"] = "子任务提交失败: %s" % json.dumps(rc, ensure_ascii=False)[:200]
        return ctx
    try:
        with open(os.path.join(jobs, ctx["child"], "spec.json"),
                  encoding="utf-8") as f:
            ctx["spec"] = json.load(f)
    except (OSError, ValueError):
        ctx["spec"] = None
    # —— 观察窗口：依赖仍在跑（未终态）⇒ 子任务不得被领取
    time.sleep(1.2)
    ctx["dep_active"] = _read_status(jobs, ctx["dep"]).get("state")
    ctx["child_before"] = _read_status(jobs, ctx["child"]).get("state")
    ctx["child_locked"] = os.path.exists(
        os.path.join(jobs, ctx["child"], "claimed.lock"))
    # —— 依赖跑完 → done；此后子任务才可领取
    ctx["dep_final"], _ = _wait_state(jobs, ctx["dep"], {"done"}, 20.0)
    try:
        ctx["dep_done_ts"] = os.path.getmtime(
            os.path.join(jobs, ctx["dep"], "status.json"))
    except OSError:
        ctx["dep_done_ts"] = None
    ctx["child_final"], _ = _wait_state(
        jobs, ctx["child"],
        {"done", "error", "timeout", "killed", "needs_review"}, 20.0)
    lock = os.path.join(jobs, ctx["child"], "claimed.lock")
    try:
        ctx["lock_ts"] = os.path.getmtime(lock)
    except OSError:
        ctx["lock_ts"] = None
    return ctx


# 生效条件：跑 A 组 4 条断言——① 子任务提交 ok 且 spec.json 含 depends_on 键；
# ② 该键值与传入逐项一致（保序）；③ 依赖未终态时子任务保持 pending 且无
# claimed.lock；④ 依赖 done 后子任务才被领取且终态 done（领取时刻不早于依赖 done
# 写盘时刻）。夹具前置缺失（无 hive.exe/拉起失败）时四条各自判红并给出原因。
def g_a():
    begin("A")
    ctx = _case_real_claim()
    note = ctx["note"] or ""
    spec = ctx["spec"] or {}
    check("A1·MCP 面提交带 depends_on 的任务 → spec.json 落盘含该键",
          ctx["ok_child"] and ctx["ok_dep"] and "depends_on" in spec,
          "note=%s ok_child=%s spec_keys=%s" % (
              note, ctx["ok_child"], sorted(spec.keys()) if spec else None))
    check("A2·落盘值与提交参数逐项一致（保序、不裁剪）",
          spec.get("depends_on") == [ctx["dep"]] and ctx["dep"] is not None,
          "spec_depends_on=%r dep=%r" % (spec.get("depends_on"), ctx["dep"]))
    check("A3·依赖未 done 时不被领取（观察窗口内 pending 且无 claimed.lock）",
          ctx["dep_active"] in ("claimed", "running")
          and ctx["child_before"] == "pending"
          and ctx["child_locked"] is False,
          "dep_state=%r child_state=%r locked=%r note=%s" % (
              ctx["dep_active"], ctx["child_before"], ctx["child_locked"], note))
    ok4 = (ctx["dep_final"] == "done" and ctx["child_final"] == "done"
           and ctx["lock_ts"] is not None and ctx["dep_done_ts"] is not None
           and ctx["lock_ts"] >= ctx["dep_done_ts"] - 0.05
           and ctx["child_locked"] is False)
    check("A4·依赖 done 后才被领取且终态 done（领取不早于依赖 done 写盘）",
          ok4, "dep_final=%r child_final=%r lock_ts=%r dep_done_ts=%r note=%s"
               % (ctx["dep_final"], ctx["child_final"], ctx["lock_ts"],
                  ctx["dep_done_ts"], note))


# ------------------------------------------------------ B/C/E/E2 组：两面闸的拒面

# 格式非法 id（每项一条断言；`..` 的路径恰是存在的目录，故它同时是 E 组的载体）。
_FMT_BAD = ("../x", "x123", "h/../../x", "..", "h\\..", "h:x",
            "h.%.txt", "h1_a ", "", "h..")


# 生效条件：跑 B 组 10 条断言——每个格式非法 id 在 MCP 面提交都返回 ok=False 且
# 原因含「项非法」（与 spec.rs 的文案同口径）。
def g_b():
    begin("B")
    jobs = os.path.join(_tmpdir("h6_fmt_"), "jobs")
    os.makedirs(jobs)
    for i, dep in enumerate(_FMT_BAD):
        r = _spawn_safe(jobs, {"model": "guard-model", "user_prompt": "x",
                             "timeout_s": 60, "depends_on": [dep]})
        err = r.get("error") or ""
        check("B%d·格式非法被拒 %r" % (i + 1, dep),
              r.get("ok") is False and "项非法" in err,
              "ok=%r error=%r" % (r.get("ok"), err[:160]))


# 生效条件：跑 C 组 2 条断言——合法格式但「目录不存在」与「同名文件而非目录」
# 两种形态都被存在性闸拒（ok=False 且原因含「依赖不完整」）。
def g_c():
    begin("C")
    jobs = os.path.join(_tmpdir("h6_exist_"), "jobs")
    os.makedirs(jobs)
    with open(os.path.join(jobs, "h_notadir_x"), "w", encoding="utf-8") as f:
        f.write("x")            # 名字合法但是**文件**——rust is_dir() 与 python isdir 同拒
    for i, dep in enumerate(("h1999999999999_zz", "h_notadir_x")):
        r = _spawn_safe(jobs, {"model": "guard-model", "user_prompt": "x",
                             "timeout_s": 60, "depends_on": [dep]})
        err = r.get("error") or ""
        check("C%d·不存在的依赖被拒 %s" % (i + 1, dep),
              r.get("ok") is False and "依赖不完整" in err,
              "ok=%r error=%r" % (r.get("ok"), err[:160]))


# 生效条件：跑 E 组 1 条断言——`..` 是格式非法 id 但其路径（池的父目录）确实存在，
# 被拒后池中任务目录集必须**一个不增**（不静默写入半成品）（若格式闸被关掉，它会被
# 存在性判据放行并落盘 ⇒ 本条转红）。
def g_e():
    begin("E")
    jobs = os.path.join(_tmpdir("h6_silent_"), "jobs")
    os.makedirs(jobs)
    before = _job_dir_names(jobs)
    r = _spawn_safe(jobs, {"model": "guard-model", "user_prompt": "x",
                         "timeout_s": 60, "depends_on": [".."]})
    after = _job_dir_names(jobs)
    check_fn("E1·格式闸拦截后池中不新增任务目录（不静默写入/不降级为无依赖）",
             lambda: r.get("ok") is False and after == before,
             "ok=%r before=%s after=%s" % (r.get("ok"), sorted(before),
                                           sorted(after)))


# 生效条件：跑 E2 组 1 条断言——存在性闸拦截的 id 被拒后池中任务目录集一个不增。
def g_e2():
    begin("E2")
    jobs = os.path.join(_tmpdir("h6_silent2_"), "jobs")
    os.makedirs(jobs)
    before = _job_dir_names(jobs)
    r = _spawn_safe(jobs, {"model": "guard-model", "user_prompt": "x",
                         "timeout_s": 60, "depends_on": ["h1999999999999_zz"]})
    after = _job_dir_names(jobs)
    check_fn("E2·存在性闸拦截后池中不新增任务目录（不静默写入）",
             lambda: r.get("ok") is False and after == before,
             "ok=%r before=%s after=%s" % (r.get("ok"), sorted(before),
                                           sorted(after)))


# --------------------------------------------------- F/G 组：类型面与缺省不写

# 生效条件：跑 F 组 1 条断言——**不传** depends_on 时提交照常成功且 spec.json 无该键
# （缺省不写；「无依赖」不是靠写空数组表达的，也不得凭空落键）。
def g_f():
    begin("F")
    jobs = os.path.join(_tmpdir("h6_nokey_"), "jobs")
    os.makedirs(jobs)
    r = _spawn_safe(jobs, {"model": "guard-model", "user_prompt": "x",
                         "timeout_s": 60})
    spec = {}
    if r.get("job_id"):
        try:
            with open(os.path.join(jobs, r["job_id"], "spec.json"),
                      encoding="utf-8") as f:
                spec = json.load(f)
        except (OSError, ValueError):
            spec = {}
    check("F1·缺省不带 depends_on → ok=True 且 spec 不含该键（缺省不写）",
          r.get("ok") is True and spec and "depends_on" not in spec,
          "ok=%r spec_keys=%s" % (r.get("ok"), sorted(spec.keys()) if spec else None))


# 生效条件：跑 G 组 1 条断言——裸字符串（非列表）被类型闸拒：ok=False 且原因明确指出
# 须为字符串列表（不静默强转；CLI 侧 as_str_vec 的宽松采信是 CLI 的历史口径，本工具
# 面 schema 声明的是 array，故有意更严——见 mcp_server._dep_gate 注释）。
def g_g():
    begin("G")
    jobs = os.path.join(_tmpdir("h6_type_"), "jobs")
    os.makedirs(jobs)
    r = _spawn_safe(jobs, {"model": "guard-model", "user_prompt": "x",
                         "timeout_s": 60, "depends_on": "h1_a"})
    err = r.get("error") or ""
    check("G1·非列表（裸字符串）被拒且原因含「列表」",
          r.get("ok") is False and "列表" in err,
          "ok=%r error=%r" % (r.get("ok"), err[:160]))


# ------------------------------------------------- D 组：rust / python 逐项对照

# 对照批次（全部包成**数组**喂 depends_on：本对照的判据面是「同一个 id 两侧判定」，
# 数组外的形态差异（裸串）已在 G 组单独钉住）。真值 = 预建目录（accept 面）与
# 同名文件/缺目录（存在性拒面）。
_PARITY_CASES = (
    ("已有目录的合法 id", ["h1758000000000_1a2b"]),
    ("已有目录的短合法 id", ["h1_a"]),
    ("已有目录的仅 h 前缀 id", ["h"]),
    ("合法格式但目录不存在", ["h1999999999999_zz"]),
    ("合法格式但同名是文件", ["h_notadir_x"]),
    ("不以 h 开头", ["x123"]),
    ("相对路径穿越", ["../victim"]),
    ("父目录锚", [".."]),
    ("h + 路径穿越", ["h/../../x"]),
    ("反斜杠穿越", ["h\\.."]),
    ("冒号（盘符/ADS 面）", ["h:x"]),
    ("百分号与点", ["h.%.txt"]),
    ("尾随空格", ["h1_a "]),
    ("空串", [""]),
    ("整型元素", [123]),
    ("布尔元素", [True]),
    ("null 元素", [None]),
    ("嵌套数组元素", [["h1_a"]]),
    ("一好一坏（存在性拒面）", ["h1758000000000_1a2b", "h1999999999999_zz"]),
    ("空列表（声明无依赖）", []),
)


# 生效条件：无入参——惰性建**跨变异轮存活**的对照池（不登记 _TMP_ROOTS：登记了会被
# 每轮 _cleanup 删掉，python 侧的 accept 面夹具随之消失 ⇒ 假红），池内预建合法 id 的
# 目录与「同名文件」夹具；返回 (jobs, tmp)。
def _parity_pool():
    if _PARITY["jobs"] is None:
        tmp = tempfile.mkdtemp(prefix="h6_parity_")
        _PERSIST_ROOTS.append(tmp)
        jobs = os.path.join(tmp, "jobs")
        os.makedirs(jobs)
        for name in ("h1758000000000_1a2b", "h1_a", "h"):
            os.makedirs(os.path.join(jobs, name))
        with open(os.path.join(jobs, "h_notadir_x"), "w", encoding="utf-8") as f:
            f.write("x")
        _PARITY.update({"jobs": jobs, "tmp": tmp})
    return _PARITY["jobs"], _PARITY["tmp"]


# 生效条件：jobs/tmp 与 depends_on 裸值给定——写 spec 并跑 `hive.exe submit
# --jobs <池>`，把 stdout JSON 归成四类之一：ok=true→"accept"；error 含「项非法」→
# "fmt_reject"；含「依赖不完整」→"exist_reject"；其余/解析失败→"other:…"。
def _rust_class(jobs: str, tmp: str, deps) -> str:
    p = _write_spec(os.path.join(tmp, "spec"), {
        "model": "guard-model", "user_prompt": "h6 parity", "timeout_s": 60,
        "depends_on": deps})
    r = subprocess.run([HIVE_EXE, "submit", "--spec", p, "--jobs", jobs],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60, cwd=_REPO)
    try:
        doc = json.loads((r.stdout or "").strip())
    except ValueError:
        return "other:" + ((r.stdout or "") + (r.stderr or ""))[:120]
    if not isinstance(doc, dict):
        return "other:non-object"
    if doc.get("ok"):
        return "accept"
    err = doc.get("error") or ""
    if "项非法" in err:
        return "fmt_reject"
    if "依赖不完整" in err:
        return "exist_reject"
    return "other:" + err[:120]


# 生效条件：jobs 与 depends_on 裸值给定——在隔离形态下走 MCP 面 _t_spawn，按与
# _rust_class 同一套文案归类；_t_spawn 抛异常（如闸门被变异后裸拼非 str 元素）归成
# "error:<类型>"（判红而非崩组）。
def _py_class(jobs: str, deps) -> str:
    try:
        r = _spawn_safe(jobs, {"model": "guard-model", "user_prompt": "h6 parity",
                             "timeout_s": 60, "depends_on": deps})
    except Exception as exc:              # noqa: BLE001 —— 变异态正是抛异常
        return "error:" + type(exc).__name__
    if r.get("ok"):
        return "accept"
    err = r.get("error") or ""
    if "项非法" in err:
        return "fmt_reject"
    if "依赖不完整" in err:
        return "exist_reject"
    if "列表" in err:
        return "type_reject"
    return "other:" + err[:120]


# 生效条件：跑 D 组 21 条断言——20 条逐项对照（同一批 depends_on 取值在 rust
# `spec::validate`（+ main.rs 存在性）与 python `_dep_gate` 上分类必须相等；
# rust 侧结果按进程缓存，rust 代码不参与变异故跨轮稳定），另 1 条钉 python 侧分类
# 分布非退化（accept/fmt_reject/exist_reject 三态都真实出现过）。
def g_d():
    begin("D")
    jobs, tmp = _parity_pool()
    py_cls = {}
    for i, (label, deps) in enumerate(_PARITY_CASES):
        key = "%d:%s" % (i, json.dumps(deps, ensure_ascii=False))
        if key not in _RUST_CACHE:
            _RUST_CACHE[key] = _rust_class(jobs, tmp, deps)
        rust = _RUST_CACHE[key]
        try:
            py = _py_class(jobs, deps)
        except Exception as exc:          # noqa: BLE001
            py = "error:" + type(exc).__name__
        py_cls[label] = py
        check("D%d·两侧逐项一致 %s" % (i + 1, label),
              rust == py, "rust=%r python=%r deps=%r" % (rust, py, deps))
    dist = set(py_cls.values())
    check_fn("D21·python 侧分类分布非退化（accept/fmt_reject/exist_reject 三态皆现）",
             lambda: {"accept", "fmt_reject", "exist_reject"} <= dist,
             "python 分类=%s" % json.dumps(py_cls, ensure_ascii=False)[:400])


# ----------------------------------------------------------- H/I 组：orch 面透传

# 生效条件：jobs 给定——把 _CFG 就位（job_dir 取**池内**的编排者任务目录，与 serve
# 拉起 orch 的真实形态一致：N145 的 _resolve_jobs_dir 双键皆空时以 job_dir 父目录推导
# 真实池，故 job_dir 必须在池内，否则推导出的池不是本夹具的临时池）、桩掉 _hm._submit
# 捕获子 spec（不落盘、不触 serve），返回 (响应, 捕获到的子 spec)；任何异常（含隔离面
# 失守）归成 ok=False 的响应（不崩组）。
def _orch_spawn(jobs: str, args: dict):
    box = {}
    try:
        with mock.patch.dict(os.environ, {"HIVE_JOBS_DIR": jobs}):
            return _orch_spawn_inner(jobs, args, box)
    except Exception as exc:              # noqa: BLE001 —— 隔离失守/变异态都按红
        return {"ok": False, "error": "raise:%s: %s" % (type(exc).__name__, exc)}, {}


# 生效条件：jobs/args/box 给定——_orch_spawn 的内层：_CFG 就位 + _assert_isolated +
# 三处打桩（_jobs_dir / _resolve_jobs_dir / _hm._submit），返回 (响应, 捕获的子 spec)。
def _orch_spawn_inner(jobs: str, args: dict, box: dict):
    job_dir = os.path.join(jobs, "h_orch_guard")
    os.makedirs(job_dir, exist_ok=True)
    _orch._CFG.update({"job_id": "h_orch_guard", "job_dir": job_dir, "jobs": jobs,
                       "model": "guard-model", "children": []})

    def _fake_submit(j, sub):
        box["sub"] = dict(sub)
        return "h_orch_child_1"

    with mock.patch.object(_hm, "_jobs_dir", lambda: jobs), \
            mock.patch.object(_orch, "_resolve_jobs_dir", lambda *a, **k: jobs), \
            mock.patch.object(_orch._hm, "_submit", side_effect=_fake_submit):
        _assert_isolated(jobs)
        r = _orch._spawn(args)
    return r, box.get("sub") or {}


# 生效条件：跑 H 组 1 条断言——orch._spawn 把显式 depends_on 透传进子 spec（值逐项
# 一致）；依赖 id 在临时池中真实存在（故过闸）。
def g_h():
    begin("H")
    jobs = os.path.join(_tmpdir("h6_orch_"), "jobs")
    os.makedirs(jobs)
    dep = "h1700000000002_up"
    os.makedirs(os.path.join(jobs, dep))
    r, sub = _orch_spawn(jobs, {"user_prompt": "p", "model": "guard-model",
                                "depends_on": [dep]})
    check("H1·orch._spawn 透传 depends_on 进子 spec",
          r.get("ok") is True and sub.get("depends_on") == [dep],
          "ok=%r sub_depends_on=%r resp=%s" % (
              r.get("ok"), sub.get("depends_on"),
              json.dumps(r, ensure_ascii=False)[:160]))


# 生效条件：跑 I 组 1 条断言——orch._spawn 缺省（不传 depends_on）时子 spec 不含该键
# （显式传值优先、缺省不写）。
def g_i():
    begin("I")
    jobs = os.path.join(_tmpdir("h6_orch2_"), "jobs")
    os.makedirs(jobs)
    r, sub = _orch_spawn(jobs, {"user_prompt": "p", "model": "guard-model"})
    check("I1·orch._spawn 缺省不写 depends_on",
          r.get("ok") is True and "depends_on" not in sub,
          "ok=%r sub_keys=%s" % (r.get("ok"), sorted(sub.keys())))


_GROUPS = (("A", g_a), ("B", g_b), ("C", g_c), ("D", g_d), ("E", g_e),
           ("E2", g_e2), ("F", g_f), ("G", g_g), ("H", g_h), ("I", g_i))


# 生效条件：重算计数器后依次跑 A–I 十组（静默与否由 print 决定），返回
# (总失败数, {组名: 失败数} 的副本)；供正常模式与 --branch-baseline 的变异核验共用。
def _run_groups():
    _reset_counters()
    for _name, fn in _GROUPS:
        fn()
    return FAIL, dict(_GROUP_FAILS)


# ---------------- 定点变异自证（--branch-baseline） ----------------
# 变异表：逐处关掉一个判据，守卫**必须转红**，且红项**恰好**落在该判据负责的组、
# 数量等于下表声明值（多一项少一项都报红）。基线源 = **工作区源码**
# （inspect.getsource 取自当前已加载模块），绝不绑 git HEAD。
_MUTATIONS = (
    ("MCP 面 depends_on 落盘（_t_spawn 写入分支）",
     "mcp", "_t_spawn",
     'if a.get("depends_on") is not None:',
     'if False:',
     {"A": 4}),
    ("MCP 面格式闸（_dep_gate 的 _valid_job_id 结构判据）",
     "mcp", "_dep_gate",
     "if not _valid_job_id(d):",
     "if False:",
     {"B": 10, "D": 14, "E": 1}),
    ("MCP 面存在性闸（_dep_gate 的 jobs/<dep> 是目录判据）",
     "mcp", "_dep_gate",
     "if not os.path.isdir(os.path.join(jobs, d)):",
     "if False:",
     {"C": 2, "D": 4, "E2": 1}),
    ("MCP 面 depends_on 类型闸（_dep_gate 非列表即拒）",
     "mcp", "_dep_gate",
     "if not isinstance(deps, list):",
     "if False:",
     {"G": 1}),
    ("「缺省即无依赖」分支（_dep_gate 的 deps is None → 不校验不写）",
     "mcp", "_dep_gate",
     "    if deps is None:\n        return None",
     '    if deps is None:\n        return "depends_on 必须是字符串列表"',
     # A 组同红是**真实耦合**（非噪声）：A 的夹具要提交一条**不带 depends_on 的
     # 根任务**当依赖源（真实用法：根任务通常不带该键）——None 分支一旦变成拒绝，
     # 根任务提交即失败、A 组四条断言连锁转红。F/I 才是本判据的本职组。
     {"A": 4, "F": 1, "I": 1}),
    ("orch 面白名单透传（_spawn 的 sub 键清单含 depends_on）",
     "orch", "_spawn",
     '"temperature", "thinking", "depends_on"):',
     '"temperature", "thinking"):',
     {"H": 1}),
)

_HOLDERS = {"mcp": _hm, "orch": _orch}
_MUTATION = [None]


# 生效条件：which 为 "mcp"/"orch" 时取 _HOLDERS[which] 里 func_name 的源码文本——
# **从 `def <name>(` 行起截断再 dedent**（本仓排版为「顶格 `# 生效条件：` 注释 +
# def」，inspect.getsource 可能把注释一并带来，直接 dedent 会因公共前缀为 0 而留缩进）；
# 函数缺失或无法取源时返回 None（调用方按锚点漂移处置）。
def _func_src(which: str, func_name: str):
    try:
        src = inspect.getsource(_HOLDERS[which].__dict__[func_name])
        return textwrap.dedent(src[src.index("def %s(" % func_name):])
    except Exception:                     # noqa: BLE001 —— 取源失败按锚点漂移处理
        return None


# 生效条件：which/func_name 对应的源码含 old 时，替换后 exec 进该模块命名空间并挂回
# 模块属性，返回还原回调；old 不在源码中返回 None（调用方按 ANCHOR-MISS 处置）。
def _patch(which: str, func_name: str, old: str, new: str):
    src = _func_src(which, func_name)
    if src is None or old not in src:
        return None
    mod = _HOLDERS[which]
    orig = mod.__dict__[func_name]
    # **exec 进模块 __dict__ 本身**（而非 vars(mod) 的快照副本）：变异函数的
    # globals 因此仍是活模块命名空间，守卫随后的 mock.patch.object（_jobs_dir /
    # _ensure_serve / _dep_gate …）照旧生效——首版用快照副本时变异轮绕开了打桩，
    # 提交落进在役 jobs 池（2026-09-29 实测缺陷，已由此修 + _assert_isolated 双保险）。
    exec(compile(src.replace(old, new), "h6_mut.py", "exec"), mod.__dict__)

    def _restore():
        mod.__dict__[func_name] = orig

    return _restore


# 生效条件：无入参——跑定点变异自证：先跑未变异基线（必须零失败），再逐个应用
# _MUTATIONS：锚点缺失立即打印 ANCHOR-MISS 并返回 2（fail-closed，不再继续）；变异后
# 红项组与数量必须与声明完全一致，否则计入 bad；全部通过返回 0，存在不符返回 1。
def _branch_baseline() -> int:
    print("!! 定点变异模式：逐处关掉判据，守卫应当转红且**恰好**命中预期组/项数\n")
    with contextlib.redirect_stdout(io.StringIO()):
        clean_fail, _clean_groups = _run_groups()
    _cleanup()
    print("  未变异基线：失败=%d" % clean_fail)
    if clean_fail:
        print("  基线即失败 → 定点变异自证无意义（先修基线）")
        _cleanup_persist()
        return 1
    bad = []
    for label, which, fname, old, new, expect in _MUTATIONS:
        restore = _patch(which, fname, old, new)
        if restore is None:
            print("  ANCHOR-MISS %s —— 变异锚点漂移（实现改了却没同步本表；"
                  "基线源=%s.%s）" % (label, which, fname))
            _cleanup_persist()
            return 2                      # fail-closed：锚点漂移不静默失效
        _MUTATION[0] = {"which": which, "func": fname, "old": old, "new": new}
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                got_fail, got_groups = _run_groups()
        finally:
            _MUTATION[0] = None
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
            bad.append(label)
    print("\n定点变异自证：%s" % ("PASS（每处判据都有断言把它钉死）"
                                  if not bad else "FAIL —— " + "、".join(bad)))
    _cleanup_persist()
    return 0 if not bad else 1


# 生效条件：命令行含 --branch-baseline 时走定点变异自证（退出码 0/1/2）；否则依次跑
# A–I 十组打印逐条结果与汇总，全部通过返回 0、存在失败返回 1。
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
    print("\n" + "=" * 64)
    print("H-6 依赖门禁守卫（MCP 面 / orch 面）：%d 通过，%d 失败" % (PASS, FAIL))
    if FAILS:
        for f in FAILS:
            print("  - %s" % f)
    _cleanup_persist()
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
