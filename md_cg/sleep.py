# -*- coding: utf-8 -*-
"""md_cg · 睡眠周期的 git 机制（P0-1：根级锁 + 影子工作树 + 独立 git 目录）

设计正身：`docs/plans/睡眠与自迭代_功能优化设计_v0.4.md` §三（周期引擎九步）/ §四
（§4.1 / §4.2 / §4.4 / §4.5）/ §4.7（env 表）。**P0-1** 落机制与机械判据（物化 /
对账+提交 / 合并 / 只 revert），**P1** 在其上接 §4.4 的四阶段协议与 §3.1 的九步
周期引擎（`run_cycle` / `iterate` / `reconcile_gated` / `merge_cycle`），并由
`md_cg/sustain.py` 的第六档 tick `_tick_sleep` 驱动。

§4.7 的七个 env 键在 `SLEEP_ENV_DEFAULTS` / `SLEEP_ENV_KEYS` 里**只有一份**定义；
读取点一律经 `sleep_env()` 及其具名包装——不得再写第二处缺省字面量。

三条硬约束（§4.1 / §4.2）：

  ① **版本库只覆盖真源面**：那 8 个 LAYERS 目录（`md_cg.mdcg.LAYERS`，**单点导入
     不抄第二份**）下的 `.md`；`_keys.json` / `_access.log` / `_index.json` /
     `*.tmp` / `*.lock` 等派生、运行态与密钥面一律不进版本库。
  ② **绝不在数据根内建 `.git`**：git 一律以
     `git --git-dir=<state_root>/sleep/lib.git --work-tree=<工作树>` **显式形态**
     调用；`add` 只喂**显式 pathspec 白名单**——**绝不整树 add**（不带 pathspec，
     或以通配/当前目录当 pathspec）。白名单之外结构性不可达：密钥不靠
     `.gitignore` 兜（数据根根本没有 ignore 面），而「哪些路径能入册」是这份
     白名单直接说了算。
  ③ 影子是 `git worktree`（分支 `sleep/<时间戳>`），落 `state_root()/sleep/shadow`；
     **三段动作各自持根级锁**（复用 `md_cg.fsutil.FileLock`；锁文件落
     `state_root()` 侧而**非数据根**）。回滚**只给 `revert`**——不提供抹历史的
     强推档（§〇.3-13：历史不丢，回滚自身也进历史）。

与 `hive/wm.py` 的关系：**形态照抄**（分支命名、`--no-ff`、冲突诚实报错不自动
解决、git 操作面串行），**数据面不同**（wm 管蜂巢任务产物，本模块管记忆真源面）。

四阶段（§4.4）里本模块的落点：

    ① 物化   `materialize()`          —— 持根级锁；主库真源面逐字节不变
    ② 迭代   （P1；在影子上跑，本模块不管）
    ③ 对账+提交 `reconcile_and_commit()` —— 持根级锁；Δ 为空即零提交零写入
    ④ 合并   `merge()`                —— 持根级锁；写主库的正是「应写的那部分」

脚本式用法（只读判读）：`python -X utf8 -m md_cg.sleep --status`
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

from . import nodefile
from .datapath import mdcg_root, state_root
from .fsutil import FileLock, append_jsonl
from .mdcg import LAYERS

#: 睡眠面在状态根下的目录名（**数据根之外**：版本库与影子都不进记忆面）。
SLEEP_DIRNAME = "sleep"
GITDIR_DIRNAME = "lib.git"
SHADOW_DIRNAME = "shadow"
#: 根级锁文件名（`FileLock` 会再拼 `.lock`）——即 `<state_root>/sleep/sleep.lock`。
LOCK_NAME = "sleep"
#: 基线分支与影子分支前缀（§4.1：分支名 `sleep/<时间戳>`）。
BASE_BRANCH = "main"
BRANCH_PREFIX = "sleep/"
GIT_USER_NAME = "lingshu-sleep"
GIT_USER_EMAIL = "sleep@lingshu.local"
#: 历史里**零命中**才合规的禁入路径（§4.5 机械判据）。
FORBIDDEN_BASENAMES = ("_keys.json", "_access.log", "_index.json")
FORBIDDEN_SUFFIXES = (".tmp", ".lock")
DEFAULT_LOCK_TIMEOUT = 30.0
#: 睡眠轮次的**台账**（append-only JSONL）——落 `sleep_root()` 侧（状态面，
#: **不是数据根**）：台账是运行态，不该成为真源面的一部分、也不该进版本库。
SLEEP_LEDGER = "_sleep.jsonl"

# ---- §4.7 env 表的**单一真源**（P1，2026-10-01）---------------------------
# 为什么要有这张表：§4.7 的七个键此前**全仓零读取点**（P1 探针取证），
# 若让 `_start_sustain`、op 路径与 `SustainLoop.__init__` 各写一份「缺省字面
# 量」，就是 P0-2 刚收掉的那种漂移（同一 `(root,name)` 走两条入口得到相反
# 语义）。纪律：**改缺省只改这里**；所有读取点只经 `sleep_env()` 及其
# 具名包装（`sleep_enabled` / `sleep_interval` / …），不得再写第二处字面量
# （守卫 test_sleep_p1.py 把这条钉死：全仓 `MDCG_SLEEP*` 带引号字面量只许
# 出现在本表的 `SLEEP_ENV_KEYS` 里）。
SLEEP_ENV_DEFAULTS = {
    "sleep": "1",            # 总开关（"1" = 开）
    "interval": "3600",      # 周期（秒）——一小时一次
    "window": "23:00-07:00",  # 睡眠时段（本地时间；留空 = 全时段；支持跨午夜）
    "merge": "auto",         # 合并策略 auto / ask / never
    "gitdir": "",            # git 目录（空 → state_root()/sleep/lib.git）
    "shadow": "",            # 影子工作树（空 → state_root()/sleep/shadow）
    "scrub_apply": "0",      # 第④步去污染**实改**闸（缺省关：只盘点不落盘）
}
#: 各键的 env 名（**唯一的字面量落点**）。
SLEEP_ENV_KEYS = {
    "sleep": "MDCG_SLEEP",
    "interval": "MDCG_SLEEP_INTERVAL",
    "window": "MDCG_SLEEP_WINDOW",
    "merge": "MDCG_SLEEP_MERGE",
    "gitdir": "MDCG_SLEEP_GITDIR",
    "shadow": "MDCG_SLEEP_SHADOW",
    "scrub_apply": "MDCG_SLEEP_SCRUB_APPLY",
}
#: 关断字面量——与 `sustain.AUTO_OFF_VALUES` 同一口径（0 / false / False）。
SLEEP_OFF_VALUES = ("0", "false", "False")
#: `MDCG_SLEEP_MERGE` 的合法取值；越界值回落 "auto"（不猜测、不静默降级成 never）。
SLEEP_MERGE_MODES = ("auto", "ask", "never")


class SleepError(Exception):
    """git 操作失败（带 stderr 摘要）。"""


# 生效条件：name 为 SLEEP_ENV_DEFAULTS 的键时，按 SLEEP_ENV_KEYS[name] 从 environ（缺省 os.environ）取名取值，缺键（None）时回落真源缺省；返回**原始字符串**（不做 bool/float 解释——解释归各具名包装）。name 非表内键时抛 KeyError（不做静默回落：拼错键名即编程错误）。
def sleep_env(name: str, environ=None) -> str:
    """§4.7 env 表的唯一读取出口（原始字面量）。"""
    env = os.environ if environ is None else environ
    v = env.get(SLEEP_ENV_KEYS[name])
    return SLEEP_ENV_DEFAULTS[name] if v is None else str(v)


# 生效条件：sleep_env("sleep") 取值不属于 SLEEP_OFF_VALUES 时为真（"1"/空串/未设 → 开；"0"/"false"/"False" → 关）。
def sleep_enabled(environ=None) -> bool:
    """总开关 `MDCG_SLEEP`（缺省开）。"""
    return sleep_env("sleep", environ) not in SLEEP_OFF_VALUES


# 生效条件：sleep_env("interval") 可 float() 且 > 0 时返回该 float，否则回落真源缺省 3600.0（非法值不抛、不猜测——回落缺省并在台账里如实标注由调用方负责）。
def sleep_interval(environ=None) -> float:
    """周期秒数 `MDCG_SLEEP_INTERVAL`（缺省 3600）。非法/非正值 → 缺省。"""
    try:
        v = float(sleep_env("interval", environ))
    except (TypeError, ValueError):
        v = 0.0
    return v if v > 0 else float(SLEEP_ENV_DEFAULTS["interval"])


# 生效条件：sleep_env("window") 的原文（留空 = 全时段）；形态校验归 parse_window/in_window。
def sleep_window(environ=None) -> str:
    """睡眠时段 `MDCG_SLEEP_WINDOW`（缺省 23:00-07:00）。"""
    return sleep_env("window", environ)


# 生效条件：sleep_env("merge") 去空白转小写后属于 SLEEP_MERGE_MODES 时原样返回，否则回落 "auto"。
def sleep_merge_mode(environ=None) -> str:
    """合并策略 `MDCG_SLEEP_MERGE`（缺省 auto）。越界值回落 auto。"""
    m = sleep_env("merge", environ).strip().lower()
    return m if m in SLEEP_MERGE_MODES else "auto"


# 生效条件：sleep_env("scrub_apply") 取值不属于 SLEEP_OFF_VALUES 时为真（缺省 "0" → 假）。
def sleep_scrub_apply(environ=None) -> bool:
    """第④步去污染**实改**闸 `MDCG_SLEEP_SCRUB_APPLY`（缺省关）。"""
    return sleep_env("scrub_apply", environ) not in SLEEP_OFF_VALUES


# 生效条件：无入参；恒返回 state_root() 下 "sleep" 的拼接路径（**不触盘**）。随 ENV_STATE_ROOT / DSH_HOME 解析结果变化——故不得缓存为模块常量。
def sleep_root() -> str:
    """睡眠面根目录（版本库 / 影子 / 锁文件的父目录，**在数据根之外**）。"""
    return os.path.join(state_root(), SLEEP_DIRNAME)


# 生效条件：explicit 非空时经 abspath 归一返回；否则取 env MDCG_SLEEP_GITDIR（非空）经 abspath 返回；两者皆空时返回 sleep_root() 下 "lib.git" 的拼接路径。不触盘、不建目录。
def git_dir(explicit: str = None) -> str:
    """独立 git 目录（§4.7 `MDCG_SLEEP_GITDIR`；缺省 `state_root()/sleep/lib.git`）。"""
    v = explicit or sleep_env("gitdir")     # 键名/缺省的真源 = SLEEP_ENV_KEYS 表
    return os.path.abspath(v) if v else os.path.join(sleep_root(), GITDIR_DIRNAME)


# 生效条件：explicit 非空时经 abspath 归一返回；否则取 env MDCG_SLEEP_SHADOW（非空）经 abspath 返回；两者皆空时返回 sleep_root() 下 "shadow" 的拼接路径。不触盘。
def shadow_dir(explicit: str = None) -> str:
    """影子工作树落点（§4.7 `MDCG_SLEEP_SHADOW`；缺省 `state_root()/sleep/shadow`）。"""
    v = explicit or sleep_env("shadow")     # 键名/缺省的真源 = SLEEP_ENV_KEYS 表
    return os.path.abspath(v) if v else os.path.join(sleep_root(), SHADOW_DIRNAME)


# 生效条件：无入参；恒返回 sleep_root() 下 "sleep" 的拼接路径（`FileLock` 会再拼 ".lock"，即 <state_root>/sleep/sleep.lock）。**绝不在数据根内**——锁件进不了真源面，也进不了版本库白名单。
def lock_path() -> str:
    """根级锁文件路径（不含 `.lock` 后缀；`FileLock` 自行拼）。

    落 `state_root()` 侧是**硬要求**（§八 P0-1）：锁文件若落数据根，会与
    `mkstemp` 临时件一起成为「数据根里多出来的件」，白名单拦得住它进版本库，
    但拦不住它进「真源面逐字节对比」以外的观测面——而它本就属于状态面。
    """
    return os.path.join(sleep_root(), LOCK_NAME)


# 生效条件：shadow 为已挂上的链式工作树（其下 .git 为文件）时，读该文件首行 "gitdir: <路径>" 并返回 abspath 归一后的专属 git 目录；文件缺失/不可读/首行不含 "gitdir:" 时返回空串。
def worktree_git_dir(shadow: str) -> str:
    """链式工作树（`git worktree add` 的产物）自己的 git 目录。

    **为什么必须有这一层**：`git --git-dir=<主 git 目录> --work-tree=<链式工作树>`
    的 HEAD 与 index 都取**主**那一份——在影子上提交会把提交落到 `main`，影子分支
    永远停在基线（本机实测：`rev-parse --abbrev-ref HEAD` 在影子侧也返回 `main`，
    对账提交后 `sleep/<ts>` 仍只有基线提交）。链式工作树的 HEAD/index 在它自己的
    gitdir（`<lib.git>/worktrees/<名>`）里，`--git-dir` 必须指过去。
    `--git-dir` + `--work-tree` 的**显式形态不变**，只是 `--git-dir` 的取值随工作树
    而变（§八 P0-1 要求的是「不用 cwd 猜、两个开关都显式」，本函数正是照此办的）。
    """
    try:
        with open(os.path.join(shadow, ".git"), encoding="utf-8") as f:
            first = f.readline().strip()
    except OSError:
        return ""
    if "gitdir:" not in first:
        return ""
    return os.path.abspath(first.split("gitdir:", 1)[1].strip())


# 生效条件：root 为目录路径时返回 8 个 LAYERS 目录中**盘上存在且其下至少有一个文件**者的目录名列表（顺序同 LAYERS）；root 下无任何命中时返回空列表。只 walk 目录、不读文件内容，命中即 break。
def pathspecs(root: str) -> list:
    """`add` 的**显式 pathspec 白名单**：`md_cg.mdcg.LAYERS` 中盘上非空者。

    与引擎**同源**（单点导入 `LAYERS`，不硬编码第二份——两处各写一份必然漂移）。
    空目录必须滤掉：`git add -- <空目录>` 会让**整条命令**以
    `fatal: pathspec ... did not match any files` 失败（本机实测），连同一批
    本该入册的目录一起拒绝；而空目录本就没有可入册的 `.md`。
    """
    out = []
    for layer in LAYERS:
        base = os.path.join(root, layer)
        for _dp, _dn, files in os.walk(base):
            if files:
                out.append(layer)
                break
    return out


# 生效条件：root 为目录时返回 {相对 root 的正斜杠路径: sha256 十六进制}，覆盖 8 个 LAYERS 目录下**全部** .md（按路径排序遍历）；单文件读失败记 "!unreadable" 而不抛；root 下无 .md 时返回空 dict。
def source_face_hashes(root: str) -> dict:
    """真源面内容哈希集合——「主库真源面逐字节不变」的判据面（§八 P0-1）。

    与版本库白名单**同口径**：只含 LAYERS 各目录下的 `.md`。派生面
    （`_index.json` / `_index_log/`）、运行态（`_access.log`）、密钥面
    （`_keys.json`）、临时件与锁件都不在内——它们逐字节变不变不是判据。
    """
    out = {}
    for layer in LAYERS:
        base = os.path.join(root, layer)
        for dirpath, _dn, files in os.walk(base):
            for fn in sorted(files):
                if not fn.endswith(".md"):
                    continue
                p = os.path.join(dirpath, fn)
                rel = os.path.relpath(p, root).replace("\\", "/")
                try:
                    with open(p, "rb") as f:
                        out[rel] = hashlib.sha256(f.read()).hexdigest()
                except OSError:
                    out[rel] = "!unreadable"
    return out


# 生效条件：before/after 为 source_face_hashes 形态的 {路径: 哈希} 时，返回 {"added": 新增路径排序表, "removed": 消失路径排序表, "changed": 双侧皆有但哈希不同者排序表}（三者皆可为空）。
def face_delta(before: dict, after: dict) -> dict:
    """真源面哈希集合的前后差（三键列表；全空 = 逐字节不变）。"""
    return {"added": sorted(set(after) - set(before)),
            "removed": sorted(set(before) - set(after)),
            "changed": sorted(k for k in set(before) & set(after)
                              if before[k] != after[k])}


# 生效条件：git_dir_path 与 work_tree 给定时以 ["git", "--git-dir=<git_dir_path>", "--work-tree=<work_tree>", *args] 调 subprocess.run（capture_output + text + 显式 utf-8/errors=replace + env 带 PYTHONUTF8=1 + shell=False）并返回 CompletedProcess；returncode 非零不抛（由调用方判）。
def _git(git_dir_path: str, work_tree: str, *args: str) -> subprocess.CompletedProcess:
    """git 调用的**唯一出口**：`--git-dir` 与 `--work-tree` 一律显式给。

    `--work-tree` 不是装饰：物化与合并传数据根，对账+提交传影子——同一个版本库
    两个工作树，靠这两个显式开关切换，**不依赖进程 cwd**（`hive/wm.py` 用 `-C`
    是因为它的工作树就是版本库本身；这里两者分居，故用分裂形态）。
    """
    argv = ["git", "--git-dir=" + git_dir_path, "--work-tree=" + work_tree]
    argv.extend(args)
    env = dict(os.environ, PYTHONUTF8="1")
    return subprocess.run(argv, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          env=env, shell=False)


# 生效条件：同 _git 的调用形态；returncode != 0 时抛 SleepError（消息取 stderr 为真值、为空则取 stdout，strip 后截 300 字符），为 0 时返回 stdout。
def _git_ok(git_dir_path: str, work_tree: str, *args: str) -> str:
    r = _git(git_dir_path, work_tree, *args)
    if r.returncode != 0:
        raise SleepError("git %s 失败: %s"
                         % (" ".join(args[:2]), (r.stderr or r.stdout).strip()[:300]))
    return r.stdout


# 生效条件：git_dir_path 为（可建或已存在的）目录；先 makedirs(dirname(git_dir_path), exist_ok=True)，若该目录此前不存在则调 git init -b main，随后逐个设 user.name/user.email/core.quotepath（幂等，失败静默）；返回 {"created": bool, "git_dir": str}。
def ensure_repo(root: str, git_dir_path: str) -> dict:
    """建 / 复用独立 git 目录（幂等）。**绝不在数据根内建 `.git`。**

    首次 `git --git-dir=<G> --work-tree=<root> init -b main`——非裸仓形态：
    「工作树」由每次调用的 `--work-tree` 显式指定，故数据根里既没有 `.git`
    目录、也没有 `.git` 文件（`--separate-git-dir` 会在数据根留一个 `.git`
    文件，同样不合格）。

    身份与编码**写进本仓 config**（不依赖全局 git 配置）：`core.quotepath=false`
    让中文文件名在 `log --name-only` 输出里可读，否则非 ASCII 路径会被
    C 风格转义，机械判据的 grep 面随之失真。

    `core.autocrlf=false` + `core.eol=lf` 同理写进本仓 config——**这是
    「真源面逐字节」判据的前提**：本机系统级配置是 `core.autocrlf=true`，
    任何检出都会把工作树里的 LF 折成 CRLF，于是「工作树字节」与「索引字节」
    永久不一致：Δ 恒非空（合并后仍报差异）、`git revert` / `git merge` 被
    「本地改动会被覆盖」挡住（本机实测：只加前两键时 revert 必失败）。
    数据面的真源是**字节**，故本仓显式关闭该折叠；只改本仓 config
    （不动使用者的全局/系统配置）。
    """
    os.makedirs(os.path.dirname(os.path.abspath(git_dir_path)), exist_ok=True)
    created = not os.path.isdir(git_dir_path)
    if created:
        _git_ok(git_dir_path, root, "init", "-b", BASE_BRANCH)
    for k, v in (("user.name", GIT_USER_NAME), ("user.email", GIT_USER_EMAIL),
                 ("core.quotepath", "false"),
                 ("core.autocrlf", "false"), ("core.eol", "lf")):
        _git(git_dir_path, root, "config", k, v)
    return {"created": created, "git_dir": git_dir_path}


# 生效条件：git_dir_path 为 git 仓时返回 git rev-parse --verify --quiet HEAD 的 returncode == 0（即该仓至少有一个提交）；非仓或零提交返回 False。
def _has_head(git_dir_path: str, work_tree: str) -> bool:
    return _git(git_dir_path, work_tree, "rev-parse", "--verify", "--quiet",
                "HEAD").returncode == 0


# 生效条件：git_dir_path 为 git 仓且 work_tree 为目录；pathspecs(work_tree) 为空时直接返回 {"committed": False, "reason": "白名单为空…"}；否则 git add -- <白名单> 后以 git diff --cached --quiet 判有无暂存改动（rc==0 即无改动），无改动返回 {"committed": False, "reason": "Δ 为空…"}（零提交、零写入）；有改动则 commit -m message 并返回 {"committed": True, "commit": <sha>, "pathspecs": [...]}。
def _stage_and_commit(git_dir_path: str, work_tree: str, message: str) -> dict:
    """白名单 add + 有改动才 commit（Δ 为空 ⇒ 整轮跳过，§4.4）。"""
    ps = pathspecs(work_tree)
    if not ps:
        return {"committed": False, "reason": "白名单为空（真源面无任何 .md）",
                "pathspecs": ps}
    _git_ok(git_dir_path, work_tree, "add", "--", *ps)
    if _git(git_dir_path, work_tree, "diff", "--cached", "--quiet").returncode == 0:
        return {"committed": False, "reason": "Δ 为空（无待提交改动）",
                "pathspecs": ps}
    _git_ok(git_dir_path, work_tree, "commit", "-m", message)
    return {"committed": True,
            "commit": _git_ok(git_dir_path, work_tree, "rev-parse", "HEAD").strip(),
            "pathspecs": ps}


# 生效条件：无入参；返回形如 "20261001-071530" 的本地时间戳（秒级），用于拼分支名 sleep/<时间戳>。
def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


# 生效条件：phase 与 timeout 给定；返回统一的「根级锁未取得」读数字典（ok=False、busy=True、lock_held=False、lock=lock_path()、timeout 原值、reason 文案）。
def _busy(phase: str, timeout: float) -> dict:
    return {"ok": False, "busy": True, "lock_held": False, "phase": phase,
            "lock": lock_path(), "timeout": timeout,
            "reason": ("根级锁未取得：另一进程正在睡眠周期内（两进程同时触发时"
                       "只有一个能进）")}


# 生效条件：root 为数据根（缺省取 mdcg_root()）；在 <state_root>/sleep/sleep 的根级锁内，建/复用独立 git 目录并（首次）把真源面入册为 main 基线，再 git worktree add -b sleep/<ts> <shadow> main（分支已存在则复用该分支重试一次）；返回含 ok/phase/busy/git_dir/shadow/branch/pathspecs/lock_acquired/source_face_delta/lock 的字典——ok 为真且 source_face_delta 三键全空 = 主库真源面逐字节未变。
def materialize(root: str = None, *, git_dir_path: str = None,
                shadow: str = None, ts: str = None,
                timeout: float = DEFAULT_LOCK_TIMEOUT) -> dict:
    """① 物化（§4.4，**持根级锁**）。

    幂等：影子已存在时先摘（`worktree remove --force`，非注册目录退化为 rmtree）
    再挂。分支已存在（同一秒重入）时退化为复用该分支。
    """
    root = os.path.abspath(root or mdcg_root())
    G = git_dir_path or git_dir()
    S = shadow or shadow_dir()
    branch = BRANCH_PREFIX + (ts or _stamp())
    before = source_face_hashes(root)
    with FileLock(lock_path(), timeout=timeout, strict=False) as lk:
        if not lk.acquired:
            return _busy("materialize", timeout)
        rep = ensure_repo(root, G)
        init = _stage_and_commit(G, root, "sleep: 基线（真源面入册）") \
            if not _has_head(G, root) else {"committed": False,
                                            "reason": "已有基线提交"}
        if os.path.isdir(S):
            r = _git(G, root, "worktree", "remove", "--force", S)
            if r.returncode != 0:
                # 非注册工作树（上一次运行被杀、目录残留）→ 直接摘目录
                shutil.rmtree(S, ignore_errors=True)
        r = _git(G, root, "worktree", "add", "-b", branch, S, BASE_BRANCH)
        if r.returncode != 0:
            r2 = _git(G, root, "worktree", "add", S, branch)
            if r2.returncode != 0:
                return {"ok": False, "busy": False, "lock_held": True,
                        "phase": "materialize", "lock": lock_path(),
                        "error": (r2.stderr or r2.stdout).strip()[:300],
                        "hint": "影子分支/目录未能挂上"}
            reused = True
        else:
            reused = False
        after = source_face_hashes(root)
        delta = face_delta(before, after)
        return {"ok": not (delta["added"] or delta["removed"] or delta["changed"]),
                "busy": False, "lock_held": True, "phase": "materialize",
                "git_dir": G, "shadow": S, "branch": branch,
                "branch_reused": reused, "repo_created": rep["created"],
                "baseline": init, "pathspecs": pathspecs(root),
                "lock": lock_path(), "source_face_delta": delta,
                "source_face_count": len(after),
                # §4.4 ① 的**基准水位**：物化这一刻的主库真源面内容哈希集合——
                # 迭代期间主库若被改动，并发闸（§4.4 ③）即以它判定「主库优先」。
                "baseline_face": after}


# 生效条件：root/shadow 给定且影子工作树存在；在根级锁内对**影子**工作树做白名单 add + 有改动才 commit（一次调用 = 一个提交，§4.4 ③），并复核主库真源面在同一窗口内逐字节未变；返回 {"ok", "busy", "lock_held", "phase", "committed", "commit", "branch", "pathspecs", "source_face_delta", "lock"}；影子不存在时返回 ok=False 与 error。
def reconcile_and_commit(root: str = None, *, git_dir_path: str = None,
                         shadow: str = None, branch: str = None,
                         batch: str = None,
                         timeout: float = DEFAULT_LOCK_TIMEOUT) -> dict:
    """③ 对账 + 提交（§4.4，**持根级锁**）。

    本轮（P0）只落**机制**：语义差异集 Δ 与四闸（保护 / tombstone / 并发 /
    生命周期）属 P1——在影子上的迭代改动由 P1 负责，本函数只保证
    「白名单 add + 一个提交 + 主库真源面不动」。

    ⚠ 工作树是**影子**不是数据根：这正是「迭代段完全不碰主库」的机制面。
    `--git-dir` 取影子的**专属** gitdir（`worktree_git_dir()`）——取主那份会让
    提交落到 `main` 而影子分支停在基线（见该函数说明的实测）。
    """
    root = os.path.abspath(root or mdcg_root())
    G = git_dir_path or git_dir()
    S = shadow or shadow_dir()
    before = source_face_hashes(root)
    with FileLock(lock_path(), timeout=timeout, strict=False) as lk:
        if not lk.acquired:
            return _busy("reconcile_and_commit", timeout)
        if not os.path.isdir(S):
            return {"ok": False, "busy": False, "lock_held": True,
                    "phase": "reconcile_and_commit", "lock": lock_path(),
                    "error": "影子工作树不存在：先 materialize", "shadow": S}
        # 链式工作树用自己的 gitdir（否则 HEAD/index 取主那一份，提交会落到 main）
        GS = worktree_git_dir(S) or G
        br = branch or _git_ok(GS, S, "rev-parse", "--abbrev-ref", "HEAD").strip()
        msg = "sleep: %s 轮对账提交" % (batch or _stamp())
        res = _stage_and_commit(GS, S, msg)
        after = source_face_hashes(root)
        delta = face_delta(before, after)
        return {"ok": not (delta["added"] or delta["removed"] or delta["changed"]),
                "busy": False, "lock_held": True,
                "phase": "reconcile_and_commit", "git_dir": G,
                "worktree_git_dir": GS, "shadow": S,
                "branch": br, "committed": res["committed"],
                "commit": res.get("commit"),
                "reason": res.get("reason"), "pathspecs": res.get("pathspecs"),
                "lock": lock_path(), "source_face_delta": delta}


# 生效条件：root 与 branch 给定；在根级锁内确认版本库 HEAD 在 BASE_BRANCH 上（否则返回 ok=False 与 error），随后 git merge --no-ff <branch> -m …；returncode != 0 时返回 ok=False 与 conflict（输出含 "CONFLICT"）及 error 截 500 字符、hint（冲突不自动解决）；成功返回 ok=True 与 merged/commit；返回体附 source_face_delta（本阶段**会**写主库，即「应写的那部分」）。
def merge(root: str = None, *, git_dir_path: str = None, branch: str,
          shadow: str = None,
          timeout: float = DEFAULT_LOCK_TIMEOUT) -> dict:
    """④ 合并（§4.4，**持根级锁**）：`--no-ff` 把 `sleep/<ts>` 合回 `main`。

    ⚠ 本阶段的工作树是**数据根**——合并会把影子分支引入的真源面变更检出到主库，
    这正是「合并阶段应写的那部分」（§八 P0-1 额外机械判据的例外项）。冲突
    **诚实报错、不自动解决**（照 `hive/wm.py` 既有裁决）。

    HEAD 不在 `main` 上（例如上一次合并冲突挂起、HEAD 残留在别处）时**拒绝执行**
    ——不许在非主线上做合并（与 `wm.py:cmd_merge` 同判据）。
    """
    root = os.path.abspath(root or mdcg_root())
    G = git_dir_path or git_dir()
    S = shadow or shadow_dir()
    before = source_face_hashes(root)
    with FileLock(lock_path(), timeout=timeout, strict=False) as lk:
        if not lk.acquired:
            return _busy("merge", timeout)
        cur = _git_ok(G, root, "rev-parse", "--abbrev-ref", "HEAD").strip()
        if cur != BASE_BRANCH:
            return {"ok": False, "busy": False, "lock_held": True, "phase": "merge",
                    "lock": lock_path(), "head": cur,
                    "error": "当前 HEAD 在 %s，merge 须在 %s 上执行" % (cur, BASE_BRANCH)}
        r = _git(G, root, "merge", "--no-ff", branch, "-m",
                 "sleep: merge %s into %s" % (branch, BASE_BRANCH))
        if r.returncode != 0:
            out = (r.stdout + r.stderr).strip()
            return {"ok": False, "busy": False, "lock_held": True, "phase": "merge",
                    "lock": lock_path(), "shadow": S,
                    "conflict": "CONFLICT" in out, "error": out[:500],
                    "source_face_delta": face_delta(before, source_face_hashes(root)),
                    "hint": ("冲突不自动解决（照 hive/wm.py 既有裁决）：人工/LLM 裁决后 "
                             "git add + git commit 收口，或 git merge --abort 放弃本次合并")}
        after = source_face_hashes(root)
        delta = face_delta(before, after)
        return {"ok": True, "busy": False, "lock_held": True, "phase": "merge",
                "lock": lock_path(), "merged": branch,
                "commit": _git_ok(G, root, "rev-parse", "HEAD").strip(),
                "source_face_delta": delta, "main_written": delta["added"] + delta["changed"]}


# 生效条件：commit 为版本库中存在的提交（或分支名）；在根级锁内以其父提交数判是否 merge（git rev-list --parents -n1 字段数 > 2 即 merge），是 merge 则附 -m 1，执行 git revert --no-edit <参数> <commit>；returncode != 0 时返回 ok=False 与 conflict/error/hint，成功返回 ok=True、reverted、commit（新提交）与 source_face_delta。**只走 revert，不提供抹历史的强推档**。
def revert(commit: str, root: str = None, *, git_dir_path: str = None,
           timeout: float = DEFAULT_LOCK_TIMEOUT) -> dict:
    """回滚（§4.4 / §〇.3-13，**持根级锁**）：`git revert` 出一个反向提交。

    **只提供 revert**：历史不丢、可追（`revert` 的自身提交也进历史）。抹历史的
    强推档（把 HEAD 直接指回旧点、把中间提交整段丢弃的那档）**不实现**——本模块
    里既没有那个子命令，也没有等价的「强推 HEAD 到旧点」路径（守卫把这条钉成
    字面量零命中）。merge commit 自动加 `-m 1`（保留主线侧、撤销分支引入的变更），
    与 `hive/wm.py:cmd_revert` 同口径。
    """
    root = os.path.abspath(root or mdcg_root())
    G = git_dir_path or git_dir()
    before = source_face_hashes(root)
    with FileLock(lock_path(), timeout=timeout, strict=False) as lk:
        if not lk.acquired:
            return _busy("revert", timeout)
        parents = _git_ok(G, root, "rev-list", "--parents", "-n1", commit).split()
        args = ["revert", "--no-edit"]
        if len(parents) > 2:
            args += ["-m", "1"]
        args.append(commit)
        r = _git(G, root, *args)
        if r.returncode != 0:
            out = (r.stdout + r.stderr).strip()
            return {"ok": False, "busy": False, "lock_held": True, "phase": "revert",
                    "lock": lock_path(), "conflict": "CONFLICT" in out,
                    "error": out[:500],
                    "hint": "冲突不自动解决；处理后可 git revert --continue / --abort"}
        after = source_face_hashes(root)
        return {"ok": True, "busy": False, "lock_held": True, "phase": "revert",
                "lock": lock_path(), "reverted": commit,
                "commit": _git_ok(G, root, "rev-parse", "HEAD").strip(),
                "merge_commit": len(parents) > 2,
                "source_face_delta": face_delta(before, after)}


# ---------------- 机械判据（§4.5）----------------

# 生效条件：版本库可读时返回 git ls-files 的逐行非空结果（相对工作树的路径，正斜杠）；仓不可读抛 SleepError。
def tracked_paths(root: str = None, *, git_dir_path: str = None) -> list:
    """版本库当前追踪的路径集合（`git ls-files`）。"""
    root = os.path.abspath(root or mdcg_root())
    G = git_dir_path or git_dir()
    return [ln.strip() for ln in _git_ok(G, root, "ls-files").splitlines()
            if ln.strip()]


# 生效条件：版本库可读时返回 git log --all --name-only 的逐行非空结果（全部引用、全部提交改动过的路径，含重复）；仓零提交时返回空列表。
def history_paths(root: str = None, *, git_dir_path: str = None) -> list:
    """**全部历史**（所有分支、所有提交）里出现过的路径。"""
    root = os.path.abspath(root or mdcg_root())
    G = git_dir_path or git_dir()
    out = _git_ok(G, root, "log", "--all", "--name-only", "--pretty=format:")
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


# 生效条件：对 history_paths 去重后逐个取 basename；basename 属于 FORBIDDEN_BASENAMES 或以 FORBIDDEN_SUFFIXES 之一结尾者计入命中；返回按路径排序的命中表（零命中 = 合规）。
def history_forbidden_hits(root: str = None, *,
                           git_dir_path: str = None) -> list:
    """历史里的禁入路径（§4.5：`_keys.json` / `_access.log` / `_index.json` /
    `*.tmp` / `*.lock` **零命中**）。"""
    hits = []
    for p in sorted(set(history_paths(root, git_dir_path=git_dir_path))):
        base = p.rsplit("/", 1)[-1]
        if base in FORBIDDEN_BASENAMES or base.endswith(FORBIDDEN_SUFFIXES):
            hits.append(p)
    return hits


# 生效条件：root 为目录、版本库可读时，返回 {"ok": bool, "tracked": int, "outside_layers": [...], "missing_md": [...]}——ok 为真当且仅当 tracked 全部落在 LAYERS 目录下（outside_layers 为空）且 LAYERS 下全部 .md 都在 tracked 内（missing_md 为空）。
def audit_tracking(root: str = None, *, git_dir_path: str = None) -> dict:
    """§4.5 判据二：追踪集合 **⊆ 8 个 LAYERS 目录** 且 **⊇ 其下全部 `.md`**。"""
    root = os.path.abspath(root or mdcg_root())
    tracked = tracked_paths(root, git_dir_path=git_dir_path)
    outside = [p for p in tracked if p.split("/", 1)[0] not in LAYERS]
    missing = sorted(set(source_face_hashes(root)) - set(tracked))
    return {"ok": not outside and not missing, "root": root, "tracked": len(tracked),
            "outside_layers": outside, "missing_md": missing}


# 生效条件：root 为目录、版本库可读时返回 {"ok": bool, "hits": [...], "scanned": int}——ok 为真当且仅当 history_forbidden_hits 为空。
def audit_history(root: str = None, *, git_dir_path: str = None) -> dict:
    """§4.5 判据一：历史里禁入路径零命中。"""
    hits = history_forbidden_hits(root, git_dir_path=git_dir_path)
    return {"ok": not hits, "hits": hits,
            "scanned": len(set(history_paths(root, git_dir_path=git_dir_path)))}


# ==========================================================================
# §3.1 九步周期引擎 · §4.4 四阶段协议（P1）
# ==========================================================================
#
# 分工（§4.4 + §4.2-7）：**git 是记录者，不是裁决者**。
#   ① 物化   `materialize()`（P0-1，持根级锁）
#   ② 迭代   `iterate()`（在影子上跑 §3.1 的 ②–⑦ 步）——**完全不碰主库**
#   ③ 对账   `reconcile_gated()`——算语义差异集 Δ，逐项过**语义四闸**，
#            只把通过者提交到 `sleep/<ts>`（Δ 空 ⇒ 零提交零写入）
#   ④ 合并   `merge_cycle()`——先语义重放 Δ 到主库（正常写路径 + 每条
#            `evolution.record` before/after），再 `git merge --no-ff`；
#            冲突项**挂起不自动解决**，出清单
#   `run_cycle()` 是这四段的编排（常驻循环的第六档 tick 调它）。

#: §3.1 九步（显式命名；台账顺序即此序——不许悄悄跳过、不许改名）。
STEPS = ("recall_scan", "induce", "promote", "scrub", "weights", "reindex",
         "record", "feedback", "self_check")
STEP_NAMES = {
    "recall_scan": "感知盘点（只读）",
    "induce": "归纳",
    "promote": "升层（情境→知识/长期）",
    "scrub": "巩固与去污染",
    "weights": "权重刷新与衰减",
    "reindex": "索引重建（六要素/时间/因果）",
    "record": "记录",
    "feedback": "反馈",
    "self_check": "方向性自检",
}
#: 本轮落成**显式 no-op 占位**的两步（后批接线）——台账里标 `skipped: "未接线"`。
#: 这是本批**有意不改检索读数**的那两步（设计稿 §3.1 的 5/6 行；接线归 P4 / P2P3）。
NOT_WIRED = {"weights": "P4（权重刷新与衰减进主分数）",
             "reindex": "P2/P3（六要素索引 / 图检索路）"}
#: 第⑨步方向性自检的节奏（§3.1：对齐理论「默认每 100 轮」）。
SELF_CHECK_EVERY = 100
#: 语义四闸的名字（§4.4 ③，顺序即裁决顺序）。
GATES = ("protect", "tombstone", "concurrent", "lifecycle")


# 生效条件：无入参；恒返回 sleep_root() 下 SLEEP_LEDGER 的拼接路径（睡眠轮次台账；不触盘）。
def ledger_path() -> str:
    return os.path.join(sleep_root(), SLEEP_LEDGER)


# 生效条件：无入参；sleep_root() 下 SLEEP_LEDGER 可读时返回其逐行 json.loads 成功的记录列表（坏行跳过），不可读/不存在返回 []；limit 为真值时只返回最后 int(limit) 条。
def read_ledger(limit=None) -> list:
    out = []
    try:
        with open(ledger_path(), encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    out.append(r)
    except OSError:
        return []
    return out[-int(limit):] if limit else out


# 生效条件：rec 为 dict 时向 sleep_root()/SLEEP_LEDGER 追加一行 JSON（先 makedirs(sleep_root())）；无返回值，写入失败抛 OSError。
def _append_ledger(rec: dict):
    os.makedirs(sleep_root(), exist_ok=True)
    append_jsonl(ledger_path(), rec)


# 生效条件：batch 为真值时返回台账中是否存在 batch 相同且 merged 为真的记录（幂等判据）；batch 为假值返回 False。
def batch_merged(batch: str) -> bool:
    if not batch:
        return False
    return any(r.get("batch") == batch and r.get("merged") is True
               for r in read_ledger())


# 生效条件：root 给定且 md_cg.mdcos 可导入时返回该 root 上的 MdCGOS 实例；导入失败抛原异常。
def _open_cg(root: str):
    from .mdcos import MdCGOS
    return MdCGOS(root)


# ---------------- 睡眠时段窗口（§4.7：本地时间 / 支持跨午夜）----------------

# 生效条件：s 形如 "HH:MM" 且时分在界内时返回当日的分钟数（h*60+m）；形态不符或越界抛 ValueError。
def _hhmm(s) -> int:
    parts = str(s).strip().split(":")
    if len(parts) != 2:
        raise ValueError("时间形态须为 HH:MM：%r" % (s,))
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("时分越界：%r" % (s,))
    return h * 60 + m


# 生效条件：spec 去空白后为空时返回 None（= 全时段，唯一显式入口）；否则要求恰含一个 "-" 且两侧均为合法 HH:MM（时分界内）才返回 (起始分钟, 结束分钟)；形态非法（无 "-" / 多段 / 非数字 / 越界）时回落**缺省窗** `SLEEP_ENV_DEFAULTS["window"]` 解析出的分钟对——**不回落全时段**。
def parse_window(spec):
    """窗口解析：**留空 → None（全时段，唯一显式入口）**；**非法形态 → 回落缺省窗**。

    裁定⑰（2026-10-01，前沿小修）：此前「留空」与「非法形态」被合并成 None（=
    全时段），即**用户把 `MDCG_SLEEP_WINDOW` 打错字**（实测 `in_window("乱写",
    "12:00") is True`，如 `23:00-99:99`）会让睡眠周期在**白天也迭代**——fail-open。
    现按同表既有惯例分流（`sleep_interval`「非法/非正回落 3600」、
    `sleep_merge_mode`「越界回落 auto」同款）：**非法 → 回落缺省窗**，
    宁可退回保守时段，也不把「打错字」当成「允许全天迭代」。
    """
    s = str(spec or "").strip()
    if not s:
        return None                      # 留空 = 全时段（唯一显式入口）
    parts = s.split("-")
    if len(parts) == 2:
        try:
            return (_hhmm(parts[0]), _hhmm(parts[1]))
        except (TypeError, ValueError):
            pass
    a, _sep, b = str(SLEEP_ENV_DEFAULTS["window"]).partition("-")
    return (_hhmm(a), _hhmm(b))          # 非法形态 → 缺省窗（单一真源，不写第二处字面量）


# 生效条件：now 为 None 时取 time.localtime()；为 str 时按 HH:MM 解析；为 int/float 时按该时间戳 localtime()；为对象时取 tm_hour/tm_min（time.struct_time）或 hour/minute（datetime.time）；返回当日分钟数。
def _minute_of(now=None) -> int:
    if now is None:
        lt = time.localtime()
        return lt.tm_hour * 60 + lt.tm_min
    if isinstance(now, str):
        return _hhmm(now)
    if isinstance(now, (int, float)):
        lt = time.localtime(float(now))
        return lt.tm_hour * 60 + lt.tm_min
    hh = getattr(now, "tm_hour", None)
    mm = getattr(now, "tm_min", None)
    if hh is None:
        hh = getattr(now, "hour", None)
        mm = getattr(now, "minute", 0)
    if hh is None:
        raise TypeError("不支持的时刻形态：%r" % (now,))
    return int(hh) * 60 + int(mm or 0)


# 生效条件：spec 解析为 None（留空）时恒返回 True（全时段）；起止相同亦返回 True；否则取 _minute_of(now) 后——起 < 止 时判 [起, 止)，起 > 止（跨午夜）时判 t>=起 或 t<止。
def in_window(spec, now=None) -> bool:
    """窗口判定：**支持跨午夜**（23:00-07:00 在 23:30 / 03:00 在窗内、12:00 在窗外）；留空 = 全时段恒真；**非法形态回落缺省窗**（裁定⑰）。"""
    w = parse_window(spec)
    if w is None:
        return True
    start, end = w
    if start == end:
        return True
    t = _minute_of(now)
    if start < end:
        return start <= t < end
    return t >= start or t < end


# ---------------- 真源面 / 语义差异集 ----------------

# 生效条件：root 为目录时返回 {node_id: {"rel","abs","layer"}}，覆盖 8 个 LAYERS 目录下**全部** .md（node_id = 文件名主干，与 md_cg 既有口径一致）；root 下无 .md 返回 {}。
def node_files(root: str) -> dict:
    out = {}
    for layer in LAYERS:
        base = os.path.join(root, layer)
        for dirpath, _dn, files in os.walk(base):
            for fn in sorted(files):
                if not fn.endswith(".md"):
                    continue
                p = os.path.join(dirpath, fn)
                out[fn[:-3]] = {"rel": os.path.relpath(p, root).replace("\\", "/"),
                                "abs": p, "layer": layer}
    return out


# 生效条件：p 可读时返回其 sha256 十六进制；不可读返回 None。
def _sha256(p: str):
    try:
        with open(p, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


# 生效条件：p 可读且 nodefile.loads 解析成功时返回 (frontmatter dict, 正文 str)；不可读或解析抛异常时返回 (None, None)。
def _fm_of(p: str):
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            fm, content = nodefile.loads(f.read())
    except (OSError, ValueError):
        return None, None
    return (fm or {}), (content or "")


# 生效条件：fm 为 None 时返回 None；否则返回 evolution.STATE_FIELDS 中存在于 fm 且值非 None 的键值对（「显式为空」的值保留）。
def _state_view(fm):
    if fm is None:
        return None
    from . import evolution as _evo
    return {k: fm[k] for k in _evo.STATE_FIELDS if k in fm and fm[k] is not None}


# 生效条件：main_root 与 shadow_root 为目录时返回按 node_id 键控的语义差异集——双侧皆有而 sha256 不同记 kind="changed"、仅影子有记 "added"、仅主库有记 "removed"；每条带 before/after 认知状态视图、双侧层位、双侧相对路径与双侧 sha256；无差异返回 {}。
def semantic_delta(main_root: str, shadow_root: str) -> dict:
    """Δ = {id → (before, after)}（§4.4 ③；按真源面 .md 的**内容哈希**判定）。"""
    A, B = node_files(main_root), node_files(shadow_root)
    out = {}
    for nid in sorted(set(A) | set(B)):
        a, b = A.get(nid), B.get(nid)
        ha = _sha256(a["abs"]) if a else None
        hb = _sha256(b["abs"]) if b else None
        if a and b:
            if ha == hb:
                continue
            kind = "changed"
        else:
            kind = "added" if b else "removed"
        fma = _fm_of(a["abs"])[0] if a else None
        fmb = _fm_of(b["abs"])[0] if b else None
        out[nid] = {"kind": kind,
                    "main_rel": (a or {}).get("rel"),
                    "shadow_rel": (b or {}).get("rel"),
                    "from_layer": (a or {}).get("layer"),
                    "to_layer": (b or {}).get("layer"),
                    "before": _state_view(fma), "after": _state_view(fmb),
                    "before_lifecycle": (fma or {}).get("lifecycle_state"),
                    "after_lifecycle": (fmb or {}).get("lifecycle_state"),
                    "main_hash": ha, "shadow_hash": hb}
    return out


# 生效条件：root 下 _deletions.jsonl 可读时返回其中 id 字段的集合（不含 None），不可读返回 set()。
def _tombstoned_ids(root: str) -> set:
    out = set()
    p = os.path.join(root, "_deletions.jsonl")
    if not os.path.exists(p):
        return out
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict) and r.get("id"):
                    out.add(r["id"])
    except OSError:
        pass
    return out


# 生效条件：cg_main 为**主库**实例、delta 为 semantic_delta 形状、baseline_face 为 materialize 记录的基准水位（rel→sha256）时，逐项按 §4.4 ③ 的**语义四闸**裁决：保护闸（protect.is_immutable；且「影子侧删除」恒拒——自动整理不删节点）、tombstone 闸（主库 _deletions.jsonl 已记的 id 不得复活）、并发闸（主库在迭代期间改动/新增过同一 id ⇒ 主库优先，记 conflict）、生命周期闸（lifecycle.can_transition）；返回 {"accepted": [id…], "conflicts": [ {id,gate,reason,kind}… ], "rejected": [ {id,gate,reason,kind}… ]}。
def gate_delta(cg_main, delta: dict, *, baseline_face: dict = None,
               shadow_root: str = None) -> dict:
    """语义四闸（§4.4 ③）——**git 的自动文本合并绕过这些闸，故准入在这里**。"""
    from . import crypto as _crypto
    from . import lifecycle as _lc
    from . import protect as _pr
    base = baseline_face or {}
    tomb = _tombstoned_ids(cg_main.root)
    accepted, rejected, conflicts = [], [], []
    for nid in sorted(delta):
        d = delta[nid]
        kind = d["kind"]
        # ⓪ 密文项（保护闸的 fail-closed 面）：影子侧是密文 ⇒ **不在重放面**。
        #   为什么必须在**这里**拦：重放端 `crypto.is_encrypted` 只在写之前跳
        #   过它，而它仍会随影子分支入册 ⇒ 重放后的主库树与影子树不同 ⇒ 合并
        #   被 `tree_divergence` 永久挂起（一处密文节点即堵死整条合并路）。
        #   在此排除后它不进提交、不参与合并（与 consolidate 的 skipped_locked 同款口径）。
        if shadow_root and d.get("shadow_rel"):
            _fm_enc, _c_enc = _fm_of(os.path.join(shadow_root, d["shadow_rel"]))
            if _fm_enc is not None and _crypto.is_encrypted(_c_enc):
                rejected.append({"id": nid, "gate": "protect", "kind": kind,
                                 "reason": ("影子侧为密文节点（无密钥不重放、"
                                            "fail-closed），不入册也不合并")})
                continue
        # ① 保护闸：不可篡改节点不得被改写；**删除永不由自动整理发起**。
        if kind == "removed":
            rejected.append({"id": nid, "gate": "protect", "kind": kind,
                             "reason": ("自动整理不删节点（五环承诺：遗忘只由显式 "
                                        "cg(op=forget) 发起）")})
            continue
        prot, why = _pr.is_immutable(cg_main, nid)
        if prot:
            rejected.append({"id": nid, "gate": "protect", "kind": kind,
                             "reason": why})
            continue
        # ② tombstone 闸：主库已遗忘的 id 不得复活。
        if nid in tomb:
            rejected.append({"id": nid, "gate": "tombstone", "kind": kind,
                             "reason": "主库 _deletions.jsonl 已有该 id 的删除记录，不得复活"})
            continue
        # ③ 并发闸：主库在迭代期间改动/新增过同一 id ⇒ **主库优先**，本项挂起。
        mrel = d.get("main_rel")
        if mrel:
            cur = base.get(mrel)
            if cur is None or d.get("main_hash") != cur:
                conflicts.append({"id": nid, "gate": "concurrent", "kind": kind,
                                  "reason": ("主库在迭代期间改动过同一 id（或新增同名 id）"
                                             "——主库优先，本项挂起不自动解决")})
                continue
        # ④ 生命周期闸：非法迁移不得由睡眠周期写进主库。
        src = d.get("before_lifecycle") or "active"
        dst = d.get("after_lifecycle") or "active"
        if not _lc.can_transition(src, dst):
            rejected.append({"id": nid, "gate": "lifecycle", "kind": kind,
                             "reason": "非法生命周期迁移 %s→%s" % (src, dst)})
            continue
        accepted.append(nid)
    return {"accepted": accepted, "conflicts": conflicts, "rejected": rejected}


# 生效条件：在**影子**工作树上只对 rels 列出的相对路径做白名单 add（显式单文件 pathspec，不走整树 add），暂存区无改动时返回 {"committed": False, "reason": "Δ 为空（无待提交改动）"}，有改动则 commit -m message 并返回 {"committed": True, "commit": <sha>, "paths": rels}；rels 为空即返回零提交。
def _commit_paths(git_dir_path: str, work_tree: str, rels, message: str) -> dict:
    rels = [r for r in dict.fromkeys(rels or []) if r]
    if not rels:
        return {"committed": False, "reason": "Δ 为空（无待提交改动）", "paths": []}
    _git_ok(git_dir_path, work_tree, "add", "--", *rels)
    if _git(git_dir_path, work_tree, "diff", "--cached", "--quiet").returncode == 0:
        return {"committed": False, "reason": "Δ 为空（无待提交改动）",
                "paths": rels}
    _git_ok(git_dir_path, work_tree, "commit", "-m", message)
    return {"committed": True,
            "commit": _git_ok(git_dir_path, work_tree, "rev-parse", "HEAD").strip(),
            "paths": rels}


# 生效条件：root 与 shadow 给定的相对路径集合按 (影子路径 ∪ 主库原路径) 去重返回（层迁移=「新位置新增 + 旧位置删除」两条都要入册，否则合并时旧文件会留在主库）。
def _stage_set(delta: dict, accepted) -> list:
    rels = []
    for nid in accepted:
        d = delta[nid]
        rels.append(d.get("shadow_rel"))
        if d.get("main_rel") and d["main_rel"] != d.get("shadow_rel"):
            rels.append(d["main_rel"])
    return [r for r in dict.fromkeys(rels) if r]


# 生效条件：root 与 shadow 给定且 shadow 存在时，在**根级锁**内算 Δ 并过四闸，把通过者提交到影子分支（rel 集 = 影子新路径 ∪ 主库旧路径），返回 {"ok","busy","lock_held","phase","delta","accepted","conflicts","rejected","committed","commit","paths","branch","source_face_delta"}；取不到锁返回 _busy；影子不存在返回 ok=False 与 error；Δ 为空 ⇒ 零提交、零写入。
def reconcile_gated(root: str = None, *, git_dir_path: str = None,
                    shadow: str = None, branch: str = None, batch: str = None,
                    baseline_face: dict = None, cg=None,
                    timeout: float = DEFAULT_LOCK_TIMEOUT) -> dict:
    """③ 对账 + 提交（§4.4，**持根级锁**）：Δ 逐项过四闸 → 只把通过者入册。"""
    root = os.path.abspath(root or mdcg_root())
    G = git_dir_path or git_dir()
    S = shadow or shadow_dir()
    before = source_face_hashes(root)
    with FileLock(lock_path(), timeout=timeout, strict=False) as lk:
        if not lk.acquired:
            return _busy("reconcile_gated", timeout)
        if not os.path.isdir(S):
            return {"ok": False, "busy": False, "lock_held": True,
                    "phase": "reconcile_gated", "lock": lock_path(),
                    "error": "影子工作树不存在：先 materialize", "shadow": S}
        cgm = cg or _open_cg(root)
        delta = semantic_delta(root, S)
        gated = gate_delta(cgm, delta, baseline_face=baseline_face,
                           shadow_root=S)
        GS = worktree_git_dir(S) or G
        br = branch or _git_ok(GS, S, "rev-parse", "--abbrev-ref", "HEAD").strip()
        rels = _stage_set(delta, gated["accepted"])
        res = _commit_paths(GS, S, rels,
                            "sleep: %s 轮对账提交" % (batch or _stamp()))
        after = source_face_hashes(root)
        return {"ok": True, "busy": False, "lock_held": True,
                "phase": "reconcile_gated", "git_dir": G, "worktree_git_dir": GS,
                "shadow": S, "branch": br, "delta": delta, **gated,
                "committed": res["committed"], "commit": res.get("commit"),
                "reason": res.get("reason"), "paths": res["paths"],
                "lock": lock_path(),
                "source_face_delta": face_delta(before, after)}


# 生效条件：cg_main 为主库实例、shadow_root 为影子目录、delta/accepted 来自 gate_delta 时，把通过项**逐条语义重放**到主库——guard_write 放行后经 `_write_node` 写到影子侧同一相对路径（层迁移时删掉主库旧路径），每条记 `evolution.record`(before/after)，末尾 rebuild_index()；密文节点 fail-closed 跳过（`crypto.is_encrypted`）；返回 {"written": [id…], "skipped": […], "failed": […], "entries": [entry_id…]}。
def replay_to_main(cg_main, shadow_root: str, delta: dict, accepted,
                   *, batch: str = None, actor: str = "sleep") -> dict:
    """④ 的第一半：语义重放 Δ 到主库（**走正常写路径** + 每条 before/after）。"""
    from . import crypto as _crypto
    from . import evolution as _evo
    from . import protect as _pr
    root = cg_main.root
    written, skipped, failed, entries = [], [], [], []
    for nid in accepted:
        d = delta[nid]
        srel = d.get("shadow_rel")
        if not srel:
            continue
        fm, content = _fm_of(os.path.join(shadow_root, srel))
        if fm is None:
            failed.append({"id": nid, "error": "影子节点不可读"})
            continue
        if _crypto.is_encrypted(content):
            skipped.append({"id": nid, "reason": "密文节点不在睡眠重放面（fail-closed）"})
            continue
        try:
            _pr.guard_write(cg_main, nid, layer=d.get("to_layer"), actor=actor)
            cg_main._write_node(nid, os.path.join(root, srel), fm, content)
            mrel = d.get("main_rel")
            if mrel and mrel != srel:
                old = os.path.join(root, mrel)
                if os.path.exists(old):
                    os.remove(old)          # 层迁移：旧位置随之清掉（否则主库留双份）
        except Exception as e:                       # noqa: BLE001 —— 单条失败不带垮整轮
            failed.append({"id": nid, "error": "%s: %s" % (type(e).__name__, e)})
            continue
        try:
            rb = _evo.record(cg_main, node_id=nid,
                             pattern="睡眠周期副本迭代 → 合并回主库（语义重放）",
                             missing="", action="语义重放 Δ（%s）" % d["kind"],
                             evidence="batch=%s gate=ok" % batch,
                             source="sleep", kind=_evo.KIND_GENERAL,
                             before=d.get("before"), after=d.get("after"),
                             extra={"batch": batch})
            entries.append(rb.get("entry_id"))
        except Exception as e:                       # noqa: BLE001 —— 账本失败不阻断写入
            entries.append({"error": "%s: %s" % (type(e).__name__, e)})
        written.append(nid)
    if written:
        try:
            cg_main.rebuild_index()
        except Exception:                            # noqa: BLE001 —— 索引可重建
            pass
    return {"written": written, "skipped": skipped, "failed": failed,
            "entries": entries}


# 生效条件：cg_main/root/branch 给定时，在**根级锁**内——先确认主库工作树 HEAD 在 BASE_BRANCH；把重放结果（+ Δ 的日志面）在白名单 pathspec 上入册并提交为**主库侧的语义重放提交**（= 本轮**内容所在**的提交，回退入口 `round_commit`）；随后确认影子分支与 HEAD 的**树完全相同**（`git diff --quiet` 判）才 `git merge --no-ff <branch>` 留下合并提交（**拓扑记录**：其树同第一父提交，故对内容零影响），树不同则**挂起不合并**（返回 deferred="tree_divergence" 与 conflict_ids）；返回含 ok/phase/replayed/round_commit/replay_commit/merge_commit/conflict/source_face_delta 的字典。
def merge_cycle(cg_main, root: str = None, *, git_dir_path: str = None,
                branch: str, shadow: str = None, delta: dict = None,
                accepted=None, batch: str = None, replay: bool = True,
                timeout: float = DEFAULT_LOCK_TIMEOUT) -> dict:
    """④ 合并（§4.4，**持根级锁**）：语义重放 → `--no-ff` 合并；冲突挂起。"""
    root = os.path.abspath(root or cg_main.root)
    G = git_dir_path or git_dir()
    S = shadow or shadow_dir()
    before = source_face_hashes(root)
    with FileLock(lock_path(), timeout=timeout, strict=False) as lk:
        if not lk.acquired:
            return _busy("merge_cycle", timeout)
        cur = _git_ok(G, root, "rev-parse", "--abbrev-ref", "HEAD").strip()
        if cur != BASE_BRANCH:
            return {"ok": False, "busy": False, "lock_held": True,
                    "phase": "merge_cycle", "lock": lock_path(), "head": cur,
                    "error": "当前 HEAD 在 %s，merge 须在 %s 上执行" % (cur, BASE_BRANCH)}
        rep = (replay_to_main(cg_main, S, delta or {}, accepted or [],
                              batch=batch) if replay
               else {"written": [], "skipped": [], "failed": [], "entries": []})
        out = {"ok": True, "busy": False, "lock_held": True, "phase": "merge_cycle",
               "lock": lock_path(), "branch": branch, "replayed": rep}
        if rep["failed"]:
            out["ok"] = False
            return out
        # 语义重放结果落到主库工作树后，先入册 + 提交（**记录重放**，不是裁决）。
        # 入册面取**显式 rel 集**（新位置 ∪ 旧位置）而非 `pathspecs(root)`：
        # 层迁移会把源层目录搬空，`pathspecs` 滤空目录后就把「旧位置删除」漏掉，
        # 主库 HEAD 会留着旧文件 ⇒ 与影子分支的树不同（本机实测过这个漏）。
        ps = _stage_set(delta or {}, accepted or [])
        if ps:
            _git_ok(G, root, "add", "--", *ps)
            if _git(G, root, "diff", "--cached", "--quiet").returncode != 0:
                _git_ok(G, root, "commit", "-m",
                        "sleep: %s 语义重放 Δ" % (batch or _stamp()))
                # **本轮内容所在的提交**（回退入口）：按 §4.4 的次序，内容由
                # 「语义重放」先写进主库并提交，随后的 `--no-ff` 合并只是**拓扑记录**
                # （其树与第一父提交相同 ⇒ `git revert -m 1 <合并提交>` 对内容零影响，
                # 回退要指向本提交；ops 文档据此登记）。
                out["round_commit"] = _git_ok(G, root, "rev-parse", "HEAD").strip()
        out["replay_commit"] = _git_ok(G, root, "rev-parse", "HEAD").strip()
        # 仅当两侧树**完全相同**才合并（否则让 git 的文本自动合并去裁决就会绕过四闸）
        same = _git(G, root, "diff", "--quiet", branch, "HEAD").returncode == 0
        if not same:
            changed = [ln.strip() for ln in _git(
                G, root, "diff", "--name-only", branch, "HEAD").stdout.splitlines()
                if ln.strip()]
            out.update(deferred="tree_divergence",
                       note="影子分支与重放后的主库树不同 ⇒ 挂起不合并（不自动解决）",
                       conflict_ids=sorted({os.path.basename(p)[:-3]
                                            for p in changed}))
            out["source_face_delta"] = face_delta(before, source_face_hashes(root))
            return out
        r = _git(G, root, "merge", "--no-ff", branch, "-m",
                 "sleep: merge %s into %s" % (branch, BASE_BRANCH))
        if r.returncode != 0:
            txt = (r.stdout + r.stderr).strip()
            out.update(ok=False, conflict="CONFLICT" in txt, error=txt[:500],
                       hint=("冲突不自动解决（照 hive/wm.py 既有裁决）：人工裁决后 "
                             "git add + git commit 收口，或放弃本次合并"))
            out["source_face_delta"] = face_delta(before, source_face_hashes(root))
            return out
        out["merge_commit"] = _git_ok(G, root, "rev-parse", "HEAD").strip()
        out["merged"] = branch
        after = source_face_hashes(root)
        dlt = face_delta(before, after)
        out["source_face_delta"] = dlt
        out["main_written"] = dlt["added"] + dlt["changed"]
        return out


# ---------------- ② 迭代（在影子上跑 §3.1 的 ②–④）----------------

# 生效条件：sh_root 为影子目录时，在其上开一个 MdCGOS 并依次跑第②步归纳（consolidate.induce_memories）、第③步升层（consolidate.promote_memories）、第④步巩固与去污染（scrub.sweep，dry_run=not scrub_apply）；返回 {step: 读数} 的字典。
def iterate(sh_root: str, *, scrub_apply: bool = False) -> dict:
    """②–④ 在**影子**上跑（§4.4 ②）——这三步都是确定性 / 可预演 / 可回滚的。

    ④ 的**实改**由 `MDCG_SLEEP_SCRUB_APPLY` 缺省关住（§3.3 的 ⚠ 档）：
    缺省只在副本上盘点（dry_run），不落盘。
    """
    from . import consolidate as _cd
    from . import scrub as _sc
    cg = _open_cg(sh_root)
    out = {}
    try:
        r2 = _cd.induce_memories(cg, apply=True)
        out["induce"] = {"written": r2.get("written"),
                         "clusters": r2.get("clusters"),
                         "note": r2.get("note")}
        r3 = _cd.promote_memories(sh_root, apply=True)
        out["promote"] = {"written": r3.get("written"),
                          "promoted": (r3.get("promoted") or [])[:8],
                          "targeted": r3.get("targeted"),
                          "note": r3.get("note")}
        r4 = _sc.sweep(cg, dry_run=not scrub_apply)
        out["scrub"] = {"apply": bool(scrub_apply),
                        "dry_run": r4.get("dry_run"),
                        "n_issues": (r4.get("audit") or {}).get("n_issues"),
                        "n_high_medium": r4.get("n_high_medium"),
                        "applied": (r4.get("decontaminate") or {}).get("applied")}
    finally:
        try:
            cg.close()
        except Exception:                            # noqa: BLE001
            pass
    return out


# 生效条件：给定九步台账的原始读数（scan / iterated / delta_digest / 相位 / 轮次 / 上一轮候选数 / skip_reason）时，**恒返回九条**按 STEPS 顺序的台账条目：①恒在（只读）、②③④在有 iterated 时并入读数否则记 skipped=skip_reason、⑤⑥恒记 skipped="未接线"、⑦记本轮 Δ 摘要与台账落点、⑧记候选数前后变化、⑨记方向性自检（只产记录，不自动触发修改）。
def ledger_steps(*, scan: dict, iterated: dict = None, delta_digest: dict = None,
                 phases: dict = None, round_index: int = 1,
                 prev_candidates=None, skip_reason: str = "",
                 self_check_every: int = SELF_CHECK_EVERY) -> list:
    """九步台账（§3.1）——**逐步留读数**；⑤⑥ 恒标 `skipped: "未接线"`。"""
    it = iterated or {}
    steps = [dict(scan, step="recall_scan", name=STEP_NAMES["recall_scan"],
                  readonly=True)]
    for key in ("induce", "promote", "scrub"):
        rec = dict(it.get(key) or {})
        rec.update(step=key, name=STEP_NAMES[key])
        if key not in it:
            rec["skipped"] = skip_reason or "本轮未迭代"
        steps.append(rec)
    for key in ("weights", "reindex"):
        steps.append({"step": key, "name": STEP_NAMES[key],
                      "skipped": "未接线", "planned": NOT_WIRED[key]})
    steps.append({"step": "record", "name": STEP_NAMES["record"],
                  "ledger": ledger_path(), "round": round_index,
                  "delta": delta_digest or {"n": 0, "ids": [], "kinds": {}},
                  "phases": phases or {}})
    cur = (scan or {}).get("candidates")
    steps.append({"step": "feedback", "name": STEP_NAMES["feedback"],
                  "candidates": cur, "prev_round_candidates": prev_candidates,
                  "delta": (cur - prev_candidates)
                  if isinstance(cur, int) and isinstance(prev_candidates, int)
                  else None})
    steps.append({"step": "self_check", "name": STEP_NAMES["self_check"],
                  "round": round_index,
                  "due": bool(round_index % int(self_check_every) == 0),
                  "auto_apply": False,
                  "note": ("方向性自检只产记录，**不自动触发修改**"
                           "（智能论3.4.md:2282）")})
    return steps


# 生效条件：给定 cg（主库）与各相位开关时，按 §3.2 的稳态判据与 §4.4 的四阶段跑一轮睡眠周期并返回台账记录；enabled=False / merge_mode="never" / 窗口外 / 候选数为 0 四种情形**只记账不动手**（②③④记 skipped）；batch 为已合并批次时直接返回 {"idempotent": True} 且零动作。
def run_cycle(cg=None, *, root: str = None, batch: str = None,
              enabled: bool = True, merge_mode: str = None,
              scrub_apply: bool = None, window: str = None,
              round_index: int = 1, now=None, git_dir_path: str = None,
              shadow: str = None, timeout: float = DEFAULT_LOCK_TIMEOUT) -> dict:
    """一轮睡眠周期（§3.1 九步 + §4.4 四阶段）。"""
    root = os.path.abspath(root or (cg.root if cg is not None else mdcg_root()))
    if cg is None:
        cg = _open_cg(root)
    b = batch or _stamp()
    mode = merge_mode or sleep_merge_mode()
    scrub = sleep_scrub_apply() if scrub_apply is None else bool(scrub_apply)
    win = sleep_window() if window is None else window
    led = read_ledger()
    prev = None
    for r in reversed(led):
        if isinstance(r.get("candidates"), int):
            prev = r["candidates"]
            break
    rec = {"op": "sleep", "t": time.time(), "batch": b, "round": round_index,
           "root": root, "merge_mode": mode, "window": win,
           "scrub_apply": bool(scrub)}
    if batch_merged(b):
        rec.update(idempotent=True, merged=False, skipped="同批次已合并（幂等：零改动）",
                   candidates=None, steps=ledger_steps(
                       scan={}, skip_reason="幂等：同批次已合并",
                       round_index=round_index, prev_candidates=prev))
        _append_ledger(rec)
        return rec

    # ① 感知盘点（主库，只读）——稳态判据的口径
    from . import sustain as _sus
    ev = _sus.evolution_candidates(cg)
    scan = {"candidates": ev["candidates"], "ccg_backlog": ev["ccg_backlog"]["n"],
            "importance_drift": ev["importance_drift"]["n"],
            "by_fix": dict(ev.get("by_fix") or {})}
    rec["candidates"] = scan["candidates"]

    gate_reason = None
    if not enabled:
        gate_reason = "MDCG_SLEEP=0（总开关关）"
    elif mode == "never":
        gate_reason = "MDCG_SLEEP_MERGE=never（只记账不迭代）"
    elif not in_window(win, now):
        gate_reason = "窗口外（MDCG_SLEEP_WINDOW=%s；只记账不迭代）" % win
    elif not scan["candidates"]:
        gate_reason = "稳态：盘点候选数为 0（只记账不动手）"

    phases, iterated, delta, digest = {}, None, {}, {"n": 0, "ids": [], "kinds": {}}
    if gate_reason is None:
        m = materialize(root, git_dir_path=git_dir_path, shadow=shadow,
                        ts=b, timeout=timeout)
        phases["materialize"] = {k: m.get(k) for k in
                                 ("ok", "busy", "branch", "shadow", "git_dir",
                                  "baseline", "source_face_delta")}
        if m.get("ok"):
            S = m["shadow"]
            iterated = iterate(S, scrub_apply=scrub)
            phases["iterate"] = iterated
            rc = reconcile_gated(root, git_dir_path=m.get("git_dir"),
                                 shadow=S, branch=m.get("branch"), batch=b,
                                 baseline_face=(m.get("baseline_face") or {}),
                                 cg=cg, timeout=timeout)
            phases["reconcile"] = {k: rc.get(k) for k in
                                   ("committed", "commit", "branch", "reason",
                                    "busy")}
            delta = rc.get("delta") or {}
            digest = {"n": len(delta), "ids": sorted(delta)[:20],
                      "kinds": {k: sum(1 for v in delta.values() if v["kind"] == k)
                                for k in ("added", "removed", "changed")}}
            rec["accepted"] = rc.get("accepted")
            rec["conflicts"] = rc.get("conflicts")
            rec["rejected"] = rc.get("rejected")
            if rc.get("committed") and mode in ("auto", "ask"):
                if mode == "ask":
                    phases["merge"] = {"deferred": "ask",
                                       "note": "MDCG_SLEEP_MERGE=ask：合并留待人工"}
                else:
                    mg = merge_cycle(cg, root, git_dir_path=m.get("git_dir"),
                                     branch=rc.get("branch"), shadow=S,
                                     delta=delta, accepted=rc.get("accepted"),
                                     batch=b, timeout=timeout)
                    phases["merge"] = {k: mg.get(k) for k in
                                       ("ok", "merged", "merge_commit",
                                        "round_commit", "replay_commit",
                                        "deferred", "conflict", "conflict_ids",
                                        "error", "main_written", "busy")}
                    phases["merge"]["replayed"] = (mg.get("replayed") or {}).get("written")
                    rec["merged"] = bool(mg.get("ok")) and not mg.get("deferred")
                    if mg.get("deferred"):
                        rec.setdefault("conflicts", [])
                        rec["conflicts"] = list(rec.get("conflicts") or []) + [
                            {"id": i, "gate": "concurrent",
                             "reason": "影子分支与重放后的主库树不同（挂起不合并）"}
                            for i in (mg.get("conflict_ids") or [])]
            else:
                phases["merge"] = ({"skipped": "本轮无提交（Δ 为空或未提交）"}
                                   if not rc.get("committed")
                                   else {"deferred": mode})

    rec["steps"] = ledger_steps(scan=scan, iterated=iterated,
                                delta_digest=digest, phases=phases,
                                round_index=round_index, prev_candidates=prev,
                                skip_reason=gate_reason or "")
    rec["skipped"] = gate_reason
    _append_ledger(rec)
    return rec


# 生效条件：argv 含 --status 时打印当前解析结果（git_dir / shadow / lock / pathspecs / tracking / history 四读数）的 JSON 并返回 0；argv 含 --audit 时只打印两条机械判据结论（不合规返回 1）；无参数时打印解析结果。
def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="睡眠周期 git 机制（只读判读面）")
    ap.add_argument("--root", default=None, help="数据根（缺省 mdcg_root()）")
    ap.add_argument("--git-dir", dest="git_dir_path", default=None)
    ap.add_argument("--shadow", default=None)
    ap.add_argument("--status", action="store_true", help="打印当前解析与判据读数")
    ap.add_argument("--audit", action="store_true", help="只跑两条机械判据")
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root or mdcg_root())
    G = a.git_dir_path or git_dir()
    shadow = a.shadow or shadow_dir()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.audit:
        tr = audit_tracking(root, git_dir_path=G)
        hi = audit_history(root, git_dir_path=G)
        print(json.dumps({"tracking": tr, "history": hi}, ensure_ascii=False,
                         indent=2))
        return 0 if (tr["ok"] and hi["ok"]) else 1
    out = {"root": root, "git_dir": G, "shadow": shadow, "lock": lock_path(),
           "lock_exists": os.path.exists(lock_path() + ".lock"),
           "git_dir_exists": os.path.isdir(G),
           "shadow_exists": os.path.isdir(shadow),
           "pathspecs": pathspecs(root),
           "source_face_md": len(source_face_hashes(root))}
    if os.path.isdir(G):
        out["tracking"] = audit_tracking(root, git_dir_path=G)
        out["history"] = audit_history(root, git_dir_path=G)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
