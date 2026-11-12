# -*- coding: utf-8 -*-
"""consolidate 负条件「两道闸窗口」守卫（issue #278）。

【守什么】
#278 报：consolidate 对 knowledge 层反复 REJECT，根因是
    neg_separated = _neg_hit(...) and _weighted_coverage(neg, body) < 0.5
与 REFLECT_PROMPT 第 2 条「不适用条件必须是**正文之外的邻近易混情境**」互斥。

复核：**机理成立，但报告的处方不成立**——报告只跑了 replay_check（闸门 2），
**跳过了闸门 1（grounding）**。两道闸方向相反，夹出一条窄缝：

    闸门 1  grounding_score(neg, body)      >= 0.34   ⇒ 必须**复用**正文领域名词
    闸门 2  _weighted_coverage(neg, body)   <  0.5    ⇒ 又不能复用**太多**

⇒ 报告建议的「换域」（完全域外，如「在 Linux 或 macOS 上部署时」）grounding=0.0，
   **过不了闸门 1**，会被 grounding_filter 丢光 ⇒ neg_dropped_all ⇒ 照样 REJECT。
   若按报告建议 1 去改 prompt，会把「被闸门 2 拒」换成「被闸门 1 丢」，**不解决**。

判据：
  W1  两道闸都在场且方向相反（结构性自证）。
  W2  报告读数复现：prompt 口径的「邻近易混」负条件被闸门 2 拒（机理成立）。
  W3  **报告的处方不成立**：完全域外负条件 grounding < 0.34，被闸门 1 丢。
  W4  窗口**非空**：复用正文领域名词 + 换场景短语的负条件过两闸（⇒ 可固化，
      不是「恒 REJECT」的死局）。
  W5  窗口**窄**：完全域外 0 条可过；报告处方 3 条全灭。
  W6  阈值成对：0.34（不适用条件）与 0.5 是**一对**，改任一都会平移窗口 ——
      本组钉住这两个数字，改动即红（提醒改的人一起看）。
  W7  闸门 1 丢光 neg ⇒ 走 neg_dropped_all（fail-closed），不落盘。
  W8  文档已写明该窗口（反陈化：只写「域外」的旧措辞正是本件被误读的根因）。

运行：python -X utf8 -m md_cg.test_issue278_neg_window
      python -X utf8 -m md_cg.test_issue278_neg_window --mutate

退出码（fail-closed）：0 = 全绿；1 = 有断言失败 / 变异未按预期转红。
"""
from __future__ import annotations

import io
import os
import sys

from . import consolidate as C
from . import mdcos as MC

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)

_PASS: list = []
_FAIL: list = []


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  -> " + str(extra)) if (extra and not cond) else ""))


# 领域名词密集的技术类正文（与报告节点同构）
BODY = ("dsh-memory 插件升级流程：pnpm 管理依赖，caret 版本写法会让升级范围扩大；"
        "profile 插件升级时须先冻结 lockfile；dsh-memory 插件升级后要重跑门禁。")
POS = ["dsh-memory 插件升级", "pnpm 依赖升级"]

# 按 REFLECT_PROMPT 第 2 条（邻近易混）产出的形态
PROMPT_CONFORMANT = ["依赖写 caret", "非 dsh-memory 插件升级", "其他 profile 插件升级"]
# 报告建议的「换域」形态（完全域外）
REPORT_REMEDY = ["在 npm 而非 pnpm 管理的工程里", "在 Linux 或 macOS 上部署时",
                 "面向公开文档的读者"]
# 实测能过两闸的形态：复用正文领域名词 + 换场景短语
WINDOW = ["pnpm 以外的包管理器", "不用 pnpm 的工程", "非插件升级场景",
          "pnpm 换成 yarn 时", "profile 以外的场景"]


def _g(term):
    return C.grounding_score(term, BODY)


def _cov(term):
    return MC._weighted_coverage(C.expand_query_terms_weighted(term), BODY)


def _passes_both(term):
    return _g(term) >= C.DEFAULT_GROUNDING["不适用条件"] and _cov(term) < C._neg_max_coverage()


def w1():
    print("== W1 两道闸在场且方向相反 ==")
    src = io.open(os.path.join(_REPO, "md_cg", "consolidate.py"),
                  encoding="utf-8", errors="replace").read()
    ok("grounding_score" in src and "def grounding_filter" in src,
       "W1a 闸门 1（grounding）在场")
    ok(callable(C._neg_max_coverage)
       and abs(C._REPLAY_NEG_MAX_DEFAULT - 0.5) < 1e-12,
       "W1b L2 阈值单点仍在（只管「与生效条件/已有知识重复」，不再管「与正文域外」）")

    t = "依赖写 caret"
    ok(_g(t) >= 0.34 and _cov(t) >= 0.5,
       "W1c 同一候选可同时「过闸门1」且「被闸门2拒」⇒ 判据方向确实相反（修前两闸的现场）",
       (_g(t), _cov(t)))


