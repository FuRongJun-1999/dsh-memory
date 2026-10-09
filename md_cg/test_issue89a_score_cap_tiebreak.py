# -*- coding: utf-8 -*-
r"""守卫 · issue #89①：分数封顶 1.0 后同分不可分辨 ⇒ 精确命中被 id 字典序挤出。

缺陷（GitHub #89，本端实测复现 2026-10-09）：打分走 bigram 覆盖度，**连续整串**
与「分散出现同样两个 bigram」得分**逐位相同**（实测 10 条 sim 全 = 1.0）；封顶
min(1.0, ...) 后完全不可分辨 ⇒ 排序退化到 id 字典序 ⇒ 精确命中被挤出 top-k
（复现：10 条同分、精确命中 id 字典序最大 ⇒ 改前 top5 = n01..n05，不含 n10）。

**issue 建议 1 前半句（封顶前保留原始分）经实测不成立**：封顶前的原始分同样
全 = 1.0（sim 与 sim+tag_bonus 逐条相同）——原始分本身就没有分辨力。故判据
落在**分数之外**：整串精确命中 0/1 标记作**次级排序键**（建议 1 后半句），
分数与阈值语义一字不动。

判据单点 mdcg.exact_hit_of 与 neg_condition_hits 判据 ① **同源**
（去全部空白后作子串 + 长度下限 2），检索面的「整串命中」只有这一个口径。

判据：
  G1 判据单点形态：内部键下划线前缀、长度下限 >= 2
  G2 exact_hit_of 行为：连续整串→1；分散同 bigram→0；短于下限→0；空值→0
  G3 端到端（本笔靶区）：10 条同分 + 精确命中 id 字典序最大 ⇒ 改后精确命中在 top1
  G4 分数契约不变：全部 score 仍落在 [0,1]（封顶未被突破）
  G5 内部键**不透出**：结果 doc 不含 EXACT_HIT_KEY（出口剥离生效）
  G6 三处排序点都带次级键 + 出口剥离在位（源码计数，锚点漂移 fail-closed）
  G7 既有「重要度作次级键」未被挤出：三处仍含 importance 且次级键在其**之前**

运行：
  python -X utf8 -m md_cg.test_issue89a_score_cap_tiebreak
  python -X utf8 -m md_cg.test_issue89a_score_cap_tiebreak --mutate A
退出码：0 全绿 ｜ 1 断言失败 ｜ 2 锚点漂移（fail-closed）
"""
from __future__ import annotations

import contextlib
import inspect
import io
import os
import sys
import tempfile

from . import mdcg
from .mdcg import MdCG
from .mdcos import MdCGOS

PASS = 0
FAIL = 0
FAILS: list = []

_FILL = "芙蓉峰下的记忆检索排序通路验证语料，用于制造同分并列的检索场景。"
_EXACT_BODY = _FILL + "本条第10项：此处为连续的灵枢阁整串命中。"
_PART_BODY = _FILL + "本条第1项：灵枢一词与枢阁一词在此分隔出现。"
_QUERY = "灵枢阁"

#: 源码锚点（字面 → 期望出现次数）。实现漂移则计数变 ⇒ 变异表失效 ⇒ exit 2。
_SRC_COUNTS = [
    ('EXACT_HIT_KEY = "_exact_hit"', 1),          # 判据单点定义
    ("EXACT_HIT_KEY: exact_hit_of(q, c)", 1),     # _score 携带
    ("-int(scored[i][0].get(EXACT_HIT_KEY) or 0)", 1),   # cut_by_relevance
    ("-int(x[0].get(EXACT_HIT_KEY) or 0)", 2),    # _emit 终排 + S3 合并
    ("_r[0].pop(EXACT_HIT_KEY, None)", 1),        # 出口剥离
]


def _file_src():
    """读**落盘源码**（不是运行时对象）——源码形态断言必须读文件，
    否则变异自证里被 patch 的函数会让断言读到变异体、抛 ValueError 假红。"""
    with io.open(os.path.join(os.path.dirname(os.path.abspath(mdcg.__file__)),
                              "mdcg.py"), encoding="utf-8") as f:
        return f.read()


