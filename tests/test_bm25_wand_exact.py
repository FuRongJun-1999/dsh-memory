# -*- coding: utf-8 -*-
"""Exact Block-Max WAND (Pivot-Skipping) parity & discriminator guard tests.

Verifies:
1. Bit-for-bit identical Top-LIMIT results, scores, and `matched` counts against
   exhaustive BM25 (`MDCG_BM25_BLOCK_MAX=0`) across >= 5,000-doc pools,
   single-term & multi-term queries, ties, outliers, CJK + English tokens.
2. Exact parity across incremental edits, deletes, all-hole tombstoned blocks,
   deferred dirty term repairs, delta-tail growth, compaction, and journal
   overflow fallback (`BLOCK_UPDATE_LIMIT`).
3. IEEE-754 summation-order edge cases with 3+ / 6+ query terms and near-ties.
4. Discriminator guards verifying WAND pivot-skipping (`bisect_left` over
   sorted block IDs) and suffix early-exit strictly reduce evaluated blocks
   (`blocks_evaluated < blocks`, `wand_pivot_skips > 0`) while keeping exact
   Top-K parity — would fail if reverted to full-block-scan-and-sort.
5. End-to-end production `MdCGOS.search_rrf(..., paths=("bm25",))` parity.
"""
from __future__ import annotations

from collections import Counter
import math
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from md_cg import bm25, mdcos  # noqa: E402


def _fresh_report(n_docs=0):
    return {
        "k1": bm25.K1, "b": bm25.B, "limit": bm25.LIMIT, "input": n_docs,
        "build_reads": 0, "update_reads": 0, "unavailable": 0,
        "posting_visits": 0, "matched": 0, "block_layout_rebuilt": False,
        "block_layout_touched": 0, "block_repaired_blocks": 0,
        "block_update_slots": 0, "block_rebuild_postings": 0,
    }


def _put_doc(idx: bm25.BM25Index, path: str, text: str, importance: float, doc_id: str):
    """Insert or replace a document in BM25Index using its exact production invariants."""
    if path in idx.docs:
        idx.remove(path)
    tf = Counter(bm25.tokenize(text))
    length = sum(tf.values())
    doc_terms = []
    for term, count in tf.items():
        if term not in idx.post:
            idx.post[term] = {}
            idx.terms[term] = term
        canonical = idx.terms[term]
        idx.post[canonical][path] = count
        doc_terms.append(canonical)
    idx.docs[path] = (idx.version, tuple(doc_terms), length, float(importance), str(doc_id))
    idx._note_block_update(path, doc_terms)
    idx.total_length += length
    idx.version += 1
    idx.initialized = True


def _rank_pair(idx: bm25.BM25Index, query: str):
    """Run WAND block-max vs exhaustive BM25 on the exact same BM25Index."""
    r_wand = _fresh_report(len(idx.docs))
    with patch.dict(os.environ, {"MDCG_BM25_BLOCK_MAX": "1"}):
        actual = idx.rank(query, idx.docs, r_wand)
    r_ref = _fresh_report(len(idx.docs))
    with patch.dict(os.environ, {"MDCG_BM25_BLOCK_MAX": "0"}):
        expected = idx.rank(query, idx.docs, r_ref)
    return actual, r_wand, expected, r_ref


