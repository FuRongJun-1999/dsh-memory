# -*- coding: utf-8 -*-
"""aeis_core — 白箱知识库自带内核（原 aeis 包的最小可移植子集）。

为什么存在
----------
白箱引擎（`whitebox_kb/wisdom/`）原本硬依赖外部 `aeis` 包的记忆内核：
    from aeis.core import (SpacetimeMemoryEngine, ConditionSpace, EdgeType,
                           MemoryLayer, Role, STNode, STEdge)
理论仓拆分后，这些内核随白箱知识库一并内迁，改名 `aeis_core`，
主仓不再需要 pip 安装 `aeis`。

边界（刻意最小）
----------------
· **自带**：`core.py`（时空记忆引擎，纯标准库）· `time_core.py`（衰减核）
  · `semantic.py`（语义坐标，零依赖）· `api.py`（Agent 薄封装）
  · `textutil.py`（自 aeis/layered.py 抽出的纯函数 `_bigram_set`）
· **不带走**：`vision` / `body` / `world_model` / `voxel_world` /
  `scene_simulator` / `game_web` 等——它们在 `core.py` 里全部是**方法内惰性
  导入**，缺失即自动降级，属「身体 / 世界模型」，归 AEIS 库。
  `layered.py`（LLM 路由）同样不搬，只抽其中的纯文本工具。
"""
from .core import (  # noqa: F401
    ConditionSpace,
    EdgeType,
    MemoryLayer,
    Role,
    STNode,
    STEdge,
    LayeredStore,
    SpacetimeMemoryEngine,
)

__all__ = [
    "ConditionSpace",
    "EdgeType",
    "MemoryLayer",
    "Role",
    "STNode",
    "STEdge",
    "LayeredStore",
    "SpacetimeMemoryEngine",
]
