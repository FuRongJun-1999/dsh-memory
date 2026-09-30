# -*- coding: utf-8 -*-
"""md_cg · B4 守卫：索引分片目录不自愈（长驻进程内 `_index_log/` 被删后
append 永抛 `FileNotFoundError`，且永不恢复）

缺陷（修复前，本守卫红态实抓：`probe_b4.py` 探针 + 本文件 A 组）
``ShardedLog`` 只在 ``__init__`` 里 ``makedirs(self.dir)``；``append`` 首次
``open(self.path, "a")`` 前**不复查目录**。生产形态是长驻进程（``MdCGSecure(
root, principal, autoflush=1)``，``MdCG.flush`` 每批写完整批 ``close()`` 分片
句柄 ⇒ 下次 append 必经重开），于是：

  · 进程内存活期间 ``_index_log/`` 被删（外部清理脚本 / 误删 / 备份还原）后，
    此后**每次** append 都在 ``open`` 处抛 ``FileNotFoundError [Errno 2]``；
  · 目录三次都不重建、``close()`` 抛同一异常、``_index.json`` 从未落成；
  · 正文 ``.md`` 已落盘（``mdcg.py`` 先写盘再标脏索引）而索引未更新——
    索引静默落后于盘面，且**无任何失败信号以外的可观测痕迹**。

实测（2026-09-30，沙箱临时根，非在役库）：
  · 修前：``add#2/#3/#4`` 三连抛 ``FileNotFoundError``，崩点 ``fsutil.py`` 的
    ``open``（原 564 行）；``read_all`` 返回 ``[]``；``close()`` 抛同异常；
    ``_index.json`` 不存在。
  · 不自愈的必要条件是「**本进程已持有 ShardedLog 实例**」：``md_cg/mdcg.py``
    仅在 ``self._log is None`` 时建实例；全新短命进程做同一操作时
    ``__init__`` 的 makedirs 生效、目录会被重建（反证，探针 P-4 已给）。

修复口径（**单点**：`fsutil.ensure_shard_dir` 是分片目录存在性的唯一实现，
``ShardedLog.__init__`` 与 ``ShardedLog.append`` 两处调用点都是委托、不做副本）：
  ① ``append`` 首次打开分片前确保 ``self.dir`` 存在——缺失即重建，**路径照常**
     （仍是 ``self.path``，同一分片名，只补回目录这一层）。
  ② **容忍 ≠ 静默**（本仓 N225 已确立的判据）：重建成功要可观测——模块级计数
     ``SHARD_DIR_REBUILDS`` + 有界样本 + stderr 汇总告警；**首建不记账**
     （``where="init"`` = 建库时目录本就不存在，那是正常路径；计入会淹没真事件）。
  ③ 重建**失败**（父目录只读 / 权限不足 / 有文件占着该路径）抛结构化
     ``ShardDirError``：可机读 ``code=E_SHARD_DIR_UNREBUILDABLE`` + 可操作
     ``hint`` + ``path``，且**仍是 ``OSError`` 子类**（既有 ``except OSError``
     面的语义不漂移）；失败**同样记账 + 告警**——异常可能被上层兜底吞掉
     （``MdCG.close`` 的 ``except (OSError, ValueError)``），痕迹不得只存在于
     异常里。
  ④ ``read_all`` 既有语义**一字不改**：directory 不是目录 → 返回 ``[]``。

守卫构成（A 自愈面 / B 边界与既有语义 / C 重建失败的结构化 / D 生产链 /
E MCP 出口端到端）：
  A 6 条：删目录后 append 不抛 · 目录真被重建 · 删除后的记录真落进分片 ·
    记账可断言（次数 + 样本）· stderr 告警可观测 · **路径照常**（分片名不换）
  B 5 条：read_all 缺目录 → ``[]`` 不抛（要求④）· read_all 路径是文件 → ``[]``
    不抛 · 首建不记账（计数 0 + stderr 干净）· 目录在位时零记账零告警（不产生
    噪声）· clear 缺目录 → 直接返回不抛（既有语义）
  C 9 条（有文件占着分片目录路径 ⇒ 重建必失败）：抛 ``ShardDirError`` 而非裸
    ``FileNotFoundError`` · 仍是 ``OSError`` 子类 · ``code`` 可机读 · message
    首字段含 ``[code]``（出口串里可机读）· ``hint`` 非空且含目录与处置 ·
    ``path`` 属性 · 失败也记账 · 失败也告警 · **打开面同口径**（append 重建失败
    也抛同一结构化错误、``where=append`` 记账）
  D 5 条（长驻 ``MdCG`` 实例，autoflush=1）：删 ``_index_log`` 后再 add 不抛 ·
    节点索引可见且盘面 ``.md`` 一致 · 分片日志可重放（索引不落后于盘面）·
    生产链自愈也记账 · 生产链自愈也告警
  E 4 条（`python -X utf8 -m md_cg.mcp_server` stdio 主循环 + 文件占住
    ``_index_log``）：MCP 出口的 error 串含 ``E_SHARD_DIR_UNREBUILDABLE``（不是
    裸 ``FileNotFoundError``）· 同一应答带可操作 ``hint`` · 错误之后进程仍应答
    且 shutdown 后 rc=0 · 变异轮**注入自证**在场（fail-closed：注入失效不得被
    读成「端到端面无判别力」）

``--branch-baseline`` 定点变异自证（与 ``test_n225_nonobject_load`` 同口径）：
逐个关掉一处判据，守卫**必须转红**且红项**恰好**落在该判据负责的组、数量等于
表内预期；锚点漂移报 ``ANCHOR-MISS`` 并以**退出码 2** fail-closed 停手；基线源
是**工作区源码**（``inspect.getsource`` 取自当前已加载模块），绝不绑 git HEAD。
``--drop-fix`` 是「抽掉修复本体」的定点自证：只施加 M1（append 前不复查目录），
逐个打印转红的断言名与红项数，恢复后重跑并打印绿项数——「红→恢复→绿」三态
原样可见。

**并行编辑边界（如实）**：D/E 组依赖 ``md_cg`` 包内 ``MdCG``/``mcp_server`` 在
树内**完整可用**；本轮是多分片并行修改同一工作区，若 ``mdcg.py`` 正处于中间态
（类体被插断 ⇒ ``MdCG`` 缺 ``_write_node``），D/E 会整组红——那是**真红**（树
确实不可用），不是守卫自身的判别力问题；此时按「HEAD 基线树 + 本处 delta」的
隔离镜像跑本文件（见 FixReport）。

隔离纪律（与 ``test_n225_nonobject_load`` / ``test_n206_stdio_jsonrpc_type``
同款）：env 剔净全部 MDCG_*/HIVE_* 注入面，只注入指向临时目录的
``MDCG_ROOT``/``MDCG_AUX_ROOT``/``MDCG_STATE_ROOT``/``MDCG_DATA_ROOT``/
``MDCG_TENANT_REGISTRY``（指向不存在的临时路径=空表回落）/``MDCG_SUSTAIN=0``/
``MDCG_LEGACY_ENV_AUTH=1``；全部合成库落在 ``tempfile.mkdtemp`` 下，跑完 rmtree。
**绝不触在役活库、真实令牌库与真实 serve。**

运行：
  python -X utf8 -m md_cg.test_b4_shard_dir_selfheal
  python -X utf8 -m md_cg.test_b4_shard_dir_selfheal --branch-baseline
  python -X utf8 -m md_cg.test_b4_shard_dir_selfheal --drop-fix
"""
from __future__ import annotations

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
from contextlib import redirect_stderr

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from . import fsutil as F              # noqa: E402

