#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hive serve 启动器：读本地配置文件注入 env，detached 拉起/停止/查看 serve。

用法（Windows 实测形态，Python 3 标准库零第三方依赖）：
    python hive/serve_start.py            # 拉起 serve（已在跑则拒绝，防双实例）
    python hive/serve_start.py --stop     # 停止 serve（读心跳 pid）
    python hive/serve_start.py --restart  # 重启 serve（stop→start 原子序；改配置/换执行器后使改动生效）
    python hive/serve_start.py --rebuild  # 重编译并重启（stop→cargo build→start；rust 改动一条命令生效）
    python hive/serve_start.py --status   # 查看心跳与任务统计（附同一份配置摘要）
    python hive/serve_start.py --show-config  # 只读核对三角色密钥：来源·掩码值·角色·是否到达执行器 + problems + 结论

配置文件（默认与脚本同目录 config.local.json，--config 可指他处）：
    JSON 对象，键=环境变量名，值支持三形态：
      "字符串"                  直值
      {"env": "DEEPSEEK_API_KEY"}   读系统环境变量（key 明文不落盘）
      {"file": "/path/to/api_key.txt"}  读文本文件全部内容并 strip（key 放仓外私有目录）
    解析失败的键 fail fast 拒绝拉起，防止残缺 env 的 serve 上岗。

本模块同时是**库**：mcp_server 首次拉起 serve 时调用 start()，故三个路径常量都可由
环境变量覆盖（HIVE_CONFIG / HIVE_EXE / HIVE_JOBS_DIR），使同一套拉起逻辑同时服务
「真实部署」与「隔离测试」两种形态。start()/stop()/status() 只返回 dict 不打印——
stdio JSON-RPC 通道上多打一行即污染协议；打印只发生在 CLI 入口（emit）。
唯一例外：start() 在 config/env 显式指定 HIVE_JOBS_DIR 时往 **stderr** 打一行提示
（stdout 是协议通道，stderr 是诊断通道，两者不混流）。

v18 外评 D-1 修复（2026-09-23）：jobs 不再只由模块级常量决定——start/restart/rebuild
先 load_config，经 _jobs_from(合并环境) 延迟求值，config 里的 HIVE_JOBS_DIR 由此
真正参与决策；此前该键被静默丢弃（env_keys 自报含它、jobs_dir 却不变，fail-silent）。

