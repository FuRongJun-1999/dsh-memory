# -*- coding: utf-8 -*-
"""dsh_log_index.py — DSH 会话日志（zstd jsonl）→ 转写 md → 摄取灵枢检索面。

定位
----
把 DSH 端（deepseek harness）的私有会话日志离线转写为 md 并摄取进**私有活库**
（MDCG_ROOT 指向的认知图根），使历史会话正文可被 cg search 检索面召回。
本脚本是一次性/可重跑的摄取工具，不是常驻服务。

隐私纪律（工程纪律第 9 条）与密级裁决
------------------------------------
· DSH 会话日志是**私有侧数据**：摄取目标只能是私有活库 root，绝不推公开库
  （本脚本拒绝把 root 指到本仓库检出内，见 `_guard_root`）。
· 节点密级显式 **internal**（使用者裁决 2026-09-26：「日志不加密，dsh 设计上
  就没有加密」）——internal 不在 at-rest 加密封套内（md_cg/crypto.py:62
  ENCRYPTED_LEVELS=("private","secret")），正文参与全文索引；私有活库内读者
  =本机授权身份（clearance≥internal，md_cg/mdcos.py `_readable` 的共享档语义：
  public/internal 跨会话可见），与手工归档节点同暴露面。v1 曾误标 private
  触发加密致检索零命中（v1.0 验证 gap①），本密级即修。
· **归因与可见性分离**（gap③ 修，使用者拍板设计 2026-09-26）：可见性单点在
  sensitivity（`_readable`：internal 共享档不做会话绑定判定）；归因维度全量
  留痕——frontmatter.writer=写入者、session=<派生标识>（内容寻址，见下）、
  dsh_session_uuid=<原 uuid>、workspace=<工作区目录名>（跨重启稳定的检索锚，
  亦落 tags ws: 前缀项）。
· **会话标识 = 内容寻址派生 hash**：sha256(f"{createdAt毫秒}|{首条 user 消息
  全文}")[:16]——会话 uuid 每次重启必换（已实证）不可作身份锚；派生标识同
  会话重跑同值（稳定性断言在红绿守卫内）。节点 id 前缀
  `dsh-log-<派生标识>-<序号>`：同逻辑会话重跑幂等。
  碰撞防线（N167）：主公式 basis 不含日志文件自身身份，缺 session 首行 /
  同毫秒同首条 user / 退化日志可跨会话碰撞——摄取前核验既有节点归属
  （frontmatter.dsh_log），非本会话即切兜底标识
  sha256(f"{createdAt}|{首条 user}|{workspace}|{session_id}")[:16]
  重编号摄取并 stderr 告警（derive_session_token_ext，正文不丢弃；
  scripts/test_dsh_log_index_token.py 红绿守卫）。
· 工具与报告**不打印日志正文原文**：stdout 只出统计与计数，无任何消息文本。
· 既有 private 旧节点处置：v1/v2/v3 摄取的 private 版 dsh-log- 节点用
  `--retire-private-legacy` 软删除（forget：文件移 trash/ + 删除清单留痕 +
  可 restore——md_cg/mdcos.py forget，需 can_admin 设计者身份），不物理删除。

日志形态（2026-09-26/27 对真实会话逐行探测得出）
------------------------------------------------
<DSH 会话根>/<工作区目录名>/<session-id>/session.v4.jsonl.zstd，zstd 压缩、
解压后逐行 JSON。与本脚本相关的行型：
  · type=session                首行元数据（id / createdAt(ms) / cwd / agentPreset）
  · type=turn/start             data.turn —— 轮次号从这里跟踪
  · type=user/message           用户消息：data.content[].text（type=text 块），
                                以 data.id 去重
  · type=agent/inbox/spliced    用户消息第二通道：data.inserted[]（content[] /
                                source.kind=="user" / id）——与 user/message
                                **同 id 重复**（实测 16/16 重复），按 id 去重
  · type=assistant/message      助手消息：正文在 data.message.content[] 内
                                （type=="text" 块；reasoning / tool-call 块不是
                                正文）。无 text 块的行跳过并计数
  · type=system/message        系统提示节点（dsh 0.1.5 起系统提示成为 surface
                                节点）：正文在 data.message.content[]（与
                                assistant 同形态，data.turn/step 归轮次）——
                                上下文指令，一并提取归档
  · type=developer/message      开发者指令节点（dsh 0.1.7 起 context-only
                                surface）：正文形态同上，一并提取
  · type=tool/call|result、    行为审计类型：只计数不摄取正文（audit 计数
    command/run|done、          可见）
    hook/invoked|result
  · 其余 KNOWN 清单内行型        计入 known_other（识别但不处理）
  · 清单外行型                  **unknown**：逐类型计数，摄取结束 stderr 告警
                                （不失败）；--verbose 逐类型列出——fail-closed
                                纪律：防新版 DSH 事件类型静默消失

事件类型显式清单（KNOWN_DSH_EVENT_TYPES）
----------------------------------------
对照参照实现 dsh-TUI `src/adapter/channel/session-projection.ts` 的
KNOWN_DSH_EVENT_TYPES 显式全集（2026-09-27 经 gh api 拉取；其纪律：未知
事件不静默跳过、前缀匹配明确不用），本地增补一项：
  · 'session' —— 本日志文件首行元数据行型（dsh-TUI 投影面输入为 events 数组
    不含首行，故其清单无此项；本工具按文件消费，必须识别）。
对清单的修订须回对参照实现；清单外新类型出现即告警（见上）。

转写结构（每会话一个 md，写系统临时目录、路径确定→幂等）
------------------------------------------------------
    # 会话 <session-id>（cwd=<cwd> · <ISO 时间> · 预设=<agentPreset>）
    ## turn <n>（用户｜助手｜系统｜开发者）[· k/N]
正文逐段落在对应轮次标题下；**turn 内长正文按空行分段、贪心聚合成
≤CHUNK_MAX 字的章**（超限长段按句边界再切），章数 >1 时标题带 `· k/N`
小节号——docindex 的节点正文=CCG 模板+摘要、不存全文（`md_cg/docindex.py:13-14`，
摘要截 `MAX_SUMMARY=200` 于 `:42/:127/:199`、渲染执行栏截 `MAX_DOC=400` 于
`:266`），turn 整体成章时深处结论会落在摘要线后被截掉、检索无从命中
（v1.0 验证 gap②/覆盖率 33.7%）；分章后每章 ≤600 字，章内结论高概率落入
章摘要（判据：v1.0 C2 案 turn2『仓库位置』结论修前内容级零命中→修后入库
可检索，见模块尾部验证口径）。正文逐段落章；空正文消息跳过。转写体内可能
出现的 ATX 标题样行首加反斜杠转义（不虚构内容，只防正文里的 markdown 标题
被章节切分误认）。

摄取（原则=生产同款章节切分）
----------------------------
不走 cg index_doc（其节点 id 由 docindex.node_id 固定为 `doc_` 前缀，无法满足
dsh-log- 前缀要求），而是**直调同款索引入口**：`refindex.index_dir(kind="doc_ref")`
（内含 docindex.extract 的 level≤3 章节切分、小节合并、围栏感知，与生产
mcp_server index_doc op 同一实现），写入侧逐条对照 refindex.add_items 的
doc_ref 分支（render / condition_space / sensitivity / tags / domain 同源），
仅节点 id 改为 `dsh-log-<session-id>-<章节序号>`。
不写 doc_ref 绑定列：转写文件是系统临时目录里的暂存物（会被系统清理），
绑定列会系统性变 dangling；且 op=ref 回读原文会开第二个日志原文暴露面。
来源溯源改记 frontmatter.dsh_log（session / workspace / 来源相对形态）。
不登记 refindex.Ledger：水位台账在活库根，登临目目录等于把暂存路径写进活库。

幂等
----
· 节点 id 由 (session-id, 章节序号) 决定 → 确定性；
· 写入前查活库索引，已存在即计「已索引跳过」，**不覆写**（活库只增不删）；
· 转写路径确定（临时根 + 工作区 + 会话 id），重跑生成逐字节相同的转写。

用法（第 15 条：argv 列表 + 显式 UTF-8，不经 Windows shell）
    set PYTHONUTF8=1
    python scripts/dsh_log_index.py --sessions-root <DSH会话根> --dry-run
    python scripts/dsh_log_index.py --sessions-root <DSH会话根> --root <灵枢库root>
    python scripts/dsh_log_index.py --sessions-root <DSH会话根> --session <id>
    python scripts/dsh_log_index.py --sessions-root <DSH会话根> --dry-run --verbose
依赖：zstandard（pip install zstandard）；md_cg 包（经 sys.path 仓库根导入）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from md_cg import docindex, refindex, security            # noqa: E402
from md_cg.mdcos import MdCGSecure                        # noqa: E402
from md_cg.security import Principal                      # noqa: E402

#: 转写暂存根（系统临时目录下、路径确定——幂等与来源稳定都靠它）
TRANSCRIPT_ROOT = os.path.join(tempfile.gettempdir(), "dsh-log-transcripts")
#: 会话日志文件名（v4 形态）
LOG_NAME = "session.v4.jsonl.zstd"
#: ATX 标题样行（正文里的 markdown 标题须转义，防章节切分误认）
_ATX_LIKE = re.compile(r"^#{1,6}\s")

# --------------------------------------------------------------------------
# DSH 会话事件类型显式清单（参照 dsh-TUI session-projection.ts，fail-closed）
# --------------------------------------------------------------------------
# 来源：gh api repos/ccch1mneyyy/dsh-TUI/contents/src/adapter/channel/
#       session-projection.ts → KNOWN_DSH_EVENT_TYPES（2026-09-27 拉取）。
# 显式全集、不用前缀匹配（参照实现纪律：未知事件不静默跳过；未知前缀如
# user/unknown-required 不因前缀而被认作已知）。本地增补 'session'（本日志
# 文件首行元数据行型——dsh-TUI 投影面输入为 events 数组不含首行）。
KNOWN_DSH_EVENT_TYPES = frozenset({
    # dsh-session core event map
    "turn/start", "turn/end", "step/start", "step/end", "user/message",
    # 0.1.5 前遗留（流式时序并入结算事件，但旧日志仍带 chunk）
    "assistant/chunk", "assistant/message",
    # 0.1.5：废弃尝试（失败/重试/取消，无表面消息）
    "assistant/attempt",
    # 0.1.5：系统提示成为 surface 节点；0.1.7：开发者指令 context-only 节点
    "system/message", "developer/message",
    "tool/call", "tool/result", "command/run", "command/done",
    "hook/invoked", "hook/result", "agent/inbox/spliced", "todo/write",
    "request/header", "request/context", "session/end-seed",
    # 非 appendable 会话事件（0.1.5 SessionId 解析失败键），折为无行
    "session/not-found",
    # dsh-tui / 生态插件事件类型（精确匹配，非前缀）
    "session/created", "session/disposed", "session/flush", "session/title",
    "session/color", "session/title-llm-request", "session/event",
    "agent/status", "agent/disposed", "agent/request",
    "agent/inbox/claimed", "agent/inbox/discarded",
    "agent-preset/selected", "approval/asked", "approval/decided",
    "approval/policy", "commands/change", "skills/change", "goal/change",
    "plan/mode", "sandbox/mode", "permission/preset", "llm/retry",
    "llm/retry-started", "model/selection", "compaction/start",
    "compaction/end", "compaction/prune", "compaction/summary",
    "deliverables/presented", "feedback/record", "feedback/message-put",
    "feedback/message-delete", "schedule/change", "session-invariant",
    "session-log-deepseek/delivery-accepted", "subagent/start",
    "subagent/end", "subagent/descriptor", "subagent/catalog",
    "subagent/model-selection-policy", "team/member",
    "team/message/delivered", "team/message/queued", "team/task",
    "tool-workflow/agent-start", "tool-workflow/agent-end",
    "tool-workflow/run-start", "tool-workflow/run-end",
    # 0.1.5 改名的 code runner 派发括号；旧日志仍带 code- 拼写，两代都识别
    "tool/code-dispatch", "tool/code-dispatch-start",
    "tool/ptc-dispatch", "tool/ptc-dispatch-start",
    "web/deepseek-search-llm-request", "dsh-tui/btw", "dsh-tui/recap",
    "dsh-working-activity/config", "dsh-working-activity/status",
    "activity/status",
    # 本地增补：会话日志文件首行元数据行型（见模块 docstring）
    "session",
})

#: 行为审计类型——只计数不摄取正文（暂不摄取，计数可见）
AUDIT_EVENT_TYPES = ("tool/call", "tool/result", "command/run",
                     "command/done", "hook/invoked", "hook/result")

#: 上下文指令消息类型（正文一并提取：system=0.1.5 系统提示 surface 节点，
#: developer=0.1.7 开发者指令 context-only 节点）
CONTEXT_MSG_TYPES = {"system/message", "developer/message"}

#: turn 内二次分章的单章正文上限（字符）：docindex 节点摘要只保留章直接正文的
#: 前 MAX_SUMMARY=200 字（md_cg/docindex.py:42/:127），章越大、深处结论越落在
#: 摘要线后被截掉。600 字取「摘要覆盖率 ≥1/3、章数不过爆」的平衡点（实测
#: session-927e3b6a：33 消息 → 207 章，docindex max_items=50000 内）。
CHUNK_MAX = 600


# ==========================================================================
# 1. 发现会话
# ==========================================================================

def discover_sessions(sessions_root: str, workspace: str = None,
                      session: str = None) -> list:
    """枚举 <sessions_root>/<工作区目录名>/<session-id>/session.v4.jsonl.zstd。

    返回 [{workspace, session_id, log}]，按 (workspace, session_id) 稳定排序。
    """
    out = []
    if not os.path.isdir(sessions_root):
        raise SystemExit(f"会话根不存在或不是目录：{sessions_root}")
    for ws in sorted(os.listdir(sessions_root)):
        if workspace and ws != workspace:
            continue
        ws_dir = os.path.join(sessions_root, ws)
        if not os.path.isdir(ws_dir):
            continue
        for sid in sorted(os.listdir(ws_dir)):
            if session and sid != session:
                continue
            log = os.path.join(ws_dir, sid, LOG_NAME)
            if os.path.isfile(log):
                out.append({"workspace": ws, "session_id": sid, "log": log})
    return out


# ==========================================================================
# 2. 解析日志（只产计数与消息序列，绝不落正文到 stdout）
# ==========================================================================

def _text_of(blocks) -> str:
    """content 块列表 → 正文（type=="text" 且 text 为 str 的块，双换行拼接）。"""
    parts = [b.get("text") for b in (blocks or [])
             if isinstance(b, dict) and b.get("type") == "text"
             and isinstance(b.get("text"), str)]
    return "\n\n".join(p for p in parts if p.strip())


def _as_dict(val) -> dict:
    """非对象值一律归零 → {}（**形态判据单点**，N218）。

    旧实现写的是 `o.get("data") or {}`：只兜住「缺失/假值」，兜不住「真值但非
    对象」——`data=[1]` / `data="x"` / `data.message="x"` / `inserted[].source="x"`
    都会在 `.get` 处抛 AttributeError。本函数把「非对象」与「缺失」两种形态收敛
    为同一语义（按空对象处理），与既有 `or {}` 口径一致。
    """
    return val if isinstance(val, dict) else {}


def parse_session_log(log_path: str) -> dict:
    """流式解析一个会话日志 → {meta, msgs, stats}。

    msgs：按日志出现顺序的 [{turn, role, text}]（user/assistant/system/
    developer 正文，空正文不收）。
    stats：各行型计数 + 审计计数（audit）+ unknown 逐类型计数
    （unknown_types）——不含任何正文。

    N218（2026-09-28）：非对象行按**同函数既有 fail-closed 纪律**记账后跳过——
    旧实现 `json.loads` 只 catch ValueError（非 JSON），一行 `null`/`[]`/`123`/
    `"x"` 解析合法却在 `o.get("type")` 抛 AttributeError 逃出 main（main 的 try
    只有 finally、无 except）⇒ 整轮摄取中断：stdout 全空、无 TOTAL 汇总、其后
    会话不再处理、stderr 只有栈无告警。次生腿=内层值非对象同型（`data=[1]` /
    `data` 为字符串 / `data.message` 为字符串 / `inserted[].source` 为字符串），
    故内层取值统一走 `_as_dict` 并计入 lines_bad_shape。
    """
    try:
        import zstandard                                   # noqa: F401
    except ImportError as e:
        raise SystemExit("缺少依赖 zstandard：pip install zstandard") from e
    import io
    import zstandard as zstd

    meta, msgs = {}, []
    seen_ids = set()                 # 消息 id 去重（spliced 与 user/message 同 id）
    cur_turn = 0
    st = {"lines_total": 0, "lines_known_other": 0, "lines_json_error": 0,
          "lines_not_object": 0, "lines_bad_shape": 0,
          "user_dup_events": 0, "assistant_no_text": 0, "assistant_msgs": 0,
          "assistant_text_msgs": 0,
          "user_msgs": 0, "chars_user": 0, "chars_assistant": 0,
          "system_msgs": 0, "system_text_msgs": 0, "chars_system": 0,
          "developer_msgs": 0, "developer_text_msgs": 0, "chars_developer": 0,
          "context_no_text": 0,
          "unknown_lines": 0, "unknown_types": {},
          "audit": {t: 0 for t in AUDIT_EVENT_TYPES},
          "turns_seen": 0}
    with open(log_path, "rb") as f:
        text = io.TextIOWrapper(zstd.ZstdDecompressor().stream_reader(f),
                                encoding="utf-8", errors="replace")
        for line in text:
            line = line.strip()
            if not line:
                continue
            st["lines_total"] += 1
            try:
                o = json.loads(line)
            except ValueError:
                st["lines_json_error"] += 1
                continue
            if not isinstance(o, dict):
                # N218 主腿：合法 JSON 但顶层非对象（null/[]/123/"x"/true）——
                # 按既有 fail-closed 纪律记账后跳过，不中断整轮摄取
                st["lines_not_object"] += 1
                continue
            t = o.get("type")
            if not isinstance(t, str):
                # 形态非法：`type` 非字符串（list/dict 还不可哈希，`t in frozenset`
                # 直接 TypeError）。与顶层非对象同族，记账跳过。
                st["lines_bad_shape"] += 1
                continue
            if o.get("data") is not None and not isinstance(o.get("data"), dict):
                st["lines_bad_shape"] += 1          # data 非对象：记账（按空对象处理）
            d = _as_dict(o.get("data"))
            if t == "session":
                meta = {"id": o.get("id"),
                        "created_at_ms": o.get("createdAt"),
                        "cwd": o.get("cwd") or "",
                        "agent_preset": o.get("agentPreset") or ""}
            elif t == "turn/start":
                if isinstance(d.get("turn"), int):
                    cur_turn = d["turn"]
                    st["turns_seen"] += 1
            elif t == "user/message":
                mid = d.get("id")
                if mid and mid in seen_ids:
                    st["user_dup_events"] += 1
                    continue
                if mid:
                    seen_ids.add(mid)
                body = _text_of(d.get("content"))
                if not body.strip():
                    continue                      # 空正文轮跳过（不计消息）
                st["user_msgs"] += 1
                st["chars_user"] += len(body)
                msgs.append({"turn": cur_turn, "role": "user", "text": body})
            elif t == "agent/inbox/spliced":
                inserted = d.get("inserted")
                if inserted is not None and not isinstance(inserted, list):
                    st["lines_bad_shape"] += 1      # 非列表：形态非法，记账跳过
                    continue
                for it in inserted or []:
                    if not isinstance(it, dict):
                        st["lines_bad_shape"] += 1  # 列表项非对象：记账跳过
                        continue
                    src = it.get("source")
                    if src is not None and not isinstance(src, dict):
                        st["lines_bad_shape"] += 1  # source 非对象：记账跳过
                        continue
                    if (src or {}).get("kind") != "user":
                        continue                  # 只收 source.kind=="user"
                    mid = it.get("id")
                    if mid and mid in seen_ids:
                        st["user_dup_events"] += 1
                        continue
                    if mid:
                        seen_ids.add(mid)
                    body = _text_of(it.get("content"))
                    if not body.strip():
                        continue
                    st["user_msgs"] += 1
                    st["chars_user"] += len(body)
                    msgs.append({"turn": cur_turn, "role": "user", "text": body})
            elif t == "assistant/message":
                if d.get("message") is not None and not isinstance(d.get("message"), dict):
                    st["lines_bad_shape"] += 1      # message 非对象：记账（按空对象处理）
                m = _as_dict(d.get("message"))     # N218：message 非对象按空对象处理
                mid = m.get("id") or d.get("id")
                if mid and mid in seen_ids:
                    st["user_dup_events"] += 1
                    continue
                if mid:
                    seen_ids.add(mid)
                st["assistant_msgs"] += 1
                body = _text_of(m.get("content"))
                if not body.strip():
                    st["assistant_no_text"] += 1  # 无 text 块（reasoning/tool）跳过
                    continue
                st["assistant_text_msgs"] += 1
                st["chars_assistant"] += len(body)
                msgs.append({"turn": d.get("turn")
                             if isinstance(d.get("turn"), int) else cur_turn,
                             "role": "assistant", "text": body})
            elif t in CONTEXT_MSG_TYPES:
                # 上下文指令节点（system / developer）：正文结构 2026-09-27 实测
                # （session-927e3b6a…）：data.message.content[].text，与
                # assistant/message 同形态（data.turn/step 归轮次）；回退
                # data.content 对齐 dsh-TUI firstText 的两级取正文语义。
                role = "system" if t == "system/message" else "developer"
                if d.get("message") is not None and not isinstance(d.get("message"), dict):
                    st["lines_bad_shape"] += 1      # message 非对象：记账（按空对象处理）
                m = _as_dict(d.get("message"))     # N218：message 非对象按空对象处理
                mid = m.get("id") or d.get("id")
                if mid and mid in seen_ids:
                    st["user_dup_events"] += 1
                    continue
                if mid:
                    seen_ids.add(mid)
                body = _text_of(m.get("content")) or _text_of(d.get("content"))
                if not body.strip():
                    st["context_no_text"] += 1      # 无 text 块：计数跳过
                    continue
                st[f"{role}_msgs"] += 1
                st[f"{role}_text_msgs"] += 1
                st[f"chars_{role}"] += len(body)
                msgs.append({"turn": d.get("turn")
                             if isinstance(d.get("turn"), int) else cur_turn,
                             "role": role, "text": body})
            elif t in st["audit"]:                  # 行为审计类型：只计数
                st["audit"][t] += 1
            elif t in KNOWN_DSH_EVENT_TYPES:        # 清单内、无处理分支：识别
                st["lines_known_other"] += 1
            else:                                   # 清单外：unknown 计数
                st["unknown_types"][t] = st["unknown_types"].get(t, 0) + 1
                st["unknown_lines"] += 1
    return {"meta": meta, "msgs": msgs, "stats": st}


# ==========================================================================
# 3. 转写 md（临时目录、路径确定）
# ==========================================================================

def _iso(ms) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


#: 消息 role → 转写章节标题用語
_ROLE_LABELS = {"user": "用户", "assistant": "助手",
                "system": "系统", "developer": "开发者"}


def _split_long_para(para: str) -> list:
    """超 CHUNK_MAX 的长段切成 ≤CHUNK_MAX 的片（只找断点，不改动/丢弃一字）。

    断点优先级：句读（。！？!? 与换行）→ 空格 → 字符硬切。后者兜住系统提示
    里无句读的长段（实测 session-927e3b6a：1670/1206/991 字的英文长句段）。
    """
    pieces = re.split(r"(?<=[。！？!?\n])", para)
    out = []
    for piece in pieces:
        while len(piece) > CHUNK_MAX:
            cut = piece.rfind(" ", 0, CHUNK_MAX)
            if cut < CHUNK_MAX // 2:          # 半章内无空格：字符硬切
                cut = CHUNK_MAX
            out.append(piece[:cut])
            piece = piece[cut:]
        if piece:
            out.append(piece)
    return out


def _chunk_body(text: str) -> list:
    """消息正文 → 章块列表：按空行分段、贪心聚合（确定性，纯函数）。

    段落边界优先（不拆段）；单段超限时按句边界再切。产块逐字节确定性——
    幂等（同日志 → 逐字节同转写）依赖此性质。
    """
    paras = [p for p in text.split("\n\n") if p.strip()]
    units = []
    for p in paras:
        units.extend(_split_long_para(p) if len(p) > CHUNK_MAX else [p])
    chunks, cur, cur_len = [], [], 0
    for u in units:
        if cur and cur_len + 2 + len(u) > CHUNK_MAX:
            chunks.append("\n\n".join(cur))
            cur, cur_len = [], 0
        cur.append(u)
        cur_len = len(u) if cur_len == 0 else cur_len + 2 + len(u)
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks or [""]


def render_transcript(workspace: str, parsed: dict) -> str:
    """解析产物 → 转写 md 文本。

    结构：# 会话 → ## turn N（角色）[· k/N] → 正文；turn 内长正文二次分章
    （≤CHUNK_MAX，见常量注），章数 >1 时标题带小节号。
    """
    meta, msgs = parsed["meta"], parsed["msgs"]
    sid = meta.get("id") or "?"
    head = (f"# 会话 {sid}（cwd={meta.get('cwd', '')}"
            f" · {_iso(meta.get('created_at_ms'))}"
            f" · 预设={meta.get('agent_preset', '')}）")
    prov = (f"来源：DSH 会话根/{workspace}/{sid}/{LOG_NAME}"
            f"（scripts/dsh_log_index.py 转写；私有侧数据，密级 private）")
    lines = [head, "", prov, ""]
    for m in msgs:
        label = _ROLE_LABELS.get(m["role"], m["role"])
        chunks = _chunk_body(m["text"])
        for k, ch in enumerate(chunks, 1):
            suffix = f" · {k}/{len(chunks)}" if len(chunks) > 1 else ""
            lines.append(f"## turn {m['turn']}（{label}）{suffix}")
            lines.append("")
            for ln in ch.split("\n"):
                # 正文里的 ATX 标题样行加 `\` 转义：不改动一个字，只防章节切分误认
                lines.append("\\" + ln if _ATX_LIKE.match(ln) else ln)
            lines.append("")
    return "\n".join(lines)


def transcript_path(workspace: str, session_id: str) -> str:
    """确定性转写路径：<系统临时目录>/dsh-log-transcripts/<工作区>/<会话>/。"""
    return os.path.join(TRANSCRIPT_ROOT, workspace, session_id)


# ==========================================================================
# 4. 摄取（生产同款章节切分 + dsh-log- 节点 id + private 密级）
# ==========================================================================

def derive_session_token(meta: dict, msgs: list) -> str:
    """会话标识 = 内容寻址派生 hash（使用者拍板设计 2026-09-26）。

    sha256(f"{createdAt毫秒}|{首条 user 消息全文}")[:16]——uuid 每次重启必换
    不可作身份锚；派生标识对同一日志文件逐字节稳定（同会话重跑同值）。
    无 user 消息的退化日志仍确定（basis 只含时间戳与分隔符）。

    碰撞面（N167）：basis 不含日志文件自身身份，「缺 type=session 首行」
    「同毫秒+同首条 user」「同为无 user 退化」等场景下**不同会话**会派生出
    同一 token。防线不在本函数（主公式保持不动=既有节点幂等不迁移），在
    ingest_transcript 的归属核验：碰撞即切 derive_session_token_ext 兜底
    空间重编号摄取并 stderr 告警（scripts/test_dsh_log_index_token.py 守卫）。
    """
    first_user = next((m["text"] for m in msgs if m.get("role") == "user"), "")
    basis = f"{meta.get('created_at_ms')}|{first_user}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def derive_session_token_ext(meta: dict, msgs: list, workspace: str,
                             session_id: str) -> str:
    """碰撞兜底标识：basis 追加日志文件路径身份（workspace|session_id）（N167）。

    (workspace, session_id) 目录对唯一标识一个日志文件且跨重启稳定——
    同文件重跑同值（兜底空间内幂等），不同文件恒不同（sha256 抗碰）。
    """
    first_user = next((m["text"] for m in msgs if m.get("role") == "user"), "")
    basis = (f"{meta.get('created_at_ms')}|{first_user}"
             f"|{workspace}|{session_id}")
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def _dsh_log_owner(cg, nid):
    """既有 dsh-log- 节点的归属 (session, workspace)；读不出 → (None, None)。

    经公开读面 cg.get（读隔离内：internal 共享档跨会话可见；private 旧版
    无密钥/不可见时返回 None）。读不出归属按**非本会话**处置（fail-closed）：
    宁可切兜底空间多入一份，不可静默吞掉本会话正文（N167 修的正是静默丢）。
    """
    g = cg.get(nid)
    if not g:
        return None, None
    dl = (g.get("frontmatter") or {}).get("dsh_log") or {}
    return dl.get("session"), dl.get("workspace")


def ingest_transcript(cg, workspace: str, session_id: str, tdir: str,
                      token: str, ext_token: str = None) -> dict:
    """索引一个会话的转写目录并写入活库（已存在节点跳过，不覆写）。

    章节切分走 refindex.index_dir(kind="doc_ref")——与 mcp_server index_doc op
    同一实现（docindex.extract：level≤3、小节合并、围栏感知）。写入逐条对照
    refindex.add_items 的 doc_ref 分支（refindex.py:378-392），差异仅：
      · 节点 id = dsh-log-<派生标识>-<章节序号>（内容寻址，跨重启幂等）；
      · 密级显式 internal（不加密；跨会话共享档——可见性单点在 sensitivity，
        归因与可见性分离）；
      · frontmatter.session=<派生标识>（显式传参覆盖 _attribution 的
        principal.session 缺省，md_cg/mdcos.py:3796-3807）+ workspace 锚 +
        dsh_session_uuid 留痕；
      · 不写 doc_ref / 不登记 Ledger（理由见模块 docstring），
        溯源另记 frontmatter.dsh_log。

    碰撞防线（N167）：摄取前核验主 token 下既有节点归属——任一节点存在但
    frontmatter.dsh_log 不指向本会话（被**别的**会话占用：同毫秒同首条 /
    缺 session 首行 / 退化日志的跨会话派生碰撞）即整体切 ext_token 兜底
    空间重编号摄取，返回值带 collision 由调用方 stderr 告警。不再无条件
    skip-existing（旧逻辑把碰撞第二会话的全部章节静默跳过=数据丢失）。
    存在性判定走索引（与可见性/密钥无关——private 旧节点同样算占用），
    归属核验走 _dsh_log_owner 的公开读面（读不出=非本会话，fail-closed）。
    """
    items, errors, stats = refindex.index_dir(
        tdir, kind="doc_ref", max_files=100, max_items=50000)
    existing = cg.index.get("nodes") or {}
    collision = None
    if ext_token and ext_token != token:
        for i in range(len(items)):
            nid = f"dsh-log-{token}-{i:04d}"
            if nid not in existing:
                continue
            o_sid, o_ws = _dsh_log_owner(cg, nid)
            if o_sid == session_id and o_ws == workspace:
                continue                        # 本会话既有节点：幂等重跑
            collision = {"token": token, "token_ext": ext_token,
                         "occupied_by": {"session": o_sid, "workspace": o_ws}}
            token = ext_token                   # 整体切兜底空间重编号
            break
    indexed, skipped_existing, sens_counts = [], 0, {}
    for i, it in enumerate(items):
        nid = f"dsh-log-{token}-{i:04d}"
        if nid in (cg.index.get("nodes") or {}):
            skipped_existing += 1                   # 已索引：幂等跳过，不覆写
            continue
        s, _basis = docindex.sensitivity_for(it.get("path"), "internal")
        sens_counts[s] = sens_counts.get(s, 0) + 1
        cg.add(
            nid, docindex.render(it),
            layer="knowledge",
            tags=["doc", "doc:md", "dsh-log", f"level:{it.get('level')}",
                  "domain:" + refindex._domain_of(it),
                  f"ws:{workspace}"],
            condition_space=docindex.condition_space(it),
            verification_basis="data",
            sensitivity=s,
            session=token,                          # 归因锚=派生标识（显式覆盖）
            workspace=workspace,                    # 工作区锚（跨重启稳定）
            dsh_session_uuid=session_id,            # 原 uuid 留痕
            dsh_log={"session": session_id, "workspace": workspace,
                     "source": f"DSH 会话根/{workspace}/{session_id}/{LOG_NAME}",
                     "transcript": it.get("path"),
                     "heading_path": it.get("heading_path"),
                     "lineno": it.get("lineno"), "end": it.get("end")})
        indexed.append(nid)
    return {"items": len(items), "indexed": indexed,
            "skipped_existing": skipped_existing,
            "sensitivity": sens_counts, "collision": collision,
            "extract_errors": errors[:5], "stats": stats}


def retire_private_legacy(root: str, tenant: str, actor: str) -> list:
    """软删除既有 private 版 dsh-log- 节点（v1/v2/v3 误标，被 internal 版取代）。

    forget = 软删除：节点文件移 trash/ + 删除清单留痕 + 可 restore
    （md_cg/mdcos.py forget；需 can_admin 设计者身份）。判据 fail-closed：
    nid 以 dsh-log- 开头 **且** frontmatter sensitivity=private 的才动——
    其余节点一律不碰。
    """
    p = Principal(tenant=tenant, actor=actor, clearance="private",
                  can_write=False, can_admin=True, role="designer",
                  harness="dsh", unit="agent", auth_mode="local-cli")
    cg = MdCGSecure(root, principal=p, autoflush=1)
    try:
        retired = []
        for nid, e in sorted((cg.index.get("nodes") or {}).items()):
            if not nid.startswith("dsh-log-"):
                continue
            if (e.get("sensitivity") or "") != "private":
                continue
            r = cg.forget(nid, reason="v4 改标 internal 重摄取取代"
                                     "（gap①加密检索/gap③会话绑定修复）")
            if r.get("ok"):
                retired.append(nid)
        return retired
    finally:
        cg.close()


# ==========================================================================
# 5. root 守卫（严禁公开库；只允许既有活库）
# ==========================================================================

def _guard_root(root: str, allow_init: bool) -> str:
    """校验摄取目标 root：拒绝空值 / 仓库检出内（公开库）/ 非活库根。"""
    root = os.path.realpath(os.path.abspath(root))
    repo = os.path.realpath(REPO_ROOT)
    if root == repo or root.startswith(repo + os.sep):
        raise SystemExit(
            "拒绝：目标 root 位于本仓库检出内（公开库）。"
            "DSH 会话日志是私有侧数据，只能摄取进私有活库（MDCG_ROOT）。")
    if not allow_init and not os.path.isfile(os.path.join(root, "_index.json")):
        raise SystemExit(
            f"拒绝：{root} 不是既有认知图根（缺 _index.json）。"
            "防止手滑新建空库；确认目标无误可用 --allow-init 显式初始化。")
    # 与 mcp_server index_doc op（mcp_server.py:2324）同款部署白名单开关
    security.check_path_root(root, "MDCG_INGEST_ROOT", "dsh_log_index")
    return root


# ==========================================================================
# 6. CLI
# ==========================================================================

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="DSH 会话日志（zstd jsonl）→ 转写 md → 摄取灵枢检索面"
                    "（统计输出不含日志正文）")
    ap.add_argument("--sessions-root", required=True,
                    help="DSH 会话根目录（其下为 <工作区目录名>/<session-id>/）")
    ap.add_argument("--root", default=(os.environ.get("MDCG_ROOT") or "").strip() or None,
                    help="灵枢库 root（缺省取环境变量 MDCG_ROOT；dry-run 可省）")
    ap.add_argument("--session", default=None, help="只处理指定 session-id")
    ap.add_argument("--workspace", default=None, help="只处理指定工作区目录名")
    ap.add_argument("--dry-run", action="store_true",
                    help="只转写与统计，不连库不摄取")
    ap.add_argument("--verbose", action="store_true",
                    help="unknown 事件类型逐类型明细列出（stderr，含类型名与行数）")
    ap.add_argument("--retire-private-legacy", action="store_true",
                    help="摄取后软删除（forget→trash 留痕）既有 private 版"
                         " dsh-log- 节点（被 internal 版取代；需设计者身份）")
    ap.add_argument("--allow-init", action="store_true",
                    help="允许目标 root 为空库（缺省拒绝，防手滑）")
    ap.add_argument("--actor", default="dsh-memory",
                    help="写入身份 actor（须与活库 DEK 身份一致，缺省 dsh-memory）")
    ap.add_argument("--tenant", default="default", help="租户（缺省 default）")
    ap.add_argument("--cleanup-transcripts", action="store_true",
                    help="摄取完成后删除转写暂存目录（默认保留：幂等重跑更快）")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    sessions = discover_sessions(args.sessions_root, args.workspace, args.session)
    if not sessions:
        print("未发现匹配的会话日志（检查 --sessions-root / --workspace / --session）")
        return 1

    total = {"sessions": 0, "turns_user": 0, "turns_assistant": 0,
             "turns_context": 0,
             "nodes_indexed": 0, "nodes_skipped_existing": 0,
             "chars": 0, "lines_skipped": 0,
             "lines_not_object": 0, "lines_bad_shape": 0,
             "audit": {t: 0 for t in AUDIT_EVENT_TYPES},
             "unknown_lines": 0, "unknown_types": {},
             "token_collisions": 0}
    per_session_unknown = []             # [(session_id, {type: count})] verbose 用
    session_tokens = {}                  # session_id -> 派生标识（稳定性审计）
    cg = None
    try:
        for s in sessions:
            parsed = parse_session_log(s["log"])
            token = derive_session_token(parsed["meta"], parsed["msgs"])
            ext_token = derive_session_token_ext(
                parsed["meta"], parsed["msgs"], s["workspace"],
                s["session_id"])
            session_tokens[s["session_id"]] = token
            md = render_transcript(s["workspace"], parsed)
            tdir = transcript_path(s["workspace"], s["session_id"])
            os.makedirs(tdir, exist_ok=True)
            tpath = os.path.join(tdir, f"{s['session_id']}.md")
            with open(tpath, "w", encoding="utf-8", newline="\n") as f:
                f.write(md)
            st = parsed["stats"]
            ctx_msgs = st["system_text_msgs"] + st["developer_text_msgs"]
            ctx_chars = st["chars_system"] + st["chars_developer"]
            row = {"session": s["session_id"], "workspace": s["workspace"],
                   "session_token": token,
                   "lines_total": st["lines_total"],
                   "turns_seen": st["turns_seen"],
                   "msgs_user": st["user_msgs"],
                   "msgs_assistant": st["assistant_text_msgs"],
                   "assistant_lines_total": st["assistant_msgs"],
                   "msgs_context": {"system": st["system_text_msgs"],
                                    "developer": st["developer_text_msgs"]},
                   "chars_user": st["chars_user"], "chars_assistant": st["chars_assistant"],
                   "chars_context": ctx_chars,
                   "audit": dict(st["audit"]),
                   "unknown": {"lines": st["unknown_lines"],
                               "types": dict(st["unknown_types"])},
                   "skipped": {"known_other": st["lines_known_other"],
                               "json_error": st["lines_json_error"],
                               "not_object": st["lines_not_object"],
                               "bad_shape": st["lines_bad_shape"],
                               "assistant_no_text": st["assistant_no_text"],
                               "context_no_text": st["context_no_text"],
                               "dup_events": st["user_dup_events"]},
                   "transcript": tpath}
            total["sessions"] += 1
            total["turns_user"] += st["user_msgs"]
            total["turns_assistant"] += st["assistant_text_msgs"]
            total["turns_context"] += ctx_msgs
            total["chars"] += (st["chars_user"] + st["chars_assistant"]
                               + ctx_chars)
            total["lines_skipped"] += (st["lines_known_other"]
                                       + st["lines_json_error"]
                                       + st["lines_not_object"]
                                       + st["lines_bad_shape"]
                                       + st["assistant_no_text"]
                                       + st["context_no_text"]
                                       + st["user_dup_events"])
            total["lines_not_object"] += st["lines_not_object"]
            total["lines_bad_shape"] += st["lines_bad_shape"]
            for t, c in st["audit"].items():
                total["audit"][t] += c
            total["unknown_lines"] += st["unknown_lines"]
            for t, c in st["unknown_types"].items():
                total["unknown_types"][t] = total["unknown_types"].get(t, 0) + c
            if st["unknown_types"]:
                per_session_unknown.append((s["session_id"],
                                            dict(st["unknown_types"])))
            if args.dry_run:
                row["mode"] = "dry-run（未连库未摄取）"
            else:
                if not args.root:
                    raise SystemExit("未指定 --root 且环境变量 MDCG_ROOT 为空："
                                     "拒绝猜测摄取目标（严禁写公开库）")
                if cg is not None:
                    cg.close()                    # 私有档会话绑定：逐会话换身份
                    cg = None
                root = _guard_root(args.root, args.allow_init)
                # 直调生产写面（review_cli 同款）：直构 Principal + autoflush=1
                # （写一条落一条索引，跨进程立即可见）。principal.session=该会话 id
                # ——私有档节点按 frontmatter.session 绑定归属（mdcos._readable）
                p = Principal(tenant=args.tenant, actor=args.actor,
                              clearance="private", can_write=True,
                              session=s["session_id"],        # 会话绑定归属
                              harness="dsh", unit="agent",
                              auth_mode="local-cli")
                cg = MdCGSecure(root, principal=p, autoflush=1)
                cs = cg.crypto_status()
                if not cs.get("unlocked"):
                    raise SystemExit(f"加密未解锁，拒绝写入私有内容：{cs}")
                ing = ingest_transcript(cg, s["workspace"], s["session_id"],
                                        tdir, token, ext_token)
                row["chapters"] = ing["items"]
                row["nodes_indexed"] = len(ing["indexed"])
                row["nodes_skipped_existing"] = ing["skipped_existing"]
                row["sensitivity"] = ing["sensitivity"]
                row["node_ids"] = ing["indexed"][:5]
                if ing.get("collision"):
                    row["token_collision"] = ing["collision"]
                    row["session_token_main"] = token   # 主标识留痕（已让位）
                    row["session_token"] = ext_token    # 生效标识=兜底空间
                    total["token_collisions"] += 1
                    c = ing["collision"]
                    print(f"WARNING: 会话 {s['workspace']}/{s['session_id']}"
                          f" 派生标识碰撞（主标识 {c['token']} 已被会话"
                          f" {c['occupied_by']['workspace']}/"
                          f"{c['occupied_by']['session']} 占用）——"
                          f"切兜底标识 {c['token_ext']} 重编号摄取，"
                          "正文不丢弃（N167 防线）", file=sys.stderr)
                if ing["extract_errors"]:
                    row["extract_errors"] = ing["extract_errors"]
                if ing["stats"].get("truncated"):
                    row["truncated"] = ing["stats"].get("truncated_reason")
                total["nodes_indexed"] += len(ing["indexed"])
                total["nodes_skipped_existing"] += ing["skipped_existing"]
            print(json.dumps(row, ensure_ascii=False))
    finally:
        if cg is not None:
            cg.close()
        if args.cleanup_transcripts and not args.dry_run:
            for s in sessions:
                tdir = transcript_path(s["workspace"], s["session_id"])
                if os.path.isdir(tdir):
                    for name in os.listdir(tdir):
                        try:
                            os.remove(os.path.join(tdir, name))
                        except OSError:
                            pass
                    try:
                        os.rmdir(tdir)
                    except OSError:
                        pass

    if args.retire_private_legacy:
        if args.dry_run:
            print(json.dumps({"retire_private_legacy": "skipped（dry-run 不连库）"},
                             ensure_ascii=False))
        else:
            if not args.root:
                raise SystemExit("--retire-private-legacy 需 --root")
            root = _guard_root(args.root, args.allow_init)
            retired = retire_private_legacy(root, args.tenant, args.actor)
            total["legacy_private_retired"] = len(retired)
            print(json.dumps({"retire_private_legacy": {"retired": len(retired),
                                                        "node_ids": retired[:10]}},
                             ensure_ascii=False))

    print(json.dumps({"TOTAL": total,
                      "mode": "dry-run" if args.dry_run else "ingest"},
                     ensure_ascii=False))
    # fail-closed 纪律（参照 dsh-TUI session-projection：未知事件不静默跳过）：
    # 摄取/转写结束若有 unknown 行，stderr 打一行告警——不失败，但绝不让新版
    # DSH 事件类型静默消失。--verbose 时逐类型列出明细。
    if total["unknown_lines"]:
        names = "、".join(f"{t}×{c}"
                          for t, c in sorted(total["unknown_types"].items()))
        print(f"WARNING: 检出 {total['unknown_lines']} 行清单外事件类型"
              f"（{len(total['unknown_types'])} 种：{names}）——"
              "新版 DSH 事件类型可能未被识别，请对照 KNOWN_DSH_EVENT_TYPES"
              "（scripts/dsh_log_index.py，源=dsh-TUI session-projection.ts）"
              "修订清单", file=sys.stderr)
        if args.verbose:
            for sid, utypes in per_session_unknown:
                for t, c in sorted(utypes.items()):
                    print(f"unknown-type: {t} × {c}（会话 {sid}）",
                          file=sys.stderr)
    # N218 同款 fail-closed 纪律：非对象/形态非法行已按 json_error 同族记账并跳过
    # （不中断整轮摄取）——但仍须显式告警，绝不让日志损坏静默消失。
    if total["lines_not_object"] or total["lines_bad_shape"]:
        print(f"WARNING: 检出 {total['lines_not_object']} 行顶层非对象 JSON 与 "
              f"{total['lines_bad_shape']} 行形态非法（type 非字符串 / data·"
              "message·inserted 形态不符）——已按失败行记账并跳过，"
              "未中断本轮摄取；请检查会话日志是否损坏或被截断",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
