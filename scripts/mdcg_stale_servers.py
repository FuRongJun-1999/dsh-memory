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

判据② 与 issue #18 的交互（2026-09-20）：自插件 v0.4.9 起，随包子进程的 cwd 被
刻意移到**插件包之外**（Windows 下 cwd 落在包内会让 pnpm 更新该包必然
`ERR_PNPM_EBUSY` 且永不自愈，见 `src/lib/datapath.ts` 的 `runRoot()`）。故：
①新版进程必带自报 → 判据①命中，cwd 不参与裁决；
②`repo_direct` 分支现仅可能命中「无自报的旧包 + 恰好以本仓为 cwd」这一边缘组合；
**不能再用 cwd 判断「进程加载的是哪个安装副本」**（新版一律为包外同一目录），
副本归属以自报的 `source_dir` 为准。

用法：
  python scripts/mdcg_stale_servers.py list                  # 只读列举（默认）
  python scripts/mdcg_stale_servers.py list --fail-on-stale   # 有污染源/陈旧则退出码 1（重建前置守卫）
  python scripts/mdcg_stale_servers.py kill --pid 19944 --pid 2100 --purge-report
  python scripts/mdcg_stale_servers.py purge                  # 显式清理自报目录（只保留在役进程的自报）

退出码（N255 起）：0 成功/无污染源；1 list 带 --fail-on-stale 且存在 risky 进程（或 kill 有失败项）；
  2 **环境错误**——进程探测不可用（PowerShell 探不到/非零退出/输出不可解析）。修前探测失败与
  「确实没有 md_cg 进程」不可分，一律落到「前置守卫通过」的退出码 0（读不通被当成干净）。
副作用边界（N255）：`list` **只读**——自报目录的写/删只发生在显式的 `purge` 与
  `kill --purge-report` 上；修前 `scan()` 尾部无条件 `purge()`，与「只读枚举无副作用」直接矛盾，
  且探测失败时 `purge([])` 会把目录下全部自报一次删光。
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


# 生效条件：argv_ps 为 PowerShell -NoProfile -Command 加入参、timeout 为秒；env 强制 PYTHONUTF8=1 且 shell=False。返回 (text, rc)——text 为合并后的 stdout+stderr（未能执行时为 "<ERR ...>"），rc 为进程退出码、None 表示未能执行（异常/超时）。**退出码必须回传**（N255）：修前只并流文本、丢掉 rc，「PowerShell 失败」与「跑通但无输出」在调用方不可分。
def _ps(argv_ps: str, timeout: int = 60):
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", argv_ps],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env, timeout=timeout, shell=False)
    except Exception as e:  # noqa: BLE001
        return "<ERR %s: %s>" % (type(e).__name__, e), None
    return (r.stdout or "") + (r.stderr or ""), r.returncode


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


# 生效条件：无入参；返回 (records, err)——err 非 None 即「探测不可用」，调用方一律 fail-closed（绝不当作「未发现 md_cg 进程」）。四条可用性判据（①未能执行 ②非零退出 ③"<ERR" 标记 ④输出不可解析/记录缺 Name·ProcessId 键）见函数体与 docstring。
def probe_processes():
    """枚举进程 → (records, err)。**探测可用性的唯一单点**（N255）。

    修前「PS 失败/超时/输出不可解析」与「确实没有 md_cg 进程」在调用方不可分——两者都
    落到 `_procs() → []`：`scan()` 返回空行 → `list --fail-on-stale` 判「前置守卫通过」
    （退出码 0），同时 scan() 尾部的 `purge([])` 把自报目录**删光**。实测（沙盒 TEMP +
    令 PATH 不含 powershell）：`list --fail-on-stale` → stdout「污染源 0 个：无」、
    EXITCODE=0，而落盘的 3 个自报 *.json 全被删除——重建前置守卫在探不到进程时反而判绿。

    可用性判据（任一不成立即判不可用）：
      ① PowerShell 未能执行（FileNotFoundError/超时等）→ rc is None；
      ② PowerShell 非零退出；
      ③ 输出带 `<ERR …>` 标记；
      ④ 输出为空 / 解析不出任何记录 / 记录缺 PS_QUERY 必有的 Name·ProcessId 键
         （后者正是把 `<ERR X: y>` 这种错误文本按「Key : Value」解析出的**伪记录**：
         `scan()` 的 `name.startswith("python")` 对它恒为假，于是静默变成「无进程」）。
    真跑过的 `Get-CimInstance Win32_Process | … | Format-List` 恒有输出（至少本进程一行），
    故「无输出/不可解析」= 探测没真正执行，不得当成「没有进程」。
    """
    text, rc = _ps(PS_QUERY)
    if rc is None:
        return [], "PowerShell 未能执行：%s" % text[:200]
    if rc != 0:
        return [], "PowerShell 退出码 %d：%s" % (rc, text[:200])
    if text.strip().startswith("<ERR"):
        return [], "PowerShell 报告错误：%s" % text[:200]
    rows = _parse_ps(text)
    if not rows:
        return [], "探测输出不可解析为进程记录（%d 字符）：%r" % (len(text), text[:200])
    bad = [r for r in rows if not (r.get("Name") and r.get("ProcessId"))]
    if bad:
        return [], "探测输出含伪记录（缺 Name/ProcessId 键）：%r" % (bad[0],)
    return rows, None


