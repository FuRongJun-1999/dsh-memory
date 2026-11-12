# -*- coding: utf-8 -*-
"""默认检索接入 BM25 的守卫（融合统一，2026-10-21）。

B1 召回不变：同一查询在 MDCG_BM25=0/1 下返回的 id 集合相同（BM25 只改排序强度）
B2 不崩：两种模式下都返回非空结果与 meta
B3 集成点在位：md_cg/mdcos.py 的 search 里存在 BM25 接线标记
"""
from __future__ import annotations

import io
import os
import tempfile

from .mdcos import MdCGSecure


def _search(flag):
    os.environ["MDCG_BM25"] = flag
    root = tempfile.mkdtemp(prefix="bmdef_")
    cg = MdCGSecure(root)
    cg.add("n1", "灵枢 记忆库 说明 文档 通用 内容", layer="knowledge")
    cg.add("n2", "灵枢 记忆库 说明 文档 通用 内容 阿洛芬希德 专有名词", layer="knowledge")
    cg.add("n3", "灵枢 记忆库 说明 文档 通用 内容 常见词 反复", layer="knowledge")
    res, meta = cg.search("灵枢 记忆库 说明", k=3)
    ids = []
    for row in res:
        doc = row[0] if isinstance(row, tuple) else row
        if isinstance(doc, dict):
            ids.append(doc.get("id"))
    return ids, meta


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

    ids_off, meta_off = _search("0")
    ids_on, meta_on = _search("1")
    chk(bool(ids_off) and bool(ids_on), "B2 两种模式都返回非空结果（off=%d on=%d）" % (len(ids_off), len(ids_on)))
    chk(set(ids_off) == set(ids_on), "B1 召回集合一致（BM25 只改排序）: %s vs %s" % (ids_off, ids_on))
    chk(isinstance(meta_on, dict) and isinstance(meta_off, dict), "B2b meta 形态不变")
    src = io.open(os.path.join(os.path.dirname(__file__), "mdcos.py"), encoding="utf-8").read()
    chk("MDCG_BM25" in src and "_bm_for(docs)" in src, "B3 集成点在位（search 内 BM25 接线）")

    print("=" * 60)
    print("BM25 默认接入守卫：%d 通过 / %d 失败" % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
