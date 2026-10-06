# -*- coding: utf-8 -*-
"""常驻循环卡死防护与观测守卫（issue #63）。

背景（外部 issue #63 三条根因，全部本文件钉死）：

  ① `sleep._git()` **无 timeout=**——子进程无界等待（实测停 9.5 小时）；
  ② 同处**未指定 stdin** ⇒ 子进程继承父进程 stdin（DSH 常驻宿主的
     JSON-RPC 活管道）——活管道下读 stdin 的子进程永不 EOF；
  ③ tick 台账在 `run_cycle` **返回后**才写 ⇒ 卡住期间外部无法知道卡在哪档
     （`phases` 空）。

修法的可判据面：

  T1 参数面——`sleep._git` 调 `subprocess.run` 必带
     `timeout=_GIT_TIMEOUT_S` 与 `stdin=subprocess.DEVNULL`（捕获 kwargs 判据）；
     旁证（机理复现，等价形态）：活管道（PIPE 不写不关）下读 stdin 的子进程
     悬挂；DEVNULL 下 0.02s 级立即 EOF 返回。旁证二：真挂起子进程 + 同形态
     timeout → 真 `TimeoutExpired` 且有界（本机 Python 超时机制在位）。
  T2 真超时——替身按 `subprocess.run(timeout=)` 契约行事（跑满一个 timeout
     后抛 `TimeoutExpired`）：`_git_ok` 抛 `SleepError`（`SleepGitTimeout`），
     消息含「超时」「已被 kill」与命令名，耗时 **≈ timeout（有界）**；
     并钉「可区分」：rc≠0 走「失败」文案、与超时文案分开。
  T3 循环续走回归——某档 tick 抛异常 → `_run` 不中断（该档下一轮照常，
     其它档不受影响）——既有能力回归。
  T4 进度面——tick 入口写 `current_tick`（且**进入即刷既有心跳戳**）/ 出口清
     并记 `last_tick_done`；失败档记 `last_tick_error`（容忍≠静默）；`status`
     展示三字段；构造过期 `current_tick` → `status` 报 `stale_tick`
     （含档名与已运行时长；负对照：未超不报）。
  T5 审计断言——interop / audit / units / bench×3 / sleep 的 `subprocess.run`
     调用（AST 参数面）带 timeout 与 `stdin=DEVNULL`；whitebox 的 Popen
     保持协议面原形态（stdin=PIPE，**不在加固面**）。

运行：python -X utf8 -m md_cg.test_sustain_bounded
      python -X utf8 -m md_cg.test_sustain_bounded --mutate        # 变异自证
      python -X utf8 -m md_cg.test_sustain_bounded --mutate --list  # 只列变异表
      python -X utf8 -m md_cg.test_sustain_bounded --mutate --null  # 空转检出对照

退出码（fail-closed）：0 = 全绿；1 = 有断言失败 / 变异未按预期转红；
2 = ANCHOR-MISS（变异锚点在当前源码里找不到——实现改了却没同步本表）。

**红项口径（复核打回修复，2026-10-06）**：每条变异的「自身红项」= 该条运行
前后 `_FAIL` 长度差——**不得**拿 `len(_FAIL)` 当本轮红项（累计值恒非空，
会让「判据空转」检测失效、空转变异被静默放行）；红项行**全量**打印且与
自身红项数**账实相符**（不符按失败判）。该缺陷类别由 `--mutate --null`
（new==old 的无害变异必须被判 MISS）钉住。

**基线纪律**：不以 git HEAD 为基线源——「改动前形态」由在当前工作区源码上做
**定点文本变异**（`_MUTATIONS`）复现，锚点漂移即退出码 2。
"""
from __future__ import annotations

import ast
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types

from . import sleep as SL
from . import sustain as SUS

