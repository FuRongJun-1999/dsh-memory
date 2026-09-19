"""
compiler.py · 中文源码 → 智能论字节码（第六阶段 C2）
AST（protocol-compiler parser）→ VM 指令（condition_vm）：
  若…则…否则 → JUMP_IF_FALSE + JUMP（条件跳转）
  道德经指令（道/德/自然/无为/止/知足）→ DAO/DE/ZIRAN/WUWEI/ZHI/ZHIZU
  术曰块 → ENTER_SHUYUE/RETURN_STEP（作用域）
  赋值 → STORE_NAME；比较/算术 → CMP_*/ADD/SUB/MUL/DIV
名实校验（NameChecker）为编译期静态检查（以名举实）——C2 智能论语义。
对照 v0.2 codegen 语义：DAO=create_path(条件空间)、DE=accumulate_trust(信任累积)、
若则=if——VM 执行结果与声明语义一致。
"""

from .lexer import tokenize, TokenType
from .parser import parse_tokens, NodeType
from .name_checker import NameChecker
from .condition_vm import Opcode


# 中文比较词 → VM 比较指令（codegen CHINESE_COMP_MAP 同构）
COMP_MAP = {
    "==": Opcode.CMP_EQ, "等于": Opcode.CMP_EQ,
    ">": Opcode.CMP_GT, "大于": Opcode.CMP_GT,
    "<": Opcode.CMP_LT, "小于": Opcode.CMP_LT,
    "!=": Opcode.CMP_NE, "不等于": Opcode.CMP_NE,
    "<=": Opcode.CMP_LE, "不大于": Opcode.CMP_LE,
    ">=": Opcode.CMP_GE, "不小于": Opcode.CMP_GE,
}

# 算术运算符 → VM 指令（含中文算术词）
ARITH_MAP = {"+": Opcode.ADD, "-": Opcode.SUB,
             "*": Opcode.MUL, "/": Opcode.DIV,
             "加": Opcode.ADD, "减": Opcode.SUB,
             "乘": Opcode.MUL, "除": Opcode.DIV}


class Compiler:
    """AST → 字节码（标签回填）"""

    def __init__(self):
        self.code = []
        self.labels = {}
        self.pending = []      # [(index, label)]
        self.zhizu_labels = [] # 知足标签（达标跳程序末尾）
        self.label_count = 0
        self.warnings = []
        self.funcs = {}        # 函数名 → (入口ip, 参数名列表)

# 生效条件：传入 ast（带 statements 可迭代）即生效，先按 NodeType.FUNC_DEF 收集 funcs 并 emit 跳过 JUMP、后置编译函数体，再对非 FUNC_DEF 语句编译主体、把跳过标签指向主体开始、把 zhizu_labels 置于末尾并 _resolve 后返回 self.code；不含 FUNC_DEF 时主体直接编译并同样返回 self.code。
    def compile(self, ast):
        # 第一遍：收集函数定义（入口标签 + 参数）
        for stmt in ast.statements:
            if stmt.type == NodeType.FUNC_DEF:
                self.funcs[stmt.name] = (self._new_label(), stmt.params)
        # 第二遍：函数定义处 emit 跳过 JUMP（目标=主体开始，后置回填）
        skip_lbls = []
        for stmt in ast.statements:
            if stmt.type == NodeType.FUNC_DEF:
                lbl = self._new_label()
                self._emit(Opcode.JUMP, lbl)
                self.pending.append((len(self.code) - 1, lbl))
                skip_lbls.append(lbl)
        # 第三遍：所有函数体后置编译（入口标签 + body + RETURN）
        for stmt in ast.statements:
            if stmt.type == NodeType.FUNC_DEF:
                self._compile_func(stmt)
        # 第四遍：主体编译（跳过 JUMP 的目标 = 主体开始）
        main_start = len(self.code)
        for stmt in ast.statements:
            if stmt.type != NodeType.FUNC_DEF:
                self._stmt(stmt)
        # 跳过标签 → 主体开始（函数体已全部前置）
        for lbl in skip_lbls:
            self.labels[lbl] = main_start
        # 知足标签 place 到程序末尾（信任达标=满足结束，对齐白箱单元语义）
        for lbl in self.zhizu_labels:
            self._place(lbl)
        self._resolve()
        return self.code

