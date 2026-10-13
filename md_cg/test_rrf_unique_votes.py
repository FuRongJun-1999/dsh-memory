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
    def fixture(self, copies=2, second=False):
        for i, suffix in enumerate(('', ' alpha', ' beta gamma', ' delta epsilon theta')):
            edges = [{'target': 'linked', 'relation_type': 'causal', 'confidence': 1.0}] * copies
            if second:
                edges += [{'target': 'second', 'relation_type': 'causal', 'confidence': 1.0}]
            self.cg.add(f'seed{i}', 'needle' + suffix, edges=edges, override=True)
        self.cg.add('linked', 'unrelated evidence', override=True)
        if second:
            self.cg.add('second', 'other evidence', override=True)

    def read(self, **options):
        opts = dict(paths=('bm25', 'graph'), k=100, judge=False, record=False)
        opts.update(options)
        return self.cg.search_rrf('needle', **opts)

    def test_native_convergence_one_vote(self):
        self.fixture()
        rows, meta = self.read()
        votes = meta['provenance']['linked']
        self.assertEqual(len(votes), 1, 'one node gets at most one vote in graph path')
        self.assertEqual(meta['paths']['graph'], 1)
        score = next(r[1] for r in rows if r[0]['id'] == 'linked')
        self.assertEqual(score, round(1 / (mdcos.RRF_K + 1), 6))

    def test_repeated_edge_invariance(self):
        self.fixture(copies=1)
        before, _ = self.read()
        signature = [(r[0]['id'], r[1], r[3]) for r in before]
        self.fixture(copies=7)
        after, _ = self.read()
        self.assertEqual([(r[0]['id'], r[1], r[3]) for r in after], signature,
                         'repeating the same edge must not inflate relevance')

    def test_duplicates_do_not_consume_unique_cap(self):
        self.fixture(copies=80, second=True)
        rows, meta = self.read()
        self.assertIn('second', {r[0]['id'] for r in rows}, 'unique candidate must survive repeated-edge cap')
        self.assertEqual(meta['paths']['graph'], 2)

    def test_distinct_paths_still_each_vote(self):
        self.fixture()
        rows, meta = self.read(paths=('bm25', 'graph', 'chain'))
        votes = meta['provenance']['linked']
        self.assertEqual({p['path'] for p in votes}, {'graph', 'chain'})
        self.assertEqual(len(votes), 2)
        score = next(r[1] for r in rows if r[0]['id'] == 'linked')
        self.assertEqual(score, round(2 / (mdcos.RRF_K + 1), 6))

    def test_max_fusion_is_duplicate_invariant(self):
        self.fixture(1)
        before, _ = self.read(fusion='max')
        self.fixture(5)
        after, _ = self.read(fusion='max')
        self.assertEqual([(r[0]['id'], r[1], r[3]) for r in before],
                         [(r[0]['id'], r[1], r[3]) for r in after])

    def test_unique_bm25_order_is_unchanged(self):
        self.fixture(2)
        entries = self.cg._candidates()
        raw, _ = bm25.search(self.cg, 'needle', entries, {'scanned': 0})
        rows, _ = self.read(paths=('bm25',))
        self.assertEqual([r[0]['id'] for r in rows], [n['id'] for n, _ in raw])

    def test_recall_only_cap_is_unique(self):
        self.fixture(80, second=True)
        rows, meta = self.read(recall_only=('graph',))
        self.assertIn('second', {r[0]['id'] for r in rows})
        self.assertEqual(meta['paths']['graph'], 2)

    def test_graph_provenance_rank_is_contiguous(self):
        self.fixture(3, second=True)
        _, meta = self.read()
        ranks = sorted(p['rank'] for ps in meta['provenance'].values()
                       for p in ps if p['path'] == 'graph')
        self.assertEqual(ranks, [1, 2])

MUTATIONS = [
    mutation('restore per-copy votes', 'md_cg.mdcos', 'MdCGOS.search_rrf',
             ['md_cg.mdcos:MdCGOS.search_rrf'], 'scored = list(unique.values())',
             'scored = scored', 'test_native_convergence_one_vote'),
    mutation('raw rows leak into recall-only cap', 'md_cg.mdcos', 'MdCGOS.search_rrf',
             ['md_cg.mdcos:MdCGOS.search_rrf'], '            ranked[name] = scored\n',
             '', 'test_recall_only_cap_is_unique'),
    mutation('deduplicate globally instead of per path', 'md_cg.mdcos', 'MdCGOS.search_rrf',
             ['md_cg.mdcos:MdCGOS.search_rrf'],
             '                contrib = w / (RRF_K + rank)',
             '                contrib = 0.0 if nid in rrf else w / (RRF_K + rank)',
             'test_distinct_paths_still_each_vote'),
]

def main(argv=None):
    return run_guard(globals(), MUTATIONS, argv)

if __name__ == "__main__":
    raise SystemExit(main())
