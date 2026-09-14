# -*- coding: utf-8 -*-
"""test_defect_regression.py · 4 个实测缺陷的回归测试（2026-09-14）

外部测试发现的 4 个真实缺陷，本文件把修复后的语义钉死，防止回归：

  ① 解析器：while 循环体贪心吞语句
     —— 「当…执行 A。B。」修复前把 B 吞进循环体；无步骤编号时把其后全部
        顶层语句吞入 → 若该语句重新武装循环条件即死循环 RecursionError。
     语义裁定：。 = 全句终止（块结束）；； = 块内续接（多语句用分号）。

  ② VM：信任值 标识符 与 trust_value 寄存器互不通信
     —— 修复前 德 只改寄存器，源码引用 信任值 在 symbols 查表必 NameError。
     修复：信任值 是内建名，读写都落在 trust_value 寄存器（名实一处存储）。

  ③ VM：条件空间 切换不可执行
     —— 修复前「若 条件空间 为 伴侣」把 条件空间/伴侣 当运行时符号查表 → NameError
        （编译期名实校验放行，运行期死代码）。修复后为真实运行期比较 + 可切换。

  ④ 语义确认（非缺陷）：知足 是「向前跳到程序末尾」的早退原语 ——
     达标即跳末尾，其后 止 被跳过（halt=None）。测试须据此设计。

另含一致性守卫：VM 内建名表 与 name_checker.PREDEFINED_SYMBOLS 的
条件空间/信任类符号必须一一对应（防两侧再次漂移）。
"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compiler.compiler import compile_source
from compiler.condition_vm import ConditionVM, Opcode
from compiler.lexer import tokenize
from compiler.parser import parse_tokens, NodeType

pass_n = fail_n = 0


def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print('[%s] %s%s' % ('OK ' if ok else 'FAIL', name, ' — ' + detail if detail else ''))


def top_types(src):
    """返回顶层语句类型名列表（观察块边界）"""
    toks, errs = tokenize(src)
    if errs:
        return ['LEXERR:' + str(errs[0])]
    ast = parse_tokens(toks, [])
    return [s.type.name for s in ast.statements]


# =============================================================================
# ① 循环体贪心吞语句
# =============================================================================
print('--- (1) while 循环体贪心吞语句 ---')

src_n = '当 计数 小于 3 执行 计数 = 计数 + 1。计数 = 0。'
types_n = top_types(src_n)
check('①a 「。」终止循环体（后续语句归顶层：LOOP + ASSIGN）',
      types_n == ['LOOP_STMT', 'ASSIGN_STMT'], str(types_n))

code_n, r_n = compile_source(src_n)
if r_n['ok']:
    try:
        st_n = ConditionVM().run(code_n, symbols={'计数': 0}, max_steps=2000)
        check('①b 不被吞语句重新武装条件（不再 RecursionError）',
              st_n['symbols'].get('计数') == 0,
              'count=%s' % st_n['symbols'].get('计数'))
    except RecursionError as e:
        check('①b 不被吞语句重新武装条件（不再 RecursionError）', False, 'still loops: %s' % e)
else:
    check('①b 无步骤编号编译成功', False, str(r_n['errors'])[:60])

src_semi = '当 计数 小于 3 执行 计数 = 计数 + 1；德 0.1。止。'
types_semi = top_types(src_semi)
check('①c 「；」仍续接循环体（LOOP + ZHI/INSTRUCTION 两项）',
      types_semi == ['LOOP_STMT', 'INSTRUCTION_STMT'], str(types_semi))
code_semi, r_semi = compile_source(src_semi)
if r_semi['ok']:
    st_semi = ConditionVM().run(code_semi, symbols={'计数': 0})
    check('①d 分号体语义（循环 3 次 德 0.1x3=0.3，循环外止）',
          st_semi['symbols'].get('计数') == 3.0 and st_semi['trust'] == 0.3
          and st_semi['halt'] == 'halt',
          'count=%s trust=%s halt=%s' % (st_semi['symbols'].get('计数'),
                                         st_semi['trust'], st_semi['halt']))
else:
    check('①d 分号体编译成功', False, str(r_semi['errors'])[:60])


# =============================================================================
# ② 信任值 <-> trust_value 寄存器
# =============================================================================
print('--- (2) 信任值 标识符 <-> trust_value 寄存器 ---')

src_t = '术曰：\n1。若 信任值 大于 0.3，则 德 0.5；\n2。止。'
code_t, r_t = compile_source(src_t, strict=False)
check('②a 引用 信任值 编译通过', r_t['ok'], str(r_t['errors'])[:50])

if r_t['ok']:
    try:
        s_hi = ConditionVM().run(code_t, trust=0.5)
        check('②b 信任值 可读（0.5>0.3 成立 → 1.0，无 NameError）',
              s_hi['trust'] == 1.0 and s_hi['halt'] == 'halt',
              'trust=%s halt=%s' % (s_hi['trust'], s_hi['halt']))
    except NameError as e:
        check('②b 信任值 可读（无 NameError）', False, str(e))
    s_lo = ConditionVM().run(code_t, trust=0.1)
    check('②c 条件为假（0.1>0.3 不成立 → 信任不变 0.1）', s_lo['trust'] == 0.1,
          'trust=%s' % s_lo['trust'])
    s_sym = ConditionVM().run(code_t, symbols={'信任值': 0.5})
    check('②d symbols 注入的信任值 归一为寄存器初值', s_sym['trust'] == 1.0,
          'trust=%s' % s_sym['trust'])

src_sync = '术曰：\n1。德 0.4；\n2。若 信任值 大于 0.3，则 德 0.1；\n3。止。'
code_sync, r_sync = compile_source(src_sync, strict=False)
if r_sync['ok']:
    s_sync = ConditionVM().run(code_sync)
    check('②e 德→寄存器→信任值 同源（0+0.4=0.4>0.3 → +0.1 = 0.5）',
          s_sync['trust'] == 0.5, 'trust=%s' % s_sync['trust'])
else:
    check('②e 编译成功', False, str(r_sync['errors'])[:60])

src_w = '术曰：\n1。信任值 = 0.9；\n2。止。'
code_w, r_w = compile_source(src_w, strict=False)
if r_w['ok']:
    s_w = ConditionVM().run(code_w)
    check('②f 写 信任值 → 落寄存器（trust=0.9）', s_w['trust'] == 0.9,
          'trust=%s' % s_w['trust'])
else:
    check('②f 写 信任值 编译通过', False, str(r_w['errors'])[:60])


# =============================================================================
# ③ 条件空间：可执行 + 可切换
# =============================================================================
print('--- (3) 条件空间 切换在 VM 可执行 ---')

src_cs = '术曰：\n1。若 条件空间 为 伴侣，则 德 0.1；\n2。止。'
code_cs, r_cs = compile_source(src_cs, strict=False)
check('③a 条件空间比较编译通过', r_cs['ok'], str(r_cs['errors'])[:50])

if r_cs['ok']:
    try:
        s_def = ConditionVM().run(code_cs)
        check('③b 默认空间下比较为假（无 NameError，德不执行）',
              s_def['trust'] == 0.0 and s_def['condition_space_name'] == '默认'
              and s_def['halt'] == 'halt',
              'trust=%s space=%s' % (s_def['trust'], s_def['condition_space_name']))
    except NameError as e:
        check('③b 默认空间下比较为假（无 NameError）', False, str(e))
    s_par = ConditionVM().run(code_cs, symbols={'条件空间': '伴侣'})
    check('③c 播种空间=伴侣 → 比较为真 → 德 0.1',
          s_par['trust'] == 0.1 and s_par['condition_space_name'] == '伴侣',
          'trust=%s space=%s' % (s_par['trust'], s_par['condition_space_name']))

src_sw = '术曰：\n1。条件空间 = 伴侣；\n2。若 条件空间 为 伴侣，则 德 0.1；\n3。止。'
code_sw, r_sw = compile_source(src_sw, strict=False)
if r_sw['ok']:
    s_sw = ConditionVM().run(code_sw)
    check('③d 写 条件空间 → 切换生效（切到伴侣后分支执行）',
          s_sw['condition_space_name'] == '伴侣' and s_sw['trust'] == 0.1,
          'space=%s trust=%s' % (s_sw['condition_space_name'], s_sw['trust']))
else:
    check('③d 写 条件空间 编译通过', False, str(r_sw['errors'])[:60])


# =============================================================================
# ④ 知足：向前跳到程序末尾的早退原语（语义确认，非缺陷）
# =============================================================================
print('--- (4) 知足 早退语义 ---')

src_z_hi = '术曰：\n1。德 0.8；\n2。知足 0.7；\n3。止。'
code_zh, r_zh = compile_source(src_z_hi)
if r_zh['ok']:
    s_zh = ConditionVM().run(code_zh)
    check('④a 达标即跳末尾 → 其后 止 被跳过（halt=None）',
          s_zh['trust'] == 0.8 and s_zh['halt'] is None,
          'trust=%s halt=%r' % (s_zh['trust'], s_zh['halt']))
else:
    check('④a 编译成功', False, str(r_zh['errors'])[:60])

src_z_lo = '术曰：\n1。德 0.3；\n2。知足 0.7；\n3。止。'
code_zl, r_zl = compile_source(src_z_lo)
if r_zl['ok']:
    s_zl = ConditionVM().run(code_zl)
    check('④b 未达标不跳 → 止 正常生效（halt=halt）',
          s_zl['trust'] == 0.3 and s_zl['halt'] == 'halt',
          'trust=%s halt=%r' % (s_zl['trust'], s_zl['halt']))
else:
    check('④b 编译成功', False, str(r_zl['errors'])[:60])


# =============================================================================
# ⑤ 一致性守卫：VM 内建名表 <-> name_checker 声明（防两侧漂移）
# =============================================================================
print('--- (5) VM 内建名 与 name_checker 声明一致性 ---')
try:
    from compiler.name_checker import PREDEFINED_SYMBOLS, SymbolKind
    from compiler import condition_vm as vmm

    declared_spaces = {n for n, s in PREDEFINED_SYMBOLS.items()
                       if s.kind == SymbolKind.CONDITION_SPACE}
    vm_spaces = set(vmm.CONDITION_SPACE_NAMES) | {vmm.BUILTIN_CONDITION_SPACE}
    check('⑤a 条件空间符号名两侧一致', vm_spaces == declared_spaces,
          'vm-only=%s declared-only=%s' % (sorted(vm_spaces - declared_spaces),
                                           sorted(declared_spaces - vm_spaces)))

    trust_kinds = {SymbolKind.TRUST_VALUE, SymbolKind.P_TRUST, SymbolKind.T_PRED,
                   SymbolKind.T_CONTEXT, SymbolKind.E_WEIGHT,
                   SymbolKind.EMOTIONAL_WEIGHT, SymbolKind.TRUST_THRESHOLD}
    declared_trust = {n for n, s in PREDEFINED_SYMBOLS.items() if s.kind in trust_kinds}
    vm_trust = {vmm.BUILTIN_TRUST_VALUE, vmm.BUILTIN_TRUST_THRESHOLD} | set(vmm.TRUST_COMPONENT_NAMES)
    check('⑤b 信任类符号名两侧一致', vm_trust == declared_trust,
          'vm-only=%s declared-only=%s' % (sorted(vm_trust - declared_trust),
                                           sorted(declared_trust - vm_trust)))
except Exception as exc:
    check('⑤ VM 与 name_checker 一致性检查', False, '%s: %s' % (type(exc).__name__, exc))


print('\n=== 缺陷回归测试: %d/%d 通过 ===' % (pass_n, pass_n + fail_n))
sys.exit(0 if fail_n == 0 else 1)
