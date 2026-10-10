"""Opt-in BM25 RRF path; no extra dependencies or persisted plaintext index.

Word TF postings and document lengths are scoped to the current eligible pool.
The read cache's path generations invalidate changed documents. Unchanged,
time-independent eligible pools can be reused. Exact block bounds prune large
postings; first builds still read every eligible Markdown source file.
"""
from __future__ import annotations

from collections import Counter, OrderedDict, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
import hashlib
import heapq
import math
import os
import re
import time

# Fixed before benchmark test evaluation. Positive IDF and conventional defaults
# follow Lucene BM25Similarity; this is not a Lucene analyzer/codec replica.
K1, B = 1.2, 0.75
LIMIT = 50
BLOCK_SIZE = 128
BLOCK_THRESHOLD = 4096
BLOCK_CACHE_TERMS = 32
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


def candidate_pool(cg, **options):
    """Reuse eligibility, never query results; clock-dependent filters bypass.

    The normal candidate method remains the sole filter implementation. Reuse
    requires the same metadata object, dirty ledger, write generation, complete
    principal and filter arguments. Gates are still applied on every query.
    """
    dirty = getattr(cg, "_dirty", None)
    if (not hasattr(cg, "_read_cache") or not hasattr(dirty, "path_gen")
            or options.get("validity")
            or any(options.get(k) is not None for k in (
                "start_time", "end_time", "start_operator", "end_operator"))
            or os.environ.get("MDCG_BM25_POOL_CACHE", "1") == "0"):
        return cg._candidates(**options)
    from .hotcache import HotCache
    principal = getattr(cg, "principal", None)
    method = cg._candidates
    key = (dirty.write_gen, dirty.broad_gen, access_key(cg),
           id(principal), HotCache._canon(vars(principal)) if principal else None,
           getattr(method, "__func__", method), HotCache._canon(options))
    nodes = cg.index["nodes"]
    saved = getattr(cg, "_bm25_candidate_pool", None)
    if saved and saved[0] is nodes and saved[1] is dirty and saved[2] == key:
        cg._time_filter_stat = None
        return saved[3]
    entries = cg._candidates(**options)
    cg._bm25_candidate_pool = (nodes, dirty, key, entries)
    return entries


