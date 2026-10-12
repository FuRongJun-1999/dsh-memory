"""Additional counterexamples for multi-check evidence and condition identity."""
from copy import deepcopy
import unittest

from . import test_memory_rsi as base_cases


class AdversarialTests(base_cases.LabTests):
    def reflected(self, value):
        return self.lab.reflect(self.lab.record_experience(value))

    def test_a_later_failed_bound_check_withholds_the_action(self):
        value = base_cases.trace()
        later = deepcopy(value['events'][-1])
        later.update(id='v2', passed=False, text='second required assertion failed')
        value['events'].append(later)
        self.assertEqual(self.reflected(value)['candidates'], [])

    def test_multiple_successful_checks_form_one_candidate_with_all_evidence(self):
        value = base_cases.trace()
        later = deepcopy(value['events'][-1])
        later.update(id='v2', text='second required assertion passed')
        value['events'].append(later)
        candidates = self.reflected(value)['candidates']
        self.assertEqual(len(candidates), 1)
        self.assertEqual({ref.event_id for ref in candidates[0].evidence}, {'e', 'a', 'v', 'v2'})
        self.assertTrue(self.lab.verify(candidates[0])['ok'])

    def test_check_cannot_credit_an_action_after_a_replacement_for_same_error(self):
        value = base_cases.trace()
        value['events'].insert(2, {'id': 'a2', 'kind': 'action', 'text': 'a different repair',
                                   'error_id': 'e'})
        self.assertEqual(self.reflected(value)['candidates'], [])

    def test_failed_first_repair_does_not_disqualify_successful_retry(self):
        value = base_cases.trace(passed=False)
        value['events'].extend([
            {'id': 'a2', 'kind': 'action', 'text': 'the verified retry', 'error_id': 'e'},
            {'id': 'v2', 'kind': 'check', 'text': 'retry check', 'source': 'tool',
             'passed': True, 'action_id': 'a2', 'error_id': 'e'}])
        candidates = self.reflected(value)['candidates']
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].action, 'the verified retry')

    def test_an_action_for_another_error_does_not_replace_this_action(self):
        value = base_cases.trace()
        value['events'][2:2] = [
            {'id': 'e2', 'kind': 'error', 'text': 'another independent error'},
            {'id': 'a2', 'kind': 'action', 'text': 'handle the other error', 'error_id': 'e2'}]
        self.assertEqual(len(self.reflected(value)['candidates']), 1)

    def test_untrusted_failed_observation_does_not_override_tool_check(self):
        value = base_cases.trace()
        later = deepcopy(value['events'][-1])
        later.update(id='v2', source='assistant', passed=False)
        value['events'].append(later)
        self.assertEqual(len(self.reflected(value)['candidates']), 1)

    def test_condition_order_does_not_bypass_conflicting_action_gate(self):
        value = base_cases.trace()
        value['conditions'] = ['condition beta', 'condition alpha']
        one = self.reflected(value)['candidates'][0]
        self.lab.curate(one)
        other = base_cases.trace(action='a conflicting action', task='two')
        other['conditions'] = list(reversed(value['conditions']))
        two = self.reflected(other)['candidates'][0]
        self.assertEqual(one.slot, two.slot)
        self.assertEqual(self.lab.curate(two)['status'], 'deferred')

    def test_condition_whitespace_and_duplicates_are_canonical_but_raw_trace_stays_raw(self):
        value = base_cases.trace()
        value['conditions'] = [' condition beta ', 'condition alpha', 'condition beta']
        nid = self.lab.record_experience(value)
        candidate = self.lab.reflect(nid)['candidates'][0]
        self.assertEqual(candidate.conditions, ('condition alpha', 'condition beta'))
        import json
        self.assertEqual(json.loads(self.cg.get(nid)['content'])['conditions'], value['conditions'])

    def test_legacy_reflector_proposal_requires_review_in_same_context(self):
        _, candidate = self.candidate()
        self.cg.propose('legacy_lesson', 'old experimental lesson', layer='knowledge',
                        memory_rsi={'kind': 'lesson', 'slot': candidate.slot, 'key': candidate.key,
                                    'scope': candidate.scope, 'conditions': candidate.conditions,
                                    'evidence': [[e.trace_id, e.trace_hash, e.event_id] for e in candidate.evidence]})
        result = self.lab.curate(candidate)
        self.assertEqual(result['status'], 'deferred')
        self.assertEqual(result['reason'], 'legacy_reflector_requires_review')


if __name__ == '__main__':
    unittest.main(verbosity=2)
