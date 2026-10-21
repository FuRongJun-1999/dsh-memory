# -*- coding: utf-8 -*-
"""conflict_surface 守卫：检索结果内「显式矛盾对」的暴露。

判据面：
  C1 A 的不适用条件 ≥4 字且出现在 B 正文 ⇒ 报一对，并给出证据子串；
  C2 无重叠 ⇒ 空（不制造「可能冲突」）；
  C3 证据短于 4 字 ⇒ 不报（防单字噪声）；
  C4 同一节点不与自己成对；
  C5 as_meta 空结果不产生键（不污染 meta）。
"""
from __future__ import annotations

from . import conflict_surface as CS


def _node(nid, content, negs=None):
    fm = {}
    if negs:
        fm["non_applicable_conditions"] = negs
    return {"id": nid, "frontmatter": fm, "content": content}


def main():
    ok = 0
    bad = 0
    def chk(cond, label):
        nonlocal ok, bad
        if cond:
            ok += 1; print("  PASS", label)
        else:
            bad += 1; print("  FAIL", label)
    a = _node("A", "第一次进入巨子塔是第 14 章。", ["第一次进入巨子塔是第 3 章"])
    b = _node("B", "正文：陈默在第三章章末抵达巨子塔。第一次进入巨子塔是第 3 章。")
    pairs = CS.conflicts_among([a, b])
    chk(len(pairs) == 1 and pairs[0]["a"] == "A" and pairs[0]["b"] == "B", "C1 报出矛盾对")
    chk(pairs and "第 3 章" in pairs[0]["evidence"], "C1b 证据子串可核对")
    chk(CS.conflicts_among([a, _node("C", "完全无关的内容。")]) == [], "C2 无重叠不报")
    chk(CS.conflicts_among([_node("D", "含 乙 字", ["乙"]), _node("E", "含 乙 字")]) == [], "C3 短证据不报")
    chk(CS.conflicts_among([a]) == [], "C4 不与自己成对")
    chk(CS.as_meta([a, b]).get("conflicts_among"), "C5 非空时产生键")
    chk(CS.as_meta([a]) == {}, "C5b 空结果不产生键")
    print("=" * 60)
    print("conflict_surface：%d 通过 / %d 失败" % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())