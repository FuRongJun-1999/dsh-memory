# -*- coding: utf-8 -*-
"""units.py · 复核单元接线层：蜂巢优先 → 提示配置 → harness 端子代理降级。

定位（与 audit.py 同一条架构约束）：**能力不在认知图内**。本模块不做智能判定，
只做三件事：选通道（probe/plan）→ 派发请求（submit/wait/run）→ 记账（_units.jsonl）。

使用者裁定（2026-09-16，第 17 条精神）：编译器（ccgc）的复核**优先使用蜂巢的
反思单元 / 验证单元**（reflect / verify，与 crosscheck.REFLECT_UNIT/VERIFY_UNIT 同值，
不新造角色名）；蜂巢不可用 → **提示使用者配置**（给出可照做的构建/启动/环境变量命令）；
或经显式 allow_degrade=True 降级到 **harness 端子代理**（宿主 agent 派发，裁决经
crosscheck 同款 verdicts 通道回填）。理由：使用者的复核是昂贵的——重活交给可并行的
外部单元，agent 本体只做编排与记账。

蜂巢契约（真源 hive/README.md + hive/hive_mcp/mcp_server.py；**复制契约不 import**，
保持 md_cg 对 hive 零依赖，与 ccgc「同款语义就地实现防 import 环」惯例一致）：
    jobs 目录   = $HIVE_JOBS_DIR | <repo>/hive/jobs
    serve 判活  = **三层**：jobs/_serve.json 的 ts（毫秒）距今 < FRESH_S(15s)
                  ∧ pid 存活 ∧ 该 pid 是本程序
                  （同 hive/serve_start.serve_alive；四路口径由
                   hive/test_serve_entry.py 机械守卫）
    job 目录    = jobs/<job_id>/{spec.json,status.json,result.json,kill}
    job_id      = 本模块自造旧形态 h<java_ms>_<uuid6>（`_job_id`，**不是** `_submit` 同款）；
                  hive 提交面自 id 契约 v2（B8）起为四槽 h_<身份>_<任务>_<单元>_<编号>，由
                  Rust 侧 `hive alloc-id` 分配——两形态都过 job.rs::valid_job_id（存量零迁移）
    id 字符判据 = **区块白名单**：唯一真源 hive/id_charset_blocks.txt 的区间并集
                  （[`_valid_job_id`]；本模块**读这份数据文件**、不 import hive，
                  与 job.rs / mcp_server.py 三处共读同一份 ⇒ 不查任何 Unicode 属性库，
                  两侧版本差结构性不可能）。本闸**有意保留**两处放宽（既有对外契约）：
                  不要求 h 前缀、允许 `-`；拒收面（零宽/双向控制/控制字符/路径成分/尾点/
                  首尾空白/Windows 保留设备名）逐条显式断，不靠「白名单外顺带拒」。
    result.json = {"ok":true,"content":...} | {"ok":false,"error":...}
    终态        = done | error | timeout | killed
    拉起 serve  = <repo>/hive/target/release/hive serve --jobs <jobs>（detached）

边界（诚实声明，不猜测）：
    · 本模块**不产生裁决**，只搬运；裁决由外部单元负责。
    · 契约漂移：hive 侧协议若变更，本模块以「无 result / 超时」如实失败，不假装成功。
    · 默认**不自动拉起 serve**（使用者裁定：不可用即提示配置）；autostart=True 才拉起。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid

HIVE, SUBAGENT, CONFIGURE = "hive", "subagent", "configure"
STATES = (HIVE, SUBAGENT, CONFIGURE)

REFLECT, VERIFY = "reflect", "verify"      # 同 crosscheck.REFLECT_UNIT/VERIFY_UNIT
ROLES = (REFLECT, VERIFY)

SERVE_FILE, SPEC_FILE = "_serve.json", "spec.json"
STATUS_FILE, RESULT_FILE, KILL_FILE = "status.json", "result.json", "kill"
LOG_NAME = "_units.jsonl"
TERMINAL_STATES = ("done", "error", "timeout", "killed")
#: serve 心跳新鲜窗口（秒）。**须与 hive/serve_start.FRESH_S 同值**——本模块
#: 只持有「判活的第 4 处实现」（复制契约不 import hive），阈值/判据结构若与
#: 权威漂移，会在通道选择面复现 v13 的「假存活」病类（v14 缺陷 E：
#: 旧值 5.0 vs 权威 15，serve 崩溃后 ≤5s 窗口内判「存活」→ 选 hive 通道 →
#: 提交的 job 永远无人处理）。守卫：hive/test_serve_entry.py。
FRESH_S, DEFAULT_TIMEOUT_S, DEFAULT_POLL_S = 15.0, 120, 1.0
#: 复核委派的 completion 预算。**必须对齐统一默认（文档：最大输出 200000）**——
#: 该模型 reasoning 与正文**共享 completion 预算**，小预算会把正文吃光并静默返回空正文：
#: 实测 2048 → reasoning 2048 / content 空；16384 → 时好时坏；200000 → 正常出裁决。
DEFAULT_MAX_TOKENS = 200000

ENV_JOBS_DIR, ENV_EXE = "HIVE_JOBS_DIR", "HIVE_EXE"
ENV_MODEL, ENV_API_KEY = "MDCG_UNIT_MODEL", "HIVE_API_KEY"

ACCEPT, REJECT, DEFER, BLINDSPOT = "ACCEPT", "REJECT", "DEFER", "BLINDSPOT"
_VERDICT_MAP = {
    "accept": ACCEPT, "accepted": ACCEPT, "keep": ACCEPT, "pass": ACCEPT,
    "ok": ACCEPT, "approve": ACCEPT,
    "drop": REJECT, "reject": REJECT, "rejected": REJECT, "deny": REJECT, "fail": REJECT,
    "defer": DEFER, "deferred": DEFER, "unsure": DEFER, "unclear": DEFER, "skip": DEFER,
    "blindspot": BLINDSPOT, "blind": BLINDSPOT,
}


# 生效条件：无入参，恒返回模块 `__file__` 绝对路径上溯两级的目录（md_cg 的上一级），与 cwd 无关。
def repo_root() -> str:
    """仓库根（md_cg 的上一级）；不用 cwd——cwd 由宿主决定，不可作判据。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# 生效条件：explicit 为真值时 d=explicit；explicit 为空串等假值而 ENV_JOBS_DIR 有真值时 d=该环境变量；两者皆假值时 d=repo_root()/hive/jobs；最终返回 os.path.abspath(d)。
def jobs_dir(explicit: str = "") -> str:
    d = explicit or os.environ.get(ENV_JOBS_DIR) or os.path.join(repo_root(), "hive", "jobs")
    return os.path.abspath(d)


# 生效条件：ENV_EXE 有真值时原样返回该值；ENV_EXE 缺失或为空串时返回 repo_root()/hive/target/release/ 下按 os.name=="nt" 取 hive.exe、否则取 hive 的拼接路径。
def exe_path() -> str:
    exe = os.environ.get(ENV_EXE)
    if exe:
        return exe
    return os.path.join(repo_root(), "hive", "target", "release",
                        "hive.exe" if os.name == "nt" else "hive")


