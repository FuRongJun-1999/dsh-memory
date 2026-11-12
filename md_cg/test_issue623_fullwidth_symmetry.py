# -*- coding: utf-8 -*-
"""全角/半角字母数字检索对称性守卫（issue #623，2026-10-22）。

根因：normalize_en 的清理字符类 [^\u4e00-\u9fff a-zA-Z0-9] 把全角拉丁/数字
（ＡＢＣ１２３，U+FF01–FF5E）整段清成空格 ⇒ 查询词消失，全角与半角双向不可命中。
修法：清理前先过 routing.nfkc_text（本仓 NFKC 唯一单点）。

F1 normalize_en 全角/半角产出逐字相同
F2 bigram 集合相同（_like/_score/reach 三条腿都吃这一份）
F3 端到端：半角写入、全角查询能命中
F4 端到端：全角写入、半角查询能命中
F5 NFKC 单点没有被绕开（normalize_en 源码里出现 routing.nfkc_text）
"""
from __future__ import annotations

import os
import re
import tempfile

from .mdcg import normalize_en, bigrams
from .mdcos import MdCGSecure

HERE = os.path.dirname(os.path.abspath(__file__))


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

    chk(normalize_en("ＡＢＣ１２３") == normalize_en("ABC123"), "F1 全角/半角归一结果逐字相同")
    chk(bigrams(normalize_en("ＡＢＣ１２３")) == bigrams(normalize_en("ABC123")), "F2 bigram 集合相同")

    root = tempfile.mkdtemp(prefix="nfk_")
    cg = MdCGSecure(root)
    cg.add("half", "ABC123 半角写入的节点", layer="knowledge", tags=["对称性"])
    cg.add("full", "ＡＢＣ１２３ 全角写入的节点", layer="knowledge", tags=["对称性"])

    def ids(q):
        res, _meta = cg.search(q, k=5, record=False)
        return [str(n.get("id")) for n, _s, _q in res]

    got_half = ids("ＡＢＣ１２３")
    chk("half" in got_half, "F3 半角写入 + 全角查询能命中（%s）" % (got_half[:3],))
    got_full = ids("ABC123")
    chk("full" in got_full, "F4 全角写入 + 半角查询能命中（%s）" % (got_full[:3],))

    src = open(os.path.join(HERE, "mdcg.py"), encoding="utf-8").read()
    m = re.search(r"def normalize_en\(.*?\n    cleaned = re\.sub\(.*?\n", src, re.S)
    chk(bool(m) and "routing.nfkc_text" in m.group(0), "F5 normalize_en 走 routing.nfkc_text 单点")

    print("=" * 60)
    print("全角/半角对称性守卫：%d 通过 / %d 失败" % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
