# -*- coding: utf-8 -*-
"""统一配置层守卫 · pytest 收集入口（脚本式，亦可用 `python -X utf8 -m` 单跑）。

为什么另立本文件：`md_cg/config_registry_guard.py` 与 `md_cg/config_validate.py`
是**脚本式**件（`python -X utf8 -m md_cg.config_registry_guard` 单跑），文件名不匹配
pytest 的默认收集 glob（`test_*.py`）。按仓内既有体例（`md_cg/test_sleep_p1.py`
一类），薄薄一层 shim 把它接进 pytest 收集面，**判据本体仍在被调模块里**（本文件
不复制任何判据，只调用）。

运行：
    python -X utf8 -m md_cg.test_config_registry      # 单跑（含变异自证）
    python -X utf8 -m pytest md_cg/test_config_registry.py -q
"""
from __future__ import annotations

import sys

from . import config_registry_guard as _guard
from . import config_validate as _cv


def test_config_registry_guard_consistency():
    """G1..G4 全绿（登记 == 代码；生成件新鲜；分区表覆盖完整）。"""
    assert _guard.run_all() == 0


def test_config_registry_guard_mutations():
    """定点变异自证：每条变异必红，复原后复跑全绿。"""
    assert _guard.main(["--mutate"]) == 0


def test_config_validate_self_test():
    """校验器内置用例自证。"""
    assert _cv.self_test() == 0


def main(argv):
    fails = 0
    for name, fn in (("一致性（G1..G4）", test_config_registry_guard_consistency),
                     ("定点变异自证", test_config_registry_guard_mutations),
                     ("校验器自证", test_config_validate_self_test)):
        print(f"== {name} ==")
        try:
            fn()
            print("  OK")
        except AssertionError as e:
            fails += 1
            print(f"  FAIL {e}")
    print(f"\n统一配置层守卫（pytest 入口）：{3 - fails} 通过，{fails} 失败")
    return 1 if fails else 0


# 生效条件：无入参（argv 仅用于将来扩展）；依次跑一致性、定点变异、校验器自证三组，任一失败即计入并返回 1，全通过返回 0。
if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
