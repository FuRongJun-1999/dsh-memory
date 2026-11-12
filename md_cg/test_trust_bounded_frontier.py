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


from collections import deque
from . import trust

class Guards(RuntimeCase):
    def add(self, nid, parents=(), state='unverified'):
        self.cg.add(nid, 'memory '+nid, depends_on=list(parents), verification_state=state)

    def test_budget_applies_across_parents(self):
        for i in range(6):
            self.add('root'+str(i), state='expired')
            self.add('child'+str(i), ['root'+str(i)])
        rep = trust.propagate(self.cg, apply=True, max_nodes=7)
        self.assertEqual(rep['updated'], ['child0'], 'six roots leave only one downstream admission')
        self.assertEqual(rep.get('visited'), 7)
        self.assertTrue(rep.get('truncated'))
        self.assertEqual(trust.state_of(self.cg.get('child5')['frontmatter']), 'unverified')

    def test_budget_applies_across_second_wave(self):
        self.add('root', state='expired')
        for mid in ('a', 'b', 'c'):
            self.add(mid, ['root'])
            for i in range(3):
                self.add(mid+str(i), [mid])
        rep = trust.propagate(self.cg, max_nodes=6)
        self.assertEqual([n['node_id'] for n in rep['planned']], ['a', 'b', 'c', 'a0', 'a1'])
        self.assertEqual(rep.get('visited'), 6)

    def test_zero_budget_no_admission(self):
        self.add('root', state='expired')
        self.add('child', ['root'])
        rep = trust.propagate(self.cg, max_nodes=0, apply=True)
        self.assertEqual(rep['updated_count'], 0)
        self.assertEqual(rep.get('visited'), 0)
        self.assertTrue(rep.get('truncated'))

    def test_more_roots_than_budget(self):
        for i in range(4):
            self.add('r'+str(i), state='expired')
        rep = trust.propagate(self.cg, max_nodes=2)
        self.assertEqual(rep['roots_count'], 4)
        self.assertEqual(rep.get('roots_admitted'), 2)
        self.assertEqual(rep.get('visited'), 2)
        self.assertTrue(rep.get('truncated'))

    def test_doubted_bridge_remains_traversable(self):
        self.add('root', state='expired')
        self.add('mid', ['root'], state='doubted')
        self.add('leaf', ['mid'], state='verified')
        rep = trust.propagate(self.cg, max_nodes=10)
        self.assertEqual([n['node_id'] for n in rep['planned']], ['leaf'])
        self.assertEqual(rep['planned'][0]['depth'], 2)
        self.assertEqual(rep['passed_doubted'], ['mid'])
        self.assertEqual(trust.state_of(self.cg.get('leaf')['frontmatter']), 'verified')
        applied = trust.propagate(self.cg, max_nodes=10, apply=True)
        self.assertEqual(applied['updated'], ['leaf'])

    def test_convergent_parent_provenance(self):
        self.add('a', state='expired')
        self.add('b', state='rechecking')
        self.add('child', ['b', 'a'])
        rep = trust.propagate(self.cg, max_nodes=10)
        self.assertEqual(rep['planned'], [{'node_id': 'child', 'depth': 1, 'via': ['a', 'b']}])

    def test_sparse_provenance_work_is_linear(self):
        self.add('root', state='expired')
        for i in range(120):
            self.add('c%03d' % i, ['root'])
        work = [0]
        class Counted(list):
            def __contains__(self, value):
                for item in self:
                    work[0] += 1
                    if item == value:
                        return True
                return False
        dep = trust.dependents_index(self.cg)
        for key, value in list(dep.items()):
            dep[key] = Counted(value)
        rep = trust.propagate(self.cg, max_nodes=1000)
        self.assertEqual(rep['reachable'], 120)
        self.assertLessEqual(work[0], 10*241, 'provenance cannot rescan all child lists per reached node')

    def test_exactly_full_leaf_wave_is_not_truncated(self):
        self.add('root', state='expired')
        self.add('leaf', ['root'])
        rep = trust.propagate(self.cg, max_nodes=2)
        self.assertEqual(rep.get('visited'), 2)
        self.assertFalse(rep.get('truncated', True))

    def test_negative_budget_is_zero(self):
        self.add('root', state='expired')
        rep = trust.propagate(self.cg, max_nodes=-1)
        self.assertEqual(rep['max_nodes'], 0)
        self.assertEqual(rep.get('visited'), 0)

    def test_cycle_and_shared_child_match_bfs_oracle(self):
        deps = {'r': [], 'a': ['r', 'd'], 'b': ['r'], 'c': ['a', 'b'], 'd': ['c']}
        for nid, parents in deps.items():
            self.add(nid, parents, state='expired' if nid == 'r' else 'unverified')
        oracle, q = {'r': 0}, deque(['r'])
        while q:
            parent = q.popleft()
            for child in sorted(deps):
                if parent in deps[child] and child not in oracle:
                    oracle[child] = oracle[parent] + 1
                    q.append(child)
        rep = trust.propagate(self.cg, max_nodes=100)
        self.assertEqual({n['node_id']: n['depth'] for n in rep['planned']},
                         {n: d for n, d in oracle.items() if n != 'r'})

MUTATIONS = [
    mutation('remove cross-parent cap', 'md_cg.trust', 'propagate', ['md_cg.trust:propagate'],
             'if len(seen) >= cap:', 'if False:', 'test_budget_applies_across_parents'),
    mutation('erase provenance parents', 'md_cg.trust', 'propagate', ['md_cg.trust:propagate'],
             'sorted(n for n in as_deps((nodes.get(k) or {}).get(DEPS_FIELD))\n                                        if n in seen)', '[]',
             'test_convergent_parent_provenance'),
    mutation('stop at doubted bridge', 'md_cg.trust', 'propagate', ['md_cg.trust:propagate'],
             '                nxt.append(k)', '                if k not in passed:\n                    nxt.append(k)',
             'test_doubted_bridge_remains_traversable'),
    mutation('restore quadratic provenance scan', 'md_cg.trust', 'propagate', ['md_cg.trust:propagate'],
             'sorted(n for n in as_deps((nodes.get(k) or {}).get(DEPS_FIELD))\n                                        if n in seen)',
             'sorted(n for n in dep_map if k in dep_map[n] and n in seen)',
             'test_sparse_provenance_work_is_linear'),
]

if __name__ == '__main__':
    raise SystemExit(run_guard(globals(), MUTATIONS))
