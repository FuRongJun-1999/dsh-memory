#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""# 功能名：出货面冒烟发布门禁 check_publish_smoke

# 生效条件：本机可解析 npm（Windows 命中 npm.cmd，走 check_publish_artifact.resolve_npm
   单点），--root 指向可打包的仓库根，且沙箱目录可写；本腿在**空沙箱**里真装真启动，
   绝不读写使用者的真实记忆库。
# 子功能：①npm pack 真产物 → 出货清单点名断言（仓根 utf8_boot.py）
   ②空沙箱真装（npm install <tgz>）→ 装好的目录里点名断言
   ②.5 懒加载数据面：装机后 import md_cg.units，问它的字符集表解析成功没有
   ③从装好的目录真启动 MCP → 真发 initialize / notifications/initialized / tools/list
   ④启动 stderr 的策略来源记录（NOTE，恒不判负）
# 执行：python -X utf8 scripts/check_publish_smoke.py [--root <仓库根>]
   沙箱：缺省 tempfile.mkdtemp()（跑完清理）；env MDCG_GATE_SANDBOX_DIR 给定时
   使用它并**保留不删**（便于人工复核）。
# 验证方式：本门禁自身即验证面——出货清单条目数、装好的目录点名文件、握手 serverInfo
   与 tools 列表、沙箱路径与是否清理，逐项打到 stdout 的 [PASS]/[FAIL] 行与末行
   SMOKE_JSON（机器可读读数，供 scripts/test_publish_smoke_guard.py 解析）。
# 不适用条件：不覆盖 DSH 桥侧（dsh/ 插件与 MCP 客户端的接线）、不覆盖真实 DSH 安装
   路径（本腿装的是空沙箱里的 node_modules）、不覆盖 peer 依赖解析（安装加
   --legacy-peer-deps 跳过 peer）、不覆盖 MDCG_MCP_SURFACE=full 的多工具面（本腿只
   测缺省面 ['cg','stg']）、不覆盖 TypeScript 侧 lib/ 的运行时行为。

为什么另立一道腿（同类已漏三次）：
  · 「仓库里在、包里不在」这一类缺陷，既有八道门禁**全看不见**——check_publish_artifact
    只扫包内件的内容政策（凭据/私有数据/隐私/非追踪），不检查某个**必要件是否缺席**；
    实测三次：#38（scripts/ 与 hive/ 整目录未出货）、issue #48（仓根 utf8_boot.py 未被
    files 收录 ⇒ 0.6.1 装机即挂，`md_cg/mcp_server.py` 的 `from utf8_boot import ensure_utf8`
    直接 ModuleNotFoundError）、第三次＝`hive/id_charset_blocks.txt` 未被 files 收录
    ⇒ 装机后 `md_cg/units.py` 的字符集表解析 fail-closed（见 S7）。
  · 第三次比前两次**隐蔽**：前两次让进程起来即退（响），第三次不阻塞启动、记忆照常，
    只在 cg(op=ccg, action=units) 这条委派链上静默把一切 job_id 判 False。
  · 故本腿以**出货清单点名 + 真装真握手 + 懒加载数据面语义探测**收口：必要件缺席即红并
    点名缺件，且不只信清单——装出来的目录里再点名一次、真启动一次、真 import 一次，把
    「清单有而装机没有」与「文件在但解析不了」一起堵住。

判据（S0–S7，名字即机器读面）：
  S0 npm 可执行面可解析（探不到即 fail-closed 退出码 1，不静默 SKIP）
  S1 出货清单含仓根 utf8_boot.py（缺则点名「修法：files 加 utf8_boot.py」）
  S2 装好的目录含 utf8_boot.py
  S3 装好的目录含 md_cg/mcp_server.py
  S4 真握手成功（initialize → serverInfo，name/version 与包内 package.json 对齐）
  S5 tools 面 == 缺省面 ['cg','stg']
  S6 策略来源来自**包内** data/policy.json（NOTE，恒不判负）
  S7 装机后 md_cg/units.py 的字符集表可解析（**语义**判据：真 import 真解析，不止看
     文件名在不在——`CHARSET_BLOCKS_ERROR is None` 且区间数 > 0；缺则点名
     「修法：files 加 hive/id_charset_blocks.txt」）
  S8 装机后 `recent·add` **真落台账**（2026-11-02 补，**行为判据**）：签写入凭据 → 起真
     MCP 发一条用户轮 → `<MDCG_ROOT>/_state_events.jsonl` 里至少 1 条且
     `actor=state_extract`。S1–S3/S7 全是静态面（件在不在、数据能不能解析），
     而 L2 台账的真缺陷是「静态全绿、链路不通」（抽取器本体在不随包的 `scripts/`）
     ⇒ 判据必须落在行为上。**不钉具体槽位/值**：把发布闸耦合到抽取规则表会让
     规则演进误伤发版。
  S9 台账**读得回来**（投影/查询面与台账账实一致）：`state_slots --status` 的 events
     数 == 台账条数，且 `stg(op=state_chain)` 对首条事件的 (subject, slot) count ≥ 1。

