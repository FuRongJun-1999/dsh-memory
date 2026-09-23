# -*- coding: utf-8 -*-
"""interop_gate —— 互验 verdict 的机械消费方（issue #37 J4）。

为何需要：verdict/valid 此前无任何代码消费方——「门禁 FAIL 一律不得合并」
（设计定稿 §7.4 纪律）只存在于文档，无机械强制。本脚本是该纪律的可执行形态：
合并/收尾流程在动.task/<iter_id> 分支前调本门禁，非 pass 即拒。

判定（与 verdict.json 契约逐字段对应）：
  exit 0  verdict=="pass" 且 valid==True（断言 AND 套件皆过，唯一放行态）
  exit 1  verdict 存在但非放行态（fail / valid!=True / failure_reason 非空）
  exit 2  verdict.json 不存在或不可读（视为未互验，fail-closed）
  exit 3  verdict 形状非法（缺契约字段 / 类型不对——拒绝解析而不是猜测）

用法：
  python scripts/interop_gate.py <iter_id>          # 读 hive/interop/<iter_id>/verdict.json
  python scripts/interop_gate.py --path <verdict.json 绝对路径>
CI / 合并钩子消费 exit code，人类可读说明走 stdout。
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REQUIRED = ("verdict", "valid", "assertions_ok", "failure_reason")


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        v = json.load(f)
    missing = [k for k in _REQUIRED if k not in v]
    if missing:
        raise ValueError(f"缺契约字段: {missing}（旧版产物？重跑互验生成新版）")
    if not isinstance(v.get("valid"), bool) or not isinstance(
            v.get("assertions_ok"), bool):
        raise ValueError("valid/assertions_ok 须为布尔")
    if not isinstance(v.get("passed"), int) or v["passed"] < 0:
        raise ValueError("passed 须为非负整数")
    return v


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 3
    if argv[1] == "--path" and len(argv) >= 3:
        path = argv[2]
    else:
        path = os.path.join(HERE, "hive", "interop", argv[1], "verdict.json")
    if not os.path.isfile(path):
        print(f"[interop_gate] FAIL（未互验，fail-closed）: {path} 不存在")
        return 2
    try:
        v = _load(path)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"[interop_gate] FAIL（形状非法，拒绝猜测）: {e}")
        return 3
    if v["verdict"] == "pass" and v["valid"] is True:
        print(f"[interop_gate] PASS: {path} verdict=pass valid=true "
              f"passed={v['passed']} failed={v['failed']}")
        return 0
    print(f"[interop_gate] FAIL: verdict={v['verdict']!r} "
          f"valid={v['valid']!r} assertions_ok={v['assertions_ok']!r} "
          f"failure_reason={v['failure_reason']!r} —— 不得合并（§7.4）")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
