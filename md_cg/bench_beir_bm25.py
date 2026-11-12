"""Official BEIR local task evaluation through production search_rrf.

python -X utf8 -m md_cg.bench_beir_bm25 --name nfcorpus --split dev \
    --data <original-beir-dataset> --pool <markdown-pool> --output-dir <out> \
    --beir-root <official-beir-checkout> --arms bm25,legacy

Requires the official BEIR evaluator, pytrec-eval-terrier, numpy and tqdm.
No model/dataset download or test-set parameter tuning is performed. BM25 uses
fixed production constants; legacy means lexical+fuzzy with candidate indexing
off. Both retain the native top-50 per-path RRF limit, gates and read entry point.
This is a local evaluation of official tasks, not a leaderboard submission.
"""
import argparse
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", choices=("scifact", "nfcorpus"), required=True)
    parser.add_argument("--split", choices=("train", "dev", "test"), required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--beir-root", type=Path, required=True)
    parser.add_argument("--arms", default="bm25")
    args = parser.parse_args()
    arms = args.arms.split(",")
    if len(set(arms)) != len(arms) or set(arms) - {"bm25", "legacy"}:
        parser.error("--arms accepts distinct bm25,legacy")
    repo = Path(__file__).resolve().parents[1]
    data, root, out, official = (p.resolve() for p in (
        args.data, args.pool, args.output_dir, args.beir_root))
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(official))
    os.environ.update(MDCG_HOTCACHE="0", MDCG_READ_CACHE="1", MDCG_FRESHNESS="0",
                      MDCG_RETRIEVAL_PIPELINE="0", MDCG_SEMANTIC="0", MDCG_UNIFY_QUERY="0",
                      MDCG_EN_ATOMS="0", MDCG_RRF_CANDIDATES="0",
                      DSH_HOME=str(root.parent / "bm25-beir-dsh-home"),
                      MDCG_AUX_ROOT=str(root.parent / "bm25-beir-aux"))
    from beir.datasets.data_loader import GenericDataLoader
    from beir.retrieval import evaluation as evaluation_module
    from beir.retrieval.evaluation import EvaluateRetrieval
    from . import bm25, mdcos, nodefile
    from .bench_fuzzy_substrings import latency
    corpus, queries, qrels = GenericDataLoader(data_folder=str(data)).load(split=args.split)
    assert len(corpus) == {"scifact": 5183, "nfcorpus": 3633}[args.name]
    assert set(queries) == set(qrels)
    if args.split == "test":
        assert len(queries) == {"scifact": 300, "nfcorpus": 323}[args.name]
    # Corpus only: no query/qrel-derived material is placed into Markdown.
    spec = {"corpus_sha256": digest(data / "corpus.jsonl"), "documents": len(corpus),
            "format": "title newline abstract", "schema": 1}
    marker = root / "_beir_fixture.json"
    if root.exists():
        assert marker.is_file() and json.loads(marker.read_text(encoding="utf-8")) == spec
    else:
        (root / "knowledge").mkdir(parents=True)
        for docid, document in corpus.items():
            assert re.fullmatch(r"[A-Za-z0-9_-]+", docid), "Unsafe fixture document ID"
            nid = "beir_" + docid
            fm = {"id": nid, "layer": "knowledge", "importance": 0.4,
                  "created_at": 1800000000.0, "tags": []}
            text = (document.get("title") or "") + "\n" + (document.get("text") or "")
            (root / "knowledge" / (nid + ".md")).write_text(nodefile.dumps(fm, text), encoding="utf-8")
        marker.write_text(json.dumps(spec), encoding="utf-8")
    assert len(list((root / "knowledge").glob("*.md"))) == len(corpus)
    prefix = "beir-bm25-" + args.name + "-" + args.split
    report_file = out / (prefix + ".json")
    assert not report_file.exists(), "Use a new output directory; do not overwrite a frozen run"
    report = {"benchmark": "BEIR " + args.name, "split": args.split,
              "corpus": len(corpus), "queries": len(queries), "arms": {},
              "protocol": "full corpus; raw queries; title+abstract; no result cache; native RRF top50 per path",
              "parameters": {"k1": bm25.K1, "b": bm25.B, "limit": bm25.LIMIT},
              "tokenizer": "Unicode words/numbers; Han unigrams+bigrams; lowercase; no stemming/stopwords",
              "judge": False, "record": False, "k": 100,
              "product_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True, encoding="utf-8").strip(),
              "product_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=repo)),
              "official_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=official, text=True, encoding="utf-8").strip(),
              "sha256": {name: digest(repo / "md_cg" / name) for name in (
                  "bm25.py", "mdcos.py", "readcache.py", "hotcache.py", "rrf_candidates.py", "mcp_server.py")},
              "adapter_sha256": digest(Path(__file__)),
              "evaluator_sha256": digest(Path(evaluation_module.__file__)),
              "dataset_sha256": {name: digest(data / name) for name in (
                  "corpus.jsonl", "queries.jsonl", "qrels/" + args.split + ".tsv")},
              "packages": {name: version(name) for name in ("pytrec-eval-terrier", "numpy", "tqdm")}}
    def save():
        report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    k_values = [1, 3, 5, 10, 50, 100]
    for arm in arms:
        paths = ("bm25",) if arm == "bm25" else ("lexical", "fuzzy")
        started = time.perf_counter()
        cg = mdcos.MdCGOS(str(root))
        init_ms = (time.perf_counter() - started) * 1000
        assert len(cg.index["nodes"]) == len(corpus)
        records, results = [], {}
        details = report["arms"][arm] = {"paths": paths, "records": records,
                    "init_ms": init_ms, "completed": 0, "failed": 0}
        try:
            started = time.perf_counter()
            cg.search_rrf(next(iter(queries.values())), k=100, paths=paths, judge=False, record=False)
            details["cold_first_ms"] = (time.perf_counter() - started) * 1000
            for index, (qid, question) in enumerate(queries.items()):
                started = time.perf_counter()
                rows, meta = cg.search_rrf(question, k=100, paths=paths, judge=False, record=False)
                ms = (time.perf_counter() - started) * 1000
                diag = meta.get("bm25", {})
                assert not diag.get("fallback") and not diag.get("unavailable"), (qid, diag)
                ranked = []
                for rank, row in enumerate(rows, 1):
                    docid = row[0]["id"].removeprefix("beir_")
                    assert docid in corpus
                    ranked.append({"docid": docid, "rank": rank, "rrf_score": row[1]})
                # Preserve actual engine order even when rounded RRF scores tie.
                results[qid] = {r["docid"]: float(len(ranked) - r["rank"] + 1) for r in ranked}
                records.append({"qid": qid, "ms": ms, "ranking": ranked,
                                "scanned": meta["scanned"], "bm25": diag})
                details["completed"] = len(records)
                if (index + 1) % 25 == 0:
                    save()
                    print(f"{args.name} {args.split} {arm}: {index+1}/{len(queries)}", flush=True)
            ndcg, ap, recall, precision = EvaluateRetrieval.evaluate(qrels, results, k_values)
            mrr = EvaluateRetrieval.evaluate_custom(qrels, results, k_values, metric="mrr")
            details.update(ndcg=ndcg, map=ap, recall=recall, precision=precision, mrr=mrr,
                           latency=latency([r["ms"] for r in records]))
            (out / (prefix + "-" + arm + "-run.json")).write_text(json.dumps(results), encoding="utf-8")
            with (out / (prefix + "-" + arm + ".run.trec")).open("w", encoding="utf-8") as stream:
                for qid, ranking in results.items():
                    for rank, (docid, score) in enumerate(ranking.items(), 1):
                        stream.write(f"{qid} Q0 {docid} {rank} {score:.9f} dsh-{arm}\n")
            save()
            print(arm, json.dumps({"ndcg": ndcg, "recall": recall, "latency": details["latency"]}), flush=True)
        except Exception as exc:
            details.update(failed=1, error_type=type(exc).__name__, error=str(exc))
            save()
            raise
        finally:
            cg.close()
    print(f"Complete: {sum(a['completed'] for a in report['arms'].values())} queries, 0 errors", flush=True)


if __name__ == "__main__":
    main()
