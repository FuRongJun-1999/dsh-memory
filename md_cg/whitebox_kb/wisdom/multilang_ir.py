# -*- coding: utf-8 -*-
"""multilang_ir.py · 多语言代码理解（第五阶段·统一 IR 跨语言）
Python（ast 完整）+ JavaScript/Rust（轻量正则提取）→ 统一 IR
→ 复用 codegraph_white 调用图/影响分析（codegraph 38 语言矩阵的白箱零依赖版）。
诚实边界：JS/Rust 为轻量提取（light=True），非完整 AST。
"""
import sys
import re
sys.stdout.reconfigure(encoding='utf-8')
try:
    from codegraph_white import extract_code_ir
except ImportError:
    from .codegraph_white import extract_code_ir


def detect_language(source="", filename=""):
    """语言检测：扩展名优先，语法特征兜底"""
    if filename.endswith(".py"):
        return "python"
    if filename.endswith(".js") or filename.endswith(".mjs") or filename.endswith(".jsx"):
        return "javascript"
    if filename.endswith(".rs"):
        return "rust"
    if "fn " in source and "->" in source and "impl " in source:
        return "rust"
    if "function " in source or "=>" in source or "import " in source:
        return "javascript"
    if "def " in source:
        return "python"
    return "unknown"


# ============ JS/Rust 轻量提取（正则结构化，诚实标注） ============
_JS_KW = {"function", "if", "for", "while", "switch", "return", "const", "let",
          "var", "new", "typeof", "console", "import", "export", "from", "require",
          "async", "await", "class", "extends", "throw", "try", "catch", "else",
          "break", "continue", "do", "in", "of", "this", "super", "delete", "void"}
_RUST_KW = {"fn", "if", "for", "while", "match", "return", "let", "mut", "impl",
            "struct", "use", "println", "print", "vec", "String", "str", "Box",
            "Some", "None", "Ok", "Err", "self", "Self", "pub", "mod", "enum",
            "trait", "where", "loop", "break", "continue", "async", "await",
            "move", "ref", "static", "unsafe", "extern", "type", "const"}


def _calls_from(src, kws):
    """调用提取：\b(\w+)\( 匹配 → 过滤关键字（轻量，允许误抓）"""
    calls = [m.group(1) for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", src)]
    return sorted({c for c in calls if c not in kws})


def _extract_js(source, file_path):
    """JavaScript 轻量提取：function/箭头函数/class/import + 调用"""
    ir = {"file": file_path, "functions": [], "classes": [], "imports": [],
          "light": True}
    # 函数：function name( / const name = (args) => / name = function(
    for m in re.finditer(r"\bfunction\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", source):
        body = source[m.end():m.end() + 600]
        ir["functions"].append({"name": m.group(1),
                                "params": [p.strip() for p in m.group(2).split(",") if p.strip()],
                                "calls": _calls_from(body, _JS_KW), "class_owner": None})
    for m in re.finditer(r"\bconst\s+([A-Za-z_]\w*)\s*=\s*\(([^)]*)\)\s*=>", source):
        body = source[m.end():m.end() + 600]
        ir["functions"].append({"name": m.group(1),
                                "params": [p.strip() for p in m.group(2).split(",") if p.strip()],
                                "calls": _calls_from(body, _JS_KW), "class_owner": None})
    for m in re.finditer(r"\bclass\s+([A-Za-z_]\w*)", source):
        ir["classes"].append({"name": m.group(1), "methods": [], "bases": []})
    for m in re.finditer(r"\bimport\s+(?:{[^}]*}\s+from\s+)?['\"]([^'\"]+)['\"]", source):
        ir["imports"].append({"module": m.group(1).split("/")[-1].replace(".js", ""),
                              "names": []})
    return ir


def _extract_rust(source, file_path):
    """Rust 轻量提取：fn/struct/impl/use + 调用"""
    ir = {"file": file_path, "functions": [], "classes": [], "imports": [],
          "light": True}
    for m in re.finditer(r"\bfn\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", source):
        body = source[m.end():m.end() + 600]
        ir["functions"].append({"name": m.group(1),
                                "params": [p.strip().split(":")[0] for p in m.group(2).split(",") if p.strip()],
                                "calls": _calls_from(body, _RUST_KW), "class_owner": None})
    for m in re.finditer(r"\bstruct\s+([A-Za-z_]\w*)", source):
        ir["classes"].append({"name": m.group(1), "methods": [], "bases": []})
    for m in re.finditer(r"\buse\s+([A-Za-z_:]+)", source):
        ir["imports"].append({"module": m.group(1).split("::")[0], "names": []})
    return ir


def extract_ir(source, filename):
    """多语言 → 统一 IR（与 codegraph_white.extract_code_ir 同结构）"""
    lang = detect_language(source, filename)
    if lang == "python":
        ir = extract_code_ir(source, filename)
        ir["lang"] = "python"
        return ir
    if lang == "javascript":
        ir = _extract_js(source, filename)
        ir["lang"] = "javascript"
        return ir
    if lang == "rust":
        ir = _extract_rust(source, filename)
        ir["lang"] = "rust"
        return ir
    return {"file": filename, "functions": [], "classes": [], "imports": [],
            "lang": lang, "light": True}


if __name__ == "__main__":
    print("=== 多语言代码理解：统一 IR 跨语言（零 LLM）===\n")
    samples = {
        "sample.py": "def parse(data):\n    return split(data)\n\ndef split(d):\n    return d.split(',')\n",
        "sample.js": "import { fs } from 'fs'\n\nfunction parse(data) {\n    return split(data);\n}\n\nconst split = (d) => d.split(',');\n",
        "sample.rs": "use std::collections::HashMap;\n\nfn parse(data: &str) -> Vec<&str> {\n    split(data)\n}\n\nfn split(d: &str) -> Vec<&str> {\n    d.split(',').collect()\n}\n",
    }
    ok_all = True
    for fname, src in samples.items():
        ir = extract_ir(src, fname)
        fns = [f["name"] for f in ir["functions"]]
        print(f"[{fname}] lang={ir['lang']} light={ir.get('light', False)} "
              f"函数={fns} 导入={[i['module'] for i in ir['imports']]}")
        if "parse" not in fns:
            ok_all = False
    print(f"\n=== 判定 ===\n统一 IR 跨语言: {'✔ 三语言函数提取成立' if ok_all else '✘'}")
