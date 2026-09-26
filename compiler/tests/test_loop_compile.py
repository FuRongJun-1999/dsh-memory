# -*- coding: utf-8 -*-
"""test_loop_compile.py · 中文循环语法（当…执行）端到端测试（第六阶段第49轮）
「当 条件 执行 操作」→ AST(LOOP_STMT) → 字节码(条件→JIF跳出→体→JUMP回条件)
→ VM 原生执行（零 Python 运行时）。对齐白箱「编译-循环」单元语义。
"""
import os
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from compiler.compiler import compile_source
from compiler.condition_vm import ConditionVM, Opcode

pass_n = fail_n = 0
# 生效条件：调用须传 name 与 ok，ok 为真时全局 pass_n 加 1、为假时 fail_n 加 1；detail 为真值（非空串）时打印行追加 " — " + detail，detail 为默认空串时只打印 name。
def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')

# ① 循环编译：当 计数 小于 3 执行 计数 = 计数 + 1
src = '''
术曰：
1。当 计数 小于 3 执行 计数 = 计数 + 1；
2。德 0.6。
'''
code, r = compile_source(src)
check('①a 循环源码编译成功', r["ok"], str(r.get("errors", []))[:40])
ops = [op for op, _ in code] if r["ok"] else []
check('①b 字节码含条件跳转(JUMP_IF_FALSE)', Opcode.JUMP_IF_FALSE in ops,
      f'{len(code)} 条指令')
check('①c 字节码含回跳(JUMP)', Opcode.JUMP in ops, '')
check('①d 字节码含算术(ADD)', Opcode.ADD in ops, '')

# ② VM 执行：计数 0→3（循环 3 次）
if r["ok"]:
    vm = ConditionVM()
    state = vm.run(code, symbols={'计数': 0})
    check('② 循环执行 计数 0→3', state["symbols"].get("计数") == 3.0,
          f'计数={state["symbols"].get("计数")}')

# ③ 循环+后续语句：循环推进计数 3 次后，德 0.6（循环后语句正常执行）
src3 = '''
术曰：
1。当 计数 小于 3 执行 计数 = 计数 + 1；
2。德 0.6。
'''
code3, r3 = compile_source(src3)
if r3["ok"]:
    vm3 = ConditionVM()
    st3 = vm3.run(code3, symbols={'计数': 0})
    check('③ 循环后语句执行（计数=3 信任=0.6）',
          st3["symbols"].get("计数") == 3.0 and st3["trust"] == 0.6,
          f'计数={st3["symbols"].get("计数")} trust={st3["trust"]}')

# ④ 条件恒假 → 循环零次（体不执行）
src4 = '''
术曰：
1。当 计数 大于 5 执行 德 0.2；
2。德 0.6。
'''
code4, r4 = compile_source(src4)
if r4["ok"]:
    vm4 = ConditionVM()
    st4 = vm4.run(code4, symbols={'计数': 0})
    check('④ 条件恒假循环零次（信任仍 0.6）', st4["trust"] == 0.6,
          f'trust={st4["trust"]}')

# ⑤ 死循环被步数上限拦截（max_steps 保护）
src5 = '''
术曰：
1。当 计数 大于 0 执行 德 0.1；
'''
code5, r5 = compile_source(src5)
if r5["ok"]:
    vm5 = ConditionVM()
    try:
        vm5.run(code5, symbols={'计数': 1}, max_steps=1000)
        check('⑤ 死循环步数上限拦截', False, '未拦截（无限执行）')
    except RecursionError as e:
        check('⑤ 死循环步数上限拦截', '循环未终止' in str(e), str(e)[:40])

# ⑥ 与白箱「编译-循环」单元对照：字节码形态一致
# 白箱单元: [cond..., JIF exit, body..., JUMP 0]（相对编译；这里标签回填绝对地址）
if r["ok"]:
    jif = next(i for i, (op, _) in enumerate(code) if op == Opcode.JUMP_IF_FALSE)
    jump = next(i for i, (op, _) in enumerate(code) if op == Opcode.JUMP)
    exit_addr = code[jif][1]
    check('⑥ 循环结构对照（JIF跳出→体→JUMP回条件）',
          exit_addr == jump + 1 and code[jump][1] == 1,
          f'JIF→{exit_addr} JUMP→{code[jump][1]}')

# ⑦ 循环体块（多语句：赋值;若则）+ 嵌套条件（控制流组合）
src7 = '''
术曰：
1。当 计数 小于 3 执行 计数 = 计数 + 1；若 计数 大于 1，则 德 0.1；
2。止。
'''
code7, r7 = compile_source(src7)
if r7["ok"]:
    vm7 = ConditionVM()
    st7 = vm7.run(code7, symbols={'计数': 0})
    check('⑦ 循环体块+嵌套条件（计数0→3 信任0.2 循环外止）',
          st7["symbols"].get("计数") == 3.0 and st7["trust"] == 0.2
          and st7["halt"] == "halt",
          f'计数={st7["symbols"].get("计数")} trust={st7["trust"]} halt={st7["halt"]}')

# ⑧ 条件体内块（若则多语句）：若 计数 大于 0 则 德 0.1；德 0.1；止
# 批次37 语义更正：本源码含真实语法错误（L4 步骤「2。」的 NUMBER 开头
# parser 报「无法解析的语句开头」）——旧用例 11/11 通过依赖的是
# compiler/parser.py「errors or []」吞错假成功（批次37 缺陷#5 已修），
# 修复后含错源码必须如实报错。断言改为「编译失败且错误可见」；
# 待步骤号语法支持补齐后可还原为执行断言（trust==0.2）。
# N4 修复（2026-09-26）即该注所待的语法补齐：then 体改
# _parse_statement_or_block（『；』同局限接 + 步骤号边界），源码由
# 「语法错误」转为合法解析——步骤 1 条件体两语句同受门控、步骤 2 止。
# 按本注预言还原为执行断言：字节码两 DE 均在 JUMP_IF_FALSE/JUMP 之间
# （门控），播种 计数=1 执行 trust==0.2；未播种时 VM 运行期 NameError
# （名实不符，运行期名实校验如实生效）。
src8 = '''
术曰：
1。若 计数 大于 0，则 德 0.1；德 0.1；
2。止。
'''
code8, r8 = compile_source(src8)
check('⑧ 条件体多语句合法编译（N4 后步骤号语法补齐）',
      r8["ok"],
      str(r8.get("errors", []))[:60])
if r8["ok"]:
    ops8 = [op.name for op, _ in code8]
    _ji, _ju = (ops8.index("JUMP_IF_FALSE"), ops8.index("JUMP"))
    check('⑧b 两处 德 均受条件门控（JUMP_IF_FALSE 与 JUMP 之间）',
          ops8[_ji + 1:_ju] == ["DE", "DE"] and ops8[_ju + 1] == "ZHI",
          str(ops8))
    st8 = ConditionVM().run(code8, symbols={"计数": 1})
    check('⑧c 执行断言还原：计数=1 → trust==0.2',
          st8["trust"] == 0.2,
          f'trust={st8["trust"]}')
    try:
        ConditionVM().run(code8)
        _name_err = False
    except NameError:
        _name_err = True
    check('⑧d 未声明 计数 时运行期 NameError（名实校验不缺席）',
          _name_err, '')

print(f'\n=== 中文循环语法（当…执行）测试: {pass_n}/{pass_n + fail_n} 通过 ===')
sys.exit(0 if fail_n == 0 else 1)