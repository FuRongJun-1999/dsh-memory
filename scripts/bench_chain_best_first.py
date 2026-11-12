# -*- coding: utf-8 -*-
"""Native Markdown/RRF chain-starvation reproduction and paired benchmark.

Run this *same* script with --repo pointing at either frozen checkout.
Only public synthetic data; warm adjacency timings exclude fixture build.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
from unittest import mock


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def quantile(samples, q):
    values = sorted(samples)
    index = (len(values) - 1) * q
    lo = int(index)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (index - lo)


def _main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=60)
    parser.add_argument("--widths", type=int, nargs="+", default=[3, 6, 12])
    parser.add_argument("--expect-baseline-failure", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1 or any(w < 1 for w in args.widths):
        parser.error("repeats and widths must be positive")
    repo = args.repo.resolve()
    sys.path.insert(0, str(repo))
    from md_cg import chain
    from md_cg.mdcos import MdCGOS

    helper_path = Path(__file__).resolve().parents[1] / "md_cg" / "test_chain_best_first.py"
    spec = importlib.util.spec_from_file_location("md_cg._chain_eval_helpers", helper_path)
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    names = ["test_strong_target_default_budget", "test_native_markdown_default_rrf"]
    guards, guard_log = helpers.run_suite(names, verbosity=1)
    if args.expect_baseline_failure:
        valid = (len(guards.failures) == 2 and not guards.errors and not guards.skipped
                 and "strong_target starved" in guard_log
                 and "default production RRF must recall strong_target" in guard_log)
    else:
        valid = guards.wasSuccessful() and not guards.skipped
    report = {
        "head": subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                        text=True, encoding="utf-8", errors="replace").strip(),
        "source_sha256": {p: digest(repo / p) for p in ("md_cg/chain.py", "md_cg/mdcos.py")},
        "harness_sha256": digest(__file__), "helper_sha256": digest(helper_path),
        "source_dirty": subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain", "--",
                                                 "md_cg/chain.py", "md_cg/mdcos.py"],
                                                text=True, encoding="utf-8", errors="replace").strip(),
        "python": sys.version, "platform": sys.platform, "repeats": args.repeats,
        "guards_expected_baseline_failure": args.expect_baseline_failure,
        "guards_valid": valid, "guards_log": guard_log, "cases": [],
        "scope": "Synthetic strong-target recall; warm adjacency; not a leaderboard or million-node/concurrency test",
    }
    if not valid:
        print(guard_log)
        raise AssertionError("baseline/fixed runtime guard outcome does not match expectation")
    if report["source_dirty"]:
        raise AssertionError("freeze production source in a commit before measuring")
    for width in args.widths:
        for reverse in (False, True):
            outgoing = helpers.converging_graph(width=width, reverse=reverse)
            canonical = json.dumps(outgoing, sort_keys=True, ensure_ascii=False).encode("utf-8")
            with tempfile.TemporaryDirectory(prefix="chain_bench_") as temp:
                with mock.patch.dict(os.environ, {"MDCG_HOTCACHE": "0", "MDCG_SUSTAIN": "0",
                                                   "MDCG_SEMANTIC": "0", "MDCG_EN_ATOMS": "0",
                                                   "MDCG_RRF_CANDIDATES": "0", "MDCG_RETRIEVAL_PIPELINE": "0"}):
                    cg = MdCGOS(str(Path(temp) / "graph"))
                    try:
                        helpers.populate(cg, outgoing)
                        result = chain.expand_from_seeds(cg, {"seed": 1})
                        samples = []
                        for _ in range(args.repeats):
                            started = time.perf_counter_ns()
                            result = chain.expand_from_seeds(cg, {"seed": 1})
                            samples.append((time.perf_counter_ns() - started) / 1e6)
                        with mock.patch.object(chain, "edge_weight", wraps=chain.edge_weight) as counter:
                            chain.expand_from_seeds(cg, {"seed": 1})
                            weight_calls = counter.call_count
                        rrf_samples = []
                        for _ in range(10):
                            started = time.perf_counter_ns()
                            rows, meta = cg.search_rrf("anchoronlyneedle", k=20, judge=False, record=False)
                            rrf_samples.append((time.perf_counter_ns() - started) / 1e6)
                        ids = [n["id"] for n, *_rest in rows]
                        target = result.get("strong_target")
                        if target:
                            assert target["score"] == .585225, "strongest target score"
                            assert target["chain"]["nodes"] == ["seed", "strong_a", "strong_target"], "target provenance"
                        if not args.expect_baseline_failure:
                            assert target and "strong_target" in ids, "fixed runtime target recall"
                        case = {"width": width, "nodes": len(cg.index["nodes"]),
                                "edges": sum(map(len, outgoing.values())),
                                "edge_order": "weak_first" if reverse else "strong_first",
                                "fixture_sha256": hashlib.sha256(canonical).hexdigest(),
                                "expansion_target": target,
                                "returned_expansion_nodes": len(result), "edge_weight_calls": weight_calls,
                                "expansion_ms": {"p50": statistics.median(samples), "p95": quantile(samples, .95)},
                                "expansion_samples_ms": samples,
                                "rrf_target": "strong_target" in ids, "rrf_ids": ids,
                                "rrf_paths": meta["paths"],
                                "rrf_target_provenance": meta.get("provenance", {}).get("strong_target"),
                                "rrf_ms": {"p50": statistics.median(rrf_samples), "p95": quantile(rrf_samples, .95)}}
                        report["cases"].append(case)
                        print(f"w={width} {case['edge_order']} nodes={case['nodes']} "
                              f"target={bool(target)} rrf={case['rrf_target']} weights={weight_calls} "
                              f"p50={case['expansion_ms']['p50']:.4f}ms", flush=True)
                    finally:
                        cg.close()
    report["expansion_target_hits"] = sum(bool(c["expansion_target"]) for c in report["cases"])
    report["rrf_target_hits"] = sum(c["rrf_target"] for c in report["cases"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"strong target recall: expansion {report['expansion_target_hits']}/{len(report['cases'])}; "
          f"default RRF {report['rrf_target_hits']}/{len(report['cases'])}")
    return 0


def main():
    with tempfile.TemporaryDirectory(prefix="chain_bench_env_") as temp:
        with mock.patch.dict(os.environ, {
            "MDCG_ROOT": str(Path(temp) / "unused"),
            "MDCG_AUX_ROOT": str(Path(temp) / "auxiliary"),
            "MDCG_DATA_ROOT": str(Path(temp) / "data"),
            "DSH_HOME": str(Path(temp) / "dsh"), "MDCG_MASTER_KEY": "ab" * 32,
            "MDCG_CHAIN_TYPES": "", "MDCG_HOTCACHE": "0", "MDCG_SUSTAIN": "0",
        }):
            return _main()


if __name__ == "__main__":
    raise SystemExit(main())
