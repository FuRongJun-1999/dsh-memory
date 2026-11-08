# -*- coding: utf-8 -*-
"""端到端 SUT：灵枢检索 → 组证据 → 交给作答模型 → 产出 sut/out/<qid>.json。

用法：
  python scripts/bench_sut_e2e.py prepare --bench <HMB> --out .tmp/e2e_payload.jsonl --k 6
  （然后由编排层把 payload 交给作答模型，拿回 picks.jsonl）
  python scripts/bench_sut_e2e.py grade --bench <HMB> --picks .tmp/picks.jsonl

判分口径与 bench 一致：`pick == answer` 即通过（零噪声、可复算）。

⚠️ 只喂**检索到的证据**，不喂全文、不喂答案——否则测的就不是记忆系统的读取能力。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def chapters(bench):
    import re
    out = []
    for f in ('u01.json', 'u02.json', 'u03.json'):
        p = os.path.join(bench, 'corpus', f)
        if not os.path.exists(p):
            continue
        d = json.load(open(p, encoding='utf-8'))
        for ch in d.get('chapters') or []:
            paras = [x.strip() for x in re.split(r'\n\s*\n', ch.get('text') or '') if x.strip()]
            buf = ''
            for para in paras:
                if buf and len(buf) + len(para) > 500:
                    out.append((ch['cid'], ch['title'], buf))
                    buf = para
                else:
                    buf = (buf + '\n' + para).strip() if buf else para
            if buf:
                out.append((ch['cid'], ch['title'], buf))
    return out


def questions(bench):
    p = os.path.join(bench, 'mcq', 'e2e-simple', '题目_选择题_150.json')
    items = json.load(open(p, encoding='utf-8'))
    return [x for x in items if x.get('material') == '蜂巢指南']


def prepare(bench, out_path, k):
    from md_cg.mdcos import MdCGOS
    import tempfile
    chunks = chapters(bench)
    g = MdCGOS(tempfile.mkdtemp(prefix='sut_'), actor='bench')
    ccg = ('# 功能名：{n}\n# 生效条件：语料\n# 子功能：s\n# 执行：e\n'
           '# 验证方式：bench\n# 不适用条件：无\n\n{body}\n')
    for i, (cid, title, body) in enumerate(chunks):
        g.add('chunk_%03d' % i, ccg.format(n='%s %s' % (cid, title), s=title[:40], e=cid,
                                           body=body), tags=[cid])
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    n = 0
    with open(out_path, 'w', encoding='utf-8') as fh:
        for q in questions(bench):
            p = g.recall(q['question'], budget_tokens=3000, k=k)
            ev = []
            for e in (p.get('pack') or [])[:k]:
                ev.append({'id': e.get('id'), 'cid': (e.get('frontmatter') or {}).get('tags', [None])[0],
                           'text': (e.get('content') or '')[:700]})
            fh.write(json.dumps({'qid': q['qid'], 'question': q['question'],
                                 'options': q['options'], 'evidence': ev},
                                ensure_ascii=False) + '\n')
            n += 1
    print(json.dumps({'prepared': n, 'chunks': len(chunks), 'k': k, 'out': out_path}))
    return 0


def grade(bench, picks_path):
    gold = {q['qid']: q['answer'] for q in questions(bench)}
    picks = {}
    for line in open(picks_path, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get('qid'):
            picks[d['qid']] = str(d.get('pick') or '').strip().upper()[:1]
    hit = sum(1 for qid, ans in gold.items() if picks.get(qid) == ans)
    miss = [qid for qid, ans in gold.items() if picks.get(qid) != ans]
    print(json.dumps({'n': len(gold), 'graded': len(picks), 'correct': hit,
                      'acc': round(hit / max(1, len(gold)), 4),
                      'unanswered': len([q for q in gold if not picks.get(q)]),
                      'miss_sample': miss[:6]}, ensure_ascii=False))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=('prepare', 'grade'))
    ap.add_argument('--bench', default=os.environ.get('HMB', ''))
    ap.add_argument('--out', default='.tmp/e2e_payload.jsonl')
    ap.add_argument('--picks', default='.tmp/picks.jsonl')
    ap.add_argument('--k', type=int, default=6)
    a = ap.parse_args()
    if not a.bench or not os.path.isdir(a.bench):
        print('需要 --bench 或 HMB 指向 hive-memory-bench 仓库根', file=sys.stderr)
        return 2
    return prepare(a.bench, a.out, a.k) if a.mode == 'prepare' else grade(a.bench, a.picks)


if __name__ == '__main__':
    sys.exit(main())