# 生效条件：当 self.funcs 中存在 stmt.name 时（不存在则 KeyError），place 其入口标签、编译 stmt.body 并 emit RETURN。
    def _compile_func(self, stmt):
        """编译函数定义：入口标签 → body 编译 → RETURN"""
        entry_lbl, params = self.funcs[stmt.name]
        self._place(entry_lbl)
        self._stmt(stmt.body)
        self._emit(Opcode.RETURN)

    # ---- 标签 ----
    def _new_label(self):
        self.label_count += 1
        return f"L{self.label_count}"

# 生效条件：把 label 作为键写入 self.labels[label] = len(self.code)（当前无写入位置的约束）。
    def _place(self, label):
        self.labels[label] = len(self.code)

# 生效条件：每次调用向 self.code 追加二元组 (op, arg)；arg 省略或显式传 None 时第二项即为 None。
    def _emit(self, op, arg=None):
        self.code.append((op, arg))

# 生效条件：遍历 self.pending，label 不在 self.labels 时抛 SyntaxError('未定义标签')；命中 ZHIZU 的槽位回填 (arg[0], labels[label])、命中 CALL 的回填 (labels[label], arg[1])、其余回填 labels[label]。
    def _resolve(self):
        for idx, label in self.pending:
            if label not in self.labels:
                raise SyntaxError(f"未定义标签 {label}")
            op, arg = self.code[idx]
            if op == Opcode.ZHIZU:
                self.code[idx] = (op, (arg[0], self.labels[label]))
            elif op == Opcode.CALL:
                # CALL (entry_lbl, param_names) → 回填入口地址
                self.code[idx] = (op, (self.labels[label], arg[1]))
            else:
                self.code[idx] = (op, self.labels[label])

    # ---- 语句 ----
# 生效条件：s 为 None 时直接返回；否则按 s.type 分派——BLOCK 递归各语句、SHUYUE 发 ENTER_SHUYUE+各步骤+RETURN_STEP、CONDITION_STMT 编译 condition 与 then_body/else_body 并回填 else/end 标签、LOOP_STMT 编译当型循环、INSTRUCTION_STMT 转 _instr、ASSIGN_STMT 求值后发 STORE_NAME、RETURN_STMT 有 value 则求值否则发 PUSH_CONST None 再发 RETURN、CALL_EXPR 转 _call_expr、WENYUE/DAYUE 跳过，其余类型向 warnings 追加未编译语句提示。
    def _stmt(self, s):
        if s is None:
            return
        if s.type == NodeType.BLOCK:
            for st in s.statements:
                self._stmt(st)
        elif s.type == NodeType.SHUYUE:
            self._emit(Opcode.ENTER_SHUYUE)
            for step in s.steps:
                self._stmt(step.statement)
            self._emit(Opcode.RETURN_STEP)
        elif s.type == NodeType.CONDITION_STMT:
            self._expr(s.condition)
            else_lbl = self._new_label()
            end_lbl = self._new_label()
            self._emit(Opcode.JUMP_IF_FALSE, else_lbl)
            self.pending.append((len(self.code) - 1, else_lbl))
            self._stmt(s.then_body)
            self._emit(Opcode.JUMP, end_lbl)
            self.pending.append((len(self.code) - 1, end_lbl))
            self._place(else_lbl)
            self._stmt(s.else_body)
            self._place(end_lbl)
        elif s.type == NodeType.LOOP_STMT:
            # 当…执行（while 语义）：条件 → JIF 跳出 → 体 → JUMP 回条件
            start_lbl = self._new_label()
            exit_lbl = self._new_label()
            self._place(start_lbl)
            self._expr(s.condition)
            self._emit(Opcode.JUMP_IF_FALSE, exit_lbl)
            self.pending.append((len(self.code) - 1, exit_lbl))
            self._stmt(s.body)
            self._emit(Opcode.JUMP, start_lbl)
            self.pending.append((len(self.code) - 1, start_lbl))
            self._place(exit_lbl)
        elif s.type == NodeType.INSTRUCTION_STMT:
            self._instr(s)
        elif s.type == NodeType.ASSIGN_STMT:
            self._expr(s.value_node)
            self._emit(Opcode.STORE_NAME, s.target)
        elif s.type == NodeType.RETURN_STMT:
            if s.value is not None:
                self._expr(s.value)
            else:
                self._emit(Opcode.PUSH_CONST, None)
            self._emit(Opcode.RETURN)
        elif s.type == NodeType.CALL_EXPR:
            # 函数调用作为语句：编译调用（结果留在栈上，丢弃）
            self._call_expr(s)
        elif s.type in (NodeType.WENYUE, NodeType.DAYUE):
            pass  # 注释性结构（问曰/答曰）
        else:
            self.warnings.append(f"L{s.line} 未编译语句类型: {s.type.name}")

    # ---- 道德经指令 ----
