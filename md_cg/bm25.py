"""Opt-in BM25 RRF path; no extra dependencies or persisted plaintext index.

Word TF postings and document lengths are scoped to the current eligible pool.
The read cache's path generations invalidate changed documents. Metadata still
requires O(N) enumeration; scoring visits only query postings and hydrates at
most 50 cards, matching search_rrf's existing per-path fusion limit.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import heapq
import math
import re
import time

# Fixed before benchmark test evaluation. Positive IDF and conventional defaults
# follow Lucene BM25Similarity; this is not a Lucene analyzer/codec replica.
K1, B = 1.2, 0.75
LIMIT = 50
_WORDS = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]+|[^\W_\u3400-\u9fff\uf900-\ufaff]+")


def tokenize(text):
    """Unicode words/numbers; Han unigrams + adjacent pairs, no stemming."""
    for word in _WORDS.findall(text.lower()):
        if "\u3400" <= word[0] <= "\u9fff" or "\uf900" <= word[0] <= "\ufaff":
            yield from word
            yield from (word[i:i + 2] for i in range(len(word) - 1))
        else:
            yield word


def access_key(cg):
    principal = getattr(cg, "principal", None)
    # In particular, lock/unlock must invalidate derived decrypted terms even
    # if neither the file generations nor the eligible metadata have changed.
    dek = getattr(cg, "dek", None)
    fingerprint = hashlib.sha256(dek).digest() if dek else None
    expires = getattr(principal, "expires_at", None)
    return (fingerprint, bool(expires and expires <= time.time()),
            tuple(getattr(principal, name, None) for name in (
                "tenant", "actor", "session", "clearance", "role")))


class BM25Index:
    def __init__(self):
        self.clear()

    def clear(self):
        self.docs = {}       # path -> (generation, Counter, length, importance, id)
        self.post = {}       # term -> {path: TF}
        self.total_length = 0
        self.nodes = self.dirty = self.access = None
        self.broad_gen = -1
        self.initialized = False

    def remove(self, path):
        old = self.docs.pop(path, None)
        if old is None:
            return
        self.total_length -= old[2]
        for term in old[1]:
            posting = self.post[term]
            del posting[path]
            if not posting:
                del self.post[term]

    def sync(self, cg, entries, report):
        dirty = getattr(cg, "_dirty", None)
        cached = (hasattr(cg, "_read_cache") and hasattr(dirty, "path_gen")
                  and hasattr(dirty, "broad_gen"))
        nodes, access = cg.index["nodes"], access_key(cg)
        if (not cached or self.nodes is not nodes or self.dirty is not dirty
                or self.access != access or dirty.broad_gen != self.broad_gen):
            self.clear()
        self.nodes, self.dirty, self.access = nodes, dirty, access
        self.broad_gen = dirty.broad_gen if cached else -1
        first = not self.initialized
        report["cache_mode"] = "path_generations" if cached else "uncached_rebuild"
        allowed = {entry["path"]: entry for entry in entries}
        # Statistics must exclude other sessions, roles, layers and gated-out
        # documents, including documents indexed by a preceding broader query.
        for path in self.docs.keys() - allowed.keys():
            self.remove(path)
        for path, entry in allowed.items():
            old = self.docs.get(path)
            if old is not None and dirty.path_gen.get(path, 0) <= old[0]:
                continue
            self.remove(path)
            report["build_reads" if first else "update_reads"] += 1
            fm, content, failure = cg._read_status(entry)
            if failure is not None or content is None:
                report["unavailable"] += 1
                continue  # Retry failures next query, never cache a negative.
            content = cg._open_content(fm.get("id"), fm, content)
            if content is None:
                report["unavailable"] += 1
                continue
            text = cg._positive_body(entry, content)
            tags = " ".join(str(t) for t in (fm.get("tags") or []))
            tf = Counter(tokenize(text + "\n" + tags))
            length = sum(tf.values())
            for term, count in tf.items():
                self.post.setdefault(term, {})[path] = count
            self.docs[path] = (getattr(dirty, "write_gen", 0), tf, length,
                               float(fm.get("importance") or 0),
                               str(fm.get("id") or path))
            self.total_length += length
        self.initialized = True
        report["documents"] = len(self.docs)
        report["tokens"] = self.total_length
        return allowed

    def rank(self, query, allowed, report):
        count = len(self.docs)
        if not count or not self.total_length:
            return []
        avg_length = self.total_length / count
        scores = defaultdict(float)
        for term in dict.fromkeys(tokenize(query)):
            posting = self.post.get(term, {})
            idf = math.log1p((count - len(posting) + 0.5) / (len(posting) + 0.5))
            report["posting_visits"] += len(posting)
            for path, tf in posting.items():
                length = self.docs[path][2]
                norm = K1 * (1.0 - B + B * length / avg_length)
                scores[path] += idf * tf * (K1 + 1.0) / (tf + norm)
        report["matched"] = len(scores)
        return heapq.nsmallest(LIMIT, scores.items(), key=lambda row: (
            -row[1], -self.docs[row[0]][3], self.docs[row[0]][4]))


def search(cg, query, entries, stat):
    report = {"k1": K1, "b": B, "limit": LIMIT, "input": len(entries),
              "build_reads": 0, "update_reads": 0, "unavailable": 0,
              "posting_visits": 0, "matched": 0}
    started = time.perf_counter()
    idx = getattr(cg, "_bm25_index", None)
    if idx is None:
        idx = cg._bm25_index = BM25Index()
    try:
        allowed = idx.sync(cg, entries, report)
        ranked = idx.rank(query, allowed, report)
        scores = dict(ranked)
        docs = cg._read_many([allowed[path] for path, _ in ranked], stat)
        report["hydrated"] = len(docs)
        report["unavailable"] += len(ranked) - len(docs)
        for path in scores.keys() - {e["path"] for e, _fm, _c in docs}:
            idx.remove(path)
        rows = [({"id": fm["id"], "path": e["path"],
                  "frontmatter": fm, "content": content}, scores[e["path"]])
                for e, fm, content in docs]
    except Exception as exc:
        idx.clear()
        report.update(fallback="lexical_index_error", error_type=type(exc).__name__)
        rows = cg._lexical(query, entries, stat)
    report["ms"] = (time.perf_counter() - started) * 1000
    return rows, report