批次69（C5）运维展示面：新增只读动作 `--show-config` 与 `start()` 启动前置校验。
三角色密钥（模型密钥 / 身份锚 / 身份令牌）此前只以文字散落在 README 与 config 模板里，
运维无从回答三个问题——「这个键的值从哪来（直值？哪个 env？哪个文件？）」「serve 起来
后执行器拿不拿得到它」「配置少哪一环会让 LLM 任务全灭」。--show-config 把三者做成逐行
可读事实，掩码走 `mask_secret` 单点函数（**绝不输出完整值**）；start() 在无可用模型密钥
且未声明 HIVE_LLM_DISABLED 真值时拒绝拉起（env 在启动时固化，残缺 serve 一旦上岗，
该池每个 LLM 任务都只在任务级 result.json 里报错）。
"""
import hashlib
import json
import os
import subprocess
import sys
import time

# ---------------------------------------------------------------- 入口自保证 UTF-8
# 约束（工作纪律第 15 条）：本调用必须在**任何文件/库 I/O 之前**——utf8_boot.ensure_utf8
# 在解释器未开 UTF-8 模式时以相同 argv 重启自身（-X utf8），早于它的任何 open/stdio
# 读写都走 locale 编码（Windows 中文机 = cp936：裸 open 抛 UnicodeDecodeError、中文写
# 落 GBK 字节）。本文件既是被拉起的 serve 启动器、又是 mcp_server 导入的库——本行
# 必须早于下方模块级常量与一切配置文件读取。仓库根入 sys.path 的形态照 hive/exec.py::
# _md_cg_import 的最小写法（助手在仓根，不是 md_cg 包目录）。
# 被 import（本模块非 __main__）时助手只置子进程继承面、绝不重启/退出——F6：静默重启
# 会吞掉调用方输入。本文件正是「既是启动器、又是被 mcp_server 导入的库」这一形态。
_UTF8_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _UTF8_ROOT not in sys.path:
    sys.path.insert(0, _UTF8_ROOT)
from utf8_boot import ensure_utf8  # noqa: E402

ensure_utf8(__file__)


HIVE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.environ.get("HIVE_CONFIG") or os.path.join(HIVE_DIR, "config.local.json")
# 与 mcp_server.py 的 _exe_path / _jobs_dir 同一口径（同一环境变量），避免两条拉起路径漂移
EXE = os.environ.get("HIVE_EXE") or os.path.join(
    HIVE_DIR, "target", "release", "hive.exe" if os.name == "nt" else "hive")
JOBS = os.environ.get("HIVE_JOBS_DIR") or os.path.join(HIVE_DIR, "jobs")
SERVE_LOG = os.path.join(JOBS, "_serve.log")
HEARTBEAT = os.path.join(JOBS, "_serve.json")


# 生效条件：env_map 给定（dict 形，如 os.environ 或 config 合并环境）；其 "HIVE_JOBS_DIR" 为非空字符串时返回该值，否则回落模块级 JOBS。jobs 决策的**唯一入口**——start/restart 经此延迟求值（D-1 修复：config 键此前被模块级常量静默丢弃）。
def _jobs_from(env_map):
    """从给定环境映射解析 jobs 目录：显式值 > 模块级默认。"""
    v = (env_map or {}).get("HIVE_JOBS_DIR")
    return v if isinstance(v, str) and v.strip() else JOBS
FRESH_S = 15  # 心跳新鲜窗口（serve 每拍 <1s 刷）。**须与 src/main.rs 的 FRESH_MS=15000 同值**——两面判「serve 是否在跑」必须同口径，否则同一个 serve 得两个结论

# ---- 配置展示面（C5，批次69）------------------------------------------------
# 三角色密钥表（README「密钥三角色」同源）：角色决定「到达执行器与否」，而到达面
# 由 hive/src/exec.rs::ORCH_SECRET_ENV_KEYS 的**身份面**剥离判据决定（N185 立闸，
# N190 收窄到身份两键）——两处表分叉即展示面与实况分叉，改一边须同时改另一边。
MODEL_KEY = "HIVE_API_KEY"        # 模型（网关）密钥：普通配置，随 serve env 默认继承给执行器
IDENTITY_KEYS = ("HIVE_ORCH_TOKEN", "HIVE_ORCH_TOKEN_FILE")   # 身份面：默认剥离，仅 orchestrate 任务条件重注
SUBAGENT_KEYS = ("HIVE_SUBAGENT_API_KEY", "HIVE_SUBAGENT_API_BASE")  # 可选子代理覆盖
LLM_DISABLED_KEY = "HIVE_LLM_DISABLED"   # 显式声明「本部署不跑 LLM」
_ORCH_ONLY_NOTE = "仅 spec.orchestrate 任务条件重注"
# 角色表：只登记有明确角色的键；未登记者一律「其他」（展示面不替未定义键猜角色）。
_ROLES = {
    MODEL_KEY: "模型密钥",
    "HIVE_ORCH_TOKEN": "身份令牌",
    "HIVE_ORCH_TOKEN_FILE": "身份锚",
    "HIVE_SUBAGENT_API_KEY": "子代理覆盖",
    "HIVE_SUBAGENT_API_BASE": "子代理覆盖",
}
# 无条件逐键展示的键（即使未设置也要出现——缺哪一环是展示面要回答的问题本身）。
_ALWAYS_SHOWN = (MODEL_KEY, LLM_DISABLED_KEY) + IDENTITY_KEYS + SUBAGENT_KEYS
# 已知配置面：既不在 config 也未在进程 env 出现的这些键（除 _ALWAYS_SHOWN）不逐条列出，
# 免得展示面被一堆「未设置」淹没；出现即列。
_WATCH_KEYS = _ALWAYS_SHOWN + ("HIVE_API_BASE", "HIVE_WEB_SEARCH_KEY",
                               "HIVE_WEB_SEARCH_BASE", "HIVE_EXEC_PY", "HIVE_JOBS_DIR")


# 生效条件：v 为 None 或空串返回空串；否则返回「至多 2 字符前缀（仅当长度 > 4）+ 长度 +
# sha256 前 8 位指纹」的掩码串。任何输入都不返回其完整内容。
def mask_secret(v):
    """单点掩码函数：`前缀少量 + 长度 + sha256 前 8 位指纹`，**绝不输出完整值**。

    全仓唯一的密钥展示出口——凡需要「让人肉眼核对面」的地方都调这里，不得各自
    拼字符串（某处漏掩就等于明文进了终端/日志/JSON-RPC 通道）。前缀只取 2 字符且
    仅当长度 > 4：短值取 0 字符，杜绝「掩码即明文」（3 字符的密钥加前缀就露全了）。
    长度与指纹让人能判断「是不是我期望的那把 key（改了没有）」，同时不泄值。
    """
    s = "" if v is None else str(v)
    if not s:
        return ""
    head = s[:2] if len(s) > 4 else ""
    fp = hashlib.sha256(s.encode("utf-8")).hexdigest()[:8]
    return f"{head}***len={len(s)}/sha256:{fp}"


# 生效条件：k 为 str 时返回 _ROLES 中登记的角色，未登记返回 "其他"；k 非 str 时同样返回 "其他"。
def role_of(k):
    """该 env 键的角色（模型密钥 / 身份锚 / 身份令牌 / 子代理覆盖 / 其他）。"""
    return _ROLES.get(k, "其他")


# 生效条件：k 为身份两键之一（HIVE_ORCH_TOKEN / HIVE_ORCH_TOKEN_FILE）返回 False；其余一律 True。
def reaches_executor(k):
    """该 env 键是否默认到达执行器 env（= exec.rs 的剥离面判据）。

    身份两键 False：serve 派发时**默认剥离**（执行器持之即可对任意任务自签合法锚、
    以 serve 身份认领 principal），唯一例外是 spec.orchestrate 真值任务条件重注。
    其余键 True：模型密钥 / 子代理覆盖 / base / 其他普通配置随 serve env 继承。
    """
    return k not in IDENTITY_KEYS


# 生效条件：v 为 str 返回「直值」；为含 "env" 键的 dict 返回 "env:<名字>"；为含 "file" 键的
# dict 返回 "file:<路径>"；其余（含非法形态）返回 "非法形态（须 str / {env:名} / {file:路径}）"。
def _source_of(v):
    """config 取值的来源描述（三形态）：直值 / env:名字 / file:路径。"""
    if isinstance(v, str):
        return "直值"
    if isinstance(v, dict):
        if "env" in v:
            return f"env:{v['env']}"
        if "file" in v:
            return f"file:{v['file']}"
    return "非法形态（须 str / {env:名} / {file:路径}）"


# 生效条件：path 存在且内容可 json.load 为 dict 时返回 (该 dict, None)；不存在 / 打不开 /
# 非 JSON / 根非对象时返回 (None, 可诊断错误串)。只读，不抛异常（展示面须能如实报出坏配置）。
def _raw_config(path):
    """读配置原文（展示面用）：与 load_config 同路径，但**不 fail fast**——坏配置如实报错。"""
    if not os.path.exists(path):
        return None, f"配置文件不存在：{path}"
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        return None, f"配置文件解析失败：{e}"
    if not isinstance(raw, dict):
        return None, "配置根不是 JSON 对象（键=环境变量名，值=三形态取值）"
    return raw, None


# 生效条件：env_map 为 dict（或 None）时，其 MODEL_KEY 为去空白非空的 str 返回 True，缺键/空串/非 str 返回 False。
def model_key_ready(env_map):
    """合并环境里模型密钥是否可用（非空字符串）。判据唯一点，start/展示面共用。"""
    v = (env_map or {}).get(MODEL_KEY)
    return isinstance(v, str) and bool(v.strip())


# 生效条件：env_map 为 dict（或 None）时，其 LLM_DISABLED_KEY 为 str、去空白后非空、且小写不在
# {"0","false","no"} 三值中时返回 True；缺键/其他类型/空串/假值串返回 False。
def llm_disabled(env_map):
    """HIVE_LLM_DISABLED 真值判定：去空白后非空且 lower 不在 {"0","false","no"}。

    口径沿用仓内既有先例（md_cg/writelimit.py:54-58 读 MDCG_WRITELIMIT：
    `str(v).strip().lower() not in ("0","false","no")`；md_cg/statushdr.py:45 同族，
    多认一个 "off"）——不自创第二套布尔真值语法。本键另加「非空」要求：空串/纯空白
    是「没声明」而不是「声明为假」，两者对门槛同效（都不放行），但语义要能区分。
    """
    v = (env_map or {}).get(LLM_DISABLED_KEY)
    if not isinstance(v, str):
        return False
    s = v.strip()
    return bool(s) and s.lower() not in ("0", "false", "no")


# 生效条件：model_key_ready(env_map) 为真返回 None；否则返回点明「该配哪个键 / 该声明哪个逃生键」的问题文案。
def _model_key_problem(env_map):
    """缺模型密钥的问题文案（None = 就绪）。start 前置校验与 --show-config 的 problems **同一判据、同一文案**。"""
    if model_key_ready(env_map):
        return None
    return (f"无可用模型密钥：{MODEL_KEY} 空/未设置（合并环境 = config.local.json 覆盖进程 env）"
            f"——该 serve 的每个 LLM 任务都会在 exec.py 入口报「{MODEL_KEY} 未设置」。"
            f"请配置它（如 {{\"{MODEL_KEY}\": {{\"env\": \"DEEPSEEK_API_KEY\"}}}}，或引一个 key 文件），"
            f"或声明 {LLM_DISABLED_KEY}=1（真值）表明本部署只跑确定性任务")


# 生效条件：config_path 缺省用模块常量 DEFAULT_CONFIG；始终返回 dict——{ok, config, keys, problems,
# llm_disabled, conclusion}，其中 keys 为逐键 {key, source, masked, role, reaches_executor}（值空时
# 多带 empty=True 与 note），ok=False 当且仅当「配置不可用」或「无可用模型密钥且未声明 HIVE_LLM_DISABLED」。
def show_config(config_path=None):
    """只读配置展示：逐键 来源 · 掩码值 · 角色 · 是否到达执行器 + problems + 结论。

    为什么存在（C5）：三角色密钥的配置正确性此前只能靠人读 README + 猜 env 来源；
    配错的表现是「任务全失败」而非「配置少一键」。本函数把合并面（config 覆盖进程 env，
    与 start() 传给 serve 的 env 同口径）逐键摊开，且**只读**——不改 env、不落盘、
    不拉起/探测任何进程。掩码走 mask_secret 单点函数：能核对面，看不到秘密。

    **只读面不拒答**：配置坏 / 缺模型密钥时它照样返回完整 JSON（`ok` 的语义是
    「这份配置能拉起 serve 吗」而非「这次读取成功吗」，故缺密钥时 ok=False 而
    keys/problems/结论 一个不少）——缺密钥的运维恰恰靠它看诊断，不能连读面一起
    拒掉；`--show-config` 也**不触发** start() 的启动前置校验（无进程被拉起）。
    """
    cfg = config_path or DEFAULT_CONFIG
    raw, cfg_err = _raw_config(cfg)
    raw = raw or {}
    problems: list = []
    if cfg_err:
        problems.append(cfg_err)
    cfg_env, bad_keys = {}, []
    for k, v in raw.items():
        if k.startswith("_"):
            continue
        val = resolve(v)
        if val is None:
            bad_keys.append(k)
            problems.append(f"配置项解析失败：{k}（来源 {_source_of(v)} 未设或文件不可读）"
                            f"——strict 口径（load_config）会因它拒绝拉起")
        else:
            cfg_env[k] = val
    merged = {**os.environ, **cfg_env}
    keys = sorted(set(cfg_env) | set(bad_keys) | set(_ALWAYS_SHOWN)
                  | {k for k in _WATCH_KEYS if k in os.environ})
    entries = []
    for k in keys:
        in_cfg = k in raw and not k.startswith("_")
        e = {"key": k,
             "source": _source_of(raw[k]) if in_cfg else f"env:{k}（进程环境）",
             "role": role_of(k),
             "reaches_executor": reaches_executor(k)}
        val = cfg_env.get(k, "") if in_cfg else (os.environ.get(k) or "")
        e["masked"] = mask_secret(val)
        if not val:
            e["empty"] = True
            e["note"] = ("未设置/空值；" + _ORCH_ONLY_NOTE) if k in IDENTITY_KEYS else "未设置/空值"
        elif k in IDENTITY_KEYS:
            e["note"] = _ORCH_ONLY_NOTE
        entries.append(e)
    mk_problem = _model_key_problem(merged)
    if mk_problem:
        problems.append(mk_problem)
    if not any((merged.get(k) or "").strip() for k in IDENTITY_KEYS):
        problems.append("身份面未配置：HIVE_ORCH_TOKEN / HIVE_ORCH_TOKEN_FILE 均空"
                        "——锚判据整体不启用（安全方向降级，行为=旧产物判据，见 keyres.rs 头注）"
                        "；编排任务会在 orch.py load_principal 处 fail-closed")
    disabled = llm_disabled(merged)
    if cfg_err:
        conclusion = "不可拉起：配置文件不可用（见 problems）"
    elif bad_keys:
        conclusion = "不可拉起：配置项解析失败（fail fast，见 problems）"
    elif mk_problem and not disabled:
        conclusion = f"不可拉起：无可用模型密钥（配 {MODEL_KEY}，或声明 {LLM_DISABLED_KEY}）"
    elif disabled:
        conclusion = f"可拉起（模型面已声明关闭：{LLM_DISABLED_KEY} 真值）——仅确定性任务可用"
    else:
        conclusion = "可拉起（模型密钥就绪）"
    return {"ok": not (cfg_err or bad_keys or (bool(mk_problem) and not disabled)),
            "config": cfg, "keys": entries, "problems": problems,
            "llm_disabled": disabled, "conclusion": conclusion}


# 生效条件：obj 为 dict（非 dict 时 obj.get 会抛 AttributeError）时打印其 ensure_ascii=False 的 JSON，并返回 0 当 obj.get("ok") 为真值，否则返回 1（ok 缺失或为 0/""/None/[] 等假值同样返回 1）。
def emit(obj):
    """打印 + 返回退出码。**只有 CLI 入口用它**；库层调用请直接取返回值。"""
    print(json.dumps(obj, ensure_ascii=False))
    return 0 if obj.get("ok") else 1


# 生效条件：v 为 str 时原样返回（空串也返回空串）；v 为含 "env" 键的 dict 时返回 os.environ.get(该名, "") 去空白后的值、空串则回落 None；v 为 dict 且无 "env" 键但有 "file" 键时读该路径去空白、空则 None、抛 OSError 则 None（非 UTF-8 内容抛出的 UnicodeDecodeError 未被捕获）；其余 dict 及非 str/dict 一律返回 None。
def resolve(v):
    """配置值三形态解析：str 直值 / {"env": name} / {"file": path}。失败返回 None。"""
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        if "env" in v:
            return os.environ.get(v["env"], "").strip() or None
        if "file" in v:
            try:
                with open(v["file"], "r", encoding="utf-8") as f:
                    return f.read().strip() or None
            except OSError:
                return None
    return None


# 生效条件：path 不存在时直接返回 (None, "配置文件不存在：{path}")；存在但 open/json.load 抛 OSError 或 ValueError 时返回解析失败；读入 JSON 对象后遍历其键，下划线开头键跳过，其余键经 resolve 得 None 即记入 bad 并返回 (None, 配置项解析失败…)，全部通过返回 (env, None)。
def load_config(path):
    if not os.path.exists(path):
        return None, f"配置文件不存在：{path}"
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        return None, f"配置文件解析失败：{e}"
    env, bad = {}, []
    for k, v in raw.items():
        if k.startswith("_"):
            continue
        val = resolve(v)
        if val is None:
            bad.append(k)
        else:
            env[k] = val
    if bad:
        return None, f"配置项解析失败（来源 env 未设或文件不可读）：{', '.join(bad)}"
    return env, None


# 生效条件：jobs 为真值时读 os.path.join(jobs, "_serve.json")，jobs 为 None 或空串等假值时回落模块常量 HEARTBEAT，该路径能打开且 json.load 成功则返回其内容，抛 OSError/ValueError 则返回 None。
def heartbeat(jobs=None):
    """读 serve 心跳。jobs 给定时读该 jobs 目录的 `_serve.json`（MCP 面用于对齐自己的 jobs）。"""
    path = os.path.join(jobs, "_serve.json") if jobs else HEARTBEAT
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# 生效条件：对传入的 pid（未做类型与正负校验，比较用 str(pid)）执行 tasklist /FO CSV 后，在其 stdout 中遇到的第一个按 '","' 切分、列数≥2 且第 2 列 strip 再 strip('"') 后等于 str(pid) 的行即返回 [第 1 列映像名, pid 字符串]，无此行或 subprocess.run 抛 OSError 时返回 None。
def _tasklist_row(pid):
    """Windows：查该 pid 的 tasklist 行 → [映像名, pid 字符串]；查不到返回 None。

    用 `/FO CSV` 后按列精确比对，**不用子串包含**——旧实现 `pid 字符串 in 输出`
    会让 pid=441 被 4410 命中（假存活）。
    """
    try:
        # 显式 utf-8 + replace：只消费 ASCII 的 pid 列，但**不依赖 locale**——
        # 否则子进程后代按 cp936 解 UTF-8 诊断时读线程会崩（2026-09-20 取证，
        # 见 md_cg/test_subproc_encoding.py 头注）。
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in (r.stdout or "").splitlines():
        cols = line.split('","')
        if len(cols) >= 2 and cols[1].strip().strip('"') == str(pid):
            return [cols[0].strip().strip('"'), cols[1].strip().strip('"')]
    return None


# 生效条件：pid 为 int 且大于 0 时（否则直接返回 False），os.name 为 "nt" 时返回 _tasklist_row(pid) 是否非 None，非 "nt" 时 os.kill(pid, 0) 未抛 OSError 返回 True、抛 OSError 返回 False。
def pid_alive(pid):
    """该 pid **号**是否存在（Windows tasklist 精确列比对 / unix `kill -0`）。

    只回答「这个号有没有进程」——**不足以判定「serve 还在跑」**，见 `pid_is_self_program`。
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


