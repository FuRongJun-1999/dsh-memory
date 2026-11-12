"""CSRE regression cases on temporary sources, including the navigation entry.

No production corpus or model is required. Run with ``python -m
md_cg.test_csre_correctness``; temporary files follow the caller's TEMP root.
"""
import contextlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

try:
    import numpy as np
except Exception as exc:
    print('SKIP: CSRE correctness requires NumPy (' + type(exc).__name__ + ')')
    raise SystemExit(2)

WISDOM = Path(__file__).resolve().parent / 'whitebox_kb' / 'wisdom'
if str(WISDOM) not in sys.path:
    sys.path.insert(0, str(WISDOM))
from csre import Csre
import navigate
import md_access


def card(name='Alpha', condition='问测试条件甲', negatives=(), domain='domain-a'):
    return {'name': name, 'domain': domain,
            'comment': {'生效条件': [condition], '不适用条件': list(negatives)}}


class CsreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='csre-correctness-')
        self.base = Path(self.temp.name)
        self.db = self.base / 'source.db'
        self.index = self.base / 'index.npz'
        self.env = patch.dict(os.environ, {'WB_MD_DIRECT': '0',
                                          'WB_MD_ROOT': str(self.base / 'absent-md')})
        self.env.start()
        with contextlib.closing(sqlite3.connect(self.db)) as db:
            db.execute('CREATE TABLE nodes(id TEXT PRIMARY KEY, content TEXT, '
                       'state_attributes TEXT, tags TEXT)')
            db.commit()
        self.put('blocked', card(negatives=['问生产环境']))
        self.put('safe', card(name='Beta'))
        self.engine = Csre(str(self.db), str(self.index))
        self.engine.build_index()

    def tearDown(self):
        navigate._CSRE_CACHE.pop(str(self.db), None)
        md_access._CONN_CACHE.clear()
        self.env.stop()
        self.temp.cleanup()

    def put(self, nid, value, *, tags='knowledge_point'):
        with contextlib.closing(sqlite3.connect(self.db)) as db:
            db.execute('INSERT OR REPLACE INTO nodes VALUES(?,?,?,?)',
                       (nid, 'temporary fixture', json.dumps(value, ensure_ascii=False), tags))
            db.commit()

    def selected(self, question='生产环境 测试条件甲', **kwargs):
        return [r['node_id'] for r in self.engine.top_units_in_domain(
            'domain-a', question, **kwargs)]

    def test_negative_gate_filters_before_top_k_and_backfills(self):
        self.assertEqual(self.selected(limit=1), ['safe'])

    def test_explicit_context_terms_take_part_in_negative_gate(self):
        self.assertEqual(self.selected('测试条件甲', neg_terms=['生产环境']), ['safe'])

    def test_safe_context_and_disabled_gate_preserve_candidates(self):
        self.assertEqual(set(self.selected('测试条件甲')), {'blocked', 'safe'})
        self.assertEqual(set(self.selected(neg_gate=0)), {'blocked', 'safe'})
        self.assertEqual(set(self.selected(neg_gate=2)), {'blocked', 'safe'})

    def test_nonpositive_limit_never_returns_rows(self):
        self.assertEqual(self.selected(limit=0), [])
        self.assertEqual(self.selected(limit=-1), [])

    def test_empty_or_nonstring_negative_conditions_do_not_reject(self):
        self.assertEqual(Csre.negative_hit({'不适用条件': ['问', '', 3]}, '测试条件甲'), 0)
        self.assertEqual(Csre.negative_hit({'不适用条件': '问生产环境'}, '生产环境'), 1)

    def test_negated_environment_keeps_candidates_through_ranking(self):
        self.assertEqual(set(self.selected('测试条件甲 非生产环境')), {'blocked', 'safe'})
        self.assertEqual(self.selected('测试条件甲 生产环境'), ['safe'])

    def test_identifier_boundary_survives_index_reload(self):
        self.put('blocked', card(negatives=['问prod']))
        self.engine.build_index()
        self.engine.save_index()
        reloaded = Csre(str(self.db), str(self.index))
        safe = reloaded.top_units_in_domain('domain-a', '测试条件甲 product')
        blocked = reloaded.top_units_in_domain('domain-a', '测试条件甲 prod')
        self.assertEqual({row['node_id'] for row in safe}, {'blocked', 'safe'})
        self.assertEqual([row['node_id'] for row in blocked], ['safe'])

    def test_index_round_trip_retains_negative_gate_without_pickle(self):
        self.engine.save_index()
        with np.load(self.index, allow_pickle=False) as data:
            for name in data.files:
                data[name]  # an object array would fail here
        other = Csre(str(self.db), str(self.index))
        self.assertTrue(other.ensure_loaded())
        self.assertEqual([r['node_id'] for r in other.top_units_in_domain(
            'domain-a', '生产环境 测试条件甲', limit=1)], ['safe'])

    def test_legacy_unbound_index_is_rejected_without_writes(self):
        np.savez_compressed(self.index, vectors=self.engine.matrix,
                            unit_ids=self.engine.unit_ids, names=self.engine.unit_names,
                            domains=self.engine.unit_domains, vectors_vocab=self.engine.vocab)
        before = self.index.read_bytes()
        other = Csre(str(self.db), str(self.index))
        self.assertFalse(other.ensure_loaded())
        self.assertEqual(other.index_info()['state'], 'legacy_index')
        self.assertIsNone(other.matrix)
        self.assertEqual(before, self.index.read_bytes())

    def test_changed_content_invalidates_new_and_already_loaded_engines(self):
        self.engine.save_index()
        warm = Csre(str(self.db), str(self.index))
        self.assertTrue(warm.ensure_loaded())
        self.put('blocked', card(condition='问更新条件乙'))
        for engine in (self.engine, warm, Csre(str(self.db), str(self.index))):
            self.assertFalse(engine.ensure_loaded())
            self.assertEqual(engine.index_info()['state'], 'stale_index')
            self.assertEqual(engine.rank_domains('测试条件甲'), [])

    def test_wal_commit_is_detected_without_relying_on_database_mtime(self):
        with contextlib.closing(sqlite3.connect(self.db)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            self.engine.build_index()
            self.engine.save_index()
            writer.execute('UPDATE nodes SET state_attributes=? WHERE id=?',
                           (json.dumps(card(condition='问更新条件乙'), ensure_ascii=False), 'blocked'))
            writer.commit()
            self.assertFalse(self.engine.ensure_loaded())
            self.assertEqual(self.engine.index_info()['state'], 'stale_index')

    def test_identical_rows_from_another_database_are_not_accepted(self):
        self.engine.save_index()
        copy = self.base / 'other.db'
        copy.write_bytes(self.db.read_bytes())
        other = Csre(str(copy), str(self.index))
        self.assertFalse(other.ensure_loaded())
        self.assertEqual(other.index_info()['state'], 'source_mismatch')

    def test_schema_change_invalidates_index(self):
        self.engine.save_index()
        with contextlib.closing(sqlite3.connect(self.db)) as db:
            db.execute('ALTER TABLE nodes ADD COLUMN extra TEXT')
            db.commit()
        self.assertFalse(self.engine.ensure_loaded())
        self.assertEqual(self.engine.index_info()['state'], 'stale_index')

    def test_deletion_and_negative_condition_edits_invalidate_index(self):
        self.engine.save_index()
        self.put('blocked', card(negatives=['问另一环境']))
        self.assertFalse(self.engine.ensure_loaded())
        self.engine.build_index()
        self.engine.save_index()
        with contextlib.closing(sqlite3.connect(self.db)) as db:
            db.execute('DELETE FROM nodes WHERE id=?', ('safe',))
            db.commit()
        self.assertFalse(self.engine.ensure_loaded())

    def test_stale_index_cannot_be_saved_over_existing_file(self):
        self.engine.save_index()
        before = self.index.read_bytes()
        self.put('blocked', card(condition='问更新条件乙'))
        with self.assertRaises(ValueError):
            self.engine.save_index()
        self.assertEqual(before, self.index.read_bytes())

    def test_interrupted_save_keeps_previous_archive_and_cleans_own_temporary_file(self):
        self.engine.save_index()
        before = self.index.read_bytes()
        with patch('csre.np.savez_compressed', side_effect=OSError('simulated write failure')):
            with self.assertRaises(OSError):
                self.engine.save_index()
        self.assertEqual(before, self.index.read_bytes())
        self.assertEqual(list(self.base.glob('.csre-*.npz')), [])

    def test_empty_vocabulary_round_trip_has_consistent_dimensions(self):
        with contextlib.closing(sqlite3.connect(self.db)) as db:
            db.execute('UPDATE nodes SET state_attributes=?', ('{}',))
            db.commit()
        self.engine.build_index()
        self.engine.save_index()
        other = Csre(str(self.db), str(self.index))
        self.assertTrue(other.ensure_loaded())
        self.assertEqual(other.rank_domains('测试条件甲'), [])

    def test_missing_database_is_not_created(self):
        self.engine.save_index()
        missing = self.base / 'does-not-exist.db'
        other = Csre(str(missing), str(self.index))
        self.assertFalse(other.ensure_loaded())
        self.assertEqual(other.index_info()['state'], 'source_unavailable')
        self.assertFalse(missing.exists())

    def test_corrupt_archive_fails_closed_and_rebuild_recovers(self):
        self.index.write_bytes(b'not an npz file')
        other = Csre(str(self.db), str(self.index))
        self.assertFalse(other.ensure_loaded())
        self.assertEqual(other.index_info()['state'], 'invalid_index')
        other.build_index()
        other.save_index()
        self.assertTrue(other.ensure_loaded())

    def test_invalid_shape_and_nonfinite_vectors_are_rejected(self):
        self.engine.save_index()
        with np.load(self.index, allow_pickle=False) as data:
            fields = {name: data[name] for name in data.files}
        for vectors in (np.ones((1, 1)), np.full_like(fields['vectors'], np.nan)):
            np.savez_compressed(self.index, **dict(fields, vectors=vectors))
            other = Csre(str(self.db), str(self.index))
            self.assertFalse(other.ensure_loaded())
            self.assertEqual(other.index_info()['state'], 'invalid_index')

    def test_navigation_rechecks_cached_engine_and_recovers_after_explicit_rebuild(self):
        self.engine.save_index()
        navigate._CSRE_CACHE[str(self.db)] = self.engine
        dex = type('Dex', (), {'db_path': str(self.db)})()
        self.assertEqual(navigate._l1_domain_prior(dex, '测试条件甲'), 'domain-a')
        self.put('blocked', card(condition='问更新条件乙', domain='domain-b'))
        self.assertIsNone(navigate._l1_domain_prior(dex, '更新条件乙'))
        rebuild = Csre(str(self.db), str(self.index))
        rebuild.build_index()
        rebuild.save_index()
        self.assertEqual(navigate._l1_domain_prior(dex, '更新条件乙'), 'domain-b')

    def test_md_direct_source_is_refreshed_without_manual_reload(self):
        root = self.base / 'md-source'
        node = root / 'knowledge' / 'node.md'
        node.parent.mkdir(parents=True)

        def write(value):
            fm = {'id': 'md-card', 'layer': 'knowledge', 'tags': ['knowledge_point'],
                  'state_attributes': value}
            node.write_text('---\n' + '\n'.join(
                key + ': ' + json.dumps(item, ensure_ascii=False) for key, item in fm.items())
                + '\n---\n\nMD source fixture\n', encoding='utf-8')

        write(card())
        with patch.dict(os.environ, {'WB_MD_DIRECT': '1', 'WB_MD_ROOT': str(root)}):
            self.engine.build_index()
            self.engine.save_index()
            write(card(condition='问更新条件乙'))
            self.assertFalse(self.engine.ensure_loaded())
            self.assertEqual(self.engine.index_info()['state'], 'stale_index')
            self.engine.build_index()
            self.assertIn('更新条件乙', self.engine.vocab)

            other_root = self.base / 'other-md-source'
            other_node = other_root / 'knowledge' / 'node.md'
            other_node.parent.mkdir(parents=True)
            other_node.write_bytes(node.read_bytes())
            self.engine.save_index()
            with patch.dict(os.environ, {'WB_MD_ROOT': str(other_root)}):
                self.assertFalse(self.engine.ensure_loaded())
                self.assertEqual(self.engine.index_info()['state'], 'source_mismatch')


class NegativeMeaningTests(unittest.TestCase):
    def test_ascii_identifier_boundaries(self):
        for query in ('product', 'nonproduction', 'prod_backup', 'xprod', 'prod7'):
            with self.subTest(query=query):
                self.assertEqual(Csre.negative_hit({'不适用条件': ['prod', 'production']}, query), 0)

    def test_explicit_local_negation(self):
        for query in ('非生产环境', '不是生产环境', '并非生产环境', '不在 生产环境',
                      'not production', 'not in production', 'non-production'):
            with self.subTest(query=query):
                self.assertEqual(Csre.negative_hit({'不适用条件': ['问生产环境', 'production']}, query), 0)

    def test_positive_mentions_still_count(self):
        for term, query in (('prod', 'on prod'), ('production', 'production deployment'),
                            ('生产环境', '部署生产环境')):
            self.assertEqual(Csre.negative_hit({'不适用条件': [term]}, query), 1)

    def test_a_positive_occurrence_survives_an_earlier_negation(self):
        for term, query in (('production', 'not production; later production'),
                            ('生产环境', '非生产环境与生产环境对照')):
            self.assertEqual(Csre.negative_hit({'不适用条件': [term]}, query), 1)

    def test_punctuation_remains_literal(self):
        self.assertEqual(Csre.negative_hit({'不适用条件': ['C++', 'a.b']}, 'C++ a.b'), 2)
        self.assertEqual(Csre.negative_hit({'不适用条件': ['a.b']}, 'axb'), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
