"""Production BM25 runtime: ranking, invalidation, security and MCP wiring."""
import math
import json
import os
import random
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

from . import bm25, mdcos, nodefile, readcache


class BM25Tests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "MDCG_HOTCACHE": "0", "MDCG_READ_CACHE": "1",
            "MDCG_RETRIEVAL_PIPELINE": "0", "MDCG_UNIFY_QUERY": "0",
            "MDCG_SEMANTIC": "0", "MDCG_EN_ATOMS": "0",
            "MDCG_RRF_CANDIDATES": "0"})
        self.env.start()
        self.temp = tempfile.TemporaryDirectory(prefix="bm25_")
        self.cg = mdcos.MdCGOS(self.temp.name)
        for nid, text in {"a": "apple apple pear", "b": "apple pear pear",
                          "c": "pear banana banana"}.items():
            self.cg.add(nid, text)
        self.cg.flush()

    def tearDown(self):
        self.cg.close()
        self.temp.cleanup()
        self.env.stop()

    def search(self, query, **kwargs):
        options = dict(k=50, paths=("bm25",), judge=False, record=False)
        options.update(kwargs)
        rows, meta = self.cg.search_rrf(query, **options)
        self.assertNotIn("fallback", meta.get("bm25", {}))
        return rows, meta

    def test_hand_calculated_frequency_saturation_and_idf(self):
        rows, report = bm25.search(self.cg, "APPLE", self.cg._candidates(), {"scanned": 0})
        scores = {n["id"]: score for n, score in rows}
        idf = math.log(1 + 1.5 / 2.5)  # N=3, df=2; all lengths=3
        self.assertAlmostEqual(scores["a"], idf * 4.4 / 3.2)
        self.assertAlmostEqual(scores["b"], idf)
        self.assertEqual([n["id"] for n, _ in rows], ["a", "b"])
        self.assertEqual(report["posting_visits"], 2)
        repeated, _ = bm25.search(self.cg, "apple apple", self.cg._candidates(), {"scanned": 0})
        self.assertEqual(rows, repeated)

    def test_length_normalization_and_missing_query(self):
        self.cg.add("short", "rareword")
        self.cg.add("long", "rareword " + "filler " * 100)
        rows, _ = self.search("rareword")
        self.assertEqual([r[0]["id"] for r in rows], ["short", "long"])
        self.assertEqual(self.search("doesnotexist")[0], [])

    def test_chinese_single_char_pair_tags_and_negative_body(self):
        self.assertEqual(list(bm25.tokenize("记忆 API-2")), ["记", "忆", "记忆", "api", "2"])
        self.cg.add("cn", "记忆检索")
        self.cg.add("tag", "天气", tags=["独有标签"])
        self.cg.add("negative", "# 生效条件：天气\n# 不适用条件：禁用线索 badnegativeterm\n晴朗")
        for query, wanted in (("记", "cn"), ("记忆", "cn"), ("独有标签", "tag")):
            self.assertEqual({r[0]["id"] for r in self.search(query)[0]}, {wanted})
        self.assertNotIn("negative", {r[0]["id"] for r in self.search("禁用线索")[0]})
        self.assertEqual(self.search("badnegativeterm")[0], [])

    def test_top50_boundary_ties_and_no_zero_score_padding(self):
        for i in reversed(range(70)):
            self.cg.add(f"tie{i:02d}", "equalword", importance=0.4)
        rows, meta = self.search("equalword", k=100)
        self.assertEqual([r[0]["id"] for r in rows], [f"tie{i:02d}" for i in range(50)])
        self.assertEqual(meta["bm25"]["matched"], 70)
        self.assertEqual(meta["scanned"], 50)
        self.assertEqual(meta["paths"], {"bm25": 50})
        self.cg.add("tie69", "equalword", importance=0.9, override=True)
        rows, _ = self.search("equalword", k=100)
        self.assertEqual([r[0]["id"] for r in rows], ["tie69"] + [f"tie{i:02d}" for i in range(49)])

    def test_warm_query_hydrates_only_matches_and_default_is_unchanged(self):
        self.search("apple")
        with patch.object(self.cg, "_read_status", wraps=self.cg._read_status) as reads:
            rows, meta = self.search("banana")
        self.assertEqual(len(rows), 1)
        self.assertLessEqual(reads.call_count, 1)
        self.assertEqual(meta["bm25"]["build_reads"], 0)
        self.assertEqual(meta["bm25"]["update_reads"], 0)
        self.assertEqual(meta["scanned"], 1)
        default, info = self.cg.search_rrf("apple", judge=False, record=False)
        self.assertNotIn("bm25", info)
        self.assertNotIn("bm25", info["paths"])
        self.assertTrue(default)

    def test_add_edit_flush_delete_and_explicit_clear(self):
        self.search("apple")
        self.cg.add("new", "freshword")
        self.cg.flush()
        rows, meta = self.search("freshword")
        self.assertEqual({r[0]["id"] for r in rows}, {"new"})
        self.assertEqual(meta["bm25"]["update_reads"], 1)
        self.cg.add("new", "replacementword", override=True)
        self.cg.flush()
        self.assertEqual(self.search("freshword")[0], [])
        self.assertEqual({r[0]["id"] for r in self.search("replacementword")[0]}, {"new"})
        self.assertTrue(self.cg.forget("new")["ok"])
        self.cg.flush()
        self.assertEqual(self.search("replacementword")[0], [])
        readcache.clear(self.cg)
        self.assertEqual(self.cg._bm25_index.docs, {})
        self.assertEqual(self.search("apple")[1]["bm25"]["build_reads"], 3)

    def test_rebuild_and_other_process_reload(self):
        self.search("apple")
        path = self.cg.index["nodes"]["a"]["path"]
        disk = Path(self.temp.name) / path
        fm, _body = nodefile.loads(disk.read_text(encoding="utf-8"))
        disk.write_text(nodefile.dumps(fm, "externalword"), encoding="utf-8")
        self.cg.rebuild_index()
        self.assertEqual({r[0]["id"] for r in self.search("externalword")[0]}, {"a"})
        writer = mdcos.MdCGOS(self.temp.name)
        try:
            writer.add("other", "crossprocessword")
            writer.flush()
            writer.compact_index()
            self.assertEqual({r[0]["id"] for r in self.search("crossprocessword")[0]}, {"other"})
        finally:
            writer.close()

    def test_session_pool_statistics_exclude_previous_broader_scope(self):
        self.cg.add("hidden", "apple " * 30, session="A")
        self.search("apple")
        rows, meta = self.search("apple", session="B")
        self.assertEqual(rows, [])
        # Pool-empty short circuit is allowed; the following narrower nonempty
        # pool must actually remove hidden documents from both DF and average DL.
        self.cg.add("visible", "apple", session="B")
        rows, meta = self.search("apple", session="B")
        self.assertEqual({r[0]["id"] for r in rows}, {"visible"})
        self.assertEqual(meta["bm25"]["documents"], 1)
        self.assertNotIn(self.cg.index["nodes"]["hidden"]["path"], self.cg._bm25_index.docs)
        score = bm25.search(self.cg, "apple", self.cg._candidates(session="B"), {"scanned": 0})[0][0][1]
        self.assertAlmostEqual(score, math.log(1 + 0.5 / 1.5))

    def test_transient_read_failure_retries_on_next_query(self):
        original = self.cg._read_status
        def fail(entry):
            return (None, None, "transient") if entry["path"].endswith("/a.md") else original(entry)
        with patch.object(self.cg, "_read_status", side_effect=fail):
            rows, meta = self.search("apple")
            self.assertNotIn("a", {r[0]["id"] for r in rows})
            self.assertGreater(meta["bm25"]["unavailable"], 0)
        self.assertIn("a", {r[0]["id"] for r in self.search("apple")[0]})

    def test_disabled_read_cache_rebuilds_instead_of_retaining_stale_terms(self):
        with patch.dict(os.environ, {"MDCG_READ_CACHE": "0"}):
            cg = mdcos.MdCGOS(self.temp.name)
        try:
            first = cg.search_rrf("apple", paths=("bm25",), record=False, judge=False)
            self.assertEqual(first[1]["bm25"]["cache_mode"], "uncached_rebuild")
            path = Path(self.temp.name) / cg.index["nodes"]["a"]["path"]
            fm, _ = nodefile.loads(path.read_text(encoding="utf-8"))
            path.write_text(nodefile.dumps(fm, "uncachedword"), encoding="utf-8")
            rows, _ = cg.search_rrf("uncachedword", paths=("bm25",), record=False, judge=False)
            self.assertEqual({r[0]["id"] for r in rows}, {"a"})
        finally:
            cg.close()

    def test_broken_derived_index_reports_lexical_fallback(self):
        self.search("apple")
        with patch.object(self.cg._bm25_index, "rank", side_effect=RuntimeError("injected")):
            rows, meta = self.cg.search_rrf("apple", paths=("bm25",), judge=False, record=False)
        self.assertTrue(rows)
        self.assertEqual(meta["bm25"]["fallback"], "lexical_index_error")
        self.assertEqual(meta["bm25"]["error_type"], "RuntimeError")
        self.assertEqual(self.cg._bm25_index.docs, {})

    def test_mcp_recall_uses_production_bm25_path(self):
        from . import mcp_server
        response = mcp_server.call_tool(self.cg, "mdcg_recall", {
            "query": "apple", "bm25": True, "causal": False, "temporal": False,
            "judge": False, "include_recent": False, "budget_tokens": 1000})
        self.assertIn("bm25", response["meta"])
        self.assertNotIn("lexical", response["meta"]["paths"])

    def test_bm25_seeds_recall_a_graph_only_target(self):
        self.cg.add("ghost", "unrelated island")
        self.cg.add("seed", "seedword", edges=[{
            "target": "ghost", "relation_type": "related_to"}])
        only, _ = self.search("seedword")
        self.assertEqual({r[0]["id"] for r in only}, {"seed"})
        expanded, _ = self.search("seedword", paths=("bm25", "graph"))
        self.assertIn("ghost", {r[0]["id"] for r in expanded})

    def test_real_mcp_stdio_schema_and_recall(self):
        root = Path(self.temp.name) / "stdio"
        (root / "knowledge").mkdir(parents=True)
        (root / "knowledge/public.md").write_text(nodefile.dumps({
            "id": "public", "layer": "knowledge", "sensitivity": "public",
            "importance": 0.4, "created_at": 1800000000.0, "tags": []}, "stdioword"), encoding="utf-8")
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "cg", "arguments": {"op": "read", "query": "stdioword", "bm25": True}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "cg", "arguments": {"op": "read", "query": "stdioword", "bm25": True,
                                              "budget_tokens": 1000}}},
            {"jsonrpc": "2.0", "id": 4, "method": "shutdown"}]
        env = dict(os.environ, MDCG_ROOT=str(root), MDCG_AUX_ROOT=str(root / "auxiliary"),
                   MDCG_DATA_ROOT=str(root / "data"), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        env.pop("MDCG_TOKEN", None)
        env["MDCG_MCP_SURFACE"] = "kernel"
        proc = subprocess.run([sys.executable, "-X", "utf8", "-m", "md_cg.mcp_server"],
            input="".join(json.dumps(m) + "\n" for m in messages), env=env,
            cwd=Path(__file__).resolve().parents[1], capture_output=True,
            text=True, encoding="utf-8", timeout=40)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        replies = {r["id"]: r for r in map(json.loads, proc.stdout.splitlines())}
        tool = next(t for t in replies[1]["result"]["tools"] if t["name"] == "cg")
        self.assertEqual(tool["inputSchema"]["properties"]["bm25"]["type"], "boolean")
        self.assertFalse(replies[2]["result"]["isError"], replies[2])
        payload = json.loads(replies[2]["result"]["content"][0]["text"])
        self.assertEqual(payload["meta"]["bm25"]["hydrated"], 1)
        self.assertEqual(payload["results"][0]["node"]["id"], "public")
        self.assertFalse(replies[3]["result"]["isError"], replies[3])
        packed = json.loads(replies[3]["result"]["content"][0]["text"])
        self.assertEqual(packed["meta"]["bm25"]["hydrated"], 1)
        self.assertEqual(packed["pack"][0]["id"], "public")

    def test_gate_pool_applies_before_bm25_statistics(self):
        # Force a known eligible pool at the shared gate seam, then exercise
        # the real scorer; existing gate tests verify the gate decision itself.
        entries = self.cg._candidates()
        selected = [e for e in entries if e["path"].endswith("/b.md")]
        with patch.object(mdcos, "apply_retrieval_gates", return_value=(selected, {"test": 1})):
            rows, meta = self.search("apple")
        self.assertEqual({r[0]["id"] for r in rows}, {"b"})
        self.assertEqual(meta["bm25"]["documents"], 1)
        self.assertEqual(meta["gates"], {"test": 1})

    def test_real_domain_bucket_condition_gates(self):
        from .test_c8_search_rrf_gates import build_lib, _Env, QUERY, CTX, A_IDS
        root = str(Path(self.temp.name) / "gated")
        build_lib(root)
        with _Env(MDCG_RETRIEVAL_PIPELINE="1", MDCG_GATE_S1_DOMAIN="1",
                  MDCG_GATE_S1B_BUCKET="1", MDCG_BUCKET_TOPK="1", MDCG_GATE_S2_COND="1"):
            cg = mdcos.MdCGSecure(root)
            try:
                rows, meta = cg.search_rrf(QUERY, k=50, paths=("bm25",),
                                          context=CTX, judge=False, record=False)
                self.assertEqual({r[0]["id"] for r in rows}, A_IDS)
                self.assertEqual(meta["bm25"]["documents"], len(A_IDS))
                self.assertTrue(meta["gates"])
            finally:
                cg.close()

    def test_ciphertext_lock_unlock_guest_and_query_cache(self):
        from . import crypto
        from .security import Principal
        root = Path(self.temp.name) / "encrypted"
        master = bytes(range(32))
        with patch.dict(os.environ, {"MDCG_HOTCACHE": "1"}):
            cg = mdcos.MdCGSecure(str(root), master_key=master, principal=Principal(
                tenant="bm25-test", actor="owner", session="S", clearance="secret",
                role="designer", can_write=True, can_admin=True))
        guest = None
        try:
            cg.add("sealed", "secretword", sensitivity="secret")
            cg.add("public", "publicword", sensitivity="public")
            cg.flush()
            path = cg.index["nodes"]["sealed"]["path"]
            self.assertTrue(crypto.is_encrypted(nodefile.loads((root / path).read_text(encoding="utf-8"))[1]))
            opts = dict(k=5, paths=("bm25",), judge=False, record=False)
            expected = cg.search_rrf("secretword", **opts)[0]
            self.assertEqual({r[0]["id"] for r in expected}, {"sealed"})
            self.assertTrue(cg.search_rrf("secretword", **opts)[1]["cached"])
            cg.lock()
            locked, info = cg.search_rrf("secretword", **opts)
            self.assertEqual(locked, [])
            self.assertFalse(info.get("cached", False))
            self.assertNotIn(path, cg._bm25_index.docs)
            cg.unlock(master)
            self.assertEqual(cg.search_rrf("secretword", **opts)[0], expected)
            guest = mdcos.MdCGSecure(str(root), master_key=master, principal=Principal(
                tenant="bm25-test", actor="guest", session="other", clearance="public",
                role="guest", can_write=False))
            self.assertEqual(guest.search_rrf("secretword", **opts)[0], [])
            self.assertNotIn(path, guest._bm25_index.docs)
        finally:
            if guest is not None:
                guest.close()
            cg.close()

    def test_block_bounds_match_exhaustive_scores_with_outliers_and_edits(self):
        rng = random.Random(108)
        for i in reversed(range(520)):
            words = ["common"] * rng.randint(1, 7)
            words += ["second"] * rng.randint(0, 8)
            words += ["third"] * rng.randint(0, 4)
            words += ["padding"] * rng.randint(0, 50)
            self.cg.add(f"mixed{i:04d}", " ".join(words), importance=rng.choice((0.1, 0.4, 0.9)))
        # The strongest short document is in a late block, not an initial prefix.
        self.cg.add("zz_outlier", "common second third", importance=1.0)
        with patch.object(bm25, "BLOCK_THRESHOLD", 64), patch.object(bm25, "BLOCK_PAIR_LIMIT", 256):
            for edited in (False, True):
                if edited:
                    self.cg.add("mixed0519", "common " * 70, importance=1.0, override=True)
                    self.cg.forget("mixed0000", override=True)
                    self.cg.flush()
                for query in ("common", "common second", "third common second",
                              "common absent", "common common third", "padding second"):
                    entries = self.cg._candidates()
                    with patch.dict(os.environ, {"MDCG_BM25_BLOCK_MAX": "0"}):
                        reference, ref = bm25.search(self.cg, query, entries, {"scanned": 0})
                    actual, info = bm25.search(self.cg, query, entries, {"scanned": 0})
                    self.assertNotIn("fallback", info)
                    self.assertEqual(actual, reference, (edited, query))
                    self.assertEqual(info["matched"], ref["matched"])
                    self.assertEqual(info["algorithm"], "exact_block_max")

    def test_equal_score_blocks_prune_without_changing_top50_or_match_count(self):
        for i in reversed(range(520)):
            self.cg.add(f"equal{i:04d}", "same common", importance=0.4)
        with patch.object(bm25, "BLOCK_THRESHOLD", 64):
            rows, meta = self.search("same common", k=100)
        info = meta["bm25"]
        self.assertEqual([r[0]["id"] for r in rows], [f"equal{i:04d}" for i in range(50)])
        self.assertEqual(info["matched"], 520)
        self.assertGreater(info["blocks_skipped"], 0)
        self.assertLess(info["posting_visits"], info["posting_candidates"])
        self.assertLess(info["scored_documents"], 520)

    def test_varied_lengths_choose_exhaustive_without_building_block_tables(self):
        for i in range(280):
            self.cg.add(f"varied{i:04d}", "common " + "filler " * i)
        with patch.object(bm25, "BLOCK_THRESHOLD", 64):
            rows, meta = self.search("common")
        self.assertNotIn("algorithm", meta["bm25"])
        self.assertIsNone(self.cg._bm25_index.ordinals)
        self.assertEqual(meta["bm25"]["posting_visits"], 280)
        self.assertEqual(rows[0][0]["id"], "varied0000")

    def test_access_changes_invalidate_reused_candidate_pool(self):
        from .security import Principal
        cg = mdcos.MdCGSecure(str(Path(self.temp.name) / "identity"), principal=Principal(
            tenant="pool-test", actor="reader", session="A", clearance="secret",
            can_admin=True, can_write=True))
        try:
            cg.add("private", "privateword", sensitivity="private")
            cg.add("public", "publicword", sensitivity="public")
            opts = dict(paths=("bm25",), judge=False, record=False)
            self.assertTrue(cg.search_rrf("privateword", **opts)[0])
            cg.principal.can_admin = False
            cg.principal.session = "B"
            self.assertEqual(cg.search_rrf("privateword", **opts)[0], [])
            cg.principal.clearance = "public"
            self.assertTrue(cg.search_rrf("publicword", **opts)[0])
            self.assertEqual(cg.search_rrf("privateword", **opts)[0], [])
        finally:
            cg.close()

    def test_large_build_prepares_other_frequent_terms_before_their_first_query(self):
        for i in range(280):
            self.cg.add(f"prepared{i:04d}", "common second", importance=0.4)
        with patch.object(bm25, "BLOCK_THRESHOLD", 64), patch.object(bm25, "STREAM_THRESHOLD", 64):
            first, meta = self.search("common")
            self.assertGreaterEqual(meta["bm25"]["block_terms_prepared"], 2)
            table = self.cg._bm25_index.term_blocks["second"]
            second, info = self.search("second")
            self.assertEqual([r[0]["id"] for r in first], [r[0]["id"] for r in second])
            self.assertIs(self.cg._bm25_index.term_blocks["second"], table)
            self.assertEqual(info["bm25"]["build_reads"], 0)
            self.assertTrue(info["bm25"]["pool_reused"])

    def test_shared_term_storage_preserves_tf_and_releases_removed_terms(self):
        self.cg.add("share1", "shared common")
        self.cg.add("share2", "shared " * 5 + "common")
        self.search("shared")
        idx = self.cg._bm25_index
        paths = tuple(self.cg.index["nodes"][nid]["path"] for nid in ("share1", "share2"))
        for path in paths:
            self.assertIsInstance(idx.docs[path][1], tuple)
            self.assertIs(next(t for t in idx.docs[path][1] if t == "shared"), idx.terms["shared"])
        self.assertEqual([idx.post["shared"][p] for p in paths], [1, 5])
        self.cg.forget("share1")
        self.cg.forget("share2")
        self.assertEqual(self.search("shared")[0], [])
        self.assertNotIn("shared", idx.terms)
        self.assertNotIn("shared", idx.post)
        readcache.clear(self.cg)
        self.assertEqual(idx.terms, {})

    def test_pool_reuse_invalidates_on_write_and_bypasses_clock_filters(self):
        with patch.object(self.cg, "_candidates", wraps=self.cg._candidates) as candidates:
            self.search("apple")
            self.search("banana")
            self.search("pear")
            self.assertEqual(candidates.call_count, 1)
            self.cg.add("fresh", "freshword")
            self.cg.flush()
            self.assertEqual({n[0]["id"] for n in self.search("freshword")[0]}, {"fresh"})
            self.assertEqual(candidates.call_count, 2)
            self.search("apple", validity=True)
            self.search("pear", validity=True)
            self.assertEqual(candidates.call_count, 4)
            self.search("apple", start_time="2020-01-01")
            self.search("pear", start_time="2020-01-01")
            self.assertEqual(candidates.call_count, 6)

    def test_parallel_build_keeps_existing_cache_and_retries_failed_reads(self):
        self.cg._read_status(self.cg.index["nodes"]["b"])
        saved = self.cg._read_cache[self.cg.index["nodes"]["b"]["path"]]
        original = self.cg._read_status
        def fail(entry):
            return (None, None, "transient") if entry["path"].endswith("/a.md") else original(entry)
        with patch.object(bm25, "STREAM_THRESHOLD", 1), patch.dict(os.environ, {
                "MDCG_BM25_BUILD_WORKERS": "4"}), patch.object(self.cg, "_read_status", side_effect=fail):
            rows, meta = self.search("apple")
            self.assertEqual({r[0]["id"] for r in rows}, {"b"})
            self.assertEqual(meta["bm25"]["build_workers"], 4)
            self.assertGreater(meta["bm25"]["unavailable"], 0)
        self.assertIs(self.cg._read_cache[self.cg.index["nodes"]["b"]["path"]], saved)
        self.assertIn(self.cg.index["nodes"]["b"]["path"], self.cg._realpath_cache)
        self.assertNotIn(self.cg.index["nodes"]["c"]["path"], self.cg._realpath_cache)
        self.assertIn("a", {r[0]["id"] for r in self.search("apple")[0]})
        self.assertTrue(self.cg.search("apple", record=False)[0])


if __name__ == "__main__":
    unittest.main()
