# -*- coding: utf-8 -*-
"""异步检索守卫（2026-10-21）：怕 MCP 超时的客户端先拿工单，过几秒再来取。

A1 defer_s>0 提交立即返回工单（<0.5s，status=pending）
A2 轮询最终 done，且带 result
A3 异步结果与同步检索的 id 集合一致（同一语义，不是另一次检索）
A4 未知 job_id → status=unknown（不静默当空结果）
A5 不带 defer_s → 仍然同步返回（默认面不变）
A6 工单表有上限（提交 70 个，保留 ≤64）——常驻进程不得无界涨
"""
from __future__ import annotations

import tempfile
import time

from .mdcos import MdCGSecure
from . import mcp_server as S


def main():
    ok = 0
    bad = 0

    def chk(cond, label):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("  PASS", label)
        else:
            bad += 1
            print("  FAIL", label)

    root = tempfile.mkdtemp(prefix="as_")
    cg = MdCGSecure(root, autoflush=1)
    for i in range(12):
        cg.add("a%d" % i, "异步检索样本 %d 内容" % i, layer="knowledge", tags=["异步探针"])

    # A5 默认同步不变
    sync = S.call_tool(cg, "mdcg_search", {"query": "异步探针", "k": 5})
    chk(isinstance(sync, dict) and isinstance(sync.get("results"), list), "A5 不带 defer_s 仍同步返回")

    # A1 提交立即返回
    t0 = time.time()
    ticket = S.call_tool(cg, "mdcg_search", {"query": "异步探针", "k": 5, "defer_s": 10})
    dt = time.time() - t0
    chk(dt < 0.5, "A1 提交立即返回（%.3fs）" % dt)
    chk(ticket.get("status") == "pending" and ticket.get("job_id"), "A1b 返回工单（%r）" % (ticket.get("job_id"),))

    # A2 轮询到 done
    jid = ticket["job_id"]
    deadline = time.time() + 20
    done = None
    while time.time() < deadline:
        cur = S.call_tool(cg, "mdcg_search", {"job_id": jid})
        if cur.get("status") in ("done", "error"):
            done = cur
            break
        time.sleep(0.2)
    chk(done is not None and done.get("status") == "done", "A2 轮询最终 done（status=%r）" % (done and done.get("status")))
    async_res = (done or {}).get("result") or {}
    chk(isinstance(async_res.get("results"), list) and async_res["results"], "A2b done 带 result")

    # A3 与同步结果一致
    s_ids = [r.get("id") for r in (sync.get("results") or [])]
    a_ids = [r.get("id") for r in (async_res.get("results") or [])]
    chk(s_ids == a_ids, "A3 异步与同步 id 集合一致（%d 条）" % len(a_ids))

    # A4 未知 job
    unk = S.call_tool(cg, "mdcg_search", {"job_id": "sjob_nope_0000"})
    chk(unk.get("status") == "unknown", "A4 未知 job_id 显式 unknown")

    # A6 上限
    for i in range(70):
        S.call_tool(cg, "mdcg_search", {"query": "异步探针", "k": 1, "defer_s": 30})
    chk(len(S._SEARCH_JOBS) <= S._SEARCH_JOB_MAX,
        "A6 工单表有上限（%d <= %d）" % (len(S._SEARCH_JOBS), S._SEARCH_JOB_MAX))

    print("=" * 60)
    print("异步检索守卫：%d 通过 / %d 失败" % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
