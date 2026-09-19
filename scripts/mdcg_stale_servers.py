# -*- coding: utf-8 -*-
"""陈旧 md_cg MCP server 进程检测与处置（防「源码已改、进程未重载」静默污染）。

# 生效条件：载体/位置：仓根 scripts/mdcg_stale_servers.py；时间：md_cg 组件源码发生改动、或库内节点形态出现反常回归（如新契约形态被刷回旧形态）时运行；方法：用 PowerShell Get-CimInstance 枚举 python 进程，对命令行含 md_cg.mcp_server 者比对进程启动时间与 md_cg/*.py 的最新 mtime，早于该阈值即判「陈旧」（进程加载的模块版本落后于磁盘源码）；约束：只读枚举无副作用，kill 子命令须显式传 PID 且执行前二次校验命令行仍匹配 md_cg.mcp_server，规避 PID 复用误杀无关进程。

用法：
  python scripts/mdcg_stale_servers.py list                # 只读列举（默认）
  python scripts/mdcg_stale_servers.py list --fail-on-stale  # 有陈旧进程则退出码 1（重建前置守卫）
  python scripts/mdcg_stale_servers.py kill --pid 19944 --pid 2100
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MDCG_DIR = os.path.join(REPO, "md_cg")
MARK = "md_cg.mcp_server"

PS_QUERY = ("Get-CimInstance Win32_Process | "
            "Select-Object ProcessId,ParentProcessId,Name,CreationDate,CommandLine | "
            "Format-List")


# 生效条件：无入参，argv 固定为 PowerShell -NoProfile -Command 加模块级 PS_QUERY 常量，env 强制 PYTHONUTF8=1 且 shell=False，返回合并后的 stdout+stderr 文本；超时或异常时返回 "<ERR ...>" 字符串而不抛出。
def _ps(argv_ps: str, timeout: int = 60) -> str:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", argv_ps],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env, timeout=timeout, shell=False)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:  # noqa: BLE001
        return "<ERR %s: %s>" % (type(e).__name__, e)


# 生效条件：text 为 Format-List 形态文本（空行分隔的记录块、每块 "Key : Value" 行）时解析为 dict 列表，键值均 strip；无 ":" 的行与空块被跳过，因此输入为空串时返回空列表而不报错。
def _parse_ps(text: str) -> list:
    procs, cur = [], {}
    for ln in text.split("\n"):
        s = ln.rstrip("\r")
        if not s.strip():
            if cur:
                procs.append(cur)
                cur = {}
            continue
        if ":" in s:
            k, v = s.split(":", 1)
            cur[k.strip()] = v.strip()
    if cur:
        procs.append(cur)
    return procs


# 生效条件：SRC 目录存在时返回该目录下全部 *.py 的 mtime 最大值；目录不存在或无 py 文件时返回 0.0（调用方据此放宽判据，不把「取不到阈值」当成「全部陈旧」）。
def _code_mtime() -> float:
    latest = 0.0
    if not os.path.isdir(MDCG_DIR):
        return latest
    for f in os.listdir(MDCG_DIR):
        if f.endswith(".py"):
            try:
                latest = max(latest, os.stat(os.path.join(MDCG_DIR, f)).st_mtime)
            except OSError:
                pass
    return latest


# 生效条件：无入参，用 _ps(PS_QUERY) 枚举全部进程并解析为 dict 列表返回；PowerShell 不可用时 _ps 返回 "<ERR ...>"，_parse_ps 对其解析出空列表（调用方看到「未发现 md_cg 进程」，需结合 stderr 文本判别环境异常）。
def _procs() -> list:
    return _parse_ps(_ps(PS_QUERY))


# 生效条件：stamp 为 "2026/9/17 15:17:30" 形态时返回 epoch 秒；解析失败返回 None（调用方据此跳过陈旧判定，不把未知启动时间的进程误判为陈旧）。
def _epoch(stamp: str):
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return time.mktime(time.strptime(stamp.strip()[:19], fmt))
        except Exception:  # noqa: BLE001
            continue
    return None


# 生效条件：无入参，返回全部命令行含 md_cg.mcp_server 的 python 进程记录（每项含 pid/parent/start/cmd/stale 四键）；阈值取 md_cg/*.py 最新 mtime，进程启动时间早于阈值即 stale=True，启动时间不可解析时 stale 置 None（未知而非陈旧）。
def scan() -> list:
    thr = _code_mtime()
    out = []
    for p in _procs():
        name = (p.get("Name") or "").lower()
        cmd = p.get("CommandLine") or ""
        if not name.startswith("python") or MARK not in cmd:
            continue
        ep = _epoch(p.get("CreationDate") or "")
        out.append({"pid": p.get("ProcessId"), "parent": p.get("ParentProcessId"),
                    "start": (p.get("CreationDate") or "")[:19], "cmd": cmd,
                    "stale": (None if ep is None else ep < thr)})
    return out


# 生效条件：pid 为字符串/整数时先按 pid 重查进程表二次校验其命令行仍含 md_cg.mcp_server，校验通过才执行 taskkill /PID <pid> /F；进程不存在、命令行不匹配或 taskkill 非零退出时返回 ok=False 与 error 文案，绝不静默跳过。
def kill(pid: int) -> dict:
    for p in _procs():
        if str(p.get("ProcessId")) == str(pid):
            if MARK not in (p.get("CommandLine") or ""):
                return {"pid": pid, "ok": False,
                        "error": "命令行已不含 %s，疑似 PID 复用，拒绝执行" % MARK}
            r = subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", shell=False)
            return {"pid": pid, "ok": r.returncode == 0, "exit_code": r.returncode,
                    "out": ((r.stdout or "") + (r.stderr or ""))[:400]}
    return {"pid": pid, "ok": False, "error": "进程不存在"}


# 生效条件：argv[0] 为 list/kill 之一时执行对应分支——list 直接打印 scan() 的结果（不改状态），kill 要求至少一个 --pid 且逐个调用 kill() 后打印结果；未给子命令时默认走 list，未知子命令返回码 2。list 带 --fail-on-stale 且存在陈旧进程时返回码 1（供重建流程做前置守卫：污染源在位则重建必被刷回，宁可拒绝执行）。
def main() -> int:
    ap = argparse.ArgumentParser(description="陈旧 md_cg MCP server 进程检测与处置")
    ap.add_argument("cmd", nargs="?", default="list", choices=["list", "kill"])
    ap.add_argument("--pid", action="append", default=[], type=int)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fail-on-stale", action="store_true",
                    help="list 时若存在陈旧进程则以退出码 1 结束（重建前置守卫）")
    a = ap.parse_args()

    if a.cmd == "list":
        rows = scan()
        stale = [r for r in rows if r["stale"]]
        if a.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return 1 if (a.fail_on_stale and stale) else 0
        thr = _code_mtime()
        print("判据阈值 = md_cg/*.py 最新 mtime = %s"
              % time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(thr)))
        print("%-8s %-8s %-20s %-7s %s" % ("PID", "PPID", "启动", "陈旧", "命令行"))
        for r in rows:
            print("%-8s %-8s %-20s %-7s %s" % (
                r["pid"], r["parent"], r["start"],
                {True: "是", False: "否", None: "未知"}[r["stale"]], r["cmd"][:60]))
        print("\n陈旧进程 %d 个：%s" % (len(stale), [r["pid"] for r in stale] or "无"))
        print("处置：python scripts/mdcg_stale_servers.py kill --pid <PID> [--pid <PID>]")
        if a.fail_on_stale and stale:
            print("前置守卫未通过：存在陈旧进程 %s，其旧 render 会覆盖重建成果，拒绝继续。"
                  % [r["pid"] for r in stale], file=sys.stderr)
            return 1
        return 0

    if not a.pid:
        print("kill 需至少一个 --pid", file=sys.stderr)
        return 2
    res = [kill(p) for p in a.pid]
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if all(r.get("ok") for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
