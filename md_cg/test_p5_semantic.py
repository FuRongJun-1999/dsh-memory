# -*- coding: utf-8 -*-
"""md_cg · P5 验收：条件空间结构化匹配（白箱语义路）

运行：python -m md_cg.test_p5_semantic

验证口径（对齐「只新增、不改既有语义」）：
  1. 条件证据提取：CCG 字段解析 / 三处来源合并 / 时间窗交叠 / 整词负路由
  2. semantic 路径：条件结构驱动（生效条件 + condition_space 四槽）
  3. 条件级负路由：不适用条件命中 → 剔除（fuzzy 做不到）
  4. 与 fuzzy 正交：condition_space.observation_tool 只有 semantic 读得到
  5. 默认 RRF 不含 semantic（四路基线不受影响）
"""
from __future__ import annotations

import shutil
import sys
import tempfile

from .mdcos import (MdCGOS, _term_degree, _weighted_coverage, _ccg_field,
                    _declared_conditions, _neg_hit, _window_overlap,
                    _slot_overlap)

PASS = FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


CCG = ("# 功能名：{n}\n# 生效条件：{c}\n# 子功能：{s}\n# 执行：{e}\n"
       "# 验证方式：test\n# 不适用条件：{neg}\n\n{body}\n")


def mk(n, cond, body, neg="其它"):
    return CCG.format(n=n, c=cond, s=body[:20], e=body, neg=neg, body=body)


# 真实迁移语料形态的 condition_space（高等数学骨架填充）
CS_MATH = {
    "observation_position": "高等数学知识点内容（按骨架填充） 知识点（微分方程应用）",
    "observation_tool": "学科知识卡拆分",
    "time_window": [0.0, 9999999999.0],
    "existence_constraint": "通用规律/知识（开源非盈利知识库）",
}


