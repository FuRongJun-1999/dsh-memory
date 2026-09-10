# -*- coding: utf-8 -*-
"""code_route_bridge.py · 代码图↔条件路由图双向映射（第五阶段·代码库=条件单元库）
函数 = 条件单元（被调函数 = 条件依赖）→ 条件代数雅可比独立性判定 →
并行测试分组（独立函数并行测试，共享依赖串行防冲突）。
价值：compose_parallel 的并行化能力应用到代码测试（零 LLM 确定性）。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')


def build_code_route_units(repo):
    """仓库 IR → 代码条件单元库（与 compose_engine.CONDITION_UNITS 同构）
    每函数一个单元：{name, conditions:[被调函数], rule, domain: 文件}"""
    units = {}
    for fn in repo["functions"]:
        callees = sorted(set(fn.get("calls", [])))
        units[fn["name"]] = {
            "conditions": callees,
            "rule": f"执行 {fn['name']} 需要其依赖成立 → 依赖: {callees}",
            "domain": fn.get("file", ""),
            "lang": fn.get("lang", ""),
        }
    return units


def code_jacobian_independence(units):
    """单元库 → 雅可比独立性（两函数无共享依赖 → 独立可并行测试）
    返回 {pairs: [(f1, f2, independent)], conds_of: {func: [依赖]}}"""
    conds_of = {name: u["conditions"] for name, u in units.items()}
    names = sorted(units.keys())
    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            shared = set(conds_of[a]) & set(conds_of[b])
            pairs.append((a, b, not shared, sorted(shared)))
    return {"pairs": pairs, "conds_of": conds_of}


def parallel_test_groups(units):
    """独立性 → 并行测试分组（贪心并组，同 compose_parallel 逻辑）：
    无共享依赖的函数并组并行，共享依赖隔离串行"""
    conds_of = {name: u["conditions"] for name, u in units.items()}
    names = sorted(units.keys())
    groups, used = [], [False] * len(names)
    for i in range(len(names)):
        if used[i]:
            continue
        group, used[i] = [names[i]], True
        for j in range(i + 1, len(names)):
            if used[j]:
                continue
            shared = set(conds_of[names[i]]) & set(conds_of[names[j]])
            if not shared:
                group.append(names[j])
                used[j] = True
        groups.append(group)
    return groups


if __name__ == "__main__":
    print("=== 代码图↔条件路由图：代码库 = 条件单元库（零 LLM）===\n")
    import sys as _sys, os, tempfile
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from codegraph_white import analyze_repository

    tmp = tempfile.mkdtemp(prefix="code_route_")
    with open(os.path.join(tmp, "lib.py"), "w", encoding="utf-8") as f:
        f.write("def base(x):\n    return x\n\ndef a():\n    return base(1)\n"
                "\ndef b():\n    return base(2)\n\ndef c():\n    return a()\n")
    repo = analyze_repository(tmp)
    units = build_code_route_units(repo)
    print("① 代码条件单元库（函数=单元，被调=条件）：")
    for name, u in sorted(units.items()):
        print(f"   {name} 依赖={u['conditions']} 域={u['domain']}")

    j = code_jacobian_independence(units)
    print("\n② 雅可比独立性（无共享依赖 → 可并行测试）：")
    for a, b, indep, shared in j["pairs"]:
        mark = "独立" if indep else f"共享依赖{shared}"
        print(f"   {a} × {b}: {mark}")

    groups = parallel_test_groups(units)
    print(f"\n③ 并行测试分组: {groups}")
    print(f"   （组内独立可并行，组间串行——同 compose_parallel 逻辑）")
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    ok = any(len(g) >= 2 for g in groups)
    print(f"\n=== 判定 ===\n并行测试分组: "
          f"{'✔ 独立函数并组成立（代码库=条件单元库）' if ok else '✘'}")
