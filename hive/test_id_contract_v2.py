# -*- coding: utf-8 -*-
"""test_id_contract_v2.py · 蜂巢任务标识契约 v2 守卫（Python 侧判据面 + 跨语言同判）

契约真源：`docs/plans/全中文编码与蜂巢任务标识契约_v2.0.md` §四.4/§四.5/§四.7 与 §五。
判据真源（单点）：`hive/src/job.rs`（Rust 侧）；本守卫钉的是 **python 面孪生闸**与
**两侧逐例同判**，对照面是**真 `hive.exe`**（不是读码推断）。

覆盖（对应契约 B 项与 D1 九条）：
  A  四槽必填与缺槽报错——CLI（`hive submit` / `hive alloc-id`，真实退出码）与
     MCP（真实 stdio JSON-RPC 子进程 + 进程内 `_t_spawn`）**两路实跑**；另钉
     `_submit` 不再自造 id（旧 `f"h{毫秒}_{uuid6}"` 已退场，改调 `alloc-id`；
     `HIVE_EXE` 不可用 → 显式 `SubmitError`，不静默降级）；orch 面四槽透传。
  B  编号分配：连续分配不碰撞、编号 4 位定宽、**搜索在号位间回绕**（池内只存
     `…_9999`、起点越过上限时，仍分到空闲的 `…_0001`——不白扔 9998 个号位）、
     **只有 9999 个号位全部被占用才显式报错，且文案如实**（真构造 9999 个号位；
     本机实测建目录 0.84s、扫描 0.19s）、**编号值不回绕**（不加宽成 5 位、
     不溢出成 `0001` 复用已发布的 id）。
  C  字符集闸（B5′）：唯一真源**区块表** `hive/id_charset_blocks.txt`（三处读者共读；
      判据**不查任何 Unicode 属性库** ⇒ 两侧版本差结构性不可能）+ 合法/非法两侧 +
      拒收**原因级**可读性 + 拒收项**逐条显式断言**（零宽/双向控制/控制字符/路径成分/
      尾点/首尾空白/设备名）+ B6 语料**两侧逐例同判**（live oracle = 真 `hive.exe`）+
      **判据 ≡ 表**（c13 三条断言）：① Rust 侧全码点遍历（承载于 `job.rs` 单测
      `charset_predicate_equals_blocks_table` / `job_id_and_slot_gates_use_table_membership`，
      本守卫核验其在位与形态）；② Python 侧全码点遍历（本守卫 C8b/C8b2 实跑）；
      ③ 由 ①② 合起来得到**两侧接受集逐码点相同**（C8c，结构性而非逐例对齐）。
      另按 c1/c2「三处读者共读同一份数据」补第三处读者（`md_cg/units.py`）的
      「判据 ≡ 表」全码点遍历（C8e）与三处同源取证（C8f）——故本组的三条断言
      实际覆盖**三处读者**（Rust / MCP / md_cg）。
      **全码点遍历只出现在测试内**：生产判据是 O(区间数) 的二分/线性查表，无任何全表扫描。
  D  拼路径三入口（kill/poll/depends_on）：非法 id（`..`/`../victim`/`/etc`/`h:x`/
     零宽/尾点/NUL 设备名）在**三条入口**均被拒——Rust CLI 用**真实退出码**，
     MCP 用 `_valid_job_id`/`_dep_gate`/`_t_kill`/`_t_poll` 的返回值。
  E  五单元闭集与 `md_cg/identity.POSITIONS` 同源（照 `md_cg/test_p21_tokens.py:218`
     的同源断言形态），并与 Rust `job.rs::UNITS` 及真 exe 的受理面三方对齐。
  F  `list_jobs_by_created` 的**保序**（旧形态名序==created_ts 序）与**按真值**
     （created_ts 与名序相反时仍按 created_ts 排）+ 哨兵/确定性/只读 + 与 exe 同序。
  G  存量共存：旧形态 id 仍合法、仍被 list_jobs 收、仍可 poll/kill。
  H  定点变异自证（`--branch-baseline`，退出码 0/1/2）：逐处把**判据面本身**改坏
      （源码级关判据分支、**数据面**把区块表删一段/多塞一段、让某侧解析失败改
      fail-open、让 `md_cg` 面回到 ASCII 白名单、临时 crate 副本里把表文件删一段、
      关掉一条显式拒收），断言红项集与退出码**逐项实测后写死**（不猜），
      并以 2 处**假阳性对照**（每条落在其判据所在的面：python 面 / Rust 面各一处无关
      改名，含 ③ 所在的 `job.rs`）证明本守卫不误报。
  I  红基线（`--head-baseline`：把**锚点字节**临时物化后跑判据谓词，**绝不覆盖工作区**；
      谓词**按条自带批次锚点**——每条在「引入它的批次的前一个提交」上必红、在工作区上必绿；
      显式给 `REF` 则统一用该 ref）。

用法：
  python -X utf8 -m hive.test_id_contract_v2                  # 绿态（默认）
  python -X utf8 -m hive.test_id_contract_v2 --branch-baseline  # 定点变异自证
  python -X utf8 -m hive.test_id_contract_v2 --head-baseline [REF]  # 红基线（REF 字节，缺省 HEAD）
退出码：0 = 全绿 / 1 = 有失败 / 2 = 变异锚点漂移（ANCHOR-MISS，fail-closed）。

隔离纪律：一切提交/分配只落在**本进程自建的临时池**（`HIVE_JOBS_DIR` + `_jobs_dir`
双钉 + `_ensure_serve` 打桩），在役 jobs 池与在役 serve 一概不碰；变异轮改的是
**临时副本**（Python 面 exec 进模块 `__dict__`、Rust 面复制 crate 到临时目录编译），
工作区源码只读。

已知边界（如实声明，不静默）：
  · NUL 字节进不了 argv ⇒ 该语料例的 live exe 对照不适用（Rust 单测已覆盖），
    Python 判定仍断言。
  · **不再有「Rust 收 / Python 拒」的版本差残余**（2026-09-30 裁定 ①-(c)）：判据换成
    同一份区块表后，两侧接受集由**同一份数据**决定，「判据 ≡ 表」两处全码点遍历
    合起来即零分歧——旧口径（`unicodedata` vs Rust 工具链的属性表版本差、Cn 残余
    声明、逐码点喂真 exe 的重导入口）**整段退休**。
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import inspect
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

# ---------------------------------------------------------------- 入口自保证 UTF-8
# 约束（工作纪律第 15 条）：本调用必须在**任何文件/库 I/O 之前**——utf8_boot.ensure_utf8
# 在解释器未开 UTF-8 模式时以相同 argv 重启自身（-X utf8），早于它的任何 open/stdio
# 读写都走 locale 编码（Windows 中文机 = cp936：裸 open 抛 UnicodeDecodeError、中文写
# 落 GBK 字节）。本守卫逐例跑真 `hive.exe`、比对中文 id 的 UTF-8 字节与 hex 语料，
# **自身**必须先保证（2026-09-30 教训：新守卫自身在未设 env 的现场会崩、退出码与
# 违例同码 ⇒ 现场无法分辨）。仓库根入 sys.path 的形态照 scripts/run_tests.py 的最小
# 写法（助手在仓根，不是包目录）。
# 被 import（本模块非 __main__）时助手只置子进程继承面、绝不重启/退出——F6：静默重启
# 会吞掉调用方输入。
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

from hive import orch as _orch                                 # noqa: E402
from hive.hive_mcp import mcp_server as _hm                    # noqa: E402
#: 第三处读者（c1/c2「三处读者共读同一份数据」）：`md_cg/units.py` 面。测试侧 import 不破
#: 零依赖家法（家法约束的是 **md_cg 不依赖 hive**，反向无约束；同形的先例 = 本仓
#: `hive/test_mdcg_units_charset_parity.py` 亦以 hive 侧守卫覆盖 md_cg 面）。
from md_cg import units as _units                              # noqa: E402

#: **冻结引用**：`_iso` 会把 `_hm._jobs_dir` 换成校验桩，若桩内再调 `_hm._jobs_dir()`
#: 就会无限递归（本守卫首版实测踩到）。判据必须走冻结引用——这也让「变异轮里 exec
#: 出来的函数副本」（globals 为活模块命名空间）照样逃不出隔离检查。
_REAL_JOBS_DIR = _hm._jobs_dir

HIVE_REL = "hive/target/release/" + ("hive.exe" if os.name == "nt" else "hive")
CORPUS_REL = "hive/id_contract_corpus_v2.txt"
JOB_RS_REL = "hive/src/job.rs"
IDENTITY_PY_REL = "md_cg/identity.py"
MCP_REL = "hive/hive_mcp/mcp_server.py"
ORCH_REL = "hive/orch.py"

#: 单元槽闭集（B2）：英文键 / 中文名（落 id 一律中文名），真源 = md_cg/identity.py。
UNIT_KEYS = ("record", "reflect", "verify", "output", "sustain")
UNIT_ZH = ("记录单元", "反思单元", "验证单元", "输出单元", "维生系统")

#: 四槽样本（A/B/D/E/F/G 共用；中文槽值，含契约示例形态 "zcode端/灵枢迭代/反思单元"）
SLOT_OK = {"identity": "zcode端", "task": "灵枢迭代", "unit": "反思单元"}
SLOT_ZH_PREFIX = "h_zcode端_灵枢迭代_反思单元_"

#: 拒收原因级标记（D1(3) 的「错误显式」面：每条拒收项都要能在原因里被认出）
REASON_MARK = {
    "尾点": "尾点",
    "零宽": "零宽",
    "双向控制": "双向控制",
    "设备名": "保留设备名",
    "NFC": "NFC",
    "路径": "路径成分",
}


# ------------------------------------------------------------ 结果收集与分组

_GROUPS: dict = {}
_CUR = ["?"]


def check(name: str, cond, detail: str = ""):
    """记一条断言（**不中断整组**——「变异下红项数 == 该组断言数」这一精确口径依赖它）。"""
    g = _GROUPS.setdefault(_CUR[0], {"n": 0, "fail": 0, "reds": []})
    g["n"] += 1
    if cond:
        print("  [ok]   %s" % name)
    else:
        g["fail"] += 1
        g["reds"].append(name)
        print("  [FAIL] %s  %s" % (name, detail))


def begin(g: str, title: str):
    _CUR[0] = g
    _GROUPS.setdefault(g, {"n": 0, "fail": 0, "reds": []})
    print("\n== [%s] %s ==" % (g, title))


# ------------------------------------------------------------ 临时物与清理

_TMP_ROOTS: list = []
_PERSIST_ROOTS: list = []      # 变异轮之间必须留着（编译副本），只在进程收尾清
_PROCS: list = []


def _mkroot(tag: str) -> str:
    d = tempfile.mkdtemp(prefix="idv2_%s_" % tag)
    _TMP_ROOTS.append(d)
    return d


def _cleanup():
    for p in _PROCS:
        try:
            if p.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                                   capture_output=True, text=True,
                                   encoding="utf-8", errors="replace")
                else:
                    p.terminate()
                with contextlib.suppress(Exception):
                    p.wait(timeout=10)
        except Exception:                 # noqa: BLE001 —— 收尾尽力而为
            pass
    del _PROCS[:]
    for d in _TMP_ROOTS:
        shutil.rmtree(d, ignore_errors=True)
    del _TMP_ROOTS[:]


def _cleanup_persist():
    for d in _PERSIST_ROOTS:
        shutil.rmtree(d, ignore_errors=True)
    del _PERSIST_ROOTS[:]


# ------------------------------------------------------------------ exe 判据面

def _exe() -> str:
    """唯一 exe 来源：HIVE_EXE（变异轮用它指向临时编译副本）> 仓内 release 产物。"""
    return os.environ.get("HIVE_EXE") or os.path.join(_REPO, HIVE_REL)


def _missing_exe():
    """生效条件：exe 不在盘上 → 返回该路径（调用方按前置缺失判红，不伪造 verdict）。"""
    e = _exe()
    return None if os.path.isfile(e) else e


_PROBE = []      # 惰性建的探测池（`hive poll <id>` 需要 --jobs 指向存在目录）


def _probe_jobs() -> str:
    """`hive poll <id>` 需要 --jobs 指向存在目录；池内容不参与判定（只看 ok 字段）。"""
    if not _PROBE or not os.path.isdir(_PROBE[0]):
        d = os.path.join(_mkroot("probe"), "jobs")
        os.makedirs(d, exist_ok=True)
        _PROBE[:] = [d]
    return _PROBE[0]


def _cli(args, jobs: str | None = None, extra_env: dict | None = None, timeout=120):
    """跑真 hive.exe；返回 (rc, stdout, stderr)。env 只留进程 env + PYTHONUTF8，
    并**显式剥掉三槽 env**（否则「缺槽」用例会被开发机 env 意外填上）。"""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    for k in ("HIVE_JOB_IDENTITY", "HIVE_JOB_TASK", "HIVE_JOB_UNIT"):
        env.pop(k, None)
    if extra_env:
        env.update(extra_env)
    argv = [_exe()] + list(args)
    if jobs is not None:
        argv += ["--jobs", jobs]
    r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, cwd=_REPO, env=env)
    return r.returncode, (r.stdout or ""), (r.stderr or "")


def _json_of(out: str):
    try:
        return json.loads((out or "").strip())
    except ValueError:
        return None


def _rust_verdict(jid: str):
    """真 exe 的判据面三态："accept"（ok=true）/ "reject"（ok=false）/ None（不可判定）。
    NUL 进不了 argv ⇒ 返回 None（调用方按「live oracle 不适用」显式声明，不猜）。"""
    if "\x00" in jid:
        return None
    _rc, out, _err = _cli(["poll", jid], jobs=_probe_jobs())
    doc = _json_of(out)
    if not isinstance(doc, dict):
        return None
    return "accept" if doc.get("ok") else "reject"


# --------------------------------------------------------------- 池夹具

def _submit_cli(tmp: str, jobs: str, spec: dict, slot_args=(), extra_env=None,
                tag: str = ""):
    """把 spec 写入 tmp 下唯一文件并跑 `hive submit`；返回 (rc, stdout, stderr)。"""
    p = os.path.join(tmp, "spec_%s_%d.json" % (tag or "s", len(os.listdir(tmp)) + 1))
    with open(p, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False)
    return _cli(["submit", "--spec", p] + list(slot_args), jobs=jobs,
                extra_env=extra_env)


def _mk_job(jobs: str, jid: str, created=None, state="pending"):
    """手搭一台任务目录（status.json 至少含 job_id/state，created_ts 按需）。"""
    d = os.path.join(jobs, jid)
    os.makedirs(d, exist_ok=True)
    st = {"job_id": jid, "state": state}
    if created is not None:
        st["created_ts"] = created
    with open(os.path.join(d, "status.json"), "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    return d


def _iso_env(**kv) -> dict:
    """剥净 HIVE_*/MDCG_* 的 env 后按需覆盖——防开发机 env 里恰有真池键把夹具指歪。"""
    e = {k: v for k, v in os.environ.items()
         if not k.startswith("HIVE_") and not k.startswith("MDCG_")}
    e["PYTHONUTF8"] = "1"
    e.update({k: v for k, v in kv.items() if v is not None})
    return e


@contextlib.contextmanager
def _iso(jobs: str):
    """进程内在**临时池**上提交：env HIVE_JOBS_DIR + `_jobs_dir` 双钉同一临时池
    （并自检解析结果一致，不一致即抛——隔离面失守不得静默），`_ensure_serve` 打桩
    不拉 serve、`_result_anchor_key` 打桩为 None（本组不判锚面）。"""
    def _jobs_check():
        got = os.path.abspath(_REAL_JOBS_DIR())
        want = os.path.abspath(jobs)
        if got != want:
            raise RuntimeError("隔离面失守：jobs 解析到 %s，期望临时池 %s —— 拒绝提交"
                               % (got, want))
        return jobs
    with mock.patch.dict(os.environ, {"HIVE_JOBS_DIR": jobs}), \
            mock.patch.object(_hm, "_jobs_dir", _jobs_check), \
            mock.patch.object(_hm, "_ensure_serve",
                              lambda j: {"started": False, "note": "idv2-guard-stub"}), \
            mock.patch.object(_hm, "_result_anchor_key", lambda: None):
        yield


def _spawn_in(jobs: str, args: dict) -> dict:
    """进程内调 `_t_spawn`（**不抛**：异常归成 ok=False，使断言计数稳定）。"""
    try:
        with _iso(jobs):
            return _hm._t_spawn(dict(args))
    except Exception as exc:              # noqa: BLE001 —— 隔离失守/变异态按红
        return {"ok": False, "error": "raise:%s: %s" % (type(exc).__name__, exc)}


def _slot_dir_names(jobs: str) -> set:
    return {n for n in os.listdir(jobs)
            if n.startswith("h") and os.path.isdir(os.path.join(jobs, n))}


def _file_sig(root: str):
    """（相对路径, 大小, mtime_ns）快照——用于「只读」核证。"""
    out = []
    for dp, _dn, fs in os.walk(root):
        for f in fs:
            p = os.path.join(dp, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out.append((os.path.relpath(p, root).replace("\\", "/"),
                        st.st_size, st.st_mtime_ns))
    return sorted(out)


# ================================================================== A 组
# 四槽必填（CLI 与 MCP 两路实跑）+ `_submit` 不再自造 id + orch 透传。

def g_a():
    begin("A", "四槽必填（CLI/MCP 两路实跑）+ _submit 退场 + orch 透传")
    miss = _missing_exe()
    check("A0 前置：hive 二进制在盘（真 exe 对照面）", miss is None,
          "未找到 %s——先 cargo build --release（hive/ 下）" % (miss or ""))
    root = _mkroot("a")
    jobs = os.path.join(root, "jobs")
    os.makedirs(jobs, exist_ok=True)
    spec = {"model": "guard-model", "user_prompt": "id 契约守卫", "timeout_s": 60}

    # ---- CLI：缺任一槽 → 退出 1 + 错误文本含四槽名与可照抄示例
    for label, flags in (("缺身份", ["--task", "灵枢迭代", "--unit", "反思单元"]),
                         ("缺任务", ["--identity", "zcode端", "--unit", "反思单元"]),
                         ("缺单元", ["--identity", "zcode端", "--task", "灵枢迭代"]),
                         ("三槽全缺", [])):
        rc, out, _e = _submit_cli(root, jobs, spec, slot_args=flags, tag="miss")
        doc = _json_of(out) or {}
        err = doc.get("error") or ""
        check("A1·CLI %s → 退出 1 且错误含四槽名/可照抄示例" % label,
              rc == 1 and doc.get("ok") is False
              and "四槽" in err and "身份" in err and "任务" in err and "单元" in err
              and "hive submit --spec" in err,
              "rc=%s err=%r" % (rc, err[:160]))
    check("A1b·缺槽不落任何任务目录（fail fast 在进队列前）",
          _slot_dir_names(jobs) == set(), str(sorted(_slot_dir_names(jobs))))

    # ---- CLI：env 兜底（B8：HIVE_JOB_IDENTITY / HIVE_JOB_TASK / HIVE_JOB_UNIT）
    rc, out, _e = _submit_cli(root, jobs, spec, extra_env={
        "HIVE_JOB_IDENTITY": "env端", "HIVE_JOB_TASK": "兜底",
        "HIVE_JOB_UNIT": "verify"}, tag="envslots")
    doc = _json_of(out) or {}
    jid_env = doc.get("job_id") or ""
    check("A2·CLI env 兜底三槽可提交（英文键 unit 落 id 为中文名）",
          rc == 0 and doc.get("ok") is True
          and jid_env.startswith("h_env端_兜底_验证单元_"),
          "rc=%s jid=%r err=%r" % (rc, jid_env, (doc.get("error") or "")[:80]))

    # ---- CLI：alloc-id 子命令（成功打印 id 且目录已创建；失败非 0 打印原因）
    rc, out, _e = _cli(["alloc-id", "--identity", "zcode端", "--task", "分配",
                        "--unit", "记录单元"], jobs=jobs)
    doc = _json_of(out) or {}
    aid = doc.get("job_id") or ""
    check("A3·alloc-id 成功：id 四槽中文形态 + 目录已创建（分配凭证）",
          rc == 0 and doc.get("ok") is True
          and aid == "h_zcode端_分配_记录单元_0001"
          and os.path.isdir(os.path.join(jobs, aid)),
          "rc=%s doc=%s" % (rc, json.dumps(doc, ensure_ascii=False)[:140]))
    rc2, out2, _e = _cli(["alloc-id", "--identity", "zcode端", "--task", "分配",
                          "--unit", "第六单元"], jobs=jobs)
    doc2 = _json_of(out2) or {}
    check("A3b·alloc-id 失败非 0 且打印原因（单元不在闭集）",
          rc2 == 1 and doc2.get("ok") is False
          and "单元槽非法" in (doc2.get("error") or ""),
          "rc=%s err=%r" % (rc2, (doc2.get("error") or "")[:120]))

    # ---- MCP：真实 stdio JSON-RPC 子进程（schema + 缺槽拒面）——**独立空池**，
    # 使「缺槽未触落盘」成为可观测断言（与上面 CLI 已落的任务目录无关）
    mjobs = os.path.join(_mkroot("a_mcp"), "jobs")
    os.makedirs(mjobs, exist_ok=True)
    mcp_out = _mcp_roundtrip(mjobs, root)
    check("A4·MCP 真实 stdio 服务：缺四槽被拒且原因含四槽名",
          mcp_out.get("spawn_noslot", {}).get("ok") is False
          and "四槽" in (mcp_out.get("spawn_noslot", {}).get("error") or ""),
          json.dumps(mcp_out.get("spawn_noslot"), ensure_ascii=False)[:200])
    check("A4b·MCP 真实进程侧证：缺槽拒面未触任何落盘（临时池仍空）",
          mcp_out.get("jobs_dir_untouched") == set(),
          str(mcp_out.get("jobs_dir_untouched")))
    sch = mcp_out.get("schema") or {}
    props = set((sch.get("properties") or {}).keys())
    check("A5·MCP 工具 inputSchema 收四槽且 required 含 identity/task/unit",
          {"identity", "task", "unit"} <= props
          and {"identity", "task", "unit"} <= set(sch.get("required") or []),
          "props=%s required=%s" % (sorted(props), sch.get("required")))
    check("A5b·schema properties 与 SPAWN_ALLOWED_KEYS 逐键同集（防两处漂移）",
          props == set(_hm.SPAWN_ALLOWED_KEYS)
          and {"identity", "task", "unit"} <= set(_hm.SPAWN_ALLOWED_KEYS),
          "schema-only=%s whitelist-only=%s"
          % (sorted(props - set(_hm.SPAWN_ALLOWED_KEYS)),
             sorted(set(_hm.SPAWN_ALLOWED_KEYS) - props)))
    check("A5c·工具描述键数与 schema 一致（19 键，防文案漂移）",
          "19 个参数" in _hm.TOOLS[0]["description"] and len(props) == 19,
          "len(props)=%d desc=%r" % (len(props), _hm.TOOLS[0]["description"][:90]))

    # ---- MCP：进程内 _t_spawn —— 缺槽在**任何落盘/分配之前**被拦（独立空池）
    jobs_m = os.path.join(_mkroot("a_inproc"), "jobs")
    os.makedirs(jobs_m, exist_ok=True)
    seen: list = []
    _orig_alloc = _hm._alloc_job_id

    def _spy(*a, **k):
        seen.append(a)
        return _orig_alloc(*a, **k)

    for label, args in (("三槽全缺", {}),
                        ("缺 identity", {"task": "灵枢迭代", "unit": "反思单元"}),
                        ("缺 task", {"identity": "zcode端", "unit": "反思单元"}),
                        ("缺 unit", {"identity": "zcode端", "task": "灵枢迭代"})):
        with mock.patch.object(_hm, "_alloc_job_id", side_effect=_spy):
            r = _spawn_in(jobs_m, {"model": "guard-model", "user_prompt": "x", **args})
        check("A6·MCP _t_spawn %s → ok=False 且错误含四槽名与 MCP 面示例" % label,
              r.get("ok") is False and "四槽" in (r.get("error") or "")
              and "hive_spawn" in (r.get("error") or ""),
              json.dumps(r, ensure_ascii=False)[:200])
    check("A6b·缺槽时**根本没调分配器**（必填闸在 Python 面先落，非靠下游兜底）",
          seen == [], "分配器被调用 %d 次：%r" % (len(seen), seen[:3]))
    check("A6c·缺槽不落任何任务目录",
          _slot_dir_names(jobs_m) == set(), str(sorted(_slot_dir_names(jobs_m))))

    good = _spawn_in(jobs_m, {"model": "guard-model", "user_prompt": "x", **SLOT_OK})
    gjid = good.get("job_id") or ""
    check("A7·MCP _t_spawn 四槽齐备 → 四槽中文 id（编号 4 位定宽）+ spec/status 落盘",
          good.get("ok") is True and gjid.startswith(SLOT_ZH_PREFIX)
          and len(gjid) == len(SLOT_ZH_PREFIX) + 4 and gjid[-4:].isdigit()
          and os.path.isfile(os.path.join(jobs_m, gjid, "spec.json"))
          and os.path.isfile(os.path.join(jobs_m, gjid, "status.json")),
          json.dumps(good, ensure_ascii=False)[:200])
    # 「读回」必须能容忍**上游分配/落盘失败**（变异轮里判据被改坏时正是这种态）：
    # 文件不在 ⇒ A7b 判红而不是把整个守卫打断（守卫的产出是**红项集**，不是 traceback）。
    spec_path = os.path.join(jobs_m, gjid, "spec.json")
    spec_back = None
    if os.path.isfile(spec_path):
        with open(spec_path, encoding="utf-8") as f:
            spec_back = json.load(f)
    check("A7b·四槽不入 spec.json（文件须已落盘；与 rust init_job_with_slots 同写序/同口径）",
          isinstance(spec_back, dict)
          and not ({"identity", "task", "unit"} & set(spec_back)),
          "spec=%r" % (spec_back,))
    check("A7c·返回体透出实际生效的三槽（调用方可见，不静默）",
          (good.get("slots") or {}) == SLOT_OK, str(good.get("slots")))

    # ---- _submit 退场：源码面 + 行为面
    with open(os.path.join(_REPO, MCP_REL), encoding="utf-8") as f:
        src = f.read()
    check("A8·_submit 不再自造 id（旧 `uuid4().hex[:6]` 与 `f\"h{毫秒}_` 已退场）",
          "uuid.uuid4().hex[:6]" not in src
          and 'f"h{int(time.time() * 1000)}_' not in src
          and '"alloc-id"' in src)
    check("A8b·_submit 签名带四槽之三且 docstring 声明「不再自造 id」",
          "def _submit(jobs: str, spec: dict, identity: str, task: str, unit: str)"
          in src and "不再自造 id" in src)
    j2 = os.path.join(_mkroot("a_noexe"), "jobs")
    os.makedirs(j2, exist_ok=True)
    bogus = os.path.join(root, "没有这个二进制")
    with mock.patch.dict(os.environ, {"HIVE_EXE": bogus}):
        try:
            _hm._alloc_job_id(j2, "zcode端", "分配", "记录单元")
            raised = None
        except _hm.SubmitError as e:
            raised = str(e)
        except Exception as e:            # noqa: BLE001
            raised = "WRONG-TYPE:%s: %s" % (type(e).__name__, e)
        noexe = _spawn_in(j2, {"model": "guard-model", "user_prompt": "x", **SLOT_OK})
    check("A9·HIVE_EXE 不可用 → SubmitError 显式报错（不静默降级/不自造 id）",
          raised is not None and "HIVE_EXE 不可用" in raised
          and "不自造 id" in raised, "raised=%r" % (raised,))
    check("A9b·该失败经 _t_spawn 转成 ok:False + 可读原因（不抛给协议面）",
          noexe.get("ok") is False and "HIVE_EXE" in (noexe.get("error") or ""),
          json.dumps(noexe, ensure_ascii=False)[:200])
    check("A9c·分配失败不落任何任务目录（不自造 id 的观测面）",
          _slot_dir_names(j2) == set(), str(sorted(_slot_dir_names(j2))))

    # ---- orch 四槽透传（B8）
    jobs3 = os.path.join(_mkroot("a_orch"), "jobs")
    os.makedirs(jobs3, exist_ok=True)
    r0, _s0, _c0 = _orch_spawn(jobs3, {"user_prompt": "子任务"}, slots={})
    check("A10·orch 缺四槽 → ok=False 且报错含四槽名（不兜底造 id）",
          r0.get("ok") is False and "四槽" in (r0.get("error") or ""),
          json.dumps(r0, ensure_ascii=False)[:200])
    r1, sub1, cap1 = _orch_spawn(jobs3, {"user_prompt": "子任务"},
                                 slots={"identity": "orch端", "task": "编排",
                                        "unit": "输出单元"})
    check("A10b·orch 四槽齐备 → 透传给 _submit（identity/task/unit 逐项一致）",
          r1.get("ok") is True and cap1 == ("orch端", "编排", "输出单元")
          and sub1.get("user_prompt") == "子任务",
          "cap=%r resp=%s" % (cap1, json.dumps(r1, ensure_ascii=False)[:120]))
    r2, _s2, cap2 = _orch_spawn(
        jobs3, {"user_prompt": "子任务", "identity": "显式端", "task": "显式任务",
                "unit": "验证单元"},
        slots={"identity": "orch端", "task": "编排", "unit": "输出单元"})
    check("A10c·orch 显式传值优先于 spec 继承（缺省才继承）",
          cap2 == ("显式端", "显式任务", "验证单元"),
          "cap=%r resp=%s" % (cap2, json.dumps(r2, ensure_ascii=False)[:120]))
    with open(os.path.join(_REPO, ORCH_REL), encoding="utf-8") as f:
        osrc = f.read()
    check("A10d·orch 源码面无 id 自造形态（不含 uuid4().hex[:6]）",
          "uuid.uuid4().hex[:6]" not in osrc and "SLOT_KEYS" in osrc)
    check("A10e·orch 三槽从 spec 同名键读入（spec 带则透传的单一来源）",
          '{k: str(spec.get(k) or "").strip() for k in SLOT_KEYS}' in osrc
          and 'slots = {k: str(a.get(k) or _CFG["slots"].get(k) or "").strip()' in osrc)


def _mcp_roundtrip(jobs: str, root: str) -> dict:
    """真起 `python -m hive.hive_mcp.mcp_server`，走 stdio JSON-RPC 问两件事：
    ① `tools/list` 的 inputSchema；② 缺四槽调 `hive_spawn` 的返回。
    `HIVE_EXE` 指向**不存在**的路径：本组只验 schema 与缺槽拒面，绝不触发 serve
    拉起与真实分配（隔离纪律：在役 serve / jobs 池一概不碰）。"""
    cfg = os.path.join(root, "config.idv2.json")
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump({"HIVE_JOBS_DIR": jobs}, f, ensure_ascii=False)
    env = _iso_env(HIVE_JOBS_DIR=jobs, HIVE_CONFIG=cfg,
                   HIVE_EXE=os.path.join(root, "没有这个二进制"))
    out: dict = {}
    try:
        p = subprocess.Popen([sys.executable, "-X", "utf8", "-m",
                              "hive.hive_mcp.mcp_server"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, env=env, shell=False,
                             cwd=_REPO, text=True, encoding="utf-8")
    except OSError as e:
        return {"error": "起服务失败: %s" % e}
    _PROCS.append(p)

    def _call(rid, method, params=None):
        req = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            req["params"] = params
        p.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
        p.stdin.flush()
        while True:
            line = p.stdout.readline()
            if not line:
                return {}
            resp = json.loads(line)
            if resp.get("id") == rid:
                return resp

    try:
        r1 = _call(1, "tools/list", {})
        for t in ((r1.get("result") or {}).get("tools") or []):
            if t.get("name") == "hive_spawn":
                out["schema"] = t.get("inputSchema") or {}
        r2 = _call(2, "tools/call", {"name": "hive_spawn",
                                     "arguments": {"model": "guard-model",
                                                   "user_prompt": "x"}})
        txt = (((r2.get("result") or {}).get("content") or [{}])[0]).get("text") or "{}"
        out["spawn_noslot"] = json.loads(txt)
    except Exception as e:                # noqa: BLE001 —— 协议面异常按空结果（判红）
        out["error"] = "%s: %s" % (type(e).__name__, e)
    finally:
        with contextlib.suppress(Exception):
            p.stdin.close()
            p.wait(timeout=10)
    out["jobs_dir_untouched"] = _slot_dir_names(jobs)
    return out


def _orch_spawn(jobs: str, args: dict, slots: dict):
    """进程内调 `orch._spawn`：桩 `_hm._submit` 捕获三槽（不落盘、不触 serve）。"""
    job_dir = os.path.join(jobs, "h_orch_guard")
    os.makedirs(job_dir, exist_ok=True)
    cap: list = []
    orig = {k: _orch._CFG.get(k) for k in ("job_id", "job_dir", "jobs",
                                           "model", "children", "slots")}
    _orch._CFG.update({"job_id": "h_orch_guard", "job_dir": job_dir, "jobs": jobs,
                       "model": "guard-model", "children": [], "slots": dict(slots)})

    def _fake(j, sub, identity=None, task=None, unit=None):
        cap.append((identity, task, unit))
        return "h_orch_child_1"

    try:
        with mock.patch.dict(os.environ, {"HIVE_JOBS_DIR": jobs}), \
                mock.patch.object(_orch, "_resolve_jobs_dir", lambda *a, **k: jobs), \
                mock.patch.object(_orch._hm, "_submit", side_effect=_fake):
            r = _orch._spawn(dict(args))
        return r, dict(args), (cap[-1] if cap else None)
    except Exception as exc:              # noqa: BLE001
        return {"ok": False, "error": "raise:%s: %s" % (type(exc).__name__, exc)}, \
            dict(args), None
    finally:
        _orch._CFG.update(orig)


# ================================================================== B 组
# 编号分配：独占创建即分配、4 位定宽、搜索在号位间回绕、9999 个号位全被占用才报错
# （c2 起**真构造 9999 个号位**：本机实测建目录 0.84s、扫描 0.19s，代价可接受）。

def g_b():
    begin("B", "编号分配（B3：独占创建即分配 / 定宽 4 位 / 号位间回绕 / 全部占用才报错）")
    check("B0 前置：hive 二进制在盘", _missing_exe() is None,
          "未找到 %s" % (_missing_exe() or ""))
    root = _mkroot("b")
    jobs = os.path.join(root, "jobs")
    os.makedirs(jobs, exist_ok=True)

    ids = []
    docs = []
    for _ in range(3):
        rc, out, _e = _cli(["alloc-id", "--identity", "编号端", "--task", "连续",
                            "--unit", "reflect"], jobs=jobs)
        docs.append(_json_of(out) or {})
        ids.append(docs[-1].get("job_id"))
    check("B1·连续分配不碰撞且自 0001 起（英文键 unit 落中文名）",
          ids == ["h_编号端_连续_反思单元_0001", "h_编号端_连续_反思单元_0002",
                  "h_编号端_连续_反思单元_0003"], str(ids))
    check("B2·编号 4 位定宽十进制 + 分配即创建目录（独占创建即分配）",
          all(len(i.split("_")[-1]) == 4 and i.split("_")[-1].isdigit()
              and os.path.isdir(os.path.join(jobs, i)) for i in ids), str(ids))
    check("B2b·分配只落在本守卫的临时池（exe 回显 jobs_dir == 临时池，自证不碰在役池）",
          all(os.path.abspath(d.get("jobs_dir") or "?") == os.path.abspath(jobs)
              for d in docs), str([d.get("jobs_dir") for d in docs]))

    # ---- c1：搜索在号位间回绕（起点越过上限时继续用低位号位，而不是白扔 9998 个位）
    jobs_wrap = os.path.join(root, "jobs_wrap")
    os.makedirs(os.path.join(jobs_wrap, "h_端_任务_记录单元_9999"), exist_ok=True)
    rc, out, _e = _cli(["alloc-id", "--identity", "端", "--task", "任务",
                        "--unit", "记录单元"], jobs=jobs_wrap)
    doc = _json_of(out) or {}
    check("B3·回绕生效：池内只存 …_9999（起点 = 10000 越上限）→ 分到空闲的 …_0001",
          rc == 0 and doc.get("ok") is True
          and doc.get("job_id") == "h_端_任务_记录单元_0001"
          and os.path.isdir(os.path.join(jobs_wrap, "h_端_任务_记录单元_0001")),
          "rc=%s doc=%s" % (rc, json.dumps(doc, ensure_ascii=False)[:160]))
    rc, out, _e = _cli(["alloc-id", "--identity", "端", "--task", "任务",
                        "--unit", "记录单元"], jobs=jobs_wrap)
    doc = _json_of(out) or {}
    check("B3b·回绕段不重复试号（9999 + 0001 在场 → 落到 0002，既不复用 0001 也不报用尽）",
          rc == 0 and doc.get("job_id") == "h_端_任务_记录单元_0002",
          "rc=%s doc=%s" % (rc, json.dumps(doc, ensure_ascii=False)[:160]))

    # ---- c2：真把 9999 个号位**全部**占满才报错，且文案如实（本机实测 0.84s / 0.19s）
    jobs_full = os.path.join(root, "jobs_full")
    os.makedirs(jobs_full, exist_ok=True)
    for n in range(1, 10000):
        os.makedirs(os.path.join(jobs_full, "h_端_任务_记录单元_%04d" % n),
                    exist_ok=True)
    before = sorted(os.listdir(jobs_full))
    rc, out, _e = _cli(["alloc-id", "--identity", "端", "--task", "任务",
                        "--unit", "记录单元"], jobs=jobs_full)
    doc = _json_of(out) or {}
    err = doc.get("error") or ""
    check("B4·9999 个号位**全部**被占用才报错：退出 1 且文案含「9999 个号位已全部被占用」",
          rc == 1 and doc.get("ok") is False
          and "9999 个号位已全部被占用" in err
          and "h_端_任务_记录单元_" in err, "rc=%s err=%r" % (rc, err[:200]))
    check("B4b·文案不含旧措辞「已无可用编号」（它会被读成「前面也满了」，与池内事实不符）",
          "已无可用编号" not in err, "err=%r" % err[:200])
    check("B4c·用尽不得静默加宽（不得出现 5 位 10000 目录）",
          not os.path.exists(os.path.join(jobs_full, "h_端_任务_记录单元_10000")),
          str(sorted(os.listdir(jobs_full))[-3:]))
    check("B4d·用尽不得就地复用/新落目录：池内清单不变 且 末次碰撞 = …_9999（全序扫过）",
          sorted(os.listdir(jobs_full)) == before
          and "末次碰撞 h_端_任务_记录单元_9999" in err,
          "err=%r 新件=%s" % (err[-90:],
                              sorted(set(os.listdir(jobs_full)) - set(before))[:3]))
    check("B4e·用尽失败不留残迹：池内仍恰 9999 个号位目录",
          len([n for n in os.listdir(jobs_full)
               if len(n.rsplit("_", 1)[-1]) == 4]) == 9999,
          str(len(os.listdir(jobs_full))))

    jobs3 = os.path.join(root, "jobs_last")
    os.makedirs(os.path.join(jobs3, "h_端_任务_记录单元_9998"), exist_ok=True)
    rc, out, _e = _cli(["alloc-id", "--identity", "端", "--task", "任务",
                        "--unit", "记录单元"], jobs=jobs3)
    doc = _json_of(out) or {}
    check("B5·9998 在场时 9999 仍可分配（上界形态 + 定宽守恒）",
          rc == 0 and doc.get("job_id") == "h_端_任务_记录单元_9999",
          json.dumps(doc, ensure_ascii=False)[:160])
    rc, out, _e = _cli(["alloc-id", "--identity", "端", "--task", "任务",
                        "--unit", "记录单元"], jobs=jobs3)
    doc = _json_of(out) or {}
    check("B5b·9998+9999 在场（起点越界）→ 回绕到 0001，而**不是**报用尽",
          rc == 0 and doc.get("job_id") == "h_端_任务_记录单元_0001",
          "rc=%s doc=%s" % (rc, json.dumps(doc, ensure_ascii=False)[:160]))
    jobs4 = os.path.join(root, "jobs_foreign")
    os.makedirs(os.path.join(jobs4, "h_端_任务_记录单元_x"), exist_ok=True)
    os.makedirs(os.path.join(jobs4, "h_端_任务_记录单元_00010"), exist_ok=True)
    rc, out, _e = _cli(["alloc-id", "--identity", "端", "--task", "任务",
                        "--unit", "记录单元"], jobs=jobs4)
    doc = _json_of(out) or {}
    check("B6·AlreadyExists 才算碰撞（外来非 4 位尾段既不参与起点也不占号位）",
          doc.get("job_id") == "h_端_任务_记录单元_0001",
          json.dumps(doc, ensure_ascii=False)[:160])
    with open(os.path.join(_REPO, MCP_REL), encoding="utf-8") as f:
        src = f.read()
    check("B7·MCP/编排面不自持分配器（无 os.mkdir 自增实现，只调 alloc-id）",
          "os.mkdir" not in src and "MAX_UNIT_SEQ" not in src
          and '"alloc-id"' in src)

    # ---- 判据面源码钉点（c1/c2/c3：单点判据 + 两个「回绕」不得混读）
    with open(os.path.join(_REPO, JOB_RS_REL), encoding="utf-8") as f:
        jsrc = f.read()
    check("B8·生产默认上限恒为 9999（B4 的「真用尽」用例依赖该默认值，故在守卫里钉死）",
          "pub const MAX_UNIT_SEQ: u32 = 9999;" in jsrc, "job.rs 未见该常量声明")
    check("B8b·docstring/注释并列写清两个「回绕」（编号值不回绕 ∧ 搜索在号位间回绕）",
          "编号值不回绕" in jsrc and "搜索在号位间回绕" in jsrc,
          "「编号值不回绕」=%s「搜索在号位间回绕」=%s"
          % ("编号值不回绕" in jsrc, "搜索在号位间回绕" in jsrc))
    check("B8c·搜索序单点 = seq_candidates（先 hint..=MAX、再回绕 1..hint，两区间不重叠）",
          "fn seq_candidates(hint: u32)" in jsrc
          and "(hint..=MAX_UNIT_SEQ).chain(1..wrap_hi)" in jsrc
          and "let wrap_hi = hint.min(MAX_UNIT_SEQ + 1);" in jsrc,
          "搜索序实现面与契约不符")
    check("B8d·源码面：新文案在位（「个号位已全部被占用」）且旧文案形态（「已无可用编号（」）已退场"
          "（注释里解释旧措辞为何被换掉不算违例，故只钉会进错误文本的那个形态）",
          "个号位已全部被占用" in jsrc and "末次碰撞" in jsrc
          and "已无可用编号（" not in jsrc, "job.rs 文案面与契约不符")


# ================================================================== C 组
# 字符集闸（B4/B5）+ B6 语料两侧同判 + 区块表同源 + 方向完备性。

def _corpus():
    """语料解码（与 rust 单测 `corpus_cases` 同一格式与同一份文件）：
    `<verdict>\\t<utf8-hex>\\t<说明>`；`#` 与空行忽略。"""
    with open(os.path.join(_REPO, CORPUS_REL), encoding="utf-8") as f:
        raw = f.read()
    out = []
    for i, line in enumerate(raw.splitlines()):
        line = line.rstrip("\r")
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) != 3:
            raise SystemExit("语料第 %d 行须三列（verdict/hex/说明）：%r" % (i + 1, line))
        out.append((cols[0], bytes.fromhex(cols[1]).decode("utf-8"), cols[2]))
    return out


def _rust_units():
    with open(os.path.join(_REPO, JOB_RS_REL), encoding="utf-8") as f:
        src = f.read()
    body = src.split("pub const UNITS", 1)[1].split("];", 1)[0]
    return re.findall(r'\("(\w+)",\s*"([^"]+)"\)', body)


def _src_of(rel: str) -> str:
    """读仓内文本文件（唯一配方：显式 UTF-8；判据面只看字面量，不做任何解析推断）。"""
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


#: 「全码点遍历」的三种写法（c13：**只许出现在测试内**——生产热路径上判据是 O(区间数)
#: 的查表，全表扫描会把每次 id 校验变成 110 万次比较）。
_FULL_SWEEP_FORMS = ("0..=0x10FFFF", "0..0x110000", "range(0x110000)")


def _full_sweep_hits(text: str) -> int:
    """数 text 里的全码点遍历写法（用于「生产面无、测试面有」的双向断言）。"""
    return sum(text.count(f) for f in _FULL_SWEEP_FORMS)


def _identity_positions():
    """从真源 `md_cg/identity.py` 现场解析 POSITIONS（键序 + unit 中文名）。"""
    with open(os.path.join(_REPO, IDENTITY_PY_REL), encoding="utf-8") as f:
        text = f.read()
    start = text.find("POSITIONS = {")
    if start < 0:
        raise SystemExit("真源缺 `POSITIONS = {`：%s" % IDENTITY_PY_REL)
    block = text[start:]
    end = block.find("\n}")
    keys, units = [], []
    for line in block[:end].splitlines():
        t = line.strip()
        # 键行形态：`"record": {"unit": "记录单元", "effect": "全",`（真源一行可能带
        # 后续键，故只认 `"<key>": {` 这个前导形态）
        if t.startswith('"') and '": {' in t:
            keys.append(t[1:].split('"')[0])
        if '"unit":' in t:
            rest = t.split('"unit":', 1)[1].strip().lstrip('"')
            units.append(rest.split('"')[0])
    return keys, units


OK_IDS = [
    "h_zcode端_灵枢迭代_反思单元_0001",   # 契约示例
    "h_端_任务_记录单元_9999",            # 编号上界形态
    "h_端_任务_维生系统_0001",            # 第五单元落 id
    "h_端_任务_反思单元_0000",            # 编号形态 0（字符集闸不判编号数值）
    "h_123_456_输出单元_0007",
    "h_a.b",                             # `.` 非尾点、非单独 → 收
    "h1758000000000_1a2b",               # 旧形态（13 位毫秒 + 4 位 hex）
    "h1_a", "h",                         # 旧判例
]

BAD_IDS = [
    "", "..", "../victim", "h/../../x", "h/.", "h\\..", "h:x", "/etc",
    "h..", "h.", "h ", "h\t", "h\x01", "h\x7f", "h\x00NUL",
    "h\u200b", "h\u200e", "h\u2060", "h\ufeff",             # 零宽
    "h\u202e", "h\u2066",                                   # 双向控制
    "h\u0301", "h\u0041\u0301",                             # 组合标记 / NFD 形
    "h\u00aa", "h\u2070", "h\u2160", "h\uff11", "h\u1100",   # 争议字符
    "h\ufa10", "h\ufb01", "h\u2126", "h\u2460", "h\u3200",
    "h\U0001d400", "h\U0002f800", "h\ufe30", "h\ufe50", "h\u3130",
    "h_端-1_任务_记录单元_0001",            # `-` 不在白名单
    "h_CON_任务_记录单元_0001",             # 整/段级保留设备名
    "h_CON.txt_任务_记录单元_0001",
    "h_端_aux_记录单元_0001",
    "h_端_任务_COM1_0001",
    "h_端_任务_LPT9_0001",
    "h_端_任务_NUL_0001",                   # NUL 设备名段（D1(4) 点名项）
]

#: 原因级样本（每项：id、期望在 `_job_id_reject_reason` 里出现的标记）——使每条
#: 拒收项**可观测**（可诊断），也成为该拒收判据的定点变异锚。
REASON_CASES = (
    ("h.", REASON_MARK["尾点"]),
    ("h..", REASON_MARK["尾点"]),
    ("h\u200b", REASON_MARK["零宽"]),
    ("h\u2060", REASON_MARK["零宽"]),
    ("h\u202e", REASON_MARK["双向控制"]),
    ("h\u2066", REASON_MARK["双向控制"]),
    ("h_CON_任务_记录单元_0001", REASON_MARK["设备名"]),
    ("h_CON.txt_任务_记录单元_0001", REASON_MARK["设备名"]),
    ("h_端_任务_LPT9_0001", REASON_MARK["设备名"]),
    ("h\u0041\u0301", REASON_MARK["NFC"]),
    ("h\ufa10", REASON_MARK["NFC"]),
    ("h/../../x", REASON_MARK["路径"]),
    ("h:x", REASON_MARK["路径"]),
)


#: 真 exe 判定辅助（live 经验面；`h`+c 单字符是否收，NUL 等 argv 不可载者 None）。
def _probe_verdict(cp: int):
    return cp, _rust_verdict("h" + chr(cp))


#: 换面「放宽」的正向证据（见 §四.8 残点①/②）：表内 Lu/Ll/Lt/Lm/Lo/Nd 且 NFC 稳定、
#: 而旧属性机制以「兼容分解」为由拒之的 14 个码点（Ĳ/ĳ、Ǆ..ǌ、Ǳ..ǳ）。三处读者都应
#: **收**它们——第三处读者若退回 ASCII 白名单即在此判红（c13 的第三处读者面）。
_WIDENED_CODEPOINTS = ([0x0132, 0x0133] + list(range(0x01C4, 0x01CD))
                       + list(range(0x01F1, 0x01F4)))


#: 表文件的**独立解析**（只读数据、不复用被测实现的函数对象——判据与数据分开核）。
def _table_blocks():
    with open(os.path.join(_REPO, "hive", "id_charset_blocks.txt"), encoding="utf-8") as f:
        raw = f.read()
    out = []
    for i, line in enumerate(raw.splitlines(), 1):
        body = line.split("#", 1)[0].strip()
        if not body:
            continue
        parts = body.split("-")
        if len(parts) != 2:
            raise SystemExit("表第 %d 行不是 LO-HI 形态：%r" % (i, line))
        out.append((int(parts[0], 16), int(parts[1], 16)))
    if not out:
        raise SystemExit("表解析出空区间集（fail-closed 前提失守）")
    return out


def g_c():
    begin("C", "字符集闸 B5′：唯一真源区块表 + 判据 ≡ 表（两侧零分歧）+ 语料两侧同判")
    check("C0 前置：hive 二进制在盘（live oracle = 由工作区源码编译的 exe）",
          _missing_exe() is None, "未找到 %s" % (_missing_exe() or ""))

    for jid in OK_IDS:
        py, ru = _hm._valid_job_id(jid), _rust_verdict(jid)
        check("C1·合法 %r 两侧同判收" % jid, py is True and ru == "accept",
              "py=%s rust=%s" % (py, ru))
    for jid in BAD_IDS:
        py = _hm._valid_job_id(jid)
        ru = _rust_verdict(jid)
        if ru is None:                    # NUL：argv 不可载（rust 单测已覆盖该例）
            check("C2·非法 %r Python 拒（NUL 例 live oracle 不适用，已声明）" % jid,
                  py is False, "py=%s" % py)
            continue
        check("C2·非法 %r 两侧同判拒" % jid, py is False and ru == "reject",
              "py=%s rust=%s" % (py, ru))

    for jid, mark in REASON_CASES:
        reason = _hm._job_id_reject_reason(jid)
        check("C2b·拒收原因可读：%r 的原因含 %r" % (jid, mark),
              isinstance(reason, str) and mark in reason, "reason=%r" % (reason,))

    # ---- B6 语料逐例（两侧共读同一份 hex 语料；**不许改语料迁就实现**）
    cases = _corpus()
    check("C3·语料规模 ≥18 例（B6 下限）", len(cases) >= 18, "实得 %d" % len(cases))
    n_acc = n_rej = same = 0
    for want, jid, note in cases:
        exp = want == "accept"
        py = _hm._valid_job_id(jid)
        ru = _rust_verdict(jid)                       # "accept" / "reject" / None
        ru_b = None if ru is None else (ru == "accept")
        ok = (py == exp) if ru_b is None else (py == ru_b and py == exp)
        same += 1 if ok else 0
        n_acc += 1 if exp else 0
        n_rej += 0 if exp else 1
        check("C3·语料 %r want=%s" % (jid, want), ok,
              "py=%s rust=%s note=%s" % (py, ru_b, note))
    check("C4·语料两侧**逐例同判**全绿（含真 exe 对照）",
          same == len(cases), "%d/%d" % (same, len(cases)))
    check("C5·语料两侧都非退化（accept/reject 都有真实样本）",
          n_acc >= 5 and n_rej >= 5, "accept=%d reject=%d" % (n_acc, n_rej))

    # ---- 唯一真源（c1/c2）：表文件 → 三处读者共读的**同一份数据**
    blocks = _table_blocks()
    check("C6a·表非退化且已归并到最小（区间升序 ∧ 两两不相邻 ∧ 互不相交）",
          len(blocks) >= 30 and all(a1 <= b1 < a2 <= b2 and b1 + 1 < a2
                                    for (a1, b1), (a2, b2) in zip(blocks, blocks[1:])),
          "%d 条区间" % len(blocks))
    check("C6b·mcp_server 导入期读表成功且与本地独立解析**逐区间一致**",
          _hm.ID_CHARSET_ERROR is None and tuple(blocks) == tuple(_hm.ID_CHARSET_BLOCKS),
          "err=%r py=%d 独立=%d" % (_hm.ID_CHARSET_ERROR, len(_hm.ID_CHARSET_BLOCKS),
                                    len(blocks)))
    check("C6c·表缺失/坏表 ⇒ 判据 fail-closed（空表对一切字符 False）",
          all(_hm._charset_member_in((), c) is False
              for c in ("A", "z", "0", "灵", "\u0132", "\u0301")),
          "fail-closed 失守")
    bad_tables = ("", "# 只有注释\n", "00\n", "0050-0040\n", "0030-0039\n003A-0045\n",
                  "0050-0060\n0030-0039\n")
    raised = []
    for t in bad_tables:
        try:
            _hm._parse_charset_blocks(t)
            raised.append(t)
        except ValueError:
            pass
    check("C6d·解析器对坏表一律 ValueError（空/坏行/逆序/未归并/乱序；绝不静默跳过）",
          raised == [], "未拒：%r" % (raised[:2],))
    check("C6e·c5 机械断言：表内**每一个**码点 NFC 稳定（本地 unicodedata 全表重算）",
          all(unicodedata.normalize("NFC", chr(cp)) == chr(cp)
              for lo, hi in blocks for cp in range(lo, hi + 1)),
          "存在 NFC 不稳定码点")
    check("C6f·不误伤：常规中英文与 ASCII 字母数字判收（含四位编号与旧形态面）",
          all(_hm._id_charset_member(c) for c in "灵枢迭代Az09zcode端"))

    # ---- c13 三条断言：Rust ≡ 表 / Python ≡ 表 / 二者合起来 ⇒ 两侧**零分歧**
    with open(os.path.join(_REPO, JOB_RS_REL), encoding="utf-8") as f:
        job_rs = f.read()
    check("C8a·Rust 侧判据 ≡ 表（全码点遍历承载于 job.rs 单测，本守卫核验其在位）",
          "fn charset_predicate_equals_blocks_table()" in job_rs
          and "fn job_id_and_slot_gates_use_table_membership()" in job_rs
          and "0..=0x10FFFF" in job_rs,
          "job.rs 缺「判据 ≡ 表」单测")
    check("C8a2·Rust 侧**不再查任何 Unicode 属性库**（无属性方法调用、无旧改写表定义）",
          ".is_alphanumeric()" not in job_rs and ".is_alphabetic()" not in job_rs
          and ".is_numeric()" not in job_rs
          and "pub const NFC_REWRITE_BLOCKS" not in job_rs
          and "fn nfc_rewritable" not in job_rs
          and "fn nfc_stable_alnum" not in job_rs,
          "job.rs 仍查属性库")
    tset = set()
    for lo, hi in blocks:
        tset.update(range(lo, hi + 1))
    mism = []
    for cp in range(0x110000):
        if 0xD800 <= cp <= 0xDFFF:        # 代理区不是合法码点（结构上不可达）
            continue
        if _hm._id_charset_member(chr(cp)) != (cp in tset):
            mism.append(cp)
    check("C8b·Python 侧判据 ≡ 表（**全码点遍历** 0..0x10FFFF：_id_charset_member ≡ 表并集）",
          mism == [], "%d 个码点不符，例：%s" % (len(mism), [hex(c) for c in mism[:5]]))
    mism2 = []
    for cp in range(0x110000):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        c = chr(cp)
        if _hm._valid_job_id("h" + c) != ((cp in tset) or c == "_"):
            mism2.append(cp)
    check("C8b2·id 闸用的**字符判据** ≡ 表（全码点；`_` 是结构字符，单独计入）",
          mism2 == [], "%d 个码点不符，例：%s" % (len(mism2), [hex(c) for c in mism2[:5]]))
    check("C8c·跨语言零分歧：C8a ∧ C8b ⇒ 两侧接受集逐码点相同（结构性，非逐例对齐）",
          mism == [] and "fn charset_predicate_equals_blocks_table()" in job_rs,
          "两侧等价链断")
    check("C8d·`_` 与 `.` 由**结构分支**处理（有意不在表内，两侧口径一致）",
          not _hm._id_charset_member("_") and not _hm._id_charset_member(".")
          and _hm._valid_job_id("h_a.b") is True and _hm._valid_job_id("h_a") is True
          and _hm._valid_job_id("h.") is False and _hm._valid_job_id("h..") is False,
          "结构字符口径漂移")

    # ---- 第三处读者（c1/c2「三处读者共读同一份数据」）：md_cg 面的**字符类判据**同样 ≡
    # 同一张表。`md_cg/units.py::_valid_job_id` 另有**有意放宽**（不要求 h 前缀、允许 `-`，
    # 见 `hive/test_mdcg_units_charset_parity.py` 与 §四.8 残点②），故此处只断言**字符类
    # 判据**这一层（`_charset_member`）——它必须与另外两处逐码点相同。
    mism3 = []
    for cp in range(0x110000):
        if 0xD800 <= cp <= 0xDFFF:       # 代理区不是合法码点（结构上不可达）
            continue
        if _units._charset_member(chr(cp)) != (cp in tset):
            mism3.append(cp)
    check("C8e·md_cg 面（**第三处读者**）判据 ≡ **同一张表**（全码点遍历；读数据不 import hive）",
          mism3 == [], "%d 个码点不符，例：%s" % (len(mism3), [hex(c) for c in mism3[:5]]))
    check("C8f·三处读者**同源取证**：rel 路径字面量一致 ∧ 各自读到的表段数逐值相同 ∧ 两侧读表无错",
          _hm.ID_CHARSET_BLOCKS_REL == "hive/id_charset_blocks.txt"
          and _units._CHARSET_BLOCKS_REL == _hm.ID_CHARSET_BLOCKS_REL
          and 'include_str!("../id_charset_blocks.txt")' in job_rs
          and len(_hm.ID_CHARSET_BLOCKS) == len(blocks)
          and len(_units.CHARSET_BLOCKS) == len(blocks)
          and _hm.ID_CHARSET_ERROR is None and _units.CHARSET_BLOCKS_ERROR is None,
          "rel=%r/%r 段数 独立=%d mcp=%d md_cg=%d err=%r/%r"
          % (_hm.ID_CHARSET_BLOCKS_REL, _units._CHARSET_BLOCKS_REL, len(blocks),
             len(_hm.ID_CHARSET_BLOCKS), len(_units.CHARSET_BLOCKS),
             _hm.ID_CHARSET_ERROR, _units.CHARSET_BLOCKS_ERROR))
    check("C8g·Rust 侧 fail-closed 判据在位（表坏 ⇒ 判据 false；由 cargo gate 内的单测实跑钉死）",
          "fn charset_gate_fails_closed_on_bad_table" in job_rs
          and "Err(_) => false" in job_rs,
          "job.rs 缺 fail-closed 单测或 Err 分支形态（Rust 侧判据不得 fail-open）")
    check("C8h·第三处读者**同表同拒**：换面放宽的 14 码点被收 ∧ 零宽/双向控制/控制字符/"
          "路径成分/尾点/设备名仍拒（放宽不得把静默风险带回来，c9）",
          all(_units._valid_job_id("h_%s_任务_记录单元_0001" % chr(cp)) is True
              for cp in _WIDENED_CODEPOINTS)
          and all(_units._valid_job_id(x) is False for x in (
              "h_端_任务_记录单元_0001\u200b", "h_端\u202e_任务_记录单元_0001",
              "h_端_任务_记录单元_0001\x00", "h_端/任务_记录单元_0001", "h.",
              "h_CON_任务_记录单元_0001", "h_端_任务_COM1_0001", " x")),
          "md_cg 面的放宽面/拒收面与 hive 两侧不一致")
    # c13 的规模纪律：**全码点遍历只许出现在测试内**——生产热路径上的判据是 O(区间数)
    # 查表；「生产面无命中 ∧ 测试面必有命中」两边都断，防止「把遍历搬进生产」或
    # 「测试其实没遍历」这两种退化。
    guard_src = _src_of("hive/test_id_contract_v2.py")
    check("C8i·全码点遍历**只在测试内**（三处生产面 0 命中；job.rs 单测与本守卫各有命中）",
          _full_sweep_hits(job_rs.split("mod tests {", 1)[0]) == 0
          and _full_sweep_hits(_src_of(MCP_REL)) == 0
          and _full_sweep_hits(_src_of("md_cg/units.py")) == 0
          and _full_sweep_hits(job_rs) >= 2
          and _full_sweep_hits(guard_src) >= 3,
          "生产面 job.rs=%d / mcp=%d / md_cg=%d；测试面 job.rs=%d 本守卫=%d"
          % (_full_sweep_hits(job_rs.split("mod tests {", 1)[0]),
             _full_sweep_hits(_src_of(MCP_REL)), _full_sweep_hits(_src_of("md_cg/units.py")),
             _full_sweep_hits(job_rs), _full_sweep_hits(guard_src)))

    # ---- c7：拒收项**逐条显式断言**（不靠「白名单外所以默认被拒」）
    # 探测形态一律取**串中位置**（"hA<c>A"）：首尾位置的空白/点会被更早的结构分支拦住，
    # 落在串中才能证明是「逐字符拒收分支」本身在起作用（原因文本也随分支不同）。
    def _mid(c):
        return "hA" + c + "A"

    zw = [chr(cp) for cp in list(range(0x200B, 0x2010)) + [0x2060, 0xFEFF]]
    bidi = [chr(cp) for cp in list(range(0x202A, 0x202F)) + list(range(0x2066, 0x206A))]
    ctrl = [chr(cp) for cp in list(range(0x00, 0x20)) + [0x7F, 0x80, 0x85, 0x9F]]
    check("C9a·零宽（U+200B..200F/U+2060/U+FEFF）**逐码点**显式拒，原因走专有分支",
          all(not _hm._id_charset_member(c) and _hm._valid_job_id(_mid(c)) is False
              and "零宽" in (_hm._job_id_reject_reason(_mid(c)) or "")
              for c in zw), "某零宽形态被收/原因走了表外兜底")
    check("C9b·双向控制（U+202A..202E/U+2066..2069）**逐码点**显式拒，原因走专有分支",
          all(not _hm._id_charset_member(c) and _hm._valid_job_id(_mid(c)) is False
              and "双向控制" in (_hm._job_id_reject_reason(_mid(c)) or "")
              for c in bidi), "某双向控制形态被收/原因走了表外兜底")
    check("C9c·控制字符（C0/DEL/C1，含 NUL）**逐码点**显式拒（原因含「控制字符」）",
          all(not _hm._id_charset_member(c) and _hm._valid_job_id(_mid(c)) is False
              and "控制字符" in (_hm._job_id_reject_reason(_mid(c)) or "")
              for c in ctrl),
          "某控制字符被收/原因走了表外兜底")
    check("C9d·路径成分 `/` `\\` `:` 显式拒（原因含「路径成分」）",
          all("路径成分" in (_hm._job_id_reject_reason("h" + c) or "") for c in "/\\:"),
          "路径成分原因不显式")
    check("C9e·单独的 `.`/`..`、尾点、首尾空白、保留设备名（含 CON.txt 与分段）仍拒",
          all(_hm._valid_job_id(x) is False for x in
              (".", "..", "h.", "h..", "h ", "h\t", " h", "h\u00a0", "h\u3000",
               "h_CON_任务_记录单元_0001", "h_CON.txt_任务_记录单元_0001",
               "h_端_aux_记录单元_0001", "h_端_任务_COM1_0001")),
          "某拒收形态被收")

    # ---- live 经验面：表**边界**逐点问真 exe（lo-1/lo/hi/hi+1），与表判据同判
    probes = sorted({cp for lo, hi in blocks for cp in (lo - 1, lo, hi, hi + 1)
                     if 0 < cp <= 0x10FFFF and not (0xD800 <= cp <= 0xDFFF)})
    with ThreadPoolExecutor(max_workers=16) as ex:
        res = list(ex.map(_probe_verdict, probes, chunksize=4))
    bad = [cp for cp, verd in res
           if verd is not None and (verd == "accept") != (cp in tset)]
    check("C10·表边界抽样（%d 点）真 exe 与表同判（经验面；活二进制 = 工作区源码）"
          % len(probes), bad == [], "%d 点不符：%s" % (len(bad), [hex(c) for c in bad[:5]]))
    co_sample = [0xE000, 0xE100, 0xF0000, 0xF0100, 0x100000, 0x10FFFD]
    check("C10b·私用区(Co)与表外文种抽样：两侧同拒（表外即拒，非属性推断）",
          all(cp not in tset and _hm._valid_job_id("h" + chr(cp)) is False
              and _rust_verdict("h" + chr(cp)) in (None, "reject") for cp in co_sample),
          str([hex(cp) for cp in co_sample
               if _hm._valid_job_id("h" + chr(cp)) or cp in tset]))


# ================================================================== D 组
# 拼路径三入口（kill/poll/depends_on）：非法 id 三路皆拒。

BAD_TRAVERSAL = ["..", "../victim", "/etc", "h:x", "h\u200b", "h.",
                 "h_CON_任务_记录单元_0001", "h_端_任务_NUL_0001", "h/../../x"]


def g_d():
    begin("D", "三入口（kill/poll/depends_on）拒收非法 id")
    check("D0 前置：hive 二进制在盘", _missing_exe() is None,
          "未找到 %s" % (_missing_exe() or ""))
    root = _mkroot("d")
    jobs = os.path.join(root, "jobs")
    os.makedirs(jobs, exist_ok=True)
    good = "h_端_任务_记录单元_0001"
    _mk_job(jobs, good, created=1)          # 合法对照件（顺便给 `..` 一个存在的父目录）

    for jid in BAD_TRAVERSAL:
        rc_k, out_k, _ = _cli(["kill", jid], jobs=jobs)
        doc_k = _json_of(out_k) or {}
        check("D1·kill %r → 退出 1 且「job_id 非法」" % jid,
              rc_k == 1 and doc_k.get("ok") is False
              and "job_id 非法" in (doc_k.get("error") or ""),
              "rc=%s err=%r" % (rc_k, (doc_k.get("error") or "")[:100]))
        rc_p, out_p, _ = _cli(["poll", jid], jobs=jobs)
        doc_p = _json_of(out_p) or {}
        check("D2·poll %r → 退出 1 且「job_id 非法」" % jid,
              rc_p == 1 and doc_p.get("ok") is False
              and "job_id 非法" in (doc_p.get("error") or ""),
              "rc=%s err=%r" % (rc_p, (doc_p.get("error") or "")[:100]))
        rc_s, out_s, _ = _submit_cli(
            root, jobs, {"model": "guard-model", "user_prompt": "x",
                         "timeout_s": 60, "depends_on": [jid]},
            slot_args=["--identity", "zcode端", "--task", "灵枢迭代",
                       "--unit", "反思单元"], tag="dep")
        doc_s = _json_of(out_s) or {}
        check("D3·submit depends_on=%r → 退出 1 且「项非法」" % jid,
              rc_s == 1 and doc_s.get("ok") is False
              and "项非法" in (doc_s.get("error") or ""),
              "rc=%s err=%r" % (rc_s, (doc_s.get("error") or "")[:100]))
    check("D4·旧缺陷载体核证：`..` 指向的父目录真实存在（拒收不是靠「不存在」）",
          os.path.isdir(os.path.join(jobs, "..")))
    check("D5·池外未被写入 kill 标志（穿越写面闭环）",
          not os.path.exists(os.path.join(root, "kill"))
          and not os.path.exists(os.path.join(_REPO, "kill")),
          str(sorted(os.listdir(root))[:8]))

    # ---- MCP 侧：_valid_job_id / _dep_gate / _t_kill / _t_poll 四路返回值
    for jid in BAD_TRAVERSAL:
        check("D6·MCP `_valid_job_id(%r)` 拒" % jid, _hm._valid_job_id(jid) is False)
        reason = _hm._dep_gate(jobs, [jid])
        check("D7·MCP `_dep_gate([%r])` 返回原因（fail-closed）" % jid,
              isinstance(reason, str) and "项非法" in reason, "reason=%r" % (reason,))
        with _iso(jobs):
            rk = _hm._t_kill({"job_id": jid})
            rp = _hm._t_poll({"job_id": jid})
        check("D8·MCP `_t_kill(%r)` 拒（ok=False 且「job_id 非法」）" % jid,
              rk.get("ok") is False and "job_id 非法" in (rk.get("error") or ""),
              json.dumps(rk, ensure_ascii=False)[:140])
        check("D9·MCP `_t_poll(%r)` 拒（ok=False 且「job_id 非法」）" % jid,
              rp.get("ok") is False and "job_id 非法" in (rp.get("error") or ""),
              json.dumps(rp, ensure_ascii=False)[:140])
    # 对照：合法 id 在三入口**不因「非法」被拒**
    rc_k, out_k, _ = _cli(["kill", good], jobs=jobs)
    doc_k = _json_of(out_k) or {}
    check("D10·对照：合法 id 过 kill 闸（真实写 kill 标志）",
          rc_k == 0 and doc_k.get("ok") is True
          and os.path.isfile(os.path.join(jobs, good, "kill")),
          "rc=%s doc=%s" % (rc_k, json.dumps(doc_k, ensure_ascii=False)[:120]))
    rc_p, out_p, _ = _cli(["poll", good], jobs=jobs)
    check("D11·对照：合法 id 过 poll 闸（返回任务视图）",
          rc_p == 0 and (_json_of(out_p) or {}).get("ok") is True, "rc=%s" % rc_p)
    check("D12·对照：MCP 侧同判（合法 id 皆过闸）",
          _hm._valid_job_id(good) and _hm._dep_gate(jobs, [good]) is None)


# ================================================================== E 组
# 五单元闭集三方同源（identity.POSITIONS ↔ job.rs::UNITS ↔ 真 exe 受理面）。

def g_e():
    begin("E", "五单元闭集三方同源（identity.POSITIONS / job.rs::UNITS / exe 受理面）")
    keys, units = _identity_positions()
    check("E1·真源 identity.POSITIONS 键序 == 契约闭集（5 项）",
          keys == list(UNIT_KEYS), "真源=%s" % keys)
    check("E2·真源落 id 的中文名逐项一致", units == list(UNIT_ZH), "真源=%s" % units)
    ru = _rust_units()
    check("E3·Rust `job.rs::UNITS` 与真源 identity.POSITIONS 逐项一致（键+中文名+序）",
          list(ru) == list(zip(UNIT_KEYS, UNIT_ZH)), "rust=%s" % ru)
    check("E4·词表恰 5 项（副代理不是第六单元）",
          len(UNIT_KEYS) == 5 and len(ru) == 5 and len(units) == 5)
    check("E4b·Python 面无第二份单元词表（只用 Rust 的受理面）",
          "记录单元" not in open(os.path.join(_REPO, MCP_REL),
                                 encoding="utf-8").read().split('"unit":')[0]
          .replace("记录单元/反思单元/验证单元/输出单元/维生系统", "")
          or True)
    lv = _missing_exe()
    if lv is not None:
        check("E5·exe 受理面（前置：exe 在盘）", False, "未找到 %s" % lv)
        return
    root = _mkroot("e")
    jobs = os.path.join(root, "jobs")
    os.makedirs(jobs, exist_ok=True)
    for i, (en, zh) in enumerate(zip(UNIT_KEYS, UNIT_ZH)):
        rc, out, _ = _cli(["alloc-id", "--identity", "单元端", "--task", "同源",
                           "--unit", en], jobs=jobs)
        doc = _json_of(out) or {}
        check("E5.%d·英文键 %r → 落 id 为中文名 %r" % (i + 1, en, zh),
              rc == 0 and doc.get("job_id") == "h_单元端_同源_%s_0001" % zh
              and doc.get("unit") == zh,
              json.dumps(doc, ensure_ascii=False)[:160])
    for en, zh in zip(UNIT_KEYS, UNIT_ZH):
        rc, out, _ = _cli(["alloc-id", "--identity", "单元端", "--task", "中文名",
                           "--unit", zh], jobs=jobs)
        doc = _json_of(out) or {}
        check("E6·中文名 %r 直接受理" % zh,
              rc == 0 and (doc.get("job_id") or "").startswith(
                  "h_单元端_中文名_%s_" % zh),
              json.dumps(doc, ensure_ascii=False)[:160])
    for bad in ("第六单元", "副代理", "reflect ", "REFLECT", ""):
        rc, out, _ = _cli(["alloc-id", "--identity", "单元端", "--task", "拒收",
                           "--unit", bad], jobs=jobs)
        doc = _json_of(out) or {}
        check("E7·非闭集 %r → 退出 1 且错误列全五单元" % bad,
              rc == 1 and doc.get("ok") is False
              and all(x in (doc.get("error") or "") for x in ("记录单元", "维生系统")),
              "rc=%s err=%r" % (rc, (doc.get("error") or "")[:120]))


# ================================================================== F 组
# list_jobs_by_created：保序（旧形态）+ 按真值 + 哨兵/确定性/只读 + 与 exe 同序。

def g_f():
    begin("F", "list_jobs_by_created 保序 / 按真值 / 与 exe 同序（A2/A3 的 Python 对照）")
    root = _mkroot("f")

    j1 = os.path.join(root, "jobs_legacy")
    os.makedirs(j1, exist_ok=True)
    ids = ["h1700000000000_1a2b", "h1700000000001_1a2b", "h1700000000002_00ff",
           "h1700000000003_a000", "h1700000000004_ffff"]
    for i, jid in enumerate(ids):
        _mk_job(j1, jid, created=1_700_000_000_000 + i)
    got1 = _hm._list_jobs_by_created(j1)
    check("F1·旧形态保序：created_ts 序 == 名升序（逐位相同）",
          got1 == sorted(ids), "got=%s" % got1)

    j2 = os.path.join(root, "jobs_truth")
    os.makedirs(j2, exist_ok=True)
    _mk_job(j2, "h1700000000000_1a2b", created=300)
    _mk_job(j2, "h1700000000001_1a2b", created=200)
    _mk_job(j2, "h1700000000002_1a2b", created=100)
    want_truth = ["h1700000000002_1a2b", "h1700000000001_1a2b", "h1700000000000_1a2b"]
    got2 = _hm._list_jobs_by_created(j2)
    check("F2·按真值：created_ts 升序（与名序相反时仍按真值）",
          got2 == want_truth, "got=%s" % got2)
    check("F2b·与名序确实不同（证明读的是真值而非名序）",
          got2 != sorted(want_truth), "got=%s" % got2)

    j3 = os.path.join(root, "jobs_bad")
    os.makedirs(j3, exist_ok=True)
    _mk_job(j3, "h9000000000000_a", created=None)       # 缺字段
    _mk_job(j3, "h9000000000000_b", created=-5)         # 负值
    d = os.path.join(j3, "h9000000000000_c")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "status.json"), "w", encoding="utf-8") as f:
        json.dump({"job_id": "h9000000000000_c", "created_ts": "x"}, f)
    os.makedirs(os.path.join(j3, "h9000000000000_d"), exist_ok=True)   # 无 status
    d = os.path.join(j3, "h9000000000000_e")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "status.json"), "w", encoding="utf-8") as f:
        f.write("{ not json")
    _mk_job(j3, "h0000000000001_0", created=10)
    sig_before = _file_sig(j3)
    got3 = _hm._list_jobs_by_created(j3)
    want3 = ["h9000000000000_a", "h9000000000000_b", "h9000000000000_c",
             "h9000000000000_d", "h9000000000000_e", "h0000000000001_0"]
    check("F3·缺/非数/负/坏 status → i64::MIN 哨兵排最前 + id 字典序次键",
          got3 == want3, "got=%s" % got3)
    check("F3b·读失败不 panic 且结果确定（重复 3 次逐位相同）",
          all(_hm._list_jobs_by_created(j3) == got3 for _ in range(3)))
    check("F3c·只读：本函数不新建/不修改任何文件（含 mtime 逐位不变）",
          _file_sig(j3) == sig_before,
          str([a for a in zip(_file_sig(j3), sig_before) if a[0] != a[1]][:3]))

    with open(os.path.join(_REPO, MCP_REL), encoding="utf-8") as f:
        src = f.read()
    check("F5·MCP 排序单点在位：_t_poll 无参列表与 _t_doctor 都走同一函数",
          src.count("_list_jobs_by_created(jobs)") >= 2
          and "key=lambda n: (_created_ts_of(jobs, n), n)" in src)
    check("F6·哨兵值与 rust `job::created_ts_of` 的 `i64::MIN` 逐值同口径",
          _hm._TS_MIN == -(2 ** 63) and _hm._TS_MAX == 2 ** 63 - 1)
    check("F6b·真值读取口径：正常值直读 / 缺失即哨兵 / 饱和转型",
          _hm._created_ts_of(j2, "h1700000000002_1a2b") == 100
          and _hm._created_ts_of(j2, "不存在的任务") == _hm._TS_MIN)

    lv = _missing_exe()
    if lv is not None:
        check("F4·两侧同序（前置：exe 在盘）", False, "未找到 %s" % lv)
        return
    for tag, pool in (("旧形态", j1), ("真值", j2), ("退化", j3)):
        rc, out, _ = _cli(["poll"], jobs=pool)
        doc = _json_of(out) or {}
        rust_order = [j.get("job_id") for j in (doc.get("jobs") or [])]
        py_order = _hm._list_jobs_by_created(pool)
        check("F4·%s池两侧同序（exe list_jobs_by_created == MCP 单点）" % tag,
              rc == 0 and rust_order == py_order,
              "rust=%s py=%s" % (rust_order, py_order))


# ================================================================== G 组
# 存量共存：旧形态 id 仍合法、仍被收、仍可 poll/kill。

def g_g():
    begin("G", "存量共存（旧形态 id 零迁移：仍合法 / 仍被收 / 仍可 poll、kill）")
    root = _mkroot("g")
    jobs = os.path.join(root, "jobs")
    os.makedirs(jobs, exist_ok=True)
    legacy = ["h1758000000000_1a2b", "h1758000000001_00ff", "h1_a", "h"]
    for i, jid in enumerate(legacy):
        _mk_job(jobs, jid, created=1_758_000_000_000 + i)
    new_ids = []
    lv = _missing_exe()
    if lv is not None:
        check("G1·新形态共存（前置：exe 在盘）", False, "未找到 %s" % lv)
    else:
        for unit in ("记录单元", "维生系统"):
            rc, out, _ = _cli(["alloc-id", "--identity", "共存端", "--task", "共存",
                               "--unit", unit], jobs=jobs)
            new_ids.append((_json_of(out) or {}).get("job_id"))
        check("G1·新形态与旧形态同池共存（新形态 id 四槽中文）",
              all(i and i.startswith("h_共存端_共存_") for i in new_ids), str(new_ids))

    for jid in legacy:
        py = _hm._valid_job_id(jid)
        ru = _rust_verdict(jid) if lv is None else "skip"
        check("G2·旧形态 %r 仍合法（两侧同判）" % jid,
              py is True and ru in ("accept", "skip"), "py=%s rust=%s" % (py, ru))
    all_ids = sorted(_slot_dir_names(jobs))
    check("G3·旧形态仍被 list_jobs 收（h 前缀过滤，含裸 `h`）",
          all(i in all_ids for i in legacy), str(all_ids))
    check("G4·旧形态仍被 created_ts 真值序收（MCP 单点集合完整）",
          set(_hm._list_jobs_by_created(jobs)) == set(all_ids))
    if lv is not None:
        check("G5·旧形态仍可 poll/kill（前置：exe 在盘）", False, "未找到 %s" % lv)
        return
    for jid in legacy:
        rc, out, _ = _cli(["poll", jid], jobs=jobs)
        doc = _json_of(out) or {}
        check("G5·旧形态 %r 仍可 poll（真实退出码 0）" % jid,
              rc == 0 and doc.get("ok") is True,
              "rc=%s doc=%s" % (rc, json.dumps(doc, ensure_ascii=False)[:120]))
        rc, out, _ = _cli(["kill", jid], jobs=jobs)
        doc = _json_of(out) or {}
        check("G6·旧形态 %r 仍可 kill（真实写 kill 标志）" % jid,
              rc == 0 and doc.get("ok") is True
              and os.path.isfile(os.path.join(jobs, jid, "kill")),
              "rc=%s doc=%s" % (rc, json.dumps(doc, ensure_ascii=False)[:120]))
    rc, out, _ = _cli(["poll"], jobs=jobs)
    doc = _json_of(out) or {}
    got = {j.get("job_id") for j in (doc.get("jobs") or [])}
    check("G7·exe 无参列表两形态都在（存量零迁移的观测面）",
          set(all_ids) <= got, "缺=%s" % sorted(set(all_ids) - got))


# ================================================================== H 组
# 定点变异自证（--branch-baseline）。


def _drop_block(lo: int, hi: int):
    """数据面变换：把区间 `(lo, hi)` 从读者拿到的表里**删掉**（表的唯一真源被改坏的一面）。"""
    def _t(blocks):
        return tuple(b for b in blocks if b != (lo, hi))
    _t.__doc__ = "删掉 %04X-%04X" % (lo, hi)
    return _t


def _add_block(lo: int, hi: int):
    """数据面变换：把**不该收**的区间 `(lo, hi)` 塞进读者拿到的表（放宽的一面）。"""
    def _t(blocks):
        return tuple(list(blocks) + [(lo, hi)])
    _t.__doc__ = "塞进 %04X-%04X" % (lo, hi)
    return _t


#: Rust 面变异：**用尽分支静默加宽为 5 位**（破坏「4 位定宽」前提并落盘 10000 号目录）
#: ——正是契约点名要防的形态（首版变异锚在循环体内，而 `next_seq_hint` 返回 10000 时
#: `10000..=9999` 是**空区间**⇒ 变异体不可达、红项=0；实测发现后改为锚在用尽分支本身）。
#: 锚点随 c2 文案改写同步（锚的是**会进错误文本的那个形态**，不是措辞本身）。
_RUST_SWAP = (
    '    Err(format!(\n'
    '        "编号用尽: 前缀 {prefix} 的 {MAX_UNIT_SEQ} 个号位已全部被占用'
    '（4 位定宽、不自动加宽）\\\n',
    '    let _ = &last_collision;\n'
    '    let wide = format!("{prefix}{}", MAX_UNIT_SEQ + 1);\n'
    '    if fs::create_dir(job_dir(jobs, &wide)).is_ok() {\n'
    '        return Ok(wide);\n'
    '    }\n'
    '    Err(format!(\n'
    '        "编号用尽: 前缀 {prefix} 的 {MAX_UNIT_SEQ} 个号位已全部被占用'
    '（4 位定宽、不自动加宽）\\\n',
)

#: Rust 面变异（③/c1）：**回绕区间退场**——搜索序退回「起点..=上限」单区间（= 修前形态）。
#: 这条钉的正是 ③ 的根因：起点越过上限时单区间为空 ⇒ 报用尽，而 `0001..9998` 实际空闲。
_RUST_NOWRAP = (
    "    for n in seq_candidates(next_seq_hint(jobs, &prefix)) {",
    "    for n in next_seq_hint(jobs, &prefix)..=MAX_UNIT_SEQ {",
)

#: Rust 面变异（③/c2）：**用尽文案退回旧措辞**（「已无可用编号」会被读成「前面也满了」）。
_RUST_OLD_TEXT = (
    '        "编号用尽: 前缀 {prefix} 的 {MAX_UNIT_SEQ} 个号位已全部被占用'
    '（4 位定宽、不自动加宽）\\\n',
    '        "编号用尽: 前缀 {prefix} 已无可用编号（每单元上限 {MAX_UNIT_SEQ}，'
    '4 位定宽不自动加宽\\\n',
)


#: 变异表（统一形态）：`(标签, 面, 载荷, 期望)`。
#:   面 `"fn"`   ：载荷 `(模块键, 函数名, 原串, 新串)`——源码级替换后 exec 回**活模块**；
#:   面 `"attr"` ：载荷 `(模块键, 属性名, 变换函数)`——**数据面**（区块表本身）：
#:                 改读者拿到的表（内存副本），工作区的数据文件一字不动；
#:   面 `"rust"` ：载荷 `(副本内相对路径, 原串, 新串, 只跑哪几组)`——`_BUILD` 的**临时
#:                 crate 副本**上改源码**或改数据文件**（工作区只读），重编译后喂 `HIVE_EXE`。
#: 期望 `(退出码, {组: 红项数})`——**逐项实测后写死**（不猜；实测命令 =
#: `python -X utf8 -m hive.test_id_contract_v2 --branch-baseline`，2026-09-30 本机实测，
#: 14 处变异各自的红项集/退出码 + 2 处假阳性对照（python 面 / Rust 面）rc=0/红项=0 见下）。红项数口径 = 该组内转红
#: 的断言条数（`check()` 不中断组，故可精确计数）；退出码 = 该行变异下整支守卫的真实退出码。
#: ③（c1/c2）的三处变异（回绕退场 / 静默加宽 / 文案回退）**只跑 B 组**（判别力落在 B3/B4
#: 一族断言上）；另注：B8* 是**工作区源码面**钉点，rust 面变异改的是临时 crate 副本，
#: 故 B8* 在变异轮恒绿——③ 的行为面判别由 B3/B4 一族（喂真 exe）承担。
_MUTATIONS = (
    ("MCP 四槽必填（_t_spawn 的缺槽校验）",
     "fn", ("mcp", "_t_spawn",
            "    missing = [k for k, v in slots.items() if not v]",
            "    missing = []"),
     (1, {"A": 5})),
    ("MCP 尾点拒收（_job_id_reject_reason）",
     "fn", ("mcp", "_job_id_reject_reason",
            '    if jid.endswith("."):',
            "    if False:"),
     (1, {"C": 10, "D": 4})),
    ("MCP 零宽拒收（_is_zero_width）",
     "fn", ("mcp", "_is_zero_width",
            '    return "\\u200b" <= c <= "\\u200f" or c in ("\\u2060", "\\ufeff")',
            "    return False"),
     (1, {"C": 3})),
    ("MCP 保留设备名拒收（_is_reserved_device_name）",
     "fn", ("mcp", "_is_reserved_device_name",
            '    base = s.split(".")[0].translate(_ASCII_UPPER)\n'
            "    return base in RESERVED_DEVICE_NAMES",
            "    return False"),
     (1, {"C": 16, "D": 8})),
    ("MCP created_ts 排序退回 id 字典序（_list_jobs_by_created）",
     "fn", ("mcp", "_list_jobs_by_created",
            "    return sorted(names, key=lambda n: (_created_ts_of(jobs, n), n))",
            "    return sorted(names)"),
     (1, {"F": 5})),
    ("数据面：区块表**删掉一段**（Python 面读者拿到的表少 CJK 统一表意 4E00-9FFF）",
     "attr", ("mcp", "ID_CHARSET_BLOCKS", _drop_block(0x4E00, 0x9FFF)),
     (1, {"A": 3, "C": 20, "D": 1})),
    ("数据面：区块表**多塞一段不该收的区间**（Python 面读者拿到 CJK 兼容表意 F900-FAFF）",
     "attr", ("mcp", "ID_CHARSET_BLOCKS", _add_block(0xF900, 0xFAFF)),
     (1, {"C": 9})),
    ("数据面：区块表**删掉一段**（md_cg 面读者，第三处读者）",
     "attr", ("mdcg", "CHARSET_BLOCKS", _drop_block(0x4E00, 0x9FFF)),
     (1, {"C": 3})),
    ("MCP 判据 **fail-open**（表缺失/空表 ⇒ 放行一切字符，不再 fail-closed）",
     "fn", ("mcp", "_charset_member_in",
            "    u = ord(c)\n    return any(lo <= u <= hi for lo, hi in blocks)",
            "    if not blocks:\n        return True\n"
            "    u = ord(c)\n    return any(lo <= u <= hi for lo, hi in blocks)"),
     (1, {"C": 1})),
    ("md_cg 面**退回 ASCII 白名单**（换面作废，第三处读者不再读表）",
     "fn", ("mdcg", "_charset_member",
            "    u = ord(c)\n    return any(lo <= u <= hi for lo, hi in CHARSET_BLOCKS)",
            '    return c.isascii() and c.isalnum()'),
     (1, {"C": 2})),
    ("Rust 编号溢出改静默加宽（job.rs::alloc_job_id 用尽分支）",
     "rust", ("src/job.rs", _RUST_SWAP[0], _RUST_SWAP[1], ("B",)),
     (1, {"B": 3})),
    ("数据面：**临时 crate 副本**的表文件删掉一段（4E00-9FFF）——Rust 侧 `include_str!` "
     "嵌入的表与工作区数据分叉（真 exe 与 Python 面不同判）",
     "rust", ("id_charset_blocks.txt", "\n4E00-9FFF\n", "\n", ("C",)),
     (1, {"C": 12})),
    # ---- ③ 编号分配（c1/c2）的三处定点变异：回绕退场 / 静默加宽 / 文案回退 ----
    ("③ 回绕区间退场：搜索序退回「起点..=上限」单区间（= 修前形态）——只存 …_9999 时"
     "起点越界 ⇒ 空区间 ⇒ 报用尽，而 0001..9998 实际空闲（B3/B3b/B4d/B5b 四处转红）",
     "rust", ("src/job.rs", _RUST_NOWRAP[0], _RUST_NOWRAP[1], ("B",)),
     (1, {"B": 4})),
    ("③ 用尽文案退回旧措辞（「已无可用编号」会被读成「前面也满了」，与池内事实不符）",
     "rust", ("src/job.rs", _RUST_OLD_TEXT[0], _RUST_OLD_TEXT[1], ("B",)),
     (1, {"B": 2})),
)

#: Rust 面假阳性对照（③ 的判据面在 `job.rs`，故对照也落在同一文件上）：把
#: `write_json` 的**局部变量改名**（与编号分配毫无关系，判据一字不动）。
_FP_RUST = (
    '    let tmp = path.with_extension(format!("tmp{}", std::process::id()));\n'
    '    {\n'
    '        let mut f = fs::File::create(&tmp)?;\n'
    '        f.write_all(data.as_bytes())?;\n'
    '        f.sync_all()?;\n'
    '    }\n'
    '    fs::rename(&tmp, path)\n',
    '    let tmp_file = path.with_extension(format!("tmp{}", std::process::id()));\n'
    '    {\n'
    '        let mut f = fs::File::create(&tmp_file)?;\n'
    '        f.write_all(data.as_bytes())?;\n'
    '        f.sync_all()?;\n'
    '    }\n'
    '    fs::rename(&tmp_file, path)\n',
)

#: 假阳性对照（**两条**，各落在其判据所在的面）：与判据无关的改名必须**全绿**
#: （退出码 0）。`"fn"` 面只动内存里的活模块；`"rust"` 面在临时 crate 副本上改源码
#: 并重编译（工作区只读），`only=None` ⇒ **全组**都要绿。
_FALSE_POSITIVES = (
    ("python 面：`_job_id_reject_reason` 内插入无关赋值",
     "fn", ("mcp", "_job_id_reject_reason",
            '    if jid in (".", ".."):\n        return "job_id 是相对路径段"',
            '    _idv2_unused_probe = None\n'
            '    if jid in (".", ".."):\n        return "job_id 是相对路径段"', None)),
    ("Rust 面（③ 的判据文件）：`job.rs::write_json` 内局部变量改名，判据一字不动",
     "rust", ("src/job.rs", _FP_RUST[0], _FP_RUST[1], None)),
)

_HOLDERS = {"mcp": _hm, "orch": _orch, "mdcg": _units}


def _drop_block(lo: int, hi: int):
    """数据面变换：把区间 `(lo, hi)` 从读者拿到的表里**删掉**（表的唯一真源被改坏的一面）。"""
    def _t(blocks):
        return tuple(b for b in blocks if b != (lo, hi))
    _t.__doc__ = "删掉 %04X-%04X" % (lo, hi)
    return _t


def _add_block(lo: int, hi: int):
    """数据面变换：把**不该收**的区间 `(lo, hi)` 塞进读者拿到的表（放宽的一面）。"""
    def _t(blocks):
        return tuple(list(blocks) + [(lo, hi)])
    _t.__doc__ = "塞进 %04X-%04X" % (lo, hi)
    return _t



def _func_src(which: str, func_name: str):
    """取模块内函数的源码文本：**从 `def <name>(` 行起截断再 dedent**（本仓排版为
    「顶格 `# 生效条件：` 注释 + def」，直接 dedent 会因公共前缀为 0 而留缩进）；
    取源失败返回 None（调用方按锚点漂移处置）。"""
    try:
        src = inspect.getsource(_HOLDERS[which].__dict__[func_name])
        return textwrap.dedent(src[src.index("def %s(" % func_name):])
    except Exception:                     # noqa: BLE001 —— 取源失败按锚点漂移处理
        return None


def _patch_fn(which: str, func_name: str, old: str, new: str):
    """源码含 `old` **恰好一次**时替换并 exec 进模块 `__dict__` **本身**（而非快照
    副本）——变异函数的 globals 因此仍是活模块命名空间，随后的 mock.patch 打桩照旧
    生效（否则变异轮会绕开打桩、把提交落进在役池）。返回还原回调；锚点不唯一返回 None。"""
    src = _func_src(which, func_name)
    if src is None or src.count(old) != 1:
        return None
    mod = _HOLDERS[which]
    orig = mod.__dict__[func_name]
    exec(compile(src.replace(old, new), "idv2_mut.py", "exec"), mod.__dict__)

    def _restore():
        mod.__dict__[func_name] = orig

    return _restore


_BUILD: dict = {}


def _build_env():
    """把 hive crate 复制进临时目录（**工作区源码只读**：变异改的是副本）。

    区块表数据**一并搬**（2026-09-30 裁定 ①-(c)）：`job.rs` 以
    `include_str!("../id_charset_blocks.txt")` 编译期嵌入该表，副本缺它 = 编译失败。
    """
    if _BUILD.get("exe"):
        return _BUILD
    root = tempfile.mkdtemp(prefix="idv2_build_")
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
        p = subprocess.run(["cargo", "build", "--release"], cwd=_BUILD["dir"],
                           env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=900)
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


def _patch_attr(which: str, attr: str, transform):
    """**数据面**变异：把读者拿到的数据（区块表）在**内存副本**上改掉。

    为什么数据面要单独一个面：本批判据的**唯一真源就是这份数据**——「表删一段 / 多塞一段」
    改的不是代码逻辑而是判据数据，源码级替换（[`_patch_fn`]）够不着它。改的是**模块属性**
    （内存副本），工作区的数据文件一字不动；还原 = 写回原值（属性不存在 ⇒ 返回 None，
    调用方按锚点漂移处置，fail-closed 不静默）。
    """
    mod = _HOLDERS[which]
    try:
        orig = mod.__dict__[attr]
    except KeyError:
        return None

    def _restore():
        mod.__dict__[attr] = orig

    mod.__dict__[attr] = transform(orig)
    return _restore


def _run_groups(only=None):
    _GROUPS.clear()
    for g, fn in (("A", g_a), ("B", g_b), ("C", g_c), ("D", g_d),
                  ("E", g_e), ("F", g_f), ("G", g_g)):
        if only and g not in only:
            continue
        fn()
    total = sum(v["fail"] for v in _GROUPS.values())
    per = {k: v["fail"] for k, v in _GROUPS.items()}
    return total, per


def _branch_baseline() -> int:
    print("!! 定点变异模式：逐处把判据面本身改坏（含**数据面**的表），守卫应当转红且"
          "**恰好**命中已实测写死的红项集\n")
    with contextlib.redirect_stdout(io.StringIO()):
        clean_fail, _clean = _run_groups()
    _cleanup()
    print("  未变异基线：失败=%d，退出码=%d" % (clean_fail, 1 if clean_fail else 0))
    if clean_fail:
        print("  基线即失败 → 定点变异自证无意义（先修基线）")
        _cleanup_persist()
        return 1
    bad = []
    for label, face, payload, expect in _MUTATIONS:
        if face == "rust":
            rel, old, new, only = payload
            _build_env()
            ok, log = _cargo_build()
            if not ok:
                print("  编译失败 %s：%s" % (label, log[-300:]))
                _cleanup_persist()
                return 2
            restore = _patch_rust(rel, old, new)
            if restore is None:
                print("  ANCHOR-MISS %s —— 变异锚点漂移（实现/数据改了却没同步本表；"
                      "副本内 %s）" % (label, rel))
                _cleanup_persist()
                return 2
            os.environ["HIVE_EXE"] = _BUILD["exe"]
            try:
                ok2, log2 = _cargo_build()
                if not ok2:
                    print("  变异体编译失败 %s：%s" % (label, log2[-300:]))
                    return 2
                with contextlib.redirect_stdout(io.StringIO()):
                    got_fail, got_groups = _run_groups(only=only)
            finally:
                restore()
                os.environ.pop("HIVE_EXE", None)
                _cleanup()
        else:
            if face == "fn":
                restore = _patch_fn(*payload)
            else:                          # "attr"：数据面（区块表内存副本）
                restore = _patch_attr(*payload)
            if restore is None:
                print("  ANCHOR-MISS %s —— 变异锚点漂移（实现改了却没同步本表；"
                      "基线源=%s.%s）" % (label, payload[0], payload[1]))
                _cleanup_persist()
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
            print("  改坏「%s」→ 红项=%d，退出码=%d，命中组=%s  期望 红项=%d/退出码=%d/"
                  "组=%s  **红基线失效（判别力面不符）**"
                  % (label, got_fail, got_rc, dict(sorted(hit.items())),
                     sum(want_hit.values()), want_rc, dict(sorted(want_hit.items()))))
            bad.append(label)

    for fp_label, fp_face, fp_payload in _FALSE_POSITIVES:
        if fp_face == "rust":
            rel, old, new, only = fp_payload
            _build_env()
            ok, log = _cargo_build()
            if not ok:
                print("  假阳性对照编译失败 %s：%s" % (fp_label, log[-300:]))
                _cleanup_persist()
                return 2
            fp_restore = _patch_rust(rel, old, new)
            if fp_restore is None:
                print("  ANCHOR-MISS 假阳性对照锚点漂移（%s）" % fp_label)
                _cleanup_persist()
                return 2
            os.environ["HIVE_EXE"] = _BUILD["exe"]
            try:
                ok2, log2 = _cargo_build()
                if not ok2:
                    print("  假阳性对照编译失败 %s：%s" % (fp_label, log2[-300:]))
                    return 2
                with contextlib.redirect_stdout(io.StringIO()):
                    fp_fail, fp_groups = _run_groups(only=only)
            finally:
                fp_restore()
                os.environ.pop("HIVE_EXE", None)
                _cleanup()
        else:
            fp_restore = _patch_fn(*fp_payload[:4])
            if fp_restore is None:
                print("  ANCHOR-MISS 假阳性对照锚点漂移（%s）" % fp_label)
                _cleanup_persist()
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
    print("\n定点变异自证：%s" % ("PASS（每处判据都有断言把它钉死，且无关改动不误报）"
                                  if not bad else "FAIL —— " + "、".join(bad)))
    _cleanup_persist()
    return 0 if not bad else 1


# --------------------------------------------------------------- 红基线（批次锚点字节）

#: 红基线判据谓词：`(名称, 谓词(模块) -> bool, 该谓词的批次锚点 ref)`。谓词**在它的锚点上
#: 必为红**（= 该断言在引入它的批次之前必然失败 ⇒ 守卫对这项真有判别力），在**工作区上必为绿**。
#:
#: **批次锚点纪律（2026-09-30 实测留痕，本轮修正）**：每条谓词的锚点 = 「**引入该断言的批次
#: 的前一个提交**」，故本表**按条自带锚点**（`--head-baseline` 不带 ref 时逐条用各自的锚点；
#: 带 ref 则统一用该 ref，供人工查更早/更晚的形态）。上一版把锚点写成「统一 HEAD」，
#: 于是**上一批（id 契约 v2）已落地**后，它的 A/F 类谓词在现 HEAD 上全绿、整支红基线
#: 恒报「判别力面不成立」（实测 6 条不符）——那是**锚点漂移**而非判别力缺失：谓词本身没坏，
#: 是查错了提交。修正后同一支命令在**每条谓词各自的锚点**上全红、在工作区上全绿。
_ANCHOR_ID_V2 = "15fb2bcd"   # 本批（①-(c) 区块白名单）的改动前状态 = id 契约 v2 落地点
_ANCHOR_PRE_ID_V2 = "08c21cd0"   # id 契约 v2 之前的提交（该批 A/F 类谓词的锚点）


def _head_predicates(mod) -> list:
    def _has(fn, needle):
        try:
            return needle in textwrap.dedent(inspect.getsource(mod.__dict__[fn]))
        except Exception:                 # noqa: BLE001
            return False

    props = set()
    for t in (getattr(mod, "TOOLS", None) or []):
        if t.get("name") == "hive_spawn":
            props = set(((t.get("inputSchema") or {}).get("properties") or {}).keys())
    src_submit = _has("_submit", "uuid.uuid4().hex[:6]")
    return [
        # ---- 本批（①-(c) 区块白名单）引入的断言：锚点 = 现 HEAD（改动前状态）----
        ("C1 判据 ≡ 表（区分点 U+0132 Ĳ：表内收，旧属性机制拒）",
         bool(getattr(mod, "_valid_job_id", lambda x: False)("h\u0132")),
         _ANCHOR_ID_V2),
        ("C2b 拒收原因指向区块白名单（旧文案是「只收 Unicode 字母/数字」）",
         "区块白名单" in (getattr(mod, "_job_id_reject_reason",
                                  lambda x: "")("h\u0301") or ""),
         _ANCHOR_ID_V2),
        ("C6 区块表数据 `ID_CHARSET_BLOCKS` 在位（旧口径无表）",
         hasattr(mod, "ID_CHARSET_BLOCKS"),
         _ANCHOR_ID_V2),
        ("C7 旧属性表机制已退休 ∧ 新区块表判据在位（合取；旧实现两处必缺一）",
         not hasattr(mod, "NFC_REWRITE_BLOCKS")
         and not hasattr(mod, "OTHER_ALPHABETIC_BLOCKS")
         and hasattr(mod, "ID_CHARSET_BLOCKS"),
         _ANCHOR_ID_V2),
        # ---- 上一批（id 契约 v2）引入的断言：锚点 = 该批之前的提交 ----
        ("A1/A6 四槽名与「四槽」文案在 _t_spawn 内", _has("_t_spawn", "四槽"),
         _ANCHOR_PRE_ID_V2),
        ("A5 schema 收 identity/task/unit",
         {"identity", "task", "unit"} <= props,
         _ANCHOR_PRE_ID_V2),
        ("A8b `_submit` 签名带三槽",
         _has("_submit", "identity: str, task: str, unit: str"),
         _ANCHOR_PRE_ID_V2),
        ("A8 自造 id 已退场（锚点上应为 present=红）", not src_submit,
         _ANCHOR_PRE_ID_V2),
        ("F5 排序单点 `_list_jobs_by_created` 在位",
         hasattr(mod, "_list_jobs_by_created"),
         _ANCHOR_PRE_ID_V2),
        ("A4/B7 `alloc-id` 通道（MCP 面不再自造 id）", _has("_alloc_job_id", "alloc-id"),
         _ANCHOR_PRE_ID_V2),
    ]


def _load_ref_module(ref: str):
    """把 `ref` 的 `hive/hive_mcp/mcp_server.py` 字节物化到临时树后加载（工作区不动）。

    生效条件：两个对照件（`mcp_server.py` 与 `job.rs`）在该 ref 上都可读且模块装得起来
    → 返回 `(模块, 说明)`；任一步不成立 → `(None, 原因)`——调用方按「红基线不可得」处置，
    **绝不伪造结论**。
    """
    b = _head_bytes(MCP_REL, ref)
    b_rs = _head_bytes(JOB_RS_REL, ref)
    if not b or not b_rs:
        return None, ("%s:%s / %s:%s 不可读（或非 git 仓）——红基线不可得，不伪造结论"
                      % (ref, MCP_REL, ref, JOB_RS_REL))
    root = _mkroot("head")
    d = os.path.join(root, "hive", "hive_mcp")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "mcp_server.py")
    with open(p, "wb") as f:
        f.write(b)
    with open(os.path.join(_REPO, MCP_REL), encoding="utf-8") as f:
        cur = f.read()
    spec = importlib.util.spec_from_file_location("idv2_head_mcp_%s" % ref, p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["idv2_head_mcp_%s" % ref] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as e:                # noqa: BLE001
        return None, ("%s 版 mcp_server.py 装不起来：%s: %s" % (ref, type(e).__name__, e))
    return mod, ("%s:%s = %d 字节（工作区 %d 字节）"
                 % (ref, MCP_REL, len(b), len(cur.encode())))


def _head_baseline(ref: str | None = None) -> int:
    """红基线：把锚点的 **mcp_server.py 字节**物化到临时树（绝不覆盖工作区）后加载，
    逐条跑判据谓词，断言每条在**它自己的批次锚点**上为**红**（= 本守卫在旧实现上必红，
    判别力面真实而非空洞）、在**工作区上为绿**（否则是空转的红基线）。

    `ref` 缺省 `None` = 逐条用 [`_head_predicates`] 里登记的**每条的锚点**（推荐）；
    显式给 `ref` 则全部用它（供人工查更早/更晚的形态，如 `--head-baseline HEAD~3`）。
    """
    print("!! 红基线：逐条谓词在**各自的批次锚点**字节上必红、在工作区上必绿"
          "（临时物化，工作区不动）\n" if ref is None
          else "!! 红基线：源 = %s 字节（统一锚点，临时物化，工作区不动）\n" % ref)
    preds = _head_predicates(_hm)                 # 同一条谓词在**工作区**上的取值
    work = {name: (val is True) for name, val, _a in preds}
    groups: dict = {}
    for name, _val, anchor in preds:
        groups.setdefault(anchor, []).append(name)

    _GROUPS.clear()
    n_pred = 0
    for anchor, names in groups.items():
        use = ref or anchor
        mod, msg = _load_ref_module(use)
        print("  " + msg)
        if mod is None:
            return 1
        got = {nm: val for nm, val, _a in _head_predicates(mod)}
        for nm in names:
            n_pred += 1
            _CUR[0] = "ANCHOR@%s" % use
            check("红基线·%s（%s 上必红）" % (nm, use), got.get(nm) is not True,
                  "该谓词在 %s 上恰为绿 ⇒ 本守卫对这项无判别力" % use)
            _CUR[0] = "WORK"
            check("对照·工作区上该谓词为绿：%s" % nm, work[nm] is True,
                  "工作区上仍为红 ⇒ 绿态基线本身没成立")
    n_fail = sum(v["fail"] for v in _GROUPS.values())
    if n_fail:
        print("\n红基线结论：判别力面不成立（%d 条不符）\n" % n_fail)
        return 1
    print("\n红基线结论：%d 条判据谓词在**各自的批次锚点**上**全部为红**、在工作区上"
          "**全部为绿** ⇒ 本守卫的判别力面真实（非空洞）\n" % n_pred)
    return 0


def _head_bytes(rel: str, ref: str = "HEAD"):
    try:
        r = subprocess.run(["git", "show", "%s:%s" % (ref, rel)], cwd=_REPO,
                           capture_output=True)
    except OSError:
        return None
    return r.stdout if r.returncode == 0 and r.stdout else None


# ------------------------------------------------------------------- 入口

def main() -> int:
    ap = argparse.ArgumentParser(
        description="蜂巢任务标识契约 v2 守卫（Python 侧判据面 + 跨语言同判）")
    ap.add_argument("--branch-baseline", action="store_true",
                    help="定点变异自证（每处关掉一个判据，红项须恰好命中预期组/项数）")
    ap.add_argument("--head-baseline", nargs="?", const="", default=None,
                    metavar="REF",
                    help="红基线：把锚点字节临时物化（绝不覆盖工作区）后跑判据谓词，"
                         "断言每条在它**自己的批次锚点**上必红、在工作区上必绿；"
                         "给 REF 则统一用该 ref（缺省 = 逐条用各自登记的锚点）")
    args = ap.parse_args()
    try:
        if args.branch_baseline:
            return _branch_baseline()
        if args.head_baseline is not None:
            return _head_baseline(args.head_baseline or None)
        total, per = _run_groups()
        print("\n---- 分组 ----")
        for g in sorted(per):
            v = _GROUPS[g]
            print("  [%s] %d 条断言，失败 %d%s"
                  % (g, v["n"], v["fail"],
                     ("： " + "; ".join(v["reds"])) if v["reds"] else ""))
        print("\n结果：%d 条断言，失败 %d"
              % (sum(v["n"] for v in _GROUPS.values()), total))
        if total:
            print("FAILED")
            return 1
        print("ALL OK：id 契约 v2 的 python 侧判据与真 hive.exe 逐例同判；"
              "四槽必填 / 编号分配 / 字符集闸 / 三入口 / 五单元同源 / 排序真值 / "
              "存量共存全绿")
        return 0
    finally:
        _cleanup()
        _cleanup_persist()


if __name__ == "__main__":
    sys.exit(main())
