# -*- coding: utf-8 -*-
"""test_verdict_product_compile.py · 验证终裁橡皮图章守卫（2026-09-25）

缺陷（合并缺陷17+23 双确认，N8 欠账自 v3）：
  api._verification_verdict 对 result.errors 为空即返回
  passed=True/'路径有效'/confidence=0.85——对产物可编译性零独立验证
  （全包无一处 compile(result.code)），信任值/条件空间检查为「简化实现」
  占位注释。漏记错误形态一律盖章假成功：
    'class = 5。'  → 产物 'class = 5.0'（SyntaxError: invalid syntax）
    '返回 1。'     → 产物模块级 return（SyntaxError: 'return' outside
                    function，缺陷16；'返回 信任值。'/'返回 甲 加 乙。' 同族）
  而对产物 compile() 实抛 SyntaxError。词法/语法/名实早退路径 verdict=None
  （验证单元在需要否决的既有错误面缺席，但该面已由 errors 否决——本守卫
  钉死其 verdict=None 现状不因本修漂移）。

修复：errors 为空分支加 compile(result.code, '<协议产物>', 'exec') 产物
终验——SyntaxError/ValueError → passed=False（经 :190-191 回流
「验证单元否决」入 errors，success=False）。合法产物仅运行期 NameError
（compile 只查语法）不受影响。

本文件把语义钉死，防止回归。
"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compiler.api import compile_source as api_compile

pass_n = fail_n = 0


def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print('[%s] %s%s' % ('OK ' if ok else 'FAIL', name, ' — ' + detail if detail else ''))


def run(src):
    try:
        return api_compile(src), None
    except Exception as e:  # noqa: BLE001
        return None, '%s: %s' % (type(e).__name__, e)


print('--- (1) 主守卫：漏记错误形态不得盖章假成功（修复前 success=True）---')

r1, e1 = run('class = 5。')
check('①a class = 5。→ success=False（N64/缺陷15/21 形态）',
      e1 is None and r1.success is False,
      e1 or 'success=%s errors=%s' % (r1.success, [str(x)[:60] for x in r1.errors[:1]]))
check('①b verdict 否决且点名产物不可编译',
      r1 is not None and r1.verdict is not None and r1.verdict.get('passed') is False
      and '不可编译' in r1.verdict.get('reason', '')
      and any('验证单元否决' in x for x in r1.errors),
      str(r1.verdict)[:80] if r1 and r1.verdict else 'verdict=%r' % (r1.verdict if r1 else None))

r2, e2 = run('返回 1。')
check('①c 返回 1。→ success=False（顶层 return/缺陷16）',
      e2 is None and r2.success is False,
      e2 or 'success=%s errors=%s' % (r2.success, [str(x)[:60] for x in r2.errors[:1]]))

print('--- (2) 顶层 return 同族闭包 ---')

for tag, src in [('②a', '返回 信任值。'), ('②b', '返回 甲 加 乙。')]:
    r, e = run(src)
    check('%s %r → success=False（模块级 return 不可编译）' % (tag, src),
          e is None and r.success is False,
          e or 'success=%s' % r.success)

print('--- (3) 对照：已记错误面 verdict 输出不变（橡皮图章问题专在漏记面）---')

r3, e3 = run('定义 +（甲，乙）：返回 甲。')
check('③a codegen 错误回流路径 verdict 原文不变',
      e3 is None and r3.success is False and
      r3.verdict == {'passed': False,
                     'reason': "编译错误: L1 名字 '+' 不是合法的 Python 标识符",
                     'authority': 'VERIFICATION_UNIT'},
      str(r3.verdict)[:90] if r3 and r3.verdict else 'verdict=%r' % (r3.verdict if r3 else None))

print('--- (4) 合法面：verdict 逐字不变 + success 不变 ---')

r4, e4 = run('止 情感权重 于 0.15。')
check('④a 旗舰合法 verdict 逐字不变（passed=True/0.85/路径有效）',
      e4 is None and r4.success is True and
      r4.verdict == {'passed': True, 'reason': '路径有效：结构一致且缩小信息差',
                     'authority': 'VERIFICATION_UNIT', 'confidence': 0.85},
      str(r4.verdict)[:80] if r4 and r4.verdict else 'verdict=%r' % (r4.verdict if r4 else None))

r4b, e4b = run('定义 双倍（x）：返回 x 乘 2。')
check('④b 函数体内 return 合法（产物 def 内 return 可编译）',
      e4b is None and r4b.success is True,
      e4b or 'success=%s errors=%s' % (r4b.success, r4b.errors[:1]))

LEGAL = [('④c', '止。'), ('④d', '计数 = 计数 + 1。'),
         ('④e', '若条件空间为伴侣，则止情感权重于0.15。'),
         ('④f', '条件空间 = 伴侣\n止情感权重于0.15。'),
         ('④g', '若 条件空间 为 工作，则 止 情感权重 于 0.05。')]
for tag, src in LEGAL:
    r, e = run(src)
    check('%s %r 仍编译成功' % (tag, src), e is None and r.success is True,
          e or 'success=%s' % r.success)

print('--- (5) 早退路径 verdict=None 现状钉死（不因本修漂移）---')

r5, e5 = run('止 情感权重 于 甲 5。')
check('⑤a 语法早退 verdict 仍为 None（既有 errors 已否决）',
      e5 is None and r5.success is False and r5.verdict is None,
      'success=%s verdict=%r' % (r5.success, r5.verdict))
r5b, e5b = run('若条件空间为伴侣，则止情感权重于1。')
check('⑤b 名实早退（上限拒绝）verdict 仍为 None',
      e5b is None and r5b.success is False and r5b.verdict is None,
      'success=%s verdict=%r' % (r5b.success, r5b.verdict))

print('\n=== 验证终裁产物终验守卫: %d/%d 通过 ===' % (pass_n, pass_n + fail_n))
sys.exit(0 if fail_n == 0 else 1)
