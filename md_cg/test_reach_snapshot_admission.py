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



from . import reach

class Guards(RuntimeCase):
    def setUp(self):
        super().setUp()
        self.cg.add('a', 'needle retrieval')
        self.cg.add('b', 'different filler')
        self.cg.flush()
        self.idx = reach.ReachIndex(self.cg.root).build(self.cg)
        self.idx.save()
        self.path = Path(self.idx.path)
        self.valid = json.loads(self.path.read_text(encoding='utf-8'))
        self.addCleanup(reach._CACHE.clear)

    def malformed(self, field, value):
        data = dict(self.valid); data[field] = value
        self.path.write_text(json.dumps(data), encoding='utf-8')
        reach._CACHE.clear()

    def assert_recovers(self):
        error = None; rows = []
        with mock.patch.dict(os.environ, {'MDCG_REACH': '1'}):
            try:
                rows, _ = self.cg.search('needle', judge=False, record=False)
            except Exception as exc:
                error = type(exc).__name__ + ': ' + str(exc)
        self.assertIsNone(error, 'derived snapshot must not break real search')
        self.assertIn('a', {r[0]['id'] for r in rows})

    def test_bad_post_container(self):
        self.malformed('post', ['wrong']); self.assert_recovers()

    def test_bad_post_members(self):
        self.malformed('post', {'ne': 7}); self.assert_recovers()

    def test_string_posting_rejected(self):
        self.malformed('post', {'ne': 'knowledge/a.md'})
        self.assertFalse(reach.ReachIndex(self.cg.root).load())

    def test_bad_adjacency(self):
        self.malformed('adj', ['wrong'])
        self.assertFalse(reach.ReachIndex(self.cg.root).load())

    def test_bad_hashes(self):
        self.malformed('hashes', ['wrong'])
        self.assertFalse(reach.ReachIndex(self.cg.root).load())

    def test_bad_semantic(self):
        self.malformed('sem', 'knowledge/a.md')
        self.assertFalse(reach.ReachIndex(self.cg.root).load())

    def test_bad_built_at(self):
        self.malformed('built_at', 'not-a-number'); self.assert_recovers()

    def test_nonfinite_built_at(self):
        self.malformed('built_at', float('inf'))
        self.assertFalse(reach.ReachIndex(self.cg.root).load())

    def test_valid_snapshot_roundtrip(self):
        idx = reach.ReachIndex(self.cg.root)
        self.assertTrue(idx.load())
        self.assertEqual(idx.post, self.idx.post)
        self.assertEqual(idx.hashes, self.idx.hashes)

    def test_rejected_load_does_not_partially_replace_state(self):
        idx = reach.ReachIndex(self.cg.root)
        self.assertTrue(idx.load()); old = dict(idx.post)
        self.malformed('built_at', 'bad')
        data = json.loads(self.path.read_text(encoding='utf-8'))
        data['post'] = {'replacement': ['knowledge/replacement.md']}
        self.path.write_text(json.dumps(data), encoding='utf-8')
        try: result = idx.load()
        except Exception: result = 'escaped'
        self.assertIs(result, False)
        self.assertEqual(idx.post, old)

    def test_valid_wrong_fingerprint_is_rebuilt(self):
        self.malformed('fp', 'another-root-snapshot'); self.assert_recovers()

    def test_json_root_not_mapping(self):
        self.path.write_text('[]', encoding='utf-8')
        self.assertFalse(reach.ReachIndex(self.cg.root).load())

    def test_huge_numeric_timestamp_rejected(self):
        self.malformed('built_at', 10 ** 500)
        error = None
        try: accepted = reach.ReachIndex(self.cg.root).load()
        except Exception as exc: error = type(exc).__name__; accepted = True
        self.assertIsNone(error)
        self.assertFalse(accepted)


MUTATIONS = [{'name': 'R1 skip snapshot table shape validation', 'module': 'md_cg.reach', 'symbol': 'ReachIndex.load', 'targets': ['md_cg.reach:ReachIndex.load'], 'old': 'if not all(isinstance(x, dict) for x in (post, adj, hashes)):', 'new': 'if False:', 'test': 'Guards.test_bad_post_container'}, {'name': 'R2 accept semantic string as a path sequence', 'module': 'md_cg.reach', 'symbol': 'ReachIndex.load', 'targets': ['md_cg.reach:ReachIndex.load'], 'old': 'if not isinstance(sem, list) or not all(isinstance(p, str) for p in sem):', 'new': 'if False:', 'test': 'Guards.test_bad_semantic'}, {'name': 'R3 admit nonfinite snapshot age', 'module': 'md_cg.reach', 'symbol': 'ReachIndex.load', 'targets': ['md_cg.reach:ReachIndex.load'], 'old': 'finite_time = isinstance(built_at, (int, float)) and math.isfinite(built_at)', 'new': 'finite_time = isinstance(built_at, (int, float))', 'test': 'Guards.test_nonfinite_built_at'}, {'name': 'R4 partially replace postings before validation', 'module': 'md_cg.reach', 'symbol': 'ReachIndex.load', 'targets': ['md_cg.reach:ReachIndex.load'], 'old': 'if (not finite_time or isinstance(built_at, bool) or not isinstance(fp, str)):', 'new': 'self.post = {k: list(v) for k, v in post.items() if v}\n        if (not finite_time or isinstance(built_at, bool) or not isinstance(fp, str)):', 'test': 'Guards.test_rejected_load_does_not_partially_replace_state'}]

if __name__ == "__main__":
    raise SystemExit(run_guard(globals(), MUTATIONS))
