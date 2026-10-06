# -*- coding: utf-8 -*-
"""test_sleep_gitlock · 影子仓 git 残留锁**有界自清**守卫（2026-10-06 落地 issue #63 待裁项）。

契约（`md_cg/sleep.py::_clear_git_lock` 三闸口径）：
  ① 范围＝仅睡眠影子仓的 `index.lock`（本模块单属仓）；
  ② `force=True` 仅在本模块刚 kill 掉自己超时的 git 后调用（此刻仓内锁只可能
     是被 kill 进程的残留）；非 force（`_git` 调用前置巡检）只在锁 mtime 距今
     ≥ `_GIT_LOCK_STALE_S`（300s，≫ 全部调用的 120s 超时上界）时清理（崩溃残留）；
  ③ 其余一律不动（返回 "left"，人工核删指引保留）；清理动作记一行
     `git_lock_cleared` 台账。

断言（S1–S8）：
  S1 无锁 → "absent"；S2 **新锁未超龄 → "left" 且文件完好（防一刀切）**；
  S3 超龄锁 → "cleared" 且文件删除；S4 force 对新锁 → 立清（超时 kill 时机）；
  S5 台账两行 `git_lock_cleared` 可读、含 age_s/force；
  S6 `_git` 前置巡检清超龄锁（走公共出口）；S7 前置巡检不误删新锁；
  S8 超时路径：`subprocess.run` 抛 `TimeoutExpired`（monkeypatch）→ 抛
     `SleepGitTimeout`、消息带「已自动清理」读数、先前新锁已被 force 清。

隔离：`MDCG_STATE_ROOT`/`MDCG_ROOT`/`MDCG_AUX_ROOT` 全指临时目录（台账亦落
临时根，绝不触在役状态面）；monkeypatch 在 finally 里还原。
运行：python -X utf8 -m md_cg.test_sleep_gitlock
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time

from . import sleep as S

_saved = {}
_ok = 0
_fail = []


def _sandbox():
    for k in ("MDCG_STATE_ROOT", "MDCG_ROOT", "MDCG_AUX_ROOT"):
        _saved[k] = os.environ.get(k)
    gen = tempfile.mkdtemp(prefix="mdcg_gitlock_")
    os.environ["MDCG_STATE_ROOT"] = os.path.join(gen, "state")
    os.environ["MDCG_ROOT"] = os.path.join(gen, "root")
    os.environ["MDCG_AUX_ROOT"] = os.path.join(gen, "aux")
    return gen


def _restore():
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("[ok] " + name)
    else:
        _fail.append(name)
        print("[FAIL] %s  · %s" % (name, str(detail)[:240]))


def _put_lock(d, age_s=0.0):
    p = os.path.join(d, S._GIT_LOCK_NAME)
    with open(p, "w", encoding="utf-8") as f:
        f.write("")
    if age_s:
        t = time.time() - age_s
        os.utime(p, (t, t))
    return p


gen = _sandbox()
gdir = os.path.join(gen, "gitdir")
os.makedirs(gdir)
try:
    check("S1 无锁 → absent", S._clear_git_lock(gdir) == "absent")

    p2 = _put_lock(gdir)
    check("S2 新锁未超龄 → left 且保持在场（防一刀切）",
          S._clear_git_lock(gdir) == "left" and os.path.exists(p2))

    p3 = _put_lock(gdir, age_s=S._GIT_LOCK_STALE_S + 60)
    check("S3 超龄锁 → cleared 且文件删除",
          S._clear_git_lock(gdir) == "cleared" and not os.path.exists(p3))

    p4 = _put_lock(gdir)
    check("S4 force 对新锁立清（超时 kill 后时机）",
          S._clear_git_lock(gdir, force=True) == "cleared"
          and not os.path.exists(p4))

    rows = [r for r in S.read_ledger() if r.get("event") == "git_lock_cleared"]
    check("S5 台账两行 git_lock_cleared（age_s/force 在场）",
          len(rows) == 2 and all("age_s" in r and "force" in r for r in rows),
          rows)

    p6 = _put_lock(gdir, age_s=S._GIT_LOCK_STALE_S + 60)
    S._git(gdir, gen, "rev-parse", "--git-dir")     # rc 不论；重点＝前置巡检
    check("S6 _git 前置巡检清超龄锁（公共出口生效）", not os.path.exists(p6))

    p7 = _put_lock(gdir)
    S._git(gdir, gen, "rev-parse", "--git-dir")
    check("S7 _git 前置巡检不误删新锁（年龄闸）", os.path.exists(p7))

    real_run = subprocess.run

    def _boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="git boom",
                                        timeout=S._GIT_TIMEOUT_S)

    subprocess.run = _boom
    msg = ""
    try:
        S._git(gdir, gen, "status")
    except S.SleepGitTimeout as e:
        msg = str(e)
    finally:
        subprocess.run = real_run
    check("S8 超时→SleepGitTimeout；消息带处置读数且新锁被 force 清",
          "残留锁处置" in msg and "已自动清理" in msg and not os.path.exists(p7),
          msg)
finally:
    _restore()
    shutil.rmtree(gen, ignore_errors=True)

print("=" * 58)
print("test_sleep_gitlock: %d 通过 / %d 失败" % (_ok, len(_fail)))
if _fail:
    print("失败项：" + "、".join(_fail))
raise SystemExit(1 if _fail else 0)
