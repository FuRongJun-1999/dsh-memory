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

from . import fsutil

class Guards(RuntimeCase):
    def test_every_utf8_cut_is_replayed_once(self):
        row = {'pid': 'p', 'content': '中文🙂完整证据'}
        data = (json.dumps(row, ensure_ascii=False) + '\n').encode('utf-8')
        for cut in range(1, len(data)):
            path = Path(self.temp.name) / ('cut' + str(cut))
            path.write_bytes(data[:cut])
            records, end = fsutil.read_jsonl_tail(str(path), 0)
            self.assertEqual((records, end), ([], 0), 'hold incomplete UTF-8 record')
            with path.open('ab') as f:
                f.write(data[cut:])
            records, end = fsutil.read_jsonl_tail(str(path), end)
            self.assertEqual(records, [row], 'completed row must survive every cut')
            self.assertEqual(fsutil.read_jsonl_tail(str(path), end), ([], end))

    def test_inbox_commit_becomes_visible(self):
        row = {'pid': 'later', 'id': 'node', 'content': 'complete after first read'}
        data = (json.dumps(row) + '\n').encode()
        path = Path(self.cg.inbox_log)
        path.write_bytes(data[:17])
        self.assertEqual(self.cg._inbox_records(), [])
        self.assertEqual(self.cg._inbox_phash_index(), {})
        with path.open('ab') as f:
            f.write(data[17:])
        self.assertEqual(self.cg._inbox_records(), [row], 'inbox commit cannot disappear')
        self.assertIn(('later', 'node'), next(iter(self.cg._inbox_phash_index().values())))
        self.assertEqual(self.cg._inbox_records(), [row], 'no duplicate on steady read')

    def test_decision_commit_becomes_visible(self):
        row = {'pid': 'later', 'status': 'accepted', 'decision': 'accepted'}
        data = (json.dumps(row) + '\n').encode()
        path = Path(self.cg.decisions_log)
        path.write_bytes(data[:20])
        self.assertEqual(self.cg._pid_status(), {})
        self.assertEqual(self.cg._decisions_records(), [])
        with path.open('ab') as f:
            f.write(data[20:])
        self.assertEqual(self.cg._pid_status(), {'later': row})
        self.assertEqual(self.cg._decisions_records(), [row])
        self.assertEqual(self.cg.review_stats()['records'], 1)

    def test_json_without_commit_newline_is_pending(self):
        path = Path(self.temp.name) / 'pending.jsonl'
        path.write_bytes(b'{"pid":"pending"}')
        self.assertEqual(fsutil.read_jsonl_tail(str(path), 0), ([], 0), 'newline is the commit boundary')
        with path.open('ab') as f:
            f.write(b'\n')
        self.assertEqual(fsutil.read_jsonl_tail(str(path), 0)[0], [{'pid': 'pending'}])

    def test_complete_bad_row_does_not_stall(self):
        path = Path(self.temp.name) / 'bad.jsonl'
        path.write_bytes(b'bad complete line\n{"pid":"good"}\n')
        rows, end = fsutil.read_jsonl_tail(str(path), 0)
        self.assertEqual(rows, [{'pid': 'good'}], 'complete corrupt row must not hide a later commit')
        self.assertEqual(end, path.stat().st_size)

    def test_incremental_watermark_keeps_prefix(self):
        path = Path(self.temp.name) / 'prefix.jsonl'
        a, b = b'{"pid":"a"}\n', b'{"pid":"b"}\n'
        path.write_bytes(a + b[:7])
        self.assertEqual(fsutil.read_jsonl_tail(str(path), 0), ([{'pid': 'a'}], len(a)))
        with path.open('ab') as f:
            f.write(b[7:])
        rows, end = fsutil.read_jsonl_tail(str(path), len(a))
        self.assertEqual((rows, end), ([{'pid': 'b'}], len(a + b)))

    def test_crash_resynchronization_keeps_next_append(self):
        path = Path(self.temp.name) / 'crash.jsonl'
        path.write_bytes(b'{"pid":"broken')
        _, end = fsutil.read_jsonl_tail(str(path), 0)
        fsutil.append_jsonl(str(path), {'pid': 'good'})
        rows, end = fsutil.read_jsonl_tail(str(path), end)
        self.assertEqual(rows, [{'pid': 'good'}])
        self.assertEqual(fsutil.read_jsonl_tail(str(path), end), ([], end))

    def test_empty_and_missing_contract(self):
        path = Path(self.temp.name) / 'missing.jsonl'
        self.assertEqual(fsutil.read_jsonl_tail(str(path), 0), ([], None))
        path.write_bytes(b'')
        self.assertEqual(fsutil.read_jsonl_tail(str(path), 0), ([], 0))

_TARGETS = ['md_cg.fsutil:read_jsonl_tail', 'md_cg.mdcos:read_jsonl_tail']
MUTATIONS = [
    mutation('advance beyond pending bytes', 'md_cg.fsutil', 'read_jsonl_tail', _TARGETS,
             'return recs, offset + committed', 'return recs, offset + len(data)',
             'test_inbox_commit_becomes_visible'),
    mutation('publish JSON before newline', 'md_cg.fsutil', 'read_jsonl_tail', _TARGETS,
             'for b in data[:committed].split(b"\\n"):', 'for b in data.split(b"\\n"):',
             'test_json_without_commit_newline_is_pending'),
    mutation('reset incremental watermark', 'md_cg.fsutil', 'read_jsonl_tail', _TARGETS,
             'return recs, offset + committed', 'return recs, committed',
             'test_incremental_watermark_keeps_prefix'),
]

def main(argv=None):
    return run_guard(globals(), MUTATIONS, argv)

if __name__ == "__main__":
    raise SystemExit(main())
