# -*- coding: utf-8 -*-
"""互维闭环（P-T-110 最小投影 · #30）验证：双实例心跳互检实证。

断言面：
  ① pid 探活：活进程 True / 死 pid·垃圾值 False（跨平台零依赖）
  ② 戳新鲜 → watch 不动作（ok/warning 不打扰）
  ③ 端到端拉起：对端失联 → 分离子进程拉起 → **验戳新鲜闭合** recovered=True
  ④ 诚实失败：拉起命令执行但对端戳未更新（互维未激活，W4 场景）→
     recovered=False + mutual_peer_unresponsive（不假装成功）
  ⑤ 冷却防风暴：距上次拉起 < cooldown → restart_cooldown（审计即状态）
  ⑥ 无手段诚实上报：无 restart_cmd → dead_unhandled（ok=False）
  ⑦ 误判防护：对端进程存活但戳陈旧 → alive_but_stale 不拉起
  ⑧ 双亡检测：双向失联 → both_dead（外部告警语义）；单侧失联 → 链路可用
  ⑨ 全链路审计：mutual 动作逐条落 _sustain.jsonl

运行：python -m md_cg.test_sustain_mutual
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time

from . import sustain
from .fsutil import append_jsonl
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


def _raw_stamp(d, name, *, ts=None, pid=0, task_running=False):
    """手写心跳戳（pid 可控：0=不存在，os.getpid()=本进程活）。"""
    os.makedirs(d, exist_ok=True)
    rec = {"v": 1, "name": name, "ts": time.time() if ts is None else ts,
           "pid": pid,
           "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "task_running": task_running}
    with open(sustain.stamp_path(name, d), "w", encoding="utf-8") as f:
        json.dump(rec, f)
    return rec


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_mutual_")
    try:
        root = os.path.join(tmp, "root")
        sd = os.path.join(tmp, "sustain")   # 独立心跳目录（不碰 ~/.mdcg）
        os.makedirs(root, exist_ok=True)
        cg = MdCGOS(root)

        # ---------- ① pid 探活 ----------
        ok(sustain.pid_alive(os.getpid()) is True, "①本进程探活 True")
        ok(sustain.pid_alive(0) is False and sustain.pid_alive(-1) is False,
           "①b非法 pid（0/-1）False")
        ok(sustain.pid_alive("garbage") is False and sustain.pid_alive(None) is False,
           "①c垃圾值 False（诚实，不猜测）")

        # ---------- ② 戳新鲜 → 不动作 ----------
        _raw_stamp(sd, "peer_a", ts=time.time())
        r = sustain.mutual_watch(cg, "peer_a", d=sd)
        ok(r["ok"] and r["action"] == "none" and r["state"] == "ok",
           "②对端新鲜 → watch 不动作")

        # ---------- ③ 端到端拉起 + 验戳闭合（真子进程） ----------
        _raw_stamp(sd, "peer_b", ts=time.time() - 99999, pid=0)   # 失联
        writer = ("import json,os,time; d=r'%s'; os.makedirs(d,exist_ok=True);"
                  " json.dump({'v':1,'name':'peer_b','ts':time.time(),"
                  "'pid':os.getpid(),'task_running':False},"
                  " open(os.path.join(d,'heartbeat.peer_b.stamp'),'w'))" % sd)
        r = sustain.mutual_watch(cg, "peer_b", d=sd,
                                 restart_cmd=[sys.executable, "-c", writer],
                                 fresh_timeout=10.0, poll=0.2)
        ok(r["action"] == "restarted" and r["recovered"] is True,
           "③失联 → 拉起子进程 → 验到对端戳变新鲜（recovered=True，W4 闭合）")

        # ---------- ④ 诚实失败：拉起后互维未激活 ----------
        _raw_stamp(sd, "peer_u", ts=time.time() - 99999, pid=0)
        r = sustain.mutual_watch(cg, "peer_u", d=sd,
                                 restart_cmd=[sys.executable, "-c",
                                              "import time; time.sleep(0.05)"],
                                 fresh_timeout=3.0, poll=0.2)
        ok(r["action"] == "restarted" and r["recovered"] is False
           and "unresponsive" in r["note"],
           "④拉起已执行但戳未更新 → recovered=False（不假装成功，W4 显式暴露）")

        # ---------- ⑤ 冷却防风暴 ----------
        _raw_stamp(sd, "peer_c", ts=time.time() - 99999, pid=0)
        append_jsonl(os.path.join(root, sustain.SUSTAIN_LOG),
                     {"t": time.time(), "op": "mutual", "action": "restart",
                      "detail": "peer_c", "pid": os.getpid()})
        r = sustain.mutual_watch(cg, "peer_c", d=sd,
                                 restart_cmd=[sys.executable, "-c", "pass"])
        ok(r["action"] == "restart_cooldown",
           "⑤距上次拉起 < cooldown → 冷却中不重复拉起")

        # ---------- ⑥ 无手段诚实上报 ----------
        _raw_stamp(sd, "peer_d", ts=time.time() - 99999, pid=0)
        r = sustain.mutual_watch(cg, "peer_d", d=sd)
        ok(r["ok"] is False and r["action"] == "dead_unhandled",
           "⑥失联且无 restart_cmd → dead_unhandled（看见但没手段，如实说）")

        # ---------- ⑦ 误判防护：进程活但戳旧 ----------
        _raw_stamp(sd, "peer_e", ts=time.time() - 99999, pid=os.getpid())
        r = sustain.mutual_watch(cg, "peer_e", d=sd,
                                 restart_cmd=[sys.executable, "-c", "pass"])
        ok(r["action"] == "alive_but_stale",
           "⑦pid 仍存活 → 不拉起（长任务未标 task_running？防误杀）")

        # ---------- ⑧ 双亡检测 ----------
        st0 = sustain.mutual_status(cg, "peer_x", d=sd)   # 自己无戳 + 对端无戳
        ok(st0["both_dead"] and st0["ok"] is False
           and "外部告警" in st0["note"],
           "⑧双向失联 → both_dead（互维不可信，外部告警语义）")
        sustain.write_stamp("md_cg", sd)
        st1 = sustain.mutual_status(cg, "peer_x", d=sd)
        ok(st1["self"] == "ok" and not st1["both_dead"] and st1["ok"],
           "⑧b自己存活、对端失联 → 链路可用（可救）")

        # ---------- ⑨ 全链路审计 ----------
        with open(os.path.join(root, sustain.SUSTAIN_LOG),
                  encoding="utf-8") as f:
            recs = [json.loads(x) for x in f if x.strip()]
        mutuals = [r for r in recs if r.get("op") == "mutual"]
        acts = [r["action"] for r in mutuals]
        ok({"restart", "restart_unverified", "dead_unhandled",
            "alive_but_stale"}.issubset(set(acts)),
           f"⑨mutual 动作逐条审计落盘（{acts}）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nmutual: {PASS} passed, {FAIL} failed")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
