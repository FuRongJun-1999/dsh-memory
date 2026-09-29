# -*- coding: utf-8 -*-
"""utf8_boot.py · 入口自保证 UTF-8（进程自保证，不依赖使用者 profile 的环境变量）。

为什么放在**仓库根**、而不是 `md_cg/` 里
------------------------------------------------------------------------
本模块被 hive / md_cg / scripts 三处的**进程入口**共用。放进 `md_cg/` 会让
`import md_cg` 拉起整个认知图包（`md_cg/__init__.py` 会 `import .mdcg`）——为一次
UTF-8 检查付出「重包导入的启动成本 + hive/scripts 入口被绑上 md_cg 依赖方向」的
双重代价。放仓库根 = 零第三方、零 md_cg 依赖、入口一行 `sys.path` 插入即可用。

它解决什么（修前事实，本机 2026-09-29 实测）
------------------------------------------------------------------------
* `locale.getlocale()` = `('Chinese (Simplified)_China', '936')`，
  `locale.getpreferredencoding(False)` = `cp936`；Python 裸 `open()` 的缺省编码
  与 stdio 的控制台代码页都跟着 locale 走。
* 清空 `PYTHONUTF8` / `PYTHONIOENCODING` 后实测：裸 `open()` 读 UTF-8 中文文件抛
  `UnicodeDecodeError`；`sys.stdout.write("中文")` 静默产出 GBK 字节（`\\xd6\\xd0\\xce\\xc4`）；
  裸 `open(p, "w")` 写中文落 GBK 字节——**静默坏**，比抛异常更难查。
* 本机之所以没炸，是因为**环境里**有 `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8`，
  且部分入口自己钉（`scripts/run_tests.py` 给子进程覆盖、`scripts/linux_verify.sh`
  export、`src/lib/mdcg_client.ts` 设 PYTHONUTF8）。
  ⇒ 正确性挂在「环境变量 + 每个入口记得设」上：换台没设的机器，或新入口漏设，
  即走 GBK。本模块把该保证**下沉到进程自身**。

三条路（`ensure_utf8` 的分支）
------------------------------------------------------------------------
0. **调用方不是进程入口（被 import）→ 只置 env 即返回**——绝不重启、绝不退出、绝不打
   日志。见下「被 import 时不得重启（F6）」。
1. `sys.flags.utf8_mode` 为真 → 立即返回（不重启、不打日志）；
2. 为假 → **默认重启自身**（`-X utf8`）；重启后子进程 `utf8_mode` 已开 ⇒ 结构上
   不可能二次重启（幂等，见守卫的「只重启一次」判据）；
3. 显式退出通道：env `LINGSHU_UTF8_NO_REEXEC` 为真 → **fail-fast** 非 0 退出并打印
   可执行指引（不能接受子进程的场景：嵌入式宿主、CI 调试、进程树审计）。

无论走哪条路（含第 0 路），都会把 `PYTHONUTF8=1` 与 `PYTHONIOENCODING=utf-8` 置入
`os.environ`，供本进程随后派生的子进程继承（执行器/编排器派生子进程时的第二道保险）。

被 import 时不得重启（F6，2026-09-29 复核实测）
------------------------------------------------------------------------
本助手在七个入口里都是**模块级**调用，而其中数个入口**同时是被 import 的库**
（`hive/serve_start.py` 被 `hive/hive_mcp/mcp_server.py` 导入、`hive/exec.py` 被
`hive/orch.py` 导入）。若「被 import」也整进程重启：调用方正在处理的输入会被吞掉。
复核员构造态实测（未加本判据前）：单会话解释器启动 2 次、第 3 条请求被吞、
**无错误帧、rc=0**——静默坏，比抛异常更难查。故重启/fail-fast 只在
「调用方模块 == `__main__`」时发生；被 import 时只置 env。

fail-fast 指引必须**可照抄**（F2，2026-09-29 复核实测）
------------------------------------------------------------------------
指引此前一律印 `python -X utf8 <入口 __file__>`；而两个 MCP 入口的真实接入形态是
`python -m md_cg.mcp_server` / `python -m hive.hive_mcp.mcp_server`（mcp.json 直连），
照抄文件形态会 `ImportError: attempted relative import with no known parent package`
（实测 rc=1）。故 `_guidance` 复用与 `reexec_argv()` **同一**判别（`__main__.__spec__`
有 name 与 parent ⇒ `-m` 形态），印 `python -X utf8 -m <模块名>`。

**禁用 `os.exec*` 系列**：Windows 上进程替换与标准句柄继承的语义不可靠，而 MCP 是
**字节组帧**的 stdio 协议——重启必须显式传递 `stdin`/`stdout`/`stderr` 三个标准流，
丢了组帧就是灾难。故本模块只用 `subprocess.run`（实测：父进程退出后子进程持有的
管道句柄仍完好）。

与设计裁决的一处偏离（已在回报中声明，理由是端到端组帧这条真判据）
------------------------------------------------------------------------
重启 argv 除 `-X utf8` 外**保留 `-m` 模块语义**：`python -m md_cg.mcp_server` 若按
`sys.argv` 原样重启，会退化成「直跑文件」（`sys.path[0]` 变包目录、`__package__`
丢失），`md_cg/mcp_server.py:3833` 的 `from .datapath import ...` 立即 ImportError
——本机实测 `python -X utf8 md_cg/mcp_server.py` → rc=1、
`ImportError: attempted relative import with no known parent package`。而
`python -m md_cg.mcp_server` 正是 ZCode/DSH 的 mcp.json 接入形态（该文件头注第 14 行）。
故 `-m` 形态按 `[python, -X, utf8, -m, <模块名>, *sys.argv[1:]]` 重建，其余形态原样
`*sys.argv`；源码无法重放的解释器形态（`-c` / `-`，从命令行/stdin 读源码）**不重启**，
只告警——那里重启会把源码丢掉（`python -X utf8 -c` 会转而从 stdin 读代码）。
"""
from __future__ import annotations

