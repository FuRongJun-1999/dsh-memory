# -*- coding: utf-8 -*-
"""test_parser_weight_value_forms.py · 情感权重上限非「于」形态绕过守卫（2026-09-25）

缺陷（缺陷20 new，N6 同族第三形态）：
  0.15 情感权重上限只挂 LITERAL 节点，数值以非「于」介词形态出现即失去
  LITERAL 类型：
    ① 空格数「止情感权重 0.9」——_merge_identifiers 只比行号不比列号
       连续（与自身 docstring「同一行、列号连续」不符），NUMBER 被拼入
       标识符名 → 操作数 [ID('情感权重0.9')]，数值彻底消失；
    ② 等于形「止情感权重等于1」——DENGYU 在指令操作数位被静默
       _advance，词法定向断开产出的 ID('1') 落成标识符操作数 →
       [ID('情感权重'), ID('1')]，仅"可能是 P1 一部分"警告。
  两形态双官方入口（api/compiler）均过审；对照「止情感权重于1」双拒。

修复：
  ① _merge_identifiers 不再把 NUMBER 拼入标识符名（数值保住 LITERAL
     类型，经 _check_literal 撞空间上限）；ID-ID 合并保持同行规则；
  ② _parse_instruction 的数值介词分支从 YU 扩到 DENGYU（等于与于同形，
     后随可转数值则成 LiteralNode，非数字后随回落 IdentifierNode）。

本文件把语义钉死，防止回归。
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


def rejected_by_api(src):
    try:
        r = api_compile(src)
        return (r.success is False
                and any('0.15' in x or '情感权重' in x for x in r.errors),
                'success=%s errors=%s' % (r.success, [str(x)[:50] for x in r.errors[:1]]))
    except Exception as e:  # noqa: BLE001
        return False, '%s: %s' % (type(e).__name__, e)


def rejected_by_vm(src):
    try:
        code, r = vm_compile(src, strict=True)
        return (r.get('ok') is False
                and any('0.15' in str(x) or '情感权重' in str(x) for x in r.get('errors', [])),
                'ok=%s errors=%s' % (r.get('ok'), [str(x)[:50] for x in r.get('errors', [])[:1]]))
    except Exception as e:  # noqa: BLE001
        return False, '%s: %s' % (type(e).__name__, e)


def legal_via_api(src):
    try:
        r = api_compile(src)
        return r.success is True, 'success=%s errors=%s warnings=%s' % (
            r.success, [str(x)[:40] for x in r.errors[:1]],
            [str(x)[:40] for x in r.warnings[:1]])
    except Exception as e:  # noqa: BLE001
        return False, '%s: %s' % (type(e).__name__, e)


print('--- (1) 主守卫：两形态双入口双拒（修复前 success=True 过审）---')

ok_a, d_a = rejected_by_api('若条件空间为伴侣，则止情感权重 0.9。')
check('①a api 拒空格数形态（数值不再被拼入标识符名）', ok_a, d_a)
ok_v, d_v = rejected_by_vm('若条件空间为伴侣，则止情感权重 0.9。')
check('①b compiler 拒空格数形态', ok_v, d_v)

ok_a2, d_a2 = rejected_by_api('若条件空间为伴侣，则止情感权重等于1。')
check('①c api 拒等于形态（DENGYU 后随数值成 LITERAL）', ok_a2, d_a2)
ok_v2, d_v2 = rejected_by_vm('若条件空间为伴侣，则止情感权重等于1。')
check('①d compiler 拒等于形态', ok_v2, d_v2)

print('--- (2) 同族闭包：无空格粘连形态 ---')

ok_a3, d_a3 = rejected_by_api('若条件空间为伴侣，则止情感权重0.9。')
check('②a api 拒无空格形态（ID(\'情感权重0\')+Lit(0.9)）', ok_a3, d_a3)

print('--- (3) 对照：「于」形态既有拒绝/合法语义不变 ---')

ok_3, d_3 = rejected_by_api('若条件空间为伴侣，则止情感权重于1。')
check('③a 于形超限仍被拒（既有行为）', ok_3, d_3)
ok_3b, d_3b = legal_via_api('若条件空间为伴侣，则止情感权重于0.15。')
check('③b 于形上限内仍合法（既有行为）', ok_3b, d_3b)

print('--- (4) 合法程序不受影响 ---')

LEGAL = [
    ('④a', '无空间切换时空格数放行（既有）', '止情感权重 0.9。'),
    ('④b', '等于形上限内合法', '若条件空间为伴侣，则止情感权重等于0.15。'),
    ('④c', '等于形带空格合法', '止 情感权重 等于 0.3。'),
    ('④d', '多词标识符指令（ID-ID 合并保留）', '德 累积信任值。'),
    ('④e', '多词标识符指令 2', '柔 响应强度。'),
    ('④f', '多词标识符指令 3', '道 新信任路径。'),
    ('④g', '知足 验证单元', '知足 验证单元。'),
    ('④h', '赋值/表达式不受影响', '计数 = 计数 + 1。'),
    ('④i', '条件空间赋值联动（上轮修复）不回归',
     '条件空间 = 伴侣\n止情感权重于0.15。'),
    ('④j', '等于后随非数字回落标识符（操作数集合不变）', '止 情感权重 等于 阈值。'),
]
for tag, name, src in LEGAL:
    ok, d = legal_via_api(src)
    check('%s %s 仍编译成功' % (tag, name), ok, d)

print('\n=== 情感权重非于形态守卫: %d/%d 通过 ===' % (pass_n, pass_n + fail_n))
sys.exit(0 if fail_n == 0 else 1)
