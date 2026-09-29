#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orch.py — 蜂巢编排器 worker：把「一个任务」拆给多个子代理并收口。

定位（与既有件的关系，避免重复建设）
----------------------------------------------------------------------------
  · exec.py        单代理执行器（LLM 委托 + 工具循环）。本文件**复用它**：同一个
                   agent loop、同一份 spec 契约、同一套 result 契约。本文件只做
                   两件事——① 注册编排三工具；② 把 lingshu_cg 的身份从默认
                   recorder 子代理换成**派生令牌编排器**。
  · exec_cmd.py    多态转发层：`spec.orchestrate` 真值 → 本文件（否则 exec.py）。
  · md_cg/units.py 「派发 + 等待」接线层（ccgc 复核通道）。本文件**不**复用它——
                   units 的 role 面是 reflect/verify 专用，编排面是任意子任务。
  · test/orchestrator_memory.py（OrcMemory）= **记忆层**并发访问（卡片提交/收口/
                   裁决）。本文件是**任务层**编排，二者正交：OrcMemory 管「记忆
                   节点怎么并发写不打架」，orch.py 管「任务怎么拆给子代理」。
                   唯一重合概念是**卡片**——本文件回流给编排者模型的也是卡片
                   （正文头 + 指针 + 按需拉取），与 OrcMemory 的 CARD_TEMPLATE
                   同源于同一条纪律：主代理只看卡片，细节按需拉取。

三处设计落点（2026-09-16 使用者裁定，均取推荐项）
----------------------------------------------------------------------------
  Q1 挂载：新 worker（exec_cmd.py 转发链加一档），语义独立，不污染 exec.py 的
           累积式修复面。
  Q2 回流：卡片 + 指针 + 按需拉取——默认只给 `content_head` 200 字 +
           `tool_trace` 摘要 + `result_path`；需要细节时显式 read_full(job_id)。
  Q3 权限：收窄派生令牌（真源 = md_cg/tokens.py 的 ORCH_* 常量）。能裁决子代理
           冲突（review），不能动地基（anchor/self）、不能删除（forget）、
           不能自验派生（derive 结构上 delegable=False）。

fail-closed（本文件的硬纪律，不降级）
----------------------------------------------------------------------------
  · 令牌缺失 / 不可用 → 立即写 result 并退出，**绝不**降级为 recorder 身份继续
    跑：静默降级 = 权限意图落空且不可见（第 4 条明令禁止的静默错执行）。
  · 子任务 tools 只允许 lingshu_cg / web_search / read_file（编排工具不传给子代理）。
  · 子任务 spec **不可能**带 orchestrate（走白名单构造 + 本文件不构造该键）
    → 结构上防无限递归。
  · read_full 只允许读**本编排者派发的**子任务（越权读被拒）。
  · 单 job 子任务数上限 max_subtasks（默认 8），超限诚实报错而非静默截断。

启动（由 serve 以 `python <exec_py> <job_dir>` 拉起，无需手工调用）：
    HIVE_EXEC_PY=<仓>/hive/exec_cmd.py     # 转发层接管多态
    HIVE_ORCH_TOKEN=<python -m md_cg.tokens orch 签发的令牌明文>
    HIVE_ORCH_TOKEN_FILE=<令牌文件>        # 与上行二选一
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time

# ---------------------------------------------------------------- 入口自保证 UTF-8
# 约束（工作纪律第 15 条）：本调用必须在**任何文件/库 I/O 之前**——utf8_boot.ensure_utf8
# 在解释器未开 UTF-8 模式时以相同 argv 重启自身（-X utf8），早于它的任何 open/stdio
# 读写都走 locale 编码（Windows 中文机 = cp936：裸 open 抛 UnicodeDecodeError、中文写
# 落 GBK 字节）。本文件下方 `import exec` 会拉起执行器（读 spec 前必须先有保证），故本行
# 必须早于它。仓库根入 sys.path 的形态照 hive/exec.py::_md_cg_import 的最小写法
# （助手在仓根，不是 md_cg 包目录）。
# 被 import（本模块非 __main__）时助手只置子进程继承面、绝不重启/退出——F6：静默重启
# 会吞掉调用方输入。
_UTF8_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _UTF8_ROOT not in sys.path:
    sys.path.insert(0, _UTF8_ROOT)
from utf8_boot import ensure_utf8  # noqa: E402

ensure_utf8(__file__)


HIVE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIVE_DIR)
if HIVE_DIR not in sys.path:
    sys.path.insert(0, HIVE_DIR)

import exec as _ex                                  # noqa: E402  同目录：agent loop + 契约
from hive_mcp import mcp_server as _hm              # noqa: E402  同仓：job 提交（单一真源）

EXIT_OK, EXIT_SPEC = _ex.EXIT_OK, _ex.EXIT_SPEC

CARD_CHARS = 200                # Q2：默认回流给编排者模型的正文头长度
TRACE_MAX = 6                   # Q2：tool_trace 摘要保留条数（尾部优先）
FULL_MAX_CHARS = 20000          # read_full 单次默认上限（超出给头 + 指针）
DEFAULT_MAX_SUBTASKS = 8        # 单 job 子任务上限（spec.orchestrate.max_subtasks 可调）
CHILDREN_FILE = "_children.json"
TERMINAL_STATES = ("done", "error", "timeout", "killed")
SUB_TOOLS_ALLOW = ("lingshu_cg", "web_search", "read_file")   # 子代理可用工具（编排工具不外传；read_file 只读）
ORCH_TOOLS = ("spawn_subtask", "poll_subtasks", "read_full", "record_adjudication")
_ADJ_FILE = "_adjudication.jsonl"     # M5 纠正链侧车（job 目录内，随 job 留痕）
_ADJ_KINDS = ("supersede", "reject", "confirm")


# 生效条件：给定 model 与 context_files 列表，返回同源组键 = model + 排序后归一文件清单的 SHA1 前 8 位；同 context_files+同 model 的子任务同组（M5 同源标记，供纠正链裁决识别孪生来源）。
def _source_group(model: str, context_files) -> str:
    norm = "\x00".join(sorted(str(p) for p in (context_files or [])))
    h = hashlib.sha1(f"{model}\x00{norm}".encode("utf-8")).hexdigest()[:8]
    return f"sg_{h}"

