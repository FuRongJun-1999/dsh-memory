# -*- coding: utf-8 -*-
"""test_state_slots · L2 状态槽位投影守卫（P2 批：事件是源、槽位是投影、查询走 stg）。

契约：`docs/plans/语义时空图补全_世界模型功能端_设计_v0.1.md` §2/§3（六签收点已批准）。

断言分组：

  A 现值/退役——多事件链（含撤回后再来新值**复活**）→ value/state 逐点断言；
    tier 透传（含 retired 态仍取最后有值事件）与缺档位 'unspecified'（不编造）。
  B 区间——t_to/seq_to 被下一事件闭合、末条不闭合（None）；retired 态
    t_from=最后有值事件、t_to=撤回事件（且是**最后一条**撤回）。
  C 变迁史——history 序=落盘序、字段原样（七字段、逐条与台账记录逐字段相等）、
    evidence/actor 回链；history=False 不带 history；尾条与现值互证（history↔value）。
  D 多主体多槽位隔离 + (subject,slot) 字典序稳定排序 + subject/slot 过滤
    + include_retired 过滤。
  E 空台账 → []（不报错）；单事件边界；孤立撤回（起端无可溯源 → None，不编造）。
  F stg.state_chain——开关关 → disabled 返回体（**不抛**、不伪装成空结果）；
    开 → 返回体形态（count/items/truncated/kept）与 limit<命中数时 truncated=True。
  G CLI——进程内调 state_slots._main（隔离 env + temp root）：--status 与
    --subject/--slot/--include-retired/--no-history 输出可解析且与 project/status
    逐值一致（env 根与 --root 显式两路一致）。
  H 不建第二真源——project 一次 → append 新事件 → 再 project 结果即变（无缓存），
    前次返回对象不被就地改写，且投影全程 zero 落盘（root 下文件集合不变）。
  I 坏行可观测——台账写一行坏 JSON → project 不崩、BAD_ROWS 递增、status 同源读数
    （沿 `md_cg/state_events.py` 既有口径）。
  J MCP 面接线（`mcp_server._stg_call` / TOOLS schema）——缺 op 与未知 op 的
    允许枚举含 state_chain、缺省 limit=50、开关关/开经 MCP 面同形、schema 参数与
    描述到位（本组是对 A–I 之外的**接线面**补充，A–I 契约不变）。

隔离：全部落临时目录（`tempfile.mkdtemp`）；env 里的根变量与投影开关全程置空或指向
临时根，**绝不动在役库**（本文件不含任何真实数据根路径字面量）。

运行：python -X utf8 -m md_cg.test_state_slots
      python -X utf8 -m md_cg.test_state_slots --mutate         # 定点变异自证
      python -X utf8 -m md_cg.test_state_slots --mutate --list  # 只列变异表

退出码（fail-closed）：0 = 全绿 / 变异自证 PASS；1 = 有断言失败 / 变异未按预期转红；
2 = ANCHOR-MISS（变异锚点在当前源码里找不到——实现改了却没同步本表即硬失败）。
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import types

from . import state_events
from . import state_slots
from . import stg
from .mdcos import MdCGOS

_PASS = []
_FAIL = []
_GEN = [0]
_TMP = tempfile.mkdtemp(prefix="mdcg_ss_")
_SAVED = {}
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: 被测模块的**可变引用**（定点变异把全局换成变异副本，组内一律经 _ss()/_sg() 取用）。
SS = state_slots
SG = stg
_REAL_SS = state_slots
_REAL_SG = stg


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


def _ss():
    return globals()["SS"]


def _sg():
    return globals()["SG"]


# 生效条件：无入参；把 MDCG_ROOT/MDCG_STATE_ROOT/MDCG_AUX_ROOT/MDCG_DATA_ROOT/MDCG_STG_STATE 的现值存入 _SAVED 并逐个从 os.environ 移除（隔离：任何经 env 取根的路径都不得落到在役库）。
def _sandbox_env():
    for k in ("MDCG_ROOT", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT", "MDCG_DATA_ROOT",
              "MDCG_STG_STATE"):
        _SAVED[k] = os.environ.get(k)
        os.environ.pop(k, None)


# 生效条件：无入参；把 _SAVED 逐个还原（原值 None 则移除键），恢复进程原有 env 形态。
def _restore_env():
    for k, v in _SAVED.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# 生效条件：无入参；在 _TMP 下新建自增代次目录并返回其上的 MdCGOS 实例（每调用一个新根：组间与变异轮间零串味；root 全在临时目录内）。
def _fresh_cg():
    _GEN[0] += 1
    return MdCGOS(os.path.join(_TMP, "gen%d" % _GEN[0], "root"))


# 生效条件：cg 为沙箱实例、subject/slot 为过滤值、include_retired/history 为投影参数时，返回该过滤下**首个**单元（无命中返回 None）。
def _one(cg, subject, slot, include_retired=False, history=True):
    us = _ss().project(cg, subject=subject, slot=slot,
                       include_retired=include_retired, history=history)
    return us[0] if us else None


# 生效条件：argv 为 _main 的入参列表时——在 stdout 重定向下进程内调用 state_slots._main，返回 (退出码, 捕获文本)；_main 抛异常时不吞（交由调用组记红）。
def _run_main(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = _ss()._main(argv)
    return rc, buf.getvalue()


# 生效条件：txt 为 CLI 输出文本时返回 json.loads(txt)；解析失败抛原异常（CLI 输出必须可解析，不吞）。
def _load(txt):
    return json.loads(txt)


# ---------------------------------------------------------------- A
# 生效条件：无入参；在自有沙箱根上按「启用→迁移→撤回→复活→带档位迁移→再撤回」推进甲/住所槽位，逐点断言 value/state/tier/event_count（落点见组内文案）。
def gA():
    print("== A 现值 / 退役（撤回后复活） ==")
    cg = _fresh_cg()
    state_events.append(cg, "甲", "住所", old=None, new="别墅", kind="enablement",
                        seq=1, evidence="u1", actor="user")
    u1 = _one(cg, "甲", "住所")
    ok(u1 and u1["value"] == "别墅" and u1["state"] == "active",
       "A1 首值生效（active / 别墅）", u1)
    state_events.append(cg, "甲", "住所", old="别墅", new="小屋", kind="migration",
                        seq=2, evidence="u2")
    u2 = _one(cg, "甲", "住所")
    ok(u2 and u2["value"] == "小屋" and u2["state"] == "active",
       "A2 迁移后现值＝新值（active / 小屋）", u2)
    state_events.append(cg, "甲", "住所", old="小屋", new=None, kind="retraction",
                        seq=3, evidence="u3")
    u3 = _one(cg, "甲", "住所", include_retired=True)
    ok(u3 and u3["value"] is None and u3["state"] == "retired",
       "A3 撤回：value=None 且 state=retired", u3)
    ok(_one(cg, "甲", "住所") is None,
       "A3b 缺省投影剔除退役单元（include_retired=False）")
    state_events.append(cg, "甲", "住所", old=None, new="船屋", kind="enablement",
                        seq=4, evidence="u4")
    u4 = _one(cg, "甲", "住所")
    ok(u4 and u4["value"] == "船屋" and u4["state"] == "active",
       "A4 撤回后新值复活（active / 船屋；事件序自然处理）", u4)
    ok(u4 and u4["event_count"] == 4,
       "A5 event_count=4（退役段一并计入该槽位）", u4 and u4["event_count"])
    ok(u4 and u4["tier"] == state_slots.TIER_UNSPECIFIED,
       "A6 无 tier → 'unspecified'（不编造档位）", u4 and u4["tier"])
    state_events.append(cg, "甲", "住所", old="船屋", new="岸上公寓",
                        kind="migration", seq=5, evidence="u5",
                        extra={"tier": "一手"})
    u5 = _one(cg, "甲", "住所")
    ok(u5 and u5["tier"] == "一手",
       "A7 extra.tier 透传（append(extra=…) 并入行顶层）", u5 and u5["tier"])
    state_events.append(cg, "甲", "住所", old="岸上公寓", new=None,
                        kind="retraction", seq=6, evidence="u6")
    u6 = _one(cg, "甲", "住所", include_retired=True)
    ok(u6 and u6["state"] == "retired" and u6["tier"] == "一手",
       "A8 retired 态 tier 仍取**最后有值**事件（一手）", u6 and (u6["state"], u6["tier"]))


# ---------------------------------------------------------------- B
# 生效条件：无入参；在自有沙箱根上构造「有值→撤回」与「末条有值」两类单元及双撤回链，断言 t_from/t_to/seq_from/seq_to 的闭合形态（落点见组内文案）。
def gB():
    print("== B 区间（闭合 / 未闭合 / retired 闭合点） ==")
    cg = _fresh_cg()
    r1 = state_events.append(cg, "乙", "住所", old=None, new="X",
                             kind="enablement", seq=10, evidence="b1")
    r2 = state_events.append(cg, "乙", "住所", old="X", new=None,
                             kind="retraction", seq=11, evidence="b2")
    u = _one(cg, "乙", "住所", include_retired=True)
    ok(u and u["state"] == "retired" and u["value"] is None,
       "B1 撤回后 retired / value=None", u)
    ok(u and u["t_from"] == r1["t"] and u["seq_from"] == 10,
       "B2 retired 态 t_from/seq_from ＝最后有值事件（r1）",
       u and (u["t_from"], r1["t"], u["seq_from"]))
    ok(u and u["t_to"] == r2["t"] and u["seq_to"] == 11,
       "B3 retired 态 t_to/seq_to ＝撤回事件（闭合点＝作废时刻）",
       u and (u["t_to"], r2["t"], u["seq_to"]))
    r3 = state_events.append(cg, "乙", "房贷", old=None, new="有",
                             kind="enablement", seq=12, evidence="b3")
    v = _one(cg, "乙", "房贷")
    ok(v and v["t_from"] == r3["t"] and v["seq_from"] == 12
       and v["t_to"] is None and v["seq_to"] is None,
       "B4 台账末条（active）：t_from/seq_from 追溯本条、t_to/seq_to=None（未闭合）",
       v and (v["t_from"], v["seq_from"], v["t_to"], v["seq_to"]))
    r4 = state_events.append(cg, "乙", "房贷", old="有", new=None,
                             kind="retraction", seq=13, evidence="b4")
    w = _one(cg, "乙", "房贷", include_retired=True)
    ok(w and w["t_to"] == r4["t"] and w["seq_to"] == 13,
       "B5 闭合点随撤回事件推进（t_to=撤回事件 t）", w and (w["t_to"], r4["t"]))
    # 双撤回链：闭合点是**最后一条**撤回（=使该槽位进入 retired 的那条），
    # 不是「有值事件的下一条」——两读法在此分道（用 seq 判，不用 t：
    # 连续两次 append 可能落同一时钟刻度，拿时间戳判「不等」会假红）。
    cg2 = _fresh_cg()
    state_events.append(cg2, "己", "槽", old=None, new="A", kind="enablement",
                        seq=14, evidence="b5")
    r6 = state_events.append(cg2, "己", "槽", old="A", new=None,
                             kind="retraction", seq=15, evidence="b6")
    r7 = state_events.append(cg2, "己", "槽", old="A", new=None,
                             kind="retraction", seq=16, evidence="b7")
    z = _one(cg2, "己", "槽", include_retired=True)
    ok(z and z["t_to"] == r7["t"] and z["seq_to"] == 16
       and z["seq_from"] == 14,
       "B6 双撤回：t_to/seq_to ＝最后一条撤回（进入 retired 的那条；"
       "非有值事件的下一条 seq=15）",
       z and (z["t_to"], r6["t"], r7["t"], z["seq_to"]))


# ---------------------------------------------------------------- C
# 生效条件：无入参；在自有沙箱根上写三条带 evidence/actor 的事件，断言 history 的序、字段集、逐字段原样、回链、与现值互证及 history=False 的键省略（落点见组内文案）。
def gC():
    print("== C 变迁史（序 / 字段 / 回链 / history=False） ==")
    cg = _fresh_cg()
    state_events.append(cg, "丙", "烤箱", old=None, new="未启用",
                        kind="enablement", seq=21, evidence="用户侧 r0021",
                        actor="user")
    state_events.append(cg, "丙", "烤箱", old="未启用", new="已启用",
                        kind="enablement", seq=22, evidence="AI 侧 r0022",
                        actor="assistant")
    state_events.append(cg, "丙", "烤箱", old="已启用", new="已拆",
                        kind="migration", seq=23, evidence="r0023")
    recs = state_events.read(cg, subject="丙", slot="烤箱")
    u = _one(cg, "丙", "烤箱")
    ok(u and [h["seq"] for h in u["history"]] == [21, 22, 23],
       "C1 history 序＝落盘序（21/22/23）",
       u and [h["seq"] for h in u["history"]])
    ok(u and len(u["history"]) == u["event_count"] == 3,
       "C2 history 条数＝event_count＝3",
       u and (len(u["history"]), u["event_count"]))
    fields = set(state_slots._HIST_FIELDS)
    ok(u and all(set(h) == fields for h in u["history"]),
       "C3 每条 history 恰为七字段（不发明字段）",
       u and [sorted(h) for h in u["history"]][:1])
    ok(u and len(recs) == 3 and all(
        h[k] == rec.get(k) for h, rec in zip(u["history"], recs)
        for k in fields),
       "C4 字段原样（逐条与台账记录逐字段相等）")
    ok(u and [h["evidence"] for h in u["history"]]
       == ["用户侧 r0021", "AI 侧 r0022", "r0023"]
       and [h["actor"] for h in u["history"]] == ["user", "assistant", ""],
       "C5 evidence/actor 回链（可回查原文）",
       u and [(h["evidence"], h["actor"]) for h in u["history"]])
    ok(u and u["history"][-1]["new"] == u["value"],
       "C6 尾条 new 与现值互证（history↔value）",
       u and (u["history"][-1]["new"], u["value"]))
    u_nh = _one(cg, "丙", "烤箱", history=False)
    ok(u_nh and "history" not in u_nh,
       "C7 history=False 时单元不带 history 键", u_nh and sorted(u_nh))
    ok(u_nh and u_nh["value"] == u["value"]
       and u_nh["event_count"] == u["event_count"]
       and u_nh["seq_from"] == u["seq_from"],
       "C8 history=False 只影响 history 键（其余读数逐位一致）")


# ---------------------------------------------------------------- D
# 生效条件：无入参；在自有沙箱根上铺三主体×两槽位（其中乙/房贷退役），断言字典序排序、include_retired 过滤、subject/slot 过滤与多主体同槽位互不串味（落点见组内文案）。
def gD():
    print("== D 多主体多槽位 / 排序 / 过滤 ==")
    cg = _fresh_cg()
    for i, (s, k, v) in enumerate([("甲", "住所", "别墅"), ("甲", "房贷", "有"),
                                   ("乙", "住所", "帐篷"), ("乙", "房贷", "有"),
                                   ("丙", "住所", "船屋")]):
        state_events.append(cg, s, k, old=None, new=v, kind="enablement",
                            seq=100 + i, evidence="d%d" % i)
    state_events.append(cg, "乙", "房贷", old="有", new=None,
                        kind="retraction", seq=200, evidence="d200")
    pairs = [(u["subject"], u["slot"])
             for u in _ss().project(cg, include_retired=True)]
    # 字典序（码位）：丙(4E19) < 乙(4E59) < 甲(7532)；住所(4F4F) < 房贷(623F)。
    expect = [("丙", "住所"), ("乙", "住所"), ("乙", "房贷"),
              ("甲", "住所"), ("甲", "房贷")]
    ok(pairs == expect, "D1 按 (subject, slot) 字典序稳定排序（含退役单元）", pairs)
    live = _ss().project(cg)
    ok(len(live) == 4 and all(u["state"] == "active" for u in live),
       "D2 include_retired=False 剔除退役单元（5→4，留存全 active）",
       [(u["subject"], u["slot"], u["state"]) for u in live])
    sub = _ss().project(cg, subject="乙")
    ok([(u["subject"], u["slot"]) for u in sub] == [("乙", "住所")],
       "D3 subject 过滤（缺省剔除乙 的退役单元）", sub)
    sub2 = _ss().project(cg, subject="乙", include_retired=True)
    ok([(u["subject"], u["slot"]) for u in sub2]
       == [("乙", "住所"), ("乙", "房贷")],
       "D4 subject 过滤 + include_retired=True（两单元，字典序）",
       [(u["subject"], u["slot"]) for u in sub2])
    sl = _ss().project(cg, slot="住所")
    ok([(u["subject"], u["slot"]) for u in sl]
       == [("丙", "住所"), ("乙", "住所"), ("甲", "住所")],
       "D5 slot 过滤（跨主体，字典序）",
       [(u["subject"], u["slot"]) for u in sl])
    ok(_ss().project(cg, subject="丁") == [],
       "D6 未登记主体 → []（空过滤不报错）")
    m = {(u["subject"], u["slot"]): u["value"]
         for u in _ss().project(cg, include_retired=True)}
    ok(m[("甲", "住所")] == "别墅" and m[("乙", "住所")] == "帐篷"
       and m[("丙", "住所")] == "船屋" and m[("乙", "房贷")] is None,
       "D7 多主体同槽位互不串味（各自现值/退役独立）", m)


# ---------------------------------------------------------------- E
# 生效条件：无入参；在自有沙箱根上断言空台账 → []与 status 全 0、单事件边界各读数、孤立撤回（起端无可溯源）的 None 语义（落点见组内文案）。
def gE():
    print("== E 空台账 / 单事件边界 ==")
    cg = _fresh_cg()
    ok(_ss().project(cg) == [], "E1 空台账 → []（不报错）")
    ok(_ss().project(cg, subject="甲", slot="住所") == [],
       "E2 空台账 + 过滤 → []")
    st = _ss().status(cg)
    ok(st["events"] == 0 and st["subjects"] == 0 and st["slots"] == 0
       and st["retired"] == 0 and isinstance(st["bad_rows"], int),
       "E3 空台账 status 全 0（bad_rows 为 int 读数）", st)
    r = state_events.append(cg, "甲", "住所", old=None, new="唯一值",
                            kind="enablement", seq=7, evidence="e7")
    us = _ss().project(cg)
    ok(len(us) == 1, "E4 单事件 → 恰一个单元", len(us))
    u = us[0]
    ok(u["value"] == "唯一值" and u["state"] == "active"
       and u["event_count"] == 1 and u["t_from"] == r["t"]
       and u["seq_from"] == 7 and u["t_to"] is None and u["seq_to"] is None,
       "E5 单事件边界读数（active / t_from=本条 / t_to=None / count=1）", u)
    ok(len(u["history"]) == 1 and u["history"][0]["seq"] == 7,
       "E6 单事件 history 恰一条")
    ok(u["alternatives"] == [] and u["blindspots"] == [],
       "E7 alternatives/blindspots 结构在场且恒空（口径后置，不臆造）", u)
    cg2 = _fresh_cg()
    r2 = state_events.append(cg2, "戊", "槽", old="悬空旧值", new=None,
                             kind="retraction", seq=8, evidence="e8")
    u2 = _one(cg2, "戊", "槽", include_retired=True)
    ok(u2 and u2["state"] == "retired" and u2["value"] is None
       and u2["t_from"] is None and u2["seq_from"] is None
       and u2["t_to"] == r2["t"],
       "E8 孤立撤回：起端无可溯源 → t_from/seq_from=None（不编造）；t_to=该撤回事件",
       u2)


# ---------------------------------------------------------------- F
# 生效条件：无入参；在自有沙箱根上先按开关关断言 disabled 返回体（不抛、不伪装空结果），再置 MDCG_STG_STATE=1 断言开臂形态、items 与 project 逐位一致、截断标记与参数透传；组末 finally 复开关（不留 env 污染）。
def gF():
    print("== F stg.state_chain（开关关 / 开 + 截断） ==")
    cg = _fresh_cg()
    for i, (s, k, v) in enumerate([("甲", "住所", "别墅"), ("甲", "房贷", "有"),
                                   ("乙", "住所", "帐篷")]):
        state_events.append(cg, s, k, old=None, new=v, kind="enablement",
                            seq=300 + i, evidence="f%d" % i)
    os.environ.pop("MDCG_STG_STATE", None)
    try:
        off = _sg().state_chain(cg)          # 关臂：**不抛**
        ok(isinstance(off, dict) and off.get("error") == "disabled",
           "F1 开关关 → disabled 体（不抛异常）", off)
        ok("MDCG_STG_STATE" in (off.get("hint") or ""),
           "F2 hint 点名开关名（可操作提示）", off.get("hint"))
        ok("items" not in off and "count" not in off,
           "F3 关臂不伪装成空结果（无 items/count 键）", sorted(off))
    except Exception as exc:                             # noqa: BLE001
        ok(False, "F1 开关关 → disabled 体（不抛异常）", repr(exc))
    os.environ["MDCG_STG_STATE"] = "1"
    try:
        on = _sg().state_chain(cg, limit=50)
        ok(on.get("count") == 3 and on.get("kept") == 3
           and on.get("truncated") is False and len(on.get("items") or []) == 3,
           "F4 开臂：count/kept/items 一致、未截断",
           {k: on.get(k) for k in ("count", "kept", "truncated")})
        ok(on.get("items") == _ss().project(cg),
           "F5 items 与 state_slots.project 逐位一致（投影单点，不复制逻辑）")
        ok(on.get("subject") is None and on.get("slot") is None
           and on.get("include_retired") is False and on.get("limit") == 50,
           "F6 返回体回带查询条件（subject/slot/include_retired/limit）",
           {k: on.get(k) for k in ("subject", "slot", "include_retired", "limit")})
        tr = _sg().state_chain(cg, limit=2)
        ok(tr.get("count") == 3 and tr.get("kept") == 2
           and tr.get("truncated") is True,
           "F7 limit(2) < 命中数(3) → truncated=True（截断可观测）",
           {k: tr.get(k) for k in ("count", "kept", "truncated")})
        ok(tr.get("items") == _ss().project(cg)[:2],
           "F8 截断取前 limit 条（序不变）")
        flt = _sg().state_chain(cg, subject="甲", include_retired=True,
                                history=False, limit=1)
        ok(flt.get("count") == 2 and flt.get("kept") == 1
           and flt.get("truncated") is True
           and "history" not in (flt.get("items") or [{}])[0],
           "F9 参数透传（subject/include_retired/history）+ 截断同时可观测",
           {k: flt.get(k) for k in ("count", "kept", "truncated")})
    finally:
        os.environ.pop("MDCG_STG_STATE", None)


# ---------------------------------------------------------------- G
# 生效条件：无入参；在自有沙箱根上把 MDCG_ROOT 指向该根（隔离），进程内调用 _main 的 --status / --subject / --include-retired / --no-history / --root / 缺省六态，断言输出可解析且与 status/project 逐值一致；组末 finally 还原 MDCG_ROOT。
def gG():
    print("== G CLI（--status / --subject；进程内 + 隔离 env） ==")
    cg = _fresh_cg()
    root = cg.root
    state_events.append(cg, "甲", "住所", old=None, new="别墅",
                        kind="enablement", seq=41, evidence="g1")
    state_events.append(cg, "甲", "住所", old="别墅", new=None,
                        kind="retraction", seq=42, evidence="g2")
    state_events.append(cg, "乙", "住所", old=None, new="帐篷",
                        kind="enablement", seq=43, evidence="g3")
    saved = os.environ.get("MDCG_ROOT")
    os.environ["MDCG_ROOT"] = root        # 隔离：CLI 的缺省根＝本沙箱
    try:
        rc, txt = _run_main(["--status"])
        ok(rc == 0, "G1 --status 退出码 0", rc)
        got = _load(txt)
        ok(got == _ss().status(cg),
           "G2 --status 输出可解析且与 status() 逐值一致（缺省根走 env）",
           (txt[:120], got))
        rc, txt = _run_main(["--subject", "乙"])
        ok(rc == 0 and _load(txt) == _ss().project(cg, subject="乙"),
           "G3 --subject 输出与 project(subject=…) 逐值一致", txt[:160])
        rc, txt = _run_main(["--subject", "甲", "--slot", "住所",
                             "--include-retired"])
        ok(rc == 0
           and _load(txt) == _ss().project(cg, subject="甲", slot="住所",
                                           include_retired=True)
           and _load(txt)[0]["state"] == "retired",
           "G4 --subject + --slot + --include-retired（退役单元可见）", txt[:200])
        rc, txt = _run_main(["--subject", "乙", "--no-history"])
        ok(rc == 0
           and _load(txt) == _ss().project(cg, subject="乙", history=False),
           "G5 --no-history 不带 history（与 project(history=False) 一致）")
        rc, txt = _run_main(["--status", "--root", root])
        ok(rc == 0 and _load(txt) == _ss().status(cg),
           "G6 --root 显式给定与 env 缺省两路同值")
        rc, txt = _run_main([])
        ok(rc == 0 and _load(txt) == _ss().project(cg),
           "G7 缺省（无 --status/--subject）打印全量投影")
    finally:
        if saved is None:
            os.environ.pop("MDCG_ROOT", None)
        else:
            os.environ["MDCG_ROOT"] = saved


# ---------------------------------------------------------------- H
# 生效条件：无入参；在自有沙箱根上断言「追加一条事件 → 再投影即变」（无缓存）、前次返回对象不被就地改写、以及投影调用（project/status/无 history）后 root 下文件集合不变（零落盘）。
def gH():
    print("== H 不建第二真源（无缓存 + 零落盘） ==")
    cg = _fresh_cg()
    root = cg.root
    state_events.append(cg, "己", "住所", old=None, new="旧值",
                        kind="enablement", seq=51, evidence="h1")
    u1 = _one(cg, "己", "住所")
    ok(u1 and u1["value"] == "旧值" and u1["event_count"] == 1,
       "H1 首次投影＝旧值（count=1）", u1)
    before = sorted(os.listdir(root))
    state_events.append(cg, "己", "住所", old="旧值", new="新值",
                        kind="migration", seq=52, evidence="h2")
    u2 = _one(cg, "己", "住所")
    ok(u2 and u2["value"] == "新值" and u2["event_count"] == 2,
       "H2 台账追加一条 → 再 project 结果即变（查询时现算，无缓存）", u2)
    ok(u1["value"] == "旧值" and u1["event_count"] == 1,
       "H3 前次返回的单元对象未被就地改写（无跨调用共享可变状态）", u1)
    _one(cg, "己", "住所")
    _ss().status(cg)
    _one(cg, "己", "住所", history=False)
    after = sorted(os.listdir(root))
    ok(after == before,
       "H4 投影零落盘：root 下文件集合不变（不建物化表/缓存文件）",
       (after, before))


# ---------------------------------------------------------------- I
# 生效条件：无入参；在自有沙箱根上追加一行坏 JSON，断言 project 不崩且好行照常、BAD_ROWS 恰 +1（一次 read 记一次）、status.bad_rows 与 state_events.BAD_ROWS 同源、坏行不计入 events/subjects/slots。
def gI():
    print("== I 坏行可观测（沿 state_events 口径） ==")
    cg = _fresh_cg()
    state_events.append(cg, "庚", "住所", old=None, new="好值",
                        kind="enablement", seq=61, evidence="i1")
    p = state_events.ledger_path(cg)
    with open(p, "a", encoding="utf-8") as f:
        f.write("{坏行 json\n")
    n0 = state_events.BAD_ROWS
    us = _ss().project(cg)               # 不崩
    ok(len(us) == 1 and us[0]["value"] == "好值",
       "I1 坏行不中断：好行照常投影", us)
    ok(state_events.BAD_ROWS == n0 + 1,
       "I2 BAD_ROWS 递增 +1（一次 read 记一次，同一坏行每次计）",
       state_events.BAD_ROWS - n0)
    st = _ss().status(cg)
    ok(st["bad_rows"] == state_events.BAD_ROWS,
       "I3 status.bad_rows ＝ state_events.BAD_ROWS（同源读数，不另计数）",
       (st["bad_rows"], state_events.BAD_ROWS))
    ok(st["events"] == 1 and st["subjects"] == 1 and st["slots"] == 1,
       "I4 坏行不计入 events/subjects/slots", st)


# ---------------------------------------------------------------- J
# 生效条件：无入参；在自有沙箱根上经 mcp_server._stg_call 断言：缺 op / 未知 op 的允许枚举含 state_chain、缺省 limit=50 与 history 缺省 true、关臂 disabled 同形、开臂与直调逐位一致、TOOLS 里 stg 的 description 与 inputSchema（subject/slot/include_retired/history + op 枚举）到位；组末 finally 复开关。
def gJ():
    print("== J MCP 面接线（_stg_call / TOOLS schema） ==")
    from . import mcp_server as MS
    cg = _fresh_cg()
    state_events.append(cg, "辛", "住所", old=None, new="甲板", kind="enablement",
                        seq=71, evidence="j1")
    state_events.append(cg, "辛", "住所", old="甲板", new="舱室",
                        kind="migration", seq=72, evidence="j2")
    os.environ.pop("MDCG_STG_STATE", None)
    try:
        off = MS._stg_call(cg, {"op": "state_chain"})
        ok(off.get("error") == "disabled",
           "J1 经 MCP 面（_stg_call）开关关 → disabled 体（不抛）", off)
    finally:
        os.environ.pop("MDCG_STG_STATE", None)
    e1 = e2 = None
    try:
        MS._stg_call(cg, {"op": ""})
    except ValueError as exc:
        e1 = str(exc)
    try:
        MS._stg_call(cg, {"op": "not_an_op"})
    except ValueError as exc:
        e2 = str(exc)
    ok(e1 is not None and "state_chain" in e1,
       "J2 缺 op 的允许枚举含 state_chain（fail-closed 且提示可操作）", e1)
    ok(e2 is not None and "state_chain" in e2,
       "J3 未知 op 的允许枚举含 state_chain", e2)
    os.environ["MDCG_STG_STATE"] = "1"
    try:
        on = MS._stg_call(cg, {"op": "state_chain", "subject": "辛"})
        direct = _sg().state_chain(cg, subject="辛")
        ok(on == direct, "J4 经 MCP 面与直调逐位一致（本层不裁剪/不改写）")
        ok(on.get("limit") == 50 and on.get("count") == 1
           and "history" in (on.get("items") or [{}])[0],
           "J5 缺省 limit=50、history 缺省 true（逐参缺省与文档一致）",
           {k: on.get(k) for k in ("limit", "count")})
        tr = MS._stg_call(cg, {"op": "state_chain", "limit": 1,
                                "history": False})
        ok(tr.get("truncated") is False and tr.get("kept") == 1
           and "history" not in (tr.get("items") or [{}])[0],
           "J6 history=false 透传（不附带变迁史）", {k: tr.get(k) for k in
                                                 ("count", "kept", "truncated")})
    finally:
        os.environ.pop("MDCG_STG_STATE", None)
    # stg 属 kernel 面（KERNEL_TOOLS），故按 ALL_TOOLS 查——只查 TOOLS 会假红。
    stg_tool = next((t for t in MS.ALL_TOOLS if t.get("name") == "stg"), None)
    desc = (stg_tool or {}).get("description") or ""
    props = ((stg_tool or {}).get("inputSchema") or {}).get("properties") or {}
    ok("op=state_chain" in desc and "MDCG_STG_STATE" in desc,
       "J7 TOOLS 的 stg description 含 op=state_chain 与开关名", desc[-90:])
    ok("state_chain" in (props.get("op") or {}).get("description", ""),
       "J8 op 参数枚举含 state_chain（调用契约不落后于实现）",
       (props.get("op") or {}).get("description"))
    ok(all(k in props for k in ("subject", "slot", "include_retired",
                                "history")),
       "J9 inputSchema 增参数 subject/slot/include_retired/history 到位",
       sorted(props))


_GROUPS = (gA, gB, gC, gD, gE, gF, gG, gH, gI, gJ)


# 生效条件：无入参；逐组执行 _GROUPS（每组自行建沙箱根），组内抛异常记为一条失败并把栈尾打印出来（不中断其余组），返回失败条数。
def _run_groups() -> int:
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        try:
            g()
        except Exception as exc:                         # noqa: BLE001
            ok(False, "断言组 %s 抛异常：%s" % (g.__name__, exc))
            import traceback
            print(traceback.format_exc()[-900:])
    return len(_FAIL)


# ---------------------------------------------------------------- 变异表
# 锚点 = (名字, rel, ((old, new), …))。每条必须让套件**转红**（红项原文由 --mutate 打印）：
#   M1 现值改取首值（不随事件推进）→ A2/A4 与 C6（history↔value 互证）红
#   M2 撤回不清空现值且 state 恒 active → A3 与 B1 红
#   M3 t_to/seq_to 恒 None（不闭合）→ B3/B6 红
#   M4 删开关判断（MDCG_STG_STATE 失去作用）→ F1/F2/F3 红
_MUTATIONS = (
    ("现值改取首值（不随事件推进）", "md_cg/state_slots.py",
     (('            value = rec.get("new")\n            last_valued = i',
       '            value = recs[0].get("new") if value is None else value\n'
       '            last_valued = i'),)),
    ("撤回不清空现值且 state 恒 active", "md_cg/state_slots.py",
     (('            value = None            # 撤回：值作废、无新值',
       '            value = value           # 变异：撤回不清空现值'),
      ('    retired = _is_void(last)        # state：最后一个事件的形态决定',
       '    retired = False                  # 变异：state 恒 active'))),
    ("t_to/seq_to 恒 None（不闭合）", "md_cg/state_slots.py",
     (('    if nxt is not None and 0 <= nxt < len(recs):\n'
       '        t_to, seq_to = recs[nxt].get("t"), recs[nxt].get("seq")\n'
       '    else:\n'
       '        t_to, seq_to = None, None',
       '    t_to, seq_to = None, None'),)),
    ("删开关判断（MDCG_STG_STATE 失效）", "md_cg/stg.py",
     (('    if not _flag_on(_STATE_ENV):\n'
       '        return {"error": "disabled",',
       '    if False:\n'
       '        return {"error": "disabled",'),)),
)


# 生效条件：rel 为仓根相对路径时返回该文件的当前源码文本（每次从盘读，不缓存——变异基线必须是**当前工作区**实现）。
def _rel_text(rel: str) -> str:
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


# 生效条件：name/rel/text 给定时——把 text 以 __package__="md_cg"、__file__=<仓内 rel 路径> 执行成命名空间并包成新模块对象返回（不注册 sys.modules、不触发 __main__；语法错误原样抛）。
def _exec_module(name: str, rel: str, text: str):
    ns = {"__name__": name, "__package__": "md_cg",
          "__file__": os.path.join(_REPO, rel)}
    exec(compile(text, rel, "exec"), ns)                 # noqa: S102 —— 基线自证用
    m = types.ModuleType(name)
    m.__dict__.update(ns)
    return m


# 生效条件：list_only 为真时只打印变异表并返回 0；否则先跑未变异基线（必须 0 失败），再逐条在**内存副本**上注入变异（逐锚点 replace，锚点缺失记 ANCHOR-MISS）后重跑整套分组——有红项记 OK、无红项记 MISS（空转即失败）；全部锚点命中有红项时返回 0、否则 1；有 ANCHOR-MISS 时返回 2（fail-closed）。
def _mutate_mode(list_only: bool = False) -> int:
    print("!! 定点变异自证：逐条把机制改回「错误/缺陷」形态，套件必须转红\n")
    if list_only:
        for name, rel, _pairs in _MUTATIONS:
            print("  %-34s [%s]" % (name, rel))
        return 0
    anchor_miss, bad = [], []
    with contextlib.redirect_stdout(buf0 := io.StringIO()):
        clean = _run_groups()
    print("  未变异基线：失败=%d（必须为 0）" % clean)
    if clean:
        bad.append("未变异基线即失败")
        for l in buf0.getvalue().splitlines():      # 基线红项逐条打印（可定位）
            if l.strip().startswith("FAIL "):
                print("        " + l.strip()[5:])
    for name, rel, pairs in _MUTATIONS:
        mut_src, miss = _rel_text(rel), []
        for old, new in pairs:
            if old not in mut_src:
                miss.append(old.splitlines()[0].strip()[:48])
                continue
            mut_src = mut_src.replace(old, new, 1)
        if miss:
            print("  ANCHOR-MISS %s —— 锚点在 %s 源码里找不到（实现改了却没"
                  "同步本表）：%s" % (name, rel, miss))
            anchor_miss.append(name)
            continue
        kind = "SS" if rel.endswith("state_slots.py") else "SG"
        try:
            globals()[kind] = _exec_module("md_cg._ss_mut", rel, mut_src)
            with contextlib.redirect_stdout(buf := io.StringIO()):
                reds = _run_groups()
            detail = buf.getvalue()
        finally:
            globals()["SS"], globals()["SG"] = _REAL_SS, _REAL_SG
        reds_lines = [l for l in detail.splitlines()
                      if l.strip().startswith("FAIL ")]
        verdict = "红" if reds else "**仍全绿 = 该判据空转**"
        print("  %s %-34s 红项=%d  %s"
              % ("OK    " if reds else "MISS  ", name, reds, verdict))
        for l in reds_lines[:6]:
            print("        " + l.strip()[5:])
        if not reds:
            bad.append(name)
    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s"
          % ("PASS（每处机制都有断言把它钉死）" if not bad
             else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def main() -> int:
    _sandbox_env()
    try:
        if "--mutate" in sys.argv:
            return _mutate_mode("--list" in sys.argv)
        n = _run_groups()
        print("\n状态槽位投影守卫：%d 通过 / %d 失败" % (len(_PASS), n))
        print("SUMMARY: md_cg.test_state_slots 通过=%d 失败=%d" % (len(_PASS), n))
        return 0 if not n else 1
    finally:
        _restore_env()
        shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