# 生效条件：explicit 为真值时取 explicit，否则取 ENV_MODEL，两者皆假值时按空串，返回该结果 strip() 后的字符串（可为空串）。
def model_name(explicit: str = "") -> str:
    """复核模型（LLM 委托型执行器的 spec.model 必填）。"""
    return (explicit or os.environ.get(ENV_MODEL) or "").strip()


# 生效条件：pid 为 int 且大于 0 时（否则 False），os.name 为 "nt" 时返回 _tasklist_row(pid) 是否非 None，非 "nt" 时 os.kill(pid, 0) 不抛 OSError 返回 True、抛 OSError 返回 False。
def pid_alive(pid) -> bool:
    """该 pid **号**是否存在（Windows tasklist 精确列比对 / unix `kill -0`）。

    只回答「这个号有没有进程」——**不足以判定「serve 还在跑」**（见
    `pid_is_self_program`）。实现与 hive/serve_start.pid_alive 同口径。
    """
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        return _tasklist_row(pid) is not None
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# 生效条件：对传入 pid 执行 tasklist /FO CSV 后，在其 stdout 中遇到的第一个按 '","' 切分、列数≥2 且第 2 列 strip 再 strip('"') 后等于 str(pid) 的行即返回 [映像名, pid 字符串]，无此行或 subprocess.run 抛 OSError 时返回 None。
def _tasklist_row(pid):
    """Windows：查该 pid 的 tasklist 行 → [映像名, pid 字符串]；查不到返回 None。

    按列精确比对，**不用子串包含**——子串会让 pid=441 被 4410 命中（假存活）。
    """
    try:
        # 显式 utf-8 + replace：只消费 ASCII 的 pid 列，但**不依赖 locale**——
        # locale 口径与「后代写 UTF-8」不一致时读线程会崩（见 test_subproc_encoding.py）。
        # P2-16（批次 30）：timeout=10——tasklist 挂起曾永久阻塞判活路径。
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in (r.stdout or "").splitlines():
        cols = line.split('","')
        if len(cols) >= 2 and cols[1].strip().strip('"') == str(pid):
            return [cols[0].strip().strip('"'), cols[1].strip().strip('"')]
    return None


# 生效条件：exe_path() 的 basename 小写非空且 pid 为 int 大于 0 时（否则 False），"nt" 下要求 _tasklist_row(pid) 非空且映像名小写等于该 basename，非 "nt" 下要求 /proc/<pid>/cmdline 首个 b"\x00" 前 token 的 basename 小写等于它（读取抛 OSError 则 False）。
def pid_is_self_program(pid) -> bool:
    """该 pid 是否**就是本程序**（同映像名）——pid 号会被无关进程复用。

    与 hive/serve_start.pid_is_self_program 同口径（复制契约）。零依赖边界：
    拿不到映像名返回 False（宁可放行启动，也不误报「已有 serve 在跑」）。
    """
    want = os.path.basename(exe_path()).lower()
    if not want or not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        row = _tasklist_row(pid)
        return bool(row) and row[0].lower() == want
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            first = f.read().split(b"\x00")[0]
    except OSError:
        return False
    return os.path.basename(first.decode("utf-8", "replace")).lower() == want


# 生效条件：以 jobs_dir(jobs) 下的 SERVE_FILE 为心跳路径——该路径不被 isfile 命中时返回 exists/alive 均 False 的未启动 reason；命中但 open/json.load 抛 OSError 或 ValueError 时返回不可读 reason；解析成功后按**三层判据**（age < fresh_s ∧ pid_alive(pid) ∧ pid_is_self_program(pid)）定 alive，回填 age_s/pid/raw 与逐层明细及失败原因。
def serve_state(jobs: str = "", fresh_s: float = FRESH_S) -> dict:
    """serve 判活：**三层**（心跳新鲜 ∧ pid 存活 ∧ 该 pid 是本程序）。

    与 `hive/serve_start.serve_alive` 同口径（同值 FRESH_S=15s、同三层判据）。
    v14 缺陷 E：旧实现只判 ts 新鲜度且阈值 5s——双漂移，serve 崩溃后
    ≤5s 内判「存活」会让 `probe()` 选 hive 通道（提交的 job 永远无人处理），
    这正是 v13「假存活」病类从守卫面搬到了**通道选择面**。
    """
    jd = jobs_dir(jobs)
    p = os.path.join(jd, SERVE_FILE)
    out = {"jobs_dir": jd, "heartbeat": p, "exists": os.path.isfile(p),
           "alive": False, "age_s": None, "pid": None, "reason": ""}
    if not out["exists"]:
        out["reason"] = "未见 _serve.json 心跳（serve 未启动或 jobs 目录不对）"
        return out
    try:
        with open(p, encoding="utf-8") as f:
            hb = json.load(f)
    except (OSError, ValueError) as exc:
        out["reason"] = "心跳不可读：%s: %s" % (type(exc).__name__, exc)
        return out
    age = time.time() - ((hb.get("ts") or 0) / 1000.0)
    pid = hb.get("pid")
    fresh_ok = age < float(fresh_s)
    pid_ok = pid_alive(pid)
    ident_ok = pid_is_self_program(pid)
    out.update({"age_s": round(age, 3), "pid": pid, "raw": hb,
                "fresh": bool(fresh_ok), "pid_alive": bool(pid_ok),
                "pid_is_self_program": bool(ident_ok)})
    out["alive"] = bool(fresh_ok and pid_ok and ident_ok)
    if out["alive"]:
        out["reason"] = ""
    elif not fresh_ok:
        out["reason"] = "心跳过期 %.1fs（阈值 %ss）——serve 可能已退出" % (age, fresh_s)
    elif not pid_ok:
        out["reason"] = "心跳新鲜但 pid=%s 已不存在——serve 已退出" % (pid,)
    else:
        out["reason"] = ("心跳新鲜且 pid=%s 存活，但该 pid 不属于本程序"
                         "（非 %s）——pid 号被无关进程复用"
                         % (pid, os.path.basename(exe_path())))
    return out


# 生效条件：jobs 仅经 jobs_dir(jobs) 用于填充指引里的 jobs 路径；reason 为假值时文案首行取“serve 未存活”，否则取 reason 原文；返回模板固定嵌入 exe_path() 的目录与路径、ENV_API_KEY、ENV_MODEL、jd、jd 下的 SERVE_FILE 与 int(FRESH_S)。
def setup_hint(jobs: str = "", reason: str = "") -> str:
    """不可用时给使用者看的**配置指引**（含降级指引）——提示即责任，须可照着做。"""
    jd = jobs_dir(jobs)
    return ("蜂巢不可用：%s\n"
            "  [A 配置蜂巢（推荐，第 17 条）]\n"
            "     1) cd %s && cargo build --release\n"
            "     2) set %s=<LLM密钥>\n     3) set %s=<复核模型名>\n"
            "     4) 启动：%s serve --jobs \"%s\"（或 hive_spawn 自动拉起）\n"
            "     判活判据：%s 的 ts 距今 < %ss\n"
            "  [B 降级 harness 端子代理]\n"
            "     重发本请求并带 allow_degrade=true：本模块返回复核请求包（prompt），\n"
            "     由宿主子代理执行后经 verdicts 回填裁决。"
            % (reason or "serve 未存活", os.path.dirname(exe_path()), ENV_API_KEY,
               ENV_MODEL, exe_path(), jd, os.path.join(jd, SERVE_FILE), int(FRESH_S)))


