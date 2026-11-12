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




from collections import Counter
from . import bm25, readcache

class Guards(RuntimeCase):
    def setUp(self):
        super().setUp()
        for i in range(53):
            self.cg.add(f'd{i:03}', 'apple ' * (1+i%5) + 'pear',
                        importance=0.1+i/100, session='A')
        self.cg.flush()

    def direct(self, query='apple pear'):
        return bm25.search(self.cg, query, self.cg._candidates(session='A'), {'scanned':0})

    def fresh(self):
        cg=mdcos.MdCGOS(self.cg.root)
        try:
            cg.rebuild_index()
            return bm25.search(cg,'apple pear',cg._candidates(session='A'),{'scanned':0})
        finally:cg.close()

    def race(self, batches=(1,), call=None, maximum_calls=None):
        # Bind faults to an actual production index instance, including when a
        # search callable was compiled in a mutation module with other globals.
        self.cg._bm25_index=bm25.BM25Index()
        original=bm25.BM25Index.rank;read=self.cg._read_many
        calls=[];deleted=[];read_paths=[]
        def hydrate(entries,stat):
            read_paths.extend(e['path'] for e in entries)
            return read(entries,stat)
        def rank(idx,*args,**kw):
            calls.append(1)
            if maximum_calls and len(calls)>maximum_calls:
                raise ValueError('fixture bounds a deliberately broken progress mutant')
            ranked=original(idx,*args,**kw)
            if len(calls)<=len(batches):
                eligible=[path for path,_score in ranked if path not in read_paths]
                for path in eligible[:batches[len(calls)-1]]:
                    target=Path(self.cg.root)/path
                    self.assertTrue(target.resolve().is_relative_to(Path(self.cg.root).resolve()))
                    target.unlink();deleted.append(path)
            return ranked
        with mock.patch.object(bm25.BM25Index,'rank',rank), mock.patch.object(self.cg,'_read_many',hydrate):
            rows,report=(call or self.direct)()
        return rows,report,calls,deleted,read_paths

    def test_native_rrf_refills_top_fifty(self):
        def entry():return self.cg.search_rrf('apple pear',k=50,session='A',paths=('bm25',),judge=False,record=False)
        rows,meta,_calls,deleted,_reads=self.race(call=entry)
        self.assertEqual(len(deleted),1)
        self.assertNotIn('fallback',meta['bm25'])
        self.assertEqual(len(rows),50)

    def test_winners_use_recomputed_corpus_scores(self):
        rows,info,*_=self.race()
        expected,_=self.fresh()
        self.assertNotIn('fallback',info)
        self.assertEqual([(n['id'],score) for n,score in rows],[(n['id'],score) for n,score in expected])

    def test_later_promoted_file_can_also_disappear(self):
        rows,info,calls,deleted,_reads=self.race(batches=(1,1))
        expected,_=self.fresh()
        self.assertEqual(len(deleted),2)
        self.assertNotIn('fallback',info)
        self.assertEqual(len(rows),50)
        self.assertEqual([n['id'] for n,_ in rows],[n['id'] for n,_ in expected])
        self.assertLessEqual(len(calls),len(deleted)+1)

    def test_payloads_already_hydrated_are_reused(self):
        _rows,info,_calls,deleted,reads=self.race()
        successful=Counter(p for p in reads if p not in deleted)
        self.assertTrue(successful)
        self.assertTrue(all(n==1 for n in successful.values()))
        self.assertNotIn('fallback',info)

    def test_all_sources_disappear_and_terminate(self):
        rows,info,calls,deleted,_reads=self.race(batches=(50,50))
        self.assertEqual(len(deleted),53)
        self.assertEqual(rows,[])
        self.assertNotIn('fallback',info)
        self.assertEqual(info.get('documents',-1),0)
        self.assertLessEqual(len(calls),3)

    def test_report_tracks_surviving_corpus(self):
        _rows,info,*_=self.race()
        self.assertEqual(info.get('documents',-1),52)
        self.assertEqual(info.get('matched',-1),52)
        self.assertEqual(info.get('hydrated',-1),50)

    def test_stuck_index_uses_existing_fallback_once(self):
        with mock.patch.object(bm25.BM25Index,'remove',return_value=None):
            _rows,info,calls,*_=self.race(maximum_calls=2)
        self.assertEqual(info.get('fallback'),'lexical_index_error')
        self.assertEqual(info.get('error_type'),'RuntimeError')
        self.assertEqual(len(calls),1)

    def test_empty_query_has_no_zero_score_padding(self):
        rows,info=self.direct('term_absent_everywhere')
        self.assertEqual(rows,[])
        self.assertEqual(info.get('hydration_reads',0),0)

    def test_normal_query_keeps_exact_scores(self):
        rows,info=self.direct();expected,_=self.fresh()
        self.assertEqual([(n['id'],s) for n,s in rows],[(n['id'],s) for n,s in expected])
        self.assertNotIn('fallback',info)
        self.assertEqual(len(rows),50)

    def test_transient_omission_is_retried_next_query(self):
        readcache.install(self.cg)
        original=self.cg._read_many;once=[]
        def transient(entries,stat):
            rows=original(entries,stat)
            if not once and rows:
                once.append(rows[0][0]['path']);return rows[1:]
            return rows
        with mock.patch.object(self.cg,'_read_many',transient):
            first,info=self.direct()
        self.assertEqual(len(first),50)
        later,_=self.direct();expected,_=self.fresh()
        self.assertEqual([n['id'] for n,_ in later],[n['id'] for n,_ in expected])
        self.assertNotIn('fallback',info)

    def test_scope_cannot_be_refilled_from_another_session(self):
        self.cg.add('secret_other_session','apple pear',session='B',importance=1.0)
        rows,info,*_=self.race()
        self.assertEqual(len(rows),50)
        self.assertNotIn('secret_other_session',[n['id'] for n,_ in rows])
        self.assertNotIn('fallback',info)

    def test_block_max_refill_equals_exhaustive_live_oracle(self):
        with mock.patch.object(bm25,'BLOCK_SIZE',8),mock.patch.object(bm25,'BLOCK_THRESHOLD',8):
            rows,info,*_=self.race()
            with mock.patch.dict(os.environ,{'MDCG_BM25_BLOCK_MAX':'0'}):expected,_=self.fresh()
        self.assertEqual(info.get('algorithm'),'exact_block_max')
        self.assertNotIn('fallback',info)
        self.assertEqual([(n['id'],s) for n,s in rows],[(n['id'],s) for n,s in expected])

