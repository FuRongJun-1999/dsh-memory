# -*- coding: utf-8 -*-
"""test_rust_vm_nonfinite_gate_435.py · Rust VM 非有限闸 + 双后端同判守卫（issue #435）

缺陷（issue #435）：Python float() 接受 'inf'/'nan' 全形态——「必须是数值」
编译闸被穿透，信任寄存器被毒化（NaN 破坏等式自反性使 止 永不触发、inf
恒过 知足 阈值使其恒早退）。Rust 侧同族：STORE_NAME 写闸只判 is_num
（f64::INFINITY 正是 Float ⇒ 放行）、DE 直接 trust_value += d（无有限性
复核）——手搓 .pbc / 修复前落盘产物在 Rust 执行路径同样毒化。

修复（#435，与 Python 侧同判）：
  Rust STORE_NAME 信任值/信任分量写闸 + DE 累积先算后验补 is_finite 拒
  （VmError::Error，消息含「有限」）；编译期闸单点在 compiler.py
  （float() 后 isfinite），由 compiler/tests/test_issue435_nonfinite_gate.py
  双入口守卫——本守卫钉 Rust 面与双后端同判。

技术审返工（PR #449 复审，ybyz2 09:04）：
  · 补 `知足`(ZHIZU) 运行期阈值面：inf/-inf/nan 阈值（.pbc 8 字节 double
    保真注入）两 VM 同拒——-inf 使判定反向（恒达标早退、止 被跳过）。
  · cargo 不可用的跳过行改**行首 SKIP 前缀**（issue #284 口径：SKIP 不得
    冒充 PASS——run_tests._SKIP_LINE_RE 只认行首 `SKIP`/`[SKIP]`，旧式
    `[✓] cargo 不可用 → 跳过` 经 check() 计入 pass_n 且不匹配 SKIP 正则
    ⇒ 整模块被记 PASS，Rust 面实未验收）。初值注入面（run 的 trust 参数/
    种子）无 CLI 入口，由 swarm/rust_runtime 的 cargo test 单测守
    （run_rejects_nonfinite_initial_trust）。

手法：真实 cargo 构建（swarm/rust_codegen 模板拷贝含修复后 vm.rs），
以 --pbc 喂手搓 .pbc（编译期闸管不到的注入面）；一次构建多次复用。
cargo 不可用时按环境声明跳过（与 test_rust_vm_builtin_guard_n272 同范式）。
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compiler.pbc import serialize, run_pbc
from compiler.condition_vm import Opcode
from compiler import condition_vm as vmm
from swarm.rust_codegen import build_rust_exe, generate_rust_project

pass_n = fail_n = 0


def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')


print("--- (1) 编译期闸收口 Rust 嵌入路径：德 inf 生成即拒（无需 cargo）---")

tmp1 = tempfile.mkdtemp(prefix="i435_gen_")
gen = generate_rust_project("德 inf。\n止。", os.path.join(tmp1, "proj"), strict=False)
check("①a rust_codegen 生成 德 inf 即拒（编译闸单点在前端）",
      not gen.get("ok")
      and any("有限" in str(e) for e in gen.get("result", {}).get("errors", [])),
      f"ok={gen.get('ok')} errors={str(gen.get('result', {}).get('errors', []))[:100]}")
check("①b 未产出 project.pbc（毒化产物不落地）",
      not os.path.exists(os.path.join(tmp1, "proj", "program.pbc")), "")

has_cargo = shutil.which("cargo") is not None

print("--- (2) Rust 运行期闸：--pbc 手搓字节码非有限拒 ---")

# 手搓 .pbc：编译期闸管不到的注入面（NaN/inf 操作数、溢出累积、写闸、
# 知足 非有限阈值）。第 4 元 = 期望终态 trust（want_ok=True 时断言）。
CASES = [
    ("②a", [(Opcode.DE, float("inf"))], False, None),
    ("②b", [(Opcode.DE, float("nan"))], False, None),
    ("②c", [(Opcode.DE, 1e308), (Opcode.DE, 1e308)], False, None),  # 溢出累积
    ("②d", [(Opcode.PUSH_CONST, float("inf")),
             (Opcode.STORE_NAME, "信任值"), (Opcode.ZHI, None)], False, None),
    ("②e", [(Opcode.PUSH_CONST, float("nan")),
             (Opcode.STORE_NAME, "P_trust"), (Opcode.ZHI, None)], False, None),
    # 知足 运行期阈值面（技术审返工·阻断②）：.pbc 8 字节 double 保真注入
    ("②h", [(Opcode.ZHIZU, (float("-inf"), 2)),
             (Opcode.DE, 0.1), (Opcode.ZHI, None)], False, None),  # 判定反向
    ("②i", [(Opcode.ZHIZU, (float("inf"), 2)),
             (Opcode.ZHI, None)], False, None),                    # 恒不可达
    ("②j", [(Opcode.ZHIZU, (float("nan"), 2)),
             (Opcode.ZHI, None)], False, None),                    # 自反性破坏
    # 对照：有限值不误伤
    ("②f", [(Opcode.DE, 0.5), (Opcode.DE, 0.25), (Opcode.ZHI, None)], True, 0.75),
    ("②g", [(Opcode.PUSH_CONST, 0.9),
             (Opcode.STORE_NAME, "信任值"), (Opcode.ZHI, None)], True, 0.9),
    ("②k", [(Opcode.ZHIZU, (0.7, 2)),
             (Opcode.DE, 0.1), (Opcode.ZHI, None)], True, 0.1),  # 未达标累积走 止
]

exe = None
if has_cargo:
    tmp2 = tempfile.mkdtemp(prefix="i435_run_")
    gen2 = generate_rust_project("止。", os.path.join(tmp2, "proj"), strict=False)
    if gen2.get("ok"):
        try:
            exe = build_rust_exe(gen2["project_dir"])
        except RuntimeError as e:
            check("②0 cargo 构建（一次构建，多次复用）", False, str(e)[:200])
    else:
        check("②0 cargo 构建（一次构建，多次复用）", False,
              f"生成失败: {str(gen2.get('result', {}).get('errors'))[:120]}")
else:
    # issue #284：行首 SKIP 前缀（run_tests._SKIP_LINE_RE 唯一认的形态）——
    # 不得经 check() 计入 pass_n（SKIP 一律「计入通过数 0」且永不出 PASS）。
    print("SKIP  cargo 不可用 → 跳过 (2)/(3)（环境声明；Rust 面未验收，不计通过）")

if exe:
    for tag, code, want_ok, want_trust in CASES:
        p = os.path.join(tmp2, f"{tag}.pbc")
        with open(p, "wb") as f:
            f.write(serialize(code))
        r = subprocess.run([exe, "--pbc", p], capture_output=True, text=True,
                           timeout=60, encoding="utf-8", errors="replace")
        if want_ok:
            try:
                state = json.loads(r.stdout.strip().splitlines()[-1])
            except (json.JSONDecodeError, IndexError):
                state = None
            check(f"{tag} Rust 对照：有限值不误伤（trust={want_trust}）",
                  r.returncode == 0 and state is not None
                  and abs(state.get("trust", -1) - want_trust) < 1e-9,
                  f"rc={r.returncode} stdout={r.stdout.strip()[:80]!r}")
        else:
            check(f"{tag} Rust 拒（VM 执行错误 · 非有限）",
                  r.returncode != 0 and "有限" in (r.stderr or ""),
                  f"rc={r.returncode} stderr={(r.stderr or '')[:100]!r}")

print("--- (3) 双后端同判：同一手搓 .pbc 两 VM 同拒/同过 ---")

if exe:
    for tag, code, want_ok, _want_trust in CASES:
        p = os.path.join(tmp2, f"{tag}.pbc")
        try:
            run_pbc(p)
            py_exc = None
        except vmm.VMBuiltinError as e:
            py_exc = e
        except Exception as e:  # noqa: BLE001
            py_exc = e
        if want_ok:
            check(f"{tag} Python 同过（有限面等价）", py_exc is None,
                  f"{type(py_exc).__name__}: {str(py_exc)[:80]}" if py_exc else "")
        else:
            check(f"{tag} Python 同拒（nonfinite）",
                  isinstance(py_exc, vmm.VMBuiltinError)
                  and getattr(py_exc, "kind", None) == "nonfinite",
                  f"{type(py_exc).__name__}: {str(py_exc)[:80]}" if py_exc else "未拒")
else:
    if has_cargo:
        check("③ 构建失败 → 双后端面未验收", False, "")
    else:
        # issue #284：行首 SKIP 前缀（同 (2)——不冒充 PASS）
        print("SKIP  cargo 不可用 → 跳过 (3)（环境声明；双后端同判面未验收）")

print(f"\n=== issue #435 Rust 非有限闸守卫: {pass_n}/{pass_n + fail_n} 通过 ===")
sys.exit(0 if fail_n == 0 else 1)
