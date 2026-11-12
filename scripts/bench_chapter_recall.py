# -*- coding: utf-8 -*-
"""章节级召回度量（对齐 dsh-memu-memory 实测口径）。

文档口径（docs/插件实测_dsh-memu-memory_检索面_v1.0.md）：
  · 指标 = 「所引章 top-1 / top-k」——用断言 query 检索，看所引章是否被召回；
  · 消融 = query 去掉「第N章「标题」」，看是否靠答案泄漏；
  · 归因 = 决定分数的是「材料里六格齐不齐、是不是同一场景」，不是字数。

本脚本对灵枢跑同一套度量（**不调用模型**，纯检索面）。
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

from bench_rubric_sut import (CCG, chapters_text, chunks_of, cn2int,  # noqa: E402
                              build_store)


def strip_chapter(stmt):
    """消融：去掉 query 里的「第N章「标题」」。"""
    return re.sub(r'第[一二三四五六七八九十\d]+章(「[^」]*」)?', '', stmt).strip(' ·')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bench', default=os.environ.get('HMB', ''))
    ap.add_argument('--k', type=int, default=5)
    ap.add_argument('--window', type=int, default=12)
    a = ap.parse_args()
    if not a.bench or not os.path.isdir(a.bench):
        print('需要 --bench 或 HMB', file=sys.stderr)
        return 2
    chunks = chunks_of(a.bench, window=a.window)
    g = build_store(chunks)
    data = json.load(open(os.path.join(a.bench, 'mcq', 'reasoning',
                                       '题目_多跳六元素_rubric92_平衡掩码.json'),
                          encoding='utf-8'))
    for label, strip in (('原 query', False), ('消融：去掉章节号', True)):
        h1 = hk = 0
        n = 0
        for q in data:
            for pt in q.get('points') or []:
                stmt = pt['stmt']
                m = re.search(r'第([一二三四五六七八九十\d]+)章', stmt)
                gold = cn2int(m.group(1)) if m else None
                if gold is None:
                    continue
                n += 1
                query = strip_chapter(stmt) if strip else stmt
                res, _meta = g.search_rrf(query, k=a.k)
                got = []
                for item in res[:a.k]:
                    mm = re.match(r'c_(\d+)', str(item[0].get('id') or ''))
                    if mm:
                        got.append(chunks[int(mm.group(1))][3])
                if gold in got:
                    hk += 1
                if got and got[0] == gold:
                    h1 += 1
        print(json.dumps({'mode': label, 'n': n, 'k': a.k, 'window': a.window,
                          'chapter_top1': round(h1 / n, 4),
                          'chapter_topk': round(hk / n, 4)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())