# 生效条件：先取 st=serve_state(jobs, fresh_s) 与 mdl=model_name(model)；st["alive"] 为真且 mdl 非空时返回 state=HIVE；否则 allow_degrade 为真时返回 state=SUBAGENT 且 channel 取 channel 或 "harness-subagent"；否则返回 state=CONFIGURE、transport=None 并附 setup_hint(jobs, why)。
def probe(jobs: str = "", model: str = "", fresh_s: float = FRESH_S,
          allow_degrade: bool = False, channel: str = "") -> dict:
    """三级能力探测：hive（可派发）→ configure（提示配置）→ subagent（显式降级）。

    判据只认**心跳 + 模型名**两项硬前提；缺任一即如实降级，绝不用相似度
    （如「hive 目录存在」）冒充可用（资格由条件证据裁决，不由相似度裁决）。
    """
    st = serve_state(jobs, fresh_s)
    mdl = model_name(model)
    if st["alive"] and mdl:
        return {"state": HIVE, "transport": HIVE, "model": mdl, "jobs_dir": st["jobs_dir"],
                "serve": st, "channel": "", "hint": ""}
    why = st["reason"] if not st["alive"] else "serve 存活但未配置复核模型（%s）" % ENV_MODEL
    if allow_degrade:
        return {"state": SUBAGENT, "transport": SUBAGENT, "model": mdl,
                "jobs_dir": st["jobs_dir"], "serve": st,
                "channel": channel or "harness-subagent",
                "hint": "已按 allow_degrade 降级到 harness 端子代理：请把 prompt 交给宿主子代理，"
                        "裁决经 verdicts 回填（蜂巢不可用原因：%s）" % why}
    return {"state": CONFIGURE, "transport": None, "model": mdl,
            "jobs_dir": st["jobs_dir"], "serve": st, "channel": "",
            "hint": setup_hint(jobs, why)}


# 生效条件：state/transport/model/jobs_dir/serve/channel/hint 全部直接取自 probe(jobs, model, fresh_s, allow_degrade, channel) 的对应键，本函数不另做判活或模型判断，仅在 chain 文案中固定引用 int(FRESH_S) 与 ENV_MODEL。
def plan(jobs: str = "", model: str = "", fresh_s: float = FRESH_S,
         allow_degrade: bool = False, channel: str = "") -> dict:
    """优先级链自描述（供 cg op=ccg action=units 与审计查看）。"""
    p = probe(jobs, model, fresh_s, allow_degrade, channel)
    return {"state": p["state"], "transport": p["transport"], "model": p["model"],
            "jobs_dir": p["jobs_dir"], "serve": p["serve"], "channel": p["channel"],
            "chain": [
                {"order": 1, "transport": HIVE, "action": "派发 reflect/verify 单元并等待 result.json",
                 "when": ("jobs/_serve.json 心跳 < %ss 且（%s 已配置 **或调用方显式传 model**）"
                          % (int(FRESH_S), ENV_MODEL))},
                {"order": 2, "transport": CONFIGURE, "action": "返回配置指引（不自动拉起、不假装通过）",
                 "when": "蜂巢不可用"},
                {"order": 3, "transport": SUBAGENT, "action": "返回复核请求包，由 harness 端子代理执行并回填",
                 "when": "调用方显式 allow_degrade=True"},
            ],
            "hint": p["hint"]}


# ---------------------------------------------------------------- 派发与收取

# 生效条件：无入参，恒返回 "h"+int(time.time()*1000)+"_"+uuid.uuid4().hex 前 6 位组成的字符串。
def _job_id() -> str:
    """本地 id 生成（旧形态 `h<毫秒>_<uuid 前 6 位>`）：serve 侧按 'h' 前缀识别任务目录。

    诚实边界（id 契约 v2 · C2 同类措辞订正）：**本函数已不是 `_submit` 的同款实现**
    ——`hive/hive_mcp/mcp_server.py::_submit` 自 B8 起调 Rust 侧 `hive alloc-id` 分配
    `h_<身份>_<任务>_<单元>_<编号>`，**不再自造 id**；本模块是 md_cg 的复核派发面，
    **不在 B8 点名的改动面**（契约只列 CLI / MCP 提交面 / orch 透传），故保留旧形态。
    旧形态 id 在新契约下**仍然合法**（存量零迁移：`job.rs::valid_job_id` 收），故此处
    不闯闸、不破坏 serve 领取；但它绕过了分配器的独占创建与五单元闭集 ⇒ 与「分配器
    唯一实现在 Rust 侧」（契约 §五 裁决 3）不齐，宜单独裁决（牵动 md_cg 派发/等待链
    语义与其守卫 `md_cg/test_units_poll.py`，不在本批「只论证订正」的范围内）。
    """
    return "h%d_%s" % (int(time.time() * 1000), uuid.uuid4().hex[:6])


# ------------------------------------------------ id 字符判据（区块白名单 · 唯一真源）

#: 区块表数据文件（**唯一真源**，与 `hive/src/job.rs` / `hive/hive_mcp/mcp_server.py`
#: **共读同一份数据**；本模块**读数据文件**而不是 import hive ⇒ 不破零依赖家法）。
_CHARSET_BLOCKS_REL = "hive/id_charset_blocks.txt"
_MAX_CP = 0x10FFFF


# 生效条件：text 为表文件全文时返回区间列表 [(起, 止)]——**唯一解析配方**（与 Rust
# `job.rs::parse_id_charset_blocks`、`mcp_server._parse_charset_blocks` 同一条，不许各写
# 一套）：每行取 `#` 之前部分后 strip；空行跳过；余下 split('-') 两段 int(x, 16)。
# 任一行不合形态 / 越界 / 逆序 / 未归并到最小 / 空表 → 抛 ValueError（fail-closed：
# 绝不静默跳过坏行——跳过一行的表是另一张表，三处读者随即不同判）。
def _parse_charset_blocks(text: str) -> list:
    """区块表解析（唯一配方）。"""
    out: list = []
    for lineno, line in enumerate(text.split("\n"), 1):
        body = line.split("#", 1)[0].strip()
        if not body:
            continue
        parts = body.split("-")
        if len(parts) != 2:
            raise ValueError("区块表第 %d 行不是 LO-HI 形态：%r" % (lineno, line))
        lo, hi = int(parts[0], 16), int(parts[1], 16)
        if not (0 <= lo <= hi <= _MAX_CP):
            raise ValueError("区块表第 %d 行区间非法：%r" % (lineno, line))
        if out and lo <= out[-1][1] + 1:
            raise ValueError("区块表第 %d 行未归并到最小（相邻/相交/乱序）：%r"
                             % (lineno, line))
        out.append((lo, hi))
    if not out:
        raise ValueError("区块表解析出空区间集（fail-closed：空表绝不放行）")
    return out


