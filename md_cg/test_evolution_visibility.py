# -*- coding: utf-8 -*-
"""演化账本 / 抽检闸 / 建议面的四处诚实性守卫（R-557，2026-11-10）。

四个缺陷（审计 P1-E7 / E8 / E9 + P2 认知）：

  a) `evolution.entries` 把 `node_visible(cg, None)` 当「不可见」——索引里查不到
     条目 ⇒ fail-closed False ⇒ **库级条目**（无 node_id 的账）对非管理员整类消失。
  b) `_BULLET_RE` 只吃首行 ⇒ 多行 `pattern` 回读被截断（写进去的与读出来的不一致）。
  c) `comment_gate._stats` 先做 `v in okv`（set）⇒ **dict 裁决直接抛 TypeError**。
  d) `metacognition._advise` 收了 `tt`（trust()）却一次都没用 —— p_trust 有读数
     却从不进建议面。

契约（本文件即其守卫）：

  【1】无 node_id 的条目对非管理员可见；有 node_id 且不可见的仍被剔除（不放松）。
  【2】多行 pattern 写完读回**逐字一致**。
  【3】`_stats` 接受 dict 裁决（{"verdict": …} / {"pass": True}）且计数正确。
  【4】`_advise`：p_trust 低 ⇒ `low_trust`；p_trust=None ⇒ `no_trust_trace`；
      两者都不再落到笼统的 `stable`。

运行：python -m md_cg.test_evolution_visibility
"""
from __future__ import annotations

import os
import shutil
import tempfile

from . import comment_gate, evolution, metacognition
from .mdcos import MdCGSecure
from .security import Principal

PASSED = FAILED = 0


def ok(cond, name):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print("  [PASS] " + name)
    else:
        FAILED += 1
        print("  [FAIL] " + name)


def main():
    tmp = tempfile.mkdtemp(prefix="evovis_")
    try:
        root = os.path.join(tmp, "lib")
        # 写侧用 private clearance 把两种节点都建出来，读侧换 internal —— 这样
        # sec1 对读侧真的不可见（不是靠「没建」制造假前提）。
        writer = MdCGSecure(root, principal=Principal(
            actor="owner", clearance="private", can_write=True))
        writer.add("pub1", "# 功能名：公开" + chr(10) + chr(10) + "公开正文。" + chr(10),
                   layer="knowledge")
        writer.add("sec1", "# 功能名：私有" + chr(10) + chr(10) + "私有正文。" + chr(10),
                   layer="knowledge", sensitivity="private")
        writer.flush()
        writer.rebuild_index()
        cg = MdCGSecure(root, principal=Principal(
            actor="guest", clearance="internal", can_write=True))

        print("[1] 库级条目 vs 不可见节点条目")
        evolution.record(cg, node_id=None, pattern="库级演化：全局规律")
        evolution.record(cg, node_id="pub1", pattern="公开节点演化")
        evolution.record(cg, node_id="sec1", pattern="私有节点演化")
        rows = evolution.entries(cg, limit=0)
        pats = [r.get("pattern") for r in rows]
        ok("库级演化：全局规律" in pats, "G1a 无 node_id 的条目可见（修前整类消失）")
        ok("公开节点演化" in pats, "G1b 可见节点的条目仍在")
        ok("私有节点演化" not in pats, "G1c 不可见节点的条目仍被剔除（不放松）")

        print("[2] 多行 pattern 完整回读")
        multi = "第一行规律：读侧与写侧同源\n第二行细节：多行必须逐字回来\n第三行结论"
        evolution.record(cg, node_id="pub1", pattern=multi)
        got = [r.get("pattern") for r in evolution.entries(cg, node_id="pub1", limit=0)]
        ok(multi in got, "G2a 多行 pattern 逐字回读（修前只剩第一行）")
        ok(any("\n" in (g or "") for g in got), "G2b 回读值里确实保留了换行")

        print("[3] 抽检闸接受 dict 裁决")
        try:
            st = comment_gate._stats([{"verdict": "faithful", "reason": "ok"},
                                      {"verdict": "pass"},
                                      {"verdict": "wrong"},
                                      {"pass": True}])
            err = None
        except Exception as e:                      # noqa: BLE001
            st, err = None, "%s: %s" % (type(e).__name__, e)
        ok(err is None, "G3a dict 裁决不再抛 TypeError（%s）" % (err,))
        ok(st and st["reviewed"] == 4 and st["passed"] == 3,
           "G3b 计数正确（4 审 3 过）：%s" % (st,))
        ok(comment_gate._stats([True, False])["passed"] == 1,
           "G3c 标量裁决口径不变（回归）")

        print("[4] _advise 真用上 trust()")
        tr = {"ok": True, "state_rates": {}, "d_state": "ok", "d2": 0.0,
              "emotion": "stable"}
        cal = {"verdict": "calibrated"}
        bs = {"unresolved_count": 0}
        low = metacognition._advise(tr, cal, bs,
                                    {"ok": True, "p_trust": 0.2, "n_events": 10})
        ok(any(a["code"] == "low_trust" for a in low), "G4a p_trust 低 ⇒ low_trust 建议")
        none = metacognition._advise(tr, cal, bs,
                                     {"ok": True, "p_trust": None, "n_events": 0})
        ok(any(a["code"] == "no_trust_trace" for a in none),
           "G4b 无验证留痕 ⇒ no_trust_trace（不冒充信任正常）")
        good = metacognition._advise(tr, cal, bs,
                                     {"ok": True, "p_trust": 0.9, "n_events": 10})
        ok([a["code"] for a in good] == ["stable"],
           "G4c p_trust 正常 ⇒ 仍落到 stable（不误报）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\ntest_evolution_visibility: %d 通过 / %d 失败" % (PASSED, FAILED))
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
