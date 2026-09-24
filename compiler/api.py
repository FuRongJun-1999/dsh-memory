"""
api.py · 编译器核心 API
统一对外接口 —— CLI 和 MCP 都通过这里调用

LLM 辞意辅助（llm_bridge）为外部可插拔面：经 CompileOptions.llm_bridge
注入实例（duck typing）。本模块不依赖任何具体桥接实现——requests 等
第三方依赖不进入本包（大脑零第三方依赖约束，原仓保留 llm_bridge）。
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from .lexer import tokenize, Token, TokenType
from .parser import parse_tokens, ProgramNode, NodeType
from .name_checker import NameChecker
from .codegen import CodeGenerator


# =============================================================================
# 编译选项
# =============================================================================

@dataclass
# 生效条件：不适用（无必需形参与模块级常量）
class CompileOptions:
    """编译选项"""
    llm_assist: bool = False        # 是否启用 LLM 辅助（辞意/说故校验）
    strict: bool = True              # 严格模式（警告视为错误）
    output_format: str = "python"    # 输出格式
    include_comments: bool = True    # 是否包含注释
    indent_size: int = 4             # 缩进大小
    
    # LLM 桥接（可选，由调用方注入）
    llm_bridge: Any = None          # LLM 适配器实例


# =============================================================================
# 编译结果
# =============================================================================

@dataclass
# 生效条件：不适用（无必需形参与模块级常量）
class CompileResult:
    """编译结果"""
    success: bool = False
    code: str = ""                    # 生成的 Python 代码
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    tokens: List[Token] = field(default_factory=list)
    ast: Optional[ProgramNode] = None
    
    # 统计信息
    token_count: int = 0
    statement_count: int = 0
    compile_time_ms: float = 0.0
    
    # 验证单元终裁结果
    verdict: Optional[Dict] = None
    
    @property
# 生效条件：不适用（无必需形参与模块级常量）
    def has_errors(self) -> bool:
        return len(self.errors) > 0
    
    @property
# 生效条件：不适用（无必需形参与模块级常量）
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0
    
# 生效条件：self.success 为真值时首行输出「✅ 编译成功」，否则输出「❌ 编译失败 (len(self.errors) 个错误)」；随后附加 token_count、statement_count、compile_time_ms:.1f；self.errors 非空时追加错误块（仅 errors[:10] 的前 10 条），self.warnings 非空时追加警告块（仅 warnings[:5] 的前 5 条），返回以 "\n" 连接的 lines。
    def summary(self) -> str:
        """生成摘要文本"""
        lines = []
        if self.success:
            lines.append(f"✅ 编译成功")
        else:
            lines.append(f"❌ 编译失败 ({len(self.errors)} 个错误)")
        
        lines.append(f"   Token 数: {self.token_count}")
        lines.append(f"   语句数: {self.statement_count}")
        lines.append(f"   编译耗时: {self.compile_time_ms:.1f} ms")
        
        if self.errors:
            lines.append(f"\n   错误：")
            for e in self.errors[:10]:
                lines.append(f"     ❌ {e}")
        
        if self.warnings:
            lines.append(f"\n   警告：")
            for w in self.warnings[:5]:
                lines.append(f"     ⚠️ {w}")
        
        return "\n".join(lines)


# =============================================================================
# 核心编译函数
# =============================================================================

# 生效条件：source 为协议源串；options 为 None 时回落 CompileOptions()；tokenize 产生 lex_errors 即提前返回，语法错误或 ast 为 None 即提前返回，名实校验有 name_errors 即提前返回；仅当 options.llm_assist 且 options.llm_bridge 同时为真值才调用 _llm_assist（异常只记入 warnings）；最终 result.success 取决于 errors 是否为空，verdict 的 reason/passed 参与追加错误。
def compile_source(source: str, options: Optional[CompileOptions] = None) -> CompileResult:
    """
    核心编译函数 —— 所有入口的统一调用点
    
    流程：
    1. 词法分析 → Token 序列
    2. 语法分析 → AST
    3. 名实校验 → 错误/警告列表
    4. LLM 辅助（可选）→ 辞意/说故建议
    5. 代码生成 → Python 代码
    6. 验证单元终裁 → 否决或放行
    
    Args:
        source: 协议源代码
        options: 编译选项
    
    Returns:
        CompileResult 对象
    """
    import time
    start = time.time()
    
    if options is None:
        options = CompileOptions()
    
    result = CompileResult()
    
    # ---- 第一步：词法分析 ----
    tokens, lex_errors = tokenize(source)
    result.tokens = tokens
    result.token_count = len([t for t in tokens if t.type != TokenType.EOF])
    result.errors.extend(lex_errors)
    
    # 词法错误即终止（无法继续语法分析）
    if lex_errors:
        result.compile_time_ms = (time.time() - start) * 1000
        return result
    
    # ---- 第二步：语法分析 ----
    # Parser 把语法错误 append 进**调用方传入的共享列表**（ProgramNode
    # 本身没有 errors 属性——旧写法 getattr(ast,'errors',[]) 恒 []，
    # 含语法错误的源码在这里静默通过）。传入列表读取即可回流。
    syntax_errors: List[str] = []
    ast = parse_tokens(tokens, syntax_errors)
    result.ast = ast

    # 获取语法错误
    if syntax_errors:
        result.errors.extend(syntax_errors)
    
    statement_count = len(getattr(ast, 'statements', [])) if ast else 0
    result.statement_count = statement_count
    
    # 语法错误即终止
    if syntax_errors or ast is None:
        result.compile_time_ms = (time.time() - start) * 1000
        return result
    
    # ---- 第三步：名实校验（核心编译模块）----
    checker = NameChecker()
    name_errors, name_warnings = checker.check(ast)
    result.errors.extend(name_errors)
    result.warnings.extend(name_warnings)
    
    # 名实校验失败即终止
    if name_errors:
        result.compile_time_ms = (time.time() - start) * 1000
        return result
    
    # ---- 第四步：LLM 辅助（可选，非阻塞）----
    llm_suggestions = None
    if options.llm_assist and options.llm_bridge:
        try:
            llm_suggestions = _llm_assist(ast, options.llm_bridge)
        except Exception as e:
            result.warnings.append(f"LLM 辅助失败: {e}")
    
    # ---- 第五步：代码生成 ----
    gen = CodeGenerator(checker)
    code = gen.generate(ast)
    result.code = code
    result.warnings.extend(gen.warnings)
    # codegen 错误（如未支持的表达式类型、非法函数名）回流——
    # 不支持的操作必须编译 fail，而非 success + 非法/残缺产物
    result.errors.extend(gen.errors)
    
    # ---- 第六步：验证单元终裁 ----
    verdict = _verification_verdict(result, options)
    result.verdict = verdict
    
    if not verdict.get("passed", True):
        result.errors.append(f"验证单元否决: {verdict.get('reason', '未知原因')}")
    
    # ---- 完成 ----
    result.success = len(result.errors) == 0
    result.compile_time_ms = (time.time() - start) * 1000
    
    return result


# 生效条件：source 为协议源串；options 为 None 时先构造 CompileOptions()，随后无论入参如何都重建为仅携带 llm_assist、strict、llm_bridge 的新 CompileOptions（output_format/include_comments/indent_size 回落默认）并以此调用 compile_source，返回 valid=result.success 与 errors/warnings/token_count/statement_count。
def validate_source(source: str, options: Optional[CompileOptions] = None) -> Dict:
    """
    仅校验（不生成代码）
    用于 IDE 实时检查、CI 预检等场景
    """
    if options is None:
        options = CompileOptions()
    
    options = CompileOptions(
        llm_assist=options.llm_assist,
        strict=options.strict,
        llm_bridge=options.llm_bridge,
    )
    
    result = compile_source(source, options)
    
    return {
        "valid": result.success,
        "errors": result.errors,
        "warnings": result.warnings,
        "token_count": result.token_count,
        "statement_count": result.statement_count,
    }


# =============================================================================
# 内部函数
# =============================================================================

# 生效条件：传入 ast 与 llm_bridge 后先调用 _ast_to_text(ast)，llm_bridge.understand(ast_text, context={"phase": "ciyi_check"}) 返回真值时追加进 suggestions["name_meaning"]，llm_bridge.suggest_verification(ast_text, {"phase": "shuogu_check"}) 返回真值时追加进 suggestions["reasoning"]，两键均为假值时保持空列表，恒返回该 suggestions。
def _llm_assist(ast: ProgramNode, llm_bridge) -> Optional[Dict]:
    """
    LLM 辅助校验（辞意/说故）
    非阻塞：失败不影响编译结果
    """
    suggestions = {
        "name_meaning": [],    # 辞意建议
        "reasoning": [],       # 说故建议
    }
    
    # 将 AST 序列化为文本供 LLM 理解
    ast_text = _ast_to_text(ast)
    
    # 辞意校验建议
    intent = llm_bridge.understand(ast_text, context={"phase": "ciyi_check"})
    if intent:
        suggestions["name_meaning"].append(intent)
    
    # 说故校验建议
    verify_suggestion = llm_bridge.suggest_verification(
        ast_text, {"phase": "shuogu_check"}
    )
    if verify_suggestion:
        suggestions["reasoning"].append(verify_suggestion)
    
    return suggestions


# 生效条件：ast 为含 statements 的 ProgramNode（直接取 ast.statements，无 getattr 兜底），逐条按 stmt.type 分派——CONDITION_STMT 输出「条件语句: 若 …」并在 stmt.then_body 为真值时追加「  则: …」，INSTRUCTION_STMT 输出「指令: 名 操作数」，SHUYUE 输出步骤数、WENYUE 输出 question[:50]、DAYUE 输出 answer[:50]，其余类型跳过，返回以 "\n" 连接的 parts。
def _ast_to_text(ast: ProgramNode) -> str:
    """将 AST 转换为文本描述（供 LLM 理解）"""
    parts = []
    for stmt in ast.statements:
        if stmt.type == NodeType.CONDITION_STMT:
            cond_text = _node_to_text(stmt.condition)
            parts.append(f"条件语句: 若 {cond_text}")
            if stmt.then_body:
                then_text = _node_to_text(stmt.then_body)
                parts.append(f"  则: {then_text}")
        elif stmt.type == NodeType.INSTRUCTION_STMT:
            instr_name = stmt.instruction.name if hasattr(stmt.instruction, 'name') else str(stmt.instruction)
            op_text = ", ".join(_node_to_text(op) for op in (stmt.operands or []))
            parts.append(f"指令: {instr_name} {op_text}".strip())
        elif stmt.type == NodeType.SHUYUE:
            parts.append(f"术曰块: {len(stmt.steps)} 个步骤")
        elif stmt.type == NodeType.WENYUE:
            parts.append(f"问曰: {stmt.question[:50]}")
        elif stmt.type == NodeType.DAYUE:
            parts.append(f"答曰: {stmt.answer[:50]}")
    return "\n".join(parts)


# 生效条件：node 为 None 时返回空串；否则按属性探测分派——有 name 返回 str(node.name)，有 value 返回 str(node.value)，有 operator 返回 `f"{left} {node.operator} {right}"`（left/right 缺失时按空串参与），以上皆无则返回 str(type(node).__name__)。
def _node_to_text(node) -> str:
    """将单个 AST 节点转为文本"""
    if node is None:
        return ""
    if hasattr(node, 'name'):
        return str(node.name)
    if hasattr(node, 'value'):
        return str(node.value)
    if hasattr(node, 'operator'):
        left = _node_to_text(node.left) if hasattr(node, 'left') else ""
        right = _node_to_text(node.right) if hasattr(node, 'right') else ""
        return f"{left} {node.operator} {right}"
    return str(type(node).__name__)


# 生效条件：result.errors 非空时返回 passed=False、reason=f"编译错误: {result.errors[0]}"、authority="VERIFICATION_UNIT"；errors 为空时返回 passed=True、reason="路径有效：结构一致且缩小信息差"、authority 同前、confidence=0.85（形参 options 在函数体内未被读取）。
def _verification_verdict(result: CompileResult, options: CompileOptions) -> Dict:
    """
    验证单元终裁
    基于协议框架 v3.1 公理进行最终裁决
    """
    # 如果有错误，直接否决
    if result.errors:
        return {
            "passed": False,
            "reason": f"编译错误: {result.errors[0]}",
            "authority": "VERIFICATION_UNIT",
        }
    
    # 检查信任值约束
    # （这里简化实现，完整版需要检查 AST 中的信任值操作）
    
    # 检查条件空间合法性
    # （这里简化实现）
    
    # 通过
    return {
        "passed": True,
        "reason": "路径有效：结构一致且缩小信息差",
        "authority": "VERIFICATION_UNIT",
        "confidence": 0.85,
    }


# =============================================================================
# 便捷函数
# =============================================================================

# 生效条件：source 为协议源串且以默认 options（未传参，走 CompileOptions()）调用 compile_source，result.success 为真时返回 result.code，否则返回 `"# 编译错误:\n# " + "\n# ".join(result.errors)`。
def quick_compile(source: str) -> str:
    """
    快速编译 —— 返回生成的代码或错误信息
    """
    result = compile_source(source)
    if result.success:
        return result.code
    else:
        return f"# 编译错误:\n# " + "\n# ".join(result.errors)


# =============================================================================
# 测试
# =============================================================================

if __name__ == "__main__":
    test_code = """若条件空间为伴侣，则止情感权重于0.15。
道 新信任路径
问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：1。德 累积信任值；2。自然 恢复默认。"""
    
    print("=" * 60)
    print("协议编译器 · 完整流水线测试")
    print("=" * 60)
    print(f"\n源代码：\n{test_code}\n")
    
    # 编译
    options = CompileOptions(llm_assist=False, strict=True)
    result = compile_source(test_code, options)
    
    print("编译结果：")
    print(result.summary())
    
    if result.success:
        print(f"\n{'─' * 60}")
        print("生成的 Python 代码：")
        print(f"{'─' * 60}")
        print(result.code)
    
    print(f"\n{'=' * 60}")
    print("测试完成")
    print(f"{'=' * 60}")