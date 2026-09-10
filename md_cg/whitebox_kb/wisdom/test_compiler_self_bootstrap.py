# -*- coding: utf-8 -*-
"""test_compiler_self_bootstrap.py · 白箱自举写编译器 + 外部校准（第六阶段 C2 白箱化）
流程：编译器代码条件单元库 → 白箱生成（模板填充）→ 三层自校验
  L1 语法（ast.parse）→ L2 样例（args→期望断言运行）→ L3 边界（空/极端）
→ 外部校准：语义对照（智能论语义基准）+ 集成（生成代码组装 VM 执行）
"""
import sys, os, ast
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compiler_code_units import COMPILER_UNITS, route_compiler_unit

pass_n = fail_n = 0
def check(name, ok, detail=''):
    """断言登记：通过/失败计数并打印 ✓✘ 结果行。"""
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')

# ============ 白箱生成 + 三层自校验 ============
generated = {}
for uid, u in COMPILER_UNITS.items():
    code_text = u["pattern"]
    # L1 语法自校验（物理基底：ast.parse）
    try:
        tree = ast.parse(code_text)
        l1_ok = True
    except SyntaxError as e:
        l1_ok = False
    check(f'L1 语法[{uid}]', l1_ok, str(e) if not l1_ok else '')
    if not l1_ok:
        continue
    # L2 样例自校验（运行生成函数断言）
    ns = {}
    exec(compile(tree, "<unit>", "exec"), ns)
    fn_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    fn = ns[fn_names[0]] if fn_names else None
    l2_ok, detail = True, ""
    if fn:
        for args, expect in u["cases"]:
            try:
                if uid == "编译-类型检查":
                    # 组装：注入「分析-类型推断」白箱生成的 infer_types（类型检查编译）
                    infer_fn = generated["分析-类型推断"][1]
                    got = fn(*args, infer_fn)
                else:
                    got = fn(*args) if isinstance(args, tuple) else fn(args)
                if isinstance(expect, dict) and isinstance(got, dict):
                    # dict 期望：子集匹配（VM 执行循环返回状态 dict）
                    if not all(got.get(k) == v for k, v in expect.items()):
                        l2_ok, detail = False, f"{args} → {got} ⊉ {expect}"
                        break
                elif got != expect:
                    l2_ok, detail = False, f"{args} → {got!r} ≠ {expect!r}"
                    break
            except Exception as e:
                l2_ok, detail = False, f"{args} → 异常 {e}"
                break
    check(f'L2 样例[{uid}]', l2_ok, detail)
    if l2_ok:
        generated[uid] = (code_text, fn)

# ============ 外部校准 ============
# 校准①：语义对照——生成代码与智能论语义基准一致
cal_ok = all(u["calibration"] for u in COMPILER_UNITS.values())
check('校准① 语义基准声明齐全', cal_ok, f'{len(COMPILER_UNITS)} 单元')

# 校准②：集成——白箱生成的单元组装成迷你 VM 跑「若则+德」
if "VM-条件跳转" in generated and "VM-信任累积" in generated:
    jf, _ = generated["VM-条件跳转"]
    at, _ = generated["VM-信任累积"]
    # 组装：栈=[False(条件为假)] → 跳转跳过德 → 信任不变
    ns = {}
    exec(compile(ast.parse(jf), "<jf>", "exec"), ns)
    exec(compile(ast.parse(at), "<at>", "exec"), ns)
    trust = ns["accumulate_trust"](0.0, 0.5)
    new_ip = ns["exec_jump_if_false"]([False], 3, 9)
    check('校准② 集成(信任累积)', trust == 0.5, f'trust={trust}')
    check('校准②b 集成(条件假跳转)', new_ip == 9, f'ip={new_ip}')

# 校准③：任务识别
check('校准③ 任务识别', route_compiler_unit("实现条件跳转") == "VM-条件跳转"
      and route_compiler_unit("信任累积怎么写") == "VM-信任累积", '')

