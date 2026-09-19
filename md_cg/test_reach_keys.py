# -*- coding: utf-8 -*-
"""test_reach_keys.py · 新鲜度键与落盘的**编码无歧义**验收（r11 复核反例固化）。

背景：_node_key 曾用 ';'/'|' 拼接 tags/edges，导致 ["a;b"] 与 ["a","b"] 生成同键；
倒排曾用 ',' 与 chr(31) 拼接路径。本测试把编码层的不变性固化：
  ① tags 含分隔符不碰撞   ② edges 含分隔符不碰撞
  ③ 倒排落地/重载对含控制字符的路径原样保留   ④ TTL<=0 回落默认（不得静默关闭兜底）
  ⑤ hash_complete 按原始 content_hash 判定

运行：python -m md_cg.test_reach_keys
"""
from __future__ import annotations

import json
import os
import tempfile
import time

from . import reach

PASS = FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    PASS += int(bool(cond))
    FAIL += int(not cond)
    print(f'[{"✓" if cond else "✘"}] {label}' + (f"  · {detail}" if detail else ""))


def _fake(root, **entry):
    base = {"path": "knowledge/a.md", "content_hash": "H1", "tags": [], "edges": []}
    base.update(entry)

    class _CG:
        def __init__(self):
            self.root = root
            self.index = {"nodes": {"n1": dict(base)}}
        def _read(self, e):
            return {}, ""
        def _open_content(self, node_id, fm, content):
            return content
    return _CG()


