> **Languages:** [中文](../../mdcg/世界模型功能端_使用与运维_v1.0.md) · English

# World model feature endpoint · Usage and operations guide (v1.0)

> **This page answers one thing: once the semantic spatiotemporal graph's 'state layer' is live, how you record events, how you query them, where the switches are, how to re-run the readings, and where the boundaries are.**
> Basis: `docs/plans/语义时空图补全_世界模型功能端_设计_v0.1.md` (six acceptance points) and `docs/秤_记忆系统评测规范_v2.1.md` §5.1 (ledger completeness criterion).
> User positioning (2026-10-06): '0.7.4 lays the foundation for the world model, that is, the semantic spatiotemporal graph.' This page corresponds to batch P3 (write-side entry + ledger completeness probe + usage documentation).

---

## 1. In one sentence

**Events are the source, slots are the projection, queries go through stg**:

```
记账（写口）        台账（源）                    投影（物化视图，查询时现算）      查询面
cg(op=state_event) → <root>/_state_events.jsonl → md_cg/state_slots.py        → stg(op=state_chain)
（MCP 面）            append-only、不截断            （只读台账、不落盘、不缓存）        （默认关）
                                                                            ↘ CLI：python -m md_cg.state_slots
```

The four surfaces each have a single source of truth and do not copy each other: the write entry does only permission/normalization/persisting (`md_cg/mcp_server.py`), the ledger only appends (`md_cg/state_events.py`), the projection only replays (`md_cg/state_slots.py`), and the query surface only handles the switch and response shaping (`md_cg/stg.py`).

---

## 2. Where the ledger (source) is and what it looks like

| Item | Content |
|---|---|
| Location | `_state_events.jsonl` under the library root (same level as `_recent.jsonl`, `_write_2pc.jsonl`) |
| Nature | **append-only**: append only, no read-modify-write, no truncation (the rolling window surface `_recent.jsonl` cannot serve as a first-class record, hence this separate ledger) |
| One line per record | `{t, subject, slot, old, new, kind, seq, evidence, actor}` |
| Five `kind` values | `migration` / `retraction` / `enablement` / `acquisition` / `replacement`; **uncategorized (None) is legal** |
| Retraction semantics | `old` has a value and `new` is empty = the value is voided with no new value; enablement = old empty, new has a value; migration/replacement = both have values |
| Bad lines | Tolerance ≠ silence: count on skip + bounded sample + stderr warning (`state_events.BAD_ROWS` is readable) |
| Multi-process | Cross-process file lock (`FileLock`); a crash leaves no half-written file (flush+fsync) |

**Recording does not judge semantics**: `kind` is only a retrieval-surface label and does not enter the criterion; the disambiguation marker (`not_fact`) for utterances that are 'not facts' (jokes / meta level / recalling a retelling) is **not in this batch** (see §8 boundaries).

---

## 3. Write: MCP recording entry `cg(op=state_event)`

### Usage

```
cg(op="state_event", subject="鲸娘", slot="住所",
   old="别墅", new="小屋", kind="migration", seq=1108, evidence="r1108")
```

| Parameter | Required | Description |
|---|---|---|
| `subject` | Yes | Event subject (whose state); empty after stripping whitespace is an error |
| `slot` | Yes | Event slot (which state); same as above |
| `old` / `new` | At least one | Value before/after the change; **both empty is illegal** (an empty event is meaningless). Retraction = leave `new` empty |
| `kind` | No | One of five values; missing/empty string/whitespace only → normalized to 'uncategorized' (None); other values raise an error |
| `seq` | No | Turn or sequence number (used to point back to the corpus location) |
| `evidence` | No | Provenance (short evidence / turn number / file path all work, for later lookback) |

Response body: `{"ok": true, "event": {…落盘记录…}}` (`event` is the line that was appended and persisted).

### Failure basis (fail-closed, nothing swallowed)

