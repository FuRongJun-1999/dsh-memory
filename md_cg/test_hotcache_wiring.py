# -*- coding: utf-8 -*-
"""热缓存接线守卫（issue #614）。

H1 两次同参查询：第二次命中 query 缓存（query_hits >= 1）且结果逐条相同
H2 写后读不陈旧：写入新节点后同参再查，必须能看到新节点（_on_index_mutation 全清）
H3 参数不同不串味：k 变化 → 未命中（键覆盖 k）
"""
from __future__ import annotations

import os
import tempfile

from . import hotcache as HC
from .mdcos import MdCGSecure


def main():
    os.environ["MDCG_HOTCACHE"] = "1"
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

    root = tempfile.mkdtemp(prefix="hc_wire_")
    cg = MdCGSecure(root)
    for i in range(6):
        cg.add("n%d" % i, "灵枢 记忆库 条目 %d 号内容" % i, layer="knowledge")
    hc = HC.get(cg)
    chk(hc is not None, "H0 热缓存已挂载（默认开）")

    r1 = cg.search("灵枢 记忆库", k=5, record=False)
    s1 = hc.stats()
    r2 = cg.search("灵枢 记忆库", k=5, record=False)
    s2 = hc.stats()
    chk(s2["query_hits"] >= 1, "H1 第二次同参查询命中缓存（query_hits=%d）" % s2["query_hits"])
    ids1 = [x[0]["id"] for x in r1[0]]
    ids2 = [x[0]["id"] for x in r2[0]]
    chk(ids1 == ids2, "H1b 缓存命中与首次结果逐条相同")

    cg.add("n_new", "阿洛芬 是新增条目里的独特词", layer="knowledge")
    r3 = cg.search("阿洛芬", k=5, record=False)
    ids3 = [x[0]["id"] for x in r3[0]]
    chk("n_new" in ids3, "H2 写后读不陈旧：新节点可见（invalidations=%d）" % hc.stats()["invalidations"])
    chk(hc.stats()["invalidations"] >= 1, "H2b 写路径确实清了 query 缓存")

    before = hc.stats()["query_hits"]
    cg.search("灵枢 记忆库", k=3, record=False)
    chk(hc.stats()["query_hits"] == before, "H3 换 k 不串味（未命中）")
    # H4 环境开关翻动必须失效（键含 env_switch）——否则同一 query 会拿到旧口径结果
    os.environ["MDCG_SEMANTIC"] = "0"
    r4 = cg.search("灵枢 记忆库", k=5, record=False)
    before4 = hc.stats()["query_hits"]
    os.environ["MDCG_SEMANTIC"] = "1"
    cg.search("灵枢 记忆库", k=5, record=False)
    chk(hc.stats()["query_hits"] == before4, "H4 环境开关翻动后不命中（键含 env_switch）")
    os.environ.pop("MDCG_SEMANTIC", None)

    # H5 命中时 meta 带 cached=True（与模块头声明的观测面一致）
    cg.search("灵枢 记忆库", k=5, record=False)
    _r, meta_hit = cg.search("灵枢 记忆库", k=5, record=False)
    chk(bool((meta_hit or {}).get("cached")), "H5 命中时 meta.cached=True")

    print("=" * 60)
    print("热缓存接线守卫：%d 通过 / %d 失败" % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
