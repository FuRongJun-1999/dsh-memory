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
_REQUIRED = ("verdict", "valid", "assertions_ok", "failure_reason",
             "passed", "failed")


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        v = json.load(f)
    # N217：顶层**类型闸**必须先于字段判定。旧实现直接 `k not in v`——对字符串
    # 而言这是**子串成员测试**：一个含四个字段名的 JSON 字符串（`"verdict valid
    # assertions_ok failure_reason"`）连 missing 闸都绕过，随后 `v.get(...)` 抛
    # AttributeError 逃出 main（契约「形状非法=3」实得 1）。合法 JSON 但顶层非
    # 对象（数组/标量/null）同型：一律判形状非法（3），拒绝解析而不是猜测。
    if not isinstance(v, dict):
        raise ValueError(
            f"verdict 顶层须为对象（实得 {type(v).__name__}）——拒绝解析")
    missing = [k for k in _REQUIRED if k not in v]
    if missing:
        raise ValueError(f"缺契约字段: {missing}（旧版产物？重跑互验生成新版）")
    if not isinstance(v.get("valid"), bool) or not isinstance(
            v.get("assertions_ok"), bool):
        raise ValueError("valid/assertions_ok 须为布尔")
    # 计数口径与产出端 md_cg/interop.shape_check_verdict 一致（「非非负整数」即拒；
    # bool 是 int 的子类，须显式排除），否则 verdict=pass 分支的 f-string 会因
    # 缺键/坏形状抛 KeyError 逃出 main（形状非法=3 实得 1）。
    for key in ("passed", "failed"):
        val = v.get(key)
        if not isinstance(val, int) or isinstance(val, bool) or val < 0:
            raise ValueError(f"{key} 须为非负整数（实得 {val!r}）")
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