def _segment(src, start_marker):
    """从落盘源码里截出 start_marker 起、到下一个同级 def 之前的一段。"""
    i = src.index(start_marker)
    indent = "\n" + (" " * (len(start_marker) - len(start_marker.lstrip())))
    j = src.find(indent + "def ", i + 1)
    return src[i:j if j > 0 else len(src)]


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s  · %s" % (name, detail))


def _build():
    """10 条同分语料：n01..n09 分散命中，n10 连续整串命中（id 字典序最大）。"""
    tmp = tempfile.mkdtemp(prefix="i89a_guard_")
    cg = MdCGOS(tmp)
    for i in range(1, 10):
        cg.add("n%02d" % i,
               _FILL + "本条第%d项：灵枢一词与枢阁一词在此分隔出现。" % i,
               layer="knowledge", content_kind="code", verification_basis="test",
               consistency=False)
    cg.add("n10", _EXACT_BODY, layer="knowledge", content_kind="code",
           verification_basis="test", consistency=False)
    cg.flush()
    return cg


def _rank(cg, k=5):
    with contextlib.redirect_stdout(io.StringIO()):
        res, _meta = cg.search(_QUERY, k=k)
    return res


def group_a(root=None):
    check("G1a 内部键带下划线前缀（内部键约定）",
          mdcg.EXACT_HIT_KEY.startswith("_"), mdcg.EXACT_HIT_KEY)
    check("G1b 长度下限 >= 2（与 NEG_MIN_TERM 同口径）",
          int(mdcg.EXACT_MIN_LEN) >= 2, str(mdcg.EXACT_MIN_LEN))

    check("G2a 连续整串 -> 1", mdcg.exact_hit_of(_QUERY, _EXACT_BODY) == 1)
    check("G2b 分散同 bigram（不连续）-> 0",
          mdcg.exact_hit_of(_QUERY, _PART_BODY) == 0)
    check("G2c 短于长度下限 -> 0", mdcg.exact_hit_of("灵", _EXACT_BODY) == 0)
    check("G2d 空查询/空正文 -> 0",
          mdcg.exact_hit_of("", _EXACT_BODY) == 0
          and mdcg.exact_hit_of(_QUERY, "") == 0)
    check("G2e 空白差异不误判（去空白后连续）",
          mdcg.exact_hit_of("灵 枢 阁", "…灵枢阁…") == 1)

    cg = _build()
    try:
        res = _rank(cg, k=5)
        ids = [d["id"] for d, _s, _q in res[:5]]
        check("G3 端到端：精确命中（id 字典序最大）进 top1",
              ids[:1] == ["n10"], "top5=%s" % ids)
        sc = [float(s) for _d, s, _q in res]
        check("G4 分数契约不变：全部 score 仍落在 [0,1]",
              bool(sc) and all(0.0 <= x <= 1.0 for x in sc), "scores=%s" % sc)
        leaked = [d["id"] for d, _s, _q in res if mdcg.EXACT_HIT_KEY in d]
        check("G5 内部键不透出（出口剥离生效）", not leaked, "泄漏=%s" % leaked)
    finally:
        cg.close()

    src = _file_src()
    check("G6 三处排序点 + 携带 + 剥离共 5 类锚点齐备（计数）",
          all(src.count(a) == n for a, n in _SRC_COUNTS),
          "实测=%s" % {a: src.count(a) for a, _n in _SRC_COUNTS})

    cut_src = _segment(src, "def cut_by_relevance(")
    emit_src = _segment(src, "    def _emit(")
    check("G7a cut_by_relevance：次级键在 importance 之前",
          "EXACT_HIT_KEY" in cut_src and 'get("importance")' in cut_src
          and cut_src.index("EXACT_HIT_KEY") < cut_src.index('get("importance")'))
    check("G7b _emit 终排：次级键在 importance 之前",
          "EXACT_HIT_KEY" in emit_src and 'get("importance")' in emit_src
          and emit_src.index("EXACT_HIT_KEY") < emit_src.index('get("importance")'))
    check("G7c 两处仍保留 importance 作次级键（既有契约未删）",
          'get("importance")' in cut_src and 'get("importance")' in emit_src)


_GROUPS = {"A": group_a}


