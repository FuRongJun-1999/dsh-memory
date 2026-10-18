# -*- coding: utf-8 -*-
"""状态槽位寄存器投影（L2「主体×谓词槽位」）——**事件是源、槽位是投影**。

设计稿：`docs/plans/语义时空图补全_世界模型功能端_设计_v0.1.md` §2/§3（P2 批）。

本模块是**投影，不是第二真源**：
  · 源＝`md_cg/state_events.py` 的 append-only 台账 `<root>/_state_events.jsonl`；
  · 查询时**现算**——不落盘、不建缓存、不写任何盘面文件；
  · 台账追加一条，投影立刻随之变化（无缓存、无物化表 ⇒ 无第二真源、无漂移面）；
  · 本模块**只读**台账（经 `state_events.iter_read`；`append` 归 `state_events`）。

投影单元字段（设计稿 §3 表逐字）：
    subject / slot / value / state(active|retired) / t_from / t_to /
    seq_from / seq_to / tier / alternatives / blindspots / history / event_count

回放规则（分组键 `(subject, slot)`，组内按 `state_events.read()` 的**落盘序**）：
  · `value` 自 None 起：事件 `new` 非空 → `value=new`；`new` 空（撤回）→ `value=None`
    且 `state=retired`；其后带值事件自然复活（事件序自然处理，无特判分支）。
    「空」＝ `None` **或空白字符串**（#375，2026-10-14；判据单点 `state_events.is_void`（#383：本体在源模块，本模块只绑定））。
  · `state`：**最后一个事件的形态**决定——`new` 空 → `'retired'`；否则 `'active'`。
  · 区间（取值一律用事件行的 `t` 落账时间戳，不另算时间）：
    `t_from`/`seq_from` ＝**最后产生当前值**的那条事件的 `t`/`seq`（retired 态＝
    最后一个**有值**事件的）；`t_to`/`seq_to` ＝**覆盖它的下一条事件**的 `t`/`seq`
    （不存在＝None，即「未闭合／仍有效」）；retired 态的覆盖者＝撤回事件（闭合点
    ＝值作废时刻）。
  · `tier` ＝最后有值事件的顶层 `tier` 透传（`append(extra=…)` 会把 extra 并入行
    顶层，故「extra.tier」与「行顶层 tier」是同一处）；缺失（键不在或为 None）→
    `TIER_UNSPECIFIED`——**不编造**。
  · `alternatives` / `blindspots`：本批**结构在场、恒为空列表**——「同期未决值」与
    「声明缺口」的判定口径**后置**（P1 事件行尚无该信号），**不得臆造填充**。
  · `history` ＝该槽位全部事件原样（每条＝事件行的 `t/seq/old/new/kind/evidence/
    actor` 七字段，值不改写；缺键取 None）；`history=False` 时**不带该键**。

撤回判据取 **payload**（`new` 为空）而不是 `kind` 标签：台账口径是「撤回＝old 有值而
new 为空」（`state_events` 模块头），且该模块明言「分类本身不进判据（记账不判语义）」
——两者一致时等价；冲突时以 payload 为准（不按标签改写数据）。判据单点＝`state_events.is_void`（#383：本体在**源模块**，本模块只绑定不实现）。

过滤与排序：`subject`/`slot` 为 None 不加过滤（该过滤**委托** `state_events.read`，
此处不写第二套条件解析）；`include_retired=False` 剔除 `state=='retired'` 的单元；
结果按 `(subject, slot)` 字典序稳定排序。

CLI（纯只读人工入口，**恒可用、无开关**）：
    python -X utf8 -m md_cg.state_slots --status
    python -X utf8 -m md_cg.state_slots --subject 鲸娘 [--slot 住所]
数据根取 `MDCG_ROOT`（缺省走 `datapath.mdcg_root()`，与 `md_cg/sleep.py` 的
`_main` 同形）。本面与 stg 的 `MDCG_STG_STATE` 开关**无关**：开关管的是 MCP 读面，
CLI 是人工排查入口（只读、不改任何状态）。

不适用条件：本模块**不判语义**——「不是事实」的言语（玩笑/元层/回忆转述）之消歧
标记（`not_fact` 等）不在本批（P1 事件行无该信号）；`alternatives`/`blindspots` 的
真值判定亦未落地（见上，恒空列表）。跨库/多租户合并不在此（单库＝单台账）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import state_events

#: 缺档位占位（台账未带 `tier` 时如实标注，不编造档位）。
TIER_UNSPECIFIED = "unspecified"

#: `history` 条目**必在**字段（单元 schema 逐字；缺键取 None，不改写数据）。
_HIST_FIELDS = ("t", "seq", "old", "new", "kind", "evidence", "actor")


# 生效条件：rec 为台账记录 dict——直接绑定**源模块**判据 `state_events.is_void`（同一函数对象）：`rec.get("new")` 为 None，或为字符串且 `str.strip()` 后为空（含全空白串）时返回 True（撤回/值作废）；其余（非 None 且非空白字符串，含数字 0、False、非空串）返回 False；入参非 dict 时按 `.get` 抛 AttributeError（台账读面保证为 dict，不吞错）。
#: 撤回判据**单点**（#375 口径 ＋ #383 同源上收）：本体在**源模块**
#: `state_events.is_void`（记录面，`None` ∪ 空白串）。本模块**只绑定、不实现**——
#: 「同一语义在两个落点各写一份判据」正是 #375（投影侧）与 #383（写入口侧）的同一
#: 病灶形态；绑定同一函数对象即结构性消除该形态。守卫
#: `md_cg/test_issue383_state_event_write_gate.py` 以 AST 面「全仓含两条腿的判据实现恰
#: 1 处」＋「本模块里它是绑定不是 def」＋运行时 `is` 同一性三条断言钉住。
_is_void = state_events.is_void


# 生效条件：rec 为一条台账记录 dict 时，返回含 _HIST_FIELDS 七键（缺键取 None）的新 dict——字段集＝单元 schema 的 history 条目逐字（不并入行内其余顶层键：新增键即「发明字段」，故限定枚举）；值原样不改写、不改写入参。
def _hist_item(rec) -> dict:
    """变迁史单条：单元 schema 的七字段原样（值不改写）。"""
    return {k: rec.get(k) for k in _HIST_FIELDS}


# 生效条件：subject/slot 为分组键、recs 为同组记录（**非空**，落盘序）、history 为真值时——按模块头回放规则返回单元 dict（含 history 键）；history 为假值时同一单元但不带 history 键；recs 为空时抛 IndexError（组由记录现场建成，恒非空，不吞错）。
def _replay(subject, slot, recs, *, history=True) -> dict:
    """单组回放：现值 / 档位 / 区间 / 变迁史（规则逐条见模块头）。"""
    value = None
    last_valued = None              # 最后**产生当前值**的事件下标（无则 None）
    for i, rec in enumerate(recs):
        if _is_void(rec):
            value = None            # 撤回：值作废、无新值
        else:
            value = rec.get("new")
            last_valued = i
    last = recs[-1]
    retired = _is_void(last)        # state：最后一个事件的形态决定
    if last_valued is None:
        # 全程无有值事件（孤立撤回）：起端无可溯源 ⇒ None（不编造）。
        t_from, seq_from = None, None
        tier = TIER_UNSPECIFIED
    else:
        lv = recs[last_valued]
        t_from, seq_from = lv.get("t"), lv.get("seq")
        tier = lv.get("tier")
        if tier is None:
            tier = TIER_UNSPECIFIED
    # 覆盖者：retired 态＝撤回事件（最后一条，闭合点＝值作废时刻）；否则＝有值事件的
    # **下一条**事件（存在则闭合，不存在＝None＝未闭合）；两者共用同一取舍。
    nxt = (len(recs) - 1) if retired else (
        None if last_valued is None else last_valued + 1)
    if nxt is not None and 0 <= nxt < len(recs):
        t_to, seq_to = recs[nxt].get("t"), recs[nxt].get("seq")
    else:
        t_to, seq_to = None, None
    unit = {"subject": subject, "slot": slot, "value": value,
            "state": "retired" if retired else "active",
            "t_from": t_from, "t_to": t_to,
            "seq_from": seq_from, "seq_to": seq_to,
            "tier": tier,
            # 结构在场、恒空：判定口径后置（模块头，不得臆造填充）。
            "alternatives": [], "blindspots": [],
            "event_count": len(recs)}
    if history:
        unit["history"] = [_hist_item(r) for r in recs]
    return unit


# 生效条件：recs 为落盘序记录（可迭代、可空）时——按 (subject, slot) 分组并稳定排序，经共享分页回放单点返回全量单元；history 为假时不带 history 键；不改写入参记录。
def _project(recs, *, include_retired=False, history=True) -> list:
    """落盘序记录 → 全量投影；流式分组后逐组释放原始记录。"""
    return _project_history_page(recs, include_retired=include_retired,
                                 history=history)[1]


# 生效条件：完整消费落盘序 recs 后，按稳定字典序只构造 limit 条结果（None 为全量，负数归零）；总数不受 limit 影响；被过滤和超额单元不构造 history。
def _project_history_page(recs, *, include_retired=False, history=True,
                          limit=None) -> tuple:
    """一次扫描，分组后只为本页单元回放/构造历史，返回 (总数, 单元)。"""
    groups = {}
    for rec in recs:
        key = (rec.get("subject"), rec.get("slot"))
        groups.setdefault(key, []).append(rec)
    # 排序键经 str() 归一：台账是外部可写面（append-only），非字符串 subject/slot 会让
    # 裸元组比较抛 TypeError；字符串形态（正常）下与裸元组字典序逐位一致。
    cap = None if limit is None else max(0, int(limit))
    out, total = [], 0
    for key in sorted(groups, key=lambda k: (str(k[0]), str(k[1]))):
        rows = groups.pop(key)
        if not include_retired and _is_void(rows[-1]):
            continue
        total += 1
        if cap is None or len(out) < cap:
            out.append(_replay(key[0], key[1], rows, history=history))
    return total, out


# 生效条件：recs 为落盘序记录迭代器时，返回逐单元现值投影；include_retired 为假时剔除退役单元；每单元只留当前字段，零落盘零缓存。
def _project_current(recs, *, include_retired=False) -> list:
    """不保留历史的全量投影（现值归约单点见下）。"""
    return _project_current_page(recs, include_retired=include_retired)[1]


# 生效条件：完整消费 recs；每单元只存计数/最后有值起端/最终闭合端；返回 (总数, 前 limit 条投影)，None 为全量，负数归零；不保留已撤回值正文。
def _project_current_page(recs, *, include_retired=False, limit=None) -> tuple:
    """单遍现值投影：每个 (subject, slot) 只保留当前单元，空间随单元数增长。

    不保留事件正文或完整历史；不缓存、不写盘。撤回仍保留最后有值事件的
    起端与档位，连续撤回使用最后撤回的闭合端；后续有值事件自然复活。
    """
    groups = {}
    for rec in recs:
        key = (rec.get("subject"), rec.get("slot"))
        group = groups.get(key)
        if group is None:
            # count, last valued event's four required fields, final retraction endpoints.
            group = [0, None, None]
            groups[key] = group
        group[0] += 1
        if _is_void(rec):
            group[2] = (rec.get("t"), rec.get("seq"))
            if group[1] is not None:
                # Retraction preserves provenance, but its old value is not returned.
                _, t_from, seq_from, tier = group[1]
                group[1] = (None, t_from, seq_from, tier)
        else:
            group[1] = (rec.get("new"), rec.get("t"), rec.get("seq"), rec.get("tier"))
            group[2] = None
    cap = None if limit is None else max(0, int(limit))
    out, total = [], 0
    for key in sorted(groups, key=lambda k: (str(k[0]), str(k[1]))):
        count, valued, closed = groups.pop(key)
        retired = closed is not None
        if retired and not include_retired:
            continue
        total += 1
        if cap is not None and len(out) >= cap:
            continue
        value, t_from, seq_from, tier = valued if valued is not None else (
            None, None, None, TIER_UNSPECIFIED)
        t_to, seq_to = closed if retired else (None, None)
        out.append({"subject": key[0], "slot": key[1],
                    "value": None if retired else value,
                    "state": "retired" if retired else "active",
                    "t_from": t_from, "t_to": t_to,
                    "seq_from": seq_from, "seq_to": seq_to,
                    "tier": TIER_UNSPECIFIED if tier is None else tier,
                    "alternatives": [], "blindspots": [], "event_count": count})
    return total, out


# 生效条件：cg 可解析 root 时现算回放；history=False 单遍读取且不保留历史，history=True 返回原样七字段历史；subject/slot 非 None 才过滤；include_retired=False 剔除退役单元；缺失/空台账返回 []。零落盘零缓存，后续追加立即可见。
def project(cg, subject=None, slot=None, include_retired=False,
            history=True) -> list:
    """槽位寄存器投影（查询时现算）：list[dict]（单元字段见模块头）。

    纯读函数：不改台账、不写盘、不缓存；过滤委托 `state_events.iter_read`
    （与 read 共用单点），本模块不另写一套条件解析。
    """
    return project_page(cg, subject=subject, slot=slot,
                        include_retired=include_retired, history=history,
                        limit=None)[1]


# 生效条件：参数与 project 同形；完整扫描同一台账一次后返回 (命中总数, 按原排序前 limit 条单元)；None 返回全量，0/负数只计数；全量坏行诊断保留，零落盘零缓存。
def project_page(cg, subject=None, slot=None, include_retired=False,
                 history=True, limit=50) -> tuple:
    """投影分页：总数精确；未返回的单元不构造结果或七字段历史。

    仍完整读一次台账。history=True 的分组保持全部原始事件，回放后即释放；
    history=False 仅保留每个单元的当前元数据。limit 不截断事件读取。
    """
    recs = state_events.iter_read(cg, subject=subject, slot=slot)
    if not history:
        return _project_current_page(recs, include_retired=include_retired, limit=limit)
    return _project_history_page(recs, include_retired=include_retired, limit=limit)


# 生效条件：cg 可解析 root 时——一次完整 iter_read 扫描后返回 events/subjects/slots/retired/bad_rows；每单元只留最后事件是否撤回，不保留历史；空台账计数皆 0，坏行计数与告警仍由 state_events 负责。
def status(cg) -> dict:
    """台账与投影的只读读数（不计语义、不改任何状态）。

    只读一次台账后统计：`bad_rows` 的口径是「累计**跳过动作次数**」（同一坏行每次
    read 均计一次，见 `state_events`）——本函数每次调用只产生**一次** read。
    `slots` 为去重**槽位名**数（同一槽位名挂在多个主体下只算一次）；
    `retired` 为回放后退役单元数（值已作废、未复活）。
    """
    subjects, slots, retired_by_key = set(), set(), {}
    events = 0
    for rec in state_events.iter_read(cg):
        subject, slot = rec.get("subject"), rec.get("slot")
        subjects.add(subject)
        slots.add(slot)
        retired_by_key[(subject, slot)] = _is_void(rec)
        events += 1
    return {"events": events,
            "subjects": len(subjects),
            "slots": len(slots),
            "retired": sum(retired_by_key.values()),
            "bad_rows": state_events.BAD_ROWS}


# 生效条件：root 给定且 md_cg.mdcos 可导入时返回该 root 上的 MdCGOS 实例（形态同 md_cg/sleep.py:_open_cg）；导入失败抛原异常。
def _open_cg(root: str):
    from .mdcos import MdCGOS
    return MdCGOS(root)


# 生效条件：传入 argv（None 取 sys.argv）——--status 时打印 status(cg) 的 JSON 并返回 0；否则要求 --subject（可配 --slot）或 --slot 单用，打印 project(cg, subject, slot, include_retired, history) 的 JSON 并返回 0；两者皆缺时打印**全量投影**（含退役需显式 --include-retired）并返回 0；--root 缺省取 datapath.mdcg_root()（env MDCG_ROOT）；argparse 对未知参数照常以 SystemExit(2) 退出（不吞）。
def _main(argv=None) -> int:
    """只读人工入口：台账现状（--status）/ 槽位投影（--subject [--slot]）。

    本入口**恒可用**（不受 `MDCG_STG_STATE` 开关约束——那把开关管的是 MCP 读面）；
    全程只读：不 append、不落盘、不改任何状态。
    """
    ap = argparse.ArgumentParser(
        description="状态槽位投影（只读）：台账现算，不落盘、不缓存")
    ap.add_argument("--root", default=None, help="数据根（缺省 mdcg_root()）")
    ap.add_argument("--status", action="store_true",
                    help="只打印台账/投影统计（events/subjects/slots/retired/bad_rows）")
    ap.add_argument("--subject", default=None, help="按主体过滤（省略＝不过滤）")
    ap.add_argument("--slot", default=None, help="按槽位过滤（省略＝不过滤）")
    ap.add_argument("--include-retired", dest="include_retired",
                    action="store_true", help="含退役单元（缺省剔除）")
    ap.add_argument("--no-history", dest="history", action="store_false",
                    help="不带变迁史（history 键省略）")
    a = ap.parse_args(argv)
    try:
        # 进程内调用（守卫/嵌入）会重定向 stdout：无 reconfigure 的流上跳过，
        # 不改变任何输出内容。
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                              # noqa: BLE001
        pass
    root = os.path.abspath(a.root or _default_root())
    cg = _open_cg(root)
    if a.status:
        out = status(cg)
    else:
        out = project(cg, subject=a.subject, slot=a.slot,
                      include_retired=a.include_retired, history=a.history)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


# 生效条件：无入参；返回 datapath.mdcg_root()（env MDCG_ROOT 非空时取该值，否则 paths.json/缺省），失败时抛原异常（不吞）。
def _default_root() -> str:
    from .datapath import mdcg_root
    return mdcg_root()


if __name__ == "__main__":
    sys.exit(_main())
