# -*- coding: utf-8 -*-
"""reconcile 修复动作的并发守卫（R-543，2026-11-10）。

缺陷（审计 P2 生命周期）：`reconcile_state(apply=True)` 的修复段**不持任何锁**——
diff 在锁外算完就逐个 `_unstage` / `_stage`。而它跑在后台线程里
（`mcp_server._reconcile_bg`），同一进程的 stdin 请求线程同时在写节点：两个写者
共用 `cg.index` / `cg._dirty` 却无互斥，于是「并发 reconcile + write 索引错乱」
可复现——对账拿锁外快照把**刚写进来的节点**当幽灵摘掉。

修法：逐节点取 `fsutil.node_write_lock`（与写路径同一把 OS 级锁、同 id 同锁），
并在锁内**重新确认**盘面/索引现状，只对仍然成立的那部分动手。

契约（本文件即其守卫）：

  【1】锁外快照说「文件没了」但锁内盘面其实在（= 并发写者刚写回）⇒ **不摘条目**。
  【2】每条被修复的节点都真的走过 `node_write_lock`（锁在路径上，不是注释）。
  【3】真实的漂移/缺失仍照常修复（收紧复核不得把正常修复也挡掉）。
  【4】`apply=False`（dry-run）不取锁、不写盘。

运行：python -m md_cg.test_reconcile_lock
"""
from __future__ import annotations

import os
import shutil
import tempfile

from . import fsutil, nodefile, reconcile
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


def _mk(root, nid):
    os.makedirs(os.path.join(root, "knowledge"), exist_ok=True)
    p = os.path.join(root, "knowledge", nid + ".md")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(nodefile.dumps({"id": nid, "layer": "knowledge",
                                "modality": "text", "importance": 0.5,
                                "confidence": 0.6, "tags": []},
                               "# 功能名：%s\n\n正文。\n" % nid))
    return p


def main():
    tmp = tempfile.mkdtemp(prefix="reclock_")
    try:
        root = os.path.join(tmp, "lib")
        _mk(root, "rx1")
        _mk(root, "rx2")
        cg = MdCGOS(root)
        cg.rebuild_index()
        ok(set(cg.index["nodes"]) == {"rx1", "rx2"}, "G0 前提：两个节点已入索引")

        # ---------- 【1】锁外快照过时（说文件没了），锁内盘面其实在 ----------
        real_scan = reconcile._scan_disk
        reconcile._scan_disk = lambda _cg: ({}, {}, [])
        try:
            rep = reconcile.reconcile_state(cg, apply=True)
        finally:
            reconcile._scan_disk = real_scan
        ok(sorted(rep["ghost_entries"]) == ["rx1", "rx2"], "G1a 快照把两节点都当幽灵")
        ok(rep["repaired"]["unstaged"] == 0,
           "G1b 锁内复核后**一个都没摘**（并发写者刚写回的节点不被误摘）")
        ok(set(cg.index["nodes"]) == {"rx1", "rx2"},
           "G1c 索引面完好（修前：两条都被摘掉 ⇒ 索引错乱）")

        # ---------- 【2】锁真的在路径上 ----------
        hits = []
        real_lock = fsutil.node_write_lock

        def _spy(cg_, nid, timeout=30.0):
            hits.append(nid)
            return real_lock(cg_, nid, timeout)

        fsutil.node_write_lock = _spy
        try:
            os.remove(os.path.join(root, "knowledge", "rx1.md"))   # 真幽灵
            # 不 rebuild_index：内存索引仍持 rx1 ⇒ 盘面无文件 = 真幽灵（生产同形态：
            # 文件被外部删掉，索引快照里还有它）
            rep = reconcile.reconcile_state(cg, apply=True)
        finally:
            fsutil.node_write_lock = real_lock
        ok(rep["ghost_entries"] == ["rx1"], "G2a 真幽灵被识别")
        ok(rep["repaired"]["unstaged"] == 1, "G2b 真幽灵被摘除")
        ok("rx1" in hits, "G2c 摘除动作走过 node_write_lock（%s）" % hits)

        # ---------- 【3】真实漂移仍照常修复 ----------
        p2 = os.path.join(root, "knowledge", "rx2.md")
        with open(p2, "w", encoding="utf-8", newline="\n") as f:
            f.write(nodefile.dumps({"id": "rx2", "layer": "knowledge",
                                    "modality": "text", "importance": 0.7,
                                    "confidence": 0.6, "tags": []},
                                   "# 功能名：rx2\n\n正文改过了。\n"))
        rep = reconcile.reconcile_state(cg, apply=True)
        ok(rep["hash_drift"] == ["rx2"], "G3a 哈希漂移被识别")
        ok(rep["repaired"]["staged"] == 1, "G3b 漂移条目按盘面重装（复核未挡正常修复）")
        ok(reconcile.reconcile_state(cg, apply=True)["repaired"]["staged"] == 0,
           "G3c 二次对账幂等（修复后 diff 为空）")

        # ---------- 【4】dry-run 不取锁 ----------
        hits2 = []
        fsutil.node_write_lock = lambda cg_, nid, timeout=30.0: hits2.append(nid)
        try:
            os.remove(os.path.join(root, "knowledge", "rx2.md"))
            cg.rebuild_index()
            rep = reconcile.reconcile_state(cg, apply=False)
        finally:
            fsutil.node_write_lock = real_lock
        ok(rep["applied"] is False and rep["repaired"]["unstaged"] == 0,
           "G4a dry-run 不修复")
        ok(hits2 == [], "G4b dry-run 不取锁（零写盘）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\ntest_reconcile_lock: %d 通过 / %d 失败" % (PASSED, FAILED))
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
