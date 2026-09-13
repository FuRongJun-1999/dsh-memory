# -*- coding: utf-8 -*-
"""transfer_test 迁移成功率实测（补测②，矩阵 #8 / P-V-15）。

理论定义（P-V-15 / aeis_core api.py 同口径）：
  条件空间内新实体预测成功率，2×SE 显著性；样本 < 20 不构成迁移判定（DEVIATION-005）。
补测设计（矩阵 §4.1）：固定题族（同条件空间、新实体）× 新旧知识库对照：
  Phase A 旧库：仅旧实体 → 基线题命中 + 新实体题（预期 0）
  Phase B 学习：写入新实体（纯 add，无重训——写入即生效）
  Phase C 新库：同题族复测 → 迁移成功率 + 旧任务不遗忘对照
判定口径：hit = 目标节点在 search top5 且资格非 REJECT（检索性能与资格标注正交）。
显著性：Δ=pC−pA>2×SE；完全分离（pA=0,pC=1，SE=0）时直接判显著（强于推断检验）。
"""
import math
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg.mdcg import MdCG

PASS = 0
FAIL = 0
FAILS = []


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}  · {detail}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


# ---------------- 题族：金属导电域（同条件空间 · 旧/新实体） ----------------
OLD_METALS = ["铜", "铁", "铝", "金", "银", "锌", "镍", "锡", "铅", "钨",
              "铂", "汞", "钠", "钾", "钙", "钡", "钛", "铬", "锰", "钴"]
NEW_METALS = ["铯", "铷", "铍", "镁", "镉", "铋", "锑", "锶", "铟", "镓",
              "铊", "锗", "铪", "钽", "铌", "钒", "钼", "锆", "镧", "铈"]
assert len(OLD_METALS) >= 20 and len(NEW_METALS) >= 20, "DEVIATION-005：样本<20 不构成迁移判定"


CONDITION_SPACE = {
    "observation_position": "常温实验台",
    "time_window": [0.0, 9999999999.0],
    "observation_tool": "万用表电阻测量",
    "existence_constraint": "被测对象为{m}且表面干燥",
}


def node_body(m):
    """CCG 六要素标题行正文（ccg_completeness 只认「# 要素：」形态）：
    生效条件行由 condition_space_text 四槽渲染（唯一合成入口，不手写冒充），
    约束槽含实体词面——供 judge 正条件确认命中。"""
    from md_cg.nodefile import condition_space_text
    cs = {k: (v.format(m=m) if isinstance(v, str) else v)
          for k, v in CONDITION_SPACE.items()}
    eff = condition_space_text(cs)
    assert eff, "四槽不全不构成生效条件（fail-closed）"
    return (f"# 功能名：金属{m}导电性检测\n\n"
            f"{m}是金属，常态下可导电，电阻率可由万用表测得。\n\n"
            f"# 生效条件：{eff}\n\n"
            f"# 子功能：对象识别；电阻测量；结果判读\n\n"
            f"# 执行：确认对象为{m} → 万用表测量 → 读出电阻率\n\n"
            f"# 验证方式：实测电阻率落在{m}标准值区间即通过（measurement）\n\n"
            f"# 不适用条件：对象非{m}或表面潮湿时测量结果不适用\n")


def seed(cg, metals):
    """同一条件空间四槽 + 六要素标题行正文——「同条件空间、新实体」的理论口径。"""
    for m in metals:
        cs = {k: (v.format(m=m) if isinstance(v, str) else v)
              for k, v in CONDITION_SPACE.items()}
        cg.add(f"metal_{m}", node_body(m), layer="knowledge",
               tags=["测试-迁移题族"], condition_space=cs,
               verification_basis="measurement")


# 检索任务情境（两阶段同口径）：实体词面由 query 提供（检索命中），
# 条件词面由情境提供（正条件确认）——检索性能与资格确认各司其职。
SCENE_CTX = {"task": "在常温实验台检查金属样本导电性，须按各样本声明条件执行"}