_PASS = []
_FAIL = []
_SRC = {}
_TMP = tempfile.mkdtemp(prefix="mdcg_bounded_")
_SAVED = {}
_REAL_SL = SL
_REAL_SUS = SUS

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: T5 的审计面：这些文件里的 `subprocess.run` 调用必须带 timeout 与
#: stdin=DEVNULL（issue #63 同批加固）；whitebox 的 Popen 单列（不在加固面）。
_AUDIT_RUN_FILES = ("md_cg/sleep.py", "md_cg/interop.py", "md_cg/audit.py",
                    "md_cg/units.py", "md_cg/bench_locomo_zh.py",
                    "md_cg/bench_zh_mad.py", "md_cg/bench_governance.py")
#: 不在加固面的既有正确形态（免误伤）：whitebox 的 Popen 是**长驻对话协议面**
#: （stdin=PIPE 与后端持续对话，给 DEVNULL 会改变协议语义）。
_WHITEBOX_REL = "md_cg/whitebox.py"


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


def _rel_text(rel: str) -> str:
    if rel in _SRC:
        return _SRC[rel]
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


def _sandbox_env():
    for k in ("MDCG_ROOT", "MDCG_AUX_ROOT", "MDCG_STATE_ROOT",
              "MDCG_SUSTAIN_DIR", "MDCG_SUSTAIN", "MDCG_SLEEP_GITDIR",
              "MDCG_SLEEP_SHADOW"):
        _SAVED[k] = os.environ.get(k)
        os.environ.pop(k, None)
    os.environ["MDCG_SUSTAIN_DIR"] = os.path.join(_TMP, "sustain")
    os.environ["MDCG_ROOT"] = os.path.join(_TMP, "data")


def _restore_env():
    for k, v in _SAVED.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


class _FakeCG:
    """最小 cg 替身：SustainLoop 只消费 .root（写戳 / 会话账本读点）。"""

    def __init__(self, root):
        self.root = root


def _new_loop(**kw):
    root = os.path.join(_TMP, "data")
    os.makedirs(root, exist_ok=True)
    d = os.path.join(_TMP, "sustain")
    os.makedirs(d, exist_ok=True)
    kw.setdefault("name", "md_cg_bounded")
    kw.setdefault("auto_sleep", True)
    kw.setdefault("sleep_merge", "auto")
    kw.setdefault("sleep_window", "")
    kw.setdefault("sleep_scrub_apply", False)
    return SUS.SustainLoop(_FakeCG(root), d=d, **kw)


# ---------------------------------------------------------------- T1
def t1():
    print("== T1 参数面：_git 必带 timeout=_GIT_TIMEOUT_S 与 stdin=DEVNULL ==")
    S = globals()["SL"]
    real_run = subprocess.run
    calls = []

    def fake(argv, **kw):
        calls.append((list(argv), dict(kw)))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    subprocess.run = fake
    try:
        S._git("<G>", "<root>", "status", "--short")
    finally:
        subprocess.run = real_run
    ok(len(calls) == 1, "T1 前置：_git 恰调 subprocess.run 一次", calls)
    if calls:
        argv, kw = calls[0]
        # 回显面**剔除 env**（含本机敏感变量，纪律第 9 条：敏感信息隔离）
        safe = {k: v for k, v in kw.items() if k != "env"}
        ok(argv[:3] == ["git", "--git-dir=<G>", "--work-tree=<root>"],
           "T1a  argv 显式 --git-dir / --work-tree（唯一出口形态不变）", argv)
        ok(kw.get("timeout") == S._GIT_TIMEOUT_S
           and isinstance(kw.get("timeout"), (int, float)),
           "T1b  **_git 必带 timeout=_GIT_TIMEOUT_S**（%r）——无界等待被闸住"
           % (kw.get("timeout"),), safe)
        ok(kw.get("stdin") is subprocess.DEVNULL,
           "T1c  **_git 必带 stdin=subprocess.DEVNULL**——不继承父进程 stdin"
           "（常驻宿主下是 JSON-RPC 活管道）", safe)
        ok(kw.get("shell") is False and kw.get("capture_output") is True,
           "T1d  既有形态保持（shell=False + capture_output=True）", safe)
        ok((kw.get("env") or {}).get("PYTHONUTF8") == "1",
           "T1e  env 带 PYTHONUTF8=1（既有形态保持；不回显 env 内容）")

    # 机理旁证（等价形态）：活管道 ⇒ 读 stdin 的子进程悬挂；DEVNULL ⇒ 立即 EOF
    code = "import sys\nsys.stdin.read()\nprint('EOF-OK')\n"
    p = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", errors="replace")
    try:
        time.sleep(0.6)
        hung = p.poll() is None
    finally:
        p.kill()
        with contextlib.suppress(Exception):
            p.communicate(timeout=5)
    ok(hung, "T1f  机理旁证：**活管道**（PIPE 不写不关）下读 stdin 的子进程"
             "悬挂（poll=None；DSH JSON-RPC 管道的等价形态）")
    t0 = time.time()
    r = subprocess.run([sys.executable, "-c", code], stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=15)
    dt = time.time() - t0
    ok(r.returncode == 0 and "EOF-OK" in (r.stdout or ""),
       "T1g  机理旁证：**stdin=DEVNULL** 下同一子进程立即 EOF 返回"
       "（%.2fs）" % dt, (r.returncode, r.stdout, r.stderr))
    t0 = time.time()
    timed_out = False
    try:
        subprocess.run([sys.executable, "-c", "import time; time.sleep(30)"],
                       stdin=subprocess.DEVNULL, capture_output=True,
                       timeout=0.5)
    except subprocess.TimeoutExpired:
        timed_out = True
    dt = time.time() - t0
    ok(timed_out and dt < 5.0,
       "T1h  机理旁证：真子进程 + timeout → 真 TimeoutExpired 且有界"
       "（%.2fs）——本机 timeout 机制在位" % dt)


