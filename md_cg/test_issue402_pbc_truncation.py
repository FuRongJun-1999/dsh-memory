# -*- coding: utf-8 -*-
# 功能名：.pbc 反序列化截断判据守卫（issue #402）
# 生效条件：python -X utf8 -m md_cg.test_issue402_pbc_truncation [--mutate [--list] | --pristine]
#   被测面＝compiler/pbc.py 的 deserialize / load_pbc / save_pbc / run_pbc（.pbc 是
#   「[op: len2B+utf8][arg_tag:1B][arg_data...]」的裸字节流，**无文件级头/尾/指令计数**）。
# 子功能：A 组＝往返与指令边界；B 组＝全截断点扫描（每点要么抛结构化错误，要么返回值逐位
#   等于完整件的合法前缀）；C 组＝load_pbc / run_pbc 的错误面；D 组＝save_pbc 原子写；
#   E 组＝负例与边界（空件/未知标签/坏 utf-8/超长长度前缀）；F 组＝相关回归（编译→执行全链）；
#   G 组＝源码面锚点自证。
# 执行：--mutate 逐条把修复锚点改回**改动前形态**（源码文本变异，不以 git HEAD 为基线源、
#   不动工作树），每条变异必须让本套件转红；--pristine 一次性改回全部锚点并断言套件整体
#   失败（＝认证一「修复前必红」的可复跑证据）。
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异须打红其预期前缀的断言；
#   --pristine（认证一）把修复整体还原成改动前形态后跑本套件——**退出码 1 ＝ 按预期失败**
#   （与真实修复前树的退出码一致，其 FAIL 行即复现缺陷的原始输出）；若竟然全绿则退出码 3。
# 不适用条件：不覆盖 .pbc 未随 npm 包发布带来的外部影响面；不覆盖 compiler/cli/__init__.py
#   的打印口径（不在本卡 write_scope）；不覆盖 save_pbc 写中断的真截断件（只以「写前失败
#   不破坏旧件」等价覆盖）。
"""#402 守卫：截断的 .pbc 不得被静默读成「合法但更短」的指令表。

病象（#402，基线 5cd2b43f）：deserialize 无长度判据——:69/:87/:103 的切片在剩余字节不足时
**静默返回更短的 op 名/字符串**，于是截断件 rc=0 执行出错误结果（实测 cut=26 的 run 打印
「信任=0.0 条件空间=['新']」，而完整件是「信任=0.3 条件空间=['新信任路径']」）；其余截断点
抛裸 IndexError / struct.error / UnicodeDecodeError。load_pbc / run_pbc 无 try ⇒ 畸形件
把裸异常抛给 CLI。

本件钉住的不变量（可判据、不靠计数巧合）：
  I1 任一截断点的 deserialize 结果，要么抛结构化错误（带 what/need/offset/remain），
     要么**逐位等于完整件的某个前缀**（＝该字节序列本身是一条合法的更短 .pbc，格式上
     不可区分——cut=0/15/38/51/57 正是指令边界，故**不是**缺陷）；
  I2 静默返回的点集合恰好等于「指令边界 ∪ {0}」——多一个即回归，少一个即过度拒绝；
  I3 任何非结构化裸异常（IndexError/struct.error/UnicodeDecodeError）出现即红；
  I4 load_pbc 把畸形件转成 PbcFormatError（点名 path 与字节数），run_pbc 随之不执行半截件。
"""
from __future__ import annotations

import io
import os
import re
import shutil
import struct
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

FAILS = []
PASSES = []
SKIPS = []


def _check(name, cond, detail=""):
    line = ("  PASS " if cond else "  FAIL ") + name
    if not cond and detail:
        line += "  " + str(detail)[:260]
    print(line)
    (PASSES if cond else FAILS).append(name)
    return bool(cond)


def _skip(name, why):
    print("  SKIP " + name + "  " + why)
    SKIPS.append(name)


_TMP = tempfile.mkdtemp(prefix="iss402_")

#: 覆盖全部 arg_tag（0/1/2/3/4/5/6）的两份样本字节码。
_CODE_FULL = [("ENTER_SHUYUE", None), ("DAO", "新信任路径"), ("DE", 0.3),
              ("ZHI", None), ("RETURN_STEP", None)]
