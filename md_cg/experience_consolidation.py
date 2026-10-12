"""Opt-in, offline source-supported experience consolidation.

The graph remains the only memory authority. Existing MemoryRSILab stores the
raw experience; an independently configured verifier authenticates execution
receipts. A capsule groups checked observations under EXACT recorded context.
It is not a proof that a model-written summary is universally true. No MCP,
production scheduler, model calls, permissions changes, or automatic approval
are installed here. Persistent verification_state remains unverified.
"""
from __future__ import annotations

import json
from pathlib import Path

from .memory_rsi import MemoryRSILab, canonical, digest
from . import trust, lifecycle

SCHEMA = 1
MAX_NODES = 1000
RECEIPT_KIND = 'memory-execution-receipt-v1'
META = 'experience_consolidation'


def _json(value):
    """Reject non-finite/non-JSON inputs before hashing or condition comparison."""
    json.dumps(value, allow_nan=False)
    return json.loads(canonical(value))


def context_verdict(required, current):
    """Unknown is DEFER; typed mismatches are REJECT, including False vs 0."""
    if not isinstance(required, dict) or not required:
        return {'state': 'DEFER', 'reason': 'missing_recorded_context'}
    if not isinstance(current, dict):
        return {'state': 'DEFER', 'reason': 'missing_current_context'}
    missing = [k for k in required if k not in current]
    different = [k for k in required if k in current and
                 canonical(required[k]) != canonical(current[k])]
    if different:
        return {'state': 'REJECT', 'reason': 'outside_recorded_scope', 'fields': different}
    if missing:
        return {'state': 'DEFER', 'reason': 'unknown_required_conditions', 'fields': missing}
    return {'state': 'ACCEPT', 'reason': 'all_recorded_conditions_confirmed'}


