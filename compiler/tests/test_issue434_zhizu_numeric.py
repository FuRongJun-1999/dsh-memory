# -*- coding: utf-8 -*-
"""test_issue434_zhizu_numeric.py · issue #434 回归：知足阈值位裸 float 不再穿透编译主入口

缺陷（issue #434）：compiler/compiler.py 的 _instr 里 ZHIZU 分支
threshold = float(val) 无防护。name_checker 的 INSTRUCTION_CONSTRAINTS[ZHIZU]
把 identifier 列为合法操作数（example='知足 验证单元'），于是官方约束表允许的
写法在字节码入口抛裸 ValueError（异常逃逸、不返回结构化错误）；同族的 DE 分支
在同输入下返回结构化错误「德 的操作数必须是数值…（名实不符）」，两面口径分叉。

修复语义（对齐 DE 分支，本件只动字节码入口的异常面）：
  非数值操作数 → 结构化 SyntaxError「知足 的操作数必须是数值，得到 '…'（名实不符）」，
  经 compile_source 窄捕获回流为 (None, {ok: False, errors: [...]})；数值操作数
  （含缺省 None → 0.0）字节码逐位不变。api/codegen 入口维持既有契约
  （identifier 是运行期检查目标，success=True；见 test_full_pipeline.multi_word_phrase）
  —— 两个入口的语义是否统一属另案裁定，本件不夹带。

守卫：12 条断言 + 3 条定点变异（naked-float / silent-zero / reject-valid），
每条变异短路一个实现缺陷 ⇒ 指定断言必须转红且点名（多红/少红均判 FAIL）。
"""
import os
import re
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
_SELF = os.path.abspath(__file__)
_COMPILER = os.path.join(_REPO, "compiler", "compiler.py")
sys.path.insert(0, _REPO)

from compiler.api import compile_source as api_compile
from compiler.compiler import compile_source as bc_compile
from compiler.condition_vm import Opcode
from compiler.pbc import compile_to_pbc

BAD_FORMS = (
    ("A1", "知足 验证单元。", "验证单元"),
    ("A2", "知足 abc。", "abc"),
    ("A3", "知足 情感权重。", "情感权重"),
)
GOOD_NUM = "知足 0.7。"
# 多指令数值程序（strict=False：只测字节码入口的数值分支；名实校验不是本件判据面）
GOOD_PROGRAM = "术曰：\n1。德 0.5；\n2。知足 0.7；\n3。止。"
BAD_PROGRAM = "术曰：\n1。德 0.5；\n2。知足 验证单元；\n3。止。"


def _bc(src, strict=True):
    """返回 (code, result, exception)：异常不逃逸到断言外。"""
    try:
        code, r = bc_compile(src, strict=strict)
        return code, r, None
    except Exception as exc:  # noqa: BLE001 —— 缺陷态正是裸异常，须捕获后判红
        return None, None, exc


def _structured_reject(src, strict=True):
    code, r, exc = _bc(src, strict=strict)
    if exc is not None:
        return False, "裸异常 %s: %s" % (type(exc).__name__, exc)
    errs = (r or {}).get("errors") or []
    ok = (
        code is None
        and bool(r)
        and r.get("ok") is False
        and bool(errs)
        and "知足" in errs[0]
        and "必须是数值" in errs[0]
        and "名实不符" in errs[0]
        and "ValueError" not in errs[0]
        and "Traceback" not in errs[0]
    )
    return ok, "code=%r ok=%r errors=%r" % (code, (r or {}).get("ok"), errs)


def a1_identifier_structured():
    return _structured_reject(BAD_FORMS[0][1])


def a2_ascii_identifier_structured():
    return _structured_reject(BAD_FORMS[1][1])


def a3_multiword_identifier_structured():
    return _structured_reject(BAD_FORMS[2][1])


def a4_de_parity_unchanged():
    code, r, exc = _bc("德 验证单元。")
    if exc is not None:
        return False, "裸异常 %s: %s" % (type(exc).__name__, exc)
    errs = (r or {}).get("errors") or []
    expect = "L1 德 的操作数必须是数值，得到 '验证单元'（名实不符）"
    ok = code is None and (r or {}).get("ok") is False and errs == [expect]
    return ok, "code=%r ok=%r errors=%r" % (code, (r or {}).get("ok"), errs)