PASS, FAIL = 0, 0
FAILS = []
_CURRENT = ["?"]
_GROUP_FAILS = {}
_TMP_ROOTS = []
_LIVE = []

# 六要素正文（写入闸要求的 text 形态；D/E 组的写入用它）
BODY = ("# 功能名：B4 守卫合成节点\n# 生效条件：守卫运行期间\n# 子功能：占位\n"
        "# 执行：占位\n# 验证方式：test\n# 不适用条件：非守卫运行")


# 生效条件：把 PASS/FAIL/失败名单/分组失败数全部清零并解除当前组名（每次完整跑套件前调用；--branch-baseline 每个变异轮都要一次干净基线）。
def _reset_counters():
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    _GROUP_FAILS.clear()
    _CURRENT[0] = "?"


# 生效条件：group 为非空字符串时设为当前组名并在 _GROUP_FAILS 里开出该组条目（未开则记 0）；重复调用同名组只是切换当前组，不清零已有计数。
def begin(group: str):
    _CURRENT[0] = group
    _GROUP_FAILS.setdefault(group, 0)


# 生效条件：cond 为真记一条通过并打印；为假把 FAIL 与当前组失败数各 +1、把 name 追加进 FAILS 并打印 detail（detail 为空则只打印名字）。
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [ok] %s" % name)
        return True
    FAIL += 1
    _GROUP_FAILS[_CURRENT[0]] = _GROUP_FAILS.get(_CURRENT[0], 0) + 1
    FAILS.append(name)
    print("  [FAIL] %s  %s" % (name, detail))
    return False


# 生效条件：fn 为无参回调时调用它取条件值——回调抛异常即判红并把异常类型与消息写进 detail（**不中断整组**，保证「变异下红项数 == 该组断言数」这一精确口径成立）；fn 正常返回则按返回值真假记账；detail 传 callable 时在同一保护下求值。
def check_fn(name, fn, detail=""):
    if callable(detail):
        try:
            detail = detail()
        except Exception as exc:          # noqa: BLE001
            detail = "detail 求值抛 %s: %s" % (type(exc).__name__, exc)
    try:
        cond = bool(fn())
        extra = detail
    except Exception as exc:              # noqa: BLE001 —— 红态正是抛异常
        cond = False
        extra = "回调抛 %s: %s（%s）" % (type(exc).__name__, exc, detail)
    return check(name, cond, extra)


# 生效条件：新建系统临时目录（prefix 前缀）并把路径登记进 _TMP_ROOTS，供本次运行收尾统一 rmtree；返回该路径。
def _tmpdir(prefix: str) -> str:
    p = tempfile.mkdtemp(prefix=prefix)
    _TMP_ROOTS.append(p)
    return p


# 生效条件：无入参，对 _TMP_ROOTS 里每个目录 rmtree(ignore_errors=True) 并清空清单、对 _LIVE 里每个认知图实例尝试 close()（异常吞掉，收尾不该再抛）；收尾是幂等的。
def _cleanup():
    for cg in _LIVE:
        try:
            cg.close()
        except Exception:                 # noqa: BLE001 —— 收尾路径不再抛
            pass
    del _LIVE[:]
    for p in _TMP_ROOTS:
        shutil.rmtree(p, ignore_errors=True)
    del _TMP_ROOTS[:]


# ---------------- A/B/C 组 fixture（只碰 fsutil，不依赖 mdcg） ----------------

# 生效条件：无入参时在临时目录建一个分片实例写入 a0、close（生产写点每批写完即 close 句柄）→ 记录分片名 → 重置记账 → rmtree 分片目录 → 以 redirect_stderr 捕获告警后追加 a1、close、追加 a2、close；返回上下文 dict（d / base / stats / stderr / err / ids / files / dir_after）。
def _case_heal() -> dict:
    tmp = _tmpdir("mdcg_b4_heal_")
    d = os.path.join(tmp, "_index_log")
    ctx = {"d": d, "base": None, "stats": None, "stderr": "", "err": None,
           "ids": None, "files": None, "dir_after": None, "err0": None}
    lg = None
    try:
        lg = F.ShardedLog(d)
        lg.append({"id": "a0"})
        lg.close()
        ctx["base"] = os.path.basename(lg.path)
        F.reset_shard_dir_stats()
        shutil.rmtree(d)
        buf = io.StringIO()
        try:
            with redirect_stderr(buf):
                lg.append({"id": "a1"})
                lg.close()
                lg.append({"id": "a2"})
                lg.close()
        except Exception as exc:          # noqa: BLE001 —— 修前此处即红
            ctx["err"] = exc
        ctx["stderr"] = buf.getvalue()
        ctx["stats"] = F.shard_dir_stats()
        ctx["dir_after"] = os.path.isdir(d)
        ctx["files"] = sorted(os.listdir(d)) if os.path.isdir(d) else None
        ctx["ids"] = [r.get("id") for r in F.ShardedLog.read_all(d)]
    except Exception as exc:              # noqa: BLE001
        ctx["err0"] = exc
    return ctx