def main():
    # ---------------- 1. 条件证据提取 ----------------
    print("\n【1】条件证据提取（确定性、零依赖）")
    body = mk("微分方程应用", "问微分方程应用 问微分方程", "微分方程应用：建模与求解",
              neg="问数列极限 问函数极限")
    check("_ccg_field：中文冒号提取生效条件",
          _ccg_field(body, "生效条件") == "问微分方程应用 问微分方程",
          _ccg_field(body, "生效条件"))
    check("_ccg_field：不适用条件", _ccg_field(body, "不适用条件") == "问数列极限 问函数极限")
    check("_ccg_field：无该字段 → 空串", _ccg_field(body, "不存在字段") == "")
    check("_ccg_field：英文冒号亦可",
          _ccg_field("# 生效条件: 问天气\n正文", "生效条件") == "问天气")

    pos, neg = _declared_conditions(
        {"non_applicable_conditions": ["海拔 > 5000 米"],
         "state_attributes": {"comment": {"生效条件": ["问微分方程"],
                                          "不适用条件": ["问数列极限"]}}},
        body)
    check("_declared_conditions：正文生效条件在列", "问微分方程应用 问微分方程" in pos)
    check("_declared_conditions：合并 state_attributes 生效条件", "问微分方程" in pos, str(pos))
    check("_declared_conditions：合并 frontmatter 负条件",
          "海拔 > 5000 米" in neg, str(neg))
    check("_declared_conditions：去重保序",
          len(neg) == len(set(neg)) and len(pos) == len(set(pos)))

    check("_window_overlap：完全包含 → 1.0",
          _window_overlap([0, 100], [10, 20]) == 1.0)
    check("_window_overlap：半交叠 → 0.5",
          abs(_window_overlap([0, 10], [5, 15]) - 0.5) < 1e-9,
          f"{_window_overlap([0, 10], [5, 15])}")
    check("_window_overlap：不相交 → 0.0",
          _window_overlap([0, 10], [20, 30]) == 0.0)
    check("_window_overlap：非法输入 → 0.0", _window_overlap(None, [1, 2]) == 0.0)

    # 条件级负路由：只认高置信整词，泛化短词不误杀
    check("_neg_hit：整词命中 → True",
          _neg_hit({"数列极限": 1.0}, ["问数列极限 问函数极限"]))
    check("_neg_hit：低权词不触发",
          not _neg_hit({"数列极限": 0.4}, ["问数列极限 问函数极限"]))
    check("_neg_hit：部分命中不触发",
          not _neg_hit({"数列": 1.0}, ["问函数极限"]))
    check("_neg_hit：无负条件 → False", not _neg_hit({"x": 1.0}, []))

    # 槽位重合：缺失槽不进分母
    cs_pos_only = {"observation_position": CS_MATH["observation_position"]}
    check("_slot_overlap：域相似度（高等数学 vs 数学 → 0.5）",
          abs(_slot_overlap({"微分方程": 1.0}, cs_pos_only, q_domain="数学") - 0.5) < 1e-9,
          f"{_slot_overlap({'微分方程': 1.0}, cs_pos_only, q_domain='数学')}")
    cs_two = dict(cs_pos_only)
    cs_two["observation_tool"] = "学科知识卡拆分"
    s2 = _slot_overlap({"微分方程": 1.0}, cs_two, q_domain="数学")
    check("_slot_overlap：未命中的槽进分母 → 分数被摊薄",
          abs(s2 - (2 * 0.5) / 3) < 1e-9, f"{s2}")
    check("_slot_overlap：无槽信息 → 0.0",
          _slot_overlap({"x": 1.0}, {}) == 0.0)

    # ---------------- 2. semantic 路径 ----------------
    print("\n【2】semantic 路径：条件结构驱动")
    root = tempfile.mkdtemp(prefix="mdcg_sem_")
    try:
        cg = MdCGOS(root, actor="test")
        cg.add("diff_eq", mk("微分方程应用", "问微分方程应用 问微分方程",
                             "微分方程应用：建模与求解",
                             neg="问数列极限 问函数极限"),
               tags=["domain:高等数学"], condition_space=CS_MATH)
        cg.add("series", mk("数列极限", "问数列极限 问函数极限",
                            "数列极限的定义与性质",
                            neg="问微分方程 问贝塞尔"),
               tags=["domain:高等数学"],
               condition_space=dict(CS_MATH,
                                    observation_position="高等数学知识点内容（按骨架填充） 知识点（数列极限）"))
        cg.add("noise", mk("无关节点", "问天气", "今天天气晴朗", neg="其它"),
               tags=["domain:通用"])

        cands = cg._candidates()
        scored, = [cg._path_semantic("微分方程", cands)]
        smap = {n["id"]: s for n, s in scored}
        check("生效条件命中 → diff_eq 被召回", "diff_eq" in smap, str(smap))
        check("不适用条件命中 → series 被条件级负路由剔除",
              "series" not in smap, str(smap))
        check("无任何条件证据 → noise 不进候选", "noise" not in smap, str(smap))
        check("semantic 打分 ∈ (0,1]", all(0 < s <= 1.0 for s in smap.values()),
              str({k: round(v, 3) for k, v in smap.items()}))

        # 对称性：换查询，命中关系反转
        scored2, = [cg._path_semantic("数列极限", cands)]
        smap2 = {n["id"]: s for n, s in scored2}
        check("对称性：查询「数列极限」→ series 召回、diff_eq 剔除",
              "series" in smap2 and "diff_eq" not in smap2, str(smap2))

        # ---------------- 3. 与 fuzzy 正交 ----------------
        print("\n【3】与 fuzzy 正交（condition_space 槽位只有 semantic 读得到）")
        # 用不可分解的 ASCII 令牌隔离「字段可见性」：正文/tags 均不含它，
        # 排除 fuzzy 通过子词扩展误命中的干扰。
        cg.add("tool_node", mk("采集流程", "none", "nothing here", neg="none"),
               tags=[], condition_space={"observation_tool": "ZXQ7"})
        cands = cg._candidates()
        sem_tool = {n["id"]: s for n, s in cg._path_semantic("ZXQ7", cands)}
        fuz_tool, _ = cg._path_fuzzy("ZXQ7", cands)
        fuz_ids = {n["id"] for n, _ in fuz_tool}
        check("semantic 命中 observation_tool 槽", "tool_node" in sem_tool, str(sem_tool))
        check("fuzzy 读不到 condition_space 字段（正交证据）",
              "tool_node" not in fuz_ids, str(fuz_ids))

        # 负条件（不适用条件）是反例声明，两条路径都不作召回键
        # （语义修正：反例的正确去向是 judge_qualification 的 REJECT，不是召回）
        cg.add("neg_declared", mk("通用流程", "问通用流程", "通用流程说明",
                                  neg="问ZXQ7"),
               tags=[], condition_space={})
        cands = cg._candidates()
        fuz_neg, _ = cg._path_fuzzy("ZXQ7", cands)
        sem_neg = {n["id"] for n, _ in cg._path_semantic("ZXQ7", cands)}
        check("fuzzy 不再召回「不适用条件」命中的节点（反例不作召回键）",
              "neg_declared" not in {n["id"] for n, _ in fuz_neg})
        check("semantic 同样剔除「不适用条件」命中的节点（条件级负路由）",
              "neg_declared" not in sem_neg)
        check("但正条件仍作召回键（生效条件命中照常召回）",
              "neg_declared" in
              {n["id"] for n, _ in cg._path_fuzzy("通用流程", cands)[0]})

        # 迁移语料形态：state_attributes.comment.生效条件
        cg.add("mig", mk("骨架卡", "（隐含）", "骨架填充的知识点",
                         neg="其它"),
               tags=["domain:高等数学"], condition_space=CS_MATH,
               state_attributes={"comment": {"生效条件": ["问微分方程应用", "问微分方程"],
                                             "不适用条件": ["问数列极限"]}})
        sem_mig = {n["id"]: s for n, s in cg._path_semantic("微分方程", cg._candidates())}
        check("迁移语料 state_attributes 生效条件被读取", "mig" in sem_mig, str(sem_mig))

        # ---------------- 4. RRF 接入 ----------------
        print("\n【4】semantic 接入 RRF（默认不启用）")
        res0, meta0 = cg.search_rrf("微分方程", k=5)
        check("默认 RRF 路径不含 semantic",
              "semantic" not in meta0.get("paths", {}), str(list(meta0.get("paths", {}))))

        paths6 = ("lexical", "bucket", "entity", "graph", "fuzzy", "semantic")
        res, meta = cg.search_rrf("微分方程", k=5, paths=paths6)
        check("显式启用后 meta 记录 semantic 路",
              "semantic" in meta.get("paths", {}), str(meta.get("paths")))
        prov = meta.get("provenance", {})
        check("provenance 含 semantic 路",
              any(any(p["path"] == "semantic" for p in prov.get(nid, []))
                  for nid in prov),
              str({k: [p["path"] for p in v] for k, v in prov.items()})[:160])
        check("结果非空", len(res) > 0, f"{len(res)} 条")

        # 单路可独立运行（无 context）
        res_s, meta_s = cg.search_rrf("微分方程", k=5, paths=("semantic",))
        check("semantic 单路在无 context 下可运行",
              isinstance(res_s, list) and len(res_s) > 0, f"{len(res_s)} 条")

        # recall 透传 paths
        rec = cg.recall("微分方程", budget_tokens=400, k=5, paths=paths6)
        check("recall 可透传 paths 启用 semantic",
              "semantic" in rec["meta"].get("paths", {}),
              str(rec["meta"].get("paths")))
        check("recall 仍遵守预算", rec["tokens_used"] <= rec["budget"],
              f"used={rec['tokens_used']}/{rec['budget']}")
        cg.close()
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 68)
    print(f"通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：" + ", ".join(FAILS))
    print("=" * 68)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
