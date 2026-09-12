# -*- coding: utf-8 -*-
"""弱语义噪声注入四臂实验（GPT 理论的形式化验证）。

理论命题（本轮与 GPT 分析定稿）：
  1. 三分离：语义完整度 ≠ 证据强度 ≠ 召回价值——「我在喝水」语义高度省略，
     但作为 episodic fact 事实承诺明确（SELF+drinking+water+now）。
  2. 语义联系是候选生成器，不是证据：semantic association ≠ evidence。
     等权 RRF 会双重奖励「多路都靠前」的语义邻居，把真正的事实挤出前排
     （排序污染）；mdcos.search_rrf docstring 已自注该现象。
  3. 证据防火墙（judge_ranking）：语义负责「不要漏」，白箱负责「不要错」——
     融合排序只产生候选，资格裁决（REJECT/BLINDSPOT 剔除、DEFER 降权、
     ACCEPT 保位）决定最终优先级。
  4. query-relative：同一记忆在不同问题下资格不同——否定事件
     （「我没喝水」）在「刚才在干什么」问句下必须 REJECT。

四臂（同一 42 节点确定性语料、同一查询）：
  A lex        单词法路（词面+CCG 正文）
  B semantic   单 fuzzy 路（同义词组/大域扩展 = 灵枢的「语义联系」等价物；
               无神经嵌入是架构取向，如实测报）
  C fusion     等权五路 RRF（现状默认形态，judge 只标注不改序）
  D firewall   C + judge_ranking（白箱终排）

指标：top1 命中率 / hit@10 / MRR（对 8 条 gold）。
断言：D ≥ C（防火墙不劣于裸融合）、D 剔除数 > 0（防火墙生效）；
C < A 的污染强度只测量不预设——实测反例时按第 4 条修正理论而非硬造。

运行：python -m md_cg.test_sem_noise
"""
from __future__ import annotations

import os
import shutil
import tempfile

from .mdcg import STATE_REJECT
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


#: 8 条 episodic gold——语义高度省略、事实承诺明确（正文首行即事实）
GOLD = [
    ("g1", "我在喝水。"),
    ("g2", "我吃了饭。"),
    ("g3", "我刚打开了电脑。"),
    ("g4", "我在看书。"),
    ("g5", "我在听音乐。"),
    ("g6", "我刚出了门。"),
    ("g7", "我在浇花。"),
    ("g8", "我刚下了班。"),
]

#: 语义邻居（泛化句）：与 gold 同主题、语义上「可能相关」，但不是该事件。
#: 每条 gold 配两条，生效条件各归各的主题问句——「问刚才在干什么」不命中。
NEIGHBORS = {
    "g1": [("n1a", "喝水对健康有好处。", "问健康建议"),
           ("n1b", "运动后需要补充水分。", "问运动恢复")],
    "g2": [("n2a", "规律饮食有助于消化。", "问健康建议"),
           ("n2b", "营养均衡是饮食原则。", "问营养知识")],
    "g3": [("n3a", "电脑需要定期清理缓存。", "问电脑维护"),
           ("n3b", "工作离不开电脑。", "问工作方式")],
    "g4": [("n4a", "阅读能增长知识。", "问阅读价值"),
           ("n4b", "书籍是人类进步的阶梯。", "问读书意义")],
    "g5": [("n5a", "音乐能舒缓情绪。", "问音乐作用"),
           ("n5b", "听音乐是常见放松方式。", "问放松方法")],
    "g6": [("n6a", "出门要记得带钥匙。", "问出门提醒"),
           ("n6b", "散步有益身心健康。", "问健康建议")],
    "g7": [("n7a", "浇花要在早晨或傍晚。", "问养花知识"),
           ("n7b", "植物需要适量水分。", "问植物养护")],
    "g8": [("n8a", "下班路上注意安全。", "问出行提醒"),
           ("n8b", "工作与生活要平衡。", "问生活理念")],
}

