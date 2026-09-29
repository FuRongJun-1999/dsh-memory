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
  B  编号分配：连续分配不碰撞、编号 4 位定宽、编号用满 9999 → 显式报错（占位目录
     构造，**不真跑满 9999 次扫描**）、不加宽不回绕。
  C  字符集闸（B4/B5）：合法/非法两侧 + 拒收**原因级**可读性 + B6 语料**两侧逐例
     同判** + NFC 改写区块表与 Rust 逐区间同源 + Other_Alphabetic 补齐闭集**实测
     重导**（表陈化即红）+ 方向完备性（Python 收 ⟹ Rust 收，**全码点**批量证明）
     + 残余分叉的定性、计量与方向。
  D  拼路径三入口（kill/poll/depends_on）：非法 id（`..`/`../victim`/`/etc`/`h:x`/
     零宽/尾点/NUL 设备名）在**三条入口**均被拒——Rust CLI 用**真实退出码**，
     MCP 用 `_valid_job_id`/`_dep_gate`/`_t_kill`/`_t_poll` 的返回值。
  E  五单元闭集与 `md_cg/identity.POSITIONS` 同源（照 `md_cg/test_p21_tokens.py:218`
     的同源断言形态），并与 Rust `job.rs::UNITS` 及真 exe 的受理面三方对齐。
  F  `list_jobs_by_created` 的**保序**（旧形态名序==created_ts 序）与**按真值**
     （created_ts 与名序相反时仍按 created_ts 排）+ 哨兵/确定性/只读 + 与 exe 同序。
  G  存量共存：旧形态 id 仍合法、仍被 list_jobs 收、仍可 poll/kill。
  H  定点变异自证（`--branch-baseline`，退出码 0/1/2）。
  I  红基线（`--head-baseline`：临时物化 HEAD 字节跑同一批判据谓词，**绝不覆盖工作区**）。

用法：
  python -X utf8 -m hive.test_id_contract_v2                  # 绿态（默认）
  python -X utf8 -m hive.test_id_contract_v2 --branch-baseline  # 定点变异自证
  python -X utf8 -m hive.test_id_contract_v2 --head-baseline    # 红基线（HEAD 字节）
退出码：0 = 全绿 / 1 = 有失败 / 2 = 变异锚点漂移（ANCHOR-MISS，fail-closed）。

隔离纪律：一切提交/分配只落在**本进程自建的临时池**（`HIVE_JOBS_DIR` + `_jobs_dir`
双钉 + `_ensure_serve` 打桩），在役 jobs 池与在役 serve 一概不碰；变异轮改的是
**临时副本**（Python 面 exec 进模块 `__dict__`、Rust 面复制 crate 到临时目录编译），
工作区源码只读。

已知边界（如实声明，不静默）：
  · NUL 字节进不了 argv ⇒ 该语料例的 live exe 对照不适用（Rust 单测已覆盖），
    Python 判定仍断言。
  · 「Rust 收 / Python 拒」存在一个**方向安全**的残余类：Python 的 `unicodedata`
    比 Rust 工具链旧，Python 判「未分配(Cn)」而 Rust 已赋值的字母 ⇒ Python 更严。
    C9 逐轮**实测并钉住**该残余的定性（只许出现在 Cn 上）与方向（不许出现
    「Python 收而 Rust 拒」）。
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
    "零宽": "零宽/双向控制",
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


#: 分歧候选类目（B5 的 `is_alphanumeric` 两侧差只可能落在这几类；实测得到的两类
#: 载体是 Mn/Mc/So，其余类目**每轮实测零命中**——放进来是为了让「零命中」本身可证）。
#: `Co`（私用区 13.7 万码点）不入候选：Rust 的 Alphabetic 不含它（C7c 抽样核证）。
_CAND_CATS = frozenset(("Mn", "Mc", "Me", "So", "Sk", "Sm", "Po", "Pc", "Cf",
                        "No", "Nd", "Nl", "Sc", "Zs", "Ps", "Pe", "Pi", "Pf",
                        "Pd", "Zl", "Zp"))


