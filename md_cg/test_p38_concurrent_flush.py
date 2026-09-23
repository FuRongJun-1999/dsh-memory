# -*- coding: utf-8 -*-
"""批次9：9·12 多写者病灶防线能红测试——flush 与 compact 的临界区互斥。

确定性时序复刻（不靠概率压测）：mock ShardedLog.read_all 在读完日志后
sleep 放大「A 已读、尚未 clear」的竞态窗口；窗口内让实例 B flush（append）。
· 防线缺失（flush 无锁）：B 的记录随 A 的 clear 被删 → 本测试红；
· 防线在场（flush 持 index_path 锁）：B 的 append 等 A 出锁 → 记录存活 → 绿。
运行：python -m md_cg.test_p38_concurrent_flush  （退出码 0 = 全绿）
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg.fsutil import ShardedLog
from md_cg.mdcg import MdCG

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [ok] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def main():
    root = tempfile.mkdtemp(prefix="mdcg_b9_")
    try:
        print("[1] flush × compact 竞态确定性复刻（9·12 防线）")
        cg_a = MdCG(root)
        cg_b = MdCG(root)
        cg_a.add("seed_1", "种子节点", verification_basis="data")
        cg_a.flush()

        orig_read_all = ShardedLog.read_all
        gate = threading.Event()

        def slow_read_all(directory):
            recs = orig_read_all(directory)
            # A 已读完日志、尚未 clear——放大竞态窗口，放行 B 的 append
            gate.set()
            time.sleep(0.15)
            return recs

        appended = threading.Event()

        def writer_b():
            try:
                gate.wait(5)
                cg_b.add("b9_probe", "并发实例写入（防线必须保住我）",
                         verification_basis="data")
                cg_b.flush()
                appended.set()
            except Exception as exc:   # noqa: BLE001 —— 调试可见性
                print(f"  [debug] writer_b 异常: {type(exc).__name__}: {exc}")
                appended.set()

        with mock.patch.object(ShardedLog, "read_all",
                               staticmethod(slow_read_all)):
            t = threading.Thread(target=writer_b)
            t.start()
            cg_a.compact_index()          # A：read_all（窗口）→ clear 分片
            t.join(10)
        appended.wait(1)

        # 盘面终态：重开一个新实例（等价 compact 后重放），b9_probe 必须可见
        cg_c = MdCG(root)
        have = "b9_probe" in cg_c.index["nodes"]
        check("1a 并发实例的 flush 记录在 compact 后存活（9·12 防线）",
              have, f"nodes={sorted(cg_c.index['nodes'])[:6]}")
        # 修复语义核对：B 的记录若被 clear 吃掉，只能靠重建 .md 扫描偶然救回——
        # 索引可见性丢失即病灶本体，不.accept「盘上有文件但不可见」。
        check("1b 索引可见性零丢失（拒绝『在盘但不可见』）",
              have and cg_c.index["nodes"]["b9_probe"].get("bucket") is not None)

        print("[2] compact 互斥不破坏既有语义")
        cg_a.add("seed_2", "第二条", verification_basis="data")
        cg_a.flush()
        cg_a.compact_index()
        cg_c2 = MdCG(root)
        check("2a compact 后种子与并发写入全部可见",
              {"seed_1", "seed_2", "b9_probe"} <= set(cg_c2.index["nodes"]),
              str(sorted(cg_c2.index['nodes'])))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n=== concurrent flush tests: {PASS} passed, {FAIL} failed ===")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
