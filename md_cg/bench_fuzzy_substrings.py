"""Paired runtime benchmark for the graded substring retrieval optimization.

Run from a Git checkout (no LLM or third-party Python packages required)::

    python -X utf8 -m md_cg.bench_fuzzy_substrings --rounds 3 \
        --scale-nodes 10000 --output fuzzy-results.json

The baseline MdCGOS implementation is loaded from --baseline-ref; both arms
share the checkout's other modules and the exact same Markdown files. This
isolates the mdcos.py change, rather than comparing different dependencies.
Hot result caching and freshness are disabled for deterministic comparisons;
the production document read cache remains enabled. The public dataset uses
the existing Jaccard / uncapped evaluation settings, not deployment defaults.

The 567-node public pool contains only gold evidence and keyword queries.
The larger pool is synthetic. Neither is an official LoCoMo QA score or proof
of million-record latency. No system file cache is cleared. "First query"
means a new engine instance, not cold storage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import types

from . import eval_common as ec, mdcos, nodefile
from . import bench_locomo_zh_public as public

BASELINE_REF = "d02c1fce939ffbfd82a59e5e2a90bdaaf6c42e0e"


def load_baseline(ref):
    """Load actual pre-change code without replacing the current module."""
    repo = Path(__file__).resolve().parents[1]
    source = subprocess.check_output(
        ["git", "show", f"{ref}:md_cg/mdcos.py"], cwd=repo).decode("utf-8")
    sha = subprocess.check_output(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=repo, text=True, encoding="utf-8", errors="replace").strip()
    baseline = types.ModuleType("md_cg._fuzzy_benchmark_baseline")
    baseline.__package__ = "md_cg"
    baseline.__file__ = str(repo / "md_cg" / "mdcos.py")
    baseline.__benchmark_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    sys.modules[baseline.__name__] = baseline
    exec(compile(source, f"git:{sha}:md_cg/mdcos.py", "exec"), baseline.__dict__)
    return baseline, sha


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def latency(values):
    return {"n": len(values), "total_ms": sum(values),
            "mean_ms": statistics.mean(values),
            "p50_ms": percentile(values, 0.50),
            "p95_ms": percentile(values, 0.95),
            "p99_ms": percentile(values, 0.99)}


def signature(result):
    # Compare full nodes, scores, qualifications, provenance and metadata.
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def paired_calls(before, after, rounds, iterations):
    expected, actual = before(), after()
    if actual != expected:
        raise AssertionError((expected, actual))
    samples = {"baseline": [], "optimized": []}
    for round_no in range(rounds):
        order = ("baseline", "optimized") if round_no % 2 == 0 else (
            "optimized", "baseline")
        for arm in order:
            call = before if arm == "baseline" else after
            started = time.perf_counter()
            for _ in range(iterations):
                call()
            samples[arm].append((time.perf_counter() - started) * 1000)
    return {"iterations_per_round": iterations, "round_ms": samples,
            "score": actual, "speedup": statistics.median(samples["baseline"]) /
            statistics.median(samples["optimized"])}


def kernel_benchmark(baseline, rounds, iterations):
    """Include cheap and near-exact controls, not just favorable long misses."""
    cases = (("two_char_miss", "甲乙", "完全无关文字"),
             ("three_char_miss", "甲乙丙", "完全无关文字"),
             ("full_match", "甲乙丙丁", "前言甲乙丙丁正文"),
             ("near_full", "abcdefghi", "abcdefgh"),
             ("long_near_full", "甲乙丙丁" * 15 + "末", "甲乙丙丁" * 15),
             ("long_no_hit", "甲乙丙丁戊己庚辛壬癸", "完全无关文字"))
    report = {}
    for name, term, text in cases:
        cache = {}
        report[name] = paired_calls(
            lambda: baseline._term_degree(term, text),
            lambda: mdcos._term_degree(term, text, cache), rounds, iterations)
    weights = {"甲乙": 1.0, "丙丁": 0.6, "戊己": 0.3}
    text = "甲乙丙丁戊己正文"
    prepared = mdcos._prepare_coverage(weights)
    report["weighted_direct_full"] = paired_calls(
        lambda: baseline._weighted_coverage(weights, text),
        lambda: mdcos._weighted_coverage(weights, text), rounds, iterations)
    report["weighted_prepared_full"] = paired_calls(
        lambda: baseline._weighted_coverage(weights, text),
        lambda: mdcos._weighted_coverage(weights, text, prepared), rounds, iterations)
    return report


def paired_search(label, root, questions, configs, baseline, rounds,
                  extra_read_cache=False):
    engines = {}
    setup_ms = {}
    first_ms = {}
    first_signatures = {}
    try:
        for arm, module in (("baseline", baseline), ("optimized", mdcos)):
            started = time.perf_counter()
            engines[arm] = module.MdCGOS(str(root))
            setup_ms[arm] = (time.perf_counter() - started) * 1000
            if extra_read_cache:
                ec.install_read_cache(engines[arm])
            started = time.perf_counter()
            result = engines[arm].search_rrf(
                questions[0]["question"], k=5, paths=configs[-1][1],
                judge=False, record=False)
            first_ms[arm] = (time.perf_counter() - started) * 1000
            first_signatures[arm] = signature(result)

        report = {"name": label, "nodes": len(engines["optimized"].index["nodes"]),
                  "queries_per_round": len(questions), "rounds": rounds,
                  "setup_ms": setup_ms, "first_query_ms": first_ms,
                  "first_query_equal": len(set(first_signatures.values())) == 1,
                  "extra_eval_read_cache": extra_read_cache,
                  "quality_applicable": any(q["evidence_turns"] for q in questions),
                  "configs": {}}
        for config, paths in configs:
            samples = {arm: [] for arm in engines}
            round_ms = {arm: [] for arm in engines}
            metrics = {}
            expected = {}
            mismatches = []
            for round_no in range(rounds):
                # Alternate arm order to reduce ordering / temperature bias.
                order = ("baseline", "optimized") if round_no % 2 == 0 else (
                    "optimized", "baseline")
                for arm in order:
                    rows = []
                    timings = []
                    for question in questions:
                        started = time.perf_counter()
                        result, meta = engines[arm].search_rrf(
                            question["question"], k=5, paths=paths,
                            judge=False, record=False)
                        timings.append((time.perf_counter() - started) * 1000)
                        digest = signature((result, meta))
                        qid = question["qid"]
                        if qid not in expected:
                            expected[qid] = digest
                        elif digest != expected[qid]:
                            mismatches.append({"qid": qid, "arm": arm,
                                               "round": round_no + 1})
                        rows.append({"qid": qid, "qtype": question["qtype"],
                                     "rank": ec.first_evidence_rank(
                                         result, set(question["evidence_turns"])),
                                     "top1_score": result[0][1] if result else 0.0})
                    samples[arm].extend(timings)
                    round_ms[arm].append(sum(timings))
                    metrics[arm] = ec.summarize(rows)
                    print(f"{label} {config} round={round_no + 1} {arm}: "
                          f"{sum(timings):.1f} ms", flush=True)
            medians = {arm: statistics.median(times)
                       for arm, times in round_ms.items()}
            report["configs"][config] = {
                "latency": {arm: latency(times) for arm, times in samples.items()},
                "round_total_ms": round_ms,
                "speedup_median_round": medians["baseline"] / medians["optimized"],
                "metrics": metrics, "mismatch_count": len(mismatches),
                "mismatches": mismatches,
                "reference_signatures": expected,
            }
        return report
    finally:
        for engine in engines.values():
            engine.close()


def synthetic_pool(root, count):
    """Write deterministic Markdown fixtures; never overwrite an existing pool."""
    marker = root / "_fuzzy_benchmark_fixture.json"
    fixture = {"version": 1, "nodes": count}
    if root.exists():
        if not marker.is_file() or json.loads(marker.read_text(encoding="utf-8")) != fixture:
            raise ValueError(f"Existing directory is not this benchmark pool: {root}")
        return
    root.mkdir(parents=True)
    layer = root / "knowledge"
    layer.mkdir()
    topics = ("向量索引检索", "会话更新历史", "条件空间评分", "最长命中子串",
              "数据库回退", "图像渲染管线", "天气观察记录", "数学公式推导")
    for i in range(count):
        topic = topics[i % len(topics)]
        body = f"# 生效条件：查询{topic}\n# 执行：{topic}\n"
        body += (f"档案{i:06d} {topic} 保留事实时间与来源，记录可以更新并重新检索。\n" * 8)
        fm = {"id": f"scale_{i:06d}", "layer": "knowledge", "tags": [topic],
              "created_at": 1800000000.0, "importance": 0.5}
        (layer / f"scale_{i:06d}.md").write_text(
            nodefile.dumps(fm, body), encoding="utf-8")
    engine = mdcos.MdCGOS(str(root))
    engine.close()
    marker.write_text(json.dumps(fixture), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default=BASELINE_REF)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--scale-nodes", type=int, default=0)
    parser.add_argument("--kernel-iterations", type=int, default=200000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.rounds < 1 or args.scale_nodes < 0 or args.kernel_iterations < 1:
        parser.error("rounds/iterations must be positive and scale-nodes nonnegative")

    # Both arms have exactly the same settings; do not mutate system caches.
    os.environ.update(MDCG_HOTCACHE="0", MDCG_READ_CACHE="1", MDCG_FRESHNESS="0")
    ec.unlock_global_cap()
    ec.use_jaccard()
    baseline, sha = load_baseline(args.baseline_ref)
    baseline.GLOBAL_CAP = mdcos.GLOBAL_CAP
    corpus = list(ec.iter_jsonl(public.CORPUS567))
    questions = list(ec.iter_jsonl(public.QUESTIONS500))
    pool = public.build_pool(corpus)
    pool.close()
    report = {"baseline_ref": sha, "python": sys.version,
              "baseline_mdcos_sha256": baseline.__benchmark_sha256,
              "optimized_mdcos_sha256": hashlib.sha256(
                  Path(mdcos.__file__).read_bytes()).hexdigest(),
              "inputs_sha256": {Path(p).name: hashlib.sha256(Path(p).read_bytes()).hexdigest()
                                for p in (public.CORPUS567, public.QUESTIONS500)},
              "platform": platform.platform(), "processor": platform.processor(),
              "logical_cpus": os.cpu_count(),
              "settings": {"hotcache": False, "readcache": True, "freshness": False,
                           "score_mode": "jaccard", "global_cap": mdcos.GLOBAL_CAP,
                           "k": 5, "judge": False, "record": False},
              "limits": ["public pool: gold-only keyword retrieval, not official QA",
                         "scale pool: synthetic, not a production corpus",
                         "single client; engine API latency, excludes MCP/network/LLM",
                         "document cache warm; operating system cache not cleared",
                         "baseline mdcos from Git shares unchanged checkout dependencies"],
              "datasets": [],
              "kernel": kernel_benchmark(baseline, args.rounds, args.kernel_iterations)}
    report["datasets"].append(paired_search(
        "locomo-zh-500", Path(public.ROOT), questions, public.CONFIGS,
        baseline, args.rounds, extra_read_cache=True))
    # Save the public run even if the optional larger run is interrupted.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.scale_nodes:
        root = Path(public.ROOT).with_name(f"_md_cg_eval_fuzzy_scale_{args.scale_nodes}")
        synthetic_pool(root, args.scale_nodes)
        queries = ("向量索引检索算法", "会话更新历史记录", "条件空间评分计算", "最长命中子串查询",
                   "数据库回退路径", "图像渲染管线处理", "天气观察记录日期", "数学公式推导步骤",
                   "无关联资料", "xyz-nonmatching-token")
        scale_questions = [{"qid": f"scale_q_{i}", "question": query,
                            "qtype": "synthetic", "evidence_turns": []}
                           for i, query in enumerate(queries)]
        report["datasets"].append(paired_search(
            "synthetic-scale", root, scale_questions,
            (("fuzzy", ("fuzzy",)), ("lexical,fuzzy", ("lexical", "fuzzy"))),
            baseline, args.rounds))
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    failures = sum(config["mismatch_count"] for dataset in report["datasets"]
                   for config in dataset["configs"].values())
    failures += sum(not dataset["first_query_equal"] for dataset in report["datasets"])
    for dataset in report["datasets"]:
        for name, config in dataset["configs"].items():
            print(f"{dataset['name']} {name}: "
                  f"{config['speedup_median_round']:.3f}x, "
                  f"mismatches={config['mismatch_count']}")
    print(f"Full-result mismatches: {failures}; report: {args.output}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
