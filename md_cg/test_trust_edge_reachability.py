# -*- coding: utf-8 -*-
"""声明迁移边 ↔ 实现点 台账守卫（issue #199 建议 4）。

【守什么】
#199 报：`TRANSITIONS` 收录了 `unverified → expired`，但唯一会「置 expired」的实现点
`coldverify` 在 `:173` **显式跳过 unverified** —— 于是这条边**声明了却没人走**（死边），
且「绝大多数存量过期记忆永远停在 unverified」。

**根因不是那一条边，而是没有断言「每条声明边都有实现点」。** 本守卫补上它：

  E1 **台账完备**：`TRANSITIONS` 的每条边都必须登记 —— 或落在具名实现点上，
     或落在 `_UNREACHABLE` 冻结台账里。**新增一条边而不更新台账 ⇒ 红。**
  E2 **台账不漂移**：具名实现点的特征片段必须在源码里**实际存在**（读源码断言），
     否则台账记的是一个已经不存在的实现点。
  E3 **死边冻结**：`_UNREACHABLE` 条数不得增加（当前恰 1 条）。
  E4 **反陈化（真跑）**：对 `_UNREACHABLE` 的每条边，断言它**现在真的不可达** ——
     真跑 coldverify 于一个 unverified 节点，断言返回 skipped == unverified_no_action。
     若有人修好 #199 T1（去掉跳过），本断言转红 ⇒ **强制更新台账**。
     这一条是刻意设计的：#210 已实测过「登记表的理由会过时且没有机制发现」。
  E5 **表与裁决函数逐位一致**：`can_transition` 的裁决必须与 `TRANSITIONS` 逐位一致
     （含幂等、未知 src 按 unverified、dst 非 STATES 一律拒绝）。

运行：python -X utf8 -m md_cg.test_trust_edge_reachability

沙箱纪律：库根落守卫临时目录，绝不碰在役库与 ~/.mdcg。
"""
from __future__ import annotations

import io
import os
import sys
import tempfile

from . import coldverify as cv_mod
from . import trust
from .mdcos import MdCGOS

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)

_PASS: list = []
_FAIL: list = []


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  -> " + str(extra)) if (extra and not cond) else ""))


# ---------------------------------------------------------------------------
# 具名实现点台账：能**自动**产生迁移的代码位置。
#
# 口径（重要）：这里只登记**自动路径**（队列/批处理/常驻循环自己发起的迁移），
# 不含「任何调用方都可请求」的公共 API `trust.set_state` —— 后者对每条声明边
# 都可达，若把它算进来，本守卫对死边就完全失去判别力。
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 具名自动实现点台账：能**自动**产生迁移的代码位置（队列/批处理/常驻循环自己发起）。
#
# 口径（重要）：这里只登记**自动路径**。公共 API trust.set_state 对每条声明边
# 都可达，若把它算进来，本守卫对「声明了却没人走的边」就完全失去判别力 ——
# 所以它单列为 _API_ONLY，而不是算作实现点。
# ---------------------------------------------------------------------------
_NAMED_IMPL = (
    # (文件, 特征片段, 该实现点可产生的边集合)
    ("md_cg/coldverify.py",
     "r = trust.set_state(cg, nid, want, reason=why,",
     frozenset({
         ("rechecking", "expired"),
         ("verified", "expired"),
         ("rechecking", "unverified"),
     })),
    # mark_dependents（trust.py:734）：一跳同步传播，把直接下游标 doubted
    ("md_cg/trust.py",
     "r = set_state(cg, k, " + chr(34) + "doubted" + chr(34) + ", reason=reason,",
     frozenset({
         ("unverified", "doubted"),
         ("verified", "doubted"),
         ("rechecking", "doubted"),
     })),
)