ORCH_SYSTEM_PROMPT = """你是蜂巢**编排者**（orchestrator），不是执行者。职责：
1. 拆解：把任务切成可独立完成的子任务 → `spawn_subtask`（毫秒即返，**不要等**，继续拆下一个）
2. 观察：`poll_subtasks` 轮询进度。子任务卡片默认只给正文头 200 字 + 工具轨迹摘要；
   需要核对细节时用 `read_full(job_id)` 按需拉取，不要凭标题猜测结论
3. 收口：全部终态后汇总——核对证据、给出一份自足结论；冲突以证据比对后
   如实留痕（`lingshu_cg`(op=write, layer=contextual) 描述分歧点），**裁决归
   设计者**（编排器令牌无 review 裁决权，can_admin=False 是安全收紧的设计行为）；
   可归档时用 `lingshu_cg`(op=write, layer=knowledge)

纪律：
- 能并行的就一次派多个，不要串行等待
- 子任务 prompt 必须**自足**（子代理看不到你的上下文，也不能再派发子任务）
- 不要替子任务干活；你自己只在需要查/写记忆或裁决时调用 lingshu_cg，
  需要核对本地文件时用 read_file（只读）
- **写后回读（必做）**：lingshu_cg(op=write) 返回后，必须以 op=read 按返回的
  节点 id 回读，核对正文已真实落盘（**不信返回的 written 计数**——多实例下
  计数可能与盘面不一致）；不一致重试 1 次，再失败如实报 error，不静默
- 冲突以**证据**裁决，不以多数票；证据不足就如实说「未定」，不要编造
- 子任务结果间有纠正/否决/确认关系时，用 `record_adjudication` 留痕
  （台账随本任务目录归档，跨任务可回溯）；同 source_group 的孪生结果
  收口时要点名比对，不以「结果一致」代替核对
- 子任务失败要如实汇报失败原因，不要用其它子任务的结果顶替"""


class OrcError(Exception):
    """编排器前置条件不满足（fail-closed，由 main 收口为 EXIT_SPEC）。"""


# --------------------------------------------------------------- 工具 schema

# 生效条件：调用即返回 spawn_subtask 工具的 OpenAI function schema（声明
# job/depends_on/model 等参数面——编排器派生子任务的白名单入口）。
def _spawn_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "spawn_subtask",
            "description": (
                "派发一个子代理任务（毫秒即返，不阻塞）。子任务在蜂巢 worker 池并发执行；"
                "用 poll_subtasks 看进度、read_full 读细节。子代理可带 lingshu_cg（记忆）、"
                "web_search（联网）与 read_file（读本地文件/目录，只读）工具，"
                "但不能再派发子任务。"),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_prompt": {"type": "string", "description":
                                    "子任务指令，必须自足（子代理看不到编排者的上下文）"},
                    "model": {"type": "string", "description":
                              "缺省继承编排者的 model；须与 HIVE_API_BASE 配对"},
                    "system_prompt": {"type": "string", "description": "缺省用执行器默认"},
                    "context_files": {"type": "array", "items": {"type": "string"},
                                      "description": "要注入子代理的文件路径（相对/绝对）"},
                    "tools": {"type": "array", "items": {"type": "string"},
                              "description": "只能是 lingshu_cg / web_search / read_file 的子集；"
                                             "缺省=三者都给（编排工具不外传）"},
                    "timeout_s": {"type": "integer", "description": "缺省 600"},
                    "context_budget_tokens": {"type": "integer", "description": "缺省 200000"},
                    "reasoning_effort": {"type": "string", "description": "缺省 high"},
                    "depends_on": {
                        "type": "array", "items": {"type": "string"},
                        "description": (
                            "上游子任务 job_id 列表（可选；H-6 依赖门禁）：全部 done "
                            "才被领取，任一上游 error/timeout/killed/needs_review → "
                            "本子任务直接 error（失败传播）。id 形如 poll_subtasks "
                            "返回的 job_id（h 开头），且该任务必须已提交存在——"
                            "不过闸即拒（不静默忽略、不降级为「无依赖」）。"
                            "缺省 = 无依赖（立即并发跑）。")},
                    "identity": {
                        "type": "string",
                        "description": ("id 契约 v2 身份槽（可选，缺省继承编排者自身 "
                                        "spec 的同名槽）：落进子任务 id = "
                                        "h_<身份>_<任务>_<单元>_<编号>；只收 Unicode "
                                        "字母/数字且须已是 NFC 稳定形态。")},
                    "task": {
                        "type": "string",
                        "description": ("id 契约 v2 任务槽（可选，缺省继承编排者自身 "
                                        "spec 的同名槽）：工作流/迭代名。")},
                    "unit": {
                        "type": "string",
                        "description": ("id 契约 v2 单元槽（可选，缺省继承编排者自身 "
                                        "spec 的同名槽）：蜂巢五单元**闭集**——记录单元 / "
                                        "反思单元 / 验证单元 / 输出单元 / 维生系统"
                                        "（英文键 record/reflect/verify/output/sustain "
                                        "亦可）。子任务按职能归单元时显式指定。")},
                },
                "required": ["user_prompt"],
            },
        },
    }


# 生效条件：调用即返回 poll_subtasks 工具的 OpenAI function schema（声明
# 子任务 id 列表参数——编排者拉取子任务进度的观测面）。
def _poll_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "poll_subtasks",
            "description": (
                "查看子任务状态与卡片：默认只给 content_head 200 字 + tool_trace 摘要 + "
                "result_path（细节用 read_full）。不传 job_ids = 本编排者派发的全部子任务；"
                "显式传 id 只允许本编排者派发的子任务（未知/越权 id 整体拒绝）。"),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_ids": {"type": "array", "items": {"type": "string"},
                                "description": "指定子任务；缺省=全部"},
                    "full": {"type": "boolean", "description":
                             "true=卡片不截断（慎用，会占上下文）"},
                },
            },
        },
    }


# 生效条件：调用即返回 read_full 工具的 OpenAI function schema（声明节点 id
# 参数——子代理按需读 L2 细节层的最小充分出口）。
def _read_full_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "read_full",
            "description": (
                "按需拉取某个**本编排者派发的**子任务的 result.json 全文（默认上限 "
                "20000 字符；超出给头部 + result_path）。"),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                    "max_chars": {"type": "integer"},
                },
                "required": ["job_id"],
            },
        },
    }