def a5_numeric_single_bytecode_frozen():
    code, r, exc = _bc(GOOD_NUM)
    if exc is not None:
        return False, "裸异常 %s: %s" % (type(exc).__name__, exc)
    ok = (r or {}).get("ok") is True and code == [(Opcode.ZHIZU, (0.7, 1))]
    return ok, "code=%r ok=%r" % (code, (r or {}).get("ok"))


def a6_numeric_program_ok():
    code, r, exc = _bc(GOOD_PROGRAM, strict=False)
    if exc is not None:
        return False, "裸异常 %s: %s" % (type(exc).__name__, exc)
    zhizus = [arg for op, arg in (code or []) if op == Opcode.ZHIZU]
    ok = (
        (r or {}).get("ok") is True
        and bool(code)
        and len(zhizus) == 1
        and zhizus[0][0] == 0.7
        and (r or {}).get("errors") == []
    )
    return ok, "ok=%r zhizu=%r errors=%r" % ((r or {}).get("ok"), zhizus, (r or {}).get("errors"))


def a7_bad_program_structured():
    return _structured_reject(BAD_PROGRAM, strict=False)


def a8_pbc_entry_structured():
    fd, path = tempfile.mkstemp(suffix=".pbc")
    os.close(fd)
    try:
        code, r = compile_to_pbc("知足 验证单元。", path)
        errs = (r or {}).get("errors") or []
        ok = (
            code is None
            and (r or {}).get("ok") is False
            and bool(errs)
            and "知足" in errs[0]
            and "必须是数值" in errs[0]
            and os.path.getsize(path) == 0
        )
        return ok, "code=%r ok=%r errors=%r exists=%s" % (
            code, (r or {}).get("ok"), errs, os.path.exists(path))
    except Exception as exc:  # noqa: BLE001 —— 缺陷态裸异常须判红
        return False, "裸异常 %s: %s" % (type(exc).__name__, exc)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def a9_pbc_numeric_ok():
    fd, path = tempfile.mkstemp(suffix=".pbc")
    os.close(fd)
    try:
        code, r = compile_to_pbc("知足 0.7。", path)
        ok = (
            bool(code)
            and (r or {}).get("ok") is True
            and os.path.exists(path)
            and os.path.getsize(path) > 0
        )
        return ok, "code=%r ok=%r exists=%s size=%s" % (
            code, (r or {}).get("ok"), os.path.exists(path),
            os.path.getsize(path) if os.path.exists(path) else -1)
    except Exception as exc:  # noqa: BLE001
        return False, "裸异常 %s: %s" % (type(exc).__name__, exc)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def a10_empty_operand_zero_threshold():
    code, r, exc = _bc("知足。")
    if exc is not None:
        return False, "裸异常 %s: %s" % (type(exc).__name__, exc)
    ok = (r or {}).get("ok") is True and code == [(Opcode.ZHIZU, (0.0, 1))]
    return ok, "code=%r ok=%r" % (code, (r or {}).get("ok"))


def a11_api_entry_contract_pinned():
    """api/codegen 入口维持既有契约：identifier 操作数是运行期检查目标。

    与 test_full_pipeline.multi_word_phrase（'柔 响应强度；知足 验证单元。'
    expect_success=True）同源；本件不改它，只把契约钉住。
    """
    r_bad = api_compile("知足 验证单元。")
    r_good = api_compile(GOOD_NUM)
    ok = (
        r_bad.success is True
        and r_bad.errors == []
        and r_good.success is True
        and r_good.errors == []
    )
    return ok, "bad(success=%r errors=%r) good(success=%r errors=%r)" % (
        r_bad.success, r_bad.errors, r_good.success, r_good.errors)


def a12_strict_false_still_structured():
    return _structured_reject("知足 验证单元。", strict=False)


_ASSERTIONS = (
    ("A1", a1_identifier_structured),
    ("A2", a2_ascii_identifier_structured),
    ("A3", a3_multiword_identifier_structured),
    ("A4", a4_de_parity_unchanged),
    ("A5", a5_numeric_single_bytecode_frozen),
    ("A6", a6_numeric_program_ok),
    ("A7", a7_bad_program_structured),
    ("A8", a8_pbc_entry_structured),
    ("A9", a9_pbc_numeric_ok),
    ("A10", a10_empty_operand_zero_threshold),
    ("A11", a11_api_entry_contract_pinned),
    ("A12", a12_strict_false_still_structured),
)

