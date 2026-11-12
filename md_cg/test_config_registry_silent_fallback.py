# -*- coding: utf-8 -*-
# 功能名：配置登记「潜在静默回落」的可观测性守卫（F26-17 主体·前半）
# 生效条件：python -X utf8 -m md_cg.test_config_registry_silent_fallback；被测面＝config_registry.entry_from_row 的两条回落路径（literal_eval 失败 / value_type 缺失）
# 子功能：①当前数据基线（两处均 0 命中，说明是防御性缺口而非活跃缺陷）②literal_eval 失败必须被 literal_failures() 记到 ③value_type 缺失必须被 missing_value_types() 记到 ④两者都**不得改变既有行为**（值原样保留、value_type 仍回落 str）
# 执行：直接构造 ROW_FIELDS 元组喂 entry_from_row，断言留痕 + 断言行为不变
# 验证方式：全部 PASS exit 0，否则 exit 1
# 不适用条件：不判 value_type 应当推断成什么（那是下一步「按值推断」，会动 427 条登记、需单独评估对 config_registry_guard 的影响）
"""F26-17 前半：把「潜在静默」变成可观测，且不改变任何既有行为。

病灶（`md_cg/config_registry.py::entry_from_row`）：
  · `val = ast.literal_eval(d["value_repr"])` 失败时**原样保留字符串**，无任何痕迹；
  · `"value_type": d.get("value_type") or "str"` —— 缺失时静默回落成 str，
    一个**数值型**登记会被当成字符串。

实测基线：当前 317 条登记里两处都是 **0 命中** ⇒ 属防御性缺口（陷阱存在但未触发），
故本轮只加可观测、不改行为；「按值推断 value_type」留作下一步。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import config_registry as cr  # noqa: E402
from md_cg.config_registry_bulk import ROW_FIELDS  # noqa: E402

_PASS, _FAIL = [], []


def ok(cond, msg, detail=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg + (("  <- " + str(detail)) if detail and not cond else ""))


def _row(**over):
    base = {f: "" for f in ROW_FIELDS}
    base.update({"name": "PROBE_X", "face": "TUNE", "layer": "L0", "kind": "const",
                 "tunable": False, "value_repr": "1", "value_type": "int",
                 "anchor_how": "const_assign", "anchor_file": "x.py",
                 "anchor_symbol": "X", "status": "uncalibrated", "evidence": "",
                 "since": "test", "notes": ""})
    base.update(over)
    return tuple(base[f] for f in ROW_FIELDS)


def main():
    print("== A 当前数据基线（防御性缺口：陷阱在、未触发）")
    rows = cr.entries()
    ok(len(rows) > 200, "A1 registry 条目数正常（>200）", len(rows))
    ok(cr.literal_failures() == [],
       "A2 当前无 literal_eval 失败项", cr.literal_failures()[:3])
    ok(cr.missing_value_types() == [],
       "A3 当前无 value_type 缺失项", cr.missing_value_types()[:3])
    ok(all(r.get("value_type") for r in rows), "A4 无条目 value_type 为空")

    print("== B literal_eval 失败必须留痕（判别力自证）")
    before = len(cr.literal_failures())
    e = cr.entry_from_row(_row(name="PROBE_BAD", value_repr="not-a-literal("))
    after = cr.literal_failures()
    ok(len(after) == before + 1, "B1 失败项被记到（+1）", (before, len(after)))
    ok(any(n == "PROBE_BAD" for n, _v in after), "B2 记的是该条名字")
    ok(e["value"] == "not-a-literal(", "B3 **行为不变**：值原样保留", e["value"])
    ok(e["value_type"] == "int", "B4 **行为不变**：value_type 仍取行内声明", e["value_type"])

    print("== C value_type 缺失必须留痕（判别力自证）")
    before2 = len(cr.missing_value_types())
    e2 = cr.entry_from_row(_row(name="PROBE_NOVT", value_type="", value_repr="42"))
    after2 = cr.missing_value_types()
    ok(len(after2) == before2 + 1, "C1 缺失项被记到（+1）", (before2, len(after2)))
    ok(any(n == "PROBE_NOVT" for n, _v in after2), "C2 记的是该条名字")
    ok(e2["value_type"] == "str", "C3 **行为不变**：仍回落 str（不擅自改成推断值）", e2["value_type"])
    ok(e2["value"] == 42, "C4 值仍被正确解析", e2["value"])

    print("== D 正常行不得被误记")
    n_lit, n_vt = len(cr.literal_failures()), len(cr.missing_value_types())
    e3 = cr.entry_from_row(_row(name="PROBE_OK", value_repr="[1, 2]", value_type="list"))
    ok(len(cr.literal_failures()) == n_lit, "D1 正常行不进 literal 失败表")
    ok(len(cr.missing_value_types()) == n_vt, "D2 正常行不进 value_type 缺失表")
    ok(e3["value"] == [1, 2] and e3["value_type"] == "list", "D3 正常行字段正确")

    print()
    print("配置登记静默回落守卫：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("  -", f)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())