# 生效条件：调用即返回 record_adjudication 工具的 OpenAI function schema——
# 强制字段（kind/supersede/evidence 等）fail-closed 校验的声明面（M5 纠正链）。
def _adjudication_schema() -> dict:
    """M5 纠正链侧车：裁决留痕工具（强制字段 fail-closed）。"""
    return {
        "type": "function",
        "function": {
            "name": "record_adjudication",
            "description": (
                "纠正链裁决留痕（M5）：对子任务结果间的纠正/否决/确认关系"
                "落一份裁决台账（_adjudication.jsonl），供跨 job 配对回溯。"
                "全部字段强制，缺一即拒（fail-closed）。裁决权边界："
                "kind=confirm 仅确认无冲突；supersede/reject 需 evidence "
                "给出被纠正方的 job_id 与依据。"),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string",
                             "enum": list(_ADJ_KINDS),
                             "description": "supersede=以新代旧 / reject=否决 / "
                                            "confirm=确认无冲突"},
                    "subject": {"type": "string",
                                "description": "被裁决的子任务 job_id"},
                    "evidence": {"type": "array", "items": {"type": "string"},
                                 "description": "裁决依据的 job_id 列表"
                                                "（含 subject 自身之外的证据源）"},
                    "verdict_note": {"type": "string",
                                     "description": "一句话裁决理由（不得为空）"},
                },
                "required": ["kind", "subject", "evidence", "verdict_note"],
            },
        },
    }


ORCH_SCHEMAS = {
    "spawn_subtask": _spawn_schema(),
    "poll_subtasks": _poll_schema(),
    "read_full": _read_full_schema(),
    "record_adjudication": _adjudication_schema(),
}


# ------------------------------------------------------------ 运行时配置容器

_CFG = {
    "job_id": "",
    "job_dir": "",
    "jobs": "",
    "model": "",
    "max_subtasks": DEFAULT_MAX_SUBTASKS,
    "children": [],
    # id 契约 v2（B8）：编排者自身的四槽之三（身份/任务/单元）——由 main() 从
    # 本编排者 spec 的同名键读入，供 `_spawn` **透传**给子任务（唯一实现是
    # Rust 侧分配器：子任务 id = `h_<身份>_<任务>_<单元>_<编号>`）。
    # 空 = spec 未带槽：`_spawn` **显式报错**，绝不兜底造 id（B8）。
    "slots": {},
}

# id 契约 v2（B8）：`spawn_subtask` 的四槽之三——编排者可在单次派发里显式指定
# （如把某个子任务定向到「验证单元」），缺省继承编排者自身 spec 的同名槽。
SLOT_KEYS = ("identity", "task", "unit")


# 生效条件：无入参，模块级常量 CHILDREN_FILE 与 _CFG['job_dir'] 可用时返回 os.path.join(_CFG['job_dir'], CHILDREN_FILE)。
def _children_path() -> str:
    return os.path.join(_CFG["job_dir"], CHILDREN_FILE)


# 生效条件：无入参，读取 _children_path()（由模块级 CHILDREN_FILE 拼接）成功且 JSON 的 data.get('children') 为真值时返回 list(data['children'])，否则（OSError/ValueError 或 children 为 None/空/假值）返回 []。
def _load_children() -> list:
    """读回子任务清单。

    持久化到编排者自己的 job 目录：编排者若因上下文预算交回续跑（换人接管），
    子任务清单不能丢——否则接管者会重复派发（资源浪费且结论可能被覆盖）。
    """
    try:
        with open(_children_path(), encoding="utf-8") as f:
            data = json.load(f)
        return list(data.get("children") or [])
    except (OSError, ValueError):
        return []


# 生效条件：path 与 payload 给定——tempfile.mkstemp(prefix=<basename>., suffix=".tmp", dir=path 同目录) 建唯一临时文件，UTF-8 json.dump(payload, ensure_ascii=False)+flush+fsync 后 os.replace 原子替换到 path；Windows replace 撞读者瞬态句柄（PermissionError）按 10ms×递增重试至多 50 次，replace 撞 FileNotFoundError（tmp 被瞬态消费/清理）时重建唯一名重写再试；任一重试耗尽才向外抛；finally best-effort 清理仍存在的 tmp（成功路径零残留）。与 exec.write_result 同一模板（v10 N82 先例，K1 并发压测守卫在位）。
def _atomic_write_json(path: str, payload) -> None:
    """tmp + fsync + rename 原子替换（N142/N88 批次 49）。

    N142：旧 _save_children 固定共享 tmp `_children.json.tmp`+裸写——双写者
    对撞（N92 孤儿+recover_orphans 重投并存的编排 job）撕裂 JSON 被 replace
    落盘，接管者 _load_children 读坏回 [] 全量重复派发。唯一临时名（同目录
    保证 rename 原子性，随机后缀防共享名对撞）+双异常重试自愈。
    N88：spec 补全写回裸 open("w") 先截断再写——写中途异常（磁盘满/杀毒锁/
    强杀落窗）毁掉任务契约，rust 重投读坏 spec 永久失败；原子替换保证
    任意时刻要么旧完整态、要么新完整态。
    """
    d = os.path.dirname(path) or "."
    base = os.path.basename(path)

    def _mk_and_dump():
        fd, tmp = tempfile.mkstemp(prefix=base + ".", suffix=".tmp", dir=d)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        return tmp

    tmp = _mk_and_dump()
    try:
        for attempt in range(50):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 49:
                    raise
                time.sleep(0.01 * (attempt + 1))
            except FileNotFoundError:
                if attempt == 49:
                    raise
                tmp = _mk_and_dump()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# 生效条件：无入参，当 _CFG['children'] 可被 json.dump 且目录可写时经 _atomic_write_json（mkstemp 唯一名+fsync+os.replace，N142 批次 49）原子落到 _children_path()；任一失败经 log 留痕（v8 N70 写侧残面收口——不再 except OSError: pass 静默吞：清单丢失会让接管者 _load_children 回 [] 全量重复派发，必须可查），函数总返回 None。
def _save_children() -> None:
    try:
        _atomic_write_json(_children_path(), {"children": _CFG["children"]})
    except OSError as e:
        _ex.log(_CFG.get("job_dir") or ".",
                f"子任务清单落盘失败（{type(e).__name__}: {e}）"
                "——接管续跑将重复派发，请检查磁盘/权限")


# ------------------------------------------------------------- 身份（Q3 落地）

# 生效条件：无入参，环境变量 HIVE_ORCH_TOKEN 去空白后非空则返回该值；否则读 HIVE_ORCH_TOKEN_FILE 去空白后非空才尝试打开并返回文件内容 strip 值，path 为空串则返回 ''，打开 OSError 抛 OrcError。
#
# 身份面**不折小写**（2026-09-28 使用者裁定「HIVE_ORCH_TOKEN 使用小写读取」的边界）：
# 同一环境变量的**锚面**读取点（`hive/src/keyres.rs::resolve_key_from_env`、
# `hive/hive_mcp/mcp_server.py::_result_anchor_key`）折 ASCII 小写——那里的值只作 HMAC
# 密钥，无逐字节对照物，折小写不误判；本函数的值**要与令牌库比对**（load_principal →
# verify_token → md_cg/tokens.parse_token），而 secret 是 `secrets.token_urlsafe` 产的
# base64url **必含大写**（parse_token 明写 secret 不受「只认小写」限制）——在此折小写
# 即把合法令牌改成查不到的形态（令牌全废）。故两面有意不同，勿「统一」。
# 守卫：hive/test_result_anchor_chain.py 的 [F] 组把两侧一并钉死（F1–F3 折、F4 不折）。
def _read_token() -> str:
    tok = (os.environ.get("HIVE_ORCH_TOKEN") or "").strip()
    if tok:
        return tok
    path = (os.environ.get("HIVE_ORCH_TOKEN_FILE") or "").strip()
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError as e:
        raise OrcError(f"读令牌文件失败：{path}（{e}）")