# 生效条件：rec 为进程记录（可能是缺键的伪记录）时返回布尔——Name 以 python 开头且 CommandLine 含 MARK 即为本仓 md_cg MCP server 进程；缺键按空串处理（不误判）。
def _is_mdcg_proc(rec) -> bool:
    """「这是不是一个 md_cg MCP server 进程」的**唯一单点**（scan 与 purge 记账共用）。"""
    return ((rec.get("Name") or "").lower().startswith("python")
            and MARK in (rec.get("CommandLine") or ""))


# 生效条件：procs 为 probe_processes() 的记录列表时返回在役 md_cg 进程 pid 的 set（ProcessId 非整数者跳过）；作为 purge 的 keep 集口径单点。
def _live_mdcg_pids(procs) -> set:
    keep = set()
    for p in procs:
        if not _is_mdcg_proc(p):
            continue
        try:
            keep.add(int(p.get("ProcessId")))
        except (TypeError, ValueError):
            continue
    return keep


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


# 生效条件：无入参；返回 (rows, err)——err 非 None 表示进程探测不可用（此时 rows 为空，但**不代表**没有 md_cg 进程，调用方须 fail-closed）。**只读**：不做任何写盘/删除（自报目录的清理走 purge_reports / kill --purge-report 显式路径；N255 修：修前此处无条件 purge，与本模块「只读枚举无副作用」直接矛盾）。每项含 pid/parent/start/cwd/cwd_err/contract/render_version/source_dir/polluting/stale_by_mtime/cmd；判据序=自报（绝对事实）→ cwd 兜底 → mtime 附加信号，polluting 仅对 POLLUTING_CONTRACTS 置 True（unknown 置 None 以示「未知而非污染」）。
def scan():
    procs, err = probe_processes()
    if err:
        return [], err
    thr = _code_mtime()
    want = _required_render_version()
    reports = _self_reports()
    repo_n = _norm(REPO)
    mdcg_n = _norm(MDCG_DIR)
    out = []
    for p in procs:
        if not _is_mdcg_proc(p):
            continue
        cmd = p.get("CommandLine") or ""
        raw_pid = p.get("ProcessId")
        ep = _epoch(p.get("CreationDate") or "")
        try:
            pid = int(raw_pid)
        except Exception:  # noqa: BLE001
            pid = None
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
    return out, None


# 生效条件：无入参；返回 (keep, 删除条数, err)——err 非 None 表示探测不可用，此时返回 (set(), 0, err) 且**不删任何文件**（fail-closed）。探测可用时才按「保留在役 md_cg 进程 pid」清理自报目录（含遗留 *.tmp），空 keep 亦允许（那意味着在役进程确已全部退出）。显式清理单点，由 `purge` 子命令与 `kill --purge-report` 调用——不再挂在 scan() 尾部（N255）。
def purge_reports():
    procs, err = probe_processes()
    if err:
        return set(), 0, err
    keep = _live_mdcg_pids(procs)
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    try:
        from md_cg import selfreport as _sr
        n = _sr.purge(keep, allow_empty=True)
    except Exception as e:  # noqa: BLE001
        return keep, 0, "自报目录清理失败：%s: %s" % (type(e).__name__, e)
    return keep, n, None


