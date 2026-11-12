#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""state_extract —— **薄垫片**（thin shim）：本体已迁至 `md_cg/state_extract.py`。

本文件**不含任何判据、不含任何实现**：只把 `md_cg.state_extract` 的公开面原样
re-export，使既有 import 路径（`scripts/state_extract.py`、`sync_zcode_session` 的
`_load_state_extract()` 按文件装载）**逐字不变**。判据单点＝`md_cg/state_extract.py`。

**为什么搬（2026-11-02，实测缺陷）**：`package.json` 的 `files` 白名单只发
`scripts/workspace_index.py`，本模块此前整份落在 `scripts/` ⇒ **随包发布物里没有
它**（`npm pack --dry-run --ignore-scripts` 实测 1791 件、`scripts/` 仅 1 件）。
装机侧因此没有抽取器，每轮记账链在装机环境是断的（生产台账 `events=0`）。
`md_cg/` 随包发货，故本体移入；本垫片保持在仓内开发路径上可用。

守卫 `md_cg/test_state_extract.py` 以 AST/文本面钉住：本文件**不得**再出现
`RULES` / `extract_turn` / `extract_and_record` 的**定义**（只有 import 绑定），
否则就是「同一语义两个落点各写一份」的复发。
"""
from __future__ import annotations

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg.state_extract import (            # noqa: E402,F401  —— 薄别名，非实现
    DEFAULT_SUBJECT,
    RULES,
    enabled,
    extract_and_record,
    extract_turn,
)

__all__ = ["DEFAULT_SUBJECT", "RULES", "enabled", "extract_turn",
           "extract_and_record"]
