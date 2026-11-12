# -*- coding: utf-8 -*-
"""issue #676 守卫：session_tasks / list_tasks 必须先按索引筛，再读盘。"""
from __future__ import annotations

import tempfile

from . import tasks
from .mdcos import MdCGOS


def _build(n_knowledge=30):
    cg = MdCGOS(tempfile.mkdtemp(prefix="f676_"))
    for i in range(n_knowledge):
        cg.add("k_%d" % i, "# 功能名：知识%d\n# 执行：乙" % i,
               layer="knowledge", importance=0.6, verification_basis="test")
    tasks.upsert(cg, "进行中的任务", plan="甲", status="active", actor="t")
    tasks.upsert(cg, "已完成的任务", plan="乙", status="done", result="丙", actor="t")
    cg.flush()
    return cg


def _count_reads(cg, fn):
    calls = {"n": 0}
    orig = cg.get

    def counting(nid, *a, **kw):
        calls["n"] += 1
        return orig(nid, *a, **kw)

    cg.get = counting
    try:
        out = fn()
    finally:
        cg.get = orig
    return out, calls["n"]


def main():
    ok = bad = 0

    def chk(cond, label, extra=""):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("  PASS", label)
        else:
            bad += 1
            print("  FAIL", label, extra)

    cg = _build(30)
    out, reads = _count_reads(cg, lambda: tasks.session_tasks(cg))
    chk(out["active_total"] == 1 and out["done_total"] == 1,
        "#676 结果正确（1 active / 1 done）", str(out)[:120])
    chk(reads == 2, "#676 只读任务卡：读盘次数 == 2（修复前为 32）", "实际 %d" % reads)

    out2, reads2 = _count_reads(cg, lambda: tasks.list_tasks(cg))
    chk(out2["total"] == 2, "#676 list_tasks 结果不变", str(out2.get("total")))
    chk(reads2 == 2, "#676 list_tasks 同样只读任务卡", "实际 %d" % reads2)

    # 阴性对照：索引缺 layer/tags 键（旧索引 / 异常条目）时必须退回读盘，不得漏任务
    idx = cg.index.get("nodes") or {}
    for e in list(idx.values()):   # H-4(a)：先取快照再迭代
        e.pop("layer", None)
        e.pop("tags", None)
    out3, reads3 = _count_reads(cg, lambda: tasks.session_tasks(cg))
    chk(out3["active_total"] == 1 and out3["done_total"] == 1,
        "#676 索引缺键时仍能发现任务卡（fail-open，不因优化漏读）", str(out3)[:120])
    chk(reads3 > 2, "#676 缺键路径确实退回读盘（判别力自证）", "实际 %d" % reads3)

    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