# 生效条件：pid 为字符串/整数时返回处置结果 dict——先 probe_processes()：探测不可用即返回 ok=False 与「探测不可用」文案（**不执行 taskkill、也不谎报「进程不存在」**，N255）；探测可用时按 pid 重查进程表二次校验其命令行仍含 md_cg.mcp_server，校验通过才执行 taskkill /PID <pid> /F；进程不存在、命令行不匹配或 taskkill 非零退出时返回 ok=False 与 error 文案，绝不静默跳过。
def kill(pid: int) -> dict:
    procs, err = probe_processes()
    if err:
        return {"pid": pid, "ok": False,
                "error": "进程探测不可用（%s）——置信度不足，拒绝执行" % err}
    for p in procs:
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


# 生效条件：argv[0] 为 list/kill/purge 之一时执行对应分支——list **只读**打印 scan()，探测不可用（err 非 None）时 stdout 打 "[]"（--json 形状兼容）、stderr 报环境错误并返回码 2，**绝不判绿**（N255）；purge 走 purge_reports() 显式清理自报目录，探测不可用→stderr 报错并返回码 2 且不删任何文件；kill 要求至少一个 --pid 且逐个调用 kill()（探测不可用则每个都记 ok=False），带 --purge-report 时再按在役集清理，清理未完成→返回码 2。未给子命令时默认走 list，未知子命令返回码 2。list 带 --fail-on-stale 且存在 polluting=True 或 stale_by_mtime=True 的进程时返回码 1（重建前置守卫：污染源在位则重建必被刷回，宁可拒绝执行）。
def main() -> int:
    ap = argparse.ArgumentParser(description="md_cg MCP server 进程代际检测与处置")
    ap.add_argument("cmd", nargs="?", default="list", choices=["list", "kill", "purge"])
    ap.add_argument("--pid", action="append", default=[], type=int)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fail-on-stale", action="store_true",
                    help="list 时若存在污染源或 mtime 陈旧进程则退出码 1（重建前置守卫）")
    ap.add_argument("--purge-report", action="store_true",
                    help="kill 后按在役集清理自报目录（探测不可用则拒绝清理并退 2）")
    a = ap.parse_args()

    if a.cmd == "purge":
        # N255：清理是**显式**动作，且解包前先确认探测可用——空 keep 既可能是「在役进程
        # 已全部退出」也可能是「探测失败」，两者不可分，故后者一律拒绝清理（退 2）。
        keep, n, err = purge_reports()
        if err:
            print("[环境错误] 拒绝清理自报目录（fail-closed）：%s" % err, file=sys.stderr)
            return 2
        if a.json:
            print(json.dumps({"purged": n, "live": sorted(keep)},
                             ensure_ascii=False))
        else:
            print("已清理自报文件 %d 个；保留在役 md_cg 进程 %d 个：%s"
                  % (n, len(keep), sorted(keep) or "无"))
        return 0

    if a.cmd == "list":
        rows, err = scan()
        if err:
            # N255：探测不可用 ≠ 没有进程。修前此处 rows=[] → risky=[] → 判「前置守卫通过」
            # （退出码 0），同时 scan() 尾部 purge([]) 把自报目录删光——读不通被当成干净。
            if a.json:
                print("[]")
            print("[环境错误] 进程探测不可用：%s" % err, file=sys.stderr)
            return 2
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
    all_ok = all(r.get("ok") for r in res)
    if a.purge_report:
        keep, n, err = purge_reports()
        if err:
            print("[环境错误] kill 已执行，但自报目录清理未完成（fail-closed）：%s" % err,
                  file=sys.stderr)
            return 2
        print("已清理自报文件 %d 个；保留在役 md_cg 进程 %d 个" % (n, len(keep)))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
