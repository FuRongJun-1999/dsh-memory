# -*- coding: utf-8 -*-
"""用**生产模块**（md_cg.scopeselect）在 bench 上量章节召回——消除「两套实现」。

做法：每章切 12 行块灌进临时库，`created_at` 设为「一章 = 一天」（章节即时间桶），
再调 `scopeselect.pick_scopes(query)`，看首个被选中的日桶是否等于所引章。

已知口径差（本脚本就是为了量它）：bench 版 `bench_state_track.py` 用**子串包含**判共现，
而生产桶词表的 token 是**整句片段**、匹配是**整词精确**——两者读数不可直接互换。
"""
from __future__ import annotations

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
    bench = os.environ.get('HMB', '')
    if not bench or not os.path.isdir(bench):
        print('需要 HMB', file=sys.stderr)
        return 2
    sys.path.insert(0, os.path.join(REPO, 'scripts'))
    from bench_rubric_sut import chapters_text, cn2int  # noqa: E402
    chap = chapters_text(bench)
    root = tempfile.mkdtemp(prefix='scopeprod_')
    g = MdCGOS(root, actor='bench')
    for ch, (_title, body) in sorted(chap.items()):
        ts = time.mktime(time.strptime('2026-01-%02d 10:00:00' % min(28, ch), '%Y-%m-%d %H:%M:%S'))
        lines = body.splitlines()
        for i in range(0, len(lines), 12):
            seg = chr(10).join(lines[i:i + 12])
            g.add('ch%02d_%03d' % (ch, i), CCG.format(n='第%d章' % ch, s='w', e='%d' % i, body=seg),
                  created_at=ts, session='chap_%02d' % ch)
    info = bi.build(g, write=True, with_content=True)
    data = json.load(open(os.path.join(bench, 'mcq', 'reasoning',
                                       '题目_多跳六元素_rubric92_平衡掩码.json'),
                          encoding='utf-8'))
    for cond in ('原query', '消融'):
        hit = n = 0
        for q in data:
            for pt in q.get('points') or []:
                m = re.search(r'第([一二三四五六七八九十\d]+)章', pt['stmt'])
                gold = cn2int(m.group(1)) if m else None
                if gold is None or gold not in chap:
                    continue
                n += 1
                query = pt['stmt'] if cond == '原query' else strip_chapter(pt['stmt'])
                picked = ss.pick_scopes(g, query, session=None, limit=3)
                want = '2026-01-%02d' % min(28, gold)
                days = [key for kind, key, _s in picked if kind == 'day']
                if days and days[0] == want:
                    hit += 1
        print(json.dumps({'cond': cond, 'n': n, 'top1': round(hit / max(1, n), 4),
                          'cooc': os.environ.get('MDCG_SCOPESEL_COOC', '0'),
                          'nodes': info.get('nodes')}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())