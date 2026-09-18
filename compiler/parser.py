"""
parser.py · 语法分析器 v2.0
将 Token 序列构建为抽象语法树（AST）
支持：条件语句、指令语句、九章算术结构

v2.0 变更：
- 新增 _merge_identifiers：合并紧密相连的 IDENTIFIER/NUMBER 序列
- 修复"道 新信任路径"被切成多个操作数的问题
- 支持"止 X 于 Y"结构中的多词 X
"""

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import List, Optional, Union, Any, Tuple
from .lexer import Token, TokenType


# =============================================================================
# AST 节点类型
# =============================================================================

class NodeType(Enum):
    """AST 节点类型"""
    
    # === 顶层 ===
    PROGRAM = auto()           # 整个程序
    
    # === 九章算术结构 ===
    WENYUE = auto()           # 问曰
    DAYUE = auto()             # 答曰
    SHUYUE = auto()            # 术曰
    STEP = auto()              # 步骤（序号.操作）
    
    # === 语句 ===
    CONDITION_STMT = auto()    # 条件语句（若...则...）
    LOOP_STMT = auto()         # 循环语句（当...执行...）
    BLOCK = auto()             # 语句块（多条顺序语句）
    FUNC_DEF = auto()          # 函数定义（定义 名（参数）：语句）
    RETURN_STMT = auto()       # 返回语句（返回 表达式）
    ASSIGN_STMT = auto()       # 赋值语句
    INSTRUCTION_STMT = auto()  # 指令语句（道德经助记符）
    OPERATION_STMT = auto()    # 操作语句
    
    # === 表达式 ===
    BINARY_EXPR = auto()       # 二元表达式
    UNARY_EXPR = auto()        # 一元表达式
    IDENTIFIER = auto()         # 标识符
    LITERAL = auto()           # 字面量
    CALL_EXPR = auto()          # 调用表达式
    
    # === 条件 ===
    COMPARISON = auto()        # 比较表达式


# =============================================================================
# AST 节点定义
# =============================================================================

@dataclass
class ASTNode:
    """AST 节点基类"""
    type: NodeType
    line: int = 1
    column: int = 1
    children: List['ASTNode'] = field(default_factory=list)
    value: Any = None
    attributes: dict = field(default_factory=dict)
    
# 生效条件：child 不是 None 时被 append 进 self.children，child 为 None 时不追加；
    def add_child(self, child: 'ASTNode'):
        if child is not None:
            self.children.append(child)
    
# 生效条件：无 required 形参，self.type 为 NodeType 时返回 f"ASTNode({self.type.name}, value={self.value!r}, children={len(self.children)})"；
    def __repr__(self) -> str:
        return f"ASTNode({self.type.name}, value={self.value!r}, children={len(self.children)})"


@dataclass
# 生效条件：省略 line/column 时取默认 1，实例化即以 NodeType.PROGRAM 为类型且 statements 初始为空列表；
class ProgramNode(ASTNode):
    """程序根节点"""
# 生效条件：省略 line/column 时取默认 1，以 NodeType.PROGRAM 调用父类构造并把 self.statements 置为空列表；
    def __init__(self, line: int = 1, column: int = 1):
        super().__init__(NodeType.PROGRAM, line, column)
        self.statements: List[ASTNode] = []
    
# 生效条件：stmt 非 None 时同时 append 进 self.statements 并调用 self.add_child(stmt)，stmt 为 None 时两条都不执行；
    def add_statement(self, stmt: ASTNode):
        if stmt is not None:
            self.statements.append(stmt)
            self.add_child(stmt)


@dataclass
# 生效条件：传入 question 即成立，节点类型为 NodeType.WENYUE，self.question 与 self.value 均等于该 question。
class WenyueNode(ASTNode):
    """问曰节点"""
# 生效条件：question 必传（line/column 默认 1），实例化即以 NodeType.WENYUE 为类型并把 question 同时写入 self.question 与 self.value；
    def __init__(self, question: str, line: int = 1, column: int = 1):
        super().__init__(NodeType.WENYUE, line, column)
        self.question = question
        self.value = question


@dataclass
# 生效条件：传入 answer 即成立，节点类型为 NodeType.DAYUE，self.answer 与 self.value 均等于该 answer。
class DayueNode(ASTNode):
    """答曰节点"""
# 生效条件：answer 必传（line/column 默认 1），实例化即以 NodeType.DAYUE 为类型并把 answer 同时写入 self.answer 与 self.value；
    def __init__(self, answer: str, line: int = 1, column: int = 1):
        super().__init__(NodeType.DAYUE, line, column)
        self.answer = answer
        self.value = answer


@dataclass
# 生效条件：省略 line/column 时取默认 1，实例化即以 NodeType.SHUYUE 为类型且 steps 初始为空列表；
class ShuyueNode(ASTNode):
    """术曰节点"""
# 生效条件：省略 line/column 时取默认 1，以 NodeType.SHUYUE 调用父类构造并把 self.steps 置为空列表；
    def __init__(self, line: int = 1, column: int = 1):
        super().__init__(NodeType.SHUYUE, line, column)
        self.steps: List['StepNode'] = []
    
# 生效条件：step 无条件 append 进 self.steps（源码无 None 判空）并调用 self.add_child(step)；
    def add_step(self, step: 'StepNode'):
        self.steps.append(step)
        self.add_child(step)


@dataclass
# 生效条件：step_num 与 statement 必传（line/column 默认 1），实例化即以 NodeType.STEP 为类型、写入 self.step_num/self.statement 并调用 add_child(statement)；
class StepNode(ASTNode):
    """步骤节点"""
# 生效条件：step_num 与 statement 必传（line/column 默认 1），写入 self.step_num/self.statement 并调用 self.add_child(statement)；
    def __init__(self, step_num: int, statement: ASTNode, line: int = 1, column: int = 1):
        super().__init__(NodeType.STEP, line, column)
        self.step_num = step_num
        self.statement = statement
        self.add_child(statement)


@dataclass
# 生效条件：传入 condition 与 then_body 即成立，二者依次加为子节点；仅当 else_body 非 None 时 else_body 才被加为子节点。
class ConditionStmtNode(ASTNode):
    """条件语句：若 [条件] 则 [操作] [否则 [操作]]（body 可为语句列表）"""
# 生效条件：condition 与 then_body 必传，else_body 非 None 时才作为第三个子节点加入，else_body 为 None 时子节点仅 condition 与 then_body；
    def __init__(self, condition: ASTNode, then_body, else_body=None,
                 line: int = 1, column: int = 1):
        super().__init__(NodeType.CONDITION_STMT, line, column)
        self.condition = condition
        self.then_body = then_body
        self.else_body = else_body
        self.add_child(condition)
        self.add_child(then_body)
        if else_body is not None:
            self.add_child(else_body)


