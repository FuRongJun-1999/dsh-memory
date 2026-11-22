# -*- coding: utf-8 -*-
"""Regression guards for #1010 (BUG-16) and #1011 (narrowed CONC-10 follow-ups).

Covers the 3 narrowed items layered on top of upstream's `_flush_window` /
`_flush_inflight` / `FlushLockBusy` concurrency guards:
  1. `_flush_gen` mid-load retry (`md_cg/mdcg.py`):
     - Completion of a flush while `_maybe_reload_index()` is inside unlocked
       `_load_index()` triggers a bounded retry so stale snapshots never
       revert fresh local writes (with negative mutation control).
     - Continuous `_flush_gen` advancement hits the bounded retry cap cleanly
       (returns False, zero infinite loop, zero stale install, preserves
       `_index_sig` for the next probe).
     - Failed flush rollback does not advance `_flush_gen`.
     - Concurrent newer `_dirty` write beats older `_flush_inflight` entry
       during reload replay.
  2. `flush_state()["pending_dirty"]` in-flight observability (`md_cg/mdcg.py`):
     - Counts `_flush_inflight` alongside `_dirty` under `_dirty_lock` so
       observers never see `pending_dirty == 0` while a batch is actively
       flushing, and never double-count after rollback.
  3. `BUG-16` (`ui/minimal/payload/{src,lib}/lib/console_web.mjs` +
     `ui/minimal/integrity.json`):
     - Byte parity between `src` and `lib` payload copies + SHA-256 parity
       against `ui/minimal/integrity.json`.
     - End-to-end Node behavioral checks on both copies: multi-byte UTF-8
       CSRF -> 403 (not 500 RangeError), malformed `Origin` -> 403 (not 500
       TypeError), valid call -> 200 with injected `ctx.logger` timing log,
       and 5-arg backward compatibility without `logger`.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from unittest import mock

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import fsutil  # noqa: E402
from md_cg.mdcg import MdCG  # noqa: E402

PASS = 0
FAIL = 0
FAILS = []

BODY = (
    "# 功能名：{title}\n"
    "# 生效条件：测试\n"
    "# 子功能：s\n"
    "# 执行：{act}\n"
    "# 验证方式：test\n"
    "# 不适用条件：无\n"
)


def check(name: str, cond: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {str(detail)[:260]}")
    return bool(cond)


def _wait(pred, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def test_flush_gen_mid_load_retry_and_mutation_control():
    print("== FG-1/2: _flush_gen mid-load completion triggers retry (with mutation control) ==")
    root = tempfile.mkdtemp(prefix="iss1011_fg_retry_")
    try:
        cg_a = MdCG(root, autoflush=1, async_flush=False)
        cg_a.add("seed_1", BODY.format(title="s", act="v1"),
                 layer="knowledge", tags=["v1"], importance=0.4,
                 verification_basis="test")
        cg_a.flush()
        cg_a.compact_index()
        cg_a.close()

        # High autoflush so `add` stages `v2_mid` in `_dirty` while `_flush_window` is False.
        cg_a = MdCG(root, autoflush=1000, async_flush=True)
        cg_a.add("seed_1", BODY.format(title="s", act="v2_mid"),
                 layer="knowledge", tags=["v2_mid"], importance=0.7,
                 verification_basis="test")
        pre_gen = cg_a._flush_gen

        # Another writer updates a different node so `_index_signature()` changes.
        cg_b = MdCG(root, autoflush=1, async_flush=False)
        cg_b.add("other_2", BODY.format(title="o2", act="o2"),
                 layer="knowledge", tags=["o2"], importance=0.5,
                 verification_basis="test")
        cg_b.flush()
        cg_b.close()

        # Intercept first `_load_index()`: read stale disk (`seed_1=v1`), THEN let
        # background flush drain `seed_1=v2_mid` to disk (clearing `_dirty` and
        # `_flush_inflight` and advancing `_flush_gen`) before returning stale `idx`.
        orig_load = cg_a._load_index
        load_calls = [0]

        def racing_load():
            load_calls[0] += 1
            idx = orig_load()
            if load_calls[0] == 1:
                cg_a.request_flush()
                _wait(lambda: cg_a._flush_gen > pre_gen, timeout=3.0)
            return idx

        cg_a._load_index = racing_load
        try:
            reloaded = cg_a._maybe_reload_index()
        finally:
            cg_a._load_index = orig_load

        node = (cg_a.index.get("nodes") or {}).get("seed_1") or {}
        check("FG-1a `_flush_gen` advance triggered retry reload",
              reloaded is True and load_calls[0] == 2 and cg_a._flush_gen > pre_gen,
              (reloaded, load_calls[0], pre_gen, cg_a._flush_gen))
        check("FG-1b retry reload preserved v2_mid and saw external other_2",
              node.get("tags") == ["v2_mid"]
              and "other_2" in (cg_a.index.get("nodes") or {}),
              (node, sorted((cg_a.index.get("nodes") or {}).keys())))

        # Negative / mutation control (FG-2): prove that WITHOUT `_flush_gen`
        # advancing across the exact same mid-load flush completion, stale v1
        # would overwrite memory.
        cg_a.add("seed_1", BODY.format(title="s", act="v3_ctrl"),
                 layer="knowledge", tags=["v3_ctrl"], importance=0.8,
                 verification_basis="test")
        cg_b2 = MdCG(root, autoflush=1, async_flush=False)
        cg_b2.add("other_3", BODY.format(title="o3", act="o3"),
                  layer="knowledge", tags=["o3"], importance=0.5,
                  verification_basis="test")
        cg_b2.flush()
        cg_b2.close()

        ctrl_gen = cg_a._flush_gen
        ctrl_calls = [0]

        def mutated_load():
            ctrl_calls[0] += 1
            idx = orig_load()
            if ctrl_calls[0] == 1:
                cg_a.flush()
                # Simulate missing `_flush_gen` bump after flush cleared `_dirty`/`_flush_inflight`.
                with cg_a._dirty_lock:
                    cg_a._flush_gen = ctrl_gen
            return idx

        cg_a._load_index = mutated_load
        try:
            ctrl_reloaded = cg_a._maybe_reload_index()
        finally:
            cg_a._load_index = orig_load
        ctrl_node = (cg_a.index.get("nodes") or {}).get("seed_1") or {}
        check("FG-2 mutation control: freezing _flush_gen causes stale reversion to v2_mid",
              ctrl_reloaded is True and ctrl_calls[0] == 1
              and ctrl_node.get("tags") == ["v2_mid"],
              (ctrl_reloaded, ctrl_calls[0], ctrl_node))
        cg_a.close()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_flush_gen_bounded_retry_and_failure_semantics():
    print("== FG-3/4/5: bounded retry cap, rollback gen invariance, dirty > inflight ==")
    root = tempfile.mkdtemp(prefix="iss1011_fg_bounds_")
    try:
        cg = MdCG(root, autoflush=1000, async_flush=False)
        cg.add("seed_b", BODY.format(title="b", act="v1"),
               layer="knowledge", tags=["v1"], importance=0.4,
               verification_basis="test")
        cg.flush()
        cg.compact_index()
        cg.add("seed_b", BODY.format(title="b", act="v2_local"),
               layer="knowledge", tags=["v2_local"], importance=0.7,
               verification_basis="test")

        # FG-3: `_flush_gen` advances on every `_load_index()` -> bounded at 4 tries, yields False.
        stale_snap = {
            "schema": cg.index.get("schema"),
            "nodes": {"seed_b": {"id": "seed_b", "tags": ["v1"], "bucket": None}},
            "buckets": {},
        }
        orig_load = cg._load_index
        calls = [0]

        def always_advancing_load():
            calls[0] += 1
            with cg._dirty_lock:
                cg._flush_gen += 1
            return {
                "schema": stale_snap["schema"],
                "nodes": dict(stale_snap["nodes"]),
                "buckets": {},
            }

        cg._index_sig = None
        cg._load_index = always_advancing_load
        try:
            reloaded = cg._maybe_reload_index()
        finally:
            cg._load_index = orig_load

        node_after = (cg.index.get("nodes") or {}).get("seed_b") or {}
        check("FG-3a continuous _flush_gen churn stops at 4 attempts and yields False",
              reloaded is False and calls[0] == 4,
              (reloaded, calls[0]))
        check("FG-3b retry exhaustion keeps local index intact and does not advance _index_sig",
              node_after.get("tags") == ["v2_local"] and cg._index_sig is None,
              (node_after.get("tags"), cg._index_sig))

        # FG-4: Failed flush rollback must NOT advance `_flush_gen`.
        gen_before_fail = cg._flush_gen
        with mock.patch.object(fsutil.ShardedLog, "append_many",
                               side_effect=OSError("disk busy")):
            raised = False
            try:
                cg.flush()
            except OSError:
                raised = True
        check("FG-4 failed flush does not advance _flush_gen and keeps item in _dirty",
              raised and cg._flush_gen == gen_before_fail
              and "seed_b" in cg._dirty and not cg._flush_inflight,
              (raised, gen_before_fail, cg._flush_gen, list(cg._dirty), cg._flush_inflight))

        # FG-5: When `_flush_inflight` holds older v2 and `_dirty` holds newer v3,
        # reload replay must keep newer v3 (never clobber with older in-flight).
        cg.flush()
        cg.add("seed_b", BODY.format(title="b", act="v3_newer"),
               layer="knowledge", tags=["v3_newer"], importance=0.9,
               verification_basis="test")
        cg._index_sig = None
        with cg._dirty_lock:
            cg._flush_inflight = {
                "seed_b": {"id": "seed_b", "tags": ["v2_older_inflight"], "bucket": None},
                "seed_inflight_only": {"id": "seed_inflight_only", "tags": ["only_if"], "bucket": None},
            }
        cg._load_index = lambda: {
            "schema": stale_snap["schema"],
            "nodes": dict(stale_snap["nodes"]),
            "buckets": {},
        }
        try:
            reloaded_5 = cg._maybe_reload_index()
        finally:
            cg._load_index = orig_load
            with cg._dirty_lock:
                cg._flush_inflight = {}
        nodes_5 = cg.index.get("nodes") or {}
        check("FG-5 newer _dirty beats older _flush_inflight while disjoint inflight survives",
              reloaded_5 is True
              and (nodes_5.get("seed_b") or {}).get("tags") == ["v3_newer"]
              and (nodes_5.get("seed_inflight_only") or {}).get("tags") == ["only_if"],
              (reloaded_5, nodes_5.get("seed_b"), nodes_5.get("seed_inflight_only")))
        cg.close()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_pending_dirty_counts_inflight():
    print("== PD-1..4: flush_state()['pending_dirty'] includes _flush_inflight ==")
    root = tempfile.mkdtemp(prefix="iss1011_pending_")
    try:
        cg = MdCG(root, autoflush=1, async_flush=True)
        entered = threading.Event()
        release = threading.Event()
        orig_flush_batch = cg._flush_batch
        paused_once = [False]

        def pause_first_flush(batch, superseded):
            if not paused_once[0]:
                paused_once[0] = True
                entered.set()
                release.wait(5.0)
            return orig_flush_batch(batch, superseded)

        cg._flush_batch = pause_first_flush
        cg.add("p1", BODY.format(title="p1", act="v1"),
               layer="knowledge", tags=["p1"], importance=0.5,
               verification_basis="test")
        check("PD-0 background flush entered in-flight window", entered.wait(3.0))

        with cg._dirty_lock:
            dirty_len = len(cg._dirty)
            inflight_len = len(cg._flush_inflight)
        st_mid = cg.flush_state()
        check("PD-1 pending_dirty == 1 while _dirty is empty and 1 batch is in-flight",
              dirty_len == 0 and inflight_len == 1 and st_mid["pending_dirty"] == 1,
              (dirty_len, inflight_len, st_mid))

        # Add a second write while first is still paused in-flight.
        cg.add("p2", BODY.format(title="p2", act="v1"),
               layer="knowledge", tags=["p2"], importance=0.5,
               verification_basis="test")
        st_both = cg.flush_state()
        check("PD-2 pending_dirty == 2 when 1 is in-flight and 1 is queued in _dirty",
              st_both["pending_dirty"] == 2, st_both)

        release.set()
        check("PD-3 pending_dirty drops to 0 after flush completes",
              _wait(lambda: cg.flush_state()["pending_dirty"] == 0, timeout=3.0)
              and cg._flush_gen >= 1,
              (cg.flush_state(), cg._flush_gen))
        cg.close()

        # PD-4: Failed sync flush rolls back to `_dirty` and clears `_flush_inflight` -> exact 1.
        cg2 = MdCG(root, autoflush=1000, async_flush=False)
        cg2.add("p3", BODY.format(title="p3", act="v1"),
                layer="knowledge", tags=["p3"], importance=0.5,
                verification_basis="test")
        with mock.patch.object(fsutil.ShardedLog, "append_many",
                               side_effect=OSError("io fail")):
            try:
                cg2.flush()
            except OSError:
                pass
        st_err = cg2.flush_state()
        check("PD-4 after rollback pending_dirty == 1 (no double-count, no false 0)",
              st_err["pending_dirty"] == 1 and not cg2._flush_inflight,
              (st_err, cg2._flush_inflight))
        cg2.flush()
        cg2.close()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_bug16_console_web_and_integrity():
    print("== BUG-16: console_web.mjs CSRF/Origin/logger & integrity.json parity ==")
    src_path = os.path.join(_REPO, "ui", "minimal", "payload", "src", "lib", "console_web.mjs")
    lib_path = os.path.join(_REPO, "ui", "minimal", "payload", "lib", "lib", "console_web.mjs")
    integ_path = os.path.join(_REPO, "ui", "minimal", "integrity.json")

    with open(src_path, "rb") as f:
        src_bytes = f.read()
    with open(lib_path, "rb") as f:
        lib_bytes = f.read()
    src_sha = hashlib.sha256(src_bytes).hexdigest().upper()
    lib_sha = hashlib.sha256(lib_bytes).hexdigest().upper()

    with open(integ_path, "r", encoding="utf-8") as f:
        integ = json.load(f)
    entries = {e["path"]: e["sha256"].upper() for e in integ.get("files", [])}
    check("B16-0 src & lib console_web.mjs match integrity.json SHA-256",
          src_bytes == lib_bytes
          and entries.get("src/lib/console_web.mjs") == src_sha
          and entries.get("lib/lib/console_web.mjs") == lib_sha,
          (src_sha, lib_sha, entries.get("src/lib/console_web.mjs"),
           entries.get("lib/lib/console_web.mjs")))

    node = shutil.which("node")
    if not node:
        print("  SKIP node not on PATH")
        return
    script = r"""
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const repo = process.argv[1];
const variants = [
  'ui/minimal/payload/src/lib/console_web.mjs',
  'ui/minimal/payload/lib/lib/console_web.mjs',
];