# 生效条件：无入参，返回 (区间表, 错误说明)——文件可读且解析通过 → (tuple 区间表, None)；
# 表缺失 / 不可读 / 解析失败 → ((), 原因)。后两者让判据 fail-closed（对一切字符 False）。
def _load_charset_blocks() -> tuple:
    """**模块导入时读一次**（不做每调用 I/O）；路径基准 = 本文件上溯两级（= 仓根）。"""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "hive", "id_charset_blocks.txt")
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        return (), "%s 不可读：%s" % (_CHARSET_BLOCKS_REL, exc)
    try:
        return tuple(_parse_charset_blocks(text)), None
    except ValueError as exc:
        return (), "%s 解析失败：%s" % (_CHARSET_BLOCKS_REL, exc)


#: 判据数据（模块导入时求值一次）：区间表 + 读取/解析错误（错误非 None ⇒ 判据一律 False）。
CHARSET_BLOCKS, CHARSET_BLOCKS_ERROR = _load_charset_blocks()


# 生效条件：c 为单字符且其码点落在区间表内 → True；表缺失 / 坏行 / 空表 → False
# （fail-closed：绝不放行）。
def _charset_member(c: str) -> bool:
    u = ord(c)
    return any(lo <= u <= hi for lo, hi in CHARSET_BLOCKS)


# Windows 保留设备名（B4 拒收项；与 `job.rs::RESERVED_DEVICE_NAMES`、
# `mcp_server.RESERVED_DEVICE_NAMES` 逐项同集——md_cg 只复制这 22 个常量，**还是读数据
# 而不是 import hive**）。Win32 对**单个路径分量**做设备名解析且**忽略扩展名**
# （`CON.txt` 与 `CON` 同指设备），故比对的是「首个 `.` 之前」部分；比对**ASCII 大小写
# 不敏感**（不用 str.upper()：它的 Unicode 折叠面比 Rust 的 eq_ignore_ascii_case 宽，
# 会让两侧分叉）。
RESERVED_DEVICE_NAMES = (
    "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6",
    "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6",
    "LPT7", "LPT8", "LPT9",
)
_ASCII_UPPER = str.maketrans("abcdefghijklmnopqrstuvwxyz",
                             "ABCDEFGHIJKLMNOPQRSTUVWXYZ")


# 生效条件：s 的「首个 `.` 之前」部分与任一保留设备名 **ASCII 大小写不敏感**相等 → True
# （含 `CON.txt` 这类带扩展名形态）——与 rust `job::is_reserved_device_name` 同判。
def _is_reserved_device_name(s: str) -> bool:
    base = s.split(".")[0].translate(_ASCII_UPPER)
    return base in RESERVED_DEVICE_NAMES


# 生效条件：jid 为 str、长度 1..128、strip() 前后无差异（首尾无空白）、首尾字符都不是
# "."（拒 "."/".."/"..." 与 Win32 会剥尾点的 "abc." 形态）、逐字符过显式拒收集合后落在
# **区块白名单**（[`_charset_member`]，唯一真源 `hive/id_charset_blocks.txt`，与 hive 两侧
# 共读同一份数据）或属结构字符 `_` `-` `.`，且整 id 与其按 `_` 分段的任一段都不是
# Windows 保留设备名、且按 `_` 分段的**任一段都不等于** `.` 或 `..`（c7 段级）时返回 True，
# 否则 False。
def _valid_job_id(jid) -> bool:
    r"""job_id 结构闸（N178，2026-09-28；2026-09-30 字符集判据换面为**区块白名单**）。

    同族家法：`hive/hive_mcp/mcp_server.py::_valid_job_id`、
    `hive/src/job.rs::valid_job_id`（三处**共读同一份区块表**，不是三套常量）。
    本闸**保留**的既有放宽（都是既有对外契约，**不得**为「同口径」收紧）：
      · **不要求 "h" 前缀**——`md_cg/test_units_poll.py` 的 "j_empty"/"j_good"/
        "j_fail" 是本模块对外契约（poll 面向任意宿主派发器写出的 job 目录），前缀
        收紧会误杀；
      · 允许 `-`（hive 侧拒它：不在区块表内、也不是它的结构字符）；
      · 长度上限 128、首尾无空白、首尾非点（拒 "."/".."/"..." 与 "x." 尾点形态）
        一并保留。
    非 str 一律拒（**不** str() 归一：与 legacy P3 同纪律，未校验的强制转换会把对象
    形态洗成合法路径成分）。
    字符类判据 = **区块白名单**（与 hive 两侧同源）——白名单外的一切字符一律拒。
    放宽带来的静默风险**逐条显式挡住**（c9：「isalpha」类判据下 Cf/Cc 天然不入，但
    **不能靠这个**）：零宽 U+200B..U+200F/U+2060/U+FEFF、双向控制
    U+202A..U+202E/U+2066..U+2069、控制字符（C0/DEL/C1）**逐条显式判**；`/` `\` `:`
    与 NUL 同样显式拒（路径成分：相对父段 "../outside"、分隔符、盘符/ADS、绝对路径
    会被 os.path.join 吸附）；Windows 保留设备名（CON/PRN/AUX/NUL/COM1..9/LPT1..9，
    含 `CON.txt` 带扩展名形态与 ASCII 大小写变体）**整 id 与按 `_` 分段的任一段**逐名
    显式拒——旧 ASCII 白名单下 `CON` 这类全字母 id 是**放行**的，故这是本闸换面时
    **收紧**的那一面（与 hive 两侧同集同判，语料 80-84 行逐例钉死）。
    表缺失 / 坏表 ⇒ 判据一律 False（fail-closed，绝不放行）。
    本闸本批**新增收紧**（c7，2026-09-30）：按 `_` 分段的**任一段**等于 `.` 或 `..` 即拒
    ——整串口径下 `h_.._x` / `h_a_.._b` 是被收的；段级是面向重构的纵深加固（段可能被当
    父目录段用），与 hive 两侧同判。范围只加这一条：空段（`h__x`）等形态不动。
    """
    if not isinstance(jid, str) or not jid or len(jid) > 128:
        return False
    if jid != jid.strip():
        return False
    if jid[0] == "." or jid[-1] == ".":
        return False
    for c in jid:
        u = ord(c)
        if u <= 0x1F or 0x7F <= u <= 0x9F or c in "/\\:":
            return False      # 控制字符（C0/DEL/C1，含 NUL）与路径成分（显式判，c9）
        if "\u200b" <= c <= "\u200f" or c in ("\u2060", "\ufeff"):
            return False      # 零宽/不可见注入载体（显式判，c9）
        if "\u202a" <= c <= "\u202e" or "\u2066" <= c <= "\u2069":
            return False      # 双向控制（显式判，c9）
        if c in "_.-":
            continue          # 结构字符：槽分隔符 / 点（首尾点已在上方拒）/ 既有放宽的 `-`
        if not _charset_member(c):
            return False
    # Windows 保留设备名（显式判，c7/c9）：整 id（首个 `.` 之前部分，Win32 忽略扩展名）
    # 与按 `_` 分段的**任一段**（Win32 的设备名解析是按路径分量做的）——与
    # `job.rs::valid_job_id` / `mcp_server._job_id_reject_reason` 同集同判。
    if _is_reserved_device_name(jid):
        return False
    if any(_is_reserved_device_name(seg) for seg in jid.split("_")):
        return False
    # 「. / ..」的**段级**判据（c7，2026-09-30 加固）：按 `_` 分段，任一段等于 `.` 或 `..`
    # 即拒——与 `job.rs::valid_job_id` / `mcp_server._job_id_reject_reason` **三处同判**。
    # 段级而非整串（本面原有的「首尾非点」只挡整串与尾点形态）：id 的段可能被宿主当
    # **目录名**或**父目录段**用（契约 §四.4「目录可作它的父段」）。现场定性：`h_.._x` /
    # `h_a_.._b` 这类「含 `..` 段但不以点结尾」的 id 拼出的路径停在池内、不构成穿越 ⇒
    # 面向重构的纵深加固。范围**只加这一条**：不拒空段（`h__x`）等未被裁定的形态。
    if any(seg in (".", "..") for seg in jid.split("_")):
        return False
    return True


