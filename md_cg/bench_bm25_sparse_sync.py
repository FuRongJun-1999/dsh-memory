"""Separate-process, real-Markdown BM25 write/query replay.

Both checkouts execute their own complete production engine. A search observer
records raw top-50 without replacing ranking; complete fused cards, raw scores,
and matched counts must agree. Timings exclude fixture generation and writes.
OS filesystem caches are not flushed. This is not a memory-QA leaderboard.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import time


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def configure(root):
    for name in list(os.environ):
        if name.startswith("MDCG_"):
            os.environ.pop(name)
    os.environ.update(MDCG_HOTCACHE="0", MDCG_READ_CACHE="1", MDCG_FRESHNESS="0",
                      MDCG_RETRIEVAL_PIPELINE="0", MDCG_UNIFY_QUERY="0",
                      MDCG_EN_ATOMS="0", MDCG_SEMANTIC="0", MDCG_SUSTAIN="0",
                      MDCG_RRF_CANDIDATES="0", MDCG_BM25_POOL_CACHE="1",
                      MDCG_BM25_BLOCK_MAX="1", MDCG_BM25_BUILD_WORKERS="4",
                      MDCG_AUX_ROOT=str(root.parent / (root.name + "-auxiliary")),
                      MDCG_DATA_ROOT=str(root.parent / (root.name + "-data")),
                      MDCG_ROOT=str(root), MDCG_MASTER_KEY="ab" * 32,
                      DSH_HOME=str(root.parent / (root.name + "-dsh")))


def worker(repo, root):
    sys.path.insert(0, str(repo))
    configure(root)
    network = []
    def deny_network(event, _args):
        if event in ("socket.connect", "socket.getaddrinfo", "socket.sendto"):
            network.append(event)
            raise RuntimeError("Network disabled for synthetic BM25 replay")
    sys.addaudithook(deny_network)
    from unittest.mock import patch
    from md_cg import bm25
    from md_cg.mdcos import MdCGOS
    from md_cg.bench_rrf_candidates import process_memory, signature

    captured, original = {}, bm25.search
    def observe(*args, **kwargs):
        rows, info = original(*args, **kwargs)
        captured["raw"] = rows
        return rows, info
    bm25.search = observe

    def normalize(value):
        if isinstance(value, str):
            for prefix in (str(root), root.as_posix()):
                if value.startswith(prefix):
                    return "<corpus>" + value[len(prefix):].replace("\\", "/")
            return value
        if isinstance(value, dict):
            return {k: normalize(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [normalize(v) for v in value]
        return value

    started = time.perf_counter()
    cg = MdCGOS(str(root))
    ready = {"ready": True, "nodes": len(cg.index["nodes"]),
             "init_ms": (time.perf_counter() - started) * 1000,
             "pid": os.getpid(), "initial_memory": process_memory(),
             "head": subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                             text=True, encoding="utf-8").strip(),
             "sources": {n: hashlib.sha256((repo / "md_cg" / n).read_bytes()).hexdigest()
                         for n in ("bm25.py", "mdcg.py", "mdcos.py", "readcache.py")}}
    print(json.dumps(ready), flush=True)
    try:
        for line in sys.stdin:
            request = json.loads(line)
            op = request["op"]
            if op == "close":
                break
            if op == "stats":
                pool = getattr(cg, "_bm25_candidate_pool", None)
                slots = pool[4] if pool and len(pool) == 6 else None
                journal = getattr(cg._dirty, "change_log", ())
                result = {"memory": process_memory(), "network_attempts": network,
                          "pool_slot_entries": len(slots) if slots is not None else 0,
                          "pool_slot_owned_bytes": (sys.getsizeof(slots) + sum(
                              sys.getsizeof(k) + sys.getsizeof(v) + sys.getsizeof(v[0])
                              for k, v in slots.items())) if slots is not None else 0,
                          "journal_entries": len(journal),
                          "journal_container_bytes": sys.getsizeof(journal),
                          "docs": len(cg._bm25_index.docs)}
            elif op == "write":
                started = time.perf_counter()
                with patch("md_cg.mdcg.time.time", return_value=request["clock"]):
                    cg.add(request["id"], request["content"], importance=0.4,
                           override=request["override"], created_at=request["clock"])
                    cg.flush()
                result = {"write_ms": (time.perf_counter() - started) * 1000}
            else:
                captured.clear()
                started = time.perf_counter()
                rows, meta = cg.search_rrf(request["q"], k=10, paths=("bm25",),
                                           judge=False, record=False)
                elapsed = (time.perf_counter() - started) * 1000
                info = meta["bm25"]
                if "fallback" in info or info["unavailable"] or meta.get("cached"):
                    raise AssertionError(meta)
                if bool(rows) != request.get("expected_hits", True):
                    raise AssertionError("Unexpected empty/nonempty search")
                result = {"ms": elapsed, "full_signature": signature(normalize(rows), normalize(meta)),
                          "raw_signature": digest(normalize(captured["raw"])), "bm25": info,
                          "ids": [r[0]["id"] for r in rows]}
            print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        bm25.search = original
        cg.close()


class Client:
    def __init__(self, repo, root, log):
        self.log = log.open("w", encoding="utf-8")
        self.process = subprocess.Popen([sys.executable, "-X", "utf8", "-u", __file__,
            "--worker", "--repo", str(repo), "--root", str(root)], cwd=repo,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
            text=True, encoding="utf-8")
        self.ready = self.read()

    def read(self):
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("Worker stopped; inspect its stderr log")
        return json.loads(line)

    def ask(self, request):
        self.process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        return self.read()

    def close(self):
        try:
            if self.process.poll() is None:
                self.process.stdin.write('{"op":"close"}\n')
                self.process.stdin.flush()
                self.process.stdin.close()
                self.process.wait(timeout=45)
        finally:
            self.log.close()


def fixture(root, count, distribution):
    from . import mdcg, nodefile
    root.mkdir()
    # Prepare a native metadata snapshot outside all query timings. The pure
    # entry builder is unchanged by this optimization. Both real constructors
    # still validate the copied directory fingerprint and load this snapshot.
    for layer in mdcg.LAYERS:
        (root / layer).mkdir()
    metadata = object.__new__(mdcg.MdCG)
    metadata.root = str(root)
    nodes = {}
    hashes = hashlib.sha256()
    for i in range(count):
        nid = f"entry_{i:08d}"
        folder = root / "knowledge" / f"{i // 1000:05d}"
        folder.mkdir(exist_ok=True, parents=True)
        body = f"commonword secondword topic{i % 4096}\n记忆检索 资料条目 {i}"
        if distribution == "varied":
            body = ("commonword " * (1 + i % 9) + ("secondword " if i % 4 else "")
                    + f"topic{i % 4096} 记忆检索 资料条目 {i}\n"
                    + "padding " * ((i * 31) % 127))
        fm = {"id": nid, "layer": "knowledge", "importance": 0.4,
              "created_at": 1800000000.0 + i, "tags": []}
        encoded = nodefile.dumps(fm, body).encode("utf-8")
        disk = folder / (nid + ".md")
        disk.write_bytes(encoded)
        actual_fm, actual_body = nodefile.loads(encoded.decode("utf-8"))
        nodes[nid] = metadata._node_entry(str(disk), "knowledge", actual_fm, actual_body)
        hashes.update(nid.encode() + b"\0" + hashlib.sha256(encoded).digest())
        if (i + 1) % 10000 == 0:
            print("fixture", distribution, i + 1, "/", count, flush=True)
    snapshot = {"schema": mdcg.SCHEMA, "nodes": nodes,
                "buckets": metadata._count_buckets(nodes), "_fingerprint": metadata._dir_fingerprint()}
    (root / "_index.json").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    return {"nodes": count, "distribution": distribution, "metadata_snapshot_prepared": True,
            "metadata_snapshot_sha256": hashlib.sha256((root / "_index.json").read_bytes()).hexdigest(),
            "markdown_sha256": hashes.hexdigest(), "generator_schema": 1}


def latency(values):
    values = sorted(values)
    return {"n": len(values), "mean_ms": statistics.mean(values),
            "p50_ms": statistics.median(values),
            "p95_ms": values[max(0, (95 * len(values) + 99) // 100 - 1)]}


def replay(args):
    base = Path(args.workspace).resolve()
    if base.exists() or Path(args.output).exists():
        raise ValueError("Use new workspace and output paths; preserve previous measurements")
    base.mkdir(parents=True)
    configure(base / "controller")
    report = {"date": time.strftime("%Y-%m-%d"), "status": "running",
              "platform": platform.platform(), "python": sys.version,
              "command": sys.argv, "rounds": args.rounds, "manifest": None,
              "ready": {}, "runs": [], "mismatches": [], "errors": [],
              "limits": ["synthetic real Markdown; not a QA or leaderboard score",
                         "single serial client per independent engine process; not concurrency",
                         "result cache/gates off; exact production BM25 RRF enabled explicitly",
                         "native metadata snapshot prepared outside timings; first BM25 build reported separately",
                         "OS cache not flushed; alternating warm request order",
                         "write duration excluded from query latency; observer copies raw search rows",
                         "p95 is nearest-rank; small subgroups cannot establish tail SLOs",
                         "slot owned bytes exclude shared strings; RSS includes complete worker"]}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    clients = {}
    try:
        source = base / "fixture"
        report["manifest"] = fixture(source, args.count, args.distribution)
        sources = {"before": Path(args.baseline).resolve(),
                   "after": Path(__file__).resolve().parents[1]}
        for name, repo in sources.items():
            root = base / name
            shutil.copytree(source, root)
            print(name, "loading independent engine", flush=True)
            clients[name] = Client(repo, root, base / (name + "-stderr.log"))
            report["ready"][name] = clients[name].ready
            if clients[name].ready["nodes"] != args.count:
                raise AssertionError("Incomplete metadata fixture")
            print(name, "init_ms", clients[name].ready["init_ms"], flush=True)
            save()
        def pair(request, phase, turn, kind="common"):
            order = ("before", "after") if turn % 2 else ("after", "before")
            results = {name: clients[name].ask(request) for name in order}
            if request["op"] == "query":
                identities = {(v["full_signature"], v["raw_signature"], v["bm25"]["matched"])
                              for v in results.values()}
                if len(identities) != 1:
                    report["mismatches"].append({"phase": phase, "turn": turn, "request": request})
                    raise AssertionError("Frozen baseline / candidate result mismatch")
            report["runs"].append({"phase": phase, "turn": turn, "kind": kind,
                                   "order": order, "request": request, "arms": results})
            return results
        common = {"op": "query", "q": "commonword secondword"}
        pair(common, "cold", 1)
        print("cold query builds complete", flush=True)
        report["cold_memory"] = {n: c.ask({"op": "stats"}) for n, c in clients.items()}
        save()
        for turn in range(1, args.rounds + 1):
            pair(common, "warm", turn)
            inserting = turn % 4 == 0
            nid = f"new_{turn:08d}" if inserting else f"entry_{(turn * 7919) % args.count:08d}"
            content = f"commonword secondword topic{turn % 4096} 记忆检索 资料条目 {turn}\n"
            if args.distribution == "varied":
                content += "padding " * (turn % 111) + "commonword " * (turn % 11)
            pair({"op": "write", "id": nid, "content": content,
                  "override": not inserting, "clock": 1800100000.0 + turn}, "write", turn)
            kind, text = (("common", common["q"]), ("rare", "topic409"),
                          ("chinese", "记忆检索"))[(turn - 1) % 3]
            request = {"op": "query", "q": text}
            pair(request, "insert_query" if inserting else "update_query", turn, kind)
            pair(request, "warm_after_write", turn, kind)
            pair({"op": "query", "q": "topic409"}, "rare", turn, "rare")
            pair({"op": "query", "q": "absentmarker999xyz", "expected_hits": False},
                 "absent", turn, "absent")
            if turn % 5 == 0 or turn == args.rounds:
                print("paired round", turn, "/", args.rounds, flush=True)
                save()
        report["final_memory"] = {n: c.ask({"op": "stats"}) for n, c in clients.items()}
        report["summary"] = {name: {phase + ":" + kind: latency([
            r["arms"][name]["ms"] for r in report["runs"]
            if r["phase"] == phase and r["kind"] == kind])
            for phase, kind in sorted({(r["phase"], r["kind"]) for r in report["runs"]
                                       if r["request"]["op"] == "query"})} for name in clients}
        report["paired_queries"] = sum(r["request"]["op"] == "query" for r in report["runs"])
        if any(v["network_attempts"] for v in report["final_memory"].values()):
            raise AssertionError("Unexpected network attempt")
        report["status"] = "passed"
    except Exception as exc:
        report["errors"].append(type(exc).__name__ + ": " + str(exc))
        report["status"] = "failed"
        raise
    finally:
        save()
        for client in clients.values():
            client.close()
    print(json.dumps({"status": report["status"], "paired_queries": report["paired_queries"],
                      "summary": report["summary"], "final_memory": report["final_memory"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--count", type=int, default=10000)
    parser.add_argument("--rounds", type=int, default=60)
    parser.add_argument("--distribution", choices=("uniform", "varied"), default="uniform")
    args = parser.parse_args()
    if args.worker:
        worker(args.repo.resolve(), args.root.resolve())
    else:
        if not args.baseline or not args.workspace or not args.output or args.count < 410 or args.rounds < 4:
            parser.error("baseline/workspace/output, count >= 410, rounds >= 4 required")
        replay(args)


if __name__ == "__main__":
    main()
