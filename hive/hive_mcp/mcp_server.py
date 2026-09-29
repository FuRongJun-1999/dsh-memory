# -*- coding: utf-8 -*-
"""灵枢蜂巢 · MCP server（蜂群多智能体并发运行时对外接口）。

形态对齐 md_cg/mcp_server.py：手写 stdio JSON-RPC 2.0，零第三方依赖。
与 hive 的通信走**文件协议**（jobs/<id>/{spec,status,result,kill} + _serve.json
心跳），零 IPC 依赖；serve 未存活时 spawn/poll 自动拉起（detached）。

启动：
    HIVE_JOBS_DIR=<jobs 目录> python -m hive.hive_mcp.mcp_server
（hive/ 为 python 包：PYTHONPATH 指向 dsh-memory 仓根）

工具面（5 个）：
  hive_spawn   提交任务（model/user_prompt **与四槽 identity/task/unit** 必填）→
               job_id（由 Rust 侧 `hive alloc-id` 独占创建得出）即返。可选：
               system_prompt/context_files/max_tokens/temperature/thinking/
               tools/max_tool_rounds/mdcg_root/web_search_backend/depends_on。
               depends_on（H-6）= 上游 job_id 列表，全 done 才被领取（失败传播见
               scheduler::deps_gate）；本面在写入 spec 前过与 CLI 同判据的两道闸
               （格式 = h 开头且不含路径成分；存在性 = jobs/<dep> 是目录），
               不满足即 fail-closed 拒绝（不静默忽略、不降级为「无依赖」）。
               id 契约 v2（B8）：id = `h_<身份>_<任务>_<单元>_<编号>`，四槽之三
               必填、编号由 Rust 侧分配器给；**本面不再自造 id**（旧
               `h{毫秒}_{uuid6}` 已退场），HIVE_EXE 不可用即显式报错（不静默降级）。
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
import subprocess
import sys
import time
import unicodedata
import uuid

# ---------------------------------------------------------------- 入口自保证 UTF-8
# 约束（工作纪律第 15 条）：本调用必须在**任何文件/库 I/O 之前**——utf8_boot.ensure_utf8
# 在解释器未开 UTF-8 模式时以相同 argv 重启自身（-X utf8），早于它的任何 open/stdio
# 读写都走 locale 编码（Windows 中文机 = cp936：裸 open 抛 UnicodeDecodeError、中文写
# 落 GBK 字节）。本文件下方 _package_version() 就在**模块级**读 package.json，故锚点
# 必须落在它之前。仓库根入 sys.path 的形态照 hive/exec.py::_md_cg_import 的最小写法
# （助手在仓根，不是 md_cg 包目录）。
# 被 import（本模块非 __main__）时助手只置子进程继承面、绝不重启/退出——F6：静默重启
# 会吞掉调用方输入；本入口的真实接入形态是 `python -m hive.hive_mcp.mcp_server`。
_UTF8_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if _UTF8_ROOT not in sys.path:
    sys.path.insert(0, _UTF8_ROOT)
from utf8_boot import ensure_utf8  # noqa: E402

ensure_utf8(__file__)


# SERVER_VERSION 从包根 package.json 动态读取（issue #42 同族：硬编码与发布
# 版本脱节）；读不到回落 "0.1.0" 保底不阻塞启动。
# v21-R1（2026-09-28）：**回落必须覆盖全形态**——修前只捉 (OSError, ValueError)
# 却无条件 `.get("version")`，顶层是合法 JSON 但非对象（`[1,2]`/`"0.9.9"`/`123`/
# `null`/`true`）时 AttributeError 逃出 except，而本句在**模块级**立即求值 ⇒
# `python -m hive.hive_mcp.mcp_server` 连 initialize 都发不出就退出（服务起不来）；
# `{"version": 123}` 不抛但把 int 塞进握手 serverInfo.version（协议要字符串）。
# 同族已修：md_cg/mcp_server.py。
def _package_version() -> str:
    """读包根 package.json 的 version；**任何**形态异常都回落 "0.1.0"。

    生效条件：文件可读、json.load 得 dict、且 doc["version"] 为 strip() 后非空
    的 str 时返回该值；文件缺失 / OSError / JSON 非法 / 顶层非对象 / version
    缺失·非字符串·空白串时一律回落 "0.1.0"（TypeError、AttributeError 一并兜底，
    绝不把异常抛给 import 期）。
    """
    try:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        with open(os.path.join(root, "package.json"), encoding="utf-8") as f:
            doc = json.load(f)
        ver = doc.get("version") if isinstance(doc, dict) else None
    except (OSError, ValueError, TypeError, AttributeError):
        return "0.1.0"
    return ver if isinstance(ver, str) and ver.strip() else "0.1.0"


SERVER_NAME = "hive-mcp"
SERVER_VERSION = _package_version()
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


# ==================================================== id 契约 v2 孪生闸（B4/B5）
#
# 判据真源 = `hive/src/job.rs::valid_job_id`（Rust 侧是单点，契约 §五 裁决 3）。
# 本段是它在 python 面的**孪生**——两侧对任何一例必须**同判**，逐例证据 =
# `hive/id_contract_corpus_v2.txt`（两侧共读同一份语料：Rust 单测
# `id_contract_corpus_verdicts` 与守卫 `hive/test_id_contract_v2.py` 各自解码同一
# 份 hex，任一侧判反即红）。**不许改语料迁就实现**。
#
# 结构逐条对齐 Rust（顺序都一致，顺序会改变错误文本）：
#   ① h 前缀与非空；② 首尾空白；③ 尾点；④ 单独的 `.`/`..`；
#   ⑤ 逐字符：控制/路径成分 → 零宽/双向控制 → `_`/`.` 直通 → NFC 稳定字母数字；
#   ⑥ 整 id 的 Windows 保留设备名；⑦ 按 `_` 分段的保留设备名（Win32 按分量解析）。
#
# 字符类判据按 Rust 的**两层**实现（B5）：`char::is_alphanumeric() && !会改写的区块`。
# 第一层 `_rust_alphanumeric` 之所以不直接用 `str.isalnum()`：两者**实测不同判**
#   ① Python `isalpha()` 只含 Lu/Ll/Lt/Lm/Lo，Rust `is_alphabetic()` 还含
#      Unicode `Other_Alphabetic`（大量 Mn/Mc 组合形与少量 So）⇒ 实测 1405 个码点
#      「Rust 收而 Python 拒」；
#   ② 反向（Python 收而 Rust 拒）不存在：Python 的 alpha/numeric 类目是 Rust
#      `is_alphabetic`/`is_numeric` 的真子集——**已完备证明**（守卫 C8：把全部
#      ~14 万个 Python 收的单字符批量喂给真 hive.exe，批量+二分定位反例，非抽样）。
#   故下表 `OTHER_ALPHABETIC_BLOCKS` 是**实测导出**的补齐闭集，把①抹平。
#
# 残余（**已实测、已声明、方向安全**，不是假设）：两侧的 Unicode 表各自演化，
# Python 判「未分配(Cn)」而 Rust 工具链已赋值的**字母**会出现「Python 拒 / Rust 收」。
# 实测（2026-09-30，Python `unicodedata` 15.0.0 × 本机 rust 工具链）：Cn 码点
# 825345 个中，Rust 收而 Python 判未分配的 **9713 个（56 个区间）**，如
# U+088F / U+1C89..U+1C8A（Todhri）/ U+2EBF0..U+2EE5D（CJK 扩展 I）——即
# 「Unicode 15.1/16 新增的字母」。该方向**只让本面更严**（Python 永不更松，越权面
# 为零），且不落任何表（嵌一张随 Unicode 版本陈化的表，收益为零而带来静默陈化风险；
# Python 解释器升级即自动收敛）。重导方法：对 `unicodedata.category(c)=="Cn"` 的
# 全部码点逐个问 `hive.exe poll "h"+c` 的 ok 字段（实测耗时 ≈44 分钟，
# 24 线程；故不入常规守卫，改为**声明 + 守卫 C9 逐轮实测该残余的定性/方向**）。

# Unicode `Other_Alphabetic` 补齐闭集（左闭右闭，**实测导出**，不是抄来的区间）：
# 导出方法 = 对「`str.isalnum()` 为假且类目 ∈ {Mn, Mc, Me, So, Sk, Sm, Po, Pc, Cf,
# No, Nd, Nl, Sc, Zs}」的全部 11045 个码点，逐个以**真 hive.exe 的判据**（
# `hive.exe poll` 的 ok 字段）问一遍，取「Rust 收而 Python 拒」者（1405 个，剔除
# `_` U+005F——它由结构分支直通）。结果按类别：Mn 904 / Mc 423 / So 78；
# 其余候选类别零命中 ⇒ 分歧集**恰好**落在 Mn/Mc/So 三类。
# 为什么不能只靠 `str.isalnum()`：那会让 `h\u0345`（U+0345 组合形希腊下标的
# 字母面）在两侧分叉——Rust 收、Python 拒（本仓「双胞胎闸必须同判」是硬要求）。
# 陈化纪律：本表随 Unicode 版本走。Rust 工具链或 Python 的 unicodedata 升级后
# 须重导；守卫 `hive/test_id_contract_v2.py` 的 C 组用真 hive.exe **重跑同一导出
# 算法**并与本表逐位比对，表陈化即红（不是靠注释约定）。
OTHER_ALPHABETIC_BLOCKS = (
    (0x0345, 0x0345), (0x0363, 0x036F), (0x05B0, 0x05BD), (0x05BF, 0x05BF), (0x05C1, 0x05C2),
    (0x05C4, 0x05C5), (0x05C7, 0x05C7), (0x0610, 0x061A), (0x064B, 0x0657), (0x0659, 0x065F),
    (0x0670, 0x0670), (0x06D6, 0x06DC), (0x06E1, 0x06E4), (0x06E7, 0x06E8), (0x06ED, 0x06ED),
    (0x0711, 0x0711), (0x0730, 0x073F), (0x07A6, 0x07B0), (0x0816, 0x0817), (0x081B, 0x0823),
    (0x0825, 0x0827), (0x0829, 0x082C), (0x08D4, 0x08DF), (0x08E3, 0x08E9), (0x08F0, 0x0903),
    (0x093A, 0x093B), (0x093E, 0x094C), (0x094E, 0x094F), (0x0955, 0x0957), (0x0962, 0x0963),
    (0x0981, 0x0983), (0x09BE, 0x09C4), (0x09C7, 0x09C8), (0x09CB, 0x09CC), (0x09D7, 0x09D7),
    (0x09E2, 0x09E3), (0x0A01, 0x0A03), (0x0A3E, 0x0A42), (0x0A47, 0x0A48), (0x0A4B, 0x0A4C),
    (0x0A51, 0x0A51), (0x0A70, 0x0A71), (0x0A75, 0x0A75), (0x0A81, 0x0A83), (0x0ABE, 0x0AC5),
    (0x0AC7, 0x0AC9), (0x0ACB, 0x0ACC), (0x0AE2, 0x0AE3), (0x0AFA, 0x0AFC), (0x0B01, 0x0B03),
    (0x0B3E, 0x0B44), (0x0B47, 0x0B48), (0x0B4B, 0x0B4C), (0x0B56, 0x0B57), (0x0B62, 0x0B63),
    (0x0B82, 0x0B82), (0x0BBE, 0x0BC2), (0x0BC6, 0x0BC8), (0x0BCA, 0x0BCC), (0x0BD7, 0x0BD7),
    (0x0C00, 0x0C04), (0x0C3E, 0x0C44), (0x0C46, 0x0C48), (0x0C4A, 0x0C4C), (0x0C55, 0x0C56),
    (0x0C62, 0x0C63), (0x0C81, 0x0C83), (0x0CBE, 0x0CC4), (0x0CC6, 0x0CC8), (0x0CCA, 0x0CCC),
    (0x0CD5, 0x0CD6), (0x0CE2, 0x0CE3), (0x0CF3, 0x0CF3), (0x0D00, 0x0D03), (0x0D3E, 0x0D44),
    (0x0D46, 0x0D48), (0x0D4A, 0x0D4C), (0x0D57, 0x0D57), (0x0D62, 0x0D63), (0x0D81, 0x0D83),
    (0x0DCF, 0x0DD4), (0x0DD6, 0x0DD6), (0x0DD8, 0x0DDF), (0x0DF2, 0x0DF3), (0x0E31, 0x0E31),
    (0x0E34, 0x0E3A), (0x0E4D, 0x0E4D), (0x0EB1, 0x0EB1), (0x0EB4, 0x0EB9), (0x0EBB, 0x0EBC),
    (0x0ECD, 0x0ECD), (0x0F71, 0x0F83), (0x0F8D, 0x0F97), (0x0F99, 0x0FBC), (0x102B, 0x1036),
    (0x1038, 0x1038), (0x103B, 0x103E), (0x1056, 0x1059), (0x105E, 0x1060), (0x1062, 0x1064),
    (0x1067, 0x106D), (0x1071, 0x1074), (0x1082, 0x108D), (0x108F, 0x108F), (0x109A, 0x109D),
    (0x1712, 0x1713), (0x1732, 0x1733), (0x1752, 0x1753), (0x1772, 0x1773), (0x17B6, 0x17C8),
    (0x1885, 0x1886), (0x18A9, 0x18A9), (0x1920, 0x192B), (0x1930, 0x1938), (0x1A17, 0x1A1B),
    (0x1A55, 0x1A5E), (0x1A61, 0x1A74), (0x1ABF, 0x1AC0), (0x1ACC, 0x1ACE), (0x1B00, 0x1B04),
    (0x1B35, 0x1B43), (0x1B80, 0x1B82), (0x1BA1, 0x1BA9), (0x1BAC, 0x1BAD), (0x1BE7, 0x1BF1),
    (0x1C24, 0x1C36), (0x1DD3, 0x1DF4), (0x2DE0, 0x2DFF), (0xA674, 0xA67B), (0xA69E, 0xA69F),
    (0xA802, 0xA802), (0xA80B, 0xA80B), (0xA823, 0xA827), (0xA880, 0xA881), (0xA8B4, 0xA8C3),
    (0xA8C5, 0xA8C5), (0xA8FF, 0xA8FF), (0xA926, 0xA92A), (0xA947, 0xA952), (0xA980, 0xA983),
    (0xA9B4, 0xA9BF), (0xA9E5, 0xA9E5), (0xAA29, 0xAA36), (0xAA43, 0xAA43), (0xAA4C, 0xAA4D),
    (0xAA7B, 0xAA7D), (0xAAB0, 0xAAB0), (0xAAB2, 0xAAB4), (0xAAB7, 0xAAB8), (0xAABE, 0xAABE),
    (0xAAEB, 0xAAEF), (0xAAF5, 0xAAF5), (0xABE3, 0xABEA), (0x10376, 0x1037A),
    (0x10A01, 0x10A03), (0x10A05, 0x10A06), (0x10A0C, 0x10A0F), (0x10D24, 0x10D27),
    (0x10EAB, 0x10EAC), (0x11000, 0x11002), (0x11038, 0x11045), (0x11073, 0x11074),
    (0x11080, 0x11082), (0x110B0, 0x110B8), (0x110C2, 0x110C2), (0x11100, 0x11102),
    (0x11127, 0x11132), (0x11145, 0x11146), (0x11180, 0x11182), (0x111B3, 0x111BF),
    (0x111CE, 0x111CF), (0x1122C, 0x11234), (0x11237, 0x11237), (0x1123E, 0x1123E),
    (0x11241, 0x11241), (0x112DF, 0x112E8), (0x11300, 0x11303), (0x1133E, 0x11344),
    (0x11347, 0x11348), (0x1134B, 0x1134C), (0x11357, 0x11357), (0x11362, 0x11363),
    (0x11435, 0x11441), (0x11443, 0x11445), (0x114B0, 0x114C1), (0x115AF, 0x115B5),
    (0x115B8, 0x115BE), (0x115DC, 0x115DD), (0x11630, 0x1163E), (0x11640, 0x11640),
    (0x116AB, 0x116B5), (0x1171D, 0x1172A), (0x1182C, 0x11838), (0x11930, 0x11935),
    (0x11937, 0x11938), (0x1193B, 0x1193C), (0x11940, 0x11940), (0x11942, 0x11942),
    (0x119D1, 0x119D7), (0x119DA, 0x119DF), (0x119E4, 0x119E4), (0x11A01, 0x11A0A),
    (0x11A35, 0x11A39), (0x11A3B, 0x11A3E), (0x11A51, 0x11A5B), (0x11A8A, 0x11A97),
    (0x11C2F, 0x11C36), (0x11C38, 0x11C3E), (0x11C92, 0x11CA7), (0x11CA9, 0x11CB6),
    (0x11D31, 0x11D36), (0x11D3A, 0x11D3A), (0x11D3C, 0x11D3D), (0x11D3F, 0x11D41),
    (0x11D43, 0x11D43), (0x11D47, 0x11D47), (0x11D8A, 0x11D8E), (0x11D90, 0x11D91),
    (0x11D93, 0x11D96), (0x11EF3, 0x11EF6), (0x11F00, 0x11F01), (0x11F03, 0x11F03),
    (0x11F34, 0x11F3A), (0x11F3E, 0x11F40), (0x16F4F, 0x16F4F), (0x16F51, 0x16F87),
    (0x16F8F, 0x16F92), (0x16FF0, 0x16FF1), (0x1BC9E, 0x1BC9E), (0x1E000, 0x1E006),
    (0x1E008, 0x1E018), (0x1E01B, 0x1E021), (0x1E023, 0x1E024), (0x1E026, 0x1E02A),
    (0x1E08F, 0x1E08F), (0x1E947, 0x1E947), (0x1F130, 0x1F149), (0x1F150, 0x1F169),
    (0x1F170, 0x1F189),
)

# NFC/NFD/NFKC 会改写的有限区块闭集（左闭右闭）——**逐区间对齐**
# `hive/src/job.rs::NFC_REWRITE_BLOCKS`（删表任一行 / 改窄任一区间 ⇒ 对应形态
# 在两侧重新变「合法」，拒绝面同时失守；守卫 B 组按内容逐区间比对两张表）。
# 分区依据见 Rust 侧头注（①真 canonical 改写区块 ②契约点名的兼容/表现形区块）。
NFC_REWRITE_BLOCKS = (
    (0x00AA, 0x00AA),           # 序数指示符 ª（兼容分解 a a）
    (0x00B2, 0x00B9),           # 上标 ¹²³ 邻域（含 U+00B5 µ 单例分解为 μ）
    (0x00BA, 0x00BA),           # 序数指示符 º（兼容分解 o）
    (0x0132, 0x0133),           # 连字 IJ/ij
    (0x01C4, 0x01CC),           # DŽ 系列连字
    (0x01F1, 0x01F3),           # DŽ 连字
    (0x1100, 0x11FF),           # Hangul Jamo（NFD 分解为 L/V/T；组合即改写）
    (0x2070, 0x209F),           # 上标/下标（兼容分解为数字/字母）
    (0x2100, 0x214F),           # Letterlike（含 U+2126 Ω / U+212A K / U+212B Å 单例分解）
    (0x2150, 0x218F),           # 数字形式 Ⅰ ⅱ ½（兼容分解为 ASCII）
    (0x2460, 0x24FF),           # 带圈字母数字 ① Ⓐ
    (0x3130, 0x318F),           # Hangul 兼容 Jamo
    (0x3200, 0x33FF),           # 带圈/括号 CJK 与单位 ㈱ ㌀
    (0xF900, 0xFAFF),           # CJK 兼容表意（U+FA10 等）
    (0xFB00, 0xFB4F),           # 字母表现形（连字 ﬁﬂ 与希伯来表现形）
    (0xFE30, 0xFE4F),           # CJK 兼容形式
    (0xFE50, 0xFE6F),           # 小写变体形式
    (0xFF00, 0xFFEF),           # 半角/全角
    (0x1D400, 0x1D7FF),         # 数学字母数字 𝐀 𝟙
    (0x2F800, 0x2FA1F),         # CJK 兼容表意补充
)

# Windows 保留设备名（B4 拒收项；与 `job.rs::RESERVED_DEVICE_NAMES` 逐项同集）。
# Win32 对**单个路径分量**做设备名解析且**忽略扩展名**（`CON.txt` 与 `CON` 同指
# 设备），故比对的是「首个 `.` 之前」部分；比对**ASCII 大小写不敏感**
# （不用 str.upper()：它的 Unicode 折叠面比 Rust 的 eq_ignore_ascii_case 宽，
# 会让两侧分叉）。
RESERVED_DEVICE_NAMES = (
    "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6",
    "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6",
    "LPT7", "LPT8", "LPT9",
)
_ASCII_UPPER = str.maketrans("abcdefghijklmnopqrstuvwxyz",
                             "ABCDEFGHIJKLMNOPQRSTUVWXYZ")


# 生效条件：c 为单字符且码点落在 NFC_REWRITE_BLOCKS 任一区块内 → True
# （= 「归一化会改写它」，不可信任的 NFC 形）——与 rust `job::nfc_rewritable` 同判。
def _nfc_rewritable(c: str) -> bool:
    u = ord(c)
    return any(lo <= u <= hi for lo, hi in NFC_REWRITE_BLOCKS)


# 生效条件：c 为 Unicode `Other_Alphabetic` 补集成员 → True。**只为补齐
# `str.isalnum()` 与 Rust `char::is_alphabetic()` 的实测差**（见上表头注）。
def _is_other_alphabetic(c: str) -> bool:
    u = ord(c)
    return any(lo <= u <= hi for lo, hi in OTHER_ALPHABETIC_BLOCKS)


# 生效条件：c 为 Rust `char::is_alphanumeric()` 会判真的字符 → True
# （= Python `isalnum()` ∪ 实测补齐闭集）。不适用条件：不做真正的 Unicode 属性
# 计算（零依赖约束下不可行）——本判据是**逐例实测对齐后的等价实现**。
def _rust_alphanumeric(c: str) -> bool:
    return c.isalnum() or _is_other_alphabetic(c)


# 生效条件：c 为「已归一化、可安全进 id」的字符 → True（= B5 单点判据，与 rust
# `job::nfc_stable_alnum` 同判：字母数字 **且** 不落在会改写的区块内）。
# 不适用条件：不做归一化（**明确不做静默归一化**，B5 的实现级收窄：拒收比静默
# 归一化更严且两侧可证同判）；也不做真正的 NFC 计算——本判据按与 Rust 同口径的
# 有限区块闭集做保守判定。
def _nfc_stable_alnum(c: str) -> bool:
    return _rust_alphanumeric(c) and not _nfc_rewritable(c)


# 生效条件：c 为零宽/不可见注入载体（U+200B..U+200F、U+2060、U+FEFF）→ True。
def _is_zero_width(c: str) -> bool:
    return "\u200b" <= c <= "\u200f" or c in ("\u2060", "\ufeff")


# 生效条件：c 为双向控制字符（U+202A..U+202E、U+2066..U+2069）→ True。
def _is_bidi_control(c: str) -> bool:
    return "\u202a" <= c <= "\u202e" or "\u2066" <= c <= "\u2069"


# 生效条件：s 的「首个 `.` 之前」部分与任一保留设备名 **ASCII 大小写不敏感**
# 相等 → True（含 `CON.txt` 这类带扩展名形态）——与 rust `job::is_reserved_device_name` 同判。
def _is_reserved_device_name(s: str) -> bool:
    base = s.split(".")[0].translate(_ASCII_UPPER)
    return base in RESERVED_DEVICE_NAMES


# 生效条件：jid 通过 id 契约 v2 全部判据 → None；否则返回**可直接展示的拒收原因**
# （含路径成分/不可见注入/NFC 形态建议等，错误显式、不静默降级）。
# 与 __valid_job_id 是同一判据的两个出口（后者 = 前者 is None），顺序逐条对齐
# rust `job::valid_job_id`（顺序会改变报错文本，但**不改判定**——所有分支都是
# 「拒」，故两侧同判性不受顺序影响；顺序对齐只为可读原因与 Rust 一致）。
def _job_id_reject_reason(jid) -> str | None:
    if not isinstance(jid, str) or jid == "":
        return "job_id 须为非空字符串"
    if not jid.startswith("h"):
        return "job_id 须以 `h` 开头（h 前缀保留，契约 §四.7）"
    if jid.strip() != jid:
        return "job_id 含首尾空白（Win32 会静默剥掉 ⇒ 与其他 id 落到同一目录）"
    if jid.endswith("."):
        return "job_id 以 `.` 结尾（Win32 会静默剥尾点 ⇒ 与去掉尾点的 id 同指）"
    if jid in (".", ".."):
        return "job_id 是相对路径段"
    for c in jid:
        if unicodedata.category(c) == "Cc" or c in "/\\:":
            return (f"job_id 含路径成分/控制字符 {c!r}"
                    f"（`/` `\\` `:` 是 2026-09-25 池外读写缺陷的载体）")
        if _is_zero_width(c) or _is_bidi_control(c):
            return (f"job_id 含零宽/双向控制字符 U+{ord(c):04X}"
                    "（不可见注入载体：同形异义、显示与字节不一致）")
        if c == "_" or c == ".":
            continue
        if not _nfc_stable_alnum(c):
            return (f"job_id 含非法字符 U+{ord(c):04X}"
                    f"（{unicodedata.name(c, '?')}）：只收 Unicode 字母/数字与 `_`"
                    "（`.` 非尾点、非单独才收）；且须已是 **NFC 稳定**形态——"
                    "会归一化改写的形态（CJK 兼容表意 / 全角 / 带圈字母数字 / 数学字母 / "
                    "组合标记 / Hangul Jamo 等）一律拒收，**不做静默归一化**："
                    "请改用其 NFC 等价形态（如把 ﬁ 写成 fi、把组合序列写成预合成字符）后重提")
    if _is_reserved_device_name(jid):
        return ("job_id 命中 Windows 保留设备名"
                "（CON/PRN/AUX/NUL/COM1..9/LPT1..9，含 CON.txt 这类带扩展名形态）")
    if any(_is_reserved_device_name(seg) for seg in jid.split("_")):
        return ("job_id 的某一段命中 Windows 保留设备名"
                "（Win32 的设备名解析是**按分量**做的：`h_CON_x` 里的 CON 段同样危险）")
    return None


# 生效条件：jid 通过 id 契约 v2 全部判据 → True，否则 False——与 rust 侧
# `job::valid_job_id` 同口径（判据单点在 Rust，本面是**孪生**；同判性由
# `hive/id_contract_corpus_v2.txt` 的对照语料逐例钉死，勿自持第二判据）。
def _valid_job_id(jid) -> bool:
    """job_id 结构校验（防路径穿越 + id 契约 v2 字符集闸，2026-09-25 缺陷）。

    MCP 面 job_id 由客户端可控：`poll ../victim` 曾可读池外任意目录全文、
    `kill ..` 曾可在池外写 kill 标志（os.path.join 裸拼 + isdir 恒真）。
    一切把外部 job_id 拼进路径的入口（_t_poll/_t_kill/_dep_gate）先过此闸。
    契约 v2 放宽为「Unicode 字母/数字 + `_`」并新增拒收（路径成分/首尾空白/尾点/
    控制字符/零宽/双向控制/Windows 保留设备名/非 NFC 稳定形态），使中文四槽 id
    与存量旧形态 `h<13位毫秒>_<4位hex>` **同时**合法（存量零迁移）。
    """
    return _job_id_reject_reason(jid) is None


# 生效条件：deps 为 None（调用方未传该参数）→ 返回 None（「缺省不写」，不校验不计入）；
# deps 非 list → 返回类型原因串；list 内任一项未过 _valid_job_id 结构闸 → 返回格式原因串；
# 任一项在 jobs 下非目录 → 返回存在性原因串；全部通过 → None。调用方拿到非 None 即
# fail-closed（拒提交、不写 spec、不拉 serve），绝不静默忽略或降级为「无依赖」。
# 不适用条件：不做 DAG 环检测——无环性由**存在性闸**结构性保证：提交时只能引用
# **已存在**的任务目录（本函数的存在性闸 + CLI 侧 `hive/src/main.rs` 的
# depends_on 存在性检查 + 运行期 `hive/src/scheduler.rs::deps_gate`），引用不到
# 提交时尚不存在的任务，自引用亦不可能。**不是**由 id 的时间序保证：旧形态 id
# 恰好也带时间戳（名序=时间序只是巧合的代理），契约 v2 的语义四槽 id **不再有此
# 性质**，故论证不得依赖它（见 hive/src/spec.rs 的 Spec.depends_on 头注）。
def _dep_gate(jobs: str, deps) -> str | None:
    """依赖门禁（H-6）：与 CLI 同判据的两道闸——**格式**（job_id 结构）与
    **存在性**（`jobs/<dep>` 是目录）。

    为什么判据必须是这一份（不得分叉第二套）：CLI 侧同两闸的落点 =
    `hive/src/spec.rs:203`（格式，走 `job::valid_job_id`）+ `hive/src/main.rs:289`
    （存在性，`jobs.join(dep).is_dir()`）；调度侧 `hive/src/scheduler.rs::deps_gate`
    读的就是 spec.json 的 `depends_on`。MCP 面此前既不收也不写该键（H-6 缺陷：
    只有 CLI `hive submit` 能用依赖门禁），程序化接入（含 orch 派生）无从使用。
    格式判据复用 `_valid_job_id`（与 rust `job::valid_job_id` 同口径的唯一实现），
    存在性判据与 CLI 同为「是目录」（同名**文件**不算）；文案亦与两侧逐字对齐
    （守卫 `hive/test_h6_mcp_depends_on.py` 的 D 组用同一批 id 两侧对照逐项钉住）。
    """
    if deps is None:
        return None
    if not isinstance(deps, list):
        # 比 CLI 更严的一处（有意、已声明）：CLI 侧 as_str_vec 对裸字符串按单元素
        # 列表宽松采信；本工具面 schema 声明的是 array，静默强转等于接受非法入参。
        return (f"depends_on 必须是字符串列表（job_id 数组），got "
                f"{type(deps).__name__}: {deps!r}——不静默强转/不降级为「无依赖」")
    for d in deps:
        if not _valid_job_id(d):
            return f"depends_on 项非法: {d}（须为 h 开头且不含路径成分的 job_id）"
        if not os.path.isdir(os.path.join(jobs, d)):
            return f"依赖不完整: {d}（任务不存在，先提交上游任务）"
    return None


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

# P11 结果完整性锚密钥链（批次53；N190 键集收窄）：与 hive/src/keyres.rs 同一链、
# 同一顺序——`HIVE_ORCH_TOKEN`（令牌明文直值）→ `HIVE_ORCH_TOKEN_FILE`（**路径**，
# 读全文 strip）→ None。只取 hive 身份/令牌面（对照 config.local 既有键），不新发明
# 密钥来源、不设公开缺省常量（N143 教训）。N190：`HIVE_API_KEY` 不再兜底——它是模型
# （网关）密钥、属普通配置（exec.py 调 LLM 必需，serve 派发时默认继承给执行器），
# 把它当锚密钥 = 每个部署到模型密钥的面都自动成为锚签发面，且「谁有权签锚」退化成
# 「谁能调模型」（服务端 hive/src/keyres.rs 头注同口径）。config.local.json 的解析值
# 按 serve_start 合并语义（{**os.environ, **config}）胜出进程 env，故先查 config 再查
# env（读序未动）。
_RESULT_KEY_KEYS = ("HIVE_ORCH_TOKEN", "HIVE_ORCH_TOKEN_FILE")
# env 直值环的键：**值本身即密钥**的键。`HIVE_ORCH_TOKEN_FILE` 的值是**路径**（同
# Rust keyres.rs:43-50），故不入本环——由下方文件环读全文 strip（N190 同源链同步：
# 旧实现把路径串本身当密钥直接返回，文件环成不可达死代码，与 serve 侧「读文件、
# 不可读/空白即 None」判据分叉）。
_ENV_DIRECT_KEYS = ("HIVE_ORCH_TOKEN",)

# 小写读取（2026-09-28 使用者裁定，与 rust keyres.rs 同口径）：`HIVE_ORCH_TOKEN` 系
# 值**读取即折小写**——写面（md_cg.tokens 签发）产小写、读面折小写 ⇒ 大小写不再是
# 第二语义。只折 ASCII `A-Z`；**不用 str.lower()**（它对 Unicode 段的结论与 Rust
# `to_ascii_lowercase()` 不同，会把跨语言同源链折出分叉）。
# 诚实边界：①锚密钥＝折小写后的值 ⇒ 锚面大小写不敏感；对含大写的存量令牌折小写会
# 改变锚密钥 ⇒ submit 面与 serve 面必须同一构建，否则判伪锚。②本归一**只作用于锚面**
# （值仅作 HMAC 密钥，无逐字节对照物）；身份面 `hive/orch.py::_read_token` **不折**——
# 那里的值要与令牌库比对，而 secret 是 base64url 必含大写（`md_cg/tokens.py::parse_token`），
# 折小写即毁令牌。
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                             "abcdefghijklmnopqrstuvwxyz")


def _ascii_lower(s: str) -> str:
    return s.translate(_ASCII_LOWER)


# 生效条件：无必需形参——先 _load_local_config() 取 config 解析值（load_config 已完成 {"file":…} 读文件），两键按序首个非空字符串胜出（折 ASCII 小写）；再查进程 env 直值环同序（值本身即密钥，同折）；再取 env HIVE_ORCH_TOKEN_FILE 读文件全文 strip 后折小写（不可读/空白视同该环缺失，不回落路径串本身）；全缺 → None（提交面退回旧格式，不写 result_nonce——零配置部署行为不变）。
def _result_anchor_key() -> str | None:
    """结果完整性锚密钥（P11 批次53；N190 收窄为身份两环）：hive 身份/令牌面唯一解析点。

    与 rust keyres::resolve_key_from_env 同链同序同归一（submit 与 serve 两侧同口径，
    勿再分叉第二套解析）；config 值胜出 env（serve_start 合并语义）。
    （N190：模型密钥不再兜底；2026-09-28：三环统一折 ASCII 小写——见 `_ascii_lower` 头注）

    诚实边界（如实点名，本批未动）：config 形态的 `HIVE_ORCH_TOKEN_FILE` 按**直值**
    采信（部署实况该键写路径串）——判据面只问「锚是否启用」（`_submit` 的
    `is not None` 判据），与 serve 侧读文件后的非空判定同结论；仅当该路径不可读时
    两面分叉。env 形态已按 Rust 语义读文件（守卫 C 组冻结两侧）。
    """

    def _env(k: str) -> str | None:
        v = (os.environ.get(k) or "").strip()
        return _ascii_lower(v) or None

    cfg, _err = _load_local_config()
    for k in _RESULT_KEY_KEYS:
        v = cfg.get(k)
        if isinstance(v, str) and v.strip():
            return _ascii_lower(v.strip())
    for k in _ENV_DIRECT_KEYS:
        v = _env(k)
        if v:
            return v
    f = _env("HIVE_ORCH_TOKEN_FILE")
    if f:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                s = _ascii_lower(fh.read().strip())
            if s:
                return s
        except OSError:
            pass
    return None


class SubmitError(Exception):
    """提交面分配失败（fail-closed：显式报错，绝不静默降级、绝不自造 id）。"""


# 生效条件：HIVE_EXE 可用（isfile）→ 以
# `hive alloc-id --identity X --task Y --unit Z --jobs <池>` 分配 job_id 并返回它
# （**任务目录已由分配器创建** = 分配已完成）；HIVE_EXE 不可用 / 进程失败 /
# 输出非 JSON / ok 非真 / 未给 job_id / 返回的 id 未过本面孪生闸 → 抛 SubmitError
# （含可直读原因，绝不静默降级、绝不自造 id）。
# 不适用条件：不写 spec.json/status.json（写序归 _submit）；本函数不产生任何
# 「毫秒 + uuid」形态的 id。
def _alloc_job_id(jobs: str, identity: str, task: str, unit: str) -> str:
    """调 `HIVE_EXE alloc-id` 分配 job_id（B3/B7/B8；契约 §五 裁决 3）。

    为什么必须调外部进程而不是在 python 里自造：分配器（独占创建即分配、编号
    定宽 4 位、五单元闭集、槽闸）的**唯一实现**是 Rust 侧 `job::alloc_job_id`；
    python 面自持第二份必然漂移（历史形态 `h{毫秒}_{uuid6}` 即此，H-1 的碰撞那半
    与 id 契约 v2 都不允许它再存在）。
    """
    exe = _exe_path()
    if not os.path.isfile(exe):
        raise SubmitError(
            f"HIVE_EXE 不可用：{exe} 不存在——id 分配器的唯一实现是 Rust 侧 "
            "`hive alloc-id`（契约 §五 裁决 3），本面**不自造 id**"
            "（旧 `h{毫秒}_{uuid6}` 形态已退场）。先 `cargo build --release`"
            "（hive/ 下），或用 HIVE_EXE 指向可用二进制。")
    try:
        r = subprocess.run(
            [exe, "alloc-id", "--identity", identity, "--task", task,
             "--unit", unit, "--jobs", jobs],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=REPO)
    except OSError as e:
        raise SubmitError(f"HIVE_EXE 调起失败：{exe}（{type(e).__name__}: {e}）")
    out = (r.stdout or "").strip()
    try:
        doc = json.loads(out)
    except ValueError:
        raise SubmitError(
            f"alloc-id 输出非 JSON（rc={r.returncode}）：{out[:400]!r}"
            f"；stderr={(r.stderr or '')[:200]!r}")
    if not isinstance(doc, dict) or doc.get("ok") is not True:
        raise SubmitError(f"分配 job_id 失败（rc={r.returncode}）："
                          f"{json.dumps(doc, ensure_ascii=False)[:400]}")
    jid = doc.get("job_id")
    if not isinstance(jid, str) or not jid:
        raise SubmitError(f"alloc-id 未返回 job_id：{out[:400]!r}")
    # 跨语言分叉自检：分配器返回的 id 必须过本面孪生闸（两闸同判是本面的硬前提，
    # 不过即显式报警——绝不把未过闸的 id 拿去拼路径）。
    if not _valid_job_id(jid):
        raise SubmitError(
            f"alloc-id 返回的 job_id 未过本面孪生闸（跨语言分叉信号）：{jid!r}"
            f"——{_job_id_reject_reason(jid)}")
    return jid


# 生效条件：三槽合法、单元 ∈ 五单元闭集、号位未满、HIVE_EXE 可用 →
# 分配 job_id（`_alloc_job_id`，**目录即由它创建**）→ 落 spec.json → 落
# status.json（state=pending），返回 job_id；分配失败（含 HIVE_EXE 不可用）→
# 抛 SubmitError（调用方转成显式 ok:False）。
# 写序与 rust `job::init_job_with_slots` 同款：spec.json 先行、status.json 后写
# = 「任务就绪」信号，serve 只领取见到 status.json 且 state=pending 的任务。
# P11（批次53）：_result_anchor_key() 解析到密钥时 status 追加
# result_nonce=uuid4 hex（任务自此声明锚预期，serve 侧 classify_result 采信 done
# 前校验 result_anchor），密钥缺失则不加该键（旧格式，行为零变更）。
# 不适用条件：**不再自造 id**（B7/B8：`f"h{毫秒}_{uuid6}"` 已退场，id 一律由
# Rust 侧分配器独占创建得出）；不做槽合法性校验（那是分配器的判据面，
# 本面不持第二套——B8 四槽必填由 _t_spawn/orch._spawn 在调用前显式拦）。
def _submit(jobs: str, spec: dict, identity: str, task: str, unit: str) -> str:
    job_id = _alloc_job_id(jobs, identity, task, unit)
    d = os.path.join(jobs, job_id)
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

# H-3（坏 status 观测面）：与 rust 侧 job.rs 的同名常量逐字一致——
#   CORRUPT_MARK = serve 连续 N 拍解析失败后落的**旁证**标记（绝不改写 status.json 本体）；
#   QUARANTINE_DIR = doctor --quarantine 移入的池内保留区（list_jobs 只收 h 前缀目录，
#   故移入者自动退出领取面/统计面）。两处不一致 = 两个口径（本仓明令避免）。
CORRUPT_MARK = "status.corrupt.json"
QUARANTINE_DIR = "_quarantine"


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


# 生效条件：jobs 与 job_id 给定；status.json 不存在 → ("absent", None)（提交竞态窗口的正常
# 时序），存在且解析成功 → ("ok", st)，存在但解析失败 → ("corrupt", 原因文本)（事故信号）。
# H-3：与 rust `job::read_status_classified` 三态同口径——**必须把「不在」与「坏」分开**，
# 旧版把两者都压成读不到（None），doctor 里就只剩一个 unknown，事故与正常时序不可分。
def _status_class(jobs: str, job_id: str):
    p = os.path.join(jobs, job_id, "status.json")
    if not os.path.isfile(p):
        return ("absent", None)
    st = _read_status(jobs, job_id)
    if st is None:
        return ("corrupt", f"{p}: status.json 不可解析")
    return ("ok", st)


# 生效条件：jobs 给定——返回隔离保留区（jobs/_quarantine）内的任务名（h 前缀目录，
# 名升序）；目录不存在/不可读 → 空列表。与 rust `job::quarantined_jobs` 同口径。
def _quarantined_jobs(jobs: str):
    root = os.path.join(jobs, QUARANTINE_DIR)
    try:
        names = os.listdir(root)
    except OSError:
        return []
    return sorted(n for n in names
                  if n.startswith("h") and os.path.isdir(os.path.join(root, n)))


# 「无时间」哨兵 = i64::MIN，与 rust `job::created_ts_of` 逐值同口径（跨语言靠本注释
# 与两侧单测/对照语料钉死，勿各自发明第二个默认值）。
_TS_MIN = -(2 ** 63)
_TS_MAX = 2 ** 63 - 1


# 生效条件：jobs 与 job_id 给定——返回该任务 status.json 的 created_ts 真值（Unix 毫秒）；
# 缺失 / 非数 / 负值 / 非有限 / status.json 缺失或不可解析 → _TS_MIN（与 rust
# `job::created_ts_of` 同判据：读失败不抛异常、按缺失处理且结果确定）。**只读**。
def _created_ts_of(jobs: str, job_id: str):
    """created_ts 真值读取单点（排序键；不做任何状态判读）。"""
    st = _read_status(jobs, job_id)
    ts = st.get("created_ts") if isinstance(st, dict) else None
    # bool 是 int 子类，但 rust 侧 Json::Bool 不是 Num → 同样按「非数」处理。
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return _TS_MIN
    if ts != ts or ts < 0 or ts in (float("inf"), float("-inf")):
        return _TS_MIN
    # rust `n as i64` 是饱和转型，此处同口径（超界不静默加宽）。
    return max(_TS_MIN, min(_TS_MAX, ts))


# 生效条件：jobs 给定——返回池内任务名（h 前缀目录）按 **created_ts 真值升序**，
# 次键 id 字典序（与 rust `job::list_jobs_by_created` 同一排序键：同哨兵值内按名序，
# 总序确定且与目录枚举次序无关）；目录不可读的异常语义与旧 sorted(listdir) 一致。
# 消费者：_t_poll 无参列表与 _t_doctor 汇总遍历（两处必须走本单点，勿各自 sorted）。
def _list_jobs_by_created(jobs: str):
    names = [n for n in os.listdir(jobs)
             if n.startswith("h") and os.path.isdir(os.path.join(jobs, n))]
    return sorted(names, key=lambda n: (_created_ts_of(jobs, n), n))


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
# depends_on（H-6）在列：它是**调度语义**键（deps_gate 读 spec.json），本面收下并过
# 格式+存在性两闸后原样写入 spec；闸不过即拒（见 _dep_gate / _t_spawn）。
# identity/task/unit（id 契约 v2 · B8）在列：它们是**必填**的四槽之三（第四槽「编号」
# 由 Rust 侧分配器给出），本面收下**不写进 spec**——它们只喂给 `HIVE_EXE alloc-id`
# 分配 id（分配器是单点，本面不持第二套）；不进白名单就会在「未知键显式拒绝」处
# 被误杀，故必须在此列出。
SPAWN_ALLOWED_KEYS = frozenset({
    "model", "user_prompt", "system_prompt", "context_files", "timeout_s",
    "reasoning_effort", "context_budget_tokens", "context_strict", "thinking",
    "tools", "max_tool_rounds", "mdcg_root", "web_search_backend",
    "max_tokens", "temperature", "depends_on",
    "identity", "task", "unit",
})


# 生效条件：a 给定；当 a 含 SPAWN_ALLOWED_KEYS 之外的键、a.get("model") 去空白后为空、
# a.get("user_prompt") 去空白后为空、**四槽之三（identity/task/unit）任一缺失或空白**、
# a.get("context_files") 中任一项（相对项按 os.getcwd() 拼接）未通过 isfile 时返回
# ok: False 与对应 error；**依赖门禁（H-6）**：a.get("depends_on") 非 None 时经
# _dep_gate(jobs, ...) 过两道闸（格式=job_id 结构，与 rust job::valid_job_id 同判据；
# 存在性=jobs/<dep> 是目录，与 CLI 同口径），任一不过返回 ok: False 与可读 error
# （**不写 spec、不拉 serve、不降级为「无依赖」**）；全过（或未传）则组装 spec
# （timeout_s/context_budget_tokens 以 int(x or 默认) 把 0/空值/缺键回落默认，workdir
# 固定为 os.getcwd()，depends_on 非 None 时原样写入列表）并**调 HIVE_EXE alloc-id
# 分配 id**（`_submit`：本面不自造 id），分配失败（含 HIVE_EXE 不可用）返回
# ok: False 与原因；成功返回 ok: True 含 job_id/jobs_dir/serve。
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
    # 四槽（B8）：身份/任务/单元**必填**（第四槽「编号」由分配器独占创建给出）。
    # 位置在 _jobs_dir()/_dep_gate/_ensure_serve **之前**：缺槽不是「可以再等等」
    # 的状态，fail fast 在触任何文件机械与 serve 之前——**不许静默推导**
    # （猜错且静默正是 H-1 那半边缺陷的形状）。
    slots = {k: str(a.get(k) or "").strip() for k in ("identity", "task", "unit")}
    missing = [k for k, v in slots.items() if not v]
    if missing:
        return {"ok": False, "error": (
            "缺四槽入参——四槽 = 身份/任务/单元/编号，其中 identity / task / unit "
            f"**必填**（编号由分配器独占创建给出，无需入参），不许静默推导。"
            f"缺：{'、'.join(missing)}。可照抄示例："
            "hive_spawn(model=\"deepseek-flash\", user_prompt=\"…\", "
            "identity=\"zcode端\", task=\"灵枢迭代\", unit=\"反思单元\")——"
            "单元槽取蜂巢五单元**闭集**（记录单元/反思单元/验证单元/输出单元/维生系统；"
            "英文键 record/reflect/verify/output/sustain 亦可）。")}
    jobs = _jobs_dir()
    for rel in a.get("context_files") or []:
        path = rel if os.path.isabs(rel) else os.path.join(os.getcwd(), rel)
        if not os.path.isfile(path):
            return {"ok": False, "error": f"context 文件不存在: {path}"}
    # 依赖门禁（H-6）：**写 spec 之前**过与 CLI 同判据的两道闸（格式 + 存在性，
    # 单点实现 = _dep_gate）。位置在 _ensure_serve 之前——坏 spec 不拉起 serve、
    # 不落盘，也绝不静默降级为「无依赖」（那会让下游任务在依赖未 done 时被领取）。
    dep_err = _dep_gate(jobs, a.get("depends_on"))
    if dep_err:
        return {"ok": False, "error": dep_err}
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
    if a.get("depends_on") is not None:
        # 依赖门禁已在前面过闸（此处只写）；原样写入、保序、不裁剪——
        # 显式 `[]` = 提交方声明「无依赖」，同样落键（不是静默省略）。
        spec["depends_on"] = list(a["depends_on"])
    spec["workdir"] = os.getcwd()
    try:
        # 分配 id 的唯一通道（B7/B8）：`HIVE_EXE alloc-id`（Rust 侧分配器），
        # 本面不再自造 id；HIVE_EXE 不可用/槽非法/号位用尽 → 显式 ok:False。
        job_id = _submit(jobs, spec, slots["identity"], slots["task"], slots["unit"])
    except SubmitError as e:
        return {"ok": False, "error": str(e)}
    return {
        "ok": True,
        "job_id": job_id,
        "jobs_dir": jobs,
        "serve": ensure,
        "slots": {"identity": slots["identity"], "task": slots["task"],
                  "unit": slots["unit"]},
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
                    "error": f"job_id 非法: {job_id}——{_job_id_reject_reason(job_id)}"}
        d = os.path.join(jobs, job_id)
        if not os.path.isdir(d):
            return {"ok": False, "error": f"任务不存在: {job_id}"}
        st = _read_status(jobs, job_id) or {"error": "status 不可读"}
        st["result"] = _result_view(d, head=None)  # 单查给全文
        return {"ok": True, "job": st}
    ids = _list_jobs_by_created(jobs)
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
                "error": f"job_id 非法: {job_id}——{_job_id_reject_reason(job_id)}"}
    d = os.path.join(jobs, job_id)
    if not os.path.isdir(d):
        return {"ok": False, "error": f"任务不存在: {job_id}"}
    flag = os.path.join(d, "kill")
    if not os.path.exists(flag):
        # 空标记文件：内容无实义（消费方 job.rs:344-346 只判存在），
        # 仍显式声明 encoding —— 判据「凡文本模式一律显式」（B 项，零例外）。
        open(flag, "w", encoding="utf-8").close()
    return {"ok": True, "job_id": job_id, "hint": "worker 检测到 kill 标志后强杀（≤1s）"}


# 生效条件：_a 给定且内容未被使用；遍历 jobs 下以 "h" 开头的目录按三态分类（_status_class，H-3）计数——
# ok 取 (status or {}).get("state") or "unknown"、absent 计 "no_status"（提交竞态窗口）、corrupt 计独立类别
# "corrupt" 并进 corrupt_jobs 明细（job_id/error/marker）；再读 _heartbeat(jobs) 与隔离保留区（quarantined）
# 后返回单个 ok: True 字典，其中 serve_alive=_serve_alive(jobs)、exe_found=os.path.isfile(_exe_path())、
# exec_source 依 hb.get("exec_py") 真值取 "serve_heartbeat" 否则 "no_heartbeat_or_legacy"。
def _t_doctor(_a: dict) -> dict:
    jobs = _jobs_dir()
    exe = _exe_path()
    cfg, cfg_err = _load_local_config()
    states = {}
    corrupt_jobs = []
    for jid in _list_jobs_by_created(jobs):
        kind, st = _status_class(jobs, jid)
        if kind == "ok":
            s = (st or {}).get("state") or "unknown"
        elif kind == "corrupt":
            # H-3：坏 status 单列独立类别 + 明细（不再被压进 unknown 里静默）
            s = "corrupt"
            corrupt_jobs.append({
                "job_id": jid,
                "error": st,
                "marker": os.path.isfile(os.path.join(jobs, jid, CORRUPT_MARK)),
            })
        else:
            s = "no_status"
        states[s] = states.get(s, 0) + 1
    hb = _heartbeat(jobs)
    return {
        "ok": True,
        "serve_alive": _serve_alive(jobs),
        "exe_found": os.path.isfile(exe),
        "exe_path": exe,
        "jobs_dir": jobs,
        "task_states": states,
        # H-3 观测面（与 CLI `hive doctor` 同口径）：坏 status 明细 + 已隔离件清单
        "corrupt_jobs": corrupt_jobs,
        "quarantine_dir": os.path.join(jobs, QUARANTINE_DIR),
        "quarantined": _quarantined_jobs(jobs),
        "corrupt_note": ("corrupt=status.json 存在但不可解析（事故信号，不自动终态化——"
                         "那会把坏文件静默吞掉）；处置=`hive doctor --quarantine` 移出池"
                         "（可 `--unquarantine` 退回），坏字节原样保留供诊断。"
                         "no_status=任务目录在但 status.json 尚未出现（提交竞态窗口，正常时序）。"),
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
        "description": "灵枢蜂巢：提交 LLM 任务到并发队列（毫秒级返回 job_id，后台执行不阻塞）。四槽必填：identity / task / unit（id = h_<身份>_<任务>_<单元>_<编号>，编号由 Rust 侧分配器独占创建给出；单元槽取蜂巢五单元闭集）。统一子代理默认：reasoning_effort=high / context_budget_tokens=200000 / timeout_s=600。**只接受下方 properties 列出的 19 个参数**：白名单外的键（如 command / commands / orchestrate / workdir）会被显式拒绝——确定性执行（跑命令/测试/回归）与编排请改走 CLI（hive submit + hive/exec_cmd.py / orch.py）。",
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
                "depends_on": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": ("上游任务 job_id 列表（可选）：全 done 才被领取，"
                                    "任一上游 error/timeout/killed/needs_review → 本任务"
                                    "直接 error（失败传播）。每个 id 须为 h 开头且不含"
                                    "路径成分，且 jobs/<id> 目录必须已存在——不过闸即"
                                    "拒绝提交（不静默忽略、不降级为「无依赖」）。"),
                },
                "identity": {
                    "type": "string",
                    "description": ("身份槽（**必填**，id 契约 v2 四槽之一）：提交者/端别，"
                                    "如 zcode端。落进 job_id = h_<身份>_<任务>_<单元>_<编号>；"
                                    "只收 Unicode 字母/数字（不含 `_` `.` 与路径成分），"
                                    "且须已是 NFC 稳定形态（**不做静默归一化**，"
                                    "非 NFC 形态直接拒收）。不许省略、不许推导。"),
                },
                "task": {
                    "type": "string",
                    "description": ("任务槽（**必填**，四槽之一）：工作流/迭代名，如 灵枢迭代。"
                                    "字符口径同 identity；目录可作它的父段（成 5 段）。"),
                },
                "unit": {
                    "type": "string",
                    "description": ("单元槽（**必填**，四槽之一）：蜂巢五单元**闭集**——"
                                    "记录单元 / 反思单元 / 验证单元 / 输出单元 / 维生系统"
                                    "（英文键 record / reflect / verify / output / sustain "
                                    "二选一，落 id 一律中文名）。副代理不是第六单元。"),
                },
            },
            "required": ["model", "user_prompt", "identity", "task", "unit"],
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