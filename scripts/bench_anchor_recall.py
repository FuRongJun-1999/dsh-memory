# -*- coding: utf-8 -*-
"""人物锚定 vs 章节字面：在「去掉章节号」的消融条件下测召回。

背景：修完章节解析 bug 后，灵枢所引章 top-1 在**原 query** 下已 100%；
但**消融（去掉「第N章「标题」」）**只有 92.21%——说明仍依赖章节字面。
使用者口径：改用**人物 + 时间**做锚定（章节号只是时间的一种写法）。

本脚本用确定性词面打分做对照（不调模型、不依赖 store 的排序）：
  plain       ：stmt 去掉章节号后，按 bigram 覆盖率排序
  person×2    ：同一排序，但含「人物」的块得分 ×2
  person+place：人物 ×2 且地点命中再 ×1.5
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

from bench_rubric_sut import chapters_text, chunks_of, cn2int  # noqa: E402

SLOT_ORDER = ('章节', '人物', '地点', '事件', '情绪', '物品')


def elements(stmt):
    parts = [p.strip() for p in str(stmt or '').split('·') if p.strip()]
    out = {}
    for slot, val in zip(SLOT_ORDER, parts):
        out[slot] = val
    return out


def bigrams(s):
    s = re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]', '', str(s or ''))
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else set()


def strip_chapter(stmt):
    return re.sub(r'第[一二三四五六七八九十\d]+章(「[^」]*」)?', '', stmt).strip(' ·')


def rank(query_grams, chunks, person=None, place=None,
         person_w=2.0, place_w=1.5):
    scored = []
    for idx, (a, b, body, ch) in enumerate(chunks):
        g = bigrams(body)
        if not g:
            continue
        hit = len(query_grams & g) / float(len(query_grams) or 1)
        w = 1.0
        if person and person in body:
            w *= person_w
        if place and place in body:
            w *= place_w
        scored.append((hit * w, -idx, ch))
    scored.sort(reverse=True)
    return [c for _s, _i, c in scored]


def main():
    bench = os.environ.get('HMB', '')
    chunks = chunks_of(bench)
    data = json.load(open(os.path.join(bench, 'mcq', 'reasoning',
                                       '题目_多跳六元素_rubric92_平衡掩码.json'),
                          encoding='utf-8'))
    modes = (('消融·plain', dict()),
             ('消融·人物×2', dict(person_w=2.0)),
             ('消融·人物×2+地点×1.5', dict(person_w=2.0, place_w=1.5)),
             ('原query·plain', dict(full=True)))
    for name, opts in modes:
        h1 = hk = n = 0
        for q in data:
            for pt in q.get('points') or []:
                stmt = pt['stmt']
                m = re.search(r'第([一二三四五六七八九十\d]+)章', stmt)
                gold = cn2int(m.group(1)) if m else None
                if gold is None:
                    continue
                el = elements(stmt)
                query = stmt if opts.get('full') else strip_chapter(stmt)
                qg = bigrams(query)
                if not qg:
                    continue
                n += 1
                ranked = rank(qg, chunks,
                              person=None if opts.get('full') else el.get('人物'),
                              place=None if opts.get('full') else el.get('地点'),
                              person_w=opts.get('person_w', 2.0),
                              place_w=opts.get('place_w', 1.5))
                if ranked and ranked[0] == gold:
                    h1 += 1
                # top-5 里是否出现 gold（按块去重后的前 5 个章）
                if gold in ranked[:5]:
                    hk += 1
        print(json.dumps({'mode': name, 'n': n,
                          'top1': round(h1 / max(1, n), 4),
                          'top5': round(hk / max(1, n), 4)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())