# ---------------------------------------------------------------- T2
def t2():
    print("== T2 真超时：SleepError + 耗时≈timeout（有界）+ 消息含「超时」 ==")
    S = globals()["SL"]
    g = S._git.__globals__
    real_run = subprocess.run
    real_tmo = g["_GIT_TIMEOUT_S"]
    calls = []

    def fake(argv, **kw):
        """按 `subprocess.run(timeout=)` 契约行事：跑满一个 timeout 后 kill 抛出。

        无 timeout（旧形态）⇒ 跑满 2s 才返回（无界等待的等价模拟——T1b/T2a
        会在该形态下转红）。
        """
        calls.append((list(argv), dict(kw)))
        tmo = kw.get("timeout")
        if tmo is None:
            time.sleep(2.0)
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        time.sleep(float(tmo))
        raise subprocess.TimeoutExpired(cmd=argv, timeout=float(tmo))

    g["_GIT_TIMEOUT_S"] = 0.3                 # 测试用短 timeout（模块单点可调）
    subprocess.run = fake
    t0 = time.time()
    raised = None
    try:
        try:
            S._git_ok("<G>", "<root>", "status")
        except S.SleepError as e:
            raised = e
    finally:
        subprocess.run = real_run
        g["_GIT_TIMEOUT_S"] = real_tmo
    dt = time.time() - t0
    ok(raised is not None and isinstance(raised, S.SleepGitTimeout),
       "T2a  超时**不吞**：_git/_git_ok 抛 SleepError（SleepGitTimeout）", raised)
    ok(raised is not None and "超时" in str(raised),
       "T2b  消息含「超时」", str(raised))
    ok(raised is not None and "已被 kill" in str(raised),
       "T2c  消息含「已被 kill」（kill 语义明示）", str(raised))
    ok(raised is not None and "status" in str(raised),
       "T2d  消息含命令名", str(raised))
    ok(raised is not None and "index.lock" in str(raised),
       "T2e  消息含残留锁人工核删指引（不自动删）", str(raised))
    ok(raised is not None and dt <= 0.3 * 3,
       "T2f  **耗时有界**（≈timeout：%.2fs ≤ 3×0.3s）——不是无界等待" % dt, dt)

    # 可区分（issue #63）：rc≠0 的失败走「失败」文案，与超时面分开
    def fake_fail(argv, **kw):
        return subprocess.CompletedProcess(argv, 1, stdout="",
                                           stderr="fatal: boom")

    subprocess.run = fake_fail
    raised2 = None
    try:
        try:
            S._git_ok("<G>", "<root>", "status")
        except S.SleepError as e2:
            raised2 = e2
    finally:
        subprocess.run = real_run
    ok(raised2 is not None and "失败" in str(raised2)
       and "超时" not in str(raised2),
       "T2g  **可区分**：rc≠0 走「失败」文案、不含「超时」（两条失败面分开）",
       str(raised2))


