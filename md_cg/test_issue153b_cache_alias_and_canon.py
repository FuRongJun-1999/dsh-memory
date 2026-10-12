# -*- coding: utf-8 -*-
r"""#153①③ 守卫：缓存出口**别名污染** + `_canon` **混合类型键**。

缺陷形态（复现于 HEAD d29a8436，A/C 组在 HEAD 上应红）：
  ① 别名污染（返回内部可变对象）：
     · `md_cg/hotcache.py` 的 `get_query` 出口 `return results, dict(meta)`
       ——meta 浅拷贝了，`results` 给的是**缓存内部 list 的引用**；
     · `md_cg/bm25.py` 的 `candidate_pool` 命中分支 `return saved[3]`
       ——直接返回缓存内 list。
     调用方（检索后处理 / 排序 / 追加）任何原地修改都**写回缓存**，
     下一次命中即拿到被污染的「结果」——静默错答。
  ③ `_canon` 混合类型键：`MDCG_HOTCACHE=1` 时
     `cg.search_rrf('…', context={1: None, '1': (1, 2)})` 抛
     `TypeError: '<' not supported between instances of 'tuple' and 'NoneType'`
     （dict 分支按 (键, 值) 二元组排序，键相同则比到值）；且
     `_canon({1: 'x'}) == _canon({'1': 'x'})` 撞键（int 1 与 str '1' 都
     str 成 "1"）。

修法（本件）：
  · `hotcache.get_query` —— 出口逐行浅拷贝（行内 dict 亦拷贝）；
  · `bm25.candidate_pool` —— 返回 `_PoolEntries` 副本（携带池键，使
    `BM25Index.sync` 的池复用判定对拷贝透明）；
  · `hotcache._canon` —— dict 分支键片段改 `("k", type(k).__name__, str(k))`
    三元组消撞键，排序键只取片段（`key=lambda kv: kv[0]`，恒可比）。

判据组：
  A 别名污染：
      A1 `get_query` 两次命中返回的 results **不是同一对象**（`is` False）
      A2 对首次返回 append 后，再次命中**看不到**追加项（缓存未被污染）
      A3 对首次返回的行内 node dict 改名后，再次命中仍是原名
      A4 正对照：缓存**关闭**时同样 `is` False（行为一致，非缓存特例）
      A5 `bm25.candidate_pool` 两次命中返回的 list 不是同一对象
      A6 对 `candidate_pool` 返回 append 后，再次命中长度不变
  B 混合类型 context 不抛：
      B1 `search_rrf(context={1: None, '1': (1, 2)})` 不抛异常
      B2 `_canon` 对同一入参可复现（两次相等）
      B3 `_canon` 对含混合键的 dict 不抛
  C 消撞键：
      C1 `_canon({1: 'x'}) != _canon({'1': 'x'})`
      C2 `_canon({'a': 1}) != _canon([('a', 1)])`（dict 与 list-of-pairs 不撞）
      C3 `_canon` 仍稳定可复现（同入参两次相等）
  D 池复用不退化（拷贝不得让池复用失效）：
      D1 两次同查询 `bm25` meta 的 `pool_reused` 为真

定点变异（`--mutate=alias` / `--mutate=canon`，抽掉修复 ⇒ 对应断言必红）：
  alias：`get_query` 出口退回 `return results, dict(meta)`（给引用）
  canon：`_canon` dict 分支退回二元组 `(str(k), value)` 排序

用法：
  python -X utf8 -m md_cg.test_issue153b_cache_alias_and_canon
  python -X utf8 -m md_cg.test_issue153b_cache_alias_and_canon --mutate=alias
  python -X utf8 -m md_cg.test_issue153b_cache_alias_and_canon --mutate=canon
退出码：0 = 全绿；1 = 有失败。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

PASS = 0
FAIL = 0
FAILS = []

BODY = ("# 功能名：缓存别名对照\n# 生效条件：沙箱\n# 子功能：对照\n"
        "# 执行：查\n# 验证方式：守卫\n# 不适用条件：无\n共享词 正文\n")


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


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if sys.argv is not None else argv)
    mut = ""
    for a in argv:
        if a.startswith("--mutate="):
            mut = a.split("=", 1)[1]

    os.environ["MDCG_HOTCACHE"] = "1"
    from md_cg import bm25
    from md_cg import hotcache
    from md_cg.mdcos import MdCGOS

    _orig_get_query = hotcache.HotCache.get_query
    _orig_canon = hotcache.HotCache._canon

    if mut == "alias":
        # 等价注入：出口退回「给引用」版（meta 浅拷贝、results 原对象）
        def _ref_get_query(self, query, k=20, layer=None, session=None,
                           branch=None, validity=None, view=None, extra=None):
            key = self._query_key(query, k, layer, session, branch, validity,
                                  view, extra)
            entry = self._queries.get(key)
            if entry is None:
                self._stats["query_misses"] += 1
                return None
            _ts, results, meta = entry
            import time as _t
            if _t.time() - _ts > self._query_ttl:
                self._queries.pop(key, None)
                self._stats["query_misses"] += 1
                return None
            self._stats["query_hits"] += 1
            self._queries.move_to_end(key)
            return results, dict(meta)
        hotcache.HotCache.get_query = _ref_get_query
    elif mut == "canon":
        # 等价注入：dict 分支退回二元组 (str(k), canon(v)) 且按整元组排序
        def _old_canon(v):
            if isinstance(v, dict):
                return tuple(sorted((str(k), _orig_canon(x))
                                    for k, x in v.items()))
            return _orig_canon(v)
        hotcache.HotCache._canon = staticmethod(_old_canon)

    sb = tempfile.mkdtemp(prefix="iss153b_")
    sb2 = tempfile.mkdtemp(prefix="iss153b_off_")
    try:
        cg = MdCGOS(os.path.join(sb, "lib"), autoflush=1)
        for i in range(6):
            cg.add("n%d" % i, BODY, layer="knowledge", importance=0.4)
        hc = hotcache.get(cg)
        ok(hc is not None, "A0 MDCG_HOTCACHE=1 ⇒ 热缓存已挂")

        print("\n[A] 缓存出口不得返回内部可变对象（别名污染）")
        r1, m1 = cg.search_rrf("共享词", k=5)
        r2, m2 = cg.search_rrf("共享词", k=5)
        ok(m2.get("cached") is True, "A0b 第二次命中缓存（前置）", m2.get("cached"))
        ok(r1 is not r2, "A1 两次命中返回的 results 不是同一对象", r1 is r2)
        _n0 = len(r2)
        r1.append(("POLLUTED", 9.9, None, []))
        r3, _m3 = cg.search_rrf("共享词", k=5)
        ok(len(r3) == _n0 and all(str(x[0]) != "POLLUTED" for x in r3),
           "A2 append 不污染后续命中", (len(r3), _n0))
        _id0 = r3[0][0].get("id") if isinstance(r3[0][0], dict) else None
        r3[0][0]["id"] = "POLLUTED_ID"
        r4, _m4 = cg.search_rrf("共享词", k=5)
        _id1 = r4[0][0].get("id") if isinstance(r4[0][0], dict) else None
        ok(_id1 != "POLLUTED_ID", "A3 行内 node dict 改名不污染后续命中",
           (_id0, _id1))

        # A4 正对照：缓存关闭时同样 is False（行为一致）
        os.environ.pop("MDCG_HOTCACHE", None)
        cgoff = MdCGOS(os.path.join(sb2, "lib"), autoflush=1)
        for i in range(6):
            cgoff.add("n%d" % i, BODY, layer="knowledge", importance=0.4)
        s1, _ = cgoff.search_rrf("共享词", k=5)
        s2, _ = cgoff.search_rrf("共享词", k=5)
        ok(s1 is not s2, "A4 正对照：缓存关时同样 is False", s1 is s2)
        os.environ["MDCG_HOTCACHE"] = "1"

        # A5/A6：bm25 候选池
        cg.add("bm1", BODY + " bm25term\n", layer="knowledge", importance=0.4)
        cg.add("bm2", BODY + " bm25term\n", layer="knowledge", importance=0.4)
        p1 = bm25.candidate_pool(cg)
        p2 = bm25.candidate_pool(cg)
        ok(p1 is not p2, "A5 candidate_pool 两次命中返回不同对象", p1 is p2)
        _l0 = len(p2)
        p1.append({"path": "POLLUTED.md"})
        p3 = bm25.candidate_pool(cg)
        ok(len(p3) == _l0, "A6 append 不污染候选池缓存", (len(p3), _l0))

        print("\n[B] 混合类型 context 不抛异常")
        err = None
        try:
            cg.search_rrf("共享词", k=5, context={1: None, "1": (1, 2)})
        except Exception as exc:                     # noqa: BLE001
            err = "%s: %s" % (type(exc).__name__, exc)
        ok(err is None, "B1 search_rrf 混合类型 context 不抛异常", err)

        def _safe_canon(v):
            try:
                return hotcache.HotCache._canon(v), None
            except Exception as exc:                 # noqa: BLE001
                return None, "%s: %s" % (type(exc).__name__, exc)

        _c1, _e1 = _safe_canon({1: None, "1": (1, 2)})
        _c2, _e2 = _safe_canon({1: None, "1": (1, 2)})
        ok(_e1 is None and _c1 == _c2, "B2 _canon 对同一入参可复现（且不抛）",
           (_e1, _e2))
        _c3, _e3 = _safe_canon({1: "x", "1": (1, 2), 2: None})
        ok(_e3 is None, "B3 _canon 含混合键 dict 不抛", _e3)

        print("\n[C] 消撞键")
        _ci, _ei = _safe_canon({1: "x"})
        _cs, _es = _safe_canon({"1": "x"})
        ok(_ei is None and _es is None and _ci != _cs,
           "C1 int 键 1 与 str 键 '1' 不撞", (_ci, _cs))
        _cd, _ed = _safe_canon({"a": 1})
        _cl, _el = _safe_canon([("a", 1)])
        ok(_ed is None and _el is None and _cd != _cl,
           "C2 dict 与 list-of-pairs 不撞")
        _ca, _ea = _safe_canon({"a": 1, "b": 2})
        _cb, _eb = _safe_canon({"b": 2, "a": 1})
        ok(_ea is None and _eb is None and _ca == _cb,
           "C3 _canon 稳定可复现（键序无关）")

        print("\n[D] 池复用不退化（拷贝不得让池复用失效）")
        cg.add("bm3", BODY + " poolterm\n", layer="knowledge", importance=0.4)
        # 注意：必须**绕开 query 热缓存**才测得到 bm25 池复用——同参数同查询
        # 第二次会直接命中 query 缓存（meta 整份复用，含上一轮的 bm25 报告），
        # 根本走不到 `BM25Index.sync`。故两次用**不同 k**（k 进 query 缓存键、
        # 不进候选池键 ⇒ 候选池仍应复用）。
        _a, ma = cg.search_rrf("poolterm", k=5, paths=("bm25",))
        _b, mb = cg.search_rrf("poolterm", k=6, paths=("bm25",))
        ok(bool((mb.get("bm25") or {}).get("pool_reused")) is True,
           "D1 同池不同 k 的第二次查询 bm25 池复用为真",
           (ma.get("bm25") or {}).get("pool_reused",
                                      mb.get("bm25") or {}))
    finally:
        hotcache.HotCache.get_query = _orig_get_query
        hotcache.HotCache._canon = _orig_canon
        for _d in (sb, sb2):
            shutil.rmtree(_d, ignore_errors=True)

    print("\n通过 %d / 失败 %d%s"
          % (PASS, FAIL, ("（变异=%s）" % mut) if mut else ""))
    for f in FAILS:
        print(" - 红：%s" % f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
