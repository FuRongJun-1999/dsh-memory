# -*- coding: utf-8 -*-
"""mini_python.py · Mini-Python 解释器（第六阶段 P1·机制训练场）
P1：词法 + 语法 + 表达式求值（对照 CPython 行为，P 线校准参考实现）
  - or/and 返回操作数 + 短路；/ 返回 float；// % floor；** 右结合高优先级
  - 除零抛 MiniPyError；链式比较；一元负号；-2**2 = -4
机制训练场：词法/AST/求值 机制供 C 线原生后端复用（语义不照抄——中文编译器走智能论语义）。
"""
import sys
import re
sys.stdout.reconfigure(encoding='utf-8')


class MiniPyError(Exception):
    """运行时错误（除零等）"""


# ============ 一、词法分析 ============
_TOKEN_RE = [
    ("STR", r"'[^']*'|\"[^\"]*\""),
    ("NUMBER", r"\d+\.\d+|\d+"),
    ("OP", r"\*\*|//|==|!=|<=|>=|\+=|-=|\*=|/=|[+\-*/%<>()=,\[\]{}:.]"),
    ("KEY", r"and|or|not|True|False|None|if|elif|else|while|def|return"),
    ("NAME", r"[A-Za-z_]\w*"),
    ("WS", r"\s+"),
]


def tokenize(src):
    """字符流 → token 列表（数字/运算符/关键字/括号）"""
    tokens, i = [], 0
    while i < len(src):
        for kind, pat in _TOKEN_RE:
            m = re.match(pat, src[i:])
            if m:
                text = m.group(0)
                i += len(text)
                if kind == "WS":
                    break
                if kind == "STR":
                    tokens.append(("STRING", text[1:-1]))
                elif kind == "KEY":
                    tokens.append((text.upper(), text))
                elif kind == "NUMBER":
                    tokens.append(("NUMBER", float(text) if "." in text else int(text)))
                elif kind == "NAME":
                    tokens.append(("NAME", text))
                else:
                    tokens.append(("OP", text))
                break
        else:
            raise SyntaxError(f"词法错误：未知字符 '{src[i]}'（位置 {i}）")
    tokens.append(("EOF", ""))
    return tokens


