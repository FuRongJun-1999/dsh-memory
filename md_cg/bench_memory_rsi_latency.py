"""Warm, untraced timing replay. No selection and no new quality samples.

python -m md_cg.bench_memory_rsi_latency --experiment /saved/run --out /new/output
One warm-up pass is excluded. The original frozen holdout fixture is replayed;
this is a performance measurement, not another blind test set.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import statistics
import time


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--experiment', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    args = ap.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    for key, name in (('MDCG_STATE_ROOT', 'state'), ('MDCG_AUX_ROOT', 'auxiliary'),
                      ('DSH_HOME', 'dsh'), ('MDCG_ROOT', 'unused')):
        os.environ[key] = str(out / name)
    os.environ.update(MDCG_HOTCACHE='0', MDCG_READ_CACHE='1', MDCG_FRESHNESS='0',
                      MDCG_SEMANTIC='0', MDCG_RRF_CANDIDATES='0')
    from .bench_memory_rsi import BUDGET, ITEM_BUDGET, populate
    from .evidence_delivery import deliver
    from .mdcos import MdCGOS
    from .memory_rsi import create_sandbox
    fixture_file = args.experiment / 'fixtures.json'
    data = json.loads(fixture_file.read_text(encoding='utf-8'))
    modes = ['A_original', 'B_query', 'B_query_metadata', 'C_prefix_control', 'D_candidate_index']
    records = []
    for fixture in (f for f in data if f['split'] == 'holdout'):
        cg = MdCGOS(str(create_sandbox(out / str(fixture['seed']))))
        try:
            populate(cg, fixture)
            for turn in range(11):
                questions = list(fixture['queries'])
                random.Random(fixture['seed'] + turn).shuffle(questions)
                for q in questions:
                    order = list(modes)
                    random.Random(q['qid'] + str(turn)).shuffle(order)
                    for mode in order:
                        os.environ['MDCG_RRF_CANDIDATES'] = '1' if mode == 'D_candidate_index' else '0'
                        wall, cpu = time.perf_counter(), time.process_time()
                        if mode in ('A_original', 'D_candidate_index'):
                            cg.recall(q['query'], k=5, budget_tokens=BUDGET, max_item_tokens=ITEM_BUDGET)
                        else:
                            found, _ = cg.search_rrf(q['query'], k=5)
                            deliver(found, q['query'], budget_tokens=BUDGET, max_item_tokens=ITEM_BUDGET,
                                mode={'B_query': 'query', 'B_query_metadata': 'query_metadata',
                                      'C_prefix_control': 'prefix'}[mode])
                        ms = (time.perf_counter() - wall) * 1000
                        cpu_ms = (time.process_time() - cpu) * 1000
                        if turn:
                            records.append({'qid': q['qid'], 'seed': fixture['seed'], 'round': turn,
                                            'mode': mode, 'ms': ms, 'cpu_ms': cpu_ms})
        finally:
            cg.close()
    summary = {}
    for mode in modes:
        rows = [r for r in records if r['mode'] == mode]
        latency = sorted(r['ms'] for r in rows)
        summary[mode] = {'executions': len(rows), 'unique_queries': len({r['qid'] for r in rows}),
                         'p50_ms': statistics.median(latency),
                         'p95_ms': latency[int(len(latency) * .95)],
                         'cpu_ms_total': sum(r['cpu_ms'] for r in rows)}
    payload = {'fixture_sha256': hashlib.sha256(fixture_file.read_bytes()).hexdigest(),
               'tracemalloc_enabled': False, 'warmup_rounds_excluded': 1,
               'repeats': 10, 'summary': summary, 'records': records,
               'warning': 'warm synthetic graph; process CPU on Windows has coarse resolution; no cold-start or RSS claim'}
    (out / 'results.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
