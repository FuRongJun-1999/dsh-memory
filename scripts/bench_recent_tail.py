# -*- coding: utf-8 -*-
"""recent_tail 的可量化读数：**「最近轮次尚未入库」时还能不能捞到**。

设计（确定性、不用模型）：
  · 语料：bench/e2e/corpus 的真实长期对话（按「我说：」切轮）；
  · 把**除最后 N 轮外**的所有轮次写进库（nodes）；最后 N 轮**只写事件窗口**（recent_events），
    模拟真实情形：刚说过的话还没沉淀成记忆节点；
  · 对最后 N 轮的每一轮，用它的特征词造查询，看该轮文本是否出现在 pack 里；
  · 对比 MDCG_RECENT_TAIL=0 / 6。

读数口径：needle_recall@pack（该轮被捞回的比例）。
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile

sys.path.insert(0, REPO := os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

CCG = ('# 功能名：{n}\n# 生效条件：对话\n# 子功能：s\n# 执行：e\n'
       '# 验证方式：bench\n# 不适用条件：无\n\n{body}\n')
RECENT = 6


def load_turns(path, limit=120):
    text = open(path, encoding='utf-8', errors='replace').read()
    out = []
    for i, seg in enumerate(re.split(r'\*\*我说：\*\*', text)[1:], 1):
        body = re.sub(r'^[-\s]*', '', seg.split('**我说：**')[0].strip())[:1200]
        if len(body) >= 80:
            out.append((i, body))
        if len(out) >= limit:
            break
    return out


def keywords(text, k=4):
    freq = {}
    for t in re.findall(r'[\u4e00-\u9fff]{2,6}', text):
        freq[t] = freq.get(t, 0) + 1
    return [w for w, _c in sorted(freq.items(), key=lambda x: (-x[1], x[0]))[:k]]


def build(old_turns, needles):
    from md_cg.mdcos import MdCGOS
    g = MdCGOS(tempfile.mkdtemp(prefix='tail_'), actor='bench')
    for idx, body in old_turns:
        g.add('turn_%03d' % idx, CCG.format(n='轮%d' % idx, s=body[:30], e='turn', body=body),
              tags=keywords(body, 3))
    for idx, body in needles:
        g.remember_event('user', body, tags=keywords(body, 3))
    return g


def run(bench, tail):
    os.environ['MDCG_RECENT_TAIL'] = str(tail)
    os.environ['MDCG_TOPIC_AGG'] = '0'
    os.environ.pop('MDCG_DET_RERANK', None)
    turns = load_turns(os.path.join(bench, 'e2e', 'corpus', '对话上下文续接方法.md'))
    needles = turns[-RECENT:]
    old = turns[:-RECENT]
    g = build(old, needles)
    hit = 0
    for idx, body in needles:
        q = ' '.join(keywords(body, 3))
        p = g.recall(q, budget_tokens=6000, k=10)
        blob = '\n'.join(str(e.get('content') or '') for e in (p.get('pack') or []))
        if body[:60] in blob:
            hit += 1
    return {'recent_tail': tail, 'needles': len(needles), 'hit': hit,
            'needle_recall': round(hit / max(1, len(needles)), 3)}


def main():
    bench = os.environ.get('HMB', '')
    if not bench or not os.path.isdir(bench):
        print('需要 HMB 指向 hive-memory-bench 仓库根', file=sys.stderr)
        return 2
    tails = [int(x) for x in (os.environ.get('TAILS') or '0,6').split(',') if x.strip()]
    for tail in tails:
        print(json.dumps(run(bench, tail), ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())