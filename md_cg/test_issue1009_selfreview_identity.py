# -*- coding: utf-8 -*-
"""裁决者身份不得自证（issue #1009 第 5 项第一半）。

【守什么】
`MdCGOS._dual_review_verdict` 曾写 `who = decided_by or self.actor`——调用方传一个
不是提案者的 `decided_by` 就能盖掉已鉴权的 `self.actor`，绕过 `self_review_forbidden`
（复现：正常 review_decide 被 dual_check_required 拦，带伪造 decided_by 直接写进 layer="self"）。

【判据】
  1. 判定只用 `self.actor`；`decided_by` 只作审计声明（记录 + 标 identity_mismatch，不改结果）。
  2. 二者不符时**留痕**，不是静默。
  3. 源码里不再出现 `decided_by or` 这种「调用方优先」的取身份写法。

运行：python -X utf8 -m md_cg.test_issue1009_selfreview_identity
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mdcos import MdCGOS  # noqa: E402

_OK = 0
_BAD = []


def ok(cond, name, extra=""):
    global _OK
    if cond:
        _OK += 1
        print("  ok   %s %s" % (name, extra))
    else:
        _BAD.append(name)
        print("  FAIL %s %s" % (name, extra))


class _Shim:
    """只借 _dual_review_verdict 的判定体，不落盘。"""

    _dual_review_verdict = MdCGOS._dual_review_verdict

    def __init__(self, actor):
        self.actor = actor


def judge(actor, proposer, decided_by=None, reviewed_by=("反思单元", "验证单元")):
    item = {"pid": "p1", "proposer": proposer}
    return _Shim(actor)._dual_review_verdict(item, "accept", decided_by, review_by_list(reviewed_by))


def review_by_list(v):
    return list(v) if v else None


def main():
    print("=== issue #1009 第 5 项：裁决者不得自证（身份只认 self.actor）===")
    r = judge(actor="same", proposer="same", decided_by=None)
    ok(r.get("error") == "self_review_forbidden", "P1 裁决者==提案者 ⇒ 拒", r.get("error"))

    r = judge(actor="same", proposer="same", decided_by="other")
    ok(r.get("error") == "self_review_forbidden",
       "P2 传 decided_by=他人 仍拒（此前正是这里被绕过）", r.get("error"))
    ok(r.get("decided_by") == "same", "P3 判定身份仍记 self.actor", r.get("decided_by"))
    ok(r.get("decided_by_claimed") == "other", "P4 声明身份被留痕", r.get("decided_by_claimed"))

    r = judge(actor="other", proposer="same")
    ok(r.get("ok") is True, "P5 裁决者!=提案者 ⇒ 放行（不误伤）", r.get("ok"))
    ok(r.get("decided_by") == "other" and not r.get("identity_mismatch"),
       "P6 无声明时不标 mismatch", r)

    r = judge(actor="other", proposer="same", decided_by="third")
    ok(r.get("ok") is True and r.get("identity_mismatch") is True,
       "P7 声明≠实名 ⇒ 放行但标 identity_mismatch（只留痕不授权）", r)

    src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mdcos.py")
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    ok("who = decided_by or" not in src,
       "S1 源码不再有「who = decided_by or ...」取身份写法（注释里留历史说明不算）")
    ok('who = getattr(self, "actor", None) or ""' in src, "S2 判定身份取 self.actor")

    from md_cg import writegate as w
    ok(w.gate_mode({"MDCG_WRITE_GATE": "bogus"}) == "enforce",
       "G1 非法档位 fail-closed 到 enforce（此前 fail-open 到 off）")
    for legal in ("enforce", "warn", "off"):
        ok(w.gate_mode({"MDCG_WRITE_GATE": legal}) == legal, "G2 合法值 %s 不变" % legal)
    ok(w.gate_mode({}) == "enforce", "G3 缺省仍 enforce")

    print()
    print("自证绕过 + 闸门档位：%d 通过，%d 失败" % (_OK, len(_BAD)))
    if _BAD:
        print("失败项：" + " / ".join(_BAD))
    return 1 if _BAD else 0


if __name__ == "__main__":
    sys.exit(main())