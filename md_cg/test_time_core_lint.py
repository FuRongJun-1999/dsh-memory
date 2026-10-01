# -*- coding: utf-8 -*-
"""时间核审计器（E5 口径）＋ P3 图检索路守卫（`md_cg/test_time_core_lint.py`）。

## 为什么有这个文件

`md_cg/whitebox_kb/aeis_core/time_core.py` 的 docstring 明文点名：

    全库一切时间演化必须经本模块。核形状唯一（指数族），状态 X 与衰减率 γ 按对象
    配置；任何在本模块之外出现的衰减核实现（exp(-t/τ)、×(1-factor)、EMA 保持率）
    都是 bug——由 tools/time_core_lint.py 按 E5 口径机械化审计。

而**该审计器此前全仓不存在**（点名了、没人实现）。本文件把它补上，并按
工作纪律第 18 条的口径**落在已登记的 `md_cg/` 内**而不是新开顶层目录
（顶层目录 = `WORKSPACE_INDEX.md` 的结构面，新增会导致 `npm run gate` 的
`workspace_index.py --check` 腿亮红，而新增文件本轮按契约保持未追踪）。
`time_core.py` 的 docstring 已在原句后补上本实现的落地路径（原句逐字保留）。

## 审计口径（E5 · 四形态）

| 形态 | 判据（正则，作用在 **AST 代码段** 上——注释与 docstring 天然不入面） |
|---|---|
| `exp_kernel`      | `exp(-…`（自写指数衰减核） |
| `pow_half_life`   | `** (… days / DAYS / half_life …)`（幂式半衰期） |
| `one_minus_factor`| `1 - factor`（离散保持率） |
| `ema_retain`      | `… * retain` / `retain * …`（EMA 保持率） |

**登记制**（E5 要求「显式登记 + 等价性断言」，不是无限豁免）：

* `md_cg/whitebox_kb/aeis_core/time_core.py` = 核权威本体，整文件豁免；
* `md_cg/links.py:500` `factor = 0.5 ** (days / DECAY_DAYS)` = **同族半衰期写法**
  ——显式登记在 `REGISTRY`，并由本守卫 G2 **逐点等价性断言**证明
  `0.5**(d/DECAY_DAYS) == cred_factor(ln2/DECAY_DAYS, d)`；
  **刻意不动它的数值行为**（P_trust 读数零位移，G2e 给读数）。

未登记的形态一律**红**（审计器非空转，G1d 用注入核证明可拦性）。

## 守卫分组

G0 隔离与基线自证 · G1 E5 审计（含可拦性）· G2 links 同族等价性 + P_trust 零位移 ·
G3 **单位断言**（秒/天两喂法必须不同且天制正确）· G4 floor（含 300 天读数）·
G5 γ 缺省与可配 · G6 时间路接线（行为：路径分 = 天制 cred_factor）·
G7 **因果路两配置读数**（默认集 0 → 显式含 reference/part_of >0）+
S3 契约不变量 · G8 缺省与分路开关（mdcos 缺省集 + mcp_server 调用点）·
G9 N137 搬迁后边集合逐项相等 · G10 双侧同改披露面（键定义一致 + Rust 缺省路集差异）。

运行：
    python -X utf8 -m md_cg.test_time_core_lint
    python -X utf8 -m md_cg.test_time_core_lint --mutate
    python -X utf8 -m md_cg.test_time_core_lint --mutate --list

退出码（fail-closed）：0 全绿；1 有断言失败 / 变异未按预期转红；2 ANCHOR-MISS
（变异锚点在源码里找不到——实现改了却没同步本表，锚点漂移必须硬失败）。
"""
from __future__ import annotations

import ast
import contextlib
import io
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

from . import chain, links, nodefile
from .fsutil import atomic_write
from .mdcos import (MdCGOS, TEMPORAL_GAMMA_ENV, TEMPORAL_SCORE_FLOOR,
                    temporal_gamma)
from .whitebox_kb.aeis_core import time_core as TC

_PASS, _FAIL, _SKIP = [], [], []
_SRC = {}                     # 变异模式下供静态组读取的源码文本（rel → text）
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


# ---------------------------------------------------------------- E5 审计器

#: 审计面之外：核权威本体 + 本守卫自身（本文件的 PATTERNS 文本即含这些字样）
_EXEMPT = ("md_cg/whitebox_kb/aeis_core/time_core.py",
           "md_cg/test_time_core_lint.py")
_SKIP_DIRS = {".git", "__pycache__", "node_modules", "target", "lib",
              "build", "dist", ".venv", ".mypy_cache", ".zcode"}

#: 四形态（E5）：名 → (正则, 人类可读说明)
PATTERNS = (
    ("exp_kernel", re.compile(r"(?:math\.)?\bexp\s*\(\s*-"),
     "本模块外的指数衰减核 exp(-…)"),
    ("pow_half_life",
     re.compile(r"\*\*\s*\([^)]*\b(?:days|DAYS|half_life|halflife|HALF_LIFE)\b"),
     "幂式半衰期 0.5 ** (Δt/D)"),
    ("one_minus_factor", re.compile(r"1(?:\.0)?\s*-\s*factor"),
     "离散保持率 (1-factor)"),
    ("ema_retain", re.compile(r"\*\s*retain\b|\bretain\b\s*\*"),
     "EMA 保持率 x·retain"),
)

