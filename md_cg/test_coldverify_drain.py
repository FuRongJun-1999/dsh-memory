# -*- coding: utf-8 -*-
r"""守卫 · #72 coldverify 的受控消费与预演（2026-10-09 DSH 端实施）。

zcode 端 2026-10-09 批准 #72 稿：显式 drain（不常驻线程）＋ dry-run 预演 ＋
status 增积压龄；**保留 opt-in 语义**（不动「默认不启线程」）。

判据（真跑真库）：
  G1 受控消费：入队 N 条 → drain(limit=N) ⇒ 队列减少 N、processed 增加 N
  G2 预演不消费：drain(dry_run=True) 前后 _coldverify.jsonl **逐字节不变**、processed 不增
  G3 预演非空转：dry_run 返回的 would_process **非空且与队首 N 条一致**
  G4 opt-in 未破（回归）：未调 start_worker() ⇒ status()['worker_alive'] is False
  G5 积压龄可读：status()['oldest_age_s'] 与队首条目的 enqueued_at 一致（±2s 容差）
运行：python -X utf8 -m md_cg.test_coldverify_drain
退出码：0 全绿 ｜ 1 断言失败
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


def _cg(root):
    """真 cg 实例：drain 的 _process 需要它做 reverify（传 None 会走 errors 分支）。"""
    from md_cg import tokens as TK
    from md_cg.mdcos import MdCGSecure
    prof = os.environ.get("MDCG_DSH_PROFILE") or ""
    tok = None
    if prof:
        try:
            m = re.search("MDCG_TOKEN:[ ]*'([^']+)'",
                          open(prof, encoding="utf-8", errors="replace").read())
            tok = m.group(1) if m else None
        except OSError:
            tok = None
    return MdCGSecure(root, principal=TK.verify_token(tok) if tok else None)


def main():
    from md_cg import coldverify
    root = tempfile.mkdtemp(prefix="p72_")
    q = coldverify.ColdVerifyQueue(root=root)
    cg = _cg(root)

    # G4：opt-in 未被破坏（未启线程）
    st0 = q.status()
    check("G4 未调 start_worker() ⇒ worker_alive is False（opt-in 未被破坏）",
          st0.get("worker_alive") is False, "worker_alive=%r" % (st0.get("worker_alive"),))

    # 入队 3 条
    for i in range(3):
        q.enqueue("n%d" % i, "reverify")
    qf = q._queue_path
    raw_before = open(qf, "rb").read() if os.path.exists(qf) else b""
    proc_before = q.status()["stats"]["processed"]

    # G2/G3：dry-run
    dv = q.drain(cg, limit=3, dry_run=True)
    raw_after = open(qf, "rb").read() if os.path.exists(qf) else b""
    proc_after = q.status()["stats"]["processed"]
    if isinstance(dv, dict):
        check("G2 预演不消费：队列文件逐字节不变且 processed 不增",
              (raw_before == raw_after) and (proc_before == proc_after),
              "file_same=%r proc %r->%r" % (raw_before == raw_after, proc_before, proc_after))
    # 类型防御：若 dry_run 失效，drain 返回的是**正常消费的 list**（而非预演 dict）
    # —— 此时必须由 G2/G3 **干净点名**，而不是让守卫自己 AttributeError 崩掉。
    # （本条由变异①发现：首版守卫在变异下抛 AttributeError，虽 rc=1 但不是"点名"。）
    if not isinstance(dv, dict):
        check("G2 预演不消费：返回体须为预演 dict（非 list）", False,
              "实得 %s ⇒ dry_run 失效" % type(dv).__name__)
        check("G3 预演非空转：would_process 与队首 3 条一致", False, "预演体缺失")
    else:
        wp = dv.get("would_process") or []
        check("G3 预演非空转：would_process 与队首 3 条一致",
              len(wp) == 3 and [x.get("node_id") for x in wp] == ["n0", "n1", "n2"],
              "n=%d ids=%r" % (len(wp), [x.get("node_id") for x in wp]))

    # G5：积压龄
    st = q.status()
    age = st.get("oldest_age_s")
    first_ts = q._queue[0].get("enqueued_at") if q._queue else None
    exp = round(time.time() - float(first_ts or 0), 1) if first_ts else None
    check("G5 status 含 oldest_age_s 且与队首条目一致（±2s）",
          age is not None and exp is not None and abs(age - exp) <= 2.0,
          "age=%r exp=%r" % (age, exp))

    # G1：真消费
    res = q.drain(cg, limit=3)
    st2 = q.status()
    check("G1 受控消费：drain(limit=3) 后队列清空、processed 增 3",
          st2["queue_size"] == 0 and st2["stats"]["processed"] == proc_after + 3,
          "size=%r processed=%r" % (st2["queue_size"], st2["stats"]["processed"]))

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
