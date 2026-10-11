# -*- coding: utf-8 -*-
"""Runtime guards for bounded query coverage, defaults and cache isolation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from . import hotcache, mdcg, mdcos, query_coverage

FLAG = "MDCG_CN_GRAMS_COVERAGE"
PREFIX = "查询当前季度项目研发计划以及各个部门资源协调落实进展和阶段预算分配情况"
TARGET = "晶格退火温度曲线"
QUERY = PREFIX + "\n特别需要了解" + TARGET + "在恒定压力下的实验参数如何设置"


def fixture_cases():
    data = Path(__file__).with_name("query_coverage_cases.tsv").read_text(encoding="utf-8")
    for line in data.splitlines():
        if not line or line.startswith("#"):
            continue
        name, query, min_run, cap, expected = line.split("\t")
        yield name, query.replace("\\n", "\n"), int(min_run), int(cap), (
            [] if expected == "-" else expected.split("|"))


class QueryCoverage(unittest.TestCase):
    def setUp(self):
        clean = {k: v for k, v in os.environ.items() if not k.startswith("MDCG_")}
        clean.update({"MDCG_CN_GRAMS": "1", "MDCG_HOTCACHE": "0",
                      "MDCG_UNIFY_QUERY": "0", "MDCG_RRF_CANDIDATES": "0"})
        self.env = patch.dict(os.environ, clean, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def make_store(self, cls=mdcos.MdCGOS, fillers=30):
        temp = tempfile.TemporaryDirectory(prefix="query_coverage_")
        self.addCleanup(temp.cleanup)
        cg = cls(temp.name)
        self.addCleanup(cg.close)
        for i in range(fillers):
            cg.add(f"filler{i:04d}", "当前季度", importance=0.5, role="knowledge")
        cg.add("gold", TARGET, importance=0.5, role="knowledge", session="mine")
        cg.flush()
        return cg

    def search(self, cg, rrf=False, **kwargs):
        options = dict(k=10, judge=False, record=False)
        options.update(kwargs)
        if rrf:
            return cg.search_rrf(QUERY, paths=("lexical",), **options)
        return cg.search(QUERY, include_neg=False, **options)

    def test_shared_golden_cases(self):
        cases = list(fixture_cases())
        self.assertEqual(len(cases), 15)
        for name, query, min_run, cap, expected in cases:
            with self.subTest(name=name), patch.dict(os.environ, {FLAG: "1"}):
                self.assertEqual(mdcg.cn_recall_grams(query, min_run, cap), expected)

    def test_default_and_non_one_values_keep_prefix(self):
        expected = ['查询', '询当', '当前', '前季', '季度', '度项', '项目', '目研',
                    '研发', '发计', '计划', '划以', '以及', '及各', '各个', '个部']
        for value in (None, "0", "true", ""):
            with self.subTest(value=value):
                if value is None:
                    os.environ.pop(FLAG, None)
                else:
                    os.environ[FLAG] = value
                self.assertEqual(mdcg.cn_recall_grams(QUERY), expected)

    def test_master_switch_and_nonpositive_cap(self):
        with patch.dict(os.environ, {FLAG: "1", "MDCG_CN_GRAMS": "0"}):
            self.assertEqual(mdcg.cn_recall_grams(QUERY), [])
        with patch.dict(os.environ, {FLAG: "1"}):
            self.assertEqual(mdcg.cn_recall_grams(QUERY, cap=-1), ["查询"])
            self.assertEqual(mdcg.cn_recall_grams(QUERY, cap=0), ["查询"])

    def test_short_queries_unchanged(self):
        for query in ("记忆检索引擎", "这个不是我们的实验", "abc API 记忆搜索", "甲乙", ""):
            with patch.dict(os.environ, {FLAG: "0"}):
                old = mdcg.cn_recall_grams(query)
            with patch.dict(os.environ, {FLAG: "1"}):
                self.assertEqual(mdcg.cn_recall_grams(query), old)

    def test_budget_membership_and_determinism(self):
        rng = random.Random(20261011)
        for _ in range(120):
            query = " ".join("".join(rng.choices("甲乙丙丁戊己庚辛壬癸天地玄黄", k=rng.randrange(2, 40)))
                             for _ in range(rng.randrange(1, 25)))
            cap = rng.randrange(1, 25)
            with patch.dict(os.environ, {FLAG: "1"}):
                actual = mdcg.cn_recall_grams(query, cap=cap)
                self.assertEqual(actual, mdcg.cn_recall_grams(query, cap=cap))
            eligible = {run[i:i + 2] for run in re.findall(r"[\u4e00-\u9fff]{4,}", query)
                        for i in range(len(run) - 1)} - mdcg.CN_STOP_GRAMS
            self.assertEqual(len(actual), min(cap, len(eligible)))
            self.assertEqual(len(set(actual)), len(actual))
            self.assertTrue(set(actual) <= eligible)

    def test_both_query_ends_get_keys(self):
        with patch.dict(os.environ, {FLAG: "1"}):
            grams = mdcg.cn_recall_grams(QUERY)
        self.assertEqual(len(grams), 16)
        self.assertIn("查询", grams)
        self.assertIn("情况", grams)
        self.assertIn("特别", grams)
        self.assertIn("设置", grams)
        self.assertTrue(any(g in TARGET for g in grams))

    def test_base_and_production_search_recall_tail(self):
        for cls in (mdcg.MdCG, mdcos.MdCGOS):
            cg = self.make_store(cls)
            with patch.dict(os.environ, {FLAG: "0"}):
                old, _ = self.search(cg)
            self.assertNotIn("gold", [r[0]["id"] for r in old])
            with patch.dict(os.environ, {FLAG: "1"}):
                new, meta = self.search(cg)
            self.assertEqual(new[0][0]["id"], "gold")
            self.assertEqual(meta["tier"], mdcg.TIER_GLOBAL_LIKE)

    def test_large_pool_candidate_accelerator_and_session_filter(self):
        cg = self.make_store(fillers=701)
        cg.add("hidden", TARGET + "额外线索", role="knowledge", session="other")
        for accelerate in ("0", "1"):
            with patch.dict(os.environ, {FLAG: "1", "MDCG_RRF_CANDIDATES": accelerate}):
                new, _ = self.search(cg, rrf=True)
                self.assertEqual(new[0][0]["id"], "gold")
                scoped, _ = self.search(cg, rrf=True, session="mine")
                self.assertEqual(scoped[0][0]["id"], "gold")
                self.assertNotIn("hidden", [r[0]["id"] for r in scoped])
        with patch.dict(os.environ, {FLAG: "0"}):
            old, _ = self.search(cg, rrf=True)
        self.assertNotIn("gold", [r[0]["id"] for r in old])

    def test_hotcache_flip_matches_uncached_result(self):
        with patch.dict(os.environ, {FLAG: "0", "MDCG_HOTCACHE": "1"}):
            cg = self.make_store()
            old, meta = self.search(cg, rrf=True)
            again, cached = self.search(cg, rrf=True)
            self.assertEqual(again, old)
            self.assertTrue(cached.get("cached"))
            before = hotcache.env_switch_key()
            os.environ[FLAG] = "1"
            self.assertNotEqual(before, hotcache.env_switch_key())
            new, changed = self.search(cg, rrf=True)
            self.assertFalse(changed.get("cached"))
            self.assertEqual(new[0][0]["id"], "gold")
            repeated, cached = self.search(cg, rrf=True)
            self.assertEqual(repeated, new)
            self.assertTrue(cached.get("cached"))
            os.environ["MDCG_HOTCACHE"] = "0"
            fresh, _ = self.search(cg, rrf=True)
            self.assertEqual(fresh, new)
            os.environ[FLAG] = "0"
            restored, _ = self.search(cg, rrf=True)
            self.assertEqual(restored, old)

    def test_mcp_stdio_search_both_modes(self):
        cg = self.make_store()
        root = cg.root
        cg.close()
        messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                     "params": {"name": "mdcg_search", "arguments": {"query": QUERY, "k": 10}}},
                    {"jsonrpc": "2.0", "id": 3, "method": "shutdown"}]
        for mode in ("0", "1"):
            env = dict(os.environ, MDCG_ROOT=str(root), MDCG_LEGACY_ENV_AUTH="1",
                       MDCG_ACTOR="coverage-test", MDCG_AUX_ROOT=str(Path(root) / "sidecar"))
            env[FLAG] = mode
            proc = subprocess.run([sys.executable, "-X", "utf8", "-m", "md_cg.mcp_server"],
                                  input="\n".join(json.dumps(m, ensure_ascii=False) for m in messages) + "\n",
                                  capture_output=True, encoding="utf-8", env=env, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            reply = next(json.loads(line) for line in proc.stdout.splitlines()
                         if json.loads(line).get("id") == 2)
            result = json.loads(reply["result"]["content"][0]["text"])
            ids = [r["node"]["id"] for r in result["results"]]
            self.assertEqual("gold" in ids, mode == "1")


if __name__ == "__main__":
    unittest.main()