_CODE_TAGS = [("CALL", (3, ["a", "bb"])), ("FLAG", True), ("N", -5),
              ("PAIR", (1.5, 2)), ("EMPTY", "")]

_SAMPLE_SRC = """问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：
1。道 新信任路径；
2。德 0.3；
3。若 信任值 大于 0.2，则 德 0.5；
4。止。
"""


def _pbc():
    """当前生效的 pbc 模块：变异态下取**换进包属性**的那一份。

    必须同时改 compiler.pbc 属性——from compiler import pbc 走的是包的属性查找，
    只换 sys.modules 拿到的仍是原模块（M1/M2 会因此假绿）。
    """
    import compiler
    return compiler.pbc


#: 变异态下的**生效源码文本**（rel → text）：静态组必须读它，否则读盘读到的是未变异
#: 的真源码，变异态下静态断言会假绿（本守卫的 G 组就是这类断言）。
_SRC = {}


def _rel_text(rel):
    if rel in _SRC:
        return _SRC[rel]
    with io.open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


def _boundaries(pbc, code):
    """独立推导指令边界：用**可信编码器** serialize 逐条量长（不借道 deserialize）。"""
    bs, acc = [], 0
    for ins in code:
        acc += len(pbc.serialize([ins]))
        bs.append(acc)
    return bs


def _structured(exc):
    """结构化截断错误判据：ValueError 子类且带 what/need/offset/remain 四字段。"""
    return (isinstance(exc, ValueError) and hasattr(exc, "what")
            and hasattr(exc, "need") and hasattr(exc, "offset")
            and hasattr(exc, "remain"))


def _segments(code, pbc):
    """按格式声明**独立重算**每个段的 (起始偏移, 长度, 段名)。

    不借道 deserialize（否则判据与被测实现同源，变异态下一起失效）。格式真源＝本模块
    docstring 的「[op: len2B+utf8][arg_tag:1B][arg_data...]」＋各 tag 的载荷布局。
    """
    segs, off = [], 0
    for op, arg in code:
        b = pbc._op_name(op).encode("utf-8")
        segs.append((off, 2, "op 名长度前缀")); off += 2
        segs.append((off, len(b), "op 名")); off += len(b)
        segs.append((off, 1, "参数标签")); off += 1
        if arg is None:
            pass
        elif isinstance(arg, bool):
            segs.append((off, 1, "bool 载荷")); off += 1
        elif isinstance(arg, int):
            segs.append((off, 8, "int 载荷")); off += 8
        elif isinstance(arg, float):
            segs.append((off, 8, "float 载荷")); off += 8
        elif isinstance(arg, str):
            s = arg.encode("utf-8")
            segs.append((off, 2, "str 长度前缀")); off += 2
            segs.append((off, len(s), "str 载荷")); off += len(s)
        elif isinstance(arg, tuple) and len(arg) == 2 and isinstance(arg[1], (list, tuple)):
            segs.append((off, 8, "tag6 入口地址")); off += 8
            segs.append((off, 2, "tag6 参数个数")); off += 2
            for x in arg[1]:
                sb = x.encode("utf-8")
                segs.append((off, 2, "tag6 参数名长度前缀")); off += 2
                segs.append((off, len(sb), "tag6 参数名")); off += len(sb)
        elif isinstance(arg, tuple):
            segs.append((off, 16, "tuple 载荷")); off += 16
    return segs


# ---------------------------------------------------------------- A 组
def g_a_roundtrip():
    pbc = _pbc()
    for tag, code in (("A1 全 tag 样本", _CODE_TAGS), ("A2 中文样本", _CODE_FULL)):
        blob = pbc.serialize(code)
        try:
            back = pbc.deserialize(blob)
            err = None
        except Exception as exc:                       # noqa: BLE001
            back, err = None, "%s: %s" % (type(exc).__name__, exc)
        _check("%s 序列化→反序列化逐位相等" % tag, back == code, (back, err))
    bs = _boundaries(pbc, _CODE_FULL)
    _check("A3 指令边界独立推导（serialize 逐条量长）＝%s" % bs,
           bs == [15, 38, 51, 57, 71] and bs[-1] == len(pbc.serialize(_CODE_FULL)), bs)


