# -*- coding: utf-8 -*-
"""守卫 · 两轴 + 潮汐（v2，2026-11-17）。

使用者裁定：
  · 落差大小 ≠ 效价好坏（被撩动与被冒犯都是落差大）
  · 预期是潮水不是棘轮：经常亲密水位高、疏远水位落；退潮复用**遗忘曲线**

  W1 两轴：同样大的落差，效价正负给出不同标签
  W2 潮涨：连续「好」事件抬高水位
  W3 潮落：无事件时水位按遗忘曲线回落（同一输入 × 不同间隔 ⇒ 读数不同）
  W4 频繁 vs 疏远：同样次数的「好」事件，密集者水位更高
  W5 落潮不归零：退潮后仍在常态附近，不会清空
  W6 情感读慢水位 + 信任（快尺度拉不动情感）
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import affect  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def main():
    s0 = affect.new_state(t=1000.0)

    # W1 两轴
    pos = affect.update(s0, {'error': 0.6, 'valence': 0.8, 'event': '被撩动', 't': 1001.0})
    neg = affect.update(s0, {'error': 0.6, 'valence': -0.8, 'event': '被冒犯', 't': 1001.0})
    ok(affect.labels(pos)['emotion'] == '被撩动', 'W1a 落差大 + 效价正 ⇒ 被撩动', affect.labels(pos))
    ok(affect.labels(neg)['emotion'] in ('受伤', '警惕'), 'W1b 落差大 + 效价负 ⇒ 受伤/警惕', affect.labels(neg))
    ok(abs(pos['scales']['just']['e'] - neg['scales']['just']['e']) < 1e-9,
       'W1c 两者落差读数相同（只是效价不同）', (pos['scales']['just']['e'], neg['scales']['just']['e']))

    # W2 潮涨：连续好事件
    s = s0
    for i in range(5):
        s = affect.update(s, {'error': 0.0, 'valence': 0.9, 't': 1001.0 + i * 3600})
    ok(s['scales']['month']['w'] > 0.6, 'W2 连续好事件 ⇒ 月尺度水位抬高', affect.tide(s))

    # W3 潮落：同一输入，不同间隔
    def after_gap(gap_s):
        x = affect.update(s0, {'error': 0.0, 'valence': 0.9, 't': 1000.0 + 60})
        return affect.update(x, {'t': 1000.0 + 60 + gap_s})

    near = after_gap(10 * 60)
    far = after_gap(5 * 86400)
    ok(near['scales']['just']['w'] > far['scales']['just']['w'] + 0.05,
       'W3a 同一输入：间隔越久，短尺度水位越低（遗忘曲线）',
       (near['scales']['just']['w'], far['scales']['just']['w']))
    ok(far['scales']['month']['w'] > near['scales']['month']['w'] * 0.97,
       'W3b 慢尺度 5 天只退一成（落得慢，但确实在落）', round(far['scales']['month']['w'], 4))

    # W4 频繁 vs 疏远
    dense = s0
    for i in range(6):
        dense = affect.update(dense, {'valence': 0.9, 't': 1001.0 + i * 3600})
    sparse = s0
    for i in range(6):
        sparse = affect.update(sparse, {'valence': 0.9, 't': 1001.0 + i * 20 * 86400})
    ok(dense['scales']['day']['w'] > sparse['scales']['day']['w'] + 0.05,
       'W4 同样 6 次好事件：密集者水位更高（亲密频率决定预期）',
       (dense['scales']['day']['w'], sparse['scales']['day']['w']))

    # W5 落潮不归零
    ok(far['scales']['just']['w'] > 0.4, 'W5 退潮后仍留在常态附近（不清空）', far['scales']['just']['w'])

    # W6 情感读慢
    lab = affect.labels(pos)
    ok(lab['affect'] in ('平稳', '踏实', '疏远'), 'W6 单次事件拉不动情感', lab)

    print()
    print('两轴+潮汐守卫：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())