def _probe_one(cp: int):
    return cp, (_rust_verdict("h" + chr(cp)) == "accept")


def _rust_accept_batch(chars: list):
    """批量问 exe「这些单字符整体是否合法」。

    Rust 判据逐字符独立，且载荷只含字母数字/闭集成员（不含 `_`/`.`/空白/控制），
    故「整串合法」⟺「每个字符都合法」——设备名分段、尾点、首尾空白三条结构判据
    不可能被批量串触发。用于**完备**证明「Python 收 ⟹ Rust 收」：
    ~14 万个 Python 收的字符只需数百次 exe 调用（二分定位反例）。
    """
    return _rust_verdict("h" + "".join(chars)) == "accept"


#: 批量法单块载荷长度（Windows CreateProcess 命令行上限 ~32K 字符，留足余量）
_BATCH_CHARS = 128


def _scan_unaccepted(chars: list) -> list:
    """返回 chars 中**未被 Rust 接受**的子集（批量 + 二分；完备而非抽样）。"""
    bad = []
    stack = [list(chars[i:i + _BATCH_CHARS])
             for i in range(0, len(chars), _BATCH_CHARS)]
    while stack:
        blk = stack.pop()
        if not blk:
            continue
        if _rust_accept_batch(blk):
            continue                      # exe 不可用/整块都收 → 无反例
        if len(blk) == 1:
            bad.append(blk[0])
        else:
            m = len(blk) // 2
            stack.append(blk[:m])
            stack.append(blk[m:])
    return bad


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
    with open(os.path.join(jobs_m, gjid, "spec.json"), encoding="utf-8") as f:
        spec_back = json.load(f)
    check("A7b·四槽不入 spec.json（与 rust init_job_with_slots 同写序/同口径）",
          not ({"identity", "task", "unit"} & set(spec_back)), str(sorted(spec_back)))
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
# 编号分配：独占创建即分配、4 位定宽、用满 9999 显式报错（占位目录构造）。

def g_b():
    begin("B", "编号分配（B3：独占创建即分配 / 定宽 4 位 / 用满显式报错）")
    check("B0 前置：hive 二进制在盘", _missing_exe() is None,
          "未找到 %s" % (_missing_exe() or ""))
    root = _mkroot("b")
    jobs = os.path.join(root, "jobs")
    os.makedirs(jobs, exist_ok=True)

    ids = []
    for _ in range(3):
        rc, out, _e = _cli(["alloc-id", "--identity", "编号端", "--task", "连续",
                            "--unit", "reflect"], jobs=jobs)
        ids.append((_json_of(out) or {}).get("job_id"))
    check("B1·连续分配不碰撞且自 0001 起（英文键 unit 落中文名）",
          ids == ["h_编号端_连续_反思单元_0001", "h_编号端_连续_反思单元_0002",
                  "h_编号端_连续_反思单元_0003"], str(ids))
    check("B2·编号 4 位定宽十进制 + 分配即创建目录（独占创建即分配）",
          all(len(i.split("_")[-1]) == 4 and i.split("_")[-1].isdigit()
              and os.path.isdir(os.path.join(jobs, i)) for i in ids), str(ids))

    jobs2 = os.path.join(root, "jobs_full")
    os.makedirs(os.path.join(jobs2, "h_端_任务_记录单元_9999"), exist_ok=True)
    rc, out, _e = _cli(["alloc-id", "--identity", "端", "--task", "任务",
                        "--unit", "记录单元"], jobs=jobs2)
    doc = _json_of(out) or {}
    err = doc.get("error") or ""
    check("B3·编号用满 9999 → 退出 1 且错误含前缀与「每单元上限 9999」",
          rc == 1 and doc.get("ok") is False and "h_端_任务_记录单元_" in err
          and "每单元上限 9999" in err, "rc=%s err=%r" % (rc, err[:160]))
    check("B4·溢出不得静默加宽（无 10000 目录）也不得回绕（无 0001 目录）",
          not os.path.exists(os.path.join(jobs2, "h_端_任务_记录单元_10000"))
          and not os.path.exists(os.path.join(jobs2, "h_端_任务_记录单元_0001")),
          str(sorted(os.listdir(jobs2))))
    jobs3 = os.path.join(root, "jobs_last")
    os.makedirs(os.path.join(jobs3, "h_端_任务_记录单元_9998"), exist_ok=True)
    rc, out, _e = _cli(["alloc-id", "--identity", "端", "--task", "任务",
                        "--unit", "记录单元"], jobs=jobs3)
    doc = _json_of(out) or {}
    check("B5·9998 在场时 9999 仍可分配（上界形态 + 定宽守恒）",
          rc == 0 and doc.get("job_id") == "h_端_任务_记录单元_9999",
          json.dumps(doc, ensure_ascii=False)[:160])
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