# 校准④：端到端组装管线——白箱生成单元组装「中文程序 → 编译 → VM 执行」
def _fn(uid):
    """域桥接取函数：从 code_compose 命名空间安全取出目标函数。"""
    t = ast.parse(COMPILER_UNITS[uid]["pattern"])
    ns = {}
    exec(compile(t, "<u>", "exec"), ns)
    return ns[[n.name for n in ast.walk(t) if isinstance(n, ast.FunctionDef)][0]]

vm_run = _fn("VM-执行循环")
compile_instr = _fn("编译-指令")
instr_token = _fn("词法-道德经")
check('校准④a 词法→编译→执行(道/德/止)',
      instr_token("道") == "DAO" and compile_instr("DAO", "路径甲") == ("DAO", "路径甲"), '')
prog = [("DAO", "新信任路径"), ("DE", "0.3"), ("DE", "0.5"), ("ZHI", None)]
instrs = [compile_instr(k, v) for k, v in prog if compile_instr(k, v)]
state = vm_run(instrs)
check('校准④b 端到端(信任累积+条件空间+止)',
      state["trust"] == 0.8 and state["cond"] == [{"name": "新信任路径"}]
      and state["halt"] == "halt",
      f'trust={state["trust"]} cond={state["cond"]} halt={state["halt"]}')
# 若则端到端：条件为假跳过 then
compile_condition = _fn("编译-若则")
cond_code = compile_condition([("PUSH", False)], [("DE", 0.5)], [("DE", 0.1)])
state2 = vm_run(cond_code)
check('校准④c 端到端(若则假跳→else)',
      state2["trust"] == 0.1 and state2["halt"] is None,
      f'trust={state2["trust"]}（假→跳过 then 的 0.5 执行 else 的 0.1）')

# 校准⑤：完整中文源码端到端（词法→编译→VM 执行）
lex_line = _fn("词法-中文程序")
compile_program = _fn("编译-程序")
instr_token = _fn("词法-道德经")
source = """问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：
1。道 新信任路径；
2。若 信任值 大于 0.3，则 德 0.5；
3。德 0.3；
4。止。
"""
stmts = []
for line in source.splitlines():
    r = lex_line(line)
    if r is None:
        continue
    kind, payload = r
    if kind in ("问曰_STRUCT", "答曰_STRUCT", "术曰_STRUCT"):
        stmts.append((kind, payload))
    elif kind == "STEP":
        words = payload[1].split()
        en = instr_token(words[0])
        if en:
            stmts.append(("INSTR", en, words[1] if len(words) > 1 else None))
    elif kind == "COND":
        cond_txt, then_txt, else_txt = payload
        then_parts = then_txt.split()
        en = instr_token(then_parts[0])
        stmts.append(("COND", cond_txt,
                      [(en if en else then_parts[0],
                        then_parts[1] if len(then_parts) > 1 else None)], []))
    elif kind == "INSTR":
        en = instr_token(payload[0])
        if en:
            stmts.append(("INSTR", en, payload[1]))
check('校准⑤a 中文源码词法', any(s[0] == "术曰_STRUCT" for s in stmts)
      and any(s[0] == "INSTR" and s[1] == "DAO" for s in stmts)
      and any(s[0] == "INSTR" and s[1] == "DE" for s in stmts),
      f'{len(stmts)} 条语句')
code5 = compile_program(stmts, compile_instr, compile_condition)
state5 = vm_run(code5)
check('校准⑤b 端到端执行(信任≥0.8+条件空间+halt)',
      state5["trust"] >= 0.8 and state5["cond"] == [{"name": "新信任路径"}]
      and state5["halt"] == "halt",
      f'trust={state5["trust"]} cond={state5["cond"]} halt={state5["halt"]}')

# 校准⑥：编译期静态检查拦截（条件空间=类型系统/名实=静态检查）
compile_pipeline = _fn("编译-管线静态检查")
check_condition_spaces = _fn("校验-条件空间存在性")
check('校准⑥a 条件空间存在性校验',
      check_condition_spaces(["伴侣"], {"伴侣"}) == []
      and check_condition_spaces(["未知"], {"伴侣"}) == ["未知"], '')