# 生效条件：模块常量 EXE 的 basename 小写 want 非空且 pid 为 int 大于 0 时（否则 False），"nt" 下要求 _tasklist_row(pid) 非空且其映像名小写等于 want，非 "nt" 下要求 /proc/<pid>/cmdline 首个 b"\x00" 前 token 的 basename 小写等于 want（读取抛 OSError 则 False），相等返回 True，否则 False。
def pid_is_self_program(pid):
    """该 pid 是否**就是本程序**（同映像名）——pid 号会被无关进程复用。

    2026-09-17 第三方 v13 实测缺陷（新发现 A）：单实例守卫原判据只问「pid 号是否
    存在」，任何无关进程（如 sleep）复用该 pid 号都会让 serve 被「假存活」挡住拒绝
    启动，且文案引导运维去停一个并不存在的 serve。故加一层身份核对：
    Windows 取 tasklist 映像名列，unix 读 `/proc/<pid>/cmdline` 首个 token 的 basename。

    零依赖边界：拿不到映像名返回 False（宁可放行启动，也不误报「已有 serve 在跑」）
    ——存活与新鲜仍由另两层判据把守（`serve_alive` 三层全真才判活）。
    """
    want = os.path.basename(EXE).lower()
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


# 生效条件：heartbeat(jobs) 为假值、或其 ts 键缺省记 0 使 age ≥ FRESH_S*1000 毫秒时返回 False；否则以 hb.get("pid")（缺键为 None）同时满足 pid_alive 与 pid_is_self_program 才返回 True。
def serve_alive(jobs=None):
    """serve 存活三层判据：心跳新鲜 **且** pid 存活 **且** 该 pid 是本程序。

    三层缺一不可：只看新鲜度 → 崩溃后残留心跳冒充存活；只看 pid 号 → 无关进程
    复用的 pid 冒充 serve（v13 实测）。与 rust `serve_running` / `cmd_doctor`、
    MCP `_serve_alive` 同一口径（跨语言靠常量注释约定 + `hive/test_serve_entry.py` 守卫）。
    """
    hb = heartbeat(jobs)
    if not hb:
        return False
    if (time.time() * 1000 - hb.get("ts", 0)) >= FRESH_S * 1000:
        return False
    pid = hb.get("pid")
    return pid_alive(pid) and pid_is_self_program(pid)


