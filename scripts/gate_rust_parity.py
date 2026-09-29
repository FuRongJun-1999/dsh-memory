# -*- coding: utf-8 -*-
"""R-7 · 门禁腿②：逐位对拍 harness（`scripts/rank_parity.py`）——把**已有**检查接进门禁。

缺陷面（R-7）：`scripts/rank_parity.py`（Python `search_rrf` vs Rust `mdcg-eval --serve`
的**逐位**对拍）此前**不在 `npm run gate` 内**。CH-1（2026-09-29）刚把两侧词法打分口径
显式钉住并让漂移变响（`rc=3`），但「口径再次漂回去」这件事在门禁里**无人拦**——门禁
绿 ≠ 对拍绿。本脚本只做「接线」：**不新增任何检查逻辑**，口径单点仍在 `rank_parity.py`。

判据（四条，缺任一条即门禁非 0）：
  ① `rank_parity.py` 退出码 0 ⇒ 本腿通过；非 0（1=逐位劈叉 / 3=两侧口径不一致 /
     4=口径不可读）⇒ 本腿退出码 1 ⇒ `npm run gate` 非 0，并按 rc 打印可执行补救命令；
  ② release 二进制**缺失** ⇒ **自动构建补救**（`cargo build --release`）：构建成功即继续
     对拍；构建失败 ⇒ 本腿退出码 1（构建产物不该「跳过」成绿）；`--build never` 时退回
     **显式 [SKIP] 且不计入通过数**并打印补救命令；
  ③ cargo 不在位（既无产物也不能构建）⇒ **显式 [SKIP] 且不计入通过数**，打印补救命令，
     退出码 0；
  ④ 汇总行**显式记账**「计入通过数 N / 跳过 N」——SKIP 永不计入通过数。

②「自动构建」还是「在位才跑 + SKIP」：**选自动构建**（`--build auto`，缺省）。论证——
  1. **另一侧根本没有兜底（这一条是决定性的）**：容器腿 `scripts/linux_verify.sh` 与 CI
     的 `hive-check.yml` 只跑 `hive/` 那个 crate 的 `cargo test`（前者 :21、后者 :31），
     **`rust/` 全无覆盖**，release 二进制也从不在容器/CI 里构建。若本腿「无产物即 SKIP」，
     那么在一台干净 clone 上 `npm run gate` 会**全绿而对拍零覆盖**——R-7 要修的正是
     「门禁绿 ≠ 有回归保障」，SKIP 会在门禁这一层把这个洞原样留着。
     （「产物缺失另有响亮面」只对**套件**成立：CH-1 守卫
     `md_cg/test_rank_parity_score_mode.py` 缺二进制时 fail-closed 退出 1——但那条腿在
     `scripts/run_tests.py` 里，**不在门禁链里**。）
  2. **代价面可控（实测）**：`rust/Cargo.toml` 虽是 `lto=true, codegen-units=1`，
     但本 crate **零第三方依赖**、单 bin 单 lib，冷 target 的 `cargo build --release`
     实测 **7.9s**（`rust/` 内，独立 CARGO_TARGET_DIR）；且本腿只在**产物缺失时**才构建
     ——常态（产物在位）零额外代价，高频门禁不受影响。
  3. **陈旧 ≠ 静默**：产物在位但过期（源码改了没重编）时，本腿**不重建**，交给 harness
     自己按 `serve info.score` **回读**面判 `rc=4`（口径读不回来即拒绝对拍）——本腿把
     `rc=4` 记红并打印重编命令。即「陈旧」由 harness 变响，而不是被自动构建**抹平**成
     「看起来是对拍的」。

②为什么是 python 脚本而不是 package.json 里的一行 shell（**工作纪律第 15 条**）：
`rank_parity.py` 要拉起的是 rust 侧原生程序，且其输出为中文 UTF-8；经 python 包装
（argv 列表 + 显式 `encoding='utf-8'`）才能既保住中文读数、又按 rc 分支出**可执行**的
补救命令（`rc=1/3/4` 的处置各不相同）。

用法（门禁链里由 `npm run gate` 调用）：
    python scripts/gate_rust_parity.py
    python scripts/gate_rust_parity.py --exe <对拍另一侧的二进制>
    python scripts/gate_rust_parity.py --crate-dir <crate 根>   # 守卫打红探针用
    python scripts/gate_rust_parity.py --build never             # 缺产物即 SKIP（不构建）

退出码：0 = 通过或显式 SKIP（SKIP 由汇总行标注不计通过）；1 = 对拍非 0 / 自动构建失败。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_LEG = "②"
_LEG_NAME = "逐位对拍 harness"

# rc → 处置（rank_parity.py 的退出码契约，见其 docstring）
_MEANING = {
    1: "逐位劈叉",
    3: "两侧词法打分口径不一致",
    4: "rust 侧口径不可读（二进制过期，未含 CH-1 的 serve info.score 回读面）",
}
_REMEDY = {
    1: "cd rust && cargo build --release 后重跑 python scripts/rank_parity.py；"
       "仍劈叉则查两侧排序/口径是否被改回各自缺省",
    3: "查两侧钉住链：Python 侧须走 md_cg/eval_common.py::use_jaccard()、"
       "Rust 侧须显式 --score；env MDCG_SCORE_MODE 与 harness 钉住值冲突时须清掉",
    4: "cd rust && cargo build --release（重编出含 serve info.score 回读面的二进制）",
}


# 生效条件：模块级常量 _REPO 下存在 rust/target/release/mdcg-eval[.exe] 时返回其绝对路径，不存在时返回同一路径（调用方按 os.path.isfile 判缺失走 SKIP）——按平台补 .exe 后缀，与 rank_parity.py 的 --exe 缺省同源。
def _default_exe() -> str:
    return os.path.join(_REPO, "rust", "target", "release",
                        "mdcg-eval.exe" if os.name == "nt" else "mdcg-eval")


# 生效条件：给定 argv（env 在 os.environ 上叠加 PYTHONUTF8=1，cwd 固定 _REPO，shell=False、显式 encoding='utf-8'）拉起子进程，返回 (returncode, stdout+stderr)——工作纪律第 15 条：cargo 属原生 Windows 程序，必须 python 包装 + 显式解码。
def _run(argv, env=None):
    e = dict(os.environ, PYTHONUTF8="1")
    e.update(env or {})
    p = subprocess.run(argv, cwd=_REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=e)
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).rstrip()


# 生效条件：crate 根下 target/release/mdcg-eval[.exe] 的绝对路径（与 rank_parity.py 的 --exe 缺省同源）——crate 根由 --crate-dir 决定，故临时 crate（守卫探针）同样适用。
def _exe_of(crate_dir: str) -> str:
    return os.path.join(crate_dir, "target", "release",
                        "mdcg-eval.exe" if os.name == "nt" else "mdcg-eval")


def main() -> int:
    ap = argparse.ArgumentParser(description="R-7 门禁腿②：逐位对拍 harness")
    ap.add_argument("--harness", default=os.path.join(_REPO, "scripts",
                                                      "rank_parity.py"),
                    help="对拍 harness 路径（门禁用默认；守卫打红探针可换副本）")
    ap.add_argument("--crate-dir", default=os.path.join(_REPO, "rust"),
                    help="crate 根（决定缺省 --exe 与自动构建的 --manifest-path）")
    ap.add_argument("--exe", default=None,
                    help="对拍另一侧的 release 二进制（缺省 <--crate-dir>/target/release）")
    ap.add_argument("--cargo", default=os.environ.get("GATE_RUST_CARGO") or None,
                    help="cargo 可执行文件（缺省取 PATH）")
    ap.add_argument("--build", choices=("auto", "never"), default="auto",
                    help="产物缺失时的处置：auto=用 cargo 构建补救（缺省）；"
                         "never=显式 SKIP 不算通过")
    args = ap.parse_args()
    exe = args.exe or _exe_of(args.crate_dir)

    print(f"== [R-7 腿{_LEG}] {_LEG_NAME}（scripts/rank_parity.py，需 release 二进制）==")

    if not os.path.isfile(exe):
        cargo = args.cargo or shutil.which("cargo")
        if args.build == "never" or not cargo:
            why = ("--build never：产物缺失即 SKIP（外部产物模式）" if args.build == "never"
                   else "cargo 不在位：既无产物也不能构建")
            print(f"[SKIP] rust release 二进制不存在：{exe} —— {why}；本腿不计入通过数")
            print(f"       补救：cd rust && cargo build --release")
            print(f"       （自动构建需 cargo 在 PATH；本腿 --build auto 会自动构建，"
                  f"--build never 则只报缺）")
            print(f"       本腿汇总：计入通过数 0 / 跳过 1 / 退出码 0（SKIP ≠ 通过）")
            return 0
        # —— 产物缺失 ⇒ 自动构建补救（不静默跳过；构建失败即判红，不算通过）——
        manifest = os.path.join(args.crate_dir, "Cargo.toml")
        print(f"[BUILD] release 二进制不存在 ⇒ --build auto：先 cargo build --release 补救")
        print(f"        exe={exe}")
        print(f"        cargo={cargo} --manifest-path {manifest}")
        rc_b, out_b = _run([cargo, "build", "--release", "--manifest-path", manifest])
        if rc_b != 0 or not os.path.isfile(exe):
            print(f"[FAIL] 自动构建失败（rc={rc_b}）—— 门禁必须因此非 0 退出")
            for ln in out_b.splitlines()[-15:]:
                print("       | " + ln)
            print(f"       补救：cd rust && cargo build --release（先修编译错误）")
            print(f"       本腿汇总：计入通过数 0 / 跳过 0 / 退出码 1")
            return 1
        print(f"[BUILD] 构建完成（rc=0），继续对拍")
    if not os.path.isfile(args.harness):
        print(f"[SKIP] harness 不存在：{args.harness} —— 本腿不计入通过数")
        print(f"       补救：确认 scripts/rank_parity.py 在位；或手工执行"
              f"：python scripts/rank_parity.py --exe {args.exe}")
        print(f"       本腿汇总：计入通过数 0 / 跳过 1 / 退出码 0（SKIP ≠ 通过）")
        return 0

    t0 = time.time()
    rc_h, out = _run([sys.executable, "-X", "utf8", args.harness, "--exe", exe])
    dt = time.time() - t0

    if rc_h == 0:
        print(f"[PASS] rank_parity rc=0（用时 {dt:.1f}s）—— 两侧同口径逐位一致")
        for ln in out.splitlines()[-3:]:
            print("       | " + ln)
        print(f"       本腿汇总：计入通过数 1 / 跳过 0 / 退出码 0")
        return 0

    if rc_h == 2:
        # harness 自报二进制缺失（本腿前置已判在位，此处是竞态/权限面）：缺失不是通过
        print(f"[SKIP] harness 报 rust 二进制不存在（rc=2）—— 本腿不计入通过数")
        print(f"       补救：cd rust && cargo build --release")
        for ln in out.splitlines()[-5:]:
            print("       | " + ln)
        print(f"       本腿汇总：计入通过数 0 / 跳过 1 / 退出码 0（SKIP ≠ 通过）")
        return 0

    why = _MEANING.get(rc_h, "未登记退出码")
    print(f"[FAIL] rank_parity rc={rc_h}（{why}，用时 {dt:.1f}s）"
          f" —— 门禁必须因此非 0 退出")
    for ln in out.splitlines()[-20:]:
        print("       | " + ln)
    print(f"       补救：{_REMEDY.get(rc_h, '查 scripts/rank_parity.py 的退出码契约')}")
    print(f"       本腿汇总：计入通过数 0 / 跳过 0 / 退出码 1")
    return 1


if __name__ == "__main__":
    sys.exit(main())
