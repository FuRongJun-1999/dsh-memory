"""Bounded fault injections for sparse eligibility and TF synchronization.

Guards pass before mutation and after restoration. A kill requires the chosen
runtime assertion, with no errors/skips; source files are never modified.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import textwrap
import traceback
import unittest
from unittest.mock import patch


MUTATIONS = (
    ("S0", "ignore incomplete write history", "journal",
     "generation < self.change_floor", "False",
     "test_history_overflow_falls_back_instead_of_missing_edits",
     'self.assertEqual({row[0]["id"] for row in rows}, {f"sparse{i:04d}" for i in range(3)})'),
    ("S1", "bypass eligibility of changed nodes", "bm25",
     "changed = method(_ids=ids, **options)",
     "changed = list(nodes[nid] for nid in ids if nid in nodes)",
     "test_membership_drop_and_restore_keep_full_candidate_order",
     'self.assertNotIn("sparse0000", [r[0]["id"] for r in rows])'),
    ("S2", "retain candidates whose membership dropped", "bm25",
     "len(changed) == len(ids)", "True",
     "test_membership_drop_and_restore_keep_full_candidate_order",
     'self.assertNotIn("sparse0000", [r[0]["id"] for r in rows])'),
    ("S3", "leave migrated paths in TF postings", "bm25",
     "allowed.pop(path, None)\n                self.remove(path)",
     "allowed.pop(path, None)",
     "test_route_migration_removes_old_tf_and_keeps_node_order",
     'self.assertNotIn("fallback", meta.get("bm25", {}))'),
    ("S4", "accept delta with a missing predecessor", "bm25",
     "and delta and delta[0] == self.write_gen", "and delta",
     "test_pool_can_advance_twice_before_bm25_consumes_it",
     'self.assertEqual({row[0]["id"] for row in rows}, {"sparse0000", "sparse0001"})'),
    ("S5", "treat incomplete reads as a reusable complete index", "bm25",
     "and self.write_gen == dirty.write_gen\n                and len(self.docs) == len(self.allowed)",
     "and self.write_gen == dirty.write_gen",
     "test_failed_delta_read_is_retried_without_another_write",
     'self.assertEqual([r[0]["id"] for r in self.search("retryword")[0]], ["sparse0045"])'),
    ("S6", "ignore broad invalidation in the journal", "journal",
     "generation < self.broad_gen", "False",
     "test_bounded_journal_retains_flush_events_and_invalidates_broad_changes",
     "self.assertIsNone(dirty.changed_ids_since(0))"),
    ("S7", "sort append IDs instead of retaining first-write order", "journal",
     "tuple(dict.fromkeys(reversed(recent)))", "tuple(sorted(set(recent)))",
     "test_appends_and_repeated_new_id_preserve_original_pool_order",
     "self.assertEqual(self.pool(), self.cg._candidates())"),
)


class GuardResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sites = {}

    def addFailure(self, test, err):
        super().addFailure(test, err)
        frames = [f for f in traceback.extract_tb(err[2])
                  if Path(f.filename).name in ("test_bm25_sparse_sync.py", "test_bm25.py")]
        self.sites[test._testMethodName] = frames[-1].line if frames else ""


def guards(names):
    from .test_bm25_sparse_sync import SparseSyncTests
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, resultclass=GuardResult).run(
        unittest.TestSuite(SparseSyncTests(name) for name in names))
    return {"tests_run": result.testsRun, "failures": result.sites,
            "errors": [test.id() for test, _text in result.errors],
            "skipped": [test.id() for test, _text in result.skipped], "log": stream.getvalue()}


def matches(result, count, expected):
    return (result["tests_run"] == count and result["failures"] == expected
            and not result["errors"] and not result["skipped"])


def run():
    from . import bm25, mdcg
    sources = {"bm25": Path(bm25.__file__).read_text(encoding="utf-8"),
               "mdcg": Path(mdcg.__file__).read_text(encoding="utf-8")}
    tree = ast.parse(sources["mdcg"])
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "_DirtyDict")
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "changed_ids_since")
    sources["journal"] = textwrap.dedent(ast.get_source_segment(sources["mdcg"], node))
    report = {"source_sha256_lf": {k: hashlib.sha256(v.encode()).hexdigest() for k, v in sources.items()},
              "guard_sha256_lf": hashlib.sha256(Path(__file__).with_name(
                  "test_bm25_sparse_sync.py").read_text(encoding="utf-8").encode()).hexdigest(),
              "mutations": [], "passed": False}
    codes = []
    for mid, _label, module, old, new, _test, _site in MUTATIONS:
        if sources[module].count(old) != 1:
            report["anchor_error"] = {"id": mid, "hits": sources[module].count(old)}
            return report
        codes.append(compile(sources[module].replace(old, new, 1),
                             bm25.__file__ if module == "bm25" else mdcg.__file__, "exec"))
    names = sorted({m[5] for m in MUTATIONS})
    report["baseline"] = baseline = guards(names)
    print("BASELINE", baseline["tests_run"], "guards", baseline["failures"], flush=True)
    if not matches(baseline, len(names), {}):
        return report
    saved = dict(vars(bm25))
    try:
        for mutation, code in zip(MUTATIONS, codes):
            mid, label, module, _old, _new, test, site = mutation
            if module == "bm25":
                try:
                    exec(code, vars(bm25))
                    result = guards([test])
                finally:
                    vars(bm25).clear()
                    vars(bm25).update(saved)
            else:
                namespace = {}
                exec(code, namespace)
                with patch.object(mdcg._DirtyDict, "changed_ids_since", namespace["changed_ids_since"]):
                    result = guards([test])
            expected = {test: site}
            passed = matches(result, 1, expected)
            report["mutations"].append({"id": mid, "fault": label, "passed": passed,
                                        "expected_failures": expected, "actual": result})
            print("PASS" if passed else "FAIL", mid, label, result["failures"], flush=True)
            if not passed:
                print(result["log"], flush=True)
    finally:
        vars(bm25).clear()
        vars(bm25).update(saved)
    report["restored"] = restored = guards(names)
    report["killed"] = sum(m["passed"] for m in report["mutations"])
    report["passed"] = (report["killed"] == len(MUTATIONS) and matches(restored, len(names), {})
                        and Path(bm25.__file__).read_text(encoding="utf-8") == sources["bm25"]
                        and Path(mdcg.__file__).read_text(encoding="utf-8") == sources["mdcg"])
    print("RESTORED", restored["tests_run"], "guards", restored["failures"], flush=True)
    print("TARGETED SPARSE MUTATIONS", report["killed"], "/", len(MUTATIONS), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("Use a new output path; preserve previous evidence")
    attempts = []
    def deny_network(event, _args):
        if event in ("socket.connect", "socket.getaddrinfo", "socket.sendto"):
            attempts.append(event)
            raise RuntimeError("Network disabled for sparse mutation acceptance")
    sys.addaudithook(deny_network)
    with tempfile.TemporaryDirectory(prefix="bm25_sparse_mutations_") as temporary:
        root = Path(temporary)
        with patch.dict(os.environ, MDCG_ROOT=str(root / "pool"), DSH_HOME=str(root / "dsh"),
                        MDCG_AUX_ROOT=str(root / "auxiliary"), MDCG_DATA_ROOT=str(root / "data"),
                        MDCG_BM25_BLOCK_MAX="1", MDCG_BM25_POOL_CACHE="1"):
            for key in ("MDCG_TOKEN", "MDCG_POLICY_FILE", "MDCG_TEST_LIVE_ROOT"):
                os.environ.pop(key, None)
            report = run()
    report["network_attempts"] = attempts
    report["passed"] = report["passed"] and not attempts
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
