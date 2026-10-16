"""Opt-in BM25 RRF path; no extra dependencies or persisted plaintext index.

Word TF postings and document lengths are scoped to the current eligible pool.
The read cache's path generations invalidate changed documents. Unchanged,
time-independent eligible pools can be reused. Exact block bounds prune large
postings; first builds still read every eligible Markdown source file.
"""
from __future__ import annotations

from collections import Counter, OrderedDict, defaultdict, deque
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
import hashlib
import heapq
from itertools import islice
import math
import os
import re
import time

# Fixed before benchmark test evaluation. Positive IDF and conventional defaults
# follow Lucene BM25Similarity; this is not a Lucene analyzer/codec replica.
K1, B = 1.2, 0.75
# `LIMIT` 的**单一真源** = `md_cg.mdcos.RRF_PATH_TERM_CAP`（issue #139 R-2）：
# BM25 路的返回上限与 search_rrf 融合 / 仅召回两处切片同源。mdcos 只在函数内
# 惰性 `from . import bm25`，故此处反向取值不成环；极端导入次序（mdcos 尚在
# 初始化 / 本模块被当顶层模块导入）下回落**同一字面量** 50，行为逐位不变。
try:
    from .mdcos import RRF_PATH_TERM_CAP as LIMIT
except Exception:                      # pragma: no cover - 仅极端导入次序触发
    LIMIT = 50

BLOCK_SIZE = 128
BLOCK_THRESHOLD = 4096
BLOCK_CACHE_TERMS = 32
BLOCK_UPDATE_LIMIT = 4096
BLOCK_SAMPLE = 256
BLOCK_PAIR_LIMIT = 32
STREAM_THRESHOLD = 32768
_WORDS = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]+|[^\W_\u3400-\u9fff\uf900-\ufaff]+")


class _PoolEntries(list):
    """候选池的**防御性副本**（#153①）：内容与缓存池逐位一致，但容器独立
    ——调用方原地修改不会写回 `cg._bm25_candidate_pool`。

    携带 `pool_key`：`candidate_pool` 的缓存命中判定是「同一 nodes / 同一
    dirty / 同键」，而 `BM25Index.sync` 原先用**对象同一性**判「这一批 entries
    还是上一批」；返回副本后同一性必然失配 ⇒ 池复用恒失效。把池键随副本带
    过去，`sync` 改看池键即可（语义等价，且对拷贝透明）。
    """
    __slots__ = ("pool_key",)

    def __init__(self, items, pool_key):
        super().__init__(items)
        self.pool_key = pool_key


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


class _PoolView(Sequence):
    """Read-only container for the engine's cached candidate sequence.

    Entries retain the existing read-only metadata contract. The private
    retrieval pipeline borrows this view in O(1); public callers still receive
    a defensive list. Slicing explicitly creates a separate container.
    """
    __slots__ = ("__items", "pool_key")

    def __init__(self, items, pool_key):
        self.__items, self.pool_key = items, pool_key

    def __len__(self):
        return len(self.__items)

    def __getitem__(self, index):
        return self.__items[index]

    def __iter__(self):
        return iter(self.__items)


def candidate_pool(cg, **options):
    """Public, independently mutable candidate container (entry dicts read-only)."""
    entries = candidate_pool_view(cg, **options)
    key = getattr(entries, "pool_key", None)
    return _PoolEntries(entries, key) if key is not None else entries


