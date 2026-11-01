> **Languages:** [中文](../../dev/开关矩阵.md) · English

# Retrieval switch matrix and adjudication history

> This page was split out of the original `README.md` (source: the "Do not mix up the two cross-language switches" section of the original README (L600-L611)).


> **Do not mix up the two cross-language switches**: `MDCG_UNIFY_QUERY` (the unified normalization layer, **off by default**. On 2026-09-30 a user adjudication flipped it from "on by default" to "**off when unset, on only with an explicit `=1`**": the job of this layer is to let English queries hit Chinese nodes, and for a Chinese retrieval pool it is pure overhead.
> Measured on the public locomo-zh-500 question set, the default-off state gives lexical hit@1 96.4% / lexical+fuzzy 97.2%, while the on state gives 95.8% / 96.6%; when explicitly enabled, a query in any language is first normalized into a standard Chinese atom sequence, and the lexical path can then hit Chinese nodes; **on 2026-09-30 the scope was narrowed: translation normalization applies only to English content, Chinese segments are kept verbatim and never sent to the segmenter**, so Chinese keyword runs in a mixed Chinese-English query are no longer split character by character) and `MDCG_EN_ATOMS` (English-to-Chinese recall term expansion, **off by default**) are independent switches;
> `MDCG_SEMANTIC` (the `fm.semantic` semantic-summary path) is likewise off by default. Changing either one requires updating the dual-state assertions in `md_cg/test_en_pipeline.py` and `md_cg/test_semantic_canonical.py`; changing the normalization layer **default / three-state** behavior requires running `md_cg/test_unify_default_off.py` (three-state agreement on both sides plus a fixed-point mutation self-proof), and changing its **scope** additionally requires running `md_cg/test_unify_scope.py` (same-origin fixture with the Rust side, `md_cg/semantic/unify_fixture.json`, see `docs/hive/检索算法口径对照_v0.1.md`).
