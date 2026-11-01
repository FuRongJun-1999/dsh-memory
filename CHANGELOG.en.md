> **Languages:** [中文](CHANGELOG.md) · English

# Changelog (CHANGELOG)

This file is maintained since **0.9.15**. For earlier versions see the git tags (`v0.9.6` … `v0.9.14`) and GitHub Releases.

The format follows [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/); version numbers follow semantic versioning.

## [0.9.21] - 2026-10-31

### Fix: standard documents are **shipped with the package** (0.9.20 only gave external links)

The 0.9.20 approach was "give GitHub absolute links in the README" - it solved "you know it exists", but **not "you can read it after installing"**.

**This release puts the 7 standards that users should follow or check into the `files` allowlist**:

| File | Purpose |
|---|---|
| `docs/mdcg/写入别名aliases规范_v0.6.md` | **How to add `aliases` when writing memory** (capability added in 0.9.19) |
| `docs/mdcg/CCG六要素编译.md` | How to write the six elements |
| `docs/mdcg/guardrail-charter.md` | Guardrail Charter (the public act) |
| `docs/mdcg/MCP工具名口径_v1.0.md` | Tool name measurement basis |
| `docs/mdcg/recall_metadata.md` | Recall metadata |
| `docs/mdcg/世界模型功能端_使用与运维_v1.0.md` | World model endpoint usage and operations |
| `docs/mdcg/cogmap_ops.md` | cogmap operations |

⇒ After installing the package, these 7 files are directly readable under `node_modules/@furongjun1999/dsh-memory/docs/mdcg/`. The documentation map links in the README also changed back to **package-relative paths**.

### Why not package the whole directory

`docs/mdcg/` has **47 .md files** in total, mixed with internal records (`release_v0.3.0.md`, `CSRE_索引与负条件修复_20261012.md`, the various `plans_*`, `D_meta_工程化方案`, and so on).
**Packaging the whole directory would ship the internal records too**, so 7 files were picked individually.

### Still not packaged (explicit boundary)

- `docs/theory/` (19 files, internal theory)
- `docs/eval/` (136 files, internal evaluation)
- `docs/plans/` (25 files, internal plans)
- `docs/ops/` (8 files, installation and operations - the README already has relative links, but they **still cannot be opened on the npm page**; an existing problem)

## [0.9.20] - 2026-10-31

### Fix: visibility of standard documents (an oversight in 0.9.19)

The 0.9.19 CHANGELOG said "full standard: `docs/mdcg/写入别名aliases规范_v0.6.md`",
**but `docs/mdcg/` was never in the npm package `files` allowlist** ⇒ that was a **dead link inside the package**; users could not find it even after installing.

**Fixes in this release**:

| Surface | Change |
|---|---|
| `README.md` · documentation map | Added a row "**Write standards**", linked via **GitHub absolute URLs** to "Write aliases", "CCG six-element compilation", and "Guardrail Charter", with an **explicit note that "these are not in the npm package"** |
| `CHANGELOG.md` · 0.9.19 section | Dead links changed to GitHub URLs, with the note "not in the npm package, read them in the repository" |

⚠️ **Why not relative paths**: the existing links in the README are all relative paths (`docs/ops/README.md` etc.),
and they **equally cannot be opened on the npm package page** - so everything newly added uses absolute URLs.

> This is an old problem between the "packaging allowlist" and "documentation pointers": `docs/mdcg/` has 47 .md files,
> some of them standards users should follow (`写入别名aliases`, `CCG六要素编译`, `guardrail-charter`),
> and some internal records (`release_v0.3.0`, `CSRE_索引与负条件修复`, the various `plans`).
> **Packaging the whole directory would ship the internal records too**, so this time the choice was "no packaging + absolute links in the README".

## [0.9.19] - 2026-10-31

### Added: `aliases` (write aliases) - the fix for natural phrasing that recall cannot reach

**Usage**: when writing memory, add `aliases` to the node and put in the phrasings for "how users might ask about this later".

