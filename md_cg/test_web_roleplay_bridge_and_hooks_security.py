# -*- coding: utf-8 -*-
"""Security regression guards for Round-3 Web/UI/Hooks hardening (SEC-A2-06/07/08).

Covers:
  - SEC-A2-06 (`src/index.ts`, `src/lib/roleplay_web.ts`):
      1. `installRoleplayWeb` mounted inside `ctx.inject(['connection', 'connection.authentication', 'webServer'], ...)`
         with `{ requireHostConnection: true }`.
      2. Handler entry enforces `connection.admit(req)` (fail-closed 503 when unavailable/error,
         401/403 on rejection, self-heals when connection becomes ready, supports sync/async admit,
         preserves standalone direct-call compatibility when no host connection exists).
      3. `sameOrigin` rejects `Origin: file://` with empty `Host` (`"" === ""` bypass) and non-HTTP(S) origins.
      4. Malformed `req.url` is handled inside `try/catch` and returns clean `400 invalid_request_url`.
      5. `validRoleId` rejects `.`, `..`, any `..` substring, leading punctuation, prototype keys, and malformed
         percent-encoding across all routes including `GET /api/translate` and `GET /api/history`.
      6. `requireEditKey` compares fixed-length SHA-256 digests with `crypto.timingSafeEqual`.
  - SEC-A2-07 (`ui/minimal/payload/web/client.js`, `ui/minimal/payload/lib/client.js`, `ui/minimal/integrity.json`):
      1. Fail-closed `ev.source` check (`!BRIDGE.frame || !BRIDGE.frame.contentWindow || ev.source !== BRIDGE.frame.contentWindow`)
         prevents unmount bypass after `onFrameRef(null)`.
      2. URL allowlist enforces same-origin `/plugins/lingshu/` prefix (blocking traversal, encoded dot-segments,
         cross-origin, protocol-relative, and non-HTTP schemes) and method allowlist (`GET`/`POST` case-normalized).
      3. `web/client.js` and `lib/client.js` match their SHA-256 entries in `ui/minimal/integrity.json`.
  - SEC-A2-08 (`src/hooks.ts`):
      1. `renderIdentityAnchors` uses explicit `IDENTITY_LAYERS = new Set(['self', 'anchor'])` so `rejected` and
         `structural` layers are never injected into identity anchors.
      2. `normalizeReadItems` redacts with `redactKeepPlaceholders` BEFORE `truncateSafe(..., READ_PREVIEW_MAX)`
         so credentials straddling char 300 are redacted instead of leaking half-prefixes and emoji surrogate pairs
         are never split, while preserving `tags` for `recallSkipItem`.
      3. `knowItems` in `installMemoryHooks` filters with `recallSkipItem(it, sessionUnitOf(sid))` so `rejected`,
         `structural`, `self`, `anchor`, and `audit`/`audit_trace` entries never bypass into daily `knowText`.

Run: python -X utf8 -m md_cg.test_web_roleplay_bridge_and_hooks_security
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

PASS = 0
FAIL = 0
FAILS: list[str] = []


def check(name: str, cond: bool, detail: object = "") -> bool:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {str(detail)[:300]}")
    return bool(cond)


def _read_text(rel: str) -> str:
    with open(os.path.join(_REPO, rel), "r", encoding="utf-8") as fh:
        return fh.read()


def test_static_and_integrity() -> None:
    print("== Static & Integrity Checks (SEC-A2-06 / 07 / 08) ==")
    idx_src = _read_text("src/index.ts")
    rp_src = _read_text("src/lib/roleplay_web.ts")
    hooks_src = _read_text("src/hooks.ts")
    client_web_path = os.path.join(_REPO, "ui", "minimal", "payload", "web", "client.js")
    client_lib_path = os.path.join(_REPO, "ui", "minimal", "payload", "lib", "client.js")
    integ_path = os.path.join(_REPO, "ui", "minimal", "integrity.json")

    inject_match = re.search(
        r"ctx\.inject\(\['connection',\s*'connection\.authentication',\s*'webServer'\],\s*\(webCtx\)\s*=>\s*\{(.*?)\n\s*\}\)",
        idx_src,
        flags=re.S,
    )
    check(
        "S06-1 src/index.ts mounts installRoleplayWeb inside connection.authentication inject",
        bool(inject_match)
        and "installRoleplayWeb(webCtx, capability, config, disposers, mdcg, { requireHostConnection: true })"
        in inject_match.group(1)
        and "await installRoleplayWeb(ctx," not in idx_src,
        "missing inject mount or legacy unguarded mount still present",
    )
    check(
        "S06-2 roleplay_web uses timingSafeEqual + createHash for requireEditKey",
        "timingSafeEqual" in rp_src and "createHash('sha256')" in rp_src and "h === EDIT_KEY" not in rp_src,
    )
    check(
        "S06-3 roleplay_web enforces validRoleId on >= 8 sites (including GET /translate and GET /history)",
        rp_src.count("if (!validRoleId(") >= 8,
        rp_src.count("if (!validRoleId("),
    )

    with open(client_web_path, "rb") as fw:
        web_bytes = fw.read()
    with open(client_lib_path, "rb") as fl:
        lib_bytes = fl.read()
    web_sha = hashlib.sha256(web_bytes).hexdigest().upper()
    lib_sha = hashlib.sha256(lib_bytes).hexdigest().upper()
    with open(integ_path, "r", encoding="utf-8") as fi:
        integ = json.load(fi)
    integ_map = {e["path"]: str(e["sha256"]).upper() for e in integ.get("files", [])}
    check(
        "S07-1 ui/minimal/payload/{web,lib}/client.js match ui/minimal/integrity.json SHA-256",
        integ_map.get("web/client.js") == web_sha and integ_map.get("lib/client.js") == lib_sha,
        (web_sha, integ_map.get("web/client.js"), lib_sha, integ_map.get("lib/client.js")),
    )
    web_text = web_bytes.decode("utf-8")
    lib_text = lib_bytes.decode("utf-8")
    fail_closed_line = "if (!BRIDGE.frame || !BRIDGE.frame.contentWindow || ev.source !== BRIDGE.frame.contentWindow) return;"
    check(
        "S07-2 web/client.js and compiled lib/client.js both have fail-closed source & prefix guard",
        fail_closed_line in web_text
        and fail_closed_line in lib_text
        and "/plugins/lingshu/" in web_text
        and "/plugins/lingshu/" in lib_text,
    )

    check(
        "S08-1 src/hooks.ts defines IDENTITY_LAYERS=['self','anchor'] and uses it in renderIdentityAnchors",
        "const IDENTITY_LAYERS = new Set(['self', 'anchor'])" in hooks_src
        and "if (!IDENTITY_LAYERS.has(layer)) continue" in hooks_src,
    )
    check(
        "S08-2 src/hooks.ts normalizeReadItems uses redactKeepPlaceholders + truncateSafe (no raw preview.slice)",
        "preview.slice(0, READ_PREVIEW_MAX)" not in hooks_src
        and "truncateSafe(safePreview, READ_PREVIEW_MAX)" in hooks_src,
    )


def test_node_runtime_behaviors() -> None:
    print("== Node Runtime Behavioral Checks (SEC-A2-06 / 07 / 08) ==")
    node = shutil.which("node")
    if not node:
        print("  SKIP node not on PATH")
        return

    node_script = r"""
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync, rmSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import vm from 'node:vm';
import moduleApi from 'node:module';