# 生效条件：jobs 缺省时按模块级 HEARTBEAT 判活；serve_alive(jobs) 为假时返回 ok:True 的 stopped:False（无心跳报「serve 未在运行」，有陈旧心跳如实说明 pid 与原因——「--stop 说没在跑 / 启动又被挡住」不可同时失效，v13 实测）；判活为真时按 os.name 用 taskkill /PID … /T /F（树杀，N92 批次 49——check=True）或 os.killpg(os.getpgid(pid), 15)（N92——serve 即进程组长，组杀覆盖 worker 树；unix 真实群杀行为 win 上不可动态验证，见 test_stop_tree_kill.py 诚实边界），抛 CalledProcessError/OSError 返回 ok:False 的「停止失败 pid=…」，否则最多轮询 30 次×0.5s serve_alive(jobs)（未转假也照常退出循环）后一律返回 ok:True 的 stopped:True 并附 pid。
def stop(jobs=None):
    hb = heartbeat(jobs)
    if not hb or not serve_alive(jobs):
        # 陈旧心跳要如实说明原因——否则「--stop 说没在跑 / 启动又被挡住」会成为
        # 两个同时失效的逃生口（v13 实测：守卫与 stop 判据不一致时正是如此）。
        if hb:
            pid = hb.get("pid")
            why = "该 pid 已不存在" if not pid_alive(pid) else "该 pid 不属于本程序"
            return {"ok": True, "stopped": False,
                    "note": f"serve 未在运行（存在陈旧心跳：pid={pid}，{why}）——可直接启动，无需 --stop"}
        return {"ok": True, "stopped": False, "note": "serve 未在运行"}
    pid = hb.get("pid")
    try:
        if os.name == "nt":
            # N92（批次 49，2026-09-26）：/T 树杀——serve 的执行器 worker 是
            # 它的子进程，只杀单 pid 会把整棵执行器树留成孤儿（持 serve 配置
            # 凭据继续外呼、晚落 result 与新 serve recover_orphans 并发同
            # job）。/T /F 形态与同仓 rust 先例一致（hive/src/exec.rs
            # kill_tree，且其守卫 kill_tree_kills_grandchildren 同判据）。
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", check=True)
        else:
            # N92 unix 臂：serve 由 start() 以 start_new_session=True 拉起
            # （见下方 start()），即会话/进程组长——killpg(getpgid(pid)) 覆盖
            # serve 及其 worker 全组，与 nt /T 等价。getpgid 顺带兜住 pid 复用
            # （按 pid 现查组而非沿用心跳里的旧号）。
            os.killpg(os.getpgid(pid), 15)
    except (subprocess.CalledProcessError, OSError) as e:
        return {"ok": False, "error": f"停止失败 pid={pid}: {e}"}
    # 等心跳过期确认真停了
    for _ in range(30):
        if not serve_alive(jobs):
            break
        time.sleep(0.5)
    return {"ok": True, "stopped": True, "pid": pid}


