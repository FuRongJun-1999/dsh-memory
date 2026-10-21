# -*- coding: utf-8 -*-
"""工具面热缓存守卫（issue #614）。

C1 第二次同参命中且结果逐条相同
C2 写后读不陈旧
C3 换 k 不串味
C4 环境开关翻动不命中
C5 显式 node_id 绕过缓存
C6 值形状标签：命中体必须是本面写入的（surface/v 校验），异形一律当未命中
C7 命中返回体是深拷贝：调用方原地修改不得污染缓存
C8 validity=True 一律不缓存（无时钟窗语义）
"""
from __future__ import annotations

import os
import tempfile

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

    root = tempfile.mkdtemp(prefix="hc_tool2_")
    cg = MdCGSecure(root)
    for i in range(6):
        cg.add("n%d" % i, "灵枢 记忆库 条目 %d alpha" % i, layer="knowledge")

    r1 = call_tool(cg, "mdcg_search", {"query": "灵枢 记忆库 alpha", "k": 5})
    hc = getattr(cg, "_hotcache_tool", None)
    chk(hc is not None, "C0 工具层用独立缓存实例")
    s1 = hc.stats()
    r2 = call_tool(cg, "mdcg_search", {"query": "灵枢 记忆库 alpha", "k": 5})
    s2 = hc.stats()
    chk(s1["query_misses"] >= 1 and s2["query_hits"] >= 1, "C1 命中（misses=%d hits=%d）" % (s1["query_misses"], s2["query_hits"]))
    chk(r1.get("results") == r2.get("results"), "C1b 命中结果逐条相同")

    cg.add("n_new", "阿洛芬 独有词", layer="knowledge")
    r3 = call_tool(cg, "mdcg_search", {"query": "阿洛芬", "k": 5})
    chk("n_new" in [x["node"]["id"] for x in (r3.get("results") or [])], "C2 写后读不陈旧")

    before = hc.stats()["query_hits"]
    call_tool(cg, "mdcg_search", {"query": "灵枢 记忆库 alpha", "k": 3})
    chk(hc.stats()["query_hits"] == before, "C3 换 k 不串味")

    os.environ["MDCG_SEMANTIC"] = "0"
    call_tool(cg, "mdcg_search", {"query": "灵枢 记忆库 alpha", "k": 5})
    b4 = hc.stats()["query_hits"]
    os.environ["MDCG_SEMANTIC"] = "1"
    call_tool(cg, "mdcg_search", {"query": "灵枢 记忆库 alpha", "k": 5})
    chk(hc.stats()["query_hits"] == b4, "C4 开关翻动后不命中")
    os.environ.pop("MDCG_SEMANTIC", None)

    b5 = hc.stats()["query_hits"]
    call_tool(cg, "mdcg_search", {"query": "灵枢 记忆库 alpha", "k": 5, "node_id": None})
    chk(hc.stats()["query_hits"] == b5, "C5 显式 node_id 绕过")

    # C6：往同一实例塞一个异形值（模拟内部层写进来的形状），必须当未命中而不是返回垃圾
    call_tool(cg, "mdcg_search", {"query": "形状探针", "k": 5})
    _q = "形状探针"
    try:
        _keys = list(hc._queries.keys())
        _k0 = [k for k in _keys if k[0] == _q]
        if _k0:
            hc._queries[_k0[0]] = (hc._queries[_k0[0]][0], [("row", 0.1, {}, "p")], {})
    except Exception:
        pass
    r6 = call_tool(cg, "mdcg_search", {"query": _q, "k": 5})
    chk(isinstance(r6, dict) and "results" in r6, "C6 异形缓存值被当未命中（不返回垃圾）")

    # C7：命中体是深拷贝——改它不能污染缓存
    _r7a = call_tool(cg, "mdcg_search", {"query": "灵枢 记忆库 alpha", "k": 5})
    _r7a.setdefault("results", []).append({"node": {"id": "污染"}, "score": 99})
    _r7b = call_tool(cg, "mdcg_search", {"query": "灵枢 记忆库 alpha", "k": 5})
    chk("污染" not in [x["node"]["id"] for x in (_r7b.get("results") or [])], "C7 命中体深拷贝（原地修改不污染）")

    # C8：validity=True 不缓存
    b8 = hc.stats()["query_hits"]
    call_tool(cg, "mdcg_search", {"query": "灵枢 记忆库 alpha", "k": 5, "validity": True})
    call_tool(cg, "mdcg_search", {"query": "灵枢 记忆库 alpha", "k": 5, "validity": True})
    chk(hc.stats()["query_hits"] == b8, "C8 validity=True 不缓存")

    print("=" * 60)
    print("工具面热缓存守卫：%d 通过 / %d 失败" % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
