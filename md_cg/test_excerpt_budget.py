"""Budget maximality plus real recall and MCP evidence-retention guards."""
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
import unittest
from unittest.mock import patch

from . import mdcos


def oracle(text, budget):
    if not text or budget <= 0:
        return ""
    if mdcos.est_tokens(text) <= budget:
        return text
    return max((text[:i].rstrip() + "…" for i in range(len(text) + 1)
                if mdcos.est_tokens(text[:i].rstrip() + "…") <= budget), key=len)


def frozen_excerpt(text, budget):
    """Pre-fix implementation, used solely as a negative control."""
    if not text or budget <= 0:
        return ""
    if mdcos.est_tokens(text) <= budget:
        return text
    cost = mdcos.est_tokens("…")
    body_budget = budget - cost
    if body_budget <= 0:
        return "…" if cost <= budget else ""
    approx = min(len(text), max(1, int(body_budget / .6)))
    while approx > 1 and mdcos.est_tokens(text[:approx]) > body_budget:
        approx -= max(1, approx // 10)
    keep = max(0, approx)
    out = text[:keep].rstrip() + "…"
    if mdcos.est_tokens(out) > budget:
        while keep > 1 and mdcos.est_tokens(text[:keep].rstrip() + "…") > budget:
            keep -= max(1, keep // 10)
        out = text[:keep].rstrip() + "…"
    return out


class ExcerptBudget(unittest.TestCase):
    def setUp(self):
        clean = {k: v for k, v in os.environ.items() if not k.startswith("MDCG_")}
        clean.update(MDCG_HOTCACHE="0", MDCG_FRESHNESS="0", MDCG_UNIFY_QUERY="0",
                     MDCG_EN_ATOMS="0", MDCG_AUX_ROOT="")
        env = patch.dict(os.environ, clean, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def store(self):
        temp = tempfile.TemporaryDirectory(prefix="excerpt_evidence_")
        self.addCleanup(temp.cleanup)
        cg = mdcos.MdCGOS(temp.name)
        self.addCleanup(cg.close)
        content = "anchorrecord " + "a" * 160 + " evidenceKEEP42 " + "tail" * 500
        cg.add("english_evidence", content, layer="knowledge", verification_basis="data",
               verification_state="doubted", source="synthetic:excerpt", session="excerpt-test")
        cg.flush()
        return cg

    def test_estimate_preserves_frozen_formula(self):
        rng = random.Random(20261012)
        for _ in range(400):
            text = "".join(rng.choice("ab甲乙あカ…\t\n\u2003🙂") for _ in range(rng.randrange(200)))
            cjk = sum(0x4e00 <= ord(c) <= 0x9fff or 0x3040 <= ord(c) <= 0x30ff for c in text)
            expected = int(cjk * .6 + (len(text) - cjk) / 4) + 1 if text else 0
            self.assertEqual(mdcos.est_tokens(text), expected)

    def test_ascii_uses_entire_budget_and_keeps_fitting_evidence(self):
        text = "a" * 160 + " evidenceKEEP42 " + "tail" * 500
        actual = mdcos.excerpt_tokens(text, 80)
        self.assertIn("evidenceKEEP42", actual)
        self.assertEqual(len(actual), 319)
        self.assertEqual(mdcos.est_tokens(actual), 80)
        self.assertTrue(actual.endswith("…"))
        self.assertEqual(actual, oracle(text, 80))

    def test_longest_prefix_matches_exhaustive_oracle(self):
        rng = random.Random(20261012)
        texts = ["a" * 100, "甲" * 100, "あ" * 100, "🙂" * 100,
                 "abc   def\n ghi" * 8, "甲\u2003乙\tABC" * 12, " " * 100]
        texts += ["".join(rng.choice("ab甲乙あカ… \t\n\u2003🙂") for _ in range(90)) for _ in range(80)]
        for text in texts:
            for budget in (1, 2, 3, 7, 12, 20, 35, 80):
                with self.subTest(text=text[:12], budget=budget):
                    actual = mdcos.excerpt_tokens(text, budget)
                    self.assertEqual(actual, oracle(text, budget))
                    self.assertLessEqual(mdcos.est_tokens(actual), budget)

    def test_empty_nonpositive_and_full_fit_keep_contract(self):
        for text in (None, "", "  fits\n", "甲乙🙂"):
            for budget in (-10, 0):
                self.assertEqual(mdcos.excerpt_tokens(text, budget), "")
            if text:
                self.assertEqual(mdcos.excerpt_tokens(text, mdcos.est_tokens(text)), text)
            else:
                self.assertEqual(mdcos.excerpt_tokens(text, 4), "")

    def test_real_recall_preserves_fitting_marker_and_metadata(self):
        cg = self.store()
        for use_rrf in (False, True):
            with self.subTest(use_rrf=use_rrf):
                out = cg.recall("anchorrecord", budget_tokens=80, max_item_tokens=80,
                                use_rrf=use_rrf, paths=("lexical",), judge=False)
                self.assertEqual([r["id"] for r in out["pack"]], ["english_evidence"])
                row = out["pack"][0]
                self.assertIn("evidenceKEEP42", row["content"])
                self.assertTrue(row["truncated"])
                self.assertEqual(row["metadata"]["source"], "synthetic:excerpt")
                self.assertEqual(row["metadata"]["verification_state"], "doubted")
                self.assertEqual(row["tokens"], mdcos.est_tokens(row["content"]))
                self.assertEqual(out["tokens_used"], 80)
                self.assertLessEqual(out["tokens_used"], out["budget"])
                self.assertEqual(out["skipped"], [])

    def test_mcp_stdio_returns_retained_evidence(self):
        cg = self.store()
        root = cg.root
        cg.close()
        messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                        "name": "mdcg_recall", "arguments": {"query": "anchorrecord",
                        "budget_tokens": 80, "max_item_tokens": 80, "causal": False,
                        "temporal": False, "judge": False}}},
                    {"jsonrpc": "2.0", "id": 3, "method": "shutdown"}]
        env = dict(os.environ, MDCG_ROOT=str(root), MDCG_LEGACY_ENV_AUTH="1",
                   MDCG_ACTOR="excerpt-test", MDCG_AUX_ROOT=str(Path(root) / "sidecar"))
        proc = subprocess.run([sys.executable, "-X", "utf8", "-m", "md_cg.mcp_server"],
                              input="\n".join(json.dumps(m) for m in messages) + "\n",
                              capture_output=True, encoding="utf-8", env=env, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        reply = next(json.loads(line) for line in proc.stdout.splitlines() if json.loads(line).get("id") == 2)
        result = json.loads(reply["result"]["content"][0]["text"])
        self.assertEqual([r["id"] for r in result["pack"]], ["english_evidence"])
        self.assertIn("evidenceKEEP42", result["pack"][0]["content"])
        self.assertEqual(result["tokens_used"], 80)


def mutations(output):
    cases = [("restore_old_conservative_cut", "test_ascii_uses_entire_budget_and_keeps_fitting_evidence", frozen_excerpt),
             ("ignore_budget", "test_longest_prefix_matches_exhaustive_oracle", lambda text, budget: text),
             ("drop_ellipsis", "test_ascii_uses_entire_budget_and_keeps_fitting_evidence",
              lambda text, budget: original(text, budget).removesuffix("…")),
             ("bypass_nonpositive_budget", "test_empty_nonpositive_and_full_fit_keep_contract", lambda text, budget: text)]
    original = mdcos.excerpt_tokens
    def run(name):
        stream = io.StringIO()
        result = unittest.TextTestRunner(stream=stream, failfast=True).run(ExcerptBudget(name))
        owner = lambda t: getattr(t, "test_case", t)._testMethodName
        return {"failures": [owner(t) for t, _ in result.failures], "errors": [owner(t) for t, _ in result.errors],
                "skips": [owner(t) for t, _ in result.skipped],
                "log": stream.getvalue().replace(str(Path(__file__).resolve().parents[1]), "<checkout>")}
    baseline = {name: run(name) for name in dict.fromkeys(c[1] for c in cases)}
    readings = []
    for mutation, name, replacement in cases:
        with patch.object(mdcos, "excerpt_tokens", replacement):
            reading = run(name)
        reading.update(mutation=mutation, expected_test=name,
                       killed=bool(reading["failures"]) and set(reading["failures"]) == {name}
                       and not reading["errors"] and not reading["skips"])
        readings.append(reading)
        print(f"{mutation}: intended assertion killed={reading['killed']}")
    restored = {name: run(name) for name in baseline}
    passed = all(r["killed"] for r in readings) and not any(
        row[field] for state in (baseline, restored) for row in state.values() for field in ("failures", "errors", "skips"))
    if output:
        Path(output).write_text(json.dumps(dict(baseline=baseline, mutations=readings,
                                                restored=restored, passed=passed), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mutate", action="store_true")
    parser.add_argument("--output")
    args, rest = parser.parse_known_args()
    if args.mutate:
        raise SystemExit(mutations(args.output))
    unittest.main(argv=[sys.argv[0], *rest])