# 生效条件：job_id 提供且 _read_token() 返回非空令牌、verify_token(tok) 返回非 None principal 时，设置 principal.session=f"hive_orch_{job_id}" 并尽力设 principal.harness="hive-orch"，返回 principal；令牌缺失、校验抛异常或 principal 为 None 均抛 OrcError。
def load_principal(job_id: str):
    """读派生令牌 → Principal（fail-closed：任何失败抛 OrcError）。

    为什么必须 fail-closed：编排器的权限意图是「能裁决子代理冲突」，而裁决在库层
    走 `require_admin`。若令牌缺失就沿用默认 recorder 身份继续跑，模型每一轮裁决
    都会失败，但 job 仍以 done 结束 —— 使用者看到的是一次「成功」的编排，实际
    从未裁决过任何冲突。这正是第 4 条禁止的静默错执行，故此处直接终止。
    """
    tok = _read_token()
    if not tok:
        raise OrcError(
            "未配置编排器令牌。签发（真源=md_cg/tokens.py 的 ORCH_* 常量）：\n"
            "  python -m md_cg.tokens orch --token-file-in <designer令牌文件> --out <orch.token>\n"
            "然后把令牌注入 hive serve 环境：HIVE_ORCH_TOKEN（或 HIVE_ORCH_TOKEN_FILE）\n"
            "参考：md_cg/tokens.py 顶部 ORCH_* 注释（收窄面与残余面的完整说明）")
    _ex._md_cg_import()
    from md_cg.tokens import verify_token            # noqa: PLC0415
    try:
        principal = verify_token(tok)
    except Exception as e:                            # noqa: BLE001
        raise OrcError(f"令牌校验失败（{type(e).__name__}: {e}）")
    if principal is None:                             # 防御：校验器若改握手形态
        raise OrcError("令牌校验返回空身份")
    principal.session = f"hive_orch_{job_id}"         # 会话隔离：编排者记忆可区分
    try:
        principal.harness = "hive-orch"
    except Exception:                                 # noqa: BLE001
        pass
    return principal


# ------------------------------------------------------------------ 卡片视图

# 生效条件：job_id 指向 _CFG['jobs'] 下任务，full 缺省 False 用 CARD_CHARS 截断（True 则不截断）；view 为空时按 state 是否在 TERMINAL_STATES 填 hint 后返回，view 含 content_head 时填 card['content_head'] 与 card['content_truncated']=True，否则填 card['content']=view.get('content')，并透传 view 中 ok/need_continue/handoff_ready/error_code/usage，card['tool_calls']=len(view.get('tool_trace') or [])，tool_trace_brief 取 trace[-TRACE_MAX:] 的 tool/ok/brief。
def _card(job_id: str, full: bool = False) -> dict:
    """子任务卡片（Q2）：正文头 + 工具轨迹摘要 + 指针；full=True 时不截断。"""
    jobs = _CFG["jobs"]
    job_dir = os.path.join(jobs, job_id)
    st = _hm._read_status(jobs, job_id) or {"job_id": job_id, "state": "unknown"}
    card = {
        "job_id": job_id,
        "state": st.get("state"),
        "elapsed_s": st.get("elapsed_s"),
        "error": st.get("error"),
        "result_path": os.path.join(job_dir, "result.json"),
    }
    # M5 同源标记：卡片带 source_group（编排者收口时识别同源孪生结果）
    for c in _CFG.get("children") or []:
        if c.get("job_id") == job_id and c.get("source_group"):
            card["source_group"] = c["source_group"]
            break
    view = _hm._result_view(job_dir, head=None if full else CARD_CHARS)
    if not view:
        if card["state"] in TERMINAL_STATES:
            card["hint"] = "已终态但无 result.json（worker 可能被强杀/崩溃）"
        else:
            card["hint"] = "执行中（继续轮询 poll_subtasks）"
        return card
    if "content_head" in view:
        card["content_head"] = view["content_head"]
        card["content_truncated"] = True
        card["hint"] = "细节用 read_full(job_id)"
    else:
        card["content"] = view.get("content")
    for k in ("ok", "need_continue", "handoff_ready", "error_code", "usage"):
        if k in view:
            card[k] = view[k]
    trace = view.get("tool_trace") or []
    card["tool_calls"] = len(trace)
    card["tool_trace_brief"] = [
        {"tool": t.get("tool"), "ok": t.get("ok"), "brief": t.get("brief")}
        for t in trace[-TRACE_MAX:]
    ]
    return card


# 生效条件：无入参，遍历 _CFG['children'] 返回每项 c['job_id']；若某项缺 job_id 则抛 KeyError。
def _known_children() -> list:
    return [c["job_id"] for c in _CFG["children"]]


# -------------------------------------------------------------- 工具实现（三）

