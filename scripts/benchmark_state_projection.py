"""Adversarial paired benchmark. Stdlib only; warm file cache, normal GC enabled.

Time: randomized alternating A/B in one interpreter, 11 paired batches; no tracemalloc.
Memory: fresh process per implementation, first query, OS working set/peak + tracemalloc
in a separate later call. Never present tracemalloc numbers as RSS.
"""
import argparse
import gc
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "repo"
sys.stdout.reconfigure(encoding="utf-8")
CASES = [
    dict(name="empty", n=0, units=1),
    dict(name="one", n=1, units=1),
    dict(name="small", n=100, units=10),
    dict(name="small_unique", n=1000, units=1000),
    dict(name="dense", n=10000, units=100),
    dict(name="unique", n=10000, units=10000),
    dict(name="large_dense", n=50000, units=100),
    dict(name="large_unique", n=50000, units=50000),
    dict(name="big_evidence", n=2000, units=20, evidence=8192),
    dict(name="big_values_unique", n=2000, units=2000, value=8192),
    dict(name="all_retired", n=10000, units=100, retired=True),
    dict(name="filtered", n=10000, units=100, subject="s0"),
    dict(name="filter_miss", n=10000, units=100, subject="absent"),
    dict(name="minimal_unique", n=10000, units=10000, minimal=True),
    dict(name="minimal_retired_unique", n=10000, units=10000, minimal=True, retired=True),
    dict(name="retired_big_values", n=2000, units=1000, value=8192, final_retire=True),
]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def implementations(candidate_dir):
    sys.path.insert(0, str(BASELINE))
    from md_cg import state_slots as baseline, state_events as base_events
    new_events = load("md_cg._review_events", Path(candidate_dir) / "md_cg/state_events.py")
    new_slots = load("md_cg._review_slots", Path(candidate_dir) / "md_cg/state_slots.py")
    new_slots.state_events = new_events
    return {"baseline": (baseline, base_events), "candidate": (new_slots, new_events)}


def call_of(pair, fixture, mode, case):
    slots, events = pair
    cg = SimpleNamespace(root=fixture)
    if mode == "status":
        return lambda: slots.status(cg)
    if mode == "read":
        return lambda: events.read(cg, subject=case.get("subject"))
    if mode in ("chain", "chain_current", "chain_count"):
        # Exercise each checkout's actual STG wrapper, including its own paging path.
        import md_cg
        api = load("md_cg._bench_stg", Path(slots.__file__).parent / "stg.py")
        os.environ["MDCG_STG_STATE"] = "1"
        def invoke():
            previous = md_cg.state_slots
            registered = sys.modules["md_cg.state_slots"]
            try:
                md_cg.state_slots = slots
                sys.modules["md_cg.state_slots"] = slots
                return api.state_chain(cg, subject=case.get("subject"),
                                       history=mode != "chain_current",
                                       limit=0 if mode == "chain_count" else 50)
            finally:
                md_cg.state_slots = previous
                sys.modules["md_cg.state_slots"] = registered
        return invoke
    return lambda: slots.project(cg, subject=case.get("subject"), history=mode == "history")


def make_fixture(directory, case):
    path = directory / "_state_events.jsonl"
    with path.open("w", encoding="utf-8", newline="\n") as output:
        for i in range(case["n"]):
            row = dict(subject=f"s{i % case['units']}", slot="住所", t=i, seq=i,
                       new="" if case.get("retired") or i % 13 == 0 else "值" * case.get("value", 2),
                       old="旧值", tier="一手", evidence="e" * case.get("evidence", 256), actor="fixture")
            if case.get("final_retire") and i >= case["units"]:
                row["new"] = ""
            if case.get("minimal"):
                row = {k: row[k] for k in ("subject", "slot", "new")}
            output.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return path


def digest(result):
    return hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def os_memory():
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ("peak_ws", "ws", "peak_paged", "paged",
                "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile", "private")]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        info = Counters()
        info.cb = ctypes.sizeof(info)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(info), info.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return {"rss_mib": info.ws / 1024**2, "peak_rss_mib": info.peak_ws / 1024**2,
                "private_mib": info.private / 1024**2}
    if sys.platform == "darwin":
        import resource
        # macOS reports bytes; this is a high-water mark, not current RSS.
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024**2
        return {"peak_rss_mib": peak}
    values = {}
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith(("VmRSS:", "VmHWM:")):
            key, value, _ = line.split()
            values[key] = int(value) / 1024
    return {"rss_mib": values["VmRSS:"], "peak_rss_mib": values["VmHWM:"]}


