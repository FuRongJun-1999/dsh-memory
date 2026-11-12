# -*- coding: utf-8 -*-
"""灵枢检索面 × hive-memory-bench 对照（会话内可重跑）。

两个模式：
  chapter  —— 章节型语料（bench/corpus/u01-03 → 切块 → 逐题 recall）
             指标：gold fact 的**词面二元组覆盖率** cov@1/3/5/10（同口径跨配置可比）。
  conv     —— 对话型语料（bench/e2e/corpus/*.md，按「我说：」切轮）
             指标：recent_tail 补入条数、topicagg 聚合组数与最大组规模。

⚠️ 口径边界（务必连读数一起引用）：
  · e2e-simple 的 `fact` 与随包语料**非逐字对应**（38 题仅 2 题可逐字定位），
    故只能用词面覆盖做**相对比较**，不可当准确率；
  · 对话语料**没有配套题目**，故 conv 模式只能验机制是否工作，不能算端到端准确率。

用法：
  export HMB=/path/to/hive-memory-bench        # 或 --bench 显式给
  python scripts/bench_lingshu_retrieval.py chapter \
      --configs baseline,det:tiebreak,det:window,det:replace
  python scripts/bench_lingshu_retrieval.py conv \
      --file 对话上下文续接方法.md
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

CCG = ('# 功能名：{n}\n# 生效条件：检索对照\n# 子功能：s\n# 执行：e\n'
       '# 验证方式：bench\n# 不适用条件：无\n\n{body}\n')


def norm(s):
    return re.sub(r'\s+', '', str(s or ''))


def bigrams(s):
    s = re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]', '', str(s or ''))
    return {s[i:i+2] for i in range(len(s) - 1)} if len(s) > 1 else set()


def coverage(gold, texts):
    g = bigrams(gold)
    return (len(g & bigrams(''.join(texts))) / len(g)) if g else 0.0


def chapters(bench):
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


def build_chapter(chunks):
    from md_cg.mdcos import MdCGOS
    root = tempfile.mkdtemp(prefix='bench_ch_')
    g = MdCGOS(root, actor='bench')
    for i, (cid, title, body) in enumerate(chunks):
        g.add('chunk_%03d' % i,
              CCG.format(n='%s %s' % (cid, title), s=title[:40], e=cid, body=body),
              tags=[cid, 'bench'])
    return g


def apply_cfg(cfg):
    os.environ.pop('MDCG_DET_RERANK', None)
    os.environ.pop('MDCG_DET_MODE', None)
    os.environ['MDCG_RECENT_TAIL'] = '0'
    os.environ['MDCG_TOPIC_AGG'] = '0'
    if cfg == 'baseline':
        return
    if cfg.startswith('det:'):
        os.environ['MDCG_DET_RERANK'] = '1'
        os.environ['MDCG_DET_MODE'] = cfg.split(':', 1)[1]
    elif cfg == 'recent':
        os.environ['MDCG_RECENT_TAIL'] = '6'
    elif cfg == 'topic':
        os.environ['MDCG_TOPIC_AGG'] = '1'


def run_chapter(bench, cfgs, k=10):
    qs = [x for x in json.load(open(os.path.join(bench, 'mcq', 'e2e-simple',
                                              '题目_选择题_150.json'), encoding='utf-8'))
          if x.get('material') == '蜂巢指南']
    chunks = chapters(bench)
    for cfg in cfgs:
        apply_cfg(cfg)
        g = build_chapter(chunks)
        acc = {kk: 0.0 for kk in ('cov@1', 'cov@3', 'cov@5')}
        ge = {kk: 0 for kk in ('g1', 'g3', 'g5')}
        for q in qs:
            p = g.recall(q['question'], budget_tokens=4000, k=k)
            texts = [norm(e.get('content')) for e in p.get('pack') or []]
            for n_, key in ((1, 'cov@1'), (3, 'cov@3'), (5, 'cov@5')):
                c = coverage(q.get('fact'), texts[:n_])
                acc[key] += c
                if c >= 0.6:
                    ge['g' + str(n_)] += 1
        n = len(qs)
        row = {'cfg': cfg, 'n': n, 'chunks': len(chunks)}
        row.update({kk: round(v / n, 3) for kk, v in acc.items()})
        row.update(ge)
        print(json.dumps(row, ensure_ascii=False), flush=True)


def load_turns(path, limit=200):
    text = open(path, encoding='utf-8', errors='replace').read()
    turns = []
    for i, seg in enumerate(re.split(r'\*\*我说：\*\*', text)[1:], 1):
        body = re.sub(r'^[-\s]*', '', seg.split('**我说：**')[0].strip())[:1200]
        if len(body) >= 40:
            turns.append((i, body))
        if len(turns) >= limit:
            break
    return turns


def keywords(text, k=3):
    freq = {}
    for t in re.findall(r'[\u4e00-\u9fff]{2,6}', text):
        freq[t] = freq.get(t, 0) + 1
    return [w for w, _c in sorted(freq.items(), key=lambda x: (-x[1], x[0]))[:k]]


def run_conv(bench, fname):
    from md_cg.mdcos import MdCGOS
    turns = load_turns(os.path.join(bench, 'e2e', 'corpus', fname))
    root = tempfile.mkdtemp(prefix='bench_cv_')
    g = MdCGOS(root, actor='bench')
    for idx, body in turns:
        tags = keywords(body)
        g.add('turn_%03d' % idx,
              CCG.format(n='轮%d' % idx, s=body[:30], e='turn', body=body), tags=tags)
        g.remember_event('user', body[:400], tags=tags)
    freq = {}
    for idx, body in turns:
        for w in keywords(body, k=5):
            freq.setdefault(w, []).append(idx)
    os.environ.pop('MDCG_DET_RERANK', None)
    os.environ['MDCG_RECENT_TAIL'] = '6'
    os.environ['MDCG_TOPIC_AGG'] = '1'
    for w, ids in [(x, y) for x, y in freq.items() if len(y) >= 3][:8]:
        p = g.recall(w, budget_tokens=6000, k=10)
        aggs = p.get('aggregates') or []
        print(json.dumps({'topic': w, 'gold_turns': len(ids),
                          'pack': len(p.get('pack') or []),
                          'recent_tail': (p.get('meta') or {}).get('recent_tail'),
                          'agg_groups': len(aggs),
                          'agg_max': (aggs[0]['count'] if aggs else 0)}, ensure_ascii=False),
              flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=('chapter', 'conv'))
    ap.add_argument('--bench', default=os.environ.get('HMB', ''),
                    help='hive-memory-bench 仓库根（也可用环境变量 HMB）')
    ap.add_argument('--configs', default='baseline,det:tiebreak,det:window,det:replace')
    ap.add_argument('--file', default='对话上下文续接方法.md')
    a = ap.parse_args()
    if not a.bench or not os.path.isdir(a.bench):
        print('需要 --bench 或环境变量 HMB 指向 hive-memory-bench 仓库根', file=sys.stderr)
        return 2
    if a.mode == 'chapter':
        run_chapter(a.bench, [c.strip() for c in a.configs.split(',') if c.strip()])
    else:
        run_conv(a.bench, a.file)
    return 0


if __name__ == '__main__':
    sys.exit(main())