退出码：0 通过｜1 判据红（含 npm 探不到，按本腿契约 fail-closed）｜2 环境错误。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_REPO, "scripts")

#: 缺省工具面（kernel 面）：md_cg/mcp_server.py 的 SURFACE 缺省档只暴露这两个基元。
#: 子进程环境剔除全部 MDCG_*，故缺省面必然生效——加了 MDCG_MCP_SURFACE（可达 33 面）
#: 的口径不在本腿判据内，本腿只钉缺省面。
DEFAULT_TOOLS = ("cg", "stg")
PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "mdcg-mcp"
#: 沙箱内四个根的叶子名。**凭据根叶子不叫 aux**：Windows 上
#: `os.path.abspath(r"D:\\x\\aux")` == `r"\\\\.\\aux"`（aux/con/nul 是保留设备名，
#: GetFullPathNameW 把整个目录吞成设备路径），md_cg.datapath._abs_host_path 据此抛
#: ValueError，会让服务以 rc=2 拒绝启动——2026-09-30 本机实测取证，故取 aux_root。
ROOT_LEAF = "memory"
AUX_LEAF = "aux_root"
STATE_LEAF = "state"
DATA_LEAF = "data"
PACK_SUBDIR = "pack"
INSTALL_SUBDIR = "install"
#: 握手总预算：实测 1.3s（0.6.1 装机面），给足余量但不无限等。
HANDSHAKE_TIMEOUT = 180
NPM_TIMEOUT = 600
#: 懒加载数据面探测预算（只 import 一个模块并打印一行 JSON，实测 <1s）。
PROBE_TIMEOUT = 120


# 生效条件：无入参，按脚本所在位置加载同目录 check_publish_artifact.py（scripts/ 非包，
# 只能按路径加载）并返回该模块；加载失败抛异常由调用方收敛为环境错误。
def _load_publish_artifact():
    """加载 npm 解析单点所在模块（scripts/check_publish_artifact.py）。"""
    fp = os.path.join(_SCRIPTS, "check_publish_artifact.py")
    spec = importlib.util.spec_from_file_location("mdcg_cpa_npm_single_point", fp)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Report:
    """判负/记录面：FAIL 名字进 report.fails（SMOKE_JSON 的机器读面即取自它）。"""

    def __init__(self):
        self.fails = []
        self.notes = []

    def rule(self, name, ok, detail=""):
        print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                               ("：" + detail) if detail else ""))
        if not ok:
            self.fails.append(name)
        return bool(ok)

    def note(self, msg):
        self.notes.append(msg)
        print("  [NOTE] %s" % msg)


# 生效条件：无入参，返回 os.environ 的副本并把 PYTHONUTF8 置为 "1"（本脚本自己的子进程
# 继承面；密闭环境另见 _sealed_env）。
def _base_env():
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    return env


# 生效条件：mem_root/aux_dir/state_dir/data_dir 为四个沙箱内绝对路径时，返回剔除调用者
# 继承来的**全部** MDCG_*/DEEPSEEK_* 之后、再注入这四个根的环境字典；恒定不抛异常。
def _sealed_env(mem_root, aux_dir, state_dir, data_dir):
    """沙箱密闭环境（本腿的凭据/数据隔离面）。

    为什么必须剔除 MDCG_*：本机开发 shell 常带 MDCG_TOKEN / MDCG_VERIFY_KEY，子进程
    能读到却不在沙箱凭据库里 → mcp_server fail-closed 拒启（rc=3「令牌不存在」）——
    那是**正确行为**，但会让本门禁假红（issue #48 复现面实测同族）。
    为什么四个根都指沙箱：只给 MDCG_ROOT/MDCG_AUX_ROOT 时，state/data 根仍回落
    `~/.dsh/.dsh-memory`（datapath.state_root/default_data_root），进而读到使用者的
    paths.json（其 data_root 可能直指真实记忆库）——本腿绝不碰使用者真实记忆库与
    ~/.mdcg，故一并钉进沙箱。
    """
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("MDCG_") and not k.startswith("DEEPSEEK_")}
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["MDCG_ROOT"] = mem_root
    env["MDCG_AUX_ROOT"] = aux_dir
    env["MDCG_STATE_ROOT"] = state_dir
    env["MDCG_DATA_ROOT"] = data_dir
    return env


# 生效条件：given（env MDCG_GATE_SANDBOX_DIR 的取值，可为空串）非空时对其做 abspath 并
# makedirs 后返回 (该路径, True)，otherwise 返回 (tempfile.mkdtemp() 新建目录, False)。
def _make_sandbox(given):
    """→ (沙箱目录, 是否保留)。缺省临时目录；env 给定时用给定目录并保留不删。"""
    given = (given or "").strip()
    if given:
        d = os.path.abspath(given)
        os.makedirs(d, exist_ok=True)
        print("  沙箱=%s（来源：MDCG_GATE_SANDBOX_DIR —— 跑完**保留不删**，供人工复核）" % d)
        return d, True
    d = tempfile.mkdtemp(prefix="mdcg_smoke_")
    print("  沙箱=%s（来源：tempfile.mkdtemp —— 跑完清理）" % d)
    return d, False


