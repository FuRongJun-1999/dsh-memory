# -*- coding: utf-8 -*-
"""issue #790：原文路径的「否定词 + 虚化动词 + 宾语」收口（方案 C）。"""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from md_cg.mdcg import (MdCG, STATE_ACCEPT, STATE_DEFER,  # noqa: E402
                        _verb_negated_at, _occurrences)

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:300])
        FAILS.append(name)


BODY = ("# 功能名：T\n# 生效条件：PE\n# 子功能：x\n"
        "# 执行：y\n# 验证方式：z\n# 不适用条件：无\n")
NODE = {"frontmatter": {"non_applicable_conditions": [], "verification_basis": "test"},
        "content": BODY}


def st(q):
    return MdCG.judge_qualification(NODE, q, None).get("state")


def main():
    print("=" * 68)
    print("issue #790 · 原文路径「否定+虚化动词」收口")
    print("=" * 68)
    # A1：虚化动词否定（原文路径，大小写同形）——必须 DEFER
    for q in ("未使用 PE 估值", "未采用 PE 估值", "不采用 PE 估值", "没有使用 PE 估值",
              "未使用这种 PE 估值", "未使用 PE"):
        ok(st(q) == STATE_DEFER, "A1 「%s」⇒ DEFER" % q, st(q))
    # A2：折叠路径不回归（全角 / 小写）
    for q in ("未使用 ＰＥ 估值", "未使用 pe 估值"):
        ok(st(q) == STATE_DEFER, "A2 「%s」⇒ DEFER（折叠路径）" % q, st(q))
    # A3：正例不受影响
    for q in ("PE 估值怎么用", "使用 PE 估值", "PE 的估值方法", "这里 PE 估值偏高"):
        ok(st(q) == STATE_ACCEPT, "A3 「%s」⇒ ACCEPT" % q, st(q))
    # A4（保护面）：base 的「不是X」判定一字不动 —— 这是方案 C 与方案 A 的分界
    for q in ("不是 PE", "不是 PE 估值", "并非 PE"):
        ok(st(q) == STATE_ACCEPT, "A4 保护面「%s」仍 ACCEPT" % q, st(q))
    # A5：判据本体（单点）
    s = "未使用 PE 估值"
    occ = _occurrences(s, "PE")
    ok(bool(occ) and all(_verb_negated_at(s, i) for i in occ),
       "A5 _verb_negated_at 对「未使用 PE」判否定", occ)
    s2 = "不是 PE"
    occ2 = _occurrences(s2, "PE")
    ok(bool(occ2) and not any(_verb_negated_at(s2, i) for i in occ2),
       "A5b _verb_negated_at 对「不是 PE」**不**判否定（保护面）", occ2)
    print()
    print("issue #790：%d 项失败" % len(FAILS) if FAILS else "issue #790：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())