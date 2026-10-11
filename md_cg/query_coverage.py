# -*- coding: utf-8 -*-
"""Bounded Chinese recall keys spread over the query's eligible runs.

This is a candidate-generation experiment, not a semantic query rewriter.
The caller supplies the existing stop grams. No model, index or score changes
are needed. Time and temporary space are O(query length); output is bounded.
"""
from __future__ import annotations

import re


def spread_indices(size: int, count: int) -> list[int]:
    """Select ordered positions including both ends when count >= 2."""
    count = min(size, count)
    if count <= 0:
        return []
    if count == 1:
        return [size // 2]
    return [i * (size - 1) // (count - 1) for i in range(count)]


def select_cn_grams(query: str, min_run: int, cap: int,
                    stop_grams: set[str]) -> list[str]:
    """Share the key budget across runs, then spread each run's allocation.

    Deduplication assigns a gram to its first run. Runs with no new eligible
    grams consume no quota. Short queries keep their original order exactly.
    When the number of nonempty runs exceeds cap, the represented runs are
    themselves spread over the query; a finite budget cannot cover every run.
    cap <= 0 preserves cn_recall_grams' historical first-key behavior.
    """
    groups, flat, seen = [], [], set()
    for match in re.finditer(r"[\u4e00-\u9fff]{%d,}" % max(min_run, 2), query or ""):
        run, grams = match.group(), []
        for i in range(len(run) - 1):
            gram = run[i:i + 2]
            if gram not in stop_grams and gram not in seen:
                seen.add(gram)
                grams.append(gram)
                flat.append(gram)
        if grams:
            groups.append(grams)
    if cap <= 0:
        return flat[:1]
    if len(flat) <= cap:
        return flat
    if len(groups) > cap:
        groups = [groups[i] for i in spread_indices(len(groups), cap)]

    quotas, remaining = [0] * len(groups), cap
    while remaining:
        for i, grams in enumerate(groups):
            if quotas[i] < len(grams):
                quotas[i] += 1
                remaining -= 1
                if not remaining:
                    break
    selected = {grams[j] for grams, quota in zip(groups, quotas)
                for j in spread_indices(len(grams), quota)}
    return [gram for gram in flat if gram in selected]
