> **Languages:** [中文](../../mdcg/recall_metadata.md) · English

# Recall core state and source information

Each `pack` entry returned by `mdcg_recall` and by `cg(op="read")` with `budget_tokens` gains a `metadata` field, so callers can read a small amount of key state information directly. The existing `id`, `score`, `state`, `tokens`, `content`, `frontmatter`, `provenance`, and the on-demand `truncated` keep their original values and meanings.

| Field | Source and meaning |
| --- | --- |
| `state` | The eligibility verdict already made for this retrieval, such as `ACCEPT`, `DEFER`, `REJECT`, `BLINDSPOT`; it describes how applicable the memory is to the current query/situation and does not mean the fact has been confirmed. |
| `reason` | The reason already recorded for this eligibility verdict; `null` when there is no reason. |
| `verification_state` | The persistent verification state read through the existing `trust.state_of(frontmatter)`: `unverified`, `verified`, `doubted`, `rechecking`, `expired`. A missing or invalid state is treated as `unverified` by the existing rules, and does not mean verification was ever completed. |
| `verification_basis` | The verification basis category declared in the original frontmatter; declaring a basis does not mean verification has passed. |
| `check_strength` | The check strength declared in the original frontmatter. |
| `derived_from`, `derived_relation` | The source memory and derivation relation declared in the original frontmatter. |
| `source` | Passes through only the source explicitly recorded in the frontmatter; it is not inferred from role or session. |

The last three rows, plus `verification_basis` and `check_strength`, are returned only when the field exists and its value is not `null`; recorded empty strings, empty lists, `false`, or `0` are preserved. `metadata` adds no new reliability score, does not copy `confidence`, and does not aggregate the full audit log, the verification history, or all versions. The existing `frontmatter` is still kept for compatibility with original callers.

For example, a memory that is applicable to the current query but has not yet been verified returns both `state: "ACCEPT"` and `verification_state: "unverified"`. The upper-layer AI should read it as "an unverified memory that can be referenced for the current task". When there is no source record, `source` is not returned; do not read "not recorded" as "directly provided by the user".

The existing `provenance` represents the retrieval path and ranking, not the factual source, so it is not copied into `metadata`. `score` is still the original retrieval score and cannot be treated as the probability that the fact is true either.

This summary uses only the data already read at final packing time and adds no storage reads or writes. Candidates, retrieval paths, RRF, ranking, eligibility verdicts, body truncation, and the original token budget calculation are all unchanged. `tokens` / `tokens_used` continue to count the body (and optionally the recent-event body) and do not represent the number of serialized tokens in the whole JSON response. The optional `recent` event window keeps its original structure.

Verification method:

```sh
python -X utf8 -m md_cg.test_recall_metadata
python -X utf8 -m md_cg.test_p2_mcp
```