```python
cg(op="write", node_id="...", content="""# 功能名：会话交接前的记忆固化
# 生效条件：聊交接、换会话、压缩、或他流露舍不得时
...""",
   aliases=["换掉", "被换", "别消失", "舍不得", "不想你走", "压缩上下文"])
```

`aliases` **participates in lexical recall but does not go into `tags`** - `tags` is occupied by machine criteria ("is this a task card", "can this be an anchor"),
and mixing them would change those criteria.

**The right way to write aliases** (summary of measured practice): before writing, **first ask yourself "how would I ask about this later?"**, and put those phrasings in verbatim (3-8 of them; colloquial, emotional, and near-synonym all count).

> ⚠️ **Do not mechanically extract words**. Measured: auto-generating by splitting the feature name on spaces, 20 entries × 5 queries = **improvement +0**
> (Chinese feature names have no spaces, so what gets split out is the whole sentence). Aliases can only be "thought of", not "split out".

**Why it is needed** - the decisive case in issue #722:

| Matching method | Condition "talk about handover, switching sessions, compression..." vs query "I don't want you to be replaced" |
|---|---|
| Whole-word matching | ❌ |
| Bigram overlap | ❌ `换会/会话` vs `我不/…/被换/换掉` - **intersection empty** |
| Query expansion | ❌ expands to `换掉/被换`, still **no intersection** with `换会话` |
| Existing synonym table (10 groups, all technical terms) | ❌ |
| **Adding `aliases`** | ✅ **hit** |

Full standard (**not in the npm package, read it in the repository**): [`docs/mdcg/写入别名aliases规范_v0.6.md`](docs/en/mdcg/write-aliases.md)

### Fixes