function makeReq(method, url, headers = {}, body = '') {
  const chunks = body ? [Buffer.from(body)] : [];
  return {
    method, url, headers,
    [Symbol.asyncIterator]() {
      let i = 0;
      return {
        next: async () => (i < chunks.length ? { value: chunks[i++], done: false } : { value: undefined, done: true }),
      };
    },
  };
}
function makeRes() {
  const state = { status: 200, body: '' };
  return {
    writeHead(s) { state.status = s; return this; },
    end(b) { state.body = b ? String(b) : ''; },
    _state: state,
  };
}

for (const rel of variants) {
  const { createConsoleHandler, installConsoleWeb } = await import(pathToFileURL(join(repo, rel)).href);
  const logs = [];
  let registered = null;
  const fakeMdcg = {
    isReady: () => true,
    bridge: { listTools: async () => [{ name: 'cg' }] },
    cg: async () => ({ ok: true }),
  };
  const fakeCtx = {
    logger: { info: (m) => logs.push(String(m)), warn: () => {} },
    get(k) {
      if (k === 'webServer') return {
        register(o) { if (o.path === '/plugins/lingshu') registered = o.handler; return () => {}; },
        tapIndex() { return () => {}; },
      };
      if (k === 'connection') return { admit: () => ({ ok: true }) };
      return undefined;
    },
  };
  installConsoleWeb(fakeCtx, { identity: 't', memory: {} }, [], fakeMdcg);
  assert.ok(registered, `console handler registered (${rel})`);

  const metaRes = makeRes();
  await registered(makeReq('GET', '/plugins/lingshu/meta', { host: 'localhost:3000' }), metaRes);
  assert.equal(metaRes._state.status, 200);
  const csrf = JSON.parse(metaRes._state.body).csrf;
  assert.equal(typeof csrf, 'string');
  assert.equal(csrf.length, 64);

  // Multi-byte UTF-8 CSRF with same UTF-16 `.length` (64 chars = 192 UTF-8 bytes) => 403, not 500 RangeError.
  const mbRes = makeRes();
  await registered(makeReq('POST', '/plugins/lingshu/call', {
    host: 'localhost:3000',
    origin: 'http://localhost:3000',
    'content-type': 'application/json',
    'x-lingshu-csrf': '中'.repeat(csrf.length),
  }, JSON.stringify({ tool: 'cg', args: { op: 'info' } })), mbRes);
  assert.equal(mbRes._state.status, 403, `${rel}: multi-byte CSRF must return 403, got ${mbRes._state.status}`);

  // Malformed Origin ('null' and invalid URL) => 403, not 500 TypeError.
  for (const badOrigin of ['null', 'not-a-valid-url']) {
    const badOriginRes = makeRes();
    await registered(makeReq('POST', '/plugins/lingshu/call', {
      host: 'localhost:3000',
      origin: badOrigin,
      'content-type': 'application/json',
      'x-lingshu-csrf': csrf,
    }, JSON.stringify({ tool: 'cg', args: { op: 'info' } })), badOriginRes);
    assert.equal(badOriginRes._state.status, 403, `${rel}: origin=${badOrigin} must return 403`);
  }

  // Valid call => 200 AND timing log emitted via injected ctx.logger (undefined ctx fixed).
  const okRes = makeRes();
  await registered(makeReq('POST', '/plugins/lingshu/call', {
    host: 'localhost:3000',
    origin: 'http://localhost:3000',
    'content-type': 'application/json',
    'x-lingshu-csrf': csrf,
  }, JSON.stringify({ tool: 'cg', args: { op: 'info' } })), okRes);
  assert.equal(okRes._state.status, 200, `${rel}: valid console call should 200`);
  assert.ok(logs.some((l) => l.includes('dsh-memory: ui-call cg:info')),
    `${rel}: timing log emitted: ${JSON.stringify(logs)}`);

  // Backward compatibility: omitting 6th logger arg still returns 200 cleanly.
  const hNoLogger = createConsoleHandler(fakeMdcg, { identity: 't', memory: {} }, {},
    () => ({ admit: () => ({ ok: true }) }), () => ({ any: true }));
  const m2 = makeRes();
  await hNoLogger(makeReq('GET', '/plugins/lingshu/meta', { host: 'localhost:3000' }), m2);
  const csrf2 = JSON.parse(m2._state.body).csrf;
  const r2 = makeRes();
  await hNoLogger(makeReq('POST', '/plugins/lingshu/call', {
    host: 'localhost:3000',
    origin: 'http://localhost:3000',
    'content-type': 'application/json',
    'x-lingshu-csrf': csrf2,
  }, JSON.stringify({ tool: 'cg', args: { op: 'info' } })), r2);
  assert.equal(r2._state.status, 200, `${rel}: 5-arg createConsoleHandler without logger should 200`);
}
console.log('BUG16_NODE_CHECKS_OK');
"""
    pr = subprocess.run(
        [node, "--input-type=module", "-e", script, _REPO],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=30,
    )
    check("B16-1 Node behavioral checks on src & lib console_web.mjs",
          pr.returncode == 0 and "BUG16_NODE_CHECKS_OK" in pr.stdout,
          (pr.returncode, pr.stdout[-200:], pr.stderr[-400:]))


def main() -> int:
    test_flush_gen_mid_load_retry_and_mutation_control()
    test_flush_gen_bounded_retry_and_failure_semantics()
    test_pending_dirty_counts_inflight()
    test_bug16_console_web_and_integrity()

    print()
    print("=" * 64)
    print(f"issue #1010/#1011 hardening suite: {PASS} passed / {FAIL} failed")
    for name in FAILS:
        print(f"  - {name}")
    print("=" * 64)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
