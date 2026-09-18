# -*- coding: utf-8 -*-
"""test_condition_vm.py · 智能论字节码 VM 测试（第六阶段 C1）
验证：①道→德→知足→止 ②条件空间栈（DAO/ZIRAN）③JUMP_IF_FALSE（若则）④名实符号表
⑤WUWEI 让出 ⑥ZHI 停止 ⑦汇编标签 ⑧未知指令/名实不符错误"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from compiler.condition_vm import ConditionVM, Opcode, VMHalt, assemble

pass_n = fail_n = 0
# 生效条件：调用须传 name 与 ok，ok 为真时全局 pass_n 加 1、为假时 fail_n 加 1；detail 为真值（非空串）时打印行追加 " — " + detail，detail 为默认空串时只打印 name。
def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')

vm = ConditionVM()

# ① 道→德→知足→止：信任 0.3 不达 0.7 不跳；再德 0.5 达标跳
code = assemble("""
DAO 路径甲
DE 0.3
ZHIZU 0.7 @L1
DE 0.5
@L1:
ZHI
""")
state = vm.run(code)
check('① 德累积+知足达标', state["trust"] >= 0.7, f'trust={state["trust"]}')
check('①b 道创建条件空间', state["condition_space"][0]["name"] == "路径甲",
      str(state["condition_space"]))

# ② 条件空间栈：DAO×2 → ZIRAN 回根
code = assemble("""
DAO 根路径
DAO 子路径
ZIRAN
ZHI
""")
state = vm.run(code)
check('② ZIRAN 恢复默认条件空间', len(state["condition_space"]) <= 1,
      f'栈={state["condition_space"]}')

# ③ JUMP_IF_FALSE：若…则（假跳真续）
code = assemble("""
PUSH_CONST 0
JUMP_IF_FALSE @skip
PUSH_CONST 99
STORE_NAME 不应执行
@skip:
PUSH_CONST 7
STORE_NAME 结果
ZHI
""")
state = vm.run(code)
check('③ 若则假跳', state["symbols"].get("结果") == 7
      and "不应执行" not in state["symbols"], str(state["symbols"]))

# ④ 名实符号表：LOAD 未声明报错（以名举实）
code = assemble("PUSH_CONST 1\nSTORE_NAME 甲\nLOAD_NAME 甲\nZHI\n")
state = vm.run(code)
check('④a 名实读写', state["symbols"].get("甲") == 1, '')
try:
    vm.run(assemble("LOAD_NAME 未声明\n"))
    check('④b 名实不符报错', False, '')
except NameError as e:
    check('④b 名实不符报错', "未声明" in str(e), str(e))

# ⑤ WUWEI 让出控制（yield 非终止，catch_halt=False 时抛出）
code = assemble("DE 0.5\nWUWEI\nZHI\n")
state = vm.run(code)
check('⑤a WUWEI 让出捕获', state.get("halt") == "yield" and state["trust"] == 0.5,
      f'halt={state.get("halt")} trust={state["trust"]}')
try:
    vm.run(code, catch_halt=False)
    check('⑤b WUWEI 抛出', False, '未抛出')
except VMHalt as e:
    check('⑤b WUWEI 抛出', e.kind == "yield", f'kind={e.kind}')

# ⑥ ZHI 停止
state = vm.run(assemble("ZHI\n"))
check('⑥ ZHI 停止', state.get("halt") == "halt", f'halt={state.get("halt")}')

# ⑦ 汇编标签 + 未知助记符
code = assemble("JUMP @end\nPUSH_CONST 1\n@end:\nZHI\n")
check('⑦a 标签解析', code[0][1] == 2, f'JUMP→{code[0][1]}（应跳 @end=index2）')
state = vm.run(code)
check('⑦c 标签跳转跳过指令', state["stack"] == [] and state.get("halt") == "halt",
      f'stack={state["stack"]} halt={state.get("halt")}（PUSH 被跳过）')
try:
    assemble("NOT_A_OP 1\n")
    check('⑦b 未知助记符报错', False, '')
except SyntaxError:
    check('⑦b 未知助记符报错', True, '')

# ⑧ 比较指令
code = assemble("PUSH_CONST 3\nPUSH_CONST 2\nCMP_GT\nZHI\n")
state = vm.run(code)
check('⑧ 比较指令', state["stack"] == [True], str(state["stack"]))

print(f'\n=== 智能论 VM 测试: {pass_n}/{pass_n + fail_n} 通过 ===')
sys.exit(0 if fail_n == 0 else 1)