# 生效条件：argv 为 argv 列表（首项为可执行文件）、cwd 为工作目录；subprocess.run 正常
# 结束时返回 CompletedProcess，抛 OSError/TimeoutExpired 时打印环境错误并返回 None。
def _run(argv, cwd, env, timeout, stdin_payload=None):
    print("  执行：%s%s" % (" ".join(argv),
                          "" if stdin_payload is None else "（stdin 逐行 3 条 JSON-RPC）"))
    t0 = time.time()
    try:
        proc = subprocess.run(argv, input=stdin_payload, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              env=env, cwd=cwd, shell=False, timeout=timeout)
    except OSError as exc:
        print("[环境错误] 无法执行 %s：%s" % (argv[0], exc))
        return None
    except subprocess.TimeoutExpired:
        print("[环境错误] %s 超时（>%ds）" % (argv[0], timeout))
        return None
    print("  rc=%s 用时=%.1fs" % (proc.returncode, time.time() - t0))
    return proc


# 生效条件：tgz 为存在的 tarball 路径时返回其内文件名列表（去掉 "package/" 前缀、按字典序），
# 打不开（非 tar.gz / IO 失败）时返回 None。
def _tarball_members(tgz):
    try:
        with tarfile.open(tgz, mode="r:gz") as tf:
            names = []
            for m in tf.getmembers():
                if not m.isfile():
                    continue
                rel = m.name.replace("\\", "/")
                while rel.startswith("./"):
                    rel = rel[2:]
                if rel.startswith("package/"):
                    rel = rel[len("package/"):]
                names.append(rel)
    except (OSError, tarfile.TarError) as exc:
        print("[环境错误] tarball 解包失败：%r" % (exc,))
        return None
    return sorted(names)


# 生效条件：stdout 为逐行 JSON-RPC 响应的文本时，返回 {id: 响应对象}——只收顶层为对象
# 且 id 非 None 的行（通知与噪声行不入表），解析失败的行直接跳过。
def _parse_replies(stdout):
    """逐行 JSON-RPC 响应 → {id: msg}（本仓 stdio 帧格式 = 逐行 JSON，不是 Content-Length）。"""
    replies = {}
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if isinstance(msg, dict) and msg.get("id") is not None:
            replies[msg["id"]] = msg
    return replies