# 生效条件：无入参时跑两段「重建必失败」场景——① 用**文件占住**分片目录路径后构造 ShardedLog（构造面）：isdir 为假、makedirs 必抛 FileExistsError；② 先正常构造再 rmdir 目录、用文件占住同路径后 append（打开面）：同一条单点判据、同一结构化错误；返回上下文 dict（d / err / stats / stderr / d2 / err_append / stats2 / stderr2 / err0）。
def _case_fail() -> dict:
    tmp = _tmpdir("mdcg_b4_fail_")
    d = os.path.join(tmp, "_index_log")
    ctx = {"d": d, "err": None, "stats": None, "stderr": "", "d2": None,
           "err_append": None, "stats2": None, "stderr2": "", "err0": None}
    try:
        with open(d, "w", encoding="utf-8") as fh:
            fh.write("squat")             # 有文件占着该路径 → 重建必失败
        F.reset_shard_dir_stats()
        buf = io.StringIO()
        try:
            with redirect_stderr(buf):
                F.ShardedLog(d)           # 构造面（where="init"）
        except Exception as exc:          # noqa: BLE001 —— 期望结构化错误
            ctx["err"] = exc
        ctx["stderr"] = buf.getvalue()
        ctx["stats"] = F.shard_dir_stats()

        d2 = os.path.join(tmp, "_index_log_append")
        ctx["d2"] = d2
        lg = F.ShardedLog(d2)             # 先正常建好
        os.rmdir(d2)                      # 再抽掉目录
        with open(d2, "w", encoding="utf-8") as fh:
            fh.write("squat")
        F.reset_shard_dir_stats()
        buf2 = io.StringIO()
        try:
            with redirect_stderr(buf2):
                lg.append({"id": "c1"})   # 打开面（where="append"）
        except Exception as exc:          # noqa: BLE001
            ctx["err_append"] = exc
        ctx["stderr2"] = buf2.getvalue()
        ctx["stats2"] = F.shard_dir_stats()
    except Exception as exc:              # noqa: BLE001
        ctx["err0"] = exc
    return ctx


# ---------------- D 生产链 fixture（长驻 MdCG 实例） ----------------

# 生效条件：无入参时在临时根建 MdCG(root, autoflush=1) 长驻实例并写入 p0（此时分片目录已建成）→ 重置记账 → 以 redirect_stderr 捕获告警后 rmtree(_index_log) 并再写 p1/p2；返回上下文 dict（root / cg / log_dir / stats / stderr / nodes / ids / on_disk / err）。
def _case_prod() -> dict:
    from .mdcg import MdCG
    tmp = _tmpdir("mdcg_b4_prod_")
    root = os.path.join(tmp, "cgroot")
    ctx = {"root": root, "cg": None, "log_dir": None, "stats": None,
           "stderr": "", "nodes": None, "ids": None, "on_disk": None,
           "err": None}
    try:
        cg = MdCG(root, autoflush=1)
        ctx["cg"] = cg
        _LIVE.append(cg)
        cg.add("b4_p0", BODY, layer="knowledge")
        log_dir = cg.index_log_dir
        ctx["log_dir"] = log_dir
        F.reset_shard_dir_stats()
        buf = io.StringIO()
        with redirect_stderr(buf):
            shutil.rmtree(log_dir)
            cg.add("b4_p1", BODY, layer="knowledge")
            cg.add("b4_p2", BODY, layer="knowledge")
        ctx["stderr"] = buf.getvalue()
        ctx["stats"] = F.shard_dir_stats()
        ctx["nodes"] = sorted(cg.index["nodes"])
        ctx["ids"] = [r.get("id") for r in F.ShardedLog.read_all(log_dir)]
        e = cg.index["nodes"].get("b4_p2") or {}
        ctx["on_disk"] = os.path.exists(os.path.join(root, e.get("path") or ""))
    except Exception as exc:              # noqa: BLE001
        ctx["err"] = exc
    return ctx


# ---------------- E stdio 端到端 fixture（MCP 出口） ----------------

# 模拟宿主前先把「身份/路径/编码」注入面清干净——子进程只吃临时目录（与 N225/N206 同款）
_DIRTY_KEYS = (
    "MDCG_TOKEN", "MDCG_TOKEN_FILE", "MDCG_MASTER_KEY", "MDCG_CLEARANCE",
    "MDCG_TENANT", "MDCG_TENANT_REGISTRY",
    "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_LEGACY_ENV_AUTH",
    "MDCG_LEGACY_ENV_ADMIN", "MDCG_SESSION", "DSH_SESSION_ID",
    "MDCG_HARNESS", "MDCG_UNIT", "MDCG_ROOT", "MDCG_STATE_ROOT",
    "MDCG_DATA_ROOT", "MDCG_AUX_ROOT", "MDCG_SUSTAIN", "MDCG_SUSTAIN_NAME",
    "MDCG_MCP_SURFACE", "MDCG_TOOL_FACE", "MDCG_ACTOR",
    "MDCG_VERIFIER_MODULES", "MDCG_HIVE_JOBS",
    "PYTHONUTF8", "PYTHONIOENCODING", "PYTHONLEGACYWINDOWSSTDIO",
)


