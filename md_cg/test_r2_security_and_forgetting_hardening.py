# -*- coding: utf-8 -*-
"""Regression guard suite for Route A PR-5 (P1 Concurrency, Security & Privacy Hardening).

Covers all 7 findings with fail-closed assertions and positive controls:
  G1 (A1-03 + A1-06) md_cg/forgetting.py:
      - _LayerBigramIndex.sync() serialized + gen_before drift detection prevents
        permanent silent corruption across concurrent writes;
      - forgetting.reinforce() guards cg._dirty[node_id] = e under cg._dirty_lock.
  G2 (SEC-A2-11) md_cg/branches.py:
      - cross-session unreadable private branch nodes cannot be overwritten by
        rewrite() or hijacked by fork(), and merge() skips them cleanly without
        unhandled ValueError.
  G3 (SEC-A2-12) md_cg/evidence.py:
      - _collect() and evidence() skip nodes where cg.get(nid) returns None so
        low-clearance readers never leak private/secret node metadata.
  G4 (SEC-A2-13) md_cg/tokens.py:
      - issue() & derive() reject NaN/±inf/bool/overflow/non-numeric TTL
        (fail-closed, cannot bypass N123 parent-TTL clamp or persist NaN in
        _tokens.json), while preserving finite ttl<0 pre-expired issuance
        (rejected on verify_token) and ttl=0 unbounded/parent-inherit contract;
      - verify_token() rejects non-finite/bool/invalid/zero expires_at on token
        and ancestors; _save() enforces allow_nan=False.
  G5 (SEC-A2-14) md_cg/export.py:
      - _write_jsonl() opens .tmp with 0o600 permissions and cleans up .tmp (and
        claimed file) in finally on any mid-write or publish failure.
  G6 (SEC-A2-09) scripts/intent_board.py:
      - public board filters out 域:私密, restricted/private/secret/encrypted
        diary nodes, escapes Markdown/HTML delimiters, sanitizes raw heartbeat
        errors, and survives non-dict heartbeat stamps.
  G7 (SEC-A2-10) scripts/degrade_watch.py:
      - large (>tail_mb) uncompressed .jsonl and single-frame .jsonl.zstd logs
        are scanned accurately instead of silently returning exit 0;
      - missing zstandard or corrupt .zstd returns documented exit code 2 (not 1);
      - non-dict JSON lines (null/int/list/str) are skipped without AttributeError.

Run: python -X utf8 -m md_cg.test_r2_security_and_forgetting_hardening
"""
from __future__ import annotations

import base64
import gc
import io
import json
import math
import os
import shutil
import stat
import sys
import tempfile
import threading
import time

# ── Environment isolation BEFORE importing md_cg submodules ──
_TMP_ROOT = tempfile.mkdtemp(prefix="mdcg_r2_pr5_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP_ROOT, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "11" * 32
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP_ROOT, "tokens_default.json")
os.environ["MDCG_WRITE_GATE"] = "warn"
os.environ["MDCG_ROOT"] = os.path.join(_TMP_ROOT, "cg_default")
os.environ["MDCG_SUSTAIN_DIR"] = os.path.join(_TMP_ROOT, "sustain_default")
os.makedirs(os.environ["MDCG_AUX_ROOT"], exist_ok=True)
for _env_k in (
    "MDCG_TOKEN",
    "MDCG_TENANT",
    "MDCG_CLEARANCE",
    "MDCG_SESSION",
    "DSH_SESSION_ID",
    "MDCG_LEGACY_ENV_AUTH",
    "MDCG_LEGACY_ENV_ADMIN",
    "MDCG_CAN_ADMIN",
    "MDCG_CAN_WRITE",
    "MDCG_STATE_ROOT",
    "MDCG_DATA_ROOT",
    "MDCG_TENANT_REGISTRY",
    "MDCG_VERIFIER_MODULES",
):
    os.environ.pop(_env_k, None)

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from md_cg import branches, evidence, export, forgetting, tokens  # noqa: E402
from md_cg.mdcg import MdCG, _DirtyDict  # noqa: E402
from md_cg.mdcos import MdCGSecure  # noqa: E402
from md_cg.security import Principal  # noqa: E402
import degrade_watch  # noqa: E402
import intent_board  # noqa: E402

_PASS = []
_FAIL = []

_BODY_TMPL = (
    "# 功能名：{name}\n"
    "# 生效条件：全时窗\n"
    "# 子功能：s\n"
    "# 执行：{text}\n"
    "# 验证方式：test\n"
    "# 不适用条件：无\n"
)


def check(name, cond, detail=""):
    if cond:
        _PASS.append(name)
        print("  PASS " + name)
    else:
        _FAIL.append(name)
        print("  FAIL " + name + (("  <- " + str(detail)[:260]) if detail else ""))
    return bool(cond)


def _raises(exc_type, fn, *args, **kwargs):
    try:
        res = fn(*args, **kwargs)
        return False, "returned %r" % (res,)
    except exc_type as exc:
        return True, str(exc)


