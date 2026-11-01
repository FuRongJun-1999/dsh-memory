# Translation glossary

> **Languages:** [中文](../README.md) · English

This glossary fixes the English vocabulary for the LINGSHU documentation. Use it consistently across every translated page. When a term is missing, add it here in the same pull request instead of inventing a synonym.

## Product and architecture

| Chinese | English | Notes |
| --- | --- | --- |
| 灵枢 | LINGSHU | Product name. Never translate as "spiritual pivot". |
| 认知图 | cognitive map | The graph of memory, verification, reflection, and connection units. |
| 记忆卡 | memory card | A typed unit stored in the cognitive map. |
| 记录单元 | recording unit | Unit kind that stores raw observations. |
| 验证单元 | verification unit | Unit kind that records evidence and verdicts. |
| 反思单元 | reflection unit | Unit kind that records reflection. |
| 召回 | recall | Retrieve units by intent, not a raw search. |
| 检索 | retrieval | Lookup inside a single surface. |
| 落盘 | persist to disk | Write durable state. |
| 提交 | committed | Git commit or durable write, depending on context. |
| 闸门 | gate | Automated acceptance check. |
| 裁决 | adjudication / adjudicate | Formal verdict on a claim. |
| 白箱 | white-box | Inspectable internal state. |
| 蜂群 | swarm | Multi-agent execution mode. |
| 蜂巢 | hive | Concurrency engine and isolation layer. |
| 蜂巢并发引擎 | Hive concurrency engine | Capitalize Hive. |
| 世界模型 | world model | Predictive model of the workspace. |
| 语义时空图 | semantic spatiotemporal graph | STG. |
| 条件空间 | condition space | The set of conditions that make a unit valid. |
| 生效条件 | effective condition | Condition under which a rule is active. |
| 名实校验 | name-reality validation | Check that a claimed name matches observable behavior. |
| 写入别名 | write aliases | Accepted alternative names for write operations. |
| 口径 | measurement basis | The agreed definition used by a metric or contract. |
| 证据链 | evidence chain | Ordered evidence supporting a claim. |
| 双实例互验 | dual-instance cross-verification | Two independent instances check each other. |
| 静默降级 | silent degradation | A capability quietly stops working. |
| 灵枢大脑 | Lingshu Brain | Capitalize both words. |
| 设计者 | Designer | Capitalize when it names the trust tier. |
| 护栏宪章 | Guardrail Charter | Capitalize as a document title. |
| 工作纪律 | Engineering Discipline | Capitalize as a document title. |
| 协议实例 | protocol instance | |
| 子代理 | subagent | |
| 外部代理 | external agent | |
| 只读层 | read layer | |
| 写入层 | write layer | |
| 验证层 | verify layer | |
| 设计层 | design layer | |
| 访客 | guest | Permission role. |
| 设计者权限 | Designer permission | |
| 一致性 | consistency | |
| 漂移 | drift | |
| 回填 | backfill | |
| 迁移 | migration | |
| 灰度 | canary / gradual rollout | Prefer "canary" for releases. |
| 复盘 | retrospective | |
| 闭环 | closed loop | |
| 抓手 | lever | Avoid literal "grip". |
| 颗粒度 | granularity | |
| 底层逻辑 | underlying logic | |
| 对齐 | align | |
| 拉通 | align across teams | |
| 落地 | land / ship | Prefer "land" for plans, "ship" for releases. |

## Tool and protocol names

Keep these tokens unchanged in prose, code spans, and links:

- Tools: cg, stg, mdcg_*, md_cg, mcp_server, tools, init, recall, verify, review, protect, sustain, scrub, consolidate, insight, ccg, edges, audit.
- Modes: core, brain, all.
- Paths and commands: python -m md_cg.mcp_server, npx @furongjun1999/dsh-memory, scripts/audit_translation.py.
- File names and config keys are never translated.
- Harness names: DSH, Codex, Claude Code, CodeBuddy, ZCode.

## Style rules

1. Write in direct, technical English. Prefer imperative sentences for procedures.
2. Keep one sentence per source sentence where practical. Do not merge or split paragraphs unless a literal translation is unreadable.
3. Preserve every heading level exactly. The audit compares the ATX heading level sequence.
4. Copy every fenced code block byte-for-byte, including comments, language tags, and trailing spaces. The audit compares blocks exactly.
5. Translate prose only. Do not translate code, commands, paths, JSON keys, config keys, tool names, or version strings.
6. Avoid Chinese punctuation in prose. Use ASCII commas, periods, colons, semicolons, parentheses, and quotation marks.
7. Do not leave Han characters in prose. If a Chinese term must appear, put it in an inline code span, for example the old label.
8. Keep the language header as the first line: a blockquote with a Chinese link back to the source and the word English.
9. Rewrite relative links: point to the English target when one exists in docs/en/TRANSLATION_MANIFEST.json; otherwise point to the Chinese source. Never leave a link broken.
10. Preserve tables, lists, blockquotes, and admonitions. Translate cell text and list text, not code tokens.
11. Do not add new sections, examples, or claims. A translation may clarify grammar but must not change scope.
12. Keep dates, version numbers, issue numbers, and commit hashes unchanged.
13. When a source sentence is ambiguous, keep the ambiguity and add a translator note only if the ambiguity would cause a wrong action.
14. Product voice: confident, concrete, evidence-first. Avoid marketing adjectives that are absent from the source.

## Verification

Run the mechanical gate from the repository root:

    python scripts/audit_translation.py --check

A translation is acceptable only when the gate reports no findings for its pair and the link checker still passes. The gate checks existence, the language header, code fences, heading levels, Han leakage, CJK punctuation, relative links, scope coverage, and generated-document handling.
