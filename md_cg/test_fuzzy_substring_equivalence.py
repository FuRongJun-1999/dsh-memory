"""Runtime equivalence tests for graded substring retrieval."""
import itertools
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from . import mdcos, nodefile


def exhaustive_degree(term, text):
    """Definition-based oracle: enumerate every qualifying substring."""
    if not term or not text:
        return 0.0
    if term in text:
        return 1.0
    longest = max((end - start
                   for start in range(len(term))
                   for end in range(start + 2, len(term) + 1)
                   if end - start < len(term) and term[start:end] in text),
                  default=0)
    return 0.5 * longest / len(term)


def oracle_coverage(weights, text, prepared=None):
    numerator = denominator = 0.0
    for term, weight in (weights or {}).items():
        if str(term).startswith("__") or weight <= 0:
            continue
        denominator += weight
        numerator += weight * exhaustive_degree(str(term), text)
    return numerator / denominator if denominator else 0.0


class FuzzySubstringEquivalence(unittest.TestCase):
    def test_all_short_strings(self):
        words = ["".join(chars) for size in range(5)
                 for chars in itertools.product("a中 ", repeat=size)]
        for term in words:
            cache = {}
            for text in words:
                expected = exhaustive_degree(term, text)
                self.assertEqual(mdcos._term_degree(term, text), expected,
                                 (term, text))
                self.assertEqual(mdcos._term_degree(term, text, cache), expected,
                                 (term, text, "prepared"))

    def test_unicode_and_long_random_matches(self):
        rng = random.Random(20261010)
        alphabet = "abc甲乙丙丁 🙂\n\t\u0301"
        for _ in range(700):
            term = "".join(rng.choices(alphabet, k=rng.randrange(1, 80)))
            text = "".join(rng.choices(alphabet, k=rng.randrange(140)))
            if rng.random() < 0.7:
                start = rng.randrange(len(term))
                end = rng.randrange(start + 1, len(term) + 1)
                text += term[start:end]
            self.assertEqual(mdcos._term_degree(term, text, {}),
                             exhaustive_degree(term, text), (term, text))

    def test_weighted_scores_and_query_isolation(self):
        weights = {"甲乙丙丁": 1.0, "abcabc": 0.37, 123: 0.2,
                   "__source__": "ignored", "negative": -0.2, "zero": 0}
        original = dict(weights)
        first = mdcos._prepare_coverage(weights)
        second = mdcos._prepare_coverage(weights)
        self.assertIsNot(first[0][0][2], second[0][0][2])
        for text in ("", "甲乙", "abcabc 123", "丙丁 abc", "完全无关", None):
            expected = oracle_coverage(weights, text)
            self.assertEqual(mdcos._weighted_coverage(weights, text), expected)
            self.assertEqual(mdcos._weighted_coverage(weights, text, first), expected)
        self.assertEqual(weights, original)

    def test_long_terms_do_not_retain_substrings(self):
        term = "甲" * 100 + "乙"
        cache = {}
        self.assertEqual(mdcos._term_degree(term, "甲" * 70, cache),
                         0.5 * 70 / len(term))
        self.assertEqual(cache, {})

    def test_near_exact_matches_on_both_edges(self):
        for term in ("abc", "甲乙丙丁戊己", "甲乙丙丁" * 15 + "末", "x" * 100 + "y"):
            for text in (term[:-1], term[1:]):
                self.assertEqual(mdcos._term_degree(term, text, {}),
                                 0.5 * (len(term) - 1) / len(term))

    def test_fused_production_paths_match_oracle(self):
        with tempfile.TemporaryDirectory(prefix="fuzzy_equivalence_") as temp:
            root = Path(temp)
            (root / "knowledge").mkdir()
            fixtures = {
                "exact": ("甲乙丙丁", "# 生效条件：甲乙丙丁\n甲乙丙丁 图片"),
                "partial": ("甲乙", "# 生效条件：甲乙\n甲乙 图像"),
                "negative": ("甲乙丙丁", "# 生效条件：甲乙丙丁\n# 不适用条件：甲乙丙丁\n其他"),
                "unrelated": ("其他", "# 生效条件：天气\n天空晴朗"),
            }
            for nid, (tag, content) in fixtures.items():
                fm = {"id": nid, "layer": "knowledge", "tags": [tag],
                      "created_at": 1800000000.0, "importance": 0.5}
                (root / "knowledge" / (nid + ".md")).write_text(
                    nodefile.dumps(fm, content), encoding="utf-8")
            cg = mdcos.MdCGOS(str(root))
            options = dict(k=4, paths=("lexical", "fuzzy", "semantic", "goal"),
                           goal_text="甲乙丙丁", record=False, judge=False)
            for flag in ("0", "1"):
                with self.subTest(candidate_index=flag), patch.dict("os.environ", {
                        "MDCG_HOTCACHE": "0", "MDCG_FRESHNESS": "0",
                        "MDCG_RRF_CANDIDATES": flag}):
                    actual = cg.search_rrf("甲乙丙丁", **options)
                    with patch.object(mdcos, "_weighted_coverage", oracle_coverage):
                        expected = cg.search_rrf("甲乙丙丁", **options)
                    # Lazy construction and a reused index have different work
                    # counters/timings. Preserve the comparison of every card,
                    # score, semantic field and candidate-path cardinality.
                    for result in (actual, expected):
                        report = result[1].get("rrf_candidates", {})
                        for key in ("build_reads", "update_reads", "index_ms", "cached_nodes"):
                            report.pop(key, None)
                        for detail in report.get("paths", {}).values():
                            detail.pop("early_bypass", None)
                    self.assertEqual(actual, expected)
            cg.close()


if __name__ == "__main__":
    unittest.main()