def w2():
    print("== W2 报告读数复现：prompt 口径的负条件被闸门 2 拒 ==")
    for t in PROMPT_CONFORMANT:
        rep = C.replay_check(POS, [t], BODY)
        # ★ 断言已反转（#278 (c) 分层）：原钉「被拒」= 修前行为（修前 = False）；
        #   分层后 L1 只判易混 ⇒ 该行为正是修复目标 ⇒ 现断言 True。原期望留作注释。
        ok(rep["neg_separated"] is True,
           "W2 邻近易混负条件**不再**被拒（L1 允许共享领域词）：%r" % (t[:22],),
           (round(_cov(t), 4), rep))


def w3():
    print("== W3 报告的处方不成立：完全域外过不了闸门 1 ==")
    for t in REPORT_REMEDY:
        ok(_g(t) < C.DEFAULT_GROUNDING["不适用条件"],
           "W3 完全域外负条件被闸门 1 丢：%r" % (t[:24],), round(_g(t), 4))
    ok(_passes_both(REPORT_REMEDY[1]) is False,
       "W3b 「在 Linux 或 macOS 上部署时」过不了两闸（报告建议 1 的直接反例）")


def w4():
    print("== W4 窗口非空：可固化的负条件形态存在 ==")
    survivors = [t for t in WINDOW if _passes_both(t)]
    ok(len(survivors) >= 3,
       "W4a 存在能过两闸的负条件（窗口非空）⇒ 不是「恒 REJECT」死局",
       survivors)
    for t in survivors[:3]:
        rep = C.replay_check(POS, [t], BODY)
        ok(rep["ok"] is True,
           "W4b 窗口内候选 replay ok：%r" % (t[:24],),
           (round(_g(t), 4), round(_cov(t), 4), rep))


def w5():
    print("== W5 窗口窄：两侧都难以满足 ==")
    n_prompt = sum(1 for t in PROMPT_CONFORMANT if _passes_both(t))
    n_remedy = sum(1 for t in REPORT_REMEDY if _passes_both(t))
    ok(n_prompt == 0, "W5a prompt 口径 0/%d 过两闸" % len(PROMPT_CONFORMANT), n_prompt)
    ok(n_remedy == 0, "W5b 报告处方 0/%d 过两闸" % len(REPORT_REMEDY), n_remedy)
    # 窗口「窄」的正确判据：把三类候选放一起，只有一小撮能过；
    # （不能断言 WINDOW 自身有失败项——WINDOW 就是「已筛出的窗口内样本」）
    pool = list(PROMPT_CONFORMANT) + list(REPORT_REMEDY) + list(WINDOW)
    n_ok = sum(1 for x in pool if _passes_both(x))
    ok(n_ok < len(pool) and n_ok <= len(WINDOW),
       "W5c 候选池 %d 条只有 %d 条过两闸（窗口窄）" % (len(pool), n_ok),
       (len(pool), n_ok))


def w6():
    print("== W6 阈值成对：0.34 与 0.5 是同一对旋钮 ==")
    ok(C.DEFAULT_GROUNDING["不适用条件"] == 0.34,
       "W6a 闸门 1 对「不适用条件」的阈值 = 0.34",
       C.DEFAULT_GROUNDING.get("不适用条件"))
    src = io.open(os.path.join(_REPO, "md_cg", "consolidate.py"),
                  encoding="utf-8", errors="replace").read()
    # ★ W6b 改钉（#278 (c) 分层）：原钉「`and _weighted_coverage(tw_neg, body) < _neg_max_coverage()`」
    #   字面在场 —— 那正是被拆掉的 **L1 覆盖率闸**。现改为钉「L2 阈值单点默认值 = 0.5」：
    #   它现在只管「与生效条件/已有知识重复」，不再管「与正文域外」。
    ok(callable(C._neg_max_coverage)
       and abs(C._REPLAY_NEG_MAX_DEFAULT - 0.5) < 1e-12,
       "W6b L2 阈值单点默认值 = 0.5（只管「与生效条件/已有知识重复」，不再管「与正文域外」）")
    ok("平移窗口" in src or "成对" in src or "一对" in src,
       "W6c 源码已写明两者成对（改一个须一起看）")


def w7():
    print("== W7 闸门 1 丢光 neg ⇒ neg_dropped_all（fail-closed）==")
    cand = {"生效条件": POS, "不适用条件": REPORT_REMEDY}
    kept, detail = C.grounding_filter(cand, BODY)
    ok(not (kept.get("不适用条件") or []),
       "W7a 完全域外的 neg 候选被 grounding_filter 全丢",
       detail.get("不适用条件"))
    ok(all(detail["不适用条件"]["scores"][t] < 0.34 for t in REPORT_REMEDY),
       "W7b 每条 grounding 分数都 < 0.34", detail["不适用条件"]["scores"])
    src = io.open(os.path.join(_REPO, "md_cg", "consolidate.py"),
                  encoding="utf-8", errors="replace").read()
    ok('_bump("neg_dropped_all")' in src,
       "W7c 丢光走 neg_dropped_all（fail-closed，不落盘）")