#: **仅公共 API 可达**：没有自动实现点，只能由调用方显式请求。
#: 这一类是**正常**的（人工/智能体驱动的状态变更），但必须显式登记 ——
#: 否则「这条边没有自动路径」在 code review 里不可见。
_API_ONLY = frozenset({
    ("doubted", "rechecking"),
    ("doubted", "verified"),
    ("expired", "rechecking"),
    ("expired", "verified"),
    ("rechecking", "verified"),
    ("unverified", "rechecking"),
    ("unverified", "verified"),
    ("verified", "rechecking"),
})

#: 无自动实现点的声明边（**冻结台账**）。
#: 规则：**新增死边必须改这里**，使「又多了一条声明了却没人自动走的边」在
#: code review 里可见；条数不得增加（E3 断言）。
_UNREACHABLE = {
    ("unverified", "expired"): {
        "reason": (
            "#199 T1：唯一会「置 expired」的**自动**实现点是 coldverify，而它在 "
            ":173 显式跳过 unverified（return skipped=unverified_no_action）；"
            "state_of 对缺字段返回 unverified ⇒ 存量缺字段的过期记忆不会**自动**"
            "走到 expired。注意：该边经公共 API trust.set_state 仍可达（E4f 实测）。"
        ),
        "issue": "199",
        "source": ("md_cg/coldverify.py",
                   "if old_state == " + chr(34) + "unverified" + chr(34) + ":"),
    },
}

def _edges_from_named() -> frozenset:
    out = set()
    for _f, _needle, edges in _NAMED_IMPL:
        out |= set(edges)
    return frozenset(out)


def e1():
    print("== E1 台账完备：TRANSITIONS 每条边都登记（三类之一）==")
    declared = frozenset(trust.TRANSITIONS)
    auto = _edges_from_named()
    ledger = auto | _API_ONLY | frozenset(_UNREACHABLE)
    missing = sorted(declared - ledger)
    phantom = sorted(ledger - declared)
    ok(not missing,
       "E1a 每条声明边都有登记（未登记 %d 条）" % len(missing), missing)
    ok(not phantom,
       "E1b 台账无幽灵边（台账多出 %d 条）" % len(phantom), phantom)
    ok(len(declared) == 15,
       "E1c 声明边数冻结为 15（实际 %d）——若有意增删边，请同批更新本台账"
       % len(declared), len(declared))
    pairs = (("自动实现点", auto, "仅 API", _API_ONLY),
             ("自动实现点", auto, "死边", frozenset(_UNREACHABLE)),
             ("仅 API", _API_ONLY, "死边", frozenset(_UNREACHABLE)))
    for n1, s1, n2, s2 in pairs:
        inter = sorted(s1 & s2)
        ok(not inter, "E1d %s 与 %s 不相交（交集 %d 条）" % (n1, n2, len(inter)),
           inter)
    ok(len(auto) + len(_API_ONLY) + len(_UNREACHABLE) == len(declared),
       "E1e 三类合计 == 声明边数（%d+%d+%d vs %d）"
       % (len(auto), len(_API_ONLY), len(_UNREACHABLE), len(declared)))
    ok(len(auto) >= 6,
       "E1f 自动实现点覆盖 >= 6 条边（实际 %d）——防实现点被误删后 E1a 仍靠"
       "「全部划进仅 API」蒙混过关" % len(auto), len(auto))

def e2():
    print("== E2 台账不漂移：具名实现点片段确实在源码里 ==")
    for rel, needle, _edges in _NAMED_IMPL:
        p = os.path.join(_REPO, rel)
        exists = os.path.exists(p)
        text = ""
        if exists:
            with io.open(p, encoding="utf-8", errors="replace") as f:
                text = f.read()
        ok(exists and needle in text,
           "E2 具名实现点仍在：%s :: %s" % (rel, needle[:48]),
           "文件存在=%s 片段命中=%s" % (exists, needle in text))
    for edge, rec in sorted(_UNREACHABLE.items()):
        rel, needle = rec["source"]
        p = os.path.join(_REPO, rel)
        text = ""
        if os.path.exists(p):
            with io.open(p, encoding="utf-8", errors="replace") as f:
                text = f.read()
        ok(needle in text,
           "E2 死边的成因片段仍在：%s→%s :: %s"
           % (edge[0], edge[1], needle[:44]), needle in text)


