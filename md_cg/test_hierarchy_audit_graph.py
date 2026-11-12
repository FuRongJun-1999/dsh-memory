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

def carrier(nodes):
    return SimpleNamespace(index={'nodes':nodes},get=lambda _nid:None)

def legacy_declared_report(graph,limit):
    # Frozen old declared-only report oracle, used ONLY for compatibility.
    known=list(graph);known_set=set(known);parent={};issues=[]
    def issue(**kw):
        if len(issues)<limit*4:issues.append(kw)
    for pid in known:
        for child in dict.fromkeys(graph[pid]):
            if child==pid:issue(id=pid,issue='self_loop',child=child);continue
            if child not in known_set:issue(id=pid,issue='dangling_child',child=child)
            prev=parent.get(child)
            if prev is not None and prev!=pid:issue(id=child,issue='multi_parent',parents=sorted({prev,pid}))
            else:parent[child]=pid
    for nid in known:
        path=[];cur=nid
        while cur is not None:
            if cur in path:issue(id=cur,issue='cycle',path=path[path.index(cur):]+[cur]);break
            path.append(cur);cur=parent.get(cur)
    return dict(scanned=len(known),issues=len(issues),items=issues[:limit],truncated=len(issues)>limit)

class Guards(RuntimeCase):
    def test_real_edge_only_cycle_is_detected(self):
        self.cg.add('p','parent p',edges=[dict(target='q',relation_type='contains')])
        self.cg.add('q','parent q',edges=[dict(target='p',relation_type='contains')])
        result=self.cg.subgraph_validate()
        self.assertTrue(any(i['issue']=='cycle' for i in result['items']))

    def test_edge_only_multiple_parents_are_detected(self):
        nodes={'p':{'subgraph':None,'edges':[dict(target='c',relation_type='contains')]},
               'q':{'subgraph':None,'edges':[dict(target='c',relation_type='parent_of')]},'c':{'subgraph':[]}}
        result=subgraph.validate(carrier(nodes))
        self.assertIn('multi_parent',{i['issue'] for i in result['items']})

    def test_explicit_dangling_parent_is_reported(self):
        self.cg.add('child','child',edges=[dict(target='missing',relation_type='part_of')])
        self.assertIn('dangling_parent',{i['issue'] for i in self.cg.subgraph_validate()['items']})

    def test_declared_and_explicit_inverse_agree(self):
        nodes={'p':{'subgraph':['c']},'c':{'subgraph':[],'edges':[dict(target='p',relation_type='part_of')]}}
        cg=carrier(nodes)
        self.assertEqual(subgraph.children_index(cg),{'p':['c']})
        self.assertEqual(subgraph.parents_index(cg),{'c':['p']})
        self.assertEqual(subgraph.validate(cg)['issues'],0)

    def test_historical_relation_and_target_aliases(self):
        for rel in ('part_of','hierarchical','parent_of','contains'):
            source,target=('c','p') if rel in ('part_of','hierarchical') else ('p','c')
            nodes={n:{'subgraph':[]} for n in ('p','c')}
            nodes[source]['edges']=[dict(target_id=target,type=rel.upper())]
            cg=carrier(nodes)
            self.assertEqual(subgraph.children_index(cg),{'p':['c']})
            self.assertEqual(subgraph.parents_index(cg),{'c':['p']})

    def test_scan_prefix_does_not_invent_a_dangling_child(self):
        cg=carrier({'p':{'subgraph':['c']},'c':{'subgraph':[]}})
        result=subgraph.validate(cg,max_scan=1)
        self.assertEqual(result['scanned'],1)
        self.assertEqual(result['issues'],0)

    def test_malformed_edge_container_is_a_diagnostic(self):
        result=subgraph.validate(carrier({'p':{'subgraph':[],'edges':7}}))
        self.assertIn('invalid_edges',{i['issue'] for i in result['items']})

    def test_causal_edges_do_not_become_hierarchy(self):
        cg=carrier({'p':{'subgraph':[],'edges':[dict(target='p',relation_type='causal')]}})
        self.assertEqual(subgraph.validate(cg)['issues'],0)
        self.assertEqual(subgraph.children_index(cg),{})

    def test_legacy_declared_reports_remain_identical(self):
        rng=random.Random(11981);ids=list('abcde')
        for case in range(60):
            graph={n:[v for v in ids+['ghost'] if rng.random()<0.25] for n in ids}
            cg=carrier({n:{'subgraph':kids} for n,kids in graph.items()})
            limit=(1,2,50)[case%3]
            with self.subTest(case=case):self.assertEqual(subgraph.validate(cg,limit=limit),legacy_declared_report(graph,limit))

    def test_cycle_tail_enters_at_the_correct_member(self):
        graph={'p':['r'],'q':['p','tail'],'r':['q'],'tail':[]}
        result=subgraph.validate(carrier({n:{'subgraph':kids} for n,kids in graph.items()}))
        self.assertEqual(result,legacy_declared_report(graph,50))
        self.assertTrue(any(i.get('path')==['q','r','p','q'] for i in result['items']))

    def test_report_cap_and_zero_limit_keep_old_counts(self):
        graph={str(i):[str(i)] for i in range(20)}
        for limit in (0,1,2):
            cg=carrier({n:{'subgraph':kids} for n,kids in graph.items()})
            self.assertEqual(subgraph.validate(cg,limit=limit),legacy_declared_report(graph,limit))

    def test_resolved_tails_have_linear_source_line_work(self):
        counts=[]
        for n in (100,300):
            cg=carrier({str(i):{'subgraph':[str(i+1)] if i<n-1 else []} for i in range(n)})
            events=[0]
            def trace(frame,event,arg):
                if frame.f_code.co_filename.startswith(subgraph.__file__):
                    if event=='line':events[0]+=1
                    return trace
                return None
            try:sys.settrace(trace);result=subgraph.validate(cg)
            finally:sys.settrace(None)
            self.assertEqual(result['issues'],0);counts.append(events[0])
        self.assertLessEqual(counts[1],4*counts[0])

