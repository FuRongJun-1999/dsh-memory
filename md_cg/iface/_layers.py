# -*- coding: utf-8 -*-
"""架构判据层台账（W1 判据的**可扩展点**，2026-11-11「结构归位」第一阶段）。

真源：docs/architecture/灵枢1.0_建设路线_v0.1.md §2 解耦分层。

===== 三个概念，别混 =====

① **层（layer）** —— `_LAYERS = ("adapter", "iface", "govern", "kernel")`，
   数字越小越靠上；下层引用上层即「反向依赖」。

② **成员（member）** —— 某层由哪些**路径**构成。默认按目录命名
   （`md_cg/kernel/**` 属 kernel 层……）。但本仓的现实是：治理层的真实实现
   直到 2026-11-11 才搬进 `md_cg/govern/`，此前全部平铺在 `md_cg/` 根目录；
   平铺面里同时住着内核件（`fsutil`/`nodefile`/`mdcg`）、治理件（`audit`/
   `rollback`/`consistency`…）、接口件（`contracts`）与适配面（`mcp_server`）。
   于是「层名 → 路径」必须是一张**显式的成员表**（本模块），而不是隐式的
   目录名推导——否则根目录永远是「无归属」，判据扫不到（这正是本轮之前
   覆盖率只有 0.34% 的成因）。

③ **已知违规基线（known violation）** —— 存量反向依赖的**登记册**。
   为什么必须有：登记表一旦落地，存量违规会让门禁**恒红**；而为了让门禁
   变绿去弱化判据，是比恒红更坏的结果（判据被绕过就再也不可见）。
   基线的纪律（照 `test/chaos_injection/registry.py` 的 `EXPECTED_GAP` 先例）：
     - 每条登记必须**给出违规全文**（文件 + import 名），不是模糊桶；
     - **精确匹配**才放行：出现第 2 条同类违规、或登记的文件里换了个 import，
       仍然红（新增违规必红）；
     - 登记条目**过期即红**（修好了却没删登记 = 基线撒谎，同样要红）。

===== 第一阶段登记了什么、没登记什么 =====

本阶段只登记**真实存在**的边：把 `md_cg/govern/` 与 `md_cg/mreview/` 纳入
`govern` 层后，`mreview → 根目录内核件` 的导入边（治理流水线反向取内核件）
在成员表上成为「govern → kernel」——**这是合法方向（向下）**，不是违规。
真正的违规是**根目录平铺面**里的边：根目录模块没有层归属（`ROOT_LAYER`），
只要它引用了**子包**（`govern`/`kernel`/`iface`），就是一条「根目录 → 子包」
的越权边，按 fail-closed 登记进基线。

清单与计数由 `iface/_verify.py` 的 `_test_root_edges_baseline()` 逐条对照，
并由 `_test_baseline_is_not_a_blanket_pass()` 证明基线**不会**吞掉新增违规。
"""

from __future__ import annotations

#: 根目录平铺模块的层归属（`md_cg/*.py`）。
#:
#: **未归类**在这里写成显式的 `None` 而不是省略：省略会让「没人想过它的层」
#: 与「想过并判定为未归类」长得一模一样，前者是盲区、后者是决策。第一阶段
#: 只对**已确定归属**的模块填层；其余保持 `None`（`ROOT_LAYER`），由
#: 「根目录 → 子包」边清单把它们暴露出来，留待第二阶段逐个归位。
ROOT_LAYER = {
    # ---- kernel：纯基础设施（零业务语义，任何层都可向下依赖）----
    "fsutil": "kernel",        # 文件原子写/锁/日志分片
    "nodefile": "kernel",      # 节点文件读写与 frontmatter 解析
    "mdcg": "kernel",          # 认知图本体（MdCG）——第二阶段拆分对象
    "chain": "kernel",         # 关系链遍历
    "crypto": "kernel",        # 加解密与密级谓词
    "tokens": "kernel",        # 令牌
    "units": "kernel",         # 单元归属
    "timeanchor": "kernel",    # 时间锚
    "reldate": "kernel",       # 相对日期
    "routing": "kernel",       # 通道路由
    "pooling": "kernel",       # 候选池
    "rrf_candidates": "kernel",  # RRF 候选融合
    "rotate": "kernel",        # 台账滚动
    "datapath": "kernel",      # 数据根解析
    "utf8guard": "kernel",     # 编码守卫
    "refindex": "kernel",      # 引用索引
    "bm25": "kernel",          # 词法打分
    "lexical": "kernel",       # 词面工具
    # ---- iface：契约与口径 ----
    "contracts": "iface",
    "protocol": "iface",       # 协议口径（md_cg/protocol 子包的门面）+ 根目录导出
    # ---- govern：治理（已迁入 govern/ 的 7 件 + 仍在根目录的治理件）----
    "lifecycle": "govern",
    "protect": "govern",
    "forgetting": "govern",
    "trust": "govern",
    "security": "govern",
    "roleviews": "govern",
    "autonomy_modes": "govern",
    "scrub": "govern",
    "sustain": "govern",
    "consolidate": "govern",
    "evolution": "govern",
    "weights": "govern",
    "health": "govern",
    "insight": "govern",
    "crosscheck": "govern",
    "census": "govern",
    "conformance_core": "govern",
    "receipts": "govern",
}

