# -*- coding: utf-8 -*-
"""test_rust_vm_jump_guard.py · Rust VM 跳转目标地址范围校验（N244，对齐 Python N239）

缺陷（红基线实测）：
  `swarm/rust_runtime/src/vm.rs` 写入 `self.ip` 的四处跳转/调用入口目标全无
  范围判定（JUMP / JUMP_IF_FALSE / ZHIZU / CALL）——
    · 负目标被 `… as usize` 折成巨大无符号数：`[(JUMP,-1),(PUSH_CONST,42),
      (STORE_NAME,'标记'),(ZHI,None)]` → `while self.ip < code.len()` 直接为假、
      run() 返回 Ok（halt=null）、二进制 exit 0，中间两条指令**静默不执行**；
    · `target > len(code)` 同样静默结束（其后指令整段不执行且无任何诊断）。
  经 `.pbc` 可达（`compiler/pbc.py` serialize 以 int64 承载任意地址）。
  Python 侧已修（N239 `_jump` 单点），Rust 侧缺口使两端语义分叉。

本守卫走**产品通路**：手写 .pbc（`compiler.pbc.save_pbc`）→ 生成项目并构建的
Rust 二进制 `protocol_vm --pbc <bad.pbc>` → 断言**非零退出**且诊断点明跳转
越界。纯行为断言（不看源码文本）。
**上界是 `<= len(code)` 而非 `<`**：`== len(code)` 是「跳到程序末尾」的既有
语义，编译器自身就产出该目标（知足标签与末尾 若/则 的 end 标签），本文件
第 ③⑥ 组钉死合法面一字不动。
"""
import io
import json
import os
import subprocess
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compiler.compiler import compile_source
from compiler.pbc import save_pbc
from swarm.rust_codegen import build_rust_exe, generate_rust_project

pass_n = fail_n = 0


def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print(f'[{"+" if ok else "x"}] {name}{" — " + detail if detail else ""}')


SOURCE = """问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：
1。道 新信任路径；
2。德 0.3；
3。止。
"""

# 知足样例：合法产物里 ZHIZU 的跳转目标恰为 len(code)（编译器自身产出），
# 用于钉死「上界取 <=」——收紧成 < 会把它打红。
SOURCE_ZHIZU = """问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：
1。道 新信任路径；
2。若 信任值 大于 0.3，则 德 0.5；
3。知足 0.7；
4。止。
"""


def run_pbc(exe, pbc_path, extra=()):
    """跑二进制单次模式：返回 (returncode, stdout, stderr)。"""
    r = subprocess.run([exe, "--pbc", pbc_path, *extra],
                       capture_output=True, text=True, timeout=120,
                       encoding="utf-8", errors="replace")
    return r.returncode, r.stdout, r.stderr


def expect_jump_error(exe, tmp, tag, code):
    """越界目标必须非零退出 + 诊断点明越界（不是 exit 0 的静默结束）。"""
    p = os.path.join(tmp, "bad.pbc")
    save_pbc(code, p)
    rc, out, err = run_pbc(exe, p)
    ok = rc != 0 and "跳转目标越界" in err
    detail = f"rc={rc} stderr={err.strip()[:80]} stdout={out.strip()[:60]}"
    check(f"{tag} → 非零退出 + 点明越界", ok, detail)


