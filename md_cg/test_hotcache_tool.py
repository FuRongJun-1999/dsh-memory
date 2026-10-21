# -*- coding: utf-8 -*-
"""工具面热缓存守卫（issue #614，默认面接线）。

C1 第二次同参调用命中（query_hits>=1），且 results 逐条相同
C2 写后读不陈旧：新增独有词节点后可见
C3 换 k 不串味（未命中）
C4 环境开关翻动后不命中（键含 env_switch）
C5 显式 node_id 的调用绕过缓存
"""
from __future__ import annotations

import os
import tempfile

from . import hotcache as HC
from .mdcos import MdCGSecure
from .mcp_server import call_tool


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

    root = tempfile.mkdtemp(prefix="hc_tool_")
    cg = MdCGSecure(root)
    for i in range(6):
        cg.add("n%d" % i, "灵枢 记忆库 条目 %d alpha" % i, layer="knowledge")
    hc = HC.get(cg)
    chk(hc is not None, "C0 热缓存已挂载")

    r1 = call_tool(cg, "mdcg_search", {"query": "灵枢 记忆库 alpha", "k": 5})
    s1 = hc.stats()
    r2 = call_tool(cg, "mdcg_search", {"query": "灵枢 记忆库 alpha", "k": 5})
    s2 = hc.stats()
    chk(s1["query_misses"] >= 1, "C1a 首次未命中（misses=%d）" % s1["query_misses"])
    chk(s2["query_hits"] >= 1, "C1b 第二次命中（hits=%d）" % s2["query_hits"])
    chk(r1.get("results") == r2.get("results"), "C1c 命中时结果逐条相同")

    cg.add("n_new", "阿洛芬 独有词", layer="knowledge")
    r3 = call_tool(cg, "mdcg_search", {"query": "阿洛芬", "k": 5})
    ids3 = [x["node"]["id"] for x in (r3.get("results") or [])]
    chk("n_new" in ids3, "C2 写后读不陈旧")

    before = hc.stats()["query_hits"]
    call_tool(cg, "mdcg_search", {"query": "灵枢 记忆库 alpha", "k": 3})
    chk(hc.stats()["query_hits"] == before, "C3 换 k 不串味")

    os.environ["MDCG_SEMANTIC"] = "0"
    call_tool(cg, "mdcg_search", {"query": "灵枢 记忆库 alpha", "k": 5})
    b4 = hc.stats()["query_hits"]
    os.environ["MDCG_SEMANTIC"] = "1"
    call_tool(cg, "mdcg_search", {"query": "灵枢 记忆库 alpha", "k": 5})
    chk(hc.stats()["query_hits"] == b4, "C4 环境开关翻动后不命中")
    os.environ.pop("MDCG_SEMANTIC", None)

    before5 = hc.stats()["query_hits"]
    call_tool(cg, "mdcg_search", {"query": "灵枢 记忆库 alpha", "k": 5, "node_id": None})
    chk(hc.stats()["query_hits"] == before5, "C5 显式 node_id 绕过缓存")

    print("=" * 60)
    print("工具面热缓存守卫：%d 通过 / %d 失败" % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