def memory_worker(args):
    case = next(c for c in CASES if c["name"] == args.case)
    call = call_of(implementations(args.candidate)[args.impl], args.fixture, args.mode, case)
    gc.collect()
    before = os_memory()
    result = call()
    after = os_memory()
    checksum = digest(result)
    del result
    gc.collect()
    released = os_memory()
    tracemalloc.start()
    result = call()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return dict(before=before, after=after, released=released, traced_peak_mib=peak / 1024**2,
                sha256=checksum)


def percentile(values, p):
    return sorted(values)[min(len(values)-1, int(p * len(values)))]


def timing(pairs, fixture, mode, case, rounds):
    calls = {k: call_of(v, fixture, mode, case) for k, v in pairs.items()}
    assert digest(calls["baseline"]()) == digest(calls["candidate"]())
    started = time.perf_counter()
    result = calls["baseline"]()
    del result
    initial = time.perf_counter() - started
    batch = max(1, min(1000, math.ceil(0.012 / max(initial, 0.000001))))
    rng = random.Random(20261015)
    measurements = []
    for _ in range(rounds):
        order = ["baseline", "candidate"]
        rng.shuffle(order)
        row = {}
        for name in order:
            started = time.perf_counter()
            for __ in range(batch):
                result = calls[name]()
                del result
            row[name] = (time.perf_counter() - started) * 1000 / batch
        measurements.append(row)
    ratios = [r["candidate"] / r["baseline"] for r in measurements]
    resamples = [statistics.median(rng.choices(ratios, k=len(ratios))) for _ in range(2000)]
    return dict(batch=batch, rounds=rounds, pairs=measurements,
                baseline_ms=statistics.median(r["baseline"] for r in measurements),
                candidate_ms=statistics.median(r["candidate"] for r in measurements),
                paired_ratio=statistics.median(ratios),
                bootstrap_95_ratio=[percentile(resamples, .025), percentile(resamples, .975)])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", default=str(ROOT))
    parser.add_argument("--baseline", required=True, help="Unmodified baseline checkout")
    parser.add_argument("--output-dir", default=str(Path.cwd()))
    parser.add_argument("--rounds", type=int, default=11)
    parser.add_argument("--label", default="state-projection")
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--modes", nargs="+", default=["current", "status", "history", "read", "chain", "chain_current", "chain_count"])
    parser.add_argument("--memory-worker", action="store_true")
    parser.add_argument("--case")
    parser.add_argument("--mode")
    parser.add_argument("--impl")
    parser.add_argument("--fixture")
    args = parser.parse_args()
    global BASELINE
    BASELINE = Path(args.baseline).resolve()
    if args.memory_worker:
        print(json.dumps(memory_worker(args)))
        return
    pairs = implementations(args.candidate)
    report = {"platform": platform.platform(), "python": sys.version, "gc_enabled": gc.isenabled(),
              "rounds": args.rounds, "label": args.label, "rows": [],
              "note": "Warm-cache paired randomized batches; time includes output release. Bootstrap describes this run only."}
    report["candidate_sources"] = {name: hashlib.sha256((Path(args.candidate)/"md_cg"/name).read_bytes()).hexdigest()
                                    for name in ("state_events.py", "state_slots.py", "stg.py")}
    suffix = "windows" if os.name == "nt" else ("macos" if sys.platform == "darwin" else "linux")
    destination = Path(args.output_dir) / f"review-{args.label}-{suffix}.json"
    with tempfile.TemporaryDirectory(prefix="dsh-review-") as directory:
        for case in CASES:
            if args.cases and case["name"] not in args.cases:
                continue
            path = make_fixture(Path(directory), case)
            for mode in args.modes:
                row = dict(case=case, mode=mode, file_mib=path.stat().st_size/1024**2)
                row.update(timing(pairs, directory, mode, case, args.rounds))
                memory = {}
                for impl in ("baseline", "candidate"):
                    command = [sys.executable, "-X", "utf8", __file__, "--memory-worker", "--case", case["name"],
                               "--mode", mode, "--impl", impl, "--fixture", directory, "--candidate", args.candidate, "--baseline", str(BASELINE)]
                    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True)
                    memory[impl] = json.loads(proc.stdout)
                assert memory["baseline"]["sha256"] == memory["candidate"]["sha256"]
                row["memory"] = memory
                report["rows"].append(row)
                destination.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
                print(json.dumps({"case": case["name"], "mode": mode,
                    "baseline_ms": round(row["baseline_ms"], 4), "candidate_ms": round(row["candidate_ms"], 4),
                    "ratio": round(row["paired_ratio"], 3), "ci": [round(v,3) for v in row["bootstrap_95_ratio"]],
                    "rss_peak_mib": [round(memory[k]["after"]["peak_rss_mib"],2) for k in ("baseline","candidate")],
                    "traced_mib": [round(memory[k]["traced_peak_mib"],3) for k in ("baseline","candidate")]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
