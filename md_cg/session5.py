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
"""
from __future__ import annotations

import hashlib
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
    """工作区路径 → slug：分隔符序列与其余非字母数字统一归一为**单**下划线（D:\\4_ai → D_4_ai、D-4_ai → D_4_ai）。

    口径（与设计者确认的形态示例一致）：
        D:\\4_ai    → D_4_ai     （":\\" 连续分隔符归一个 _）
        D-4_ai    → D_4_ai     （DSH 会话目录名形态）
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
