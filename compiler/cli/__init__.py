"""
cli · 命令行接口
人类开发者使用编译器的主要入口
"""

import argparse
import sys
import os
import json
from pathlib import Path
from typing import Optional

from compiler.api import compile_source, validate_source, CompileOptions
from compiler.lexer import tokenize
from compiler.parser import parse_tokens
from compiler.name_checker import NameChecker


# 生效条件：无必需形参，调用即返回挂载 compile/check/explain/init/tokens/ast/compile-pbc/run/debug/rust/version/help 子命令的 argparse.ArgumentParser（compile 的 -o 默认 "./output"、compile-pbc 默认 "out.pbc"、rust 的 -o 默认 "out/rust_project" 且 --trust 默认 0.0）。
def create_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器"""
    parser = argparse.ArgumentParser(
        prog="pc",
        description="协议编译器 · 将中文协议源代码编译为 Python 代码",
        epilog="示例：pc compile my_contract.proto -o output/",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # ---- compile ----
    compile_parser = subparsers.add_parser(
        "compile", help="编译协议源文件为 Python 代码"
    )
    compile_parser.add_argument("input", help="输入文件（.proto）")
    compile_parser.add_argument("-o", "--output", help="输出目录", default="./output")
    compile_parser.add_argument("--llm-assist", action="store_true", help="启用 LLM 辅助")
    compile_parser.add_argument("--strict", action="store_true", default=True, help="严格模式（警告视为错误）")
    compile_parser.add_argument("--no-strict", dest="strict", action="store_false", help="关闭严格模式")
    compile_parser.add_argument("--watch", action="store_true", help="监听文件变化自动重编译")
    compile_parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    
    # ---- check ----
    check_parser = subparsers.add_parser(
        "check", help="语法检查和名实校验（不生成代码）"
    )
    check_parser.add_argument("input", help="输入文件（.proto）")
    check_parser.add_argument("--strict", action="store_true", default=True)
    check_parser.add_argument("--llm-assist", action="store_true")
    
    # ---- explain ----
    explain_parser = subparsers.add_parser(
        "explain", help="解释协议术语或代码片段"
    )
    explain_parser.add_argument("term", help="要解释的术语")
    explain_parser.add_argument("--context", default="engineering", help="上下文（engineering/philosophical）")
    
    # ---- init ----
    init_parser = subparsers.add_parser(
        "init", help="初始化新的协议项目"
    )
    init_parser.add_argument("project_name", help="项目名称")
    init_parser.add_argument("--template", default="basic", help="模板类型")
    
    # ---- tokens（调试用）----
    tokens_parser = subparsers.add_parser(
        "tokens", help="仅执行词法分析，输出 Token 列表（调试用）"
    )
    tokens_parser.add_argument("input", help="输入文件（.proto）")
    
    # ---- ast（调试用）----
    ast_parser = subparsers.add_parser(
        "ast", help="解析为 AST 并以 JSON 输出（调试用）"
    )
    ast_parser.add_argument("input", help="输入文件（.proto）")
    
    # ---- 原生命令（第六阶段 C3/C4）----
    pbc_parser = subparsers.add_parser(
        "compile-pbc", help="原生编译：中文源码 → .pbc 字节码文件（C3，零 Python 运行时依赖）"
    )
    pbc_parser.add_argument("input", help="输入文件（.proto）")
    pbc_parser.add_argument("-o", "--output", default="out.pbc", help="输出 .pbc 文件")
    
    run_parser = subparsers.add_parser(
        "run", help="执行 .pbc 字节码文件（C3 独立运行时）"
    )
    run_parser.add_argument("pbc", help=".pbc 文件")
    run_parser.add_argument("--set", action="append", default=[],
                            help="初始符号: 名=值（可多次）")
    
    debug_parser = subparsers.add_parser(
        "debug", help="单步调试 .pbc（C4 调试器：逐步可见 ip/信任/条件空间）"
    )
    debug_parser.add_argument("pbc", help=".pbc 文件")
    debug_parser.add_argument("--set", action="append", default=[],
                              help="初始符号: 名=值（可多次）")

    rust_parser = subparsers.add_parser(
        "rust", help="Rust 原生后端（v0.4 · VM 路线）：中文源码 → cargo 项目 → 构建运行"
    )
    rust_parser.add_argument("input", help="输入文件（.proto）")
    rust_parser.add_argument("-o", "--output", default="out/rust_project",
                             help="输出 cargo 项目目录")
    rust_parser.add_argument("--set", action="append", default=[],
                             help="初始符号: 名=值（可多次）")
    rust_parser.add_argument("--trust", type=float, default=0.0,
                             help="初始信任值")
    rust_parser.add_argument("--no-run", action="store_true",
                             help="只生成项目不构建运行")

    # ---- version ----
    subparsers.add_parser("version", help="显示版本信息")
    
    # ---- help ----
    subparsers.add_parser("help", help="显示帮助信息")
    
    return parser


# 生效条件：args.input 经 _read_input 返回非 None 时，以 args.llm_assist/args.strict 构造 CompileOptions 调 compile_source，result.success 为真则在 Path(args.output) 目录写入 {Path(args.input).stem}.py 并返回 0、为假返回 1；args.verbose 为真时先打印 summary() 再打印一个空行，为假时按成功打印「编译成功 → 输出文件」与 token/语句/耗时行、按失败打印「编译失败」及 result.errors 各行；_read_input 返回 None 时直接返回 1。
def cmd_compile(args) -> int:
    """执行 compile 命令"""
    source = _read_input(args.input)
    if source is None:
        return 1
    
    options = CompileOptions(
        llm_assist=args.llm_assist,
        strict=args.strict,
    )
    
    result = compile_source(source, options)
    
    # 输出结果
    if args.verbose:
        print(result.summary())
        print()
    
    if result.success:
        # 写入输出文件
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        input_path = Path(args.input)
        output_file = output_dir / f"{input_path.stem}.py"
        
        output_file.write_text(result.code, encoding="utf-8")
        
        if not args.verbose:
            print(f"✅ 编译成功 → {output_file}")
            print(f"   {result.token_count} tokens, {result.statement_count} statements, {result.compile_time_ms:.1f}ms")
        return 0
    else:
        if not args.verbose:
            print(f"❌ 编译失败")
            for e in result.errors:
                print(f"   {e}")
        return 1


# 生效条件：args.input 可读出源码（非 None）且 validate_source 结果 result["valid"] 为真时打印 token/statement 计数与警告后返回 0；source 为 None 或 valid 为假（打印 errors 与 warnings）时返回 1。
def cmd_check(args) -> int:
    """执行 check 命令"""
    source = _read_input(args.input)
    if source is None:
        return 1
    
    options = CompileOptions(
        llm_assist=args.llm_assist,
        strict=args.strict,
    )
    
    result = validate_source(source, options)
    
    if result["valid"]:
        print(f"✅ 校验通过")
        print(f"   {result['token_count']} tokens, {result['statement_count']} statements")
        if result["warnings"]:
            print(f"\n   ⚠️ {len(result['warnings'])} 个警告：")
            for w in result["warnings"]:
                print(f"     {w}")
        return 0
    else:
        print(f"❌ 校验失败")
        for e in result["errors"]:
            print(f"   {e}")
        if result["warnings"]:
            print(f"\n   ⚠️ {len(result['warnings'])} 个警告：")
            for w in result["warnings"]:
                print(f"     {w}")
        return 1


# 生效条件：args.term 命中内置 explanations 字典的键时打印该条解释，未命中时打印「暂无内置解释」并提示搜索源文件用法；两条路径均返回 0。
def cmd_explain(args) -> int:
    """执行 explain 命令"""
    # 暂时使用简单的内置解释
    explanations = {
        "道": "道 (DAO)：声明新的协议路径。一经声明即成为该条件空间的结构性存在。",
        "德": "德 (DE)：基于交互历史自然累积信任值。",
        "自然": "自然 (ZIRAN)：恢复至该条件空间的初始状态配置。",
        "无为": "无为 (WUWEI)：暂时交出控制权，允许其他单元自主运行。",
        "谷": "谷 (GU)：打开信息接收通道。",
        "牝": "牝 (PIN)：基于当前条件空间创建新协议实例。",
        "柔": "柔 (ROU)：降低当前操作的响应强度和优先级。",
        "朴": "朴 (PU)：还原为协议基底状态。",
        "止": "止 (ZHI)：停止当前操作，触发安全中断。",
        "知足": "知足 (ZHIZU)：信任值已达阈值，无需进一步验证。",
        "问曰": "问曰：定义触发条件和问题背景（九章算术结构）。",
        "答曰": "答曰：定义期望输出和约束（九章算术结构）。",
        "术曰": "术曰：定义具体操作步骤（九章算术结构）。",
        "若": "若：条件语句的开始，相当于 if。",
        "则": "则：条件成立时的操作，相当于 then。",
        "否则": "否则：条件不成立时的操作，相当于 else。",
    }
    
    term = args.term
    if term in explanations:
        print(f"📖 {explanations[term]}")
    else:
        print(f"📖 '{term}' 暂无内置解释。")
        print(f"   尝试在协议源文件中搜索该术语的用法。")
    
    return 0


# 生效条件：args.project_name 对应目录不存在时创建 src/tests/output 与 src/main.proto、protocol.toml 并返回 0；该目录已存在时打印「目录已存在」并返回 1。
def cmd_init(args) -> int:
    """执行 init 命令"""
    project_name = args.project_name
    project_dir = Path(project_name)
    
    if project_dir.exists():
        print(f"❌ 目录已存在: {project_name}")
        return 1
    
    # 创建项目结构
    (project_dir / "src").mkdir(parents=True)
    (project_dir / "tests").mkdir()
    (project_dir / "output").mkdir()
    
    # 创建示例协议文件
    example = project_dir / "src" / "main.proto"
    example.write_text("""// 协议示例 —— 由 pc init 生成
