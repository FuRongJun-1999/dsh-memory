# -*- coding: utf-8 -*-
"""md_cg · review_cli 裁决落盘跨进程可见性守卫（P1b autoflush 第二落点，DSH 端在役实测）

缺陷（修复前）：`review_cli._cg` 构造 `MdCGSecure(_root(args), principal=p)`
不传 autoflush → 缺省 64。库的索引增量链路是「写入先经 `_stage` 入内存
`_dirty` 与内存索引，攒够 autoflush 条才 flush() 落分片日志 `_index_log/`」；
短命进程的**正常退出**另有 main finally `cg.close()` + 库层 atexit 双兜底
（mdcg.py `_LIVE_CGS`，2026-09-16 取证），但**被 kill / 崩溃退出时两者都不
执行**（兜底刻意只覆盖正常退出这一条路径）——裁决落盘的少量节点停在内存
索引、分片日志从未落，盘面节点文件在而索引链路断。DSH 端在役实测：裁决后
MCP 读面 read null。对照：mcp_server.py:3695-3702 同症状 2026-09-16 已修
（server 级 autoflush=1 兜底），review_cli 这个短命工具落点被遗漏——本修复
补齐，与 server 同款。

守卫（四组，全部临时库 + 哑主密钥，绝不触真实 ~/.mdcg）：
  ① 真实在役入口：subprocess 跑 `python -m md_cg.review_cli accept`（正常
    完成）→ 进程 B（全新 python 子进程 _load_index + read）断言业务节点与
    审计记录节点均可见。
  ② kill 形态可见性：进程 A' 等价直接调库落盘 2 条（无任何显式 flush）后
    `os._exit(0)`（模拟被杀：close/atexit 全部跳过）→ 进程 B 全新子进程
    断言读回可见。
  ③ 落账契约（autoflush=1 的直接可观察效应，**修复前红**）：② 的进程 A'
    被杀退出后，盘面 `_index_log/` 必须已含其全部写入的索引记录——"写入即
    落分片日志"，与 mcp_server 的 server 级 autoflush=1 同一契约。
  ④ 同病工具面：evidence._open_cg / scripts/linkref_backfill /
    scripts/migrate_restricted 同样补 autoflush=1（前两者行为断言
    .autoflush==1，后两者源级断言构造语句带参）。

如实边界：本仓 HEAD 上 ①② 的读面断言在修复前已绿——正常路径由 09-16 的
review_decide 显式 flush（mdcos.py）+ close/atexit 兜底覆盖；kill 形态的
重开读面由批次39（2026-09-25）`_load_index` 指纹失配全扫自愈兜住。修复前
红的只有 ③ 的落账契约与在役旧读面（0.4.x 副本 `_load_index` 盲信快照）——
后者正是 DSH 端观察到 read null 的形态；本守卫把读面断言一并钉住，防上述
两层兜底未来被移除时旧症复发。

运行：python -m md_cg.test_review_cli_visibility
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

from .mdcg import ShardedLog
from .mdcos import MdCGSecure
from .security import Principal

PASS = FAIL = 0
FAILS = []

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DUMMY_KEY = "ab" * 32          # 哑主密钥：子进程绝不触真实 ~/.mdcg/master.key

KILL_CHILD = r'''
import argparse, os, sys
sys.path.insert(0, sys.argv[2])
from md_cg import review_cli
# 等价直接调库落盘：走 review_cli 的生产构造路径 _cg（与 CLI 同一 autoflush），
# 随后裸 add 两条（无任何显式 flush）——覆盖 review_decide 之外的写入形态。
cg = review_cli._cg(argparse.Namespace(root=sys.argv[1]))
sys.stderr.write("staged=0 autoflush=%d\n" % cg.autoflush)
cg.add("vis-node-1", "P1b 可见性守卫节点一：kill 形态落账。", layer="knowledge",
       tags=["vis:p1b"])
cg.add("vis-node-2", "P1b 可见性守卫节点二：kill 形态落账。", layer="knowledge",
       tags=["vis:p1b"])
os._exit(0)                     # 硬退：close / atexit 一律不执行（模拟被杀）
'''

READ_CHILD = r'''
import sys
sys.path.insert(0, sys.argv[2])
from md_cg.mdcos import MdCGSecure
from md_cg.security import Principal
p = Principal(actor="vis-reader", clearance="internal", can_write=True,
              can_admin=True, role="designer", auth_mode="test")
cg = MdCGSecure(sys.argv[1], principal=p)
ids = sys.argv[3].split(",")
print("READ " + " ".join("1" if cg.get(nid) is not None else "0" for nid in ids))
'''


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def _child_env(extra=None):
    """子进程环境：哑密钥 + UTF-8 + PYTHONPATH 指向本仓（纪律 15）。"""
    env = dict(os.environ)
    env["MDCG_MASTER_KEY"] = DUMMY_KEY
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = REPO + os.pathsep + env.get("PYTHONPATH", "")
    env.update(extra or {})
    return env


def _run_cli(root, argv):
    """跑一次 review_cli（包内入口 python -m md_cg.review_cli，真实在役入口）。"""
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "md_cg.review_cli"] + argv,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=_child_env(), cwd=REPO)


def _spawn(code, root, arg3=""):
    """独立子进程跑一段内嵌脚本（进程 A' 杀退形态 / 进程 B 全新读面）。"""
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-c", code, root, REPO, arg3],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=_child_env())