# 生效条件：tmp 为本次隔离根时，返回剔净 _DIRTY_KEYS 后的 os.environ 副本再注入指向 tmp 的覆盖键（MDCG_ROOT / MDCG_TENANT_REGISTRY / MDCG_STATE_ROOT / MDCG_DATA_ROOT / MDCG_AUX_ROOT / MDCG_TOKEN_FILE / MDCG_MASTER_KEY / MDCG_SUSTAIN / MDCG_LEGACY_ENV_AUTH / MDCG_ACTOR）——子进程绝不读真实 ~/.mdcg、真实令牌库与真实密钥面。
def _env(tmp: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _DIRTY_KEYS}
    env["MDCG_ROOT"] = os.path.join(tmp, "cgroot")
    env["MDCG_TENANT_REGISTRY"] = os.path.join(tmp, "_tenants_absent.json")
    env["MDCG_STATE_ROOT"] = os.path.join(tmp, "state")
    env["MDCG_DATA_ROOT"] = os.path.join(tmp, "data")
    env["MDCG_AUX_ROOT"] = os.path.join(tmp, "auxroot")   # 不可取名 "aux"（设备名）
    env["MDCG_TOKEN_FILE"] = os.path.join(tmp, "tokens.json")
    env["MDCG_MASTER_KEY"] = "00" * 32                     # 哑主密钥
    env["MDCG_SUSTAIN"] = "0"                              # 关常驻循环
    env["MDCG_LEGACY_ENV_AUTH"] = "1"                      # 既有豁免面：零令牌
    env["MDCG_ACTOR"] = "b4-guard"
    return env


# 当前生效的变异（仅 --branch-baseline/--drop-fix 期间非 None）：内存 patch 不跨
# 进程，E 组走独立子进程 ⇒ 靠 sitecustomize 把同一处定点变异注入子进程，端到端
# 面才有真正的判别力。注入以 stderr 标记自证，标记缺失即 E 组判红（fail-closed）。
_MUTATION = [None]

_SITECUSTOMIZE_SRC = '''# B4 守卫跨进程变异注入（临时件，随 tmp 目录一并回收）
import os
import sys
import textwrap
import inspect
_repo = os.environ.get("B4_REPO") or ""
if _repo and _repo not in sys.path:
    sys.path.insert(0, _repo)
try:
    from md_cg import fsutil as _F
    _which = os.environ["B4_MUT_WHICH"]
    _fname = os.environ["B4_MUT_FUNC"]
    _old = os.environ["B4_MUT_OLD"]
    _new = os.environ["B4_MUT_NEW"]
    if _which == "fsutil":
        _holder, _raw = _F.ShardedLog, _F.ShardedLog.__dict__[_fname]
    else:                                     # fsutil_mod：模块级函数
        _holder, _raw = _F, _F.__dict__[_fname]
    _src = inspect.getsource(getattr(_raw, "__func__", _raw))
    _src = textwrap.dedent(_src[_src.index("def %s(" % _fname):])
    # 真全局（vars(_F) 副本会让被测函数的 `global X; X += 1` 写进临时 dict，
    # 父进程断言读到的恒为 0 ⇒ 那是 patch 机制的假红，不是判据红）。
    _ns = _F.__dict__
    exec(compile(_src.replace(_old, _new), "b4_mut.py", "exec"), _ns)
    if _which == "fsutil":
        setattr(_holder, _fname, staticmethod(_ns[_fname]))
    else:
        setattr(_holder, _fname, _ns[_fname])
    sys.stderr.write("[b4-mut] injected %s.%s\\n" % (_which, _fname))
except Exception as _e:
    sys.stderr.write("[b4-mut] inject FAILED: %r\\n" % (_e,))
'''


# 生效条件：lines 为待喂给 stdin 的字符串序列、tmp 为隔离根时，spawn `python -X utf8 -m md_cg.mcp_server`（cwd=包根、env=_env(tmp)；变异轮另经 sitecustomize 注入）一次喂完并 communicate；超时则 kill 后取残余输出；随后删掉**本子进程自己**的自报戳；返回 (returncode, stdout, stderr)。
def _talk(lines, tmp: str, timeout: int = 180):
    env = _env(tmp)
    mut = _MUTATION[0]
    if mut is not None:
        sc_dir = os.path.join(tmp, "_mutpath")
        os.makedirs(sc_dir, exist_ok=True)
        with open(os.path.join(sc_dir, "sitecustomize.py"), "w",
                  encoding="utf-8") as f:
            f.write(_SITECUSTOMIZE_SRC)
        env["PYTHONPATH"] = sc_dir + os.pathsep + env.get("PYTHONPATH", "")
        env["B4_REPO"] = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        env["B4_MUT_WHICH"] = mut["which"]
        env["B4_MUT_FUNC"] = mut["func"]
        env["B4_MUT_OLD"] = mut["old"]
        env["B4_MUT_NEW"] = mut["new"]
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-m", "md_cg.mcp_server"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    try:
        out, err = proc.communicate("\n".join(lines) + "\n", timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    try:
        os.remove(os.path.join(tempfile.gettempdir(), "md_cg_servers",
                               "%d.json" % proc.pid))
    except OSError:
        pass
    return proc.returncode, out or "", err or ""


# 生效条件：rid/method 给定、params 为 None 时省略该键，否则原样写入；返回一行紧凑 JSON-RPC 请求文本。
def _rpc(rid, method, params=None) -> str:
    msg = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg, ensure_ascii=False)


# 生效条件：out 为 stdout 文本时逐行 strip、空行跳过，返回 [(原始行, 解析结果或 None)]（解析失败记 None）。
def _resp_lines(out: str):
    got = []
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            got.append((ln, json.loads(ln)))
        except ValueError:
            got.append((ln, None))
    return got