# ---------------------------------------------------------------- T3
def t3():
    print("== T3 循环续走回归：某档抛异常 → _run 不中断（下一轮照常）==")
    lp = _new_loop(beat_interval=30.0, heal_interval=0.15, scrub_interval=0.3,
                   evolve_interval=60.0, tidy_interval=60.0,
                   sleep_interval=60.0)
    log = []

    def bad():
        log.append(("heal", time.time()))
        raise RuntimeError("t3-fail-once")

    def good():
        log.append(("scrub", time.time()))

    lp._tick_heal = bad
    lp._tick_scrub = good
    lp._tick_evolve = lambda: log.append(("evolve", time.time()))
    lp._tick_tidy = lambda: log.append(("tidy", time.time()))
    lp._tick_sleep = lambda: log.append(("sleep", time.time()))
    lp.start()
    try:
        time.sleep(1.1)
    finally:
        lp.stop()
    n_heal = sum(1 for t, _ in log if t == "heal")
    n_scrub = sum(1 for t, _ in log if t == "scrub")
    ok(n_heal >= 2,
       "T3a  某档 tick 抛异常后**不中断**：该档下一轮照常调度（heal×%d）"
       % n_heal, log)
    ok(n_scrub >= 1,
       "T3b  其它档不受影响（scrub×%d）" % n_scrub, log)
    ok(lp.last_tick_error is not None
       and lp.last_tick_error.get("name") == "heal"
       and "RuntimeError: t3-fail-once" in lp.last_tick_error.get("error", ""),
       "T3c  异常**不再全静默**：last_tick_error 记 {档名, 类名+摘要}",
       lp.last_tick_error)
    ok(lp.last_tick_done is not None and lp.last_tick_done.get("ok") is False,
       "T3d  last_tick_done 记 ok=False（失败档）", lp.last_tick_done)


# ---------------------------------------------------------------- T4
def t4():
    print("== T4 进度面：current_tick / last_tick_done / last_tick_error / "
          "stale_tick ==")
    lp = _new_loop()
    seen = {}

    def fn():
        seen["mem"] = lp.current_tick
        seen["stamp"] = SUS.read_stamp(lp.name, lp.d)

    lp._wrap_tick("scrub", fn)()
    ct = seen.get("mem") or {}
    ok(ct.get("name") == "scrub" and "started_at" in ct
       and ct.get("pid") == os.getpid(),
       "T4a  tick 入口写 current_tick={name, started_at, pid}", ct)
    ok(((seen.get("stamp") or {}).get("current_tick") or {}).get("name")
       == "scrub",
       "T4a2 **进入档即刷既有状态面**（心跳戳里读得到 current_tick——"
       "卡住场景下也读得到）", seen.get("stamp"))
    ok(lp.current_tick is None,
       "T4b  tick 出口清 current_tick", lp.current_tick)
    ok(lp.last_tick_done is not None
       and lp.last_tick_done.get("name") == "scrub"
       and lp.last_tick_done.get("ok") is True
       and "t" in lp.last_tick_done,
       "T4b2 tick 出口记 last_tick_done={name, t, ok}", lp.last_tick_done)

    lp._wrap_tick("heal", lambda: (_ for _ in ()).throw(ValueError("t4-e")))()
    ok(lp.last_tick_error is not None
       and lp.last_tick_error.get("name") == "heal"
       and "ValueError: t4-e" in lp.last_tick_error.get("error", ""),
       "T4c  失败档记 last_tick_error（类名+摘要）", lp.last_tick_error)
    ok(lp.last_tick_done is not None and lp.last_tick_done.get("ok") is False,
       "T4c2 失败档 last_tick_done.ok=False", lp.last_tick_done)

    st = lp.status()
    ok("current_tick" in st and "last_tick_done" in st
       and "last_tick_error" in st,
       "T4d  status 输出含进度三字段（cg(op=sustain,action=status) 同源）",
       sorted(st))
    ok(st["last_tick_done"]["name"] == "heal"
       and st["last_tick_done"]["ok"] is False,
       "T4d2 status 的 last_tick_done 反映最近一档（失败态可见）", st["last_tick_done"])

    lp.current_tick = {"name": "sleep", "started_at": time.time() - 9000.0,
                       "pid": os.getpid()}
    st2 = lp.status()
    ok(bool(st2["stale_tick"]) and st2["stale_tick"].get("tick") == "sleep",
       "T4e  过期 current_tick → status 报 stale_tick（档名=sleep）",
       st2["stale_tick"])
    ok(bool(st2["stale_tick"])
       and "sleep" in st2["stale_tick"].get("alert", "")
       and "9000" in st2["stale_tick"].get("alert", ""),
       "T4e2 stale_tick.alert 含档名与已运行时长", st2["stale_tick"])
    ok(st2["current_tick"].get("running_s") >= 9000,
       "T4e3 current_tick 附已运行秒数 running_s", st2["current_tick"])
    lp.current_tick = {"name": "sleep", "started_at": time.time() - 10.0,
                       "pid": os.getpid()}
    ok(lp.status()["stale_tick"] is None,
       "T4f  负对照：未超阈值不报 stale_tick（不误报）")
    # 跨进程回落：内存清空后仍能从既有状态面读到（写点是戳，不是内存独有）
    lp.last_tick_done = None
    st3 = lp.status()
    ok(st3["last_tick_done"] is not None,
       "T4g  跨进程回落：内存清空后 last_tick_done 仍可从戳读到",
       st3["last_tick_done"])