def _build_reads(cg, entries, report, stream):
    """Bounded I/O prefetch; parsing contracts and index writes are unchanged.

    At most twice the worker count is in flight. Index mutations, decryption
    and tokenization stay on the calling thread, in source entry order. This
    does not make simultaneous calls on a shared engine thread-safe.
    """
    try:
        workers = max(1, min(16, int(os.environ.get("MDCG_BM25_BUILD_WORKERS", "4"))))
    except ValueError:
        workers = 4
    if not stream:
        workers = 1
    report["build_workers"] = workers
    read_cache = getattr(cg, "_read_cache", {})
    body_cache = getattr(cg, "_positive_body_cache", {})

    def submit(entry, executor):
        path = entry["path"]
        existed = (path in read_cache, path in body_cache)
        value = executor.submit(cg._read_status, entry) if executor else cg._read_status(entry)
        return entry, value, existed

    def release(entry, existed):
        # Large builds retain terms rather than a second full plaintext copy.
        # Entries already cached by another retrieval path remain untouched.
        if stream:
            if not existed[0]:
                read_cache.pop(entry["path"], None)
            if not existed[1]:
                body_cache.pop(entry["path"], None)

    if workers == 1:
        for entry in entries:
            entry, value, existed = submit(entry, None)
            try:
                yield entry, value
            finally:
                release(entry, existed)
        return
    iterator, pending = iter(entries), deque()
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="bm25-read") as executor:
        try:
            for _ in range(workers * 2):
                entry = next(iterator, None)
                if entry is not None:
                    pending.append(submit(entry, executor))
            while pending:
                entry, future, existed = pending.popleft()
                try:
                    yield entry, future.result()
                finally:
                    release(entry, existed)
                following = next(iterator, None)
                if following is not None:
                    pending.append(submit(following, executor))
        finally:
            # Failed builds also release their own prefetched plaintext after
            # workers finish; existing cache contents keep their old policy.
            for entry, future, existed in pending:
                try:
                    future.result()
                finally:
                    release(entry, existed)


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
        self.version = 0
        self.rank_version = -1
        self.block_paths = self.ordinals = self.block_best = None
        self.term_blocks = OrderedDict()
        self.entries = self.allowed = self.write_gen = None

    def remove(self, path):
        old = self.docs.pop(path, None)
        if old is None:
            return
        self.total_length -= old[2]
        self.version += 1
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
        if (cached and self.initialized and self.entries is entries
                and self.write_gen == dirty.write_gen
                and len(self.docs) == len(self.allowed)):
            report.update(documents=len(self.docs), tokens=self.total_length,
                          pool_reused=True, build_workers=0)
            return self.allowed
        allowed = {entry["path"]: entry for entry in entries}
        # Statistics must exclude other sessions, roles, layers and gated-out
        # documents, including documents indexed by a preceding broader query.
        for path in self.docs.keys() - allowed.keys():
            self.remove(path)
        def changed():
            for path, entry in allowed.items():
                old = self.docs.get(path)
                if old is not None and dirty.path_gen.get(path, 0) <= old[0]:
                    continue
                self.remove(path)
                report["build_reads" if first else "update_reads"] += 1
                yield entry
        for entry, (fm, content, failure) in _build_reads(
                cg, changed(), report, stream=len(allowed) >= BLOCK_THRESHOLD):
            path = entry["path"]
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
            self.version += 1
        self.initialized = True
        self.entries, self.allowed = entries, allowed
        self.write_gen = getattr(dirty, "write_gen", None)
        report["documents"] = len(self.docs)
        report["tokens"] = self.total_length
        return allowed

    def rank(self, query, allowed, report):
        count = len(self.docs)
        if not count or not self.total_length:
            return []
        avg_length = self.total_length / count
        terms = [(self.post[term], math.log1p(
                    (count - len(self.post[term]) + 0.5) / (len(self.post[term]) + 0.5)), term)
                 for term in dict.fromkeys(tokenize(query)) if term in self.post]
        report["posting_candidates"] = sum(len(p) for p, _idf, _term in terms)
        if (terms and max(len(p) for p, _idf, _term in terms) >= BLOCK_THRESHOLD
                and os.environ.get("MDCG_BM25_BLOCK_MAX", "1") != "0"):
            return self._rank_blocks(terms, avg_length, report)
        scores = defaultdict(float)
        for posting, idf, _term in terms:
            report["posting_visits"] += len(posting)
            for path, tf in posting.items():
                length = self.docs[path][2]
                norm = K1 * (1.0 - B + B * length / avg_length)
                scores[path] += idf * tf * (K1 + 1.0) / (tf + norm)
        report["matched"] = len(scores)
        return heapq.nsmallest(LIMIT, scores.items(), key=lambda row: (
            -row[1], -self.docs[row[0]][3], self.docs[row[0]][4]))

    def _blocks(self, posting, term):
        cached = self.term_blocks.get(term)
        if cached is not None:
            self.term_blocks.move_to_end(term)
            return cached
        blocks = {}
        for path, tf in posting.items():
            slot = self.ordinals[path]
            block, bit = divmod(slot, BLOCK_SIZE)
            bitmap, pairs = blocks.get(block, (0, set()))
            pairs.add((tf, self.docs[path][2]))
            blocks[block] = (bitmap | (1 << bit), pairs)
        blocks = {block: (bitmap, tuple(pairs)) for block, (bitmap, pairs) in blocks.items()}
        if len(posting) >= BLOCK_THRESHOLD:
            self.term_blocks[term] = blocks
            while len(self.term_blocks) > BLOCK_CACHE_TERMS:
                self.term_blocks.popitem(last=False)
        return blocks

    def _rank_blocks(self, terms, avg_length, report):
        """Exact top 50 with per-block score bounds and deterministic ties.

        Bounds take the maximum of the actual (TF, length) pairs in each block,
        using the same floating-point operations as exhaustive scoring. Taking
        a maximum, then summing in query-term order, cannot understate any
        document's computed score. Bitmaps count all matches, even pruned ones.
        """
        if self.rank_version != self.version:
            self.block_paths = list(self.docs)
            self.ordinals = {path: i for i, path in enumerate(self.block_paths)}
            self.block_best = [min((-self.docs[p][3], self.docs[p][4])
                                   for p in self.block_paths[i:i + BLOCK_SIZE])
                               for i in range(0, len(self.block_paths), BLOCK_SIZE)]
            self.term_blocks.clear()
            self.rank_version = self.version
        bounds, matches = defaultdict(float), defaultdict(int)
        for posting, idf, term in terms:
            for block, (bitmap, pairs) in self._blocks(posting, term).items():
                bounds[block] += max(idf * tf * (K1 + 1.0) /
                    (tf + K1 * (1.0 - B + B * length / avg_length))
                    for tf, length in pairs)
                matches[block] |= bitmap
        report.update(matched=sum(bits.bit_count() for bits in matches.values()),
                      blocks=len(bounds), blocks_skipped=0, scored_documents=0,
                      algorithm="exact_block_max")
        key = lambda row: (-row[1], -self.docs[row[0]][3], self.docs[row[0]][4])
        best = []
        for block in sorted(bounds, key=lambda b: (-bounds[b], *self.block_best[b])):
            if len(best) == LIMIT and (-bounds[block], *self.block_best[block]) > key(best[-1]):
                report["blocks_skipped"] += 1
                continue
            bits, rows = matches[block], []
            while bits:
                low = bits & -bits
                path = self.block_paths[block * BLOCK_SIZE + low.bit_length() - 1]
                norm = K1 * (1.0 - B + B * self.docs[path][2] / avg_length)
                score = 0.0
                for posting, idf, _term in terms:
                    tf = posting.get(path)
                    if tf is not None:
                        score += idf * tf * (K1 + 1.0) / (tf + norm)
                        report["posting_visits"] += 1
                rows.append((path, score))
                bits ^= low
            report["scored_documents"] += len(rows)
            best = heapq.nsmallest(LIMIT, best + rows, key=key)
        return best


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
