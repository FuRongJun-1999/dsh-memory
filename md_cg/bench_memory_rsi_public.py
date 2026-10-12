"""RRF/delivery diagnostics on public hive state-chain data; no reader QA score.

python -m md_cg.bench_memory_rsi_public --bench /checkout/hive-memory-bench --out /new/output
Only the existing official diagnostic normalization is reused. Value-substring
presence does NOT prove current-value correctness, support, or temporal reasoning.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import time


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bench', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--include-compact', action='store_true', help='retrospective compact-metadata ablation')
    args = ap.parse_args(argv)
    out, bench = args.out.resolve(), args.bench.resolve()
    out.mkdir(parents=True, exist_ok=False)
    for key, folder in (('MDCG_ROOT', 'graph'), ('MDCG_STATE_ROOT', 'state'),
                        ('MDCG_AUX_ROOT', 'auxiliary'), ('DSH_HOME', 'dsh')):
        os.environ[key] = str(out / folder)
    os.environ.update(MDCG_SEMANTIC='0', MDCG_HOTCACHE='0', MDCG_FRESHNESS='0',
                      MDCG_RRF_CANDIDATES='0', MDCG_SUSTAIN='0')
    # Keep imports after isolation: storage modules bind some paths at import.
    from scripts import bench_chain_retrieval_diag as diag
    from .evidence_delivery import deliver
    from .mdcos import MdCGOS, est_tokens

    _, norm = diag.load_official(str(bench))
    chapters, keys = diag.load_bench(str(bench))
    files = ['chain/corpus/corpus.json', 'chain/keys/keys.json', 'chain/tools/probe_judge.py']
    hashes = {p: hashlib.sha256((bench / p).read_bytes()).hexdigest() for p in files}
    evaluator_files = [Path(__file__), Path(__file__).with_name('evidence_delivery.py')]
    evaluator_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in evaluator_files}
    modes = ('A_original', 'B_query', 'B_query_metadata', 'C_prefix_control', 'D_candidate_index')
    if args.include_compact:
        modes += ('B_query_metadata_compact',)
    protocol = {'bench_commit': subprocess.check_output(
        ['git', '-C', str(bench), 'rev-parse', 'HEAD'], text=True,
        encoding='utf-8', errors='replace').strip(),
        'source_sha256': hashes, 'k': 6, 'budgets': [240, 1200], 'max_item_tokens': 250,
        'evaluator_source_sha256': evaluator_hashes, 'include_compact': args.include_compact,
        'evaluation_history': 'previously observed public corpus; retrospective diagnostic',
        'graph_created_at': 1767225600,
        'selection': 'none; fixed diagnostics after synthetic development',
        'model': None, 'reader': None, 'official_answer_score': False,
        'warning': 'value occurrence is not an answer or chain-support metric'}
    (out / 'protocol.json').write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding='utf-8')
    cg = MdCGOS(str(out / 'graph'))
    rows_out = []
    try:
        for ch in chapters:
            cg.add(diag.MdCGEngine.node_id(ch['cid']), '# ' + ch['cid'] + '\n' + ch['text'],
                   layer='knowledge', verification_basis='data', source='public:hive-memory-bench',
                   created_at=1767225600)
        cg.flush()
        for q in (q for q in keys if q.get('type') == '现值'):
            cur, stale = diag.split_values(q['answer'], norm)
            for budget in (240, 1200):
                for mode in modes:
                    os.environ['MDCG_RRF_CANDIDATES'] = '1' if mode == 'D_candidate_index' else '0'
                    start = time.perf_counter()
                    if mode in ('A_original', 'D_candidate_index'):
                        packed = cg.recall(q['question'], k=6, budget_tokens=budget, max_item_tokens=250)
                        text = '\n\n'.join(p['content'] for p in packed['pack'])
                    else:
                        found, _ = cg.search_rrf(q['question'], k=6)
                        packed = deliver(found, q['question'], budget_tokens=budget, max_item_tokens=250,
                            mode={'B_query': 'query', 'B_query_metadata': 'query_metadata',
                                  'B_query_metadata_compact': 'query_metadata_compact',
                                  'C_prefix_control': 'prefix'}[mode])
                        text = packed['text']
                    elapsed = (time.perf_counter() - start) * 1000
                    found, _ = cg.search_rrf(q['question'], k=6)
                    hits = [{'text': r[0]['content'], 'score': r[1]} for r in found]
                    d = diag.diag_case(hits, cur, stale, norm)
                    rows_out.append({'qid': q['qid'], 'mode': mode, 'budget': budget,
                                     'retrieval': d, 'rank_ids': [r[0]['id'] for r in found],
                                     'delivered_current_value_present': bool(cur and cur in norm(text)),
                                     'tokens': est_tokens(text), 'ms': elapsed, 'text': text})
    finally:
        os.environ['MDCG_RRF_CANDIDATES'] = '0'
        cg.close()
    summary = {}
    for budget in (240, 1200):
        summary[str(budget)] = {}
        for mode in sorted({r['mode'] for r in rows_out}):
            selected = [r for r in rows_out if r['mode'] == mode and r['budget'] == budget]
            summary[str(budget)][mode] = {
                'questions': len(selected),
                'retrieved_current_value_present_rate': statistics.mean(r['retrieval']['cur_rank'] is not None for r in selected),
                'stale_precedes_current_proxy': statistics.mean(r['retrieval']['stale_beats_current'] for r in selected),
                'delivered_current_value_present_rate': statistics.mean(r['delivered_current_value_present'] for r in selected),
                'mean_estimated_tokens': statistics.mean(r['tokens'] for r in selected),
                'budget_violations': sum(r['tokens'] > budget for r in selected),
                'answer_accuracy': None, 'temporal_reasoning_accuracy': None}
    unchanged = all(hashlib.sha256((bench / p).read_bytes()).hexdigest() == h for p, h in hashes.items())
    result = {'protocol': protocol, 'summary': summary, 'records': rows_out,
              'source_files_unchanged': unchanged,
              'evaluator_sources_unchanged': all(hashlib.sha256(path.read_bytes()).hexdigest()
                  == evaluator_hashes[path.name] for path in evaluator_files)}
    (out / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
