# -*- coding: utf-8 -*-
"""session_norm · 会话身份归一化公共模块（Issue #434 硬前置 #2 解耦落点）。

背景：
    此前 `_normalize_session` 定义在 `md_cg/mcp_server.py`（adapter 接线层），
    `md_cg/stg.py` 在读侧 `_env_session_authority` / `_view_session` /
    `_session_declaration_ignored` 三处惰性 `from .mcp_server import _normalize_session`，
    与 `mcp_server._stg_call` 的 `from . import stg` 构成 `stg ↔ mcp_server` 双向惰性循环。

设计：
    将无宿主依赖的会话归一化纯函数下沉至本公共小模块（仅依赖标准库 `os` 与同层
    `md_cg/session5.py`），使 `stg` 与 `mcp_server` 单向共消费本模块，彻底切断
    `stg → mcp_server` 导入边。`mcp_server` 仍保留同名转发入口以兼容既有外部调用方。
"""
from __future__ import annotations

import os


# 生效条件：s=str(s or "").strip()；不以 "session-" 开头、或去前缀按 "-" 分组后长度不等于 [8,4,4,4,12]、或某组字符不都在 "0123456789abcdef" 时返回 False，三者皆过返回 True。
def is_dsh_session(s: str) -> bool:
    """DSH 会话 id 形态判定：session-<8>-<4>-<4>-<4>-<12>（uuid4）。"""
    s = str(s or "").strip()
    if not s.startswith("session-"):
        return False
    groups = s[len("session-"):].split("-")
    if [len(g) for g in groups] != [8, 4, 4, 4, 12]:
        return False
    return all(all(c in "0123456789abcdef" for c in g) for g in groups)


# 生效条件：优先导入 md_cg.session5.is_session5（兼容包内/脚本形态），成功时返回 bool(is_session5(s))；模块缺失或判定抛异常时返回 False（安全退化为非 s5）。
def is_session5_like(s) -> bool:
    """会话身份五元组形态（s5.*）判定 —— 权威定义见 md_cg/session5.py。"""
    try:
        from .session5 import is_session5
    except ImportError:
        try:
            from session5 import is_session5
        except ImportError:
            return False
    try:
        return bool(is_session5(s))
    except Exception:
        return False


# 生效条件：s=str(raw or "").strip()；s 为空返回 "anonymous"；s5.* 或非 DSH 形态原样返回 s；DSH 形态时以 root=os.environ.get("MDCG_DSH_SESSIONS_ROOT") or ~/.dsh/sessions 遍历条目，存在 root/<name>/s 目录则返回 s，os.listdir 抛 OSError 时返回 s，否则返回 "anonymous"。
def normalize_session(raw) -> str:
    """会话 id 归一 + 轻校验（只影响归因与视图过滤，不影响写入授权）。"""
    s = str(raw or "").strip()
    if not s:
        return "anonymous"
    if is_session5_like(s):          # s5 五元组形态（见 md_cg/session5.py）
        return s
    if not is_dsh_session(s):
        return s
    root = (os.environ.get("MDCG_DSH_SESSIONS_ROOT")
            or os.path.join(os.path.expanduser("~"), ".dsh", "sessions"))
    try:
        for name in os.listdir(root):
            if os.path.isdir(os.path.join(root, name, s)):
                return s
    except OSError:
        return s                      # 目录不可读：不因环境差异丢失会话标记
    return "anonymous"
