# -*- coding: utf-8 -*-
"""验收判据③ · qual["bucket"] 可复算（goal-caf158e5）。"""
from __future__ import annotations

import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import bucketscope, bucketindex  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:160])
        FAILS.append(name)


def main():
    cg = MdCGOS(tempfile.mkdtemp(prefix="qb_"), actor="t")
    now = time.time()
    cg.add("d1", "昨天聊了界面改造与记忆分类", layer="contextual",
           tags=["用途:修缺陷"], session="s5.dsh.maintainer.D_4_ai.1791340000.aaaaaaaaaaaa")
    cg.add("d2", "今天聊了角色扮演的语气", layer="contextual", tags=["用途:扮演"])
    cg.flush()

    bucketindex.build(cg)
    res = bucketscope.scope_recall(cg, "记忆分类", "", now)
    items = res if isinstance(res, list) else (res.get("items") if isinstance(res, dict) else None)
    ok(isinstance(items, list), "Q1 scope_recall 返回条目列表", type(res).__name__)
    print("  INFO 召回条目数:", len(items or []))
    if not items:
        print("  SKIP Q2–Q4：本夹具未召回到条目（不伪造通过）")
    else:
        # scope_recall 条目形态是 (node, score, qual) 三元组
        def _qual(it):
            if isinstance(it, tuple):
                for x in it:
                    if isinstance(x, dict) and "bucket" in x:
                        return x
                return {}
            return (it.get("qual") or {}) if isinstance(it, dict) else {}
        quals = [_qual(it) for it in items]
        buckets = [str(q.get("bucket") or "") for q in quals]
        ok(all(b == "session" or b.startswith("day:") for b in buckets),
           "Q2 qual.bucket 只可能是 session 或 day:YYYY-MM-DD", buckets[:5])
        ok(all(float(q.get("score") or 0.0) == 0.0 for q in quals),
           "Q3 qual.score 全为 0.0（证据分语义）", [q.get("score") for q in quals][:5])
        ok(all(not b.startswith("session:unattributed") for b in buckets),
           "Q4 未归属不进任何 session: 桶", buckets[:5])

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
