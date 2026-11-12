"""BM25 targeted fault injection against existing production runtime guards.

Run with ``python -X utf8 -m md_cg.test_bm25_mutations --output report.json``.
Each source anchor must occur exactly once. Mutants execute only in the imported
module's memory; no production source is rewritten. All ten guards run for every
mutant. A kill requires the exact declared test AND assertion, with no errors,
skips, extra failures or surviving mutants. Baseline and restoration must pass.
This is a bounded mutation set, not a general mutation-coverage measurement.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
import unittest
from unittest.mock import patch


GUARDS = (
    "test_hand_calculated_frequency_saturation_and_idf",
    "test_length_normalization_and_missing_query",
    "test_warm_query_hydrates_only_matches_and_default_is_unchanged",
    "test_block_bounds_match_exhaustive_scores_with_outliers_and_edits",
    "test_equal_score_blocks_prune_without_changing_top50_or_match_count",
    "test_varied_lengths_choose_exhaustive_without_building_block_tables",
    "test_access_changes_invalidate_reused_candidate_pool",
    "test_shared_term_storage_preserves_tf_and_releases_removed_terms",
    "test_pool_reuse_invalidates_on_write_and_bypasses_clock_filters",
    "test_parallel_build_keeps_existing_cache_and_retries_failed_reads",
)

# Expected failures are fixed here, never learned from a mutant's outcome.
# Keys name existing tests; values name the actual assert statement that must fail.
MUTATIONS = (
    ("M0", "discard term frequency", "self.post[canonical][path] = count",
     "self.post[canonical][path] = 1", {
         GUARDS[0]: 'self.assertAlmostEqual(scores["a"], idf * 4.4 / 3.2)',
         GUARDS[7]: 'self.assertEqual([idx.post["shared"][p] for p in paths], [1, 5])'}),
    ("M1", "underestimate block bounds", "bounds[block] += max(",
     "bounds[block] += min(", {
         GUARDS[3]: "self.assertEqual(actual, reference, (edited, query))"}),
    ("M2", "disable exact pruning",
     "if len(best) == LIMIT and (-bounds[block], *self.block_best[block]) > key(best[-1]):",
     "if False:", {
         GUARDS[4]: 'self.assertGreater(info["blocks_skipped"], 0)'}),
    ("M3", "disable complex-distribution cost guard",
     "self.block_policy[term] = len(pairs) <= BLOCK_PAIR_LIMIT",
     "self.block_policy[term] = True", {
         GUARDS[5]: 'self.assertNotIn("algorithm", meta["bm25"])'}),
    ("M4", "omit identity from eligibility cache key",
     "key = (dirty.write_gen, dirty.broad_gen, access_key(cg),\n"
     "           id(principal), HotCache._canon(vars(principal)) if principal else None,\n"
     '           getattr(method, "__func__", method), HotCache._canon(options))',
     "key = (dirty.write_gen, dirty.broad_gen,\n"
     '           getattr(method, "__func__", method), HotCache._canon(options))', {
         GUARDS[6]: 'self.assertEqual({e["path"] for e in bm25.candidate_pool(cg)}, {paths["public"]})'}),
    ("M5", "omit write generations from eligibility cache key",
     "key = (dirty.write_gen, dirty.broad_gen, access_key(cg),",
     "key = (0, 0, access_key(cg),", {
         GUARDS[8]: 'self.assertEqual({n[0]["id"] for n in self.search("freshword")[0]}, {"fresh"})'}),
    ("M6", "cache clock-dependent validity pool",
     'or options.get("validity")', "or False", {
         GUARDS[8]: "self.assertEqual(candidates.call_count, 4)"}),
    ("M7", "evict a preexisting read-cache entry",
     "if not existed[0]:", "if True:", {
         GUARDS[9]: 'self.assertIs(self.cg._read_cache[self.cg.index["nodes"]["b"]["path"]], saved)'}),
    ("M8", "retain duplicate per-document TF Counter",
     'self.docs[path] = (getattr(dirty, "write_gen", 0), tuple(doc_terms), length,',
     'self.docs[path] = (getattr(dirty, "write_gen", 0), tf, length,', {
         GUARDS[7]: "self.assertIsInstance(idx.docs[path][1], tuple)"}),
)


class GuardResult(unittest.TextTestResult):
    """Record exact assertion sites; import errors cannot count as killed faults."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sites = {}

    def addFailure(self, test, err):
        super().addFailure(test, err)
        sites = [frame for frame in traceback.extract_tb(err[2])
                 if Path(frame.filename).name == "test_bm25.py"]
        self.sites[test._testMethodName] = sites[-1].line if sites else ""


