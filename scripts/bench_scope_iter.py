# -*- coding: utf-8 -*-
"""状态追踪式范围选择的迭代实验（纯确定性，无模型）。

对照组（消融条件：去掉「第N章」）：
  lex         词面 bigram 覆盖率排序（现有基线）
  cooc        槽位共现投票（plain）
  cooc_rare   共现投票 + 丢弃「出现在 >50% 章」的弱区分值
  cooc_margin 共现投票；若 top1 与 top2 同分则回退词面
  hybrid      0.5×归一化共现 + 0.5×归一化词面
另报「原 query」下各法表现，确认加了章节号不会变差。
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'scripts'))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from bench_rubric_sut import chapters_text, chunks_of, cn2int  # noqa: E402

SLOTS = ('章节', '人物', '地点', '事件', '情绪', '物品')


def elements(stmt):
    parts = [p.strip() for p in str(stmt or '').split('·') if p.strip()]
    return {s: v for s, v in zip(SLOTS, parts)}


def bigrams(s):
    s = re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]', '', str(s or ''))
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else set()


def strip_chapter(stmt):
    return re.sub(r'第[一二三四五六七八九十\d]+章(「[^」]*」)?', '', stmt).strip(' ·')


def chap_of_value(value, chap_text):
    return {ch for ch, (_t, b) in chap_text.items() if value and value in b}


def lexical_rank(query, chap_text):
    qg = bigrams(query)
    if not qg:
        return []
    scored = []
    for ch, (_t, body) in chap_text.items():
        g = bigrams(body)
        scored.append((len(qg & g) / float(len(qg)), -ch, ch))
    scored.sort(reverse=True)
    return [c for _s, _i, c in scored]


def cooc_scores(vals, chap_text, drop_weak=False):
    total = len(chap_text)
    score = defaultdict(float)
    for _slot, val in vals:
        if not val:
            continue
        chs = chap_of_value(val, chap_text)
        if not chs:
            continue
        if drop_weak and len(chs) > total * 0.5:
            continue          # 过半章都有的值不具区分度
        for ch in chs:
            score[ch] += 1.0
    return dict(score)


def pick(score, fallback_rank=None, margin=False):
    if not score:
        return (fallback_rank[0] if fallback_rank else None)
    ranked = sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))
    if margin and len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return (fallback_rank[0] if fallback_rank else ranked[0][0])
    return ranked[0][0]


def main():
    bench = os.environ.get('HMB', '')
    chap_text = chapters_text(bench)
    data = json.load(open(os.path.join(bench, 'mcq', 'reasoning',
                                       '题目_多跳六元素_rubric92_平衡掩码.json'),
                          encoding='utf-8'))
    rows = []
    for q in data:
        for pt in q.get('points') or []:
            m = re.search(r'第([一二三四五六七八九十\d]+)章', pt['stmt'])
            gold = cn2int(m.group(1)) if m else None
            if gold is None:
                continue
            rows.append((pt['stmt'], gold))
    modes = ('lex', 'cooc', 'cooc_rare', 'cooc_margin', 'hybrid')
    for cond in ('消融', '原query'):
        for mode in modes:
            hit = 0
            n = 0
            for stmt, gold in rows:
                query = stmt if cond == '原query' else strip_chapter(stmt)
                el = elements(stmt)
                vals = [(s, el.get(s)) for s in ('人物', '地点', '事件', '情绪', '物品')]
                lex = lexical_rank(query, chap_text)
                if mode == 'lex':
                    pred = lex[0] if lex else None
                else:
                    sc = cooc_scores(vals, chap_text, drop_weak=(mode == 'cooc_rare'))
                    if mode == 'hybrid':
                        total = max(1, len(chap_text))
                        words = {c: bigrams(b) for c, (_t, b) in chap_text.items()}
                        qg = bigrams(query)
                        sc2 = defaultdict(float)
                        for ch, g in words.items():
                            sc2[ch] = 0.5 * (len(qg & g) / float(len(qg) or 1)) + \
                                       0.5 * (sc.get(ch, 0.0) / 5.0)
                        pred = pick(dict(sc2), lex)
                    else:
                        pred = pick(sc, lex, margin=(mode == 'cooc_margin'))
                n += 1
                if pred == gold:
                    hit += 1
            print(json.dumps({'cond': cond, 'mode': mode, 'n': n,
                              'top1': round(hit / max(1, n), 4)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())