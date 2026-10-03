# -*- coding: utf-8 -*-
"""test_job_id_segment_dot.py · 「`.` / `..`」**段级**判据的三处同判守卫（契约 c7/c8/c9）

# 功能名
job_id 的「`.` / `..`」判据从**整串**口径加固为**段级**口径的三处同判守卫（含存量实测、
语料在位、三处定点变异自证）。

# 生效条件
契约真源 = `docs/plans/全中文编码与蜂巢任务标识契约_v2.0.md` §四.4（拒收表「单独的 `.` 与
`..`」，2026-09-30 明确为**段级**读法：按 `_` 分段，**任一段**等于 `.` 或 `..` 即拒）。
三处读者（**必须同判**，任一处退回整串口径即本守卫红）：
  ① `hive/src/job.rs::valid_job_id`——判据单点。本守卫以**真 `hive.exe`** 读它的判定
     （`hive poll <id>` 的门就是它），故 live oracle 不是读码推断；
  ② `hive/hive_mcp/mcp_server.py::_job_id_reject_reason`（`_valid_job_id` = 前者 is None）；
  ③ `md_cg/units.py::_valid_job_id`（第三处读者）。该面有意保留两处本地放宽（**不要求
     `h` 前缀**、**允许 `-`**）——本守卫的形态矩阵**不含**依赖这两处差异的样例，故三处
     在矩阵上须**严格同判**（不设白名单）。
载体/位置：本文件（`hive/test_*.py`，`scripts/run_tests.py` 发现面内，跑法
`python -X utf8 -m hive.test_job_id_segment_dot`）。

# 子功能
  A 段级判据（c7）：`h_.._x` / `h_a_.._b` / 四槽与五段形态里的 `..` 段——三处**同判拒**，
    每条形态三处各一条断言（三面各自与期望比）+ 一条三处一致断言。
  B **范围边界**（c7「只加这一条，不许顺手收紧」的反证）：`h_..._x`（段是 `...` 而非
    `.`/`..`）、空段 `h__x`、非尾点 `.`（`h_a.b`）**仍收**（三处同判）。
  C 存量零迁移（c8）：在役 `hive/jobs` 的每个 `h*` 目录过三处闸，**判非法 0 个**（逐个列出
    结论；只读 poll，不写不建）。
  D 语料（c9）：段级 `..` 的两条 reject 例在语料内**在位**（hex 解码后逐字比对）且三处同判
    reject；另做全语料三方复算——与语料 verdict 逐例一致（md_cg 面**登记在案**的有意差异
    「允许 `-`」那一例除外；NUL 例 live exe 不可判，如实跳过而非猜）。
  E 定点变异自证（`--branch-baseline`）：三处判据各一处「**退回整串口径**」变异 ⇒ 本守卫
    转红；三处各一处**无关改名**假阳性对照 ⇒ 全绿（不误报）。红项集与退出码**逐项实测后
    写死**（不猜）。

# 执行
`python -X utf8 -m hive.test_job_id_segment_dot`（绿态）/ `--branch-baseline`（变异自证）。
退出码：0 = 全绿；1 = 有失败 / 变异红基线不符；2 = 变异锚点漂移（ANCHOR-MISS，fail-closed）。
隔离纪律：本守卫**只读**——exe 只跑 `poll`，一切 `HIVE_JOBS_DIR` 显式指向本进程自建临时池
（c8 那一组指向在役 `hive/jobs` 也**只读**）；变异改的是**临时物化副本**（Python 面 exec 进
模块 `__dict__`、Rust 面复制 crate 到临时目录编译），工作区源码只读。

# 验证方式
本守卫自身即判据面：A/B/C/D 四组在**真 hive.exe** 上逐例同判 + E 组三处定点变异 red/假阳性
green。守卫自身先接入口自保证 UTF-8（形态照 `scripts/run_tests.py` 的最小写法）。

# 不适用条件
不做「空段 / `...` 段 / 其它形态」的判据收紧（未被裁定，见 B 组反证）；不改语料 verdict 行
（语料侧只许补注释）；不覆盖非 Windows 宿主上设备名判据的松紧（另有守卫）。
"""
from __future__ import annotations