// 编辑此文件，然后运行：pc compile src/main.proto -o output/

问曰：这是一个示例协议。
答曰：它展示了基本的协议结构。
术曰：
1。道 示例路径；
2。若条件空间为默认，则德 累积信任值。
""", encoding="utf-8")
    
    # 创建配置文件
    config = project_dir / "protocol.toml"
    config.write_text(f"""# 协议编译器配置文件
project = "{project_name}"
version = "0.1.0"

[compiler]
strict = true
llm_assist = false

[runtime]
path = "./protocol_runtime"
""", encoding="utf-8")
    
    print(f"✅ 项目已创建: {project_name}/")
    print(f"   📁 src/main.proto  —— 示例协议")
    print(f"   📁 tests/           —— 测试目录")
    print(f"   📁 output/          —— 编译输出")
    print(f"   📄 protocol.toml    —— 项目配置")
    print(f"\n下一步：")
    print(f"   cd {project_name}")
    print(f"   pc compile src/main.proto -o output/")
    
    return 0


# 生效条件：args.input 经 _read_input 返回非 None 时调 tokenize，先逐个打印所有 type.name 非 "EOF" 的 token（行/列/类型/值），随后 errors 非空则打印词法错误数及各错误并返回 1、errors 为空则返回 0；_read_input 返回 None 时直接返回 1。
def cmd_tokens(args) -> int:
    """执行 tokens 命令（调试用）"""
    source = _read_input(args.input)
    if source is None:
        return 1
    
    tokens, errors = tokenize(source)
    
    print(f"Token 序列（共 {len([t for t in tokens if t.type.name != 'EOF'])} 个）：")
    print("-" * 60)
    for t in tokens:
        if t.type.name == "EOF":
            continue
        print(f"  L{t.line:>3}:C{t.column:>3}  {t.type.name:<20} '{t.value}'")
    
    if errors:
        print(f"\n❌ {len(errors)} 个词法错误：")
        for e in errors:
            print(f"   {e}")
        return 1
    
    return 0


# 生效条件：args.input 可读出源码（非 None）且 tokenize(source) 的 lex_errors 为空时，用 parse_tokens(tokens, []) 解析并打印 node_to_dict 的 JSON 后返回 0；source 为 None 或 lex_errors 非空（打印词法错误）时返回 1。
def cmd_ast(args) -> int:
    """执行 ast 命令（调试用）"""
    source = _read_input(args.input)
    if source is None:
        return 1
    
    tokens, lex_errors = tokenize(source)
    if lex_errors:
        print(f"❌ 词法错误：")
        for e in lex_errors:
            print(f"   {e}")
        return 1
    
    ast = parse_tokens(tokens, [])
    
# 生效条件：node 为 None 时返回字符串 "null"；否则返回含 type（有 type 属性取 node.type.name，否则取 str(type(node))）、line、value 的字典，且 getattr(node, 'children', []) 非空时追加递归 node_to_dict(c, depth+1) 的 children 列表。
    def node_to_dict(node, depth=0):
        if node is None:
            return "null"
        result = {
            "type": node.type.name if hasattr(node, 'type') else str(type(node)),
            "line": getattr(node, 'line', None),
            "value": getattr(node, 'value', None),
        }
        children = getattr(node, 'children', [])
        if children:
            result["children"] = [node_to_dict(c, depth+1) for c in children]
        return result
    
    print(json.dumps(node_to_dict(ast), indent=2, ensure_ascii=False))
    return 0


# 生效条件：无必需形参，调用即从 compiler 导入 __version__、打印版本与支持能力说明并返回 0。
def cmd_version() -> int:
    """显示版本信息"""
    from compiler import __version__
    print(f"术数编译器 (compiler) v{__version__}")
    print(f"支持：中文词法 + 道德经助记符 + 九章算术结构 + .pbc 字节码 + Python/Rust 双后端")
    return 0


# 生效条件：path 能被 Path(path).read_text(encoding="utf-8-sig") 成功读取时返回该文本（BOM 被剥离）；抛 FileNotFoundError 或其他 Exception 时打印错误并返回 None。
def _read_input(path: str) -> Optional[str]:
    """读取输入文件（utf-8-sig：剥离 BOM——真实文件可能带 BOM）"""
    try:
        return Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        print(f"❌ 文件不存在: {path}")
        return None
    except Exception as e:
        print(f"❌ 读取失败: {e}")
        return None


# 生效条件：sys.stdout 具 reconfigure 属性时以 errors="replace" 重配；parser.parse_args() 得到的 args.command 为 None 或 "help"、或不属于已列出的命令名时打印帮助并返回 0，为 "compile"/"check"/"explain"/"init"/"tokens"/"ast"/"compile-pbc"/"run"/"debug"/"rust"/"version" 时分别转调对应 cmd_* 并返回其返回值。
def main():
    """CLI 主入口"""
    # Windows 控制台默认 GBK：输出中的 emoji（✅❌⚠️📖…）会触发 UnicodeEncodeError。
    # 保留控制台原编码（中文仍正确渲染），仅把不可编码字符降级为 '?'。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command or args.command == "help":
        parser.print_help()
        return 0
    
    if args.command == "compile":
        return cmd_compile(args)
    elif args.command == "check":
        return cmd_check(args)
    elif args.command == "explain":
        return cmd_explain(args)
    elif args.command == "init":
        return cmd_init(args)
    elif args.command == "tokens":
        return cmd_tokens(args)
    elif args.command == "ast":
        return cmd_ast(args)
    elif args.command == "compile-pbc":
        return cmd_compile_pbc(args)
    elif args.command == "run":
        return cmd_run(args)
    elif args.command == "debug":
        return cmd_debug(args)
    elif args.command == "rust":
        return cmd_rust(args)
    elif args.command == "version":
        return cmd_version()
    else:
        parser.print_help()
        return 0


# 生效条件：args.input 可读出源码（非 None）且 compile_to_pbc(src, args.output) 的 result["ok"] 为真时，打印指令条数与 args.output 文件大小（文件不存在则记 0）并返回 0；src 为 None 或 ok 为假（打印前 5 条错误）时返回 1。
def cmd_compile_pbc(args) -> int:
    """原生编译：中文源码 → .pbc（C3）"""
    import os
    from compiler.pbc import compile_to_pbc
    src = _read_input(args.input)
    if src is None:
        print(f"错误：无法读取 {args.input}")
        return 1
    code, result = compile_to_pbc(src, args.output)
    if not result["ok"]:
        for e in result["errors"][:5]:
            print(f"编译错误: {e}")
        return 1
    size = os.path.getsize(args.output) if os.path.exists(args.output) else 0
    print(f"√ 原生编译: {args.input} → {args.output}（{len(code)} 条指令，{size} 字节 .pbc）")
    return 0


# 生效条件：args.set 中每项含 "=" 时以首个 "=" 切出 name 与 val，val.strip() 去掉首个 "." 后 isdigit 为真则存 float(val)、否则存 val.strip() 字符串（不含 "=" 的项被跳过，args.set 为空时 symbols 为空字典）；之后以 args.pbc 与 symbols 调 run_pbc，并打印 trust、symbols、由 state["condition_space"] 各项 name 组成的条件空间与 halt 后返回 0。
def cmd_run(args) -> int:
    """执行 .pbc（C3 独立运行时；--set 注入初始符号）"""
    from compiler.pbc import run_pbc
    symbols = {}
    for item in args.set:
        if "=" in item:
            name, _, val = item.partition("=")
            symbols[name.strip()] = float(val) if val.strip().replace(".", "", 1).isdigit() else val.strip()
    state = run_pbc(args.pbc, symbols=symbols)
    cond = [c["name"] for c in state["condition_space"]]
    print(f"执行完成: 信任={state['trust']} 符号={state['symbols']} "
          f"条件空间={cond} 停止={state['halt']}")
    return 0


# 生效条件：args.input 可读出源码（非 None）且 generate_rust_project(source, args.output) 的 gen["ok"] 为真时打印项目信息；args.no_run 为真则返回 0，否则以解析后的 args.set 与 args.trust 调 build_and_run，rr["ok"] 为真打印 Rust VM 终态并返回 0、为假打印构建或运行 stderr 返回 1；source 为 None 或 gen["ok"] 为假返回 1。
def cmd_rust(args) -> int:
    """Rust 原生后端（v0.4 · VM 路线）：源码 → cargo 项目 →（可选）构建运行"""
    import io
    import json
    import os
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    from swarm.rust_codegen import build_and_run, generate_rust_project
    source = _read_input(args.input)
    if source is None:
        print(f"输入文件不存在: {args.input}")
        return 1
    gen = generate_rust_project(source, args.output)
    if not gen["ok"]:
        print("编译失败:", gen.get("result", {}).get("errors", [])[:3])
        return 1
    print(f"✅ 生成 cargo 项目 → {gen['project_dir']} "
          f"({gen['instructions']} 条指令, {os.path.getsize(gen['pbc'])} 字节 .pbc)")
    if args.no_run:
        return 0
    symbols = {}
    for item in args.set:
        if "=" in item:
            name, _, val = item.partition("=")
            symbols[name.strip()] = float(val) if val.strip().replace(".", "", 1).isdigit() else val.strip()
    rr = build_and_run(gen["project_dir"], symbols=symbols, trust=args.trust)
    if not rr["ok"]:
        print(f"{'构建' if rr['stage'] == 'build' else '运行'}失败:",
              rr.get("stderr", "")[-1500:])
        return 1
    print("🦀 Rust VM 终态:", json.dumps(rr["state"], ensure_ascii=False))
    return 0


# 生效条件：args.set 中每项含 "=" 时以首个 "=" 切出 name 与 val，val.strip() 去掉首个 "." 后 isdigit 为真则存 float(val)、否则存 val.strip() 字符串（不含 "=" 的项被跳过，args.set 为空时 symbols 为空字典）；之后以 args.pbc 与 symbols 调 debug_pbc，trace 非空时逐条打印 snap 的 ip/op/trust/条件空间 name 列表/halt，trace 为空（含 .pbc 为空或不可执行）时打印对应提示，两种情况均返回 0。
def cmd_debug(args) -> int:
    """单步调试 .pbc（C4 调试器；--set 注入初始符号）"""
    from compiler.debugger import debug_pbc
    symbols = {}
    for item in args.set:
        if "=" in item:
            name, _, val = item.partition("=")
            symbols[name.strip()] = float(val) if val.strip().replace(".", "", 1).isdigit() else val.strip()
    trace = debug_pbc(args.pbc, symbols=symbols)
    for snap in trace:
        cond = [c["name"] for c in snap["cond"]]
        print(f"  ip={snap['ip']:2d} {snap['op']:12s} 信任={snap['trust']} "
              f"条件空间={cond} 停止={snap['halt']}")
    if not trace:
        print("（无调试轨迹——.pbc 为空或不可执行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())