# ---------------------------------------------------------------- B 组
def g_b_truncation_scan():
    """全截断点扫描：I1/I2/I3 三个不变量。"""
    pbc = _pbc()
    for tag, code in (("B1 全 tag 样本", _CODE_TAGS), ("B2 中文样本", _CODE_FULL)):
        blob = pbc.serialize(code)
        bounds = set(_boundaries(pbc, code))
        full = pbc.deserialize(blob)
        silent, bare, nonprefix, badfields = [], [], [], []
        for cut in range(len(blob) + 1):
            piece = blob[:cut]
            try:
                got = pbc.deserialize(piece)
            except Exception as exc:                   # noqa: BLE001
                if not _structured(exc):
                    bare.append((cut, type(exc).__name__, str(exc)[:60]))
                    continue
                ok = (exc.offset >= 0 and exc.need >= 0 and exc.remain >= 0
                      and exc.offset + exc.need > len(piece)
                      and exc.remain == max(0, len(piece) - exc.offset)
                      and "pbc 截断：" in str(exc))
                if not ok:
                    badfields.append((cut, exc.what, exc.need, exc.offset,
                                      exc.remain, str(exc)[:80]))
                continue
            if cut == len(blob):
                continue
            if got == full:
                continue
            if got == full[:len(got)]:
                silent.append(cut)
            else:
                nonprefix.append((cut, got))
        _check("%s I3 无裸异常（IndexError/struct.error/UnicodeDecodeError）" % tag,
               not bare, bare[:4])
        _check("%s I1 静默点全部是完整件的合法前缀（无「更短字符串」）" % tag,
               not nonprefix, nonprefix[:3])
        # 全长（cut=len(blob)）本身不是截断点，故期望集合＝(指令边界 − 全长) ∪ {0}：
        # 静默点**多一个**即回归（静默错值），**少一个**即过度拒绝（把合法短件判成坏件）。
        _want = (bounds - {len(blob)}) | {0}
        _check("%s I2 静默点集合恰＝(指令边界−全长)∪{0}" % tag,
               set(silent) == _want,
               "多=%s 少=%s" % (sorted(set(silent) - _want), sorted(_want - set(silent))))
        _check("%s 结构化错误的四字段自洽" % tag, not badfields, badfields[:3])
    # 点名病象：cut=26 此前静默给出 ('DAO','新')（合法但更短的字符串）
    blob = pbc.serialize(_CODE_FULL)
    try:
        got26 = pbc.deserialize(blob[:26])
        exc26 = None
    except Exception as exc:                           # noqa: BLE001
        got26, exc26 = None, exc
    _check("B3 病象点 cut=26 不再静默给出更短字符串",
           exc26 is not None and _structured(exc26),
           (got26, None if exc26 is None else "%s: %s" % (type(exc26).__name__, exc26)))
    try:
        got29 = pbc.deserialize(blob[:29])
        exc29 = None
    except Exception as exc:                           # noqa: BLE001
        got29, exc29 = None, exc
    _check("B4 病象点 cut=29 同上", exc29 is not None and _structured(exc29), got29)
    # B5 每个读取点都必须有判据、且错误**点名正确的段**：对每个段取一个落在段内的
    # 截断点（长度≥2 取「段首+1」，长度=1 取段首），断言抛出的错误段名与该段一致。
    # 独立重算段布局 ⇒ 任一 _need 调用被摘掉，对应段必然点名错误或不再报错（转红）。
    for tag, code in (("B5 全 tag 样本", _CODE_TAGS), ("B5b 中文样本", _CODE_FULL)):
        blob = pbc.serialize(code)
        segs = _segments(code, pbc)
        _check("%s 段布局独立重算覆盖全部字节（%d）" % (tag, len(blob)),
               segs and segs[-1][0] + segs[-1][1] == len(blob), (segs[-1] if segs else None,))
        bad5 = []
        for (s0, ln, what) in segs:
            if ln == 0:
                continue          # 零长段（如空字符串载荷）无字节可截，不适用
            cut = s0 + 1 if ln >= 2 else s0
            _err5 = None
            _got5 = None
            try:
                _got5 = pbc.deserialize(blob[:cut])
            except Exception as exc:                   # noqa: BLE001 —— 变异态不得崩栈
                _err5 = exc
            if _err5 is None:
                bad5.append((what, cut, "未报错，返回 %r" % (_got5,)))
            elif not _structured(_err5) or _err5.what != what:
                bad5.append((what, cut, "%s/%s" % (type(_err5).__name__,
                             getattr(_err5, "what", "-"))))
        _check("%s 每个读取点都点名正确的段（%d 段）" % (tag, len(segs)), not bad5, bad5[:4])