# 生效条件：无入参，返回 job_id 非法的结构化拒绝 dict（ok=False、state="invalid_job_id"、terminal=False、job_dir/content/status 均为 None、error 含非法 id 与本闸口径），字段集与 poll 的返回同构。
def _bad_job_id(job_id, *, where: str) -> dict:
    """非法 job_id 的统一拒答（poll/wait/submit 同构，便于调用方机械判别）。"""
    return {"job_id": job_id, "job_dir": None, "state": "invalid_job_id",
            "terminal": False, "ok": False, "content": None, "status": None,
            "error": ("job_id 非法：%r（%s）——job_id 须为**单个路径分量**：区块白名单"
                      "（hive/id_charset_blocks.txt）内的字母/数字，或结构字符 `_` `-` `.`；"
                      "首尾非点，不含 / \\ : 与控制/零宽/双向控制字符/NUL，"
                      "且整 id 与按 `_` 分段的任一段都不得是 Windows 保留设备名"
                      "（CON/PRN/AUX/NUL/COM1..9/LPT1..9，含 CON.txt 形态）"
                      "（N178：拒 ../victim 型越池读 result.json、"
                      "拒任意目录建目录写 spec.json）" % (job_id, where))}


# 生效条件：cg.root 与 cg.cg.root 都取不到真值时不写、直接返回 None；取到 root 时向 root/LOG_NAME 追加一行 rec（副本，setdefault ts）的 JSON，写入抛 OSError 时被吞掉静默返回 None。
def _log(cg, rec: dict) -> None:
    """留痕 _units.jsonl（对齐 _crosscheck.jsonl / _backfill.jsonl 纪律）。"""
    root = getattr(cg, "root", None) or getattr(getattr(cg, "cg", None), "root", None)
    if not root:
        return
    try:
        rec = dict(rec)
        rec.setdefault("ts", int(time.time() * 1000))
        with open(os.path.join(str(root), LOG_NAME), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


# 生效条件：role 不在 ROLES 时返回 ok=False 的未知角色 error；否则 model_name(model) 为空时返回 ok=False 的未配置复核模型；否则 str(prompt or "").strip() 为空时返回 ok=False 的 prompt 为空；否则落盘前先过 _valid_job_id 结构闸（未过返回 ok=False 的 job_id 非法，**不建目录不写文件**——N178：job_id 来源一旦不是 _job_id()，join 后就是「任意目录 + 生成名」的建目录/写文件原语）；闸过则在 jobs_dir(jobs)/job_id 下写 spec.json 与 status.json（context_files 为真、temperature 非 None、extra 为真时才并入 spec），OSError 时返回 ok=False 的写入失败，全部成功返回 ok=True 与 job_id/job_dir/spec/model。
def submit(*, prompt: str, role: str = REFLECT, model: str = "", system_prompt: str = "",
           context_files=None, timeout_s: int = DEFAULT_TIMEOUT_S,
           max_tokens: int = DEFAULT_MAX_TOKENS, temperature=None, jobs: str = "",
           actor: str = "", extra: dict = None, cg=None) -> dict:
    """写一条 LLM 委托型 job（spec.json + status.json，形态同 _submit）；只写文件不起进程。"""
    if role not in ROLES:
        return {"ok": False, "error": "未知复核角色：%r（可选 %s）" % (role, list(ROLES))}
    mdl = model_name(model)
    if not mdl:
        return {"ok": False, "error": "未配置复核模型：请设 %s 或显式传 model" % ENV_MODEL}
    if not str(prompt or "").strip():
        return {"ok": False, "error": "prompt 为空"}
    jd, job_id = jobs_dir(jobs), _job_id()
    # N178（2026-09-28）：**落盘前**过闸——makedirs 之后再过就等于已经建了目录。
    if not _valid_job_id(job_id):
        return {"ok": False, "job_dir": None, "job_id": job_id,
                "error": _bad_job_id(job_id, where="submit 落点")["error"]}
    d = os.path.join(jd, job_id)
    spec = {"model": mdl, "user_prompt": str(prompt), "system_prompt": str(system_prompt or ""),
            "timeout_s": int(timeout_s), "max_tokens": int(max_tokens),
            "role": role, "unit_role": role}
    if context_files:
        spec["context_files"] = list(context_files)
    if temperature is not None:
        spec["temperature"] = temperature
    if extra:
        spec.update(extra)
    try:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, SPEC_FILE), "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False)
        with open(os.path.join(d, STATUS_FILE), "w", encoding="utf-8") as f:
            json.dump({"job_id": job_id, "state": "pending",
                       "created_ts": int(time.time() * 1000), "started_ts": None,
                       "heartbeat_ts": None, "elapsed_s": 0.0, "timeout_s": int(timeout_s),
                       "model": mdl, "pid": None, "error": None}, f, ensure_ascii=False)
    except OSError as exc:
        return {"ok": False, "job_dir": d,
                "error": "job 写入失败：%s: %s" % (type(exc).__name__, exc)}
    _log(cg, {"action": "submit", "job_id": job_id, "role": role, "model": mdl,
              "timeout_s": int(timeout_s), "actor": actor, "prompt_head": str(prompt)[:200]})
    return {"ok": True, "job_id": job_id, "job_dir": d, "spec": spec,
            "unit_role": role, "model": mdl}


