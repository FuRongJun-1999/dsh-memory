# -*- coding: utf-8 -*-
"""test_weight_cap_string_missing.py · 情感权重上限引号数值/缺操作数绕过守卫（2026-09-25）

缺陷（缺陷22 new）：
  ① 引号数值：『…止 情感权重 于 "0.9"。』——STRING 收作字符串操作数
     （parser STRING 分支），_check_literal 仅 literal_type=='number' 才
     进入上限检查，字符串形态整体跳过 → success=True 假成功，产物
     _runtime.halt("情感权重", "0.9")（阈值降级为字符串）；
  ② 缺操作数：『止 情感权重 于。』——_parse_numeric_value 返回 None 即被
     静默丢弃，「于」后无值零报错，ZHI min_operands=0 无兜底 → 上限
     语义静默失效；
  ③ 上限硬编码：name_checker 仅硬编码「伴侣+0.15」，工作空间 0.05
     上限（CONDITION_SPACE_RULES 表内明文）从不生效（缺陷4/22 同源）。

修复：
  ① parser：YU/DENGYU 后 _parse_numeric_value 返回 None → 记语法错误
     「于/等于后期望数值」（缺值与字符串形态均覆盖）；
  ② name_checker：上限改表驱动（CONDITION_SPACE_RULES.max_emotional_weight，
     伴侣 0.15/工作 0.05；「默认」自身描述"无特殊约束"且既有语义不拦截，
     不在此列——消息文案对伴侣逐字不变）；止（ZHI）指令的字符串操作数
     可 float 解析且超限时同款报错（阈值不得经字符串降级绕过）。

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


def api_result(src):
    try:
        return api_compile(src), None
    except Exception as e:  # noqa: BLE001
        return None, '%s: %s' % (type(e).__name__, e)


def rejected_by_api(src, needle='期望数值'):
    r, e = api_result(src)
    return (e is None and r.success is False
            and any(needle in x for x in r.errors),
            e or 'success=%s errors=%s' % (r.success, [str(x)[:50] for x in r.errors[:1]]))


def rejected_by_vm(src, needle='期望数值'):
    try:
        code, r = vm_compile(src, strict=True)
        return (r.get('ok') is False
                and any(needle in str(x) for x in r.get('errors', [])),
                'ok=%s errors=%s' % (r.get('ok'), [str(x)[:50] for x in r.get('errors', [])[:1]]))
    except Exception as e:  # noqa: BLE001
        return False, '%s: %s' % (type(e).__name__, e)


def legal_via_api(src):
    r, e = api_result(src)
    return (e is None and r.success is True,
            e or 'success=%s errors=%s' % (r.success, [str(x)[:40] for x in r.errors[:1]]))


print('--- (1) 主守卫：引号数值不得假成功（修复前 success=True）---')

ok_a, d_a = rejected_by_api('若 条件空间 为 伴侣，则 止 情感权重 于 "0.9"。')
check('①a api 拒引号数值（于后期望数值）', ok_a, d_a)
ok_v, d_v = rejected_by_vm('若 条件空间 为 伴侣，则 止 情感权重 于 "0.9"。')
check('①b compiler 同拒', ok_v, d_v)

print('--- (2) 主守卫：于/等于后缺值不得静默丢弃 ---')

for tag, src in [('②a', '止 情感权重 于。'), ('②b', '止 情感权重 等于。')]:
    ok_1, d_1 = rejected_by_api(src)
    check('%s api 拒 %r' % (tag, src), ok_1, d_1)
    ok_2, d_2 = rejected_by_vm(src)
    check('%s compiler 拒' % tag, ok_2, d_2)

print('--- (3) 查表扩展：工作空间 0.05 上限生效（修复前从不检查）---')

ok_w1, d_w1 = rejected_by_api('若 条件空间 为 工作，则 止 情感权重 于 0.3。',
                              needle='0.05')
check('③a 工作空间比较式超限被拒（0.3 > 0.05）', ok_w1, d_w1)
ok_w2, d_w2 = rejected_by_api('条件空间 = 工作\n止情感权重于0.06。',
                              needle='0.05')
check('③b 工作空间赋值式超限被拒（0.06 > 0.05）', ok_w2, d_w2)
ok_w3, d_w3 = legal_via_api('若 条件空间 为 工作，则 止 情感权重 于 0.05。')
check('③c 工作空间上限内 0.05 合法', ok_w3, d_w3)

print('--- (4) 无「于」字符串降级形态闭包（止的阈值经字符串绕过）---')

ok_s1, d_s1 = legal_via_api('止 情感权重 "0.9"。')
check('④a 无空间时字符串操作数仍放行（既有）', ok_s1, d_s1)
ok_s2, d_s2 = rejected_by_api('若 条件空间 为 伴侣，则 止 情感权重 "0.9"。',
                              needle='0.15')
check('④b 伴侣空间止指令字符串阈值被拒（0.9 > 0.15）', ok_s2, d_s2)
ok_s3, d_s3 = legal_via_api('若 条件空间 为 伴侣，则 止 情感权重 "0.1"。')
check('④c 伴侣空间字符串阈值上限内合法（"0.1"）', ok_s3, d_s3)
ok_s4, d_s4 = legal_via_api('若 条件空间 为 伴侣，则 谷 "说明"。')
check('④d 非数值字符串操作数不受影响（"说明"）', ok_s4, d_s4)

print('--- (5) 伴侣消息逐字不变 + 默认/无空间不动 ---')

r5, e5 = api_result('若条件空间为伴侣，则止情感权重于1。')
check('⑤a 伴侣超限消息逐字不变（既有）',
      e5 is None and r5.success is False and
      r5.errors and r5.errors[0] == 'L1:C17 在「伴侣」条件空间中情感权重不可超过 0.15，当前值: 1.0',
      e5 or str(r5.errors[:1]))

for tag, src in [('⑤b', '止情感权重于0.9。'),
                 ('⑤c', '条件空间 = 默认\n止情感权重于0.9。'),
                 ('⑤d', '条件空间 = 恢复默认\n止情感权重于0.9。')]:
    ok, d = legal_via_api(src)
    check('%s %r 无空间/默认仍放行（既有钉死）' % (tag, src), ok, d)

print('--- (6) 合法于/等于形态不回归 ---')

LEGAL = [('⑥a', '若 条件空间 为 伴侣，则 止 情感权重 于 0.15。'),
         ('⑥b', '止 情感权重 于 0.3。'),
         ('⑥c', '止 情感权重 等于 阈值。'),
         ('⑥d', '止 情感权重 等于 0.3。')]
for tag, src in LEGAL:
    ok, d = legal_via_api(src)
    check('%s %r 仍编译成功' % (tag, src), ok, d)

print('\n=== 情感权重引号/缺值绕过守卫: %d/%d 通过 ===' % (pass_n, pass_n + fail_n))
sys.exit(0 if fail_n == 0 else 1)