#: **登记表**：合法出现的同族写法（rel, 形态）→ (源码行原文, 理由)。
#: 登记项必须在源码里**逐字命中**（否则判「登记陈化」红）——登记表不得空转。
REGISTRY = {
    ("md_cg/links.py", "pow_half_life"): (
        "0.5 ** (days / DECAY_DAYS)",
        "同族半衰期（半衰期 30 天 = links.DECAY_DAYS）：与 "
        "cred_factor(ln2/DECAY_DAYS, d) 数值等价（G2 逐点断言）；"
        "**数值行为刻意不变**（P_trust 读数零位移）。"),
}


def _iter_files(root):
    """审计面：root 下所有 .py / .rs（跳过 _SKIP_DIRS）→ [(rel, abspath)]。"""
    out = []
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in _SKIP_DIRS]
        for f in sorted(fn):
            if not (f.endswith(".py") or f.endswith(".rs")):
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, root).replace("\\", "/")
            out.append((rel, p))
    return sorted(out)


def _py_hits(rel, text):
    """Python：只在 **AST 代码段** 上匹配（注释 / docstring 天然不入面）。"""
    hits = []
    try:
        tree = ast.parse(text)
    except SyntaxError as e:                       # 语法坏 → 显式报，不静默跳过
        return [(rel, int(getattr(e, "lineno", 0) or 0), "<syntax error>",
                 "parse_error")]
    seen = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Call, ast.BinOp)):
            continue
        seg = (ast.get_source_segment(text, node) or "").split("\n")[0].strip()
        if not seg:
            continue
        for name, rx, _d in PATTERNS:
            if rx.search(seg) and (node.lineno, name) not in seen:
                seen.add((node.lineno, name))
                hits.append((rel, node.lineno, seg, name))
    return hits


def _rs_hits(rel, text):
    """Rust：逐行正则（跳过注释行）——Rust 侧无 AST 面，注释行显式排除。"""
    hits = []
    for i, line in enumerate(text.split("\n"), 1):
        s = line.strip()
        if not s or s.startswith("//"):
            continue
        for name, rx, _d in PATTERNS:
            if rx.search(s):
                hits.append((rel, i, s, name))
    return hits


def audit(root=None, extra=None):
    """E5 审计：返回 (findings, stats)。

    findings 每项 `(rel, lineno, code, pattern, registered)`；`registered=True`
    表示命中登记表（合法）。`extra` = {rel: text} 覆盖面（供可拦性/变异注入用）。
    """
    root = root or _REPO
    overlay = dict(extra or {})
    findings, n_files, n_reg = [], 0, 0
    on_disk = _iter_files(root)
    disk_rels = {rel for rel, _p in on_disk}
    # 覆盖面：磁盘面 ∪ 注入面（注入面可含磁盘上不存在的新文件——可拦性/变异用）
    todo = list(on_disk) + [(rel, None) for rel in sorted(overlay)
                            if rel not in disk_rels]
    for rel, p in todo:
        if rel in _EXEMPT and rel not in overlay:
            continue
        if rel in overlay:
            text = overlay[rel]
        else:
            try:
                with open(p, encoding="utf-8") as f:
                    text = f.read()
            except (OSError, UnicodeDecodeError):
                continue
        n_files += 1
        hits = _py_hits(rel, text) if rel.endswith(".py") else _rs_hits(rel, text)
        for rel2, ln, code, pat in hits:
            reg = REGISTRY.get((rel2, pat))
            if reg is not None and code == reg[0]:
                n_reg += 1
                continue
            findings.append((rel2, ln, code, pat,
                             bool(reg is not None)))
    # 登记陈化：登记表里的行必须在源码里逐字命中
    for (rel, pat), (want, _why) in REGISTRY.items():
        p = os.path.join(root, rel)
        try:
            with open(p, encoding="utf-8") as f:
                src = overlay.get(rel, f.read())
        except OSError:
            findings.append((rel, 0, "<文件缺失>", pat, True))
            continue
        if want not in src:
            findings.append((rel, 0, "<登记陈化：源码里找不到该行> " + want,
                             pat, True))
    return findings, {"files": n_files, "registered": n_reg}


# ---------------------------------------------------------------- 沙箱

_TMP = tempfile.mkdtemp(prefix="mdcg_tclint_")
_GEN = [0]

_BODY = ("# 功能名：{n}\n# 生效条件：无条件\n# 子功能：无\n"
         "# 执行：无\n# 验证方式：test\n# 不适用条件：无\n\n正文 {n}。\n")


def _mk_node(root, nid, extra_fm=None, layer="knowledge", body=None):
    fm = {"id": nid, "layer": layer, "created_at": time.time(), "tags": []}
    fm.update(extra_fm or {})
    d = os.path.join(root, layer)
    os.makedirs(d, exist_ok=True)
    atomic_write(os.path.join(d, nid + ".md"),
                 nodefile.dumps(fm, body or _BODY.format(n=nid)))


