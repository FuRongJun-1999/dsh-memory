"""Lossless metadata and total-budget checks for the explicit compact mode."""
import hashlib
import json
import unittest

from .evidence_delivery import COMPACT_FIELDS, deliver
from .mdcos import est_tokens


class CompactTests(unittest.TestCase):
    def rows(self):
        fm = {'created_at': '2026-01-01', 'source': 'fixture document',
              'condition_space': {'all': ['project=Quartz', 'quoted\ncondition']},
              'verification_state': 'unverified', 'effective_from': '2025-12-01',
              'effective_until': '2026-02-01', 'believed_at': '2026-01-02'}
        return [({'id': f'fixture-{i}', 'content': 'Quartz value is ' + str(i) + '.\n' + 'padding ' * 100,
                  'frontmatter': fm}, 1.0 - i / 10, {'state': 'PASS'}, ['lexical'])
                for i in range(3)]

    def test_metadata_values_round_trip_with_one_shared_schema(self):
        result = deliver(self.rows()[:1], 'Quartz value', budget_tokens=500,
                         mode='query_metadata_compact')
        lines = result['text'].splitlines()
        columns = json.loads(lines[0].split('=', 1)[1])
        self.assertEqual(columns, list(COMPACT_FIELDS))
        decoded = dict(zip(columns, json.loads(lines[1])))
        self.assertEqual(decoded, result['records'][0]['metadata'])
        self.assertEqual(result['text'].count('memory_metadata_columns='), 1)

    def test_all_rendered_text_fits_and_source_spans_stay_exact(self):
        rows = self.rows()
        for budget in (0, 8, 40, 80, 120, 240, 500, 1200):
            result = deliver(rows, 'Quartz value', budget_tokens=budget,
                             mode='query_metadata_compact')
            self.assertLessEqual(est_tokens(result['text']), budget)
            self.assertEqual(result['tokens_used'], est_tokens(result['text']))
            self.assertEqual([r['id'] for r in result['records']],
                             [row[0]['id'] for row in rows[:len(result['records'])]])
            for record in result['records']:
                content = next(row[0]['content'] for row in rows if row[0]['id'] == record['id'])
                self.assertEqual(record['source_sha256'], hashlib.sha256(content.encode()).hexdigest())
                for span in record['spans']:
                    self.assertTrue(0 <= span['start'] <= span['end'] <= len(content))

    def test_empty_output_does_not_spend_budget_on_an_unused_schema(self):
        for rows in ([], self.rows()):
            result = deliver(rows, 'Quartz value', budget_tokens=0, mode='query_metadata_compact')
            self.assertEqual(result['text'], '')
            self.assertEqual(result['records'], [])
            self.assertEqual(result['tokens_used'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