MUTATIONS=[{'name': 'A1 omit explicit parent-to-child hierarchy edges', 'module': 'md_cg.subgraph', 'symbol': '_hierarchy_pairs', 'targets': ['md_cg.subgraph:_hierarchy_pairs'], 'old': 'elif rel in ("parent_of", "contains"):', 'new': 'elif False:', 'test': 'Guards.test_real_edge_only_cycle_is_detected'}, {'name': 'A2 reverse historical part-of edge direction', 'module': 'md_cg.subgraph', 'symbol': '_hierarchy_pairs', 'targets': ['md_cg.subgraph:_hierarchy_pairs'], 'old': 'yield pid, target', 'new': 'yield target, pid', 'test': 'Guards.test_declared_and_explicit_inverse_agree'}, {'name': 'A3 do not memoize resolved ancestor tails', 'module': 'md_cg.subgraph', 'symbol': '_cycle_entries', 'targets': ['md_cg.subgraph:_cycle_entries'], 'old': 'while cur is not None and cur not in positions and cur not in resolved:', 'new': 'while cur is not None and cur not in positions:', 'test': 'Guards.test_resolved_tails_have_linear_source_line_work'}, {'name': 'A4 discard discovered cycles', 'module': 'md_cg.subgraph', 'symbol': '_cycle_entries', 'targets': ['md_cg.subgraph:_cycle_entries'], 'old': 'if cur in positions:', 'new': 'if False:', 'test': 'Guards.test_cycle_tail_enters_at_the_correct_member'}, {'name': 'A5 confuse the scan prefix with the entire graph', 'module': 'md_cg.subgraph', 'symbol': 'validate', 'targets': ['md_cg.subgraph:validate'], 'old': 'known_set = set(all_known)', 'new': 'known_set = set(known)', 'test': 'Guards.test_scan_prefix_does_not_invent_a_dangling_child'}]

if __name__=="__main__":
    raise SystemExit(run_guard(globals(),MUTATIONS))