@dataclass
# 生效条件：传入 condition 与 body 即成立，节点类型为 NodeType.LOOP_STMT，condition 与 body 依次加为子节点。
class LoopStmtNode(ASTNode):
    """循环语句：当 [条件] 执行 [操作]（while 语义，body 可为语句列表）"""
# 生效条件：condition 与 body 必传（line/column 默认 1），二者都被加入子节点；
    def __init__(self, condition: ASTNode, body, line: int = 1, column: int = 1):
        super().__init__(NodeType.LOOP_STMT, line, column)
        self.condition = condition
        self.body = body
        self.add_child(condition)
        self.add_child(body)


@dataclass
# 生效条件：传入可迭代的 statements 即成立，节点类型为 NodeType.BLOCK，statements 中每个元素被 add_child 追加为子节点。
class BlockNode(ASTNode):
    """语句块：多条顺序执行的语句（循环体/条件体多语句支持）"""
# 生效条件：statements 必传，实例化时逐个 s 调用 self.add_child(s)，statements 为空可迭代对象时不加任何子节点；
    def __init__(self, statements, line: int = 1, column: int = 1):
        super().__init__(NodeType.BLOCK, line, column)
        self.statements = statements
        for s in statements:
            self.add_child(s)


@dataclass
# 生效条件：传入 name、params 与 body 即成立，节点类型为 NodeType.FUNC_DEF，name 与 params 存为字段，body 被加为子节点。
class FuncDefNode(ASTNode):
    """函数定义：定义 名（参数）：语句（body 可为语句列表）"""
# 生效条件：name、params、body 必传（line/column 默认 1），三者被写入 self.name/self.params/self.body 且 body 被加入子节点；
    def __init__(self, name: str, params: List[str], body, line: int = 1, column: int = 1):
        super().__init__(NodeType.FUNC_DEF, line, column)
        self.name = name
        self.params = params
        self.body = body
        self.add_child(body)


@dataclass
# 生效条件：value 为真值 ASTNode 时被加为子节点；value 为 None 时节点仍成立（类型 NodeType.RETURN_STMT）但不加子节点。
class ReturnStmtNode(ASTNode):
    """返回语句：返回 [表达式]"""
# 生效条件：value 必传（可为 None），value 为真值时将其加入子节点，value 为 None 等假值时不加入子节点；
    def __init__(self, value: Optional[ASTNode], line: int = 1, column: int = 1):
        super().__init__(NodeType.RETURN_STMT, line, column)
        self.value = value
        if value:
            self.add_child(value)


@dataclass
# 生效条件：传入 name 与 args 即成立，节点类型为 NodeType.CALL_EXPR，args 中每个元素被 add_child 追加为子节点。
class CallExprNode(ASTNode):
    """函数调用：名（参数1，参数2）"""
# 生效条件：name 与 args 必传（line/column 默认 1），args 中每个元素依次被加入子节点；
    def __init__(self, name: str, args: List[ASTNode], line: int = 1, column: int = 1):
        super().__init__(NodeType.CALL_EXPR, line, column)
        self.name = name
        self.args = args
        for a in args:
            self.add_child(a)


@dataclass
# 生效条件：传入 instruction 即成立，节点类型为 NodeType.INSTRUCTION_STMT；operands 为 None 时按空列表处理，非 None 时每个操作数被加为子节点。
class InstructionStmtNode(ASTNode):
    """指令语句：道德经助记符 + 操作数"""
# 生效条件：instruction 必传，operands 为 None 或空列表等假值时回落到新的 []（非空列表则沿用原对象），随后逐个 op 加入子节点；
    def __init__(self, instruction: TokenType, operands: List[ASTNode] = None,
                 line: int = 1, column: int = 1):
        super().__init__(NodeType.INSTRUCTION_STMT, line, column)
        self.instruction = instruction
        self.operands = operands or []
        for op in self.operands:
            self.add_child(op)


@dataclass
# 生效条件：传入 target 与 value 即成立，节点类型为 NodeType.ASSIGN_STMT，target 存为字段，value 存于 value_node 并被加为子节点。
class AssignStmtNode(ASTNode):
    """赋值语句：标识符 = 值"""
# 生效条件：target 与 value 必传（line/column 默认 1），value 写入 self.value_node 并被加入子节点；
    def __init__(self, target: str, value: ASTNode, line: int = 1, column: int = 1):
        super().__init__(NodeType.ASSIGN_STMT, line, column)
        self.target = target
        self.value_node = value
        self.add_child(value)


@dataclass
# 生效条件：传入 left、operator 与 right 即成立，节点类型为 NodeType.BINARY_EXPR，left 与 right 依次加为子节点。
class BinaryExprNode(ASTNode):
    """二元表达式：左 操作符 右"""
# 生效条件：left、operator、right 必传（line/column 默认 1），left 与 right 各被加入一次子节点；
    def __init__(self, left: ASTNode, operator: str, right: ASTNode,
                 line: int = 1, column: int = 1):
        super().__init__(NodeType.BINARY_EXPR, line, column)
        self.left = left
        self.operator = operator
        self.right = right
        self.add_child(left)
        self.add_child(right)


@dataclass
# 生效条件：传入 left、op 与 right 即成立，节点类型为 NodeType.COMPARISON，left 与 right 依次加为子节点。
class ComparisonNode(ASTNode):
    """比较表达式"""
# 生效条件：left、op、right 必传（line/column 默认 1），left 与 right 各被加入一次子节点；
    def __init__(self, left: ASTNode, op: str, right: ASTNode,
                 line: int = 1, column: int = 1):
        super().__init__(NodeType.COMPARISON, line, column)
        self.left = left
        self.op = op
        self.right = right
        self.add_child(left)
        self.add_child(right)


@dataclass
# 生效条件：传入 name 即成立，节点类型为 NodeType.IDENTIFIER，self.name 与 self.value 均等于该 name。
class IdentifierNode(ASTNode):
    """标识符"""
# 生效条件：name 必传（line/column 默认 1），实例化即以 NodeType.IDENTIFIER 为类型并把 name 同时写入 self.name 与 self.value；
    def __init__(self, name: str, line: int = 1, column: int = 1):
        super().__init__(NodeType.IDENTIFIER, line, column)
        self.name = name
        self.value = name


@dataclass
# 生效条件：传入 value 与 literal_type 即成立，节点类型为 NodeType.LITERAL，literal_value 与 value 均等于该 value，literal_type 原样保存。
class LiteralNode(ASTNode):
    """字面量"""
