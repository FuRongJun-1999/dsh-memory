# -*- coding: utf-8 -*-
"""md_cg · review_cli 归因守卫（P1 裁决面身份归因退化，DSH 端在役实测）

缺陷（修复前）：`review_cli._cg` 构造 `Principal(actor="designer-cli", ...)`
不传 session → `security.Principal.__init__` 每次随机生成 `sess_<uuid12>`；
accept 落盘经 `MdCGSecure._attribution` 的 setdefault，writer 缺省成裁决者
designer-cli——于是 DSH 端实测：5 个裁决节点 5 个互不相同的随机会话 id、
writer 全被 designer-cli 覆盖，原始写入者（dsh-memory，提案记录 actor 有）
不可追溯。

守卫（修复前红）：
  ① review_cli accept --session <s> → 落盘节点 frontmatter.session == <s>
  ② 落盘节点 frontmatter.writer == 提案记录的原始 actor（dsh-memory）
  ③ 裁决者身份不丢失：frontmatter.reviewer == "designer-cli"
  ④ 稳定性：同一 --session 两次裁决 → 两节点 session 一致
  ⑤ 兜底：未传 --session 时环境变量 MDCG_SESSION 生效
  ⑥ 仍无（两者皆缺省）→ stderr 告警一行 + 维持随机会话（现状兼容）

运行：python -m md_cg.test_review_cli_attribution
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

from . import nodefile
from .mdcos import MdCGOS, MdCGSecure
from .security import Principal

PASS = FAIL = 0
FAILS = []

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DUMMY_KEY = "ab" * 32          # 哑主密钥：子进程绝不触真实 ~/.mdcg/master.key


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def _child_env(extra=None, remove=("MDCG_SESSION", "DSH_SESSION_ID",
                                   "MDCG_REDTEAM_REQUIRED")):
    """子进程环境：哑密钥 + UTF-8 + PYTHONPATH 指向本仓（纪律 15）。

    remove 里的会话/红队环境变量先摘除——守卫 ①~④⑥ 必须证明 --session
    是唯一来源，不能被外层环境偷跑。
    """
    env = dict(os.environ)
    for k in remove:
        env.pop(k, None)
    env["MDCG_MASTER_KEY"] = DUMMY_KEY
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = REPO + os.pathsep + env.get("PYTHONPATH", "")
    env.update(extra or {})
    return env


def _run_cli(root, argv, extra=None):
    """跑一次 review_cli 子命令（包内入口 python -m md_cg.review_cli）。"""
    return subprocess.run(
        [sys.executable, "-m", "md_cg.review_cli"] + argv,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=_child_env(extra), cwd=REPO)


def _propose(root, nid, content):
    """以原始写入者身份（dsh-memory，DSH 端 agent 形态）入队一条提案。"""
    cg = MdCGSecure(root, principal=Principal(
        actor="dsh-memory", clearance="internal", can_write=True,
        can_admin=False, role="recorder", session="sess_writer_orig"))
    try:
        return cg.propose(nid, content, layer="knowledge", tags=["attr"])
    finally:
        cg.close()


def _fm(root, nid):
    """直读节点文件 frontmatter（不经密级读闸——守卫只看归因字段）。"""
    probe = MdCGOS(root, actor="probe")
    try:
        e = (probe.index.get("nodes") or {}).get(nid)
        if not e:
            return None
        with open(os.path.join(root, e["path"]), encoding="utf-8") as f:
            fm, _c = nodefile.loads(f.read())
        return fm
    finally:
        probe.close()


def main():
    roots = []
    try:
        print("\n【①~③】accept --session → 落盘归因（session/writer/reviewer）")
        root_a = tempfile.mkdtemp(prefix="cliattrib_a_")
        roots.append(root_a)
        pid = _propose(root_a, "attr-node-1", "P1 归因守卫：原始写入者应可追溯。")
        r = _run_cli(root_a, ["accept", pid, "--session", "sess_decide_01",
                              "--root", root_a, "--reason", "归因守卫"])
        check("review_cli accept --session 退出码 0", r.returncode == 0,
              (r.stdout or r.stderr or "")[:200])
        fm = _fm(root_a, "attr-node-1")
        check("frontmatter.session == 传入 --session",
              bool(fm) and fm.get("session") == "sess_decide_01",
              str(fm and fm.get("session")))
        check("frontmatter.writer == 提案原始 actor（dsh-memory）",
              bool(fm) and fm.get("writer") == "dsh-memory",
              str(fm and fm.get("writer")))
        check("裁决者身份保留于 frontmatter.reviewer == designer-cli",
              bool(fm) and fm.get("reviewer") == "designer-cli",
              str(fm and fm.get("reviewer")))

        print("\n【④】同一 --session 两次裁决 → 落盘归属一致")
        pid2 = _propose(root_a, "attr-node-2",
                        "P1 归因守卫第二提案：同批裁决同会话。")
        r2 = _run_cli(root_a, ["accept", pid2, "--session", "sess_decide_01",
                               "--root", root_a, "--reason", "归因守卫"])
        fm2 = _fm(root_a, "attr-node-2")
        check("第二节点 session 与第一节点一致",
              r2.returncode == 0 and bool(fm) and bool(fm2)
              and fm2.get("session") == fm.get("session") == "sess_decide_01",
              "%r vs %r" % (fm and fm.get("session"), fm2 and fm2.get("session")))

        print("\n【⑤】MDCG_SESSION 环境变量兜底")
        pid3 = _propose(root_a, "attr-node-3",
                        "P1 归因守卫第三提案：环境变量会话。")
        r3 = _run_cli(root_a, ["accept", pid3, "--root", root_a,
                               "--reason", "归因守卫"],
                      extra={"MDCG_SESSION": "sess_env_03"})
        fm3 = _fm(root_a, "attr-node-3")
        check("无 --session 时 MDCG_SESSION 生效",
              r3.returncode == 0 and bool(fm3)
              and fm3.get("session") == "sess_env_03",
              str(fm3 and fm3.get("session")))

        print("\n【⑥】两者皆缺省 → stderr 告警一行 + 维持随机会话")
        pid4 = _propose(root_a, "attr-node-4",
                        "P1 归因守卫第四提案：随机会话告警。")
        r4 = _run_cli(root_a, ["accept", pid4, "--root", root_a,
                               "--reason", "归因守卫"])
        fm4 = _fm(root_a, "attr-node-4")
        check("退出码 0（告警不阻断裁决）", r4.returncode == 0,
              (r4.stdout or r4.stderr or "")[:200])
        warn = [ln for ln in (r4.stderr or "").splitlines() if ln.strip()]
        check("stderr 恰一行随机会话告警",
              len(warn) == 1 and "随机会话" in warn[0], str(warn))
        check("缺省仍落随机会话 id（sess_ 前缀，现状兼容）",
              bool(fm4) and str(fm4.get("session", "")).startswith("sess_"),
              str(fm4 and fm4.get("session")))
        check("无 --session 时原始 writer 归因同样在位",
              bool(fm4) and fm4.get("writer") == "dsh-memory",
              str(fm4 and fm4.get("writer")))
    finally:
        for r_ in roots:
            shutil.rmtree(r_, ignore_errors=True)

    print("\n" + "=" * 64)
    print(f"PASS={PASS}  FAIL={FAIL}")
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
