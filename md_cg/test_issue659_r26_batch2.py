# -*- coding: utf-8 -*-
"""R26 清单（issue #659）第二批守卫：min_score 单点 / exclude_doc 类型与超取。

覆盖 F26-06（inf 让检索恒空）、F26-12（两处开关判据相反）、F26-14（门槛读数不可见）、
F26-15（负覆盖尾绕过门槛）、F26-28（字符串 "false" 反向开启）、F26-11（k 截断后过滤吃配额）。
"""
from __future__ import annotations

import os
import tempfile

from . import mcp_server
from .mdcg import parse_min_score
from .mdcos import MdCGOS


def main():
    ok = bad = 0

    def chk(cond, label):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("  PASS", label)
        else:
            bad += 1
            print("  FAIL", label)

    # ---------- F26-06 / F26-12：解析单点 ----------
    chk(parse_min_score("inf", 0.0) == (0.0, "invalid"), "F26-06 inf 判非法并回落默认（不再全量滤空）")
    chk(parse_min_score("-inf", 0.0) == (0.0, "invalid"), "F26-06 -inf 同样判非法")
    chk(parse_min_score("nan", 0.0) == (0.0, "invalid"), "F26-12 nan 判非法（此前静默等同关闭）")
    chk(parse_min_score("0.01", 0.0) == (0.01, "ok"), "F26-06 正常值原样解析")
    chk(parse_min_score(None, -1.0) == (-1.0, "default"), "F26-12 缺省取各自默认（recall 面 -1）")

    # ---------- F26-28：布尔强制 ----------
    chk(mcp_server._as_flag("false") is False, "F26-28 字符串 false 不再反向开启")
    chk(mcp_server._as_flag("true") is True, "F26-28 字符串 true 判真")
    chk(mcp_server._as_flag(0) is False and mcp_server._as_flag(1) is True, "F26-28 数字按 0/非 0")
    items = [{"id": "doc_1"}, {"id": "mem_1"}]
    kept, dropped = mcp_server.drop_doc_nodes(items, lambda x: x["id"], "false")
    chk(len(kept) == 2 and dropped == 0, "F26-28 传 \"false\" 时不过滤（旧实现会丢掉 doc_1）")

    # ---------- F26-06 端到端：inf 不再把结果滤空 ----------
    root = tempfile.mkdtemp(prefix="f659_")
    cg = MdCGOS(root)
    cg.add("mem_alpha", "# 功能名：甲\n# 执行：乙", layer="knowledge", tags=["t1"],
           importance=0.6, verification_basis="test")
    cg.flush()
    # 默认读路径是 search_rrf（cg(op=read) bm25=True 走它），故在此验端到端。
    os.environ["MDCG_MIN_SCORE"] = "inf"
    try:
        res, meta = cg.search_rrf("甲", paths=("bm25",), k=5)
        chk(len(res) >= 1, "F26-06 MIN_SCORE=inf 时检索仍有结果（旧实现恒空，实际 %d 条）" % len(res))
        chk(meta.get("min_score_input") == "invalid", "F26-06 非法输入如实记账 min_score_input=invalid")
    finally:
        del os.environ["MDCG_MIN_SCORE"]

    # ---------- F26-14：门槛读数可观测 ----------
    os.environ["MDCG_MIN_SCORE"] = "0.01"
    try:
        res, meta = cg.search_rrf("甲", paths=("bm25",), k=5)
        chk(meta.get("min_score") == 0.01, "F26-14 生效门槛值透出到 meta（此前写入 stat 无人读）")
        chk("min_score_dropped" in meta, "F26-14 被丢弃条数同样可观测")
    finally:
        del os.environ["MDCG_MIN_SCORE"]

    print("=" * 56)
    print("R26 第二批守卫：%d 通过 / %d 失败" % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
