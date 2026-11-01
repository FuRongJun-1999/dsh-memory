# English translation policy

> **Languages:** [中文](../README.md) · English

This directory contains the English edition of the user-facing LINGSHU documentation. It is a translation, not a fork. The Chinese files remain the source of truth.

## Scope

Translated surfaces:

- the root README and CHANGELOG
- the documentation index
- operations, development, and protocol guides under docs/ops and docs/dev
- the Guardrail Charter and the user-facing protocol notes under docs/mdcg
- the five harness integration guides
- the optional UI guide
- the AI coding standards under docs/规范

Not translated:

- historical evaluation, experiment, plan, theory, discipline, promotion, and retrospective records
- skills/ conditional units and runtime prompts
- UI runtime source files and their integrity hashes
- generated documents listed in docs/en/TRANSLATION_MANIFEST.json

Generated documents are produced from source code by scripts/cogmap_sync.py. Editing or translating them by hand would drift from the generator. See docs/en/mdcg/generated-docs.md.

## Source of truth

Each translated page starts with a language header that links back to its Chinese source. If a translation and its source disagree, the Chinese source wins and the translation must be fixed in the same pull request.

## Structural fidelity

The audit gate compares each pair for:

- source and target existence
- a language header in the first ten lines that links back to the source
- byte-identical fenced code blocks
- identical ATX heading level sequences
- no untranslated Han characters in prose
- no CJK punctuation in prose
- every relative markdown link resolving
- every scope file translated or explicitly excluded
- no hand translation of generated documents

Run it with:

    python scripts/audit_translation.py --check

Machine-readable output:

    python scripts/audit_translation.py --json

Regenerate the report after a change:

    python scripts/audit_translation.py --write-report

Exit code 0 means pass, 1 means findings, 2 means a usage or manifest error.

## Maintenance

When a Chinese source changes, update the English target in the same pull request and run the audit. When a new user-facing document is added, add it to the manifest, translate it, and extend the scope. Do not add a translated page without a manifest pair; the coverage check will reject orphan files in scope.

## Vocabulary

Use docs/en/glossary.md. Add missing terms there before using them in a page.

## What stays Chinese

Code fences stay byte-identical, including Chinese comments, because the audit treats code as executable content. Inline code spans may contain Chinese identifiers when they name a real file, command, or label. Prose must be English.
