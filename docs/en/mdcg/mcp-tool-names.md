> **Languages:** [中文](../../mdcg/MCP工具名口径_v1.0.md) · English

# MCP tool name basis v1.0 (the single authoritative table)

> Purpose: eliminate the **first-recognition errors** caused by "the same tool having different names on different endpoints". Whenever any endpoint, any document, or any injected section references a tool name, this table prevails.
> Registration date: 2026-10-19 | Basis: `md_cg/mcp_server.py` (TOOLS definitions) and actual reads of each endpoint's configuration files.

## 1. Standard names (the only ones)

| Layer | Standard name | Source (true origin) |
| --- | --- | --- |
| **MCP service name** | **`mdcg`** | The server key in `codebuddy/mcp.json` is already `mdcg`; `md_cg/mcp_server.py` is that service itself |
| Main tool (cognitive map) | **`cg`** | The TOOLS definitions in `md_cg/mcp_server.py` |
| Main tool (semantic spatiotemporal graph) | **`stg`** | Same as above |
| Fine-grained tools | **`mdcg_*`** (`mdcg_remember` / `mdcg_recall` / `mdcg_search` / `mdcg_get` / `mdcg_reflect` / `mdcg_verify` / `mdcg_propose` / `mdcg_rejected` / `mdcg_unresolved` …) | Same as above (actual read hits) |

## 2. No tool name prefix is allowed (Designer ruling A, 2026-10-19)

**All hosts use the same MCP service, so tool names must be identical character for character; "aliases / prefix mapping" do not exist and are not allowed.**

- Counter-example (already removed): the DSH plugin previously used `` ``toolPrefix: `${config.serverName}_` `` `` to register `cg` as `lingshu_cg`,
  causing the first-recognition error of "the same MCP service, different tool names on different endpoints"; that prefix was removed in `src/index.ts` (commit `f7afd2a1`).
- `serverName` (default `lingshu`) is still used for the internal provider / log identity and **must not** participate in tool names any more.
- If any endpoint needs a "namespace" to avoid conflicts with host-owned tools, it may only rename **host-owned tools**, never md_cg tool names.
## 3. Existing deviation points (actual read this round, to be fixed point by point)

| File | Current state | Should become |
| --- | --- | --- |
| `dsh/cordis.yml.example` | Contains `lingshu_cg` / `lingshu_stg` | Keep them (host display names), but **annotate the standard names** `cg` / `stg` alongside; or reference this table in a comment |
| `codex/AGENTS.md` | Contains both `lingshu_cg` (2 times) and `cg` (9 times) | Unify the wording: use the standard names `cg`/`stg` in body text, and write the `lingshu_` prefix mapping only where "DSH host display name" is meant |
| `src/index.ts` | Residual `lingshu_remember` (1 place) | Check whether it is a historical alias; delete it if it is a dead reference, or add a comment pointing to this table if it is a compatibility mapping |

## 4. Usage rules

1. **New documents / new injected sections**: always use the standard names; when a host display name must be mentioned, the standard name **must** be given at the same time (`lingshu_cg` = host prefix + `cg`).
2. **System prompts / discipline injection**: where tool names are involved, reference this table; do not write a separate set each time.
3. **Gate**: when adding tool names, `md_cg/op_table.py` and `md_cg/mcp_server.py` are the only true sources; on the documentation side, `cogmap_sync.py check` guards against drift.

## 5. Non-applicable conditions

- Does not cover host **own** tools (such as DSH's `run_code`, `agent_teams_*`, `hive_*`) — those are outside the md_cg naming surface;
- Does not change the behavior or parameters of any tool, only unifies **naming and references**;
- Apart from the in-endpoint display form (case, separators), this document contains no protocol changes.