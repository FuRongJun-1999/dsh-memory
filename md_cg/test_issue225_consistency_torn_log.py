# -*- coding: utf-8 -*-
"""留痕台账半截行守卫（issue #225）。

【守什么】
#225 报：`_consistency.jsonl` 只要被写坏一次（最后一条留痕**截在多字节字符中间**、
没有结尾换行），此后 `cg(op=remember)` 与 `cg(op=info)` **永久报错**——
新记忆静默全丢、重启不恢复，而 heal 报 ok。

同一探针在修复前后的读数（`.dsh-tmp/c225probe.py` 语义的 15 条判据）：
  改前：通过 7 / 失败 8（rc=1）
    FAIL S1 check() 不抛  UnicodeDecodeError: 'utf-8' codec can't decode bytes
                          in position 0-1: unexpected end of data
    FAIL S3 history 好行全在  UnicodeDecodeError: ...
    FAIL S4/S5 summary  UnicodeDecodeError: ...
    FAIL S6-S8 追加  UnicodeDecodeError: 'utf-8' codec can't decode bytes
                     in position 226-227: invalid continuation byte
  改后：通过 15 / 失败 0（rc=0）

病灶（三处读取器 ＋ 一处写入端，都在 `md_cg/consistency.py`）：
  · `_last_strength` / `history` / `summary` 都用**严格** utf-8 解码。
    `UnicodeDecodeError` 是 `ValueError` 子类，但它在 `for line in f` 处抛、
    内层 `except (ValueError, TypeError)` 管不到，外层只接 `OSError`
    ⇒ 一行坏、三个读取器全废。非对象行（`null` / `[1]`）另在 `.get(...)` 抛
    `AttributeError`，连 `(ValueError, TypeError)` 都不接。
  · `check()` **无条件**取上一条强度（`emotional_bias(strength, _last_strength(cg))`），
    它就在**写热路径**上；`summary()` 是 `cg(op=info)` 的健康面。
  · 写入端 `log()` 没有防粘连：残行之后的新记录会与残行拼成一行，
    两条一起读不出来——**丢的是新记录**。

修法（只改 `md_cg/consistency.py`，接口与返回值向后兼容）：
  ① 新增单点 `_records(p, stats=None)`：`errors="replace"` ＋ 坏行/非对象行跳过，
     只产出 dict 行（容错口径与 `fsutil.read_jsonl` 一致，差别只在多一个计数）；
  ② `_last_strength` / `history` / `summary` 三处改走它；`summary()` 另返回
     `unparsable`（读不出来的行数），诊断面不再假性健康；
  ③ `log()` 追加前 `ends_mid_line` 补换行——读取端容错只能让台账**可读**，
     不补换行丢的是**新**记录。

判据：
  S1  半截台账下三个读取器都不抛；`_last_strength` 取到最后一条可解析记录的强度。
  S2  ★ 写热路径：`check()` 在半截台账上返回判决（改前 UnicodeDecodeError）。
  S3  坏行不静默：`summary()` 的 `unparsable` = 坏行数（含 `null` / `[1]` 非对象行），
      `records` 只计可解析对象行。
  S4  ★ 写入端防粘连：残行之后 `log()` 的新记录自成一行、`history()` 读得到。
  S5  口径不变：干净台账 `records`/`by_verdict`/`by_bias` 与旧口径逐位相同、
      `unparsable`=0、写入字节格式逐字不变；缺文件时三读取器返回值不变。
  S6  单点：`consistency.py` 里不带 `errors=` 的严格读 0 处（读只走 `_records`）。
  S7  连续追加：残行后连追 3 条全部可读，`unparsable` 仍为 1（补换行不产生多余空行）。

运行：python -X utf8 -m md_cg.test_issue225_consistency_torn_log
      python -X utf8 -m md_cg.test_issue225_consistency_torn_log --mutate
"""
from __future__ import annotations

import ast
import io
import json
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="i225g_")
# ★ 目录名不可用 "aux"——AUX 是 Windows 保留设备名（#245 实测踩到）。
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxstore")
os.makedirs(os.environ["MDCG_AUX_ROOT"], exist_ok=True)

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import consistency as C          # noqa: E402

_OK = 0
_BAD = []
_N = [0]


def _check(name, cond, detail=""):
    global _OK
    if cond:
        _OK += 1
        print("  ok   %s" % name)
    else:
        _BAD.append(name)
        print("  FAIL %s  %s" % (name, detail))


def _root():
    _N[0] += 1
    r = os.path.join(_TMP, "r%d" % _N[0])
    os.makedirs(r, exist_ok=True)
    return r


