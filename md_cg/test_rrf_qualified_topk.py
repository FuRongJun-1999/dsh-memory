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

class Guards(RuntimeCase):
    def fixture(self, count=12, disposition='reject'):
        text = ('# 功能名：查询助手\n# 生效条件：needle\n# 子功能：检索\n'
                '# 执行：返回 needle 查询的证据\n# 验证方式：使用测试\n# 不适用条件：无\n')
        for i in range(count):
            self.cg.add(f'a{i:02}', text, verification_basis=None if disposition == 'defer' else 'test',
                        non_applicable_conditions=['forbiddencontext'] if disposition == 'reject' else [],
                        override=True)
        self.cg.add('zsafe', text + ' safe extra text', verification_basis='test',
                    non_applicable_conditions=['unrelatedcontext'], override=True)

    def read(self, **kw):
        opts = dict(paths=('lexical',), k=1, judge=True, judge_ranking=True,
                    context={'scene': 'forbiddencontext'}, record=False)
        opts.update(kw)
        return self.cg.search_rrf('needle', **opts)

    def test_refill_after_twelve_rejections(self):
        self.fixture()
        rows, meta = self.read()
        self.assertEqual([r[0]['id'] for r in rows], ['zsafe'], 'safe candidate below fixed window must fill top-k')
        self.assertEqual(meta['judge_filtered'], 12)
        self.assertEqual(rows[0][2]['state'], 'ACCEPT')

    def test_defer_penalty_does_not_hide_later_accept(self):
        self.fixture(disposition='defer')
        rows, _ = self.read()
        self.assertEqual([r[0]['id'] for r in rows], ['zsafe'], 'accepted candidate can beat earlier deferred rows')

    def test_early_bound_avoids_unnecessary_judgments(self):
        self.fixture(count=35, disposition='accept')
        with mock.patch.object(self.cg, 'judge_qualification', wraps=self.cg.judge_qualification) as judge:
            rows, _ = self.read(k=3)
        self.assertEqual([r[0]['id'] for r in rows], ['a00', 'a01', 'a02'])
        self.assertEqual(judge.call_count, 3, 'stop only after a proven top-k bound')

    def test_all_rejected_exhausts_pool(self):
        self.fixture()
        self.cg.forget('zsafe')
        rows, meta = self.read()
        self.assertEqual(rows, [])
        self.assertEqual(meta['judge_filtered'], 12)

    def test_large_k_returns_all_eligible(self):
        self.fixture()
        rows, _ = self.read(k=20)
        self.assertEqual([r[0]['id'] for r in rows], ['zsafe'])

    def test_judging_off_keeps_original_candidates(self):
        self.fixture()
        rows, _ = self.read(judge=False)
        self.assertEqual([r[0]['id'] for r in rows], ['a00'])

    def test_full_scan_oracle_for_native_candidates(self):
        self.fixture(count=24, disposition='defer')
        raw, _ = self.read(k=50, judge=False)
        expected = []
        for row in raw:
            state = self.cg.judge_qualification(row[0], 'needle', {'scene': 'forbiddencontext'})['state']
            if state not in ('REJECT', 'BLINDSPOT'):
                raw_score = sum(1 / (mdcos.RRF_K + p['rank'])
                                for p in row[3] if not p.get('recall_only'))
                expected.append((row[0]['id'], raw_score if state == 'ACCEPT' else raw_score * .5))
        expected.sort(key=lambda x: (-x[1], x[0]))
        for k in (1, 2, 5, 11, 30):
            rows, _ = self.read(k=k)
            self.assertEqual([r[0]['id'] for r in rows], [x[0] for x in expected[:k]])

    def test_zero_k_returns_empty(self):
        self.fixture()
        self.assertEqual(self.read(k=0)[0], [])

MUTATIONS = [
    mutation('restore fixed oversampling window', 'md_cg.mdcos', 'MdCGOS.search_rrf',
             ['md_cg.mdcos:MdCGOS.search_rrf'], 'for nid, fs in fused_all:\n',
             'for nid, fs in fused_all[:max(k * 2, 10)]:\n', 'test_refill_after_twelve_rejections'),
    mutation('stop when unqualified ranks fill k', 'md_cg.mdcos', 'MdCGOS.search_rrf',
             ['md_cg.mdcos:MdCGOS.search_rrf'],
             'for nid, fs in fused_all:\n', 'for nid, fs in fused_all[:k]:\n',
             'test_defer_penalty_does_not_hide_later_accept'),
    mutation('remove bound early exit', 'md_cg.mdcos', 'MdCGOS.search_rrf',
             ['md_cg.mdcos:MdCGOS.search_rrf'], 'if (k > 0 and len(kept) == k',
             'if (False and k > 0 and len(kept) == k', 'test_early_bound_avoids_unnecessary_judgments'),
    mutation('remove defer discount', 'md_cg.mdcos', 'MdCGOS.search_rrf',
             ['md_cg.mdcos:MdCGOS.search_rrf'],
             'kept.append((nid, fs if st == STATE_ACCEPT else fs * 0.5))',
             'kept.append((nid, fs))', 'test_defer_penalty_does_not_hide_later_accept'),
]

def main(argv=None):
    return run_guard(globals(), MUTATIONS, argv)

if __name__ == "__main__":
    raise SystemExit(main())
