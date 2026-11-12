# -*- coding: utf-8 -*-
"""写入闸与检索质量三连守卫（issue #644 / #637 / #636，2026-10-23）。

#644 add 拒收空/空白 content（与 state_events.is_void 同一判据文化）
#637 T3_global_scan 零分条目不进结果、不占 k 配额
#636 NFC/NFD + 无重音查询三种形态互检对称（fold_accents 单点）
"""
from __future__ import annotations

import os
import tempfile

from .mdcg import (MdCG, normalize_en, fold_accents,
                   TIER_GLOBAL_SCAN, TIER_GLOBAL_LIKE)


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

    root = tempfile.mkdtemp(prefix="g3_")
    cg = MdCG(root)

    # ---- #644 ----
    cg.add("ok_node", "deploy window every wednesday", layer="knowledge")
    rejected = []
    for bad_content in ("", "   ", "  \n\t ", None, 12345, ["x"]):
        try:
            cg.add("bad_" + str(abs(hash(str(bad_content))))[:8], bad_content, layer="knowledge")
            rejected.append((bad_content, False))
        except ValueError:
            rejected.append((bad_content, True))
    chk(all(r for _, r in rejected), "#644 空/空白/非字符串 content 一律 ValueError（%s）"
        % ([t for t, r in rejected if not r] or "全部拒绝"))
    leftovers = [f for f in os.listdir(os.path.join(root, "knowledge", "orphan"))
                 if f.startswith("bad_\x00".replace("\x00", ""))] if os.path.isdir(
        os.path.join(root, "knowledge", "orphan")) else []
    chk(not [f for f in leftovers if f.startswith("bad_")], "#644 被拒的写没有一个落盘")
    chk(cg.get("ok_node") is not None, "#644 正常写入不受影响")

    # ---- #637 ----
    # #637 的落点是「可配门槛 + 召回面默认丢零分」：
    # 默认（不做门槛）T3 仍按 k 预算返回，以保住 S1b/S7 的「回退含异桶节点」契约；
    # 设 MDCG_MIN_SCORE 后零分条目不进结果、也不占 k 配额。
    chk(cg._primary_bound(10, 0, TIER_GLOBAL_SCAN, 2) == 10,
        "#637 默认不裁 T3（保住 test_retr_s1b 的回退契约）")
    os.environ["MDCG_MIN_SCORE"] = "0.01"
    try:
        _res, _meta = cg.search("finished", k=10)
        _scores = [r[1] for r in (_res or [])]
        chk(all(sc >= 0.01 for sc in _scores),
            "#637 MDCG_MIN_SCORE=0.01 时零分条目不进结果（scores=%s）" % (_scores,))
    finally:
        os.environ.pop("MDCG_MIN_SCORE", None)

    # ---- #636 ----
    pre = "caf\u00e9 latte shop"
    comb = "cafe\u0301 latte shop"
    chk(normalize_en(pre) == normalize_en(comb) == "cafe latte shop",
        "#636 预合成/组合归一结果逐字相同")
    chk(fold_accents("caf\u00e9") == "cafe", "#636 fold_accents 剥离重音")
    cg.add("n_pre", pre, layer="knowledge")
    cg.add("n_comb", comb, layer="knowledge")
    for q in ("cafe", "cafe\u0301", "caf\u00e9"):
        res, _meta = cg.search(q, k=5)
        ids = [r[0].get("id") for r in (res or [])]
        chk({"n_pre", "n_comb"} <= set(ids), "#636 查询 %r 命中两种形态（%s）" % (q, ids))

    print("=" * 60)
    print("写入闸/检索质量三连守卫：%d 通过 / %d 失败" % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
