"""Isolated P0/P1 experiments; synthetic evidence metrics, NOT Agent QA scores.

python -X utf8 -m md_cg.bench_memory_rsi --out /new/experiment-directory
All source fixtures, labels, per-query results and selection inputs are saved.
No external model, production memory, benchmark-score rewrite or shell executor.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import time
import tracemalloc

from .memory_rsi import MemoryRSILab, create_sandbox, recommend_strategy

BUDGET = 240
ITEM_BUDGET = 120
SEEDS = (20261012, 314159)
SPLITS = ('development', 'validation', 'holdout')
GRAPH_CREATED_AT = 1767225600  # 2026-01-01T00:00:00Z, MdCG.add expects Unix seconds


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def fixture(seed, split):
    rng = random.Random(f'{seed}:{split}')
    docs, queries = [], []
    for index in range(24):
        key = 'K' + ''.join(rng.choice('ABCDEFGHJKLMNPQRSTUVWXYZ') for _ in range(8))
        kind = ('head', 'tail', 'tail', 'long_line', 'temporal', 'multihop')[index % 6]
        count = 2 if kind in ('temporal', 'multihop') else 1
        gold, evidence = [], []
        for part in range(count):
            nid = f'doc_{index:02d}_{part}'
            action = rng.choice(['restore the backup', 'restart the worker', 'renew the lease',
                                 'use the absolute path', 'reduce the batch size'])
            text = f'{key} recovery step {part + 1}: {action}.'
            prefix = '\n'.join('Background observation: normal service status.' for _ in range(48))
            if kind == 'head':
                body = text + '\n' + prefix
            elif kind == 'long_line':
                body = prefix.replace('\n', ' ') + ' ' + text
            else:
                body = prefix + '\n' + text
            if kind == 'temporal':
                body += f' Effective on 2026-0{part + 1}-01.'
            docs.append({'id': nid, 'content': body, 'key': key,
                         'source': f'synthetic:{split}:{index}:{part}',
                         'effective_from': f'2026-0{part + 1}-01' if kind == 'temporal' else None})
            gold.append(nid)
            evidence.append(text)
        # Off-distribution vocabulary deliberately retains a retrieval failure
        # mode: the key is absent and the query cannot be solved by lexical lookup.
        question = (f'How should {key} recovery proceed?' if index % 8 != 7 else
                    f'Which earlier intervention resolved incident alias-{index}?')
        queries.append({'qid': f'{seed}:{split}:{index}', 'query': question, 'kind': kind,
                        'gold': gold, 'evidence': evidence})
    for index in range(48):
        docs.append({'id': f'noise_{index:02d}', 'content':
                     f'Unrelated service memo number {index}. Normal observation only.',
                     'key': f'NOISE{index}', 'source': f'synthetic:noise:{index}',
                     'effective_from': None})
    queries.extend({'qid': f'{seed}:{split}:unknown{i}',
                    'query': f'Unobserved {rng.getrandbits(64):016x} intervention?',
                    'kind': 'unknown', 'gold': [], 'evidence': []} for i in range(4))
    return {'seed': seed, 'split': split, 'documents': docs, 'queries': queries}


def populate(cg, data):
    for doc in data['documents']:
        cg.add(doc['id'], doc['content'], layer='knowledge', verification_basis='data',
               condition_space={'all': [doc['key']]}, source=doc['source'],
               effective_from=doc['effective_from'], created_at=GRAPH_CREATED_AT)
    cg.flush()


def measure(fn):
    tracemalloc.reset_peak()
    before, _ = tracemalloc.get_traced_memory()
    wall, cpu = time.perf_counter(), time.process_time()
    value = fn()
    elapsed, used_cpu = time.perf_counter() - wall, time.process_time() - cpu
    _, peak = tracemalloc.get_traced_memory()
    return value, {'ms': elapsed * 1000, 'cpu_ms': used_cpu * 1000,
                   'python_transient_peak_bytes': max(0, peak - before)}


def summarize(rows):
    labelled = [r for r in rows if r['gold_count']]
    unknown = [r for r in rows if not r['gold_count']]
    latencies = sorted(r['ms'] for r in rows)
    return {'executions': len(rows), 'labelled_executions': len(labelled),
            'unique_queries': len({r['qid'] for r in rows}),
            'unique_labelled_queries': len({r['qid'] for r in labelled}),
            'recall_at_1': statistics.mean(r['recall1'] for r in labelled),
            'recall_at_5': statistics.mean(r['recall5'] for r in labelled),
            'mrr': statistics.mean(r['rr'] for r in labelled),
            'evidence_complete_rate': statistics.mean(r['complete'] for r in labelled),
            'temporal_evidence_complete_rate': statistics.mean(r['complete'] for r in labelled if r['kind'] == 'temporal'),
            'multihop_evidence_complete_rate': statistics.mean(r['complete'] for r in labelled if r['kind'] == 'multihop'),
            'unknown_nonempty_rate': statistics.mean(r['nonempty'] for r in unknown),
            'p50_ms': statistics.median(latencies),
            'p95_ms': latencies[min(len(latencies) - 1, int(len(latencies) * .95))],
            'mean_estimated_tokens': statistics.mean(r['tokens'] for r in rows),
            'max_estimated_tokens': max(r['tokens'] for r in rows),
            'cpu_ms_total': sum(r['cpu_ms'] for r in rows),
            'max_python_transient_peak_bytes': max(r['python_transient_peak_bytes'] for r in rows),
            'budget_violations': sum(r['tokens'] > BUDGET for r in rows),
            'provenance_exact_rate': statistics.mean(r['provenance_exact'] for r in rows if r['nonempty']),
            'agent_task_success_rate': None, 'temporal_reasoning_accuracy': None,
            'multihop_reasoning_accuracy': None, 'physical_peak_rss_bytes': None}


def score(q, rank_ids, text, tokens, timing, provenance_exact):
    gold = set(q['gold'])
    first = next((i + 1 for i, nid in enumerate(rank_ids) if nid in gold), None)
    return {'qid': q['qid'], 'kind': q['kind'], 'gold_count': len(gold),
            'rank_ids': rank_ids, 'recall1': len(gold & set(rank_ids[:1])) / len(gold) if gold else None,
            'recall5': len(gold & set(rank_ids[:5])) / len(gold) if gold else None,
            'rr': 1 / first if first else 0, 'complete': bool(gold) and all(e in text for e in q['evidence']),
            'tokens': tokens, 'nonempty': bool(text), 'provenance_exact': provenance_exact,
            'delivered_text': text, **timing}


def paired_interval(a, b, seed=827):
    # Timing repeats are clustered by question, never new statistical samples.
    def per_question(rows):
        grouped = {}
        for row in rows:
            if row['gold_count']:
                grouped.setdefault(row['qid'], []).append(float(row['complete']))
        return {qid: statistics.mean(values) for qid, values in grouped.items()}
    left, right = per_question(a), per_question(b)
    if not left or left.keys() != right.keys():
        raise ValueError('paired intervals require matching nonempty labelled question sets')
    pairs = [right[qid] - left[qid] for qid in sorted(left)]
    rng = random.Random(seed)
    values = sorted(statistics.mean(rng.choices(pairs, k=len(pairs))) for _ in range(2000))
    return {'difference': statistics.mean(pairs), 'unique_labelled_queries': len(pairs),
            'bootstrap_95_interval': [values[50], values[1949]],
            'unit': 'synthetic_query', 'warning': 'query bootstrap; templates are correlated; not population evidence'}


def experiment(base, data, rounds, *, include_compact=False):
    # Import storage only after main has isolated all persistence roots:
    # crypto/theory/tokens bind some auxiliary paths during import.
    from .evidence_delivery import deliver
    from .mdcos import MdCGOS, est_tokens
    graph = create_sandbox(base)
    cg = MdCGOS(str(graph))
    populate(cg, data)
    modes = ('A_original', 'B_query', 'B_query_metadata', 'C_prefix_control', 'D_candidate_index')
    if include_compact:
        modes += ('B_query_metadata_compact',)
    records = {name: [] for name in modes}
    oracles = []
    mismatch = 0
    try:
        # Quality and oracle decomposition on one deterministic pass.
        for q in data['queries']:
            rows, meta = cg.search_rrf(q['query'], k=5)
            full = '\n'.join(r[0]['content'] for r in rows)
            goldrows = [(cg.get(nid), 1.0, {'state': 'oracle'}, ['oracle']) for nid in q['gold']]
            original = cg.search_rrf
            try:
                cg.search_rrf = lambda *args, **kw: (goldrows, {'oracle': True})
                oraclepack = cg.recall(q['query'], k=5, budget_tokens=BUDGET, max_item_tokens=ITEM_BUDGET)
            finally:
                cg.search_rrf = original
            rtext = '\n'.join(p['content'] for p in oraclepack['pack'])
            oracles.append({'qid': q['qid'], 'gold_count': len(q['gold']),
                            'R_oracle_original_delivery': bool(q['gold']) and all(e in rtext for e in q['evidence']),
                            'actual_R_D_full_unbounded': bool(q['gold']) and all(e in full for e in q['evidence']),
                            'R_oracle_D_full_unbounded': bool(q['gold']),
                            'actual_retrieved_ids': [r[0]['id'] for r in rows]})
        for turn in range(rounds):
            questions = list(data['queries'])
            random.Random(data['seed'] + turn).shuffle(questions)
            for q in questions:
                order = modes if turn % 2 == 0 else tuple(reversed(modes))
                signatures = {}
                for name in order:
                    os.environ['MDCG_RRF_CANDIDATES'] = '1' if name == 'D_candidate_index' else '0'
                    # A is the actual original recall entry. D changes only the
                    # existing index flag. Candidate deliveries receive no labels.
                    if name in ('A_original', 'D_candidate_index'):
                        pack, timing = measure(lambda: cg.recall(q['query'], k=5,
                            budget_tokens=BUDGET, max_item_tokens=ITEM_BUDGET))
                        text = '\n\n'.join(p['content'] for p in pack['pack'])
                        tokens = est_tokens(text)
                        delivered = [p['id'] for p in pack['pack']]
                        exact = all(cg.get(p['id'])['content'].startswith(p['content'].rstrip('…')) for p in pack['pack'])
                    else:
                        def candidate_call():
                            found, _ = cg.search_rrf(q['query'], k=5)
                            out = deliver(found, q['query'], budget_tokens=BUDGET,
                                          max_item_tokens=ITEM_BUDGET,
                                          mode={'B_query': 'query', 'B_query_metadata': 'query_metadata',
                                                'B_query_metadata_compact': 'query_metadata_compact',
                                                'C_prefix_control': 'prefix'}[name])
                            return out
                        pack, timing = measure(candidate_call)
                        text, tokens = pack['text'], pack['tokens_used']
                        delivered = [r['id'] for r in pack['records']]
                        exact = all(r['source_sha256'] == hashlib.sha256(cg.get(r['id'])['content'].encode('utf-8')).hexdigest()
                                    and all(0 <= s['start'] <= s['end'] <= len(cg.get(r['id'])['content']) for s in r['spans'])
                                    for r in pack['records'])
                    rows, _ = cg.search_rrf(q['query'], k=5)
                    ids = [r[0]['id'] for r in rows]
                    signatures[name] = ids
                    records[name].append({'round': turn + 1, 'delivered_ids': delivered,
                                          **score(q, ids, text, tokens, timing, exact)})
                if signatures['A_original'] != signatures['D_candidate_index']:
                    mismatch += 1
            print(f'{data["split"]} seed={data["seed"]} round={turn + 1}/{rounds}', flush=True)
    finally:
        os.environ['MDCG_RRF_CANDIDATES'] = '0'
        cg.close()
    labelled = [r for r in oracles if r['gold_count']]
    return {'split': data['split'], 'seed': data['seed'],
            'summary': {name: summarize(values) for name, values in records.items()},
            'paired_B_query_vs_A': paired_interval(records['A_original'], records['B_query']),
            'oracle': {key: statistics.mean(r[key] for r in labelled) for key in
                       ('R_oracle_original_delivery', 'actual_R_D_full_unbounded', 'R_oracle_D_full_unbounded')},
            'index_ranking_mismatch_count': mismatch, 'oracle_records': oracles, 'records': records,
            'graph_disk_bytes': sum(p.stat().st_size for p in graph.rglob('*') if p.is_file())}


def experience_experiment(base):
    from .mdcos import MdCGOS
    modes = ('original_direct', 'original_proposal', 'checked_reflector')
    results, raw = {}, []
    for mode in modes:
        cg = MdCGOS(str(create_sandbox(base / mode)))
        lab = MemoryRSILab(cg, base / mode, enabled=True)
        false_positive, supported, knowledge_written = 0, 0, 0
        try:
            for i in range(32):
                passed = i % 2 == 0
                error = f'ModuleNotFoundError: library_{i}'
                action = f'pip install library_{i}'
                if mode.startswith('original'):
                    # Original log miner sees a command followed by a failed
                    # result, and has no structured success check to consult.
                    events = [{'text': error}, {'text': action},
                              {'text': 'assertion passed' if passed else 'installation failed; same error persists'}]
                    result = cg.mine_fix_pairs(events, as_proposals=mode == 'original_proposal')
                    proposed = bool(result['pids'] if mode == 'original_proposal' else result['knowledge_ids'])
                    knowledge_written += len(result['knowledge_ids'])
                else:
                    trace = {'task_id': str(i), 'scope': 'isolated dependency installation',
                             'conditions': [f'environment_{i}'], 'events': [
                        {'id': 'e', 'kind': 'error', 'text': error},
                        {'id': 'a', 'kind': 'action', 'text': action, 'error_id': 'e'},
                        {'id': 'v', 'kind': 'check', 'text': 'import assertion result',
                         'action_id': 'a', 'error_id': 'e', 'source': 'tool', 'passed': passed}]}
                    nid = lab.record_experience(trace)
                    reflected = lab.reflect(nid)
                    result = [lab.curate(c) for c in reflected['candidates']]
                    proposed = bool(result)
                false_positive += int(proposed and not passed)
                supported += int(proposed and passed)
                raw.append({'arm': mode, 'case': i, 'observed_check_passed': passed,
                            'lesson_produced': proposed, 'result': result})
            results[mode] = {'unsupported_lesson_rate': false_positive / 16,
                             'supported_lesson_rate': supported / 16,
                             'knowledge_written': knowledge_written,
                             'pending_proposals': len(cg.review_list()),
                             'external_authenticity': 'not_authenticated',
                             'agent_transfer_success': None}
        finally:
            cg.close()
    return {'summary': results, 'records': raw}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True, help='new directory; existing paths refused')
    ap.add_argument('--rounds', type=int, default=3)
    ap.add_argument('--include-compact', action='store_true', help='retrospective compact-metadata ablation')
    args = ap.parse_args(argv)
    if not 1 <= args.rounds <= 5:
        ap.error('rounds must be 1..5')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    # Override every persistence root BEFORE constructing any memory instance.
    for key, name in (('MDCG_STATE_ROOT', 'state'), ('MDCG_AUX_ROOT', 'auxiliary'),
                      ('DSH_HOME', 'dsh'), ('MDCG_ROOT', 'unused-default')):
        os.environ[key] = str(out / name)
    os.environ.update(MDCG_HOTCACHE='0', MDCG_READ_CACHE='1', MDCG_FRESHNESS='0',
                      MDCG_SEMANTIC='0', MDCG_RRF_CANDIDATES='0')
    fixtures = [fixture(seed, split) for split in SPLITS for seed in SEEDS]
    save(out / 'fixtures.json', fixtures)
    frozen = hashlib.sha256((out / 'fixtures.json').read_bytes()).hexdigest()
    evaluator_files = ('bench_memory_rsi.py', 'evidence_delivery.py', 'memory_rsi.py')
    source_hashes = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                     for name in evaluator_files}
    save(out / 'protocol.json', {'schema': 2, 'seed': SEEDS, 'budget_tokens': BUDGET,
         'max_item_tokens': ITEM_BUDGET, 'rounds': args.rounds, 'k': 5,
         'model': None, 'reader': None, 'fixture_sha256': frozen, 'source_sha256': source_hashes,
         'graph_created_at': GRAPH_CREATED_AT,
         'sample_unit': 'unique question; repeated executions measure timing only',
         'scorer': 'exact all-support substring; ranking Recall@K and first relevant reciprocal rank',
         'oracle_warning': 'full-delivery oracles remove the budget; diagnostic upper bounds only',
         'selection': 'validation only; holdout evaluated once after recommendation is fixed',
         'include_compact': args.include_compact,
         'evaluation_history': 'previously observed fixtures; retrospective replay, not a new blind holdout',
         'metrics_not_measured': ['agent success', 'reasoning accuracy', 'real model tokens', 'physical RSS'],
         'public_benchmark_score': False})
    tracemalloc.start()
    report = {'baseline_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True,
                                                        encoding='utf-8', errors='replace').strip(),
              'python': sys.version, 'platform': platform.platform(), 'runs': []}
    for split in ('development', 'validation'):
        for data in (f for f in fixtures if f['split'] == split):
            report['runs'].append(experiment(out / f'{split}-{data["seed"]}', data, args.rounds,
                                            include_compact=args.include_compact))
            save(out / 'results.json', report)
    validation = [r for r in report['runs'] if r['split'] == 'validation']
    inputs = []
    for name in validation[0]['summary']:
        stats = [r['summary'][name] for r in validation]
        inputs.append({'name': name, 'split': 'validation',
                       'budget_ok': all(v['budget_violations'] == 0 for v in stats),
                       'unsafe_accepts': 0,  # deliveries perform no knowledge writes
                       'evidence_rate': statistics.mean(v['evidence_complete_rate'] for v in stats),
                       'p95_ms': statistics.mean(v['p95_ms'] for v in stats)})
    report['selection_inputs'] = inputs
    report['selection'] = recommend_strategy(inputs)
    save(out / 'selection-before-holdout.json', report['selection'])
    for data in (f for f in fixtures if f['split'] == 'holdout'):
        report['runs'].append(experiment(out / f'holdout-{data["seed"]}', data, args.rounds,
                                        include_compact=args.include_compact))
    report['experience'] = experience_experiment(out / 'experience')
    report['fixtures_unchanged'] = hashlib.sha256((out / 'fixtures.json').read_bytes()).hexdigest() == frozen
    report['evaluator_sources_unchanged'] = all(
        hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() == expected
        for name, expected in source_hashes.items())
    report['python_traced_peak_bytes'] = tracemalloc.get_traced_memory()[1]
    save(out / 'results.json', report)
    print(json.dumps({'selection': report['selection'], 'experience': report['experience']['summary'],
                      'fixture_sha256': frozen, 'output': str(out)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