def _suite(case):
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2,
                                    resultclass=GuardResult).run(
        unittest.TestSuite(case(name) for name in GUARDS))
    return {
        "tests_run": result.testsRun,
        "failures": dict(result.sites),
        "errors": [test.id() for test, _text in result.errors],
        "skipped": [test.id() for test, _reason in result.skipped],
        "log": stream.getvalue(),
    }


def _matches(result, expected):
    return (result["tests_run"] == len(GUARDS)
            and result["failures"] == expected
            and not result["errors"] and not result["skipped"])


def _run():
    from . import bm25
    from .test_bm25 import BM25Tests

    source = Path(bm25.__file__).read_text(encoding="utf-8")
    report = {"source_sha256_lf": hashlib.sha256(source.encode()).hexdigest(),
              "guard_sha256_lf": hashlib.sha256(Path(__file__).with_name(
                  "test_bm25.py").read_text(encoding="utf-8").encode()).hexdigest(),
              "guards": list(GUARDS), "mutations": [], "passed": False}
    compiled = []
    for mid, label, old, new, expected in MUTATIONS:
        hits = source.count(old)
        if hits != 1:
            report["anchor_error"] = {"id": mid, "hits": hits, "expected": 1}
            print(f"ANCHOR-MISS {mid}: {hits} occurrences (expected 1)", flush=True)
            return report, 2
        compiled.append(compile(source.replace(old, new, 1), bm25.__file__, "exec"))
    # Keep the original module dictionary. Existing call sites retain the same
    # module object, and each mutant gets a fresh class plus fresh module globals.
    saved = dict(vars(bm25))
    baseline = report["baseline"] = _suite(BM25Tests)
    print(f"BASELINE: {baseline['tests_run']} guards; "
          f"failures={len(baseline['failures'])}, errors={len(baseline['errors'])}", flush=True)
    if not _matches(baseline, {}):
        print(baseline["log"], flush=True)
        return report, 1
    for (mid, label, _old, _new, expected), code in zip(MUTATIONS, compiled):
        started = time.perf_counter()
        try:
            exec(code, vars(bm25))
            result = _suite(BM25Tests)
        finally:
            vars(bm25).clear()
            vars(bm25).update(saved)
        hit = _matches(result, expected)
        report["mutations"].append({"id": mid, "fault": label,
            "expected_failures": expected, "actual": result,
            "passed": hit, "elapsed_s": time.perf_counter() - started})
        print(f"{'PASS' if hit else 'FAIL'} {mid} {label}: "
              f"expected={sorted(expected)} actual={sorted(result['failures'])} "
              f"errors={len(result['errors'])}", flush=True)
        if not hit:
            print(result["log"], flush=True)
    restored = report["restored"] = _suite(BM25Tests)
    report["passed"] = (all(row["passed"] for row in report["mutations"])
                        and _matches(restored, {})
                        and Path(bm25.__file__).read_text(encoding="utf-8") == source)
    report["killed"] = sum(row["passed"] for row in report["mutations"])
    print(f"RESTORED: {restored['tests_run']} guards; "
          f"failures={len(restored['failures'])}, errors={len(restored['errors'])}", flush=True)
    print(f"TARGETED MUTATIONS: {report['killed']}/{len(MUTATIONS)}; "
          f"{'PASS' if report['passed'] else 'FAIL'}", flush=True)
    return report, 0 if report["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write all raw guard logs as JSON")
    args = parser.parse_args()
    network_attempts = []

    def deny_network(event, _args):
        if event in ("socket.connect", "socket.getaddrinfo", "socket.sendto"):
            network_attempts.append(event)
            raise RuntimeError("Network is disabled for BM25 mutation acceptance")

    sys.addaudithook(deny_network)
    # Set every data root before importing production code, including crypto's
    # import-time master-key path. All data is synthetic and inside this sandbox.
    with tempfile.TemporaryDirectory(prefix="bm25_mutations_") as sandbox:
        with patch.dict(os.environ, {
                "MDCG_ROOT": str(Path(sandbox) / "pool"),
                "MDCG_AUX_ROOT": str(Path(sandbox) / "auxiliary"),
                "MDCG_DATA_ROOT": str(Path(sandbox) / "data"),
                "DSH_HOME": str(Path(sandbox) / "dsh"),
                "MDCG_BM25_BLOCK_MAX": "1", "MDCG_BM25_POOL_CACHE": "1"}):
            for key in ("MDCG_TOKEN", "MDCG_POLICY_FILE", "MDCG_TEST_LIVE_ROOT"):
                os.environ.pop(key, None)
            report, code = _run()
    report["network_attempts"] = network_attempts
    if network_attempts:
        report["passed"], code = False, 1
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
