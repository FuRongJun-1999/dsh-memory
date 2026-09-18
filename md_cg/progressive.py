#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""progressive.py · 渐进式语义检索控制器（Progressive Semantic Retrieval）

理论定位（使用者与 GPT 定稿，2026-09-14）：
    语义解析的完整性与检索的必要性不是同一个问题——一句话不必完成完整
    语义解析，往往已含足够检索线索。查询不是固定语义结构，而是**不断
    收紧的约束集合**；检索本身成为语义理解的一部分。

    不要追求「一句话完成语义理解」，而要从**最小可靠语义**开始，
    通过检索获得上下文，再逐步增加条件，使语义收敛。

    架构：AI 翻译 → 中文 → 基础语义组合 → 宽检索（少条件）→ 候选集合
          → 逐步增加条件 → 精确语义判断。

与灵枢既有机制的对接（全部已存在，本模块只补控制器壳）：
    - 宽检索可行性    = bench_en_atoms_public 臂⑤⑥⑦实证：归一残缺 20%
                        时 hit@10 仍 99.2-99.8——宽检索不要求完整归一；
    - 四态控制器      = judge_qualification / judge_ranking（证据防火墙）：
                        DEFER ≠ 失败 =「当前语义分辨率不足，继续获取条件」；
    - 主动条件获取    = autonomy.explore 信息差驱动（Active Semantic
                        Retrieval 的写侧对应物，后续增量汇合点）。

代码职责（纯函数、确定性、评分器注入式）：
    - core_subset()      Stage-1 宽检索核心子集（保序截断）；
    - discriminative()   候选间区分度最大的未用原子（覆盖差，None=无
                         区分性条件可加——诚实停止，不硬选）；
    - progressive_search()  宽检索 → 区分度引导加条件 → 重排 的循环，
                         返回逐阶段轨迹（可审计）。

诚实边界：
    1) 区分性条件词池由调用方给定（bench 侧=归一原子全集；引擎侧真实
       系统应由 atoms.json 标准词表驱动——手工池只是评测示教）；
    2) 零干扰池（567 全 gold）上渐进预期 ≈ 一次性全原子——机制价值
       在归一残缺场景与受控干扰池（见 bench_progressive.py）；
    3) 本模块不接 AI、不写库——DEFER 驱动的主动问询（向用户/环境获取
       条件）是后续增量。
"""
from __future__ import annotations

#: 区分度阈值：覆盖差 gap = 1-|2cov-1| ∈ (0,1]，低于此值不选
#: （0 = 全命中/全不命中，加了不产生任何排序差异）。取小正数即可——
#: 「最大区分度」排序本身已保证质量，阈值只排除零区分的无效条件。
MIN_DISCRIM = 0.1


# 生效条件：atoms 经 `a for a in (atoms or ()) if a` 过滤后为空（atoms 为 None/空容器/元素全为假值）→ 返回 []，否则取过滤后前 n 项，n = max(1, int(len(toks)*ratio))，故 ratio=0 或负值时仍返回 1 项、ratio=1.0 时返回全部。
def core_subset(atoms, ratio=0.5):
    """Stage-1 宽检索核心子集：归一序列前 int(len*ratio) 个（保序，确定性）。

    「最小可靠语义」的确定性近似——归一产物的前段通常是事件核心
    （主体/动作），尾段多为修饰限定。ratio=1.0 退化为一次性全原子。
    """
    toks = [a for a in (atoms or ()) if a]
    if not toks:
        return []
    n = max(1, int(len(toks) * ratio))
    return toks[:n]


# 生效条件：cand_sets 长度 < 2 或 unused 为假值/空序列 → 返回 None；否则对 unused 保序逐项算 cov=命中 cand_sets 的比例、gap=1-|2*cov-1|，返回 gap 严格大于 float(min_gap)（默认模块常量 MIN_DISCRIM）者中 gap 最大者，同 gap 取 unused 原序靠前者；无满足者返回 None。
def discriminative(unused, cand_sets, min_gap=MIN_DISCRIM):
    """候选间区分度最大的未用原子（确定性：同 gap 取归一序列原序靠前者）。

    unused:     候选条件词序列（保序）；
    cand_sets:  当前 top 候选的原子集序列（frozenset）；
    返回 gap 最大且 > min_gap 的原子；无 → None（无区分性条件可加）。
    """
    n = len(cand_sets)
    if n < 2 or not unused:
        return None
    best, best_gap = None, float(min_gap)
    for a in unused:
        cov = sum(1 for s in cand_sets if a in s) / n
        gap = 1.0 - abs(2.0 * cov - 1.0)     # cov=0.5 → 1.0；0/1 → 0.0
        if gap > best_gap:
            best, best_gap = a, gap
    return best


# 生效条件：atoms 真值过滤后为空 → 返回 {'stages': [], 'added': [], 'converged': False}；否则从 used=core_subset(toks, ratio) 起在 range(max_stages) 内循环，每阶段记录 rank_fn(used) 的前 k（默认 10）个 cid 与当前 used，若 stage==max_stages-1 则 break 且 converged 保持 False，非末阶段则用 pool（cond_pool 为真值时取 list(cond_pool)，否则回落为 toks 真值过滤后的 atoms）中未用原子对 top 的 cand_atoms.get(cid, frozenset()) 调 discriminative：结果非 None 时并入 used 并追加进 added 继续循环，为 None 时置 converged=True 提前结束。
def progressive_search(rank_fn, atoms, cand_atoms,
                       ratio=0.5, k=10, max_stages=4,
                       cond_pool=None, min_gap=MIN_DISCRIM):
    """渐进式语义检索主循环（评分器注入式，纯函数）。

    rank_fn(atoms_list) -> [(cid, score), ...]  分数降序（bench 侧=原子
        Jaccard；引擎侧=search_rrf 的适配包装——四态终排在引擎内生效）；
    atoms:      归一原子全集（Stage-1 取 core_subset，后续按区分度补）；
    cand_atoms: {cid: frozenset} 候选原子集（区分度观测面）；
    cond_pool:  引擎侧的候选条件词池（bench 原子面缺省=atoms 未用部分）；
    max_stages: 检索预算（最多 rank 次数，每阶段都被测量，不空转）。

    返回轨迹：
        stages: [{used, top}]   每阶段使用的条件与 top-k 候选 id；
        added:  [atom]          逐阶段新增的区分性条件（refinement steps）；
        converged: bool         无区分性条件可加而提前停止（True）或
                                预算耗尽（False）。
    """
    toks = [a for a in (atoms or ()) if a]
    if not toks:
        return {"stages": [], "added": [], "converged": False}
    used = core_subset(toks, ratio)
    stages, added = [], []
    converged = False
    pool = list(cond_pool) if cond_pool else toks
    for stage in range(max_stages):
        ranked = rank_fn(used)
        top = ranked[:k]
        stages.append({"used": list(used),
                       "top": [cid for cid, _s in top]})
        if stage == max_stages - 1:
            break
        nxt = discriminative([a for a in pool if a not in used],
                             [cand_atoms.get(cid, frozenset())
                              for cid, _s in top],
                             min_gap=min_gap)
        if nxt is None:
            converged = True          # 无条件可加：当前分辨率下已收敛
            break
        used = used + [nxt]
        added.append(nxt)
    return {"stages": stages, "added": added, "converged": converged}
