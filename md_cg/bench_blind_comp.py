# -*- coding: utf-8 -*-
"""组合盲测基线（P4 · unseen compositions）—— P1 Semantic Composition 的验收器。

## 为什么做这个（先例取证）

四臂/域轴消融（bench_zh_mad / bench_axis_domain）的语料与题库同源（locomo），
组合概念的「分解规则」经由 morpheme/synonym 源已在系统可见范围内 —— 无法回答
「系统对**没见过**的组合是否仍能召回」。P1（compositions.json + ontology typing）
落地前后需要一把不可被训练数据污染的尺子，故自造受控盲测集。

## 盲测纪律（全部机器断言，非口头承诺）

1. 未见组合词 **不在** atoms.json（assert_material 运行时断言；未来若 atoms 混入
   组合词，本 bench 立即 fail —— 防盲测腐化）；
2. 组成原子 **在** atoms.json（素材完整性）；
3. 干扰文档 **不含** 任何 gold 组合词的连续子串（防「原子命中即算对」的假阳性）；
4. L3 语义题的 query 与对应 gold 文档 **bigram 零交集**（纯语义层，生成时校验
   + 模板 re-roll）；L1/L2 query 允许词面重叠（它们考的就是词面/跨语词面）。

## 三档难度 × 两臂

| 档 | query 形态 | 考什么 | 预期 |
|---|---|---|---|
| L1_surface | 组合词中文词面（马肉） | bigram 基础召回 sanity | b0 高 |
| L2_crosslingual | 英文组合词面（horse meat） | en→zh 语素映射 + 组合 | b0≈0；b1 视词表覆盖 |
| L3_semantic | 中文语义描述（零 bigram 重叠） | 结构组合理解 | b0/b1≈0 → **P1 靶区** |

臂差异：

* b0_legacy：MDCG_EN_ATOMS 未设（现状默认链路）；
* b1_enatoms：MDCG_EN_ATOMS=1（opt-in 跨语路，en_zh_terms 映射）；
* b2_comp：**MDCG_SEMANTIC=1 + gold 节点附加 fm.semantic 标准原子摘要**
  （2026-09-14 加入）。臂差异扩展声明：正文与 b0/b1 库逐字一致（「同库
  同内容」守恒），差异仅在 gold 节点的 fm 衍生层——semantic 标准原子
  摘要本身即被测变量（AI 写入侧归一 + 检索组合共现，semantic/canonical.py）。
  L3 提升即语义摘要路净效应；L1 词面直配（sim=1）不受 max 聚合拖累、
  L2 与 b0 同（enatoms 关——跨语路正交性对照）；
* b3_unified：**MDCG_SEMANTIC=1 + 原句直查**（2026-09-14 加入）。与 b2 同库
  （gold 带 fm.semantic），差异在查询侧：不做 q_atoms 手工替换，英文原题
  /中文原句直接进检索，归一在 canonical.query_atoms 内部完成——英文经
  en_normalizer 归一为中文语素、复合概念保持整词、与 doc 侧共享同一真源
  切分器。「英文检索路径归一化到统一标准真源」的最小闭环实证：预期 L2
  英文原题经归一命中 semantic 摘要（受控上界），L3 中文原句=中间态（词面
  原子齐备题才可救，其余需查询侧归一即 b2 形态）。

## 判决标准

* L1 b0 hit@1 低 → 基础召回回归问题（先修基础，不谈组合）；
* L2 b1 > b0 → en_zh_terms 对未见组合有净增益；b1 亦≈0 → 对照 L2 白箱探针
  归因「词表映射缺失」vs「组合结构缺失」（前者属 en 词表工作，后者属 P1）；
* L3 双臂≈0 → 现有路对该层无解，量化 P1 的增益空间上限；
  b2 L3 > 0 → 语义摘要路净效应实证（受控上界）；b2 L3=100 且 L1/L2
  与基线一致 → max 聚合与跨语路正交性同证。

## 诚实条款

* 自造语料 33 篇 / 33 题，n 小 → 题级 CV 大（n=100 时 CV≈8.3%，n=33 显著放大）
  → 只做方向性判读，差距 <20% 不可下结论；
* 组合配对（马肉/羊奶…）由出题人显式枚举，未经语料统计验证自然度；
* 「牛肉/鸡蛋」等常用复合词在 atoms 是 serialize 出口的既有设计
  （zh_en_atoms.segment 贪心最长匹配依赖），不在本盲测评判范围；
  atoms 中长概念污染（整句/课程名）另案处理，属 P1 前置清单；
* 指标为受控上界口径：池 = gold + 受控干扰，无开放域噪声；
* 语料生成 seed 固定、纯规则零 LLM，同输入必同输出，可第三方重放。

跑法：python -m md_cg.bench_blind_comp
"""
import json
import os
import random
import shutil
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (HERE, os.path.join(HERE, "md_cg")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from md_cg import eval_common as ec          # noqa: E402
from md_cg import mdcg as mg                 # noqa: E402  L2 白箱探针
from md_cg.mdcos import MdCGOS              # noqa: E402

SEED = 7
ARM_ROOT = os.path.join(HERE, "_md_cg_eval_blind")   # .gitignore /_md_cg_eval_*/ 已覆盖
ATOMS_PATH = os.path.join(HERE, "md_cg", "semantic", "atoms.json")

# 未见组合（组成原子均已确认在 atoms：马鱼狗鸟羊猪鸭 / 肉奶蛋油）
UNSEEN = ["马肉", "鱼肉", "狗肉", "鸟肉", "羊奶", "马奶", "鸭蛋", "鱼蛋",
          "鱼油", "羊油", "猪油"]
L3_SET = {"鱼油", "羊油", "猪油"}
COMP_EN = {"马肉": "horse meat", "鱼肉": "fish meat", "狗肉": "dog meat",
           "鸟肉": "bird meat", "羊奶": "goat milk", "马奶": "mare milk",
           "鸭蛋": "duck egg", "鱼蛋": "fish egg",
           "鱼油": "fish oil", "羊油": "sheep fat", "猪油": "pig fat"}
COMP_L3 = {"鱼油": "体检后医生建议我补充一些从深海鱼类里提取的油脂",
           "羊油": "那种用羊的脂肪慢慢熬出来的白色油脂，是火锅底料的灵魂",
           "猪油": "妈妈熬了一罐雪白的荤油，拌饭特别香"}
# L3 query 的标准原子串（设想终态：查询侧 AI 归一产物——AI 检索前按基准
# 词表把原句归一为标准原子。bench 中手工标注，模拟 AI 归一；原句直查=
# 中间态，代码侧无同义表时只救词面原子齐备题——本 seed 实测 1/3（鱼油），
# 羊油（脂肪→油 距离 12>win6）与猪油（荤油无「猪」字）必须经查询侧归一）
L3_QUERY_ATOMS = {"鱼油": "鱼 油", "羊油": "羊 油", "猪油": "猪 油"}

G_TPL = [
    "今天午饭吃了{c}，味道不错，下次还做。",
    "周末试着做了{c}，家人都说好吃。",
    "朋友来家里聚餐，我特意准备了{c}。",
    "楼下新开的小馆子，招牌就是{c}。",
    "昨天在食堂居然吃到了{c}，挺意外。",
    "妈妈寄来了做{c}用的食材，让我自己学着做。",
    "电视里正在介绍{c}的家常做法。",
    "下班路上买了{c}，打算明天当早饭。",
]
D_TPL = [
    "下午去市场买了{a}，价格比昨天便宜一些。",
    "晚上用{a}和{b}做了两道菜，都没放辣椒。",
    "冰箱里还剩点{a}，再不吃就要坏了。",
    "便利店买的{b}有点贵，下次去批发市场。",
]
# 干扰原子池：只取组成原子自身（错位搭配由生成+断言保证不构成 gold）
DISTRACT_POOL = ["马", "鱼", "狗", "鸟", "羊", "猪", "鸭", "肉", "奶", "蛋", "油", "米"]


# 生效条件：s 为字符串时返回其全部相邻二元组集合；当 len(s) 小于 2 时返回空集合。
def _bigrams(s):
    return {s[i:i + 2] for i in range(len(s) - 1)}


# 生效条件：无参调用且 ATOMS_PATH 载入 atoms 后，逐条确认 UNSEEN 各组合词不在其中文集合、其相邻字符对均为原子，并确认 UNSEEN 无重复、set(COMP_EN)==set(UNSEEN)、set(COMP_L3)<=set(UNSEEN)，全部成立才静默通过，任一断言不成立即 AssertionError。
def assert_material():
    """盲测纪律的机器化：素材在/不在 atoms + 组合词互相不冲突。"""
    atoms = json.load(open(ATOMS_PATH, encoding="utf-8"))["atoms"]
    zh = {a["zh"] for a in atoms}
    for c in UNSEEN:
        assert c not in zh, "盲测腐化：组合词 %r 已混入 atoms" % c
        for i in range(len(c) - 1):
            assert c[i] in zh and c[i + 1] in zh, \
                "素材缺原子：%r 需要 %r/%r" % (c, c[i], c[i + 1])
    assert len(set(UNSEEN)) == len(UNSEEN)
    assert set(COMP_EN) == set(UNSEEN) and set(COMP_L3) <= set(UNSEEN)


# 生效条件：以 SEED 初始化 random.Random 后对 UNSEEN 每词按 G_TPL 取模板生成含 gold 的篇目，再对 j=0..21 用 DISTRACT_POOL 随机取两个不同词按 D_TPL 造文，50 次重试内首次出现不含 UNSEEN 任何组合词的文本即 break 并 append，22 篇齐备后返回 corpus，50 次全冲突则 raise AssertionError。
def gen_corpus():
    """33 篇受控语料：11 gold + 22 干扰。确定性，断言内嵌。"""
    rng = random.Random(SEED)
    corpus = []
    for i, c in enumerate(UNSEEN):
        body = G_TPL[i % len(G_TPL)].format(c=c)
        corpus.append({"id": "g_%s" % c, "text": body, "gold": c})
    for j in range(22):
        for _try in range(50):
            a, b = rng.choice(DISTRACT_POOL), rng.choice(DISTRACT_POOL)
            if a == b:
                continue
            text = D_TPL[j % len(D_TPL)].format(a=a, b=b)
            if not any(c in text for c in UNSEEN):     # 纪律3：零子串
                break
        else:
            raise AssertionError("干扰文档 50 次重试仍冲突（seed=%d）" % SEED)
        corpus.append({"id": "d_%02d" % (j + 1), "text": text, "gold": None})
    return corpus


# 生效条件：对 UNSEEN 中每个 c 生成 L1 与 L2 题；当 c 属于 L3_SET 时，用 assert 强制其 COMP_L3 问句与 g_c 的 gold 文本 bigram 零交集，失败抛 AssertionError，通过后追加 L3 题。
def gen_questions():
    """33 题。L3 生成时校验 query×gold bigram 零交集（纪律4）。"""
    questions = []
    for c in UNSEEN:
        questions.append({"qid": "L1|%s" % c, "qtype": "L1_surface",
                          "question": c,
                          "evidence_turns": ["g_%s" % c]})
        questions.append({"qid": "L2|%s" % c, "qtype": "L2_crosslingual",
                          "question": COMP_EN[c],
                          "evidence_turns": ["g_%s" % c]})
        if c in L3_SET:
            q = COMP_L3[c]
            gold_text = next(r["text"] for r in CORPUS if r["id"] == "g_%s" % c)
            assert not (_bigrams(q) & _bigrams(gold_text)), \
                "L3 纪律破坏：%r 与 gold %r bigram 相交" % (q, c)
            questions.append({"qid": "L3|%s" % c, "qtype": "L3_semantic",
                              "question": q, "evidence_turns": ["g_%s" % c],
                              "q_atoms": L3_QUERY_ATOMS[c]})
    return questions


CORPUS = None   # gen_questions 需引用语料正文（L3 校验），main 内先建语料


# 生效条件：以 cg/questions/tag/en_atoms 与默认 semantic=False 调用时，en_atoms 为真则设 os.environ["MDCG_EN_ATOMS"]="1"、为假则 pop，semantic 为真则设 MDCG_SEMANTIC="1" 且仅当 semantic=="norm" 时把带真值 q_atoms 的题替换为 q_atoms 文本、semantic=="raw" 保持原句、semantic 为假则 pop，随后在 lexical 路径以 k=5 评测并返回 (按 ALL/L1_surface/L2_crosslingual/L3_semantic 分型的 by_type, 仅 en_atoms 为真时按 L2_crosslingual 题收集中文语素的 probe)。
def run_arm(cg, questions, tag, en_atoms, semantic=False):
    """单臂评测：臂差异只在查询侧环境开关展开。返回 (summary_by_type, l2_probe)。

    semantic 三态：False=关；"norm"=查询侧 AI 归一（q_atoms 替换，b2 臂）；
    "raw"=原句直查（归一在 canonical.query_atoms 内部完成，b3 臂——统一
    真源路，英文 query 同路：en_normalizer→中文语素→标准原子）。
    """
    if en_atoms:
        os.environ["MDCG_EN_ATOMS"] = "1"
    else:
        os.environ.pop("MDCG_EN_ATOMS", None)
    if semantic:
        os.environ["MDCG_SEMANTIC"] = "1"
        if semantic == "norm":
            # 设想终态：查询侧 AI 归一——检索前把原句按基准词表归一为标准原子串
            questions = [dict(q, question=q["q_atoms"]) if q.get("q_atoms") else q
                         for q in questions]
        # semantic == "raw"：原句直查，两端归一共享同一真源切分器
    else:
        os.environ.pop("MDCG_SEMANTIC", None)
    rows = ec.evaluate_group(cg, questions, k=5, paths=("lexical",),
                             verbose=False)
    summ = ec.summarize(rows, k=5)
    by_type = {"ALL": summ}
    for lv in ("L1_surface", "L2_crosslingual", "L3_semantic"):
        sub = [r for r in rows if r["qtype"] == lv]
        by_type[lv] = ec.summarize(sub, k=5)
    # L2 白箱探针：展开出的中文语素（归因「映射缺失」vs「组合缺失」）
    probe = {}
    if en_atoms:
        for q in questions:
            if q["qtype"] != "L2_crosslingual":
                continue
            zh_terms = [t for t in mg.expand_query_terms(q["question"])
                        if any("\u4e00" <= ch <= "\u9fff" for ch in t)]
            probe[q["qid"]] = zh_terms
    return by_type, probe


# 生效条件：无参调用时先 assert_material 再经 gen_corpus/gen_questions 得到语料与题，os.path.isdir(ARM_ROOT) 为真则删除该目录，以 ARM_ROOT 建 cg 并写入 CORPUS 全部篇目，os.path.isdir(ARM_ROOT+"_b2") 为真则删除该目录、以该路径建 cg2 并仅对 gold 为真值的篇目附加 semantic=" ".join(gold) 后写入，再依次以 (cg,b0_legacy,False,False)/(cg,b1_enatoms,True,False)/(cg2,b2_comp,False,"norm")/(cg2,b3_unified,False,"raw") 四臂调 run_arm 汇总指标与 b1 的 L2 探针，最后 ec.save_result 写出 blind_comp_baseline.json 并在 out 中记录 seed/n_corpus/n_q/arms/l2_probe/elapsed_s/boundaries。
def main():
    global CORPUS
    t0 = time.time()
    assert_material()
    CORPUS = gen_corpus()
    questions = gen_questions()
    print("[blind_comp] 素材断言通过；语料 %d 篇 / 题 %d 道（seed=%d）"
          % (len(CORPUS), len(questions), SEED))

    ec.unlock_global_cap()
    ec.use_jaccard()

    if os.path.isdir(ARM_ROOT):
        shutil.rmtree(ARM_ROOT, ignore_errors=True)
    cg = MdCGOS(ARM_ROOT, autoflush=500)
    for r in CORPUS:
        cg.add(r["id"], r["text"], layer="knowledge",
               eval_src="blind_comp", verification_basis="data")
    cg.flush()
    ec.install_read_cache(cg)

    out = {"seed": SEED, "n_corpus": len(CORPUS), "n_q": len(questions),
           "arms": {}, "l2_probe": {}}
    # b2 库：正文逐字一致，仅 gold 节点附加 fm.semantic 标准原子摘要
    # （模拟 AI 写入侧归一产物：同义体已按基准翻译成「鱼 油」类原子序列）
    arm2_root = ARM_ROOT + "_b2"
    if os.path.isdir(arm2_root):
        shutil.rmtree(arm2_root, ignore_errors=True)
    cg2 = MdCGOS(arm2_root, autoflush=500)
    for r in CORPUS:
        kw = {}
        if r["gold"]:
            kw["semantic"] = " ".join(r["gold"])     # 「鱼油」→「鱼 油」
        cg2.add(r["id"], r["text"], layer="knowledge",
                eval_src="blind_comp", verification_basis="data", **kw)
    cg2.flush()
    ec.install_read_cache(cg2)

    arms = ((cg, "b0_legacy", False, False),
            (cg, "b1_enatoms", True, False),
            (cg2, "b2_comp", False, "norm"),
            (cg2, "b3_unified", False, "raw"))
    for arm_cg, tag, en, sem in arms:
        by_type, probe = run_arm(arm_cg, questions, tag, en, semantic=sem)
        out["arms"][tag] = by_type
        out["l2_probe"][tag] = probe
        sem_desc = {False: "", "norm": ", 查询侧归一(q_atoms)",
                    "raw": ", 原句直查(query_atoms 内部归一)"}.get(sem, "")
        print("\n== 臂 %s（MDCG_EN_ATOMS=%s, MDCG_SEMANTIC=%s%s%s）=="
              % (tag, "1" if en else "off", "1" if sem else "off",
                 ", gold 带 fm.semantic" if sem else "", sem_desc))
        for lv in ("ALL", "L1_surface", "L2_crosslingual", "L3_semantic"):
            s = by_type[lv]
            print("  %-16s hit@1=%6.1f%%  hit@5=%6.1f%%  MRR=%.4f  (n=%d)"
                  % (lv, s["hit@1"] * 100, s["hit@5"] * 100, s["mrr"], s["n"]))
    if out["l2_probe"]["b1_enatoms"]:
        print("\n== L2 白箱探针（b1 展开出的中文语素）==")
        for qid, terms in out["l2_probe"]["b1_enatoms"].items():
            print("  %-16s -> %s" % (qid, terms or "(映射缺失)"))

    out["elapsed_s"] = round(time.time() - t0, 1)
    out["boundaries"] = [
        "自造受控语料 33 篇/33 题，n 小 CV 大，只做方向性判读",
        "组合配对为出题人显式枚举，未经语料统计验证",
        "b2 语义摘要为 gold 节点人工标注标准原子（模拟 AI 写入侧归一），"
        "非端到端自动归一质量；受控池 0 误配不可外推开放域"
        "（「鱼和油分述」需 P1 组合结构约束）",
        "L3 b0/b1 基线即该两路增益空间上限；P1 compositions 结构层另案",
        "b3 L2 受控上界：受控组合全在 en_normalizer 词表内"
        "（EN_ZH 已含 horse/goat/duck/mare/oil/fat），开放域英文受归一"
        "词表覆盖限制——开放域数字以 locomo-500 英文侧统一真源路实测为准",
    ]
    ec.save_result("blind_comp_baseline.json", out)
    print("\n[blind_comp] 完成，结果已存 blind_comp_baseline.json")


if __name__ == "__main__":
    main()