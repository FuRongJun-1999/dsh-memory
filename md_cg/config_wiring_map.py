# -*- coding: utf-8 -*-
"""配置接线地图（生成件，勿手改）。

真源：`scripts/config-wiring-audit.py --emit-map`（AST import 闭包，从生产入口出发）。
UNWIRED 里的模块：登记表把它当锚点，但生产链上一次 import 都没有。
"""

UNWIRED = (
    "md_cg.corpus",
    "md_cg.interop",
    "md_cg.progressive",
    "md_cg.store_pools",
    "md_cg.t27a_per_message",
    "md_cg.whitebox_kb.seed_knowledge",
    "md_cg.whitebox_kb.wisdom.navigate",
)

UNWIRED_ENTRIES = (
    ("MIN_ACCEPT_SCORE", "md_cg.whitebox_kb.wisdom.navigate"),
    ("MIN_DISCRIM", "md_cg.progressive"),
    ("SEED_MIN_ACCEPT_SCORE", "md_cg.whitebox_kb.wisdom.navigate"),
    ("_GIT_TIMEOUT_S", "md_cg.interop"),
)
