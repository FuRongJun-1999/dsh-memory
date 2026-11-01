> **Languages:** [中文](../../../claude/README.md) · English

# Claude Code side · LINGSHU integration configuration

This directory = **Claude Code (Anthropic) harness-specific configuration**. Claude Code **reads `CLAUDE.md` at the project root at session start**
(it also supports global injection via `~/.claude/CLAUDE.md` and the private `CLAUDE.local.md` addition),
so this side's artifact uses the `full` variant and mirrors the ZCode / Codex sides.

## Directory contents

| File | Purpose | Nature |
|---|---|---|
| `CLAUDE.md` | Full text of the 19 engineering discipline rules (injected at session start) | **Rendered artifact**; do not edit by hand |
| `mcp.json.example` | LINGSHU integration template: two MCP servers, `mdcg` (memory brain) + `hive` (Hive concurrency), to save as `.mcp.json` at the project root | Template |
| `README.md` | This file (integration guide + memory strategy) | Hand-written |

## Three-step integration

### 1. Connect the memory brain (MCP)

Copy `mcp.json.example` to the root of your project and **rename it to `.mcp.json`**, then replace the `env.PYTHONPATH`
placeholder (`REPLACE_WITH_ABSOLUTE_PATH_TO_dsh-memory`) with **the directory where the dsh-memory repository sits
on your machine**. This must be a resolvable absolute path: Python uses it to locate the `md_cg` package inside the repository,
and a relative path breaks when the process working directory changes.

You can also register it with the built-in Claude Code command (equivalent effect):

```bash
claude mcp add mdcg --env PYTHONPATH=<本机 dsh-memory 绝对路径> --env MDCG_MCP_SURFACE=kernel \
  --env MDCG_ACTOR=claude-code -- python -m md_cg.mcp_server
```

For the tool surface, see [`../codebuddy/README.md`](codebuddy.md): `MDCG_MCP_SURFACE=kernel`
exposes only the two cognitive primitives `cg` / `stg`; `cg` already covers every op such as `route` / `read` / `write`,
so **the write path is not missing**. The `md_cg` brain ships with the repository, so no engine needs to be installed with pip.

#### 1b. Connect Hive (multi-agent concurrency + task context management)

Also write the second, same-source `mcpServers.hive` entry from `mcp.json.example` into `.mcp.json`: four tools
`hive_spawn` / `hive_poll` / `hive_kill` / `hive_doctor` provide **concurrent execution shared across harnesses** and
**task context management** (`context_files` injection, resuming on returned budget, progress card observation). Or register it with a command (equivalent effect):

```bash
claude mcp add hive --env PYTHONPATH=<本机 dsh-memory 绝对路径> -- python -m hive.hive_mcp.mcp_server
```

For semantics and boundaries, see [`../hive/README.md`](../../../hive/README.md), section 'per-harness registration'. **Deterministic tasks
(running commands / tests) are not on the MCP surface**; use the CLI: `hive/target/release/hive.exe submit --spec <spec.json>`.

### 2. Inject the engineering discipline

Copy `claude/CLAUDE.md` to **the root of your project** (Claude Code reads it automatically at session start);
it takes effect in a new session. To apply it to all projects, put it in `~/.claude/CLAUDE.md` (global injection, affects every session, use with care).

> This repository deliberately keeps the artifact in the `claude/` subdirectory and **does not put it at the root**: the repository-root `AGENTS.md` is a local private carrier
> (it contains machine operations notes and is ignored by `.gitignore`); and Claude Code only recognizes `CLAUDE.md` and does not read
> `AGENTS.md`, so its file name does not conflict with CodeBuddy (`CODEBUDDY.md`) / Codex (`AGENTS.md`).
> Multiple sides can coexist at the same project root without overwriting each other.

### 3. Restart the session

The discipline is **injected in full once at session start**; after a change you must create a new session for it to take effect.

## Memory strategy: record what matters, not the stream

Same as the CodeBuddy / Codex sides: **record only core changes (content / reason / location / verification conclusion) + the conversation record**;
never write intermediate process / trial-and-error steps / debugging details. The Claude Code side has no session hook for automatic memory,
so memory capture is driven by explicit archiving under discipline rule 16 (`cg(op=write, gated=true)` passes the three-question four-state gate).
See the 'Memory strategy' section of [`../codebuddy/README.md`](codebuddy.md).

## Write credentials (determines whether data actually persists)

`md_cg` is **fail-closed**: without a token it runs as a **read-only guest**, so reads / recall / timelines work as usual,
but memory writes **do not persist**. Issue a token (designer is the only role that can manage, with `clearance_cap=secret`):

```bash
python -m md_cg.tokens issue --role designer --actor claude-code
```

Put the returned plaintext token into `env` in the project-root `.mcp.json`:

```json
"MDCG_TOKEN": "<签发返回的明文令牌>"
```

> **Do not treat `ok: true` as a successful write**: when nothing persists, the response body looks like
> `{"ok": true, "committed": false, "moved_to": "review_queue"}`; whether data persisted **depends only on `committed`**.

## Coexistence with other sides

Claude Code reads `CLAUDE.md` at the project root, CodeBuddy reads `CODEBUDDY.md`, and Codex / ZCode read
`AGENTS.md`: the file names do not conflict and can coexist at the same project root; the content is same-source (rendered from the same source of truth), so copying either one is enough.

## Maintenance (for LINGSHU maintainers)

- `CLAUDE.md` is rendered by `scripts/render_discipline.py` from the **single source of truth**, `docs/工作纪律_认知图条目_v1.1.json`;
  see `docs/discipline/harnesses.yaml` for the matrix (`claude-code` slot).
- Change the discipline -> change the source of truth -> run `python scripts/render_discipline.py --target claude-code --write`
  -> `python scripts/verify_discipline.py --target claude-code` passes -> commit.
- **Hand-editing `CLAUDE.md` in this directory is flagged as drift by `verify_discipline.py`**.
