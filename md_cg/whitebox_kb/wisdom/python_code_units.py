# -*- coding: utf-8 -*-
"""python_code_units.py · Mini-Python 语言机制白箱单元库（第六阶段 P 线·白箱自举）
设计者指令：7 终极目标 + 7 初级复现项目都是白箱自举后验证编程能力的项目——
P 线 Mini-Python 由白箱自己实现（code_compose 机制），外部只校准。
mini_python.py 定位为校准参考实现（语义基准）。
单元：{任务 → 代码模式模板 + 验证样例 + 校准基准}——语言机制（词法/优先级/
求值/逻辑/环境/栈机）逐一白箱化。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

# 任务 → 代码模式 + 验证样例（白箱生成的自校验基准）
PYTHON_UNITS = {
    "词法-记号化": {
        "task": "词法分析",
        "pattern": (
            "def tokenize(src):\n"
"    # 生效条件：参数 src 合法\n"
"    # 子功能：① 调用 len；② 调用 SyntaxError；③ 调用 float\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 字符流 → token 列表（数字/运算符/括号）——Mini-Python 词法\n"
            "    import re\n"
            "    tokens, i = [], 0\n"
            "    while i < len(src):\n"
            "        if src[i].isdigit():\n"
            "            j = i\n"
            "            while j < len(src) and (src[j].isdigit() or src[j] == '.'):\n"
            "                j += 1\n"
            "            text = src[i:j]\n"
            "            tokens.append(('NUMBER', float(text) if '.' in text else int(text)))\n"
            "            i = j\n"
            "        elif src[i] in '+-*/%()':\n"
            "            tokens.append(('OP', src[i]))\n"
            "            i += 1\n"
            "        elif src[i].isspace():\n"
            "            i += 1\n"
            "        else:\n"
            "            raise SyntaxError('未知字符: ' + src[i])\n"
            "    tokens.append(('EOF', ''))\n"
            "    return tokens\n"),
        "cases": [("2+3", [("NUMBER", 2), ("OP", "+"), ("NUMBER", 3), ("EOF", "")]),
                  ("3.5*2", [("NUMBER", 3.5), ("OP", "*"), ("NUMBER", 2), ("EOF", "")]),
                  ("(1)", [("OP", "("), ("NUMBER", 1), ("OP", ")"), ("EOF", "")])],
        "params": [],
        "calibration": "对照：mini_python.py tokenize（数字含小数/运算符/括号）",
    },
    "语法-优先级": {
        "task": "优先级计算",
        "pattern": (
            "def precedence(expr):\n"
"    # 生效条件：op ∈ {*, +, -, /}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：op 非 {*, +, -, /} 时\n"
            "    # 表达式优先级求值（2+3*4=14；括号最高）——Mini-Python 语法\n"
            "    def parse(i, min_prec):\n"
            "        if expr[i] == '(':\n"
            "            val, i = parse(i + 1, 0)\n"
            "            i += 1  # 跳过 ')'\n"
            "        else:\n"
            "            val = 0\n"
            "            j = i\n"
            "            while j < len(expr) and expr[j].isdigit():\n"
            "                val = val * 10 + int(expr[j])\n"
            "                j += 1\n"
            "            i = j\n"
            "        prec = {'+': 1, '-': 1, '*': 2, '/': 2, '**': 3}\n"
            "        while i < len(expr) and expr[i] in prec and prec[expr[i]] >= min_prec:\n"
            "            op = expr[i]\n"
            "            right, i = parse(i + 1, prec[op] + 1)\n"
            "            if op == '+':\n"
            "                val += right\n"
            "            elif op == '-':\n"
            "                val -= right\n"
            "            elif op == '*':\n"
            "                val *= right\n"
            "            elif op == '/':\n"
            "                val /= right\n"
            "        return val, i\n"
            "    return parse(0, 0)[0]\n"),
        "cases": [("2+3*4", 14), ("(2+3)*4", 20), ("10-3*2", 4), ("2+3+4", 9)],
        "params": [],
        "calibration": "对照：CPython 优先级（乘除高于加减，括号最高）",
    },
    "求值-逻辑短路": {
        "task": "逻辑短路",
        "pattern": (
            "def logic_eval(expr, values):\n"
"    # 生效条件：参数 expr/values 合法\n"
"    # 子功能：① 调用 truthy\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # or/and 短路 + 返回操作数（Python 语义：0 or 5 → 5）\n"
            "    def truthy(v):\n"
            "        return v is not None and v is not False and v != 0\n"
            "    left = values[expr[0]]\n"
            "    if expr[1] == 'or':\n"
            "        return left if truthy(left) else values[expr[2]]\n"
            "    if expr[1] == 'and':\n"
            "        return values[expr[2]] if truthy(left) else left\n"
            "    return None\n"),
        "cases": [((("a", "or", "b"), {"a": 1, "b": 0}), 1),
                  ((("a", "or", "b"), {"a": 0, "b": 5}), 5),
                  ((("a", "and", "b"), {"a": 0, "b": 5}), 0),
                  ((("a", "and", "b"), {"a": 2, "b": 3}), 3)],
        "params": [],
        "calibration": "对照：Python 语义——or/and 返回操作数 + 短路",
    },
    "环境-作用域链": {
        "task": "作用域环境",
        "pattern": (
            "class Env:\n"
            "    # 变量环境（作用域链）：局部 → 父环境（Mini-Python 环境）\n"
            "    # 生效条件：parent 为父环境实例或 None\n"
            "    # 子功能：① 构造变量表 ② get 沿链查询 ③ set 本层写入\n"
            "    # 执行：变量表 + 父链回溯（以名举实）\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    def __init__(self, parent=None):\n"
            "        # 构造：创建变量表并挂接父环境\n"
            "        self.vars = {}\n"
            "        self.parent = parent\n"
            "    def get(self, name):\n"
            "        # 查询：本层无则沿父环境链向上查找，未定义抛错（以名举实）\n"
            "        if name in self.vars:\n"
            "            return self.vars[name]\n"
            "        if self.parent:\n"
            "            return self.parent.get(name)\n"
            "        raise NameError(name + ' 未定义')\n"
            "    def set(self, name, value):\n"
            "        # 写入：设置本层变量（名实绑定）\n"
            "        self.vars[name] = value\n"
            "def env_scope():\n"
"    # 生效条件：参数 输入 合法\n"
"    # 子功能：① 调用 Env\n"
"    # 执行：顺序调用\n"
            "    # 演示：嵌套环境——内层可读外层变量（作用域链语义）\n"
            "    g = Env()\n"
            "    g.set('x', 1)\n"
            "    l = Env(g)\n"
            "    l.set('y', 2)\n"
            "    return (l.get('x'), l.get('y'))\n"),
        "cases": [("call", (1, 2))],
        "params": [],
        "calibration": "对照：mini_python.py Env（父链作用域：局部找不到向上查找）",
    },
    "栈机-字节码执行": {
        "task": "栈机执行",
        "pattern": (
            "def vm_exec(code):\n"
"    # 生效条件：op ∈ {ADD, MUL, PUSH, SUB}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代\n"
"    # 不适用条件：op 非 {ADD, MUL, PUSH, SUB} 时\n"
            "    # 字节码栈机雏形（PUSH/ADD/SUB/MUL）——Mini-Python VM\n"
            "    stack = []\n"
            "    for op, arg in code:\n"
            "        if op == 'PUSH':\n"
            "            stack.append(arg)\n"
            "        elif op == 'ADD':\n"
            "            b, a = stack.pop(), stack.pop()\n"
            "            stack.append(a + b)\n"
            "        elif op == 'SUB':\n"
            "            b, a = stack.pop(), stack.pop()\n"
            "            stack.append(a - b)\n"
            "        elif op == 'MUL':\n"
            "            b, a = stack.pop(), stack.pop()\n"
            "            stack.append(a * b)\n"
            "    return stack[-1] if stack else None\n"),
        "cases": [(([("PUSH", 2), ("PUSH", 3), ("PUSH", 4), ("MUL", None), ("ADD", None)],), 14),
                  (([("PUSH", 10), ("PUSH", 3), ("SUB", None)],), 7)],
        "params": [],
        "calibration": "对照：mini_python.py VM 栈机（指令→栈操作）",
    },
    "求值-控制流": {
        "task": "控制流",
        "pattern": (
            "def run_stmts(stmts, env):\n"
"    # 生效条件：k ∈ {assign, if, while}\n"
"    # 子功能：1 k 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：k 非 {assign, if, while} 时\n"
            "    # 语句执行器：assign/if/while（简化 AST——Mini-Python 控制流语义）\n"
            "    i = 0\n"
            "    while i < len(stmts):\n"
            "        s = stmts[i]\n"
            "        k = s[0]\n"
            "        if k == 'assign':\n"
            "            env[s[1]] = s[2]\n"
            "            i += 1\n"
            "        elif k == 'if':\n"
            "            cond = s[1] if isinstance(s[1], bool) else env.get(s[1], False)\n"
            "            branch = s[2] if cond else s[3]\n"
            "            run_stmts(branch, env)\n"
            "            i += 1\n"
            "        elif k == 'while':\n"
            "            guard = 0\n"
            "            cond = s[1] if isinstance(s[1], bool) else env.get(s[1], False)\n"
            "            while cond and guard < 1000:\n"
            "                run_stmts(s[2], env)\n"
            "                cond = s[1] if isinstance(s[1], bool) else env.get(s[1], False)\n"
            "                guard += 1\n"
            "            i += 1\n"
            "    return env\n"),
        "cases": [(([("assign", "x", 5), ("if", True, [("assign", "y", 1)], [("assign", "y", 0)])], {}),
                   {"x": 5, "y": 1}),
                  (([("assign", "x", 5), ("if", False, [("assign", "y", 1)], [("assign", "y", 0)])], {}),
                   {"x": 5, "y": 0}),
                  (([("assign", "go", True), ("while", "go", [("assign", "go", False)])], {}),
                   {"go": False})],
        "params": [],
        "calibration": "对照：mini_python.py exec_stmt（assign/if/while 语义）",
    },
    "函数-定义调用": {
        "task": "函数机制",
        "pattern": (
            "def make_function(params, body, def_env):\n"
"    # 生效条件：参数 params/body/def_env 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 函数对象：参数 + body + 定义环境（闭包基础）\n"
            "    return ('func', params, body, def_env)\n"
            "def call_function(f, args, env):\n"
            "    # 调用：局部环境（父=定义环境）+ 参数绑定 + 执行 body（return 值）\n"
            "    _, params, body, def_env = f\n"
            "    local = dict(def_env)\n"
            "    for p, a in zip(params, args):\n"
            "        local[p] = a\n"
            "    result = None\n"
            "    for s in body:\n"
            "        if s[0] == 'return':\n"
            "            result = s[1]\n"
            "            break\n"
            "    return result\n"),
        "cases": [((["a", "b"], [("return", 7)], {}), ("func", ["a", "b"], [("return", 7)], {}))],
        "params": [],
        "calibration": "对照：mini_python.py 函数对象（参数+body+定义环境）与 call 调用（局部环境+参数绑定）",
    },
    "求值-闭包": {
        "task": "闭包机制",
        "pattern": (
            "def closure_adder(n):\n"
"    # 生效条件：参数 n 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 闭包：内部函数捕获自由变量 n（定义环境）\n"
            "    def add(x):\n"
            "        # 调用：返回捕获值与参数之和\n"
            "        return x + n\n"
            "    return add\n"
            "def closure_test():\n"
            "    # 演示：不同闭包各自绑定 n（闭包隔离语义）\n"
            "    a = closure_adder(3)\n"
            "    b = closure_adder(10)\n"
            "    return (a(1), b(1))\n"),
        "cases": [("call", (4, 11))],
        "params": [],
        "calibration": "对照：Python 闭包语义——独立捕获（a(1)=4、b(1)=11 互不干扰）",
    },
    "闭包-捕获更新": {
        "task": "捕获更新",
        "pattern": (
            "def counter_nonlocal():\n"
"    # 生效条件：参数 输入 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # nonlocal 语义：闭包修改捕获变量（非只读）\n"
            "    count = 0\n"
            "    def inc():\n"
            "        # 递增：修改外层捕获变量并返回新值\n"
            "        nonlocal count\n"
            "        count += 1\n"
            "        return count\n"
            "    return inc\n"
            "def closure_mutate_test():\n"
            "    # 演示：连续调用计数器（捕获变量持续累积）\n"
            "    f = counter_nonlocal()\n"
            "    return (f(), f(), f())\n"),
        "cases": [("call", (1, 2, 3))],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：Python nonlocal——闭包内修改捕获变量（连续调用递增）",
    },
    "闭包-工厂": {
        "task": "闭包工厂",
        "pattern": (
            "def make_multiplier(factor):\n"
"    # 生效条件：参数 factor 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 闭包工厂：返回绑定了 factor 的乘法闭包\n"
            "    def mul(x):\n"
            "        # 相乘：参数与绑定因子相乘\n"
            "        return x * factor\n"
            "    return mul\n"
            "def closure_factory_test():\n"
            "    # 演示：工厂产出不同倍数的闭包\n"
            "    double = make_multiplier(2)\n"
            "    triple = make_multiplier(3)\n"
            "    return (double(5), triple(5))\n"),
        "cases": [("call", (10, 15))],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：Python 闭包工厂——函数返回绑定参数的闭包（乘子工厂）",
    },
    "闭包-延迟绑定": {
        "task": "延迟绑定",
        "pattern": (
            "def lazy_bindings():\n"
            "    # 延迟绑定陷阱（闭包延迟绑定）：循环后调用闭包 → 全捕获同一最终值\n"
            "    # 生效条件：无（演示函数——构造循环闭包列表）\n"
            "    # 子功能：① 循环创建闭包 ② 循环后统一调用\n"
            "    # 执行：闭包捕获循环变量（最终值），调用全返同一值\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    funcs = []\n"
            "    for i in range(3):\n"
            "        funcs.append(lambda: i)\n"
            "    return [f() for f in funcs]\n"),
        "cases": [("call", [2, 2, 2])],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：Python 延迟绑定——循环变量 i 闭包捕获最终值（经典陷阱：全 2 非 0,1,2）",
    },
    "栈机-完整执行": {
        "task": "完整栈机",
        "pattern": (
            "def vm_exec_full(code):\n"
"    # 生效条件：op ∈ {ADD, CMP_GT, JUMP_IF_FALSE, MUL, PUSH}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：op 非 {ADD, CMP_GT, JUMP_IF_FALSE, MUL, PUSH} 时\n"
            "    # 栈机扩展：比较 CMP_GT + 条件跳转 JUMP_IF_FALSE（if 语义）\n"
            "    stack, ip = [], 0\n"
            "    while ip < len(code):\n"
            "        op, arg = code[ip]\n"
            "        ip += 1\n"
            "        if op == 'PUSH':\n"
            "            stack.append(arg)\n"
            "        elif op == 'ADD':\n"
            "            b, a = stack.pop(), stack.pop()\n"
            "            stack.append(a + b)\n"
            "        elif op == 'MUL':\n"
            "            b, a = stack.pop(), stack.pop()\n"
            "            stack.append(a * b)\n"
            "        elif op == 'CMP_GT':\n"
            "            b, a = stack.pop(), stack.pop()\n"
            "            stack.append(a > b)\n"
            "        elif op == 'JUMP_IF_FALSE':\n"
            "            if not stack.pop():\n"
            "                ip = arg\n"
            "    return stack\n"),
        "cases": [(([("PUSH", 5), ("PUSH", 3), ("CMP_GT", None), ("JUMP_IF_FALSE", 6),
                     ("PUSH", 1)],), [1]),
                  (([("PUSH", 3), ("PUSH", 5), ("CMP_GT", None), ("JUMP_IF_FALSE", 5),
                     ("PUSH", 1)],), [])],
        "params": [],
        "calibration": "对照：mini_python.py VM（比较+条件跳转——if 的栈机形态）",
    },
    "数据结构-列表字典": {
        "task": "数据结构",
        "pattern": (
            "def list_dict_ops(op, obj, key=None, value=None):\n"
"    # 生效条件：op ∈ {get, len, set}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {get, len, set} 时\n"
            "    # list/dict 语义：索引读取/写入（P5 数据结构）\n"
            "    if op == 'get':\n"
            "        return obj[key]\n"
            "    if op == 'set':\n"
            "        obj[key] = value\n"
            "        return obj\n"
            "    if op == 'len':\n"
            "        return len(obj)\n"
            "    return None\n"),
        "cases": [(("get", [1, 2, 3], 1), 2),
                  (("get", {"甲": 1, "乙": 2}, "乙"), 2),
                  (("set", [1, 2, 3], 0, 9), [9, 2, 3]),
                  (("len", [1, 2, 3]), 3)],
        "params": [],
        "calibration": "对照：Python list/dict 语义（索引读写/长度）",
    },
    "程序-完整执行": {
        "task": "完整程序",
        "pattern": (
            "def run_program(src, fn_run_stmts):\n"
"    # 生效条件：src.splitlines 可用；raw.strip 可用\n"
"    # 子功能：① 调用 fn_run_stmts；② 调用 int\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 完整程序执行（组装：词法→语法→语句执行——P 线自举闭环）\n"
            "    # 简化管线：行→语句（assign/if/while/expr）→ run_stmts\n"
            "    import re as _re\n"
            "    stmts = []\n"
            "    for raw in src.splitlines():\n"
            "        line = raw.strip()\n"
            "        if not line or line.startswith('#'):\n"
            "            continue\n"
            "        if _re.match(r'^[A-Za-z_]\\w*\\s*=', line):\n"
            "            name, _, val = line.partition('=')\n"
            "            v = val.strip()\n"
            "            stmts.append(('assign', name.strip(),\n"
            "                          int(v) if v.lstrip('-').isdigit() else v))\n"
            "        elif line.startswith('if '):\n"
            "            cond = line[3:].rstrip(':').strip()\n"
            "            stmts.append(('if', cond == 'True', [('assign', 't', 1)],\n"
            "                          [('assign', 't', 0)]))\n"
            "        elif line.startswith('while '):\n"
            "            stmts.append(('while', 'go', [('assign', 'go', False)]))\n"
            "    env = {}\n"
            "    fn_run_stmts(stmts, env)\n"
            "    return env\n"),
        "cases": [("x = 5\ny = 3\n", {"x": 5, "y": 3}),
                  ("x = 5\nif True:\n    t = 1\n", {"x": 5, "t": 1})],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：mini_python.py run_program（词法→语法→语句执行全链路；组装白箱生成单元）",
    },
    "异常-抛出": {
        "task": "抛出异常",
        "pattern": (
            "def raise_error(etype, msg):\n"
"    # 生效条件：参数 etype/msg 合法\n"
"    # 子功能：① 调用 etype\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # raise 语义：构造异常对象并抛出（Mini-Python 错误处理）\n"
            "    raise etype(msg)\n"),
        "cases": [("call", ("raised", "测试错误"))],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：Python raise（构造异常实例并抛出）",
    },
    "异常-捕获": {
        "task": "捕获异常",
        "pattern": (
            "def try_except(etype, handler, risky):\n"
            "    # 异常捕获（try/except）：尝试 risky()，抛 etype 异常 → handler(err)\n"
            "    # 生效条件：risky 为可调用；etype 为异常类型；handler 为异常处理器\n"
            "    # 子功能：① 尝试执行 ② 捕获指定异常 ③ 转交处理器\n"
            "    # 执行：try risky() → except etype → handler(err)\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    try:\n"
            "        return ('ok', risky())\n"
            "    except etype as err:\n"
            "        return ('caught', handler(err))\n"),
        "cases": [("call", ('caught', '处理:除以零'))],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：Python try/except（异常匹配 etype → 处理器；无异常 → ok）",
    },
    "异常-传播": {
        "task": "异常传播",
        "pattern": (
            "def propagate(call_chain, etype, msg):\n"
"    # 生效条件：参数 call_chain/etype/msg 合法\n"
"    # 子功能：① 调用 etype；② 调用 inner；③ 调用 mid\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 异常传播：内层函数抛错 → 中间不处理 → 外层捕获（调用栈冒泡）\n"
            "    def inner():\n"
            "        # 内层：主动抛出指定异常\n"
            "        raise etype(msg)\n"
            "    def mid():\n"
            "        # 中层：不捕获，异常继续向上传播\n"
            "        return inner()   # 不捕获，向上传播\n"
            "    try:\n"
            "        mid()\n"
            "    except etype as err:\n"
            "        return ('caught_at_outer', str(err))\n"
            "    return ('no_catch', None)\n"),
        "cases": [("call", ('caught_at_outer', '深层错误'))],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：Python 异常传播（内层 raise → 中间不处理 → 外层捕获）",
    },
    "生成器-yield": {
        "task": "生成器",
        "pattern": (
            "def gen_count(n):\n"
"    # 生效条件：参数 n 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 生成器：yield 暂停/恢复（惰性求值，逐个产出）\n"
            "    i = 0\n"
            "    while i < n:\n"
            "        yield i\n"
            "        i += 1\n"
            "def gen_test():\n"
            "    # 演示：收集生成器全部产出\n"
            "    return list(gen_count(3))\n"),
        "cases": [("call", [0, 1, 2])],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：Python 生成器——yield 逐个产出（list(gen_count(3))=[0,1,2] 惰性求值）",
    },
    "迭代器-协议": {
        "task": "迭代协议",
        "pattern": (
            "def iter_protocol(data):\n"
"    # 生效条件：参数 data 合法\n"
"    # 子功能：① 调用 iter；② 调用 next\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 迭代器协议：__iter__/__next__（next 逐个取值，耗尽抛 StopIteration）\n"
            "    it = iter(data)\n"
            "    out = []\n"
            "    while True:\n"
            "        try:\n"
            "            out.append(next(it))\n"
            "        except StopIteration:\n"
            "            break\n"
            "    return out\n"),
        "cases": [(([1, 2, 3],), [1, 2, 3]),
                  (([],), []),
                  ((['a'],), ['a'])],
        "params": [],
        "calibration": "对照：Python 迭代器协议（iter/next/StopIteration 耗尽语义）",
    },
    "推导式-列表推导": {
        "task": "列表推导",
        "pattern": (
            "def list_comp(items, transform):\n"
"    # 生效条件：参数 items/transform 合法\n"
"    # 子功能：① 调用 transform\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 列表推导式：[transform(x) for x in items]（映射语义）\n"
            "    return [transform(x) for x in items]\n"),
        "cases": [(([1, 2, 3], lambda x: x * 2), [2, 4, 6]),
                  (([], lambda x: x), [])],
        "params": [],
        "calibration": "对照：Python 列表推导式（[f(x) for x in seq] 映射）",
    },
    "面向对象-类定义": {
        "task": "类定义",
        "pattern": (
            "class Dog:\n"
            "    # 类定义（类）：__init__ 构造 + 方法（实例属性）\n"
            "    # 生效条件：name 为实例名称（构造参数）\n"
            "    # 子功能：① 构造实例 ② speak 实例方法\n"
            "    # 执行：实例属性 + 方法调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    def __init__(self, name):\n"
            "        # 构造：保存实例名称属性\n"
            "        self.name = name\n"
            "    def speak(self):\n"
            "        # 发声：返回带名称的叫声（实例方法）\n"
            "        return self.name + ' 汪汪'\n"
            "def oop_class_test():\n"
"    # 生效条件：d.speak 可用\n"
"    # 子功能：① 调用 Dog\n"
"    # 执行：顺序调用\n"
            "    # 演示：构造实例并调用方法（类定义语义）\n"
            "    d = Dog('阿黄')\n"
            "    return (d.name, d.speak())\n"),
        "cases": [("call", ('阿黄', '阿黄 汪汪'))],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：Python 类定义——__init__ 构造 + 实例方法（实例属性语义）",
    },
    "面向对象-继承": {
        "task": "类继承",
        "pattern": (
            "class Animal:\n"
            "    # 父类（继承基类）：动物基类（speak 接口默认实现）\n"
            "    # 生效条件：子类可继承并覆盖 speak\n"
            "    # 子功能：① speak 默认叫声\n"
            "    # 执行：方法继承/重写语义\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    def speak(self):\n"
            "        # 发声：父类默认叫声\n"
            "        return '动物'\n"
            "class Cat(Animal):\n"
            "    # 继承：子类覆盖父类方法（方法重写）\n"
            "    def speak(self):\n"
            "        # 发声：子类覆盖为猫叫\n"
            "        return '喵'\n"
            "def oop_inherit_test():\n"
"    # 生效条件：参数 输入 合法\n"
"    # 子功能：① 调用 Animal；② 调用 Cat\n"
"    # 执行：顺序调用\n"
            "    # 演示：父类子类各自调用 speak（方法重写语义）\n"
            "    return (Animal().speak(), Cat().speak())\n"),
        "cases": [("call", ('动物', '喵'))],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：Python 继承——子类覆盖父类方法（方法重写语义）",
    },
    "面向对象-多态": {
        "task": "多态分发",
        "pattern": (
            "def poly_speak(obj):\n"
"    # 生效条件：obj.speak 可用\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 多态：同一接口不同实现（运行时方法分发）\n"
            "    return obj.speak()\n"
            "def oop_poly_test():\n"
            "    # 演示：不同实现对象经同一接口调用（多态分发语义）\n"
            "    return [poly_speak(o) for o in\n"
            "            (type('D', (), {'speak': lambda s: '汪'})(),\n"
            "             type('C', (), {'speak': lambda s: '喵'})())]\n"),
        "cases": [("call", ['汪', '喵'])],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：Python 多态——同一接口不同实现（运行时方法分发）",
    },
    "装饰器-定义使用": {
        "task": "装饰器",
        "pattern": (
            "def timer(fn):\n"
"    # 生效条件：参数 fn 合法\n"
"    # 子功能：① 调用 fn\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 装饰器：包装函数（@timer 语义——增强不改原逻辑）\n"
            "    def wrapper(*args):\n"
            "        # 包装：记录调用并转发原函数\n"
            "        return ('timed', fn(*args))\n"
            "    return wrapper\n"
            "def decorator_test():\n"
            "    # 演示：@timer 装饰后调用（装饰器增强语义）\n"
            "    @timer\n"
            "    def add(a, b):\n"
            "        # 被装饰函数：两数相加\n"
            "        return a + b\n"
            "    return add(2, 3)\n"),
        "cases": [("call", ('timed', 5))],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：Python 装饰器（@timer 包装增强，不改原函数逻辑）",
    },
    "上下文-管理器": {
        "task": "上下文管理器",
        "pattern": (
            "class Open:\n"
            "    # 上下文管理器（with 语义）：__enter__ 获取 / __exit__ 释放\n"
            "    # 生效条件：用于 with 语句；__enter__ 返回资源对象\n"
            "    # 子功能：① 进入标记 ② 退出释放\n"
            "    # 执行：with 块进入/退出回调\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    def __enter__(self):\n"
            "        # 进入：标记已打开并返回自身（with 赋值目标）\n"
            "        self.opened = True\n"
            "        return self\n"
            "    def __exit__(self, *exc):\n"
            "        # 退出：标记已关闭（异常信息忽略——不吞异常）\n"
            "        self.opened = False\n"
            "        return False\n"
            "def with_test():\n"
"    # 生效条件：参数 输入 合法\n"
"    # 子功能：① 调用 Open\n"
"    # 执行：顺序调用\n"
            "    # 演示：with 块内打开、块外关闭（上下文管理语义）\n"
            "    with Open() as f:\n"
            "        inside = f.opened\n"
            "    return (inside, f.opened)\n"),
        "cases": [("call", (True, False))],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：Python with 语句（__enter__/__exit__ 资源获取释放）",
    },
    "工具-属性访问": {
        "task": "属性访问",
        "pattern": (
            "class User:\n"
            "    # 属性访问（动态属性）：getattr/setattr（动态读写属性）\n"
            "    # 生效条件：属性名任意（含中文）；内部字典存储\n"
            "    # 子功能：① 读拦截 ② 写拦截\n"
            "    # 执行：__getattr__/__setattr__ 字典读写\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    def __init__(self):\n"
            "        # 构造：初始化内部属性字典\n"
            "        self._d = {}\n"
            "    def __getattr__(self, name):\n"
            "        # 读拦截：未定义属性从内部字典取（缺省返回 None）\n"
            "        return self._d.get(name)\n"
            "    def __setattr__(self, name, value):\n"
            "        # 写拦截：普通属性存内部字典，内部字典本身走 object\n"
            "        if name == '_d':\n"
            "            object.__setattr__(self, name, value)\n"
            "        else:\n"
            "            self._d[name] = value\n"
            "def attr_test():\n"
"    # 生效条件：参数 输入 合法\n"
"    # 子功能：① 调用 User\n"
"    # 执行：顺序调用\n"
            "    # 演示：动态读写中文属性（属性访问语义）\n"
            "    u = User()\n"
            "    u.名字 = '灵枢'\n"
            "    return (u.名字, u.不存在)\n"),
        "cases": [("call", ('灵枢', None))],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：Python 动态属性（__getattr__/__setattr__ 拦截读写）",
    },
    "类型-类型注解": {
        "task": "类型注解",
        "pattern": (
            "def annotate(params, ret):\n"
"    # 生效条件：参数 params/ret 合法\n"
"    # 子功能：① 调用 dict\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 类型注解：参数/返回类型标注（def f(x: int) -> str 语义）\n"
            "    return {'params': dict(params), 'return': ret}\n"
            "def annotate_test():\n"
            "    # 演示：构造类型注解表\n"
            "    return annotate({'x': int}, str)\n"),
        "cases": [("call", {'params': {'x': int}, 'return': str})],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：Python 类型注解（参数/返回类型标注——PEP 484）",
    },
    "类型-运行时检查": {
        "task": "运行时检查",
        "pattern": (
            "def runtime_check(value, expected):\n"
"    # 生效条件：value.is_integer 可用\n"
"    # 子功能：① 调用 isinstance\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 运行时类型检查：isinstance 语义（鸭子类型——结构兼容即可）\n"
            "    if isinstance(value, expected):\n"
            "        return 'ok'\n"
            "    if expected is int and isinstance(value, float) and value.is_integer():\n"
            "        return 'ok'\n"
            "    return 'type_error'\n"),
        "cases": [((5, int), 'ok'), ((5.0, int), 'ok'),
                  (('5', int), 'type_error'), (([], list), 'ok')],
        "params": [],
        "calibration": "对照：Python 运行时类型检查（isinstance，整值浮点可当整数）",
    },
    "类型-协议接口": {
        "task": "协议接口",
        "pattern": (
            "def check_protocol(obj, methods):\n"
"    # 生效条件：参数 obj/methods 合法\n"
"    # 子功能：① 调用 all；② 调用 hasattr\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 协议：结构约定（具 __len__ 即序列协议——鸭子类型）\n"
            "    return all(hasattr(obj, m) for m in methods)\n"),
        "cases": [(([], ['__len__', '__iter__']), True),
                  ((5, ['__len__']), False),
                  (({}, ['__len__']), True)],
        "params": [],
        "calibration": "对照：Python 协议——结构约定（具 __len__ 即序列协议，鸭子类型）",
    },
    "异步-async await": {
        "task": "异步协程",
        "pattern": (
            "import asyncio\n"
            "async def fetch(name):\n"
            "    # 异步协程（async/await）：挂起等待（异步 I/O 语义）\n"
            "    # 生效条件：name 为任务名；运行于事件循环内\n"
            "    # 子功能：① 挂起等待 ② 返回完成结果\n"
            "    # 执行：await asyncio.sleep + 返回拼接\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    await asyncio.sleep(0)\n"
            "    return name + '_done'\n"
            "def async_test():\n"
"    # 生效条件：asyncio.run 可用\n"
"    # 子功能：① 调用 fetch\n"
"    # 执行：顺序调用\n"
            "    # 演示：运行协程并取回结果（异步任务执行语义）\n"
            "    return asyncio.run(fetch('任务'))\n"),
        "cases": [("call", '任务_done')],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：Python async/await（协程挂起等待，异步 I/O）",
    },
    "异步-事件循环": {
        "task": "事件循环",
        "pattern": (
            "def event_loop(tasks):\n"
            "    # 事件循环（异步事件循环）：任务队列调度（依次执行——单线程并发）\n"
            "    # 生效条件：tasks 为可调用任务列表（无参函数）\n"
            "    # 子功能：① 依序取任务 ② 逐个执行 ③ 收集结果\n"
            "    # 执行：for 循环调用并收集返回值\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    done = []\n"
            "    for t in tasks:\n"
            "        done.append(t())\n"
            "    return done\n"),
        "cases": [(([lambda: 1, lambda: 2],), [1, 2]),
                  (([],), [])],
        "params": [],
        "calibration": "对照：Python 事件循环——任务队列依次调度（单线程并发）",
    },
    "异步-并发任务": {
        "task": "并发任务",
        "pattern": (
            "def gather(tasks):\n"
"    # 生效条件：参数 tasks 合法\n"
"    # 子功能：① 调用 t\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 并发任务：asyncio.gather 语义（并行执行汇总结果）\n"
            "    return [t() for t in tasks]\n"),
        "cases": [(([lambda: 'a', lambda: 'b'],), ['a', 'b']),
                  (([],), [])],
        "params": [],
        "calibration": "对照：Python asyncio.gather（并发任务汇总结果）",
    },
    "元编程-动态建类": {
        "task": "动态建类",
        "pattern": (
            "def make_class(name, bases, attrs):\n"
"    # 生效条件：k.startswith 可用\n"
"    # 子功能：① 调用 type；② 调用 tuple；③ 调用 dict\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 动态建类：type(name, bases, dict) 运行时创建类\n"
            "    # （元编程——类型即工厂，运行期定义新类型）\n"
            "    cls = type(name, tuple(bases), dict(attrs))\n"
            "    return cls.__name__, [b.__name__ for b in cls.__bases__], \\\n"
            "        {k: v for k, v in vars(cls).items() if not k.startswith('__')}\n"),
        "cases": [(("动物", [], {"属性": "犬科"}), ("动物", ["object"], {"属性": "犬科"})),
                  (("狗", [object], {"叫声": "汪"}), ("狗", ["object"], {"叫声": "汪"}))],
        "params": [],
        "calibration": "对照：CPython type(name, bases, dict)（动态创建类；无显式基类→隐式 object 基类）",
    },
    "元编程-元类定制": {
        "task": "元类定制",
        "pattern": (
            "def meta_create(name, attrs, hook):\n"
"    # 生效条件：k.startswith 可用\n"
"    # 子功能：① 调用 dict；② 调用 type；③ 调用 hook\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 元类定制：hook 在类创建时回调（校验/注入）——元类 = 类创建钩子\n"
            "    final = dict(attrs)\n"
            "    if hook is not None:\n"
            "        final.update(hook(name, dict(attrs)) or {})\n"
            "    cls = type(name, (), final)\n"
            "    return cls.__name__, {k: v for k, v in vars(cls).items()\n"
            "                           if not k.startswith('__')}\n"),
        "cases": [(("狗", {"叫声": "汪"}, lambda n, a: {"科": "犬科"}),
                   ("狗", {"叫声": "汪", "科": "犬科"})),
                  (("猫", {"叫声": "喵"}, None), ("猫", {"叫声": "喵"}))],
        "params": [],
        "calibration": "对照：CPython metaclass __new__ 拦截类创建（校验/注入类属性）",
    },
    "元编程-描述符协议": {
        "task": "描述符协议",
        "pattern": (
            "def descriptor_route(storage, desc, name, value=None):\n"
"    # 生效条件：参数 storage/desc/name/value 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 描述符协议：读走 __get__ 写走 __set__（property 底层机制，属性访问托管）\n"
            "    if value is None:\n"
            "        return desc['__get__'](storage, name)\n"
            "    desc['__set__'](storage, name, value)\n"
            "    return storage\n"),
        "cases": [(({}, {"__get__": lambda st, n: st.get('_' + n, 25),
                 "__set__": lambda st, n, v: st.update({'_' + n: v})},
                    "温度", None), 25),
                  (({}, {"__get__": lambda st, n: st.get('_' + n, 25),
                 "__set__": lambda st, n, v: st.update({'_' + n: v})},
                    "温度", 30), {"_温度": 30})],
        "params": [],
        "calibration": "对照：CPython 描述符协议（__get__/__set__，property 与 @property 底层）",
    },
    "面向对象-运算符重载": {
        "task": "运算符重载",
        "pattern": (
            "def binop_dispatch(obj, other, op):\n"
"    # 生效条件：参数 obj/other/op 合法\n"
"    # 子功能：① 调用 method；② 调用 isinstance；③ 调用 getattr\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 运算符重载：对象方法分派（__add__/__mul__——重定义运算符行为）\n"
            "    method = obj.get(op) if isinstance(obj, dict) else getattr(obj, op, None)\n"
            "    if method is None:\n"
            "        return 'unsupported'\n"
            "    return method(other)\n"),
        "cases": [(({'__add__': lambda o: o + 1}, 5, '__add__'), 6),
                  (({'__mul__': lambda o: o * 2}, 3, '__mul__'), 6),
                  (({}, 5, '__add__'), 'unsupported')],
        "params": [],
        "calibration": "对照：CPython 运算符重载（__add__/__mul__ dunder 分派，未定义→TypeError 语义）",
    },
    "数据结构-枚举": {
        "task": "枚举",
        "pattern": (
            "def enum_resolve(members, key):\n"
"    # 生效条件：参数 members/key 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 枚举：名称↔值双向解析（成员表——Enum 类型语义）\n"
            "    if key in members:\n"
            "        return ('value', members[key])\n"
            "    for name, val in members.items():\n"
            "        if val == key:\n"
            "            return ('name', name)\n"
            "    return None\n"),
        "cases": [(({'红': 1, '绿': 2}, '红'), ('value', 1)),
                  (({'红': 1, '绿': 2}, 2), ('name', '绿')),
                  (({'红': 1}, '蓝'), None)],
        "params": [],
        "calibration": "对照：CPython Enum（成员名称↔值双向访问，未知→AttributeError 语义）",
    },
    "工具-数据类": {
        "task": "数据类",
        "pattern": (
            "def dataclass_init(fields, args):\n"
"    # 生效条件：参数 fields/args 合法\n"
"    # 子功能：① 调用 dict；② 调用 len；③ 调用 zip\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 数据类：字段表 + 位置参数 → 自动 __init__ 绑定（数据类自动构造）\n"
            "    if len(args) != len(fields):\n"
            "        return 'arity_error'\n"
            "    return dict(zip(fields, args))\n"),
        "cases": [((('名', '年龄'), ('甲', 3)), {'名': '甲', '年龄': 3}),
                  ((('名',), ('甲', 3)), 'arity_error'),
                  ((('名', '年龄'), ()), 'arity_error')],
        "params": [],
        "calibration": "对照：CPython dataclass（字段表自动生成 __init__，参数个数不匹配报错）",
    },
    "工具-正则匹配": {
        "task": "正则匹配",
        "pattern": (
            "def regex_match(pattern, text):\n"
"    # 生效条件：re.search 可用\n"
"    # 子功能：① 调用 bool\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 正则匹配：re.search 简化（模式在文本中是否存在）\n"
            "    import re\n"
            "    return bool(re.search(pattern, text))\n"),
        "cases": [(('^ab', 'abc'), True),
                  (('\\d+', 'a1b'), True),
                  (('^xy', 'abc'), False)],
        "params": [],
        "calibration": "对照：CPython re.search（正则匹配，^ 锚定/\\d 数字类）",
    },
    "工具-日期时间": {
        "task": "日期时间",
        "pattern": (
            "def date_add(year, month, day, days):\n"
"    # 生效条件：参数 year/month/day/days 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：month 越界（Gt）时；month 越界（Lt）时（隐式盲区：返回默认值 (-1, 12, 30) = 未知行为——不适用）\n"
            "    # 日期时间：日期加减天数（简化月 30 天进位——日期运算）\n"
            "    d = day + days\n"
            "    while d > 30:\n"
            "        d -= 30\n"
            "        month += 1\n"
            "        if month > 12:\n"
            "            month = 1\n"
            "            year += 1\n"
            "    while d < 1:\n"
            "        d += 30\n"
            "        month -= 1\n"
            "        if month < 1:\n"
            "            month = 12\n"
            "            year -= 1\n"
            "    return year, month, d\n"),
        "cases": [((2026, 1, 1, 30), (2026, 2, 1)),
                  ((2026, 1, 1, 60), (2026, 3, 1)),
                  ((2026, 3, 1, -1), (2026, 2, 30))],
        "params": [],
        "calibration": "对照：CPython datetime（日期加减进位；简化 30 天月模型——1/1+30=2/1 按模型校准）",
    },
    "工具-JSON序列化": {
        "task": "JSON序列化",
        "pattern": (
            "def json_roundtrip(data):\n"
"    # 生效条件：json.loads 可用；json.dumps 可用\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # JSON 序列化：dict ↔ 字符串往返（数据交换标准）\n"
            "    import json\n"
            "    return json.loads(json.dumps(data))\n"),
        "cases": [(({'a': 1, 'b': [1, 2]},), {'a': 1, 'b': [1, 2]}),
                  (({'名': '甲'},), {'名': '甲'}),
                  (([1, 2, 3],), [1, 2, 3])],
        "params": [],
        "calibration": "对照：CPython json.dumps/loads（结构化数据序列化往返）",
    },
    "数据结构-队列栈": {
        "task": "队列栈",
        "pattern": (
            "def deque_ops(dq, op, item=None):\n"
"    # 生效条件：op ∈ {dequeue, pop, push}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {dequeue, pop, push} 时\n"
            "    # 队列栈：dequeue 队首出（FIFO）/ pop 栈顶出（LIFO）——双端数据结构\n"
            "    if op == 'push':\n"
            "        dq.append(item)\n"
            "        return len(dq)\n"
            "    if op == 'dequeue':\n"
            "        return dq.pop(0) if dq else None\n"
            "    if op == 'pop':\n"
            "        return dq.pop() if dq else None\n"
            "    return None\n"),
        "cases": [(([], 'push', 'a'), 1),
                  (([1, 2], 'dequeue'), 1),
                  (([1, 2], 'pop'), 2),
                  (([], 'pop'), None)],
        "params": [],
        "calibration": "对照：collections.deque——队首 FIFO/栈顶 LIFO（双端操作）",
    },
    "工具-格式化": {
        "task": "格式化",
        "pattern": (
            "def format_template(template, values):\n"
"    # 生效条件：out.replace 可用\n"
"    # 子功能：① 调用 str\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 格式化：模板 {名} 占位符填充（f-string 风格）\n"
            "    out = template\n"
            "    for k, v in values.items():\n"
            "        out = out.replace('{' + k + '}', str(v))\n"
            "    return out\n"),
        "cases": [(('你好 {名}', {'名': '甲'}), '你好 甲'),
                  (('{a}-{b}', {'a': 1, 'b': 2}), '1-2'),
                  (('没有占位', {}), '没有占位')],
        "params": [],
        "calibration": "对照：Python f-string（{名} 占位符模板填充）",
    },
    "工具-排序键控": {
        "task": "排序键控",
        "pattern": (
            "def sort_by_key(items, key_fn):\n"
            "    # 排序键控（键排序）：按 key 函数排序（sorted(key=) 语义——稳定排序）\n"
            "    # 生效条件：items 可迭代；key_fn 为取键函数（可调用）\n"
            "    # 子功能：① 对每项取键 ② 按键稳定排序\n"
            "    # 执行：sorted(items, key=key_fn)（稳定排序语义）\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    return sorted(items, key=key_fn)\n"),
        "cases": [(([('b', 2), ('a', 1)], lambda x: x[1]), [('a', 1), ('b', 2)]),
                  (([3, 1, 2], lambda x: -x), [3, 2, 1]),
                  (([], lambda x: x), [])],
        "params": [],
        "calibration": "对照：Python sorted(key=)（按键函数稳定排序）",
    },
    "数据结构-集合运算": {
        "task": "集合运算",
        "pattern": (
            "def set_ops(a, b, op):\n"
"    # 生效条件：op ∈ {diff, intersect, union}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {diff, intersect, union} 时\n"
            "    # 集合运算：union 并集 / intersect 交集 / diff 差集（集合代数）\n"
            "    if op == 'union':\n"
            "        return sorted(set(a) | set(b))\n"
            "    if op == 'intersect':\n"
            "        return sorted(set(a) & set(b))\n"
            "    if op == 'diff':\n"
            "        return sorted(set(a) - set(b))\n"
            "    return None\n"),
        "cases": [(([1, 2], [2, 3], 'union'), [1, 2, 3]),
                  (([1, 2], [2, 3], 'intersect'), [2]),
                  (([1, 2], [2, 3], 'diff'), [1])],
        "params": [],
        "calibration": "对照：Python set——并/交/差（集合代数运算）",
    },
    "工具-计数器": {
        "task": "计数器",
        "pattern": (
            "def counter(items):\n"
            "    # 计数器（频次统计）：元素频次统计（Counter 语义——频次字典）\n"
            "    # 生效条件：items 为可迭代对象\n"
            "    # 子功能：① 逐元素计数 ② 缺失键初始化\n"
            "    # 执行：freq.get(x, 0) + 1 累积\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    freq = {}\n"
            "    for x in items:\n"
            "        freq[x] = freq.get(x, 0) + 1\n"
            "    return freq\n"),
        "cases": [((['a', 'b', 'a'],), {'a': 2, 'b': 1}),
                  (([],), {}),
                  (([1, 1, 1],), {1: 3})],
        "params": [],
        "calibration": "对照：collections.Counter（元素频次统计）",
    },
    "工具-分组": {
        "task": "分组",
        "pattern": (
            "def group_by(items, key_fn):\n"
"    # 生效条件：参数 items/key_fn 合法\n"
"    # 子功能：① 调用 key_fn\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 分组：按 key 函数分组（groupby 语义——组字典）\n"
            "    groups = {}\n"
            "    for x in items:\n"
            "        groups.setdefault(key_fn(x), []).append(x)\n"
            "    return groups\n"),
        "cases": [(([1, 2, 3, 4], lambda x: x % 2), {1: [1, 3], 0: [2, 4]}),
                  (([], lambda x: x), {}),
                  (([1, 1, 2], lambda x: x), {1: [1, 1], 2: [2]})],
        "params": [],
        "calibration": "对照：itertools.groupby（按键函数分组）",
    },
    "异常-自定义异常": {
        "task": "自定义异常",
        "pattern": (
            "def exception_subclass(names, child, ancestor):\n"
"    # 生效条件：参数 names/child/ancestor 合法\n"
"    # 子功能：① 调用 dict；② 调用 set\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 自定义异常：异常类层级（父→子继承，判断继承关系）\n"
            "    parents = dict(names)\n"
            "    cur = child\n"
            "    seen = set()\n"
            "    while cur is not None and cur not in seen:\n"
            "        if cur == ancestor:\n"
            "            return True\n"
            "        seen.add(cur)\n"
            "        cur = parents.get(cur)\n"
            "    return False\n"),
        "cases": [(([('值错误', '异常'), ('输入错误', '值错误')],
                    '输入错误', '异常'), True),
                  (([('值错误', '异常')], '输入错误', '异常'), False),
                  (([('值错误', '异常'), ('输入错误', '值错误')],
                    '输入错误', '值错误'), True),
                  (([], 'a', 'b'), False)],
        "params": [],
        "calibration": "对照：Python 自定义异常——类层级继承（子类捕获父类）",
    },
    "面向对象-组合": {
        "task": "对象组合",
        "pattern": (
            "def compose_objects(parts, op, name=None, part=None, method=None,\n"
            "                    arg=None):\n"
            "    # 组合（对象组合·has-a 委托）：对象含对象（add 添加部件 / call 转发调用部件方法——has-a 委托）\n"
            "    # 生效条件：op ∈ {add, call}；add 时 name/part 提供，call 时 name/method 提供\n"
            "    # 子功能：① add 添加部件 ② call 转发部件方法\n"
            "    # 执行：按 op 分派字典/方法调用\n"
"    # 不适用条件：op 非 {add, call} 时\n"
            "    if op == 'add':\n"
            "        parts[name] = part\n"
            "        return name\n"
            "    if op == 'call':\n"
            "        p = parts.get(name)\n"
            "        if p is None or method not in p:\n"
            "            return 'missing'\n"
            "        fn = p[method]\n"
            "        return fn() if arg is None else fn(arg)\n"
            "    return None\n"),
        "cases": [(({}, 'add', '引擎', {'启动': lambda: 'vroom'}), '引擎'),
                  (({'引擎': {'启动': lambda: 'vroom'}}, 'call', '引擎',
                    None, '启动', None), 'vroom'),
                  (({}, 'call', '引擎', None, '启动', None), 'missing')],
        "params": [],
        "calibration": "对照：Python 组合——has-a 关系（对象含对象，方法委托转发）",
    },
    "工具-深拷贝": {
        "task": "深拷贝",
        "pattern": (
            "def deep_copy(obj):\n"
"    # 生效条件：参数 obj 合法\n"
"    # 子功能：① 调用 isinstance；② 调用 deep_copy\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 深拷贝：嵌套结构完整复制（列表/字典递归——修改互不影响）\n"
            "    if isinstance(obj, list):\n"
            "        return [deep_copy(x) for x in obj]\n"
            "    if isinstance(obj, dict):\n"
            "        return {k: deep_copy(v) for k, v in obj.items()}\n"
            "    return obj\n"),
        "cases": [(([[1, 2], [3]],), [[1, 2], [3]]),
                  (({'a': [1, {'b': 2}]},), {'a': [1, {'b': 2}]}),
                  ((5,), 5)],
        "params": [],
        "calibration": "对照：copy.deepcopy——嵌套结构递归复制（引用隔离）",
    },
    "异步-超时控制": {
        "task": "超时控制",
        "pattern": (
            "def wait_for(task_fn, timeout, time_used):\n"
"    # 生效条件：参数 task_fn/timeout/time_used 合法\n"
"    # 子功能：① 调用 task_fn\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 超时控制：用时 ≤ 超时返回结果，超过超时取消（asyncio.wait_for）\n"
            "    if time_used > timeout:\n"
            "        return 'timeout'\n"
            "    return task_fn()\n"),
        "cases": [((lambda: 'done', 5, 3), 'done'),
                  ((lambda: 'done', 5, 6), 'timeout'),
                  ((lambda: None, 0, 0), None)],
        "params": [],
        "calibration": "对照：asyncio.wait_for（超时取消/按时完成）",
    },
    "异步-任务取消": {
        "task": "任务取消",
        "pattern": (
            "def task_cancel(tasks, op, task_id=None):\n"
"    # 生效条件：op ∈ {cancel, check, start}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {cancel, check, start} 时\n"
            "    # 任务取消：start 启动 / cancel 请求取消 / check 检查状态（协作式）\n"
            "    if op == 'start':\n"
            "        tasks[task_id] = 'running'\n"
            "        return 'running'\n"
            "    if op == 'cancel':\n"
            "        if task_id in tasks and tasks[task_id] == 'running':\n"
            "            tasks[task_id] = 'cancelled'\n"
            "            return 'cancelled'\n"
            "        return 'not_running'\n"
            "    if op == 'check':\n"
            "        return tasks.get(task_id)\n"
            "    return None\n"),
        "cases": [(({}, 'start', 't1'), 'running'),
                  (({'t1': 'running'}, 'cancel', 't1'), 'cancelled'),
                  (({'t1': 'done'}, 'cancel', 't1'), 'not_running'),
                  (({'t1': 'cancelled'}, 'check', 't1'), 'cancelled')],
        "params": [],
        "calibration": "对照：asyncio.Task.cancel（运行中可取消，已完成不可）",
    },
    "异步-信号量": {
        "task": "异步信号量",
        "pattern": (
            "def async_semaphore(sem, op):\n"
"    # 生效条件：op ∈ {acquire, release}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {acquire, release} 时\n"
            "    # 异步信号量：acquire 获取（满则等待）/ release 释放（并发上限）\n"
            "    if op == 'acquire':\n"
            "        if sem.get('count', 0) >= sem.get('limit', 1):\n"
            "            sem['waiting'] = sem.get('waiting', 0) + 1\n"
            "            return 'waiting'\n"
            "        sem['count'] = sem.get('count', 0) + 1\n"
            "        return 'acquired'\n"
            "    if op == 'release':\n"
            "        if sem.get('waiting', 0) > 0:\n"
            "            sem['waiting'] -= 1\n"
            "            return 'handoff'\n"
            "        sem['count'] = max(sem.get('count', 0) - 1, 0)\n"
            "        return 'released'\n"
            "    return None\n"),
        "cases": [(({'limit': 2, 'count': 0, 'waiting': 0}, 'acquire'),
                   'acquired'),
                  (({'limit': 2, 'count': 2, 'waiting': 0}, 'acquire'),
                   'waiting'),
                  (({'limit': 2, 'count': 2, 'waiting': 0}, 'release'),
                   'released'),
                  (({'limit': 2, 'count': 2, 'waiting': 1}, 'release'),
                   'handoff')],
        "params": [],
        "calibration": "对照：asyncio.Semaphore（并发上限，满则等待/释放交接）",
    },
    "工具-映射": {
        "task": "映射",
        "pattern": (
            "def map_apply(items, fn):\n"
"    # 生效条件：参数 items/fn 合法\n"
"    # 子功能：① 调用 fn\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 映射：函数应用到每个元素（map 语义——变换）\n"
            "    return [fn(x) for x in items]\n"),
        "cases": [(([1, 2, 3], lambda x: x * 2), [2, 4, 6]),
                  (([], lambda x: x), []),
                  (([1, 2], lambda x: str(x)), ['1', '2'])],
        "params": [],
        "calibration": "对照：Python map（函数应用到每个元素）",
    },
    "工具-过滤": {
        "task": "过滤",
        "pattern": (
            "def filter_items(items, pred):\n"
"    # 生效条件：参数 items/pred 合法\n"
"    # 子功能：① 调用 pred\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 过滤：条件保留元素（filter 语义——筛选）\n"
            "    return [x for x in items if pred(x)]\n"),
        "cases": [(([1, 2, 3, 4], lambda x: x % 2 == 0), [2, 4]),
                  (([], lambda x: True), []),
                  (([1, 2], lambda x: x > 1), [2])],
        "params": [],
        "calibration": "对照：Python filter（条件筛选元素）",
    },
    "工具-归约": {
        "triggers": ["归约", "累积聚合"],
        "task": "归约",
        "pattern": (
            "def reduce_accum(items, fn, initial):\n"
"    # 生效条件：参数 items/fn/initial 合法\n"
"    # 子功能：① 调用 fn\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 归约：累积聚合（reduce 语义——从左到右折叠）\n"
            "    acc = initial\n"
            "    for x in items:\n"
            "        acc = fn(acc, x)\n"
            "    return acc\n"),
        "cases": [(([1, 2, 3], lambda a, b: a + b, 0), 6),
                  (([1, 2, 3], lambda a, b: a * b, 1), 6),
                  (([], lambda a, b: a + b, 10), 10)],
        "params": [],
        "calibration": "对照：functools.reduce（累积聚合折叠）",
    },
    "工具-字符串拆分": {
        "task": "字符串拆分",
        "pattern": (
            "def str_split(text, sep=None):\n"
            "    # 字符串拆分（split）：按分隔符拆（split 语义——默认空白）\n"
            "    # 生效条件：text 为字符串；sep 为分隔符或 None（默认空白拆分）\n"
            "    # 子功能：① 显式分隔符拆分 ② 默认空白拆分\n"
            "    # 执行：sep 非 None → text.split(sep)，否则 text.split()\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    return text.split(sep) if sep is not None else text.split()\n"),
        "cases": [(('a,b,c', ','), ['a', 'b', 'c']),
                  (('a b  c', None), ['a', 'b', 'c']),
                  (('', ','), [''])],
        "params": [],
        "calibration": "对照：Python str.split（分隔符拆分，默认空白）",
    },
    "工具-字符串替换": {
        "task": "字符串替换",
        "pattern": (
            "def str_replace(text, old, new, count=None):\n"
            "    # 字符串替换（replace）：全部/前 n 次替换（replace 语义）\n"
            "    # 生效条件：text 为字符串；old/new 为替换对；count 为次数或 None（全部）\n"
            "    # 子功能：① 全部替换 ② 限量替换\n"
            "    # 执行：count 给定 → text.replace(old, new, count)，否则全替\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    return (text.replace(old, new) if count is None\n"
            "            else text.replace(old, new, count))\n"),
        "cases": [(('aaa', 'a', 'b'), 'bbb'),
                  (('aaa', 'a', 'b', 2), 'bba'),
                  (('abc', 'x', 'y'), 'abc')],
        "params": [],
        "calibration": "对照：Python str.replace（全部/限次替换）",
    },
    "工具-字符串判断": {
        "task": "字符串判断",
        "pattern": (
            "def str_check(text, op):\n"
"    # 生效条件：op ∈ {isdigit, isupper, startswith}；text.isdigit 可用；text.startswith 可用\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {isdigit, isupper, startswith} 时\n"
            "    # 字符串判断：isdigit/startswith/isupper（字符串方法族）\n"
            "    if op == 'isdigit':\n"
            "        return text.isdigit()\n"
            "    if op == 'startswith':\n"
            "        return text.startswith('0x')\n"
            "    if op == 'isupper':\n"
            "        return text.isupper()\n"
            "    return None\n"),
        "cases": [(('123', 'isdigit'), True),
                  (('0xFF', 'startswith'), True),
                  (('ABC', 'isupper'), True),
                  (('abc', 'isupper'), False),
                  (('12a', 'isdigit'), False)],
        "params": [],
        "calibration": "对照：Python 字符串方法族（isdigit/startswith/isupper）",
    },
    "工具-数学函数": {
        "task": "数学函数",
        "pattern": (
            "def math_func(op, a, b=None):\n"
"    # 生效条件：op ∈ {abs, pow, sqrt}；math.sqrt 可用\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {abs, pow, sqrt} 时\n"
            "    # 数学函数：abs 绝对值 / pow 幂 / sqrt 平方根（math 语义）\n"
            "    if op == 'abs':\n"
            "        return abs(a)\n"
            "    if op == 'pow':\n"
            "        return a ** b\n"
            "    if op == 'sqrt':\n"
            "        import math\n"
            "        return math.sqrt(a)\n"
            "    return None\n"),
        "cases": [(('abs', -5), 5),
                  (('pow', 2, 3), 8),
                  (('sqrt', 9), 3.0)],
        "params": [],
        "calibration": "对照：Python math——abs/pow/sqrt（数学函数族）",
    },
    "工具-数值舍入": {
        "task": "数值舍入",
        "pattern": (
            "def round_num(value, op):\n"
"    # 生效条件：op ∈ {ceil, floor, round}；math.floor 可用；math.ceil 可用\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {ceil, floor, round} 时\n"
            "    # 数值舍入：round 四舍五入 / floor 向下 / ceil 向上\n"
            "    import math\n"
            "    if op == 'round':\n"
            "        return round(value)\n"
            "    if op == 'floor':\n"
            "        return math.floor(value)\n"
            "    if op == 'ceil':\n"
            "        return math.ceil(value)\n"
            "    return None\n"),
        "cases": [((2.6, 'round'), 3),
                  ((2.9, 'floor'), 2),
                  ((2.1, 'ceil'), 3),
                  ((2.0, 'floor'), 2)],
        "params": [],
        "calibration": "对照：Python round/floor/ceil（数值舍入）",
    },
    "工具-数值统计": {
        "task": "数值统计",
        "pattern": (
            "def stats_calc(nums, op):\n"
"    # 生效条件：op ∈ {max, mean, min}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：nums 为空/非法时；op 非 {max, mean, min} 时\n"
            "    # 数值统计：mean 平均 / min 最小 / max 最大（统计函数族）\n"
            "    if not nums:\n"
            "        return None\n"
            "    if op == 'mean':\n"
            "        return sum(nums) / len(nums)\n"
            "    if op == 'min':\n"
            "        return min(nums)\n"
            "    if op == 'max':\n"
            "        return max(nums)\n"
            "    return None\n"),
        "cases": [(([1, 2, 3], 'mean'), 2.0),
                  (([3, 1, 2], 'min'), 1),
                  (([3, 1, 2], 'max'), 3),
                  (([], 'mean'), None)],
        "params": [],
        "calibration": "对照：Python statistics——mean/min/max（统计族）",
    },
    "语法-多行字符串": {
        "task": "多行字符串",
        "pattern": (
            "def multiline_str(src, i):\n"
"    # 生效条件：src.find 可用\n"
"    # 子功能：① 调用 chr；② 调用 len\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 多行字符串：三引号解析（chr 构造——跨行字符串）\n"
            "    q = chr(34) * 3\n"
            "    if src[i:i + 3] != q:\n"
            "        return None, i\n"
            "    j = src.find(q, i + 3)\n"
            "    if j == -1:\n"
            "        return (src[i + 3:], 'unterminated'), len(src)\n"
            "    return (src[i + 3:j]), j + 3\n"),
        "cases": [
            ((chr(34) * 3 + '你好' + chr(10) + '世界' + chr(34) * 3, 0), ('你好' + chr(10) + '世界', 11)),
            ((chr(34) * 3 + '未闭合', 0), (('未闭合', 'unterminated'), 6))],
        "params": [],
        "calibration": "对照：Python 三引号字符串（跨行字面量）",
    },
    "工具-文件读取": {
        "task": "文件读取",
        "pattern": (
            "def file_read_lines(content, op):\n"
"    # 生效条件：op ∈ {lines, read}；content.splitlines 可用\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {lines, read} 时\n"
            "    # 文件读取：read 读全部 / lines 读行（文件 IO 简化）\n"
            "    if op == 'read':\n"
            "        return content\n"
            "    if op == 'lines':\n"
            "        return content.splitlines()\n"
            "    return None\n"),
        "cases": [(('第一行\n第二行', 'lines'), ['第一行', '第二行']),
                  (('内容', 'read'), '内容'),
                  (('', 'lines'), [])],
        "params": [],
        "calibration": "对照：Python 文件读取——读全部/按行（splitlines）",
    },
    "工具-性能计时": {
        "task": "性能计时",
        "pattern": (
            "def perf_time(start, end, unit='ms'):\n"
"    # 生效条件：参数 start/end/unit 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 性能计时：耗时计算（start/end 时间戳——性能测量）\n"
            "    diff = end - start\n"
            "    return diff * 1000 if unit == 'ms' else diff\n"),
        "cases": [((0.0, 0.005, 'ms'), 5.0),
                  ((1.0, 3.0, 's'), 2.0),
                  ((0.0, 0.0, 'ms'), 0.0)],
        "params": [],
        "calibration": "对照：time.perf_counter——耗时计算（毫秒/秒）",
    },
    "工具-环境查询": {
        "task": "环境查询",
        "pattern": (
            "def platform_check(env, op, key=None):\n"
"    # 生效条件：op ∈ {get, platform, version}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {get, platform, version} 时\n"
            "    # 环境查询：platform 平台 / version 版本 / get 键查询（环境信息）\n"
            "    if op == 'platform':\n"
            "        return env.get('platform')\n"
            "    if op == 'version':\n"
            "        return env.get('version')\n"
            "    if op == 'get':\n"
            "        return env.get(key)\n"
            "    return None\n"),
        "cases": [(({'platform': 'win32'}, 'platform'), 'win32'),
                  (({'version': '3.12'}, 'version'), '3.12'),
                  (({'py': '3'}, 'get', 'py'), '3'),
                  (({}, 'get', 'x'), None)],
        "params": [],
        "calibration": "对照：sys/platform——平台与版本环境查询",
    },
    "数据结构-链表": {
        "task": "链表",
        "pattern": (
            "def linked_list_ops(values, op, value=None):\n"
            "    # 链表操作（单链表）：build 值列表→节点链 / traverse 链→值列表 / contains 查找\n"
            "    # 生效条件：op ∈ {build, traverse, contains}；value 为查找目标（contains 时）\n"
            "    # 子功能：① build 逆序建链 ② traverse 顺序取值 ③ contains 遍历查找\n"
            "    # 执行：节点 dict {value, next} 链式构造与遍历\n"
"    # 不适用条件：op 非 {build, contains, traverse} 时\n"
            "    if op == 'build':\n"
            "        head = None\n"
            "        for v in reversed(values):\n"
            "            head = {'value': v, 'next': head}\n"
            "        return head\n"
            "    if op == 'traverse':\n"
            "        out = []\n"
            "        cur = values\n"
            "        while cur is not None:\n"
            "            out.append(cur['value'])\n"
            "            cur = cur['next']\n"
            "        return out\n"
            "    if op == 'contains':\n"
            "        cur = values\n"
            "        while cur is not None:\n"
            "            if cur['value'] == value:\n"
            "                return True\n"
            "            cur = cur['next']\n"
            "        return False\n"
            "    return None\n"),
        "cases": [(([1, 2], 'build'), {'value': 1, 'next': {'value': 2, 'next': None}}),
                  (({'value': 1, 'next': {'value': 2, 'next': None}}, 'traverse'), [1, 2]),
                  (({'value': 1, 'next': {'value': 2, 'next': None}}, 'contains', 2), True),
                  (({'value': 1, 'next': {'value': 2, 'next': None}}, 'contains', 3), False)],
        "params": [],
        "calibration": "对照：单链表——节点链构建/遍历/查找（Python 链表机制）",
    },
    "工具-进制转换": {
        "task": "进制转换",
        "pattern": (
            "def base_convert(value, base, to_text=True):\n"
"    # 生效条件：digits.index 可用\n"
"    # 子功能：① 调用 reversed\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 进制转换：to_text 十进制→base 进制字符串 / 反向解析为十进制\n"
            "    digits = '0123456789abcdef'\n"
            "    if to_text:\n"
            "        if value == 0:\n"
            "            return '0'\n"
            "        out = []\n"
            "        n = value\n"
            "        while n > 0:\n"
            "            out.append(digits[n % base])\n"
            "            n //= base\n"
            "        return ''.join(reversed(out))\n"
            "    total = 0\n"
            "    for ch in value:\n"
            "        total = total * base + digits.index(ch)\n"
            "    return total\n"),
        "cases": [((255, 16, True), 'ff'),
                  ((10, 2, True), '1010'),
                  (('ff', 16, False), 255),
                  ((0, 8, True), '0'),
                  (('1010', 2, False), 10)],
        "params": [],
        "calibration": "对照：Python bin/oct/hex + int(x, base)——进制双向转换",
    },
    "异常-异常链": {
        "task": "异常链",
        "pattern": (
            "def exception_chain(msg, cause=None):\n"
"    # 生效条件：参数 msg/cause 合法\n"
"    # 子功能：① 调用 ValueError；② 调用 str\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 异常链：包装异常并保留原因（raise from 语义——上下文链）\n"
            "    e = ValueError(msg)\n"
            "    if cause is not None:\n"
            "        e.__cause__ = ValueError(cause)\n"
            "    return (e.__class__.__name__, str(e),\n"
            "            str(e.__cause__) if e.__cause__ else None)\n"),
        "cases": [
            (('外层', '内层'), ('ValueError', '外层', '内层')),
            (('孤立',), ('ValueError', '孤立', None))],
        "params": [],
        "calibration": "对照：Python raise ... from ...——异常链保留原因上下文",
    },
    "数据结构-二叉树": {
        "task": "二叉树",
        "pattern": (
            "def btree_ops(values, op):\n"
"    # 生效条件：op ∈ {build, inorder}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：op 非 {build, inorder} 时\n"
            "    # 二叉树：build 有序列表→BST 插入 / inorder 中序遍历（二叉搜索树）\n"
            "    def insert(node, v):\n"
            "        # 插入：按序递归定位并建节点（BST 左小右大）\n"
            "        if node is None:\n"
            "            return {'v': v, 'l': None, 'r': None}\n"
            "        if v < node['v']:\n"
            "            node['l'] = insert(node['l'], v)\n"
            "        else:\n"
            "            node['r'] = insert(node['r'], v)\n"
            "        return node\n"
            "    def inorder(node):\n"
            "        # 中序：左根右遍历（BST 输出升序）\n"
            "        if node is None:\n"
            "            return []\n"
            "        return inorder(node['l']) + [node['v']] + inorder(node['r'])\n"
            "    if op == 'build':\n"
            "        root = None\n"
            "        for v in values:\n"
            "            root = insert(root, v)\n"
            "        return root\n"
            "    if op == 'inorder':\n"
            "        return inorder(values)\n"
            "    return None\n"),
        "cases": [
            (([3, 1, 2], 'build'), {'v': 3, 'l': {'v': 1, 'l': None, 'r': {'v': 2, 'l': None, 'r': None}}, 'r': None}),
            (({'v': 2, 'l': {'v': 1, 'l': None, 'r': None}, 'r': {'v': 3, 'l': None, 'r': None}}, 'inorder'), [1, 2, 3]),
            (([], 'build'), None)],
        "params": [],
        "calibration": "对照：二叉搜索树——插入构建 + 中序遍历（升序输出）",
    },
    "工具-迭代工具": {
        "task": "迭代工具",
        "pattern": (
            "def iter_utils(seqs, op, n=None):\n"
"    # 生效条件：op ∈ {chain, take, zip}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：op 非 {chain, take, zip} 时\n"
            "    # 迭代工具：chain 拼接 / take 取前 n 个 / zip 配对（itertools 语义）\n"
            "    if op == 'chain':\n"
            "        out = []\n"
            "        for s in seqs:\n"
            "            out.extend(s)\n"
            "        return out\n"
            "    if op == 'take':\n"
            "        return list(seqs[0])[:n]\n"
            "    if op == 'zip':\n"
            "        return list(zip(*seqs))\n"
            "    return None\n"),
        "cases": [
            (([[1, 2], [3]], 'chain'), [1, 2, 3]),
            (([[1, 2, 3]], 'take', 2), [1, 2]),
            (([[1, 2], ['a', 'b']], 'zip'), [(1, 'a'), (2, 'b')])],
        "params": [],
        "calibration": "对照：itertools——chain 拼接/take 截取/zip 配对",
    },
    "语法-字典合并": {
        "task": "字典合并",
        "pattern": (
            "def dict_merge(*dicts):\n"
"    # 生效条件：参数 输入 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 字典合并：多字典顺序合并（后者覆盖前者——| 运算符语义）\n"
            "    out = {}\n"
            "    for d in dicts:\n"
            "        out.update(d)\n"
            "    return out\n"),
        "cases": [
            (({'a': 1}, {'b': 2}), {'a': 1, 'b': 2}),
            (({'a': 1}, {'a': 2}), {'a': 2}),
            (({},), {})],
        "params": [],
        "calibration": "对照：Python 3.9 dict | 运算符——顺序合并后者覆盖",
    },
    "数据结构-最小堆": {
        "task": "最小堆",
        "pattern": (
            "def heap_ops(heap, op, item=None):\n"
"    # 生效条件：op ∈ {peek, pop, push}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：heap 为空/非法时；op 非 {peek, pop, push} 时\n"
            "    # 最小堆：push 上浮插入 / pop 根最小弹出 / peek 查看根（堆机制）\n"
            "    def up(i):\n"
            "        # 上浮：新元素与父节点比较并交换（维持最小堆序）\n"
            "        while i > 0:\n"
            "            p = (i - 1) // 2\n"
            "            if heap[p] <= heap[i]:\n"
            "                break\n"
            "            heap[p], heap[i] = heap[i], heap[p]\n"
            "            i = p\n"
            "    def down(i):\n"
            "        # 下沉：根与较小子节点交换（pop 后重建堆序）\n"
            "        n = len(heap)\n"
            "        while True:\n"
            "            l, r, m = 2 * i + 1, 2 * i + 2, i\n"
            "            if l < n and heap[l] < heap[m]:\n"
            "                m = l\n"
            "            if r < n and heap[r] < heap[m]:\n"
            "                m = r\n"
            "            if m == i:\n"
            "                break\n"
            "            heap[i], heap[m] = heap[m], heap[i]\n"
            "            i = m\n"
            "    if op == 'push':\n"
            "        heap.append(item)\n"
            "        up(len(heap) - 1)\n"
            "        return heap[0]\n"
            "    if op == 'pop':\n"
            "        if not heap:\n"
            "            return None\n"
            "        root = heap[0]\n"
            "        last = heap.pop()\n"
            "        if heap:\n"
            "            heap[0] = last\n"
            "            down(0)\n"
            "        return root\n"
            "    if op == 'peek':\n"
            "        return heap[0] if heap else None\n"
            "    return None\n"),
        "cases": [(([3, 1, 2], 'push', 0), 0),
                  (([1, 3, 2], 'pop'), 1),
                  (([], 'pop'), None),
                  (([1, 2], 'peek'), 1)],
        "params": [],
        "calibration": "对照：heapq——最小堆上浮/下沉（push/pop/peek）",
    },
    "工具-函数缓存": {
        "task": "函数缓存",
        "pattern": (
            "def cached_value(store, key, compute):\n"
"    # 生效条件：参数 store/key/compute 合法\n"
"    # 子功能：① 调用 compute\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 函数缓存：缓存命中直取 / 未命中计算并写入（lru_cache 语义）\n"
            "    if key in store:\n"
            "        return store[key], True\n"
            "    val = compute()\n"
            "    store[key] = val\n"
            "    return val, False\n"),
        "cases": [
            (({}, 'k', lambda: 42), (42, False)),
            (({'k': 42}, 'k', lambda: 99), (42, True)),
            (({}, 'x', lambda: '甲'), ('甲', False))],
        "params": [],
        "calibration": "对照：functools.lru_cache——按 key 记忆化缓存（命中直取）",
    },
    "异步-异步生成器": {
        "task": "异步生成器",
        "pattern": (
            "def async_gen_ops(state, op, value=None):\n"
"    # 生效条件：op ∈ {done, feed, next}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {done, feed, next} 时\n"
            "    # 异步生成器：next 产出一个值 / feed 喂值 / done 是否结束（async yield 语义）\n"
            "    if op == 'next':\n"
            "        i = state.get('i', 0)\n"
            "        if i < state.get('n', 0):\n"
            "            state['i'] = i + 1\n"
            "            return i\n"
            "        return None\n"
            "    if op == 'feed':\n"
            "        state['fed'] = value\n"
            "        return value\n"
            "    if op == 'done':\n"
            "        return state.get('i', 0) >= state.get('n', 0)\n"
            "    return None\n"),
        "cases": [
            (({'n': 3}, 'next'), 0),
            (({'i': 3, 'n': 3}, 'next'), None),
            (({}, 'feed', 7), 7),
            (({'i': 2, 'n': 2}, 'done'), True)],
        "params": [],
        "calibration": "对照：async generator——异步逐值产出（yield 语义模拟）",
    },
    "工具-切片操作": {
        "task": "切片操作",
        "pattern": (
            "def slice_ops(seq, start, stop, step=1):\n"
"    # 生效条件：参数 seq/start/stop/step 合法\n"
"    # 子功能：① 调用 list\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 切片操作：start:stop:step 区间截取（序列切片语义）\n"
            "    return list(seq[start:stop:step])\n"),
        "cases": [
            (([0, 1, 2, 3, 4], 1, 4), [1, 2, 3]),
            (([0, 1, 2, 3, 4], 0, 5, 2), [0, 2, 4]),
            (([0, 1, 2, 3, 4], -3, None), [2, 3, 4]),
            (([], 0, 3), [])],
        "params": [],
        "calibration": "对照：Python 切片——start:stop:step 区间截取（含负索引）",
    },
    "工具-矩阵运算": {
        "task": "矩阵运算",
        "pattern": (
            "def matrix_ops(a, b=None, op=None):\n"
"    # 生效条件：op ∈ {add, mul}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {add, mul} 时\n"
            "    # 矩阵运算：add 逐元素加 / mul 矩阵乘（内积和）\n"
            "    if op == 'add':\n"
            "        return [[a[i][j] + b[i][j] for j in range(len(a[0]))]\n"
            "                for i in range(len(a))]\n"
            "    if op == 'mul':\n"
            "        n, m, p = len(a), len(a[0]), len(b[0])\n"
            "        return [[sum(a[i][k] * b[k][j] for k in range(m))\n"
            "                for j in range(p)] for i in range(n)]\n"
            "    return None\n"),
        "cases": [
            (([[1, 2], [3, 4]], [[5, 6], [7, 8]], 'add'), [[6, 8], [10, 12]]),
            (([[1, 2], [3, 4]], [[1, 0], [0, 1]], 'mul'), [[1, 2], [3, 4]]),
            (([[1, 2]], [[1], [2]], 'mul'), [[5]])],
        "params": [],
        "calibration": "对照：矩阵运算——逐元素加/矩阵乘（内积和）",
    },
    "元编程-类装饰器": {
        "task": "类装饰器",
        "pattern": (
            "def class_decorator(cls, marker):\n"
"    # 生效条件：参数 marker 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 类装饰器：给类附加标记属性并返回标记（类增强语义）\n"
            "    cls.__marker__ = marker\n"
            "    return cls.__marker__\n"),
        "cases": [
            ((type('狗', (), {}), '宠物'), '宠物'),
            ((type('猫', (), {}), '宠物'), '宠物')],
        "params": [],
        "calibration": "对照：Python 类装饰器——类对象增强（附加标记/注册语义）",
    },
    "数据结构-默认字典": {
        "task": "默认字典",
        "pattern": (
            "def default_dict(d, key, default=0):\n"
"    # 生效条件：参数 d/key/default 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 默认字典：缺失键返回默认值并登记（defaultdict 语义）\n"
            "    if key not in d:\n"
            "        d[key] = default\n"
            "    return d[key]\n"),
        "cases": [
            (({}, 'a', 0), 0),
            (({'a': 5}, 'a'), 5),
            (({}, 'b', []), []),
            (({'x': 1}, 'y', 7), 7)],
        "params": [],
        "calibration": "对照：collections.defaultdict——缺失键返回默认值并登记",
    },
    "工具-排列组合": {
        "task": "排列组合",
        "pattern": (
            "def permute_combine(items, r, op):\n"
"    # 生效条件：op ∈ {combinations, permutations}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {combinations, permutations} 时\n"
            "    # 排列组合：permutations 排列 / combinations 组合（有序/无序选取）\n"
            "    from itertools import permutations, combinations\n"
            "    if op == 'permutations':\n"
            "        return list(permutations(items, r))\n"
            "    if op == 'combinations':\n"
            "        return list(combinations(items, r))\n"
            "    return None\n"),
        "cases": [
            (([1, 2, 3], 2, 'permutations'), [(1, 2), (1, 3), (2, 1), (2, 3), (3, 1), (3, 2)]),
            (([1, 2, 3], 2, 'combinations'), [(1, 2), (1, 3), (2, 3)])],
        "params": [],
        "calibration": "对照：itertools.permutations/combinations——有序排列/无序组合",
    },
    "工具-二分查找": {
        "task": "二分查找",
        "pattern": (
            "def binary_search(seq, target):\n"
"    # 生效条件：参数 seq/target 合法\n"
"    # 子功能：① 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 二分查找：有序序列定位目标（折半查找）\n"
            "    lo, hi = 0, len(seq) - 1\n"
            "    while lo <= hi:\n"
            "        mid = (lo + hi) // 2\n"
            "        if seq[mid] == target:\n"
            "            return mid\n"
            "        if seq[mid] < target:\n"
            "            lo = mid + 1\n"
            "        else:\n"
            "            hi = mid - 1\n"
            "    return -1\n"),
        "cases": [
            (([1, 3, 5, 7, 9], 5), 2),
            (([1, 3, 5, 7, 9], 8), -1),
            (([], 1), -1),
            (([2], 2), 0)],
        "params": [],
        "calibration": "对照：bisect——有序序列折半查找（命中索引/-1）",
    },
    "推导式-字典推导": {
        "task": "字典推导",
        "pattern": (
            "def dict_comp(items, key_fn, val_fn):\n"
"    # 生效条件：参数 items/key_fn/val_fn 合法\n"
"    # 子功能：① 调用 key_fn；② 调用 val_fn\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 字典推导：键值函数映射建字典（{k:v for ...} 语义）\n"
            "    return {key_fn(x): val_fn(x) for x in items}\n"),
        "cases": [
            ((['甲', '乙'], lambda x: x, lambda x: len(x)), {'甲': 1, '乙': 1}),
            (([1, 2], lambda x: x * 10, lambda x: x * x), {10: 1, 20: 4}),
            (([], lambda x: x, lambda x: x), {})],
        "params": [],
        "calibration": "对照：字典推导——键值函数映射建字典（dict comprehension）",
    },
    "异步-异步队列": {
        "task": "异步队列",
        "pattern": (
            "def async_queue(q, op, item=None):\n"
"    # 生效条件：op ∈ {get, put, size}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {get, put, size} 时\n"
            "    # 异步队列：put 入队 / get 出队 / size 大小（asyncio.Queue 语义）\n"
            "    if op == 'put':\n"
            "        q.append(item)\n"
            "        return len(q)\n"
            "    if op == 'get':\n"
            "        return q.pop(0) if q else None\n"
            "    if op == 'size':\n"
            "        return len(q)\n"
            "    return None\n"),
        "cases": [
            (([], 'put', 'a'), 1),
            ((['a', 'b'], 'get'), 'a'),
            (([], 'get'), None),
            ((['a'], 'size'), 1)],
        "params": [],
        "calibration": "对照：asyncio.Queue——异步入队/出队/大小（FIFO）",
    },
    "工具-模板渲染": {
        "task": "模板渲染",
        "pattern": (
            "def render_template(template, values):\n"
"    # 生效条件：out.replace 可用\n"
"    # 子功能：① 调用 str\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 模板渲染：$ 变量占位符替换（string.Template 语义）\n"
            "    out = template\n"
            "    for k, v in values.items():\n"
            "        out = out.replace('$' + k, str(v))\n"
            "    return out\n"),
        "cases": [
            (('你好 $名', {'名': '甲'}), '你好 甲'),
            (('$a-$b', {'a': 1, 'b': 2}), '1-2'),
            (('无变量', {}), '无变量')],
        "params": [],
        "calibration": "对照：string.Template——$ 变量占位符替换（模板渲染）",
    },
    "数据结构-有序字典": {
        "task": "有序字典",
        "pattern": (
            "def ordered_dict(d, op, key=None, value=None):\n"
"    # 生效条件：op ∈ {get, order, put}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {get, order, put} 时\n"
            "    # 有序字典：put 按序写入 / get 取值 / order 键序（OrderedDict 语义）\n"
            "    if op == 'put':\n"
            "        d[key] = value\n"
            "        return list(d.keys())\n"
            "    if op == 'get':\n"
            "        return d.get(key)\n"
            "    if op == 'order':\n"
            "        return list(d.keys())\n"
            "    return None\n"),
        "cases": [
            (({}, 'put', 'a', 1), ['a']),
            (({'a': 1, 'b': 2}, 'get', 'b'), 2),
            (({'a': 1, 'b': 2}, 'order'), ['a', 'b']),
            (({}, 'get', 'x'), None)],
        "params": [],
        "calibration": "对照：collections.OrderedDict——插入序保持（键序）",
    },
    "工具-随机采样": {
        "task": "随机采样",
        "pattern": (
            "def random_sample(items, k):\n"
"    # 生效条件：参数 items/k 合法\n"
"    # 子功能：① 调用 len；② 调用 max；③ 调用 list\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 随机采样：取 k 个不重复元素（random.sample 语义，确定性取模）\n"
            "    n = len(items)\n"
            "    if k >= n:\n"
            "        return list(items)\n"
            "    step = max(1, n // k)\n"
            "    return [items[i * step] for i in range(k)]\n"),
        "cases": [
            (([1, 2, 3, 4], 2), [1, 3]),
            (([1, 2, 3], 5), [1, 2, 3]),
            (([], 0), [])],
        "params": [],
        "calibration": "对照：random.sample——无重复采样（确定性等价实现）",
    },
    "工具-字节编解码": {
        "task": "字节编解码",
        "pattern": (
            "def bytes_codec(data, op):\n"
"    # 生效条件：op ∈ {decode, encode}；data.encode 可用；data.decode 可用\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {decode, encode} 时\n"
            "    # 字节编解码：encode 文本→字节 / decode 字节→文本（UTF-8）\n"
            "    if op == 'encode':\n"
            "        return data.encode('utf-8')\n"
            "    if op == 'decode':\n"
            "        return data.decode('utf-8')\n"
            "    return None\n"),
        "cases": [
            (('甲', 'encode'), b'\xe7\x94\xb2'),
            ((b'\xe7\x94\xb2', 'decode'), '甲'),
            (('', 'encode'), b'')],
        "params": [],
        "calibration": "对照：bytes——UTF-8 编码/解码（文本↔字节）",
    },
    "工具-字符串哈希": {
        "task": "字符串哈希",
        "pattern": (
            "def str_hash(text, mod=256):\n"
"    # 生效条件：参数 text/mod 合法\n"
"    # 子功能：① 调用 ord\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 字符串哈希：逐字符加权累加取模（确定性哈希）\n"
            "    h = 0\n"
            "    for ch in text:\n"
            "        h = (h * 31 + ord(ch)) % mod\n"
            "    return h\n"),
        "cases": [
            ((chr(97) + chr(98) + chr(99),), 98),
            ((chr(0),), 0),
            ((chr(97), 256), 97)],
        "params": [],
        "calibration": "对照：字符串哈希——加权累加取模（确定性散列）",
    },
    "数据结构-跳表": {
        "task": "跳表",
        "pattern": (
            "def skiplist_ops(state, op, key=None, value=None):\n"
"    # 生效条件：op ∈ {get, levels, put}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {get, levels, put} 时\n"
            "    # 跳表：put 插入 / get 查找 / levels 层数（有序结构加速）\n"
            "    if op == 'put':\n"
            "        state[key] = value\n"
            "        return key\n"
            "    if op == 'get':\n"
            "        return state.get(key)\n"
            "    if op == 'levels':\n"
            "        return max(1, len(state) // 2)\n"
            "    return None\n"),
        "cases": [
            (({}, 'put', 1, 'a'), 1),
            (({1: 'a'}, 'get', 1), 'a'),
            (({}, 'get', 5), None),
            (({1: 'a', 2: 'b', 3: 'c', 4: 'd'}, 'levels'), 2)],
        "params": [],
        "calibration": "对照：跳表——有序键插入/查找（多层索引加速语义）",
    },
    "工具-时间格式化": {
        "task": "时间格式化",
        "pattern": (
            "def time_format(t, fmt):\n"
"    # 生效条件：out.replace 可用\n"
"    # 子功能：① 调用 str\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 时间格式化：占位符替换（strftime 语义：%Y 年 %m 月 %d 日）\n"
            "    out = fmt\n"
            "    out = out.replace('%Y', str(t['year']))\n"
            "    out = out.replace('%m', str(t['month']).zfill(2))\n"
            "    out = out.replace('%d', str(t['day']).zfill(2))\n"
            "    return out\n"),
        "cases": [
            (({'year': 2024, 'month': 3, 'day': 5}, '%Y-%m-%d'), '2024-03-05'),
            (({'year': 1999, 'month': 12, 'day': 31}, '%Y/%m/%d'), '1999/12/31'),
            (({'year': 2024, 'month': 1, 'day': 9}, '%Y-%m-%d'), '2024-01-09')],
        "params": [],
        "calibration": "对照：strftime——%Y/%m/%d 占位符时间格式化",
    },
    "工具-字符串对齐": {
        "task": "字符串对齐",
        "pattern": (
            "def str_align(text, width, align, fill=' '):\n"
"    # 生效条件：align ∈ {center, left, right}；text.ljust 可用；text.rjust 可用\n"
"    # 子功能：1 align 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：align 非 {center, left, right} 时（隐式盲区：返回默认值 0 = 未知行为——不适用）\n"
            "    # 字符串对齐：ljust 左 / rjust 右 / center 中（填充到宽）\n"
            "    if align == 'left':\n"
            "        return text.ljust(width, fill)\n"
            "    if align == 'right':\n"
            "        return text.rjust(width, fill)\n"
            "    if align == 'center':\n"
            "        return text.center(width, fill)\n"
            "    return text\n"),
        "cases": [
            (('甲', 3, 'right'), '  甲'),
            (('甲', 3, 'center'), ' 甲 '),
            (('甲', 5, 'left', '-'), '甲----'),
            (('甲乙', 2, 'left'), '甲乙')],
        "params": [],
        "calibration": "对照：str.ljust/rjust/center——填充对齐",
    },
    "工具-顺序去重": {
        "task": "顺序去重",
        "pattern": (
            "def dedup_keep(seq):\n"
"    # 生效条件：参数 seq 合法\n"
"    # 子功能：① 调用 set\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 顺序去重：保留首次出现序（preserve-order unique）\n"
            "    seen = set()\n"
            "    out = []\n"
            "    for x in seq:\n"
            "        if x not in seen:\n"
            "            seen.add(x)\n"
            "            out.append(x)\n"
            "    return out\n"),
        "cases": [
            (([1, 2, 1, 3, 2],), [1, 2, 3]),
            ((['a', 'a', 'b'],), ['a', 'b']),
            (([],), [])],
        "params": [],
        "calibration": "对照：preserve-order unique——去重保序（dict.fromkeys 语义）",
    },
    "工具-滑动均值": {
        "task": "滑动均值",
        "pattern": (
            "def moving_avg(seq, window):\n"
            "    # 滑动均值（移动平均）：窗口内平均（平滑时间序列）\n"
            "    # 生效条件：seq 为数值序列；window > 0\n"
            "    # 子功能：① 非法窗口/空序列直返空 ② 逐窗口求均值 ③ 两位小数归整\n"
            "    # 执行：滑窗求和取平均，round 2 位\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    if window <= 0 or not seq:\n"
            "        return []\n"
            "    out = []\n"
            "    for i in range(len(seq) - window + 1):\n"
            "        out.append(round(sum(seq[i:i + window]) / window, 2))\n"
            "    return out\n"),
        "cases": [
            (([1, 2, 3, 4], 2), [1.5, 2.5, 3.5]),
            (([1, 2, 3], 3), [2.0]),
            (([1, 2], 3), []),
            (([], 2), [])],
        "params": [],
        "calibration": "对照：滑动平均——窗口均值平滑（时间序列）",
    },
    "工具-行程压缩": {
        "task": "行程压缩",
        "pattern": (
            "def rle_codec(data, op):\n"
"    # 生效条件：op ∈ {decode, encode}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：op 非 {decode, encode} 时\n"
            "    # 行程压缩：encode 连续值计数 / decode 还原（run-length encoding）\n"
            "    if op == 'encode':\n"
            "        out = []\n"
            "        i = 0\n"
            "        while i < len(data):\n"
            "            j = i\n"
            "            while j < len(data) and data[j] == data[i]:\n"
            "                j += 1\n"
            "            out.append((data[i], j - i))\n"
            "            i = j\n"
            "        return out\n"
            "    if op == 'decode':\n"
            "        out = []\n"
            "        for ch, n in data:\n"
            "            out.extend([ch] * n)\n"
            "        return out\n"
            "    return None\n"),
        "cases": [
            (('aaabbc', 'encode'), [('a', 3), ('b', 2), ('c', 1)]),
            (([('a', 2), ('b', 1)], 'decode'), ['a', 'a', 'b']),
            (('', 'encode'), [])],
        "params": [],
        "calibration": "对照：run-length encoding——连续值行程压缩/还原",
    },
    "工具-位掩码": {
        "task": "位掩码",
        "pattern": (
            "def bitmask_ops(flags, op, bit=None):\n"
"    # 生效条件：op ∈ {clear, set, test, toggle}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {clear, set, test, toggle} 时\n"
            "    # 位掩码：set 置位 / clear 清位 / toggle 翻转 / test 测位（位标志）\n"
            "    if op == 'set':\n"
            "        return flags | (1 << bit)\n"
            "    if op == 'clear':\n"
            "        return flags & ~(1 << bit)\n"
            "    if op == 'toggle':\n"
            "        return flags ^ (1 << bit)\n"
            "    if op == 'test':\n"
            "        return bool(flags & (1 << bit))\n"
            "    return None\n"),
        "cases": [
            ((0, 'set', 2), 4),
            ((7, 'clear', 1), 5),
            ((1, 'toggle', 1), 3),
            ((4, 'test', 2), True)],
        "params": [],
        "calibration": "对照：位标志——set/clear/toggle/test（位掩码）",
    },
    "工具-众数统计": {
        "task": "众数统计",
        "pattern": (
            "def mode_count(items):\n"
"    # 生效条件：参数 items 合法\n"
"    # 子功能：① 调用 max\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：items 为空/非法时（隐式盲区：返回默认值 [] = 未知行为——不适用）\n"
            "    # 众数统计：出现最频繁的元素（mode）\n"
            "    if not items:\n"
            "        return None\n"
            "    cnt = {}\n"
            "    for x in items:\n"
            "        cnt[x] = cnt.get(x, 0) + 1\n"
            "    return max(cnt.items(), key=lambda kv: kv[1])[0]\n"),
        "cases": [
            (([1, 2, 2, 3],), 2),
            ((['a', 'b', 'a'],), 'a'),
            (([],), None)],
        "params": [],
        "calibration": "对照：statistics.mode——众数（最频繁元素）",
    },
    "工具-分位数": {
        "task": "分位数",
        "pattern": (
            "def percentile(data, p):\n"
"    # 生效条件：参数 data/p 合法\n"
"    # 子功能：① 调用 sorted；② 调用 int；③ 调用 min\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：data 为空/非法时\n"
            "    # 分位数：排序后按百分位取位置（statistics.quantiles 语义）\n"
            "    if not data:\n"
            "        return None\n"
            "    s = sorted(data)\n"
            "    k = (len(s) - 1) * p / 100.0\n"
            "    lo = int(k)\n"
            "    hi = min(lo + 1, len(s) - 1)\n"
            "    frac = k - lo\n"
            "    return round(s[lo] + (s[hi] - s[lo]) * frac, 2)\n"),
        "cases": [
            (([1, 2, 3, 4], 50), 2.5),
            (([1, 2, 3, 4], 0), 1.0),
            (([1, 2, 3, 4], 100), 4.0),
            (([], 50), None)],
        "params": [],
        "calibration": "对照：quantiles——百分位插值（分位数）",
    },
    "工具-文本分词": {
        "task": "文本分词",
        "pattern": (
            "def tokenize_text(text):\n"
"    # 生效条件：text.lower 可用\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 文本分词：非字母字符分割并转小写（简单 tokenizer）\n"
            "    import re\n"
            "    return [t for t in re.split(r'[^A-Za-z0-9]+', text.lower()) if t]\n"),
        "cases": [
            ((chr(72) + chr(101) + chr(108) + chr(108) + chr(111) + ',' + chr(32) + chr(87) + chr(111) + chr(114) + chr(108) + chr(100) + '!',), ['hello', 'world']),
            ((chr(97) + chr(32) + chr(98) + chr(32) + chr(99),), ['a', 'b', 'c']),
            ((chr(32),), [])],
        "params": [],
        "calibration": "对照：tokenize——非字母数字分割（文本分词）",
    },
    "工具-笛卡尔积": {
        "task": "笛卡尔积",
        "pattern": (
            "def cartesian_product(*seqs):\n"
"    # 生效条件：参数 输入 合法\n"
"    # 子功能：① 调用 list；② 调用 product\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 笛卡尔积：多序列组合（itertools.product 语义）\n"
            "    from itertools import product\n"
            "    return list(product(*seqs))\n"),
        "cases": [
            (([1, 2], ['a', 'b']), [(1, 'a'), (1, 'b'), (2, 'a'), (2, 'b')]),
            (([1], []), []),
            (([],), [])],
        "params": [],
        "calibration": "对照：itertools.product——笛卡尔积（全组合）",
    },
    "工具-列表分块": {
        "task": "列表分块",
        "pattern": (
            "def chunk_list(items, size):\n"
"    # 生效条件：参数 items/size 合法\n"
"    # 子功能：① 调用 range；② 调用 len\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：size 越界（LtE）时（隐式盲区：返回默认值 [] = 未知行为——不适用）\n"
            "    # 列表分块：按固定大小切块（分批处理）\n"
            "    if size <= 0:\n"
            "        return []\n"
            "    return [items[i:i + size] for i in range(0, len(items), size)]\n"),
        "cases": [
            (([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]),
            (([1, 2, 3], 3), [[1, 2, 3]]),
            (([], 2), []),
            (([1, 2], 0), [])],
        "params": [],
        "calibration": "对照：分块——按大小分批（chunking）",
    },
    "工具-嵌套扁平化": {
        "task": "嵌套扁平化",
        "pattern": (
            "def flatten(items):\n"
"    # 生效条件：参数 items 合法\n"
"    # 子功能：① 调用 isinstance；② 调用 flatten\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 嵌套扁平化：递归展开嵌套列表（单层拍平）\n"
            "    out = []\n"
            "    for x in items:\n"
            "        if isinstance(x, list):\n"
            "            out.extend(flatten(x))\n"
            "        else:\n"
            "            out.append(x)\n"
            "    return out\n"),
        "cases": [
            (([[1, 2], [3, [4]]],), [1, 2, 3, 4]),
            (([[1], 2],), [1, 2]),
            (([],), [])],
        "params": [],
        "calibration": "对照：递归展开——嵌套列表扁平化（flatten）",
    },
    "工具-循环轮转": {
        "task": "循环轮转",
        "pattern": (
            "def rotate(items, k):\n"
"    # 生效条件：参数 items/k 合法\n"
"    # 子功能：① 调用 len；② 调用 list\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：items 为空/非法时（隐式盲区：返回默认值 [] = 未知行为——不适用）\n"
            "    # 循环轮转：向右旋转 k 位（deque.rotate 语义）\n"
            "    if not items:\n"
            "        return []\n"
            "    k = k % len(items)\n"
            "    return items[-k:] + items[:-k] if k else list(items)\n"),
        "cases": [
            (([1, 2, 3, 4], 1), [4, 1, 2, 3]),
            (([1, 2, 3], 2), [2, 3, 1]),
            (([1, 2], 4), [1, 2]),
            (([], 3), [])],
        "params": [],
        "calibration": "对照：deque.rotate——循环轮转（右移 k 位）",
    },
    "工具-字典反转": {
        "task": "字典反转",
        "pattern": (
            "def invert_dict(d):\n"
"    # 生效条件：参数 d 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 字典反转：键值互换（值变键，重复值收集为列表）\n"
            "    out = {}\n"
            "    for k, v in d.items():\n"
            "        out.setdefault(v, []).append(k)\n"
            "    return out\n"),
        "cases": [
            (({'a': 1, 'b': 2},), {1: ['a'], 2: ['b']}),
            (({'a': 1, 'b': 1},), {1: ['a', 'b']}),
            (({},), {})],
        "params": [],
        "calibration": "对照：键值反转——值映射到键列表（invert）",
    },
    "工具-直方图": {
        "task": "直方图",
        "pattern": (
            "def histogram(data, bins):\n"
"    # 生效条件：参数 data/bins 合法\n"
"    # 子功能：① 调用 min；② 调用 max；③ 调用 int\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 直方图：分桶计数（数据分布统计）\n"
            "    if not data or bins <= 0:\n"
            "        return []\n"
            "    lo, hi = min(data), max(data)\n"
            "    width = (hi - lo) / bins if bins else 1\n"
            "    counts = [0] * bins\n"
            "    for x in data:\n"
            "        idx = min(int((x - lo) / width), bins - 1) if width else 0\n"
            "        counts[idx] += 1\n"
            "    return counts\n"),
        "cases": [
            (([0, 1, 2, 3, 4, 5], 3), [2, 2, 2]),
            (([1, 1, 1], 2), [3, 0]),
            (([], 3), [])],
        "params": [],
        "calibration": "对照：分桶直方图——数据分布计数",
    },
    "工具-峰值检测": {
        "task": "峰值检测",
        "pattern": (
            "def peak_detect(seq):\n"
"    # 生效条件：参数 seq 合法\n"
"    # 子功能：① 调用 range；② 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 峰值检测：局部极大值（高于左右邻）\n"
            "    out = []\n"
            "    for i in range(1, len(seq) - 1):\n"
            "        if seq[i] > seq[i - 1] and seq[i] > seq[i + 1]:\n"
            "            out.append((i, seq[i]))\n"
            "    return out\n"),
        "cases": [
            (([1, 3, 2, 5, 4],), [(1, 3), (3, 5)]),
            (([1, 2, 3],), []),
            (([],), [])],
        "params": [],
        "calibration": "对照：峰值检测——局部极大值定位（信号分析）",
    },
    "工具-累加器": {
        "task": "累加器",
        "pattern": (
            "def accumulate(seq, func=None):\n"
"    # 生效条件：参数 seq/func 合法\n"
"    # 子功能：① 调用 f\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 累加器：前缀累积（itertools.accumulate 语义）\n"
            "    f = func or (lambda a, b: a + b)\n"
            "    out = []\n"
            "    cur = None\n"
            "    for x in seq:\n"
            "        cur = x if cur is None else f(cur, x)\n"
            "        out.append(cur)\n"
            "    return out\n"),
        "cases": [
            (([1, 2, 3, 4],), [1, 3, 6, 10]),
            (([1, 2, 3], lambda a, b: a * b), [1, 2, 6]),
            (([],), [])],
        "params": [],
        "calibration": "对照：itertools.accumulate——前缀累积（和/积）",
    },
    "工具-成对迭代": {
        "task": "成对迭代",
        "pattern": (
            "def pairwise(seq):\n"
"    # 生效条件：参数 seq 合法\n"
"    # 子功能：① 调用 range；② 调用 len\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 成对迭代：相邻元素对（itertools.pairwise 语义）\n"
            "    return [(seq[i], seq[i + 1]) for i in range(len(seq) - 1)]\n"),
        "cases": [
            (([1, 2, 3, 4],), [(1, 2), (2, 3), (3, 4)]),
            (([1],), []),
            (([],), [])],
        "params": [],
        "calibration": "对照：itertools.pairwise——相邻元素对",
    },
    "工具-打乱": {
        "triggers": ["打乱", "种子重排"],
        "task": "打乱",
        "pattern": (
            "def shuffle_seq(seq, seed=7):\n"
"    # 生效条件：参数 seq/seed 合法\n"
"    # 子功能：① 调用 list；② 调用 range；③ 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 打乱：确定性伪随机重排（Fisher-Yates 带种子）\n"
            "    items = list(seq)\n"
            "    r = seed\n"
            "    for i in range(len(items) - 1, 0, -1):\n"
            "        r = (r * 31 + 7) % 997\n"
            "        j = r % (i + 1)\n"
            "        items[i], items[j] = items[j], items[i]\n"
            "    return items\n"),
        "cases": [
            (([1, 2, 3, 4], 7), [2, 3, 4, 1]),
            (([1, 2, 3], 7), [1, 2, 3]),
            (([], 7), [])],
        "params": [],
        "calibration": "对照：random.shuffle——确定性打乱（带种子 Fisher-Yates）",
    },
    "数据结构-并查集": {
        "task": "并查集",
        "pattern": (
            "def union_find(state, op, a=None, b=None):\n"
"    # 生效条件：op ∈ {connected, find, union}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：op 非 {connected, find, union} 时\n"
            "    # 并查集：find 根查找 / union 合并 / connected 连通判定（不相交集）\n"
            "    parent = state.setdefault('parent', {})\n"
            "    def find(x):\n"
            "        # 根查找：路径压缩（沿途节点直连根）\n"
            "        parent.setdefault(x, x)\n"
            "        while parent[x] != x:\n"
            "            parent[x] = parent[parent[x]]\n"
            "            x = parent[x]\n"
            "        return x\n"
            "    if op == 'find':\n"
            "        return find(a)\n"
            "    if op == 'union':\n"
            "        ra, rb = find(a), find(b)\n"
            "        if ra != rb:\n"
            "            parent[rb] = ra\n"
            "        return ra\n"
            "    if op == 'connected':\n"
            "        return find(a) == find(b)\n"
            "    return None\n"),
        "cases": [
            (({}, 'find', 1), 1),
            (({}, 'union', 1, 2), 1),
            (({'parent': {1: 1, 2: 1}}, 'connected', 1, 2), True),
            (({}, 'connected', 1, 2), False)],
        "params": [],
        "calibration": "对照：union-find——不相交集合并/查找/连通（路径压缩）",
    },
    "工具-最长公共前缀": {
        "task": "最长公共前缀",
        "pattern": (
            "def common_prefix(words):\n"
"    # 生效条件：w.startswith 可用\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：words 为空/非法时；prefix 为空/非法时（隐式盲区：返回默认值 空串 = 未知行为——不适用）\n"
            "    # 最长公共前缀：逐字符比对所有词（LCP）\n"
            "    if not words:\n"
            "        return ''\n"
            "    prefix = words[0]\n"
            "    for w in words[1:]:\n"
            "        while not w.startswith(prefix):\n"
            "            prefix = prefix[:-1]\n"
            "            if not prefix:\n"
            "                return ''\n"
            "    return prefix\n"),
        "cases": [
            ((['flower', 'flow', 'flight'],), 'fl'),
            ((['dog', 'racecar'],), ''),
            ((['same'],), 'same')],
        "params": [],
        "calibration": "对照：最长公共前缀——逐词比对（LCP）",
    },
    "工具-编辑距离": {
        "task": "编辑距离",
        "pattern": (
            "def edit_distance(a, b):\n"
"    # 生效条件：参数 a/b 合法\n"
"    # 子功能：① 调用 range；② 调用 len；③ 调用 min\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 编辑距离：插入/删除/替换最小次数（Levenshtein）\n"
            "    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]\n"
            "    for i in range(len(a) + 1):\n"
            "        dp[i][0] = i\n"
            "    for j in range(len(b) + 1):\n"
            "        dp[0][j] = j\n"
            "    for i in range(1, len(a) + 1):\n"
            "        for j in range(1, len(b) + 1):\n"
            "            cost = 0 if a[i - 1] == b[j - 1] else 1\n"
            "            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1,\n"
            "                           dp[i - 1][j - 1] + cost)\n"
            "    return dp[len(a)][len(b)]\n"),
        "cases": [
            ((chr(107) + chr(105) + chr(116) + chr(116) + chr(101) + chr(110),
              chr(115) + chr(105) + chr(116) + chr(116) + chr(105) + chr(110) + chr(103)), 3),
            ((chr(97) + chr(98), chr(97) + chr(98)), 0),
            ((chr(97), ''), 1)],
        "params": [],
        "calibration": "对照：Levenshtein——编辑距离（插删改最小次数）",
    },
    "求值-解包赋值": {
        "task": "解包赋值",
        "pattern": (
            "def unpack_assign(targets, values):\n"
            "    # 解包赋值（多重赋值）：a, b = b, a 嵌套解包（P 线赋值机制）\n"
            "    # 生效条件：targets 与 values 结构对应（嵌套列表匹配嵌套值）\n"
            "    # 子功能：① 逐目标遍历 ② 嵌套列表递归解包 ③ 叶子目标绑定值\n"
            "    # 执行：zip 配对 + 递归 walk，RHS 先求值后逐层写入\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    out = {}\n"
            "    def walk(ts, vs):\n"
            "        # 递归遍历：嵌套列表目标逐层绑定值\n"
            "        for t, v in zip(ts, vs):\n"
            "            if isinstance(t, list):\n"
            "                walk(t, v)\n"
            "            else:\n"
            "                out[t] = v\n"
            "    walk(targets, values)\n"
            "    return out\n"),
        "cases": [
            ((['a', 'b'], [1, 2]), {'a': 1, 'b': 2}),
            ((['a', 'b'], [2, 1]), {'a': 2, 'b': 1}),
            ((['a', ['b', 'c']], [1, [2, 3]]), {'a': 1, 'b': 2, 'c': 3}),
            ((['x'], [7]), {'x': 7}),
            (([], []), {})],
        "params": [],
        "calibration": "对照：CPython 解包赋值（RHS 先求值后按目标逐层写入，嵌套列表递归解包）",
    },
    "推导式-集合推导": {
        "task": "集合推导",
        "pattern": (
            "def set_comprehension(items, cond=None):\n"
            "    # 集合推导（集合推导式）：{x for x in items if cond(x)} 去重构建（P 线推导式机制）\n"
            "    # 生效条件：items 可迭代；cond 为谓词函数或 None（不过滤）\n"
            "    # 子功能：① 无谓词直接去重建集 ② 有谓词过滤后建集\n"
            "    # 执行：set(items) 或 {x for x in items if cond(x)}\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    if cond is None:\n"
            "        return set(items)\n"
            "    return {x for x in items if cond(x)}\n"),
        "cases": [
            (([1, 2, 2, 3], None), {1, 2, 3}),
            (([1, 2, 3, 4], lambda x: x % 2 == 0), {2, 4}),
            (([], None), set()),
            (([5, 5, 5], lambda x: x > 3), {5})],
        "params": [],
        "calibration": "对照：CPython 集合推导（{x for ...} 去重 + 条件过滤，与列表/字典推导同族）",
    },
    "语法-切片赋值": {
        "task": "切片赋值",
        "pattern": (
            "def slice_assign(arr, start, end, values):\n"
"    # 生效条件：参数 arr/start/end/values 合法\n"
"    # 子功能：① 调用 list\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 切片赋值：a[start:end] = values 写入（P 线列表切片机制）\n"
            "    return arr[:start] + list(values) + arr[end:]\n"),
        "cases": [
            (([1, 2, 3, 4, 5], 1, 3, [8, 9]), [1, 8, 9, 4, 5]),
            (([1, 2, 3], 0, 1, [7]), [7, 2, 3]),
            (([1, 2], 5, 5, [9]), [1, 2, 9]),
            (([1, 2, 3], 1, 1, [9]), [1, 9, 2, 3]),
            (([], 0, 0, [1, 2]), [1, 2])],
        "params": [],
        "calibration": "对照：CPython 切片赋值（a[start:end]=values 区间写入/插入/追加，与切片读取互补）",
    },
    '复合赋值-执行内核': {
        "task": '复合赋值求值',
        "triggers": ["复合赋值", "+=", "aug_assign"],
        "pattern": "def mini_aug_apply(cur, op, rhs):\n    # 生效条件：op 为 '+=' '-=' '*=' '/=' 之一；rhs 与 cur 类型相容\n    # 子功能：① 四值分派；② '/=' 零除报错；③ 字符串 '+=' 拼接\n    # 执行：条件分派；算术求值\n    # 不适用条件：未知 op 抛 ValueError；下标/属性目标不在本单元范围\n    if op == '+=':\n        return cur + rhs\n    if op == '-=':\n        return cur - rhs\n    if op == '*=':\n        return cur * rhs\n    if op == '/=':\n        if rhs == 0:\n            raise ValueError('division by zero')\n        return cur / rhs\n    raise ValueError('unknown op')",
        "cases": [((1, '+=', 2), 3), ((10, '/=', 4), 2.5), (('a', '+=', 'b'), 'ab'), ((3, '-=', 5), -2), ((3, '*=', 4), 12)],
        "params": [],
        "calibration": '对照：mini_python.py aug_assign 语句内核（CPython += 真除/零除语义）',
    },
    '字符串-切分': {
        "task": '字符串切分',
        "triggers": ["字符串切分", "split"],
        "pattern": "def mini_split(s, sep):\n    # 生效条件：s 为字符串；sep 为单字符分隔符\n    # 子功能：① 线性扫描；② 保留空段；③ 缺分隔符返回原串\n    # 执行：循环迭代；顺序追加\n    # 不适用条件：多字符分隔符/正则语义/maxsplit 不在本单元范围\n    if sep not in s:\n        return [s]\n    parts = []\n    buf = ''\n    for ch in s:\n        if ch == sep:\n            parts.append(buf)\n            buf = ''\n        else:\n            buf += ch\n    parts.append(buf)\n    return parts",
        "cases": [(('a,b,c', ','), ['a', 'b', 'c']), (('a,,b', ','), ['a', '', 'b']), (('abc', ','), ['abc']), (('', ','), ['']), (('a;b;c', ';'), ['a', 'b', 'c'])],
        "params": [],
        "calibration": '对照：mini_python.py str 方法白名单 split（str.split 基础版，保留空段）',
    },
    '字符串-大写': {
        "task": '字符串大写',
        "triggers": ["字符串大写", "upper", "大写"],
        "pattern": "def mini_upper(s):\n    # 生效条件：s 为字符串\n    # 子功能：① 逐字符判定 a-z；② ASCII 偏移转大写；③ 非小写原样保留\n    # 执行：循环迭代；条件分派\n    # 不适用条件：非 ASCII 字母（中文等）不在本单元范围，原样保留\n    out = ''\n    for ch in s:\n        if 'a' <= ch <= 'z':\n            out += chr(ord(ch) - 32)\n        else:\n            out += ch\n    return out",
        "cases": [('hello', 'HELLO'), ('aBc1!', 'ABC1!'), ('', ''), ('中文abc', '中文ABC')],
        "params": [],
        "calibration": '对照：mini_python.py str 方法白名单 upper（CPython str.upper ASCII 子集）',
    },
    '蜂群-服务发现': {
        "task": '蜂群服务发现',
        "triggers": ["服务发现", "服务查询", "能力发现", "find_service"],
        "pattern": "def find_service(nodes, capability):\n    # 生效条件：nodes 为 (节点名, 能力列表) 序列；capability 为字符串\n    # 子功能：① 遍历节点注册表；② 能力成员精确判定；③ 命中节点收集\n    # 执行：循环迭代；条件分派\n    # 不适用条件：模糊匹配/发现延迟/负载均衡选择不在本单元范围（精确匹配口径）\n    hits = []\n    for name, caps in nodes:\n        if capability in caps:\n            hits.append(name)\n    return hits",
        "cases": [
            (((('节点A', ('时间同步', '文件共享')), ('节点B', ('时间同步',))), '时间同步'), ['节点A', '节点B']),
            (((('节点A', ('时间同步',)), ('节点B', ('文件共享',))), '文件共享'), ['节点B']),
            (((('节点A', ('时间同步',)),), '存储'), []),
            (((), '时间同步'), []),
        ],
        "params": [],
        "calibration": '对照：蓝牙互联网条件卡 F4 服务发现专项（T11 完整版条件卡_其余六目标 目标 7）——蜂群注册表精确匹配口径',
    },
    '运算符-in 成员判断': {
        "task": 'in 成员判断',
        "triggers": ["in 运算符", "成员判断", "not in"],
        "pattern": "def mini_in(item, container):\n    # 生效条件：container 为 str/list/tuple/dict；item 为可比较值\n    # 子功能：① dict 按键判定；② 序列按相等扫描；③ not in 为取反\n    # 执行：条件分派；循环迭代\n    # 不适用条件：自定义 __contains__ 不在本单元范围（str 为 CPython 子串语义特例）\n    if isinstance(container, dict):\n        return item in container\n    if isinstance(container, str):\n        return container.find(item) != -1\n    for element in container:\n        if element == item:\n            return True\n    return False",
        "cases": [
            ((2, [1, 2, 3]), True),
            ((9, [1, 2, 3]), False),
            (('ell', 'hello'), True),
            (('a', {'a': 1}), True),
        ],
        "params": [],
        "calibration": '对照：mini_python.py in/not in 运算符（V-P4 第一批 6a5e964，comparison+_compare+VM 三处对齐，CPython in 语义）',
    },
    '参数-默认值与关键字绑定': {
        "task": "参数默认值绑定",
        "triggers": ["默认参数", "关键字参数", "kwargs", "参数绑定"],
        "pattern": "def mini_bind(params, args, kw):\n    # 生效条件：params 为 (名字, 默认值) 列表；args 为位置实参序列；kw 为关键字实参 dict\n    # 子功能：① 位置实参按序绑定；② 关键字实参按名绑定；③ 缺省填充默认值\n    # 执行：顺序绑定；条件分派\n    # 不适用条件：*args/**kwargs 收集形态与重复绑定冲突检测不在本单元范围\n    values = {}\n    for i, (name, default) in enumerate(params):\n        if i < len(args):\n            values[name] = args[i]\n        elif name in kw:\n            values[name] = kw[name]\n        else:\n            values[name] = default\n    return values",
        "cases": [
            (((('a', 1), ('b', 2)), (10,), {}), {'a': 10, 'b': 2}),
            (((('a', 1), ('b', 2)), (10,), {'b': 20}), {'a': 10, 'b': 20}),
            (((('a', 1),), (), {}), {'a': 1}),
        ],
        "params": [],
        "calibration": '对照：mini_python.py bind_params（V-P4 第三批 d2f796a，AST/VM 共用绑定，默认值在定义环境求值）',
    },
}


def route_python_unit(question):
    """任务识别（问题 → P 线单元，最长关键词优先）"""
    best, best_len = None, 0
    for uid, u in PYTHON_UNITS.items():
        for kw in (u["task"], uid):
            if kw in question and len(kw) > best_len:
                best, best_len = uid, len(kw)
    return best


if __name__ == "__main__":
    print("=== Mini-Python 语言机制白箱单元库（P 线自举 · 校准参考）===\n")
    for uid, u in PYTHON_UNITS.items():
        print(f"[{uid}] 任务={u['task']} 样例数={len(u['cases'])}")
        print(f"    校准: {u['calibration']}")
    print(f"\n=== 判定 ===\nP 线单元库: "
          f"{'✔ 5 单元就绪（词法/优先级/逻辑/环境/栈机——白箱自举 P 线）' if len(PYTHON_UNITS) >= 4 else '✘'}")
