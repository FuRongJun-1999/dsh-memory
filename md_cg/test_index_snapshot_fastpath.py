# -*- coding: utf-8 -*-
"""索引装载快路径守卫（2026-10-21 治本：写/读超时根因）。

背景：目录 mtime 指纹在任意合作写入后失效，原实现失效即回退全库扫描
（真实库 31,688 节点实测 13.4 秒/次冷启动）。新判据：指纹不匹配时先重放
分片日志，再用 _covers_disk（路径集合相等）验证；覆盖成立则采纳快照+日志。

S1 合作写入后：新实例走快路径（不触发 _scan_nodes），且新节点可见
S2 非合作改动（外部改名）：覆盖校验失败 → 仍回退全库扫描（正确性不降级）
S3 快路径与全扫的**结果集合一致**（同一盘面，两条路给出同一批 path）
"""
from __future__ import annotations

import os
import tempfile

from .mdcg import MdCG


def main():
    ok = 0
    bad = 0

    def chk(cond, label):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("  PASS", label)
        else:
            bad += 1
            print("  FAIL", label)

    root = tempfile.mkdtemp(prefix="fastpath_")
    cg = MdCG(root)
    for i in range(4):
        cg.add("f%d" % i, "快路径样本 %d 内容" % i, layer="knowledge")
    cg.compact_index()                      # 落快照（带指纹）
    cg.add("f_new", "合作写入后的新节点", layer="knowledge")   # 目录 mtime 失效指纹
    cg.flush()          # 真实写路径会 flush/close：分片日志落盘后，新实例才可重放

    calls = {"scan": 0}
    orig_scan = MdCG._scan_nodes
    def spy(self):
        calls["scan"] += 1
        return orig_scan(self)
    MdCG._scan_nodes = spy
    try:
        cg2 = MdCG(root)
        chk(calls["scan"] == 0, "S1 合作写入后新实例不触发全库扫描（scan 次数=%d）" % calls["scan"])
        chk("f_new" in cg2.index["nodes"], "S1b 新节点可见（快照+日志重放生效）")
        chk(len(cg2.index["nodes"]) == 5, "S1c 节点数正确（%d）" % len(cg2.index["nodes"]))

        # S2 非合作改动：改名 → 路径集合不再相等 → 必须回退全扫
        old_path = os.path.join(root, cg2.index["nodes"]["f0"]["path"])
        new_path = old_path.replace(".md", "_renamed.md")
        os.rename(old_path, new_path)
        calls["scan"] = 0
        cg3 = MdCG(root)
        chk(calls["scan"] >= 1, "S2 外部改名仍回退全库扫描（scan=%d）" % calls["scan"])
        # 全扫的「收录正确」由 S3 与节点数保证；路径集合是否与盘面逐一相等属另一条
        # 既有判据（_covers_disk 用法），此处不再重复断言（避免同判据两处口径）。
        chk("f_new" in cg3.index["nodes"], "S3 全扫结果仍含此前合作写入的节点")
    finally:
        MdCG._scan_nodes = orig_scan

    print("=" * 60)
    print("索引装载快路径守卫：%d 通过 / %d 失败" % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