# ------------------------------------------------------------------ G1: A1-03 & A1-06
def g1_forgetting_concurrency_and_dirty_lock():
    print("\n== G1 (A1-03 + A1-06): forgetting bigram sync concurrency & _dirty_lock ==")

    # G1a: Deterministic concurrent sync() race across v2 -> v3 write.
    root_a = os.path.join(_TMP_ROOT, "g1a")
    enter_get = threading.Event()
    resume_get = threading.Event()
    pause_state = {"armed": False, "fired": False}

    class _PausingMdCG(MdCG):
        """Subclass hook (not in __dict__) so _can_use_bigram_index remains True."""

        def get(self, node_id, probe=True):
            res = super().get(node_id, probe=probe)
            if node_id == "n1" and pause_state["armed"] and not pause_state["fired"]:
                pause_state["fired"] = True
                enter_get.set()
                resume_get.wait(timeout=10.0)
            return res

    cg = _PausingMdCG(root_a, autoflush=100000, async_flush=False)
    try:
        v1 = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉"
        v2 = "春花秋月何时了往事知多少小楼昨夜又东风故国"
        v3 = "星河鹭起云帆沧海长风破浪直挂云帆济沧海明月"
        cg.add("n1", _BODY_TMPL.format(name="n1", text=v1),
               layer="contextual", tags=["t"], importance=0.4, verification_basis="test")
        # Prime the bigram index at v1.
        r0 = forgetting.redundancy(cg, v1, layer="contextual")
        check("G1a-0 baseline bigram index matches v1",
              abs(r0["max"] - 1.0) < 1e-12 and r0["with"] == "n1", r0)

        # Write v2, then arm pause on next sync's get("n1").
        cg.add("n1", _BODY_TMPL.format(name="n1", text=v2),
               layer="contextual", tags=["t"], importance=0.4, verification_basis="test")
        pause_state["armed"] = True
        t2_errors = []

        def _t2():
            try:
                forgetting.redundancy(cg, v2, layer="contextual")
            except BaseException as exc:  # noqa: BLE001
                t2_errors.append(repr(exc))

        th2 = threading.Thread(target=_t2)
        th2.start()
        check("G1a-1 T2 entered get(n1) inside sync()", enter_get.wait(timeout=5.0))

        # While T2 holds stale v2 mid-sync, write v3 and launch T1 concurrently.
        cg.add("n1", _BODY_TMPL.format(name="n1", text=v3),
               layer="contextual", tags=["t"], importance=0.4, verification_basis="test")
        t1_done = threading.Event()
        t1_res = {}

        def _t1():
            try:
                t1_res["val"] = forgetting.redundancy(cg, v3, layer="contextual")
            except BaseException as exc:  # noqa: BLE001
                t1_res["err"] = repr(exc)
            finally:
                t1_done.set()

        th1 = threading.Thread(target=_t1)
        th1.start()
        # T1 must be blocked by sync lock while T2 is inside sync()!
        check("G1a-2 T1 is serialized behind T2 lock during sync()",
              not t1_done.wait(timeout=0.15))

        resume_get.set()
        th2.join(timeout=10.0)
        th1.join(timeout=10.0)
        check("G1a-3 concurrent sync threads finished without errors",
              not t2_errors and "err" not in t1_res, (t2_errors, t1_res))

        # Subsequent single-threaded calls must NEVER be permanently corrupted!
        lin_v3 = forgetting.redundancy(cg, v3, layer="contextual", limit=100)
        lin_v2 = forgetting.redundancy(cg, v2, layer="contextual", limit=100)
        for attempt in range(3):
            ex_v3 = forgetting.redundancy(cg, v3, layer="contextual")
            check(f"G1a-4.{attempt + 1} v3 exact == linear (1.0) after concurrent sync",
                  abs(ex_v3["max"] - lin_v3["max"]) < 1e-12
                  and ex_v3["with"] == lin_v3["with"] == "n1",
                  (ex_v3, lin_v3))
        ex_v2 = forgetting.redundancy(cg, v2, layer="contextual")
        check("G1a-5 stale v2 does NOT falsely match as 1.0",
              abs(ex_v2["max"] - lin_v2["max"]) < 1e-12 and ex_v2["max"] < 0.5,
              (ex_v2, lin_v2))
    finally:
        cg.close()

    # G1b: Multi-threaded writer + concurrent redundancy() readers converge cleanly.
    root_b = os.path.join(_TMP_ROOT, "g1b")
    cg_b = MdCG(root_b, autoflush=100000, async_flush=False)
    try:
        for i in range(10):
            cg_b.add(f"m_{i}", _BODY_TMPL.format(name=f"m_{i}", text=f"基线样本段落内容编号{i}甲乙丙丁"),
                     layer="contextual", tags=["t"], importance=0.4, verification_basis="test")
        stop_ev = threading.Event()
        errs = []

        def _reader(tid):
            while not stop_ev.is_set():
                try:
                    forgetting.redundancy(cg_b, f"并发查询段落内容编号{tid}戊己庚辛", layer="contextual")
                except BaseException as exc:  # noqa: BLE001
                    errs.append(repr(exc))
                    return

        readers = [threading.Thread(target=_reader, args=(i,)) for i in range(3)]
        for t in readers:
            t.start()
        try:
            for k in range(25):
                cg_b.add(f"m_{k % 10}",
                         _BODY_TMPL.format(name=f"m_{k % 10}", text=f"更新轮次{k}并发内容甲乙丙丁戊己"),
                         layer="contextual", tags=["t"], importance=0.4, verification_basis="test")
        finally:
            stop_ev.set()
            for t in readers:
                t.join(timeout=10.0)
        check("G1b-1 multi-threaded writer + redundancy readers zero errors", not errs, errs)
        probe_text = "更新轮次24并发内容甲乙丙丁戊己"
        exact_after = forgetting.redundancy(cg_b, probe_text, layer="contextual")
        linear_after = forgetting.redundancy(cg_b, probe_text, layer="contextual", limit=500)
        check("G1b-2 post-stress exact index matches linear scan",
              abs(exact_after["max"] - linear_after["max"]) < 1e-12
              and exact_after["with"] == linear_after["with"],
              (exact_after, linear_after))
    finally:
        cg_b.close()

    # G1c: A1-06 forgetting.reinforce() acquires cg._dirty_lock around cg._dirty[nid] = e.
    root_c = os.path.join(_TMP_ROOT, "g1c")
    cg_c = MdCG(root_c, autoflush=100000, async_flush=False)
    try:
        cg_c.add("r1", _BODY_TMPL.format(name="r1", text="强化锁保护测试正文"),
                 layer="contextual", tags=["t"], importance=0.4, verification_basis="test")

        class _TrackingRLock:
            def __init__(self):
                self._lock = threading.RLock()
                self._tls = threading.local()

            @property
            def depth(self):
                return getattr(self._tls, "depth", 0)

            def __enter__(self):
                self._lock.acquire()
                self._tls.depth = self.depth + 1
                return self

            def __exit__(self, *exc):
                self._tls.depth = max(0, self.depth - 1)
                self._lock.release()
                return False

        tlock = _TrackingRLock()
        write_depths = []

        class _ObsDirty(_DirtyDict):
            def __setitem__(self, k, v):
                write_depths.append((k, tlock.depth))
                return super().__setitem__(k, v)

        obs = _ObsDirty()
        obs.root = cg_c._dirty.root
        obs.write_gen = cg_c._dirty.write_gen
        obs.broad_gen = cg_c._dirty.broad_gen
        obs.path_gen = dict(cg_c._dirty.path_gen)
        dict.update(obs, cg_c._dirty)
        cg_c._dirty_lock = tlock
        cg_c._dirty = obs

        res = forgetting.reinforce(cg_c, "r1", delta=0.05)
        check("G1c-1 reinforce succeeded", isinstance(res, dict) and res.get("node_id") == "r1", res)
        check("G1c-2 reinforce wrote cg._dirty under _dirty_lock (depth >= 1)",
              bool(write_depths) and all(d >= 1 for _, d in write_depths),
              write_depths)
    finally:
        cg_c.close()

    # G1d: Concurrent reinforce() + flush() zero RuntimeError.
    root_d = os.path.join(_TMP_ROOT, "g1d")
    cg_d = MdCG(root_d, autoflush=100000, async_flush=False)
    try:
        for i in range(6):
            cg_d.add(f"rf_{i}", _BODY_TMPL.format(name=f"rf_{i}", text=f"并发强化节点{i}"),
                     layer="contextual", tags=["t"], importance=0.35, verification_basis="test")
        stop_d = threading.Event()
        err_d = []

        def _flusher():
            while not stop_d.is_set():
                try:
                    cg_d.flush()
                except BaseException as exc:  # noqa: BLE001
                    err_d.append(repr(exc))
                    return

        tf = threading.Thread(target=_flusher)
        tf.start()
        try:
            for k in range(30):
                forgetting.reinforce(cg_d, f"rf_{k % 6}", delta=0.01)
        finally:
            stop_d.set()
            tf.join(timeout=10.0)
        check("G1d concurrent reinforce() + flush() zero RuntimeError", not err_d, err_d)
    finally:
        cg_d.close()


