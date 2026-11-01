> **Languages:** [中文](../../mdcg/CCG六要素编译.md) · English

# Memory reliability gate: CCG six-element compilation

> This page was split out of the former `README.md` (source: the former README "Memory reliability gate" and the tools mode table (L384–L438)).


## Compilation chain and error codes

### 🧱 Memory reliability gate: CCG six-element compilation (`cg(op=ccg)`)

Compile conversation records into retrievable CCG six-element entries (`# feature name / # effective condition / # sub-feature / # execution / # verification method / # non-applicable conditions`), and **the compiler must not self-certify** — candidates produced by the LLM must pass review by an **out-of-band unit outside the cognitive map** before they may be persisted (mechanical rejection code `E041`, not dependent on prompt discipline). Candidates are bound to a content digest for staging (`_ccgc_pending/`, invisible to the index), and are tamper-proof across three independent calls.

| Step | Call | Result |
| --- | --- | --- |
| ① Compile | `cg(op=ccg, action=compile, node_id=…, dialog=…)` | Six-element candidate + name-reality gate check (every written value must be a substring of the source text), **not written to the store on the spot** |
| ② Review | `cg(op=ccg, action=review, node_id=…, blocking=true)` | Out-of-band unit adjudication: Hive `reflect`/`verify` first; if Hive is unavailable, **return configuration guidance** (do not pretend it is available); only an explicit `allow_degrade` falls back to a subagent |
| ③ Persist | `cg(op=ccg, action=link, node_id=…, apply=true)` | Written only after the digest check + signature admission pass |

Error codes: `E040` no signature · `E041` self-certification rejected · `E042` review not passed · `E043` only the four slots may be corrected (`action=recalibrate`). `action=catalog` self-describes all actions; `action=units` inspects the review channel (three states: Hive / pending configuration / subagent fallback).

## tools modes and risky tools

| `tools` mode | Exposed count | Notes |
| --- | --- | --- |
| `'core'` (**default**) | **2** | Only `cg` / `stg` |
| `'brain'` | **30** | `cg`/`stg` + 28 fine-grained |
| `'all'` | **30** | full surface 33 − 3 host-level risky tools |

> Risky tools `mdcg_forget` / `mdcg_restore` / `mdcg_review_decide` require `can_admin`; even with `tools: 'all'` they are not exposed automatically.
> All 35 ops have been smoke-tested one by one: **35/35 reachable, 0 unknown ops, 0 unexpected crashes**.
> The historical 82 tools **belong to the separate tool surface of the old aeis engine, not this repository** (in this repository md_cg has two primitive surfaces, `cg` with 22 ops and `stg` with 4 ops; the fine-grained surface in the table above measures **31 tools** at runtime) — for where they went, see [migration mapping](../../mdcg/灵枢82工具_功能整理与迁移映射_v0.1.md), whose disposition rule is "**keep the two tool surfaces cg/stg; no longer register 82 standalone tools**".
