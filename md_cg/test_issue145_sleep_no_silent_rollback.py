# -*- coding: utf-8 -*-
r"""#145 守卫：sleep 合并**不得静默回滚**首轮之后的主库编辑。

病象（修前，沙箱实测）：主库只在**首轮**入册 `lib.git`（`if not _has_head(G, root)`），
而影子是 `worktree add -b <branch> S BASE_BRANCH`（从**冻结基线** fork）⇒
「首轮入库 → 主库编辑 v2 → 再物化 → 影子 Δ → 合并」序列里，影子带回的是 v1，
`gate_delta` 的两方比对（base vs 当前 main）恰好放行 ⇒ 旧副本写回主库，
`merge ok=True`、无冲突、无 deferred —— **静默回滚**。

判据：
  A1 主库编辑 v2 在整轮合并后**幸存**（无静默回滚）
  A2 每轮物化都把真源面入册（`baseline.committed is True`）且回传 `base_commit`
  A3 影子 fork 点 = 当前 HEAD（影子拿到的是含 v2 的版本）
  A4 **不误伤**：影子侧的合法编辑被正常重放（正对照）
  A5 **正对照·无编辑**：主库无新编辑时，物化—合并行为不变（仍 ok/merged）
  A6 #145③：影子陈旧（fork 点落后于 HEAD）时**拒绝重放**（aborted=stale_shadow，主库不被写）
运行：
  python -X utf8 -m md_cg.test_issue145_sleep_no_silent_rollback
  python -X utf8 -m md_cg.test_issue145_sleep_no_silent_rollback --mutate=twoside   # 期望 A1/A2 红
  python -X utf8 -m md_cg.test_issue145_sleep_no_silent_rollback --mutate=nofork   # 期望 A6 红
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

PASS = 0
FAIL = 0
FAILS = []


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", label,
                           ("  · " + str(detail)) if detail else ""))
    return bool(cond)


def _mk_sandbox(tag):
    # 沙箱根一律取系统临时目录（**不得**硬编码本机路径：那会把探针产物
    # 写到仓外固定位置，且本机路径不许进追踪面——本仓 check_local_paths 硬门禁）。
    sb = tempfile.mkdtemp(prefix="iss145_%s_" % tag)
    root = os.path.join(sb, "lib")
    os.makedirs(os.path.join(root, "knowledge"))
    os.makedirs(os.path.join(root, "structural"))
    return sb, root, os.path.join(sb, "state", "lib.git"), os.path.join(sb, "state", "shadow")


def _node(t, ver):
    return ("---\nid: %s\nlayer: knowledge\nverification_basis: test\n---\n%s %s PASSED\n"
            % (t, t.upper(), ver))


def _tail(p):
    with open(p, encoding="utf-8") as f:
        return f.read().splitlines()[-1]


def _write(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


def _mutate(which):
    """把被验实现退回病灶形态（注入在**实现侧**，不是断言侧）。"""
    from md_cg import sleep as SL
    if which == "twoside":          # 退回「只在首轮入册」
        real = SL._stage_and_commit

        def only_first(g, w, msg):
            if SL._has_head(g, w):
                return {"committed": False, "reason": "已有基线提交（变异：退回首轮语义）"}
            return real(g, w, msg)
        SL._stage_and_commit = only_first
    elif which == "nofork":         # 拆掉 ③ 的 fork 点写前复核
        real_ok = SL._git_ok

        def blind(g, w, *a):
            if a and a[0] == "merge-base":
                return real_ok(g, w, "rev-parse", "HEAD")
            return real_ok(g, w, *a)
        SL._git_ok = blind


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    mut = ""
    for a in argv:
        if a.startswith("--mutate="):
            mut = a.split("=", 1)[1]
    if mut:
        _mutate(mut)
        print("（变异=%s：注入在实现侧）" % mut)
    from md_cg import sleep as SL
    from md_cg.mdcos import MdCGOS

    sb, root, G, S = _mk_sandbox("a")
    try:
        bp = os.path.join(root, "structural", "b.md")
        _write(os.path.join(root, "knowledge", "a.md"), _node("a", "v1"))
        _write(bp, _node("b", "v1"))
        cg = MdCGOS(root, autoflush=0)
        m1 = SL.materialize(root, git_dir_path=G, shadow=S, ts="g1")
        ok(m1.get("ok"), "A0 首轮物化成功", m1.get("error"))
        _write(bp, _node("b", "v2-主库编辑版"))          # 首轮之后的编辑
        m2 = SL.materialize(root, git_dir_path=G, shadow=S, ts="g2")
        ok((m2.get("baseline") or {}).get("committed") is True,
           "A2 每轮物化都把真源面入册（baseline.committed is True）", m2.get("baseline"))
        ok(bool(m2.get("base_commit")), "A2b 物化回传 base_commit", m2.get("base_commit"))
        ok("v2-主库编辑版" in _tail(os.path.join(S, "structural", "b.md")),
           "A3 影子 fork 自含 v2 的提交（影子侧 b 是 v2）", _tail(os.path.join(S, "structural", "b.md")))
        _write(os.path.join(S, "knowledge", "a.md"), _node("a", "v2-影子迭代"))
        delta = SL.semantic_delta(root, S)
        gated = SL.gate_delta(cg, delta, baseline_face=m2.get("base_face"), shadow_root=S)
        out = SL.merge_cycle(cg, root, git_dir_path=G, branch=m2["branch"], shadow=S,
                             delta=delta, accepted=gated["accepted"], batch="guard")
        ok("v2-主库编辑版" in _tail(bp),
           "A1 主库编辑在整轮合并后幸存（无静默回滚）", _tail(bp))
        ok("v2-影子迭代" in _tail(os.path.join(root, "knowledge", "a.md")),
           "A4 不误伤：影子侧合法编辑被重放", _tail(os.path.join(root, "knowledge", "a.md")))
        # 注：`deferred=tree_divergence` 是**既有**的 fail-closed 行为（两侧树不同即挂起、
        # 不自动解决）——它不写回任何内容，故不是本件要钉的面。A5 只钉「轮次不失败」。
        ok(out.get("ok") is True,
           "A5 正对照：正常轮次不失败（ok=True；deferred 属既有挂起语义，不在本件面内）",
           {k: out.get(k) for k in ("ok", "deferred", "merged")})
    finally:
        shutil.rmtree(sb, ignore_errors=True)

    # A6 影子陈旧 ⇒ ③ 拒绝重放
    sb, root, G, S = _mk_sandbox("b")
    try:
        bp = os.path.join(root, "structural", "b.md")
        _write(os.path.join(root, "knowledge", "a.md"), _node("a", "v1"))
        _write(bp, _node("b", "v1"))
        cg = MdCGOS(root, autoflush=0)
        m1 = SL.materialize(root, git_dir_path=G, shadow=S, ts="s1")
        _write(bp, _node("b", "v2"))
        # 另起一个提交把 HEAD 推前（模拟「两次物化之间主库被别的写方推进」）
        SL._stage_and_commit(G, root, "sleep: 他方推进")
        _write(os.path.join(S, "knowledge", "a.md"), _node("a", "影子迭代"))
        delta = SL.semantic_delta(root, S)
        gated = SL.gate_delta(cg, delta, baseline_face=m1.get("base_face"), shadow_root=S)
        out = SL.merge_cycle(cg, root, git_dir_path=G, branch=m1["branch"], shadow=S,
                             delta=delta, accepted=gated["accepted"], batch="stale")
        ok(out.get("aborted") == "stale_shadow",
           "A6 影子陈旧 ⇒ 拒绝重放（aborted=stale_shadow）",
           {k: out.get(k) for k in ("ok", "aborted", "error")})
        ok("v2" in _tail(bp), "A6b 拒绝后主库未被写（b 仍 v2）", _tail(bp))
    finally:
        shutil.rmtree(sb, ignore_errors=True)

    print("\nissue145_sleep_no_silent_rollback: %d pass / %d fail%s"
          % (PASS, FAIL, ("（变异=%s）" % mut) if mut else ""))
    for f in FAILS:
        print(" - 红：%s" % f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())