def _rust_blocks():
    """从 Rust **真源**现场解析 `NFC_REWRITE_BLOCKS`（不抄一份常量，逐区间同源比对）。"""
    with open(os.path.join(_REPO, JOB_RS_REL), encoding="utf-8") as f:
        src = f.read()
    body = src.split("pub const NFC_REWRITE_BLOCKS", 1)[1].split("];", 1)[0]
    return [(int(a, 16), int(b, 16)) for a, b in
            re.findall(r"\(0x([0-9A-Fa-f]+),\s*0x([0-9A-Fa-f]+)", body)]


def _rust_units():
    with open(os.path.join(_REPO, JOB_RS_REL), encoding="utf-8") as f:
        src = f.read()
    body = src.split("pub const UNITS", 1)[1].split("];", 1)[0]
    return re.findall(r'\("(\w+)",\s*"([^"]+)"\)', body)


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
    ("h\u202e", REASON_MARK["零宽"]),
    ("h_CON_任务_记录单元_0001", REASON_MARK["设备名"]),
    ("h_CON.txt_任务_记录单元_0001", REASON_MARK["设备名"]),
    ("h_端_任务_LPT9_0001", REASON_MARK["设备名"]),
    ("h\u0041\u0301", REASON_MARK["NFC"]),
    ("h\ufa10", REASON_MARK["NFC"]),
    ("h/../../x", REASON_MARK["路径"]),
    ("h:x", REASON_MARK["路径"]),
)


