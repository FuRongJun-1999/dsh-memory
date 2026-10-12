"""Opt-in, offline experience reflection using the existing graph and inbox.

No model calls, command execution, production hooks or automatic acceptance.
A successful check in a supplied trace is evidence of that observation only;
neither this module nor an LLM can authenticate the trace's external origin.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

SCHEMA = 1
REFLECTOR_VERSION = 2
MARKER = '.memory-rsi-sandbox.json'
MAX_EVENTS = 128
MAX_TRACE_BYTES = 65536
MAX_SCAN = 1000


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def normalized_conditions(values):
    """The existing condition_space 'all' relation is order-independent."""
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(sorted({value.strip() for value in values
                         if isinstance(value, str) and value.strip()}))


def create_sandbox(path):
    """Create a NEW lab directory. Refuse to bless any existing memory root."""
    base = Path(path).resolve()
    base.mkdir(parents=True, exist_ok=False)
    (base / 'graph').mkdir()
    (base / MARKER).write_text(canonical({'schema': SCHEMA, 'purpose': 'offline-memory-rsi'}),
                               encoding='utf-8')
    return base / 'graph'


@dataclass(frozen=True)
class Evidence:
    trace_id: str
    trace_hash: str
    event_id: str


@dataclass(frozen=True)
class Candidate:
    error: str
    action: str
    conditions: tuple[str, ...]
    scope: str
    evidence: tuple[Evidence, ...]
    related: tuple[str, ...] = ()
    verification_status: str = 'candidate'
    confidence: float = 0.5

    @property
    def slot(self):
        return digest([self.error, self.conditions, self.scope])

    @property
    def key(self):
        return digest([self.slot, self.action])


class MemoryRSILab:
    def __init__(self, cg, sandbox, *, enabled=False):
        if enabled is not True:
            raise ValueError('Memory-RSI is disabled; explicitly enable an offline sandbox')
        base = Path(sandbox).resolve()
        marker = json.loads((base / MARKER).read_text(encoding='utf-8'))
        if marker != {'schema': SCHEMA, 'purpose': 'offline-memory-rsi'}:
            raise ValueError('invalid sandbox marker')
        if Path(cg.root).resolve() != base / 'graph':
            raise ValueError('graph must belong to this offline sandbox')
        self.cg = cg

    def _require(self, op):
        principal = getattr(self.cg, 'principal', None)
        if principal is not None:
            principal.require_op(op)

    def record_experience(self, trace):
        """Record raw structured events in the SAME contextual graph."""
        self._require('write')
        value = json.loads(canonical(trace))  # detach mutable caller objects
        if not isinstance(value, dict) or not isinstance(value.get('events'), list):
            raise ValueError('trace must contain events')
        if not isinstance(value.get('scope'), str) or not value['scope'].strip():
            raise ValueError('explicit scope is required')
        conditions = value.get('conditions')
        if (not isinstance(conditions, list) or not conditions or
                any(not isinstance(c, str) or not c.strip() for c in conditions)):
            raise ValueError('explicit conditions are required')
        events = value['events']
        if not 1 <= len(events) <= MAX_EVENTS:
            raise ValueError('event resource limit')
        ids = []
        for event in events:
            if (not isinstance(event, dict) or
                    event.get('kind') not in ('error', 'action', 'check') or
                    not isinstance(event.get('id'), str) or not event['id'] or
                    not isinstance(event.get('text'), str) or not event['text'].strip()):
                raise ValueError('invalid event')
            ids.append(event['id'])
        if len(set(ids)) != len(ids):
            raise ValueError('duplicate event id')
        value['schema'] = SCHEMA
        body = canonical(value)
        if len(body.encode('utf-8')) > MAX_TRACE_BYTES:
            raise ValueError('trace byte resource limit')
        nid = 'rsi_trace_' + digest(value)[:24]
        old = self.cg.get(nid)
        if old:
            if old['content'].strip() != body:
                raise ValueError('trace identity collision')
            return nid
        self.cg.add(nid, body, layer='contextual', role='tool-output',
                    verification_basis='data', verification_state='unverified',
                    source='memory-rsi:structured-trace',
                    memory_rsi={'kind': 'experience', 'hash': digest(value)})
        self.cg.flush()
        return nid

    def _trace(self, trace_id):
        self._require('read')
        node = self.cg.get(trace_id)
        if not node or (node.get('frontmatter', {}).get('memory_rsi') or {}).get('kind') != 'experience':
            raise ValueError('experience missing or inaccessible')
        value = json.loads(node['content'])
        actual = digest(value)
        if actual != node['frontmatter']['memory_rsi'].get('hash'):
            raise ValueError('experience changed')
        return value, actual

    def reflect(self, trace_id):
        """Extract only actions whose relevant, action-bound tool checks all pass."""
        trace, fingerprint = self._trace(trace_id)
        by_id = {e['id']: (i, e) for i, e in enumerate(trace['events'])}
        candidates, withheld, groups, latest_action = [], [], {}, {}
        for index, check in enumerate(trace['events']):
            if check['kind'] == 'action':
                latest_action[check.get('error_id')] = check['id']
            if check['kind'] != 'check':
                continue
            action_item = by_id.get(check.get('action_id'))
            error_item = by_id.get(check.get('error_id'))
            if (not action_item or not error_item or
                    not error_item[0] < action_item[0] < index or
                    action_item[1]['kind'] != 'action' or error_item[1]['kind'] != 'error' or
                    action_item[1].get('error_id') != error_item[1]['id'] or
                    check.get('source') != 'tool'):
                withheld.append({'check_id': check['id'], 'reason': 'unverified_or_failed_check'})
                continue
            if latest_action.get(error_item[1]['id']) != action_item[1]['id']:
                withheld.append({'check_id': check['id'], 'reason': 'action_replaced_before_check'})
                continue
            key = error_item[1]['id'], action_item[1]['id']
            groups.setdefault(key, (error_item[1], action_item[1], []))[2].append(check)
        for error, action, checks in groups.values():
            if any(check.get('passed') is not True for check in checks):
                withheld.extend({'check_id': check['id'], 'reason': 'one_or_more_bound_checks_failed'}
                                for check in checks)
                continue
            refs = tuple(Evidence(trace_id, fingerprint, e['id']) for e in (error, action, *checks))
            candidates.append(Candidate(error['text'], action['text'],
                                        normalized_conditions(trace['conditions']), trace['scope'], refs))
        return {'candidates': candidates, 'withheld': withheld,
                'status': 'candidate_only', 'reflector_version': REFLECTOR_VERSION,
                'external_authenticity': 'not_authenticated'}

    def verify(self, candidate):
        """Check byte identity AND semantic scope; a quote match alone is insufficient."""
        if not isinstance(candidate, Candidate) or not candidate.evidence:
            return {'ok': False, 'reason': 'missing_evidence'}
        trace_ids = {e.trace_id for e in candidate.evidence}
        try:
            supported = []
            for tid in sorted(trace_ids):
                _, fingerprint = self._trace(tid)
                if any(e.trace_hash != fingerprint for e in candidate.evidence if e.trace_id == tid):
                    return {'ok': False, 'reason': 'stale_evidence'}
                supported.extend(self.reflect(tid)['candidates'])
            # The deterministic extractor defines the supported claim. Generated
            # broader conditions/action/confidence may not inherit its evidence.
            if candidate not in supported:
                return {'ok': False, 'reason': 'claim_or_scope_not_supported'}
        except (ValueError, KeyError, TypeError):
            return {'ok': False, 'reason': 'evidence_unavailable_or_changed'}
        return {'ok': True, 'status': 'observation_checked',
                'knowledge_verified': False, 'external_authenticity': 'not_authenticated'}

    def _versions(self):
        entries = list(self.cg.index['nodes'])
        pending = self.cg.review_list()
        if len(entries) + len(pending) > MAX_SCAN:
            raise ValueError('conflict_scan_resource_limit')
        versions = []
        for item in pending:
            summary = (item.get('extra') or {}).get('memory_rsi') or {}
            if summary.get('kind') == 'lesson':
                versions.append((item['id'], item['pid'], summary))
        for node_id in entries:
            # Read through the existing visibility/decryption boundary.
            node = self.cg.get(node_id)
            if not node:
                continue
            summary = node['frontmatter'].get('memory_rsi') or {}
            if summary.get('kind') == 'lesson':
                versions.append((node['id'], None, summary))
        return versions

    def curate(self, candidate):
        self._require('write')
        verdict = self.verify(candidate)
        if not verdict['ok']:
            return {'status': 'rejected', **verdict, 'committed': False}
        try:
            versions = self._versions()
        except ValueError as error:
            return {'status': 'deferred', 'reason': str(error), 'committed': False}
        legacy = [nid for nid, _, summary in versions
                  if summary.get('reflector_version') != REFLECTOR_VERSION
                  and summary.get('scope') == candidate.scope
                  and normalized_conditions(summary.get('conditions')) == candidate.conditions]
        if legacy:
            return {'status': 'deferred', 'reason': 'legacy_reflector_requires_review',
                    'related': legacy, 'committed': False}
        conflicts = [nid for nid, _, s in versions
                     if s.get('slot') == candidate.slot and s.get('key') != candidate.key]
        if conflicts:
            return {'status': 'deferred', 'reason': 'conflicting_action_requires_review',
                    'related': conflicts, 'committed': False}
        matching = [(nid, pid, s) for nid, pid, s in versions if s.get('key') == candidate.key]
        refs = {(e.trace_id, e.trace_hash, e.event_id) for e in candidate.evidence}
        previous = []
        for nid, pid, summary in matching:
            old_refs = {tuple(e) for e in summary['evidence']}
            if refs <= old_refs:
                return {'status': 'duplicate', 'pid': pid, 'node_id': nid, 'committed': False}
            refs.update(old_refs)
            previous.append(nid)
        # Merged observations must still resolve. Old proposals remain immutable.
        for tid, fingerprint, _ in refs:
            try:
                _, actual = self._trace(tid)
            except (ValueError, KeyError):
                return {'status': 'deferred', 'reason': 'prior_evidence_changed', 'committed': False}
            if actual != fingerprint:
                return {'status': 'deferred', 'reason': 'prior_evidence_changed', 'committed': False}
        refs = sorted(refs)
        trace_ids = sorted({e[0] for e in refs})
        summary = {'kind': 'lesson', 'reflector_version': REFLECTOR_VERSION,
                   'slot': candidate.slot, 'key': candidate.key,
                   'error': candidate.error, 'action': candidate.action,
                   'evidence': refs, 'scope': candidate.scope, 'conditions': candidate.conditions,
                   'related': sorted(previous), 'verification_status': 'observation_checked',
                   'confidence': candidate.confidence}
        # Keep scope and raw observation explicit; never claim a universal fix.
        content = ('# 功能名：经观察的修复候选\n'
                   f'# 生效条件：{candidate.error}；' + '；'.join(candidate.conditions) + '\n'
                   f'# 子功能：适用范围 {candidate.scope}\n'
                   f'# 执行：{candidate.action}\n'
                   '# 验证方式：原始轨迹中的工具检查；仍须独立复验与人工审核\n'
                   '# 不适用条件：条件或范围不匹配；原始证据失效；未经独立复验\n\n'
                   + canonical(summary))
        nid = 'rsi_lesson_' + digest([candidate.key, refs])[:24]
        result = self.cg.propose(
            nid, content, layer='knowledge', tags=['memory-rsi', 'candidate'],
            condition_space={'all': [candidate.error, *candidate.conditions]},
            verify={'kind': 'data', 'assertions': [
                'evidence hashes and action-bound successful checks resolve',
                'scope remains local; independent task validation and human review required']},
            info=True, confidence=candidate.confidence, verification_basis='data',
            verification_state='unverified', derived_from=trace_ids,
            source='memory-rsi:reflector', memory_rsi=summary)
        return {'status': 'proposed', 'node_id': nid, **result, 'committed': False,
                'merged_observations': len(trace_ids), 'supersedes_proposals': previous}

    def rollback(self, pid):
        """Cancel a pending proposal with the existing audited decision API."""
        return self.cg.review_decide(pid, 'reject', reason='offline Memory-RSI rollback')


def recommend_strategy(validation, *, max_candidates=6):
    """Bounded, data-only selection. No scorer/code mutation or activation.

    Input is validation ONLY. A caller must evaluate the chosen strategy once
    on a frozen holdout and obtain human review before any deployment.
    """
    if not 1 <= len(validation) <= min(6, max_candidates):
        raise ValueError('candidate resource limit')
    if any(v.get('split') != 'validation' for v in validation):
        raise ValueError('selection accepts validation only')
    eligible = [v for v in validation if v['budget_ok'] and v['unsafe_accepts'] == 0]
    best = max(eligible, key=lambda v: (v['evidence_rate'], -v['p95_ms'])) if eligible else None
    return {'recommendation': best['name'] if best else None, 'rounds': 1,
            'accepted': False, 'requires': ['frozen_holdout', 'human_review'],
            'rollback': 'disable experimental strategy; original API is unchanged'}
