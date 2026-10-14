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


from . import chain, subgraph, trust, nodefile, hotcache, lifecycle

class Guards(RuntimeCase):
    def setUp(self):
        super().setUp()
        hotcache.attach(self.cg)

    def pair(self):
        self.cg.add('seed', 'needle seed')
        self.cg.add('tail', 'unrelated tail')

    def query(self):
        return self.cg.search_rrf('needle', paths=('lexical', 'graph'), record=False, judge=False)

    def warm_query(self):
        self.query()
        self.assertTrue(self.query()[1].get('cached'), 'precondition: query cache is actually warm')

    def rewrite(self, nid, **changes):
        got = self.cg.get(nid)
        fm = dict(got['frontmatter'])
        fm.update(changes)
        Path(self.cg.root, got['path']).write_text(nodefile.dumps(fm, got['content']), encoding='utf-8')
        self.cg.rebuild_index()

    def test_append_edge_refreshes_chain(self):
        self.pair()
        self.assertEqual(chain.walk(self.cg, 'seed'), [])
        self.assertTrue(self.cg.append_edge('seed', {'target': 'tail', 'relation_type': 'causal'}))
        self.assertEqual([r['nodes'] for r in chain.walk(self.cg, 'seed')], [['seed', 'tail']],
                         'a committed edge must be visible without manual cache invalidation')

    def test_append_subgraph_refreshes_chain(self):
        self.pair()
        chain.adjacency(self.cg)
        self.cg.append_subgraph_node('seed', 'tail')
        self.assertIn('tail', [nid for nid, _ in chain.adjacency(self.cg).get('seed', [])])

    def test_edge_condition_refreshes_chain(self):
        self.pair()
        self.cg.append_edge('seed', {'target': 'tail', 'relation_type': 'causal',
                                     'condition_space': {'observation_position': 'old condition'}})
        chain.walk(self.cg, 'seed')
        self.cg.set_edge_condition('seed', 'tail', 'causal', {'observation_position': 'new condition'})
        self.assertIn('new condition', str(chain.walk(self.cg, 'seed')[0]['conditions']))

    def test_metadata_write_refreshes_query(self):
        self.pair()
        self.warm_query()
        self.cg.append_edge('seed', {'target': 'tail', 'relation_type': 'causal'})
        rows, meta = self.query()
        self.assertIn('tail', [r[0]['id'] for r in rows], 'graph hit must join the next result after metadata write')
        self.assertFalse(meta.get('cached', False))

    def test_verification_change_refreshes_query(self):
        self.pair()
        self.warm_query()
        self.assertTrue(trust.set_state(self.cg, 'seed', 'verified', reason='test evidence')['ok'])
        rows, meta = self.query()
        self.assertEqual(rows[0][0]['frontmatter']['verification_state'], 'verified')
        self.assertFalse(meta.get('cached', False))

    def test_lifecycle_change_refreshes_query(self):
        self.pair()
        self.warm_query()
        self.assertTrue(lifecycle.set_state(self.cg, 'seed', 'converged', reason='test')['ok'])
        rows, _ = self.query()
        self.assertEqual(rows[0][0]['frontmatter']['lifecycle_state'], 'converged')

    def test_rebuild_refreshes_query(self):
        self.pair()
        self.warm_query()
        self.rewrite('seed', tags=['new-source-tag'])
        rows, _ = self.query()
        self.assertIn('new-source-tag', rows[0][0]['frontmatter']['tags'])

    def test_rebuild_refreshes_graph(self):
        self.pair()
        chain.adjacency(self.cg)
        self.rewrite('seed', edges=[{'target': 'tail', 'relation_type': 'causal'}])
        self.assertEqual([r['nodes'] for r in chain.walk(self.cg, 'seed')], [['seed', 'tail']])

    def test_rebuild_refreshes_both_hierarchy_directions(self):
        self.pair()
        subgraph.children_index(self.cg)
        subgraph.parents_index(self.cg)
        self.rewrite('seed', subgraph={'nodes': ['tail']})
        self.assertEqual(subgraph.children(self.cg, 'seed'), ['tail'])
        self.assertEqual(subgraph.parents_index(self.cg).get('tail'), ['seed'])

    def test_rebuild_refreshes_dependency_index(self):
        self.pair()
        trust.dependents_index(self.cg)
        self.rewrite('tail', depends_on=['seed'])
        self.assertEqual(trust.dependents_index(self.cg).get('seed'), ['tail'],
                         'dependency cache must follow the rebuilt authoritative snapshot')

    def test_unchanged_reads_reuse_caches(self):
        self.pair()
        adj = chain.adjacency(self.cg)
        self.assertIs(chain.adjacency(self.cg), adj)
        self.warm_query()
        self.cg.get('seed')
        self.assertIs(chain.adjacency(self.cg), adj)
        self.assertTrue(self.query()[1].get('cached'))

    def test_base_mdcg_metadata_write(self):
        with tempfile.TemporaryDirectory(prefix='base_cache_') as root:
            cg = mdcg.MdCG(root)
            try:
                cg.add('a', 'base a')
                cg.add('b', 'base b')
                chain.adjacency(cg)
                cg.append_edge('a', {'target': 'b', 'relation_type': 'causal'})
                self.assertEqual(chain.walk(cg, 'a')[0:1] and chain.walk(cg, 'a')[0]['nodes'], ['a', 'b'])
            finally:
                cg.close()

MUTATIONS = [
    mutation('ignore dirty generation', 'md_cg.mdcg', 'MdCG._cache_generation', ['md_cg.mdcg:MdCG._cache_generation'],
             'previous[2] != version', 'False', 'test_append_edge_refreshes_chain'),
    mutation('ignore chain generation', 'md_cg.chain', 'adjacency', ['md_cg.chain:adjacency'],
             'and getattr(cg, "_chain_generation", None) == generation', 'and True', 'test_append_edge_refreshes_chain'),
    mutation('omit query generation witness', 'md_cg.mdcos', 'MdCGOS._index_generation', ['md_cg.mdcos:MdCGOS._index_generation'],
             'return g + self._cache_generation()', 'return g', 'test_verification_change_refreshes_query'),
    mutation('omit hierarchy generation', 'md_cg.subgraph', '_ensure_cache_generation', ['md_cg.subgraph:_ensure_cache_generation'],
             'if getattr(cg, "_subgraph_generation", None) != generation:', 'if False:',
             'test_rebuild_refreshes_both_hierarchy_directions'),
    mutation('ignore dependency generation', 'md_cg.trust', 'dependents_index', ['md_cg.trust:dependents_index'],
             'if not refresh and getattr(cg, "_trust_generation", None) == generation:', 'if not refresh:',
             'test_rebuild_refreshes_dependency_index'),
]

if __name__ == '__main__':
    raise SystemExit(run_guard(globals(), MUTATIONS))
