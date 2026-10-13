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

import math
import random
from . import stgidx, stg

class Guards(RuntimeCase):
    def make(self, count=2000):
        self.nodes = {f'n{i:05}': {'temporal': float(i % 29), 'session': str(i % 3), 'layer': 'knowledge'}
                      for i in reversed(range(count))}
        return stgidx.build({'nodes': self.nodes})

    def test_inclusive_range_ties(self):
        ix = self.make()
        for lo, hi in ((0, 0), (5, 5), (0, 28), (7, 14), (99, 100), (14, 7)):
            expected = sorted((e['temporal'], nid) for nid, e in self.nodes.items() if lo <= e['temporal'] <= hi)
            self.assertEqual(ix.range_ids(lo, hi), [nid for _, nid in expected])

    def test_random_updates_match_sorted_oracle(self):
        ix = self.make(90)
        rng = random.Random(1337)
        for step in range(1500):
            nid = f'n{rng.randrange(180):05}'
            if rng.randrange(3) == 0:
                ix.remove(nid)
                self.nodes.pop(nid, None)
            else:
                entry = {'temporal': float(rng.randrange(40)), 'session': str(rng.randrange(3)), 'layer': 'knowledge'}
                ix.add(nid, entry)
                self.nodes[nid] = entry
            self.assertFalse(ix.broken)
            expected = sorted((e['temporal'], n) for n, e in self.nodes.items())
            self.assertEqual(list(ix.by_time), expected, 'time-order projection equals independent sorted oracle')

    def test_empty_and_reinsert(self):
        ix = self.make(300)
        for nid in list(self.nodes):
            ix.remove(nid)
        self.assertEqual(list(ix.by_time), [])
        self.assertEqual(ix.range_ids(-math.inf, math.inf), [])
        ix.add('again', {'temporal': 7.0})
        self.assertFalse(ix.broken)
        self.assertEqual(ix.range_ids(7, 7), ['again'])

    def test_leaf_bounds_and_growth(self):
        ix = self.make(200)
        for i in range(200, 6000):
            ix.add(f'g{i:05}', {'temporal': float(6000 - i)})
        self.assertTrue(hasattr(ix.by_time, '_blocks'), 'timed updates must use bounded sorted blocks')
        self.assertFalse(ix.broken)
        blocks = ix.by_time
        self.assertTrue(all(0 < len(b) <= 2 * blocks._leaf for b in blocks._blocks))
        self.assertEqual(blocks._maxes, [b[-1] for b in blocks._blocks])
        self.assertEqual(len(blocks), sum(map(len, blocks._blocks)))
        self.assertLessEqual(blocks._leaf, 2 * max(32, math.isqrt(len(blocks))))

    def test_range_and_subsets_keep_physical_order(self):
        ix = self.make(500)
        ids, _ = ix.subset(session='1', time_range=(3, 8))
        expected = [nid for nid, e in self.nodes.items() if e['session'] == '1' and 3 <= e['temporal'] <= 8]
        self.assertEqual(ids, expected)
        self.assertEqual(stgidx.verify(ix, self.nodes), [])

    def test_nonfinite_and_untimed_still_partition(self):
        nodes = {'a': {'temporal': 5.0}, 'b': {}, 'c': {'temporal': float('nan')},
                 'd': {'temporal': float('inf')}}
        ix = stgidx.build({'nodes': nodes})
        self.assertEqual(stgidx.verify(ix, nodes), [])
        ids, _ = ix.subset(time_range=(5, 5))
        self.assertEqual(set(ids), {'a', 'c', 'd'})
        # The old incremental builder marks incomparable IDs as broken.
        # Bulk sorting must keep that recovery boundary instead of throwing.
        try:
            broken = stgidx.build({'nodes': {1: {'temporal': 1.0},
                                            'a': {'temporal': 1.0}}}).broken
        except TypeError:
            broken = False
        self.assertTrue(broken, 'bulk comparison failure must mark the index broken')

    def test_native_stg_index_matches_scan(self):
        for i in range(35):
            self.cg.add(f'stg{i:02}', 'time evidence ' + str(i), temporal=float(i + 1000),
                        session='scope' if i % 2 else 'other')
        options = dict(time_window=[1005, 1027], limit=100)
        with mock.patch.dict(os.environ, {'MDCG_STG_INDEX': '0'}):
            full = stg.anchors(self.cg, **options)
        with mock.patch.dict(os.environ, {'MDCG_STG_INDEX': '1'}):
            indexed = stg.anchors(self.cg, **options)
        self.assertEqual(full['items'], indexed['items'])

    def test_removing_absent_id_is_noop(self):
        ix = self.make(30)
        before = list(ix.by_time)
        ix.remove('absent')
        self.assertFalse(ix.broken)
        self.assertEqual(list(ix.by_time), before)

MUTATIONS = [
    mutation('lose bulk failure fallback', 'md_cg.stgidx', 'build',
             ['md_cg.stgidx:build'],
             '        ix.broken = True\n', '        pass\n',
             'test_nonfinite_and_untimed_still_partition'),
    mutation('exclude upper endpoint', 'md_cg.stgidx', '_TimeBlocks.range_ids',
             ['md_cg.stgidx:_TimeBlocks.range_ids'], 'if t > hi:', 'if t >= hi:',
             'test_inclusive_range_ties'),
    mutation('retain deleted time pair', 'md_cg.stgidx', 'StgIndex._unclassify',
             ['md_cg.stgidx:StgIndex._unclassify'], 'self.by_time.remove((t, nid))',
             'pass', 'test_empty_and_reinsert'),
    mutation('reverse update time', 'md_cg.stgidx', 'StgIndex._classify',
             ['md_cg.stgidx:StgIndex._classify'], 'self.by_time.add((t, nid))',
             'self.by_time.add((-t, nid))', 'test_random_updates_match_sorted_oracle'),
    mutation('drop time range filtering', 'md_cg.stgidx', 'StgIndex.range_ids',
             ['md_cg.stgidx:StgIndex.range_ids'], 'return self.by_time.range_ids(lo, hi)',
             'return [nid for t, nid in self.by_time]', 'test_inclusive_range_ties'),
]

def main(argv=None):
    return run_guard(globals(), MUTATIONS, argv)

if __name__ == "__main__":
    raise SystemExit(main())
