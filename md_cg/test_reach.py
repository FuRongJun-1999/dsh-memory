# -*- coding: utf-8 -*-
"""test_reach.py · 检索候选收敛层（reach）验收。

覆盖（对应 A2/A3 判据的可证形式）：
 (1) 包含性：收敛集 ⊇ 全量 LIKE 命中集，且 ⊇ 词法打分>0 集合（A2「不丢召回」的可证形式）
 (2) 条件门控：收敛集 ⊆ 调用方候选集（层/角色/会话/分支由 _candidates 承载）；不可读节点不越权
 (3) 图扩散：edges 邻居被吸收补召回；扩散受 DIFFUSE_MAX_FACTOR 上限约束
 (4) 回退：MDCG_REACH=0 / 单字符 term / 索引不可用 → 不收敛（返回 None），旧行为不变
 (5) 端到端：search 开关两态结果集为包含关系、meta 带 reach*、scanned 下降
 (6) 缓存失效：新增节点后重建，新节点可被收敛召回（防陈旧缓存丢召回）

运行：python -m md_cg.test_reach
"""
from __future__ import annotations

import json
import os
import tempfile
import time

from .mdcos import MdCGOS
from .mdcg import bigrams, expand_query_terms, normalize_en
from . import reach

PASS = FAIL = 0
FAILS = []


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {label}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  [FAIL] {label}" + (f"  · {detail}" if detail else ""))


QUERY = "召回截断 分池"
BODY = "召回截断 索引 分池 内容"


def _mk(root):
    cg = MdCGOS(root, actor="test_reach")
    for i in range(3):
        cg.add(f"code_{i}", f"# 功能名：索引条目 {i}\n# 生效条件：条件 I\n\n{BODY} {i}\n",
               layer="knowledge", tags=["index"])
    for i in range(3):
        cg.add(f"kp_{i}", f"# 功能名：知识 {i}\n# 生效条件：条件 K\n\n召回截断 索引 内容 {i}\n",
               layer="knowledge")
    cg.add("other_1", "# 功能名：无关\n# 生效条件：条件 O\n\n完全无关的另一段文本。\n",
           layer="knowledge")
    # 组扩散：other_2 不含查询词，但被 code_0 通过 edges 指向（图扩散应把它补进收敛集）
    cg.add("other_2", "# 功能名：邻居\n# 生效条件：条件 N\n\n也不含查询词的邻居正文。\n",
           layer="knowledge")
    cg.add("code_0b", f"# 功能名：索引条目 0b\n# 生效条件：条件 I\n\n{BODY} 0b\n",
           layer="knowledge", edges=[{"target": "other_2", "type": "similar", "confidence": 0.9}])
    cg.add("n_rej", f"# 功能名：被否决\n# 生效条件：条件 R\n\n{BODY} 否\n", layer="rejected")
    cg.flush()
    return cg


def _env(on):
    os.environ["MDCG_REACH"] = "1" if on else "0"
    reach._CACHE.clear()


def _search_both(cg, query, k, on):
    """在指定开关下跑一次 search（供两态对比）。"""
    _env(on)
    if on:
        reach._CACHE.clear()
    return cg.search(query, k=k)


def _like_ids(cg, entries, terms):
    stat = {"scanned": 0}
    docs = cg._read_many(entries, stat)
    return {e["path"] for e, fm, c in docs if cg._like(c, fm, terms)}, docs


