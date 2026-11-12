#!/usr/bin/env python3
"""audit_translation.py - mechanical gate for English documentation translations.

The audit reads docs/en/TRANSLATION_MANIFEST.json and checks every declared
source/target pair for structural fidelity and completeness:

- both sides exist
- the target starts with a language header that links back to the source
- fenced code blocks are byte-identical
- ATX heading level sequences match
- no untranslated Han characters or CJK punctuation in prose
- every relative markdown link resolves
- every file matched by the manifest scope is either translated or excluded
- generated documentation is never hand-translated
- the manifest itself is valid

Exit codes: 0 pass, 1 findings, 2 usage or manifest error.

Zero dependencies. Run from the repository root:

    python scripts/audit_translation.py --check
    python scripts/audit_translation.py --json
    python scripts/audit_translation.py --write-report
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

BACKTICK = chr(96)
HEADER_RE = re.compile(r"^>\s*\*\*Languages:\*\*\s*\[中文\]\(([^)]+)\)\s*·\s*English\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+")
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\)")
HTML_RE = re.compile(r"<[^>]+>")
URL_RE = re.compile(r"https?://[^\s)>\]]+")
LINK_DEST_RE = re.compile(r"\]\([^)]*\)")
INLINE_RE = re.compile(BACKTICK + r"+[^" + BACKTICK + r"]*" + BACKTICK + r"+")

REQUESTED = ("schema", "source_language", "target_language", "pairs")


def is_han(ch: str) -> bool:
    code = ord(ch)
    return (0x3400 <= code <= 0x4DBF) or (0x4E00 <= code <= 0x9FFF) or (0xF900 <= code <= 0xFAFF)


def is_cjk_punct(ch: str) -> bool:
    code = ord(ch)
    return (0x3000 <= code <= 0x303F) or (0xFF00 <= code <= 0xFFEF)


def fence_marker(line: str):
    stripped = line.lstrip()
    if stripped.startswith(BACKTICK * 3):
        return BACKTICK
    if stripped.startswith("~~~"):
        return "~"
    return None


def scan_fences(lines):
    blocks = []
    outside = []
    index = 0
    while index < len(lines):
        line = lines[index]
        marker = fence_marker(line)
        if marker is None:
            outside.append(line)
            index += 1
            continue
        block = [line]
        index += 1
        while index < len(lines):
            block.append(lines[index])
            stripped = lines[index].lstrip()
            if stripped.startswith(marker * 3) and stripped.strip().strip(marker) == "":
                index += 1
                break
            index += 1
        blocks.append("".join(block))
    return blocks, outside


def heading_levels(lines):
    levels = []
    for line in lines:
        match = HEADING_RE.match(line)
        if match:
            levels.append(len(match.group(1)))
    return levels


def cjk_text(lines):
    kept = [line for line in lines if not HEADER_RE.match(line.rstrip("\r\n"))]
    text = "".join(kept)
    text = HTML_RE.sub(" ", text)
    text = URL_RE.sub(" ", text)
    text = LINK_DEST_RE.sub("]()", text)
    text = INLINE_RE.sub(" ", text)
    return text


def finding(code, message, source=None, target=None):
    item = {"code": code, "message": message}
    if source is not None:
        item["source"] = source
    if target is not None:
        item["target"] = target
    return item


def resolve_link(root: Path, target: Path, dest: str) -> Path:
    dest = dest.strip()
    if dest.startswith("<") and dest.endswith(">"):
        dest = dest[1:-1]
    dest = dest.split("#", 1)[0]
    if not dest:
        return target
    dest = unquote(dest)
    if dest.startswith("/"):
        return root / dest[1:]
    return target.parent / dest


def audit(root: Path):
    findings = []
    manifest_path = root / "docs" / "en" / "TRANSLATION_MANIFEST.json"
    if not manifest_path.is_file():
        return None, [finding("MANIFEST_INVALID", "manifest not found: %s" % manifest_path)]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, [finding("MANIFEST_INVALID", "cannot parse manifest: %s" % exc)]
    if not isinstance(manifest, dict):
        return None, [finding("MANIFEST_INVALID", "manifest must be a JSON object")]
    for key in REQUESTED:
        if key not in manifest:
            return None, [finding("MANIFEST_INVALID", "missing key: %s" % key)]
    if manifest.get("schema") != 1:
        return None, [finding("MANIFEST_INVALID", "unsupported schema: %r" % manifest.get("schema"))]
    pairs = manifest.get("pairs")
    if not isinstance(pairs, list):
        return None, [finding("MANIFEST_INVALID", "pairs must be a list")]
    clean_pairs = []
    seen_targets = set()
    for entry in pairs:
        if not isinstance(entry, dict) or "source" not in entry or "target" not in entry:
            return None, [finding("MANIFEST_INVALID", "pair needs source and target: %r" % (entry,))]
        source = str(entry["source"]).replace("\\", "/")
        target = str(entry["target"]).replace("\\", "/")
        if target in seen_targets:
            return None, [finding("MANIFEST_INVALID", "duplicate target: %s" % target)]
        seen_targets.add(target)
        clean_pairs.append((source, target))
    scope = [str(item) for item in manifest.get("scope", [])]
    exclude = [str(item) for item in manifest.get("exclude", [])]
    generated = set(str(item).replace("\\", "/") for item in manifest.get("generated", []))

    source_set = {source for source, _ in clean_pairs}
    for source, target in clean_pairs:
        source_path = root / source
        target_path = root / target
        if not source_path.is_file():
            findings.append(finding("MISSING_SOURCE", "source does not exist", source, target))
            continue
        if not target_path.is_file():
            findings.append(finding("MISSING_TARGET", "target does not exist", source, target))
            continue
        if source in generated:
            findings.append(finding("GENERATED_TRANSLATED", "generated document must not be translated", source, target))
        source_text = source_path.read_text(encoding="utf-8", errors="replace")
        target_text = target_path.read_text(encoding="utf-8", errors="replace")
        source_lines = source_text.splitlines(keepends=True)
        target_lines = target_text.splitlines(keepends=True)

        header_ok = False
        header_link = None
        for line in target_lines[:10]:
            match = HEADER_RE.match(line.rstrip("\r\n"))
            if match:
                header_ok = True
                header_link = match.group(1)
                break
        if not header_ok:
            findings.append(finding("LANGUAGE_HEADER", "missing language header in first 10 lines", source, target))
        else:
            try:
                resolved = resolve_link(root, target_path, header_link)
            except ValueError:
                resolved = None
            if resolved is None or not resolved.exists() or resolved.resolve() != source_path.resolve():
                findings.append(finding("LANGUAGE_HEADER", "header must link back to the source: %s" % header_link, source, target))

        source_blocks, source_outside = scan_fences(source_lines)
        target_blocks, target_outside = scan_fences(target_lines)
        if source_blocks != target_blocks:
            findings.append(finding("CODE_FENCE_DRIFT", "fenced code blocks differ", source, target))

        source_levels = heading_levels(source_outside)
        target_levels = heading_levels(target_outside)
        if source_levels != target_levels:
            findings.append(finding("HEADING_DRIFT", "heading level sequence %r != %r" % (target_levels, source_levels), source, target))

        prose = cjk_text(target_outside)
        for number, line in enumerate(prose.splitlines(), 1):
            for ch in line:
                if is_han(ch):
                    findings.append(finding("CJK_LEAK", "untranslated Han character %r at prose line %d" % (ch, number), source, target))
                    break
            else:
                continue
            break
        for number, line in enumerate(prose.splitlines(), 1):
            for ch in line:
                if is_cjk_punct(ch):
                    findings.append(finding("CJK_PUNCTUATION", "CJK punctuation %r at prose line %d" % (ch, number), source, target))
                    break
            else:
                continue
            break

        link_text = "".join(target_outside)
        for match in LINK_RE.finditer(link_text):
            dest = match.group(1).strip()
            if not dest or dest.startswith("#"):
                continue
            lowered = dest.lower()
            if lowered.startswith(("http://", "https://", "mailto:", "tel:", "data:")):
                continue
            if any(token in dest for token in ("{", "}", "<", ">")):
                continue
            candidate = resolve_link(root, target_path, dest)
            if not candidate.exists():
                findings.append(finding("BROKEN_LINK", "link does not resolve: %s" % dest, source, target))

    covered = set()
    for source, target in clean_pairs:
        covered.add(source)
    for item in exclude:
        covered.add(item)
    for item in generated:
        covered.add(item)
    for pattern in scope:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if rel in covered:
                continue
            if any(fnmatch.fnmatch(rel, item) for item in exclude):
                continue
            findings.append(finding("COVERAGE_GAP", "scope file has no translation or exclusion: %s" % rel))
    return manifest, findings


def render_report(manifest, findings):
    lines = ["# Translation audit report", "", "Generated by scripts/audit_translation.py.", ""]
    lines.append("- Result: %s" % ("PASS" if not findings else "FAIL"))
    lines.append("- Pairs: %d" % len(manifest.get("pairs", []) if manifest else []))
    lines.append("- Findings: %d" % len(findings))
    lines.append("")
    lines.append("## Findings")
    lines.append("")
    if not findings:
        lines.append("No findings.")
    else:
        for item in findings:
            location = ""
            if item.get("source"):
                location = " (%s -> %s)" % (item.get("source"), item.get("target", ""))
            lines.append("- %s%s: %s" % (item["code"], location, item["message"]))
    lines.append("")
    return "\n".join(lines)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Audit English documentation translations.")
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("--check", action="store_true", help="print findings (default)")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--write-report", action="store_true", help="write docs/en/TRANSLATION_REPORT.md")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    manifest, findings = audit(root)
    if manifest is None:
        for item in findings:
            print("%s: %s" % (item["code"], item["message"]))
        return 2

    if args.json:
        payload = {
            "ok": not findings,
            "counts": {
                "pairs": len(manifest.get("pairs", [])),
                "scope": len(manifest.get("scope", [])),
                "generated": len(manifest.get("generated", [])),
                "findings": len(findings),
            },
            "findings": findings,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if not findings else 1

    for item in findings:
        location = ""
        if item.get("source"):
            location = " %s -> %s" % (item.get("source"), item.get("target", ""))
        print("FINDING %s%s: %s" % (item["code"], location, item["message"]))
    print("SUMMARY pairs=%d findings=%d" % (len(manifest.get("pairs", [])), len(findings)))

    if args.write_report:
        report_path = root / "docs" / "en" / "TRANSLATION_REPORT.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_report(manifest, findings), encoding="utf-8")
        print("REPORT %s" % report_path)
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
