"""Runtime candidate containment, RRF equivalence and write visibility tests."""
import os
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from . import mdcos, nodefile, readcache
from .mdcg import index_key_hits
from .test_fuzzy_substring_equivalence import exhaustive_degree


class RRFCandidates(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "MDCG_RRF_CANDIDATES": "1", "MDCG_HOTCACHE": "0",
            "MDCG_READ_CACHE": "1", "MDCG_FRESHNESS": "0",
            "MDCG_RETRIEVAL_PIPELINE": "0", "MDCG_SEMANTIC": "0"})
        self.env.start()
        self.temp = tempfile.TemporaryDirectory(prefix="rrf_candidates_")
        root = Path(self.temp.name)
        (root / "knowledge").mkdir()
        self.bodies = {
            "exact": "# 生效条件：甲乙丙丁\n甲乙丙丁 abcabc 🙂x",
            "partial": "# 生效条件：甲乙\n甲乙 ab \n间隔",
            "negative": "# 生效条件：天气\n# 不适用条件：甲乙丙丁\n晴朗",
            "tags": "标签独有的节点",
            "unrelated": "完全不同的天气预报",
            "meta": "这里没有验证关键词",
            "semantic": "语义摘要载体",
        }
        for i in range(25):
            self.bodies[f"noise{i}"] = f"无关资料 第{i}条 空间气候"
        for nid, body in self.bodies.items():
            fm = {"id": nid, "layer": "knowledge", "importance": 0.2,
                  "created_at": 1800000000.0,
                  "tags": ["甲乙丙丁"] if nid == "tags" else []}
            if nid == "semantic":
                fm["semantic"] = "条件 检索"
            (root / "knowledge" / (nid + ".md")).write_text(
                nodefile.dumps(fm, body), encoding="utf-8")
        self.cg = mdcos.MdCGOS(str(root))
        self.cg.index["nodes"]["meta"][nodefile.POSTCONDITION_TERMS_KEY] = ["独有验证钥匙"]

    def tearDown(self):
        self.cg.close()
        self.temp.cleanup()
        self.env.stop()

    def compare(self, query, **options):
        args = dict(k=50, judge=False, record=False,
                    paths=("lexical", "fuzzy", "semantic", "goal", "graph", "chain"),
                    goal_text="甲乙丙丁")
        args.update(options)
        with patch.dict(os.environ, {"MDCG_RRF_CANDIDATES": "0"}):
            reference, ref_meta = self.cg.search_rrf(query, **args)
        actual, meta = self.cg.search_rrf(query, **args)
        self.assertEqual(actual, reference, (query, args))
        for key in ("paths", "fused", "provenance", "goal_used", "judge_filtered"):
            self.assertEqual(meta.get(key), ref_meta.get(key), (query, key))
        return actual, meta

    def test_unicode_partial_single_char_and_all_paths(self):
        for query in ("甲乙丙丁", "甲", "ab", "abcabc", "🙂x", "ab \n", "不存在的键"):
            self.compare(query)

    def test_random_fuzzy_candidates_preserve_exhaustive_matches(self):
        rng = random.Random(20261010)
        entries = self.cg._candidates()
        for _ in range(75):
            term = "".join(rng.choices("abc甲乙丙丁 \n🙂x", k=rng.randrange(1, 9)))
            if not term.strip():
                continue  # Production rejects an empty/whitespace query.
            results, _meta = self.compare(
                term, paths=("fuzzy",), query_expand=lambda q, t=term: {t: 1.0})
            expected = set()
            for e, fm, content in self.cg._read_many(entries, {"scanned": 0}):
                text = self.cg._positive_body(e, content) + " " + " ".join(fm.get("tags") or [])
                if exhaustive_degree(term, text) > 0:
                    expected.add(fm["id"])
            self.assertEqual({r[0]["id"] for r in results}, expected, repr(term))

    def test_index_keys_and_semantic_summary_are_not_lost(self):
        e = self.cg.index["nodes"]["meta"]
        self.assertTrue(index_key_hits(e, ["独有验证钥匙"], "独有验证钥匙")["hit"])
        self.compare("独有验证钥匙", paths=("lexical",))
        self.compare("什么条件下不适用", paths=("lexical",), judge=True)
        with patch.dict(os.environ, {"MDCG_SEMANTIC": "1"}):
            self.compare("根本没有词面重叠", paths=("lexical",))

    def test_empty_expanded_term_keeps_relevance_cap(self):
        with patch.object(mdcos, "GLOBAL_CAP", 3):
            self.compare("🦄🦄🦄", paths=("lexical", "fuzzy"))

    def test_lexical_false_positive_keeps_full_fallback_pool(self):
        self.cg.add("important", "完全无关", importance=0.99)
        with patch.object(mdcos, "expand_query_terms", return_value=["WXZY"]):
            self.cg.add("false_positive", "WX XZ ZY", override=True)
            results, meta = self.compare("WXZY", paths=("lexical",))
        self.assertTrue(results)
        self.assertEqual(meta["rrf_candidates"]["paths"]["lexical"]["fallback"], "no_like_hit")

    def test_add_edit_and_flush_only_reindex_changed_nodes(self):
        self.compare("甲乙丙丁", paths=("fuzzy",))
        self.cg.add("new", "新增罕见线索")
        self.cg.flush()
        results, meta = self.compare("新增罕见线索", paths=("fuzzy",))
        self.assertIn("new", {r[0]["id"] for r in results})
        self.assertEqual(meta["rrf_candidates"]["build_reads"], 0)
        self.assertEqual(meta["rrf_candidates"]["update_reads"], 1)
        self.cg.add("new", "更新后的别名", override=True)
        self.cg.flush()
        results, meta = self.compare("更新后的别名", paths=("fuzzy",))
        self.assertIn("new", {r[0]["id"] for r in results})
        self.assertEqual(meta["rrf_candidates"]["update_reads"], 1)
        self.compare("新增罕见线索", paths=("fuzzy",))

    def test_delete_rebuild_and_clear_keep_visibility(self):
        self.compare("甲乙丙丁")
        self.assertTrue(self.cg.forget("exact")["ok"])
        results, _ = self.compare("甲乙丙丁")
        self.assertNotIn("exact", {r[0]["id"] for r in results})
        self.cg.rebuild_index()
        self.compare("甲乙丙丁")
        readcache.clear(self.cg)
        self.assertIsNone(self.cg._rrf_candidate_index.nodes)
        self.assertIsNone(self.cg._rrf_candidate_index.dirty)
        _, meta = self.compare("甲乙丙丁", paths=("fuzzy",))
        self.assertGreater(meta["rrf_candidates"]["build_reads"], 0)

    def test_filter_views_and_read_failure_recovery(self):
        self.cg.add("private", "会话独有检索词", session="A", role="tool-output")
        for options in ({"session": "A"}, {"session": "B"},
                        {"include_work": True}, {"view": "receipt"}):
            self.compare("会话独有检索词", **options)
        readcache.clear(self.cg)
        original = self.cg._read_status
        def fail_once(entry):
            if entry["path"].endswith("exact.md"):
                return None, None, "transient"
            return original(entry)
        with patch.object(self.cg, "_read_status", side_effect=fail_once):
            self.cg.search_rrf("甲乙丙丁", paths=("fuzzy",), judge=False, record=False)
        results, _ = self.compare("甲乙丙丁", paths=("fuzzy",))
        self.assertIn("exact", {r[0]["id"] for r in results})

    def test_read_cache_opt_out_falls_back_and_flag_is_keyed(self):
        from . import hotcache
        before = hotcache.env_switch_key()
        with patch.dict(os.environ, {"MDCG_RRF_CANDIDATES": "0"}):
            self.assertNotEqual(before, hotcache.env_switch_key())
        del self.cg._read_cache
        _, meta = self.compare("甲乙丙丁", paths=("fuzzy",))
        self.assertEqual(meta["rrf_candidates"]["paths"]["fuzzy"]["fallback"],
                         "read_cache_unavailable")

    def test_crossprocess_reload_and_retrieval_gates(self):
        self.compare("甲乙丙丁")
        other = mdcos.MdCGOS(self.temp.name)
        try:
            other.add("external", "外部写入独有线索")
            other.flush()
            self.assertTrue(self.cg._maybe_reload_index())
            results, _ = self.compare("外部写入独有线索", paths=("fuzzy",))
            self.assertIn("external", {r[0]["id"] for r in results})
        finally:
            other.close()
        with patch.dict(os.environ, {"MDCG_RETRIEVAL_PIPELINE": "1"}):
            self.compare("甲乙丙丁", context={"tags": ["索引"]})

    def test_secure_index_only_contains_readable_nodes(self):
        from .security import Principal
        root = Path(self.temp.name) / "secure"
        (root / "knowledge").mkdir(parents=True)
        for nid, sensitivity in (("visible", "public"), ("hidden", "secret")):
            fm = {"id": nid, "layer": "knowledge", "sensitivity": sensitivity,
                  "session": "other", "importance": 0.2}
            (root / "knowledge" / (nid + ".md")).write_text(
                nodefile.dumps(fm, "甲乙丙丁 私密探针"), encoding="utf-8")
        cg = mdcos.MdCGSecure(str(root), principal=Principal(
            clearance="public", can_write=False, role="guest", session="reader"))
        try:
            with patch.dict(os.environ, {"MDCG_RRF_CANDIDATES": "0"}):
                expected, _ = cg.search_rrf("甲乙丙丁", paths=("lexical", "fuzzy"),
                                            judge=False, record=False)
            actual, _ = cg.search_rrf("甲乙丙丁", paths=("lexical", "fuzzy"),
                                      judge=False, record=False)
            self.assertEqual(actual, expected)
            self.assertEqual({r[0]["id"] for r in actual}, {"visible"})
            self.assertFalse(any("hidden" in p for p in cg._rrf_candidate_index.docs))
        finally:
            cg.close()

    def test_nonfinite_expander_and_index_failure_preserve_reference(self):
        self.compare("甲乙", paths=("fuzzy",), query_expand=lambda q: {"z": float("nan")})
        from . import rrf_candidates
        with patch.object(rrf_candidates.CandidateIndex, "sync", side_effect=OSError("test")):
            _, meta = self.compare("甲乙丙丁", paths=("fuzzy",))
        self.assertEqual(meta["rrf_candidates"]["paths"]["fuzzy"]["fallback"], "index_error")


if __name__ == "__main__":
    unittest.main()