# ---------------------------------------------------------------- C 组
def g_c_error_surface():
    """load_pbc / run_pbc：畸形件必须给结构化错误面（点名文件），绝不返回半截结果。"""
    pbc = _pbc()
    blob = pbc.serialize(_CODE_FULL)
    bad = []
    for cut in range(len(blob)):
        p = os.path.join(_TMP, "c_%d.pbc" % cut)
        with open(p, "wb") as f:
            f.write(blob[:cut])
        try:
            pbc.load_pbc(p)
            continue                                   # 合法更短件（边界点）：放行是对的
        except ValueError as exc:
            if not isinstance(exc, getattr(pbc, "PbcFormatError", ())):
                bad.append((cut, "非 PbcFormatError：%s" % type(exc).__name__))
            elif exc.path != p or exc.bytes != cut or p not in str(exc):
                bad.append((cut, "字段/文案未点名文件", exc.path, exc.bytes))
        except Exception as exc:                       # noqa: BLE001
            bad.append((cut, "裸异常 %s: %s" % (type(exc).__name__, str(exc)[:50])))
    _check("C1 load_pbc 对每个畸形截断点抛 PbcFormatError 且点名 path/字节数", not bad, bad[:4])

    p = os.path.join(_TMP, "c_run.pbc")
    with open(p, "wb") as f:
        f.write(blob[:26])
    try:
        st = pbc.run_pbc(p)
        _check("C2 run_pbc 对截断件不返回执行结果（此前 rc=0 静默执行错结果）", False,
               "返回了 %r" % (st,))
    except ValueError as exc:
        _check("C2 run_pbc 对截断件不返回执行结果（此前 rc=0 静默执行错结果）",
               isinstance(exc, getattr(pbc, "PbcFormatError", ())),
               "%s: %s" % (type(exc).__name__, str(exc)[:90]))
    except Exception as exc:                           # noqa: BLE001
        _check("C2 run_pbc 对截断件不返回执行结果（此前 rc=0 静默执行错结果）", False,
               "裸异常 %s: %s" % (type(exc).__name__, str(exc)[:60]))


# ---------------------------------------------------------------- D 组
def g_d_atomic_save():
    """save_pbc：临时名 + 同目录 + os.replace；写前失败不得破坏既有完整件。"""
    pbc = _pbc()
    d = os.path.join(_TMP, "d1")
    p = os.path.join(d, "n.pbc")
    pbc.save_pbc(_CODE_FULL, p)
    before = io.open(p, "rb").read()
    _check("D1 首次落盘往返正确", pbc.load_pbc(p) == _CODE_FULL)
    try:
        pbc.save_pbc([("BAD", object())], p)
        raised = None
    except Exception as exc:                           # noqa: BLE001
        raised = type(exc).__name__
    _check("D2 不可序列化入参抛出（serialize 先于任何落盘动作）", raised is not None, raised)
    after = io.open(p, "rb").read()
    _check("D3 写前失败后旧件逐字节未变（非裸 open(wb) 截断）",
           after == before and pbc.load_pbc(p) == _CODE_FULL,
           "旧件 %d 字节 → %d 字节" % (len(before), len(after)))
    residue = [n for n in os.listdir(d) if ".tmp-" in n]
    _check("D4 无临时件残留", not residue, residue)
    p2 = os.path.join(_TMP, "d2", "deep", "n2.pbc")
    pbc.save_pbc(_CODE_TAGS, p2)
    _check("D5 目标目录不存在时自动建目录并落盘", pbc.load_pbc(p2) == _CODE_TAGS)


