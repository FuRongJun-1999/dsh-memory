# -*- coding: utf-8 -*-
"""test_check_unreachable_decode —— check_unreachable 非 UTF-8 解码失败收口守卫（N261）

缺陷（修前形态，HEAD 可复现）：scripts/check_unreachable.py 文件头承诺「任一文件
ast.parse 失败计 FAIL（语法坏）」，但实现的 read_text(encoding="utf-8") 在 try 内、
except 只接 SyntaxError——文件含非 UTF-8 字节时 read_text 抛 UnicodeDecodeError
（ValueError 族，非 SyntaxError）穿出 main：整轮扫描崩溃，stdout 无 [SYNTAX] 行、
无汇总行、其余文件不再被扫。修法（有界）：捕获面扩为
(SyntaxError, UnicodeDecodeError)，解码失败按承诺计 FAIL 并继续扫描。

为什么区分判据不是退出码：未捕获异常时解释器退出码同为 1——「rc=1」在崩溃形态
与 FAIL 形态都成立，故本守卫的区分面是 [SYNTAX] 行、汇总行、坏文件之后其余文件
仍被分析（[UNREACHABLE] 记录与汇总计数）三段。

守卫断言（行为断言：夹具喂给被测实现，读其 stdout 记账与退出码；不做源码文本匹配）：
  A 组 坏字节夹具（scripts/bad.py 非法 UTF-8 + scripts/tail.py 含 1 处 unreachable）：
       A1 退出码 = 1
       A2 [SYNTAX] 行点名 scripts/bad.py
       A3 汇总行存在（崩溃形态 stdout 为空，此腿即红）
       A4 汇总恰 2 文件 / 1 命中 / 1 语法失败（坏文件计入计数且不中断全轮）
       A5 scripts/tail.py 的 unreachable 照常报出（证明坏文件之后继续扫描）
  B 组 对照夹具（仅 scripts/clean.py 干净文件）：
       B1 退出码 = 0；B2 无 [SYNTAX] 行；B3 汇总恰 1 文件 / 0 命中 / 0 语法失败
  C 组 判据未放宽（仅含 unreachable 的好文件）：
       C1 退出码 = 1；C2 [UNREACHABLE] 点名 scripts/dirty.py；C3 无 [SYNTAX]；
       C4 汇总 1 文件 / 1 命中 / 0 语法失败——修解码面不得弱化原检测面
  D 组 红基线自证（默认模式内联）：HEAD 版（git show HEAD:scripts/check_unreachable.py
       物化临时副本）跑坏字节夹具应恰按 A2–A5 点名转红；HEAD 已含修复则 SKIP

用法（任意 cwd）：
  python -X utf8 scripts/test_check_unreachable_decode.py               # 测工作树版
  python -X utf8 scripts/test_check_unreachable_decode.py --impl head   # 红基线取证
  python -X utf8 scripts/test_check_unreachable_decode.py --impl <path> # 指定实现副本
  python -X utf8 scripts/test_check_unreachable_decode.py --mutate      # 定点变异自证
退出码：0 = 全部按预期；1 = 有断言失败 / 变异未按预期转红；2 = 变异锚点失配。
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEFAULT_IMPL = os.path.join(HERE, "check_unreachable.py")

# stdout 记账面（口径 = check_unreachable.main() 的打印格式；格式一变则断言腿红）
_RE_SYNTAX = re.compile(r"^\[SYNTAX\]\s+(.+?\.py):")
_RE_UNREACH = re.compile(r"^\[UNREACHABLE\]\s+(.+?\.py):(\d+)")
_RE_SUMMARY = re.compile(r"unreachable 扫描：(\d+) 文件，命中 (\d+)，语法失败 (\d+)")

# 夹具：bad.py 含非法 UTF-8 字节（\xff 是 UTF-8 非法起始字节）；dirty.py / tail.py
# 各含恰 1 处 unreachable（Return 后同 block 仍有 Assign）。
_ILLEGAL_BYTES = b"x = 1\n# \xff\xfe\xba\xad illegal utf-8 bytes\n"
_DIRTY_SRC = "def f():\n    return 1\n    x = 2\n"
_CLEAN_SRC = "def f():\n    return 1\n"

# 断言名常量（_MUTATIONS 与断言腿共用同一字符串，防两处漂移）
_N_A1 = "A1 坏字节夹具：退出码 = 1"
_N_A2 = "A2 [SYNTAX] 行点名 scripts/bad.py"
_N_A3 = "A3 汇总行存在（崩溃形态 stdout 为空，此腿即红）"
_N_A4 = "A4 汇总恰 2 文件 / 1 命中 / 1 语法失败（坏文件计入且不中断全轮）"
_N_A5 = "A5 scripts/tail.py 的 unreachable 照常报出（坏文件之后继续扫描）"
_N_B1 = "B1 对照夹具（仅好文件）：退出码 = 0"
_N_B2 = "B2 对照夹具：无 [SYNTAX] 行"
_N_B3 = "B3 对照夹具：汇总恰 1 文件 / 0 命中 / 0 语法失败"
_N_C1 = "C1 含 unreachable 的好文件：退出码 = 1"
_N_C2 = "C2 [UNREACHABLE] 点名 scripts/dirty.py"
_N_C3 = "C3 无 [SYNTAX] 行"
_N_C4 = "C4 汇总 1 文件 / 1 命中 / 0 语法失败"

# `--impl head` 红基线必须点名的关键判据（修前缺陷形态的直接断言面：
# 崩溃形态 stdout 为空 → [SYNTAX]/汇总/继续扫描三段全缺失）
_HEAD_EXPECT_RED = (_N_A2, _N_A3, _N_A4, _N_A5)

# 定点变异表：（名称, 源码锚点, 替换文本, 预期转红点名集合）
_MUTATIONS = (
    ("N261 捕获面改回仅 SyntaxError（修前形态）",
     "            except (SyntaxError, UnicodeDecodeError) as e:",
     "            except SyntaxError as e:  # MUT：捕获面退回缺陷形态",
     _HEAD_EXPECT_RED),
)

_RESULTS = []
_SKIPPED = []


def _check(name, cond, detail=""):
    _RESULTS.append((name, bool(cond), str(detail).replace("\n", " | ")[:400]))


def _skip(name, why):
    _SKIPPED.append((name, why))


def _is(path_in_line, want):
    """记账行里的路径是否就是夹具内 want（归一后全等，跨平台）。"""
    return os.path.normpath(path_in_line.strip()) == os.path.normpath(want)


def _mk_fixture(root, files):
    """在 root 下建夹具：files = {相对路径: str|bytes}（str 以 UTF-8 + LF 写出）。"""
    for rel, data in files.items():
        p = os.path.join(root, rel)
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        if isinstance(data, bytes):
            with open(p, "wb") as fh:
                fh.write(data)
        else:
            with open(p, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(data)
    return root


def _run(impl, cwd):
    """子进程直跑被测实现（cwd=夹具；PYTHONPATH 摘除；PYTHONUTF8=1；显式 utf-8）。"""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env.pop("PYTHONPATH", None)
    return subprocess.run([sys.executable, "-X", "utf8", impl],
                          cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env, timeout=120)


def _parse(res):
    """取读数：被点名的 [SYNTAX]/[UNREACHABLE] 路径集合 + 汇总三元组（缺失=None）。"""
    syntax, unreach = [], []
    for line in (res.stdout or "").splitlines():
        m = _RE_SYNTAX.match(line)
        if m:
            syntax.append(m.group(1))
        m = _RE_UNREACH.match(line)
        if m:
            unreach.append((m.group(1), int(m.group(2))))
    m = _RE_SUMMARY.search(res.stdout or "")
    counts = tuple(int(g) for g in m.groups()) if m else None
    return {"syntax": syntax, "unreach": unreach, "counts": counts}


def _tail(res, n=260):
    out = ((res.stdout or "") + "\n--- stderr ---\n" + (res.stderr or "")).strip()
    return out[-n:]


def _case_decode(impl, tmp):
    """A 组：坏字节夹具——解码失败计 FAIL、其余文件照扫。"""
    root = _mk_fixture(os.path.join(tmp, "decode"), {
        "scripts/bad.py": _ILLEGAL_BYTES,
        "scripts/tail.py": _DIRTY_SRC,
    })
    res = _run(impl, root)
    got = _parse(res)
    _check(_N_A1, res.returncode == 1, "rc=%s ｜ %s" % (res.returncode, _tail(res)))
    _check(_N_A2, any(_is(p, "scripts/bad.py") for p in got["syntax"]),
           "syntax=%r ｜ %s" % (got["syntax"], _tail(res)))
    _check(_N_A3, got["counts"] is not None,
           "counts=%r ｜ %s" % (got["counts"], _tail(res)))
    _check(_N_A4, got["counts"] == (2, 1, 1), "counts=%r" % (got["counts"],))
    _check(_N_A5, any(_is(p, "scripts/tail.py") for p, _ln in got["unreach"]),
           "unreach=%r ｜ %s" % (got["unreach"], _tail(res)))


def _case_control(impl, tmp):
    """B 组：对照夹具——仅好文件应全绿（解码面收口不得引入新红）。"""
    root = _mk_fixture(os.path.join(tmp, "control"),
                       {"scripts/clean.py": _CLEAN_SRC})
    res = _run(impl, root)
    got = _parse(res)
    _check(_N_B1, res.returncode == 0, "rc=%s ｜ %s" % (res.returncode, _tail(res)))
    _check(_N_B2, not got["syntax"], "syntax=%r" % (got["syntax"],))
    _check(_N_B3, got["counts"] == (1, 0, 0), "counts=%r" % (got["counts"],))


def _case_not_weakened(impl, tmp):
    """C 组：判据未放宽——原 unreachable 检测面（含退出码 1）保持。"""
    root = _mk_fixture(os.path.join(tmp, "dirty"),
                       {"scripts/dirty.py": _DIRTY_SRC})
    res = _run(impl, root)
    got = _parse(res)
    _check(_N_C1, res.returncode == 1, "rc=%s ｜ %s" % (res.returncode, _tail(res)))
    _check(_N_C2, any(_is(p, "scripts/dirty.py") for p, _ln in got["unreach"]),
           "unreach=%r ｜ %s" % (got["unreach"], _tail(res)))
    _check(_N_C3, not got["syntax"], "syntax=%r" % (got["syntax"],))
    _check(_N_C4, got["counts"] == (1, 1, 0), "counts=%r" % (got["counts"],))


def _materialize_head(tmp):
    """物化 HEAD 版 check_unreachable.py（红基线取用；git show 原始 blob 字节）。"""
    r = subprocess.run(["git", "show", "HEAD:scripts/check_unreachable.py"],
                       cwd=REPO, capture_output=True)
    if r.returncode != 0 or not (r.stdout or b"").strip():
        return None, "git show 失败 rc=%s %s" % (
            r.returncode, (r.stderr or b"").decode("utf-8", "replace").strip()[:200])
    p = os.path.join(tmp, "check_unreachable_head.py")
    with open(p, "wb") as fh:
        fh.write(r.stdout)
    return p, ""


def _head_leg(tmp):
    """D 组（默认模式内联）：HEAD 版跑 A 组，应恰按 A2–A5 点名转红；已修则 SKIP。"""
    keep = list(_RESULTS)
    del _RESULTS[:]
    head, why = _materialize_head(tmp)
    if head is None:
        _check("D 红基线自证：HEAD 版物化", False, why)
    else:
        _case_decode(head, os.path.join(tmp, "head_run"))
        reds = {n for n, ok, _d in _RESULTS if not ok}
        del _RESULTS[:]          # 明细只用于分类；D 腿只留一条结论
        if not reds:
            _skip("D 红基线自证",
                  "HEAD 版已呈修复形态——红基线只在本改动提交前可复现")
        elif reds == set(_HEAD_EXPECT_RED):
            _check("D 红基线自证：HEAD 版恰按 4 条点名转红（崩溃形态可复现）", True)
        else:
            _check("D 红基线自证：HEAD 版转红集合意外（多红 %r / 少红 %r）"
                   % (sorted(reds - set(_HEAD_EXPECT_RED)),
                      sorted(set(_HEAD_EXPECT_RED) - reds)), False)
    _RESULTS[:] = keep + _RESULTS


def _baseline_mode(impl, tmp):
    """`--impl head` 显式模式：以 HEAD 版跑 A/B/C，红基线必须按点转红。"""
    print("!! 红基线取证：以 HEAD 版跑 A/B/C 断言组——修前缺陷形态必须按点转红\n")
    _case_decode(impl, tmp)
    _case_control(impl, tmp)
    _case_not_weakened(impl, tmp)
    reds = {n for n, ok, _d in _RESULTS if not ok}
    for name, ok, detail in _RESULTS:
        print("  %s %s%s" % ("[RED ]" if not ok else "[green]", name,
                             ("  —— " + detail) if (not ok and detail) else ""))
    print("\n  （注：A1「退出码 = 1」在崩溃形态同样成立——未捕获异常退出码亦为 1；"
          "这正是本缺陷的诡诈处，区分面在 [SYNTAX]/汇总/继续扫描三段）")
    exp = set(_HEAD_EXPECT_RED)
    if not reds:
        print("\nHEAD 版 A/B/C 全绿——HEAD 已含修复，红基线只在本改动提交前可复现（SKIP）")
        return 0
    if reds == exp:
        print("\n红基线成立：HEAD 版恰按 4 条点名转红（崩溃形态可复现）")
        return 0
    print("\n红基线不成立：转红集合与预期不符（多红 %r / 少红 %r）"
          % (sorted(reds - exp), sorted(exp - reds)))
    return 1


def _mutate_mode(tmp):
    """定点变异自证：把修复点改回缺陷形态，断言组必须按预期点名转红。"""
    print("!! 定点变异自证：逐条把修复点改回缺陷形态，断言组必须按预期点名转红\n")
    src = open(DEFAULT_IMPL, encoding="utf-8").read()
    bad = 0
    for i, (name, old, new, expect_red) in enumerate(_MUTATIONS, 1):
        if old not in src:
            print("  [FAIL] ANCHOR-MISS：%s（锚点不在工作树实现里）" % name)
            bad += 1
            continue
        path = os.path.join(tmp, "mut_%d.py" % i)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(src.replace(old, new, 1))
        del _RESULTS[:]
        _case_decode(path, tmp)
        _case_control(path, tmp)
        _case_not_weakened(path, tmp)
        reds = {n for n, ok, _d in _RESULTS if not ok}
        exp = set(expect_red)
        if reds == exp:
            print("  [PASS] %s：转红 %d 条恰为预期（%s）"
                  % (name, len(reds), "；".join(sorted(reds))))
        else:
            bad += 1
            print("  [FAIL] %s：转红集合与预期不符（多红 %r / 少红 %r）"
                  % (name, sorted(reds - exp), sorted(exp - reds)))
    print("\n定点变异 %d/%d 恰合" % (len(_MUTATIONS) - bad, len(_MUTATIONS)))
    return 0 if not bad else 1


def _report():
    failed = 0
    for name, ok, detail in _RESULTS:
        line = "  %s %s" % ("[PASS]" if ok else "[FAIL]", name)
        if not ok and detail:
            line += "  —— " + detail
        print(line)
        if not ok:
            failed += 1
    for name, why in _SKIPPED:
        print("  [SKIP] %s（%s）" % (name, why))
    print("\n%d passed, %d failed, %d skipped"
          % (len(_RESULTS) - failed, failed, len(_SKIPPED)))
    return 1 if failed else 0


def _live_mode(impl, tmp):
    print("[1] A 组：坏字节夹具（scripts/bad.py 非法 UTF-8 + scripts/tail.py 含 1 处 unreachable）")
    _case_decode(impl, tmp)
    print("[2] B 组：对照夹具（仅 scripts/clean.py 干净文件）")
    _case_control(impl, tmp)
    print("[3] C 组：判据未放宽（仅含 unreachable 的好文件）")
    _case_not_weakened(impl, tmp)
    print("[4] D 组：红基线自证（HEAD 版跑坏字节夹具）")
    _head_leg(tmp)
    return _report()


def main(argv=None):
    ap = argparse.ArgumentParser(description="check_unreachable 解码失败收口守卫（N261）")
    ap.add_argument("--impl", default=None,
                    help="被测实现：缺省=工作树；head=HEAD 版（红基线取证）；或 .py 路径")
    ap.add_argument("--mutate", action="store_true", help="定点变异自证")
    ap.add_argument("--list", action="store_true", help="只列变异表")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.list:
        for name, _o, _n, exp in _MUTATIONS:
            print("  %-46s expect_red=%d" % (name, len(exp)))
        return 0

    tmp = tempfile.mkdtemp(prefix="unreach_decode_guard_")
    try:
        if args.mutate:
            return _mutate_mode(tmp)
        if args.impl == "head":
            head, why = _materialize_head(tmp)
            if head is None:
                print("取不到 HEAD 版：%s" % why)
                return 1
            return _baseline_mode(head, tmp)
        impl = os.path.abspath(args.impl) if args.impl else DEFAULT_IMPL
        if not os.path.isfile(impl):
            print("--impl 指向的文件不存在：%s" % impl)
            return 1
        return _live_mode(impl, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