def e3():
    print("== E3 死边冻结：条数不得增加 ==")
    n = len(_UNREACHABLE)
    ok(n <= 1, "E3 死边条数 ≤ 1（实际 %d）——新增死边须先说明为何是必要的" % n, n)


def e4():
    print("== E4 反陈化：死边**现在真的**不可达（真跑 coldverify）==")
    root = tempfile.mkdtemp(prefix="edge_reach_")
    cg = MdCGOS(root)
    # 造一个 unverified 节点（缺 verification_state 字段 ⇒ state_of 返回 unverified）
    cg.add(content="# 死边探针\n\n用于断言 unverified 节点走 coldverify 会被跳过。",
           layer="knowledge", node_id="probe_dead_edge", importance=0.5,
           consistency=False, on_conflict="defer")
    node = cg.get("probe_dead_edge")
    fm = (node or {}).get("frontmatter") or {}
    st = trust.state_of(fm)
    ok(st == "unverified",
       "E4a 前置：探针节点的状态确为 unverified（实际 %r）" % st, st)

    q = cv_mod.ColdVerifyQueue(root=os.path.join(root, "_coldverify_q"))
    q.enqueue("probe_dead_edge", action="reverify")
    res = q.drain(cg)
    rows = res if isinstance(res, list) else (res or {}).get("results") or []
    if not rows and isinstance(res, dict):
        rows = [res]
    skipped = [r.get("skipped") for r in rows if isinstance(r, dict)]
    ok("unverified_no_action" in skipped,
       "E4b 死边仍不可达：coldverify 对 unverified 返回 unverified_no_action"
       "（实际 %r）" % (skipped or res), skipped or res)

    after = (cg.get("probe_dead_edge") or {}).get("frontmatter") or {}
    ok(trust.state_of(after) == "unverified",
       "E4c 死边未被执行：状态仍为 unverified（实际 %r）"
       % trust.state_of(after), trust.state_of(after))

    # 反向腿：同一实现点对**非** unverified 节点确实会动手（否则 E4b 可能
    # 是因为 coldverify 整个坏了，而不是因为这条边被刻意跳过）。
    cg.add(content="# 对照探针\n\n非 unverified 节点。", layer="knowledge",
           node_id="probe_live_edge", importance=0.5,
           consistency=False, on_conflict="defer")
    trust.set_state(cg, "probe_live_edge", "verified", reason="E4 对照")
    st2 = trust.state_of((cg.get("probe_live_edge") or {}).get("frontmatter") or {})
    ok(st2 == "verified",
       "E4d 反向腿前置：对照节点已被置为 verified（实际 %r）" % st2, st2)
    q2 = cv_mod.ColdVerifyQueue(root=os.path.join(root, "_coldverify_q2"))
    q2.enqueue("probe_live_edge", action="reverify")
    res2 = q2.drain(cg)
    rows2 = res2 if isinstance(res2, list) else (res2 or {}).get("results") or []
    if not rows2 and isinstance(res2, dict):
        rows2 = [res2]
    sk2 = [r.get("skipped") for r in rows2 if isinstance(r, dict)]
    ok("unverified_no_action" not in sk2,
       "E4e 反向腿：非 unverified 节点**不**被同一跳过分支拦下"
       "（实际 %r）" % (sk2 or res2), sk2 or res2)

    # E4f：把「不可达」的**准确边界**钉住 —— 该边在 TRANSITIONS 里，经公共 API
    # 仍然可达。故它是「无**自动**实现点」，不是「表里有、函数拒绝」。
    r_api = trust.set_state(cg, "probe_dead_edge", "expired",
                            reason="E4f 公共 API 可达性探针")
    ok(bool(r_api.get("ok")),
       "E4f 该边经公共 API 仍可达（ok=%r）——「死边」= 无自动实现点，非表内拒绝"
       % r_api.get("ok"), r_api.get("error"))
    st3 = trust.state_of((cg.get("probe_dead_edge") or {}).get("frontmatter") or {})
    ok(st3 == "expired",
       "E4g 公共 API 调用后状态确为 expired（实际 %r）" % st3, st3)


