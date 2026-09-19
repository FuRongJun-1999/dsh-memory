# -*- coding: utf-8 -*-
"""md_cg · 审核队列 conformance（数据健康不变量，pi storage conformance 口径）

把存储承诺写成断言，防止未来改动静默破坏：
  ① strict 锁语义：不能丢的写超时必须显式报错，而非静默放行退化为无锁并发
  ② 幂等对账：同内容重试（超时重试/崩溃恢复）→ 幂等返回既有 pid，不重复入队
  ③ 已裁决内容的对账：accepted/rejected 内容重提 → 返回原 pid + 终态
  ④ 存量兼容：无 payload_hash 的旧格式记录参与对账（现算）
  ⑤ 级联出清：主提案终态裁决后，同内容存量兄弟提案自动关闭
  ⑥ close/reopen 状态保持：重开实例后队列视图一致
  ⑦ 并发幂等（真多进程）：N 进程同内容并发 propose → 恰好 1 条、pid 全同
  ⑧ 并发不丢（真多进程）：N 进程×M 条不同内容 → inbox 读回恰好 N×M 条
  ⑨ decisions 并发不丢（真多进程）：并发裁决 → 记录恰好 N 条且指纹完整
  ⑩ 安全层转发：MdCGSecure.propose 的幂等/info 透传
  ⑪ NOOP 裁决：只留痕（jsonl + 审计节点）不落业务节点、不写负记忆、终态关闭、
     统计可见，且与 reject 的留痕状态可区分

运行：python -m md_cg.test_review_conformance
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from .fsutil import FileLock, append_jsonl
from .mdcos import MdCGOS
from .security import Principal
from .mdcos import MdCGSecure

PASS = FAIL = 0
FAILS = []

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WORKER = '''# -*- coding: utf-8 -*-
"""conformance worker：子进程内建 MdCGOS 执行单次 propose / review_decide。"""
import json
import sys

sys.path.insert(0, sys.argv[1])
from md_cg.mdcos import MdCGOS

root, mode = sys.argv[2], sys.argv[3]
arg = sys.argv[4] if len(sys.argv) > 4 else ""
cg = MdCGOS(root, actor="conf-worker")
if mode == "propose":                 # arg = content
    print(json.dumps(cg.propose("w-node", arg, layer="knowledge", tags=["w"])))
elif mode == "propose_n":             # arg = json list of contents
    out = [cg.propose("w-node-%d" % i, c, layer="knowledge")
           for i, c in enumerate(json.loads(arg))]
    print(json.dumps(out))
elif mode == "decide":                # arg = pid
    print(json.dumps(cg.review_decide(arg, "reject", reason="conformance")))
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


def _ensure_worker(workdir):
    wk = os.path.join(workdir, "worker.py")
    if not os.path.exists(wk):
        with open(wk, "w", encoding="utf-8") as f:
            f.write(WORKER)
    return wk


def _run_worker(workdir, root, mode, arg="", timeout=120):
    """子进程跑 worker（argv 列表 + UTF-8 + shell=False，纪律 15）。"""
    wk = _ensure_worker(workdir)
    env = dict(os.environ, PYTHONUTF8="1")
    return subprocess.run(
        [sys.executable, wk, REPO, root, mode, arg],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, env=env, shell=False)


def main():
    workdir = tempfile.mkdtemp(prefix="mdcg_conf_wk_")
    root = tempfile.mkdtemp(prefix="mdcg_conf_")
    root2 = root2b = root3 = root4 = root5 = ""
    _ensure_worker(workdir)
    try:
        cg = MdCGOS(root, actor="test")

        # ---------------- ① strict 锁语义 ----------------
        print("\n【1】strict 锁：不能丢的写超时报错，不放行")
        lock_path = os.path.join(root, "hippocampus", "inbox.jsonl")
        blocker = FileLock(lock_path, timeout=30.0)
        blocker.__enter__()
        t0 = time.time()
        raised = None
        try:
            FileLock(lock_path, timeout=0.3, strict=True).__enter__()
        except TimeoutError as e:
            raised = e
        check("strict 占锁下获锁超时抛 TimeoutError", raised is not None,
              str(raised)[:60])
        check("strict 超时不做长等待", time.time() - t0 < 5.0,
              f"耗时={time.time()-t0:.2f}s")
        soft = FileLock(lock_path, timeout=0.3).__enter__()
        check("非 strict 维持放行语义（best-effort 簿记不受影响）",
              soft.acquired is False, f"acquired={soft.acquired}")
        blocker.__exit__()

        # ---------------- ② 幂等对账：pending ----------------
        print("\n【2】幂等对账：同内容重试返回既有 pid")
        c_body = "# 功能名：conformance 幂等探针\n\n同内容重试不应重复入队。\n"
        p1 = cg.propose("dup1", c_body, layer="knowledge")
        p2 = cg.propose("dup1", c_body, layer="knowledge")       # 模拟重试
        p3 = cg.propose("dup2", c_body, layer="knowledge")       # 换 node_id 同内容
        check("三次 propose 返回同一 pid", p1 == p2 == p3,
              f"{p1} / {p2} / {p3}")
        pend = [r for r in cg.review_list() if r.get("id") in ("dup1", "dup2")]
        check("inbox 恰好 1 条该内容提案", len(pend) == 1, f"pending={len(pend)}")
        info = cg.propose("dup1", c_body, layer="knowledge", info=True)
        check("info=True 透出去重信息",
              info.get("dedup") is True and info.get("dup_of") == p1
              and info.get("dup_status") == "pending", str(info))

        # ---------------- ③ 幂等对账：已裁决内容 ----------------
        print("\n【3】幂等对账：已裁决内容重提返回原 pid + 终态")
        d = cg.review_decide(p1, "accept")
        check("accept 落库", d.get("ok") is True, str(d.get("error") or "")[:60])
        again = cg.propose("dup3", c_body, layer="knowledge", info=True)
        check("accepted 内容重提幂等返回原 pid",
              again.get("dedup") is True and again.get("dup_of") == p1
              and again.get("dup_status") == "accepted", str(again))
        check("重提未产生新队列条目",
              not any(r.get("id") == "dup3" for r in cg.review_list()), "")

        # ---------------- ④ 存量兼容：无 payload_hash 旧记录 ----------------
        print("\n【4】存量兼容：旧格式记录（无 payload_hash）参与对账")
        # 独立内容探针（c_body 在【3】已被 accept，会抢先命中终态分支）
        leg_body = "# 功能名：存量兼容探针\n\n旧账无 hash 也要能对账。\n"
        old = {"t": time.time(), "pid": "prop_legacy0001", "id": "legacy1",
               "content": leg_body, "layer": "knowledge", "tags": [],
               "condition_space": {}, "verify": {}, "verify_hash": "",
               "extra": {}, "actor": "legacy"}
        append_jsonl(cg.inbox_log, old)
        leg = cg.propose("dup4", leg_body, layer="knowledge", info=True)
        check("对账命中存量记录（现算 hash）",
              leg.get("dedup") is True and leg.get("dup_of") == "prop_legacy0001"
              and leg.get("dup_status") == "pending", str(leg))

        # ---------------- ⑤ 级联出清：同 hash 存量兄弟 ----------------
        print("\n【5】级联出清：主提案终态后兄弟自动关闭")
        sib_body = "# 功能名：级联探针\n\n存量重复入队产物。\n"
        main_pid = cg.propose("casc_main", sib_body, layer="knowledge")
        # 手工构造存量兄弟（绕过 propose 的入队查重，模拟修复上线前的旧账）
        for i, nid in enumerate(("casc_sib_a", "casc_sib_b")):
            ph = hashlib.sha1(sib_body.strip().encode("utf-8")).hexdigest()[:12]
            append_jsonl(cg.inbox_log, {
                "t": time.time(), "pid": f"prop_sib{i}000000", "id": nid,
                "content": sib_body, "layer": "knowledge", "tags": [],
                "condition_space": {}, "payload_hash": ph,
                "verify": {}, "verify_hash": "", "extra": {}, "actor": "legacy"})
        sibs_before = [r for r in cg.review_list()
                       if r.get("id") in ("casc_main", "casc_sib_a", "casc_sib_b")]
        check("裁决前 3 条同内容提案全部可见", len(sibs_before) == 3,
              f"n={len(sibs_before)}")
        dmain = cg.review_decide(main_pid, "accept")
        check("accept 成功且级联出清 2 条兄弟",
              dmain.get("ok") and len(dmain.get("cascade_closed") or []) == 2,
              f"cascade={dmain.get('cascade_closed')}")
        left = [r for r in cg.review_list()
                if r.get("id") in ("casc_main", "casc_sib_a", "casc_sib_b")]
        check("裁决后队列无同内容残留", len(left) == 0, f"left={len(left)}")
        decs = [x for x in cg.decisions() if "cascade_dedup" in (x.get("reason") or "")]
        check("级联裁决落 decisions 且带说明", len(decs) == 2
              and all(x.get("status") == "rejected" for x in decs),
              f"n={len(decs)}")

        # ---------------- ⑥ close/reopen 状态保持 ----------------
        print("\n【6】close/reopen：重开实例队列视图一致")
        cg2 = MdCGOS(root, actor="test-reopen")
        rl2 = cg2.review_list()
        check("重开后 review_list 与原实例一致", rl2 == cg.review_list(),
              f"n={len(rl2)}")

        # ---------------- ⑦⑧⑨ 真多进程并发 ----------------
        print("\n【7】并发幂等：4 进程同内容并发 propose")
        root2 = tempfile.mkdtemp(prefix="mdcg_conf_p_")
        content = "# 功能名：并发幂等探针\n\n四进程同时入队只应产生一条。\n"
        procs = [subprocess.Popen(
            [sys.executable, os.path.join(workdir, "worker.py"), REPO,
             root2, "propose", content],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
            env=dict(os.environ, PYTHONUTF8="1")) for _ in range(4)]
        pids = []
        for p in procs:
            out, _err = p.communicate(timeout=120)
            pids.append(json.loads(out.strip()))
        check("4 进程返回同一 pid", len(set(pids)) == 1, str(pids))
        inbox2 = os.path.join(root2, "hippocampus", "inbox.jsonl")
        with open(inbox2, encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
        check("inbox 恰好 1 条（无重复入队）", len(lines) == 1,
              f"lines={len(lines)}")
        rec1 = json.loads(lines[0])
        check("入队记录带 payload_hash", bool(rec1.get("payload_hash")), "")

        print("\n【8】并发不丢：4 进程×5 条不同内容")
        root2b = tempfile.mkdtemp(prefix="mdcg_conf_p2_")
        contents = [json.dumps([
            f"# 功能名：并发不丢 {i}-{j}\n\n第 {i} 进程第 {j} 条。\n"
            for j in range(5)]) for i in range(4)]
        procs = [subprocess.Popen(
            [sys.executable, os.path.join(workdir, "worker.py"), REPO,
             root2b, "propose_n", contents[i]],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
            env=dict(os.environ, PYTHONUTF8="1")) for i in range(4)]
        for p in procs:
            p.communicate(timeout=180)
        with open(os.path.join(root2b, "hippocampus", "inbox.jsonl"),
                  encoding="utf-8") as f:
            all_lines = [ln for ln in f if ln.strip()]
        recs = []
        bad = 0
        for ln in all_lines:
            try:
                recs.append(json.loads(ln))
            except ValueError:
                bad += 1
        check("4×5 并发后读回恰好 20 条（一条不丢）",
              len(recs) == 20 and bad == 0, f"read={len(recs)} bad={bad}")
        check("pid 互不重复", len({r.get("pid") for r in recs}) == 20, "")

        # 【8c】pid 唯一性守卫（2026-09-16 取证修复）：旧式
        # "prop_" + _sig(node_id + time.time()) 无进程熵，同一时刻多 worker
        # 用相同 node_id 入队会碰撞——本项在单进程内高频连续入队，把
        # 「同一时刻多次 propose」这一碰撞条件压缩到必然暴露，防回归。
        root2c = tempfile.mkdtemp(prefix="mdcg_conf_p3_")
        cg2c = MdCGOS(root2c, actor="test")
        pids2c = [cg2c.propose("same-node", f"# 功能名：唯一性 {i}\n\n内容 {i}。\n",
                               layer="knowledge") for i in range(20)]
        check("同 node_id 高频连续 propose：20 pid 互不重复",
              len(set(pids2c)) == 20, f"uniq={len(set(pids2c))}/20")
        check("pid 复现格式（prop_ + 12 hex，调用方依赖）",
              all(isinstance(p, str) and len(p) == 17 and p.startswith("prop_")
                  and all(ch in "0123456789abcdef" for ch in p[5:])
                  for p in pids2c), pids2c[0])


        print("\n【9】decisions 并发：4 进程各裁决 1 个 pid")
        root3 = tempfile.mkdtemp(prefix="mdcg_conf_d_")
        cg3 = MdCGOS(root3, actor="test")
        pids3 = [cg3.propose(f"cc{i}", f"# 功能名：并发裁决 {i}\n\n内容 {i}。\n",
                             layer="knowledge") for i in range(4)]
        procs = [subprocess.Popen(
            [sys.executable, os.path.join(workdir, "worker.py"), REPO,
             root3, "decide", pids3[i]],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
            env=dict(os.environ, PYTHONUTF8="1")) for i in range(4)]
        outs = []
        for p in procs:
            out, _err = p.communicate(timeout=180)
            outs.append(out.strip())
        check("4 项裁决全部成功", all(json.loads(o).get("ok") for o in outs),
              str([o[:40] for o in outs]))
        drecs = cg3.decisions()
        check("decisions 读回恰好 4 条（无交错丢失）", len(drecs) == 4,
              f"n={len(drecs)}")
        check("每条裁决带 record_hash 指纹",
              all(r.get("record_hash") for r in drecs), "")
        check("重开后裁决状态保持",
              len(MdCGOS(root3, actor="x")._closed_pids()) == 4, "")

        # ---------------- ⑩ MdCGSecure.propose info 转发 ----------------
        print("\n【10】安全层转发：MdCGSecure.propose 幂等透传")
        root4 = tempfile.mkdtemp(prefix="mdcg_conf_s_")
        sec = MdCGSecure(root4, principal=Principal(
            actor="conf", clearance="private", can_write=True, can_admin=True))
        sec_body = "# 功能名：安全层幂等\n\n转发链上的去重。\n"
        sp1 = sec.propose("sec1", sec_body, layer="knowledge", info=True)
        sp2 = sec.propose("sec1", sec_body, layer="knowledge", info=True)
        check("安全层两次入队同一 pid 且 dedup 命中",
              sp1.get("pid") == sp2.get("pid") and sp2.get("dedup") is True,
              f"{sp1.get('pid')} / {sp2}")
        with open(os.path.join(root4, "hippocampus", "inbox.jsonl"),
                  encoding="utf-8") as f:
            sec_rec = json.loads(f.readline())
        check("info 不泄漏进 extra",
              "info" not in (sec_rec.get("extra") or {}),
              str(sec_rec.get("extra")))

        # ---------------- ⑪ NOOP 裁决（治理层动作） ----------------
        print("\n【11】NOOP 裁决：只留痕、不落节点、不写负记忆、终态关闭")
        root5 = tempfile.mkdtemp(prefix="mdcg_conf_noop_")
        cg5 = MdCGOS(root5, actor="test-noop")

        def _neg_n():
            """负记忆条目数（rejected 层）——NOOP 不得增加它。"""
            return sum(1 for e in cg5.index["nodes"].values()
                       if (e.get("layer") or "") == "rejected")

        nb = _neg_n()
        np1 = cg5.propose("noop1", "# 功能名：NOOP 探针\n\n已评估，判定无需改动。\n",
                          layer="knowledge")
        dn = cg5.review_decide(np1, "noop", reason="评估过，无需改动")
        check("noop 裁决成功且 decision=noop",
              dn.get("ok") is True and dn.get("decision") == "noop", str(dn)[:80])
        check("noop 不落业务节点", not cg5.get("noop1"), "")
        nrecs = [r for r in cg5.decisions() if r.get("pid") == np1]
        check("noop 进 decisions 留痕（status=noop + record_hash）",
              len(nrecs) == 1 and nrecs[0].get("status") == "noop"
              and bool(nrecs[0].get("record_hash")),
              f"n={len(nrecs)} status={nrecs[0].get('status') if nrecs else '-'}")
        check("noop 不写负记忆（rejected 条目数不增）", _neg_n() == nb,
              f"{nb}→{_neg_n()}")
        check("noop 后提案终态关闭（review_list 不再列出）",
              not any(r.get("pid") == np1 for r in cg5.review_list()), "")
        dn2 = cg5.review_decide(np1, "noop")
        check("重复 noop 幂等拒绝（already_decided）",
              dn2.get("ok") is False and dn2.get("error") == "already_decided",
              str(dn2.get("error")))
        audit = cg5.review_records(pid=np1)
        check("noop 的 md 审计记录节点已落（外部来源可复核）",
              len(audit) == 1, f"n={len(audit)}")
        vrec = cg5.verify_review_record(audit[0]["id"]) if audit else {}
        check("noop 审计记录指纹复核一致且状态为 noop",
              vrec.get("ok") is True and vrec.get("status") == "noop",
              str(vrec)[:90])
        st5 = cg5.review_stats()
        check("review_stats 统计到 noop（by_decision.noop=1）且队列已清",
              st5.get("noop") == 1
              and (st5.get("by_decision") or {}).get("noop") == 1
              and st5.get("pending") == 0 and st5.get("closed") == 1,
              str(st5))
        # 语义分界：noop 与 reject 都终止提案，但留痕状态必须可区分
        # （否则「评估过、无需改动」会被误读为「否掉了这条候选」）
        rj1 = cg5.propose("rej1", "# 功能名：NOOP 对照探针\n\n对照用。\n",
                          layer="knowledge")
        dr = cg5.review_decide(rj1, "reject", reason="对照")
        rjrec = [r for r in cg5.decisions() if r.get("pid") == rj1]
        check("noop 与 reject 留痕状态可区分（noop vs rejected）",
              dr.get("ok") is True and bool(rjrec)
              and rjrec[0].get("status") == "rejected",
              f"reject_status={rjrec[0].get('status') if rjrec else '-'}")

        print(f"\n===== conformance：PASS={PASS} FAIL={FAIL} =====")
        if FAILS:
            print("失败项：", "；".join(FAILS))
        return 1 if FAIL else 0
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        for r in (root, root2, root2b, root3, root4, root5):
            if r:
                shutil.rmtree(r, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
