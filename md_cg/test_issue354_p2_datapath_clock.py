# -*- coding: utf-8 -*-
# 功能名：datapath 保留设备名清单对「CLOCK$」的取源复核与假拒护栏（issue #354 P2-16）
# 生效条件：python -X utf8 -m md_cg.test_issue354_p2_datapath_clock [--mutate]；被测面=md_cg/datapath.py 的 _RESERVED_DEVICE_NAMES / _reserved_device_tail / _abs_host_path
# 子功能：A 组=固化「CLOCK$ 不是 Windows 保留设备名」的三重实测（内核 API / 归一 / 实建）与真源唯一性；K 组=真保留名仍被拒、判据不按字符集、平台闸与恒等归一未被削弱
# 执行：--mutate 时把「报告建议的修法」（清单加 CLOCK$）与两种反向改动注入镜像树，守卫必须按预期转红（定点变异自证）
# 验证方式：全部 PASS 即通过（断言总数须 ≥ FLOOR）；--mutate 下每条变异的「指定命中」须与预期一致；ntdll 不可用时该条如实标 SKIP（不假装通过）
# 不适用条件：不判非 Windows 平台的 Resolve 语义（平台闸另有断言）；不覆盖 Win9x/ReactOS 等非 NT 内核；不判「清单该不该更宽」这一设计取舍（取舍归使用者，本守护的是「误拒合法目录名」这一后果面）
"""issue #354 [P2-16] 复核守卫：Windows 保留设备名清单**不该**补 CLOCK$。

报告主张：清单漏了 CLOCK$，应补全。本端复核（第 4 条：先取证不猜测）判**不成立**，
三重独立读数都在同一侧：
  ① 内核判据  ntdll.RtlIsDosDeviceName_U：CON/PRN/AUX/NUL/CONIN$/CONOUT$/COM1/LPT1
     全非 0，CLOCK$ 与 clock$ 均为 0（NT 不认它是 DOS 设备名）；
  ② 归一判据  GetFullPathNameW 不把「<目录>\\clock$」吞成 \\\\.\\clock$（真设备名会吞）；
  ③ 实建判据  os.makedirs / CreateDirectoryW 建得成，写入读回一致，listdir 可见；
              \\\\.\\clock$ 打不开（而 \\\\.\\aux、\\\\.\\nul、\\\\.\\conin$ 都打得开）。
仓库自己的记录同口径：docs/eval/发布11_外报六连修与世界模型底座_v1.0.md 已写明
「实测 com0/lpt0/com10/lpt10/clock$ 不保留」。真源位置＝md_cg/datapath.py 的
_RESERVED_DEVICE_NAMES（模块自持、末段直判的唯一清单，**不另起一份**）。

为什么「宁缺不假拒」：_abs_host_path 是 **fail-closed** 面——命中即抛 ValueError，
mcp_server 启动探针据此 return 2（不带病运行）。把合法目录名收进清单，等于让
aux/data 根末段正好叫 clock$ 的用户**启动即被拒**；而漏一个「本机并不生效」的名字，
后果为零。故本守卫钉的是**后果面**：合法名不被假拒 + 真设备名仍被拒。
"""
from __future__ import annotations

import ast
import ctypes
import io
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from .datapath import (_RESERVED_DEVICE_NAMES, _abs_host_path,
                       _reserved_device_tail)

FLOOR = 40
PASS, FAIL, SKIP = 0, 0, 0
FAILS = []

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DP = os.path.join(_REPO, "md_cg", "datapath.py")


def _check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS " + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL " + name + "  " + str(detail)[:220])


def _skip(name, why):
    global SKIP
    SKIP += 1
    print("  SKIP " + name + "  " + why)


def _is_nt():
    return os.name == "nt"


def _rtl_is_dos_device(name):
    """ntdll.RtlIsDosDeviceName_U：返回设备名长度（0 = 不是 DOS 设备名）；不可用返回 None。"""
    try:
        f = ctypes.WinDLL("ntdll").RtlIsDosDeviceName_U
        f.argtypes = [ctypes.c_wchar_p]
        f.restype = ctypes.c_ulong
        return int(f(name))
    except Exception:                              # noqa: BLE001
        return None


