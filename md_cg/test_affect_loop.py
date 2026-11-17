# -*- coding: utf-8 -*-
"""守卫 · 情绪/情感四时间尺度闭环（2026-11-17）。

使用者裁定：**不把上一轮结论当基线**——那等于让短期记忆直接当情绪，极其情绪化。
同一件事在「刚刚/日/月/年」四档上答案不同（心愿也有长期短期），故：

  S1 快慢分离：单次冲击在 just 尺度强、year 尺度弱
  S2 慢尺度需持续：一次冲击几乎不动 year；连喂 20 天才抬起
  S3 快尺度会忘：just 半衰期 10 分钟；month 几乎不动
  S4 情绪读快、情感读慢：一次冲击 ⇒ 情绪起反应、情感仍平稳
  N1/N2/N3 与 X1/X2 同前
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
    ok(set(s0['scales']) == set(affect.TIMESCALES), 'S0 四尺度初始化齐全', list(s0['scales']))

    s1 = affect.update(s0, {'expect': 1.0, 'actual': 0.0, 'event': '意外', 't': 1001.0})
    sc = s1['scales']
    ok(sc['just']['e'] > sc['day']['e'] > sc['month']['e'] > sc['year']['e'],
       'S1 同一冲击：just > day > month > year', {k: round(v['e'], 3) for k, v in sc.items()})
    ok(sc['year']['e'] < 0.1, 'S2a 一次冲击几乎不动 year 尺度', round(sc['year']['e'], 4))

    s = s1
    for i in range(20):
        s = affect.update(s, {'error': 0.9, 't': 1001.0 + (i + 1) * 86400})
    ok(s['scales']['year']['e'] > 0.3, 'S2b 持续 20 天后 year 尺度抬起', round(s['scales']['year']['e'], 3))

    quiet = affect.update(s1, {'t': 1001.0 + 10 * 60 * 6})
    ok(quiet['scales']['just']['e'] < 0.05, 'S3a just 尺度 1 小时后回落', round(quiet['scales']['just']['e'], 4))
    ok(quiet['scales']['month']['e'] > 0.2, 'S3b 同一时刻 month 尺度几乎不动', round(quiet['scales']['month']['e'], 3))

    lab = affect.labels(s1)
    ok(lab['emotion'] in ('警惕', '困惑·加剧'), 'S4a 一次冲击 ⇒ 情绪起反应', lab)
    ok(lab['affect'] == '平稳', 'S4b 同一冲击 ⇒ 情感仍平稳（慢尺度未动）', lab)

    before = json_dumps = str(s1)
    affect.labels(s1)
    ok(before == str(s1), 'N1 labels() 纯读，不改状态')
    s2 = affect.update(s0, {'trust_ext_delta': -0.4, 'event': '失信', 't': 1002.0})
    ok(all(abs(s2['scales'][n]['e']) < 1e-9 for n in affect.TIMESCALES),
       'N2a 信任下降不产生任何尺度的误差')
    ok(affect.labels(s2)['affect'] == '信任下降', 'N2b 情感反映信任下降', affect.labels(s2))

    nd = {'half_life_s': 0}
    a1 = affect.update(s0, {'error': 0.7, 't': 1002.0}, cfg=nd)
    a2 = affect.update(a1, {'error': 0.7, 't': 1002.0}, cfg=nd)
    ok(abs(a2['scales']['just']['de']) < 1e-12, 'N3 同观测重复 ⇒ just 尺度 dE=0', a2['scales']['just']['de'])

    ex = affect.explain(s1)
    ok(set(ex['scales']) == set(affect.TIMESCALES) and ex['last_event'] == '意外',
       'X1 explain 逐尺度给读数 + 事件', list(ex.keys()))
    T = tempfile.mkdtemp(prefix='affect_')
    try:
        os.environ.pop('MDCG_AFFECT', None)
        ok(affect.enabled() is False, 'X2a 默认关闭')
        os.environ['MDCG_AFFECT'] = '1'
        p = affect.append(T, s1)
        last, rows = affect.load_last(T)
        ok(os.path.isfile(p) and len(rows) == 1 and last['n'] == s1['n'],
           'X2b append-only 落盘与读回一致', (len(rows), last and last.get('n')))
    finally:
        os.environ.pop('MDCG_AFFECT', None)
        shutil.rmtree(T, ignore_errors=True)

    print()
    print('四尺度情绪闭环守卫：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())
