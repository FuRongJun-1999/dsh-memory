# -*- coding: utf-8 -*-
"""md 认知图 P1 验收 · 白箱认知架构 9 维度补全

覆盖（对照 docs/认知图_MD目录方案_v0.1.md v0.3 待办 + 白箱 5 篇）：
  1. MARKS 5 要素 + 验证基底 + 不适用条件
  2. 负记忆目录（rejected/unresolved）
  3. 资格判定四态（ACCEPT/REJECT/DEFER/BLINDSPOT）
  4. Top-1/Top-5/盲区触发率指标（vs 客观真值 oracle）
  5. 两阶段并行收敛路由（14 大域 → 桶内 KCCS）
  6. 信息差 D(t,C) 与 d²D/dt²
  7. 知识飞轮：错误→补条件→结构更新
  8. 五大单元之反思/验证
  9. CCG 完整度 + 验证基底覆盖率健康度自检

语料：md_cg/corpus.py 自建的 md 文档记忆库（336 节点），但用 **marks=False 的纯
叙述正文** 写入 —— 模拟「从旧库迁移来的节点」，这样维度9 的「完整度不得虚报」
才有对照物（只有本测试显式写的完整 CCG 节点才该被 health 计入）。
旧版依赖 wisdom-book-cloud-new.db（迁移 + sqlite Top-5 基线）；本仓库按「用新的
md 文档记忆库做验证」改为 md 原生，不再依赖任何外部数据库。

说明：测试自建节点全部用「完整 CCG 正文」格式 + domain:数学 tag（否则
资格判定会因 MARKS 不全而 BLINDSPOT——那是正确行为，不是 bug）。
固定 id → 幂等可重跑；不靠清空目录（见 corpus.reset_root），重跑 ≡ 首跑由
「knowledge 层节点数 == 语料数 + 本测试显式写入数」的等号断言守门。

跑法：python -m md_cg.test_p1
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mdcg import (MdCG, STATE_ACCEPT, STATE_REJECT, STATE_DEFER,
                        STATE_BLINDSPOT)
from md_cg import nodefile, routing, corpus

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(_BASE, "_md_cg_p1")
DOM_TAG = ["domain:数学"]

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}"
          + (f"   · {detail}" if detail not in ("", None) else ""))
    return cond


def ccg_body(subject, verify="由第 5 章实验记录验证", neg="无需例外"):
    """构造完整 CCG 5 要素正文（第 1 篇第 17 章格式）。"""
    return (f"# 功能名：{subject}\n"
            f"# 生效条件：默认满足\n"
            f"# 子功能：对 {subject} 建立白箱资格判定\n"
            f"# 执行：检索 {subject} 相关条件证据\n"
            f"# 验证方式：{verify}\n"
            f"# 不适用条件：{neg}\n"
            f"{subject} 的白箱执行正文。")


def main():
    print("=" * 68)
    print("md 认知图 P1 验收 · 白箱认知架构 9 维度")
    print("=" * 68)

    # 自建 md 语料（纯叙述正文、无 MARKS）替代「从 sqlite 迁移」这一步：
    # 维度9 要验「叙述节点不得被计为 CCG 完整」，迁移节点只是它的一个实例
    corpus.reset_root(ROOT)
    cg = MdCG(ROOT, autoflush=64)
    written = corpus.seed(cg, marks=False)
    cg.rebuild_index()
    print(f"自建 md 语料：{written} 节点（纯叙述正文，模拟旧库迁移节点）\n")

    # ===================================================== 维度 1
    print("【维度1】MARKS 5 要素 + 验证基底 + 不适用条件（白箱第 1 篇第 17 章）")
    cg.add("p1_ok", ccg_body("能量守恒的判定"),
           layer="knowledge", tags=DOM_TAG,
           verification_basis="formal_proof",
           non_applicable_conditions=["开放系统"])
    cg.flush()
    fm = cg.get("p1_ok")["frontmatter"]
    check("frontmatter 含 verification_basis（枚举内）",
          fm.get("verification_basis") == "formal_proof")
    check("frontmatter 含 non_applicable_conditions",
          fm.get("non_applicable_conditions") == ["开放系统"])
    cpl = nodefile.ccg_completeness(cg.get("p1_ok")["content"])
    check("完整 CCG 正文 → complete=True",
          cpl["complete"] is True, f"required_present={cpl['required_present']}")
    bad_vb = False
    try:
        cg.add("p1_badvb", ccg_body("x"), verification_basis="magic_guess")
    except ValueError:
        bad_vb = True
    check("非法 verification_basis 被拒（枚举约束）", bad_vb)

    # ===================================================== 维度 2
    print("\n【维度2】负记忆目录（白箱第 5 篇 L2/L5）")
    rej1 = cg.add_rejected(hypothesis="绿按钮是传送门",
                           reason="按了 5 次门都没反应",
                           verification_basis="test")
    rej2 = cg.add_rejected(hypothesis="绿按钮是传送门",
                           reason="按了 5 次门都没反应")
    check("add_rejected 幂等（同假设不重复）", rej1 == rej2)
    cg.add_unresolved(question="白箱资格判定能否跨域迁移",
                      known_clues="CCG 5 要素在数学域 100%",
                      goal="找反例")
    check("rejected/ 目录存在且有节点",
          os.path.isdir(os.path.join(ROOT, "rejected")) and
          any(f.endswith(".md") for f in os.listdir(os.path.join(ROOT, "rejected"))))
    check("unresolved/ 目录存在且有节点",
          os.path.isdir(os.path.join(ROOT, "unresolved")) and
          any(f.endswith(".md") for f in os.listdir(os.path.join(ROOT, "unresolved"))))
    # rejected 的 MARKS 必填 = 假设/否决原因/验证（与 knowledge 不同）
    rej_doc = cg.get(rej1)
    check("rejected 节点用自身 MARKS（假设/否决原因）",
          rej_doc and "# 假设：" in rej_doc["content"] and
          "# 否决原因：" in rej_doc["content"])

    # ===================================================== 维度 3
    print("\n【维度3】资格判定四态（与性能 tier 正交）")
    # 4 个测试节点正文都要含查询词「白箱资格判定」，否则召回不了（score=0 不返回）
    cg.add("p1_accept", ccg_body("纯数学恒等式证明的白箱资格判定"),
           tags=DOM_TAG, verification_basis="formal_proof",
           non_applicable_conditions=["需要测量的物理量"])
    cg.add("p1_defer", ccg_body("未经验证的观察假设的白箱资格判定"),
           tags=DOM_TAG, non_applicable_conditions=[])
    # BLINDSPOT：CCG 不完整（只给功能名），但仍含查询词可被召回
    cg.add("p1_spot",
           "# 功能名：残缺知识\n白箱资格判定正文没写完整要素。",
           tags=DOM_TAG, verification_basis="test")
    # REJECT：不适用条件命中 context（同一 query，context 含海拔词）
    cg.add("p1_reject", ccg_body("海拔环境的白箱资格判定"),
           tags=DOM_TAG, verification_basis="test",
           non_applicable_conditions=["海拔 > 5000 米"])
    cg.flush()

    ctx = {"tags": DOM_TAG, "环境": "当前测量在海拔 > 5000 米进行"}
    r, m = cg.search("白箱资格判定", k=30, context=ctx)
    states = {x[0]["id"]: x[2]["state"] for x in r}
    check("CCG 完整+基底+条件未命中 → ACCEPT",
          states.get("p1_accept") == STATE_ACCEPT, str(states.get("p1_accept")))
    check("CCG 完整但无验证基底 → DEFER",
          states.get("p1_defer") == STATE_DEFER, str(states.get("p1_defer")))
    check("CCG 要素不全 → BLINDSPOT",
          states.get("p1_spot") == STATE_BLINDSPOT, str(states.get("p1_spot")))
    check("不适用条件命中 → REJECT",
          states.get("p1_reject") == STATE_REJECT, str(states.get("p1_reject")))
    check("被 REJECT 的节点仍被召回（资格≠性能）",
          "p1_reject" in states, f"tier={m['tier']}")

    # ===================================================== 维度 4
    print("\n【维度4】Top-1 / Top-5 / 盲区触发率（第 1 篇第 9 章 CCG 指标）")
    # 真值来源：客观 oracle —— 正文含查询词的 knowledge 节点全集（即 LIKE 的严格定义）。
    # 旧版拿 sqlite 版 Top-5 当基线，本质是「拿另一个实现的排序偏好当真值」；
    # md 原生下换成 oracle 反而更硬：它不依赖任何实现的排序，只依赖语料事实。
    queries = ["能量守恒", "二分查找", "细胞呼吸", "贝塞尔不等式", "牛顿第二定律",
               "光合作用", "事务隔离", "内力与截面法", "熵增", "机会成本"]
    contents = {nid: (cg.get(nid) or {}).get("content", "")
                for nid, e in cg.index["nodes"].items() if e["layer"] == "knowledge"}
    t1 = t5 = 0
    n = 0
    blindspots = []
    print(f"  {'query':<14}{'真值集':>7}{'召回':>6}{'Top-1':>7}")
    for q in queries:
        gold = [nid for nid, c in contents.items() if q in c]
        if not gold:
            blindspots.append(q)
            continue
        n += 1
        r, _m = cg.search(q, layer="knowledge", k=5, context=None, judge=False)
        got = [x[0]["id"] for x in r]
        hit = set(got) & set(gold)
        top1_ok = bool(got) and got[0] in gold
        if top1_ok:
            t1 += 1
        if hit:
            t5 += 1
        print(f"  {q:<14}{len(gold):>7}{len(hit):>6}{'是' if top1_ok else '否':>7}")
    top1, top5 = (t1 / n if n else 0.0), (t5 / n if n else 0.0)
    print(f"  Top-1 = {top1:.0%}（md Top-1 落在客观真值集内）")
    print(f"  Top-5 = {top5:.0%}，无真值（盲区）查询 = {blindspots}")
    check("Top-1 ≥ 0.7（最强证据放在最前）", top1 >= 0.7, f"{top1:.0%}")
    check("Top-5 ≥ 0.9（不漏召回）", top5 >= 0.9, f"{top5:.0%}")
    check("无盲区（每个查询在语料中都有真值）", not blindspots, str(blindspots))

    # ===================================================== 维度 5
    print("\n【维度5】两阶段并行收敛路由（第 2 篇第 5 章 + 第 3 篇第 4 章）")
    check("物理词收敛到物理大域",
          routing.big_domain_classify(["能量守恒", "海拔", "沸点"]) == "物理")
    check("数学词收敛到数学大域",
          routing.big_domain_classify(["贝塞尔不等式", "矩阵", "证明"]) == "数学")
    check("生物词收敛到生物大域",
          routing.big_domain_classify(["细胞呼吸", "光合作用", "酶"]) == "生物")
    check("无命中词 → None（不做错误收敛）",
          routing.big_domain_classify(["qzzzz完全虚构"]) is None)
    r, m = cg.search("能量守恒", k=5, context=None)
    check("search meta 报告大域收敛",
          m.get("big_domain") == "物理", f"big_domain={m.get('big_domain')}")
    scores = m.get("big_domain_scores", {})
    check("大域打分明细可审计",
          isinstance(scores, dict) and scores.get("物理", 0) >= 1 and
          scores["物理"] == max(scores.values()),
          f"scores[物理]={scores.get('物理')}")

    # ===================================================== 维度 6
    print("\n【维度6】信息差 D(t,C) 与 d²D/dt²（第 3/4 篇）")
    # 无结果查询 → D=1.0（信息差空白）；含 ACCEPT 结果 → D 应显著回落
    rf_empty = cg.reflect("完全虚构词 qzzzz", [])
    fake_hit = [({"id": "x", "frontmatter": {}, "content": "c"}, 1.0,
                 {"state": "ACCEPT"})]
    rf_hit = cg.reflect("能量守恒", fake_hit)
    check("无结果查询 → D=1.0（信息差空白）",
          rf_empty["d_curr"] == 1.0, f"D={rf_empty['d_curr']:.2f}")
    check("有效命中 → D 显著回落（D=D(t,C) 演化）",
          rf_hit["d_curr"] <= 0.5, f"D={rf_hit['d_curr']:.2f}")
    check("d_delta（一阶变化）被记录", "d_delta" in rf_hit)
    check("d2 = d²D/dt² 被计算", "d2" in rf_hit,
          f"d2={rf_hit.get('d2')}")
    check("反思日志追加落盘",
          os.path.exists(cg.reflection_log) and os.path.getsize(cg.reflection_log) > 0)

    # ===================================================== 维度 7
    print("\n【维度7】知识飞轮（第 2 篇第 8 章：误差→找条件→更新）")
    fw = cg.flywheel_step({"query": "能量守恒", "expected_state": "ACCEPT",
                           "actual_state": "BLINDSPOT",
                           "missing": "缺少开放/封闭系统的条件分支"})
    unr_doc = cg.get(fw["unresolved_id"])
    check("飞轮产出 unresolved 条目", unr_doc is not None and
          "已知线索" in unr_doc["content"])
    # 飞轮是知识闭环入口：同一 query 再次遇盲区不重复建条目（幂等）
    fw2 = cg.flywheel_step({"query": "能量守恒", "expected_state": "ACCEPT",
                            "actual_state": "BLINDSPOT",
                            "missing": "缺少开放/封闭系统的条件分支"})
    check("飞轮幂等（同问题不重复产条目）",
          fw["unresolved_id"] == fw2["unresolved_id"])

    # ===================================================== 维度 8
    print("\n【维度8】验证单元（第 3 篇第 13 章）")
    cg.add("p1_verify", ccg_body("验证目标卡片"), tags=DOM_TAG,
           verification_basis="test")
    cg.flush()
    pre = float(cg.get("p1_verify")["frontmatter"]["confidence"])
    cg.verify("p1_verify", "通过 5 次实验确认", "confirmed")
    post = float(cg.get("p1_verify")["frontmatter"]["confidence"])
    check("confirmed → confidence 上调", post > pre, f"{pre} → {post}")
    # weakened：confidence 非对称下调（反例权重大于正例）
    pre2 = float(cg.get("p1_verify")["frontmatter"]["confidence"])
    cg.verify("p1_verify", "与另一实验组结果不符", "weakened")
    post2 = float(cg.get("p1_verify")["frontmatter"]["confidence"])
    check("weakened → confidence 下调", post2 < pre2, f"{pre2} → {post2}")
    # falsified：add_rejected 按内容 hash 幂等，故断言「存在负记忆条目」而非计数增量
    cg.verify("p1_verify", "发现反例：条件不成立", "falsified")
    neg_ids = [e.get("path") for e in cg.index["nodes"].values()
               if e["layer"] == "rejected"]
    neg_hit = False
    for p in neg_ids:
        full_p = os.path.join(ROOT, p)
        try:
            with open(full_p, encoding="utf-8") as f:
                neg_hit = neg_hit or "验证目标卡片" in f.read()
        except OSError:
            pass
    check("falsified → 节点负记忆化（rejected/ 出现对应条目）", neg_hit,
          f"rejected 节点数={len(neg_ids)}")
    gone = cg.get("p1_verify")
    check("falsified 后原 knowledge 节点被移除", gone is None,
          "p1_verify 已不在 knowledge")

    # ===================================================== 维度 9
    print("\n【维度9】CCG 完整度 + 验证基底覆盖率（health 自检）")
    # 守门断言（重跑 ≡ 首跑）：既然不再靠清空目录（见 corpus.reset_root），
    # 「knowledge 层恰好 = 语料 + 本测试显式写入」就必须被显式守住——
    # 有残留节点会在这里打红，而不是被 rmtree 静默掩盖。
    explicit_knowledge = ("p1_ok", "p1_accept", "p1_defer", "p1_spot", "p1_reject")
    n_know = sum(1 for e in cg.index["nodes"].values() if e["layer"] == "knowledge")
    check("重跑 ≡ 首跑：knowledge 层节点数不多不少（无残留污染）",
          n_know == corpus.EXPECTED_NODES + len(explicit_knowledge),
          f"{n_know} == {corpus.EXPECTED_NODES} + {len(explicit_knowledge)}")
    h = cg.health()
    kb = h.get("ccg_by_layer", {}).get("knowledge", {})
    rej_cnt = h.get("neg_memory_counts", {}).get("rejected", 0)
    unr_cnt = h.get("neg_memory_counts", {}).get("unresolved", 0)
    check("health 报告 knowledge 层 CCG 完整度统计",
          kb.get("total", 0) >= corpus.EXPECTED_NODES and "ccg_complete" in kb,
          f"total={kb.get('total')}")
    check("health 报告负记忆密度（rejected/unresolved 均 >0）",
          rej_cnt >= 1 and unr_cnt >= 1,
          f"rejected={rej_cnt}, unresolved={unr_cnt}")
    # 叙述节点（无 MARKS）不得被计为完整；只有我们显式写的完整 CCG 才算
    full_ids = [nid for nid in ("p1_ok", "p1_accept", "p1_defer", "p1_reject")
                if cg.get(nid) and nodefile.ccg_completeness(
                    cg.get(nid)["content"])["complete"]]
    expected_full = len(full_ids)
    # corpus.seed(marks=False) 的 336 个节点是纯叙述正文（不含 MARKS 行）→ 不被计入；
    # 我们显式写的完整 CCG 节点必须都被统计到
    check("所有完整 CCG 测试节点均被 health 计入",
          kb.get("ccg_complete", 0) >= expected_full,
          f"expected>= {expected_full}, got={kb.get('ccg_complete')}")
    check("叙述节点完整度不虚报（完整数远小于总数）",
          kb.get("ccg_complete", 0) < kb.get("total", 0) * 0.05,
          f"complete={kb.get('ccg_complete')}/{kb.get('total')}")

    print("\n" + "=" * 68)
    print(f"通过 {len(PASS)} / 失败 {len(FAIL)}")
    if FAIL:
        print("失败项：\n  - " + "\n  - ".join(FAIL))
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    # 用 reconfigure 而非「包一层 TextIOWrapper」：后者在 stdout 重定向到文件时
    # 会在解释器退出阶段丢缓冲，CI 里会看不到失败原因。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())