# ------------------------------------------------------------------ G2: SEC-A2-11
def g2_branches_cross_session_hardening():
    print("\n== G2 (SEC-A2-11): branches cross-session rewrite/merge/fork fail-closed ==")
    root = os.path.join(_TMP_ROOT, "g2_branches")
    kek = bytes.fromhex("22" * 32)
    p_s1 = Principal(tenant="default", actor="alice", session="sess_1",
                     clearance="private", can_write=True, can_admin=False, role="record")
    p_s2 = Principal(tenant="default", actor="alice", session="sess_2",
                     clearance="private", can_write=True, can_admin=False, role="record")
    cg1 = MdCGSecure(root, principal=p_s1, master_key=kek, autoflush=1, async_flush=False)
    cg2 = None
    try:
        orig_secret = "S1_PRIVATE_BRANCH_SECRET_9911"
        cg1.add("mem_a", orig_secret, layer="contextual", sensitivity="private",
                tags=["keep_tag"], verification_basis="test", consistency=False)
        fk = branches.fork(cg1, ["mem_a"], branch_id="exp")
        check("G2-0 S1 fork private contextual node ok", fk.get("ok") is True, fk)

        # Also create an internal main node + S1 private branch node for merge() test.
        cg1.add("mem_pub", "PUBLIC_MAIN_BODY", layer="contextual", sensitivity="internal",
                verification_basis="test", consistency=False)
        cg1.add("mem_pub@exp2", "S1_PRIVATE_EXP2_BODY", layer="contextual",
                sensitivity="private", branch_id="exp2", branched_from="mem_pub",
                verification_basis="test", consistency=False)
        cg1.flush()

        cg2 = MdCGSecure(root, principal=p_s2, master_key=kek, autoflush=1, async_flush=False)
        check("G2-1 S2 cannot read S1 private branch node",
              cg2.get("mem_a@exp") is None and cg2.get("mem_pub@exp2") is None)

        # Fail-closed rewrite by S2
        rw = branches.rewrite(cg2, "mem_a@exp", "OVERWRITTEN_BY_S2")
        check("G2-2 S2 rewrite() on unreadable private branch node blocked fail-closed",
              rw.get("ok") is False and "不可见" in str(rw.get("error")), rw)

        # Verify S1's branch node is completely untouched on disk and in frontmatter
        cg1._maybe_reload_index()
        s1_rec = cg1.get("mem_a@exp")
        check("G2-3 S1 branch node content & tags intact after blocked S2 rewrite",
              s1_rec is not None
              and orig_secret in (s1_rec.get("content") or "")
              and "keep_tag" in ((s1_rec.get("frontmatter") or {}).get("tags") or []),
              s1_rec)

        # Fail-closed merge by S2: must NOT crash with ValueError!
        mg = branches.merge(cg2, "exp2")
        check("G2-4 S2 merge() on unreadable private branch node skips cleanly without ValueError",
              mg.get("ok") is False
              and mg.get("merged") == []
              and any(s.get("id") == "mem_pub@exp2" and "不可见" in str(s.get("why"))
                      for s in (mg.get("skipped") or [])),
              mg)
        check("G2-5 mem_pub content untouched after S2 merge skip",
              "PUBLIC_MAIN_BODY" in ((cg2.get("mem_pub") or {}).get("content") or ""))

        # Fail-closed fork collision by S2 against existing unreadable branch id
        fk2 = branches.fork(cg2, ["mem_pub"], branch_id="exp2")
        check("G2-6 S2 fork() cannot hijack existing unreadable branch node id",
              fk2.get("ok") is False and fk2.get("forked") == []
              and any("已存在" in str(s.get("why")) for s in (fk2.get("skipped") or [])),
              fk2)

        # Positive control: S1 can still rewrite and merge its own private branch node
        rw_ok = branches.rewrite(cg1, "mem_a@exp", orig_secret + " UPDATED_BY_S1")
        mg_ok = branches.merge(cg1, "exp")
        check("G2-7 positive control: S1 rewrite & merge succeed on own private branch",
              rw_ok.get("ok") is True and mg_ok.get("ok") is True
              and "UPDATED_BY_S1" in ((cg1.get("mem_a") or {}).get("content") or ""),
              (rw_ok, mg_ok))
    finally:
        cg1.close()
        if cg2 is not None:
            cg2.close()


