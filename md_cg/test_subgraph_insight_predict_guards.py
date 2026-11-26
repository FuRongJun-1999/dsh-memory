# -*- coding: utf-8 -*-
"""Regression guards for md_cg.{subgraph,insight,predict} isolation & numeric bounds."""
from __future__ import annotations

import importlib
import json
import math
import os
import shutil
import sys
import tempfile
import unittest

_TMP_ROOT = tempfile.mkdtemp(prefix="sg_ins_pred_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP_ROOT, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "cd" * 32
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP_ROOT, "tokens.json")
os.environ["MDCG_WRITE_GATE"] = "off"
os.environ["MDCG_SUSTAIN"] = "0"
os.environ["MDCG_READ_CACHE"] = "0"
os.environ["MDCG_HOTCACHE"] = "0"
os.makedirs(os.environ["MDCG_AUX_ROOT"], exist_ok=True)
for _k in ("MDCG_SESSION", "DSH_SESSION_ID", "MDCG_TOKEN", "MDCG_TENANT",
           "MDCG_CLEARANCE", "MDCG_LEGACY_ENV_AUTH", "MDCG_LEGACY_ENV_ADMIN",
           "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE"):
    os.environ.pop(_k, None)

from md_cg import insight, mdcos, predict, security, subgraph  # noqa: E402


