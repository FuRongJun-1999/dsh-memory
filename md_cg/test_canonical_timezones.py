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



from datetime import datetime, timezone
import math
from . import trust

class Guards(RuntimeCase):
    def test_utc_z(self):
        want = datetime(2026, 10, 15, tzinfo=timezone.utc).timestamp()
        # Even a local conversion returning another epoch must not affect Z.
        with mock.patch.object(trust.time, 'mktime', return_value=-1234):
            self.assertEqual(trust.parse_time('2026-10-15T00:00:00Z'), want)

    def test_offset_equivalence(self):
        want = datetime(2026, 10, 15, tzinfo=timezone.utc).timestamp()
        for s in ('2026-10-15T08:00:00+08:00', '2026-10-14T20:00:00-04:00',
                  '2026-10-15T00:00:00+00:00'):
            with self.subTest(s=s):
                self.assertEqual(trust.parse_time(s), want)

    def test_fractional_offset(self):
        self.assertEqual(trust.parse_time('2026-10-15T08:00:00.125+08:00'),
                         datetime(2026, 10, 15, microsecond=125000, tzinfo=timezone.utc).timestamp())

    def test_nonfinite_rejected(self):
        for x in (float('nan'), float('inf'), -float('inf'), 'NaN', 'Infinity', '-inf'):
            with self.subTest(x=str(x)):
                self.assertIsNone(trust.parse_time(x))

    def test_nonfinite_does_not_shadow_alias(self):
        self.assertEqual(trust.first_endpoint({'effective_until': 'NaN', 'valid_until': 42},
                                             trust.UNTIL_ALIASES), (42.0, 'valid_until'))

    def test_invalid_query_endpoints_fail_closed(self):
        for value in ('NaN', 'inf', '-Infinity'):
            self.assertTrue(trust.check_time_args(start_time=value)[2])

    def test_naive_dates_keep_local_contract(self):
        for s, fmt in (('2026-10-15', '%Y-%m-%d'),
                       ('2026/10/15 08:20', '%Y-%m-%d %H:%M'),
                       ('2026-10-15T08:20:30', '%Y-%m-%d %H:%M:%S')):
            normalized = s.replace('/', '-').replace('T', ' ')
            self.assertEqual(trust.parse_time(s), trust.time.mktime(trust.time.strptime(normalized, fmt)))

    def test_numeric_seconds_milliseconds(self):
        for x in (1792022400, 1792022400000, '1792022400000'):
            self.assertEqual(trust.parse_time(x), 1792022400.0)

    def test_invalid_date_returns_none(self):
        for x in ('2026-99-99', 'not-time', '2026-10-15T08:00:00+99:00'):
            self.assertIsNone(trust.parse_time(x))

    def test_native_observed_window(self):
        moment = datetime(2026, 10, 15, tzinfo=timezone.utc).timestamp()
        self.cg.add('utc', 'timezone needle', temporal='2026-10-15T08:00:00+08:00')
        rows, meta = self.cg.search_rrf('needle', judge=False, record=False,
                                      paths=('lexical',), start_time=moment - 1,
                                      end_time=moment + 1, time_axis='observed')
        self.assertEqual([r[0]['id'] for r in rows], ['utc'])

    def test_validity_with_offset_deadline(self):
        moment = datetime(2026, 10, 15, tzinfo=timezone.utc).timestamp()
        self.assertEqual(trust.validity({'effective_until': '2026-10-15T08:00:00+08:00'},
                                        now=moment + 1)[0], 'expired')

    def test_observed_aliases_same_epoch(self):
        self.assertEqual(trust.time_window_of({'condition_space': {'time_window':
            ['2026-10-15T00:00:00Z', '2026-10-15T08:00:00+08:00']}}, 'observed'),
            (1792022400.0, 1792022400.0))

    def test_stg_keeps_nonfinite_conservative_bucket(self):
        from . import stgidx
        nodes = {'a': {'temporal': 5.0}, 'b': {}, 'c': {'temporal': float('nan')},
                 'd': {'temporal': float('inf')}}
        idx = stgidx.build({'nodes': nodes})
        self.assertEqual(stgidx.verify(idx, nodes), [])
        self.assertEqual(set(idx.subset(time_range=(5, 5))[0]), {'a', 'c', 'd'})
        self.assertIsNone(trust.parse_time(float('nan')))

    def test_stg_legacy_uncertainty_matches_index_and_scan(self):
        from . import stg
        interval = stg._interval({'temporal': float('nan')})
        self.assertIsNotNone(interval)
        self.assertTrue(all(math.isnan(x) for x in interval))
        self.assertIsNone(stg._interval({'valid_from': float('nan'), 'valid_until': 5},
                                       'effective'))

MUTATIONS = [{'name': 'T1 discard explicit timezone', 'module': 'md_cg.trust', 'symbol': 'parse_time', 'targets': ['md_cg.trust:parse_time'], 'old': 'if aware.tzinfo is not None:', 'new': 'if False:', 'test': 'Guards.test_offset_equivalence'}, {'name': 'T2 allow NaN and infinity', 'module': 'md_cg.trust', 'symbol': 'epoch_seconds', 'targets': ['md_cg.trust:epoch_seconds'], 'old': 'if not _allow_nonfinite and not math.isfinite(v):', 'new': 'if False:', 'test': 'Guards.test_nonfinite_rejected'}, {'name': 'T3 erase fractional seconds', 'module': 'md_cg.trust', 'symbol': 'parse_time', 'targets': ['md_cg.trust:parse_time'], 'old': 'ts = aware.timestamp()', 'new': 'ts = int(aware.timestamp())', 'test': 'Guards.test_fractional_offset'}, {'name': 'T4 replace local naive epoch', 'module': 'md_cg.trust', 'symbol': 'parse_time', 'targets': ['md_cg.trust:parse_time'], 'old': 'return time.mktime(time.strptime(t, f))', 'new': 'return 0.0', 'test': 'Guards.test_naive_dates_keep_local_contract'}, {'name': 'T5 drop conservative nonfinite index candidates', 'module': 'md_cg.stgidx', 'symbol': 'time_of', 'targets': ['md_cg.stgidx:time_of'], 'old': 'trust.time_window_of(entry, "observed", _allow_nonfinite=True)', 'new': 'trust.time_window_of(entry, "observed")', 'test': 'Guards.test_stg_keeps_nonfinite_conservative_bucket'}, {'name': 'T6 erase legacy uncertain STG intervals', 'module': 'md_cg.stg', 'symbol': '_interval', 'targets': ['md_cg.stg:_interval'], 'old': '_allow_nonfinite=(axis == "observed")', 'new': '_allow_nonfinite=False', 'test': 'Guards.test_stg_legacy_uncertainty_matches_index_and_scan'}]

if __name__ == "__main__":
    raise SystemExit(run_guard(globals(), MUTATIONS))
