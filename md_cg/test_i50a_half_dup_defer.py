# -*- coding: utf-8 -*-
"""md_cg · issue50-a 守卫：半重复 → DEFER（与重要度解耦）

缺陷（编排侧改前实测，非推断）
------------------------------
主动遗忘闸门 `forgetting.assess` 的「半重复且不重要 → DEFER」分支（改动前
:318-321）条件为 `red["max"] >= DUP_DROP and imp["score"] < IMPORTANCE_MIN`
——**结构性不可达**：

  · 用户角色属外部惊奇来源（`SOURCE_WEIGHT["external_surprising"]=1.00`），
    启发式重要度 = 0.5·novelty + 0.3·1.00 + 0.2·lf ⇒ novelty→1 时基线恰为
    **0.30 = IMPORTANCE_MIN**，而比较用的是 `>=`（差一步就够不着）；
  · 插件缺省还显式传 `hint=0.6`（≥0.30）。

实测：重复度 0.7324 / 0.7606 的半重复内容一律走分支⑤判 ACCEPT；在役库 215 条
留痕 ACCEPT 201 / MERGE 14，**DROP 与 DEFER 皆 0**——本应是「变更确认」输入端的
那条回路从不产生输入。

本批修复（契约冻结，只此一条）
------------------------------
分支④改为**与重要度无关**：`red["max"] >= DUP_DROP`（且未触发保护）→ DEFER。
分支序不变：①保护 ACCEPT → ②内部确定性 DROP → ③冗余≥0.85 MERGE → ④半重复
DEFER → ⑤重要度 ACCEPT → ⑥新信息 ACCEPT → ⑦其余 DEFER。常量、其余分支的
判据与文案、writelimit、`mdcos.remember_gated` 的落库动作均不动。

断言分组（每组都在**隔离临时根**的合成库上真跑，绝不触在役数据根）
  F 夹具自检：构造出的重复度确实落在各区（防「测试面打滑」——测的不是想测的）
  A 修复面：dup∈[0.60,0.85) 且 role=user 非保护 → DEFER（hint=0.60 与启发式
    hint=None 两路都必须 DEFER——后者正是改前误判 ACCEPT 的那一路）；
    hint=0.9 的半重复 → ACCEPT（保护优先不受影响）；reason 文案如实描述新判据
  B 窗口边界（④ 不许外溢）：dup≥0.85 仍 MERGE（③ 先）；dup<0.60 仍 ACCEPT
  C 先后次序：role=tool-output 且 dup∈[0.60,0.85) → DROP（② 先于 ④）
  E 不动面：①③⑤⑥ 的判据/文案与五个判据常量原样

定点变异自证（--mutate）
------------------------
每一处判据都配一个定点变异把它打红，且**恰好**命中预期红项数
（`_SRC_MUTATIONS` / `_CONST_MUTATIONS` 的 expected 列；实测计数不符即判 FAIL
——照 test_neg_condition_hits.py 的 --branch-baseline 同口径）。锚点漂移（实现
改了却没同步本表）→ 报 ANCHOR-MISS 并 **exit 2**（fail-closed）；默认模式同样
先做锚点自检。**不以 git HEAD 为基线源**——基线绑提交即失效（本仓已有两次教训），
变异一律作用在**当前盘的实现**上。

运行：python -X utf8 -m md_cg.test_i50a_half_dup_defer
      python -X utf8 -m md_cg.test_i50a_half_dup_defer --mutate
"""
from __future__ import annotations

import contextlib
import inspect
import io
import os
import shutil
import sys
import tempfile

from . import forgetting
from .mdcos import MdCGOS

_PASS = []
_FAIL = []


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


def _line(r):
    """一行读数：verdict · reason · dup · importance（报告面逐行可核对）。"""
    return ("%s · %s · dup=%.4f · imp=%s/%s"
            % (r["verdict"], r["reason"], r["redundancy"]["max"],
               r["importance"]["score"], r["importance"]["from"]))


# ---------------------------------------------------------------- 夹具构造
# 600 个互异汉字作基线正文、另 600 个互异汉字作全新填充——两者的 bigram 集合
# 几乎不交，于是「前 k 字的覆盖比例」可以线性地调出目标重复度（实测 k=360 →
# dup 0.6074、k=436 → 0.7302、k=455 → 0.7609、k=503 → 0.8384、k=579 → 0.9612）。
BASE = "".join(chr(0x4e00 + i) for i in range(600))
FILL = "".join(chr(0x8000 + i) for i in range(600))
TITLE_BASE, TITLE_NEW = "基线节点标题", "新写入标题"

