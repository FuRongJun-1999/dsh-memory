# -*- coding: utf-8 -*-
"""hive serve stop 段树杀守卫（N92：stop 只杀单进程，执行器树成孤儿）。

背景（v10 首报，v15 报告明示「下轮优先/速收候选」，欠账三轮）：stop/restart/
rebuild 的 stop 段（serve_start.py）nt 臂 `taskkill /PID <pid> /F` 无 /T、
unix 臂 `os.kill(pid, 15)` 无 killpg——serve 被杀而其执行器 worker 树成孤儿，
在自身 timeout_s 窗口内持 serve 配置凭据继续外呼，晚落 result 与新 serve 的
recover_orphans 重投并发同 job，形成 state=error + result.ok=true 矛盾终态。
同仓 rust 侧早有先例：hive/src/exec.rs kill_tree 用 `taskkill /PID … /T /F`
（并有 kill_tree_kills_grandchildren 守卫）。killpg 前提在位未用：
start() 以 start_new_session=(os.name != "nt") 拉起（serve 即会话/进程组长）。

修法（最小两处）：nt 臂补 /T（同 exec.rs 形态）；unix 臂
os.killpg(os.getpgid(pid), 15)。

诚实边界：unix 臂的**真实** killpg 群杀行为 win32 本机不可动态验证——本测试
以 mock 接线验证（stop 在 posix 分支确以 killpg(getpgid(pid), 15) 发信）+
源断言（killpg 前提 start_new_session 在位）+ 读码论证落地；全修须 unix 机
实跑验证（ nt 臂端到端哑进程树实验本机可动态验证，[A] 节）。

本测试（哑父子进程树 + 手工心跳 + 补丁 EXE，绝不触真实 serve）：
  [A] 实弹面（nt）：哑父 spawn 哑子，stop() 后父与子**都**须死——旧代码
      子进程存活（孤儿成立）即红
  [B] unix 臂接线（mock os.name/killpg/win 上可跑）：killpg(getpgid(pid),15)
      恰调一次且 ok——旧代码单 pid kill → 红
  [C] 源断言：nt 臂 /T 在位、unix 臂 killpg 在位、killpg 前提
      start_new_session 在位、rust 先例 exec.rs /T /F 未漂移
运行：python -X utf8 -m hive.test_stop_tree_kill   （退出码 0 = 全绿）
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from unittest import mock

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok] {name}")
        return
    FAIL += 1
    print(f"  [FAIL] {name}  {detail}")


def _load(mod_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        mod_name, os.path.join(_HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ss = _load("hive_serve_start_treekill", "serve_start.py")

with open(os.path.join(_HERE, "serve_start.py"), encoding="utf-8") as f:
    SS_PY = f.read()

TMP = tempfile.mkdtemp(prefix="hive_stop_tree_")
real_exe = ss.EXE

PARENT_SRC = (
    "import os, subprocess, sys, time\n"
    "here = os.path.dirname(os.path.abspath(__file__))\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
    "with open(os.path.join(here, 'childpid.txt'), 'w') as f:\n"
    "    f.write(str(child.pid))\n"
    "time.sleep(300)\n"
)
PARENT_PY = os.path.join(TMP, "dummy_parent.py")
with open(PARENT_PY, "w", encoding="utf-8") as f:
    f.write(PARENT_SRC)


def _cleanup_tree(parent_pid: int, child_pid: int | None = None) -> None:
    """守卫自清理：树杀哑进程（不依赖被测代码的行为）。

    注意：父已被被测代码杀掉时 taskkill /T 对死根是 no-op（树杀只认活根）
    ——故须对已记录的子 pid 追加直杀，防哑进程残留。
    """
    if os.name == "nt":
        for pid in (parent_pid, child_pid):
            if not pid:
                continue
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    else:
        try:
            os.killpg(os.getpgid(parent_pid), 15)
        except OSError:
            try:
                os.kill(parent_pid, 15)
            except OSError:
                pass


# ------------------------------------------------------- [A] nt 实弹面（树杀）
print("[A] 实弹（nt）：stop() 后哑父与哑子都必须死（旧代码子存活=孤儿）")
parent = subprocess.Popen([sys.executable, PARENT_PY],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          start_new_session=(os.name != "nt"))
child_pid = None
try:
    for _ in range(50):  # ≤10s 等父进程报出子 pid
        cp = os.path.join(TMP, "childpid.txt")
        if os.path.isfile(cp):
            with open(cp) as f:
                child_pid = int(f.read().strip())
            break
        if parent.poll() is not None:
            break
        time.sleep(0.2)
    check("A0 哑父进程树就位（父活+子 pid 已报）",
          parent.poll() is None and child_pid is not None,
          f"parent.poll()={parent.poll()} child_pid={child_pid}")
    if child_pid is not None:
        ss.EXE = sys.executable  # 身份层放行：映像名=python.exe（test_serve_entry 同法）
        with open(os.path.join(TMP, "_serve.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"pid": parent.pid, "ts": time.time() * 1000}, f)
        res = ss.stop(TMP)
        check("A1 stop ok 且 stopped=True",
              res.get("ok") is True and res.get("stopped") is True,
              f"got {json.dumps(res, ensure_ascii=False)[:200]}")
        # TERM 异步投递（unix killpg）与 /F 同步强杀（win taskkill）语义差：
        # 父进程死亡判定给与 A3 同款宽限轮询；判活必须用 parent.poll()——
        # 哑父是本进程亲儿子，死后僵尸窗口内 os.kill(pid,0) 恒 True（Linux 实测），
        # poll() 即 waitpid 收尸，rc=-15 即死于 SIGTERM，是唯一权威判据
        parent_dead = False
        for _ in range(10):
            if parent.poll() is not None:
                parent_dead = True
                break
            time.sleep(0.5)
        check("A2 父进程已死（单进程杀旧代码即满足）",
              parent_dead,
              f"parent rc={parent.poll()} 在 stop 后宽限期内未退出")
        # 树杀判据：给子进程最多 5s 消失（/T 树杀异步收尾）
        child_dead = False
        for _ in range(10):
            if not ss.pid_alive(child_pid):
                child_dead = True
                break
            time.sleep(0.5)
        check("A3 子进程已死（树杀成立；旧代码无 /T 子存活→孤儿）",
              child_dead, f"child pid={child_pid} 在 stop 后仍存活（孤儿）")
finally:
    ss.EXE = real_exe
    _cleanup_tree(parent.pid, child_pid)

# --------------------------------------- [B] unix 臂接线（mock，win 上可跑）
print("[B] unix 臂接线（mock os.name/killpg；真实群杀行为须 unix 机实跑）")


def _serve_alive_seq():
    """首调判活 True，此后 False（模拟杀后心跳判死）。"""
    state = {"n": 0}

    def _f(*a, **k):
        state["n"] += 1
        return state["n"] == 1
    return _f


DUMMY_PID = 424242  # 哑 pid：kill 已 mock，不发真信号
# win32 的 os 无 getpgid/killpg（POSIX-only）——create=True 打桩只为接线验证
with mock.patch.object(os, "name", "posix"), \
        mock.patch.object(ss, "heartbeat",
                          return_value={"pid": DUMMY_PID, "ts": time.time()}), \
        mock.patch.object(ss, "serve_alive", side_effect=_serve_alive_seq()), \
        mock.patch.object(os, "getpgid", create=True,
                          return_value=DUMMY_PID) as m_gpg, \
        mock.patch.object(os, "killpg", create=True,
                          return_value=None) as m_kpg:
    res = ss.stop("dummy_jobs_unix_arm")
check("B1 unix 臂 ok=True（旧代码 os.kill(424242) 在 win 抛 OSError→失败）",
      res.get("ok") is True,
      f"got {json.dumps(res, ensure_ascii=False)[:200]}")
check("B2 getpgid(哑pid) 恰调一次（先取真进程组再群杀）",
      m_gpg.call_count == 1 and m_gpg.call_args[0][0] == DUMMY_PID,
      f"getpgid calls={m_gpg.call_count} args={m_gpg.call_args}")
check("B3 killpg(getpgid(pid), 15) 恰调一次（旧代码从不调 killpg→红）",
      m_kpg.call_count == 1 and m_kpg.call_args == mock.call(DUMMY_PID, 15),
      f"killpg calls={m_kpg.call_count} args={m_kpg.call_args}")

# ------------------------------------------------------------- [C] 源断言
print("[C] 源断言：/T 与 killpg 在位 + killpg 前提 + rust 先例未漂移")
check("C1 nt 臂 taskkill 含 /T（树杀；exec.rs:68 同形态）",
      '"/PID", str(pid), "/T", "/F"' in SS_PY)
check("C2 unix 臂 killpg(getpgid(pid), 15) 在位",
      "os.killpg(os.getpgid(pid), 15)" in SS_PY)
check("C3 killpg 前提在位：start 以 start_new_session 拉起（serve=进程组长）",
      'start_new_session=(os.name != "nt")' in SS_PY)
try:
    with open(os.path.join(_HERE, "src", "exec.rs"), encoding="utf-8") as f:
        RS = f.read()
    check("C4 rust 先例 kill_tree /T /F 未漂移（同仓口径一致）",
          '"/T", "/F"' in RS, "exec.rs 的 taskkill /T /F 形态丢失")
except OSError as e:
    check("C4 rust 先例可读", False, f"{type(e).__name__}: {e}")

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n结果: {PASS} pass / {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
