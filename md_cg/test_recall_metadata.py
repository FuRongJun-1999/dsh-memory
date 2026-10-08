# -*- coding: utf-8 -*-
"""Recall 核心可靠性元数据：两种取数路径及原装包契约回归。

固定检索结果只隔离取数，实际执行 MdCGOS.recall 的组装与预算逻辑。
历史缺字段夹具不经 add，避免写入默认值遮掉缺失信息的分支。
真实 stdio MCP 返回面的断言另在 test_p2_mcp 中覆盖。
运行：python -m md_cg.test_recall_metadata
"""
from __future__ import annotations

import copy
import tempfile
import unittest
from unittest.mock import patch

from .mdcos import MdCGOS, est_tokens


class RecallMetadataTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory(prefix="mdcg_recall_metadata_")
        self.addCleanup(root.cleanup)
        self.cg = MdCGOS(root.name)
        self.addCleanup(self.cg.close)

    @staticmethod
    def row(nid, content, fm=None, state="ACCEPT", score=0.75,
            reason="本次查询条件满足"):
        return ({"id": nid, "content": content, "frontmatter": fm},
                score, {"state": state, "reason": reason},
                [{"path": "lexical", "rank": 1, "score": score}])

    def recall(self, rows, use_rrf=True, **kw):
        meta = {"tier": "test_fixture", "paths": {"lexical": len(rows)}}
        args = {"budget_tokens": 10000, "max_item_tokens": 0, **kw}
        with patch.object(self.cg, "search_rrf", return_value=(rows, meta)) as rrf, \
                patch.object(self.cg, "search",
                             return_value=([r[:3] for r in rows], meta)) as search:
            out = self.cg.recall("查询", use_rrf=use_rrf, **args)
        self.assertEqual(rrf.call_count, int(use_rrf))
        self.assertEqual(search.call_count, int(not use_rrf))
        self.assertEqual(out["meta"], meta)
        return out

    def test_metadata_uses_existing_fields_without_changing_results(self):
        fm = {"verification_state": "doubted", "verification_basis": "data",
              "check_strength": "hoop", "derived_from": ["parent"],
              "derived_relation": "extracted_from", "source": "session:fact",
              "confidence": 0.85, "audit": [{"internal": True}],
              "verification_history": [{"to": "doubted"}],
              "evidence_log": [{"verdict": "weakened"}],
              "state_history": [{"to": "active"}],
              "provenance": [{"path": "internal_debug"}]}
        rows = [self.row("z_first", "记忆正文 A", fm, score=0.4),
                self.row("a_second", "记忆正文 B", {}, state="DEFER", score=0.9,
                         reason="未声明验证基底")]
        snapshot = copy.deepcopy(rows)
        expected = {"state": "ACCEPT", "reason": "本次查询条件满足",
                    "verification_state": "doubted", "verification_basis": "data",
                    "check_strength": "hoop", "derived_from": ["parent"],
                    "derived_relation": "extracted_from", "source": "session:fact"}
        for use_rrf in (True, False):
            with self.subTest(use_rrf=use_rrf):
                out = self.recall(rows, use_rrf)
                self.assertEqual([p["id"] for p in out["pack"]],
                                 ["z_first", "a_second"])
                for entry, row in zip(out["pack"], rows):
                    node, score, qual, prov = row
                    old_fields = {"id": node["id"], "content": node["content"],
                                  "score": score, "state": qual["state"],
                                  "tokens": est_tokens(node["content"]),
                                  "frontmatter": node["frontmatter"],
                                  "provenance": prov if use_rrf else []}
                    self.assertEqual({k: entry[k] for k in old_fields}, old_fields)
                    self.assertNotIn("truncated", entry)
                self.assertEqual(out["pack"][0]["metadata"], expected)
                self.assertEqual(out["tokens_used"],
                                 sum(est_tokens(r[0]["content"]) for r in rows))
                self.assertEqual(out["skipped"], [])
                self.assertEqual(out["recent"], [])
                # 查到适用候选仍可处于存疑态，两种状态不可互相覆写。
                self.assertEqual(out["pack"][0]["state"], "ACCEPT")
                self.assertEqual(out["pack"][0]["metadata"]["verification_state"],
                                 "doubted")
        self.assertEqual(rows, snapshot, "组装输出不得改写节点或检索结果")

    def test_missing_and_null_fields_do_not_invent_evidence(self):
        fm = {k: None for k in ("verification_basis", "check_strength",
                               "derived_from", "derived_relation", "source")}
        rows = [self.row("legacy", "历史原文", None, state="DEFER",
                         reason="legacy 记忆"),
                self.row("null_fields", "未声明证据", fm, state="DEFER")]
        for use_rrf in (True, False):
            with self.subTest(use_rrf=use_rrf):
                out = self.recall(rows, use_rrf)
                for entry, row in zip(out["pack"], rows):
                    self.assertEqual(entry["content"], row[0]["content"])
                    self.assertEqual(entry["metadata"], {
                        "state": row[2]["state"], "reason": row[2]["reason"],
                        "verification_state": "unverified"})
                    self.assertNotIn("confidence", entry["metadata"])

    def test_declared_falsy_values_are_not_treated_as_missing(self):
        fm = {"verification_state": "verified", "verification_basis": "data",
              "check_strength": None, "derived_from": [],
              "derived_relation": "", "source": 0}
        for use_rrf in (True, False):
            with self.subTest(use_rrf=use_rrf):
                entry = self.recall([self.row("declared", "原文", fm)],
                                    use_rrf)["pack"][0]
                self.assertEqual(entry["metadata"], {
                    "state": "ACCEPT", "reason": "本次查询条件满足",
                    "verification_state": "verified", "verification_basis": "data",
                    "derived_from": [], "derived_relation": "", "source": 0})

    def test_unknown_verification_state_uses_existing_unverified_semantics(self):
        entry = self.recall([self.row("unknown", "原文",
                                     {"verification_state": "not_a_state"})])["pack"][0]
        self.assertEqual(entry["metadata"]["verification_state"], "unverified")
        self.assertEqual(entry["frontmatter"]["verification_state"], "not_a_state")

    def test_disabled_judgement_does_not_invent_qualification(self):
        row = self.row("no_judge", "原文", {}, state=None, reason="judge_disabled")
        entry = self.recall([row], judge=False)["pack"][0]
        self.assertIsNone(entry["state"])
        self.assertIsNone(entry["metadata"]["state"])
        self.assertEqual(entry["metadata"]["reason"], "judge_disabled")

    def test_disabled_truncation_skips_oversize_and_keeps_later_small_memory(self):
        rows = [self.row("large", "记忆" * 120, {"source": "archive"}),
                self.row("small", "短", {}, state="DEFER", score=0.1)]
        for use_rrf in (True, False):
            with self.subTest(use_rrf=use_rrf):
                out = self.recall(rows, use_rrf, budget_tokens=2, max_item_tokens=0)
                self.assertEqual([p["id"] for p in out["pack"]], ["small"])
                self.assertEqual(out["pack"][0]["content"], "短")
                self.assertEqual(out["pack"][0]["metadata"]["state"], "DEFER")
                self.assertEqual(out["skipped"], [{"id": "large",
                                 "tokens": est_tokens(rows[0][0]["content"]),
                                 "reason": "oversize_or_over_budget"}])
                self.assertEqual(out["tokens_used"], est_tokens("短"))

    def test_excerpt_preserves_identity_status_order_and_token_budget(self):
        fm = {"verification_state": "doubted", "verification_basis": "data",
              "source": "原始来源" * 1000}
        rows = [self.row("large", "记忆正文" * 120, fm, score=0.2),
                self.row("small", "短", {}, score=0.8)]
        snapshot = copy.deepcopy(rows)
        for use_rrf in (True, False):
            with self.subTest(use_rrf=use_rrf):
                out = self.recall(rows, use_rrf, budget_tokens=20, max_item_tokens=12)
                self.assertEqual([p["id"] for p in out["pack"]], ["large", "small"])
                large, small = out["pack"]
                self.assertTrue(large["truncated"])
                self.assertNotEqual(large["content"], rows[0][0]["content"])
                self.assertTrue(large["content"].endswith("…"))
                self.assertTrue(rows[0][0]["content"].startswith(large["content"][:-1]))
                self.assertLessEqual(large["tokens"], 12)
                self.assertEqual(large["score"], 0.2)
                self.assertEqual(large["metadata"]["source"], fm["source"])
                self.assertEqual(large["metadata"]["verification_state"], "doubted")
                self.assertEqual(small["content"], "短")
                self.assertNotIn("truncated", small)
                self.assertEqual(out["tokens_used"],
                                 sum(est_tokens(p["content"]) for p in out["pack"]))
                self.assertLessEqual(out["tokens_used"], out["budget"])
                self.assertEqual(out["skipped"], [])
        self.assertEqual(rows, snapshot)

    def test_zero_budget_and_recent_events_keep_existing_accounting(self):
        row = self.row("memory", "abcd", {"source": "来源" * 1000})
        out = self.recall([row], budget_tokens=0)
        self.assertEqual(out["pack"], [])
        self.assertEqual(out["tokens_used"], 0)
        self.assertEqual(out["budget"], 0)
        events = [{"role": "user", "t": 1, "text": "x" * 16},
                  {"role": "user", "t": 2, "text": "efgh"}]
        with patch.object(self.cg, "recent_events", return_value=events):
            out = self.recall([row], budget_tokens=5, include_recent=True)
        self.assertEqual([e["text"] for e in out["recent"]], ["efgh"])
        self.assertEqual(out["tokens_used"], est_tokens("abcd") + est_tokens("efgh"))
        self.assertLessEqual(out["tokens_used"], out["budget"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
