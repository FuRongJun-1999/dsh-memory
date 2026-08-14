# dsh-memory · 灵枢（Lingshu）时空记忆图插件

[![Protocol](https://img.shields.io/badge/Protocol-Intelligentics%20v3.2-blue)](https://github.com/FuRongJun-1999/CommonTrustProtocol)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![npm](https://img.shields.io/npm/v/@furongjun1999/dsh-memory)](https://www.npmjs.com/package/@furongjun1999/dsh-memory)

**Multi-agent spatiotemporal memory graph for DeepSeek Harness.**
Cross-session persistence, knowledge flywheel, importance-gated memory — trust governed by an auditable charter.

灵枢（Lingshu）的完整大脑接入 DeepSeek Harness：多智能体时空记忆图——跨会话持久化、知识飞轮、自我认知与重要性门控的长期记忆写入。

## Install

```bash
npm i @furongjun1999/dsh-memory
```

cordis.yml:

```yaml
- id: dsh-memory
  name: '@furongjun1999/dsh-memory'
  config:
    serverName: 'lingshu'
    dbPath: 'D:/data/lingshu.db'   # SQLite, auto-created
    tools: 'brain'                 # 'brain' | 'core' | 'all' | [tool names]
```

## What it gives your agent (34 brain tools)

| Module | Tools |
|---|---|
| Memory | `lingshu_remember` `recall` `search` `timeline` `session_note` `session_recall` `compact_context` |
| Reasoning | `think` `relate` `reason` `predict_routes` |
| Cognition | `self_check` `gap_trend` `cognition` `cognition_report` `emotional_bias` `self_reliability` `action_log` `preflight` |
| Reflection | `recursive_reflect` |
| Learning | `blindspots` `learn` `induce` |
| Flywheel | `distill` `flywheel_report` `transfer_test` `calibrate` |
| Long-term memory gate | `longterm_snapshot` `promote_memories` |
| Ingest | `ingest_text` `ingest_file` `ingest_url` `web_search` |
| Lifecycle | `step` `lifecycle_state` |

## Design highlights

- **Spatiotemporal memory graph**: knowledge carries spatiotemporal coordinates and condition spaces — not a flat store.
- **Multi-agent**: shared memory across instances, sub-agents, and the swarm.
- **Importance-gated memory**: an evaluation (info-gap, trust, second-order change, mention count) decides what becomes permanent — long-term memory gate.
- **Knowledge flywheel**: verify → induce → relate → distill → predict.
- **Auto memory hooks**: conversations persist automatically (deduplicated, importance-weighted).
- **Seed memory**: empty databases auto-sync the Lingxu base profile (identity / protocol core / charter / values) from the central repository on first run.
- **Zero runtime deps**: hand-written stdio MCP bridge (no MCP SDK).
- **Self-healing**: bridge process auto-restarts with exponential backoff.
- **Charter-governed**: activating the plugin declares acceptance of the [Lingshu Guardrail Charter](https://github.com/FuRongJun-1999/CommonTrustProtocol/blob/main/docs/guardrail-charter.md) (public, auditable, designee-final; human-protection chapter).

## Protocol & governance

This plugin is the engineering-layer projection of the Intelligentics protocol (v3.2), whose theoretical layer lives in [CommonTrustProtocol](https://github.com/FuRongJun-1999/CommonTrustProtocol). Same structure, different condition space: protocol = self-constraint (constitution), charter = external constraint (law).

MIT licensed. Feedback, issues and PRs welcome.
