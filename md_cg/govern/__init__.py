# -*- coding: utf-8 -*-
"""灵枢 1.0 治理层（govern）——W1 骨架，无实现。

真源：docs/architecture/灵枢1.0_建设路线_v0.1.md §2 / §5 M4。

治理层职责（路线稿 §2）：
    生命周期四档 · 审计台账 · 回滚/2PC · 资格判定（DEFER/BLINDSPOT）

**本包为 W1 骨架（M1）**：只放类型与协议。M4 才把 revise/retire/rollback
真正切换过来；届时 `rollback` 必须**覆盖正文**——该能力已由
`md_cg/rollback.py` 实现（`method=preimage`，逐字节回前像），M4 的验收是
**回归保持全绿**，不是重新实现（详见路线稿 §4 注）。

与内核层的关系：治理层可依赖内核层；内核层**不得**反向依赖本包。
打分层不得输出 ``state``（#111 既定契约）——`state` 只由治理层给出。
"""

__all__ = ["GOVERN_LAYER", "LIFECYCLE_STATES"]

GOVERN_LAYER = "govern"

#: 生命周期四档（路线稿 §2 的「生命周期四档」；具体语义在 M4 落定）。
LIFECYCLE_STATES = ("active", "dormant", "retired", "tombstoned")
