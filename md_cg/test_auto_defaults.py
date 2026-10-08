# -*- coding: utf-8 -*-
"""`auto_*` 四档缺省「单一真源」守卫（P0-2，2026-10-01）。

契约（设计稿 `docs/plans/睡眠与自迭代_功能优化设计_v0.4.md` §八 P0-2 / §4.7）：

    同一 `(root, name)` 的两条入口必须得到**同一组** `auto_*` 取值；
    缺省只许有**一份定义**（`sustain.AUTO_DEFAULTS` + 三个读取器），
    两个调用点不得再写第二处字面量。

改动前实测（探针读数，逐条引 `path:line`）：

    op 路径（工具面 `sustain action=start`）   `auto_tidy=bool(a.get("auto_tidy", False))`
                                              → **False**（mcp_server.py:1639）
    env 路径（常驻 serve 自启 `_start_sustain`）`auto_tidy=os.environ.get("MDCG_AUTO_TIDY","1") not in (...)`
                                              → **True**（mcp_server.py:3595-3596）
    另三项 auto_heal/auto_scrub/auto_evolve 两入口一致（True / False / False）；
    `SustainLoop.__init__` 形参另有一份 `auto_tidy=False`（sustain.py:966）——
    即「单一真源尚未成立，全仓 auto_tidy 缺省字面量至少两处」。

**本轮对外可见的缺省变更（裁决值 = 开）**：`auto_tidy` 缺省由 False 收敛为
**True**（取 env 路径既有值）；opt-out = `MDCG_AUTO_TIDY=0`（env 路径）／
显式 `auto_tidy=false`（op 路径）。另三项**逐项未变**（G4 钉死，防「顺手改多了」）。

断言分组：

  G0 隔离与基线自证——库根/状态根/辅助根/心跳目录全落守卫临时目录（绝不碰在役
     库与 `~/.mdcg`）；断言真源表与三个读取器在位。
  G1 真源表与读取器——四项值、键集、env 键映射、关断字面量固定；`auto_default`
     逐项一致；`auto_from_env` 的缺省字面量**由表推出**（真值→"1"、假值→"0"，
     与改动前两处字面量同义）。
  G2 三面同源读数（端到端，真起循环）——env 路径（`_start_sustain`）、op 路径
     （`_sustain_call` 的 start 分支）、构造面（`SustainLoop(cg)`）三面在同一档上
     取值相同且**都等于真源表**；并验两侧 opt-out / 显式入参仍优先。
  G3 单一真源（静态）——带引号字面量 `"MDCG_AUTO_TIDY"` 在生产源码里恰 1 处
     （在 `AUTO_ENVS`）；`mcp_server.py` 内 `a.get("auto_*"` /
     `os.environ.get("MDCG_AUTO_*"` / `os.environ.get("MDCG_SUSTAIN_AUTOHEAL"` 零命中；
     两入口各恰好一处读取器调用。（`md_cg/test_*.py` 不在判据面内：本守卫自己的
     变异表就含这些字面量，属红基线工具面。）
  G4 对外可见变更的披露面——`auto_tidy` 缺省为 True 且 op 路径无参即得 True；
     另三项缺省与本轮前逐项相同；opt-out 名取自 `AUTO_ENVS` 而非硬编码。

运行：python -X utf8 -m md_cg.test_auto_defaults
      python -X utf8 -m md_cg.test_auto_defaults --mutate         # 定点变异自证
      python -X utf8 -m md_cg.test_auto_defaults --mutate --list  # 只列变异表

退出码（fail-closed）：0 = 全绿；1 = 有断言失败 / 变异未按预期转红；
2 = ANCHOR-MISS（变异锚点在当前源码里找不到——实现改了却没同步本表，
锚点漂移必须硬失败，不得静默跳过）。

**基线纪律**：本守卫**不以 git HEAD 为基线源**——「改动前形态」由在当前工作区
源码上做**定点文本变异**（`_MUTATIONS`）复现，锚点漂移即退出码 2。
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import types

from . import mcp_server as MCP
from . import sustain

_PASS = []
_FAIL = []
_SKIP = []
#: 变异模式下供静态组读取的**源码文本**（rel → text）；未变异时读盘。
_SRC = {}

_REAL_SUSTAIN = sustain
_REAL_MCP = MCP


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


def skip(msg):
    _SKIP.append(msg)
    print("  SKIP " + msg)


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _rel_text(rel: str) -> str:
    """源码文本：变异模式下取变异后的文本，否则读盘。"""
    if rel in _SRC:
        return _SRC[rel]
    with open(os.path.join(_repo_root(), rel), encoding="utf-8") as f:
        return f.read()


def _tracked_rels():
    """git 追踪面（仓根相对 · posix 分隔）集合；git 不可用/非仓 ⇒ None（调用方降级）。

    G3 静态判据面须锚在**追踪面**而非文件系统面：本地工作树的 gitignore 产物
    （`.tmp/` 草稿、`md_cg/_md_cg_eval_*/` 评测灌库、`md_cg/knowledge/` 运行态）
    不在 CI 干净克隆里，用文件系统面判定会让「本地红 / CI 绿」分裂。`.tmp` 只是
    当前最大污染源，故按「是否被 git 追踪」这个**性质**判，不逐个硬编码排除目录。
    """
    try:
        proc = subprocess.run(["git", "-C", _repo_root(), "ls-files", "-z"],
                              capture_output=True, check=True)
    except Exception:                                  # noqa: BLE001 —— 兜底见下
        return None
    return {p.replace("\\", "/") for p in
            proc.stdout.decode("utf-8", "replace").split("\0") if p}


def _md_cg_py_texts():
    """静态判据面 = `md_cg/` 下全部 `.py` ∩ **git 追踪面**（非追踪件不入面）。

    降级（明示，非静默改语义）：git 不可用或非仓环境 ⇒ 退化为原文件系统走查，
    并打印 `[降级]` 一行——此时判据面可能与 CI 干净克隆不一致，读数须按降级看待。
    """
    tracked = _tracked_rels()
    if tracked is None:
        print("  [降级] git 不可用：G3 静态扫描面退化为文件系统走查"
              "（可能与 CI 干净克隆不一致）")
    d = os.path.join(_repo_root(), "md_cg")
    out = {}
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".py"):
            continue
        rel = "md_cg/" + fn
        if tracked is not None and rel not in tracked:
            continue          # 非追踪件不入判据面（保留原 .py 语义）
        out[rel] = _rel_text(rel)
    return out


# ---------------------------------------------------------------- 沙箱
_TMP = tempfile.mkdtemp(prefix="mdcg_autodef_")
_SAVED = {}
_GEN = [0]


def _sandbox_env():
    """把四条根全钉进守卫临时目录；原值留待还原（绝不碰在役库 / ~/.mdcg）。"""
    for k in ("MDCG_ROOT", "MDCG_AUX_ROOT", "MDCG_STATE_ROOT", "MDCG_SUSTAIN_DIR",
              "MDCG_SUBSTAIN", "MDCG_SUSTAIN", "MDCG_SUSTAIN_NAME",
              "MDCG_AUTO_TIDY", "MDCG_AUTO_SCRUB", "MDCG_AUTO_EVOLVE",
              "MDCG_SUSTAIN_AUTOHEAL"):
        _SAVED[k] = os.environ.get(k)
    os.environ["MDCG_ROOT"] = os.path.join(_TMP, "cg")
    os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "aux")
    os.environ["MDCG_STATE_ROOT"] = os.path.join(_TMP, "state")
    os.environ["MDCG_SUSTAIN_DIR"] = os.path.join(_TMP, "sustain")
    os.environ["MDCG_SUBSTAIN"] = "0"
    os.environ.pop("MDCG_SUSTAIN", None)
    for k in ("MDCG_AUTO_TIDY", "MDCG_AUTO_SCRUB", "MDCG_AUTO_EVOLVE",
              "MDCG_SUSTAIN_AUTOHEAL"):
        os.environ.pop(k, None)


def _restore_env():
    for k, v in _SAVED.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _cg(name="cg"):
    """每轮 `_run_groups` 用**全新根**：`sustain.ensure_loop` 按 (root,name) 复用
    实例，同一根跨轮复用会让变异轮读到上一轮的循环（假绿）。"""
    from .mdcos import MdCGOS
    root = os.path.join(_TMP, "gen%d" % _GEN[0], name)
    os.makedirs(root, exist_ok=True)
    return MdCGOS(root)


# ---------------------------------------------------------------- G0
def g0():
    print("== G0 隔离与基线自证 ==")
    ok(hasattr(_REAL_SUSTAIN, "AUTO_DEFAULTS"),
       "G0a sustain.AUTO_DEFAULTS 存在（缺省真源表）")
    ok(all(hasattr(_REAL_SUSTAIN, n)
           for n in ("auto_default", "auto_from_env", "auto_from_args")),
       "G0b 三个读取器（auto_default / auto_from_env / auto_from_args）均在位")
    ok(os.environ["MDCG_ROOT"].startswith(_TMP)
       and os.environ["MDCG_AUX_ROOT"].startswith(_TMP),
       "G0c 沙箱：库根与辅助根都在守卫临时目录内", os.environ["MDCG_ROOT"])


# ---------------------------------------------------------------- G1
_EXPECT = {"auto_heal": True, "auto_scrub": False,
           "auto_evolve": False, "auto_tidy": True}


def g1():
    print("== G1 真源表与读取器 ==")
    S = globals()["sustain"]
    ok(dict(S.AUTO_DEFAULTS) == _EXPECT,
       "G1 真源表四项与裁决值一致（含 auto_tidy=True——本轮唯一的对外可见变更）",
       S.AUTO_DEFAULTS)
    ok(set(S.AUTO_ENVS) == set(S.AUTO_DEFAULTS),
       "G1a env 键映射与真源表同键集", sorted(S.AUTO_ENVS))
    ok(S.AUTO_ENVS["auto_tidy"] == "MDCG_AUTO_TIDY",
       "G1b auto_tidy 的 env 键名 = MDCG_AUTO_TIDY（opt-out 名）")
    ok(tuple(S.AUTO_OFF_VALUES) == ("0", "false", "False"),
       "G1c 关断字面量与改动前两入口逐字一致（0 / false / False）",
       S.AUTO_OFF_VALUES)
    for k, v in _EXPECT.items():
        ok(S.auto_default(k) is v,
           "G1d auto_default(%s) 与表一致 = %r" % (k, v))
    for k, v in _EXPECT.items():
        ok(S.auto_from_env(k, {}) is v,
           "G1e auto_from_env(%s) 空环境下回落真源缺省 %r（默认字面量由表推出）"
           % (k, v))
    for k in _EXPECT:
        for off in ("0", "false", "False", "FALSE ", ""):
            got = S.auto_from_env(k, {S.AUTO_ENVS[k]: off})
            want = off not in S.AUTO_OFF_VALUES
            ok(got is want,
               "G1f auto_from_env(%s) 取 %r → %r（关断口径不变）" % (k, off, want),
               got)
    ok(S.auto_from_env("auto_tidy", {"MDCG_AUTO_TIDY": "1"}) is True,
       "G1g 显式 1 仍为开（开态仍可达）")


# ---------------------------------------------------------------- G2
def g2():
    print("== G2 三面同源读数（端到端，真起循环）==")
    S = globals()["sustain"]
    M = globals()["MCP"]
    cg = _cg("cg_g2")
    os.environ.pop("MDCG_AUTO_TIDY", None)
    os.environ["MDCG_SUSTAIN_NAME"] = "env_edge"
    lp = M._start_sustain(cg)
    ok(lp is not None, "G2 env 路径确已起循环（前置）")
    ok(lp.auto_tidy is True,
       "G2a env 路径（_start_sustain）无 env 覆盖时 auto_tidy=True（生产路径既有值）",
       lp.auto_tidy)
    os.environ["MDCG_AUTO_TIDY"] = "0"
    os.environ["MDCG_SUSTAIN_NAME"] = "env_off"
    lp2 = M._start_sustain(cg)
    ok(lp2 is not None and lp2.auto_tidy is False,
       "G2b env 路径 opt-out：MDCG_AUTO_TIDY=0 → auto_tidy=False",
       (lp2.auto_tidy if lp2 else None))
    os.environ.pop("MDCG_AUTO_TIDY", None)
    ti = {"beat_interval": 3600, "heal_interval": 3600, "scrub_interval": 3600,
          "evolve_interval": 3600, "tidy_interval": 3600}
    r = M._sustain_call(cg, dict({"action": "start", "name": "op_default"}, **ti))
    opl = S.get_loop(cg, "op_default")
    ok("loop" in r and opl is not None, "G2c op 路径确已起循环（前置）", r)
    ok(opl is not None and opl.auto_tidy is True,
       "G2d op 路径（sustain action=start）不传参时 auto_tidy=True——**本轮的缺省变更**",
       (opl.auto_tidy if opl else None))
    M._sustain_call(cg, dict({"action": "start", "name": "op_off",
                              "auto_tidy": False}, **ti))
    opl2 = S.get_loop(cg, "op_off")
    ok(opl2 is not None and opl2.auto_tidy is False,
       "G2e op 路径显式 auto_tidy=false → False（显式入参优先于真源表）",
       (opl2.auto_tidy if opl2 else None))
    M._sustain_call(cg, dict({"action": "start", "name": "op_face"}, **ti))
    env_face = S.get_loop(cg, "env_edge")
    op_face = S.get_loop(cg, "op_face")
    ctor_face = S.SustainLoop(cg, name="ctor_face",
                              d=os.environ["MDCG_SUSTAIN_DIR"])
    ok(env_face is not None and op_face is not None,
       "G2f 前置：env / op 两面循环都在册")
    for k in _EXPECT:
        trio = (getattr(env_face, k), getattr(op_face, k), getattr(ctor_face, k))
        ok(trio[0] == trio[1] == trio[2] == _EXPECT[k],
           "G2g 三面同值 %s：env/op/构造 = %r，真源 = %r" % (k, trio, _EXPECT[k]))
    S.stop_all()


# ---------------------------------------------------------------- G3
def g3():
    print("== G3 单一真源（静态）==")
    texts = _md_cg_py_texts()
    prod = {rel: t for rel, t in texts.items()
            if not os.path.basename(rel).startswith("test_")}
    quoted = sorted((rel, t.count('"MDCG_AUTO_TIDY"')) for rel, t in prod.items()
                    if t.count('"MDCG_AUTO_TIDY"'))
    ok(quoted == [("md_cg/sustain.py", 1)],
       "G3 带引号字面量 \"MDCG_AUTO_TIDY\" 在生产源码里恰 1 处（在 AUTO_ENVS）",
       quoted)
    pats = ('os.environ.get("MDCG_AUTO_TIDY"', 'a.get("auto_tidy"',
            'a.get("auto_heal"', 'a.get("auto_scrub"', 'a.get("auto_evolve"',
            'os.environ.get("MDCG_AUTO_SCRUB"',
            'os.environ.get("MDCG_AUTO_EVOLVE"',
            'os.environ.get("MDCG_SUSTAIN_AUTOHEAL"')
    bad = [(rel, p, t.count(p)) for rel, t in prod.items()
           for p in pats if t.count(p)]
    ok(not bad, "G3a 生产源码里零命中「缺省字面量」形态（^ 见 detail）", bad)
    s = _rel_text("md_cg/sustain.py")
    ok("AUTO_DEFAULTS = {" in s, "G3b 真源表在 sustain.py 定义")
    ok(s.count("auto_tidy: bool = AUTO_DEFAULTS[") == 1,
       "G3c SustainLoop 形参默认值引用真源表（不写第二处字面量）")
    m = _rel_text("md_cg/mcp_server.py")
    ok(m.count('auto_tidy=sustain.auto_from_args("auto_tidy", a)') == 1,
       "G3d op 路径恰一处经 auto_from_args 读 auto_tidy")
    ok(m.count('auto_tidy=sustain.auto_from_env("auto_tidy")') == 1,
       "G3e env 路径恰一处经 auto_from_env 读 auto_tidy")
    ok('"auto_tidy", False' not in m and 'auto_tidy=False)' not in m,
       "G3f mcp_server.py 内不再有 auto_tidy 的 False 缺省字面量")


# ---------------------------------------------------------------- G4
def g4():
    print("== G4 变更披露面（防顺手改多了）==")
    S = globals()["sustain"]
    ok(S.AUTO_DEFAULTS["auto_tidy"] is True,
       "G4 裁决值 = 开：auto_tidy 真源缺省为 True")
    ok(S.AUTO_DEFAULTS["auto_heal"] is True
       and S.AUTO_DEFAULTS["auto_scrub"] is False
       and S.AUTO_DEFAULTS["auto_evolve"] is False,
       "G4a 另三项缺省与本轮前逐项相同（heal=True / scrub=False / evolve=False）",
       S.AUTO_DEFAULTS)
    ok(S.AUTO_ENVS["auto_tidy"] == "MDCG_AUTO_TIDY",
       "G4b opt-out env 名（自真源读）= MDCG_AUTO_TIDY")
    ok(S.auto_from_args("auto_tidy", {"auto_tidy": None}) is False,
       "G4c 显式传 None（键在）→ False，与改动前 bool(a.get(name, default)) 同义")
    ok(S.auto_from_args("auto_tidy", {"other": 1}) is True,
       "G4d 缺键才回落真源缺省（True）")


_GROUPS = (g0, g1, g2, g3, g4)


# ---------------------------------------------------------------- 变异表
# 锚点 = (名字, 模式, rel, old, new, 预期红项数下限)。
#   "mod" = 改**可执行实现**（exec 成模块并换进 `sys.modules`，供 `from . import` 面读到）
#   "src" = 只改**源码文本**（静态组 G3 读 `_SRC`，不 exec）
# 「改动前形态」的复现即在这里：
#   M1 把真源表里的 auto_tidy 改回 False（= 旧的 op 路径字面量）
#   M2 让 op 路径读取器不回落真源（= 旧的「另一处字面量」）
#   M3 把 env 路径改回旧的手写 env 读取（= 旧 env 路径形态 + 第二处字面量）
_MUTATIONS = (
    ("真源表 auto_tidy 改回 False（旧 op 路径值）", "mod", "md_cg/sustain.py",
     '"auto_evolve": False, "auto_tidy": True}',
     '"auto_evolve": False, "auto_tidy": False}', 1),
    ("op 路径读取器不回落真源（旧「另一处字面量」）", "mod", "md_cg/sustain.py",
     "        return bool(args[name])\n    return auto_default(name)",
     "        return bool(args[name])\n    return False", 1),
    ("env 路径改回手写 env 读取（第二处 MDCG_AUTO_TIDY 字面量）", "src",
     "md_cg/mcp_server.py",
     'auto_tidy=sustain.auto_from_env("auto_tidy"))',
     'auto_tidy=os.environ.get("MDCG_AUTO_TIDY", "1") not in ("0", "false", "False"))',
     1),
)


def _run_groups() -> int:
    _GEN[0] += 1
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        try:
            g()
        except Exception as exc:                       # noqa: BLE001
            ok(False, "断言组 %s 抛异常：%s" % (g.__name__, exc))
            import traceback
            print(traceback.format_exc()[-800:])
    for mod in (globals().get("sustain"), _REAL_SUSTAIN):
        try:
            mod.stop_all()
        except Exception:                              # noqa: BLE001
            pass
    return len(_FAIL)


def _exec_module(name: str, rel: str, text: str):
    ns = {"__name__": name, "__package__": "md_cg",
          "__file__": os.path.join(_repo_root(), rel)}
    exec(compile(text, rel, "exec"), ns)               # noqa: S102 —— 基线自证用
    m = types.ModuleType(name)
    m.__dict__.update(ns)
    return m


def _mutate_mode(list_only: bool = False) -> int:
    print("!! 定点变异自证：逐条把「单一真源」改回改动前形态，套件必须转红\n")
    if list_only:
        for name, kind, rel, _o, _n, exp in _MUTATIONS:
            print("  %-46s [%s] expect_red>=%d  (%s)" % (name, kind, exp, rel))
        return 0
    anchor_miss, bad = [], []
    with contextlib.redirect_stdout(io.StringIO()):
        clean = _run_groups()
    print("  未变异基线：失败=%d（必须为 0）" % clean)
    if clean:
        bad.append("未变异基线即失败")

    for name, kind, rel, old, new, expect in _MUTATIONS:
        src = _rel_text(rel)
        if old not in src:
            print("  ANCHOR-MISS %s —— 锚点在 %s 源码里找不到（实现改了却没同步"
                  "本表；锚点漂移不得静默）" % (name, rel))
            anchor_miss.append(name)
            continue
        mut_src = src.replace(old, new, 1)
        _SRC[rel] = mut_src
        live = None
        try:
            if kind == "mod":
                live = sys.modules["md_cg.sustain"]
                mut = _exec_module("md_cg._autodef_mut", rel, mut_src)
                sys.modules["md_cg.sustain"] = mut
                globals()["sustain"] = mut
            with contextlib.redirect_stdout(buf := io.StringIO()):
                reds = _run_groups()
            detail = buf.getvalue()
        finally:
            if live is not None:
                sys.modules["md_cg.sustain"] = live
                globals()["sustain"] = _REAL_SUSTAIN
            _SRC.pop(rel, None)
        red_lines = [l for l in detail.splitlines()
                     if l.strip().startswith("FAIL ")]
        verdict = "红" if reds else "**仍全绿 = 该判据空转**"
        mark = "OK  " if reds >= expect else "MISMATCH"
        print("  %s %-46s 红项=%d 预期>=%d  %s"
              % (mark, name, reds, expect, verdict))
        for l in red_lines[:6]:
            print("        " + l.strip()[5:])
        if reds < expect:
            bad.append("%s（红=%d 预期>=%d）" % (name, reds, expect))

    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s"
          % ("PASS（每处判据都被打红）" if not bad else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def main() -> int:
    _sandbox_env()
    try:
        if "--mutate" in sys.argv:
            return _mutate_mode("--list" in sys.argv)
        n = _run_groups()
        print("\nauto_* 缺省单一真源守卫：%d 通过，%d 失败，%d 跳过"
              % (len(_PASS), n, len(_SKIP)))
        return 0 if not n else 1
    finally:
        try:
            _REAL_SUSTAIN.stop_all()
        except Exception:                              # noqa: BLE001
            pass
        _restore_env()
        shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