# 生效条件：load_config(config_path) 报错时原样返回该 error；配置通过则先 C5 启动前置校验——model_key_ready(合并环境) 为假且 llm_disabled(合并环境) 为假时返回 ok:False 的「启动前置校验未通过——<缺模型密钥文案>」；校验通过后再判 serve_alive() 为真时返回 ok:False 的「已在运行（pid=hb.get('pid')）」；否则按合并环境延迟解析 jobs（config/env 的 HIVE_JOBS_DIR > 模块级默认，见 _jobs_from）并建目录、以合并环境 Popen([EXE, "serve", "--jobs", <延迟 jobs>])，Popen 抛 OSError 返回「拉起失败」，否则最多 20 次 ×0.5s 轮询 serve_alive(jobs)，出现心跳即返回 ok:True（含 pid/workers/jobs_dir=<实际生效目录>/env_keys/config=config_path；HIVE_LLM_DISABLED 真值时多带 llm_disabled=True 与 note），20 轮仍无则返回该目录日志末尾 400 字符的「心跳未出现」。
def start(config_path):
    """拉起 serve（已在跑则拒绝）。返回 dict；调用方决定是否打印。"""
    env, err = load_config(config_path)
    if err:
        return {"ok": False, "error": err}
    merged = {**os.environ, **env}
    # C5 启动前置校验（批次69）：无可用模型密钥且未声明 HIVE_LLM_DISABLED 真值 → 拒绝
    # 拉起。为什么必须前置：serve 的 env 在启动时固化（子进程无法反查），残缺 serve 一旦
    # 上岗，该池**每个** LLM 任务都只在任务级 result.json 里报「HIVE_API_KEY 未设置」——
    # 运维看到的是「任务全失败」而不是「配置缺一键」。判据/文案单点 = _model_key_problem
    # （--show-config 的 problems 同源，两处不复制）。逃生门：声明 HIVE_LLM_DISABLED
    # 真值（只跑确定性任务的部署）→ 放行，且在结果里回带提示。
    problem = _model_key_problem(merged)
    llm_off = llm_disabled(merged)
    if problem and not llm_off:
        return {"ok": False, "error": f"启动前置校验未通过——{problem}"}
    # D-1 修复（v18 外评，2026-09-23）：jobs 延迟到合并环境求值——config 里的
    # HIVE_JOBS_DIR 由此真正参与决策。此前模块级 JOBS 在 import 时固化并被
    # `--jobs` 显式钉死，config 键被静默丢弃（fail-silent，违背 fail-fast）。
    # 「已在跑」检查同样按目标池判——config 换池时不能拿默认池的在跑状态挡人。
    jobs = _jobs_from(merged)
    if serve_alive(jobs):
        hb = heartbeat(jobs)
        return {"ok": False, "error": f"serve 已在运行（pid={hb.get('pid')}），先 --stop 再启动"}
    if jobs != JOBS:
        print(f"[serve_start] HIVE_JOBS_DIR 来自 config/env：{jobs}"
              f"（模块级默认 {JOBS} 不生效）", file=sys.stderr)
    os.makedirs(jobs, exist_ok=True)
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    logf = open(os.path.join(jobs, "_serve.log"), "ab")
    try:
        # close_fds=True 必须显式指定（含 Windows）：detached 的 serve 是长命进程，
        # 若关掉 close_fds 关闭语义，它会继承调用进程的可继承句柄——包括 IDE/终端
        # 用于捕获输出的管道。调用方随后读不到 EOF，表现为「命令跑着永不返回」
        # （2026-09-16 实测：后台脚本挂死 26 分钟，根因即此处）。
        # Python 3.7+ 在 Windows 上 close_fds=True 仍能正确传递显式 std 句柄。
        subprocess.Popen(
            [EXE, "serve", "--jobs", jobs],
            stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            env=merged, cwd=HIVE_DIR, creationflags=flags,
            start_new_session=(os.name != "nt"), close_fds=True)
    except OSError as e:
        logf.close()
        return {"ok": False, "error": f"拉起失败（先 cargo build --release？）: {e}"}
    for _ in range(20):  # 等首个心跳
        if serve_alive(jobs):
            hb = heartbeat(jobs)
            res = {"ok": True, "pid": hb.get("pid"), "workers": hb.get("workers"),
                   "jobs_dir": jobs,
                   "env_keys": sorted(env.keys()),
                   "config": config_path}
            if llm_off:
                # C5：声明了「本部署不跑 LLM」的放行要**可见**——否则下一个运维看到
                # LLM 任务全失败时，不知道这是声明的后果而非配置事故。
                res["llm_disabled"] = True
                res["note"] = (f"{LLM_DISABLED_KEY} 已声明：模型面关闭——本 serve 只跑确定性"
                               f"任务；要跑 LLM 请配置 {MODEL_KEY} 并去掉该键后 --restart")
            return res
        time.sleep(0.5)
    tail = ""
    try:
        with open(os.path.join(jobs, "_serve.log"), "r",
                  encoding="utf-8", errors="replace") as f:
            tail = f.read()[-400:]
    except OSError:
        pass
    return {"ok": False, "error": f"serve 心跳未出现，日志尾部：{tail}"}


