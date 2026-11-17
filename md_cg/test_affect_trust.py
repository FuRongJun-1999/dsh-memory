# -*- coding: utf-8 -*-
"""守卫 · 理论信任接入 affect（2026-11-17）：信任由 δ_norm / D_norm 驱动，情绪误差不驱动。

理论：智能论 3.4 §2.9（T_total = f(P_trust, T_pred, T_context)；E_weight = d²T/dt²）。
工程：窗口 N=TRUST_WINDOW（可微调）；权重是工程默认值，不是理论结论。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import affect  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def run(seq, t0=1000.0):
    s = affect.new_state(t=t0)
    for i, obs in enumerate(seq):
        s = affect.update(s, dict(obs, t=t0 + 10 * (i + 1)))
    return s


def main():
    # A1 无 delta/gap ⇒ 不产出理论信任字段（不让 error 驱动信任）
    plain = run([{'error': 0.8, 'valence': -0.8}])
    ok('p_trust' not in plain, 'A1 只给情绪误差时不产出 p_trust（分离原则）', list(plain.keys()))

    # A2 持续小偏差 ⇒ P_trust 高、T 上升
    good = run([{'delta': 0.02, 'gap': 0.03}] * 6)
    ok(good['p_trust'] >= 0.99, 'A2a 持续小偏差 ⇒ P_trust≈1', good['p_trust'])
    ok(good['t_ext'] > 0.9, 'A2b 信任上升到 0.9 以上', round(good['t_ext'], 3))
    ok(good['fully_trusted'] is True, 'A2c 双维达标 ⇒ 完全可信', (good['p_trust'], good['p_gap']))

    # A3 大偏差 ⇒ P_trust 掉、T 下降
    bad = run([{'delta': 0.40, 'gap': 0.30}] * 6)
    ok(bad['p_trust'] <= 0.01, 'A3a 大偏差 ⇒ P_trust≈0', bad['p_trust'])
    ok(bad['t_ext'] < good['t_ext'], 'A3b 大偏差时信任低于小偏差时', (round(bad['t_ext'], 3), round(good['t_ext'], 3)))
    ok(bad['fully_trusted'] is False, 'A3c 不达标 ⇒ 非完全可信')

    # A4 单维独大不算完全可信（P_trust 高但 gap 差）
    lopsided = run([{'delta': 0.02, 'gap': 0.30}] * 6)
    ok(lopsided['p_trust'] >= 0.99 and (lopsided['p_gap'] or 0) <= 0.01,
       'A4a 构造单维独大', (lopsided['p_trust'], lopsided['p_gap']))
    ok(lopsided['fully_trusted'] is False, 'A4b P_gap 不达标 ⇒ 不算完全可信')

    # A5 E_weight 是二阶变化：信任上升后趋平 ⇒ 负
    ramp = affect.new_state(t=1000.0)
    hist = []
    for i, d in enumerate([0.01, 0.01, 0.01, 0.40, 0.40, 0.40]):
        ramp = affect.update(ramp, {'delta': d, 'gap': 0.02, 't': 1001 + i * 10})
        hist.append(ramp['t_ext'])
    ok('e_weight' in ramp, 'A5a 三次以上观测后产出 e_weight', ramp.get('e_weight'))
    # E_weight 是**二阶**变化：下降时若降速放缓，二阶为正——这是公式本身，不是错误。
    ok(ramp['t_hist'][-1] < ramp['t_hist'][-2], 'A5b 大偏差后信任在下降',
       [round(x, 4) for x in ramp['t_hist']])
    from md_cg import trust_math as tm
    ok(abs(ramp['e_weight'] - tm.e_weight(*ramp['t_hist'][-3:])) < 1e-6,
       'A5c e_weight 与 trust_math.e_weight 复算一致（单一真源）', ramp['e_weight'])

    # A6 窗口上限
    many = run([{'delta': 0.02, 'gap': 0.02}] * (affect.TRUST_WINDOW + 8))
    ok(len(many['deltas']) == affect.TRUST_WINDOW, 'A6 窗口按 TRUST_WINDOW 截断',
       len(many['deltas']))

    # A7 原有守卫不被破坏：误差尖峰仍不带动信任
    spike = run([{'error': 0.9, 'valence': -0.9}, {'error': 0.9, 'valence': -0.9}])
    ok(abs(spike['dt_ext']) < 1e-9 and abs(spike['t_ext'] - 0.5) < 1e-9,
       'A7 情绪误差不动信任（回归 N2a）', (spike['t_ext'], spike['dt_ext']))

    print()
    print('理论信任接入守卫：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())
