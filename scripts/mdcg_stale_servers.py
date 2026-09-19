# -*- coding: utf-8 -*-
"""md_cg MCP server 进程代际检测与处置（防「旧契约进程覆盖重建成果」静默污染）。

# 生效条件：载体/位置：仓根 scripts/mdcg_stale_servers.py；时间：全量重建（code 节点重切）**前置守卫**、md_cg 组件源码改动后、或库内节点形态出现反常回归（新契约形态被刷回 old_synth）时运行；方法：PowerShell 枚举 python 进程筛命令行含 md_cg.mcp_server 者，逐进程按「①自报（md_cg/selfreport.py 落的事实：实际加载源 source_dir + 契约代际 render_version）②cwd 兜底（ctypes 读目标进程 PEB.CurrentDirectory，`python -m` 时 sys.path[0] 恒为 cwd）③mtime 附加信号」三级判据裁决契约代际；约束：只读枚举无副作用，kill 子命令须显式传 PID 且执行前二次校验命令行仍匹配 md_cg.mcp_server，规避 PID 复用误杀无关进程。

## 判据升级（2026-09-19）：从「相对量」到「绝对事实」

原判据只有一条：进程启动时间 < md_cg/*.py 最新 mtime 即判陈旧。**活体盲区**：
npm 副本内进程启动于 11:37~11:39，而源码 mtime 为 09:24 → `stale=False`，
但它加载的是插件包 0.4.8 的旧契约 `codeindex.render`，把全量重建成果刷回
`old_synth`（AGENTS.md §5 运维注记实证）。mtime 是相对量，每次须复算且天然滞后。

升级后以**自报**为主判据（进程自己报出实际加载的 md_cg 包目录与
`codeindex.RENDER_VERSION`）：旧包不含 `md_cg/selfreport.py`，故**「无自报」
本身即旧契约的证据**；无自报时用 cwd 兜底（cwd 指向本仓即可确认加载源，
指向其它副本则保守判污染）。mtime 降级为**附加信号**保留（它独立表达
「源码已改、进程未重载」）。新判据严格强于旧判据。

合同代际（contract）取值：
  current            自报在位 + source_dir=本仓 md_cg + render_version>=要求 → 放行
  stale_contract     自报在位但 render_version < 要求 → 污染源
  foreign_src        自报在位但 source_dir 非本仓 md_cg → 污染源（异源副本）
  repo_direct        无自报但 cwd=本仓 → 加载源必为本仓（代际待自报确认）
  unverified_foreign 无自报且 cwd 非本仓 → 污染源（保守：来源无法确认）
  unknown            无自报且 cwd 取不到 → 未知，不判污染（不误杀）

用法：
  python scripts/mdcg_stale_servers.py list                  # 只读列举（默认）
  python scripts/mdcg_stale_servers.py list --fail-on-stale   # 有污染源/陈旧则退出码 1（重建前置守卫）
  python scripts/mdcg_stale_servers.py kill --pid 19944 --pid 2100 --purge-report
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
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

# 污染类合同（须先处置再重建）；repo_direct/unknown 不列入。
POLLUTING_CONTRACTS = ("stale_contract", "foreign_src", "unverified_foreign")

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_ntdll = ctypes.WinDLL("ntdll")


class _PBI(ctypes.Structure):
    _fields_ = [("Reserved1", ctypes.c_void_p),
                ("PebBaseAddress", ctypes.c_void_p),
                ("Reserved2", ctypes.c_void_p * 2),
                ("UniqueProcessId", ctypes.c_void_p),
                ("Reserved3", ctypes.c_void_p)]


# 生效条件：无入参，把平台路径规范化为可跨拼写比较的形态（abspath + normpath + normcase + 统一分隔符），入参为 None/空串时返回空串；用于「自报 source_dir 是否等于本仓 md_cg」这类判定，避免大小写与斜杠差异造成的假异源。
def _norm(p) -> str:
    if not p:
        return ""
    try:
        return os.path.normcase(os.path.normpath(os.path.abspath(p)))
    except Exception:  # noqa: BLE001
        return ""


# 生效条件：h 为已打开的进程句柄、addr 为目标地址、buf 为 ctypes 缓冲、size 为字节数时执行 ReadProcessMemory 并返回布尔成功标志；失败返回 False（调用方据此降级为「未知」而非误判）。
def _rpm(h, addr, buf, size) -> bool:
    n = ctypes.c_size_t()
    return bool(_k32.ReadProcessMemory(ctypes.c_void_p(h), ctypes.c_void_p(addr),
                                       buf, size, ctypes.byref(n)))


# 生效条件：pid 为整数进程号时，用 OpenProcess(QUERY_INFORMATION|VM_READ) + NtQueryInformationProcess + 三级 ReadProcessMemory 读目标进程 PEB.CurrentDirectory（x64 偏移：PEB+0x20 → RTL_USER_PROCESS_PARAMETERS+0x38 的 UNICODE_STRING.Length、+0x40 的 Buffer），返回 (cwd, None)；OpenProcess 被拒/查询失败/取到空串时返回 (None, 错误文案)，绝不抛。
def _read_cwd(pid):
    """读目标进程当前工作目录（零依赖，ctypes 直读 PEB）。"""
    try:
        h = _k32.OpenProcess(0x0400 | 0x0010, False, int(pid))
        if not h:
            return None, "OpenProcess err=%d" % ctypes.get_last_error()
        try:
            pbi = _PBI()
            r = _ntdll.NtQueryInformationProcess(ctypes.c_void_p(h), 0,
                                                ctypes.byref(pbi),
                                                ctypes.sizeof(pbi), None)
            if r != 0:
                return None, "NtQueryInformationProcess=%d" % r
            params = ctypes.c_void_p()
            if not _rpm(h, pbi.PebBaseAddress + 0x20, ctypes.byref(params), 8):
                return None, ("ReadProcessMemory(params) err=%d"
                              % ctypes.get_last_error())
            us = wt.USHORT()
            bufptr = ctypes.c_void_p()
            if not _rpm(h, params.value + 0x38, ctypes.byref(us), 2):
                return None, ("ReadProcessMemory(us.Length) err=%d"
                              % ctypes.get_last_error())
            if not _rpm(h, params.value + 0x40, ctypes.byref(bufptr), 8):
                return None, ("ReadProcessMemory(us.Buffer) err=%d"
                              % ctypes.get_last_error())
            if not us.value or not bufptr.value:
                return None, "CurrentDirectory 为空"
            raw = ctypes.create_string_buffer(us.value)
            if not _rpm(h, bufptr.value, raw, us.value):
                return None, ("ReadProcessMemory(string) err=%d"
                              % ctypes.get_last_error())
            return raw.raw.decode("utf-16-le", "replace"), None
        finally:
            _k32.CloseHandle(ctypes.c_void_p(h))
    except Exception as e:  # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)


# 生效条件：argv 固定为 PowerShell -NoProfile -Command 加入参 argv_ps，env 强制 PYTHONUTF8=1 且 shell=False，返回合并后的 stdout+stderr 文本；超时或异常时返回 "<ERR ...>" 字符串而不抛出。
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


# 生效条件：MDCG_DIR 存在时返回该目录下全部 *.py 的 mtime 最大值；目录不存在或无 py 文件时返回 0.0（调用方据此放宽判据，不把「取不到阈值」当成「全部陈旧」）。
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


# 生效条件：本仓 md_cg 包可导入时返回 int(codeindex.RENDER_VERSION)（与 refindex 写进节点的版本戳**同源**，不在此处硬编码版本号）；导入失败返回 None，此时版本维度判据降级为「不裁决」而非误判。
def _required_render_version():
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    try:
        from md_cg import codeindex
        return int(codeindex.RENDER_VERSION)
    except Exception:  # noqa: BLE001
        return None


# 生效条件：sid 为 int/str 形态 pid 时返回 str(sid) 供字典键匹配；与 selfreport.read_all() 的 int 键比较时由 _self_reports 统一转 int。
def _self_reports() -> dict:
    """读自报（pid → 记录）；导入失败返回空字典（该维度降级为 cwd 兜底）。"""
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    try:
        from md_cg import selfreport
        return selfreport.read_all()
    except Exception:  # noqa: BLE001
        return {}


# 生效条件：ep 为 pid 启动 epoch、rec 为自报记录（可能为 None）时返回可用自报记录——rec 为 None 时返回 None；rec["ts"] 早于启动时间 5 秒以上时判为「pid 复用遗留文件」返回 None；ts 缺失时按可用处理（兼容早期格式）。
def _valid_report(ep, rec):
    if not rec:
        return None
    ts = rec.get("ts")
    if isinstance(ts, (int, float)) and ep is not None and ts < ep - 5:
        return None
    return rec


# 生效条件：无入参，返回全部命令行含 md_cg.mcp_server 的 python 进程记录，每项含 pid/parent/start/cwd/cwd_err/contract/render_version/source_dir/polluting/stale_by_mtime/cmd；判据序=自报（绝对事实）→ cwd 兜底 → mtime 附加信号，polluting 仅对 POLLUTING_CONTRACTS 置 True（unknown 置 None 以示「未知而非污染」）。
def scan() -> list:
    thr = _code_mtime()
    want = _required_render_version()
    reports = _self_reports()
    repo_n = _norm(REPO)
    mdcg_n = _norm(MDCG_DIR)
    pids = []
    out = []
    for p in _procs():
        name = (p.get("Name") or "").lower()
        cmd = p.get("CommandLine") or ""
        if not name.startswith("python") or MARK not in cmd:
            continue
        raw_pid = p.get("ProcessId")
        ep = _epoch(p.get("CreationDate") or "")
        try:
            pid = int(raw_pid)
        except Exception:  # noqa: BLE001
            pid = None
        pids.append(pid)
        cwd, cwd_err = (_read_cwd(pid) if pid else (None, "无效 pid"))
        rec = _valid_report(ep, reports.get(pid) if pid else None)

        # ---- 判据①：自报（绝对事实）------------------------------------
        if rec:
            src_n = _norm(rec.get("source_dir"))
            rv = rec.get("render_version")
            if src_n and src_n != mdcg_n:
                contract = "foreign_src"
            elif want is not None and isinstance(rv, int) and rv < want:
                contract = "stale_contract"
            elif src_n and src_n == mdcg_n:
                contract = "current"
            else:
                contract = "unknown"
        # ---- 判据②：cwd 兜底（无自报时）--------------------------------
        elif cwd:
            contract = "repo_direct" if _norm(cwd) == repo_n else "unverified_foreign"
        else:
            contract = "unknown"

        out.append({
            "pid": raw_pid, "parent": p.get("ParentProcessId"),
            "start": (p.get("CreationDate") or "")[:19], "cmd": cmd,
            "cwd": cwd, "cwd_err": cwd_err,
            "contract": contract,
            "render_version": (rec or {}).get("render_version"),
            "source_dir": (rec or {}).get("source_dir"),
            "polluting": (True if contract in POLLUTING_CONTRACTS
                          else (None if contract == "unknown" else False)),
            "stale_by_mtime": (None if ep is None else ep < thr),
        })
    try:
        from md_cg import selfreport as _sr
        _sr.purge(pids)
    except Exception:  # noqa: BLE001
        pass
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


# 生效条件：argv[0] 为 list/kill 之一时执行对应分支——list 打印 scan() 并给出合同代际分布（不改状态），kill 要求至少一个 --pid 且逐个调用 kill() 后打印结果；未给子命令时默认走 list，未知子命令返回码 2。list 带 --fail-on-stale 且存在 polluting=True 或 stale_by_mtime=True 的进程时返回码 1（重建前置守卫：污染源在位则重建必被刷回，宁可拒绝执行）。
def main() -> int:
    ap = argparse.ArgumentParser(description="md_cg MCP server 进程代际检测与处置")
    ap.add_argument("cmd", nargs="?", default="list", choices=["list", "kill"])
    ap.add_argument("--pid", action="append", default=[], type=int)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fail-on-stale", action="store_true",
                    help="list 时若存在污染源或 mtime 陈旧进程则退出码 1（重建前置守卫）")
    a = ap.parse_args()

    if a.cmd == "list":
        rows = scan()
        risky = [r for r in rows
                 if r["polluting"] is True or r["stale_by_mtime"] is True]
        if a.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return 1 if (a.fail_on_stale and risky) else 0
        thr = _code_mtime()
        want = _required_render_version()
        print("判据①自报来源 = <tempdir>/md_cg_servers/<pid>.json"
              "（md_cg/selfreport.py 落盘）")
        print("判据②cwd 兜底 = 目标进程 PEB.CurrentDirectory（python -m 时 sys.path[0]）")
        print("判据③mtime 阈值 = md_cg/*.py 最新 mtime = %s"
              % time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(thr)))
        print("要求 render_version >= %s（本仓 codeindex.RENDER_VERSION）" % want)
        print("%-8s %-8s %-20s %-19s %-6s %-7s %s"
              % ("PID", "PPID", "启动", "合同代际", "版本", "污染", "cwd"))
        for r in rows:
            print("%-8s %-8s %-20s %-19s %-6s %-7s %s" % (
                r["pid"], r["parent"], r["start"], r["contract"],
                r["render_version"] if r["render_version"] is not None else "-",
                {True: "是", False: "否", None: "未知"}[r["polluting"]],
                r["cwd"] or ("<取不到: %s>" % r["cwd_err"])))
        print("\n污染源 %d 个：%s"
              % (len([r for r in rows if r["polluting"] is True]),
                 [r["pid"] for r in rows if r["polluting"] is True] or "无"))
        print("mtime 陈旧 %d 个：%s"
              % (len([r for r in rows if r["stale_by_mtime"] is True]),
                 [r["pid"] for r in rows if r["stale_by_mtime"] is True] or "无"))
        print("处置：python scripts/mdcg_stale_servers.py kill --pid <PID> [--pid <PID>]"
              "（被 kill 的进程由其宿主按需重连拉起，新进程会自报）")
        if a.fail_on_stale and risky:
            print("前置守卫未通过：risky 进程 %s（其旧 render 会覆盖重建成果），拒绝继续。"
                  % [r["pid"] for r in risky], file=sys.stderr)
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