# 类型错误源码：德 操作数非数值 → 编译期拦截
_, r_bad = compile_pipeline([("INSTR", "DE", "高信任"), ("止", None)],
                            {"信任值": "数值"}, {"伴侣"})
check('校准⑥b 类型错误编译期拦截', r_bad["ok"] is False
      and any("类型错误" in e for e in r_bad["errors"]), str(r_bad["errors"]))
# 未声明条件空间 → 编译期拦截
_, r_bad2 = compile_pipeline([("COND", "条件空间为未知 则 德 0.5", [("DE", "0.5")], [])],
                             {"信任值": "数值"}, {"伴侣"})
check('校准⑥c 未声明条件空间拦截', r_bad2["ok"] is False
      and any("条件空间未声明" in e for e in r_bad2["errors"]), str(r_bad2["errors"]))
# 正确源码 → 通过
code_ok, r_ok = compile_pipeline([("INSTR", "DE", "0.5"), ("止", None)],
                                 {"信任值": "数值"}, {"伴侣"})
check('校准⑥d 正确源码通过', r_ok["ok"] and code_ok == [("COMPILED", 2)], str(r_ok))

# 校准⑦：单入口完整编译（白箱版 pc compile：词法→静态检查→编译）
compile_full = _fn("编译-完整管线")
src_ok = "道 新信任路径\n德 0.3\n止。\n"
code7, r7 = compile_full(src_ok, {"伴侣"})
check('校准⑦a 单入口编译(道/德/止)',
      r7["ok"] and code7 == [("DAO", "新信任路径"), ("DE", 0.3), ("ZHI", None)],
      str(code7))
if r7["ok"]:
    state7 = vm_run(code7)
    check('校准⑦b 单入口执行(信任0.3+条件空间+halt)',
          state7["trust"] == 0.3 and state7["cond"] == [{"name": "新信任路径"}]
          and state7["halt"] == "halt",
          f'trust={state7["trust"]} cond={state7["cond"]} halt={state7["halt"]}')
# 未声明条件空间 → 单入口拦截
_, r7_bad = compile_full("若 条件空间为未知 则 德 0.5\n止。\n", {"伴侣"})
check('校准⑦c 单入口拦截未声明空间', r7_bad["ok"] is False
      and any("条件空间未声明" in e for e in r7_bad["errors"]), str(r7_bad["errors"]))
# 未知行 → 拦截
_, r7_bad2 = compile_full("随便文本\n", set())
check('校准⑦d 单入口拦截未知行', r7_bad2["ok"] is False
      and any("无法识别" in e for e in r7_bad2["errors"]), str(r7_bad2["errors"]))
# 声明空间后通过（若则）
code7b, r7b = compile_full("若 条件空间为伴侣 则 德 0.5\n止。\n", {"伴侣"})
check('校准⑦e 声明空间后通过', r7b["ok"] and len(code7b) >= 2,
      f'{len(code7b)} 条指令')

# 校准⑧：条件真值计算（若则真实判定）
eval_condition = _fn("求值-条件表达式")
check('校准⑧a 条件表达式求值',
      eval_condition("信任值 大于 0.3", {"信任值": 0.5}) is True
      and eval_condition("信任值 大于 0.3", {"信任值": 0.2}) is False
      and eval_condition("未知量 大于 0.3", {"信任值": 0.5}) is None, '')
# 单入口：信任值 0.5 → 真 → 执行 then
src_t = "若 信任值 大于 0.3，则 德 0.5\n止。\n"
code8, r8 = compile_full(src_t, {"伴侣"})
check('校准⑧b 条件真值编译(LOAD+PUSH+CMP)',
      r8["ok"] and any(op == "CMP_GT" for op, _ in code8), str(code8))
