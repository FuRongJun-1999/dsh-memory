# -*- coding: utf-8 -*-
"""test_condition_space_alias_n270.py · 条件空间两模型脱钩三修守卫（N270）

缺陷（2026-10-05 本会话实跑复现，三条子证据；编号续 N269）：
  ① 别名绕过（静态名实校验 vs 运行期 VM 脱钩）：
     『甲 = 伴侣／条件空间 = 甲／止情感权重于0.9。』——静态
     name_checker._apply_space_assign_switch 只认直接空间名/字符串字面量，
     不跟随别名赋值；而运行期 VM 真切进「伴侣」空间（实测
     condition_space_name='伴侣'、condition_space=[{'name': '伴侣', ...}]）
     ——伴侣空间情感权重上限 0.15 只在 name_checker 静态独有，别名形态
     整体绕过（api/compiler 双入口均 success=True/ok=True，0.9 直达伴侣空间）。
  ② 字符串信任值：『信任值 = "0.9"』编译全绿（success=True 零警告）、
     运行期 Python VM 裸 TypeError（type str doesn't define __round__ method）；
     Rust VM 对信任值写非数值是结构化拒（vm.rs:412-418），两台 VM 必须一致
     （SEMANTICS.md:4-6）。
  ③ 负向条件误拒：『若 条件空间 不为 伴侣，则 止情感权重于0.9。』被
     _check_condition_space_switch 置上下文为伴侣——该检测不看比较运算符
     极性，负向条件（不为/不等于）then 内并不处于该空间，上限误报。

修复（N270）：
  a) 静态别名跟随：NameChecker 顺序流别名环境（甲=伴侣 ⇒ 甲 解析出「伴侣」；
     链式 甲→乙 传递；中途重赋值即失效），条件空间赋值与比较两处的空间名
     解析单点收口（_resolve_space_name）。别名环境是**顺序流的单一全局字典**
     （不做块级保存/还原）——块内赋值会沿用至块外，这是**故意的 fail-closed
     取舍**：上限判据（CONDITION_SPACE_RULES）只在静态侧独有，若块内别名不外推，
     「若…则 甲 = 伴侣。」之后的『条件空间 = 甲』将整体绕过上限（正是本缺陷本相）。
     代价是分支不执行的少数形态可能被过度拒绝（如『若 0 大于 1，则 甲 = 伴侣。』
     之后『条件空间 = 甲』仍按「伴侣」上限判）——已知保守边界，判定方向只紧不松。
  b) 极性感知：正向比较（为/等于）then 内生效、else 不沿用；负向比较
     （不为/不等于）then 内不沿用、else 生效；条件语句结束恢复外层空间
     （此前无条件置 None，使条件语句后的已知空间丢失）。
  c) Python VM 对 条件空间 写非字符串加结构化拒绝（对齐 Rust vm.rs:420-429）、
     对 信任值/信任分量 写非数值同款结构化拒——与注入初值闸同点收口
     （STORE_NAME/reset 单点，不另立第二份判据）。

本文件把语义钉死，防止回归：
  ① 别名/字符串别名/链式/重赋值（更新到最新 / 失效）/恢复默认别名的静态跟随
  ② 极性四象限（正向 then/else、负向 then/else、无空格形态）
  ③ 运行期真实切换语义不回归（别名切换在 VM 上仍真实生效）
  ④ Python VM 写类型闸结构化拒绝（非 TypeError 裸穿）+ 遮蔽消除
"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compiler.api import compile_source as api_compile
from compiler.compiler import compile_source as vm_compile
from compiler.condition_vm import ConditionVM, Opcode
from compiler import condition_vm as vmm

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


def rejected_by_api(src, needle='0.15'):
    r, e = api_no_crash(src)
    return (e is None and r is not None and r.success is False
            and any(needle in x for x in r.errors),
            e or 'success=%s errors=%s' % (getattr(r, 'success', None),
                                           [str(x)[:60] for x in getattr(r, 'errors', [])[:1]]))


def rejected_by_vm(src, needle='0.15'):
    try:
        code, r = vm_compile(src, strict=True)
        return (r.get('ok') is False
                and any(needle in str(x) for x in r.get('errors', [])),
                'ok=%s errors=%s' % (r.get('ok'), [str(x)[:60] for x in r.get('errors', [])[:1]]))
    except Exception as e:  # noqa: BLE001
        return False, '%s: %s' % (type(e).__name__, e)


def legal_via_api(src):
    r, e = api_no_crash(src)
    return (e is None and r is not None and r.success is True,
            e or 'success=%s errors=%s' % (getattr(r, 'success', None),
                                           [str(x)[:60] for x in getattr(r, 'errors', [])[:1]]))


print('--- (1) 别名绕过消除：甲 = 伴侣／条件空间 = 甲／止情感权重于0.9 ---')

ALIAS_ATTACKS = [
    ('①a 直接别名', '甲 = 伴侣\n条件空间 = 甲\n止情感权重于0.9。', '0.15'),
    ('①b 字符串别名', '甲 = "伴侣"\n条件空间 = 甲\n止情感权重于0.9。', '0.15'),
    ('①c 链式别名 甲→乙', '甲 = 伴侣\n乙 = 甲\n条件空间 = 乙\n止情感权重于0.9。', '0.15'),
    ('①d 工作空间别名', '甲 = 工作\n条件空间 = 甲\n止情感权重于0.06。', '0.05'),
]
for tag, src, needle in ALIAS_ATTACKS:
    ok_a, d_a = rejected_by_api(src, needle)
    check('%s api 拒绝（修复前 success=True）' % tag, ok_a, d_a)
    ok_v, d_v = rejected_by_vm(src, needle)
    check('%s compiler 同拒' % tag, ok_v, d_v)

print('--- (2) 重赋值：更新到最新 / 失效为普通值 ---')

ok, d = rejected_by_api('甲 = 工作\n甲 = 伴侣\n条件空间 = 甲\n止情感权重于0.9。')
check('②a 重赋值后跟随最新空间名（工作→伴侣）', ok, d)

r2b, e2b = api_no_crash('甲 = 伴侣\n甲 = 1.0\n条件空间 = 甲\n止情感权重于0.9。')
check('②b 重赋值为非空间值 → 别名失效、不再误报伴侣上限',
      e2b is None and r2b is not None and r2b.success is True
      and any('未知的条件空间' in w for w in r2b.warnings),
      e2b or 'success=%s warnings=%s' % (getattr(r2b, 'success', None),
                                         getattr(r2b, 'warnings', [])[:1]))

ok, d = legal_via_api('甲 = 伴侣\n甲 = "说明"\n条件空间 = 甲\n止情感权重于0.9。')
check('②c 重赋值为普通字符串 → 别名失效', ok, d)

ok, d = legal_via_api('甲 = 恢复默认\n条件空间 = 甲\n止情感权重于0.9。')
check('②d 恢复默认别名 → 默认空间放行（0.9 合法）', ok, d)

ok, d = legal_via_api('甲 = 伴侣\n条件空间 = 甲\n止情感权重于0.15。')
check('②e 别名切换后上限内仍合法（0.15）', ok, d)

print('--- (3) 极性四象限（为/不为 × then/else）---')

ok, d = rejected_by_api('若 条件空间 为 伴侣，则 止情感权重于0.9。')
check('③a 正向 then 内生效（既有语义回归）', ok, d)

ok, d = legal_via_api('若 条件空间 为 伴侣，则 德 0.1 否则 止情感权重于0.9。')
check('③b 正向 else 不沿用（修复前误拦）', ok, d)

ok, d = legal_via_api('若 条件空间 不为 伴侣，则 止情感权重于0.9。')
check('③c 负向 then 不沿用（修复前误拒）', ok, d)
try:
    code, rr = vm_compile('若 条件空间 不为 伴侣，则 止情感权重于0.9。', strict=True)
    check('③c2 compiler 入口同判（负向不再误拒）', rr.get('ok') is True,
          'ok=%s errors=%s' % (rr.get('ok'), [str(x)[:60] for x in rr.get('errors', [])[:1]]))
except Exception as e:  # noqa: BLE001
    check('③c2 compiler 入口同判（负向不再误拒）', False, '%s: %s' % (type(e).__name__, e))

ok, d = rejected_by_api('若 条件空间 不为 伴侣，则 德 0.1 否则 止情感权重于0.9。')
check('③d 负向 else 生效（else 意味着 == 伴侣）', ok, d)

ok, d = legal_via_api('若条件空间不为伴侣，则止情感权重于0.9。')
check('③e 无空格负向形态（lexer 定向断开）同不误拒', ok, d)

ok, d = rejected_by_api('若条件空间为伴侣，则止情感权重于0.9。')
check('③f 无空格正向攻击样例仍拒绝（既有守卫回归）', ok, d)

print('--- (4) 运行期真实切换语义不回归 ---')

code4, r4 = vm_compile('甲 = 伴侣\n条件空间 = 甲\n德 0.1。', strict=True)
if r4.get('ok'):
    st4 = ConditionVM().run(code4)
    check('④a 别名切换在 VM 上真实生效（空间=伴侣、德 0.1）',
          st4['condition_space_name'] == '伴侣' and st4['trust'] == 0.1,
          'space=%s trust=%s' % (st4['condition_space_name'], st4['trust']))
else:
    check('④a 别名切换在 VM 上真实生效（空间=伴侣、德 0.1）', False,
          'ok=%s errors=%s' % (r4.get('ok'), [str(x)[:60] for x in r4.get('errors', [])[:1]]))

code4b, r4b = vm_compile('甲 = "工作"\n条件空间 = 甲\n德 0.05。', strict=True)
if r4b.get('ok'):
    st4b = ConditionVM().run(code4b)
    check('④b 字符串别名切换真实生效（空间=工作；0.05 不超工作上限）',
          st4b['condition_space_name'] == '工作', str(st4b['condition_space_name']))
else:
    check('④b 字符串别名切换真实生效（空间=工作；0.05 不超工作上限）', False,
          'ok=%s errors=%s' % (r4b.get('ok'), [str(x)[:60] for x in r4b.get('errors', [])[:1]]))

print('--- (5) Python VM 写类型闸：结构化拒绝（对齐 Rust，不裸异常）---')


def run_raw(instrs):
    return ConditionVM().run(instrs)


# ⑤a 条件空间写数值 → 结构化拒（修复前数字成空间名 cond_name=0.9）
try:
    run_raw([(Opcode.PUSH_CONST, 0.9), (Opcode.STORE_NAME, '条件空间'),
             (Opcode.ZHI, None)])
    check('⑤a 条件空间写数值结构化拒', False, '未拒（数字成空间名）')
except vmm.VMBuiltinError as e:
    check('⑤a 条件空间写数值结构化拒', '只能写空间名' in str(e), str(e)[:80])
except Exception as e:  # noqa: BLE001
    check('⑤a 条件空间写数值结构化拒', False, '裸异常 %s: %s' % (type(e).__name__, e))

# ⑤b 信任值写字符串 → 结构化拒（修复前裸 TypeError 在 round）
try:
    run_raw([(Opcode.PUSH_CONST, '0.9'), (Opcode.STORE_NAME, '信任值'),
             (Opcode.ZHI, None)])
    check('⑤b 信任值写字符串结构化拒', False, '未拒')
except vmm.VMBuiltinError as e:
    check('⑤b 信任值写字符串结构化拒', '只能写数值' in str(e), str(e)[:80])
except Exception as e:  # noqa: BLE001
    check('⑤b 信任值写字符串结构化拒', False, '裸异常 %s: %s' % (type(e).__name__, e))

# ⑤c 信任分量写字符串 → 结构化拒（修复前无闸）
try:
    run_raw([(Opcode.PUSH_CONST, 'x'), (Opcode.STORE_NAME, 'P_trust'),
             (Opcode.ZHI, None)])
    check('⑤c 信任分量写字符串结构化拒', False, '未拒')
except vmm.VMBuiltinError as e:
    check('⑤c 信任分量写字符串结构化拒', '只能写数值' in str(e), str(e)[:80])
except Exception as e:  # noqa: BLE001
    check('⑤c 信任分量写字符串结构化拒', False, '裸异常 %s: %s' % (type(e).__name__, e))

# ⑤d 注入口径对齐 Rust：信任值初值非数值 → 结构化拒；条件空间初值非字符串 → 不切换
try:
    ConditionVM().run([(Opcode.ZHI, None)], symbols={'信任值': 'x'})
    check('⑤d 信任值注入初值非数值结构化拒', False, '未拒')
except vmm.VMBuiltinError as e:
    check('⑤d 信任值注入初值非数值结构化拒', '初值需数值' in str(e), str(e)[:80])
except Exception as e:  # noqa: BLE001
    check('⑤d 信任值注入初值非数值结构化拒', False, '裸异常 %s: %s' % (type(e).__name__, e))

st5 = ConditionVM().run([(Opcode.ZHI, None)], symbols={'条件空间': 0.9})
check('⑤e 条件空间注入初值非字符串不切换（对齐 Rust 语义）',
      st5['condition_space_name'] == '默认', str(st5['condition_space_name']))

# ⑤f 合法写入不回归
st6 = ConditionVM().run([(Opcode.PUSH_CONST, 0.9), (Opcode.STORE_NAME, '信任值'),
                         (Opcode.PUSH_CONST, '伴侣'), (Opcode.STORE_NAME, '条件空间'),
                         (Opcode.ZHI, None)])
check('⑤f 合法写入（信任值=0.9 数值 / 条件空间=伴侣 字符串）不回归',
      st6['trust'] == 0.9 and st6['condition_space_name'] == '伴侣',
      'trust=%s space=%s' % (st6['trust'], st6['condition_space_name']))

print('\n=== N270 条件空间别名/极性/写类型闸守卫: %d/%d 通过 ==='
      % (pass_n, pass_n + fail_n))
sys.exit(0 if fail_n == 0 else 1)
