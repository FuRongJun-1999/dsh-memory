#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**薄垫片**（源码树路径保留；设计判据本体只此一处，在 `md_cg/probe_d_retirement_discipline.py`）。

# 功能名：probe_d 的源码树入口（只转发，不含第二份判据）
# 生效条件：源码树里有人照抄 `python -X utf8 scripts/probe_d_retirement_discipline.py` 时；
#   装机侧没有 scripts/，故文档给的是
#   `python -X utf8 -m md_cg.probe_d_retirement_discipline`。
# 子功能：仅 re-export 本体符号 + 转发 `main()`；零判据、零常量。
# 执行：本文件即入口（`__main__` 分支直接调本体 main）。
# 验证方式：`md_cg/test_probe_c_shipped.py`（随包性与两路径等价一并覆盖）。
# 不适用条件：不要在此添加任何逻辑——薄垫片一旦有逻辑，就是「同一判据两个落点」。

为什么保留本文件而不是删掉：仓内既有文档/脚本/测试按 `scripts/` 路径引用它，
删掉会让源码树里的照抄路径失效。薄垫片是**唯一的兼容手段**——只 re-export，
不含第二份判据（沿 `md_cg/state_extract.py` 的同一处置）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.probe_d_retirement_discipline import (   # noqa: F401,E402  —— 薄垫片只转发
    ANCHOR_WINDOW,
    NODE_V1,
    NODE_V2,
    QUERY,
    RETIRE_PATH,
    assert_outside_repo,
    main,
    read_face_ids,
    stg_face_ids,
    wrongly_falsified,
)

if __name__ == "__main__":
    sys.exit(main())