# 生效条件：config_path 给定；先 load_config 并按合并环境经 _jobs_from 解析目标 jobs（config 的 HIVE_JOBS_DIR 参与，与 start 同口径），再调 stop(jobs)（serve 未在跑时其 stopped=False 且如实 note，不算失败），stop() 返回 ok 为假（taskkill/kill 失败）即返回 ok:False 的 stage=stop 错误并附 stop 段；否则调 start(config_path)，其结果 dict 原样返回并附 restart 段（stopped=本次是否真的停了旧实例 / old_pid / note=stop 的说明）。
def restart(config_path):
    """重启 serve：stop（如在跑）→ start。改 config.local.json 或换执行器后用它使改动生效。

    为什么存在：serve 级配置（env/执行器/worker 数）在启动时固化，改动必须重启
    serve 才生效；此前唯一的重启方式是「--stop 再手动启动」两步人肉——步骤断档时
    会出现「以为重启了、实际旧 serve 还带着旧配置在跑」。本函数把两步合成原子序：
    stop 失败（杀不掉）则**绝不 start**（防双实例抢队列）；stop 报「未在运行」
    （含陈旧心跳）不算失败，直接进入 start。

    stop 的目标池按**新 config 解析出的 jobs**（与 start 同口径，D-1 修复）——
    「实例」本就是 per-jobs 目录概念；旧实例若跑在别的池，不归本次重启管。
    """
    env, err = load_config(config_path)
    if err:
        return {"ok": False, "stage": "stop", "error": err}
    jobs = _jobs_from({**os.environ, **(env or {})})
    stop_res = stop(jobs)
    if not stop_res.get("ok"):
        return {"ok": False, "stage": "stop",
                "error": stop_res.get("error") or "stop 失败", "stop": stop_res}
    start_res = start(config_path)
    start_res["restart"] = {
        "stopped": stop_res.get("stopped", False),
        "old_pid": stop_res.get("pid"),
        "note": stop_res.get("note"),
    }
    return start_res


