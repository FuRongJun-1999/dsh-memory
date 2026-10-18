# -*- coding: utf-8 -*-
r"""守卫 · issue #72（Feature/operations）coldverify 队列无受控消费入口。

缺陷（本件修复 · md_cg/coldverify.py）
--------------------------------------
现状读数（issue 正文）：queue_size=119 / processed=0 / worker_alive=false——
写入侧持续 enqueue，工具面只有 `cg(op=status)` 可看水位，没有任何**经权限、
限量、审计保护**的消费入口。`drain()` 是库内方法：无权限门、无单批硬上限、
无审计，任何拿到 cg 的调用方都能全量消费且不留痕。

修复：新增模块级单点 `controlled_drain(cg, limit=, dry_run=, principal=)`：
  · 权限闸：须 can_admin；未授权返回 forbidden 且**不返回队列内容**；
  · 限量闸：0 <= limit <= CONTROL_LIMIT_MAX（= BATCH_LIMIT），越界 fail-closed；
  · 审计闸：cg._audit 写一行聚合（payload-free），失败不阻断；
  · 失败处置：ok=False 的任务重入队（attempts+1，上限 CONTROL_MAX_ATTEMPTS），
    超过计入 dead_letter——失败可见、可重试、不无限滞留；
  · 不引入常驻线程（start_worker 的 opt-in 语义不变）。

【功能名】coldverify 受控消费入口（#72）
【生效条件】cg 挂有冷路径队列；principal.can_admin 为真；limit 在
  [0, CONTROL_LIMIT_MAX]；dry_run 亦过同一权限闸。
【子功能】限量消费 / 预演 / 失败重入队与 dead-letter / 聚合审计 / opt-in 不破。
【执行】python -X utf8 -m md_cg.test_issue72_coldverify_controlled_drain
        python -X utf8 -m md_cg.test_issue72_coldverify_controlled_drain --mutate
【验证方式】退出码 0 全绿；--mutate 下每个变异体点名预期红项且非空。
【不适用条件】不判后台线程的吞吐/告警（issue 里那两条是运维配置面，非本件
  最小能力）；不覆盖 MCP op 注册接线（需改 mcp_server.py，不在本单元授权面）。
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PASS = 0
FAIL = 0
FAILS = []
SILENT = False
VIOL = []
SANDBOXES = []

_SRC = os.path.join(HERE, "coldverify.py")


def check(name, cond, detail=""):
    global PASS, FAIL
    if SILENT:
        if not cond:
            VIOL.append(name)
        return bool(cond)
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  · " + str(detail)) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s  · %s" % (name, detail))
    return bool(cond)


def _tmp(tag):
    t = tempfile.mkdtemp(prefix="p72c_%s_" % tag)
    SANDBOXES.append(t)
    return t


def _bind(cg, q):
    """把**同一个**队列实例挂到 cg（attach() 会新建实例，内存队列不共享）。"""
    cg._coldverify = q
    return q


def _cg(root, can_admin=True):
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal
    return MdCGSecure(root, principal=Principal(
        role="designer", clearance="private", can_write=True,
        can_admin=can_admin), autoflush=1)


class _BoomCG:
    """消费必失败的最小 cg：get 抛异常 ⇒ drain 走 errors 分支（ok=False）。"""

    def __init__(self, root):
        self.root = root
        self.audit = []

        class _P:
            can_admin = True
        self.principal = _P()

    def _audit(self, op, node_id, **meta):
        self.audit.append({"op": op, "id": node_id, **meta})


def g1_forbidden_hides_queue():
    print("== G1 未授权：不消费、不返回队列内容 ==")
    from md_cg import coldverify
    root = _tmp("forbid")
    q = coldverify.ColdVerifyQueue(root=root)
    cg = _cg(root, can_admin=False)
    coldverify.attach(cg)
    _bind(cg, q)
    q.enqueue("secret-node", "reverify")
    raw0 = io.open(q._queue_path, "rb").read()
    proc0 = q.status()["stats"]["processed"]
    r = coldverify.controlled_drain(cg, limit=5)
    raw1 = io.open(q._queue_path, "rb").read()
    check("G1a 非 admin ⇒ ok=False / forbidden",
          r.get("ok") is False and r.get("error") == "forbidden", r)
    check("G1b 拒绝体不含队列内容（无 would_process/results/queue_size/node_id）",
          not any(k in r for k in ("would_process", "results", "queue_size"))
          and "secret-node" not in json.dumps(r, ensure_ascii=False), sorted(r))
    check("G1c 拒绝时不消费（队列文件逐字节不变、processed 不增）",
          raw0 == raw1 and q.status()["stats"]["processed"] == proc0)
    shutil.rmtree(root, ignore_errors=True)


def g2_dry_run_no_side_effect():
    print("== G2 预演：不改队列、不计数、无正文 ==")
    from md_cg import coldverify
    root = _tmp("dry")
    q = coldverify.ColdVerifyQueue(root=root)
    cg = _cg(root)
    coldverify.attach(cg)
    _bind(cg, q)
    for i in range(3):
        q.enqueue("n%d" % i, "reverify", secret="正文-不得外泄")
    raw0 = io.open(q._queue_path, "rb").read()
    proc0 = q.status()["stats"]["processed"]
    r = coldverify.controlled_drain(cg, limit=2, dry_run=True)
    raw1 = io.open(q._queue_path, "rb").read()
    check("G2a dry_run 成功且 would_process 恰为 2 条",
          r.get("ok") is True and len(r.get("would_process") or []) == 2,
          r.get("would_process"))
    check("G2b dry_run 不改队列文件、不增 processed",
          raw0 == raw1 and q.status()["stats"]["processed"] == proc0)
    check("G2c 预演体不含任务正文（只 node_id/action/age_s）",
          "正文-不得外泄" not in json.dumps(r, ensure_ascii=False))
    shutil.rmtree(root, ignore_errors=True)


def g3_limit_exact_and_idempotent():
    print("== G3 限量精确 + 重复运行不重复迁移 ==")
    from md_cg import coldverify
    root = _tmp("limit")
    q = coldverify.ColdVerifyQueue(root=root)
    cg = _cg(root)
    coldverify.attach(cg)
    _bind(cg, q)
    for i in range(5):
        q.enqueue("n%d" % i, "reverify")
    r1 = coldverify.controlled_drain(cg, limit=2)
    r2 = coldverify.controlled_drain(cg, limit=2)
    ids1 = [x.get("node_id") for x in (r1.get("results") or [])]
    ids2 = [x.get("node_id") for x in (r2.get("results") or [])]
    check("G3a limit=2 ⇒ 每批恰处理 2 条",
          len(ids1) == 2 and len(ids2) == 2, (ids1, ids2))
    check("G3b 两批处理的不是同一批任务（不重复状态迁移）",
          not (set(ids1) & set(ids2)), (ids1, ids2))
    check("G3c 两批后队列剩 1 条",
          q.status()["queue_size"] == 1, q.status()["queue_size"])
    r3 = coldverify.controlled_drain(cg, limit=0)
    check("G3d limit=0 合法且零处理（不静默改语义）",
          r3.get("ok") is True and r3.get("processed") == 0
          and q.status()["queue_size"] == 1, r3.get("processed"))
    shutil.rmtree(root, ignore_errors=True)


def g4_bad_limit_fail_closed():
    print("== G4 limit 越界 fail-closed（不静默截断） ==")
    from md_cg import coldverify
    root = _tmp("badlim")
    q = coldverify.ColdVerifyQueue(root=root)
    cg = _cg(root)
    coldverify.attach(cg)
    _bind(cg, q)
    q.enqueue("n0", "reverify")
    for bad in (coldverify.CONTROL_LIMIT_MAX + 1, -1, "x"):
        r = coldverify.controlled_drain(cg, limit=bad)
        check("G4 limit=%r ⇒ bad_limit 且不消费" % (bad,),
              r.get("ok") is False and r.get("error") == "bad_limit"
              and q.status()["queue_size"] == 1, r)
    shutil.rmtree(root, ignore_errors=True)


def g5_failed_requeued_then_dead_letter():
    print("== G5 失败任务可重试，超限进 dead_letter（不静默蒸发） ==")
    from md_cg import coldverify
    root = _tmp("fail")
    q = coldverify.ColdVerifyQueue(root=root)
    cg = _BoomCG(root)
    q._root = root
    q._queue_path = os.path.join(root, coldverify.QUEUE_FILE)
    _bind(cg, q)
    q.enqueue("boom", "reverify")
    r1 = coldverify.controlled_drain(cg, limit=1)
    check("G5a 失败被点名（errors 非空）",
          len(r1.get("errors") or []) == 1, r1.get("errors"))
    check("G5b 失败任务重新入队（requeued=1，队列仍有 1 条）",
          r1.get("requeued") == 1 and q.status()["queue_size"] == 1,
          {"requeued": r1.get("requeued"), "size": q.status()["queue_size"]})
    r2 = coldverify.controlled_drain(cg, limit=1)
    r3 = coldverify.controlled_drain(cg, limit=1)
    r4 = coldverify.controlled_drain(cg, limit=1)
    check("G5c 重试上限后进 dead_letter（第 4 次 dead_letter=1、队列清空）",
          r4.get("dead_letter") == 1 and q.status()["queue_size"] == 0,
          {"r2": r2.get("requeued"), "r3": r3.get("requeued"),
           "dead": r4.get("dead_letter"), "size": q.status()["queue_size"]})
    shutil.rmtree(root, ignore_errors=True)


def g6_audit_payload_free():
    print("== G6 消费留审计：聚合读数、不含正文 ==")
    from md_cg import coldverify
    root = _tmp("audit")
    q = coldverify.ColdVerifyQueue(root=root)
    cg = _cg(root)
    coldverify.attach(cg)
    _bind(cg, q)
    q.enqueue("n0", "reverify", secret="正文-审计不得外泄")
    r = coldverify.controlled_drain(cg, limit=1)
    ap = os.path.join(root, "_audit.jsonl")
    recs = []
    if os.path.exists(ap):
        for ln in io.open(ap, encoding="utf-8"):
            if ln.strip():
                try:
                    recs.append(json.loads(ln))
                except Exception:                       # noqa: BLE001
                    pass
    hit = [x for x in recs if x.get("op") == "coldverify_drain"]
    check("G6a 审计落一行 coldverify_drain", len(hit) == 1, hit)
    if hit:
        h = hit[0]
        check("G6b 审计含聚合读数（limit/processed/errors/queue_size）",
              h.get("limit") == 1 and "processed" in h and "errors" in h
              and "queue_size" in h, sorted(h))
        check("G6c 审计 payload-free（不含任务正文）",
              "正文-审计不得外泄" not in json.dumps(h, ensure_ascii=False))
    check("G6d 返回体披露审计状态", r.get("audit") is True, r.get("audit"))
    shutil.rmtree(root, ignore_errors=True)


def g7_opt_in_intact():
    print("== G7 回归：受控消费不启后台线程（opt-in 不变） ==")
    from md_cg import coldverify
    root = _tmp("optin")
    q = coldverify.ColdVerifyQueue(root=root)
    cg = _cg(root)
    coldverify.attach(cg)
    _bind(cg, q)
    q.enqueue("n0", "reverify")
    r = coldverify.controlled_drain(cg, limit=1)
    check("G7 消费后 worker_alive 仍为 False",
          r.get("worker_alive") is False and q.status()["worker_alive"] is False,
          r.get("worker_alive"))
    shutil.rmtree(root, ignore_errors=True)


# ============================ 源断言 ============================

def b_source_face():
    print("== B 源断言（关键判据在场 + 反陈化） ==")
    src = io.open(_SRC, encoding="utf-8", errors="replace").read()
    check("B1 权限闸在场", 'getattr(p, "can_admin", False)' in src)
    check("B2 限量闸在场（范围判据 + 硬上限 + fail-closed）",
          "CONTROL_LIMIT_MAX = BATCH_LIMIT" in src
          and "if lim < 0 or lim > CONTROL_LIMIT_MAX:" in src
          and '"bad_limit"' in src)
    check("B3 失败重入队 + dead_letter 在场（调用点，不只是定义）",
          "q._requeue_failed(src, attempts)" in src
          and "attempts > CONTROL_MAX_ATTEMPTS" in src
          and '"dead_letter"' in src)
    check("B4 审计出口在场（payload-free）",
          '"coldverify_drain"' in src and "payload" not in
          src.split('"coldverify_drain"')[1][:600].lower())
    check("B5 反陈化：点名 issue #72", "#72" in src)
    seg = src[src.find("def controlled_drain"):]
    nxt = seg.find("\ndef ")
    if nxt > 0:
        seg = seg[:nxt]
    check("B6 不启后台线程（函数体内无 start_worker 调用）",
          "start_worker(" not in seg)


# ============================ 主流程 ============================

GROUPS = (g1_forbidden_hides_queue, g2_dry_run_no_side_effect,
          g3_limit_exact_and_idempotent, g4_bad_limit_fail_closed,
          g5_failed_requeued_then_dead_letter, g6_audit_payload_free,
          g7_opt_in_intact)


def run_groups():
    global PASS, FAIL
    PASS = 0
    FAIL = 0
    del FAILS[:]
    del VIOL[:]
    for g in GROUPS:
        try:
            g()
        except Exception as exc:                        # noqa: BLE001
            check("断言组 %s 抛异常：%s" % (g.__name__, exc), False)
            import traceback
            print(traceback.format_exc()[-600:])
    b_source_face()
    return len(FAILS)


# ============================ 变异自证 ============================

MUTATIONS = (
    ("M1 删权限闸",
     '    if not getattr(p, "can_admin", False):\n'
     '        return {"ok": False, "error": "forbidden",\n'
     '                "reason": "受控消费需 can_admin（未授权调用不返回队列内容）"}\n',
     "", "G1a", "G1b", "B1"),
    ("M2 删限量闸",
     "    if lim < 0 or lim > CONTROL_LIMIT_MAX:\n"
     '        return {"ok": False, "error": "bad_limit",\n'
     '                "reason": "limit 须在 [0, %d]（单批硬上限）" % CONTROL_LIMIT_MAX,\n'
     '                "limit_max": CONTROL_LIMIT_MAX}\n',
     "", "G4", "B2"),
    ("M3 失败不重入队（静默蒸发）",
     "        q._requeue_failed(src, attempts)\n        requeued += 1\n",
     "", "G5b", "G5c", "B3"),
    ("M4 删审计调用",
     '    if a is not None:\n'
     '        try:\n'
     '            a("coldverify_drain", "", dry_run=False, limit=lim,\n'
     '              processed=st["stats"].get("processed"), errors=len(errs),\n'
     '              requeued=requeued, dead_letter=dead,\n'
     '              queue_size=st["queue_size"], oldest_age_s=st.get("oldest_age_s"))\n'
     "            audit_ok = True\n"
     '        except Exception:                              # noqa: BLE001\n'
     '            audit_ok = False          # 审计失败不阻断消费（best-effort，同 G8）\n',
     "", "G6a", "G6d", "B4"),
)


def mutate():
    pristine = io.open(_SRC, encoding="utf-8", newline="").read()
    global SILENT
    bad = []
    for name, anchor, repl, *want in MUTATIONS:
        orig = pristine
        NL = "\r\n" if "\r\n" in orig else "\n"
        a_ = anchor.replace("\n", NL)
        r_ = repl.replace("\n", NL)
        if a_ not in orig:
            print("  ANCHOR-MISS %s" % name)
            bad.append(name)
            continue
        try:
            io.open(_SRC, "w", encoding="utf-8", newline="").write(
                orig.replace(a_, r_, 1))
            # 变异体必须在**新模块状态**下判：否则第二轮起跑的是首轮缓存
            # （首轮 M1 删权限闸 ⇒ 后续所有变异都看到无权限闸的旧代码）。
            import importlib
            from md_cg import coldverify as _cv
            importlib.reload(_cv)
            SILENT = True
            run_groups()
            reds = list(VIOL)
            hit = [w for w in want if any(x.startswith(w) for x in reds)]
            print("  %-4s %-34s 红项=%-3d 命中=%s"
                  % ("OK" if len(hit) == len(want) else "BAD", name,
                     len(reds), ",".join(hit) if hit else "无"))
            if len(hit) != len(want):
                print("       期望红：%s；实红：%s" % (list(want), reds[:8]))
                bad.append(name)
        finally:
            SILENT = False
            io.open(_SRC, "w", encoding="utf-8", newline="").write(pristine)
            import importlib
            from md_cg import coldverify as _cv
            importlib.reload(_cv)      # 复原后立即回到真实现，避免污染下一轮
            if io.open(_SRC, encoding="utf-8", newline="").read() != pristine:
                print("  RESTORE-FAILED %s" % name)
                bad.append(name + "(恢复失败)")
    if bad:
        print("\n定点变异自证：FAIL -- %s" % "、".join(bad))
        return 1
    print("\n定点变异自证：PASS（每处判据都被打红）")
    return 0


def cleanup():
    for t in SANDBOXES:
        shutil.rmtree(t, ignore_errors=True)


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        rc = mutate()
        cleanup()
        sys.exit(rc)
    # 锚点自检（fail-closed）：修法的关键判据不在源码里 ⇒ exit 2，不给假绿。
    _s = io.open(_SRC, encoding="utf-8", errors="replace").read()
    _miss = [a for a in ("def controlled_drain",
                         'getattr(p, "can_admin", False)',
                         '"coldverify_drain"') if a not in _s]
    if _miss:
        print("锚点自检失败：关键判据字面量缺失 %s" % _miss)
        cleanup()
        sys.exit(2)
    n = run_groups()
    print("\nissue72 coldverify 受控消费守卫：%d 通过，%d 失败" % (PASS, n))
    cleanup()
    sys.exit(1 if n else 0)
