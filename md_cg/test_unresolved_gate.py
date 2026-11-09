# -*- coding: utf-8 -*-
"""G 未解源头闸：检索无果自动登记默认关闭 + 问句可答性闸。

功能名：test_unresolved_gate —— unresolved.note_miss 源头守卫（隔离临时库）。
生效条件：`PYTHONPATH=<root> python -m md_cg.test_unresolved_gate`。
子功能：断言面——
  A1 MISS_ENABLED=False（缺省）→ skipped=disabled，零落盘；
  A2 打开开关 + 碎片问句（「记忆 检索 缺陷」）→ skipped=not_answerable，零落盘；
  A3 打开开关 + 带疑问词的真问题 → 落盘 1 条，层=unresolved；
  A4 同一问题第二次 → created=False（幂等，不重复写）；
  A5 打开开关 + 无疑问词但足够长（>=16 字）→ 落盘（宽进，只是不收回显式长问句）；
  A6 开关打开但问题为空 → skipped=empty。
执行：`python -m md_cg.test_unresolved_gate`。
验证方式：test。
不适用条件：活库（一切读写都在 tempfile.mkdtemp 内）。
"""
from __future__ import annotations

import shutil
import sys
import tempfile

from . import unresolved
from .mdcos import MdCGOS

PASS = 0
FAIL = 0
FAILS = []


def _ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS", label)
    else:
        FAIL += 1
        FAILS.append(label)
        print("  FAIL", label)


def _n_unresolved(cg):
    nodes = (cg.index or {}).get("nodes") or {}
    return sum(1 for v in nodes.values() if v.get("layer") == "unresolved")


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_unresolved_gate_")
    real = unresolved.MISS_ENABLED
    try:
        cg = MdCGOS(tmp)
        print("[A1] 缺省关闭")
        unresolved.MISS_ENABLED = False
        r = unresolved.note_miss(cg, "为什么记忆检索总是零命中")
        _ok(r.get("skipped") == "disabled", "skipped=disabled（%r）" % (r,))
        _ok(_n_unresolved(cg) == 0, "零落盘")

        print("[A2] 碎片问句被闸掉")
        unresolved.MISS_ENABLED = True
        r = unresolved.note_miss(cg, "记忆 检索 缺陷")
        _ok(r.get("skipped") == "not_answerable", "skipped=not_answerable（%r）" % (r,))
        _ok(_n_unresolved(cg) == 0, "仍零落盘")

        print("[A3/A4] 真问题落盘且幂等")
        q = "我以前说过路由器怎么设置吗"
        r = unresolved.note_miss(cg, q)
        _ok(r.get("ok") is True and r.get("created") is True, "created=True")
        _ok(_n_unresolved(cg) == 1, "落盘 1 条")
        node = cg.get(r["id"], probe=True) or {}
        _ok((node.get("frontmatter") or {}).get("layer") == "unresolved", "层=unresolved")
        r2 = unresolved.note_miss(cg, q)
        _ok(r2.get("created") is False, "第二次 created=False")
        _ok(_n_unresolved(cg) == 1, "不重复写")

        print("[A5/A6] 长问句放行 / 空串拒绝")
        r3 = unresolved.note_miss(cg, "主库记忆投影写入路径在哪一层负责落盘与索引重建")
        _ok(r3.get("created") is True, "长问句落盘")
        r4 = unresolved.note_miss(cg, "")
        _ok(r4.get("skipped") == "empty", "空串 skipped=empty")
    finally:
        unresolved.MISS_ENABLED = real
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n=== test_unresolved_gate: PASS %d / FAIL %d ===" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
