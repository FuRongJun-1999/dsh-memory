"""Runtime regressions for the offline lab, evidence boundaries and delivery."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from .evidence_delivery import deliver, query_excerpt
from .mdcos import MdCGOS, MdCGSecure, est_tokens
from .memory_rsi import MemoryRSILab, create_sandbox, recommend_strategy
from .security import Principal, AccessDenied
from .bench_memory_rsi import paired_interval


def trace(*, passed=True, action='use an absolute config path', task='one'):
    return {'task_id': task, 'scope': 'Windows config loader',
            'conditions': ['working directory differs from project root'],
            'events': [
                {'id': 'e', 'kind': 'error', 'text': 'FileNotFoundError config.yaml'},
                {'id': 'a', 'kind': 'action', 'text': action, 'error_id': 'e'},
                {'id': 'v', 'kind': 'check', 'text': 'config loader assertion result',
                 'action_id': 'a', 'error_id': 'e', 'source': 'tool', 'passed': passed}]}


class LabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='memory-rsi-test-')
        self.base = Path(self.temp.name) / 'lab'
        self.root = create_sandbox(self.base)
        self.cg = MdCGOS(str(self.root))
        self.lab = MemoryRSILab(self.cg, self.base, enabled=True)

    def tearDown(self):
        self.cg.close()
        self.temp.cleanup()

    def candidate(self, value=None):
        nid = self.lab.record_experience(value or trace())
        return nid, self.lab.reflect(nid)['candidates'][0]

    def test_disabled_and_existing_root_refused(self):
        with self.assertRaises(ValueError):
            MemoryRSILab(self.cg, self.base)
        with self.assertRaises(FileExistsError):
            create_sandbox(self.base)
        other = MdCGOS(str(Path(self.temp.name) / 'other'))
        try:
            with self.assertRaises(ValueError):
                MemoryRSILab(other, self.base, enabled=True)
        finally:
            other.close()

    def test_trace_is_idempotent_and_not_knowledge(self):
        first = self.lab.record_experience(trace())
        self.assertEqual(first, self.lab.record_experience(trace()))
        node = self.cg.get(first)
        self.assertEqual(node['frontmatter']['layer'], 'contextual')
        self.assertEqual(node['frontmatter']['role'], 'tool-output')
        self.assertEqual(self.cg.search_rrf('FileNotFoundError config.yaml')[0], [])
        self.assertEqual(json.loads(node['content'])['events'], trace()['events'])

    def test_failed_or_string_true_never_yields_lesson(self):
        for passed in (False, 'true', 1, None):
            nid = self.lab.record_experience(trace(passed=passed))
            self.assertEqual(self.lab.reflect(nid)['candidates'], [])
        self.assertEqual(self.cg.review_list(), [])

    def test_unrelated_and_out_of_order_checks_withheld(self):
        value = trace()
        value['events'][-1]['action_id'] = 'absent'
        nid = self.lab.record_experience(value)
        self.assertEqual(self.lab.reflect(nid)['candidates'], [])
        value = trace()
        value['events'] = list(reversed(value['events']))
        nid = self.lab.record_experience(value)
        self.assertEqual(self.lab.reflect(nid)['candidates'], [])

    def test_untrusted_observation_and_missing_evidence_rejected(self):
        value = trace()
        value['events'][-1]['source'] = 'assistant'
        nid = self.lab.record_experience(value)
        self.assertEqual(self.lab.reflect(nid)['candidates'], [])
        _, candidate = self.candidate()
        verdict = self.lab.curate(replace(candidate, evidence=()))
        self.assertEqual(verdict['status'], 'rejected')

    def test_generalization_and_confidence_cannot_inherit_evidence(self):
        _, candidate = self.candidate()
        for changed in (replace(candidate, scope='all operating systems'),
                        replace(candidate, action='delete all config files'),
                        replace(candidate, confidence=1.0),
                        replace(candidate, conditions=('always',))):
            self.assertFalse(self.lab.verify(changed)['ok'])

    def test_changed_source_is_rejected(self):
        nid, candidate = self.candidate()
        old = self.cg.get(nid)
        self.cg.add(nid, old['content'].replace('absolute', 'relative'), layer='contextual',
                    memory_rsi=old['frontmatter']['memory_rsi'])
        self.assertFalse(self.lab.verify(candidate)['ok'])
        self.assertEqual(self.lab.curate(candidate)['status'], 'rejected')

    def test_proposal_only_duplicate_and_audited_rollback(self):
        nid, candidate = self.candidate()
        result = self.lab.curate(candidate)
        self.assertEqual(result['status'], 'proposed')
        self.assertIsNone(self.cg.get(result['node_id']))
        self.assertFalse(result['committed'])
        item = self.cg.review_list()[0]
        self.assertEqual(item['extra']['verification_state'], 'unverified')
        self.assertTrue(item['verify_hash'])
        self.assertEqual(self.lab.curate(candidate)['status'], 'duplicate')
        self.assertEqual(len(self.cg.review_list()), 1)
        decision = self.lab.rollback(result['pid'])
        self.assertTrue(decision['ok'])
        self.assertEqual(self.cg.review_list(), [])
        self.assertIsNotNone(self.cg.get(nid))
        self.assertIsNone(self.cg.get(result['node_id']))
        self.assertIn('rollback', Path(self.cg.decisions_log).read_text(encoding='utf-8'))

    def test_repeated_experiences_merge_without_erasing_versions(self):
        _, first = self.candidate()
        one = self.lab.curate(first)
        _, second = self.candidate(trace(task='two'))
        two = self.lab.curate(second)
        self.assertEqual(two['merged_observations'], 2)
        self.assertNotEqual(one['pid'], two['pid'])
        pending = self.cg.review_list()
        self.assertEqual(len(pending), 2)
        old = next(p for p in pending if p['pid'] == one['pid'])
        new = next(p for p in pending if p['pid'] == two['pid'])
        self.assertEqual(len(old['extra']['derived_from']), 1)
        self.assertEqual(len(new['extra']['derived_from']), 2)

    def test_existing_review_accept_retains_evidence_without_upgrading_truth(self):
        nid, candidate = self.candidate()
        proposed = self.lab.curate(candidate)
        accepted = self.cg.review_decide(proposed['pid'], 'accept',
            reason='explicit isolated test review', redteam={'verdict': 'pass'})
        self.assertTrue(accepted['ok'])
        lesson = self.cg.get(proposed['node_id'])
        self.assertEqual(lesson['frontmatter']['derived_from'], [nid])
        self.assertEqual(lesson['frontmatter']['verification_state'], 'unverified')
        self.assertEqual(self.lab.curate(candidate)['status'], 'duplicate')

    def test_conflicting_action_is_deferred_with_original_evidence(self):
        nid, first = self.candidate()
        self.lab.curate(first)
        _, second = self.candidate(trace(task='two', action='ignore the missing config'))
        result = self.lab.curate(second)
        self.assertEqual(result['status'], 'deferred')
        self.assertTrue(result['related'])
        self.assertEqual(len(self.cg.review_list()), 1)
        self.assertIsNotNone(self.cg.get(nid))

    def test_secure_guest_cannot_write_through_lab(self):
        self.cg.close()
        self.cg = MdCGSecure(str(self.root), principal=Principal(
            role='guest', can_write=False, ops_allow=['read', 'route', 'info']))
        lab = MemoryRSILab(self.cg, self.base, enabled=True)
        with self.assertRaises(AccessDenied):
            lab.record_experience(trace())

    def test_resource_limits_are_explicit(self):
        value = trace()
        value['events'][0]['text'] = 'x' * 70000
        with self.assertRaises(ValueError):
            self.lab.record_experience(value)
        row = {'name': 'a', 'split': 'holdout', 'budget_ok': True,
               'unsafe_accepts': 0, 'evidence_rate': 1, 'p95_ms': 1}
        with self.assertRaises(ValueError):
            recommend_strategy([row])
        row['split'] = 'validation'
        self.assertFalse(recommend_strategy([row])['accepted'])
        with self.assertRaises(ValueError):
            recommend_strategy([row] * 7)


class DeliveryTests(unittest.TestCase):
    def test_timing_repeats_do_not_inflate_confidence_sample_size(self):
        left = [{'qid': str(i), 'gold_count': 1, 'complete': False} for i in range(8)]
        right = [{**r, 'complete': i % 2 == 0} for i, r in enumerate(left)]
        once = paired_interval(left, right)
        repeated = paired_interval(left * 3, list(reversed(right * 3)))
        self.assertEqual(once, repeated)
        self.assertEqual(once['unique_labelled_queries'], 8)
        with self.assertRaises(ValueError):
            paired_interval(left, right[:-1])

    def test_tail_selection_has_exact_source_offsets(self):
        content = ('unrelated background material\n' * 40
                   + 'Quartz recovery action: restore the configuration backup.\n')
        text, spans = query_excerpt(content, 'Quartz recovery action', 40)
        self.assertIn('restore the configuration backup', text)
        for span in spans:
            self.assertIn(content[span['start']:span['end']], text)
        self.assertLessEqual(est_tokens(text), 40)

    def test_rendered_budget_counts_metadata_and_preserves_time_semantics(self):
        node = {'id': 'node-one', 'content': 'Quartz recovery: restore backup.\n' * 20,
                'frontmatter': {'created_at': '2026-01-01', 'effective_from': '2025-12-01',
                                'source': 'test-trace', 'condition_space': {'all': ['Quartz']}}}
        row = (node, 1.0, {'state': 'PASS'}, ['lexical'])
        for budget in (0, 10, 80, 140, 240):
            packed = deliver([row] * 3, 'Quartz recovery', budget_tokens=budget)
            self.assertLessEqual(est_tokens(packed['text']), budget)
        packed = deliver([row], 'Quartz recovery', budget_tokens=240)
        self.assertIn('2025-12-01', packed['text'])
        self.assertIn('2026-01-01', packed['text'])
        self.assertIn('node-one', packed['text'])
        self.assertEqual(packed['records'][0]['metadata']['verification_state'], 'unverified')


if __name__ == '__main__':
    unittest.main()
