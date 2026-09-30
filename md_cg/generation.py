# -*- coding: utf-8 -*-
"""md_cg · 代校验单点（generation）——「长驻进程是否还持有旧代代码」的唯一判据面

为什么存在（第 4 条根因，2026-09-30 已定因）
--------------------------------------------
本仓是 stdio 长驻 MCP 服务：`python -m md_cg.mcp_server` 只在**模块首次导入**时
读盘，此后一直用内存里的模块对象。而 md_cg 内有**大量函数内延迟导入**（AST 实测
函数内跨模块相对导入 328 处；其中相当一部分是为**避开循环导入**才写在函数里的）。
两者叠加 ⇒ 代码升级（重装/替换/`git pull`）后，长驻进程里「启动时已载入的旧代
模块」与「升级后第一次被惰性导入的新代模块」会**跨代混用**：

    实测（0.6.1 发版轮）：cg 写入返回
    ImportError: cannot import name 'mint_auto_id' from 'md_cg.mdcg'
    而同一时刻**新解释器**导入同一模块完全正常、盘面上 mdcg.py:1079 就是
    `def mint_auto_id(...)` ⇒ 盘面无罪，是进程内的 md_cg.mdcg 停留在旧代。

处置（使用者裁定方案 b）：把「**升级后须重启长驻 MCP 进程**」写成运维前提，并加
一道代校验把这句话变成可自检、可机械判定的东西。

本模块提供四件（外加一个自检器）：
  · ``fingerprint()``         —— 盘面 md_cg/**/*.py 的**内容**指纹（sha256 十六进制）
  · ``STARTUP_FINGERPRINT``   —— 本模块被导入那一刻的指纹（＝本进程的「代」）
  · ``is_stale()``            —— 现算指纹 != 启动指纹
  · ``report()``              —— 给 ``cg(op=info)`` 用的五键自报（纯增量）
  · ``verify_delegations()``  —— 延迟导入自检器（见下）

为什么指纹用**内容哈希**而不是 mtime/size
------------------------------------------
「无改动重写」在打包/解压/校验回写里很常见（mtime 变、内容不变），用 mtime 会把
同代误报成换代 ⇒ 使用者被引导去做无谓的重启；用 size 更糟（不同内容同长度即漏报）。
内容哈希只认字节：无改动重写 = 同代（实测全量 416 个 .py / 约 11.7 MB 内容哈希
约 21ms，够便宜，可放在每次 op=info 上）。

``verify_delegations()`` 的判定语义（**这一条最要紧，别改成顶层 import**）
------------------------------------------------------------------------
它对盘面每个「函数内（非模块顶层）相对导入」逐项做「导入目标模块 → getattr 取
名字」。要点：

1. **必须在函数内做延迟导入，绝不能为了校验把它们提到模块顶层**——这些导入里
   有相当一部分正是为避开循环导入才写在函数里的，提到顶层会直接制造循环导入。
   校验动作本身（本函数）因此天然只能读盘 + 导入 + getattr。
2. `importlib.import_module` 对**已在本进程 sys.modules 里的模块直接返回内存实例**
   ——这正是跨代判据生效的地方：检查的是「本进程实际持有的那个模块对象」，
   而不是盘面文件（盘面文件另由 fingerprint 覆盖）。
3. 判定三分（取值见返回 dict）：
   · **名字缺失 ⇒ 致命**：目标模块可导入、但其中没有这个名字 ⇒ 抛
     ``GenerationError``（点名子模块与名字 + 「请重启常驻 MCP 进程」指引）。
   · **包内子模块缺失 ⇒ 可选缺失（非致命）**：`from . import x` / `from .pkg import x`
     里 x 其实是**子模块名**而该子模块不在盘面（例：`whitebox_kb/aeis_core/api.py`
     里 `from .knowledge import ingest_text`——该目录的 docstring 明写「不带走
     vision/body/world_model 等，它们在 core.py 里全部是方法内惰性导入，**缺失即
     自动降级**」）。这类是**设计上的可选降级面**，不是换代证据；若判致命，服务
     将永远起不来（实测 25 项）。判别器＝目标模块是否为包（有 ``__path__``）：
     是包才允许用「名字其实是子模块」解释。
   · **目标模块本身导入不进 ⇒ 可选缺失（非致命）**：外部可选模块未装（同上语义）。
   两条非致命项都**如实记进返回 dict 的 ``unavailable``**，不静默丢弃。
4. 结果**按目标模块为单位缓存**（同一进程只扫一次）；扫描与校验**不写任何文件、
   不联网、不做任何时间/随机依赖**（文件按路径排序后处理）。

不适用条件（negative）
----------------------
· 不适用于**已经换代**的判定：本模块只回答「盘面 vs 本进程启动代是否同形」，
  不回答「哪一代更正确」；跨代处置一律是「重启常驻进程」，不做热重载
  （热重载会与函数内延迟导入的避环设计冲突，且会把已加载模块的类身份打散）。
· ``verify_delegations()`` 不构成「所有延迟导入都能跑通」的完备证明：它只校验
  **相对导入的名字存在性**（不执行被导入者、不校验签名/行为），也不覆盖
  `import x.y` 绝对导入与 `importlib.import_module("...")` 字符串形态。
· 代校验只在**进程边界**有效：同一进程内改盘不会自动重载，这正是要重启的原因。
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import os

__all__ = [
    "GenerationError",
    "code_root",
    "fingerprint",
    "STARTUP_FINGERPRINT",
    "is_stale",
    "report",
    "verify_delegations",
]

# 包名（本模块在 md_cg 包内；用 __package__ 而不是写字面量，便于副本/改名场景）
_PACKAGE = __package__ or "md_cg"

# 指纹与代际展示用前缀长度（12 位十六进制足够区分代际，且不把 info 响应撑大）
_GEN_PREFIX = 12

# 单进程内的延迟导入校验缓存（键 = 本模块 code_root()，值 = verify_delegations 返回 dict）
_VERIFY_CACHE: dict = {}

# 扫描时跳过的目录名（编译缓存不是源码；跳掉才不会被 .pyc 干扰指纹）
_SKIP_DIRS = {"__pycache__"}


class GenerationError(RuntimeError):
    """本进程与磁盘代码不同代（跨代混合快照）。

    抛出时机：盘面上某处「函数内相对导入」所要的名字，在**本进程实际持有的**
    目标模块里不存在（而该模块又不是包、无法用「子模块名」解释）。此时该延迟
    导入一旦被执行就是 ImportError，且盘面自洽（新解释器导入正常）——唯一处置
    是把**长驻进程重启**，让它重新只读一代代码。
    """


# 生效条件：无入参，恒返回本文件（md_cg/generation.py）所在目录的绝对路径，即盘面 md_cg 包目录。
def code_root() -> str:
    """盘面 md_cg 包目录（本文件所在目录）的绝对路径。"""
    return os.path.dirname(os.path.abspath(__file__))


# 生效条件：root 为空/缺省时取 code_root()；遍历其下 **.py** 源文件（跳过 __pycache__ 目录与 test_*.py），按相对路径排序后逐字节喂 sha256。
def _iter_source_files(root: str):
    """产出 (相对路径 posix 形态, 绝对路径)，顺序＝相对路径排序（确定性）。"""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            # test_*.py 排除：守卫/测试文件不是长驻服务要惰性导入的运行面，
            # 且它们处于持续改写中——纳入指纹会让「跑一次测试」就假报换代。
            if name.startswith("test_"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            found.append((rel, full))
    found.sort(key=lambda it: it[0])
    return found


# 生效条件：无入参（root 语义见 _iter_source_files）；对每个源文件喂 (相对路径 UTF-8 字节 + NUL + 文件全部字节 + NUL)，返回 sha256 十六进制串；不写任何文件。
def fingerprint() -> str:
    """盘面 md_cg 代码的**内容**指纹（sha256 十六进制，全 64 位）。

    只用（相对路径, 文件字节）——不用 mtime/size：打包/解压/校验回写造成的
    「无改动重写」会变 mtime 而不变内容，用 mtime 会把同代误报成换代。
    """
    root = code_root()
    digest = hashlib.sha256()
    for rel, full in _iter_source_files(root):
        digest.update(rel.encode("utf-8"))
        digest.update(b"\x00")
        with open(full, "rb") as fh:
            digest.update(fh.read())
        digest.update(b"\x00")
    return digest.hexdigest()


# 本进程的「代」＝本模块被导入那一刻的盘面指纹。导入后再改盘不会更新它——
# 这正是「长驻进程停在启动代」的机械表达（需要新代 ⇒ 重启进程）。
STARTUP_FINGERPRINT = fingerprint()


# 生效条件：无入参；现算 fingerprint() 与 STARTUP_FINGERPRINT 逐字符比较，不等即 True（盘面已换代，本进程仍持启动代）。
def is_stale() -> bool:
    """现算指纹 != 启动指纹 ⇒ 本进程与磁盘代码不同代。"""
    return fingerprint() != STARTUP_FINGERPRINT


# 生效条件：无入参；恒返回含 code_generation/disk_generation/stale_on_disk/restart_required/hint 五键的 dict；盘面读取失败（OSError）时按「已换代」保守上报并写进 hint，不抛异常（本函数挂在 cg(op=info) 上，诊断面不得把 info 拖崩）。
def report() -> dict:
    """代校验自报（供 ``cg(op=info)`` 纯增量挂载）。

    五键语义：
      · ``code_generation``   —— 启动代指纹前 12 位（本进程实际持有的一代）
      · ``disk_generation``   —— 现算盘面指纹前 12 位（此刻盘面上的一代）
      · ``stale_on_disk``     —— 两者是否不同（True ⇒ 磁盘代码已换代）
      · ``restart_required``  —— 是否需要重启本进程（与 stale_on_disk 同真值）
      · ``hint``              —— 中文一句话处置指引（可执行，不猜测）
    """
    startup = STARTUP_FINGERPRINT[:_GEN_PREFIX]
    try:
        disk_full = fingerprint()
        stale = disk_full != STARTUP_FINGERPRINT
        disk = disk_full[:_GEN_PREFIX]
    except OSError as exc:                      # 盘面读不到：保守按「已换代」报
        stale = True
        disk = None
        read_error = repr(exc)
    else:
        read_error = None
    if stale:
        hint = ("检测到磁盘上的 md_cg 代码已换代（本进程仍是启动时载入的那一代）："
                "请重启常驻 MCP 进程（重连/重启 mcp_server 即可，记忆数据无损）"
                "后重试。")
        if read_error:
            hint = ("无法读取盘面代码指纹（%s）——按已换代保守上报：请重启常驻 "
                    "MCP 进程（重连/重启 mcp_server 即可，记忆数据无损）后重试。"
                    % read_error)
    else:
        hint = "本进程与磁盘 md_cg 代码同代，暂不需要重启常驻 MCP 进程。"
    return {
        "code_generation": startup,
        "disk_generation": disk,
        "stale_on_disk": bool(stale),
        "restart_required": bool(stale),
        "hint": hint,
    }


# ---------------------------------------------------------------- 延迟导入校验
# 生效条件：path 为本包（root）内某 .py 的绝对路径；返回其在包内的点分模块名，__init__.py 归并为包名本身（例：<root>/a/b/__init__.py → "md_cg.a.b"）。
def _module_name_of(path: str, root: str) -> str:
    """源文件绝对路径 → 包内模块名（`__init__.py` 归并为包名本身）。"""
    rel = os.path.relpath(path, os.path.dirname(root)).replace(os.sep, "/")
    if rel.endswith(".py"):
        rel = rel[:-3]
    if rel.endswith("/__init__"):
        rel = rel[: -len("/__init__")]
    return rel.replace("/", ".")


# 生效条件：file_module 为引入语句所在文件的点分模块名，level ≥ 1 为相对层级（from 后点的个数），node_module 为语句里的模块部分（`from . import x` 形态为 None）；返回解析后的绝对目标模块名（不校验其是否可导入，空包名时为 ""）。
def _resolve_base(file_module: str, level: int, node_module):
    """把 `from <level 个点><node_module> import ...` 解析成绝对目标模块名。

    level=1 指当前包；level=2 指上一级，依此类推（相对导入的层数语义）。
    node_module 为 None 时（`from . import x` 形态）目标即所在包的**包名本身**。
    """
    parts = file_module.split(".")
    pkg = parts[:-1]                       # 文件所在包
    up = level - 1
    if up:
        pkg = pkg[: len(pkg) - up] if up <= len(pkg) else []
    if node_module:
        return ".".join(pkg + [node_module]) if pkg else node_module
    return ".".join(pkg)


# 生效条件：以 (文件名→模块名, 相对路径) 构造后 visit(ast)；items 里为**函数体深度 >0** 的相对导入项（模块顶层与类体顶层不计），每项＝(目标模块名, 被导入名, 相对路径, 行号, 是否 `from . import x` 形态)。
class _DelegationVisitor(ast.NodeVisitor):
    """收集**函数体内**（depth>0）的跨模块相对导入。

    意义：模块顶层的 import 在导入期就会执行（换代必然同步）；写在函数里的
    导入要到该行被跑到才执行——正是它制造了「新代代码用旧代模块」的窗口。
    """

    def __init__(self, file_module: str, rel_path: str):
        self.file_module = file_module
        self.rel_path = rel_path
        self.depth = 0
        self.items = []                    # (target_base, name, rel_path, lineno, module_is_none)

    def _visit_function(self, node):
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    def visit_FunctionDef(self, node):     # noqa: N802 —— ast 回调名
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node):  # noqa: N802
        self._visit_function(node)

    def visit_ImportFrom(self, node):      # noqa: N802
        if self.depth > 0 and node.level and node.level > 0:
            base = _resolve_base(self.file_module, node.level, node.module)
            for alias in node.names:
                self.items.append((base, alias.name, self.rel_path,
                                   node.lineno, node.module is None))
        self.generic_visit(node)


# 生效条件：无入参；AST 扫盘面 md_cg/**/*.py（与 fingerprint 同排除集：__pycache__ 与 test_*.py）里所有函数内相对导入，对每一项「导入目标模块 → getattr 取名字」，名字缺失即抛 GenerationError（点名子模块与名字 + 重启指引）；包内子模块缺失与目标模块导入不进这两类记入 unavailable（非致命）；结果按 code_root 缓存，同一进程只扫一次；不写文件、不联网。
def verify_delegations() -> dict:
    """延迟导入自检器：盘面每个「函数内相对导入」是否能在当前模块面上解析。

    返回 dict（键与语义稳定）：
      · ``ok``               —— 无致命不一致（True/False）
      · ``scanned_files``    —— 参与扫描的源文件数
      · ``delegations``      —— 扫到的函数内相对导入**项数**（一个 import 语句可多项）
      · ``target_modules``   —— 去重后的目标模块数
      · ``resolved``         —— 去重后成功解析的 (目标模块, 名字) 数
      · ``unavailable``      —— 非致命项列表：[{target, name, rel_path, line, reason}]
      · ``mismatches``       —— 致命项列表：[{target, name, rel_path, line}]
    致命项非空时抛 ``GenerationError``（消息点名子模块与名字）。
    同一进程内只扫一次（缓存），缓存键为 ``code_root()``。

    文件集与 ``fingerprint()`` 同口径（跳过 ``__pycache__`` 与 ``test_*.py``）：
    长驻服务要惰性导入的是**运行面**，`test_*.py` 不属运行面（且处于持续改写中）。
    注意本函数**不写任何文件**（不建缓存文件），缓存只在内存。

    另：扫描期 `ast.parse` 失败（源码语法坏）会**原样抛出** `SyntaxError`——盘面
    语法坏本就该 fail-closed（由调用方按启动闸处置），此处不吞成「可用」。
    """
    root = code_root()
    cache_key = root
    if cache_key in _VERIFY_CACHE:
        return _VERIFY_CACHE[cache_key]

    items = []
    files = _iter_source_files(root)
    for rel, full in files:
        with open(full, encoding="utf-8") as fh:
            src = fh.read()
        visitor = _DelegationVisitor(_module_name_of(full, root), rel)
        visitor.visit(ast.parse(src, full))
        items.extend(visitor.items)

    # 去重（同一 (目标模块, 名字) 在多处延迟导入只需查一次；首次出现的引用位置留痕）
    uniq: dict = {}
    for base, name, rel, line, module_is_none in items:
        uniq.setdefault((base, name), (base, name, rel, line, module_is_none))

    resolved = 0
    unavailable = []
    mismatches = []
    for (base, name), (_b, _n, rel, line, module_is_none) in sorted(uniq.items()):
        try:
            # 已加载则取内存实例（跨代判据；不是重读盘面文件）
            target = importlib.import_module(base)
        except ModuleNotFoundError as exc:
            unavailable.append({"target": base, "name": name, "rel_path": rel,
                                "line": line, "reason": "目标模块不在盘面：%s" % exc})
            continue
        except Exception as exc:               # noqa: BLE001 —— 导入期异常归入非致命并如实登记
            unavailable.append({"target": base, "name": name, "rel_path": rel,
                                "line": line,
                                "reason": "目标模块导入失败（%s）：%s"
                                          % (type(exc).__name__, exc)})
            continue
        if hasattr(target, name):
            resolved += 1
            continue
        if hasattr(target, "__path__"):        # 目标模块是包 ⇒ 名字可能是子模块
            try:
                importlib.import_module("%s.%s" % (base, name))
                resolved += 1
                continue
            except ModuleNotFoundError:
                unavailable.append({
                    "target": base, "name": name, "rel_path": rel, "line": line,
                    "reason": "包内子模块不存在（可选降级面，非换代证据）"})
                continue
            except Exception as exc:           # noqa: BLE001
                unavailable.append({
                    "target": base, "name": name, "rel_path": rel, "line": line,
                    "reason": "子模块导入失败（%s）：%s" % (type(exc).__name__, exc)})
                continue
        mismatches.append({"target": base, "name": name, "rel_path": rel,
                           "line": line, "module_is_none_form": module_is_none})

    result = {
        "ok": not mismatches,
        "scanned_files": len(files),
        "delegations": len(items),
        "target_modules": len({base for base, _n in uniq}),
        "resolved": resolved,
        "unavailable": unavailable,
        "mismatches": mismatches,
    }
    _VERIFY_CACHE[cache_key] = result

    if mismatches:
        raise GenerationError(_mismatch_message(mismatches))
    return result


# 生效条件：mismatches 非空（每项含 target/name/rel_path/line）；返回多行中文消息——点名首项的子模块与名字、按「启动代 vs 盘面代」是否相等分流陈述，并给出含「重启常驻 MCP 进程」的可执行指引。
def _mismatch_message(mismatches) -> str:
    """跨代不一致的异常消息（点名子模块与名字 + 可执行指引）。

    两代关系**分开陈述**，不套一句话：启动代≠盘面代 ⇒ 真·跨代（升级后未重启，
    这正是本模块要防的那一种）；启动代==盘面代 ⇒ 盘面自身不自洽（半升级/改坏/
    删了定义但引用方还在）。两种都要求重启常驻进程，但只有前者能说「不同代」——
    把后者也说成「不同代」是假读（实测出现过：两侧前缀都是 1afbcba9935a 却印着
    「≠」），故此处按事实分流。
    """
    head = mismatches[0]
    startup = STARTUP_FINGERPRINT[:_GEN_PREFIX]
    disk = _disk_prefix()
    lines = [
        "跨代混合快照：盘面上的函数内延迟导入在本进程的模块面上解析不了。",
        "  · 目标子模块：%s" % head["target"],
        "  · 找不到的名字：%s" % head["name"],
        "  · 引用处：%s:%s（函数内延迟导入）" % (head["rel_path"], head["line"]),
    ]
    if startup != disk:
        lines.append("  · 本进程启动代 %s ≠ 当前盘面代 %s" % (startup, disk))
    else:
        lines.append("  · 启动代与当前盘面代同为 %s：本次不一致不是「换代」本身，"
                     "而是盘面代码在该模块面上不自洽（半升级/被改坏/定义被删但"
                     "引用方仍在）" % startup)
    if len(mismatches) > 1:
        lines.append("  · 同类不一致共 %d 项：%s"
                     % (len(mismatches),
                        "、".join("%s.%s" % (m["target"], m["name"])
                                  for m in mismatches[1:9])))
    if startup != disk:
        lines.append("本进程与磁盘代码不同代，请重启常驻 MCP 进程"
                     "（重连/重启 mcp_server 即可，记忆数据无损）后重试。")
    else:
        lines.append("请重新完整部署/安装本包（或修复该名字），并重启常驻 MCP 进程"
                     "（重连/重启 mcp_server 即可，记忆数据无损）后重试。")
    return "\n".join(lines)


# 生效条件：无入参；现算 fingerprint() 前 12 位返回（盘面读不到时返回 "?" 而不抛——仅供异常消息展示）。
def _disk_prefix():
    """现算指纹前 12 位（读不到时返回 '?'）——仅供异常消息展示。"""
    try:
        return fingerprint()[:_GEN_PREFIX]
    except OSError:
        return "?"