# 生效条件：python_exe 为解释器路径、pkg_dir 为装好的包目录（含 md_cg/ 与 utf8_boot.py）、
# 四个根为沙箱内绝对路径时，以 _sealed_env 密闭环境在该目录下逐行喂 3 条 JSON-RPC
# （initialize / notifications/initialized / tools/list）并返回 (CompletedProcess, 秒数)；
# 解释器不可执行或超时返回 (None, 秒数)。
def _handshake(python_exe, pkg_dir, mem_root, aux_dir, state_dir, data_dir):
    env = _sealed_env(mem_root, aux_dir, state_dir, data_dir)
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                    "clientInfo": {"name": "publish-smoke", "version": "1.0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in requests)
    proc = _run([python_exe, "-X", "utf8", "-m", "md_cg.mcp_server"], pkg_dir,
                env, HANDSHAKE_TIMEOUT, stdin_payload=payload)
    return proc


# ---- L2 状态台账端到端（S8/S9）----
#: 探针发言：一句话同时命中两条保守抽取规则（地点·所在迁移 + 情感·偏好）。
#: **不硬编码命中结果**——只要求「至少落 1 条且 actor=state_extract」，避免把门禁
#: 耦合到抽取规则表本身（规则演进不该让发布闸变红）。
L2_PROBE_TEXT = "我搬到杭州了，我很喜欢西湖"
L2_PROBE_SESSION = "publish-smoke-l2"
L2_PROBE_TURN = 7


# 生效条件：python_exe 为解释器路径、pkg_dir 为装好的包目录、四根为沙箱内绝对路径（须已
# makedirs）时，签一张写入凭据（recent 面即可，收窄到最小权限）→ 起真 MCP 发一条
# recent·add（role=user、meta 带 session/turn）→ 读 <mem_root>/_state_events.jsonl。
# 返回 dict：token_ok / ledger_exists / events / actors / bad_rows / rc / note。
# 任何子进程异常都回落成字段而非抛出（本函数只供 S8 判据取值）。
def _l2_write_probe(python_exe, pkg_dir, mem_root, aux_dir, state_dir, data_dir):
    env = _sealed_env(mem_root, aux_dir, state_dir, data_dir)
    out = {"token_ok": False, "ledger_exists": False, "events": 0,
           "actors": [], "bad_rows": None, "rc": None, "note": ""}
    # ① 签凭据（--ops-allow recent：只给写窗口所需的最小 op 面）
    proc = _run([python_exe, "-X", "utf8", "-m", "md_cg.tokens", "issue",
                 "--role", "recorder", "--actor", "publish-smoke",
                 "--clearance", "internal", "--ops-allow", "recent,write"],
                pkg_dir, env, PROBE_TIMEOUT)
    if proc is None or proc.returncode != 0:
        out["note"] = "签发写入凭据失败（rc=%s）：%s" % (
            None if proc is None else proc.returncode,
            _stderr_tail(None if proc is None else (proc.stderr or proc.stdout), 3))
        return out
    token = None
    # tokens issue 的输出是**缩进的多行 JSON**（不是单行）——先整体解析，失败再逐行兜底。
    raw = proc.stdout or ""
    candidates = []
    try:
        candidates.append(json.loads(raw))
    except ValueError:
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                candidates.append(json.loads(line))
            except ValueError:
                continue
    for obj in candidates:
        if isinstance(obj, dict) and isinstance(obj.get("token"), str):
            token = obj["token"]
            break
    if not token:
        out["note"] = "tokens issue 返回 0 但取不到 token 字段"
        return out
    out["token_ok"] = True

    # ② 真发一条 recent·add（走与 DSH/zcode 两端共用的那个分支）
    env2 = dict(env)
    env2["MDCG_TOKEN"] = token
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                    "clientInfo": {"name": "publish-smoke-l2", "version": "1.0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "cg", "arguments": {
             "op": "recent", "action": "add", "role": "user",
             "text": L2_PROBE_TEXT,
             "meta": {"session": L2_PROBE_SESSION, "turn": L2_PROBE_TURN}}}},
    ]
    payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in requests)
    proc = _run([python_exe, "-X", "utf8", "-m", "md_cg.mcp_server"], pkg_dir,
                env2, HANDSHAKE_TIMEOUT, stdin_payload=payload)
    if proc is None:
        out["note"] = "recent·add 进程起不来"
        return out
    out["rc"] = proc.returncode
    replies = _parse_replies(proc.stdout)
    added = replies.get(2) or {}
    res = added.get("result") if isinstance(added.get("result"), dict) else {}
    if added.get("error") or res.get("isError"):
        detail = added.get("error") or res
        out["note"] = "recent·add 被判负：%s" % (json.dumps(detail, ensure_ascii=False)[:200],)
        return out

    # ③ 读台账（判据面：文件在 + 至少 1 条 + 记账人可甄别）
    led = os.path.join(mem_root, "_state_events.jsonl")
    out["ledger_exists"] = os.path.isfile(led)
    if not out["ledger_exists"]:
        out["note"] = ("按 recent·add 写入后台账文件未生成 —— 记账链在装机侧没跑"
                       "（抽取器缺失 / 接线未挂 / 开关被关，三者之一）")
        return out
    rows, bad = [], 0
    try:
        with open(led, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    bad += 1
    except OSError as exc:
        out["note"] = "台账读不动：%r" % (exc,)
        return out
    out["events"] = len(rows)
    out["bad_rows"] = bad
    out["actors"] = sorted({str(r.get("actor")) for r in rows if isinstance(r, dict)})
    out["rows"] = rows
    return out


# 生效条件：python_exe/pkg_dir/四根同 _l2_write_probe，且台账至少有 1 条时，读侧两验：
# ① `python -m md_cg.state_slots --status` 的 events 数；② stg(op=state_chain) 对台账里
# 头一条事件的 (subject, slot) 查 count。返回 dict：slots_events / chain_count / note。
def _l2_read_probe(python_exe, pkg_dir, mem_root, aux_dir, state_dir, data_dir, rows):
    env = _sealed_env(mem_root, aux_dir, state_dir, data_dir)
    out = {"slots_events": None, "chain_count": None, "note": ""}
    proc = _run([python_exe, "-X", "utf8", "-m", "md_cg.state_slots", "--status"],
                pkg_dir, env, PROBE_TIMEOUT)
    if proc is not None and proc.returncode == 0:
        try:
            out["slots_events"] = json.loads((proc.stdout or "").strip()).get("events")
        except ValueError:
            out["note"] = "state_slots --status 输出不可解析"
    else:
        out["note"] = "state_slots --status rc=%s" % (None if proc is None else proc.returncode)

    first = next((r for r in rows if isinstance(r, dict) and r.get("slot")), None)
    if not first:
        out["note"] = (out["note"] + "；" if out["note"] else "") + "台账里没有带 slot 的事件"
        return out
    env2 = dict(env)
    env2["MDCG_STG_STATE"] = "1"      # 查询面缺省关，读侧探针须显式打开
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                    "clientInfo": {"name": "publish-smoke-l2r", "version": "1.0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "stg", "arguments": {
             "op": "state_chain", "subject": first.get("subject"),
             "slot": first.get("slot"), "include_retired": True, "history": True}}},
    ]
    payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in requests)
    proc = _run([python_exe, "-X", "utf8", "-m", "md_cg.mcp_server"], pkg_dir,
                env2, HANDSHAKE_TIMEOUT, stdin_payload=payload)
    if proc is None:
        out["note"] = (out["note"] + "；" if out["note"] else "") + "state_chain 进程起不来"
        return out
    replies = _parse_replies(proc.stdout)
    got = replies.get(2) or {}
    res = got.get("result") if isinstance(got.get("result"), dict) else {}
    body = res.get("content") if isinstance(res, dict) else None
    if isinstance(body, list) and body and isinstance(body[0], dict):
        try:
            inner = json.loads(body[0].get("text") or "{}")
        except ValueError:
            inner = {}
        if isinstance(inner, dict):
            out["chain_count"] = inner.get("count")
    return out


