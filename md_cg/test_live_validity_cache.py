"""Runtime guard with actual temporary graphs and named mutation assertions."""
"""Shared runtime/mutation harness. No source file is modified by mutations."""
import argparse
from contextlib import ExitStack
import hashlib
import importlib
import io
import json
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

def _tests(module, name=None):
    loader = unittest.TestLoader()
    suite = (loader.loadTestsFromName(name, module) if name
             else loader.loadTestsFromModule(module))
    log = io.StringIO()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    failed = {t.id().split(' (')[0] for t, _ in result.failures + result.errors}
    return result, {'tests': result.testsRun, 'passed': result.testsRun - len(failed) - len(result.skipped),
                    'failed': len(failed), 'errors': len(result.errors),
                    'skipped': len(result.skipped), 'log': log.getvalue()}

def run_guard(namespace, mutations, argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--mutate', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    module = types.ModuleType(namespace['__name__'])
    module.__dict__.update(namespace)
    _, baseline = _tests(module)
    if baseline['tests'] == 0:
        baseline['errors'] += 1
        baseline['failed'] += 1
        baseline['log'] += '\nERROR: no tests were discovered\n'
    report = baseline
    if args.mutate and baseline['failed'] == baseline['errors'] == baseline['skipped'] == 0:
        records = []
        for spec in mutations:
            original = importlib.import_module(spec['module'])
            path = Path(original.__file__)
            before = path.read_bytes()
            source = before.decode('utf-8-sig').replace('\r\n', '\n')
            record = {'name': spec['name'], 'test': spec['test'], 'killed': False}
            try:
                assert source.count(spec['old']) == 1, 'mutation anchor must occur once'
                source = source.replace(spec['old'], spec['new'], 1)
                name = spec['module'] + '._runtime_mutant'
                mutant = types.ModuleType(name)
                mutant.__package__ = original.__package__
                mutant.__file__ = str(path)
                with mock.patch.dict(sys.modules, {name: mutant}):
                    exec(compile(source, str(path) + '.mutant', 'exec'), mutant.__dict__)
                    value = mutant
                    for part in spec['symbol'].split('.'):
                        value = getattr(value, part)
                    with ExitStack() as stack:
                        for target in spec['targets']:
                            modname, attrpath = target.split(':')
                            owner = importlib.import_module(modname)
                            parts = attrpath.split('.')
                            for part in parts[:-1]:
                                owner = getattr(owner, part)
                            stack.enter_context(mock.patch.object(owner, parts[-1], value))
                        result, summary = _tests(module, spec['test'])
                    record.update(summary)
                    record['killed'] = (result.testsRun == 1 and len(result.failures) >= 1
                                        and not result.errors and not result.skipped)
            except Exception as exc:
                record['harness_error'] = type(exc).__name__ + ': ' + str(exc)
            record['source_untouched'] = path.read_bytes() == before
            record['source_sha256'] = hashlib.sha256(before).hexdigest()
            record['killed'] &= record['source_untouched']
            records.append(record)
        _, restored = _tests(module)
        report = {'baseline': baseline, 'mutants': records, 'restored': restored,
                  'tests': len(records), 'passed': sum(r['killed'] for r in records),
                  'failed': sum(not r['killed'] for r in records),
                  'errors': sum('harness_error' in r or r.get('errors', 0) > 0 for r in records),
                  'skipped': sum(r.get('skipped', 0) for r in records),
                  'source_untouched': all(r['source_untouched'] for r in records)}
        report['failed'] += restored['failed'] + restored['errors'] + restored['skipped']
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if report['failed'] or report['errors']:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"通过 {report['passed']} / 失败 {report['failed']} / errors {report['errors']} / SKIP {report['skipped']}")
    return int(bool(report['failed'] or report['errors'] or report['skipped']))

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from . import mdcos, mdcg

class RuntimeCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='memory_runtime_')
        self.addCleanup(self.temp.cleanup)
        self.env = mock.patch.dict(os.environ, {
            'MDCG_MASTER_KEY': 'ab' * 32, 'MDCG_HOTCACHE': '0',
            'MDCG_RRF_CANDIDATES': '0', 'MDCG_RANK_CREDIBILITY': '0',
            'MDCG_RETRIEVAL_PIPELINE': '0', 'MDCG_UNIFY_QUERY': '0',
            'MDCG_EN_ATOMS': '0', 'MDCG_SEMANTIC': '0',
            'MDCG_SUSTAIN': '0', 'MDCG_SESSION': '', 'DSH_SESSION_ID': '',
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.cg = mdcos.MdCGOS(self.temp.name)
        self.addCleanup(self.cg.close)

def mutation(name, module, symbol, targets, old, new, test):
    return dict(name=name, module=module, symbol=symbol, targets=targets,
                old=old, new=new, test='Guards.' + test)



from . import hotcache, bm25, security

class Guards(RuntimeCase):
    NOW = 1792022400.0

    def setUp(self):
        super().setUp()
        hotcache.attach(self.cg)
        self.cg.add('a_expiring', 'needle', importance=0.9, valid_until=self.NOW + 2)
        self.cg.add('z_stable', 'needle', importance=0.4)

    def query(self, **kw):
        options = dict(paths=('lexical',), judge=False, record=False, validity=True, k=1)
        options.update(kw)
        return self.cg.search_rrf('needle', **options)

    def test_expiry_replaces_cached_top_one(self):
        with mock.patch('time.time', return_value=self.NOW):
            self.assertEqual(self.query()[0][0][0]['id'], 'a_expiring')
        with mock.patch('time.time', return_value=self.NOW + 3):
            self.assertEqual([r[0]['id'] for r in self.query()[0]], ['z_stable'])

    def test_validity_queries_do_not_read_or_write_result_cache(self):
        with mock.patch('time.time', return_value=self.NOW):
            self.query(); _, meta = self.query()
        self.assertFalse(meta.get('cached', False))
        self.assertEqual(hotcache.get(self.cg).stats()['query_cache_size'], 0)

    def test_clock_rollback_can_restore_not_expired_candidate(self):
        with mock.patch('time.time', return_value=self.NOW + 3):
            self.assertEqual([r[0]['id'] for r in self.query()[0]], ['z_stable'])
        with mock.patch('time.time', return_value=self.NOW):
            self.assertEqual([r[0]['id'] for r in self.query()[0]], ['a_expiring'])

    def test_bm25_pool_and_result_both_refresh(self):
        with mock.patch('time.time', return_value=self.NOW):
            self.query(paths=('bm25',))
        with mock.patch('time.time', return_value=self.NOW + 3):
            rows, meta = self.query(paths=('bm25',))
        self.assertEqual([r[0]['id'] for r in rows], ['z_stable'])
        self.assertFalse(meta.get('cached', False))

    def test_default_queries_still_cache(self):
        with mock.patch('time.time', return_value=self.NOW):
            self.query(validity=None)
            rows, meta = self.query(validity=None)
        self.assertTrue(meta.get('cached'))
        self.assertEqual(rows[0][0]['id'], 'a_expiring')

    def test_false_validity_keeps_cache(self):
        with mock.patch('time.time', return_value=self.NOW):
            self.query(validity=False)
            self.assertTrue(self.query(validity=False)[1].get('cached'))

    def test_not_yet_remains_in_pool(self):
        self.cg.add('future', 'needle', valid_from=self.NOW + 10000)
        with mock.patch('time.time', return_value=self.NOW):
            rows, _ = self.query(k=10)
        self.assertIn('future', {r[0]['id'] for r in rows})

    def test_equal_deadline_is_still_active(self):
        with mock.patch('time.time', return_value=self.NOW + 2):
            self.assertEqual(self.query()[0][0][0]['id'], 'a_expiring')

    def test_secure_wrapper_refills_after_expiration(self):
        # Same trusted principal, no identity mutation: only the clock advances.
        principal = security.Principal(tenant='default', actor='validity_guard',
                                       role='designer', clearance='secret', session='validity')
        cg = mdcos.MdCGSecure(self.temp.name, principal=principal)
        self.addCleanup(cg.close)
        self.cg.flush(); cg.rebuild_index(); hotcache.attach(cg)
        args = dict(paths=('lexical',), judge=False, record=False, validity=True, k=1)
        with mock.patch('time.time', return_value=self.NOW):
            cg.search_rrf('needle', **args)
        with mock.patch('time.time', return_value=self.NOW + 3):
            rows, _ = cg.search_rrf('needle', **args)
        self.assertEqual([r[0]['id'] for r in rows], ['z_stable'])

MUTATIONS = [{'name': 'V1 cache clock dependent results again', 'module': 'md_cg.mdcos', 'symbol': 'MdCGOS.search_rrf', 'targets': ['md_cg.mdcos:MdCGOS.search_rrf'], 'old': '_time_on = bool(validity) or any(', 'new': '_time_on = any(', 'test': 'Guards.test_expiry_replaces_cached_top_one'}, {'name': 'V2 bypass reads but keep writing result cache', 'module': 'md_cg.mdcos', 'symbol': 'MdCGOS.search_rrf', 'targets': ['md_cg.mdcos:MdCGOS.search_rrf'], 'old': 'if hc is not None and results and not _time_on and not _bypass:', 'new': 'if hc is not None and results and not _bypass:', 'test': 'Guards.test_validity_queries_do_not_read_or_write_result_cache'}, {'name': 'V3 disable cache for ordinary queries', 'module': 'md_cg.mdcos', 'symbol': 'MdCGOS.search_rrf', 'targets': ['md_cg.mdcos:MdCGOS.search_rrf'], 'old': '_bypass = query_expand is not None', 'new': '_bypass = True', 'test': 'Guards.test_default_queries_still_cache'}]

if __name__ == "__main__":
    raise SystemExit(run_guard(globals(), MUTATIONS))
