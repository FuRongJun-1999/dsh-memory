"""Native recall + optional real-reader replay on a pinned public Hive snapshot.

Gold cards are read only by score(), after retrieval finishes. Reader prompts
contain question and retrieved source excerpts, never cards. Rule-layer scores
are diagnostics, not the benchmark's semantic adjudication or leaderboard entry.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def git_head(repo):
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                   text=True, encoding="utf-8", errors="replace").strip()


def retrieve(args):
    sys.path.insert(0, str(args.repo.resolve()))
    for name in list(os.environ):
        if name.startswith("MDCG_"):
            os.environ.pop(name)
    os.environ.update(MDCG_AUX_ROOT=str(args.output.parent / (args.strategy + "-aux")),
                      MDCG_UNIFY_QUERY="0", MDCG_HOTCACHE="0", MDCG_FRESHNESS="0", MDCG_EN_ATOMS="0")
    from md_cg.mdcos import MdCGOS
    bench = args.bench
    chapters = [c for path in sorted((bench / "corpus").glob("u*.json"))
                for c in json.loads(path.read_text(encoding="utf-8"))["chapters"]]
    questions = json.loads((bench / "questions/题目_主轮.json").read_text(encoding="utf-8"))
    store = args.output.parent / (args.output.stem + "-memory")
    if store.exists():
        raise ValueError("Use a new output filename; benchmark source store must be fresh")
    cg = MdCGOS(str(store))
    try:
        for index, chapter in enumerate(chapters):
            edges = ([{"target": chapters[index + 1]["cid"], "relation_type": "sequential",
                       "confidence": 1.0, "condition": "source chapter order"}]
                     if index + 1 < len(chapters) else [])
            cg.add(chapter["cid"], chapter["text"], layer="knowledge", tags=[chapter["title"]],
                   source="hive-memory-bench:" + chapter["cid"], edges=edges)
        cg.flush()
        rows = []
        for question in questions:
            kw = dict(budget_tokens=args.budget, max_item_tokens=args.item_budget,
                      paths=("bm25", "chain"), k=20, judge=False)
            if args.strategy == "query":
                kw["excerpt_strategy"] = "query"
            started = time.perf_counter()
            result = cg.recall(question["question"], **kw)
            elapsed = (time.perf_counter() - started) * 1000
            context = "\n\n".join("[" + item["id"] + "]\n" + item["content"] for item in result["pack"])
            rows.append({**question, "context": context, "pack": result["pack"],
                         "tokens": result["tokens_used"], "retrieval_ms": elapsed,
                         "meta": result["meta"]})
            if len(rows) % 20 == 0:
                print(args.strategy, "retrieved", len(rows), flush=True)
        files = ["md_cg/mdcos.py", "md_cg/chain.py", "md_cg/bm25.py", "md_cg/query_excerpt.py"]
        result = {"strategy": args.strategy, "budget_tokens": args.budget, "item_budget": args.item_budget,
                  "paths": ["bm25", "chain"], "repo_head": git_head(args.repo),
                  "source_sha256": {p: digest(args.repo / p) for p in files if (args.repo / p).exists()},
                  "benchmark_head": git_head(bench),
                  "dataset_sha256": {str(p.relative_to(bench)): digest(p) for p in
                                       sorted((bench / "corpus").glob("u*.json"))
                                       + [bench / "questions/题目_主轮.json"]},
                  "chapters": len(chapters), "rows": rows}
        write(args.output, result)
        print(args.strategy, len(rows), "p50_ms", round(statistics.median(r["retrieval_ms"] for r in rows), 3), flush=True)
    finally:
        cg.close()


def parse_json(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    first, last = text.find("{"), text.rfind("}")
    return json.loads(text[first:last + 1])


def reader(args):
    import yaml

    # Only this function sees the credential. Never include it in args or logs.
    vault = yaml.safe_load(args.auth_file.read_text(encoding="utf-8"))
    key = (vault.get("refs") or {}).get("DEEPSEEK_API_KEY", "")
    if not key:
        raise ValueError("Harness credential unavailable")
    material = json.loads(args.input.read_text(encoding="utf-8"))
    contract = (args.bench / "questions/作答契约.md").read_text(encoding="utf-8").split("---")[1].strip()
    contract = contract.replace("写入指定的输出文件 `sut/out/<qid>.json`（文件内容就是该对象，不要代码块包裹、不要额外说明）",
                                "直接输出该对象（不要代码块包裹、不要额外说明）")
    prompts = [(row, contract + "\n\n以下是检索到的原文片段，不是全文；[…] 表示有省略，不能跨省略拼接引文。\n\n"
                + row["context"] + "\n\n题目：" + row["qid"] + "\n" + row["question"])
               for row in material["rows"][:args.limit or None]]
    args.output.mkdir(parents=True, exist_ok=True)

    def work(pair):
        row, prompt = pair
        spec = {"model": args.model, "messages": [{"role": "user", "content": prompt}],
                "temperature": 0, "thinking": {"type": "disabled"}, "max_tokens": 2400}
        fingerprint = hashlib.sha256(json.dumps(spec, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        path = args.output / (row["qid"] + ".json")
        if path.exists():
            old = json.loads(path.read_text(encoding="utf-8"))
            if old.get("fingerprint") == fingerprint and old.get("ok"):
                return row["qid"], True, "cached"
        for attempt in range(2):
            started = time.perf_counter()
            try:
                request = urllib.request.Request(args.api_base.rstrip("/") + "/chat/completions",
                                                 data=json.dumps(spec, ensure_ascii=False).encode("utf-8"),
                                                 headers={"Authorization": "Bearer " + key,
                                                          "Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=120) as response:
                    data = json.load(response)
                message = data["choices"][0]["message"]["content"]
                answer = parse_json(message)
                if answer.get("qid") != row["qid"] or not isinstance(answer.get("evidence"), list):
                    raise ValueError("invalid answer contract")
                write(path, {"ok": True, "fingerprint": fingerprint, "request": spec,
                             "response": answer, "raw": message, "usage": data.get("usage"),
                             "returned_model": data.get("model"),
                             "elapsed_seconds": time.perf_counter() - started,
                             "finish_reason": data["choices"][0].get("finish_reason"), "attempt": attempt + 1})
                return row["qid"], True, "called"
            except Exception as exc:
                error = {"type": type(exc).__name__}
                if isinstance(exc, urllib.error.HTTPError):
                    error["http_status"] = exc.code
                # No raw exception/request/header text may enter public evidence.
                if attempt:
                    write(path, {"ok": False, "fingerprint": fingerprint, "error": error})
                    return row["qid"], False, "failed"
                time.sleep(1)
    complete = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = [pool.submit(work, pair) for pair in prompts]
        for future in as_completed(jobs):
            complete.append(future.result())
            if len(complete) % 10 == 0 or not complete[-1][1]:
                print("reader", len(complete), "/", len(prompts), complete[-1], flush=True)
    write(args.output / "manifest.json", {"model": args.model, "input_sha256": digest(args.input),
                                          "completed": complete, "attempts_per_item_max": 2})
    if not all(ok for _, ok, _ in complete):
        raise SystemExit("Reader failures remain; never score them as successful answers")


def score(args):
    import yaml

    bench = args.bench
    spec = importlib.util.spec_from_file_location("hive_official_judge", bench / "judge.py")
    judge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(judge)
    idx = judge.chapter_index(judge.load_units())
    data = json.loads(args.input.read_text(encoding="utf-8"))
    chapters = {c["cid"]: c["text"] for path in sorted((bench / "corpus").glob("u*.json"))
                for c in json.loads(path.read_text(encoding="utf-8"))["chapters"]}
    norm = lambda text: re.sub(r"\s+", "", text)
    readings = []
    for row in data["rows"]:
        card = yaml.safe_load((bench / "cards" / (row["qid"] + ".yaml")).read_text(encoding="utf-8"))
        evidence = card.get("supporting_evidence") or card.get("evidence_pool") or []
        valid = [e for e in evidence if e.get("quote") and norm(e["quote"]) in norm(chapters.get(e.get("cid"), ""))]
        found = sum(norm(e["quote"]) in norm("\n".join(p["content"] for p in row["pack"] if p["id"] == e["cid"]))
                    for e in valid)
        reading = {"qid": row["qid"], "kind": card["kind"], "annotated_quotes": len(evidence),
                   "valid_source_quotes": len(valid), "retained_quotes": found,
                   "quote_recall": found / len(valid) if valid else None}
        if args.answers and (args.answers / (row["qid"] + ".json")).exists():
            answer = json.loads((args.answers / (row["qid"] + ".json")).read_text(encoding="utf-8"))
            if not answer.get("ok"):
                reading["reader_failed"] = True
            else:
                response = answer["response"]
                coverage = (judge.axis_conclusion_objective(card, response) if card["kind"] == "objective"
                            else judge.axis_coverage_open(card, response))
                citations = judge.axis_evidence(card, response, idx, min_required=0, open_mode=card["kind"] != "objective")
                verdict = judge.judge(card, response, idx)
                reading.update(rule_coverage=coverage.get("coverage", coverage.get("score", 0)),
                               rule_coverage_pass=bool(coverage["pass"]), rule_verdict=verdict,
                               citations=citations, usage=answer.get("usage"))
        readings.append(reading)
    qa = [r for r in readings if "rule_coverage" in r]
    result = {"metric_boundary": "Annotated source quote retention; optional real-reader official RULE layer only, no semantic adjudication or leaderboard claim",
              "strategy": data["strategy"], "budget_tokens": data["budget_tokens"], "questions": len(readings),
              "annotated_valid_quotes": sum(r["valid_source_quotes"] for r in readings),
              "retained_quotes": sum(r["retained_quotes"] for r in readings),
              "macro_quote_recall": statistics.mean(r["quote_recall"] for r in readings if r["quote_recall"] is not None),
              "reader_scored": len(qa), "rule_coverage_mean": statistics.mean(r["rule_coverage"] for r in qa) if qa else None,
              "rule_coverage_pass_count": sum(r["rule_coverage_pass"] for r in qa),
              "retrieval_p50_ms": statistics.median(r["retrieval_ms"] for r in data["rows"]), "rows": readings}
    write(args.output, result)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("retrieve", "reader", "score"))
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--bench", type=Path, required=True)
    parser.add_argument("--strategy", choices=("prefix", "query"), default="prefix")
    parser.add_argument("--budget", type=int, default=1200)
    parser.add_argument("--item-budget", type=int, default=250)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--answers", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--auth-file", type=Path, default=Path.home() / ".dsh/.credentials.yaml")
    parser.add_argument("--api-base", default="https://api.deepseek.com")
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    {"retrieve": retrieve, "reader": reader, "score": score}[args.action](args)


if __name__ == "__main__":
    main()
