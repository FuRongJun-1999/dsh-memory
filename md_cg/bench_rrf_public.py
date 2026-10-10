"""Paired RRF candidate evaluation on the project's public 500-query pool.

python -X utf8 -m md_cg.bench_rrf_public --rounds 3 --output public.json

Gold-only keyword pool; this is not an official memory QA leaderboard result.
Production document cache only; no eval read monkeypatch or result cache.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import time

from . import mdcos, eval_common as ec, bench_locomo_zh_public as public
from .bench_rrf_candidates import signature
from .bench_fuzzy_substrings import latency

REPO = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--output', type=Path, default=Path('rrf-public-results.json'))
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error('rounds must be positive')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    os.environ.update(MDCG_HOTCACHE='0', MDCG_READ_CACHE='1', MDCG_FRESHNESS='0',
                      MDCG_RETRIEVAL_PIPELINE='0', MDCG_SEMANTIC='0', MDCG_UNIFY_QUERY='0')
    ec.unlock_global_cap()
    ec.use_jaccard()
    questions = list(ec.iter_jsonl(public.QUESTIONS500))
    pool = public.build_pool(list(ec.iter_jsonl(public.CORPUS567)))
    pool.close()
    engines = {arm: mdcos.MdCGOS(public.ROOT) for arm in ('scan', 'indexed')}
    report = {'nodes': len(engines['scan'].index['nodes']), 'questions': len(questions),
              'rounds': args.rounds, 'limits': 'gold-only keyword pool; not official QA',
              'cache': 'production read cache only; no eval read monkeypatch or result cache',
              'baseline': 'same substring-optimized code, candidate flag off',
              'sha256': {name: hashlib.sha256((REPO / 'md_cg' / name).read_bytes()).hexdigest()
                         for name in ('mdcos.py', 'rrf_candidates.py', 'readcache.py', 'hotcache.py')},
              'benchmark_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'first': {}, 'configs': {}}
    try:
        for arm, cg in engines.items():
            os.environ['MDCG_RRF_CANDIDATES'] = '1' if arm == 'indexed' else '0'
            started = time.perf_counter()
            rows, meta = cg.search_rrf(questions[0]['question'], k=5,
                                       paths=('lexical', 'fuzzy'), judge=False, record=False)
            report['first'][arm] = {'ms': (time.perf_counter() - started) * 1000,
                                   'signature': signature(rows, meta),
                                   'index': meta.get('rrf_candidates')}
        for label, paths in public.CONFIGS:
            records = {arm: [] for arm in engines}
            rounds = {arm: [] for arm in engines}
            reference, mismatches, quality = {}, [], {}
            for turn in range(args.rounds):
                order = ('scan', 'indexed') if turn % 2 == 0 else ('indexed', 'scan')
                for arm in order:
                    os.environ['MDCG_RRF_CANDIDATES'] = '1' if arm == 'indexed' else '0'
                    quality_rows = []
                    sample = []
                    for question in questions:
                        started = time.perf_counter()
                        rows, meta = engines[arm].search_rrf(question['question'], k=5,
                                                            paths=paths, judge=False, record=False)
                        ms = (time.perf_counter() - started) * 1000
                        digest = signature(rows, meta)
                        qid = question['qid']
                        if qid not in reference:
                            reference[qid] = digest
                        elif reference[qid] != digest:
                            mismatches.append({'round': turn+1, 'arm': arm, 'qid': qid})
                        sample.append(ms)
                        records[arm].append({'qid': qid, 'round': turn+1, 'ms': ms,
                                             'signature': digest, 'index': meta.get('rrf_candidates')})
                        quality_rows.append({'qid': qid, 'qtype': question['qtype'],
                                             'rank': ec.first_evidence_rank(rows, set(question['evidence_turns'])),
                                             'top1_score': rows[0][1] if rows else 0.0})
                    rounds[arm].append(sum(sample))
                    quality[arm] = ec.summarize(quality_rows)
                    print(f'public {label} round={turn+1} {arm}: {sum(sample):.1f} ms', flush=True)
            report['configs'][label] = {
                'latency': {arm: latency([r['ms'] for r in values]) for arm, values in records.items()},
                'round_ms': rounds, 'speedup_median_round': statistics.median(rounds['scan']) / statistics.median(rounds['indexed']),
                'quality': quality, 'mismatch_count': len(mismatches), 'mismatches': mismatches, 'records': records}
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        for cg in engines.values():
            cg.close()
    failed = any(c['mismatch_count'] for c in report['configs'].values())
    failed |= report['first']['scan']['signature'] != report['first']['indexed']['signature']
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
