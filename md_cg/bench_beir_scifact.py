"""Run the full BEIR SciFact test through production MdCGOS.

python -X utf8 -m md_cg.bench_beir_scifact --data <scifact-dir> \
    --pool <new-markdown-pool> --output-dir <results-dir> \
    --beir-root <official-beir-checkout> --bm25-reference

Requires the official BEIR evaluator, pytrec-eval-terrier and tqdm. The optional
local BM25 reference also needs rank-bm25. No dataset/model download is implicit.
Use the original BEIR archive (official MD5 5f7d1de60b170fc8027bb7898e2efca1).
Results cover one official benchmark subtask, not a full leaderboard submission.
"""
import argparse
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--pool', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--beir-root', type=Path)
    parser.add_argument('--bm25-reference', action='store_true')
    args = parser.parse_args()
    REPO = Path(__file__).resolve().parents[1]
    DATA, OUT = args.data.resolve(), args.output_dir.resolve()
    OFFICIAL = args.beir_root.resolve() if args.beir_root else None
    OUT.mkdir(parents=True, exist_ok=True)
    if OFFICIAL:
        sys.path.insert(0, str(OFFICIAL))
    os.environ.update(MDCG_HOTCACHE='0', MDCG_READ_CACHE='1', MDCG_FRESHNESS='0',
                      MDCG_RETRIEVAL_PIPELINE='0', MDCG_SEMANTIC='0', MDCG_UNIFY_QUERY='0',
                      MDCG_EN_ATOMS='0',
                      DSH_HOME=str(args.pool.resolve().parent / 'beir-dsh-home'),
                      MDCG_AUX_ROOT=str(args.pool.resolve().parent / 'beir-aux'))
    from beir.datasets.data_loader import GenericDataLoader
    from beir.retrieval import evaluation as evaluation_module
    from beir.retrieval.evaluation import EvaluateRetrieval
    from . import mdcos, nodefile, mdcg
    from .bench_rrf_candidates import signature
    from .bench_fuzzy_substrings import latency
    corpus, queries, qrels = GenericDataLoader(data_folder=str(DATA)).load(split='test')
    assert len(corpus) == 5183 and len(queries) == len(qrels) == 300
    root = args.pool.resolve()
    marker = root / '_beir_fixture.json'
    corpus_hash = digest(DATA / 'corpus.jsonl')
    spec = {'corpus_sha256': corpus_hash, 'documents': len(corpus), 'format': 'title newline abstract', 'schema': 1}
    if root.exists():
        assert marker.is_file() and json.loads(marker.read_text(encoding='utf-8')) == spec
    else:
        (root / 'knowledge').mkdir(parents=True)
        # The fixture is built exclusively from the corpus, independently of qrels.
        for docid, document in corpus.items():
            assert docid.isdecimal()
            nid = 'beir_' + docid
            fm = {'id': nid, 'layer': 'knowledge', 'importance': 0.4,
                  'created_at': 1800000000.0, 'tags': []}
            text = (document.get('title') or '') + '\n' + (document.get('text') or '')
            (root / 'knowledge' / (nid + '.md')).write_text(nodefile.dumps(fm, text), encoding='utf-8')
        marker.write_text(json.dumps(spec), encoding='utf-8')
    assert len(list((root / 'knowledge').glob('*.md'))) == len(corpus)
    report = {'benchmark': 'BEIR SciFact full test', 'corpus': len(corpus), 'queries': len(queries),
              'protocol': 'full corpus, raw English queries, title+abstract, no gold leakage or eval monkeypatch',
              'paths': ['lexical', 'fuzzy'], 'judge': False, 'record': False, 'k': 100,
              'score_mode': mdcg.SCORE_MODE, 'global_cap': mdcos.GLOBAL_CAP,
              'rank_scores': 'strictly descending engine ranks; original RRF scores retained in records',
              'product_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True, encoding='utf-8').strip(),
              'product_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=REPO)),
              'official_commit': (subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=OFFICIAL, text=True, encoding='utf-8').strip() if OFFICIAL else None),
              'packages': {name: version(name) for name in ('pytrec-eval-terrier', 'tqdm', 'numpy')},
              'sha256': {name: digest(REPO / 'md_cg' / name) for name in ('mdcos.py', 'rrf_candidates.py', 'readcache.py', 'hotcache.py')},
              'dataset_sha256': {name: digest(DATA / name) for name in ('corpus.jsonl', 'queries.jsonl', 'qrels/test.tsv')},
              'evaluator_sha256': digest(Path(evaluation_module.__file__)),
              'adapter_sha256': digest(Path(__file__)), 'arms': {}}
    reference = {}
    k_values = [1, 3, 5, 10, 50, 100]
    for arm, flag in (('scan', '0'), ('indexed', '1')):
        os.environ['MDCG_RRF_CANDIDATES'] = flag
        cg = mdcos.MdCGOS(str(root))
        assert len(cg.index['nodes']) == len(corpus)
        started = time.perf_counter()
        cg.search_rrf(next(iter(queries.values())), k=100, paths=('lexical', 'fuzzy'), judge=False, record=False)
        cold_ms = (time.perf_counter() - started) * 1000
        results, records, mismatches = {}, [], []
        try:
            for index, (qid, question) in enumerate(queries.items()):
                started = time.perf_counter()
                rows, meta = cg.search_rrf(question, k=100, paths=('lexical', 'fuzzy'), judge=False, record=False)
                ms = (time.perf_counter() - started) * 1000
                sig = signature(rows, meta)
                if reference.setdefault(qid, sig) != sig:
                    mismatches.append(qid)
                ranking = []
                for rank, row in enumerate(rows, 1):
                    docid = row[0]['id'].removeprefix('beir_')
                    assert docid in corpus
                    ranking.append({'docid': docid, 'rrf_score': row[1], 'rank': rank})
                results[qid] = {row['docid']: float(len(ranking) - row['rank'] + 1) for row in ranking}
                records.append({'qid': qid, 'question': question, 'ms': ms, 'signature': sig,
                                'ranking': ranking, 'index': meta.get('rrf_candidates')})
                if (index + 1) % 25 == 0:
                    print(f'BEIR SciFact {arm}: {index+1}/300', flush=True)
            assert set(results) == set(qrels)
            ndcg, map_scores, recall, precision = EvaluateRetrieval.evaluate(qrels, results, k_values)
            mrr = EvaluateRetrieval.evaluate_custom(qrels, results, k_values, metric='mrr')
            with (OUT / f'beir-scifact-{arm}.run.trec').open('w', encoding='utf-8') as output:
                for qid, ranked in results.items():
                    for rank, (docid, score) in enumerate(ranked.items(), 1):
                        output.write(f'{qid} Q0 {docid} {rank} {score:.9f} dsh-memory-{arm}\n')
            (OUT / f'beir-scifact-{arm}-run.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
            report['arms'][arm] = {'completed': len(records), 'failed': 0, 'cold_first_ms': cold_ms,
                                   'latency': latency([r['ms'] for r in records]),
                                   'ndcg': ndcg, 'map': map_scores, 'recall': recall, 'precision': precision,
                                   'mrr': mrr, 'mismatch_count': len(mismatches), 'mismatches': mismatches,
                                   'records': records}
            (OUT / 'beir-scifact-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(arm, json.dumps({'ndcg': ndcg, 'recall': recall, 'mrr': mrr}), flush=True)
        finally:
            cg.flush()
    assert all(a['completed'] == 300 and not a['mismatches'] for a in report['arms'].values())
    print('BEIR SciFact complete: 600 queries, 0 errors, 0 mismatches', flush=True)
    if not args.bm25_reference:
        return
    from rank_bm25 import BM25Okapi
    # A local reference, not a reproduction of the paper's Anserini BM25 row.
    # It uses exactly the same complete corpus, queries, and official qrels.
    tokenize = lambda text: re.findall(r'[a-z0-9]+', text.lower())
    docids = list(corpus)
    bm25 = BM25Okapi([tokenize((d.get('title') or '') + '\n' + (d.get('text') or ''))
                      for d in corpus.values()], k1=1.5, b=0.75, epsilon=0.25)
    reference_results, reference_records = {}, []
    for qid, question in queries.items():
        started = time.perf_counter()
        scores = bm25.get_scores(tokenize(question))
        ranked = sorted(zip(docids, scores), key=lambda row: (-row[1], row[0]))[:100]
        reference_results[qid] = {docid: float(len(ranked) - rank)
                                  for rank, (docid, _) in enumerate(ranked)}
        reference_records.append({'qid': qid, 'ms': (time.perf_counter() - started) * 1000,
                                  'ranking': [{'docid': d, 'bm25_score': float(s)} for d, s in ranked]})
    ndcg, map_scores, recall, precision = EvaluateRetrieval.evaluate(qrels, reference_results, k_values)
    mrr = EvaluateRetrieval.evaluate_custom(qrels, reference_results, k_values, metric='mrr')
    report['local_bm25_reference'] = {'library': 'rank-bm25', 'version': version('rank-bm25'),
                                     'tokenizer': 'lowercase regex [a-z0-9]+; no stemming or stopword removal',
                                     'parameters': {'k1': 1.5, 'b': 0.75, 'epsilon': 0.25},
                                     'limits': 'local comparison only, not the official Anserini BM25 implementation; timing excludes Markdown I/O',
                                     'completed': 300, 'failed': 0, 'ndcg': ndcg, 'map': map_scores,
                                     'recall': recall, 'precision': precision, 'mrr': mrr,
                                     'records': reference_records}
    with (OUT / 'beir-scifact-bm25.run.trec').open('w', encoding='utf-8') as output:
        for qid, ranked in reference_results.items():
            for rank, (docid, score) in enumerate(ranked.items(), 1):
                output.write(f'{qid} Q0 {docid} {rank} {score:.9f} local-bm25\n')
    (OUT / 'beir-scifact-bm25-run.json').write_text(json.dumps(reference_results, indent=2), encoding='utf-8')
    (OUT / 'beir-scifact-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Local BM25 reference', json.dumps({'ndcg': ndcg, 'recall': recall, 'mrr': mrr}), flush=True)


if __name__ == '__main__':
    main()