# 生效条件：job_id 先过 _valid_job_id 结构闸（未过返回 state="invalid_job_id" 的结构化拒绝，**不触盘**——N178：修前 "../victim" 会被 join 成池外目录并读出其 result.json 全文）；闸过时 jobs_dir(jobs)/job_id 不是目录返回 state=missing、terminal=False 的目录不存在 error；是目录时读 STATUS_FILE（读失败则 status 置 None）并用其 state 覆盖 state/terminal（state 属 TERMINAL_STATES 才 terminal=True）；RESULT_FILE 被 isfile 命中则 terminal=True、state=st or "done"，解析抛 OSError/ValueError 时提前返回该 error；解析为 dict 时取 ok/content/error/usage/model，且 ok 为真而 content 去空白为空时把 ok 改 False 并写空正文 error，解析为非 dict 时 ok=True 且 content 为原值。
def poll(job_id: str, jobs: str = "") -> dict:
    """读 job 终态视图：**以 result.json 出现为终态主判据**，status.json 仅作辅助。"""
    # N178（2026-09-28）：调用方给的 job_id 是路径成分，**先过闸再 join**。
    # 修前此处无闸，且 `str(job_id or "")` 还会把非 str 洗成合法成分。
    if not _valid_job_id(job_id):
        return _bad_job_id(job_id, where="poll 池路径成分")
    d = os.path.join(jobs_dir(jobs), job_id)
    out = {"job_id": job_id, "job_dir": d, "state": "missing", "terminal": False,
           "ok": False, "content": None, "error": None, "status": None}
    if not os.path.isdir(d):
        out["error"] = "job 目录不存在：%s" % d
        return out
    sp = os.path.join(d, STATUS_FILE)
    if os.path.isfile(sp):
        try:
            with open(sp, encoding="utf-8") as f:
                out["status"] = json.load(f)
        except (OSError, ValueError):
            out["status"] = None
    st = (out["status"] or {}).get("state")
    if st:
        out.update({"state": st, "terminal": st in TERMINAL_STATES})
    rp = os.path.join(d, RESULT_FILE)
    if os.path.isfile(rp):
        out["state"] = st or "done"
        out["terminal"] = True
        try:
            with open(rp, encoding="utf-8") as f:
                res = json.load(f)
        except (OSError, ValueError) as exc:
            out["error"] = "result.json 不可读：%s" % type(exc).__name__
            return out
        if isinstance(res, dict):
            out["ok"] = bool(res.get("ok"))
            out["content"] = res.get("content")
            out["error"] = res.get("error") or out["error"]
            out["usage"] = res.get("usage")
            out["model"] = res.get("model")
            # 空正文**不得报成功**：reasoning 与正文共享 completion 预算，预算不足时
            # job 仍自称 ok 但 content 为空 → 若不拦，会被误读成「复核单元无答复」
            # （假死锁）。run() 早已有同等校验，此处补齐，消除两处口径不一致。
            if out["ok"] and not str(out["content"] or "").strip():
                out["ok"] = False
                out["error"] = ("空正文：job 自称 ok 但 content 为空（多为 reasoning 吃尽"
                                "完成预算；提高 max_tokens，勿把预算不足当通道不可用）")
        else:
            out["ok"], out["content"] = True, res
    return out


# 生效条件：job_id 未过 _valid_job_id 结构闸时**立即**返回 poll 的同一拒绝结构（N178：否则非法 id 会空转满 timeout_s 才超时返回——拒绝不该以等待为代价）；闸过时循环 poll(job_id, jobs)，结果 terminal 为真即补 waited_s 后返回；否则 time.time()-t0 >= float(timeout_s) 时返回 terminal=False、timeout=True 与超时 error；两者皆不满足则 sleep(float(poll_s)) 后重试（timeout_s=0 时首次 poll 非终态即超时返回）。
def wait(job_id: str, *, jobs: str = "", timeout_s: float = DEFAULT_TIMEOUT_S,
         poll_s: float = DEFAULT_POLL_S) -> dict:
    """阻塞等终态；超时如实返回（不假装成功、不强杀 job）。"""
    if not _valid_job_id(job_id):
        # N178（2026-09-28）：fail-fast——复用 poll 的拒绝结构，绝不进轮询。
        return poll(job_id, jobs)
    t0 = time.time()
    while True:
        cur = poll(job_id, jobs)
        if cur.get("terminal"):
            cur["waited_s"] = round(time.time() - t0, 3)
            return cur
        if (time.time() - t0) >= float(timeout_s):
            cur.update({"terminal": False, "timeout": True, "waited_s": round(time.time() - t0, 3),
                        "error": "等待超时 %.0fs（job 仍在 %s）" % (float(timeout_s),
                                                                  cur.get("state"))})
            return cur
        time.sleep(float(poll_s))


# 生效条件：submit(prompt=prompt, role=role, cg=cg, actor=actor, **kw) 的 ok 为假时返回 stage="submit" 的失败 dict（含 **sub）；ok 为真时 wait(sub["job_id"], jobs=kw.get("jobs",""), timeout_s=wait_s)，补 stage="wait"/job_id/unit_role/model，并把 ok 改为 res 的 ok 与 content 同时为真。
def run(*, prompt: str, role: str = REFLECT, cg=None, actor: str = "",
        wait_s: float = DEFAULT_TIMEOUT_S, **kw) -> dict:
    """submit + wait 组合（阻塞式复核，MCP action=review 主路径）。"""
    sub = submit(prompt=prompt, role=role, cg=cg, actor=actor, **kw)
    if not sub.get("ok"):
        return {"ok": False, "stage": "submit", "error": sub.get("error"), **sub}
    res = wait(sub["job_id"], jobs=kw.get("jobs", ""), timeout_s=wait_s)
    res.update({"stage": "wait", "job_id": sub["job_id"], "unit_role": role,
                "model": sub.get("model")})
    res["ok"] = bool(res.get("ok")) and bool(res.get("content"))
    return res


# ---------------------------------------------------------------- 裁决解析与搬运

_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.S)


# 生效条件：raw 是 dict/list 时原样返回；否则取 str(raw or "").strip()，为空串（含 0/False/None 等假值）返回 None；否则依次尝试 _FENCE_RE 第 1 组、整段文本、首个 "{" 到末个 "}" 及首个 "[" 到末个 "]" 的切片，返回首个能 json.loads 成 dict 或 list 的候选；全部失败返回 None。
def _json_of(raw):
    """从单元输出抽第一个 JSON 对象/数组（容忍 ```json 围栏与前后噪声）。"""
    if isinstance(raw, (dict, list)):
        return raw
    text = str(raw or "").strip()
    if not text:
        return None
    cands = []
    m = _FENCE_RE.search(text)
    if m:
        cands.append(m.group(1))
    cands.append(text)
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = text.find(opener), text.rfind(closer)
        if 0 <= i < j:
            cands.append(text[i:j + 1])
    for c in cands:
        try:
            v = json.loads(c)
        except ValueError:
            continue
        if isinstance(v, (dict, list)):
            return v
    return None


# 生效条件：data=_json_of(raw) 为 list 时取 data[0]（仅当它是 dict，否则 None）；非 dict 时返回 verdict=DEFER、parsed=False；dict 时 word 取 verdict/decision/state/result 中首个真值后 strip().lower()，_VERDICT_MAP.get(word) 为 None 时返回 DEFER、parsed=True 并带 corr 与 reason，命中时返回该裁决及 reason、slot_corrections（取自 slot_corrections/corrections，非 dict 则置 {}）、checks、raw 前 500 字符。
def verdict_of(raw) -> dict:
    """单元输出 → 裁决四态；解析不出 → DEFER（不猜测、不当通过）。"""
    data = _json_of(raw)
    if isinstance(data, list):
        data = data[0] if data and isinstance(data[0], dict) else None
    if not isinstance(data, dict):
        return {"verdict": DEFER, "reason": "单元输出无法解析为裁决 JSON",
                "slot_corrections": {}, "raw": str(raw)[:500], "parsed": False}
    word = str(data.get("verdict") or data.get("decision") or data.get("state")
               or data.get("result") or "").strip().lower()
    reason = str(data.get("reason") or data.get("why") or data.get("detail") or "").strip()
    corr = data.get("slot_corrections") or data.get("corrections") or {}
    corr = corr if isinstance(corr, dict) else {}
    got = _VERDICT_MAP.get(word)
    if got is None:
        return {"verdict": DEFER, "slot_corrections": corr, "parsed": True, "raw": str(raw)[:500],
                "reason": "单元未给出可识别的裁决（%r）%s" % (word, ("：" + reason) if reason else "")}
    return {"verdict": got, "reason": reason, "slot_corrections": corr,
            "checks": data.get("checks"), "raw": str(raw)[:500], "parsed": True}


