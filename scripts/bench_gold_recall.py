# -*- coding: utf-8 -*-
"""六元素判断题（476）的真·gold 召回度量。

与前几个 harness 的根本区别：这里的 gold 是**行号**（evidence: L229 / L153、L173、L215），
所以能直接量「检索有没有把证据行捞进 top-k」，不再用词面覆盖做代理。

用法：python scripts/bench_gold_recall.py --bench <HMB> --k 10 [--configs baseline,chapter]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

CCG = ('# 功能名：{n}\n# 生效条件：语料\n# 子功能：s\n# 执行：e\n'
       '# 验证方式：bench\n# 不适用条件：无\n\n{body}\n')


def load_corpus(bench, max_lines=12):
    """把语料按**行窗**切块，保留行号区间；块不跨章。"""
    path = os.path.join(bench, 'corpus', '语料.md')
    lines = open(path, encoding='utf-8').read().splitlines()
    chunks = []
    cur, start = [], None
    for i, ln in enumerate(lines, 1):
        if ln.startswith('## ') and cur:
            chunks.append((start, i - 1, '\n'.join(cur)))
            cur, start = [], None
        if start is None:
            start = i
        cur.append(ln)
        if len(cur) >= max_lines:
            chunks.append((start, i, '\n'.join(cur)))
            cur, start = [], None
    if cur:
        chunks.append((start, len(lines), '\n'.join(cur)))
    return chunks


def gold_lines(ev):
    return [int(x) for x in re.findall(r'L(\d+)', str(ev or ''))]


def build(chunks):
    from md_cg.mdcos import MdCGOS
    g = MdCGOS(tempfile.mkdtemp(prefix='gold_'), actor='bench')
    for i, (a, b, body) in enumerate(chunks):
        g.add('c_%04d' % i, CCG.format(n='L%d-L%d' % (a, b), s='line-window', e='%d-%d' % (a, b), body=body),
              tags=['L%d' % a, 'L%d' % b])
    return g


def run(bench, configs, k=10):
    chunks = load_corpus(bench)
    qs = json.load(open(os.path.join(bench, 'mcq', 'reasoning', '题目_六元素判断题_476.json'),
                        encoding='utf-8'))['questions']
    for cfg in configs:
        os.environ.pop('MDCG_DET_RERANK', None)
        os.environ['MDCG_RECENT_TAIL'] = '0'
        os.environ['MDCG_TOPIC_AGG'] = '0'
        g = build(chunks)
        hit1 = hit3 = hitk = 0
        for q in qs:
            res, _meta = g.search_rrf(q['stmt'], k=k)
            ids = []
            for item in res[:k]:
                nid = item[0].get('id') or ''
                m = re.match(r'c_(\d+)', str(nid))
                if m:
                    a, b, _body = chunks[int(m.group(1))]
                    ids.append((a, b))
            gold = gold_lines(q.get('evidence'))
            pos = None
            for i, (a, b) in enumerate(ids):
                if any(a <= gl <= b for gl in gold):
                    pos = i + 1
                    break
            if pos:
                hitk += 1
                if pos <= 1:
                    hit1 += 1
                if pos <= 3:
                    hit3 += 1
        n = len(qs)
        print(json.dumps({'cfg': cfg, 'n': n, 'chunks': len(chunks),
                          'gold_recall@1': round(hit1 / n, 4),
                          'gold_recall@3': round(hit3 / n, 4),
                          'gold_recall@%d' % k: round(hitk / n, 4)}, ensure_ascii=False), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bench', default=os.environ.get('HMB', ''))
    ap.add_argument('--k', type=int, default=10)
    ap.add_argument('--configs', default='baseline')
    a = ap.parse_args()
    if not a.bench or not os.path.isdir(a.bench):
        print('需要 --bench 或 HMB 指向 hive-memory-bench 仓库根', file=sys.stderr)
        return 2
    run(a.bench, [c.strip() for c in a.configs.split(',') if c.strip()], a.k)
    return 0


if __name__ == '__main__':
    sys.exit(main())