#: 否定/反事实：语义上与 gold 最近（「我没喝水」vs「我在喝水」），
#: 但 state/negation 完全不同——在「刚才在干什么」问句下必须被负条件 REJECT。
NEG_TEXTS = [("x1", "我没喝水。"), ("x2", "我没吃饭。"), ("x3", "我还没打开电脑。"),
             ("x4", "我没看书。"), ("x5", "我没听音乐。"), ("x6", "我没出门。"),
             ("x7", "我没浇花。"), ("x8", "我还没下班。")]

#: 无关背景噪声（占用候选池）
UNREL = ["u%d" % i for i in range(1, 11)]
UNREL_DOCS = [
    ("u1", "今天天气很热。", "问天气"), ("u2", "周五下午三点开会。", "问会议安排"),
    ("u3", "地铁三号线今天停运。", "问交通信息"), ("u4", "小区门口新开了超市。", "问周边设施"),
    ("u5", "我的快递到了驿站。", "问快递状态"), ("u6", "明天可能下雨。", "问天气预报"),
    ("u7", "这个月话费涨了。", "问账单"), ("u8", "楼下在修路。", "问施工信息"),
    ("u9", "牙膏用完了要买。", "问采购清单"), ("u10", "窗台的多肉长新芽了。", "问植物状态"),
]

QUERY = "你刚才在干什么"
#: episodic gold 的统一生效条件——必须是 QUERY 的词面子串（正条件确认即「情境
#: 提问与记忆声明的问题类型一致」，这正是「条件是适用边界而非必填字段」）。
GOLD_COND = "刚才在干什么"
NEG_COND = "问没做的事"


def _doc(fact, cond, extra_neg=False):
    lines = ["# 功能名：事件记录",
             f"# 生效条件：{cond}",
             "# 子功能：episodic 片段（语义可省略，事实承诺明确）",
             "# 执行：陈述事实",
             "# 验证方式：据用户直接陈述核对",
             f"# 不适用条件：{'刚才在干什么' if extra_neg else '无'}"]
    return fact + "\n" + "\n".join(lines) + "\n"


def _metrics(cg, arm_kw, gold_ids):
    ranks, states = {}, {}
    res, meta = cg.search_rrf(QUERY, k=10, judge=True, **arm_kw)
    ids = [r[0]["id"] for r in res]
    for gid in gold_ids:
        if gid in ids:
            r = ids.index(gid) + 1
            ranks[gid] = r
            states[gid] = res[ids.index(gid)][2].get("state")
    top1 = sum(1 for r in ranks.values() if r == 1)
    hit10 = len(ranks)
    mrr = sum(1.0 / r for r in ranks.values()) / len(gold_ids)
    return top1, hit10, mrr, ranks, states, meta


