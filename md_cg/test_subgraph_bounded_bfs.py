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
            'MDCG_MASTER_KEY': 'ab' * 32, 'MDCG_HOTCACHE': '0', 'MDCG_READ_CACHE': '0',
            'MDCG_AUX_ROOT': self.temp.name, 'MDCG_TOKEN_FILE': str(Path(self.temp.name)/'tokens.json'),
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




import random
from types import SimpleNamespace
from . import subgraph

def carrier(graph):
    return SimpleNamespace(index={'nodes':{n:{'subgraph':kids} for n,kids in graph.items()}},
        _subgraph_children=graph,get=lambda _nid:None)

class Guards(RuntimeCase):
    def diamond(self):
        return {'r':['a','b'],'a':['x'],'x':['c'],'b':['c'],'c':['tail'],'tail':[]}

    def test_depth_limited_shared_child_uses_shorter_route(self):
        for nid,kids in self.diamond().items():self.cg.add(nid,'hierarchy '+nid,subgraph=kids)
        result=self.cg.subgraph_expand('r',max_depth=3)
        self.assertIn('tail',result['nodes'])
        self.assertEqual(result['paths']['tail'],'r/b/c/tail')
        for order in (['a','b'],['b','a']):
            graph=self.diamond();graph['r']=order
            alternative=subgraph.expand(carrier(graph),'r',max_depth=3)
            self.assertIn('tail',alternative['nodes'])
            self.assertEqual(alternative['paths']['tail'],'r/b/c/tail')

    def test_edges_are_closed_over_admitted_nodes(self):
        result=subgraph.expand(carrier(self.diamond()),'r',max_nodes=1)
        self.assertEqual(result['nodes'],['r'])
        self.assertEqual(result['edges'],[])
        self.assertTrue(result['truncated'])

    def test_node_budget_is_never_exceeded(self):
        for budget in range(1,7):
            with self.subTest(budget=budget):
                result=subgraph.expand(carrier(self.diamond()),'r',max_nodes=budget)
                self.assertLessEqual(result['n_nodes'],budget)
                self.assertTrue(all(e['source'] in result['nodes'] and e['target'] in result['nodes'] for e in result['edges']))

    def test_frontier_does_not_copy_a_wide_child_list(self):
        visits=[]
        class Counted(list):
            def __iter__(self):
                for item in super().__iter__():visits.append(1);yield item
        graph={'r':Counted(str(i) for i in range(10000))}
        result=subgraph.expand(carrier(graph),'r',max_nodes=1)
        self.assertTrue(result['truncated'])
        self.assertLessEqual(len(visits),2)

    def test_depth_boundary_does_not_include_grandchildren(self):
        result=subgraph.expand(carrier({'r':['a'],'a':['b'],'b':[]}), 'r',max_depth=1)
        self.assertEqual(set(result['nodes']),{'r','a'})
        self.assertTrue(result['truncated'])

    def test_flatten_respects_closed_budget_projection(self):
        result=subgraph.flatten(carrier(self.diamond()),'r',max_nodes=1)
        self.assertEqual(result['edges'],[])
        self.assertEqual(result['n_edges'],0)

    def test_cycles_terminate_with_closed_edges(self):
        result=subgraph.expand(carrier({'r':['r','a'],'a':['r']}),'r',max_nodes=2)
        self.assertEqual(set(result['nodes']),{'r','a'})
        self.assertEqual(result['n_edges'],3)
        self.assertFalse(result['truncated'])

    def test_exact_tree_budget_is_not_truncated(self):
        result=subgraph.expand(carrier({'r':['a','b'],'a':[],'b':[]}), 'r',max_nodes=3)
        self.assertEqual(result['n_nodes'],3)
        self.assertFalse(result['truncated'])

    def test_zero_budget_does_not_prepare_adjacency(self):
        with mock.patch.object(subgraph,'children_index',side_effect=AssertionError('must not prepare unused adjacency')):
            result=subgraph.expand(self.cg,'r',max_nodes=0)
        self.assertEqual(result['nodes'],[])
        self.assertTrue(result['truncated'])

    def test_same_depth_tie_keeps_declaration_order(self):
        graph={'r':['a','b'],'a':['c'],'b':['c'],'c':[]}
        result=subgraph.expand(carrier(graph),'r')
        self.assertEqual(result['paths']['c'],'r/a/c')

    def test_nonfinite_node_budget_cannot_disable_the_bound(self):
        for value in (float('nan'),float('inf'),-float('inf')):
            with self.subTest(value=str(value)):
                with self.assertRaises((ValueError,OverflowError)):
                    subgraph.expand(carrier(self.diamond()),'r',max_nodes=value)

    def test_exhaustive_short_walk_oracle(self):
        rng=random.Random(90521)
        for case in range(60):
            ids=[str(i) for i in range(6)]
            graph={n:[v for v in ids if rng.random()<0.22] for n in ids}
            depth=case%5;walks=[('0',0)];reachable={'0'}
            while walks:
                current,d=walks.pop()
                if d>=depth:continue
                for child in graph[current]:reachable.add(child);walks.append((child,d+1))
            result=subgraph.expand(carrier(graph),'0',max_depth=depth,max_nodes=20)
            with self.subTest(case=case):
                self.assertEqual(set(result['nodes']),reachable)
                self.assertTrue(all(len(path.split('/'))-1<=depth for path in result['paths'].values()))

MUTATIONS=[{'name': 'B1 use a LIFO frontier again', 'module': 'md_cg.subgraph', 'symbol': 'expand', 'targets': ['md_cg.subgraph:expand'], 'old': 'cur, depth = queue.popleft()', 'new': 'cur, depth = queue.pop()', 'test': 'Guards.test_depth_limited_shared_child_uses_shorter_route'}, {'name': 'B2 ignore the node admission budget', 'module': 'md_cg.subgraph', 'symbol': 'expand', 'targets': ['md_cg.subgraph:expand'], 'old': 'if len(seen) >= max_nodes:', 'new': 'if False:', 'test': 'Guards.test_node_budget_is_never_exceeded'}, {'name': 'B3 copy the whole child list before checking budget', 'module': 'md_cg.subgraph', 'symbol': 'expand', 'targets': ['md_cg.subgraph:expand'], 'old': 'kids = adjacency.get(cur) or ()', 'new': 'kids = children(cg, cur)', 'test': 'Guards.test_frontier_does_not_copy_a_wide_child_list'}, {'name': 'B4 admit an edge before its child node', 'module': 'md_cg.subgraph', 'symbol': 'expand', 'targets': ['md_cg.subgraph:expand'], 'old': 'truncated = True\n                    break  # No unbounded frontier or edges to unadmitted IDs.', 'new': 'edges.append({"source": ch, "target": cur, "relation_type": "part_of"})\n                    truncated = True\n                    break', 'test': 'Guards.test_edges_are_closed_over_admitted_nodes'}, {'name': 'B5 expand one layer past the depth boundary', 'module': 'md_cg.subgraph', 'symbol': 'expand', 'targets': ['md_cg.subgraph:expand'], 'old': 'if max_depth is not None and depth >= max_depth:', 'new': 'if max_depth is not None and depth > max_depth:', 'test': 'Guards.test_depth_boundary_does_not_include_grandchildren'}]

if __name__=="__main__":
    raise SystemExit(run_guard(globals(),MUTATIONS))
