# -*- coding: utf-8 -*-
"""预测闭环（控制论式）：预测 → 动作 → 观测 → 误差 → 修正（2026-11-17）。

使用者纠正：*「预测是允许猜的，但猜不是瞎猜，是基于控制论的方式」*。
我原来的错误是**把 δ 当成外部输入**，问「谁来给我偏差」——但控制论里偏差来自
**自己出的预测与实际观测之差**：预测在我这一侧，反馈回来的是同一个环。

三条约束：
  ① **预测必须带依据**（basis）：无依据的预测 = 瞎猜，本模块直接拒绝（fail-closed）；
  ② **误差用概率计分**（Brier）：p 是自信度，y 是实际是否发生，δ = (p − y)²，天然落 0..1；
  ③ **必须能校准**：长期统计「说的自信 vs 实际的命中」，过度自信要能被抓出来。

本模块只做计算与留痕，不写库；调用方负责把 δ 送进 affect/trust。
"""

from __future__ import annotations


def make_prediction(basis, claim, confidence):
    """构造一条预测。basis 为空 ⇒ 拒绝（瞎猜不算预测）。

    basis 可以是「依据字符串」或字符串列表：引用记忆节点 id、规则条目、上次结论等。
    confidence ∈ (0,1)：**允许不确定**，允许 0.5；但不许不给依据。
    """
    if isinstance(basis, (list, tuple)):
        items = [str(b).strip() for b in basis if str(b).strip()]
    else:
        items = [str(basis or '').strip()] if str(basis or '').strip() else []
    if not items:
        raise ValueError('预测必须带依据（basis）：无依据的猜是瞎猜，不予登记')
    c = float(confidence)
    if not (0.0 < c < 1.0):
        raise ValueError('confidence 必须在 (0,1) 开区间：0 与 1 等于放弃可校准性')
    return {'claim': str(claim or '').strip(), 'confidence': c, 'basis': items}


def resolve(prediction, happened):
    """把预测与结果比对，给出 Brier 误差 δ ∈ [0,1] 与命中判定。"""
    c = float(prediction.get('confidence'))
    y = 1.0 if happened else 0.0
    delta = (c - y) ** 2
    return {'delta': round(delta, 6), 'hit': bool(happened), 'confidence': c,
            'claim': prediction.get('claim'), 'basis': list(prediction.get('basis') or [])}


def calibration(records):
    """校准读数：平均自信 vs 实际命中率；差得越多＝越容易过度自信/过度保守。

    records: [{confidence, hit}, ...]
    返回 brier（越小越好）、mean_conf、hit_rate、gap（正=过度自信）、over/under。
    """
    rows = [r for r in (records or []) if 'confidence' in r and 'hit' in r]
    if not rows:
        return {'n': 0, 'brier': None, 'mean_conf': None, 'hit_rate': None,
                'gap': None, 'verdict': 'insufficient'}
    n = len(rows)
    mean_conf = sum(float(r['confidence']) for r in rows) / n
    hit_rate = sum(1.0 if r['hit'] else 0.0 for r in rows) / n
    brier = sum((float(r['confidence']) - (1.0 if r['hit'] else 0.0)) ** 2 for r in rows) / n
    gap = mean_conf - hit_rate
    if n < 5:
        verdict = 'insufficient'
    elif gap > 0.20:
        verdict = 'overconfident'
    elif gap < -0.20:
        verdict = 'underconfident'
    else:
        verdict = 'calibrated'
    return {'n': n, 'brier': round(brier, 4), 'mean_conf': round(mean_conf, 4),
            'hit_rate': round(hit_rate, 4), 'gap': round(gap, 4), 'verdict': verdict}


def surprise(prediction, happened):
    """惊讶度 = |p − y|（与 Brier 区分：Brier 罚高置信错误更狠，惊讶只看差距）。"""
    c = float(prediction.get('confidence'))
    return round(abs(c - (1.0 if happened else 0.0)), 6)