- **Web panel `permissionNote` does not accept the `*` wildcard** (#723 / PR #724): under a full-permission token (`ops_allow: ["*"]`),
  **all 12/12 presets on the four pages "Goals and Tasks", "Self-Knowledge", "Spatiotemporal Relations", and "Review and Maintenance" falsely reported "permission not declared"**,
  while the actual calls all succeeded. Root cause: **the front end and the server used different criteria for the same judgment**:
  the server's `_in_scope` accepted `"*" in allow`, the front end only did `allowed.includes(op)`. Now aligned.

  ⚠️ The inverted-criteria symptom is worth recording: **a full-permission token sees a screen full of red, while a narrow token sees only partial hints**.

### Added: write gate criteria (**not wired in yet, only testable functions**)

| Function | Purpose |
|---|---|
| `writegate.cond_is_metadata(cond_text)` | Decide whether the "effective condition" describes the carrier/path/method (metadata) rather than a trigger scenario |
| `writegate.check_condition_quality(content)` | Write-gate wrapper around the above, returns `{ok, is_metadata, cond, hint}`; **never raises** |
| `writegate.aliases_is_thin(fm, content)` | Decide whether aliases are "thin" (no aliases, or only repeating words already present in the body) |

⚠️ **These three functions are not wired into `add()` yet** - only testable entry points are provided; wiring is the next change.

### Internal: tests and guards

- **`test_mode_parity` `full_D` cross-minute time leak** (PR #720): `tombstone` is a content hash,
  and the content contains wall-clock aggregate lines ⇒ two subprocesses across a minute boundary necessarily DIFF. A fixed timestamp is now injected in `_RUNNER`.
- New guards: `test_723_permission_wildcard` (6 items, **cross-side criteria consistency**, same family as `test_rust_fold_parity`),
  `test_722_condition_quality` (8 items), `test_722_aliases_thin` (11 items).

### Measured baseline (for comparison, not a promise)

Measured on this machine's library (32,845 nodes):

| Item | Reading |
|---|---|
| Recall count for natural phrasing | **2** |
| `aliases` coverage | **0%** |
| `role=None` in the `knowledge` layer (index cards) | **99.7%** |
| Share of effective conditions that are metadata | **76.5%** |

⇒ So the value of `aliases` depends on **whether it is actually written at write time**. Existing nodes in the library **do not gain it automatically**.

## [0.9.18] - 2026-10-30

### ⚠️ BREAKING: injected block format change

The line format of the `【本会话近期对话】` block now carries an **attribution prefix** (issue #712 / PR #713):

```
旧：[user] 内容
新：[10-30 14:23|本|私] [user] 内容
      └──┬──┘ └┬┘ └┬┘
       时间   会话 密级
```

| Segment | Value |
|---|---|
| Time | `MM-DD HH:mm`; missing renders `??-?? ??:??` |
| Session | equal to the current session → `本`; otherwise → `会话<后4位>`; missing → `?` |
| Sensitivity | `private`/`secret` → `私`; `public`/`internal`/`restricted` → `共`; missing → `?` |

**Why the change**: previously the model only saw `[role] content` and could not tell "is this what I just said, or something another session said, is it private or shared" -
a measured case existed of "quoting a line from another window as if the current user had just said it" (#712).

The block total length cap changed from `800 → 900` characters accordingly (the prefix costs about 20 characters per line).
**If you have parsers or assertions that depend on the old format, sync them.**

### Added

- **`cg(op=info).write_gate`** (#708): **in-process counters** for the layered write gate - `{mode, total, by_layer, recent, hint}`.
  Previously `warn` mode only wrote to the subprocess stderr, and DSH does not forward it ⇒ the observation period was effectively nothing.
  It now does not depend on stderr forwarding and does not write to disk; `recent` keeps only `layer/tier/reason` (**no content, no node ids**), bounded to 20 entries.
  Counters **reset to zero on restart**; observing one full working day before switching to `enforce` is recommended.
- **`Principal.sessions_read`** (#712 / option C tiered isolation): `None` = old behavior unchanged digit for digit; a set = read only those sessions;
  `{"*"}` = read all. **`can_admin` is not weakened** (issue #35 "Designer exemption" finalized).
- **Four event attribution elements**: `pack["recent"]` entries now contain `session`/`t`/`id`/`sensitivity`/`actor`/`token_id`/`identity_role`/`parent`.
  Events gain a stable key `id` (`re_<ms>_<6hex>`, **for attribution display only, must not be used for permission decisions or deduplication lookups**).
- **Theory document**: "Identity and Persona: the Variability of Professional Identity vs the Consistency of Persona"
  (`docs/theory/身份与人格_职业身份可变性与人格一致性_v0.1.md`) -
  distinguishes **persona** (constant across sessions, `self`/`anchor` layers) from **professional identity** (session level, working layer + event attribution).

### Fixes

- **Under `enforce`, the adjudication audit node was blocked by the same gate** (#708 ② / #709): `_write_review_record` writes `structural` (tier 2),
  yet did not pass the review units ⇒ `decisions.jsonl` remained, but **the reviewable md audit node was gone**.
  Now the `reviewed_by` already obtained by this adjudication is carried all the way into the write.
- **Two earlier gaps in the same chain** (found while investigating #709):
  - **`propose` deadlock**: a candidate entering the inbox is not persisted to the memory disk, yet review units were required according to the target layer ⇒
    under enforce, "writing knowledge needs reflect → reflect needs adjudication → adjudication needs a proposal → a proposal needs reflect".
    Now `require_layer_write(..., skip_gate=False)` adds that parameter, and **only** `propose` passes `True`;
    the layer allowlist and sensitivity check **still run as usual**, and `accept` persisting to disk still goes through the same gate.
  - **`accept` persisting a business node** did not pass `reviewed_by` ⇒ "adjudication passed, persist blocked".
- **`reviewed_by` no longer pollutes frontmatter**: it is **an input parameter of the write gate, not memory metadata**.
  Previously `kw.get()` read it without deleting it, so it landed in the node fm through `super().add(**kw)` (measured: `test_i50c`'s B1 key-by-key comparison reported `reviewed_by: null`).
  Now changed to `kw.pop()`.
- **`actor` was always None** (hollow identity attribution): in `MdCGSecure.remember_event`, `tenant`/`session`/`harness`/`unit`/`sensitivity`
  **all get values from principal**, but `actor` ("who said it") did not ⇒ the injection surface always received `actor` as None. Fixed.
- **Window-order bugs x2** (#712 / #715): both `session_recall` and `session_compact` **truncate the last N entries first, then filter by session**
  ⇒ under multi-session concurrency, this session's messages are pushed out of the window, and `session="A"` may get an **empty recent** (false negative, extremely hard to find).
  `session_compact` is worse - it compresses "0 events in total" and **writes it into a session node** (one wrong memory written).
  Fix: when narrowing is needed, fetch the full set first, then filter, then truncate back.
- **Falsy `session` silently falls back to the global window** (#712): it now adds `recent_global_window` in `degraded`, so callers can see it.
- **Identity block always empty** (#715): `【灵枢身份锚点】` reused the timeline payload **with session filtering**,
  while the `session` of `self`/`anchor` nodes is **always `unattributed`** ⇒ the permanent layers were all filtered out ⇒ **the block never appeared and no error was raised**.
  Now the identity block **fetches independently, without session filtering**; the "recent memory" block keeps session isolation.
  This is exactly the real case of theory R3: **the visibility of persona should not be decided by session**.
  An `else` branch with `logger.info` was also added - when the switch is on but there is no identity node, it says so explicitly instead of staying silent.
- **Falsy session id silently falls back to the global window** (PR #714 by LeeRolling): now `logger.warn` once (no flooding).

### Internal

- The code-reading anchor in `test/chaos_injection/test_fi_m09_guest_write_denied.py` was relaxed from "the full call string" to "both `layer, sens` parameters present",
  and two hard-coded line numbers were removed.
- `NEW_INFO_KEYS` in `test_generation_guard.py` registers `write_gate`.
- The mutation anchor in `test_p45_session_identity.py` was synced to the new shape (**mutation semantics unchanged**).
- New guards: `test_issue712_session_window_attribution` (29 items, covering window order / four elements / identity three dimensions / separation of powers),
  `test/issue715` (W715), `test/issue714` (W714 / W714b).

### Upgrade notes

- **The `--gate` default is still `strict`**; `op=info` only **adds** keys; `sessions_read` defaults to `None` = old behavior unchanged digit for digit.
- If you hit problems in #708 / #709: after upgrading, `cg(op="info")["write_gate"]` shows the warn counts,
  and **`record_error` in the return body of `review accept` should be empty**.
- If you hit problems in #712 / #715: after upgrading, injected blocks should carry the attribution prefix, and the identity block should appear when `autoRecallIdentity: true`.
## [0.9.17] - 2026-10-28

### Fixes

- **`warn` mode was completely invisible to users (#708 ①)**: `security._write_gate_verdict` only did `sys.stderr.write`, and DSH does not forward this
  into `desktop-next.log` ⇒ the observation period was effectively nothing. Now `writegate` keeps **in-process counters** and exposes them via `cg(op=info).write_gate`:

  ```python
  cg(op="info")["write_gate"]
  # {mode, total, by_layer: {"knowledge@L1": 3}, recent: [{layer,tier,reason}…], hint}
  ```

  It does not depend on stderr forwarding and does not write to disk; `recent` keeps only `layer/tier/reason` (**no content, no node ids**), bounded to 20 entries.
  The stderr line is kept (still visible in real time when the host is willing to forward it).

- **Under `enforce`, the adjudication audit node is blocked by the same gate (#708 ② / #709)**: `_write_review_record` writes `structural` (tier 2: needs reflect+verify),
  yet does not pass the review units ⇒ `decisions.jsonl` remains, but **the reviewable md audit node is gone**. Now the `reviewed_by`
  already obtained by this adjudication is carried all the way into the write: `review_decide → _finish_decision → _record_decision → _write_review_record → add(reviewed_by=…)`.

- **Two earlier landing points of the same hole (found while investigating #709, fixed together)**:
  - **`propose` deadlock**: a candidate entering the inbox is not persisted to the memory disk, yet review units are required by the **target layer** ⇒ under `enforce`,
    "writing knowledge needs reflect → reflect needs adjudication → adjudication needs a proposal → a proposal needs reflect".
    Now `require_layer_write(..., skip_gate=False)` adds that parameter, and **only** `propose` passes `True`;
    the layer allowlist and sensitivity check **run as usual** (only the write_gate stage is skipped), and `accept` persisting to disk still goes through the same gate.
  - **`accept` persisting a business node** does not pass `reviewed_by` ⇒ "adjudication passed, persist blocked". Now carried through together.

- **`reviewed_by` no longer pollutes frontmatter**: it is **an input parameter of the write gate, not memory metadata**. Previously `kw.get()` was used to read without deleting,
  so it landed in the node fm through `super().add(**kw)` (measured: `test_i50c`'s B1 key-by-key comparison reported `reviewed_by: null`). Now changed to `kw.pop()`.

### Internal

- The code-reading anchor in `test/chaos_injection/test_fi_m09_guest_write_denied.py` was relaxed from "the full call string" to "both `layer, sens` parameters present"
  (`require_layer_write` now has an extra `reviewers=` argument); two hard-coded line numbers were also removed - line numbers drift with changes.
- `NEW_INFO_KEYS` in `test_generation_guard.py` registers `write_gate` (the new diagnostic key of `op=info`, same class as `code_generation`).

### Upgrade notes

- This release **has no breaking changes**: `skip_gate` defaults to `False`; the `--gate` default is still `strict`; `op=info` only **adds** one `write_gate` key.
- If you hit problems in #708 / #709: after upgrading, `cg(op="info")["write_gate"]` shows the warn counts,
  and **`record_error` in the return body of `review accept` should be empty**.
- Counters are **accumulated in-process and reset to zero on restart** (not written to disk); observing one full working day before switching to `enforce` is recommended.
## [0.9.16] - 2026-10-28

### Fixes

- **`/lingshu` always returned 503 "host authentication unavailable" on DSH 0.2.1-rc.3 (#699)**: `createConsoleHandler` fetched `ctx.get('connection')` once **at mount time**,
  and cordis's `Context.get(name, strict=true)` returns `undefined` when the serving fiber is not ready -
  the empty value was frozen into the closure, so every request hit 503 and it did not self-heal even after the host became ready. Now it **fetches in real time on every request** (passing a getter function; a non-function is wrapped as a constant, for backward compatibility),
  and the 503 message changed to "the host authentication service is not ready yet, please retry later". 3 guards, and "the connection arrives late ⇒ the same handler immediately returns 200" is exactly the lesion point.
- **Test entry "zero-selected false green" (#1910 cross-repo report)**: the `--module` help taught the **slash** form (`md_cg/test_issue4`),
  while the actual target names use **dots** (`md_cg.test_issue4`), and the old implementation did not normalize ⇒ the slash form selected **zero targets** yet still printed `SUMMARY 0/0` + `rc=0`.
  Now normalized (slash ≡ dot, `.py` ignored, empty selector matches nothing) + **zero selections must not return 0** (execution path `rc=2`). 21 guards including a self-proof of discriminating power.
- **F26-13 `_primary_bound` comment did not match the implementation**: the `#637` comment promised "T3 trims when score>0", but the code only trims when `n_real == 0`.
  Measured: implementing the comment **breaks the "fallback includes cross-bucket nodes" contract of S1b/S7** (`test_retr_s1b`/`test_retr_s7` immediately turn red) ⇒
  confirmed that "no trimming by default" is a deliberate trade-off, changed to **align the comment with the implementation** and wrote the evidence into the comment (so later readers do not step on it again).
- **F26-25 Rust side missing accent folding**: `normalize_en` turned every non-ASCII non-Chinese character into a space ⇒ `café` → `caf`, while Python gives `cafe`.
  Constrained by `Cargo.toml`'s "zero third-party dependencies", changed to **follow the Python criteria** and generate a 963-entry single-character mapping table plus three-range combining-mark stripping;
  cross-implementation guards **29 items** checked item by item (including the boundary that `ß`/`ø` do not fold, and Japanese dakuten do not fold).

### Added

- **Gate level `--gate fast|strict` + `--module` filter** (`scripts/run_tests.py`):
  "fast = set the problem aside / slow = dig into the root cause" is a value trade-off, and **the choice is handed to the user**; not a single line changed on the guard side,
  and "whether to run heavy quality checks" is decided by the upper layer. Default `strict` (does not lower existing strength); **CI environment + `fast` automatically upgrades to strict** to prevent missed detection. 17 guards.
- **Config registry generator "add-only" protection** (`scripts/gen_config_registry.py`): a whole-file rewrite would erase manually added lines
  (measured incident: `MDCG_WARM_SEARCH`/`MDCG_VISION_ROOT` disappeared). Now, before writing to disk, it reads the old table's entry names with AST and refuses if one is missing (`rc=3`),
  with `--force` as an explicit escape hatch. 14 guards.
- **Audit gains a `source` key-name set dimension** (`src/lib/hook_audit.ts`): the key gap in #695 was that "which fields the event's `source` actually carries" was unobservable.
  A `source_shapes` bucket was added, recording **key names only, never values** (pinned by a sentinel guard). Measured on this machine, 383 sessions / 9,614 lines: the `user` tier takes 18.4%,
  of which 80.3% carry `rpcId` and **19.7% carry only `kind`** - this reading turns "source attribution" from a guess into something quantifiable.
- **Two silent fallbacks in `entry_from_row` made observable** (`md_cg/config_registry.py`): a `literal_eval` failure and a missing `value_type`
  previously left no trace at all (numeric registrations would silently be treated as strings). Two read entry points added, `literal_failures()` / `missing_value_types()`, with **zero behavior change**. 15 guards.

### Documentation

- **README 321 → 227 lines**: the "graphical interface" and "permissions" chapters were each compressed to ~14 lines (one-line positioning + minimal commands + one table + links),
  with details moved into [`docs/en/ops/ui-install-troubleshooting.md`](docs/en/ops/ui-install-troubleshooting.md) and [`docs/en/ops/permissions-review.md`](docs/en/ops/permissions-review.md).
  The README reader is "deciding within 30 seconds whether to use it"; details belong in `docs/`.

### Upgrade notes

- This release **has no breaking changes**: the `--gate` default is still `strict`; `createConsoleHandler` keeps the old "pass the value directly" calling style;
  both `--module` forms now work (the slash form previously selected zero targets).
- If you hit a constant 503 on `/lingshu` on DSH 0.2.1-rc.3: after upgrading **no extra action is needed**; it self-heals even if the service arrives late.
  If it is still 503, please reply with the `kinds` section of `$DSH_HOME/logs/dsh-memory-hook-audit.json` (no content).
## [0.9.15] - 2026-10-27

Theme: **permission layering and the review model land** (read/write/adjudicate layers each narrowable on its own) + one order-of-magnitude performance fix + two real "cannot install / cannot start" bugs.

### Added · Review model for writes and adjudication

- **Layered write strictness gate** (`MDCG_WRITE_GATE`, default `off`) - scenario/goal/unresolved/negative memory (tier 0) can be written directly without review;
  the knowledge layer needs a reflection unit; the structural layer needs reflection + verification; the self/anchor layer needs reflection + verification + **human adjudication**.
  **With no review channel at all, only tier 0 may be written**; everything else is refused.
- **Adjudication dual-unit review gate** (`MDCG_REVIEW_DUAL_CHECK`, default off) - adjudication must carry `reviewed_by` containing both a reflection unit and a verification unit;
  **duplicates of the same kind do not count as complete** (two reflections still lack verification); the adjudicator must not be the proposer (`self_review_forbidden`); unknown units are not silently counted.
- `MDCG_REVIEW_CHANNELS` (review channel declaration: `hive,subagent,team`). Note that it is a **deployment declaration**:
  empty only means "never declared", **not** that this machine has no subagents/hive/team.
- **Designer token coverage criteria** - `DESIGNER_COVERAGE_OPS` / `coverage_gap()` / `HIGH_RISK_OPS` / `high_risk_granted()`;
  `tokens verify` output appends `designer_coverage_gap`; at issue time, two kinds of hints, "narrowed and missing read surfaces" and "high-risk surfaces granted", are written into the return value `warnings`
  (the library layer does not write to stderr; the CLI entry prints them).

### Added · Graphical interface (optional add-on package)

- `ui/minimal/`: one-line install, per-file rollback, reusing the local brain bridge (data never leaves the machine);
  a seven-page panel (overview / memory / goals and tasks / self-knowledge / spatiotemporal relations / review and maintenance / toolbench).
- The `files` allowlist in `package.json` adds `ui` and `web`, so the installer, payload, and static assets **ship with the npm package**.
- **Wiring into the package**: `dsh.client` / `exports["./client"]` written into `package.json`, `installConsoleWeb(...)` written into `src/index.ts`;
  the artifacts are generated by the new `scripts/build_ui.py` (idempotent; `--check` only verifies and fails closed when files are missing; both `build` and `prepublishOnly` run it automatically).
  So **changing the plugin manifest no longer requires reinstalling the UI**; `install.ps1` now targets end users who go "from the npm package to the local plugin directory",
  and it still auto-completes plugin packages that predate the wiring. The guard `md_cg/test_ui_wiring_in_repo.py` (18 items) pins the declaration/distribution/build three faces against drift.

### Performance

- `protect.stats()` switched to **entry-based criteria** (reads the index, no longer reading frontmatter node by node):
  on the live library (32,000 nodes) the cold state went **310 s → 0.015 s**. This function is called unconditionally through the `protection` section of `cg(op=info)`,
  and was the root cause of the UI overview page "looking frozen"; after the fix the overview page went from the 5-minute level to the second level.
  Semantics unchanged: a full comparison of `protected` / `immutable` shows **diff 0**.

### Fixes

- **The UI add-on package could not be installed on Windows**: the payload was checked out as CRLF by `core.autocrlf`, mismatching `integrity.json` (sha256 recorded against LF),
  and the installer falsely reported "shared package files missing or corrupted". `.gitattributes` now pins `ui/minimal/payload/** eol=lf`.
- **hive serve would not start**: `{"env": "DEEPSEEK_API_KEY"}` in `config.local.json` reads the environment variable of the **calling process**,
  and DSH subprocesses do not inherit machine-level variables ⇒ a false "config item parse failed". A Windows machine-level fallback was added
  (an explicit process env value still wins; if both are empty it still fails fast).
- The config registry surface registers `MDCG_WRITE_GATE` / `MDCG_REVIEW_CHANNELS` / `MDCG_REVIEW_DUAL_CHECK`.

### Documentation

- README adds two chapters: "🖥️ Graphical interface (optional add-on package · for DSH)" and "🔐 Permissions: read / write / adjudicate, three layers, each narrowable on its own",
  covering which four of the seven pages are command panels, three troubleshooting items, the 17 read-surface ops, the layered write matrix, dual-unit adjudication, and the error reference table.

### Upgrade notes

- **The default values of the three new switches all keep the old behavior** (`MDCG_WRITE_GATE=off`, `MDCG_REVIEW_CHANNELS` empty, `MDCG_REVIEW_DUAL_CHECK` off)
  ⇒ behavior is unchanged after upgrading; they must be enabled explicitly. Recommended order: observe with `warn` first, then `enforce` after the review channels are connected.
- Designer tokens **do not widen because of an upgrade**; if your token was narrowed by hand, `tokens verify` reports `designer_coverage_gap` and names the missing surfaces.
- Windows users who previously could not install the UI can install it directly in this release.

### Known boundaries

- The write gate and the adjudication gate only recognize "review unit declarations"; they do not verify whether evidence is genuine (genuineness is countersigned on the hive/subagent side).
- Before `MDCG_WRITE_GATE=enforce`, declare `MDCG_REVIEW_CHANNELS` first, otherwise the knowledge layer and above (including automatic archiving) will be refused writes.
