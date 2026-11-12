"""Six bounded, in-memory fault injections for incremental BM25 maintenance.

Each mutant runs its predeclared runtime guard and must fail at the exact
assertion shown below. Errors, skips and unrelated failures do not count.
All six guards must pass before mutation and after restoring module globals.
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
import traceback
import unittest
from unittest.mock import patch


MUTATIONS = (
    ("I0", "omit removed-term invalidation", "self._note_block_update(path, old[1], removed=True)", "pass",
     "test_removed_query_term_rebuilds_its_old_block_bitmap",
     'self.assertNotIn(1, idx.term_blocks["second"])'),
    ("I1", "reuse stale TF/length pairs", "cached[block] = (bitmap, tuple(pairs))",
     "cached[block] = (bitmap, cached.get(block, (0, tuple(pairs)))[1])",
     "test_single_edit_repairs_only_local_cached_blocks",
     "self.assertEqual(actual, expected)"),
    ("I2", "reuse stale importance tie bound", "self.block_best[block] = best",
     "self.block_best[block] = self.block_best[block]",
     "test_importance_only_edit_refreshes_pruning_tie_bound",
     'self.assertEqual(actual[0][0]["id"], "tie0259")'),
    ("I3", "scatter delta documents into old holes",
     "slot = len(self.block_paths)\n                self.block_paths.append(path)",
     "slot = self.block_paths.index(None) if self.block_holes else len(self.block_paths)\n"
     "                if slot == len(self.block_paths):\n"
     "                    self.block_paths.append(path)\n"
     "                else:\n"
     "                    self.block_paths[slot] = path\n"
     "                    self.block_holes -= 1",
     "test_removed_pool_paths_keep_live_map_and_append_delta",
     "self.assertEqual(idx.ordinals[path], original_slots)"),
    ("I4", "disable bounded journal fallback",
     "if path not in self.block_updates and len(self.block_updates) >= BLOCK_UPDATE_LIMIT:",
     "if False:", "test_bounded_update_journal_falls_back_to_exact_full_layout",
     'self.assertTrue(info["block_layout_rebuilt"])'),
    ("I5", "never compact sparse slots",
     "return (self.block_paths is not None and len(self.block_paths) + extra\n"
     "                > max(2 * BLOCK_SIZE, 2 * len(self.docs)))",
     "return False", "test_large_pool_shrink_compacts_slots_and_remains_exact",
     'self.assertTrue(info["block_layout_rebuilt"])'),
)


class GuardResult(unittest.TextTestResult):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.sites = {}

    def addFailure(self, test, err):
        super().addFailure(test, err)
        sites = [f for f in traceback.extract_tb(err[2])
                 if Path(f.filename).name == "test_bm25_incremental.py"]
        self.sites[test._testMethodName] = sites[-1].line if sites else ""


def run_guards(names):
    from .test_bm25_incremental import IncrementalBlockTests
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=GuardResult).run(
        unittest.TestSuite(IncrementalBlockTests(name) for name in names))
    return {"tests_run": result.testsRun, "failures": result.sites,
            "errors": [test.id() for test, _text in result.errors],
            "skipped": [test.id() for test, _text in result.skipped], "log": stream.getvalue()}


def matches(result, count, expected):
    return (result["tests_run"] == count and result["failures"] == expected
            and not result["errors"] and not result["skipped"])


def run():
    from . import bm25
    source = Path(bm25.__file__).read_text(encoding="utf-8")
    report = {"source_sha256_lf": hashlib.sha256(source.encode()).hexdigest(),
              "guard_sha256_lf": hashlib.sha256(Path(__file__).with_name(
                  "test_bm25_incremental.py").read_text(encoding="utf-8").encode()).hexdigest(),
              "mutations": [], "passed": False}
    compiled = []
    for mid, _label, old, new, _test, _site in MUTATIONS:
        if source.count(old) != 1:
            report["anchor_error"] = {"id": mid, "hits": source.count(old)}
            return report
        compiled.append(compile(source.replace(old, new, 1), bm25.__file__, "exec"))
    saved = dict(vars(bm25))
    guards = [m[4] for m in MUTATIONS]
    report["baseline"] = baseline = run_guards(guards)
    print("BASELINE", baseline["tests_run"], "guards; failures", baseline["failures"], flush=True)
    if not matches(baseline, len(guards), {}):
        return report
    try:
        for (mid, label, _old, _new, test, site), code in zip(MUTATIONS, compiled):
            try:
                exec(code, vars(bm25))
                result = run_guards([test])
            finally:
                vars(bm25).clear()
                vars(bm25).update(saved)
            expected = {test: site}
            passed = matches(result, 1, expected)
            report["mutations"].append({"id": mid, "fault": label,
                "expected_failures": expected, "actual": result, "passed": passed})
            print("PASS" if passed else "FAIL", mid, label, result["failures"], flush=True)
            if not passed:
                print(result["log"], flush=True)
    finally:
        vars(bm25).clear()
        vars(bm25).update(saved)
    report["restored"] = restored = run_guards(guards)
    report["killed"] = sum(m["passed"] for m in report["mutations"])
    report["passed"] = (report["killed"] == len(MUTATIONS)
                        and matches(restored, len(guards), {})
                        and Path(bm25.__file__).read_text(encoding="utf-8") == source)
    print("RESTORED", restored["tests_run"], "guards; failures", restored["failures"], flush=True)
    print("TARGETED INCREMENTAL MUTATIONS", report["killed"], "/", len(MUTATIONS), flush=True)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    if args.output and args.output.exists():
        p.error("Use a new output; preserve previous evidence")
    attempts = []
    def deny_network(event, _args):
        if event in ("socket.connect", "socket.getaddrinfo", "socket.sendto"):
            attempts.append(event)
            raise RuntimeError("Network disabled for incremental BM25 mutation acceptance")
    sys.addaudithook(deny_network)
    with tempfile.TemporaryDirectory(prefix="bm25_incremental_mutations_") as temp:
        with patch.dict(os.environ, {
                "MDCG_ROOT": str(Path(temp) / "pool"), "DSH_HOME": str(Path(temp) / "dsh"),
                "MDCG_AUX_ROOT": str(Path(temp) / "auxiliary"),
                "MDCG_DATA_ROOT": str(Path(temp) / "data"), "MDCG_BM25_BLOCK_MAX": "1",
                "MDCG_BM25_POOL_CACHE": "1"}):
            for key in ("MDCG_TOKEN", "MDCG_POLICY_FILE", "MDCG_TEST_LIVE_ROOT"):
                os.environ.pop(key, None)
            report = run()
    report["network_attempts"] = attempts
    report["passed"] = report["passed"] and not attempts
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
