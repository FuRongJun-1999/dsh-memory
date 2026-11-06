# -*- coding: utf-8 -*-
"""灵枢 1.0 内核层（kernel）——W1 骨架，无实现。

真源：docs/architecture/灵枢1.0_建设路线_v0.1.md §2 解耦分层 / §5 迁移路径 M1。

   适配层   dsh 插件 / MCP server / hive worker   ← 只调 D2，不碰 D1/D0
   接口层   四个契约（Write / Read / Govern / SelfCheck）
   治理层   生命周期四档 · 审计台账 · 回滚/2PC · 资格判定
   内核层   节点存储 · 索引 · 检索打分 · 锁/WAL        ← 本包

**本包为 W1 骨架（M1「建空壳 + 契约类型，无实现」）**：只放类型与协议，
不含任何存储/索引/检索实现。M2 起才把读路径接到此处。

禁止项（路线稿 §2，违反即判耦合）：
- 内核/治理层不得出现 ``from ..dsh``；
- 内核/治理层不得读环境变量决定行为（除路径根）；
- 内核层不得 import 接口层之外的任何宿主类型。

边界：本包当前**零 IO、零副作用**；纯类型声明。
"""

__all__ = ["KERNEL_LAYER", "LAYER_ORDER"]

KERNEL_LAYER = "kernel"

#: 依赖只能自上而下（路线稿 §2）；数字越小越靠上。
LAYER_ORDER = ("adapter", "iface", "govern", "kernel")
