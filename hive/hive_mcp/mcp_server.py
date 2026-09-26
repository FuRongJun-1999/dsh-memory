# -*- coding: utf-8 -*-
"""灵枢蜂巢 · MCP server（蜂群多智能体并发运行时对外接口）。

形态对齐 md_cg/mcp_server.py：手写 stdio JSON-RPC 2.0，零第三方依赖。
与 hive 的通信走**文件协议**（jobs/<id>/{spec,status,result,kill} + _serve.json
心跳），零 IPC 依赖；serve 未存活时 spawn/poll 自动拉起（detached）。

启动：
    HIVE_JOBS_DIR=<jobs 目录> python -m hive.hive_mcp.mcp_server
（hive/ 为 python 包：PYTHONPATH 指向 dsh-memory 仓根）

工具面（5 个）：
  hive_spawn   提交任务（model/user_prompt 必填）→ job_id 毫秒即返。可选：
               system_prompt/context_files/max_tokens/temperature/thinking/
               tools/max_tool_rounds/mdcg_root/web_search_backend。
               **统一子代理默认**（缺省即注入）：reasoning_effort=high、
               context_budget_tokens=200000、timeout_s=600。模型名须与
               HIVE_API_BASE 配对（deepseek base→deepseek-flash/deepseek-v4-pro；
               智谱 base→glm-5.3-flash）。
  hive_poll    查状态：传 job_id 单查（含全文），不传=活跃任务摘要
               （content 截断 800 字防上下文爆炸，全文读 result_path）
  hive_kill    写 kill 标志（worker ≤1s 强杀）
  hive_restart 重启 serve（stop→start 原子序，复用 serve_start.restart）：
               改 serve 级配置（config.local.json）或 rust 重新 build 后使改动
               生效；stop 失败绝不 start（防双实例）。重启中断 claimed/running
               任务（重启后由 recover_orphans 收尸）。
  hive_doctor  serve 存活 / 任务状态统计 / 启动指引。env 分两列：
               serve_env_source（config.local.json=serve env 的真实来源，判资格
               看这列）与 mcp_process_env（仅诊断，勿用它判 serve 资格）

env：HIVE_JOBS_DIR（默认 <仓>/hive/jobs）、HIVE_EXE（默认 <仓>/hive/target/
release/hive.exe，自动探测）、HIVE_EXEC_PY（执行器，serve 级；指向
hive/exec_cmd.py 可让同一 serve 兼跑确定性任务）；HIVE_API_KEY / HIVE_API_BASE /
HIVE_WORKERS 等由 config.local.json 注入 serve，再由 serve 透传给执行器。
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import time
import uuid

SERVER_NAME = "hive-mcp"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HIVE_DIR = os.path.join(REPO, "hive")
# 与 serve_start 的 DEFAULT_CONFIG / _exe_path / _jobs_dir 同口径（同一环境变量），
# 使「真实部署」与「隔离测试」两形态都只需改 env，无需改代码。
CONFIG_LOCAL = os.environ.get("HIVE_CONFIG") or os.path.join(HIVE_DIR, "config.local.json")

# 统一子代理执行配置（使用者裁定 2026-09-16）：思考强度高 / 上下文 200k / 超时 10 分钟。
# 缺省即注入 spec；调用方显式传值优先。
DEFAULT_REASONING_EFFORT = "high"
DEFAULT_CONTEXT_BUDGET_TOKENS = 200000
DEFAULT_TIMEOUT_S = 600


# 生效条件：无必需形参；HIVE_DIR 可导入 serve_start 且 os.path.exists(CONFIG_LOCAL) 为真时返回 serve_start.load_config(CONFIG_LOCAL) 的 (cfg or {}, err)（cfg 为假值时第一项回落 {}），serve_start 导入失败或 CONFIG_LOCAL 不存在时返回 ({}, 原因串)。
def _load_local_config():
    """读 hive/config.local.json —— **serve 进程 env 的真实来源**。

    复用 serve_start.load_config（单一真源，避免两处解析口径漂移）。→ ({}, err)。

    为什么 doctor 要读配置而不是读进程 env：serve 的 env 在启动时固化，子进程无法反查；
    用「MCP 进程 env」推断 serve 资格会得到错位结论（2026-09-16 实际误判的根因）。
    """
    try:
        if HIVE_DIR not in sys.path:
            sys.path.insert(0, HIVE_DIR)
        import serve_start  # noqa: PLC0415 —— 同目录模块，延迟导入避开包名歧义
    except Exception as e:  # noqa: BLE001
        return {}, f"serve_start 不可导入（{type(e).__name__}），配置未生效"
    if not os.path.exists(CONFIG_LOCAL):
        return {}, f"配置文件不存在：{CONFIG_LOCAL}"
    cfg, err = serve_start.load_config(CONFIG_LOCAL)
    return (cfg or {}), err


# 生效条件：无必需形参；经 serve_start._jobs_from({**os.environ, **(load_config(CONFIG_LOCAL)[0] or {})}) 求值（N89 批次 49：与 serve_start.start :231/:236 同一决策函数同一合并语义——config.local.json 的 HIVE_JOBS_DIR 键与 serve 面同权生效；config 缺失/解析失败时 cfg={} 自然回落 env/模块默认，与 _lifecycle_jobs 的「stop 不因 config 笔误而停不掉」同宽容度；serve_start 不可导入时同路径回落），makedirs(exist_ok=True) 后返回该路径。
def _jobs_dir() -> str:
    """jobs 池**唯一决策口径** = serve_start._jobs_from(合并环境)（N89 修复）。

    历史缺陷（v2 N17 首报，四轮维持）：本处只读 MCP 进程 env，serve 面以
    {**os.environ, **config} 合并（config 键胜出）——config 设 HIVE_JOBS_DIR
    且 MCP env 未设时，spawn ok=True 但任务落默认池永无人领取，观测面全绿
    与实况相悖。现与 serve 同吃一份 config：spawn/poll/kill/doctor/restart
    五面同走本函数，单点修复即全修（`_ensure_serve` :196 的 setdefault 是
    env 层补写，config 键存在时本就不构成补救——现两层天然一致）。
    """
    try:
        if HIVE_DIR not in sys.path:
            sys.path.insert(0, HIVE_DIR)
        import serve_start  # noqa: PLC0415 —— 同目录模块，延迟导入避开包名歧义
    except Exception as e:  # noqa: BLE001
        # serve_start 不可导入：退回旧 env/默认口径（fail-soft 不崩协议面）
        sys.stderr.write(f"[mcp_server] serve_start 不可导入（{type(e).__name__}），"
                         "HIVE_JOBS_DIR 按 env/默认解析\n")
        d = os.environ.get("HIVE_JOBS_DIR") or os.path.join(REPO, "hive", "jobs")
        os.makedirs(d, exist_ok=True)
        return d
    cfg, _err = _load_local_config()
    d = serve_start._jobs_from({**os.environ, **(cfg or {})})
    os.makedirs(d, exist_ok=True)
    return d


# 生效条件：无必需形参；HIVE_EXE 为真值时直接返回该值，否则返回 REPO/hive/target/release/ 下按 os.name == "nt" 取名的 hive.exe 或 hive。
def _exe_path() -> str:
    exe = os.environ.get("HIVE_EXE")
    if exe:
        return exe
    name = "hive.exe" if os.name == "nt" else "hive"
    return os.path.join(REPO, "hive", "target", "release", name)


# 生效条件：jid 为 str、以 "h" 开头且其余每字符均为 ASCII 字母/数字/下划线时返回 True，其余（含空串、`..`、`../victim`、`h/../../x`、非 str）一律 False——与 rust 侧 `job::valid_job_id` 同口径（跨语言靠注释约定对齐，勿自持第二判据）。
def _valid_job_id(jid) -> bool:
    """job_id 结构校验（防路径穿越，2026-09-25 缺陷）。

    MCP 面 job_id 由客户端可控：`poll ../victim` 曾可读池外任意目录全文、
    `kill ..` 曾可在池外写 kill 标志（os.path.join 裸拼 + isdir 恒真）。
    一切把外部 job_id 拼进路径的入口（_t_poll/_t_kill）先过此闸。
    """
    if not isinstance(jid, str) or not jid.startswith("h"):
        return False
    return all(("a" <= c <= "z") or ("A" <= c <= "Z")
               or ("0" <= c <= "9") or c == "_" for c in jid)


# ---------------------------------------------------------------- serve 管理

# 生效条件：jobs 给定；打开 jobs/_serve.json 并 json.load 成功且结果为真值时返回该 dict，json.load 结果为假值或抛 OSError/ValueError 时返回 {}。
def _heartbeat(jobs: str) -> dict:
    """读 serve 心跳（`_serve.json`）——**执行器资格的权威来源**（serve 启动时固化）。

    跨进程 env 不可反查，故「serve 真实生效的执行器」只能由 serve 自己写出来。
    不存在 / 解析失败 → {}（旧版本心跳无 exec_py/exec_mode 键时也走这里）。
    """
    try:
        with open(os.path.join(jobs, "_serve.json"), encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


# 生效条件：无必需形参；HIVE_DIR 可导入 serve_start 且 float(serve_start.FRESH_S) 求值不抛异常时返回该值，try 段内任意异常（导入失败、属性缺失或 float 转换失败）一律回落 15.0。
def _fresh_s() -> float:
    """serve 存活判定的心跳新鲜窗口（秒）——**单一常量源 = serve_start.FRESH_S**。

    必须与 CLI 侧 `hive/src/main.rs` 的 `FRESH_MS = 15000` 同口径（跨语言只能靠注释
    约定 + 守卫测试对齐）。历史缺陷：本处曾硬编码 5.0s，与 serve_start 的 15s、
    CLI doctor 的 5000ms 形成三处不一致——窗口偏小会把「心跳稍慢」误判为死，进而
    由 `_ensure_serve` 重复拉起第二个 serve（双实例抢队列 / `_serve.json` pid 互覆 /
    `--stop` 只杀得掉一个）。serve_start 不可导入时退回 15.0 保底。
    """
    try:
        if HIVE_DIR not in sys.path:
            sys.path.insert(0, HIVE_DIR)
        import serve_start  # noqa: PLC0415 —— 同目录模块，延迟导入避开包名歧义
        return float(serve_start.FRESH_S)
    except Exception:  # noqa: BLE001
        return 15.0


# 生效条件：jobs 给定；serve_start 可导入且 serve_start.serve_alive(jobs) 未抛异常时返回其布尔结果，try 段内任意异常（含 serve_alive 自身抛出）则回落为：_heartbeat(jobs) 为假值返回 False，否则按 (time.time() - hb.get("ts", 0) / 1000.0) < _fresh_s() 判定。
def _serve_alive(jobs: str) -> bool:
    """serve 存活判定——**直接复用 `serve_start.serve_alive(jobs)`**（三层判据：
    心跳新鲜 + pid 存活 + 该 pid 是本程序），保证 MCP 面与 CLI 面、rust 侧同口径。

    历史缺陷（2026-09-17 v13 新发现 A 的同族）：本处曾**只判 ts 新鲜度**，与 rust
    `serve_running`（新鲜 + pid 存活）分叉——同一份心跳两面得两个结论：崩溃后的残留
    心跳会被判成「serve 存活」而拒绝重复拉起，而 CLI `--stop` 又可能因判据不同
    回「未在运行」，两条逃生口同时失效。判据只此一处实现，勿再自持一份。

    serve_start 不可导入时退回「仅新鲜度」并如实降级（宁可少判一层，不阻断拉起）。
    """
    try:
        if HIVE_DIR not in sys.path:
            sys.path.insert(0, HIVE_DIR)
        import serve_start  # noqa: PLC0415 —— 同目录模块，延迟导入避开包名歧义
        return bool(serve_start.serve_alive(jobs))
    except Exception:  # noqa: BLE001
        hb = _heartbeat(jobs)
        if not hb:
            return False
        return (time.time() - hb.get("ts", 0) / 1000.0) < _fresh_s()


# 生效条件：jobs 给定；_serve_alive(jobs) 为真时返回 {started: False, note: "serve 存活"}，否则仅在 _exe_path() 可被 isfile 判定为真、serve_start 可导入、serve_start.start(CONFIG_LOCAL) 不抛异常且其返回 r 的 get("ok") 为真时返回 started: True（含 pid/routes/config_keys），以上任一失败分支返回 started: False 及对应 note，拉超前以 os.environ.setdefault 设 HIVE_JOBS_DIR。
def _ensure_serve(jobs: str) -> dict:
    """serve 未存活则 detached 拉起；返回 {started: bool, note: str}。

    **直接复用 serve_start.start()**——拉起逻辑只此一处实现，杜绝「两条拉起路径 env
    不一致」（2026-09-16 实测缺陷：MCP 侧自有实现硬编码 HIVE_JOBS_DIR，且 config 里的
    HIVE_EXEC_PY 压过了测试注入的假执行器，导致 smoke 端到端误走真 API）。jobs / config /
    exe 三个路径经 HIVE_JOBS_DIR / HIVE_CONFIG / HIVE_EXE 三个环境变量在两侧同口径解析。
    """
    if _serve_alive(jobs):
        return {"started": False, "note": "serve 存活"}
    exe = _exe_path()
    if not os.path.isfile(exe):
        return {
            "started": False,
            "note": f"serve 未运行且未找到可执行文件 {exe}——先 cargo build --release（hive/ 下）",
        }
    try:
        if HIVE_DIR not in sys.path:
            sys.path.insert(0, HIVE_DIR)
        import serve_start  # noqa: PLC0415 —— 同目录模块，延迟导入避开包名歧义
    except Exception as e:  # noqa: BLE001
        return {"started": False, "note": f"serve_start 不可导入（{type(e).__name__}）：{e}"}
    os.environ.setdefault("HIVE_JOBS_DIR", jobs)  # serve_start 模块级常量在 import 时求值
    try:
        # serve_start 库层函数不打印，此处重定向双保险：MCP 的 stdout 是 JSON-RPC 通道
        with contextlib.redirect_stdout(io.StringIO()):
            r = serve_start.start(CONFIG_LOCAL)
    except Exception as e:  # noqa: BLE001
        return {"started": False, "note": f"拉起异常（{type(e).__name__}）：{e}"}
    if not r.get("ok"):
        return {"started": False, "note": f"拉起失败：{r.get('error')}"}
    return {
        "started": True,
        "note": "serve 已自动拉起（env=宿主+config.local.json，逻辑复用 serve_start）",
        "pid": r.get("pid"),
        "routes": {"HIVE_CONFIG": CONFIG_LOCAL, "HIVE_JOBS_DIR": jobs, "HIVE_EXE": exe},
        "config_keys": r.get("env_keys", []),
    }


# ---------------------------------------------------------------- 工具实现

# ---------------------------------------------------------------- 工具实现

# P11 结果完整性锚密钥链（批次53）：与 hive/src/keyres.rs 同一链、同一顺序——
# 只取 hive 既有配置/令牌面（对照 config.local 既有键），不新发明密钥来源、
# 不设公开缺省常量（N143 教训）。config.local.json 的解析值按 serve_start
# 合并语义（{**os.environ, **config}）胜出进程 env，故先查 config 再查 env。
_RESULT_KEY_KEYS = ("HIVE_ORCH_TOKEN", "HIVE_ORCH_TOKEN_FILE", "HIVE_API_KEY")


# 生效条件：无必需形参——先 _load_local_config() 取 config 解析值（load_config 已完成 {"file":…} 读文件），三键按序首个非空字符串胜出；再查进程 env 同序（HIVE_ORCH_TOKEN_FILE 形态读文件全文 strip）；全缺 → None（提交面退回旧格式，不写 result_nonce——零配置部署行为不变）。
def _result_anchor_key() -> str | None:
    """结果完整性锚密钥（P11 批次53）：hive 既有配置/令牌面唯一解析点。

    与 rust keyres::resolve_key_from_env 同链（submit 与 serve 两侧同口径，
    勿再分叉第二套解析）；config 值胜出 env（serve_start 合并语义）。
    """

    def _env(k: str) -> str | None:
        v = (os.environ.get(k) or "").strip()
        return v or None

    cfg, _err = _load_local_config()
    for k in _RESULT_KEY_KEYS:
        v = cfg.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    for k in _RESULT_KEY_KEYS:
        v = _env(k)
        if v:
            return v
    f = _env("HIVE_ORCH_TOKEN_FILE")
    if f:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                s = fh.read().strip()
            if s:
                return s
        except OSError:
            pass
    return None


# 生效条件：jobs 与 spec 给定且不做校验，即生成 h{毫秒时间戳}_{uuid4 前 6 位} 的 job_id，建 jobs/job_id 目录并写 spec.json 与 status.json（state=pending、timeout_s 取 spec.get("timeout_s", 300) 缺键回落 300、model 取 spec.get("model") 缺键为 None）；P11 批次53：_result_anchor_key() 解析到密钥时 status 追加 result_nonce=uuid4 hex（任务自此声明锚预期，serve 侧 classify_result 采信 done 前校验 result_anchor），密钥缺失则不加该键（旧格式，行为零变更），返回 job_id。
def _submit(jobs: str, spec: dict) -> str:
    job_id = f"h{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    d = os.path.join(jobs, job_id)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "spec.json"), "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False)
    nonce = uuid.uuid4().hex if _result_anchor_key() is not None else None
    status = {
        "job_id": job_id,
        "state": "pending",
        "created_ts": int(time.time() * 1000),
        "started_ts": None,
        "heartbeat_ts": None,
        "elapsed_s": 0.0,
        "timeout_s": spec.get("timeout_s", 300),
        "model": spec.get("model"),
        "pid": None,
        "error": None,
    }
    if nonce:
        # 秘密性归锚密钥；nonce 只求任务内唯一（防锚跨任务复用）
        status["result_nonce"] = nonce
    with open(os.path.join(d, "status.json"), "w", encoding="utf-8") as f:
        json.dump(
            status,
            f,
            ensure_ascii=False,
        )
    return job_id


# 解析缓存（v7 留档「orch._poll 重复解析」修复，缺陷迭代第 14 轮）：
# poll 是编排等待循环的高频重复动作（spawn 返回 hint 明示「继续轮询
# poll_subtasks」），_poll→_card（与 MCP 面 _t_poll 同源走本模块两函数）
# 此前每次轮询对全部子任务全量重读+json.load status.json 与 result.json
# 全文——实测 8 子任务/210KB result 串行 7rep 中位 2.67ms/轮、content
# 50K/200K/800K → 0.98/2.67/10.13ms 随产物大小近似线性、随轮询次数线性
# 累积；对照同批 16 文件纯 os.stat 仅 0.233ms。按 (st_mtime_ns, st_size)
# 签名短路未变更文件的重解析：文件未变复用已解析值，变更（worker 重写
# status/result 必产生新 mtime）/删除按签名失配或 stat 失败重读——语义
# 与逐次读盘逐位一致。有界防长驻累积：超上限整体清空（粗粒度，正确性
# 不受影响，只多付一次冷启解析）。
_PARSE_CACHE = {}          # path -> (mtime_ns, size, parsed)
_PARSE_CACHE_MAX = 256


# 生效条件：path 与 parse 给定；os.stat(path) 抛 OSError 时摘除该 path 的缓存项并原样执行 parse()（其异常语义由调用方处理），stat 成功且缓存命中（(st_mtime_ns, st_size) 与登记值相等）时返回登记解析值，否则执行 parse()、成功返回（不抛异常）后登记（含超上限先整体清空）并返回其值。
def _cached_json(path, parse):
    """(mtime_ns, size) 签名短路的一次性解析入口（未变更文件零重读）。"""
    try:
        st = os.stat(path)
        sig = (st.st_mtime_ns, st.st_size)
    except OSError:
        _PARSE_CACHE.pop(path, None)
        return parse()
    hit = _PARSE_CACHE.get(path)
    if hit is not None and (hit[0], hit[1]) == sig:
        return hit[2]
    val = parse()
    if len(_PARSE_CACHE) >= _PARSE_CACHE_MAX:
        _PARSE_CACHE.clear()
    _PARSE_CACHE[path] = (sig[0], sig[1], val)
    return val


# 生效条件：jobs 与 job_id 给定；jobs/job_id/status.json 的缓存解析成功时返回其浅拷贝（每次调用拿到可独立变更的新 dict——_t_poll 会往 st 上挂 result，不得污染缓存），解析抛 OSError 或 ValueError 时返回 None。
def _read_status(jobs: str, job_id: str):
    p = os.path.join(jobs, job_id, "status.json")
    try:
        st = _cached_json(p, lambda: _load_json_file(p))
    except (OSError, ValueError):
        return None
    return dict(st) if isinstance(st, dict) else st


def _load_json_file(p: str):
    """open+json.load 原语（_cached_json 的 parse 回调；异常原样外抛）。"""
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# 生效条件：job_dir 与 head 给定；job_dir/result.json 未通过 os.path.isfile 时返回 None，缓存解析抛 OSError/ValueError 时返回 {"error": "result.json 解析失败: …"}，否则在该解析值（**浅拷贝**上派生——缓存基底不被下面截断/挂键变更）：head 非 None（含 head=0）且 len(content) > head 时把 content 截成 content_head 并置 content_truncated，并统一加 result_path 与 handoff_ready（need_continue is True 且 completed 非 True）。
def _result_view(job_dir: str, head):
    p = os.path.join(job_dir, "result.json")
    if not os.path.isfile(p):
        return None
    try:
        r = _cached_json(p, lambda: _load_json_file(p))
    except (OSError, ValueError) as e:
        return {"error": f"result.json 解析失败: {e}"}
    # 派生在浅拷贝上做，缓存基底保持原样；非 dict 形态（病态 result.json）
    # 不拷贝——后续 r.get 抛 AttributeError 与旧逐次解析口径一致。
    r = dict(r) if isinstance(r, dict) else r
    content = r.get("content") or ""
    if head is not None and len(content) > head:
        r["content_head"] = content[:head]
        r["content_truncated"] = True
        r.pop("content", None)
    r["result_path"] = p
    # 交接信号派生字段：与 rust `result_summary` 同口径（同一事件两面一眼可判）。
    # 原始字段（need_continue/completed/handoff）如实透传；缺失不伪造 false。
    r["handoff_ready"] = (r.get("need_continue") is True
                          and r.get("completed") is not True)
    return r


# hive_spawn 入参白名单——与 TOOLS[0].inputSchema.properties **逐键同集**（smoke_test 断言守卫，
# 防两处漂移导致「schema 收得下、白名单拒得掉」）。
# 为什么需要它：spec 由 _t_spawn 内逐字段 if 赋值**白名单构造**，未列入的键既不进 spec 也不报错。
# 宿主照 hive/README.md「spec 字段」表传 command / commands / orchestrate / workdir 时——
# 前三个只属 CLI/spec 层（exec_cmd.py / orch.py），workdir 由本面强制取进程 cwd——四者皆被
# 静默丢弃，表现为「以为在跑确定性任务、实际走了 LLM 路径烧 token」。故显式拒绝并指路 CLI。
SPAWN_ALLOWED_KEYS = frozenset({
    "model", "user_prompt", "system_prompt", "context_files", "timeout_s",
    "reasoning_effort", "context_budget_tokens", "context_strict", "thinking",
    "tools", "max_tool_rounds", "mdcg_root", "web_search_backend",
    "max_tokens", "temperature",
})


# 生效条件：a 给定；当 a 含 SPAWN_ALLOWED_KEYS 之外的键、a.get("model") 去空白后为空、a.get("user_prompt") 去空白后为空、或 a.get("context_files") 中任一项（相对项按 os.getcwd() 拼接）未通过 isfile 时返回 ok: False 与对应 error，否则组装 spec（timeout_s/context_budget_tokens 以 int(x or 默认) 把 0/空值/缺键回落默认，workdir 固定为 os.getcwd()）并返回 ok: True 含 job_id/jobs_dir/serve。
def _t_spawn(a: dict) -> dict:
    unknown = sorted(k for k in a if k not in SPAWN_ALLOWED_KEYS)
    if unknown:
        return {"ok": False, "error": (
            f"hive_spawn 不接受参数：{', '.join(unknown)}——本工具只提交 LLM 委托型任务，"
            "入参白名单外的键进不了 spec，故显式拒绝（不再静默丢弃）。"
            "确定性执行（command / commands）与编排（orchestrate）请改走 CLI："
            "`hive submit` 提交带这些字段的 spec.json，执行器见 hive/exec_cmd.py；"
            "workdir 由本面强制取 MCP 进程 cwd，需指定基准目录请用绝对路径 context_files。")}
    if not (a.get("model") or "").strip():
        return {"ok": False, "error": (
            "缺必填参数 model。模型名须与 HIVE_API_BASE 配对——deepseek base（api.deepseek.com）"
            "→ deepseek-flash / deepseek-v4-pro；智谱 base → glm-5.3-flash。子代理推荐 flash 档。")}
    if not (a.get("user_prompt") or "").strip():
        return {"ok": False, "error": "缺必填参数 user_prompt"}
    jobs = _jobs_dir()
    for rel in a.get("context_files") or []:
        path = rel if os.path.isabs(rel) else os.path.join(os.getcwd(), rel)
        if not os.path.isfile(path):
            return {"ok": False, "error": f"context 文件不存在: {path}"}
    ensure = _ensure_serve(jobs)
    spec = {"model": a["model"].strip(), "user_prompt": a["user_prompt"]}
    if a.get("system_prompt"):
        spec["system_prompt"] = a["system_prompt"]
    if a.get("context_files"):
        spec["context_files"] = a["context_files"]
    # —— 统一子代理执行配置：缺省即注入（显式传值优先）
    spec["timeout_s"] = int(a.get("timeout_s") or DEFAULT_TIMEOUT_S)
    spec["reasoning_effort"] = a.get("reasoning_effort") or DEFAULT_REASONING_EFFORT
    spec["context_budget_tokens"] = int(
        a.get("context_budget_tokens") or DEFAULT_CONTEXT_BUDGET_TOKENS)
    if a.get("context_strict") is not None:
        # 旧 fail fast 开关（缺省=达预算交回续跑）；显式传值优先。
        spec["context_strict"] = bool(a["context_strict"])
    if a.get("max_tokens"):
        spec["max_tokens"] = a["max_tokens"]
    if a.get("temperature") is not None:
        spec["temperature"] = a["temperature"]
    if a.get("thinking") is not None:
        spec["thinking"] = a["thinking"]
    if a.get("tools"):
        spec["tools"] = a["tools"]
    if a.get("max_tool_rounds"):
        spec["max_tool_rounds"] = int(a["max_tool_rounds"])
    if a.get("mdcg_root"):
        spec["mdcg_root"] = a["mdcg_root"]
    if a.get("web_search_backend"):
        spec["web_search_backend"] = a["web_search_backend"]
    spec["workdir"] = os.getcwd()
    job_id = _submit(jobs, spec)
    return {
        "ok": True,
        "job_id": job_id,
        "jobs_dir": jobs,
        "serve": ensure,
        "spec_defaults": {
            "reasoning_effort": spec["reasoning_effort"],
            "context_budget_tokens": spec["context_budget_tokens"],
            "timeout_s": spec["timeout_s"],
        },
        "hint": "hive_poll(job_id) 轮询；done 后 result.content_head 取摘要、result_path 读全文",
    }


# 生效条件：a 给定；a.get("job_id") 为真时先过 _valid_job_id 结构闸（未过返回 ok: False 的 job_id 非法——防 `../victim` 路径穿越读池外全文，2026-09-25 缺陷），jobs/<job_id> 非目录返回 ok: False 任务不存在，否则返回 {"ok": True, "job": st}（st 为 _read_status 结果，读不到时用 {"error": "status 不可读"}，并附 head=None 的全文 result）；job_id 缺失或为假值时遍历 jobs 下以 "h" 开头的目录，仅 state 属 pending/claimed/running，或 state 属 done/error/timeout/killed 且距今 (heartbeat_ts or created_ts or 0) 不足 3600_000 毫秒者入选，返回 ok/count/jobs。
def _t_poll(a: dict) -> dict:
    jobs = _jobs_dir()
    job_id = a.get("job_id")
    if job_id:
        if not _valid_job_id(job_id):
            return {"ok": False,
                    "error": f"job_id 非法: {job_id}（须为 h 开头且不含路径成分）"}
        d = os.path.join(jobs, job_id)
        if not os.path.isdir(d):
            return {"ok": False, "error": f"任务不存在: {job_id}"}
        st = _read_status(jobs, job_id) or {"error": "status 不可读"}
        st["result"] = _result_view(d, head=None)  # 单查给全文
        return {"ok": True, "job": st}
    ids = sorted(
        n for n in os.listdir(jobs)
        if n.startswith("h") and os.path.isdir(os.path.join(jobs, n))
    )
    active_states = {"pending", "claimed", "running"}
    items = []
    for jid in ids:
        st = _read_status(jobs, jid)
        if not st:
            continue
        active = st.get("state") in active_states
        recent_done = st.get("state") in {"done", "error", "timeout", "killed"} and (
            time.time() * 1000 - (st.get("heartbeat_ts") or st.get("created_ts") or 0)
        ) < 3600_000
        if not (active or recent_done):
            continue
        st["result"] = _result_view(os.path.join(jobs, jid), head=800)  # 摘要防爆炸
        items.append(st)
    return {"ok": True, "count": len(items), "jobs": items}


# 生效条件：a 给定；job_id = a.get("job_id") or "" 先过 _valid_job_id 结构闸（未过返回 ok: False 的 job_id 非法——`..`/`../victim` 曾可在池外写 kill 标志、空串曾落到 jobs 本身，2026-09-25 缺陷），jobs/<job_id> 非目录时返回 ok: False 任务不存在，否则在 kill 标志未存在时创建它并返回 ok: True 与 job_id/hint。
def _t_kill(a: dict) -> dict:
    jobs = _jobs_dir()
    job_id = a.get("job_id") or ""
    if not _valid_job_id(job_id):
        return {"ok": False,
                "error": f"job_id 非法: {job_id}（须为 h 开头且不含路径成分）"}
    d = os.path.join(jobs, job_id)
    if not os.path.isdir(d):
        return {"ok": False, "error": f"任务不存在: {job_id}"}
    flag = os.path.join(d, "kill")
    if not os.path.exists(flag):
        open(flag, "w").close()
    return {"ok": True, "job_id": job_id, "hint": "worker 检测到 kill 标志后强杀（≤1s）"}


# 生效条件：_a 给定且内容未被使用；遍历 jobs 下以 "h" 开头的目录按 (status or {}).get("state") or "unknown" 计数并读 _heartbeat(jobs) 后返回单个 ok: True 字典，其中 serve_alive=_serve_alive(jobs)、exe_found=os.path.isfile(_exe_path())、exec_source 依 hb.get("exec_py") 真值取 "serve_heartbeat" 否则 "no_heartbeat_or_legacy"。
def _t_doctor(_a: dict) -> dict:
    jobs = _jobs_dir()
    exe = _exe_path()
    cfg, cfg_err = _load_local_config()
    states = {}
    for jid in sorted(
        n for n in os.listdir(jobs)
        if n.startswith("h") and os.path.isdir(os.path.join(jobs, n))
    ):
        st = _read_status(jobs, jid)
        s = (st or {}).get("state") or "unknown"
        states[s] = states.get(s, 0) + 1
    hb = _heartbeat(jobs)
    return {
        "ok": True,
        "serve_alive": _serve_alive(jobs),
        "exe_found": os.path.isfile(exe),
        "exe_path": exe,
        "jobs_dir": jobs,
        "task_states": states,
        # 执行器资格（**优先采信 serve 自报的心跳**，与 CLI doctor 同口径）
        "exec_py": hb.get("exec_py"),
        "exec_mode": hb.get("exec_mode"),
        "exec_source": "serve_heartbeat" if hb.get("exec_py") else "no_heartbeat_or_legacy",
        "exec_note": ("exec_mode 判据=执行器文件名（exec_cmd.py=多态转发：带 command 跑命令、"
                      "不带转 LLM；其余=仅 LLM 委托）。确证正路=提交带 command 的探针任务，"
                      "result.content 以「确定性执行」开头即证明。"),
        "serve_env_source": {
            "note": ("serve 的 env 来源=config.local.json（serve 启动时固化，子进程无法反查）。"
                     "判资格看本块，**不要**用 mcp_process_env 判——那会得到错位结论。"
                     "另注：本块是**配置期望值**，serve 实际生效值看顶层 exec_py/exec_mode"
                     "（改了配置未重启 serve 时两者会不同）。"),
            "path": CONFIG_LOCAL,
            "exists": os.path.exists(CONFIG_LOCAL),
            "keys": sorted(cfg.keys()),
            "api_key_set": bool(cfg.get("HIVE_API_KEY")),
            "api_base": cfg.get("HIVE_API_BASE"),
            "exec_py": cfg.get("HIVE_EXEC_PY"),
            "error": cfg_err,
        },
        "mcp_process_env": {
            "note": "本进程 env，仅供诊断；它不等于 serve 的 env",
            "api_key_set": bool(os.environ.get("HIVE_API_KEY")),
            "api_base": os.environ.get("HIVE_API_BASE") or "(未设→执行器内置默认)",
            "workers": os.environ.get("HIVE_WORKERS", "4"),
        },
        "start_cmd": ("python hive/serve_start.py（唯一推荐：读 config.local.json 注入完整 env；"
                      "MCP spawn 会自动拉起）。裸 `hive serve` 不读配置——执行器回退 exec.py"
                      "（llm_only），确定性执行不可用。"),
    }


# 生效条件：_a 给定且内容未被使用；serve_start 可导入时先记 jobs 心跳旧 pid，再以 os.environ.setdefault 设 HIVE_JOBS_DIR 后调 serve_start.restart(CONFIG_LOCAL)（stdout 重定向防污染 JSON-RPC），返回 ok:False（附 stage/error）当 restart 返回 ok 为假或抛异常，否则返回 ok:True 含 old_pid/new_pid/workers/env_keys 与生效说明。
def _t_restart(_a: dict) -> dict:
    """重启 serve（stop→start 原子序）——**逻辑复用 serve_start.restart**（单一实现）。

    修改后自主重启的通道：serve 级配置（config.local.json 的 env/执行器/worker 数）
    启动时固化，改动须重启生效。MCP 进程独立于 serve 进程树，故本工具重启 serve
    不会自杀（区别于任务内 `hive serve --stop`——那会随 worker 一起死）。
    诚实边界：重启中断 claimed/running 任务，重启后由 serve 侧 recover_orphans 收尸
    （claimed 重投 / running 标 error）；rust 面改动须先 cargo build --release。
    """
    jobs = _jobs_dir()
    old_pid = (_heartbeat(jobs) or {}).get("pid")
    try:
        if HIVE_DIR not in sys.path:
            sys.path.insert(0, HIVE_DIR)
        import serve_start  # noqa: PLC0415 —— 同目录模块，延迟导入避开包名歧义
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"serve_start 不可导入（{type(e).__name__}）：{e}"}
    os.environ.setdefault("HIVE_JOBS_DIR", jobs)  # serve_start 模块级常量在 import 时求值
    try:
        # serve_start 库层函数不打印，此处重定向双保险：MCP 的 stdout 是 JSON-RPC 通道
        with contextlib.redirect_stdout(io.StringIO()):
            r = serve_start.restart(CONFIG_LOCAL)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"重启异常（{type(e).__name__}）：{e}"}
    if not r.get("ok"):
        return {"ok": False, "stage": r.get("stage"),
                "error": r.get("error") or "重启失败"}
    return {"ok": True, "old_pid": old_pid, "new_pid": r.get("pid"),
            "workers": r.get("workers"), "env_keys": r.get("env_keys"),
            "note": ("serve 已重启（stop→start，逻辑复用 serve_start.restart）。"
                     "python 面改动即时生效；rust 面改动须先 cargo build --release。")}


# ---------------------------------------------------------------- JSON-RPC 面

TOOLS = [
    {
        "name": "hive_spawn",
        "description": "灵枢蜂巢：提交 LLM 任务到并发队列（毫秒级返回 job_id，后台执行不阻塞）。统一子代理默认：reasoning_effort=high / context_budget_tokens=200000 / timeout_s=600。**只接受下方 properties 列出的 15 个参数**：白名单外的键（如 command / commands / orchestrate / workdir）会被显式拒绝——确定性执行（跑命令/测试/回归）与编排请改走 CLI（hive submit + hive/exec_cmd.py / orch.py）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "LLM 模型名（必填）。须与 HIVE_API_BASE 配对：deepseek base（api.deepseek.com）→ deepseek-flash / deepseek-v4-pro；智谱 base → glm-5.3-flash。子代理推荐 flash 档。"},
                "user_prompt": {"type": "string", "description": "用户提示词（必填）"},
                "system_prompt": {"type": "string", "description": "系统提示词（可选）"},
                "context_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "上下文文件路径列表（相对 cwd 或绝对，可选）",
                },
                "timeout_s": {"type": "integer", "description": "硬超时秒（默认 600=10min，5..3600）"},
                "reasoning_effort": {"type": "string", "enum": ["low", "medium", "high"], "description": "思考强度（默认 high）"},
                "context_budget_tokens": {"type": "integer", "description": "上下文预算 token（默认 200000）。达预算默认写进展卡交回续跑（result.need_continue / handoff_ready，见 hive_poll），不再整任务失败"},
                "context_strict": {"type": "boolean", "description": "可选，默认 false=达预算交回续跑；true=保持旧行为（超预算即 error 终止，不交回）"},
                "thinking": {"type": "object", "description": '思考开关（可选，如 {"type":"enabled"}）'},
                "tools": {"type": "array", "items": {"type": "string"}, "description": "执行器侧工具白名单（可选，如 lingshu_cg / web_search / read_file；read_file 为只读面，写仍只走 lingshu_cg op=write）"},
                "max_tool_rounds": {"type": "integer", "description": "工具回合上限（可选）"},
                "mdcg_root": {"type": "string", "description": "lingshu_cg 指向的认知图 root（可选）"},
                "web_search_backend": {"type": "string", "description": "web_search 后端（可选）"},
                "max_tokens": {"type": "number", "description": "可选"},
                "temperature": {"type": "number", "description": "可选，[0,2]"},
            },
            "required": ["model", "user_prompt"],
        },
    },
    {
        "name": "hive_poll",
        "description": "灵枢蜂巢：查任务状态。传 job_id 单查（含结果全文）；不传=活跃+近 1h 完成任务摘要（content 截 800 字）。含 elapsed_s/tokens 心跳观测。**handoff_ready=true = 子代理满上下文交回（need_continue）**：读 result.handoff + 进展卡（wm.py progress --job <job目录>）后决定是否 spawn 新 job 续跑（不自动续跑，裁决权在主代理）。",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string", "description": "任务 id（可选）"}},
        },
    },
    {
        "name": "hive_kill",
        "description": "灵枢蜂巢：写 kill 标志，worker 检测后强杀子进程（≤1s），任务终态 killed。",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string", "description": "任务 id（必填）"}},
            "required": ["job_id"],
        },
    },
    {
        "name": "hive_restart",
        "description": "灵枢蜂巢：重启 serve（stop→start 原子序，复用 serve_start.restart）。改 serve 级配置（config.local.json 的 env/执行器/worker 数）或 rust 重新 build 后使改动生效；stop 失败绝不 start（防双实例）。诚实边界：重启中断 claimed/running 任务（重启后 recover_orphans 收尸）；rust 面改动须先 cargo build --release。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "hive_doctor",
        "description": "灵枢蜂巢：健康检查——serve 存活/可执行文件/任务状态统计/启动指引。env 分两列：serve_env_source（config.local.json，判资格的权威列）与 mcp_process_env（仅诊断，勿用它判 serve 资格）。密钥只报存在性不回显。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

_DISPATCH = {
    "hive_spawn": _t_spawn,
    "hive_poll": _t_poll,
    "hive_kill": _t_kill,
    "hive_restart": _t_restart,
    "hive_doctor": _t_doctor,
}


# 生效条件：req 给定；req 非 dict（批量数组/裸标量等 JSON 合法值，2026-09-25 v2-N16 DoS 缺陷）时返回 id=None 的 -32600 Invalid Request 且不再下探；req 为 dict 时按 req.get("method", "") 分派——initialize 返回 protocolVersion/capabilities/serverInfo，notifications/initialized 返回 None，tools/list 返回 TOOLS，tools/call 在 params 非 dict 时返回 -32602 Invalid params（不进工具），params 为 dict 时以 params.get("arguments") or {} 调 _DISPATCH 中的 fn（名字不在表内返回 -32602 错误，fn 抛异常则包成 {"ok": False, "error": …} 的文本 content）；其余 method 在 req.get("id") 非 None 时返回 -32601，id 为 None 时返回 None。
def _rpc(req: dict):
    # 入口守卫（fail-closed）：一行非 dict JSON 曾直接 req.get 崩掉常驻
    # server（DoS）——恶意客户端一行 `[…]`/`"x"`/`123`/`null` 即可。回
    # -32600（JSON-RPC 2.0 Invalid Request），id 置 null（非 object 无从取 id）。
    if not isinstance(req, dict):
        return {"jsonrpc": "2.0", "id": None,
                "error": {"code": -32600,
                          "message": "Invalid Request：req 必须为 object"}}
    method = req.get("method", "")
    rid = req.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = req.get("params")
        # params 守卫（fail-closed）：params 非 dict（str/list/int）曾在入口
        # 解析处 AttributeError 崩 server——工具层 try 只包 fn(args)，包不到
        # 这里。回 -32602 Invalid params，不进工具。
        if not isinstance(params, dict):
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32602,
                              "message": "Invalid params：params 必须为 object"}}
        name = params.get("name", "")
        args = params.get("arguments") or {}
        fn = _DISPATCH.get(name)
        if fn is None:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32602, "message": f"未知工具 {name}"}}
        try:
            out = fn(args)
        except Exception as e:  # noqa: BLE001 —— 工具层兜底不崩 server
            out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        return {"jsonrpc": "2.0", "id": rid,
                "result": {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]}}
    if rid is not None:
        return {"jsonrpc": "2.0", "id": rid,
                "error": {"code": -32601, "message": f"未知方法 {method}"}}
    return None


# 生效条件：sys.stdin/stdout/stderr 三个流逐个 reconfigure(encoding="utf-8", errors="replace")，
# 流不支持 reconfigure（AttributeError）或取值非法（ValueError）时静默跳过该流，无返回值。
def _force_utf8_stdio():
    """进程内强制 stdio 三流 = UTF-8（issue #39，与 md_cg/mcp_server.py 同族同修）。

    MCP 协议是 UTF-8 JSON，但 Windows 控制台默认代码页（如 CP936/GBK）会让
    stdio 管道跟随 locale——宿主按 UTF-8 发来的中文参数（model/user_prompt 等）
    被按 GBK 解码：strict 下读侧直接 UnicodeDecodeError，surrogateescape 下
    解出代理对（\\udcXX），main() 里 ``json.dumps(..., ensure_ascii=False)``
    写 stdout 时按 UTF-8 编码即抛 ``UnicodeEncodeError: surrogates not
    allowed``，整条请求失败。桥层 ``PYTHONUTF8=1``（src/lib/mdcg_client.ts）
    只覆盖 DSH 桥路径，mcp.json 直连不经桥仍踩；进程内 reconfigure 是纵深
    补位；``errors="replace"`` 保证坏字节最多丢字符、不炸整条请求。
    必须在 main() 首行调用：早于一切 stderr 中文写与 stdin 读取。
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


# 生效条件：_force_utf8_stdio() 先执行（stdio 三流强制 UTF-8，issue #39）；此后逐行读 sys.stdin，空行与 json.loads 抛 ValueError 的行被跳过，_rpc(req) 抛非 ValueError 异常时回写 id=None 的 -32603 internal error 一行（入口兜底不崩 server，与工具层 try 同款模板），仅 _rpc(req) 返回非 None 时向 stdout 写一行 JSON 并 flush，读到 EOF 后返回 0。
def main() -> int:
    _force_utf8_stdio()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        try:
            resp = _rpc(req)
        except Exception as e:  # noqa: BLE001 —— 入口兜底不崩 server（2026-09-25 v2-N16：_rpc 曾在 try 外，一行恶意 JSON 杀进程）
            resp = {"jsonrpc": "2.0", "id": None,
                    "error": {"code": -32603,
                              "message": f"internal error: {type(e).__name__}"}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())