# 生效条件：value 与 literal_type 必传（line/column 默认 1），value 同时写入 self.literal_value 与 self.value，literal_type 仅被原样存储（源码不校验其取值）；
    def __init__(self, value: Union[str, float, int], literal_type: str,
                 line: int = 1, column: int = 1):
        super().__init__(NodeType.LITERAL, line, column)
        self.literal_value = value
        self.literal_type = literal_type  # "number", "string"
        self.value = value


# =============================================================================
# 语法分析器
# =============================================================================

# 生效条件：传入 tokens 即成立，current_token 取 tokens[0]（tokens 为空时为 None）；errors 为 None 时以空列表作为 self.errors。
class Parser:
    """
    语法分析器 v2.0
    将 Token 序列构建为 AST
    """
    
    # 指令助记符集合
    INSTRUCTION_TOKENS = {
        TokenType.DAO, TokenType.DE, TokenType.ZIRAN,
        TokenType.WUWEI, TokenType.GU, TokenType.PIN,
        TokenType.ROU, TokenType.PU, TokenType.ZHI, TokenType.ZHIZU,
    }
    
# 生效条件：tokens 必传，errors 为 None 或空列表等假值时回落到新的 []，self.current_token 在 tokens 非空时取 tokens[0]、tokens 为空时取 None；
    def __init__(self, tokens: List[Token], errors: List[str] = None):
        self.tokens = tokens
        self.pos = 0
        self.errors: List[str] = errors or []
        self.current_token = self.tokens[0] if tokens else None
    
# 生效条件：无 required 形参，先建 ProgramNode，随后 while not self._is_at_end()：遇 NEWLINE/SEMICOLON/COMMA 即 continue，stmt 为真值时 program.add_statement(stmt)，为假值时 _advance()，循环结束返回 program；
    def parse(self) -> ProgramNode:
        """解析整个程序"""
        program = ProgramNode()
        
        while not self._is_at_end():
            if self._match(TokenType.NEWLINE, TokenType.SEMICOLON, TokenType.COMMA):
                continue
            
            stmt = self._parse_statement()
            if stmt:
                program.add_statement(stmt)
                # DEBUG
                # print(f"  [parse] Added: type={stmt.type.name} value={stmt.value!r}")
                # if hasattr(stmt, 'operands'):
                #     for j, op in enumerate(stmt.operands):
                #         print(f"    op{j}: {op.type.name} value={op.value!r}")
            else:
                # print(f"  [parse] None at {self.current_token}")
                self._advance()
        
        return program
    
    # ---- 语句解析 ----
    
# 生效条件：current_token 为 None 或 TokenType.EOF 返回 None；TokenType.WENYUE→_parse_wenyue_block、SHUYUE→_parse_shuyue_block、RUO→_parse_condition、DANG→_parse_loop、DINGYI→_parse_func_def、FANHUI→推进后取表达式返回 ReturnStmtNode、类型在 INSTRUCTION_TOKENS→_parse_instruction、IDENTIFIER→_parse_assign_or_call、PERIOD→推进并返回 None，其余追加带 L{line}:C{column} 的 errors 项、推进并返回 None；
    def _parse_statement(self) -> Optional[ASTNode]:
        """解析单个语句"""
        token = self.current_token
        
        if token is None or token.type == TokenType.EOF:
            return None
        
        # 问曰 → 答曰 → 术曰（九章算术结构）
        if token.type == TokenType.WENYUE:
            return self._parse_wenyue_block()
        
        # 术曰 → 术曰块（可以独立出现）
        if token.type == TokenType.SHUYUE:
            return self._parse_shuyue_block()
        
        # 若 → 条件语句
        if token.type == TokenType.RUO:
            return self._parse_condition()
        
        # 当 → 循环语句（白箱循环语法：当 条件 执行 操作）
        if token.type == TokenType.DANG:
            return self._parse_loop()
        
        # 定义 → 函数定义（定义 名（参数）：语句）
        if token.type == TokenType.DINGYI:
            return self._parse_func_def()
        
        # 返回 → 返回语句（返回 表达式）
        if token.type == TokenType.FANHUI:
            self._advance()
            val = self._parse_expression() if self.current_token else None
            return ReturnStmtNode(val,
                                  line=token.line, column=token.column)
        
        # 道德经助记符 → 指令语句
        if token.type in self.INSTRUCTION_TOKENS:
            return self._parse_instruction()
        
        # 标识符 → 可能是赋值
        if token.type == TokenType.IDENTIFIER:
            return self._parse_assign_or_call()
        
        # 句号结束
        if token.type == TokenType.PERIOD:
            self._advance()
            return None
        
        # 无法识别
        self.errors.append(
            f"L{token.line}:C{token.column} 无法解析的语句开头: '{token.value}' ({token.type.name})"
        )
        self._advance()
        return None
    
# 生效条件：无 required 形参，消费 SHUYUE 后以当前 token 的行列建 ShuyueNode，循环内先跳过分隔符（SEMICOLON/COMMA/COLON），当前 token 为 NUMBER 时取 int(float(value)) 为步骤号、可选跳过 PERIOD、解析步骤内容且内容为真值时 add_step(StepNode(...))，当前 token 非 NUMBER 即 break，最后返回 shuyue；
    def _parse_shuyue_block(self) -> Optional[ASTNode]:
        """
        解析术曰块（独立形式）：术曰：1。... 2。...
        不依赖前面的问曰/答曰
        """
        self._consume(TokenType.SHUYUE, "期望 '术曰'")
        
        shuyue = ShuyueNode(line=self.current_token.line if self.current_token else 1,
                            column=self.current_token.column if self.current_token else 1)
        
        # 解析步骤序列
        while not self._is_at_end():
            # 跳过分隔符
            while (self.current_token and
                   self.current_token.type in (TokenType.SEMICOLON,
                                                 TokenType.COMMA,
                                                 TokenType.COLON)):
                self._advance()
            
            if self.current_token and self.current_token.type == TokenType.NUMBER:
                step_num = int(float(self.current_token.value))
                self._advance()
                
                if self.current_token and self.current_token.type == TokenType.PERIOD:
                    self._advance()
                
                step_content = self._parse_step_content()
                if step_content:
                    shuyue.add_step(StepNode(step_num, step_content,
                                            line=step_content.line,
                                            column=step_content.column))
            else:
                break
        
        return shuyue
    
