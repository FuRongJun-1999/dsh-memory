"""Sparse production qualification and TF sync against a fresh exhaustive oracle."""
from collections import deque
import os
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

_isolated = tempfile.TemporaryDirectory(prefix="bm25_sparse_aux_")
os.environ["MDCG_AUX_ROOT"] = str(Path(_isolated.name) / "auxiliary")
os.environ["MDCG_MASTER_KEY"] = "ab" * 32

from . import bm25, mdcg, mdcos, readcache  # noqa: E402
from . import test_bm25 as base_tests  # noqa: E402


class SparseSyncTests(unittest.TestCase):
    setUp = base_tests.BM25Tests.setUp
    tearDown = base_tests.BM25Tests.tearDown
    search = base_tests.BM25Tests.search

    def pool(self, **options):
        # Match search_rrf's exact eligibility call, including explicit defaults.
        # A differently shaped cache key would silently force a full scan here
        # and hide bugs in candidate ordering or an unconsumed delta.
        arguments = dict(layer=None, roles=None, include_work=False, session=None,
                         branch=None, validity=None, start_time=None, end_time=None,
                         start_operator=None, end_operator=None, time_axis=None, view=None)
        arguments.update(options)
        return bm25.candidate_pool(self.cg, **arguments)

    def populate(self, count=96):
        for i in range(count):
            self.cg.add(f"sparse{i:04d}", "common second " + "padding " * (i % 7))
        self.cg.flush()
        self.search("common second")

    def oracle(self, query, **options):
        entries = self.cg._candidates(**options)
        actual, info = bm25.search(self.cg, query, self.pool(**options), {"scanned": 0})
        with patch.object(self.cg, "_bm25_index", None), patch.dict(os.environ, {"MDCG_BM25_BLOCK_MAX": "0"}):
            expected, cold = bm25.search(self.cg, query, entries, {"scanned": 0})
        self.assertNotIn("fallback", info)
        self.assertEqual(actual, expected)
        self.assertEqual(info["matched"], cold["matched"])
        self.assertEqual(info["documents"], cold["documents"])

    def test_one_overwrite_checks_one_document_after_flush(self):
        self.populate()
        with patch.object(bm25, "BLOCK_THRESHOLD", 32):
            self.search("common second")
            self.cg.add("sparse0045", "common newword " + "longword " * 40, override=True)
            self.cg.flush()
            rows, meta = self.search("common second newword")
        self.assertTrue(rows)
        self.assertTrue(meta["bm25"]["pool_incremental"])
        self.assertEqual(meta["bm25"]["sync_checked_documents"], 1)
        self.assertEqual(meta["bm25"]["update_reads"], 1)
        self.oracle("common second newword")

    def test_appends_and_repeated_new_id_preserve_original_pool_order(self):
        self.populate()
        self.cg.add("new_z", "newword common")
        self.cg.add("new_a", "newword " * 8)
        self.cg.add("new_z", "newword replacement", override=True)
        self.cg.flush()
        rows, meta = self.search("newword common")
        self.assertTrue(rows)
        self.assertTrue(meta["bm25"]["pool_incremental"])
        self.assertEqual(meta["bm25"]["sync_checked_documents"], 2)
        self.assertEqual(meta["bm25"]["documents"], 101)
        self.assertEqual(self.pool(), self.cg._candidates())
        self.oracle("newword common")

    def test_partial_pool_rejects_hidden_insert_and_keeps_statistics_scoped(self):
        self.cg.add("visible", "sharedword", session="A")
        self.search("sharedword", session="A")
        self.cg.add("hidden", "sharedword " * 80, session="B")
        self.cg.flush()
        rows, meta = self.search("sharedword", session="A")
        self.assertEqual([row[0]["id"] for row in rows], ["visible"])
        self.assertEqual(meta["bm25"]["documents"], 1)
        self.assertFalse(meta["bm25"]["pool_incremental"])
        self.oracle("sharedword", session="A")

    def test_route_migration_removes_old_tf_and_keeps_node_order(self):
        self.populate()
        old_path = self.cg.index["nodes"]["sparse0045"]["path"]
        self.cg.add("sparse0045", "migratedword " * 9, layer="contextual", override=True)
        self.cg.flush()
        new_path = self.cg.index["nodes"]["sparse0045"]["path"]
        self.assertNotEqual(old_path, new_path)
        rows, info = self.search("migratedword common")
        self.assertIn("sparse0045", [r[0]["id"] for r in rows])
        self.assertTrue(info["bm25"]["pool_incremental"])
        self.assertEqual(info["bm25"]["sync_checked_documents"], 1)
        self.assertNotIn(old_path, self.cg._bm25_index.allowed)
        self.assertNotIn(old_path, self.cg._bm25_index.docs)
        self.assertEqual(self.pool(), self.cg._candidates())
        self.oracle("migratedword common")

    def test_in_place_path_migration_uses_the_saved_original_path(self):
        self.populate()
        entry = self.cg.index["nodes"]["sparse0045"]
        old_path = entry["path"]
        moved = "knowledge/moved/sparse0045.md"
        target = Path(self.temp.name) / moved
        target.parent.mkdir(parents=True)
        (Path(self.temp.name) / old_path).rename(target)
        entry["path"] = moved
        self.cg._dirty["sparse0045"] = entry
        self.cg.flush()
        _, info = self.search("common second")
        self.assertTrue(info["bm25"]["pool_incremental"])
        self.assertNotIn(old_path, self.cg._bm25_index.docs)
        self.assertEqual(info["bm25"]["documents"], 99)
        self.oracle("common second")

    def test_secure_delta_reuses_the_same_visibility_filter(self):
        from .security import Principal
        cg = mdcos.MdCGSecure(str(Path(self.temp.name) / "secure"),
            master_key=bytes(range(32)), principal=Principal(tenant="sparse", actor="owner",
                session="S", clearance="secret", role="designer", can_write=True, can_admin=True))
        try:
            with patch.object(self, "cg", cg):
                cg.add("visible", "secureword", sensitivity="public")
                cg.add("sealed", "secureword " * 50, sensitivity="secret")
                cg.flush()
                self.search("secureword")
                cg.principal.clearance = "public"
                rows, info = self.search("secureword")
                self.assertEqual([r[0]["id"] for r in rows], ["visible"])
                self.assertEqual(info["bm25"]["documents"], 1)
                cg.add("visible", "secureword freshword", sensitivity="public", override=True)
                cg.flush()
                rows, info = self.search("freshword secureword")
                self.assertEqual([r[0]["id"] for r in rows], ["visible"])
                self.assertTrue(info["bm25"]["pool_incremental"])
                self.assertEqual(info["bm25"]["sync_checked_documents"], 1)
                self.oracle("freshword secureword")
                # Even when the principal is unchanged, a metadata visibility
                # drop must remove the old DF/length contribution immediately.
                cg._index_sensitivity("visible", "secret")
                cg.flush()
                self.assertEqual(self.search("freshword secureword")[0], [])
                self.oracle("freshword secureword")
        finally:
            cg.close()

    def test_gate_projection_forces_sync_of_its_own_statistics(self):
        self.populate()
        selected = [self.cg.index["nodes"]["sparse0045"]]
        with patch.object(mdcos, "apply_retrieval_gates", return_value=(selected, {"test": 1})):
            self.search("common")
        self.cg.add("sparse0045", "common " * 20, override=True)
        self.cg.flush()
        selected = [self.cg.index["nodes"]["sparse0045"]]
        with patch.object(mdcos, "apply_retrieval_gates", return_value=(selected, {"test": 1})):
            rows, info = self.search("common")
        self.assertEqual([r[0]["id"] for r in rows], ["sparse0045"])
        self.assertEqual(info["bm25"]["documents"], 1)
        self.assertFalse(info["bm25"]["pool_incremental"])
        self.oracle("common")

    def test_legacy_id_path_alias_uses_the_original_full_qualification(self):
        self.populate()
        entry = self.cg.index["nodes"].pop("sparse0045")
        self.cg.index["nodes"]["alias"] = entry
        self.cg._dirty.clear(broad=True)
        self.search("common")
        self.cg.add("sparse0044", "aliasword common", override=True)
        self.cg.flush()
        _, info = self.search("aliasword common")
        self.assertFalse(info["bm25"]["pool_incremental"])
        self.oracle("aliasword common")

    def test_no_write_flush_keeps_a_complete_empty_delta(self):
        self.populate()
        self.cg._dirty.clear()
        _, info = self.search("common")
        self.assertTrue(info["bm25"]["pool_incremental"])
        self.assertEqual(info["bm25"]["sync_checked_documents"], 0)
        self.oracle("common")

    def test_randomized_writes_filters_and_routes_match_fresh_exact_scoring(self):
        self.populate(24)
        rng = random.Random(20261012)
        for turn in range(30):
            nid = f"sparse{rng.randrange(24):04d}" if turn % 4 else f"new_{turn}"
            self.cg.add(nid, "common " * rng.randrange(1, 15) + "rareword "
                        + "padding " * rng.randrange(30), override=True,
                        layer=rng.choice(("knowledge", "contextual")),
                        session=rng.choice(("A", "B")),
                        role=rng.choice(("user", "tool-output")),
                        importance=rng.choice((0.3, 0.6)))
            self.cg.flush()
            options = ({}, {"session": "A"}, {"include_work": True})[turn % 3]
            self.search("common rareword", **options)
            self.oracle("common rareword", **options)

    def test_membership_drop_and_restore_keep_full_candidate_order(self):
        self.populate()
        entry = self.cg.index["nodes"]["sparse0000"]
        entry["role"] = "tool-output"
        self.cg._dirty["sparse0000"] = entry
        self.cg.flush()
        rows, info = self.search("common")
        self.assertNotIn("sparse0000", [r[0]["id"] for r in rows])
        self.assertFalse(info["bm25"]["pool_incremental"])
        entry["role"] = "user"
        self.cg._dirty["sparse0000"] = entry
        self.cg.flush()
        self.search("common")
        self.assertEqual(self.pool(), self.cg._candidates())
        self.oracle("common")

    def test_history_overflow_falls_back_instead_of_missing_edits(self):
        self.populate()
        self.cg._dirty.change_log = deque(maxlen=2)
        for i in range(3):
            self.cg.add(f"sparse{i:04d}", "overflowword " * (i + 1), override=True)
        self.cg.flush()
        rows, meta = self.search("overflowword")
        self.assertEqual({row[0]["id"] for row in rows}, {f"sparse{i:04d}" for i in range(3)})
        self.assertFalse(meta["bm25"]["pool_incremental"])
        self.oracle("overflowword common")

    def test_pool_can_advance_twice_before_bm25_consumes_it(self):
        self.populate()
        self.cg.add("sparse0000", "intermediateword", override=True)
        self.cg.flush()
        self.pool()
        self.cg.add("sparse0001", "latestword", override=True)
        self.cg.flush()
        rows, meta = self.search("intermediateword latestword")
        self.assertEqual({row[0]["id"] for row in rows}, {"sparse0000", "sparse0001"})
        self.assertFalse(meta["bm25"]["pool_incremental"])
        self.oracle("intermediateword latestword common")

    def test_failed_delta_read_is_retried_without_another_write(self):
        self.populate()
        path = self.cg.index["nodes"]["sparse0045"]["path"]
        self.cg.add("sparse0045", "retryword", override=True)
        self.cg.flush()
        original = self.cg._read_status
        with patch.object(self.cg, "_read_status", side_effect=lambda e:
                          (None, None, "transient") if e["path"] == path else original(e)):
            rows, info = self.search("retryword")
            self.assertEqual(rows, [])
            self.assertGreater(info["bm25"]["unavailable"], 0)
        self.assertEqual([r[0]["id"] for r in self.search("retryword")[0]], ["sparse0045"])
        self.oracle("retryword common")

    def test_delete_and_explicit_clear_release_sparse_state(self):
        self.populate()
        self.cg.add("sparse0045", "changedword", override=True)
        self.cg.flush()
        self.search("changedword")
        self.assertIsNotNone(self.cg._bm25_pool_delta)
        self.cg.forget("sparse0045")
        self.cg.flush()
        self.assertEqual(self.search("changedword")[0], [])
        self.oracle("common")
        readcache.clear(self.cg)
        self.assertIsNone(self.cg._bm25_pool_delta)
        self.assertIsNone(self.cg._bm25_candidate_pool)
        self.oracle("common")

    def test_clock_and_opt_out_paths_use_the_existing_full_filter(self):
        self.populate()
        self.cg.add("sparse0000", "clockword", override=True)
        self.cg.flush()
        self.assertFalse(self.search("clockword", validity=True)[1]["bm25"]["pool_incremental"])
        with patch.dict(os.environ, {"MDCG_BM25_POOL_CACHE": "0"}):
            self.oracle("clockword common")
        self.assertIsNone(self.cg._bm25_pool_delta)

    def test_bounded_journal_retains_flush_events_and_invalidates_broad_changes(self):
        dirty = mdcg._DirtyDict()
        dirty["a"] = {"path": "a.md"}
        dirty["b"] = {"path": "b.md"}
        dirty["a"] = {"path": "a.md"}
        dirty.clear()
        self.assertEqual(dirty.changed_ids_since(0), ("a", "b"))
        self.assertEqual(dirty.changed_ids_since(dirty.write_gen), ())
        dirty.clear(broad=True)
        self.assertIsNone(dirty.changed_ids_since(0))

    def test_evicted_version_is_an_exclusive_history_boundary(self):
        dirty = mdcg._DirtyDict()
        dirty.change_log = deque(maxlen=2)
        dirty["a"] = {"path": "a.md"}
        dirty["b"] = {"path": "b.md"}
        dirty["c"] = {"path": "c.md"}
        self.assertIsNone(dirty.changed_ids_since(0))
        self.assertEqual(dirty.changed_ids_since(1), ("b", "c"))
        self.assertEqual(dirty.changed_ids_since(2), ("c",))
        dirty.clear()
        self.assertEqual(dirty.changed_ids_since(3), ())


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        _isolated.cleanup()
