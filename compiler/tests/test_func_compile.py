# -*- coding: utf-8 -*-
"""test_func_compile.py · 中文函数定义/调用/递归（第六阶段第57轮）
「定义 名（参数）：语句」→ FUNC_DEF → 函数体后置 + CALL/RETURN 调用栈帧
→ VM 原生执行（递归通过 CALL 自身，对齐 P 线 P3 函数+递归语义）。
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

# ① 递归阶乘：定义 阶乘（n）… 结果 = 阶乘（4）
src = '''
定义 阶乘（n）：若 n 小于 2，则 返回 1，否则 返回 n 乘 阶乘（n 减 1）；
结果 = 阶乘（4）；
止。
'''
code, r = compile_source(src, strict=False)
check('① 函数源码编译成功', r["ok"] and not r["warnings"], str(r["warnings"])[:40])
if r["ok"]:
    ops = [op for op, _ in code]
    check('①b 字节码含 CALL 与 RETURN', Opcode.CALL in ops and Opcode.RETURN in ops, '')
    check('①c 字节码含跳过 JUMP（函数体后置）', Opcode.JUMP in ops, '')
    vm = ConditionVM()
    st = vm.run(code)
    check('①d 递归阶乘 4! = 24', st["symbols"].get("结果") == 24.0,
          f'阶乘(4)={st["symbols"].get("结果")}')

# ② 多函数 + 相互调用：定义 双倍（x）返回 x 乘 2；定义 计算（y）返回 双倍（y）
src2 = '''
定义 双倍（x）：返回 x 乘 2；
定义 计算（y）：返回 双倍（y）加 1；
结果 = 计算（5）；
止。
'''
code2, r2 = compile_source(src2, strict=False)
if r2["ok"]:
    vm2 = ConditionVM()
    st2 = vm2.run(code2)
    check('② 多函数互调（双倍(5)+1=11）', st2["symbols"].get("结果") == 11.0,
          f'结果={st2["symbols"].get("结果")}')
else:
    check('② 多函数互调（双倍(5)+1=11）', False, str(r2["errors"])[:40])

# ③ 参数作用域隔离：函数参数遮蔽同名全局（改（甲）内参数 x=1，全局甲不变）
src3 = '''
定义 改（x）：返回 x 乘 10；
甲 = 1；
乙 = 改（甲）；
止。
'''
code3, r3 = compile_source(src3, strict=False)
if r3["ok"]:
    vm3 = ConditionVM()
    st3 = vm3.run(code3)
    check('③ 参数作用域隔离（乙=10 甲仍=1）',
          st3["symbols"].get("乙") == 10.0 and st3["symbols"].get("甲") == 1.0,
          f'甲={st3["symbols"].get("甲")} 乙={st3["symbols"].get("乙")}')
else:
    check('③ 参数作用域隔离（乙=10 甲仍=1）', False, str(r3["errors"])[:40])

# ④ 递归深度：尾递归计数（定义 计数（n）：若 n 小于 1 则 返回 0 否则 返回 计数（n 减 1）加 1）
src4 = '''
定义 计数（n）：若 n 小于 1，则 返回 0，否则 返回 计数（n 减 1）加 1；
结果 = 计数（5）；
止。
'''
code4, r4 = compile_source(src4, strict=False)
if r4["ok"]:
    vm4 = ConditionVM()
    st4 = vm4.run(code4)
    check('④ 递归深度计数 计数(5)=5', st4["symbols"].get("结果") == 5.0,
          f'结果={st4["symbols"].get("结果")}')
else:
    check('④ 递归深度计数 计数(5)=5', False, str(r4["errors"])[:40])

# ⑤ 顶层 RETURN = 程序结束（无调用者时 halt）
src5 = '''
定义 早退（）：返回 7；
止。
'''
code5, r5 = compile_source(src5, strict=False)
if r5["ok"]:
    vm5 = ConditionVM()
    st5 = vm5.run(code5)
    check('⑤ 函数定义未调用不执行（直接到止）', st5["halt"] == "halt", '')

# ⑥ 双递归：斐波那契（两次自身调用，调用帧深度嵌套）
src6 = '''
定义 斐波那契（n）：若 n 小于 2，则 返回 n，否则 返回 斐波那契（n 减 1）加 斐波那契（n 减 2）；
结果 = 斐波那契（6）；
止。
'''
code6, r6 = compile_source(src6, strict=False)
if r6["ok"]:
    vm6 = ConditionVM()
    st6 = vm6.run(code6)
    check('⑥ 双递归斐波那契 fib(6)=8', st6["symbols"].get("结果") == 8.0,
          f'斐波那契(6)={st6["symbols"].get("结果")}')
else:
    check('⑥ 双递归斐波那契 fib(6)=8', False, str(r6["errors"])[:40])

# ⑦ 多参数递归：欧几里得 gcd（嵌套若则 × 双参数 × 递归）
src7 = '''
定义 最大公约数（甲，乙）：若 甲 等于 乙，则 返回 甲，否则 若 甲 大于 乙，则 返回 最大公约数（甲 减 乙，乙），否则 返回 最大公约数（甲，乙 减 甲）；
结果 = 最大公约数（48，36）；
止。
'''
code7, r7 = compile_source(src7, strict=False)
if r7["ok"]:
    vm7 = ConditionVM()
    st7 = vm7.run(code7)
    check('⑦ 多参数递归 gcd(48,36)=12', st7["symbols"].get("结果") == 12.0,
          f'gcd(48,36)={st7["symbols"].get("结果")}')
else:
    check('⑦ 多参数递归 gcd(48,36)=12', False, str(r7["errors"])[:40])

print(f'\n=== 中文函数（定义/调用/递归）测试: {pass_n}/{pass_n + fail_n} 通过 ===')
sys.exit(0 if fail_n == 0 else 1)