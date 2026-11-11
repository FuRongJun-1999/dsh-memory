# -*- coding: utf-8 -*-
"""内核层 · 角色常量真源（`ALL_ROLES` / `WORK_ROLES`）。

真源：docs/architecture/灵枢1.0_建设路线_v0.1.md §2 解耦分层。

**为什么这两个常量必须住内核层**：角色域是被治理的**数据面**，而
`md_cg/mreview/govern.py`（治理流水线）此前反向 `from ..mdcos import
ALL_ROLES, WORK_ROLES`——即「被治理方定义标准」，治理层层层依赖根目录单体，
既成环也给治理层装上了一根本不该有的依赖。常量下沉内核层后，引用方向变成
`govern → kernel`（合法向下），根模块一律 re-export 以保 205 处调用点不变。

**不变量**：本模块零 IO、零副作用、不 import 任何其它层；字面值一字不改
（`roleviews._WORK_ROLES` 与之字面一致，由 test_role_views 的断言钉住）。

生效条件：任何需要「角色全域/工作角色」判定的模块（检索过滤、写入域校验、
mreview 角色投影）都从这里取；根模块 `md_cg.mdcos` 仍 re-export，故
`from .mdcos import WORK_ROLES` 的既有写法继续有效。
不适用条件：不承担**语义裁决**——角色标签的解释权仍属治理层
（`roleviews` / `mreview.govern`），本模块只是常量真源。
"""

from __future__ import annotations

__all__ = ["ALL_ROLES", "WORK_ROLES"]

#: 工作角色（默认不参与正排：工具输出/命令/编辑 会稀释召回）。
WORK_ROLES = ("tool-output", "command", "edit")

#: 角色全域：基础四角色 + 工作角色。
ALL_ROLES = ("user", "assistant", "developer", "knowledge") + WORK_ROLES
