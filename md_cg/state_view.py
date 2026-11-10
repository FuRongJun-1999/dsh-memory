# -*- coding: utf-8 -*-
"""状态视图（state_view）——L2 槽位寄存器的**stable 语义 + 多槽位联合投影**。

设计依据：`docs/设计_状态账本与终态投影_v0.1.md` §3.2/§3.3，理论依据《智能论 v3.4》
3.2.2（stable 租约）+ 5.2（混杂系统：连续衰减 dc/dt=-γ(c-c0)、dTTL/dt=-1；
离散跳变 guard(V_hit, t>TTL, conflict) → transition）。

与既有模块的分工（**不新增真源、不复制回放规则**）：
  · `state_events`   = 账本（append-only 唯一真源，五元结构）；
  · `state_slots`    = 纯回放投影（value/state/t_from/t_to/alternatives/history），**不判语义**；
  · **本模块**        = 在 `state_slots` 之上加一层**租约语义**：
        stable ⟺ (now − t_from) < TTL  且 值非撤回
        超时 ⇒ weak=True（**降级不删除**，值仍返回；3.2.2 P1-003）
  并把同一 subject 的**全部槽位联合给出**（§3.3：多要素题需要一次看到全部当前值）。

为什么 TTL 放在这一层而不进 `state_slots`：后者是"回放"语义（同一账本必得同一投影），
TTL 是"此刻是否仍可信"的**时间相关**判断——混进回放会让历史查询随 wall clock 变化。

TTL 取值（**无理论依据，见设计稿 §7 盲区**）：
  · 理论只说「由验证单元按条件空间校准」，未给数 ⇒ 本模块用**槽位名启发式**给缺省，
    并允许 `MDCG_STATE_TTL_DAYS` 全局覆盖（单一标量，便于校准实验）；
  · 日期/时间类 30d · 地点类 365d · 状态类 7d · 其余 180d。
  这不是"事实"，是**可调缺省**；任何读数都要带 TTL 配置一起报。

不适用条件：`pending`（未决值）**未实现**——账本行当前不带置信度字段，
"最后一条断言是否足以改终态"无法从 payload 判出（设计稿 §7 已列此盲区）；
本模块只做「TTL 是否过期」这一条 guard，不臆造冲突判定。
"""
from __future__ import annotations

import os
import time

from . import state_slots

#: 槽位名启发式 → TTL 天数的缺省表（顺序敏感：先命中先返回）。
_TTL_RULES = (
    (("时间", "日期", "time", "date", "deadline", "截止"), 30),
    (("地点", "地址", "place", "location", "住所", "住址"), 365),
    (("状态", "state", "status", "进度", "progress"), 7),
)
#: 兜底 TTL（天）。
TTL_DEFAULT_DAYS = 180


# 生效条件：环境变量 MDCG_STATE_TTL_DAYS 为可解析的正数时返回该值（全局覆盖），否则返回 None
def _env_ttl():
    raw = (os.environ.get("MDCG_STATE_TTL_DAYS") or "").strip()
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if v > 0 else None


#: `extra.ttl` 表示「永不过期」的取值（已发生事实：事件时点/交稿日期/获得日）。
IMMUTABLE_WORDS = ("immutable", "never", "none", "-", "0")


# 生效条件：slot 为字符串（可为 None）；返回 TTL 天数，**None 表示不可变（永不 weak）**
def ttl_days_of(slot, kind=None, ttl=None):
    """槽位租约天数。**判据：这个值会不会被改写**（2026-11 定）。

    优先级（前者胜）：
      ① 调用方显式声明 `extra.ttl`：`"immutable"` ⇒ None（永不 weak）；数字 ⇒ 该天数；
      ② env `MDCG_STATE_TTL_DAYS` 全局覆盖；
      ③ `kind == "migration"`（改期/变更）⇒ 30d：承诺类**会**被改写，必须复核；
      ④ 槽位名启发式（时间30/地点365/状态7/其余180）。

    为什么①优先且要支持 immutable：外测实证——「7 月 20 日交的稿」是不可变历史，
    按槽位名（含『日期』）判 30d 会在 9 月查询时被标 weak，判官看到「需核实」反而降分；
    而「尚未寄出」是状态量，45 天后确实可能已变 ⇒ 该标 weak。**槽位名分不出这两类**，
    只有写入方知道，故以显式声明为准，推断只做保守缺省。
    """
    raw = ttl
    if raw is not None:
        if isinstance(raw, str) and raw.strip().lower() in IMMUTABLE_WORDS:
            return None
        try:
            v = float(str(raw).strip())
        except (TypeError, ValueError):
            v = None
        if v is not None and v > 0:
            return v
    env = _env_ttl()
    if env is not None:
        return env
    if str(kind or "").strip().lower() == "migration":
        return 30.0
    s = str(slot or "").lower()
    for keys, days in _TTL_RULES:
        for k in keys:
            if k in s:
                return float(days)
    return float(TTL_DEFAULT_DAYS)


