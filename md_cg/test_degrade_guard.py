# -*- coding: utf-8 -*-
"""退化守卫的守卫：用 2026-11-20 的实测样本做断言。

# 功能名：test_degrade_guard —— degrade_guard 的定点断言（含变异锚）
# 生效条件：改动 md_cg/degrade_guard.py 的判据或阈值后
# 子功能：
#   ① 用真实样本验证四条判据各自能红 / 能绿
#   ② 变异锚：把阈值放宽后，原本红的样本必须变绿（证明断言不是恒真）
# 执行：python -X utf8 md_cg/test_degrade_guard.py
# 验证方式：自证——每条断言都带一条「反过来就该失败」的对照
# 不适用条件：本测试不验证语义正确性，只验证形态判据
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import degrade_guard as dg  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:160]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def main():
    print('=== degrade_guard 守卫 ===')

    same = ['我把它理解成A因为你说了X没说Y'] * 3
    r = dg.check_chain(same)
    ok(r['verdict'] == 'degraded' and any('Jaccard' in f for f in r['failures']),
       'D1 完全复述判 degraded', r)

    diff = ['灵枢是记忆系统。', '它把经验写成带条件的记忆。', '它同时负责记取与归档。']
    r = dg.check_chain(diff)
    ok(r['verdict'] == 'ok', 'D1 三个不同短句判 ok', r)

    long_common = '这件事之所以重要是因为它决定了后续所有判据的口径'
    a = '开头甲。' + long_common + '尾巴甲很长很长很长。'
    b = '开头乙。' + long_common + '尾巴乙也很长很长很长。'
    r = dg.check_chain([a, b])
    ok(any('最长公共子串' in f for f in r['failures']), 'D2 长公共子串触发', r)

    nag = '做。\n给。\n执行。\n正文到此结束。'
    ok(dg.nag_runs(nag) >= 3, 'D3 催稿段识别', dg.nag_runs(nag))
    ok(dg.nag_runs('这是一段正常的解释性文字，没有短句连排。') == 0, 'D3 正常段落不误判')

    single_like = ['我把它理解成开放不是发布因为你说了对外开放没说只发布'] * 4
    r = dg.check_chain(single_like, requirement='reason')
    ok(r['verdict'] == 'degraded' and any('唯一率' in f for f in r['failures']),
       'D4 固定开头判固化', r['failures'])

    three_like = [
        '我把它理解成开放不是发布因为你说了对外开放没说只发布。其余略。',
        '我拿不准的只有范围若范围相反则结论要改。其余略。',
        '我按严格口径处理依据是材料里写的不提供生产保证。其余略。',
        '考虑到前一轮已经把边界说清了这一轮只补证据来源。其余略。',
    ]
    r = dg.check_chain(three_like, requirement='reason')
    ok(r['verdict'] == 'ok', 'D4 多形态开头判合格', r)

    no_reason = ['这份材料讲的是对外开放的风险，涉及隐私与合规两个方面，需要逐条评估。'] * 3
    r = dg.check_chain(no_reason, requirement='reason')
    ok(any('存在率' in f for f in r['failures']), 'D5 不写理由被识别', r['failures'])

    saved = dg.CROSS_TURN_JACCARD
    try:
        dg.CROSS_TURN_JACCARD = 1.01
        ok(dg.check_chain(same)['verdict'] == 'ok', 'M 放宽 Jaccard 阈值后同一样本变绿')
    finally:
        dg.CROSS_TURN_JACCARD = saved
    ok(dg.check_chain(same)['verdict'] == 'degraded', 'M 阈值恢复后重新变红')

    # ---- S 组：源侧固化（#996 第三种落点 + yunluo4444 的 pool_varies 前提）----
    same = [('n1', '同一行台账文本')] * 4
    r1 = dg.source_fixation(same)
    ok(r1['degraded'] is True, 'S1 同对象同产出 → 判空转', r1)
    r2 = dg.source_fixation(same, pool_varies=False)
    ok(r2['degraded'] is False, 'S2 池本不该变 → 不判（前提生效）', r2)
    r3 = dg.source_fixation([('n1', 'a'), ('n2', 'a'), ('n3', 'a')])
    ok(r3['degraded'] is False, 'S3 对象在变 → 不判', r3)
    r4 = dg.source_fixation([('n1', '甲')] * 3 + [('n1', '完全不同的另一段产出文字')])
    ok(r4['degraded'] is False, 'S4 同对象但产出在变 → 不判', r4)

    # ---- B 组：回合级空回合（主判据）+ 真实语料回归锚 ----
    ok(dg.blank_turn({'thinking': 'x' * 300, 'body_len': 0, 'tool_calls': 0}) is True,
       'B1 空回合判定为真')
    ok(dg.blank_turn({'thinking': 'x' * 300, 'body_len': 12, 'tool_calls': 0}) is False,
       'B2 有正文判假')
    ok(dg.blank_turn({'thinking': 'x' * 300, 'body_len': 0, 'tool_calls': 3}) is False,
       'B3 有工具调用判假（正常工具步不算）')
    ok(dg.blank_turn({'thinking': 'x' * 50, 'body_len': 0, 'tool_calls': 0}) is False,
       'B4 思考过短判假')

    real = ('执行。\n\n时间：快。\n\n执行。\n\n写。\n\n执行。\n\n时间：快。'
            '\n\n执行。\n\nOK。\n\n执行。\n\n时间：快。')
    ok(dg.nag_runs(real) >= 8,
       'N1 真实退化样本 nag_runs ≥8（修前因空行切断只有 1–2）', dg.nag_runs(real))
    ok(dg.nag_runs('我今天检查了三个模块的实现，发现锁的获取顺序有问题，需要按地址排序后再加锁。') == 0,
       'N2 正常文本不误报')

    print()
    print('守卫结果：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())