def _logpath(root):
    return os.path.join(root, C.LOG_FILE)


def _raw(root):
    with io.open(_logpath(root), "rb") as f:
        return f.read()


def _src(rel):
    with io.open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


class _Stub(object):
    """`consistency.check()` 只碰 cg 的两个面：`root` 与 `index["nodes"]`。"""

    def __init__(self, root):
        self.root = root
        self.index = {}


_GOOD1 = {"verdict": "CLEAR", "conflict_strength": 0.1,
          "emotional": {"bias": "none"}}
_GOOD2 = {"verdict": "CONDITION_CLASH", "conflict_strength": 0.7,
          "emotional": {"bias": "avoid"}}
_TORN = '{"verdict": "CONFLICT", "detail": "重启不恢复（断电）'


def _seed_torn(root):
    """两条完整留痕 ＋ 一条**截在多字节字符中间**且无结尾换行的残行。"""
    with io.open(_logpath(root), "wb") as f:
        f.write((json.dumps(_GOOD1, ensure_ascii=False) + "\n").encode("utf-8"))
        f.write((json.dumps(_GOOD2, ensure_ascii=False) + "\n").encode("utf-8"))
        f.write(_TORN.encode("utf-8")[:-1])          # 末字节是多字节字符的前缀
    return _GOOD1, _GOOD2


def _seed_clean(root):
    """两条完整留痕，**没有**坏行——供只测坏行口径的判据用（与 S1 的半截形态隔离）。"""
    with io.open(_logpath(root), "wb") as f:
        f.write((json.dumps(_GOOD1, ensure_ascii=False) + "\n").encode("utf-8"))
        f.write((json.dumps(_GOOD2, ensure_ascii=False) + "\n").encode("utf-8"))
    return _GOOD1, _GOOD2


def _try(name, fn, ok):
    """跑 fn() 并把返回值喂给 ok()：抛异常 ⇒ 该判据红（附异常名与原文）。"""
    try:
        v = fn()
    except Exception as exc:                         # noqa: BLE001
        _check(name, False, "%s: %s" % (type(exc).__name__, exc))
        return None
    _check(name, ok(v), repr(v)[:160])
    return v


def s1():
    print("== S1 半截台账下三个读取器都不抛 ==")
    root = _root()
    _seed_torn(root)
    cg = _Stub(root)
    _try("S1a _last_strength 不抛且取最后一条可解析记录",
         lambda: C._last_strength(cg), lambda v: v == 0.7)
    _try("S1b history 好行全在（倒序）",
         lambda: [r.get("verdict") for r in C.history(cg, 10)],
         lambda v: v == ["CONDITION_CLASH", "CLEAR"])
    _try("S1c summary 不抛且 records=2",
         lambda: C.summary(cg), lambda v: v.get("records") == 2)


def s2():
    print("== S2 写热路径：check() 在半截台账上仍返回判决 ==")
    root = _root()
    _seed_torn(root)
    cg = _Stub(root)
    rec = _try("S2a check() 不抛",
               lambda: C.check(cg, "新增一条记忆正文", log_write=False),
               lambda v: True)
    if rec is None:
        return
    _check("S2b 返回判决字段", rec.get("verdict") in C.VERDICTS,
           repr(rec.get("verdict")))


def s3():
    print("== S3 坏行不静默：unparsable 计数 ==")
    root = _root()
    _seed_clean(root)                                # 干净台账：与 S1 的半截形态隔离
    with io.open(_logpath(root), "a", encoding="utf-8") as f:
        # 前置换行让两行**自成行**（残行与追加行粘连是 S4 的判据），本组只看坏行口径：
        # `null` 解析成 None、`[1, 2]` 解析成 list，旧版在 .get 处抛 AttributeError，
        # 连 (ValueError, TypeError) 都不接。
        f.write("\nnull\n[1, 2]\n")
    cg = _Stub(root)
    s = _try("S3a summary 不抛", lambda: C.summary(cg), lambda v: True)
    if s is None:
        return
    _check("S3b records 只计可解析对象行 = 2",
           s.get("records") == 2, repr(s.get("records")))
    _check("S3c unparsable = 2（null 与 [1, 2] 两个非对象行）",
           s.get("unparsable") == 2, repr(s.get("unparsable")))
    _try("S3d history 不含非对象行",
         lambda: all(isinstance(r, dict) for r in C.history(cg, 10)), lambda v: v)
    _try("S3e _last_strength 不受非对象行影响",
         lambda: C._last_strength(cg), lambda v: v == 0.7)


