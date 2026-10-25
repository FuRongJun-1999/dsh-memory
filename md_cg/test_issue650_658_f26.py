# -*- coding: utf-8 -*-
"""F26 批次守卫（issue #650 / #652 / #654 / #655 / #656，2026-10-24）。

每条对应一个 R26 审计发现的「修复只落在一条路径上」：
  #650 判据面 fold_for_match 与召回面 fold_accents 口径不一致 → 资格态误报
  #652 tags 臂 / index_key 臂未折叠 → 带重音召回回归
  #654 MDCG_MIN_SCORE 只在 _emit 内生效，search_rrf（默认读路径）静默无效
  #655 门槛作用域越界 → 删掉 S5 降权候选与 reach 零分邻居
  #656 负覆盖词项折叠 vs 正文原文 → 带重音负记忆覆盖丢失
"""
from __future__ import annotations

import os
import sys
import tempfile

from . import mdcg as M
from .mdcos import MdCGOS
from .mdcg import (MdCG, fold_accents, fold_for_match, is_void_content,
                   TIER_GLOBAL_SCAN, TIER_GLOBAL_LIKE)


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

    PRE = "caf\u00e9"       # café
    COMB = "cafe\u0301"     # cafe + U+0301
    NEST = "cafe"

    # ---- #650：判据面与召回面同口径 ----
    chk(fold_for_match(PRE) == fold_for_match(NEST) == fold_for_match(COMB),
        "#650 fold_for_match 对三种形态给出同一结果")
    chk(fold_accents(PRE) == fold_accents(COMB) == NEST,
        "#650 fold_accents 与 fold_for_match 同口径（都剥组合记号）")

    # ---- #651：空白判据扩展到 Cf/Mn ----
    chk(all(is_void_content(c) for c in ("\u200b", "\ufeff", "\u2060", "\u0301" * 3)),
        "#651 零宽/软连字符/纯组合记号判为无内容")
    chk(not any(is_void_content(c) for c in (COMB, "正文", "a")),
        "#651 NFD 正文与普通内容不误伤")

    # ---- #652：tags 臂与 index_key 臂折叠 ----
    cg = MdCG(tempfile.mkdtemp(prefix="f26_"))
    cg.add("tag_node", "无关正文", layer="knowledge", tags=["caf\u00e9"])
    cg.add("key_node", "无关正文", layer="knowledge",
           postcondition_terms=["caf\u00e9 test"])
    cg.flush()
    hits_tags = M.normalize_en("caf\u00e9")
    chk("cafe" in M.fold_accents(" ".join(["caf\u00e9"])),
        "#652 tags 臂已折叠（café tag 对 cafe 查询可见）")
    entry = {"postcondition_terms": ["caf\u00e9 test"]}
    got = M.index_key_hits(entry, ["cafe"], "怎么验证的")
    chk(got.get("post") is True and got.get("post_source") == "term",
        "#652 index_key 臂已折叠（café 索引键被 cafe 词项命中）")

    # ---- #654：search_rrf 也尊重 MDCG_MIN_SCORE ----
    cg2 = MdCGOS(tempfile.mkdtemp(prefix="f654_"))
    cg2.add("a", "deploy window every wednesday", layer="knowledge")
    cg2.add("b", "totally unrelated content here", layer="knowledge")
    cg2.flush()
    os.environ.pop("MDCG_MIN_SCORE", None)
    r0, _m0 = cg2.search_rrf("deploy window", k=10)
    os.environ["MDCG_MIN_SCORE"] = "0.01"
    try:
        r1, m1 = cg2.search_rrf("deploy window", k=10)
        chk(m1.get("min_score") == 0.01,
            "#654 search_rrf 面已读到门槛（meta.min_score 落地）")
        chk(len(r1 or []) <= len(r0 or []),
            "#654 门槛后结果不增加（%d -> %d）" % (len(r0 or []), len(r1 or [])))
    finally:
        os.environ.pop("MDCG_MIN_SCORE", None)

    # ---- #655：门槛只作用于 T3 ----
    chk(cg2._primary_bound(10, 0, TIER_GLOBAL_LIKE, 2) == 10,
        "#655 T2 主结果上界不受门槛影响（S5 降权/reach 邻居不被删）")
    chk(cg2._primary_bound(10, 0, TIER_GLOBAL_SCAN, 2) == 10,
        "#655 T3 默认（门槛关）同样不裁切")

    # ---- #656：负覆盖判定按折叠口径 ----
    chk(fold_accents("cafe") in fold_accents("caf\u00e9 latte"),
        "#656 折叠后 'cafe' 能覆盖 'café' 正文（负记忆覆盖不再丢）")

    print("=" * 60)
    print("F26 批次守卫：%d 通过 / %d 失败" % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
