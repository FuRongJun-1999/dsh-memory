# -*- coding: utf-8 -*-
"""compiler · 术数编译器（灵枢大脑核心内部能力）。

自 protocol-compiler 迁入（v0.6.2，2026-09-13 荣裁定：编译器并入大脑作为核心
能力——中文编译为 Python/Rust 双后端 + 编译期安全校验）。零第三方依赖
（stdlib only，对齐 md_cg D-005）。

编译管线（编译期安全防护，全部确定性组件，任一环失败即拒绝产出）：
  1. 词法分析   lexer.py        → Token 序列（错误即终止）
  2. 语法分析   parser.py       → AST（错误即终止）
  3. 名实校验   name_checker.py → 以名举实：符号表 + 指令操作数约束（错误即终止）
  4. 代码生成   codegen.py      → Python 代码（白名单式翻译：固定算子映射 + 固定模板）
  5. 验证终裁   api.py          → 否决或放行（verification 终裁）
  字节码面     compiler.py → .pbc（pbc.py 序列化；condition_vm.py 确定性封闭指令集执行）
  工具面       analyzer.py（可读转储/符号表/调用图/def-use 链）+ debugger.py（VM 单步）
  用户入口     cli/（compile/check/compile-pbc/run/debug/rust 等）

用法：
  from compiler import compile_source
  result = compile_source("术曰：1。德 累积信任值。")
  python -m compiler.cli compile main.proto -o output/

双后端分工：
  Python 后端  codegen.py → 可读 Python 代码（依赖 protocol_runtime 时降级模拟实现）
  Rust 后端   swarm.rust_codegen → cargo 项目（protocol_vm，纯 std 零依赖）

诚实边界：
  - 编译校验防错误程序与语义漂移（名实不符）；封闭指令集 + 白名单翻译
    结构性排除任意代码注入；不提供对抗性 fuzz。
  - LLM 辞意辅助为外部可插拔面（CompileOptions.llm_bridge 注入，duck typing），
    大脑侧默认不启用；llm_bridge/protocol_prompt 留在 protocol-compiler 原仓。
  - 与蜂群正交：compiler=实例编程面（编译），swarm=多智能体执行面（运行）。
"""
__version__ = "0.6.2"

# 词法/语法/校验
from .lexer import tokenize, Token, TokenType
from .parser import parse_tokens, ProgramNode
from .name_checker import NameChecker

# 字节码面（确定性封闭指令集）
from .condition_vm import ConditionVM, Opcode, VMResourceError
from .compiler import compile_source as compile_to_bytecode
from .pbc import (serialize, deserialize, compile_to_pbc,
                  save_pbc, load_pbc, run_pbc)

# Python 后端 + 统一管线
from .codegen import CodeGenerator
from .api import compile_source, validate_source, CompileOptions, CompileResult

# 工具面
from .analyzer import bytecode_dump, analyze_source, analyze_pbc
from .debugger import VMDebugger, debug_pbc

__all__ = [
    # 词法/语法/校验
    "tokenize", "Token", "TokenType",
    "parse_tokens", "ProgramNode",
    "NameChecker",
    # 字节码面
    "ConditionVM", "Opcode", "VMResourceError",
    "compile_to_bytecode",
    "serialize", "deserialize", "compile_to_pbc", "save_pbc", "load_pbc", "run_pbc",
    # Python 后端 + 统一管线
    "CodeGenerator",
    "compile_source", "validate_source", "CompileOptions", "CompileResult",
    # 工具面
    "bytecode_dump", "analyze_source", "analyze_pbc",
    "VMDebugger", "debug_pbc",
]