import locale
import os
import subprocess
import sys

__all__ = ["ensure_utf8", "launch_hint", "reexec_argv", "NO_REEXEC_ENV",
           "EXIT_UTF8_REQUIRED"]

#: 显式退出通道：置真值即不自动重启，改为 fail-fast 非 0 退出
NO_REEXEC_ENV = "LINGSHU_UTF8_NO_REEXEC"
#: fail-fast 退出码（非 0；指引文案里点名「怎么改」）
EXIT_UTF8_REQUIRED = 2
#: 真值判定集（去空白 + 转小写后比对；未设 / 空串 / 其它值一律视为否）
_TRUTHY = frozenset(("1", "true", "yes", "on", "y", "t"))
#: 源码无法重放的解释器形态（`-c` 从命令行读、`-` 从 stdin 读）：重启会丢源码
_UNREBUILDABLE_ARGV0 = frozenset(("-c", "-"))
#: 结构化退出码：解释器形态无法重放时「不重启也不假装已保证」的退出码（守卫熔断未命中）
_EXIT_UNREBUILDABLE = 3


# 生效条件：env name 存在且其值去空白转小写后落在 _TRUTHY 内返回 True；未设、空串或其它值返回 False。
def _truthy(name: str) -> bool:
    """env 真值判定（唯一口径：去空白 + 小写 + 白名单比对）。"""
    return (os.environ.get(name) or "").strip().lower() in _TRUTHY


# 生效条件：无入参；把 PYTHONUTF8=1 与 PYTHONIOENCODING=utf-8 写入 os.environ（覆盖旧值，幂等），随后派生的子进程按此继承，无返回值。
def _set_child_env() -> None:
    """置子进程继承面（第四条）：PYTHONUTF8=1 + PYTHONIOENCODING=utf-8。"""
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"


# 生效条件：无入参；`__main__.__spec__` 同时有 name 与 parent（`python -m pkg.mod` 形态）时返回该模块名，否则返回 None（直跑文件时 `__spec__` 为 None）。
def _m_module_name() -> str | None:
    """本进程是否以 `python -m <模块>` 启动；是则返回模块名，否则 None。

    **单点判别**：`reexec_argv()`（重启 argv）与 `launch_hint()`（fail-fast 指引文案）
    共用本函数——两处各写一份必然漂移，而指引印错的代价是使用者照抄后撞墙（F2）。
    """
    main = sys.modules.get("__main__")
    spec = getattr(main, "__spec__", None)
    name = getattr(spec, "name", None)
    if name and getattr(spec, "parent", None):
        return name
    return None


