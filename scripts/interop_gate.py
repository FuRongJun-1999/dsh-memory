# -*- coding: utf-8 -*-
"""interop_gate —— 互验 verdict 的机械消费方（issue #37 J4）。

为何需要：verdict/valid 此前无任何代码消费方——「门禁 FAIL 一律不得合并」
（设计定稿 §7.4 纪律）只存在于文档，无机械强制。本脚本是该纪律的可执行形态：
合并/收尾流程在动.task/<iter_id> 分支前调本门禁，非 pass 即拒。

判定（与 verdict.json 契约逐字段对应）：
  exit 0  verdict=="pass" 且 valid==True 且 assertions_ok==True 且 failed==0 且
          failure_reason 为空——「断言 AND 套件皆过」是**唯一**放行态
  exit 1  verdict 存在但非放行态（上述任一条件不成立：fail / valid!=True /
          failure_reason 非空 / failed!=0 / assertions_ok!=True）
  exit 2  verdict.json 不存在或不可读（视为未互验，fail-closed）
  exit 3  verdict 形状非法（缺契约字段 / 类型不对——拒绝解析而不是猜测）

N252（2026-10-05，high）：修前 :73 的放行判据只查 verdict/valid **两项**，把同一契约里
断言面与套件面的三字段（assertions_ok / failed / failure_reason）整体丢掉，于是生产端
公开 API `md_cg/interop.py` 的 `make_verdict(verdict='pass', failed=1)` 经 sanity+shape
双门禁正常产出 `verdict=pass / valid=True / assertions_ok=False /
failure_reason='assertions_failed' / failed=1` 后**被放行**（stdout 自己打印着 failed=1）
——§7.4「门禁 FAIL 一律不得合并」在断言面整体失守；`_load` 又漏了 verdict 的类型闸，
`verdict=123` 落到 exit 1 而非本 docstring 承诺的「形状非法」3。放行判据现由
release_blockers() 单点给出（逐条列阻因，不再只报一句结论）。

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
    # N252：verdict 的**类型闸**。修前只判枚举外的值落到 exit 1，于是 `verdict=123`
    # （类型不对）与本 docstring「形状非法=3」相反——「读不通」被伪装成「语义判负」。
    if not isinstance(v.get("verdict"), str):
        raise ValueError(
            f"verdict 须为字符串（实得 {v.get('verdict')!r}）——拒绝解析")
    # failure_reason 同属形状面：契约取值是 None 或字符串（产出端
    # md_cg/interop.shape_check_verdict 另做枚举白名单），此处只拒类型。
    _fr = v.get("failure_reason")
    if _fr is not None and not isinstance(_fr, str):
        raise ValueError(
            f"failure_reason 须为字符串或 null（实得 {_fr!r}）——拒绝解析")
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


def release_blockers(v: dict) -> list:
    """非放行态成因 → 列表（空列表 = 唯一放行态）。**放行判据的唯一单点**（N252）。

    放行态与 docstring :9-11 逐字对应，即契约里「断言 AND 套件皆过」的全合取：
    `verdict == "pass"` 且 `valid is True` 且 `assertions_ok is True` 且 `failed == 0`
    且 `failure_reason` 为空。修前只取前两项，断言面/套件面三字段被丢掉——生产端
    `make_verdict(verdict='pass', failed=1)` 的产出即可被放行（见模块 docstring N252 注）。
    逐条成因而非一句结论：门禁的消费方是合并钩子，需要知道**哪一面**没过。
    """
    blockers = []
    if v["verdict"] != "pass":
        blockers.append("verdict 非 pass（实得 %r）" % (v["verdict"],))
    if v["valid"] is not True:
        blockers.append("valid 非 True（实得 %r）" % (v["valid"],))
    if v["assertions_ok"] is not True:
        blockers.append("assertions_ok 非 True（实得 %r）" % (v["assertions_ok"],))
    if v["failed"] != 0:
        blockers.append("failed 非 0（实得 %r）" % (v["failed"],))
    if v["failure_reason"]:
        blockers.append("failure_reason 非空（实得 %r）" % (v["failure_reason"],))
    return blockers


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
    blockers = release_blockers(v)
    if not blockers:
        print(f"[interop_gate] PASS: {path} verdict=pass valid=true "
              f"assertions_ok=true passed={v['passed']} failed={v['failed']}")
        return 0
    print(f"[interop_gate] FAIL: verdict={v['verdict']!r} "
          f"valid={v['valid']!r} assertions_ok={v['assertions_ok']!r} "
          f"failure_reason={v['failure_reason']!r} "
          f"passed={v['passed']} failed={v['failed']} —— 不得合并（§7.4）")
    for b in blockers:
        print(f"  [阻因] {b}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