# ------------------------------------------------------------------ G3: SEC-A2-12
def g3_evidence_metadata_leak_hardening():
    print("\n== G3 (SEC-A2-12): evidence._collect() & evidence() skip unreadable nodes ==")
    root = os.path.join(_TMP_ROOT, "g3_evidence")
    kek = bytes.fromhex("33" * 32)
    p_hi = Principal(tenant="default", actor="alice", session="s_hi",
                     clearance="secret", can_write=True, can_admin=True, role="designer")
    p_lo = Principal(tenant="default", actor="bob", session="s_lo",
                     clearance="internal", can_write=False, can_admin=False, role="output")
    cg_hi = MdCGSecure(root, principal=p_hi, master_key=kek, autoflush=1, async_flush=False)
    cg_lo = None
    try:
        cg_hi.add("obs_priv_1", "PRIVATE_OBS_CANARY", layer="contextual",
                  sensitivity="private",
                  tags=["identity_observation", "subject:alice", "secret-tag"],
                  verification_basis="test", consistency=False)
        cg_hi.add("obs_sec_1", "SECRET_OBS_CANARY", layer="contextual",
                  sensitivity="secret",
                  tags=["identity_observation", "subject:alice", "top-secret-tag"],
                  verification_basis="test", consistency=False)
        cg_hi.add("obs_pub_1", "PUBLIC_OBS_TEXT", layer="contextual",
                  sensitivity="internal",
                  tags=["identity_observation", "subject:alice", "pub-tag"],
                  verification_basis="test", consistency=False)
        # Imported cross-node evidence: one private, one internal
        cg_hi.add("xnode_priv_1", "XNODE_PRIV_CANARY", layer="contextual",
                  sensitivity="private",
                  tags=[evidence.TAG_XNODE, "subject:alice", "source:peer_a"],
                  verification_basis="test", consistency=False)
        cg_hi.add("xnode_pub_1", "XNODE_PUB_TEXT", layer="contextual",
                  sensitivity="internal",
                  tags=[evidence.TAG_XNODE, "subject:alice", "source:peer_a"],
                  verification_basis="test", consistency=False)
        cg_hi.flush()

        cg_lo = MdCGSecure(root, principal=p_lo, master_key=kek, autoflush=1, async_flush=False)
        check("G3-0 low-clearance reader gets None on private/secret nodes",
              cg_lo.get("obs_priv_1") is None and cg_lo.get("obs_sec_1") is None
              and cg_lo.get("xnode_priv_1") is None)

        lo_items = evidence._collect(cg_lo)
        lo_ids = [it["node_id"] for it in lo_items]
        check("G3-1 _collect(low) omits private & secret observation metadata",
              lo_ids == ["obs_pub_1"], lo_items)

        lo_ev = evidence.evidence(cg_lo)
        lo_ev_ids = [it["node_id"] for it in lo_ev["evidence"]]
        check("G3-2 evidence(low) omits private imported cross-node metadata",
              lo_ev["count"] == 1 and lo_ev_ids == ["xnode_pub_1"], lo_ev)

        # Positive control: high-clearance reader sees all nodes
        hi_ids = [it["node_id"] for it in evidence._collect(cg_hi)]
        hi_ev_ids = [it["node_id"] for it in evidence.evidence(cg_hi)["evidence"]]
        check("G3-3 positive control: high-clearance reader sees all observations & xnode evidence",
              set(hi_ids) == {"obs_priv_1", "obs_sec_1", "obs_pub_1"}
              and set(hi_ev_ids) == {"xnode_priv_1", "xnode_pub_1"},
              (hi_ids, hi_ev_ids))
    finally:
        cg_hi.close()
        if cg_lo is not None:
            cg_lo.close()