# 生效条件：job_dir=None 为可选入参；① env 或 config 任一显式设 HIVE_JOBS_DIR（含 config 胜出合并语义）→ 返回 _hm._jobs_dir() 原样（N89 批次 49 一致语义不动）；② 两键皆空（或皆空串）且 job_dir（缺省取 _CFG['job_dir']）去空白非空时，返回 os.path.dirname(os.path.abspath(job_dir))——serve 以 `hive serve --jobs X` 显式钉池启动且未设键时，本编排器的 job_dir 必在真实池 X 之下，父目录即 serve 实际监听池（N145，2026-09-28 第 23 轮）；推导池不是目录（job_dir 未就位/伪造路径）时回落 ①，不引入新失败面。
def _resolve_jobs_dir(job_dir: str | None = None) -> str:
    """子任务池解析：显式键 > job_dir 父目录推导 > 默认池（N145）。

    历史缺陷（历轮口径 N142，v17 重编 N145）：_spawn(:477) 与 main() 的
    _CFG['jobs'](:662) 只经 _hm._jobs_dir() 吃 env+config（N89 修复面），
    不含 job_dir 推导——rust spawn_executor（src/exec.rs:91-107）Command
    继承 serve env 且仅注入 HIVE_RESULT_ANCHOR 不注入 HIVE_JOBS_DIR，
    `hive serve --jobs X`（env/config 均无键）形态下回落 REPO/hive/jobs
    默认池 ≠ X：spawn_subtask 把子任务提交进默认池，serve 在池 X 无人
    领取，子任务永久饿死且 spawn 返回 ok=True（观测面全绿与实况相悖）。

    诚实边界：独立编排（orch.py <任意目录> 直跑、无 serve）时父目录推导
    指向该目录父级——此时本无「真实池」可言，推导值与旧默认值同为约定
    面；生产面（serve spawn 的编排器）job_dir 恒为 <池>/<job_id>，推导
    即真实池。设键形态（显式 env/config）不受本函数影响（N89 不动）。
    """
    env_set = bool((os.environ.get("HIVE_JOBS_DIR") or "").strip())
    cfg_set = False
    try:
        cfg, _err = _hm._load_local_config()
        cfg_set = bool(str((cfg or {}).get("HIVE_JOBS_DIR") or "").strip())
    except Exception:  # noqa: BLE001 —— config 读不了按未设处理，回落口径不变
        cfg_set = False
    if env_set or cfg_set:
        return _hm._jobs_dir()
    jd = job_dir if job_dir is not None else (_CFG.get("job_dir") or "")
    if str(jd).strip():
        pool = os.path.dirname(os.path.abspath(str(jd)))
        if os.path.isdir(pool):
            return pool
    return _hm._jobs_dir()