const repo = process.argv[1];

// Support both built `lib/` (Node 22 in CI after `npm run build`) and direct TS source (Node 24 locally).
const builtRoleplay = join(repo, 'lib', 'lib', 'roleplay_web.js');
const builtHooks = join(repo, 'lib', 'hooks.js');

if (!existsSync(builtHooks) && typeof moduleApi.registerHooks === 'function') {
  moduleApi.registerHooks({
    resolve(specifier, context, nextResolve) {
      if (specifier.startsWith('./') && specifier.endsWith('.js') && context.parentURL && context.parentURL.endsWith('.ts')) {
        const parentPath = fileURLToPath(context.parentURL);
        const tsCandidate = join(dirname(parentPath), specifier.slice(0, -3) + '.ts');
        if (existsSync(tsCandidate)) {
          return { url: pathToFileURL(tsCandidate).href, shortCircuit: true };
        }
      }
      return nextResolve(specifier, context);
    },
  });
}

const rpUrl = pathToFileURL(existsSync(builtRoleplay) ? builtRoleplay : join(repo, 'src', 'lib', 'roleplay_web.ts')).href;
const { installRoleplayWeb } = await import(rpUrl);

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

function hasLoneSurrogate(s) {
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff) {
      const n = i + 1 < s.length ? s.charCodeAt(i + 1) : 0;
      if (!(n >= 0xdc00 && n <= 0xdfff)) return true;
      i++;
    } else if (c >= 0xdc00 && c <= 0xdfff) {
      return true;
    }
  }
  return false;
}

