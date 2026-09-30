# -*- coding: utf-8 -*-
"""拒绝域双语义判据守卫（P0-4 / §5.2）——`boundary_hit` 与资格 REJECT **分开**。

契约（设计稿 `docs/plans/睡眠与自迭代_功能优化设计_v0.4.md` §5.2）：

    拒绝域命中**必须标记为「边界命中」**，与资格判定的 REJECT **分开计数、分开
    呈现**——即：检索「什么条件下不适用」→ 该节点以 `boundary_hit` 命中（可召回、
    可展示）；该节点的**正例资格不受影响**（不因边界命中就 REJECT 它）。

探针给的现状（`md_cg/**` 全仓 grep）：

    `boundary_hit` 字面量**零命中**（只出现在设计稿与本工作流草稿里）；
    `不适用条件` 现在**只在一处**被当负条件用——`MdCG.judge_qualification`
    （`mdcg.py` :2997 取 `non_applicable_conditions` → :2998 调单点
    `neg_condition_hits` → :3000-3002 命中即 `REJECT`）。
    ⇒「同一字段只承载一条语义（负条件→REJECT）」，P0-4 要的两件都**尚未存在**。

本轮**不接检索面**（接线在 P2）：只落判据函数与守卫，检索读数必须零位移。

断言分组：

  B0 判据在位与形状——`boundary_hit` / `is_boundary_query` / `judge_with_boundary`
     / `tally_boundary` / `BOUNDARY_MARKER` 齐备；返回体的**键集逐项钉死**
     （P2 直接依赖的形状）。
  B1 单点结构（静态）——`boundary_hit` 的命中走**既有负条件判据单点**
     `neg_condition_hits`；`judge_with_boundary` 的资格腿走
     `MdCG.judge_qualification`（不重判、不抄第二份）。
  B2 双语义可分（端到端，真建临时库）——边界问句 ⇒ `boundary_hit` 且
     `qualification.state != REJECT`（**不因边界命中而 REJECT**）；
     非边界问句而情境真落在拒绝域 ⇒ 照旧 `REJECT`（**灵敏度不变**）；
     两者 `counts.reject` 与 `counts.boundary_hit` **分开计数**。
  B3 分开呈现——返回体两个顶层键 `qualification` / `boundary` 各自独立；
     标记只出现在 `boundary` 侧，`qualification` 侧不得出现 `marker`。
  B4 聚合计数——`tally_boundary` 的 `self_negation` 恒 0（非 0 = 自否定残留）；
     reject 与 boundary_hit 分别计数、互不掩盖。
  B5 **本轮零接线**——生产源码（除 `mdcg.py` 的定义块本身）内
     `boundary_hit` / `judge_with_boundary` / `tally_boundary` 零命中；
     `mdcg.search` 与 `mdcos.py` 不引用它们 ⇒ 检索读数不可能被本判据改动。

运行：python -X utf8 -m md_cg.test_boundary_hit
      python -X utf8 -m md_cg.test_boundary_hit --head-baseline  # 红基线自证
      python -X utf8 -m md_cg.test_boundary_hit --mutate         # 定点变异自证

退出码（fail-closed）：0 = 全绿 / 红基线确有红项；1 = 断言失败 / 变异未按预期转红；
2 = ANCHOR-MISS（变异锚点在当前源码里找不到）。
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile

from . import mdcg as M
from .mdcg import (BOUNDARY_MARKER, MdCG, boundary_hit, is_boundary_query,
                   strip_boundary_terms, tally_boundary)

_PASS = []
_FAIL = []
_SKIP = []
_SRC = {}
_TMP = tempfile.mkdtemp(prefix="mdcg_boundary_")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 拒绝域条目（语料口径，与既有负条件守卫的 G7 同形）
NEG = "本条不覆盖 tags 字段的扫描面，闸门只扫 content"
DOC = ("# 功能名：写入闸门对 tags 的扫描面\n"
       "# 生效条件：问写入闸门内容闸门的判据时\n"
       "# 子功能：md_cg/writepipe.py\n# 执行：读闸门代码\n"
       "# 验证方式：编译器/静态检查通过\n"
       "# 不适用条件：%s\n" % NEG)

_SHAPE_JWB = {"qualification", "boundary", "counts", "recallable", "reason"}
_SHAPE_QUAL = {"state", "reason", "boundary_suppressed"}
_SHAPE_BND = {"hit", "terms", "marker", "reason"}
_SHAPE_CNT = {"accept", "reject", "defer", "blindspot", "boundary_hit"}


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


def _rel_text(rel: str) -> str:
    if rel in _SRC:
        return _SRC[rel]
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


def _mk_applicable():
    """真建临时库：一个六要素齐全、带拒绝域的节点（走完整写入面）。"""
    from .mdcos import MdCGOS
    r = tempfile.mkdtemp(prefix="bh_", dir=_TMP)
    cg = MdCGOS(r)
    cg.add("bh1", DOC, layer="knowledge", verification_basis="test",
           non_applicable_conditions=[NEG])
    cg.flush()
    got = cg.get("bh1")
    return cg, {"frontmatter": got["frontmatter"], "content": got["content"]}


# ---------------------------------------------------------------- B0
def b0():
    print("== B0 判据在位与返回形状 ==")
    ok(BOUNDARY_MARKER == "boundary_hit",
       "B0 展示标记字面量 = boundary_hit（§5.2 的判据名）")
    for name in ("boundary_hit", "is_boundary_query", "strip_boundary_terms",
                 "tally_boundary"):
        ok(callable(globals().get(name) or getattr(M, name, None)),
           "B0a 模块级判据 `%s` 在位" % name)
    ok(hasattr(MdCG, "judge_with_boundary")
       and isinstance(MdCG.__dict__.get("judge_with_boundary"), staticmethod),
       "B0b MdCG.judge_with_boundary 在位且为 staticmethod（与 judge_qualification 同形）")
    cg, node = _mk_applicable()
    r = MdCG.judge_with_boundary(node, "问：什么条件下不适用？" + NEG)
    ok(set(r) == _SHAPE_JWB, "B0c 顶层键集逐项一致", sorted(set(r)))
    ok(set(r["qualification"]) == _SHAPE_QUAL, "B0d qualification 键集",
       sorted(r["qualification"]))
    ok(set(r["boundary"]) == _SHAPE_BND, "B0e boundary 键集",
       sorted(r["boundary"]))
    ok(set(r["counts"]) == _SHAPE_CNT, "B0f counts 键集", sorted(r["counts"]))
    ok(isinstance(r["recallable"], bool), "B0g recallable 为 bool")
    bh = boundary_hit(node, NEG)
    ok(set(bh) == {"hit", "terms", "marker", "reason", "scene"},
       "B0h boundary_hit 的键集", sorted(bh))
    cg.close()


# ---------------------------------------------------------------- B1
def b1():
    print("== B1 单点结构（静态）==")
    src = _rel_text("md_cg/mdcg.py")
    i = src.index("def boundary_hit(")
    body = src[i:i + 1600]
    ok("neg_condition_hits(terms, scene_str," in body,
       "B1 boundary_hit 的命中走**既有负条件判据单点** neg_condition_hits")
    code = "\n".join(l for l in body.splitlines()
                     if not l.strip().startswith("#"))
    ok("any(w in scene" not in code and "for w in str(" not in code,
       "B1a 不重判、不抄第二份切词实现")
    j = src.index("def judge_with_boundary(")
    jb = src[j:j + 2600]
    ok("MdCG.judge_qualification(" in jb,
       "B1b 资格腿走 MdCG.judge_qualification（不重判）")
    ok(jb.count("MdCG.judge_qualification(") == 2,
       "B1c 两条分支（边界问句摘词面重跑 / 其余原样）各调一次", 
       jb.count("MdCG.judge_qualification("))


# ---------------------------------------------------------------- B2
def b2():
    print("== B2 双语义可分（端到端）==")
    cg, node = _mk_applicable()
    # ① 边界问句：问的就是该节点的拒绝域
    q1 = "这条记忆在什么条件下不适用？" + NEG
    ok(is_boundary_query(q1) is True, "B2 前置：q1 被识别为边界问句", q1)
    r1 = MdCG.judge_with_boundary(node, q1)
    ok(r1["boundary"]["hit"] is True,
       "B2a 边界命中（hit=True）", r1["boundary"])
    ok(r1["boundary"]["marker"] == "boundary_hit",
       "B2b 命中即带展示标记 boundary_hit", r1["boundary"]["marker"])
    ok(r1["qualification"]["state"] != "REJECT",
       "B2c **不因边界命中而 REJECT**：资格态 = %s" % r1["qualification"]["state"],
       r1["qualification"])
    ok(r1["counts"]["boundary_hit"] == 1 and r1["counts"]["reject"] == 0,
       "B2d 分开计数：boundary_hit=1 / reject=0", r1["counts"])
    ok(r1["recallable"] is True, "B2e 可召回可展示（recallable=True）")
    # ② 非边界问句 + 情境真落在拒绝域：灵敏度不变 ⇒ 照旧 REJECT
    r2 = MdCG.judge_with_boundary(node, NEG)
    ok(is_boundary_query(NEG) is False, "B2f 前置：q2 不是边界问句")
    ok(r2["qualification"]["state"] == "REJECT",
       "B2g **灵敏度不变**：非边界问句下情境落在拒绝域 ⇒ 照旧 REJECT",
       r2["qualification"])
    ok(r2["counts"]["reject"] == 1,
       "B2h 该 REJECT 计入 counts.reject（不与边界命中混计）", r2["counts"])
    # ③ 边界问句但拒绝域未命中 ⇒ 无边界命中
    r3 = MdCG.judge_with_boundary(node, "这条记忆在什么条件下不适用？")
    ok(r3["boundary"]["hit"] is False and r3["boundary"]["marker"] is None,
       "B2i 边界问句但词面未命中 ⇒ 无边界标记", r3["boundary"])
    # ④ 不变量批量：任取边界问句组合，(boundary.hit ∧ state==REJECT) 恒假
    bad = []
    for q in ("什么条件下不适用 " + NEG, "何时不适用：" + NEG,
              "拒绝域 " + NEG, "边界条件？" + NEG, NEG + " 什么情况下不适用"):
        rr = MdCG.judge_with_boundary(node, q)
        if rr["boundary"]["hit"] and rr["qualification"]["state"] == "REJECT":
            bad.append(q)
    ok(not bad, "B2j **不变量**：边界命中 ∧ 资格 REJECT 的组合恒不出现", bad)
    cg.close()


# ---------------------------------------------------------------- B3
def b3():
    print("== B3 分开呈现 ==")
    cg, node = _mk_applicable()
    r = MdCG.judge_with_boundary(node, "什么条件下不适用 " + NEG)
    ok("marker" not in r["qualification"],
       "B3 资格面**不含**展示标记（两语义各管各的呈现）",
       sorted(r["qualification"]))
    ok("marker" in r["boundary"],
       "B3a 展示标记只在边界面出现")
    ok(r["qualification"]["boundary_suppressed"] is True,
       "B3b 边界问句下资格判定走了「摘词面重跑」并如实留痕")
    r2 = MdCG.judge_with_boundary(node, NEG)
    ok(r2["qualification"]["boundary_suppressed"] is False,
       "B3c 非边界问句下不摘词面（boundary_suppressed=False，灵敏度不变）")
    cg.close()


# ---------------------------------------------------------------- B4
def b4():
    print("== B4 聚合计数 ==")
    cg, node = _mk_applicable()
    recs = [MdCG.judge_with_boundary(node, "什么条件下不适用 " + NEG),
            MdCG.judge_with_boundary(node, NEG),
            MdCG.judge_with_boundary(node, "写入闸门怎么配"),
            MdCG.judge_with_boundary(node, "何时不适用 " + NEG)]
    t = tally_boundary(recs)
    ok(t["self_negation"] == 0,
       "B4 self_negation=0（边界问句下无自否定残留）", t)
    ok(t["boundary_hit"] == 3 and t["reject"] == 1,
       "B4a 边界命中 3 条 / 资格 REJECT 1 条——**分开计数、互不掩盖**", t)
    ok(t["total"] == 4 and t["reject"] + t["accept"] + t["defer"]
       + t["blindspot"] == 4,
       "B4b 资格四态计数自洽（相加 = total）", t)
    ok(t["recallable"] == 3, "B4c 可召回 3 条（REJECT 那条不可召回）", t)
    cg.close()


# ---------------------------------------------------------------- B5
def b5():
    print("== B5 本轮零接线（检索读数不可能被本判据改动）==")
    d = os.path.join(_REPO, "md_cg")
    hits = []
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".py") or fn.startswith("test_"):
            continue
        if fn == "mdcg.py":
            continue
        t = _rel_text("md_cg/" + fn)
        for k in ("boundary_hit", "judge_with_boundary", "tally_boundary",
                  "is_boundary_query"):
            if k in t:
                hits.append((fn, k))
    ok(not hits, "B5 除 mdcg.py 定义块外，生产源码零引用这组判据", hits)
    src = _rel_text("md_cg/mdcg.py")
    for fn in ("mdcos.py",):
        t = _rel_text("md_cg/" + fn)
        ok("judge_with_boundary" not in t and "boundary_hit" not in t,
           "B5a %s 未引用本判据（检索面接线在 P2）" % fn)
    # search 体内不得引用
    i = src.index("    def search(self, query")
    body = src[i:i + 4000]
    ok("judge_with_boundary" not in body and "boundary_hit" not in body,
       "B5b MdCG.search 体内零引用（本轮不动默认链路）")


_GROUPS = (b0, b1, b2, b3, b4, b5)


def _run_groups() -> int:
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        try:
            g()
        except Exception as exc:                       # noqa: BLE001
            ok(False, "断言组 %s 抛异常：%s" % (g.__name__, exc))
            import traceback
            print(traceback.format_exc()[-900:])
    return len(_FAIL)


# ---------------------------------------------------------------- 变异表
# 锚点 = (名字, rel, old, new)。每次变异必须让套件**转红**：
#   M1 边界问句不做抑制（= P0-4 之前的形态：命中即 REJECT）→ B2c 红
#   M2 不设展示标记（= 边界不可展示）→ B2b/B2i/B3a/B4 红
#   M3 判据不复用单点（抄第二份切词实现）→ B1/B1a 红
_MUTATIONS = (
    ("边界问句不做抑制（改动前形态）", "md_cg/mdcg.py",
     '        if bh["hit"] and bq:', "        if False:"),
    ("不设展示标记", "md_cg/mdcg.py",
     '            "marker": BOUNDARY_MARKER if hit else None,',
     '            "marker": None,'),
    ("判据不复用单点（抄第二份实现）", "md_cg/mdcg.py",
     "    hit = neg_condition_hits(terms, scene_str, MdCG._self_topic_text(fm, content))",
     "    hit = [x for x in terms if any(w in scene_str for w in str(x).split())]"),
)


def _mutate_mode(list_only: bool = False) -> int:
    print("!! 定点变异自证：逐条把双语义判据改回「改动前/失效」形态，套件必须转红\n")
    if list_only:
        for name, rel, _o, _n in _MUTATIONS:
            print("  %-34s [%s]" % (name, rel))
        return 0
    anchor_miss, bad = [], []
    with contextlib.redirect_stdout(io.StringIO()):
        clean = _run_groups()
    print("  未变异基线：失败=%d（必须为 0）" % clean)
    if clean:
        bad.append("未变异基线即失败")

    for name, rel, old, new in _MUTATIONS:
        src = _rel_text(rel)
        if old not in src:
            print("  ANCHOR-MISS %s —— 锚点在 %s 源码里找不到（实现改了却没同步"
                  "本表）" % (name, rel))
            anchor_miss.append(name)
            continue
        mut_src = src.replace(old, new, 1)
        _SRC[rel] = mut_src
        try:
            mut = _exec_module("md_cg._bh_mut", rel, mut_src)
            _install(mut)
            with contextlib.redirect_stdout(buf := io.StringIO()):
                reds = _run_groups()
            detail = buf.getvalue()
        finally:
            _install(M)
            _SRC.pop(rel, None)
        red_lines = [l for l in detail.splitlines()
                     if l.strip().startswith("FAIL ")]
        verdict = "红" if reds else "**仍全绿 = 该判据空转**"
        print("  %s %-34s 红项=%d  %s"
              % ("OK    " if reds else "MISS  ", name, reds, verdict))
        for l in red_lines[:5]:
            print("        " + l.strip()[5:])
        if not reds:
            bad.append(name)

    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s"
          % ("PASS（每处判据都被打红）" if not bad else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def _install(mod) -> None:
    """把某个 mdcg 模块的判据装进守卫的全局名（变异/还原共用）。"""
    global boundary_hit, is_boundary_query, strip_boundary_terms, tally_boundary
    global MdCG, BOUNDARY_MARKER
    boundary_hit = mod.boundary_hit
    is_boundary_query = mod.is_boundary_query
    strip_boundary_terms = mod.strip_boundary_terms
    tally_boundary = mod.tally_boundary
    MdCG = mod.MdCG
    BOUNDARY_MARKER = mod.BOUNDARY_MARKER
    globals()["M"] = mod


def _exec_module(name: str, rel: str, text: str):
    import types
    ns = {"__name__": name, "__package__": "md_cg",
          "__file__": os.path.join(_REPO, rel)}
    exec(compile(text, rel, "exec"), ns)               # noqa: S102 —— 基线自证用
    m = types.ModuleType(name)
    m.__dict__.update(ns)
    return m


def main() -> int:
    try:
        if "--mutate" in sys.argv:
            return _mutate_mode("--list" in sys.argv)
        if "--head-baseline" in sys.argv:
            print("!! 红基线模式：`is_boundary_query` 换回「恒 False」"
                  "（= P0-4 之前的形态：边界词面命中即 REJECT），应当转红\n")
            M.is_boundary_query = lambda q: False
            globals()["is_boundary_query"] = lambda q: False
            n = _run_groups()
            print("\n== 红基线判定：应有失败 ==")
            print("红基线失败数 = %d（>0 才算断言有判别力）" % n)
            for f in _FAIL:
                print("   红:", f)
            return 0 if n else 1
        n = _run_groups()
        print("\n拒绝域双语义判据守卫：%d 通过，%d 失败，%d 跳过"
              % (len(_PASS), n, len(_SKIP)))
        return 0 if not n else 1
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