# ------------------------------------------------------------------ G4: SEC-A2-13
def g4_tokens_nan_ttl_hardening():
    print("\n== G4 (SEC-A2-13): tokens NaN/±inf/bool/overflow TTL, <=0 contract & allow_nan=False ==")
    tf = os.path.join(_TMP_ROOT, "g4_tokens.json")

    bad_ttls = [
        ("nan", float("nan")),
        ("+inf", float("inf")),
        ("-inf", float("-inf")),
        ("str_nan", "nan"),
        ("str_inf", "inf"),
        ("str_neg_inf", "-inf"),
        ("bool_true", True),
        ("bool_false", False),
        ("non_numeric", "abc"),
        ("overflow_float", 1e308 * 2),
        ("overflow_int", 10**400),
    ]
    for label, bad_ttl in bad_ttls:
        ok_err, msg = _raises(tokens.TokenError, tokens.issue, "record",
                              actor="bad-" + label, ttl=bad_ttl, path=tf)
        check(f"G4-1 issue() rejects ttl={label}", ok_err, msg)

    # Issue valid bounded parent token (positive control)
    parent = tokens.issue("designer", actor="g4-parent", ttl=3600.0, path=tf,
                          _allow_bootstrap=True)
    check("G4-2 positive control: issue() valid positive ttl succeeds",
          parent.get("ok") is True and math.isfinite(parent["expires_at"]), parent)

    # Preserve existing finite ttl <= 0 contracts:
    # - ttl=-10 mints a pre-expired token (used by test_issue1009_dual_review_auth),
    #   which verify_token() immediately rejects as expired;
    # - ttl=0 in issue() stays unbounded (expires_at=None), and in derive() inherits
    #   the bounded parent expires_at (cannot bypass N123 parent clamp).
    pre_exp = tokens.issue("verify", actor="g4-pre-expired", ttl=-10, path=tf)
    ok_pre_exp, msg_pre_exp = _raises(tokens.TokenError, tokens.verify_token,
                                      pre_exp["token"], path=tf)
    check("G4-2b issue(ttl=-10) creates pre-expired token rejected by verify_token()",
          pre_exp.get("ok") is True
          and math.isfinite(pre_exp["expires_at"])
          and pre_exp["expires_at"] < time.time()
          and ok_pre_exp and "过期" in msg_pre_exp,
          (pre_exp.get("expires_at"), msg_pre_exp))

    zero_issue = tokens.issue("record", actor="g4-zero-unbounded", ttl=0, path=tf)
    p_zero = tokens.verify_token(zero_issue["token"], path=tf)
    check("G4-2c issue(ttl=0) preserves unbounded expires_at=None contract",
          zero_issue.get("ok") is True and zero_issue["expires_at"] is None
          and p_zero.role == "record", zero_issue)

    for label, bad_ttl in bad_ttls:
        ok_err, msg = _raises(tokens.TokenError, tokens.derive, parent["token"],
                              "record", actor="d-" + label, ttl=bad_ttl, path=tf)
        check(f"G4-3 derive() rejects ttl={label} (cannot bypass N123 clamp)", ok_err, msg)

    neg_child = tokens.derive(parent["token"], "record", actor="g4-derive-neg",
                              ttl=-10.0, path=tf)
    ok_neg_child, msg_neg_child = _raises(tokens.TokenError, tokens.verify_token,
                                          neg_child["token"], path=tf)
    check("G4-3b derive(ttl=-10) creates pre-expired child rejected by verify_token()",
          neg_child.get("ok") is True
          and math.isfinite(neg_child["expires_at"])
          and neg_child["expires_at"] < time.time()
          and ok_neg_child and "过期" in msg_neg_child,
          (neg_child.get("expires_at"), msg_neg_child))

    zero_child = tokens.derive(parent["token"], "record", actor="g4-derive-zero",
                               ttl=0, path=tf)
    check("G4-3c derive(ttl=0) inherits bounded parent expires_at (N123 intact)",
          zero_child.get("ok") is True
          and zero_child["expires_at"] is not None
          and abs(zero_child["expires_at"] - parent["expires_at"]) < 1e-6,
          (zero_child.get("expires_at"), parent.get("expires_at")))

    # Confirm valid derive still clamps to parent TTL and verify_token passes
    child = tokens.derive(parent["token"], "record", actor="g4-child",
                          ttl=999999.0, path=tf)
    check("G4-4 positive control: derive() clamps finite long ttl to parent",
          "expires_at" in (child.get("clamped") or [])
          and child["expires_at"] <= parent["expires_at"] + 1e-6, child)
    p_child = tokens.verify_token(child["token"], path=tf)
    check("G4-5 positive control: verify_token(valid child) succeeds",
          p_child.role == "record", p_child)

    # Confirm _tokens.json on disk is strict JSON (no NaN / Infinity)
    raw_disk = open(tf, encoding="utf-8").read()
    check("G4-6 _tokens.json contains no NaN/Infinity literals",
          "NaN" not in raw_disk and "Infinity" not in raw_disk)

    # _save() rejects NaN via allow_nan=False
    bad_snapshot = json.loads(raw_disk)
    bad_snapshot["tokens"][child["token_id"]]["expires_at"] = float("nan")
    ok_save_err, save_msg = _raises(tokens.TokenError, tokens._save, bad_snapshot, tf)
    check("G4-7 _save() refuses to persist NaN (allow_nan=False)", ok_save_err, save_msg)

    # Tampered on-disk expires_at (NaN, Infinity, -Infinity, True, 0, "nan") -> verify_token fails closed
    for label, raw_exp in (
        ("NaN", "NaN"),
        ("Infinity", "Infinity"),
        ("-Infinity", "-Infinity"),
        ("bool_true", "true"),
        ("zero_epoch", "0"),
        ("str_nan", '"nan"'),
    ):
        tf_bad = os.path.join(_TMP_ROOT, f"g4_tamper_{label}.json")
        # Copy valid store and inject malformed expires_at into child record
        store = json.loads(raw_disk)
        store["tokens"][child["token_id"]]["expires_at"] = "__INJECT_EXP__"
        text = json.dumps(store, ensure_ascii=False).replace('"__INJECT_EXP__"', raw_exp)
        with open(tf_bad, "w", encoding="utf-8") as fh:
            fh.write(text)
        ok_v, vmsg = _raises(tokens.TokenError, tokens.verify_token, child["token"], path=tf_bad)
        check(f"G4-8 verify_token() fails closed on tampered self expires_at={label}", ok_v, vmsg)

    # Tampered ancestor expires_at=NaN -> verify_token(child) fails closed along chain
    tf_anc = os.path.join(_TMP_ROOT, "g4_tamper_anc.json")
    store_anc = json.loads(raw_disk)
    store_anc["tokens"][parent["token_id"]]["expires_at"] = "__INJECT_ANC__"
    with open(tf_anc, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(store_anc, ensure_ascii=False).replace('"__INJECT_ANC__"', "NaN"))
    ok_anc, anc_msg = _raises(tokens.TokenError, tokens.verify_token, child["token"], path=tf_anc)
    check("G4-9 verify_token() fails closed on tampered ancestor expires_at=NaN", ok_anc, anc_msg)