# 生效条件：无 required 形参（self 除外）时，若 self.current_token 为 WENYUE 且后续 _consume 能依次消费 DAYUE、SHUYUE，则收集 question/answer，循环跳过分隔符后仅当 current_token 为 NUMBER 时取 int(float(value))、可选消费 PERIOD，且仅当 _parse_step_content() 返回真值才 shuyue.add_step(StepNode(...))，非 NUMBER 时 break，最后设 shuyue.attributes 的 question/answer 并返回 shuyue；
    def _parse_wenyue_block(self) -> Optional[ASTNode]:
        """解析 问曰：... 答曰：... 术曰：... 结构"""
        # 问曰
        self._consume(TokenType.WENYUE, "期望 '问曰'")
        question_parts = self._collect_until(TokenType.DAYUE)
        question = "".join(p.value for p in question_parts).strip()
        
        # 答曰
        self._consume(TokenType.DAYUE, "期望 '答曰'")
        answer_parts = self._collect_until(TokenType.SHUYUE)
        answer = "".join(p.value for p in answer_parts).strip()
        
        # 术曰
        self._consume(TokenType.SHUYUE, "期望 '术曰'")
        
        # 用独立的术曰解析逻辑
        shuyue = ShuyueNode(line=self.current_token.line if self.current_token else 1,
                            column=self.current_token.column if self.current_token else 1)
        
        while not self._is_at_end():
            # 跳过分隔符
            while (self.current_token and 
                   self.current_token.type in (TokenType.SEMICOLON, 
                                                TokenType.COMMA,
                                                TokenType.COLON)):
                self._advance()
            
            if self.current_token and self.current_token.type == TokenType.NUMBER:
                step_num = int(float(self.current_token.value))
                self._advance()
                
                if self.current_token and self.current_token.type == TokenType.PERIOD:
                    self._advance()
                
                step_content = self._parse_step_content()
                if step_content:
                    shuyue.add_step(StepNode(step_num, step_content,
                                            line=step_content.line,
                                            column=step_content.column))
            else:
                break
        
        shuyue.attributes["question"] = question
        shuyue.attributes["answer"] = answer
        
        return shuyue
    
# 生效条件：无 required 形参，按 current_token.type 分派——RUO→_parse_condition、DANG→_parse_loop、DINGYI→_parse_func_def、FANHUI→推进后取表达式返回 ReturnStmtNode(val,line=1,column=1)、助记符（INSTRUCTION_TOKENS）→_parse_instruction、IDENTIFIER 且 _peek_next() 为 EQUALS 或 LPAREN→_parse_assign_or_call 否则 _merge_identifiers、其余把到 NUMBER/PERIOD 前的 token 拼成字符串 LiteralNode（无内容返回 None）；
    def _parse_step_content(self) -> Optional[ASTNode]:
        """解析步骤内容"""
        if self.current_token and self.current_token.type == TokenType.RUO:
            return self._parse_condition()
        elif self.current_token and self.current_token.type == TokenType.DANG:
            return self._parse_loop()
        elif self.current_token and self.current_token.type == TokenType.DINGYI:
            return self._parse_func_def()
        elif self.current_token and self.current_token.type == TokenType.FANHUI:
            self._advance()
            val = self._parse_expression() if self.current_token else None
            return ReturnStmtNode(val, line=1, column=1)
        elif self.current_token and self.current_token.type in self.INSTRUCTION_TOKENS:
            return self._parse_instruction()
        elif self.current_token and self.current_token.type == TokenType.IDENTIFIER:
            # 缺陷⑤修复（2026-09-14）：步骤内容里的**赋值/调用**此前被静默丢弃
            # —— 原实现无条件走 _merge_identifiers()（多词短语合并），
            # 从不检查其后是否紧跟 = 或 （，于是「1。甲 = 0.9；」只留下
            # 裸标识符 甲，`= 0.9` 被丢掉且不报错（静默错值，比崩溃更危险）。
            # 修法：先探视下一个 token —— = 或 （ 走 _parse_assign_or_call，
            # 否则保持原多词合并行为（道 新信任路径 等短语不受影响）。
            _nxt = self._peek_next()
            if _nxt is not None and _nxt.type in (TokenType.EQUALS,
                                                  TokenType.LPAREN):
                return self._parse_assign_or_call()
            merged = self._merge_identifiers()
            return merged
        else:
            parts = []
            while (self.current_token and
                   self.current_token.type not in (TokenType.NUMBER, TokenType.PERIOD) and
                   not self._is_at_end()):
                parts.append(self.current_token.value)
                self._advance()
            if parts:
                return LiteralNode("".join(parts).strip(), "string",
                                  line=self.current_token.line if self.current_token else 1,
                                  column=self.current_token.column if self.current_token else 1)
            return None
    
# 生效条件：无 required 形参，消费 RUO 后解析比较式并跳过标点消费 ZE，then_body 由 _parse_single_statement 取得，仅当再跳过标点后 current_token 为 FOUZE 时才推进并解析 else_body（否则 else_body=None），返回 ConditionStmtNode(condition, then_body, else_body, start_line, start_col)；
    def _parse_condition(self) -> Optional[ASTNode]:
        """解析条件语句：若 [条件] 则 [操作] [否则 [操作]]"""
        start_line = self.current_token.line if self.current_token else 1
        start_col = self.current_token.column if self.current_token else 1
        
        self._consume(TokenType.RUO, "期望 '若'")
        
        condition = self._parse_comparison()
        
        self._skip_punctuation_before(TokenType.ZE)
        
        self._consume(TokenType.ZE, "期望 '则'")
        
        then_body = self._parse_single_statement()
        
        else_body = None
        # 跳过 then 与 否则 之间的分隔符（逗号/分号等）
        self._skip_punctuation_before(TokenType.FOUZE)
        if self.current_token and self.current_token.type == TokenType.FOUZE:
            self._advance()
            else_body = self._parse_single_statement()
        
        return ConditionStmtNode(condition, then_body, else_body, start_line, start_col)
    
# 生效条件：无 required 形参，消费 DANG 后解析比较式、跳过标点消费 ZHIXING，body 取 _parse_statement_or_block()，返回 LoopStmtNode(condition, body, start_line, start_col)；
    def _parse_loop(self) -> Optional[ASTNode]:
        """解析循环语句：当 [条件] 执行 [操作]（while 语义）"""
        start_line = self.current_token.line if self.current_token else 1
        start_col = self.current_token.column if self.current_token else 1
        
        self._consume(TokenType.DANG, "期望 '当'")
        
        condition = self._parse_comparison()
        
        self._skip_punctuation_before(TokenType.ZHIXING)
        
        self._consume(TokenType.ZHIXING, "期望 '执行'")
        
        body = self._parse_statement_or_block()
        
        return LoopStmtNode(condition, body, start_line, start_col)
    
