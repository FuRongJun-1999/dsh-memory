# -*- coding: utf-8 -*-
"""入队面第二道层闸漏传 skip_gate 的守卫（issue #1006）。

【守什么】
`MdCGSecure.propose` 有两道层闸：① 入队面自身（#709 已显式 skip_gate=True 修好）；
② 既有节点真层真密级复核（#346 引入，**没继承 skip_gate**）。后果（issue 原文）：
enforce 档下同一函数、同一身份，**新节点能入队、既有节点入不了队**——
「要写 knowledge 需 reflect → 要 reflect 需裁决 → 要裁决需有提案 → 提案又要 reflect」
的第二支路死锁。

判据：
  P1 新节点入队：enforce 下正常
  P2 既有节点入队：enforce 下**也**正常（修复点；修复前必红）
  P3 skip_gate 不绕过层白名单：只允许 contextual 的身份对既有 knowledge 节点入队 ⇒ 拒
  P4 skip_gate 不绕过密级：clearance=internal 的身份对既有 secret 节点入队 ⇒ 拒
  P5 落盘面未被削弱：enforce 下 add 新节点仍被写闸拒（跳过闸只给不落盘的入队）
  P6 缺省不跳过：其它调用点直接 require_layer(...) 在 enforce 下仍拒（默认 skip_gate=False）

运行：python -X utf8 -m md_cg.test_issue1006_propose_existing_gate
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import protect
from md_cg.mdcos import MdCGOS, MdCGSecure
from md_cg.security import AccessDenied, Principal

_OK = 0
_BAD = []


def _check(name, cond, extra=""):
    global _OK
    if cond:
        _OK += 1
        print("  ok   %s %s" % (name, extra))
    else:
        _BAD.append(name)
        print("  FAIL %s %s" % (name, extra))


def _princ(**kw):
    base = dict(tenant="t", actor="u", clearance="secret",
                can_write=True, can_admin=True)
    base.update(kw)
    return Principal(**base)


def _seed(root, nid, layer="knowledge", sensitivity=None):
    """用非安全实例直接落盘造「既有节点」——安全实例的 add 本身要过写闸，不能用作种。"""
    seed = MdCGOS(root)
    seed.add(nid, "既有节点正文", layer=layer, sensitivity=sensitivity)


def _proposed(cg, nid, **kw):
    try:
        cg.propose(nid, "候选内容", layer=kw.pop("layer", "knowledge"), **kw)
        return None
    except AccessDenied as exc:
        return exc


def p1_p2(tmp):
    print("== P1/P2 入队面对新节点与既有节点同口径 ==")
    _seed(tmp, "n-exist")
    cg = MdCGSecure(tmp, principal=_princ())
    _check("P1 新节点入队（enforce 下）", _proposed(cg, "n-new") is None)
    exc = _proposed(cg, "n-exist")
    _check("P2 既有节点入队（修复点：此前 AccessDenied）", exc is None,
           "" if exc is None else "-> %s" % str(exc)[:60])


def p3_4(tmp):
    print("== P3/P4 skip_gate 只跳 write_gate 一档，层/密级照常 ==")
    _seed(tmp, "n-know", layer="knowledge")
    _seed(tmp, "n-secret", layer="knowledge", sensitivity="secret")
    cg_l = MdCGSecure(tmp, principal=_princ(layers_allow=("contextual",)))
    _check("P3 层白名单外仍拒", _proposed(cg_l, "n-know") is not None)
    cg_s = MdCGSecure(tmp, principal=_princ(clearance="internal"))
    _check("P4 密级不足仍拒", _proposed(cg_s, "n-secret") is not None)
    cg_ok = MdCGSecure(tmp, principal=_princ())
    _check("P4b 同节点高权身份可入队", _proposed(cg_ok, "n-secret") is None)


def p5_p6(tmp):
    print("== P5/P6 落盘面与其它调用点未被顺带放开 ==")
    cg = MdCGSecure(tmp, principal=_princ())
    denied = False
    try:
        cg.add("n-disk", "落盘正文", layer="knowledge")
    except AccessDenied:
        denied = True
    _check("P5 enforce 下 add 仍被写闸拒", denied)
    _seed(tmp, "n-other")
    cg2 = MdCGSecure(tmp, principal=_princ())
    raised = False
    try:
        protect.require_layer(cg2, "n-other", layer="knowledge")
    except AccessDenied:
        raised = True
    _check("P6 缺省 skip_gate=False：直接调用仍拒", raised)


def main():
    os.environ.pop("MDCG_REVIEW_CHANNELS", None)
    os.environ.pop("MDCG_REVIEWERS", None)
    os.environ["MDCG_WRITE_GATE"] = "enforce"
    p1_p2(tempfile.mkdtemp(prefix="i1006a_"))
    p3_4(tempfile.mkdtemp(prefix="i1006b_"))
    p5_p6(tempfile.mkdtemp(prefix="i1006c_"))
    print()
    print("入队面层闸守卫：%d 通过，%d 失败" % (_OK, len(_BAD)))
    return 1 if _BAD else 0


if __name__ == "__main__":
    sys.exit(main())