def _propose(root, nid, content):
    """以原始写入者身份入队一条提案（复刻 DSH 端 agent 形态）。"""
    cg = MdCGSecure(root, principal=Principal(
        actor="dsh-memory", clearance="internal", can_write=True,
        can_admin=False, role="recorder", session="sess_writer_orig"))
    try:
        return cg.propose(nid, content, layer="knowledge", tags=["vis:p1b"])
    finally:
        cg.close()


def _log_ids(root):
    """读盘面分片日志的记录 id 集（落账契约的观察点）。"""
    log_dir = os.path.join(root, "_index_log")
    if not os.path.isdir(log_dir):
        return None                     # 目录不存在 = 一条都没落过
    return {rec.get("id") for rec in ShardedLog.read_all(log_dir)
            if rec.get("id")}


def main():
    roots = []
    try:
        # ---------- ① 真实在役入口：review_cli accept → 进程 B 读 ----------
        print("\n【①】subprocess 跑 review_cli accept（正常完成）→ 进程 B 读")
        root_1 = tempfile.mkdtemp(prefix="clivis_1_")
        roots.append(root_1)
        pid = _propose(root_1, "vis-acc-node",
                       "P1b 可见性守卫：accept 落盘后其它进程立即可见。")
        r = _run_cli(root_1, ["accept", pid, "--root", root_1,
                              "--reason", "可见性守卫"])
        check("review_cli accept 退出码 0", r.returncode == 0,
              (r.stdout or r.stderr or "")[:200])
        b = _spawn(READ_CHILD, root_1, "vis-acc-node")   # 全新子进程 _load_index+read
        m = re.search(r"READ (\d)", b.stdout or "")
        check("进程 B 读回业务节点 vis-acc-node 可见",
              bool(m) and m.group(1) == "1",
              (b.stdout or b.stderr or "")[:200])
        pa = MdCGSecure(root_1, principal=Principal(
            actor="vis-reader", clearance="internal", can_write=True,
            can_admin=True, role="designer", auth_mode="test"))
        try:
            recs = pa.review_records(pid)
        finally:
            pa.close()
        check("进程 B 侧审计记录节点可见（review_records 命中 1 条）",
              len(recs) == 1, str(recs))

        # ---------- ②③ kill 形态：调库落盘后 os._exit → 落账契约 + 读 ----------
        print("\n【②③】进程 A' 调库落 2 条即 os._exit（模拟被杀）→ 落账契约 + 进程 B 读")
        root_2 = tempfile.mkdtemp(prefix="clivis_2_")
        roots.append(root_2)
        a = _spawn(KILL_CHILD, root_2)
        check("进程 A' 经生产构造 _cg（autoflush=1 回显）",
              a.returncode == 0 and "autoflush=1" in (a.stderr or ""),
              (a.stderr or "")[:200])
        ids = _log_ids(root_2)
        check("③ 落账契约：A' 被杀退出后 _index_log 已含全部 2 条写入记录"
              "（autoflush=1 写毕即落日志；修复前 autoflush=64 未达阈值=红）",
              ids is not None and {"vis-node-1", "vis-node-2"} <= ids,
              "log_ids=%s" % sorted(ids or []))
        b2 = _spawn(READ_CHILD, root_2, "vis-node-1,vis-node-2")   # 全新子进程读
        m2 = re.search(r"READ (\d) (\d)", b2.stdout or "")
        check("② 进程 B 读回 kill 形态的两条节点均可见",
              bool(m2) and m2.group(1) == "1" and m2.group(2) == "1",
              (b2.stdout or b2.stderr or "")[:200])

        # ---------- ④ 同病工具面：三处同款补 autoflush=1 ----------
        print("\n【④】同病工具面 autoflush=1")
        cg_rv = None
        try:
            from . import review_cli as _rv
            cg_rv = _rv._cg(argparse.Namespace(root=root_1))
            check("review_cli._cg 构造 autoflush==1", cg_rv.autoflush == 1,
                  str(cg_rv.autoflush))
        finally:
            if cg_rv is not None:
                cg_rv.close()
        from . import evidence as _ev
        cg_ev = _ev._open_cg(root_1)
        try:
            check("evidence._open_cg 构造 autoflush==1", cg_ev.autoflush == 1,
                  str(cg_ev.autoflush))
        finally:
            cg_ev.close()
        for rel, anchor in (
                ("scripts/linkref_backfill.py",
                 "cg = MdCGSecure(a.root, principal=p, autoflush=1)"),
                ("scripts/migrate_restricted.py", None)):
            with open(os.path.join(REPO, rel), encoding="utf-8") as f:
                src = f.read()
            if anchor is not None:
                ok = anchor in src
            else:
                # migrate_restricted 构造跨多行：断言构造语句带 autoflush=1
                ok = re.search(r"MdCGSecure\([^)]*?auth_mode=\"test\"\), "
                               r"autoflush=1\)", src, re.S) is not None
            check("%s 构造语句带 autoflush=1（源级断言）" % rel, ok)
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
