# -*- coding: utf-8 -*-
"""渐进式语义检索控制器测试（md_cg/progressive.py）。

断言面（性质级，不锚具体数字）：
  ① core_subset   保序截断 / 确定性 / 空集 / ratio 边界
  ② discriminative 零区分→None（诚实停止）/ 最大区分入选 / 同 gap 保序 /
                   空候选与单候选→None
  ③ 收敛演示       宽检索 gold 非前排 → 区分性条件把它推到 top1
  ④ 无区分性       候选同质 → 一步停、不空转
  ⑤ 预算约束       多步收敛不超过 max_stages，每阶段都被测量
  ⑥ 空原子集       stages 空、不炸

运行：python -m md_cg.test_progressive
"""
from __future__ import annotations

from .progressive import (MIN_DISCRIM, core_subset, discriminative,
                          progressive_search)

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


def _jaccard_rank(qset, docs):
    """bench 同款 Jaccard 评分器：[(cid, score)] 降序（tie 按 id 序）。"""
    out = []
    for cid, ds in docs:
        inter = len(qset & ds)
        out.append((cid, inter / len(qset | ds) if inter else 0.0))
    out.sort(key=lambda t: (-t[1], t[0]))
    return out


def main():
    # ---------- ① core_subset ----------
    cs = core_subset(["买", "外套", "红色", "东京", "昨天"], 0.5)
    ok(cs == ["买", "外套"],
       f"①保序截断（5×0.5→2）: {cs}")
    ok(core_subset(["a", "b", "c"], 0.5) == ["a"],
       "①int 截断确定性（3×0.5→1）")
    ok(core_subset([], 0.5) == [] and core_subset(["", None, "x"], 0.5) == ["x"],
       "①空集/空 token 过滤")
    ok(core_subset(["a", "b"], 1.0) == ["a", "b"],
       "①ratio=1.0 退化为全原子")

    # ---------- ② discriminative ----------
    ok(discriminative(["a"], [{"a"}]) is None,
       "②单候选→None（无『候选间』区分可言）")
    ok(discriminative(["a"], []) is None,
       "②空候选→None")
    # a 全命中（cov=1→gap=0 零区分）不选；b 一半命中（gap=1）入选
    ok(discriminative(["a", "b"], [{"a", "x"}, {"a", "b"}]) == "b",
       "②零区分排除+最大区分入选")
    # 全不命中（cov=0→gap=0）同样排除
    ok(discriminative(["z"], [{"a", "x"}, {"a", "b"}]) is None,
       "②全不命中=零区分，同样排除")
    # 同 gap 保序：两个原子都恰一半命中 → 取序列靠前者
    ok(discriminative(["p", "q"], [{"p"}, {"q"}]) == "p",
       "②同 gap 按原序 tie-break（确定性）")
    ok(discriminative([], [{"a"}, {"b"}]) is None,
       "②空条件池→None")

    # ---------- ③ 收敛演示：宽检索 gold 非前排 → 渐进推到 top1 ----------
    docs = [
        ("gold", frozenset("买 外套 红色 东京".split())),
        ("dA",   frozenset("买 外套".split())),
        ("dB",   frozenset("买 外套 东京".split())),
    ]
    cand_atoms = dict(docs)
    atoms = "买 外套 红色 东京".split()

    def rank_fn(used):
        return _jaccard_rank(frozenset(used), docs)

    r0 = rank_fn(core_subset(atoms, 0.5))          # core=[买,外套]
    gold_rank0 = [cid for cid, _ in r0].index("gold") + 1
    tr = progressive_search(rank_fn, atoms, cand_atoms,
                            ratio=0.5, k=10, max_stages=4)
    final_top = tr["stages"][-1]["top"]
    gold_rank1 = final_top.index("gold") + 1
    ok(gold_rank0 > 1,
       f"③前置：宽检索（core 50%）gold 非前排（rank={gold_rank0}）")
    ok(gold_rank1 == 1,
       f"③区分性条件把 gold 推到 top1（added={tr['added']}）")
    ok(tr["added"] and len(tr["added"]) <= 3,
       "③refinement 步数有限且非零")

    # ---------- ④ 候选同质：无区分性 → 一步停、不空转 ----------
    docs_same = [("m1", frozenset("a b".split())),
                 ("m2", frozenset("a b c".split())),
                 ("m3", frozenset("a b d".split()))]
    tr2 = progressive_search(lambda u: _jaccard_rank(frozenset(u), docs_same),
                             "a b c d".split(), dict(docs_same),
                             ratio=0.5, k=10, max_stages=4)
    # c 只有 m2 有（cov=1/3→gap=1/3>0.1 可区分）——应加条件而非停；
    # 加到某步后剩余原子均零/低区分 → 收敛。只断言：步数 ≤ 预算且每阶段被测量。
    ok(len(tr2["stages"]) <= 4 and len(tr2["added"]) == len(tr2["stages"]) - 1,
       "④阶段数=加条件数+1（每阶段都被测量，不空转）")
    docs_twin = [("t1", frozenset("a b".split())),
                 ("t2", frozenset("a b".split()))]
    tr3 = progressive_search(lambda u: _jaccard_rank(frozenset(u), docs_twin),
                             "a b c".split(), dict(docs_twin),
                             ratio=0.5, k=10, max_stages=3)
    ok(tr3["converged"] and not tr3["added"] and len(tr3["stages"]) == 1,
       "④候选同质（剩余原子全零区分）→ 一步收敛，不硬加条件")

    # ---------- ⑤ 预算约束 ----------
    atoms5 = list("abcdef")
    docs5 = [(f"n{i}", frozenset(atoms5[:i + 1])) for i in range(6)]  # 递增前缀
    tr5 = progressive_search(lambda u: _jaccard_rank(frozenset(u), docs5),
                             atoms5, dict(docs5), ratio=0.5, k=10, max_stages=3)
    ok(len(tr5["stages"]) <= 3 and not tr5["converged"],
       "⑤预算耗尽 converged=False（预算内每步已测量）")
    tr5b = progressive_search(lambda u: _jaccard_rank(frozenset(u), docs5),
                              atoms5, dict(docs5), ratio=0.5, k=10,
                              max_stages=10)
    ok(len(tr5b["stages"]) <= 10,
       "⑤放宽预算不炸（步数受收敛/原子数天然上限约束）")

    # ---------- ⑥ 空原子集 ----------
    tr6 = progressive_search(lambda u: [], [], {}, ratio=0.5, k=10)
    ok(tr6 == {"stages": [], "added": [], "converged": False},
       "⑥空原子集→空轨迹不炸")

    # ---------- ⑦ MIN_DISCRIM 语义守卫 ----------
    ok(0 < MIN_DISCRIM < 1, "⑦阈值为 (0,1) 内小正数（排除零区分，不卡高区分）")

    print(f"\nprogressive: {PASS} passed, {FAIL} failed")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