K_LO = 355          # dup ≈ 0.5994（刚好落在 DUP_DROP 之下）
K_EDGE = 360        # dup ≈ 0.6074（刚好越过 DUP_DROP）
K_HALF1 = 436       # dup ≈ 0.7302
K_HALF2 = 455       # dup ≈ 0.7609
K_TOP = 503         # dup ≈ 0.8384（贴近 DUP_MERGE 但未到）
K_NEAR_MID = 541    # dup ≈ 0.8998
K_NEAR = 579        # dup ≈ 0.9612


# 生效条件：title 与 body 给定时按本仓 CCG 六要素模板拼出节点正文（模板行两侧
# 一致，故不成为重复度的差量来源）；无输入校验，参数缺失即抛 TypeError。
def _doc(title, body):
    return ("# 功能名：%s\n# 生效条件：任意情境\n# 子功能：验收\n"
            "# 执行：直接调用\n# 验证方式：test\n# 不适用条件：无\n%s\n"
            % (title, body))


# 生效条件：k 为整数下标；返回「前 k 字取自 BASE、其余取自 FILL」的新正文。
def _mixed(k):
    return BASE[:k] + FILL[:len(BASE) - k]


# 生效条件：在**隔离临时根**上真建一个基线节点（层 contextual），再对 _mixed(k)
# 的正文调 forgetting.assess（走 forgetting.assess 属性查表，**不**本地绑定，
# 否则变异自证打不进去）；same_title 为真时新正文复用基线标题（精确重复用）。
# 返回 assess 的完整判据字典；临时根在 finally 里删除，绝不触在役数据根。
def _case(k, role="user", hint=None, same_title=False):
    root = tempfile.mkdtemp(prefix="i50a_")
    try:
        cg = MdCGOS(root)
        cg.add("n1", _doc(TITLE_BASE, BASE), layer="contextual", importance=0.5)
        title = TITLE_BASE if same_title else TITLE_NEW
        return forgetting.assess(cg, _doc(title, _mixed(k)), layer="contextual",
                                 role=role, verification_basis=None,
                                 importance_hint=hint, node_id=None)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- F 夹具自检
def g_f():
    print("== F 夹具自检（构造出的重复度确实落在预期区）==")
    d = {}
    for name, k, same in (("fresh", 0, False), ("lo", K_LO, False),
                          ("edge", K_EDGE, False), ("top", K_TOP, False),
                          ("near", K_NEAR, False), ("exact", 600, True)):
        d[name] = _case(k, same_title=same)["redundancy"]["max"]
    ok(d["fresh"] < 0.60, "F1 全新内容 dup<0.60（%.4f）" % d["fresh"])
    ok(d["lo"] < 0.60, "F2 边界下侧 dup<0.60（%.4f，恰好卡在 DUP_DROP 之下）"
       % d["lo"])
    ok(0.60 <= d["edge"] < 0.85, "F3 边界上侧 dup∈[0.60,0.85)（%.4f）"
       % d["edge"])
    ok(0.60 <= d["top"] < 0.85, "F4 贴近 DUP_MERGE 仍 ∈[0.60,0.85)（%.4f）"
       % d["top"])
    ok(d["near"] >= 0.85, "F5 近重复 dup≥0.85（%.4f）" % d["near"])
    ok(d["exact"] == 1.0, "F6 精确重复 dup==1.0（%.4f）" % d["exact"])