# 生效条件：无入参时在临时根用**文件占住** `_index_log` 路径（重建必失败）→ 起 stdio 主循环喂 [initialize, mdcg_remember(b4_e1), tools/list, shutdown]；返回上下文 dict（tmp / rc / out / err / by_id / tool_text / tool_obj / inject_ok / error）。
def _case_stdio() -> dict:
    tmp = _tmpdir("mdcg_b4_stdio_")
    ctx = {"tmp": tmp, "rc": None, "out": "", "err": "", "by_id": {},
           "tool_text": "", "tool_obj": None, "inject_ok": True,
           "error": None}
    try:
        root = os.path.join(tmp, "cgroot")
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, "_index_log"), "w",
                  encoding="utf-8") as fh:
            fh.write("squat")             # 目录路径被文件占住
        lines = [_rpc(1, "initialize"),
                 _rpc(2, "tools/call",
                      {"name": "mdcg_remember",
                       "arguments": {"node_id": "b4_e1", "content": BODY}}),
                 _rpc(3, "tools/list"), _rpc(4, "shutdown")]
        ctx["rc"], ctx["out"], ctx["err"] = _talk(lines, tmp)
        ctx["inject_ok"] = ("[b4-mut] injected" in ctx["err"]
                            if _MUTATION[0] is not None else True)
        objs = [o for _raw, o in _resp_lines(ctx["out"])]
        ctx["by_id"] = {o.get("id"): o for o in objs if isinstance(o, dict)}
        call = ctx["by_id"].get(2) or {}
        content = (call.get("result") or {}).get("content") or []
        ctx["tool_text"] = content[0].get("text") if content else ""
        try:
            ctx["tool_obj"] = json.loads(ctx["tool_text"])
        except Exception:                 # noqa: BLE001 —— 非 JSON 也照实记录
            ctx["tool_obj"] = None
    except Exception as exc:              # noqa: BLE001
        ctx["error"] = exc
    return ctx


# ---------------- A 自愈面 ----------------

# 生效条件：跑 A 组 6 条断言（append 不抛 / 目录被重建 / 删除后的记录真落进分片 / 记账可断言 / stderr 告警可观测 / 路径照常）；ctx 由 _case_heal 产出，任一阶段抛异常时六条各自判红。
def g_a():
    begin("A")
    ctx = _case_heal()
    check_fn("B4-A1·删目录后 append 不抛（修前为 FileNotFoundError）",
             lambda c=ctx: c["err"] is None and c["err0"] is None,
             "err=%r err0=%r" % (ctx["err"], ctx["err0"]))
    check_fn("B4-A2·分片目录被重建（isdir 为真）",
             lambda c=ctx: c["dir_after"] is True,
             "dir_after=%r" % (ctx["dir_after"],))
    check_fn("B4-A3·删除后的记录真落进分片（read_all 含 a1/a2）",
             lambda c=ctx: c["ids"] == ["a1", "a2"],
             "ids=%r" % (ctx["ids"],))
    check_fn("B4-A4·记账可断言（1 次重建 + 样本 where=append）",
             lambda c=ctx: c["stats"] is not None
             and c["stats"][0] == 1 and c["stats"][2] == 0
             and len(c["stats"][1]) == 1
             and c["stats"][1][0][1] == "append",
             "stats=%r" % (ctx["stats"],))
    check_fn("B4-A5·不静默（stderr 含「缺失」与目录名）",
             lambda c=ctx: "分片目录缺失" in c["stderr"]
             and "_index_log" in c["stderr"],
             "stderr=%r" % (ctx["stderr"][:200],))
    check_fn("B4-A6·路径照常（分片名与删前同名，不换名）",
             lambda c=ctx: c["files"] == [c["base"]],
             "files=%r base=%r" % (ctx["files"], ctx["base"]))


# ---------------- B 边界与既有语义 ----------------

# 生效条件：跑 B 组 5 条断言（read_all 缺目录 → [] / read_all 路径是文件 → [] / 首建不记账 / 目录在位零记账零告警 / clear 缺目录不抛），全部就地构造最小场景、不依赖 mdcg。
def g_b():
    begin("B")
    tmp = _tmpdir("mdcg_b4_edge_")
    missing = os.path.join(tmp, "_index_log_absent")
    squat = os.path.join(tmp, "_index_log_squat")
    with open(squat, "w", encoding="utf-8") as fh:
        fh.write("squat")

    got_missing, err_missing = None, None
    try:
        got_missing = F.ShardedLog.read_all(missing)
    except Exception as exc:              # noqa: BLE001
        err_missing = exc
    check_fn("B4-B1·read_all 缺目录 → [] 不抛（既有语义一字不改）",
             lambda: err_missing is None and got_missing == [],
             "got=%r err=%r" % (got_missing, err_missing))

    got_squat, err_squat = None, None
    try:
        got_squat = F.ShardedLog.read_all(squat)
    except Exception as exc:              # noqa: BLE001
        err_squat = exc
    check_fn("B4-B2·read_all 路径是文件 → [] 不抛（非目录降级口径）",
             lambda: err_squat is None and got_squat == [],
             "got=%r err=%r" % (got_squat, err_squat))

    fresh = os.path.join(tmp, "_index_log_fresh")
    F.reset_shard_dir_stats()
    st = None
    buf = io.StringIO()
    with redirect_stderr(buf):
        lg = F.ShardedLog(fresh)
        lg.append({"id": "b_fresh"})
        lg.close()
        st = F.shard_dir_stats()
    check_fn("B4-B3·首建不记账（构造 + 首写：计数 0、stderr 干净）",
             lambda: st == (0, (), 0, ()) and buf.getvalue() == "",
             "stats=%r stderr=%r" % (st, buf.getvalue()[:120]))

    F.reset_shard_dir_stats()
    st2 = None
    buf2 = io.StringIO()
    with redirect_stderr(buf2):
        lg2 = F.ShardedLog(fresh)         # 目录已存在
        lg2.append({"id": "b_exist"})
        lg2.close()
        st2 = F.shard_dir_stats()
    check_fn("B4-B4·目录在位时零记账零告警（不产生噪声）",
             lambda: st2 == (0, (), 0, ()) and buf2.getvalue() == ""
             and os.path.isdir(fresh),
             "stats=%r stderr=%r" % (st2, buf2.getvalue()[:120]))

    err_clear = None
    try:
        F.ShardedLog.clear(os.path.join(tmp, "_index_log_absent2"))
    except Exception as exc:              # noqa: BLE001
        err_clear = exc
    check_fn("B4-B5·clear 缺目录 → 直接返回不抛（既有语义）",
             lambda: err_clear is None, "err=%r" % (err_clear,))


