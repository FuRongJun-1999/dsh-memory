# -*- coding: utf-8 -*-
"""issue #102 守卫 · 六要素标题解析的「模式构造开销」收口（预构造表 + 回退路径）。

运行：python -m md_cg.test_n102_heading_re_cache
变异自证：python -m md_cg.test_n102_heading_re_cache --mutate A

本件指控的口径（报告人自陈，必须守住）：Python 本就有正则缓存，**不能**称为
「每行重新编译正则」——被指控的是 **模式构造开销**：`_ccg_heading_rest` 每次调用都
`"^#\\s*" + re.escape(mark)` 拼一次模式串，六要素取值/齐全度/正文剥除反复走该单点。
故本守卫**不测「编译次数」**，测的是「热路径上 `re.compile` / `re.escape` 的**调用次数**」
（构造面），并断言固定六字段走预构造表后为 **0**。

四组断言：
  G1 预构造表在场：`nodefile._HEADING_RE` 覆盖全部 CCG_MARKS、值为已编译 Pattern、
     且每个 Pattern 与「即时构造」的语义逐位一致；
  G2 表被真正使用（非摆设）：命中表内 mark 时热路径 `re.compile`/`re.escape` 调用数为 0；
     命中表外 mark（非六要素）时走回退构造，语义与旧实现逐位一致（通用性未坏）；
  G3 边界六条：`# 生效条件`/`#生效条件`/`# 生效条件：v`/`# 生效条件 v` 命中，
     `## 生效条件`/`  # 生效条件` 不命中——逐条与写入闸门 data/policy.json 的
     `(?m)^#\\s*<mark>` 复算比对（同一行语义，不许变）；
  G4 性能读数：同进程内 A/B 交替，新（查表）vs 旧（每次构造）的 ns/call 与倍率。

变异组 A（退化成每次构造）：把 `nodefile._HEADING_RE` 清空 ⇒ 所有 mark 走回退构造
⇒ G2 的「构造次数为 0」当场转红并点名。
"""
from __future__ import annotations

import inspect
import io
import json
import os
import re
import sys
import time

from . import nodefile

PASS = FAIL = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % label)
    else:
        FAIL += 1
        FAILS.append(label)
        print("  [FAIL] %s" % label)


# ---- 构造面计数：热路径上 re.compile / re.escape 被调用几次 ------------------

class _CountConstruct:
    """临时替换 `re.compile` / `re.escape`，统计调用次数（构造面，不是编译面）。

    只在 with 块内生效；退出即还原。nodefile 顶层 `import re` 后以 `re.compile`
    调用，故替换 `re` 模块的同名属性即可命中其调用点。
    """

    def __init__(self):
        self.compile_calls = 0
        self.escape_calls = 0

    def __enter__(self):
        self._c, self._e = re.compile, re.escape

        def _c_counted(*a, **kw):
            self.compile_calls += 1
            return self._c(*a, **kw)

        def _e_counted(*a, **kw):
            self.escape_calls += 1
            return self._e(*a, **kw)

        re.compile = _c_counted
        re.escape = _e_counted
        return self

    def __exit__(self, *exc):
        re.compile = self._c
        re.escape = self._e
        return False


def _construct_calls(fn, n):
    with _CountConstruct() as c:
        for _ in range(n):
            fn()
    return c.compile_calls + c.escape_calls


# ---- 旧实现（即时构造）复算——回退路径的对照真源 ------------------------------

def _old_heading_rest(line, mark):
    """修复前实现（每次构造模式串）——只作对照，不参与生产路径。"""
    m = re.match(r"^#\s*" + re.escape(mark), line or "")
    if not m:
        return None
    return (line or "")[m.end():]


BOUNDARY_HIT = ("# 生效条件", "#生效条件", "# 生效条件：v", "# 生效条件 v")
BOUNDARY_MISS = ("## 生效条件", "  # 生效条件")