def _fresh_root(tag):
    _GEN[0] += 1
    root = os.path.join(_TMP, "%s%d" % (tag, _GEN[0]))
    os.makedirs(root, exist_ok=True)
    return root


# ---------------------------------------------------------------- G0
def g0():
    print("== G0 隔离与基线自证 ==")
    kp = os.path.join(_REPO, "md_cg", "whitebox_kb", "aeis_core", "time_core.py")
    ok(os.path.isfile(kp), "G0a 核权威在位（time_core.py）")
    ok(callable(getattr(TC, "cred_factor", None)),
       "G0b cred_factor(gamma, dt, floor, ceil) 可取")
    ok("md_cg/test_time_core_lint.py" in (TC.__doc__ or "")
       and os.path.isfile(os.path.join(_REPO, "md_cg",
                                       "test_time_core_lint.py")),
       "G0c time_core docstring 点名的审计器**落地路径**在位（原句逐字保留，"
       "只在其后补落地实现——不再是悬空点名）")
    ok(_TMP.startswith(tempfile.gettempdir()),
       "G0d 全部实验库根落系统临时目录（绝不碰在役库）")


# ---------------------------------------------------------------- G1
def g1():
    print("== G1 E5 衰减核审计（含可拦性）==")
    findings, stats = audit()
    ok(stats["files"] >= 100,
       "G1a 审计面非空（%d 个 .py/.rs 入面）——防「扫描面为空 = 假绿」"
       % stats["files"], stats)
    ok(stats["registered"] == len(REGISTRY),
       "G1b 登记表逐条在源码里命中（%d 条）" % stats["registered"], stats)
    ok(findings == [],
       "G1c 未登记的衰减核实现 **零命中**（findings=%d）" % len(findings),
       findings[:5])
    # 可拦性：注入两种形态，审计器必须抓到（否则是空转）
    inj_py = ("import math\n\n\ndef f(g, dt, days, factor, retain):\n"
              "    a = math.exp(-g * dt)\n"
              "    b = 0.5 ** (days / 30.0)\n"
              "    c = x * retain\n"
              "    d = 1.0 - factor\n"
              "    return a, b, c, d\n")
    f2, _s2 = audit(extra={"md_cg/_injected_probe.py": inj_py})
    got = {x[3] for x in f2}
    ok({"exp_kernel", "pow_half_life", "ema_retain",
        "one_minus_factor"} <= got,
       "G1d 可拦性：注入四形态全部被抓（%s）" % sorted(got), sorted(got))
    # 核权威本体豁免：time_core.py 自己必须**不**进 findings
    ok(all(not x[0].endswith("aeis_core/time_core.py") for x in f2),
       "G1e 核权威本体豁免（注入不改写其豁免面）")


# ---------------------------------------------------------------- G2
def g2():
    print("== G2 links 同族半衰期：等价性断言 + P_trust 零位移 ==")
    D = float(links.DECAY_DAYS)
    g = math.log(2.0) / D
    pts = (0.0, 1.0, 7.0, 14.0, 30.0, 90.0, 300.0, 3650.0)
    bad = [(d, 0.5 ** (d / D), TC.cred_factor(g, d)) for d in pts
           if abs(0.5 ** (d / D) - TC.cred_factor(g, d)) > 1e-12]
    ok(not bad,
       "G2a 0.5**(d/DECAY_DAYS) == cred_factor(ln2/DECAY_DAYS, d) 逐点（%d 点）"
       % len(pts), bad)
    ok(abs(0.5 ** (30.0 / D) - 0.5) < 1e-12 and abs(TC.cred_factor(g, 30.0) - 0.5) < 1e-12,
       "G2b 半衰期刻度对齐：d=30 天处两式同为 0.5（与 links.py:53 同刻度）")
    # P_trust 读数：links.decay_all 的公式逐字来自 links.py:500，未改其数值行为
    before, init = 1.0, links.P_TRUST_INIT
    days = 10.0
    factor = 0.5 ** (days / D)
    after_links = max(0.0, min(1.0, round(init + (before - init) * factor, 6)))
    after_cred = max(0.0, min(1.0, round(
        init + (before - init) * TC.cred_factor(g, days), 6)))
    ok(after_links == after_cred,
       "G2c P_trust 读数零位移：links 式与 cred_factor 式同值"
       "（before=%.4f days=%.0f → after=%.6f）" % (before, days, after_links))
    src = _rel_text("md_cg/links.py")
    ok("factor = 0.5 ** (days / DECAY_DAYS)" in src
       and "math.exp" not in src,
       "G2d links.py 的衰减行**逐字未改**（本批不动其数值行为）")


# ---------------------------------------------------------------- G3
def g3():
    print("== G3 单位断言（γ 是「每天」的速率）==")
    g = temporal_gamma()
    dt_days = 7.0
    dt_secs = dt_days * 86400.0
    v_day = TC.cred_factor(g, dt_days, TEMPORAL_SCORE_FLOOR, 1.0)
    v_sec = TC.cred_factor(g, dt_secs, TEMPORAL_SCORE_FLOOR, 1.0)
    ok(math.isclose(v_day, math.exp(-g * dt_days), rel_tol=0, abs_tol=1e-12),
       "G3a 天制喂法正确：cred_factor(γ, 7.0) == exp(-γ·7) = %.6f" % v_day)
    ok(v_day != v_sec,
       "G3b 同一 Δt 秒/天两喂法**必须不同**（天=%.6f vs 秒=%.6f）"
       % (v_day, v_sec))
    ok(v_day > v_sec,
       "G3c 且天制正确方向：天制值 > 秒制值（秒制被 γ 放大 86400 倍衰减）")
    ok(math.isclose(TC.cred_factor(g, 0.0), 1.0, abs_tol=1e-12),
       "G3d Δt=0 → 1.0（新近度满值）")