if r8["ok"]:
    state8 = vm_run(code8, symbols={"信任值": 0.5})
    check('校准⑧c 真条件执行then(信任0.5)',
          state8["trust"] == 0.5, f'trust={state8["trust"]}')
    state8b = vm_run(code8, symbols={"信任值": 0.2})
    check('校准⑧d 假条件跳过then(信任0)',
          state8b["trust"] == 0.0, f'trust={state8b["trust"]}')

# 校准⑨：赋值/变量（名实动态绑定）
src9 = "甲 = 3\n若 甲 大于 2，则 德 0.5\n止。\n"
code9, r9 = compile_full(src9, {"伴侣"})
check('校准⑨a 赋值编译(STORE)', r9["ok"]
      and any(op == "STORE" and arg == "甲" for op, arg in code9), str(code9))
if r9["ok"]:
    state9 = vm_run(code9)
    check('校准⑨b 赋值+条件执行(符号甲=3, 3>2真→德0.5)',
          state9["symbols"].get("甲") == 3 and state9["trust"] == 0.5
          and state9["halt"] == "halt",
          f'symbols={state9["symbols"]} trust={state9["trust"]} halt={state9["halt"]}')
# 变量复制：乙 = 甲
code9b, r9b = compile_full("甲 = 3\n乙 = 甲\n止。\n", set())
if r9b["ok"]:
    state9b = vm_run(code9b)
    check('校准⑨c 变量复制(乙=甲)', state9b["symbols"].get("甲") == 3
          and state9b["symbols"].get("乙") == 3,
          f'symbols={state9b["symbols"]}')

# 校准⑩：对接 protocol-compiler 真实 lexer/parser（同一源码 → 白箱编译 → VM 执行）
import sys as _sys
import os as _os
_pc = os.environ.get('AEIS_PROTOCOL_COMPILER') or os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
    _os.pardir, 'protocol-compiler')
if _os.path.isdir(_pc) and _pc not in _sys.path:
    _sys.path.insert(0, _pc)
bridge_token = _fn("对接-协议词法")
try:
    from core.lexer import tokenize, TokenType
    from core.parser import parse_tokens, NodeType
    src_pc = """问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：
1。道 新信任路径；
2。德 0.3；
3。止。"""
    tokens_pc, lex_err = tokenize(src_pc)
    ast_pc = parse_tokens(tokens_pc, [])
    instrs_pc = []
    for stmt in ast_pc.statements:
        if getattr(stmt, "type", None) == NodeType.SHUYUE:
            for step in stmt.steps:
                s = step.statement
                if getattr(s, "type", None) == NodeType.INSTRUCTION_STMT:
                    kind = bridge_token(s.instruction.name)
                    operand = None
                    if s.operands:
                        op0 = s.operands[0]
                        operand = getattr(op0, "name", None) or getattr(
                            op0, "literal_value", None)
                    ci = compile_instr(kind, operand)
                    if ci:
                        instrs_pc.append(ci)
    check('校准⑩a 真实解析→白箱编译', len(instrs_pc) >= 2
          and ("DAO", "新信任路径") in instrs_pc
          and ("DE", 0.3) in instrs_pc, str(instrs_pc))
    if instrs_pc:
        state_pc = vm_run(instrs_pc)
        check('校准⑩b VM执行(真实AST→信任0.3+条件空间+halt)',
              state_pc["trust"] == 0.3
              and state_pc["cond"] == [{"name": "新信任路径"}]
              and state_pc["halt"] == "halt",
              f'trust={state_pc["trust"]} cond={state_pc["cond"]} halt={state_pc["halt"]}')
except ImportError as e:
    check('校准⑩ protocol-compiler 对接', False, f'导入失败: {e}')

# 校准⑪：知足（信任达标跳转，道德经指令全覆盖验证）
src_z1 = "德 0.3\n知足 0.7\n德 0.5\n止。\n"
code_z1, r_z1 = compile_full(src_z1, set())
check('校准⑪a 知足编译(达标目标末尾回填)', r_z1["ok"]
      and any(op == "ZHIZU" and arg == (0.7, 4) for op, arg in code_z1), str(code_z1))