#: 子包 → 层（这些是**目录即层**的规范形态）。
PACKAGE_LAYER = {
    "kernel": "kernel",
    "govern": "govern",
    "iface": "iface",
    # mreview 是**治理流水线**（候选 → 规则 → 定位 → 打包 → 落单），
    # 2026-11-11 起登记为 govern 层成员。此前它不在 `_LAYERS` 里，
    # 于是它反向 `from ..mdcos import ALL_ROLES` 这类边**完全不可见**。
    "mreview": "govern",
}

#: 根目录平铺模块里**不是层成员**的（数据面 / 语料 / 纯 CLI / 宿主接口）。
#:
#: 为什么单列：这些不是「待归位的模块」，而是本阶段**明确不动**的对象
#: （数据字典与语料、`bench_*`、`probe_*`、`mutate_*` 与宿主接口面）。
#: 它们与层的关系由 `test_govern_scope` 的硬性纪律规定，不进架构判据。
EXCLUDED_ROOTS = {
    "mcp_server",              # 宿主接线面（adapter）——第二阶段拆分对象
    "whitebox_kb",             # 数据字典与语料（绝不改动）
    "bench_*", "probe_*", "mutate_*",   # 基准/探针/变异脚本（绝不改动）
    "test_*",                  # 测试
    "_*",                      # 私有脚本
}

#: **已知违规基线**（第一阶段实测的「根目录 → 子包」越权边，2026-11-11 测）。
#:
#: 键 = `(根目录模块名, 被引用子包名)`；值 = 该边的说明与出处。
#: 由 `_test_root_edges_baseline()` 逐条与实测边对账：
#:   - 实测算出的边**不在**本表 ⇒ 新增违规 ⇒ 红；
#:   - 本表登记了但实测**已不存在** ⇒ 基线过期 ⇒ 红（要求清理）。
#:
#: 为什么只有 8 条、且全是「根目录 → 自己的治理层真源」：根目录的 7 个治理模块
#: 已迁入 `md_cg/govern/` 并留下薄 shim（必须引用真源才能转发），`mdcos` 则
#: re-export 内核层的角色常量（反掉了「被治理方定义标准」）。**这 8 条都是
#: 有意为之的、随 shim 一起在第二阶段消失的边**，所以登记而不是「修掉」。
#: 反之，任何**新**的「根目录 → 子包」引用（例如根目录模块去 import
#: `md_cg.mreview.*`）都会立刻让门禁转红——这正是本条基线的目的。
KNOWN_ROOT_EDGES: dict[tuple[str, str], str] = {
    ("audit", "govern"):
        "md_cg/audit.py 薄 shim → md_cg/govern/audit.py（2026-11-11 迁移过渡层）",
    ("conformance", "govern"):
        "md_cg/conformance.py 薄 shim → md_cg/govern/conformance.py（迁移过渡层）",
    ("consistency", "govern"):
        "md_cg/consistency.py 薄 shim → md_cg/govern/consistency.py（迁移过渡层）",
    ("revise", "govern"):
        "md_cg/revise.py 薄 shim → md_cg/govern/revise.py（迁移过渡层）",
    ("rollback", "govern"):
        "md_cg/rollback.py 薄 shim → md_cg/govern/rollback.py（迁移过渡层）",
    ("writegate", "govern"):
        "md_cg/writegate.py 薄 shim → md_cg/govern/writegate.py（迁移过渡层）",
    ("writelimit", "govern"):
        "md_cg/writelimit.py 薄 shim → md_cg/govern/writelimit.py（迁移过渡层）",
    ("mdcos", "kernel"):
        "md_cg/mdcos.py re-export `md_cg.kernel.roles` 的 ALL_ROLES/WORK_ROLES"
        "（常量下沉内核层；根模块保留导出以保既有调用点逐字不变）",
}

#: 已知的**层内**违规（子包之间）。键 = `(来源层, 相对文件, import 全名)`。
#:
#: 第一阶段实测到**唯一**一条：`conformance_core`（治理层）在函数内
#: `from .mcp_server import _cg_dispatch`——`mcp_server` 是宿主接线面，
#: 属 adapter 层（最上），于是这是「govern 反向依赖 adapter」。它与
#: `govern/revise.py` 的 `_write_new` 是**同一个耦合**（写入链的唯一入口在
#: mcp_server），第二阶段「写入链下沉 kernel/iface」时一并解除。
#:
#: 登记而非删条目：判据视野一旦把根目录纳进来，就必须**如实登记**存量违规；
#: 把 `conformance_core` 从成员表里摘掉、或给 `_violations` 加例外分支，都是
#: 「为了绿而弱化判据」，比恒红更坏。基线是**逐 import 名精确**的，同文件里
#: 再多一条新的向上依赖仍会红（见 `_test_baseline_is_not_a_blanket_pass`）。
KNOWN_LAYER_VIOLATIONS: dict[tuple[str, str, str], str] = {
    ("govern", "md_cg/conformance_core.py", ".mcp_server._cg_dispatch"):
        "conformance_core._make_ctx 在函数内取宿主接线面的 _cg_dispatch 装配 cg"
        "（与 govern/revise.py::_write_new 同族耦合；写入链下沉后解除）",
    ("govern", "md_cg/govern/revise.py", "..mcp_server._cg_dispatch"):
        "govern/revise.py::_write_new 走正常写入链，其唯一入口就是适配面的"
        " _cg_dispatch（既有设计）。第二阶段写入链下沉到 kernel/iface 后解除。"
        "**禁止改用 importlib 在调用点取用**：那会让这条边从基线里消失，"
        "而耦合仍在——判据只认「可见」，隐藏一条已知耦合会让第二阶段"
        "失去解除账目",
}
