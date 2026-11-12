# -*- coding: utf-8 -*-
"""test_issue130_rrf_rank_credibility · 「名次可信度」契约守卫（issue #130）

# 功能名：RRF 融合层的名次可信度契约守卫
# 生效条件：改动 `md_cg/mdcos.py` 的 `_path_entity` 打分或 `search_rrf` 融合循环之后必跑
# 子功能：①断言「分数无判别力的路不得冒充名次」（常量分路不参与打分，退回 recall_only）
#         ②断言「不在 _RANK_ABSTAIN_PATHS 内、分数有分级的路不被名次可信度门拦下」与「名单内的路（entity）出现同分块 ⇒ 必被拦」（本节契约于 #130 追评后修正：量化结论「不拦则真命中被压 24 位，26 → 50」） ③4 条定点变异：把判据打坏 ⇒ 读数必须变差（逐字给）
# 执行：python -m md_cg.test_issue130_rrf_rank_credibility
# 验证方式：末行「通过 N / 失败 M」；变异段逐条打印「变异前 → 变异后」读数
# 不适用条件：只测**检索侧融合契约**，不测 reader/判分层；不碰在役库（全程 tempfile 沙箱）

## 缺陷现场（issue #130）
`search_rrf` 的融合式 `score(d) = Σ w/(RRF_K + rank)` **只吃名次**，其隐含前提是
「每路的名次携带相关性信息」。而 `_path_entity` 旧实现命中即返回常量 `1.0`，
排序退化为 `(-score, -importance, id)` 兜底键＝枚举序（写入序）——名次无意义，
却仍以全额权重投票 ⇒ 标签命中获得与「正文相关」同等票权（实测真命中 1 → 41 位）。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import mdcos as _mdcos                      # noqa: E402
from md_cg.mdcos import MdCGOS, _tag_affinity, _RANK_ABSTAIN_PATHS          # noqa: E402

PASS = FAIL = 0
FAILS = []

PATHS_ON = ("lexical", "bucket", "entity", "graph", "chain", "temporal")
PATHS_OFF = ("lexical", "bucket", "graph", "chain", "temporal")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  · " + str(detail)) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s  · %s" % (name, detail))


def rank_of(res, nid):
    for i, row in enumerate(res, 1):
        n = row[0] if isinstance(row, (tuple, list)) else row
        if isinstance(n, dict) and n.get("id") == nid:
            return i
    return None


def build(cls, root, same_tag=True, n_noise=40):
    """受控语料：1 个真命中（正文含 query、tag 不含）+ n 个 tag 命中干扰。

    same_tag=True → 全部干扰 tag 相同 ⇒ 实体路**必然**同分（无判别力）
    same_tag=False → tag 长度分级 ⇒ 实体路有判别力（用于「不误伤」断言）
    """
    os.makedirs(root, exist_ok=True)
    eng = cls(root)
    eng.add("target", "# target\n北极星协议 的负责人是 张岚。", layer="knowledge")
    graded = ["北极星协议", "北极星协", "北极星", "负责人"]
    for i in range(n_noise):
        tag = "北极星协议" if same_tag else graded[i % len(graded)]
        eng.add("noise%02d" % i, "# noise%02d\n与查询无关的日常记录 %d。" % (i, i),
                layer="knowledge", tags=[tag], importance=0.5)
    eng.flush()
    return eng


def run_case(cls, sandbox, tag_name, same_tag=True, paths=PATHS_ON, with_off=True):
    eng = build(cls, os.path.join(sandbox, tag_name), same_tag=same_tag)
    q = "北极星协议 的负责人是谁"
    res_on, meta_on = eng.search_rrf(q, k=60, paths=paths)
    res_off = res_on
    if with_off:
        res_off, _ = eng.search_rrf(q, k=60, paths=PATHS_OFF)
    out = {"rank_on": rank_of(res_on, "target"), "rank_off": rank_of(res_off, "target"),
           "no_rank_signal": sorted(meta_on.get("no_rank_signal") or []),
           "top1_on": res_on[0][0].get("id") if res_on else None}
    eng.close()
    return out


def mutant(patches, name):
    """文本级定点变异：把 mdcos.py 源码替换后 exec 成独立模块（不改盘上文件）。"""
    src = open(_mdcos.__file__, encoding="utf-8").read()
    for a, b in patches:
        assert a in src, "变异锚点未命中：%r" % a[:60]
        src = src.replace(a, b)
    mod = types.ModuleType("md_cg._mdcos_" + name)
    mod.__package__, mod.__file__ = "md_cg", _mdcos.__file__
    exec(compile(src, "<mutant:%s>" % name, "exec"), mod.__dict__)   # noqa: S102
    return mod


# 定点变异锚点：**逐字**取自 md_cg/mdcos.py 的真实原文（含缩进与换行，禁行号）。
# GATE = 追评加严后的**多行**门控；GATE_LOOSE = 加严前的单行旧形态（M3 变异用）。
GATE = (
    "            if _gate_on and len(_scores) >= 2 and (\n"
    "                    _whole_tie\n"
    "                    or (_has_block and name in _RANK_ABSTAIN_PATHS)\n"
    "                    or _cred is not None):")
GATE_LOOSE = "            if _gate_on and len(_scores) >= 2 and len(set(_scores)) == 1:"
# 2026-11-12 合并：R-512 之后 `_gate_on` 在**循环内每轮重算**（`mdcos.py` 那一行），
# 循环前那次赋值不再是判定点 —— 变异必须打**真判定点**，否则变异不生效、判据假绿。
GATE_MULTI = "_gate_on = sum(1 for n in _active_paths if n not in ro) >= 2"
ENT_LINE = '            aff = _tag_affinity(tags, query)      # issue #130：布尔命中 → 匹配强度'
ENT_OLD = '            aff = 1.0 if any(t in query or query in t for t in tags if len(t) >= 2) else 0.0'


def main():
    sandbox = tempfile.mkdtemp(prefix="mdcos130_")
    os.makedirs(os.path.join(sandbox, "auxstore"), exist_ok=True)
    os.environ["MDCG_ROOT"] = os.path.join(sandbox, "root")
    os.environ["MDCG_AUX_ROOT"] = os.path.join(sandbox, "auxstore")
    os.environ.setdefault("MDCG_MASTER_KEY", "00" * 32)
    try:
        print("=== issue #130 名次可信度契约守卫 ===")

        print("\n[1] 单元：_tag_affinity 有判别力（不再是布尔/常量）")
        q = "北极星协议 的负责人是谁"
        check("完全相等 = 1.0", _tag_affinity([q], q) == 1.0, _tag_affinity([q], q))
        a_long = _tag_affinity(["北极星协议"], q)
        a_short = _tag_affinity(["北极星"], q)
        check("tag 越长（覆盖越多）分越高", a_long > a_short > 0, (round(a_long, 4), round(a_short, 4)))
        check("不命中 = 0.0（口径与旧实现一致：词面之外不算）",
              _tag_affinity(["无关标签"], q) == 0.0 and _tag_affinity(["x"], q) == 0.0)

        print("\n[2] 集成：常量分路不得冒充名次（40 个同 tag 干扰）")
        base = run_case(MdCGOS, sandbox, "base")
        print("    读数：rank_on=%s rank_off=%s top1_on=%s no_rank_signal=%s"
              % (base["rank_on"], base["rank_off"], base["top1_on"], base["no_rank_signal"]))
        check("开 entity 的真命中名次 == 关 entity（旧实现此处 1 vs 41）",
              base["rank_on"] == base["rank_off"] == 1, base)
        check("meta.no_rank_signal 如实留痕 entity（可审计）",
              "entity" in base["no_rank_signal"], base["no_rank_signal"])
        check("top1 仍是真命中（不再被标签干扰顶掉）", base["top1_on"] == "target", base["top1_on"])

        print("\n[3] 契约修正（issue #130 追评）：拦名单内路的同分块，不拦真实打分路")
        print("    本节契约于 #130 追评后修正：量化结论「不拦则真命中被压 24 位，26 → 50」")
        graded = run_case(MdCGOS, sandbox, "graded", same_tag=False)
        print("    读数：rank_on=%s rank_off=%s no_rank_signal=%s"
              % (graded["rank_on"], graded["rank_off"], graded["no_rank_signal"]))
        check("（正向）entity 出现同分块 ⇒ 被名次可信度门拦下（no_rank_signal 含 entity）",
              "entity" in graded["no_rank_signal"], graded["no_rank_signal"])
        check("（名单）_RANK_ABSTAIN_PATHS 逐字可审计（== ('entity',)）",
              _RANK_ABSTAIN_PATHS == ("entity",), list(_RANK_ABSTAIN_PATHS))
        graded2 = run_case(MdCGOS, sandbox, "graded2", same_tag=False,
                           paths=("lexical", "entity"))
        print("    读数：paths=('lexical','entity') → rank_on=%s no_rank_signal=%s"
              % (graded2["rank_on"], graded2["no_rank_signal"]))
        check("（反向）不在 _RANK_ABSTAIN_PATHS 内、分数有分级的路（lexical）不被门拦下",
              "lexical" not in graded2["no_rank_signal"],
              "abstain=%s signal=%s" % (list(_RANK_ABSTAIN_PATHS), graded2["no_rank_signal"]))

        print("\n[3b] 生效条件：**单路**竞争不启用契约（保既有 importance 兜底契约）")
        single = run_case(MdCGOS, sandbox, "single", paths=("entity",), with_off=False)
        print("    读数：paths=('entity',) → no_rank_signal=%s top1=%s"
              % (single["no_rank_signal"], single["top1_on"]))
        check("单路全同分**不**被契约改写（no_rank_signal 为空）",
              single["no_rank_signal"] == [], single["no_rank_signal"])
        check("单路仍按路内序（importance/id 兜底）出结果（top1 为标签命中干扰）",
              str(single["top1_on"] or "").startswith("noise"), single["top1_on"])

        print("\n[4] 定点变异（文本级：只改内存副本，不改盘上文件）")
        m1 = mutant([(GATE, "            if False:")], "m1_nogate")
        r1 = run_case(m1.MdCGOS, sandbox, "m1")
        print("    M1 关掉名次可信度门 → rank_on=%s（修复前形态）no_rank_signal=%s"
              % (r1["rank_on"], r1["no_rank_signal"]))
        check("M1 判据被打坏 ⇒ 真命中名次从 1 掉到 41（守卫必然察觉）",
              r1["rank_on"] == 41 and base["rank_on"] == 1,
              "fixed=%s mutant=%s" % (base["rank_on"], r1["rank_on"]))

        m2 = mutant([(ENT_LINE, ENT_OLD)], "m2_const")
        r2 = run_case(m2.MdCGOS, sandbox, "m2")
        print("    M2 把 _path_entity 打回常量 1.0 → rank_on=%s no_rank_signal=%s"
              % (r2["rank_on"], r2["no_rank_signal"]))
        check("M2 即使实体路退回常量分，门仍独立兜住（名次不回退、且留痕）",
              r2["rank_on"] == 1 and "entity" in r2["no_rank_signal"],
              "rank=%s signal=%s" % (r2["rank_on"], r2["no_rank_signal"]))

        m3 = mutant([(GATE, GATE_LOOSE)], "m3_loose")
        r3 = run_case(m3.MdCGOS, sandbox, "m3", same_tag=False,
                      paths=("lexical", "entity"))
        print("    M3 回退加严（只拦整路同分）→ no_rank_signal=%s"
              % (r3["no_rank_signal"],))
        check("M3 加严判据被打坏 ⇒ 有分级的 entity 重新参与打分（no_rank_signal 不再含 entity）",
              "entity" not in r3["no_rank_signal"]
              and "entity" in graded2["no_rank_signal"],
              "fixed=%s mutant=%s" % (graded2["no_rank_signal"], r3["no_rank_signal"]))

        m4 = mutant([(GATE_MULTI, "_gate_on = True")], "m4_always")
        r4 = run_case(m4.MdCGOS, sandbox, "m4", paths=("entity",), with_off=False)
        print("    M4 取消「多路」限定（_gate_on 恒 True）→ 单路 no_rank_signal=%s"
              % r4["no_rank_signal"])
        check("M4 生效条件被打坏 ⇒ 单路也被契约改写（本应为空，变异后含 entity）",
              r4["no_rank_signal"] == ["entity"] and single["no_rank_signal"] == [],
              "fixed=%s mutant=%s" % (single["no_rank_signal"], r4["no_rank_signal"]))

        print("\n" + "=" * 68)
        print("通过 %d / 失败 %d" % (PASS, len(FAILS)))
        if FAILS:
            print("失败项：" + "、".join(FAILS))
        print("=" * 68)
        return 1 if FAILS else 0
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
