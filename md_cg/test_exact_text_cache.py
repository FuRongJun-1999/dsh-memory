"""Runtime guards for exact-match projection reuse and its invalidation."""
from __future__ import annotations

import os
import re
import tempfile
import unittest
from unittest.mock import call, patch

from . import mdcg, nodefile, readcache
from .mdcos import MdCGOS


def frozen_exact(q, content, **kw):
    """Pre-optimization predicate, independent of all new projection helpers."""
    query = re.sub(r"\s+", "", q or "")
    return int(len(query) >= 2 and query in re.sub(r"\s+", "", content or ""))


class ExactTextCache(unittest.TestCase):
    def setUp(self):
        clean = {k: v for k, v in os.environ.items() if not k.startswith("MDCG_")}
        clean.update(MDCG_HOTCACHE="0", MDCG_READ_CACHE="1", MDCG_FRESHNESS="0",
                     MDCG_UNIFY_QUERY="0", MDCG_EN_ATOMS="0")
        self.env = patch.dict(os.environ, clean, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def make_store(self, bodies=None):
        temp = tempfile.TemporaryDirectory(prefix="exact_projection_")
        self.addCleanup(temp.cleanup)
        cg = MdCGOS(temp.name)
        self.addCleanup(cg.close)
        for nid, body in (bodies or {"a": "AB 与 BC 分开", "z": "A B\u2003C", "case": "abc"}).items():
            cg.add(nid, body, layer="knowledge", importance=0.5)
        cg.flush()
        return cg

    def docs(self, cg):
        return [(entry, *cg._read(entry)) for entry in list(cg.index["nodes"].values())]

    def score(self, cg, query):
        return cg._score(self.docs(cg), query, mdcg.bigrams(query))

    def test_raw_and_prepared_predicates_preserve_whitespace_and_case(self):
        cases = [("ABC", "A B\u2003C", 1), ("A\tB C", "ABC", 1),
                 ("ABC", "AB 与 BC 分开", 0), ("ABC", "abc", 0),
                 ("甲\n乙", "甲\u00a0乙", 1), ("甲乙", "甲\u3000乙", 1),
                 ("", "ABC", 0), (None, None, 0), ("A", "A", 0)]
        for query, body, expected in cases:
            with self.subTest(query=query, body=body):
                prepared = (mdcg.compact_exact_text(query), mdcg.compact_exact_text(body))
                self.assertEqual(mdcg.exact_hit_of(query, body), expected)
                self.assertEqual(mdcg.exact_hit_of(query, body, _prepared=prepared), expected)

    def test_production_results_and_scores_equal_frozen_predicate(self):
        cg = self.make_store()
        for mode in ("legacy", "jaccard"):
            with patch.object(mdcg, "SCORE_MODE", mode):
                for query in ("ABC", "A B C", "甲乙", "unmatched", "", "abc"):
                    with self.subTest(mode=mode, query=query):
                        cached_scores = self.score(cg, query)
                        new_search, _ = cg.search(query, k=3, judge=False, record=False)
                        new_rrf, _ = cg.search_rrf(query, k=3, paths=("lexical",), judge=False, record=False)
                        with patch.object(mdcg, "exact_hit_of", frozen_exact):
                            self.assertEqual(cached_scores, self.score(cg, query))
                            self.assertEqual(new_search, cg.search(query, k=3, judge=False, record=False)[0])
                            self.assertEqual(new_rrf, cg.search_rrf(query, k=3, paths=("lexical",), judge=False, record=False)[0])

    def test_warm_scoring_normalizes_only_query_once(self):
        cg = self.make_store()
        self.score(cg, "ABC")
        with patch.object(mdcg, "compact_exact_text", wraps=mdcg.compact_exact_text) as normalize:
            self.score(cg, "A B C")
        self.assertEqual(normalize.call_args_list, [call("A B C")])

    def test_one_write_invalidates_only_changed_document(self):
        cg = self.make_store()
        self.score(cg, "ABC")
        before = {path: record[1] for path, record in cg._exact_text_cache.items()}
        cg.add("a", "A\tB\nC 新内容", layer="knowledge", importance=0.5)
        cg.flush()
        with patch.object(mdcg, "compact_exact_text", wraps=mdcg.compact_exact_text) as normalize:
            rows = self.score(cg, "ABC")
        self.assertEqual(normalize.call_count, 2)  # one query, one changed document
        a = next(node for node, _ in rows if node["id"] == "a")
        self.assertEqual(a[mdcg.EXACT_HIT_KEY], 1)
        for path, record in cg._exact_text_cache.items():
            if path != cg.index["nodes"]["a"]["path"]:
                self.assertIs(record[1], before[path])

    def test_clear_removes_projection_without_changing_legacy_count(self):
        cg = self.make_store()
        cg.search_rrf("ABC", paths=("lexical",), judge=False, record=False)
        expected = sum(len(getattr(cg, name, {})) for name in
                       ("_read_cache", "_norm_bigrams_cache", "_positive_body_cache"))
        self.assertTrue(cg._exact_text_cache)
        self.assertTrue(cg._like_lower_cache)
        self.assertEqual(readcache.clear(cg), expected)
        self.assertFalse(cg._exact_text_cache)
        self.assertFalse(cg._like_lower_cache)
        self.assertEqual(readcache.clear(cg), 0)

    def test_short_query_does_not_normalize_documents(self):
        cg = self.make_store()
        with patch.object(cg, "_doc_exact_text", side_effect=AssertionError("unnecessary projection")):
            rows = self.score(cg, "A")
        self.assertTrue(all(node[mdcg.EXACT_HIT_KEY] == 0 for node, _ in rows))

    def test_opt_out_uses_uncached_projection(self):
        with patch.dict(os.environ, {"MDCG_READ_CACHE": "0"}):
            cg = self.make_store()
        self.assertFalse(hasattr(cg, "_exact_text_cache"))
        self.assertFalse(hasattr(cg, "_like_lower_cache"))
        rows = self.score(cg, "ABC")
        self.assertEqual({node["id"]: node[mdcg.EXACT_HIT_KEY] for node, _ in rows},
                         {"a": 0, "z": 1, "case": 0})

    def test_instances_with_same_relative_path_are_isolated(self):
        first = self.make_store({"same": "A B C"})
        second = self.make_store({"same": "D E F"})
        self.assertEqual(self.score(first, "ABC")[0][0][mdcg.EXACT_HIT_KEY], 1)
        self.assertEqual(self.score(second, "ABC")[0][0][mdcg.EXACT_HIT_KEY], 0)
        self.assertIsNot(first._exact_text_cache, second._exact_text_cache)

    def test_reinstall_does_not_keep_hidden_projection_cache(self):
        cg = self.make_store()
        entry = next(iter(cg.index["nodes"].values()))
        cg._doc_exact_text(entry, "A B C")
        cg._like_body_lower(entry, "A B C")
        cg._doc_norm_bigrams(entry, "A B C")
        readcache.install(cg)
        readcache.clear(cg)
        self.assertEqual(cg._doc_exact_text(entry, "D E F"), "DEF")
        self.assertEqual(cg._like_body_lower(entry, "DIFFERENT"), "different")
        readcache.clear(cg)
        self.assertEqual(cg._positive_body(entry, "NEW BODY"), "NEW BODY")
        self.assertEqual(cg._doc_norm_bigrams(entry, "NEW BODY"),
                         mdcg.bigrams(mdcg.normalize_en("NEW BODY")))

    def test_lowercase_projection_preserves_old_like_predicate(self):
        cg = self.make_store({"same": "# 正文：İΣ Alpha 中文\n# 不适用条件：Forbidden"})
        entry, fm, body = self.docs(cg)[0]
        fm["tags"] = ["MixedTag"]
        # issue #636（2026-10-23）：_like_body_lower 现在过 fold_accents（重音折叠），
        # 判据随之重述——期望值用同一折叠口径计算，而不是旧的无折叠 lower()。
        lower = mdcg.fold_accents(nodefile.positive_body(body)).lower()
        raw_lower = nodefile.positive_body(body).lower()
        for terms in ([], ["alpha"], ["Alpha"], ["i\u0307"], ["中文"],
                      ["forbidden"], ["mixedtag"], ["absent"]):
            with self.subTest(terms=terms):
                # issue #636 后两条 path 的 body 侧口径不同（这是刻意的）：
                #   无 body_lower 的旧分支仍用裸 lower()；
                #   传 _like_body_lower 的缓存分支用 fold_accents 后的 lower()。
                # 故期望值分开算——断言的是「每条 path 与它自己的归一化逐位一致」。
                expected_raw = any(t in raw_lower or t.lower() in "mixedtag" for t in terms)
                expected_folded = any(t in lower or t.lower() in "mixedtag" for t in terms)
                self.assertEqual(cg._like(body, fm, terms), expected_raw)
                self.assertEqual(cg._like(body, fm, terms, entry=entry,
                                         body_lower=cg._like_body_lower), expected_folded)
        self.assertTrue(cg._like(body, fm, [], index_keys={"hit": True},
                                 body_lower=lambda *_: self.fail("index hit should return early")))

    def test_lowercase_warm_reuse_and_single_write_invalidation(self):
        cg = self.make_store({"a": "Alpha OLD", "b": "Alpha OTHER"})
        cg.search_rrf("alpha", paths=("lexical",), judge=False, record=False)
        # BM25 并入默认检索后，首次 search 会为 bm25 索引投影一次正文（之后走缓存）。
        # 故先**预热一次** search，再断言「热态下不再重复投影」——意图不变（热复用零投影）。
        cg.search("alpha", judge=False, record=False)
        before = dict(cg._like_lower_cache)
        with patch.object(cg, "_positive_body", wraps=cg._positive_body) as project:
            cg.search("alpha", judge=False, record=False)
            self.assertEqual(project.call_count, 0)
            cg.add("a", "Alpha NEW", layer="knowledge", importance=0.5)
            cg.flush()
            hits, _ = cg.search_rrf("alpha new", paths=("lexical",), judge=False, record=False)
            self.assertEqual(project.call_count, 1)
        self.assertIn("a", [hit[0]["id"] for hit in hits])
        other = cg.index["nodes"]["b"]["path"]
        self.assertIs(cg._like_lower_cache[other][1], before[other][1])
        changed = cg.index["nodes"]["a"]["path"]
        self.assertIn("new", cg._like_lower_cache[changed][1])
        self.assertNotIn("old", cg._like_lower_cache[changed][1])

    def test_rebuild_after_external_write_invalidates_both_projections(self):
        cg = self.make_store({"same": "A B C Alpha"})
        cg.search_rrf("alpha", paths=("lexical",), judge=False, record=False)
        entry = cg.index["nodes"]["same"]
        path = os.path.join(cg.root, entry["path"])
        with open(path, encoding="utf-8") as stream:
            original = stream.read()
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(original.replace("A B C Alpha", "D E F Beta"))
        cg.rebuild_index()
        hits, _ = cg.search_rrf("beta", paths=("lexical",), judge=False, record=False)
        self.assertIn("same", [hit[0]["id"] for hit in hits])
        self.assertIn("DEF", cg._doc_exact_text(entry, cg._read(entry)[1]))
        self.assertNotIn("ABC", cg._doc_exact_text(entry, cg._read(entry)[1]))


if __name__ == "__main__":
    unittest.main()
