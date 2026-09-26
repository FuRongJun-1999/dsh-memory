# -*- coding: utf-8 -*-
"""test_parser_n148_stepnum_overflow.py · 术曰步骤号 int(float()) 崩溃族守卫（N148）

缺陷（N148-A，2026-09-26）：parser._parse_shuyue_block（parser.py:441）与
parser._parse_wenyue_block（parser.py:486）的步骤号转换
`step_num = int(float(value))` 裸调无防护——F1 五点防护（_parse_instruction /
_parse_numeric_value / _parse_expression 的裸 float 族）不含此两转换点：

  ① ≥309 位数字字面量：词法 float() 得 inf 不报错（NUMBER 合法发出），
    parser int(inf) 抛 OverflowError: cannot convert float infinity to integer
    —— api.compile_source（词法门禁拦不住：词法零错）与
       compiler.compile_source 双主入口皆崩；
  ② 词法毒 token NUMBER('.')（孤立'.'，词法记错但仍发 NUMBER）：
    compiler.compile_source 先 parse（compiler.py:259）后查词法错（:260），
    parser float('.') 抛 ValueError: could not convert string to float: '.'
    —— vm 主入口崩（api 入口同源因词法门禁早退 success=False，不崩）。

传导面：CLI cmd_compile（cli/__init__.py:131 直调 api.compile_source 无兜底）
与 pbc/analyzer/debugger（均透传 compiler.compile_source）同路径。

修复语义：两转换点对齐 F1 既有防护模式——try/except (ValueError,
OverflowError) 记结构化语法错误「L{line}:C{col} 非法数值: '<value>'」并消费
该 token 继续，编译失败而非栈崩；合法输入（≤308 位步骤号、正常步骤号）编译
输出逐位不变。

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
    """compiler.compile_source 不得抛异常：返回 ((code, result), 异常串)"""
    try:
        return vm_compile(src), None
    except Exception as e:  # noqa: BLE001
        return None, '%s: %s' % (type(e).__name__, e)


_LONG = '9' * 309   # float → inf（308 位仍有限，是合法对照）

print('--- (1) ①≥309 位步骤号：OverflowError 族（api + vm 双入口）---')

r1, e1 = api_no_crash('术曰：' + _LONG + '。道 术一。')
check('①a api 术曰块 309 位不抛异常（旧码 OverflowError 崩溃）', e1 is None, e1 or '')
check('①b api 返回 success=False 且 errors 非空',
      r1 is not None and r1.success is False and len(r1.errors) > 0,
      'success=%s errors=%s' % (getattr(r1, 'success', None),
                                getattr(r1, 'errors', [])[:1]))
check('①c api 错误为结构化「非法数值」而非栈崩文本',
      r1 is not None and any('非法数值' in x for x in r1.errors),
      str(getattr(r1, 'errors', [])[:1]))

r1d, e1d = api_no_crash('问曰：问。答曰：答。术曰：' + _LONG + '。道 术一。')
check('①d api 问曰块（_parse_wenyue_block:486）不抛异常且报错',
      e1d is None and r1d is not None and r1d.success is False,
      e1d or 'success=%s' % getattr(r1d, 'success', None))

r1e, e1e = vm_no_crash('术曰：' + _LONG + '。道 术一。')
check('①e vm 入口 309 位不抛异常且 ok=False',
      e1e is None and r1e is not None and r1e[1].get('ok') is False,
      e1e or 'ok=%s' % (r1e[1].get('ok') if r1e else None))

print('--- (2) ②词法毒 token NUMBER(\'.\')：ValueError 族（vm 主入口）---')

r2, e2 = vm_no_crash('术曰：.。')
check('②a vm 术曰块孤点号不抛异常（旧码 ValueError 崩溃）', e2 is None, e2 or '')
check('②b vm 返回 ok=False 且 errors 非空',
      r2 is not None and r2[1].get('ok') is False and len(r2[1].get('errors', [])) > 0,
      'ok=%s errors=%s' % (r2[1].get('ok') if r2 else None,
                           [str(x)[:40] for x in r2[1].get('errors', [])[:1]] if r2 else None))

r2c, e2c = vm_no_crash('问曰：问。答曰：答。术曰：.。')
check('②c vm 问曰块孤点号（:486）不抛异常且 ok=False',
      e2c is None and r2c is not None and r2c[1].get('ok') is False,
      e2c or 'ok=%s' % (r2c[1].get('ok') if r2c else None))

r2d, e2d = api_no_crash('术曰：.。')
check('②d api 同源（词法门禁早退）仍 success=False 不异常',
      e2d is None and r2d is not None and r2d.success is False,
      e2d or 'success=%s' % getattr(r2d, 'success', None))

print('--- (3) 错误记录可重复获得（稳定非崩溃路径）---')

ra, ea = api_no_crash('术曰：' + _LONG + '。道 术一。')
rb, eb = api_no_crash('术曰：' + _LONG + '。道 术一。')
check('③ 同输入两次编译均稳定报错（不崩溃）',
      ea is None and eb is None and ra.success is False and rb.success is False, '')

print('--- (4) 合法输入不受影响（步骤号逐位基线）---')

for tag, src in [('④a', '术曰：1。道 术一。'),
                 ('④b', '术曰：1。道 术一；2。德 0.5。'),
                 ('④c', '术曰：' + '9' * 308 + '。道 术一。'),
                 ('④d', '术曰：3.5。道 术一。'),
                 ('④e', '问曰：问。答曰：答。术曰：1。道 术一。')]:
    r, e = api_no_crash(src)
    check('%s %r… 仍编译成功' % (tag, src[:12]),
          e is None and r is not None and r.success is True,
          e or 'success=%s errors=%s' % (r.success, r.errors[:1]))

rc, ec = vm_no_crash('术曰：1。道 术一；2。止。')
check('④f vm 入口合法术曰仍 ok=True',
      ec is None and rc is not None and rc[1].get('ok') is True and rc[0] is not None,
      ec or 'ok=%s' % (rc[1].get('ok') if rc else None))

print('\n=== N148 步骤号崩溃族守卫: %d/%d 通过 ===' % (pass_n, pass_n + fail_n))
sys.exit(0 if fail_n == 0 else 1)
