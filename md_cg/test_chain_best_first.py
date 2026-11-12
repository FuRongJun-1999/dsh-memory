# -*- coding: utf-8 -*-
"""Chain retrieval: independent exhaustive oracle, native RRF and mutation guards.

Run: python -X utf8 tests/test_chain_best_first.py [--mutate]
The oracle enumerates all simple paths on small fixtures, without walk() or
the optimized frontier. No latency thresholds, external corpus or service.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import random
import tempfile
import types
import unittest
from unittest import mock

from . import chain


def edge(target, confidence=1.0, relation="causal", condition="fixture condition"):
    return {"target": target, "confidence": confidence,
            "relation_type": relation, "condition": condition}


class Graph:
    """Index-shaped graph; adjacency() still performs real visibility/archive gates."""
    def __init__(self, outgoing):
        ids = set(outgoing)
        ids.update(e["target"] for es in outgoing.values() for e in es)
        self.index = {"nodes": {nid: {"id": nid, "subgraph": [],
                                      "edges": copy.deepcopy(outgoing.get(nid, []))}
                                 for nid in sorted(ids)}}

    def get(self, nid):
        fm = self.index["nodes"].get(nid)
        return {"frontmatter": fm, "content": "# 生效条件：seed fallback"} if fm else None


def converging_graph(width=6, layers=4, reverse=False):
    bands = [[f"weak_{d}_{i}" for i in range(width)] for d in range(layers)]
    graph = {"seed": [edge("strong_a"), edge("weak_root", .01)],
             "strong_a": [edge("strong_target")], "strong_target": [],
             "weak_root": [edge(n) for n in bands[0]]}
    for d, band in enumerate(bands):
        for nid in band:
            graph[nid] = [edge(n) for n in bands[d + 1]] if d + 1 < layers else []
    if reverse:
        for es in graph.values():
            es.reverse()
    return graph


def exhaustive(outgoing, seeds, depth=5, decay=.9, relation_types=chain.CHAIN_TYPES_DEFAULT):
    """Independent simple-path enumeration and public score formula.

    Ties: shorter depth, greater unrounded product, then node sequence.
    Edge weights are the public single source; search/pruning is independent.
    """
    choices = {}
    for start, s0 in seeds.items():
        stack = [(start, (start,), (), 1.0)]
        while stack:
            current, nodes, hops, weight = stack.pop()
            if len(hops) >= depth:
                continue
            for e in outgoing.get(current, []):
                target, rel = e["target"], chain.edge_rel(e)
                if target in nodes or (relation_types and rel not in relation_types):
                    continue
                w = chain.edge_weight(e)
                product = weight * w
                condition = chain.edge_condition(e)
                if not condition and not hops:
                    condition = "seed fallback"
                new_hops = hops + ({"from": current, "to": target,
                                    "relation_type": rel, "weight": w,
                                    "condition": condition},)
                new_nodes = nodes + (target,)
                d = len(new_hops)
                score = float(s0) * round(product, 6) * decay**d
                key = (-score, d, -product, new_nodes)
                c = {"start": start, "nodes": list(new_nodes), "hops": list(new_hops),
                     "conditions": [h["condition"] for h in new_hops],
                     "weight": round(product, 6), "depth": d,
                     "avg_weight": round(product ** (1.0 / d), 6)}
                item = {"score": round(score, 6), "chain": c, "depth": d,
                        "conditions": c["conditions"]}
                if target not in choices or key < choices[target][0]:
                    choices[target] = (key, item)
                stack.append((target, new_nodes, new_hops, product))
    return {nid: value[1] for nid, value in choices.items()}


def assert_oracle(test, actual, outgoing, seeds, depth=5, decay=.9):
    """Compare all strongest scores and shortest optimal depths. Tied chain
    provenance may differ, but every hop, condition and score must be real.
    """
    expected = exhaustive(outgoing, seeds, depth, decay)
    test.assertEqual(set(actual), set(expected), "oracle target set")
    for target, item in actual.items():
        c = item["chain"]
        test.assertEqual((item["score"], item["depth"]),
                         (expected[target]["score"], expected[target]["depth"]), "oracle strongest score/depth")
        test.assertEqual(c["nodes"][0], c["start"])
        test.assertEqual(c["nodes"][-1], target)
        test.assertEqual(len(set(c["nodes"])), len(c["nodes"]), "oracle simple path")
        test.assertEqual(c["depth"], len(c["hops"]))
        product = 1.0
        for i, h in enumerate(c["hops"]):
            test.assertEqual((h["from"], h["to"]), tuple(c["nodes"][i:i + 2]))
            matches = [e for e in outgoing.get(h["from"], [])
                       if e["target"] == h["to"] and chain.edge_rel(e) == h["relation_type"]
                       and chain.edge_weight(e) == h["weight"]
                       and (chain.edge_condition(e) or ("seed fallback" if i == 0 else "")) == h["condition"]]
            test.assertTrue(matches, "oracle authentic edge and condition")
            product *= h["weight"]
        test.assertEqual(c["conditions"], [h["condition"] for h in c["hops"]])
        test.assertEqual(item["conditions"], c["conditions"])
        test.assertEqual(c["weight"], round(product, 6), "oracle cumulative rounding")
        test.assertEqual(item["score"], round(seeds[c["start"]] * round(product, 6) * decay**c["depth"], 6))


def body(title):
    return (f"# 功能名：{title}\n# 生效条件：合成实验\n# 子功能：链检索\n"
            f"# 执行：读取\n# 验证方式：机械对拍\n# 不适用条件：真实部署\n{title}\n")


def populate(cg, outgoing):
    for nid, es in outgoing.items():
        cg.add(nid, body("anchoronlyneedle" if nid == "seed" else nid),
               edges=es, importance=.4)
    cg.flush()


class ChainGuards(unittest.TestCase):
    def test_strong_target_default_budget(self):
        result = chain.expand_from_seeds(Graph(converging_graph()), {"seed": 1.0})
        self.assertTrue("strong_target" in result, "strong_target starved by weak DFS branch")
        self.assertEqual(result["strong_target"]["score"], .585225, "strong chain score")
        self.assertEqual(result["strong_target"]["chain"]["nodes"],
                         ["seed", "strong_a", "strong_target"], "strong chain provenance")

    def test_convergence_work_and_order(self):
        results = []
        for reverse in (False, True):
            stats = {}
            results.append(chain.expand_from_seeds(Graph(converging_graph(reverse=reverse)),
                                                   {"seed": 1}, stats=stats))
            self.assertTrue(stats["complete"], "28-node converging graph must complete")
            self.assertLessEqual(stats["expanded"], 28, "duplicate path expansion bound")
            self.assertLessEqual(stats["edges_scanned"], 117, "unique converging edges")
            self.assertLessEqual(stats["seeds"][0]["enqueued"], 28, "duplicate label queue bound")
        self.assertEqual(results[0], results[1], "edge order must not change complete results")

    def test_priority_under_truncation(self):
        graph = {"seed": [edge("strong_a"), edge("weak_root", .01)],
                 "strong_a": [edge("strong_target")], "strong_target": [],
                 "weak_root": [edge(f"leaf{i:04}") for i in range(1000)]}
        stats = {}
        result = chain.expand_from_seeds(Graph(graph), {"seed": 1}, stats=stats)
        self.assertTrue("strong_target" in result, "priority must preserve strong target under budget")
        self.assertFalse(stats["complete"], "wide graph must disclose truncated search")
        self.assertLessEqual(stats["expanded"], 500, "node budget unchanged")
        self.assertLessEqual(len(result), 500, "per-seed output cap unchanged")

    def test_shallow_weaker_prefix(self):
        graph = {"s": [edge("a"), edge("weak", .01)], "a": [edge("b")],
                 "b": [edge("x")], "weak": [edge("x")],
                 "x": [edge("u")], "u": [edge("v")], "v": []}
        result = chain.expand_from_seeds(Graph(graph), {"s": 1}, max_depth=4)
        self.assertTrue("v" in result, "shallow weak prefix must retain remaining depth")
        self.assertEqual(result["v"]["chain"]["nodes"], ["s", "weak", "x", "u", "v"], "depth Pareto path")
        self.assertEqual(result, exhaustive(graph, {"s": 1}, depth=4))

    def test_multiple_seeds_and_decay(self):
        graph = {"s": [edge("x", .5)], "t": [edge("x"), edge("s")],
                 "x": [edge("u")], "u": []}
        result = chain.expand_from_seeds(Graph(graph), {"s": 5, "t": .5}, decay=.7)
        self.assertEqual(result, exhaustive(graph, {"s": 5, "t": .5}, decay=.7),
                         "seed scaling, decay and reaching another seed")
        self.assertNotEqual(result["x"]["score"], result["u"]["score"])

    def test_cycles_zero_weights_and_scores(self):
        graph = {"s": [edge("s"), edge("a", 0), edge("b")],
                 "a": [edge("b"), edge("u")], "b": [edge("a"), edge("s")], "u": []}
        for score, decay in ((1, .9), (0, .9), (1, 0), (1, 1)):
            with self.subTest(score=score, decay=decay):
                result = chain.expand_from_seeds(Graph(graph), {"s": score}, decay=decay)
                self.assertEqual(result, exhaustive(graph, {"s": score}, decay=decay), "cycle/zero oracle")
                for item in result.values():
                    nodes = item["chain"]["nodes"]
                    self.assertEqual(len(nodes), len(set(nodes)), "simple-path invariant")

    def test_zero_suffix_tied_provenance(self):
        graph = {"s": [edge("a", .1), edge("b")], "a": [edge("x")],
                 "b": [edge("x")], "x": [edge("u", 0)], "u": []}
        first = chain.expand_from_seeds(Graph(graph), {"s": 1})
        assert_oracle(self, first, graph, {"s": 1})
        for es in graph.values():
            es.reverse()
        self.assertEqual(first, chain.expand_from_seeds(Graph(graph), {"s": 1}),
                         "zero-suffix ties retain deterministic authentic provenance")

    def test_round_only_final_product(self):
        graph = {"s": [edge("a", .123456)], "a": [edge("b", .123456)],
                 "b": [edge("u", .333333)], "u": []}
        assert_oracle(self, chain.expand_from_seeds(Graph(graph), {"s": 7}), graph, {"s": 7})

    def test_conditions_and_relation_filter(self):
        graph = {"s": [edge("a", condition=""), edge("x", relation="similar")],
                 "a": [edge("u", condition="downstream condition")], "u": [], "x": []}
        result = chain.expand_from_seeds(Graph(graph), {"s": 1})
        self.assertNotIn("x", result, "default relation filter")
        self.assertEqual(result["u"]["conditions"], ["seed fallback", "downstream condition"],
                         "first-hop condition fallback and downstream provenance")
        self.assertIn("x", chain.expand_from_seeds(Graph(graph), {"s": 1}, relation_types=None))

    def test_hierarchy_and_read_gates(self):
        graph = Graph({"s": [edge("hidden"), edge("archived"), edge("public")],
                       "hidden": [edge("leak")], "archived": [edge("leak")],
                       "public": [], "leak": [], "child": []})
        graph.index["nodes"]["archived"]["lifecycle_state"] = "archived"
        graph.index["nodes"]["s"]["subgraph"] = {"nodes": ["child"]}
        graph._chain_visible = lambda nid: nid != "hidden"
        result = chain.expand_from_seeds(graph, {"s": 1}, relation_types=None)
        self.assertEqual(set(result), {"public", "child"}, "visibility, archive and hierarchy gates")
        result = chain.expand_from_seeds(graph, {"s": 1}, relation_types=None, include_hierarchy=False)
        self.assertEqual(set(result), {"public"}, "hierarchy flag")

    def test_depth_and_budget_edges(self):
        outgoing = {f"n{i}": [edge(f"n{i + 1}")] for i in range(70)}
        graph = Graph(outgoing)
        for depth in (0, -1):
            self.assertEqual(len(chain.expand_from_seeds(graph, {"n0": 1}, max_depth=depth)), 0, "zero depth")
        result = chain.expand_from_seeds(graph, {"n0": 1}, max_depth=1000)
        self.assertIn("n64", result, "hard depth cap includes boundary")
        self.assertNotIn("n65", result, "hard depth cap rejects next node")
        self.assertIn("n70", chain.expand_from_seeds(graph, {"n0": 1}, max_depth=None), "natural end")
        for kwargs in ({"max_nodes": 0}, {"max_chains": 0}):
            self.assertEqual(chain.expand_from_seeds(graph, {"n0": 1}, **kwargs), {}, "zero budget")
        stats = {}
        result = chain.expand_from_seeds(graph, {"n0": 1}, max_nodes=1, stats=stats)
        self.assertEqual(set(result), {"n1"}, "root may expose direct neighbors")
        self.assertFalse(stats["complete"], "one node budget is incomplete")

    def test_legacy_numeric_fallback(self):
        graph = Graph({"s": [edge("a")], "a": [edge("u")], "u": []})
        for seeds, kwargs in (({"s": -2}, {}), ({"s": 1}, {"decay": 1.1}),
                              ({"s": 1}, {"decay": -.5}), ({"s": 1}, {"max_nodes": 2.0})):
            stats = {}
            actual = chain.expand_from_seeds(graph, seeds, stats=stats, **kwargs)
            self.assertEqual(actual, chain._expand_legacy(graph, seeds, **kwargs), "legacy numeric parity")
            self.assertEqual(stats["algorithm"], "legacy_fallback", "nonmonotone input fallback")
        self.assertEqual(chain.expand_from_seeds(graph, [("s", "bad"), ("", 1)]), {}, "invalid seed skip")

    def test_seeded_exhaustive_oracle(self):
        rng = random.Random(680013)
        for case in range(600):
            ids = [f"n{i}" for i in range(6)]
            graph = {a: [edge(b, rng.choice([0, .01, .2, .5, .999999, 1]),
                              rng.choice(["causal", "sequential", "applies_to", "similar"]))
                         for b in ids if rng.random() < .38] for a in ids}
            seeds = {"n0": rng.choice([0, .1, 1, 3]), "n1": rng.choice([0, .5, 2])}
            depth, decay = rng.choice([1, 2, 3, 4, 5]), rng.choice([0, .7, .9, 1])
            with self.subTest(case=case):
                actual = chain.expand_from_seeds(Graph(graph), seeds, max_depth=depth, decay=decay,
                                                 max_nodes=10000, max_chains=10000)
                assert_oracle(self, actual, graph, seeds, depth, decay)

    def test_native_markdown_default_rrf(self):
        from .mdcos import MdCGOS
        with tempfile.TemporaryDirectory(prefix="chain_best_first_") as tmp:
            with mock.patch.dict(os.environ, {"MDCG_HOTCACHE": "0", "MDCG_SUSTAIN": "0",
                                              "MDCG_SEMANTIC": "0", "MDCG_EN_ATOMS": "0",
                                              "MDCG_RRF_CANDIDATES": "0", "MDCG_RETRIEVAL_PIPELINE": "0"}):
                cg = MdCGOS(str(Path(tmp) / "graph"))
                try:
                    populate(cg, converging_graph())
                    self.assertEqual(len(cg.index["nodes"]), 28, "real native fixture size")
                    for reverse in (False, True):
                        if reverse:
                            cg.add("seed", body("anchoronlyneedle"),
                                   edges=converging_graph(reverse=True)["seed"],
                                   importance=.4, override=True)
                            cg.flush()
                        rows, meta = cg.search_rrf("anchoronlyneedle", k=20, judge=False, record=False)
                        self.assertIn("strong_target", [n["id"] for n, *_rest in rows],
                                      "default production RRF must recall strong_target")
                        self.assertEqual(meta["paths"]["chain"], 27, "default chain route count")
                finally:
                    cg.close()


def run_suite(names=None, verbosity=2):
    suite = (unittest.defaultTestLoader.loadTestsFromTestCase(ChainGuards) if names is None else
             unittest.TestSuite(ChainGuards(name) for name in names))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=verbosity).run(suite)
    return result, stream.getvalue()


def mutation_proof():
    """One production edit per mutant, in memory. Only a named assertion
    failure kills it; errors/skips/import failures never count as a kill.
    The actual chain.py bytes are checked unchanged and restored guards run.
    """
    source_path = Path(chain.__file__)
    original_bytes = source_path.read_bytes()
    source = original_bytes.decode("utf-8")
    mutations = [
        ("legacy_dfs", "    report = {\"algorithm\": \"depth_pareto_best_first\" if safe",
         "    safe = False\n    report = {\"algorithm\": \"depth_pareto_best_first\" if safe",
         "test_strong_target_default_budget", "strong_target starved"),
        ("weakest_first", "heapq.heappush(queue, (-upper,", "heapq.heappush(queue, (upper,",
         "test_priority_under_truncation", "priority must preserve strong target"),
        ("no_dominance", "for old in frontier.values():", "for old in ():",
         "test_convergence_work_and_order", "duplicate label queue bound"),
        ("ignore_depth_in_dominance", "if old[1] <= depth and old[2] >= weight:", "if old[2] >= weight:",
         "test_shallow_weaker_prefix", "shallow weak prefix must retain remaining depth"),
        ("omit_seed_score", "score = s0 * rounded_weight * (decay ** depth)",
         "score = rounded_weight * (decay ** depth)",
         "test_multiple_seeds_and_decay", "seed scaling, decay"),
        ("omit_decay", "score = s0 * rounded_weight * (decay ** depth)",
         "score = s0 * rounded_weight",
         "test_multiple_seeds_and_decay", "seed scaling, decay"),
        ("ignore_relation_filter", "if (rels and rel not in rels) or tgt in nodes:", "if tgt in nodes:",
         "test_conditions_and_relation_filter", "default relation filter"),
        ("ignore_depth_limit", "if depth_limit is not None and depth >= depth_limit:", "if False:",
         "test_depth_and_budget_edges", "zero depth"),
        ("erase_conditions", "condition = edge_condition(edge)", "condition = \"\"",
         "test_conditions_and_relation_filter", "downstream provenance"),
    ]
    before, before_log = run_suite(verbosity=1)
    if not before.wasSuccessful() or before.skipped:
        return {"passed": 0, "failed": 1, "precondition": before_log, "mutants": []}
    rows = []
    for name, old, new, guard, assertion in mutations:
        if source.count(old) != 1:
            raise AssertionError(f"mutation {name}: source anchor must occur exactly once")
        mod = types.ModuleType("md_cg._chain_mutant")
        mod.__package__ = "md_cg"
        mod.__file__ = str(source_path)
        exec(compile(source.replace(old, new, 1), str(source_path), "exec"), mod.__dict__)
        with mock.patch.object(chain, "expand_from_seeds", mod.expand_from_seeds):
            result, log = run_suite([guard], verbosity=1)
        killed = bool(result.failures) and not result.errors and not result.skipped and assertion in log
        rows.append({"mutation": name, "guard": guard, "expected_assertion": assertion,
                     "killed_by_named_assertion": killed, "errors": len(result.errors),
                     "skipped": len(result.skipped), "log": log})
        print(f"{'KILLED' if killed else 'SURVIVED'} {name} -> {guard}: {assertion}")
    after, after_log = run_suite(verbosity=1)
    unchanged = source_path.read_bytes() == original_bytes
    restored = after.wasSuccessful() and not after.skipped and unchanged
    passed = sum(row["killed_by_named_assertion"] for row in rows)
    return {"passed": passed, "failed": len(rows) - passed + int(not restored),
            "mutants": rows, "source_sha256": hashlib.sha256(original_bytes).hexdigest(),
            "source_unchanged": unchanged, "restored_passed": restored,
            "restored_tests": after.testsRun, "restored_log": after_log}


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mutate", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.mutate:
        report = mutation_proof()
        if args.output:
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"通过 {report['passed']} / 失败 {report['failed']}")
        return int(report["failed"] != 0)
    result, log = run_suite()
    print(log, end="")
    failed = len({test.id().split(" (")[0] for test, _trace in result.failures + result.errors})
    report = {"tests": result.testsRun, "passed": result.testsRun - failed - len(result.skipped),
              "failed": failed, "failure_assertions": len(result.failures),
              "errors": len(result.errors), "skipped": len(result.skipped), "log": log}
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"通过 {report['passed']} / 失败 {failed}")
    return int(failed != 0 or bool(result.skipped))


def main(argv=None):
    with tempfile.TemporaryDirectory(prefix="chain_guard_env_") as temp:
        with mock.patch.dict(os.environ, {
            "MDCG_ROOT": str(Path(temp) / "unused"),
            "MDCG_AUX_ROOT": str(Path(temp) / "auxiliary"),
            "MDCG_DATA_ROOT": str(Path(temp) / "data"),
            "DSH_HOME": str(Path(temp) / "dsh"), "MDCG_MASTER_KEY": "ab" * 32,
            "MDCG_CHAIN_TYPES": "", "MDCG_HOTCACHE": "0", "MDCG_SUSTAIN": "0",
        }):
            return _main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
