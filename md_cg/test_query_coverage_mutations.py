# -*- coding: utf-8 -*-
"""Six in-memory faults must fail their intended runtime assertions.

Never edits the checkout. Each child imports a fresh copy, changes one function
or cache key in memory, and runs only the guard for that fault.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest

from . import hotcache, mdcg, query_coverage

CASES = {
    "no_dispatch": "test_base_and_production_search_recall_tail",
    "prefix_only": "test_shared_golden_cases",
    "unbounded": "test_budget_membership_and_determinism",
    "cache_key_omitted": "test_hotcache_flip_matches_uncached_result",
    "default_on": "test_default_and_non_one_values_keep_prefix",
    "master_ignored": "test_master_switch_and_nonpositive_cap",
}


def change_function(module, name, old, new):
    source = inspect.getsource(getattr(module, name))
    if source.count(old) != 1:
        raise RuntimeError(f"mutation anchor mismatch: {name}: {old!r}")
    exec(compile(source.replace(old, new, 1), "<query-coverage-mutation>", "exec"), module.__dict__)


def child(mutant):
    if mutant == "cache_key_omitted":
        hotcache._ENV_SWITCHES = tuple(k for k in hotcache._ENV_SWITCHES
                                     if k != "MDCG_CN_GRAMS_COVERAGE")
    elif mutant in ("prefix_only", "unbounded"):
        old, new = (("return [gram for gram in flat if gram in selected]", "return flat[:cap]")
                    if mutant == "prefix_only" else ("if len(flat) <= cap:", "if True:"))
        change_function(query_coverage, "select_cn_grams", old, new)
    elif mutant in ("no_dispatch", "default_on", "master_ignored"):
        old = 'if os.environ.get("MDCG_CN_GRAMS_COVERAGE") == "1":'
        new = "if False:" if mutant == "no_dispatch" else (
            'if os.environ.get("MDCG_CN_GRAMS_COVERAGE") != "0":')
        if mutant == "master_ignored":
            old, new = 'if os.environ.get("MDCG_CN_GRAMS") == "0":', "if False:"
        change_function(mdcg, "cn_recall_grams", old, new)
    names = [CASES[mutant]] if mutant else list(CASES.values())
    targets = ["md_cg.test_query_coverage.QueryCoverage." + name for name in names]
    suite = unittest.defaultTestLoader.loadTestsFromNames(targets)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    record = {"mutant": mutant or "baseline", "tests": result.testsRun,
              "failures": [test.id() for test, _ in result.failures],
              "errors": [test.id() for test, _ in result.errors],
              "skips": len(result.skipped), "log": stream.getvalue().replace(
                  str(Path(__file__).resolve().parents[1]), "<repo>")}
    print(json.dumps(record, ensure_ascii=False))
    return 0 if result.wasSuccessful() else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", choices=("baseline", *CASES))
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    if args.child:
        return child(None if args.child == "baseline" else args.child)
    records = []
    for name in ("baseline", *CASES, "baseline"):
        proc = subprocess.run([sys.executable, "-X", "utf8", "-m", __spec__.name,
                               "--child", name], capture_output=True, encoding="utf-8", timeout=60)
        record = json.loads(proc.stdout)
        record["returncode"] = proc.returncode
        if name == "baseline":
            record["expected"] = proc.returncode == 0 and not record["skips"]
        else:
            intended = "md_cg.test_query_coverage.QueryCoverage." + CASES[name]
            # subTest failures add a suffix; no unrelated error counts as a kill.
            record["expected"] = (proc.returncode == 1 and not record["errors"]
                                  and not record["skips"] and bool(record["failures"])
                                  and all(f.startswith(intended) for f in record["failures"]))
        records.append(record)
        print(f"{name}: {'PASS' if record['expected'] else 'FAIL'} "
              f"rc={proc.returncode} failures={len(record['failures'])}")
    root = Path(__file__).resolve().parents[1]
    files = ["md_cg/mdcg.py", "md_cg/query_coverage.py", "md_cg/hotcache.py",
             "md_cg/query_coverage_cases.tsv", "md_cg/test_query_coverage.py"]
    evidence = {"records": records, "source_sha256": {
        f: hashlib.sha256((root / f).read_bytes()).hexdigest() for f in files}}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if all(r["expected"] for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