# ---------------- C 重建失败的结构化 ----------------

# 生效条件：跑 C 组 9 条断言（构造面：抛 ShardDirError 而非裸 FileNotFoundError / 仍是 OSError 子类 / code 可机读 / message 首字段含 [code] / hint 非空且含目录与处置 / path 属性 / 失败也记账 / 失败也告警；打开面：append 走同一条单点判据、同一结构化错误与 where=append 样本）；ctx 由 _case_fail 产出。
def g_c():
    begin("C")
    ctx = _case_fail()
    e = ctx["err"]
    check_fn("B4-C1·抛 ShardDirError（不是裸 FileNotFoundError）",
             lambda: isinstance(e, F.ShardDirError),
             "err=%r err0=%r" % (e, ctx["err0"]))
    check_fn("B4-C2·仍是 OSError 子类（既有 except OSError 面语义不变）",
             lambda: isinstance(e, OSError), "type=%s" % type(e).__name__)
    check_fn("B4-C3·code 可机读（== E_SHARD_DIR_UNREBUILDABLE）",
             lambda: getattr(e, "code", None) == F.SHARD_DIR_ERR_CODE,
             "code=%r" % (getattr(e, "code", None),))
    check_fn("B4-C4·message 首字段含 [code]（MCP 出口 error 串里可机读）",
             lambda: ("[%s]" % F.SHARD_DIR_ERR_CODE) in str(e),
             "str=%r" % (str(e)[:160],))
    check_fn("B4-C5·hint 非空且含目录与处置（重开进程即可恢复索引）",
             lambda: bool(getattr(e, "hint", ""))
             and ctx["d"] in e.hint and "重开进程" in e.hint,
             "hint=%r" % (getattr(e, "hint", "")[:160],))
    check_fn("B4-C6·path 属性 == 分片目录（可机读定位）",
             lambda: getattr(e, "path", None) == ctx["d"],
             "path=%r d=%r" % (getattr(e, "path", None), ctx["d"]))
    check_fn("B4-C7·失败也记账（1 次失败 + 样本含 where 与异常类型名）",
             lambda: ctx["stats"] is not None and ctx["stats"][2] == 1
             and len(ctx["stats"][3]) == 1
             and ctx["stats"][3][0][1] == "init"
             and ctx["stats"][3][0][2] == "FileExistsError",
             "stats=%r" % (ctx["stats"],))
    check_fn("B4-C8·失败也告警（stderr 含「重建失败」与 code）",
             lambda: "重建失败" in ctx["stderr"]
             and F.SHARD_DIR_ERR_CODE in ctx["stderr"],
             "stderr=%r" % (ctx["stderr"][:200],))
    check_fn("B4-C9·打开面同口径：append 重建失败也抛结构化 + where=append 记账",
             lambda c=ctx: isinstance(c["err_append"], F.ShardDirError)
             and getattr(c["err_append"], "code", None) == F.SHARD_DIR_ERR_CODE
             and c["stats2"][2] == 1 and c["stats2"][3][0][1] == "append",
             "err=%r stats2=%r" % (ctx["err_append"], ctx["stats2"]))


# ---------------- D 生产链（长驻 MdCG 实例） ----------------

# 生效条件：跑 D 组 5 条断言（删 _index_log 后再 add 不抛 / 节点索引可见且盘面 .md 一致 / 分片日志可重放 / 生产链自愈也记账 / 生产链自愈也告警）；ctx 由 _case_prod 产出，MdCG 不可用时五条各自判红。
def g_d():
    begin("D")
    ctx = _case_prod()
    check_fn("B4-D1·生产链：删 _index_log 后再 add 不抛（修前为 FileNotFoundError）",
             lambda c=ctx: c["err"] is None, "err=%r" % (ctx["err"],))
    check_fn("B4-D2·删除后写入的节点索引可见且盘面 .md 存在（索引不落后于盘面）",
             lambda c=ctx: c["nodes"] is not None
             and {"b4_p0", "b4_p1", "b4_p2"} <= set(c["nodes"])
             and c["on_disk"] is True,
             "nodes=%r on_disk=%r" % (ctx["nodes"], ctx["on_disk"]))
    check_fn("B4-D3·分片日志可重放（read_all 含删除后写入的 p1/p2）",
             lambda c=ctx: c["ids"] is not None
             and {"b4_p1", "b4_p2"} <= set(c["ids"]),
             "ids=%r" % (ctx["ids"],))
    check_fn("B4-D4·生产链自愈也记账（1 次重建 + 样本 where=append）",
             lambda c=ctx: c["stats"] is not None and c["stats"][0] == 1
             and c["stats"][2] == 0 and len(c["stats"][1]) == 1
             and c["stats"][1][0][1] == "append",
             "stats=%r" % (ctx["stats"],))
    check_fn("B4-D5·生产链自愈也告警（stderr 含「缺失」与 _index_log）",
             lambda c=ctx: "分片目录缺失" in c["stderr"]
             and "_index_log" in c["stderr"],
             "stderr=%r" % (ctx["stderr"][:200],))


# ---------------- E MCP 出口端到端 ----------------

# 生效条件：跑 E 组 4 条断言（出口 error 串含 code / 出口带可操作 hint / 错误之后进程仍应答且 rc=0 / 变异轮注入自证在场）；ctx 由 _case_stdio 产出。
def g_e():
    begin("E")
    ctx = _case_stdio()
    obj = ctx["tool_obj"]
    check_fn("B4-E1·MCP 出口不裸抛：error 串含 E_SHARD_DIR_UNREBUILDABLE",
             lambda c=ctx: isinstance(c["tool_obj"], dict)
             and F.SHARD_DIR_ERR_CODE in (c["tool_obj"].get("error") or "")
             and "ShardDirError" in (c["tool_obj"].get("error") or ""),
             "tool_text=%r" % (ctx["tool_text"][:220],))
    check_fn("B4-E2·MCP 出口带可操作 hint（含「重开进程」处置）",
             lambda: isinstance(obj, dict)
             and "重开进程" in (obj.get("hint") or ""),
             "hint=%r" % ((obj or {}).get("hint") or "")[:160])
    check_fn("B4-E3·错误之后进程仍应答（tools/list 有 id=3 应答）且 rc=0",
             lambda c=ctx: c["rc"] == 0 and 3 in c["by_id"],
             "rc=%r ids=%r stderr=%r" % (ctx["rc"], sorted(ctx["by_id"]),
                                         ctx["err"][-200:]))
    check_fn("B4-E4·变异轮注入自证在场（fail-closed：注入失效即判红）",
             lambda c=ctx: c["inject_ok"] is True,
             "inject_ok=%r stderr=%r" % (ctx["inject_ok"], ctx["err"][-200:]))


