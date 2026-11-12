"""Read current algorithms with synthetic SQLite/graph fixtures; no real memory.

python -X utf8 -m md_cg.probe_memory_rsi --out /new/probe-directory
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    os.environ.update(WB_MD_DIRECT='0', WB_MD_ROOT=str(out / 'empty-md'),
                      MDCG_AUX_ROOT=str(out / 'auxiliary'), MDCG_STATE_ROOT=str(out / 'state'),
                      MDCG_ROOT=str(out / 'unused-default'), DSH_HOME=str(out / 'dsh'),
                      MDCG_FRESHNESS='0')
    wisdom = Path(__file__).resolve().parent / 'whitebox_kb' / 'wisdom'
    sys.path.insert(0, str(wisdom))
    from csre import Csre
    from neural_retrieve import NeuralRetriever
    from .mdcos import MdCGOS, RRF_K
    from .memory_rsi import create_sandbox

    def card(name, conditions, negatives=()):
        return {'name': name, 'domain': 'synthetic-domain',
                'comment': {'生效条件': conditions, '不适用条件': list(negatives)}}

    def database(path, nid, value):
        with contextlib.closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE nodes(id TEXT PRIMARY KEY, content TEXT, state_attributes TEXT, tags TEXT)')
            db.execute('INSERT INTO nodes VALUES(?,?,?,?)',
                       (nid, '合成审计卡', json.dumps(value, ensure_ascii=False), 'knowledge_point'))
            db.commit()

    db, index = out / 'a.db', out / 'a.npz'
    initial = card('合成甲卡', ['问测试条件甲'], ['问生产环境'])
    database(db, 'card-a', initial)
    engine = Csre(str(db), index_path=str(index))
    engine.build_index()
    negative = {'hits': engine.negative_hit(initial['comment'], '生产环境 测试条件甲'),
                'neg_gate': 1,
                'returned': engine.top_units_in_domain('synthetic-domain', '生产环境 测试条件甲',
                                                       neg_terms=['生产环境'], neg_gate=1)}
    engine.save_index()
    with contextlib.closing(sqlite3.connect(db)) as connection:
        connection.execute('UPDATE nodes SET state_attributes=?',
                           (json.dumps(card('更新甲卡', ['问更新条件乙']), ensure_ascii=False),))
        connection.commit()
    stale = Csre(str(db), index_path=str(index))
    stale_loaded = stale.ensure_loaded()
    rebuilt = Csre(str(db), index_path=str(out / 'fresh.npz'))
    rebuilt.build_index()
    database(out / 'b.db', 'card-b', card('乙库卡', ['问乙库条件丙']))
    cross = Csre(str(out / 'b.db'), index_path=str(index))
    cross_loaded = cross.ensure_loaded()
    neural = NeuralRetriever()
    neural_loaded = neural.load_index(npz_path=str(out / 'missing-neural.npz'),
                                     meta_path=str(out / 'missing-neural.json'))
    cg = MdCGOS(str(create_sandbox(out / 'rrf')))
    try:
        for nid in ('z', 'a', 'm'):
            cg.add(nid, 'Quartz configuration repair', verification_basis='data', importance=.5)
        weights = {'lexical': 2.0, 'bucket': .5, 'entity': 1.5, 'graph': .25}
        rows, meta = cg.search_rrf('Quartz configuration', k=3,
                                   paths=tuple(weights), path_weights=weights, judge=False)
        errors = [abs(score - sum(weights[p['path']] / (RRF_K + p['rank']) for p in prov))
                  for _, score, _, prov in rows]
        rrf = {'ids': [r[0]['id'] for r in rows], 'recomputed_max_absolute_error': max(errors, default=0),
               'source_of_formula': 'mdcos.search_rrf', 'weights': weights}
    finally:
        cg.close()
    result = {'csre_negative_gate': negative,
              'csre_freshness': {'loaded': stale_loaded, 'loaded_vocab': list(stale.vocab or []),
                                 'rebuilt_vocab': list(rebuilt.vocab), 'index_info': stale.index_info()},
              'csre_cross_database': {'loaded': cross_loaded, 'loaded_ids': list(cross.unit_ids or []),
                                      'index_info': cross.index_info()},
              'neural_missing_index': {'loaded': neural_loaded, 'last_failure': neural.last_failure()},
              'rrf': rrf,
              'source_sha256': {name: hashlib.sha256((wisdom / name).read_bytes()).hexdigest()
                                for name in ('csre.py', 'neural_retrieve.py')},
              'scope': 'synthetic API probes; no production corpus or Agent success claim'}
    (out / 'audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
