# -*- coding: utf-8 -*-
"""章节召回分路径对照（对齐 memu 口径）：原 query vs 消融，不同检索路径。"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from bench_rubric_sut import chapters_text, chunks_of, cn2int, build_store  # noqa: E402


def strip_chapter(stmt):
    return re.sub(r'第[一二三四五六七八九十\d]+章(「[^」]*」)?', '', stmt).strip(' ·')


def main():
    bench = os.environ.get('HMB', '')
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    chunks = chunks_of(bench)
    g = build_store(chunks)
    data = json.load(open(os.path.join(bench, 'mcq', 'reasoning',
                                       '题目_多跳六元素_rubric92_平衡掩码.json'),
                          encoding='utf-8'))
    pathsets = [('默认（全路）', None),
                ('仅 bm25', ('bm25',)),
                ('bm25+entity', ('bm25', 'entity')),
                ('lexical+bm25', ('lexical', 'bm25'))]
    for label, paths in pathsets:
        for cond in ('原query', '消融'):
            h1 = hk = n = 0
            for q in data:
                for pt in q.get('points') or []:
                    stmt = pt['stmt']
                    m = re.search(r'第([一二三四五六七八九十\d]+)章', stmt)
                    gold = cn2int(m.group(1)) if m else None
                    if gold is None:
                        continue
                    n += 1
                    query = stmt if cond == '原query' else strip_chapter(stmt)
                    kw = {'k': k}
                    if paths is not None:
                        kw['paths'] = paths
                    res, _meta = g.search_rrf(query, **kw)
                    got = []
                    for item in res[:k]:
                        mm = re.match(r'c_(\d+)', str(item[0].get('id') or ''))
                        if mm:
                            got.append(chunks[int(mm.group(1))][3])
                    if gold in got:
                        hk += 1
                    if got and got[0] == gold:
                        h1 += 1
            print(json.dumps({'path': label, 'cond': cond, 'n': n,
                              'top1': round(h1 / max(1, n), 4),
                              'topk': round(hk / max(1, n), 4)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())