# 生效条件：a 为 dict，当 a.get('depends_on') 非 None 时先过 pool 解析后的 _hm._dep_gate（H-6：格式 = h 开头且不含路径成分的 job_id，与 rust job::valid_job_id 同判据；存在性 = pool/<dep> 是目录，与 CLI `hive submit` 同口径）——不过闸即返回 {'ok': False, 'error': ...}（**不写子 spec、不静默丢弃、不降级为「无依赖」**）；随后在 len(_CFG['children']) < _CFG['max_subtasks']、a.get('user_prompt') 去空白后非空、a.get('model') 或 _CFG['model'] 去空白后非空、a.get('tools') 各项（缺省/空列表回落 list(SUB_TOOLS_ALLOW)）均属 SUB_TOOLS_ALLOW、a.get('context_files') 每项对应路径 isfile 为真、**四槽之三 identity/task/unit 齐备**（显式传值优先，缺省继承 _CFG['slots']——即本编排者 spec 的同名键；两处都缺即 {'ok': False, 'error': '缺四槽入参…'}，绝不兜底造 id）时，构造 sub 白名单键（仅当 a.get(k) not in (None, '', [], {}) 才写入 system_prompt/context_files/max_tool_rounds/web_search_backend/mdcg_root/max_tokens/temperature/thinking/depends_on），timeout_s 取 _ex._int_arg(a,'timeout_s',_hm.DEFAULT_TIMEOUT_S,hi=sys.maxsize)、context_budget_tokens 取 _ex._int_arg(a,'context_budget_tokens',_hm.DEFAULT_CONTEXT_BUDGET_TOKENS,hi=sys.maxsize)（脏值/非正回落默认，不夹紧），reasoning_effort 取 a.get('reasoning_effort') or _hm.DEFAULT_REASONING_EFFORT，pool 解析经 _resolve_jobs_dir()（N145：双键皆空时从 _CFG['job_dir'] 父目录推导真实池，设键时 N89 语义原样）、env HIVE_SUBAGENT_API_KEY 去空白非空时 sub 加布尔键 use_subagent_llm=True（C4：只写布尔，不写值/不写 env 名/不写地址；为假时该键不出现）提交（_hm._submit：内部调 Rust 侧 `hive alloc-id` 分配 id，本面不自造；SubmitError → {'ok': False, 'error': …}）后 append 到 _CFG['children']、_save_children()、_ex.progress(kind='spawn_subtask') 并返回 ok=True 及 defaults；上述前置失败则返回对应 {'ok': False, 'error': ...}。
def _spawn(a: dict) -> dict:
    """派发子任务。

    护栏（结构性，不靠约定）：
      · tools 只允许 SUB_TOOLS_ALLOW 的子集 —— 编排工具不外传，子代理无法再编排
      · 子 spec 由**白名单键**构造，`orchestrate` 不可能出现 → 结构上防无限递归
      · 子任务数达上限即诚实报错（不静默丢弃、不静默排队）
      · depends_on（H-6）透传但先过 `_hm._dep_gate` 两道闸（格式 + 存在性，与 CLI
        同判据）：不过闸即回 ok=False，**不写子 spec、不降级为「无依赖」**
      · 四槽（B8）必填：显式传值优先、缺省继承编排者 spec 的同名槽、两处都缺即
        诚实报错——**不兜底造 id**（id 的唯一来源 = Rust 侧分配器）
    提交走 _hm._submit（与 MCP 面**同一份** job 契约，避免第二份实现漂移）；
    但**不**走 _hm._t_spawn —— 它内含 _ensure_serve，而编排者本身就跑在 serve 的
    worker 里，serve 必然存活，无需（也不应从 worker 内）尝试拉起第二个 serve。
    """
    limit = _CFG["max_subtasks"]
    if len(_CFG["children"]) >= limit:
        return {"ok": False, "error": (
            f"子任务数达上限 {limit}（spec.orchestrate.max_subtasks 可调）。"
            f"请先 poll_subtasks 收口已有子任务，或提高上限后重试。")}
    prompt = (a.get("user_prompt") or "").strip()
    if not prompt:
        return {"ok": False, "error": "缺必填参数 user_prompt"}
    model = (a.get("model") or _CFG["model"] or "").strip()
    if not model:
        return {"ok": False, "error": "无可用 model（编排者 spec.model 缺失且未显式传 model）"}
    tools = [str(t) for t in (a.get("tools") or list(SUB_TOOLS_ALLOW))]
    bad = [t for t in tools if t not in SUB_TOOLS_ALLOW]
    if bad:
        return {"ok": False, "error": f"子代理不可用工具 {bad}（只允许 "
                f"{list(SUB_TOOLS_ALLOW)}；编排工具不外传防递归）"}
    for rel in a.get("context_files") or []:
        p = rel if os.path.isabs(rel) else os.path.join(os.getcwd(), rel)
        if not os.path.isfile(p):
            return {"ok": False, "error": f"context 文件不存在: {p}"}
    # 四槽（id 契约 v2 · B8）：显式传值优先，缺省继承编排者自身 spec 的同名槽
    # （`_CFG["slots"]`，由 main() 从本编排者 spec 读入）；**两处都缺即 fail-closed
    # 报错**——绝不兜底造 id（旧 `h{毫秒}_{uuid6}` 已退场：它会绕过 Rust 侧分配器的
    # 独占创建与五单元闭集，正是 H-1 那半边缺陷的形状）。
    slots = {k: str(a.get(k) or _CFG["slots"].get(k) or "").strip()
             for k in SLOT_KEYS}
    missing = [k for k, v in slots.items() if not v]
    if missing:
        return {"ok": False, "error": (
            f"缺四槽入参——四槽 = 身份/任务/单元/编号，其中 identity / task / unit "
            f"**必填**（编号由分配器独占创建给出），不许兜底造 id。缺："
            f"{'、'.join(missing)}。来源二选一：① 本工具的 identity/task/unit 参数"
            f"（显式传值）；② 编排者自身 spec 的同名键 identity/task/unit"
            f"（当前 spec 值：{_CFG['slots'] or '（未带）'}）。"
            "可照抄示例：spawn_subtask(user_prompt=…, identity=\"zcode端\", "
            "task=\"灵枢迭代\", unit=\"反思单元\")——单元槽取蜂巢五单元闭集"
            "（记录单元/反思单元/验证单元/输出单元/维生系统）。")}
    sub = {"model": model, "user_prompt": prompt, "tools": tools,
           "workdir": os.getcwd(),
           # M3.2 来源行「父任务」链路：子任务 spec 带父编排任务 id，
           # exec.py main() 读入后由工具层注入 worker 直写来源行
           "orch_job": _CFG.get("job_id") or ""}
    # 白名单透传键（H-6 补 depends_on：子任务依赖门禁的透传面——编排者把上游
    # 子任务 job_id（如 poll_subtasks 看到的 id）填进来，子任务即受调度侧
    # deps_gate 约束（全 done 才领取）。显式传值优先、缺省不写。）
    for k in ("system_prompt", "context_files", "max_tool_rounds", "web_search_backend",
              "mdcg_root", "max_tokens", "temperature", "thinking", "depends_on"):
        if a.get(k) not in (None, "", [], {}):
            sub[k] = a[k]
    # 统一子代理默认注入（与 MCP 面同源常量，显式传值优先）。
    # 脏参容错（v2 N13，2026-09-25）：timeout_s/context_budget_tokens 是模型
    # 可控参数，function calling 常见脏值 '600s'/'20k'/[600] 曾从裸 int() 抛
    # ValueError/TypeError 逃出工具处理器 → exec.main 兜底以 EXIT_API 判死
    # 整个编排 job（已派发子任务全部成孤儿）。接 exec._int_arg 模板：脏值/
    # 非正回落默认；hi=sys.maxsize = 本面不引入新值域上限（上限属调度面语义）。
    sub["timeout_s"] = _ex._int_arg(a, "timeout_s", _hm.DEFAULT_TIMEOUT_S,
                                    hi=sys.maxsize)
    sub["reasoning_effort"] = a.get("reasoning_effort") or _hm.DEFAULT_REASONING_EFFORT
    sub["context_budget_tokens"] = _ex._int_arg(
        a, "context_budget_tokens", _hm.DEFAULT_CONTEXT_BUDGET_TOKENS,
        hi=sys.maxsize)
    # C4（批次69）：子代理模型端点开关——**只写布尔**。是否用
    # HIVE_SUBAGENT_API_KEY 覆盖由子任务执行器按**自己的 env** 解析；密钥/base
    # 的值绝不进 spec（spec 落盘、进 result/log、被读取方与编排链看见 → 写 spec
    # 者即可让执行器把任意凭据发往任意地址）。编排者 env 没有该键时**不写**该键
    # （子任务继承主配置，与历史行为逐位一致）。
    if (os.environ.get("HIVE_SUBAGENT_API_KEY") or "").strip():
        sub["use_subagent_llm"] = True
    jobs = _resolve_jobs_dir()
    # 依赖门禁（H-6）：子任务 depends_on 由**模型可控**的 function calling 参数而来，
    # 故与 MCP 面同闸同判据——_hm._dep_gate（格式 = h 开头且不含路径成分的 job_id，
    # 与 rust job::valid_job_id 同口径；存在性 = pool/<dep> 是目录，与 CLI
    # `hive submit` 同口径）。不过闸即 fail-closed 回 {'ok': False, ...}：不写子
    # spec、不静默丢弃、不降级为「无依赖」（静默丢弃 = 模型以为串好了 DAG、实际
    # 子任务无依赖并发跑，正是本仓第 4 条禁止的静默错执行；判据实现只此一份，
    # 勿在此另立第二套）。
    dep_err = _hm._dep_gate(jobs, a.get("depends_on"))
    if dep_err:
        return {"ok": False, "error": dep_err}
    try:
        # 分配 id 的唯一通道（B7/B8）：`_hm._submit` 内部调 Rust 侧
        # `hive alloc-id`——编排面**不自造 id**（§五 裁决 3：分配器唯一实现在
        # Rust 侧）；HIVE_EXE 不可用/槽非法/号位用尽 → 显式 ok:False（不静默降级）。
        cid = _hm._submit(jobs, sub, slots["identity"], slots["task"], slots["unit"])
    except _hm.SubmitError as e:
        return {"ok": False, "error": str(e)}
    _CFG["children"].append({
        "job_id": cid, "prompt_head": prompt[:160], "tools": tools,
        "model": model, "ts": time.time(),
        # M5 同源标记：同 context_files+同 model 归同组（纠正链裁决识别孪生来源）
        "source_group": _source_group(model, a.get("context_files")),
    })
    _save_children()
    _ex.progress(_CFG["job_dir"], kind="spawn_subtask", child=cid,
                 tools=tools, prompt=prompt[:200])
    return {"ok": True, "job_id": cid, "state": "pending", "tools": tools,
            "defaults": {"timeout_s": sub["timeout_s"],
                         "reasoning_effort": sub["reasoning_effort"],
                         "context_budget_tokens": sub["context_budget_tokens"]},
            "hint": "不要等；继续派发其它子任务，稍后用 poll_subtasks 收口"}


# 生效条件：a 为 dict，a.get('job_ids') 转字符串后非空则用之，否则回落到 _known_children()；若 ids 仍空返回 {'ok': True, 'count': 0, 'children': [], 'hint': ...}；任一 id 不属于 _known_children()（含 ../ 穿越形态）返回 {'ok': False, 'error': ...}（与 _read_full 同款 fail-closed），否则 full=bool(a.get('full')) 逐 id 调 _card，done 计 c.get('state') 在 TERMINAL_STATES 的卡片，返回 count/done/active/children。
def _poll(a: dict) -> dict:
    known = _known_children()
    ids = [str(x) for x in (a.get("job_ids") or [])] or known
    if not ids:
        return {"ok": True, "count": 0, "children": [],
                "hint": "尚未派发子任务（先 spawn_subtask）"}
    bad = [i for i in ids if i not in known]
    if bad:
        return {"ok": False, "error": (
            f"{bad} 含非本编排者派发的任务（越权读被拒）。"
            f"已知子任务：{known or '（无）'}")}
    full = bool(a.get("full"))
    cards = [_card(i, full=full) for i in ids]
    done = [c for c in cards if c.get("state") in TERMINAL_STATES]
    return {"ok": True, "count": len(cards), "done": len(done),
            "active": len(cards) - len(done), "children": cards}


