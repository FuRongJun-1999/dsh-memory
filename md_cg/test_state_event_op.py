# -*- coding: utf-8 -*-
"""test_state_event_op · cg(op=state_event) 记账写口守卫（P3 批：写侧入口）。

契约：`docs/plans/语义时空图补全_世界模型功能端_设计_v0.1.md` §2「事件是源、槽位是
投影、查询走 stg」＋ §5②（记账入口形态）。本批把「记账」这一步放到 MCP 面：
`md_cg/mcp_server.py` 的 cg 基元新增 op=state_event（写口），底层仍是
`md_cg/state_events.append`（append-only 台账）。

断言分组：

  A 全链——cg(op=state_event) 写入 → `_state_events.jsonl` 得一行（五元
    subject/slot/old/new/kind ＋ seq/evidence/actor 逐字段）→ 投影
    （state_slots.project）与查询面（stg.state_chain，开关开）可见该事件；
    台账追加一条变迁后变迁史条数随之增长；经最外层 `call_tool` 的通路同形。
  B 双闸——① op 映射：state_event 映射到既有 "write" 词（受限令牌的拒绝消息
    点名 op=write 而非 op=state_event；**含 write 不含 state_event** 的白名单
    令牌可记账）；② 写闸 require_write：can_write=False / theory_ok=False /
    clearance 不足三态各自被拒（台账直写盘面、绕过库层节点写闸，故须显式补齐）。
  C 防伪造——请求里塞 actor 参数无效：落盘 actor 恒＝令牌 actor（无 principal
    时＝"system"）。
  D kind 归一——缺省/空串/纯空白 → 落盘 kind=None（「未分类」是合法记账，而
    append 对空串抛 ValueError）；显式合法值（含带空白）strip 后透传；非法值
    ValueError 原样上抛。
  E 参数校验——缺/空 subject、缺/空 slot、old/new 双空 → ValueError 原样上抛
    （fail-closed，不吞、不包装）；合法撤回（old 有值、new 空）照常通过。
  F 回归——既有 op（info/read/recent 抽查）行为与权限行改动前一致：designer
    令牌全过、受限令牌该拒的仍拒且消息点名原 op 词；`_ACTION_SIGS` /
    `_ACTION_DEFAULT` 未被本批改动（state_event 无 action 面）。

隔离：全部落临时目录（`tempfile.mkdtemp`）；env 里的根变量与投影开关全程置空或
指向临时根，令牌签发写临时令牌库，**绝不动在役库/在役令牌库**（本文件不含任何
真实数据根路径字面量）。

运行：python -X utf8 -m md_cg.test_state_event_op
      python -X utf8 -m md_cg.test_state_event_op --mutate         # 定点变异自证
      python -X utf8 -m md_cg.test_state_event_op --mutate --list  # 只列变异表

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

from . import mcp_server
from . import state_events
from . import state_slots
from . import stg
from . import tokens
from .mdcos import MdCGOS, MdCGSecure
from .security import Principal

_PASS = []
_FAIL = []
_GEN = [0]
_TMP = tempfile.mkdtemp(prefix="mdcg_se_")
_SAVED = {}
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_KEK = os.urandom(32)
#: 被测写口模块的**可变引用**（定点变异把全局换成变异副本，组内一律经 _ms() 取用）。
MS = mcp_server
_REAL_MS = mcp_server


# 生效条件：cond 为真记入 _PASS 并打印 PASS，否则记入 _FAIL 并打印 FAIL（extra 仅在失败时打印，供定位）。
def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


# 生效条件：无入参；返回当前被测写口模块（未变异＝mcp_server 本体，变异轮＝内存副本）。
def _ms():
    return globals()["MS"]


# 生效条件：无入参；把 MDCG_ROOT/MDCG_STATE_ROOT/MDCG_AUX_ROOT/MDCG_DATA_ROOT/MDCG_STG_STATE 的现值存入 _SAVED 并逐个从 os.environ 移除（隔离：任何经 env 取根的路径都不得落到在役库）。
def _sandbox_env():
    for k in ("MDCG_ROOT", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT", "MDCG_DATA_ROOT",
              "MDCG_STG_STATE"):
        _SAVED[k] = os.environ.get(k)
        os.environ.pop(k, None)
    # #86（令牌运行期复检）：把复检读的令牌库钉到本进程隔离库——本件 _principal 的签发/
    # 校验都显式落 _tokfile()，而 mcp_server._runtime_token_recheck 经 tokens.token_file(None)
    # 读 env MDCG_TOKEN_FILE（缺省＝在役库）；不钉则复检在在役库查不到本库 token_id ⇒
    # A10（最外层 call_tool 通路）被误判「令牌记录已不存在」。_restore_env 依 _SAVED 原样还原。
    _SAVED["MDCG_TOKEN_FILE"] = os.environ.get("MDCG_TOKEN_FILE")
    os.environ["MDCG_TOKEN_FILE"] = _tokfile()


# 生效条件：无入参；把 _SAVED 逐个还原（原值 None 则移除键），恢复进程原有 env 形态。
def _restore_env():
    for k, v in _SAVED.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# 生效条件：无入参；返回本进程专用的临时令牌库文件路径（签发/校验全落 _TMP，不触在役令牌库）。
def _tokfile():
    return os.path.join(_TMP, "_tokens.json")


# 生效条件：role 为 tokens.ROLE_SPECS 角色名；签发该角色令牌（actor 缺省 evt-<role>）后经 verify_token 取回 Principal；**签发与校验都只落临时令牌库**；未知角色/参数非法时抛原异常（不吞）。
def _principal(role, actor=None, **kw):
    r = tokens.issue(role, actor=actor or ("evt-" + role), path=_tokfile(), **kw)
    return tokens.verify_token(r["token"], path=_tokfile())


# 生效条件：无入参；在 _TMP 下新建自增代次目录并返回其上的 MdCGOS 实例（**无 principal**——测「无令牌只读面」路径；每调用一个新根，组间零串味）。
def _plain_cg():
    _GEN[0] += 1
    return MdCGOS(os.path.join(_TMP, "gen%d" % _GEN[0], "root"))


# 生效条件：principal 为 security.Principal 实例；在 _TMP 下新建自增代次目录并返回其上的 MdCGSecure 实例（principal 参与授权判定；master_key 用进程级随机 kek，密钥库落临时根内）。
def _secure_cg(principal):
    _GEN[0] += 1
    return MdCGSecure(os.path.join(_TMP, "gen%d" % _GEN[0], "root"),
                      principal=principal, master_key=_KEK)


# 生效条件：cg 为沙箱实例、a 为 cg 面参数（不含 op）；按外层 _cg_call 调 op=state_event 并返回其返回体（op 显式传入，不走 op 推导）。
def _evt(cg, **a):
    args = {"op": "state_event"}
    args.update(a)
    return _ms()._cg_call(cg, args)


# 生效条件：fn 为无参可调用对象时——正常返回 ("", "")；抛异常返回 (异常类型名, 错误文本)。用于「该拒的拒、且拒的理由是哪个类型/哪句话」的断言。
def _err(fn):
    try:
        fn()
        return "", ""
    except Exception as exc:                             # noqa: BLE001
        return type(exc).__name__, str(exc)


# 生效条件：cg 为沙箱实例；读取其台账文件并返回逐行 json.loads 的列表（台账缺失 → []；坏行照常抛——守卫只写合法行）。
def _ledger(cg):
    p = state_events.ledger_path(cg)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


# ---------------------------------------------------------------- A
# 生效条件：无入参；在自有沙箱根上（designer 令牌 principal）经 cg(op=state_event) 连写两条事件，断言返回体/落盘行/投影/state_chain 四面对齐、开关关臂不抛、最外层 call_tool 通路同形（落点见组内文案）。
def gA():
    print("== A 全链：记账 → 台账 → 投影 → state_chain ==")
    cg = _secure_cg(_principal("designer", actor="evt-designer"))
    out = _evt(cg, subject="甲", slot="住所", old=None, new="别墅",
               kind="enablement", seq=1, evidence="u1")
    ev = (out or {}).get("event") or {}
    ok(out.get("ok") is True and isinstance(ev, dict),
       "A1 cg(op=state_event) 返回 {ok:true, event:rec}", out)
    ok(ev.get("subject") == "甲" and ev.get("slot") == "住所"
       and ev.get("old") is None and ev.get("new") == "别墅"
       and ev.get("kind") == "enablement" and ev.get("seq") == 1
       and ev.get("evidence") == "u1" and ev.get("actor") == "evt-designer"
       and isinstance(ev.get("t"), (int, float)),
       "A2 event 五元/seq/evidence/actor/t 逐字段", ev)
    lines = _ledger(cg)
    ok(len(lines) == 1, "A3 台账 _state_events.jsonl 恰得一行", len(lines))
    ok(lines and lines[0] == ev,
       "A4 落盘行与返回 event 逐字段相等（落盘记录＝append 返回值）",
       (lines, ev))
    units = state_slots.project(cg, subject="甲", slot="住所")
    ok(len(units) == 1 and units[0]["value"] == "别墅"
       and units[0]["state"] == "active" and units[0]["seq_from"] == 1
       and units[0]["t_from"] == ev.get("t"),
       "A5 投影可见：project 得该槽位单元（value/state/seq_from/t_from 对齐）",
       units)
    os.environ["MDCG_STG_STATE"] = "1"
    try:
        chain = stg.state_chain(cg, subject="甲")
    finally:
        os.environ.pop("MDCG_STG_STATE", None)
    ok(chain.get("count") == 1 and chain.get("kept") == 1
       and (chain.get("items") or []) == state_slots.project(cg, subject="甲"),
       "A6 stg(state_chain)（开关开）可见该事件：items 与 project 逐位一致",
       chain)
    off = stg.state_chain(cg)
    ok(off.get("error") == "disabled",
       "A7 开关关 → disabled 体（「没开」与「没命中」可分辨，不抛）", off)
    out2 = _evt(cg, subject="甲", slot="住所", old="别墅", new="小屋",
                kind="migration", seq=2, evidence="u2")
    ok((out2 or {}).get("ok") is True, "A8 第二条（迁移）写入成功", out2)
    units2 = state_slots.project(cg, subject="甲", slot="住所")
    ok(len(units2) == 1 and units2[0]["value"] == "小屋"
       and units2[0]["event_count"] == 2
       and len(units2[0]["history"]) == 2,
       "A9 变迁史：event_count=2、history 两条（台账追加即投影可见）",
       units2)
    via = _ms().call_tool(cg, "cg",
                          {"op": "state_event", "subject": "乙", "slot": "住所",
                           "new": "帐篷", "seq": 3, "evidence": "u3"})
    ok((via or {}).get("ok") is True
       and (via.get("event") or {}).get("actor") == "evt-designer",
       "A10 经最外层 call_tool（MCP tools/call 通路）同形：ok=true、actor=令牌 actor",
       via)
    ok(len(_ledger(cg)) == 3, "A11 三条事件皆落盘（append-only 不截断）",
       len(_ledger(cg)))


# ---------------------------------------------------------------- B
# 生效条件：无入参；在自有沙箱根上按三类令牌（受限 ops_allow 无 write / 含 write 不含 state_event / designer 星号）与三种写闸不足（can_write=False / theory_ok=False / clearance 不足）逐条断言拒绝或放行，并校验拒绝消息点名的 op 词（落点见组内文案）。
def gB():
    print("== B 双闸：op 映射（write 词）＋ require_write（三态） ==")
    # ① op 映射：受限令牌（白名单无 write）→ 拒，且消息点名 op=write（不是 op=state_event）
    rcg = _secure_cg(_principal("recorder", actor="evt-restricted",
                                ops_allow=["read"]))
    t, txt = _err(lambda: _evt(rcg, subject="甲", slot="住所", new="值"))
    ok(t == "AccessDenied" and "op=write" in txt and "op=state_event" not in txt,
       "B1 受限令牌（ops_allow 无 write）→ AccessDenied 且消息点名 op=write"
       "（映射生效；不引入 state_event 新 op 词）", (t, txt[:120]))
    ok(_ledger(rcg) == [], "B2 被拒时不落盘（台账零行）", _ledger(rcg))
    # ② 含 write 不含 state_event → 可记账（回退成 require_op(op) 则此处转红）
    wcg = _secure_cg(_principal("recorder", actor="evt-writer",
                                ops_allow=["read", "write"]))
    out = _evt(wcg, subject="甲", slot="住所", new="值", seq=1, evidence="b2")
    ok(out.get("ok") is True and len(_ledger(wcg)) == 1,
       "B3 白名单含 write 不含 state_event → 放行并落盘（映射到既有 write 词）",
       out)
    # ③ designer（ops_allow 星号）→ 放行
    dcg = _secure_cg(_principal("designer", actor="evt-designer"))
    out = _evt(dcg, subject="甲", slot="住所", new="值", seq=1)
    ok(out.get("ok") is True, "B4 designer（ops_allow=*）→ 放行", out)
    # ④ guest 令牌（can_write=False，白名单无 write）→ op 闸先拒
    gcg = _secure_cg(_principal("guest", actor="evt-guest"))
    t, txt = _err(lambda: _evt(gcg, subject="甲", slot="住所", new="值"))
    ok(t == "AccessDenied" and "op=write" in txt,
       "B5 guest 令牌 → AccessDenied（只读访客照拒）", (t, txt[:120]))
    # ⑤ 写闸·can_write：直接构造「白名单含 write 但 can_write=False」的 principal
    #    （角色规格里无此组合，须显式构造——这条正是 require_write 补齐的判据）
    ncg = _secure_cg(Principal(actor="evt-nocw", role="guest", clearance="internal",
                               can_write=False, ops_allow=("*",)))
    t, txt = _err(lambda: _evt(ncg, subject="甲", slot="住所", new="值"))
    ok(t == "AccessDenied" and "无写权限" in txt,
       "B6 can_write=False（op 闸放行）→ 被 require_write 拒（写闸显式补齐）",
       (t, txt[:120]))
    ok(_ledger(ncg) == [], "B7 该拒的不落盘", _ledger(ncg))
    # ⑥ 写闸·theory_ok=False
    tcg = _secure_cg(Principal(actor="evt-notheory", clearance="internal",
                               can_write=True, ops_allow=("*",),
                               theory_ok=False))
    t, txt = _err(lambda: _evt(tcg, subject="甲", slot="住所", new="值"))
    ok(t == "AccessDenied" and "版本层校验未通过" in txt,
       "B8 theory_ok=False → 被拒（版本层校验维度）", (t, txt[:120]))
    # ⑦ 写闸·密级：clearance=public < internal
    scg = _secure_cg(Principal(actor="evt-lowclear", clearance="public",
                               can_write=True, ops_allow=("*",)))
    t, txt = _err(lambda: _evt(scg, subject="甲", slot="住所", new="值"))
    ok(t == "AccessDenied" and "clearance" in txt,
       "B9 clearance 不足 internal → 被拒（密级维度）", (t, txt[:120]))


# ---------------------------------------------------------------- C
# 生效条件：无入参；在自有沙箱根上断言请求里塞 actor 参数不生效：带令牌时落盘 actor 恒＝令牌 actor、无 principal 时恒＝"system"（落点见组内文案）。
def gC():
    print("== C 防伪造：actor 恒取令牌/系统（请求参数无效） ==")
    cg = _secure_cg(_principal("recorder", actor="evt-real",
                               ops_allow=["read", "write"]))
    out = _evt(cg, subject="甲", slot="住所", new="值", seq=1,
               evidence="c1", actor="forger")
    ok((out.get("event") or {}).get("actor") == "evt-real",
       "C1 请求 actor=forger 无效：落盘 actor＝令牌 actor", out)
    lines = _ledger(cg)
    ok(lines and lines[0].get("actor") == "evt-real",
       "C2 台账行 actor 逐字＝令牌 actor（不落伪造值）", lines)
    pcg = _plain_cg()
    out = _evt(pcg, subject="甲", slot="住所", new="值", seq=1,
               evidence="c3", actor="forger")
    ok((out.get("event") or {}).get("actor") == "system",
       "C3 无 principal：actor 恒＝system（也不取请求参数）", out)


# ---------------------------------------------------------------- D
# 生效条件：无入参；在自有沙箱根上按 kind 的五态（缺省/空串/纯空白/显式合法含空白/非法）逐条断言落盘归一结果或 ValueError 上抛（落点见组内文案）。
def gD():
    print("== D kind 归一（空串 → None；非法值 fail-closed） ==")
    cg = _secure_cg(_principal("designer", actor="evt-d"))
    out = _evt(cg, subject="甲", slot="s1", new="v1", seq=1)
    ok((out.get("event") or {}).get("kind") is None,
       "D1 缺省 kind → 落盘 None（未分类是合法记账）", out)
    out = _evt(cg, subject="甲", slot="s2", new="v2", seq=2, kind="")
    ok((out.get("event") or {}).get("kind") is None,
       "D2 kind=空串 → 归一 None（不抛 ValueError）", out)
    out = _evt(cg, subject="甲", slot="s3", new="v3", seq=3, kind="   ")
    ok((out.get("event") or {}).get("kind") is None,
       "D3 kind=纯空白 → 归一 None", out)
    out = _evt(cg, subject="甲", slot="s4", new="v4", seq=4, kind="migration")
    ok((out.get("event") or {}).get("kind") == "migration",
       "D4 显式合法值透传", out)
    out = _evt(cg, subject="甲", slot="s5", new="v5", seq=5, kind=" migration ")
    ok((out.get("event") or {}).get("kind") == "migration",
       "D5 带空白合法值 strip 后透传", out)
    t, txt = _err(lambda: _evt(cg, subject="甲", slot="s6", new="v6",
                               kind="bogus"))
    ok(t == "ValueError" and "bogus" in txt,
       "D6 非法 kind → ValueError 原样上抛（fail-closed）", (t, txt[:120]))
    ok(len(_ledger(cg)) == 5, "D7 只有合法五条落盘（非法值不落盘）",
       len(_ledger(cg)))


# ---------------------------------------------------------------- E
# 生效条件：无入参；在自有沙箱根上按 subject/slot/old-new 组合逐条断言 ValueError 原样上抛（不包装、不吞）与合法撤回照常通过（落点见组内文案）。
def gE():
    print("== E 参数校验（ValueError 原样上抛） ==")
    cg = _secure_cg(_principal("designer", actor="evt-e"))
    t, txt = _err(lambda: _evt(cg, slot="住所", new="值"))
    ok(t == "ValueError" and "subject" in txt,
       "E1 缺 subject → ValueError（点名 subject）", (t, txt[:120]))
    t, txt = _err(lambda: _evt(cg, subject="  ", slot="住所", new="值"))
    ok(t == "ValueError" and "subject" in txt,
       "E2 subject 纯空白 → ValueError", (t, txt[:120]))
    t, txt = _err(lambda: _evt(cg, subject="甲", new="值"))
    ok(t == "ValueError" and "slot" in txt,
       "E3 缺 slot → ValueError（点名 slot）", (t, txt[:120]))
    t, txt = _err(lambda: _evt(cg, subject="甲", slot="  ", new="值"))
    ok(t == "ValueError" and "slot" in txt,
       "E4 slot 纯空白 → ValueError", (t, txt[:120]))
    t, txt = _err(lambda: _evt(cg, subject="甲", slot="住所"))
    ok(t == "ValueError" and "old" in txt and "new" in txt,
       "E5 old/new 双空（缺省）→ ValueError", (t, txt[:120]))
    t, txt = _err(lambda: _evt(cg, subject="甲", slot="住所",
                               old=None, new=None))
    ok(t == "ValueError", "E6 old/new 显式双 None → ValueError", (t, txt[:120]))
    out = _evt(cg, subject="甲", slot="住所", old="旧值", new=None,
               kind="retraction", seq=9, evidence="e7")
    ok(out.get("ok") is True
       and (out.get("event") or {}).get("new") is None
       and (out.get("event") or {}).get("old") == "旧值",
       "E7 合法撤回（old 有值、new 空）照常通过", out)
    ok(len(_ledger(cg)) == 1,
       "E8 校验失败的各次均未落盘（台账仅合法撤回一条）", len(_ledger(cg)))


# ---------------------------------------------------------------- F
# 生效条件：无入参；在自有沙箱根上断言既有 op（info/read/recent/未知 op）与受限令牌拒绝路径行为不变（消息点名原 op 词）、无 principal 只读面照常、_ACTION_SIGS/_ACTION_DEFAULT 未被本批改动（落点见组内文案）。
def gF():
    print("== F 回归：既有 op 行为与权限行改动前一致 ==")
    dcg = _secure_cg(_principal("designer", actor="evt-reg"))
    r = _err(lambda: _ms()._cg_call(dcg, {"op": "info"}))
    ok(r[0] == "", "F1 designer：op=info 放行（无异常）", r)
    r = _err(lambda: _ms()._cg_call(dcg, {"op": "read", "query": "回归"}))
    ok(r[0] == "", "F2 designer：op=read 放行", r)
    r = _err(lambda: _ms()._cg_call(dcg, {"op": "recent",
                                          "action": "list"}))
    ok(r[0] == "", "F3 designer：op=recent/list 放行", r)
    t, txt = _err(lambda: _ms()._cg_call(dcg, {"op": "no_such_op"}))
    ok(t == "ValueError",
       "F4 designer：未识别 op 仍走 ValueError 兜底（分发尾部不变）",
       (t, txt[:100]))
    rcg = _secure_cg(_principal("recorder", actor="evt-reg2",
                                ops_allow=["read"]))
    r = _err(lambda: _ms()._cg_call(rcg, {"op": "read", "query": "回归"}))
    ok(r[0] == "", "F5 受限令牌：白名单内 op=read 放行", r)
    t, txt = _err(lambda: _ms()._cg_call(rcg, {"op": "whitebox",
                                               "action": "ping"}))
    ok(t == "AccessDenied" and "op=whitebox" in txt,
       "F6 受限令牌：白名单外 op=whitebox 拒且消息点名 op=whitebox"
       "（非 state_event 的 op 词逐位不变）", (t, txt[:120]))
    t, txt = _err(lambda: _ms()._cg_call(rcg, {"op": "write", "node_id": "x",
                                               "content": "y"}))
    ok(t == "AccessDenied" and "op=write" in txt,
       "F7 受限令牌：白名单外 op=write 拒（既有写面拒绝行为不变）",
       (t, txt[:120]))
    pcg = _plain_cg()
    r = _err(lambda: _ms()._cg_call(pcg, {"op": "read", "query": "回归"}))
    ok(r[0] == "", "F8 无 principal（MdCGOS）：只读面照常（闸门跳过路径不变）", r)
    ok("state_event" not in _ms()._ACTION_SIGS
       and "state_event" not in _ms()._ACTION_DEFAULT,
       "F9 state_event 无 action 面（_ACTION_SIGS/_ACTION_DEFAULT 未动）",
       (sorted(_ms()._ACTION_SIGS), sorted(_ms()._ACTION_DEFAULT)))


_GROUPS = (gA, gB, gC, gD, gE, gF)


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
#   M1 权限映射回退（require_op(op)，state_event 失去 write 词映射）→ B1/B3 红
#   M2 actor 改取请求参数（防伪造失效）→ C1/C2/C3 红
#   M3 kind 不归一（空串直传，append 对空串抛 ValueError）→ D2/D3 红
#   M4 删写闸 require_write（can_write=False 不再拦）→ B6/B7 红
_MUTATIONS = (
    ("权限映射回退（state_event 不再映射到 write 词）", "md_cg/mcp_server.py",
     (('        _p.require_op("write" if op == "state_event" else op)',
       '        _p.require_op(op)'),)),
    ("actor 改取请求参数（防伪造失效）", "md_cg/mcp_server.py",
     (('        from . import state_events as _se\n'
       '        _actor = _p.actor if _p is not None else "system"',
       '        from . import state_events as _se\n'
       '        _actor = a.get("actor") or (_p.actor if _p is not None else "system")'),)),
    ("kind 不归一（空串直传）", "md_cg/mcp_server.py",
     (('                         kind=(a.get("kind") or "").strip() or None,',
       '                         kind=a.get("kind"),'),)),
    ("删写闸 require_write（can_write 不再拦）", "md_cg/mcp_server.py",
     (('        if _p is not None:\n            _p.require_write("internal")\n',
       '        if False:\n            _p.require_write("internal")\n'),)),
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
            print("  %-40s [%s]" % (name, rel))
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
        try:
            globals()["MS"] = _exec_module("md_cg._ms_mut", rel, mut_src)
            with contextlib.redirect_stdout(buf := io.StringIO()):
                reds = _run_groups()
            detail = buf.getvalue()
        finally:
            globals()["MS"] = _REAL_MS
        reds_lines = [l for l in detail.splitlines()
                      if l.strip().startswith("FAIL ")]
        verdict = "红" if reds else "**仍全绿 = 该判据空转**"
        print("  %s %-40s 红项=%d  %s"
              % ("OK    " if reds else "MISS  ", name, reds, verdict))
        for l in reds_lines[:6]:
            print("        " + l.strip()[5:])
        if not reds:
            bad.append(name)
    # 恢复证明：全部轮次结束后把真模块放回，重跑一次基线并须全绿。
    with contextlib.redirect_stdout(buf1 := io.StringIO()):
        restored = _run_groups()
    print("  恢复后基线（真模块）：失败=%d（必须为 0）" % restored)
    if restored:
        bad.append("恢复后基线失败")
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
        print("\n状态事件记账写口守卫：%d 通过 / %d 失败" % (len(_PASS), n))
        print("SUMMARY: md_cg.test_state_event_op 通过=%d 失败=%d"
              % (len(_PASS), n))
        return 0 if not n else 1
    finally:
        _restore_env()
        shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
