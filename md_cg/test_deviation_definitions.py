# -*- coding: utf-8 -*-
"""守卫 · 偏差的实际定义层（2026-11-17 使用者裁定）。

理论里 δ 是统称；落到对象上定义不同：
  · 情感：与**预测的行为、表现**不一致
  · 信任：与**约定**不一致
同一对数字在两条线上公式相同，但**比对对象不同** ⇒ 不同场景给出不同偏差。
未登记的对象一律拒绝（fail-closed），不猜。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import deviation as dv  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def main():
    # D1 定义表与使用者原话一致（防文档漂移）
    ok(dv.same_definition_as('affect', '与预测的行为、表现不一致'),
       'D1a 情感定义 = 与预测的行为、表现不一致', dv.definition_of('affect')[0])
    ok(dv.same_definition_as('trust', '与约定不一致'),
       'D1b 信任定义 = 与约定不一致', dv.definition_of('trust')[0])

    # D2 未登记对象 fail-closed
    try:
        dv.deviation('emotion_of_user', 1.0, 0.0)
        ok(False, 'D2 未知对象应拒绝', '竟然通过了')
    except ValueError as e:
        ok('未知偏差对象' in str(e), 'D2 未知对象拒绝并说明允许项', str(e)[:60])

    # D3 情感：比「表现」——多维表现取平均差
    a = dv.affect_deviation({'语气': 1.0, '动作': 1.0}, {'语气': 0.4, '动作': 1.0})
    ok(abs(a - 0.3) < 1e-9, 'D3a 情感偏差 = 各维表现差的均值', a)

    # D4 信任：比「约定」——未列出的约定视为未兑现
    t = dv.trust_deviation({'今天来': 1, '带笔记': 1}, {'今天来': 1})
    ok(abs(t - 0.5) < 1e-9, 'D4a 信任偏差 = 1 − 兑现率（漏项计偏差）', t)
    t2 = dv.trust_deviation({'今天来': 1}, {'今天来': 1})
    ok(abs(t2) < 1e-9, 'D4b 全部兑现 ⇒ 偏差 0', t2)

    # D5 同一对数字公式相同，但对象决定比对对象
    ok(dv.deviation('affect', 0.9, 0.4) == dv.deviation('trust', 0.9, 0.4),
       'D5a 通用函数与对象无关（只是归一化）')
    a_scene = dv.affect_deviation({'语气': 0.9}, {'语气': 0.4})      # 表现不一致
    t_scene = dv.trust_deviation({'按约定办': 1}, {})                   # 约定未兑现
    ok(abs(a_scene - 0.5) < 1e-9 and abs(t_scene - 1.0) < 1e-9,
       'D5b 同一事件在两条线上给出不同偏差（对象决定判据）', (a_scene, t_scene))

    # D6 信息差把「未闭合存量」单列
    d1 = dv.d_norm([0.0, 0.0, 0.0], unresolved_ratio=0.0)
    d2 = dv.d_norm([0.0, 0.0, 0.0], unresolved_ratio=1.0)
    ok(abs(d1) < 1e-9 and d2 > 0.29, 'D6 未闭合项独立计入信息差', (d1, round(d2, 3)))

    print()
    print('偏差定义守卫：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())