def s4():
    print("== S4 写入端防粘连：残行之后的新记录自成一行 ==")
    root = _root()
    _seed_torn(root)
    cg = _Stub(root)
    n0 = _raw(root).count(b"\n")
    _check("S4a 起始：残行无结尾换行", not _raw(root).endswith(b"\n"),
           repr(_raw(root)[-8:]))
    C.log(cg, {"verdict": "CONFLICT", "conflict_strength": 0.9,
               "note": "残行之后的新记录"})
    raw = _raw(root)
    _check("S4b 追加后以换行收尾", raw.endswith(b"\n"))
    _check("S4c 补了 1 个换行（%d → %d）" % (n0, raw.count(b"\n")),
           raw.count(b"\n") == n0 + 2, "%d" % raw.count(b"\n"))
    _try("S4d 新记录读得到（未被残行吞掉）",
         lambda: [r.get("note") for r in C.history(cg, 10) if r.get("note")],
         lambda v: v == ["残行之后的新记录"])
    _try("S4e 好行仍全在",
         lambda: [r.get("verdict") for r in C.history(cg, 10)],
         lambda v: v == ["CONFLICT", "CONDITION_CLASH", "CLEAR"])


def s5():
    print("== S5 口径不变：干净台账与缺文件 ==")
    root = _root()
    cg = _Stub(root)
    recs = ({"verdict": "CLEAR"},
            {"verdict": "CLEAR", "emotional": {"bias": "none"}},
            {"verdict": "CONDITION_CLASH", "emotional": {"bias": "avoid"}})
    for r in recs:
        C.log(cg, r)
    with io.open(_logpath(root), encoding="utf-8") as f:
        raw = f.read().replace("\r\n", "\n")       # 读侧按通用换行归一，与平台无关
    want = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs)
    _check("S5a 干净路径写入格式逐字不变", raw == want, repr(raw)[:160])
    s = _try("S5b summary 不抛", lambda: C.summary(cg), lambda v: True)
    if s is not None:
        _check("S5c records=3", s.get("records") == 3, repr(s.get("records")))
        _check("S5d by_verdict 口径不变",
               s.get("by_verdict") == {"CLEAR": 2, "CONDITION_CLASH": 1},
               repr(s.get("by_verdict")))
        _check("S5e by_bias 口径不变（只计真值）",
               s.get("by_bias") == {"none": 1, "avoid": 1},
               repr(s.get("by_bias")))
        _check("S5f 干净台账 unparsable=0",
               s.get("unparsable") == 0, repr(s.get("unparsable")))
        _check("S5g max_scan/max_depth/min_gain 仍取模块常量",
               (s.get("max_scan"), s.get("max_depth"), s.get("min_gain")) ==
               (C.MAX_SCAN, C.MAX_DEPTH, C.MIN_GAIN), repr(s))
    _try("S5h history 倒序＋limit 口径不变",
         lambda: [r.get("verdict") for r in C.history(cg, 2)],
         lambda v: v == ["CONDITION_CLASH", "CLEAR"])
    empty = _Stub(_root())
    _try("S5i 缺文件 _last_strength=None",
         lambda: C._last_strength(empty), lambda v: v is None)
    _try("S5j 缺文件 history=[]", lambda: C.history(empty), lambda v: v == [])
    _try("S5k 缺文件 summary records=0 / unparsable=0",
         lambda: C.summary(empty),
         lambda v: v.get("records") == 0 and v.get("unparsable") == 0)


def _opens(src):
    """AST 口径：返回 (读模式的 open 行号, 其中不带 errors= 的行号)。"""
    reads, strict = [], []
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "open"):
            continue
        mode = None
        if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
            mode = node.args[1].value
        for kw in node.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                mode = kw.value.value
        if mode == "r":
            reads.append(node.lineno)
            if not any(kw.arg == "errors" for kw in node.keywords):
                strict.append(node.lineno)
    return reads, strict


def s6():
    print("== S6 单点：留痕读只走 _records ==")
    src = _src("md_cg/consistency.py")
    reads, strict = _opens(src)
    _check("S6a 无严格读（不带 errors= 的读 0 处）", strict == [],
           "行号=%s" % strict)
    _check("S6b 读模式的 open 只有 _records 一处", len(reads) == 1,
           "读模式=%s" % reads)
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_records"]
    _check("S6c 三个读取器都走 _records（调用点 ≥3）", len(calls) >= 3,
           "调用点=%d" % len(calls))


