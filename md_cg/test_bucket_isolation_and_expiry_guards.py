# -*- coding: utf-8 -*-
"""Guard tests for bucketindex / bucketscope / scopeselect privacy isolation,
lifecycle retirement, UTC/epoch expiry parity, and scope deduplication.

Run:
  python -X utf8 -m md_cg.test_bucket_isolation_and_expiry_guards
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from md_cg import bucketindex as BI
from md_cg import bucketscope as BS
from md_cg import crypto
from md_cg import lifecycle
from md_cg import scopeselect as SS
from md_cg.mdcos import MdCGSecure
from md_cg.security import Principal


class TestBucketIsolationAndExpiryGuards(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="test_b1_guard_")
        self._old_env = {k: os.environ.get(k) for k in (
            "HOME", "USERPROFILE", "MDCG_SESSION", "DSH_SESSION_ID",
            "MDCG_WRITE_GATE", "MDCG_BUCKET_SCOPE", "MDCG_SCOPE_SELECT",
        )}
        os.environ["HOME"] = self._tmp
        os.environ["USERPROFILE"] = self._tmp
        os.environ.pop("MDCG_SESSION", None)
        os.environ.pop("DSH_SESSION_ID", None)
        os.environ["MDCG_WRITE_GATE"] = "off"
        os.environ["MDCG_BUCKET_SCOPE"] = "1"
        os.environ["MDCG_SCOPE_SELECT"] = "1"
        self.store_dir = os.path.join(self._tmp, "store")
        self.mk = b"\x22" * 32
        self.principal = Principal(
            actor="alice", clearance="secret", session="sess_a", can_admin=True
        )
        self.cg = MdCGSecure(self.store_dir, principal=self.principal, master_key=self.mk)

    def tearDown(self):
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_01_build_with_content_never_leaks_sensitive_private_or_retired_plaintext(self):
        now = 1760000000.0
        self.cg.add(
            "n_priv", "secret payload SECRET_PRIV_TOKEN_99 alpha_term",
            layer="contextual", sensitivity="private", session="sess_a", created_at=now,
        )
        self.cg.add(
            "n_sec", "top secret SECRET_SEC_TOKEN_88 alpha_term",
            layer="contextual", sensitivity="secret", session="sess_a", created_at=now,
        )
        self.cg.add(
            "n_rest", "restricted error SECRET_REST_TOKEN_77 alpha_term",
            layer="contextual", sensitivity="restricted", session="sess_a", created_at=now,
        )
        self.cg.add(
            "n_pdom", "private domain SECRET_PDOM_TOKEN_66 alpha_term",
            layer="contextual", tags=["域:私密"], session="sess_a", created_at=now,
        )
        self.cg.add(
            "n_rej", "rejected memory SECRET_REJ_TOKEN_55 alpha_term",
            layer="rejected", session="sess_a", created_at=now,
        )
        self.cg.add(
            "n_ok", "normal public memory PUBLIC_OK_TOKEN_11 alpha_term",
            layer="contextual", session="sess_a", created_at=now,
        )

        BI.build(self.cg, write=True, with_content=True)
        with open(os.path.join(self.store_dir, BI.SKEL_FILE), encoding="utf-8") as fh:
            skel_txt = fh.read()
        with open(os.path.join(self.store_dir, BI.TERMS_FILE), encoding="utf-8") as fh:
            terms_txt = fh.read()
        for tok in (
            "secret_priv_token_99",
            "secret_sec_token_88",
            "secret_rest_token_77",
            "secret_pdom_token_66",
            "secret_rej_token_55",
        ):
            self.assertNotIn(tok, skel_txt)
            self.assertNotIn(tok, terms_txt)
        self.assertIn("public_ok_token_11", skel_txt)

    def test_02_default_recall_and_pick_block_retired_isolated_ciphertext_and_private_domain(self):
        now = 1760000000.0
        self.cg.add("n_arch", "archived memory alpha_query", layer="contextual", session="sess_a", created_at=now)
        r_dem = lifecycle.set_state(self.cg, "n_arch", "demoted", reason="step1")
        self.assertTrue(r_dem["ok"], r_dem)
        r_arc = lifecycle.set_state(self.cg, "n_arch", "archived", reason="retired")
        self.assertTrue(r_arc["ok"], r_arc)
        self.cg.add("n_sup", "superseded memory alpha_query", layer="contextual", session="sess_a", created_at=now)
        r_sup = lifecycle.set_state(self.cg, "n_sup", "superseded", reason="replaced")
        self.assertTrue(r_sup["ok"], r_sup)
        self.cg.add("n_rej", "rejected memory alpha_query", layer="rejected", session="sess_a", created_at=now)
        self.cg.add("n_goal", "goal memory alpha_query", layer="goals", session="sess_a", created_at=now)
        self.cg.add("n_pdom", "private domain alpha_query", layer="contextual", tags=["域:私密"], session="sess_a", created_at=now)
        self.cg.add("n_ok", "active memory alpha_query", layer="contextual", session="sess_a", created_at=now)

        BI.build(self.cg, write=True, with_content=True)
        res = self.cg.recall("alpha_query", session="sess_a", now=now + 60)
        ids = [item["id"] for item in res["pack"]]
        self.assertIn("n_ok", ids)
        for forbidden in ("n_arch", "n_sup", "n_rej", "n_goal"):
            self.assertNotIn(forbidden, ids)
        # Direct bucketscope must also block 域:私密 in addition to retired & isolated layers
        bs_res = BS.scope_recall(self.cg, "alpha_query", "sess_a", now + 60, cap=8)
        bs_ids = [n["id"] for n, *_ in bs_res]
        self.assertEqual(bs_ids, ["n_ok"])

        # fill_rest=True path must also enforce eligibility
        picked_fill = BS._pick(
            self.cg, ["n_arch", "n_sup", "n_rej", "n_goal", "n_pdom", "n_ok"],
            ["nomatchterm"], 8, validity=True, now=now + 60, fill_rest=True,
        )
        self.assertEqual([n["id"] for n, *_ in picked_fill], ["n_ok"])

        # Raw ciphertext node must never be returned by _pick
        fake_ct = crypto.seal_node("secret alpha_query", self.mk, "n_ct", "default", "alice")

        class _CipherStore:
            index = {"nodes": {"n_ct": {"id": "n_ct", "layer": "contextual"}}}
            def get(self, nid):
                return {"id": nid, "content": fake_ct, "frontmatter": {"created_at": now}}

        self.assertEqual(BS._pick(_CipherStore(), ["n_ct"], ["mdcg-enc"], 5, fill_rest=True), [])

    def test_03_is_expired_handles_utc_offset_epoch_and_effective_until(self):
        # 2026-01-01T00:00:00Z == epoch 1767225600.0
        utc_ts = 1767225600.0
        node_utc = {"frontmatter": {"valid_until": "2026-01-01T00:00:00Z"}}
        # 1 hour BEFORE UTC expiry must NOT be expired (previously falsely expired on UTC+8!)
        self.assertFalse(BS._is_expired(node_utc, now=utc_ts - 3600))
        # 60s AFTER UTC expiry MUST be expired
        self.assertTrue(BS._is_expired(node_utc, now=utc_ts + 60))

        # Numeric epoch valid_until
        self.assertFalse(BS._is_expired({"frontmatter": {"valid_until": utc_ts}}, now=utc_ts - 60))
        self.assertTrue(BS._is_expired({"frontmatter": {"valid_until": utc_ts}}, now=utc_ts + 60))

        # Canonical effective_until & camelCase validUntil
        self.assertTrue(BS._is_expired({"frontmatter": {"effective_until": "2026-01-01T00:00:00Z"}}, now=utc_ts + 60))
        self.assertTrue(BS._is_expired({"frontmatter": {"validUntil": "2026-01-01T00:00:00Z"}}, now=utc_ts + 60))

        # bool must not be treated as epoch 1
        self.assertFalse(BS._is_expired({"frontmatter": {"valid_until": True}}, now=utc_ts))

    def test_04_step15_dedup_and_scopeselect_cache_invalidation(self):
        now = 1760000000.0
        self.cg.add(
            "n_dup", "duplicate guard alpha_unique_term",
            layer="contextual", session="sess_a", created_at=now,
        )
        BI.build(self.cg, write=True, with_content=True)
        # Rapid same-size overwrite of _bucketskel.json must invalidate _SKEL_CACHE via mtime_ns/ino
        s1 = SS._skel_table(self.cg)
        self.assertIn("alpha_unique_term", json.dumps(s1, ensure_ascii=False))
        self.cg.add(
            "n_dup", "duplicate guard zzzzz_unique_term",
            layer="contextual", session="sess_a", created_at=now,
        )
        BI.build(self.cg, write=True, with_content=True)
        s2 = SS._skel_table(self.cg)
        self.assertIn("zzzzz_unique_term", json.dumps(s2, ensure_ascii=False))

        # Verify step 1.5 deduplicates nodes already picked in step 1 (session)
        self.cg.index["nodes"]["n_dup"]["bucket"] = "cond_alpha_1"
        orig_pick = SS.pick_scopes
        try:
            SS.pick_scopes = lambda *a, **kw: [("bucket", "cond_alpha_1", 2.0)]
            res = BS.scope_recall(self.cg, "zzzzz_unique_term", "sess_a", now + 60, cap=8)
            ids = [n["id"] for n, *_ in res]
            self.assertEqual(ids.count("n_dup"), 1, f"duplicate node in scope_recall: {ids}")
        finally:
            SS.pick_scopes = orig_pick

    def test_05_day_of_rejects_bool_and_nonfinite_and_rebuild_lock_prevents_race(self):
        self.assertIsNone(BI.day_of(True))
        self.assertIsNone(BI.day_of(False))
        self.assertIsNone(BI.day_of(float("nan")))
        self.assertIsNone(BI.day_of(float("inf")))
        self.assertIsNotNone(BI.day_of(1760000000.0))

        # Concurrent background maybe_auto_rebuild for same root must not double-spawn
        gate = threading.Event()
        entered = threading.Event()
        orig_build = BI.build
        calls = []

        def slow_build(store, *a, **kw):
            calls.append(1)
            entered.set()
            gate.wait(timeout=2.0)
            return orig_build(store, *a, **kw)

        try:
            BI.build = slow_build
            r1 = BI.maybe_auto_rebuild(self.cg, interval_h=0.0, background=True)
            r2 = BI.maybe_auto_rebuild(self.cg, interval_h=0.0, background=True)
            self.assertTrue(r1["rebuilt"])
            self.assertFalse(r2["rebuilt"])
            self.assertEqual(r2["reason"], "running")
            entered.wait(timeout=2.0)
        finally:
            gate.set()
            time.sleep(0.05)
            BI.build = orig_build
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