# ---------------------------------------------------------------- G4
def g4():
    print("== G4 floor（不许老节点被乘成 0）==")
    g = temporal_gamma()
    f = TEMPORAL_SCORE_FLOOR
    raw300 = math.exp(-g * 300.0)
    ok(abs(raw300 - 0.5 ** 10) < 1e-12,
       "G4a 300 天（10 个半衰期）原值 = 0.5**10 = %.6f" % raw300)
    ok(TC.cred_factor(g, 300.0, f, 1.0) == f,
       "G4b floor 生效：300 天权重被夹到 floor=%.4f（原值 %.6f < floor）" % (f, raw300))
    ok(f < raw300 * 10 and f > 0.0,
       "G4c floor 取值理由可判：0 < floor=%.4f，且与 300 天原值同量级" % f)
    ok(TC.cred_factor(g, float("inf"), f, 1.0) == f,
       "G4d created_at 缺失（Δt=∞）→ floor，节点仍可召回（不被乘成 0）")
    ok(TC.cred_factor(g, 1.0) <= 1.0,
       "G4e ceil 生效：权重上界 1.0")


# ---------------------------------------------------------------- G5
def g5():
    print("== G5 γ 缺省与可配 ==")
    D = float(links.DECAY_DAYS)
    ok(abs(temporal_gamma() - math.log(2.0) / D) < 1e-15,
       "G5a 缺省 γ = ln2/%.0f天 = %.9f" % (D, math.log(2.0) / D))
    ok(abs(temporal_gamma({}) - math.log(2.0) / D) < 1e-15,
       "G5b 空 env → 缺省（与 MDCG_SPREAD_DECAY 同款读取单点）")
    ok(temporal_gamma({TEMPORAL_GAMMA_ENV: "0.1"}) == 0.1,
       "G5c env 可覆盖")
    for bad in ("乱写", "0", "-1", ""):
        ok(abs(temporal_gamma({TEMPORAL_GAMMA_ENV: bad})
               - math.log(2.0) / D) < 1e-15,
           "G5d 非法/非正 env %r → 回落缺省（不抛、不静默取 0）" % bad)
    ok(TEMPORAL_GAMMA_ENV in _rel_text("md_cg/hotcache.py"),
       "G5e MDCG_TEMPORAL_GAMMA 已登记进热路径缓存键的 env 开关清单"
       "（漏登即跨口径串味）")


# ---------------------------------------------------------------- G6
def g6():
    print("== G6 时间路接线（行为·排名项·不 _scan）==")
    root = _fresh_root("t")
    now = time.time()
    for nid, days in (("d0", 0), ("d7", 7), ("d30", 30), ("d400", 400)):
        ts = now - days * 86400.0
        _mk_node(root, nid, {"created_at": ts, "effective_from": ts})
    cg = MdCGOS(root)
    entries = cg._candidates()
    out = cg._path_temporal(entries, now - 1000 * 86400, now, None, None)
    sc = {n["id"]: s for n, s in out}
    g = temporal_gamma()
    ok(set(sc) == {"d0", "d7", "d30", "d400"},
       "G6a 时间算子启用 → 命中集（索引标量直读）全覆盖 %s" % sorted(sc))
    ok(sc["d7"] == round(TC.cred_factor(g, 7.0, TEMPORAL_SCORE_FLOOR, 1.0), 6),
       "G6b 路径分 = 天制 cred_factor（d7 → %.6f）；喂秒会得 %.6f（被 floor 夹）"
       % (sc["d7"], round(TC.cred_factor(g, 7.0 * 86400,
                                         TEMPORAL_SCORE_FLOOR, 1.0), 6)))
    ok(sc["d0"] > sc["d7"] > sc["d30"] > sc["d400"],
       "G6c 单调：越近越大 %s" % [sc[k] for k in ("d0", "d7", "d30", "d400")])
    ok(sc["d30"] == 0.5, "G6d 半衰期锚点：d30 → 0.5")
    ok(cg._path_temporal(entries, None, None, None, None) == [],
       "G6e 无时间算子/区间 → 本路恒空（默认查询零变更）")
    _r, m = cg.search_rrf("正文 d7", k=5, record=False,
                          start_time=now - 1000 * 86400, end_time=now)
    ok(m["paths"].get("temporal", 0) >= 1,
       "G6f 默认 paths 含 temporal 且启用时真有候选（%r）" % m["paths"])
    _r2, m2 = cg.search_rrf("正文 d7", k=5, record=False)
    ok(m2["paths"].get("temporal", 0) == 0,
       "G6g 未给时间参数 → temporal 路 0 候选（缺省查询零变更）")
    ok("cred_factor" in _rel_text("md_cg/mdcos.py"),
       "G6h 本模块**不写指数核**：核调用走 time_core.cred_factor")


