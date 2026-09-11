# -*- coding: utf-8 -*-
"""LongMemEval-S（xiaowu0162/LongMemEval）T-REC 复跑：三组分报 hit@1。

v2.0 三组映射（报告须声明；LongMemEval-S 实测 500 题，无 abstention 类）：
    精确回溯 → single-session-user/assistant/preference（156 题）
    时序推理 → temporal-reasoning（133 题）
    干扰抑制 → knowledge-update（78 题；旧信息被更新后应召回新信息抑制旧信息）
    参考组   → multi-session（133 题；跨会话组合）
    负例组   → S 版无 abstention，负例由 LoCoMo adversarial + 自建噪声层承担
干扰组通过线 ≥80%（hit@1，v2.0 标尺）。

口径为「证据命中」机判：answer_session_ids 映射到 haystack turn 集合，
Top-K 含任一证据 turn 记命中；非 LLM-judge，与论文口径不可直接比较。

双口径（同 bench_locomo，eval_common 模块头有完整说明）：
    口径 A legacy     -- 默认。裸 turn 入库 + 四路基线：底座下界。
    口径 B calibrated -- --calibrated。五要素标定入库 + semantic 路：系统形态。

跑法：
    python -m md_cg.bench_longmem                   # 口径 A 全量 500 题
    python -m md_cg.bench_longmem --calibrated      # 口径 B 全量
    python -m md_cg.bench_longmem --n 50            # 每组抽样 50 题
"""
import argparse

from md_cg import eval_common as ec

GROUPS = {
    "precise": ("single-session-user", "single-session-assistant",
                "single-session-preference"),
    "temporal": ("temporal-reasoning",),
    "interference": ("knowledge-update",),
    "reference": ("multi-session",),
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

    print(f"== LongMemEval-S T-REC 复跑（k={args.k}，口径 {'B 标定' if cal else 'A legacy'}，"
          f"{'全量' if not args.n else f'每组≤{args.n}'}）==")
    ec.unlock_global_cap()   # 口径：解除 LIKE 预筛的插入序截断
    ec.use_jaccard()         # 口径：词法打分切 jaccard（长度自惩罚，长 turn 语料）
    cg = ec.build_eval_cg(None, ec.ROOT_LM_CAL if cal else ec.ROOT_LM,
                          ec.LM_H, ec.lm_turn_text, "lme",
                          calib_of=ec.calibrate_lm_turn if cal else None,
                          rebuild=args.rebuild)
    ec.install_read_cache(cg)

    paths = ec.PATHS_CAL if cal else ec.PATHS
    rows_by = {}
    for gname, qtypes in GROUPS.items():
        qs = ec.sample_questions(ec.load_questions("lm", qtypes=qtypes), args.n)
        print(f"  [{gname}] {len(qs)} 题 …")
        rows_by[gname] = ec.evaluate_group(cg, qs, k=args.k, paths=paths,
                                           fusion=args.fusion,
                                           path_weights=wmap)

    pos_rows = [r for g in POS_GROUPS for r in rows_by[g]]
    line = ec.calibrate_line(pos_rows)
    pos_false_refusal = ec.false_refusal_rate(pos_rows, line)

    groups = {g: ec.summarize(rows_by[g], k=args.k) for g in GROUPS}
    ec.print_table(f"LongMemEval-S T-REC 三组（口径 {'B 标定' if cal else 'A legacy'}）",
                   groups, k=args.k)
    print(f"\n拒答线（正例 hit@1 题 Top-1 分 p10）：{line:.6f}")
    print(f"正例误拒率（Top-1 分 < 线）：{ec.pct(pos_false_refusal)}")
    gate = {"interference_hit1": groups["interference"].get("hit@1", 0.0),
            "interference_pass": groups["interference"].get("hit@1", 0.0) >= 0.80,
            "calibrated_line": line}
    print(f"干扰组 gate（≥80%）：{'PASS' if gate['interference_pass'] else 'FAIL'}")

    ec.save_result("trec_longmem_cal.json" if cal else "trec_longmem.json", {
        "dataset": "LongMemEval-S (xiaowu0162/LongMemEval)",
        "caliber": "B-calibrated（五要素标定 + semantic 路）" if cal
                   else "A-legacy（裸 turn，四路基线）",
        "metric_caliber": "evidence-hit（answer_session_ids→turn 集合命中），"
                          "非 LLM-judge",
        "paths": list(paths),
        "k": args.k, "sampling": args.n or "full",
        "groups": groups,
        "false_refusal_pos": pos_false_refusal,
        "gate": gate,
        "group_mapping": {g: list(q) for g, q in GROUPS.items()},
    })


if __name__ == "__main__":
    main()
