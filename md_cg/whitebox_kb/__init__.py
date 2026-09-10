# -*- coding: utf-8 -*-
"""whitebox_kb — 灵枢白箱知识库（随灵枢插件主仓自带，不再依赖理论仓）。

内容
----
    wisdom/           白箱引擎（条件论知识图谱 / 检索 / 对话 / 组合，55 py）
    seed_knowledge/   知识卡种子源（wisdom_cards/，首启播种用，离线可重建）
    knowledge/        知识库可读投影（md 综述，非运行时依赖）
    aeis_core/        自带记忆内核（原 aeis 包最小子集，见其 __init__）

路径契约（勿改）
----------------
`wisdom/wisdom_cloud.py` 中 `SEED_CARDS_DIR = dirname(wisdom/) + "/seed_knowledge/wisdom_cards"`，
即 **`seed_knowledge/` 必须是 `wisdom/` 的兄弟目录**——本目录结构即为维持该
契约而保留。`wisdom/` 内 18 个文件用 `sys.path.insert(自身目录)` + 平铺导入
（如 `from wisdom_book import ConditionDex`），故本 `__init__` 在包导入时
**统一注入** `whitebox_kb/` 与 `whitebox_kb/wisdom/` 到 `sys.path`，
使平铺导入与 `import aeis_core` 在任何入口下都确定可解析。
"""
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))

WISDOM_DIR = _os.path.join(_HERE, "wisdom")
SEED_DIR = _os.path.join(_HERE, "seed_knowledge")
KNOWLEDGE_DIR = _os.path.join(_HERE, "knowledge")

#: 随包知识库（137 卡 · 首启种子来源 / 无持久库时的回退库）
DEFAULT_DB = _os.path.join(WISDOM_DIR, "wisdom-book-cloud.db")

#: 平铺导入引导：whitebox_kb/（aeis_core、seed_knowledge）+ whitebox_kb/wisdom/（白箱引擎）
for _p in (_HERE, WISDOM_DIR):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

__all__ = ["WISDOM_DIR", "SEED_DIR", "KNOWLEDGE_DIR", "DEFAULT_DB"]
