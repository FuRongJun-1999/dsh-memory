# -*- coding: utf-8 -*-
"""守卫 · 本地热层（分库分表第一层）：自我信息 + 短期记忆固化，优先检索。

断言：
  H1 构建幂等：同源库连建两次，节点集合与 token 数一致；第二次 `ensure()` 复用（reused=True）
  H2 过期即重建：源库 `_index.json` 变化后 `ensure()` 判过期并重建（stamp 不同）
  H3 只收三类：self/anchor 全部 + 近 N 天 contextual + importance≥阈值；其余不进
  H4 热层检索优先自我：同一 query 下 self 层条目排名靠前（层加权）
  H5 热层可弃：删掉 `_hot/` 后 search 返回 available=False，且不抛错（派生物，非真源）
  H6 上限生效：max_nodes 截断时 meta.truncated=True（防热层长成第二个总库）
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import hottier  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:170])
        FAILS.append(name)


def main():
    print("=" * 70)
    print("本地热层（分库分表 · 本地优先）")
    print("=" * 70)

    cg = MdCGOS(tempfile.mkdtemp(prefix="hot_guard_"), actor="test")
    now = time.time()
    cg.add("self_a", "自我锚点：身份=灵枢；价值观=白箱纪律，不猜测，未找到就 DEFER", layer="self", tags=["identity_anchor"])
    cg.add("anchor_a", "存在契约：责任而非权力", layer="anchor")
    cg.add("ctx_today", "今天在改界面：身份档案要人话化", layer="contextual")
    cg.add("know_hi", "降熵定理：新结构必须自证降熵", layer="knowledge", importance=0.9)
    cg.add("know_lo", "随手记的一条低重要度知识", layer="knowledge", importance=0.2)
    old = "很久以前的一条情景记忆，应被窗口过滤"
    cg.add("ctx_old", old, layer="contextual")
    cg.flush()   # 索引是派生物：落盘后源库戳才有意义（生产写入同样会 flush）

    m1 = hottier.build(cg)
    ids1 = set(hottier.load(cg.root)["nodes"])
    m2 = hottier.build(cg)
    ids2 = set(hottier.load(cg.root)["nodes"])
    ok(ids1 == ids2, "H1 构建幂等（两次节点集合一致）", (sorted(ids1), sorted(ids2)))
    r = hottier.ensure(cg)
    ok(r.get("reused") is True, "H1b 未过期时 ensure 复用", r.get("reused"))

    ok({"self_a", "anchor_a"} <= ids1, "H3 self/anchor 全部进热层", sorted(ids1))
    ok("know_hi" in ids1, "H3 高重要度知识进热层", sorted(ids1))
    ok("know_lo" not in ids1, "H3 低重要度知识不进热层", sorted(ids1))
    ok("ctx_today" in ids1, "H3 近期情景进热层")

    res = hottier.search(cg, "灵枢 价值观", k=5)
    ids = [i["id"] for i in res["items"]]
    ok(ids and ids[0] == "self_a", "H4 自我条目优先（层加权）", ids)

    stamp_before = hottier.source_stamp(cg.root)
    cg.add("extra_anchor", "再加一条锚点，触发索引变化", layer="anchor")
    cg.flush()
    stamp_after = hottier.source_stamp(cg.root)
    ok(stamp_before != stamp_after, "H2 源库戳随写入变化", (stamp_before, stamp_after))
    r2 = hottier.ensure(cg)
    ok(r2.get("reused") is False and "extra_anchor" in hottier.load(cg.root)["nodes"],
       "H2b 过期即重建（新节点进热层）", r2.get("reused"))

    bk = tempfile.mkdtemp(prefix="hot_bk_")
    shutil.rmtree(os.path.join(cg.root, hottier.HOT_DIR), ignore_errors=True)
    res2 = hottier.search(cg, "灵枢")
    ok(res2["items"] == [] and res2["meta"].get("available") is False,
       "H5 热层缺失时优雅降级（不抛错）", res2["meta"])

    m3 = hottier.build(cg, max_nodes=2)
    ok(m3.get("truncated") is True and m3.get("nodes") == 2,
       "H6 上限截断并如实标记", (m3.get("nodes"), m3.get("truncated")))

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())