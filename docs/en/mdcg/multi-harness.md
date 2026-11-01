> **Languages:** [中文](../../mdcg/多harness接入.md) · English

# Multi-harness integration (five-endpoint differences)

> This page was split out of the former `README.md` (source: the former README section "Multi-harness integration" (L522–L561)).


## Main recommended path and five-endpoint comparison

### Multi-harness integration (directories per endpoint)

> **Main recommended path: MCP direct mount** — what the endpoints share is **mounting the same stdio MCP server** (`python -m md_cg.mcp_server`): any host that supports MCP can mount it directly, **with no dependency on any plugin system**.

The shared layer (`md_cg/` brain · `data/` · `docs/` · `scripts/`) sits at the repository root; **harness-specific configuration is filed per endpoint**, and the table below lists only the differences in each endpoint's **discipline injection method** (how discipline enters the context); the brain and the memory source of truth are unchanged:

> ⚠ **The boundary between the shipped surface and the source tree**: the npm package `files` only contains `lib/ src/ md_cg/ skills/ README.md dsh/ codebuddy/ zcode/ docs/`
> — `scripts/`, `hive/`, `swarm/`, `compiler/`, `rust/` belong to the **source tree** (release gate, hive runtime, Rust evaluator) and **do not exist** in the installed plugin. Therefore runtime dependencies must never point at them:
> the criterion-surface list goes through the in-package `md_cg/judgment_manifest.py` (called in-process by `md_cg/interop.py`),
> the adjudication CLI goes through the in-package `python -m md_cg.review_cli`, and the full test run goes through the in-package `python -m md_cg.run_tests`;
> **tests** that depend on `scripts/`/`hive/` are handled according to the actual run shape when pieces are missing (never reporting a false pass): in the **installed state** (`scripts/`/`hive/`/`swarm/`/`compiler/` absent) the suite discovers by existence and naturally has no targets for those groups; in the **source tree**, suites that need Rust build artifacts (such as `md_cg.test_rank_parity_score_mode`) **fail-closed FAIL** when not built (printing the rebuild guidance `cd rust && cargo build --release`); an honest SKIP is used only for three categories — guard success passes that depend on an unbuilt hive binary (`scripts/test_utf8_boot_guard.py` etc., with per-item reasons and not counted as passes), missing gitignored local data (p44 etc.), and platform mismatch (Windows-only pieces on non-Windows).

## Five endpoints, discipline from the same source

> The five endpoints' discipline is **from the same source** (`docs/工作纪律_认知图条目_v1.1.json`), rendered by `scripts/render_discipline.py` and guarded against drift by `scripts/verify_discipline.py`; the matrix is in `docs/discipline/harnesses.yaml`.

## Optional supplement: plugin-form installation

<details>
<summary><b>Optional supplement: plugin-form installation (Claude Code / Codex CLI only · saves manual copying, not the main recommended path)</b></summary>

> Equivalent to configuring manually per the table above, except that the discipline skill and the configuration samples come with the plugin; **not installing the plugin does not affect any capability**.

| Host | Install | Plugin location | One step after install |
|---|---|---|---|
| Claude Code | `/plugin marketplace add FuRongJun-1999/dsh-memory` → `/plugin install lingshu-memory@lingshu` | `claude/lingshu-memory/` (discipline is distributed as a skill; `/lingshu-memory:linglu-discipline` can be invoked explicitly) | Copy the plugin's `mcp.json.example` to `.mcp.json` at the project root and fill in `PYTHONPATH` |
| Codex CLI | `codex plugin marketplace add <repo path>` → `codex plugin add lingshu-memory@lingshu` | `codex/lingshu-memory/` (the skill loads progressively in three levels; `.codex-plugin/plugin.json` manifest) | Merge the two sections of the plugin's `config.toml.example` into `~/.codex/config.toml` and fill in `PYTHONPATH` |

> marketplace manifests: the Claude side is at the repository root `.claude-plugin/marketplace.json`, the Codex side at the repository root
> `.agents/plugins/marketplace.json`. The plugin does not contain the brain itself (`md_cg/` is not distributed with the plugin) — once MCP is installed,
> the brain is still your local dsh-memory repository; the plugin-form discipline skill is likewise rendered from the source of truth (the `skill` variant,
> matrix slots `claude-code-plugin-skill` / `codex-plugin-skill`), and drift is guarded by the same `verify_discipline.py`.

</details>