import argparse
import contextlib
import inspect
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

# ---------------------------------------------------------------- 入口自保证 UTF-8
# 工作纪律第 15 条：本调用必须在**任何文件/库 I/O 之前**——本守卫逐例喂真 `hive.exe` 中文
# id 并打印中文结论，自身在未开 UTF-8 模式的现场会崩且退出码与违例同码。形态照
# `scripts/run_tests.py` 的最小写法（助手在仓根，不是包目录）。
_UTF8_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _UTF8_ROOT not in sys.path:
    sys.path.insert(0, _UTF8_ROOT)
from utf8_boot import ensure_utf8  # noqa: E402

ensure_utf8(__file__)

_HERE = os.path.dirname(os.path.abspath(__file__))          # hive/
_REPO = os.path.dirname(_HERE)
for _p in (_REPO, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from hive.hive_mcp import mcp_server as _hm                    # noqa: E402
from md_cg import units as _units                              # noqa: E402

CORPUS_REL = "hive/id_contract_corpus_v2.txt"
JOB_RS_REL = "hive/src/job.rs"
MCP_REL = "hive/hive_mcp/mcp_server.py"
UNITS_REL = "md_cg/units.py"
JOBS_REL = "hive/jobs"

#: md_cg 面**登记在案**的有意差异（与 `hive/test_mdcg_units_charset_parity.py::_CORPUS_DIVERGENCES`
#: 同集）：md_cg 保留「允许 `-`」的既有对外契约 ⇒ 该例语料判 reject、md_cg 面判 accept。
#: 本守卫**不**放宽这条以外的任何例（多一条即红）。
_CORPUS_MDCG_DIVERGENCES = {"h_端-1_任务_记录单元_0001"}

#: 段级 `..` 的两条语料例（c9）：`(hex, 期望解出的 id)`——hex 与语料文件**逐字**比对。
_CORPUS_SEGMENT_ROWS = (
    ("685f2e2e5f78", "h_.._x"),
    ("685f615f2e2e5f62", "h_a_.._b"),
)

#: 形态矩阵（c7）：期望 = True（收）/ False（拒）。
#: **范围纪律**：只加「按 `_` 分段的任一段等于 `.` 或 `..`」这一条；`_ACCEPT_BOUNDARY`
#: 三例正是「未被裁定的形态不许顺手收紧」的反证。
_REJECT_FORMS = (
    ("h_.._x", "段 `..` 在中位（本批语料的载体形态）"),
    ("h_a_.._b", "段 `..` 在中位、两侧均为普通槽值"),
    ("h_.._任务_记录单元_0001", "四槽 id 形态里的 `..` 段"),
    ("h_端_任务_.._记录单元_0001", "五段形态（契约 §四.4「目录可作它的父段」）里的 `..` 段"),
    ("h_x_..", "整串落在 `..` 段上（既有整串/尾点判据已覆盖，回归钉点）"),
)
_ACCEPT_BOUNDARY = (
    ("h_..._x", "段是 `...` 而非 `.`/`..` ⇒ **不**在 c7 范围内（不得顺手拒）"),
    ("h__x", "空段 ⇒ 未被裁定的形态（不得顺手拒）"),
    ("h_a.b", "非尾点、非单独的 `.` ⇒ 既有 accept 契约（语料第 44 行同形）"),
)


# ------------------------------------------------------------ 结果收集与分组

_GROUPS: dict = {}
_CUR = ["?"]


def check(name: str, cond, detail: str = ""):
    """记一条断言（**不中断整组**——变异轮的「红项数」精确口径依赖它）。"""
    g = _GROUPS.setdefault(_CUR[0], {"n": 0, "fail": 0, "reds": []})
    g["n"] += 1
    if cond:
        print("  [ok]   %s" % name)
    else:
        g["fail"] += 1
        g["reds"].append(name)
        print("  [FAIL] %s%s" % (name, ("  ← %s" % detail) if detail else ""))


def begin(g: str, title: str):
    _CUR[0] = g
    _GROUPS.setdefault(g, {"n": 0, "fail": 0, "reds": []})
    print("\n== %s 组 %s ==" % (g, title))


# ------------------------------------------------------------ exe / 池 / 三处闸

_TMP_ROOTS: list = []
_PERSIST_ROOTS: list = []   # 变异轮的临时 crate 副本（全程存活：还原/再编译要它，末尾才清）


def _mkroot(tag: str) -> str:
    """本守卫自建的临时池根（一切 exe 调用的 `HIVE_JOBS_DIR` 都指这里，绝不指在役池）。"""
    d = tempfile.mkdtemp(prefix="segdot_%s_" % tag)
    _TMP_ROOTS.append(d)
    return d


def _cleanup():
    """清临时池（**不动**变异轮的 crate 副本根——`_BUILD` 缓存的 exe 路径要活到本轮结束）。"""
    for d in _TMP_ROOTS:
        shutil.rmtree(d, ignore_errors=True)
    _TMP_ROOTS.clear()


def _cleanup_all():
    _cleanup()
    for d in _PERSIST_ROOTS:
        shutil.rmtree(d, ignore_errors=True)
    _PERSIST_ROOTS.clear()
    _BUILD.clear()


def _exe() -> str:
    """真 `hive.exe`：env `HIVE_EXE` 覆盖（变异轮指向临时 crate 副本的产物）→ 工作区
    release 产物。"""
    e = os.environ.get("HIVE_EXE")
    if e:
        return e
    return os.path.join(_HERE, "target", "release",
                        "hive.exe" if os.name == "nt" else "hive")


def _missing_exe() -> str | None:
    e = _exe()
    return None if os.path.isfile(e) else e


def _cli(args, jobs: str | None = None, timeout: int = 120):
    """argv 列表直调真 exe（不经 shell；显式 UTF-8 + PYTHONUTF8=1）。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("HIVE_")}
    env["PYTHONUTF8"] = "1"
    if jobs:
        env["HIVE_JOBS_DIR"] = jobs
    p = subprocess.run([_exe()] + list(args), cwd=_REPO, env=env,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    return p.returncode, p.stdout or "", p.stderr or ""


def _rust_verdict(jid: str, jobs: str):
    """Rust 面判定：`hive poll <id>` 的门就是 `job::valid_job_id`（ok=true = 收）。
    NUL 进不了 argv ⇒ 返回 None（live oracle 不适用，如实声明而不是猜）。"""
    if "\x00" in jid:
        return None
    _rc, out, _err = _cli(["poll", jid], jobs=jobs)
    try:
        doc = json.loads(out.strip())
    except ValueError:
        return None
    return "accept" if doc.get("ok") else "reject"


def _mcp_verdict(jid) -> str:
    return "accept" if _hm._job_id_reject_reason(jid) is None else "reject"


def _units_verdict(jid) -> str:
    return "accept" if _units._valid_job_id(jid) else "reject"


_FACES = (("rust", _rust_verdict), ("mcp", lambda j, jobs: _mcp_verdict(j)),
          ("md_cg", lambda j, jobs: _units_verdict(j)))


def _three(jid: str, jobs: str) -> dict:
    return {name: (fn(jid, jobs) if name == "rust" else fn(jid, None))
            for name, fn in _FACES}


def _want(want: bool) -> str:
    return "accept" if want else "reject"


def _verdict_asserts(tag: str, jid: str, want: bool, jobs: str, why: str = ""):
    """一个形态四条断言：三面各自与期望比 + 一条三处一致（单面变异 ⇒ 该面断言与一致性
    断言同时转红；故变异轮的红项数可逐面写死）。"""
    got = _three(jid, jobs)
    label = "%s %r%s" % (tag, jid, ("（%s）" % why) if why else "")
    for name in ("rust", "mcp", "md_cg"):
        check("%s · %s 面判 %s" % (label, name, _want(want)),
              got[name] == _want(want), "实得 %s（三面＝%s）" % (got[name], got))
    check("%s · 三处同判" % label, len(set(got.values())) == 1, "三面＝%s" % got)


# ================================================================== A 组

def g_a():
    begin("A", "段级 `..` 判据（c7：按 `_` 分段，任一段等于 `.`/`..` 即拒；三处同判）")
    check("A0 前置：真 hive.exe 在盘（Rust 面的 live oracle）", _missing_exe() is None,
          "未找到 %s" % (_missing_exe() or ""))
    root = _mkroot("a")
    jobs = os.path.join(root, "jobs")
    os.makedirs(jobs, exist_ok=True)
    for jid, why in _REJECT_FORMS:
        _verdict_asserts("A·段级 .. 拒", jid, False, jobs, why)


# ================================================================== B 组

def g_b():
    begin("B", "范围边界（c7「只加一条」的反证：`...` 段 / 空段 / 非尾点 `.` **仍收**）")
    root = _mkroot("b")
    jobs = os.path.join(root, "jobs")
    os.makedirs(jobs, exist_ok=True)
    for jid, why in _ACCEPT_BOUNDARY:
        _verdict_asserts("B·范围外仍收", jid, True, jobs, why)


# ================================================================== C 组

def g_c():
    begin("C", "存量零迁移（c8：在役 hive/jobs 的 h* 目录被三处闸判非法者必须为 0）")
    pool = os.path.join(_REPO, *JOBS_REL.split("/"))
    names = []
    if os.path.isdir(pool):
        names = sorted(n for n in os.listdir(pool)
                       if n.startswith("h") and os.path.isdir(os.path.join(pool, n)))
    if not names:
        # 干净检出 / CI 无在役台账（hive/jobs 为 gitignored 本地产物）：本组语义是
        # 「存量零迁移」，无存量时**显式跳过**——如实标记、不静默、不假绿（对比：
        # 原 C0 以 FAIL 表达「防空池假绿」，但未区分「无存量」与「存量违规」两态
        # ——2026-10-03 CI 实测该组在空池下长期红；单跑者同判）。
        print("  [SKIP] C 组跳过：无在役 job 台账（%s 不存在或为空——干净检出 / CI 的预期形态）" % pool)
        return
    check("C0 前置：在役池可枚举且非空（防空池假绿）", bool(names),
          "池=%s 实得 %d 个 h* 目录" % (pool, len(names)))
    bad, rows = [], []
    for n in names:
        got = _three(n, pool)
        rows.append((n, got))
        if any(v != "accept" for v in got.values()):
            bad.append("%s→%s" % (n, got))
    for n, got in rows:
        print("     · %-28s rust=%-6s mcp=%-6s md_cg=%-6s"
              % (n, got["rust"], got["mcp"], got["md_cg"]))
    check("C1 存量 %d 个目录被三处闸判非法者 = 0（逐个结论见上）" % len(names),
          not bad, "；".join(bad[:4]))


# ================================================================== D 组

def _corpus_rows():
    with open(os.path.join(_REPO, *CORPUS_REL.split("/")), encoding="utf-8") as f:
        raw = f.read()
    rows = []
    for ln, line in enumerate(raw.split("\n"), 1):
        line = line.rstrip("\r")
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        rows.append((ln, cols[0].strip(), cols[1].strip(),
                     bytes.fromhex(cols[1].strip()).decode("utf-8"),
                     cols[2].strip() if len(cols) > 2 else ""))
    return rows


def g_d():
    begin("D", "语料（c9：段级 `..` 两例在位且三处同判；全语料三方复算逐例一致）")
    rows = _corpus_rows()
    check("D0 语料可读且例数非退化（防读出空表假绿）", len(rows) >= 50, "%d 例" % len(rows))
    want = {hexs: jid for hexs, jid in _CORPUS_SEGMENT_ROWS}
    hit = [(ln, hexs, jid, v) for ln, v, hexs, jid, _d in rows if hexs in want]
    check("D1 段级 `..` 两例在语料内**在位**（hex 逐字比对，解出的 id 亦须对上）",
          sorted((h, j) for _l, h, j, _v in hit) ==
          sorted((h, j) for h, j in _CORPUS_SEGMENT_ROWS),
          "实得 %r 期望 %r" % ([(h, j) for _l, h, j, _v in hit], list(_CORPUS_SEGMENT_ROWS)))
    check("D2 两例的 verdict 行均为 reject（不许为迁就实现改 verdict）",
          all(v == "reject" for _l, _h, _j, v in hit),
          "实得 %r" % [(l, v) for l, _h, _j, v in hit])
    root = _mkroot("d")
    jobs = os.path.join(root, "jobs")
    os.makedirs(jobs, exist_ok=True)
    for _l, hexs, jid, _v in hit:
        _verdict_asserts("D·语料例", jid, False, jobs, "hex=%s" % hexs)

    # ---- 全语料三方复算（NUL 例的 live exe 面不可判 ⇒ 如实跳过，不猜）
    mcp_bad, rust_bad, units_bad, nul = [], [], [], 0
    for ln, verdict, _hexs, jid, desc in rows:
        w = _want(verdict == "accept")
        rv = _rust_verdict(jid, jobs)
        if rv is None:
            nul += 1
        if _mcp_verdict(jid) != w:
            mcp_bad.append("行%d %r" % (ln, jid))
        if rv is not None and rv != w:
            rust_bad.append("行%d %r" % (ln, jid))
        if _units_verdict(jid) != w and jid not in _CORPUS_MDCG_DIVERGENCES:
            units_bad.append("行%d %r" % (ln, jid))
    check("D3 全语料 MCP 面逐例与 verdict 一致", not mcp_bad, "；".join(mcp_bad[:4]))
    check("D4 全语料 Rust 面逐例与 verdict 一致（NUL 例不可判，如实跳过 %d 例）" % nul,
          not rust_bad, "；".join(rust_bad[:4]))
    check("D5 全语料 md_cg 面逐例一致（仅登记在案的有意差异「允许 -」一例除外）",
          not units_bad, "；".join(units_bad[:4]))


# ================================================================== E 组：定点变异自证

#: Rust 面变异（c7）：**段级判据整段退场**——退回「只剩整串 `.`/`..` 与尾点」的旧口径。
_R_SEG_OLD = """    if id.split('_').any(|seg| seg == "." || seg == "..") {
        return false;
    }
"""
_R_SEG_NEW = ""

#: MCP 面变异（c7）：同上的「退回整串口径」。
_M_SEG_OLD = """    if any(seg in (".", "..") for seg in jid.split("_")):
        return ("job_id 的某一段是相对路径段（`.` / `..`）"
                "——段级判据：任一段等于 `.` 或 `..` 即拒（该段可能被当目录名或父目录段用）")
"""
_M_SEG_NEW = "    pass\n"

#: md_cg 面变异（c7）：同上的「退回整串口径」。
_U_SEG_OLD = """    if any(seg in (".", "..") for seg in jid.split("_")):
        return False
"""
_U_SEG_NEW = "    pass\n"

#: 假阳性对照（无关改名；c7 判据面一字不动）：三处各一。
_FP_R_OLD = ".find(|(en, zh)| *en == unit || *zh == unit)"
_FP_R_NEW = ".find(|(en, zhn)| *en == unit || *zhn == unit)"
_FP_PY_OLD = '    base = s.split(".")[0].translate(_ASCII_UPPER)\n    return base in RESERVED_DEVICE_NAMES\n'
_FP_PY_NEW = '    bs = s.split(".")[0].translate(_ASCII_UPPER)\n    return bs in RESERVED_DEVICE_NAMES\n'

#: 变异表：`(标签, 面, 载荷, 期望)`。
#:   面 `"fn"`  ：载荷 `(模块键, 函数名, 原串, 新串)`——源码级替换后 exec 回**活模块**；
#:   面 `"rust"`：载荷 `(副本内相对路径, 原串, 新串)`——`_BUILD` 的**临时 crate 副本**上改
#:                 源码（工作区只读），重编译后喂 `HIVE_EXE`。
#: 期望 `(退出码, {组: 红项数})`——**逐项实测后写死**（实测命令 =
#: `python -X utf8 -m hive.test_job_id_segment_dot --branch-baseline`，2026-09-30 本机实测）：
#: 三处变异各自 **红项=13 / 退出码=1 / 命中组 {A:8, D:5}**（三处**红项集内容不同**、计数相同）：
#:   · A:8 = 4 个「含 `..` 段且**不以点结尾**」的形态 ×（该面 1 条 + 三处一致 1 条）；
#:     第 5 个形态 `h_x_..` 不红——它同时被**尾点**判据拒（尾点判据不在本变异范围内），
#:     变异体上仍判 reject ⇒ 该条断言如实保持绿（**不是**漏网：尾点面由 A 组回归钉点覆盖）。
#:   · D:5 = 两条语料例各 2 条（该面 + 一致）+ 该面的全语料复算 1 条——三条复算断言
#:     （D3/D4/D5）按面分列，故三处各自命中的**是各自那一条**。
_MUTATIONS = (
    ("Rust 面 `.`/`..` 段级判据**退回整串口径**（删掉 `id.split('_')` 那一段判据）",
     "rust", ("src/job.rs", _R_SEG_OLD, _R_SEG_NEW), (1, {"A": 8, "D": 5})),
    ("MCP 面 `.`/`..` 段级判据退回整串口径（`h_.._x` 重新被收）",
     "fn", ("mcp", "_job_id_reject_reason", _M_SEG_OLD, _M_SEG_NEW), (1, {"A": 8, "D": 5})),
    ("md_cg 面 `.`/`..` 段级判据退回整串口径（`h_.._x` 重新被收）",
     "fn", ("mdcg", "_valid_job_id", _U_SEG_OLD, _U_SEG_NEW), (1, {"A": 8, "D": 5})),
)

#: 假阳性对照表：`(标签, 面, 载荷)`——**无关改名**，期望恒为「红项 0 / 退出码 0」。
_FALSE_POSITIVES = (
    ("Rust 面无关改名：`unit_canonical` 的闭包参数 `zh` → `zhn`（与 `.`/`..` 判据无关）",
     "rust", ("src/job.rs", _FP_R_OLD, _FP_R_NEW)),
    ("MCP 面无关改名：`_is_reserved_device_name` 的局部 `base` → `bs`（判据逻辑一字不动）",
     "fn", ("mcp", "_is_reserved_device_name", _FP_PY_OLD, _FP_PY_NEW)),
    ("md_cg 面无关改名：同上函数的局部 `base` → `bs`",
     "fn", ("mdcg", "_is_reserved_device_name", _FP_PY_OLD, _FP_PY_NEW)),
)


def _func_src(which: str, fn: str):
    """函数源码文本：从 `def <name>(` 行起截断再 dedent（本仓排版为「顶格注释 + def」，
    直接 dedent 会因公共前缀为 0 而留缩进）；取源失败返回 None（按锚点漂移处置）。"""
    try:
        src = inspect.getsource(_HOLDERS[which].__dict__[fn])
        return textwrap.dedent(src[src.index("def %s(" % fn):])
    except Exception:                     # noqa: BLE001 —— 取源失败按锚点漂移处理
        return None


_HOLDERS = {"mcp": _hm, "mdcg": _units}


def _patch_fn(which: str, fn: str, old: str, new: str):
    """源码含 `old` **恰好一次**时替换并 exec 进模块 `__dict__`（活命名空间）。返回还原回调；
    锚点不唯一 / 取源失败返回 None。"""
    src = _func_src(which, fn)
    if src is None or src.count(old) != 1:
        return None
    mod = _HOLDERS[which]
    orig = mod.__dict__[fn]
    exec(compile(src.replace(old, new), "segdot_mut.py", "exec"), mod.__dict__)

    def _restore():
        mod.__dict__[fn] = orig

    return _restore


_BUILD: dict = {}


def _build_env():
    """把 hive crate 复制进临时目录（**工作区源码只读**：变异改的是副本）。
    区块表数据一并搬：`job.rs` 以 `include_str!` 编译期嵌入它，副本缺它 = 编译失败。"""
    if _BUILD.get("exe"):
        return _BUILD
    root = tempfile.mkdtemp(prefix="segdot_build_")
    _PERSIST_ROOTS.append(root)
    crate = os.path.join(root, "crate")
    os.makedirs(crate)
    shutil.copy2(os.path.join(_HERE, "Cargo.toml"), os.path.join(crate, "Cargo.toml"))
    lock = os.path.join(_HERE, "Cargo.lock")
    if os.path.isfile(lock):
        shutil.copy2(lock, os.path.join(crate, "Cargo.lock"))
    shutil.copytree(os.path.join(_HERE, "src"), os.path.join(crate, "src"))
    shutil.copy2(os.path.join(_HERE, "id_charset_blocks.txt"),
                 os.path.join(crate, "id_charset_blocks.txt"))
    _BUILD.update({"dir": crate, "target": os.path.join(root, "target"),
                   "exe": os.path.join(root, "target", "release",
                                       "hive.exe" if os.name == "nt" else "hive")})
    return _BUILD


def _cargo_build():
    if shutil.which("cargo") is None:
        return False, "cargo 不在 PATH（定点变异自证需要 rust 工具链）"
    env = dict(os.environ)
    env["CARGO_TARGET_DIR"] = _BUILD["target"]
    env["PYTHONUTF8"] = "1"
    try:
        p = subprocess.run(["cargo", "build", "--release"], cwd=_BUILD["dir"], env=env,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=900)
    except Exception as exc:              # noqa: BLE001
        return False, "cargo 调用异常: %s: %s" % (type(exc).__name__, exc)
    return p.returncode == 0, ((p.stdout or "") + (p.stderr or ""))[-1200:]


def _patch_rust(rel_path: str, anchor: str, new: str):
    """字节级读写（不翻译行尾），锚点在副本中出现**恰好一次**才替换。"""
    p = os.path.join(_BUILD["dir"], rel_path)
    try:
        with open(p, "rb") as f:
            src_b = f.read()
    except OSError:
        return None
    try:
        src = src_b.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if src.count(anchor) != 1:
        return None
    with open(p, "wb") as f:
        f.write(src.replace(anchor, new).encode("utf-8"))

    def _restore():
        with open(p, "wb") as f2:
            f2.write(src_b)

    return _restore


def _run_groups(only=None):
    _GROUPS.clear()
    for g, fn in (("A", g_a), ("B", g_b), ("C", g_c), ("D", g_d)):
        if only and g not in only:
            continue
        fn()
    total = sum(v["fail"] for v in _GROUPS.values())
    per = {k: v["fail"] for k, v in _GROUPS.items()}
    return total, per


def _branch_baseline() -> int:
    print("!! 定点变异模式：把 `.`/`..` 判据在**临时物化副本**上退回整串口径，本守卫应当转红；"
          "无关改名应全绿\n")
    with contextlib.redirect_stdout(io.StringIO()):
        clean_fail, _clean = _run_groups()
    _cleanup()
    print("  未变异基线：失败=%d，退出码=%d" % (clean_fail, 1 if clean_fail else 0))
    if clean_fail:
        print("  基线即失败 → 定点变异自证无意义（先修基线）")
        _cleanup_all()
        return 1
    bad = []
    for label, face, payload, expect in _MUTATIONS:
        if face == "rust":
            rel, old, new = payload
            _build_env()
            ok, log = _cargo_build()
            if not ok:
                print("  编译失败 %s：%s" % (label, log[-300:]))
                _cleanup_all()
                return 2
            restore = _patch_rust(rel, old, new)
            if restore is None:
                print("  ANCHOR-MISS %s —— 变异锚点漂移（实现改了却没同步本表；副本内 %s）"
                      % (label, rel))
                _cleanup_all()
                return 2
            os.environ["HIVE_EXE"] = _BUILD["exe"]
            try:
                ok2, log2 = _cargo_build()
                if not ok2:
                    print("  变异体编译失败 %s：%s" % (label, log2[-300:]))
                    _cleanup_all()
                    return 2
                with contextlib.redirect_stdout(io.StringIO()):
                    got_fail, got_groups = _run_groups()
            finally:
                restore()
                os.environ.pop("HIVE_EXE", None)
                _cleanup()
        else:
            restore = _patch_fn(*payload)
            if restore is None:
                print("  ANCHOR-MISS %s —— 变异锚点漂移（实现改了却没同步本表；基线源=%s.%s）"
                      % (label, payload[0], payload[1]))
                _cleanup_all()
                return 2
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    got_fail, got_groups = _run_groups()
            finally:
                restore()
                _cleanup()
        got_rc = 1 if got_fail else 0
        hit = {g: n for g, n in got_groups.items() if n}
        if expect is None:
            print("  [未标定] 改坏「%s」→ 红项=%d，退出码=%d，命中组=%s"
                  % (label, got_fail, got_rc, dict(sorted(hit.items()))))
            continue
        want_rc, want_hit = expect
        if hit == want_hit and got_fail == sum(want_hit.values()) and got_rc == want_rc:
            print("  改坏「%s」→ 红项=%d，退出码=%d，命中组=%s（恰好命中预期）"
                  % (label, got_fail, got_rc, dict(sorted(hit.items()))))
        else:
            print("  改坏「%s」→ 红项=%d，退出码=%d，命中组=%s  期望 红项=%d/退出码=%d/组=%s"
                  "  **红基线失效（判别力面不符）**"
                  % (label, got_fail, got_rc, dict(sorted(hit.items())),
                     sum(want_hit.values()), want_rc, dict(sorted(want_hit.items()))))
            bad.append(label)

    for fp_label, fp_face, fp_payload in _FALSE_POSITIVES:
        if fp_face == "rust":
            rel, old, new = fp_payload
            _build_env()
            ok, log = _cargo_build()
            if not ok:
                print("  假阳性对照编译失败 %s：%s" % (fp_label, log[-300:]))
                _cleanup_all()
                return 2
            fp_restore = _patch_rust(rel, old, new)
            if fp_restore is None:
                print("  ANCHOR-MISS 假阳性对照锚点漂移（%s）" % fp_label)
                _cleanup_all()
                return 2
            os.environ["HIVE_EXE"] = _BUILD["exe"]
            try:
                ok2, log2 = _cargo_build()
                if not ok2:
                    print("  假阳性对照编译失败 %s：%s" % (fp_label, log2[-300:]))
                    _cleanup_all()
                    return 2
                with contextlib.redirect_stdout(io.StringIO()):
                    fp_fail, fp_groups = _run_groups()
            finally:
                fp_restore()
                os.environ.pop("HIVE_EXE", None)
                _cleanup()
        else:
            fp_restore = _patch_fn(*fp_payload)
            if fp_restore is None:
                print("  ANCHOR-MISS 假阳性对照锚点漂移（%s）" % fp_label)
                _cleanup_all()
                return 2
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    fp_fail, fp_groups = _run_groups()
            finally:
                fp_restore()
                _cleanup()
        if fp_fail == 0:
            print("  假阳性对照「%s」→ 红项=0，退出码=0 —— 本守卫不误报" % fp_label)
        else:
            print("  假阳性对照「%s」→ 红项=%d，命中组=%s  **误报**"
                  % (fp_label, fp_fail, {g: n for g, n in fp_groups.items() if n}))
            bad.append("假阳性对照(%s)" % fp_label)
    print("\n定点变异自证：%s" % ("PASS（三处判据各有断言把它钉死，且无关改名不误报）"
                                  if not bad else "FAIL —— " + "、".join(bad)))
    _cleanup_all()
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="job_id 段级 `.`/`..` 判据三处同判守卫（c7/c8/c9）")
    ap.add_argument("--branch-baseline", action="store_true",
                    help="定点变异自证（三处判据各退回整串口径 + 三处假阳性对照）")
    args = ap.parse_args()
    if args.branch_baseline:
        return _branch_baseline()
    total, per = _run_groups()
    print("\n---- 分组 ----")
    for g in ("A", "B", "C", "D"):
        v = _GROUPS.get(g, {"n": 0, "fail": 0})
        print("  [%s] %d 条断言，失败 %d" % (g, v["n"], v["fail"]))
    print("\n结果：%d 条断言，失败 %d" % (sum(v["n"] for v in _GROUPS.values()), total))
    if total:
        for g, v in _GROUPS.items():
            for r in v["reds"]:
                print("   红: [%s] %s" % (g, r))
    else:
        print("ALL OK：`.`/`..` 段级判据三处同判（真 exe / MCP / md_cg）；"
              "范围边界未收紧；存量零迁移；语料两例在位且全语料逐例一致")
    _cleanup_all()
    return 0 if not total else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                 # noqa: BLE001
            pass
    sys.exit(main())