MUTATIONS=[{'name': 'H1 stop after the first incomplete payload batch', 'module': 'md_cg.bm25', 'symbol': 'search', 'targets': ['md_cg.bm25:search'], 'old': 'if not unavailable:\n                break', 'new': 'if True:\n                ranked = [(p, s) for p, s in ranked if p in hydrated]\n                break', 'test': 'Guards.test_native_rrf_refills_top_fifty'}, {'name': 'H2 retain old corpus scores for surviving winners', 'module': 'md_cg.bm25', 'symbol': 'search', 'targets': ['md_cg.bm25:search'], 'old': 'scores = dict(ranked)', 'new': 'if "initial_scores" not in locals():\n                initial_scores = dict(ranked)\n            ranked = [(p, initial_scores.get(p, s)) for p, s in ranked]\n            scores = dict(ranked)', 'test': 'Guards.test_winners_use_recomputed_corpus_scores'}, {'name': 'H3 discard already hydrated successful payloads', 'module': 'md_cg.bm25', 'symbol': 'search', 'targets': ['md_cg.bm25:search'], 'old': 'hydrated = {path: doc for path, doc in hydrated.items() if path in scores}', 'new': 'hydrated = {}', 'test': 'Guards.test_payloads_already_hydrated_are_reused'}, {'name': 'H4 disable the monotone progress defense', 'module': 'md_cg.bm25', 'symbol': 'search', 'targets': ['md_cg.bm25:search'], 'old': 'if len(idx.docs) >= before:', 'new': 'if False:', 'test': 'Guards.test_stuck_index_uses_existing_fallback_once'}, {'name': 'H5 leave unavailable winners in term statistics', 'module': 'md_cg.bm25', 'symbol': 'search', 'targets': ['md_cg.bm25:search'], 'old': 'idx.remove(path)', 'new': 'pass', 'test': 'Guards.test_block_max_refill_equals_exhaustive_live_oracle'}]

if __name__=="__main__":
    raise SystemExit(run_guard(globals(),MUTATIONS))
