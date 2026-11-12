> **Languages:** [中文](../../ops/权限与复核模型.md) · English

# Permissions and review model: read / write / adjudicate layers

> This document is the full version of the README "Permissions" section: token issuance and narrowing, layered write gates, dual-unit adjudication, and an error reference.

LINGSHU runs as a **read-only guest** by default (it can read but cannot write). Writing and adjudication require a token and follow the three rulings of 2026-10-27:

> **The Designer is read-only · writes must be careful · adjudication requires review by reflection and verification units.**
> The reason: drift and amnesia of the self persona are destructive, and full permissions on an unreliable system are a disaster.

## 1) Tokens: issue, narrow, health-check

```bash
# 签发（不传 --ops-allow 即角色默认；designer 的默认是 ["*"] 全集）
python -m md_cg.tokens issue --role designer --actor my-agent

# 收窄成「只读面」——给界面、自动化、子智能体用这个（只能收窄，不能放大）
python -m md_cg.tokens issue --role designer --actor ui-panel \
  --ops-allow info,help,status,edges,read,route,recent,identity,self_state,\
metacognition,review,protect,evolution,sustain,goal,task,whitebox

# 体检（含 designer 覆盖面缺口报告）
python -m md_cg.tokens verify --token-file-in <令牌文件>
```

| Surface | Suggested for | op boundary |
|---|---|---|
| **Read-only surface** (17 ops) | UI panels, subagents, read-only inspection | as listed above; **excludes** `write` / `verify` / `forget` / `scrub` / `consolidate` / `index_*` / `export` / `maintain` / `link` |
| Write surface | recording units | adds `write` (+ `session` / `ingest` / `ccg` as needed) |
| Adjudication surface | verification units | adds `verify`; the `redteam` gate and re-approval still apply |

After issuance, inject it into the host: `config.env.MDCG_TOKEN` (for example the DSH profile config), or write it to the keyring at `~/.mdcg/token`;
the token store defaults to `~/.mdcg/_tokens.json` (override with `MDCG_TOKEN_FILE`).

## 2) Layered writes: each layer stricter than the last

`MDCG_WRITE_GATE` controls whether this table takes effect (`off` by default / `warn` records only / `enforce` actually blocks):

> **Where to see `warn` records**: `cg(op=info).write_gate` -> `{mode, total, by_layer, recent, hint}`.
> They are recorded **in-process** (not on disk, reset on restart), so they do not depend on whether the host forwards subprocess stderr —
> this matters: DSH does **not** forward MCP subprocess stderr by default, so looking only at the logs makes it seem like "warn recorded nothing".

| Tier | Layer | Required when a review channel exists | **When no review channel exists** |
|---|---|---|---|
| 0 | `contextual` · `goals` · `unresolved` · `rejected` | none | ✅ direct write allowed (relaxed channel) |
| 1 | `knowledge` | reflection unit | ❌ write rejected |
| 2 | `structural` | reflection + verification unit | ❌ write rejected |
| 3 | `self` · `anchor` | reflection + verification + **human adjudication** | ❌ write rejected |

Review channels are **declared** with `MDCG_REVIEW_CHANNELS` (any of `hive,subagent,team`). Note: the variable is a **deployment declaration**; empty only means "never declared" and does **not** mean this machine has no subagents, Hive, or teams.

## 3) Adjudication: dual-unit review, no self-certification

With `MDCG_REVIEW_DUAL_CHECK=1` enabled, an adjudication must carry both kinds of review unit:

```python
cg(op="review", action="decide", pid="…", decision="accept",
   reviewed_by=["反思单元", "验证单元"])   # 中英文同义均可：reflect / verify / human
```

| Condition | Behavior |
|---|---|
| Missing reflection or verification | `dual_check_required` (names the missing side) |
| Two of the same kind (two reflections) | still counts as missing verification — **same-side mutual confirmation is not review** |
| Adjudicator == proposer | `self_review_forbidden` |
| Unknown unit | `unknown_review_unit` (not silently counted) |

It is **orthogonal** to the existing gates: `redteam` + `needs_reapproval` handle rejection and re-approval; `verify_readonly` handles "criteria are declared by propose and cannot change at adjudication time"; this gate only answers "who reviewed it".

## 4) Error quick reference

| Error | Meaning | Action |
|---|---|---|
| `AccessDenied: 本令牌的 ops 作用域不含 op=xxx` | the token's ops scope is narrowed and lacks that op | re-issue with the missing `--ops-allow`, or switch to a token that has it |
| `designer_coverage_gap` (`verify` output) | the Designer token lacks the inspect/adjudicate surface | re-issue with the missing ops; the gaps are listed |
| `write_gate ... deny` | the target layer needs review and there is no channel/evidence right now | declare `MDCG_REVIEW_CHANNELS` or add review units; or switch to `warn` first and observe |
| `dual_check_required` / `self_review_forbidden` | see the table above | add units / change the adjudicator |
| `redteam_required` / `reapproval_required` | red-team gate and re-approval | include `redteam.verdict=pass` (round count increments) |
