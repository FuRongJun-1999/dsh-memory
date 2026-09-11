# -*- coding: utf-8 -*-
"""md_cg · 第 45 篇：嵌套身份归因与会话切片（(harness, session) 不参与授权）

设计口径（设计者，2026-09-11）：
  · 唯一设计者 = 外部用户；被授权端 codebuddy / dsh / zcode 是本机三个进程，
    权限域一致（同一最高权限），区别只在单元分工（工程内容）；
  · 身份靠 (harness, session) 归因，而不是靠多令牌/多实例提权；
  · 会话产物落薄卡（单例）的 session 维度切片 + 富索引指针，卡本身仍是单例。

覆盖：
  A Principal 归因字段（harness/unit/session；与授权正交）
  B _normalize_session：DSH 形态 + 目录存在 → 采用；不存在 → anonymous；
    非 DSH 形态 → 采用；根可配置（MDCG_DSH_SESSIONS_ROOT）
  C _apply_attribution：MDCG_SESSION / DSH_SESSION_ID / MDCG_HARNESS / MDCG_UNIT
  D self_state 会话切片：refresh(session=) 登记维度 / summary(session=) 回报 /
    单例卡语义不变 / 不覆盖显式维度
  E 会话要点：session_note 缺省用 Principal.session；recall 带回会话自我切片
  F 审计归因：_audit.jsonl 条目带 harness/unit
  G MCP 入口：_self_state_call 缺省会话透传 + index 快捷反查

运行：python -m md_cg.test_p45_session_identity
"""
from __future__ import annotations

import json
import os
import tempfile

from .mdcos import MdCGOS, MdCGSecure
from .security import Principal
from . import self_state as ss
from . import mcp_server as ms

PASS = FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def _setenv(**kw):
    old = {k: os.environ.get(k) for k in kw}
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return old


