# -*- coding: utf-8 -*-
"""test_python_self_bootstrap.py · P 线白箱自举测试（第六阶段·Mini-Python 机制白箱化）
流程：语言机制单元库 → 白箱生成（模板填充）→ 三层自校验（L1 语法/L2 样例）
→ 外部校准（对照 CPython 行为 + 校准参考 mini_python.py）
"""
import sys
import os, ast
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from python_code_units import PYTHON_UNITS, route_python_unit
from mini_python import run_program

pass_n = fail_n = 0
def check(name, ok, detail=''):
    """断言登记：通过/失败计数并打印结果行。"""
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')

# ============ 白箱生成 + 三层自校验 ============
generated = {}
for uid, u in PYTHON_UNITS.items():
    tree = ast.parse(u["pattern"])
    check(f'L1 语法[{uid}]', True, '')
    ns = {}
    exec(compile(tree, "<unit>", "exec"), ns)
    fn_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    fn = ns[fn_names[0]] if fn_names else None
    cls_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    l2_ok, detail = True, ""
    if fn:
        for args, expect in u["cases"]:
            try:
                if args == "call":  # 特殊：调用单元入口（闭包→closure_test，环境→env_scope）
                    if uid == "异常-抛出":
                        # 注入验证：raise 构造异常并抛出（期望 ValueError 消息）
                        try:
                            ns["raise_error"](ValueError, "测试错误")
                            got, expect = None, ("raised", "测试错误")
                        except ValueError as e:
                            got = ("raised", str(e))
                    elif uid == "异常-捕获":
                        # 注入验证：try_except 捕获 ValueError → handler
                        def risky():
                            raise ValueError("除以零")
                        got = ns["try_except"](ValueError, lambda e: "处理:" + str(e), risky)
                    elif uid == "异常-传播":
                        # 注入验证：内层抛 → 外层捕获
                        got = ns["propagate"](None, ValueError, "深层错误")
                    elif uid in ("闭包-捕获更新", "闭包-工厂", "闭包-延迟绑定"):
                        # 注入验证：闭包族入口（捕获更新/工厂/延迟绑定）
                        entry = ns.get("closure_mutate_test") or \
                            ns.get("closure_factory_test") or ns.get("lazy_bindings")
                        got = entry()
                    elif uid == "生成器-yield":
                        # 注入验证：生成器 yield 逐个产出
                        got = ns["gen_test"]()
                    elif uid in ("面向对象-类定义", "面向对象-继承", "面向对象-多态"):
                        # 注入验证：OOP 族入口（类定义/继承/多态）
                        entry = ns.get("oop_class_test") or \
                            ns.get("oop_inherit_test") or ns.get("oop_poly_test")
                        got = entry()
                    elif uid in ("装饰器-定义使用", "上下文-管理器", "工具-属性访问"):
                        # 注入验证：高级语法族入口（装饰器/上下文/属性）
                        entry = ns.get("decorator_test") or \
                            ns.get("with_test") or ns.get("attr_test")
                        got = entry()
                    elif uid == "类型-类型注解":
                        # 注入验证：类型注解
                        got = ns["annotate_test"]()
                    elif uid == "异步-async await":
                        # 注入验证：async/await 协程
                        got = ns["async_test"]()
                    else:
                        entry = ns.get("closure_test") or ns.get("env_scope")
                        got = entry()
                elif uid == "程序-完整执行":
                    # 组装：注入「求值-控制流」白箱生成的 run_stmts（自举闭环）
                    run_stmts = generated.get("求值-控制流", ({}, []))[0]["run_stmts"]
                    got = fn(args, run_stmts)
                else:
                    got = fn(*args) if isinstance(args, tuple) else fn(args)
                if isinstance(expect, dict) and isinstance(got, dict):
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
        generated[uid] = (ns, fn_names)

# ============ 外部校准 ============
# 校准①：对照 CPython（优先级/逻辑）
ns_prec, _ = generated.get("语法-优先级", ({}, []))
if ns_prec:
    fn = ns_prec["precedence"]
    ok = fn("2+3*4") == 14 and fn("(2+3)*4") == 20 and fn("10-3*2") == 4
    check('校准① 优先级对照CPython', ok, '')
ns_logic, _ = generated.get("求值-逻辑短路", ({}, []))
if ns_logic:
    fn = ns_logic["logic_eval"]
    ok = fn(("a", "or", "b"), {"a": 1, "b": 0}) == 1 and fn(("a", "or", "b"), {"a": 0, "b": 5}) == 5
    check('校准② 逻辑短路对照Python', ok, '')

# 校准③：对照校准参考 mini_python.py（栈机结果一致）
ns_vm, _ = generated.get("栈机-字节码执行", ({}, []))
if ns_vm:
    fn = ns_vm["vm_exec"]
    r1 = fn([("PUSH", 2), ("PUSH", 3), ("PUSH", 4), ("MUL", None), ("ADD", None)])
    from mini_python import eval_expr
    check('校准③ 栈机对照eval_expr(2+3*4)', r1 == eval_expr("2+3*4") == 14,
          f'vm={r1} eval={eval_expr("2+3*4")}')

# 校准④：任务识别
check('校准④ 任务识别', route_python_unit("词法分析怎么做") == "词法-记号化"
      and route_python_unit("栈机执行") == "栈机-字节码执行", '')

# 校准⑤：外部校准对照（控制流/函数/闭包/完整栈机 vs 校准参考 mini_python.py）
ns_cf, _ = generated.get("求值-控制流", ({}, []))
if ns_cf:
    fn = ns_cf["run_stmts"]
    env = fn([("assign", "x", 5), ("if", True, [("assign", "y", 1)], [("assign", "y", 0)])], {})
    check('校准⑤a 控制流(if真)', env == {"x": 5, "y": 1}, str(env))
ns_fn, _ = generated.get("函数-定义调用", ({}, []))
if ns_fn:
    f = ns_fn["make_function"]("a", [("return", 7)], {})
    check('校准⑤b 函数对象', ns_fn["call_function"](f, [2, 3], {}) == 7, '')
ns_cl, _ = generated.get("求值-闭包", ({}, []))
if ns_cl:
    check('校准⑤c 闭包独立捕获', ns_cl["closure_test"]() == (4, 11), '')
ns_full, _ = generated.get("栈机-完整执行", ({}, []))
if ns_full:
    fn = ns_full["vm_exec_full"]
    r = fn([("PUSH", 5), ("PUSH", 3), ("CMP_GT", None), ("JUMP_IF_FALSE", 6), ("PUSH", 1)])
    check('校准⑤d 完整栈机(if跳转)', r == [1], str(r))

print(f'\n=== P 线白箱自举（Mini-Python 机制）: {pass_n}/{pass_n + fail_n} 通过 ===')


# ---- P4 补全验证（2026-08-27 · for 循环 + 内置 range）----
try:
    _env = run_program("s = 0" + chr(10) + "for i in range(1, 6):" + chr(10) + "    s = s + i" + chr(10))
    _v = _env.vars.get("s")
    check("P4 for-range 求和（1..5=15，荣指认缺陷根治）", _v == 15, f"实际 {_v}")
except Exception as _e:
    check("P4 for-range 求和", False, str(_e)[:80])
try:
    _env2 = run_program("total = 0" + chr(10) + "for x in [3, 1, 2]:" + chr(10) + "    total = total + x" + chr(10))
    check("P4 for 列表迭代求和", _env2.vars.get("total") == 6,
          f"实际 {_env2.vars.get('total')}")
except Exception as _e:
    check("P4 for 列表迭代", False, str(_e)[:80])

sys.exit(0 if fail_n == 0 else 1)