# ---------------------------------------------------------------- A 修复面
def g_a():
    print("== A 修复面：半重复且未触发保护 → DEFER（与重要度无关）==")
    r = _case(K_EDGE, hint=0.60)
    ok(r["verdict"] == "DEFER",
       "A1 边界上侧 dup=%.4f + hint=0.60 → DEFER" % r["redundancy"]["max"],
       _line(r))
    r_h1 = _case(K_HALF1, hint=0.60)
    ok(r_h1["verdict"] == "DEFER",
       "A2 dup=%.4f + hint=0.60 → DEFER（改前走⑤误判 ACCEPT）"
       % r_h1["redundancy"]["max"], _line(r_h1))
    r_h1n = _case(K_HALF1, hint=None)
    ok(r_h1n["verdict"] == "DEFER",
       "A3 dup=%.4f + hint=None（启发式 %.4f≥%.2f）→ 仍 DEFER"
       % (r_h1n["redundancy"]["max"], r_h1n["importance"]["score"],
          forgetting.IMPORTANCE_MIN), _line(r_h1n))
    r_h2 = _case(K_HALF2, hint=0.60)
    ok(r_h2["verdict"] == "DEFER",
       "A4 dup=%.4f + hint=0.60 → DEFER" % r_h2["redundancy"]["max"], _line(r_h2))
    r_top = _case(K_TOP, hint=0.60)
    ok(r_top["verdict"] == "DEFER",
       "A5 dup=%.4f（贴近 DUP_MERGE）+ hint=0.60 → DEFER"
       % r_top["redundancy"]["max"], _line(r_top))
    r_p = _case(K_HALF1, hint=0.9)
    ok(r_p["verdict"] == "ACCEPT",
       "A6 半重复 + hint=0.9 → ACCEPT（① 保护优先不受本批影响）", _line(r_p))
    ok(r_p.get("dedup_skipped") is not None,
       "A7 保护优先分支的去重读数仍在（dedup_skipped 非空）",
       r_p.get("dedup_skipped"))
    why = r_h1["reason"]
    ok("半重复" in why and "未触发不可遗忘保护" in why and "重要度" not in why,
       "A8 分支④ 文案如实描述新判据（半重复/未触发保护，不再称重要度不足）",
       why)


# ---------------------------------------------------------------- B 窗口边界
def g_b():
    print("== B 窗口边界：④ 不许外溢 ==")
    r = _case(K_NEAR, hint=0.60)
    ok(r["verdict"] == "MERGE" and "强化既有" in r["reason"],
       "B1 dup=%.4f≥0.85 → MERGE（③ 仍先于 ④，分支③ 文案原样）"
       % r["redundancy"]["max"], _line(r))
    r = _case(K_NEAR_MID, hint=None)
    ok(r["verdict"] == "MERGE",
       "B2 dup=%.4f≥0.85 → MERGE" % r["redundancy"]["max"], _line(r))
    r = _case(600, same_title=True)
    ok(r["verdict"] == "MERGE",
       "B3 精确重复（dup=1.0）→ MERGE", _line(r))
    r = _case(K_LO, hint=0.60)
    ok(r["verdict"] == "ACCEPT",
       "B4 dup=%.4f<0.60 → ACCEPT（④ 不外溢到 DUP_DROP 之下）"
       % r["redundancy"]["max"], _line(r))
    r = _case(0, hint=None)
    ok(r["verdict"] == "ACCEPT", "B5 全新内容（dup=%.4f）→ ACCEPT"
       % r["redundancy"]["max"], _line(r))


# ---------------------------------------------------------------- C 先后次序
def g_c():
    print("== C 先后次序：分支② 仍先于 ④ ==")
    r = _case(K_EDGE, role="tool-output")
    ok(r["verdict"] == "DROP",
       "C1 tool-output + dup=%.4f∈[0.60,0.85) → DROP（② 先于 ④）"
       % r["redundancy"]["max"], _line(r))
    r = _case(K_TOP, role="tool-output")
    ok(r["verdict"] == "DROP" and "低熵噪音" in r["reason"],
       "C2 贴近 DUP_MERGE 仍 DROP，分支② 文案原样", _line(r))
    r = _case(0, role="tool-output")
    ok(r["verdict"] == "ACCEPT",
       "C3 反向腿：tool-output 全新内容仍 ACCEPT（C 组不是恒判 DROP）", _line(r))


# ---------------------------------------------------------------- E 不动面
def g_e():
    print("== E 不动面：①③⑤⑥ 的判据/文案与五个常量原样 ==")
    r = _case(K_NEAR, hint=0.9)
    ok(r["verdict"] == "ACCEPT" and "触发不可遗忘保护" in r["reason"],
       "E1 ① 保护优先仍最先（dup=0.96 + hint=0.9 → ACCEPT，未被 ③ 抢走）",
       _line(r))
    r = _case(0, hint=0.35)
    ok(r["verdict"] == "ACCEPT" and "重要度" in r["reason"],
       "E2 ⑤ 重要度≥IMPORTANCE_MIN → ACCEPT，文案原样", _line(r))
    r = _case(0, role="command", hint=0.1)
    ok(r["verdict"] == "ACCEPT" and "新信息" in r["reason"],
       "E3 ⑥ 新信息≥NOVELTY_MIN → ACCEPT，文案原样", _line(r))
    ok(forgetting.DUP_MERGE == 0.85 and forgetting.DUP_DROP == 0.60
       and forgetting.NOVELTY_MIN == 0.15 and forgetting.IMPORTANCE_MIN == 0.30
       and forgetting.PROTECT_IMPORTANCE == 0.70,
       "E4 五个判据常量原样（本批不改任何常量值）",
       (forgetting.DUP_MERGE, forgetting.DUP_DROP, forgetting.NOVELTY_MIN,
        forgetting.IMPORTANCE_MIN, forgetting.PROTECT_IMPORTANCE))