_GROUPS = (("A", g_a), ("B", g_b), ("C", g_c), ("D", g_d), ("E", g_e))


# 生效条件：重算计数器后依次跑 A–E 五组（静默与否由 print 决定），返回 (总失败数, {组名: 失败数} 的副本)；供正常模式与 --branch-baseline 的变异核验共用。
def _run_groups():
    _reset_counters()
    for _name, fn in _GROUPS:
        fn()
    return FAIL, dict(_GROUP_FAILS)


# ---------------- 定点变异自证 ----------------

# 变异表：逐处关掉一个判据，守卫**必须转红**，且红项**恰好**落在该判据负责的
# 组、数量等于表内预期（多一项少一项都报红）。表内数字是**实跑读数**（不是
# 设计意图的估计），每条后面的「外溢面」注释说明该变异为什么牵连到别的组——
# 红项数不是越小越好，而是必须与真实因果一致。基线源=**工作区源码**
# （inspect.getsource 取自当前已加载模块），绝不绑 git HEAD。
_MUTATIONS = (
    # ① 修复本体：append 首开前不复查目录（= 修前行为）。
    #    外溢面（如实登记，不掩盖）：
    #    · C9（append 面的结构化失败）——自愈调用被抽掉后 append 改由 open 抛裸
    #      NotADirectoryError；
    #    · D 全组 5 条——生产链 fixture 在第一次 add 就抛，后续读数（nodes /
    #      read_all / 记账 / 告警）连带落空（修前实测就是这样：一次抛即整链停）。
    ("M1 抽掉修复本体（append 打开前不复查目录）",
     "fsutil", "append",
     'ensure_shard_dir(self.dir, "append")', "pass",
     {"A": 6, "C": 1, "D": 5}),
    # ② 自愈静默：重建成功不记账（容忍 ≠ 静默的计数面）
    ("M2 自愈不记账（计数不累加）",
     "fsutil_mod", "note_shard_dir_rebuild",
     "SHARD_DIR_REBUILDS += 1", "pass",
     {"A": 1, "D": 1}),
    # ③ 自愈静默：重建成功不告警（stderr 面）
    ("M3 自愈不告警（stderr 静默）",
     "fsutil_mod", "note_shard_dir_rebuild",
     "        sys.stderr.write(", "        (lambda *a: None)(",
     {"A": 1, "D": 1}),
    # ④ 重建失败不记账不告警（痕迹只剩异常，被兜底吞掉即失明）。
    #    外溢面：C9 同轮转红（打开面复用同一记账函数）。
    ("M4 重建失败不记账不告警",
     "fsutil_mod", "ensure_shard_dir",
     "note_shard_dir_heal_failure(directory, where, exc)", "pass",
     {"C": 3}),
    # ⑤ 重建失败降级为裸 FileNotFoundError（③ 的反面：冒到出口）。
    #    外溢面：E1/E2（出口串里 code 与 hint 双失）——这正是本条要钉的死点。
    ("M5 重建失败降级为裸 FileNotFoundError",
     "fsutil_mod", "ensure_shard_dir",
     "note_shard_dir_heal_failure(directory, where, exc)",
     "raise FileNotFoundError(directory)",
     {"C": 8, "E": 2}),
    # ⑥ 口径过宽：首建也记账（把正常路径当病态事件，淹没真事件）
    ("M6 首建也记账（口径过宽）",
     "fsutil_mod", "note_shard_dir_rebuild",
     '    if where == "init":\n        return', '    if False:\n        return',
     {"B": 1}),
    # ⑦ 改掉 read_all「非目录 → []」语义（要求④ 的反面）。
    #    外溢面：D 全组 + E 全组——read_all 抛异常会打断 MdCG 装载链
    #    （`_load_index` 在盘面无快照时经它重放），常驻服务连启动都过不去；
    #    这正是要求④「不许改 read_all 既有语义」的**因果理由**，不是偶然牵连。
    ("M7 read_all 非目录不再返回空列表",
     "fsutil", "read_all", "        return []", "        pass",
     {"B": 2, "D": 5, "E": 3}),
)


# 生效条件：which 为 "fsutil" 时从 ShardedLog 类、为 "fsutil_mod" 时从 fsutil 模块取 func_name 的源码文本；**从 `def <name>(` 行起截断再 dedent**（inspect.getsource 对本仓「顶格 `# 生效条件：` 注释 + 类内缩进 def」的排版会把注释一并带来，直接 dedent 会留下缩进 ⇒ IndentationError）；函数缺失或无法取源时返回 None。
def _func_src(which: str, func_name: str):
    try:
        if which == "fsutil":
            raw = F.ShardedLog.__dict__[func_name]
        else:
            raw = F.__dict__[func_name]
        fn = getattr(raw, "__func__", raw)
        src = inspect.getsource(fn)
        return textwrap.dedent(src[src.index("def %s(" % func_name):])
    except Exception:                     # noqa: BLE001 —— 取源失败按锚点漂移处理
        return None