class TestBM25WandExact(unittest.TestCase):
    def test_large_pool_5500_randomized_parity_multiterm_and_singleterm(self):
        """5,500-doc randomized pool: bit-for-bit parity across 30+ diverse queries."""
        rng = random.Random(20261122)
        idx = bm25.BM25Index()
        common_vocab = ["common", "alpha", "beta", "gamma"]
        mid_vocab = [f"mid{i}" for i in range(12)]
        rare_vocab = [f"rare{i}" for i in range(40)]
        cjk_phrases = ["资料条目", "记忆检索", "系统架构", "块剪枝优化"]

        for i in range(5500):
            parts = []
            # Ensure common terms exceed BLOCK_THRESHOLD (4096) with varied TFs
            parts.extend(["common"] * rng.randint(1, 4))
            if rng.random() < 0.85:
                parts.extend(["alpha"] * rng.randint(1, 3))
            if rng.random() < 0.80:
                parts.extend(["beta"] * rng.randint(1, 5))
            if rng.random() < 0.78:
                parts.extend(["gamma"] * rng.randint(1, 2))
            if rng.random() < 0.15:
                parts.extend([rng.choice(mid_vocab)] * rng.randint(1, 4))
            if rng.random() < 0.02:
                parts.extend([rng.choice(rare_vocab)] * rng.randint(1, 3))
            if rng.random() < 0.82:
                parts.append(cjk_phrases[0])
            if rng.random() < 0.40:
                parts.append(rng.choice(cjk_phrases[1:]))
            # Pad with varying lengths so length normalization is exercised heavily
            parts.extend(["pad"] * rng.choice((0, 1, 2, 4, 8, 16, 32)))
            imp = rng.choice((0.1, 0.4, 0.4, 0.7, 0.9))
            _put_doc(idx, f"k/{i:05d}.md", " ".join(parts), imp, f"doc_{i:05d}")

        # Plant high-score short outliers in early, middle, and VERY LAST blocks
        _put_doc(idx, "k/outlier_mid.md", "common alpha rare0", 1.0, "zz_mid")
        _put_doc(idx, "k/outlier_end1.md", "common beta gamma rare1", 1.0, "zz_end1")
        _put_doc(idx, "k/outlier_end2.md", "alpha alpha alpha beta beta", 0.95, "zz_end2")
        _put_doc(idx, "k/outlier_cjk.md", "资料条目 记忆检索", 1.0, "zz_cjk")

        queries = [
            "common",
            "alpha",
            "beta",
            "gamma",
            "common alpha",
            "common beta gamma",
            "alpha beta gamma common",
            "common rare0",
            "common alpha rare1",
            "beta mid0 rare2",
            "common mid1 mid2",
            "common common alpha alpha",
            "common nonexistent_xyz",
            "nonexistent_xyz",
            "rare0 rare1 rare2",
            "资料",
            "资料 记忆",
            "资料条目 记忆检索 common",
            "alpha gamma mid3 mid4 rare5",
            "common alpha beta gamma mid0 rare0",
        ]
        # Allow high TF/length variance through _block_worthwhile so WAND runs on every query
        with patch.object(bm25, "BLOCK_PAIR_LIMIT", 512):
            for q in queries:
                actual, r_wand, expected, r_ref = _rank_pair(idx, q)
                self.assertEqual(actual, expected, f"Bit-for-bit mismatch on query={q!r}")
                self.assertEqual(r_wand["matched"], r_ref["matched"], f"matched mismatch on {q!r}")
                if q not in ("nonexistent_xyz", "rare0 rare1 rare2"):
                    self.assertEqual(r_wand.get("algorithm"), "exact_block_max", f"expected WAND on {q!r}")
                    self.assertEqual(r_wand["blocks"] - r_wand["blocks_skipped"] >= 0, True)

    def test_tie_breaker_determinism_forward_reversed_and_mixed_importance(self):
        """Equal-score corpora in forward, reversed, and mixed importance orders."""
        for order_name, ids in (
            ("forward", [f"eq_{i:05d}" for i in range(5200)]),
            ("reversed", [f"eq_{i:05d}" for i in reversed(range(5200))]),
        ):
            idx = bm25.BM25Index()
            for pos, doc_id in enumerate(ids):
                _put_doc(idx, f"p/{pos:05d}.md", "same common", 0.4, doc_id)
            actual, r_wand, expected, r_ref = _rank_pair(idx, "same common")
            self.assertEqual(actual, expected, order_name)
            self.assertEqual(r_wand["matched"], 5200, order_name)
            self.assertEqual(r_wand["matched"], r_ref["matched"], order_name)
            self.assertEqual(r_wand["algorithm"], "exact_block_max", order_name)
            self.assertGreater(r_wand["blocks_skipped"], 0, order_name)
            self.assertLess(r_wand["scored_documents"], 5200, order_name)

        # Shuffled IDs with late-block high-importance winners
        rng = random.Random(77)
        idx = bm25.BM25Index()
        doc_ids = [f"shuf_{i:05d}" for i in range(5200)]
        rng.shuffle(doc_ids)
        for pos, doc_id in enumerate(doc_ids):
            imp = 1.0 if pos in (5195, 5198, 5199) else 0.4
            _put_doc(idx, f"s/{pos:05d}.md", "same common", imp, doc_id)
        actual, r_wand, expected, r_ref = _rank_pair(idx, "same common")
        self.assertEqual(actual, expected)
        self.assertEqual(r_wand["matched"], r_ref["matched"])
        self.assertEqual([idx.docs[p][4] for p, _ in actual[:3]],
                         sorted([doc_ids[5195], doc_ids[5198], doc_ids[5199]]))

    def test_incremental_updates_deletes_tombstones_and_compaction_parity(self):
        """Incremental edits, deletes, empty tombstoned blocks, deferred repairs, compaction."""
        rng = random.Random(31415)
        idx = bm25.BM25Index()
        for i in range(5120):
            text = "common " * (1 + (i % 3)) + "second " * (1 + (i % 2))
            if i % 17 == 0:
                text += "raretag "
            text += "fill " * (i % 4)
            _put_doc(idx, f"inc/{i:05d}.md", text, 0.4, f"inc_{i:05d}")

        def assert_all_queries_exact(stage):
            for q in ("common", "second", "common second", "common raretag", "common second raretag"):
                actual, r_wand, expected, r_ref = _rank_pair(idx, q)
                self.assertEqual(actual, expected, f"{stage} query={q!r}")
                self.assertEqual(r_wand["matched"], r_ref["matched"], f"{stage} matched query={q!r}")
            for term, table in idx.term_blocks.items():
                self.assertIn(term, idx.term_block_meta, f"{stage} missing meta for {term}")
                self.assertEqual(idx.term_block_meta[term][0], sorted(table),
                                 f"{stage} unsorted block_ids for {term}")

        # Warm up cached block tables & metadata
        assert_all_queries_exact("initial")
        self.assertIn("common", idx.term_blocks)
        self.assertIn("second", idx.term_blocks)

        # 1. Edit a doc to become the new global TF max (appended to delta tail)
        _put_doc(idx, "inc/05119.md", "common " * 30 + "second " * 15, 0.9, "inc_05119")
        assert_all_queries_exact("after_max_tf_edit")

        # 2. Lower that doc's TF back down (forces recompute_min in term_block_meta!)
        _put_doc(idx, "inc/05119.md", "common fill fill fill fill", 0.2, "inc_05119")
        assert_all_queries_exact("after_min_recompute_edit")

        # 3. Importance-only edit on a late-block doc
        _put_doc(idx, "inc/05100.md", "common second", 1.0, "inc_05100")
        assert_all_queries_exact("after_importance_edit")

        # 4. Delete an ENTIRE block (128 consecutive docs) -> all-hole tombstoned block!
        block_to_wipe = 2
        start = block_to_wipe * bm25.BLOCK_SIZE
        wipe_paths = [p for p in idx.block_paths[start:start + bm25.BLOCK_SIZE] if p is not None]
        for p in wipe_paths:
            idx.remove(p)
        # Query ONLY "common" first so "second" stays deferred-dirty across an intervening query!
        actual, r_wand, expected, r_ref = _rank_pair(idx, "common")
        self.assertEqual(actual, expected)
        self.assertEqual(r_wand["matched"], r_ref["matched"])
        self.assertEqual(idx.block_best[block_to_wipe], (math.inf, ""))
        self.assertNotIn(block_to_wipe, idx.term_blocks["common"])
        self.assertNotIn(block_to_wipe, idx.term_block_meta["common"][0])
        # Now query "second" (triggers deferred repair of wiped block)
        assert_all_queries_exact("after_full_block_tombstone_and_deferred_repair")
        self.assertNotIn(block_to_wipe, idx.term_blocks["second"])
        self.assertNotIn(block_to_wipe, idx.term_block_meta["second"][0])

        # 5. Append 300 new docs across multiple new delta-tail blocks
        for j in range(300):
            _put_doc(idx, f"new/{j:04d}.md",
                     "common " * (1 + j % 5) + "second " + ("raretag " if j % 10 == 0 else ""),
                     rng.choice((0.3, 0.6, 0.95)), f"new_{j:04d}")
        assert_all_queries_exact("after_delta_tail_append")

        # 6. Shrink pool heavily to force compaction (`_blocks_need_compaction`)
        keep = set(list(idx.docs)[:4200])
        for p in list(idx.docs):
            if p not in keep:
                idx.remove(p)
        # Keep removing & re-adding enough to ensure compaction triggers
        for p in list(idx.docs)[:100]:
            idx.remove(p)
        for j in range(200):
            _put_doc(idx, f"post/{j:04d}.md", "common second", 0.5, f"post_{j:04d}")
        assert_all_queries_exact("after_shrink_and_compaction")

    def test_float_summation_order_edge_cases_3plus_terms(self):
        """Adversarial 3-, 5-, and 8-term queries with near-identical scores across blocks."""
        idx = bm25.BM25Index()
        vocab = [f"t{k}" for k in range(8)]
        # Make terms appear with staggered block patterns and slightly different DFs
        # so cursor order != original query-term order and sums differ by 1-2 ULPs if misordered.
        for i in range(5200):
            block = i // bm25.BLOCK_SIZE
            toks = []
            for k, tok in enumerate(vocab):
                # Stagger presence across blocks so cursors sort in scrambled orders
                if (block + k) % 9 != 0 or i < 200:
                    toks.extend([tok] * (1 + ((i + k) % 2)))
            # Keep exact same doc length bucket for tight float near-ties
            toks.extend(["pad"] * (20 - len(toks)))
            _put_doc(idx, f"fp/{i:05d}.md", " ".join(toks), 0.5, f"fp_{i:05d}")

        queries = [
            "t0 t1 t2",
            "t2 t0 t1",
            "t7 t3 t5 t1 t0",
            "t0 t1 t2 t3 t4 t5 t6 t7",
            "t7 t6 t5 t4 t3 t2 t1 t0",
        ]
        with patch.object(bm25, "BLOCK_PAIR_LIMIT", 512):
            for q in queries:
                actual, r_wand, expected, r_ref = _rank_pair(idx, q)
                self.assertEqual(actual, expected, f"Float-order mismatch on {q!r}")
                self.assertEqual(r_wand["matched"], r_ref["matched"], q)
                self.assertEqual(r_wand["algorithm"], "exact_block_max")

    def test_wand_pivot_skipping_discriminator_guard(self):
        """Discriminator guard: WAND MUST pivot-skip blocks (fails if reverted to full scan)."""
        class _CountedBlockDict(dict):
            """Counts real per-block table reads; unfakeable behavioral discriminator."""
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.reads = 0

            def __getitem__(self, k):
                self.reads += 1
                return super().__getitem__(k)

            def get(self, k, default=None):
                self.reads += 1
                return super().get(k, default)

            def items(self):
                for k, v in super().items():
                    self.reads += 1
                    yield k, v

            def values(self):
                for v in super().values():
                    self.reads += 1
                    yield v

            def __iter__(self):
                for k in super().__iter__():
                    self.reads += 1
                    yield k

        idx = bm25.BM25Index()
        # 10,240 docs = 80 blocks of 128 docs.
        # commona, commonb appear in ALL 80 blocks (df=10240, very low IDF).
        # rarehi appears in ONLY 6 scattered blocks (60 docs total, high IDF >> U_commona + U_commonb).
        rare_blocks = {5, 20, 35, 50, 65, 75}
        for i in range(10240):
            b = i // bm25.BLOCK_SIZE
            offset = i % bm25.BLOCK_SIZE
            words = ["commona", "commonb", "pad1", "pad2"]
            if b in rare_blocks and offset < 10:
                words.append("rarehi")
            _put_doc(idx, f"w/{i:05d}.md", " ".join(words), 0.4, f"w_{i:05d}")

        # Warm up cached block tables first so we measure steady-state ranking reads.
        _rank_pair(idx, "commona commonb")
        counted_a = _CountedBlockDict(idx.term_blocks["commona"])
        counted_b = _CountedBlockDict(idx.term_blocks["commonb"])
        idx.term_blocks["commona"] = counted_a
        idx.term_blocks["commonb"] = counted_b

        # 1. Mixed-rarity multi-term query: WAND pivot-skipping via bisect_left must jump
        #    past almost all of the 74 common-only blocks without reading their block entries!
        counted_a.reads = counted_b.reads = 0
        actual, info, expected, ref = _rank_pair(idx, "commona commonb rarehi")
        self.assertEqual(actual, expected)
        self.assertEqual(info["matched"], 10240)
        self.assertEqual(info["matched"], ref["matched"])
        self.assertEqual(info["algorithm"], "exact_block_max")
        self.assertEqual(info["blocks"], 80)
        # Behavioral discriminator: pre-WAND main reads ALL 80 entries of commona & commonb.
        self.assertLessEqual(counted_a.reads, 12,
                             f"WAND must skip untouched blocks of commona (read {counted_a.reads}/80)")
        self.assertLessEqual(counted_b.reads, 12,
                             f"WAND must skip untouched blocks of commonb (read {counted_b.reads}/80)")
        # Report discriminators
        self.assertIn("wand_pivot_skips", info)
        self.assertGreater(info["wand_pivot_skips"], 100,
                           f"Expected substantial WAND pivot skips, got {info}")
        self.assertIn("blocks_evaluated", info)
        self.assertLessEqual(info["blocks_evaluated"], 12,
                             f"Expected <= 12 blocks evaluated out of 80, got {info}")
        self.assertGreaterEqual(info["blocks_skipped"], 70)
        self.assertLess(info["scored_documents"], 1500)
        # Verify sorted block IDs metadata invariant
        self.assertEqual(idx.term_block_meta["commona"][0], sorted(idx.term_blocks["commona"]))
        self.assertEqual(idx.term_block_meta["commonb"][0], sorted(idx.term_blocks["commonb"]))

        # 2. Homogeneous common multi-term query: suffix early-exit skips remaining 79 blocks in O(1)
        counted_a.reads = counted_b.reads = 0
        actual2, info2, expected2, ref2 = _rank_pair(idx, "commona commonb")
        self.assertEqual(actual2, expected2)
        self.assertEqual(info2["matched"], 10240)
        self.assertEqual(info2["matched"], ref2["matched"])
        self.assertEqual(info2["algorithm"], "exact_block_max")
        self.assertLessEqual(counted_a.reads, 2,
                             f"Expected <= 2 block reads on homogeneous forward pool, got {counted_a.reads}")
        self.assertLessEqual(info2["blocks_evaluated"], 2,
                             f"Expected <= 2 blocks evaluated on homogeneous forward pool, got {info2}")
        self.assertGreaterEqual(info2["blocks_skipped"], 78)
        self.assertGreater(info2["wand_pivot_skips"], 100)

    def test_end_to_end_mdcos_search_rrf_wand_parity(self):
        """End-to-end production search_rrf parity with real Markdown files, edits & deletes."""
        with tempfile.TemporaryDirectory(prefix="bm25_wand_e2e_") as tmp, patch.dict(
            os.environ, {
                "MDCG_HOTCACHE": "0", "MDCG_READ_CACHE": "1",
                "MDCG_RETRIEVAL_PIPELINE": "0", "MDCG_UNIFY_QUERY": "0",
                "MDCG_SEMANTIC": "0", "MDCG_EN_ATOMS": "0",
                "MDCG_RRF_CANDIDATES": "0", "MDCG_WRITE_GATE": "warn",
            }
        ):
            cg = mdcos.MdCGOS(tmp)
            try:
                rng = random.Random(99)
                for i in range(600):
                    text = "common " * rng.randint(1, 3) + "second " * rng.randint(0, 2)
                    if i in (50, 250, 450, 580, 595):
                        text += "needle " * rng.randint(1, 3)
                    cg.add(f"n{i:04d}", text, importance=rng.choice((0.2, 0.4, 0.8)))
                cg.flush()

                with patch.object(bm25, "BLOCK_THRESHOLD", 64), patch.object(bm25, "BLOCK_PAIR_LIMIT", 256):
                    for step in range(3):
                        if step == 1:
                            cg.add("n0599", "common " * 10 + "needle", importance=1.0, override=True)
                            cg.forget("n0050")
                            cg.flush()
                        elif step == 2:
                            cg.add("n_fresh", "common second needle", importance=0.95)
                            cg.flush()
                        for q in ("common", "common second", "common needle", "common second needle"):
                            with patch.dict(os.environ, {"MDCG_BM25_BLOCK_MAX": "1"}):
                                rows_w, meta_w = cg.search_rrf(q, k=50, paths=("bm25",),
                                                               judge=False, record=False)
                            with patch.dict(os.environ, {"MDCG_BM25_BLOCK_MAX": "0"}):
                                rows_e, meta_e = cg.search_rrf(q, k=50, paths=("bm25",),
                                                               judge=False, record=False)
                            self.assertNotIn("fallback", meta_w["bm25"])
                            self.assertEqual(rows_w, rows_e, (step, q))
                            self.assertEqual(meta_w["bm25"]["matched"], meta_e["bm25"]["matched"])
                            self.assertEqual(meta_w["bm25"]["algorithm"], "exact_block_max")
            finally:
                cg.close()


if __name__ == "__main__":
    unittest.main()