# 生效条件：无 required 形参，消费 DINGYI 后 current_token 不属于 (IDENTIFIER, OP_ADD, OP_SUB, OP_MUL, OP_DIV) 时向 errors 追加"定义后期望函数名"并返回 None；否则取函数名，遇 LPAREN 时括号内仅 IDENTIFIER 被收作 params（其余 token 只推进），可选跳过 COLON，body 取 _parse_single_statement()，返回 FuncDefNode(name, params, body, start_line, start_col)；
    def _parse_func_def(self) -> Optional[ASTNode]:
        """解析函数定义：定义 名（参数1，参数2）：语句
        参数在（ ）内，逗号分隔；返回 FuncDefNode（body 可为块）"""
        start_line = self.current_token.line if self.current_token else 1
        start_col = self.current_token.column if self.current_token else 1
        
        self._consume(TokenType.DINGYI, "期望 '定义'")
        
        # 函数名（标识符；T11：允许运算词作函数名，与调用侧对称——
        # 否则「定义 加（甲，乙）」定义头失败，函数体泄漏顶层）
        _name_types = (TokenType.IDENTIFIER, TokenType.OP_ADD,
                       TokenType.OP_SUB, TokenType.OP_MUL, TokenType.OP_DIV)
        if not (self.current_token and self.current_token.type in _name_types):
            self.errors.append("定义后期望函数名")
            return None
        name = self.current_token.value
        self._advance()
        
        # 参数列表（ ）
        params = []
        if self.current_token and self.current_token.type == TokenType.LPAREN:
            self._advance()
            while (self.current_token and
                   self.current_token.type != TokenType.RPAREN and
                   not self._is_at_end()):
                if self.current_token.type == TokenType.IDENTIFIER:
                    params.append(self.current_token.value)
                self._advance()  # 跳过标识符/逗号/空格
            if self.current_token and self.current_token.type == TokenType.RPAREN:
                self._advance()
        
        # 冒号（可选分隔）
        if self.current_token and self.current_token.type == TokenType.COLON:
            self._advance()
        
        body = self._parse_single_statement()
        
        return FuncDefNode(name, params, body, start_line, start_col)
    
    def _skip_punctuation_before(self, *target_types: TokenType):
        """跳过标点符号"""
        while self.current_token and self.current_token.type in (
            TokenType.COMMA, TokenType.PERIOD, TokenType.SEMICOLON,
            TokenType.COLON, TokenType.QUESTION, TokenType.EXCLAM,
        ):
            self._advance()
    
# 生效条件：无 required 形参，循环调用 _parse_single_statement 收语句：current_token 为 PERIOD 时推进并结束；为 SEMICOLON/COMMA 时推进且其后 token 为 NUMBER 或 SHUYUE 则结束、否则 continue；其他情况直接结束；stmts 为空返回 None，恰 1 条返回该语句本身，多条返回 BlockNode(stmts, line=stmts[0].line, column=stmts[0].column)；
    def _parse_statement_or_block(self) -> Any:
        """解析语句或块：返回语句列表（单语句=[stmt]；分号分隔多条）

        分隔符语义（2026-09-14 修复缺陷①）：
          ；/，  → 块内续接，继续收下一条（循环体多语句用分号连接）
          。    → **全句终止**，块到此结束，后续语句归上一层（顶层）
        修复前 。 也续接，导致「当…执行 A。B。」把 B 吞进循环体；
        无步骤编号时更会把其后全部顶层语句吞入 → 顶层语句在循环里
        反复执行（若该语句重新武装循环条件即为死循环 RecursionError）。
        块内若要写多条语句，请用分号：`当 X 执行 A；B。`
        """
        stmts = []
        while True:
            stmt = self._parse_single_statement()
            if stmt is not None:
                stmts.append(stmt)
            tok = self.current_token
            # 。= 全句终止 → 块结束（缺陷①修复点）
            if tok and tok.type == TokenType.PERIOD:
                self._advance()
                break
            # ；/，= 块内续接
            if tok and tok.type in (TokenType.SEMICOLON, TokenType.COMMA):
                self._advance()
                # 分隔符后若是步骤号/术曰 → 块结束（九章算术步骤边界 1。…2。…）
                if (self.current_token and
                        self.current_token.type in (TokenType.NUMBER, TokenType.SHUYUE)):
                    break
                continue
            break
        if not stmts:
            return None
        if len(stmts) == 1:
            return stmts[0]
        return BlockNode(stmts, line=stmts[0].line, column=stmts[0].column)

# 生效条件：无 required 形参，按 current_token.type 分派——RUO→_parse_condition、DANG→_parse_loop、DINGYI→_parse_func_def、FANHUI→推进后取表达式返回 ReturnStmtNode(val,line=1,column=1)、助记符（INSTRUCTION_TOKENS）→_parse_instruction、IDENTIFIER→_parse_assign_or_call，否则收集 _STOP（PERIOD/COMMA/SEMICOLON/WENYUE/DAYUE/SHUYUE/RUO/FOUZE/DANG/ZHIXING）之前的 token 拼成字符串 LiteralNode，文本为空返回 None；
    def _parse_single_statement(self) -> Optional[ASTNode]:
        """解析单条语句"""
        if self.current_token and self.current_token.type == TokenType.RUO:
            return self._parse_condition()
        elif self.current_token and self.current_token.type == TokenType.DANG:
            return self._parse_loop()
        elif self.current_token and self.current_token.type == TokenType.DINGYI:
            return self._parse_func_def()
        elif self.current_token and self.current_token.type == TokenType.FANHUI:
            self._advance()
            val = self._parse_expression() if self.current_token else None
            return ReturnStmtNode(val, line=1, column=1)
        elif self.current_token and self.current_token.type in self.INSTRUCTION_TOKENS:
            return self._parse_instruction()
        elif self.current_token and self.current_token.type == TokenType.IDENTIFIER:
            return self._parse_assign_or_call()
        else:
            parts = []
            # 停止条件：标点符号 + 语句开头关键字
            _STOP = (
                TokenType.PERIOD, TokenType.COMMA, TokenType.SEMICOLON,
                TokenType.WENYUE, TokenType.DAYUE, TokenType.SHUYUE,
                TokenType.RUO, TokenType.FOUZE, TokenType.DANG,
                TokenType.ZHIXING,
            )
            while (self.current_token and
                   self.current_token.type not in _STOP and
                   not self._is_at_end()):
                parts.append(self.current_token.value)
                self._advance()
            text = "".join(parts).strip()
            if text:
                return LiteralNode(text, "string")
            return None
    
