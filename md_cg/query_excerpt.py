"""Query-focused, source-addressable excerpts; no model or answer-key input.

Paragraph IDF discounts ubiquitous query terms. Greedy marginal coverage chooses
up to four windows, with repeated terms discounted. Only original substrings are
returned, in source order, separated by an explicit omission marker. This is a
lexical evidence selector, not a semantic entailment or completeness guarantee.
"""
from __future__ import annotations

from collections import Counter
import math
import re

from .bm25 import tokenize

GAP = "\n[…]\n"
MAX_TERMS = 64
MAX_CANDIDATES = 256
MAX_WINDOWS = 4


def _merge(spans):
    out = []
    for start, end in sorted(set(map(tuple, spans))):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(end, out[-1][1]))
        else:
            out.append((start, end))
    return out


def _render(text, spans):
    spans = _merge(spans)
    if not spans:
        return ""
    body = GAP.join(text[start:end] for start, end in spans)
    return (GAP if spans[0][0] else "") + body + (GAP if spans[-1][1] < len(text) else "")


def _center(text, start, end, anchor, budget, estimate):
    """Keep the anchor and expand both sides within a token estimate budget."""
    left, right = start, min(end, anchor + 1)
    lo, hi = start, anchor
    while lo < hi:
        mid = (lo + hi) // 2
        if estimate(text[mid:right]) <= max(1, budget // 2):
            hi = mid
        else:
            lo = mid + 1
    left = lo
    lo, hi = right, end
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if estimate(text[left:mid]) <= budget:
            lo = mid
        else:
            hi = mid - 1
    right = lo
    # Spend unused space on the left when the anchor is near the paragraph end.
    lo, hi = start, left
    while lo < hi:
        mid = (lo + hi) // 2
        if estimate(text[mid:right]) <= budget:
            hi = mid
        else:
            lo = mid + 1
    return lo, right


def select(text, query, max_tokens):
    """Return content, original character offsets, and an explicit fallback.

    The budget uses the same estimate as recall(), including omission markers.
    Callers must treat offsets as indices into the *unchanged* input string.
    """
    from .mdcos import est_tokens, excerpt_tokens, _tokens_from_counts

    text = text or ""
    budget = int(max_tokens)
    if not text or budget <= 0:
        return {"content": "", "spans": [], "strategy": "query", "fallback": "empty"}
    if est_tokens(text) <= budget:
        return {"content": text, "spans": [[0, len(text)]], "strategy": "query", "fallback": None}

    def prefix(reason):
        content = excerpt_tokens(text, budget)
        end = len(content) - 1 if content else 0
        return {"content": content, "spans": [[0, end]] if end else [],
                "strategy": "query", "fallback": reason}

    terms = tuple(dict.fromkeys(tokenize(query or "")))[:MAX_TERMS]
    if not terms or budget < 16:
        return prefix("empty_query" if not terms else "small_budget")
    termset = set(terms)
    paragraphs = []
    for match in re.finditer(r"\S.*?(?=\n[ \t]*\n|\Z)", text, flags=re.S):
        body = match.group().rstrip()
        tf = Counter(t for t in tokenize(body) if t in termset)
        paragraphs.append((match.start(), match.start() + len(body), tf))
    if not paragraphs:
        return prefix("no_query_match")
    df = Counter(t for _, _, tf in paragraphs for t in tf)
    weights = {t: math.log1p((len(paragraphs) - df[t] + .5) / (df[t] + .5))
               * (.2 if len(t) == 1 and not t.isdigit() else 1.0) for t in terms}
    window_budget = max(8, (budget - 8) // 2)
    candidates = {}
    span_sizes = {}
    for start, end, tf in paragraphs:
        if not tf:
            continue
        body = text[start:end]
        if est_tokens(body) <= window_budget:
            spans = [(start, end)]
        else:
            anchors = []
            for term in sorted(tf, key=lambda t: (-weights[t], t))[:8]:
                for index, match in enumerate(re.finditer(re.escape(term), body, flags=re.I)):
                    if index == 4:
                        break
                    anchors.append((weights[term], start + match.start()))
            spans = [_center(text, start, end, anchor, window_budget, est_tokens)
                     for _, anchor in sorted(anchors, key=lambda row: (-row[0], row[1]))[:8]]
        for span in spans:
            content = text[span[0]:span[1]]
            counts = Counter(t for t in tokenize(content) if t in termset)
            if counts:
                candidates[span] = counts
                cjk = sum(1 for ch in content if 0x4e00 <= ord(ch) <= 0x9fff
                          or 0x3040 <= ord(ch) <= 0x30ff)
                span_sizes[span] = (cjk, len(content) - cjk)
    if not candidates:
        return prefix("no_query_match")

    def value(span, counts, covered):
        gain = sum(weights[t] * n / (n + 1) / (covered[t] + 1) for t, n in counts.items())
        return gain / max(1, _tokens_from_counts(*span_sizes[span])) ** .25

    covered = Counter()
    choices = sorted(candidates, key=lambda span: (-value(span, candidates[span], covered), span))[:MAX_CANDIDATES]
    selected = []
    selected_cjk = selected_other = 0
    gap_cjk = sum(1 for ch in GAP if 0x4e00 <= ord(ch) <= 0x9fff
                  or 0x3040 <= ord(ch) <= 0x30ff)
    gap_other = len(GAP) - gap_cjk
    for _ in range(MAX_WINDOWS):
        viable = []
        for span in choices:
            if any(span[0] < end and span[1] > start for start, end in selected):
                continue
            merged = _merge(selected + [span])
            gaps = len(merged) - 1 + int(merged[0][0] > 0) + int(merged[-1][1] < len(text))
            cjk, other = span_sizes[span]
            trial_tokens = _tokens_from_counts(selected_cjk + cjk + gaps * gap_cjk,
                                              selected_other + other + gaps * gap_other)
            if trial_tokens <= budget:
                viable.append(span)
        if not viable:
            break
        chosen = min(viable, key=lambda span: (-value(span, candidates[span], covered), span))
        selected.append(chosen)
        cjk, other = span_sizes[chosen]
        selected_cjk += cjk
        selected_other += other
        covered.update({t: 1 for t in candidates[chosen]})
        choices.remove(chosen)
    if not selected:
        return prefix("no_fitting_window")
    spans = _merge(selected)
    content = _render(text, spans)
    return {"content": content, "spans": [list(s) for s in spans],
            "strategy": "query", "fallback": None}
