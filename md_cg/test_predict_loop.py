# -*- coding: utf-8 -*-
"""守卫 · 预测闭环（控制论式，2026-11-17）。

使用者纠正：预测允许猜，但**不许瞎猜**——预测要基于依据，误差要能反馈、能校准。
三条判据：
  P1 无依据的预测必须被拒（瞎猜不算预测，fail-closed）
  P2 误差用概率计分：δ = (p − y)²，高置信错误罚得更重
  P3 校准可读：过度自信必须能被抓出来（gap > 0.20）
  P4 闭环可用：δ 可直接喂给 affect（情绪/信任随之变化）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import affect  # noqa: E402
from md_cg import predict_loop as pl  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def main():
    # P1 无依据拒绝
    try:
        pl.make_prediction('', '这条会过', 0.8)
        ok(False, 'P1a 无依据应被拒', '竟然通过了')
    except ValueError as e:
        ok('依据' in str(e), 'P1a 无依据拒绝并说明原因', str(e)[:60])
    try:
        pl.make_prediction(['依据'], '肯定成', 1.0)
        ok(False, 'P1b confidence=1 应被拒', '竟然通过了')
    except ValueError:
        ok(True, 'P1b confidence 必须开区间（1.0 放弃可校准性）')

    # P2 Brier 计分
    hi_hit = pl.resolve(pl.make_prediction(['x'], 'a', 0.9), True)
    hi_miss = pl.resolve(pl.make_prediction(['x'], 'b', 0.9), False)
    ok(abs(hi_hit['delta'] - 0.01) < 1e-9, 'P2a 高置信猜对 ⇒ δ=0.01', hi_hit['delta'])
    ok(abs(hi_miss['delta'] - 0.81) < 1e-9, 'P2b 高置信猜错 ⇒ δ=0.81（罚得重）', hi_miss['delta'])
    ok(hi_miss['delta'] > hi_hit['delta'], 'P2c 错的代价大于对的收益')

    # P3 校准
    recs = [{'confidence': 0.9, 'hit': i < 1} for i in range(5)]   # 说 90%，只中 1 次
    cal = pl.calibration(recs)
    ok(cal['verdict'] == 'overconfident', 'P3a 过度自信被抓出', cal)
    good = pl.calibration([{'confidence': 0.6, 'hit': i < 3} for i in range(5)])
    ok(good['verdict'] == 'calibrated', 'P3b 说 60% 中 3/5 ⇒ calibrated', good)
    ok(pl.calibration([])['verdict'] == 'insufficient', 'P3c 样本不足时不下结论')

    # P4 闭环：δ 进 affect
    s = affect.new_state(t=1000.0)
    for i, rec in enumerate([{'confidence': 0.9, 'hit': False}] * 3):
        r = pl.resolve(pl.make_prediction(['basis'], 'c', rec['confidence']), rec['hit'])
        s = affect.update(s, {'error': r['delta'], 'valence': -1.0, 't': 1001 + i * 10})
    ok(affect.labels(s)['emotion'] in ('受伤', '警惕'), 'P4a 连续猜错 ⇒ 情绪转负面', affect.labels(s))
    ok(s['scales']['just']['e'] > 0.5, 'P4b 落差进入 just 尺度', round(s['scales']['just']['e'], 3))

    print()
    print('预测闭环守卫：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())