# 生效条件：root 指向含 package.json 的目录且其 name 为非空字符串时返回该 name（含 scope，
# 如 "@furongjun1999/dsh-memory"）；文件缺失/JSON 非法/name 缺失或非字符串返回 None。
def _pkg_name(root):
    try:
        with open(os.path.join(root, "package.json"), encoding="utf-8") as fh:
            pj = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(pj, dict) or not isinstance(pj.get("name"), str) or not pj["name"].strip():
        return None
    return pj["name"].strip()


# 生效条件：root 指向含 package.json 的目录时返回其 version（str，缺则空串）；任何读取/
# 解析异常一律回落空串（只用于握手自报版本的对齐判据，读不通由 S4 判负）。
def _pkg_version(root):
    try:
        with open(os.path.join(root, "package.json"), encoding="utf-8") as fh:
            pj = json.load(fh)
    except (OSError, ValueError):
        return ""
    if isinstance(pj, dict) and isinstance(pj.get("version"), str):
        return pj["version"]
    return ""


def _stderr_tail(text, n=8):
    lines = [l for l in (text or "").splitlines() if l.strip()]
    return "\n".join("        | " + l for l in lines[-n:])


# 生效条件：report 为 Report、summary 为读数字典、code 为拟定退出码时，打印结论行与
# 末行 machine-readable SMOKE_JSON（verdict/fails/…）并返回 code。
def _finish(report, summary, code, keep, sandbox):
    if sandbox is None:
        print("  沙箱：未创建（本腿在解析 npm 之前就退出）")
    elif keep:
        print("  沙箱保留：%s（MDCG_GATE_SANDBOX_DIR 指定）" % sandbox)
    else:
        shutil.rmtree(sandbox, ignore_errors=True)
        print("  沙箱已清理：%s（缺省临时目录）" % sandbox)
    print("=== 结论 ===")
    print("  判据失败数=%d（%s）" % (len(report.fails), "；".join(report.fails) or "无"))
    summary["verdict"] = "PASS" if code == 0 else "FAIL"
    # 环境错误（code=2）与判据红（code=1）分开记账：前者「本腿没跑成」，后者「跑成了但判负」
    summary["env_error"] = code == 2
    summary["fails"] = list(report.fails)
    summary["exit_code"] = code
    summary["sandbox"] = sandbox
    summary["sandbox_kept"] = bool(keep)
    print("VERDICT=%s" % summary["verdict"])
    print("SMOKE_JSON " + json.dumps(summary, ensure_ascii=False))
    return code


def parse_args(argv):
    parser = argparse.ArgumentParser(description="出货面冒烟发布门禁（pack → 空沙箱真装 → 真握手）")
    parser.add_argument("--root", default=None, help="仓库根目录，默认由脚本位置推导")
    return parser.parse_args(argv)


