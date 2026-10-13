"""Experimental query-time text delivery. Pure functions; no production hooks.

The budget counts the actual rendered text, including metadata and separators,
using the project's token ESTIMATOR, not a model tokenizer. All excerpts point
to source character offsets and retain their source hash. No text is invented.
"""
from __future__ import annotations

import hashlib
import json
import re

from .mdcg import expand_query_terms
from .mdcos import est_tokens, excerpt_tokens

COMPACT_FIELDS = ('id', 'created_at', 'source', 'conditions', 'verification_state',
                  'qualification', 'effective_from', 'effective_until', 'believed_at')


def query_excerpt(content, query, budget):
    if est_tokens(content) <= budget:
        return content, [{'start': 0, 'end': len(content)}]
    terms = tuple(dict.fromkeys(t.lower() for t in expand_query_terms(query) if t))[:64]
    # Bounded windows keep a single huge line from consuming all the budget.
    windows = []
    for match in re.finditer(r'[^\n]+(?:\n|$)', content):
        for start in range(match.start(), match.end(), 160):
            end = min(start + 240, match.end())
            block = content[start:end].lower()
            score = sum(1 for term in terms if term in block)
            windows.append((score, start, end))
    windows.sort(key=lambda w: (-w[0], w[1]))
    chosen = []
    for score, start, end in windows:
        if not score and chosen:
            continue
        if any(start < b and end > a for a, b in chosen):
            continue
        trial = sorted(chosen + [(start, end)])
        rendered = '\n[…]\n'.join(content[a:b] for a, b in trial)
        if est_tokens(rendered) <= budget:
            chosen = trial
    if not chosen:
        clipped = excerpt_tokens(content, budget)
        end = len(clipped[:-1]) if clipped.endswith('…') else len(clipped)
        return clipped, [{'start': 0, 'end': end}]
    text = '\n[…]\n'.join(content[a:b] for a, b in chosen)
    return text, [{'start': a, 'end': b} for a, b in chosen]


def deliver(rows, query, *, budget_tokens=240, max_item_tokens=120,
            mode='query_metadata'):
    """Consume production search_rrf rows, preserving their order and gates."""
    if mode not in ('prefix', 'query', 'query_metadata', 'query_metadata_compact'):
        raise ValueError('unknown delivery mode')
    if budget_tokens < 0 or max_item_tokens < 1:
        raise ValueError('invalid delivery budget')
    records, blocks = [], []
    schema = ('memory_metadata_columns=' + json.dumps(COMPACT_FIELDS, separators=(',', ':')) + '\n'
              if mode == 'query_metadata_compact' else '')

    def rendered(items):
        return schema + '\n\n'.join(items) if items else ''

    for node, score, qual, paths in rows:
        fm = node.get('frontmatter') or {}
        content = node.get('content') or ''
        metadata = {'id': node['id'], 'created_at': fm.get('created_at'),
                    'source': fm.get('source'), 'conditions': fm.get('condition_space'),
                    'verification_state': fm.get('verification_state', 'unverified'),
                    'qualification': qual.get('state')}
        for field in ('effective_from', 'effective_until', 'believed_at'):
            if fm.get(field) is not None:
                metadata[field] = fm[field]
        header = (json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
                  + '\n') if mode == 'query_metadata' else ''
        if mode == 'query_metadata_compact':
            header = json.dumps([metadata.get(field) for field in COMPACT_FIELDS],
                                ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n'
        remaining = budget_tokens - est_tokens(rendered(blocks))
        if schema and not blocks:
            remaining -= est_tokens(schema)
        room = min(max_item_tokens, remaining - est_tokens(header) - 2)
        if room < 8:
            continue
        if mode == 'prefix':
            excerpt = excerpt_tokens(content, room)
            end = len(excerpt[:-1]) if excerpt.endswith('…') else len(excerpt)
            spans = [{'start': 0, 'end': end}]
        else:
            excerpt, spans = query_excerpt(content, query, room)
        block = header + excerpt
        if est_tokens(rendered(blocks + [block])) > budget_tokens:
            continue
        blocks.append(block)
        records.append({'id': node['id'], 'metadata': metadata, 'spans': spans,
                        'source_sha256': hashlib.sha256(content.encode('utf-8')).hexdigest(),
                        'truncated': excerpt != content})
    text = rendered(blocks)
    return {'text': text, 'records': records, 'tokens_used': est_tokens(text),
            'budget': budget_tokens, 'mode': mode, 'token_measure': 'project_estimator'}
