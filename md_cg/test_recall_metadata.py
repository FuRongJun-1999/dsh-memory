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




# ===================== DSH 端增补（2026-10-09）=====================
# 以下为落地 issue #76 时新增，**不改动上方任何原用例与断言**：
#   ① 声明一致性断言——把 protocol.py 的条目级登记从「注释」变成**可执行判据**
#      （zcode 指明的前置：登记 read.pack 的条目级新字段；只写注释不算登记，
#       因为注释不会红。此处让「声明」与「实际装包」逐项对账）。
#   ② 定点变异自证开关（照 md_cg/test_w7_redlines.py 范式；原 PR 未带）。
import contextlib
import inspect
import io
import sys

from . import mdcos as _mdcos
from . import nodefile, protocol, trust


class RecallMetadataDeclarationTests(unittest.TestCase):
    """protocol.py read.pack 的条目级声明须与实际装包逐项一致（issue #76 前置）。"""

    def setUp(self):
        root = tempfile.TemporaryDirectory(prefix="mdcg_recall_decl_")
        self.addCleanup(root.cleanup)
        self.cg = MdCGOS(root.name)
        self.addCleanup(self.cg.close)

    def _shape(self):
        return protocol.VERB_SPECS["read"]["shapes"]["pack"]

    def _entry(self):
        fm = {trust.STATE_FIELD: "doubted", "verification_basis": "data",
              nodefile.CHECK_STRENGTH_FIELD: "hoop", "derived_from": ["p"],
              "derived_relation": "extracted_from", "source": "session:x"}
        row = ({"id": "m1", "content": "正文", "frontmatter": fm},
               0.5, {"state": "ACCEPT", "reason": "本次查询条件满足"},
               [{"path": "lexical", "rank": 1, "score": 0.5}])
        with patch.object(self.cg, "search_rrf",
                          return_value=([row], {"tier": "t", "paths": {}})):
            out = self.cg.recall("查询", budget_tokens=1000, max_item_tokens=0)
        return out["pack"][0]

    def test_entry_level_declaration_matches_actual_pack(self):
        sh = self._shape()
        e = self._entry()
        req = set(sh.get("entry_required") or ())
        opt = set(sh.get("entry_optional") or ())
        self.assertTrue(req, "protocol.py 未登记 pack 条目级字段（entry_required）")
        self.assertEqual(set(e) - opt, req,
                         "条目级键与声明不符：实际 %s / 声明必含 %s / 声明可选 %s"
                         % (sorted(e), sorted(req), sorted(opt)))

    def test_metadata_declaration_matches_actual_metadata(self):
        sh = self._shape()
        md = self._entry().get("metadata")
        self.assertIsInstance(md, dict, "装包条目缺 metadata")
        req = set(sh.get("entry_metadata_required") or ())
        opt = set(sh.get("entry_metadata_optional") or ())
        self.assertTrue(req, "protocol.py 未登记 metadata 级字段")
        self.assertEqual(set(md) - opt, req,
                         "metadata 键与声明不符：实际 %s / 声明必含 %s / 声明可选 %s"
                         % (sorted(md), sorted(req), sorted(opt)))

    def test_declared_names_are_single_sourced(self):
        """声明里的字段名须与 trust/nodefile 的单点常量同源，不许另写一份字面量。"""
        sh = self._shape()
        self.assertIn(trust.STATE_FIELD, sh["entry_metadata_required"])
        self.assertIn(nodefile.CHECK_STRENGTH_FIELD, sh["entry_metadata_optional"])
        self.assertEqual(trust.STATE_FIELD, "verification_state")
        self.assertEqual(nodefile.CHECK_STRENGTH_FIELD, "check_strength")


_ALL_TESTS = (RecallMetadataTests, RecallMetadataDeclarationTests)