# ------------------------------------------------------------------ G5: SEC-A2-14
def g5_export_perms_and_tmp_cleanup():
    print("\n== G5 (SEC-A2-14): export 0o600 permissions & .tmp cleanup on error ==")
    root = os.path.join(_TMP_ROOT, "g5_export")
    out_dir = os.path.join(_TMP_ROOT, "g5_out")
    os.makedirs(out_dir, exist_ok=True)
    kek = bytes.fromhex("44" * 32)
    p = Principal(tenant="default", actor="alice", session="s1",
                  clearance="secret", can_write=True, can_admin=True, role="designer")
    cg = MdCGSecure(root, principal=p, master_key=kek, autoflush=1, async_flush=False)
    try:
        cg.add("p1", "EXPORT_SECRET_CANARY_4455", layer="knowledge",
               sensitivity="private", verification_basis="test", consistency=False)
        cg.add("p2", "EXPORT_PUBLIC_ROW", layer="knowledge",
               sensitivity="internal", verification_basis="test", consistency=False)
        cg.flush()

        # G5a: Observe os.open flags/mode for .tmp creation (+ POSIX mode check).
        seen_opens = []
        real_open = export.os.open

        def _spy_open(path, flags, mode=0o777, *args, **kwargs):
            seen_opens.append((path, flags, mode))
            return real_open(path, flags, mode, *args, **kwargs)

        export.os.open = _spy_open
        try:
            out_ok = os.path.join(out_dir, "ok_export.jsonl")
            res = export.export_graph(cg, out=out_ok)
        finally:
            export.os.open = real_open

        tmp_opens = [item for item in seen_opens if str(item[0]).endswith(".tmp")]
        check("G5-1 .tmp created with O_EXCL and mode 0o600",
              len(tmp_opens) == 1
              and bool(tmp_opens[0][1] & os.O_EXCL)
              and tmp_opens[0][2] == 0o600,
              tmp_opens)
        if os.name != "nt":
            mode_bits = stat.S_IMODE(os.stat(out_ok).st_mode)
            check("G5-1b POSIX exported file mode is 0o600", mode_bits == 0o600, oct(mode_bits))
        check("G5-2 positive control: export wrote both nodes & left zero .tmp files",
              res.get("ok") is True and res.get("written") == 2
              and not [f for f in os.listdir(out_dir) if ".tmp" in f],
              (res, os.listdir(out_dir)))

        # G5b: Mid-write exception MUST clean up .tmp file (no plaintext orphan!)
        err_dir = os.path.join(_TMP_ROOT, "g5_err_write")
        os.makedirs(err_dir, exist_ok=True)
        out_fail = os.path.join(err_dir, "fail_write.jsonl")

        def _failing_entries():
            items = list(export._iter_entries(cg))
            yield items[0]
            raise RuntimeError("simulated mid-write I/O failure")

        ok_exc, exc_msg = _raises(RuntimeError, export._write_jsonl, cg, out_fail, _failing_entries())
        leftover_w = os.listdir(err_dir)
        check("G5-3 mid-write exception propagates and leaves zero .tmp files",
              ok_exc and leftover_w == [], (exc_msg, leftover_w))

        # G5c: Publish failure with claim=True cleans up BOTH claimed placeholder and .tmp!
        pub_dir = os.path.join(_TMP_ROOT, "g5_err_pub")
        os.makedirs(pub_dir, exist_ok=True)
        out_pub = os.path.join(pub_dir, "fail_pub.jsonl")
        real_pub = export.publish

        def _boom_publish(src, dst):
            raise OSError("simulated publish failure")

        export.publish = _boom_publish
        try:
            ok_pe, pmsg = _raises(OSError, export._write_jsonl, cg, out_pub,
                                  export._iter_entries(cg), claim=True)
        finally:
            export.publish = real_pub
        leftover_p = os.listdir(pub_dir)
        check("G5-4 publish failure with claim=True cleans both claimed file and .tmp",
              ok_pe and leftover_p == [], (pmsg, leftover_p))
    finally:
        cg.close()


