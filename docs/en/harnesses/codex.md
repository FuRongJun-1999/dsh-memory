> **Languages:** [中文](../../../codex/README.md) · English

# Codex side · LINGSHU integration configuration

This directory = **Codex CLI harness-specific configuration**. Codex (OpenAI Codex CLI) **reads `AGENTS.md` at the project root at session start**
(it also supports global injection via `~/.codex/AGENTS.md`), so this side's artifact uses the `full` variant and mirrors ZCode.

## Directory contents

| File | Purpose | Nature |
|---|---|---|
| `AGENTS.md` | Full text of the 19 engineering discipline rules (injected at session start) | **Rendered artifact**; do not edit by hand |
| `config.toml.example` | LINGSHU integration template: two MCP servers, `mdcg` (memory brain) + `hive` (Hive concurrency), to merge into `~/.codex/config.toml` | Template |
| `README.md` | This file (integration guide + memory strategy) | Hand-written |

## Three-step integration

### 1. Connect the memory brain (MCP)

Merge the `[mcp_servers.mdcg]` / `[mcp_servers.mdcg.env]` sections of `config.toml.example` into
`~/.codex/config.toml`, then replace the `PYTHONPATH` placeholder
(`REPLACE_WITH_ABSOLUTE_PATH_TO_dsh-memory`) with **the directory where the dsh-memory repository sits on your machine**.
This must be a resolvable absolute path: Python uses it to locate the `md_cg` package inside the repository, and a relative path
breaks when the process working directory changes.

For the tool surface, see [`../codebuddy/README.md`](codebuddy.md): `MDCG_MCP_SURFACE=kernel`
exposes only the two cognitive primitives `cg` / `stg`; `cg` already covers every op such as `route` / `read` / `write`,
so **the write path is not missing**. The `md_cg` brain ships with the repository, so no engine needs to be installed with pip.

#### 1b. Connect Hive (multi-agent concurrency + task context management)

Also merge the same-source `[mcp_servers.hive]` and `[mcp_servers.hive.env]` from `config.toml.example` into
`~/.codex/config.toml`: four tools `hive_spawn` / `hive_poll` / `hive_kill` / `hive_doctor`
provide **concurrent execution shared across harnesses** and **task context management** (`context_files` injection, resuming on returned budget,
progress card observation). For semantics and boundaries, see [`../hive/README.md`](../../../hive/README.md), section 'per-harness registration'.
**Deterministic tasks (running commands / tests) are not on the MCP surface**; use the CLI:
`hive/target/release/hive.exe submit --spec <spec.json>`.

### 2. Inject the engineering discipline

Copy `codex/AGENTS.md` to **the root of your project** (Codex reads it automatically at session start); it takes effect in a new session.
To apply it to all projects, put it in `~/.codex/AGENTS.md` (global injection, affects every session, use with care).

> This repository deliberately keeps the artifact in the `codex/` subdirectory and **does not put it at the root**: the repository-root `AGENTS.md`
> is a local private carrier (it contains machine operations notes and is ignored by `.gitignore`), and putting the artifact at the root would overwrite it.

### 3. Restart the session

The discipline is **injected in full once at session start**; after a change you must create a new session for it to take effect.

## Memory strategy: record what matters, not the stream

Same as the CodeBuddy / ZCode sides: **record only core changes (content / reason / location / verification conclusion) + the conversation record**;
never write intermediate process / trial-and-error steps / debugging details. The Codex side has no session hook for automatic memory,
so memory capture is driven by explicit archiving under discipline rule 16 (`cg(op=write, gated=true)` passes the three-question four-state gate).
See the 'Memory strategy' section of [`../codebuddy/README.md`](codebuddy.md).

## Write credentials (determines whether data actually persists)

`md_cg` is **fail-closed**: without a token it runs as a **read-only guest**, so reads / recall / timelines work as usual,
but memory writes **do not persist**. Issue a token (designer is the only role that can manage, with `clearance_cap=secret`):

```bash
python -m md_cg.tokens issue --role designer --actor codex
```

Put the returned plaintext token into `[mcp_servers.mdcg.env]` in `~/.codex/config.toml`:

```toml
MDCG_TOKEN = "<签发返回的明文令牌>"
```

> **Do not treat `ok: true` as a successful write**: when nothing persists, the response body looks like
> `{"ok": true, "committed": false, "moved_to": "review_queue"}`; whether data persisted **depends only on `committed`**.

## Coexistence with other sides

Codex / ZCode both read the project-root `AGENTS.md`, and their content is same-source (rendered from the same source of truth), so copying either one is enough;
CodeBuddy reads `CODEBUDDY.md` at the root, and Claude Code reads `CLAUDE.md` at the root. The file names
do not conflict, so the sides can coexist without interfering.

## Maintenance (for LINGSHU maintainers)

- `AGENTS.md` is rendered by `scripts/render_discipline.py` from the **single source of truth**, `docs/工作纪律_认知图条目_v1.1.json`;
  see `docs/discipline/harnesses.yaml` for the matrix (`codex` slot).
- Change the discipline -> change the source of truth -> run `python scripts/render_discipline.py --target codex --write`
  -> `python scripts/verify_discipline.py --target codex` passes -> commit.
- **Hand-editing `AGENTS.md` in this directory is flagged as drift by `verify_discipline.py`**.
