# -*- coding: utf-8 -*-
"""session5 · 会话身份五元组形态（s5）的权威定义。

形态（设计者 2026-10-09 定稿）：
    s5.<harness>.<unit>.<workspace>.<start_epoch>.<msg_digest12>
    例：s5.dsh.agent.D_4_ai.1791340000.3f9a2b7c1d05

语义：会话身份由 (harness, unit, workspace, 会话创建时间, 首条 user 消息)
五元组**确定性推导**——任何进程、任何端都能由会话内容复算同一值，不依赖
env 传递。用于治两个已知根因：
  · DSH 端：启动脚本按会话目录 mtime 择优猜会话，而新版 DSH 只更新目录内
    文件、不更新目录 mtime ⇒ 会话身份滞留旧会话；
  · zcode 端：MCP 进程级共享 ⇒ MDCG_SESSION 固化于首启者 ⇒ 跨会话写入错标。

三条决定（设计者）：
  ① 形态字符串 = s5.<harness>.<unit>.<workspace>.<epoch>.<digest12>（已接受）
  ② 起点消息 = **首条 user 消息原文**，截断 **1024** 字符后取 sha1 前 12 位
  ③ 起点时间 = **会话创建时间**（unix 秒）

前缀口径（为什么是 s5. 而不是 session- / sess_）：
  · 不得用 session- ：mcp_server._is_dsh_session 会把 session- 开头者按 uuid4
    形态校验，不符即降级 anonymous（会话标记丢失）；
  · 不得用 sess_    ：security.py 的进程级随机回落桶用它，语义冲突。
  · s5. 走 _normalize_session 的「非 DSH 形态原样采用」分支，无需改主路径即可
    启用；本模块额外提供可复算校验（防编造），供写入侧/审计侧使用。

**依赖（只影响「读会话文件」这条链路：`read_session_file` / `session5_resolve`）**：
  `session5_resolve()` 需读 DSH 会话文件（`session.v4.jsonl.zstd`，多 frame zstd），
  **需自备 `pip install zstandard`** —— 本仓库不声明该依赖，**CI 也不代装**。
  · 未装 ⇒ `read_session_file()` 返回 `zstandard_missing`，`session5_resolve()` 返回 None
    并写入 `reason_out["reason"]`；调用方**拿不到稳定会话身份**——同一会话在不同进程
    可能算出不同 id ⇒ **跨会话写入错标、召回串会话**。
  · **不崩 ≠ 能用**：进程照跑、记忆照写，但**会话隔离这项能力不可用**。
    不要把「不崩」读成「能用」——前者是健壮性，后者是功能可用性，是两件事。
  · **装上也不保证成功**：同一个 None 还有 `not_uuid_form` / `sessions_root_not_found` /
    `session_file_not_found` / `ambiguous_N` / `no_session_header` / `header_incomplete` /
    `no_real_user_message` / `decompress_failed` 等 reason；排查先读 `reason`。
  · **只认 `session.v4.jsonl.zstd`**：纯文本 `session.jsonl` 走不到本链路（不是缺依赖，是同属解不出）。
  · **仅 DSH 端**：其他 harness 无此文件布局，需各自实现适配（`sources.py` 另收 `session.jsonl*`）。
  · ⚠ 「不依赖第三方」这句靠**惰性 import** 撑着：`zstandard` 只在 `read_session_file()`
    函数体内 import，模块级只用标准库（`glob/hashlib/json/os/re`）。若将来把它提到
    模块级，`make/parse/is/verify_session5` 的「仅用标准库」会**静默变假**。
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re

SESSION5_PREFIX = "s5"
SESSION5_MSG_MAX = 1024          # 决定②：首条消息截断长度

_SLUG_RE = re.compile(r"[^A-Za-z0-9_]")
_SEP_RE = re.compile(r"[\\/:]+")
_RUN_RE = re.compile(r"_+")
_S5_RE = re.compile(
    r"^s5\.([a-z0-9_]{1,32})\.([a-z0-9_]{1,32})\."
    r"([A-Za-z0-9_]{1,64})\.(\d{10})\.([0-9a-f]{12})$")


def slug_workspace(path):
    """工作区路径 → slug：分隔符序列与其余非字母数字统一归一为**单**下划线（C:\\proj\\app → C_proj_app、C-proj-app → C_proj_app）。

    口径（与设计者确认的形态示例一致）：
        C:\\proj\\app → C_proj_app （":\\" 连续分隔符归一个 _）
        C-proj-app → C_proj_app （DSH 会话目录名形态）
        /home/x/y → home_x_y
    即无论调用方给原生路径还是已归一的目录名，同一工作区得同一 slug
    （纯函数、跨端一致）——这是「同一会话在任何端复算出同一 id」的前提。
    """
    p = str(path or "").strip()
    p = _SEP_RE.sub("_", p)               # 路径分隔符（含连续）→ 单 _
    p = _SLUG_RE.sub("_", p)              # 其余非字母数字 → _
    p = _RUN_RE.sub("_", p).strip("_")    # 合并连续下划线、去首尾
    return p


def digest_message(first_message):
    """决定②：首条 user 消息原文截断 SESSION5_MSG_MAX 字符 → sha1 前 12 位。"""
    raw = str(first_message or "")[:SESSION5_MSG_MAX]
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def make_session5(harness, unit, workspace, start_epoch, first_message):
    """按五元组生成会话 id（纯函数，可跨端复算）。"""
    h = str(harness or "").strip().lower()
    u = str(unit or "").strip().lower()
    ws = slug_workspace(workspace)
    try:
        ep = int(start_epoch)
    except (TypeError, ValueError):
        raise ValueError("start_epoch 必须是整数（unix 秒）")
    if not h or not u or not ws:
        raise ValueError("harness / unit / workspace 均不得为空")
    if ep <= 0 or ep > 9999999999:
        raise ValueError("start_epoch 必须是 10 位 unix 秒")
    return "%s.%s.%s.%s.%d.%s" % (SESSION5_PREFIX, h, u, ws, ep,
                                  digest_message(first_message))


def is_session5(s):
    """形态判定（不做可复算校验——归一化路径用这个）。"""
    return bool(_S5_RE.match(str(s or "").strip()))


def parse_session5(s):
    """拆解为字段；非 s5 形态返回 None。"""
    m = _S5_RE.match(str(s or "").strip())
    if not m:
        return None
    return {"harness": m.group(1), "unit": m.group(2), "workspace": m.group(3),
            "start_epoch": int(m.group(4)), "msg_digest12": m.group(5)}


def verify_session5(s, first_message):
    """可复算校验（防编造）：给定首条消息，复算 digest 是否吻合。

    仅凭会话 id 本身无法验证（digest 是单向的）；调用方须能提供该会话的
    首条 user 消息原文。提供不了时用 is_session5 做形态判定即可。
    """
    parsed = parse_session5(s)
    if parsed is None:
        return False
    return digest_message(first_message) == parsed["msg_digest12"]


# ── A2 路线：从 DSH 会话文件解析会话身份（s5）──────────────────────────────
#
# 生效条件：需要把「当前 DSH 会话」映射为稳定身份时（写入面优先用 s5 作 session 值）。
#
# 为什么读文件而不是让 DSH 传：DSH 侧的会话 uid **不稳定**——启动脚本按会话目录 mtime
# 猜会话，而新版 DSH 只更新目录内文件、不更新目录 mtime ⇒ 身份滞留旧会话；
# 而**会话的第一句话不变**。故由内容确定性推导（见模块头）。
#
# ⚠️ 本函数**依赖 DSH 的会话文件格式**（`session.v4.jsonl.zstd`）。使用者已裁定：
#    用户主要在 dsh 端，其他 harness 由使用者按各自实现改适配；**不能让 dsh 端改**。
#    格式升级时本函数会**降级返回 None**（调用方退回 sess_xxxx），且必须记账原因。
#
_SESSIONS_ENV = "MDCG_SESSIONS_ROOT"

#: 系统注入前缀——**必须过滤**：子代理会话首条 user/message 是 `<system-reminder>You are
#: teammate ...`，不过滤会让「不同会话算出同一 s5」（实测：214 会话里 5 个撞车，全是这种）。
_SYS_INJECT_PREFIXES = (
    "<system-reminder>", "<user-reminder>", "<system>", "<reminder>",
    "<environment_context>", "<local-command-stdout>", "<command-name>",
)


# 生效条件：显式 root 非空且为目录时原样返回；否则依次试 env `MDCG_SESSIONS_ROOT`、
# `$DSH_HOME/sessions`、`~/.dsh/sessions`、`$USERPROFILE/.dsh/sessions`；全部不存在返回 None。
# **不硬编码任何绝对路径**——本机路径一律由环境或探测得出，换机/换盘不需改代码。
def resolve_sessions_root(root=None):
    """解析 DSH 会话根目录（三级：参数 → 环境 → 探测）。找不到返回 None。"""
    # 显式传参**不回落**：传了就用传的，不存在就 None。
    # 理由：静默回落到别处会让调用方以为在用 A、实际在用 B——本仓反复踩过这类坑。
    if root:
        try:
            p = os.path.abspath(os.path.expanduser(str(root)))
        except Exception:
            return None
        return p if os.path.isdir(p) else None
    cands = []
    env = os.environ.get(_SESSIONS_ENV)
    if env:
        cands.append(env)
    dsh_home = os.environ.get("DSH_HOME")
    if dsh_home:
        cands.append(os.path.join(dsh_home, "sessions"))
    home = os.path.expanduser("~")
    if home and home != "~":
        cands.append(os.path.join(home, ".dsh", "sessions"))
    up = os.environ.get("USERPROFILE")
    if up:
        cands.append(os.path.join(up, ".dsh", "sessions"))
    seen = set()
    for c in cands:
        try:
            p = os.path.abspath(os.path.expanduser(c))
        except Exception:
            continue
        if p in seen:
            continue
        seen.add(p)
        if os.path.isdir(p):
            return p
    return None


# 生效条件：sid 去掉 `session-` 前缀后是 36 字符 uuid4 形态；root 下能 glob 到**唯一**一份
# `*/session-<uuid>/session.v4.jsonl.zstd`。返回 (path, None) 或 (None, 原因串)。
# **按 uuid 定位而非 slug**——实测 uuid 在 6,092 个会话里唯一命中，且不依赖工作区命名算法。
def locate_session_file(session_id, sessions_root=None):
    """按会话 id 定位会话文件。返回 (path, reason)；失败时 path=None + 原因。"""
    sid = str(session_id or "").strip()
    if not sid:
        return None, "empty_session_id"
    uuid = sid[len("session-"):] if sid.startswith("session-") else sid
    if not re.match(r"^[0-9a-fA-F-]{32,40}$", uuid):
        return None, "not_uuid_form"
    root = resolve_sessions_root(sessions_root)
    if not root:
        return None, "sessions_root_not_found"
    pat = os.path.join(root, "*", "session-" + uuid, "session.v4.jsonl.zstd")
    hits = glob.glob(pat)
    if not hits:
        return None, "session_file_not_found"
    if len(hits) > 1:
        return None, "ambiguous_%d" % len(hits)
    return hits[0], None


# 生效条件：path 可读且为 zstd 流；解压后按 jsonl 解析，取 type=session 的头（需含 cwd/createdAt）
# 与**首条非系统注入**的 type=user/message（取 data.content[*].text 拼接）。返回 (hdr, first_text, reason)。
# ⚠ 必须**流式解压**：该文件是多 frame，一次性 `decompress()` 只得到首帧（实测：73KB 只解出 1 行）。
def read_session_file(path):
    """读会话文件 → (会话头 dict, 首条真 user 消息文本, 原因)。"""
    try:
        import zstandard
    except Exception:
        return None, None, "zstandard_missing"
    try:
        with open(path, "rb") as f:
            with zstandard.ZstdDecompressor().stream_reader(f) as rd:
                raw = rd.read()
        text = raw.decode("utf-8", "replace")
    except Exception as exc:                              # noqa: BLE001
        return None, None, "decompress_failed:%s" % type(exc).__name__
    hdr, users = None, []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        t = obj.get("type")
        if t == "session" and hdr is None:
            hdr = obj
        elif t == "user/message":
            users.append(obj)
    if not hdr:
        return None, None, "no_session_header"
    users.sort(key=lambda x: x.get("seq") or 0)
    for u in users:
        d = u.get("data") or {}
        c = d.get("content")
        parts = []
        if isinstance(c, list):
            for x in c:
                if isinstance(x, dict) and x.get("type") == "text":
                    parts.append(str(x.get("text") or ""))
        elif isinstance(c, str):
            parts = [c]
        txt = "\n".join(p for p in parts if p)
        if txt and not any(txt.lstrip().startswith(p) for p in _SYS_INJECT_PREFIXES):
            return hdr, txt, None
    return hdr, None, "no_real_user_message"


# 生效条件：locate + read 均成功且头含 cwd 与非零 createdAt 时，返回 make_session5 结果；
# 任一步失败返回 None，并通过 `reason_out`（可选 dict）回填**具体降级原因**——不得静默降级。
def session5_resolve(session_id, harness="dsh", unit="agent", sessions_root=None,
                     reason_out=None):
    """DSH 会话 id → s5 身份串。失败返回 None，原因写进 `reason_out`（若给）。

    用法（写入面）：
        reason = {}
        s5id = session5_resolve(session, reason_out=reason)
        if s5id:
            session = s5id                 # 用稳定身份
        else:
            log("session5 降级: %s" % reason.get("reason"))   # 显式记账，不静默
    """
    def _fail(why):
        if isinstance(reason_out, dict):
            reason_out["reason"] = why
        return None
    path, why = locate_session_file(session_id, sessions_root=sessions_root)
    if not path:
        return _fail(why)
    hdr, first, why2 = read_session_file(path)
    if not hdr:
        return _fail(why2)
    if not first:
        return _fail(why2 or "no_real_user_message")
    try:
        epoch = int((hdr.get("createdAt") or 0) / 1000)
    except Exception:
        return _fail("bad_created_at")
    cwd = hdr.get("cwd") or ""
    if not cwd or epoch <= 0:
        return _fail("header_incomplete")
    try:
        sid = make_session5(harness, unit, cwd, epoch, first)
    except Exception as exc:                              # noqa: BLE001
        return _fail("make_failed:%s" % type(exc).__name__)
    if isinstance(reason_out, dict):
        reason_out["reason"] = None
        reason_out["file"] = path
    return sid