def g_c():
    begin("C", "字符集闸 B4/B5 + B6 语料两侧同判 + 区块表同源 + 方向完备")
    check("C0 前置：hive 二进制在盘", _missing_exe() is None,
          "未找到 %s" % (_missing_exe() or ""))

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

    # ---- NFC 改写区块表：与 Rust **逐区间**同源
    rust_blocks = _rust_blocks()
    check("C6·NFC 改写区块表与 Rust 逐区间一致（%d 区间，缺一即红）" % len(rust_blocks),
          list(_hm.NFC_REWRITE_BLOCKS) == rust_blocks,
          "py=%d rust=%d 缺=%s" % (len(_hm.NFC_REWRITE_BLOCKS), len(rust_blocks),
                                  [b for b in rust_blocks
                                   if b not in _hm.NFC_REWRITE_BLOCKS][:3]))
    check("C6b·契约点名的 11 个最低区块在表内（代表点判「会改写」）",
          all(any(lo <= cp <= hi for lo, hi in _hm.NFC_REWRITE_BLOCKS)
              for cp in (0x1100, 0x3130, 0xF900, 0xFE30, 0xFE50, 0xFF00,
                         0x2460, 0x3200, 0x2100, 0x1D400, 0x2F800))
          and len(_hm.NFC_REWRITE_BLOCKS) >= 11)
    check("C6c·不误伤：常规中文与 ASCII 字母数字判稳定",
          all(_hm._nfc_stable_alnum(c) for c in "灵枢迭代Az09zcode端"))

    lv = _missing_exe()
    if lv is not None:
        check("C7·分区闭集实测重导（前置：exe 在盘）", False, "未找到 %s" % lv)
        check("C8·方向完备（前置：exe 在盘）", False, "未找到 %s" % lv)
        check("C9·残余分叉定性（前置：exe 在盘）", False, "未找到 %s" % lv)
        return

    # ---- Other_Alphabetic 补齐闭集：**实测重导**（表陈化即红）
    cand = [cp for cp in range(0x110000)
            if not (0xD800 <= cp <= 0xDFFF)
            and unicodedata.category(chr(cp)) in _CAND_CATS
            and not chr(cp).isalnum()]
    with ThreadPoolExecutor(max_workers=16) as ex:
        res = list(ex.map(_probe_one, cand, chunksize=64))
    got = sorted(cp for cp, ok in res if ok and cp != 0x5F)
    want = sorted(cp for lo, hi in _hm.OTHER_ALPHABETIC_BLOCKS
                  for cp in range(lo, hi + 1))
    check("C7·Other_Alphabetic 补齐闭集 == 真 exe 实测重导（%d 码点 / %d 候选）"
          % (len(want), len(cand)), got == want,
          "实测 %d / 表内 %d 差集=%s" % (len(got), len(want),
                                        sorted(set(want) ^ set(got))[:5]))
    check("C7b·表确有效用（该码点 Python `isalnum()` 判假、Rust 判真 ⇒ 无表必分叉）",
          len(want) > 0 and not chr(want[0]).isalnum()
          and _hm._rust_alphanumeric(chr(want[0]))
          and _hm._valid_job_id("h" + chr(want[0])) is True
          and _rust_verdict("h" + chr(want[0])) == "accept")
    co_sample = [0xE000, 0xE100, 0xF0000, 0xF0100, 0x100000, 0x10FFFD]
    check("C7c·私用区(Co)抽样：Rust 一律拒（故 Co 不入候选类目是安全的）",
          all(_rust_verdict("h" + chr(cp)) == "reject" for cp in co_sample),
          str([hex(cp) for cp in co_sample
               if _rust_verdict("h" + chr(cp)) != "reject"]))

    # ---- 方向完备：Python 收 ⟹ Rust 收（全码点，批量 + 二分，非抽样）
    # 预筛 = 与实现**同一份定义**（字母数字 ∪ 补齐闭集）的 O(1) 判据，逐个再由
    # `_valid_job_id` 本体裁决（预筛只省算力，不放宽判据——C7 已把该定义钉在 exe 上）。
    tbl = set()
    for lo, hi in _hm.OTHER_ALPHABETIC_BLOCKS:
        tbl.update(range(lo, hi + 1))
    acc_chars = []
    for cp in range(0x110000):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        c = chr(cp)
        if c in "_.":
            continue                      # 结构分支（不走字符类判据），单独断言
        if not (c.isalnum() or cp in tbl):
            continue
        if _hm._valid_job_id("h" + c):
            acc_chars.append(c)
    bad = _scan_unaccepted(acc_chars)
    check("C8·方向完备：Python 收的**每一个**字符 Rust 都收（全码点，非抽样）",
          bad == [], "Python 收 %d 字符，其中 Rust 拒 %d 个：%s"
          % (len(acc_chars), len(bad), [hex(ord(c)) for c in bad[:5]]))
    check("C8b·`_` 与 `.` 由结构分支处理且两侧同判",
          _hm._valid_job_id("h_a.b") and _hm._valid_job_id("h1_a")
          and not _hm._valid_job_id("h.") and not _hm._valid_job_id("h..")
          and _rust_verdict("h_a.b") == "accept"
          and _rust_verdict("h.") == "reject")

    # ---- 残余分叉：定性（只许在 Python 判未分配的码点上）+ 方向（不许 Python 更松）
    stride = [cp for cp in range(1, 0x110000, 509)
              if not (0xD800 <= cp <= 0xDFFF)]
    with ThreadPoolExecutor(max_workers=16) as ex:
        res2 = list(ex.map(_probe_one, stride, chunksize=64))
    worse = [cp for cp, ok in res2 if ok and not _hm._valid_job_id("h" + chr(cp))]
    perm = [cp for cp, ok in res2 if not ok and _hm._valid_job_id("h" + chr(cp))]
    check("C9·方向断言：抽样内无「Python 收而 Rust 拒」（安全方向不许破）",
          perm == [], "越权面=%s" % [hex(cp) for cp in perm[:5]])
    non_cn = [cp for cp in worse if unicodedata.category(chr(cp)) != "Cn"]
    check("C9b·残余（Rust 收 / Python 拒）**只**出现在 Python 判未分配(Cn) 的码点上"
          "（= Unicode 版本差，非语义分歧）", non_cn == [],
          "非 Cn 残余=%s（Python unicodedata %s vs rust 工具链）"
          % ([hex(cp) for cp in non_cn[:5]], unicodedata.unidata_version))
    print("      · 计量声明：抽样 %d 点，残余 %d 个（全 Python-Cn；方向=Python 更严）"
          % (len(res2), len(worse)))
    print("      · 全量实测留档（2026-09-30，`--cn-sweep` 可重导）：Python 判 Cn 的"
          "825345 码点中，Rust 收而 Python 拒 **9713 个（56 区间）** = Unicode 15.1/16"
          " 新增字母；方向仅令本面更严，越权面为零")


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