def candidate_pool_view(cg, **options):
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
    entries = _PoolView(cg._candidates(**options), key)
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
    real_cache = getattr(cg, "_realpath_cache", {})

    def submit(entry, executor):
        path = entry["path"]
        existed = (path in read_cache, path in body_cache, path in real_cache)
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
            if not existed[2]:
                real_cache.pop(entry["path"], None)

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
        self.docs = {}       # path -> (generation, unique terms, length, importance, id)
        self.post = {}       # term -> {path: TF}
        self.terms = {}      # per-index canonical strings; cleared with access scope
        self.total_length = 0
        self.nodes = self.dirty = self.access = None
        self.broad_gen = -1
        self.initialized = False
        self.version = 0
        self.rank_version = -1
        self.block_paths = self.ordinals = self.block_best = None
        self.term_blocks = OrderedDict()
        self.block_updates = {}
        self.block_dirty = {}
        self.block_holes = 0
        self.block_policy = OrderedDict()
        self.policy_version = -1
        self.entries = self.allowed = self.write_gen = None

    def remove(self, path):
        old = self.docs.pop(path, None)
        if old is None:
            return
        self._note_block_update(path, old[1], removed=True)
        self.total_length -= old[2]
        self.version += 1
        for term in old[1]:
            posting = self.post[term]
            del posting[path]
            if not posting:
                del self.post[term]
                del self.terms[term]
                self.term_blocks.pop(term, None)
                self.block_dirty.pop(term, None)

    def _reset_blocks(self):
        """Discard only derived bounds/layout, retaining current TF statistics."""
        self.block_paths = self.ordinals = self.block_best = None
        self.rank_version = -1
        self.term_blocks.clear()
        self.block_updates.clear()
        self.block_dirty.clear()
        self.block_holes = 0

    def _blocks_need_compaction(self, extra=0):
        return (self.block_paths is not None and len(self.block_paths) + extra
                > max(2 * BLOCK_SIZE, 2 * len(self.docs)))

    def _note_block_update(self, path, terms, removed=False):
        if self.ordinals is None:
            return
        # Keep only cached term names, so repeated edits cannot accumulate an
        # unbounded history of removed words. Large batches rebuild on demand.
        if path not in self.block_updates and len(self.block_updates) >= BLOCK_UPDATE_LIMIT:
            self._reset_blocks()
            return
        old_terms, new_terms = self.block_updates.setdefault(path, [set(), set()])
        target = old_terms if removed else new_terms
        if not removed:
            target.clear()
        target.update(term for term in terms if term in self.term_blocks)

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
        # #153①：候选池改由 `candidate_pool` 返回**防御性副本**，故「同一批
        # entries」不再能靠对象同一性判——副本携带池键（`_PoolEntries.pool_key`）
        # 时按池键判等；无池键（直调 `cg._candidates` 的路径）回落原同一性判据。
        _pool_same = self.entries is entries
        if not _pool_same:
            _ek = getattr(entries, "pool_key", None)
            _sk = getattr(self.entries, "pool_key", None)
            _pool_same = _ek is not None and _ek == _sk
        if (cached and self.initialized and _pool_same
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
                cg, changed(), report, stream=len(allowed) >= STREAM_THRESHOLD):
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
            doc_terms = []
            for term, count in tf.items():
                if term not in self.post:
                    self.post[term] = {}
                    self.terms[term] = term
                canonical = self.terms[term]
                self.post[canonical][path] = count
                doc_terms.append(canonical)
            # TF already lives in postings. Removal only needs the unique
            # terms. Share their strings within this index rather than keeping
            # a duplicate Counter and duplicate Han tokens for every document.
            # No global interning: lock/scope invalidation must release terms.
            self.docs[path] = (getattr(dirty, "write_gen", 0), tuple(doc_terms), length,
                               float(fm.get("importance") or 0),
                               str(fm.get("id") or path))
            self._note_block_update(path, doc_terms)
            self.total_length += length
            self.version += 1
        self.initialized = True
        if not self.docs:
            self._reset_blocks()
        elif self._blocks_need_compaction():
            # An exhaustive/absent query may never prepare blocks again after
            # a scope shrink. Drop its oversized layout immediately as well.
            self._reset_blocks()
        self.entries, self.allowed = entries, allowed
        self.write_gen = getattr(dirty, "write_gen", None)
        report["documents"] = len(self.docs)
        report["tokens"] = self.total_length
        if first and len(allowed) >= STREAM_THRESHOLD and os.environ.get("MDCG_BM25_BLOCK_MAX", "1") != "0":
            started = time.perf_counter()
            frequent = heapq.nlargest(BLOCK_CACHE_TERMS, self.post,
                                      key=lambda term: len(self.post[term]))
            for term in frequent:
                posting = self.post[term]
                if self._block_worthwhile(posting, term):
                    self._prepare_block_paths(report)
                    self._blocks(posting, term, report)
            report["block_terms_prepared"] = len(self.term_blocks)
            report["block_preparation_ms"] = (time.perf_counter() - started) * 1000
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
        if (os.environ.get("MDCG_BM25_BLOCK_MAX", "1") != "0"
                and terms and any(self._block_worthwhile(p, term) for p, _idf, term in terms)):
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

    def _block_worthwhile(self, posting, term):
        """Avoid bound overhead when a posting has highly varied TF/length.

        This only chooses an exact execution algorithm, never a candidate set.
        A bounded sample makes no distributional correctness assumption: a bad
        cost prediction can cost time, but cannot remove any search result.
        """
        if len(posting) < BLOCK_THRESHOLD:
            return False
        if self.policy_version != self.version:
            self.block_policy.clear()
            self.policy_version = self.version
        if term not in self.block_policy:
            pairs = {(tf, self.docs[path][2]) for path, tf in islice(posting.items(), BLOCK_SAMPLE)}
            self.block_policy[term] = len(pairs) <= BLOCK_PAIR_LIMIT
            while len(self.block_policy) > BLOCK_CACHE_TERMS:
                self.block_policy.popitem(last=False)
        self.block_policy.move_to_end(term)
        return self.block_policy[term]

    def _blocks(self, posting, term, report=None):
        cached = self.term_blocks.get(term)
        if cached is not None:
            for block in self.block_dirty.pop(term, ()):
                start = block * BLOCK_SIZE
                paths = self.block_paths[start:start + BLOCK_SIZE]
                bitmap, pairs = 0, set()
                for bit, path in enumerate(paths):
                    tf = posting.get(path) if path is not None else None
                    if tf is not None:
                        bitmap |= 1 << bit
                        pairs.add((tf, self.docs[path][2]))
                if bitmap:
                    cached[block] = (bitmap, tuple(pairs))
                else:
                    cached.pop(block, None)
                if report is not None:
                    report["block_repaired_blocks"] += 1
                    report["block_update_slots"] += len(paths)
            self.term_blocks.move_to_end(term)
            return cached
        if report is not None:
            report["block_rebuild_postings"] += len(posting)
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
                evicted, _ = self.term_blocks.popitem(last=False)
                self.block_dirty.pop(evicted, None)
        return blocks

    def _prepare_block_paths(self, report=None):
        if self.rank_version == self.version:
            return
        # Unchanged documents keep their slots. Changed/new documents append
        # together, rather than scattering new TF/length outliers across old
        # blocks and loosening many bounds. Compact this delta tail when its
        # holes would exceed half the layout; bulk changes rebuild on demand.
        rebuild = (self.ordinals is None or not self.block_updates
                   or self._blocks_need_compaction(sum(p in self.docs for p in self.block_updates)))
        if rebuild:
            self.block_paths = list(self.docs)
            self.ordinals = {path: i for i, path in enumerate(self.block_paths)}
            self.block_best = [min((-self.docs[p][3], self.docs[p][4])
                                   for p in self.block_paths[i:i + BLOCK_SIZE])
                               for i in range(0, len(self.block_paths), BLOCK_SIZE)]
            self.term_blocks.clear()
            self.block_dirty.clear()
            self.block_holes = 0
            if report is not None:
                report["block_layout_rebuilt"] = True
        else:
            touched = set()

            def mark(slot, terms):
                block = slot // BLOCK_SIZE
                touched.add(block)
                for term in terms:
                    if term in self.term_blocks:
                        self.block_dirty.setdefault(term, set()).add(block)

            # Tombstone old slots, then group replacements in the delta tail.
            # Old and new cached terms both invalidate their affected blocks.
            for path, (old_terms, _new_terms) in self.block_updates.items():
                if path in self.ordinals:
                    slot = self.ordinals.pop(path)
                    self.block_paths[slot] = None
                    self.block_holes += 1
                    mark(slot, old_terms)
            for path, (_old_terms, new_terms) in self.block_updates.items():
                if path not in self.docs:
                    continue
                slot = len(self.block_paths)
                self.block_paths.append(path)
                self.ordinals[path] = slot
                mark(slot, new_terms)
            for block in sorted(touched):
                best = min(((-self.docs[p][3], self.docs[p][4])
                            for p in self.block_paths[block * BLOCK_SIZE:(block + 1) * BLOCK_SIZE]
                            if p is not None), default=(math.inf, ""))
                if block == len(self.block_best):
                    self.block_best.append(best)
                else:
                    self.block_best[block] = best
            if report is not None:
                report["block_layout_touched"] += len(touched)
        self.block_updates.clear()
        self.rank_version = self.version

    def _rank_blocks(self, terms, avg_length, report):
        """Exact top 50 with per-block score bounds and deterministic ties.

        Bounds take the maximum of the actual (TF, length) pairs in each block,
        using the same floating-point operations as exhaustive scoring. Taking
        a maximum, then summing in query-term order, cannot understate any
        document's computed score. Bitmaps count all matches, even pruned ones.
        """
        self._prepare_block_paths(report)
        bounds, matches = defaultdict(float), defaultdict(int)
        for posting, idf, term in terms:
            for block, (bitmap, pairs) in self._blocks(posting, term, report).items():
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
              "posting_visits": 0, "matched": 0, "block_layout_rebuilt": False,
              "block_layout_touched": 0, "block_repaired_blocks": 0,
              "block_update_slots": 0, "block_rebuild_postings": 0}
    started = time.perf_counter()
    idx = getattr(cg, "_bm25_index", None)
    if idx is None:
        idx = cg._bm25_index = BM25Index()
    try:
        allowed = idx.sync(cg, entries, report)
        hydrated = {}
        report.update(hydration_rounds=0, hydration_reads=0)
        while True:
            ranked = idx.rank(query, allowed, report)
            scores = dict(ranked)
            # Keep at most this ranked batch's payloads, even across retries.
            hydrated = {path: doc for path, doc in hydrated.items() if path in scores}
            pending = [allowed[path] for path, _ in ranked if path not in hydrated]
            if pending:
                report["hydration_rounds"] += 1
                report["hydration_reads"] += len(pending)
                for doc in cg._read_many(pending, stat):
                    hydrated[doc[0]["path"]] = doc
            unavailable = scores.keys() - hydrated.keys()
            if not unavailable:
                break
            # A missing source changes both Top-K eligibility and corpus IDF /
            # average length. Re-rank all winners with the updated statistics;
            # appending the next old rank would mix incompatible scores.
            report["unavailable"] += len(unavailable)
            before = len(idx.docs)
            for path in unavailable:
                idx.remove(path)
            if len(idx.docs) >= before:
                raise RuntimeError("BM25 hydration made no progress")
            # Each retry removes at least one indexed document. A later query
            # can retry it through sync's existing incomplete-pool condition.
        docs = [hydrated[path] for path, _ in ranked]
        report.update(hydrated=len(docs), documents=len(idx.docs), tokens=idx.total_length)
        rows = [({"id": fm["id"], "path": e["path"],
                  "frontmatter": fm, "content": content}, scores[e["path"]])
                for e, fm, content in docs]
    except Exception as exc:
        idx.clear()
        report.update(fallback="lexical_index_error", error_type=type(exc).__name__)
        rows = cg._lexical(query, entries, stat)
    report["ms"] = (time.perf_counter() - started) * 1000
    return rows, report
