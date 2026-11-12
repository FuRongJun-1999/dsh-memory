# -*- coding: utf-8 -*-
"""W1 守卫入口（`scripts/run_tests.py` 以 `test_*.py` 发现，故此处为薄壳）。

实际断言在 `md_cg/iface/_verify.py`——文件名以下划线开头，不被运行器当作
独立测试收集，但由本薄壳调用，因此仍进入全量套件。

生效条件：直接运行 `python -X utf8 -m md_cg.test_kernel_iface_contracts`
即执行全部 11 条断言；任一条失败退出码 1。
"""

from __future__ import annotations

import sys

from md_cg.iface._verify import main

if __name__ == "__main__":
    sys.exit(main())