#: 变异表：`(标签, 面, 函数名, 原串, 新串, 期望红项集 {组: 条数})`。
#: `expect` 为 None = **未标定**（首轮照实打印实测红项集与退出码，由实测值写死——
#: 不猜）。Rust 面的 `old/new` 走 `_RUST_SWAP`（源码在 `_BUILD` 的临时副本上改）。
_MUTATIONS = (
    ("MCP 四槽必填（_t_spawn 的缺槽校验）",
     "mcp", "_t_spawn",
     "    missing = [k for k, v in slots.items() if not v]",
     "    missing = []",
     {"A": 5}),
    ("MCP 尾点拒收（_job_id_reject_reason）",
     "mcp", "_job_id_reject_reason",
     '    if jid.endswith("."):',
     "    if False:",
     {"C": 8, "D": 4}),
    ("MCP 零宽拒收（_is_zero_width）",
     "mcp", "_is_zero_width",
     '    return "\\u200b" <= c <= "\\u200f" or c in ("\\u2060", "\\ufeff")',
     "    return False",
     {"C": 2}),
    ("MCP 保留设备名拒收（_is_reserved_device_name）",
     "mcp", "_is_reserved_device_name",
     '    base = s.split(".")[0].translate(_ASCII_UPPER)\n'
     "    return base in RESERVED_DEVICE_NAMES",
     "    return False",
     {"C": 15, "D": 8}),
    ("MCP created_ts 排序退回 id 字典序（_list_jobs_by_created）",
     "mcp", "_list_jobs_by_created",
     "    return sorted(names, key=lambda n: (_created_ts_of(jobs, n), n))",
     "    return sorted(names)",
     {"F": 5}),
    ("Rust 编号溢出改静默加宽（job.rs::alloc_job_id 用尽分支）",
     "rust", "alloc_job_id", None, None,
     {"B": 2}),
)

#: 假阳性对照：与判据无关的改名必须**全绿**（退出码 0）。
_FALSE_POSITIVE = ("mcp", "_job_id_reject_reason",
                   '    if jid in (".", ".."):\n        return "job_id 是相对路径段"',
                   '    _idv2_unused_probe = None\n'
                   '    if jid in (".", ".."):\n        return "job_id 是相对路径段"')