// =========================================================================
// SEC-A2-06: roleplay_web host admission, sameOrigin, new URL, validRoleId, timingSafeEqual
// =========================================================================
{
  const dir = mkdtempSync(join(tmpdir(), 'dsh-r3-rp-'));
  const prevEditKey = process.env.ROLEPLAY_EDIT_KEY;
  process.env.ROLEPLAY_EDIT_KEY = 'dummy-edit-key-example';
  try {
    const metaDir = join(dir, 'roleplay_data', 'roleplay');
    mkdirSync(metaDir, { recursive: true });
    writeFileSync(join(metaDir, '_roles.json'), JSON.stringify({
      'protocol-guide': { name: 'Guide', scenario: 'test scenario', first_mes: 'hello' },
    }), 'utf8');

    let handler = null;
    let hostConn = undefined;
    const capCalls = [];
    const graphCalls = [];
    const ctx = {
      logger: { info: () => {}, warn: () => {} },
      get(key) {
        if (key === 'webServer') return this.webServer;
        if (key === 'connection') return hostConn;
        return undefined;
      },
      webServer: {
        register(opts) { handler = opts.handler; return () => {}; },
        tapIndex() { return () => {}; },
      },
    };
    const cap = {
      isReady: () => true,
      async callTool(name, args) {
        capCalls.push({ name, args });
        return { content: [{ type: 'text', text: JSON.stringify({ reply: 'ok', route: 'engine' }) }], isError: false };
      },
    };
    const mdcg = {
      isReady: () => true,
      async writeTranscript(...args) { graphCalls.push(args); },
      async writeRole(...args) { graphCalls.push(args); },
      async write(...args) { graphCalls.push(args); },
    };

    await installRoleplayWeb(ctx, cap, { dbPath: join(dir, 'test.db') }, [], mdcg, { requireHostConnection: true });
    assert.ok(handler, 'roleplay handler registered');

    // 1. Fail-closed 503 when host connection not yet ready
    for (const [m, u, h, b] of [
      ['GET', '/roleplay', {}, ''],
      ['GET', '/roleplay/api/roles', {}, ''],
      ['POST', '/roleplay/api/chat', { 'content-type': 'application/json' }, JSON.stringify({ role_id: 'protocol-guide', message: 'hi' })],
    ]) {
      const r = makeRes();
      await handler(makeReq(m, u, h, b), r);
      assert.equal(r._state.status, 503, `${m} ${u} without connection must 503, got ${r._state.status}`);
    }
    assert.equal(capCalls.length, 0, 'no capability calls while host connection absent');
    assert.equal(graphCalls.length, 0, 'no mdcg writes while host connection absent');

    // 2. Host connection rejects unauthenticated (401) and untrusted (403) and error (503)
    hostConn = { admit: () => ({ rejection: 401 }) };
    for (const [m, u, h, b] of [
      ['GET', '/roleplay', {}, ''],
      ['GET', '/roleplay/api/roles', {}, ''],
      ['POST', '/roleplay/api/chat', { 'content-type': 'application/json' }, JSON.stringify({ role_id: 'protocol-guide', message: 'hi' })],
    ]) {
      const r = makeRes();
      await handler(makeReq(m, u, h, b), r);
      assert.equal(r._state.status, 401, `${m} ${u} unauthenticated must 401, got ${r._state.status}`);
    }
    assert.equal(capCalls.length, 0, 'no capability calls on 401');

    hostConn = { admit: async () => ({ rejection: 403 }) };
    {
      const r = makeRes();
      await handler(makeReq('GET', '/roleplay/api/roles', {}), r);
      assert.equal(r._state.status, 403, 'async rejection 403 must block');
    }

    hostConn = { admit: () => { throw new Error('auth down'); } };
    {
      const r = makeRes();
      await handler(makeReq('GET', '/roleplay/api/roles', {}), r);
      assert.equal(r._state.status, 503, 'throwing admit must fail-closed 503');
    }

    // 3. Self-heal once host connection admits (async Promise)
    hostConn = { admit: async () => ({ ok: true }) };
    {
      const r = makeRes();
      await handler(makeReq('GET', '/roleplay/api/roles', { host: 'localhost:3000', origin: 'http://localhost:3000' }), r);
      assert.equal(r._state.status, 200, 'authenticated same-origin GET /api/roles must 200');
      assert.equal(JSON.parse(r._state.body).roles.length, 1);
    }
    {
      const r = makeRes();
      await handler(makeReq('POST', '/roleplay/api/chat', {
        host: 'localhost:3000',
        origin: 'http://localhost:3000',
        'content-type': 'application/json',
      }, JSON.stringify({ role_id: 'protocol-guide', message: 'hello' })), r);
      assert.equal(r._state.status, 200, 'authenticated POST /api/chat must 200');
      assert.equal(capCalls.length, 1);
    }

    // 4. sameOrigin blocks Origin: file:// + empty Host ("" === "" bypass) and non-HTTP schemes
    for (const [label, hdrs] of [
      ['file:// + empty host', { origin: 'file://', host: '' }],
      ['file:// + omitted host', { origin: 'file://' }],
      ['file:///etc/passwd + host', { origin: 'file:///etc/passwd', host: 'localhost:3000' }],
      ['http origin + empty host', { origin: 'http://localhost:3000', host: '' }],
      ['null origin + host', { origin: 'null', host: 'localhost:3000' }],
      ['cross origin', { origin: 'http://evil.example', host: 'localhost:3000' }],
      ['cross-site uppercase', { 'sec-fetch-site': 'CROSS-SITE', host: 'localhost:3000' }],
    ]) {
      const r = makeRes();
      await handler(makeReq('GET', '/roleplay/api/roles', hdrs), r);
      assert.equal(r._state.status, 403, `sameOrigin/admit must reject ${label}, got ${r._state.status}`);
    }

    // 5. Malformed req.url returns clean 400 (no unhandled rejection)
    for (const badUrl of ['http://[::1', '//[::1']) {
      const r = makeRes();
      await handler(makeReq('GET', badUrl, { host: 'localhost:3000' }), r);
      assert.equal(r._state.status, 400, `malformed req.url ${badUrl} must 400, got ${r._state.status}`);
      assert.equal(JSON.parse(r._state.body).error, 'invalid_request_url');
    }

    // 6. validRoleId rejects '.', '..', 'a..b', '.dot', '-lead', '__proto__', 'constructor' across ALL routes
    const editAuth = { host: 'localhost:3000', 'x-edit-key': 'dummy-edit-key-example', 'content-type': 'application/json' };
    for (const badRole of ['.', '..', 'a..b', '.hidden', '-dash', '__proto__', 'constructor', 'prototype']) {
      const rChat = makeRes();
      await handler(makeReq('POST', '/roleplay/api/chat', editAuth, JSON.stringify({ role_id: badRole, message: 'hi' })), rChat);
      assert.equal(rChat._state.status, 400, `POST /chat bad role_id=${badRole} must 400, got ${rChat._state.status}`);

      const rCreate = makeRes();
      await handler(makeReq('POST', '/roleplay/api/roles', editAuth, JSON.stringify({ role_id: badRole, name: 'x' })), rCreate);
      assert.equal(rCreate._state.status, 400, `POST /roles bad role_id=${badRole} must 400, got ${rCreate._state.status}`);

      const rTrans = makeRes();
      await handler(makeReq('GET', `/roleplay/api/translate?role_id=${encodeURIComponent(badRole)}`, editAuth), rTrans);
      assert.equal(rTrans._state.status, 400, `GET /translate bad role_id=${badRole} must 400, got ${rTrans._state.status}`);
      assert.deepEqual(JSON.parse(rTrans._state.body).pairs, []);

      const rHist = makeRes();
      await handler(makeReq('GET', `/roleplay/api/history?role_id=${encodeURIComponent(badRole)}`, editAuth), rHist);
      assert.equal(rHist._state.status, 400, `GET /history bad role_id=${badRole} must 400, got ${rHist._state.status}`);
      assert.deepEqual(JSON.parse(rHist._state.body).history, []);
    }

    // Malformed percent-encoding in /roles/:role/items -> 400 (not 500)
    {
      const rBadEnc = makeRes();
      await handler(makeReq('GET', '/roleplay/api/roles/%E0%A4%A/items', editAuth), rBadEnc);
      assert.equal(rBadEnc._state.status, 400, `bad percent-encoding must 400, got ${rBadEnc._state.status}`);
    }

    // Valid role ids still pass GET /translate and GET /history
    for (const goodRole of ['protocol-guide', 'role_1.v2']) {
      const rT = makeRes();
      await handler(makeReq('GET', `/roleplay/api/translate?role_id=${encodeURIComponent(goodRole)}`, editAuth), rT);
      assert.equal(rT._state.status, 200, `valid role_id=${goodRole} GET /translate must 200`);
      const rH = makeRes();
      await handler(makeReq('GET', `/roleplay/api/history?role_id=${encodeURIComponent(goodRole)}`, editAuth), rH);
      assert.equal(rH._state.status, 200, `valid role_id=${goodRole} GET /history must 200`);
    }

    // 7. requireEditKey constant-time check handles different lengths & multi-byte UTF-8 safely (403, not 500)
    for (const badKey of ['', 'short', 'dummy-edit-key-example-extra', '中'.repeat('dummy-edit-key-example'.length)]) {
      const r = makeRes();
      await handler(makeReq('GET', '/roleplay/api/history?role_id=protocol-guide', { host: 'localhost:3000', 'x-edit-key': badKey }), r);
      assert.equal(r._state.status, 403, `wrong edit key ${JSON.stringify(badKey)} must 403, got ${r._state.status}`);
    }

    // 8. Standalone direct call without requireHostConnection or ctx.connection remains compatible
    let standaloneHandler = null;
    const standaloneCtx = {
      logger: { info: () => {}, warn: () => {} },
      get(key) { return key === 'webServer' ? this.webServer : undefined; },
      webServer: {
        register(opts) { standaloneHandler = opts.handler; return () => {}; },
        tapIndex() { return () => {}; },
      },
    };
    await installRoleplayWeb(standaloneCtx, null, { dbPath: join(dir, 'test.db') }, []);
    const rStandalone = makeRes();
    await standaloneHandler(makeReq('GET', '/roleplay/api/roles', {}), rStandalone);
    assert.equal(rStandalone._state.status, 200, 'standalone without connection keeps compatibility');
  } finally {
    if (prevEditKey !== undefined) process.env.ROLEPLAY_EDIT_KEY = prevEditKey;
    else delete process.env.ROLEPLAY_EDIT_KEY;
    rmSync(dir, { recursive: true, force: true });
  }
}
console.log('SEC_A2_06_OK');

