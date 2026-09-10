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
    
    def add_child(self, child: 'ASTNode'):
        """追加子节点（None 直接忽略）。"""
        if child is not None:
            self.children.append(child)
    
    def __repr__(self) -> str:
        """AST 节点调试表示：类型与子节点概览。"""
        return f"ASTNode({self.type.name}, value={self.value!r}, children={len(self.children)})"


@dataclass
class ProgramNode(ASTNode):
    """程序根节点"""
    def __init__(self, line: int = 1, column: int = 1):
        """构造 ProgramNode：绑定本节点的声明字段与子结构。"""
        super().__init__(NodeType.PROGRAM, line, column)
        self.statements: List[ASTNode] = []
    
    def add_statement(self, stmt: ASTNode):
        """追加语句并同时挂入子树。"""
        if stmt is not None:
            self.statements.append(stmt)
            self.add_child(stmt)


@dataclass
class WenyueNode(ASTNode):
    """问曰节点"""
    def __init__(self, question: str, line: int = 1, column: int = 1):
        """构造 WenyueNode：绑定本节点的声明字段与子结构。"""
        super().__init__(NodeType.WENYUE, line, column)
        self.question = question
        self.value = question


@dataclass
class DayueNode(ASTNode):
    """答曰节点"""
    def __init__(self, answer: str, line: int = 1, column: int = 1):
        """构造 DayueNode：绑定本节点的声明字段与子结构。"""
        super().__init__(NodeType.DAYUE, line, column)
        self.answer = answer
        self.value = answer


@dataclass
class ShuyueNode(ASTNode):
    """术曰节点"""
    def __init__(self, line: int = 1, column: int = 1):
        """构造 ShuyueNode：绑定本节点的声明字段与子结构。"""
        super().__init__(NodeType.SHUYUE, line, column)
        self.steps: List['StepNode'] = []
    
    def add_step(self, step: 'StepNode'):
        """追加步骤节点并挂入子树。"""
        self.steps.append(step)
        self.add_child(step)


@dataclass
class StepNode(ASTNode):
    """步骤节点"""
    def __init__(self, step_num: int, statement: ASTNode, line: int = 1, column: int = 1):
        """构造 StepNode：绑定本节点的声明字段与子结构。"""
        super().__init__(NodeType.STEP, line, column)
        self.step_num = step_num
        self.statement = statement
        self.add_child(statement)


@dataclass
class ConditionStmtNode(ASTNode):
    """条件语句：若 [条件] 则 [操作] [否则 [操作]]（body 可为语句列表）"""
    def __init__(self, condition: ASTNode, then_body, else_body=None,
                 line: int = 1, column: int = 1):
        """构造 ConditionStmtNode：绑定本节点的声明字段与子结构。"""
        super().__init__(NodeType.CONDITION_STMT, line, column)
        self.condition = condition
        self.then_body = then_body
        self.else_body = else_body
        self.add_child(condition)
        self.add_child(then_body)
        if else_body is not None:
            self.add_child(else_body)


@dataclass
class LoopStmtNode(ASTNode):
    """循环语句：当 [条件] 执行 [操作]（while 语义，body 可为语句列表）"""
    def __init__(self, condition: ASTNode, body, line: int = 1, column: int = 1):
        """构造 LoopStmtNode：绑定本节点的声明字段与子结构。"""
        super().__init__(NodeType.LOOP_STMT, line, column)
        self.condition = condition
        self.body = body
        self.add_child(condition)
        self.add_child(body)


@dataclass
class BlockNode(ASTNode):
    """语句块：多条顺序执行的语句（循环体/条件体多语句支持）"""
    def __init__(self, statements, line: int = 1, column: int = 1):
        """构造 BlockNode：绑定本节点的声明字段与子结构。"""
        super().__init__(NodeType.BLOCK, line, column)
        self.statements = statements
        for s in statements:
            self.add_child(s)


@dataclass
class FuncDefNode(ASTNode):
    """函数定义：定义 名（参数）：语句（body 可为语句列表）"""
    def __init__(self, name: str, params: List[str], body, line: int = 1, column: int = 1):
        """构造 FuncDefNode：绑定本节点的声明字段与子结构。"""
        super().__init__(NodeType.FUNC_DEF, line, column)
        self.name = name
        self.params = params
        self.body = body
        self.add_child(body)


@dataclass
class ReturnStmtNode(ASTNode):
    """返回语句：返回 [表达式]"""
    def __init__(self, value: Optional[ASTNode], line: int = 1, column: int = 1):
        """构造 ReturnStmtNode：绑定本节点的声明字段与子结构。"""
        super().__init__(NodeType.RETURN_STMT, line, column)
        self.value = value
        if value:
            self.add_child(value)


@dataclass
class CallExprNode(ASTNode):
    """函数调用：名（参数1，参数2）"""
    def __init__(self, name: str, args: List[ASTNode], line: int = 1, column: int = 1):
        """构造 CallExprNode：绑定本节点的声明字段与子结构。"""
        super().__init__(NodeType.CALL_EXPR, line, column)
        self.name = name
        self.args = args
        for a in args:
            self.add_child(a)


@dataclass
class InstructionStmtNode(ASTNode):
    """指令语句：道德经助记符 + 操作数"""
    def __init__(self, instruction: TokenType, operands: List[ASTNode] = None,
                 line: int = 1, column: int = 1):
        """构造 InstructionStmtNode：绑定本节点的声明字段与子结构。"""
        super().__init__(NodeType.INSTRUCTION_STMT, line, column)
        self.instruction = instruction
        self.operands = operands or []
        for op in self.operands:
            self.add_child(op)


