#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""索引快照自动落盘守卫（issue：add→close 永不写快照，重开付全库扫描+重放）。

缺陷形态（缺陷报告实测）：flush 只 append 分片日志、compact_index 生产零
调用、close/atexit 只 flush——「add→close」的库永远没有快照，每次重开
_load_index 都 _scan_nodes 全库逐文件 open+frontmatter 解析（1500 池本机
~104ms），随后无条件重放全部索引日志（在扫描基底上纯冗余）。

本守卫断言（调用计数/存在性形态，非时间阈值）：
  C1 close 落快照：add→close 后 _index.json 存在（旧代码恒不存在 → 红）；
  C2 重开零全库扫描：close 后重开期间 _scan_nodes 调用 == 0（旧代码
     每次重开 1 次全库扫描 → 红）；
  C3 重开零日志重放：close 后重开期间 ShardedLog.read_all 产出条数 == 0
     （旧代码重放全部增量日志 → 红）；
  C4 节点集一致：close→重开后 index["nodes"] 的 id 集与关闭前一致；
  C5 尾部写入不丢：未达 autoflush 阈值的尾部 add 在 close 后重开可见；
  C6 快照损坏防御：_index.json 写坏后 close/compact 不产出空快照——
     节点仍全量可见（旧 compact 拿空骨架+增量日志会写出清池快照 → 红）；
  C7 空库不落快照：无节点时 close 不产生 _index.json（保持原行为）。
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import md_cg.mdcg as mdcg_mod               # noqa: E402
from md_cg.fsutil import ShardedLog         # noqa: E402
from md_cg.mdcos import MdCGOS              # noqa: E402

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")


def count_reload_reads(fn):
    """打桩 _scan_nodes 调用数与 ShardedLog.read_all 产出条数。"""
    n_scan, n_replay = 0, 0
    real_scan = mdcg_mod.MdCG._scan_nodes
    real_read = ShardedLog.read_all

    def _scan_spy(self):
        nonlocal n_scan
        n_scan += 1
        return real_scan(self)

    def _read_spy(path, *a, **kw):
        nonlocal n_replay
        out = list(real_read(path, *a, **kw))
        n_replay += len(out)
        return iter(out)

    mdcg_mod.MdCG._scan_nodes = _scan_spy
    ShardedLog.read_all = staticmethod(_read_spy)
    mdcg_mod.ShardedLog.read_all = staticmethod(_read_spy)
    try:
        return fn(), n_scan, n_replay
    finally:
        mdcg_mod.MdCG._scan_nodes = real_scan
        ShardedLog.read_all = real_read
        mdcg_mod.ShardedLog.read_all = real_read


def build(root, n=30):
    cg = MdCGOS(root, autoflush=64)          # 高阈值：尾部写入留在 _dirty
    for i in range(n):
        cg.add("mem_%04d" % i,
               "# 功能名：快照守卫 %d\n# 正文：蜂群调度 样本 %d" % (i, i),
               layer="knowledge")
    return cg


def main():
    root = tempfile.mkdtemp(prefix="mdcg_snap_guard_")
    try:
        # C1/C4/C5：close 落快照 + 尾部写入 + 节点集一致
        print("== C1/C4/C5 close 落快照 ==")
        cg = build(root)
        ids_before = set(cg.index["nodes"])
        check("C5pre 尾部写入在 _dirty（未 flush）", len(cg._dirty) > 0,
              f"dirty={len(cg._dirty)}")
        cg.close()
        snap = os.path.join(root, "_index.json")
        check("C1a add→close 后 _index.json 快照存在（旧代码恒不存在）",
              os.path.exists(snap))

        def _reopen():
            return MdCGOS(root)

        cg2, n_scan, n_replay = count_reload_reads(_reopen)
        try:
            ids_after = set(cg2.index["nodes"])
            check("C4a 重开后节点集与关闭前一致",
                  ids_after == ids_before and len(ids_after) == 30,
                  f"before={len(ids_before)} after={len(ids_after)}")
        finally:
            cg2.close()
        check("C2a 重开零全库扫描（_scan_nodes 调用==0，旧每次重开 1 次）",
              n_scan == 0, f"scans={n_scan}")
        check("C3a 重开零日志重放（read_all 条数==0，旧全量重放）",
              n_replay == 0, f"replayed={n_replay}")

        # C6 快照损坏防御：写坏快照 → 重开（scan 基底）→ close 不产空快照
        print("== C6 快照损坏防御 ==")
        with open(snap, "w", encoding="utf-8") as f:
            f.write("{corrupted json !!!")
        root6 = root                            # 同库继续
        cg6 = MdCGOS(root6)                      # 损坏 → _scan_nodes 基底
        n6 = len(cg6.index["nodes"])
        check("C6a 损坏快照下重开走全库扫描（节点全量可见）",
              n6 == 30, f"nodes={n6}")
        cg6.close()
        cg6b = MdCGOS(root6)
        try:
            n6b = len(cg6b.index["nodes"])
            check("C6b 损坏后 close/compact 不产空快照（重开仍 30 节点）",
                  n6b == 30, f"nodes={n6b}")
        finally:
            cg6b.close()

        # C8 未 flush 写入兜底（issue #33 修复中发现的回归形态）：实例 A
        # 写节点不收尾（dirty 未 flush、文件已落盘），实例 B close 落快照
        # ——B 的账本不含 A 的节点。此后重开必须仍能看到 A 的节点
        # （compact 计数对账 + 重开指纹校验双保险；任一缺失都会让节点
        # 「在盘上但索引不可见」）。
        print("== C8 未 flush 写入兜底 ==")
        root8 = tempfile.mkdtemp(prefix="mdcg_snap_guard8_")
        try:
            a = MdCGOS(root8, autoflush=64)
            a.add("a1", "# 功能名：甲\n# 正文：甲的节点 蜂群", layer="knowledge")
            a.add("a2", "# 功能名：乙\n# 正文：乙的节点 星云", layer="knowledge")
            b = MdCGOS(root8, autoflush=64)
            b.add("b1", "# 功能名：丙\n# 正文：丙的节点 水位", layer="knowledge")
            b.close()                       # B 落快照（账本不含 a1/a2）
            c = MdCGOS(root8)
            try:
                ids_c = set(c.index["nodes"])
                check("C8a A 未 flush 的节点在 B close 落快照后重开仍可见",
                      {"a1", "a2", "b1"} <= ids_c, f"ids={sorted(ids_c)}")
            finally:
                c.close()
            d = MdCGOS(root8)
            try:
                ids_d = set(d.index["nodes"])
                check("C8b C close 后再次重开节点仍全量可见（快照已含全部）",
                      {"a1", "a2", "b1"} <= ids_d, f"ids={sorted(ids_d)}")
            finally:
                d.close()
        finally:
            shutil.rmtree(root8, ignore_errors=True)

        # C7 空库不落快照
        print("== C7 空库不落快照 ==")
        root7 = tempfile.mkdtemp(prefix="mdcg_snap_guard7_")
        try:
            cg7 = MdCGOS(root7)
            cg7.close()
            check("C7a 空库 close 不产生 _index.json（保持原行为）",
                  not os.path.exists(os.path.join(root7, "_index.json")))
        finally:
            shutil.rmtree(root7, ignore_errors=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 60)
    print(f"结果：PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