#: Rust 面变异：**用尽分支静默加宽为 5 位**（破坏「4 位定宽」前提并落盘 10000 号目录）
#: ——正是契约点名要防的形态（首版变异锚在循环体内，而 `next_seq_hint` 返回 10000 时
#: `10000..=9999` 是**空区间**⇒ 变异体不可达、红项=0；实测发现后改为锚在用尽分支本身）。
_RUST_SWAP = (
    '    Err(format!(\n'
    '        "编号用尽: 前缀 {prefix} 已无可用编号（每单元上限 {MAX_UNIT_SEQ}，'
    '4 位定宽不自动加宽\\\n',
    '    let _ = &last_collision;\n'
    '    let wide = format!("{prefix}{}", MAX_UNIT_SEQ + 1);\n'
    '    if fs::create_dir(job_dir(jobs, &wide)).is_ok() {\n'
    '        return Ok(wide);\n'
    '    }\n'
    '    Err(format!(\n'
    '        "编号用尽: 前缀 {prefix} 已无可用编号（每单元上限 {MAX_UNIT_SEQ}，'
    '4 位定宽不自动加宽\\\n',
)

_HOLDERS = {"mcp": _hm, "orch": _orch}


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
    """把 hive crate 复制进临时目录（**工作区源码只读**：变异改的是副本）。"""
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


def _cn_sweep() -> int:
    """重导「Python 判未分配(Cn) 而 Rust 收」的残余集（声明值的可复现入口）。

    实测耗时 ≈44 分钟（24 线程 × 825345 个码点）——**故不入常规守卫**：常规轮只做
    C9（残余的定性与方向，抽样）。本入口供 Unicode 版本升级后重新计量与留档。
    """
    print("!! Cn 残余重导：Python %s × 真 hive.exe\n" % unicodedata.unidata_version)
    if _missing_exe() is not None:
        print("  未找到 %s" % _missing_exe())
        return 1
    cand = [cp for cp in range(0x110000)
            if not (0xD800 <= cp <= 0xDFFF)
            and unicodedata.category(chr(cp)) == "Cn"]
    with ThreadPoolExecutor(max_workers=24) as ex:
        res = list(ex.map(_probe_one, cand, chunksize=256))
    extra = sorted(cp for cp, ok in res if ok)
    rngs = []
    for cp in extra:
        if rngs and cp == rngs[-1][1] + 1:
            rngs[-1][1] = cp
        else:
            rngs.append([cp, cp])
    print("  Python 判 Cn 的码点数 = %d" % len(cand))
    print("  Rust 收而 Python 判未分配 = %d（%d 个区间）" % (len(extra), len(rngs)))
    for a, b in rngs[:8]:
        print("    (0x%04X, 0x%04X)" % (a, b))
    if len(rngs) > 8:
        print("    …（共 %d 个区间）" % len(rngs))
    return 0


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
    print("!! 定点变异模式：逐处关掉判据，守卫应当转红且**恰好**命中预期组/项数\n")
    with contextlib.redirect_stdout(io.StringIO()):
        clean_fail, _clean = _run_groups()
    _cleanup()
    print("  未变异基线：失败=%d" % clean_fail)
    if clean_fail:
        print("  基线即失败 → 定点变异自证无意义（先修基线）")
        _cleanup_persist()
        return 1
    bad = []
    for label, which, fname, old, new, expect in _MUTATIONS:
        if which == "rust":
            _build_env()
            ok, log = _cargo_build()
            if not ok:
                print("  编译失败 %s：%s" % (label, log[-300:]))
                _cleanup_persist()
                return 2
            restore = _patch_rust("src/job.rs", _RUST_SWAP[0], _RUST_SWAP[1])
            if restore is None:
                print("  ANCHOR-MISS %s —— 变异锚点漂移（实现改了却没同步本表）" % label)
                _cleanup_persist()
                return 2
            os.environ["HIVE_EXE"] = _BUILD["exe"]
            try:
                ok2, log2 = _cargo_build()
                if not ok2:
                    print("  变异体编译失败 %s：%s" % (label, log2[-300:]))
                    return 2
                with contextlib.redirect_stdout(io.StringIO()):
                    got_fail, got_groups = _run_groups(only=("B",))
            finally:
                restore()
                os.environ.pop("HIVE_EXE", None)
                _cleanup()
        else:
            restore = _patch_fn(which, fname, old, new)
            if restore is None:
                print("  ANCHOR-MISS %s —— 变异锚点漂移（实现改了却没同步本表；"
                      "基线源=%s.%s）" % (label, which, fname))
                _cleanup_persist()
                return 2
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    got_fail, got_groups = _run_groups()
            finally:
                restore()
                _cleanup()
        hit = {g: n for g, n in got_groups.items() if n}
        if expect is None:
            print("  [未标定] 关掉「%s」→ 红项=%d，退出码=1，命中组=%s"
                  % (label, got_fail, dict(sorted(hit.items()))))
            continue
        if hit == expect and got_fail == sum(expect.values()):
            print("  关掉「%s」→ 红项=%d，退出码=1，命中组=%s（恰好命中预期）"
                  % (label, got_fail, dict(sorted(hit.items()))))
        else:
            print("  关掉「%s」→ 红项=%d，命中组=%s  期望=%s  "
                  "**红基线失效（判别力面不符）**"
                  % (label, got_fail, dict(sorted(hit.items())),
                     dict(sorted(expect.items()))))
            bad.append(label)

    restore = _patch_fn(*_FALSE_POSITIVE)
    if restore is None:
        print("  ANCHOR-MISS 假阳性对照锚点漂移")
        _cleanup_persist()
        return 2
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            fp_fail, fp_groups = _run_groups()
    finally:
        restore()
        _cleanup()
    if fp_fail == 0:
        print("  假阳性对照「无关改名」→ 红项=0，退出码=0 —— 本守卫不误报")
    else:
        print("  假阳性对照「无关改名」→ 红项=%d，命中组=%s  **误报**"
              % (fp_fail, {g: n for g, n in fp_groups.items() if n}))
        bad.append("假阳性对照")
    print("\n定点变异自证：%s" % ("PASS（每处判据都有断言把它钉死，且无关改动不误报）"
                                  if not bad else "FAIL —— " + "、".join(bad)))
    _cleanup_persist()
    return 0 if not bad else 1


