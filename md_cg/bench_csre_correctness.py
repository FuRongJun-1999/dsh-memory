"""Compare explicit CSRE correctness and warm cost on fixed temporary sources.

``--engine-source`` optionally selects an archived, trusted csre.py baseline.
This is a diagnostic benchmark, not Agent success or a public QA benchmark.
"""
import argparse
import atexit
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import statistics
import sys
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--engine-source', type=Path)
    ap.add_argument('--session', action='store_true', help='opt-in SQLite data_version session')
    ap.add_argument('--sizes', type=int, nargs='+', default=[100, 1000])
    ap.add_argument('--repeats', type=int, default=7)
    args = ap.parse_args()
    if args.session and args.engine_source:
        ap.error('--session and --engine-source are mutually exclusive')
    if not 1 <= args.repeats <= 30 or any(not 20 <= n <= 5000 for n in args.sizes):
        ap.error('sizes must be 20..5000; repeats must be 1..30')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    os.environ.update(WB_MD_DIRECT='0', WB_MD_ROOT=str(out / 'empty-md'))
    wisdom = Path(__file__).resolve().parent / 'whitebox_kb' / 'wisdom'
    sys.path.insert(0, str(wisdom))
    source = (args.engine_source or wisdom / ('csre_session.py' if args.session else 'csre.py')).resolve()
    spec = importlib.util.spec_from_file_location('csre_bench_engine', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine_class = module.CsreSession if args.session else module.Csre
    sessions = contextlib.ExitStack()
    atexit.register(sessions.close)

    def new_engine(database, index):
        instance = engine_class(str(database), str(index))
        return sessions.enter_context(instance) if args.session else instance

    before = sha(source)
    protocol = {'kind': 'synthetic correctness and cost diagnostic',
                'sizes': args.sizes, 'repeats': args.repeats, 'warmup': 1,
                'query_count_per_size': 20, 'engine_source': str(source),
                'session_enabled': args.session,
                'parent_csre_sha256': sha(wisdom / 'csre.py') if args.session else None,
                'engine_sha256': before, 'script_sha256': sha(__file__),
                'clock': 'perf_counter; validation cost included',
                'caveats': ['local warm SQLite only', 'no statistical speedup claim',
                            'not a blind or natural-language Agent evaluation']}
    (out / 'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    results = []
    for size in args.sizes:
        folder = out / str(size)
        folder.mkdir()
        database, index = folder / 'source.db', folder / 'index.npz'
        fixture = []
        for i in range(size):
            value = {'name': f'card-{i:05}', 'domain': f'domain-{i % 4}',
                     'comment': {'生效条件': [f'问基准条件{i % 20:02}'],
                                 '不适用条件': ['问生产环境'] if i % 7 == 0 else []}}
            fixture.append([f'u{i:05}', 'temporary benchmark card',
                            json.dumps(value, ensure_ascii=False), 'knowledge_point'])
        (folder / 'fixture.json').write_text(json.dumps(fixture, ensure_ascii=False), encoding='utf-8')
        with contextlib.closing(sqlite3.connect(database)) as db:
            db.execute('CREATE TABLE nodes(id TEXT PRIMARY KEY, content TEXT, '
                       'state_attributes TEXT, tags TEXT)')
            db.executemany('INSERT INTO nodes VALUES(?,?,?,?)', fixture)
            db.commit()
        engine = new_engine(database, index)
        start = time.perf_counter()
        build = engine.build_index()
        build_ms = (time.perf_counter() - start) * 1000
        engine.save_index()
        loaded = new_engine(database, index)
        load_ok = loaded.ensure_loaded()
        query_rows = []
        samples = []
        for repeat in range(args.repeats + 1):
            for q in range(20):
                query = f'基准条件{q:02} 生产环境'
                start = time.perf_counter()
                loaded.rank_domains(query, top_k=1)
                rows = loaded.top_units_in_domain(f'domain-{q % 4}', query, limit=3)
                elapsed = (time.perf_counter() - start) * 1000
                if repeat:
                    samples.append(elapsed)
                if repeat == 1:
                    ids = [row['node_id'] for row in rows]
                    blocked = [nid for nid in ids if int(nid[1:]) % 7 == 0]
                    query_rows.append({'query': query, 'ids': ids, 'blocked_ids_returned': blocked})
        copy = folder / 'identical-other-source.db'
        shutil.copyfile(database, copy)
        cross = new_engine(copy, index)
        cross_loaded = cross.ensure_loaded()
        index_before = sha(index)
        with contextlib.closing(sqlite3.connect(database)) as db:
            changed = {'name': 'updated', 'domain': 'domain-0',
                       'comment': {'生效条件': ['问更新条件乙'], '不适用条件': []}}
            db.execute('UPDATE nodes SET state_attributes=? WHERE id=?',
                       (json.dumps(changed, ensure_ascii=False), 'u00000'))
            db.commit()
        stale_loaded = loaded.ensure_loaded()
        rebuilt = new_engine(database, folder / 'rebuild.npz')
        rebuilt.build_index()
        row = {'units': size, 'fixture_sha256': sha(folder / 'fixture.json'),
               'build': build, 'build_ms': build_ms, 'fresh_load': load_ok,
               'queries': query_rows,
               'negative_violation_queries': sum(bool(q['blocked_ids_returned']) for q in query_rows),
               'cross_source_accepted': cross_loaded,
               'stale_source_accepted': stale_loaded,
               'warm_vocab_contains_new_condition': '更新条件乙' in (loaded.vocab or []),
               'explicit_rebuild_contains_new_condition': '更新条件乙' in rebuilt.vocab,
               'read_checks_left_index_unchanged': sha(index) == index_before,
               'timing_executions': len(samples), 'p50_ms': statistics.median(samples),
               'p95_ms': sorted(samples)[int(.95 * (len(samples) - 1))],
               'raw_ms': samples}
        if hasattr(loaded, 'index_info'):
            row['stale_state'] = loaded.index_info()
            row['cross_source_state'] = cross.index_info()
        results.append(row)
        sessions.close()
    result = {'protocol': protocol, 'results': results,
              'engine_source_unchanged': before == sha(source),
              'agent_task_success': None, 'production_latency': None}
    (out / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'results': [{k: v for k, v in row.items() if k not in ('queries', 'raw_ms')}
                                 for row in results]}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
