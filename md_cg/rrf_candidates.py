"""Exact-superset candidates for RRF word matching, opt in with MDCG_RRF_CANDIDATES=1.

The instance-local index uses the production read cache's path generations.
It is built lazily, updates changed paths, and is never written to disk.
Only lexical/fuzzy/goal inputs are narrowed, after the existing visibility and
retrieval gates. Semantic, temporal and graph paths keep their own candidates.
Metadata enumeration remains linear. A broad invalidation/reload rebuilds the
index; external file edits have the same boundary as the production read cache.
"""
from __future__ import annotations

import os
import sys
import time


def enabled():
    return os.environ.get("MDCG_RRF_CANDIDATES") == "1"


def tokens(text):
    """Raw characters and adjacent pairs, including whitespace and Unicode."""
    return set(text) | {text[i:i + 2] for i in range(len(text) - 1)}


def term_tokens(term):
    return {term} if len(term) == 1 else {
        term[i:i + 2] for i in range(len(term) - 1)}


class CandidateIndex:
    def __init__(self):
        self.nodes = None
        self.dirty = None
        self.broad_gen = -1
        self.docs = {}
        self.post = {}
        self.semantic = set()
        self.initialized = False
        self.last_sync = None

    def clear(self):
        self.docs.clear()
        self.semantic.clear()
        self.post.clear()
        self.nodes = None
        self.dirty = None
        self.broad_gen = -1
        self.initialized = False
        self.last_sync = None

    def remove(self, path):
        old = self.docs.pop(path, None)
        self.semantic.discard(path)
        if old is None:
            return
        for word in old[1]:
            paths = self.post[word]
            paths.discard(path)
            if not paths:
                del self.post[word]

    def sync(self, cg, entries, report):
        dirty = cg._dirty
        nodes = cg.index["nodes"]
        last = self.last_sync
        if (last is not None and last[0] is report
                and last[1:] == (id(entries), dirty.write_gen)
                and self.nodes is nodes and self.dirty is dirty):
            return  # The same query's lexical/fuzzy/goal paths share a pool.
        if (self.nodes is not nodes or self.dirty is not dirty
                or dirty.broad_gen > self.broad_gen):
            self.clear()
        self.nodes, self.dirty = nodes, dirty
        self.broad_gen = dirty.broad_gen
        first = not self.initialized
        started = time.perf_counter()
        cached_nodes = 0
        for entry in entries:
            path = entry["path"]
            old = self.docs.get(path)
            if old is not None and dirty.path_gen.get(path, 0) <= old[0]:
                cached_nodes += 1
                continue
            self.remove(path)
            report["build_reads" if first else "update_reads"] += 1
            fm, content, failure = cg._read_status(entry)
            if failure is not None or content is None:
                # Never freeze transient failures or failed decryption into a
                # negative candidate cache. Retry on the next query.
                continue
            content = cg._open_content(fm.get("id"), fm, content)
            if content is None:
                continue
            tags = " ".join(str(t) for t in (fm.get("tags") or []))
            positive = cg._positive_body(entry, content)
            # One superset table serves all three scoring paths. Interning
            # repeated short grams avoids retaining duplicate Unicode objects
            # for every node. Negative/case false positives are still checked
            # by each path's unchanged exact scorer.
            words = {sys.intern(g) for g in (
                tokens(content + " " + tags) | tokens(positive + " " + tags)
                | tokens(positive.lower() + " " + tags.lower()))}
            for g in words:
                self.post.setdefault(g, set()).add(path)
            if fm.get("semantic"):
                self.semantic.add(path)
            self.docs[path] = (dirty.write_gen, words)
            cached_nodes += 1
        self.initialized = True
        report["index_ms"] += (time.perf_counter() - started) * 1000
        report["cached_nodes"] = cached_nodes
        self.last_sync = (report, id(entries), dirty.write_gen)


def begin(cg):
    cg._rrf_candidate_report = None
    if not enabled():
        return {}
    report = {"paths": {}, "build_reads": 0, "update_reads": 0,
              "index_ms": 0.0, "cached_nodes": 0}
    cg._rrf_candidate_report = report
    return {"rrf_candidates": report}


def narrow(cg, entries, terms, mode, query=""):
    if not enabled():
        return entries
    report = getattr(cg, "_rrf_candidate_report", None)
    if report is None:
        return entries  # Private direct calls retain their original behavior.
    detail = {"input": len(entries), "output": len(entries)}
    report["paths"][mode] = detail
    if mode == "lexical" and any(not str(term) for term in terms):
        # expand_query_terms can yield [''] for punctuation/emoji-only input.
        # Existing LIKE treats the empty substring as matching every document;
        # its relevance cap differs from the importance fallback cap.
        detail["fallback"] = "empty_term_matches_all"
        return entries
    dirty = getattr(cg, "_dirty", None)
    if (not hasattr(cg, "_read_cache") or not hasattr(dirty, "path_gen")
            or not hasattr(dirty, "broad_gen")):
        detail["fallback"] = "read_cache_unavailable"
        return entries
    idx = getattr(cg, "_rrf_candidate_index", None)
    if idx is None:
        idx = cg._rrf_candidate_index = CandidateIndex()
    try:
        idx.sync(cg, entries, report)
        table = idx.post
        found = set()
        for term in terms:
            text = str(term).lower() if mode == "lexical" else str(term)
            for word in term_tokens(text):
                found.update(table.get(word, ()))
        if len(found) >= len(entries) * 0.75:
            detail["fallback"] = "broad_candidates"
            return entries
        if mode == "lexical":
            from .mdcg import index_key_hits, semantic_on
            if semantic_on():
                found.update(idx.semantic)
            # Six-element postcondition/rejection keys are metadata, and can
            # recall a node with no matching body. Keep that route intact.
            selected = [e for e in entries if e["path"] in found
                        or e["path"] not in idx.docs
                        or index_key_hits(e, terms, query).get("hit")]
        else:
            selected = [e for e in entries if e["path"] in found
                        or e["path"] not in idx.docs]
    except Exception as exc:
        # A broken derived index must not change retrieval or block a read.
        idx.clear()
        detail["fallback"] = "index_error"
        detail["error_type"] = type(exc).__name__
        return entries
    detail["output"] = len(selected)
    return selected


def lexical_fallback(cg, size):
    report = getattr(cg, "_rrf_candidate_report", None)
    if report is not None and "lexical" in report["paths"]:
        report["paths"]["lexical"].update(
            fallback="no_like_hit", output=size)
