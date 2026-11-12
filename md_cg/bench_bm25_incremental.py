"""Paired production BM25 benchmark for write-then-query block maintenance.

Generates separate deterministic Markdown corpora for the frozen/current arms.
Only the BM25 module differs. Result caches are off, arm order alternates, and
every query compares all raw BM25 top-50 rows/scores and fused production rows.
This is a local synthetic benchmark, not a memory-QA leaderboard submission.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import types


BASELINE = "b4f6b68ee3e51a34dca430b187cba3fc8d570ebb"
BASELINE_SHA256 = "bfbd94135796813871a47465f7f16db54749f7549d787ae67830b9e7ac3d465a"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--count", type=int, default=10000)
    p.add_argument("--rounds", type=int, default=12)
    p.add_argument("--baseline", default=BASELINE)
    p.add_argument("--baseline-source", type=Path,
                   help="offline copy of the frozen baseline's bm25.py; exact SHA256 required")
    p.add_argument("--prepare-only", action="store_true")
    p.add_argument("--prepare-metadata", action="store_true",
                   help="with --prepare-only, persist production metadata in two independent processes")
    args = p.parse_args()
    if args.count < 4096 or args.rounds < 3 or args.output.exists():
        p.error("Requires count >= 4096, rounds >= 3 and a new output")
    if args.prepare_metadata and not args.prepare_only:
        p.error("--prepare-metadata requires --prepare-only")
    network_attempts = []
    def deny_network(event, _args):
        if event in ("socket.connect", "socket.getaddrinfo", "socket.sendto"):
            network_attempts.append(event)
            raise RuntimeError("Network disabled for paired BM25 measurement")
    sys.addaudithook(deny_network)
    root, output = args.root.resolve(), args.output.resolve()
    repo = Path(__file__).resolve().parents[1]
    frozen = None
    if not args.prepare_only:
        if args.baseline_source:
            frozen = args.baseline_source.read_bytes()
            if args.baseline != BASELINE or hashlib.sha256(frozen).hexdigest() != BASELINE_SHA256:
                p.error("Offline baseline must match the exact frozen b4f6b68e source")
        else:
            frozen = subprocess.check_output([
                "git", "show", args.baseline + ":md_cg/bm25.py"], cwd=repo)
    marker = root / "_incremental_benchmark.json"
    spec = {"schema": 1, "count": args.count, "baseline": args.baseline}
    if root.exists() and (not marker.is_file() or json.loads(
            marker.read_text(encoding="utf-8")) != spec):
        p.error("Refusing an unrelated or previously measured corpus")
    root.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(spec), encoding="utf-8")
    os.environ.update(MDCG_HOTCACHE="0", MDCG_READ_CACHE="1", MDCG_FRESHNESS="0",
                      MDCG_RETRIEVAL_PIPELINE="0", MDCG_SEMANTIC="0", MDCG_UNIFY_QUERY="0",
                      MDCG_EN_ATOMS="0", MDCG_RRF_CANDIDATES="0",
                      MDCG_BM25_BLOCK_MAX="1", MDCG_BM25_POOL_CACHE="1",
                      DSH_HOME=str(root / "dsh"), MDCG_AUX_ROOT=str(root / "auxiliary"))
    from unittest.mock import patch
    from . import bm25, mdcos
    from .bench_rrf_candidates import fixture, key, signature
    from .bench_fuzzy_substrings import latency
    for name in ("before", "after"):
        fixture(root / name, args.count)
    if args.prepare_only:
        if args.prepare_metadata:
            jobs, logs = [], []
            child = ("from md_cg.mdcos import MdCGOS; import sys; "
                     "cg=MdCGOS(sys.argv[1]); print('nodes', len(cg.index['nodes']), flush=True); "
                     "cg.close(); print('metadata snapshot persisted', flush=True)")
            try:
                for name in ("before", "after"):
                    log = (root / (name + "-metadata-preparation.log")).open("w", encoding="utf-8")
                    logs.append(log)
                    child_env = dict(os.environ, DSH_HOME=str(root / (name + "-dsh")),
                                     MDCG_AUX_ROOT=str(root / (name + "-auxiliary")))
                    jobs.append(subprocess.Popen([sys.executable, "-X", "utf8", "-c", child,
                        str(root / name)], cwd=Path(__file__).resolve().parents[1],
                        env=child_env, stdout=log, stderr=subprocess.STDOUT))
                codes = [job.wait(timeout=1800) for job in jobs]
                if any(codes):
                    raise RuntimeError("Metadata preparation failed: " + str(codes))
            finally:
                for log in logs:
                    log.close()
        print("PREPARED", root, flush=True)
        return
    marker.write_text(json.dumps(dict(spec, measured=True)), encoding="utf-8")
    before = types.ModuleType("md_cg._incremental_baseline")
    before.__package__ = "md_cg"
    exec(compile(frozen, "git:" + args.baseline + ":bm25.py", "exec"), vars(before))
    original = bm25.search
    engines, reference = {}, {}
    report = {"date": time.strftime("%Y-%m-%d"), "count": args.count,
        "rounds": args.rounds, "baseline": args.baseline,
        "protocol": "independent real Markdown corpora; current production search_rrf; "
                    "only BM25 differs; alternating arm order; result cache off; "
                    "OS cache not flushed; writes excluded from query latency; "
                    "first builds separate; raw top-50 and fused top-10 full equality",
        "platform": platform.platform(), "python": platform.python_version(),
        "source_sha256": {n: hashlib.sha256((repo / "md_cg" / n).read_bytes()).hexdigest()
                          for n in ("bm25.py", "mdcos.py", "mdcg.py", "readcache.py")},
        "baseline_bm25_sha256": hashlib.sha256(frozen).hexdigest(),
        "arms": {}, "mismatches": [], "errors": [], "status": "running",
        "network_attempts": network_attempts}

    def save():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def normalize(value, name):
        if isinstance(value, str):
            for prefix in (str(root / name), (root / name).as_posix()):
                if value.startswith(prefix):
                    return "<corpus>" + value[len(prefix):].replace("\\", "/")
            return value
        if isinstance(value, dict):
            return {k: normalize(v, name) for k, v in value.items()}
        if isinstance(value, (tuple, list)):
            return [normalize(v, name) for v in value]
        return value

    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                        separators=(",", ":")).encode()).hexdigest()

    @contextmanager
    def arm(name, captured):
        target = before.search if name == "before" else original
        def capture(*a, **kw):
            rows, info = target(*a, **kw)
            captured["raw"] = rows
            return rows, info
        bm25.search = capture
        try:
            yield
        finally:
            bm25.search = original

    def query(name, phase, turn, text):
        cg, captured = engines[name], {}
        idx = getattr(cg, "_bm25_index", None)
        tables = dict(getattr(idx, "term_blocks", {}))
        with arm(name, captured):
            started = time.perf_counter()
            rows, meta = cg.search_rrf(text, k=10, paths=("bm25",), judge=False, record=False)
            elapsed = (time.perf_counter() - started) * 1000
        info, idx = meta["bm25"], cg._bm25_index
        if "fallback" in info or info["unavailable"] or meta.get("cached"):
            raise AssertionError(info)
        full = signature(normalize(rows, name), normalize(meta, name))
        raw = digest(normalize(captured["raw"], name))
        value = (full, raw, info["matched"])
        identity = (phase, turn, text)
        if identity in reference and reference[identity] != value:
            report["mismatches"].append({"arm": name, "phase": phase, "round": turn, "query": text})
        reference.setdefault(identity, value)
        if phase != "absent" and not rows:
            raise AssertionError("Expected nonempty production results")
        if phase == "absent" and rows:
            raise AssertionError("Absent term returned results")
        record = {"phase": phase, "round": turn, "query": text, "ms": elapsed,
                  "full_signature": full, "raw_signature": raw, "bm25": info,
                  "previous_term_tables": len(tables),
                  "retained_term_tables": sum(v is idx.term_blocks.get(k) for k, v in tables.items())}
        if phase == "first":
            report["arms"][name]["first"] = record
        else:
            report["arms"][name]["records"].append(record)

    try:
        for name in ("before", "after"):
            print(name, "loading production metadata", flush=True)
            prepared = (root / name / "_index.json").is_file()
            started = time.perf_counter()
            engines[name] = mdcos.MdCGOS(str(root / name))
            report["arms"][name] = {"init_ms": (time.perf_counter() - started) * 1000,
                                    "records": [], "nodes": len(engines[name].index["nodes"]),
                                    "metadata_snapshot_prepared": prepared}
            print(name, "init_ms", report["arms"][name]["init_ms"], flush=True)
            if report["arms"][name]["nodes"] != args.count:
                raise AssertionError("Unexpected initial corpus size")
            query(name, "first", 0, "资料 条目")
            print(name, "first_ms", report["arms"][name]["first"]["ms"], flush=True)
            save()
        for turn in range(1, args.rounds + 1):
            for name in (("before", "after") if turn % 2 else ("after", "before")):
                query(name, "warm", turn, "资料 条目")
                cg = engines[name]
                # Alternate local overrides and inserts. Both arms get the
                # same logical history and explicit clock/creation metadata.
                inserting = turn % 3 == 0
                nid = f"new_{turn:08d}" if inserting else f"entry_{(turn * 7919) % args.count:08d}"
                text = f"资料条目\n主题：{key(turn % 4096)}\n正文记录编号 {turn}。资料 条目 "
                started = time.perf_counter()
                with patch("md_cg.mdcg.time.time", return_value=1800100000.0 + turn):
                    cg.add(nid, text, importance=0.4, override=not inserting,
                           created_at=1800100000.0 + turn)
                    cg.flush()
                write_ms = (time.perf_counter() - started) * 1000
                phase = "insert_query" if inserting else "update_query"
                query(name, phase, turn, "资料 条目")
                report["arms"][name]["records"][-1]["write_ms"] = write_ms
                query(name, "warm_after_write", turn, "资料 条目")
                query(name, "rare", turn, key(409))
                query(name, "absent", turn, "quuxnotinthefixture999xyz")
            print("paired round", turn, "of", args.rounds, flush=True)
            save()
        phases = ("warm", "update_query", "insert_query", "warm_after_write", "rare", "absent")
        for details in report["arms"].values():
            details["latency"] = {phase: latency([r["ms"] for r in details["records"]
                                                  if r["phase"] == phase]) for phase in phases}
        if report["mismatches"] or network_attempts:
            raise AssertionError("Before/after results differ")
        report["paired_queries"] = len(reference)
        report["status"] = "passed"
    except Exception as exc:
        report["errors"].append(type(exc).__name__ + ": " + str(exc))
        report["status"] = "failed"
        raise
    finally:
        save()
        for cg in engines.values():
            cg.close()
    print(json.dumps({"status": report["status"], "paired_queries": report["paired_queries"],
                      "mismatches": len(report["mismatches"]),
                      "latency": {n: d["latency"] for n, d in report["arms"].items()}},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
