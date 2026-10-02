# -*- coding: utf-8 -*-
"""test_issue39_utf8_stdio.py · Windows 控制台代码页下 stdio MCP 中文必炸的守卫（issue #39）

现场（外部用户实测，issue #39）：Windows 控制台代码页（GBK/CP936）下，md_cg 的
stdio MCP server 写中文必失败——宿主按 UTF-8 发来的中文参数被按 GBK 解码：
· ``gbk:strict`` → 读侧直接 ``UnicodeDecodeError``（本守卫实弹注入的形态，已实证
  「中文标题：编码守卫」的 UTF-8 字节序列按 GBK 严格解码必非法）；
· ``surrogateescape`` → 解出代理对 ``\\udcXX``，``_j()``（ensure_ascii=False）
  按 UTF-8 编码时抛 ``UnicodeEncodeError: surrogates not allowed``。
两种形态整条请求同亡；写英文正常，用户难自查。桥层 0.4.10 已在
``src/lib/mdcg_client.ts`` 的 ``mdcgChildEnv()`` 注入 ``PYTHONUTF8=1``，但只覆盖
DSH 桥路径——Claude Code / code CLI 直接 mcp.json 接入不经桥，仍踩。

修复（本守卫的红绿两态锚点）：``md_cg/mcp_server.py`` 与
``hive/hive_mcp/mcp_server.py``（同族全修）各加模块级 ``_force_utf8_stdio()``，
并在 ``main()`` **首行**调用——进程内把 stdio 三流 reconfigure 成
``utf-8``/``errors="replace"``，是对桥层 PYTHONUTF8=1 的纵深补位；``replace``
保证坏字节最多丢字符、不炸整条请求。

实弹形态：subprocess spawn ``[sys.executable, "-m", "md_cg.mcp_server"]``
（cwd=仓根，**不带** ``-X utf8``），env 显式设 ``PYTHONIOENCODING=gbk:strict``
模拟 CP936 控制台；按行分隔 JSON-RPC（initialize → notifications/initialized →
tools/call cg {op:"write", content:中文}）。断言：响应行是合法 JSON、write 响应
不含 ``UnicodeEncodeError`` 且返回 ``ok``/``moved_to`` 字段。修复前此面红
（进程在读侧崩、响应行缺失），修复后绿。

hive 面**两趟**（契约 c4/c5/c6；id 契约 v2 之后 `_submit` 改调 Rust 侧
``hive alloc-id`` 分配 id，故两趟口径不同、缺一不可）：
  · **失败趟（保留）**：``HIVE_EXE`` 指向**不存在的探针路径**，请求带一个不存在的
    中文相对 context 路径 ⇒ 断言 ``ok=false`` 且原因**回显该中文路径**（逐字节相等）
    ——中文入参已过 JSON 解码与四槽闸（四槽闸在 context 闸之前）。
  · **成功趟（c4 补回）**：``HIVE_EXE`` 指向**真实 release 二进制**
    （``hive/target/release/hive.exe``，或环境变量 ``HIVE_EXE`` 覆盖），
    ``HIVE_JOBS_DIR`` 指向**本守卫自己的临时池**，喂四槽中文参数 spawn ⇒ 断言
    ``ok=true``、``job_id`` 非空且形如 ``h_…_…_…_NNNN``（四段中文形态）、任务目录
    落在临时池内、中文逐字节往返（spec.json 与响应 slots）。**二进制缺失**
    （未构建的新检出）⇒ 本趟**显式 SKIP 并打印期望路径**，不计入通过数；失败趟照旧
    必须通过。
  · 安全前提（真 exe 为什么安全，码上必须写明）：``alloc-id`` 是**纯分配**通道
    （Rust ``job::alloc_job_id`` 只 ``fs::create_dir`` 落池，不读不启动 serve）；
    且 ``HIVE_CONFIG`` 钉在不存在路径 ⇒ ``_ensure_serve`` 的拉起分支在
    ``serve_start.start()`` 的 ``load_config`` 即返回失败（serve_start.py:462-464），
    Popen 那一步不执行——成功趟据此断言 ``serve.started is False`` 自证（失败趟的
    响应是 context 闸的拒收，本就**没有** serve 字段，故该断言只落在成功趟）。

隔离纪律：MDCG_ROOT/MDCG_STATE_ROOT/MDCG_DATA_ROOT/MDCG_AUX_ROOT/
MDCG_TENANT_REGISTRY/HIVE_JOBS_DIR/HIVE_CONFIG 全部指向 tempfile.mkdtemp 临时
目录（登记表指向不存在的临时路径=空表回落），身份走既有豁免面
``MDCG_LEGACY_ENV_AUTH=1``（env 直连 designer，零令牌、不回落真实 ~/.mdcg），
MDCG_SUSTAIN=0 关常驻循环；成功趟的池是**指针**（HIVE_JOBS_DIR）指向的临时目录，
并前后比对在役 ``hive/jobs`` 清单（只读）自证零触碰；finally rmtree——绝不触真实
令牌库与真实数据目录。

自检 floor：实弹断言低于 LIVE_FLOOR 视为失败——防止「spawn 面失效 → 假绿」。
SKIP 单列计数（PASS/FAIL/SKIP 三态）：跳过项计入输出与汇总，**绝不计入通过数**。

④ 的两趟与定点变异自证（d1；**在临时物化副本上做，绝不改工作树**）
------------------------------------------------------------------------
本守卫不持变异自证装置（它的判据面是「真起进程喂 JSON-RPC」，逐条变异要另建一套
物化 + 重跑装置）；改法是把「两趟是否还在」变成**一条判据**（3'·两趟齐备，见
`_two_passes_reason`：AST 读**仓面那一份**源码的 `main()` 语段查判据骨架），再用
一次性脚本在临时物化副本上实测三种态（**实测命令与读数，2026-09-30 本机**）：

  python -X utf8 <TEMP>/guardb_mut.py     # 物化 1163 文件的副本，副本不含 hive/target

  A 原样副本（副本无二进制 ⇒ 成功趟 SKIP，失败趟照旧跑）
      rc=0 · 13 passed / 0 failed / **1 skipped**(live=7) · 打印
      `[SKIP] 2e–2k 成功路径…` 与 `⚠ 显式 SKIP 1 项（未计入通过数）`
  B **删掉成功趟**（2' 段整段退场，5375 字节）
      rc=1 · 11 passed / **2 failed** · 红项恰为
      {`3'·两趟齐备`（缺 binexe/ok is True/2g/started is False/2j 五处骨架）, `4b`}
  C 假阳性对照（失败趟内局部改名 `serr`→`serr_text`，判据一字不动）
      rc=0 · 13 passed / 0 failed / 1 skipped —— 不误报

⚠ 与仓库其它守卫的差别（如实声明）：A/C 两态里成功趟是 SKIP 而非真跑（副本无构建
产物）——**真跑**那条由仓面直跑覆盖（本机 rc=0、20 passed、live=13，成功趟真跑过）。
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile

# ---------------------------------------------------------------- 入口自保证 UTF-8
# 约束（工作纪律第 15 条，d2）：本调用必须在**任何文件/库 I/O 之前**——本守卫也是
# 一个进程入口（`python -X utf8 -m md_cg.test_issue39_utf8_stdio` / 直跑文件），它的
# 判据描述与判据名都含中文：在清空 PYTHONUTF8/PYTHONIOENCODING 的 cp936 控制台上
# 直跑，未接助手时第一条 `print` 即 UnicodeEncodeError 崩、rc=1 且**后半判据根本没
# 跑**——守卫守的就是这件事，自己不自保证说不过去。形态照 scripts/run_tests.py 的
# 最小写法（助手在仓根，不是 md_cg 包目录）；被 import（本模块非 __main__）时助手只
# 置子进程继承面、绝不重启/退出（F6）。
_UTF8_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _UTF8_ROOT not in sys.path:
    sys.path.insert(0, _UTF8_ROOT)
from utf8_boot import ensure_utf8  # noqa: E402

ensure_utf8(__file__)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE_FLOOR = 2          # 实弹断言下限（md_cg 面 ≥1 + hive 面 ≥1）
PROBE = "中文标题：编码守卫"   # UTF-8 字节按 GBK strict 解码必非法（红态机制，见头注）
#: 探针用的中文**相对** context 路径（必不存在）：`_t_spawn` 的 context 存在性闸会把
#: 它逐字节回显进 error ⇒ 一次调用同时证明「中文入参已被受理」与「中文出参编码正确」。
PROBE_CTX = "探针_中文上下文_无此文件.md"
#: 成功趟（c4）的四槽（前三槽；第四槽「编号」由 Rust 侧分配器给出）与
#: **存在**的中文 context 文件（逐字节往返的第二载体：它会被写进 spec.json）
PROBE_SLOTS = {"identity": "探针端", "task": "编码守卫", "unit": "验证单元"}
PROBE_ID_PREFIX = "h_探针端_编码守卫_验证单元_"
PROBE_CTX_OK_NAME = "探针_中文上下文_存在.md"
#: hive 二进制相对路径（成功趟用真二进制；见 `_hive_bin` 的两级查找）
HIVE_BIN_REL = ("hive", "target", "release",
                "hive.exe" if os.name == "nt" else "hive")

#: 本守卫自身的仓内相对路径（`3'·两趟齐备` 这条自我锚读它——**读被判根的那一份**，
#: 不是内存里的活模块；故定点变异在临时物化副本上改它即可生效）
SELF_REL = "md_cg/test_issue39_utf8_stdio.py"
#: ④ 两趟齐备的**自我锚**：成功趟与失败趟在 `main()` 语段里必须出现的判据骨架。
#: 查法 = AST 取 `main` 的源码语段再查子串（见 `_two_passes_reason`）——**不在本常量处
#: 查**：这些字面量本身就在本常量里，若整文件查子串，删掉成功趟后锚点仍由常量自身满足
#: ⇒ 自我指涉假绿。取 `main()` 语段即把常量排除在外。
TWO_PASS_ANCHORS = (
    # 失败趟（原口径，**必须保留**）：ok=false 且原因回显中文 context 路径
    "2b 中文 hive_spawn 逐字节往返",
    'payload.get("ok") is False and PROBE_CTX in serr',
    "2d 拒面未落任何任务目录",
    # 成功趟（c4 补回）：真 exe + 临时池 + ok=true + 四槽中文形态 + 未拉 serve + 零触碰
    "binexe = _hive_bin()",
    'payload.get("ok") is True',
    "2g 任务目录落在守卫自己的临时池",
    '(payload.get("serve") or {}).get("started") is False',
    "2j 在役池零触碰",
)
#: 自我锚同时钉住的辅助函数面（删掉 `skip`/`_hive_bin` 即等于把 c4/c6 的手段拆掉）
TWO_PASS_FUNCS = ("skip", "_hive_bin", "_hive_env", "_pool_listing", "_under")

PASS, FAIL, LIVE, SKIP = 0, 0, 0, 0


def check(name, cond, detail="", live=False):
    global PASS, FAIL, LIVE
    if live:
        LIVE += 1
    if cond:
        PASS += 1
        print(f"  [ok] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def skip(name, reason):
    """显式跳过（c6）：计入输出与汇总，**不计入通过数**（三态：PASS/FAIL/SKIP）。"""
    global SKIP
    SKIP += 1
    print(f"  [SKIP] {name}\n         {reason}")


# 模拟 CP936 控制台前，先把父进程可能携带的「身份/路径/编码」注入面清干净——
# 守卫子进程只吃临时目录，绝不吃本机真实 ~/.mdcg / 真实 MDCG_ROOT。
_DIRTY_KEYS = (
    "MDCG_TOKEN", "MDCG_CLEARANCE", "MDCG_TENANT", "MDCG_TENANT_REGISTRY",
    "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_LEGACY_ENV_AUTH",
    "MDCG_LEGACY_ENV_ADMIN", "MDCG_SESSION", "DSH_SESSION_ID",
    "MDCG_HARNESS", "MDCG_UNIT", "MDCG_ROOT", "MDCG_STATE_ROOT",
    "MDCG_DATA_ROOT", "MDCG_AUX_ROOT", "MDCG_SUSTAIN", "MDCG_SUSTAIN_NAME",
    "MDCG_MCP_SURFACE", "MDCG_TOOL_FACE", "MDCG_ACTOR",
    "MDCG_VERIFIER_MODULES", "MDCG_HIVE_JOBS",
    "PYTHONUTF8", "PYTHONIOENCODING", "PYTHONLEGACYWINDOWSSTDIO",
    "HIVE_JOBS_DIR", "HIVE_CONFIG", "HIVE_EXE", "HIVE_API_KEY",
)


def _base_env(tmp: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _DIRTY_KEYS}
    env["PYTHONIOENCODING"] = "gbk:strict"     # 模拟 CP936 控制台（无 -X utf8）
    env["MDCG_SUSTAIN"] = "0"                  # 关常驻循环（线程面归零）
    env["MDCG_ACTOR"] = "issue39-guard"
    # 身份走既有豁免面：env 直连 designer（二次开关齐全），零令牌、不回落真实凭据面
    env["MDCG_LEGACY_ENV_AUTH"] = "1"
    env["MDCG_CAN_ADMIN"] = "1"
    env["MDCG_LEGACY_ENV_ADMIN"] = "1"
    _ = tmp
    return env


def _mdcg_env(tmp: str) -> dict:
    env = _base_env(tmp)
    env["MDCG_ROOT"] = os.path.join(tmp, "cgroot")
    env["MDCG_TENANT_REGISTRY"] = os.path.join(tmp, "_tenants_absent.json")
    env["MDCG_STATE_ROOT"] = os.path.join(tmp, "state")
    env["MDCG_DATA_ROOT"] = os.path.join(tmp, "data")
    # 子目录名不可取 "aux"：AUX 是 Windows 保留设备名，ntpath.abspath 经
    # GetFullPathNameW 会把末段 aux 解析成设备路径 \\.\aux（实测），导致
    # aux_root() 覆盖键静默失联——取名 auxroot 避开。
    env["MDCG_AUX_ROOT"] = os.path.join(tmp, "auxroot")
    return env


def _hive_env(tmp: str, exe: str | None = None) -> dict:
    """hive 面子进程 env。

    生效条件：exe 为 None（失败趟）⇒ HIVE_EXE 钉在**不存在的探针路径**（`_alloc_job_id`
    在 isfile 即抛显式 SubmitError）；exe 给定时（成功趟）⇒ HIVE_EXE 指向该**真实**
    二进制。两趟的 HIVE_CONFIG 一律指向不存在的路径：`_ensure_serve` 的拉起分支因此
    在 `serve_start.start()` 的 `load_config` 即返回失败（serve_start.py:462-464），
    Popen 那一步**不执行** ⇒ 真 exe 也绝不拉起在役 serve。HIVE_JOBS_DIR 一律指向本
    守卫自己的临时池。
    """
    env = _base_env(tmp)
    env["HIVE_JOBS_DIR"] = os.path.join(tmp, "hivejobs")
    # 指向不存在的配置与（缺省时）可执行文件：_ensure_serve 在 isfile 即返回，绝不拉起真 serve
    env["HIVE_CONFIG"] = os.path.join(tmp, "hive_config_absent.json")
    env["HIVE_EXE"] = exe or os.path.join(tmp, "no_such_hive.exe")
    return env


def _hive_bin() -> str:
    """成功趟用的**真实** hive 二进制（两级查找；不猜、不下载、不构建）。

    ① 环境变量 ``HIVE_EXE``（需 isfile）——使用者显式覆盖；
    ② 本仓 ``hive/target/release/hive[.exe]``——即它**期望存在**的那条路径：
       两级都不在时也返回它，供 SKIP 理由把期望路径原样打印出来（c6）。
    """
    env = os.environ.get("HIVE_EXE")
    if env and os.path.isfile(env):
        return env
    return os.path.join(ROOT, *HIVE_BIN_REL)


def _pool_listing() -> list | None:
    """在役 `hive/jobs` 的目录项排序清单（**只读**；不存在 ⇒ None）。

    c5 的自证面：成功趟前后各取一次，清单必须逐字节一致——守卫的池是 HIVE_JOBS_DIR
    指针指向的临时目录，在役池不该因本守卫增减任何一项。
    **排除在役 serve 的心跳产物**（`_serve*`：`_serve.json` / `_serve.log` /
    `_serve.tmp<pid>`——与 `scripts/test_utf8_boot_guard.py::_pool_listing` 同口径，
    该处 2026-10-01 已按同一归因修复）：心跳的原子写协议是 tmp→rename，
    `_serve.tmp<pid>` 存续窗口实测约 0.35s、占空比约一半（2026-10-02 探针 45s/448
    采样：含 `_serve*` 口径变化 62 次，排除后 0 次）——不排除则两个采样点之间必被
    闪现命中而假红（全量实测随机红，两次跑一红一绿）。排除后其余任何新增（含意外
    落池）照旧判违规——判据强度不变。
    """
    try:
        return sorted(n for n in os.listdir(os.path.join(ROOT, "hive", "jobs"))
                      if not n.startswith("_serve"))
    except OSError:
        return None


def _under(path: str, parent: str) -> bool:
    """path 是否落在 parent（含 parent 自身）之下（绝对路径比对）——临时池自证用。"""
    p, q = os.path.abspath(path), os.path.abspath(parent)
    return p == q or p.startswith(q.rstrip("\\/") + os.sep)


def _two_passes_reason() -> str | None:
    """④ 两趟齐备的自我锚：成功趟与失败趟的判据骨架都在本文件 `main()` 语段里。

    生效条件：读 `<ROOT>/md_cg/test_issue39_utf8_stdio.py`（git 追踪面里的**那一份**，
    与定点变异在临时物化副本上改的是同一路径——故「成功趟被删掉」在本判据上转红，
    见头注的定点变异实测记录）→ AST 取 `main` 函数语段 + 全模块函数名集合 → 逐项查
    `TWO_PASS_ANCHORS`/`TWO_PASS_FUNCS`；全在返回 None，缺任一项返回人类可读的缺失清单
    （**判据面漂移不得静默**）。源码不可读/不可解析时同样返回原因（fail-closed）。
    不适用条件：不判「判据是否真的在跑」（那是 4a/4b 的 floor 与 2e–2k 的实弹面），
    本判据只回答「两趟的代码是否还在」——即「不许把某趟悄悄删掉」。
    """
    ap = os.path.join(ROOT, SELF_REL.replace("/", os.sep))
    try:
        with open(ap, encoding="utf-8", errors="replace") as fh:
            src = fh.read()
        tree = ast.parse(src, filename=SELF_REL)
    except (OSError, SyntaxError) as e:
        return f"本守卫源码不可读/不可解析（{ap}）：{type(e).__name__}: {e}"
    mains = [n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name == "main"]
    if not mains:
        return "本守卫源码里找不到 main()（判据面已漂移）"
    body = ast.get_source_segment(src, mains[0]) or ""
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    miss = [t for t in TWO_PASS_ANCHORS if t not in body]
    miss += [f"函数 {fn}() 不存在" for fn in TWO_PASS_FUNCS if fn not in names]
    return None if not miss else "缺：" + "；".join(miss)


def _rpc(rid, method, params=None):
    msg = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg, ensure_ascii=False)


def _talk(cmd_args, env, lines, timeout=180):
    """spawn server → 写 JSON-RPC 行 → 收 (returncode, stdout_text, stderr_text)。"""
    proc = subprocess.Popen(
        cmd_args, cwd=ROOT, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace")
    try:
        out, err = proc.communicate("\n".join(lines) + "\n", timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    return proc.returncode, out or "", err or ""


def _resp_lines(out: str):
    """stdout 逐行解析成 (raw_line, obj_or_None)。"""
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


def _find_resp(resps, rid):
    for _raw, obj in resps:
        if isinstance(obj, dict) and obj.get("id") == rid:
            return obj
    return None


def _main_body_has_call(src: str) -> bool:
    """源断言：main() 函数体首段含 _force_utf8_stdio() 调用（定义与调用都在）。"""
    if "def _force_utf8_stdio()" not in src:
        return False
    idx = src.find("def main")
    if idx < 0:
        return False
    window = src[idx:idx + 400]
    return "_force_utf8_stdio()" in window


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_issue39_")
    pool_before = _pool_listing()      # 在役池快照（只读；c5 的前后比对基线）
    try:
        # ---- 1. md_cg 面实弹：GBK 代码页下写中文 ----
        print("[1] md_cg stdio 实弹（PYTHONIOENCODING=gbk:strict，无 -X utf8）")
        rc, out, err = _talk(
            [sys.executable, "-m", "md_cg.mcp_server"], _mdcg_env(tmp), [
                _rpc(1, "initialize", {}),
                _rpc(None, "notifications/initialized"),
                _rpc(3, "tools/call", {"name": "cg", "arguments": {
                    "op": "write", "content": PROBE}}),
            ])
        resps = _resp_lines(out)
        init = _find_resp(resps, 1)
        check("1a initialize 握手在 GBK 控制台下存活（合法 JSON 响应）",
              isinstance(init, dict)
              and (init.get("result") or {}).get("serverInfo", {}).get(
                  "name") == "mdcg-mcp",
              f"rc={rc} lines={len(resps)} err_tail={err[-200:]!r}", live=True)
        wr = _find_resp(resps, 3)
        wr_ok = False
        if isinstance(wr, dict):
            try:
                payload = json.loads(
                    (wr.get("result") or {}).get("content", [{}])[0].get(
                        "text", "{}"))
                wr_ok = ("ok" in payload) or ("moved_to" in payload)
            except (ValueError, AttributeError, IndexError):
                wr_ok = False
        check("1b 中文 write 响应合法且返回 ok/moved_to 字段（红态：进程在读侧崩，本条缺失）",
              wr_ok, f"wr={str(wr)[:200]}", live=True)
        check("1c 全程无 UnicodeEncodeError（stdout/stderr 不见代理对编码炸点）",
              "UnicodeEncodeError" not in out and "UnicodeEncodeError" not in err,
              f"out_tail={out[-160:]!r} err_tail={err[-160:]!r}", live=True)
        check("1d 进程正常下线（EOF 后 returncode=0，非中途崩死）",
              rc == 0, f"rc={rc} err_tail={err[-200:]!r}", live=True)

        # ---- 2. hive 面实弹：同族 server 同款代码页 ----
        # id 契约 v2（B8）下的口径调整（**已声明**，非静默放宽）：`_submit` 不再自造 id，
        # 改调 Rust 侧 `hive alloc-id`；本守卫的 `_hive_env` 把 `HIVE_EXE` 钉在**不存在的
        # 路径**（绝不拉起真 serve），故「ok=true+job_id」这条成功路径在本面**结构性不可
        # 达**。改判的仍是同一件事——中文能否原样穿过 stdio 双程：请求带中文四槽 + 一个
        # 不存在的中文相对 context 路径，断言 ok=False 且原因**回显该中文路径**（逐字节
        # 相等），且错误不是「缺四槽」⇒ 中文入参已过 JSON 解码与四槽闸。
        print("[2] hive stdio 实弹（同款 PYTHONIOENCODING=gbk:strict）")
        rc2, out2, err2 = _talk(
            [sys.executable, "-m", "hive.hive_mcp.mcp_server"],
            _hive_env(tmp), [
                _rpc(1, "initialize", {}),
                _rpc(None, "notifications/initialized"),
                _rpc(3, "tools/call", {"name": "hive_spawn", "arguments": {
                    "model": "probe-model", "user_prompt": PROBE,
                    "identity": "探针端", "task": "编码守卫", "unit": "验证单元",
                    "context_files": [PROBE_CTX]}}),
            ])
        resps2 = _resp_lines(out2)
        init2 = _find_resp(resps2, 1)
        check("2a initialize 握手存活（合法 JSON 响应，serverInfo=hive-mcp）",
              isinstance(init2, dict)
              and (init2.get("result") or {}).get("serverInfo", {}).get(
                  "name") == "hive-mcp",
              f"rc={rc2} lines={len(resps2)} err_tail={err2[-200:]!r}", live=True)
        sp = _find_resp(resps2, 3)
        sp_ok = False
        if isinstance(sp, dict):
            try:
                payload = json.loads(
                    (sp.get("result") or {}).get("content", [{}])[0].get(
                        "text", "{}"))
                serr = payload.get("error") or ""
                sp_ok = (payload.get("ok") is False and PROBE_CTX in serr
                         and "四槽" not in serr)
            except (ValueError, AttributeError, IndexError):
                sp_ok = False
        check("2b 中文 hive_spawn 逐字节往返（ok=false 且原因回显中文 context 路径；"
              "探针 exe 不存在，绝不拉真 serve）",
              sp_ok, f"resp={str(sp)[:200]}", live=True)
        check("2c hive 面无 UnicodeEncodeError",
              "UnicodeEncodeError" not in out2
              and "UnicodeEncodeError" not in err2,
              f"err_tail={err2[-160:]!r}", live=True)
        # 探针诚实边界（id 契约 v2 下重述）：本探针的拒面发生在**分配之前**（context
        # 存在性闸），故守卫自己的临时池应零任务残留——在役池自然零触碰。
        jobs_dir = os.path.join(tmp, "hivejobs")
        probe_jobs = [n for n in (os.listdir(jobs_dir) if os.path.isdir(jobs_dir)
                                  else []) if n.startswith("h")]
        check("2d 拒面未落任何任务目录（临时池零残留 ⇒ 隔离面自证）",
              len(probe_jobs) == 0,
              f"probe_jobs={probe_jobs}")

        # ---- 2'. hive **成功路径**（c4/c5/c6）：真 exe + 守卫自己的临时池 ----
        # 为什么真 exe 是安全的（关键前提，必须写在码上）：
        #   ① 本趟走的是 `hive_spawn` → `_submit` → `_alloc_job_id` → `hive alloc-id`；
        #      alloc-id 是**纯分配**通道（Rust `job::alloc_job_id` 只 fs::create_dir
        #      落池 + 回显 job_id），**不读也不启动任何 serve**；
        #   ② `HIVE_CONFIG` 仍钉在不存在路径 ⇒ `_ensure_serve` 的拉起分支即使被走到，
        #      也在 `serve_start.start()` 的 `load_config` 即返回 {"ok": False,…}
        #      （serve_start.py:462-464），`Popen([EXE, "serve", …])` 不执行；
        #   ③ 池是 HIVE_JOBS_DIR 指针指向的**临时**目录 ⇒ 在役池零触碰（2g/2j 自证）。
        print("[2'] hive 成功路径实弹（真 exe + 守卫自己的临时池；alloc-id 不启动 serve）")
        binexe = _hive_bin()
        if not os.path.isfile(binexe):
            skip("2e–2k 成功路径（ok=true + job_id 四槽中文形态 + 目录落临时池）",
                 f"hive 二进制缺失：期望 {binexe}（未构建的新检出 ⇒ 先在 hive/ 下 "
                 f"cargo build --release，或用环境变量 HIVE_EXE 指向可用二进制）"
                 f"——成功趟**未执行**，不计入通过数；失败趟（2a–2d）已照旧执行")
        else:
            ctx = os.path.join(tmp, PROBE_CTX_OK_NAME)
            with open(ctx, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("中文内容：上下文逐字节往返探针\n")
            rc2b, out2b, err2b = _talk(
                [sys.executable, "-m", "hive.hive_mcp.mcp_server"],
                _hive_env(tmp, binexe), [
                    _rpc(1, "initialize", {}),
                    _rpc(None, "notifications/initialized"),
                    _rpc(3, "tools/call", {"name": "hive_spawn", "arguments": {
                        "model": "probe-model", "user_prompt": PROBE,
                        "identity": PROBE_SLOTS["identity"],
                        "task": PROBE_SLOTS["task"],
                        "unit": PROBE_SLOTS["unit"],
                        "context_files": [ctx]}}),
                ])
            resps2b = _resp_lines(out2b)
            init2b = _find_resp(resps2b, 1)
            check("2e 真 exe 下 initialize 握手存活（组帧未被 alloc-id 打断）",
                  isinstance(init2b, dict)
                  and (init2b.get("result") or {}).get("serverInfo", {}).get(
                      "name") == "hive-mcp",
                  f"rc={rc2b} lines={len(resps2b)} err_tail={err2b[-200:]!r}",
                  live=True)
            sp2 = _find_resp(resps2b, 3)
            payload = {}
            if isinstance(sp2, dict):
                try:
                    payload = json.loads(
                        (sp2.get("result") or {}).get("content", [{}])[0].get(
                            "text", "{}"))
                except (ValueError, AttributeError, IndexError):
                    payload = {}
            jid = payload.get("job_id") or ""
            jobs_dir = os.path.join(tmp, "hivejobs")
            jdir = os.path.join(jobs_dir, jid) if jid else ""
            tail4 = jid[len(PROBE_ID_PREFIX):] if jid.startswith(
                PROBE_ID_PREFIX) else ""
            check("2f 成功路径：ok=true 且 job_id 非空、形如 h_…_…_…_NNNN"
                  "（四段中文形态 = 四槽齐备且编号 4 位定宽）",
                  payload.get("ok") is True and bool(jid)
                  and jid.startswith(PROBE_ID_PREFIX)
                  and len(tail4) == 4 and tail4.isdigit() and jid.count("_") == 4,
                  f"rc={rc2b} payload={json.dumps(payload, ensure_ascii=False)[:220]}",
                  live=True)
            check("2g 任务目录落在守卫自己的临时池（c5 自证：父目录 == 临时池 ∧ 路径在 "
                  "tmp 下 ∧ 不在在役 hive/jobs 下 ∧ 响应 jobs_dir 回显同一池）",
                  bool(jid) and os.path.isdir(jdir)
                  and os.path.dirname(os.path.abspath(jdir))
                  == os.path.abspath(jobs_dir)
                  and _under(jdir, tmp)
                  and not _under(jdir, os.path.join(ROOT, "hive", "jobs"))
                  and os.path.abspath(payload.get("jobs_dir") or "")
                  == os.path.abspath(jobs_dir),
                  f"jid={jid!r} jobs_dir={payload.get('jobs_dir')!r} 临时池={jobs_dir!r}",
                  live=True)
            check("2h 真 exe 下**未拉起 serve**（alloc-id 不启动 serve；HIVE_CONFIG 缺席"
                  " ⇒ 拉起分支在 load_config 即返回）",
                  (payload.get("serve") or {}).get("started") is False,
                  f"serve={payload.get('serve')!r}", live=True)
            spec_ok, spec_seen = False, None
            try:
                with open(os.path.join(jdir, "spec.json"), encoding="utf-8") as fh:
                    spec_seen = json.load(fh)
                spec_ok = (spec_seen.get("user_prompt") == PROBE
                           and spec_seen.get("context_files") == [ctx])
            except (OSError, ValueError):
                spec_ok = False
            check("2i 成功趟的中文逐字节往返（响应 slots 与 spec.json 的 "
                  "user_prompt/context_files 皆与请求逐字节相等）",
                  spec_ok and payload.get("slots") == dict(PROBE_SLOTS),
                  f"slots={payload.get('slots')!r} spec={json.dumps(spec_seen, ensure_ascii=False)[:200] if spec_seen else None!r}",
                  live=True)
            check("2j 在役池零触碰（hive/jobs 清单前后逐字节一致）",
                  _pool_listing() == pool_before,
                  f"before={pool_before!r} after={_pool_listing()!r}")
            check("2k 成功趟全程无 UnicodeEncodeError",
                  "UnicodeEncodeError" not in out2b
                  and "UnicodeEncodeError" not in err2b,
                  f"rc={rc2b} err_tail={err2b[-160:]!r}", live=True)

        # ---- 3. 源断言：两 server 的 main() 首段强制 UTF-8 ----
        print("[3] 源断言（main() 首段 _force_utf8_stdio()）")
        for rel in ("md_cg/mcp_server.py", "hive/hive_mcp/mcp_server.py"):
            with open(os.path.join(ROOT, rel), encoding="utf-8",
                      errors="replace") as fh:
                src = fh.read()
            check(f"3·{rel}: 定义存在且 main() 首段调用 _force_utf8_stdio()",
                  _main_body_has_call(src),
                  "缺定义或 main() 首段未调用（必须早于一切 stderr 中文写与 stdin 读取）")

        # ---- 3'. 两趟齐备（④ 自我锚；定点变异自证：删掉成功趟 ⇒ 本条转红）----
        _why = _two_passes_reason()
        check("3'·两趟齐备（成功趟 + 失败趟的判据骨架都在 main() 语段里；"
              "判据面读的是仓面那一份源码，删趟即转红）",
              _why is None, _why or "")

        # ---- 4. 守卫自检 floor：实弹断言不足即假绿 ----
        print("[4] 守卫自检")
        check(f"4a 实弹断言数 ≥ {LIVE_FLOOR}（防 spawn/扫描面失效假绿）",
              LIVE >= LIVE_FLOOR, f"LIVE={LIVE}")
        _bin_ok = os.path.isfile(_hive_bin())
        check("4b 成功趟的取舍与二进制是否在盘一致（在盘 ⇒ 必须真跑过、零 SKIP；"
              "不在盘 ⇒ 必须显式 SKIP——不许静默缺趟）",
              (SKIP == 0) if _bin_ok else (SKIP >= 1),
              f"bin={_hive_bin()!r} exists={_bin_ok} SKIP={SKIP} LIVE={LIVE}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n=== issue39 utf8 stdio tests: {PASS} passed, {FAIL} failed, "
          f"{SKIP} skipped (live={LIVE}) ===")
    if SKIP:
        print(f"⚠ 显式 SKIP {SKIP} 项（未计入通过数；理由见上方 [SKIP] 行）"
              f"——本守卫**不因 SKIP 判绿**")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    sys.exit(main())
