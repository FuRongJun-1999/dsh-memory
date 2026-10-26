# -*- coding: utf-8 -*-
"""issue #659 第三批守卫：hotcache 开关登记 + 重音折叠不误伤假名浊点。"""
from __future__ import annotations

from . import hotcache
from .mdcg import fold_accents


def main():
    ok = bad = 0

    def chk(cond, label, extra=""):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("  PASS", label)
        else:
            bad += 1
            print("  FAIL", label, extra)

    # ---- F26-16：门槛开关必须进热路径缓存键（漏登 = 跨口径串味） ----
    for name in ("MDCG_MIN_SCORE", "MDCG_RECALL_MIN_SCORE"):
        chk(name in hotcache._ENV_SWITCHES,
            "#659 F26-16 %s 已登记 hotcache._ENV_SWITCHES" % name)

    # ---- F26-27：Mn 剥离只针对拉丁组合记号，不得折叠假名浊点 ----
    chk(fold_accents("café") == "cafe", "#659 F26-27 拉丁重音仍折叠（café → cafe）")
    chk(fold_accents("が") != fold_accents("か"),
        "#659 F26-27 日文浊点不折叠（が ≠ か）",
        (fold_accents("が"), fold_accents("か")))
    chk(fold_accents("ば") != fold_accents("は"), "#659 F26-27 半浊点不折叠（ば ≠ は）")
    chk(fold_accents("ＡＢＣ１２３") == "ABC123", "#659 F26-27 NFKC 全角折叠不受影响")

    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