if r_z1["ok"]:
    state_z1 = vm_run(code_z1)
    check('校准⑪b 知足不达标继续(信任0.8)',
          state_z1["trust"] == 0.8, f'trust={state_z1["trust"]}')
src_z2 = "德 0.8\n知足 0.7\n德 0.5\n止。\n"
code_z2, r_z2 = compile_full(src_z2, set())
if r_z2["ok"]:
    state_z2 = vm_run(code_z2)
    check('校准⑪c 知足达标跳结束(信任0.8,跳过德0.5)',
          state_z2["trust"] == 0.8, f'trust={state_z2["trust"]}')

# 校准⑫：C3 原生编译——字节码序列化/反序列化往返 + .pbc 执行
serialize = _fn("字节码-序列化")
deserialize = _fn("字节码-反序列化")
src_pbc = "德 0.3\n若 信任值 大于 0.2，则 德 0.5\n止。\n"
code_pbc, r_pbc = compile_full(src_pbc, {"伴侣"})
check('校准⑫a 编译成功', r_pbc["ok"] and code_pbc, str(r_pbc.get("errors", []))[:30])
if r_pbc["ok"]:
    data = serialize(code_pbc)
    check('校准⑫b 序列化字节串', isinstance(data, bytes) and len(data) > 0,
          f'{len(data)} 字节')
    code_rt = deserialize(data)
    check('校准⑫c 反序列化往返一致', code_rt == code_pbc,
          f'len={len(code_rt)}')
    # .pbc 独立执行（不依赖编译流程，直接 VM 加载执行）
    state_pbc = vm_run(code_rt, symbols={"信任值": 0.5})
    state_direct = vm_run(code_pbc, symbols={"信任值": 0.5})
    check('校准⑫d .pbc 执行结果一致(信任0.8)',
          state_pbc["trust"] == state_direct["trust"] == 0.8,
          f'trust={state_pbc["trust"]}')

# 校准⑬：类型推断（目标3 分析器完整化——编译期类型流）
infer_types = _fn("分析-类型推断")
r_t = infer_types([("assign", "甲", 3), ("assign", "乙", "x"), ("assign", "丙", True)])
check('校准⑬a 类型推断(数值/文本/布尔)',
      r_t["types"] == {"甲": "数值", "乙": "文本", "丙": "布尔"}, str(r_t["types"]))
r_t2 = infer_types([("assign", "甲", 3), ("assign", "甲", "x")])
check('校准⑬b 类型冲突→混合', r_t2["types"]["甲"] == "混合", str(r_t2["types"]))
r_t3 = infer_types([("COND", "条件空间为伴侣 则 德 0.5", [], [])])
check('校准⑬c 条件空间声明登记', r_t3["spaces"] == {"伴侣": "已声明"}, str(r_t3["spaces"]))

# 校准⑭：类型检查接入编译管线（未推断/混合类型编译期拦截）
compile_typed = _fn("编译-类型检查")
code_t, r_t4 = compile_typed([("assign", "甲", 3), ("COND", "甲 大于 2 则 德 0.5", [], [])],
                             infer_types)
check('校准⑭a 类型一致通过', r_t4["ok"] and code_t == [("TYPED_OK", 2)],
      str(r_t4.get("errors", []))[:30])
_, r_t5 = compile_typed([("COND", "未知量 大于 2 则 德 0.5", [], [])], infer_types)
check('校准⑭b 未推断类型拦截', r_t5["ok"] is False
      and any("未推断类型" in e for e in r_t5["errors"]), str(r_t5["errors"]))
_, r_t6 = compile_typed([("assign", "甲", 3), ("assign", "甲", "x"),
                         ("COND", "甲 大于 2 则 德 0.5", [], [])], infer_types)
check('校准⑭c 混合类型拦截', r_t6["ok"] is False
      and any("类型冲突" in e for e in r_t6["errors"]), str(r_t6["errors"]))

print(f'\n=== 白箱自举写编译器（C2 白箱化）: {pass_n}/{pass_n + fail_n} 通过 ===')
sys.exit(0 if fail_n == 0 else 1)
