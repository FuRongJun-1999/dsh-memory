"""Paired exact BM25 optimization benchmark through production search_rrf.

Uses the requested Git revision's original BM25 and search_rrf for the before
arm. The after arm uses current production code. No result cache, external
model or query/qrel material enters the corpus. Reuse existing deterministic
Markdown fixtures or generate them with bench_rrf_candidates. A write probe
left by that generator counts as an additional node and is reported honestly.
"""
import argparse
import ast
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import types


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--baseline", default="8d40dea36d888b22af0c29dfa229a4203bcfeabe")
    args = parser.parse_args()
    assert args.rounds >= 1 and not args.output.exists()
    root, out = args.root.resolve(), args.output.resolve()
    repo = Path(__file__).resolve().parents[1]
    os.environ.update(MDCG_HOTCACHE="0", MDCG_READ_CACHE="1", MDCG_FRESHNESS="0",
                      MDCG_RETRIEVAL_PIPELINE="0", MDCG_SEMANTIC="0", MDCG_UNIFY_QUERY="0",
                      MDCG_EN_ATOMS="0", MDCG_RRF_CANDIDATES="0",
                      DSH_HOME=str(out.parent / "blockmax-bench-dsh"),
                      MDCG_AUX_ROOT=str(out.parent / "blockmax-bench-aux"))
    from . import bm25, mdcos
    from .bench_rrf_candidates import key
    from .bench_fuzzy_substrings import latency
    before_source = subprocess.check_output([
        "git", "show", args.baseline + ":md_cg/bm25.py"], cwd=repo)
    before = types.ModuleType("md_cg.bm25_frozen_before")
    exec(compile(before_source, "git:" + args.baseline + ":md_cg/bm25.py", "exec"), before.__dict__)
    old_mdcos = subprocess.check_output([
        "git", "show", args.baseline + ":md_cg/mdcos.py"], cwd=repo)
    tree = ast.parse(old_mdcos)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MdCGOS")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "search_rrf")
    namespace = dict(mdcos.__dict__)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "git:" + args.baseline + ":search_rrf", "exec"), namespace)
    Before = type("Before", (mdcos.MdCGOS,), {"search_rrf": namespace["search_rrf"]})
    original = bm25.search

    @contextmanager
    def arm(name):
        bm25.search = before.search if name == "before" else original
        try:
            yield
        finally:
            bm25.search = original

    queries = [("common", q) for q in ("资料", "条目", "记录", "主题")]
    queries += [("rare", key(i)) for i in (409, 2047)]
    queries += [("absent", "quuxnotinthefixture999xyz")]
    report = {"baseline": args.baseline, "root": str(root), "rounds": args.rounds,
              "protocol": "real Markdown; full production search_rrf; independent engines; "
                          "alternating arm order; result cache off; no OS cache flush; first calls separate",
              "sha256": {n: hashlib.sha256((repo / "md_cg" / n).read_bytes()).hexdigest()
                         for n in ("bm25.py", "mdcos.py", "mdcg.py", "readcache.py")},
              "baseline_bm25_sha256": hashlib.sha256(before_source).hexdigest(),
              "baseline_mdcos_sha256": hashlib.sha256(old_mdcos).hexdigest(),
              "arms": {}, "mismatches": [], "errors": []}
    engines, reference = {}, {}

    def save():
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def signature(rows):
        return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False,
                                         separators=(",", ":")).encode("utf-8")).hexdigest()

    try:
        for name, engine in (("before", Before), ("after", mdcos.MdCGOS)):
            with arm(name):
                started = time.perf_counter()
                cg = engines[name] = engine(str(root))
                details = report["arms"][name] = {"records": [], "nodes": len(cg.index["nodes"]),
                    "init_ms": (time.perf_counter() - started) * 1000}
                started = time.perf_counter()
                rows, meta = cg.search_rrf("资料", k=10, paths=("bm25",), judge=False, record=False)
                details["first"] = {"ms": (time.perf_counter() - started) * 1000,
                                    "bm25": meta["bm25"]}
                assert "fallback" not in meta["bm25"] and not meta["bm25"]["unavailable"]
                print(name, "first_ms", details["first"]["ms"], flush=True)
                save()
        assert report["arms"]["before"]["nodes"] == report["arms"]["after"]["nodes"]
        for turn in range(args.rounds):
            for name in (("before", "after") if turn % 2 == 0 else ("after", "before")):
                with arm(name):
                    for kind, query in queries:
                        started = time.perf_counter()
                        rows, meta = engines[name].search_rrf(
                            query, k=10, paths=("bm25",), judge=False, record=False)
                        elapsed = (time.perf_counter() - started) * 1000
                        info, sig = meta["bm25"], signature(rows)
                        assert "fallback" not in info and not info["unavailable"]
                        assert all(query in row[0]["content"] for row in rows)
                        assert len(rows) == (0 if kind == "absent" else 10)
                        if query in reference and reference[query] != sig:
                            report["mismatches"].append({"arm": name, "query": query, "round": turn + 1})
                        reference.setdefault(query, sig)
                        report["arms"][name]["records"].append({"round": turn + 1,
                            "kind": kind, "query": query, "ms": elapsed, "signature": sig, "bm25": info})
                print(name, "round", turn + 1, "done", flush=True)
                save()
        for name, data in report["arms"].items():
            data["latency"] = {kind: latency([r["ms"] for r in data["records"] if r["kind"] == kind])
                               for kind in ("common", "rare", "absent")}
        assert not report["mismatches"]
        report["status"] = "passed"
    except Exception as exc:
        report["errors"].append(type(exc).__name__ + ": " + str(exc))
        report["status"] = "failed"
        raise
    finally:
        save()
        for cg in engines.values():
            cg.close()
    print(json.dumps({"status": report["status"], "mismatches": len(report["mismatches"]),
                      "arms": {n: d["latency"] for n, d in report["arms"].items()}}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
