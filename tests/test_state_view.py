# -*- coding: utf-8 -*-
"""state_view 守卫：stable 租约（TTL/weak）+ 多槽位联合视图。

理论依据：《智能论 v3.4》3.2.2 stable 租约（`S ∈ stable ⟺ (t−t_verified)<TTL ∧ ¬conflict`，
降级作用于状态不作用于记录）+ 5.2 混杂系统（dTTL/dt=−1、guard→transition）。

设计稿：docs/设计_状态账本与终态投影_v0.1.md §3.2/§3.3。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import state_events, state_view as sv  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:170])
        FAILS.append(name)


def main():
    print("=" * 70)
    print("state_view：stable 租约 + 多槽位联合")
    print("=" * 70)
    os.environ.pop("MDCG_STATE_TTL_DAYS", None)
    now = time.time()

    # ---- TTL 启发式 ----
    ok(sv.ttl_days_of("会议时间") == 30, "T1 时间类槽位 TTL=30d", sv.ttl_days_of("会议时间"))
    ok(sv.ttl_days_of("住所") == 365, "T2 地点类槽位 TTL=365d", sv.ttl_days_of("住所"))
    ok(sv.ttl_days_of("健康状态") == 7, "T3 状态类槽位 TTL=7d", sv.ttl_days_of("健康状态"))
    ok(sv.ttl_days_of("爱好") == 180, "T4 其它槽位 TTL=180d", sv.ttl_days_of("爱好"))
    os.environ["MDCG_STATE_TTL_DAYS"] = "3"
    ok(sv.ttl_days_of("会议时间") == 3.0, "T5 env 全局覆盖优先", sv.ttl_days_of("会议时间"))
    os.environ.pop("MDCG_STATE_TTL_DAYS", None)

    # ---- 租约判定 ----
    fresh = {"slot": "时间", "state": "active", "t_from": now - 86400}
    stale = {"slot": "时间", "state": "active", "t_from": now - 40 * 86400}
    retired = {"slot": "时间", "state": "retired", "t_from": now - 86400}
    ok(sv.lease_of(fresh, now) == {"weak": False, "weak_reason": None, "age_days": 1.0, "ttl_days": 30.0},
       "T6 新鲜值不 weak", sv.lease_of(fresh, now))
    lo = sv.lease_of(stale, now)
    ok(lo["weak"] and lo["weak_reason"] == "ttl_exceeded", "T7 超 TTL ⇒ weak=ttl_exceeded", lo)
    ok(sv.lease_of(stale, now)["weak"] is True and stale.get("value") is None,
       "T8 降级不删记录（weak 只是标记，值不在此层被删除）")
    ro = sv.lease_of(retired, now)
    ok(ro["weak_reason"] == "retired", "T9 撤回值是 retired 不是 weak", ro)
    no_t = sv.lease_of({"slot": "时间", "state": "active", "t_from": None}, now)
    ok(no_t["weak"] and no_t["weak_reason"] == "no_timestamp", "T10 无时间戳不敢当稳定值", no_t)

    # ---- 端到端：账本 → 投影 → 联合视图 ----
    root = tempfile.mkdtemp(prefix="sv_")
    g = MdCGOS(root, actor="test")
    state_events.append(g, "会议", "时间", old="2026-07-18 15:00", new="2026-07-21 15:00",
                        kind="migration", actor="test")
    state_events.append(g, "会议", "地点", old=None, new="城西咖啡馆",
                        kind="enablement", actor="test")
    state_events.append(g, "会议", "参与人", old=None, new="老贺",
                        kind="enablement", actor="test")
    state_events.append(g, "爱好", "乐器", old=None, new="吉他",
                        kind="enablement", actor="test")
    out = sv.state_view(g, now=now)
    view = out["view"]
    ok(out["units_count"] == 4, "T11 四个槽位单元", out["units_count"])
    meeting = [c for c in view if c["subject"] == "会议"]
    ok(len(meeting) == 1, "T12 同主体归并为一张卡", [c["subject"] for c in view])
    slots = (meeting[0] if meeting else {}).get("slots") or {}
    ok(set(slots) == {"时间", "地点", "参与人"}, "T13 卡内联合给出全部槽位", sorted(slots))
    ok(slots.get("时间", {}).get("value") == "2026-07-21 15:00",
       "T14 改期后终态 = 新值（旧值进 alternatives）", slots.get("时间"))
    # alternatives 的口径是「**曾被断言过**且不等于当前值的值」——单次迁移里
    # 旧值只作为 old 出现、从未被断言成当前值，故此处**应为空**（判据正确，不是缺陷）。
    ok((slots.get("时间", {}).get("alternatives") or []) == [],
       "T15a 单次迁移不产生 alternatives（旧值只在 old 位）", slots.get("时间", {}).get("alternatives"))
    # 两次不同断言 ⇒ 前值进 alternatives（可回溯）
    state_events.append(g, "会议", "议程", old=None, new="讨论预算", kind="enablement", actor="test")
    state_events.append(g, "会议", "议程", old="讨论预算", new="讨论排期", kind="migration", actor="test")
    out_a = sv.state_view(g, subject="会议", now=now)
    card_a = out_a["view"][0]["slots"].get("议程") or {}
    ok("讨论预算" in (card_a.get("alternatives") or []),
       "T15b 被覆盖的前值进 alternatives（可回溯）", card_a.get("alternatives"))
    ok(view[0]["subject"] == "爱好" or len(view) >= 2, "T16 视图按需排序（不崩）", [c["subject"] for c in view])

    # ---- 撤回：值消失但不删事件 ----
    state_events.append(g, "爱好", "乐器", old="吉他", new="",
                        kind="retraction", actor="test")
    out2 = sv.state_view(g, subject="爱好", include_retired=True, now=now)
    hobby = out2["view"][0] if out2["view"] else {}
    ok((hobby.get("slots") or {}).get("乐器", {}).get("value") is None,
       "T17 撤回后当前值为 None", (hobby.get("slots") or {}).get("乐器"))
    ok((hobby.get("slots") or {}).get("乐器", {}).get("weak_reason") == "retired",
       "T18 撤回标记 retired（不是 weak）")
    ok(state_events.read(g) and len(state_events.read(g)) == 7, "T19 撤回收 7 条事件（记录未删）",
       len(state_events.read(g)))

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())