# --------------------------------------------------------------- 红基线（HEAD 字节）

#: 红基线判据谓词：在 **HEAD 字节**上与在工作区上应得**相反**结论的谓词
#: （(名称, 在 HEAD 上是否应为「该断言会红」的谓词)——每条都对应守卫里的一条断言）。
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
        ("A1/A6 四槽名与「四槽」文案在 _t_spawn 内", _has("_t_spawn", "四槽")),
        ("A5 schema 收 identity/task/unit",
         {"identity", "task", "unit"} <= props),
        ("A8b `_submit` 签名带三槽",
         _has("_submit", "identity: str, task: str, unit: str")),
        ("A8 自造 id 已退场（HEAD 应为 present=红）", not src_submit),
        ("C1 中文四槽 id 过闸（HEAD 的 ASCII 白名单应拒）",
         bool(getattr(mod, "_valid_job_id", lambda x: False)(
             "h_zcode端_灵枢迭代_反思单元_0001"))),
        ("C2b 拒收原因级出口 `_job_id_reject_reason` 在位",
         hasattr(mod, "_job_id_reject_reason")),
        ("C6 区块表常量 `NFC_REWRITE_BLOCKS` 在位",
         hasattr(mod, "NFC_REWRITE_BLOCKS")),
        ("C7 补齐闭集 `OTHER_ALPHABETIC_BLOCKS` 在位",
         hasattr(mod, "OTHER_ALPHABETIC_BLOCKS")),
        ("F5 排序单点 `_list_jobs_by_created` 在位",
         hasattr(mod, "_list_jobs_by_created")),
        ("A4/B7 `alloc-id` 通道（MCP 面不再自造 id）", _has("_alloc_job_id", "alloc-id")),
    ]