# ---------------------------------------------------------------- T5
def t5():
    print("== T5 审计断言：加固面 subprocess.run 带 timeout+DEVNULL；"
          "whitebox Popen 保持协议面 ==")

    def run_calls(rel):
        tree = ast.parse(_rel_text(rel))
        out = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "run"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "subprocess"):
                out.append(node)
        return out

    def has_kw(node, key, devnull=False):
        for kw in node.keywords:
            if kw.arg != key:
                continue
            if not devnull:
                return True
            v = kw.value
            return (isinstance(v, ast.Attribute) and v.attr == "DEVNULL"
                    and isinstance(v.value, ast.Name)
                    and v.value.id == "subprocess")
        return False

    for rel in _AUDIT_RUN_FILES:
        nodes = run_calls(rel)
        ok(len(nodes) >= 1, "T5 前置：%s 内有 subprocess.run 调用（%d 处）"
           % (rel, len(nodes)))
        for i, node in enumerate(nodes, 1):
            ok(has_kw(node, "timeout"),
               "T5a %s:%d subprocess.run 带 timeout=" % (rel, node.lineno))
            ok(has_kw(node, "stdin", devnull=True),
               "T5b %s:%d subprocess.run 带 stdin=subprocess.DEVNULL"
               % (rel, node.lineno))

    # whitebox：长驻对话协议面（stdin=PIPE）——**不在加固面**，保持原形态
    tree = ast.parse(_rel_text(_WHITEBOX_REL))
    popens = [n for n in ast.walk(tree)
              if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute)
              and n.func.attr == "Popen"
              and isinstance(n.func.value, ast.Name)
              and n.func.value.id == "subprocess"]
    ok(len(popens) >= 1, "T5c 前置：whitebox.py 内有 subprocess.Popen（%d 处）"
       % len(popens))
    for node in popens:
        stdin_kw = next((kw for kw in node.keywords if kw.arg == "stdin"), None)
        ok(stdin_kw is not None
           and isinstance(stdin_kw.value, ast.Attribute)
           and stdin_kw.value.attr == "PIPE",
           "T5d whitebox Popen 保持协议面原形态（stdin=PIPE，不加固）"
           "（%s:%d）" % (_WHITEBOX_REL, node.lineno))


