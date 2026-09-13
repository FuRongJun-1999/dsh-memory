# -*- coding: utf-8 -*-
"""test_c4_tooling.py · C4 工具链测试（第六阶段）：分析器 + 调试器
验证：①字节码转储可读 ②单步执行状态正确 ③调试轨迹（逐步可见）④.pbc 调试"""
import sys, os, tempfile
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from compiler.analyzer import bytecode_dump, analyze_source
from compiler.debugger import VMDebugger, debug_pbc
from compiler.compiler import compile_source

pass_n = fail_n = 0
def check(name, ok, detail=''):
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')

src = """术曰：
1。道 新信任路径；
2。德 0.3；
3。若 信任值 大于 0.2，则 德 0.5；
4。止。
"""
code, r = compile_source(src, strict=False)

# ① 分析器：字节码转储可读
lines, r_a = analyze_source(src, strict=False)
check('①a 转储生成', r_a["ok"] and len(lines) > 0, f'{len(lines)} 行')
check('①b 转储可读(地址+指令)', any("DAO" in ln for ln in lines)
      and any("DE" in ln for ln in lines), lines[0] if lines else '')

# ② 调试器：单步执行状态正确
dbg = VMDebugger(code, symbols={"信任值": 0.5})
s1 = dbg.step()   # ENTER_SHUYUE
s2 = dbg.step()   # DAO
s3 = dbg.step()   # DE 0.3
check('②a 单步执行(道压入条件空间)', s2["cond"] and s2["cond"][0]["name"] == "新信任路径",
      str([c["name"] for c in s2["cond"]]))
check('②b 单步信任递增', s3["trust"] == 0.3, f'trust={s3["trust"]}')

# ③ 调试轨迹：逐步可见直到 halt
trace = dbg.run()
check('③a 轨迹含止', any(s.get("halt") == "halt" for s in trace), '')
check('③b 最终状态(信任0.8+halt)', dbg.state()["trust"] == 0.8
      and dbg.state()["halt"] == "halt", f'trust={dbg.state()["trust"]}')
check('③c 轨迹逐步(信任非减)', [s["trust"] for s in trace] == sorted(
      [s["trust"] for s in trace]), '')

# ④ .pbc 调试
from compiler.pbc import save_pbc
tmp = tempfile.mkdtemp(prefix="c4_")
pbc = os.path.join(tmp, "out.pbc")
save_pbc(code, pbc)
tr = debug_pbc(pbc, symbols={"信任值": 0.5})
check('④ .pbc 单步调试', len(tr) > 0 and tr[-1].get("halt") == "halt",
      f'{len(tr)} 步')

print(f'\n=== C4 工具链测试: {pass_n}/{pass_n + fail_n} 通过 ===')
sys.exit(0 if fail_n == 0 else 1)