# 生效条件：entry 为入口标识或 None；本进程经 `python -m` 启动时返回 `-m <模块名>`，其余形态返回 entry 本身（None 时回落占位 `<entry>`）。
def launch_hint(entry: str | None) -> str:
    """「照抄即可跑」的启动形态（`-X utf8` 之后的那一段）。

    -m 形态 → `-m <模块名>`（模块名可被 python 重新 import，等同使用者的原始命令）；
    其余形态 → `entry`（通常 `__file__`，绝对路径）。
    """
    name = _m_module_name()
    if name:
        return "-m %s" % name
    return entry or "<entry>"


# 生效条件：无入参；调用 ensure_utf8 的模块 `f_globals` 与 `sys.modules['__main__'].__dict__` 同一时返回 True；取不到调用帧时返回 False（保守：不重启）。
def _caller_is_process_entry() -> bool:
    """调用 `ensure_utf8` 的模块是否**就是本进程入口**（`__main__`）。

    F6 判据本体：只在「本模块即进程入口」时重启/fail-fast——被 import 时重启会吞掉
    调用方正在处理的输入（复核实测：无错误帧、rc=0，静默）。用 `f_globals` 与
    `__main__.__dict__` 的**同一性**比对：`python -m pkg.mod` 下入口模块的 `__name__`
    也是 `"__main__"`，故 -m 与直跑文件两种入口形态得到同一判定。
    """
    try:
        frame = sys._getframe(1)                  # ensure_utf8 自身的帧
        globs = frame.f_back.f_globals            # 调用 ensure_utf8 的那一帧
    except (ValueError, AttributeError):
        return False                              # 取不到调用帧：不重启（静默重启的代价更大）
    return globs is getattr(sys.modules.get("__main__"), "__dict__", None)


# 生效条件：无入参；sys.argv[0] 为 -c/- （源码不可重放）时返回 None；本进程经 python -m 启动（_m_module_name 非空）时返回 [exe, -X, utf8, -m, 模块名, *sys.argv[1:]]；其余形态返回 [exe, -X, utf8, *sys.argv]。
def reexec_argv() -> list | None:
    """重启自身的 argv（保留 -m 模块语义）；源码不可重放时返回 None。"""
    if sys.argv and sys.argv[0] in _UNREBUILDABLE_ARGV0:
        return None
    name = _m_module_name()
    if name:
        return [sys.executable, "-X", "utf8", "-m", name, *sys.argv[1:]]
    return [sys.executable, "-X", "utf8", *sys.argv]


# 生效条件：entry 为入口标识（通常 __file__）或 None，cause 为原因短句；返回「可执行指引」多行文本——启动形态经 launch_hint 复用 -m 判别（-m 入口印 `python -X utf8 -m <模块名>`，其余印 `<entry>`），并含 PYTHONUTF8=1 写法、当前 locale 缺省编码、以及取消 NO_REEXEC_ENV 的出路；全为 ASCII 与中文，无任何凭据。
def _guidance(entry: str, cause: str) -> str:
    """fail-fast / 无法重启时的可执行指引（照抄即可跑）。"""
    try:
        pref = locale.getpreferredencoding(False)
    except Exception:                                     # noqa: BLE001
        pref = "?"
    hint = launch_hint(entry)                             # F2：与 reexec_argv 同一判别
    return (
        "utf8_boot: 入口需要**进程级 UTF-8**，但当前解释器未启用"
        "（sys.flags.utf8_mode=0，locale 缺省编码=%s）。\n"
        "  入口：%s\n"
        "  原因：%s\n"
        "请改用下列任一方式启动（可照抄）：\n"
        "    python -X utf8 %s\n"
        "    PYTHONUTF8=1 python %s        # Windows cmd: set PYTHONUTF8=1 && python ...\n"
        "或取消环境变量 %s（让入口自动以 -X utf8 重启自身）。\n"
        % (pref, entry, cause, hint, hint, NO_REEXEC_ENV)
    )


