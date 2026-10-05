# -*- coding: utf-8 -*-
"""test_rust_vm_builtin_guard_n272.py · Rust VM 内建写面闸 + 双后端同判守卫（N272）

缺陷（2026-10-05 本会话实跑复现；编号续 N269）：
  ① 信任阈值写静默遮蔽（Rust 侧）：『信任阈值 = 0.9／止。』Rust VM 照收
     （实测 stage=None、state symbols={'信任阈值': 0.9}）——内建只读名被
     符号表遮蔽，判定被改写；Python 侧同漏（见 compiler 侧守卫）。
  ② 空间名可写（Rust 侧）：『伴侣 = 1.0』照收（symbols={'伴侣': 1}）。
  ③ 写类型闸（Rust 侧既有，本守卫钉其不回归并与 Python 新闸同判）：
     信任值写非数值 / 条件空间写非字符串 → VmError::Error（结构化，
     非 panic）；Python 侧须同判（结构化 VMBuiltinError，不再裸 TypeError）。

修复（N272）：
  Rust STORE_NAME 增只读拒（信任阈值 + 伴侣/工作/默认/恢复默认/default），
  与 Python 单点闸同判；写类型闸两侧语义逐字对齐（信任值/信任分量须数值、
  条件空间须字符串）。本守卫用真实 cargo 构建双后端，逐形态比对。

cargo 不可用时按环境声明跳过（与 test_rust_codegen ⑦ 同范式）。
"""
import io
import json
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compiler.compiler import compile_source as vm_compile
from compiler.condition_vm import ConditionVM
from compiler import condition_vm as vmm
from swarm.rust_codegen import build_and_run, generate_rust_project

pass_n = fail_n = 0


def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')


def py_run(src, trust=0.0, symbols=None):
    """源码（宽松编译）→ Python VM 执行；返回 (state, 异常名, 异常消息)。"""
    code, r = vm_compile(src, strict=False)
    if not r.get("ok"):
        return None, "CompileError", str(r.get("errors", [])[:1])
    try:
        return ConditionVM().run(code, symbols=dict(symbols or {}), trust=trust), None, ""
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__, str(e)


def rust_run(src, trust=0.0, symbols=None):
    """源码（宽松编译）→ Rust cargo 构建运行；返回 (state, ok, stderr)。"""
    tmp = tempfile.mkdtemp(prefix="n272_")
    gen = generate_rust_project(src, os.path.join(tmp, "proj"), strict=False)
    if not gen.get("ok"):
        return None, False, "generate 失败: %s" % str(gen.get("result", {}).get("errors"))[:120]
    rr = build_and_run(gen["project_dir"], trust=trust, symbols=symbols)
    return rr.get("state"), bool(rr.get("ok")), rr.get("stderr", "") or ""


has_cargo = shutil.which("cargo") is not None

print("--- (1) 只读内建名写入：Rust 结构化拒（修复前照收）---")

if has_cargo:
    for tag, src, name in [
            ("①a", "信任阈值 = 0.9\n止。", "信任阈值"),
            ("①b", "伴侣 = 1.0\n止。", "伴侣"),
            ("①c", "默认 = 1.0\n止。", "默认")]:
        st, ok, err = rust_run(src)
        check("%s Rust 拒 %s 写入（修复前 symbols 被遮蔽）" % (tag, name),
              (not ok) and ("只读内建名" in err),
              f"ok={ok} stderr={err[:120]!r}")
else:
    check("cargo 不可用 → 跳过 (1)（环境声明）", True)

print("--- (2) 写类型闸：两 VM 同判（结构化，非裸异常/panic）---")

TYPE_CASES = [
    ("②a", '信任值 = "0.9"\n止。', "信任值", "只能写数值"),
    ("②b", "条件空间 = 0.9\n止。", "条件空间", "只能写空间名"),
]

if has_cargo:
    for tag, src, name, needle in TYPE_CASES:
        st_py, exc_py, msg_py = py_run(src)
        check("%s Python 拒（%s 结构化）" % (tag, "VMBuiltinError"),
              exc_py == "VMBuiltinError" and needle in msg_py,
              f"{exc_py}: {msg_py[:100]}")
        st, ok, err = rust_run(src)
        check("%s Rust 同判（%s）" % (tag, needle), (not ok) and needle in err,
              f"ok={ok} stderr={err[:120]!r}")
else:
    check("cargo 不可用 → 跳过 (2)（环境声明）", True)

print("--- (3) 合法写面双后端等价（不回归）---")

LEGAL_SRC = "信任值 = 0.9\n条件空间 = 伴侣\n止。"

if has_cargo:
    st_py, exc_py, msg_py = py_run(LEGAL_SRC)
    st_rs, ok_rs, err_rs = rust_run(LEGAL_SRC)
    ok_py = st_py is not None and abs(st_py["trust"] - 0.9) < 1e-9 \
        and st_py["condition_space_name"] == "伴侣"
    check("③a Python 合法写入不回归（信任=0.9 空间=伴侣）", ok_py, msg_py or str(st_py)[:100])
    ok_r = ok_rs and st_rs is not None and abs(st_rs["trust"] - 0.9) < 1e-9 \
        and st_rs["condition_space"][0]["name"] == "伴侣"
    check("③b Rust 合法写入不回归", ok_r, f"ok={ok_rs} stderr={err_rs[:120]!r}")
    check("③c 双后端合法面语义等价（trust/空间名）",
          ok_py and ok_r, "py/rs 见上两条")
else:
    check("cargo 不可用 → 跳过 (3)（环境声明）", True)

print("--- (4) 写面拒集合两 VM 一致（同源码同判) ---")

if has_cargo:
    for tag, src in [("④a", "信任阈值 = 0.9\n止。"),
                     ("④b", "恢复默认 = 1.0\n止。")]:
        st_py, exc_py, _ = py_run(src)
        st_rs, ok_rs, err_rs = rust_run(src)
        check("%s 两 VM 均拒（py=%s / rs ok=%s）" % (tag, exc_py, ok_rs),
              exc_py == "VMBuiltinError" and (not ok_rs),
              f"py_exc={exc_py} rs_ok={ok_rs} stderr={err_rs[:100]!r}")
else:
    check("cargo 不可用 → 跳过 (4)（环境声明）", True)

print(f"\n=== N272 Rust 内建写面闸守卫: {pass_n}/{pass_n + fail_n} 通过 ===")
sys.exit(0 if fail_n == 0 else 1)
