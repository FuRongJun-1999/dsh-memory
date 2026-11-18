# -*- coding: utf-8 -*-
"""会话名归一（纯叶模块，issue #994）。

背景：`md_cg/stg.py` 曾三处 `from .mcp_server import _normalize_session`，
而 `mcp_server.py` 又 `from . import stg` —— 双向惰性循环，导致 stg 无法在
屏蔽 `md_cg.mcp_server` 的隔离环境独立导入或拆包（#434 硬前置第 2 项）。

本模块把三个函数下沉为**零反向依赖**：只 import 标准库（os），
`session5` 走**延迟 import + fail-soft**（它依赖 zstandard，缺依赖时
退化为「非 s5 形态」，与下沉前逐位一致）。

接口：
  · `is_dsh_session(s)`   —— DSH uuid4 形态判定
  · `is_session5_like(s)` —— s5 五元组形态判定（权威定义见 md_cg/session5.py）
  · `normalize_session(raw)` —— 归一 + 轻校验（只影响归因，不影响写入）

`md_cg/mcp_server.py` 保留原名的**薄包装**（`_is_dsh_session` 等），
签名与语义一字不改，外部调用方不受影响。
"""
from __future__ import annotations

import os

__all__ = ["is_dsh_session", "is_session5_like", "normalize_session"]


def is_dsh_session(s: str) -> bool:
    """DSH 会话 id 形态判定：session-<8>-<4>-<4>-<4>-<12>（uuid4）。"""
    s = str(s or "").strip()
    if not s.startswith("session-"):
        return False
    groups = s[len("session-"):].split("-")
    if [len(g) for g in groups] != [8, 4, 4, 4, 12]:
        return False
    return all(all(c in "0123456789abcdef" for c in g) for g in groups)


def is_session5_like(s) -> bool:
    """会话身份五元组形态（s5.*）判定 —— 权威定义见 md_cg/session5.py。

    s5.<harness>.<unit>.<workspace>.<epoch>.<digest12>；会话身份由
    (harness, unit, 工作区, 会话创建时间, 首条 user 消息) 确定性推导。

    为何不改主校验而走本分支：is_dsh_session 只认 uuid4 形态，session- 前缀的
    非 uuid4 串会被判假进而降级 anonymous；s5.* 属「载体自定的会话名」，走
    normalize_session 的『非 DSH 形态原样采用』分支即可。

    延迟 import（兼容包内/脚本两种加载形态）+ fail-soft：session5 缺失
    （它依赖 zstandard）时安全退化为「非 s5」，不影响既有会话归因。
    """
    try:
        from session5 import is_session5
    except ImportError:
        try:
            from .session5 import is_session5
        except Exception:  # noqa: BLE001
            return False
    try:
        return bool(is_session5(s))
    except Exception:  # noqa: BLE001
        return False


def normalize_session(raw):
    """会话 id 归一 + 轻校验（只影响归因，不影响写入）。

    规则：
      · DSH 形态且根目录下存在该会话 → 原样采用（可重算校验，防编造会话 id）；
      · DSH 形态、根目录可读但无该会话 → "anonymous"（降级不拒绝，防特殊环境丢记忆）；
      · 根目录不存在/不可读（未装 DSH 等）→ 原样采用（fail-soft）；
      · 非 DSH 形态（载体自定的会话名）→ 原样采用；
      · 目录根可用 MDCG_DSH_SESSIONS_ROOT 覆盖（默认 ~/.dsh/sessions）。
    """
    s = str(raw or "").strip()
    if not s:
        return "anonymous"
    if is_session5_like(s):
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
        return s
    return "anonymous"