# 生效条件：无 required 形参，以当前 token 类型为 instr_type 并推进，随后循环至 _INST_STOP（PERIOD/COMMA/SEMICOLON/EOF 及各语句开头关键字）或 _is_at_end()：YU→推进后取 _parse_numeric_value 加入 operands、IDENTIFIER→_merge_identifiers 后加入、NUMBER→LiteralNode(float(value),"number")、STRING→LiteralNode(value,"string")、其他类型仅推进，返回 InstructionStmtNode(instr_type, operands, line=指令 token 行, column=指令 token 列)；
    def _parse_instruction(self) -> Optional[ASTNode]:
        """
        解析指令语句 v2.0
        
        关键改进：使用 _merge_identifiers 合并紧密相连的
        IDENTIFIER/NUMBER 序列为一个逻辑操作数。
        
        例：道 新信任路径  → 道 + [ID(新信任路径)]
        例：柔 响应强度    → 柔 + [ID(响应强度)]
        例：止情感权重于0.15 → 止 + [ID(情感权重)] + [Lit(0.15)]
        """
        instr_token = self.current_token
        instr_type = instr_token.type
        self._advance()
        
        operands = []
        
        # 停止条件：标点符号 + 语句开头关键字（防止跨语句吞噬）
        _INST_STOP = (
            TokenType.PERIOD, TokenType.COMMA, TokenType.SEMICOLON,
            TokenType.EOF,
            # 语句开头关键字 —— 遇到这些说明指令操作数已结束
            TokenType.WENYUE,    # 问曰 → 新语句
            TokenType.DAYUE,     # 答曰 → 新语句
            TokenType.SHUYUE,    # 术曰 → 新语句
            TokenType.RUO,        # 若 → 条件语句
            TokenType.FOUZE,     # 否则 → 条件语句
            TokenType.DAO,       # 道 → 指令（但不在操作数位置）
            TokenType.DE,        # 德 → 指令
            TokenType.ZIRAN,     # 自然 → 指令
            TokenType.WUWEI,     # 无为 → 指令
            TokenType.GU,        # 谷 → 指令
            TokenType.PIN,       # 牝 → 指令
            TokenType.ROU,       # 柔 → 指令
            TokenType.PU,        # 朴 → 指令
            TokenType.ZHI,       # 止 → 指令
            TokenType.ZHIZU,     # 知足 → 指令
        )
        
        while (self.current_token and
               self.current_token.type not in _INST_STOP and
               not self._is_at_end()):
            
            tok = self.current_token
            
            if tok.type == TokenType.YU:
                # "于" → 后面跟数值
                self._advance()
                value = self._parse_numeric_value()
                if value is not None:
                    operands.append(value)
                continue
            
            elif tok.type == TokenType.IDENTIFIER:
                # 合并后续紧密相连的 IDENTIFIER/NUMBER
                merged = self._merge_identifiers()
                operands.append(merged)
            
            elif tok.type == TokenType.NUMBER:
                operands.append(LiteralNode(float(tok.value), "number", tok.line, tok.column))
                self._advance()
            
            elif tok.type == TokenType.STRING:
                operands.append(LiteralNode(tok.value, "string", tok.line, tok.column))
                self._advance()
            
            else:
                self._advance()
        
        return InstructionStmtNode(instr_type, operands,
                                   line=instr_token.line,
                                   column=instr_token.column)
    
# 生效条件：无 required 形参，以 current_token 的 value 为首段并推进，之后把行号相同且类型为 IDENTIFIER/NUMBER 的 token.value 依次拼入（源码只比较 line、未比较列号是否连续），返回 IdentifierNode(拼接名, 起始 line, 起始 col)；
    def _merge_identifiers(self) -> ASTNode:
        """
        合并从当前位置开始的紧密相连的 IDENTIFIER/NUMBER 序列
        
        例：ID(新) ID(信任) ID(路径) → IdentifierNode("新信任路径")
        例：ID(响应) ID(强度) → IdentifierNode("响应强度")
        例：ID(累积) ID(信任值) → IdentifierNode("累积信任值")
        
        判断标准：同一行、列号连续
        """
        start_tok = self.current_token
        parts = [start_tok.value]
        line = start_tok.line
        col = start_tok.column
        self._advance()
        
        while (self.current_token and
               self.current_token.line == line and
               self.current_token.type in (TokenType.IDENTIFIER, TokenType.NUMBER)):
            parts.append(self.current_token.value)
            self._advance()
        
        merged_name = "".join(parts)
        return IdentifierNode(merged_name, line, col)
    
# 生效条件：无 required 形参，current_token 为 None 或类型为其他时返回 None；为 NUMBER 时返回 float 值 LiteralNode；为 IDENTIFIER 时若后随 PERIOD 再跟 NUMBER 则拼接为小数、后随 PERIOD 而后续非 NUMBER 则 float(prefix) 成功返回数值节点、ValueError 时返回 IdentifierNode、后随 NUMBER 则拼接转 float、其余后随返回 IdentifierNode。
    def _parse_numeric_value(self) -> Optional[ASTNode]:
        """解析数值（可能跨多个 token）"""
        if self.current_token is None:
            return None
        
        if self.current_token.type == TokenType.NUMBER:
            val = float(self.current_token.value)
            line, col = self.current_token.line, self.current_token.column
            self._advance()
            return LiteralNode(val, "number", line, col)
        
        if self.current_token.type == TokenType.IDENTIFIER:
            prefix = self.current_token.value
            line, col = self.current_token.line, self.current_token.column
            self._advance()
            
            if self.current_token and self.current_token.type == TokenType.PERIOD:
                self._advance()
                if self.current_token and self.current_token.type == TokenType.NUMBER:
                    val = float(prefix + "." + self.current_token.value)
                    self._advance()
                    return LiteralNode(val, "number", line, col)
                else:
                    try:
                        return LiteralNode(float(prefix), "number", line, col)
                    except ValueError:
                        return IdentifierNode(prefix, line, col)
            elif self.current_token and self.current_token.type == TokenType.NUMBER:
                val = float(prefix + self.current_token.value)
                self._advance()
                return LiteralNode(val, "number", line, col)
            else:
                return IdentifierNode(prefix, line, col)
        
        return None
    
