# -*- coding: utf-8 -*-
"""LoCoMo（mteb/LoCoMo BEIR 转制版）T-REC 复跑：三组分报 hit@1 + adversarial 负例组。

v2.0 三组映射（报告须声明）：
    精确回溯 → single_hop        （单证据事实回溯，840 题）
    时序推理 → temporal_reasoning（时间计算/排序，321 题）
    干扰抑制 → multi_hop         （长对话多话题干扰下组合多证据，280 题）
    负例组   → adversarial       （涉及对话未提及/矛盾信息，应拒答，446 题）
    参考组   → open_domain       （不计入三组，89 题）
干扰组通过线 ≥80%（hit@1，v2.0 标尺）；只报总分 = 不通过。

负例拒答口径：Top-1 融合分 < 校准线（正例 hit@1 题 Top-1 分的 10 分位）判拒答。
口径为「证据命中」机判，非 LLM-judge，与论文口径不可直接比较。

双口径（报告分栏声明，eval_common 模块头有完整口径说明）：
    口径 A legacy     -- 默认。原始 turn 裸文本入库，四路基线（lexical,bucket,
                         entity,graph）：测检索底座下界（entity/bucket 两路
                         天然空转、负路由不参与）。
    口径 B calibrated -- --calibrated。确定性白箱标定器把 turn 加工为 CCG
                         五要素 md 条目 + tags + condition_space 入库，四路 +
                         semantic（条件结构路，负路由所在）：测记忆系统完整
                         形态。标定器纯规则、零 LLM、盲于查询集，可重放。

跑法：
    python -m md_cg.bench_locomo                    # 口径 A 全量 1976 题
    python -m md_cg.bench_locomo --calibrated       # 口径 B 全量
    python -m md_cg.bench_locomo --n 100            # 每组抽样 100 题
"""
import argparse

from md_cg import eval_common as ec

GROUPS = {
    "precise": ("single_hop",),
    "temporal": ("temporal_reasoning",),
    "interference": ("multi_hop",),
    "negative": ("adversarial",),
    "reference": ("open_domain",),
}
POS_GROUPS = ("precise", "temporal", "interference")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=0, help="每组抽样上限（0=全量）")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--calibrated", action="store_true",
                    help="口径 B：五要素标定入库 + semantic 路启用")
    ap.add_argument("--rebuild", action="store_true",
                    help="删库重建（标定器改版后必须）")
    ap.add_argument("--paths", default=None,
                    help="覆盖召回路（逗号分隔），用于按路拆解归因，如 lexical")
    ap.add_argument("--fusion", default=None, choices=["sum", "max"],
                    help="覆盖 RRF 融合方式（sum=等权共识，max=单路独出不稀释）")
    ap.add_argument("--weights", default=None,
                    help="覆盖路权重（如 lexical:1,entity:0.2,semantic:0.2），压低噪声路")
    args = ap.parse_args()
    cal = args.calibrated
    if args.paths:
        ec.PATHS_CAL = ec.PATHS = tuple(args.paths.split(","))
        print(f"  [拆解] 召回路覆盖为 {ec.PATHS_CAL}")
    wmap = None
    if args.weights:
        wmap = {p.split(":")[0]: float(p.split(":")[1])
                for p in args.weights.split(",")}
        print(f"  [拆解] 路权重覆盖为 {wmap}")

    print(f"== LoCoMo T-REC 复跑（k={args.k}，口径 {'B 标定' if cal else 'A legacy'}，"
          f"{'全量' if not args.n else f'每组≤{args.n}'}）==")
    ec.unlock_global_cap()   # 口径：解除 LIKE 预筛的插入序截断
    # 不切 jaccard：LoCoMo 是短对话语料，而 jaccard 的收益随文档长度单调增长
    # （短文档组仅「基本持平或微降」，见 mdcg.lexical_sim 口径注释）→ 保持 legacy。
    cg = ec.build_eval_cg(None, ec.ROOT_LC_CAL if cal else ec.ROOT_LC,
                          ec.LC_CORPUS, ec.lc_turn_text, "locomo",
                          calib_of=ec.calibrate_lc_turn if cal else None,
                          rebuild=args.rebuild)
    ec.install_read_cache(cg)

    paths = ec.PATHS_CAL if cal else ec.PATHS
    rows_by = {}
    for gname, qtypes in GROUPS.items():
        qs = ec.sample_questions(ec.load_questions("lc", qtypes=qtypes), args.n)
        print(f"  [{gname}] {len(qs)} 题 …")
        rows_by[gname] = ec.evaluate_group(cg, qs, k=args.k, paths=paths,
                                           fusion=args.fusion,
                                           path_weights=wmap)

    pos_rows = [r for g in POS_GROUPS for r in rows_by[g]]
    line = ec.calibrate_line(pos_rows)
    neg = ec.refusal_metrics(rows_by["negative"], line)
    neg_false_pos = ec.false_refusal_rate(rows_by["negative"], line)  # 负例中被误当正例
    pos_false_refusal = ec.false_refusal_rate(pos_rows, line)         # 正例被误拒

    groups = {g: ec.summarize(rows_by[g], k=args.k) for g in GROUPS}
    ec.print_table(f"LoCoMo T-REC 三组 + 负例组（口径 {'B 标定' if cal else 'A legacy'}）",
                   groups, k=args.k)
    print(f"\n拒答线（正例 hit@1 题 Top-1 分 p10）：{line:.6f}")
    print(f"负例组（adversarial）拒答率：{ec.pct(neg['refusal_rate'])}"
          f"（{neg['refused']}/{neg['n']}）")
    print(f"正例误拒率（Top-1 分 < 线）：{ec.pct(pos_false_refusal)}")
    gate = {"interference_hit1": groups["interference"].get("hit@1", 0.0),
            "interference_pass": groups["interference"].get("hit@1", 0.0) >= 0.80,
            "negative_refusal": neg["refusal_rate"], "calibrated_line": line}
    print(f"干扰组 gate（≥80%）：{'PASS' if gate['interference_pass'] else 'FAIL'}")

    ec.save_result("trec_locomo_cal.json" if cal else "trec_locomo.json", {
        "dataset": "LoCoMo (mteb/LoCoMo BEIR)",
        "caliber": "B-calibrated（五要素标定 + semantic 路）" if cal
                   else "A-legacy（裸 turn，四路基线）",
        "metric_caliber": "evidence-hit（qrels 标注命中），非 LLM-judge",
        "paths": list(paths),
        "k": args.k, "sampling": args.n or "full",
        "groups": groups, "negative": neg,
        "false_refusal_pos": pos_false_refusal,
        "gate": gate,
        "group_mapping": {g: list(q) for g, q in GROUPS.items()},
    })


if __name__ == "__main__":
    main()
