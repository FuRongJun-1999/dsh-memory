"""
condition_vm.py · 智能论字节码 VM（第六阶段 C1 · 原生编译地基）
道德经助记符 → 指令；条件空间/信任 为 VM 内建状态（非外部运行时调用）。
  道(DAO)=创建协议路径(条件空间栈压入)  德(DE)=信任累积  知足(ZHIZU)=信任达标跳转
  自然(ZIRAN)=恢复默认条件空间  无为(WUWEI)=让出控制  止(ZHI)=停止
  若…则…否则 = JUMP_IF_FALSE（条件跳转）
零 Python 依赖运行时（VM 自足）——「完全使用智能论的分析方法和逻辑」的 VM 层。
"""

from enum import IntEnum


class Opcode(IntEnum):
    """智能论 VM 指令操作码枚举：PUSH_CONST·LOAD_NAME·STORE_NAME 等协议助记指令。"""
    PUSH_CONST = 0      # 压字面量
    LOAD_NAME = 1       # 符号表取值（以名举实·读）
    STORE_NAME = 2      # 符号表存值（以名举实·写）
    JUMP = 3            # 无条件跳转
    JUMP_IF_FALSE = 4   # 栈顶假则跳（若…则…否则）
    DAO = 5             # 道：创建协议路径（条件空间栈压入）
    DE = 6              # 德：信任值累积
    ZIRAN = 7           # 自然：恢复默认条件空间（弹栈到根）
    WUWEI = 8           # 无为：让出控制（yield）
    ZHI = 9             # 止：停止执行（halt）
    ZHIZU = 10          # 知足：信任≥阈值跳转
    CMP_EQ = 11         # 等于
    CMP_GT = 12         # 大于
    CMP_LT = 13         # 小于
    ENTER_SHUYUE = 14   # 进入术曰块（作用域）
    RETURN_STEP = 15    # 步骤返回（出作用域）
    ADD = 16            # 加
    SUB = 17            # 减
    MUL = 18            # 乘
    DIV = 19            # 除
    CMP_NE = 20         # 不等于
    CMP_LE = 21         # 不大于（≤）
    CMP_GE = 22         # 不小于（≥）
    CALL = 23           # 调用函数（定义 名（参数）：语句；调用栈帧）
    RETURN = 24         # 返回调用者（恢复符号表与返回地址）

    @classmethod
    def names(cls):
        """枚举名→值映射表。"""
        return {m.name: m.value for m in cls}


class VMHalt(Exception):
    """止：正常停止（含 yield 让出——kind 区分）"""
    def __init__(self, kind="halt", state=None):
        """停机帧构造：默认 halt，可携带终止状态快照。"""
        self.kind = kind
        self.state = state or {}
        super().__init__(f"VM {kind}")


