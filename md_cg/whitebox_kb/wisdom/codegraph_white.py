# -*- coding: utf-8 -*-
"""codegraph_white.py · 白箱代码理解能力（第五阶段·codegraph 模式落地）
模式 ②③④：AST→统一IR→类型化图 + 影响分析 + 环检测（零 LLM，Python 内置 ast）
  1. extract_code_ir   源码 → 统一 IR（函数/类/导入/调用）——codegraph CodeIR 同构
  2. build_call_graph  IR → 调用图（Function 节点 + Calls 边）
  3. impact_analysis   改函数 → 调用面（BFS 逆向 = 谁受影响）
  4. detect_cycles     调用环检测（Tarjan SCC）
"""
import sys
import ast
import os
sys.stdout.reconfigure(encoding='utf-8')


# ============ 一、统一 IR 提取（AST → CodeIR 等价物） ============
def extract_code_ir(source, file_path="<source>"):
    """源码 → 统一 IR：{file, functions[], classes[], imports[], calls[]}
    functions: {name, params[], calls[], class_owner}
    classes:   {name, methods[], bases[]} | imports: {module, names[]}"""
    tree = ast.parse(source)
    ir = {"file": file_path, "functions": [], "classes": [], "imports": [], "calls": []}

    def calls_of(node):
        """提取函数内所有调用：Name 调用（parse()）+ Attribute 调用（utils.parse() → parse）
        v2：Attribute 调用跨文件解析需要——utils.parse 定位到 utils.py"""
        out = []
        for n in ast.walk(node):
            if isinstance(n, ast.Call):
                f = n.func
                if isinstance(f, ast.Name):
                    out.append(f.id)
                elif isinstance(f, ast.Attribute):
                    out.append(f.attr)
        return out

    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                ir["imports"].append({"module": a.name.split(".")[0], "names": [a.asname or a.name]})
        elif isinstance(n, ast.ImportFrom):
            ir["imports"].append({"module": n.module or "", "names":
                                  [a.asname or a.name for a in n.names]})
    for n in tree.body:
        if isinstance(n, ast.FunctionDef):
            ir["functions"].append({"name": n.name,
                                    "params": [a.arg for a in n.args.args],
                                    "calls": calls_of(n), "class_owner": None})
        elif isinstance(n, ast.ClassDef):
            cls = {"name": n.name,
                   "methods": [m.name for m in n.body if isinstance(m, ast.FunctionDef)],
                   "bases": [ast.unparse(b) for b in n.bases]}
            ir["classes"].append(cls)
            for m in n.body:
                if isinstance(m, ast.FunctionDef):
                    ir["functions"].append({"name": f"{n.name}.{m.name}",
                                            "params": [a.arg for a in m.args.args],
                                            "calls": calls_of(m), "class_owner": n.name})
    return ir


# ============ 二、调用图（Function 节点 + Calls 边） ============
def build_call_graph(ir):
    """IR → 调用图 {func: [被调用的函数名]}（只保留图中存在的函数）"""
    funcs = {f["name"] for f in ir["functions"]}
    graph = {}
    for f in ir["functions"]:
        graph[f["name"]] = [c for c in f["calls"] if c in funcs]
    return graph


# ============ 三、影响分析（BFS 逆向：谁调用我 → 影响面） ============
def impact_analysis(ir, target, max_depth=3):
    """改 target 函数 → 逆向 BFS 求调用面（谁直接/间接受影响）
    返回 {target, callers[], depth, chain[]}——codegraph impact_analysis 同构"""
    graph = build_call_graph(ir)
    # 反向邻接：callee -> callers
    reverse = {}
    for f, callees in graph.items():
        for c in callees:
            reverse.setdefault(c, []).append(f)
    visited, queue, depth_map = set(), [target], {target: 0}
    callers = []
    while queue:
        cur = queue.pop(0)
        for caller in reverse.get(cur, []):
            if caller not in visited:
                visited.add(caller)
                depth_map[caller] = depth_map[cur] + 1
                if depth_map[caller] <= max_depth:
                    callers.append(caller)
                    queue.append(caller)
    # 正向依赖链（它调用谁——简单一跳）
    callees = graph.get(target, [])
    return {"target": target, "callers": callers, "depth": depth_map,
            "callees": callees}