@dataclass
class AssignStmtNode(ASTNode):
    """赋值语句：标识符 = 值"""
    def __init__(self, target: str, value: ASTNode, line: int = 1, column: int = 1):
        """构造 AssignStmtNode：绑定本节点的声明字段与子结构。"""
        super().__init__(NodeType.ASSIGN_STMT, line, column)
        self.target = target
        self.value_node = value
        self.add_child(value)


@dataclass
class BinaryExprNode(ASTNode):
    """二元表达式：左 操作符 右"""
    def __init__(self, left: ASTNode, operator: str, right: ASTNode,
                 line: int = 1, column: int = 1):
        """构造 BinaryExprNode：绑定本节点的声明字段与子结构。"""
        super().__init__(NodeType.BINARY_EXPR, line, column)
        self.left = left
        self.operator = operator
        self.right = right
        self.add_child(left)
        self.add_child(right)


@dataclass
class ComparisonNode(ASTNode):
    """比较表达式"""
    def __init__(self, left: ASTNode, op: str, right: ASTNode,
                 line: int = 1, column: int = 1):
        """构造 ComparisonNode：绑定本节点的声明字段与子结构。"""
        super().__init__(NodeType.COMPARISON, line, column)
        self.left = left
        self.op = op
        self.right = right
        self.add_child(left)
        self.add_child(right)


@dataclass
class IdentifierNode(ASTNode):
    """标识符"""
    def __init__(self, name: str, line: int = 1, column: int = 1):
        """构造 IdentifierNode：绑定本节点的声明字段与子结构。"""
        super().__init__(NodeType.IDENTIFIER, line, column)
        self.name = name
        self.value = name


@dataclass
class LiteralNode(ASTNode):
    """字面量"""
    def __init__(self, value: Union[str, float, int], literal_type: str,
                 line: int = 1, column: int = 1):
        """构造 LiteralNode：绑定本节点的声明字段与子结构。"""
        super().__init__(NodeType.LITERAL, line, column)
        self.literal_value = value
        self.literal_type = literal_type  # "number", "string"
        self.value = value


# =============================================================================
# 语法分析器
# =============================================================================

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
    
    def __init__(self, tokens: List[Token], errors: List[str] = None):
        """构造 Parser：绑定本节点的声明字段与子结构。"""
        self.tokens = tokens
        self.pos = 0
        self.errors: List[str] = errors or []
        self.current_token = self.tokens[0] if tokens else None
    
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
            # 可能是单个标识符或合并后的多词短语
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
    
    def _parse_func_def(self) -> Optional[ASTNode]:
        """解析函数定义：定义 名（参数1，参数2）：语句
        参数在（ ）内，逗号分隔；返回 FuncDefNode（body 可为块）"""
        start_line = self.current_token.line if self.current_token else 1
        start_col = self.current_token.column if self.current_token else 1
        
        self._consume(TokenType.DINGYI, "期望 '定义'")
        
        # 函数名（标识符）
        if not (self.current_token and self.current_token.type == TokenType.IDENTIFIER):
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
    
    def _parse_statement_or_block(self) -> Any:
        """解析语句或块：返回语句列表（单语句=[stmt]；分号/句号分隔多条）
        块内多条语句：`则 语句1；语句2；...`（支持循环体/条件体多语句）"""
        stmts = []
        while True:
            stmt = self._parse_single_statement()
            if stmt is not None:
                stmts.append(stmt)
            # 分隔符：分号/句号 → 继续收下一条；否则块结束
            if self.current_token and self.current_token.type in (
                    TokenType.SEMICOLON, TokenType.PERIOD, TokenType.COMMA):
                self._advance()
                # 分隔符后若是步骤号/块边界 → 块结束（九章算术步骤边界 1。…2。…）
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
    
    def _is_at_end(self) -> bool:
        """指针越界探测：True=已消费全部 token。"""
        return self.pos >= len(self.tokens) or (
            self.current_token is not None and self.current_token.type == TokenType.EOF
        )
    
    def _advance(self) -> Optional[Token]:
        """消费当前 token 并前进一格。"""
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
            self.current_token = self.tokens[self.pos]
        elif self.pos == len(self.tokens) - 1:
            self.pos += 1
            self.current_token = None
        return self.current_token

    def _peek_next(self) -> Optional[Token]:
        """查看下一个 token（不消费）"""
        if self.pos < len(self.tokens) - 1:
            return self.tokens[self.pos + 1]
        return None
    
    def _match(self, *types: TokenType) -> bool:
        """类型相符即消费返回 True，否则 False。"""
        if self.current_token and self.current_token.type in types:
            self._advance()
            return True
        return False
    
    def _consume(self, token_type: TokenType, message: str) -> Optional[Token]:
        """消费当前 token：类型相符即前进返回，否则带行列定位报错。"""
        if self.current_token and self.current_token.type == token_type:
            token = self.current_token
            self._advance()
            return token
        else:
            loc = f"L{self.current_token.line}:C{self.current_token.column}" if self.current_token else "EOF"
            self.errors.append(f"{loc} {message}，实际得到: '{self.current_token.value if self.current_token else 'EOF'}'")
            return None
    
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

def parse_tokens(tokens: List[Token], errors: List[str] = None) -> ProgramNode:
    """便捷函数：将 Token 列表解析为 AST"""
    parser = Parser(tokens, errors or [])
    return parser.parse()


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