# 生效条件：text 给出后优先以 UTF-8 字节写 sys.stderr.buffer（不受控制台代码页影响），buffer 不可用时回落文本层写入；两级都失败则静默返回，无返回值。
def _emit(text: str) -> None:
    """把指引写到 stderr——**显式 UTF-8 字节**，不随控制台代码页漂移。"""
    try:
        sys.stderr.buffer.write(text.encode("utf-8"))
        sys.stderr.buffer.flush()
        return
    except Exception:                                     # noqa: BLE001
        pass
    try:
        sys.stderr.write(text)
        sys.stderr.flush()
    except Exception:                                     # noqa: BLE001
        pass


# 生效条件：entry 为入口标识或 None；先把 PYTHONUTF8/PYTHONIOENCODING 置入 env；调用方非进程入口（本助手被 import）时立即返回（不重启/不退出/不打日志）；sys.flags.utf8_mode 为真时立即返回（不重启、不打日志）；为假且 LINGSHU_UTF8_NO_REEXEC 为真时向 stderr 打印可执行指引并以 EXIT_UTF8_REQUIRED 退出；为假且该 env 非真时以 reexec_argv() 重启自身（显式传递 stdin/stdout/stderr 三流）并以子进程退出码退出；重启 argv 为 None（-c/- 形态）或子进程无法启动（OSError）时打印指引并以 _EXIT_UNREBUILDABLE / EXIT_UTF8_REQUIRED 退出；无返回值（不返回即在重启或退出的路上）。
def ensure_utf8(entry: str | None = None) -> None:
    """入口自保证 UTF-8 —— 唯一调用点，**必须在任何文件/库 I/O 之前**。

    生效条件：`utf8_mode` 已开时置 env 后立即返回（不重启、不打日志）；未开且
    **本模块不是进程入口**（本助手被 import）时置 env 后立即返回——不重启、不退出、
    不打日志（F6：被 import 时重启会静默吞掉调用方的输入）；未开且
    `LINGSHU_UTF8_NO_REEXEC` 为真时向 stderr 打印可执行指引并以
    ``EXIT_UTF8_REQUIRED``(2) 退出；未开且该 env 非真时以 ``reexec_argv()`` 重启
    自身（``-X utf8``，显式传递 stdin/stdout/stderr）并以子进程退出码退出——重启后
    子进程 ``utf8_mode`` 已开，故不会二次重启；``-c``/``-`` 形态（源码不可重放）
    不重启，打印指引后以 ``3`` 退出。

    不适用条件：本进程已在 UTF-8 模式下运行、或本助手是被 import 的（非进程入口）时，
    只置子进程继承面、不做任何重启——即「已在 utf8 模式」「被 import」两者都是幂等
    且安静的（子进程不会再重启）。**入口若以非 `__main__` 形态被 import，则不获得
    重启保证**（这是有意的：静默重启的代价高于少一次保证）。
    """
    _set_child_env()
    if sys.flags.utf8_mode:
        return                                            # ②：已开 → 不重启、不打日志
    if not _caller_is_process_entry():
        return                                            # F6：被 import → 只置 env，静默
    target = entry or (sys.argv[0] if sys.argv else "<entry>")
    if _truthy(NO_REEXEC_ENV):
        _emit(_guidance(target, "%s 已置真：禁止自动重启" % NO_REEXEC_ENV))
        raise SystemExit(EXIT_UTF8_REQUIRED)              # ③：显式退出通道
    argv = reexec_argv()
    if argv is None:
        _emit(_guidance(target, "解释器以 -c/- 读源码，argv 无法重放（不重启）"))
        raise SystemExit(_EXIT_UNREBUILDABLE)
    try:
        proc = subprocess.run(argv, stdin=sys.stdin, stdout=sys.stdout,
                              stderr=sys.stderr)          # 三流显式传递：字节组帧
    except OSError as exc:
        _emit(_guidance(target, "重启自身失败：%r" % (exc,)))
        raise SystemExit(EXIT_UTF8_REQUIRED)
    raise SystemExit(proc.returncode)
