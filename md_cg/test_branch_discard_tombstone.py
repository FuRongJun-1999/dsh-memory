# -*- coding: utf-8 -*-
"""branches.discard 摘索引落 tombstone 守卫（缺陷：只 pop 内存 → 幽灵条目固化）。

缺陷形态（缺陷报告 2026-09-25 复现证实，medium）：discard()（branches.py:261）
摘除分支索引条目只 `pop` 内存、不写删除记录（未走 `_unstage`），且其内部
flush（:262-267）把 fork 阶段仍在 `_dirty` 的分支条目作为 **upsert** 持久化进
`_index_log`。close 时 compact 的「计数对账重扫 + 日志重放」（mdcg.py:1010-1012
`_apply_log(self._scan_nodes())`）把已物理移走（publish 至 `_branches/<id>/`，
LAYERS 之外）的分支 upsert **叠回**干净扫描之上——幽灵条目连同目录指纹一起固化
进 `_index.json` 快照，此后重开指纹校验放行、幽灵永久存活（get()=None、
检索候选白跑、dangling 不归零）。

修复口径（forget 的正确模式，mdcos.py:2244-2246 注释明载同构坑）：discard
摘除分支条目走 `_unstage(nid)`——pop 内存 + `_dirty[nid]=None`（tombstone）
+ 立即 flush，重放时按序 pop 掉 fork upsert。

红守卫 = 缺陷报告复现流程：S1 主支落快照 → S2 fork+discard → S3 close 重开
断言索引不含 `mem_base@br1` 幽灵条目。B1/B4/B5 锁 discard 既有语义不变
（返回形态 / 教训节点存活 / 主支完好），B2/B3/B6 为红项。
运行：python -m md_cg.test_branch_discard_tombstone
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

from . import branches
from .fsutil import ShardedLog
from .mdcg import LAYERS
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []

BID = "br1"
GHOST = "mem_base@br1"
SUMMARY = "branch_summary_br1"
SUMMARY_TEXT = "分支假设：改写可提检索命中 实验结果：无提升 教训：回归再上分支"


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


def _layer_md_ids(root):
    """盘面真值：LAYERS 各层目录下现存 .md 的节点 id 集合（含子桶）。"""
    ids = set()
    for layer in LAYERS:
        base = os.path.join(root, layer)
        for _dp, _dirs, files in os.walk(base):
            for fn in files:
                if fn.endswith(".md"):
                    ids.add(fn[:-3])
    return ids


def main():
    os.environ.pop("MDCG_READ_CACHE", None)
    tmp = tempfile.mkdtemp(prefix="mdcg_br_tomb_")
    try:
        root = os.path.join(tmp, "root")
        os.makedirs(root)

        # S1：主支节点入库并 close 落快照（此后 S2 的 close 走 compact 而非 rebuild）
        cg0 = MdCGOS(root)
        cg0.add("mem_base", "# 功能名：分支守卫主支\n\n正文：蜂群调度基线。\n",
                layer="knowledge")
        cg0.close()

        # S2：fork → discard（fork 后不 flush——fork 阶段条目仍在 _dirty）
        cg1 = MdCGOS(root)
        fr = branches.fork(cg1, ["mem_base"], branch_id=BID,
                           note="守卫：命中提升实验")
        ok(fr.get("ok") and fr["forked"][0]["to"] == GHOST,
           f"B0a fork 出分支副本 {GHOST}")
        r = branches.discard(cg1, BID, SUMMARY_TEXT)
        ok(r.get("ok") is True and r.get("moved") == 1
           and r.get("summary_node") == SUMMARY,
           f"B1 discard 语义不变（ok/moved/summary_node，实测 {r!r}）")

        # B2（机制，红项）：摘除必须落删除记录——discard 返回时 _index_log
        # 已含该 nid 的 tombstone（e is None），且 _dirty 中无待写 upsert
        recs = list(ShardedLog.read_all(cg1.index_log_dir))
        ok(any(x.get("id") == GHOST and x.get("e") is None for x in recs),
           f"B2 discard 已落 tombstone（日志含 {GHOST} 删除记录；实测"
           f" {[(x.get('id'), x.get('e') is None) for x in recs]}）")
        ok(GHOST not in cg1._dirty
           and GHOST not in cg1.index["nodes"],
           "B2b 内存索引已摘除且 _dirty 无该节点待写条目")
        cg1.close()

        # S3：重开——幽灵条目不得复活
        cg2 = MdCGOS(root)
        idx_ids = set((cg2.index.get("nodes") or {}).keys())
        ok(GHOST not in idx_ids,
           f"B3 重开后索引不含幽灵条目 {GHOST}（实测索引节点 "
           f"{sorted(idx_ids)}）")
        ok("mem_base" in idx_ids and SUMMARY in idx_ids,
           "B4 主支节点与教训节点存活（discard 其余语义不变）")
        disk_ids = _layer_md_ids(root)
        ok(idx_ids == disk_ids,
           f"B5 索引与盘面对账一致（索引 {sorted(idx_ids)} / 盘面 "
           f"{sorted(disk_ids)}）")
        ok(cg2.get(GHOST) is None and cg2.get("mem_base") is not None,
           "B6 幽灵不可取回、主支可正常读取")
        ok(cg2.get(SUMMARY) is not None
           and "教训" in (cg2.get(SUMMARY) or {}).get("content", ""),
           "B7 教训节点内容可读（可检索召回）")
        # 冷归档物理保留（不违背永不删除）
        cold = os.path.join(root, branches.COLD_DIR, BID,
                            GHOST + ".md")
        ok(os.path.isfile(cold), f"B8 分支文件冷归档保留（{cold}）")
        cg2.close()
    finally:
        os.environ.pop("MDCG_READ_CACHE", None)
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 60)
    print(f"结果：PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
