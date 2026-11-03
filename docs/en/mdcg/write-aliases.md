> **Languages:** [中文](../../mdcg/写入别名aliases规范_v0.6.md) · English

# Write aliases specification v0.6

> 2026-10-31 · Cause: issue #722 "the condition gate matches literally, so natural phrasings are mostly judged DEFER"
> **This specification is backed by a measured closed loop**: the mechanism is ready (#719), the case has been verified to work, and in-library usage is 0%.
> v0.1–v0.5, five versions, all took "change the verdict / change the condition quality" and were all overturned by measurement; this version switches to **adding aliases on the write side**.

## 1. Empirical evidence (all reproducible)

### 1.1 Decisive case (given by the issue reporter)

Condition: when talking about handover, switching sessions, compression, or when he shows reluctance to part
Query: `我不想你被换掉`

| Matching method | Result |
|---|---|
| **Whole word in** (current) | ❌ No match |
| **Bigram overlap** | ❌ `换会`/`会话` vs `我不`/`不想`/`想你`/`你被`/`被换`/`换掉` — **empty intersection** |
| **Query expansion** (`expand_query_terms`) | ❌ Expands `换掉`/`被换`, still **no intersection** with `换会话` |
| **Existing synonym table** (10 groups, all technical terms) | ❌ No `会话`/`换掉` group |
| **Adding aliases** (`换掉`/`被换`/`别消失`/`舍不得`/`不想你走`/`会交接`/`换会话`/`压缩上下文`) | ✅ **Match** (False → True) |

⇒ **All four literal paths are dead; only aliases work.**

### 1.2 Current state in the library (full scan + sampling)

| Item | Reading |
|---|---|
| aliases coverage | **0 / 120 = 0%** |
| Share whose effective condition is **metadata** | **65 / 85 = 76.5%** (sample 120, structured slot-label criterion) |
| role=None in the knowledge layer (index cards) | **99.7%** (30,468 / 30,558) |
| Recall count for natural phrasings | **2 items / 32,845** |

⇒ **The mechanism exists and works, but nobody uses it** — that is the whole truth of #722.

## 2. Specification

### 2.1 What to write

> **When writing a memory, aliases must at least contain "how the user might ask about this".**

**Not**: technical term abbreviations, field names, path fragments.
**But**: the colloquial wording, emotional expressions, and near-synonyms the user would say.

Taking the case in 1.1 as an example, the condition is `聊交接、换会话、压缩、或他流露舍不得时`,
and the aliases are written as: `换掉` / `被换` / `别消失` / `舍不得` / `不想你走` / `会交接` / `换会话` / `压缩上下文`.

### 2.2 Why not write them into tags

tags are already occupied by machine criteria (is it a task card: tasks.py; can it be an anchor: anchor.py / predict.py).
Stuffing aliases in would **change those criteria**. aliases and tags are **physically separate** and take part only in retrieval recall.

### 2.3 How to generate them (**recommend the LLM asking itself**)

> **When writing aliases, first ask yourself: "How will I ask about this later?" — write those phrasings into aliases verbatim.**

Concrete approach (when the writer is an LLM):

1. After reading the memory, **without looking at the condition first**, ask yourself: "If three months from now I forget this, what words would I use to ask about it?"
2. Write **3–8** such questions/keywords (colloquial, emotional, and near-synonyms all count);
3. Write them into `aliases`; words already present in the source text do not need repeating (the criterion would judge them "thin").

**Demonstration** (#722 case):

```
条件：聊交接、换会话、压缩、或他流露舍不得时
自问：以后会怎么问？
  → 「换掉」「被换」「别消失」「舍不得」「不想你走」「会交接」「压缩上下文」
aliases: 换掉 / 被换 / 别消失 / 舍不得 / 不想你走 / 会交接 / 换会话 / 压缩上下文
```

⚠️ **Do not extract words mechanically**. Measured (2026-10-31): auto-generating aliases by splitting feature names on spaces,
5 real questions × 20 nodes = **lift +0** — because Chinese feature names have no spaces, so what gets split out is the whole sentence,
which has nothing to do with "how the user would say it". **Aliases must be predicted by the party that understands the content and cannot be generated automatically.**

### 2.4 Criterion (executable)

`aliases_is_thin(fm) -> bool`: **no aliases**, or **all aliases can be found verbatim in the body/condition**
(= only repeats existing words, expands no recall head) ⇒ judged "thin".

⚠️ **Does not judge "whether the count is enough"** — 3 precise aliases may beat 10 noisy ones.

## 3. Write guard (warn first)

Reuse the three write_gate levels from #708:

| Level | Behavior |
|---|---|
| off | No check |
| **warn (default)** | Write succeeds + counted + hint "this entry has no expansion aliases, natural phrasings may not recall it" |
| enforce | Reject the write |

**Does not block writes**: aliases are a bonus, not a prerequisite for correctness. Missing them should not make a memory unwritable.

## 4. Legacy data (explicitly no bulk backfill)

Bulk-adding aliases to 32,845 nodes is **not realistic** (it requires understanding every item). The realistic path:

1. **New writes** follow this specification (the guard starts at warn);
2. **Hot spots first**: **backfill** aliases after the fact for queries that actually fail to recall (whichever fails to recall, backfill that one);
3. **Observable**: `cg(op=info)` exposes "the number of nodes without aliases" as an improvement baseline.

## 5. Verification approach (every item must be testable)

| Assertion | How to test | Current state |
|---|---|---|
| Aliases can rescue the #722 case | Same comparison as 1.1 | ✅ **Tested** (False → True) |
| Library-wide alias coverage | Sample-read fm.aliases | ✅ **Tested** (0/120) |
| All literal paths are dead | Compare whole word / bigram / expansion / synonym table one by one | ✅ **Tested** (all empty intersections) |
| aliases_is_thin can identify the current state | Run it on the sample, ≈100% judged thin | To be built |
| Aliases do not pollute the tags criteria | After adding aliases, "is it a task card" and "can it be an anchor" are unchanged | ✅ **Tested** (C/D group guards of PR #719) |
| The warn level does not block writes | Nodes without aliases are still written successfully, only counted | To be built |

## 6. Non-applicable conditions

1. **Does not solve "phrasings that were never anticipated"** — aliases depend on someone writing them; whatever is not written still cannot be recalled;
2. **Does not replace semantic retrieval** — semantic coverage is 0, which is a separate engineering line;
3. **Does not bulk-backfill legacy data**;
4. **Does not change tags semantics** (the machine criteria of that field stay put);
5. **Does not support automatic alias generation** — measured (2026-10-31): mechanically extracting words from feature names/body, 5 real questions × 20 items = **lift +0**.
   Aliases must be written by the party that understands the content (a human or an LLM) **predicting how the user would ask**.

## 7. Criterion evolution record (do not repeat)

| Version | Direction | Why it was overturned |
|---|---|---|
| v0.1–v0.4 | Change the verdict algorithm (text source / weak state / S3 graph diffusion / topic surface) | **Wrong target**: what gets judged is 99.7% index cards |
| v0.5 | Change condition quality (judge whether it is metadata) | **A diagnosis, not a solution** — metadata conditions are a product of the indexer and cannot be changed |
| **v0.6** | **Add aliases on the write side** | ✅ The mechanism already exists (#719) + the case proves it works |