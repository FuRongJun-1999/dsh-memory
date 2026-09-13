"""
analyzer.py · 分析器（第六阶段 C4）：字节码可读转储
中文源码/.pbc → 可读指令列表（地址+指令+参数）——开发者工具链。
"""


def bytecode_dump(code):
    """字节码（枚举/字符串 op）→ 可读指令列表"""
    lines = []
    for i, (op, arg) in enumerate(code):
        name = op.name if hasattr(op, "name") else str(op)
        lines.append(f"{i:4d}  {name:14s} {arg}")
    return lines


def analyze_source(source, strict=False):
    """中文源码 → 字节码转储（分析器入口）"""
    from .compiler import compile_source
    code, result = compile_source(source, strict=strict)
    if not result["ok"]:
        return None, result
    return bytecode_dump(code), result


def analyze_pbc(path):
    """.pbc 文件 → 字节码转储"""
    from .pbc import load_pbc
    return bytecode_dump(load_pbc(path))


if __name__ == "__main__":
    print("=== C4：分析器（字节码可读转储）===\n")
    src = """术曰：
1。道 新信任路径；
2。德 0.3；
3。止。
"""
    lines, r = analyze_source(src)
    if r["ok"]:
        for ln in lines:
            print(f"  {ln}")
        print(f"\n=== 判定 ===\n分析器: {'✔ 字节码可读转储' if lines else '✘'}")


# ============ T11 · 分析器完整化（F3 符号表 / F4 调用图 / F5 数据流） ============

def _walk(node, out):
    """递归收集 AST 节点（children 与已知子节点字段）"""
    if node is None:
        return
    out.append(node)
    for k in ("children", "body", "then_body", "else_body",
              "statements", "left", "right", "value_node", "value"):
        v = getattr(node, k, None)
        if v is None:
            continue
        items = v if isinstance(v, list) else [v]
        for item in items:
            if hasattr(item, "type"):
                _walk(item, out)
    args = getattr(node, "args", None)
    if args:
        for a in args:
            if hasattr(a, "type"):
                _walk(a, out)


def symbol_table(ast) -> dict:
    """F3 符号表转储：变量（赋值目标+函数参数）与函数签名完整视图。

    生效条件：ast 为 ProgramNode
    子功能：① 收集赋值目标变量 ② 收集函数名与参数 ③ 类型推断（数值/文本）
    执行：递归遍历 + 类型推断（字面量数值→number、引号→string）
    不适用条件：宏/元编程结构不在静态分析范围
    """
    symbols = {"variables": {}, "functions": {}}

    def infer(node):
        v = getattr(node, "literal_value", None)
        if isinstance(v, (int, float)):
            return "number"
        if isinstance(v, str):
            return "string"
        return "unknown"

    def visit(node):
        if node is None:
            return
        t = getattr(node, "type", None)
        nt = t.name if t is not None else ""
        if nt == "FUNC_DEF":
            params = getattr(node, "params", []) or []
            symbols["functions"][getattr(node, "name", "")] = {
                "params": params}
        elif nt == "ASSIGN_STMT":
            target = getattr(node, "target", "")
            val = getattr(node, "value_node", None)
            vtype = infer(val) if val is not None else "unknown"
            symbols["variables"][target] = vtype
        for k in ("children", "body", "then_body", "else_body",
                  "left", "right", "value_node", "value"):
            v = getattr(node, k, None)
            if hasattr(v, "type"):
                visit(v)
            elif isinstance(v, list):
                for item in v:
                    if hasattr(item, "type"):
                        visit(item)

    visit(ast)
    return symbols


def call_graph(ast) -> dict:
    """F4 调用图：函数名 → [被调用的函数名]（含主程序段调用）。"""
    graph = {}

    def visit(node, current):
        if node is None:
            return
        t = getattr(node, "type", None)
        nt = t.name if t is not None else ""
        if nt == "FUNC_DEF":
            current = getattr(node, "name", "")
            graph.setdefault(current, [])
        if nt == "CALL_EXPR":
            callee = getattr(node, "name", "")
            if current and callee not in graph.setdefault(current, []):
                graph[current].append(callee)
        for k in ("children", "body", "then_body", "else_body",
                  "left", "right", "value_node", "value"):
            v = getattr(node, k, None)
            if hasattr(v, "type"):
                visit(v, current)
            elif isinstance(v, list):
                for item in v:
                    if hasattr(item, "type"):
                        visit(item, current)

    visit(ast, None)
    return graph


def def_use_chains(ast) -> dict:
    """F5 数据流：变量 → {'def': 次数, 'use': 次数}（定义-使用链统计）。"""
    chains = {}

    def visit(node):
        if node is None:
            return
        t = getattr(node, "type", None)
        nt = t.name if t is not None else ""
        if nt == "ASSIGN_STMT":
            target = getattr(node, "target", "")
            if target:
                chains.setdefault(target, {"def": 0, "use": 0})
                chains[target]["def"] += 1
        if nt == "IDENTIFIER":
            name = getattr(node, "value", "")
            if name:
                chains.setdefault(name, {"def": 0, "use": 0})
                chains[name]["use"] += 1
        for k in ("children", "body", "then_body", "else_body",
                  "left", "right", "value_node", "value"):
            v = getattr(node, k, None)
            if hasattr(v, "type"):
                visit(v)
            elif isinstance(v, list):
                for item in v:
                    if hasattr(item, "type"):
                        visit(item)

    visit(ast)
    return chains


def full_analysis(ast) -> dict:
    """三合一：F3 符号表 + F4 调用图 + F5 数据流。"""
    return {"symbol_table": symbol_table(ast),
            "call_graph": call_graph(ast),
            "def_use_chains": def_use_chains(ast)}
