# -*- coding: utf-8 -*-
"""检索候选预筛守卫（2026-10-21，分层检索第二级：全局索引 → 正文）。

P1 词项命中足够多 → 预筛生效（meta.prefilter 在场），且命中节点仍被召回
P2 命中太少 → 回退全量（meta.prefilter 缺席），不漏召回
P3 MDCG_PREFILTER=0 → 不预筛
P4 预筛不改写任何节点内容（只读）
"""
from __future__ import annotations

import os
import tempfile

from .mdcos import MdCGSecure


def _mk(tag_count_hi=True):
    root = tempfile.mkdtemp(prefix="pf_")
    cg = MdCGSecure(root)
    # 60 条带 tag 的节点：足以越过默认阈值 50
    for i in range(60):
        cg.add("t%d" % i, "样本内容 %d" % i, layer="knowledge",
               tags=["预筛探针", "组%d" % (i % 6)])
    if tag_count_hi:
        for i in range(60):
            cg.add("o%d" % i, "其它内容 %d" % i, layer="knowledge", tags=["无关标签"])
    return root, cg


def main():
    os.environ.pop("MDCG_PREFILTER", None)
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

    root, cg = _mk()
    before = (cg.get("t0") or {}).get("content")
    res, meta = cg.search("预筛探针", k=3, record=False)
    ids = [n.get("id") for n, _s, _q in res]
    chk(bool(meta.get("prefilter")), "P1 命中足够多时预筛生效（meta.prefilter=%r）" % (meta.get("prefilter"),))
    chk(any(str(i).startswith("t") for i in ids), "P1b 命中节点仍被召回：%s" % (ids[:3],))
    chk((cg.get("t0") or {}).get("content") == before, "P4 预筛只读（节点内容未变）")

    # P2：查询词在 tags 里只命中少数（< 阈值 50）→ 回退全量
    cg.add("solo", "独有词 阿尔法", layer="knowledge", tags=["独有词"])
    res2, meta2 = cg.search("阿尔法", k=3, record=False)
    chk(not meta2.get("prefilter"), "P2 命中太少回退全量（无 prefilter 键）")
    ids2 = [n.get("id") for n, _s, _q in res2]
    chk("solo" in [str(i) for i in ids2], "P2b 回退后仍能召回：%s" % (ids2[:3],))

    # P3：显式关闭
    os.environ["MDCG_PREFILTER"] = "0"
    try:
        res3, meta3 = cg.search("预筛探针", k=3, record=False)
        chk(not meta3.get("prefilter"), "P3 MDCG_PREFILTER=0 时不预筛")
    finally:
        os.environ.pop("MDCG_PREFILTER", None)

    print("=" * 60)
    print("候选预筛守卫：%d 通过 / %d 失败" % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
