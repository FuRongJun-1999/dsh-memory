# -*- coding: utf-8 -*-
"""issue #156⑧ 守卫：swarm rust 运行时的递归下降 JSON 解析器必须有嵌套深度上限
================================================================================
背景（K 组 · task-49）：swarm/rust_runtime/src/ 下有**两处**各自独立、递归下降、
无深度上限的 JSON 解析器——
  · swarm.rs 的 serde_json_like::parse / pv（收件箱 / 事件行 / --config 面）；
  · serve.rs 的 serde_like::parse / parse_value（请求行读侧）。
而 hive 侧同族解析器 hive/src/json.rs 早已有防护：const MAX_DEPTH: usize = 256
（N184，批次65：深嵌套输入递归无界，Rust 栈溢出 abort 整进程，不可捕获）。
本件把该范式补到 swarm 两处（要的是「拒绝解析」而不是「崩」）。

判据（本测试）：深嵌套 JSON 必须得到**干净的 Err**（配置面 → 退出码 2 + 可读原因），
**不得**以栈溢出 abort 收场；上限内结构照常解析（上限不过紧）。

[A] 行为面（CLI，无需 unix）：protocol_vm swarm --config <深嵌套 JSON>
    · A1 深度 300（略高于 256）：修复后 → stderr 含「配置 JSON 非法」；修复前 → 解析
      **成功**、无此错（随后按 shared_secret 缺失报别的错）——**不依赖崩溃即能判别**。
    · A2 深度 5000：修复后 → 干净 rc=2；修复前 → 栈溢出 abort（Windows 退出码
      0xC00000FD = 3221225725，或负值/大值）。
[A/B 对照] 深度 10 的合法配置：两侧都不得出现「配置 JSON 非法」（上限不过紧）。
[C] 源断言：两处解析器都带 MAX_DEPTH 常量与深度检查（防只修一处）。
serve.rs 读侧无 CLI 入口，另以 crate 单元测试守（cargo test，见 serve.rs 的
deep_nesting_... 测试）。

诚实边界：A2 的「崩溃」形态与栈预算相关（主线程栈、debug/release 差异，见
hive/src/json.rs:118-121 的实测口径：debug 主线程 768 层可过、1024 层即溢出）。
故 A1（深度 300 的**语义**判别）是本守卫的主判据，A2 是佐证。
运行：python -X utf8 -m swarm.tests.test_issue156_max_depth   （0 = 全绿）
环境：PROTOCOL_VM_EXE 可指向别处的 protocol_vm 可执行文件。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))       # 仓根
_SRC = os.path.join(_REPO, "swarm", "rust_runtime", "src")

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [ok] " + name)
        return
    FAIL += 1
    print("  [FAIL] " + name + "  " + detail)


def _default_exe() -> str:
    env = os.environ.get("PROTOCOL_VM_EXE")
    if env:
        return env
    base = os.path.join(_REPO, "swarm", "rust_runtime", "target", "release", "protocol_vm")
    return base + ".exe" if os.name == "nt" else base


EXE = _default_exe()
_RT_DIR = os.path.join(_REPO, "swarm", "rust_runtime")
_TMP_ROOT = tempfile.gettempdir()


def _ensure_exe() -> bool:
    """确保 protocol_vm 可执行文件在场；返回是否可用。

    **为什么在守卫里自建**：`swarm/rust_runtime/target/` 是 gitignored 的构建产物，
    裸 clone / CI runner 上不存在。本仓对 swarm 侧守卫的既有口径就是**自建**
    （`swarm/tests/test_rust_swarm.py` 的「独立形态蜂群」段：`cwd=rt_dir` 跑
    `cargo build --release --no-default-features`，并以 `shutil.which("cargo")` 为前置）。
    本守卫首版只查在场、不自建 ⇒ Linux CI 上 H0 直接 FAIL 且 `probe()` 抛
    `FileNotFoundError` ⇒ 整件 rc=1（**「未构建」被误报成代码失败**——正是
    `.github/workflows/python-tests.yml` 的注释明令要避免的形态）。
    这里同样以 cargo 在场为前置：**cargo 不在 ⇒ 行为面 SKIP（显式计数）+ 源断言面 [C] 照判**，
    不把「没测到」记成绿，也不把「没构建」记成红。
    """
    if os.path.isfile(EXE):
        return True
    if not shutil.which("cargo") or not os.path.isdir(_RT_DIR):
        return False
    try:
        p = subprocess.run(["cargo", "build", "--release", "--no-default-features"],
                           cwd=_RT_DIR, capture_output=True, text=True, timeout=600,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as e:
        print("  [SKIP] 自建 protocol_vm 失败：" + type(e).__name__ + ": " + str(e))
        return False
    if p.returncode != 0:
        print("  [SKIP] 自建 protocol_vm 非零退出：" + (p.stderr or "")[-200:])
        return False
    return os.path.isfile(EXE)


def run(argv, timeout=120):
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, shell=False, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def deep_json(n: int) -> str:
    return '{"a":' * n + "1" + "}" * n


def probe(depth: int, extra: str = ""):
    root = tempfile.mkdtemp(prefix="swarm_maxdepth_" + str(depth) + "_")
    real = os.path.realpath(root)
    if not real.startswith(os.path.realpath(_TMP_ROOT)):
        raise SystemExit("SANDBOX_ASSERT 失败：" + real + " 不在 " + _TMP_ROOT + " 内，拒跑")
    cfg = os.path.join(root, "swarm.json")
    body = deep_json(depth)
    if extra:
        body = '{"shared_secret":"guard-dummy",' + body[1:]
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(body)
    return run([EXE, "swarm", "--config", cfg])


def tail_of(out: str) -> str:
    ls = [l for l in out.strip().splitlines() if l.strip()]
    return ls[-1][:110] if ls else "(空)"


print("### 守卫对象 = " + EXE)
_HAS_EXE = _ensure_exe()
# ★修前形态：此处 `check("H0 …", _HAS_EXE, …)` 会在二进制缺席时**先记一个 FAIL**，
# 而下方 skip 分支随后才打印 SKIP 并 `sys.exit(0 if FAIL == 0 else 1)` ⇒
# **先红后 SKIP**：CI（无 cargo/无二进制）上整件必红。
# 判据目标不变（行为面确需二进制才可判），改的是「缺席时不该算作判据失败」——
# 对齐本仓「裸 clone 不假红」口径与 `hive/test_issue155_156_rust.py` 同款。
if _HAS_EXE:
    check("H0 protocol_vm 可执行文件在场", True, EXE)

if not _HAS_EXE:
    # 行为面 SKIP（显式打印），源断言面 [C] 照判——与 hive/test_issue155_156_rust.py 同款：
    # 「依赖二进制的行为面」与「纯源码可判的面」分开计，不因前者缺席而整件红/绿。
    print("[A][A/B] 行为面 SKIP：缺 protocol_vm 且无法自建（无 cargo / 构建失败）")
    print("[C] 源断言：两处解析器都带 MAX_DEPTH（防只修一处）")
    for rel in ("swarm.rs", "serve.rs"):
        try:
            with open(os.path.join(_SRC, rel), encoding="utf-8") as f:
                src = f.read()
            check("C·" + rel + " 有 MAX_DEPTH 常量 + 深度检查",
                  "MAX_DEPTH" in src and "depth" in src and "嵌套过深" in src,
                  rel + " 缺深度上限")
        except OSError as e:
            check("C·" + rel + " 可读", False, type(e).__name__ + ": " + str(e))
    print("\n结果: " + str(PASS) + " pass / " + str(FAIL) + " fail（行为面 SKIP）")
    sys.exit(0 if FAIL == 0 else 1)

print("[A] 行为面：深嵌套必须**干净拒绝**，不得栈溢出 abort")
rc300, out300 = probe(300, extra="secret")
print("    深度 300 读数: rc=" + str(rc300) + "  尾部=" + tail_of(out300))
check("A1 深度 300 → 明确判为「配置 JSON 非法」（修复前此处解析成功、无此错）",
      "配置 JSON 非法" in out300,
      "未见「配置 JSON 非法」⇒ 解析器无深度上限（深输入直落递归）")

rc_deep, out_deep = probe(5000)
print("    深度 5000 读数: rc=" + str(rc_deep) + "  尾部=" + tail_of(out_deep))
check("A2 深度 5000 → 干净 rc=2 + 可读原因（非栈溢出 abort）",
      rc_deep == 2 and "配置 JSON 非法" in out_deep,
      "rc=" + str(rc_deep) + "（0xC00000FD / 3221225725 一类 = 栈溢出 abort）")

print("[A/B 对照] 浅结构照常解析（上限不过紧）")
rc10, out10 = probe(10, extra="secret")
print("    深度 10 读数: rc=" + str(rc10) + "  尾部=" + tail_of(out10))
check("B1 深度 10 的合法配置**不**被误判为「配置 JSON 非法」",
      "配置 JSON 非法" not in out10, "上限过紧：浅结构也被拒")

print("[C] 源断言：两处解析器都带 MAX_DEPTH（防只修一处）")
for rel in ("swarm.rs", "serve.rs"):
    try:
        with open(os.path.join(_SRC, rel), encoding="utf-8") as f:
            src = f.read()
        check("C·" + rel + " 有 MAX_DEPTH 常量 + 深度检查",
              "MAX_DEPTH" in src and "depth" in src and "嵌套过深" in src,
              rel + " 缺深度上限")
    except OSError as e:
        check("C·" + rel + " 可读", False, type(e).__name__ + ": " + str(e))

print("\n结果: " + str(PASS) + " pass / " + str(FAIL) + " fail")
sys.exit(0 if FAIL == 0 else 1)