def e5():
    print("== E5 表与裁决函数逐位一致 ==")
    bad = []
    for a in trust.STATES:
        for b in trust.STATES:
            want = True if a == b else ((a, b) in trust.TRANSITIONS)
            got = trust.can_transition(a, b)
            if got != want:
                bad.append((a, b, want, got))
    ok(not bad, "E5a can_transition 与 TRANSITIONS 在 5×5 全格上逐位一致", bad)
    ok(trust.can_transition("nosuch", "verified") is True,
       "E5b 未知 src 按 unverified 处理（unverified→verified 合法）")
    ok(trust.can_transition("unverified", "nosuch") is False,
       "E5c dst 非 STATES 一律拒绝")
    ok(trust.can_transition("expired", "expired") is True,
       "E5d 同状态幂等放行")


def e6():
    print("== E6 拒绝必须被报出（不静默）==")
    # #199 附探：mark_dependents 无条件对每个下游请求 doubted，而
    # ("expired","doubted") **不在** TRANSITIONS ⇒ expired 下游必然被拒。
    # 拒本身可辩（过期节点再标存疑语义存疑），但**不得静默**——
    # 必须出现在 skipped 里，否则「地基动了」的信号被无声吞掉。
    root = tempfile.mkdtemp(prefix="edge_e6_")
    cg = MdCGOS(root)
    cg.add(content="# 上游\n\n地基。", layer="knowledge", node_id="up",
           importance=0.5, consistency=False, on_conflict="defer")
    cg.add(content="# 下游\n\n依赖上游。", layer="knowledge", node_id="dn",
           importance=0.5, consistency=False, on_conflict="defer",
           depends_on=["up"])
    ok(trust.deps_of(cg, "dn") == ["up"],
       "E6a 前置：dn 确已声明依赖 up（实际 %r）" % trust.deps_of(cg, "dn"),
       trust.deps_of(cg, "dn"))
    r1 = trust.mark_dependents(cg, "up", reason="E6 探针", apply=True)
    st1 = trust.state_of((cg.get("dn") or {}).get("frontmatter") or {})
    ok(r1.get("changed") == 1 and st1 == "doubted",
       "E6b 非 expired 下游可被标 doubted（changed=%r 终态=%r）"
       % (r1.get("changed"), st1), (r1.get("changed"), st1))

    root2 = tempfile.mkdtemp(prefix="edge_e6b_")
    cg2 = MdCGOS(root2)
    cg2.add(content="# 上游\n\n地基。", layer="knowledge", node_id="up",
            importance=0.5, consistency=False, on_conflict="defer")
    cg2.add(content="# 下游\n\n依赖上游。", layer="knowledge", node_id="dn",
            importance=0.5, consistency=False, on_conflict="defer",
            depends_on=["up"])
    cg2.set_verification("dn", "expired", reason="E6 探针")
    r2 = trust.mark_dependents(cg2, "up", reason="E6 探针", apply=True)
    st2 = trust.state_of((cg2.get("dn") or {}).get("frontmatter") or {})
    ok(st2 == "expired",
       "E6c expired 下游未被改动（终态 %r）" % st2, st2)
    skipped = list(r2.get("skipped") or [])
    ok(bool(skipped),
       "E6d 拒绝**被报出**（skipped 非空）：%r" % (skipped,), skipped)
    ok(any("illegal_transition" in str(s) for s in skipped),
       "E6e skipped 里带机器码 illegal_transition：%r" % (skipped,), skipped)


_GROUPS = (e1, e2, e3, e4, e5, e6)


