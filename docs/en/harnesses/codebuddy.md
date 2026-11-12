> **Languages:** [中文](../../../codebuddy/README.md) · English

# CodeBuddy side · LINGSHU integration configuration

This directory = **CodeBuddy harness-specific configuration** (LINGSHU = the Lingshu memory system). It is a peer of `dsh/` and `zcode/`;
the shared layer (`md_cg/` brain, `data/`, `docs/`, `scripts/`) lives at the repository root and belongs to no single side.

## Directory contents

| File | Purpose | Nature |
|---|---|---|
| `CODEBUDDY.md` | Full text of the 19 engineering discipline rules (injected at session start) | **Rendered artifact**; do not edit by hand |
| `mcp.json` | LINGSHU integration template: two MCP servers, `mdcg` (memory brain) + `hive` (Hive concurrency), to copy into CodeBuddy settings | Template |
| `README.md` | This file (integration guide + memory strategy) | Hand-written |

## Three-step integration

### 1. Connect the memory brain (MCP)

Merge the `mcpServers.mdcg` section of `mcp.json` into the CodeBuddy MCP configuration, then replace
the `PYTHONPATH` placeholder (`REPLACE_WITH_ABSOLUTE_PATH_TO_dsh-memory`) with **the directory where the dsh-memory repository sits on your machine**.
This must be a resolvable absolute path: Python uses it to locate the `md_cg` package inside the repository, and a relative path breaks when the process working directory changes.

The `md_cg` brain ships with the repository, so **no engine needs to be installed with pip**; you only need Python and Node ≥ 22.19 on the machine.

> **Tool surface `MDCG_MCP_SURFACE=kernel`** (matches the default in `md_cg/mcp_server.py`): only the two cognitive primitives `cg` /
> `stg` are exposed; `cg` already covers every op such as `route` / `read` / `write`, so **the write path is not missing**.
> The fine-grained `mdcg_*` tools are visible only on the `full` surface and serve compatibility / debugging purposes; day-to-day integration does not need them enabled.

#### 1b. Connect Hive (multi-agent concurrency + task context management)

Also merge the second, same-source `mcpServers.hive` entry in `mcp.json`: four tools `hive_spawn` / `hive_poll` /
`hive_kill` / `hive_doctor` provide **concurrent execution shared across harnesses** and **task context management**
(`context_files` injection, resuming on returned budget, progress card observation). For semantics and boundaries, see
'per-harness registration' in [`../hive/README.md`](../../../hive/README.md).

> This depends on the Rust-side `hive.exe` and `hive/config.local.json` (executor key). If it has not been built yet, run
> `cd hive && cargo build --release`; if `cargo` is not on PATH, use the absolute path
> `"%USERPROFILE%\.cargo\bin\cargo.exe" build --release --manifest-path hive/Cargo.toml`;
> the first `hive_spawn` starts `serve` automatically in detached mode.
> **Deterministic tasks (running commands / tests) are not on the MCP surface**; use the CLI:
> `hive/target/release/hive.exe submit --spec <spec.json>`.

### 2. Inject the engineering discipline

Copy `CODEBUDDY.md` to **the root of your project**.

> CodeBuddy rule precedence: when `CODEBUDDY.md` exists at the root, `AGENTS.md` is **ignored**.
> This repository deliberately keeps the artifact in the `codebuddy/` subdirectory and **does not put it at the root**,
> because the repository-root `AGENTS.md` is a local private carrier (it contains machine operations notes and is ignored by `.gitignore`).
> Keeping it in the subdirectory lets external users take it directly without hiding the local discipline.

### 3. Restart the session

The discipline is **injected in full once at session start**; after a change you must create a new session for it to take effect.

## Memory strategy: record what matters, not the stream

LINGSHU is a memory system, but **recording everything is the same as recording nothing**, so the write side has two mechanical filters rather than relying on human discipline:

| Layer | Content | Landing point | Filter |
|---|---|---|---|
| **Important content** | Core changes: content / reason / location / verification conclusion | `knowledge` / `self` layer | `cg(op=write, gated=true)` passes the **three-question four-state gate**; anything other than `ACCEPT` does not persist |
| **Conversation record** | Session transcript | `contextual` layer | The active forgetting gate automatically `DROP`s low-entropy noise by importance threshold |

- **Rule 16** requires archiving core changes at the end of every task: this is the closed-loop entry from conversation to long-term memory.
- **Never** write intermediate process / trial-and-error steps / debugging details / repeated confirmations; such content pollutes retrieval and interferes with later recall.
- The CodeBuddy side **has no** session hook for automatic memory like DSH, so memory capture is driven by discipline (the agent explicitly calls
  `cg(op=write, gated=true)` at the end) rather than by automatic process capture.

## Write credentials (determines whether data actually persists)

`md_cg` is **fail-closed**: without credentials the plugin runs as a **read-only guest**, so reads / recall / timelines work as usual,
but memory writes **do not persist**. To persist, issue a token:

```bash
python -m md_cg.tokens issue --role designer --actor codebuddy --clearance internal ^
  --ops-allow info,route,read,write,recent,goal,identity,whitebox,verify ^
  --layers-allow knowledge,contextual,structural,self,goals,unresolved,rejected
```

Then put `MDCG_TOKEN` into the `env` of `mcp.json` (or set a system environment variable and reference it).

> **Do not treat `ok: true` as a successful write**: when nothing persists, the response body looks like
> `{"ok": true, "committed": false, "moved_to": "review_queue"}`; whether data persisted **depends only on `committed`**.

## Maintenance (for LINGSHU maintainers)

- `CODEBUDDY.md` is rendered by `scripts/render_discipline.py` from the **single source of truth**, `docs/工作纪律_认知图条目_v1.1.json`;
  see `docs/discipline/harnesses.yaml` for the matrix (`codebuddy` slot).
- Change the discipline -> change the source of truth -> run `python scripts/render_discipline.py --target codebuddy --write`
  -> `python scripts/verify_discipline.py --target codebuddy` passes -> commit.
- **Hand-editing `CODEBUDDY.md` in this directory is flagged as drift by `verify_discipline.py`**.