def _probe():
    """跑全部用例，返回红项集合（用例名）。"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([loader.loadTestsFromTestCase(c) for c in _ALL_TESTS])
    res = unittest.TestResult()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        suite.run(res)
    # 归一到**用例方法名**：subTest 失败时 id() 会带 "(use_rrf=False)" 之类后缀，
    # 直接当红项名会让期望集随夹具分支数漂移、无法稳定复现。
    return {t.id().split(".")[-1].split(" (")[0]
            for t, _ in list(res.failures) + list(res.errors)}


def _wrap_recall(fn):
    """对 recall 返回的 pack 逐条就地改写，模拟该层的退化。"""
    orig = MdCGOS.recall

    def _patched(self, *a, **kw):
        out = orig(self, *a, **kw)
        for e in (out or {}).get("pack") or []:
            fn(e)
        return out

    MdCGOS.recall = _patched
    return lambda: setattr(MdCGOS, "recall", orig)


def _mut_drop_metadata():
    """复现修前形态：装包条目不带 metadata。"""
    return _wrap_recall(lambda e: e.pop("metadata", None))


def _mut_keep_none():
    """透传时把 None 也算作「有值」（缺失/null 被带进摘要）。"""

    def f(e):
        md = e.get("metadata")
        if isinstance(md, dict):
            md.setdefault(nodefile.CHECK_STRENGTH_FIELD, None)
            md.setdefault("derived_from", None)

    return _wrap_recall(f)


def _mut_state_confused():
    """把「本次查询资格 state」当成「持久验证状态 verification_state」。"""

    def f(e):
        md = e.get("metadata")
        if isinstance(md, dict):
            md["verification_state"] = md.get("state")

    return _wrap_recall(f)


def _mut_state_of_always_verified():
    """把未知/缺失的验证状态推断成已确认（违反 unverified 默认）。"""
    orig = trust.state_of
    trust.state_of = lambda fm: "verified"
    return lambda: setattr(trust, "state_of", orig)


#: 期望红项集——**按实测填，不按推测填**（本端跑 --mutate 逐条量出后写回）。
#: 每条退化只允许命中自己的集合：多命中说明用例间耦合超出预期，少命中说明该面没被守住。
_RED_DROP_METADATA = {
    "test_declared_falsy_values_are_not_treated_as_missing",
    "test_disabled_judgement_does_not_invent_qualification",
    "test_disabled_truncation_skips_oversize_and_keeps_later_small_memory",
    "test_entry_level_declaration_matches_actual_pack",
    "test_excerpt_preserves_identity_status_order_and_token_budget",
    "test_metadata_declaration_matches_actual_metadata",
    "test_metadata_uses_existing_fields_without_changing_results",
    "test_missing_and_null_fields_do_not_invent_evidence",
    "test_unknown_verification_state_uses_existing_unverified_semantics",
}
_RED_KEEP_NONE = {
    "test_declared_falsy_values_are_not_treated_as_missing",
    "test_missing_and_null_fields_do_not_invent_evidence",
}
_RED_STATE_CONFUSED = {
    "test_declared_falsy_values_are_not_treated_as_missing",
    "test_excerpt_preserves_identity_status_order_and_token_budget",
    "test_metadata_uses_existing_fields_without_changing_results",
    "test_missing_and_null_fields_do_not_invent_evidence",
    "test_unknown_verification_state_uses_existing_unverified_semantics",
}
_RED_STATE_OF_VERIFIED = {
    "test_excerpt_preserves_identity_status_order_and_token_budget",
    "test_metadata_uses_existing_fields_without_changing_results",
    "test_missing_and_null_fields_do_not_invent_evidence",
    "test_unknown_verification_state_uses_existing_unverified_semantics",
}

#: 组 → [(变异名, 应用函数, 期望转红用例名集合)]
_MUTATIONS = {
    "A": [
        ("装包不带 metadata（复现修前形态）", _mut_drop_metadata, _RED_DROP_METADATA),
        ("透传时把 None 也算作有值", _mut_keep_none, _RED_KEEP_NONE),
        ("state 与 verification_state 混淆", _mut_state_confused, _RED_STATE_CONFUSED),
        ("未知验证状态推断成已确认", _mut_state_of_always_verified, _RED_STATE_OF_VERIFIED),
    ],
}

#: 源码锚点自检（命中次数必须恰为 1，否则实现已漂移、变异表失效）
_ANCHORS = [
    ("mdcos 装包处带 metadata 键", '"provenance": prov, "metadata": metadata}', _mdcos),
    ("protocol read.pack 已登记条目级字段", '"entry_metadata_required"', protocol),
    ("trust 验证状态单点", 'STATE_FIELD = "verification_state"', trust),
]


def _anchor_preflight():
    bad = []
    for label, anchor, mod in _ANCHORS:
        n = inspect.getsource(mod).count(anchor)
        if n != 1:
            bad.append((label, n))
    if not bad:
        return 0
    for label, n in bad:
        print("  ANCHOR-MISS %s：命中 %d 次（期望 1）" % (label, n))
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed）")
    return 2


def _mutate(name):
    if name not in _MUTATIONS:
        print("未知组名 %r（可选 %s）" % (name, sorted(_MUTATIONS)))
        return 1
    rc = _anchor_preflight()
    if rc:
        return rc
    print("!! #76 定点变异自证 · 组 %s：内存注入退化，逐条要求**恰好**命中期望\n" % name)
    base = _probe()
    print("  未变异基线：红项 %d %s" % (len(base), "（应为 0）" if not base else sorted(base)))
    bad = []
    if base:
        bad.append("基线即转红：%s" % sorted(base))
    for mname, apply, expect in _MUTATIONS[name]:
        restore = apply()
        try:
            red = _probe()
        except Exception as exc:                       # noqa: BLE001
            red = {"<变异体异常:%s>" % type(exc).__name__}
        finally:
            restore()
        ok = (red == expect)
        print("  [%s] %s → 红项 %s（期望 %s）" % ("OK" if ok else "BAD", mname, sorted(red), sorted(expect)))
        if not ok:
            bad.append("%s：得 %s 期望 %s" % (mname, sorted(red), sorted(expect)))
    if bad:
        print("\n变异自证失败：")
        for b in bad:
            print("  · " + b)
        return 1
    print("\n变异自证通过：%d 条退化各自**恰好**命中期望红项" % len(_MUTATIONS[name]))
    return 0


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        _i = sys.argv.index("--mutate")
        sys.exit(_mutate(sys.argv[_i + 1] if _i + 1 < len(sys.argv) else ""))
    sys.exit(0 if unittest.main(exit=False, verbosity=2).result.wasSuccessful() else 1)
