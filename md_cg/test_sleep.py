# -*- coding: utf-8 -*-
"""睡眠周期 git 机制守卫（P0-1：根级锁 + 影子工作树 + 独立 git 目录）。

契约（设计稿 `docs/plans/睡眠与自迭代_功能优化设计_v0.4.md` §八 P0-1 / §4.1 /
§4.2 / §4.4 / §4.5）：

    ① 迭代期间主库真源面**逐字节不变**（8 个 LAYERS 目录下全部 .md 的内容哈希集合对拍）；
    ② git 历史里 `_keys.json` / `_access.log` / `_index.json` / `*.tmp` / `*.lock`
       **零命中**；版本库追踪集合 **⊆ 8 个 LAYERS 目录** 且 **⊇ 其下全部 .md**；
    ③ 两进程同时触发睡眠**只有一个拿到根级锁**（要有可判读数）；锁文件落
       `state_root` 侧而非数据根；**绝不在数据根内建 `.git`**；
    ④ 回滚**只提供 `revert`**（不提供抹历史的强推档）。

断言分组：

  G0 隔离与落点——沙箱四根全落守卫临时目录；锁文件在 `state_root` 侧、**不在数据根**；
     影子落 `state_root()/sleep/shadow`。
  G1 静态形态（字面量面）——`sleep.py` 内 `add -A` / `add .` / `checkout` /
     `reset --hard` **零命中**；`--git-dir=` 与 `--work-tree=` 显式形态在位；
     `LAYERS` 自 `md_cg.mdcg` **单点导入**（对象同一，非第二份副本）。
  G2 物化——主库真源面哈希集合前后**逐字节相同**；影子挂上且有 `.git`；
     数据根内**无 `.git`**（目录与文件都无）；独立 git 目录在 `state_root` 侧；
     根里planted 的密钥/临时/锁件**不在追踪集合**里；两条机械判据全绿。
  G3 对账 + 提交（在**影子**上）——提交确实发生；主库真源面**仍逐字节不变**；
     影子里的新增 .md 入册；影子里 planted 的密钥/临时/锁件**不入册**
     （历史判据仍零命中）。
  G4 合并——`--no-ff` 合回 main；主库**只多出应写的那一个 .md**（根里的 planted
     非白名单件原样不动、仍不在追踪集合）；两条机械判据仍全绿。
  G5 回滚——`revert` 出一个反向提交：主库真源面回到合并前；**历史不丢**
     （合并提交与被还原路径仍在 `log --all --name-only` 里）。
  G6 根级锁跨进程唯一——父进程持锁时另起**子进程**调 `materialize` 必须
     `busy=True` 且不取得锁；父进程释放后同一子进程脚本转 `ok=True`。
  G7 判据自身有判别力（正对照）——改动一个 .md 后 `face_delta` 必须报 changed；
     给根里加一个非白名单 .md 之外的件不改变判据（负对照）。

运行：python -X utf8 -m md_cg.test_sleep
      python -X utf8 -m md_cg.test_sleep --mutate         # 定点变异自证
      python -X utf8 -m md_cg.test_sleep --mutate --list  # 只列变异表

退出码（fail-closed）：0 = 全绿；1 = 有断言失败 / 变异未按预期转红；
2 = ANCHOR-MISS（变异锚点在当前源码里找不到）。

**基线纪律**：不以 git HEAD 为基线源——「改动前形态」由在当前工作区源码上做
**定点文本变异**（`_MUTATIONS`）复现，锚点漂移即退出码 2。
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types

from . import mdcg as M
from . import sleep as SL
from .fsutil import FileLock

_PASS = []
_FAIL = []
_SKIP = []
_SRC = {}
#: 变异核验上下文：{"mutsrc": <变异源码落盘路径>}——G6 的子进程据此载入变异模块
#: （子进程读真源码，不共享父进程内存里的变异；不给它这份落盘件，跨进程那条
#: 断言就对「不校验锁」的变异失明——本机实测过一次）。
_MUT_CTX = {}
_GEN = [0]
_TMP = tempfile.mkdtemp(prefix="mdcg_sleep_")
_SAVED = {}
_REAL_SL = SL

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 安放在数据根里的**非白名单件**（§4.5 判据一逐一覆盖）：密钥面 / 运行态 /
#: 派生面 / 临时件 / 锁件。
DECOYS = {"_keys.json": '{"k":"v"}',
          "_access.log": "a\tb\n",
          "_index.json": '{"schema":1}',
          "junk.tmp": "tmp",
          "other.lock": "lock"}


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


def _rel_text(rel: str) -> str:
    if rel in _SRC:
        return _SRC[rel]
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


def _sandbox_env():
    for k in ("MDCG_ROOT", "MDCG_AUX_ROOT", "MDCG_STATE_ROOT",
              "MDCG_SLEEP_GITDIR", "MDCG_SLEEP_SHADOW"):
        _SAVED[k] = os.environ.get(k)
        os.environ.pop(k, None)


def _restore_env():
    for k, v in _SAVED.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _fixture():
    """建一个沙箱数据面：8 个 LAYERS 目录（其中 7 个为空——专门压 pathspec 白名单
    必须滤空目录这条）+ 若干 .md + 五个非白名单件。返回 (gen 根, 数据根, 状态根)。"""
    _GEN[0] += 1
    gen = os.path.join(_TMP, "gen%d" % _GEN[0])
    root = os.path.join(gen, "data", "mdcg")
    state = os.path.join(gen, "state")
    for L in M.LAYERS:
        os.makedirs(os.path.join(root, L), exist_ok=True)
    for nid, layer in (("n_a", "knowledge"), ("n_b", "knowledge"),
                       ("n_c", "contextual")):
        p = os.path.join(root, layer, nid + ".md")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write("# 功能名：%s\n# 生效条件：全时窗\n# 子功能：s\n# 执行：e\n"
                    "# 验证方式：test\n# 不适用条件：无\n" % nid)
    for name, body in DECOYS.items():
        with open(os.path.join(root, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
    os.makedirs(state, exist_ok=True)
    os.environ["MDCG_STATE_ROOT"] = state
    os.environ["MDCG_ROOT"] = root
    os.environ["MDCG_AUX_ROOT"] = os.path.join(gen, "aux")
    return gen, root, state


# ---------------------------------------------------------------- G0
def g0():
    print("== G0 隔离与落点 ==")
    S = globals()["SL"]
    gen, root, state = _fixture()
    lp = S.lock_path()
    ok(lp == os.path.join(state, "sleep", "sleep"),
       "G0a 锁文件在 state_root 侧：<state_root>/sleep/sleep(.lock)", lp)
    ok(not lp.startswith(root + os.sep),
       "G0b 锁文件**不在数据根内**（否则会进真源面观测面）", lp)
    ok(S.shadow_dir() == os.path.join(state, "sleep", "shadow"),
       "G0c 影子落 state_root()/sleep/shadow（§4.7 缺省）", S.shadow_dir())
    ok(S.git_dir() == os.path.join(state, "sleep", "lib.git"),
       "G0d 独立 git 目录落 state_root()/sleep/lib.git", S.git_dir())
    ok(S.SLEEP_DIRNAME == "sleep" and S.GITDIR_DIRNAME == "lib.git"
       and S.SHADOW_DIRNAME == "shadow",
       "G0e 三个落点常量与 §4.1 的布局逐字一致")


# ---------------------------------------------------------------- G1
def g1():
    print("== G1 静态形态（字面量面）==")
    s = _rel_text("md_cg/sleep.py")
    for lit in ("add -A", "add .", "checkout", "reset --hard"):
        ok(s.count(lit) == 0,
           "G1 `%s` 在 sleep.py 内零命中（不含注释里的引述）" % lit,
           s.count(lit))
    ok(s.count("--git-dir=") >= 1 and s.count("--work-tree=") >= 1,
       "G1a git 调用一律 --git-dir + --work-tree 显式形态",
       (s.count("--git-dir="), s.count("--work-tree=")))
    ok("from .mdcg import LAYERS" in s,
       "G1b LAYERS 自 md_cg.mdcg **单点导入**（不硬编码第二份白名单）")
    import re as _re
    ok(_re.search(r'\["git", "--git-dir=" \+ git_dir_path, "--work-tree=" \+ work_tree\]', s),
       "G1c 唯一 git 出口的 argv 形态逐字可读（--git-dir / --work-tree 并列）")


# ---------------------------------------------------------------- G2
def _paths(root):
    return globals()["SL"].source_face_hashes(root)


def g2():
    print("== G2 物化（持根级锁）==")
    S = globals()["SL"]
    gen, root, state = _fixture()
    G = os.path.join(state, "sleep", "lib.git")
    SH = os.path.join(state, "sleep", "shadow")
    before = S.source_face_hashes(root)
    ok(len(before) == 3, "G2 前置：真源面 3 个 .md", sorted(before))
    m = S.materialize(root=root, git_dir_path=G, shadow=SH, ts="G2T1")
    ok(m.get("ok") is True,
       "G2a 物化成功（ok=True）", {k: m.get(k) for k in
                                  ("ok", "busy", "error", "hint")})
    ok(m.get("busy") is False and m.get("lock_held") is True,
       "G2b 物化在**已取得**根级锁下完成（lock_held=True）", m.get("lock"))
    ok(m["source_face_delta"] == {"added": [], "removed": [], "changed": []},
       "G2c 物化全程**主库真源面逐字节不变**（内容哈希集合三键全空）",
       m["source_face_delta"])
    ok(S.source_face_hashes(root) == before,
       "G2d 物化后重算真源面哈希与物化前**逐位相同**")
    ok(os.path.isdir(SH) and os.path.exists(os.path.join(SH, ".git")),
       "G2e 影子已挂上（git worktree，含 .git 文件）", SH)
    wg = S.worktree_git_dir(SH)
    ok(wg.startswith(os.path.join(G, "worktrees")) and os.path.isdir(wg),
       "G2e2 影子有**专属** gitdir（<lib.git>/worktrees/<名>）——对账提交靠它把"
       "提交落到 sleep 分支而不是 main", wg)
    ok(not os.path.exists(os.path.join(root, ".git")),
       "G2f **数据根内无 .git**（目录与文件都没有）")
    ok(os.path.isdir(G) and G.startswith(state),
       "G2g 版本库在 state_root 侧（独立 git 目录）", G)
    ok(m["branch"].startswith("sleep/"),
       "G2h 影子分支名形如 sleep/<时间戳>", m["branch"])
    ok(S.pathspecs(root) == ["knowledge", "contextual"],
       "G2i pathspec 白名单 = 盘上非空的 LAYERS 目录（空目录被滤掉）",
       S.pathspecs(root))
    # 两条机械判据
    hi = S.audit_history(root, git_dir_path=G)
    tr = S.audit_tracking(root, git_dir_path=G)
    ok(hi["ok"] and not hi["hits"],
       "G2j 判据一：历史里 _keys.json/_access.log/_index.json/*.tmp/*.lock 零命中",
       hi["hits"])
    ok(tr["ok"] and not tr["outside_layers"] and not tr["missing_md"],
       "G2k 判据二：追踪集合 ⊆ LAYERS 目录 且 ⊇ 其下全部 .md",
       {"outside": tr["outside_layers"], "missing": tr["missing_md"]})
    # 安放在根里的非白名单件仍原样在盘上、且不在追踪集合
    for name in DECOYS:
        ok(os.path.exists(os.path.join(root, name)),
           "G2l 非白名单件 %s 仍在数据根（物化不搬它）" % name)
    tracked = S.tracked_paths(root, git_dir_path=G)
    ok(not any(p.rsplit("/", 1)[-1] in DECOYS for p in tracked),
       "G2m 非白名单件**不在**追踪集合里", tracked)
    ok(sorted(tracked) == sorted(before.keys()),
       "G2n 追踪集合 = 真源面 .md 全集（刚好相等）",
       (sorted(tracked), sorted(before)))


# ---------------------------------------------------------------- G3
def g3():
    print("== G3 对账 + 提交（在影子上）==")
    S = globals()["SL"]
    gen, root, state = _fixture()
    G = os.path.join(state, "sleep", "lib.git")
    SH = os.path.join(state, "sleep", "shadow")
    S.materialize(root=root, git_dir_path=G, shadow=SH, ts="G3T1")
    # 模拟 P1 在影子上的迭代改动 + 影子里也安放非白名单件
    newrel = "knowledge/n_new.md"
    with open(os.path.join(SH, "knowledge", "n_new.md"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write("# 功能名：n_new\n# 生效条件：全时窗\n# 子功能：s\n# 执行：e\n"
                "# 验证方式：test\n# 不适用条件：无\n")
    for name, body in DECOYS.items():
        with open(os.path.join(SH, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
    before_root = S.source_face_hashes(root)
    rc = S.reconcile_and_commit(root=root, git_dir_path=G, shadow=SH)
    ok(rc.get("ok") is True and rc.get("committed") is True,
       "G3 影子上的改动被提交（一次调用 = 一个提交）",
       {k: rc.get(k) for k in ("ok", "committed", "reason", "error")})
    ok(rc["source_face_delta"] == {"added": [], "removed": [], "changed": []},
       "G3a 提交阶段**主库真源面仍逐字节不变**（迭代段不碰主库）",
       rc["source_face_delta"])
    ok(S.source_face_hashes(root) == before_root,
       "G3b 提交后重算主库真源面哈希与之前逐位相同")
    wg = rc["worktree_git_dir"]
    sh_tracked = S.tracked_paths(SH, git_dir_path=wg)
    ok(newrel in sh_tracked, "G3c 影子里的新 .md 已入册（白名单内）", sh_tracked)
    ok(not any(p.rsplit("/", 1)[-1] in DECOYS for p in sh_tracked),
       "G3d 影子里安放的非白名单件**不入册**（白名单是唯一入口）", sh_tracked)
    hi = S.audit_history(root, git_dir_path=G)
    ok(hi["ok"], "G3e 提交后历史判据仍零命中（影子里的密钥/锁/临时件进不去）",
       hi["hits"])
    cur = SL._git_ok(G, root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    ok(cur == "main", "G3f 主库工作树 HEAD 仍在 main（物化/提交不动主线）", cur)
    # 关键：提交必须落在 sleep 分支上，main 仍在基线（否则「影子迭代 + 周期合并」
    # 变成「直接改主线」——本机实测过这个错法：--git-dir 取主那份即落到 main）
    n_main = SL._git_ok(G, root, "rev-list", "--count", "main").strip()
    n_br = SL._git_ok(G, root, "rev-list", "--count", rc["branch"]).strip()
    ok(n_main == "1" and n_br == "2",
       "G3h 提交落在 sleep 分支（main 仍 = 基线 1 个提交；分支 = 2）",
       (n_main, n_br, rc["branch"]))
    ok(SL._git_ok(G, root, "rev-parse", "main").strip()
       == SL._git_ok(G, root, "rev-parse", "main~0").strip()
       and SL._git_ok(G, root, "rev-parse", rc["branch"]).strip()
       != SL._git_ok(G, root, "rev-parse", "main").strip(),
       "G3i sleep 分支与 main 指向不同提交（分支真的前进了）")
    # 无改动再来一次 → 零提交（Δ 为空整轮跳过）
    rc2 = S.reconcile_and_commit(root=root, git_dir_path=G, shadow=SH)
    ok(rc2.get("committed") is False and "Δ 为空" in (rc2.get("reason") or ""),
       "G3g 重复对账＝零提交（Δ 为空则整轮跳过）", rc2.get("reason"))


# ---------------------------------------------------------------- G4
def g4():
    print("== G4 合并（持根级锁，写主库的只有应写那部分）==")
    S = globals()["SL"]
    gen, root, state = _fixture()
    G = os.path.join(state, "sleep", "lib.git")
    SH = os.path.join(state, "sleep", "shadow")
    m = S.materialize(root=root, git_dir_path=G, shadow=SH, ts="G4T1")
    branch = m["branch"]
    body = ("# 功能名：n_merged\n# 生效条件：全时窗\n# 子功能：s\n# 执行：e\n"
            "# 验证方式：test\n# 不适用条件：无\n")
    with open(os.path.join(SH, "knowledge", "n_merged.md"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write(body)
    S.reconcile_and_commit(root=root, git_dir_path=G, shadow=SH)
    before = S.source_face_hashes(root)
    mg = S.merge(root=root, git_dir_path=G, branch=branch)
    ok(mg.get("ok") is True, "G4 合并成功（--no-ff 合回 main）",
       {k: mg.get(k) for k in ("ok", "error", "conflict", "hint")})
    ok(mg["main_written"] == ["knowledge/n_merged.md"],
       "G4a 主库**只多出应写的那一个 .md**（main_written 逐项）",
       mg["main_written"])
    after = S.source_face_hashes(root)
    ok(after.get("knowledge/n_merged.md") is not None
       and all(after.get(k) == v for k, v in before.items())
       and len(after) == len(before) + 1,
       "G4b 合并后主库真源面 = 合并前 + 恰好一个新件（其余逐位不变）",
       S.face_delta(before, after))
    got = open(os.path.join(root, "knowledge", "n_merged.md"),
               encoding="utf-8").read()
    ok(got == body, "G4c 合并进来的内容与影子里写下的逐字节相同")
    for name, want in DECOYS.items():
        p = os.path.join(root, name)
        ok(os.path.exists(p) and open(p, encoding="utf-8").read() == want,
           "G4d 数据根里的非白名单件 %s 原样未被合并触碰" % name)
    tracked = S.tracked_paths(root, git_dir_path=G)
    ok(not any(p.rsplit("/", 1)[-1] in DECOYS for p in tracked)
       and set(tracked) == set(after),
       "G4e 合并后追踪集合 = 真源面 .md 全集（非白名单件仍不可达）",
       (sorted(set(tracked) - set(after)), sorted(set(after) - set(tracked))))
    hi = S.audit_history(root, git_dir_path=G)
    tr = S.audit_tracking(root, git_dir_path=G)
    ok(hi["ok"] and tr["ok"],
       "G4f 合并后两条机械判据仍全绿",
       {"history": hi["hits"], "outside": tr["outside_layers"],
        "missing": tr["missing_md"]})


# ---------------------------------------------------------------- G5
def g5():
    print("== G5 回滚（只 revert，历史不丢）==")
    S = globals()["SL"]
    gen, root, state = _fixture()
    G = os.path.join(state, "sleep", "lib.git")
    SH = os.path.join(state, "sleep", "shadow")
    m = S.materialize(root=root, git_dir_path=G, shadow=SH, ts="G5T1")
    with open(os.path.join(SH, "knowledge", "n_rev.md"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write("# 功能名：n_rev\n# 生效条件：全时窗\n# 子功能：s\n# 执行：e\n"
                "# 验证方式：test\n# 不适用条件：无\n")
    S.reconcile_and_commit(root=root, git_dir_path=G, shadow=SH)
    before_merge = S.source_face_hashes(root)
    mg = S.merge(root=root, git_dir_path=G, branch=m["branch"])
    ok(mg.get("ok") is True, "G5 前置：合并成功")
    hist_before = set(S.history_paths(root, git_dir_path=G))
    rv = S.revert(mg["commit"], root, git_dir_path=G)
    ok(rv.get("ok") is True, "G5a revert 成功（反向提交）",
       {k: rv.get(k) for k in ("ok", "error", "conflict", "hint")})
    ok(rv.get("merge_commit") is True,
       "G5b merge commit 自动 -m 1（撤销该次合并引入的变更）", rv.get("merge_commit"))
    ok(S.source_face_hashes(root) == before_merge,
       "G5c 回滚后主库真源面 == 合并前（逐位）",
       S.face_delta(before_merge, S.source_face_hashes(root)))
    hist_after = set(S.history_paths(root, git_dir_path=G))
    ok("knowledge/n_rev.md" in hist_after,
       "G5d **历史不丢**：被回滚的路径仍在 log --all --name-only 里",
       sorted(hist_after - hist_before))
    ok(hist_after >= hist_before,
       "G5e 历史是 append-only：回滚只增不减（revert 自身也进历史）")
    n_commits = int(SL._git_ok(G, root, "rev-list", "--count", "HEAD").strip())
    ok(n_commits >= 4,
       "G5f 提交数 >= 4（基线 / 对账 / 合并 / 回滚各一个 —— 实测 %s）" % n_commits)
    ok(S.audit_history(root, git_dir_path=G)["ok"],
       "G5g 回滚后历史判据仍零命中")


# ---------------------------------------------------------------- G6
_CHILD_SRC = '''# -*- coding: utf-8 -*-
import json, sys, types
sys.path.insert(0, r"%(repo)s")
import md_cg                                   # 真包（datapath/fsutil/mdcg 走真源）
_mut = r"%(mutsrc)s"
if _mut:
    # 变异核验：把（变异后的）机制源码当 md_cg.sleep 载入——G6 才吃得下变异
    with open(_mut, encoding="utf-8") as _f:
        _src = _f.read()
    _ns = {"__name__": "md_cg.sleep", "__package__": "md_cg", "__file__": _mut}
    exec(compile(_src, "sleep_mut.py", "exec"), _ns)
    _m = types.ModuleType("md_cg.sleep")
    _m.__dict__.update(_ns)
    sys.modules["md_cg.sleep"] = _m
    sleep = _m
else:
    from md_cg import sleep
r = sleep.materialize(root=r"%(root)s", git_dir_path=r"%(git)s",
                      shadow=r"%(shadow)s", ts="CHILD", timeout=0.6)
print("RESULT " + json.dumps({k: r.get(k) for k in
      ("ok", "busy", "lock_held", "phase", "lock", "reason")},
      ensure_ascii=False))
'''


def _run_child(gen, root, G, SH, mutsrc: str = ""):
    p = os.path.join(gen, "child_probe.py")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(_CHILD_SRC % {"repo": _REPO.replace("\\", "\\\\"),
                              "root": root.replace("\\", "\\\\"),
                              "git": G.replace("\\", "\\\\"),
                              "shadow": SH.replace("\\", "\\\\"),
                              "mutsrc": mutsrc.replace("\\", "\\\\")})
    env = dict(os.environ, PYTHONUTF8="1")
    r = subprocess.run([sys.executable, "-X", "utf8", p], capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       env=env, shell=False)
    for line in (r.stdout or "").splitlines():
        if line.startswith("RESULT "):
            return json.loads(line[len("RESULT "):]), r
    return None, r


def g6():
    print("== G6 根级锁跨进程唯一（两进程同时触发只有一个能进）==")
    S = globals()["SL"]
    gen, root, state = _fixture()
    G = os.path.join(state, "sleep", "lib.git")
    SH = os.path.join(state, "sleep", "shadow")
    lp = S.lock_path()
    mutsrc = _MUT_CTX.get("mutsrc", "")
    with FileLock(lp, timeout=5.0, strict=False) as lk:
        ok(lk.acquired is True, "G6 前置：父进程已持根级锁", lp)
        got, r = _run_child(gen, root, G, SH, mutsrc)
        ok(got is not None,
           "G6a 子进程跑通（前置：能取到读数）", (r.stdout or "")[-200:])
        if got:
            ok(got["busy"] is True and got["lock_held"] is False
               and got["ok"] is False,
               "G6b 父进程持锁期间，子进程 materialize → busy=True（拿不到锁）",
               got)
            ok(os.path.exists(lp + ".lock"),
               "G6c 锁件实际落点 = <state_root>/sleep/sleep.lock", lp + ".lock")
            ok(not (lp + ".lock").startswith(root + os.sep),
               "G6d 锁件不在数据根内")
    # 释放后同一子进程脚本必须能进
    got2, r2 = _run_child(gen, root, G, SH, mutsrc)
    ok(got2 is not None and got2["busy"] is False and got2["ok"] is True,
       "G6e 父进程释放后，同一子进程转 ok=True（锁可达、非死锁）",
       got2 if got2 else (r2.stdout or "")[-200:])


# ---------------------------------------------------------------- G7
def g7():
    print("== G7 判据自身的判别力（正/负对照）==")
    S = globals()["SL"]
    gen, root, state = _fixture()
    a = S.source_face_hashes(root)
    # 正对照：改一个 .md 的正文 → changed 必报
    p = os.path.join(root, "knowledge", "n_a.md")
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        f.write("补一行\n")
    b = S.source_face_hashes(root)
    d = S.face_delta(a, b)
    ok(d["changed"] == ["knowledge/n_a.md"] and not d["added"] and not d["removed"],
       "G7 正对照：真源面内容改动被 face_delta 报为 changed", d)
    # 负对照：动一个非白名单件 → 真源面哈希集合**不变**（判据面不掺派生/密钥面）
    with open(os.path.join(root, "_keys.json"), "w", encoding="utf-8") as f:
        f.write('{"k":"v2"}')
    with open(os.path.join(root, "junk.tmp"), "w", encoding="utf-8") as f:
        f.write("tmp2")
    c = S.source_face_hashes(root)
    ok(c == b, "G7a 负对照：动密钥/临时件**不改变**真源面哈希集合（判据面被钉死）")
    # 正对照：新增 .md → added；删除 .md → removed
    for L in ("knowledge", "anchor"):
        os.makedirs(os.path.join(root, L), exist_ok=True)
    with open(os.path.join(root, "anchor", "n_d.md"), "w", encoding="utf-8",
              newline="\n") as f:
        f.write("x")
    d1 = S.face_delta(c, S.source_face_hashes(root))
    ok(d1["added"] == ["anchor/n_d.md"] and not d1["removed"],
       "G7b 正对照：新增 .md 被报为 added", d1)
    with_p = S.source_face_hashes(root)
    os.remove(os.path.join(root, "anchor", "n_d.md"))
    d2 = S.face_delta(with_p, S.source_face_hashes(root))
    ok(d2["removed"] == ["anchor/n_d.md"] and not d2["added"],
       "G7c 正对照：删除 .md 被报为 removed", d2)


_GROUPS = (g0, g1, g2, g3, g4, g5, g6, g7)


def _run_groups() -> int:
    _GEN[0] += 1                       # 每轮换 gen：沙箱与状态根全新，互不串味
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        try:
            g()
        except Exception as exc:                       # noqa: BLE001
            ok(False, "断言组 %s 抛异常：%s" % (g.__name__, exc))
            import traceback
            print(traceback.format_exc()[-900:])
    return len(_FAIL)


# ---------------------------------------------------------------- 变异表
# 锚点 = (名字, rel, old, new)。每次变异必须让套件**转红**：
#   M1 白名单不滤空目录（旧形态：把 LAYERS 目录名整表喂给 add）→ add 整体失败
#   M2 add 退回整树形态（不带 pathspec）→ 数据根里的密钥/临时/锁件被入册
#   M3 materialize 不校验锁（旧形态：无根级锁）→ 跨进程唯一性判据失效
#   M4 影子改落 state_root 根（不在 sleep/ 下）→ 落点判据失效
#   M5 锁文件改落数据根 → 「锁不在数据根」判据失效
_MUTATIONS = (
    ("白名单不滤空目录", "md_cg/sleep.py",
     "            if files:\n                out.append(layer)\n                break",
     "            out.append(layer)\n            break"),
    ("add 退回整树形态（不带 pathspec）", "md_cg/sleep.py",
     '    _git_ok(git_dir_path, work_tree, "add", "--", *ps)',
     '    _git_ok(git_dir_path, work_tree, "add", "-A")'),
    ("materialize 不校验根级锁", "md_cg/sleep.py",
     '        if not lk.acquired:\n            return _busy("materialize", timeout)',
     '        if False:\n            return _busy("materialize", timeout)'),
    ("影子改落 state_root 根", "md_cg/sleep.py",
     "    return os.path.abspath(v) if v else os.path.join(sleep_root(), SHADOW_DIRNAME)",
     "    return os.path.abspath(v) if v else os.path.join(state_root(), SHADOW_DIRNAME)"),
    ("锁文件改落数据根", "md_cg/sleep.py",
     "    return os.path.join(sleep_root(), LOCK_NAME)",
     "    return os.path.join(mdcg_root(), LOCK_NAME)"),
)


def _exec_module(name: str, rel: str, text: str):
    ns = {"__name__": name, "__package__": "md_cg",
          "__file__": os.path.join(_REPO, rel)}
    exec(compile(text, rel, "exec"), ns)               # noqa: S102 —— 基线自证用
    m = types.ModuleType(name)
    m.__dict__.update(ns)
    return m


def _mutate_mode(list_only: bool = False) -> int:
    print("!! 定点变异自证：逐条把机制改回「改动前/错误」形态，套件必须转红\n")
    if list_only:
        for name, rel, _o, _n in _MUTATIONS:
            print("  %-34s [%s]" % (name, rel))
        return 0
    anchor_miss, bad = [], []
    with contextlib.redirect_stdout(io.StringIO()):
        clean = _run_groups()
    print("  未变异基线：失败=%d（必须为 0）" % clean)
    if clean:
        bad.append("未变异基线即失败")

    for name, rel, old, new in _MUTATIONS:
        src = _rel_text(rel)
        if old not in src:
            print("  ANCHOR-MISS %s —— 锚点在 %s 源码里找不到（实现改了却没同步"
                  "本表）" % (name, rel))
            anchor_miss.append(name)
            continue
        mut_src = src.replace(old, new, 1)
        _SRC[rel] = mut_src
        mfile = os.path.join(_TMP, "sleep_mut_%d.py" % len(_MUT_CTX))
        with open(mfile, "w", encoding="utf-8", newline="\n") as f:
            f.write(mut_src)
        _MUT_CTX["mutsrc"] = mfile
        try:
            mut = _exec_module("md_cg._sleep_mut", rel, mut_src)
            globals()["SL"] = mut
            with contextlib.redirect_stdout(buf := io.StringIO()):
                reds = _run_groups()
            detail = buf.getvalue()
        finally:
            globals()["SL"] = _REAL_SL
            _SRC.pop(rel, None)
            _MUT_CTX.pop("mutsrc", None)
        reds_lines = [l for l in detail.splitlines()
                      if l.strip().startswith("FAIL ")]
        verdict = "红" if reds else "**仍全绿 = 该判据空转**"
        print("  %s %-34s 红项=%d  %s"
              % ("OK    " if reds else "MISS  ", name, reds, verdict))
        for l in reds_lines[:5]:
            print("        " + l.strip()[5:])
        if not reds:
            bad.append(name)

    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s"
          % ("PASS（每处机制都有一条断言把它钉死）" if not bad
             else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def main() -> int:
    _sandbox_env()
    try:
        if "--mutate" in sys.argv:
            return _mutate_mode("--list" in sys.argv)
        n = _run_groups()
        print("\n睡眠 git 机制守卫：%d 通过，%d 失败，%d 跳过"
              % (len(_PASS), n, len(_SKIP)))
        return 0 if not n else 1
    finally:
        _restore_env()
        shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