class SubgraphInsightPredictGuards(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="sip_case_", dir=_TMP_ROOT)
        self.root = os.path.join(self.td, "store")
        self.admin = security.Principal(
            tenant="t1", actor="admin", clearance="secret",
            can_write=True, can_admin=True, role="designer", session="sess_admin",
        )
        self.guest = security.Principal(
            tenant="t1", actor="guest", clearance="internal",
            can_write=False, can_admin=False, role="guest", session="sess_guest",
        )
        self.cg_a = mdcos.MdCGSecure(self.root, principal=self.admin)
        self.cg_a.add(
            "pub_root",
            "# 功能名：公开根节点\n# 生效条件：公开通用环境\n公开正文内容",
            layer="knowledge", sensitivity="internal", tags=["pub"],
            subgraph={"nodes": ["sec_child", "pub_leaf"]},
            edges=[{"target": "pub_leaf", "relation_type": "causal", "condition": "公开条件"}],
        )
        self.cg_a.add(
            "pub_leaf",
            "# 功能名：公开叶节点\n# 生效条件：公开叶场景\n# 不适用条件：离线场景\n公开叶正文",
            layer="knowledge", sensitivity="internal", tags=["pub"],
        )
        self.cg_a.add(
            "sec_child",
            "# 功能名：机密子项\n# 生效条件：核心密钥部署\n机密口令ALPHA",
            layer="knowledge", sensitivity="secret", importance=0.95, tags=["sec"],
            edges=[{"target": "pub_leaf", "relation_type": "causal", "condition": "密级条件X"}],
        )
        self.cg_a.add(
            "res_node",
            "# 功能名：受限错误节点\n# 生效条件：内部排查\n受限内容BETA",
            layer="knowledge", sensitivity="restricted", importance=0.65,
        )
        self.cg_a.add(
            "priv_dom",
            "# 功能名：私密域节点\n# 生效条件：个人情绪私密\n私密域内容GAMMA",
            layer="contextual", sensitivity="internal", tags=["域:私密"],
        )
        self.cg_g = mdcos.MdCGSecure(self.root, principal=self.guest)

    def tearDown(self):
        self.cg_a.close()
        self.cg_g.close()

    # ---- subgraph guards ----

    def test_expand_max_nodes_none_and_validation(self):
        res = subgraph.expand(self.cg_a, "pub_root", max_nodes=None)
        self.assertEqual(res["root"], "pub_root")
        self.assertIn("pub_leaf", res["nodes"])
        self.assertIn("sec_child", res["nodes"])
        self.assertFalse(res["truncated"])
        with self.assertRaises(ValueError):
            subgraph.expand(self.cg_a, "pub_root", max_nodes=True)
        with self.assertRaises(ValueError):
            subgraph.expand(self.cg_a, "pub_root", max_depth=False)
        for bad in (float("nan"), float("inf"), -float("inf")):
            with self.assertRaises((ValueError, OverflowError)):
                subgraph.expand(self.cg_a, "pub_root", max_nodes=bad)

    def test_subgraph_visibility_isolation_for_guest(self):
        ch_idx = subgraph.children_index(self.cg_g)
        self.assertEqual(ch_idx.get("pub_root"), ["pub_leaf"])
        self.assertNotIn("sec_child", ch_idx.get("pub_root", []))
        self.assertNotIn("sec_child", subgraph.parents_index(self.cg_g))
        rts = subgraph.roots(self.cg_g)
        self.assertNotIn("sec_child", rts)
        self.assertNotIn("res_node", rts)
        self.assertIn("pub_root", rts)

        ex_sec = subgraph.expand(self.cg_g, "sec_child")
        self.assertEqual(ex_sec["nodes"], [])
        self.assertEqual(ex_sec["n_nodes"], 0)

        val = subgraph.validate(self.cg_g)
        for it in val["items"]:
            self.assertNotEqual(it.get("id"), "sec_child")
            self.assertNotEqual(it.get("child"), "sec_child")
            self.assertNotEqual(it.get("parent"), "sec_child")

    def test_reconstruct_scene_isolation_and_stale_index_fail_closed(self):
        # Guest probing secret/restricted node IDs must get blindspot (no oracle)
        rec = subgraph.reconstruct_scene(self.cg_g, ids=["sec_child", "res_node"])
        self.assertEqual(rec["status"], "blindspot")
        self.assertEqual(rec["anchors"], [])
        self.assertEqual(set(rec["missing"]), {"sec_child", "res_node"})

        rec_clue = subgraph.reconstruct_scene(self.cg_g, clues="sec_child 机密口令ALPHA")
        self.assertEqual(rec_clue["status"], "blindspot")

        # Even for admin, stale index missing sensitivity on secret node must NOT leak condition terms
        self.cg_a.index["nodes"]["sec_child"].pop("sensitivity", None)
        cs = subgraph._condition_space(self.cg_a, ["sec_child"])
        self.assertEqual(cs["per_anchor"].get("sec_child"), {"effective": [], "non_applicable": []})
        self.assertEqual(cs["common"], [])
        self.assertEqual(cs["individual"], [])

        # _anchor_scores must skip encrypted nodes even for admin
        scores = subgraph._anchor_scores(self.cg_a, ["sec_child"], ["机密口令ALPHA", "核心密钥部署"])
        self.assertEqual(scores, [])

        # _node_terms_and_grams fail-closed on unjudgeable frontmatter sensitivity
        bad_id = "bad_sens_node"
        self.cg_a.add(bad_id, "# 功能名：坏密级\n# 生效条件：条件A\n正文", layer="knowledge", sensitivity="internal")
        nd = self.cg_a.get(bad_id)
        fm = dict(nd["frontmatter"])
        fm["sensitivity"] = "bogus_level"
        self.cg_a._write_node(bad_id, os.path.join(self.cg_a.root, nd["path"]), fm, nd["content"])
        self.cg_a.index["nodes"][bad_id].pop("sensitivity", None)
        # MdCGSecure rejects invalid sensitivity in _readable -> None (fail-closed)
        self.assertIsNone(subgraph._node_terms_and_grams(self.cg_a, bad_id))
        # Plain MdCGOS (no _readable) hits frontmatter _sensitivity_of -> unjudgeable=True
        self.cg_a.flush()
        plain_cg = mdcos.MdCGOS(self.root)
        try:
            plain_cg.index["nodes"][bad_id].pop("sensitivity", None)
            ntg = subgraph._node_terms_and_grams(plain_cg, bad_id)
            self.assertEqual(ntg["grams"], set())
            self.assertTrue(ntg.get("unjudgeable"))
        finally:
            plain_cg.close()

        # reconstruct_scene(apply=True) from 域:私密 preserves tag & withholds maintain log terms
        rec_p = subgraph.reconstruct_scene(self.cg_a, ids=["priv_dom"], apply=True)
        self.assertEqual(rec_p["status"], "reconstructed")
        self.assertTrue(rec_p["scene_written"])
        scene_nd = self.cg_a.get(rec_p["scene_id"])
        self.assertIn("域:私密", scene_nd["frontmatter"].get("tags") or [])
        mlog = os.path.join(self.cg_a.root, subgraph.MAINTAIN_LOG)
        with open(mlog, encoding="utf-8") as fh:
            last_rec = json.loads(fh.read().strip().splitlines()[-1])
        self.assertTrue(last_rec.get("condition_terms_withheld"))
        self.assertEqual(last_rec.get("common"), [])

    # ---- insight guards ----

    def test_insight_outlook_and_events_isolation(self):
        self.cg_a.add(
            "sec_ins", "机密洞见正文", layer="contextual",
            sensitivity="secret", tags=[insight.TAG_EVENT], insight_state="pending",
        )
        # Re-open guest to see updated index
        cg_g2 = mdcos.MdCGSecure(self.root, principal=self.guest)
        try:
            self.assertNotIn("sec_ins", insight._events(cg_g2))
            self.assertIsNone(insight._read_event(cg_g2, "sec_ins"))
            ol_g = insight.outlook(cg_g2)
            ol_a = insight.outlook(self.cg_a)
            # Admin sees pub_root, pub_leaf, sec_child, res_node, priv_dom, sec_ins (6)
            # Guest sees only internal: pub_root, pub_leaf, priv_dom (3)
            self.assertEqual(ol_a["d1"]["total"], 6)
            self.assertEqual(ol_g["d1"]["total"], 3)
            self.assertNotIn("sec_child", ol_g["d2"]["high_importance_unprotected"])
            self.assertEqual(ol_g["d2"]["insight"]["recorded"], 0)
        finally:
            cg_g2.close()

    def test_insight_normalize_record_verify_list_bounds(self):
        # Non-finite and bool retrievability must NOT open window
        for bad_c1 in (float("inf"), -float("inf"), float("nan"), True, False):
            w = insight.window({"retrievability": bad_c1, "cross_domain": ["x"], "pressure": "low"})
            self.assertFalse(w["open"], f"window must stay closed for {bad_c1!r}")
            self.assertEqual(w["c1"], 0.0)
        # Non-finite and bool continuity_turns must not raise OverflowError
        for bad_ct in (float("inf"), -float("inf"), float("nan"), True, -5):
            norm = insight.normalize({"continuity_turns": bad_ct})
            self.assertEqual(norm["conditions"]["continuity_turns"], 0)

        # record(**extra) must NOT allow forging insight_state/protected
        r = insight.record(
            self.cg_a, statement="不可伪造状态", node_id="ins_no_forge",
            insight_state="verified", protected=True, protection_reason="fake",
            insight_evidence=[{"type": "v3"}],
        )
        self.assertEqual(r["state"], insight.STATE_PENDING)
        nd = self.cg_a.get("ins_no_forge")
        fm = nd["frontmatter"]
        self.assertEqual(fm["insight_state"], insight.STATE_PENDING)
        self.assertFalse(fm.get("protected"))
        self.assertEqual(fm["insight_evidence"], [])

        # record rejects NaN/Inf/bool importance
        for bad_imp in (float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                insight.record(self.cg_a, statement=f"bad_{bad_imp}", importance=bad_imp)

        # verify recovers cleanly from NaN stored importance
        self.cg_a._write_node(
            "ins_no_forge", os.path.join(self.cg_a.root, nd["path"]),
            {**fm, "importance": float("nan")}, nd["content"],
        )
        vr = insight.verify(self.cg_a, "ins_no_forge", verdict="verified")
        self.assertEqual(vr["importance"], insight.VERIFY_IMPORTANCE_FLOOR)
        self.assertTrue(math.isfinite(vr["importance"]))

        # list_events negative limit returns [] and bool raises ValueError
        self.assertEqual(insight.list_events(self.cg_a, limit=-1), [])
        with self.assertRaises(ValueError):
            insight.list_events(self.cg_a, limit=True)

        # outlook rejects invalid sample_limit / recent_days
        with self.assertRaises(ValueError):
            insight.outlook(self.cg_a, sample_limit=True)
        with self.assertRaises(ValueError):
            insight.outlook(self.cg_a, recent_days=float("nan"))

    # ---- predict guards ----

    def test_predict_nan_and_beta_posterior_guards(self):
        self.assertEqual(predict._edge_conf({"confidence": float("nan")}), 0.0)
        self.assertEqual(predict._edge_conf({"confidence": float("inf")}), 0.0)
        self.assertEqual(predict._edge_conf({"confidence": -float("inf")}), 0.0)
        self.assertEqual(predict._edge_conf({}), 1.0)

        u = predict._uncertainty(float("nan"))
        self.assertEqual(u["confidence"], 0.0)
        self.assertEqual(u["lower"], 0.0)
        self.assertEqual(u["upper"], 0.5)
        self.assertEqual(predict._uncertainty(float("inf"))["confidence"], 0.0)
        self.assertEqual(predict._uncertainty(True)["confidence"], 0.0)

        self.assertEqual(predict.extrapolation_validity({"confs": [0.5, float("nan")]}), "unknown")
        self.assertEqual(predict.extrapolation_validity({"confs": [0.5, float("inf")]}), "unknown")

        for bad_args in (
            ([], 0, 0.4),
            ([], -1, 0.4),
            ([], 10, 1.5),
            ([], 10, -0.1),
            ([], float("nan"), 0.4),
            ([], float("inf"), 0.4),
            ([], 10, float("nan")),
            ([], True, 0.4),
            ([], 10, False),
        ):
            with self.assertRaises(ValueError, msg=f"beta_posterior{bad_args} must raise ValueError"):
                predict.beta_posterior(*bad_args)

        # Valid boundary base=0.0 and base=1.0 still succeed cleanly
        p_zero = predict.beta_posterior([], prior_k=10, base=0.0)
        self.assertEqual(p_zero["mean"], 0.0)
        self.assertEqual(p_zero["std"], 0.0)

        # PREDICTION_META_DIM=inf must fall back to 0.0 on reload
        old_env = os.environ.get("PREDICTION_META_DIM")
        try:
            os.environ["PREDICTION_META_DIM"] = "inf"
            reloaded = importlib.reload(predict)
            self.assertEqual(reloaded.W_META, 0.0)
        finally:
            if old_env is None:
                os.environ.pop("PREDICTION_META_DIM", None)
            else:
                os.environ["PREDICTION_META_DIM"] = old_env
            importlib.reload(predict)

    def test_predict_visibility_and_gap_classification(self):
        # Guest cannot probe secret node via routes() or causal_path() or causal_gate()
        r = predict.routes(self.cg_g, start_id="sec_child")
        self.assertEqual(r["status"], "start_not_found")
        cp_self = predict.causal_path(self.cg_g, "sec_child", "sec_child")
        self.assertFalse(cp_self["reachable"])
        cp_edge = predict.causal_path(self.cg_g, "sec_child", "pub_leaf")
        self.assertFalse(cp_edge["reachable"])
        self.assertEqual(predict.causal_gate(self.cg_g, "sec_child", "pub_leaf"), (False, "rejected_semantic_only"))
        self.assertEqual(predict._label(self.cg_g, "sec_child"), "sec_child")
        self.assertEqual(predict._label(self.cg_a, "sec_child"), "sec_child")  # encrypted -> id only
        self.assertEqual(predict.semantic_neighbors(self.cg_a, "sec_child"), [])

        # _write_gap must preserve sensitivity & 域:私密 and withhold secret plaintext
        self.cg_a.add(
            "unres_sec", "机密未决问题正文XYZ", layer="unresolved",
            sensitivity="secret", tags=["域:私密"],
        )
        step = {"description": "机密未决问题正文XYZ", "hint": "待补", "terminal": "unresolved"}
        gid = predict._write_gap(self.cg_a, "unres_sec", step, actor="insight")
        self.assertIsNotNone(gid)
        gnd = self.cg_a.get(gid)
        self.assertEqual(gnd["frontmatter"].get("sensitivity"), "secret")
        self.assertIn("域:私密", gnd["frontmatter"].get("tags") or [])
        self.assertNotIn("机密未决问题正文XYZ", gnd["content"])


if __name__ == "__main__":
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(SubgraphInsightPredictGuards)
        res = unittest.TextTestRunner(verbosity=2).run(suite)
        sys.exit(0 if res.wasSuccessful() else 1)
    finally:
        shutil.rmtree(_TMP_ROOT, ignore_errors=True)
