> **Languages:** [中文](../../../zcode/README.md) · English

# ZCode side · LINGSHU integration configuration

This directory = **ZCode harness-specific configuration**. ZCode mirrors CodeBuddy: it **reads `AGENTS.md` at the project root at session start**
and injects it in full, so this side's artifact also uses the `full` variant.

## Directory contents

| File | Purpose | Nature |
|---|---|---|
| `AGENTS.md` | Full text of the 19 engineering discipline rules (injected at session start) | **Rendered artifact**; do not edit by hand |
| `README.md` | This file (integration guide) | Hand-written |

## Integration

Copy `zcode/AGENTS.md` to **the root of your project**; it takes effect in a new session.

Memory access on the ZCode side reuses the same MCP brain, configured the same way as CodeBuddy
(see [`../codebuddy/mcp.json`](../../../codebuddy/mcp.json) and [`../codebuddy/README.md`](codebuddy.md)); only change `MDCG_ACTOR` to `zcode`.

The same template contains a second MCP server, `hive` (Hive: multi-agent concurrency + task context management); merge it as well.
When ZCode and CodeBuddy point at the same repository, they **share the same concurrency pool**. For semantics and boundaries, see
'per-harness registration' in [`../hive/README.md`](../../../hive/README.md).

## Coexistence with CodeBuddy

They do not interfere: CodeBuddy reads `CODEBUDDY.md` at the root and ZCode reads `AGENTS.md` at the root;
if a project uses both sides, place each corresponding file there (the content is same-source, both rendered from the source of truth).

## Memory strategy

Same as the CodeBuddy side: **record only important content (core changes: content/reason/location/verification conclusion) + the conversation record**;
everything else is filtered by the write gate. See the 'Memory strategy' section of [`../codebuddy/README.md`](codebuddy.md).

## Maintenance (for LINGSHU maintainers)

- `AGENTS.md` is rendered by `scripts/render_discipline.py` from the **single source of truth**, `docs/工作纪律_认知图条目_v1.1.json`;
  see `docs/discipline/harnesses.yaml` for the matrix (`zcode` slot).
- Change the discipline -> change the source of truth -> run `python scripts/render_discipline.py --target zcode --write`
  -> `python scripts/verify_discipline.py --target zcode` passes -> commit.
- **Hand-editing `AGENTS.md` in this directory is flagged as drift by `verify_discipline.py`**.