class ConditionVM:
    """智能论字节码 VM：ip + 值栈 + 符号表 + 条件空间栈 + 信任值寄存器"""

    def __init__(self):
        """VM 实例构造：状态立即复位至初始可执行态。"""
        self.reset()

    def reset(self, symbols=None, trust=0.0, condition_stack=None):
        """重置执行状态：指令指针/栈/符号表/条件栈归零重来。"""
        self.ip = 0
        self.stack = []
        self.symbols = dict(symbols or {})   # 名实对应（以名举实）
        self.condition_stack = list(condition_stack or [])  # 条件空间栈
        self.trust_value = trust             # 信任值寄存器
        self.scope_depth = 0                 # 术曰作用域深度
        self.trace = []                      # 执行轨迹（可解释性）
        self.call_stack = []                 # 调用栈帧 [(返回ip, 保存的符号表)]

    def run(self, code, trace=False, catch_halt=True, symbols=None,
            trust=0.0, condition_stack=None, max_steps=100000):
        """执行字节码；code = [(op, arg), ...]
        symbols/trust/condition_stack：初始执行环境（C2 语义：符号表/信任/条件空间）
        catch_halt=True：止(ZHI)/无为(WUWEI) 作为正常控制流信号捕获，
        返回 {"halt": kind, ...}（VM 自足——停止/让出是语言语义非错误）
        max_steps：步数上限防死循环（对齐白箱 VM-循环执行单元：超出报 error）"""
        self.reset(symbols, trust, condition_stack)
        halt = None
        steps = 0
        while self.ip < len(code):
            steps += 1
            if steps > max_steps:
                raise RecursionError(f"循环未终止（超出步数上限 {max_steps}）")
            op, arg = code[self.ip]
            self.trace.append((self.ip, op, arg))
            self.ip += 1
            if catch_halt:
                try:
                    self._exec(op, arg)
                except VMHalt as h:
                    halt = h.kind
                    break
            else:
                self._exec(op, arg)
        return {"trust": round(self.trust_value, 3),
                "symbols": dict(self.symbols),
                "condition_space": list(self.condition_stack),
                "stack": list(self.stack),
                "halt": halt,
                "trace": self.trace if trace else None}

    def _truthy(self, v):
        """真值判定：None·0·空串为假，其余真（对照 CPython）。"""
        return v is not None and v is not False and v != 0

    def _exec(self, op, arg):
        """VM 取指分派单步：按操作码执行常量压栈/名装载等；未声明名抛「名实不符」。"""
        if op == Opcode.PUSH_CONST:
            self.stack.append(arg)
        elif op == Opcode.LOAD_NAME:
            if arg not in self.symbols:
                raise NameError(f"名实不符：'{arg}' 未声明（以名举实）")
            self.stack.append(self.symbols[arg])
        elif op == Opcode.STORE_NAME:
            self.symbols[arg] = self.stack.pop()
        elif op == Opcode.JUMP:
            self.ip = arg
        elif op == Opcode.JUMP_IF_FALSE:
            if not self._truthy(self.stack.pop()):
                self.ip = arg
        elif op == Opcode.DAO:
            # 道：创建协议路径 → 条件空间栈压入（对应灵枢条件路由）
            self.condition_stack.append({"name": arg, "trust_at_create": self.trust_value})
        elif op == Opcode.DE:
            # 德：信任值累积（信任引擎内建）
            self.trust_value += arg
        elif op == Opcode.ZIRAN:
            # 自然：恢复默认条件空间（弹栈到根）
            self.condition_stack = self.condition_stack[:1]
        elif op == Opcode.WUWEI:
            # 无为：让出控制（yield 暂停，非终止）
            raise VMHalt("yield", self._state())
        elif op == Opcode.ZHI:
            raise VMHalt("halt", self._state())
        elif op == Opcode.ZHIZU:
            # 知足：信任≥阈值跳转（达标判定）
            threshold, addr = arg
            if self.trust_value >= threshold:
                self.ip = addr
        elif op == Opcode.CMP_EQ:
            b, a = self.stack.pop(), self.stack.pop()
            self.stack.append(a == b)
        elif op == Opcode.CMP_GT:
            b, a = self.stack.pop(), self.stack.pop()
            self.stack.append(a > b)
        elif op == Opcode.CMP_LT:
            b, a = self.stack.pop(), self.stack.pop()
            self.stack.append(a < b)
        elif op == Opcode.CMP_NE:
            b, a = self.stack.pop(), self.stack.pop()
            self.stack.append(a != b)
        elif op == Opcode.CMP_LE:
            b, a = self.stack.pop(), self.stack.pop()
            self.stack.append(a <= b)
        elif op == Opcode.CMP_GE:
            b, a = self.stack.pop(), self.stack.pop()
            self.stack.append(a >= b)
        elif op == Opcode.ADD:
            b, a = self.stack.pop(), self.stack.pop()
            self.stack.append(a + b)
        elif op == Opcode.SUB:
            b, a = self.stack.pop(), self.stack.pop()
            self.stack.append(a - b)
        elif op == Opcode.MUL:
            b, a = self.stack.pop(), self.stack.pop()
            self.stack.append(a * b)
        elif op == Opcode.DIV:
            b, a = self.stack.pop(), self.stack.pop()
            if b == 0:
                raise ZeroDivisionError("除零错误")
            self.stack.append(a / b)
        elif op == Opcode.ENTER_SHUYUE:
            self.scope_depth += 1
        elif op == Opcode.RETURN_STEP:
            self.scope_depth = max(0, self.scope_depth - 1)
        elif op == Opcode.CALL:
            # CALL (entry_ip, param_names)：栈顶 len(param_names) 个实参 → 参数绑定
            entry_ip, param_names = arg
            args = []
            for _ in range(len(param_names)):
                args.append(self.stack.pop())
            args.reverse()
            # 保存调用帧（返回地址 + 符号表 + 信任 + 条件空间）
            self.call_stack.append((self.ip, dict(self.symbols),
                                    self.trust_value, list(self.condition_stack)))
            # 新作用域：继承全局 + 参数绑定（参数遮蔽同名全局）
            self.symbols = dict(self.symbols)
            for pname, pval in zip(param_names, args):
                self.symbols[pname] = pval
            self.ip = entry_ip
        elif op == Opcode.RETURN:
            # 返回值：栈顶保留；恢复调用帧（无帧则程序结束）
            if self.call_stack:
                ret_ip, saved_symbols, saved_trust, saved_cond = self.call_stack.pop()
                self.symbols = saved_symbols
                self.trust_value = saved_trust
                self.condition_stack = saved_cond
                self.ip = ret_ip
            else:
                # 顶层 RETURN：停止执行（无调用者）
                raise VMHalt("halt", self._state())
        else:
            raise ValueError(f"未知指令 {op}")

    def _state(self):
        """采集 VM 状态快照（ip·栈·符号表）供审计与续跑。"""
        return {"trust": round(self.trust_value, 3),
                "symbols": dict(self.symbols),
                "condition_space": list(self.condition_stack),
                "stack": list(self.stack)}


