"""Targeted runtime mutations; only intended assertion failures count as kills."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from . import mdcg, readcache
from .test_exact_text_cache import ExactTextCache


def run(names):
    stream = io.StringIO()
    suite = unittest.TestSuite(ExactTextCache(name) for name in names)
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    def name(test):
        return getattr(test, "test_case", test)._testMethodName
    return {"run": result.testsRun, "failures": [name(t) for t, _ in result.failures],
            "errors": [name(t) for t, _ in result.errors],
            "skips": [name(t) for t, _ in result.skipped],
            "log": stream.getvalue().replace(str(Path(__file__).resolve().parents[1]), "<checkout>")}


def install_mutation(kind):
    original = readcache.install
    def wrapped(cg):
        cache = original(cg)
        if kind == "uncached":
            cg._doc_exact_text = cg._doc_exact_text_uncached
        elif kind in ("stale_exact", "stale_lower"):
            attr = "_doc_exact_text" if kind == "stale_exact" else "_like_body_lower"
            fn, stale = getattr(cg, attr), {}
            def cached_forever(entry, content):
                p = entry["path"]
                if p not in stale:
                    stale[p] = fn(entry, content)
                return stale[p]
            setattr(cg, attr, cached_forever)
        return cache
    return patch.object(readcache, "install", wrapped)


def hidden_nested_cache():
    original = readcache.install
    def wrapped(cg):
        for attr in ("_positive_body_uncached", "_doc_norm_bigrams_uncached"):
            if hasattr(cg, attr):
                delattr(cg, attr)
        return original(cg)
    return patch.object(readcache, "install", wrapped)


def missing_clear():
    original = readcache.clear
    def wrapped(cg):
        saved = dict(getattr(cg, "_exact_text_cache", {}))
        count = original(cg)
        cg._exact_text_cache.update(saved)
        return count
    return patch.object(readcache, "clear", wrapped)


def main(output):
    compact = mdcg.compact_exact_text
    cases = [
        ("no_whitespace_removal", "test_raw_and_prepared_predicates_preserve_whitespace_and_case",
         lambda: patch.object(mdcg, "compact_exact_text", lambda text: text or "")),
        ("casefold_exact", "test_raw_and_prepared_predicates_preserve_whitespace_and_case",
         lambda: patch.object(mdcg, "compact_exact_text", lambda text: compact(text).lower())),
        ("uncached_exact", "test_warm_scoring_normalizes_only_query_once", lambda: install_mutation("uncached")),
        ("stale_exact", "test_one_write_invalidates_only_changed_document", lambda: install_mutation("stale_exact")),
        ("stale_lower", "test_lowercase_warm_reuse_and_single_write_invalidation", lambda: install_mutation("stale_lower")),
        ("missing_clear", "test_clear_removes_projection_without_changing_legacy_count", missing_clear),
        ("hidden_nested_cache", "test_reinstall_does_not_keep_hidden_projection_cache", hidden_nested_cache),
    ]
    names = list(dict.fromkeys(test for _, test, _ in cases))
    evidence = {"baseline": run(names), "mutations": []}
    if any(evidence["baseline"][name] for name in ("failures", "errors", "skips")):
        raise AssertionError(evidence["baseline"])
    for mutation, test, apply in cases:
        with apply():
            reading = run([test])
        killed = bool(reading["failures"]) and set(reading["failures"]) == {test} and not reading["errors"] and not reading["skips"]
        evidence["mutations"].append({"mutation": mutation, "expected_test": test,
                                      "killed": killed, **reading})
        print(f"{mutation}: intended assertion killed={killed}")
    evidence["restored"] = run(names)
    evidence["passed"] = all(r["killed"] for r in evidence["mutations"]) and not any(
        evidence["restored"][name] for name in ("failures", "errors", "skips"))
    if output:
        Path(output).write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output")
    raise SystemExit(main(ap.parse_args().output))