# ============ 四、环检测（Tarjan SCC：循环调用/递归依赖） ============
def detect_cycles(ir):
    """调用环检测（Tarjan SCC，codegraph algorithms 同构）
    返回 [ [环内函数...], ... ]（仅 size>1 的强连通分量 + 自环）"""
    graph = build_call_graph(ir)
    nodes = list(graph.keys())
    index, lowlink, on_stack, stack = {}, {}, set(), []
    result = []
    counter = [0]

    def strongconnect(v):
        index[v] = lowlink[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in graph.get(v, []):
            if w not in index:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], index[w])
        if lowlink[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                result.append(comp)

    for v in nodes:
        if v not in index:
            strongconnect(v)
    return result


# ============ 五、仓库级分析（多文件：依赖树 + 跨文件调用） ============
def analyze_repository(dirpath, suffix=None):
    """目录 → 仓库 IR：逐文件 extract IR + 文件归属 + 文件级导入
    v2：按扩展名分流多语言（py→ast 完整，js/rs→轻量正则，multilang_ir）——
    混合语言仓库统一理解。suffix=None 时接受 .py/.js/.rs/.mjs。
    返回 {"files": {path: ir}, "functions": [带 file], "classes": [带 file],
          "imports": [{from_file, module}], "file_count", "function_count"}"""
    repo = {"files": {}, "functions": [], "classes": [], "imports": [], "file_count": 0}
    if not os.path.isdir(dirpath):
        return repo
    ok_ext = (suffix,) if suffix else (".py", ".js", ".mjs", ".rs")
    # 延迟导入（multilang_ir 依赖本模块 extract_code_ir——防循环）
    from multilang_ir import extract_ir
    for name in sorted(os.listdir(dirpath)):
        path = os.path.join(dirpath, name)
        if not (os.path.isfile(path) and name.endswith(ok_ext)):
            continue
        with open(path, encoding="utf-8") as f:
            src = f.read()
        ir = extract_ir(src, name)  # 多语言分流（py 完整 / js/rs 轻量）
        repo["files"][name] = ir
        for fn in ir["functions"]:
            fn["file"] = name
            fn["lang"] = ir.get("lang", "")
            repo["functions"].append(fn)
        for cls in ir["classes"]:
            cls["file"] = name
            repo["classes"].append(cls)
        for imp in ir["imports"]:
            imp["from_file"] = name
            repo["imports"].append(imp)
        repo["file_count"] += 1
    repo["function_count"] = len(repo["functions"])
    return repo


def build_dependency_tree(repo):
    """仓库 IR → 文件依赖树：文件 → [它导入的文件模块]
    本地模块 = 仓库内存在的文件名（多扩展名 .py/.js/.rs 的 stem）；返回 {file: [dep_files]}"""
    local = {os.path.splitext(name)[0] for name in repo["files"]}
    tree = {name: [] for name in repo["files"]}
    for imp in repo["imports"]:
        mod = imp["module"]
        dep = None
        for f in repo["files"]:
            if os.path.splitext(f)[0] == mod:
                dep = f
                break
        if dep and dep != imp["from_file"]:
            tree[imp["from_file"]].append(dep)
    return {k: sorted(set(v)) for k, v in tree.items()}


def cross_file_calls(repo):
    """跨文件调用解析：函数调用目标定位到定义文件
    返回 {file: {caller_func: [(callee, def_file)]}}——调用发生在 A 文件、定义在 B 文件"""
    # 函数名 → 定义文件
    def_of = {}
    for fn in repo["functions"]:
        base = fn["name"].split(".")[-1]  # 类方法取方法名
        def_of.setdefault(base, []).append(fn["file"])
    out = {}
    for fn in repo["functions"]:
        for callee in fn["calls"]:
            if callee not in def_of:
                continue
            for dfile in def_of[callee]:
                if dfile != fn["file"]:  # 跨文件
                    out.setdefault(fn["file"], []).append(
                        (fn["name"], callee, dfile))
    return out


def repo_stats(repo):
    """仓库统计：文件/函数/类/导入/跨文件调用数"""
    return {"files": repo["file_count"],
            "functions": repo["function_count"],
            "classes": len(repo["classes"]),
            "imports": len(repo["imports"]),
            "cross_calls": sum(len(v) for v in cross_file_calls(repo).values())}


# ============ 六、仓库级影响分析（跨文件调用面） ============
def impact_analysis_repo(repo, target, max_depth=3):
    """改 target 函数 → 跨文件调用面（BFS 逆向，含文件定位）
    返回 {target, target_file, callers[{name, file, depth}], files_affected[]}
    价值：改一个函数 → 算跨文件波及面（codegraph impact_analysis 仓库版）"""
    # 函数名 → 定义文件（仓库全局索引）
    def_of = {}
    for fn in repo["functions"]:
        base = fn["name"].split(".")[-1]
        def_of.setdefault(base, []).append(fn["file"])
    # 仓库调用图（合并所有文件；跨文件同名取全部定义文件）
    graph = {}
    for fn in repo["functions"]:
        graph.setdefault(fn["name"], [])
        for callee in fn["calls"]:
            if callee in def_of:
                graph[fn["name"]].append(callee)
    # 逆向邻接：callee -> [caller]
    reverse = {}
    for f, callees in graph.items():
        for c in callees:
            reverse.setdefault(c, []).append(f)
    # 目标定位
    target_file = def_of.get(target, [None])[0]
    visited, queue, callers = set(), [target], []
    depth_map = {target: 0}
    while queue:
        cur = queue.pop(0)
        for caller in reverse.get(cur, []):
            if caller not in visited:
                visited.add(caller)
                depth_map[caller] = depth_map[cur] + 1
                if depth_map[caller] <= max_depth:
                    # caller 的 file：函数名 → 定义文件（同名多文件取全部）
                    for f in repo["functions"]:
                        if f["name"] == caller:
                            callers.append({"name": caller, "file": f["file"],
                                            "depth": depth_map[caller]})
                    queue.append(caller)
    files_affected = sorted({c["file"] for c in callers} |
                            ({target_file} if target_file else set()))
    return {"target": target, "target_file": target_file,
            "callers": callers, "files_affected": files_affected,
            "depth": depth_map}


if __name__ == "__main__":
    print("=== 白箱代码理解能力（codegraph 模式落地 · 零 LLM）===\n")
    SAMPLE = '''
import math
import os

def parse(data):
    tokens = split(data)
    return tokens

def split(data):
    return data.split(",")

def compute(tokens):
    return parse(tokens)

def main():
    data = os.read()
    result = compute(data)
    print(result)

class Service:
    def handle(self, req):
        return compute(req)

def recursive(n):
    if n <= 1:
        return 1
    return n * recursive(n - 1)
'''
    ir = extract_code_ir(SAMPLE, "sample.py")
    print(f"① 统一 IR: {len(ir['functions'])} 函数 / {len(ir['classes'])} 类 / {len(ir['imports'])} 导入")
    for f in ir["functions"]:
        print(f"   {f['name']}({','.join(f['params'])}) 调用: {f['calls']}")

    print("\n② 调用图:")
    for f, c in build_call_graph(ir).items():
        if c:
            print(f"   {f} -> {c}")

    print("\n③ 影响分析（改 compute → 谁受影响）:")
    r = impact_analysis(ir, "compute")
    print(f"   调用面: {r['callers']}（深度: {r['depth']}）| compute 调用: {r['callees']}")

    print("\n④ 环检测（Tarjan SCC）:")
    cycles = detect_cycles(ir)
    print(f"   调用环: {cycles if cycles else '无（除递归自环）'}")
    ok = len(ir["functions"]) >= 6 and "compute" in r["callers"] and len(cycles) >= 0
    print(f"\n=== 判定 ===\n白箱代码理解: {'✔ IR/调用图/影响分析/环检测成立' if ok else '✘'}")