# ---------------------------------------------------------------- 变异表
# 锚点 = (名字, rel, old, new)。每次变异必须让套件**转红**：
#   M1 主修删 timeout=（_git 退回无界等待）→ T1b / T2a 红
#   M2 主修删 stdin=DEVNULL（子进程继承活管道 stdin）→ T1c 红
#   M3 进度面删「进入写点」→ T4a / T4a2 红
#   M4 六档 except 删 last_tick_error 记录（退回全静默）→ T3c / T4c 红
_MUTATIONS = (
    ("删 timeout=（_git 退回无界等待）", "md_cg/sleep.py",
     "                              env=env, shell=False,\n"
     "                              timeout=_GIT_TIMEOUT_S,\n"
     "                              stdin=subprocess.DEVNULL)",
     "                              env=env, shell=False,\n"
     "                              stdin=subprocess.DEVNULL)"),
    ("删 stdin=DEVNULL（继承活管道 stdin）", "md_cg/sleep.py",
     "                              env=env, shell=False,\n"
     "                              timeout=_GIT_TIMEOUT_S,\n"
     "                              stdin=subprocess.DEVNULL)",
     "                              env=env, shell=False,\n"
     "                              timeout=_GIT_TIMEOUT_S)"),
    ("删进度面进入写点（卡住读不到档）", "md_cg/sustain.py",
     '            self.current_tick = {"name": name, "started_at": time.time(),\n'
     '                                 "pid": os.getpid()}\n'
     '            self._flush_progress()\n',
     ""),
    ("删失败档 last_tick_error（退回全静默）", "md_cg/sustain.py",
     "            except Exception as e:                   # noqa: BLE001\n"
     "                ok_ = False\n"
     "                self.last_tick_error = {\"name\": name, \"t\": time.time(),\n"
     "                                        \"error\": \"%s: %s\" % (type(e).__name__,\n"
     "                                                             str(e)[:200])}\n",
     "            except Exception:                        # noqa: BLE001\n"
     "                ok_ = False\n"),
)

#: 空转检出对照（meta 自证，`--mutate --null`）：new==old 的「无害变异」——
#: 行为零变化、自身红项必须为 0 且被判 MISS。若哪天「本轮红项」判定口径
#: 退化为累计计数（累计恒非空），本对照立即转 FAIL（钉住的正是复核打回
#: 实证过的那条假阳性通道）。锚点取 `_git` 调用里一行行为零变化的文本。
_NULL_MUTATION = ("空转对照（new==old，行为零变化）", "md_cg/sleep.py",
                  "                              env=env, shell=False,\n",
                  "                              env=env, shell=False,\n")


def _exec_module(name: str, rel: str, text: str):
    ns = {"__name__": name, "__package__": "md_cg",
          "__file__": os.path.join(_REPO, rel)}
    exec(compile(text, rel, "exec"), ns)               # noqa: S102 —— 基线自证用
    m = types.ModuleType(name)
    m.__dict__.update(ns)
    return m


def _run_groups() -> int:
    for fn in (t1, t2, t3, t4, t5):
        try:
            fn()
        except Exception as e:                         # noqa: BLE001
            ok(False, "%s 组抛异常：%s: %s" % (fn.__name__, type(e).__name__, e))
    return len(_FAIL)


def _mutate_once(name: str, rel: str, old: str, new: str):
    """跑一条变异并返回**本轮自身**读数 (reds_self, reds_lines, detail)。

    红项口径（复核打回修复，2026-10-06）：`_FAIL` 是**全局累计**列表，
    故「本轮红项」必须取**调用前后长度差**——直接拿 `len(_FAIL)` 当本轮
    红项会让「判据空转」检测失效（累计值恒非空 ⇒ 空转变异也会被记成
    「红」并放行）。本轮自身红项还须与输出里 FAIL 行数**账实相符**。
    """
    src = _rel_text(rel)
    if old not in src:
        return None, [], "ANCHOR-MISS：锚点在 %s 源码里找不到（实现改了却没同步" \
                         "本表）" % rel
    base = len(_FAIL)                        # 本轮起点：只数本轮自身的红项
    _SRC[rel] = src.replace(old, new, 1)
    try:
        mut = _exec_module("md_cg._bounded_mut", rel, _SRC[rel])
        if rel == "md_cg/sleep.py":
            globals()["SL"] = mut
        else:
            globals()["SUS"] = mut
        with contextlib.redirect_stdout(buf := io.StringIO()):
            _run_groups()
        detail = buf.getvalue()
    finally:
        globals()["SL"] = _REAL_SL
        globals()["SUS"] = _REAL_SUS
        _SRC.pop(rel, None)
    reds = len(_FAIL) - base                 # **本轮自身**红项数
    reds_lines = [l for l in detail.splitlines()
                  if l.strip().startswith("FAIL ")]
    return reds, reds_lines, detail