# 生效条件：无必需形参；HIVE_CARGO 指向存在的文件时返回该值，否则 ~/.cargo/bin/cargo(.exe) 存在时返回它，再否则 shutil.which("cargo") 的结果（可能为 None）。
def find_cargo():
    """定位 cargo：HIVE_CARGO env > ~/.cargo/bin > PATH。

    为什么不能只靠 PATH：serve 常由 detached/受限 env 的进程拉起，cargo 常不在
    PATH（2026-09-22 实测：宿主终端 `where cargo` 都找不到，cargo 只在
    ~/.cargo/bin）。找不到返回 None——调用方 fail-closed，不猜。
    """
    p = os.environ.get("HIVE_CARGO")
    if p and os.path.isfile(p):
        return p
    name = "cargo.exe" if os.name == "nt" else "cargo"
    home = os.path.join(os.path.expanduser("~"), ".cargo", "bin", name)
    if os.path.isfile(home):
        return home
    from shutil import which
    return which("cargo")


# 生效条件：config_path 给定；先调 stop()（ok 为假即返回 stage=stop 错误），随后 find_cargo() 为 None 时返回 stage=build 错误（serve 保持停止态），cargo build --release（cwd=HIVE_DIR）返回码非 0 时返回 stage=build 错误并附 stderr/stderr 尾 800 字符（serve 保持停止态），成功则调 start(config_path) 并在结果 dict 附 rebuild 段（stopped/old_pid/cargo）。
def rebuild(config_path):
    """重编译并重启：stop → cargo build --release → start。rust 改动一条命令生效。

    为什么 --restart 不够（2026-09-22 实测缺陷）：Windows 锁定运行中的可执行文件，
    serve 在跑时 `cargo build --release` 报 os error 5（拒绝访问）写不进 hive.exe；
    --restart 的 stop→start 中间插不进 build，等于「重启了个旧二进制」还以为改动了
    生效。本函数把三步合成原子序，且 **build 失败保持停止态**（fail-closed：宁可
    serve 停着，也不让旧二进制假活）——错误信息注明用 --restart 恢复。
    """
    env, err = load_config(config_path)
    if err:
        return {"ok": False, "stage": "stop", "error": err}
    stop_res = stop(_jobs_from({**os.environ, **(env or {})}))
    if not stop_res.get("ok"):
        return {"ok": False, "stage": "stop",
                "error": stop_res.get("error") or "stop 失败", "stop": stop_res}
    cargo = find_cargo()
    if not cargo:
        return {"ok": False, "stage": "build",
                "error": ("未找到 cargo（设 HIVE_CARGO 指向 cargo.exe，或安装 Rust 工具链）"
                          "——serve 已停；修复后用 --restart 或 --rebuild 拉起"),
                "stop": stop_res}
    try:
        r = subprocess.run([cargo, "build", "--release"], cwd=HIVE_DIR,
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except OSError as e:
        return {"ok": False, "stage": "build",
                "error": f"cargo 启动失败（serve 已停）：{e}", "stop": stop_res}
    if r.returncode != 0:
        tail = ((r.stderr or "") + (r.stdout or ""))[-800:]
        return {"ok": False, "stage": "build",
                "error": f"cargo build --release 失败（serve 已停；修复后 --restart 拉起）：\n{tail}",
                "stop": stop_res}
    start_res = start(config_path)
    start_res["rebuild"] = {"stopped": stop_res.get("stopped", False),
                            "old_pid": stop_res.get("pid"), "cargo": cargo}
    return start_res


# 生效条件：cfg 给定（配置文件路径）；load_config(cfg) 得 (env, err)，返回 _jobs_from({**os.environ, **(env or {})})——env 为 None（配置缺失/解析失败）时合并项为空、自然回落 env/模块级默认 JOBS，config 错误**不阻断**生命周期命令。
def _lifecycle_jobs(cfg):
    """--stop/--status 的目标池解析（D-1 修复续，2026-09-25）：与 start/restart/
    rebuild 同口径经 _jobs_from 吃进 config 的 HIVE_JOBS_DIR。

    此前两条 CLI 生命周期路径不经 config——config-only 设该键时 serve 跑在
    池 B，`--stop` 盯着池 A 报「未在运行」停不掉真 serve、`--status` 永远
    alive=false（fail-silent，正是 v13 要消灭的失效对残余）。config 加载失败
    时降级为仅 env 决策（--stop 不能因 config 笔误而停不掉 serve——比
    restart/rebuild 的 fail-fast 更宽容，因二者失败可重试而 stop 须尽力）。"""
    env, _err = load_config(cfg)
    return _jobs_from({**os.environ, **(env or {})})


# 生效条件：jobs 给定时以其为池（None/空串回落模块级 JOBS），始终返回 {ok:True, alive, heartbeat, jobs_dir:<生效池>}；hb 为真而 serve_alive(jobs) 为假时额外附 stale_heartbeat（pid、pid_alive(pid)、pid_is_self_program(pid)、以及按 hb.get("ts", 0) 缺失记 0 算出的 age_s）；alive 为真且生效池路径存在时额外遍历其中各子目录的 status.json，把 json.load(f).get("state", "?")（缺 state 键记 "?"，抛 OSError/ValueError 的条目跳过）按值计数写入 job_states。
def status(jobs=None):
    jobs = jobs or JOBS
    hb = heartbeat(jobs)
    alive = serve_alive(jobs)
    info = {"ok": True, "alive": alive, "heartbeat": hb, "jobs_dir": jobs}
    if hb and not alive:
        # 判死时给出三层判据明细——运维一眼看出是「心跳过期」还是「pid 假存活」，
        # 而不是只拿到一个 false 去猜。
        pid = hb.get("pid")
        info["stale_heartbeat"] = {
            "pid": pid,
            "pid_alive": pid_alive(pid),
            "pid_is_self_program": pid_is_self_program(pid),
            "age_s": round((time.time() * 1000 - hb.get("ts", 0)) / 1000.0, 1),
        }
    if alive and os.path.exists(jobs):
        states = {}
        for jid in os.listdir(jobs):
            sp = os.path.join(jobs, jid, "status.json")
            if not os.path.isfile(sp):
                continue
            try:
                with open(sp, "r", encoding="utf-8") as f:
                    st = json.load(f).get("state", "?")
                states[st] = states.get(st, 0) + 1
            except (OSError, ValueError):
                pass
        info["job_states"] = states
    return info


# 生效条件：参数取自 sys.argv[1:]（"--config" 存在时取其紧随的一项作为 cfg，缺该项会在 args[i+1] 抛未捕获的 IndexError，否则用模块常量 DEFAULT_CONFIG）；处理后 args 仍含 "--show-config" 时返回 emit(show_config(cfg))（只读，不探测进程、不改运行态）、含 "--stop" 时返回 emit(stop(_lifecycle_jobs(cfg)))、含 "--status" 时返回 emit(status(_lifecycle_jobs(cfg))) 并在其结果 dict 上附 config_summary=show_config(cfg)（同一份摘要走同一函数，判据不复制；目标池与 start/restart/rebuild 同口径，D-1 修复续），其余情形返回 emit(start(cfg))。
def main():
    args = sys.argv[1:]
    cfg = DEFAULT_CONFIG
    if "--config" in args:
        i = args.index("--config")
        cfg = args[i + 1]
        args = args[:i] + args[i + 2:]
    if "--show-config" in args:
        return emit(show_config(cfg))
    if "--rebuild" in args:
        return emit(rebuild(cfg))
    if "--restart" in args:
        return emit(restart(cfg))
    if "--stop" in args:
        return emit(stop(_lifecycle_jobs(cfg)))
    if "--status" in args:
        st = status(_lifecycle_jobs(cfg))
        # C5：--status 附同一份配置摘要（复用 show_config，不另立判据/文案）
        st["config_summary"] = show_config(cfg)
        return emit(st)
    return emit(start(cfg))


if __name__ == "__main__":
    sys.exit(main())