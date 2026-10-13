"""Runtime guards for query excerpts, source offsets, budget and native recall."""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from . import mdcos, query_excerpt as qe


class QueryExcerpt(unittest.TestCase):
    def check_spans(self, text, result):
        spans = result["spans"]
        self.assertEqual(spans, sorted(spans), "source order")
        for index, (start, end) in enumerate(spans):
            self.assertTrue(0 <= start < end <= len(text), "valid original offsets")
            if index:
                self.assertLessEqual(spans[index - 1][1], start, "non-overlapping")
        if not result["fallback"]:
            self.assertEqual(result["content"], qe._render(text, spans), "exact source provenance")

    def test_tail_evidence_survives(self):
        text = "Unrelated introduction. " * 200 + "\n\nRhea owns a sapphire key.\n\n" + "Unrelated ending. " * 100
        result = qe.select(text, "Which key does Rhea own?", 80)
        self.assertIn("sapphire key", result["content"], "tail evidence retained")
        self.assertNotIn("sapphire key", mdcos.excerpt_tokens(text, 80))
        self.check_spans(text, result)

    def test_cjk_tail_and_negation_are_preserved(self):
        text = "闲话天气。" * 300 + "\n\n林岚不能使用蓝色钥匙，因为权限已被撤销。\n\n" + "无关背景。" * 300
        result = qe.select(text, "林岚蓝色钥匙权限", 80)
        self.assertIn("林岚不能使用蓝色钥匙，因为权限已被撤销。", result["content"])
        self.check_spans(text, result)

    def test_distinct_query_facets(self):
        text = ("Rhea discusses ordinary travel.\n\n" * 30
                + "Rhea owns a sapphire key.\n\n" + "Unrelated bridge.\n\n" * 30
                + "The launch deadline is November 14.\n\n" + "Unrelated ending. " * 100)
        result = qe.select(text, "Rhea sapphire key launch deadline November", 90)
        self.assertIn("sapphire key", result["content"], "first facet")
        self.assertIn("November 14", result["content"], "second facet")
        self.check_spans(text, result)

    def test_long_paragraph_keeps_query_anchor(self):
        text = "background " * 1000 + " The copper beacon is powered by sunlight. " + "padding " * 1000
        result = qe.select(text, "copper beacon powered sunlight", 100)
        self.assertIn("copper beacon", result["content"], "long paragraph anchor")
        self.check_spans(text, result)

    def test_small_empty_and_no_match_fall_back_explicitly(self):
        text = "background without the requested marker. " * 50
        for query, budget, reason in (("", 40, "empty_query"), ("sapphire", 40, "no_query_match"),
                                      ("background", 7, "small_budget")):
            result = qe.select(text, query, budget)
            self.assertEqual(result["fallback"], reason)
            self.assertEqual(result["content"], mdcos.excerpt_tokens(text, budget))
        self.assertEqual(qe.select(text, "background", 0)["content"], "")

    def test_full_fit_is_byte_for_byte(self):
        text = "  Original 原文。\n\nİstanbul, 12:30. 🙂  "
        result = qe.select(text, "İstanbul", mdcos.est_tokens(text))
        self.assertEqual(result["content"], text)
        self.assertEqual(result["spans"], [[0, len(text)]])

    def test_budget_includes_gap_markers_and_random_unicode(self):
        rng = random.Random(20261013)
        for _ in range(80):
            text = "\n\n".join("".join(rng.choice("ab甲乙İ🙂 ") for _ in range(rng.randrange(10, 120)))
                                 + " sapphire " for _ in range(8))
            for budget in (1, 7, 16, 30, 60):
                result = qe.select(text, "甲 sapphire", budget)
                self.assertLessEqual(mdcos.est_tokens(result["content"]), budget, "complete output budget")
                if result["spans"]:
                    self.check_spans(text, result)

    def test_deterministic_and_original_order(self):
        text = "a b key blue.\n\n" * 20 + "sapphire launch.\n\n" + "a b key blue.\n\n" * 20
        first = qe.select(text, "key sapphire launch", 70)
        self.assertEqual(first, qe.select(text, "key sapphire launch", 70))
        self.check_spans(text, first)

    def store(self):
        temp = tempfile.TemporaryDirectory(prefix="query_excerpt_")
        self.addCleanup(temp.cleanup)
        cg = mdcos.MdCGOS(temp.name)
        self.addCleanup(cg.close)
        text = "Rhea profile. " * 500 + "\n\nRhea owns a sapphire key.\n\n" + "Ordinary details. " * 200
        cg.add("rhea", text, layer="knowledge", source="fixture:source", verification_state="doubted")
        cg.flush()
        return cg, text

    def test_real_recall_changes_excerpt_only(self):
        cg, _ = self.store()
        kw = dict(budget_tokens=80, max_item_tokens=80, paths=("bm25",), judge=False)
        old = cg.recall("Rhea sapphire key", **kw)
        new = cg.recall("Rhea sapphire key", excerpt_strategy="query", **kw)
        self.assertEqual([r["id"] for r in old["pack"]], [r["id"] for r in new["pack"]])
        self.assertNotIn("sapphire key", old["pack"][0]["content"])
        self.assertIn("sapphire key", new["pack"][0]["content"], "native recall keeps tail evidence")
        for field in ("id", "score", "frontmatter", "provenance", "metadata"):
            self.assertEqual(old["pack"][0][field], new["pack"][0][field])
        self.assertEqual(new["pack"][0]["excerpt"]["strategy"], "query")
        self.assertLessEqual(new["tokens_used"], 80)

    def test_legacy_default_and_invalid_option(self):
        cg, _ = self.store()
        kw = dict(budget_tokens=80, max_item_tokens=80, paths=("bm25",), judge=False)
        implicit = cg.recall("Rhea", **kw)
        explicit = cg.recall("Rhea", excerpt_strategy="prefix", **kw)
        for field in ("pack", "tokens_used", "budget", "skipped", "recent"):
            self.assertEqual(implicit[field], explicit[field])
        with self.assertRaisesRegex(ValueError, "excerpt_strategy"):
            cg.recall("Rhea", excerpt_strategy="invented", **kw)

    def test_stdio_mcp_recall_and_core_read_use_query_excerpts(self):
        cg, _ = self.store()
        root = cg.root
        cg.close()
        requests = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}]
        for ident, name, args in (
            (2, "mdcg_recall", {"query": "Rhea sapphire key", "budget_tokens": 80,
                                "max_item_tokens": 80, "bm25": True, "causal": False, "temporal": False,
                                "excerpt_strategy": "query"}),
            (3, "cg", {"op": "read", "query": "Rhea sapphire key", "budget_tokens": 80,
                       "bm25": True, "excerpt_strategy": "query"}),
        ):
            requests.append({"jsonrpc": "2.0", "id": ident, "method": "tools/call",
                             "params": {"name": name, "arguments": args}})
        requests.append({"jsonrpc": "2.0", "id": 4, "method": "shutdown"})
        env = dict(os.environ, MDCG_ROOT=str(root), MDCG_LEGACY_ENV_AUTH="1",
                   MDCG_ACTOR="query-test", MDCG_AUX_ROOT=str(Path(root) / "sidecar"))
        proc = subprocess.run([sys.executable, "-X", "utf8", "-m", "md_cg.mcp_server"],
                              input="\n".join(json.dumps(r) for r in requests) + "\n",
                              capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=40)
        self.assertEqual(proc.returncode, 0, proc.stderr[-1500:])
        replies = {r["id"]: r for line in proc.stdout.splitlines() if "id" in (r := json.loads(line))}
        for ident in (2, 3):
            value = json.loads(replies[ident]["result"]["content"][0]["text"])
            self.assertIn("sapphire key", value["pack"][0]["content"], "real stdio returns evidence")
            self.assertEqual(value["pack"][0]["excerpt"]["strategy"], "query")
            self.assertLessEqual(value["tokens_used"], 80)