# ---------------------------------------------------------------- E 组
def g_e_negative_boundary():
    pbc = _pbc()
    _check("E1 空字节串 → 空指令表（格式声明：data 为空则返回空列表）",
           pbc.deserialize(b"") == [])
    blob = struct.pack("H", 1) + b"A" + b"\x09"   # 合法长度前缀 + 合法 op 名 + 未知 tag
    try:
        pbc.deserialize(blob)
        got = "未抛"
    except ValueError as exc:
        got = "%s: %s" % (type(exc).__name__, str(exc)[:60])
    except Exception as exc:                           # noqa: BLE001
        got = "裸 %s" % type(exc).__name__
    _check("E2 未知参数标签仍抛 ValueError（未被截断判据吞掉）",
           got.startswith("ValueError"), got)
    long_op = struct.pack("H", 60000) + b"x" * 4
    try:
        pbc.deserialize(long_op)
        got2 = None
    except Exception as exc:                           # noqa: BLE001
        got2 = exc
    _check("E3 长度前缀声称 60000 字节而实余 4 字节 → 结构化截断（点名「op 名」）",
           got2 is not None and _structured(got2) and got2.what == "op 名"
           and got2.need == 60000, got2)
    p = os.path.join(_TMP, "e_utf8.pbc")
    with open(p, "wb") as f:
        f.write(struct.pack("H", 1) + b"A" + b"\x04" + struct.pack("H", 2) + b"\xff\xfe")
    try:
        pbc.load_pbc(p)
        got3 = "未抛"
    except Exception as exc:                           # noqa: BLE001
        got3 = "%s/%s" % (type(exc).__name__, type(exc.cause).__name__
                          if hasattr(exc, "cause") else "-")
    _check("E4 非法 utf-8 载荷 → 结构化错误面（含 PbcFormatError 包装）",
           got3 == "PbcFormatError/UnicodeDecodeError", got3)


# ---------------------------------------------------------------- F 组
def g_f_regression():
    """相关回归：编译→落盘→VM 执行全链仍与既有读数一致（改错误面不得改成功路径）。"""
    pbc = _pbc()
    p = os.path.join(_TMP, "f_src.pbc")
    try:
        code, res = pbc.compile_to_pbc(_SAMPLE_SRC, p)
        err = None
    except Exception as exc:                           # noqa: BLE001
        code, res, err = None, None, "%s: %s" % (type(exc).__name__, exc)
    _check("F1 中文源码仍编译成功且落盘", err is None and res.get("ok") is True, err or res)
    if err is None:
        # compile_source 产出的 op 是枚举/整数，序列化经 _op_name 落成字符串 ⇒ 读回面是 str
        _check("F2 落盘件可读回（指令数=%d）" % len(code),
               pbc.load_pbc(p) == [(pbc._op_name(o), a) for o, a in code],
               pbc.load_pbc(p))
        try:
            st = pbc.run_pbc(p)
            e2 = None
        except Exception as exc:                       # noqa: BLE001
            st, e2 = None, "%s: %s" % (type(exc).__name__, exc)
        _check("F3 VM 执行读数与既有基线一致（trust=0.8 / halt=halt / 条件空间=新信任路径）",
               e2 is None and st.get("trust") == 0.8 and st.get("halt") == "halt"
               and [c.get("name") for c in (st.get("condition_space") or [])] == ["新信任路径"],
               e2 or st)
    # 既有入口 compiler/analyzer.py、compiler/debugger.py 依赖 load_pbc 的返回值形状
    from compiler import analyzer
    try:
        dump = analyzer.analyze_pbc(p)
        e3 = None
    except Exception as exc:                           # noqa: BLE001
        dump, e3 = None, "%s: %s" % (type(exc).__name__, exc)
    _check("F4 analyzer.analyze_pbc 仍可用（load_pbc 返回形状未变）", e3 is None, e3 or str(dump)[:80])