def main():
    global PASS, FAIL
    tmp = tempfile.mkdtemp(prefix="mdcg_semanoise_")
    try:
        root = os.path.join(tmp, "root")
        os.makedirs(root, exist_ok=True)
        cg = MdCGOS(root)

        for gid, fact in GOLD:
            cg.add(gid, _doc(fact, GOLD_COND), layer="knowledge",
                   verification_basis="test")
        for gid, lst in NEIGHBORS.items():
            for nid, fact, cond in lst:
                cg.add(nid, _doc(fact, cond), layer="knowledge",
                       verification_basis="test")
        for nid, fact in NEG_TEXTS:
            cg.add(nid, _doc(fact, NEG_COND, extra_neg=True), layer="knowledge",
                   verification_basis="test",
                   non_applicable_conditions=["刚才在干什么"])
        for nid, fact, cond in UNREL_DOCS:
            cg.add(nid, _doc(fact, cond), layer="knowledge",
                   verification_basis="test")

        gold_ids = [g for g, _ in GOLD]
        ARMS = {
            "A_lex": dict(paths=("lexical",)),
            "B_sem": dict(paths=("fuzzy",)),
            "C_fusion": dict(paths=("lexical", "bucket", "entity", "graph",
                                    "fuzzy"), fusion="sum"),
            "D_firewall": dict(paths=("lexical", "bucket", "entity", "graph",
                                      "fuzzy"), fusion="sum", judge_ranking=True),
        }
        table = {}
        for name, kw in ARMS.items():
            top1, hit10, mrr, ranks, states, meta = _metrics(cg, kw, gold_ids)
            table[name] = (top1, hit10, mrr)
            print(f"{name:12s} top1={top1}/8  hit@10={hit10}/8  MRR={mrr:.3f}"
                  + (f"  filtered={meta.get('judge_filtered')}"
                     if name == "D_firewall" else ""))

        c_top1, c_hit, c_mrr = table["C_fusion"]
        d_top1, d_hit, d_mrr = table["D_firewall"]
        a_top1, a_hit, a_mrr = table["A_lex"]
        b_top1, b_hit, b_mrr = table["B_sem"]
        print("\n排序污染测量（只报告，不预设）：C-A top1 差 = "
              f"{a_top1 - c_top1}，C-A MRR 差 = {a_mrr - c_mrr:+.3f}")
        print("防火墙增益（D-C）：top1 {:+d}，MRR {:+.3f}".format(
            d_top1 - c_top1, d_mrr - c_mrr))

        # ---------- 断言 ----------
        ok(d_top1 >= c_top1 and d_mrr >= c_mrr - 1e-9,
           "①防火墙不劣于裸融合（D≥C）")
        # query-relative 否定剔除：否定节点声明的负条件是问句类型词面，
        # 在同类问句下必须 REJECT（不依赖召回路径，直调裁决器验证）
        bad = 0
        for nid, _fact in NEG_TEXTS:
            fm, c = cg._read(cg.index["nodes"][nid])
            jn = MdCGOS.judge_qualification({"frontmatter": fm, "content": c},
                                            QUERY, None)
            if jn["state"] != STATE_REJECT:
                bad += 1
        ok(bad == 0,
           f"②query-relative 否定剔除：{len(NEG_TEXTS)-bad}/{len(NEG_TEXTS)}"
           " 个否定节点被 REJECT（「我没喝水」在「刚才在干什么」问句下"
           "不得冒充事件）")
        # 语义邻居「相关≠适用」：正条件不适用 → DEFER 降权而非 ACCEPT
        fm, c = cg._read(cg.index["nodes"][NEIGHBORS["g1"][0][0]])
        jn = MdCGOS.judge_qualification({"frontmatter": fm, "content": c},
                                        QUERY, None)
        ok(jn["state"] == "DEFER",
           "②b 语义邻居「喝水对健康有好处」→ DEFER（正条件「问健康建议」"
           "不适用该问句；相关但不适用）")
        # query-relative：否定节点在该问句下不得冒充事件
        res, _ = cg.search_rrf(QUERY, k=10, judge=True, judge_ranking=True)
        st = {r[0]["id"]: r[2].get("state") for r in res}
        ok(all("x" + g[1:] not in st for g in gold_ids),
           "③top-10 无否定节点冒充（x* 全部被剔除）")
        if c_top1 < a_top1:
            ok(d_top1 >= a_top1,
               "④融合确实产生排序污染（C<A 已实测）且防火墙恢复到词法水平（D≥A）")
        else:
            ok(True, "④本语料下融合未弱于词法（污染未实测到，如实记录）")
        # gold 资格：正条件命中 → 全 ACCEPT（语义省略≠弱证据）
        res2, _ = cg.search_rrf(QUERY, k=10, judge=True, judge_ranking=True)
        gstates = {r[0]["id"]: r[2].get("state") for r in res2
                   if r[0]["id"] in gold_ids}
        ok(all(s == "ACCEPT" for s in gstates.values()),
           f"⑤正条件命中的 episodic gold 全 ACCEPT（{len(gstates)} 条在 top-10）"
           "——语义不完整不被降级")
        # 同一记忆换问句 → 资格随情境变化（query-relative）
        res3, _ = cg.search_rrf("你在哪里喝水", k=10, judge=True)
        st3 = {r[0]["id"]: r[2] for r in res3 if r[0]["id"] == "g1"}
        if st3:
            ok(st3["g1"]["state"] != "ACCEPT",
               "⑥query-relative：问「在哪里喝」时 g1 不再 ACCEPT（条件不适用→"
               + st3["g1"]["state"] + "）——BLINDSPOT 是问出来的，不是存出来的")
        else:
            ok(True, "⑥query-relative：问「在哪里喝」时 g1 未被召回（等效不冒充）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nsem_noise: {PASS} passed, {FAIL} failed")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
