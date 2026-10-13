"""Run the same source/gating regressions against the opt-in SQLite session."""
import contextlib
import os
import sqlite3
import unittest
from unittest.mock import patch

from . import test_csre_correctness as base_cases
from .whitebox_kb.wisdom.csre_session import CsreSession


class SessionTests(base_cases.CsreTests):
    def setUp(self):
        super().setUp()
        self.engine = CsreSession(str(self.db), str(self.index))
        self.engine.__enter__()
        self.engine.build_index()

    def tearDown(self):
        self.engine.close()
        super().tearDown()

    def test_warm_checks_reuse_snapshot_but_commit_triggers_full_check(self):
        scans = self.engine.full_source_reads
        for _ in range(5):
            self.assertTrue(self.engine.ensure_loaded())
        self.assertEqual(self.engine.full_source_reads, scans)
        self.assertGreaterEqual(self.engine.source_cache_hits, 5)
        self.put('blocked', base_cases.card(condition='问更新条件乙'))
        self.assertFalse(self.engine.ensure_loaded())
        self.assertGreater(self.engine.full_source_reads, scans)

    def test_restored_mtime_does_not_hide_sqlite_commit(self):
        before = self.db.stat()
        self.engine.save_index()
        self.put('blocked', base_cases.card(condition='问更新条件乙'))
        os.utime(self.db, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertFalse(self.engine.ensure_loaded())

    def test_same_content_commit_is_safe_and_updates_observer_token(self):
        scans = self.engine.full_source_reads
        with contextlib.closing(sqlite3.connect(self.db)) as writer:
            writer.execute('CREATE TABLE irrelevant(value TEXT)')
            writer.commit()
        self.assertTrue(self.engine.ensure_loaded())
        self.assertEqual(self.engine.full_source_reads, scans + 1)
        self.assertTrue(self.engine.ensure_loaded())
        self.assertEqual(self.engine.full_source_reads, scans + 1)

    def test_observer_is_readonly_and_context_exit_closes_it(self):
        with self.assertRaises(sqlite3.OperationalError):
            self.engine._observer.execute('DELETE FROM nodes')
        self.engine.save_index()
        with CsreSession(str(self.db), str(self.index)) as other:
            self.assertTrue(other.ensure_loaded())
            connection = other._observer
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute('SELECT 1')
        self.assertFalse(other.ensure_loaded())

    def test_unstable_source_fails_closed_after_bounded_retries(self):
        self.engine._snapshot_token = None
        with patch.object(self.engine, '_version', side_effect=range(6)):
            self.assertFalse(self.engine.ensure_loaded())
        self.assertEqual(self.engine.index_info()['state'], 'source_unavailable')


if __name__ == '__main__':
    unittest.main(verbosity=2)