def _raises(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return False, ""
    except ValueError as e:
        return True, str(e)
    except Exception as e:                         # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, e)


print("== A 组：判据固化（CLOCK$ 不收的读数与真源唯一性）==")

# A1 真源唯一性：末段直判清单只有一处定义（本仓忌「两份真源漂移」）
with io.open(_DP, encoding="utf-8", newline="") as f:
    _SRC = f.read()
_ndef = _SRC.count("_RESERVED_DEVICE_NAMES = frozenset(")
_check("A1 清单在 datapath.py 中恰定义 1 次（真源单点）", _ndef == 1, _ndef)
_sites = []
for _fn in ast.walk(ast.parse(_SRC)):
    if isinstance(_fn, ast.FunctionDef) and any(
            isinstance(n, ast.Name) and n.id == "_RESERVED_DEVICE_NAMES"
            for n in ast.walk(_fn)):
        _sites.append(_fn.name)
_check("A1 清单只被 _reserved_device_tail 消费（AST 面，无第二份副本）",
       _sites == ["_reserved_device_tail"], _sites)

# A2 清单不含 CLOCK$
_upper = {str(n).upper() for n in _RESERVED_DEVICE_NAMES}
_check("A2 清单不含 CLOCK$（大小写不敏感）",
       "CLOCK$" not in _upper, sorted(_upper))
_check("A2 清单仍含 DOS 设备名与主控台伪设备（判据非空集）",
       {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} <= _upper,
       sorted(_upper))

# A3 谓词面：clock$ 的各种形态都判「不是保留名」
for form in ("clock$", "CLOCK$", "Clock$", "clock$.txt", "D:\\probe\\clock$",
             "D:/probe/clock$", "clock$ ", "clock$.log"):
    _check("A3 _reserved_device_tail(%r) 判 False（不是保留名）" % form,
           _reserved_device_tail(form) is False, _reserved_device_tail(form))

# A4 归一/现场面：合法目录名不被 fail-closed 误拒
_tmp = tempfile.mkdtemp(prefix="i354p2_")
try:
    _clock_path = os.path.join(_tmp, "clock$")
    if _is_nt():
        ok, why = _raises(_abs_host_path, _clock_path, "MDCG_AUX_ROOT")
        _check("A4 _abs_host_path(<tmp>\\clock$) 不抛（合法名不被误拒）",
               not ok, why)
        try:
            got = _abs_host_path(_clock_path, "MDCG_AUX_ROOT")
            _check("A4 归一结果末段仍是 clock$（未吞成设备路径）",
                   got.replace("/", "\\").rstrip("\\").split("\\")[-1] == "clock$",
                   got)
        except Exception as e:                     # noqa: BLE001
            _check("A4 归一结果末段仍是 clock$（未吞成设备路径）", False, e)
    else:
        _skip("A4 _abs_host_path(<tmp>\\clock$) 不抛", "非 Windows：平台闸不判定")

    # A5 实建面：真的建得出来、写得进、读得回
    made = True
    try:
        os.makedirs(_clock_path)
    except Exception as e:                         # noqa: BLE001
        made = False
        _check("A5 os.makedirs 建 clock$ 目录成功", False,
               "%s: %s" % (type(e).__name__, e))
    if made:
        _check("A5 os.makedirs 建 clock$ 目录成功且 isdir 为真",
               os.path.isdir(_clock_path), "")
        try:
            fp = os.path.join(_clock_path, "probe.txt")
            with io.open(fp, "w", encoding="utf-8", newline="") as f:
                f.write("i354p2")
            with io.open(fp, encoding="utf-8", newline="") as f:
                back = f.read()
            _check("A5 clock$ 目录内写入读回一致", back == "i354p2", back)
        except Exception as e:                     # noqa: BLE001
            _check("A5 clock$ 目录内写入读回一致", False,
                   "%s: %s" % (type(e).__name__, e))
        _check("A5 listdir 里可见 clock$（不是被吞的设备路径）",
               "clock$" in os.listdir(_tmp), sorted(os.listdir(_tmp)))
finally:
    shutil.rmtree(_tmp, ignore_errors=True)

# A6 内核判据面
if _is_nt():
    r_clock = _rtl_is_dos_device("CLOCK$")
    r_aux = _rtl_is_dos_device("AUX")
    r_conout = _rtl_is_dos_device("CONOUT$")
    if r_clock is None:
        _skip("A6 RtlIsDosDeviceName_U 判 CLOCK$=0", "ntdll 不可用")
    else:
        _check("A6 RtlIsDosDeviceName_U(\"CLOCK$\") == 0（NT 不认它是设备名）",
               r_clock == 0, r_clock)
        _check("A6 对照：AUX / CONOUT$ 均非 0（判据非恒零）",
               (r_aux or 0) > 0 and (r_conout or 0) > 0, (r_aux, r_conout))
    # 设备命名空间对照：\\.\clock$ 打不开，而真设备名打得开
    opened = {}
    for n in ("aux", "nul", "conin$", "clock$"):
        try:
            fd = os.open("\\\\.\\" + n, os.O_RDONLY)
            os.close(fd)
            opened[n] = True
        except Exception:                          # noqa: BLE001
            opened[n] = False
    _check("A6 \\\\.\\clock$ 打不开（不是设备）", opened.get("clock$") is False,
           opened)
    _check("A6 对照：\\\\.\\aux / \\\\.\\nul / \\\\.\\conin$ 都打得开（判据非恒假）",
           opened.get("aux") and opened.get("nul") and opened.get("conin$"),
           opened)
else:
    _skip("A6 内核判据面", "非 Windows")

# A7 同源：仓库既有记录同口径（文件缺失则如实跳过，不假装核过）
_doc = None
_docs = os.path.join(_REPO, "docs", "eval")
if os.path.isdir(_docs):
    for fn in sorted(os.listdir(_docs)):
        if fn.startswith("发布11_"):
            _doc = os.path.join(_docs, fn)
            break
if _doc is None:
    _skip("A7 既有记录同口径", "docs/eval/发布11_* 不在本检出面")
else:
    with io.open(_doc, encoding="utf-8", newline="") as f:
        _dtxt = f.read()
    _check("A7 既有记录已写明 clock$ 实测不保留（同源口径）",
           "clock$" in _dtxt and "不保留" in _dtxt, _doc)

print("")
print("== K 组：非恒真 / 非恒假对照 ==")

# K1 真保留名仍判 True
_TRUE_FORMS = ["CON", "con", "PRN", "AUX", "aux", "NUL", "nul", "CONIN$",
               "conin$", "CONOUT$", "COM1", "COM9", "LPT1", "LPT9",
               "D:\\probe\\aux", "D:/probe/aux", "aux.txt", "AUX ", "nul.",
               "aux...", "com1.tar.gz"]
for form in _TRUE_FORMS:
    _check("K1 _reserved_device_tail(%r) 判 True" % form,
           _reserved_device_tail(form) is True, _reserved_device_tail(form))

# K2 非保留名仍判 False
_FALSE_FORMS = ["cone", "clock", "com0", "com10", "lpt0", "lpt10", "auxx",
                ".aux", "auxiliary", "", "D:\\probe\\com0", "clock$",
                "logger$", "conin", "com", "lpt", "nul1", "con2x"]
for form in _FALSE_FORMS:
    _check("K2 _reserved_device_tail(%r) 判 False" % form,
           _reserved_device_tail(form) is False, _reserved_device_tail(form))

# K3 判据不是「带 $ 就拒」
_check("K3 对照：CONOUT$ 判 True 而 CLOCK$ 判 False（不是按字符集定）",
       _reserved_device_tail("CONOUT$") is True
       and _reserved_device_tail("CLOCK$") is False, "")

# K4 现场对照：真保留名仍 fail-closed
_tmp2 = tempfile.mkdtemp(prefix="i354p2k_")
try:
    _aux_path = os.path.join(_tmp2, "aux")
    raised, why = _raises(_abs_host_path, _aux_path, "MDCG_AUX_ROOT")
    if _is_nt():
        _check("K4 _abs_host_path(<tmp>\\aux) 抛 ValueError（真设备名仍拒）",
               raised and "保留设备名" in why, why[:120])
    else:
        _check("K4 非 Windows：<tmp>/aux 是合法目录名，不抛（平台闸在）",
               not raised, why[:120])
    raised2, _ = _raises(_abs_host_path, os.path.join(_tmp2, "cone"))
    _check("K4 对照：<tmp>\\cone 任何平台都不抛（判据非恒真）", not raised2, "")
    # K5 恒等归一：普通路径 abspath 语义未被改动
    p = os.path.join(_tmp2, "plain", "..", "plain")
    _check("K5 普通路径仍走 abspath 归一（恒等语义未变）",
           os.path.normcase(_abs_host_path(p)) ==
           os.path.normcase(os.path.abspath(p)), _abs_host_path(p))
finally:
    shutil.rmtree(_tmp2, ignore_errors=True)

print("")
print("断言总数 %d（PASS %d / FAIL %d / SKIP %d），FLOOR=%d"
      % (PASS + FAIL, PASS, FAIL, SKIP, FLOOR))
if PASS + FAIL < FLOOR:
    FAILS.append("FLOOR")
    print("  FAIL 断言总数低于 FLOOR —— 探针面疑似失效（防假绿）")

if FAILS:
    print("issue #354 [P2-16] 结果：%d 失败" % len(FAILS))
    for f in FAILS:
        print("   - " + f)
else:
    print("issue #354 [P2-16] 结果：全部通过（CLOCK$ 不收——报告主张不成立）")


# ---------------------------------------------------------------- 定点变异自证

_TARGET = "md_cg/datapath.py"
_LIST_ANCHOR = '    ["CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"]'
_MUTATIONS = (
    ("V1 按报告建议把 CLOCK$ 加进清单（假拒合法目录名）",
     _LIST_ANCHOR,
     '    ["CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$", "CLOCK$"]',
     ("A2", "A3", "A4")),
    ("V2 反向：删掉真保留名 AUX（清单失守）",
     _LIST_ANCHOR,
     '    ["CON", "PRN", "NUL", "CONIN$", "CONOUT$"]',
     ("K1", "K4")),
    ("V3 大小写归一被去掉（stem 不再 .upper()）",
     "    return stem.upper() in _RESERVED_DEVICE_NAMES",
     "    return stem in _RESERVED_DEVICE_NAMES",
     ("K1",)),
)


def _mirror_build():
    """镜像树：拷 md_cg/scripts/根级 .py 到临时树（真实工作树只读）。"""
    dst = tempfile.mkdtemp(prefix="i354p2_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and name.endswith(".py"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _fold(text, eol):
    """按目标文件实际行尾折算（本仓 CRLF/LF 混合）。"""
    return text.replace("\r\n", "\n").replace("\n", eol)


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue354_p2_datapath_clock"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "FAIL " in ln]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：注入报告建议的修法与两种反向改动，守卫必须按预期转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print("\n".join(out.splitlines()[-25:]))
        ok, bad = 0, []
        for desc, old, new, exp in _MUTATIONS:
            p = os.path.join(tree, _TARGET)
            with io.open(p, encoding="utf-8", newline="") as f:
                t = f.read()
            eol = "\r\n" if "\r\n" in t else "\n"
            o, n = _fold(old, eol), _fold(new, eol)
            if t.count(o) != 1:
                bad.append("%s —— 锚点在 %s 里命中 %d 次" % (desc, _TARGET, t.count(o)))
                print("  ANCHOR-MISS " + desc)
                continue
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(t.replace(o, n, 1))
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(t)
            hit = [r for r in reds2 if any(r.startswith(e) for e in exp)]
            if rc2 != 0 and len(hit) >= len(exp):
                ok += 1
                print("  OK   %s  红项=%d 指定命中=%d/%d"
                      % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s  红项=%d 指定命中=%d/%d rc=%d"
                      % (desc, len(reds2), len(hit), len(exp), rc2))
                for r in reds2[:8]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    if "--mutate" in sys.argv:
        _mutate()
        return 0 if not FAILS else 1
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