# ============ 二、语法分析（递归下降，Python 优先级） ============
class Parser:
    def __init__(self, tokens):
        """解析器初始化：持有词元流与位置指针。"""
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        """前瞻：返回当前 token 类型但不消费。"""
        return self.tokens[self.pos]

    def advance(self):
        """前进：消费并返回当前 token。"""
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def match(self, *texts):
        """尝试匹配：类型相符即消费返回 True，否则 False。"""
        t = self.peek()
        if t[1] in texts:
            return self.advance()
        return None

    def _maybe_index(self, node):
        """索引后缀：obj[key] → ("index", obj, key)（P5 数据结构）"""
        while self.peek()[1] == "[":
            self.advance()
            key = self.or_expr()
            self.expect("]")
            node = ("index", node, key)
        return node

    def _peek_eq(self):
        """后视：当前 NAME 后是否跟单个 =（kwarg 形态，区别于 ==）。"""
        nxt = self.tokens[self.pos + 1] if self.pos + 1 < len(self.tokens) else None
        return nxt is not None and nxt[0] == "OP" and nxt[1] == "="

    def _parse_call_args(self):
        """调用参数列表：位置参数 + 关键字参数 k=v（V-P4 kwargs 第一批）。"""
        args, kwargs = [], []
        if self.peek()[1] != ")":
            while True:
                t = self.peek()
                if t[0] == "NAME" and self._peek_eq():  # k=v
                    self.advance()
                    self.advance()
                    kwargs.append((t[1], self.or_expr()))
                else:
                    args.append(self.or_expr())
                if not self.match(","):
                    break
        self.expect(")")
        return args, kwargs

    def _parse_suffixes(self, node, name=None):
        """后缀链统一：.attr / [idx] / (args)（V-P3：NAME 与字符串字面量共用）。

        循环消化后缀使链式调用成立（s.strip().upper()）；调用结果再取下标
        （f(x)[0]）同样支持。obj.method(args) → ("method", obj, name, args)；
        name(args) → ("call", ...)。下标结果再调用（如 a[0](x)）显式不支持
        ——原实现会静默错当 a(x)。
        """
        while True:
            t1 = self.peek()[1]
            if t1 == ".":
                self.advance()
                attr = self.advance()
                if attr[0] != "NAME":
                    raise SyntaxError(f"语法错误：'.' 后应为属性名，得到 '{attr[1]}'")
                node = ("attr", node, attr[1])
            elif t1 == "[":
                self.advance()
                key = self.or_expr()
                self.expect("]")
                node = ("index", node, key)
            elif t1 == "(":
                self.advance()
                args, kwargs = self._parse_call_args()
                if node[0] == "attr":  # obj.method(args) → 方法调用节点
                    node = ("method", node[1], node[2], args, kwargs)
                elif name is not None and node[0] == "name" and node[1] == name:
                    node = ("call", name, args, kwargs)
                else:
                    raise SyntaxError("语法错误：该表达式不可调用（下标结果调用不支持）")
            else:
                break
        return node

    def expect(self, text):
        t = self.peek()
        if t[1] != text:
            raise SyntaxError(f"语法错误：期望 '{text}'，得到 '{t[1]}'")
        return self.advance()

    def parse(self):
        node = self.or_expr()
        if self.peek()[0] != "EOF":
            raise SyntaxError(f"语法错误：意外的 token '{self.peek()[1]}'")
        return node

    def or_expr(self):
        """or 链：短路求值（左真返左，否则续右）——对照 CPython 语义。"""
        node = self.and_expr()
        while self.match("or"):
            node = ("or", node, self.and_expr())
        return node

    def and_expr(self):
        """and 链：短路求值（左假返假，否则续右）。"""
        node = self.not_expr()
        while self.match("and"):
            node = ("and", node, self.not_expr())
        return node

    def not_expr(self):
        """not 一元表达式求值。"""
        if self.match("not"):
            return ("not", self.not_expr())
        return self.comparison()

    def comparison(self):
        """比较链：== != < <= > >= in / not in（V-P4）双目比较。"""
        node = self.arith()
        while True:
            t = self.peek()
            if t[1] in ("==", "!=", "<", ">", "<=", ">="):
                self.advance()
                node = (t[1], node, self.arith())
            elif t[1] == "in":  # V-P4：成员运算符（in 为 NAME token）
                self.advance()
                node = ("in", node, self.arith())
            elif t[1] == "not" and self._peek_is_in():  # not in（KEY token）
                self.advance()
                self.advance()  # 消费 in
                node = ("not in", node, self.arith())
            else:
                return node

    def _peek_is_in(self):
        """后视：not 后是否跟 in（not in 运算符，区别于逻辑 not 前缀）。"""
        nxt = self.tokens[self.pos + 1] if self.pos + 1 < len(self.tokens) else None
        return nxt is not None and nxt[1] == "in"

    def arith(self):
        """加减项：+ - 左结合。"""
        node = self.term()
        while True:
            t = self.peek()
            if t[1] in ("+", "-"):
                self.advance()
                node = (t[1], node, self.term())
            else:
                return node

    def term(self):
        """乘除项：* / // % 左结合。"""
        node = self.factor()
        while True:
            t = self.peek()
            if t[1] in ("*", "/", "//", "%"):
                self.advance()
                node = (t[1], node, self.factor())
            else:
                return node

    def factor(self):
        """一元因子：- 负号 / not 前缀。"""
        if self.peek()[1] in ("-", "+"):
            op = self.advance()[1]
            return (op, self.factor())  # 一元负号在外层：-2**2 = -(2**2)
        return self.power()

    def power(self):
        """幂运算：** 右结合。"""
        node = self.atom()
        if self.match("**"):
            return ("**", node, self.factor())  # 右结合
        return node

    def atom(self):
        """原子项：数字/字符串/名称/括号表达式/[列表]/字典字面量。"""
        t = self.peek()
        if t[0] == "NUMBER":
            self.advance()
            return ("num", t[1])
        if t[0] == "STRING":  # P5：字符串字面量（V-P3：后缀链与 NAME 统一）
            self.advance()
            return self._parse_suffixes(("str", t[1]))
        if t[0] == "NAME":  # 变量/函数调用/方法链（P3 + T4 后缀统一）
            self.advance()
            return self._parse_suffixes(("name", t[1]), name=t[1])
        if t[1] == "[":
            self.advance()
            items = []
            if self.peek()[1] != "]":
                items.append(self.or_expr())
                while self.match(","):
                    items.append(self.or_expr())
            self.expect("]")
            return self._maybe_index(("list", items))
        if t[1] == "{":
            self.advance()
            pairs = []
            if self.peek()[1] != "}":
                k = self.or_expr()
                self.expect(":")
                v = self.or_expr()
                pairs.append((k, v))
                while self.match(","):
                    k = self.or_expr()
                    self.expect(":")
                    v = self.or_expr()
                    pairs.append((k, v))
            self.expect("}")
            return self._maybe_index(("dict", pairs))
        if t[1] == "True":
            self.advance()
            return ("bool", True)
        if t[1] == "False":
            self.advance()
            return ("bool", False)
        if t[1] == "None":
            self.advance()
            return ("none", None)
        if t[1] == "(":
            self.advance()
            node = self.or_expr()
            self.expect(")")
            return node
        raise SyntaxError(f"语法错误：意外的 token '{t[1]}'")