def probe(cg, metals, k=5):
    """题级命中：目标节点在 top5 且资格非 REJECT。返回 (hits, qual_counts)。"""
    hits, quals = 0, {}
    for m in metals:
        res, _ = cg.search(f"{m}导电吗", k=k, context=SCENE_CTX, record=False)
        target = f"metal_{m}"
        ok = False
        for node, score, qual in res:
            q = qual.get("state") if isinstance(qual, dict) else (qual or "?")
            quals[q] = quals.get(q, 0) + 1
            if node.get("id") == target and q != "REJECT":
                ok = True
                break
        hits += 1 if ok else 0
    return hits, quals


def two_se(pA, nA, pC, nC):
    """2×SE 比例差检验；完全分离（SE=0 且 Δ>0）判显著。"""
    se = math.sqrt(pA * (1 - pA) / nA + pC * (1 - pC) / nC)
    delta = pC - pA
    if se == 0:
        return se, delta, delta > 0
    return se, delta, delta > 2 * se


def run_transfer(n_old, n_new, verbose=False):
    """三阶段对照，返回指标 dict。n 由参数控制（供样本守卫测试）。"""
    root = tempfile.mkdtemp(prefix="mdcg_transfer_")
    try:
        cg = MdCG(root)
        olds, news = OLD_METALS[:n_old], NEW_METALS[:n_new]
        # Phase A：旧库（仅旧实体）
        seed(cg, olds)
        a_old, _ = probe(cg, olds)
        a_new, _ = probe(cg, news)
        # Phase B：学习新实体（纯 add，无重训）
        seed(cg, news)
        # Phase C：新库复测
        c_new, quals_c_new = probe(cg, news)
        c_old, _ = probe(cg, olds)
        pA, pC = a_new / n_new, c_new / n_new
        se, delta, sig = two_se(pA, n_new, pC, n_new)
        return {
            "n_old": n_old, "n_new": n_new,
            "a_old": a_old, "a_new": a_new,
            "c_new": c_new, "c_old": c_old,
            "quals_c_new": quals_c_new,
            "pA": round(pA, 3), "pC": round(pC, 3),
            "delta": round(delta, 3), "se": round(se, 4), "significant": sig,
            "retention_ok": c_old >= a_old,
            "n_judgable": n_new >= 20,
            "verdict": ("insufficient_sample" if n_new < 20 else
                        ("transfer_confirmed" if sig and c_old >= a_old
                         else "transfer_not_confirmed")),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    global PASS, FAIL
    print("\n[1] 主对照：20 旧实体 × 20 新实体（同条件空间题族）")
    r = run_transfer(20, 20)
    print(f"    Phase A 旧库：基线题 {r['a_old']}/20，新实体题 {r['a_new']}/20")
    print(f"    Phase C 新库：迁移题 {r['c_new']}/20（qual 分布 {r['quals_c_new']}），"
          f"基线复测 {r['c_old']}/20")
    print(f"    成功率 {r['pA']}→{r['pC']}（Δ={r['delta']}, SE={r['se']}, "
          f"2×SE 显著={r['significant']}），不遗忘={r['retention_ok']}")
    print(f"    判定 verdict={r['verdict']}（n={r['n_new']}）")

    print("\n[2] 断言")
    check("① Phase A 基线题命中（旧库自身健康 ≥19/20）", r["a_old"] >= 19, f"{r['a_old']}/20")
    check("② Phase A 新实体题成功率为 0（旧库无新实体知识）", r["a_new"] == 0, f"{r['a_new']}/20")
    check("③ Phase C 迁移成功率 ≥19/20（写入即生效）", r["c_new"] >= 19, f"{r['c_new']}/20")
    check("④ 2×SE 显著性成立", r["significant"], f"Δ={r['delta']} SE={r['se']}")
    check("⑤ 旧任务不遗忘（基线复测不降）", r["retention_ok"], f"{r['a_old']}→{r['c_old']}")
    check("⑥ 判定为 transfer_confirmed（n≥20 达判定门槛）",
          r["verdict"] == "transfer_confirmed", r["verdict"])

    print("\n[3] 样本守卫：n=10（<20）须拒绝判定")
    small = run_transfer(5, 10)
    check("⑦ 小样本 verdict=insufficient_sample（DEVIATION-005）",
          small["verdict"] == "insufficient_sample",
          f"n={small['n_new']} verdict={small['verdict']}")

    print(f"\n{'=' * 60}\n通过 {PASS} / {PASS + FAIL}")
    if FAILS:
        print("失败：" + "、".join(FAILS))
    return FAIL == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