def _run_groups() -> int:
    """跑全部断言组（清空并重填 _PASS/_FAIL），返回失败条数。"""
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        try:
            g()
        except Exception as exc:                              # noqa: BLE001
            ok(False, "断言组 %s 抛异常：%s" % (g.__name__, exc))
            import traceback
            print(traceback.format_exc()[-900:])
    return len(_FAIL)


def main() -> int:
    n = _run_groups()
    print("\n迁移边可达性守卫：%d 通过，%d 失败" % (len(_PASS), n))
    return 1 if n else 0


# --------------------------------------------------------------- 定点变异自证
# 口径：每个变异必须让**至少一条**断言转红，否则该判据没有判别力。
# 变异在**内存**里做（改模块全局），不动源码。
_MUTATIONS = (
    ("V1 声明一条新边而不登记台账", "add_edge",
     ("doubted", "unverified"), "E1a"),
    ("V2 具名实现点被删（propagate 的 doubted 边失登记）", "drop_impl",
     "md_cg/trust.py", "E1a"),
    ("V3 死边台账被清空（unverified->expired 变未登记）", "clear_unreachable",
     None, "E1a"),
    ("V4 具名实现点片段漂移（源码里已不存在）", "drift_impl",
     "md_cg/trust.py", "E2"),
    ("V5 死边条数增加", "grow_unreachable", None, "E3"),
    ("V6 表与裁决函数不一致（can_transition 放行一条未声明边）",
     "break_can_transition", None, "E5a"),
    ("V7 拒绝被静默吞掉（skipped 恒空）", "silent_skip", None, "E6d"),
)


def _mutate() -> int:
    """逐条施加变异，断言预期断言组转红。"""
    bad = []
    for name, kind, arg, want_red in _MUTATIONS:
        orig_T = trust.TRANSITIONS
        orig_impl = globals()["_NAMED_IMPL"]
        orig_unreach = dict(globals()["_UNREACHABLE"])
        orig_ct = trust.can_transition
        _orig_md_save = trust.mark_dependents
        try:
            if kind == "add_edge":
                trust.TRANSITIONS = frozenset(set(orig_T) | {arg})
            elif kind == "drop_impl":
                globals()["_NAMED_IMPL"] = tuple(
                    x for x in orig_impl if x[0] != arg)
            elif kind == "clear_unreachable":
                globals()["_UNREACHABLE"] = {}
            elif kind == "drift_impl":
                globals()["_NAMED_IMPL"] = tuple(
                    (f, n + "  # 已漂移", e) if f == arg else (f, n, e)
                    for f, n, e in orig_impl)
            elif kind == "grow_unreachable":
                globals()["_UNREACHABLE"] = dict(orig_unreach)
                globals()["_UNREACHABLE"][("doubted", "unverified")] = {
                    "reason": "变异：伪造第二条死边", "issue": "199",
                    "source": ("md_cg/trust.py", "def can_transition"),
                }
            elif kind == "break_can_transition":
                trust.can_transition = lambda s, d: True
            elif kind == "silent_skip":
                # 让被拒的下游不进 skipped（即「静默吞掉」）
                _orig_md = trust.mark_dependents

                def _silent(*a, **k):
                    rr = _orig_md(*a, **k)
                    rr["skipped"] = []
                    return rr
                trust.mark_dependents = _silent
            _run_groups()
            reds = list(_FAIL)
            hit = any(want_red in r for r in reds)
            print("  %-4s %-50s 红项=%-3d 命中%s=%s"
                  % ("OK" if hit else "BAD", name, len(reds), want_red,
                     "是" if hit else "否"))
            if not hit:
                bad.append(name)
        finally:
            trust.TRANSITIONS = orig_T
            globals()["_NAMED_IMPL"] = orig_impl
            globals()["_UNREACHABLE"] = orig_unreach
            trust.can_transition = orig_ct
            trust.mark_dependents = _orig_md_save
    if bad:
        print("\n定点变异自证：FAIL -- %s" % "、".join(bad))
        return 1
    print("\n定点变异自证：PASS（每处判据都被打红）")
    return 0


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(_mutate())
    sys.exit(main())
