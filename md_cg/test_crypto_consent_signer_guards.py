# -*- coding: utf-8 -*-
"""Guard tests for md_cg/crypto.py, md_cg/consent_gate.py, and md_cg/signer.py.

Run:
  python -X utf8 -m md_cg.test_crypto_consent_signer_guards
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from md_cg import consent_gate as G
from md_cg import crypto
from md_cg import signer as S


class TestCryptoHardening(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="test_b2_crypto_")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_01_verify_encrypted_rejects_non_b64_and_tagless_blocks(self):
        forged_plain = crypto.ENC_PREFIX + "!!!PLAINTEXT WITH SPACES AND XX!!!" + crypto.ENC_SUFFIX
        tagless_12b = crypto.ENC_PREFIX + base64.b64encode(b"A" * 12).decode() + crypto.ENC_SUFFIX
        short_27b = crypto.ENC_PREFIX + base64.b64encode(b"A" * 27).decode() + crypto.ENC_SUFFIX
        self.assertFalse(crypto.verify_encrypted(forged_plain))
        self.assertFalse(crypto.verify_encrypted(tagless_12b))
        self.assertFalse(crypto.verify_encrypted(short_27b))

        dek = b"k" * crypto.KEY_LEN
        sealed = crypto.seal_node("real secret", dek, "n1", "t", "a")
        self.assertTrue(crypto.verify_encrypted(sealed))
        self.assertTrue(crypto.verify_encrypted(sealed, dek, "n1", "t", "a"))

    def test_02_load_master_key_validates_strict_b64_length_and_concurrent_creation(self):
        env_var = "MDCG_TEST_B2_MK"
        try:
            for bad in ("!!!abcd!!!", base64.b64encode(b"short").decode(), "zzzz" * 16):
                os.environ[env_var] = bad
                with self.assertRaises(crypto.CryptoError):
                    crypto.load_master_key(env_var=env_var, create=False)
        finally:
            os.environ.pop(env_var, None)

        empty_path = os.path.join(self._tmp, "empty_master.key")
        with open(empty_path, "w", encoding="utf-8") as fh:
            fh.write("")
        with self.assertRaises(crypto.CryptoError):
            crypto.load_master_key(empty_path, env_var="MDCG_NO_SUCH_MK", create=True)

        # Concurrent first-start creation must converge to a single 32B key
        mk_path = os.path.join(self._tmp, "race", "master.key")
        results = []
        errors = []
        barrier = threading.Barrier(4)

        def worker():
            try:
                barrier.wait(timeout=5.0)
                results.append(crypto.load_master_key(mk_path, env_var="MDCG_NO_SUCH_MK", create=True))
            except Exception as exc:
                errors.append(exc)

        ts = [threading.Thread(target=worker) for _ in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=10.0)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 4)
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(len(results[0]), crypto.KEY_LEN)

    def test_03_unwrap_dek_malformed_envelopes_raise_locked_error_and_non_utf8_md_safe(self):
        fp = crypto.identity_fingerprint("t", "a")
        bad_envs = [
            "not-a-dict",
            {"id_fp": fp},
            {"id_fp": fp, "ct": "!!!bad!!!", "nonce": base64.b64encode(b"n" * 12).decode()},
            {"id_fp": fp, "ct": base64.b64encode(b"short").decode(), "nonce": base64.b64encode(b"n" * 12).decode()},
            {"id_fp": fp, "ct": base64.b64encode(b"c" * 32).decode(), "nonce": base64.b64encode(b"short").decode()},
        ]
        for idx, env in enumerate(bad_envs):
            rdir = os.path.join(self._tmp, f"k_{idx}")
            os.makedirs(rdir, exist_ok=True)
            with open(os.path.join(rdir, crypto.KEYS_FILE), "w", encoding="utf-8") as fh:
                json.dump({"v": 1, "alg": crypto.ALG, "envelopes": {"t|a": env}}, fh)
            with self.assertRaises(crypto.LockedError):
                crypto.unwrap_dek(rdir, b"k" * 32, "t", "a")

        # Non-UTF-8 .md must not crash _actor_has_ciphertext
        broot = os.path.join(self._tmp, "non_utf8")
        os.makedirs(broot, exist_ok=True)
        with open(os.path.join(broot, "corrupt.md"), "wb") as fh:
            fh.write(b"\xff\xfe\x80\x81")
        self.assertFalse(crypto._actor_has_ciphertext(broot, "t", "a"))


class TestConsentGateHardening(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="test_b2_gate_")
        with open(os.path.join(self._tmp, G.GATES_FILE), "w", encoding="utf-8") as fh:
            json.dump({"demo": {"must_contain": ["alice"], "any_of": ["allow"], "exclude": ["deny"]}}, fh)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_04_invalid_ttl_future_clock_and_never_raise_contract(self):
        for bad_ttl in (float("inf"), float("-inf"), float("nan"), 0, -5, True, False, "60", None):
            r = G.open_gate(self._tmp, "demo", "alice allow", source="user", ttl=bad_ttl, now=1000.0)
            self.assertIsInstance(r, dict)
            self.assertFalse(r["ok"], f"ttl={bad_ttl!r} should fail")
            self.assertFalse(G.is_open(self._tmp, "demo", now=1000.0))
            self.assertIsNone(G.stamp(self._tmp, "demo", now=1000.0))

        # Bad now must not raise in open_gate
        for bad_now in (float("nan"), float("inf"), True, "bad"):
            r = G.open_gate(self._tmp, "demo", "alice allow", source="user", ttl=60, now=bad_now)
            self.assertFalse(r["ok"])

        # Future opened_at must fail-closed across is_open, stamp, and state
        r_ok = G.open_gate(self._tmp, "demo", "alice allow", source="user", ttl=60, now=5000.0)
        self.assertTrue(r_ok["ok"])
        self.assertFalse(G.is_open(self._tmp, "demo", now=1000.0))
        self.assertIsNone(G.stamp(self._tmp, "demo", now=1000.0))
        self.assertFalse(G.state(self._tmp, now=1000.0)["demo"]["open"])
        self.assertTrue(G.is_open(self._tmp, "demo", now=5010.0))
        self.assertIsNotNone(G.stamp(self._tmp, "demo", now=5010.0))

        # Tampered _gate_state.json with inf/nan ttl must never crash stamp/is_open/state
        with open(os.path.join(self._tmp, "_gate_state.json"), "w", encoding="utf-8") as fh:
            json.dump({"demo": {"opened_at": 1000.0, "ttl": "Infinity"}}, fh)
        self.assertFalse(G.is_open(self._tmp, "demo", now=1005.0))
        self.assertIsNone(G.stamp(self._tmp, "demo", now=1005.0))
        self.assertFalse(G.state(self._tmp, now=1005.0)["demo"]["open"])

        # Non-dict spec entry must not crash open_gate
        with open(os.path.join(self._tmp, G.GATES_FILE), "w", encoding="utf-8") as fh:
            json.dump({"demo": "corrupted"}, fh)
        r_bad = G.open_gate(self._tmp, "demo", "alice allow", source="user", ttl=60, now=1000.0)
        self.assertFalse(r_bad["ok"])

    def test_05_is_quoted_blocks_padded_untrusted_memory_tilde_fence_and_partial_quote(self):
        padded = "X" * 60 + " <untrusted-memory> alice allow </untrusted-memory>"
        self.assertTrue(G.is_quoted(padded))
        self.assertTrue(G.is_quoted("~~~\nalice allow\n~~~"))
        self.assertTrue(G.is_quoted("hello\n> alice allow"))
        self.assertFalse(G.is_quoted("alice allow"))


class TestSignerHardening(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="test_b2_signer_")
        self._old_env = {k: os.environ.get(k) for k in (S.SIGNERS_FILE_ENV, S.SIGNER_MODULE_ENV, S.KEY_FILE_ENV)}
        self.sp = os.path.join(self._tmp, "_signers.json")
        os.environ[S.SIGNERS_FILE_ENV] = self.sp

    def tearDown(self):
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_06_loosening_catches_default_signer_and_sign_on_removal(self):
        S.set_policy(
            "sub1", path=self.sp, signer="hmac-local",
            sign_on=["handshake", "evidence"],
            require_peer_signature=True, on_verify_fail="reject",
        )
        msg_def = S.loosening("sub1", path=self.sp, default_signer="null")
        self.assertIn("default_signer", msg_def)

        msg_rm = S.loosening("sub1", path=self.sp, sign_on=["handshake"])
        self.assertIn("evidence", msg_rm)

        msg_empty = S.loosening("sub1", path=self.sp, sign_on=[])
        self.assertTrue(bool(msg_empty))

        # Strengthening (adding action) must NOT be treated as loosening
        self.assertEqual(
            S.loosening("sub1", path=self.sp, sign_on=["handshake", "evidence", "withdrawal"]),
            "",
        )

    def test_07_autoload_does_not_poison_cache_on_failure_and_load_key_atomic(self):
        bad_mod = "_mdcg_nonexistent_signer_mod_wave4"
        S._LOADED_MODULES.discard(bad_mod)
        os.environ[S.SIGNER_MODULE_ENV] = bad_mod
        with self.assertRaises(S.SignerError):
            S._autoload()
        self.assertNotIn(bad_mod, S._LOADED_MODULES)
        # Second attempt must still fail rather than silently returning
        with self.assertRaises(S.SignerError):
            S._autoload()
        os.environ.pop(S.SIGNER_MODULE_ENV, None)

        # Concurrent first-start load_key must yield one identical key
        kf = os.path.join(self._tmp, "keys", "_signer.key")
        keys = []
        errs = []
        barrier = threading.Barrier(4)

        def worker():
            try:
                barrier.wait(timeout=5.0)
                keys.append(S.load_key(kf))
            except Exception as exc:
                errs.append(exc)

        ts = [threading.Thread(target=worker) for _ in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=10.0)
        self.assertEqual(errs, [])
        self.assertEqual(len(keys), 4)
        self.assertEqual(len(set(keys)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