def main():
    root = tempfile.mkdtemp(prefix="reach_keys_")
    # reach 为显式 opt-in（契约 §7：不在默认路径上启用新行为），本测试须自行开启
    os.environ["MDCG_REACH"] = "1"
    os.environ["MDCG_REACH_INDEX"] = os.path.join(root, "idx.json")
    # r12 复核：无 path 的条目不计入覆盖判定（与 build 口径一致）
    class _CG3:
        def __init__(self):
            self.root = root
            self.index = {"nodes": {"n1": {"path": "knowledge/a.md", "content_hash": "H1"},
                                          "n2": {"content_hash": None}}}
        def _read(self, e):
            return {}, ""
        def _open_content(self, node_id, fm, content):
            return content
    ok(reach._hash_complete(_CG3()) is True,
       "⑤ 无 path 条目不计入 hash 覆盖（与 build 口径一致）")

    print("md_cg reach 键编码验收 · 无歧义 / TTL 兜底 / 落盘往返")
    print("=" * 66)
    # ① tags 分隔符不碰撞
    k1 = reach._node_key(_fake(root, tags=["a;b"]).index["nodes"]["n1"])
    k2 = reach._node_key(_fake(root, tags=["a", "b"]).index["nodes"]["n1"])
    ok(k1 != k2, "① tags 含分号不碰撞", f"{k1[:26]} vs {k2[:26]}")
    k3 = reach._node_key(_fake(root, tags=["a|b"]).index["nodes"]["n1"])
    k4 = reach._node_key(_fake(root, tags=["a", "b"]).index["nodes"]["n1"])
    ok(k3 != k4, "① tags 含竖线不碰撞")
    # ② edges 分隔符不碰撞
    e1 = reach._node_key(_fake(root, edges=[{"target": "a|b", "type": ""}]).index["nodes"]["n1"])
    e2 = reach._node_key(_fake(root, edges=[{"target": "a", "type": "b"}]).index["nodes"]["n1"])
    ok(e1 != e2, "② edges 含竖线不碰撞")
    e3 = reach._node_key(_fake(root, edges=[{"target": "a;b", "type": "c"}]).index["nodes"]["n1"])
    e4 = reach._node_key(_fake(root, edges=[{"target": "a", "type": "b;c"}]).index["nodes"]["n1"])
    ok(e3 != e4, "② edges 含分号不碰撞")
    # ③ 倒排落盘对控制字符路径原样往返
    idx = reach.ReachIndex(root)
    weird = "knowledge/a" + chr(31) + "b.md"
    idx.post = {"召": [weird]}
    idx.adj = {}
    idx.hashes = {}
    idx.save()
    back = reach.ReachIndex(root)
    back.load()
    ok(back.post.get("召") == [weird], "③ 含控制字符路径经落盘/重载原样保留",
       str(back.post.get("召")))
    # ④ TTL<=0 → 回落默认（不得静默关闭）
    class _CG2:
        def __init__(self):
            self.root = root
            self.index = {"nodes": {"n1": {"path": "knowledge/a.md", "content_hash": "H1",
                                           "tags": [], "edges": []}}}
    cg = _CG2()
    os.environ["MDCG_REACH_TTL"] = "0"
    idx2 = reach.ReachIndex(root)
    idx2.built_at = time.time() - 4000
    saved = reach._CACHE
    reach._CACHE = {}
    ok(reach._ttl() == 600.0, "④ TTL=0 经 _ttl() 回落 600s", str(reach._ttl()))
    os.environ["MDCG_REACH_TTL"] = "-5"
    ok(reach._ttl() == 600.0, "④ TTL 负值同样回落默认")
    os.environ["MDCG_REACH_TTL"] = "abc"
    ok(reach._ttl() == 600.0, "④ TTL 非法文本回落默认")
    os.environ["MDCG_REACH_TTL"] = "30"
    ok(reach._ttl() == 30.0, "④ 正数 TTL 原样生效")
    os.environ["MDCG_REACH_TTL"] = "inf"
    ok(reach._ttl() == 600.0, "④ TTL=inf 回落默认（否则过期判断永假）", str(reach._ttl()))
    os.environ["MDCG_REACH_TTL"] = "1e999"
    ok(reach._ttl() == 600.0, "④ TTL=1e999（溢出为 inf）回落默认")
    os.environ["MDCG_REACH_TTL"] = "nan"
    ok(reach._ttl() == 600.0, "④ TTL=nan 回落默认")
    os.environ["MDCG_REACH_TTL"] = "0"
    reach._CACHE = saved
    # ⑤ hash_complete 按原始 content_hash 判定
    a = reach.ReachIndex(root); a.hash_complete = None
    b = reach.ReachIndex(root); b.hash_complete = None
    a.build(_fake(root, content_hash="H1"))
    b.build(_fake(root, content_hash=None))
    ok(a.hash_complete is True and b.hash_complete is False,
       "⑤ hash_complete 按原始 content_hash", f"a={a.hash_complete} b={b.hash_complete}")
    # r13 复核：真实磁盘新鲜度路径（不手写 _CACHE）
    os.environ["MDCG_REACH_TTL"] = "0"
    cg2 = _CG3()
    idx_a = reach.ReachIndex(root)
    idx_a.build(cg2)
    idx_a.save()
    idx_b = reach.ReachIndex(root)
    idx_b.load()
    ok(reach._disk_fresh(idx_b, cg2) is True, "⑤ 真实磁盘缓存：同库判新鲜")
    cg3 = _CG3()
    cg3.index["nodes"]["n1"]["content_hash"] = "H2"
    ok(reach._disk_fresh(idx_b, cg3) is False, "⑤ 真实磁盘缓存：content_hash 变即判不新鲜")
    # r13 复核：落盘失败（只读根）时不得入进程缓存（类级替换 save 注入 OSError）
    saved_save = reach.ReachIndex.save
    def _boom(self):
        raise OSError('readonly')
    reach.ReachIndex.save = _boom
    try:
        reach._CACHE.clear()
        reach._index(cg2, force=True)
        ok(len(reach._CACHE) == 0, '⑤ 落盘失败时不入进程缓存（下次调用重建）', str(list(reach._CACHE)))
    finally:
        reach.ReachIndex.save = saved_save
    # r15 复核：库内缺 content_hash 时，即使本次刚重建也必须回退（不得收敛）
    class _CG5:
        def __init__(self):
            self.root = root
            self.index = {"nodes": {"n1": {"path": "knowledge/a.md", "tags": [], "edges": []}}}
        def _read(self, e):
            return {}, ""
        def _open_content(self, node_id, fm, content):
            return content
    os.environ["MDCG_REACH_INDEX"] = os.path.join(root, "idx2.json")
    reach._CACHE.clear()
    got_h, meta_h = reach.narrow(_CG5(), [{"path": "knowledge/a.md"}], ["abcd"], {"abcd"}, None, q="abcd")
    ok(got_h is None and meta_h.get("reach") == "hash_incomplete",
       "⑤ 缺 content_hash 时一律回退不收敛", str(meta_h)[:80])
    # r17 复核：库内含不可读节点时，磁盘缓存仍须判新鲜（口径与 build 的剔除对齐）
    class _CG6:
        def __init__(self):
            self.root = root
            self.index = {"nodes": {"n1": {"path": "knowledge/a.md", "content_hash": "H1"},
                                          "n2": {"path": "knowledge/locked.md", "content_hash": "H2"}}}
        def _read(self, e):
            if e.get("path", "").endswith("locked.md"):
                return None, None          # 不可读（模拟解密失败）
            return {}, ""
        def _open_content(self, node_id, fm, content):
            return content
    os.environ["MDCG_REACH_INDEX"] = os.path.join(root, "idx3.json")
    cg6 = _CG6()
    i6 = reach.ReachIndex(root)
    i6.build(cg6)
    i6.save()
    i6b = reach.ReachIndex(root)
    i6b.load()
    ok(reach._disk_fresh(i6b, cg6) is True,
       "⑤ 含不可读节点时磁盘缓存仍判新鲜（跨进程可复用）",
       "hashes=%d" % len(i6.hashes))
    cg6.index["nodes"]["n1"]["content_hash"] = "H9"
    ok(reach._disk_fresh(i6b, cg6) is False, "⑤ 已缓存节点 hash 变即判不新鲜")
    # r18 复核：hash 不完整时——首次调用必须暴露首建成本；第二次调用不得再全库重建
    os.environ["MDCG_REACH_INDEX"] = os.path.join(root, "idx4.json")
    reach._CACHE.clear()
    _cg7 = _CG5()
    _g1, m1 = reach.narrow(_cg7, [{"path": "knowledge/a.md"}], ["abcd"], {"abcd"}, None, q="abcd")
    ok(_g1 is None and m1.get("reach") == "hash_incomplete" and m1.get("reach_build_docs") is not None,
       "⑤ hash 不完整：首次调用暴露首建成本", str(m1)[:90])
    _g2, m2 = reach.narrow(_cg7, [{"path": "knowledge/a.md"}], ["abcd"], {"abcd"}, None, q="abcd")
    ok(_g2 is None and m2.get("reach") == "hash_incomplete" and "reach_build_docs" not in m2,
       "⑤ hash 不完整：第二次调用复用缓存（不再全库重建）", str(m2)[:90])
    print(f"\n===== 键编码验收：{PASS}/{PASS + FAIL} 通过 =====")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