# 定点变异臂：锚点 → (原串, 短路串, 期望转红的断言集合)
_ARMS = {
    "M1": (
        "            try:\n"
        "                threshold = float(val) if val is not None else 0.0\n"
        "            except (TypeError, ValueError):\n"
        "                raise SyntaxError(\n"
        "                    f\"L{s.line} 知足 的操作数必须是数值，得到 '{val}'（名实不符）\")\n",
        "            threshold = float(val) if val is not None else 0.0\n",
        {"A1", "A2", "A3", "A7", "A8", "A12"},
    ),
    "M2": (
        "            except (TypeError, ValueError):\n"
        "                raise SyntaxError(\n"
        "                    f\"L{s.line} 知足 的操作数必须是数值，得到 '{val}'（名实不符）\")\n",
        "            except (TypeError, ValueError):\n"
        "                threshold = 0.0\n",
        {"A1", "A2", "A3", "A7", "A8", "A12"},
    ),
    "M3": (
        "            try:\n"
        "                threshold = float(val) if val is not None else 0.0\n",
        "            try:\n"
        "                threshold = float(val) if val is not None else 0.0\n"
        "                if threshold is not None:\n"
        "                    raise SyntaxError(\n"
        "                        f\"L{s.line} 知足 的操作数必须是数值，得到 '{val}'（名实不符）\")\n",
        {"A5", "A6", "A9", "A10"},
    ),
}


def _run_assertions():
    """跑全部断言，返回失败数；逐条 [OK]/[FAIL] + 汇总行。"""
    fail = 0
    for name, fn in _ASSERTIONS:
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001 —— 断言外异常也算红
            ok, detail = False, "未捕获 %s: %s" % (type(exc).__name__, exc)
        fail += 0 if ok else 1
        print("[%s] %s %s" % ("OK  " if ok else "FAIL", name, detail))
    print("通过 %d / 失败 %d" % (len(_ASSERTIONS) - fail, fail))
    return fail


def _subprocess_fail_names():
    """在子进程里跑断言（确保 import 到变异后的源码），返回 (红项集合, 原始输出)。"""
    r = subprocess.run(
        [sys.executable, "-X", "utf8", _SELF, "--assert-only"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=_REPO, timeout=300,
    )
    names = set(re.findall(r"\[FAIL\]\s+(A\d+)", r.stdout or ""))
    return names, (r.stdout or "") + (r.stderr or "")


def _mutate(argv):
    want = ""
    for a in argv:
        if a == "--mutate":
            want = want or "ALL"
        elif a.startswith("--mutate="):
            want = a.split("=", 1)[1]
    if not want:
        return 0

    ids = sorted(_ARMS) if want == "ALL" else [want]
    with open(_COMPILER, "rb") as fh:
        orig = fh.read()
    red = 0
    try:
        for mid in ids:
            if mid not in _ARMS:
                print("[ANCHOR-MISS] %s：未登记该变异臂" % mid)
                return 2
            old, new, expect = _ARMS[mid]
            text = orig.decode("utf-8")
            nl = "\r\n" if "\r\n" in text else "\n"
            norm = text.replace("\r\n", "\n")
            if norm.count(old) != 1:
                print("[ANCHOR-MISS] %s：锚点命中 %d 次（期望 1）⇒ 无法变异，判据失效"
                      % (mid, norm.count(old)))
                return 2
            with open(_COMPILER, "wb") as fh:
                fh.write(norm.replace(old, new).replace("\n", nl).encode("utf-8"))
            actual, out = _subprocess_fail_names()
            if actual == expect:
                print("[MUTATE-OK]   %s：指定断言转红 %s" % (mid, sorted(actual)))
            else:
                print("[MUTATE-FAIL] %s：期望红 %s，实际红 %s"
                      % (mid, sorted(expect), sorted(actual)))
                for line in out.splitlines():
                    if line.startswith("[FAIL]"):
                        print("    " + line)
                red += 1
    finally:
        with open(_COMPILER, "wb") as fh:
            fh.write(orig)
    print("反证结果：%d 条变异，%s" % (len(ids), "全部恰好命中" if red == 0 else "%d 条未命中" % red))
    return 1 if red else 0


if __name__ == "__main__":
    _f = _run_assertions()
    if "--assert-only" in sys.argv:
        sys.exit(1 if _f else 0)
    _m = _mutate(sys.argv[1:])
    sys.exit(1 if (_f or _m) else 0)
