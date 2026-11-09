# -*- coding: utf-8 -*-
"""P1 元认知口径：d 的含义要说清、恒满格要叫 starved、盲区数不能冒充查询次数。

功能名：test_metacog_honesty —— metacognition 读数诚实性守卫（隔离临时库）。
生效条件：`PYTHONPATH=<root> python -m md_cg.test_metacog_honesty`。
子功能：断言面——
  A1 三条 d_curr=1.0 的反思留痕 → trace.d_state == "starved"（不是 stable/flat 了事）；
  A2 trace 带 d_meaning（0=完美 1=完全空白）与 state_rates_note（资格态≠盲区率）；
  A3 report 的 advice 首条是 no_accept_nodes，且 action 指向补语料/verify；
  A4 盲区建议（blindspot_dense）仍在，但排在 no_accept_nodes 之后；
  B1 blindspots.items 每条带 queried_times 与 blindspot_nodes，且 blindspot 是节点数不是次数；
  B2 counts_note 存在（说明两个数各自的意思）；
  C1 d 值回落到 0.0（满分命中）后 d_state 不再是 starved（闸不是恒真）。
执行：`python -m md_cg.test_metacog_honesty`。
验证方式：test。
不适用条件：活库（一切读写都在 tempfile.mkdtemp 内）。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

from . import metacognition
from .fsutil import append_jsonl
from .mdcos import MdCGOS

PASS = 0
FAIL = 0
FAILS = []


def _ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS", label)
    else:
        FAIL += 1
        FAILS.append(label)
        print("  FAIL", label)


def _seed(cg, ds, states, query="主库 记忆 投影 写入 路径"):
    for d in ds:
        append_jsonl(os.path.join(cg.root, "_reflection.jsonl"),
                     {"t": time.time(), "query": query, "d_curr": float(d),
                      "d_prev": 1.0, "d_delta": 0.0, "d2": 0.0,
                      "states": states, "n_results": 1, "feedback": None})


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_metacog_honesty_")
    try:
        cg = MdCGOS(tmp)
        print("[A1/A2] 恒满格 → starved，且口径写在回包里")
        _seed(cg, [1.0, 1.0, 1.0], {"BLINDSPOT": 5, "DEFER": 1})
        tr = metacognition.trace(cg)
        _ok(tr.get("ok") is True, "trace ok")
        _ok(tr.get("d_state") == "starved", "d_state=starved（%r）" % (tr.get("d_state"),))
        _ok("0=信息差为零" in str(tr.get("d_meaning")), "d_meaning 标明刻度方向")
        _ok("不是查询盲区率" in str(tr.get("state_rates_note")), "state_rates 有口径注")
        _ok(tr.get("emotion") == "stable", "emotion 仍按 d2 算（不改既有语义）")

        print("[A3/A4] advice 先指向语料，而不是先建 unresolved")
        rec = metacognition.report(cg)
        codes = [a.get("code") for a in rec.get("advice") or []]
        _ok(codes[:1] == ["no_accept_nodes"], "首条 no_accept_nodes（%r）" % (codes,))
        first = (rec.get("advice") or [{}])[0]
        _ok("verify" in str(first.get("action")), "action 指向 verify/补语料")
        _ok("blindspot_dense" in codes, "blindspot_dense 仍在")
        _ok(codes.index("no_accept_nodes") < codes.index("blindspot_dense"),
            "no_accept_nodes 排在 blindspot_dense 之前")

        print("[B1/B2] 盲区数标注为节点数")
        bs = metacognition.blindspots(cg)
        items = bs.get("items") or []
        _ok(len(items) >= 1, "有盲区条目")
        it = items[0]
        _ok("queried_times" in it and "blindspot_nodes" in it, "两条计数都在")
        _ok(it.get("blindspot_nodes") == it.get("blindspot"), "blindspot_nodes 同值")
        _ok(it.get("queried_times") == it.get("samples"), "queried_times == 出现次数")
        _ok("不是「该问题盲了几次」" in str(it.get("counts_note")), "每条计数带说明")

        print("[C1] 闸不是恒真")
        tmp2 = tempfile.mkdtemp(prefix="mdcg_metacog_ok_")
        try:
            cg2 = MdCGOS(tmp2)
            _seed(cg2, [0.0, 0.0, 0.0], {"ACCEPT": 3}, query="灵枢 令牌 收窄")
            tr2 = metacognition.trace(cg2)
            _ok(tr2.get("d_state") != "starved", "满分命中时不是 starved（%r）"
                % (tr2.get("d_state"),))
            rec2 = metacognition.report(cg2)
            codes2 = [a.get("code") for a in rec2.get("advice") or []]
            _ok("no_accept_nodes" not in codes2, "不再给 no_accept_nodes（%r）" % (codes2,))
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n=== test_metacog_honesty: PASS %d / FAIL %d ===" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