# 生效条件：state==HIVE 时返回 "hive:<role>:<job_id 或 'unknown'>"；state==SUBAGENT 时返回 "subagent:<role>:<channel 或 'harness'>"；其余 state 返回空串。
def transport_name(state: str, role: str, job_id: str = "", channel: str = "") -> str:
    """裁决来源标识：**结构上不可能等于编译者**，保证 A 裁定「不得自证」不被误伤。"""
    if state == HIVE:
        return "hive:%s:%s" % (role, job_id or "unknown")
    if state == SUBAGENT:
        return "subagent:%s:%s" % (role, channel or "harness")
    return ""


# 生效条件：unit 为假值时按 {} 处理；verdict=unit.get("verdict") or DEFER，verifier=transport_name(state, role, job_id, channel)，evidence 取 unit 的 reason，为空则退回 str(unit["raw"])[:300]，job_id 为真时再追加“（job=<job_id>）”；仅当 unit 的 slot_corrections 为真才带该键，仅当 compiled_by 与 verifier 皆非空且相等才置 self_verify=True。
def to_attest_args(unit: dict, *, state: str = "", role: str = REFLECT, job_id: str = "",
                   channel: str = "", compiled_by: str = "") -> dict:
    """单元裁决 → ccgc.attest(...) 入参（纯函数，离线可测）。

    诚实边界：只做搬运与命名；裁决正确性由外部单元负责，本模块不为其背书。
    """
    unit = unit or {}
    verdict = unit.get("verdict") or DEFER
    verifier = transport_name(state, role, job_id, channel)
    evidence = str(unit.get("reason") or "")
    if unit.get("raw") and not evidence:
        evidence = str(unit["raw"])[:300]
    if job_id:
        evidence = "%s（job=%s）" % (evidence, job_id)
    args = {"verdict": verdict, "verifier": verifier, "evidence": evidence}
    if unit.get("slot_corrections"):
        args["slot_corrections"] = unit["slot_corrections"]
    if compiled_by and verifier and verifier == compiled_by:
        args["self_verify"] = True
    return args


# ---------------------------------------------------------------- 复核请求包

_REFLECT_TPL = """你是认知图记忆节点的**反思单元**（reflect）。下面是一份由 ccgc 编译出的
CCG 六要素候选（功能名/生效条件/子功能/执行/验证方式/不适用条件）。请逐项反思：

1) 六要素是否齐备，是否都能在「对话记录」里找到字面依据；
2) 「生效条件」四槽（场景/时窗/对象/前置）是否与实际适用范围一致，有无过度泛化；
3) 「不适用条件」（拒绝域）是否漏掉了明显该拒的情形；
4) 若有问题，给出**最小修正**（只改该字段，不重写）。

编译产物（JSON）：
{digest}

原始对话记录（真源，引用必须出自此处）：
{dialog}

只输出一个 JSON 对象，不要任何解释文字：
{{"verdict":"accept|drop|defer","reason":"一句话依据","slot_corrections":{{}},
  "checks":[{{"element":"功能名","ok":true,"note":""}}]}}"""

_VERIFY_TPL = """你是独立**验证单元**（verify）。对下面这份 CCG 六要素候选与反思单元的结论
逐条复核：来源是否真实可追溯、结论是否被对话记录支持、修正是否越权（不得新增事实）。

**你只能否决或存疑，不得新增主张、不得改写事实**（可给出 slot_corrections 修正已有槽位）。

候选（JSON）：
{digest}

反思单元结论：
{reflect_rows}

对话记录（真源）：
{dialog}

只输出一个 JSON 对象：
{{"verdict":"accept|drop|defer","reason":"一句话依据","slot_corrections":{{}}}}"""


# 生效条件：digest is None 时返回 "{}"；digest 是 str 时原样返回；否则先试 to_dict/as_dict 可调用方法并 json.dumps 其返回值（抛异常即跳出改走后续分支）；是 dict 时 json.dumps(digest)；其余取 vars(digest) 中不以 "_" 开头的属性 json.dumps（default=str）。
def _digest_of(digest) -> str:
    if digest is None:
        return "{}"
    if isinstance(digest, str):
        return digest
    for attr in ("to_dict", "as_dict"):
        fn = getattr(digest, attr, None)
        if callable(fn):
            try:
                return json.dumps(fn(), ensure_ascii=False, indent=1)
            except Exception:                                     # noqa: BLE001
                break
    if isinstance(digest, dict):
        return json.dumps(digest, ensure_ascii=False, indent=1)
    return json.dumps({k: v for k, v in vars(digest).items() if not k.startswith("_")},
                      ensure_ascii=False, indent=1, default=str)


# 生效条件：role==VERIFY 选 _VERIFY_TPL，否则选 _REFLECT_TPL；reflect_rows 是 str 时直接作为 rows，否则 json.dumps(reflect_rows or [], ensure_ascii=False, indent=1)；最终返回 tpl.format(digest=_digest_of(digest), dialog=str(dialog or "（未提供）")[:6000], reflect_rows=rows[:3000])。
def prompt_for(role: str, digest=None, *, dialog: str = "", reflect_rows="") -> str:
    """按角色生成复核请求包正文（reflect/verify 共用一处模板真源）。"""
    tpl = _VERIFY_TPL if role == VERIFY else _REFLECT_TPL
    rows = reflect_rows if isinstance(reflect_rows, str) else json.dumps(
        reflect_rows or [], ensure_ascii=False, indent=1)
    return tpl.format(digest=_digest_of(digest), dialog=str(dialog or "（未提供）")[:6000],
                      reflect_rows=rows[:3000])


