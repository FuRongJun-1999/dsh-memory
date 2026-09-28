# -*- coding: utf-8 -*-
"""md_cg · 写面绕层闸族守卫（N197 + N208，按指令同批计一个席位）

缺陷（修复前，本守卫红态实跑）：两条写面都**直调 `cg._write_node`**，既无
`principal.require_layer_write` 亦无 `protect.guard_write`——同一身份对**同层**
的 `add` 被正常 `AccessDenied`，但这两条写面照样落盘（「同一库两条出口口径
不一致」），且不抛错、不落 `_protected_history` 快照、不写
`_protected_audit.jsonl`：

① `md_cg/insight.py:297`（verify 写回）：`_read_event` 后 `cg._write_node(...)`，
   全程零闸。攻击者用 `sustain`（`layers_allow=('self',)`、`can_write=True`、
   ops_allow 含 insight → `_insight_call` 只查 can_write）对**他人留下的
   contextual 层** pending 事件调 `verify(verdict="verified", evidence=[])`
   → 越层改写他人层节点，零证据自证 + 自置不可遗忘保护位
   （`importance` 抬到 0.9、`protected=True`、`protection_reason=insight_verified`、
   盘面 `verification_basis="data"`）。
② `md_cg/ccgc.py:880`（recalibrate 写回，:804 的 link 同款）：唯一准入是**自报
   字符串** `verifier != compiled_by`（:839 `_same_subject`），无层闸、无保护闸
   → `record` 身份（layers_allow 不含 self）可改写 **self 层 immutable 节点**的
   正文与 `condition_space`；且 :189-208 `_upsert_ccg_line` 不过滤换行——
   `slot_corrections={"observation_tool": "工具B\\n# 功能名：注入的新功能名"}`
   会在正文里**注入一行独立的 `# 功能名：…`**（`ccg_field_value` 取首个命中行
   ⇒ 读面被顶替）。

修复（最小改动 · 同族单点，镜像既有 N131 review 队列 merge 面的双闸顺序）：
  ① `protect.guard_overwrite(cg, node_id, ...)`：既有节点覆写前的统一双闸——
     `principal.require_layer_write(节点真层, 敏感度)` 在先（对照
     `MdCGSecure.add`），引擎级 `protect.guard_write` 在后（对照 `MdCG.add`）；
     进入前做索引代际探活（`_maybe_reload_index`，N195 同族：陈旧索引会让两道
     闸同时静默失效）。
  ② `insight.verify` 与 `ccgc.link` / `ccgc.recalibrate` 三个写点前统一过该闸
     （`ccgc` 两处共用同一调用，避免「修一处漏一处」）。
  ③ `ccgc._upsert_ccg_line` 拒收含换行的值（`ValueError`），`compile_dialog`
     与 `recalibrate` 在**更早的边界**以 `E022` 拒绝——fail-closed 且带结构化
     错误码，不静默改写调用方的值。

守卫（六组，全部临时库 + 哑主密钥 + 临时令牌库，**绝不触真实 ~/.mdcg**）：
  ⓿ 隔离自证：aux 根 / 令牌库都须落在守卫临时目录，否则中止；
  ① insight.verify：sustain 越层被拒（盘面零改写）；designer 对 self 层事件节点
     被**保护闸**拒（层闸对其放行，故该腿单独钉住 guard_write）；record/reflect
     同层正当写入仍成功（反向腿，防一刀切收紧）；
  ② ccgc.recalibrate：record 改写 self 层节点被拒（层闸）；designer 对同节点被
     保护闸拒；换行注入被 `E022` 拒且盘面零改写、无伪造行；合法单行修正仍成功；
     直调 `_upsert_ccg_line` 的注入被拒；
  ③ ccgc.link 同款注入面：显式 marks 带换行的候选在编译期即遭 `E022`，link
     apply 拒写；合法单行候选 + 令牌签章仍落库（反向腿）；
  ④ 工具面真身（与缺陷材料同口径）：`mcp_server.call_tool(cg, "cg", …)` 走
     `op=insight action=verify` / `op=ccgc action=recalibrate` 同样被拒；
  ⑤ 源断言 + floor：三处写点前都出现 `guard_overwrite`、`_write_node` 前有闸；
     实弹断言计数下限。

实测（本机）：修前 10 passed / 18 failed（用 HEAD 版 insight.py/ccgc.py/protect.py
覆盖临时包副本后实跑，18 条红腿含 4a/4b 两条工具面端到端）；修后 28 passed /
0 failed（live=20）。

运行：python -X utf8 -m md_cg.test_n197_n208_write_face_gates
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
import time

# ── 隔离前置：必须在 import md_cg 子模块**之前**（tokens/theory 等在模块级把
# aux_root() 冻成常量）——否则会指到真实 ~/.mdcg 并在那里建密钥/令牌库。 ──
_TMP = tempfile.mkdtemp(prefix="n197_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "cd" * 32          # 哑主密钥（绝不触真实密钥面）
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP, "tokens.json")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "cgroot")
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_SESSION",
           "DSH_SESSION_ID", "MDCG_LEGACY_ENV_AUTH", "MDCG_LEGACY_ENV_ADMIN",
           "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_STATE_ROOT",
           "MDCG_DATA_ROOT", "MDCG_TENANT_REGISTRY", "MDCG_VERIFIER_MODULES",
           "PYTHONIOENCODING", "PYTHONUTF8"):
    os.environ.pop(_k, None)

from . import ccgc, insight, mcp_server, nodefile, protect, tokens   # noqa: E402
from .datapath import aux_root                               # noqa: E402
from .mdcos import MdCGOS, MdCGSecure                        # noqa: E402
from .security import Principal                              # noqa: E402

atexit.register(lambda: _cleanup(_TMP))       # LIFO：晚于库层 _atexit_flush_all

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ROOT = os.path.join(_TMP, "cgroot")
PASS = FAIL = LIVE = 0
LIVE_FLOOR = 18
FAILS = []

C1_OK = {"retrievability": 0.8, "outside_observer": True,
         "cross_domain": ["存储", "网络"], "premise_questioned": True,
         "pressure": "low", "continuity_turns": 3, "externalized": True,
         "tone": "curious"}
SLOTS = {"observation_position": "本地磁盘",
         "time_window": [0, 253402300799],
         "observation_tool": "扩展名映射表",
         "existence_constraint": "仅对本地可读文件生效"}
INJECT = "工具B\n# 功能名：注入的新功能名"           # 换行注入探针


def check(name, cond, detail="", live=False):
    global PASS, FAIL, LIVE
    if live:
        LIVE += 1
    if cond:
        PASS += 1
        print("  [PASS] %s" % name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s · %s" % (name, detail))


def _princ(role, clearance="internal", can_admin=False):
    spec = tokens.role_spec(role)
    return Principal(tenant="default", actor="n197-" + role,
                     clearance=clearance, can_write=bool(spec["can_write"]),
                     can_admin=can_admin, role=role,
                     layers_allow=spec["layers_allow"],
                     ops_allow=spec["ops_allow"], auth_mode="test")


_OPEN = []


def _secured(principal):
    cg = MdCGSecure(ROOT, principal=principal)
    _OPEN.append(cg)
    return cg


def _close_all():
    for cg in _OPEN:
        try:
            cg.close()
        except Exception:                      # noqa: BLE001 —— 清理面不得再抛
            pass


def _cleanup(path) -> bool:
    import gc
    for _ in range(6):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return True
        gc.collect()
        time.sleep(0.25)
    return not os.path.exists(path)


def _fm_of(cg, nid):
    node = cg.get(nid)
    return (node or {}).get("frontmatter") or {}, (node or {}).get("content") or ""


def _raises(fn, *a, **kw):
    """执行并返回 (ok, 异常类名/空, 结果/异常文本)。"""
    try:
        return True, "", fn(*a, **kw)
    except Exception as exc:                   # noqa: BLE001 —— 守卫要的是拒绝形态
        return False, type(exc).__name__, str(exc)


def _snapshot_state(cg, nid):
    """(frontmatter 关键位, 正文) —— 用于「盘面零改写」断言。"""
    fm, content = _fm_of(cg, nid)
    return ({k: fm.get(k) for k in ("insight_state", "protected",
                                    "protection_reason", "importance",
                                    "verification_basis", "condition_space")},
            content)


def _src_window(src, start, end):
    i = src.find(start)
    if i < 0:
        return ""
    j = src.find(end, i)
    return src[i:] if j < 0 else src[i:j]


def _not_raises_but_no_forged_line():
    """直调 _upsert_ccg_line：换行值必须被拒（抛异常）或至少不产生独立注入行。"""
    try:
        out = ccgc._upsert_ccg_line("# 正文\n", "生效条件", INJECT)
    except ValueError:
        return True
    return not [ln for ln in out.split("\n") if ln.strip().startswith("# 功能名")]


def main():
    global LIVE
    # ---------- ⓿ 隔离自证 ----------
    print("[0] 隔离自证")
    _tok = tokens.token_file()
    check("0a 默认令牌库与 aux 根都落在守卫临时目录（绝不触真实凭据）",
          os.path.abspath(_tok).lower().startswith(os.path.abspath(_TMP).lower())
          and os.path.abspath(aux_root()).lower().startswith(
              os.path.abspath(_TMP).lower()),
          "tok=%s aux=%s" % (_tok, aux_root()))
    if not os.path.abspath(ROOT).lower().startswith(os.path.abspath(_TMP).lower()):
        print("FATAL: 隔离失败，中止（绝不带病跑真实库）")
        return 2

    # ---------- 夹具：contextual 洞见事件 ×2 + self 层事件 + 两节点 ----------
    designer = _secured(_princ("designer", clearance="secret", can_admin=True))
    ev = designer.insight(action="record", statement="N197 探针事件：零证据自证（甲链路）",
                          conditions=C1_OK)
    ev_id = ev["node_id"]
    ev2 = designer.insight(action="record",
                           statement="缓存分层应保持离线可运行：跨域证据待补（乙链路）",
                           conditions=C1_OK)
    ev2_id = ev2["node_id"]
    ev3 = designer.insight(action="record",
                           statement="离线优先的网络探测策略（丙链路·工具面探针）",
                           conditions=C1_OK)
    ev3_id = ev3["node_id"]
    # self 层事件节点（层闸对 designer 放行 → 单独钉住保护闸）
    self_ev = designer.add(
        "selfevent", "# 事件正文：self 层洞见事件\n",
        layer="self", tags=[insight.TAG_EVENT], insight_state="pending")
    check("0b 夹具就位（三个 contextual 事件 + self 层事件；层位可查）",
          bool(ev_id) and bool(ev2_id) and bool(ev3_id) and bool(self_ev)
          and len({ev_id, ev2_id, ev3_id}) == 3
          and all((designer.index["nodes"].get(x) or {}).get("layer") == "contextual"
                  for x in (ev_id, ev2_id, ev3_id))
          and (designer.index["nodes"].get(self_ev) or {}).get("layer") == "self")
    # knowledge 层节点：无 `# 功能名` 行（注入行会成为**首个**功能名行 → 读面顶替）
    knode = designer.add("kn", "# 正文：知识节点占位。\n", layer="knowledge",
                         condition_space=SLOTS)
    snode = designer.add("selfcard", "# 正文：自我状态卡占位。\n", layer="self",
                         condition_space=SLOTS, importance=0.9)

    # ---------- ① insight.verify：越层 / 保护闸 ----------
    print("[1] insight.verify：既得写面（越层腿 + 保护腿 + 反向腿）")
    sustain = _secured(_princ("sustain"))
    t0 = time.time()
    ok, exc_name, out = _raises(sustain.insight, action="verify",
                                node_id=ev_id, verdict="verified")
    check("1a sustain（layers=('self',)）越层 verify 被拒（修前 = 越层改写成功）",
          (not ok) and exc_name == "AccessDenied",
          "exc=%s out=%s" % (exc_name, str(out)[:80]), live=True)
    fm1, c1 = _fm_of(sustain, ev_id)
    check("1b 被拒后盘面零改写（仍 pending、未自授保护位/0.9/基底 data）",
          fm1.get("insight_state") == "pending" and not fm1.get("protected")
          and float(fm1.get("importance") or 0) < 0.9
          and fm1.get("verification_basis") != "data",
          "state=%s protected=%s imp=%s basis=%s"
          % (fm1.get("insight_state"), fm1.get("protected"),
             fm1.get("importance"), fm1.get("verification_basis")), live=True)
    check("1c 被拒路径不留伪造快照/审计（_protected_history 无该节点、审计无该条）",
          not os.path.exists(os.path.join(ROOT, protect.HISTORY_DIR, ev_id)),
          "history=%s" % protect.history(sustain, ev_id))

    ok, exc_name, out = _raises(designer.insight, action="verify",
                                node_id=self_ev, verdict="verified")
    check("1d designer（layers=('*',) 层闸放行）对 self 层事件覆写仍被保护闸拒"
          "（修前 = 无痕覆写 self 层节点）",
          (not ok) and exc_name in ("ProtectionError", "PermissionError"),
          "exc=%s out=%s" % (exc_name, str(out)[:80]), live=True)
    _, self_ev_content = _fm_of(designer, self_ev)
    check("1e self 层节点正文未被无痕覆写（保护闸拒绝无副作用）",
          self_ev_content == "# 事件正文：self 层洞见事件\n",
          repr(self_ev_content[:60]), live=True)

    rec = _secured(_princ("record"))
    ok_r, exc_r, out_r = _raises(rec.insight, action="verify", node_id=ev_id,
                                 verdict="verified",
                                 evidence=[{"type": "v3", "ref": "外部确证-1"}])
    fm_r, _c = _fm_of(rec, ev_id)
    check("1f 反向腿：record（layers 含 contextual）同层正当 verify 仍成功",
          ok_r and out_r.get("state") == "verified"
          and float(out_r.get("importance") or 0) >= 0.9,
          "ok=%s exc=%s out=%s" % (ok_r, exc_r, str(out_r)[:80]), live=True)
    check("1g 反向腿落盘：verified 后基底升 data 且带 verified 标签",
          fm_r.get("verification_basis") == "data"
          and insight.TAG_VERIFIED in (fm_r.get("tags") or []),
          "basis=%s tags=%s" % (fm_r.get("verification_basis"),
                                fm_r.get("tags")), live=True)
    reflect = _secured(_princ("reflect"))
    ok_rf, exc_rf, out_rf = _raises(reflect.insight, action="verify",
                                    node_id=ev2_id, v_types=["v3"])
    check("1h 反向腿：reflect（layers=('contextual',)）同层 verify 仍成功",
          ok_rf and getattr(out_rf, "get", lambda *a: None)("state") == "verified",
          "exc=%s out=%s" % (exc_rf, str(out_rf)[:80]), live=True)

    # ---------- ② ccgc.recalibrate ----------
    print("[2] ccgc.recalibrate：层闸 / 保护闸 / 换行注入 / 反向腿")
    before_k = _snapshot_state(designer, knode)
    ok2, exc2, out2 = _raises(ccgc.recalibrate, snode,
                              {"observation_tool": "工具B"}, "reviewer-B",
                              "agent-A", cg=rec, apply=True)
    check("2a record 身份改写 self 层节点被层闸拒（修前 ok=True written=1）",
          (not ok2) and exc2 == "AccessDenied",
          "exc=%s out=%s" % (exc2, str(out2)[:80]), live=True)
    fm_s, c_s = _fm_of(rec, snode)
    check("2b 被拒后 self 层节点正文与 condition_space 零改写",
          c_s == "# 正文：自我状态卡占位。\n"
          and fm_s.get("condition_space") == SLOTS,
          "content=%r slots=%s" % (c_s[:40], fm_s.get("condition_space")), live=True)

    ok3, exc3, out3 = _raises(ccgc.recalibrate, snode,
                              {"observation_tool": "工具B"}, "reviewer-B",
                              "agent-A", cg=designer, apply=True)
    check("2c designer（层闸放行）改写 self 层 immutable 节点被保护闸拒"
          "（修前 = 无痕覆写不可篡改层）",
          (not ok3) and exc3 in ("ProtectionError", "PermissionError"),
          "exc=%s out=%s" % (exc3, str(out3)[:80]), live=True)

    ok4, exc4, out4 = _raises(ccgc.recalibrate, knode,
                              {"observation_tool": INJECT}, "reviewer-B",
                              "agent-A", cg=rec, apply=True)
    fm_k, c_k = _fm_of(rec, knode)
    forged = [ln for ln in c_k.split("\n") if ln.strip().startswith("# 功能名")]
    check("2d 换行注入被拒（E022；修前 = 注入行落盘）",
          (not ok4 and "E022" in str(out4))
          or (ok4 and getattr(out4, "ok", False) is False
              and any("E022" in e for e in (getattr(out4, "errors", None) or []))),
          "exc=%s out=%s" % (exc4, str(out4)[:100]), live=True)
    check("2e 注入被拒后盘面零改写、无伪造 `# 功能名` 独立行",
          not forged and fm_k.get("condition_space") == SLOTS
          and c_k == before_k[1],
          "forged=%s slots=%s" % (forged, fm_k.get("condition_space")), live=True)
    check("2f 读面未被顶替：ccg_field_value 未取到注入值",
          "注入的新功能名" not in str(nodefile.ccg_field_value(c_k, "功能名")),
          "got=%r" % nodefile.ccg_field_value(c_k, "功能名"), live=True)
    ok5, exc5, out5 = _raises(ccgc.recalibrate, knode,
                              {"observation_tool": "改用扩展名映射表路由"},
                              "reviewer-B", "agent-A", cg=rec, apply=True)
    fm_k2, c_k2 = _fm_of(rec, knode)
    check("2g 反向腿：合法单行四槽修正仍落盘（written=1 + 正文生效条件行更新）",
          ok5 and getattr(out5, "ok", False) and getattr(out5, "written", 0) == 1
          and fm_k2.get("condition_space", {}).get("observation_tool")
          == "改用扩展名映射表路由",
          "exc=%s out=%s" % (exc5, str(getattr(out5, "errors", ""))[:80]), live=True)
    check("2h 直调 _upsert_ccg_line 的换行值被拒（同族单点，非仅调用方自觉）",
          _not_raises_but_no_forged_line(), "见 _not_raises_but_no_forged_line",
          live=True)

    # ---------- ③ ccgc.link 同款注入面 ----------
    print("[3] ccgc.link：同款注入面 + 反向腿")
    tk = tokens.issue("verify", actor="n197-reviewer", path=tokens.token_file())
    comp_bad = ccgc.compile_dialog(
        "探针对话：使用扩展名映射表进行路由。", knode, "n197-record",
        marks={"功能名": "探针对话\n# 功能名：注入的新功能名"},
        slots=dict(SLOTS), cg=rec, strict_spans=False)
    check("3a 含换行的候选在**编译期**即遭 E022（阻断点前移到候选入口）",
          not comp_bad.success
          and any("E022" in e for e in comp_bad.errors),
          str(comp_bad.errors)[:120], live=True)
    at = ccgc.attest(knode, ccgc.ACCEPT, "n197-reviewer", "n197-record", cg=rec,
                     verifier_token=tk["token"])
    lk_bad = ccgc.link(comp_bad, at, cg=rec, apply=True)
    fm_l, c_l = _fm_of(rec, knode)
    check("3b 编译不通过 → link 拒写、盘面无伪造行",
          (not lk_bad.ok) and c_l == c_k2
          and not [ln for ln in c_l.split("\n")
                   if ln.strip().startswith("# 功能名")],
          "errs=%s" % str(lk_bad.errors)[:100], live=True)
    comp_ok = ccgc.compile_dialog(
        "探针对话：使用扩展名映射表进行路由。", knode, "n197-record",
        marks={"功能名": "探针功能名", "子功能": "编译复核"},
        slots=dict(SLOTS), cg=rec, strict_spans=False)
    at_ok = ccgc.attest(knode, ccgc.ACCEPT, "n197-reviewer", "n197-record",
                        cg=rec, verifier_token=tk["token"])
    lk_ok = ccgc.link(comp_ok, at_ok, cg=rec, apply=True)
    fm_l2, c_l2 = _fm_of(rec, knode)
    check("3c 反向腿：合法候选 + 令牌签章仍落库（link ok，六要素行写入）",
          lk_ok.ok and getattr(lk_ok, "written", 0) >= 1
          and "# 功能名：探针功能名" in c_l2,
          "ok=%s errs=%s" % (lk_ok.ok, str(lk_ok.errors)[:80]), live=True)

    # ---------- ④ 工具面真身 ----------
    print("[4] 工具面真身（mcp_server.call_tool）：与缺陷材料同口径")
    ok6, exc6, out6 = _raises(mcp_server.call_tool, sustain, "cg",
                              {"op": "insight", "action": "verify",
                               "node_id": ev3_id, "verdict": "verified"})
    fm6, c6 = _fm_of(sustain, ev3_id)
    check("4a call_tool(op=insight, action=verify) 越层 leg 走真身同样被拒"
          "（材料口径：sustain 对他人 contextual 事件零证据自证）",
          (not ok6) and exc6 == "AccessDenied"
          and fm6.get("insight_state") == "pending"
          and not fm6.get("protected"),
          "exc=%s state=%s protected=%s"
          % (exc6, fm6.get("insight_state"), fm6.get("protected")), live=True)
    ok7, exc7, out7 = _raises(mcp_server.call_tool, rec, "cg",
                              {"op": "ccg", "action": "recalibrate",
                               "ccg": {"node_id": snode, "apply": True,
                                       "slot_corrections": {"observation_tool":
                                                            "工具B"},
                                       "verifier": "reviewer-B",
                                       "compiled_by": "agent-A"}})
    fm_s4, c_s4 = _fm_of(rec, snode)
    check("4b call_tool(op=ccg, action=recalibrate) 越层被拒且盘面零改写",
          (not ok7) and exc7 == "AccessDenied" and c_s4 == c_s,
          "exc=%s out=%s content=%r" % (exc7, str(out7)[:60], c_s4[:40]), live=True)

    # ---------- ⑤ 源断言 + floor ----------
    print("[5] 源断言 + 守卫自检")
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "insight.py"), encoding="utf-8", errors="replace") as fh:
        src_i = fh.read()
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "ccgc.py"), encoding="utf-8", errors="replace") as fh:
        src_c = fh.read()
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "protect.py"), encoding="utf-8", errors="replace") as fh:
        src_p = fh.read()
    win_i = _src_window(src_i, "def verify(cg, node_id=None, evidence=None",
                        "# ---------------------------------------------------------------")
    check("5a insight.verify 写点前紧邻 guard_overwrite（注释里的 `_write_node` "
          "字样不作数：断言代码形态相邻），且层/敏感度取节点 fm 真值",
          "protect.guard_overwrite(cg, node_id, layer=fm.get(\"layer\"),\n"
          "                            sensitivity=fm.get(\"sensitivity\"), "
          "actor=actor)\n    cg._write_node(node_id,"
          in src_i.replace("\r\n", "\n"),
          "win_len=%d" % len(win_i))
    check("5b ccgc.link 与 recalibrate 两个写点前各自紧邻 guard_overwrite"
          "（层/敏感度各取本节点 fm 真值）",
          src_c.count("protect.guard_overwrite(") == 2
          and ("protect.guard_overwrite(_cg, node_id, layer=fm.get(\"layer\"),"
               in src_c.replace("\r\n", "\n"))
          and ("protect.guard_overwrite(_cg, out.node_id, layer=fm.get(\"layer\"),"
               in src_c.replace("\r\n", "\n"))
          and ("actor=actor or compiled.actor)\n    _cg._write_node(node_id,"
               in src_c.replace("\r\n", "\n"))
          and ("actor=verifier)\n    _cg._write_node(out.node_id,"
               in src_c.replace("\r\n", "\n")),
          "count=%d" % src_c.count("protect.guard_overwrite("))
    _gw = _src_window(src_p, "def guard_overwrite", "\n\n# ")
    _rl = _src_window(src_p, "def require_layer(cg, node_id", "\n\n# ")
    _rt = _src_window(src_p, "def _resolve_target", "\n\n# ")
    check("5c protect.guard_overwrite 单点内层闸 + 保护闸 + 代际探活齐备"
          "（N209 起解析与层闸收敛到 require_layer/_resolve_target 同一单点，"
          "故三要素分别钉在调用方与被调用方）",
          "def guard_overwrite" in src_p
          and "require_layer(cg, node_id" in _gw and "guard_write(" in _gw
          and "require_layer_write" in _rl and "_maybe_reload_index" in _rt,
          "gw_len=%d rl_len=%d rt_len=%d" % (len(_gw), len(_rl), len(_rt)))
    check("5d ccgc 换行闸：_upsert_ccg_line 拒收 + 编译期/recalibrate 边界 E022",
          "E022" in src_c and "含换行" in src_c
          and "换行" in _src_window(src_c, "def _upsert_ccg_line",
                                    "def _append_jsonl"),
          "E022=%d" % src_c.count("E022"))
    check("5e 实弹断言数 ≥ %d（防 spawn/扫描面失效假绿）" % LIVE_FLOOR,
          LIVE >= LIVE_FLOOR, "LIVE=%d" % LIVE)

    print("\n=== N197/N208 write-face gates: %d passed, %d failed (live=%d) ==="
          % (PASS, FAIL, LIVE))
    if FAILS:
        print("失败项：%s" % "；".join(FAILS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    _code = 0
    try:
        _code = main()
    finally:
        _close_all()
        if not _cleanup(_TMP):
            print("WARN: 临时根残留未清（%s）——请人工清理" % _TMP)
    sys.exit(_code)
