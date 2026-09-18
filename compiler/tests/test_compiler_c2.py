# -*- coding: utf-8 -*-
"""test_compiler_c2.py · C2 测试：中文源码 → 字节码 → VM 执行（第六阶段）
验证：①若则编译为条件跳转 ②道德经指令→DAO/DE ③术曰作用域 ④名实静态检查
⑤对照 v0.2 codegen 语义（道=条件空间/德=信任累积）⑥算术/比较指令"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
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

# ① 若…则…否则 → JUMP_IF_FALSE 条件跳转
src1 = """
问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：
1。若 信任值 大于 0.3，则 德 0.5；
2。止。
"""
code, r = compile_source(src1, strict=False)
check('①a 编译成功', r["ok"] and code is not None, str(r["errors"][:2]) if not r["ok"] else '')
check('①b 含条件跳转', any(op == Opcode.JUMP_IF_FALSE for op, _ in code),
      f'{len(code)} 条指令')
check('①c 含德指令', any(op == Opcode.DE for op, _ in code), '')
vm = ConditionVM()
# 缺陷②修复后：符号注入的「信任值」归一为**寄存器初值**（名实一处存储）。
# 故 0.5 起步 → 信任值(0.5) > 0.3 成立 → 德 0.5 → 1.0。
# （修复前符号与寄存器互不通信，德 只加到寄存器 0→0.5，断言 0.5 固化了该缺陷）
state = vm.run(code, symbols={"信任值": 0.5})
check('①d 信任累积语义（德=accumulate_trust，0.5+0.5=1.0）', state["trust"] == 1.0,
      f'trust={state["trust"]}')

# ② 道/知足/止：条件空间 + 信任达标跳转
src2 = """
术曰：
1。道 新信任路径；
2。德 0.3；
3。知足 0.7；
4。德 0.5；
5。止。
"""
code, r = compile_source(src2, strict=False)
state = vm.run(code)
check('②a 道创建条件空间', state["condition_space"][0]["name"] == "新信任路径",
      str(state["condition_space"]))
check('②b 知足未达标不跳（继续德）', state["trust"] >= 0.7, f'trust={state["trust"]}')

# ③ 术曰作用域（ENTER/RETURN）
check('③ 术曰作用域指令', any(op == Opcode.ENTER_SHUYUE for op, _ in code)
      and any(op == Opcode.RETURN_STEP for op, _ in code), '')

# ④ 名实静态检查（未声明符号 → 编译期错误，以名举实）
src4 = """
术曰：
1。德 未声明变量；
2。止。
"""
_, r4 = compile_source(src4, strict=True)
check('④ 名实校验拦截（严格模式）', not r4["ok"] and r4.get("name_errors"),
      str(r4.get("name_errors", [])[:1])[:60])

# ⑤ 对照 v0.2 codegen 语义（道=create_path/德=accumulate_trust 在 INSTRUCTION_MAP 声明）
from compiler.codegen import INSTRUCTION_MAP
from compiler.lexer import TokenType
check('⑤a codegen 语义对照(道→create_path)', "create_path" in INSTRUCTION_MAP.get(
      TokenType.DAO, ""), INSTRUCTION_MAP.get(TokenType.DAO, ""))
check('⑤b codegen 语义对照(德→accumulate_trust)', "accumulate_trust" in INSTRUCTION_MAP.get(
      TokenType.DE, ""), INSTRUCTION_MAP.get(TokenType.DE, ""))

# ⑥ 算术/比较指令（BINARY_EXPR + 中文比较词）
src6 = """
术曰：
1。若 4 大于 3，则 德 0.2；
2。止。
"""
code6, r6 = compile_source(src6, strict=False)
check('⑥a 算术+比较编译', r6["ok"], str(r6.get("warnings", []))[:40])
if r6["ok"]:
    state6 = vm.run(code6)
    check('⑥b 算术比较执行（5>4 真→德执行）', state6["trust"] == 0.2,
          f'trust={state6["trust"]}')

print(f'\n=== C2 中文编译器测试: {pass_n}/{pass_n + fail_n} 通过 ===')
sys.exit(0 if fail_n == 0 else 1)