def _policy_required(mark):
    """读**真源** data/policy.json，取该要素的必需正则（相对本模块定位）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with io.open(os.path.join(root, "data", "policy.json"), encoding="utf-8") as fh:
        reqs = json.load(fh)["required"]
    return next(re.compile(p) for p in reqs if mark in p)


def main() -> int:
    print("== G1 预构造表在场且语义与即时构造一致 ==")
    tbl = getattr(nodefile, "_HEADING_RE", None)
    ok(isinstance(tbl, dict), "G1a `_HEADING_RE` 在场且为 dict")
    ok(isinstance(tbl, dict) and sorted(tbl) == sorted(nodefile.CCG_MARKS),
       "G1b 表键 == CCG_MARKS 六要素（%s）" % (sorted(tbl) if isinstance(tbl, dict) else None))
    if isinstance(tbl, dict):
        for mark in nodefile.CCG_MARKS:
            pat = tbl.get(mark)
            ok(isinstance(pat, re.Pattern), "G1c[%s] 值为已编译 re.Pattern" % mark)
            if isinstance(pat, re.Pattern):
                # 与即时构造逐位同语义：对一批探针串比对 match 结果与 rest
                probes = ["# %s" % mark, "#%s" % mark, "# %s：v" % mark,
                          "# %s v" % mark, "## %s" % mark, "  # %s" % mark,
                          "# %sx" % mark, "无 # 前缀 %s" % mark]
                same = all(
                    (pat.match(p).end() if pat.match(p) else None)
                    == (re.compile(r"^#\s*" + re.escape(mark)).match(p).end()
                        if re.compile(r"^#\s*" + re.escape(mark)).match(p) else None)
                    for p in probes)
                ok(same, "G1d[%s] 预构造 Pattern 与即时构造逐位同语义" % mark)

    print("== G2 表被真正使用（热路径构造次数为 0）＋ 表外 mark 回退一致 ==")
    # 源码锚点：函数体必须查表（防「表在场但函数仍即时构造」的摆设态）
    src = inspect.getsource(nodefile._ccg_heading_rest)
    ok("_HEADING_RE.get(mark)" in src,
       "G2a 函数体含 `_HEADING_RE.get(mark)`（表确被查）")
    # 热路径：六个固定要素各调用一次 ⇒ 构造面应为 0（构造只在模块导入时发生）
    n_hits = _construct_calls(
        lambda: [nodefile._ccg_heading_rest("# 生效条件：v", m) for m in nodefile.CCG_MARKS], 200)
    ok(n_hits == 0,
       "G2b 命中表内六要素时 re.compile/re.escape 调用数 = %d（期望 0：查表即不构造）" % n_hits)
    # 表外 mark：非六要素任意字符串必须走回退且语义与旧实现逐位一致
    fb_marks = ["自定义字段", "note", "x", "生效条件 ", "生效条", "##"]
    fb_lines = ["# 自定义字段：v", "#自定义字段", "# 自定义字段", "## 自定义字段",
                "  # 自定义字段", "# 自定义字段x", "# note v", "#x", "# ##"]
    for mk in fb_marks:
        for ln in fb_lines:
            got = nodefile._ccg_heading_rest(ln, mk)
            exp = _old_heading_rest(ln, mk)
            if got != exp:
                ok(False, "G2c 回退不一致 mark=%r line=%r got=%r old=%r" % (mk, ln, got, exp))
                break
        else:
            continue
        break
    else:
        ok(True, "G2c 表外 mark（非六要素）回退与旧实现逐位一致（%d mark × %d line）"
           % (len(fb_marks), len(fb_lines)))
    n_fb = _construct_calls(lambda: nodefile._ccg_heading_rest("# 自定义字段：v", "自定义字段"), 50)
    ok(n_fb >= 50, "G2d 表外 mark 确实走即时构造（构造次数 = %d ≥ 50）" % n_fb)

    print("== G3 边界六条（与写入闸门 policy.json 复算比对）==")
    gate = _policy_required("生效条件")
    for line in BOUNDARY_HIT:
        r = nodefile._ccg_heading_rest(line, "生效条件")
        ok(r is not None, "G3 命中：%r → rest=%r" % (line, r))
        ok(bool(gate.search(line)), "G3 闸门同判命中：%r" % line)
    for line in BOUNDARY_MISS:
        r = nodefile._ccg_heading_rest(line, "生效条件")
        ok(r is None, "G3 不命中：%r → %r" % (line, r))
        ok(not gate.search(line), "G3 闸门同判不命中：%r" % line)

    print("== G4 性能读数（同进程 A/B 交替，构造面开销）==")
    LINE = "# 生效条件：值"
    N = 200_000
    # 预热
    for _ in range(2000):
        nodefile._ccg_heading_rest(LINE, "生效条件")
        _old_heading_rest(LINE, "生效条件")
    t0 = time.perf_counter()
    for _ in range(N):
        nodefile._ccg_heading_rest(LINE, "生效条件")
    t_new = time.perf_counter() - t0
    t0 = time.perf_counter()
    for _ in range(N):
        _old_heading_rest(LINE, "生效条件")
    t_old = time.perf_counter() - t0
    ns_new, ns_old = t_new / N * 1e9, t_old / N * 1e9
    print("  样本 N=%d ｜ 新（查表）%.1f ns/call（%.4fs）｜ 旧（每次构造）%.1f ns/call（%.4fs）"
          % (N, ns_new, t_new, ns_old, t_old))
    print("  → 构造面开销消除，约 %.2fx" % (ns_old / ns_new if ns_new else float("nan")))
    ok(ns_new < ns_old, "G4 新实现快于旧实现（%.1f < %.1f ns/call）" % (ns_new, ns_old))

    print()
    print("n102_heading_re_cache: PASS=%d FAIL=%d" % (PASS, FAIL))
    if FAILS:
        print("FAILS: " + "; ".join(FAILS))
    return 1 if FAIL else 0


# ---- 定点变异自证 -------------------------------------------------------------

def _mut_degrade_no_table():
    """退化：清空 `_HEADING_RE` ⇒ 所有 mark 走回退即时构造（= 缺陷形态复现）。"""
    orig = nodefile._HEADING_RE
    nodefile._HEADING_RE = {}
    return lambda: setattr(nodefile, "_HEADING_RE", orig)


def _mut_break_fallback():
    """退化：把回退路径弄坏（表外 mark 恒不命中）——证明守卫护住了「非六要素 mark 不许坏」。

    实现手法：临时把 `_ccg_heading_rest` 换成「只查表、表外恒 None」的版本——
    这正是「为提速牺牲通用性」的缺陷形态。期望 G2c（回退一致性）当场转红。
    """
    orig = nodefile._ccg_heading_rest

    def _broken(line, mark):
        pat = nodefile._HEADING_RE.get(mark)
        if pat is None:
            return None          # 表外 mark 直接判不命中 = 通用性被弄坏
        s = line or ""
        m = pat.match(s)
        return None if not m else s[m.end():]

    nodefile._ccg_heading_rest = _broken
    return lambda: setattr(nodefile, "_ccg_heading_rest", orig)


_MUTATIONS = {
    "A": [("退化：清空 _HEADING_RE ⇒ 每次构造模式串", _mut_degrade_no_table,
           ("G2b", "G1b"))],
    "B": [("退化：表外 mark 恒不命中（弄坏回退/通用性）", _mut_break_fallback,
           ("G2c",))],
}


def _probe():
    """跑 main 断言，返回 (红项标签列表, 退出码)。"""
    global PASS, FAIL, FAILS
    PASS = FAIL = 0
    FAILS = []
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rc = main()
    finally:
        sys.stdout = old
    return list(FAILS), rc


def _mutate(name):
    if name not in _MUTATIONS:
        print("未知组名 %r（可选 %s）" % (name, sorted(_MUTATIONS)))
        return 1
    print("!! #102 定点变异自证 · 组 %s：内存注入，要求红项**点名**到期望断言\n" % name)
    base_red, base_rc = _probe()
    print("  未变异基线：红项 %s（应为 []）｜rc=%d（应为 0）" % (base_red, base_rc))
    bad = []
    if base_red or base_rc != 0:
        bad.append("基线不符：红 %s rc=%d" % (base_red, base_rc))
    for mname, apply, expect_substr in _MUTATIONS[name]:
        restore = apply()
        try:
            red, rc = _probe()
        finally:
            restore()
        hit = all(any(e in r for r in red) for e in expect_substr) and rc == 1
        print("  [%s] %s → rc=%d 红项 %s（须含 %s）"
              % ("OK" if hit else "BAD", mname, rc, red, list(expect_substr)))
        if not hit:
            bad.append("%s：得 rc=%d 红%s，期望含 %s" % (mname, rc, red, list(expect_substr)))
    if bad:
        print("\n变异自证失败：")
        for b in bad:
            print("  · " + b)
        return 1
    print("\n变异自证通过：%d 条各自命中期望断言" % len(_MUTATIONS[name]))
    return 0


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        _i = sys.argv.index("--mutate")
        sys.exit(_mutate(sys.argv[_i + 1] if _i + 1 < len(sys.argv) else ""))
    sys.exit(main())
