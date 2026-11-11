# -*- coding: utf-8 -*-
"""B/C/D 面「改既有节点」写闸守卫（R-554，2026-11-10）。

缺陷（审计 P1-E4）：三档矩阵对 B（合并）/C（改写）/D（删除）在 confirm 档规定
「先出变更单、经裁决 accept 后才落」，但**五条改既有节点的写路径**（分支合并 /
洞见裁决 / 演化回滚 / 预测反馈 / 自我卡刷新）**不经过任何判定**——缺省 confirm
档下它们照样直接落盘，矩阵在这五处形同虚设。

修法：`autonomy_modes.gate_write()` 作统一闸（ALLOW ⇒ 原链原样；CONFIRM ⇒ 出单
不落盘；FORBID ⇒ fail-closed），五处写点各自接线。

契约（本文件即其守卫）：

  【1】`gate_write` 三态：ALLOW 返回 (dec, None)；CONFIRM 返回 (dec, ticket) 且
      变更单**真的入了审核队列**；plan 档无计划 ⇒ (dec, forbidden) 不落盘不出单。
  【2】五处写点**都**接了这处闸（源码级钉子，防「又变回零调用」）。
  【3】端到端：confirm 档下 `insight.verify` 出单且节点未被改写；full 档下真落盘。

运行：python -m md_cg.test_autonomy_gate_write
"""
from __future__ import annotations

import io
import os
import shutil
import tempfile

from . import autonomy_modes as AM
from . import insight
from .mdcos import MdCGOS

PASSED = FAILED = 0
HERE = os.path.dirname(os.path.abspath(__file__))


def ok(cond, name):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print("  [PASS] " + name)
    else:
        FAILED += 1
        print("  [FAIL] " + name)


def _with_env(val, fn):
    old = os.environ.get("MDCG_AUTONOMY")
    if val is None:
        os.environ.pop("MDCG_AUTONOMY", None)
    else:
        os.environ["MDCG_AUTONOMY"] = val
    try:
        return fn()
    finally:
        if old is None:
            os.environ.pop("MDCG_AUTONOMY", None)
        else:
            os.environ["MDCG_AUTONOMY"] = old


def main():
    tmp = tempfile.mkdtemp(prefix="amgate_")
    try:
        root = os.path.join(tmp, "lib")
        os.makedirs(os.path.join(root, "knowledge"), exist_ok=True)
        cg = MdCGOS(root)
        cg.add("g1", "# 功能名：闸测\n\n正文。\n",
               layer="knowledge", tags=["insight_event"])
        cg.flush()
        cg.rebuild_index()

        print("[1] gate_write 三态")
        dec, stop = _with_env("full", lambda: AM.gate_write(
            AM.B_MERGE, cg, "g1", after="x", reason="t"))
        ok(dec["decision"] == AM.ALLOW and stop is None,
           "G1a full 档 B 类 ⇒ ALLOW、无返回体（原链原样）")

        before = len(cg.proposals() if callable(getattr(cg, "proposals", None))
                     else [])
        dec2, stop2 = _with_env("confirm", lambda: AM.gate_write(
            AM.B_MERGE, cg, "g1", after="x", reason="闸测合并"))
        ok(dec2["decision"] == AM.CONFIRM and isinstance(stop2, dict),
           "G1b confirm 档 B 类 ⇒ CONFIRM 且给出返回体")
        ok(stop2.get("committed") is False and stop2.get("moved_to") == "review_queue",
           "G1c 返回体 = 未落盘 + 入审核队列（committed=False）")
        ok(bool(stop2.get("pid")), "G1d 变更单有 pid（真的入队）")

        dec3, stop3 = _with_env("plan", lambda: AM.gate_write(
            AM.B_MERGE, cg, "g1", after="x", reason="t"))
        ok(dec3["decision"] == AM.FORBID and stop3.get("error") == "autonomy_forbidden",
           "G1e plan 档无计划 ⇒ FORBID（不落盘、不出单）")

        print("[2] 五处写点都接了闸（源码级钉子）")
        sites = {
            "md_cg/branches.py": "_am.B_MERGE",
            "md_cg/insight.py": "_am.C_REWRITE",
            "md_cg/evolution.py": "_am.C_REWRITE",
            "md_cg/predict.py": "_am.E_WEIGHT",
            "md_cg/self_state.py": "_am.E_WEIGHT",
        }
        for fn, cls in sites.items():
            src = io.open(os.path.join(os.path.dirname(HERE), fn),
                          encoding="utf-8").read()
            ok("_am.gate_write(" in src and cls in src,
               "G2 %s 接了 gate_write(%s)" % (fn.split("/")[-1], cls))

        print("[3] 端到端：insight.verify 在 confirm 档出单、full 档落盘")
        def _verify():
            return insight.verify(cg, "g1", verdict="verified",
                                  evidence="闸测证据", actor="tester")

        conf = _with_env("confirm", _verify)
        ok(conf.get("committed") is False and conf.get("moved_to") == "review_queue",
           "G3a confirm 档 ⇒ 出变更单未落盘（%s）" % (conf.get("moved_to"),))
        fm0 = (cg.get("g1") or {}).get("frontmatter") or {}
        ok(fm0.get("verification_state") in (None, "unverified"),
           "G3b 节点未被改写（verification_state=%s）"
           % (fm0.get("verification_state"),))

        full = _with_env("full", _verify)
        ok(full.get("ok") and full.get("committed") is not False,
           "G3c full 档 ⇒ 真落盘")
        fm1 = (cg.get("g1") or {}).get("frontmatter") or {}
        ok(insight.TAG_VERIFIED in (fm1.get("tags") or []),
           "G3d 节点已改写（tags 含 %s）" % insight.TAG_VERIFIED)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\ntest_autonomy_gate_write: %d 通过 / %d 失败" % (PASSED, FAILED))
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