_GROUPS = (g_f, g_a, g_b, g_c, g_e)


def _run_groups():
    """跑全部断言组（静默），返回失败数——供变异自证复用。"""
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        g()
    return len(_FAIL)


# ---------------------------------------------------------------- 定点变异自证
# 表内每项 = (说明, 锚点原文, 替换文, 预期红项数)。锚点必须**逐字**出现在
# 当前实现的 assess 源码里；漂移即 ANCHOR-MISS（fail-closed，exit 2）。
_SRC_MUTATIONS = (
    # 契约指定的那处：把分支④ 的条件改回「且重要度不足」——半重复重新被重要度
    # 拦住 → A1..A5 全部落回分支⑤ ACCEPT，A8 文案也随之变成「重要度 …」
    ("④ 分支加回重要度合取（改回缺陷形态）",
     'elif red["max"] >= DUP_DROP:',
     'elif red["max"] >= DUP_DROP and imp["score"] < IMPORTANCE_MIN:',
     6),
    # 整条删掉分支④——半重复无出口，落回分支⑤
    ("④ 分支整条删除", 'elif red["max"] >= DUP_DROP:', 'elif False:', 6),
    # 整条删掉分支③——dup≥0.85 不再 MERGE 而是落到 ④：B 组「≥0.85→MERGE」
    # 那端的判别力由本变异钉死
    ("③ 分支整条删除（≥0.85 不再 MERGE）",
     'elif red["max"] >= DUP_MERGE:', 'elif False:', 3),
    # ① 保护分支失能（阈值抬到不可能达到）——保护面与半重复面同时暴露
    ("① 保护分支失能（PROTECT_IMPORTANCE 抬到 1.1）",
     'imp["score"] >= PROTECT_IMPORTANCE', 'imp["score"] >= 1.1', 3),
)
# 常量变异：直接改模块属性（assess 在调用时按模块 globals 取名，故立刻生效）
# 表内 = (说明, 常量名, 变异值, 预期红项数)。**每条常量变异的红项数都含 E4
# +1**——E4 断言的正是「五个常量原样」，常量一动它就必红，这是设计使然。
_CONST_MUTATIONS = (
    # 契约指定的那处：DUP_DROP 抬到 0.9。**实测与契约的预期不同**（见回报）：
    # 分支③(0.85) 在 ④ 之前，抬高 DUP_DROP 只会让 ④ 的窗口变成空集 ⇒ 半重复
    # 落回 ⑤（A 组红），而 B 组的「≥0.85→MERGE」与「<0.60→ACCEPT」两端都不受影响。
    ("DUP_DROP 抬到 0.9（契约指定；④ 窗口变空）", "DUP_DROP", 0.9, 9),
    # 反方向：DUP_DROP 降到 0.30 —— ④ 的入口边界下移，dup<0.60 的「不许外溢」
    # 断言（B4）必红。这才是 B 组在该常量上的判别力所在。
    ("DUP_DROP 降到 0.30（④ 的入口边界下移）", "DUP_DROP", 0.30, 2),
    ("DUP_MERGE 降到 0.60（③ 抢在 ④ 之前）", "DUP_MERGE", 0.60, 7),
    ("IMPORTANCE_MIN 抬到 1.1（⑤ 失能）", "IMPORTANCE_MIN", 1.1, 2),
    ("NOVELTY_MIN 抬到 1.1（⑥ 失能）", "NOVELTY_MIN", 1.1, 2),
)

# 静态锚点（默认模式也自检，fail-closed）：
#   · 缺陷形态的合取**不得**出现在 assess 源码里（回归即 ANCHOR-MISS）
#   · 新文案的两个词必须在位
_ANCHORS_BANNED = ("and imp[\"score\"] < IMPORTANCE_MIN",)
_ANCHORS_REQUIRED = ("半重复", "未触发不可遗忘保护", "待定复核")