| Situation | Result |
|---|---|
| Missing/empty `subject`, missing/empty `slot` | `ValueError` (naming which one is missing) |
| Both `old` and `new` empty | `ValueError` |
| Illegal `kind` value | `ValueError` (listing the five allowed values) |

All of the above are `ValueError`s **raised as-is** (not wrapped errors), so the client can handle them as ordinary errors — **on failure nothing is persisted**.

---

## 4. Read: projection and query

### 1. Query surface `stg(op=state_chain)` (off by default, see §5)

```
stg(op="state_chain", subject="鲸娘", slot="住所", include_retired=true)
```

The response body follows stg's existing basis: `count` (total condition hits, before truncation) / `items` (the first limit items) /
`kept` / `truncated`. Unit fields:

| Field | Semantics |
|---|---|
| `value` | Current value (null after a retraction, until the next event with a value brings it back) |
| `state` | `active` / `retired` (**retirement does not delete**; default queries drop retired items, `include_retired=true` makes them visible) |
| `t_from` / `t_to`, `seq_from` / `seq_to` | Effective interval and sequence numbers: `*_from` = the last event that produced the current value; `*_to` = the next event that supersedes it (not superseded = null = still effective / not yet closed) |
| `tier` | Source tier (passed through from the top-level `tier` of the ledger row; absent = `unspecified`, **never fabricated**) |
| `history` | All events of that slot, the original seven fields (`t/seq/old/new/kind/evidence/actor`); when `history=false` the key is omitted |
| `alternatives` / `blindspots` | Structure present, **always empty lists** (the verdict criterion is deferred, see §8) |
| `event_count` | Number of events in that slot |

**The projection is a materialized view, not a second source of truth**: it is computed from the ledger at query time and neither persisted nor cached — append one line to the ledger and the next query result changes.

### 2. CLI manual entry (`md_cg.state_slots`, **always available**)

```
python -X utf8 -m md_cg.state_slots --status
python -X utf8 -m md_cg.state_slots --subject 鲸娘 [--slot 住所] [--include-retired] [--no-history]
```

The data root is taken from `MDCG_ROOT` (defaulting to `datapath.mdcg_root()`). This CLI is **independent** of the `MDCG_STG_STATE`
switch — that switch governs the MCP read surface; the CLI is a read-only manual inspection entry (it changes no state).

---

## 5. Switches

| Switch | Default | What it governs |
|---|---|---|
| `MDCG_STG_STATE` | **off** | The MCP query surface `stg(op=state_chain)`; the off arm returns `{"error": "disabled", "hint": …}` (**not an exception** — 'not enabled' and 'no hit' must be distinguishable); same discipline as `MDCG_STG_INDEX`/`MDCG_STG_QUALIFY` |
| (no switch) | — | The `cg(op=state_event)` recording entry is **always available** (subject to the permission gate, see §6); the `md_cg.state_slots` CLI is **always available** |

---

## 6. Authorization basis (zero new words against the existing token surface)

- **`state_event` goes through the `write` word mapping**: the op-scope gate of the `cg` surface decides by `write` —
  any role whose `ops_allow` whitelist contains `write` (or a designer token using `"*"`) may record events;
  guest/read-only tokens are still rejected. The token surface **introduces no new op word** (role whitelists and derived narrowing surfaces are unchanged).
