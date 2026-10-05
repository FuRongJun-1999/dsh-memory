# -*- coding: utf-8 -*-
"""test_gate_rust_legs —— R-7 守卫：rust crate 测试与逐位对拍 harness **是否真在门禁内**
（且**真会变红**）。

清单声明（R-7，须独立复现）：`rust/` 的 crate 测试与 `scripts/rank_parity.py` 均**不在**
`npm run gate` 内——R-1/R-3/R-4 那类「两侧口径漂移」修好之后**没有回归保障**。本守卫
的验收判据**不是「门禁绿」**（接线前后门禁都可能绿）：而是「把已有检查接进门禁后，
**故意打红时门禁真的非 0，并指认到那条腿**」。故除结构断言外，本守卫自带**打红探针**
（`--probe`，含端到端 `npm run gate` 实测）。

断言面（每条都对应修复契约的一项）：

  G1（契约①「gate 链里确实含这两条腿」）——读 `package.json` 的 `scripts.gate`：
        ①腿①`gate_rust_crate_test.py`、腿②`gate_rust_parity.py` 各**恰好一次**在链里；
        ②链是**纯 `&&` 短路**（无 `||` / `;` / 裸 `&` 吞错——否则腿失败不会让 gate 非 0）；
        ③既有六条腿仍原样在位（新腿是**追加**，不是顶掉别人的位置）。

  G2（契约②「缺工具/缺产物不得静默绿」）——两条腿各自：
        缺 cargo（PATH 清空）：退出码 0、打印 `[SKIP]`、**可执行的补救命令**、汇总行
        **`计入通过数 0`**，且**不出现 `[PASS]`**（「跑不起来」不得记成绿色）；
        腿②另证 `--build never`（外部产物模式）下缺二进制也是同款显式 SKIP。

  G6（契约②的补救面·自动构建）——腿②在**产物缺失**时的缺省处置是 `--build auto`：
        用**真 cargo** 把临时 crate（rust/ 的构建面拷贝）构建出来继续对拍——
        ①构建成功：打印 `[BUILD]`、产物落盘、对拍仍 `逐位一致 10/10`、退出码 0；
        ②构建失败（临时 crate 注入语法错）：**非 0 退出** + `[FAIL]` + `自动构建失败`
        （构建不出来**不算通过**）。
        选「自动构建」而不选「缺产物即 SKIP」的理由见 `scripts/gate_rust_parity.py`
        头部论证（容器腿与 CI 只覆盖 `hive/` 那个 crate，`rust/` 全无覆盖；冷构建
        实测 7.9s；陈旧二进制仍由 harness 的 `rc=4` 变响）。

  G3（负向控制：SKIP 不是无条件）——前置在位时两条腿**真跑**：退出码 0、`[PASS]`、
        `计入通过数 1`；腿②的读数行须是 `逐位一致 10/10`。前置缺失时**显式 SKIP 且
        不计通过**（附原因），不以「跳过」冒充通过。

  G4（**红传导**：接了但不管用 ≡ 没接）——三条打红路径各自断言腿**非 0 退出 + 指认到
        自己**：
          ①腿①：桩 cargo（模拟 `cargo test` 失败，rc=101）⇒ 腿① 非 0 + `[FAIL]`；
          ②腿②：真二进制 + env `MDCG_SCORE_MODE=legacy`（两侧口径被拨散）⇒ 腿② 非 0
            + `[FAIL]` + `口径不一致`（CH-1 的 rc=3 报警面真被门禁接住）；
          ③腿②：桩 serve（`info.score=legacy`，不依赖真二进制）⇒ 同上（无 rust 工具链的
            环境也能跑出这条辨别力）。

  G5（契约③「注释订正 + CH-1 守卫锚点判别力未被削弱」）：
        ①从 `md_cg/test_rank_parity_score_mode.py` **源码抽出** `_RUST_CFG_DEFAULT_ANCHOR`
          字面量，断言它在 `rust/src/main.rs` 里**仍能命中**（锚点未成孤儿 = CH-1 的 G3k
          仍有判据面）；`_PY_DEFAULT_ANCHOR` 同法对 `md_cg/mdcg.py`；
        ②失实原话（整句字面量）**已不在** `main.rs`；
        ③订正后的**事实**在注释里（`Python 侧产品缺省是 legacy` + `与 Python 缺省不一致`）；
        ④**同一失实断言在 `main.rs` 头注释（`:13-14`）的第二处**也一并订正并钉住——
          契约 ③ 只点名 `:99` 那一处，但两处是同一句话的同一失实断言（`优化第二批`
          报告 §6.2 已点其为陈化文案），故本守卫对**两处**都断言「旧话不在 + 新话在」。

  `--probe`（**本项真正的验收判据**）：真造一次可控红 → 断言门禁非 0 且指认到腿 →
  还原 → 复跑绿。步骤：
        P1 腿①真红：临时 crate 内放一个必失败用例，用**真 cargo** 跑腿① ⇒ 非 0 + `[FAIL]`；
        P1b 腿①真红**经门禁链短路**：`GATE_RUST_CARGO` 指向桩 cargo（`cargo test` 必失败），
           用**取自 `package.json` 的门禁链尾**（同一 `&&` 语义）复跑 ⇒ 非 0 + 腿①`[FAIL]`
           + **腿②段不存在**（证明短路确实吃掉后续腿，腿①的失败真的能让门禁非 0）；
        P2 腿②真红：真二进制 + env 口径冲突 ⇒ 非 0 + `口径不一致`；
        P3 端到端：真 `npm run gate` + 同一 env ⇒ **gate 非 0** 且输出含腿②`[FAIL]`标记；
           若门禁在**更早的腿**就被判红（本批并发改动留下的未追踪件会让
           `check_publish_artifact` 的 R4 判红，链根本到不了腿②）⇒ 退到**链尾**
           （`package.json` 链里自腿①起的条目，同一 `&&` 短路语义）复跑同一注入，
           并把门禁旁的既有红项**如实打印**为「非本探针」；
        P4 还原：链尾**不带** env ⇒ 退出码 0、两腿都 `[PASS]`（红是那条腿造成的，
           不是常年红）；P4b 另跑真门禁整体，若它因**别的腿**判红则 NOTE 如实披露
           （不当作自己通过，也不冒充绿）。
        前置缺失（无 npm / 无二进制 / 无 cargo）的步骤**显式 SKIP 并附原因**，不计通过。

  `--mutate`（定点变异自证）：把修复点逐条改回缺陷形态（gate 链去掉一条腿 / 链上挂
  `|| true` / SKIP 记成 PASS / 失败不传非 0 / main.rs 注释改回失实原文 / main.rs 锚点
  漂移），断言**恰好**命中预期条数。锚点找不到 = **ANCHOR-MISS 退出 2**（fail-closed，
  实现改了却没同步本表即硬失败，不得静默跳过）。

基线纪律：本守卫**不以 git HEAD（或任何提交快照）为基线源**——「修前形态」全部由在
**当前工作区源码/产物**上做定点文本变异得到（`_MUTATIONS`），变异副本写入本守卫的
临时目录，**不进仓库工作区、不改在役数据根**（库根一律 `tempfile.mkdtemp`）。

运行：
    python -X utf8 scripts/test_gate_rust_legs.py              # 断言组
    python -X utf8 scripts/test_gate_rust_legs.py --probe      # 打红探针（含真门禁）
    python -X utf8 scripts/test_gate_rust_legs.py --mutate     # 定点变异自证

退出码：0 = 全绿；1 = 有断言失败 / 变异未按预期转红；2 = ANCHOR-MISS（锚点漂移）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 被测面（**可替换**：变异模式换成临时目录里的变异副本，断言一律经 F 取，不闭包捕获
# 原路径，否则变异对断言不可见）
F = {
    "pkg": os.path.join(_REPO, "package.json"),
    "main_rs": os.path.join(_REPO, "rust", "src", "main.rs"),
    "ch1": os.path.join(_REPO, "md_cg", "test_rank_parity_score_mode.py"),
    "mdcg": os.path.join(_REPO, "md_cg", "mdcg.py"),
    "leg1": os.path.join(_REPO, "scripts", "gate_rust_crate_test.py"),
    "leg2": os.path.join(_REPO, "scripts", "gate_rust_parity.py"),
}
_LIVE = dict(F)

_LEG1 = "python scripts/gate_rust_crate_test.py"
_LEG2 = "python scripts/gate_rust_parity.py"
_LEGS = (_LEG1, _LEG2)
# 既有六条腿（追加新腿不得顶掉它们）。A2（2026-10-05 使用者裁决）：discipline 腿自本轮起
# 显式携带认知图 root（`--cg-root .tmp/discipline-cg`，root 缺失即 fail-closed）——值仍
# 逐字取自 package.json gate 链，腿被顶掉/被改写都仍会在此点名。
_OLD_LEGS = ("python scripts/check_unreachable.py",
             "python scripts/check_publish_artifact.py",
             "python scripts/cogmap_sync.py check",
             "python scripts/link_check.py",
             "python scripts/workspace_index.py --check",
             "python scripts/verify_discipline.py --allow-missing --cg-root .tmp/discipline-cg")

_EXE = os.path.join(_REPO, "rust", "target", "release",
                    "mdcg-eval.exe" if os.name == "nt" else "mdcg-eval")
_RUST_DIR = os.path.join(_REPO, "rust")

_TMP = tempfile.mkdtemp(prefix="r7_gate_")

# 订正后的**事实**在 main.rs 注释里的跨行唯一字面量（G5e 的判据；见 G5e 处说明）
_CORRECTED_FACT = ("与 Python 缺省不一致**——Python 侧产品\n"
                   "        // 缺省是 legacy（md_cg/mdcg.py:SCORE_MODE")
# 头注释（`:13-14`）那一处的订正事实（G5g 的判据；同上，跨行唯一）
_CORRECTED_FACT_DOC = ("（**Rust 侧**缺省 `jaccard`；注意它与\n"
                       "//!     Python 侧产品缺省 `legacy`")
# 两处共用的**失实原话**片段（单点常量：任一处回潮即命中）
_FALSE_CLAIM = "SCORE_MODE 缺省一致"

_PASS: list = []
_FAIL: list = []
_SKIP: list = []


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))
    return bool(cond)


def skip(msg):
    _SKIP.append(msg)
    print("  SKIP(未跑·不计通过) " + msg)


def _read(path):
    return open(path, encoding="utf-8").read()


def _env(extra=None):
    env = dict(os.environ, PYTHONUTF8="1")
    env.pop("MDCG_SCORE_MODE", None)          # 缺省态：口径 env 必须干净
    env.update(extra or {})
    return env


# 生效条件：给定 argv/env/cwd 后拉起子进程；TimeoutExpired 时返回 (-1, "超时…")，否则返回 (returncode, stdout+stderr)——调用方按 rc 断言，绝不把「跑不起来」当通过。
def _run(argv, env=None, cwd=_REPO, timeout=900):
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           env=env or _env(), timeout=timeout)
    except subprocess.TimeoutExpired:
        return -1, "超时（>%ds）：%s" % (timeout, " ".join(argv))
    return p.returncode, ((p.stdout or "") + (p.stderr or ""))


def _leg1_run(args=(), env=None, leg=None):
    return _run([sys.executable, "-X", "utf8", leg or F["leg1"],
                 "--crate-dir", _RUST_DIR] + list(args), env=env)


def _leg2_run(args=(), env=None, leg=None):
    return _run([sys.executable, "-X", "utf8", leg or F["leg2"],
                 "--harness", os.path.join(_REPO, "scripts", "rank_parity.py")]
                + list(args), env=env)


# 生效条件：从 package.json 的 gate 链里取**自腿①起**的尾部条目（腿①+腿②），用同一条 `&&` 短路语义经系统 shell 执行，返回 (rc, out)——门禁被**更早的腿**（并发改动面）判红时的等价复跑通道，判据与真门禁链尾逐字同源（命令取自 package.json，不另抄一份）。
def _chain_tail(env=None):
    gate = json.loads(_read(F["pkg"]))["scripts"]["gate"]
    entries = [e.strip() for e in gate.split("&&")]
    i = entries.index(_LEG1)
    line = " && ".join(entries[i:])
    argv = (["cmd", "/c", line] if os.name == "nt" else ["sh", "-c", line])
    return _run(argv, env=env)


# ------------------------------------------------------------------ 桩件
# 生效条件：在目录 d 下写出 name.py 与其启动器（Windows=.cmd / POSIX=.sh，透传退出码），返回启动器路径——给「打红探针」造一个可控的假工具/假产物（真红仍走真工具，见 --probe）。
def _stub(d, name, body):
    py = os.path.join(d, name + ".py")
    with open(py, "w", encoding="utf-8") as f:
        f.write(body)
    if os.name == "nt":
        launcher = os.path.join(d, name + ".cmd")
        with open(launcher, "w", encoding="utf-8", newline="") as f:
            f.write('@echo off\r\n"%s" "%s" %%*\r\nexit /b %%ERRORLEVEL%%\r\n'
                    % (sys.executable, py))
    else:
        launcher = os.path.join(d, name + ".sh")
        with open(launcher, "w", encoding="utf-8") as f:
            f.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, py))
        os.chmod(launcher, 0o755)
    return launcher


_STUB_CARGO = (
    "import sys\n"
    "print('   Compiling mdcg-eval v0.2.0 (stub)')\n"
    "print('test result: FAILED. 1 passed; 1 failed; 0 ignored')\n"
    "sys.exit(101)\n"
)

_STUB_SERVE = (
    "import sys, json\n"
    "for line in sys.stdin:\n"
    "    line = line.strip()\n"
    "    if not line:\n"
    "        continue\n"
    "    req = json.loads(line)\n"
    "    if req.get('op') == 'info':\n"
    "        resp = {'ok': True, 'root': 'stub', 'docs': 0, 'score': 'legacy'}\n"
    "    else:\n"
    "        resp = {'ok': True, 'hits': []}\n"
    "    sys.stdout.write(json.dumps(resp) + '\\n')\n"
    "    sys.stdout.flush()\n"
)


# ================================================================ G1 契约①
def g1():
    print("== G1 契约①：gate 链里确实含这两条腿（且是纯 && 短路）==")
    try:
        gate = json.loads(_read(F["pkg"]))["scripts"]["gate"]
    except Exception as exc:                                # noqa: BLE001
        ok(False, "G1 前置：package.json 可读且含 scripts.gate", exc)
        return
    entries = [e.strip() for e in gate.split("&&")]
    ok(_LEG1 in entries, "G1a gate 链含腿①（rust crate 测试）", gate)
    ok(_LEG2 in entries, "G1b gate 链含腿②（逐位对拍 harness）", gate)
    ok(gate.count(_LEG1) == 1 and gate.count(_LEG2) == 1,
       "G1c 两条腿各**恰好一次**（不重复计、不空转）",
       (gate.count(_LEG1), gate.count(_LEG2)))
    ok("||" not in gate and ";" not in gate and "&" not in gate.replace("&&", ""),
       "G1d 链是**纯 `&&` 短路**：无 `|| ` / `;` / 裸 `&` 吞错——任一条腿非 0 即 gate 非 0",
       gate)
    miss = [e for e in _OLD_LEGS if e not in entries]
    ok(not miss, "G1e 既有六条腿仍原样在位（新腿是追加，不顶掉别人）", miss)


# ================================================================ G2 契约② SKIP
def g2():
    print("== G2 契约②：缺工具/缺产物 = 显式 SKIP + 不计通过 + 补救命令 ==")
    # ①腿①：cargo 不在位（PATH 清空 = 真实现场形态）
    rc, out = _leg1_run(env=_env({"PATH": ""}))
    ok(rc == 0, "G2a 腿①缺 cargo：退出码 0（SKIP 不拦死门禁）", "rc=%s out=%s" % (rc, out[-300:]))
    ok("[SKIP]" in out, "G2b 腿①缺 cargo：显式 [SKIP]（不静默通过）", out[-300:])
    ok("计入通过数 0" in out, "G2c 腿①缺 cargo：汇总**不计入通过数**（SKIP ≠ 通过）", out[-300:])
    ok("[PASS]" not in out, "G2d 腿①缺 cargo：**不出现 [PASS]**（跑不起来不得记绿）", out[-300:])
    ok("cargo test" in out, "G2e 腿①缺 cargo：打印可执行补救命令（cd rust && cargo test）",
       out[-300:])
    # ②腿②：release 二进制不存在 + --build never（**外部产物模式**：不代构建，只报缺）
    rc, out = _leg2_run(["--exe", os.path.join(_TMP, "no_such_mdcg_eval"),
                         "--build", "never"])
    ok(rc == 0, "G2f 腿②缺二进制（--build never）：退出码 0", "rc=%s out=%s" % (rc, out[-300:]))
    ok("[SKIP]" in out, "G2g 腿②缺二进制：显式 [SKIP]", out[-300:])
    ok("计入通过数 0" in out, "G2h 腿②缺二进制：汇总**不计入通过数**", out[-300:])
    ok("[PASS]" not in out, "G2i 腿②缺二进制：**不出现 [PASS]**", out[-300:])
    ok("cargo build --release" in out, "G2j 腿②缺二进制：打印补救命令（cd rust && cargo build --release）",
       out[-300:])
    # ③腿②：cargo 不在位（缺工具）—— 既无产物也不能构建 ⇒ 同样显式 SKIP、不计通过
    rc, out = _leg2_run(["--exe", os.path.join(_TMP, "no_such_mdcg_eval")],
                        env=_env({"PATH": ""}))
    ok(rc == 0 and "[SKIP]" in out and "计入通过数 0" in out and "[PASS]" not in out,
       "G2k 腿②缺 cargo（--build auto）：显式 [SKIP]、不计通过、不出 [PASS]",
       "rc=%s out=%s" % (rc, out[-300:]))
    ok("cargo 不在位" in out, "G2l 腿②缺 cargo：SKIP 理由写明「cargo 不在位」", out[-300:])


# ================================================================ G3 正向控制
def g3():
    print("== G3 负向控制：前置在位时两条腿真跑（SKIP 不是无条件）==")
    cargo = shutil.which("cargo") or os.environ.get("GATE_RUST_CARGO")
    if cargo:
        rc, out = _leg1_run()
        ok(rc == 0, "G3a 腿①真跑：退出码 0", "rc=%s out=%s" % (rc, out[-300:]))
        ok("[PASS]" in out, "G3b 腿①真跑：打印 [PASS]", out[-300:])
        ok("计入通过数 1" in out, "G3c 腿①真跑：计入通过数 1（与 SKIP 的 0 形成对照）", out[-300:])
        ok("failed" in out, "G3d 腿①真跑：汇报 cargo test 读数（passed/failed）", out[-200:])
    else:
        skip("G3a-d 腿①真跑（cargo 不在 PATH）—— 修复：安装 Rust 工具链后重跑")
    if os.path.isfile(_EXE):
        rc, out = _leg2_run(["--exe", _EXE])
        ok(rc == 0, "G3e 腿②真跑：退出码 0", "rc=%s out=%s" % (rc, out[-300:]))
        ok("[PASS]" in out, "G3f 腿②真跑：打印 [PASS]", out[-300:])
        ok("计入通过数 1" in out, "G3g 腿②真跑：计入通过数 1", out[-300:])
        ok("逐位一致 10/10" in out, "G3h 腿②真跑：读数行 = 逐位一致 10/10（CH-1 接线后的基线）",
           out[-300:])
    else:
        skip("G3e-h 腿②真跑（release 二进制缺失）—— 修复：cd rust && cargo build --release")


# ================================================================ G4 红传导
def g4():
    print("== G4 红传导：腿失败必须非 0 退出并指认到那条腿（接了不管用 ≡ 没接）==")
    # ①腿①：桩 cargo（模拟 cargo test 失败）
    stub = _stub(_TMP, "stub_cargo_fail", _STUB_CARGO)
    rc, out = _leg1_run(["--cargo", stub])
    ok(rc != 0, "G4a 腿①cargo test 失败 ⇒ 腿**非 0 退出**（gate 才会红）",
       "rc=%s out=%s" % (rc, out[-300:]))
    ok("[FAIL]" in out, "G4b 腿①失败：打印 [FAIL]（指认到腿①）", out[-300:])
    ok("计入通过数 0" in out, "G4c 腿①失败：不计入通过数", out[-300:])
    ok("cargo test" in out and "补救" in out, "G4d 腿①失败：打印补救命令", out[-300:])
    # ②腿②：真二进制 + 口径 env 冲突（CH-1 报警面）
    if os.path.isfile(_EXE):
        rc, out = _leg2_run(["--exe", _EXE], env=_env({"MDCG_SCORE_MODE": "legacy"}))
        ok(rc != 0, "G4e 腿②两侧口径漂移 ⇒ 腿**非 0 退出**",
           "rc=%s out=%s" % (rc, out[-400:]))
        ok("[FAIL]" in out, "G4f 腿②漂移：打印 [FAIL]（指认到腿②）", out[-400:])
        ok("口径不一致" in out, "G4g 腿②漂移：透出 CH-1 的「口径不一致」判定", out[-400:])
        ok("eval_common" in out, "G4h 腿②漂移：补救命令直指两侧钉住链", out[-400:])
    else:
        skip("G4e-h 腿②漂移（真二进制缺失）—— 修复：cd rust && cargo build --release")
    # ③腿②：桩 serve（info 报 legacy）——不依赖真二进制/工具链
    stub_serve = _stub(_TMP, "stub_serve_legacy", _STUB_SERVE)
    rc, out = _leg2_run(["--exe", stub_serve])
    ok(rc != 0, "G4i 腿②（桩 serve 报 legacy）⇒ 腿**非 0 退出**",
       "rc=%s out=%s" % (rc, out[-400:]))
    ok("[FAIL]" in out and "口径不一致" in out,
       "G4j 腿②桩 serve：打印 [FAIL] + 口径不一致", out[-400:])


# ================================================================ G6 缺产物的补救面
def _temp_crate(name, broken=False):
    """把 rust/ 的构建面（Cargo.toml/lock + src/）拷到守卫临时目录（不动工作区）。

    broken=True 时在 lib.rs 尾部制造语法错——用来验证「自动构建失败 ⇒ 判红」。
    """
    d = tempfile.mkdtemp(prefix="r7_" + name + "_", dir=_TMP)
    for rel in ("Cargo.toml", "Cargo.lock"):
        src = os.path.join(_RUST_DIR, rel)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(d, rel))
    shutil.copytree(os.path.join(_RUST_DIR, "src"), os.path.join(d, "src"))
    if broken:
        with open(os.path.join(d, "src", "lib.rs"), "a", encoding="utf-8") as f:
            f.write("\nfn r7_probe_broken( { \n")
    return d


def g6():
    print("== G6 缺产物的补救面：自动构建（补救成功即继续；构建失败即判红）==")
    if not (shutil.which("cargo") or os.environ.get("GATE_RUST_CARGO")):
        skip("G6 自动构建（cargo 不在 PATH）—— 修复：安装 Rust 工具链后重跑")
        return
    d = _temp_crate("ok")
    rc, out = _leg2_run(["--crate-dir", d])
    exe_built = os.path.isfile(os.path.join(d, "target", "release",
                                            "mdcg-eval.exe" if os.name == "nt"
                                            else "mdcg-eval"))
    ok(rc == 0, "G6a 缺产物 ⇒ 自动构建后对拍通过（rc=0）",
       "rc=%s out=%s" % (rc, out[-400:]))
    ok("[BUILD]" in out, "G6b 打印自动构建动作（[BUILD]，不静默跳过）", out[-400:])
    ok(exe_built, "G6c 构建产物确实落盘（<crate>/target/release/mdcg-eval）", out[-400:])
    ok("逐位一致 10/10" in out, "G6d 用**新构建**的二进制对拍仍 10/10", out[-400:])
    db = _temp_crate("broken", broken=True)
    rc, out = _leg2_run(["--crate-dir", db])
    ok(rc != 0, "G6e 自动构建失败 ⇒ 本腿**非 0 退出**（构建不出来不算通过）",
       "rc=%s out=%s" % (rc, out[-400:]))
    ok("[FAIL]" in out and "自动构建失败" in out, "G6f 打印 [FAIL] + 自动构建失败",
       out[-400:])


# ================================================================ G5 契约③
def g5():
    print("== G5 契约③：注释订正到位 + CH-1 守卫锚点判别力未被削弱 ==")
    ch1 = _read(F["ch1"])
    main_rs = _read(F["main_rs"])
    m = None
    for line in ch1.splitlines():
        if line.startswith("_RUST_CFG_DEFAULT_ANCHOR = "):
            m = line.split("=", 1)[1].strip().strip('"')
    ok(bool(m), "G5a 从 CH-1 守卫源码抽出 _RUST_CFG_DEFAULT_ANCHOR 字面量", m)
    ok(bool(m) and m in main_rs,
       "G5b 该锚点在 rust/src/main.rs 里**仍能命中**（锚点未成孤儿 ⇒ CH-1 的 G3k 仍有判据面）",
       m)
    mp = None
    for line in ch1.splitlines():
        if line.startswith("_PY_DEFAULT_ANCHOR = "):
            mp = line.split("=", 1)[1].strip().strip("'\"")
    ok(bool(mp) and mp in _read(F["mdcg"]),
       "G5c Python 侧负向锚点（_PY_DEFAULT_ANCHOR）对 md_cg/mdcg.py 仍能命中", mp)
    old = "缺省 jaccard（长度自惩罚），与 Python SCORE_MODE 缺省一致"
    ok(old not in main_rs,
       "G5d 失实原话（整句字面量）**已不在** main.rs（该注与事实相反）")
    # 跨行取字面量（且**必须唯一**）：`缺省是 legacy（…` 在 main.rs 里另有一处
    # （CLI --score 的说明文字），单行锚会退化成「别处还在就算过」的空转判据。
    ok(_CORRECTED_FACT in main_rs,
       "G5e 订正后的事实写在注释里：Rust 缺省与 Python 缺省不一致，后者是 legacy"
       "（跨行唯一锚点）", _CORRECTED_FACT)
    ok("与 Python 缺省不一致" in main_rs,
       "G5c2 订正后的结论明确：Rust 缺省「与 Python 缺省不一致」")
    # 头注释（:13-14）那一处：契约 ③ 只点名 :99，但两处是同一失实断言（同一句话的
    # 第二份拷贝，见 `docs/eval/优化第二批…v1.0.md` §6.2 陈化文案清单）——一并钉住，
    # 否则「订正了 :99」也能与头注释自相矛盾地长期共存。
    ok(_FALSE_CLAIM not in main_rs,
       "G5f 失实片段「SCORE_MODE 缺省一致」在 main.rs **全文件**已清零"
       "（:99 与头注释 :13-14 两处）")
    ok(_CORRECTED_FACT_DOC in main_rs,
       "G5g 头注释已订正为事实：Rust 侧缺省 jaccard 与 Python 侧产品缺省 legacy 不一致"
       "（跨行唯一锚点）", _CORRECTED_FACT_DOC)


# ================================================================ 打红探针
def _probe() -> int:
    print("!! R-7 打红探针：真造一次可控红 → 断言门禁非 0 且指认到那条腿 → 还原 → 复跑绿\n")
    bad = []

    def _leg_markers(out, leg):
        """腿在 gate 输出里被点名的形态（[PASS] / [FAIL] / [SKIP] + 计数行）。"""
        tail = out.split(leg)[-1] if leg in out else ""   # 该腿的整段输出（到链尾）
        return {"seen": leg in out and "计入通过数" in tail,
                "pass": "[PASS]" in tail, "fail": "[FAIL]" in tail,
                "skip": "[SKIP]" in tail}

    def _foreign(out):
        """门禁里**不是本探针**造成的红（本批并发改动面）：逐条打印以便如实披露。"""
        return [l.strip() for l in out.splitlines()
                if l.strip().startswith("[FAIL]") or "VERDICT=FAIL" in l
                or l.strip().startswith("FAIL 规则数")]

    # ---- P1 腿①真红：临时 crate 内的必失败用例（真 cargo，不动仓库工作区）----
    cargo = shutil.which("cargo") or os.environ.get("GATE_RUST_CARGO")
    if not cargo:
        skip("P1 腿①真红（cargo 不在 PATH）—— 修复：安装 Rust 工具链后重跑")
    else:
        d = tempfile.mkdtemp(prefix="r7_probe_crate_", dir=_TMP)
        with open(os.path.join(d, "Cargo.toml"), "w", encoding="utf-8") as f:
            f.write('[package]\nname = "r7_probe"\nversion = "0.0.1"\n'
                    'edition = "2021"\n\n[dependencies]\n')
        os.makedirs(os.path.join(d, "src"), exist_ok=True)
        with open(os.path.join(d, "src", "lib.rs"), "w", encoding="utf-8") as f:
            f.write("#[test]\nfn r7_probe_must_fail() {\n    assert_eq!(1, 2);\n}\n")
        rc, out = _leg1_run(["--cargo", cargo, "--crate-dir", d])
        good = rc != 0 and "[FAIL]" in out
        print("  %s P1 腿①真红（真 cargo，临时 crate 内必失败用例）：rc=%s"
              % ("OK  " if good else "MISS", rc))
        if not good:
            bad.append("P1 腿①真红 rc=%s" % rc)
            print("      " + "\n      ".join(out.splitlines()[-8:]))
        shutil.rmtree(d, ignore_errors=True)

    # ---- P1b 腿①真红**经门禁链**（`GATE_RUST_CARGO` 桩 ⇒ 链尾同一 `&&` 语义短路）----
    stub_gate = _stub(_TMP, "stub_cargo_gate", _STUB_CARGO)
    rc, out = _chain_tail(_env({"GATE_RUST_CARGO": stub_gate}))
    m1 = _leg_markers(out, "[R-7 腿①]")
    good = rc != 0 and m1["seen"] and m1["fail"] and "[R-7 腿②]" not in out
    print("  %s P1b 腿①经门禁链（桩 cargo 进 GATE_RUST_CARGO，链尾复跑）：rc=%s；"
          "腿①[FAIL]=%s；腿②未被跑到=%s"
          % ("OK  " if good else "MISS", rc, m1["fail"], "[R-7 腿②]" not in out))
    if not good:
        bad.append("P1b 腿①经门禁链 rc=%s marker=%s" % (rc, m1))
        print("      " + "\n      ".join(out.splitlines()[-10:]))

    # ---- P2 腿②真红：真二进制 + env 口径冲突 ----
    if not os.path.isfile(_EXE):
        skip("P2 腿②真红（release 二进制缺失）—— 修复：cd rust && cargo build --release")
    else:
        rc, out = _leg2_run(["--exe", _EXE], env=_env({"MDCG_SCORE_MODE": "legacy"}))
        good = rc != 0 and "[FAIL]" in out and "口径不一致" in out
        print("  %s P2 腿②真红（真二进制 + env MDCG_SCORE_MODE=legacy）：rc=%s"
              % ("OK  " if good else "MISS", rc))
        if not good:
            bad.append("P2 腿②真红 rc=%s" % rc)
            print("      " + "\n      ".join(out.splitlines()[-8:]))

    # ---- P3/P4 端到端：真 npm run gate（红 → 还原 → 绿）----
    npm = shutil.which("npm")
    need = (os.path.isfile(_EXE), bool(npm))
    if not all(need):
        skip("P3/P4 端到端 npm run gate（缺 %s）—— 修复：装 node/npm 或 "
             "cd rust && cargo build --release"
             % ("npm" if not npm else "release 二进制"))
        print("\n打红探针：%s" % ("PASS（红确实由接进来的腿造成）"
                                  if not bad else "FAIL —— " + "、".join(bad)))
        return 0 if not bad else 1
    argv = (["cmd", "/c", "npm", "run", "gate"] if os.name == "nt"
            else ["npm", "run", "gate"])

    # P3：真门禁 + 口径冲突 ⇒ 必须非 0 且**指认到腿②**
    t0 = time.time()
    rc_red, out_red = _run(argv, env=_env({"MDCG_SCORE_MODE": "legacy"}))
    dt = time.time() - t0
    m2 = _leg_markers(out_red, "[R-7 腿②]")
    if not m2["seen"]:
        # 门禁在**更早的腿**就中断（并发工作流留下的未追踪件会让 check_publish_artifact
        # 的 R4 判红）⇒ 退到「链尾两条腿」同语义复跑，仍按 `&&` 短路判红，并如实标注。
        print("  !! 真门禁未到达腿②（更早的腿已判红，%.1fs）—— 退到**链尾**复跑同一注入"
              % dt)
        for l in _foreign(out_red)[:6]:
            print("       门禁旁的既有红项（非本探针）：" + l)
        t0 = time.time()
        rc_red, out_red = _chain_tail(_env({"MDCG_SCORE_MODE": "legacy"}))
        dt = time.time() - t0
        m2 = _leg_markers(out_red, "[R-7 腿②]")
        label = "链尾"
    else:
        label = "真门禁"
    good = rc_red != 0 and m2["seen"] and m2["fail"] and "口径不一致" in out_red
    print("  %s P3 端到端（%s）：口径冲突 ⇒ rc=%s（%.1fs）；腿②[FAIL]标记=%s"
          % ("OK  " if good else "MISS", label, rc_red, dt, m2["fail"]))
    if not good:
        bad.append("P3 端到端红 rc=%s marker=%s" % (rc_red, m2))
        print("      " + "\n      ".join(out_red.splitlines()[-12:]))

    # P4：还原（去掉口径 env）⇒ 两条腿必须回到 [PASS]、链尾退出码 0
    t0 = time.time()
    rc_g, out_g = _chain_tail(_env())
    dt = time.time() - t0
    m1g, m2g = _leg_markers(out_g, "[R-7 腿①]"), _leg_markers(out_g, "[R-7 腿②]")
    good = rc_g == 0 and m1g["pass"] and m2g["pass"]
    print("  %s P4 还原后复跑（链尾，无口径 env）⇒ rc=%s（%.1fs）；"
          "腿①[PASS]=%s 腿②[PASS]=%s" % ("OK  " if good else "MISS", rc_g, dt,
                                           m1g["pass"], m2g["pass"]))
    if not good:
        bad.append("P4 还原复跑绿 rc=%s m1=%s m2=%s" % (rc_g, m1g, m2g))
        print("      " + "\n      ".join(out_g.splitlines()[-12:]))
    # P4b：真门禁整体（若因**别的腿**判红，如实披露，不当作自己通过）
    t0 = time.time()
    rc_f, out_f = _run(argv, env=_env())
    dt = time.time() - t0
    f = _foreign(out_f)
    if rc_f == 0:
        print("  OK   P4b 真门禁整体（无口径 env）：rc=0（两条腿都在链尾 [PASS]）")
    else:
        print("  NOTE P4b 真门禁整体：rc=%s —— 红项**不属于本探针**（本批并发改动面）："
              % rc_f)
        for l in f[:8]:
            print("       " + l)
        print("       （链尾两条腿自身仍是绿的，见 P4；本项不判红，仅如实披露）")

    print("\n打红探针：%s" % ("PASS（红确实由接进来的腿造成，还原后门禁回绿）"
                              if not bad else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


# ================================================================ 变异表
# 每条 = (名称, 被测面 key, 源码锚点, 替换文本, 预期转红条数)。
# 锚点必须逐字命中当前源码（找不到 → ANCHOR-MISS → 退出码 2，fail-closed）。
_MUTATIONS = (
    ("R-7 gate 链去掉腿①（rust crate 测试）",
     "pkg", " && " + _LEG1, "", 2),
    ("R-7 gate 链去掉腿②（逐位对拍 harness）",
     "pkg", " && " + _LEG2, "", 2),
    ("R-7 gate 链挂 `|| true` 吞掉腿②的失败",
     "pkg", " && " + _LEG2, " && " + _LEG2 + " || true", 2),
    ("R-7 腿①把 SKIP 当 PASS（静默绿）",
     "leg1", "[SKIP] cargo 不在位", "[PASS] cargo 不在位", 2),
    ("R-7 腿①失败不传非 0（return 1 → return 0）",
     "leg1", '跳过 0 / 退出码 1")\n    return 1',
     '跳过 0 / 退出码 1")\n    return 0', 1),
    ("R-7 腿②失败不传非 0（return 1 → return 0）", "leg2",
     '跳过 0 / 退出码 1")\n    return 1', '跳过 0 / 退出码 1")\n    return 0', 2),
    ("R-7 腿②缺产物静默跳过（撤掉自动构建补救）", "leg2",
     '        if args.build == "never" or not cargo:',
     "        if True:  # MUT：不再构建，缺产物一律静默跳过", 5),
    ("R-7 腿②自动构建失败不判红（return 1 → return 0）", "leg2",
     '            print(f"       补救：cd rust && cargo build --release（先修编译错误）")\n'
     '            print(f"       本腿汇总：计入通过数 0 / 跳过 0 / 退出码 1")\n'
     "            return 1",
     '            print(f"       补救：cd rust && cargo build --release（先修编译错误）")\n'
     '            print(f"       本腿汇总：计入通过数 0 / 跳过 0 / 退出码 1")\n'
     "            return 0", 1),
    ("R-7 main.rs 注释改回失实原文",
     "main_rs",
     "        // 缺省 jaccard（长度自惩罚）。**注意：与 Python 缺省不一致**——Python 侧产品\n",
     "        // 缺省 jaccard（长度自惩罚），与 Python SCORE_MODE 缺省一致\n",
     4),
    ("R-7 main.rs 删掉「Python 缺省是 legacy」的事实行",
     "main_rs",
     "        // 缺省是 legacy（md_cg/mdcg.py:SCORE_MODE，|qb∩db|/|qb|），两侧缺省本就不同\n",
     "", 1),
    ("R-7 main.rs 头注释改回失实原文（:13-14 那处）",
     "main_rs",
     "（**Rust 侧**缺省 `jaccard`；注意它与\n"
     "//!     Python 侧产品缺省 `legacy`（`md_cg/mdcg.py:SCORE_MODE`）**不一致**——\n"
     "//!     两侧缺省本就不同，R-7 订正，详见下方 `Cfg.jaccard` 处注释）",
     "（缺省 jaccard，与 Python\n//!     mdcg.SCORE_MODE 缺省一致）",
     2),
    ("R-7 main.rs 锚点漂移（CH-1 的 G3k 锚点成孤儿）",
     "main_rs", "jaccard: true, // 缺省 jaccard", "jaccard: true, // 缺省", 1),
)


class _N:
    n = 0


def _write_mutated(key, old, new):
    """把 `key` 面源码做定点文本替换后写入**守卫临时目录**（不进仓库工作区）。

    返回 (变异副本路径 | None, 源文本)；None = 锚点未命中（调用方报 ANCHOR-MISS）。
    """
    src = _read(_LIVE[key])
    if old not in src:
        return None, src
    _N.n += 1
    ext = os.path.splitext(_LIVE[key])[1]
    path = os.path.join(_TMP, "mut_%s_%d%s" % (key, _N.n, ext))
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(src.replace(old, new, 1))
    return path, src


def _run_groups() -> int:
    _PASS.clear()
    _FAIL.clear()
    _SKIP.clear()
    for g in (g1, g2, g6, g3, g4, g5):
        try:
            g()
        except Exception as exc:                            # noqa: BLE001
            ok(False, "断言组 %s 抛异常：%s" % (g.__name__, exc))
    return len(_FAIL)


def _mutate_mode(list_only=False) -> int:
    print("!! 定点变异自证：逐条把修复点改回缺陷形态，套件必须按预期条数转红\n")
    if list_only:
        for name, key, _old, _new, exp in _MUTATIONS:
            print("  %-46s 面=%-8s expect_red=%d" % (name, key, exp))
        return 0

    import contextlib
    import io
    anchor_miss, bad = [], []
    with contextlib.redirect_stdout(io.StringIO()):
        clean = _run_groups()
    print("  未变异基线：失败=%d（必须为 0）" % clean)
    if clean:
        bad.append("未变异基线即失败")

    for name, key, old, new, expect in _MUTATIONS:
        path, _ = _write_mutated(key, old, new)
        if path is None:
            print("  ANCHOR-MISS %s —— 锚点在 %s 当前源码里找不到（实现改了却没同步"
                  "本表；基线不得静默漂移）" % (name, os.path.relpath(_LIVE[key], _REPO)))
            anchor_miss.append(name)
            continue
        live = F[key]
        F[key] = path
        try:
            with contextlib.redirect_stdout(buf := io.StringIO()):
                fails = _run_groups()
            detail = buf.getvalue()
        finally:
            F[key] = live
        red = [ln for ln in detail.splitlines() if ln.strip().startswith("FAIL ")]
        verdict = "红" if fails else "**仍全绿 = 该判据空转**"
        print("  %s %-46s 红项=%d 预期=%d  %s"
              % ("OK  " if fails == expect else "MISMATCH", name, fails, expect, verdict))
        for ln in red:
            print("        " + ln.strip()[5:][:110])
        if fails != expect:
            bad.append("%s（红=%d 预期=%d）" % (name, fails, expect))

    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s" % ("PASS（每处判据都被打红且恰好命中预期项数）"
                                  if not bad else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def _cleanup():
    shutil.rmtree(_TMP, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="R-7 守卫：rust 门禁腿接线")
    ap.add_argument("--probe", action="store_true", help="打红探针（真门禁红→还原绿）")
    ap.add_argument("--mutate", action="store_true", help="定点变异自证")
    ap.add_argument("--list", action="store_true", help="只列变异表")
    args = ap.parse_args()
    try:
        if args.mutate:
            return _mutate_mode(args.list)
        if args.list:
            return _mutate_mode(True)
        if args.probe:
            return _probe()
        n_fail = _run_groups()
        print("\nR-7 守卫（rust 门禁腿接线）：%d 通过，%d 失败，%d 跳过"
              % (len(_PASS), n_fail, len(_SKIP)))
        return 0 if not n_fail else 1
    finally:
        _cleanup()


if __name__ == "__main__":
    sys.exit(main())
