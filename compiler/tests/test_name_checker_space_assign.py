# -*- coding: utf-8 -*-
"""test_name_checker_space_assign.py · 赋值形态条件空间切换的上下文联动守卫（2026-09-25）

缺陷（缺陷19 new，N6 同威胁模型经赋值形态复活）：
  赋值「条件空间 = 伴侣」是 SEMANTICS.md §1.2 明文切换机制，VM 侧
  STORE_NAME 对 BUILTIN_CONDITION_SPACE 真调 _switch_condition_space
  （condition_vm.py:208-213），但 name_checker._check_assign 无切换检测——
  赋值切换后「伴侣」空间约束（情感权重上限 0.15）整体失效：
  『条件空间 = 伴侣\\n止情感权重于0.9。』双官方入口（api/compiler）均过审。

修复：_check_assign 对 target==条件空间 的赋值对齐
_check_condition_space_switch 设检查上下文（合法赋值仍通过，只补联动）。

本文件把语义钉死，防止回归：
  ① 赋值切换后超限值被拒（plain/string/术曰嵌套三形态、双入口）
  ② 比较式形态既有拒绝语义不变
  ③ 合法赋值切换（上限内/白名单指令/恢复默认/既有回归用例）仍通过
  ④ 未知空间名沿比较式同款「仅警告」语义
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
    try:
        return api_compile(src), None
    except Exception as e:  # noqa: BLE001
        return None, '%s: %s' % (type(e).__name__, e)


def rejected_by_api(src):
    r, e = api_no_crash(src)
    return (e is None and r is not None and r.success is False
            and any('0.15' in x or '情感权重' in x for x in r.errors),
            e or 'success=%s errors=%s' % (getattr(r, 'success', None),
                                           [str(x)[:50] for x in getattr(r, 'errors', [])[:1]]))


def rejected_by_vm(src):
    try:
        code, r = vm_compile(src, strict=True)
        return (r.get('ok') is False
                and any('0.15' in str(x) or '情感权重' in str(x) for x in r.get('errors', [])),
                'ok=%s errors=%s' % (r.get('ok'), [str(x)[:50] for x in r.get('errors', [])[:1]]))
    except Exception as e:  # noqa: BLE001
        return False, '%s: %s' % (type(e).__name__, e)


print('--- (1) 主守卫：赋值切换后超限被拒（修复前 success=True 过审）---')

ok1, d1 = rejected_by_api('条件空间 = 伴侣\n止情感权重于0.9。')
check('①a api 拒绝并点名 0.15 上限', ok1, d1)
ok1b, d1b = rejected_by_vm('条件空间 = 伴侣\n止情感权重于0.9。')
check('①b compiler.compile_source 同拒', ok1b, d1b)

print('--- (2) 三种源码形态 × 双入口 ---')

FORMS = [('②a', 'plain 顶层', '条件空间 = 伴侣\n止情感权重于0.9。'),
         ('②b', 'string 形态', '条件空间 = "伴侣"\n止情感权重于0.9。'),
         ('②c', '术曰嵌套', '术曰：\n1。条件空间 = 伴侣；\n2。止情感权重于0.9。')]
for tag, name, src in FORMS:
    ok_a, d_a = rejected_by_api(src)
    check('%s api 拒绝（%s）' % (tag, name), ok_a, d_a)
    ok_v, d_v = rejected_by_vm(src)
    check('%s compiler 拒绝（%s）' % (tag, name), ok_v, d_v)

print('--- (3) 比较式形态既有拒绝语义不变（对照）---')

ok3, d3 = rejected_by_api('若条件空间为伴侣，则止情感权重于0.9。')
check('③a 比较式仍被拒（既有行为）', ok3, d3)

print('--- (4) 合法赋值切换仍通过 ---')

LEGAL = [('④a', '上限内 0.15', '条件空间 = 伴侣\n止情感权重于0.15。'),
         ('④b', '白名单指令 德 0.1',
          '术曰：\n1。条件空间 = 伴侣；\n2。若 条件空间 为 伴侣，则 德 0.1；\n3。止。'),
         ('④c', '恢复默认弹栈后不再受限',
          '条件空间 = 伴侣\n条件空间 = 恢复默认\n止情感权重于0.9。'),
         ('④d', '写 默认 直切默认空间', '条件空间 = 默认\n止情感权重于0.9。'),
         ('④e', '无切换时默认放行（既有）', '止情感权重于0.9。')]
for tag, name, src in LEGAL:
    r, e = api_no_crash(src)
    check('%s %r 仍编译成功' % (tag, name),
          e is None and r is not None and r.success is True,
          e or 'success=%s errors=%s warnings=%s' % (r.success, r.errors[:1], r.warnings[:1]))

print('--- (5) 未知空间名：沿比较式「仅警告」语义（不放行错误值也不误杀）---')

r5, e5 = api_no_crash('条件空间 = 未知空间\n止情感权重于0.9。')
check('⑤a 未知空间名仅警告、编译仍成功（对齐比较式 :843-846）',
      e5 is None and r5 is not None and r5.success is True
      and any('未知的条件空间' in w for w in r5.warnings),
      e5 or 'success=%s warnings=%s' % (r5.success, r5.warnings[:1]))

r5b, e5b = api_no_crash('条件空间 = 0.9。')
check('⑤b 非空间名赋值（数值）不受影响仍成功',
      e5b is None and r5b is not None and r5b.success is True,
      e5b or 'success=%s' % r5b.success)

print('\n=== 赋值切换上下文联动守卫: %d/%d 通过 ===' % (pass_n, pass_n + fail_n))
sys.exit(0 if fail_n == 0 else 1)