class VerifiedExperiences:
    def __init__(self, cg, sandbox, *, receipt_verifier, enabled=False, min_sources=2):
        # Reuse the existing new-sandbox marker/root/opt-in check.
        try:
            self.lab = MemoryRSILab(cg, sandbox, enabled=enabled)
        except OSError as exc:
            raise ValueError('offline experience sandbox marker is unavailable') from exc
        if not callable(receipt_verifier):
            raise ValueError('an independent receipt verifier is required')
        if not isinstance(min_sources, int) or min_sources < 2:
            raise ValueError('at least two source task observations are required')
        self.cg = cg
        self.verifier = receipt_verifier
        self.min_sources = min_sources

    def _nodes(self, kind):
        ids = list(self.cg.index.get('nodes') or {})
        if len(ids) > MAX_NODES:
            raise ValueError('experience scan resource limit')
        out = []
        for nid in ids:
            node = self.cg.get(nid)  # Preserve existing visibility/decryption.
            if node and (node['frontmatter'].get(META) or {}).get('kind') == kind:
                out.append(node)
        return out

    def _auth(self, envelope):
        try:
            return bool(self.verifier(_json(envelope)))
        except Exception:
            return False

    def _bound(self, trace_id, envelope):
        if not self._auth(envelope):
            raise ValueError('execution receipt is not authenticated')
        trace, fingerprint = self.lab._trace(trace_id)
        p = envelope.get('payload') or {}
        if (p.get('kind') != RECEIPT_KIND or p.get('trace_id') != trace_id or
                p.get('trace_hash') != fingerprint or
                p.get('task_id') != trace.get('task_id') or
                p.get('candidate_sha256') != trace.get('candidate_sha256') or
                canonical(p.get('context')) != canonical(trace.get('context')) or
                p.get('scope') != trace.get('scope') or
                not isinstance(p.get('passed'), bool) or
                p['passed'] is not (trace.get('outcomes') or {}).get('passed')):
            raise ValueError('receipt does not bind this trace, task, context and result')
        return trace, p

    def attach_receipt(self, trace_id, envelope):
        self.lab._require('write')
        trace, p = self._bound(trace_id, envelope)
        nid = 'experience_receipt_' + digest(envelope)[:24]
        old = self.cg.get(nid)
        if old:
            if old['content'].strip() != canonical(envelope):
                raise ValueError('receipt identity collision')
            return nid
        self.cg.add(nid, canonical(envelope), layer='contextual', role='tool-output',
                    verification_basis='data', verification_state='unverified',
                    derived_from=[trace_id], source='experience-consolidation:execution-receipt',
                    immutable=True, **{META: {'schema': SCHEMA, 'kind': 'receipt',
                                             'trace_id': trace_id, 'task_id': p['task_id']}})
        self.cg.flush()
        return nid

    def _observation(self, trace_id):
        for node in self._nodes('receipt'):
            meta = node['frontmatter'][META]
            if meta['trace_id'] != trace_id:
                continue
            envelope = json.loads(node['content'])
            trace, payload = self._bound(trace_id, envelope)
            source = self.cg.get(trace_id)
            fm = source['frontmatter']
            if trust.is_expired(fm) or trust.state_of(fm) in ('doubted', 'rechecking', 'expired'):
                raise ValueError('source observation expired or no longer trusted')
            if lifecycle.is_archived(fm):
                raise ValueError('source observation is archived')
            return trace, payload, node['id']
        raise ValueError('independent execution receipt missing')

    def _heads(self):
        heads = {}
        for node in self._nodes('capsule'):
            m = node['frontmatter'][META]
            old = heads.get(m['slot'])
            if old is None or (m['version'], node['id']) > (old['frontmatter'][META]['version'], old['id']):
                heads[m['slot']] = node
        return heads

    def _append(self, slot, summary, content, previous=None):
        version = previous['frontmatter'][META]['version'] + 1 if previous else 1
        summary = {**summary, 'schema': SCHEMA, 'kind': 'capsule', 'slot': slot,
                   'version': version, 'previous_version': previous['id'] if previous else None,
                   'knowledge_verified': False, 'automatic_production_acceptance': False}
        nid = 'experience_capsule_' + digest([slot, version, summary, content])[:24]
        parents = sorted(set(summary['source_experience_ids'] + summary['receipt_ids'] +
                             ([previous['id']] if previous else []) + summary.get('feedback_trace_ids', [])))
        self.cg.add(nid, content, layer='knowledge', tags=['experience-capsule', 'source-supported-candidate'],
                    verification_basis='data', verification_state='unverified',
                    source='experience-consolidation:offline-candidate', derived_from=parents,
                    depends_on=parents, condition_space={'all': [f'{k}={canonical(v)}' for k, v in summary['preconditions'].items()]},
                    # These words describe the boundary, not a newly verified
                    # empirical claim about every out-of-scope task.
                    non_applicable_conditions=['必要条件不同或缺失', '原始执行证据不可用'],
                    immutable=True, **{META: summary})
        self.cg.flush()
        return {'status': summary['verification_status'], 'node_id': nid, 'version': version,
                'source_tasks': summary.get('supporting_task_ids', []), 'knowledge_verified': False,
                'experimental_only': True}

    def consolidate(self, trace_ids, *, apply=False):
        self.lab._require('write' if apply else 'read')
        observations = []
        try:
            for tid in sorted(set(trace_ids)):
                trace, p, rid = self._observation(tid)
                if p['passed'] is not True or not self.lab.reflect(tid)['candidates']:
                    return {'status': 'deferred', 'reason': 'failed_or_unbound_action'}
                observations.append((tid, trace, p, rid))
        except (ValueError, KeyError, TypeError) as exc:
            return {'status': 'deferred', 'reason': str(exc)}
        tasks = sorted({p['task_id'] for _, _, p, _ in observations})
        if len(tasks) < self.min_sources:
            return {'status': 'deferred', 'reason': 'insufficient_distinct_source_tasks'}
        contexts = {canonical(p['context']) for _, _, p, _ in observations}
        scopes = {p['scope'] for _, _, p, _ in observations}
        if len(contexts) != 1 or len(scopes) != 1:
            return {'status': 'deferred', 'reason': 'different_scopes_are_not_automatically_generalized'}
        context = _json(observations[0][2]['context'])
        if not context:
            return {'status': 'deferred', 'reason': 'explicit_context_required'}
        claims = {}
        claim_sets = []
        for _, _, p, _ in observations:
            claim_sets.append(set(p.get('checked_claims') or {}))
            for key, value in (p.get('checked_claims') or {}).items():
                if key in claims and canonical(claims[key]) != canonical(value):
                    return {'status': 'deferred', 'reason': 'contradictory_checked_claims', 'field': key}
                claims[key] = value
        repeated = set.intersection(*claim_sets) if claim_sets else set()
        claims = {key: claims[key] for key in sorted(repeated)}
        if not claims:
            return {'status': 'deferred', 'reason': 'no_explicit_checked_claims'}
        scope = next(iter(scopes))
        slot = digest([scope, context, sorted(claims)])
        old = self._heads().get(slot)
        tids = sorted(tid for tid, _, _, _ in observations)
        if old:
            m = old['frontmatter'][META]
            if m['verification_status'] != 'source_supported_candidate':
                return {'status': 'deferred', 'reason': 'prior_feedback_requires_independent_revalidation'}
            # A new version extends old support. Never silently forget a source.
            missing = set(m['source_experience_ids']) - set(tids)
            if missing:
                return self.consolidate(sorted(set(tids) | missing), apply=apply)
            if m['source_experience_ids'] == tids and m['checked_claims'] == claims:
                return {'status': 'duplicate', 'node_id': old['id'], 'version': m['version']}
            for key, value in m['checked_claims'].items():
                if key in claims and canonical(claims[key]) != canonical(value):
                    return {'status': 'deferred', 'reason': 'prior_checked_claim_conflict'}
        summary = {'scope': scope, 'preconditions': context,
            'negative_conditions': [{'field': k, 'outside_scope_when_not_equal': v} for k, v in context.items()],
            'source_experience_ids': tids, 'receipt_ids': sorted(r for _, _, _, r in observations),
            'supporting_task_ids': tasks, 'checked_claims': claims,
            'verification_status': 'source_supported_candidate',
            'confidence_audit': {'source_task_count': len(tasks), 'independent_family_count': len(scopes),
                                 'calibrated_success_probability': None}, 'feedback_trace_ids': []}
        lines = ['# 功能名：限定条件的任务经验', '# 生效条件：' + '；'.join(f'{k}={canonical(v)}' for k, v in context.items()),
                 '# 子功能：' + scope, '# 执行：复用下列已检查的任务要求与实际动作前，确认当前条件和代码语义',
                 '# 验证方式：独立控制器回执、原始轨迹哈希和绑定动作检查；泛化尚待新任务验证',
                 '# 不适用条件：必要条件不同或缺失；原始执行证据不可用；已有失败反馈', '',
                 'Source-supported observations, not a universal theorem. Persistent verification_state=unverified.',
                 'Required context: ' + canonical(context), 'Source experiences: ' + ', '.join(tids),
                 'Checked source-task requirements: ' + canonical(claims)]
        for tid, trace, _, _ in observations:
            lines += ['', 'Observed source task: ' + trace['task_id'],
                      'Observed checked action: ' + self.lab.reflect(tid)['candidates'][0].action,
                      'Unverified model summaries remain in the original experience; they are not promoted into this capsule.']
        content = '\n'.join(lines)
        if not apply:
            return {'status': 'candidate', 'summary': summary, 'content': content, 'knowledge_verified': False}
        return self._append(slot, summary, content, old)

    def feedback(self, capsule_id, trace_id):
        """Append associated failure; it disputes usefulness, not a proven cause."""
        self.lab._require('write')
        node = self.cg.get(capsule_id)
        if not node or (node['frontmatter'].get(META) or {}).get('kind') != 'capsule':
            raise ValueError('capsule missing or inaccessible')
        trace, p, rid = self._observation(trace_id)
        m = node['frontmatter'][META]
        if self._heads().get(m['slot'], {}).get('id') != capsule_id:
            raise ValueError('feedback must bind the current version')
        if capsule_id not in p.get('used_capsule_ids', []):
            raise ValueError('feedback has no recorded association with this capsule')
        if context_verdict(m['preconditions'], p['context'])['state'] != 'ACCEPT':
            raise ValueError('feedback context is outside this scope')
        if p['passed'] is not False:
            return {'status': 'unchanged', 'reason': 'success_is_not_automatic_generalization_or_restoration'}
        summary = {k: v for k, v in m.items() if k not in ['schema', 'kind', 'slot', 'version', 'previous_version']}
        summary.update(verification_status='disputed', feedback_trace_ids=m.get('feedback_trace_ids', []) + [trace_id],
                       receipt_ids=sorted(set(m['receipt_ids'] + [rid])))
        return self._append(m['slot'], summary, node['content'] + '\n\nAssociated failed task: ' + trace['task_id'] + '\nStatus: disputed; causal attribution remains unproven.', node)

    def rollback(self, capsule_id):
        """Disable through an appended version, preserving all original records."""
        self.lab._require('write')
        node = self.cg.get(capsule_id)
        if not node:
            raise ValueError('capsule missing or inaccessible')
        m = node['frontmatter'].get(META) or {}
        if m.get('kind') != 'capsule' or self._heads().get(m['slot'], {}).get('id') != capsule_id:
            raise ValueError('rollback must bind the current capsule version')
        summary = {k: v for k, v in m.items() if k not in ['schema', 'kind', 'slot', 'version', 'previous_version']}
        summary['verification_status'] = 'rolled_back'
        return self._append(m['slot'], summary, node['content'] + '\n\nOffline capsule disabled by appended rollback version.', node)

    def recall(self, query, facts, *, budget_tokens=1000, k=4, enforce_conditions=True):
        self.lab._require('read')
        from .mdcos import excerpt_tokens, est_tokens
        heads = {n['id']: n for n in self._heads().values()}
        base = self.cg.recall(query, context=facts, layer='knowledge', budget_tokens=budget_tokens,
                              k=k, judge=False, paths=('lexical',), max_item_tokens=450)
        accepted, rejected = [], []
        for p in base['pack']:
            node = heads.get(p['id'])
            if not node:
                rejected.append({'id': p['id'], 'reason': 'not_current_capsule_version'})
                continue
            m = node['frontmatter'][META]
            verdict = context_verdict(m['preconditions'], facts)
            if trust.is_expired(node['frontmatter']) or trust.state_of(node['frontmatter']) in ('doubted', 'rechecking', 'expired') or lifecycle.is_archived(node['frontmatter']):
                rejected.append({'id': p['id'], 'reason': 'capsule_expired_or_withdrawn'})
                continue
            if m['verification_status'] != 'source_supported_candidate':
                rejected.append({'id': p['id'], 'reason': m['verification_status']})
                continue
            if enforce_conditions and verdict['state'] != 'ACCEPT':
                rejected.append({'id': p['id'], **verdict})
                continue
            try:
                for tid in m['source_experience_ids']:
                    _, receipt, _ = self._observation(tid)
                    if receipt['passed'] is not True:
                        raise ValueError('source result no longer supports observation')
            except (ValueError, KeyError, TypeError):
                rejected.append({'id': p['id'], 'reason': 'source_evidence_unavailable_or_changed'})
                continue
            accepted.append({'id': p['id'], 'content': p['content'], 'preconditions': m['preconditions'],
                'source_experience_ids': m['source_experience_ids'], 'version': m['version'],
                'verification_status': m['verification_status'], 'persistent_verification_state': 'unverified'})
        text = excerpt_tokens(json.dumps(accepted, ensure_ascii=False, separators=(',', ':')), 650)
        ids = [x['id'] for x in accepted]
        self.last_recall_audit = {'base_API_result': base, 'accepted': accepted,
                                  'full_rejections': rejected, 'current_heads': list(heads)}
        result = {'text': text, 'retrieved_ids': [p['id'] for p in base['pack']],
                  'delivered_ids': [nid for nid in ids if json.dumps(nid) in text],
                  'rejected': rejected, 'estimated_tokens': est_tokens(text),
                  'insufficient_evidence': not ids, 'source': 'source-supported-capsule-recall',
                  'query': query, 'source_support_is_not_universal_knowledge_verification': True}
        # The entire public envelope, not just content, is budgeted.
        while est_tokens(json.dumps(result, ensure_ascii=False, separators=(',', ':'))) > budget_tokens:
            if result['rejected']:
                result['rejected'] = result['rejected'][:-1]
            elif len(result['text']) > 40:
                result['text'] = excerpt_tokens(result['text'], max(1, est_tokens(result['text']) - 40))
                result['delivered_ids'] = [nid for nid in ids if json.dumps(nid) in result['text']]
            else:
                raise ValueError('budget too small for evidence envelope')
            result['estimated_tokens'] = est_tokens(result['text'])
        return result
