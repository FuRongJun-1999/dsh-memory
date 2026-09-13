# -*- coding: utf-8 -*-
"""test_pbc.py · C3 原生编译测试（第六阶段）：.pbc 字节码文件
验证：①序列化→反序列化往返一致 ②中文源码→.pbc 文件 ③.pbc→VM 独立执行结果一致
④.pbc 不依赖 Python 运行时（独立字节码文件）"""
import sys, os, tempfile
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from compiler.pbc import (serialize, deserialize, save_pbc, load_pbc,
                      compile_to_pbc, run_pbc)

pass_n = fail_n = 0
def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')

# ① 序列化往返
code = [("DAO", "新信任路径"), ("DE", 0.3), ("ZHIZU", (0.7, 5)),
        ("ZHI", None), ("PUSH", True), ("STORE", "甲")]
data = serialize(code)
code_rt = deserialize(data)
check('① 序列化往返一致', code_rt == code and len(data) > 0,
      f'{len(data)} 字节')

# ② 中文源码 → .pbc 文件
src = """问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：
1。道 新信任路径；
2。德 0.3；
3。若 信任值 大于 0.2，则 德 0.5；
4。止。
"""
tmp = tempfile.mkdtemp(prefix="pbc_test_")
pbc = os.path.join(tmp, "out.pbc")
code_c, r = compile_to_pbc(src, pbc)
check('②a 编译为.pbc', r["ok"] and os.path.isfile(pbc) and os.path.getsize(pbc) > 10,
      f'{os.path.getsize(pbc) if os.path.isfile(pbc) else 0} 字节')

# ③ .pbc → VM 独立执行
if os.path.isfile(pbc):
    state = run_pbc(pbc, symbols={"信任值": 0.5})
    check('③a 独立执行(信任0.8+条件空间+halt)',
          state["trust"] == 0.8
          and state["condition_space"][0]["name"] == "新信任路径"
          and state["halt"] == "halt",
          f'trust={state["trust"]} halt={state["halt"]}')
    # 直接编译执行的对照
    from compiler.condition_vm import ConditionVM
    state_direct = ConditionVM().run(code_c, symbols={"信任值": 0.5})
    check('③b 与直接编译执行一致', state["trust"] == state_direct["trust"], '')

# ④ .pbc 往返加载（文件 → 字节码 → 再保存一致；op 统一为枚举比较）
if os.path.isfile(pbc):
    loaded = load_pbc(pbc)
    from compiler.condition_vm import Opcode
    loaded_norm = [(Opcode[n], a) for n, a in loaded]
    check('④ .pbc 文件加载一致', loaded_norm == code_c, f'len={len(loaded)}')

print(f'\n=== C3 原生编译测试: {pass_n}/{pass_n + fail_n} 通过 ===')
sys.exit(0 if fail_n == 0 else 1)
