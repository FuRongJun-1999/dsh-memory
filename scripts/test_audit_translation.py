# -*- coding: utf-8 -*-
"""test_audit_translation.py - translation audit gate self-tests.

Guard surface: scripts/audit_translation.py. The audit is the only mechanical
proof that the English docs are complete, structurally faithful, and free of
untranslated prose. This test proves the gate both passes a good fixture and
goes red on each failure class (missing target, CJK leak, code-fence drift,
heading drift, broken link, missing language header, coverage gap, generated
doc translation, missing source, invalid manifest).

Run directly: python scripts/test_audit_translation.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AUDIT = REPO / "scripts" / "audit_translation.py"
ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fixture(tmp: str) -> Path:
    root = Path(tmp)
    write(root, "README.md", "# 项目\n\n中文说明。\n\n```bash\npython -m demo\n```\n\n[文档](docs/ops/guide.md)\n")
    write(root, "docs/ops/guide.md", "# 指南\n\n中文。\n")
    write(
        root,
        "README.en.md",
        "> **Languages:** [中文](README.md) · English\n\n# Project\n\nEnglish text.\n\n"
        "```bash\npython -m demo\n```\n\n[Guide](docs/en/ops/guide.md)\n",
    )
    write(
        root,
        "docs/en/ops/guide.md",
        "> **Languages:** [中文](../../ops/guide.md) · English\n\n# Guide\n\nEnglish.\n",
    )
    write(root, "docs/en/glossary.md", "# Glossary\n")
    write(root, "docs/en/TRANSLATION.md", "# Translation policy\n")
    write(root, "docs/en/mdcg/generated-docs.md", "# Generated docs\n")
    write(root, "docs/mdcg/cogmap_ops.md", "# 生成\n")
    manifest = {
        "schema": 1,
        "source_language": "zh-CN",
        "target_language": "en",
        "pairs": [
            {"source": "README.md", "target": "README.en.md"},
            {"source": "docs/ops/guide.md", "target": "docs/en/ops/guide.md"},
        ],
        "scope": ["README.md", "docs/ops/*.md", "docs/mdcg/*.md"],
        "exclude": ["docs/mdcg/cogmap_ops.md"],
        "generated": ["docs/mdcg/cogmap_ops.md"],
        "generated_note": "docs/en/mdcg/generated-docs.md",
    }
    write(root, "docs/en/TRANSLATION_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return root


def run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(AUDIT), "--root", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=ENV,
    )


def expect(root: Path, code: str) -> tuple[bool, str]:
    proc = run(root, "--check")
    out = (proc.stdout or "") + (proc.stderr or "")
    return (proc.returncode == 1 and code in out), out


def test_valid_fixture_passes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp)
        proc = run(root, "--check")
        out = (proc.stdout or "") + (proc.stderr or "")
        assert proc.returncode == 0, "valid fixture should pass, got %s\n%s" % (proc.returncode, out)
        assert "SUMMARY" in out, "missing summary line:\n%s" % out


def test_missing_target() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp)
        (root / "docs/en/ops/guide.md").unlink()
        ok, out = expect(root, "MISSING_TARGET")
        assert ok, "missing target must fail\n%s" % out


def test_missing_source() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp)
        (root / "README.md").unlink()
        ok, out = expect(root, "MISSING_SOURCE")
        assert ok, "missing source must fail\n%s" % out


def test_cjk_leak() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp)
        with (root / "docs/en/ops/guide.md").open("a", encoding="utf-8") as handle:
            handle.write("\n未翻译的句子。\n")
        ok, out = expect(root, "CJK_LEAK")
        assert ok, "CJK leak must fail\n%s" % out


def test_code_fence_drift() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp)
        path = root / "README.en.md"
        path.write_text(path.read_text(encoding="utf-8").replace("python -m demo", "python -m demo2"), encoding="utf-8")
        ok, out = expect(root, "CODE_FENCE_DRIFT")
        assert ok, "code fence drift must fail\n%s" % out


def test_heading_drift() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp)
        path = root / "docs/en/ops/guide.md"
        path.write_text(path.read_text(encoding="utf-8").replace("# Guide", "## Guide"), encoding="utf-8")
        ok, out = expect(root, "HEADING_DRIFT")
        assert ok, "heading drift must fail\n%s" % out


def test_broken_link() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp)
        path = root / "README.en.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace("docs/en/ops/guide.md", "docs/en/ops/missing.md"),
            encoding="utf-8",
        )
        ok, out = expect(root, "BROKEN_LINK")
        assert ok, "broken link must fail\n%s" % out


def test_language_header() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp)
        path = root / "README.en.md"
        path.write_text(path.read_text(encoding="utf-8").split("\n", 1)[1], encoding="utf-8")
        ok, out = expect(root, "LANGUAGE_HEADER")
        assert ok, "missing language header must fail\n%s" % out


def test_coverage_gap() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp)
        write(root, "docs/ops/new.md", "# 新文档\n")
        ok, out = expect(root, "COVERAGE_GAP")
        assert ok, "coverage gap must fail\n%s" % out


def test_generated_translated() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp)
        manifest_path = root / "docs/en/TRANSLATION_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["pairs"].append({"source": "docs/mdcg/cogmap_ops.md", "target": "docs/en/mdcg/cogmap_ops.md"})
        write(root, "docs/en/mdcg/cogmap_ops.md", "> **Languages:** [中文](../../../docs/mdcg/cogmap_ops.md) · English\n\n# Generated\n")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        ok, out = expect(root, "GENERATED_TRANSLATED")
        assert ok, "translating a generated doc must fail\n%s" % out


def test_invalid_manifest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp)
        (root / "docs/en/TRANSLATION_MANIFEST.json").write_text("{not json", encoding="utf-8")
        proc = run(root, "--check")
        out = (proc.stdout or "") + (proc.stderr or "")
        assert proc.returncode == 2, "invalid manifest should be usage error 2, got %s\n%s" % (proc.returncode, out)
        assert "MANIFEST_INVALID" in out, "invalid manifest must be named\n%s" % out


def test_json_output_and_report() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp)
        proc = run(root, "--json")
        out = (proc.stdout or "") + (proc.stderr or "")
        assert proc.returncode == 0, "json run should pass\n%s" % out
        payload = json.loads(proc.stdout)
        assert payload["ok"] is True, "json ok must be true: %s" % payload
        assert payload["counts"]["pairs"] == 2, "json pair count: %s" % payload
        proc = run(root, "--write-report")
        out = (proc.stdout or "") + (proc.stderr or "")
        assert proc.returncode == 0, "report run should pass\n%s" % out
        report = (root / "docs/en/TRANSLATION_REPORT.md").read_text(encoding="utf-8")
        assert "Translation audit report" in report, "report title missing:\n%s" % report


def test_unicode_paths_do_not_crash_cp1252() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = fixture(tmp)
        write(root, "docs/中文.md", "# 中文\n")
        manifest_path = root / "docs/en/TRANSLATION_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["pairs"].append({"source": "docs/中文.md", "target": "docs/en/中文.md"})
        manifest["scope"].append("docs/中文.md")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        env = {**os.environ, "PYTHONUTF8": "0", "PYTHONIOENCODING": "cp1252"}
        proc = subprocess.run(
            [sys.executable, str(AUDIT), "--root", str(root), "--check"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        assert proc.returncode == 1, "findings should exit 1, got %s\n%s" % (proc.returncode, out)
        assert "MISSING_TARGET" in out, "missing target must be reported\n%s" % out
        assert "UnicodeEncodeError" not in out, "output must not crash on non-ASCII paths\n%s" % out


def main() -> int:
    tests = [
        test_valid_fixture_passes,
        test_missing_target,
        test_missing_source,
        test_cjk_leak,
        test_code_fence_drift,
        test_heading_drift,
        test_broken_link,
        test_language_header,
        test_coverage_gap,
        test_generated_translated,
        test_invalid_manifest,
        test_json_output_and_report,
        test_unicode_paths_do_not_crash_cp1252,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print("[ok] %s" % test.__name__)
        except AssertionError as exc:
            failed += 1
            print("[FAIL] %s\n%s" % (test.__name__, exc))
        except Exception as exc:  # noqa: BLE001 - test harness must report, not crash
            failed += 1
            print("[FAIL] %s\nunexpected: %r" % (test.__name__, exc))
    print("SUMMARY %d/%d passed" % (len(tests) - failed, len(tests)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
