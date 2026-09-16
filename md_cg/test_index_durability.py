# -*- coding: utf-8 -*-
"""md_cg · 索引持久化守卫（跨进程可见性 · 进程退出兜底）

运行：python -m md_cg.test_index_durability

背景（2026-09-16 取证，首例=审核裁决通路）：
  节点 .md 由 `add()` **立即写盘**，但索引条目先进内存 `_dirty`，靠 `flush()` /
  `close()` 落分片日志。一次性进程（CLI / 脚本）写入 1~2 条、远未达 autoflush(64)
  阈值即退出 → 日志无记录；而**已有 `_index.json` 的根重开时不重扫目录**
  （`_load_index`：快照优先，仅重放日志），于是节点「**在盘上但索引无条目**」，
  其它进程与重载后的长驻进程都检索不到，只能靠某次全量 `rebuild_index()` 偶然救回。
  表象极易被误判为「写入丢失」——故本测试以**索引可见性**（而非 `get()`）为判据。

固化三处修复 + 一处反证（防测试空转）：
  ① 库层进程退出兜底（`mdcg._LIVE_CGS` + atexit）：子进程不显式收尾也能落盘；
  ② `review_decide` 统一收尾：目标节点 **与** 审计记录节点双落盘
     （accept/edit 写前者、`_record_decision` 写后者；reject 路径**只**写后者）；
  ③ `review_cli` 显式 `close()`：真实缺陷现场（一次性 CLI 裁决）端到端；
  ④ 反证组：清空兜底登记 → 复现「索引不可见」，证明 ①② 确在生效。

  `_index.json` 快照是「贴真实库形态」的必要前提：空 root 首开会全扫目录，
  恰好掩盖本缺陷（这也是首版复现实验失败的教训）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CCG = ("# 功能名：{n}\n# 生效条件：{c}\n# 子功能：{s}\n# 执行：{e}\n"
       "# 验证方式：test\n# 不适用条件：{neg}\n\n{body}\n")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def mk(n, cond, body, neg="其它"):
    return CCG.format(n=n, c=cond, s=body[:20], e=body, neg=neg, body=body)


def _child_env():
    """子进程环境：显式 UTF-8 + PYTHONPATH 指向本仓（纪律 15：不经 Windows shell）。"""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = REPO + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _run_child(code):
    """以子进程执行一段脚本（argv 列表，shell=False）。"""
    fd, path = tempfile.mkstemp(suffix=".py", prefix="_idxguard_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(code)
    try:
        return subprocess.run([sys.executable, path], capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              env=_child_env(), cwd=REPO)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _seed(root, nid="seed"):
    """建一个「已有快照」的库形态（缺陷成立的必要前提）。"""
    cg = MdCGOS(root, actor="seed")
    cg.add(nid, mk("种子节点", "问种子", "仅用于建索引快照"),
           verification_basis="test")
    cg.flush()
    cg.rebuild_index()
    cg.close()


def _visible(root, nid):
    """索引可见性判据：**新实例**（模拟其它进程 / 重载后的长驻进程）索引里是否有该条目。

    刻意不用 `get()`：它夹带密级/密钥可读性判据，会把「索引缺失」与「读不到」混为一谈。
    """
    probe = MdCGOS(root, actor="probe")
    try:
        return nid in (probe.index.get("nodes") or {})
    finally:
        probe.close()


CHILD_BODY = (
    "import sys\n"
    "sys.path.insert(0, {repo!r})\n"
    "from md_cg.mdcos import MdCGOS\n"
    "cg = MdCGOS({root!r}, actor='child', autoflush=64)\n"
    "cg.add({nid!r}, {content!r}, verification_basis='test')\n"
)


def main():
    roots = []
    try:
        # ---------------- ① 进程退出兜底（atexit） ----------------
        print("\n【①】库层进程退出兜底：子进程不显式收尾")
        root_a = tempfile.mkdtemp(prefix="idxdur_a_")
        roots.append(root_a)
        _seed(root_a)
        r = _run_child(CHILD_BODY.format(
            repo=REPO, root=root_a, nid="n_atexit",
            content=mk("兜底测试节点", "问兜底", "子进程写一条后直接退出")) +
            "# 故意不 close：验证进程退出兜底（atexit）\n")
        check("子进程正常退出", r.returncode == 0, (r.stderr or "")[:200])
        check("兜底生效：新进程索引可见", _visible(root_a, "n_atexit"))

        # ---------------- ④ 反证组（防测试空转） ----------------
        print("\n【④】反证组：清空兜底登记 → 复现缺陷")
        root_b = tempfile.mkdtemp(prefix="idxdur_b_")
        roots.append(root_b)
        _seed(root_b)
        r = _run_child(CHILD_BODY.format(
            repo=REPO, root=root_b, nid="n_nohook",
            content=mk("反证测试节点", "问反证", "清空兜底登记后退出")) +
            "# 反证：摘掉兜底登记（等价于修复前形态）\n"
            "from md_cg.mdcg import _LIVE_CGS\n"
            "_LIVE_CGS.clear()\n")
        check("反证子进程正常退出", r.returncode == 0, (r.stderr or "")[:200])
        check("反证：索引不可见（缺陷可复现，证明兜底是有效变量）",
              not _visible(root_b, "n_nohook"))

        # ---------------- ③ 显式 close 对照（原有正路不回归） ----------------
        print("\n【③】显式收尾对照：close() 仍是正路")
        root_c = tempfile.mkdtemp(prefix="idxdur_c_")
        roots.append(root_c)
        _seed(root_c)
        r = _run_child(CHILD_BODY.format(
            repo=REPO, root=root_c, nid="n_close",
            content=mk("显式收尾节点", "问收尾", "子进程写一条后 close")) +
            "cg.close()\n")
        check("显式 close 子进程正常退出", r.returncode == 0, (r.stderr or "")[:200])
        check("显式 close：新进程索引可见", _visible(root_c, "n_close"))

        # ---------------- ② review_decide 通路统一收尾 ----------------
        print("\n【②】审核裁决通路：目标节点 + 审计记录节点双落盘")
        root_d = tempfile.mkdtemp(prefix="idxdur_d_")
        roots.append(root_d)
        _seed(root_d, nid="seed_d")
        osd = MdCGOS(root_d, actor="designer")
        pid = osd.propose("n_acc", mk("受审节点", "问受审", "审核落盘的目标节点"),
                          verify={"kind": "test", "assertions": ["断言通过"]})
        out = osd.review_decide(pid, "accept", reason="测试判据")
        check("accept 裁决成功", bool(out.get("ok")), str(out)[:160])
        rec_nid = out.get("record_node_id")
        probe = MdCGOS(root_d, actor="probe")
        try:
            check("accept：目标节点索引可见（新实例）",
                  out.get("node_id") in probe.index["nodes"], str(out.get("node_id")))
            check("accept：审计记录节点索引可见（新实例）",
                  bool(rec_nid) and rec_nid in probe.index["nodes"], str(rec_nid))
            check("accept：review_records 可列出（复核面不空）",
                  any(x["id"] == rec_nid for x in probe.review_records(pid=pid)))
        finally:
            probe.close()

        pid2 = osd.propose("n_rej", mk("被拒节点", "问被拒", "reject 只记裁决不落目标节点"))
        out2 = osd.review_decide(pid2, "reject", reason="不通过")
        check("reject 裁决成功", bool(out2.get("ok")), str(out2)[:160])
        rec2 = out2.get("record_node_id")
        check("reject：审计记录节点索引可见（该路径只写它）",
              bool(rec2) and _visible(root_d, rec2), str(rec2))
        osd.close()

        # ---------------- ③ review_cli 端到端（真实缺陷现场） ----------------
        print("\n【③】review_cli 端到端（一次性 CLI 裁决）")
        root_e = tempfile.mkdtemp(prefix="idxdur_e_")
        roots.append(root_e)
        _seed(root_e, nid="seed_e")
        ose = MdCGOS(root_e, actor="designer")
        pid_e = ose.propose("n_cli", mk("CLI 裁决节点", "问 CLI",
                                        "review_cli 落盘的目标节点"))
        ose.close()
        r = subprocess.run(
            [sys.executable, os.path.join(REPO, "scripts", "review_cli.py"),
             "accept", pid_e, "--root", root_e, "--reason", "端到端守卫测试"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=_child_env(), cwd=REPO)
        check("review_cli 退出码 0", r.returncode == 0,
              (r.stdout or r.stderr or "")[:200])
        check("review_cli：目标节点索引可见（新进程）", _visible(root_e, "n_cli"))
        probe = MdCGOS(root_e, actor="probe")
        try:
            recs = probe.review_records(pid=pid_e)
            check("review_cli：审计记录节点索引可见",
                  bool(recs) and all(x["id"] in probe.index["nodes"] for x in recs),
                  str([x["id"] for x in recs]))
        finally:
            probe.close()
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