def w8():
    print("== W8 反陈化：文档已写明该窗口（旧措辞正是误读根因）==")
    src = io.open(os.path.join(_REPO, "md_cg", "consolidate.py"),
                  encoding="utf-8", errors="replace").read()
    ok("issue #278" in src, "W8a 源码标注 issue #278")
    # **必须收窄到 replay_check 函数体**：模块头也写了同样的说明，全文件 in 匹配
    # 会在删掉判据处那段文档后仍读到模块头那一份而假绿（变异 V3 实测踩到）。
    i0 = src.index("def replay_check(")
    i1 = src.index("# ---- 写盘（固化）")
    body = src[i0:i1]
    ok("issue #278" in body,
       "W8a2 判据处（replay_check 内）标注 issue #278")
    ok("闸门 1" in body,
       "W8b 判据处写明「完全域外过不了闸门 1」——报告处方的反例")
    ok("窄缝" in body or "窄" in body,
       "W8c 判据处写明这是「窄缝」而非单纯的「域外」")
    ok("复用正文领域名词" in body,
       "W8d 判据处给出可行形态（复用正文领域名词 + 换场景短语）")
    ok("平移窗口" in body or "成对" in body or "一起看" in body,
       "W8e 判据处写明两个阈值成对、改一个须一起看")


_GROUPS = (w1, w2, w3, w4, w5, w6, w7, w8)


def _run_groups() -> int:
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        try:
            g()
        except Exception as exc:                              # noqa: BLE001
            ok(False, "断言组 %s 抛异常：%s" % (g.__name__, exc))
            import traceback
            print(traceback.format_exc()[-700:])
    return len(_FAIL)


def main() -> int:
    n = _run_groups()
    print("\n负条件两闸窗口守卫：%d 通过，%d 失败" % (len(_PASS), n))
    return 1 if n else 0


_MUTATIONS = (
    ("V1 闸门 2 阈值放宽到 0.9（窗口右移，prompt 口径也能过）",
     "        and _weighted_coverage(tw_neg, body) < _neg_max_coverage()",
     "        and _weighted_coverage(tw_neg, body) < 0.9", "W2"),
    ("V2 闸门 1 对不适用条件的阈值降到 0.0（窗口左移，完全域外也能过）",
     'DEFAULT_GROUNDING = {"生效条件": 0.5, "子功能": 0.5, "执行": 0.5, "不适用条件": 0.34}',
     'DEFAULT_GROUNDING = {"生效条件": 0.5, "子功能": 0.5, "执行": 0.5, "不适用条件": 0.0}',
     "W6"),
    ("V3 删掉窗口文档（退回只写「域外」= 本件被误读的根因）",
     "    #    ★ issue #278：上面这句「域外」**单独看会误导**——它只是本闸的条件。",
     "    #    （窗口说明被变异删除）", "W8"),
)


def _reload():
    import importlib
    from . import consolidate as _c
    importlib.reload(_c)
    globals()["C"] = _c


def _mutate() -> int:
    bad = []
    src_p = os.path.join(_REPO, "md_cg", "consolidate.py")
    with io.open(src_p, encoding="utf-8", newline="") as f:
        pristine = f.read()
    if "issue #278" not in pristine:
        print("  SOURCE-ALREADY-MUTATED：consolidate.py 缺 #278 文档，请先恢复源码")
        return 1
    for name, anchor, repl, want in _MUTATIONS:
        with io.open(src_p, encoding="utf-8", newline="") as f:
            orig = f.read()
        NL = "\r\n" if "\r\n" in orig else "\n"
        a_ = anchor.replace("\n", NL)
        r_ = repl.replace("\n", NL)
        try:
            if a_ not in orig:
                print("  ANCHOR-MISS %s" % name)
                bad.append(name)
                continue
            with io.open(src_p, "w", encoding="utf-8", newline="") as f:
                f.write(orig.replace(a_, r_, 1))
            _reload()
            _run_groups()
            reds = list(_FAIL)
            hit = any(r.startswith(want) for r in reds)
            print("  %-4s %-50s 红项=%-3d 命中%s=%s"
                  % ("OK" if hit else "BAD", name, len(reds), want,
                     "是" if hit else "否"))
            if not hit:
                bad.append(name)
        finally:
            with io.open(src_p, "w", encoding="utf-8", newline="") as f:
                f.write(pristine)
            with io.open(src_p, encoding="utf-8", newline="") as f:
                if f.read() != pristine:
                    print("  RESTORE-FAILED %s" % name)
                    bad.append(name + "(恢复失败)")
            _reload()
    if bad:
        print("\n定点变异自证：FAIL -- %s" % "、".join(bad))
        return 1
    print("\n定点变异自证：PASS（每处判据都被打红）")
    return 0


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(_mutate())
    sys.exit(main())
