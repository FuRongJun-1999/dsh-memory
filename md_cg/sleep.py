# -*- coding: utf-8 -*-
"""md_cg · 睡眠周期的 git 机制（P0-1：根级锁 + 影子工作树 + 独立 git 目录）

设计正身：`docs/plans/睡眠与自迭代_功能优化设计_v0.4.md` §四（§4.1 / §4.2 / §4.4 /
§4.5）。本模块**只落机制与机械判据**——不接周期循环、不跑迭代步骤（那是 P1）：
三段动作（物化 / 对账+提交 / 合并）可用、可持锁、可判读，但**没有任何自动触发源**，
也没有任何调用方（P1 才接线）。

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

from .datapath import mdcg_root, state_root
from .fsutil import FileLock
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


class SleepError(Exception):
    """git 操作失败（带 stderr 摘要）。"""


# 生效条件：无入参；恒返回 state_root() 下 "sleep" 的拼接路径（**不触盘**）。随 ENV_STATE_ROOT / DSH_HOME 解析结果变化——故不得缓存为模块常量。
def sleep_root() -> str:
    """睡眠面根目录（版本库 / 影子 / 锁文件的父目录，**在数据根之外**）。"""
    return os.path.join(state_root(), SLEEP_DIRNAME)


# 生效条件：explicit 非空时经 abspath 归一返回；否则取 env MDCG_SLEEP_GITDIR（非空）经 abspath 返回；两者皆空时返回 sleep_root() 下 "lib.git" 的拼接路径。不触盘、不建目录。
def git_dir(explicit: str = None) -> str:
    """独立 git 目录（§4.7 `MDCG_SLEEP_GITDIR`；缺省 `state_root()/sleep/lib.git`）。"""
    v = explicit or os.environ.get("MDCG_SLEEP_GITDIR")
    return os.path.abspath(v) if v else os.path.join(sleep_root(), GITDIR_DIRNAME)


# 生效条件：explicit 非空时经 abspath 归一返回；否则取 env MDCG_SLEEP_SHADOW（非空）经 abspath 返回；两者皆空时返回 sleep_root() 下 "shadow" 的拼接路径。不触盘。
def shadow_dir(explicit: str = None) -> str:
    """影子工作树落点（§4.7 `MDCG_SLEEP_SHADOW`；缺省 `state_root()/sleep/shadow`）。"""
    v = explicit or os.environ.get("MDCG_SLEEP_SHADOW")
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
    """
    os.makedirs(os.path.dirname(os.path.abspath(git_dir_path)), exist_ok=True)
    created = not os.path.isdir(git_dir_path)
    if created:
        _git_ok(git_dir_path, root, "init", "-b", BASE_BRANCH)
    for k, v in (("user.name", GIT_USER_NAME), ("user.email", GIT_USER_EMAIL),
                 ("core.quotepath", "false")):
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
                "source_face_count": len(after)}


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