# 生效条件：a 为 dict，a.get('job_id') 去空白后非空且 jid 属于 _known_children() 时，cap=_ex._int_arg(a,'max_chars',FULL_MAX_CHARS,hi=sys.maxsize)（脏值/非正回落默认），读 _CFG['jobs']/jid/result.json；OSError 返回 {'ok': False, ...}，len(raw)>cap 时返回 truncated=True/head，否则返回 truncated=False/raw；job_id 缺失或越权返回 {'ok': False, ...}。
def _read_full(a: dict) -> dict:
    jid = (a.get("job_id") or "").strip()
    if not jid:
        return {"ok": False, "error": "缺必填参数 job_id"}
    if jid not in _known_children():
        return {"ok": False, "error": (
            f"{jid} 不是本编排者派发的子任务（越权读被拒）。"
            f"已知子任务：{_known_children() or '（无）'}")}
    # 脏参/负数容错（v2 N13）：'2k' 等脏串曾抛 ValueError 逃出杀 job；
    # 负数（如 -100）曾使 len(raw)>cap 恒真而 head=raw[:-100]——truncated=True
    # 却返回 ~90% 全文（截断契约破坏）。_int_arg：脏值/非正一律回落默认。
    cap = _ex._int_arg(a, "max_chars", FULL_MAX_CHARS, hi=sys.maxsize)
    path = os.path.join(_CFG["jobs"], jid, "result.json")
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        return {"ok": False, "error": f"result.json 不可读（{e}）", "result_path": path}
    if len(raw) > cap:
        return {"ok": True, "job_id": jid, "result_path": path, "truncated": True,
                "chars": len(raw), "head": raw[:cap],
                "hint": f"全文 {len(raw)} 字符超上限 {cap}；调大 max_chars 或直读 result_path"}
    return {"ok": True, "job_id": jid, "result_path": path, "truncated": False,
            "chars": len(raw), "raw": raw}


# 生效条件：按 name 分派，name=='spawn_subtask' 返回 _spawn(args)、'poll_subtasks' 返回 _poll(args)、'read_full' 返回 _read_full(args)，其余 name 返回 {'ok': False, 'error': ...}；job_id 形参在源码中未被使用。
def _record_adjudication(args: dict) -> dict:
    """M5 纠正链侧车：强制字段校验（fail-closed）→ 追加 _adjudication.jsonl。

    台账随编排 job 目录留痕（会话后可审计可回放）；session=本编排 job id。
    """
    kind = str(args.get("kind") or "").strip()
    subject = str(args.get("subject") or "").strip()
    evidence = [str(x) for x in (args.get("evidence") or []) if str(x).strip()]
    note = str(args.get("verdict_note") or "").strip()
    if kind not in _ADJ_KINDS:
        return {"ok": False, "error": f"kind 必须为 {_ADJ_KINDS} 之一，got {kind!r}"}
    if not subject:
        return {"ok": False, "error": "subject 必填（被裁决的子任务 job_id）"}
    if not evidence:
        return {"ok": False, "error": "evidence 必填且非空（裁决依据 job_id 列表）——"
                                      "不以「多个结果一致」代替证据"}
    if not note:
        return {"ok": False, "error": "verdict_note 必填（一句话裁决理由）"}
    rec = {"ts": time.time(), "kind": kind, "subject": subject,
           "evidence": evidence, "verdict_note": note[:400],
           "session": f"hive_orch_{_CFG.get('job_id') or 'unknown'}"}
    path = os.path.join(_CFG.get("job_dir") or "", _ADJ_FILE)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        return {"ok": False, "error": f"裁决台账写入失败: {e}"}
    _ex.progress(_CFG.get("job_dir"), **{**rec, "kind": "adjudication"})
    return {"ok": True, "recorded": rec, "file": _ADJ_FILE,
            "hint": "裁决已留痕；subject 结果按 kind 语义在收口结论中呈现"}


def orch_handler(name: str, args: dict, job_id: str) -> dict:
    """编排工具的处理器（注册进 exec.register_tools）。

    生效条件：name 为四个编排工具之一（spawn_subtask/poll_subtasks/
    read_full/record_adjudication）时按名分派对应处理函数；未知工具名
    → 上抛由执行器工具面统一报错。
    验证方式：test——test_orch 85/0（含 M5 record_adjudication
    fail-closed 字段校验与派生令牌身份链）。"""
    if name == "spawn_subtask":
        return _spawn(args)
    if name == "poll_subtasks":
        return _poll(args)
    if name == "read_full":
        return _read_full(args)
    if name == "record_adjudication":
        return _record_adjudication(args)
    return {"ok": False, "error": f"未注册的编排工具 {name!r}"}


# ---------------------------------------------------------------------- 入口

# 生效条件：spec 为 dict，spec.get('tools') 去空/缺省时初始 tools=['lingshu_cg','web_search','read_file']，否则 tools 为 given 去重；added 为 ("lingshu_cg",)+ORCH_TOOLS 中不在 tools 的项，tools.extend(added) 后返回 (tools, added)。
def merge_tools(spec: dict) -> tuple:
    """算最终工具白名单：编排三工具是**能力下限**（强制并入），lingshu_cg 缺省并入。

    为什么强制：编排器没有这三工具就不是编排器（模型会转而自己干活，交出的
    "编排结果"其实是单代理结果，而 job 仍是 done —— 静默的能力缺失）。显式
    spec.tools 里想关掉编排能力属误配置，并入后由 added 字段留痕可审计。

    read_file 只读、默认全路径放开（读放开 / 写严格）：进缺省面但**不强制并入**，
    显式 spec.tools 不含它即视为使用者主动收窄编排者读面。
    """
    given = [str(t) for t in (spec.get("tools") or [])]
    tools = list(dict.fromkeys(given)) if given else ["lingshu_cg", "web_search", "read_file"]
    added = [t for t in ("lingshu_cg",) + ORCH_TOOLS if t not in tools]
    tools.extend(added)
    return tools, added


