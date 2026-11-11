# -*- coding: utf-8 -*-
"""backfill 真批次守卫（R-542，2026-11-10）。

缺陷（审计 P2 生命周期）：`apply` / `cap_apply` / `exempt_apply` /
`fix_conditions_apply` 四个写入口的批次缺省一律回落**常量**
（`BATCH_DEFAULT="backfill"` / `FIX_BATCH_DEFAULT="cond_fix"`）⇒ 历次运行的留痕
`batch` 完全相同，`rollback(batch=…)` 实际只能「把历史上所有回填一起撤」，
「只撤一批」这件事**拿不到真实批次号**，判据也就无从成立。

修法：批次号由**运行时刻 + 进程内序号 + 随机尾**生成（`backfill.new_batch`），
四个写入口各自拿一个；显式传 `batch=` 的调用方行为不变。

契约（本文件即其守卫）：

  【1】不传 batch 的两次 apply ⇒ 留痕里是**两个不同的真批次号**（非常量）。
  【2】`rollback(batch=<第一批>)` 只撤第一批写的节点；第二批写的仍在。
  【3】`rollback(entry_ids=[<某一条>])` 只撤那一条。
  【4】显式 `batch="x"` 仍按 x 记账（不被打回随机号）。

运行：python -m md_cg.test_backfill_batch
"""
from __future__ import annotations

import io
import os
import re
import shutil
import tempfile

from . import backfill, nodefile
from .mdcos import MdCGOS

PASSED = FAILED = 0


def ok(cond, name):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print("  [PASS] " + name)
    else:
        FAILED += 1
        print("  [FAIL] " + name)


def _seed_node(root, nid):
    """直写一个「旧式」节点（绕开 add 的写时补齐）⇒ plan() 会把它列为可回填。"""
    os.makedirs(os.path.join(root, "knowledge"), exist_ok=True)
    fm = {
        "id": nid, "layer": "knowledge", "modality": "text",
        "importance": 0.5, "confidence": 0.6,
        "condition_space": {
            "observation_position": "本地文件系统（摄取器内部观测位）",
            "observation_tool": "扩展名映射表 + Ingestor",
            "time_window": [0.0, 9999999999.0],
            "existence_constraint": "仅对本地可读文件生效"},
        "tags": [], "created_at": 1000.0, "access_count": 0,
        "last_access": 0, "edges": [], "verification_basis": "test",
        "non_applicable_conditions": ["二进制文件"],
        "state_attributes": {"comment": {
            "子功能": "按扩展名路由到对应摄取器",
            "执行": "读后缀映射表→调用对应 Ingestor"}},
    }
    with io.open(os.path.join(root, "knowledge", nid + ".md"), "w",
                 encoding="utf-8", newline="\n") as f:
        f.write(nodefile.dumps(fm, "# 功能名：%s 的正文\n\n迁移入库。\n" % nid))


def _body(cg, nid):
    return cg._read(cg.index["nodes"][nid])[1]


def main():
    tmp = tempfile.mkdtemp(prefix="bfbatch_")
    try:
        root = os.path.join(tmp, "lib")
        _seed_node(root, "bf_a")
        _seed_node(root, "bf_b")
        cg = MdCGOS(root)
        cg.rebuild_index()

        print("[1] 两次 apply 的批次号必须不同")
        r1 = backfill.apply(cg, actor="t")
        b1 = r1["batch"]
        ok(r1["written"] == 2, "G1a 第一批写 2 个节点")
        ok(b1 != backfill.BATCH_DEFAULT, "G1b 批次号不是常量缺省（%s）" % b1)
        ok(re.match(r"^backfill-\d{8}T\d{6}Z-\d{2}[0-9a-f]{4}$", b1) is not None,
           "G1c 批次号形态 = 前缀-UTC时间-序号+随机尾")

        _seed_node(root, "bf_c")
        cg.rebuild_index()
        r2 = backfill.apply(cg, actor="t")
        b2 = r2["batch"]
        ok(r2["written"] == 1, "G2a 第二批写 1 个节点（bf_c）")
        ok(b2 != b1, "G2b 两批批次号不同（此前恒相同）")

        print("[2] rollback(batch=第一批) 只撤第一批")
        rb = backfill.rollback(cg, batch=b1, actor="t")
        ok(rb["reverted"] == 2, "G3a 只撤第一批的 2 条")
        ok("# 执行：" not in _body(cg, "bf_a"), "G3b bf_a 已还原")
        ok("# 执行：" in _body(cg, "bf_c"), "G3c bf_c（第二批）仍在 —— 按批回滚成立")

        print("[3] rollback(entry_ids=[…]) 只撤那一条")
        eid = r2["entry_ids"][0]
        rb2 = backfill.rollback(cg, entry_ids=[eid], actor="t")
        ok(rb2["reverted"] == 1, "G4a 只撤 1 条")
        ok("# 执行：" not in _body(cg, "bf_c"), "G4b 该条已还原")

        print("[4] 显式 batch 仍按显式值记账")
        _seed_node(root, "bf_d")
        cg.rebuild_index()
        r3 = backfill.apply(cg, batch="my-batch-1", actor="t")
        ok(r3["batch"] == "my-batch-1", "G5a 显式 batch 未被改写")
        h = backfill.history(cg, action="backfill", batch="my-batch-1")
        ok(h["total"] == r3["written"] and h["total"] >= 1,
           "G5b 留痕按显式批次查到且条数 == 本次写入数（%d）" % r3["written"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\ntest_backfill_batch: %d 通过 / %d 失败" % (PASSED, FAILED))
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