# ============ 三、求值（对照 CPython 行为） ============
def is_truthy(v):
    """真值判定：对照 CPython 规则（None/False/0/空容器/空串为假）。"""
    if v is None or v is False:
        return False
    if isinstance(v, (int, float)) and v == 0:
        return False
    if isinstance(v, (str, list, tuple, dict)) and len(v) == 0:
        return False
    return True


def eval_node(node, env=None):
    """AST 求值（P2：env 提供变量环境；name 节点从环境取值）"""
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "str":
        return node[1]
    if kind == "bool":
        return node[1]
    if kind == "none":
        return None
    if kind == "name":
        if env is not None:
            try:
                return env.get(node[1])
            except MiniPyError:
                pass
        if node[1] in _BUILTINS:  # V-P4：内置函数可作值引用（sorted(x, key=len)）
            return _BUILTINS[node[1]]
        raise MiniPyError(f"NameError: name '{node[1]}' is not defined")
    if kind == "or":
        a = eval_node(node[1], env)
        return a if is_truthy(a) else eval_node(node[2], env)
    if kind == "and":
        a = eval_node(node[1], env)
        return eval_node(node[2], env) if is_truthy(a) else a
    if kind == "not":
        return not is_truthy(eval_node(node[1], env))
    if kind in ("==", "!=", "<", ">", "<=", ">=", "in", "not in"):
        return _compare(kind, eval_node(node[1], env), eval_node(node[2], env))
    if kind in ("-", "+") and len(node) == 2:  # 一元（先于二元判断）
        v = eval_node(node[1], env)
        return -v if kind == "-" else +v
    if kind == "+":
        return eval_node(node[1], env) + eval_node(node[2], env)
    if kind == "-":
        return eval_node(node[1], env) - eval_node(node[2], env)
    if kind == "*":
        return eval_node(node[1], env) * eval_node(node[2], env)
    if kind == "/":
        b = eval_node(node[2], env)
        if b == 0:
            raise MiniPyError("ZeroDivisionError: division by zero")
        return eval_node(node[1], env) / b
    if kind == "//":
        b = eval_node(node[2], env)
        if b == 0:
            raise MiniPyError("ZeroDivisionError: integer division by zero")
        a = eval_node(node[1], env)
        return int(a // b)  # floor（Python 语义）
    if kind == "%":
        b = eval_node(node[2], env)
        if b == 0:
            raise MiniPyError("ZeroDivisionError: modulo by zero")
        return eval_node(node[1], env) % b
    if kind == "**":
        return eval_node(node[1], env) ** eval_node(node[2], env)
    if kind == "attr":  # T4：属性/方法访问（白名单内才放行）
        obj = eval_node(node[1], env)
        if node[2] not in _METHOD_WHITELIST:
            raise MiniPyError(f"方法不在白名单: .{node[2]}（允许: {sorted(_METHOD_WHITELIST)}）")
        if not hasattr(obj, node[2]):
            raise MiniPyError(f"对象无该方法: {type(obj).__name__}.{node[2]}")
        return getattr(obj, node[2])
    if kind == "method":  # T4：obj.method(args) 调用（白名单校验）
        obj = eval_node(node[1], env)
        if node[2] not in _METHOD_WHITELIST:
            raise MiniPyError(f"方法不在白名单: .{node[2]}（允许: {sorted(_METHOD_WHITELIST)}）")
        m = getattr(obj, node[2], None)
        if not callable(m):
            raise MiniPyError(f"不可调用: {type(obj).__name__}.{node[2]}")
        args = [eval_node(a, env) for a in node[3]]
        kw = {k: eval_node(v, env) for k, v in node[4]} if len(node) > 4 else {}
        return m(*args, **kw)
    if kind == "call":  # 函数调用（P3：局部作用域 + 参数绑定 + return 捕获）
        try:
            f = env.get(node[1]) if env is not None else None
        except MiniPyError:
            f = None
        builtin = _BUILTINS.get(node[1])
        kw = {k: eval_node(v, env) for k, v in node[3]} if len(node) > 3 else {}
        if not (isinstance(f, tuple) and f[0] == "func"):
            if builtin is not None:
                args = [eval_node(a, env) for a in node[2]]
                return builtin(*args, **kw)
            raise MiniPyError(f"NameError: name '{node[1]}' is not defined")
        args = [eval_node(a, env) for a in node[2]]
        _, params, body, def_env = f
        local = bind_params(params, args, kw, def_env)  # V-P4：默认值+kwargs 绑定
        try:
            for s in body:
                exec_stmt(s, local)
        except ReturnSignal as rs:
            return rs.value
        return None
    if kind == "list":  # P5：list 字面量
        return [eval_node(e, env) for e in node[1]]
    if kind == "dict":  # P5：dict 字面量
        return {eval_node(k, env): eval_node(v, env) for k, v in node[1]}
    if kind == "index":  # P5：obj[key]
        obj = eval_node(node[1], env)
        key = eval_node(node[2], env)
        try:
            return obj[key]
        except (TypeError, IndexError, KeyError):
            raise MiniPyError(f"索引错误：{obj!r}[{key!r}]")
    raise MiniPyError(f"未知节点: {node}")


def _compare(op, a, b):
    """比较运算统一求值：==·!=·<·>·in·not in 分派（对照 CPython 类型提升）。"""
    if op == "in":  # V-P4：成员运算（str/list/tuple/dict 原生语义）
        return a in b
    if op == "not in":
        return a not in b
    return {"==": a == b, "!=": a != b, "<": a < b, ">": a > b,
            "<=": a <= b, ">=": a >= b}[op]


def eval_expr(src):
    """表达式求值入口：源码 → 值（P1）"""
    tokens = tokenize(src)
    ast = Parser(tokens).parse()
    return eval_node(ast)


# ============ P2：变量环境 + 控制流（赋值/if/while，缩进块） ============
# 语句树：("assign", name, expr) / ("if", cond, then[], else[]) /
#         ("while", cond, body[]) / ("expr", expr)
# 缩进块解析：行 → (缩进, 语句) → 嵌套树

# 内置函数表（P4 补全 2026-08-27）：对照 CPython 语义的最小白箱内置集
_BUILTINS = {
    "range": lambda *a: list(range(*[int(x) for x in a])),
    "len": len, "sum": sum, "abs": abs, "min": min, "max": max,
    "int": int, "float": float, "str": str, "list": list, "sorted": sorted,
    "print": print,
}

# 方法白名单（T4 起步 upper/split；V-P3 扩展 str 方法族 + V-P2 揭示 F4 需
# list.append / dict.get 容器方法原语——全部为 CPython 原生方法，getattr
# 分派直接对齐 CPython 语义。contains 不入列：str 无 .contains，应走 in
# 运算符（V-P4 挂账，涉及 for 头解析冲突需专项））
_METHOD_WHITELIST = {"upper", "split", "startswith", "endswith", "strip", "join",
                     "append", "get"}


class Env:
    """变量环境（P3：作用域链——局部 → 父环境）"""
    def __init__(self, parent=None):
        """作用域帧构造：本地变量表 + 父链指向外层（链式查找）。"""
        self.vars = {}
        self.parent = parent

    def get(self, name):
        """变量读取：沿父作用域链向上查找，未定义抛 NameError。"""
        if name in self.vars:
            return self.vars[name]
        if self.parent:
            return self.parent.get(name)
        raise MiniPyError(f"NameError: name '{name}' is not defined")

    def set(self, name, value):
        """变量赋值绑定到当前作用域。"""
        self.vars[name] = value


def bind_params(params, args, kw, def_env):
    """V-P4 第三批：参数绑定（位置→关键字→默认值），AST 与 VM 共用。

    params 元素 = (name, default_ast|None)；默认值在定义环境 def_env 求值。
    """
    from_dict = dict(kw or {})
    values = {}
    for i, (pname, dflt) in enumerate(params):
        if i < len(args):
            values[pname] = args[i]
        elif pname in from_dict:
            values[pname] = from_dict.pop(pname)
        elif dflt is not None:
            values[pname] = eval_node(dflt, def_env)
        else:
            raise MiniPyError(f"参数缺失: {pname}（无默认值且未传）")
    if from_dict:
        raise MiniPyError(f"未识别的关键字参数: {sorted(from_dict)}")
    local = Env(def_env)
    for k, v in values.items():
        local.set(k, v)
    return local


class ReturnSignal(Exception):
    """return 语句信号（P3）"""
    def __init__(self, value):
        """常量值包装（字面量求值结果载体）。"""
        self.value = value


# T4：复合赋值符（模块级预编译）
_AUG_RE = re.compile(r"(\w+)\s*(\+=|-=|\*=|/=)\s*(.+)$")
# T4：普通赋值行首形态（变量名 + 单个 =，排除 ==/<=/>=/!= 与字符串内等号）
_ASSIGN_RE = re.compile(r"([A-Za-z_]\w*)\s*=(?!=)")
# V-P2：下标赋值行首形态（obj[key] = value；[(.+)] 贪婪至最后一个 ]）
_SUBASSIGN_RE = re.compile(r"([A-Za-z_]\w*)\s*\[(.+)\]\s*=(?!=)\s*(.+)$")


def parse_program(src):
    """源码 → 语句树（缩进决定嵌套）"""
    lines = []
    for raw in src.splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append((indent, raw.strip()))
    # 缩进栈构建嵌套
    def build(idx, indent):
        stmts = []
        while idx[0] < len(lines):
            cur_indent, code = lines[idx[0]]
            if cur_indent < indent:
                break
            if cur_indent > indent:
                raise SyntaxError(f"意外的缩进：{code}")
            idx[0] += 1
            stmts.append(_parse_line(code, build, idx))
        return stmts

    def _parse_line(code, build, idx):
        # T4：复合赋值 += -= *= /=（先于 = 检测，避免 "x += 1" 被 split("=",1) 误拆）
        m_aug = _AUG_RE.match(code)
        if m_aug:
            return ("aug_assign", m_aug.group(1), m_aug.group(2),
                    Parser(tokenize(m_aug.group(3))).parse())
        # 赋值（T4 修正：行首 \w+= 形态判定——字符串内等号/"=="不再误判为赋值）
        m_assign = _ASSIGN_RE.match(code)
        if m_assign:
            return ("assign", m_assign.group(1),
                    Parser(tokenize(code[m_assign.end():])).parse())
        # 下标赋值 obj[key] = value（V-P2：F4 字典/列表写入原语；贪婪匹配
        # 最后一个 ] 使嵌套 key 如 a[b[1]] 正确拆分）
        m_sub = _SUBASSIGN_RE.match(code)
        if m_sub:
            return ("index_assign", m_sub.group(1),
                    Parser(tokenize(m_sub.group(2))).parse(),
                    Parser(tokenize(m_sub.group(3))).parse())
        # if/elif/else
        if code.startswith("def "):
            import re as _re
            m = _re.match(r"def\s+(\w+)\s*\(([^)]*)\)\s*:", code)
            name = m.group(1)
            # V-P4 第三批：参数支持默认值 name=expr → (name, default_ast|None)
            params = []
            for p_raw in m.group(2).split(","):
                p_raw = p_raw.strip()
                if not p_raw:
                    continue
                if "=" in p_raw:
                    pn, _, pv = p_raw.partition("=")
                    params.append((pn.strip(), Parser(tokenize(pv.strip())).parse()))
                else:
                    params.append((p_raw, None))
            body = build(idx, lines[idx[0]][0] if idx[0] < len(lines) else 0)
            return ("funcdef", name, params, body)
        if code.startswith("return "):
            return ("return", Parser(tokenize(code[7:])).parse())
        if code.startswith("if "):
            cond = Parser(tokenize(code[3:].rstrip(":"))).parse()
            then_indent = lines[idx[0]][0] if idx[0] < len(lines) else 0
            then = build(idx, then_indent)
            else_stmts = []
            # else 配对：同缩进 else 行 → else 块
            if idx[0] < len(lines) and lines[idx[0]][1].startswith("else"):
                idx[0] += 1  # 消费 else 行
                else_indent = lines[idx[0]][0] if idx[0] < len(lines) else 0
                else_stmts = build(idx, else_indent)
            return ("if", cond, then, else_stmts)
        # P4 补全（2026-08-27 · 荣「求和=1.0」缺陷根治）：for 语句
        if code.startswith("for "):
            import re as _re
            m = _re.match(r"for\s+(\w+)\s+in\s+(.+):$", code)
            if not m:
                raise SyntaxError("for 语句格式：for 变量 in 可迭代对象:")
            var = m.group(1)
            iterable = Parser(tokenize(m.group(2))).parse()
            body_indent = lines[idx[0]][0] if idx[0] < len(lines) else 0
            body = build(idx, body_indent)
            return ("for", var, iterable, body)
        if code.startswith("while "):
            cond = Parser(tokenize(code[6:].rstrip(":"))).parse()
            body = build(idx, lines[idx[0]][0] if idx[0] < len(lines) else 0)
            return ("while", cond, body)
        if code.startswith(("else", "elif ")):
            raise SyntaxError("else/elif 未与 if 配对（意外的 else 行）")
        # 表达式语句
        return ("expr", Parser(tokenize(code)).parse())

    idx = [0]
    return build(idx, 0)


def exec_stmt(stmt, env):
    """执行单条语句（if/while/funcdef 递归执行块）"""
    kind = stmt[0]
    if kind == "assign":
        env.set(stmt[1], eval_node(stmt[2], env))
    elif kind == "index_assign":  # V-P2：下标写入 obj[key] = value（list/dict 原生语义）
        obj = env.get(stmt[1])
        key = eval_node(stmt[2], env)
        try:
            obj[key] = eval_node(stmt[3], env)
        except IndexError:
            raise MiniPyError(f"索引赋值越界：{obj!r}[{key!r}]")
        except TypeError:
            raise MiniPyError(f"类型不支持下标赋值：{type(obj).__name__}[{key!r}]")
    elif kind == "aug_assign":  # T4：x op= e → x = x op e（/= 除零对齐 / 语义）
        cur = env.get(stmt[1])
        rhs = eval_node(stmt[3], env)
        op = stmt[2]
        if op == "+=":
            env.set(stmt[1], cur + rhs)
        elif op == "-=":
            env.set(stmt[1], cur - rhs)
        elif op == "*=":
            env.set(stmt[1], cur * rhs)
        else:
            if rhs == 0:
                raise MiniPyError("ZeroDivisionError: division by zero")
            env.set(stmt[1], cur / rhs)
    elif kind == "funcdef":
        # 函数对象 = 参数 + body + 定义环境（P4 闭包基础）
        env.set(stmt[1], ("func", stmt[2], stmt[3], env))
    elif kind == "return":
        raise ReturnSignal(eval_node(stmt[1], env))
    elif kind == "if":
        if is_truthy(eval_node(stmt[1], env)):
            for s in stmt[2]:
                exec_stmt(s, env)
        elif stmt[3]:
            for s in stmt[3]:
                exec_stmt(s, env)
    elif kind == "while":
        guard = 0
        while is_truthy(eval_node(stmt[1], env)) and guard < 10000:
            for s in stmt[2]:
                exec_stmt(s, env)
            guard += 1
    elif kind == "for":
        _, var, iter_node, body = stmt
        iterable = eval_node(iter_node, env)
        if isinstance(iterable, (list, tuple)):
            items = list(iterable)
        elif isinstance(iterable, str):
            items = list(iterable)
        elif hasattr(iterable, "__iter__"):
            items = list(iterable)
        else:
            raise MiniPyError(f"for 迭代对象不可迭代: {type(iterable).__name__}")
        for item in items[:10000]:          # 步数上限对齐 while guard 纪律
            env.set(var, item)
            for s in body:
                exec_stmt(s, env)
    elif kind == "expr":
        eval_node(stmt[1], env)
    else:
        raise MiniPyError(f"未知语句: {stmt}")


def run_program(src):
    """程序执行：源码 → Env（P2：变量/if/while）"""
    env = Env()
    for stmt in parse_program(src):
        exec_stmt(stmt, env)
    return env


# ============ P5：字节码 VM 雏形（栈机——机制供 C 线原生后端复用） ============
# 表达式 → 字节码指令 → 栈机执行（对照 eval_node 结果）
# 指令：PUSH_CONST/PUSH_LIST/PUSH_DICT/LOAD_NAME/ADD/SUB/MUL/DIV/FLOOR/MOD/POW/
#       NEG/AND_OR/CMP_*/JUMP_IF_FALSE/JUMP（逻辑短路用跳转）

def compile_expr(node):
    """AST 表达式 → 字节码指令列表（栈机）"""
    kind = node[0]
    if kind == "num":
        return [("PUSH_CONST", node[1])]
    if kind == "str":
        return [("PUSH_CONST", node[1])]
    if kind == "bool":
        return [("PUSH_CONST", node[1])]
    if kind == "none":
        return [("PUSH_CONST", None)]
    if kind == "name":
        return [("LOAD_NAME", node[1])]
    if kind == "list":
        code = []
        for e in node[1]:
            code.extend(compile_expr(e))
        code.append(("PUSH_LIST", len(node[1])))
        return code
    if kind == "dict":
        code = []
        for k, v in node[1]:
            code.extend(compile_expr(k))
            code.extend(compile_expr(v))
        code.append(("PUSH_DICT", len(node[1])))
        return code
    if kind == "index":
        code = compile_expr(node[1]) + compile_expr(node[2])
        code.append(("INDEX", None))
        return code
    if kind in ("-", "+") and len(node) == 2:  # 一元
        code = compile_expr(node[1])
        if kind == "-":
            code.append(("NEG", None))
        return code
    if kind in ("+", "-", "*", "/", "//", "%", "**"):
        code = compile_expr(node[1]) + compile_expr(node[2])
        code.append((_ARITH_VM[kind], None))
        return code
    if kind in ("==", "!=", "<", ">", "<=", ">=", "in", "not in"):
        code = compile_expr(node[1]) + compile_expr(node[2])
        code.append((_CMP_VM[kind], None))
        return code
    if kind == "not":
        return compile_expr(node[1]) + [("NOT", None)]
    if kind == "or" or kind == "and":
        # 短路：左值 → 真保留左值（or）/假保留左值（and）→ 否则求右值
        right = compile_expr(node[2])
        code = compile_expr(node[1])
        jmp = "JUMP_IF_TRUE" if kind == "or" else "JUMP_IF_FALSE"
        jmp_idx = len(code)
        code.append((jmp, 0))       # 回填
        code.append(("POP", None))  # 丢弃左值（不短路时）
        code.extend(right)
        code[jmp_idx] = (jmp, len(code))  # 短路目标 = 程序末尾（栈顶左值保留）
        return code
    if kind == "attr":  # T4：VM 同步支持（双路对照）
        return compile_expr(node[1]) + [("GET_ATTR", node[2])]
    if kind == "method":  # T4：obj + args → CALL_METHOD(方法名, 参数数)
        code = compile_expr(node[1])
        for a in node[3]:
            code.extend(compile_expr(a))
        code.append(("CALL_METHOD", (node[2], len(node[3]))))
        return code
    if kind == "call":
        code = [("LOAD_NAME", node[1])]
        for a in node[2]:
            code.extend(compile_expr(a))
        if len(node) > 3 and node[3]:  # V-P4：kwargs 压 key,值 序列 + CALL_KW
            for k, v in node[3]:
                code.append(("PUSH_CONST", k))
                code.extend(compile_expr(v))
            code.append(("CALL_KW", (len(node[2]), len(node[3]))))
        else:
            code.append(("CALL", len(node[2])))
        return code
    if kind == "method":
        if len(node) > 4 and node[4]:
            raise MiniPyError("VM 暂不支持方法关键字参数（V-P4 第二批）")
    raise MiniPyError(f"无法编译节点: {node}")


_ARITH_VM = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV",
             "//": "FLOOR", "%": "MOD", "**": "POW"}
