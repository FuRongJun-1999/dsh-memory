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



from . import bm25

class Guards(RuntimeCase):
    def setUp(self):
        super().setUp()
        for i in range(96):
            self.cg.add('n%03d' % i, 'needle %d' % i)
        self.cg.flush()

    def query(self, **kw):
        options = dict(paths=('bm25',), judge=False, record=False, k=10)
        options.update(kw)
        return self.cg.search_rrf('needle', **options)

    def copies(self, fn):
        touched = []; original = bm25._PoolEntries.__init__
        def counted(obj, items, pool_key):
            touched.append(len(items)); original(obj, items, pool_key)
        with mock.patch.object(bm25._PoolEntries, '__init__', counted):
            result = fn()
        return result, sum(touched)

    def test_warm_query_has_no_full_pool_copy(self):
        before = self.query()[0]
        (after, meta), copied = self.copies(self.query)
        self.assertEqual([r[0]['id'] for r in after], [r[0]['id'] for r in before])
        self.assertEqual(copied, 0, 'hot internal retrieval must not copy all N candidate pointers')
        self.assertTrue(meta['bm25'].get('pool_reused'))

    def test_public_pool_copy_is_defensive(self):
        a = bm25.candidate_pool(self.cg)
        self.assertIsInstance(a, list)
        expected = list(a)
        a.clear()
        self.assertEqual(list(bm25.candidate_pool(self.cg)), expected)

    def test_first_public_pool_copy_is_defensive(self):
        self.cg._bm25_candidate_pool = None
        a = bm25.candidate_pool(self.cg)
        self.assertIsInstance(a, list)
        count = len(a); a.pop()
        self.assertEqual(len(bm25.candidate_pool(self.cg)), count)

    def test_internal_candidate_fn_avoids_initial_copies(self):
        _, copied = self.copies(self.query)
        self.assertEqual(copied, 0)

    def test_write_generation_still_refreshes_pool(self):
        self.query()
        self.cg.add('new', 'needle needle needle')
        rows, _ = self.query(k=50)
        self.assertIn('new', {r[0]['id'] for r in rows})

    def test_role_scope_does_not_reuse_other_pool(self):
        self.query()
        rows, meta = self.query(roles=('tool-output',))
        self.assertEqual(rows, [])

    def test_clock_dependent_pool_bypasses_still_work(self):
        self.cg.add('expired', 'needle needle', valid_until=1)
        rows, _ = self.query(validity=True, k=50)
        self.assertNotIn('expired', {r[0]['id'] for r in rows})

    def test_internal_wrapper_cannot_mutate_cached_container(self):
        self.query()
        entries = self.cg._bm25_index.entries
        self.assertFalse(hasattr(entries, 'append'))
        with self.assertRaises(TypeError):
            entries[0] = entries[-1]

MUTATIONS = [{'name': 'P1 copy the warm internal pool again', 'module': 'md_cg.mdcos', 'symbol': 'MdCGOS.search_rrf', 'targets': ['md_cg.mdcos:MdCGOS.search_rrf'], 'old': 'bm25.candidate_pool_view(self, **options)', 'new': 'bm25.candidate_pool(self, **options)', 'test': 'Guards.test_warm_query_has_no_full_pool_copy'}, {'name': 'P2 expose private view to public mutable callers', 'module': 'md_cg.bm25', 'symbol': 'candidate_pool', 'targets': ['md_cg.bm25:candidate_pool'], 'old': 'return _PoolEntries(entries, key) if key is not None else entries', 'new': 'return entries', 'test': 'Guards.test_public_pool_copy_is_defensive'}, {'name': 'P3 ignore pool write generation', 'module': 'md_cg.bm25', 'symbol': 'candidate_pool_view', 'targets': ['md_cg.bm25:candidate_pool_view'], 'old': 'key = (dirty.write_gen, dirty.broad_gen, access_key(cg),', 'new': 'key = (0, dirty.broad_gen, access_key(cg),', 'test': 'Guards.test_write_generation_still_refreshes_pool'}, {'name': 'P4 retain mutable list in internal search', 'module': 'md_cg.bm25', 'symbol': 'candidate_pool_view', 'targets': ['md_cg.bm25:candidate_pool_view'], 'old': 'entries = _PoolView(cg._candidates(**options), key)', 'new': 'entries = cg._candidates(**options)', 'test': 'Guards.test_internal_wrapper_cannot_mutate_cached_container'}]

if __name__ == "__main__":
    raise SystemExit(run_guard(globals(), MUTATIONS))