# ---------------------------------------------------------------- G 组
def g_g_source_anchors():
    """源码面自证：截断判据的调用点数量与闸函数在场（锚点漂移即在此报红）。"""
    src = _rel_text("compiler/pbc.py")
    calls = re.findall(r"^\s+_need\(data,", src, re.M)
    _check("G1 deserialize 内 _need 调用点＝13（每个读取点一处）", len(calls) == 13, len(calls))
    _check("G2 截断判据唯一实现在场（def _need）", "def _need(data, i, n, what):" in src)
    _check("G3 生效条件已声明「输入必须完整」（#402 的自述缺口已补）",
           "输入必须完整" in src)
    _check("G4 save_pbc 走临时名 + os.replace（原子替换）",
           "mkstemp" in src and "os.replace" in src and 'open(path, "wb")' not in src)
    _check("G5 load_pbc 有 PbcFormatError 包装", "raise PbcFormatError(path, len(data), exc)" in src)


_GROUPS = (g_a_roundtrip, g_b_truncation_scan, g_c_error_surface, g_d_atomic_save,
           g_e_negative_boundary, g_f_regression, g_g_source_anchors)


def _run_groups():
    PASSES.clear()
    FAILS.clear()
    SKIPS.clear()
    for g in _GROUPS:
        try:
            g()
        except Exception as exc:                       # noqa: BLE001
            _check("断言组 %s 抛异常" % g.__name__, False,
                   "%s: %s" % (type(exc).__name__, exc))
            import traceback
            print(traceback.format_exc()[-600:])
    return len(FAILS)


# ---------------------------------------------------------------- 变异
# 锚点 = (名字, rel, old, new, 预期红项数下限, 预期红项前缀)。
# 每条 new 都是**改动前形态**的原文复现（不加 git 依赖）。
_MUTATIONS = (
    ("M1 摘掉 op 名长度前缀的长度判据", "compiler/pbc.py",
     '        _need(data, i, 2, "op 名长度前缀")\n', "", 1, "B"),
    ("M2 摘掉 op 名的长度判据", "compiler/pbc.py",
     '        _need(data, i, n, "op 名")\n', "", 1, "B"),
    ("M3 摘掉 str 载荷的长度判据（静默更短串之源）", "compiler/pbc.py",
     '            _need(data, i, m, "str 载荷")\n', "", 1, "B"),
    ("M4 还原 load_pbc 的无 try 裸读", "compiler/pbc.py",
     "    try:\n        return deserialize(data)\n"
     "    except ValueError as exc:\n"
     "        raise PbcFormatError(path, len(data), exc) from exc",
     "    return deserialize(data)", 1, "C"),
    ("M5 还原 save_pbc 的非原子裸写", "compiler/pbc.py",
     "    blob = serialize(code)\n"
     '    d = os.path.dirname(os.path.abspath(path)) or "."\n'
     "    os.makedirs(d, exist_ok=True)\n"
     '    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".tmp-", dir=d)\n'
     "    try:\n"
     '        with os.fdopen(fd, "wb") as f:\n'
     "            f.write(blob)\n"
     "        _publish(tmp, path)\n"
     "        tmp = None\n"
     "    finally:\n"
     "        if tmp is not None and os.path.exists(tmp):\n"
     "            try:\n"
     "                os.remove(tmp)\n"
     "            except OSError:\n"
     "                pass\n"
     "    return path",
     '    with open(path, "wb") as f:\n'
     "        f.write(serialize(code))\n"
     "    return path", 1, "D"),
)


def _exec_module(name, rel, text):
    import types
    ns = {"__name__": name, "__package__": "compiler",
          "__file__": os.path.join(_REPO, rel)}
    exec(compile(text, rel, "exec"), ns)               # noqa: S102 —— 基线自证用
    m = types.ModuleType(name)
    m.__dict__.update(ns)
    return m


def _revert_all():
    """把所有修复锚点改回改动前形态（内存态），返回 (命中数, 未命中列表)。"""
    hit, miss = 0, []
    # ★必须**累积**：逐条从「上一条变异后的文本」继续，而不是每条都从磁盘原文重来
    # （否则循环结束时只有最后一条变异生效，前面几条被覆盖 ⇒ pristine 面假绿）。
    text = _rel_text("compiler/pbc.py")
    for name, rel, old, new, _e, _p in _MUTATIONS:
        if old not in text:
            miss.append(name)
            continue
        text = text.replace(old, new, 1)
        hit += 1
    if hit:
        _SRC[rel] = text
        _install(_exec_module("compiler.pbc", rel, text))
    return hit, miss