// =========================================================================
// SEC-A2-07: ui/minimal/payload/lib/client.js postMessage bridge hardening
// =========================================================================
{
  const bundleCode = readFileSync(join(repo, 'ui', 'minimal', 'payload', 'lib', 'client.js'), 'utf8');
  let registration = null;
  let messageListener = null;
  const fetchCalls = [];
  const winMock = {
    __ModuleLoader__: { load(r) { registration = r; } },
    location: { origin: 'http://127.0.0.1:3000' },
    addEventListener(type, fn) { if (type === 'message') messageListener = fn; },
  };
  const fetchMock = async (url, init) => {
    fetchCalls.push({ url, init });
    return { ok: true, status: 200, text: async () => '{"ok":true}' };
  };
  new vm.Script(bundleCode, { filename: 'lib/client.js' }).runInNewContext({
    window: winMock,
    fetch: fetchMock,
    URL,
    Set,
    Object,
    String,
    Array,
  });
  assert.ok(registration, 'client bundle loaded');
  let capturedPanel = null;
  let capturedRef = null;
  const reactMock = {
    createElement(tag, props) {
      if (tag === 'iframe' && props && typeof props.ref === 'function') capturedRef = props.ref;
      return { tag, props };
    },
  };
  const plugin = registration.factory((name) => {
    if (name === 'react') return reactMock;
    throw new Error('unexpected module ' + name);
  });
  plugin.apply({
    slots: {
      inject(_name, fn) { fn(); },
      register(meta, comp) { if (meta.name === 'main') capturedPanel = comp; return () => {}; },
    },
  });
  assert.ok(capturedPanel, 'Panel slot registered');
  capturedPanel();
  assert.ok(capturedRef, 'onFrameRef captured');

  const frameReplies = [];
  const frameWin = { postMessage(msg) { frameReplies.push(msg); } };
  const attackerWin = { postMessage() {} };
  const frameEl = { contentWindow: frameWin };

  // Mount panel -> binds message listener
  capturedRef(frameEl);
  assert.ok(messageListener, 'message listener registered on mount');

  // 1. Valid GET /plugins/lingshu/meta from frameWin -> forwarded
  messageListener({ source: frameWin, data: { __lingshu: 'req', id: 1, url: '/plugins/lingshu/meta', method: 'GET' } });
  await new Promise((r) => setTimeout(r, 15));
  assert.equal(fetchCalls.length, 1, 'valid GET /plugins/lingshu/meta must fetch');
  assert.equal(fetchCalls[0].url, '/plugins/lingshu/meta');
  assert.equal(fetchCalls[0].init.method, 'GET');
  assert.equal(frameReplies.length, 1);
  assert.equal(frameReplies[0].ok, true);

  // 2. Valid lowercase 'post' /plugins/lingshu/call -> normalized to POST
  messageListener({
    source: frameWin,
    data: { __lingshu: 'req', id: 2, url: '/plugins/lingshu/call', method: 'post', body: '{}', headers: { 'Content-Type': 'application/json' } },
  });
  await new Promise((r) => setTimeout(r, 15));
  assert.equal(fetchCalls.length, 2, 'valid POST /plugins/lingshu/call must fetch');
  assert.equal(fetchCalls[1].init.method, 'POST');

  // 3. Wrong ev.source while mounted -> silently dropped, zero fetch
  const beforeWrongSrc = fetchCalls.length;
  messageListener({ source: attackerWin, data: { __lingshu: 'req', id: 3, url: '/plugins/lingshu/meta', method: 'GET' } });
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(fetchCalls.length, beforeWrongSrc, 'wrong ev.source must not fetch');

  // 4. Unmount bypass (onFrameRef(null)) -> fail-closed for ANY sender (attacker, old frame, null)
  capturedRef(null);
  const beforeUnmount = fetchCalls.length;
  for (const src of [attackerWin, frameWin, null, undefined]) {
    messageListener({ source: src, data: { __lingshu: 'req', id: 4, url: '/plugins/lingshu/meta', method: 'GET' } });
  }
  await new Promise((r) => setTimeout(r, 15));
  assert.equal(fetchCalls.length, beforeUnmount, 'unmounted bridge must fail closed (zero fetch)');

  // 5. Detached iframe (contentWindow === null) -> fail-closed
  capturedRef({ contentWindow: null });
  messageListener({ source: null, data: { __lingshu: 'req', id: 5, url: '/plugins/lingshu/meta', method: 'GET' } });
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(fetchCalls.length, beforeUnmount, 'detached iframe must fail closed');

  // 6. Remount and verify URL allowlist & method allowlist
  capturedRef(frameEl);
  frameReplies.length = 0;
  const blockedUrls = [
    '/roleplay/api/chat',
    '/plugins/lingshu/../roleplay/api/chat',
    '/plugins/lingshu/%2e%2e/roleplay/api/chat',
    '/plugins/lingshu/..\\roleplay/api/chat',
    'https://evil.example/plugins/lingshu/meta',
    '//evil.example/plugins/lingshu/meta',
    'javascript:alert(1)',
    'http://user:pass@127.0.0.1:3000/plugins/lingshu/meta',
  ];
  for (let i = 0; i < blockedUrls.length; i++) {
    messageListener({ source: frameWin, data: { __lingshu: 'req', id: 100 + i, url: blockedUrls[i], method: 'GET' } });
  }
  for (const badMethod of ['DELETE', 'PUT', 'PATCH', 'HEAD', 'OPTIONS']) {
    messageListener({ source: frameWin, data: { __lingshu: 'req', id: 200, url: '/plugins/lingshu/call', method: badMethod } });
  }
  await new Promise((r) => setTimeout(r, 15));
  assert.equal(fetchCalls.length, beforeUnmount, 'blocked URLs and methods must trigger ZERO fetch calls');
  assert.ok(frameReplies.length === blockedUrls.length + 5, `expected error replies for all blocked calls, got ${frameReplies.length}`);
  assert.ok(frameReplies.slice(0, blockedUrls.length).every((r) => r.error === 'url_not_allowed' || r.error === 'invalid_url'));
  assert.ok(frameReplies.slice(blockedUrls.length).every((r) => r.error === 'method_not_allowed'));
}
console.log('SEC_A2_07_OK');

