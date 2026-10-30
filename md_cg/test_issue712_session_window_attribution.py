# -*- coding: utf-8 -*-
# 功能名：#712 会话窗口四要素组装 + 分档会话隔离（方案 C）守卫
# 生效条件：python -X utf8 -m md_cg.test_issue712_session_window_attribution；被测面＝remember_event 的 id / recent_events 派生 / session_recall 的取窗顺序与四要素 / Principal.sessions_read
# 子功能：①事件有稳定键且确定性派生 ②注入面 recent 条目含 session/sensitivity/actor/id 四要素 ③**取窗顺序**：按会话收窄时先取全量再过滤再截（修前会得到空窗口）④falsy 会话进 degraded 不再静默 ⑤sessions_read 仅集合生效、can_admin 不被削弱
# 执行：临时库造两会话交错事件，按窗口小于本会话消息数的条件断言不空；再验四要素与权限分档
# 验证方式：全部 PASS exit 0；每条守卫都能独立变红（见各 ok() 的失败面）
# 不适用条件：不判 hooks.ts 的渲染格式（本批未改渲染）；不判 MCP 序列化；不判 DSH 宿主是否转发 stderr
"""#712：会话窗口消息组装（会话·时间·身份·id）+ 分档会话隔离。

病灶（取证见 PR #712 审查）：
  ① 事件无 id，模型无法引用「哪一条」；
  ② 注入面条目只留 role/text/t ⇒ 模型不知道「哪个会话说的、私有还是共有、谁说的」；
  ③ **取窗顺序 bug**：先截末 N 条再按会话过滤 ⇒ 多会话并发时本会话消息被挤出窗口，
     session="A" 可能拿到**空 recent**（false-negative，极难被发现）；
  ④ session 为 falsy 时静默退回全局窗口，无任何留痕。
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_PASS, _FAIL = [], []


def ok(cond, msg, detail=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg + (("  <- " + str(detail)) if detail and not cond else ""))


def main():
    T = tempfile.mkdtemp(prefix="i712g_")
    try:
        for k in list(os.environ):
            if k.startswith("MDCG_"):
                del os.environ[k]
        os.environ.update(MDCG_ROOT=os.path.join(T, "brain"),
                          MDCG_STATE_ROOT=os.path.join(T, "stroot"),
                          MDCG_AUX_ROOT=os.path.join(T, "auxroot"),
                          MDCG_DATA_ROOT=os.path.join(T, "dataroot"),
                          MDCG_EXPORT_ROOT=T, MDCG_SUSTAIN="0", MDCG_SLEEP="0")
        from md_cg.mdcos import MdCGSecure
        from md_cg.security import Principal
        from md_cg.tokens import role_spec

        sg = role_spec("designer")
        p = Principal(role="designer", clearance="secret", can_write=sg["can_write"],
                      can_admin=sg["can_admin"], layers_allow=sg["layers_allow"],
                      ops_allow=sg["ops_allow"], session="sessX")
        cg = MdCGSecure(os.path.join(T, "brain"), principal=p, autoflush=1)

        print("== A 事件稳定键")
        r1 = cg.remember_event("user", "hello A", meta={"session": "sessA"})
        ev = r1.get("event") or {}
        ok(bool(ev.get("id")), "A1 事件带 id", ev.get("id"))
        ok(str(ev.get("id") or "").startswith("re_"), "A2 id 形如 re_<ms>_<hex>", ev.get("id"))
        ok("actor" in (ev.get("meta") or {}), "A3 meta.actor 键存在（值为 None 亦可）", ev.get("meta"))
        ok("actor" not in ev, "A4 **不加**顶层 actor 键（顶层形状不被动）", list(ev)[:8])
        # 确定性：同 t 同 text 派生同 id
        from md_cg.mdcg import _event_suffix
        ok(_event_suffix("abc") == _event_suffix("abc"), "A5 后缀确定性（同一 text 恒同串）")

        print("== B 取窗顺序（本批核心）")
        # 造交错事件：A 3 条、B 5 条，交替；窗口 recent_limit=3
        cg.remember_event("user", "A-1", meta={"session": "sessA"})
        for i in range(5):
            cg.remember_event("user", "B-%d" % i, meta={"session": "sessB"})
        cg.remember_event("user", "A-2", meta={"session": "sessA"})
        cg.remember_event("user", "A-3", meta={"session": "sessA"})
        pack = cg.session_recall("sessA", limit=1, recent_limit=3)
        rec = pack.get("recent") or []
        ok(len(rec) > 0,
           "B1 session=sessA 且 A 的消息数(3) >= 窗口(3) 时**不空**（修前：先截后滤 ⇒ 可能空）",
           len(rec))
        ok(all((x.get("session") == "sessA") for x in rec),
           "B2 窗口里**只有** sessA 的条目（无跨会话泄漏）",
           [x.get("session") for x in rec][:5])
        # 更极端：A 只有 1 条，且被大量 B 消息夹在中间
        cg2 = MdCGSecure(os.path.join(T, "brain2"), principal=p, autoflush=1)
        for i in range(20):
            cg2.remember_event("user", "Bx-%d" % i, meta={"session": "sessB2"})
        cg2.remember_event("user", "A-only", meta={"session": "sessA2"})
        for i in range(20):
            cg2.remember_event("user", "By-%d" % i, meta={"session": "sessB2"})
        pack2 = cg2.session_recall("sessA2", limit=1, recent_limit=3)
        rec2 = pack2.get("recent") or []
        ok(len(rec2) == 1 and (rec2[0].get("text") or "").startswith("A-only"),
           "B3 **A 仅 1 条且被 40 条 B 夹住**时仍能取到（修前必空——这是核心回归）",
           [(x.get("session"), (x.get("text") or "")[:8]) for x in rec2][:4])
        cg2.close()

        print("== C 四要素齐备")
        ok(rec, "C0 有条目可查", len(rec))
        if rec:
            keys = set(rec[0].keys())
            ok({"role", "text", "t", "id", "session", "sensitivity", "actor"} <= keys,
               "C1 条目含 role/text/t/id/session/sensitivity/actor", sorted(keys))
            ok(rec[0].get("session") == "sessA", "C2 session 取值正确", rec[0].get("session"))

        print("== D falsy 会话留痕")
        pack3 = cg.session_recall(None, limit=1, recent_limit=3)
        ok("recent_global_window" in (pack3.get("degraded") or []),
           "D1 session=None 时 degraded 含 recent_global_window（不再静默）",
           pack3.get("degraded"))
        pack4 = cg.session_recall("sessA", limit=1, recent_limit=3)
        ok("recent_global_window" not in (pack4.get("degraded") or []),
           "D2 给了会话则**不**打该标记（不误报）", pack4.get("degraded"))

        print("== E sessions_read 分档（方案 C）")
        ok(p.sessions_read is None, "E1 缺省 None（旧行为，不限制）", p.sessions_read)
        p_none = Principal(role="designer", clearance="secret", can_write=True,
                           can_admin=False, layers_allow=["*"], session="sessX")
        cg3 = MdCGSecure(os.path.join(T, "brain"), principal=p_none, autoflush=1)
        pk = cg3.session_recall("sessA", limit=1, recent_limit=5)
        ok(len(pk.get("recent") or []) > 0, "E2 sessions_read=None 时按参数正常取（旧行为）",
           len(pk.get("recent") or []))
        cg3.close()
        p_nar = Principal(role="designer", clearance="secret", can_write=True,
                          can_admin=False, layers_allow=["*"], session="sessX",
                          sessions_read=["sessB"])
        cg4 = MdCGSecure(os.path.join(T, "brain"), principal=p_nar, autoflush=1)
        pk4 = cg4.session_recall("sessA", limit=1, recent_limit=10)
        ok(all((x.get("session") == "sessB") for x in (pk4.get("recent") or [])),
           "E3 sessions_read={sessB} 时**读不到** sessA（收紧生效）",
           [x.get("session") for x in (pk4.get("recent") or [])][:5])
        cg4.close()
        p_all = Principal(role="designer", clearance="secret", can_write=True,
                          can_admin=False, layers_allow=["*"], session="sessX",
                          sessions_read=["*"])
        cg5 = MdCGSecure(os.path.join(T, "brain"), principal=p_all, autoflush=1)
        pk5 = cg5.session_recall("sessA", limit=1, recent_limit=10)
        ok(len(pk5.get("recent") or []) > 0, "E4 sessions_read 为星号时全读（不收窄）",
           len(pk5.get("recent") or []))
        cg5.close()

        cg.close()
    finally:
        shutil.rmtree(T, ignore_errors=True)

    print()
    print("#712 守卫：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("  -", f)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