_CMP_VM = {"==": "CMP_EQ", "!=": "CMP_NE", "<": "CMP_LT", ">": "CMP_GT",
           "<=": "CMP_LE", ">=": "CMP_GE",
           "in": "CMP_IN", "not in": "CMP_NOT_IN"}  # V-P4


class VM:
    """栈机执行（P5 雏形：算术/比较/逻辑短路/数据结构/调用）"""
    def __init__(self, env):
        """VM 执行上下文：环境引用·操作数栈·调用帧序列。"""
        self.env = env
        self.stack = []
        self.frames = []  # 调用帧（P5 简化：函数调用直接执行 body）

    def run(self, code, max_steps=100000):
        """字节码 VM 执行主循环：取指分派，max_steps 上限防死循环。"""
        ip = 0
        while ip < len(code) and max_steps > 0:
            op, arg = code[ip]
            ip += 1
            max_steps -= 1
            if op == "PUSH_CONST":
                self.stack.append(arg)
            elif op == "LOAD_NAME":
                try:
                    self.stack.append(self.env.get(arg))
                except MiniPyError:
                    if arg in _BUILTINS:  # V-P2：VM 路内置函数兜底（与 AST 路对齐）
                        self.stack.append(_BUILTINS[arg])
                    else:
                        raise
            elif op == "PUSH_LIST":
                items = self.stack[-arg:]
                self.stack = self.stack[:-arg]
                self.stack.append(items)
            elif op == "PUSH_DICT":
                pairs = self.stack[-arg * 2:]
                self.stack = self.stack[:-arg * 2]
                self.stack.append({pairs[i]: pairs[i + 1] for i in range(0, len(pairs), 2)})
            elif op == "INDEX":
                key, obj = self.stack.pop(), self.stack.pop()
                self.stack.append(obj[key])
            elif op == "ADD":
                b, a = self.stack.pop(), self.stack.pop()
                self.stack.append(a + b)
            elif op == "SUB":
                b, a = self.stack.pop(), self.stack.pop()
                self.stack.append(a - b)
            elif op == "MUL":
                b, a = self.stack.pop(), self.stack.pop()
                self.stack.append(a * b)
            elif op == "DIV":
                b, a = self.stack.pop(), self.stack.pop()
                if b == 0:
                    raise MiniPyError("ZeroDivisionError")
                self.stack.append(a / b)
            elif op == "FLOOR":
                b, a = self.stack.pop(), self.stack.pop()
                if b == 0:
                    raise MiniPyError("ZeroDivisionError")
                self.stack.append(int(a // b))
            elif op == "MOD":
                b, a = self.stack.pop(), self.stack.pop()
                if b == 0:
                    raise MiniPyError("ZeroDivisionError")
                self.stack.append(a % b)
            elif op == "POW":
                b, a = self.stack.pop(), self.stack.pop()
                self.stack.append(a ** b)
            elif op == "NOT":
                self.stack.append(not is_truthy(self.stack.pop()))
            elif op == "NEG":
                self.stack.append(-self.stack.pop())
            elif op.startswith("CMP_"):
                b, a = self.stack.pop(), self.stack.pop()
                _cmp_map = {"EQ": "==", "NE": "!=", "LT": "<", "GT": ">",
                            "LE": "<=", "GE": ">=", "IN": "in", "NOT_IN": "not in"}
                self.stack.append(_compare(_cmp_map[op[4:]], a, b))
            elif op == "JUMP_IF_TRUE":
                if is_truthy(self.stack[-1]):
                    ip = arg
            elif op == "JUMP_IF_FALSE":
                if not is_truthy(self.stack[-1]):
                    ip = arg
            elif op == "POP":
                self.stack.pop()
            elif op == "CALL":
                args = self.stack[-arg:]
                self.stack = self.stack[:-arg]
                f = self.stack.pop()  # 函数在参数之下（先压函数后压参数）
                if isinstance(f, tuple) and f and f[0] == "func":
                    _, params, body, def_env = f
                    local = bind_params(params, args, None, def_env)  # V-P4
                    try:
                        for s in body:
                            exec_stmt(s, local)
                        self.stack.append(None)
                    except ReturnSignal as rs:
                        self.stack.append(rs.value)
                elif callable(f):  # V-P2：内置函数（与 AST 路 _BUILTINS 分派对齐）
                    self.stack.append(f(*args))
                else:
                    raise MiniPyError(f"不可调用: {f!r}")
            elif op == "CALL_KW":  # V-P4：带关键字参数调用（栈序 f, pos..., k1,v1,...）
                n_pos, n_kw = arg
                kw_items = self.stack[len(self.stack) - 2 * n_kw:]
                self.stack = self.stack[:-2 * n_kw]
                kwargs = {kw_items[2 * i]: kw_items[2 * i + 1] for i in range(n_kw)}
                args = self.stack[-n_pos:] if n_pos else []
                if n_pos:
                    self.stack = self.stack[:-n_pos]
                f = self.stack.pop()
                if isinstance(f, tuple) and f and f[0] == "func":
                    _, params, body, def_env = f
                    local = bind_params(params, args, kwargs, def_env)  # V-P4
                    try:
                        for s in body:
                            exec_stmt(s, local)
                        self.stack.append(None)
                    except ReturnSignal as rs:
                        self.stack.append(rs.value)
                    continue
                if callable(f):
                    self.stack.append(f(*args, **kwargs))
                else:
                    raise MiniPyError(f"不可调用: {f!r}")
            elif op == "GET_ATTR":  # T4
                obj = self.stack.pop()
                if arg not in _METHOD_WHITELIST:
                    raise MiniPyError(f"方法不在白名单: .{arg}（允许: {sorted(_METHOD_WHITELIST)}）")
                if not hasattr(obj, arg):
                    raise MiniPyError(f"对象无该方法: {type(obj).__name__}.{arg}")
                self.stack.append(getattr(obj, arg))
            elif op == "CALL_METHOD":  # T4：arg=(方法名, 参数数)
                mname, n = arg
                args = self.stack[len(self.stack) - n:] if n else []
                if n:
                    self.stack = self.stack[:-n]
                obj = self.stack.pop()
                if mname not in _METHOD_WHITELIST:
                    raise MiniPyError(f"方法不在白名单: .{mname}（允许: {sorted(_METHOD_WHITELIST)}）")
                m = getattr(obj, mname, None)
                if not callable(m):
                    raise MiniPyError(f"不可调用: {type(obj).__name__}.{mname}")
                self.stack.append(m(*args))
            else:
                raise MiniPyError(f"未知指令: {op}")
        return self.stack[-1] if self.stack else None


def eval_expr_vm(src, env=None):
    """字节码 VM 求值入口（P5：对照 eval_expr/eval_node）"""
    env = env or Env()
    ast = Parser(tokenize(src)).parse()
    code = compile_expr(ast)
    return VM(env).run(code)


if __name__ == "__main__":
    print("=== Mini-Python P2：变量环境 + 控制流（对照 CPython）===\n")
    prog = """
x = 0
while x < 5:
    x = x + 1
if x == 5:
    y = 10
else:
    y = 0
"""
    env = run_program(prog)
    print(f"① 程序执行后: x={env.get('x')} y={env.get('y')}")
    ok = env.get("x") == 5 and env.get("y") == 10
    print(f"\n=== 判定 ===\n变量+控制流: {'✔ 循环/条件/赋值成立（对照 CPython）' if ok else '✘'}")


if __name__ == "__main__":
    print("=== Mini-Python P1：表达式求值（对照 CPython）===\n")
    cases = [
        ("2+3*4", 14), ("2**3**2", 512), ("-2**2", -4), ("4/2", 2.0),
        ("10//3", 3), ("-7//2", -4), ("-7%2", 1), ("3>2", True),
        ("not 1>2", True), ("0 or 5", 5), ("2 and 3", 3),
        ("True or 1/0", True), ("0 and 1/0", 0), ("2**-1", 0.5),
        ("1<2<3", True), ("(2+3)*4", 20), ("-5+3", -2),
    ]
    ok_n = 0
    for src, expect in cases:
        try:
            got = eval_expr(src)
            ok = got == expect and type(got) is type(expect)
            if ok:
                ok_n += 1
            print(f"[{'✔' if ok else '✘'}] {src} = {got!r} (期望 {expect!r})")
        except Exception as e:
            print(f"[✘] {src} → 异常 {e}")
    print(f"\n=== 判定 ===\n表达式求值: {ok_n}/{len(cases)}（对照 CPython 行为）")
