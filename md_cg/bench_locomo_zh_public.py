# -*- coding: utf-8 -*-
"""locomo-zh-500 公开复现入口（外部第三方可独立运行，零上游依赖）。

数据集：`data/benchmarks/locomo-zh-500/`（随仓库公开，CC BY-NC 4.0）
用途：外部在同一份中文题面上，用**灵枢自身的默认检索口径**复现本仓库公布的
      参考量级（词法单路 hit@1 ≈ 93.6% / 词法+同义 ≈ 97.6%）。

## 与既有脚本的分工（不要混用）

* `md_cg/bench_axis_domain.py`：**消融实验**入口（4 臂 × 6 路组合），依赖
  `data/external/locomo_zh/`——该目录被 `.gitignore` 覆盖、**不随仓库公开**，
  因此外部拿到仓库后跑不了。
* 本脚本：**公开数据集的最小消费者**。只读 `data/benchmarks/locomo-zh-500/`，
  不读任何未入库路径、不依赖 Rust 评测器、不依赖上游 LoCoMo 原始下载。

两者评测口径一致（同 `eval_common` 的 GLOBAL_CAP 解除 + jaccard 词法），
差异只在「跑哪些路」：本脚本只跑参考量级对应的两路。

## 跑法

    python -m md_cg.bench_locomo_zh_public

## 诚实条款（报告须原样保留）

* 被测池 567 条**全部**是 500 题的 gold 证据 → 池内零干扰，指标为**上界**，
  不可外推为端到端记忆能力（详见数据集 README「诚实边界」）。
* `question` 是**中文关键词串**而非自然语言问句 → 本集评的是检索命中，
  不是 QA、不是意图理解。
* 本脚本产出的是**灵枢系统自身口径**的数字；第三方用自己的系统 + 自己的
  口径跑出的数字才是可比对的结论。
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (HERE, os.path.join(HERE, "md_cg")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from md_cg import eval_common as ec       # noqa: E402

DATA = os.path.join(HERE, "data", "benchmarks", "locomo-zh-500")
CORPUS567 = os.path.join(DATA, "corpus567.jsonl")
QUESTIONS500 = os.path.join(DATA, "questions500.jsonl")
ROOT = os.path.join(HERE, "_md_cg_eval_public")   # .gitignore 的 /_md_cg_eval_*/ 已覆盖

# 参考量级对应的两个检索配置（顺序即报告顺序）
CONFIGS = (
    ("lexical", ("lexical",)),
    ("lexical,fuzzy", ("lexical", "fuzzy")),
)

# VERSION.json 公布的参考值（仅作对照，不作断言——第三方环境差异允许浮动）
REFERENCE = {"lexical": 0.936, "lexical,fuzzy": 0.976}


def body_of(c):
    """正文：与 bench_axis_domain.body_of / bench_zh_mad 的 a0 臂**逐字一致**。

    正文 = 中文层四槽（身份/时间/摘要/词/条件）+ 原始陈述。保持逐字一致是为了
    让本脚本复现的参考数字与消融表 d0_base 臂**同源可比**（第2条：在既有成果上开发，
    不另起一套口径）。
    """
    f = c["zh_fields"]
    return "\n".join([
        f"身份：{f['identity']}",
        f"时间：{f['time']}",
        f"摘要：{f['summary']}",
        f"词：{','.join(f['terms'])}",
        "条件：" + "|".join(f"{k}:{v}" for k, v in f["condition"].items()),
        "",
        c["text"],
    ])


def build_pool(corpus, rebuild=False):
    """把 567 条灌成灵枢记忆库（layer=knowledge，无 tags）。

    layer=knowledge：与消融 a0/d0_base 臂同层，使条件约束路（bucket）有桶可路由；
    无 tags：不给 entity 路喂裸词（裸词 tags 在实测中是净污染，见 bench_axis_domain
    模块头的四轴取证）——本脚本只测**词法/同义**两路，故不引入其它路的干扰。
    """
    import shutil
    from md_cg.mdcos import MdCGOS

    if rebuild and os.path.isdir(ROOT):
        shutil.rmtree(ROOT, ignore_errors=True)
    cg = MdCGOS(ROOT, autoflush=500)
    if len(cg.index["nodes"]) >= len(corpus):
        print(f"  建库复用 {ROOT}：{len(cg.index['nodes'])} 节点")
        return cg
    t0 = time.time()
    for c in corpus:
        cg.add(c["id"], body_of(c), layer="knowledge",
               eval_src="public:locomo-zh-500", verification_basis="data")
    cg.flush()
    print(f"  建库完成：{len(cg.index['nodes'])} 节点，{time.time() - t0:.0f}s")
    return cg


def main():
    if not os.path.exists(CORPUS567) or not os.path.exists(QUESTIONS500):
        raise SystemExit(
            f"[失败] 未找到公开数据集：{DATA}\n"
            "       本脚本只读 data/benchmarks/locomo-zh-500/，请确认仓库完整。")

    corpus = list(ec.iter_jsonl(CORPUS567))
    questions = list(ec.iter_jsonl(QUESTIONS500))
    print(f"公开数据集 locomo-zh-500：池 {len(corpus)} 条，题 {len(questions)} 道")

    # 评测口径（与既有公开基准一致，否则与参考量级不可比）
    ec.unlock_global_cap()
    ec.use_jaccard()

    cg = build_pool(corpus)
    ec.install_read_cache(cg)

    table = {}
    for label, paths in CONFIGS:
        t0 = time.time()
        rows = ec.evaluate_group(cg, questions, k=5, paths=paths, verbose=False)
        s = ec.summarize(rows, k=5)
        table[label] = s
        ref = REFERENCE.get(label)
        note = f"（VERSION.json 参考 {ref:.1%}）" if ref is not None else ""
        print(f"  {label:<16} hit@1={s['hit@1']:>6.1%} hit@5={s['hit@5']:>6.1%} "
              f"MRR={s['mrr']:.4f}  用时 {time.time() - t0:.0f}s {note}")

    ec.print_table(f"locomo-zh-500 公开复现（池 {len(corpus)} / 题 {len(questions)}，"
                   f"jaccard + GLOBAL_CAP 解除）", table, k=5)
    ec.save_result("public_locomo_zh_replay.json",
                   {"n_pool": len(corpus), "n_q": len(questions),
                    "configs": {k: v for k, v in table.items()}})

    print("\n== 诚实边界（务必与数字一并引用）==")
    print("  1) 池 567 条全为 gold → 零干扰，指标是**上界**，非端到端能力。")
    print("  2) question 是中文关键词串，非自然语言问句 → 评的是检索命中，不是 QA。")
    print("  3) 上表是**灵枢自身口径**；请以自己系统 + 自己口径的数字为准。")
    print("  4) 数据集许可 CC BY-NC 4.0（署名 + 非商业），见 data/benchmarks/"
          "locomo-zh-500/README.md。")


if __name__ == "__main__":
    main()
