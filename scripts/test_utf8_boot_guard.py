# -*- coding: utf-8 -*-
"""test_utf8_boot_guard.py · 入口自保证 UTF-8 的机械守卫（A 项 / 工作纪律第 15 条）

**守卫面**：`utf8_boot.ensure_utf8`（仓根助手）与**七个进程入口**在「解释器未开
UTF-8 模式」这一真实现场下的行为。修前正确性挂在「环境里有 `PYTHONUTF8=1` + 每个
入口记得钉」上——本守卫把那层保证从环境变量搬到进程自身后，逐条钉死。

判据（与设计裁决的验证清单逐条对应）：
  ① E2E-HIVE / E2E-MDCG —— **端到端组帧**：清空 `PYTHONUTF8`/`PYTHONIOENCODING`
     且不带 `-X utf8` 的子进程里启动 stdio MCP 入口，喂含中文的 JSON-RPC 请求行，
     断言拿到正确响应、且 stdout **逐行皆为合法 JSON**（组帧未被重启打断）。
     hive 面**两趟**（契约 c4/c5/c6）：
       · `E2E-HIVE-OK`（**成功趟**）：`HIVE_EXE` 指向**真实 release 二进制**、
         `HIVE_JOBS_DIR` 指向守卫**自己的临时池** ⇒ 断言 `ok=true`、`job_id` 为
         四槽中文形态 `h_…_…_…_NNNN`、任务目录落在临时池内、中文逐字节往返、
         **未拉起 serve**（`serve.started is False`）。二进制缺失（未构建的新检出）
         ⇒ 本趟**显式 SKIP 并打印期望路径**，**不计入通过数**（三态
         ok/红/skip，见 `Skipped`）。
       · `E2E-HIVE`（**失败趟**，原口径**保留**）：探针 exe 缺席 ⇒ 断言 `ok=false`
         且原因**回显中文 context 路径**（逐字节相等）。两趟缺一不可。
       · `E2E-PASSES`：**两趟齐备的自我锚**（AST 读**被判根**的守卫源码：两趟的注册项
         与成功趟的断言骨架必须在位）——删掉成功趟即转红（定点变异 S1 实测）。
  ② ONCE —— **只重启一次**：以「解释器启动计数」证明进程数不增长、不递归。
  ③ FAILFAST —— 显式退出通道（`LINGSHU_UTF8_NO_REEXEC`）非 0 退出且含可执行指引，
     并且**确未重启**（计数为 1）。
  ④ NOOP / ENV-CHILD —— `-X utf8`（模式已开）时**不重启**（计数为 1）；且
     `PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8` 已置入 env，供同进程随后派生的子进程继承。
  ⑤ ANCHOR —— 七个入口逐个断言「确实调用了助手」（import 锚 + 调用锚 + 约束注释锚），
     且**调用锚早于该文件第一个模块级 `def`**（即早于一切模块级 I/O）。
  ⑥ DEPDIR —— 依赖方向：助手只 import 标准库；import 它之后 `md_cg` 不在 `sys.modules`。
  ⑦ GUIDE（F2）—— 七个入口逐个：fail-fast 指引里**印出的那条命令必须真能跑起来**
     （起进程，观察到非 ImportError 的启动迹象），且形态与该入口的真实接入形态一致
     （`-m <模块名>` 或 `<入口路径>`）。只做字符串断言不算过——指引写错的代价就是
     使用者照抄后撞墙（修前实测：`python -X utf8 md_cg/mcp_server.py` → rc=1 ImportError）。
  ⑧ IMPORT-NO-RESTART（F6）—— 逐个 import 七入口**不得**导致解释器重启（启动计数 1）；
     与 ② 合起来即「被 import 不重启 ∧ `python -m` 形态仍自动重启」（F6 不得修坏 A3）。
  ⑨ STREAMS（F3）—— **行为差分**：在「父进程 sys.stdin/stdout/stderr 不指向 fd 0/1/2」
     的拓扑下跑同一条 stdio 组帧 E2E，助手**漏传任一条流**都必须让组帧转红。
  ⑩ MUTATIONS —— 定点变异自证：每个判据都有定点变异把它打红，且**恰好**命中预期项集
     与预期退出码（另含一个「无关改动必须全绿」的假阳性对照）。
  ⑪ 三态汇总 —— 判据结果分 `ok` / `红` / **`skip`**（抛出 `Skipped`）：skip 逐条打印
     理由（含期望路径），**不计入通过数**；存在 skip 时汇总另打 ⚠ 行（不得静默判绿）。

⑨ 的拓扑为什么不是「宿主 PIPE 直连」（本机 2026-09-29 实测，**这是本条判据的设计依据**）：
  把宿主侧也做成 `Popen(..., stdin=PIPE, stdout=PIPE, stderr=PIPE)` 时，助手即使**漏传**
  `stdin=` / `stdout=` / `stderr=`，子进程也会**直接继承**父进程的 fd 0/1/2（同一条管道），
  组帧照样成立——单独剥离任一条流，① 的 E2E 依然全绿（实测：M9/M10/M11 三项各自只在
  「宿主 PIPE 直连」拓扑下跑时全绿，继承掩盖了缺失）。故 ⑨ 把父进程的三条流换成**普通
  文件对象**（非 fd 0/1/2）：此时「显式传递」⇒ 子进程写进那三个文件（正确），「漏传」⇒
  子进程写进宿主管道（文件里没有组帧）——差异真实、可观测、可定点变异。

ANCHOR-MISS（锚点漂移，**退出码 2**，fail-closed）三类：
  · 入口锚点缺失/改名（⑤ 的 import 锚 / 调用锚 / 约束注释锚任一不见）；
  · 助手源码里变异注入点找不到（判据面已漂移，变异从未真正生效）；
  · 定点变异**未**命中预期项集或预期退出码（说明判据与实现已脱钩）。

判据现场构造口径（诚实边界）：现场要求「清空 `PYTHONUTF8` / `PYTHONIOENCODING`」。
Linux 上 locale 为 `C`/`POSIX` 时解释器会**自动**开 UTF-8 模式（PEP 540），清空 env
构不出「未开」态——此时守卫追加 `PYTHONUTF8=0` 强制构造，并在报告里点名该事实
（本机 Windows/cp936 清空即得「未开」，不需要追加）。

隔离纪律：全部实验面在 `tempfile.TemporaryDirectory` 内（认知图根 / 状态面 / aux 根 /
hive jobs 池全部指向临时目录，身份走既有 `MDCG_LEGACY_ENV_AUTH` 豁免面，`HIVE_EXE`
指向不存在的探针路径 ⇒ 绝不拉起真 serve），**不触任何在役数据根**；定点变异在
「临时物化的仓面」上做，**绝不改动工作树**。

退出码：0 = 全绿；1 = 存在违例（判据红 / 顺序漂移）；2 = ANCHOR-MISS。
（显式 SKIP **不改变退出码**——未构建的新检出上「跑不了」既不是违例也不是通过；
它的存在由逐条 `[skip]` 行 ＋ 汇总计数 ＋ ⚠ 行显式暴露，见 ⑪。）

用法：
  python scripts/test_utf8_boot_guard.py                 # 全量（含定点变异自证）
  python scripts/test_utf8_boot_guard.py --no-mutations   # 跳过 ⑦（快速）
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

# ---------------------------------------------------------------- 入口自保证 UTF-8
# 约束（工作纪律第 15 条）：本调用必须在**任何文件/库 I/O 之前**——本守卫自己也是
# 一个进程入口（`--no-mutations` / 套件直跑）。实测反证：不接它时，在清空
# `PYTHONUTF8`/`PYTHONIOENCODING` 的父进程下直跑，本守卫 print 判据描述（含 `⇒`）
# 即在 gbk stdout 上 `UnicodeEncodeError` 崩、rc=1 且**后半判据根本没跑**——守卫守的
# 就是这件事，自己不自保证说不过去。仓库根入 sys.path 的形态照 hive/exec.py::
# _md_cg_import 的最小写法（助手在仓根，不是 md_cg 包目录）。
_UTF8_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _UTF8_ROOT not in sys.path:
    sys.path.insert(0, _UTF8_ROOT)
from utf8_boot import ensure_utf8  # noqa: E402

ensure_utf8(__file__)


_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)

# ---------------------------------------------------------------- 判据面常量

#: 七个进程入口（顺序即报告顺序）
ENTRIES = (
    ("hive/hive_mcp/mcp_server.py", "ZCode/DSH 直连 stdio MCP 服务"),
    ("md_cg/mcp_server.py", "认知图 stdio MCP 服务"),
    ("hive/exec.py", "执行器子进程"),
    ("hive/orch.py", "编排器 worker"),
    ("hive/serve_start.py", "serve 拉起"),
    ("md_cg/run_tests.py", "包内全量入口"),
    ("scripts/run_tests.py", "源码树全量入口"),
)

ANCHOR_COMMENT = "# ---------------------------------------------------------------- 入口自保证 UTF-8"
ANCHOR_NOTE = "# 约束（工作纪律第 15 条）：本调用必须在**任何文件/库 I/O 之前**"
ANCHOR_IMPORT = "from utf8_boot import ensure_utf8"
ANCHOR_CALL = "ensure_utf8(__file__)"

#: 七入口的**真实接入形态**（F2）与「真能跑起来」探针（GUIDE 判据用）。
#:   form=("m", 模块名) ⇒ `python -X utf8 -m <模块名>`；form=("f", None) ⇒ `python -X utf8 <入口路径>`
#:   argv=追加参数；probe=启动迹象断言（见 _startup_ok）
ENTRY_LAUNCH = {
    "hive/hive_mcp/mcp_server.py": {
        "form": ("m", "hive.hive_mcp.mcp_server"), "argv": [],
        "probe": ("rpc", "hive-mcp")},
    "md_cg/mcp_server.py": {
        "form": ("m", "md_cg.mcp_server"), "argv": [],
        "probe": ("rpc", "mdcg-mcp")},
    "hive/exec.py": {
        "form": ("f", None), "argv": [],
        "probe": ("stderr", "usage: exec.py")},
    "hive/orch.py": {
        "form": ("f", None), "argv": [],
        "probe": ("stderr", "usage: orch.py")},
    "hive/serve_start.py": {
        "form": ("f", None), "argv": ["--show-config"],
        "probe": ("stdout", '"keys"')},
    "md_cg/run_tests.py": {
        "form": ("m", "md_cg.run_tests"), "argv": ["--list"],
        "probe": ("rc0", None)},
    "scripts/run_tests.py": {
        "form": ("f", None), "argv": ["--list"],
        "probe": ("rc0", None)},
}
#: 指引里「可照抄启动命令」那一行的前缀（_parse_guide_cmd 只认它）
GUIDE_CMD_PREFIX = "python -X utf8 "
#: IMPORT-NO-RESTART 判据的 import 形态（scripts/ 不是包 ⇒ 只能按文件装载，且模块名**不是** __main__）
IMPORT_CASES = (
    ("hive.serve_start", "mod", "hive.serve_start"),
    ("hive.exec", "mod", "hive.exec"),
    ("hive.orch", "mod", "hive.orch"),
    ("hive.hive_mcp.mcp_server", "mod", "hive.hive_mcp.mcp_server"),
    ("md_cg.run_tests", "mod", "md_cg.run_tests"),
    ("md_cg.mcp_server", "mod", "md_cg.mcp_server"),
    ("scripts.run_tests", "file", "scripts/run_tests.py"),
)


HELPER_REL = "utf8_boot.py"
#: 助手允许的 import 顶层名（纯 stdlib；`__future__` 是编译指示）
HELPER_ALLOWED_IMPORTS = frozenset(("__future__", "locale", "os", "subprocess", "sys"))
#: 依赖方向判据：这些包名一个都不得出现在助手的 import 面
FORBIDDEN_IMPORTS = frozenset(("md_cg", "hive", "scripts", "compiler", "swarm"))

#: 中文探针（UTF-8 字节按 GBK 严格解码必非法 ⇒ 组帧若走 locale 编码必现形）
PROBE_ZH = "中文标题：编码守卫"
#: 探针用的中文**相对** context 路径（必不存在）：`_t_spawn` 的 context 存在性闸会把
#: 它逐字节回显进 error ⇒ 一次调用同时证明「中文入参已被受理」与「中文出参编码正确」。
PROBE_ZH_CTX = "探针_中文上下文_无此文件.md"

# ---------------------------------------------------------------- 成功趟（c4/c5）探针面
#: 成功趟的四槽（前三槽；第四槽「编号」由 Rust 侧分配器给出）与**存在**的中文 context
#: 文件——后者是逐字节往返的**第二载体**（它随 spec.json 落盘，再从盘上读回来比对）。
PROBE_SLOTS = {"identity": "探针端", "task": "编码守卫", "unit": "验证单元"}
PROBE_CTX_OK_NAME = "探针_中文上下文_存在.md"
PROBE_CTX_OK_BODY = "中文内容：上下文逐字节往返探针\n"
#: 成功趟期望的 job_id 前缀（四槽前三段，逐字节）与「形如 h_…_…_…_NNNN」的形态判据
PROBE_ID_PREFIX = "h_探针端_编码守卫_验证单元_"
PROBE_ID_RE = re.compile(r"^h_[^_]+_[^_]+_[^_]+_\d{4}$")
#: hive 二进制相对路径（成功趟用真二进制；见 `_hive_bin` 的三级查找）
HIVE_BIN_REL = ("hive", "target", "release",
                "hive.exe" if os.name == "nt" else "hive")
#: 本守卫自身的仓内相对路径（`E2E-PASSES` 自我锚读**被判根**的这一份源码）
GUARD_REL = "scripts/test_utf8_boot_guard.py"
#: 成功趟**断言骨架**锚（c4 的硬要求：ok=true / job_id 四槽形态 / 目录落临时池 /
#: 未拉 serve / 中文落盘往返）。查法：AST 取 `check_e2e_hive_ok` 的源码语段再查子串
#: ——**只在该语段里查**，故这些字面量写在本常量处不会自我指涉（若整文件查子串，删掉
#: 成功趟后锚点仍由本常量自身满足 ⇒ 假绿）。
SUCCESS_BODY_TOKENS = (
    'sp.get("ok") is True',
    "PROBE_ID_RE.match(jid)",
    "落在守卫自己的临时池",
    'get("started") is False',
    'spec.get("context_files") != [ctx]',
)
#: `E2E-PASSES` 同时钉住的函数名（两趟各一；删掉任一趟即转红）
PASS_FUNCS = ("check_e2e_hive_fail", "check_e2e_hive_ok")
#: `E2E-PASSES` 同时钉住的注册 id（`_CHECKS` 里的两项）
PASS_IDS = ("E2E-HIVE", "E2E-HIVE-OK")

NO_REEXEC_ENV = "LINGSHU_UTF8_NO_REEXEC"
FAILFAST_EXIT = 2
#: 解释器启动计数上限（熔断；正向预期为 1~2，故 6 不误伤）
FUSE_LIMIT = 6
FUSE_EXIT = 97

#: 子进程 env 的污染清理面（照 md_cg/test_issue39_utf8_stdio.py 的同族清单）
_DIRTY_KEYS = (
    "MDCG_TOKEN", "MDCG_CLEARANCE", "MDCG_TENANT", "MDCG_TENANT_REGISTRY",
    "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_LEGACY_ENV_AUTH",
    "MDCG_LEGACY_ENV_ADMIN", "MDCG_SESSION", "DSH_SESSION_ID",
    "MDCG_HARNESS", "MDCG_UNIT", "MDCG_ROOT", "MDCG_STATE_ROOT",
    "MDCG_DATA_ROOT", "MDCG_AUX_ROOT", "MDCG_SUSTAIN", "MDCG_SUSTAIN_NAME",
    "MDCG_MCP_SURFACE", "MDCG_TOOL_FACE", "MDCG_ACTOR",
    "MDCG_VERIFIER_MODULES", "MDCG_HIVE_JOBS", "MDCG_TOKEN_FILE",
    "PYTHONUTF8", "PYTHONIOENCODING", "PYTHONLEGACYWINDOWSSTDIO",
    "HIVE_JOBS_DIR", "HIVE_CONFIG", "HIVE_EXE", "HIVE_API_KEY",
    "HIVE_API_BASE", "HIVE_EXEC_PY", "HIVE_ORCH_PY", "HIVE_LLM_EXEC_PY",
    "UTF8GUARD_COUNT", "UTF8GUARD_FUSE", NO_REEXEC_ENV,
)

#: 定点变异要物化的仓面前缀白名单（跳过语料/图片/构建产物——与判据无关且体积大）
_MATERIALIZE_SKIP = ("docs/", "skills/", "node_modules/", "hive/target/",
                     "hive/jobs/", "hive/interop/", ".git/", ".zcode/",
                     "_md_cg_", "rust/target/")


class AnchorMiss(Exception):
    """锚点漂移（退出码 2）。"""


class Skipped(Exception):
    """判据**显式跳过**（三态里的第三态：非通过、非违例）。

    为什么需要第三态（c6）：成功趟要用**真实 release 二进制**——未构建的新检出上它
    不存在，此时「跑不了」既不是通过也不是违例（判绿 = 静默撒谎；判红 = 拿没构建的
    环境当缺陷）。故跳过必须**显式**：携带理由（**含期望路径**）逐条打印、计入汇总的
    SKIP 计数、**绝不计入通过数**、并在汇总处另打 ⚠ 行。
    """


# ---------------------------------------------------------------- 子进程工具

# 生效条件：root/fusedir 给出后返回构造好的子进程 env dict（详见函数 docstring）；extra/counter 缺省表示不追加业务键、不计数；fuse 给出时覆盖熔断上限（缺省 FUSE_LIMIT）。
def _env_clean(root: str, fusedir: str, extra: dict | None = None,
               counter: str | None = None, fuse: int | None = None) -> dict:
    """构造「未开 UTF-8 模式」的子进程 env（清空 PYTHONUTF8/PYTHONIOENCODING）。

    生效条件：总是把 PYTHONPATH 置为「熔断面 + root」；counter 非空时置计数器与熔断
    上限（fuse 缺省 FUSE_LIMIT）；宿主默认已开 UTF-8 模式（Linux C locale）时追加
    PYTHONUTF8=0 强制构造「未开」态（否则该现场在本机根本构不出）；extra 最后覆盖。
    """
    env = {k: v for k, v in os.environ.items() if k not in _DIRTY_KEYS}
    env["PYTHONPATH"] = fusedir + os.pathsep + root
    # 兜底隔离面：任何一条判据下的进程（含 M7 变异下被助手 import 的 md_cg）都不得
    # 回落到真实 ~/.mdcg 凭据根——aux/root/state/data 一律指向本次守卫的临时面。
    iso = os.path.join(os.path.dirname(fusedir), "iso")
    env.setdefault("MDCG_AUX_ROOT", os.path.join(iso, "auxroot"))
    env.setdefault("MDCG_ROOT", os.path.join(iso, "cgroot"))
    env.setdefault("MDCG_STATE_ROOT", os.path.join(iso, "state"))
    env.setdefault("MDCG_DATA_ROOT", os.path.join(iso, "data"))
    env.setdefault("MDCG_TENANT_REGISTRY", os.path.join(iso, "_tenants_absent.json"))
    if counter:
        env["UTF8GUARD_COUNT"] = counter
        env["UTF8GUARD_FUSE"] = str(fuse if fuse else FUSE_LIMIT)
    if _host_utf8_default():
        env["PYTHONUTF8"] = "0"
    if extra:
        env.update(extra)
    return env


# 生效条件：缓存非空即返回缓存；否则以「清空 PYTHONUTF8/PYTHONIOENCODING 的裸解释器」实测 sys.flags.utf8_mode 是否为 1，返回该布尔（用于决定是否强制 PYTHONUTF8=0）。
def _host_utf8_default() -> bool:
    """宿主在「清空两个 env」后是否**自动**处于 UTF-8 模式（PEP 540）。"""
    global _HOST_UTF8
    if _HOST_UTF8 is not None:
        return _HOST_UTF8
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    try:
        p = subprocess.run([sys.executable, "-c",
                            "import sys;print(sys.flags.utf8_mode)"],
                           env=env, capture_output=True, timeout=60)
        _HOST_UTF8 = p.stdout.decode("ascii", "replace").strip() == "1"
    except (OSError, subprocess.TimeoutExpired):
        _HOST_UTF8 = False
    return _HOST_UTF8


_HOST_UTF8: "bool | None" = None


# 生效条件：argv/env/cwd 给出后以二进制管道 spawn（三个标准流均为 PIPE），若 lines 非空则按行写 UTF-8 字节并关 stdin；超时则 kill 并返回 (124, 已读字节, "超时")；返回 (returncode, stdout_bytes, stderr_bytes)。
def _talk(argv: list, env: dict, lines: list, cwd: str,
          timeout: int = 180) -> tuple[int, bytes, bytes]:
    """二进制管道收发（**不做 text 解码**——组帧判据要看原始字节）。"""
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    payload = ("\n".join(lines) + "\n").encode("utf-8") if lines else b""
    try:
        out, err = proc.communicate(payload, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        return 124, out or b"", (err or b"") + b"<timeout>"
    return proc.returncode, out or b"", err or b""


# 生效条件：rid 为任意 JSON-RPC id，method 为方法名，params 为 None 或对象；返回该请求的 JSON 文本（ensure_ascii=False，中文按 UTF-8 出线）。
def _rpc(rid, method: str, params=None) -> str:
    msg = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg, ensure_ascii=False)


# 生效条件：raw 为子进程 stdout 原始字节；UTF-8 严格解码失败返回 (None, 原因)；否则把非空行逐个 json.loads，任一行非法即返回 (None, 原因)，全部合法返回 (行对象列表, "")——组帧判据只认「逐行皆 JSON」。
def _frames(raw: bytes) -> tuple[list | None, str]:
    """stdout → JSON-RPC 帧列表（逐行严格判定）。"""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        return None, "stdout 不是合法 UTF-8：%s" % e
    objs = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            objs.append(json.loads(ln))
        except ValueError:
            return None, "stdout 有非 JSON 行（组帧被污染）：%r" % ln[:120]
    return objs, ""


# 生效条件：objs 为帧列表、rid 给定；返回 id == rid 的首个对象，无则返回 None。
def _find(objs: list, rid):
    for o in objs:
        if isinstance(o, dict) and o.get("id") == rid:
            return o
    return None


# 生效条件：obj 为 tools/call 响应帧；其 result.content[0].text 可解析为 JSON 对象时返回该对象，否则返回 {}（不抛）。
def _payload(obj) -> dict:
    try:
        text = (obj.get("result") or {}).get("content", [{}])[0].get("text", "{}")
        out = json.loads(text)
        return out if isinstance(out, dict) else {}
    except (ValueError, AttributeError, IndexError, TypeError):
        return {}


# 生效条件：path 给出时返回其行数（文件缺失返回 0）；用于解释器启动计数。
def _count_lines(path: str) -> int:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return sum(1 for ln in fh if ln.strip())
    except OSError:
        return 0


# 生效条件：dirpath 与 root 给出时删除 dirpath 下**本轮新增**且其 pid 已不存活的自报文件（`<tempdir>/md_cg_servers/<pid>.json`），绝不删在跑进程的文件；返回删除数。
def _clean_selfreports(dirpath: str, before: set) -> int:
    """清掉本轮 md_cg 进程留下的自报文件（判存活后才删，绝不误删在役服务）。"""
    if not os.path.isdir(dirpath):
        return 0
    n = 0
    for name in os.listdir(dirpath):
        if not name.endswith(".json") or name in before:
            continue
        pidtxt = name[:-5]
        if not pidtxt.isdigit():
            continue
        if _pid_alive(int(pidtxt)):
            continue
        try:
            os.remove(os.path.join(dirpath, name))
            n += 1
        except OSError:
            pass
    return n


# 生效条件：pid 为正整数时返回该进程是否仍存活（POSIX 用 os.kill(pid,0)，Windows 用 OpenProcess 查询句柄），判定失败一律返回 True（保守：宁可不删）。
def _pid_alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except (OSError, PermissionError):
            return True
    try:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    except Exception:                                     # noqa: BLE001
        return True


# ---------------------------------------------------------------- 现场构造

# 生效条件：tmp 给出时返回 md_cg 隔离 env 覆盖（root/state/data/aux/登记表全指向 tmp 子目录，身份走 MDCG_LEGACY_ENV_AUTH 豁免面，MDCG_SUSTAIN=0 关常驻）。
def _mdcg_extra(tmp: str) -> dict:
    """md_cg 侧隔离面（照 md_cg/test_issue39_utf8_stdio.py 同款口径）。"""
    return {
        "MDCG_ROOT": os.path.join(tmp, "cgroot"),
        "MDCG_TENANT_REGISTRY": os.path.join(tmp, "_tenants_absent.json"),
        "MDCG_STATE_ROOT": os.path.join(tmp, "state"),
        "MDCG_DATA_ROOT": os.path.join(tmp, "data"),
        # 子目录名不可取 "aux"：Windows 保留设备名（ntpath.abspath 经
        # GetFullPathNameW 解析成 \\.\aux，aux_root() 覆盖键静默失联）
        "MDCG_AUX_ROOT": os.path.join(tmp, "auxroot"),
        "MDCG_SUSTAIN": "0",
        "MDCG_ACTOR": "utf8-guard",
        "MDCG_LEGACY_ENV_AUTH": "1",
        "MDCG_CAN_ADMIN": "1",
        "MDCG_LEGACY_ENV_ADMIN": "1",
    }


# 生效条件：tmp 给出时返回 hive 隔离 env 覆盖（jobs 池指向 tmp；HIVE_CONFIG/HIVE_EXE 指向不存在的路径 ⇒ _ensure_serve 在 isfile 即返回，绝不拉起真 serve）。
def _hive_extra(tmp: str) -> dict:
    """hive 侧隔离面（探针 exe 不存在 ⇒ 绝不触真实在役 serve）。

    **两趟共用**：失败趟要的就是这条「exe 缺席」面；成功趟另把 HIVE_EXE 覆盖成真实
    二进制（见 `check_e2e_hive_ok`），但 `HIVE_CONFIG` 保持缺席——那才是「真 exe 也
    拉不起 serve」的那道闸（`serve_start.start` 在 `load_config` 即返回）。
    """
    return {
        "HIVE_JOBS_DIR": os.path.join(tmp, "hivejobs"),
        "HIVE_CONFIG": os.path.join(tmp, "absent_config.json"),
        "HIVE_EXE": os.path.join(tmp, "no_such_hive.exe"),
    }


# 生效条件：root 给出时返回成功趟要用的**真实** hive 二进制路径（三级查找，绝不猜、绝不构建）：① env HIVE_EXE（需 isfile）② 被判根 <root>/hive/target/release/hive[.exe] ③ 本仓 <ROOT>/hive/target/release/hive[.exe]；三级都不在时仍返回第②级路径（期望路径，供 SKIP 理由原样打印）。
def _hive_bin(root: str) -> str:
    """成功趟用的真实 hive 二进制。

    为什么要第③级：`--mutations` 的定点变异跑在**临时物化副本**上（`_MATERIALIZE_SKIP`
    跳过 `hive/target/`，副本里没有构建产物）。此时用本仓已构建的二进制是**有意为之**：
    被判面是 python 入口（`hive/hive_mcp/mcp_server.py`——副本里那份才是被变异的那份）
    与 stdio 组帧，二进制只充当**真实分配器**（`alloc-id` 不启动 serve，见
    `check_e2e_hive_ok` 的安全前提）。故三级查找不会把「变异是否生效」掩盖掉。
    """
    env = os.environ.get("HIVE_EXE")
    if env and os.path.isfile(env):
        return env
    cand = os.path.join(root, *HIVE_BIN_REL)
    if os.path.isfile(cand):
        return cand
    repo_cand = os.path.join(ROOT, *HIVE_BIN_REL)
    if os.path.isfile(repo_cand):
        return repo_cand
    return cand


# 生效条件：root 给出时返回 `<root>/hive/jobs` 的目录项排序清单（不存在/不可读 ⇒ None）——**只读**，用于 c5「在役池零触碰」的前后比对；清单**排除在役 serve 的心跳产物**（`_serve*`：`_serve.json` / `_serve.log` / `_serve.tmp<pid>`——在役 serve 约 20s 一次原子改写心跳、改写瞬间伴生 .tmp，与被判面的行为无关）。
def _pool_listing(root: str):
    """在役池清单快照（只读）。

    排除 `_serve*`（归因实验 2026-10-01：在役 serve 的心跳每 ~20s 改写一次
    `_serve.json`——mtime 逐次精准 +20s——改写瞬间伴生 `_serve.tmp<pid>`；
    落在 c5 前后快照窗口内会被误判为「本趟写了在役池」，实测套件并行下
    命中率 ≈ 窗口/20s、最小复现 3 轮红 1）。c5 的意图是「本趟不得往在役池
    写**作业目录**」，心跳不是被判面的产物；排除后其余任何新增（含意外
    文件）仍判违规——口径只收窄这一族，判据强度不变。
    """
    try:
        return sorted(n for n in os.listdir(os.path.join(root, "hive", "jobs"))
                      if not n.startswith("_serve"))
    except OSError:
        return None


# 生效条件：path/parent 给出时返回 path 是否落在 parent（含 parent 自身）之下（绝对路径比对）。
def _under(path: str, parent: str) -> bool:
    """path 是否在 parent 之下——临时池自证用（c5）。"""
    p, q = os.path.abspath(path), os.path.abspath(parent)
    return p == q or p.startswith(q.rstrip("\\/") + os.sep)


# ---------------------------------------------------------------- 判据 ①：端到端组帧

# 生效条件：root 为被判仓面、tmp 为临时面；清空两个 env 且不带 -X utf8 起 hive stdio MCP，喂 initialize/tools-list/中文 hive_spawn 三行，返回 (是否通过, 说明)——断言 rc=0、逐行 JSON、握手 serverInfo=hive-mcp、中文 spawn **逐字节往返**（ok=False 且原因里回显请求中的中文路径，且错误不是「缺四槽」）。
#
# **失败趟**（原口径，c4 要求**保留**；成功趟见 check_e2e_hive_ok）：
# id 契约 v2（B8）下 `_submit` 不再自造 id、改调 Rust 侧 `hive alloc-id`；本趟把
# `HIVE_EXE` 钉在**不存在的路径**（`_hive_extra`），故这一趟判的是**失败路径**：
# 请求带中文四槽 + 一个不存在的中文相对 context 路径 ⇒ 断言 ok=False、原因里**回显
# 该中文路径**（逐字节相等）⇒ 中文入参已被受理（过了四槽闸与 JSON 解码）且中文出参
# 编码正确。它**不能**替代成功趟（成功趟才覆盖「alloc-id 真跑通 + job_id 四槽形态」）。
def check_e2e_hive_fail(root: str, tmp: str, fusedir: str) -> tuple[bool, str]:
    jobs = os.path.join(tmp, "hivejobs")
    os.makedirs(jobs, exist_ok=True)
    env = _env_clean(root, fusedir, _hive_extra(tmp))
    lines = [
        _rpc(1, "initialize", {}),
        _rpc(None, "notifications/initialized"),
        _rpc(2, "tools/list", {}),
        _rpc(3, "tools/call", {"name": "hive_spawn", "arguments": {
            "model": "probe-model", "user_prompt": PROBE_ZH,
            "identity": "探针端", "task": "编码守卫", "unit": "验证单元",
            "context_files": [PROBE_ZH_CTX]}}),
    ]
    rc, out, err = _talk([sys.executable, "-m", "hive.hive_mcp.mcp_server"],
                         env, lines, root)
    objs, why = _frames(out)
    if objs is None:
        return False, "rc=%d 组帧非法：%s stderr=%r" % (rc, why, err[-200:])
    init = _find(objs, 1)
    if not (isinstance(init, dict)
            and ((init.get("result") or {}).get("serverInfo") or {}).get("name")
            == "hive-mcp"):
        return False, "initialize 握手异常：rc=%d objs=%s" % (rc, str(objs)[:200])
    sp = _payload(_find(objs, 3) or {})
    serr = sp.get("error") or ""
    if not (sp.get("ok") is False and PROBE_ZH_CTX in serr and "四槽" not in serr):
        return False, ("中文 hive_spawn 未逐字节往返（期望 ok=False 且原因回显中文"
                       " context 路径 %r）：%s" % (PROBE_ZH_CTX, str(sp)[:200]))
    if rc != 0:
        return False, "进程未正常下线 rc=%d stderr=%r" % (rc, err[-200:])
    if "UnicodeEncodeError" in err.decode("utf-8", "replace"):
        return False, "stderr 出现 UnicodeEncodeError"
    return True, "rc=0 帧数=%d 中文入参逐字节往返成功（原因回显 %s）" % (
        len(objs), PROBE_ZH_CTX)


# 生效条件：root 为被判仓面、tmp 为临时面；`HIVE_EXE` 指向真实 release 二进制、`HIVE_JOBS_DIR` 指向守卫自己的临时池，清空两个 env 且不带 -X utf8 起 hive stdio MCP，喂 initialize + 中文四槽 hive_spawn（带一个**存在**的中文 context 文件），返回 (是否通过, 说明)；二进制缺失抛 Skipped（显式跳过、含期望路径、不计入通过数）；断言 rc=0、逐行 JSON、握手 hive-mcp、ok=true、job_id 为四槽中文形态、任务目录在临时池内、未拉起 serve、中文逐字节往返（响应 slots 与 spec.json）。
#
# 为什么真 exe 不会拉起在役 serve（**安全前提，必须写在码上**）：
#   ① 本趟走 `hive_spawn` → `_submit` → `_alloc_job_id` → `HIVE_EXE alloc-id`；alloc-id
#      是**纯分配**通道（Rust `job::alloc_job_id` 只 `fs::create_dir` 落池 + 回显 id），
#      **不读也不启动任何 serve**；
#   ② `HIVE_CONFIG` 仍钉在**不存在**的路径（`_hive_extra`）⇒ `_ensure_serve` 的拉起
#      分支即使被走到，也在 `serve_start.start()` 的 `load_config` 即返回
#      {"ok": False, "error": "配置文件不存在…"}（hive/serve_start.py:462-464），
#      `Popen([EXE, "serve", …])` 那一步**不执行**；
#   ③ 本判据另断言响应 `serve.started is False`——把「没拉 serve」变成**断言**而非承诺。
#
# 为什么必须**显式**跳过而不是判绿/判红（c6）：未构建的新检出上没有二进制——判绿是
# 撒谎（成功路径根本没验），判红是把「没构建」当缺陷。故抛 Skipped：逐条打印理由
# （含期望路径）、计入 SKIP 计数、不计入通过数、汇总另打 ⚠ 行。
def check_e2e_hive_ok(root: str, tmp: str, fusedir: str) -> tuple[bool, str]:
    binexe = _hive_bin(root)
    if not os.path.isfile(binexe):
        raise Skipped(
            "成功趟未执行：hive 二进制缺失，期望路径 %s（未构建的新检出 ⇒ 先在 hive/ 下 "
            "`cargo build --release`，或用环境变量 HIVE_EXE 指向可用二进制）"
            "——跳过**不计入通过数**（失败趟 E2E-HIVE 已照旧执行并通过）" % binexe)
    jobs = os.path.join(tmp, "hivejobs")
    os.makedirs(jobs, exist_ok=True)
    ctx = os.path.join(tmp, PROBE_CTX_OK_NAME)
    with open(ctx, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(PROBE_CTX_OK_BODY)
    extra = dict(_hive_extra(tmp))
    extra["HIVE_EXE"] = binexe                  # 真二进制：只作 alloc-id 的载体，见上方安全前提
    env = _env_clean(root, fusedir, extra)
    before = _pool_listing(root)                # 在役池快照（只读；c5 的前后比对基线）
    lines = [
        _rpc(1, "initialize", {}),
        _rpc(None, "notifications/initialized"),
        _rpc(2, "tools/list", {}),
        _rpc(3, "tools/call", {"name": "hive_spawn", "arguments": {
            "model": "probe-model", "user_prompt": PROBE_ZH,
            "identity": PROBE_SLOTS["identity"], "task": PROBE_SLOTS["task"],
            "unit": PROBE_SLOTS["unit"], "context_files": [ctx]}}),
    ]
    rc, out, err = _talk([sys.executable, "-m", "hive.hive_mcp.mcp_server"],
                         env, lines, root)
    objs, why = _frames(out)
    if objs is None:
        return False, "rc=%d 组帧非法：%s stderr=%r" % (rc, why, err[-200:])
    init = _find(objs, 1)
    if not (isinstance(init, dict)
            and ((init.get("result") or {}).get("serverInfo") or {}).get("name")
            == "hive-mcp"):
        return False, "initialize 握手异常：rc=%d objs=%s" % (rc, str(objs)[:200])
    sp = _payload(_find(objs, 3) or {})
    jid = sp.get("job_id") or ""
    jdir = os.path.join(jobs, jid) if jid else ""
    bad = []
    if not (sp.get("ok") is True):
        bad.append("ok 非 true（分配未跑通；失败路径那趟的判据不得顶替成功趟）：%s"
                   % str(sp)[:220])
    if not (jid and PROBE_ID_RE.match(jid) and jid.startswith(PROBE_ID_PREFIX)):
        bad.append("job_id 非四槽中文形态 h_…_…_…_NNNN（期望前缀 %r）：%r"
                   % (PROBE_ID_PREFIX, jid))
    if not (jid and os.path.isdir(jdir)
            and os.path.dirname(os.path.abspath(jdir)) == os.path.abspath(jobs)
            and _under(jdir, tmp)
            and not _under(jdir, os.path.join(root, "hive", "jobs"))):
        bad.append("任务目录落在守卫自己的临时池（c5 自证）不成立："
                   "jid=%r jdir=%r tmp=%r" % (jid, jdir, tmp))
    if os.path.abspath(sp.get("jobs_dir") or "") != os.path.abspath(jobs):
        bad.append("响应 jobs_dir 未回显临时池：%r" % (sp.get("jobs_dir"),))
    if sp.get("slots") != PROBE_SLOTS:
        bad.append("四槽未逐字节回显（期望 %r）：%r" % (PROBE_SLOTS, sp.get("slots")))
    if (sp.get("serve") or {}).get("started") is False:
        pass
    else:
        bad.append("serve.started 非 False（真 exe 下**不得**拉起 serve）：%r"
                   % (sp.get("serve"),))
    spec = None
    if jid:
        try:
            with open(os.path.join(jdir, "spec.json"), encoding="utf-8") as fh:
                spec = json.load(fh)
        except (OSError, ValueError) as e:
            bad.append("spec.json 不可读（%s）：%s" % (os.path.join(jdir, "spec.json"), e))
    if isinstance(spec, dict):
        if spec.get("user_prompt") != PROBE_ZH:
            bad.append("spec.user_prompt 中文未逐字节往返：%r" % (spec.get("user_prompt"),))
        if spec.get("context_files") != [ctx]:
            bad.append("spec.context_files 中文路径未逐字节往返：%r"
                       % (spec.get("context_files"),))
    if _pool_listing(root) != before:
        bad.append("在役池清单发生变化（c5 违规）：%r → %r"
                   % (before, _pool_listing(root)))
    if rc != 0:
        bad.append("进程未正常下线 rc=%d stderr=%r" % (rc, err[-200:]))
    if "UnicodeEncodeError" in err.decode("utf-8", "replace"):
        bad.append("stderr 出现 UnicodeEncodeError")
    if bad:
        return False, "；".join(bad)[:600]
    return True, ("rc=0 帧数=%d job_id=%s（真 exe=%s）任务目录落临时池 %s、"
                  "serve.started=False、中文逐字节往返（slots+spec.json）"
                  % (len(objs), jid, os.path.basename(binexe), jobs))


# 生效条件：root 为被判仓面；读 `<root>/scripts/test_utf8_boot_guard.py` 的 AST——`_CHECKS` 的注册 id 集合含 E2E-HIVE 与 E2E-HIVE-OK、模块定义了 PASS_FUNCS 两个函数、且 check_e2e_hive_ok 的**源码语段**里齐备 SUCCESS_BODY_TOKENS；全过返回 (True, 说明)，缺任一返回 (False, 缺失清单)。
#
# 为什么要有这条（d1 ④）：两条趟都是**判据**，而「把成功趟悄悄删掉」在本守卫里曾经是
# 无法察觉的（删掉判据 ⇒ 它就不再产生红项）。本判据把「两趟还在不在」变成一条可红的
# 事实，读的是**被判根的那份源码**（定点变异在临时物化副本上改同一路径 ⇒ 变异可生效）。
# 查法用 AST 取 `check_e2e_hive_ok` 的源码语段再查子串——**不在整文件查子串**：锚点
# 字面量本身写在 SUCCESS_BODY_TOKENS 常量里，整文件查会被常量自身满足（自我指涉假绿）。
def check_e2e_hive_passes(root: str, _tmp: str, _fusedir: str) -> tuple[bool, str]:
    ap = os.path.join(root, GUARD_REL.replace("/", os.sep))
    if not os.path.isfile(ap):
        return False, "自我锚读不到本守卫源码：%s（判据面不可达 ⇒ fail-closed）" % ap
    try:
        with open(ap, encoding="utf-8", errors="replace") as fh:
            src = fh.read()
        tree = ast.parse(src, filename=GUARD_REL)
    except (OSError, SyntaxError) as e:
        return False, "本守卫源码不可读/不可解析（%s）：%s: %s" % (ap, type(e).__name__, e)
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    ids = set()
    for n in ast.walk(tree):
        if (isinstance(n, ast.Assign)
                and any(getattr(t, "id", None) == "_CHECKS" for t in n.targets)):
            for el in getattr(n.value, "elts", []):
                if (isinstance(el, ast.Tuple) and el.elts
                        and isinstance(el.elts[0], ast.Constant)):
                    ids.add(el.elts[0].value)
    miss = ["注册项 %s" % i for i in PASS_IDS if i not in ids]
    miss += ["函数 %s()" % f for f in PASS_FUNCS if f not in funcs]
    if "check_e2e_hive_ok" in funcs:
        body = ast.get_source_segment(src, funcs["check_e2e_hive_ok"]) or ""
        miss += ["成功趟断言骨架 %r" % t for t in SUCCESS_BODY_TOKENS if t not in body]
    if miss:
        return False, "两趟不齐备（缺 %s）——判据面已漂移或成功趟被删" % "、".join(miss)
    return True, ("注册项 %s 与函数 %s 齐备；成功趟断言骨架 %d 项全在（源码：%s）"
                  % (sorted(ids & set(PASS_IDS)), list(PASS_FUNCS),
                     len(SUCCESS_BODY_TOKENS), GUARD_REL))


# 生效条件：root 为被判仓面、tmp 为临时面；清空两个 env 且不带 -X utf8 起 md_cg stdio MCP，喂 initialize + 中文 cg write，返回 (是否通过, 说明)——断言 rc=0、逐行 JSON、serverInfo=mdcg-mcp、中文 write 回 ok/moved_to、无 UnicodeEncodeError。
def check_e2e_mdcg(root: str, tmp: str, fusedir: str) -> tuple[bool, str]:
    env = _env_clean(root, fusedir, _mdcg_extra(tmp))
    lines = [
        _rpc(1, "initialize", {}),
        _rpc(None, "notifications/initialized"),
        _rpc(3, "tools/call", {"name": "cg", "arguments": {
            "op": "write", "content": PROBE_ZH}}),
    ]
    rc, out, err = _talk([sys.executable, "-m", "md_cg.mcp_server"],
                         env, lines, root)
    objs, why = _frames(out)
    if objs is None:
        return False, "rc=%d 组帧非法：%s stderr=%r" % (rc, why, err[-200:])
    init = _find(objs, 1)
    if not (isinstance(init, dict)
            and ((init.get("result") or {}).get("serverInfo") or {}).get("name")
            == "mdcg-mcp"):
        return False, "initialize 握手异常：rc=%d objs=%s" % (rc, str(objs)[:200])
    pay = _payload(_find(objs, 3) or {})
    if not ("ok" in pay or "moved_to" in pay):
        return False, "中文 write 响应缺 ok/moved_to：%s" % str(pay)[:200]
    if rc != 0:
        return False, "进程未正常下线 rc=%d stderr=%r" % (rc, err[-200:])
    if "UnicodeEncodeError" in err.decode("utf-8", "replace"):
        return False, "stderr 出现 UnicodeEncodeError"
    return True, "rc=0 帧数=%d 中文 write 被受理（%s）" % (
        len(objs), "ok" if "ok" in pay else "moved_to")


# ---------------------------------------------------------------- 判据 ②/③/④：重启次数与退出通道

# 生效条件：root/tmp/fusedir 给出时，清空两个 env 且不带 -X utf8 起 hive stdio MCP 并统计解释器启动数，返回 (是否通过, 说明)——断言恰好 2 次启动（首次 + 一次重启）且熔断未触发、组帧正常。
def check_once(root: str, tmp: str, fusedir: str) -> tuple[bool, str]:
    cnt = os.path.join(tmp, "once.count")
    env = _env_clean(root, fusedir, _hive_extra(tmp), counter=cnt)
    rc, out, err = _talk([sys.executable, "-m", "hive.hive_mcp.mcp_server"],
                         env, [_rpc(1, "initialize", {})], root)
    n = _count_lines(cnt)
    if rc == FUSE_EXIT:
        return False, "解释器启动数触顶熔断（疑似递归重启）n=%d" % n
    if n != 2:
        return False, ("解释器启动 %d 次 ≠ 2（首次 + 一次重启；>2 即递归，<2 即未重启）"
                       " rc=%d" % (n, rc))
    objs, why = _frames(out)
    if objs is None or _find(objs, 1) is None:
        return False, "重启后组帧异常：%s rc=%d" % (why or "缺 id=1 响应", rc)
    note = "（宿主默认 UTF-8 模式，已追加 PYTHONUTF8=0 构造「未开」现场）" \
        if _host_utf8_default() else ""
    return True, "启动 2 次（首次未开 → 重启一次后已开）%s" % note


# 生效条件：root/tmp/fusedir 给出时，以 -X utf8 起 hive stdio MCP 并统计解释器启动数，返回 (是否通过, 说明)——断言恰好 1 次启动（模式已开 ⇒ 不重启）且 rc=0。
def check_noop(root: str, tmp: str, fusedir: str) -> tuple[bool, str]:
    cnt = os.path.join(tmp, "noop.count")
    env = _env_clean(root, fusedir, _hive_extra(tmp), counter=cnt)
    env.pop("PYTHONUTF8", None)                  # -X utf8 下无需强制关
    rc, _out, err = _talk([sys.executable, "-X", "utf8",
                           "-m", "hive.hive_mcp.mcp_server"], env, [], root)
    n = _count_lines(cnt)
    if n != 1 or rc != 0:
        return False, "启动 %d 次（期望 1，模式已开不得重启）rc=%d stderr=%r" % (
            n, rc, err[-160:])
    return True, "启动 1 次（-X utf8 ⇒ 早退分支，不重启）"


# 生效条件：root/tmp/fusedir 给出时，以 LINGSHU_UTF8_NO_REEXEC=1 清空两个 env 起 hive 入口，返回 (是否通过, 说明)——断言 rc=FAILFAST_EXIT、stderr 为合法 UTF-8 且含 -X utf8 / PYTHONUTF8 可执行指引、启动数仍为 1（确未重启）。
def check_failfast(root: str, tmp: str, fusedir: str) -> tuple[bool, str]:
    cnt = os.path.join(tmp, "failfast.count")
    env = _env_clean(root, fusedir, _hive_extra(tmp), counter=cnt)
    env[NO_REEXEC_ENV] = "1"
    rc, _out, err = _talk([sys.executable, "-m", "hive.hive_mcp.mcp_server"],
                          env, [], root)
    try:
        text = err.decode("utf-8")
    except UnicodeDecodeError as e:
        return False, "指引不是 UTF-8 字节（控制台代码页漂移）：%s" % e
    n = _count_lines(cnt)
    if rc != FAILFAST_EXIT:
        return False, "退出码 %d ≠ %d（fail-fast 未生效）" % (rc, FAILFAST_EXIT)
    miss = [tok for tok in ("-X utf8", "PYTHONUTF8", NO_REEXEC_ENV)
            if tok not in text]
    if miss:
        return False, "指引缺可执行要素 %s：%r" % (miss, text[:200])
    if n != 1:
        return False, "fail-fast 路径居然重启了（启动 %d 次）" % n
    return True, "rc=2 且指引含 -X utf8 / PYTHONUTF8 / %s，启动 1 次（未重启）" % (
        NO_REEXEC_ENV)


# 生效条件：root/tmp/fusedir 给出时，在临时面写一个「照七个真入口最小形态调用助手」的探针并清空两个 env 起它，返回 (是否通过, 说明)——断言探针自身与它派生的孙进程都看到 PYTHONUTF8=1 与 PYTHONIOENCODING=utf-8。
def check_env_child(root: str, tmp: str, fusedir: str) -> tuple[bool, str]:
    probe = os.path.join(tmp, "probe_entry.py")
    src = (
        "# -*- coding: utf-8 -*-\n"
        "import os\n"
        "import subprocess\n"
        "import sys\n"
        "sys.path.insert(0, %r)\n"
        "from utf8_boot import ensure_utf8\n"
        "ensure_utf8(__file__)\n"
        "code = ('import os,sys;'\n"
        "        'print(\"GRAND\", os.environ.get(\"PYTHONUTF8\"),'\n"
        "        '      os.environ.get(\"PYTHONIOENCODING\"), sys.stdout.encoding)')\n"
        "r = subprocess.run([sys.executable, '-c', code], capture_output=True)\n"
        "sys.stdout.write(r.stdout.decode('utf-8', 'replace'))\n"
        "sys.stdout.write('SELF %%d %%r %%r\\n' %% (\n"
        "    sys.flags.utf8_mode, os.environ.get('PYTHONUTF8'),\n"
        "    os.environ.get('PYTHONIOENCODING')))\n" % (root,)
    )
    with open(probe, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(src)
    env = _env_clean(root, fusedir)
    rc, out, err = _talk([sys.executable, probe], env, [], root)
    text = out.decode("utf-8", "replace")
    if "GRAND 1 utf-8" not in text:
        return False, "孙进程未继承 UTF-8 面：rc=%d out=%r err=%r" % (
            rc, text[:200], err[-160:])
    if "SELF 1 '1' 'utf-8'" not in text:
        return False, "本进程未同时满足「模式已开 + env 已置」：%r" % text[:200]
    return True, "本进程 utf8_mode=1 且 env 已置；孙进程 GRAND 1 utf-8（继承面成立）"


# ---------------------------------------------------------------- 判据 ⑤：入口锚点

# 生效条件：root 给出时逐个核对 ENTRIES——文件存在、含约束注释锚/import 锚/调用锚，且调用锚行号小于该文件首个模块级 def 行号；锚缺失抛 AnchorMiss（退出码 2），顺序倒置返回 (False, 说明)；全过返回 (True, 说明)。
def check_anchor(root: str, _tmp: str, _fusedir: str) -> tuple[bool, str]:
    order_bad = []
    for rel, role in ENTRIES:
        ap = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(ap):
            raise AnchorMiss("入口文件不存在：%s（%s）" % (rel, role))
        with open(ap, encoding="utf-8", errors="replace") as fh:
            src = fh.read()
        lines = src.split("\n")
        if ANCHOR_COMMENT not in src:
            raise AnchorMiss("入口缺约束块注释锚：%s" % rel)
        if ANCHOR_NOTE not in src:
            raise AnchorMiss("入口缺约束说明锚（%r）：%s" % (ANCHOR_NOTE, rel))
        if ANCHOR_IMPORT not in src:
            raise AnchorMiss("入口缺助手 import 锚：%s" % rel)
        if ANCHOR_CALL not in src:
            raise AnchorMiss("入口未调用助手（缺 %r 锚）：%s" % (ANCHOR_CALL, rel))
        call_at = next(i for i, ln in enumerate(lines, 1)
                       if ln.strip() == ANCHOR_CALL)
        defs = [i for i, ln in enumerate(lines, 1) if ln.startswith("def ")]
        if defs and call_at > defs[0]:
            order_bad.append("%s（调用在第 %d 行，首个 def 在第 %d 行）"
                             % (rel, call_at, defs[0]))
    if order_bad:
        return False, "调用锚晚于模块级 def（不再「早于一切 I/O」）：" + "；".join(order_bad)
    return True, "%d 个入口全部：注释锚 + import 锚 + 调用锚齐备，且调用早于首个 def" % len(ENTRIES)


# ---------------------------------------------------------------- 判据 ⑥：依赖方向

# 生效条件：root 给出时以 AST 核对 utf8_boot.py 只 import 标准库白名单、且不含 md_cg/hive/scripts/compiler/swarm；再以独立解释器实测 import 助手后这三个包名均不在 sys.modules；返回 (是否通过, 说明)。
def check_depdir(root: str, _tmp: str, fusedir: str) -> tuple[bool, str]:
    ap = os.path.join(root, HELPER_REL)
    if not os.path.isfile(ap):
        raise AnchorMiss("助手不存在：%s" % HELPER_REL)
    with open(ap, encoding="utf-8", errors="replace") as fh:
        tree = ast.parse(fh.read(), filename=HELPER_REL)
    got = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            got.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                got.add(node.module.split(".")[0])
            else:
                got.add("<relative>")
    bad = sorted(got - HELPER_ALLOWED_IMPORTS)
    if bad:
        return False, "助手 import 面越界（须纯 stdlib、零 md_cg 依赖）：%s" % bad
    code = ("import sys;sys.path.insert(0, %r);import utf8_boot;"
            "print(','.join(sorted(m for m in %r if m in sys.modules)))"
            % (root, sorted(FORBIDDEN_IMPORTS)))
    env = _env_clean(root, fusedir)
    p = subprocess.run([sys.executable, "-c", code], cwd=root, env=env,
                       capture_output=True, timeout=120)
    gotmods = p.stdout.decode("utf-8", "replace").strip()
    if gotmods:
        return False, "import 助手后这些包进入了 sys.modules：%s" % gotmods
    return True, "助手 import 面 = %s（纯 stdlib）；import 后 md_cg/hive/scripts 均不在 sys.modules" % sorted(got)


# ---------------------------------------------------------------- 判据 ⑦：指引可执行（F2）

# 生效条件：rel 为入口相对路径、tmp 为临时面；hive/ 下的入口取 hive 隔离面、md_cg/ 下取 md_cg 隔离面、其余（scripts/）取空覆盖；返回该入口探测用的 env 覆盖 dict。
def _extra_for(rel: str, tmp: str) -> dict:
    """按入口归属取隔离面覆盖（与 E2E 同口径，绝不触在役根）。"""
    if rel.startswith("hive/"):
        return dict(_hive_extra(tmp))
    if rel.startswith("md_cg/"):
        return dict(_mdcg_extra(tmp))
    return {}


# 生效条件：entry_src 为入口绝对路径、form 为 ("m", 模块名) 或 ("f", None)、argv_extra 为可迭代追加参数；返回含 -X utf8 的 argv 列表（= 指引应当印出的那条命令）。
def _launch_argv(entry_src: str, form: tuple, argv_extra=()) -> list:
    """指引命令的 argv（`-X utf8` + `-m <模块>` 或 `<入口路径>` + 追加参数）。"""
    head = ([sys.executable, "-X", "utf8", "-m", form[1]] if form[0] == "m"
            else [sys.executable, "-X", "utf8", entry_src])
    return head + list(argv_extra)


# 生效条件：entry_src 为入口绝对路径、form 为 ("m", 模块名) 或 ("f", None)；返回该入口**真实接入形态**的 argv（**不带** -X utf8 —— 采 fail-fast 指引必须在「解释器未开 UTF-8 模式」的现场，带了 -X utf8 就永远采不到指引）。
def _entry_argv(entry_src: str, form: tuple) -> list:
    """入口的真实接入形态 argv（无 -X utf8）：采指引 / 复现「宿主直连」现场用。"""
    if form[0] == "m":
        return [sys.executable, "-m", form[1]]
    return [sys.executable, entry_src]


# 生效条件：text 为 fail-fast 指引文本；返回其中以 GUIDE_CMD_PREFIX 开头那一行**去掉该前缀后的命令串**（即 `-X utf8` 之后的形态，如 `-m md_cg.mcp_server` 或入口绝对路径），无该行返回 None。
def _parse_guide_cmd(text: str):
    """从指引文本里取出「可照抄的那条命令」——只认 python -X utf8 那一行。"""
    for ln in text.splitlines():
        ln = ln.strip()
        if ln.startswith(GUIDE_CMD_PREFIX):
            return ln[len(GUIDE_CMD_PREFIX):].strip()
    return None


# 生效条件：kind/needle 给出、rc/out/err 为探针进程读数；先判 stderr 无 ImportError/ModuleNotFoundError/No module named，再按 kind（rpc|stderr|stdout|rc0）判定启动迹象；返回 (是否通过, 说明)。
def _startup_ok(kind: str, needle, rc: int, out: bytes, err: bytes) -> tuple[bool, str]:
    """「非 ImportError 的启动迹象」判定（指引命令真能跑起来的唯一口径）。"""
    etext = err.decode("utf-8", "replace")
    for bad in ("ImportError", "ModuleNotFoundError", "No module named"):
        if bad in etext:
            tail = etext.strip().splitlines()[-1:]
            return False, "启动即 %s：%r" % (bad, tail)
    if kind == "rpc":
        objs, why = _frames(out)
        if objs is None:
            return False, "喂 initialize 后组帧非法：%s" % why
        name = (((_find(objs, 1) or {}).get("result") or {})
                .get("serverInfo", {}).get("name"))
        if name != needle:
            return False, "握手 serverInfo=%r ≠ %r" % (name, needle)
        return True, "initialize 握手 %s" % needle
    if kind == "stderr":
        if needle not in etext:
            return False, "stderr 未见 %r：%r" % (needle, etext[:160])
        return True, "stderr 见 %r（rc=%d）" % (needle, rc)
    if kind == "stdout":
        otext = out.decode("utf-8", "replace")
        if needle not in otext:
            return False, "stdout 未见 %r：%r" % (needle, otext[:160])
        return True, "stdout 见 %r（rc=%d，%d 字节）" % (needle, rc, len(out))
    if kind == "rc0":
        if rc != 0:
            return False, "rc=%d ≠ 0，stderr=%r" % (rc, etext[:160])
        return True, "rc=0 且产出 %d 字节" % len(out)
    return False, "未知探针类型 %r" % (kind,)


# 生效条件：tmp 与 tag 给出时返回一个**全新**的计数文件路径（先删后返回）——每次子运行必须各用一份：共用一份会让计数跨子运行累加到熔断上限，正常入口也会被误杀。
def _fresh_counter(tmp: str, tag: str) -> str:
    """为一次子运行分配独立计数文件（熔断判据的作用域 = 一次子运行）。"""
    p = os.path.join(tmp, "cnt_%s.txt" % tag)
    if os.path.exists(p):
        os.remove(p)
    return p


# 生效条件：root 为被判仓面、tmp 为临时面；逐个入口 (a) 以真实接入形态 + NO_REEXEC 采 fail-fast 指引、(b) 断言指引形态与接入形态一致、(c) 真跑该命令并断言有非 ImportError 启动迹象；返回 (是否通过, 说明)。
def check_guide(root: str, tmp: str, fusedir: str) -> tuple[bool, str]:
    """⑦（F2）指引必须可照抄：印出的命令真能跑起来，形态与真实接入形态一致。

    熔断（必读）：采指引与探针**都带独立计数熔断**——「采指引」在 NO_REEXEC 被变异
    破坏时（M4）会退化成「真跑入口」（实测：`scripts/run_tests.py` 会真跑整个套件，
    并拉起源仓副本里的守卫自己 ⇒ 递归跑套件、孤儿进程堆积），「探针」在「幂等被破坏」
    的变异下（M2）会无限自重启。故两处都挂计数熔断：任何失控的解释器启动在第 N 次
    被 sitecustomize `os._exit(97)` 截断，且两处各用**独立**计数文件（共用会把正常
    入口也累加到熔断线）。
    """
    fails, oks = [], []
    for rel, _role in ENTRIES:
        sp = ENTRY_LAUNCH[rel]
        form, entry_src = sp["form"], os.path.join(root, rel.replace("/", os.sep))
        extra = _extra_for(rel, tmp)
        tag = rel.replace("/", "_").replace(".", "")
        env = _env_clean(root, fusedir, {**extra, NO_REEXEC_ENV: "1"},
                         counter=_fresh_counter(tmp, tag + "_h"), fuse=3)
        # 采指引必须走**真实接入形态且不带 -X utf8**（否则 utf8 模式已开、早退分支先命中，
        # 永远采不到指引）；超时收紧到 60s——采不到就该红，绝不能把入口的活干一遍。
        rc, _o, err = _talk(_entry_argv(entry_src, form), env, [], root, timeout=60)
        text = err.decode("utf-8", "replace")
        cmd = _parse_guide_cmd(text)
        if rc != FAILFAST_EXIT or cmd is None:
            fails.append("%s：未取到 fail-fast 指引（rc=%d）%r" % (rel, rc, text[:160]))
            continue
        want = ("-m %s" % form[1]) if form[0] == "m" else entry_src
        if cmd != want:
            fails.append("%s：指引形态不符——印 %r，应 %r" % (rel, cmd, want))
            continue
        feed = ([_rpc(1, "initialize", {}), _rpc(None, "notifications/initialized")]
                if sp["probe"][0] == "rpc" else [])
        env2 = _env_clean(root, fusedir, extra,
                         counter=_fresh_counter(tmp, tag + "_p"))
        rc2, out2, err2 = _talk(_launch_argv(entry_src, form, sp["argv"]), env2,
                                feed, root, timeout=300)
        good, why = _startup_ok(sp["probe"][0], sp["probe"][1], rc2, out2, err2)
        if not good:
            fails.append("%s：指引命令跑不起来（%r）——%s" % (rel, cmd, why))
            continue
        oks.append("%s→%r %s" % (rel.split("/")[-1], cmd, why))
    if fails:
        return False, "；".join(fails)
    return True, "七入口指引均可照抄并真跑通：%s" % "；".join(oks)


# ---------------------------------------------------------------- 判据 ⑧：被 import 不得重启（F6）

#: F6 探针源码（守卫生成，非仓库源码）：逐个 import 七入口，逐个打印 IMPORTED 标记。
#: 换 `<ROOT>`/`<CASES>` 占位而非 %-格式——源码里自带 `%` 字面量，用 % 会踩转义坑。
_IMPORT_PROBE_SRC = '''# -*- coding: utf-8 -*-
"""F6 探针（守卫生成）：import 七入口，解释器**只许启动一次**（被 import 绝不重启）。"""
import importlib
import importlib.util
import sys

sys.path.insert(0, <ROOT>)
for _tag, _kind, _val in <CASES>:
    if _kind == "mod":
        importlib.import_module(_val)
    else:
        _s = importlib.util.spec_from_file_location("utf8guard_scripts_run_tests", _val)
        _m = importlib.util.module_from_spec(_s)
        _s.loader.exec_module(_m)
    sys.stdout.write("IMPORTED %s\\n" % _tag)
    sys.stdout.flush()
sys.stdout.write("DONE utf8flag=%d\\n" % sys.flags.utf8_mode)
'''


# 生效条件：root/tmp/fusedir 给出时，以计数 sitecustomize 起一个导入七入口的探针进程，返回 (是否通过, 说明)——断言启动数恰为 1、七个 IMPORTED 标记齐备、DONE 出现（进程未被重启吞掉）。
def check_import_no_restart(root: str, tmp: str, fusedir: str) -> tuple[bool, str]:
    """⑧（F6）：import 七入口之一不得导致解释器重启（启动计数 1、标记齐备）。"""
    probe = os.path.join(tmp, "import_probe.py")
    cases = [(tag, kind, (os.path.join(root, val.replace("/", os.sep))
                          if kind == "file" else val))
             for tag, kind, val in IMPORT_CASES]
    src = (_IMPORT_PROBE_SRC.replace("<ROOT>", repr(root))
           .replace("<CASES>", repr(cases)))
    with open(probe, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(src)
    cnt = os.path.join(tmp, "import.count")
    env = _env_clean(root, fusedir, {**_hive_extra(tmp), **_mdcg_extra(tmp)},
                     counter=cnt)
    rc, out, err = _talk([sys.executable, probe], env, [], root, timeout=300)
    n = _count_lines(cnt)
    text = out.decode("utf-8", "replace").replace("\r\n", "\n")
    if n != 1:
        return False, ("import 七入口导致解释器启动 %d 次（期望 1：被 import 绝不重启）"
                       " rc=%d stderr=%r" % (n, rc, err[-200:]))
    miss = [tag for tag, _k, _v in IMPORT_CASES
            if ("IMPORTED %s\n" % tag) not in text]
    if miss or "DONE" not in text:
        return False, ("进程被重启吞掉：缺标记 %s（rc=%d out=%r）"
                       % (miss or "DONE", rc, text[-200:]))
    return True, "启动 1 次；七入口全部 import 成功且进程未重启（%d 个标记齐备）" % len(IMPORT_CASES)


# ---------------------------------------------------------------- 判据 ⑨：三流显式传递（F3）

#: STREAMS 探针源码（守卫生成，非仓库源码）。拓扑要点两条：
#:   ① 本进程把 sys.stdin/stdout/stderr 换成三个**普通文件对象**（不是 fd 0/1/2）——只有这样
#:      「助手把三条流显式传给重启出的子进程」才有可观测差异；
#:   ② 重定向**只在本进程首次执行**，并置 env 标记 `UTF8GUARD_STREAMS_ONCE` 供重启出的子
#:      进程继承——子进程**不得**自己重开这三个文件。否则「漏传」会被子进程的自愈掩盖：
#:      实测（2026-09-29）子进程若自行重开文件，M9/M10/M11 三项定点变异全绿（判据对丢失
#:      不敏感）——那正是本条判据存在的理由，故必须用标记把自愈路径堵死。
_STREAMS_PROBE_SRC = '''# -*- coding: utf-8 -*-
"""F3 探针（守卫生成）：三流换成非 fd 0/1/2 的文件对象后，做一次二进制的 stdio 组帧往返。"""
import json
import os
import sys

if not os.environ.get("UTF8GUARD_STREAMS_ONCE"):
    os.environ["UTF8GUARD_STREAMS_ONCE"] = "1"       # 重启出的子进程按 env 继承本标记
    sys.stdin = open(os.environ["UTF8GUARD_REQ"], "r", encoding="utf-8", newline="")
    sys.stdout = open(os.environ["UTF8GUARD_OUT"], "w", encoding="utf-8", newline="")
    sys.stderr = open(os.environ["UTF8GUARD_ERR"], "w", encoding="utf-8", newline="")
sys.path.insert(0, <ROOT>)
from utf8_boot import ensure_utf8
ensure_utf8(__file__)
for _line in sys.stdin:
    _line = _line.strip()
    if not _line:
        continue
    _req = json.loads(_line)
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": _req.get("id"),
                                 "result": {"echo": _req.get("params", {}).get("zh"),
                                            "utf8": sys.flags.utf8_mode}},
                                ensure_ascii=False) + "\\n")
    sys.stdout.flush()
sys.stderr.write("PROBE-STDERR %s\\n" % (<ZH>,))
'''


# 生效条件：root/tmp/fusedir 给出时，起 STREAMS 探针（清空两 env、不带 -X utf8、三流为非 fd 0/1/2 的文件对象），返回 (是否通过, 说明)——断言子进程把组帧与 stderr 都写回**显式传入的**三条流，且宿主管道里没有它们的痕迹。
def check_streams(root: str, tmp: str, fusedir: str) -> tuple[bool, str]:
    """⑨（F3）行为差分：漏传任一条标准流 ⇒ 组帧写不回显式传入的流 ⇒ 判据转红。"""
    req = os.path.join(tmp, "streams.req")
    outp = os.path.join(tmp, "streams.out")
    errp = os.path.join(tmp, "streams.err")
    probe = os.path.join(tmp, "streams_probe.py")
    src = (_STREAMS_PROBE_SRC.replace("<ROOT>", repr(root))
           .replace("<ZH>", repr(PROBE_ZH)))
    with open(probe, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(src)
    with open(req, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_rpc(7, "echo", {"zh": PROBE_ZH}) + "\n")
    env = _env_clean(root, fusedir, {"UTF8GUARD_REQ": req, "UTF8GUARD_OUT": outp,
                                     "UTF8GUARD_ERR": errp})
    rc, host_out, host_err = _talk([sys.executable, probe], env, [], root, timeout=180)
    raw = open(outp, "rb").read() if os.path.isfile(outp) else b""
    objs, why = _frames(raw)
    if objs is None:
        return False, ("子进程未把组帧写回**显式传入的 stdout**（%s；宿主 rc=%d）——"
                       "重启必须显式传递三条标准流" % (why, rc))
    # 注意：不能用 _payload()——那是 tools/call 专用（读 result.content[0].text），
    # 本探针回的是 {"result": {"echo": …, "utf8": …}} 直取值。
    pay = ((_find(objs, 7) or {}).get("result") or {})
    if pay.get("echo") != PROBE_ZH or pay.get("utf8") != 1:
        return False, ("显式传入的 stdout 里组帧不完整：%r（期望 echo=%r utf8=1）；"
                       "探针 stderr 文件=%r；宿主 rc=%d stderr=%r"
                       % (pay, PROBE_ZH,
                          (open(errp, "rb").read()[:300]
                           if os.path.isfile(errp) else None), rc, host_err[-200:]))
    etxt = open(errp, "rb").read().decode("utf-8", "replace") if os.path.isfile(errp) else ""
    if "PROBE-STDERR" not in etxt:
        return False, ("子进程未把 stderr 写回**显式传入的 stderr**：%r" % etxt[:160])
    if b'"jsonrpc"' in host_out or b"PROBE-STDERR" in host_err:
        return False, ("组帧/标记出现在**宿主管道**而非显式传入的流——子进程用的是继承来的 "
                       "fd 0/1/2（三流被漏传）")
    return True, ("非 fd 0/1/2 拓扑下组帧往返成功：echo=%r utf8=1、stderr 标记落显式流、"
                  "宿主管道零痕迹" % PROBE_ZH)


# ---------------------------------------------------------------- 判据登记表

_CHECKS = (
    ("E2E-HIVE-OK", "① 成功路径（真 exe + 临时池）：ok=true + job_id 四槽中文形态（c4/c5）",
     check_e2e_hive_ok),
    ("E2E-HIVE", "① stdio MCP 端到端组帧（hive 失败路径：探针 exe 缺席 + 中文逐字节往返）",
     check_e2e_hive_fail),
    ("E2E-PASSES", "① 两趟齐备自我锚（成功趟/失败趟的注册与断言骨架都在被判根源码里）",
     check_e2e_hive_passes),
    ("E2E-MDCG", "① stdio MCP 端到端组帧（md_cg，清空 env 无 -X utf8）", check_e2e_mdcg),
    ("ONCE", "② 只重启一次（解释器启动计数恰好 2）", check_once),
    ("FAILFAST", "③ LINGSHU_UTF8_NO_REEXEC ⇒ 非 0 退出 + 可执行指引 + 未重启", check_failfast),
    ("NOOP", "④ -X utf8（模式已开）⇒ 不重启（计数 1）", check_noop),
    ("ENV-CHILD", "④ PYTHONUTF8/PYTHONIOENCODING 置入 env 供子进程继承", check_env_child),
    ("ANCHOR", "⑤ 七入口锚点：调用存在 + 早于一切模块级 def", check_anchor),
    ("DEPDIR", "⑥ 依赖方向：纯 stdlib，md_cg 不入 sys.modules", check_depdir),
    ("GUIDE", "⑦ 七入口 fail-fast 指引可照抄：起进程真跑通（F2）", check_guide),
    ("IMPORT", "⑧ import 七入口不得重启解释器（F6，计数 1）", check_import_no_restart),
    ("STREAMS", "⑨ 三流显式传递：非 fd 0/1/2 拓扑下组帧必须落显式流（F3）", check_streams),
)


# 生效条件：root/tmp/fusedir 与 skip 集合给出时逐个执行 _CHECKS（跳过 skip），Skipped 记为该判据「skip」（保留理由）、AnchorMiss 记为该判据红且置锚命标记；返回 (结果字典 id→(状态,说明), 是否存在锚命)——状态 ∈ {"ok","red","skip"}，skip **不算通过也不算违例**。
def _run_checks(root: str, tmp: str, fusedir: str,
                skip: tuple = ()) -> tuple[dict, bool]:
    res, miss = {}, False
    for cid, desc, fn in _CHECKS:
        if cid in skip:
            continue
        try:
            ok, detail = fn(root, tmp, fusedir)
            state = "ok" if ok else "red"
        except Skipped as e:
            state, detail = "skip", str(e)
        except AnchorMiss as e:
            state, detail, miss = "red", "ANCHOR-MISS：%s" % e, True
        except Exception as e:                            # noqa: BLE001
            state, detail = "red", "判据自身异常 %s：%s" % (type(e).__name__, e)
        res[cid] = (state, detail)
    return res, miss


# 生效条件：结果字典给出时返回退出码——任一项红且存在锚命 ⇒ 2；任一项红 ⇒ 1；否则 0（skip 不影响退出码：跳过不是违例，但它的存在由汇总的 ⚠ 行与计数显式暴露，绝不静默）。
def _exit_of(res: dict, miss: bool) -> int:
    if any(state == "red" for state, _d in res.values()):
        return 2 if miss else 1
    return 0


# ---------------------------------------------------------------- 判据 ⑦：定点变异自证

# 生效条件：src 含 old 恰好一次时返回替换结果，否则抛 AnchorMiss（变异注入点漂移，不得静默不变异）。
def _sub(src: str, old: str, new: str, what: str) -> str:
    if src.count(old) != 1:
        raise AnchorMiss("变异注入点漂移（%s）：%r 出现 %d 次" % (what, old, src.count(old)))
    return src.replace(old, new, 1)


# 生效条件：srcs 为 {相对路径: 文本} 时把 utf8_boot.reexec_argv 的 -m 分支关掉（重启退化为直跑文件），返回新 srcs。
def _mut_m_form_off(srcs: dict) -> dict:
    rel = HELPER_REL
    srcs[rel] = _sub(srcs[rel],
                     '    if name:\n'
                     '        return [sys.executable, "-X", "utf8", "-m", name, *sys.argv[1:]]\n',
                     "    if False:\n"
                     '        return [sys.executable, "-X", "utf8", "-m", name, *sys.argv[1:]]\n',
                     "M1")
    return srcs


# 生效条件：srcs 给出时把助手「模式已开即早退」的条件取反（幂等被破坏），返回新 srcs。
def _mut_early_return_inverted(srcs: dict) -> dict:
    rel = HELPER_REL
    srcs[rel] = _sub(srcs[rel], "    if sys.flags.utf8_mode:\n",
                     "    if not sys.flags.utf8_mode:\n", "M2")
    return srcs


# 生效条件：srcs 给出时把 _set_child_env 改成空实现（第四项失效），返回新 srcs。
def _mut_env_not_set(srcs: dict) -> dict:
    rel = HELPER_REL
    srcs[rel] = _sub(srcs[rel],
                     '    os.environ["PYTHONUTF8"] = "1"\n'
                     '    os.environ["PYTHONIOENCODING"] = "utf-8"\n',
                     "    return\n", "M3")
    return srcs


# 生效条件：srcs 给出时把 LINGSHU_UTF8_NO_REEXEC 的真值判定钉死为 False（显式退出通道失效），返回新 srcs。
def _mut_no_reexec_ignored(srcs: dict) -> dict:
    rel = HELPER_REL
    srcs[rel] = _sub(srcs[rel],
                     '    return (os.environ.get(name) or "").strip().lower() in _TRUTHY',
                     "    return False", "M4")
    return srcs


# 生效条件：srcs 给出时删掉 hive/exec.py 的助手调用行（只留 import 锚），返回新 srcs。
def _mut_anchor_call_removed(srcs: dict) -> dict:
    rel = "hive/exec.py"
    srcs[rel] = _sub(srcs[rel], ANCHOR_CALL + "\n", "", "M5")
    return srcs


# 生效条件：srcs 给出时把 hive/serve_start.py 的助手调用挪到该文件首个 def 之后，返回新 srcs。
def _mut_anchor_order_drift(srcs: dict) -> dict:
    rel = "hive/serve_start.py"
    lines = srcs[rel].split("\n")
    idx = [i for i, ln in enumerate(lines) if ln.strip() == ANCHOR_CALL]
    if len(idx) != 1:
        raise AnchorMiss("变异注入点漂移（M6）：%r 行数 %d" % (ANCHOR_CALL, len(idx)))
    del lines[idx[0]]
    first_def = next(i for i, ln in enumerate(lines) if ln.startswith("def "))
    lines.insert(first_def + 1, "    " + ANCHOR_CALL)
    srcs[rel] = "\n".join(lines)
    return srcs


# 生效条件：srcs 给出时让助手反向 import md_cg（依赖方向破坏），返回新 srcs。
def _mut_depdir(srcs: dict) -> dict:
    rel = HELPER_REL
    srcs[rel] = _sub(srcs[rel], "import locale\n",
                     "import locale\nimport md_cg  # 定点变异：依赖方向\n", "M7")
    return srcs


# 生效条件：srcs 给出时把助手内部常量 _TRUTHY 全量改名（功能等价的无关改动——假阳性对照），返回新 srcs。
def _mut_green_control(srcs: dict) -> dict:
    rel = HELPER_REL
    src = srcs[rel]
    if src.count("_TRUTHY") < 2:
        raise AnchorMiss("变异注入点漂移（M8）：_TRUTHY 出现 %d 次" % src.count("_TRUTHY"))
    srcs[rel] = src.replace("_TRUTHY", "_TRUTHY_SET")
    return srcs


# 生效条件：srcs 给出时把助手重启调用里的 `stdout=sys.stdout,` 去掉（三流之一漏传），返回新 srcs。
def _mut_no_stdin(srcs: dict) -> dict:
    rel = HELPER_REL
    srcs[rel] = _sub(srcs[rel], "stdin=sys.stdin, stdout=sys.stdout,",
                     "stdout=sys.stdout,", "M9-stdin")
    return srcs


# 生效条件：srcs 给出时把助手重启调用里的 `stdin=sys.stdin,` 去掉（三流之一漏传），返回新 srcs。
def _mut_no_stdout(srcs: dict) -> dict:
    rel = HELPER_REL
    srcs[rel] = _sub(srcs[rel], "stdin=sys.stdin, stdout=sys.stdout,",
                     "stdin=sys.stdin,", "M10-stdout")
    return srcs


# 生效条件：srcs 给出时把助手重启调用里的 `stderr=sys.stderr` 去掉（三流之一漏传，改传 None），返回新 srcs。
def _mut_no_stderr(srcs: dict) -> dict:
    rel = HELPER_REL
    srcs[rel] = _sub(srcs[rel], "stderr=sys.stderr)", "stderr=None)", "M11-stderr")
    return srcs


# 生效条件：srcs 给出时把 launch_hint 的 -m 判别关掉（指引退回印入口文件路径——F2 的原始缺陷形态），返回新 srcs。
def _mut_guide_no_m(srcs: dict) -> dict:
    rel = HELPER_REL
    srcs[rel] = _sub(srcs[rel], '    if name:\n        return "-m %s" % name\n',
                     '    if False:\n        return "-m %s" % name\n', "M12")
    return srcs


# 生效条件：srcs 给出时把「调用方非进程入口则不重启」的闸门打开失效（还原 F6 之前的静默重启行为），返回新 srcs。
def _mut_import_gate_off(srcs: dict) -> dict:
    rel = HELPER_REL
    srcs[rel] = _sub(srcs[rel], "    if not _caller_is_process_entry():\n",
                     "    if not True:\n", "M13")
    return srcs


# ------------------------------------------------- ④ 成功趟（c4/c5/c6）的三处定点变异

# 生效条件：srcs 给出时把**成功趟**从本守卫里删掉（`_CHECKS` 注册项改 id + 函数名退场 = 修前的单趟形态），返回新 srcs。
def _mut_success_pass_dropped(srcs: dict) -> dict:
    """④：「成功趟被删掉」——注册 id 与函数名同时退场，两趟退回单趟。

    为什么改这两处而不是整段删代码：改完仍是**语法合法**的源码（`E2E-PASSES` 的
    AST 解析不会先炸），红项才归因于「两趟不齐备」这一条判据本身，而不是文件读不来。

    为什么两个 needle 都用**拼接**写（`'("E2E-HIVE-' + 'OK",'`）：本函数自己就在被判
    源码里（守卫读的是本位件），字面量写成整串会让它在本文件里**出现两次** ⇒
    `_sub` 的「恰好一次」判据直接报漂移；与本文件 `SUCCESS_BODY_TOKENS` 的自我指涉
    防法同源（那里靠「只查函数语段」，这里靠「不写出整串」）。
    """
    rel = GUARD_REL
    srcs[rel] = _sub(srcs[rel], '("E2E-HIVE-' + 'OK",',
                     '("E2E-HIVE-OK-RETIRED",', "S1-注册项")
    srcs[rel] = _sub(srcs[rel], "def check_e2e_hive_" + "ok(",
                     "def _dropped_check_e2e_hive_ok(", "S1-函数名")
    return srcs


# 生效条件：srcs 给出时让生产面 `_alloc_job_id` 在分配之前直接抛错（成功路径结构性不可达），返回新 srcs。
def _mut_alloc_blocked(srcs: dict) -> dict:
    """④：生产面**成功路径**被切断——成功趟必须转红（证明它不是空判据）。

    `_alloc_job_id` 是 python 面唯一的分配入口（`_submit` 调它）；在它开头抛
    SubmitError 即「真 exe 在盘也没用」的形态。锚点选 `if not os.path.isfile(exe)` 的
    **下一行**（`raise SubmitError(`）：`_ensure_serve` 里也有一对同形的
    `exe = _exe_path()` / `if not os.path.isfile(exe):`，不分行到下一句就会撞上
    「恰好一次」判据（本变异第一次实测即因此报漂移，见头注实测记录）。失败趟不受影响：
    它的探针带一个**不存在**的中文 context 路径，`_t_spawn` 的 context 存在性闸在
    `_submit` **之前**就返回 ok=False（故失败趟仍绿——两趟的判别力彼此独立，正是分两趟
    的意义）。
    """
    rel = "hive/hive_mcp/mcp_server.py"
    srcs[rel] = _sub(srcs[rel],
                     "    if not os.path.isfile(exe):\n        raise SubmitError(\n",
                     '    raise SubmitError("定点变异：分配通道被切断")\n'
                     "    if not os.path.isfile(exe):\n        raise SubmitError(\n",
                     "S2")
    return srcs


# 生效条件：srcs 给出时在 `hive/hive_mcp/mcp_server.py` 里做**与判据无关的改名**（模级函数 `_exe_path` 全量改名，判据一字不动），返回新 srcs——假阳性对照（必须全绿）。
def _mut_green_control_mcp(srcs: dict) -> dict:
    """假阳性对照（④ 的判据面所在文件）：无关改名必须**全绿**（本守卫不误报）。"""
    rel = "hive/hive_mcp/mcp_server.py"
    n = srcs[rel].count("_exe_path")
    if n < 2:
        raise AnchorMiss("变异注入点漂移（S3）：_exe_path 出现 %d 次" % n)
    srcs[rel] = srcs[rel].replace("_exe_path", "_hive_exe_path")
    return srcs


# 生效条件：srcs 给出时让 `_t_spawn` 的 context 闸**不再回显**请求里的路径（失败趟的证据被抹掉），返回新 srcs。
def _mut_ctx_echo_gone(srcs: dict) -> dict:
    """失败趟的判别力：`ok=false` 的**证据**是原因里逐字节回显的中文路径。

    生产面不再回显 ⇒ 失败趟必须转红（否则「中文出参逐字节正确」这条在本面就没有
    可证伪的载体）。这条同时补上评审报告点名的缺口（`docs/eval/编码面前置_入口自保证
    UTF8与文本open守卫_v1.0.md` §七-Q3：`E2E-HIVE` 在原变异表里**无任何单点变异能打红**
    ——补法即此处：单点改生产面的证据回显）。成功趟不受影响（它给的 context 文件存在，
    该闸不触发）——两趟判别力独立，正是分两趟的意义。
    """
    rel = "hive/hive_mcp/mcp_server.py"
    srcs[rel] = _sub(srcs[rel],
                     '            return {"ok": False, "error": f"context 文件不存在: {path}"}\n',
                     '            return {"ok": False, "error": "context 文件不存在"}\n',
                     "S4")
    return srcs


#: 定点变异表：id / 说明 / 变异函数 / 预期红项集 / 预期退出码
#:   预期红项集是**实测钉死**的事实（不是愿望）：每项都实跑过、读下红项与退出码后写死；
#:   实现或判据任何一侧漂移都会让「恰好命中」不成立 ⇒ ANCHOR-MISS。
#:
#: ④ 新增四处（S1–S4）的**实测读数**（2026-09-30 本机，命令
#: `python -X utf8 scripts/test_utf8_boot_guard.py`，rc=0、**30/30**
#: = 正向 13/13 + 定点变异 17/17；耗时 27.6s）：
#:   S1 删掉成功趟（注册 id 改 id + 函数名退场）→ 红项恰 {E2E-PASSES}、退出码 1；
#:   S2 生产面 `_alloc_job_id` 在分配前抛错 → 红项恰 {E2E-HIVE-OK}、退出码 1
#:      （证明成功趟**不是空判据**：生产面成功路径一断它必红）；
#:   S3 假阳性对照（`_exe_path` 全量改名、判据一字不动）→ 红项 ∅、退出码 0；
#:   S4 失败趟的证据被抹掉（context 闸不再回显路径）→ 红项恰 {E2E-HIVE}、退出码 1
#:      （补上评审报告 §七-Q3 点名的缺口：原表里没有任何单点变异能打红 E2E-HIVE）。
#:   二进制缺席时的 SKIP 路径另实测于**临时物化副本**（副本无 `hive/target`）：rc=0、
#:   `[skip] E2E-HIVE-OK`（打印期望路径）、失败趟仍绿、S2 记入跳过清单、汇总
#:   `28/30 通过（正向 12/13 + 定点变异 16/17）；显式 SKIP 2 项（不计入通过数）` ＋ ⚠ 行
#:   （脚本 `<TEMP>/guardA_skip.py`，非仓内件）。
#:   留痕（不得静默改判据）：S1/S2 的第一版曾因**注入点撞车**报漂移——S1 的 needle
#:   整串写在变异函数里（本文件即被判源码）⇒ 出现 2 次；S2 的锚点与 `_ensure_serve`
#:   同形 ⇒ 也 2 次。修法见两个变异函数的 docstring（拼接法 + 锚到下一句）。
_MUTATIONS = (
    ("M1-no-m-form", "重启 argv 丢掉 -m 模块语义（直跑文件）",
     _mut_m_form_off, frozenset({"E2E-MDCG"}), 1),
    ("M2-early-return-inverted", "utf8 已开也不早退（幂等被破坏，递归被熔断截断）",
     _mut_early_return_inverted,
     frozenset({"ONCE", "NOOP", "FAILFAST", "ENV-CHILD", "GUIDE", "STREAMS"}), 1),
    ("M3-env-not-set", "第四项失效：不置 PYTHONUTF8/PYTHONIOENCODING",
     _mut_env_not_set, frozenset({"ENV-CHILD"}), 1),
    ("M4-no-reexec-ignored", "显式退出通道失效（NO_REEXEC 被忽略）",
     _mut_no_reexec_ignored, frozenset({"FAILFAST", "GUIDE"}), 1),
    ("M5-anchor-call-removed", "入口不再调用助手（锚点缺失 ⇒ ANCHOR-MISS）",
     _mut_anchor_call_removed, frozenset({"ANCHOR", "GUIDE"}), 2),
    ("M6-anchor-order-drift", "调用锚被挪到首个 def 之后（顺序漂移）",
     _mut_anchor_order_drift, frozenset({"ANCHOR", "GUIDE"}), 1),
    ("M7-dep-direction", "助手反向 import md_cg（依赖方向破坏）",
     _mut_depdir, frozenset({"DEPDIR"}), 1),
    ("M8-green-control", "无关改名（假阳性对照：必须全绿）",
     _mut_green_control, frozenset(), 0),
    ("M9-stream-stdin-dropped", "重启不传 stdin（组帧的输入侧）",
     _mut_no_stdin, frozenset({"STREAMS"}), 1),
    ("M10-stream-stdout-dropped", "重启不传 stdout（组帧的输出侧）",
     _mut_no_stdout, frozenset({"STREAMS"}), 1),
    ("M11-stream-stderr-dropped", "重启不传 stderr（诊断侧同样不得丢）",
     _mut_no_stderr, frozenset({"STREAMS"}), 1),
    ("M12-guide-no-m-reuse", "指引不复用 -m 判别（退回印入口文件路径）",
     _mut_guide_no_m, frozenset({"GUIDE"}), 1),
    ("M13-import-gate-off", "被 import 也重启（F6 前的静默重启行为）",
     _mut_import_gate_off, frozenset({"IMPORT"}), 1),
    # ---- ④ 成功趟（c4/c5/c6）的三处：删趟 / 生产面切断 / 无关改名假阳性 ----
    ("S1-success-pass-dropped", "成功趟被删掉（注册 id 与函数名退场 ⇒ 两趟退回单趟）",
     _mut_success_pass_dropped, frozenset({"E2E-PASSES"}), 1),
    ("S2-alloc-path-cut", "生产面 `_alloc_job_id` 在分配前抛错（真 exe 在手也分配不出去）",
     _mut_alloc_blocked, frozenset({"E2E-HIVE-OK"}), 1),
    ("S3-green-control-mcp", "无关改名（hive_mcp/mcp_server.py 的 `_exe_path` 全量改名，"
                             "判据一字不动）——假阳性对照：必须全绿",
     _mut_green_control_mcp, frozenset(), 0),
    ("S4-ctx-echo-gone", "失败趟的证据被抹掉（context 闸不再回显请求里的中文路径）",
     _mut_ctx_echo_gone, frozenset({"E2E-HIVE"}), 1),
)


# 生效条件：root 给出时返回「git 追踪面 + 未忽略的未追踪面」过滤 _MATERIALIZE_SKIP 后的相对路径列表（git 不可用则回落到 wal​k 枚举，同样过滤）；返回列表按字典序。
def _materialize_list(root: str) -> list:
    names = []
    try:
        p = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root, capture_output=True,
            env={**os.environ, "PYTHONUTF8": "1"})
        if p.returncode == 0:
            names = [x for x in p.stdout.decode("utf-8", "replace").split("\0") if x]
    except OSError:
        names = []
    if not names:
        for cur, subs, files in os.walk(root):
            subs[:] = [d for d in subs if d != "__pycache__"]
            for f in files:
                names.append(os.path.relpath(os.path.join(cur, f), root)
                             .replace("\\", "/"))
    keep = [n for n in names if not n.startswith(_MATERIALIZE_SKIP)]
    return sorted(set(keep))


# 生效条件：src_root 为源仓面、dst 为目标目录；把 _materialize_list(src_root) 的每个文件逐字节复制到 dst（保留目录结构），返回复制件数；源文件缺失（被 git 记录但已删）跳过。
def _materialize(src_root: str, dst: str) -> int:
    n = 0
    for rel in _materialize_list(src_root):
        ap = os.path.join(src_root, rel.replace("/", os.sep))
        if not os.path.isfile(ap):
            continue
        dp = os.path.join(dst, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dp), exist_ok=True)
        shutil.copyfile(ap, dp)
        n += 1
    return n


# 生效条件：sandbox/fusedir 与变异表给出时，逐个变异「注入 → 跑全量判据（不含 ⑦ 自身）→ 还原」，断言红项集与退出码**恰好**等于预期；返回 (失败清单, 报告行, 跳过清单)；注入点漂移或结果不符即进失败清单（外层按 ANCHOR-MISS 处置）；预期红项含 E2E-HIVE-OK 而二进制不在盘时该变异记入跳过清单（成功趟未执行 ⇒ 该变异无法判定，**不得**算通过也不算失败）。
def run_mutations(sandbox: str, fusedir: str) -> tuple[list, list, list]:
    miss: list = []
    rep: list = []
    skipped_mut: list = []
    cache_dir = tempfile.mkdtemp(prefix="utf8guard_mut_")
    try:
        for mid, desc, fn, want_red, want_exit in _MUTATIONS:
            orig = {}
            # 注意：GUARD_REL 也在内——成功趟的定点变异改的正是**本守卫自己的源码**
            # （`E2E-PASSES` 读被判根的那一份），不进这份清单就还原不了，会污染后续变异。
            files = [HELPER_REL, GUARD_REL] + [rel for rel, _r in ENTRIES]
            for rel in files:
                ap = os.path.join(sandbox, rel.replace("/", os.sep))
                with open(ap, encoding="utf-8", errors="replace") as fh:
                    orig[rel] = fh.read()
            if "E2E-HIVE-OK" in want_red and not os.path.isfile(_hive_bin(sandbox)):
                skipped_mut.append(
                    "%s（%s）：预期红项含 E2E-HIVE-OK，但 hive 二进制不在盘"
                    "（期望 %s）⇒ 成功趟未执行，本变异无法判定——**不计通过也不算失败**"
                    % (mid, desc, _hive_bin(sandbox)))
                continue
            touched = False
            try:
                srcs = dict(orig)
                srcs = fn(srcs)
                for rel, src in srcs.items():
                    if src != orig.get(rel):
                        touched = True
                        with open(os.path.join(sandbox, rel.replace("/", os.sep)),
                                  "w", encoding="utf-8", newline="\n") as fh:
                            fh.write(src)
                if not touched:
                    raise AnchorMiss("变异 %s 未改动任何字节（注入点漂移）" % mid)
                tmp = tempfile.mkdtemp(prefix="utf8guard_case_", dir=cache_dir)
                res, amiss = _run_checks(sandbox, tmp, fusedir,
                                         skip=("MUTATIONS",))
                got_red = frozenset(cid for cid, (st, _d) in res.items() if st == "red")
                got_exit = _exit_of(res, amiss)
                if got_red != want_red or got_exit != want_exit:
                    miss.append(
                        "定点变异 %s（%s）：预期红项 %s/退出码 %d，实测红项 %s/退出码 %d；"
                        "明细 %s" % (mid, desc, sorted(want_red), want_exit,
                                     sorted(got_red), got_exit,
                                     {k: v[1][:120] for k, v in res.items()
                                      if v[0] != "ok"}))
                else:
                    rep.append("%s（%s）：红项 %s / 退出码 %d —— 与预期恰好一致"
                               % (mid, desc, sorted(got_red) or "∅", got_exit))
            except AnchorMiss as e:
                miss.append("定点变异 %s 注入失败：%s" % (mid, e))
            finally:
                for rel, src in orig.items():
                    with open(os.path.join(sandbox, rel.replace("/", os.sep)),
                              "w", encoding="utf-8", newline="\n") as fh:
                        fh.write(src)
    finally:
        shutil.rmtree(cache_dir, ignore_errors=True)
    return miss, rep, skipped_mut


# ---------------------------------------------------------------- 主流程

# 生效条件：无入参；在临时熔断面与临时隔离面内跑 _CHECKS（含 ⑦ 定点变异自证，--no-mutations 时跳过），逐项打印，按 _exit_of 与变异命中情况返回退出码（0/1/2）。
def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description="入口自保证 UTF-8 守卫（A 项）")
    ap.add_argument("--no-mutations", action="store_true",
                    help="跳过 ⑦ 定点变异自证（快速正向跑）")
    args = ap.parse_args(argv)
    try:                                  # 重定向到文件时也逐行可见（长跑自证型守卫的现场可观测性）
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass

    with tempfile.TemporaryDirectory(prefix="utf8guard_") as tmp:
        fusedir = os.path.join(tmp, "_fuse")
        os.makedirs(fusedir, exist_ok=True)
        with open(os.path.join(fusedir, "sitecustomize.py"), "w",
                  encoding="utf-8", newline="\n") as fh:
            fh.write(_FUSE_SRC)
        work = os.path.join(tmp, "case")
        os.makedirs(work, exist_ok=True)

        selfdir = os.path.join(tempfile.gettempdir(), "md_cg_servers")
        before = set(os.listdir(selfdir)) if os.path.isdir(selfdir) else set()

        print("守卫面：%s（助手 %s）" % (ROOT, HELPER_REL))
        print("现场：清空 PYTHONUTF8/PYTHONIOENCODING、不带 -X utf8%s"
              % ("；宿主默认 UTF-8 模式 ⇒ 追加 PYTHONUTF8=0 强制构造「未开」态"
                 if _host_utf8_default() else ""))
        res, amiss = _run_checks(ROOT, work, fusedir, skip=("MUTATIONS",))
        npass = sum(1 for st, _d in res.values() if st == "ok")
        nskip = sum(1 for st, _d in res.values() if st == "skip")
        for cid, desc, _fn in _CHECKS:
            if cid not in res:
                continue
            state, detail = res[cid]
            if state == "skip":
                print("  [skip] %-10s %s（**未计入通过数**）" % (cid, desc))
                print("        %s" % detail)
                continue
            print("  [%s] %-10s %s" % ("ok" if state == "ok" else "红", cid, desc))
            if detail:
                print("        %s" % detail)

        mut_miss: list = []
        mut_rep: list = []
        mut_skip: list = []
        if not args.no_mutations:
            sandbox = os.path.join(tmp, "sandbox")
            os.makedirs(sandbox, exist_ok=True)
            copied = _materialize(ROOT, sandbox)
            print("\n⑦ 定点变异自证（临时物化仓面 %d 文件，绝不改工作树）" % copied)
            mut_miss, mut_rep, mut_skip = run_mutations(sandbox, fusedir)
            for line in mut_rep:
                print("  [ok] %s" % line)
            for line in mut_skip:
                print("  [skip] %s" % line)
            for line in mut_miss:
                print("  [红] %s" % line)

        cleaned = _clean_selfreports(selfdir, before)
        print("\n残留自报文件清理：%d 件（%s）" % (cleaned, selfdir))

        total = len(res) + len(_MUTATIONS if not args.no_mutations else ())
        ok_count = npass + (len(mut_rep) if not args.no_mutations else 0)
        nskip_total = nskip + len(mut_skip)
        print("===== SUMMARY %d/%d 通过（正向 %d/%d + 定点变异 %d/%d）%s"
              % (ok_count, total, npass, len(res),
                 len(mut_rep) if not args.no_mutations else 0,
                 len(_MUTATIONS) if not args.no_mutations else 0,
                 "" if not nskip_total else
                 "；显式 SKIP %d 项（**不计入通过数**）" % nskip_total))

        if mut_miss:
            print("✖ ANCHOR-MISS（定点变异未按预期命中，判据面已脱钩）")
            return 2
        if any(st == "red" for st, _d in res.values()):
            print("✖ 存在违例")
            return _exit_of(res, amiss)
        if nskip_total:
            print("⚠ 无违例，但有 %d 项**显式 SKIP**（未计入通过数，逐项理由见上）——"
                  "本守卫不因 SKIP 判绿，也不把「没跑成」冒充成「跑过了」" % nskip_total)
        print("✔ 无违例：入口自保证 UTF-8 的 %d 条判据成立（正向 %d ok / %d skip），"
              "定点变异恰好命中预期项数（%d 处，另 %d 处按上列理由跳过）"
              % (len(_CHECKS), npass, nskip, len(mut_rep), len(mut_skip)))
        return 0


_FUSE_SRC = '''# -*- coding: utf-8 -*-
"""utf8 守卫熔断（自证用，非仓库源码）：每次解释器启动记一笔，超上限即熔断退出。"""
import os
import sys

_path = os.environ.get("UTF8GUARD_COUNT")
if _path:
    try:
        with open(_path, "a", encoding="utf-8") as _fh:
            _fh.write("%d\\n" % os.getpid())
    except OSError:
        pass
    try:
        with open(_path, encoding="utf-8") as _fh:
            _n = sum(1 for _line in _fh)
    except OSError:
        _n = 0
    try:
        _cap = int(os.environ.get("UTF8GUARD_FUSE") or "6")
    except ValueError:
        _cap = 6
    if _n >= _cap:
        sys.stderr.write("utf8guard-fuse: 解释器启动数 %d 达上限 %d，熔断退出\\n"
                         % (_n, _cap))
        sys.stderr.flush()
        os._exit(97)
'''


if __name__ == "__main__":
    sys.exit(main())