def main():
    print("md_cg 收敛层 reach 验收 · 大域收敛 / 条件门控 / 图扩散 / 回退")
    print("=" * 70)
    root = tempfile.mkdtemp(prefix="mdcg_reach_")
    try:
        os.environ["MDCG_REACH_INDEX"] = os.path.join(root, "_idx_measure.json")
        cg = _mk(root)
        entries = cg._candidates()
        terms = expand_query_terms(QUERY)
        qb = bigrams(normalize_en(QUERY))

        # ---------------- (1) 包含性 ----------------
        print("\n(1) 大域收敛包含性（A2 可证形式）")
        _env(True)
        full_like, docs = _like_ids(cg, entries, terms)
        narrow, meta = reach.narrow(cg, entries, terms, qb, None, q=QUERY)
        nset = {e["path"] for e in (narrow or [])}
        ok(full_like and full_like <= nset,
           "(1) 收敛集 ⊇ 全量 LIKE 命中集", f"like={len(full_like)} narrow={len(nset)} miss={len(full_like - nset)}")
        scored = cg._score(docs, QUERY, qb, None)
        pos = {d[0]["path"] for d in scored if d[1] > 0}
        ok(pos <= nset, "(1) 收敛集 ⊇ 词法打分>0 集合",
           f"score>0={len(pos)} miss={len(pos - nset)}")
        ok(meta.get("reach") == "converged" and meta.get("reach_seed", 0) > 0,
           "(1) meta 如实报收敛状态", str(meta))

        # ---------------- (2) 条件门控 ----------------
        print("\n(2) 条件门控（收敛集 ⊆ 候选集）")
        epaths = {e["path"] for e in entries}
        ok(nset <= epaths, "(2) 收敛集不越出调用方候选集")
        ok(all(e.get("layer") != "rejected" for e in narrow), "(2) 负记忆层不因收敛回流")

        # ---------------- (3) 图扩散 ----------------
        print("\n(3) 图扩散")
        idx = reach._index(cg)
        ids = {e["path"].split("/")[-1][:-3] for e in narrow}
        os.environ["MDCG_REACH_DIFFUSE"] = "1"      # 扩散默认关（保 A2 精确），此处置开验证能力
        narrow_d, meta_d = reach.narrow(cg, entries, terms, qb, None, q=QUERY)
        os.environ["MDCG_REACH_DIFFUSE"] = "0"
        ids_d = {e["path"].split("/")[-1][:-3] for e in (narrow_d or [])}
        ok("other_2" in ids_d and meta_d.get("reach_diffused") == 1,
           "(3) 扩散开关开启时 edges 邻居被吸收",
           f"other_2 in narrow_d={'other_2' in ids_d} diffused={meta_d.get('reach_diffused')} (默认关时 ids={len(ids)})")
        fake = reach.ReachIndex(root)
        fake.adj = {"a": ["b", "c"], "b": ["d"], "d": ["e"]}
        one = fake.diffuse({"a"}, hops=1)
        two = fake.diffuse({"a"}, hops=2)
        ok(one == {"a", "b", "c"}, "(3) 1 跳邻居集合正确", str(sorted(one)))
        ok(two >= {"a", "b", "c", "d"}, "(3) 2 跳可达", str(sorted(two)))
        big = {"s0"}
        fake.adj = {"s0": [f"n{i}" for i in range(100)]}
        lim = fake.diffuse({"s0"}, hops=1, limit=3)
        ok(len(lim) <= 3, "(3) 扩散受上限约束", f"|out|={len(lim)}")

        # ---------------- (4) 回退 ----------------
        print("\n(4) 回退（不适用条件 → 不收敛）")
        _env(False)
        got, meta = reach.narrow(cg, entries, terms, qb, None, q=QUERY)
        ok(got is None and meta.get("reach") == "off", "(4) MDCG_REACH=0 → 不收敛", str(meta))
        _env(True)
        got, meta = reach.narrow(cg, entries, ["白"], bigrams("白"), None, q="白")
        ok(got is None and meta.get("reach") == "short_term", "(4) 单字符 term → 不收敛", str(meta))
        saved = reach._index
        reach._index = lambda *a, **k: None
        try:
            got, meta = reach.narrow(cg, entries, terms, qb, None, q=QUERY)
            ok(got is None and meta.get("reach") == "index_unavailable",
               "(4) 索引不可用 → 不收敛", str(meta))
        finally:
            reach._index = saved

        # ---------------- (5) 端到端 ----------------
        print("\n(5) 端到端（search 两态）")
        _env(False)
        res_off, m_off = cg.search(QUERY, k=10)
        off_ids = [r[0]["id"] for r in res_off]
        _env(True)
        reach._CACHE.clear()
        res_on, m_on = cg.search(QUERY, k=10)
        on_ids = [r[0]["id"] for r in res_on]
        ok(set(on_ids) >= set(off_ids), "(5) 开态结果集 ⊇ 关态（不丢召回）",
           f"off={off_ids[:3]} on={on_ids[:3]}")
        ok(m_on.get("reach") == "converged" and m_on.get("reach_seed"),
           "(5) meta 透出 reach* 审计字段", f"reach={m_on.get('reach')} seed={m_on.get('reach_seed')}")
        ok(m_on.get("scanned", 0) <= m_off.get("scanned", 0),
           "(5) 开态读盘数不增（收敛生效）",
           f"off={m_off.get('scanned')} on={m_on.get('scanned')}")
        ok(m_on.get("pre_cap", 0) >= m_off.get("pre_cap", 0),
           "(5) 截断前候选数不少于关态（图扩散可补召回）",
           f"off={m_off.get('pre_cap')} on={m_on.get('pre_cap')}")
        # 图扩散必须真的落到**结果层**（T3-r3 复核：只并入收敛集、随后被 _like 过滤掉等于没做）
        os.environ["MDCG_REACH_DIFFUSE"] = "1"      # 结果层放行扩散节点需显式开关
        res_big_off, _ = _search_both(cg, QUERY, 50, False)
        res_big_on, _ = _search_both(cg, QUERY, 50, True)
        os.environ["MDCG_REACH_DIFFUSE"] = "0"
        ids_on = {r[0]["id"] for r in res_big_on}
        ids_off = {r[0]["id"] for r in res_big_off}
        ok("other_2" in ids_on and "other_2" not in ids_off,
           "(5) 图扩散邻居进入 search 结果（补召回落地）",
           f"other_2 on={'other_2' in ids_on} off={'other_2' in ids_off}")

        # r14 复核：收敛集非空但 LIKE 命中为空 → 回退全量，且 meta.reach 必须改写为 reverted（不得谎报 converged）
        _env(True)
        _saved_like = cg._like
        cg._like = staticmethod(lambda *a, **k: False)   # 模拟「bigram 有交集但无 LIKE 命中」
        try:
            res_rv, m_rv = cg.search(QUERY, k=5)
        finally:
            cg._like = _saved_like
        ok(m_rv.get("reach") == "reverted",
           "(5b) 回退全量时 reach 改写为 reverted（不谎报 converged）", str(m_rv.get("reach")))
        ok(bool(res_rv), "(5b) 回退后仍能出结果（全量路径）", f"n={len(res_rv)}")
        ok(m_rv.get("reach_reverted") is True, "(5b) 回退标记 reach_reverted=True")
        ok(isinstance(m_rv.get("reach_reverted_docs"), int) and m_rv["reach_reverted_docs"] >= 0,
           "(5b) 回退时暴露收敛阶段读盘量（A3 可扣减）", f"docs={m_rv.get('reach_reverted_docs')}")
        # 让该次调用确实发生重建：清缓存并把磁盘缓存改旧，再令 _like 恒假 → 回退且首建成本必须保留
        reach._CACHE.clear()
        live2 = reach._index(cg)
        live2.built_at = time.time() - 4000
        try:
            d4 = json.load(open(live2.path, encoding="utf-8"))
            d4["built_at"] = time.time() - 4000
            json.dump(d4, open(live2.path, "w", encoding="utf-8"))
        except OSError:
            pass
        cg._like = staticmethod(lambda *a, **k: False)
        try:
            res_rv2, m_rv2 = cg.search(QUERY, k=5)
        finally:
            cg._like = _saved_like
        ok(m_rv2.get("reach") == "reverted" and m_rv2.get("reach_build_docs") is not None,
           "(5b) 回退时若发生重建，首建成本字段必须保留",
           f"reach={m_rv2.get(chr(39)+chr(39)) if False else m_rv2.get('reach')} build={m_rv2.get('reach_build_docs')}")

        # ---------------- (6) 缓存失效 ----------------
        print("\n(6) 缓存失效（新增节点后仍可召回）")
        cg.add("code_new", f"# 功能名：新增索引条目\n# 生效条件：条件 I\n\n{BODY} new\n",
               layer="knowledge", tags=["index"])
        cg.flush()
        res2, m2 = cg.search(QUERY, k=20)
        ok(any(r[0]["id"] == "code_new" for r in res2),
           "(6) 新增节点进入收敛集（指纹失效触发重建）",
           f"reach={m2.get('reach')} ids={[r[0]['id'] for r in res2][:4]}")
        # 指纹必须含 path（r6 复核：路径交换/重命名而 content_hash 未变时不得复用缓存）
        class _FakeCG:
            def __init__(self, path):
                self.root = root
                self.index = {"nodes": {"n1": {"path": path, "content_hash": "H1"}}}
        fp_a = reach._fingerprint(_FakeCG("knowledge/a.md"))
        fp_b = reach._fingerprint(_FakeCG("knowledge/b.md"))
        ok(fp_a != fp_b, "(7) 指纹含 path（路径变更即判不新鲜）", "%s vs %s" % (fp_a[:8], fp_b[:8]))
        # r7 复核：仅改 edges 也必须判不新鲜（否则 MDCG_REACH_DIFFUSE=1 时扩散复用旧邻接表）
        class _FakeCG2:
            def __init__(self, edges):
                self.root = root
                self.index = {"nodes": {"n1": {"path": "knowledge/a.md",
                                              "content_hash": "H1", "edges": edges}}}
        e0 = _FakeCG2([])
        e1 = _FakeCG2([{"target": "knowledge/b.md", "type": "similar"}])
        ok(reach._fingerprint(e0) != reach._fingerprint(e1),
           "(7) 指纹含 edges（仅改边即判不新鲜）")
        ok(reach._node_key(e0.index["nodes"]["n1"]) != reach._node_key(e1.index["nodes"]["n1"]),
           "(7) 新鲜度键含 edges 签名")
        # r9 复核：tags 变更也必须判不新鲜（倒排含标签 bigram）
        class _FakeCG3:
            def __init__(self, tags):
                self.root = root
                self.index = {"nodes": {"n1": {"path": "knowledge/a.md",
                                              "content_hash": "H1", "tags": tags, "edges": []}}}

        ok(reach._node_key(_FakeCG3(["x"]).index["nodes"]["n1"])
           != reach._node_key(_FakeCG3(["y"]).index["nodes"]["n1"]),
           "(7) 新鲜度键含 tags（仅改标签即判不新鲜）")
        # r10 复核：真实 cg.add 后的索引条目必须带 tags（否则 tags 新鲜度不可用）
        cg.add("tag_probe", "# 功能名：标签探针\n# 生效条件：条件 T\n\n标签探针正文。\n",
               layer="knowledge", tags=["alpha"])
        cg.flush()
        ent = cg.index["nodes"].get("tag_probe")
        ok(bool(ent) and "alpha" in (ent.get("tags") or []),
           "(7) 真实索引含 tags（新鲜度键可依赖）", str((ent or {}).get("tags"))[:60])
        import copy as _copy
        e_mod = _copy.deepcopy(ent or {})
        e_mod["tags"] = ["beta"]
        ok(reach._node_key(ent or {}) != reach._node_key(e_mod),
           "(7) 真实条目改标签即改新鲜度键")
        # r10 复核：hash_complete 必须看原始 content_hash（缺则判不完整 → 不复用）
        class _FakeCG4:
            def __init__(self, with_hash):
                self.root = root
                n = {"path": "knowledge/a.md", "tags": [], "edges": []}
                if with_hash:
                    n["content_hash"] = "H1"
                self.index = {"nodes": {"n1": n}}
            def _read(self, e):
                return {}, ""
            def _open_content(self, node_id, fm, content):
                return content
        idx_fresh = reach.ReachIndex(root)
        idx_fresh.build(_FakeCG4(True))
        idx_miss = reach.ReachIndex(root)
        idx_miss.build(_FakeCG4(False))
        ok(idx_fresh.hash_complete is True and idx_miss.hash_complete is False,
           "(7) hash_complete 按原始 content_hash 判定",
           "fresh=%s miss=%s" % (idx_fresh.hash_complete, idx_miss.hash_complete))
        # ---------------- (7) 落盘/新鲜度/首建成本 ----------------
        print(chr(10) + "(7) 落盘分隔符 / 新鲜度 / 首建成本")
        cg.add("comma,node", f"# 功能名：含逗号\n# 生效条件：条件 C\n\n{BODY} 逗号\n",
               layer="knowledge")
        cg.flush()
        saved = reach._index(cg)
        saved.save()
        reloaded = reach.ReachIndex(root); reloaded.load()
        pth = [e["path"] for e in cg._candidates() if e["path"].endswith("comma,node.md")]
        ok(bool(pth) and pth[0] in reloaded.post.get("召回", []) + reloaded.post.get("召", []),
           "(7) 含逗号路径经落盘/重载仍在倒排中（_SEP 而非逗号）", f"path={pth}")
        fake_cg = type("X", (), {"index": {"nodes": {"n1": {"path": "knowledge/n1.md"}}}})()
        ok(reach._disk_fresh(saved, fake_cg) is False,
           "(7) content_hash 缺失 → 判不新鲜（触发重建）")
        os.environ["MDCG_REACH_TTL"] = "1"
        d = json.load(open(saved.path, encoding="utf-8"))
        d["built_at"] = time.time() - 30          # 让**磁盘缓存**过期（改内存对象无效）
        json.dump(d, open(saved.path, "w", encoding="utf-8"))
        reach._CACHE.clear()
        again = reach._index(cg)
        ok(getattr(again, "built_now", False) is True,
           "(7) 磁盘缓存超 TTL → 重建")
        os.environ["MDCG_REACH_TTL"] = "0"
        # ---------------- (8) 新节点并入（陈旧索引不漏召回） ----------------
        # 复用缓存时不得残留上一轮的首建标记
        again.built_now = True
        reach._CACHE[again.path] = (again, reach._fingerprint(cg))
        _, m_reuse = reach.narrow(cg, cg._candidates(), terms, qb, None, q=QUERY)
        ok("reach_build_docs" not in m_reuse, "(7) 复用缓存时不残留首建标记")

        # 未索引节点并入（path 不在 idx.hashes）
        cg.add("unindexed_node", "# 功能名：未索引\n# 生效条件：条件 U\n\n与查询无关。\n",
               layer="knowledge")
        cg.flush()
        reach._CACHE.clear()
        stale2 = reach.ReachIndex(root); stale2.load()
        ok(not any(p.endswith("unindexed_node.md") for p in stale2.hashes),
           "(8b) 前置：磁盘缓存里确无该节点")
        reach._CACHE[stale2.path] = (stale2, reach._fingerprint(cg))
        got3, meta3 = reach.narrow(cg, cg._candidates(), terms, qb, None, q=QUERY)
        # r8 复核：未索引节点超过上限时必须整段回退（不得静默截断后仍提前返回）
        saved_max = reach._FRESH_MAX
        reach._FRESH_MAX = 1
        cg.add("unindexed2", "# 功能名：未索引2\n# 生效条件：条件 U2\n\n与查询无关。\n", layer="knowledge")
        cg.flush()
        reach._CACHE.clear()
        st3 = reach.ReachIndex(root); st3.load()
        reach._CACHE[st3.path] = (st3, reach._fingerprint(cg))
        got4, meta4 = reach.narrow(cg, cg._candidates(), terms, qb, None, q=QUERY)
        reach._FRESH_MAX = saved_max
        ok(got4 is None and meta4.get("reach") == "fresh_overflow",
           "(8c) 未索引节点超过上限 → 整段回退（不静默截断）", str(meta4)[:80])

        # r8 复核：进程内缓存 TTL 过期也要重建（不清 _CACHE，改内存实例的 built_at）
        os.environ["MDCG_REACH_TTL"] = "1"
        live = reach._index(cg)
        live.built_at = time.time() - 30
        try:
            d2 = json.load(open(live.path, encoding="utf-8"))
            d2["built_at"] = time.time() - 30          # 磁盘缓存也过期 → 必须真重建
            json.dump(d2, open(live.path, "w", encoding="utf-8"))
        except OSError:
            pass
        got5, meta5 = reach.narrow(cg, cg._candidates(), terms, qb, None, q=QUERY)
        os.environ["MDCG_REACH_TTL"] = "0"
        ok(meta5.get("reach_build_docs") is not None,
           "(8d) 内存+磁盘缓存均超 TTL → 真重建（以 reach_build_docs 出现为准）", str(meta5)[:110])
        ok(meta3.get("reach_fresh_nodes", 0) >= 1,
           "(8b) 未索引节点被并入候选", f"fresh={meta3.get('reach_fresh_nodes')}")
        print(chr(10) + "(8) 新节点并入")
        cg.add("late_node", "# 功能名：后写节点\n# 生效条件：条件 L\n\n与查询无关的后写正文。\n",
               layer="knowledge")
        cg.flush()
        _env(True)
        # 强制「指纹比对通过但缓存里没有后写节点」的陈旧场景，验证并入机制
        stale = reach.ReachIndex(root); stale.load()
        reach._CACHE[stale.path] = (stale, reach._fingerprint(cg))
        got2, meta2 = reach.narrow(cg, cg._candidates(), terms, qb, None, q=QUERY)
        ids2 = {e["path"].split("/")[-1][:-3] for e in (got2 or [])}
        ok("late_node" in ids2 or meta2.get("reach_fresh_nodes", 0) > 0,
           "(8) 索引建成后写入的节点被并入候选", f"fresh={meta2.get('reach_fresh_nodes')}")
        print(f"\n===== reach 验收：{PASS}/{PASS + FAIL} 通过 =====")
        if FAILS:
            print("失败项：" + "；".join(FAILS))
        return 0 if FAIL == 0 else 1
    finally:
        _env(True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