def _mutate_mode(list_only: bool = False) -> int:
    print("!! 定点变异自证：逐条把机制改回「改动前/错误」形态，套件必须转红"
          "（红项 = 本轮自身，非法用全局累计值）\n")
    if list_only:
        for name, rel, _o, _n in _MUTATIONS:
            print("  %-38s [%s]" % (name, rel))
        return 0
    anchor_miss, bad = [], []
    base0 = len(_FAIL)
    with contextlib.redirect_stdout(io.StringIO()):
        _run_groups()
    clean = len(_FAIL) - base0
    print("  未变异基线：失败=%d（必须为 0）" % clean)
    if clean:
        bad.append("未变异基线即失败")

    for name, rel, old, new in _MUTATIONS:
        reds, reds_lines, detail = _mutate_once(name, rel, old, new)
        if reds is None:
            print("  ANCHOR-MISS %s —— %s" % (name, detail))
            anchor_miss.append(name)
            continue
        verdict = "红" if reds else "**仍全绿 = 该判据空转**"
        print("  %s %-38s 自身红项=%d（本轮；基线=%d）  %s"
              % ("OK    " if reds else "MISS  ", name, reds, clean, verdict))
        for l in reds_lines:                 # **全量**打印（回报即读数，不截断）
            print("        " + l.strip()[5:])
        if len(reds_lines) != reds:
            # 账实不符 = 计数面自身有缺陷——按失败判（fail-closed）
            print("        ！账实不符：FAIL 行数=%d ≠ 自身红项=%d——计数面缺陷"
                  % (len(reds_lines), reds))
            bad.append(name + "（账实不符）")
        if not reds:
            bad.append(name)

    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s"
          % ("PASS（每处机制都有一条断言把它钉死）" if not bad
             else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def _null_mode() -> int:
    """空转检出对照（meta 自证）：new==old 的「无害变异」必须被判 MISS。

    钉住的缺陷类别（复核打回实证）：若「本轮红项」误用全局累计值（累计恒
    非空），空转变异会被记成「红」并放行——`--mutate` 的 fail-closed 承诺
    （「变异未按预期转红 = 退出码 1」）随之失效。本对照即钉住该检出能力。
    """
    print("!! 空转检出对照：一条 new==old 的「无害变异」——必须被判 MISS"
          "（不得凭任何累计值蒙混）\n")
    name, rel, old, new = _NULL_MUTATION
    reds, reds_lines, detail = _mutate_once(name, rel, old, new)
    if reds is None:
        print("  ANCHOR-MISS %s —— %s" % (name, detail))
        return 2
    detected = reds == 0 and not reds_lines
    print("  变异=%s 自身红项=%d（本轮） FAIL 行数=%d ⇒ %s"
          % (name, reds, len(reds_lines),
             "MISS（如期检出空转，判定有效）" if detected
             else "红（**空转漏检 = 判据失效**，fail-closed 不成立）"))
    print("空转检出对照：%s" % ("PASS" if detected else "FAIL"))
    return 0 if detected else 1


def main() -> int:
    _sandbox_env()
    try:
        if "--mutate" in sys.argv:
            if "--null" in sys.argv:
                return _null_mode()
            return _mutate_mode("--list" in sys.argv)
        n = _run_groups()
        print("\nSUMMARY: 常驻卡死防护守卫：%d 通过，%d 失败" % (len(_PASS), n))
        return 0 if not n else 1
    finally:
        _restore_env()
        shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
