# -*- coding: utf-8 -*-
"""CH-1 守卫 · `scripts/rank_parity.py` 两侧词法打分口径接线。

来源：编排会话 2026-09-29 实测「Python search_rrf vs Rust mcdg-eval --serve」
逐位对拍三态，定位到**缺陷在 harness 的口径漏接线**而非产品侧：

    态                     逐位    集合    top-1   rc
    缺省（修前）           7/10   10/10   7/10    1
    MDCG_UNIFY_QUERY=0     6/10    9/10   6/10    1
    Python 侧切 jaccard   10/10   10/10  10/10    0

两侧**产品缺省本就不同**（Python `md_cg/mdcg.py:SCORE_MODE` 缺省 `legacy`；
Rust `Cfg.jaccard` / `EngineConfig::default().jaccard` 缺省 `true`=jaccard），
而修前的 harness 两侧都不钉口径 ⇒ 长期拿两套词法公式互相比较，三条 DIFF 全是
「同一批分数分配给不同节点」的伪差异（词法排序在并列处劈叉）。

覆盖与判据（每条都对应修复契约的一项）：

  G1/G1b（契约①「两侧口径由单点显式钉住」）——临时库上跑 harness 的等价对拍，
      断言**缺省态即逐位 10/10 · 集合 10/10 · top-1 10/10、退出码 0**：
        G1  = 守卫自建临时库 + `--root`（库根由 tempfile.mkdtemp 造）
        G1b = 完全缺省调用（harness 自建临时库，即编排侧实跑的那条命令）
      同时断言头部行印出「两侧钉住」可观测面 `score=jaccard=rust jaccard`。

  G2（契约②「口径漂移必须变响」）——只给 Python 侧设 `MDCG_SCORE_MODE=legacy`
      （两侧口径被人为拨散）：断言 harness **非 0 退出（3）**、打印**两侧实际
      口径**与修复提示，且**不打印逐位读数**（未静默给出低分）。

  G3（结构面·防回退）——源码锚点 + 行为自证：
        单点常量 `SCORE_MODE = "jaccard"` 在位且 docstring 写明缺省口径；
        Python 侧走**既有的** `eval_common.use_jaccard()`（且该单点自身仍是
        `m.SCORE_MODE = "jaccard"`——**不新写第二套开关**）；
        Rust 侧 argv 显式 `--score` + `serve info` 回读面在位；
        **两侧产品缺省未被本批改动**（负向锚点：Python 缺省仍 legacy、Rust 缺省
        仍 jaccard——本批只显式化差异，不动检索口径）；
        `pin_python_score_mode()` 在缺省态把模块口径拨到 jaccard；env 声明冲突时
        返回冲突说明且**不覆盖**模块口径。

  G4（契约②的 fail-closed 面）——伪造一个「能应答但 info 不报 score」的过期
      serve：断言 harness 退回 **rc=4** + 可执行的重编提示，且**不给逐位读数**
      （读不到对方口径就不得继续对拍）。

运行：
    python -X utf8 -m md_cg.test_rank_parity_score_mode              # 正向
    python -X utf8 -m md_cg.test_rank_parity_score_mode --mutate     # 定点变异自证
    python -X utf8 -m md_cg.test_rank_parity_score_mode --mutate --list

退出码（fail-closed）：0 = 全绿；1 = 有断言失败 / 变异未按预期转红；
2 = **ANCHOR-MISS**（变异锚点在当前源码里找不到——实现改了却没同步本表，
本表就是判据，锚点漂移必须硬失败，不得静默跳过）。

依赖与「未构建」处置（**选 fail-closed**，不选 SKIP）：本守卫需要 `rust/target/
release/mdcg-eval`（对拍的另一侧）。二进制缺失时 `main()` **前置判红**：打印可执行
的重编命令 `cd rust && cargo build --release` 并直接退出 **1**（不进断言组、不计
通过）——即「跑不起来」永远不等于「通过」。断言组内另留同款兜底（若二进制在组内
中途消失：依赖组逐条打印 `SKIP(未跑)` **不计入通过数**，同时补一条 fail-closed
红项），故任何口径下都不会出现「跳过=通过」。

**基线纪律**：本守卫**不以 git HEAD（或任何提交快照）为基线源**——触发红项的
「修前形态」全部由**在当前工作区源码上做定点文本变异**得到（`_MUTATIONS`），
基线随代码一起走、不随提交漂移。变异副本写入**本守卫的临时目录**（不进仓库
工作区），运行期经 PYTHONPATH 指向仓库根解析 `md_cg`，故 `_REPO` 派生物
（`--exe` 缺省、`MDCG_EN_ZH_MAP` 缺省）在本守卫里一律**显式传参**，两侧同源。

硬边界：不动任何在役数据根；库根一律 `tempfile.mkdtemp`；不 git add/commit/push；
不改 `data/policy.json`；不改任何检索算法与排序判据。
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import sys
import tempfile
import time

# ── 隔离前置：必须在 import md_cg 子模块**之前**（tokens/theory 等在模块级把
# aux_root() 冻成常量）——否则会指到真实 ~/.mdcg 并在那里建密钥/令牌库。
# 与 md_cg/test_opt_batch1_md_cg.py 同款前置（同一纪律）。 ──
_TMP = tempfile.mkdtemp(prefix="ch1_rp_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "cd" * 32          # 哑主密钥（绝不触真实密钥面）
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP, "tokens.json")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "cgroot")
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_SESSION",
           "DSH_SESSION_ID", "MDCG_LEGACY_ENV_AUTH", "MDCG_LEGACY_ENV_ADMIN",
           "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_STATE_ROOT",
           "MDCG_DATA_ROOT", "MDCG_TENANT_REGISTRY", "MDCG_VERIFIER_MODULES",
           # 口径面：本守卫在**缺省态**上验证，故这两个开关必须干净
           "MDCG_SCORE_MODE", "MDCG_UNIFY_QUERY"):
    os.environ.pop(_k, None)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SELF = os.path.abspath(__file__)

_HARNESS = os.path.join(_REPO, "scripts", "rank_parity.py")
_EXE = os.path.join(_REPO, "rust", "target", "release",
                    "mdcg-eval.exe" if os.name == "nt" else "mdcg-eval")
_EN_ZH_MAP = os.path.join(_REPO, "md_cg", "semantic", "en_zh_map.json")

# 被测 harness 的**可替换路径**：变异模式换成变异副本（临时目录），断言组一律
# 经本表取路径/取模块（不直接闭包捕获原路径），否则变异对断言不可见。
H = {"path": _HARNESS}

# 两侧**产品缺省**（负向锚点用：本批不得改动它们）
_PY_DEFAULT_ANCHOR = 'SCORE_MODE = os.environ.get("MDCG_SCORE_MODE") or "legacy"'
_RUST_CFG_DEFAULT_ANCHOR = "jaccard: true, // 缺省 jaccard"

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


def _cleanup(path) -> bool:
    import gc
    for _ in range(6):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return True
        gc.collect()
        time.sleep(0.2)
    return not os.path.exists(path)


# --------------------------------------------------------------- 被测面装载
_LOAD_CTR = [0]


def _load_harness(path):
    """把 harness 源码装成独立模块（不执行 main；不落盘、不改工作区）。"""
    _LOAD_CTR[0] += 1
    name = "rank_parity_under_test_%d" % _LOAD_CTR[0]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_harness(extra_args=(), env_overrides=None, exe=_EXE, timeout=900):
    """跑一次 harness（真进程：新解释器 = 无跨运行状态残留）。

    显式传 `--exe` 与 `MDCG_EN_ZH_MAP`：变异副本位于临时目录，其 `_REPO` 派生
    缺省不可信——两侧同源靠显式传参保证，否则「变异转红」可能来自路径错而非判据。
    """
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = _REPO + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["MDCG_EN_ZH_MAP"] = _EN_ZH_MAP
    env.update(env_overrides or {})
    argv = [sys.executable, "-X", "utf8", H["path"], "--exe", exe] + list(extra_args)
    return subprocess_run(argv, env)


def subprocess_run(argv, env):
    import subprocess
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, cwd=_REPO, timeout=900)


def _summary(out):
    """从 harness 输出取 (逐位, 集合, top-1, 总数)；无该行返回 None。"""
    m = re.search(r"逐位一致 (\d+)/(\d+) · 集合一致 (\d+)/(\d+) · "
                  r"top-1 一致 (\d+)/(\d+)", out or "")
    if not m:
        return None
    g = [int(x) for x in m.groups()]
    return (g[0], g[2], g[4], g[1])


def _fake_stale_exe(d):
    """伪造「能应答但 info 不报 score」的过期 serve（二进制过期形态）。"""
    py = os.path.join(d, "fake_stale_serve.py")
    with open(py, "w", encoding="utf-8") as f:
        f.write(
            "import sys, json\n"
            "for line in sys.stdin:\n"
            "    line = line.strip()\n"
            "    if not line:\n"
            "        continue\n"
            "    if line == 'quit':\n"
            "        break\n"
            "    req = json.loads(line)\n"
            "    if req.get('op') == 'info':\n"
            # 关键：**不报 score**（修前 serve 的 info 面）
            "        resp = {'ok': True, 'root': 'stale', 'docs': 0}\n"
            "    else:\n"
            "        resp = {'ok': True, 'hits': []}\n"
            "    sys.stdout.write(json.dumps(resp) + '\\n')\n"
            "    sys.stdout.flush()\n")
    if os.name == "nt":
        launcher = os.path.join(d, "fake_stale_serve.cmd")
        with open(launcher, "w", encoding="utf-8") as f:
            f.write('@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, py))
    else:
        launcher = os.path.join(d, "fake_stale_serve.sh")
        with open(launcher, "w", encoding="utf-8") as f:
            f.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, py))
        os.chmod(launcher, 0o755)
    return launcher


# ================================================================ G0 前置自证
def g0():
    print("== G0 隔离与前置自证 ==")
    ok(os.path.abspath(os.environ["MDCG_AUX_ROOT"]).lower().startswith(_TMP.lower()),
       "G0a 辅助根落在守卫临时目录（绝不触真实凭据/密钥面）",
       os.environ["MDCG_AUX_ROOT"])
    ok("MDCG_SCORE_MODE" not in os.environ and "MDCG_UNIFY_QUERY" not in os.environ,
       "G0b 口径类 env 干净：本守卫确实在**缺省态**上验证",
       os.environ.get("MDCG_SCORE_MODE"))
    # 基线源自证（反「基线绑提交」）：变异加载器直接 open 当前工作区源文件，
    # 读到的就是它此刻在盘上的内容——不含任何提交快照读取面。
    live = _read(_HARNESS)
    mut_path, src = _write_mutated(live, 'SCORE_MODE = "jaccard"', 'SCORE_MODE = "jaccard"  # MUT')
    ok(mut_path is not None and src == live,
       "G0c 变异基线源 = 当前工作区源码（非 git HEAD／提交快照）", mut_path)
    print("      被测面：%s" % H["path"])
    print("      对拍另一侧：%s" % _EXE)


# ================================================================ G1 缺省态对拍
def g1():
    print("== G1 契约①：缺省态即 10/10/10（守卫自建临时库 + --root）==")
    if not os.path.isfile(_EXE):
        skip("G1 对拍（rust 二进制缺失）—— 修复：cd rust && cargo build --release")
        ok(False, "G1 前置：rust release 二进制在位（fail-closed：跑不起来≠通过）", _EXE)
        return
    mod = _load_harness(H["path"])
    root = tempfile.mkdtemp(prefix="ch1_db_")           # 实验库根：系统临时目录
    try:
        n = mod.build_cogmap(root)
        ok(n == 30, "G1a 临时库建成 30 节点（正对照：夹具不空转）", n)
        p = _run_harness(["--root", root])
        s = _summary(p.stdout)
        ok(p.returncode == 0, "G1b 缺省态退出码 0（口径已接线：两侧同钉 jaccard）",
           "rc=%s out=%s" % (p.returncode, p.stdout.strip()[-200:]))
        ok(s is not None and s[0] == s[3] == 10,
           "G1c 逐位一致 10/10（修前缺省态 7/10）", s)
        ok(s is not None and s[1] == 10, "G1d 集合一致 10/10", s)
        ok(s is not None and s[2] == 10, "G1e top-1 一致 10/10（修前 7/10）", s)
        ok("[DIFF]" not in p.stdout, "G1f 无 DIFF 行（三条伪差异已消失）",
           [l for l in p.stdout.splitlines() if "DIFF" in l][:3])
        ok(re.search(r"score=jaccard=rust jaccard", p.stdout) is not None,
           "G1g 头部行印出两侧实际口径（自描述：score=jaccard=rust jaccard）",
           p.stdout.strip().splitlines()[0] if p.stdout.strip() else "")
    finally:
        _cleanup(root)


# ================================================================ G1b 缺省调用
def g1b():
    print("== G1b 契约①：完全缺省调用（harness 自建临时库，编排侧实跑形态）==")
    if not os.path.isfile(_EXE):
        skip("G1b 对拍（rust 二进制缺失）—— 修复：cd rust && cargo build --release")
        ok(False, "G1b 前置：rust release 二进制在位（fail-closed）", _EXE)
        return
    p = _run_harness([])
    s = _summary(p.stdout)
    ok(p.returncode == 0, "G1b-1 缺省调用退出码 0",
       "rc=%s out=%s" % (p.returncode, p.stdout.strip()[-200:]))
    ok(s == (10, 10, 10, 10), "G1b-2 缺省调用逐位/集合/top-1 = 10/10/10", s)
    ok("[DIFF]" not in p.stdout, "G1b-3 无 DIFF 行")


# ================================================================ G2 漂移变响
def g2():
    print("== G2 契约②：两侧口径被人为拨散 → 非 0 退出并报口径不一致 ==")
    if not os.path.isfile(_EXE):
        skip("G2 漂移闸（rust 二进制缺失）—— 修复：cd rust && cargo build --release")
        ok(False, "G2 前置：rust release 二进制在位（fail-closed）", _EXE)
        return
    p = _run_harness([], env_overrides={"MDCG_SCORE_MODE": "legacy"})
    out = p.stdout
    ok(p.returncode != 0, "G2a 非 0 退出（口径不一致不得继续对拍）", "rc=%s" % p.returncode)
    ok(p.returncode == 3, "G2b 退出码 = 3（口径不一致专用码，与逐位劈叉 1 区分）",
       "rc=%s" % p.returncode)
    ok("口径不一致" in out, "G2c 打印口径不一致判定")
    ok(re.search(r"python 侧实际口径 = legacy", out) is not None,
       "G2d 打印 Python 侧**实际**口径 = legacy（读回值，非假设）",
       out.strip()[:200])
    ok(re.search(r"rust\s+侧实际口径 = jaccard", out) is not None,
       "G2e 打印 Rust 侧**实际**口径 = jaccard（回读自被拉起进程）",
       out.strip()[:200])
    ok("修复" in out, "G2f 打印修复提示")
    ok(_summary(out) is None,
       "G2g **不打印逐位读数**（未静默给出低分——修前形态即此处静默）",
       _summary(out))


# ================================================================ G3 结构面
def g3():
    print("== G3 结构面：口径钉住的单点与回读面在位、两侧产品缺省未被改动 ==")
    src = _read(H["path"])
    ok('SCORE_MODE = "jaccard"' in src,
       'G3a harness 口径**唯一单点**常量 SCORE_MODE = "jaccard" 在位')
    ok("缺省口径 = jaccard" in src,
       "G3b 顶部用法注释写明本 harness 的缺省口径 = jaccard（与 eval 面同判据）")
    # ② Python 侧走既有单点，且该单点自身未被改写成第二套开关
    ok(any(l.strip() == "eval_common.use_jaccard()" for l in src.splitlines()),
       "G3c Python 侧经**既有** md_cg/eval_common.py::use_jaccard() 注入（非自造开关）")
    ec = _read(os.path.join(_HERE, "eval_common.py"))
    ok('m.SCORE_MODE = "jaccard"' in ec,
       "G3d 评测面单点 eval_common.use_jaccard 本体仍是 m.SCORE_MODE = \"jaccard\"")
    # ③ Rust 侧显式入参 + 回读面
    ok(re.search(r'"--score",\s*score', src) is not None,
       'G3e Rust 侧 argv 显式钉住口径（"--score", score），不吃 Config::default()')
    ok("rust_reported_score" in src and "score" in src,
       "G3f harness 回读 Rust 侧自报口径（rust_reported_score / info.score）")
    serve = _read(os.path.join(_REPO, "rust", "src", "serve.rs"))
    ok('"score".to_string()' in serve,
       "G3g rust/src/serve.rs 的 info 面回带 score（回读面的服务端一侧）")
    eng = _read(os.path.join(_REPO, "rust", "src", "engine.rs"))
    ok("pub fn jaccard(&self) -> bool" in eng,
       "G3h engine 暴露实际生效口径的访问器（回读面取值处）")
    main_rs = _read(os.path.join(_REPO, "rust", "src", "main.rs"))
    ok("mdcg_eval::engine::score_label" in main_rs,
       "G3i 口径标签映射单点（main.rs 转调 engine::score_label，与 serve 同源）")
    # 负向锚点：两侧**产品缺省**不得被本批改动（只显式化差异，不动检索口径）
    md = _read(os.path.join(_HERE, "mdcg.py"))
    ok(_PY_DEFAULT_ANCHOR in md,
       "G3j 负向锚点：Python 产品缺省仍是 legacy（md_cg/mdcg.py:SCORE_MODE 未被本批改）")
    ok(_RUST_CFG_DEFAULT_ANCHOR in main_rs,
       "G3k 负向锚点：Rust Cfg 缺省仍是 jaccard: true（Config::default() 未被本批改）")
    # 行为自证：缺省（legacy）态下钉住体把模块口径拨到 jaccard，并**读回**该值
    import md_cg.mdcg as m
    before = m.SCORE_MODE
    ok(before == "legacy",
       "G3l 前置：本进程内 mdcg.SCORE_MODE 为产品缺省 legacy（缺省态验证的前提）", before)
    mod = _load_harness(H["path"])
    got, conflict = mod.pin_python_score_mode()
    ok(got == "jaccard" and conflict is None,
       "G3m 行为自证：缺省态下 pin 后读回口径 = jaccard（且无冲突）",
       "got=%s conflict=%s" % (got, conflict))
    ok(m.SCORE_MODE == "jaccard",
       "G3n 行为自证：模块级 SCORE_MODE 实际被拨到 jaccard（mdcos 读同一份）",
       m.SCORE_MODE)
    # env 声明冲突：报冲突且**不覆盖**（不静默无视操作者声明）
    m.SCORE_MODE = "legacy"
    os.environ["MDCG_SCORE_MODE"] = "legacy"
    try:
        got2, conflict2 = mod.pin_python_score_mode()
        ok(conflict2 is not None and got2 == "legacy",
           "G3o env 声明冲突时返回冲突说明且实际口径仍为 legacy（不静默覆盖）",
           "got=%s conflict=%s" % (got2, conflict2))
    finally:
        os.environ.pop("MDCG_SCORE_MODE", None)
        m.SCORE_MODE = before
    # A/B 路径同口径（同一 harness 只有一套口径单点）
    ok("口径 {py_mode}" in src,
       "G3p --ab 路径头部自描述口径（不再隐式吃缺省）")


# ================================================================ G4 过期二进制
def g4():
    print("== G4 fail-closed：Rust 侧不报口径（二进制过期）→ 不得继续对拍 ==")
    d = tempfile.mkdtemp(prefix="ch1_stale_")
    try:
        launcher = _fake_stale_exe(d)
        p = _run_harness([], exe=launcher)
        out = p.stdout
        ok(p.returncode == 4, "G4a 退出码 = 4（口径不可读专用码）",
           "rc=%s out=%s" % (p.returncode, out.strip()[-300:]))
        ok("口径不可读" in out, "G4b 打印「口径不可读」判定")
        ok("cargo build --release" in out, "G4c 给出可执行的重编提示")
        ok(_summary(out) is None, "G4d 不给逐位读数（读不到对方口径不得继续对拍）",
           _summary(out))
    finally:
        _cleanup(d)


# ================================================================ 变异表
# 每条 = (名称, 源码锚点, 替换文本, 预期转红条数)。
# 锚点必须逐字命中当前源码（找不到 → ANCHOR-MISS → 退出码 2，fail-closed）。
_MUTATIONS = (
    ("CH-1 去掉 Python 侧口径钉住（撤 eval_common.use_jaccard 调用）",
     "        eval_common.use_jaccard()\n",
     "        pass  # MUT：Python 侧回退吃产品缺省 legacy\n",
     10),
    ("CH-1 撤掉两侧口径对照闸（漂移不再变响）",
     "    if py_conflict or py_mode != rs_mode:\n",
     "    if False:  # MUT：漂移闸拆除\n",
     6),
)


class _Name:
    """变异副本的稳定命名容器（与 _MUT_CTR 配合）。"""
    n = 0


def _write_mutated(src: str, old: str, new: str):
    """把 `src` 做定点文本替换后写入**守卫临时目录**（不进仓库工作区）。

    返回 (变异副本路径 | None, 源文本)。None = 锚点未命中（调用方报 ANCHOR-MISS）。
    """
    if old not in src:
        return None, src
    _Name.n += 1
    path = os.path.join(_TMP, "mut_rank_parity_%d.py" % _Name.n)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src.replace(old, new, 1))
    return path, src


def _run_groups() -> int:
    """跑全部断言组，返回失败数（变异核验复用）。"""
    _PASS.clear()
    _FAIL.clear()
    _SKIP.clear()
    for g in (g0, g1, g1b, g2, g3, g4):
        try:
            g()
        except Exception as exc:                            # noqa: BLE001
            ok(False, "断言组 %s 抛异常：%s" % (g.__name__, exc))
    return len(_FAIL)


def _mutate_mode(list_only: bool = False) -> int:
    print("!! 定点变异自证：逐条把修复点改回缺陷形态，套件必须按预期条数转红\n")
    if list_only:
        for name, old, new, exp in _MUTATIONS:
            print("  %-52s expect_red=%d" % (name, exp))
        return 0

    import contextlib
    import io
    anchor_miss = []
    bad = []
    with contextlib.redirect_stdout(io.StringIO()):
        clean = _run_groups()
    print("  未变异基线：失败=%d（必须为 0）" % clean)
    if clean:
        bad.append("未变异基线即失败")

    live_src = _read(_HARNESS)
    for name, old, new, expect in _MUTATIONS:
        path, _ = _write_mutated(live_src, old, new)
        if path is None:
            print("  ANCHOR-MISS %s —— 锚点在 scripts/rank_parity.py 当前源码里"
                  "找不到（实现改了却没同步本表；基线不得静默漂移）" % name)
            anchor_miss.append(name)
            continue
        live_path = H["path"]
        H["path"] = path
        try:
            with contextlib.redirect_stdout(buf := io.StringIO()):
                fails_extra = _run_groups()
            detail = buf.getvalue()
        finally:
            H["path"] = live_path
        red = [l for l in detail.splitlines() if l.strip().startswith("FAIL ")]
        verdict = "红" if fails_extra else "**仍全绿 = 该判据空转**"
        mark = "OK  " if fails_extra == expect else "MISMATCH"
        print("  %s %-52s 红项=%d 预期=%d  %s"
              % (mark, name, fails_extra, expect, verdict))
        for l in red:
            print("        " + l.strip()[5:])
        if fails_extra != expect:
            bad.append("%s（红=%d 预期=%d）" % (name, fails_extra, expect))

    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s" % ("PASS（每处判据都被打红且恰好命中预期项数）"
                                   if not bad else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def main() -> int:
    if not os.path.isfile(_EXE):
        print("!! rust release 二进制缺失：%s" % _EXE)
        print("   修复：cd rust && cargo build --release")
        print("   处置：**fail-closed**（本守卫不计通过、直接退出 1；"
              "不采用静默 SKIP 而返回 0——跑不起来永远不等于通过）")
        return 1
    if "--mutate" in sys.argv:
        try:
            return _mutate_mode("--list" in sys.argv)
        finally:
            _cleanup(_TMP)
    try:
        n_fail = _run_groups()
        print("\nCH-1 守卫（rank_parity 两侧口径接线）：%d 通过，%d 失败，%d 跳过"
              % (len(_PASS), n_fail, len(_SKIP)))
        return 0 if not n_fail else 1
    finally:
        _cleanup(_TMP)


if __name__ == "__main__":
    sys.exit(main())
