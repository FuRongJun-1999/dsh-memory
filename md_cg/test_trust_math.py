# -*- coding: utf-8 -*-
"""守卫 · 信任度计算（智能论 3.4 §2.7/§2.9 落地，2026-11-17）。

背景：这套公式写在理论里四个月，**从未进入算法**。本守卫逐条钉住理论原文的判据，
并且钉住「工程默认权重 ≠ 理论结论」这条边界。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import trust_math as tm  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def main():
    # T1 死区：小于 0.02 的误差不计
    ok(tm.u_prediction_error([0.01]) == 0.0, 'T1 死区内误差不产生代价', tm.u_prediction_error([0.01]))
    ok(tm.u_prediction_error([0.05]) > 0.0, 'T1b 超出死区即计入', tm.u_prediction_error([0.05]))

    # T2 限幅 0.3
    ok(abs(tm.u_prediction_error([1.0]) - tm.U_LIMIT) < 1e-9, 'T2 限幅=0.3（单维不得主导）',
       tm.u_prediction_error([1.0]))

    # T3 动态死区：3σ，且封顶 0.20
    ok(tm.deadzone([0.1] * 5, sigma=0.01) < tm.deadzone([0.1] * 5, sigma=0.05),
       'T3a 方差大 ⇒ 死区变大')
    ok(abs(tm.deadzone([0.1] * 5, sigma=1.0) - tm.DEADZONE_MAX) < 1e-9, 'T3b 死区封顶 0.20',
       tm.deadzone([0.1] * 5, sigma=1.0))

    # T4 P_trust 是比例
    ok(abs(tm.p_trust([0.1] * 7 + [0.3] * 3) - 0.7) < 1e-9, 'T4 P_trust=偏低比例（7/10）',
       tm.p_trust([0.1] * 7 + [0.3] * 3))

    # T5 完全可信：两维同时 ≥0.95
    ok(tm.fully_trusted(0.96, 0.96) is True, 'T5a 双高 ⇒ 完全可信')
    ok(tm.fully_trusted(0.99, 0.90) is False, 'T5b 单维独大不算完全可信（P_gap 不达标）')

    # T6 E_weight 放大 + 夹紧
    ok(abs(tm.effective(0.5, 1.0) - 0.6) < 1e-9, 'T6a η=0.2、E=1 ⇒ 0.5→0.6', tm.effective(0.5, 1.0))
    ok(tm.effective(0.95, 1.0) <= 1.0, 'T6b 放大后仍夹在 1.0 以内', tm.effective(0.95, 1.0))

    # T7 情感权重 = 信任二阶变化
    ok(abs(tm.e_weight(0.5, 0.5, 0.6) - 0.1) < 1e-9, 'T7a 匀速上升 ⇒ 二阶=0.1?（等间隔近似）',
       tm.e_weight(0.5, 0.5, 0.6))
    ok(abs(tm.e_weight(0.5, 0.6, 0.6) + 0.1) < 1e-9, 'T7b 先升后平 ⇒ 二阶 = −0.1（降速）',
       tm.e_weight(0.5, 0.6, 0.6))

    # T8 情绪方向：信息差加速收缩 ⇒ 正向
    ok(tm.emotion_signal(-0.1) > 0, 'T8a d²D<0（加速收缩）⇒ 正效价', tm.emotion_signal(-0.1))
    ok(tm.emotion_signal(0.1) < 0, 'T8b d²D>0（加速扩大）⇒ 负效价', tm.emotion_signal(0.1))

    # T9 边界：权重是工程参数，不是理论结论
    ok(tm.W_DEFAULT != (1.0 / 3, 1.0 / 3, 1.0 / 3) and abs(sum(tm.W_DEFAULT) - 1.0) < 1e-9,
       'T9a 工程默认权重和为 1 且非均匀（显式声明，可替换）', tm.W_DEFAULT)
    ok(tm.t_total([0.1] * 5, [0.05] * 5, 0.5, weights=(1.0, 0.0, 0.0)) <= 1.0,
       'T9b 替换权重后仍夹在 0..1')

    print()
    print('信任度计算守卫：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())