# ---------------------------------------------------------------- G7
def g7():
    print("== G7 因果路：两配置读数（默认集 0 → 显式集 >0）==")
    root = _fresh_root("c")
    _mk_node(root, "ch1",
             {"edges": [{"target": "ch2", "relation_type": "reference",
                         "confidence": 0.6}]},
             body="# 功能名：ch1 苹果章\n# 生效条件：无条件\n# 子功能：无\n"
                  "# 执行：无\n# 验证方式：test\n# 不适用条件：无\n\n苹果 章节一。\n")
    _mk_node(root, "ch2",
             body="# 功能名：ch2\n# 生效条件：无条件\n# 子功能：无\n"
                  "# 执行：无\n# 验证方式：test\n# 不适用条件：无\n\n第二章。\n")
    env0 = os.environ.pop("MDCG_CHAIN_TYPES", None)
    try:
        cg = MdCGOS(root)
        _r, m_def = cg.search_rrf("苹果", k=5, record=False,
                                  paths=("lexical", "chain"))
        n_def = m_def["paths"].get("chain", 0)
        os.environ["MDCG_CHAIN_TYPES"] = "reference,part_of"
        cg2 = MdCGOS(root)
        r2, m_env = cg2.search_rrf("苹果", k=5, record=False,
                                   paths=("lexical", "chain"))
        n_env = m_env["paths"].get("chain", 0)
    finally:
        os.environ.pop("MDCG_CHAIN_TYPES", None)
        if env0 is not None:
            os.environ["MDCG_CHAIN_TYPES"] = env0
    ok(n_def == 0,
       "G7a 默认集（causal/sequential/applies_to）在 doc_ref 型语料上候选 = %d"
       "（只有 reference/part_of 边 → 恒空，正是「写死等于没接」的现场）" % n_def)
    ok(n_env > 0,
       "G7b 显式集含 reference/part_of → 候选 = %d（本批最要紧的一条：边类型集可配）"
       % n_env)
    ok(any(e.get("chain") for e in (m_env.get("provenance") or {}).values()
           for e in e),
       "G7c 命中的 provenance 带链（可审计「为什么召回它」）")
    ok(chain.chain_types_from_env({"MDCG_CHAIN_TYPES": "reference,part_of"})
       == ("reference", "part_of"),
       "G7d 读取单点解析 env（顺序 = 声明序）")
    ok(chain.chain_types_from_env({"MDCG_CHAIN_TYPES": "nope,unknown"})
       == chain.CHAIN_TYPES_DEFAULT,
       "G7e 未登记形态被剔除 → 回落缺省（不静默按 DEFAULT_EDGE_WEIGHT 走未知边）")
    ok(chain.chain_types_from_env({}) == chain.CHAIN_TYPES_DEFAULT,
       "G7f 未设 env → 缺省集一字不变")
    ok(chain.CHAIN_TYPES_ENV in _rel_text("md_cg/hotcache.py"),
       "G7g MDCG_CHAIN_TYPES 已登记进热路径缓存键的 env 开关清单")
    # S3 契约不变量（docs/hive/检索路径与认知结构契约_v0.1.md:21-53）
    ids_env = {n[0]["id"] for n in r2}
    ok("ch2" in ids_env,
       "G7h ③不引入未过 S2 门控的节点：chain 命中仍落在候选集内（allowed 过滤）")
    ok(chain.edge_weight({"relation_type": "reference"}) == 0.5
       and chain.edge_weight({"relation_type": "causal"}) == 0.85,
       "G7i ④边权沿用既有唯一权重表（reference .5 / causal .85）——未新造第二份")

    # ② 多跳 + 逐跳衰减：h1 --causal--> h2 --causal--> h3（种子在 h1）
    rh = _fresh_root("h")
    _mk_node(rh, "h1", {"edges": [{"target": "h2", "relation_type": "causal",
                                    "confidence": 1.0}]},
             body="# 功能名：h1\n# 生效条件：无条件\n# 子功能：无\n# 执行：无\n"
                  "# 验证方式：test\n# 不适用条件：无\n\n荔枝 起点。\n")
    _mk_node(rh, "h2", {"edges": [{"target": "h3", "relation_type": "causal",
                                    "confidence": 1.0}]},
             body="# 功能名：h2\n# 生效条件：无条件\n# 子功能：无\n# 执行：无\n"
                  "# 验证方式：test\n# 不适用条件：无\n\n中转。\n")
    _mk_node(rh, "h3", body="# 功能名：h3\n# 生效条件：无条件\n# 子功能：无\n"
                            "# 执行：无\n# 验证方式：test\n# 不适用条件：无\n\n"
                            "末端。\n")
    ch = MdCGOS(rh)
    rr_h, mm_h = ch.search_rrf("荔枝", k=8, record=False,
                               paths=("lexical", "chain"))
    prov_h = {(k, p.get("rank")): p for k, v in (mm_h.get("provenance") or {}).items()
              for p in v if p.get("path") == "chain"}
    dp = {k[0]: v.get("chain") and len(v["chain"]) - 1
          for k, v in prov_h.items()}
    ok(dp.get("h2") == 1 and dp.get("h3") == 2,
       "G7j ②沿 edges 多跳扩散（1 跳 h2 / 2 跳 h3；MAX_DEPTH_DEFAULT=5、decay=0.9 复用既有 chain 原语）"
       " 实测跳数=%r" % (dp,))
    # 链分逐跳乘衰减：同一批边权/置信度下，2 跳节点的链分必低于 1 跳节点。
    # 直接读 `_path_chain` 的**路内分**（RRF 只吃名次，路内分要单独取）。
    _ps, _ = ch._path_chain("荔枝", ch._candidates(), [({"id": "h1"}, 1.0)])
    _psc = {n["id"]: s for n, s in _ps}
    ok("h3" in _psc and _psc["h3"] < _psc.get("h2", 1.0),
       "G7k ②' 跳数越深链分越低（decay=0.9 逐跳乘）——h2=%.6f > h3=%.6f"
       % (_psc.get("h2", 0), _psc.get("h3", 0)))
    ch.close()

    # ③ 不得引入未过门控的节点：链上目标落 rejected 层（候选面已排除）
    rq = _fresh_root("q")
    _mk_node(rq, "s1", {"edges": [{"target": "q_neg", "relation_type": "causal",
                                    "confidence": 1.0}]},
             body="# 功能名：s1\n# 生效条件：无条件\n# 子功能：无\n# 执行：无\n"
                  "# 验证方式：test\n# 不适用条件：无\n\n龙眼 起点。\n")
    _mk_node(rq, "q_neg", body="# 功能名：q_neg\n# 生效条件：无条件\n# 子功能：无\n"
                               "# 执行：无\n# 验证方式：test\n# 不适用条件：无\n\n"
                               "被否决的结论。\n", layer="rejected")
    cq = MdCGOS(rq)
    rr_q, mm_q = cq.search_rrf("龙眼", k=8, record=False,
                               paths=("lexical", "chain"))
    hit_q = {t[0]["id"] for t in rr_q} | {k for k, v in
                                          (mm_q.get("provenance") or {}).items()
                                          for p in v if p.get("path") == "chain"}
    ok("q_neg" not in hit_q,
       "G7l ③' 未过门控（rejected 层，候选面已排除）的链上目标**不引入**"
       "（实测命中集=%r）" % sorted(hit_q))
    cq.close()


