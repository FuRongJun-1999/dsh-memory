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

import copy
from . import nodefile

class Guards(RuntimeCase):
    def snapshot(self):
        self.cg.add('survivor', 'authoritative original evidence')
        self.source_content = self.cg.get('survivor')['content']
        self.cg.flush()
        self.cg.rebuild_index()
        return json.loads(Path(self.cg.index_path).read_text(encoding='utf-8'))

    def put(self, doc):
        # Restore adversarial derived fixtures before close(), including after
        # a failing mutant assertion. Source files themselves are unchanged.
        self.addCleanup(self.cg.rebuild_index)
        Path(self.cg.index_path).write_text(json.dumps(doc), encoding='utf-8')

    def recover(self):
        try:
            reopened = mdcg.MdCG(self.temp.name)
            self.addCleanup(reopened.close)
            node = reopened.get('survivor')
            return node is not None and node['content'] == self.source_content
        except (AttributeError, TypeError, KeyError):
            return False

    def test_load_container_shapes_recover(self):
        original = self.snapshot()
        for shape in (None, [], 3, 'bad'):
            with self.subTest(shape=shape):
                doc = copy.deepcopy(original)
                doc['nodes'] = shape
                self.put(doc)
                self.assertTrue(self.recover(), 'bad derived container must not block authoritative reads')

    def test_entry_shapes_recover(self):
        original = self.snapshot()
        for entry in (None, [], 'bad', {}, {'path': None}, {'path': 7}):
            with self.subTest(entry=entry):
                doc = copy.deepcopy(original)
                doc['nodes'] = {'phantom': entry}
                self.put(doc)
                self.assertTrue(self.recover(), 'bad entry must not replace real nodes')

    def test_unhashable_bucket_recovers(self):
        doc = self.snapshot()
        doc['nodes']['survivor']['bucket'] = ['bad']
        self.put(doc)
        self.assertTrue(self.recover(), 'malformed bucket must not crash snapshot accounting')

    def test_compact_container_shapes_recover(self):
        original = self.snapshot()
        for shape in (None, [], 9, {'phantom': None}, {'phantom': {}}):
            with self.subTest(shape=shape):
                doc = copy.deepcopy(original)
                doc['nodes'] = shape
                self.put(doc)
                try:
                    self.cg.compact_index()
                    success = 'survivor' in self.cg.index['nodes']
                except (AttributeError, TypeError, KeyError):
                    success = False
                self.assertTrue(success, 'compaction must share snapshot admission with startup')

    def test_missing_nodes_recovers(self):
        doc = self.snapshot()
        del doc['nodes']
        self.put(doc)
        self.assertTrue(self.recover())

    def test_valid_snapshot_keeps_fast_load(self):
        self.snapshot()
        with mock.patch.object(mdcg.MdCG, '_scan_nodes', side_effect=AssertionError('valid snapshot must stay fast')):
            reopened = mdcg.MdCG(self.temp.name)
        self.addCleanup(reopened.close)
        self.assertIsNotNone(reopened.get('survivor'))

    def test_real_node_bytes_are_unchanged(self):
        doc = self.snapshot()
        path = Path(self.temp.name) / doc['nodes']['survivor']['path']
        before = path.read_bytes()
        doc['nodes'] = None
        self.put(doc)
        self.assertTrue(self.recover())
        self.assertEqual(path.read_bytes(), before)

    def test_malformed_snapshot_and_new_log_preserve_both_nodes(self):
        doc = self.snapshot()
        self.cg.add('second', 'new committed evidence')
        self.cg.flush()
        doc['nodes'] = {'phantom': []}
        self.put(doc)
        try:
            self.cg.compact_index()
            ids = set(self.cg.index['nodes'])
        except (AttributeError, TypeError, KeyError):
            ids = set()
        self.assertEqual(ids, {'survivor', 'second'})

MUTATIONS = [
    mutation('accept malformed container', 'md_cg.mdcg', '_usable_index_snapshot',
             ['md_cg.mdcg:_usable_index_snapshot'], 'return isinstance(nodes, dict) and all(',
             'return True or all(', 'test_load_container_shapes_recover'),
    mutation('skip entry validation', 'md_cg.mdcg', '_usable_index_snapshot',
             ['md_cg.mdcg:_usable_index_snapshot'], 'for nid, entry in nodes.items())',
             'for nid, entry in [])', 'test_entry_shapes_recover'),
    mutation('compact bypasses shape gate', 'md_cg.mdcg', 'MdCG.compact_index',
             ['md_cg.mdcg:MdCG.compact_index'], 'if not _usable_index_snapshot(d):',
             'if not isinstance(d, dict):', 'test_compact_container_shapes_recover'),
    mutation('allow unhashable bucket', 'md_cg.mdcg', '_usable_index_snapshot',
             ['md_cg.mdcg:_usable_index_snapshot'],
             'and (entry.get("bucket") is None or isinstance(entry.get("bucket"), str))',
             'and True', 'test_unhashable_bucket_recovers'),
]

def main(argv=None):
    return run_guard(globals(), MUTATIONS, argv)

if __name__ == "__main__":
    raise SystemExit(main())
