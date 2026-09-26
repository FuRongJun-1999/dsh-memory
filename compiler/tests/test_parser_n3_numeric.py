# -*- coding: utf-8 -*-
"""test_parser_n3_numeric.py · _parse_numeric_value 裸 float 崩溃族守卫（2026-09-25）

缺陷（合并 缺陷8 new + 缺陷18 legacy，v3 N3 同族）：
  parser._parse_numeric_value 的 NUMBER 拼接分支裸 float() 无 try 保护——
  「于 标识符 数字」序列（如 '止 情感权重 于 甲 5。'）使
  ValueError: could not convert string to float: '甲5' 逃出 api.compile_source
  主入口与 CLI（栈崩而非返回 CompileResult 报错）。

  同型裸 float（同一崩溃族，经 compiler.compile_source——该入口 parse 先于
  词法错误检查，词法错 token 可进 parser）：
    parser.py _parse_numeric_value NUMBER 分支      —— float('.') 可达
    parser.py _parse_numeric_value ID+PERIOD+NUMBER —— float('甲.5') 可达
    parser.py _parse_instruction NUMBER 操作数      —— float('.') 可达
    parser.py _parse_expression  NUMBER 分支        —— float('.') 可达

修复语义：照同函数 PERIOD-else 分支（try/except ValueError→回落）既有模式，
ValueError 时按 _consume 同款风格记语法错误并回落节点——错误回流
api.errors / compiler errors，编译失败而不崩溃。

本文件把这些语义钉死，防止回归。
"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compiler.api import compile_source as api_compile
from compiler.compiler import compile_source as vm_compile

pass_n = fail_n = 0


def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print('[%s] %s%s' % ('OK ' if ok else 'FAIL', name, ' — ' + detail if detail else ''))


def api_no_crash(src):
    """api.compile_source 不得抛异常：返回 (result, 异常串)"""
    try:
        return api_compile(src), None
    except Exception as e:  # noqa: BLE001 —— 守卫目标即"任何异常都算失败"
        return None, '%s: %s' % (type(e).__name__, e)


def vm_no_crash(src):
    """compiler.compile_source 不得抛异常：返回 (result, 异常串)"""
    try:
        return vm_compile(src), None
    except Exception as e:  # noqa: BLE001
        return None, '%s: %s' % (type(e).__name__, e)


print('--- (1) 主入口守卫：「于 标识符 数字」不得崩溃，须 CompileResult 报错 ---')

r1, e1 = api_no_crash('止 情感权重 于 甲 5。')
check('①a 主守卫不抛异常（旧代码 ValueError 崩溃）', e1 is None, e1 or '')
check('①b 返回 success=False 且 errors 非空',
      r1 is not None and r1.success is False and len(r1.errors) > 0,
      'success=%s errors=%s' % (getattr(r1, 'success', None),
                                getattr(r1, 'errors', [])[:1]))

r1c, e1c = api_no_crash('止 情感权重 于 甲 5。')
check('①c CompileResult 可重复获得（稳定非崩溃路径）',
      e1c is None and r1c is not None and r1c.success is False, '')

print('--- (2) 同输入变体（独立双轮实跑确认的崩溃面）---')

for tag, src in [('②a', '止 情感权重 于 甲 0.9。'),
                 ('②b', '止 情感权重 于 甲.5。'),
                 ('②c', '止 情感权重 于 乙 5。')]:
    r, e = api_no_crash(src)
    check('%s %r 不崩溃且 success=False' % (tag, src),
          e is None and r is not None and r.success is False,
          e or 'success=%s' % getattr(r, 'success', None))

print('--- (3) 条件体链（则→指令→于→数值，:560/:689/:764/:844 链）---')

r3, e3 = api_no_crash('若 条件空间 为 伴侣，则止 情感权重 于 甲 5。')
check('③a 条件体链不崩溃且 success=False',
      e3 is None and r3 is not None and r3.success is False,
      e3 or 'success=%s' % getattr(r3, 'success', None))

print('--- (4) 同型裸 float 族（compiler.compile_source：parse 先于词法检查）---')

for tag, src, site in [
        ('④a', '止 情感权重 于 . 。', '_parse_numeric_value NUMBER 分支'),
        ('④b', '止 情感权重 于 甲。5。', '_parse_numeric_value ID+PERIOD+NUMBER'),
        ('④c', '计数 = . 5。', '_parse_expression NUMBER 分支'),
        ('④d', '止 . 。', '_parse_instruction NUMBER 操作数')]:
    r, e = vm_no_crash(src)
    ok = e is None and r is not None and r[1].get('ok') is False
    check('%s %s 不崩溃且 ok=False（%s）' % (tag, src, site), ok,
          e or 'ok=%s errors=%s' % (r[1].get('ok'), [str(x)[:40] for x in r[1].get('errors', [])[:1]]))

print('--- (5) 合法程序不受影响（于-数值/小数/负数/无操作数）---')

for tag, src in [('⑤a', '止 情感权重 于 0.15。'),
                 ('⑤b', '止情感权重于0.15。'),
                 ('⑤c', '止 情感权重 于 .5。'),
                 ('⑤d', '止 情感权重 于 -3。'),
                 ('⑤e', '止。')]:
    r, e = api_no_crash(src)
    check('%s %r 仍编译成功' % (tag, src),
          e is None and r is not None and r.success is True,
          e or 'success=%s errors=%s' % (r.success, r.errors[:1]))

print('\n=== N3 裸 float 崩溃族守卫: %d/%d 通过 ===' % (pass_n, pass_n + fail_n))
sys.exit(0 if fail_n == 0 else 1)