# 生效条件：text 取 prompt 真值或 prompt_for(role, digest, dialog=dialog, reflect_rows=reflect_rows)；pr=probe(jobs, model, allow_degrade=allow_degrade, channel=channel) 为 SUBAGENT 时原样返回未派发的 SUBAGENT 包、为 CONFIGURE 时返回未派发的 CONFIGURE 包；为 HIVE 时若 autostart 为真且 serve_state(jobs) 非 alive 先 autostart_serve(jobs)，再 submit(...)，submit 失败回 CONFIGURE 且把 error 拼进 hint，成功则给出 job_id，blocking=False 直接返回；blocking=True 时 wait(sub["job_id"], jobs=jobs, timeout_s=wait_s)，res.ok 为假则 unit 记 DEFER 并附未产出有效结果的 hint，为真则 unit=verdict_of(res.get("content"))，随后填 transport/attest/result_ok/waited_s 并 _log。
def review(*, prompt: str = "", role: str = REFLECT, digest=None, dialog: str = "",
           reflect_rows="", node_id: str = "", jobs: str = "", model: str = "",
           timeout_s: int = DEFAULT_TIMEOUT_S, allow_degrade: bool = False,
           channel: str = "", wait_s: float = DEFAULT_TIMEOUT_S, blocking: bool = True,
           cg=None, actor: str = "", autostart: bool = False) -> dict:
    """复核主入口：**蜂巢优先 → 提示配置 → 端子代理降级**（三态各自如实返回）。

    返回统一形态：{state, role, node_id, transport, unit, attest, prompt, job_id, hint}
    - state=hive     ：已派发；blocking=True 时等终态并给出 unit/attest；否则只给 job_id
    - state=configure：**未派发**，hint 为配置指引（使用者裁定：不可用即提示配置）
    - state=subagent ：**未派发**，返回 prompt 包供宿主子代理执行并回填
    """
    text = prompt or prompt_for(role, digest, dialog=dialog, reflect_rows=reflect_rows)
    pr = probe(jobs, model, allow_degrade=allow_degrade, channel=channel)
    base = {"role": role, "node_id": node_id, "prompt": text,
            "transport": None, "unit": None, "attest": None,
            "job_id": None, "hint": pr.get("hint") or "", "channel": pr.get("channel") or "",
            "degrade": {"channel": channel or "harness-subagent",
                        "how": "宿主子代理执行 prompt → 裁决经 verdicts 回填 attest"}}
    if pr["state"] == SUBAGENT:
        return {"state": SUBAGENT, **base,
                "degrade": {"available": True, "channel": channel or "harness-subagent",
                            "how": "把 prompt 交给宿主子代理，取其 JSON 裁决后调 "
                                   "cg(op=ccg, action=attest, verdict=<accept|drop|defer>, "
                                   "verifier=subagent:<role>:<channel>)"}}
    if pr["state"] == CONFIGURE:
        return {"state": CONFIGURE, **base,
                "degrade": {"available": True, "channel": channel or "harness-subagent",
                            "how": "① 按 hint 配置蜂巢后重试；② 或带 allow_degrade=true 降级子代理"}}
    if autostart and not serve_state(jobs)["alive"]:
        pr["autostart"] = autostart_serve(jobs)
    sub = submit(prompt=text, role=role, jobs=jobs, model=model, timeout_s=timeout_s,
                 cg=cg, actor=actor)
    if not sub.get("ok"):
        return {"state": CONFIGURE, **base, "hint": (pr.get("hint") or "") + "\n" + str(sub.get("error"))}
    out = {"state": HIVE, **base, "job_id": sub["job_id"], "unit_role": role,
           "model": sub.get("model")}
    if not blocking:
        return out
    res = wait(sub["job_id"], jobs=jobs, timeout_s=wait_s)
    unit = verdict_of(res.get("content")) if res.get("ok") else {
        "verdict": DEFER, "reason": res.get("error") or "单元未返回可用结果",
        "slot_corrections": {}, "parsed": False}
    out["unit"] = unit
    out["transport"] = transport_name(HIVE, role, sub["job_id"])
    out["attest"] = to_attest_args(unit, state=HIVE, role=role, job_id=sub["job_id"])
    out["result_ok"] = bool(res.get("ok"))
    out["waited_s"] = res.get("waited_s")
    if not res.get("ok"):
        out["hint"] = "蜂巢 job 未产出有效结果：%s（裁决按 DEFER 处理，未假装通过）" % res.get("error")
    _log(cg, {"action": "review", "job_id": sub["job_id"], "role": role,
              "node_id": node_id, "actor": actor, "unit_verdict": unit.get("verdict"),
              "result_ok": bool(res.get("ok"))})
    return out


# ---------------------------------------------------------------- serve 拉起（显式）

# 生效条件：serve_state(jobs_dir(jobs)) 已 alive 时返回 started=False 的“serve 存活”；否则 exe_path() 未被 isfile 命中时返回 started=False 并提示先 cargo build --release；否则以 detached/新会话 Popen 拉起 exe serve --jobs jd 并把 stdout/stderr 写入 jd/_serve.log，Popen 抛 OSError 时返回 started=False 的拉起失败；拉起后在 float(wait_s) 内轮询到 alive 返回 started=True 的“serve 已拉起”，轮询超时仍返回 started=True 但标注心跳未就绪。
def autostart_serve(jobs: str = "", wait_s: float = 5.0) -> dict:
    """**显式**拉起 serve（默认不启用；使用者裁定：不可用即提示配置）。

    形态同 hive_mcp._ensure_serve：detached + 独立日志，不阻塞调用方。
    """
    jd = jobs_dir(jobs)
    if serve_state(jd)["alive"]:
        return {"started": False, "note": "serve 存活"}
    exe = exe_path()
    if not os.path.isfile(exe):
        return {"started": False, "note": "未找到可执行文件 %s——先 cargo build --release" % exe}
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    try:
        os.makedirs(jd, exist_ok=True)
        with open(os.path.join(jd, "_serve.log"), "ab") as logf:
            subprocess.Popen([exe, "serve", "--jobs", jd], stdout=logf, stderr=logf,
                             stdin=subprocess.DEVNULL, **kwargs)
    except OSError as exc:
        return {"started": False, "note": "拉起失败：%s: %s" % (type(exc).__name__, exc)}
    t0 = time.time()
    while time.time() - t0 < float(wait_s):
        if serve_state(jd)["alive"]:
            return {"started": True, "note": "serve 已拉起"}
        time.sleep(0.1)
    return {"started": True, "note": "serve 已拉起（心跳未就绪，稍后自愈）"}


# 生效条件：返回 dict 的 ok=p["state"]==HIVE，其中 p=plan(jobs)（model/fresh_s/allow_degrade/channel 全走默认），state/serve_alive/serve_age_s/chain/hint/model 取自该 p；jobs_dir 取 jobs_dir(jobs)，exe_found 与 exe_path 取 exe_path() 是否被 isfile 命中，model_set=bool(model_name())（无参，读 ENV_MODEL），api_key_set=bool(os.environ.get(ENV_API_KEY))，env 记录 ENV_JOBS_DIR 与 ENV_MODEL 的原值。
def doctor(jobs: str = "") -> dict:
    """能力体检（形态对齐 hive_doctor）：判活 + exe + 模型 + 优先级链。"""
    jd = jobs_dir(jobs)
    p = plan(jobs)
    return {"ok": p["state"] == HIVE, "state": p["state"], "jobs_dir": jd,
            "serve_alive": p["serve"]["alive"], "serve_age_s": p["serve"]["age_s"],
            "exe_found": os.path.isfile(exe_path()), "exe_path": exe_path(),
            "model_set": bool(model_name()), "model": p["model"],
            "api_key_set": bool(os.environ.get(ENV_API_KEY)),
            "env": {"HIVE_JOBS_DIR": os.environ.get(ENV_JOBS_DIR, ""),
                    "MDCG_UNIT_MODEL": os.environ.get(ENV_MODEL, "")},
            "chain": p["chain"], "hint": p["hint"]}