# ---------------------------------------------------------------- G8
def g8():
    print("== G8 缺省与分路开关（mdcos 缺省集 + mcp_server 调用点）==")
    import inspect
    from . import mcp_server
    d = inspect.signature(MdCGOS.search_rrf).parameters["paths"].default
    ok(d == ("lexical", "bucket", "entity", "graph", "chain", "temporal"),
       "G8a search_rrf 缺省 paths = 六路（两条图检索路进缺省集）", d)
    root = _fresh_root("d")
    _mk_node(root, "x1",
             body="# 功能名：x1\n# 生效条件：无条件\n# 子功能：无\n"
                  "# 执行：无\n# 验证方式：test\n# 不适用条件：无\n\n草莓。\n")
    cg = MdCGOS(root)
    pack = mcp_server._dispatch(cg, "mdcg_recall", {"query": "草莓", "k": 5})
    ok(set((pack.get("meta") or {}).get("paths") or {}) >=
       {"lexical", "bucket", "entity", "graph", "chain", "temporal"},
       "G8b mcp_server 缺省调用点：六路齐（含 chain/temporal）",
       (pack.get("meta") or {}).get("paths"))
    pack2 = mcp_server._dispatch(cg, "mdcg_recall",
                                 {"query": "草莓", "k": 5,
                                  "causal": False, "temporal": False})
    ok(set((pack2.get("meta") or {}).get("paths") or {})
       == {"lexical", "bucket", "entity", "graph"},
       "G8c ⑤每路可单独关：causal=false & temporal=false → 回到四路",
       (pack2.get("meta") or {}).get("paths"))
    m = _rel_text("md_cg/mcp_server.py")
    ok("or use_causal" in m and "use_temporal" in m,
       "G8d 融合口径照抄先例形态（同一表达式内追加 use_causal 条件）")
    ok('paths.append("chain")' in m and 'paths.append("temporal")' in m,
       "G8e 调用点显式列出两条新路（与 mdcos 缺省集同改，两侧不分裂）")


