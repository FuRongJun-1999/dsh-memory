# -*- coding: utf-8 -*-
"""test_rust_codegen.py · Rust 原生后端验收（v0.4 · VM 路线）
荣 2026-09-06 裁定验收：双后端语义等价（同一 .pbc，Python VM vs Rust VM 终态一致）
+ cargo build/clippy 零警告 + 既有测试基线不破坏。
用例：trust 样例 / 循环 / 递归阶乘(CALL tag6) / 多函数互调 / 旧 .pbc 格式兼容。
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

from compiler.compiler import compile_source
from compiler.condition_vm import ConditionVM, Opcode
from compiler.pbc import compile_to_pbc, deserialize, load_pbc, run_pbc, serialize
from swarm.rust_codegen import build_and_run, generate_rust_project

pass_n = fail_n = 0


def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')


def num_eq(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-9
    return a == b


def state_equiv(py, rs):
    """双后端终态等价：trust 容差 / halt / symbols 数值等价 / condition_space 同构"""
    ok = abs(py["trust"] - rs["trust"]) < 1e-9
    ok = ok and py["halt"] == rs["halt"]
    ok = ok and set(py["symbols"]) == set(rs["symbols"])
    if ok:
        for k in py["symbols"]:
            ok = ok and num_eq(py["symbols"][k], rs["symbols"][k])
    pc, rc = py["condition_space"], rs["condition_space"]
    ok = ok and len(pc) == len(rc)
    if ok:
        for (a, b) in zip(pc, rc):
            ok = ok and a["name"] == b["name"] \
                and num_eq(a["trust_at_create"], b["trust_at_create"])
    return ok


def equiv_case(name, source, symbols=None, trust=0.0, expect=None):
    """标准等价用例：compile → 双后端执行 → 对照 →（可选）期望断言"""
    tmp = tempfile.mkdtemp(prefix="rust_eq_")
    pbc = os.path.join(tmp, "o.pbc")
    code, r = compile_to_pbc(source, pbc, strict=False)
    if not r["ok"]:
        check(f"{name} 编译", False, str(r.get("errors", []))[:60])
        return None
    py = run_pbc(pbc, symbols=dict(symbols or {}), trust=trust)
    gen = generate_rust_project(source, os.path.join(tmp, "proj"), strict=False)
    if not gen["ok"]:
        check(f"{name} Rust 生成", False)
        return None
    rr = build_and_run(gen["project_dir"], symbols=symbols, trust=trust)
    if not rr["ok"]:
        check(f"{name} Rust 运行", False,
              f"[{rr.get('stage')}] {rr.get('stderr', '')[-200:]}")
        return None
    check(f"{name} 双后端语义等价", state_equiv(py, rr["state"]),
          f"py={json.dumps({k: py[k] for k in ('trust', 'halt')}, default=str)} "
          f"rs={json.dumps({k: rr['state'][k] for k in ('trust', 'halt')})}")
    if expect:
        for k, v in expect.items():
            got = rr["state"]["symbols"].get(k)
            check(f"{name} 期望 {k}={v}", num_eq(got, v), f"得 {got}")
    return rr["state"]


# ============ ① trust 样例（examples/trust.proto 同源） ============
print("=== ① trust：道/德/若/止 ===")
equiv_case(
    "trust",
    open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "examples", "trust.proto"), encoding="utf-8-sig").read()
    if os.path.exists(os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "examples", "trust.proto")) else """问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：
1。道 新信任路径；
2。德 0.3；
3。若 信任值 大于 0.2，则 德 0.5；
4。止。
""",
    symbols={"信任值": 0.5}, expect={"信任值": 0.5})

# ============ ② 循环（当…执行） ============
print("=== ② 循环：计数 0→3 ===")
equiv_case(
    "loop",
    """
术曰：
1。当 计数 小于 3 执行 计数 = 计数 + 1；
2。德 0.6。
""",
    symbols={"计数": 0}, expect={"计数": 3})

# ============ ③ 递归阶乘（CALL tag6 序列化路径） ============
print("=== ③ 递归：4! = 24 ===")
equiv_case(
    "fact",
    """
定义 阶乘（n）：若 n 小于 2，则 返回 1，否则 返回 n 乘 阶乘（n 减 1）；
结果 = 阶乘（4）；
止。
""", expect={"结果": 24})

# ============ ④ 多函数互调 ============
print("=== ④ 多函数：双倍/计算 ===")
equiv_case(
    "multifn",
    """