def _assess_src():
    return inspect.getsource(forgetting.assess)


def _code_face():
    """assess 的**可执行面**（剥掉函数 docstring 与整行注释）。

    与 test_neg_condition_hits.py 的 G6a 同口径：说明性文字里**引述**被删掉的
    旧实现是允许的（正是要记下它为何被换掉），判别力只压在可执行行上。
    """
    import ast
    src = _assess_src()
    lines = src.splitlines()
    fn = ast.parse(src).body[0]
    skip = set()
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)
            and isinstance(fn.body[0].value.value, str)):
        doc = fn.body[0]
        for i in range(doc.lineno, (doc.end_lineno or doc.lineno) + 1):
            skip.add(i)
    return [(i, l) for i, l in enumerate(lines, 1)
            if i not in skip and not l.strip().startswith("#")]


def _anchor_check():
    """返回 ANCHOR-MISS 说明列表（空 = 全部在位）。"""
    src = _assess_src()
    code = "\n".join(l for _i, l in _code_face())
    bad = []
    for name, old, _new, _n in _SRC_MUTATIONS:
        if old not in src:
            bad.append("变异锚点缺失：%s（锚点 %r）" % (name, old))
    for s in _ANCHORS_BANNED:
        if s in code:
            bad.append("缺陷形态回归：assess 可执行行里仍有 %r" % s)
    for s in _ANCHORS_REQUIRED:
        if s not in code:
            bad.append("新文案锚点缺失：assess 可执行行里找不到 %r" % s)
    return bad


# 生效条件：old 与 new 给定时，取当前 forgetting.assess 的源码做字面替换并以
# forgetting 的模块 globals 副本 exec 出新函数；返回该函数对象（不落盘、不改源文件）。
def _mutate_src(old, new):
    ns = dict(vars(forgetting))
    exec(compile(_assess_src().replace(old, new), "i50a_mut.py", "exec"), ns)
    return ns["assess"]


def _with_patched(fn, run):
    """把 forgetting.assess 临时换成 fn 跑一遍 run()，finally 原样还原。"""
    live = forgetting.assess
    forgetting.assess = fn
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return run()
    finally:
        forgetting.assess = live


def _mutate_mode():
    bad = []
    anchor_bad = _anchor_check()
    if anchor_bad:
        for b in anchor_bad:
            print("  ANCHOR-MISS " + b)
        print("\n锚点自检：FAIL（fail-closed，exit 2）")
        return 2
    with contextlib.redirect_stdout(io.StringIO()):
        clean = _run_groups()
    print("  未变异基线：红项=%d%s" % (clean, "" if clean == 0 else "  ← 基线即红，变异核验无意义"))
    if clean:
        bad.append("未变异基线即失败")
    for name, old, new, expect in _SRC_MUTATIONS:
        fails = _with_patched(_mutate_src(old, new), _run_groups)
        verdict = "命中预期" if fails == expect else "**红项数不符（预期 %d）**" % expect
        print("  变异「%s」→ 红项=%d  %s" % (name, fails, verdict))
        if fails != expect:
            bad.append(name)
    for name, const, val, expect in _CONST_MUTATIONS:
        live = getattr(forgetting, const)
        try:
            setattr(forgetting, const, val)
            fails = _with_patched(forgetting.assess, _run_groups)
        finally:
            setattr(forgetting, const, live)
        verdict = "命中预期" if fails == expect else "**红项数不符（预期 %d）**" % expect
        print("  变异「%s」→ 红项=%d  %s" % (name, fails, verdict))
        if fails != expect:
            bad.append(name)
    print("\n定点变异自证：%s" % ("PASS（每处判据都有变异钉死，且红项数逐处吻合）"
                                  if not bad else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def main() -> int:
    src = os.path.basename(os.path.abspath(__file__))
    if "--mutate" in sys.argv:
        print("!! 定点变异模式：逐个变异判据，套件应转红且红项数吻合\n")
        return _mutate_mode()
    anchor_bad = _anchor_check()
    if anchor_bad:
        for b in anchor_bad:
            print("  ANCHOR-MISS " + b)
        print("\n锚点自检：FAIL（fail-closed，exit 2）——实现改了请同步变异表/文案")
        return 2
    print("锚点自检：PASS（%s；不以 git HEAD 为基线源）" % src)
    for g in _GROUPS:
        g()
    print("\nissue50-a 守卫：%d 通过，%d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        print("失败项：" + "、".join(_FAIL))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