def expect_ok(exe, tmp, tag, code, pbc_name="ok.pbc", extra=(), halt=None):
    p = os.path.join(tmp, pbc_name)
    save_pbc(code, p)
    rc, out, err = run_pbc(exe, p, extra)
    if rc != 0:
        check(tag, False, f"rc={rc} stderr={err.strip()[:100]}")
        return None
    try:
        st = json.loads(out.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        check(tag, False, f"stdout 非 JSON：{out.strip()[:100]}")
        return None
    if halt is not None:
        check(tag, st.get("halt") == halt, f"halt={st.get('halt')!r}")
    return st


if __name__ == "__main__":
    tmp = tempfile.mkdtemp(prefix="rust_vm_jump_")
    proj = os.path.join(tmp, "proj")
    gen = generate_rust_project(SOURCE, proj)
    check("项目生成", gen["ok"])
    if not gen["ok"]:
        print(f"\n{pass_n} passed, {fail_n} failed")
        sys.exit(1)
    exe = build_rust_exe(proj)
    check("二进制构建", os.path.exists(exe), os.path.basename(exe))

    print("--- (1) 负目标不得被折成无符号数静默走完 ---")
    expect_jump_error(exe, tmp, "①a JUMP -1（旧实现：中间指令静默不执行、exit 0）",
                      [("JUMP", -1), ("PUSH_CONST", 42),
                       ("STORE_NAME", "标记"), ("ZHI", None)])
    expect_jump_error(exe, tmp, "①b JUMP_IF_FALSE -1（取假分支）",
                      [("PUSH_CONST", 0), ("JUMP_IF_FALSE", -1), ("ZHI", None)])
    expect_jump_error(exe, tmp, "①c ZHIZU (0.0,-1)（达标跳负地址）",
                      [("ZHIZU", (0.0, -1)), ("PUSH_CONST", 9), ("ZHI", None)])
    expect_jump_error(exe, tmp, "①d CALL 入口 -1",
                      [("PUSH_CONST", 1), ("CALL", (-1, ["a"])), ("ZHI", None)])

    print("--- (2) 超界目标不得静默结束 ---")
    expect_jump_error(exe, tmp, "②a JUMP 999（len=4）",
                      [("PUSH_CONST", 1), ("STORE_NAME", "甲"),
                       ("JUMP", 999), ("ZHI", None)])
    expect_jump_error(exe, tmp, "②b JUMP_IF_FALSE 99（取假分支）",
                      [("PUSH_CONST", 0), ("JUMP_IF_FALSE", 99), ("ZHI", None)])
    expect_jump_error(exe, tmp, "②c ZHIZU 超界地址",
                      [("ZHIZU", (0.0, 99)), ("ZHI", None)])
    expect_jump_error(exe, tmp, "②d CALL 入口超界",
                      [("PUSH_CONST", 1), ("CALL", (99, ["a"])), ("ZHI", None)])

    print("--- (3) 边界精确性：len(code) 合法，len+1 拒 ---")
    st = expect_ok(exe, tmp, "③a JUMP 到 len(code) 合法（跳到末尾 halt=null）",
                   [("PUSH_CONST", 1), ("STORE_NAME", "甲"),
                    ("JUMP", 4), ("ZHI", None)], pbc_name="end.pbc", halt=None)
    if st is not None:
        check("③a 跳转前的指令须已执行（甲=1）",
              st["symbols"].get("甲") == 1, str(st["symbols"]))
    expect_jump_error(exe, tmp, "③b JUMP 到 len(code)+1 拒",
                      [("PUSH_CONST", 1), ("STORE_NAME", "甲"),
                       ("JUMP", 5), ("ZHI", None)])

    print("--- (4) 合法面一字不动（编译器产物照跑）---")
    code_zhizu, r_zhizu = compile_source(SOURCE_ZHIZU, strict=False)
    check("④a 知足样例编译", r_zhizu["ok"], str(r_zhizu.get("errors"))[:80])
    if r_zhizu["ok"]:
        p = os.path.join(tmp, "zhizu.pbc")
        save_pbc(code_zhizu, p)
        rc, out, err = run_pbc(exe, p, ["--trust", "0.4"])
        got = None
        if rc == 0:
            try:
                got = json.loads(out.strip().splitlines()[-1])
            except (json.JSONDecodeError, IndexError):
                got = None
        check("④b 知足达标 → 跳到 len(code)、止 被跳过（trust=0.9、halt=null）",
              got is not None and got.get("trust") == 0.9 and got.get("halt") is None,
              f"rc={rc} state={got if got is None else (got.get('trust'), got.get('halt'))}"
              + (f" stderr={err.strip()[:80]}" if rc else ""))

    print(f"\n{pass_n} passed, {fail_n} failed")
    sys.exit(1 if fail_n else 0)
