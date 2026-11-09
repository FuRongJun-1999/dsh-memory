# -*- coding: utf-8 -*-
"""漏检归因：灵枢为什么漏掉 5% 的所引章（对齐 memu 口径后逐条挖）。

核心假设：六元素断言里，假题的「错元素」本身就在**别的章**——
所以词面检索天然会偏向那个「错元素所在的章」，而不是题面声明的章。

本脚本量化：漏检时 top-1 是哪个章？它是不是「错元素所在章」？
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'scripts'))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from bench_rubric_sut import chapters_text, chunks_of, cn2int, build_store  # noqa: E402


def main():
    bench = os.environ.get('HMB', '')
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    chunks = chunks_of(bench)
    g = build_store(chunks)
    chap_text = chapters_text(bench)
    data = json.load(open(os.path.join(bench, 'mcq', 'reasoning',
                                       '题目_多跳六元素_rubric92_平衡掩码.json'),
                          encoding='utf-8'))
    stats = {'total': 0, 'hit': 0, 'miss': 0,
             'miss_top1_is_odd_chapter': 0, 'miss_odd_in_pack': 0,
             'true_stmt_miss': 0, 'false_stmt_miss': 0}
    samples = []
    for q in data:
        for pt in q.get('points') or []:
            stmt = pt['stmt']
            m = re.search(r'第([一二三四五六七八九十\d]+)章', stmt)
            gold = cn2int(m.group(1)) if m else None
            if gold is None:
                continue
            stats['total'] += 1
            # 错元素：required 里在 gold 章找不到的那个槽
            req = ((pt.get('rubric') or {}).get('required') or [])
            odd = []
            for slot in req:
                val = str(slot.get('value') or '')
                if not val:
                    continue
                in_gold = gold in chap_text and val in chap_text[gold][1]
                if not in_gold:
                    where = [c for c, (_t, b) in chap_text.items() if val in b]
                    if where:
                        odd.append((val, where))
            res, _meta = g.search_rrf(stmt, k=k)
            got = []
            for item in res[:k]:
                mm = re.match(r'c_(\d+)', str(item[0].get('id') or ''))
                if mm:
                    got.append(chunks[int(mm.group(1))][3])
            if gold in got:
                stats['hit'] += 1
                continue
            stats['miss'] += 1
            if pt.get('answer'):
                stats['true_stmt_miss'] += 1
            else:
                stats['false_stmt_miss'] += 1
            top1 = got[0] if got else None
            odd_chaps = {c for _v, ws in odd for c in ws}
            if top1 in odd_chaps:
                stats['miss_top1_is_odd_chapter'] += 1
            if odd_chaps & set(got):
                stats['miss_odd_in_pack'] += 1
            if len(samples) < 8:
                samples.append({'stmt': stmt[:70], 'gold': gold, 'top1': top1,
                                'odd_chapters': sorted(odd_chaps)[:5],
                                'answer': pt.get('answer')})
    stats['miss_rate'] = round(stats['miss'] / max(1, stats['total']), 4)
    print(json.dumps(stats, ensure_ascii=False))
    for s in samples:
        print(json.dumps(s, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())