# 生效条件：无 required 形参，取自 self.current_token 的标识符消费后：紧跟 EQUALS 则解析表达式返回 AssignStmtNode(target=ident,...)；紧跟 LPAREN 则循环收集 IDENTIFIER/NUMBER 参数（其他 token 直接 _advance 跳过），遇到 RPAREN 或无 RPAREN 时均返回 CallExprNode(ident, args,...)；其余情况返回 IdentifierNode(ident,...)。
    def _parse_assign_or_call(self) -> Optional[ASTNode]:
        """解析赋值或调用

        若后面紧跟 = 或 ＝ → 赋值语句
        若后面紧跟 （ → 函数调用表达式（名（参数））
        否则 → 标识符表达式
        """
        ident = self.current_token.value
        line = self.current_token.line
        col = self.current_token.column
        self._advance()

        # 检查是否是赋值
        if self.current_token and self.current_token.type == TokenType.EQUALS:
            self._advance()  # 跳过 =
            value_node = self._parse_expression()
            return AssignStmtNode(
                target=ident,
                value=value_node,
                line=line,
                column=col
            )

        # 函数调用：名（参数1，参数2）
        if self.current_token and self.current_token.type == TokenType.LPAREN:
            self._advance()
            args = []
            while (self.current_token and
                   self.current_token.type != TokenType.RPAREN and
                   not self._is_at_end()):
                # 参数可为表达式（n 减 1）/标识符/数值
                if self.current_token.type in (TokenType.IDENTIFIER,
                                               TokenType.NUMBER):
                    args.append(self._parse_expression())
                else:
                    self._advance()
            if self.current_token and self.current_token.type == TokenType.RPAREN:
                self._advance()
            return CallExprNode(ident, args, line, col)

        return IdentifierNode(ident, line, col)
    
# 生效条件：无 required 形参，先以 _parse_expression() 得 left，仅当随后 self.current_token.type 属于 DENGYU/DAYU/XIAOYU/WEI/BUWEI 时消费该 token（映射为 ==/>/</==/!=，WEI 与 DENGYU 均映射 ==）并取 right（_parse_numeric_value 返回 None 时改调 _parse_expression）返回 ComparisonNode，否则原样返回 left。
    def _parse_comparison(self) -> ASTNode:
        """解析比较表达式"""
        left = self._parse_expression()
        
        if self.current_token and self.current_token.type in (
            TokenType.DENGYU, TokenType.DAYU, TokenType.XIAOYU,
            TokenType.WEI, TokenType.BUWEI,
        ):
            op_token = self.current_token
            op_map = {
                TokenType.DENGYU: "==",
                TokenType.DAYU: ">",
                TokenType.XIAOYU: "<",
                TokenType.WEI: "==",
                TokenType.BUWEI: "!=",
            }
            op = op_map.get(op_token.type, "==")
            self._advance()
            
            right = self._parse_numeric_value()
            if right is None:
                right = self._parse_expression()
            return ComparisonNode(left, op, right, line=op_token.line, column=op_token.column)
        
        return left
    
    def _parse_expression(self) -> ASTNode:
        """解析表达式（支持二元算术 + 括号优先：标识符/数值/(表达式) + 运算符 + 右）"""
        if self.current_token is None:
            return LiteralNode("", "string")
        
        if self.current_token.type == TokenType.LPAREN:
            # 括号优先： ( 表达式 )
            line = self.current_token.line
            col = self.current_token.column
            self._advance()
            inner = self._parse_expression()
            if self.current_token and self.current_token.type == TokenType.RPAREN:
                self._advance()
            return self._parse_binary_tail(inner)
        
        if self.current_token.type == TokenType.IDENTIFIER:
            # 若后跟 （ → 函数调用；否则合并多词短语
            if (self._peek_next() and
                    self._peek_next().type == TokenType.LPAREN):
                name = self.current_token.value
                line = self.current_token.line
                col = self.current_token.column
                self._advance()  # 消费函数名
                self._advance()  # 消费 （
                args = []
                while (self.current_token and
                       self.current_token.type != TokenType.RPAREN and
                       not self._is_at_end()):
                    if self.current_token.type in (TokenType.IDENTIFIER,
                                                   TokenType.NUMBER):
                        args.append(self._parse_expression())
                    else:
                        self._advance()
                if self.current_token and self.current_token.type == TokenType.RPAREN:
                    self._advance()
                return self._parse_binary_tail(
                    CallExprNode(name, args, line, col))
            left = self._merge_identifiers()
            return self._parse_binary_tail(left)
        elif (self.current_token.type in (TokenType.OP_ADD, TokenType.OP_SUB,
                                          TokenType.OP_MUL, TokenType.OP_DIV)
              and self._peek_next() and self._peek_next().type == TokenType.LPAREN):
            # 运算词作函数名调用（与「定义 加（甲，乙）」定义侧对称）——
            # 否则落入末尾字符串兜底，静默产出错误字节码（T9-2b 缺陷一）
            name = self.current_token.value
            line = self.current_token.line
            col = self.current_token.column
            self._advance()
            self._advance()  # 消费 （
            args = []
            while (self.current_token and
                   self.current_token.type != TokenType.RPAREN and
                   not self._is_at_end()):
                if self.current_token.type in (TokenType.IDENTIFIER,
                                               TokenType.NUMBER):
                    args.append(self._parse_expression())
                else:
                    self._advance()
            if self.current_token and self.current_token.type == TokenType.RPAREN:
                self._advance()
            return self._parse_binary_tail(
                CallExprNode(name, args, line, col))
        elif self.current_token.type == TokenType.NUMBER:
            node = LiteralNode(float(self.current_token.value), "number",
                                self.current_token.line,
                                self.current_token.column)
            self._advance()
            return self._parse_binary_tail(node)
        elif self.current_token.type == TokenType.STRING:
            node = LiteralNode(self.current_token.value, "string",
                                self.current_token.line,
                                self.current_token.column)
            self._advance()
            return self._parse_binary_tail(node)
        else:
            parts = []
            # 停止条件：标点符号 + 语句开头关键字
            _EXPR_STOP = (
                TokenType.ZE, TokenType.FOUZE,
                TokenType.PERIOD, TokenType.COMMA, TokenType.SEMICOLON,
                TokenType.WENYUE, TokenType.DAYUE, TokenType.SHUYUE,
                TokenType.RUO, TokenType.DAO, TokenType.DE,
                TokenType.ZIRAN, TokenType.WUWEI, TokenType.GU,
                TokenType.PIN, TokenType.ROU, TokenType.PU,
                TokenType.ZHI, TokenType.ZHIZU,
            )
            while (self.current_token and
                   self.current_token.type not in _EXPR_STOP and
                   not self._is_at_end()):
                parts.append(self.current_token.value)
                self._advance()
            return LiteralNode("".join(parts).strip(), "string")
    
