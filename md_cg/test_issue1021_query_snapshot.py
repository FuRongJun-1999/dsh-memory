# -*- coding: utf-8 -*-
"""Regression guard for #1021: _LayerBigramIndex.query must not iterate live structures.

The b&b query used to iterate the live posting set (`for nid in plist`) and index
`docs[nid]` directly. A concurrent `sync()` on another thread does
`p.add(nid)` / `p.discard(nid)` and `self._remove_doc(nid)`, which surfaces as
`RuntimeError: Set changed size during iteration` or `KeyError` inside `redundancy()`.

These guards reproduce both shapes **deterministically** (no sleeps, no threads):
  G1 snapshot     - a doc whose len() mutates every posting set (what sync does)
                    must not make the iteration explode
  G2 missing doc  - a doc removed mid-query must be skipped, not KeyError
  G3 parity       - the interfered query returns the same verdict as the clean one
"""
from __future__ import annotations

import os
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import forgetting  # noqa: E402
from md_cg.mdcg import MdCG  # noqa: E402

PASS = 0
FAIL = 0
FAILS = []

COMMON = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥"
BODY = (
    "# 功能名：{n}\n"
    "# 生效条件：t\n"
    "# 子功能：s\n"
    "# 执行：{t}\n"
    "# 验证方式：t\n"
    "# 不适用条件：无\n"
)


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS " + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL " + name + "  " + str(detail)[:260])
    return bool(cond)


def _build(root, n=20):
    cg = MdCG(root, autoflush=100000, async_flush=False)
    for i in range(n):
        cg.add("ctx_%02d" % i, BODY.format(n="n%d" % i, t=COMMON + "尾%d" % i),
               layer="contextual", tags=["t"], importance=0.4, verification_basis="test")
    forgetting.redundancy(cg, COMMON + "尾1", layer="contextual")
    return cg, cg._forgetting_bigram_index.layers["contextual"]


def test_snapshot_survives_concurrent_posting_mutation():
    print("== G1: posting-set mutation during query ==")
    cg, idx = _build(tempfile.mkdtemp(prefix="iss1021_g1_"))
    baseline, _ = idx.query(forgetting.bigrams(COMMON), exclude=None)

    state = {"n": 0}

    class _SyncLikeSet(set):
        """len() 时模拟另一线程 sync()：往所有 posting 集合里增删元素。"""

        def __len__(self):
            state["n"] += 1
            if state["n"] == 1:
                for p in list(idx.postings.values()):
                    p.add("intruder")
            return super().__len__()

    for nid in list(idx.docs.keys()):
        idx.docs[nid] = _SyncLikeSet(idx.docs[nid])

    raised = None
    try:
        got, _stats = idx.query(forgetting.bigrams(COMMON), exclude=None)
    except BaseException as exc:  # noqa: BLE001
        raised = exc
        got = None
    check("G1a query does not raise RuntimeError when postings change under it",
          raised is None, repr(raised))
    check("G1b interfered query returns the same verdict as the clean run",
          got is not None and got.get("with") == baseline.get("with")
          and abs(float(got.get("max") or 0) - float(baseline.get("max") or 0)) < 1e-12,
          (got, baseline))
    cg.close()


def test_doc_removed_mid_query_is_skipped():
    print("== G2: doc removed mid-query must be skipped, not KeyError ==")
    cg, idx = _build(tempfile.mkdtemp(prefix="iss1021_g2_"))
    baseline, _ = idx.query(forgetting.bigrams(COMMON), exclude=None)
    victim = sorted(idx.docs.keys())[-1]
    state = {"n": 0}

    class _RemovingSet(set):
        """len() 时模拟另一线程 _remove_doc：把同层另一篇文档从索引里摘掉。"""

        def __len__(self):
            state["n"] += 1
            if state["n"] == 1 and victim in idx.docs:
                idx.docs.pop(victim, None)
                idx.doc_pos.pop(victim, None)
            return super().__len__()

    for nid in list(idx.docs.keys()):
        idx.docs[nid] = _RemovingSet(idx.docs[nid])

    raised = None
    try:
        got, _stats = idx.query(forgetting.bigrams(COMMON), exclude=None)
    except BaseException as exc:  # noqa: BLE001
        raised = exc
        got = None
    check("G2a missing doc during query does not raise KeyError",
          raised is None, repr(raised))
    check("G2b removed doc is never reported as the winner",
          got is not None and got.get("with") != victim,
          (got, victim))
    check("G2c the surviving result matches the clean run when the victim was not the winner",
          got is not None and (baseline.get("with") == victim
                               or got.get("with") == baseline.get("with")),
          (got, baseline, victim))
    cg.close()


def main():
    test_snapshot_survives_concurrent_posting_mutation()
    test_doc_removed_mid_query_is_skipped()
    print("")
    print("== summary: %d pass / %d fail ==" % (PASS, FAIL))
    for f in FAILS:
        print("  FAILED: " + f)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())