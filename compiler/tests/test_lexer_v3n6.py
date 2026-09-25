# -*- coding: utf-8 -*-
"""test_lexer_v3n6.py · v3 N6 回归守卫：无空格「条件空间为X」定向断开（2026-09-25）

安全缺陷（v3 N6，severity=high）：协议源码用无空格写法『若条件空间为伴侣，
则止情感权重于0.9。』可让超限情感权重通过编译进入「伴侣」条件空间——
词法层把「条件空间为伴侣」整段吞作单 IDENTIFIER（「为」不在 CJK 断开前瞻
集合），parser 不生成 COMPARISON，名实校验 _check_condition_space_switch
（依赖 left=="条件空间" 的比较节点）永不触发，「伴侣」空间情感权重上限
0.15 约束对无空格源码整体失效（success=True、errors=[]）。

修复（compiler/lexer.py CJK 收集分支定向断开）：仅当「为/不为」紧接在名词
「条件空间」之后才断开——断点落在关键字（WEI/BUWEI）起点，主循环最长匹配
随后发出 WEI/BUWEI，与带空格写法「条件空间 为 X」产生相同 token 流。
不把「为」全局加入断开集合：「作为/成为/行为/认为」等含「为」名词会被切碎。

本文件钉死：攻击样例必须被拒（errors 非空且点名上限）、带空格版不回归、
含「为」合法标识符不被误切、断开不外溢到非「条件空间」语境。
"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compiler.compiler import compile_source
from compiler.lexer import tokenize, TokenType

pass_n = fail_n = 0


def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print('[%s] %s%s' % ('OK ' if ok else 'FAIL', name, ' — ' + detail if detail else ''))


def token_seq(src):
    toks, _ = tokenize(src)
    return [(t.type.name, t.value) for t in toks if t.type != TokenType.EOF]


# =============================================================================
# ① 攻击样例：无空格写法必须被名实校验拒绝
# =============================================================================
print('--- (1) 无空格攻击样例必须被拒 ---')

ATTACK = '若条件空间为伴侣，则止情感权重于0.9。'
_, r = compile_source(ATTACK)
check('①a 无空格『条件空间为伴侣』情感权重 0.9 编译被拒',
      not r['ok'] and any('0.15' in e and '情感权重' in e for e in r['errors']),
      'ok=%s errors=%s' % (r['ok'], r['errors']))

_, r2 = compile_source('若条件空间不为伴侣，则止情感权重于0.9。')
check('①b 无空格『不为』形态同被拒（fail-closed）',
      not r2['ok'] and any('情感权重' in e for e in r2['errors']),
      'ok=%s errors=%s' % (r2['ok'], r2['errors']))

# 前缀名词形态：词法层已正确断开（③c），编译行为须与带空格版一致——
# name_checker 只认精确名「条件空间」（_check_condition_space_switch 的
# left.name == "条件空间" 判定），「我的条件空间」是另一符号，带空格版
# 本就不触发切换；无空格版不得与带空格版产生行为分叉（分叉即绕过口）。
_, r3n = compile_source('若我的条件空间为伴侣，则止情感权重于0.9。')
_, r3s = compile_source('若我的条件空间 为 伴侣，则止情感权重于0.9。')
check('①c 前缀名词形态无空格/带空格行为一致（无分叉）',
      r3n['ok'] == r3s['ok'] and
      [e for e in r3n['errors'] if '情感权重' in e] ==
      [e for e in r3s['errors'] if '情感权重' in e],
      'nospace ok=%s errors=%s | spaced ok=%s errors=%s' %
      (r3n['ok'], r3n['errors'], r3s['ok'], r3s['errors']))

# =============================================================================
# ② 带空格版（既有形态）不回归 + 合法值不误伤
# =============================================================================
print('--- (2) 带空格版不回归 / 合法值不误伤 ---')

_, rs = compile_source('若条件空间 为 伴侣，则止情感权重于0.9。')
check('②a 带空格版仍拒绝（既有守卫形态）',
      not rs['ok'] and any('0.15' in e for e in rs['errors']),
      'ok=%s errors=%s' % (rs['ok'], rs['errors']))

_, rl = compile_source('若条件空间为伴侣，则止情感权重于0.15。')
check('②b 合法值 0.15（无空格）不误报上限',
      not any('情感权重' in e for e in rl['errors']),
      'errors=%s' % rl['errors'])

# =============================================================================
# ③ 词法层定向断开：token 流与带空格写法等价
# =============================================================================
print('--- (3) token 流形态 ---')

check('③a 『条件空间为伴侣』→ ID(条件空间)+WEI+ID(伴侣)',
      token_seq('条件空间为伴侣') ==
      [('IDENTIFIER', '条件空间'), ('WEI', '为'), ('IDENTIFIER', '伴侣')],
      str(token_seq('条件空间为伴侣')))

check('③b 『条件空间不为伴侣』→ ID+BUWEI+ID',
      token_seq('条件空间不为伴侣') ==
      [('IDENTIFIER', '条件空间'), ('BUWEI', '不为'), ('IDENTIFIER', '伴侣')],
      str(token_seq('条件空间不为伴侣')))

check('③c 『我的条件空间为伴侣』→ ID(我的条件空间)+WEI+ID',
      token_seq('我的条件空间为伴侣') ==
      [('IDENTIFIER', '我的条件空间'), ('WEI', '为'), ('IDENTIFIER', '伴侣')],
      str(token_seq('我的条件空间为伴侣')))

# =============================================================================
# ④ 断开不外溢：含「为」的合法名词保持整体
# =============================================================================
print('--- (4) 断开不外溢（误伤面钉死）---')

for word in ['作为', '成为', '行为', '认为', '人为', '信任为基']:
    seq = token_seq(word)
    check('④『%s』仍为单 IDENTIFIER（不发 WEI）' % word,
          seq == [('IDENTIFIER', word)], str(seq))

seq = token_seq('无为')
check('④『无为』仍是单关键字 WUWEI（非 ID+WEI）',
      seq == [('WUWEI', '无为')], str(seq))

print('\n=== v3 N6 词法定向断开回归: %d/%d 通过 ===' % (pass_n, pass_n + fail_n))
sys.exit(0 if fail_n == 0 else 1)