# ---------------------------------------------------------------- G9
def g9():
    print("== G9 N137：降级搬迁后边集合逐项相等 ==")
    root = _fresh_root("m")
    ts = time.time()
    _mk_node(root, "n1",
             {"created_at": ts, "edges": [{"target": "n2",
                                           "relation_type": "causal",
                                           "confidence": 0.8}],
              "subgraph": {"nodes": ["n2"]},
              "valid_from": ts - 100, "valid_until": ts + 100000,
              "effective_from": ts - 100, "effective_until": ts + 100000},
             body="# 功能名：n1\n# 生效条件：无条件\n# 子功能：无\n"
                  "# 执行：无\n# 验证方式：test\n# 不适用条件：无\n\n"
                  "上游条件 葡萄 触发。\n")
    _mk_node(root, "n2", body="# 功能名：n2\n# 生效条件：无条件\n# 子功能：无\n"
                              "# 执行：无\n# 验证方式：test\n# 不适用条件：无\n\n"
                              "下游结论 苹果 成立。\n")
    cg = MdCGOS(root)
    e0 = dict(cg.index["nodes"]["n1"])
    res = cg._move_layer("n1", "contextual", reason="N137 守卫")
    ok(bool(res) and res.get("to") == "contextual", "G9a 搬迁执行成功", res)
    e1 = cg.index["nodes"]["n1"]
    ok((e1.get("edges") or []) == (e0.get("edges") or [])
       and (e1.get("edges") or []) != [],
       "G9b 搬迁前后**边集合逐项相等**且非空（%r）" % (e1.get("edges"),))
    ok(e1.get("subgraph") == e0.get("subgraph"),
       "G9c subgraph 快照存活（递归展开免读盘）")
    for k in ("valid_from", "valid_until", "effective_from", "effective_until"):
        ok(k in e1 and e1.get(k) == e0.get(k),
           "G9d 双时间轴键 %s 存活（trust.validity 免读盘判定面）" % k)
    # 端到端：搬迁后因果路仍能经边召到下游（新路不再静默拿不到边）
    # 种子 = 词法命中 n1（上游），目标 n2 词面无重叠 —— 正是因果路的靶区。
    _r, m = cg.search_rrf("葡萄", k=5, record=False, paths=("lexical", "chain"))
    ok(m["paths"].get("chain", 0) >= 1
       and any(h[0]["id"] == "n2" for h in _r),
       "G9e 搬迁后 chain 路仍可达下游（%r）" % m["paths"])


# ---------------------------------------------------------------- G10
def g10():
    print("== G10 双侧同改披露面（键定义一致 + 缺省路集差异）==")
    py = _rel_text("md_cg/mdcos.py")
    rs = _rel_text("rust/src/retrieval.rs")
    ok('key=lambda x: (-x[1],\n' in py.replace("  ", " ")
       or "-float(x[0][\"frontmatter\"].get(\"importance\") or 0)" in py,
       "G10a Python 每路排序键在位（-score, -importance, id）")
    ok("b.score" in rs and "importance" in rs and "ida.cmp(&idb)" in rs,
       "G10b Rust sort_path 同三键在位（先例 docs/eval/优化第一批…:218-221 的"
       "「键定义一致」形态；**非**运行期逐位对拍）")
    eng = _rel_text("rust/src/engine.rs")
    ok("全部四路" in eng,
       "G10c 如实披露：Rust 侧缺省路集仍是四路（lexical/bucket/entity/graph）"
       "——本批**未**在 Rust 侧实现 chain/temporal，两侧缺省集不同")


# ---------------------------------------------------------------- 运行
def _rel_text(rel):
    if rel in _SRC:
        return _SRC[rel]
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


_GROUPS = (g0, g1, g2, g3, g4, g5, g6, g7, g8, g9, g10)


def _run_groups():
    del _PASS[:], _FAIL[:], _SKIP[:]
    for fn in _GROUPS:
        fn()
    return len(_FAIL)


# ===================== 定点变异自证（--mutate） =====================

_MUTATIONS = (
    ("P3-M1 自写指数核：mdcos 时间路不再走 cred_factor（退回被点名的 bug 形态）",
     "md_cg/mdcos.py",
     "            score = _tc.cred_factor(gamma, dt_days, TEMPORAL_SCORE_FLOOR, 1.0)\n",
     "            score = math.exp(-gamma * dt_days)\n", 1),
    ("P3-M2 γ 缺省漂移：ln2/30 天 → ln2/14 天（半衰期刻度不再锚定 links）",
     "md_cg/mdcos.py",
     "    return math.log(2.0) / float(DECAY_DAYS)\n",
     "    return math.log(2.0) / 14.0\n", 1),
    ("P3-M3 单位错：Δt 不再换算成「天」（喂秒，衰减放大 86400 倍）",
     "md_cg/mdcos.py",
     "                dt_days = abs(created - float(ref)) / 86400.0\n",
     "                dt_days = abs(created - float(ref))\n", 2),
    ("P3-M4 边类型集写死：chain_types_from_env 不读 env（doc 语料上恒空）",
     "md_cg/chain.py",
     "    raw = (environ or os.environ).get(CHAIN_TYPES_ENV)\n",
     "    raw = None\n", 1),
    ("P3-M5 N137 复发：_move_layer 的 _stage 条目不再带 edges",
     "md_cg/mdcg.py",
     "            \"edges\": fm.get(\"edges\") or [],\n"
     "            \"subgraph\": fm.get(\"subgraph\"),\n",
     "            \"subgraph\": fm.get(\"subgraph\"),\n", 2),
    ("P3-M6 缺省集退化：search_rrf 缺省不再含两条图检索路",
     "md_cg/mdcos.py",
     "                   paths=(\"lexical\", \"bucket\", \"entity\", \"graph\", \"chain\",\n"
     "                          \"temporal\"),\n",
     "                   paths=(\"lexical\", \"bucket\", \"entity\", \"graph\"),\n", 2),
    ("P3-M7 融合口径脱钩：mcp_server 不再把因果路纳入 max 缺省",
     "md_cg/mcp_server.py",
     "            \"max\" if (use_fuzzy or use_semantic or use_goal or use_causal) else None)\n",
     "            \"max\" if (use_fuzzy or use_semantic or use_goal) else None)\n", 1),
    ("P3-M8 links 数值行为被改：半衰期写法换成自写指数核",
     "md_cg/links.py",
     "            factor = 0.5 ** (days / DECAY_DAYS)\n",
     "            factor = math.exp(-days / DECAY_DAYS)\n", 2),
)