# 生效条件：必填实参 left 已解析，仅当 self.current_token.type 为 OP_ADD/OP_SUB/OP_MUL/OP_DIV 时消费该运算符、以 _parse_expression() 解析 right 并返回 BinaryExprNode（单级，不再递归调用自身），否则原样返回 left。
    def _parse_binary_tail(self, left: ASTNode) -> ASTNode:
        """解析二元算术尾部：left [+|-|*|/] right（右结合单级，满足循环体自增语义）"""
        if self.current_token and self.current_token.type in (
            TokenType.OP_ADD, TokenType.OP_SUB,
            TokenType.OP_MUL, TokenType.OP_DIV,
        ):
            op_token = self.current_token
            op_map = {
                TokenType.OP_ADD: "+", TokenType.OP_SUB: "-",
                TokenType.OP_MUL: "*", TokenType.OP_DIV: "/",
            }
            op = op_map[op_token.type]
            self._advance()
            right = self._parse_expression()
            return BinaryExprNode(left, op, right,
                                  line=op_token.line, column=op_token.column)
        return left
    
    # ---- 辅助方法 ----
    
# 生效条件：无 required 形参，self.pos >= len(self.tokens)（含 tokens 为空列表）或 self.current_token 非 None 且其 type 为 TokenType.EOF 时返回 True，否则返回 False。
    def _is_at_end(self) -> bool:
        return self.pos >= len(self.tokens) or (
            self.current_token is not None and self.current_token.type == TokenType.EOF
        )
    
# 生效条件：无 required 形参，pos < len(self.tokens)-1 时 pos 加 1、current_token 置为 tokens[pos] 并返回之；pos == len(self.tokens)-1 时 pos 加 1、current_token 置为 None 并返回 None；pos 已大于 len(self.tokens)-1 时不改动，返回当前 self.current_token。
    def _advance(self) -> Optional[Token]:
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
            self.current_token = self.tokens[self.pos]
        elif self.pos == len(self.tokens) - 1:
            self.pos += 1
            self.current_token = None
        return self.current_token

# 生效条件：无 required 形参，仅当 self.pos < len(self.tokens)-1 时返回 self.tokens[self.pos + 1]（不推进 self.pos），否则返回 None（含 tokens 为空时）。
    def _peek_next(self) -> Optional[Token]:
        """查看下一个 token（不消费）"""
        if self.pos < len(self.tokens) - 1:
            return self.tokens[self.pos + 1]
        return None
    
    def _match(self, *types: TokenType) -> bool:
        if self.current_token and self.current_token.type in types:
            self._advance()
            return True
        return False
    
# 生效条件：必填实参 token_type 与 message 到位，self.current_token 非 None 且 type == token_type 时返回该 token 并 _advance；否则向 self.errors 追加含 token_type 不符位置与 message 的字符串并返回 None（current_token 为 None 时位置记为 EOF）。
    def _consume(self, token_type: TokenType, message: str) -> Optional[Token]:
        if self.current_token and self.current_token.type == token_type:
            token = self.current_token
            self._advance()
            return token
        else:
            loc = f"L{self.current_token.line}:C{self.current_token.column}" if self.current_token else "EOF"
            self.errors.append(f"{loc} {message}，实际得到: '{self.current_token.value if self.current_token else 'EOF'}'")
            return None
    
# 生效条件：无 required 形参，从 self.current_token 起循环收集，current_token 为 None、type 为 TokenType.EOF 或 type 属于 stop_types 时停止；循环内 type 为 COLON 的 token 只 _advance 不加入 parts，其余加入 parts 后推进，返回 parts（stop_types 为空元组时只有 EOF 或 token 耗尽能终止）。
    def _collect_until(self, *stop_types: TokenType) -> List[Token]:
        """收集 Token 直到遇到停止类型"""
        parts = []
        while (self.current_token and
               self.current_token.type not in stop_types and
               self.current_token.type != TokenType.EOF):
            if self.current_token.type == TokenType.COLON:
                self._advance()
                continue
            parts.append(self.current_token)
            self._advance()
        return parts


# =============================================================================
# 便捷函数
# =============================================================================

# 生效条件：传入 tokens 且 errors 为 None 或列表时，返回 Parser(tokens, errors or []).parse() 得到的 ProgramNode。
def parse_tokens(tokens: List[Token], errors: List[str] = None) -> ProgramNode:
    """便捷函数：将 Token 列表解析为 AST"""
    parser = Parser(tokens, errors or [])
    return parser.parse()


# 生效条件：传入 source 字符串时，tokenize(source) 产出 tokens 与 lex_errors，再返回 (parse_tokens(tokens, []) 的 AST, lex_errors, 该 AST 的 errors 属性或 [])。
def parse_source(source: str) -> tuple:
    """便捷函数：从源代码直接解析为 AST"""
    from .lexer import tokenize
    tokens, lex_errors = tokenize(source)
    ast = parse_tokens(tokens, [])
    return ast, lex_errors, ast.errors if hasattr(ast, 'errors') else []


# =============================================================================
# 测试
# =============================================================================

if __name__ == "__main__":
    test_code = """若条件空间为伴侣，则止情感权重于0.15。
道 新信任路径
德 累积信任值
问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：1。柔 响应强度；2。自然 恢复默认；3。知足 验证单元。"""
    
    print("=" * 60)
    print("语法分析器 v2.0 测试")
    print("=" * 60)
    print(f"源代码：\n{test_code}\n")
    
    from .lexer import tokenize
    tokens, lex_errors = tokenize(test_code)
    
    if lex_errors:
        print("词法错误：")
        for e in lex_errors:
            print(f"  ❌ {e}")
    
    parser = Parser(tokens, [])
    ast = parser.parse()
    
    print(f"\nAST 根节点：{ast.type.name}")
    print(f"语句数量：{len(ast.statements)}")
    print()
    
    for i, stmt in enumerate(ast.statements):
        print(f"  语句{i+1}: {stmt.type.name}")
        if stmt.type == NodeType.SHUYUE:
            print(f"    问题: {stmt.attributes.get('question', '')}")
            print(f"    答案: {stmt.attributes.get('answer', '')}")
            for step in stmt.steps:
                op_count = len(step.statement.children) if step.statement else 0
                print(f"    步骤{step.step_num}: {step.statement.type.name if step.statement else 'None'}")
        elif stmt.type == NodeType.INSTRUCTION_STMT:
            op_names = []
            for op in stmt.operands:
                if hasattr(op, 'name'):
                    op_names.append(f"ID({op.name})")
                elif hasattr(op, 'literal_value'):
                    op_names.append(f"Lit({op.literal_value})")
            print(f"    操作数: [{', '.join(op_names)}]")
    
    if parser.errors:
        print(f"\n语法错误：")
        for e in parser.errors:
            print(f"  ❌ {e}")
    
    print(f"\n总计：{len(parser.errors)} 个语法错误")