# =============================================================================
# 汇编器：文本 → 字节码（标签支持）
# =============================================================================

def assemble(src):
    """汇编文本 → [(op, arg), ...]
    格式：指令 [参数] [@标签]；标签行 '名:'"""
    code, labels, pending = [], {}, {}
    for raw in src.strip().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith(":"):          # 标签定义
            labels[line[:-1].strip()] = len(code)
            continue
        parts = line.split()
        mnem = parts[0]
        args = parts[1:]
        if mnem == "PUSH_CONST":
            code.append((Opcode.PUSH_CONST, _num(args[0])))
        elif mnem in ("LOAD_NAME", "STORE_NAME"):
            code.append((getattr(Opcode, mnem), args[0]))
        elif mnem in ("JUMP",):
            pending[len(code)] = args[0]
            code.append((Opcode.JUMP, 0))
        elif mnem == "JUMP_IF_FALSE":
            pending[len(code)] = args[0]
            code.append((Opcode.JUMP_IF_FALSE, 0))
        elif mnem == "DAO":
            code.append((Opcode.DAO, " ".join(args)))
        elif mnem == "DE":
            code.append((Opcode.DE, float(args[0])))
        elif mnem == "ZHIZU":
            pending[len(code)] = args[1]
            code.append((Opcode.ZHIZU, (float(args[0]), 0)))
        elif mnem in ("ZIRAN", "WUWEI", "ZHI", "ENTER_SHUYUE", "RETURN_STEP"):
            code.append((getattr(Opcode, mnem), None))
        elif mnem in ("CMP_EQ", "CMP_GT", "CMP_LT"):
            code.append((getattr(Opcode, mnem), None))
        else:
            raise SyntaxError(f"未知助记符 '{mnem}'")
    # 回填标签
    for idx, label in pending.items():
        if label not in labels:
            raise SyntaxError(f"未定义标签 '{label}'")
        op, arg = code[idx]
        if op == Opcode.ZHIZU:
            code[idx] = (op, (arg[0], labels[label]))
        else:
            code[idx] = (op, labels[label])
    return code


def _num(s):
    """数值规整：含小数点转 float，否则 int（栈算术口径一致）。"""
    return float(s) if "." in s else int(s)


if __name__ == "__main__":
    print("=== 智能论字节码 VM（C1 · 原生编译地基 · 零外部运行时）===\n")
    src = """
DAO 新信任路径
DE 0.3
ZHIZU 0.7 @L1
PUSH_CONST 1
STORE_NAME 甲
@L1:
DE 0.5
ZHIZU 0.7 @L2
@L2:
ZHI
"""
    code = assemble(src)
    print("① 汇编字节码：")
    for i, (op, arg) in enumerate(code):
        print(f"   {i:3d} {op.name:14s} {arg}")
    vm = ConditionVM()
    state = vm.run(code, trace=True)
    print(f"\n② VM 执行结果: 信任={state['trust']} 符号={state['symbols']}")
    ok = state["trust"] >= 0.7 and state["symbols"].get("甲") == 1
    print(f"\n=== 判定 ===\n智能论 VM: "
          f"{'✔ 道/德/知足/名实 内建执行（不依赖外部运行时）' if ok else '✘'}")
