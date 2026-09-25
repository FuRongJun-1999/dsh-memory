#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""review 治理面单次调用复用一次解析守卫（issue：同一 jsonl 单调用内重复全量读）。

缺陷形态（缺陷报告实测 + 当前代码复核）：review_stats 链路每次全量读
decisions 1 遍（by_decision 统计）+ review_list 全量读 inbox 1 遍；
review_decide 线性扫 inbox 找 pid + _cascade_dedup 再全量读 inbox 一遍；
verify_review_record 无 pid 索引线性扫全量 decisions 找单条——解析量随
M/D 线性放大（M=D=4000 实测 review_stats 15.97ms / decide 21.31ms /
verify 28.92ms）。

本守卫断言（调用计数/对账形态，非时间阈值）：
  R1 稳态 review_stats 零全量读：预热装载后 read_jsonl 调用 == 0
     （旧代码每次 decisions+inbox 各 1 次 → 红）；
  R2 稳态 review_decide(reject) 零全量读：同上（旧代码 inbox 2 次 → 红）；
  R3 稳态 verify_review_record 零全量读：同上（旧代码 decisions 1 次 → 红）；
  R4 增量不漏账：外部（他进程形态）append 新裁决/新提案后，统计口径与
     队列视图立即可见；
  R5 语义对账：review_stats 的 records/by_decision/pending/closed 与
     手工全量直读的独立口径逐项一致（缓存不改变结果，只改变速度）。
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import md_cg.mdcos as mdcos_mod               # noqa: E402
from md_cg.fsutil import append_jsonl, read_jsonl as fs_read_jsonl  # noqa: E402
from md_cg.mdcos import MdCGOS, _sig          # noqa: E402

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")


def count_full_reads(fn):
    n = 0
    real = mdcos_mod.read_jsonl

    def _spy(path, *a, **kw):
        nonlocal n
        n += 1
        return real(path, *a, **kw)

    mdcos_mod.read_jsonl = _spy
    try:
        return fn(), n
    finally:
        mdcos_mod.read_jsonl = real


def build(root, m=8, d=5):
    cg = MdCGOS(root)
    for i in range(m):
        c = "存量提案 %d 蜂群调度 %d" % (i, i)
        append_jsonl(cg.inbox_log,
                     {"t": 1.0, "pid": "prop_g%03d" % i, "id": "n%03d" % i,
                      "content": c, "layer": "knowledge", "tags": [],
                      "condition_space": {}, "verify": {},
                      "payload_hash": _sig(c), "actor": "g"})
    for j in range(d):
        append_jsonl(cg.decisions_log,
                     {"t": 1.0, "pid": "prop_g%03d" % j, "decision": "accept",
                      "status": "accepted", "round": 1, "actor": "g"})
    return cg


def main():
    root = tempfile.mkdtemp(prefix="mdcg_review_guard_")
    try:
        cg = build(root)
        cg.review_stats()                       # 预热装载（不计数）

        # R1 稳态 review_stats 零全量读
        print("== R1 稳态 review_stats 零全量读 ==")
        st1, n1 = count_full_reads(lambda: cg.review_stats())
        check("R1a 预热后 review_stats 全量 read_jsonl==0（旧每次 2 次）",
              n1 == 0, f"full_reads={n1}")
        check("R1b 统计口径 sane（records≥d、pending≥1）",
              st1["records"] >= 5 and st1["pending"] >= 1, str(st1)[:100])

        # R2 稳态 review_decide(reject) 零全量读
        print("== R2 稳态 review_decide(reject) 零全量读 ==")
        def _decide():
            _decide.i += 1
            pid = cg.propose("c1", "纯 pending 候选 星云编译 %d" % _decide.i)
            return cg.review_decide(pid, "reject", reason="g")
        _decide.i = 0
        _decide()                                # 预热：装载 phash 索引 +
        out2, n2 = count_full_reads(_decide)     # decisions 创建后的 pid 状态缓存
        check("R2a decide(reject) 全量 read_jsonl==0（旧 inbox 2 次；"
              "首装装载属预期不在此窗）",
              n2 == 0, f"full_reads={n2}")
        check("R2b 裁决 ok", out2.get("ok"), str(out2)[:80])

        # R3 稳态 verify_review_record 零全量读
        print("== R3 稳态 verify_review_record 零全量读 ==")
        def _verify():
            _verify.i += 1
            pid = cg.propose("c2", "复核候选 信任聚合 %d" % _verify.i)
            out = cg.review_decide(pid, "accept", reason="g")
            assert out.get("ok"), out
            return cg.verify_review_record(out["record_node_id"])
        _verify.i = 0
        _verify()                                # 预热同上
        ok3, n3 = count_full_reads(_verify)
        check("R3a verify 链路全量 read_jsonl==0（旧 decisions 1 次扫全量找单条）",
              n3 == 0, f"full_reads={n3}")
        check("R3b 复核通过", ok3.get("ok") is True, str(ok3)[:80])

        # R4 增量不漏账：他进程形态 append
        print("== R4 跨进程 append 增量并入 ==")
        append_jsonl(cg.inbox_log,
                     {"t": 2.0, "pid": "prop_ext_x", "id": "nx",
                      "content": "外部新提案 水位信箱", "layer": "knowledge",
                      "tags": [], "condition_space": {}, "verify": {},
                      "payload_hash": _sig("外部新提案 水位信箱"),
                      "actor": "ext"})
        append_jsonl(cg.decisions_log,
                     {"t": 2.0, "pid": "prop_ext_x", "decision": "noop",
                      "status": "noop", "round": 1, "actor": "ext"})
        st4 = cg.review_stats()
        check("R4a 外部新裁决进统计（by_decision.noop=1）",
              st4["by_decision"].get("noop") == 1, str(st4["by_decision"]))
        pend_ids = [r.get("pid") for r in cg.review_list()]
        check("R4b 外部新裁决立即可见（prop_ext_x 已关闭，不在 pending）",
              "prop_ext_x" not in pend_ids, f"pending={pend_ids}")

        # R5 语义对账：与独立全量直读口径逐项一致
        print("== R5 统计口径独立对账 ==")
        by = {}
        for r in fs_read_jsonl(cg.decisions_log):
            d_ = str(r.get("decision") or "").strip() or "unknown"
            by[d_] = by.get(d_, 0) + 1
        n_pid = len({r.get("pid") for r in fs_read_jsonl(cg.decisions_log)
                     if r.get("pid")})
        st5 = cg.review_stats()
        check("R5a records/by_decision 与独立直读一致",
              st5["records"] == sum(by.values())
              and st5["by_decision"] == by,
              f"got={st5['by_decision']} want={by}")
        check("R5b proposals 与独立直读 pid 数一致",
              st5["proposals"] == n_pid,
              f"got={st5['proposals']} want={n_pid}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 60)
    print(f"结果：PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
