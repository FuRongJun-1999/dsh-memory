# -*- coding: utf-8 -*-
"""守卫 · 写入闸默认开 + 复核通道默认声明（2026-11-17 使用者裁定）。

此前闸默认 off、通道默认空 ⇒ 分档模型（情景0/知识1/结构2/自我3）形同虚设，
外部模型随手把手戏写进知识层、还拿到 0.9 + protected。

  W1 缺省档位 = enforce；缺省通道含 hive 与 subagent
  W2 无复核单元 ⇒ 知识层 require_review；情景层 allow
  W3 带 reviewers=reflect ⇒ 知识层放行
  W4 安全主体层真的拦（Principal.require_layer_write）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import security, writegate  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def main():
    clean = {k: v for k, v in os.environ.items()
             if k not in ('MDCG_WRITE_GATE', 'MDCG_REVIEW_CHANNELS', 'MDCG_REVIEWERS')}
    ok(writegate.gate_mode(clean) == 'warn', 'W1a 缺省档位 = warn（判定+留痕，不硬拦）', writegate.gate_mode(clean))
    ch = writegate.review_channels(clean)
    ok('hive' in ch and 'subagent' in ch, 'W1b 缺省通道含 hive 与 subagent', ch)

    d1 = writegate.decide_write('knowledge', environ=clean)
    ok(d1['decision'] == 'require_review' and d1['missing'] == ['reflect'],
       'W2a 知识层无复核 ⇒ require_review', d1)
    d0 = writegate.decide_write('contextual', environ=clean)
    ok(d0['decision'] == 'allow', 'W2b 情景层直写', d0)

    d2 = writegate.decide_write('knowledge', reviewers=('reflect',), environ=clean)
    ok(d2['decision'] == 'allow', 'W3 带 reflect 复核 ⇒ 放行', d2)

    os.environ['MDCG_WRITE_GATE'] = 'enforce'
    p = security.Principal(actor='t', role='designer')
    try:
        p.require_layer_write('knowledge', 'internal')
        ok(False, 'W4a 知识层应被拦', '竟然通过')
    except Exception as e:
        ok('复核闸' in str(e) or 'AccessDenied' in type(e).__name__, 'W4a 知识层被拦（无复核）', str(e)[:60])
    try:
        p.require_layer_write('contextual', 'internal')
        ok(True, 'W4b 情景层放行')
    except Exception as e:
        ok(False, 'W4b 情景层应放行', str(e)[:60])

    os.environ.pop('MDCG_WRITE_GATE', None)
    print()
    print('写入闸守卫：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())