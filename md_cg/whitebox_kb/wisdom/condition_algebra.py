# -*- coding: utf-8 -*-
"""condition_algebra.py · 条件代数工程化 v1——影响雅可比图（用户确认「开始吧」）
理论：《条件函数与条件代数》（GPT 最终方向）——条件路由图 = 离散化影响雅可比结构
落地：
  ① 条件单元库 → 影响雅可比矩阵 J[knowledge][condition] = ∂knowledge/∂condition
  ② 条件独立性检测：两条件共享知识 → 相关（不可并行）；无共享 → 独立（组合可并行）
     —— 混合偏导 ∂²f/∂x∂y=0 的图判定（组合引擎并行化的数学基础）
  ③ 链式法则传播：条件 → 知识 → 条件 → 知识 的多步影响（J 路径传播）
     —— 链式法则 = 条件链组合（0.9×0.85）
零 LLM：全部矩阵/图运算，白箱确定性。
"""
import sys
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')


def build_influence_jacobian(units=None):
    """条件单元库 → 影响雅可比矩阵（离散化偏导：存在条件→知识关系 = 1）
    返回 (J, knowledges, conditions)：J[i][j] = ∂knowledge_i/∂condition_j"""
    units = units or {}
    knowledges = list(units.keys())
    conditions = sorted({c for u in units.values() for c in u["conditions"]})
    J = np.zeros((len(knowledges), len(conditions)), dtype=np.float32)
    for i, k in enumerate(knowledges):
        for c in units[k]["conditions"]:
            J[i, conditions.index(c)] = 1.0
    return J, knowledges, conditions


def condition_impact(J, condition_idx):
    """条件对知识的直接影响（雅可比列——∂知识/∂条件）"""
    return J[:, condition_idx]


def knowledge_dependencies(J, knowledge_idx):
    """知识的条件依赖（雅可比行——该知识依赖哪些条件）"""
    return J[knowledge_idx, :]


def condition_independence(J, conditions, c1, c2):
    """条件独立性（混合偏导 ∂²f/∂x∂y=0 的图判定）：
    两条件共享知识（共同影响目标）→ 相关（不可独立并行）；
    无共享知识 → 独立（可分离组合——组合引擎并行化）"""
    col1 = J[:, conditions.index(c1)]
    col2 = J[:, conditions.index(c2)]
    shared = [i for i in range(len(col1)) if col1[i] > 0 and col2[i] > 0]
    independent = len(shared) == 0
    return independent, shared


def chain_rule_propagate(J, conditions, start_condition, max_steps=3):
    """链式法则传播：条件 → 知识 → 条件 → 知识…（多步影响，J 路径）
    条件 c 影响知识 k（∂k/∂c），该知识若与条件 c' 共享（该知识是 c' 的条件链一环）
    则 c 通过 k 间接影响 c' 的规律——链式法则 dz/dx = dz/dy·dy/dx"""
    ci = conditions.index(start_condition)
    # 条件→知识 影响：J 列（∂知识/∂条件）
    affected_knowledge = [k for k in range(J.shape[0]) if J[k, ci] > 0]
    steps = [(start_condition, affected_knowledge)]
    frontier = affected_knowledge
    for _ in range(max_steps - 1):
        next_knowledge = []
        for k in frontier:
            # 该知识影响的下一条件（知识 → 条件的出链：J 行非零的其他条件）
            for cj in range(J.shape[1]):
                if J[k, cj] > 0 and cj != ci:
                    next_knowledge.extend(
                        [k2 for k2 in range(J.shape[0])
                         if J[k2, cj] > 0 and k2 not in next_knowledge])
        if not next_knowledge:
            break
        steps.append((f"知识传递", next_knowledge))
        frontier = next_knowledge
    return steps


if __name__ == "__main__":
    import sys as _sys
    # 单源规范：模块同目录解析，无需外部路径注入
    import compose_engine as ce

    print("=== 条件代数工程化：影响雅可比图（零 LLM） ===\n")

    # ① 条件单元库 → 影响雅可比
    J, knowledges, conditions = build_influence_jacobian(ce.CONDITION_UNITS)
    print("① 影响雅可比 J[知识][条件]（存在条件→知识关系 = ∂知识/∂条件）")
    print(f"   {len(knowledges)} 个知识规律 × {len(conditions)} 个条件维度")
    print(f"   条件维度: {conditions}")

    # ② 条件独立性（组合并行化的数学基础）
    print("\n② 条件独立性（混合偏导 ∂²f/∂x∂y=0 的图判定）")
    for c1, c2 in [("气压", "光照"), ("气压", "温度"), ("温度", "通风")]:
        indep, shared = condition_independence(J, conditions, c1, c2)
        shared_names = [knowledges[i] for i in shared]
        print(f"   「{c1}」vs「{c2}」: {'独立（可并行组合）' if indep else '相关（共享知识: ' + str(shared_names) + '）'}")

    # ③ 链式法则传播（条件 → 知识 → 条件…）
    print("\n③ 链式法则传播（条件链 = 雅可比路径）")
    steps = chain_rule_propagate(J, conditions, "气压")
    for i, (tag, ks) in enumerate(steps):
        names = [knowledges[k] for k in ks]
        print(f"   第{i+1}步: 影响 {names}")

    # ④ 组合生成 × 微积分：条件链置信度 = 链式法则（从 compose_engine 实际组合）
    print("\n④ 条件链组合 = 链式法则（compose_engine 实际演示）")
    r = ce.route_compose("为什么高原上煮饭不容易熟？")
    print(f"   「高原煮饭不熟」组合生成: {r['answer'][:50]}")
    print(f"   （链式法则: ∂煮不熟/∂气压 = ∂煮不熟/∂沸点 × ∂沸点/∂气压——条件链组合）")

    # ⑤ 条件独立性 → 组合并行（气压域 vs 光域 可并行组合）
    print("\n⑤ 条件独立性工程价值：气压域与光域独立 → 可并行组合")
    print("   （不同知识域的查询互不依赖——组合引擎可并行；")
    print("    共享条件的查询需串行——混合偏导≠0 的交互部分）")
