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
    def native(self):
        for nid, tw in [('long', [100, 300]), ('left', [100, 205]),
                        ('point', [205, 205]), ('outside', [500, 600])]:
            self.cg.add(nid, 'memory '+nid, condition_space={'time_window': tw})

    def ids(self, flag):
        with mock.patch.dict(os.environ, {'MDCG_STG_INDEX': str(flag)}):
            r = stg.anchors(self.cg, time_window=[200, 210], limit=100)
        return [n['id'] for n in r['items']]

    def test_native_contains_and_overlap(self):
        self.native()
        self.assertEqual(self.ids(0), ['long', 'left', 'point'])
        self.assertEqual(self.ids(1), self.ids(0), 'indexed anchors must retain containing/overlapping memories')

    def test_random_intervals_match_exact_oracle(self):
        rng = random.Random(711)
        nodes = {f'n{i:03}': {'time_window': sorted([rng.randrange(1000), rng.randrange(1000)])}
                 for i in range(350)}
        ix = stgidx.build({'nodes': nodes})
        for lo, hi in ((100, 110), (500, 500), (1, 999), (990, 1000)):
            ids, _ = ix.subset(time_range=(lo, hi))
            expected = [nid for nid, e in nodes.items()
                        if stg.time_relation(tuple(e['time_window']), (lo, hi))
                        in ('during', 'contains', 'overlaps', 'equals')]
            actual = [nid for nid in ids if stg.time_relation(tuple(nodes[nid]['time_window']), (lo, hi))
                      in ('during', 'contains', 'overlaps', 'equals')]
            self.assertEqual(actual, expected, 'full scan and indexed overlap decisions must agree in physical order')

    def test_point_fast_path_inclusive(self):
        nodes = {str(i): {'temporal': i} for i in range(30)}
        ix = stgidx.build({'nodes': nodes})
        self.assertEqual(ix.subset(time_range=(10, 12))[0], ['10', '11', '12'])
        self.assertEqual(ix.subset(time_range=(12, 10))[0], [])

    def test_incremental_endpoint_replacement(self):
        nodes = {'a': {'time_window': [100, 300]}, 'b': {'temporal': 205}}
        ix = stgidx.build({'nodes': nodes})
        nodes['a'] = {'time_window': [400, 450]}
        ix.add('a', nodes['a'])
        self.assertEqual(stgidx.verify(ix, nodes), [], 'old endpoint must be removed when an interval changes')
        self.assertEqual(ix.subset(time_range=(200, 210))[0], ['b'])
        self.assertEqual(ix.subset(time_range=(420, 430))[0], ['a'])

    def test_remove_interval_cleans_endpoint(self):
        nodes = {'a': {'time_window': [100, 300]}, 'b': {'temporal': 205}}
        ix = stgidx.build({'nodes': nodes})
        ix.remove('a')
        nodes.pop('a')
        self.assertEqual(stgidx.verify(ix, nodes), [])
        self.assertEqual(ix.subset(time_range=(200, 210))[0], ['b'])

    def test_nonfinite_endpoint_is_conservative(self):
        nodes = {'nanend': {'time_window': [100, math.nan]},
                 'nanstart': {'time_window': [math.nan, 300]},
                 'infend': {'time_window': [100, math.inf]},
                 'point': {'temporal': 205}}
        ix = stgidx.build({'nodes': nodes})
        ids, _ = ix.subset(time_range=(200, 210))
        expected = {nid for nid, e in nodes.items()
                    if stg.time_relation(tuple(e.get('time_window', [205, 205])), (200, 210))
                    in ('during', 'contains', 'overlaps', 'equals')}
        self.assertTrue(expected <= set(ids), 'non-finite ends must not silently remove exact baseline hits')

    def test_millisecond_windows_and_temporal_precedence(self):
        lo = 1792022400
        nodes = {'long': {'time_window': [(lo-100)*1000, (lo+100)*1000]},
                 'point_override': {'temporal': lo+500, 'time_window': [lo-100, lo+100]}}
        ix = stgidx.build({'nodes': nodes})
        self.assertEqual(ix.subset(time_range=(lo, lo+1))[0], ['long'])

    def test_endpoint_audit_detects_corruption(self):
        nodes = {'long': {'time_window': [100, 300]}}
        ix = stgidx.build({'nodes': nodes})
        self.assertTrue(hasattr(ix, 'by_end'), 'interval endpoint index is required')
        ix.by_end.remove((300.0, 'long'))
        self.assertTrue(stgidx.verify(ix, nodes), 'endpoint/index mismatch must be observable')

    def test_layer_and_session_intersection(self):
        nodes = {'a': {'time_window': [100, 300], 'layer': 'knowledge', 'session': 'x'},
                 'b': {'time_window': [100, 300], 'layer': 'contextual', 'session': 'x'},
                 'c': {'temporal': 205, 'layer': 'knowledge', 'session': 'y'}}
        ix = stgidx.build({'nodes': nodes})
        self.assertEqual(ix.subset(time_range=(200, 210), layer='knowledge', session='x')[0], ['a'])

    def test_broken_index_still_falls_back(self):
        self.native()
        with mock.patch.dict(os.environ, {'MDCG_STG_INDEX': '1'}):
            stg.anchors(self.cg, time_window=[200, 210])
            self.cg._stg_index.broken = True
            r = stg.anchors(self.cg, time_window=[200, 210])
        self.assertEqual([n['id'] for n in r['items']], ['long', 'left', 'point'])

    def test_random_interval_updates_preserve_block_bounds(self):
        rng = random.Random(9015)
        nodes = {f'n{i:04}': {'time_window': [i, i+70]} for i in range(180)}
        ix = stgidx.build({'nodes': nodes})
        for step in range(900):
            nid = f'n{rng.randrange(260):04}'
            if rng.randrange(4) == 0:
                ix.remove(nid)
                nodes.pop(nid, None)
            else:
                start = rng.randrange(300)
                nodes[nid] = {'time_window': [start, start+rng.randrange(1, 120)]}
                ix.add(nid, nodes[nid])
            if step % 30 == 0:
                self.assertEqual(stgidx.verify(ix, nodes), [], 'split/merge and endpoint summaries must stay coherent')
                ids, _ = ix.subset(time_range=(100, 110))
                expected = {n for n, e in nodes.items() if e['time_window'][0] <= 110 and e['time_window'][1] >= 100}
                self.assertTrue(expected <= set(ids))

    def test_interval_delete_all_and_regrow(self):
        nodes = {f'n{i:04}': {'time_window': [i, i+100]} for i in range(240)}
        ix = stgidx.build({'nodes': nodes})
        for nid in list(nodes):
            ix.remove(nid)
            nodes.pop(nid)
        self.assertEqual(stgidx.verify(ix, nodes), [])
        nodes['new'] = {'time_window': [1, 999]}
        ix.add('new', nodes['new'])
        self.assertEqual(stgidx.verify(ix, nodes), [])
        self.assertEqual(ix.subset(time_range=(500, 510))[0], ['new'])

    def test_endpoint_start_audit_checks_values(self):
        nodes = {'a': {'time_window': [10, 300]}, 'b': {'time_window': [100, 400]}}
        ix = stgidx.build({'nodes': nodes})
        self.assertTrue(hasattr(ix, 'interval_starts'), 'start summaries require a source-value witness')
        # Keep the block minimum unchanged: key-only and minimum-only audits
        # would both miss this different start value on the nonminimum member.
        ix.interval_starts['b'] = 200
        self.assertTrue(stgidx.verify(ix, nodes), 'each stored start value must equal its authoritative interval')