# 生效条件：which 为 "fsutil"/"fsutil_mod"、old 在 func_name 源码中时，把替换后的源码 exec 进 **fsutil 模块的真实命名空间**（`vars(F)` 而非副本——被测函数里的 `global X; X += 1` 必须落到模块真全局，副本会让计数写在临时 dict 里、守卫读到的恒为 0，那是 patch 机制的假红）并挂回目标（类属性或模块级名字；原为 staticmethod 者仍包 staticmethod），返回还原回调；old 不在源码中返回 None（调用方按 ANCHOR-MISS 处置，退出码 2）。
def _patch(which: str, func_name: str, old: str, new: str):
    src = _func_src(which, func_name)     # 取源必须在 exec 之前（exec 后原件被覆盖）
    if src is None or old not in src:
        return None
    holder = F.ShardedLog if which == "fsutil" else F
    orig = holder.__dict__[func_name]     # ← 先存原件：exec 会就地覆盖目标名字
    ns = F.__dict__                       # 真全局：global 语句必须落在被测模块命名空间
    exec(compile(src.replace(old, new), "b4_mut.py", "exec"), ns)
    if isinstance(orig, staticmethod):
        setattr(holder, func_name, staticmethod(ns[func_name]))
    else:
        setattr(holder, func_name, ns[func_name])

    def _restore():
        setattr(holder, func_name, orig)
        if holder is not F and ns.get(func_name) is not orig:
            ns.pop(func_name, None)       # 类方法变异在模块面留下的同名残件

    return _restore


# 生效条件：无入参时跑定点变异自证——先跑未变异基线（必须零失败），再逐个应用 _MUTATIONS：锚点缺失立即打印 ANCHOR-MISS 并返回 2（fail-closed，不再继续）；变异后**逐一打印转红的断言名**与红项数，红项组与数量必须与预期完全一致，否则计入 bad；全部通过返回 0，存在不符返回 1。
def _branch_baseline() -> int:
    print("!! 定点变异模式：逐处关掉判据，守卫应当转红且**恰好**命中预期组/项数\n")
    with contextlib.redirect_stdout(io.StringIO()):
        clean_fail, _clean_groups = _run_groups()
    print("  未变异基线：失败=%d" % clean_fail)
    if clean_fail:
        print("  基线即失败 → 定点变异自证无意义（先修基线）")
        return 1
    bad = []
    for label, which, fname, old, new, expect in _MUTATIONS:
        restore = _patch(which, fname, old, new)
        if restore is None:
            print("  ANCHOR-MISS %s —— 变异锚点漂移（实现改了却没同步本表；"
                  "基线源=%s.%s）" % (label, which, fname))
            return 2                      # fail-closed：锚点漂移不静默失效
        _MUTATION[0] = {"which": which, "func": fname, "old": old, "new": new}
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                got_fail, got_groups = _run_groups()
            red_names = list(FAILS)
        finally:
            _MUTATION[0] = None
            restore()
            _cleanup()                    # 每轮清干净：临时根与活实例不跨轮累积
        hit = {g: n for g, n in got_groups.items() if n}
        print("  关掉「%s」→ 红项=%d，命中组=%s" % (label, got_fail, hit))
        for nm in red_names:
            print("      [RED] %s" % nm)
        if hit == expect and got_fail == sum(expect.values()):
            print("      %s（与预期逐位一致）" % "OK")
        else:
            print("      MISMATCH 预期=%s/%d 实得=%s/%d"
                  % (expect, sum(expect.values()), hit, got_fail))
            bad.append(label)
    return 0 if not bad else 1


# 生效条件：无入参时只施加 M1（抽掉修复本体）——打印转红断言名与红项数、还原后重跑并打印绿项数（「红→恢复→绿」三态原地可见）；锚点缺失返回 2，红项数与预期不符返回 1，两侧都符合返回 0。
def _drop_fix() -> int:
    print("!! 抽掉修复本体：append 打开分片前不再复查目录（= 修前行为）\n")
    label, which, fname, old, new, expect = _MUTATIONS[0]
    print("  变异：%s\n  锚点：%s.%s  %r → %r\n" % (label, which, fname, old, new))
    restore = _patch(which, fname, old, new)
    if restore is None:
        print("  ANCHOR-MISS —— 锚点漂移，fail-closed（退出码 2）")
        return 2
    _MUTATION[0] = {"which": which, "func": fname, "old": old, "new": new}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            got_fail, got_groups = _run_groups()
        red_names = list(FAILS)
    finally:
        _MUTATION[0] = None
        restore()
        _cleanup()
    hit = {g: n for g, n in got_groups.items() if n}
    print("  抽掉修复后：红项=%d 项，命中组=%s" % (got_fail, hit))
    for nm in red_names:
        print("      [RED] %s" % nm)
    with contextlib.redirect_stdout(io.StringIO()):
        back_fail, back_groups = _run_groups()
    back_hit = {g: n for g, n in back_groups.items() if n}
    print("\n  恢复修复后：红项=%d 项，命中组=%s（全绿 ⇒ 红态确由该改动引起）"
          % (back_fail, back_hit))
    ok_red = hit == expect and got_fail == sum(expect.values())
    ok_green = back_fail == 0
    print("  判定：红态%s  ；恢复%s"
          % ("符合预期（%s/%d）" % (expect, sum(expect.values())) if ok_red
             else "**与预期不符**（预期 %s/%d）" % (expect, sum(expect.values())),
             "转绿（0 失败）" if ok_green else "**仍未转绿（%d 失败）**"
             % back_fail))
    return 0 if (ok_red and ok_green) else 1


# 生效条件：命令行含 --branch-baseline 时走定点变异自证（退出码 0/1/2）；含 --drop-fix 时只抽掉修复本体跑「红→恢复→绿」（退出码 0/1/2）；否则依次跑 A–E 五组打印逐条结果与汇总，全部通过返回 0、存在失败返回 1。
def main() -> int:
    try:
        if "--branch-baseline" in sys.argv:
            return _branch_baseline()
        if "--drop-fix" in sys.argv:
            return _drop_fix()
        _reset_counters()
        for _name, fn in _GROUPS:
            fn()
    finally:
        _cleanup()
    print("\n" + "=" * 64)
    print("B4 分片目录自愈守卫：%d 通过，%d 失败" % (PASS, FAIL))
    if FAILS:
        for f in FAILS:
            print("  - %s" % f)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
