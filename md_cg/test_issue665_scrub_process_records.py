# -*- coding: utf-8 -*-
"""scrub 过程记录误报守卫（issue #665 / #40 残留面）。"""
from __future__ import annotations

import tempfile

from . import scrub
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

    # 1) _kv_pairs：列表行不抽键；rej 的两个固定字段也不抽
    rev = "\n".join([
        "# 功能名：裁决记录",
        "- 提案：prop_aaa",
        "- 轮次：1　裁决：accept",
    ])
    chk(scrub._kv_pairs(rev) == {}, "#665 列表行不抽键（rev 记录零键）")
    rej = "\n".join(["假设：Claude Desktop", "否决原因：V1 未过", "验证：test"])
    chk(scrub._kv_pairs(rej) == {}, "#665 rej 固定字段已在 _SKIP_KEYS")

    # 2) 真矛盾仍能被抽到（阴性对照：判据非恒假）
    real = "\n".join(["端口：8080", "协议：tcp"])
    chk(scrub._kv_pairs(real) == {"端口": "8080", "协议": "tcp"},
        "#665 普通断言行仍可抽键（判据非恒假）")

    # 3) audit 端到端：两条 rev 记录不得互判「同键不同值」
    cg = MdCGOS(tempfile.mkdtemp(prefix="f665_"))
    for i, prop in enumerate(("prop_aaa", "prop_bbb")):
        cg.add("rev_x%d_r1" % i, "\n".join([
            "# 功能名：裁决记录 %d" % i,
            "- 提案：" + prop,
            "- 轮次：1　裁决：accept",
        ]), layer="contextual", role="tool-output",
            tags=["review"], importance=0.4, verification_basis="test")
    cg.flush()
    res = scrub.audit(cg, min_severity="info")
    kinds = [i["kind"] for i in res.get("issues", [])
             if i["node_id"].startswith("rev_x")]
    chk("contradiction" not in kinds,
        "#665 过程记录不再被判同键不同值（实际 kinds=%s）" % (kinds,))
    print("=" * 56)
    print("scrub 过程记录守卫：%d 通过 / %d 失败" % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