def _anchor_preflight():
    src = _file_src()
    bad = [(a, src.count(a), n) for a, n in _SRC_COUNTS if src.count(a) != n]
    if not bad:
        return 0
    for a, got, want in bad:
        print("  ANCHOR-MISS %s：命中 %d 次（期望 %d）" % (a[:52], got, want))
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed）")
    return 2


def _mut_exact_always_zero():
    """判据失效：恒判非精确 ⇒ 排序退回 id 字典序（复现 #89① 缺陷形态）。"""
    orig = mdcg.exact_hit_of
    mdcg.exact_hit_of = lambda q, c: 0
    return lambda: setattr(mdcg, "exact_hit_of", orig)


def _mut_exact_always_one():
    """退化解：恒判精确 ⇒ 判据失去分辨力。"""
    orig = mdcg.exact_hit_of
    mdcg.exact_hit_of = lambda q, c: 1
    return lambda: setattr(mdcg, "exact_hit_of", orig)


def _mut_min_len_zero():
    """长度下限退化到 0：空串也判命中。"""
    orig = mdcg.EXACT_MIN_LEN
    mdcg.EXACT_MIN_LEN = 0
    return lambda: setattr(mdcg, "EXACT_MIN_LEN", orig)


def _mut_no_strip():
    """出口剥离失效：内部键随 doc 透出。"""
    orig = MdCG._emit

    def _patched(self, *a, **kw):
        out, meta = orig(self, *a, **kw)
        for r in out:
            if isinstance(r[0], dict):
                r[0][mdcg.EXACT_HIT_KEY] = 1     # 模拟「未剥离」
        return out, meta

    MdCG._emit = _patched
    return lambda: setattr(MdCG, "_emit", orig)


#: 组 → [(变异名, 应用函数, 期望转红断言前缀集合)]
_MUTATIONS = {
    "A": [
        ("判据失效：恒判非精确（复现 #89① 缺陷形态）", _mut_exact_always_zero,
         {"G2a", "G2e", "G3"}),
        ("退化解：恒判精确（判据失去分辨力）", _mut_exact_always_one,
         {"G2b", "G2c", "G2d", "G3"}),
        ("长度下限退化到 0（空串也判命中）", _mut_min_len_zero,
         {"G1b", "G2c", "G2d"}),
        ("出口剥离失效（内部键透出）", _mut_no_strip, {"G5"}),
    ],
}


def _run_group(name, root=None):
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    _GROUPS[name](root)
    return ({n.split(" ", 1)[0] for n in FAILS}, PASS, FAIL)


def _mutate(name):
    if name not in _MUTATIONS:
        print("未知组名 %r（可选 %s）" % (name, sorted(_MUTATIONS)))
        return 1
    rc = _anchor_preflight()
    if rc:
        return rc
    print("!! #89① 定点变异自证 · 组 %s：内存注入退化，逐条要求**恰好**命中期望\n" % name)
    bad = []
    with contextlib.redirect_stdout(io.StringIO()):
        base_red, _, _ = _run_group(name)
    print("  未变异基线：红项 %d %s" % (len(base_red), "（应为 0）" if not base_red else sorted(base_red)))
    if base_red:
        bad.append("基线即转红：%s" % sorted(base_red))
    for mname, apply, expect in _MUTATIONS[name]:
        restore = apply()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                red, _, _ = _run_group(name)
        except Exception as exc:                       # noqa: BLE001
            red = {"<变异体异常:%s>" % type(exc).__name__}
        finally:
            restore()
        ok = (red == expect)
        print("  [%s] %s → 红项 %s（期望 %s）" % ("OK" if ok else "BAD", mname, sorted(red), sorted(expect)))
        if not ok:
            bad.append("%s：得 %s 期望 %s" % (mname, sorted(red), sorted(expect)))
    if bad:
        print("\n变异自证失败：")
        for b in bad:
            print("  · " + b)
        return 1
    print("\n变异自证通过：%d 条退化各自**恰好**命中期望红项" % len(_MUTATIONS[name]))
    return 0


def main():
    print("[#89① 分数封顶同分裁决] 正断言组 A")
    _run_group("A")
    print("\n==== #89① 结果：%d 通过 / %d 失败 ====" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        _i = sys.argv.index("--mutate")
        sys.exit(_mutate(sys.argv[_i + 1] if _i + 1 < len(sys.argv) else ""))
    sys.exit(main())