def _restore(old):
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def main():
    # ---------- A. Principal 归因字段 ----------
    print("\n[A] Principal 归因字段（与授权正交）")
    p0 = Principal(actor="a0")
    check("A1 默认会话是进程随机 id", (p0.session or "").startswith("sess_"),
          p0.session)
    check("A2 harness/unit 默认为 None", p0.harness is None and p0.unit is None)
    p1 = Principal(actor="a1", session="session-x", harness="dsh", unit="record",
                   ops_allow=("read",))
    d = p1.as_dict()
    check("A3 as_dict 暴露 harness/unit/session",
          d.get("harness") == "dsh" and d.get("unit") == "record"
          and d.get("session") == "session-x")
    check("A4 归因不影响授权（ops 仍按记录）",
          p1.allows_op("read") and not p1.allows_op("write"))

    # ---------- B. _normalize_session ----------
    print("\n[B] 会话 id 归一与轻校验")
    sdir = tempfile.mkdtemp(prefix="mdcg_p45_sess_")
    # 人造 id：不得使用任何真实 DSH 会话 id，否则断言会依赖运行机器的磁盘现状
    # （若该 id 恰好在 ~/.dsh/sessions 下存在，B5 的 fail-soft 断言会被偶然满足）。
    sid = "session-deadbeef-6abc-4a71-a1f2-b658712be0fb"
    os.makedirs(os.path.join(sdir, "--ws--", sid))
    # 形态自检：id 若不满足 DSH 五段形态，B1/B5 会退化成「非 DSH 形态原样采用」
    # 而仍然通过——断言落空且看不出来，故先钉死前提。
    check("B0 测试用 id 满足 DSH 形态（防断言落空）", ms._is_dsh_session(sid))
    old = _setenv(MDCG_DSH_SESSIONS_ROOT=sdir)
    try:
        check("B1 DSH 形态 + 目录存在 → 采用",
              ms._normalize_session(sid) == sid)
        check("B2 DSH 形态 + 目录不存在 → anonymous",
              ms._normalize_session(
                  "session-00000000-0000-0000-0000-000000000000") == "anonymous")
        check("B3 非 DSH 形态 → 原样采用",
              ms._normalize_session("dsl-web-main") == "dsl-web-main")
        check("B4 空值 → anonymous", ms._normalize_session("") == "anonymous")
    finally:
        _restore(old)
    # 必须显式指向「不存在的根」：若沿用默认根，在装了 DSH 的机器上根目录存在，
    # 会落到「根可读但无该会话 → anonymous」分支，测不到 fail-soft（易假 PASS）。
    old = _setenv(MDCG_DSH_SESSIONS_ROOT=os.path.join(sdir, "_no_such_root_"))
    try:
        check("B5 根不存在/不可读 → fail-soft（保留标记，不丢会话）",
              ms._normalize_session(sid) == sid, "根不存在时不因环境差异丢弃会话标记")
    finally:
        _restore(old)

    # ---------- C. _apply_attribution ----------
    print("\n[C] 归因注入（MDCG_SESSION / DSH_SESSION_ID / HARNESS / UNIT）")
    old = _setenv(MDCG_SESSION="dsl-web-main", DSH_SESSION_ID=None,
                  MDCG_HARNESS="dsh", MDCG_UNIT="record")
    try:
        p = Principal(actor="a2")
        ms._apply_attribution(p)
        check("C1 MDCG_SESSION 优先", p.session == "dsl-web-main", p.session)
        check("C2 harness/unit 注入",
              p.harness == "dsh" and p.unit == "record")
        # 原实现此处复述了 C1（测的仍是 MDCG_SESSION），未覆盖「后备不越权覆盖」。
        old_dsh = _setenv(DSH_SESSION_ID="session-abc")
        try:
            pm = Principal(actor="a2b")
            ms._apply_attribution(pm)
            check("C3 两者并存时 MDCG_SESSION 优先（后备不覆盖）",
                  pm.session == "dsl-web-main", pm.session)
        finally:
            _restore(old_dsh)
    finally:
        _restore(old)
    old = _setenv(MDCG_SESSION=None, DSH_SESSION_ID="session-abc",
                  MDCG_HARNESS=None, MDCG_UNIT=None)
    try:
        p = Principal(actor="a3")
        ms._apply_attribution(p)
        check("C4 无 MDCG_SESSION 时用 DSH_SESSION_ID",
              p.session == "session-abc", p.session)
        check("C5 无归因环境时保留进程随机 id",
              (p := Principal()).session.startswith("sess_"))
    finally:
        _restore(old)

    # ---------- D. self_state 会话切片 ----------
    print("\n[D] 薄卡 + 会话维度切片（单例语义不变）")
    root = tempfile.mkdtemp(prefix="mdcg_p45_")
    SESS = ms._normalize_session("dsl-web-main")
    cg = MdCGSecure(root, principal=Principal(
        actor="dsh", session=SESS, harness="dsh", unit="record"))
    r = cg.self_state_refresh(ss.DEFAULT_SUBJECT)
    check("D1 refresh 缺省带会话维度",
          bool(r.get("ok")) and SESS in (
              (r.get("state") or {}).get("dimensions") or {}).get("session", []),
          str(r.get("changed")))
    card = cg.self_state_snapshot(ss.DEFAULT_SUBJECT)
    check("D2 单例卡 id 未因会话改变",
          card.get("node_id") == ss.state_node_id(ss.DEFAULT_SUBJECT))
    summ = cg.self_state_summary(ss.DEFAULT_SUBJECT, session=SESS)
    check("D3 summary 回报本会话已登记",
          summ.get("session_registered") is True and summ.get("session") == SESS)
    other = cg.self_state_summary(ss.DEFAULT_SUBJECT, session="session-other")
    check("D4 其它会话未登记且指针为空",
          other.get("session_registered") is False
          and (other.get("session_refs") or {}).get("count") == 0)
    r2 = cg.self_state_refresh(ss.DEFAULT_SUBJECT,
                               dimensions={"session": ["manual-x"]})
    dims = ((r2.get("state") or {}).get("dimensions") or {}).get("session", [])
    check("D5 会话并入而不覆盖显式维度",
          "manual-x" in dims and SESS in dims, str(dims))
    check("D6 窄刷新仍以单例卡为准（同 subject 一张卡）",
          cg.self_state_snapshot(ss.DEFAULT_SUBJECT).get("node_id")
          == ss.state_node_id(ss.DEFAULT_SUBJECT))

    # ---------- E. 会话要点 ----------
    print("\n[E] 会话要点：缺省会话 = Principal.session")
    n = cg.session_note("P45 会话要点：嵌套身份归因联调")
    check("E1 session_note 缺省采用进程会话", n.get("session") == SESS,
          str(n.get("session")))
    rec = cg.session_recall(session=SESS, include_state=True)
    check("E2 recall 命中本会话要点",
          any(x.get("id") == n.get("id") for x in rec.get("notes") or []))
    check("E3 recall 的自我状态带会话切片",
          (rec.get("self_state") or {}).get("session") == SESS)

    # ---------- F. 审计归因 ----------
    print("\n[F] 审计归因（harness/unit 只入审计）")
    with open(os.path.join(root, "_audit.jsonl"), encoding="utf-8") as f:
        rows = [json.loads(x) for x in f if x.strip()]
    last = rows[-1] if rows else {}
    check("F1 审计条目带 harness", last.get("harness") == "dsh", str(last.get("op")))
    check("F2 审计条目带 unit", last.get("unit") == "record")
    check("F3 审计条目带会话", bool(last.get("session")))

    # ---------- G. MCP 入口 ----------
    print("\n[G] MCP 分发：会话缺省透传")
    out = ms._self_state_call(cg, {"action": "summary"})
    check("G1 summary 缺省取 Principal 会话",
          out.get("session") == SESS and out.get("session_registered") is True)
    idx = ms._self_state_call(cg, {"action": "index"})
    check("G2 index 不传 dim → 按当前会话反查",
          idx.get("dimension") == "session" and idx.get("value") == SESS,
          str(idx.get("count")))
    out2 = ms._self_state_call(cg, {"action": "refresh"})
    check("G3 refresh 经 MCP 缺省登记会话",
          bool(out2.get("ok")))

    print("\n" + "=" * 68)
    print(f"通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 68)
    return FAIL


if __name__ == "__main__":
    import sys
    sys.exit(1 if main() else 0)