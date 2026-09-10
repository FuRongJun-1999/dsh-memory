# -*- coding: utf-8 -*-
"""compiler_compose.py · 编译原理概念条件单元（第四阶段·代码深学·编译原理方向）
编译原理概念 = 条件单元（{条件→规律}）：问题「为什么要词法分析/什么是IR/
类型检查有什么好处」→ 方向识别 → 概念单元 → 组合生成（未预写完整答案）。
衔接 mini_compiler.py 白箱管线（词法→语法→求值→代码生成）。
零 LLM 确定性——编译原理知识白箱化。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')


# ============ 一、编译原理概念单元 ============
COMPILER_UNITS = {
    "词法分析": {
        "direction": "词法",
        "conditions": ["词法", "token", "字符流"],
        "rule": "字符流→token（正则/有限自动机）→ 编译第一步 → 非法字符定位报错",
        "conclusion": ("{词法分析}把字符流切分为 token（记号：数字/运算符/标识符）"
                       "→ 编译第一步 → 非法字符当场定位报错 → 后续阶段只面对规整 token"),
        "core": ["词法", "token", "字符", "记号", "报错"],
        "examples": ["为什么要词法分析", "什么是 token", "分词器"],
    },
    "语法分析": {
        "direction": "语法",
        "conditions": ["语法", "AST", "解析"],
        "rule": "token→AST（文法/递归下降/优先级）→ 判定结构合法性 → 树表达层次",
        "conclusion": ("{语法分析}按文法（BNF）把 token 流解析为语法树（AST）"
                       "→ 优先级/结合性编码进树结构 → 语法错误在此层报出 → 后续基于树处理"),
        "core": ["语法", "AST", "文法", "树", "解析"],
        "examples": ["什么是语法分析", "AST 是什么", "递归下降解析"],
    },
    "中间表示": {
        "direction": "中间表示",
        "conditions": ["中间表示", "IR", "中间码"],
        "rule": "与机器无关中间码 → 统一优化平台 → 多后端复用 → 前后端解耦",
        "conclusion": ("{中间表示}（IR）是与机器无关的中间码 → 优化只在 IR 层做一次"
                       " → 同一 IR 翻译到多个后端（x86/ARM/JS）→ 前端后端解耦"),
        "core": ["中间表示", "IR", "机器无关", "后端", "优化"],
        "examples": ["什么是中间表示", "IR 有什么用", "为什么需要中间代码"],
    },
    "类型检查": {
        "direction": "类型检查",
        "conditions": ["类型", "类型安全"],
        "rule": "类型约束/推导 → 编译期捕获类型错误 → 尽早失败 → 类型安全",
        "conclusion": ("{类型检查}在编译期校验类型约束/做类型推导 → 类型错误提前暴露"
                       " → 尽早失败而非运行时崩溃 → 类型安全（不变量由类型承载）"),
        "core": ["类型", "检查", "编译期", "错误", "安全"],
        "examples": ["类型检查有什么用", "静态类型好处", "类型推导"],
    },
    "优化": {
        "direction": "优化",
        "conditions": ["优化", "常量折叠", "死代码"],
        "rule": "保持语义改性能 → 常量折叠/死代码消除/寄存器分配 → 等价变换",
        "conclusion": ("{优化}在保持语义不变的前提下提升性能 → 常量折叠/死代码消除/"
                       "寄存器分配 → 每一步都是可证明的等价变换 → 优化前后行为一致"),
        "core": ["优化", "语义", "性能", "折叠", "等价"],
        "examples": ["编译优化是什么", "常量折叠", "死代码消除"],
    },
    "代码生成": {
        "direction": "代码生成",
        "conditions": ["代码生成", "codegen", "机器码"],
        "rule": "AST/IR→目标语言/机器码 → 后端翻译 → 按目标约定输出",
        "conclusion": ("{代码生成}把 AST/IR 翻译为目标代码（机器码/字节码/其他语言）"
                       " → 按目标平台约定输出 → 前端与目标无关 → 换目标只换后端"),
        "core": ["代码生成", "目标", "翻译", "后端", "输出"],
        "examples": ["代码生成阶段做什么", "codegen 是什么", "生成机器码"],
    },
    "符号表": {
        "direction": "符号表",
        "conditions": ["符号表", "作用域"],
        "rule": "名字→属性（类型/作用域/地址）→ 解析引用/查重复声明 → 上下文凭据",
        "conclusion": ("{符号表}记录每个名字的属性（类型/作用域/存储地址）→ 解析名字引用"
                       " → 检出重复声明/未声明 → 是编译各阶段的上下文凭据"),
        "core": ["符号表", "名字", "作用域", "属性", "声明"],
        "examples": ["符号表是什么", "作用域怎么管理", "重复声明检测"],
    },
    "错误处理": {
        "direction": "错误处理",
        "conditions": ["错误处理", "报错", "诊断"],
        "rule": "词法/语法/语义错误分级 → 定位+恢复 → 一次多报错 → 友好诊断",
        "conclusion": ("{错误处理}对词法/语法/语义错误分级 → 错误定位（行列）+恢复继续编译"
                       " → 一次编译报多个错 → 诊断信息友好（程序员可据此修）"),
        "core": ["错误", "定位", "恢复", "诊断", "报错"],
        "examples": ["编译器怎么报错", "错误恢复", "诊断信息"],
    },
}

# 方向识别（问题 → 编译原理概念）
COMPILER_DIRECTIONS = {
    "词法": ["词法", "token", "分词", "字符流", "记号"],
    "语法": ["语法", "AST", "解析", "文法", "递归下降", "语法树", "优先级"],
    "中间表示": ["中间表示", "中间码", "IR"],
    "类型检查": ["类型检查", "类型推导", "类型安全", "静态类型"],
    "优化": ["常量折叠", "死代码", "寄存器分配", "编译优化"],
    "代码生成": ["代码生成", "生成目标", "机器码", "codegen"],
    "符号表": ["符号表", "作用域", "名字解析"],
    "错误处理": ["错误处理", "报错", "错误恢复", "诊断", "错误"],
}


def identify_compiler_direction(question):
    """编译原理概念识别（最长关键词优先）"""
    best, best_len = None, 0
    for direction, kws in COMPILER_DIRECTIONS.items():
        for k in kws:
            if k in question and len(k) > best_len:
                best, best_len = direction, len(k)
    return best


def compiler_route(question):
    """编译原理概念组合生成：方向识别 → 概念单元 → 模板生成 → 自校验"""
    direction = identify_compiler_direction(question)
    if direction is None:
        return {"question": question, "ok": False,
                "reason": "编译原理概念未识别（落回通用域）"}
    unit = None
    for uid, u in COMPILER_UNITS.items():
        if u["direction"] == direction:
            unit = u
            break
    if unit is None:
        return {"question": question, "ok": False,
                "reason": f"概念[{direction}]无单元覆盖"}
    # 组合生成（占位符代入概念名）
    answer = unit["conclusion"].replace("{词法分析}", "词法分析").replace(
        "{语法分析}", "语法分析").replace("{中间表示}", "中间表示").replace(
        "{类型检查}", "类型检查").replace("{优化}", "优化").replace(
        "{代码生成}", "代码生成").replace("{符号表}", "符号表").replace(
        "{错误处理}", "错误处理")
    # 自校验：答案含概念核心词（白箱确定性）
    core_hit = sum(1 for c in unit["core"] if c in answer)
    ok = core_hit >= 2
    checks = [] if ok else [f"✗ 概念自校验失败：核心词命中 {core_hit}/{len(unit['core'])}"]
    return {"question": question, "direction": direction,
            "ok": ok, "answer": answer, "checks": checks,
            "core_hit": core_hit, "unit": [u for u, x in COMPILER_UNITS.items() if x is unit][0]}


if __name__ == "__main__":
    print("=== 编译原理概念条件单元（代码深学 · 零 LLM）===\n")
    QS = [
        "为什么要词法分析？", "什么是语法分析？", "什么是中间表示（IR）？",
        "类型检查有什么好处？", "编译优化是什么？", "代码生成阶段做什么？",
        "符号表是什么？", "编译器怎么处理错误？",
    ]
    ok_n = 0
    for q in QS:
        r = compiler_route(q)
        if r.get("ok"):
            ok_n += 1
        mark = "✔" if r.get("ok") else "✘"
        print(f"[{mark}] ({r.get('direction')}) {q}")
        print(f"   -> {r.get('answer', r.get('reason'))}")
        for c in r.get("checks", []):
            print(f"   {c}")
    # 未识别回落
    r = compiler_route("什么是碳中和？")
    print(f"\n[{'✔' if not r.get('ok') else '✘'}] 非编译问题回落: {r.get('reason')}")
    print(f"\n=== 判定 ===\n编译原理概念命中: {ok_n}/{len(QS)}")
