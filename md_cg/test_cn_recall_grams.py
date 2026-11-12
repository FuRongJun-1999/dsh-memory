# -*- coding: utf-8 -*-
r"""守卫 · #108 中文召回键的**预算分配**（长拼接查询下召回只覆盖开头）。

病灶（HEAD，逐字内联为 _OLD 供对拍/变异）：
    md_cg/mdcg.py 的 cn_recall_grams 逐段 append gram，一旦 len(out) >= cap
    就**整函数返回** ⇒ 多段查询（题卡式「两段以换行拼接」）只有**开头段**进入
    召回键。实测 64 字 + 12 字两段查询：末段 gram 覆盖 0.000（cap=16/32）、
    0.159（cap=64）。

判据：
  A 单段查询逐位不变（与旧实现逐字对拍）
  B 多段且 gram 总数 <= cap ⇒ 逐位同旧（预算够时零差异）
  C 预算不足 ⇒ **末段覆盖率 >= 0.5**（旧为 0.000），且首段仍被覆盖   ← 本笔主判据
  D cap=None = 「不限」：返回全部 gram（覆盖 1.000）且 > 默认 cap     ← 新增能力
  E cap=0 **不是**「不限」：与旧实现同为「首个 gram」1 个（钉住误用）
  F 去重/停用词/段序语义不变（不限时与旧实现逐位相同）
  G MDCG_CN_GRAMS=0 ⇒ 新旧同为 []
  H 端到端（tempfile 沙箱）：正文只含末段 gram 时，expand_query_terms 能给出
    命中该正文的 term（旧实现给不出）——即「候选资格」被恢复        ← 本笔主判据
运行：
  python -X utf8 -m md_cg.test_cn_recall_grams                 # 期望 0 退出
  python -X utf8 -m md_cg.test_cn_recall_grams --mutate=old    # 期望 1 退出
  变异期望红 = {C, H}（主判据）+ {D, F}（旧实现无 cap=None 能力，属能力级红）
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from md_cg import mdcg  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

PASS = FAIL = 0
FAILS = []
BIG = 10 ** 9          # 旧实现的「不限」等价写法（它不支持 cap=None）


def _OLD(query: str, min_run: int = 4, cap: int = 16) -> list:
    """旧实现逐字内联（取自 HEAD:md_cg/mdcg.py 的 cn_recall_grams 函数体）。
    仅供「逐位对拍」与「--mutate=old 定点变异」用，**不参与生产路径**。"""
    if os.environ.get("MDCG_CN_GRAMS") == "0":
        return []
    out = []
    for run in re.findall(r"[\u4e00-\u9fff]{%d,}" % max(min_run, 2), query or ""):
        for i in range(len(run) - 1):
            g = run[i:i + 2]
            if g in mdcg.CN_STOP_GRAMS or g in out:
                continue
            out.append(g)
            if len(out) >= cap:
                return out
    return out


def call(fn, q, **kw):
    """调用被测实现；不支持的能力（如旧实现的 cap=None）返回哨兵而非崩栈。"""
    try:
        return fn(q, **kw)
    except TypeError as exc:
        return "ERR:TypeError(%s)" % exc


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (label, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(label)
        print("[FAIL] %s  · %s" % (label, detail))


def grams_all(q):
    """全量 gram（同口径：>=4 连续中文串、2-gram、去重、剔停用词、段序）。"""
    out = []
    for run in re.findall(r"[\u4e00-\u9fff]{4,}", q or ""):
        for i in range(len(run) - 1):
            g = run[i:i + 2]
            if g not in mdcg.CN_STOP_GRAMS and g not in out:
                out.append(g)
    return out


def _terms_with_old_grams(q):
    """旧实现下的 expand_query_terms 等值替身（只替换 gram 来源，其余同生产）。"""
    saved = mdcg.cn_recall_grams
    mdcg.cn_recall_grams = _OLD
    try:
        return mdcg.expand_query_terms(q)
    finally:
        mdcg.cn_recall_grams = saved


EX1 = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥"
TOPIC = ["数据同步", "检索过滤", "缓存分层", "索引快照", "并发写入", "容量上限",
         "路径解析", "会话归属", "召回扩展", "截断窗口", "治理积压", "提案裁决",
         "密级过滤", "来源标注", "批量处置", "演练预览", "留痕审计", "阈值告警"]
SEG_A = "".join(TOPIC[(3 * k) % len(TOPIC)] for k in range(16))     # 64 字
SEG_B = (EX1 * 5)[0:12]                                            # 12 字
LONG_Q = SEG_A + "\n" + SEG_B
SHORT_QS = ["酪氨酸激酶抑制剂", "抑制剂怎么选", "中文召回扩展的预算分配",
            "缓存分层与索引快照", "检索过滤", "数据同步检索过滤缓存分层",
            "灵枢 hotcache 设计说明", "长查询拼接预算"]
SMALL_MULTI = ["数据同步\n检索过滤", "缓存分层索引快照\n并发写入容量上限",
               "召回扩展\n截断窗口治理积压", "路径解析会话归属\n密级过滤来源标注"]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    mutate = None
    for a in argv:
        if a.startswith("--mutate="):
            mutate = a.split("=", 1)[1]
    func = mdcg.cn_recall_grams
    if mutate == "old":            # 定点变异：换回修复前实现（逐字内联版）
        func = _OLD
        mdcg.cn_recall_grams = _OLD
    print("被验实现 = %r | mutate=%s" % (getattr(func, "__name__", "?"), mutate))
    print("LONG_Q: 首段 %d 字 + 末段 %d 字（共 %d 字）"
          % (len(SEG_A), len(SEG_B), len(LONG_Q)))

    # ---- A 单段逐位不变 ----
    bad = [q for q in SHORT_QS if call(func, q) != _OLD(q)]
    ok(not bad, "A 单段查询逐位不变（%d 例对拍）" % len(SHORT_QS),
       "差异例 = %r" % bad[:2])

    # ---- B 多段、总数 <= cap ⇒ 逐位同旧 ----
    small = [q for q in SMALL_MULTI if len(grams_all(q)) <= 16]
    bad = [q for q in small if call(func, q) != _OLD(q)]
    ok(bool(small) and not bad, "B 多段且总数<=cap 逐位同旧（%d 例）" % len(small),
       "差异例 = %r" % bad[:2])

    # ---- C 预算不足 ⇒ 末段覆盖（主判据） ----
    gB = {SEG_B[i:i + 2] for i in range(len(SEG_B) - 1)}
    gA = set(grams_all(SEG_A))
    full = grams_all(LONG_Q)
    keys = call(func, LONG_Q)
    ks = set(keys) if isinstance(keys, list) else set()
    covB = len(ks & gB) / max(1, len(gB))
    covA = len(ks & gA) / max(1, len(gA))
    ok(covB >= 0.5, "C 预算不足时末段覆盖 >=0.5",
       "末段覆盖=%.3f（键 %d 个：首段命中 %d / 末段命中 %d）"
       % (covB, len(keys) if isinstance(keys, list) else -1,
          len(ks & gA), len(ks & gB)))
    ok(covA > 0, "C2 首段仍被覆盖（轮转不牺牲开头）", "首段覆盖=%.3f" % covA)
    ok(isinstance(keys, list) and len(keys) <= 16, "C3 键数不超预算",
       "len=%s" % (len(keys) if isinstance(keys, list) else keys))

    # ---- D cap=None = 不限 ----
    un = call(func, LONG_Q, cap=None)
    ok(isinstance(un, list) and len(un) == len(full) and len(un) > 16,
       "D cap=None = 不限（返回全部 gram）",
       "len=%s / full=%d" % (len(un) if isinstance(un, list) else un, len(full)))

    # ---- E cap=0 不是「不限」 ----
    z0 = call(func, LONG_Q, cap=0)
    ok(isinstance(z0, list) and len(z0) == 1 and z0 == _OLD(LONG_Q, cap=0)
       and len(z0) != len(full),
       "E cap=0 = 首个 gram（**不是**不限；与旧实现逐位同）",
       "cap=0 -> %r（旧 -> %r，不限 -> %d 个）" % (z0, _OLD(LONG_Q, cap=0), len(full)))

    # ---- F 去重/段序/停用词语义（不限时逐位同旧） ----
    rep = "数据同步数据同步\n检索过滤检索过滤的了一个"
    a_rep, b_rep = call(func, rep, cap=None), _OLD(rep, cap=BIG)
    ok(a_rep == b_rep, "F 不限时去重·停用词·段序与旧实现逐位相同",
       "%r" % (a_rep if not isinstance(a_rep, list) else a_rep[:6],))

    # ---- G 开关 ----
    os.environ["MDCG_CN_GRAMS"] = "0"
    a0, b0 = call(func, LONG_Q), _OLD(LONG_Q)
    os.environ.pop("MDCG_CN_GRAMS", None)
    ok(a0 == [] and b0 == [], "G MDCG_CN_GRAMS=0 ⇒ 新旧同为 []", "%r/%r" % (a0, b0))

    # ---- H 端到端：候选资格（主判据） ----
    sand = tempfile.mkdtemp(prefix="cn_grams_guard_")
    try:
        cg = MdCGOS(sand)
        body = "\n".join(SEG_B[2 * i:2 * i + 2] for i in range(6))
        cg.add("tgt", body, layer="knowledge")
        bl = body.lower()
        terms = mdcg.expand_query_terms(LONG_Q)
        hit_terms = [t for t in terms if t in bl]
        old_hits = [t for t in _terms_with_old_grams(LONG_Q) if t in bl]
        ok(bool(hit_terms), "H 候选资格恢复：expand_query_terms 给出命中正文的 term",
           "命中 %d 个（例：%r）｜旧实现命中数=%d"
           % (len(hit_terms), [t[:8] for t in hit_terms[:3]], len(old_hits)))
        cg.close()
    finally:
        shutil.rmtree(sand, ignore_errors=True)

    print("\ncn_recall_grams: %d pass / %d fail" % (PASS, FAIL))
    for f in FAILS:
        print(" - 红：%s" % f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