MUTATIONS = [
    mutation('audit only endpoint keys', 'md_cg.stgidx', 'verify', ['md_cg.stgidx:verify'],
             'ix.interval_starts != starts', 'set(ix.interval_starts) != set(starts)',
             'test_endpoint_start_audit_checks_values'),
    mutation('reverse block-start pruning', 'md_cg.stgidx', '_TimeBlocks.crossing_ids', ['md_cg.stgidx:_TimeBlocks.crossing_ids'],
             'if self._mins[j] >= lo:', 'if self._mins[j] <= lo:', 'test_native_contains_and_overlap'),
    mutation('start-only subset', 'md_cg.stgidx', 'StgIndex.subset', ['md_cg.stgidx:StgIndex.subset'],
             'self.overlap_ids(lo, hi) + list(self.nonfinite)', 'self.range_ids(lo, hi) + list(self.nonfinite)',
             'test_native_contains_and_overlap'),
    mutation('ignore long interval ends', 'md_cg.stgidx', 'StgIndex.overlap_ids', ['md_cg.stgidx:StgIndex.overlap_ids'],
             'if self.interval_ends:', 'if False:', 'test_native_contains_and_overlap'),
    mutation('omit endpoint insertion', 'md_cg.stgidx', 'StgIndex._classify', ['md_cg.stgidx:StgIndex._classify'],
             'self.by_end.add((end, nid))', 'pass', 'test_native_contains_and_overlap'),
    mutation('retain stale interval end', 'md_cg.stgidx', 'StgIndex._unclassify', ['md_cg.stgidx:StgIndex._unclassify'],
             'self.by_end.remove((end, nid))', 'pass', 'test_incremental_endpoint_replacement'),
    mutation('drop uncertain endpoints', 'md_cg.stgidx', 'StgIndex._classify', ['md_cg.stgidx:StgIndex._classify'],
             'self.uncertain_ends.add(nid)', 'pass', 'test_nonfinite_endpoint_is_conservative'),
]

if __name__ == '__main__':
    raise SystemExit(run_guard(globals(), MUTATIONS))
