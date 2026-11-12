# -*- coding: utf-8 -*-
"""灵枢 1.0 接口层（iface）——四个契约的唯一出口。

真源：docs/architecture/灵枢1.0_建设路线_v0.1.md §3。

适配层（dsh 插件 / MCP server / hive worker）**只允许**从本包导入契约类型；
不得直接 import 内核层或治理层的实现模块（路线稿 §2 禁止项）。
"""

from .contracts import (
    CONTRACT_NAMES,
    IFACE_LAYER,
    ContractViolation,
    GovernContract,
    ReadContract,
    ReadItem,
    ReadRequest,
    RecordState,
    SelfCheckContract,
    SelfCheckReport,
    WriteContract,
    WriteReceipt,
    WriteRequest,
    reject_state_in_scoring,
    require_provenance,
    require_why,
)

__all__ = [
    "CONTRACT_NAMES",
    "IFACE_LAYER",
    "ContractViolation",
    "WriteContract",
    "ReadContract",
    "GovernContract",
    "SelfCheckContract",
    "WriteRequest",
    "WriteReceipt",
    "ReadRequest",
    "ReadItem",
    "SelfCheckReport",
    "RecordState",
    "require_provenance",
    "require_why",
    "reject_state_in_scoring",
]