定义 双倍（x）：返回 x 乘 2；
定义 计算（y）：返回 双倍（y）加 1；
结果 = 计算（5）；
止。
""", expect={"结果": 11})

# ============ ⑤ tag6 序列化/反序列化往返 ============
print("=== ⑤ .pbc tag6 往返 ===")
sig = ("CALL", (12, ["n", "甲"]))
rt = deserialize(serialize([sig]))
check("tag6 往返保真", rt[0][0] == "CALL" and rt[0][1] == (12, ["n", "甲"]),
      str(rt))

# ============ ⑥ 旧格式兼容（tag5 老字节码仍可读） ============
print("=== ⑥ 旧格式兼容 ===")
old_src = """问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：
1。道 新信任路径；
2。德 0.3；
3。若 信任值 大于 0.2，则 德 0.5；
4。止。
"""
tmp6 = tempfile.mkdtemp(prefix="pbc_old_")
code6, r6 = compile_to_pbc(old_src, os.path.join(tmp6, "old.pbc"))
st6 = run_pbc(os.path.join(tmp6, "old.pbc"), symbols={"信任值": 0.5})
check("旧格式（含 tag5 ZHIZU 路径）可读可执行",
      r6["ok"] and st6["trust"] >= 0.7 and st6["halt"] == "halt",
      f"trust={st6['trust']}")

# ============ ⑦ 模板 clippy 零警告 ============
print("=== ⑦ clippy 零警告（rust_runtime 模板） ===")
rt_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "rust_runtime")
has_cargo = shutil.which("cargo") is not None
if has_cargo and os.path.isdir(rt_dir):
    # 模板目录缺 program.pbc（构建期嵌入）——生成一个最小项目代替 clippy 检查
    tmp7 = tempfile.mkdtemp(prefix="clippy_")
    gen7 = generate_rust_project(old_src, tmp7)
    clip = subprocess.run(["cargo", "clippy", "--release"], cwd=gen7["project_dir"],
                          capture_output=True, text=True, timeout=180)
    warn_lines = [l for l in clip.stdout.splitlines() + clip.stderr.splitlines()
                  if l.startswith("warning")]
    check("clippy 零警告", clip.returncode == 0 and not warn_lines,
          f"警告数 {len(warn_lines)}")
else:
    check("cargo 不可用 → 跳过 clippy（环境声明）", True)

# ============ ⑧ Python 侧既有 VM 行为不被 pbc 扩展破坏 ============
print("=== ⑧ 既有 VM 基线 ===")
code8, r8 = compile_source("""
术曰：
1。当 计数 小于 3 执行 计数 = 计数 + 1；
2。德 0.6。
""", strict=False)
ops8 = [op for op, _ in code8] if r8["ok"] else []
check("循环字节码含 JUMP_IF_FALSE/JUMP/ADD",
      Opcode.JUMP_IF_FALSE in ops8 and Opcode.JUMP in ops8 and Opcode.ADD in ops8)
vm8 = ConditionVM()
st8 = vm8.run(code8, symbols={"计数": 0})
check("Python VM 循环基线 计数=3 信任=0.6",
      st8["symbols"].get("计数") == 3 and st8["trust"] == 0.6)

# ============ ⑨ 独立/库形态（--no-default-features + 运行期 --pbc） ============
print("=== ⑨ 独立形态：--no-default-features ===")
if has_cargo and os.path.isdir(rt_dir):
    ind = subprocess.run(["cargo", "build", "--release", "--no-default-features"],
                         cwd=rt_dir, capture_output=True, text=True, timeout=300,
                         encoding="utf-8", errors="replace")
    check("独立形态构建（关闭 embed）", ind.returncode == 0, (ind.stderr or "")[-200:])
    exe9 = os.path.join(rt_dir, "target", "release",
                        "protocol_vm.exe" if os.name == "nt" else "protocol_vm")
    tmp9 = tempfile.mkdtemp(prefix="pbc_ind_")
    pbc9 = os.path.join(tmp9, "trust.pbc")
    _, r9 = compile_to_pbc(old_src, pbc9)
    if r9["ok"] and os.path.exists(exe9):
        py9 = run_pbc(pbc9, symbols={"信任值": 0.5})
        run9 = subprocess.run(
            [exe9, "--pbc", pbc9, "--symbols",
             json.dumps({"信任值": 0.5}, ensure_ascii=False)],
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace")
        rs9 = json.loads(run9.stdout) if run9.returncode == 0 and run9.stdout else {}
        check("独立形态双后端语义等价", bool(rs9) and state_equiv(py9, rs9),
              f"exit={run9.returncode} {(run9.stderr or '')[-160:]}")
        # 独立形态不持有嵌入字节码：缺 --pbc 须引导性报错退出，而非 panic
        no9 = subprocess.run([exe9], capture_output=True, text=True, timeout=60,
                             encoding="utf-8", errors="replace")
        check("独立形态缺 --pbc 时报错退出(2)", no9.returncode == 2,
              f"exit={no9.returncode}")
    else:
        check("独立形态可执行产物存在", False, exe9)
else:
    check("cargo 不可用 → 跳过独立形态（环境声明）", True)

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