def run_suite(verbosity=1):
    return unittest.TextTestRunner(verbosity=verbosity).run(unittest.defaultTestLoader.loadTestsFromTestCase(QueryExcerpt))


def mutations():
    source = Path(qe.__file__).read_text(encoding="utf-8")
    if not run_suite().wasSuccessful():
        return False
    cases = [
        ("ignore-query", 'terms = tuple(dict.fromkeys(tokenize(query or "")))[:MAX_TERMS]', 'terms = ()', "test_tail_evidence_survives"),
        ("ignore-budget", 'if est_tokens(trial) <= budget:', 'if True:', "test_budget_includes_gap_markers_and_random_unicode"),
        ("shift-offset", '"spans": [list(s) for s in spans]', '"spans": [[s[0] + 1, s[1]] for s in spans]', "test_tail_evidence_survives"),
        ("omit-selected-text", 'content = _render(text, spans)', 'content = "fabricated evidence"', "test_tail_evidence_survives"),
        ("whole-document", 'content = _render(text, spans)', 'content = text', "test_budget_includes_gap_markers_and_random_unicode"),
        ("always-prefix", 'if not terms or budget < 16:', 'if True:', "test_real_recall_changes_excerpt_only"),
    ]
    killed = 0
    for name, old, new, guard in cases:
        if source.count(old) != 1:
            raise AssertionError("mutation point must be unique: " + name)
        mutant = types.ModuleType("md_cg._query_excerpt_mutant")
        mutant.__package__ = "md_cg"
        exec(compile(source.replace(old, new, 1), str(qe.__file__), "exec"), mutant.__dict__)
        output = io.StringIO()
        with mock.patch.object(qe, "select", mutant.select):
            result = unittest.TextTestRunner(stream=output).run(QueryExcerpt(guard))
        caught = len(result.failures) == 1 and not result.errors and not result.skipped
        print(name, "assertion-red" if caught else "NOT-CAUGHT", guard)
        killed += int(caught)
    print(f"通过 {killed} / 失败 {len(cases) - killed}")
    restored = run_suite().wasSuccessful()
    unchanged = source == Path(qe.__file__).read_text(encoding="utf-8")
    print("restored guards", restored, "production source unchanged", unchanged)
    return killed == len(cases) and restored and unchanged


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mutate", action="store_true")
    args = parser.parse_args()
    if args.mutate:
        return 0 if mutations() else 1
    result = run_suite()
    print(f"通过 {result.testsRun - len(result.failures) - len(result.errors)} / 失败 {len(result.failures) + len(result.errors)}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