# 生效条件：按 s.instruction 分派——DAO 发 (DAO, val)，val 为 None（operands 为空或 _operand_value 返回 None）时用 '无名路径'；DE 发 float(val)，val 为 None 时 0.0、非数值时抛 SyntaxError 名实不符；ZIRAN/WUWEI/ZHI 各发对应无参指令；ZHIZU 以 float(val)（None 时 0.0）为阈值新建标签并挂 pending 与 zhizu_labels；其余指令向 warnings 追加未接入提示。
    def _instr(self, s):
        op = s.instruction
        operands = s.operands
        val = self._operand_value(operands[0]) if operands else None
        if op == TokenType.DAO:
            self._emit(Opcode.DAO, val if val is not None else "无名路径")
        elif op == TokenType.DE:
            try:
                self._emit(Opcode.DE, float(val) if val is not None else 0.0)
            except (TypeError, ValueError):
                # 以名举实：非数值操作数（未声明标识符）编译期拦截——名实不符
                raise SyntaxError(
                    f"L{s.line} 德 的操作数必须是数值，得到 '{val}'（名实不符）")
        elif op == TokenType.ZIRAN:
            self._emit(Opcode.ZIRAN)
        elif op == TokenType.WUWEI:
            self._emit(Opcode.WUWEI)
        elif op == TokenType.ZHI:
            self._emit(Opcode.ZHI)
        elif op == TokenType.ZHIZU:
            threshold = float(val) if val is not None else 0.0
            lbl = self._new_label()
            self._emit(Opcode.ZHIZU, (threshold, lbl))
            self.pending.append((len(self.code) - 1, lbl))
            self.zhizu_labels.append(lbl)  # 达标跳程序末尾（满足）
        else:
            self.warnings.append(f"L{s.line} 指令 {op.name} 未接入 VM（诚实边界）")

# 生效条件：node.type 为 LITERAL 时返回 node.literal_value、为 IDENTIFIER 时返回 node.name，其余类型返回 None。
    def _operand_value(self, node):
        if node.type == NodeType.LITERAL:
            return node.literal_value
        if node.type == NodeType.IDENTIFIER:
            return node.name
        return None

    # ---- 表达式 ----
# 生效条件：e 为 None 时发 PUSH_CONST None 后返回；否则按 e.type 分派——LITERAL 发 PUSH_CONST literal_value、IDENTIFIER 发 LOAD_NAME name、COMPARISON 先编译 left/right 再发 COMP_MAP[e.op]（映射缺失时记未知比较词并返回）、BINARY_EXPR 同序走 ARITH_MAP[e.operator]（缺失时记未知运算符并返回）、CALL_EXPR 转 _call_expr，其余类型向 warnings 追加未编译表达式。
    def _expr(self, e):
        if e is None:
            self._emit(Opcode.PUSH_CONST, None)
            return
        if e.type == NodeType.LITERAL:
            self._emit(Opcode.PUSH_CONST, e.literal_value)
        elif e.type == NodeType.IDENTIFIER:
            self._emit(Opcode.LOAD_NAME, e.name)
        elif e.type == NodeType.COMPARISON:
            self._expr(e.left)
            self._expr(e.right)
            op = COMP_MAP.get(e.op)
            if op is None:
                self.warnings.append(f"L{e.line} 未知比较词 '{e.op}'")
                return
            self._emit(op)
        elif e.type == NodeType.BINARY_EXPR:
            self._expr(e.left)
            self._expr(e.right)
            op = ARITH_MAP.get(e.operator)
            if op is None:
                self.warnings.append(f"L{e.line} 未知运算符 '{e.operator}'")
                return
            self._emit(op)
        elif e.type == NodeType.CALL_EXPR:
            self._call_expr(e)
        else:
            self.warnings.append(f"L{e.line} 未编译表达式: {e.type.name}")

