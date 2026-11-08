# -*- coding: utf-8 -*-
"""alternatives（同期未决值）判定口径探针 —— 只读面，不改写侧。

背景：`state_slots._replay` 把 `alternatives` 恒置空列表，模块头明言「判定口径后置，
不得臆造填充」。本探针回答一个问题：**仅凭既有台账字段，alternatives 能判到什么程度？**

先钉住「不能怎么判」（避免臆造）：
  · 台账 `t` 是 `time.time()` 浮点秒，是**记账时刻**，不是事件的发生时刻；
    ⇒ 不能用「同一时间窗内」做判据（会把两个相隔很久的记账误判成同期）。
  · `seq` 是调用方给的「轮/序号」，可缺省为 None；不是单调保证。
    ⇒ 不能用 seq 差值做「同期」判据。

本探针采用**可判且不臆造**的定义：
  alternatives ＝ 该 (subject, slot) 的变迁史中，**曾被断言过、但不是当前值**的去重值集合。
  即「这个槽位历史上有过、现在不是它的那些值」——它是**历史遗留候选**，
  不是「同期未决」的强语义。探针同时统计有多少组真的会非空，供后续定级。
"""
from __future__ import annotations

import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _PKG)

from md_cg import mdcg, state_events, state_slots  # noqa: E402

_PASS, _FAIL = [], []


def ok(cond, name, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (("  | " + detail) if detail else ""))


def seed(cg):
    """按真实语义造一组事件：迁移 → 迁移 → 撤回。
    住所：旧家 → 新家 → （撤回，值作废）
    身份：学徒（仅一次，无历史）"""
    A = "鲸娘"
    state_events.append(cg, A, "住所", old=None, new="旧家", kind="enablement",
                        seq=1, evidence="第1轮")
    state_events.append(cg, A, "住所", old="旧家", new="新家", kind="migration",
                        seq=2, evidence="第2轮")
    state_events.append(cg, A, "身份", old=None, new="学徒", kind="enablement",
                        seq=3, evidence="第3轮")
    # 撤回：住所值作废
    state_events.append(cg, A, "住所", old="新家", new=None, kind="retraction",
                        seq=4, evidence="第4轮")


def main():
    root = tempfile.mkdtemp(prefix="probe_alt_")
    print("临时库:", root)
    try:
        cg = mdcg.MdCG(root)
        seed(cg)

        recs = state_events.read(cg)
        ok(len(recs) == 4, "A0 台账 4 条", "实际 %d" % len(recs))

        # ---- B：现状基线 —— alternatives 恒空（确认缺口真实存在）----
        # 注意：默认 include_retired=False 会**整单元剔除**已撤回的槽位
        # （「住所」被撤回 ⇒ 不在默认投影里）。要观察 retired 单元必须显式 include_retired=True。
        proj = {(u["subject"], u["slot"]): u for u in state_slots.project(cg)}
        ok(all(u["alternatives"] == [] for u in proj.values()),
           "B0 现状：alternatives 恒为空列表（缺口确认）",
           str({k: v["alternatives"] for k, v in proj.items()}))
        ok(("鲸娘", "住所") not in proj,
           "B1 默认投影剔除已撤回单元（retired 不入默认读面）",
           "keys=%s" % (list(proj),))

        # 要观察 retired 单元需显式 include_retired=True
        proj = {(u["subject"], u["slot"]): u
                for u in state_slots.project(cg, include_retired=True)}

        # ---- C：可判定义下的期望值 ----
        # 住所：历史有 旧家、新家；当前 retired（撤回）⇒ 备择应为 {旧家, 新家}
        # 身份：只有 学徒 一个值，且是当前值 ⇒ 备择应为 []
        zs = proj[("鲸娘", "住所")]
        sf = proj[("鲸娘", "身份")]
        print("    住所 value=%r state=%r" % (zs["value"], zs["state"]))
        print("    身份 value=%r state=%r" % (sf["value"], sf["state"]))

        def _alts(unit):
            """可判定义：历史中出现过、且不等于当前值的去重值（保持首次出现序）。"""
            seen, out = set(), []
            for h in unit.get("history") or []:
                v = h.get("new")
                if state_events.is_void({"new": v}):
                    continue
                if v == unit["value"]:
                    continue
                if v not in seen:
                    seen.add(v)
                    out.append(v)
            return out

        ok(sorted(_alts(zs)) == ["新家", "旧家"],
           "C1 住所：历史遗留两值均为备择", str(_alts(zs)))
        ok(_alts(sf) == [], "C2 身份：无历史遗留 ⇒ 备择为空（不臆造）", str(_alts(sf)))

        # ---- D：关键负向判据 —— 不得把「当前值」算进备择 ----
        ok("学徒" not in _alts(sf), "D1 当前值不进 alternatives")

        # ---- E：撤回态下当前值已作废，历史值全部成为备择 ----
        ok(zs["state"] == "retired" and "新家" in _alts(zs),
           "E1 retired 态：被撤回的值仍进备择（可回溯）")

        # ---- F：排序与去重稳定性（重复值只出现一次）----
        state_events.append(cg, "鲸娘", "住所", old=None, new="新家", kind="enablement",
                            seq=5, evidence="第5轮·复位")
        proj2 = {(u["subject"], u["slot"]): u for u in state_slots.project(cg)}
        zs2 = proj2[("鲸娘", "住所")]
        ok(zs2["value"] == "新家", "F0 复位后当前值=新家", repr(zs2["value"]))
        ok(_alts(zs2) == ["旧家"],
           "F1 当前值新家不入备择，旧家仍在（去重无重复）", str(_alts(zs2)))

        # ---- G：seq / t 不能当同期判据（记录反例，防后人误用）----
        ok(True, "G0 口径备忘：t 是记账时刻、seq 可为 None ⇒ 不用时间窗判「同期」")

    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)

    print("\n== 结果: %d passed / %d failed ==" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("  FAILED:", f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
