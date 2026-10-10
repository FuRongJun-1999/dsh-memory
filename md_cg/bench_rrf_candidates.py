"""Actual Markdown / production RRF paired candidate-index benchmark.

python -X utf8 -m md_cg.bench_rrf_candidates --sizes 10000,100000 --rounds 3

Both arms use the substring-optimized engine. Only MDCG_RRF_CANDIDATES differs.
Synthetic rare, common and absent queries are reported separately. The first
query includes lazy index construction; warm timings do not. No LLM, external
service or result cache is used. This is not a memory QA leaderboard score.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time

from . import mdcos, nodefile
from .bench_fuzzy_substrings import latency


def key(topic):
    return chr(0x4E00 + topic) + chr(0x6000 + topic) + chr(0x7200 + topic)


def process_memory():
    """Whole-process RSS, including both engines; not per-arm index memory."""
    if sys.platform != "win32":
        return {"available": False}
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    api = ctypes.WinDLL("psapi")
    kernel = ctypes.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    api.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    value = Counters()
    value.cb = ctypes.sizeof(value)
    if not api.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(value), value.cb):
        return {"available": False}
    return {"available": True, "rss_mib": value.WorkingSetSize / 1048576,
            "peak_rss_mib": value.PeakWorkingSetSize / 1048576}


def fixture(root, count):
    marker = root / "_rrf_candidate_fixture.json"
    spec = {"schema": 1, "nodes": count, "topics": 4096}
    if root.exists():
        if not marker.is_file() or json.loads(marker.read_text(encoding="utf-8")) != spec:
            raise ValueError(f"Refusing to overwrite an unrelated/incomplete pool: {root}")
        return
    root.mkdir(parents=True)
    for i in range(count):
        nid = f"entry_{i:08d}"
        folder = root / "knowledge" / f"{i // 1000:05d}"
        if i % 1000 == 0:
            folder.mkdir(parents=True)
        fm = {"id": nid, "layer": "knowledge", "importance": 0.4,
              "created_at": 1800000000.0 + i, "tags": []}
        content = f"资料条目\n主题：{key(i % 4096)}\n正文记录编号 {i}。\n"
        (folder / (nid + ".md")).write_text(nodefile.dumps(fm, content), encoding="utf-8")
        if (i + 1) % 10000 == 0:
            print(f"fixture {count}: wrote {i + 1} Markdown files", flush=True)
    marker.write_text(json.dumps(spec), encoding="utf-8")


def signature(result, meta):
    # Performance counters/fingerprints intentionally differ. Compare every
    # returned card, score, qualification, provenance and path cardinality.
    value = (result, {name: meta.get(name) for name in (
        "paths", "fused", "provenance", "goal_used", "judge_filtered",
        "expand_source", "judge_ranking", "early_stopped", "boundary")})
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def benchmark(root, rounds):
    queries = [("rare", key(i)) for i in (1, 409, 2047, 4095)]
    queries += [("common", "资料"), ("absent", "🦄🦄🦄")]
    report = {"root": str(root), "queries": queries, "first": {}, "configs": {}}
    engines = {}
    counters = {}
    try:
        for arm in ("scan", "indexed"):
            os.environ["MDCG_RRF_CANDIDATES"] = "1" if arm == "indexed" else "0"
            started = time.perf_counter()
            cg = engines[arm] = mdcos.MdCGOS(str(root))
            report.setdefault("construct_ms", {})[arm] = (time.perf_counter() - started) * 1000
            counters[arm] = {"inputs": 0}
            original = cg._read_many
            def measured(entries, stat, original=original, counter=counters[arm]):
                counter["inputs"] += len(entries)
                return original(entries, stat)
            cg._read_many = measured
            started = time.perf_counter()
            rows, meta = cg.search_rrf(queries[0][1], k=10, paths=("lexical", "fuzzy"),
                                       judge=False, record=False)
            report["first"][arm] = {"ms": (time.perf_counter() - started) * 1000,
                                    "signature": signature(rows, meta),
                                    "read_many_inputs": counters[arm]["inputs"],
                                    "index": meta.get("rrf_candidates")}
        report["nodes"] = len(engines["scan"].index["nodes"])
        report["first_equal"] = report["first"]["scan"]["signature"] == report["first"]["indexed"]["signature"]
        for paths in (("fuzzy",), ("lexical", "fuzzy")):
            name = ",".join(paths)
            records = {arm: [] for arm in engines}
            reference = {}
            mismatches = []
            for turn in range(rounds):
                order = ("scan", "indexed") if turn % 2 == 0 else ("indexed", "scan")
                for arm in order:
                    os.environ["MDCG_RRF_CANDIDATES"] = "1" if arm == "indexed" else "0"
                    for kind, query in queries:
                        counters[arm]["inputs"] = 0
                        started = time.perf_counter()
                        rows, meta = engines[arm].search_rrf(query, k=10, paths=paths,
                                                            judge=False, record=False)
                        ms = (time.perf_counter() - started) * 1000
                        digest = signature(rows, meta)
                        if query not in reference:
                            reference[query] = digest
                        elif digest != reference[query]:
                            mismatches.append({"arm": arm, "round": turn + 1, "query": query})
                        records[arm].append({"round": turn + 1, "kind": kind,
                                             "query": query, "ms": ms,
                                             "read_many_inputs": counters[arm]["inputs"],
                                             "index": meta.get("rrf_candidates"),
                                             "signature": digest})
                    print(f"{report['nodes']} {name} round={turn + 1} {arm}: "
                          f"{sum(r['ms'] for r in records[arm][-len(queries):]):.1f} ms", flush=True)
            groups = {}
            for kind in ("rare", "common", "absent", "all"):
                selected = {arm: [r for r in records[arm] if kind == "all" or r["kind"] == kind]
                            for arm in engines}
                means = {arm: statistics.mean(r["ms"] for r in rows)
                         for arm, rows in selected.items()}
                groups[kind] = {"latency": {arm: latency([r["ms"] for r in rows])
                                           for arm, rows in selected.items()},
                                "speedup_mean": means["scan"] / means["indexed"],
                                "mean_read_many_inputs": {arm: statistics.mean(
                                    r["read_many_inputs"] for r in rows)
                                    for arm, rows in selected.items()}}
            report["configs"][name] = {"groups": groups, "records": records,
                                        "mismatch_count": len(mismatches),
                                        "mismatches": mismatches}
        # A real production write + flush followed by retrieval. Its latency
        # includes add/flush; query time and index update reads are also separate.
        cg = engines["indexed"]
        os.environ["MDCG_RRF_CANDIDATES"] = "1"
        started = time.perf_counter()
        cg.add("write_probe", "🪷🪷🪷", importance=0.1)
        cg.flush()
        query_started = time.perf_counter()
        rows, meta = cg.search_rrf("🪷🪷🪷", k=10, paths=("fuzzy",), judge=False, record=False)
        report["write_visibility"] = {
            "add_flush_query_ms": (time.perf_counter() - started) * 1000,
            "query_ms": (time.perf_counter() - query_started) * 1000,
            "retrieved": "write_probe" in {r[0]["id"] for r in rows},
            "index": meta.get("rrf_candidates")}
        report["process_memory"] = process_memory()
        return report
    finally:
        # The benchmark does not rewrite/compact the immutable fixture index.
        # Flush handles are closed by the production flush() implementation.
        for cg in engines.values():
            cg.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", default="10000,100000")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2] / "rrf-candidate-bench")
    parser.add_argument("--output", type=Path, default=Path("rrf-candidate-results.json"))
    args = parser.parse_args()
    sizes = [int(s) for s in args.sizes.split(",")]
    if args.rounds < 1 or any(s < 1 for s in sizes):
        parser.error("sizes and rounds must be positive")
    os.environ.update(MDCG_HOTCACHE="0", MDCG_READ_CACHE="1", MDCG_FRESHNESS="0",
                      MDCG_RETRIEVAL_PIPELINE="0", MDCG_SEMANTIC="0",
                      MDCG_UNIFY_QUERY="0")
    report = {"python": platform.python_version(), "platform": platform.platform(),
              "rounds": args.rounds, "cache": "document cache on; result cache off",
              "baseline": "same substring-optimized code, candidate flag off",
              "datasets": [], "sha256": {name: hashlib.sha256(
                  (Path(__file__).parent / name).read_bytes()).hexdigest()
                  for name in ("mdcos.py", "rrf_candidates.py", "readcache.py", "hotcache.py",
                               "bench_rrf_candidates.py")}}
    args.root.mkdir(parents=True, exist_ok=True)
    for count in sizes:
        root = args.root / str(count)
        fixture(root, count)
        report["datasets"].append(benchmark(root, args.rounds))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    failed = any(not d["first_equal"] or not d["write_visibility"]["retrieved"]
                 or any(c["mismatch_count"] for c in d["configs"].values())
                 for d in report["datasets"])
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
