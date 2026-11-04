> **Languages:** [中文](../../ops/环境与已知问题.md) · English

# Environments and known issues

> **Scope of this page**: it collects only phenomena that **look like a bug but are actually environment, installation, or contract** issues, together with the evidence used to classify them.
> For functional defects, open an [issue](https://github.com/FuRongJun-1999/dsh-memory/issues) (with trigger conditions + a minimal reproduction + measured readings);
> installation steps are in [Installation and prerequisites](install.md), and upgrades and operations are in [Operations and troubleshooting](operations-troubleshooting.md).

---

## 1. DSH Desktop startup warnings (host side, outside this repository's fix scope)

**Symptom**: every startup logs a `migration failed` (about 2.6 seconds) and a `profile maintenance frozen`, and the log writes
`@deepseek-ai/schemastery does not resolve from the installation closure`.

**Mechanism** (verifiable): DSH Desktop's `installer.mjs` first hoists every `@deepseek-ai/*` package out of the generation as a **host singleton** (`hoistHostSingletons`), and then **validates the dependency closure against that same generation directory**. The pair of rules "remove it first, then validate it in place" necessarily reports "cannot resolve" for any plugin that declares host packages as normal dependencies.

**Functional impact**: **none**. At runtime the host's `host-module-fallback` catches imports with the `@deepseek-ai/` prefix and serves them from the copy shipped with the host (memory writes/recall and `cg(op=info)` all work normally).

**Why the package declaration is not changed**: switching to `peerDependencies` would make "import after a bare npm install" fail outright (the original defect in issue #222; `test/issue222_optional_peer.test.ts` guards that contract). Both contracts cannot hold under the current dependency shape; this plugin targets the DSH **web UI**, so the status quo stands and is recorded here (analysis in issue #660; upstream has it logged as deepseek-harness discussion #10940).

---

## 2. Size and deployment: it is not "copy a few .py files and it runs"

`md_cg/` is **coupled as an entire directory**: code + assets (`whitebox_kb` / `lexicon` / `semantic` / `knowledge`) live in one tree.
MCP mode also depends on `utf8_boot.py` at the **package root**.

| Item | Measured (v0.9.13 main) |
|---|---|
| `md_cg/` total | **71.9 MB / 2765 files** |
| `whitebox_kb/` | 20.8 MB / 580 files |
| `lexicon/` | 1.6 MB |
| `semantic/` | 1.2 MB |

**Criterion**: copying only some modules throws `ImportError: cannot import name 'nodefile' from partially initialized module` at import time (`mdcg.py` has a top-level `from . import (nodefile, protect, routing, subgraph, chain, provenance, pooling, …)`). Ship the whole directory, or wait for package splitting (issue #672 has it registered as an evaluation item).

---

## 3. Persist timing: node files synchronous, index derivatives asynchronous (#677 P2)

A single `cg(op=write)` persists in **two layers** with **different** timing (a design trade-off, not a defect):

| Layer | Timing | Semantics |
|---|---|---|
| Node file `<root>/<layer>/<id>.md` | **synchronous** (on disk before the return) | source of truth; authoritative data |
| In-memory index (retrieval visibility) | **synchronous** (same `_stage` hook) | "searchable immediately after a write" is **not degraded** |
| Index derivative `_index_log/` shard logs (the flush triggered by the threshold) | **asynchronous** (background thread `mdcg-index-flush`) | derived data; rebuildable by replaying node files |

**Why asynchronous**: that flush must append entry by entry under a `FileLock` and open/close shard handles, which is the main cost on the RPC return path. The client's 60s timeout measures the **entire chain**, so "persisted but no reply" is read as a failure, and a retry creates duplicate entries (three pieces of evidence in issue #677). Moving this work off the return path sharply narrows the chance of "timeout ≠ failure".

**The price of asynchrony and the three exits** (lose any one and it degrades into "silent degradation"):

1. **To be certain it persisted** -> `cg(op=maintain, action=flush)`: explicitly and **synchronously** writes the pending index
   (returns `{ok, action:"flush", async, pending_dirty, worker_alive, last_error}`);
   `cg.close()` / a normal process exit also persist synchronously (close semantics unchanged: return means persisted).
2. **To see whether the index derivative lags the on-disk state** -> `os.index_flush` in `cg(op=info)`
   (`{async, pending_dirty, worker_alive, last_error}`). A background persist failure **always leaves a trace**
   (`last_error` + one stderr warning); it never lives only inside an exception.
3. **To turn asynchrony off (back to the bit-for-bit old behavior)** -> the `MDCG_ASYNC_FLUSH=0` environment variable.

**An existing shape derived from this**: in the same process, after `del cg; gc.collect(); shutil.rmtree(path)` the directory may
**be recreated** (file timestamps carry the moment of deletion). To clean up a temporary store in tests, **start another process** (`subprocess` / a standalone script),
or call `cg.close()` explicitly before exiting.

## 4. Timeout ≠ failure: look first, then write (#677 P1/P3)

On the write surface, **a timeout does not mean the write did not land**. The correct order after a timeout is **look first, then write**:

```js
try { write({ content, dedupe: true }) }   // dedupe：同层同内容复用既有节点（opt-in）
catch (e) {
  const hit = await route(intent);         // ① 先看落没落盘
  if (!hit) write({ content, node_id });   // ② 确认没有再写，且**自带固定 node_id**
}
```

- **Two ways to be idempotent**: supply your own `node_id` (overwriting the same id is naturally idempotent); or `dedupe: true`
  (short-circuit reuse of an existing node by "same layer + content fingerprint", returning `deduped: true` and `content_sha`).
- **Neither is the default**: when `node_id` is not passed, the server generates one, so a retry adds a node — existing contract, unchanged.
- Where the rule lives: `md_cg/writepipe.py` (the idempotency gate short-circuits at the head of the chain, before reference resolution or edge creation).
- **Automatic memory is deduplicated by default** (issue #677 @1, 2026-11-05): the three kinds written by the
  plugin (user/assistant/tool) carry `dedupe: true`, so a retry after a timeout no longer adds a duplicate node.
  - **Deduplication is session-scoped** (the server compares `session`): the same text written by two different
    sessions does **not** collapse — otherwise, with `sessionPrivate` on, the second session would "hit" the
    first session's private node and silently read nothing.
  - **Cost**: the same message repeated within one session is kept once — occurrence count, timestamps and
    attribution are lost (tool results suffer most). Set `memory.dedupe` to `false` to keep duplicates.
  - A hit adds no node but does **not** skip this round's gates (dedupe short-circuits at the head of
    `mdcg_remember`; it reuses a node that already passed the gates). A dedicated `audit.deduped` counter is
    not implemented yet.

---

## 5. The `rmtree` quirk on Windows + Python 3.12 (a Python issue, not this repository's)

`shutil.rmtree(root)` throws `FileNotFoundError`, yet `os.path.exists(root)` is `False` (the tree is in fact already gone).
The combination of nested directories and lock files makes it more likely. **Handling**: ignore the exception; do not treat it as a failed delete and retry the write.

---

## 6. Design trade-offs: they look like bugs but are contracts

### 5.1 The default value and source of `importance`

The write surface gives `importance` a default (0.5 at the library layer, 0.6 commonly used by the plugin hint surface), and tags the source in `importance_source` (such as `hint`).
**This is not "a dirty store"** — the automatic memory surface writes at the "worth remembering" default tier and converges through later `scrub` / calibration.

### 5.2 `importance >= 0.7` is a **hard protection**; a wrong write cannot be undone

`md_cg/scrub.py` says verbatim: **protected nodes (self/anchor/importance≥0.7/explicitly protected) are skipped; never deleted**.
The single-point constant is `protect.AUTO_PROTECT_IMPORTANCE = 0.70`.
**Meaning**: a high importance value is an application for never-forget protection; deleting after a wrong write requires an explicit `override`.

### 5.3 `calibration` only suggests; it does not apply automatically

Calibration output looks like `{suggested_offset: -0.15, applied: false}`:
`suggested_offset` is a **suggested value**, and `applied` always reports whether it was actually applied (by default confidence is **not changed automatically**).
**This is a "human in the loop" trade-off, not a "knows but does not change it" bug**; applying it requires passing `apply` explicitly.

### 5.4 `validity` excludes only "expired", not "not yet effective"

The `validity` semantics of `search` / `search_rrf` are **exclude expired** (`not_yet` is kept), while the name reads easily as "only valid ones".
Both read paths now report this faithfully in `meta.validity_scope`: `expired_only` (enabled) / `off` (not enabled).

### 5.6 Minimum score thresholds: both `0` and `-1` mean "off"

The two threshold switches have **different defaults**, which is easy to misread:

| Variable | Default | Semantics |
|---|---|---|
| `MDCG_MIN_SCORE` | `0` | minimum score threshold of the fusion surface / T3 exit; **0 = off** (no filtering) |
| `MDCG_RECALL_MIN_SCORE` | `-1` | minimum score threshold of the recall surface (token-budget packing); **-1 = off**; set `0.01` to enable |

**The rule is unified as: only `> 0` counts as enabled**: a value of `0` or a negative number is always "off", not "threshold 0 (everything qualifies)" — the latter looks equivalent but actually erases the difference between "a real candidate that S5 pushed down to 0" and "a zero-score fallback".

Invalid values (non-numeric / `nan` / `±inf`) **fall back to the default and are recorded**: `min_score_input=invalid` in the read-surface meta means the setting is wrong.

One historical measurement-basis difference, for completeness (now unified): the fusion surface used `>0` while the recall surface used `>=0`, so `MDCG_MIN_SCORE=0` was off on one side and on for the other, and `-0.0` still opened the gate. Both now go through the same single parsing point.

### 5.5 Orphan nodes must remain reachable by fallback recall

Nodes with empty `edges` and `access_count: 0` are hit by `T2_global_like` (the global lexical fallback path), and **this is a contract requirement**:
`md_cg/routing.py` says verbatim "the node stays in the ORPHAN/fallback pool (**it must remain reachable by fallback recall when S1 converges**, see contract §3, S1 invariant)". If you want "high-confidence results only", use the qualification adjudication tier (`judge` / `cg(op=route)`), not a threshold on the fallback path.

---

## 7. Session-level exclusion for automatic memory (#695)

An external bridge (e.g. a QQ bridge) calls `sessions.prompt()` with a wake-up/management protocol plus a chat snapshot,
and DSH projects that into a `user/message` whose `source.kind` is still `user` — and, **measured, it also carries**
`rpcId` (12/12), while a normal Web input only differs by the optional `clientTimeZone`. So lingshu **cannot** tell
"human input" from "bridge-synthesized prompt" by event shape alone; the `source_shapes` audit is two marginal
distributions (no kind × shape joint table).

Explicit fallback: `memory.excludeSessions` (default `[]`).

```jsonc
{ "memory": { "userMessage": true, "excludeSessions": ["sess_bridge_*"] } }
```

- Exact match; entries ending with `*` match by prefix (`sess_bridge_*`). A bare `*` is **ignored** (otherwise one
  entry would silently disable every session; use `userMessage=false` to disable globally).
- A matching session writes **nothing to the knowledge track** (user / assistant / tool skipped) and does not count
  toward the every-ten-turns reminder.
- **The context-window write side still runs** (`_recent.jsonl`: runtime state, not searchable, not knowledge nodes);
  the injection side is untouched.
- **No content-marker filtering**: strings like `【会话令牌】` are never used as a criterion.
- Malformed configuration (not an array / non-string items) means **no exclusion** (safe degradation).

### Known costs

1. **If a session mixes human input with synthetic prompts, the human content is dropped too.** Exclusion is
   session-level, while a bridge is often "one group = one session". **Recommended: give bridge control prompts
   their own session** (e.g. `sess_bridge_<channel>_*`).
2. **Sessions with an empty `sid` (unassigned) cannot be excluded** — if the bridge does not pass a session id,
   the switch silently does nothing.
3. **Audit surface change**: `counts.filtered` gains a `session_excluded` key; `sumCounts` only tolerates a
   missing **new** key, while a missing old key still marks the file corrupt.

### Cleaning up already-polluted nodes (this switch only stops new ones)

```text
cg(op=read, query="【会话令牌】")        # or "【本次消息快照】"
# after manual confirmation, delete (importance >= 0.7 needs override=True)
```

> **"No content-marker filtering" ≠ "cannot clean by marker"**: the marker stays out of code (it would kill real
> memories) and lives only in this runbook.

> True attribution needs a trustworthy source field from the host (option A in issue #695). Until then this switch is
> the honest "remember less rather than misremember" choice; real bridge chat should use a separate entry point.

---

## 8. Session memory isolation: `sessionPrivate` and the narrowing surface (#730)

### 8.1 "Each session reads its own" uses the existing sensitivity mechanism

Server-side `_readable` (`md_cg/mdcos.py`): `public`/`internal` are cross-session levels;
`private`/`secret` are **session-bound** (only the owning `frontmatter.session` can read them,
`can_admin` exempts). Session-bound nodes without an owner are fail-closed (designer only).

So the plugin only needs to mark automatic memories `private`:

```jsonc
{ "memory": { "userMessage": true, "sessionPrivate": true } }
```

- Default **false** (cross-session continuity is the existing default; cross-session recall is still a
  product decision, see #749).
- When on, user / assistant / tool memories carry `sensitivity: "private"`.
- **Unassigned sessions are never marked private** — a private node without an owner is visible only to
  the designer, i.e. effectively lost.

### 8.3 Costs of enabling `sessionPrivate`

1. **The session id must be stable across restarts**: visibility is `fm.session == principal.session`. If the host
   generates a new `sess_*` on every start, private memories written last run cannot be read next run (not
   "isolated" — lost; `recall` just returns less without error). The `s5` identity chain covers only part of the
   paths — if the assistant seems to "forget" after enabling, turn the switch off and check session identity.
2. **`private` is an encrypted level**: writing needs a master key (KEK/DEK). Without one the write is
   fail-closed (not written), so on a keyless deployment enabling private means **no automatic memory at all**,
   not "isolation works".
3. **Only session flowing memories are affected**: knowledge-layer / distilled / direct `remember` writes stay
   `internal`. Cross-session continuity should ride on **distilled knowledge**, not raw session turns — that is how
   `sessionPrivate` and #749 coexist.
4. **No owner, no private** (`sid` empty or exactly the `unassigned` sentinel) — private without an owner is
   designer-only, i.e. written into the void.

> One line: **enable only if you want isolation; enabling costs cross-session continuity and restart readability.**### 8.2 `sessions_read` and the `narrowed_principal` narrowing surface

`sessions_read` limits the recent-event window in the resume package (it is **not** search visibility —
that is governed by sensitivity).

- Issue/derive: `tokens.issue(..., sessions_read=[...])` / `tokens.derive(..., sessions_read=[...])`
  (derive takes the **intersection**; an empty intersection raises `TokenError`).
- CLI: `--sessions-read a,b`.
- Request-level narrowing: `as_unit` goes through `narrowed_principal`, which now propagates the owner
  `sessions_read` (previously dropped: an owner restriction silently widened to unlimited, fail-open).
- Single source of narrowing fields: `tokens.NARROWING_FIELDS` (clearance / can_write / can_admin /
  layers_allow / ops_allow / sessions_read), guarded by `test_issue730_narrowing_audit`.
- **No `as_session`**: `_readable` already rules that session identity cannot be self-declared;
  switching sessions is privilege-neutral, not a narrowing.