def _install(mod):
    """把变异模块同时装进 sys.modules 与 compiler 包属性（两处必须一致）。"""
    import compiler
    sys.modules["compiler.pbc"] = mod
    compiler.pbc = mod
    return mod


def _restore_real():
    import importlib
    import compiler
    sys.modules.pop("compiler.pbc", None)
    mod = importlib.import_module("compiler.pbc")
    compiler.pbc = mod
    return mod


def _mutate_mode(list_only=False):
    print("!! 定点变异自证：逐条把修复锚点改回改动前形态，套件必须转红\n")
    if list_only:
        for name, rel, _o, _n, exp, pre in _MUTATIONS:
            print("  %-44s expect_red>=%d 前缀[%s]  (%s)" % (name, exp, pre, rel))
        return 0
    anchor_miss, bad = [], []
    with _redirect() as buf:
        clean = _run_groups()
    print("  未变异基线：失败=%d（必须为 0）" % clean)
    if clean:
        bad.append("未变异基线即失败")
        for l in buf.getvalue().splitlines():
            if l.strip().startswith("FAIL "):
                print("        " + l.strip()[5:])
    for name, rel, old, new, expect, pre in _MUTATIONS:
        src = _rel_text(rel)
        if old not in src:
            print("  ANCHOR-MISS %s —— 锚点在 %s 源码里找不到（实现改了却没同步本表；"
                  "锚点漂移不得静默）" % (name, rel))
            anchor_miss.append(name)
            continue
        text = src.replace(old, new, 1)
        _SRC[rel] = text
        _restore_real()
        _install(_exec_module("compiler.pbc", rel, text))
        try:
            with _redirect() as buf:
                reds = _run_groups()
            detail = buf.getvalue()
        finally:
            _SRC.pop(rel, None)
            _restore_real()
        red_lines = [l.strip()[5:] for l in detail.splitlines()
                     if l.strip().startswith("FAIL ")]
        marked = [l for l in red_lines if l.startswith(pre)]
        mark = "OK  " if (reds >= expect and marked) else "MISMATCH"
        print("  %s %-44s 红项=%d 预期>=%d 命中前缀[%s]=%d"
              % (mark, name, reds, expect, pre, len(marked)))
        for l in red_lines[:5]:
            print("        " + l)
        if reds < expect or not marked:
            bad.append("%s（红=%d 预期>=%d 前缀命中=%d）" % (name, reds, expect, len(marked)))
    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s" % ("PASS（每处判据都被打红）" if not bad
                                  else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


class _redirect:
    def __enter__(self):
        self._buf = io.StringIO()
        self._old = sys.stdout
        sys.stdout = self._buf
        return self._buf

    def __exit__(self, *exc):
        sys.stdout = self._old
        return False


def _pristine_mode():
    """认证一：把修复整体还原成改动前形态后跑本套件，**必须失败**。"""
    print("!! 修复前形态（全部锚点还原，源码文本变异、不动 git）：套件必须 FAIL\n")
    hit, miss = _revert_all()
    print("  还原命中=%d 未命中=%s" % (hit, miss or "无"))
    if miss:
        print("\nANCHOR-MISS：%s" % "、".join(miss))
        return 2
    try:
        n = _run_groups()
    finally:
        _SRC.pop("compiler/pbc.py", None)
        _restore_real()
    print("\n修复前形态：失败=%d，跳过=%d" % (n, len(SKIPS)))
    if n == 0:
        print("退出码 3：修复前形态竟然全绿 ⇒ 本守卫对 #402 无鉴别力（不是好消息）")
        return 3
    print("按预期：修复前形态 FAIL —— 退出码 1 与「在真实修复前树上跑本守卫」的退出码**一致**，")
    print("上面的 FAIL 行即认证一要求的修复前原始输出（复现 #402：静默更短串 / 裸异常 / 非原子写）。")
    return 1


def main():
    try:
        if "--mutate" in sys.argv:
            return _mutate_mode("--list" in sys.argv)
        if "--pristine" in sys.argv:
            return _pristine_mode()
        n = _run_groups()
        print("\n.pbc 截断判据守卫（#402）：%d 通过，%d 失败，%d 跳过"
              % (len(PASSES), n, len(SKIPS)))
        return 0 if not n else 1
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
