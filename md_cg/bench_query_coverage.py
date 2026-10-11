# -*- coding: utf-8 -*-
"""Paired synthetic mechanism benchmark through the production search API.

This is not LoCoMo, the private 86-query corpus, an LLM QA test, or a load test.
Both arms use the same store, scores, 16-key budget and candidate caps.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time

from . import mdcg
from .mdcos import MdCGOS

PREFIX = "查询当前季度项目研发计划以及各个部门资源协调落实进展和阶段预算分配情况"
FACTS = ("晶格退火温度曲线", "齿轮啮合振动频谱", "星云脉冲辐射强度", "晶圆蚀刻掩膜厚度",
         "热泵蒸发冷凝压差", "船舶锚链拉伸极限", "岩层孔隙渗流系数", "磁芯饱和通量阈值")
FLAG = "MDCG_CN_GRAMS_COVERAGE"


@contextmanager
def settings(values):
    before = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for k, value in before.items():
            if value is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = value


def summary(samples):
    ordered = sorted(samples)
    return {"n": len(samples), "mean_ms": statistics.mean(samples),
            "p50_ms": statistics.median(samples),
            "p95_ms": ordered[math.ceil(len(samples) * 0.95) - 1]}


def measure(root, fillers, rounds, strong=False):
    cg = MdCGOS(str(root))
    try:
        for i in range(fillers):
            cg.add(f"filler{i:05d}", PREFIX if strong else "当前季度", importance=0.5,
                   role="knowledge")
        for i, fact in enumerate(FACTS):
            cg.add(f"gold{i}", fact, importance=0.5, role="knowledge")
        cg.flush()
        cases = []
        for i, fact in enumerate(FACTS):
            clue = "特别需要了解" + fact + "在恒定压力下的实验参数如何设置"
            for kind, query in (("tail", PREFIX + "\n" + clue),
                                ("head", clue + "\n" + PREFIX), ("short", fact)):
                cases.append({"kind": kind, "query": query, "gold": f"gold{i}"})
        results, timings = {"prefix": [], "coverage": []}, {"prefix": [], "coverage": []}
        for index, case in enumerate(cases):
            signatures = {}
            for iteration in range(rounds + 1):  # first pair warms document caches
                arms = ("prefix", "coverage") if (index + iteration) % 2 == 0 else ("coverage", "prefix")
                for arm in arms:
                    with settings({FLAG: "1" if arm == "coverage" else "0"}):
                        started = time.perf_counter_ns()
                        rows, meta = cg.search(case["query"], k=10, record=False,
                                               judge=False, include_neg=False)
                        elapsed = (time.perf_counter_ns() - started) / 1e6
                        signature = [(r[0]["id"], r[1]) for r in rows]
                        if arm in signatures and signature != signatures[arm]:
                            raise AssertionError("ranking changed during paired repetitions")
                        signatures[arm] = signature
                        if iteration:
                            timings[arm].append(elapsed)
                        if iteration == 0:
                            ids = [r[0]["id"] for r in rows]
                            results[arm].append({**case, "rank": ids.index(case["gold"]) + 1
                                                if case["gold"] in ids else None,
                                                 "ids": ids, "tier": meta.get("tier"),
                                                 "pre_cap": meta.get("pre_cap"),
                                                 "scanned": meta.get("scanned"),
                                                 "grams": mdcg.cn_recall_grams(case["query"])})
        return {"nodes": fillers + len(FACTS), "strong_prefix_control": strong,
                "rounds": rounds, "cases": results,
                "hit_at_10": {arm: {kind: {"hit": sum(r["rank"] is not None for r in rows if r["kind"] == kind),
                                          "total": sum(r["kind"] == kind for r in rows)}
                                    for kind in ("tail", "head", "short")}
                              for arm, rows in results.items()},
                "timing": {arm: summary(samples) for arm, samples in timings.items()}}
    finally:
        cg.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fillers", type=int, default=701)
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if args.fillers < 0 or args.rounds < 1:
        ap.error("fillers >= 0 and rounds >= 1 required")
    root = Path(__file__).resolve().parents[1]
    source_files = ["md_cg/mdcg.py", "md_cg/mdcos.py", "md_cg/query_coverage.py", "md_cg/hotcache.py",
                    "rust/src/text.rs", "md_cg/bench_query_coverage.py"]
    sha = lambda: {f: hashlib.sha256((root / f).read_bytes()).hexdigest() for f in source_files}
    before = sha()
    config = {"MDCG_HOTCACHE": "0", "MDCG_READ_CACHE": "1", "MDCG_CN_GRAMS": "1",
              "MDCG_UNIFY_QUERY": "0", "MDCG_SEMANTIC": "0", "MDCG_EN_ATOMS": "0",
              "MDCG_RETRIEVAL_PIPELINE": "0", "MDCG_RRF_CANDIDATES": "0",
              "MDCG_SCORE_MODE": "legacy", "MDCG_FRESHNESS": "0"}
    original_mode = mdcg.SCORE_MODE
    try:
        with tempfile.TemporaryDirectory(prefix="query_coverage_bench_") as directory, settings(config):
            # SCORE_MODE is captured at import time, unlike the query flags.
            # Pin the actual scoring constant as well as the environment.
            mdcg.SCORE_MODE = config["MDCG_SCORE_MODE"]
            effective = {"score_mode": mdcg.SCORE_MODE, "global_cap": mdcg.GLOBAL_CAP}
            fixture = measure(Path(directory) / "thin", args.fillers, args.rounds)
            control = measure(Path(directory) / "strong", args.fillers, args.rounds, strong=True)
    finally:
        mdcg.SCORE_MODE = original_mode
    if before != sha():
        raise AssertionError("source changed during benchmark")
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                         encoding="utf-8", check=True).stdout.strip()
    evidence = {"base_commit": git, "python": sys.version, "platform": platform.platform(),
                "settings": config, "effective": effective, "source_sha256": before,
                "fixture": fixture, "control": control,
                "limits": ["synthetic mechanism fixture, not real-dialogue QA",
                           "warm document cache, no result cache; OS caches not cleared",
                           "latency is measured, no speedup assumed", "single process, no load test"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"hit_at_10": fixture["hit_at_10"], "timing": fixture["timing"],
                      "control_hit_at_10": control["hit_at_10"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
