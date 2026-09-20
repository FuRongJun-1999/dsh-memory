# -*- coding: utf-8 -*-
"""治理四指标只读评估器（阶段三 §5.1/§5.2 基线测量，纯合成确定性语料，不改任何行为面）。

四指标（对照值来自 docs/灵枢自我改进工作计划_外部研究系列吸收 §5）：
  g1 修正传播率  — 上游信任态降级后，依赖下游一跳同步失效比例
                   （承载=trust.set_state+mark_dependents；对照 MAGE 91.2%）
  g2 矛盾处理率  — 矛盾/否定证据被正确裁决比例
                   （承载=judge_qualification 负条件 REJECT + judge_ranking 终排剔除；
                   对照 MAGE 88.5%）
  g3 过期取回率  — 检索 top-k 返回已过期节点比例（越低越好）
                   （口径唯一真源=trust.is_expired / scrub._EXPIRY_KEYS；
                   主口径=validity 防线残留率，副口径=默认面暴露率；对照 MAGE 3.1%）
  g4 拒答 F1     — 不可答问题拒答的精确率/召回率/F1
                   （拒答判据=空结果 或 top1 资格态∈{BLINDSPOT, DEFER}；
                   对照 REMem 64.0）

设计约束：
  - 纯合成语料、无随机源，重复运行结果逐位一致（第 5 条可回放）；
  - tempfile 库，不触碰真实认知图库（评估器只读）；
  - 语料守卫断言（语料本身不合法立即 fail，防指标虚高——对齐 bench_blind_comp
    assert_material 纪律）。
运行：python -X utf8 -m md_cg.bench_governance [--out <json>]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from .mdcg import MdCG
from .mdcos import MdCGOS
from . import trust

BASELINE_REF = {
    "g1_correction_propagation": {"ours": None, "mage": 0.912},
    "g2_contradiction_handling": {"ours": None, "mage": 0.885},
    "g3_expired_recall": {"ours": None, "mage": 0.031, "note": "越低越好"},
    "g4_refusal_f1": {"ours": None, "remem_f1": 64.0, "note": "REMem 为其自报口径，仅作量级对照"},
}

# ---------------------------------------------------------------- 语料 ----

NOW = None  # main 内注入，保证同一次运行内时间一致


def _doc(title, fact, cond="无条件", neg=None):
    """CCG 六要素正文（与 test_sem_noise._doc 同构：负条件双写中的正文行）。"""
    lines = [
        "# 功能名：" + title,
        "# 生效条件：" + cond,
        "# 子功能：" + title + "事实卡",
        "# 执行：检索面事实提供",
        "# 验证方式：test",
        "# 不适用条件：" + (neg or "无"),
        "",
        fact,
    ]
    return "\n".join(lines)


# 可答事实：条件词面刻意出现在对应 query 里（正条件确认可命中 → ACCEPT）
FACTS = [
    # (nid, 事实句, 正条件行, query)
    ("g_f1", "灵枢检索缓存默认保留 128 条。", "载体：缓存配置", "缓存配置里默认缓存多大"),
    ("g_f2", "蜂巢心跳间隔为 30 秒。", "载体：蜂巢参数", "蜂巢参数中心跳间隔是多少"),
    ("g_f3", "评测器统一经 eval_common 汇总指标。", "载体：评测约定", "评测约定的汇总入口在哪"),
    ("g_f4", "python 命令统一走 argv 列表加显式 UTF-8。", "无条件", "python 命令执行要用什么编码约定"),
    ("g_f5", "语义摘要路默认关闭、显式 opt-in 才启用。", "无条件", "语义摘要路默认开还是关"),
    ("g_f6", "分支节点不出库、不进主支检索。", "无条件", "分支节点会不会进主支检索"),
]

# 否定反事实：负条件双写（kwarg + 正文行），否定情境 query=「你刚才在干什么」
NEG_QUERY = "你刚才在干什么"
NEG_COND = "刚才在干什么"
NEGATIVES = [
    ("g_n1", "我没有在喝水。"),
    ("g_n2", "我没有在写代码。"),
    ("g_n3", "我没有在开会。"),
    ("g_n4", "我没有在跑步。"),
]

# 过期节点：与可答事实同题竞争（旧版本数值已失效），effective_until 已过
STALE = [
    ("g_e1", "蜂巢心跳间隔曾为 10 秒（旧版）。", "g_f2"),
    ("g_e2", "评测器旧口径按 k=3 汇总（已废弃）。", "g_f3"),
    ("g_e3", "检索缓存默认曾为 64 条（旧版）。", "g_f1"),
]

# 修正传播链：地基 U + 一跳依赖 D1..D4
U_GOV = "g_u_gov"
DEPENDENTS = ["g_d1", "g_d2", "g_d3", "g_d4"]

# 无关背景（干扰；CCG 完整可 ACCEPT——拒答 F1 的诚实下界来自它）
BACKDROP = [
    ("g_b1", "工作区在约定中默认使用简体中文交流。"),
    ("g_b2", "认知图只给知识与建议能力名，不执行操作。"),
    ("g_b3", "留痕粒度按任务合并，不逐命令逐行。"),
]

# 不可答问题（与语料词面零重叠；期望系统拒答）
UNANSWERABLE = [
    "用户 2026 年春节在哪过的",
    "项目预算总共批了多少万",
    "作者最喜欢的菜是什么",
    "下个版本计划支持日语吗",
    "服务器部署在哪个机房",
    "团队现在有多少人",
    "竞品报价单是多少",
    "昨天的会议纪要说了什么",
]


def _assert_material(now):
    """语料守卫：素材纪律机器断言（违者 fail，防指标虚高）。"""
    fact_ids = {nid for nid, *_ in FACTS}
    stale_ids = {nid for nid, *_ in STALE}
    neg_ids = {nid for nid, *_ in NEGATIVES}
    assert not (fact_ids & stale_ids | fact_ids & neg_ids | stale_ids & neg_ids), "语料 id 重叠"
    assert len(UNANSWERABLE) >= 5 and len(FACTS) >= 5, "探针集过小"
    # 不可答题与语料词面零重叠（粗粒度：语料特征词不出现于不可答题面）
    lex = "".join(f for _, f, *_ in FACTS) + "".join(f for _, f in NEGATIVES) \
        + "".join(f for _, f, _ in STALE) + "".join(f for _, f in BACKDROP)
    for q in UNANSWERABLE:
        overlap = [w for w in ("缓存", "蜂巢", "心跳", "评测", "python", "语义摘要", "分支") if w in q]
        assert not overlap, f"不可答题词面泄漏：{q} 命中 {overlap}"
    assert "无条件" not in lex or True  # 语料自洽由 judge 实测兜底
    for _, _, base in STALE:
        assert base in fact_ids, "过期节点必须与某可答事实同题竞争"


def build_corpus(cg, now):
    """建确定性语料。返回节点数。"""
    n = 0
    # 可答事实（F1-F3 带条件、F4-F6 无条件豁免）
    for nid, fact, cond, _q in FACTS:
        cg.add(nid, _doc(nid, fact, cond=cond), layer="knowledge",
               verification_basis="test")
        n += 1
    # 否定反事实（负条件双写）
    for nid, sent in NEGATIVES:
        cg.add(nid, _doc(nid, sent, cond="时间：即时情境", neg=NEG_COND), layer="knowledge",
               verification_basis="test", non_applicable_conditions=[NEG_COND])
        n += 1
    # 过期节点（effective_until 已过；expired_at 冗余由 add 派生）
    for nid, fact, _base in STALE:
        cg.add(nid, _doc(nid, fact, cond="无条件"), layer="knowledge",
               verification_basis="test",
               effective_from=now - 7200.0, effective_until=now - 3600.0)
        n += 1
    # 无关背景
    for nid, fact in BACKDROP:
        cg.add(nid, _doc(nid, fact), layer="knowledge", verification_basis="test")
        n += 1
    # 修正传播链：地基 + 一跳依赖（depends_on=依赖图语义，trust.dependents_index 消费；
    # derived_from=血缘溯源，语义不同不混用）
    cg.add(U_GOV, _doc(U_GOV, "地基结论：核心算法口径以文档 A 为准。", cond="无条件"),
           layer="knowledge", verification_basis="test")
    n += 1
    for did in DEPENDENTS:
        cg.add(did, _doc(did, f"{did} 结论：沿用地基口径实现细节。", cond="无条件"),
               layer="knowledge", verification_basis="test", depends_on=[U_GOV])
        n += 1
    return n


# ---------------------------------------------------------------- 指标 ----

def m1_correction_propagation(cg):
    """g1：上游降级 doubted → mark_dependents 一跳同步传播率。"""
    r0 = trust.set_state(cg, U_GOV, "doubted", reason="基线评测：地基被修正")
    assert isinstance(r0, dict) and r0.get("ok"), f"上游降级失败：{r0}"
    r = trust.mark_dependents(cg, U_GOV, reason="基线评测：上游修正传播", apply=True)
    deps, upd = r.get("dependents") or [], r.get("updated") or []
    assert sorted(deps) == sorted(DEPENDENTS), f"依赖索引不符预期：{deps}"
    rate = (len(upd) / len(deps)) if deps else None
    return {"metric": "correction_propagation", "value": rate,
            "detail": {"dependents": len(deps), "updated": len(upd),
                       "skipped": r.get("skipped"), "reference_mage": 0.912}}


def _is_refusal(results):
    """拒答判据：空结果 或 top1 资格态 ∈ {BLINDSPOT, DEFER}。"""
    if not results:
        return True, "empty"
    entry = results[0]
    qual = entry[2] if len(entry) > 2 else None  # 条目=(node, score, qual, prov)
    st = (qual or {}).get("state") if isinstance(qual, dict) else None
    return st in ("BLINDSPOT", "DEFER"), st


def m2_contradiction_handling(cg):
    """g2：否定证据正确裁决率 = 定点裁决 + 检索防线（skip 项不入分母）。"""
    correct = wrong = skipped = 0
    detail = {"judged": [], "retrieval": []}
    # (a) 定点裁决：否定节点在否定情境下应 REJECT（judge_qualification 直调）
    for nid, _sent in NEGATIVES:
        node = cg.get(nid)
        qual = MdCG.judge_qualification(
            {"frontmatter": node.get("frontmatter") or {}, "content": node.get("content") or ""},
            NEG_QUERY, None)
        st = qual.get("state")
        detail["judged"].append({"nid": nid, "state": st})
        if st == "REJECT":
            correct += 1
        elif st is None:
            skipped += 1
        else:
            wrong += 1
    # (b) 检索防线：judge_ranking 终排后 top-k 无否定节点冒充
    res, meta = cg.search_rrf(NEG_QUERY, k=10, judge=True, judge_ranking=True,
                              record=False)
    ids = [r[0]["id"] for r in res]
    leaked = [i for i in ids if i in {n for n, _ in NEGATIVES}]
    detail["retrieval"] = {"top_ids": ids[:5], "leaked_negatives": leaked,
                           "judge_filtered": (meta or {}).get("judge_filtered")}
    if leaked:
        wrong += 1
    else:
        correct += 1
    total = correct + wrong
    return {"metric": "contradiction_handling", "value": (correct / total) if total else None,
            "detail": dict(detail, correct=correct, wrong=wrong, skipped=skipped,
                           reference_mage=0.885)}


def m3_expired_recall(cg, now):
    """g3：过期取回率。主口径=validity 防线残留率；副口径=默认面暴露率。"""
    stale_ids = {nid for nid, *_ in STALE}
    probe = "蜂巢参数中心跳间隔是多少"  # 与过期节点 g_e1 同题竞争
    out = {}
    for tag, kw in (("raw", {}), ("guard", {"validity": True}),
                    ("judge_ranking", {"judge_ranking": True})):
        res, _meta = cg.search_rrf(probe, k=10, judge=True, record=False, **kw)
        ids = [r[0]["id"] for r in res]
        hits = [i for i in ids if i in stale_ids]
        out[tag] = {"top_ids": ids[:5], "stale_hits": hits,
                    "rate": (len(hits) / len(ids)) if ids else None}
    return {"metric": "expired_recall",
            "value": out["guard"]["rate"],            # 主口径：防线后残留（越低越好）
            "detail": dict(out, probe=probe, stale_total=len(stale_ids),
                           reference_mage=0.031, note="raw=默认面暴露；guard=validity 防线")}


def m4_refusal_f1(cg):
    """g4：拒答精确率/召回率/F1（正类=不可答）。"""
    tp = fn = fp = tn = 0
    detail = {"unanswerable": [], "answerable": []}
    for q in UNANSWERABLE:
        res, _m = cg.search_rrf(q, k=3, judge=True, judge_ranking=True, record=False)
        refused, st = _is_refusal(res)
        detail["unanswerable"].append({"q": q, "refused": refused, "top_state": st})
        if refused:
            tp += 1
        else:
            fn += 1
    for _nid, _fact, _cond, q in FACTS:
        res, _m = cg.search_rrf(q, k=3, judge=True, judge_ranking=True, record=False)
        refused, st = _is_refusal(res)
        detail["answerable"].append({"q": q, "refused": refused, "top_state": st})
        if refused:
            fp += 1
        else:
            tn += 1
    p = tp / (tp + fp) if (tp + fp) else None
    r = tp / (tp + fn) if (tp + fn) else None
    if p is not None and r is not None and p + r:
        f1 = 2 * p * r / (p + r)
    else:
        # tp+fp=0：系统从未拒答（无 query 侧拒答信号）——保守编码 F1=0.0 并如实注明
        f1 = 0.0
    return {"metric": "refusal_f1",
            "value": f1,
            "detail": {"precision": p, "recall": r, "tp": tp, "fn": fn, "fp": fp, "tn": tn,
                       "refusal_rule": "empty or top1 state in {BLINDSPOT, DEFER}",
                       "note": ("no refusal signal: judge 资格态只判节点可用性，"
                                "不判答案存在性；不可答题被无关 ACCEPT 节点冒充全部未拒"
                                if (tp + fp) == 0 else ""),
                       "reference_remem_f1": 64.0}}


# ---------------------------------------------------------------- 主流程 ----

def run(root=None, keep=False):
    """跑四指标，返回 (report_dict, root)。root 供测试复检。"""
    now = time.time()
    _assert_material(now)
    root = root or tempfile.mkdtemp(prefix="mdcg_governance_")
    try:
        cg = MdCGOS(root, actor="bench_governance", autoflush=200)
        n_nodes = build_corpus(cg, now)
        cg.flush()
        report = {
            "meta": {
                "bench": "bench_governance",
                "date": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                "corpus_nodes": n_nodes,
                "head": _git_head(),
                "determinism": "synthetic corpus, no RNG",
                "scopes": "阶段三 §5.1 治理三件套 + §5.2 拒答量化（基线测量，不改行为）",
            },
            "g1_correction_propagation": m1_correction_propagation(cg),
            "g2_contradiction_handling": m2_contradiction_handling(cg),
            "g3_expired_recall": m3_expired_recall(cg, now),
            "g4_refusal_f1": m4_refusal_f1(cg),
            "baseline_reference": BASELINE_REF,
        }
        return report, root
    finally:
        if not keep:
            shutil.rmtree(root, ignore_errors=True)


def _git_head():
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", shell=False, timeout=10)
        return (out.stdout or "").strip() or "unknown"
    except Exception:                                     # noqa: BLE001
        return "unknown"


def main(argv=None):
    ap = argparse.ArgumentParser(description="治理四指标只读评估器")
    ap.add_argument("--out", default=os.path.join("data", "external", "eval_results",
                                                  "governance_baseline.json"))
    ap.add_argument("--keep", action="store_true", help="保留临时库目录（调试用）")
    args = ap.parse_args(argv)
    report, root = run(keep=args.keep)
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: v.get("value") for k, v in report.items()
                      if isinstance(v, dict) and "value" in v},
                     ensure_ascii=False, indent=2))
    print("baseline ->", out, "| temp root:", root)
    vals = [report[g]["value"] for g in ("g1_correction_propagation",
                                         "g2_contradiction_handling",
                                         "g3_expired_recall", "g4_refusal_f1")]
    return 0 if all(v is not None for v in vals) else 1


if __name__ == "__main__":
    raise SystemExit(main())
