"""Incremental block maintenance against cold, exhaustive production BM25."""
import os
import random
import unittest
from unittest.mock import patch

from . import bm25
from . import test_bm25 as base_tests


class IncrementalBlockTests(unittest.TestCase):
    setUp = base_tests.BM25Tests.setUp
    tearDown = base_tests.BM25Tests.tearDown

    def populate(self, count=520):
        for i in range(count):
            self.cg.add(f"local{i:04d}", "common second " + "padding " * (i % 5),
                        importance=0.4)
        self.cg.flush()

    def raw(self, query, entries=None):
        if entries is None:
            entries = self.cg._candidates()
        rows, info = bm25.search(self.cg, query, entries, {"scanned": 0})
        self.assertNotIn("fallback", info)
        self.assertEqual(info["unavailable"], 0)
        return rows, info

    def exact(self, query, actual, info, entries=None):
        # A fresh index cannot reuse any stale per-document or block state.
        # Its exhaustive scorer uses current N/DF/average length, not bounds.
        with patch.object(self.cg, "_bm25_index", None), patch.dict(
                os.environ, {"MDCG_BM25_BLOCK_MAX": "0"}):
            expected, reference = self.raw(query, entries)
        self.assertEqual(actual, expected)
        self.assertEqual(info["matched"], reference["matched"])

    def test_single_edit_repairs_only_local_cached_blocks(self):
        self.populate()
        with patch.object(bm25, "BLOCK_THRESHOLD", 64):
            self.raw("common second")
            idx = self.cg._bm25_index
            ordinals, common = idx.ordinals, idx.term_blocks["common"]
            path = self.cg.index["nodes"]["local0519"]["path"]
            slot = ordinals[path]
            self.cg.add("local0519", "common " * 40 + "second " * 20,
                        importance=0.4, override=True)
            self.cg.flush()
            actual, info = self.raw("common second")
            self.exact("common second", actual, info)
            self.assertIs(idx.ordinals, ordinals)
            self.assertGreater(idx.ordinals[path], slot)
            self.assertIsNone(idx.block_paths[slot])
            self.assertIs(idx.term_blocks["common"], common)
            self.assertFalse(info["block_layout_rebuilt"])
            self.assertEqual(info["block_layout_touched"], 1)
            self.assertEqual(info["block_repaired_blocks"], 2)
            self.assertLessEqual(info["block_update_slots"], 2 * bm25.BLOCK_SIZE)
            self.assertEqual(info["block_rebuild_postings"], 0)

    def test_changed_average_length_reuses_unrelated_cached_pairs(self):
        self.populate()
        self.cg.add("unrelated", "other other")
        with patch.object(bm25, "BLOCK_THRESHOLD", 64):
            self.raw("common second")
            idx = self.cg._bm25_index
            common = idx.term_blocks["common"]
            self.cg.add("unrelated", "other " * 600, override=True)
            self.cg.flush()
            actual, info = self.raw("common second")
            self.assertIs(idx.term_blocks["common"], common)
            self.assertEqual(info["block_repaired_blocks"], 0)
            self.assertEqual(info["block_rebuild_postings"], 0)
            self.exact("common second", actual, info)

    def test_removed_query_term_rebuilds_its_old_block_bitmap(self):
        self.populate()
        with patch.object(bm25, "BLOCK_THRESHOLD", 64):
            self.raw("common second")
            idx = self.cg._bm25_index
            paths = idx.block_paths[bm25.BLOCK_SIZE:2 * bm25.BLOCK_SIZE]
            ids = [idx.docs[path][4] for path in paths]
            for nid in ids:
                self.cg.add(nid, "common", importance=0.4, override=True)
            self.cg.flush()
            actual, info = self.raw("second")
            self.assertNotIn(1, idx.term_blocks["second"])
            self.assertEqual(info["block_repaired_blocks"], 1)
            self.exact("second", actual, info)

    def test_removed_pool_paths_keep_live_map_and_append_delta(self):
        self.populate()
        with patch.object(bm25, "BLOCK_THRESHOLD", 64):
            self.raw("common second")
            idx = self.cg._bm25_index
            original_slots = len(idx.block_paths)
            removed = set(self.cg.index["nodes"][nid]["path"]
                          for nid in ("local0005", "local0400"))
            removed_slots = [idx.ordinals[path] for path in removed]
            entries = [e for e in self.cg._candidates() if e["path"] not in removed]
            actual, info = self.raw("common second", entries)
            self.exact("common second", actual, info, entries)
            self.cg.add("replacement", "common second", importance=0.9)
            self.cg.flush()
            entries = [e for e in self.cg._candidates() if e["path"] not in removed]
            actual, info = self.raw("common second", entries)
            path = self.cg.index["nodes"]["replacement"]["path"]
            self.assertEqual(idx.ordinals[path], original_slots)
            self.assertEqual(len(idx.block_paths), original_slots + 1)
            self.assertEqual(idx.block_holes, 2)
            self.assertTrue(all(idx.block_paths[slot] is None for slot in removed_slots))
            self.assertTrue(removed.isdisjoint(idx.ordinals))
            self.exact("common second", actual, info, entries)

    def test_multiple_new_blocks_keep_layout_and_tie_order(self):
        self.populate()
        with patch.object(bm25, "BLOCK_THRESHOLD", 64):
            self.raw("common second")
            idx = self.cg._bm25_index
            ordinals = idx.ordinals
            for i in range(300):
                self.cg.add(f"append{i:04d}", "common second", importance=0.4)
            self.cg.flush()
            actual, info = self.raw("common second")
            self.assertIs(idx.ordinals, ordinals)
            self.assertFalse(info["block_layout_rebuilt"])
            self.assertEqual(len(idx.block_best),
                             (len(idx.block_paths) + bm25.BLOCK_SIZE - 1) // bm25.BLOCK_SIZE)
            self.exact("common second", actual, info)

    def test_large_pool_shrink_compacts_slots_and_remains_exact(self):
        self.populate()
        with patch.object(bm25, "BLOCK_THRESHOLD", 64):
            self.raw("common second")
            idx = self.cg._bm25_index
            entries = [e for e in self.cg._candidates()
                       if idx.docs[e["path"]][4].startswith("local")][:130]
            actual, info = self.raw("common second", entries)
            self.assertTrue(info["block_layout_rebuilt"])
            self.assertEqual(len(idx.block_paths), len(idx.docs))
            self.assertEqual(idx.block_holes, 0)
            self.exact("common second", actual, info, entries)

    def test_bounded_update_journal_falls_back_to_exact_full_layout(self):
        self.populate()
        with patch.object(bm25, "BLOCK_THRESHOLD", 64), patch.object(
                bm25, "BLOCK_UPDATE_LIMIT", 1):
            self.raw("common second")
            idx = self.cg._bm25_index
            for nid in ("local0001", "local0002"):
                self.cg.add(nid, "common " * 10 + "second", override=True)
            self.cg.flush()
            actual, info = self.raw("common second")
            self.assertTrue(info["block_layout_rebuilt"])
            self.assertEqual(idx.block_updates, {})
            self.assertEqual(len(idx.block_paths), len(idx.docs))
            self.exact("common second", actual, info)

    def test_empty_pool_releases_block_layout_and_terms(self):
        self.populate()
        with patch.object(bm25, "BLOCK_THRESHOLD", 64):
            self.raw("common second")
            idx = self.cg._bm25_index
            actual, info = self.raw("common second", [])
            self.assertEqual(actual, [])
            self.assertIsNone(idx.ordinals)
            self.assertEqual(idx.term_blocks, {})
            self.assertEqual(idx.block_updates, {})
            self.assertEqual(idx.block_dirty, {})

    def test_importance_only_edit_refreshes_pruning_tie_bound(self):
        for i in range(260):
            self.cg.add(f"tie{i:04d}", "same terms", importance=0.4)
        self.cg.flush()
        with patch.object(bm25, "BLOCK_THRESHOLD", 64):
            self.raw("same terms")
            idx = self.cg._bm25_index
            path = self.cg.index["nodes"]["tie0259"]["path"]
            block = idx.ordinals[path] // bm25.BLOCK_SIZE
            self.cg.add("tie0259", "same terms", importance=1.0, override=True)
            self.cg.flush()
            actual, info = self.raw("same terms")
            self.assertEqual(actual[0][0]["id"], "tie0259")
            self.assertEqual(idx.block_best[block], (-1.0, "tie0259"))
            self.exact("same terms", actual, info)

    def test_deferred_repairs_match_cold_oracle_across_mixed_history(self):
        self.populate(300)
        rng = random.Random(107)
        with patch.object(bm25, "BLOCK_THRESHOLD", 64):
            self.raw("common second")
            for turn in range(12):
                nid = f"local{rng.randrange(300):04d}"
                text = ("common " * rng.randrange(1, 10)
                        + "second " * rng.randrange(5)
                        + "padding " * rng.randrange(6))
                self.cg.add(nid, text, importance=rng.choice((0.4, 0.8)), override=True)
                if turn % 3 == 0:
                    self.cg.add(f"new{turn}", "second padding", importance=0.7)
                self.cg.flush()
                # Some cached terms stay dirty over several intervening queries.
                query = ("common", "second", "padding common")[turn % 3]
                entries = self.cg._candidates()
                if turn % 4 == 0:
                    excluded = self.cg.index["nodes"]["local0000"]["path"]
                    entries = [e for e in entries if e["path"] != excluded]
                actual, info = self.raw(query, entries)
                self.exact(query, actual, info, entries)

    def test_repeated_edits_compact_before_layout_doubles(self):
        self.populate(20)
        compacted = 0
        with patch.object(bm25, "BLOCK_SIZE", 16), patch.object(bm25, "BLOCK_THRESHOLD", 16):
            self.raw("common second")
            idx = self.cg._bm25_index
            for turn in range(25):
                self.cg.add("local0000", "common " * (turn % 5 + 1) + "second",
                            importance=0.4, override=True)
                self.cg.flush()
                actual, info = self.raw("common second")
                compacted += info["block_layout_rebuilt"]
                self.assertLessEqual(len(idx.block_paths), max(32, 2 * len(idx.docs)))
                self.assertEqual(idx.block_holes, len(idx.block_paths) - len(idx.docs))
            self.assertGreater(compacted, 0)
            self.exact("common second", actual, info)

    def test_small_exhaustive_pool_drops_stale_large_layout(self):
        self.populate()
        with patch.object(bm25, "BLOCK_THRESHOLD", 64):
            self.raw("common second")
            idx = self.cg._bm25_index
            entries = self.cg._candidates()[:20]
            actual, info = self.raw("common second", entries)
            self.assertNotIn("algorithm", info)
            self.assertIsNone(idx.ordinals)
            self.assertEqual(idx.term_blocks, {})
            self.exact("common second", actual, info, entries)


if __name__ == "__main__":
    unittest.main()
