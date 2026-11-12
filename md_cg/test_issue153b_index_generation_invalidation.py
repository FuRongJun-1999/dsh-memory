# -*- coding: utf-8 -*-
r"""#153b 守卫：索引突变 ⇒ 查询缓存按**代际**失配（正确性），且**不全清**（性能）。

口径取证（不猜）：mdcos.py:1746-1748 的 P1b-2 注释自陈「旧索引代里缓存的命中结果对
新写入不可见（**静默错答**）」；hotcache 的 query 键（hotcache._query_key）原本**不含**
任何索引代际；而 mdcos.py:721-728 记载热缓存**默认关**（env 未设 → get(self) 恒 None），
MDCG_HOTCACHE=1 才挂 ⇒ 本守卫必须在启用态取判据。

判据：
  A1 写后读不陈旧：先查（填缓存）→ 写新节点 → 再查 ⇒ 必须看得见新节点
  A2 代际进键：仅推进代际（不改内容）后，同一查询必须**不命中**（代际已进键）
  A3 **禁全清**：索引突变后，其他查询的缓存条目仍在（不得 clear/全清 query）
  A4 命中率不退化：100 次同查询 + 10 次写 ⇒ query_hits 保持高位（≥80）
运行：
  python -X utf8 -m md_cg.test_issue153b_index_generation_invalidation
  python -X utf8 -m md_cg.test_issue153b_index_generation_invalidation --mutate=nofix
  python -X utf8 -m md_cg.test_issue153b_index_generation_invalidation --mutate=harsh
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

PASS = 0
FAIL = 0
FAILS = []


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", label,
                           ("  · " + str(detail)) if detail else ""))
    return bool(cond)


def _ids(r):
    out = set()
    for x in r:
        while isinstance(x, (list, tuple)) and x:
            x = x[0]
        if hasattr(x, "get") and isinstance(x.get("id"), str):
            out.add(x["id"])
    return sorted(out)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    mut = ""
    for a in argv:
        if a.startswith("--mutate="):
            mut = a.split("=", 1)[1]
    os.environ["MDCG_HOTCACHE"] = "1"      # 默认关，本守卫须在启用态取判据
    from md_cg import mdcg as _M
    from md_cg import hotcache
    from md_cg.mdcos import MdCGOS
    if mut == "nofix":                     # 等价注入：退回「不经单点、代际恒 0」
        MdCGOS._set_index_entry = _M.MdCG._set_index_entry
        MdCGOS._index_generation = lambda self: 0
    sb = tempfile.mkdtemp(prefix="iss153b_")
    try:
        root = os.path.join(sb, "lib"); os.makedirs(root, exist_ok=True)
        cg = MdCGOS(root, autoflush=1)
        hc = hotcache.get(cg)
        ok(hc is not None, "A0 MDCG_HOTCACHE=1 ⇒ 热缓存已挂")
        # 缓存读侧入口是 search_rrf（mdcos.py:1746-1780 的命中逻辑在其内）；
        # search() 不经热缓存 —— 用错入口会得到「零命中」的假读数。
        _q = getattr(cg, "search_rrf", None) or cg.search

        def Q(s, k=50):
            return _q(s, k=k)
        if mut == "harsh":                 # 违反硬约束的注入：每次索引突变**全清**
            def _harsh(self, node_id=None):
                self._index_gen = self._index_generation() + 1
                hc.clear()
                return self._index_gen
            MdCGOS._on_index_mutation = _harsh

        def W(nid):
            cg.add(nid, "---\nid: %s\nlayer: knowledge\nverification_basis: test\n---\n%s PASSED\n" % (nid, nid), layer="knowledge")

        W("a")
        r1, _ = Q("PASSED")
        ok(_ids(r1) == ["a"], "A1a 首查见 a（此时填缓存）", _ids(r1))
        W("b")
        r2, _ = Q("PASSED")
        ok("b" in _ids(r2), "A1 写后读不陈旧：新写入可见（无静默错答）", _ids(r2))

        st0 = hc.stats()
        r3, _ = Q("PASSED")          # 同代重复查询 ⇒ 应命中
        st1 = hc.stats()
        ok(st1["query_hits"] > st0["query_hits"],
           "A2a 同代重复查询命中（代际未变 ⇒ 命中率不受损）",
           (st0["query_hits"], st1["query_hits"]))
        before_miss = st1["query_misses"]
        cg._on_index_mutation(None)                # 仅推进代际，不改内容
        r4, _ = Q("PASSED")
        st2 = hc.stats()
        ok(st2["query_misses"] > before_miss,
           "A2 代际进键：推进代际后同一查询**不再命中**",
           (before_miss, st2["query_misses"]))

        cg2_q = "PASSED"
        _r, _ = Q("BBB")             # 另一个查询填缓存
        n_before = len(hc._queries)
        W("c")
        n_after = len(hc._queries)
        ok(n_after >= n_before,
           "A3 禁全清：索引突变后 query 缓存条目未被清空",
           (n_before, n_after))

        h0 = hc.stats()["query_hits"]
        for i in range(10):
            W("w%d" % i)
        for i in range(100):
            Q("PASSED")
        h1 = hc.stats()["query_hits"]
        ok((h1 - h0) >= 80, "A4 命中率不退化：100 次同查询 + 10 次写 ⇒ 新增命中 ≥80",
           (h0, h1))
        # A5 登记纪律（仿 test_i32_hotcache_env_key 的 K1）：清单真源必须登记 index_gen，
        # 否则下一个人看不出该键承重（键用整份 extra ⇒ 漏登不影响正确性、影响可读性）。
        _ke = hotcache._KEYED_EXTRA
        if mut == "unreg":
            _ke = tuple(x for x in _ke if x != "index_gen")
        ok("index_gen" in _ke, "A5 _KEYED_EXTRA 登记 index_gen（清单真源，防漏登）",
           len(_ke))
    finally:
        shutil.rmtree(sb, ignore_errors=True)
    print("\nissue153b: %d pass / %d fail%s"
          % (PASS, FAIL, ("（变异=%s）" % mut) if mut else ""))
    for f in FAILS:
        print(" - 红：%s" % f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())