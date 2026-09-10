# -*- coding: utf-8 -*-
"""bootstrap_watchdog.py · 自举循环停转检测与守护 v2（2026-09-10 迁移+加固）

背景（v1，2026-09-03）：2026-09-02 发现 tools/bootstrap_loop.py 停转约 17h
无自动恢复（见学习任务 node_4c97142a），故加本守护，供 Windows 计划任务调度。

v2 迁移与加固（2026-09-10，三仓分离后）：
  1. 归属：协议仓 `CommonTrustProtocol/tools/` → **灵枢大脑 `dsh-memory/scripts/`**。
  2. 日志/队列统一落 `<数据根>/bootstrap/`（走 md_cg/datapath.py 解析）。
  3. **修复「假绿」**（v1 在循环已报错时仍报 alive）——v1 只测日志**新鲜度**，
     而循环报错时照样写日志，于是「越出错越 alive」。v2 增加：
       · 内容级判据：末轮 round 是否为错误类；连续错误 ≥ 阈值 → 判定 degraded 并重启。
       · 路径级判据：关键路径（WISDOM / wisdom-book-cloud.db）缺失 → 判定 config_error
         （**不重启**——重启不修复已删目录，只把故障刷成噪声）。
  4. 补上 v1 从未实现的 `--once` 健康语义：`--check-only` 只报告不动作。

检测口径：
  stale      = 末条 ts 距今 > 2×interval（+120s 缓冲）
  degraded   = 新鲜但连续 ≥3 轮为错误类 round
  config_error = 关键路径缺失（需人工介入）
恢复流程：进程卡死(存在但日志陈旧) → 先杀再拉起；进程缺失 → 直接拉起。

用法：
  python scripts/bootstrap_watchdog.py                 # 检测 + 停转自动恢复
  python scripts/bootstrap_watchdog.py --check-only    # 只报告不动作
日志：<数据根>/bootstrap/bootstrap_watchdog.jsonl
"""
from __future__ import annotations

import argparse
import datetime as _dt
import glob
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BRAIN = os.path.dirname(HERE)
WISDOM = os.path.join(BRAIN, "md_cg", "whitebox_kb", "wisdom")
sys.path.append(os.path.join(BRAIN, "md_cg"))

try:
    import datapath as _dp
except Exception:                                   # 兜底
    class _dp:                                      # type: ignore
        @staticmethod
        def data_root() -> str:
            return os.path.join(BRAIN, "data")

STATE = os.path.join(_dp.data_root(), "bootstrap")
os.makedirs(STATE, exist_ok=True)
LOG = os.path.join(STATE, "bootstrap_log.jsonl")
WLOG = os.path.join(STATE, "bootstrap_watchdog.jsonl")
BOOTSTRAP = os.path.join(HERE, "bootstrap_loop.py")
TS_FMT = "%Y-%m-%d %H:%M:%S"
GRACE = 120          # 额外缓冲秒
DEGRADE_LIMIT = 3    # 连续错误轮次阈值

# 健康/降级轮次分类（内容级判据的事实来源）
HEALTHY_ROUNDS = ("bootstrap_v2", "loop_start", "csre_rebuild")
DEGRADED_ROUNDS = ("loop_error", "csre_rebuild_error")


def resolve_python() -> str:
    """选定拉起循环用的解释器。

    优先级：LINGSHU_PYTHON 环境变量 > 当前解释器 > 常见安装位置扫描。
    （v1 硬编码了某台机器的 Python310 绝对路径，换机即失效。）
    """
    env = os.environ.get("LINGSHU_PYTHON")
    if env and os.path.isfile(env):
        return env
    cur = sys.executable or ""
    if cur and "python" in os.path.basename(cur).lower():
        return cur
    la = os.environ.get("LOCALAPPDATA", "")
    for pat in (os.path.join(la, "Programs", "Python", "Python3*", "python.exe"),
                r"C:\Python3*\python.exe"):
        hits = sorted(glob.glob(pat), reverse=True)
        if hits:
            return hits[0]
    return cur or "python"


PY = resolve_python()


