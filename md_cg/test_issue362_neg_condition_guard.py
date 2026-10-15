# -*- coding: utf-8 -*-
"""issue #362（P1 条件路由）守卫——neg_condition_hits 的否定作用域/归一 +
judge_with_boundary 的边界不压 REJECT。

缺陷（#362 实测读数，2026-10-15 改前探针复现）：

  a 否定句误拒：「现在不是梅雨季节，…」被负条件「梅雨季节」拒绝（REJECT）
    ——命中后不看否定作用域；
  b 全角/大小写不归一：４Ｇ单模终端、ＵＳＢ２．０、pdf vs PDF——负条件与
    查询字面形态不一致即漏拒（routing.py:42 已用 NFKC，本函数只做 \\s+ 归一）；
  c 繁简不互通：載貨電梯 vs 载货电梯——漏拒（**留作已知边界**，见 G5）；
  d 边界问句把 REJECT 压成 DEFER：查询逐字含负条件但带「…适用吗，还是
    不适用」⇒ 裸 judge_qualification=REJECT、judge_with_boundary=DEFER
    （boundary_suppressed=True）。

修复（md_cg/mdcg.py，2026-10-15）：

  a 命中点前 2 字（去空白后）内含否定字（不/非/没/无）⇒ 该次出现处于否定
    作用域；条目/词**每一次**出现都被否定才不计命中。窗口取 2 不取 3：3 字
    会把「…不适用<X>」边界问句措辞误判成对 X 的否定（G3c 钉住）。
  b/c 两侧 NFKC → 去空白 → casefold（与 routing.py 同口径）；繁简为不同
    码位，NFKC 不映射，仓内无繁简表（grep opencc/繁简 无命中）——G5 登记。
  d 摘词面重跑收窄到**边界枚举问句**（is_boundary_enum_query 强标记，
    = BOUNDARY_QUERY_MARKERS 去掉弱标记「不适用」）：「…适用吗，还是
    不适用」按原句判，REJECT 不被压掉，边界侧照常报告双语义。

断言分组：

  G0 判据在位——is_boundary_enum_query/BOUNDARY_ENUM_MARKERS 存在且
     不含弱标记「不适用」。
  G1 否定句不误拒（#362a）——「不是/非/没有/无」+负条件 ⇒ 不 REJECT；
     裸 judge_qualification 与 neg_condition_hits 双层读数。
  G2 全角/大小写归一后照拒（#362b）——４Ｇ/ＵＳＢ２．０/ｐｄｆ 三形态
     双向（条目侧全角 ⇄ 查询侧半角）。
  G3 防过修——普通字面包含照拒；否定词远隔（超出 2 字窗口）照拒；
     多次出现有一次未被否定照拒；边界问句措辞 3 字邻接不误判成否定
     （窗口=2 的判别力锚）。
  G4 边界问句不再压掉 REJECT（#362d）＋纯边界双语义问句既有 DEFER
     行为零回归（强标记问句照旧摘词面重跑）。
  G5 已知边界登记（#362c）——繁简漏拒读数与改前一致，钉住防止无声漂移：
     将来引入繁简映射时本组会转红提醒同步收口。

运行：python -X utf8 -m md_cg.test_issue362_neg_condition_guard
      python -X utf8 -m md_cg.test_issue362_neg_condition_guard --mutate

退出码（fail-closed）：0 = 全绿 / 1 = 断言失败或变异未按预期转红；
2 = ANCHOR-MISS（变异锚点在当前源码里找不到）。
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import types

from . import mdcg as M
from .mdcg import (BOUNDARY_ENUM_MARKERS, BOUNDARY_QUERY_MARKERS, MdCG,
                   is_boundary_enum_query, is_boundary_query,
                   neg_condition_hits)

_PASS = []
_FAIL = []
_SRC = {}
_TMP = tempfile.mkdtemp(prefix="mdcg_i362_")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 语料口径的拒绝域条目（与 test_boundary_hit 的 NEG 同形——纯边界问句的
#: 既有行为以此为锚做零回归）。
NEG_T = "本条不覆盖 tags 字段的扫描面，闸门只扫 content"
DOC_TPL = ("# 功能名：设备适用环境判定\n"
           "# 生效条件：问设备适用环境时\n"
           "# 子功能：md_cg/env.py\n# 执行：读环境代码\n"
           "# 验证方式：编译器/静态检查通过\n"
           "# 不适用条件：%s\n")


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else " FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


def _scene(q: str) -> str:
    return json.dumps({"query": q}, ensure_ascii=False)


def _mk_node(neg):
    """独立临时库（每调用一个 MDCG_ROOT）真建六要素节点，走完整写入面。"""
    from .mdcos import MdCGOS
    root = tempfile.mkdtemp(prefix="i362_", dir=_TMP)
    cg = MdCGOS(root)
    cg.add("n1", DOC_TPL % neg[0], layer="knowledge",
           verification_basis="test", non_applicable_conditions=neg)
    cg.flush()
    got = cg.get("n1") or {}
    node = {"frontmatter": got.get("frontmatter") or {},
            "content": got.get("content") or ""}
    return cg, node


def _rel_text(rel: str) -> str:
    if rel in _SRC:
        return _SRC[rel]
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------- G0
def g0():
    print("== G0 判据在位（#362d 强标记表）==")
    ok("不适用" not in BOUNDARY_ENUM_MARKERS,
       "G0 BOUNDARY_ENUM_MARKERS 不含弱标记「不适用」（枚举/适用性分界在位）",
       BOUNDARY_ENUM_MARKERS)
    ok(set(BOUNDARY_ENUM_MARKERS) == set(BOUNDARY_QUERY_MARKERS) - {"不适用"},
       "G0a 强标记表 = 边界问句表去掉弱标记「不适用」（不另起一套词面）")
    ok(is_boundary_enum_query("什么条件下不适用") is True,
       "G0b 枚举问句（强标记）识别为 True")
    ok(is_boundary_query("梅雨季节适用吗，还是不适用") is True
       and is_boundary_enum_query("梅雨季节适用吗，还是不适用") is False,
       "G0c 适用性问句：弱标记 True / 强标记 False（#362d 缺陷形态的前置）")


# ---------------------------------------------------------------- G1
def g1():
    print("== G1 否定句不误拒（#362a）==")
    for neg_word, q in (("梅雨季节", "现在不是梅雨季节，这台设备能用吗"),
                        ("梅雨季节", "今年并无梅雨季节，能开工吗"),
                        ("载货电梯", "厂里没有载货电梯，走哪个梯"),
                        ("USB2.0", "这台机器非USB2.0接口，怎么接")):
        h = neg_condition_hits([neg_word], _scene(q), "")
        ok(h == [], "G1 否定句不计命中：「%s」对负条件「%s」" % (q, neg_word), h)
    cg, node = _mk_node(["梅雨季节"])
    q = "现在不是梅雨季节，这台设备能用吗"
    st = MdCG.judge_qualification(node, q, None)["state"]
    ok(st != "REJECT", "G1a 端到端：否定句不 REJECT（state=%s）" % st, st)
    st2 = MdCG.judge_qualification(node, "现在正值梅雨季节，设备能用吗", None)["state"]
    ok(st2 == "REJECT", "G1b 正对照：肯定句照旧 REJECT（state=%s）" % st2, st2)
    cg.close()


# ---------------------------------------------------------------- G2
def g2():
    print("== G2 全角/大小写归一后照拒（#362b）==")
    cases = (("4G单模终端", "４Ｇ单模终端能用吗"),
             ("USB2.0", "ＵＳＢ２．０接口认得出吗"),
             ("PDF", "pdf 版说明书在哪"),
             ("ＵＳＢ２．０", "USB2.0 接口认得出吗"),
             ("pdf", "ＰＤＦ文件怎么开"))
    for neg, q in cases:
        h = neg_condition_hits([neg], _scene(q), "")
        ok(bool(h), "G2 归一后照拒：负条件 %r 对问句 %r 命中" % (neg, q), h)
    for neg, q in cases[:3]:
        cg, node = _mk_node([neg])
        st = MdCG.judge_qualification(node, q, None)["state"]
        ok(st == "REJECT", "G2a 端到端照拒：%r / %r → REJECT（state=%s）"
           % (neg, q, st), st)
        cg.close()


# ---------------------------------------------------------------- G3
def g3():
    print("== G3 防过修（灵敏度不回退）==")
    cg, node = _mk_node(["梅雨季节"])
    st = MdCG.judge_qualification(node, "现在是梅雨季节，这台设备能用吗", None)["state"]
    ok(st == "REJECT", "G3 普通字面包含照拒（state=%s）" % st, st)
    h = neg_condition_hits(["梅雨季节"],
                           _scene("不知道梅雨季节是什么意思，这台设备能用吗"), "")
    ok(bool(h), "G3a 否定词远隔（「不知道」距命中点 >2 字）照拒", h)
    h = neg_condition_hits(["梅雨季节"],
                           _scene("现在不是梅雨季节，但档案里记着梅雨季节预警"), "")
    ok(bool(h), "G3b 多次出现有一次未被否定 ⇒ 照拒（不是一律放行）", h)
    cg.close()
    # 窗口=2 的判别力锚：3 字邻接的边界问句措辞「…不适用<X>」不得误判成
    # 对 X 的否定（窗口取 3 时本断言转红——test_boundary_hit B4 语料同形）。
    h = neg_condition_hits([NEG_T], _scene("什么条件下不适用 " + NEG_T), "")
    ok(bool(h), "G3c 边界问句措辞 3 字邻接不误判成否定（窗口=2）", h)
    h = neg_condition_hits(["问ZXQ7"], _scene("问ZXQ7 是什么"), "")
    ok(bool(h), "G3d 语料灵敏度不回退（问ZXQ7）", h)


# ---------------------------------------------------------------- G4
def g4():
    print("== G4 边界问句不压 REJECT（#362d）＋纯边界 DEFER 零回归 ==")
    cg, node = _mk_node(["梅雨季节"])
    q = "梅雨季节适用吗，还是不适用"
    plain = MdCG.judge_qualification(node, q, None)
    ok(plain["state"] == "REJECT",
       "G4 前置：裸 judge_qualification 对该问句 REJECT", plain)
    r = MdCG.judge_with_boundary(node, q, None)
    ok(r["qualification"]["state"] == "REJECT",
       "G4a 边界问句不再压掉 REJECT（route=REJECT）", r["qualification"])
    ok(r["qualification"]["boundary_suppressed"] is False,
       "G4b 适用性问句不走摘词面重跑（boundary_suppressed=False）")
    ok(r["counts"]["reject"] == 1 and r["counts"]["boundary_hit"] == 1,
       "G4c 双语义照常报告：reject=1 / boundary_hit=1 分开计数", r["counts"])
    ok(r["recallable"] is False, "G4d REJECT 不可召回（拒绝域灵敏度不因边界让步）")
    cg.close()
    # 防过修：纯边界双语义问句（强标记）既有 DEFER 行为零回归
    cg, node = _mk_node([NEG_T])
    q2 = "这条记忆在什么条件下不适用？" + NEG_T
    r2 = MdCG.judge_with_boundary(node, q2, None)
    ok(r2["qualification"]["state"] != "REJECT"
       and r2["qualification"]["boundary_suppressed"] is True,
       "G4e 纯边界问句照旧摘词面重跑且不 REJECT（state=%s）"
       % r2["qualification"]["state"], r2["qualification"])
    ok(r2["counts"]["boundary_hit"] == 1 and r2["counts"]["reject"] == 0
       and r2["recallable"] is True,
       "G4f 可召回可展示（B2/B4 语义零回归）", r2["counts"])
    cg.close()


# ---------------------------------------------------------------- G5
def g5():
    print("== G5 已知边界登记（#362c 繁简不互通——未修复，防无声漂移）==")
    h = neg_condition_hits(["载货电梯"], _scene("載貨電梯需要年检吗"), "")
    ok(h == [], "G5 繁简漏拒读数与改前一致（NFKC 不映射异体简繁；仓内无表，"
       "不引入大依赖——引入映射后本断言转红，须同步收口本组）", h)
    cg, node = _mk_node(["载货电梯"])
    st = MdCG.judge_qualification(node, "載貨電梯需要年检吗", None)["state"]
    ok(st != "REJECT", "G5a 端到端读数登记：非 REJECT（已知边界）", st)
    cg.close()


_GROUPS = (g0, g1, g2, g3, g4, g5)


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
# 锚点 = (名字, rel, old, new)。逐条把三处修复分别回退到 #362 之前的形态，
# 对应断言组必须转红（两向读数：回退红 / 恢复绿）：
#   Ma 否定作用域回退（_negated 恒 False = 命中后不看否定）→ G1/G1a 红
#   Mb 归一回退（只去空白 = 无 NFKC/casefold）→ G2/G2a 红
#   Md 边界抑制回退（弱标记也算枚举 = 原地压 REJECT）→ G4/G4a 红
#   （#362c 繁简无代码改动，无可回退项——G5 是登记不是判据。）
_MUTATIONS = (
    ("否定作用域回退（#362a 改前形态）", "md_cg/mdcg.py",
     '            if not any(c in scene_norm[max(0, i - 2):i] for c in "不非没无"):',
     "            if True:"),
    ("NFKC+casefold 归一回退（#362b 改前形态）", "md_cg/mdcg.py",
     '        return re.sub(r"\\s+", "", unicodedata.normalize(\n'
     '            "NFKC", str(s or ""))).casefold()',
     '        return re.sub(r"\\s+", "", str(s or ""))'),
    ("边界抑制回退（#362d 改前形态）", "md_cg/mdcg.py",
     "suppress = bool(bh[\"hit\"] and bq and is_boundary_enum_query(query))",
     "suppress = bool(bh[\"hit\"] and bq)"),
)


def _install(mod) -> None:
    """把某个 mdcg 模块的判据装进守卫的全局名（变异/还原共用）。"""
    global neg_condition_hits, MdCG, is_boundary_query, is_boundary_enum_query
    global BOUNDARY_ENUM_MARKERS, BOUNDARY_QUERY_MARKERS
    neg_condition_hits = mod.neg_condition_hits
    MdCG = mod.MdCG
    is_boundary_query = mod.is_boundary_query
    is_boundary_enum_query = mod.is_boundary_enum_query
    BOUNDARY_ENUM_MARKERS = mod.BOUNDARY_ENUM_MARKERS
    BOUNDARY_QUERY_MARKERS = mod.BOUNDARY_QUERY_MARKERS
    globals()["M"] = mod


def _exec_module(name: str, rel: str, text: str):
    ns = {"__name__": name, "__package__": "md_cg",
          "__file__": os.path.join(_REPO, rel)}
    exec(compile(text, rel, "exec"), ns)               # noqa: S102 —— 变异自证用
    m = types.ModuleType(name)
    m.__dict__.update(ns)
    return m


def _mutate_mode() -> int:
    print("!! 定点变异自证：逐条把三处修复回退到 #362 之前的形态，套件必须转红\n")
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
            mut = _exec_module("md_cg._i362_mut", rel, mut_src)
            _install(mut)
            with contextlib.redirect_stdout(buf := io.StringIO()):
                reds = _run_groups()
            detail = buf.getvalue()
        finally:
            _install(M)
            _SRC.pop(rel, None)
        red_lines = [l for l in detail.splitlines()
                     if l.strip().startswith("FAIL ")]
        verdict = "红" if red_lines else "**仍全绿 = 该修复空转**"
        print("  %s %-38s 红项=%d  %s"
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
          % ("PASS（每处修复都被打红）" if not bad else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def main() -> int:
    try:
        if "--mutate" in sys.argv:
            return _mutate_mode()
        n = _run_groups()
        print("\nissue #362 负条件/边界守卫：%d 通过，%d 失败" % (len(_PASS), n))
        return 0 if not n else 1
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