def _force_utf8_stdio():
    """Windows 控制台默认 GBK：本脚本会打印 ⇒/→ 等字符，必须强制 UTF-8。

    与仓库纪律「命令执行统一走 python + PYTHONUTF8=1」同向：脚本自身兜底，
    不要求调用方记得设环境变量（npm run gate 就是没设的那种）。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv=None):
    _force_utf8_stdio()
    args = parse_args(argv)
    root = os.path.abspath(args.root or _REPO)
    report = Report()
    summary = {"root": root}
    print("=== 0) 对象 ===")
    print("  root=%s" % root)
    if not os.path.isdir(root):
        print("[环境错误] 仓库根目录不存在：%s" % root)
        return 2

    # ---- S0：npm 解析单点（复用 check_publish_artifact，不写第二套方言）----
    try:
        cpa = _load_publish_artifact()
        npm = cpa.resolve_npm()
    except Exception as exc:                       # noqa: BLE001 —— 单点不可得即环境错误
        print("[环境错误] 无法加载 npm 解析单点（scripts/check_publish_artifact.py）：%r" % (exc,))
        return 2
    found = shutil.which(npm)
    print("  npm 单点：check_publish_artifact.resolve_npm() → %r（which=%s）" % (npm, found))
    if not found:
        report.rule("S0 npm 可执行面可解析", False,
                    "本机探不到 %r —— 本腿 fail-closed（不静默 SKIP；装好 npm 或把 "
                    "npm 加入 PATH 后重跑）" % npm)
        return _finish(report, summary, 1, keep=False, sandbox=None)

    pkg_name = _pkg_name(root)
    if not pkg_name:
        print("[环境错误] 读不到 package.json 的 name（无法定位装好的包目录）：%s" % root)
        return 2
    pkg_version = _pkg_version(root)

    sandbox, keep = _make_sandbox(os.environ.get("MDCG_GATE_SANDBOX_DIR", ""))
    pack_dir = os.path.join(sandbox, PACK_SUBDIR)
    install_dir = os.path.join(sandbox, INSTALL_SUBDIR)
    mem_root = os.path.join(sandbox, ROOT_LEAF)
    aux_dir = os.path.join(sandbox, AUX_LEAF)
    state_dir = os.path.join(sandbox, STATE_LEAF)
    data_dir = os.path.join(sandbox, DATA_LEAF)
    # 只清本腿自己的子目录（给定沙箱可能被复用；名字固定且专属本腿）
    for d in (pack_dir, install_dir, mem_root, aux_dir, state_dir, data_dir):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)

    # ---- ① npm pack（真产物，不是 --dry-run）----
    print("=== 1) 打包（npm pack 真产物）===")
    proc = _run([npm, "pack", "--pack-destination", pack_dir], root, _base_env(), NPM_TIMEOUT)
    if proc is None or proc.returncode != 0:
        print("[环境错误] npm pack 未产出 tarball（rc=%s）"
              % (None if proc is None else proc.returncode))
        print(_stderr_tail(None if proc is None else proc.stderr))
        return _finish(report, summary, 2, keep, sandbox)
    tgzs = sorted(f for f in os.listdir(pack_dir) if f.endswith(".tgz"))
    if not tgzs:
        print("[环境错误] npm pack 已返回 0 但 %s 下没有 .tgz" % pack_dir)
        print(_stderr_tail(proc.stdout))
        return _finish(report, summary, 2, keep, sandbox)
    tgz = os.path.join(pack_dir, tgzs[-1])
    members = _tarball_members(tgz)
    if members is None:
        return _finish(report, summary, 2, keep, sandbox)
    print("  出货清单：条目=%d（文件）tarball=%s" % (len(members), os.path.basename(tgz)))
    summary["manifest_entries"] = len(members)
    summary["tarball"] = os.path.basename(tgz)
    shipped = set(members)
    summary["has_utf8_boot"] = "utf8_boot.py" in shipped
    if not report.rule("S1 出货清单含仓根 utf8_boot.py", "utf8_boot.py" in shipped,
                       "" if "utf8_boot.py" in shipped
                       else "清单里没有顶层 utf8_boot.py —— 仓里在、包里不在，"
                            "装机即挂（md_cg/mcp_server.py 的 from utf8_boot import ensure_utf8）"):
        print("         修法：files 加 utf8_boot.py（package.json 的 files 白名单加回该项）")

    # ---- ② 空沙箱真装 ----
    print("=== 2) 空沙箱安装（npm install <tgz>）===")
    with open(os.path.join(install_dir, "package.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"name": "mdcg-publish-smoke", "private": True}, indent=2) + "\n")
    proc = _run([npm, "install", tgz, "--no-audit", "--no-fund", "--legacy-peer-deps"],
                install_dir, _base_env(), NPM_TIMEOUT)
    installed_pkg = os.path.join(install_dir, "node_modules", *pkg_name.split("/"))
    install_ok = proc is not None and proc.returncode == 0 and os.path.isdir(installed_pkg)
    if not install_ok:
        print(_stderr_tail(None if proc is None else proc.stderr))
    print("  装好的目录=%s（rc=%s）" % (installed_pkg, None if proc is None else proc.returncode))
    summary["installed_dir"] = installed_pkg
    have_boot = install_ok and os.path.isfile(os.path.join(installed_pkg, "utf8_boot.py"))
    have_server = install_ok and os.path.isfile(
        os.path.join(installed_pkg, "md_cg", "mcp_server.py"))
    summary["installed_has_utf8_boot"] = have_boot
    summary["installed_has_mcp_server"] = have_server
    report.rule("S2 装好的目录含 utf8_boot.py", have_boot,
                "" if have_boot
                else ("安装未成功" if not install_ok
                      else "装机目录里没有 utf8_boot.py —— 装机即挂（与出货清单同族）"))
    report.rule("S3 装好的目录含 md_cg/mcp_server.py", have_server,
                "" if have_server
                else ("安装未成功" if not install_ok else "装机目录里没有 md_cg/mcp_server.py"))

    # ---- ②.5 懒加载数据面：装机后「模块能不能解析出它的数据」 ----
    # 与 S1/S2/S3 同族（都是拦「仓库里在、包里不在」），但**判据更强**：不看某个
    # 文件名在不在，而是真起一个解释器 import 该模块、问它数据解析成功没有。
    # 第三例复发（前两例见 issue #38 / #48「出货面缺件」）：
    #   `md_cg/units.py` 在**模块导入时**按「本文件上溯两级 + hive/id_charset_blocks.txt」
    #   读字符集表（三处读者共读的唯一真源），而 package.json 的 files 白名单不含
    #   `hive/` ⇒ 装机后该表不可读、解析 fail-closed（区间集为空 ⇒ 一切 job_id 判
    #   False）。**这一例比前两例隐蔽**：它不阻塞进程启动、记忆功能照常（不像 #48
    #   那样 `ModuleNotFoundError` 让插件起来即退），只在走到 cg(op=ccg, action=units)
    #   这条委派链时静默失效——故必须由本腿点名。
    charset_err = None
    charset_ranges = None
    charset_ok = False
    charset_detail = "安装未成功，无从探测"
    if install_ok:
        probe = (
            "import sys, json\n"
            "sys.path.insert(0, %r)\n"
            "import md_cg.units as u\n"
            "print(json.dumps({'err': u.CHARSET_BLOCKS_ERROR,"
            " 'n': len(u.CHARSET_BLOCKS)}))\n" % installed_pkg)
        proc_probe = _run([sys.executable, "-X", "utf8", "-c", probe],
                          installed_pkg, _base_env(), PROBE_TIMEOUT)
        if proc_probe is None:
            charset_detail = "探测进程起不来（解释器不可执行或超时）"
        elif proc_probe.returncode != 0:
            charset_detail = ("探测进程 rc=%s（md_cg.units 导入即失败）：%s"
                              % (proc_probe.returncode, _stderr_tail(proc_probe.stderr, 4)))
        else:
            try:
                payload = json.loads((proc_probe.stdout or "").strip().splitlines()[-1])
                charset_err = payload.get("err")
                charset_ranges = payload.get("n")
            except (ValueError, IndexError) as exc:
                charset_detail = "探测输出不可解析：%s" % exc
            if charset_ranges is not None:
                charset_ok = (charset_err is None and isinstance(charset_ranges, int)
                              and charset_ranges > 0)
                if charset_ok:
                    charset_detail = ""
                else:
                    charset_detail = ("装机后字符集表不可用（ranges=%r err=%r）——"
                                      "job_id 闸 fail-closed 会判一切 id 为 False"
                                      % (charset_ranges, charset_err))
    summary["charset_blocks_error"] = charset_err
    summary["charset_blocks_ranges"] = charset_ranges
    if not report.rule("S7 装机后 md_cg/units.py 的字符集表可解析（懒加载数据面）",
                       charset_ok, charset_detail):
        print("         修法：files 加 hive/id_charset_blocks.txt"
              "（package.json 的 files 白名单收录该数据文件）")

    # ---- ③ 真启动 + 真握手 ----
    print("=== 3) 真启动 + 真握手（stdlib MCP：initialize / notifications/initialized / tools/list）===")
    print("  env：剔除继承来的全部 MDCG_*/DEEPSEEK_* 后注入 MDCG_ROOT=%s · MDCG_AUX_ROOT=%s"
          % (mem_root, aux_dir))
    print("       · MDCG_STATE_ROOT=%s · MDCG_DATA_ROOT=%s（四根全在沙箱 ⇒ 密闭）"
          % (state_dir, data_dir))
    handshake_ok = False
    tools = None
    server_info = None
    policy_source = None
    policy_path = None
    if install_ok:
        proc = _handshake(sys.executable, installed_pkg, mem_root, aux_dir, state_dir, data_dir)
        if proc is None:
            print("[环境错误] 握手进程起不来（解释器不可执行或超时）")
            report.rule("S4 真握手成功（initialize → serverInfo；tools/list → tools）", False,
                        "握手进程起不来")
            report.rule("S5 tools 面 == 缺省面 ['cg','stg']", False, "无从取 tools")
        else:
            replies = _parse_replies(proc.stdout)
            init = replies.get(1) or {}
            server_info = ((init.get("result") or {}).get("serverInfo")
                           if isinstance(init.get("result"), dict) else None)
            handshake_ok = (proc.returncode == 0 and isinstance(server_info, dict)
                            and server_info.get("name") == SERVER_NAME
                            and server_info.get("version") == pkg_version)
            detail = ""
            if not handshake_ok:
                detail = ("握手未成功：rc=%s serverInfo=%r（期望 name=%s version=%s）"
                          % (proc.returncode, server_info, SERVER_NAME, pkg_version))
            report.rule("S4 真握手成功（initialize → serverInfo；tools/list → tools）",
                        handshake_ok, detail)
            tl = replies.get(2) or {}
            tresult = tl.get("result") if isinstance(tl.get("result"), dict) else {}
            raw_tools = tresult.get("tools") if isinstance(tresult, dict) else None
            if isinstance(raw_tools, list):
                tools = [t.get("name") for t in raw_tools if isinstance(t, dict)]
            summary["serverInfo"] = server_info
            summary["tools"] = tools
            summary["handshake_rc"] = proc.returncode
            print("  serverInfo=%s" % json.dumps(server_info, ensure_ascii=False))
            print("  tools=%s" % json.dumps(tools, ensure_ascii=False))
            if not handshake_ok:
                print(_stderr_tail(proc.stderr))
            report.rule("S5 tools 面 == 缺省面 ['cg','stg']",
                        tools == list(DEFAULT_TOOLS),
                        "" if tools == list(DEFAULT_TOOLS) else "实得 tools=%r" % (tools,))
            # ---- ④ 策略来源（NOTE，恒不判负）----
            blob = (proc.stderr or "") + (proc.stdout or "")
            for line in blob.splitlines():
                if "写入策略：来源=" in line:
                    policy_source = line.split("来源=", 1)[1].split(" ", 1)[0].strip()
                    if "path=" in line:
                        policy_path = line.split("path=", 1)[1].split("（", 1)[0].strip()
                    break
            summary["policy_source"] = policy_source
            summary["policy_path"] = policy_path
            if policy_source == "package_default" and policy_path:
                inside = os.path.normcase(policy_path).startswith(
                    os.path.normcase(os.path.join(installed_pkg, "data")))
                report.note("S6 启动 stderr 的策略来源：来源=%s path=%s（包内件=%s）"
                            % (policy_source, policy_path, "是" if inside else "否"))
            else:
                report.note("S6 启动 stderr 未见「写入策略：来源=」证据（来源=%r）——"
                            "本项只记录不判负" % (policy_source,))
    else:
        report.rule("S4 真握手成功（initialize → serverInfo；tools/list → tools）", False,
                    "安装未成功，无从启动")
        report.rule("S5 tools 面 == 缺省面 ['cg','stg']", False, "安装未成功，无从取 tools")

    summary["handshake_ok"] = handshake_ok

    # ---- ⑤ L2 状态台账端到端（S8 写侧 / S9 读侧）----
    # 为什么本腿必须真跑一次 recent·add：S1–S3 只证「件在包里」，S7 只证「数据能解析」，
    # 全都是**静态面**。上一轮的真缺陷恰恰是静态面全绿而链路不通——抽取器本体在
    # `scripts/`（不随包）⇒ 装机侧 `_state_events.jsonl` 长期不存在。判据必须落在
    # **行为**上：发一条用户轮，看台账里有没有落进一条可甄别的记录。
    # 判据面取「至少 1 条 且 actor=state_extract」——不钉具体槽位/值，避免把发布闸
    # 耦合到抽取规则表（规则演进不该让发布闸变红；抽不到的回归由 md_cg 层守卫管）。
    l2_write = {}
    l2_read = {}
    if install_ok and handshake_ok:
        print("=== 5) L2 状态台账端到端（签凭据 → 真发 recent·add → 读台账 → 投影/查询面回读）===")
        l2_write = _l2_write_probe(sys.executable, installed_pkg,
                                   mem_root, aux_dir, state_dir, data_dir)
        led_ok = (l2_write.get("ledger_exists") and (l2_write.get("events") or 0) >= 1
                  and "state_extract" in (l2_write.get("actors") or []))
        s8_detail = ""
        if not led_ok:
            s8_detail = l2_write.get("note") or (
                "台账已生成但无 state_extract 记账（events=%r actors=%r bad_rows=%r）"
                % (l2_write.get("events"), l2_write.get("actors"),
                   l2_write.get("bad_rows")))
        if not report.rule("S8 装机后 recent·add 真落台账（至少 1 条 actor=state_extract）",
                           led_ok, s8_detail):
            print("         修法：确认 md_cg/state_extract.py 随包（R9a 管的）、"
                  "mcp_server 的 recent·add 分支挂着抽取、且 MDCG_STATE_EXTRACT 未被关")
        if led_ok:
            l2_read = _l2_read_probe(sys.executable, installed_pkg,
                                     mem_root, aux_dir, state_dir, data_dir,
                                     l2_write.get("rows") or [])
            n = l2_write.get("events")
            s9_ok = (l2_read.get("slots_events") == n
                     and (l2_read.get("chain_count") or 0) >= 1)
            s9_detail = ""
            if not s9_ok:
                s9_detail = ("投影/查询面与台账不一致：台账 events=%r，"
                             "state_slots --status events=%r，state_chain count=%r%s"
                             % (n, l2_read.get("slots_events"), l2_read.get("chain_count"),
                                ("；" + l2_read["note"]) if l2_read.get("note") else ""))
            report.rule("S9 台账读得回来（state_slots 投影数 == 台账数 且 state_chain 可查）",
                        s9_ok, s9_detail)
        else:
            report.rule("S9 台账读得回来（state_slots 投影数 == 台账数 且 state_chain 可查）",
                        False, "S8 未过，无从回读")
    else:
        report.rule("S8 装机后 recent·add 真落台账（至少 1 条 actor=state_extract）",
                    False, "安装/握手未成功，无从探测记账链")
        report.rule("S9 台账读得回来（state_slots 投影数 == 台账数 且 state_chain 可查）",
                    False, "安装/握手未成功，无从回读")
    summary["l2_ledger_exists"] = l2_write.get("ledger_exists", False)
    summary["l2_events"] = l2_write.get("events", 0)
    summary["l2_actors"] = l2_write.get("actors", [])
    summary["l2_slots_events"] = l2_read.get("slots_events")
    summary["l2_chain_count"] = l2_read.get("chain_count")

    code = 1 if report.fails else 0
    return _finish(report, summary, code, keep, sandbox)


if __name__ == "__main__":
    sys.exit(main())