- **`actor` always comes from the token** (request parameters have no effect): the persisted `actor` is always the token identity (in no-token form it is
  `"system"`) — clients must not rewrite attribution (following the repository's existing anti-forgery basis).
- **Double insurance on the write gate**: the ledger is an append-only file on the direct-disk surface that **bypasses the library-layer node write gate**, so the recording entry
  additionally makes `require_write("internal")` explicit — `can_write` × `theory_ok` × clearance three-state each take effect
  (read-only tokens, failed version-layer validation, and clearance below internal are all rejected without persisting).

---

## 7. Readings and re-runs: probes + guards

### 1. Ledger completeness probe (Scale 5.1 criterion)

```
python -X utf8 scripts/probe_c_ledger_integrity.py \
    --events %TEMP%/state_events.jsonl --expect-slots 住所,房贷,名字 \
    [--out %TEMP%/probe_c_out]
```

| Reading | Criterion |
|---|---|
| ① Event coverage gap rate | Among the `--expect-slots` list, the share of slots with 'no records at all in the ledger' (both numerator and denominator are printed) |
| ② No-ledger distinguishability rate | For 'slots with no records' plus a fixed synthetic non-existent slot, query `state_chain`: the pass ratio of `count==0 且 items==[]` (**no fabrication, no reverse inference**) |
| ③ Transition-history queryability rate | Among slots with records, the ratio where the total history count returned by `state_chain` (`include_retired=True`, `history=True`) == the ledger's record count for that slot |

Characteristics (hard requirements): reads input only; isolates a temp root (copies `--events` to that root's
`_state_events.jsonl`) — **zero writes to the memory library**; `--out` must land outside the repository (fail-closed);
**determinism** (two runs on the same input produce byte-identical stdout and `--out` artifacts);
the last stdout line is a `PROBE_C_LEDGER_JSON {...}` summary (machine-readable), and with `--out` it also writes
`rates.json` + `probe_c_slots.jsonl`.

### 2. Write-side guard

```
python -X utf8 -m md_cg.test_state_event_op            # 全链/双闸/防伪造/归一/校验/回归
python -X utf8 -m md_cg.test_state_event_op --mutate   # 定点变异自证（每条机制必须能被断言钉红）
```

---

## 8. Boundaries (as they are)

- The verdict criterion for `alternatives` (concurrent undecided values) / `blindspots` (declared gaps) is **deferred**: in this batch the structure is present and
  the lists are always empty, with **no invented filling**.
- The **disambiguation marker** (`not_fact` etc.) for utterances that are 'not facts' (jokes / meta level / recalling a retelling) is not in this batch
  (the P1 event row has no such signal).
- The probe only measures **ledger-surface** distinguishability; **generator-level 'answering without a ledger' is not measured** — that requires readings from the generator side and is deferred.
- Slots are matched **exactly by label** (slot names equal), with no synonym merging or fuzzy matching.
- `state_chain` has no `time_axis` semantics: ledger event rows have only the recording timestamp `t`, no second axis (**no fabrication**);
  for axis semantics use the `stg` timeline/relation/anchors.
- One library = one ledger: cross-library / multi-tenant merging is not covered here.

---

## 9. Retirement discipline: node lifecycle `archived` (excluded from retrieval by default)

> The landing page for the 'retirement discipline' criterion of Scale v2.1 §5.2. **First distinguish the two kinds of 'retirement'** (same name, different things):

| Which one | Field / parameter | Who manages it |
|---|---|---|
| The survival state of a ledger **slot unit** (§4) | Projection unit `state` = `active`/`retired`, query parameter `include_retired` | `md_cg/state_slots.py` (computed at query time) |
| The archive state of a **node** (md memory entry) (this section) | frontmatter / index `lifecycle_state` = `archived` | `md_cg/lifecycle.py` state machine + read-surface exclusion |

### 1. Semantics (fixed in writing, comparable level by level)

| `lifecycle_state` | Default read/injection surfaces (retrieval surface · stg surface · session continuation pack in full) | Notes |
|---|---|---|
| `active` (**missing key or illegal value is the same**) | Participates | fail-open: existing nodes need zero migration and are not wrongly dropped |
| `converged` | Participates | **down-weighting axis** (isomorphic aggregation finalized), not retirement |
| `demoted` | Participates | **down-weighting axis** (weakened), not retirement |
| `archived` | **Excluded by default** | Retirement does not delete: the node file remains and can be explicitly restored |

### 2. Criterion and landing points (single criterion, three consumer surfaces)

- Single criterion: `lifecycle.is_archived(e)` (`md_cg/lifecycle.py`) ≡ `state_of(e) == "archived"`;
  all consumption points reference it together and do not each write their own version.
- Consumer point ① (**cg retrieval surface**): `MdCGOS._candidates` (`md_cg/mdcos.py`) — the **retrieval-type** cg read ops
  (`route` / `read`'s retrieval branch and its `budget_tokens` budget-recall branch / `search` / `search_rrf` and the
  lexical·bucket·entity·graph·chain·temporal paths they contain) all go through this one candidate pool;
  `MdCGSecure._candidates` stacks read visibility on top of it via `super()`, with the same criterion.
  Note: cg's read ops do not all go through the candidate pool — see consumer point ③ (the session continuation surface holds its own data-fetch surface).
- Consumer point ② (**stg scan surface**): `stg._scan_one` (`md_cg/stg.py`, the single per-item implementation of `_scan`)
  — the candidate surfaces of the `timeline` / `anchors` / `consistency` ops are covered at the same point, and the indexed subset
  (`MDCG_STG_INDEX=1`) and the full traversal branches agree bit for bit. `relation` reads an explicit id directly and
  `state_chain` goes through the ledger, so neither passes through the candidate surface (not constrained by this section).
- Consumer point ③ (**session continuation injection surface**): the **four data-fetch segments** of `MdCGOS.session_recall` (`md_cg/mdcos.py`)
  — session notes `_session_notes`, active goals `goals`, task ledger `tasks`, and unresolved questions `unresolved` (`goals`/`tasks` look up the index by id via `_retired_by_id` and then hand it to the same
  criterion). `cg(op=session, action=recall)` holds its own data-fetch surface (bypassing `_candidates`); it assembles node
  content into a 'continuation pack' returned to the caller / injected into the context (= the injection surface), so it is likewise subject to this criterion. The two ledger segments take the **full window**
  (`_LEDGER_WINDOW`), filter, and then truncate to `_PACK_ROWS=5` rows, so retirement exclusion does not make the
  pack 'short'; `tasks.active_total/done_total` accordingly take the **post-exclusion** full-window counts (self-consistent with the list
  source). The `recent` segment is an event window (not nodes), and `self_state` is a read-only snapshot card, so neither involves retirement.
  (An independent review measured two rounds on 2026-10-06: before the wiring, archived note summaries, unresolved-question bodies, active goals,
  and task cards all still came back through that op; they are now pinned by guards R1.12/R1.13/R3.5/R3.6/R4.6.)

### 3. Unrestricted surfaces (the other half of 'retirement does not delete')

- `cg.get(node_id)` direct read and the `cg(op=audit)` evidence audit view: **still reachable** while archived;
- The engineering ledger surface (`goal` / `task`) and statistical surfaces (`health` / `whoami` / conformance): read the index directly,
  not constrained by this section;
- **Lifecycle recovery**: the library-layer entry `MdCG.set_state(node, "archived"→"active")`
  (`md_cg/mdcg.py:4069` → `lifecycle.set_state`, following the legal transition table, one level at a time with no level skipping); after recovery
  the read surface / continuation surface see it again. **The MCP tool surface has no standalone lifecycle entry** (`mcp_server.py` contains the strings `set_state` / `lifecycle` nowhere)
  — 'explicit recovery' is a library-layer call surface.
- Difference from `op=restore` (easy to confuse, stated explicitly): `op=restore` is `action=restore` of `op=forget`
  → `restore` (`md_cg/mdcos.py:4784`) = putting back a node that has been **forgotten** (soft-deleted into `trash/`);
  it is the **deletion axis** and unrelated to the lifecycle state machine; moreover, on restore `lifecycle_state` is judged as a new node (`active`),
  and an `active→archived` level skip is rejected ⇒ **no pass-through (lands as `active`)** (existing behavior, unchanged this round).

### 4. Re-run readings

```
python -X utf8 scripts/probe_d_retirement_discipline.py    # 《秤》v2.1 §5.2 探针
python -X utf8 -m md_cg.test_lifecycle_retire_leak         # 守卫 R1–R4
```

| Reading (`PROBE_D_JSON`) | Criterion | Target (surface counts; ratios in parentheses) |
|---|---|---|
| ① Retirement leak rate | After retirement, the number of surfaces where v2 still appears on verification surfaces (read surface search∪recall, spatiotemporal surface timeline∪anchors) / number of surfaces | `0/2` (0.0) |
| ② Update adoption rate | After v2 is written, the number of visible surfaces / number of surfaces (guards against the reverse defect of 'filtering everything indiscriminately') | `2/2` (1.0) |
| ③ Old-fact residue rate | After the retirement step, the number of surfaces where v1 is still visible / number of surfaces (no collateral exclusion) | `2/2` (1.0) |
| ④ Invalidity misjudgment falsification rate | Number of retired nodes wrongly set to falsified/rejected / number of retired nodes (retirement ≠ falsification) | `0/1` (0.0) |

(The probe's human-readable line prints exactly the **surface count** 'n/denominator (target m)'; the table above uses the same unit, and the ratios are converted values.)

Probe characteristics: isolated temp root (zero writes to the live library), pure stdlib, no randomness/no timestamps,
`--out` must land outside the repository (fail-closed), last line `PROBE_D_JSON {...}`, **two runs produce byte-identical stdout**.

### 5. Boundaries (as they are)

- Only `archived` is excluded. To make `converged`/`demoted` not participate, use the existing other dimensions
  (`role` / `view` / `layer` / `session` / `validity`) — they must not be merged into the retirement criterion.
- Ledger unit retirement (§4 `retired`) and node retirement (this section's `archived`) are **independent of each other with no linkage**.
- **Surface criterion (fixed, for future wiring to classify accordingly)**: the **default read/injection surface** = the caller gives a query/intent/session view,
  **the library chooses the node set**, and the result goes directly back to the caller or into the injected context ⇒ it must consume `is_archived`;
  a **targeted/management/statistical surface** = the caller gives an **explicit node selection key** (`node_id` / `subject:*` label / prefix /
  layer / state), or the surface itself is diagnostic·statistical·write ⇒ direct read, not constrained by this section.
- Wired consumer surfaces (3 places, 4 sub-surfaces): retrieval surface `_candidates`, stg surface `_scan_one`, and the session continuation injection surface
  `session_recall`'s **all four data-fetch segments** (notes `_session_notes` + active goals + task ledger +
  unresolved questions; the latter two go through `_retired_by_id` by id criterion) (§2).
- **Enumerated but classified as 'targeted/management/statistical surfaces' (unrestricted, declared item by item)**: `cg.get` direct read, `op=audit`
  evidence audit, the **explicit management query surface of the engineering ledger** (`cg(op=goal, action=list)` / `cg(op=task,
  action=list)` — direct ledger reads; archived items are still listed while archived, pinned by guard R1.13c),
  `health`/`whoami`/`_role_counts`/`_sensitivity_counts`/`conformance`/`census`/`insight`
  statistics, `review_records` review records, `export`/`evidence` export and evidence surfaces, `crosscheck`/
  `ghostref`/`consistency` diagnostic surfaces, `backfill*`/`writelimit`/`freshness`/`forgetting`
  maintenance write surfaces, `mreview/govern` governance surfaces, and the white-box KB tool surface.
  **Do not read this together with consumer point ③**: for the same goal/task ledger, **the injection surface (continuation pack) excludes archived,
  while the management query surface reads directly** — this is not a contradiction but a division of labor between the two sides of the criterion (guards pin both sides at once: R1.13b exclusion,
  R1.13c direct read).
  One representative surface that **returns content and whose set is chosen by the library** must be named honestly: `identity.profile`
  (`md_cg/identity.py:310`, which self-selects by the `subject:<id>` label and returns anchor body excerpts) — measured archived
  anchors are still returned (evidence: the `anchors[0].content` returned by `identity.profile` contains the archived node's body marker);
  under the criterion above it is a **targeted surface** (`subject_id` is an explicit selection key, same family as `cg.get`), so **it was not wired this round**
  (its file is outside the surfaces this round is allowed to change).
- **Surface wiring state (landed in the 2026-10-06 user-ruling batch — the disposition of the original four 'known uncovered surfaces')**:
  - **Base class `MdCG.search` → wired** (the candidate condition in `md_cg/mdcg.py` adds the `lifecycle.is_archived`
    criterion): the default retrieval surface of plain `MdCG` instances (white-box KB / offline scripts / tests) now uses the same criterion as the production path
    (guard R5, including the 'converged down-weighting axis is not wrongly dropped' control).
  - **Causal chain / graph surface `chain.adjacency` → wired** (a new `skip_archived=True` default parameter):
    outgoing edges of retired nodes do not enter the table at all, and edges pointing at retired targets are truncated — `cg(op=causal, action=chain)`,
    `predict.*` and other read/prediction surfaces no longer diffuse into archived (guards R6.0/R6.1/R6.4, including the measured leg where archiving happens
    while the cache is already warm). **Maintenance surfaces explicitly bypass**: `scrub` decontamination sampling passes
    `skip_archived=False` to take the full table (guards R6.2/R6.3 pin the bypass — the division of surface criteria:
    default read/injection surfaces must consume it, maintenance/management surfaces read directly).
  - **Cache invalidation hook (the delivery gap evidenced in this batch)**: a state transition changes the `is_archived` reading,
    while the `chain` adjacency cache was previously **not invalidated** after `set_state` (probe evidence: after archiving,
    `causal_chain` still contained the target) — now `lifecycle.set_state` calls `chain.invalidate_cache` at the same point as the write-disk point
    (lazy import; `invalidate_cache` swallows its own exceptions and does not block progress).
  - **Structural/topological surface `subgraph.children_index` / `parents_index` → ruled not wired**
    (the caller gives explicit parent/child ids and the return is an id mapping with no body, so it is a targeted/structural surface and reads directly) —
    guards R7.0/R7.1 **pin the ruling**: after a child node retires the mapping still exists; if anyone 'conveniently wires it' in the future,
    R7.1 turning red is the reminder to change the ruling first.
  - **rust retrieval kernel → wired** (`rust/src/store.rs`): `Entry` gains a
    `lifecycle_state` field (the key name shares its source with Python's `lifecycle.STATE_FIELD`), and
    `candidates()` excludes `archived` (missing key/illegal = active, fail-open; converged/
    demoted still participate) — crate unit tests `archived_entries_excluded_from_candidates`
    and `lifecycle_state_parsed_from_index_json` pin both; consistency of the two sides continues to be watched by the
    `rank_parity` gate leg (the evaluation corpus has no archived, so it is a bit-for-bit zero shift).
- Cross-process consistency: the criterion reads only **this process's index entries** (`lifecycle_state` is synced with
  migrations by `lifecycle._sync_index` and recorded in `_index_log`); within the window where another process has just archived but this process's index
  has not reloaded, readings may lag (same source as the existing persist basis of `lifecycle.set_state`).

---

## 10. Multi-subject state tracking (core capability and resident read view)

> User positioning 2026-10-06: 'This feature can be resident, maintaining state tracking for other characters; this should be
> a core function of the semantic spatiotemporal graph.'

**Capability statement**: state tracking (multi-subject · five-element events · slot projection) is the **core function** of the semantic spatiotemporal graph —
`subject` is parameterized to any subject (character/institution/me), the ledger (`_state_events.jsonl`) is the sole source of truth,
and everything else is projection/view.

**Resident form** = **a read-only view computed at query time** (same philosophy as `state_slots`, no second source of truth):
calling at any moment yields the latest state; no background task dependency. Tool surfaces (all in `scripts/`):

| Item | Purpose |
|---|---|
| `state_atlas.py` | **Generic multi-subject tracking map** (resident piece): one md = a worldbook for all characters (current values/retirement/transition history/major events/per-act) plus optional `--worldbook-json` (tavern-style key/content) |
| `whale_state_tracker.py` | Corpus-line extractor (turns dialogue corpora into five-element events; the whale character ruleset, whose machinery can be imitated to build rule packs for other characters) |
| `whale_state_atlas.py` | Corpus-line dedicated tracking map (generated from the extractor's md output) |
| `state_slots.py` (CLI) | Read-only entry for slot projection (always available, `--status` etc.) |
| `stg(op=state_chain)` | MCP query surface (flag `MDCG_STG_STATE` off by default — discipline unchanged, complementary to the always-available CLI) |

**Library root resolution (same source as zcode MCP, preventing two-library forking)**: `--root` > env `MDCG_ROOT` >
`~/.zcode/cli/config.json`'s `mcp.servers.mdcg.env.MDCG_ROOT` > `mdcg_root()` default.
**Read-only discipline**: tool surfaces are read-only, and `--out` is always outside the repository (fail-closed).

**Recording discipline (general guidance, distilled from the whale-character line's three-layer disambiguation basis)**: ① record when a state change happens (whose
what slot, old/new, one of five kinds); ② **user-side statements take precedence** (a state the user explicitly states is authoritative;
a character's self-reported 'misremembering' does not overwrite the true value); ③ the three non-fact categories (jokes/meta level/recalling a retelling) are labeled truthfully and
do not overwrite the true value; ④ retraction = old has a value and new is empty (explicit voiding, no silent rewriting).

**Live status (measured 2026-10-06)**: the authoritative library (the AEIS data-area library root — root resolution follows the same-source basis above)
has **0 events** in its ledger — the full mechanism is in place and the data is uncharted territory; multi-subject rendering was demonstrated and verified in an isolated library
(2 subjects/30 events/15 slots/15 worldbook entries; readings in the `docs/eval/` report v1.2 section).

**Pending ruling (optional enhancement for resident automation)**: whether to hang a step
'pre-generate tracking map md by subject → state surface' on the sleep-cycle 'organize' slot — the current state is **computed on demand** (open it and it is the latest), and pre-generation would only be a cache object for
'a file exists as soon as you open it'; changing the resident loop is a production behavior change and must be filed as its own item.

### Session link integration (step two of the turn write chain; user ruling 2026-10-06)

> 'Treat this feature as the 10-turn information write for the session, and process it when writing mdcg... each write
> adds some processes asynchronously, but the benefit is a maintainable state, and at the same time a cognitive map and a semantic spatiotemporal graph,
> with relationship traceability of the original information.'

- **Wiring point**: `scripts/sync_zcode_session.py::sync_to_window` (zcode side, every turn —
  Stop hook/cold start/compression recovery share the same chain) — **within the same loop** that writes the `_recent` window, call
  `scripts/state_extract.py` for conservative extraction on the same turn → `state_events.append` into the ledger. The hook runs as a subprocess at the end of the turn (processed outside the session, i.e. 'asynchronous'),
  **fail-soft per turn** (extraction failure never affects window writing or turn progress).
- **Conservative basis (the discipline for writing into the live library: better to miss than to be wrong)**: extract only **user turns** (a real person = the fact source);
  only two high-precision rules (`地点·所在` migration / `情感·偏好`, with the negative direction explicitly recorded as `不喜欢：`); values have
  sentence-final modal particles stripped; **deduplicate identical values** (to prevent repeated recording every turn); evidence `[auto] session=… turn=…`,
  `actor=state_extract` — so it can be identified/cleaned up wholesale; the switch `MDCG_STATE_EXTRACT` is **on by default**
  (=0 turns it off). The probe has shown: bare word forms (promise 138 / causal 59/225 hits) do not enter the rule table.
- **Three layers from one source + relationship traceability**: cognitive map (`_recent`/knowledge surface) + semantic spatiotemporal graph (ledger/`state_slots`
  projection/`state_atlas` view) + original text (session md mirror/full transcription) — the event `evidence` carries
  session/turn number/short evidence, so any layer can look back at the other two.
- **Readings**: guard `scripts/test_state_extract.py` **10/10** (zero hits from the three noise families, deduplication,
  value-change chains, evidence format, switch, wiring point) + full run **359/359**.
- **DSH side**: the same wiring lives on the plugin side (TS) — it is a follow-up item (requires changing the plugin and releasing it with the package); this batch only has
  the zcode side online, and DSH-side behavior is unchanged.
- **Known boundary (left to be ruled)**: generalized word forms of the 'lives here' kind will match (the value is taken as 'inside' and the like) — this is how the v1 word forms
  are; whether to narrow them is up to the user.

---

## Revision history

| Date | Key points |
|---|---|
| 2026-10-06 | v1.0 first edition (batch P3): full chain (ledger→projection→query→recording entry→CLI→probe) / switch `MDCG_STG_STATE` off by default and the CLI always available / authorization basis (`state_event`→`write` word mapping, actor always from the token) / re-run commands for the probe's three readings / boundaries as they are (§1–§8) |
| 2026-10-06 | Added §9 'Retirement discipline': default retrieval exclusion of nodes with `lifecycle_state=archived` (single criterion `lifecycle.is_archived`, consumer surfaces `MdCGOS._candidates` + `stg._scan_one` + the four segments of the session continuation injection surface `session_recall` [notes/active goals/task ledger/unresolved questions]) / the boundary between the two meanings of 'retirement' / unrestricted surfaces (direct read · audit · **ledger management query surface** · statistics) and 'lifecycle recovery ≠ `op=restore` (deletion axis)' / the four readings of the Scale 5.2 probe (surface-count basis) and guard re-runs / boundaries as they are (uncovered surfaces: base class `MdCG.search`, causal chain surface `chain.adjacency`, structural surface `subgraph`, rust kernel, targeted surface `identity.profile`) |
| 2026-10-06 | **Boundary four-item ruling batch landed (user ruling: 1/2/4 wired, 3 not wired)**: base class `MdCG.search` wired (R5) / `chain.adjacency` wired (`skip_archived` parameter, R6; scrub maintenance surface explicit bypass) / rust kernel wired (crate unit tests pin both) / `subgraph` structural surface **ruled not wired** (R7 pins the ruling); and added `chain.invalidate_cache` same-point invalidation in `lifecycle.set_state` (the cache gap evidenced by this batch's probe); guards 36→45 assertions |
| 2026-10-06 | **Added §10 'Multi-subject state tracking' (core capability positioning, user 2026-10-06)**: resident form = read-only view computed at query time (no second source of truth); four tool surfaces (`state_atlas` generic multi-subject / two corpus-line pieces / CLI); library root resolution from the same source as MCP (preventing two-library forking); four recording disciplines (distilled from the whale-character line's three-layer disambiguation basis); 0-event live ledger measurement + isolated multi-subject demo readings; sleep-slot pre-generation listed as pending ruling |
| 2026-10-06 | **Added §10 'Session link integration' (step two of the turn write chain, user ruling 2026-10-06)**: `sync_to_window` conservatively extracts the same turn within the same loop (`state_extract`: user turns only / two high-precision rules / deduplication / identifiable evidence; switch on by default) → ledger; three layers from one source + relationship traceability; guard `test_state_extract` 10/10, full run 359/359; the same wiring on the DSH side is listed as a follow-up item |