# ------------------------------------------------------------------ G6: SEC-A2-09
def g6_intent_board_privacy_and_heartbeat_hardening():
    print("\n== G6 (SEC-A2-09): intent_board private-domain/encrypted diary filter & heartbeat ==")
    root = os.path.join(_TMP_ROOT, "g6_board")
    kek = bytes.fromhex("55" * 32)
    p = Principal(tenant="default", actor="alice", session="s1",
                  clearance="secret", can_write=True, can_admin=True, role="designer")
    cg = MdCGSecure(root, principal=p, master_key=kek, autoflush=1, async_flush=False)
    try:
        cg.add("mem_1111aaaa", "公开日记安全首行 PUBLIC_DIARY_OK", layer="contextual",
               sensitivity="internal", tags=["日记"], verification_basis="test", consistency=False)
        cg.add("mem_2222bbbb", "私密域日记首行 PRIV_DOMAIN_CANARY_8822", layer="contextual",
               sensitivity="internal", tags=["日记", "域:私密"], verification_basis="test", consistency=False)
        cg.add("mem_3333cccc", "加密私密日记 PRIV_ENC_CANARY_7733", layer="contextual",
               sensitivity="private", tags=["日记"], verification_basis="test", consistency=False)
        cg.add("mem_4444dddd", "绝密日记 SECRET_ENC_CANARY_6644", layer="contextual",
               sensitivity="secret", tags=["日记"], verification_basis="test", consistency=False)
        cg.add("mem_5555eeee", "受限错误处置日记 RESTRICTED_CANARY_5511", layer="contextual",
               sensitivity="restricted", tags=["日记"], verification_basis="test", consistency=False)
        cg.add("mem_6666ffff", "公开 | 含竖线 <script>alert(1)</script> 日记", layer="contextual",
               sensitivity="internal", tags=["日记"], verification_basis="test", consistency=False)
        cg.flush()
    finally:
        cg.close()

    # Add heartbeat stamps: one valid with sensitive error, two malformed non-dict shapes.
    sustain_dir = os.path.join(root, "sustain")
    os.makedirs(sustain_dir, exist_ok=True)
    with open(os.path.join(sustain_dir, "heartbeat.ep1.stamp"), "w", encoding="utf-8") as fh:
        json.dump({
            "pid": os.getpid(),
            "ts": time.time(),
            "iso": "2026-11-25T12:00:00",
            "last_tick_done": {"name": "tidy", "ok": True},
            "last_tick_error": {"name": "sync", "error": "RAW_TRACE_SECRET_PATH_9900 | <b>bad</b>"},
        }, fh, ensure_ascii=False)
    with open(os.path.join(sustain_dir, "heartbeat.badlist.stamp"), "w", encoding="utf-8") as fh:
        fh.write('["not-a-dict-stamp"]')
    with open(os.path.join(sustain_dir, "heartbeat.badfields.stamp"), "w", encoding="utf-8") as fh:
        json.dump({
            "pid": "not-an-int",
            "ts": "not-a-float",
            "last_tick_done": "not-a-dict",
            "last_tick_error": "RAW_NON_DICT_ERR_CANARY_3322",
        }, fh, ensure_ascii=False)

    pub = intent_board.render(root, now=time.time(), private=False)
    check("G6-1 public board includes safe public diary",
          "PUBLIC_DIARY_OK" in pub, pub[-400:])
    check("G6-2 public board excludes 域:私密 diary plaintext",
          "PRIV_DOMAIN_CANARY_8822" not in pub and "mem_2222bbbb" not in pub)
    check("G6-3 public board excludes private/secret encrypted diaries & mdcg-enc envelopes",
          "mdcg-enc:" not in pub
          and "PRIV_ENC_CANARY_7733" not in pub
          and "SECRET_ENC_CANARY_6644" not in pub
          and "mem_3333cccc" not in pub
          and "mem_4444dddd" not in pub)
    check("G6-4 public board excludes restricted diary",
          "RESTRICTED_CANARY_5511" not in pub and "mem_5555eeee" not in pub)
    check("G6-5 public board escapes pipe and HTML tags in diary title",
          "\\|" in pub and "&lt;script&gt;" in pub and "<script>" not in pub)
    check("G6-6 public board omits raw heartbeat error strings & survives non-dict stamps",
          "RAW_TRACE_SECRET_PATH_9900" not in pub
          and "RAW_NON_DICT_ERR_CANARY_3322" not in pub
          and "已发生错误（详情见私有看板）" in pub)

    # Positive control: private board renders without crashing and keeps private heartbeat details
    orig_msg = intent_board.his_last_message
    intent_board.his_last_message = lambda **kw: {"ts": None, "files": 0, "scanned": 0}
    try:
        pri = intent_board.render(root, now=time.time(), private=True)
    finally:
        intent_board.his_last_message = orig_msg
    check("G6-7 positive control: private board renders safely with error detail",
          "RAW_TRACE_SECRET_PATH_9900" in pri and "PUBLIC_DIARY_OK" in pri)