def log_watch(evt: dict) -> None:
    evt["ts"] = _dt.datetime.now().strftime(TS_FMT)
    try:
        with open(WLOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_tail(n: int = 6) -> list:
    """读循环日志末 n 条（解析失败的行跳过）。"""
    try:
        with open(LOG, "r", encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
        out = []
        for l in lines[-n:]:
            try:
                out.append(json.loads(l))
            except Exception:
                continue
        return out
    except Exception:
        return []


def last_log_ts() -> tuple[float | None, dict | None]:
    """读循环日志末条记录，返回 (epoch_ts, 原始行 dict)。"""
    tail = read_tail(1)
    if not tail:
        return None, None
    last = tail[-1]
    try:
        ts = _dt.datetime.strptime(last.get("ts", ""), TS_FMT).timestamp()
        return ts, last
    except Exception:
        return None, None


def consecutive_degraded() -> int:
    """末尾连续「错误类轮次」计数——内容级判据。"""
    n = 0
    for evt in reversed(read_tail(20)):
        if evt.get("round") in DEGRADED_ROUNDS:
            n += 1
        elif evt.get("round") in HEALTHY_ROUNDS:
            break
        # 其他 round（如 gap_watch）不计入、不打断
    return n


def missing_paths() -> list:
    """关键路径缺失检查——这类故障重启无用，须人工介入。"""
    miss = []
    if not os.path.isdir(WISDOM):
        miss.append(WISDOM)
    if not os.path.isfile(BOOTSTRAP):
        miss.append(BOOTSTRAP)
    db = os.path.join(WISDOM, "wisdom-book-cloud.db")
    if not os.path.isfile(db):
        miss.append(db)
    return miss


def find_bootstrap_procs() -> list:
    """仅按命令行匹配 bootstrap_loop.py 的 python 进程。

    ⚠ 只认命令行含 bootstrap_loop.py 的进程——绝不 kill 其他 python
    （MCP server 等同解释器进程共存，宽匹配会误杀）。wmic 输出行尾
    \\r 干扰 PID 提取，一律 python re 提取（2026-08-31 教训固化）。
    """
    procs = []
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name like '%python%'",
             "get", "processid,commandline", "/format:csv"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace")
        import re
        pat = re.compile(r"(\d+)\s*$")
        for line in out.stdout.splitlines():
            if "bootstrap_loop.py" not in line:
                continue
            m = pat.search(line.strip())
            if m:
                procs.append({"pid": m.group(1),
                              "cmd": line.strip()[:200].replace("\r", "")})
    except Exception:
        pass
    return procs


def kill_procs(procs: list) -> None:
    for p in procs:
        try:
            subprocess.run(["taskkill", "/F", "/PID", p["pid"]],
                           capture_output=True, timeout=30)
        except Exception:
            pass


def restart(check_only: bool) -> dict:
    """拉起 bootstrap_loop（与设计一致：--interval 600, GAP_DEBUG=1）。"""
    env = dict(os.environ)
    env["GAP_DEBUG"] = "1"
    cmd = [PY, BOOTSTRAP, "--interval", "600"]
    if check_only:
        return {"action": "would_restart", "cmd": cmd}
    try:
        proc = subprocess.Popen(
            cmd, cwd=BRAIN, env=env, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.DEVNULL if os.name != "nt"
            else (subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW))
        # 等 6s 验证 loop_start 落地
        time.sleep(6)
        ts, last = last_log_ts()
        ok = last and last.get("round") == "loop_start"
        return {"action": "restarted", "pid": proc.pid,
                "verify": "loop_start_seen" if ok else "no_loop_start_yet",
                "last_round": (last or {}).get("round")}
    except Exception as e:
        return {"action": "restart_failed", "error": str(e)[:200]}


def main() -> int:
    ap = argparse.ArgumentParser(description="bootstrap_loop 停转检测与守护 v2")
    ap.add_argument("--interval", type=int, default=600)
    ap.add_argument("--check-only", action="store_true", help="只报告不动作")
    args = ap.parse_args()

    stale_limit = 2 * args.interval + GRACE
    now = time.time()
    last_ts, last = last_log_ts()
    report = {"round": "watchdog", "interval": args.interval,
              "stale_limit_s": stale_limit,
              "data_root": _dp.data_root(), "state": STATE}

    # ⓪ 路径级判据：关键路径缺失 → 人工介入，不重启（消除「重启刷噪声」）
    miss = missing_paths()
    if miss:
        report.update({"status": "config_error", "missing": miss,
                       "detail": "关键路径缺失，重启不修复——需人工处置"})
        log_watch(report)
        print(json.dumps(report, ensure_ascii=False))
        return 3

    if last_ts is None:
        report.update({"status": "no_log", "detail": "日志缺失或不可解析",
                       "log": LOG})
        log_watch(report)
        print(json.dumps(report, ensure_ascii=False))
        return 1

    age = now - last_ts
    deg = consecutive_degraded()
    report.update({"log_age_s": round(age, 1), "last_round": last.get("round"),
                   "last_ts": last.get("ts"), "consecutive_degraded": deg})

    # ① 内容级判据优先于新鲜度：新鲜但持续报错 → degraded，不报 alive
    if age <= stale_limit and deg >= DEGRADE_LIMIT:
        procs = find_bootstrap_procs()
        report.update({"status": "degraded", "proc_status":
                       "running" if procs else "not_running",
                       "procs": [{"pid": p["pid"]} for p in procs],
                       "detail": f"日志新鲜但连续 {deg} 轮错误（≥{DEGRADE_LIMIT}），"
                                 f"last={last.get('round')}"})
        log_watch(report)
        if procs and not args.check_only:
            kill_procs(procs)
            report.update(restart(False))
            report["status"] = "recovered" if report.get("action") == "restarted" \
                else "recover_failed"
            log_watch(report)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["status"] in ("degraded", "recovered") else 2

    # ② 新鲜且内容健康 → alive
    if age <= stale_limit:
        report.update({"status": "alive",
                       "detail": f"日志新鲜 {age:.0f}s ≤ {stale_limit}s 且末轮健康"})
        log_watch(report)
        print(json.dumps(report, ensure_ascii=False))
        return 0

    # ③ 停转：查进程后恢复
    procs = find_bootstrap_procs()
    report["procs"] = [{"pid": p["pid"]} for p in procs]
    if procs:
        report["proc_status"] = "stale_running"
        log_watch(report)
        if not args.check_only:
            kill_procs(procs)
    else:
        report["proc_status"] = "not_running"
        log_watch(report)
    res = restart(args.check_only)
    report.update(res)
    report["status"] = "recovered" if res.get("action") == "restarted" else (
        "would_recover" if res.get("action") == "would_restart" else "recover_failed")
    log_watch(report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] in ("recovered", "would_recover") else 2


if __name__ == "__main__":
    sys.exit(main())