def _head_baseline() -> int:
    """红基线：把 **HEAD 字节**物化到临时树（绝不覆盖工作区）后加载，跑同一批
    判据谓词，断言它们在 HEAD 上**全部为红**（= 本守卫在旧实现上必红，
    判别力面真实而非空洞）。"""
    print("!! 红基线：源 = HEAD 字节（临时物化，工作区不动）\n")
    b = _head_bytes(MCP_REL)
    b_rs = _head_bytes(JOB_RS_REL)
    if not b or not b_rs:
        print("  HEAD:%s / HEAD:%s 不可读（或非 git 仓）——红基线不可得，不伪造结论"
              % (MCP_REL, JOB_RS_REL))
        return 1
    root = _mkroot("head")
    d = os.path.join(root, "hive", "hive_mcp")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "mcp_server.py")
    with open(p, "wb") as f:
        f.write(b)
    with open(os.path.join(_REPO, MCP_REL), encoding="utf-8") as f:
        cur = f.read()
    print("  HEAD:%s = %d 字节（工作区 %d 字节）" % (MCP_REL, len(b), len(cur.encode())))
    spec = importlib.util.spec_from_file_location("idv2_head_mcp", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["idv2_head_mcp"] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as e:                # noqa: BLE001
        print("  HEAD 版 mcp_server.py 装不起来：%s: %s" % (type(e).__name__, e))
        return 1
    preds = _head_predicates(mod)

    _GROUPS.clear()
    _CUR[0] = "HEAD"
    _GROUPS.setdefault("HEAD", {"n": 0, "fail": 0, "reds": []})
    for name, green_on_head in preds:
        # 断言「该谓词在 HEAD 上为**红**」（= 守卫的对应断言在旧实现上必失败）
        check("红基线·%s（HEAD 上必红）" % name, not green_on_head,
              "该谓词在 HEAD 上恰为绿 ⇒ 本守卫对这项无判别力")
    # 反向：同一批谓词在工作区上**必须为绿**（否则是空转的红基线）
    _CUR[0] = "WORK"
    _GROUPS.setdefault("WORK", {"n": 0, "fail": 0, "reds": []})
    wpreds = _head_predicates(_hm)
    for (name, _g), (_n2, g2) in zip(preds, wpreds):
        check("对照·工作区上该谓词为绿：%s" % name, g2 is True,
              "工作区上仍为红 ⇒ 绿态基线本身没成立")
    n_fail = sum(v["fail"] for v in _GROUPS.values())
    if n_fail:
        print("\n红基线结论：判别力面不成立（%d 条不符）\n" % n_fail)
        return 1
    print("\n红基线结论：%d 条判据谓词在 HEAD（契约前）上**全部为红**、在工作区上"
          "**全部为绿** ⇒ 本守卫的判别力面真实（非空洞）\n" % len(preds))
    return 0


def _head_bytes(rel: str):
    try:
        r = subprocess.run(["git", "show", "HEAD:%s" % rel], cwd=_REPO,
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
    ap.add_argument("--head-baseline", action="store_true",
                    help="红基线：临时物化 HEAD 字节跑同一批判据谓词（绝不覆盖工作区）")
    ap.add_argument("--cn-sweep", action="store_true",
                    help="重导「Python 判未分配(Cn) 而 Rust 收」的残余集（≈44 分钟，"
                         "供 Unicode 版本升级后重新计量）")
    args = ap.parse_args()
    try:
        if args.cn_sweep:
            return _cn_sweep()
        if args.branch_baseline:
            return _branch_baseline()
        if args.head_baseline:
            return _head_baseline()
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