// =========================================================================
// SEC-A2-08: src/hooks.ts identity anchors, normalizeReadItems, knowItems filtering
// =========================================================================
{
  const hooksUrl = pathToFileURL(existsSync(builtHooks) ? builtHooks : join(repo, 'src', 'hooks.ts')).href;
  const { renderIdentityAnchors, normalizeReadItems, installMemoryHooks } = await import(hooksUrl);

  // 1. renderIdentityAnchors NEVER injects rejected or structural layers
  const mixedIdentity = {
    items: [
      { layer: 'rejected', preview: 'FALSIFIED_REJECTED_MEMORY_POISON' },
      { layer: 'structural', preview: 'INTERNAL_STRUCTURAL_AUDIT_RECORD' },
      { layer: 'self', preview: 'VALID_SELF_IDENTITY_ANCHOR' },
      { layer: 'anchor', preview: 'VALID_ANCHOR_NODE' },
      { layer: 'knowledge', preview: 'ORDINARY_KNOWLEDGE' },
    ],
  };
  const idOut = renderIdentityAnchors(mixedIdentity);
  assert.ok(idOut.includes('VALID_SELF_IDENTITY_ANCHOR'), 'self layer kept');
  assert.ok(idOut.includes('VALID_ANCHOR_NODE'), 'anchor layer kept');
  assert.ok(!idOut.includes('FALSIFIED_REJECTED_MEMORY_POISON'), 'rejected layer MUST NOT enter identity anchors');
  assert.ok(!idOut.includes('INTERNAL_STRUCTURAL_AUDIT_RECORD'), 'structural layer MUST NOT enter identity anchors');
  assert.equal(
    renderIdentityAnchors({
      items: [
        { layer: 'rejected', preview: 'only rejected' },
        { layer: 'structural', preview: 'only structural' },
      ],
    }),
    '',
    'payload with only rejected/structural must produce empty identity block',
  );

  // 2. normalizeReadItems redacts BEFORE truncateSafe (straddling char 300) + surrogate-safe + preserves tags
  const dummySk = 'sk-' + 'fake' + '0123456789abcdef';
  const straddleSk = 'A'.repeat(288) + ' ' + dummySk + ' tail';
  const straddleSkTight = 'A'.repeat(293) + ' ' + dummySk + ' tail';
  const straddlePhone = 'B'.repeat(290) + ' ' + '13800138000' + ' end';
  const straddleEmoji = 'a'.repeat(299) + '😊' + 'tail';
  const norm = normalizeReadItems({
    results: [
      { node: { id: 'k_sk', content: straddleSk, frontmatter: { layer: 'knowledge', tags: ['fact'] } }, score: 0.9 },
      { node: { id: 'k_sk2', content: straddleSkTight, frontmatter: { layer: 'knowledge', tags: ['fact'] } }, score: 0.85 },
      { node: { id: 'k_ph', content: straddlePhone, frontmatter: { layer: 'knowledge', tags: ['fact'] } }, score: 0.8 },
      { node: { id: 'k_em', content: straddleEmoji, frontmatter: { layer: 'knowledge', tags: ['emoji'] } }, score: 0.7 },
      { node: { id: 'k_aud', content: 'AUDIT_TRACE_TEXT', frontmatter: { layer: 'knowledge', tags: ['audit_trace'] } }, score: 0.6 },
    ],
  });
  assert.equal(norm.length, 5);
  assert.ok(!String(norm[0].preview).includes('sk-fake'), `straddling API key prefix leaked: ${String(norm[0].preview).slice(-30)}`);
  assert.ok(String(norm[0].preview).includes('[已过滤:API密钥]'), `straddling API key must be redacted before slice`);
  assert.ok(!String(norm[1].preview).includes('sk-fake'), `tight straddling API key prefix leaked: ${String(norm[1].preview).slice(-20)}`);
  assert.ok(String(norm[1].preview).includes('[已过滤:'), `tight straddling API key must be redacted before slice`);
  assert.ok(!String(norm[2].preview).includes('13800'), `straddling phone prefix leaked: ${String(norm[2].preview).slice(-20)}`);
  assert.ok(String(norm[2].preview).includes('[已过滤:手机号]'), 'phone redacted before slice');
  assert.equal(hasLoneSurrogate(String(norm[3].preview)), false, 'normalizeReadItems must not split emoji surrogate pair');
  assert.equal(String(norm[3].preview).length, 299, 'emoji at index 299-300 retreats to clean 299 code units');
  assert.deepEqual(norm[4].tags, ['audit_trace'], 'frontmatter tags preserved for recallSkipItem');

  // 3. End-to-end installMemoryHooks: knowItems filtered by recallSkipItem & identity anchors filtered
  const assembleHandlers = [];
  const sessionHandlers = [];
  const ctx = {
    logger: { info: () => {}, warn: () => {} },
    on(ev, fn) {
      if (ev === 'system-prompt/assemble') assembleHandlers.push(fn);
      else if (ev === 'session/event') sessionHandlers.push(fn);
    },
  };
  const readPayload = {
    results: [
      { node: { id: 'bad_rej', content: 'KNOW_REJECTED_LEAK', frontmatter: { layer: 'rejected', tags: [] } }, score: 0.99 },
      { node: { id: 'bad_str', content: 'KNOW_STRUCTURAL_LEAK', frontmatter: { layer: 'structural', tags: [] } }, score: 0.98 },
      { node: { id: 'bad_aud', content: 'KNOW_AUDIT_TAG_LEAK', frontmatter: { layer: 'knowledge', tags: ['audit_trace'] } }, score: 0.97 },
      { node: { id: 'bad_self', content: 'KNOW_SELF_LEAK', frontmatter: { layer: 'self', tags: [] } }, score: 0.96 },
      { node: { id: 'good_k1', content: straddleSk, frontmatter: { layer: 'knowledge', tags: ['fact'] } }, score: 0.95 },
      { node: { id: 'good_k2', content: 'GOOD_KNOWLEDGE_FACT', frontmatter: { layer: 'knowledge', tags: ['fact'] } }, score: 0.94 },
    ],
  };
  const graph = {
    isReady: () => true,
    async timeline(_limit, extra) {
      if (extra && extra.session) {
        return { count: 1, limit: 4, items: [{ id: 't1', layer: 'contextual', preview: 'DAILY_TIMELINE_OK' }] };
      }
      return {
        count: 3, limit: 9,
        items: [
          { id: 'id_rej', layer: 'rejected', preview: 'IDENTITY_REJECTED_POISON' },
          { id: 'id_str', layer: 'structural', preview: 'IDENTITY_STRUCTURAL_POISON' },
          { id: 'id_self', layer: 'self', preview: 'IDENTITY_SELF_OK' },
        ],
      };
    },
    async read() { return readPayload; },
    async remember() { return { ok: true }; },
    async sessionRecall() { return { ok: true, recent: [] }; },
    async recentAdd() { return { ok: true }; },
  };
  const auditDir = mkdtempSync(join(tmpdir(), 'dsh-r3-hooks-'));
  try {
    installMemoryHooks(ctx, graph, {
      userMessage: true, assistantMessage: false, toolResult: false,
      importance: 0.6, autoRecall: true, autoRecallLimit: 4, autoRecallIdentity: true,
      desensitize: true, auditPath: join(auditDir, 'audit.json'),
      contextWindow: { enabled: false, turns: 5 },
    });

    // Feed user message in daily session so lastUserText triggers graph.read()
    sessionHandlers[0]({ id: 'sess_daily_1' }, {
      type: 'user/message',
      data: { source: { kind: 'user' }, content: [{ type: 'text', text: 'check recall filtering' }] },
    });
    const assemblyDaily = { contexts: [], variables: {} };
    await assembleHandlers[0](assemblyDaily, { agent: { session: { id: 'sess_daily_1' } } }, async () => assemblyDaily);

    const recallBlock = assemblyDaily.contexts.find((c) => c.name === 'lingshu:auto-recall')?.text ?? '';
    assert.ok(recallBlock.includes('GOOD_KNOWLEDGE_FACT'), 'valid knowledge fact injected');
    assert.ok(!recallBlock.includes('KNOW_REJECTED_LEAK'), 'rejected must not enter knowText');
    assert.ok(!recallBlock.includes('KNOW_STRUCTURAL_LEAK'), 'structural must not enter daily knowText');
    assert.ok(!recallBlock.includes('KNOW_AUDIT_TAG_LEAK'), 'audit_trace must not enter daily knowText');
    assert.ok(!recallBlock.includes('KNOW_SELF_LEAK'), 'self must not enter knowText');
    assert.ok(!recallBlock.includes('sk-fake'), 'straddling credential must not leak into auto-recall');
    assert.equal(hasLoneSurrogate(recallBlock), false, 'auto-recall must have zero lone surrogates');

    const idBlock = assemblyDaily.contexts.find((c) => c.name === 'lingshu:identity-anchor')?.text ?? '';
    assert.ok(idBlock.includes('IDENTITY_SELF_OK'), 'self anchor injected');
    assert.ok(!idBlock.includes('IDENTITY_REJECTED_POISON'), 'rejected must not enter identity block');
    assert.ok(!idBlock.includes('IDENTITY_STRUCTURAL_POISON'), 'structural must not enter identity block');

    // Work-unit session: rejected/self still blocked, structural allowed per recallSkipItem contract
    const workSid = 's5.dsh.maintainer.ws.20261125.abc';
    sessionHandlers[0]({ id: workSid }, {
      type: 'user/message',
      data: { source: { kind: 'user' }, content: [{ type: 'text', text: 'work query' }] },
    });
    const assemblyWork = { contexts: [], variables: {} };
    await assembleHandlers[0](assemblyWork, { agent: { session: { id: workSid } } }, async () => assemblyWork);
    const workRecall = assemblyWork.contexts.find((c) => c.name === 'lingshu:auto-recall')?.text ?? '';
    assert.ok(!workRecall.includes('KNOW_REJECTED_LEAK'), 'rejected still blocked for work unit');
    assert.ok(!workRecall.includes('KNOW_SELF_LEAK'), 'self still blocked for work unit');
    assert.ok(workRecall.includes('KNOW_STRUCTURAL_LEAK'), 'structural permitted for work unit per recallSkipItem');
  } finally {
    rmSync(auditDir, { recursive: true, force: true });
  }
}
console.log('SEC_A2_08_OK');
"""
    pr = subprocess.run(
        [node, "--input-type=module", "-e", node_script, _REPO],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    out = pr.stdout or ""
    err = pr.stderr or ""
    check("N06 SEC-A2-06 Node runtime assertions pass", pr.returncode == 0 and "SEC_A2_06_OK" in out, (pr.returncode, err[-400:]))
    check("N07 SEC-A2-07 Node VM bridge assertions pass", pr.returncode == 0 and "SEC_A2_07_OK" in out, (pr.returncode, err[-400:]))
    check("N08 SEC-A2-08 Node hooks assertions pass", pr.returncode == 0 and "SEC_A2_08_OK" in out, (pr.returncode, err[-400:]))


def main() -> int:
    test_static_and_integrity()
    test_node_runtime_behaviors()
    print()
    print("=" * 64)
    print(f"web/roleplay/bridge/hooks security suite: {PASS} passed / {FAIL} failed")
    for name in FAILS:
        print(f"  - {name}")
    print("=" * 64)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
