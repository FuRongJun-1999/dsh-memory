> **Languages:** [中文](../../ops/README.md) · English

# ops/ · Installation and operations

| Document | Content |
|---|---|
| [Installation and prerequisites](install.md) | One-command setup / manual three steps / prerequisites (Node, Python, and DSH versions) / verified environments / post-install verification / automatic memory scope / troubleshooting clues |
| [Environment and known issues](environment-known-issues.md) | DSH Desktop startup warnings (host side) / size and whole-directory coupling / **persistence timing (nodes sync, indexing is async #677 P2, plus three exits)** / **timeout is not failure: check before writing (#677 P1)** / Windows rmtree quirks / **design tradeoffs (not bugs)** |
| [Operations and troubleshooting](operations-troubleshooting.md) | Restart the long-running process after an upgrade (proxy verification of five fields) / write credentials and `committed` semantics / common questions (FAQ) |

> Domain assignment rules are in the [docs/ directory index](../README.md).
