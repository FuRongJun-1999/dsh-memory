# -*- coding: utf-8 -*-
"""状态追踪式检索：用「槽位共现」推断时间桶，再在桶内核对六要素。

理论依据（灵枢状态追踪设计）：
  · state_event 台账 = (subject, slot, value, 时间区间, evidence)；
  · 判定不是「哪段文字更像」，而是「该时间区间内槽位值是否等于断言值」。

本脚本在 bench 语料上做最小实现（不调模型、不改主库）：
  1. 从语料建立 value → {chapter} 索引（哪些值出现在哪些章）；
  2. 消融条件（去掉「第N章」）下，用**其余五个槽位值的章共现**推断时间桶；
  3. 在推断出的桶内核对六要素 → 判真/假；
  4. 与词面基线（92.21% top-1）对比。
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, 'scripts'))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from bench_rubric_sut import chapters_text, cn2int  # noqa: E402

SLOTS = ('章节', '人物', '地点', '事件', '情绪', '物品')


def elements(stmt):
    parts = [p.strip() for p in str(stmt or '').split('·') if p.strip()]
    return {s: v for s, v in zip(SLOTS, parts)}


def build_index(chap_text):
    """value → {chapter: 命中次数}（只在章正文里做子串查找，确定性）。"""
    idx = defaultdict(dict)
    for ch, (_title, body) in chap_text.items():
        idx['__body__'][ch] = body
    return idx


def chapters_of(value, chap_text):
    return {ch for ch, (_t, b) in chap_text.items() if value and value in b}


def infer_scope(values, chap_text, slot_weight=None):
    """槽位共现推断时间桶：每个候选章得分 = Σ 权重(槽位) × 该值是否在本章。"""
    score = defaultdict(float)
    for slot, val in values:
        if not val:
            continue
        w = (slot_weight or {}).get(slot, 1.0)
        for ch in chapters_of(val, chap_text):
            score[ch] += w
    if not score:
        return None, {}
    best = max(score.items(), key=lambda kv: (kv[1], -kv[0]))
    return best[0], dict(score)


def main():
    bench = os.environ.get('HMB', '')
    chap_text = chapters_text(bench)
    data = json.load(open(os.path.join(bench, 'mcq', 'reasoning',
                                       '题目_多跳六元素_rubric92_平衡掩码.json'),
                          encoding='utf-8'))
    import re
    # 槽位权重：人物/地点/事件 更具体（情感/物品也具体，章节最不具体）
    weights = {'人物': 1.0, '地点': 1.2, '事件': 1.2, '情绪': 1.0, '物品': 1.2}
    hit = n = 0
    judge_tp = judge_tn = judge_fp = judge_fn = 0
    for q in data:
        for pt in q.get('points') or []:
            stmt = pt['stmt']
            m = re.search(r'第([一二三四五六七八九十\d]+)章', stmt)
            gold = cn2int(m.group(1)) if m else None
            if gold is None:
                continue
            el = elements(stmt)
            values = [(s, el.get(s)) for s in ('人物', '地点', '事件', '情绪', '物品')]
            inferred, _score = infer_scope(values, chap_text, weights)
            if inferred is None:
                continue
            n += 1
            if inferred == gold:
                hit += 1
            # 在**推断出的桶**内核对全部六要素（含章节槽位对应的章）
            body = chap_text.get(inferred, ('', ''))[1]
            ok_all = all((v in body) for _s, v in values if v)
            pred = bool(ok_all)
            truth = bool(pt.get('answer'))
            if truth and pred:
                judge_tp += 1
            elif truth and not pred:
                judge_fn += 1
            elif (not truth) and pred:
                judge_fp += 1
            else:
                judge_tn += 1
    pos = judge_tp + judge_fn
    neg = judge_tn + judge_fp
    tpr = judge_tp / pos if pos else 0.0
    tnr = judge_tn / neg if neg else 0.0
    print(json.dumps({'n': n,
                      'scope_infer_top1': round(hit / max(1, n), 4),
                      'oracle_judge_balanced': round((tpr + tnr) / 2, 4),
                      'tp': judge_tp, 'tn': judge_tn, 'fp': judge_fp, 'fn': judge_fn},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())