# ------------------------------------------------------------------ G7: SEC-A2-10
def g7_degrade_watch_hardening():
    print("\n== G7 (SEC-A2-10): degrade_watch large logs, exit-code 2, & non-dict lines ==")
    think_dead = "执行。\n\n时间：快。\n\n执行。\n\n" + ("再试一次。" * 50)
    dead_events = [
        {"type": "assistant/message", "data": {
            "turn": 9999,
            "message": {"role": "assistant", "content": [{"type": "reasoning", "text": think_dead}]},
        }},
        {"type": "turn/end", "data": {"turn": 9999, "reason": {"kind": "completed"}}},
    ]

    # G7a: Uncompressed .jsonl > 1 MB with --tail-mb 1 must NOT be silently dropped!
    root_big_raw = os.path.join(_TMP_ROOT, "g7_big_raw")
    sess_raw = os.path.join(root_big_raw, "sess-big-raw")
    os.makedirs(sess_raw, exist_ok=True)
    raw_fp = os.path.join(sess_raw, "session.v4.jsonl")
    pad_line = json.dumps({"type": "user/message", "data": {"pad": "x" * 1024}}) + "\n"
    with open(raw_fp, "w", encoding="utf-8") as fh:
        for _ in range(1200):  # ~1.25 MB > 1 MB
            fh.write(pad_line)
        for ev in dead_events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    check("G7-0 uncompressed fixture exceeds 1 MB", os.path.getsize(raw_fp) > 1024 * 1024)
    res_raw = degrade_watch.scan_file(raw_fp, tail_mb=1)
    check("G7-1 large uncompressed .jsonl (>tail_mb) detects dead turn",
          res_raw is not None and res_raw[0]["dead"] == 1, res_raw)
    rc_raw = degrade_watch.main(["--root", root_big_raw, "--tail-mb", "1", "--quiet"])
    check("G7-2 main() returns exit 1 on large uncompressed .jsonl with dead turn",
          rc_raw == 1, rc_raw)

    # G7b: Single-frame .jsonl.zstd > 1 MB with --tail-mb 1 must NOT be silently dropped!
    if degrade_watch._zstd is not None:
        root_big_z = os.path.join(_TMP_ROOT, "g7_big_zstd")
        sess_z = os.path.join(root_big_z, "sess-big-zstd")
        os.makedirs(sess_z, exist_ok=True)
        z_fp = os.path.join(sess_z, "session.v4.jsonl.zstd")
        # Use incompressible high-entropy base64 so single zstd frame > 1.2 MB!
        parts = []
        for i in range(3600):
            chunk = base64.b64encode(os.urandom(360)).decode("ascii")
            parts.append(json.dumps({"type": "noop", "i": i, "d": chunk}))
        for ev in dead_events:
            parts.append(json.dumps(ev, ensure_ascii=False))
        payload = ("\n".join(parts) + "\n").encode("utf-8")
        comp = degrade_watch._zstd.ZstdCompressor(level=1).compress(payload)
        with open(z_fp, "wb") as fh:
            fh.write(comp)
        check("G7-3 single-frame .jsonl.zstd fixture exceeds 1 MB",
              os.path.getsize(z_fp) > 1024 * 1024, os.path.getsize(z_fp))
        res_z = degrade_watch.scan_file(z_fp, tail_mb=1)
        check("G7-4 large single-frame .jsonl.zstd (>tail_mb) widens window & detects dead=1",
              res_z is not None and res_z[0]["dead"] == 1, res_z)
        rc_z = degrade_watch.main(["--root", root_big_z, "--tail-mb", "1", "--quiet"])
        check("G7-5 main() returns exit 1 on large single-frame .jsonl.zstd with dead turn",
              rc_z == 1, rc_z)

        # G7c: Missing zstandard on .jsonl.zstd MUST return exit code 2 (NOT 1!)
        saved_zstd = degrade_watch._zstd
        degrade_watch._zstd = None
        try:
            rc_noz = degrade_watch.main(["--root", root_big_z, "--tail-mb", "1", "--quiet"])
        finally:
            degrade_watch._zstd = saved_zstd
        check("G7-6 missing zstandard returns documented exit code 2 (not false-alert 1)",
              rc_noz == 2, rc_noz)
    else:
        # Even without zstandard installed, test missing zstandard -> rc=2 on a magic-prefixed file!
        root_mz = os.path.join(_TMP_ROOT, "g7_mock_zstd")
        sess_mz = os.path.join(root_mz, "sess-mz")
        os.makedirs(sess_mz, exist_ok=True)
        with open(os.path.join(sess_mz, "session.v4.jsonl.zstd"), "wb") as fh:
            fh.write(degrade_watch._MAGIC + b"\x00" * 64)
        rc_noz = degrade_watch.main(["--root", root_mz, "--tail-mb", "1", "--quiet"])
        check("G7-6 missing zstandard returns documented exit code 2 (not false-alert 1)",
              rc_noz == 2, rc_noz)

    # G7d: Corrupt .jsonl.zstd (no valid magic) fails closed with exit code 2.
    root_badz = os.path.join(_TMP_ROOT, "g7_bad_zstd")
    sess_badz = os.path.join(root_badz, "sess-badz")
    os.makedirs(sess_badz, exist_ok=True)
    with open(os.path.join(sess_badz, "session.v4.jsonl.zstd"), "wb") as fh:
        fh.write(b"NOT_A_VALID_ZSTD_FRAME_AT_ALL" * 10)
    rc_badz = degrade_watch.main(["--root", root_badz, "--tail-mb", "1", "--quiet"])
    check("G7-7 corrupt .jsonl.zstd fails closed with exit code 2", rc_badz == 2, rc_badz)

    # G7e: Non-dict JSON lines & malformed line do NOT crash aggregate() or scan_file()!
    direct_turns = degrade_watch.aggregate([None, 123, "str", [1, 2], {"type": "turn/end", "data": "bad"}] + dead_events)
    check("G7-8 aggregate() tolerates non-dict events & non-dict data without AttributeError",
          9999 in direct_turns and direct_turns[9999]["reason"] == "completed", direct_turns)

    root_nondict = os.path.join(_TMP_ROOT, "g7_nondict")
    sess_nd = os.path.join(root_nondict, "sess-nd")
    os.makedirs(sess_nd, exist_ok=True)
    nd_fp = os.path.join(sess_nd, "session.v4.jsonl")
    with open(nd_fp, "w", encoding="utf-8") as fh:
        fh.write("null\n123\n[1, 2, 3]\n\"just-a-string\"\n{truncated json line\n")
        for ev in dead_events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    rc_nd = degrade_watch.main(["--root", root_nondict, "--tail-mb", "1", "--quiet"])
    check("G7-9 main() ignores non-dict/malformed lines and still detects dead turn (rc=1)",
          rc_nd == 1, rc_nd)

    # G7f: Positive control: healthy completed turn with text -> rc=0
    root_ok = os.path.join(_TMP_ROOT, "g7_ok")
    sess_ok = os.path.join(root_ok, "sess-ok")
    os.makedirs(sess_ok, exist_ok=True)
    with open(os.path.join(sess_ok, "session.v4.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "type": "assistant/message",
            "data": {"turn": 1, "message": {"role": "assistant", "content": [
                {"type": "reasoning", "text": think_dead},
                {"type": "text", "text": "正常回复正文"},
            ]}},
        }, ensure_ascii=False) + "\n")
        fh.write(json.dumps({"type": "turn/end", "data": {"turn": 1, "reason": {"kind": "completed"}}}) + "\n")
    rc_ok = degrade_watch.main(["--root", root_ok, "--tail-mb", "1", "--quiet"])
    check("G7-10 positive control: healthy session returns exit code 0", rc_ok == 0, rc_ok)


def _cleanup():
    for _ in range(6):
        shutil.rmtree(_TMP_ROOT, ignore_errors=True)
        if not os.path.exists(_TMP_ROOT):
            return
        gc.collect()
        time.sleep(0.1)


def main():
    try:
        g1_forgetting_concurrency_and_dirty_lock()
        g2_branches_cross_session_hardening()
        g3_evidence_metadata_leak_hardening()
        g4_tokens_nan_ttl_hardening()
        g5_export_perms_and_tmp_cleanup()
        g6_intent_board_privacy_and_heartbeat_hardening()
        g7_degrade_watch_hardening()
    finally:
        _cleanup()
    print("\n== summary: %d pass / %d fail ==" % (len(_PASS), len(_FAIL)))
    for name in _FAIL:
        print("  FAILED: " + name)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
