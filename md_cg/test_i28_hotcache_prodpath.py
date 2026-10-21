# -*- coding: utf-8 -*-
"""issue #28 守卫：hotcache 生产路径挂载（读侧写侧已接、中间从未装上）。

病灶（2026-09-23 外部报告）：search_rrf 读 hotcache（mdcos:1195）、writepipe
写后失效（writepipe:436），但全仓无任何 attach() 调用——生产 get(cg) 恒
None，重复 query 永远全量重扫。与 #25 同模式：读写两侧在、挂载点悬空。

修复：MdCGOS.__init__ 按 MDCG_HOTCACHE=1 显式挂载（默认关零变更）；
容量 env 可配（MDCG_HOTCACHE_MAX_NODES/MAX_QUERIES）。

断言：
  H1 默认零变更（无 env → get 为 None，能红「无条件挂载」的过度修复）；
  H2 开关开启 → 生产类（MdCGSecure）get 非 None（能红旧实现）；
  H3 query 缓存命中（重复 query meta.cached=True + stats）；
  H4 写后失效联动（写入 → query 缓存全清，不返回陈旧结果）；
  H5 容量 env 生效（max_nodes 缩容 → LRU 淘汰按新上限）。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import hotcache
from md_cg.mdcos import MdCGSecure

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


def _mk(root):
    from md_cg.security import Principal
    return MdCGSecure(root, principal=Principal(
        actor="t_i28", clearance="secret", can_write=True,
        role="designer", auth_mode="test"))


def main():
    print("== H1 默认零变更 ==")
    os.environ.pop("MDCG_HOTCACHE", None)
    cg1 = _mk(tempfile.mkdtemp(prefix="mdcg_i28a_"))
    check("H1 无 env → 不挂载（get=None；能红『无条件挂载』误修）",
          hotcache.get(cg1) is None)

    print("== H2 开关挂载（能红旧实现）==")
    os.environ["MDCG_HOTCACHE"] = "1"
    try:
        cg2 = _mk(tempfile.mkdtemp(prefix="mdcg_i28b_"))
        check("H2 生产类构造后 hotcache 已挂（旧实现恒 None）",
              hotcache.get(cg2) is not None)
        cg2.add("mem_h1", "# 功能名：热缓存探针\n# 正文：hotcache probe 内容",
                layer="knowledge")

        print("== H3 query 缓存命中 ==")
        _r1, m1 = cg2.search_rrf("hotcache probe") if hasattr(
            cg2, "search_rrf") else (None, {})
        _r2, m2 = cg2.search_rrf("hotcache probe")
        check("H3a 重复 query 命中缓存（meta.cached=True）",
              m2.get("cached") is True,
              json.dumps(m2, ensure_ascii=False, default=str)[:160])
        st = hotcache.get(cg2).stats()
        check("H3b 统计计数可见（query_hits>=1）",
              st.get("query_hits", 0) >= 1, json.dumps(st))

        print("== H4 写后失效联动（生产写入路径）==")
        # 失效挂在 writepipe 的 after_trust（MCP op=write 路径）——库层直调
        # cg.add 不经过该链（内部/测试场景），其失效缺口如实登记不在本断言。
        from md_cg.mcp_server import _cg_dispatch
        _w = _cg_dispatch(cg2, {"op": "write", "content_kind": "code",
                                "layer": "knowledge", "node_id": "mem_h2",
                                "content": "def h2():\n    return 'hotcache new'\n"})
        check("H4a 生产写入成功（失效触发前提）",
              _w.get("committed") is True,
              json.dumps(_w, ensure_ascii=False, default=str)[:160])
        _r3, m3 = cg2.search_rrf("hotcache probe")
        check("H4b 写入后 query 缓存全清（不返回陈旧结果）",
              m3.get("cached") is not True,
              json.dumps({k: m3.get(k) for k in ("cached", "tier")},
                         ensure_ascii=False))

        print("== H5 容量 env 生效 ==")
        os.environ["MDCG_HOTCACHE_MAX_NODES"] = "3"
        cg3 = _mk(tempfile.mkdtemp(prefix="mdcg_i28c_"))
        hc3 = hotcache.get(cg3)
        check("H5a 容量 env 进入实例（max_nodes=3）",
              hc3 is not None and hc3._max_nodes == 3,
              f"max_nodes={getattr(hc3, '_max_nodes', None)}")
        for i in range(6):
            hc3.put_node(f"n{i}", {"layer": "knowledge"}, "")
            _ = hc3.get_node(f"n{i}")     # 反复摸 n0..n5 → n0/n1 应被挤出
        check("H5b LRU 按新上限淘汰（size==3，最旧两节点不在）",
              len(hc3._nodes) == 3
              and hotcache.get(cg3).get_node("n0") is None
              and hotcache.get(cg3).get_node("n5") is not None,
              f"size={len(hc3._nodes)}")
    finally:
        os.environ.pop("MDCG_HOTCACHE", None)
        os.environ.pop("MDCG_HOTCACHE_MAX_NODES", None)

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} 项 → {', '.join(FAILS)}")
        return 1
    print(f"ALL OK: {PASS} 项（issue #28 热缓存生产路径守卫全绿）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