_MUT_FILES = tuple(sorted({m[1] for m in _MUTATIONS}))


def _mirror_build():
    """最小镜像树：md_cg（除 __pycache__）+ rust/src + data/policy.json + 根级
    utf8_boot.py（mcp_server.py 的入口自保证依赖它，缺了会在 G8 崩——镜像面
    必须覆盖被判据读到的模块依赖）。"""
    root = tempfile.mkdtemp(prefix="mdcg_tclint_mut_")
    shutil.copytree(os.path.join(_REPO, "md_cg"), os.path.join(root, "md_cg"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(os.path.join(_REPO, "rust", "src"),
                    os.path.join(root, "rust", "src"))
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    pol = os.path.join(_REPO, "data", "policy.json")
    if os.path.exists(pol):
        shutil.copy2(pol, os.path.join(root, "data", "policy.json"))
    boot = os.path.join(_REPO, "utf8_boot.py")
    if os.path.exists(boot):
        shutil.copy2(boot, os.path.join(root, "utf8_boot.py"))
    return root


def _reds_in(cwd):
    p = subprocess.run([sys.executable, "-X", "utf8", "-m",
                        "md_cg.test_time_core_lint"],
                       cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=900)
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode, [l.strip() for l in out.splitlines()
                          if l.strip().startswith("FAIL ") or
                          l.strip().startswith("ANCHOR-MISS")], out


def _mutate_mode(list_only=False):
    print("!! 定点变异自证：逐条把判据改回改动前形态，守卫必须转红\n")
    if list_only:
        for name, rel, _o, _n, exp in _MUTATIONS:
            print("  %-58s expect_red>=%d  (%s)" % (name[:58], exp, rel))
        return 0
    base = _mirror_build()
    try:
        rc, reds, out0 = _reds_in(base)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）"
              % (rc, len(reds)))
        for r in reds[:5]:
            print("      " + r)
        bad = []
        if reds:
            bad.append("未变异镜像基线即红")
        if rc != 0:
            # rc!=0 而零红项 = 守卫在镜像里**崩了**（如缺根级模块）——这类
            # 静默崩溃会让下面每一条变异都「红项不足」而看不出真因，必须响。
            bad.append("未变异镜像基线 rc=%d≠0（镜像面缺依赖或守卫崩溃）" % rc)
            print("      ——镜像基线尾部输出——")
            for line in (out0 or "").splitlines()[-12:]:
                print("      | " + line)
        anchor_miss, mismatch = [], []
        for name, rel, old, new, exp in _MUTATIONS:
            src_p = os.path.join(base, rel)
            with open(src_p, encoding="utf-8") as f:
                original = f.read()
            if old not in original:
                print("  ANCHOR-MISS %s —— 锚点在 %s 里找不到（实现改了却没同步"
                      "本表；锚点漂移不得静默）" % (name, rel))
                anchor_miss.append(name)
                continue
            with open(src_p, "w", encoding="utf-8", newline="\n") as f:
                f.write(original.replace(old, new, 1))
            try:
                rc2, reds2, out2 = _reds_in(base)
            finally:
                with open(src_p, "w", encoding="utf-8", newline="\n") as f:
                    f.write(original)
            crashed = "Traceback (most recent call last)" in (out2 or "")
            mark = "OK  " if len(reds2) >= exp and not crashed else "MISMATCH"
            print("  %s %-58s 红项=%d 预期>=%d %s"
                  % (mark, name[:58], len(reds2), exp,
                     "**未按预期转红**" if len(reds2) < exp
                     else ("**镜像崩溃而非判据转红**" if crashed else "")))
            for r in reds2[:4]:
                print("        " + r)
            if crashed:
                for line in (out2 or "").splitlines()[-6:]:
                    print("        | " + line)
            if len(reds2) < exp or crashed:
                mismatch.append("%s（红=%d 预期>=%d%s）"
                                % (name, len(reds2), exp,
                                   "，且镜像崩溃" if crashed else ""))
        if anchor_miss:
            print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
            print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
            return 2
        bad += mismatch
        print("\n定点变异自证：%s"
              % ("PASS（每处判据都被打红）" if not bad else "FAIL —— " + "、".join(bad)))
        return 0 if not bad else 1
    finally:
        shutil.rmtree(base, ignore_errors=True)


def main() -> int:
    try:
        if "--mutate" in sys.argv:
            return _mutate_mode("--list" in sys.argv)
        n = _run_groups()
        print("\n时间核审计 + P3 图检索路守卫：%d 通过，%d 失败，%d 跳过"
              % (len(_PASS), n, len(_SKIP)))
        return 0 if not n else 1
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
