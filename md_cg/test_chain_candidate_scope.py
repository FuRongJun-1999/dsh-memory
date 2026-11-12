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



from . import chain

class Guards(RuntimeCase):
    def graph(self, **middle):
        edge = lambda target: {'target': target, 'relation_type': 'causal', 'confidence': 1.0}
        self.cg.add('seed', 'needle seed', edges=[edge('bridge')])
        self.cg.add('bridge', '# 生效条件：bridge-only-condition\nbridge', edges=[edge('tail')], **middle)
        self.cg.add('tail', 'remote destination')
        self.cg.flush()
        seed = self.cg.get('seed')
        return [(dict(seed, id='seed'), 1.0)]

    def path(self, seeds, **options):
        entries = self.cg._candidates(**options)
        return self.cg._path_chain('needle', entries, seeds)

    def test_hidden_branch_is_not_a_bridge(self):
        seeds = self.graph(branch_id='experiment')
        rows, provenance = self.path(seeds)
        self.assertEqual(rows, [])
        self.assertEqual(provenance, {})

    def test_explicit_branch_restores_path(self):
        seeds = self.graph(branch_id='experiment')
        rows, prov = self.path(seeds, branch='experiment')
        self.assertIn('tail', {r[0]['id'] for r in rows})
        self.assertEqual(prov['tail']['chain'], ['seed', 'bridge', 'tail'])

    def test_work_role_is_not_a_bridge(self):
        seeds = self.graph(role='tool-output')
        rows, _ = self.path(seeds)
        self.assertEqual(rows, [])

    def test_include_work_restores_path(self):
        seeds = self.graph(role='tool-output')
        self.assertIn('tail', {r[0]['id'] for r in self.path(seeds, include_work=True)[0]})

    def test_expired_node_is_not_a_bridge(self):
        seeds = self.graph(valid_until=1)
        self.assertEqual(self.path(seeds, validity=True)[0], [])

    def test_session_filter_also_constrains_intermediates(self):
        seeds = self.graph(session='other')
        # Seed/tail share the selected session; only the intermediate differs.
        for nid in ('seed', 'tail'):
            self.cg.index['nodes'][nid]['session'] = 'selected'
        self.assertEqual(self.path(seeds, session='selected')[0], [])

    def test_layer_filter_constrains_intermediates(self):
        seeds = self.graph(layer='contextual')
        self.assertEqual(self.path(seeds, layer='knowledge')[0], [])

    def test_real_rrf_has_no_hidden_provenance(self):
        self.graph(branch_id='experiment')
        rows, meta = self.cg.search_rrf('needle', paths=('lexical', 'chain'),
                                       judge=False, record=False, k=20)
        self.assertNotIn('tail', {r[0]['id'] for r in rows})
        self.assertNotIn('bridge-only-condition', json.dumps(rows, ensure_ascii=False))

    def test_direct_unscoped_api_keeps_existing_behavior(self):
        self.graph(branch_id='experiment')
        found = chain.expand_from_seeds(self.cg, {'seed': 1.0})
        self.assertIn('tail', found)

    def test_empty_candidate_pool_returns_no_paths(self):
        seeds = self.graph()
        self.assertEqual(self.cg._path_chain('needle', [], seeds), ([], {}))

    def test_scope_does_not_poison_global_adjacency(self):
        seeds = self.graph(branch_id='experiment')
        self.assertEqual(self.path(seeds)[0], [])
        self.assertIn('tail', chain.expand_from_seeds(self.cg, {'seed': 1.0}))

    def test_nonmonotone_fallback_keeps_scope(self):
        self.graph(branch_id='experiment')
        # The native fallback remains usable; only a disallowed bridge is cut.
        report = {}
        import inspect
        # Assert capability first so the baseline is a named assertion failure.
        self.assertIn('allowed_ids', inspect.signature(chain.expand_from_seeds).parameters)
        found = chain.expand_from_seeds(self.cg, {'seed': 1.0}, decay=1.1,
                                       allowed_ids={'seed', 'tail'}, stats=report)
        self.assertEqual(found, {})
        self.assertEqual(report['algorithm'], 'legacy_fallback')

    def test_incoming_walk_keeps_scope(self):
        self.graph()
        import inspect
        self.assertIn('allowed_ids', inspect.signature(chain.walk).parameters)
        self.assertEqual(chain.walk(self.cg, 'tail', direction='in',
                                   allowed_ids={'seed', 'tail'}), [])

    def test_hidden_intermediate_does_not_consume_budget(self):
        self.graph(branch_id='experiment')
        import inspect
        self.assertIn('allowed_ids', inspect.signature(chain.expand_from_seeds).parameters)
        report = {}
        chain.expand_from_seeds(self.cg, {'seed': 1.0}, allowed_ids={'seed', 'tail'}, stats=report)
        self.assertEqual(report['edges_scanned'], 0)
        self.assertEqual(report['expanded'], 1)

MUTATIONS = [{'name': 'C1 allow a hidden target into scoped adjacency', 'module': 'md_cg.chain', 'symbol': '_scoped_adjacency', 'targets': ['md_cg.chain:_scoped_adjacency'], 'old': 'if dst in allowed_ids] for src in allowed_ids}', 'new': 'if True] for src in allowed_ids}', 'test': 'Guards.test_hidden_intermediate_does_not_consume_budget'}, {'name': 'C2 ignore candidate scope entirely', 'module': 'md_cg.chain', 'symbol': '_scoped_adjacency', 'targets': ['md_cg.chain:_scoped_adjacency'], 'old': 'if allowed_ids is None:\n        return adj', 'new': 'if True:\n        return adj', 'test': 'Guards.test_work_role_is_not_a_bridge'}, {'name': 'C3 drop scope in legacy fallback', 'module': 'md_cg.chain', 'symbol': '_expand_legacy', 'targets': ['md_cg.chain:_expand_legacy'], 'old': 'include_hierarchy=include_hierarchy, allowed_ids=allowed_ids):', 'new': 'include_hierarchy=include_hierarchy, allowed_ids=None):', 'test': 'Guards.test_nonmonotone_fallback_keeps_scope'}, {'name': 'C4 forget scope at production RRF call', 'module': 'md_cg.mdcos', 'symbol': 'MdCGOS._path_chain', 'targets': ['md_cg.mdcos:MdCGOS._path_chain'], 'old': 'max_depth=depth, decay=decay, allowed_ids=allowed_ids)', 'new': 'max_depth=depth, decay=decay, allowed_ids=None)', 'test': 'Guards.test_real_rrf_has_no_hidden_provenance'}]

if __name__ == "__main__":
    raise SystemExit(run_guard(globals(), MUTATIONS))
