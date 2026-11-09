# -*- coding: utf-8 -*-
"""灵枢**生产检索 → 材料 → 外部判官** 端到端（统一口径用）。

与 `bench_scope_prod.py` 的区别：那个只量检索层；本脚本把 `scopeselect.pick_scopes`
选出的 top-1 / top-3 章**原文（含标题行）**装配成材料，供外部 LLM 判官判分——
即「系统自己检索出来的材料」，不是 oracle 所引章。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from md_cg import bucketindex as bi  # noqa: E402
from md_cg import scopeselect as ss  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

CCG = ('# 功能名：{n}\n# 生效条件：c\n# 子功能：s\n# 执行：e\n'
       '# 验证方式：bench\n# 不适用条件：无\n\n{body}\n')


def strip_chapter(stmt):
    return re.sub(r'第[一二三四五六七八九十\d]+章(「[^」]*」)?', '', str(stmt or '')).strip(' ·')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bench', default=os.environ.get('HMB', ''))
    ap.add_argument('--out', default='.tmp/prod_e2e')
    ap.add_argument('--topn', type=int, default=1)
    ap.add_argument('--shards', type=int, default=16)
    ap.add_argument('--strip', action='store_true', help='消融：判定前把 query 的章节号去掉')
    a = ap.parse_args()
    if not a.bench or not os.path.isdir(a.bench):
        print('需要 --bench/HMB', file=sys.stderr)
        return 2
    sys.path.insert(0, os.path.join(REPO, 'scripts'))
    from bench_rubric_sut import chapters_text, cn2int  # noqa: E402
    chap = chapters_text(a.bench)
    root = tempfile.mkdtemp(prefix='prode2e_')
    g = MdCGOS(root, actor='bench')
    for ch, (_title, body) in sorted(chap.items()):
        ts = time.mktime(time.strptime('2026-01-%02d 10:00:00' % min(28, ch),
                                       '%Y-%m-%d %H:%M:%S'))
        lines = body.splitlines()
        for i in range(0, len(lines), 12):
            seg = chr(10).join(lines[i:i + 12])
            g.add('ch%02d_%03d' % (ch, i),
                  CCG.format(n='第%d章' % ch, s='w', e=str(i), body=seg),
                  created_at=ts, session='chap_%02d' % ch)
    bi.build(g, write=True, with_content=True)
    data = json.load(open(os.path.join(a.bench, 'mcq', 'reasoning',
                                       '题目_多跳六元素_rubric92_平衡掩码.json'),
                          encoding='utf-8'))
    os.makedirs(a.out, exist_ok=True)
    rows = []
    for q in data:
        points = []
        for j, pt in enumerate(q.get('points') or []):
            m = re.search(r'第([一二三四五六七八九十\d]+)章', pt['stmt'])
            gold = cn2int(m.group(1)) if m else None
            if gold is None or gold not in chap:
                continue
            query = strip_chapter(pt['stmt']) if a.strip else pt['stmt']
            picked = ss.pick_scopes(g, query, session=None, limit=max(3, a.topn))
            days = [key for kind, key, _s in picked if kind == 'day'][:a.topn]
            pack = []
            for d in days:
                chn = int(d.split('-')[-1])
                if chn in chap:
                    title, body = chap[chn]
                    pack.append({'chapter': chn,
                                 'text': ('## ' + title + chr(10) + body)})
            points.append({'idx': j, 'stmt': pt['stmt'], 'gold': gold,
                           'picked': [int(d.split('-')[-1]) for d in days],
                           'pack': pack})
        rows.append({'qid': q['qid'], 'points': points})
    per = max(1, (len(rows) + a.shards - 1) // a.shards)
    for i in range(0, len(rows), per):
        with open(os.path.join(a.out, 'p_%02d.jsonl' % (i // per)), 'w', encoding='utf-8') as fh:
            for r in rows[i:i + per]:
                fh.write(json.dumps(r, ensure_ascii=False) + chr(10))
    n = sum(len(r['points']) for r in rows)
    hit = sum(1 for r in rows for p in r['points'] if p['gold'] in p['picked'])
    print(json.dumps({'assertions': n, 'chapter_hit_at_n': round(hit / max(1, n), 4),
                      'topn': a.topn, 'strip': a.strip,
                      'shards': (len(rows) + per - 1) // per}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())