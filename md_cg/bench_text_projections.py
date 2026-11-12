"""Separate-process, alternating-order replay of frozen source checkouts.

No result cache, no patched production functions. Synthetic long documents and
the bundled public keyword corpus are reported separately; neither measures QA.
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
import tempfile
import time


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def worker(repo, root):
    sys.path.insert(0, str(repo))
    for name in list(os.environ):
        if name.startswith("MDCG_"):
            os.environ.pop(name)
    os.environ.update(MDCG_HOTCACHE="0", MDCG_READ_CACHE="1", MDCG_FRESHNESS="0",
                      MDCG_UNIFY_QUERY="0", MDCG_EN_ATOMS="0", MDCG_SEMANTIC="0",
                      MDCG_RRF_CANDIDATES="0")
    from md_cg import mdcg
    from md_cg.mdcos import MdCGOS
    from md_cg.bench_rrf_candidates import process_memory
    cg = MdCGOS(str(root))
    print(json.dumps({"ready": True, "nodes": len(cg.index["nodes"]),
                      "commit": subprocess.check_output(
                          ["git", "-C", str(repo), "rev-parse", "HEAD"],
                          text=True, encoding="utf-8", errors="replace").strip()}), flush=True)
    try:
        for line in sys.stdin:
            req = json.loads(line)
            if req["op"] == "close":
                break
            if req["op"] == "stats":
                attrs = ("_exact_text_cache", "_like_lower_cache")
                projections = {name: {"entries": len(getattr(cg, name, {})),
                                     "value_bytes": sum(sys.getsizeof(r[1]) for r in getattr(cg, name, {}).values())}
                               for name in attrs}
                print(json.dumps({"memory": process_memory(), "projections": projections}), flush=True)
                continue
            mdcg.SCORE_MODE = req.get("mode", "legacy")
            start = time.perf_counter_ns()
            if req["op"] == "write":
                cg.add(req["id"], req["content"], layer="knowledge", importance=0.5,
                       session="projection-bench")
                cg.flush()
                result = {"written": req["id"]}
            else:
                kw = {"k": 50, "judge": False, "record": False}
                if req["op"] == "rrf":
                    hits, meta = cg.search_rrf(req["q"], paths=("lexical",), **kw)
                else:
                    hits, meta = cg.search(req["q"], **kw)
                result = {"hits": hits, "meta": {name: meta.get(name) for name in (
                    "paths", "fused", "provenance", "goal_used", "judge_filtered",
                    "expand_source", "judge_ranking", "early_stopped", "boundary")}}
            elapsed = (time.perf_counter_ns() - start) / 1e6
            # Full returned cards and semantic metadata are compared, except
            # after add() where timestamps differ across processes by design.
            if req.get("after_write"):
                result = [(h[0]["id"], h[0].get("content"), h[1:]) for h in hits]
            print(json.dumps({"ms": elapsed, "signature": digest(result),
                              "ids": [h[0]["id"] for h in hits] if req["op"] not in ("write",) else []}), flush=True)
    finally:
        cg.close()


class Client:
    def __init__(self, repo, root):
        self.p = subprocess.Popen([sys.executable, "-u", "-X", "utf8", __file__,
                                   "--worker", "--repo", str(repo), "--root", str(root)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  text=True, encoding="utf-8", cwd=repo)
        self.ready = self.read()
        if not self.ready.get("ready"):
            raise RuntimeError(self.ready)

    def read(self):
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError("worker stopped without a result")
        return json.loads(line)

    def ask(self, req):
        self.p.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
        self.p.stdin.flush()
        return self.read()

    def close(self):
        self.p.stdin.write('{"op":"close"}\n')
        self.p.stdin.flush()
        self.p.stdin.close()
        if self.p.wait(timeout=30):
            raise RuntimeError("worker close failed")


def fixture(root, case, count):
    from md_cg import nodefile
    root.mkdir()
    if case == "public":
        from md_cg.bench_locomo_zh_public import body_of, CORPUS567, QUESTIONS500
        corpus = [json.loads(line) for line in Path(CORPUS567).read_text(encoding="utf-8").splitlines()]
        queries = [json.loads(line)["question"] for line in Path(QUESTIONS500).read_text(encoding="utf-8").splitlines()]
        docs = [(r["id"], body_of(r)) for r in corpus]
    else:
        paragraph = "设备校准记录用于说明实验条件与操作过程，实验日期和观测位置由记录员复核。" * 35
        docs = [(f"doc{i:04d}", (paragraph + "\n") * 8 +
                 f"\nAlpha calibration 当前季度资源协调 文档编号{i:04d}") for i in range(count)]
        queries = ["alpha calibration frequency", "当前季度资源协调", "设备校准记录",
                   "zzzznohit", "文档编号0001", "Alpha", "A B C", "🦄"]
    folder = root / "knowledge"
    folder.mkdir()
    for nid, body in docs:
        fm = {"id": nid, "layer": "knowledge", "importance": 0.5, "confidence": 0.6,
              "created_at": 1800000000.0, "tags": [], "session": "projection-bench"}
        (folder / (nid + ".md")).write_text(nodefile.dumps(fm, body), encoding="utf-8")
    files = sorted(folder.glob("*.md"))
    return queries, {"nodes": len(docs), "body_chars": sum(len(body) for _, body in docs),
                     "markdown_sha256": digest([(f.name, hashlib.sha256(f.read_bytes()).hexdigest()) for f in files]),
                     "queries_sha256": digest(queries)}


def latency(rows):
    values = sorted(rows)
    return {"n": len(values), "mean_ms": statistics.mean(values),
            "p50_ms": statistics.median(values), "p95_ms": values[int((len(values) - 1) * .95)]}


def replay(args):
    sources = {"baseline": Path(args.baseline).resolve()}
    if args.stage_one:
        sources["exact_only"] = Path(args.stage_one).resolve()
    sources["both"] = Path(__file__).resolve().parents[1]
    report = {"platform": platform.platform(), "python": sys.version, "cases": {},
              "limits": ["local warm-process microbenchmark, not throughput or QA",
                         "cold query includes lazy caches; startup is excluded",
                         "retained projection values omit mapping overhead; RSS is whole process",
                         "external edits require rebuild/clear, as with existing readcache",
                         "write parity compares content/scores/qualification/provenance, excludes timestamp fields"]}
    with tempfile.TemporaryDirectory(prefix="projection_replay_", dir=args.workspace) as temporary:
        base = Path(temporary)
        for case in ("long", "public"):
            queries, manifest = fixture(base / (case + "-source"), case, args.nodes)
            clients, runs = {}, []
            try:
                for arm, repo in sources.items():
                    root = base / (case + "-" + arm)
                    shutil.copytree(base / (case + "-source"), root)
                    clients[arm] = Client(repo, root)
                names = list(clients)
                def pair(req, ordinal, phase):
                    order = names[ordinal % len(names):] + names[:ordinal % len(names)]
                    result = {arm: clients[arm].ask(req) for arm in order}
                    if len({r["signature"] for r in result.values()}) != 1:
                        raise AssertionError(f"result mismatch: {case} {phase} {req} {result}")
                    if phase == "after_write" and any("doc0001" not in r["ids"] for r in result.values()):
                        raise AssertionError("written fresh marker was not retrieved")
                    runs.append({"phase": phase, "request": req, "order": order, "arms": result})
                pair({"op": "rrf", "q": queries[0]}, 0, "cold")
                # Warm every query and both public entry points in every arm.
                for i, q in enumerate(queries):
                    for op in ("rrf", "search"):
                        pair({"op": op, "q": q}, i, "warmup")
                for repeat in range(args.repeats if case == "long" else 1):
                    for i, q in enumerate(queries):
                        for op in ("rrf", "search"):
                            pair({"op": op, "q": q}, repeat + i, "warm")
                    print(f"{case}: warm repeat {repeat+1} complete", flush=True)
                stats = {arm: client.ask({"op": "stats"}) for arm, client in clients.items()}
                for mode in ("legacy", "jaccard"):
                    for i, q in enumerate(queries[:8]):
                        pair({"op": "rrf", "q": q, "mode": mode}, i, "mode_parity")
                if case == "long":
                    for i in range(4):
                        pair({"op": "write", "id": "doc0001", "content": f"Alpha freshversion{i} A B C"}, i, "write")
                        pair({"op": "rrf", "q": f"freshversion{i}", "after_write": True}, i, "after_write")
                summary = {arm: {op: latency([r["arms"][arm]["ms"] for r in runs
                                              if r["phase"] == "warm" and r["request"]["op"] == op])
                                 for op in ("rrf", "search")} for arm in clients}
                report["cases"][case] = {"manifest": manifest, "workers": {a: c.ready for a, c in clients.items()},
                                          "summary": summary, "memory": stats, "runs": runs,
                                          "parity": "all signatures equal"}
                print(json.dumps({"case": case, "summary": summary, "memory": stats}), flush=True)
            finally:
                for client in clients.values():
                    client.close()
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--repo")
    parser.add_argument("--root")
    parser.add_argument("--baseline")
    parser.add_argument("--stage-one")
    parser.add_argument("--workspace")
    parser.add_argument("--nodes", type=int, default=1000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", default="text-projections.json")
    options = parser.parse_args()
    if options.worker:
        worker(Path(options.repo), Path(options.root))
    else:
        if not options.baseline or not options.workspace or options.nodes < 2 or options.repeats < 1:
            parser.error("--baseline, --workspace, nodes >= 2 and repeats >= 1 are required")
        replay(options)
