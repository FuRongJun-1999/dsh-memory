# -*- coding: utf-8 -*-
"""R-7 · 门禁腿①：rust crate 测试（`cargo test` @ `rust/`）——把**已有**检查接进门禁。

缺陷面（R-7）：`rust/` 的 crate 测试（`rust/src/*` 单测 + `rust/tests/*.rs` 集成探针）
此前**不在 `npm run gate` 内**——`cargo test` 只在人工手敲与容器腿（`linux_verify.sh`）
里偶发地跑过。于是 R-1/R-3 那类「Rust 侧口径漂移」修好之后**没有回归保障**：改回
缺省/改坏排序，门禁照样绿。

本脚本只做「接线」：**不新增任何检查逻辑**，只把既有的 `cargo test` 摆进门禁链。

判据（四条，缺任一条即门禁非 0）：
  ① `cargo test` 在 `rust/` 下真实执行，退出码 != 0 ⇒ 本腿退出码 1 ⇒ `npm run gate` 非 0；
  ② `cargo` 不在位 ⇒ **显式 [SKIP] 且不计入通过数**，打印可执行的补救命令，退出码 0；
  ③ 汇总行**显式记账**「计入通过数 N / 跳过 N」——SKIP 永不计入通过数；
  ④ `cargo test` rc=0 但 **0 测试**（passed 汇总为 0）⇒ 本腿退出码 1——「跑起来了却没
     测到任何用例」（用例被删/改名、manifest 被掏空）同样没有回归保障，不得计入通过
     （N257，与 N9「0 样本不构成通过」同口径）。

②为什么是 SKIP 而不是 fail-closed：本仓既有 [SKIP] 语义即先例——`scripts/
verify_discipline.py` 对未生成的 `codebuddy-local` 产物打 `[SKIP] codebuddy-local
variant=full -> 未生成：…` 后**仍报「10/10 目标一致」并退出 0**（门禁是提交前高频
动作，缺一个可选前置不该把所有人拦死）；`scripts/run_tests.py` 对裸 clone 缺依赖的
目标同样是「标 SKIP 附原因、不计失败」。故本腿沿用同一语义，但把「SKIP ≠ 通过」
写成机械可读的一行（`计入通过数 0`），杜绝「跑不起来 = 绿」。

②为什么**不做自动构建**（不 auto `cargo build`）：腿②需要 release 二进制，见
`scripts/gate_rust_parity.py` 的论证（release profile 是全仓最贵构建；二进制缺失另有
响亮面）。本腿的 `cargo test` 天然要编 **debug** 产物（零第三方依赖、增量缓存于
`rust/target/`，实测热态 ~2s），这是「跑测试」的固有代价，不构成额外取舍。

为什么是 python 脚本而不是 package.json 里的一行 shell（**工作纪律第 15 条**）：
`cargo` 是原生 Windows 程序，拉起它必须经 python 包装（argv 列表 + 显式
`encoding='utf-8', errors='replace'`）才能规避 GBK 解码异常——门禁里直接写
`cargo test` 会让失败输出在中文 Windows 上乱码，定位不到失败用例。

用法（门禁链里由 `npm run gate` 调用）：
    python scripts/gate_rust_crate_test.py
    python scripts/gate_rust_crate_test.py --cargo "C:/Users/x/.cargo/bin/cargo.exe"
    python scripts/gate_rust_crate_test.py --crate-dir <临时 crate 目录>   # 守卫打红探针用

退出码：0 = 通过或显式 SKIP（SKIP 由汇总行标注不计通过）；1 = cargo test 失败。
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_LEG = "①"
_LEG_NAME = "rust crate 测试"
_REMEDY = ("安装 Rust 工具链后重跑（https://rustup.rs）；"
           "或手工执行：cd rust && cargo test")


def main() -> int:
    ap = argparse.ArgumentParser(description="R-7 门禁腿①：rust crate 测试（cargo test）")
    ap.add_argument("--crate-dir", default=os.path.join(_REPO, "rust"),
                    help="crate 根（门禁用默认 rust/；守卫打红探针指向临时 crate）")
    ap.add_argument("--cargo", default=os.environ.get("GATE_RUST_CARGO") or None,
                    help="cargo 可执行文件（缺省取 PATH；env GATE_RUST_CARGO 可覆盖）")
    args = ap.parse_args()

    manifest = os.path.join(args.crate_dir, "Cargo.toml")
    try:                                   # crate 在**异盘**时 relpath 会 ValueError
        shown = os.path.relpath(manifest, _REPO).replace("\\", "/")
    except ValueError:                     # （--crate-dir 指向别的盘，如守卫探针）
        shown = manifest.replace("\\", "/")
    print(f"== [R-7 腿{_LEG}] {_LEG_NAME}（cargo test @ {shown}）==")

    cargo = args.cargo or shutil.which("cargo")
    if not cargo or not os.path.isfile(cargo):
        print(f"[SKIP] cargo 不在位（PATH 未命中 / --cargo={args.cargo!r}）"
              f" —— 本腿不计入通过数")
        print(f"       补救：{_REMEDY}")
        print(f"       本腿汇总：计入通过数 0 / 跳过 1 / 退出码 0（SKIP ≠ 通过）")
        return 0
    if not os.path.isfile(manifest):
        print(f"[SKIP] crate 清单不存在：{manifest} —— 本腿不计入通过数")
        print(f"       补救：确认 rust/ 未被移动；或手工执行：cd rust && cargo test")
        print(f"       本腿汇总：计入通过数 0 / 跳过 1 / 退出码 0（SKIP ≠ 通过）")
        return 0

    argv = [cargo, "test", "--manifest-path", manifest]
    env = dict(os.environ, PYTHONUTF8="1")
    t0 = time.time()
    p = subprocess.run(argv, cwd=_REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    dt = time.time() - t0
    out = (p.stdout or "") + (p.stderr or "")
    passed = sum(int(x) for x in re.findall(r"(\d+) passed", out))
    failed = sum(int(x) for x in re.findall(r"(\d+) failed", out))

    if p.returncode == 0:
        # N257（2026-10-05）：rc=0 但**零测试**不算通过——本腿的全部价值是「已有检查
        # 真的跑起来」；passed 汇总为 0 意味着没有一条用例被发现/执行（用例被删、
        # manifest 被掏空、crate 改名都会走到这里），回归保障为零，与 SKIP 一样不得
        # 计入通过（N9「0 样本不构成通过」同口径）。
        if passed == 0:
            print(f"[FAIL] cargo test rc=0 但**零测试**（0 passed）——本腿无回归保障，"
                  f"不计入通过（用时 {dt:.1f}s）")
            for ln in out.splitlines()[-15:]:
                print("       | " + ln)
            print(f"       补救：cd rust && cargo test —— 确认用例未被删除/改名")
            print(f"       本腿汇总：计入通过数 0 / 跳过 0 / 退出码 1")
            return 1
        print(f"[PASS] cargo test rc=0：{passed} passed / {failed} failed"
              f"（用时 {dt:.1f}s）")
        print(f"       本腿汇总：计入通过数 1 / 跳过 0 / 退出码 0")
        return 0

    print(f"[FAIL] cargo test rc={p.returncode}：{passed} passed / {failed} failed"
          f"（用时 {dt:.1f}s）—— 门禁必须因此非 0 退出")
    for ln in out.splitlines()[-25:]:
        print("       | " + ln)
    print(f"       补救：cd rust && cargo test（复现并定位失败用例）")
    print(f"       本腿汇总：计入通过数 0 / 跳过 0 / 退出码 1")
    return 1


if __name__ == "__main__":
    sys.exit(main())
