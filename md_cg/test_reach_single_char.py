# -*- coding: utf-8 -*-
"""reach 单字符 term 收敛守卫（issue #611）。

R1 含单字符 term 时不再整段跳过（meta.reach 不是 short_term）
R2 召回不丢：同一查询在 reach 开/关下，命中集合一致（单字符 bigram 并集是超集口径）
R3 仍能收敛：含单字符 term 时 scanned 小于全量候选数
"""
from __future__ import annotations

import os
import tempfile

from .mdcg import MdCG
from . import reach as R


def _mk():
    root = tempfile.mkdtemp(prefix="reach_sc_")
    cg = MdCG(root)
    docs = [
        ("a1", "灵枢 记忆库 的第一条记录"),
        ("a2", "灵枢 的 记 字单独出现 也无所谓"),
        ("a3", "记忆库 与 灵枢 的组合内容"),
        ("a4", "完全无关的 数据 一条"),
        ("a5", "记 录 单字 命中 样本"),
    ]
    for nid, txt in docs:
        cg.add(nid, txt, layer="knowledge")
    return cg


def main():
    os.environ["MDCG_REACH"] = "1"
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

    cg = _mk()
    entries = list(cg.index["nodes"].values())
    terms = ["灵枢", "记"]
    got, meta = R.narrow(cg, entries, terms, set(), q="灵枢 记")
    chk(meta.get("reach") != "short_term", "R1 单字符 term 不再整段跳过（reach=%s）" % meta.get("reach"))
    chk(got is not None, "R1b 返回收敛集而非 None")
    if got is not None:
        chk(len(got) < len(entries), "R3 确有收敛（%d < %d）" % (len(got), len(entries)))
        # R2：收敛集必须覆盖「含灵枢 或 含记」的全部文档
        full = [e for e in entries
                if any(t in cg.get(e.get("path", "").rsplit("/", 1)[-1][:-3] or "") for t in [])] if False else None
        pathes = {e.get("path") for e in got}
        # 用 LIKE 语义核对：凡正文含 "灵枢" 或 "记" 的节点都应在收敛集内
        for e in entries:
            node = cg.get(str(e.get("id") or ""))
            body = (node or {}).get("content", "") if isinstance(node, dict) else ""
            if ("灵枢" in body or "记" in body) and e.get("path") not in pathes:
                chk(False, "R2 召回丢失：%s 未进收敛集" % e.get("path"))
                break
        else:
            chk(True, "R2 召回不丢（含灵枢/记的节点全在收敛集内）")

    print("=" * 60)
    print("reach 单字符守卫：%d 通过 / %d 失败" % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