# 生效条件：先对 e.args 逐个求值入栈；若 e.name 不在 self.funcs 则向 warnings 追加未定义函数并返回（不发 CALL），否则发 CALL (entry_lbl, params) 并挂 pending。
    def _call_expr(self, e):
        """函数调用编译：实参求值入栈 → CALL (入口, 参数名)"""
        for a in e.args:
            self._expr(a)
        if e.name not in self.funcs:
            self.warnings.append(f"L{e.line} 未定义函数 '{e.name}'（调用悬空）")
            return
        entry_lbl, params = self.funcs[e.name]
        self._emit(Opcode.CALL, (entry_lbl, params))
        self.pending.append((len(self.code) - 1, entry_lbl))


# 生效条件：传入 source（可配默认 strict=True）后先 tokenize/parse，errors 非空即返回 (None,{ok:False,errors,warnings:[]})；否则执行 NameChecker.check，仅当 strict 为真且 name_errors 非空时返回 (None,{ok:False,errors:name_errors,warnings:name_warnings,name_errors:name_errors})，strict 为假值时不因此提前返回而继续编译；compiler.compile 抛 SyntaxError 时返回 (None,{ok:False,errors:[str(e)],warnings:[],name_errors:[str(e)]})，否则返回 (code,{ok:True,errors:[],warnings:compiler.warnings})。
def compile_source(source, strict=True):
    """中文源码 → 字节码（含名实校验静态检查）
    返回 (code, result)：result = {ok, errors, warnings, name_errors}"""
    tokens, lex_errors = tokenize(source)
    errors = list(lex_errors or [])
    ast = parse_tokens(tokens, errors)
    if errors:
        return None, {"ok": False, "errors": errors, "warnings": []}
    # 名实校验（以名举实·静态检查——C2 智能论语义）
    checker = NameChecker()
    name_errors, name_warnings = checker.check(ast)
    if strict and name_errors:
        return None, {"ok": False, "errors": name_errors,
                      "warnings": name_warnings, "name_errors": name_errors}
    compiler = Compiler()
    try:
        code = compiler.compile(ast)
    except SyntaxError as e:
        return None, {"ok": False, "errors": [str(e)],
                      "warnings": [], "name_errors": [str(e)]}
    return code, {"ok": True, "errors": [], "warnings": compiler.warnings}


if __name__ == "__main__":
    print("=== C2：中文源码 → 智能论字节码（对照 v0.2 语义）===\n")
    src = """
问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：
1。道 新信任路径；
2。若 信任值 大于 0.3，则 德 0.5；
3。知足 0.7；
4。止。
"""
    code, result = compile_source(src)
    if not result["ok"]:
        print("编译错误:", result["errors"][:3])
    else:
        print("① 字节码（" + str(len(code)) + " 条指令）：")
        for i, (op, arg) in enumerate(code):
            print(f"   {i:3d} {op.name:14s} {arg}")
        from .condition_vm import ConditionVM
        vm = ConditionVM()
        # 播种初始信任 0.4 —— 使「信任值 大于 0.3」成立以驱动条件分支。
        # （缺陷②修复后 信任值 读的就是 trust_value 寄存器，名实一处存储；
        #   修复前示例在此处直接 NameError："名实不符：'信任值' 未声明"）
        state = vm.run(code, trust=0.4)
        print(f"\n② VM 执行: 信任={state['trust']} 条件空间={state['condition_space']} "
              f"停止={state['halt']}")
        # 0.4 > 0.3 → 德 0.5 → 信任 0.9；知足 0.7 达标 → 向前跳到程序末尾，
        # 故其后的 止 被跳过（halt=None）——这是知足 的早退语义（缺陷④）。
        ok = (state["trust"] >= 0.7 and state["condition_space"]
              and state["halt"] is None)
        print(f"\n=== 判定 ===\n中文源码原生执行: "
              f"{'✔ 若则/道德经指令/术曰 在 VM 上运行（零 Python 运行时；知足达标早退）' if ok else '✘'}")