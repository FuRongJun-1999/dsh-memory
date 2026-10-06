# -*- coding: utf-8 -*-
"""状态槽位寄存器投影（L2「主体×谓词槽位」）——**事件是源、槽位是投影**。

设计稿：`docs/plans/语义时空图补全_世界模型功能端_设计_v0.1.md` §2/§3（P2 批）。

本模块是**投影，不是第二真源**：
  · 源＝`md_cg/state_events.py` 的 append-only 台账 `<root>/_state_events.jsonl`；
  · 查询时**现算**——不落盘、不建缓存、不写任何盘面文件；
  · 台账追加一条，投影立刻随之变化（无缓存、无物化表 ⇒ 无第二真源、无漂移面）；
  · 本模块**只读**台账（经 `state_events.read`；`append` 归 `state_events`）。

投影单元字段（设计稿 §3 表逐字）：
    subject / slot / value / state(active|retired) / t_from / t_to /
    seq_from / seq_to / tier / alternatives / blindspots / history / event_count

回放规则（分组键 `(subject, slot)`，组内按 `state_events.read()` 的**落盘序**）：
  · `value` 自 None 起：事件 `new` 非空 → `value=new`；`new` 空（撤回）→ `value=None`
    且 `state=retired`；其后带值事件自然复活（事件序自然处理，无特判分支）。
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
——两者一致时等价；冲突时以 payload 为准（不按标签改写数据）。判据单点＝`_is_void`。

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


# 生效条件：rec 为台账记录 dict——`rec.get("new")` 为 None 时返回 True（撤回/值作废），非 None 时返回 False；入参非 dict 时按 `.get` 抛 AttributeError（台账读面保证为 dict，不吞错）。
def _is_void(rec) -> bool:
    """撤回判据（单点）：`new` 为空＝值作废、无新值（口径见模块头）。"""
    return rec.get("new") is None


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


# 生效条件：recs 为台账记录序列（落盘序，可空）时——按 (subject, slot) 分组（组序＝首现序）后按 (str(subject), str(slot)) 字典序稳定排序，逐组经 _replay；include_retired 为假时剔除 state=='retired' 的单元，为真时全留；返回单元列表（recs 为空返回 []）；history 透传 _replay（假时不带 history 键）。
def _project(recs, *, include_retired=False, history=True) -> list:
    """记录序列 → 单元列表（project 与 status 共用的回放单点）。"""
    groups = {}
    for rec in recs:
        key = (rec.get("subject"), rec.get("slot"))
        groups.setdefault(key, []).append(rec)
    # 排序键经 str() 归一：台账是外部可写面（append-only），非字符串 subject/slot 会让
    # 裸元组比较抛 TypeError；字符串形态（正常）下与裸元组字典序逐位一致。
    out = []
    for key in sorted(groups, key=lambda k: (str(k[0]), str(k[1]))):
        unit = _replay(key[0], key[1], groups[key], history=history)
        if unit["state"] == "retired" and not include_retired:
            continue
        out.append(unit)
    return out


# 生效条件：cg 可解析出 root（经 state_events.ledger_path）时——以 state_events.read(cg, subject=subject, slot=slot) 为源（subject/slot 非 None 才过滤，空串亦为合法过滤值）、现算回放，返回单元列表；include_retired=False 剔除 state=='retired' 的单元；history=False 时单元不带 history 键；台账缺失/为空返回 []（不报错）。**零落盘、零缓存**——同一调用序列中台账追加一条，下一次调用结果即变。
def project(cg, subject=None, slot=None, include_retired=False,
            history=True) -> list:
    """槽位寄存器投影（查询时现算）：list[dict]（单元字段见模块头）。

    纯读函数：不改台账、不写盘、不缓存；过滤委托 `state_events.read`（单点），
    本模块不另写一套条件解析。
    """
    recs = state_events.read(cg, subject=subject, slot=slot)
    return _project(recs, include_retired=include_retired, history=history)


# 生效条件：cg 可解析出 root 时——一次 state_events.read(cg) 后返回只读统计 dict：events（台账记录总数）/ subjects（去重 subject 数）/ slots（去重 slot 数）/ retired（回放后 state=='retired' 的单元数）/ bad_rows（state_events.BAD_ROWS 累计值，坏行采样与告警由该模块负责）；台账缺失/为空时 events/subjects/slots/retired 皆 0。
def status(cg) -> dict:
    """台账与投影的只读读数（不计语义、不改任何状态）。

    只读一次台账后回放：`bad_rows` 的口径是「累计**跳过动作次数**」（同一坏行每次
    read 均计一次，见 `state_events`）——本函数每次调用只产生**一次** read。
    `slots` 为去重**槽位名**数（同一槽位名挂在多个主体下只算一次）；
    `retired` 为回放后退役单元数（值已作废、未复活）。
    """
    recs = state_events.read(cg)
    units = _project(recs, include_retired=True, history=False)
    return {"events": len(recs),
            "subjects": len({r.get("subject") for r in recs}),
            "slots": len({r.get("slot") for r in recs}),
            "retired": sum(1 for u in units if u["state"] == "retired"),
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