# 生效条件：unit 为 state_slots 投影单元（含 value/state/t_from）；返回 {weak, age_days, ttl_days, weak_reason}
def lease_of(unit, now=None):
    """算一条槽位单元的租约状态（3.2.2 stable 租约）。"""
    now = time.time() if now is None else float(now)
    u = unit or {}
    ttl = ttl_days_of(u.get("slot"), kind=u.get("kind"), ttl=u.get("ttl"))
    t_from = (unit or {}).get("t_from")
    age = None
    if t_from is not None:
        try:
            age = max(0.0, (now - float(t_from)) / 86400.0)
        except (TypeError, ValueError):
            age = None
    weak = False
    reason = None
    if u.get("state") == "retired":
        reason = "retired"          # 值已撤回：不是 weak，是"没有当前值"
    elif ttl is None:
        reason = "immutable"        # 显式声明不可变：已发生事实，永不 weak
    elif age is None:
        weak, reason = True, "no_timestamp"   # 不知道什么时候确认的 ⇒ 不敢当稳定值
    elif age >= ttl:
        weak, reason = True, "ttl_exceeded"
    return {"weak": weak, "weak_reason": reason, "age_days": None if age is None else round(age, 1),
            "ttl_days": ttl}


# 生效条件：units 为 state_slots 投影单元列表；返回按 subject 归并的视图（同主体全部槽位联合）
def build_view(units, now=None):
    """把槽位单元按 subject 归并成「一个主体一张卡」（设计稿 §3.3）。

    为什么必须联合给：多要素题（如"周五下午谁收、放哪"）要求同一主体
    的时间/参与人/地点**同时在场**；逐槽位分开给等于让模型自己做合成。
    """
    by_subject = {}
    for u in units or []:
        subj = u.get("subject")
        slot = u.get("slot")
        lease = lease_of(u, now=now)
        card = {
            "value": u.get("value"),
            "state": u.get("state"),
            "t_from": u.get("t_from"),
            "t_to": u.get("t_to"),
            "tier": u.get("tier"),
            "alternatives": u.get("alternatives") or [],
            "event_count": u.get("event_count"),
            "kind": u.get("kind"),
            "ttl_declared": u.get("ttl"),
            **lease,
        }
        by_subject.setdefault(subj, {"subject": subj, "slots": {}, "weak_slots": []})
        by_subject[subj]["slots"][slot] = card
        if lease["weak"]:
            by_subject[subj]["weak_slots"].append(slot)
    out = list(by_subject.values())
    # 稳定排序 + 弱值多的排前面（越需要复核的主体越先看到）
    out.sort(key=lambda c: (-len(c["weak_slots"]), str(c["subject"])))
    return out


# 生效条件：cg 提供 root；返回 {view, units_count, weak_count, ttl_env, now}
def state_view(cg, subject=None, slot=None, include_retired=False,
               now=None, history=True, limit=None):
    """读账本 → 回放投影（state_slots）→ 加租约 → 按主体联合。

    纯只读：不写盘、不建缓存；同一账本 + 同一 now 必得同一结果（可复算）。
    """
    units = state_slots.project(cg, subject=subject, slot=slot,
                                include_retired=include_retired, history=history)
    if limit:
        units = units[:int(limit)]
    view = build_view(units, now=now)
    weak = sum(1 for c in view for s in c["weak_slots"])
    return {
        "view": view,
        "units_count": len(units),
        "weak_count": weak,
        "ttl_days_default": TTL_DEFAULT_DAYS,
        "ttl_env": _env_ttl(),
        "now": time.time() if now is None else float(now),
    }