# 生效条件：len(sys.argv)<2 时输出 usage 并返回 EXIT_SPEC；否则 job_dir=normpath(sys.argv[1])、job_id=basename(job_dir)，read_spec 异常则写 result 返回 EXIT_SPEC，spec.orchestrate.max_subtasks 为真值时尝试 _CFG['max_subtasks']=max(1,int(...))（TypeError/ValueError 静默跳过），load_principal(job_id) 抛 OrcError 则写 result 返回 EXIT_SPEC，成功则先 _CFG.update({job_id, job_dir, jobs=_resolve_jobs_dir(job_dir)（N145：双键皆空时从 job_dir 父目录推导真实池，设键时 N89 语义原样；显式传局部 job_dir 防字面量构造期读旧值）, model=(spec.get('model') or '').strip()}) 再 _CFG.update({children: _load_children()})（v10 N87：children 装载必须后于 job_dir 就位——单字面量会在构造期以初态空 job_dir 求值 _load_children，恒读 CWD 相对 _children.json）、merge_tools 补 tools、缺 system_prompt 填 ORCH_SYSTEM_PROMPT、写回 spec、register_tools(ORCH_SCHEMAS, orch_handler)、set_principal_factory(...)、log/progress，最后返回 _ex.main() 并在 finally 调 _save_children()。
def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write("usage: orch.py <job_dir>\n")
        return EXIT_SPEC
    job_dir = os.path.normpath(sys.argv[1])
    job_id = os.path.basename(job_dir)
    t0 = time.time()
    try:
        spec = _ex.read_spec(job_dir)
    except Exception as e:                            # noqa: BLE001
        _ex.write_result(job_dir, {"ok": False, "content": f"spec 读取失败：{e}",
                                   "error": f"spec 读取失败：{e}"})
        return EXIT_SPEC

    ov = spec.get("orchestrate")
    if isinstance(ov, dict) and ov.get("max_subtasks"):
        try:
            _CFG["max_subtasks"] = max(1, int(ov["max_subtasks"]))
        except (TypeError, ValueError):
            pass

    # —— ① 身份（Q3）：令牌缺失/不可用 → fail-closed，绝不降级为 recorder 继续跑
    try:
        principal = load_principal(job_id)
    except OrcError as e:
        msg = str(e)
        _ex.log(job_dir, f"编排器身份不可用（fail-closed）：{msg}")
        _ex.progress(job_dir, kind="error", where="orch_token", error=msg[:400])
        _ex.write_result(job_dir, {
            "ok": False, "completed": False, "need_continue": False,
            "content": f"编排器未启动（fail-closed）：{msg}",
            "error": msg, "error_code": "orch_token_unavailable",
            "duration_s": round(time.time() - t0, 2),
        })
        return EXIT_SPEC

    # —— ② 运行时配置（子任务清单持久化读回：换人续跑不重复派发）
    # v10 N87（2026-09-25，复现成立）：children 的装载必须拆到 _CFG 的
    # job_dir 就位**之后**——旧的单个 update 字面量里 "children":
    # _load_children() 在**字典构造期**求值，此刻 _CFG["job_dir"] 仍为模块
    # 初态空串，_children_path() 恒解析为 CWD 相对 "_children.json"（=serve
    # 的 HIVE_DIR）：接管者恒视为无子任务全量重复派发（max_subtasks 从 0
    # 重计可放行翻倍）；CWD 恰有他人/遗留 _children.json 时读进他人清单，
    # poll/read_full 以本编排者身份读他人结果（越权读污染）。两阶段 update
    # 是纯求值顺序调整，零语义变更。
    _CFG.update({
        "job_id": job_id,
        "job_dir": job_dir,
        # N145：显式传本函数局部 job_dir——update 字面量在构造期求值，此刻
        # _CFG['job_dir'] 尚为旧值（N87 同款求值顺序陷阱），不能靠函数内读。
        "jobs": _resolve_jobs_dir(job_dir),
        "model": (spec.get("model") or "").strip(),
        # id 契约 v2（B8）：编排者自身的四槽之三从**本编排者 spec 的同名键**读入
        # （spec 带则透传，缺则 `_spawn` 显式报错）——不推导、不从 job_id 反解
        # （反解是「静默推导」，B1 明令禁止），更不自造 id。
        "slots": {k: str(spec.get(k) or "").strip() for k in SLOT_KEYS},
    })
    _CFG.update({"children": _load_children()})

    # —— ③ spec 补全并写回（exec.main 会重新读盘；补全留痕在 spec 里可审计）
    tools, added = merge_tools(spec)
    spec["tools"] = tools
    if not (spec.get("system_prompt") or "").strip():
        spec["system_prompt"] = ORCH_SYSTEM_PROMPT
    # 编排任务的工具轮次下限（2026-09-22 实测缺陷）：exec.py 默认 5 轮对
    # 「派 N 个子任务 + 逐轮 poll + 收口」天然不够——轮次耗尽触发 forced_final，
    # 模型的「想调工具」意图文本被当最终结论交回（观测：DSML 原文漏进 content）。
    # 下限按子任务容量线性给足；显式传值优先（setdefault 不覆盖）。
    spec.setdefault(
        "max_tool_rounds",
        max(12, 4 + 2 * int(_CFG.get("max_subtasks") or DEFAULT_MAX_SUBTASKS)),
    )
    try:
        # N88（批次 49）：原子写回——exec.main 会重新读盘，裸 open("w") 先截断
        # 再写，写中途异常毁任务契约（rust 重投读坏 spec 永久失败）。
        _atomic_write_json(os.path.join(job_dir, "spec.json"), spec)
    except OSError as e:
        _ex.log(job_dir, f"spec 补全写回失败（{e}）——工具注册仍按内存值生效")

    # —— ④ 注册（默认零行为变更的两个扩展口）
    from md_cg.tokens import ORCH_OPS_ALLOW           # noqa: PLC0415
    _ex.register_tools(ORCH_SCHEMAS, orch_handler)
    _ex.set_principal_factory(lambda args, jid: principal, ops_allow=ORCH_OPS_ALLOW)

    _ex.log(job_dir, f"编排器启动 role={getattr(principal, 'role', '?')} "
                     f"admin={getattr(principal, 'can_admin', '?')} "
                     f"ops={list(getattr(principal, 'ops_allow', ()) or ())} "
                     f"layers={list(getattr(principal, 'layers_allow', ()) or ())}")
    _ex.progress(job_dir, kind="orch_start", max_subtasks=_CFG["max_subtasks"],
                 tools=tools, added=added, token_role=getattr(principal, "role", None),
                 resumed_children=len(_CFG["children"]))

    # —— ⑤ 交给 exec.py 的 agent loop（同一实现，零重复）
    try:
        return _ex.main()
    finally:
        _save_children()


if __name__ == "__main__":
    sys.exit(main())