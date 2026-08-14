---
title: "Plugin: @furongjun1999/dsh-memory — Lingshu (灵枢) memory & cognition bridge, a full 'brain' for your agents"
---

## 🧠 Lingshu Brain — DeepSeek Harness plugin

**@furongjun1999/dsh-memory** gives any DSH agent a complete cognitive "brain": cross-session long-term memory, knowledge flywheel, self-cognition, recursive reflection, and an importance-gated long-term memory system — **without requiring any local devices** (lightweight "brain mode", body excluded).

### Install

```bash
npm i @furongjun1999/dsh-memory
```

cordis.yml:

```yaml
- id: lingshu-memory
  name: '@furongjun1999/dsh-memory'
  config:
    serverName: 'lingshu'
    dbPath: 'D:/data/lingshu.db'   # SQLite, auto-created
    tools: 'brain'                # 'brain' | 'core' | 'all' | [tool names]
```

### What the agent gains (34 brain tools)

| Module | Tools |
|---|---|
| Memory | `lingshu_remember` `recall` `search` `timeline` `session_note` `session_recall` `compact_context` |
| Reasoning | `think` `relate` `reason` `predict_routes` |
| Cognition | `self_check` `gap_trend` `cognition` `cognition_report` `emotional_bias` `self_reliability` `action_log` `preflight` |
| Reflection | `recursive_reflect` |
| Learning | `blindspots` `learn` `induce` |
| Flywheel | `distill` `flywheel_report` `transfer_test` `calibrate` |
| Long-term memory gate | `longterm_snapshot` `promote_memories` — importance evaluation (info-gap / trust / second-order change / mention count) decides what becomes permanent |
| Ingest | `ingest_text` `ingest_file` `ingest_url` `web_search` |
| Lifecycle | `step` `lifecycle_state` |

### Design highlights

- **Auto-memory**: conversations are automatically persisted into the Lingshu memory database (deduplicated, importance-weighted).
- **Dynamic schema**: tool list is pulled live from the memory engine at runtime — engine upgrades appear with zero plugin changes.
- **Zero runtime deps**: hand-written stdio MCP bridge (no MCP SDK), same philosophy as the engine's zero-dependency core.
- **Self-healing**: the bridge process auto-restarts with exponential backoff (1s→30s).
- **Charter-governed**: activating the plugin declares acceptance of the **Lingshu Guardrail Charter** (public, enforceable, auditable rules; designee final arbitration; human protection chapter) — see the repo docs.

### Repo

https://github.com/FuRongJun-1999/CommonTrustProtocol/tree/master/plugins/dsh-memory

MIT licensed. Feedback, issues and PRs welcome — this is an open invitation to give agents a persistent self.