def s7():
    print("== S7 连续追加：残行后连追 3 条 ==")
    root = _root()
    _seed_torn(root)
    cg = _Stub(root)
    for i in range(3):
        C.log(cg, {"verdict": "CLEAR", "note": "n%d" % i})
    _try("S7a 三条新记录全部可读且倒序",
         lambda: [r.get("note") for r in C.history(cg, 10) if r.get("note")],
         lambda v: v == ["n2", "n1", "n0"])
    s = _try("S7b summary 不抛", lambda: C.summary(cg), lambda v: True)
    if s is not None:
        _check("S7c records=5（2 好 ＋ 3 新）",
               s.get("records") == 5, repr(s.get("records")))
        _check("S7d unparsable 仍为 1（补换行不产生多余空行）",
               s.get("unparsable") == 1, repr(s.get("unparsable")))
    raw = _raw(root)
    _check("S7e 换行数 = 2 好 ＋ 1 补 ＋ 3 条 = 6",
           raw.count(b"\n") == 6, "%d" % raw.count(b"\n"))


_GROUPS = (("S1", s1), ("S2", s2), ("S3", s3), ("S4", s4),
           ("S5", s5), ("S6", s6), ("S7", s7))


def _run_groups():
    global _OK
    _OK = 0
    _BAD.clear()
    for gid, g in _GROUPS:
        try:
            g()
        except Exception as exc:                     # noqa: BLE001
            _check("%s 组内异常：%s" % (gid, exc), False)
            import traceback
            print(traceback.format_exc()[-600:])
    return len(_BAD)


def main():
    n = _run_groups()
    print()
    print("留痕半截行守卫：%d 通过，%d 失败" % (_OK, n))
    return 1 if n else 0


_MUTATIONS = (
    ("V1 _records 回到严格解码（本件病象）",
     'with open(p, "r", encoding="utf-8", errors="replace") as f:',
     'with open(p, "r", encoding="utf-8", errors="strict") as f:', "S1"),
    ("V2 log() 不补换行（残行吞掉新记录）",
     '        if ends_mid_line(p):\n            line = "\\n" + line\n',
     "", "S4"),
    ("V3 只跳 None、非对象行照收（.get 抛 AttributeError）",
     "            if not isinstance(r, dict):",
     "            if r is None:", "S3"),
    ("V4 history 回到严格读（部分回退）",
     "        out = list(_records(p))\n",
     '        out = []\n'
     '        with open(p, "r", encoding="utf-8") as f:\n'
     '            for line in f:\n'
     '                line = line.strip()\n'
     '                if not line:\n'
     '                    continue\n'
     '                try:\n'
     '                    out.append(json.loads(line))\n'
     '                except (ValueError, TypeError):\n'
     '                    pass\n', "S1"),
    ("V5 by_bias 不判真值（口径退化）",
     '            if b:\n                by_bias[b] = by_bias.get(b, 0) + 1\n',
     "            by_bias[b] = by_bias.get(b, 0) + 1\n", "S5"),
)


def _reload():
    import importlib
    from md_cg import consistency as _c
    importlib.reload(_c)
    globals()["C"] = _c


def _mutate():
    bad = []
    p = os.path.join(_REPO, "md_cg", "consistency.py")
    with io.open(p, encoding="utf-8", newline="") as f:
        pristine = f.read()
    if "def _records(" not in pristine:
        print("  SOURCE-ALREADY-MUTATED：consistency.py 缺 _records")
        return 1
    for name, anchor, repl, want in _MUTATIONS:
        with io.open(p, encoding="utf-8", newline="") as f:
            orig = f.read()
        NL = "\r\n" if "\r\n" in orig else "\n"
        a_ = anchor.replace("\n", NL)
        r_ = repl.replace("\n", NL)
        try:
            if a_ not in orig:
                print("  ANCHOR-MISS %s" % name)
                bad.append(name)
                continue
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(orig.replace(a_, r_, 1))
            _reload()
            _run_groups()
            reds = list(_BAD)
            hit = any(x.startswith(want) for x in reds)
            print("  %-4s %-44s 红项=%-3d 命中%s=%s"
                  % ("OK" if hit else "BAD", name, len(reds), want,
                     "是" if hit else "否"))
            print("       红项：%s" % "、".join(reds))
            if not hit:
                bad.append(name)
        finally:
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(pristine)
            with io.open(p, encoding="utf-8", newline="") as f:
                if f.read() != pristine:
                    print("  RESTORE-FAILED %s" % name)
                    bad.append(name + "(恢复失败)")
            _reload()
    if bad:
        print()
        print("定点变异自证：FAIL -- %s" % "、".join(bad))
        return 1
    print()
    print("定点变异自证：PASS（每处判据都被打红）")
    return 0


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(_mutate())
    sys.exit(main())
