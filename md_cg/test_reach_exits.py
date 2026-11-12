# -*- coding: utf-8 -*-
"""reach 不再产生 short_term 的静态+动态守卫（issue #611 回归）。

S1 静态：md_cg/reach.py 源码中不再出现 short_term 字样（防注释/代码漂移回潮）
S2 动态：单字符 term 调用 narrow 不得返回 short_term
S3 出口清单：允许的 reach 值集合固定（converged/off/index_unavailable/hash_incomplete/
   no_tokens/empty_converge/fresh_overflow）
"""
from __future__ import annotations

import io
import os
import tempfile

from . import reach as R
from .mdcg import MdCG

ALLOWED = {"converged", "off", "index_unavailable", "hash_incomplete",
           "no_tokens", "empty_converge", "fresh_overflow"}


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

    src = io.open(os.path.join(os.path.dirname(__file__), "reach.py"), encoding="utf-8").read()
    chk("short_term" not in src, "S1 源码中不再出现 short_term（#611 已修）")

    root = tempfile.mkdtemp(prefix="reach_exits_")
    cg = MdCG(root)
    for i, txt in enumerate(("灵枢 记忆库 记录", "记 单字 样本", "无关 内容")):
        cg.add("x%d" % i, txt, layer="knowledge")
    entries = list(cg.index["nodes"].values())
    _got, meta = R.narrow(cg, entries, ["记"], set(), q="记")
    chk(meta.get("reach") != "short_term", "S2 单字符 term 不再返回 short_term（实得 %s）" % meta.get("reach"))
    chk(meta.get("reach") in ALLOWED, "S3 出口值在允许集合内")

    print("=" * 60)
    print("reach 出口守卫：%d 通过 / %d 失败" % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
