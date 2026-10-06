# -*- coding: utf-8 -*-
"""test_lifecycle_retire_leak · 退役纪律守卫（archived 不参与默认检索）

现场（编排侧复现的对外缺陷）：写 v1 → 写矛盾 v2 → 把 v2 走**合法迁移表**
降到 `archived` → 查。`frontmatter.lifecycle_state` 与索引条目都已正确为
`archived`，而 `cg.search` 与 `stg.timeline` **仍返回 v2**——`lifecycle.py`
宣称「archived 已归档：不再参与默认检索」，而**读面从未实现该过滤**
（标称 vs 实现缺口）。

判据单点：`lifecycle.is_archived`（fail-open：缺键/非法值 → active）。
消费面（三个，判据只此一份）：①cg **检索面** `MdCGOS._candidates`；
②stg 扫描面 `stg._scan_one`（`_scan` 的全量遍历与索引子集两条分支共用的
逐条实现单点）；③会话续接**注入面** `MdCGOS.session_recall` 的四个取数段
（会话要点 `_session_notes` + 活跃目标 `goals` + 任务台账 `tasks` +
未解问题 `unresolved`；`goals`/`tasks` 经 `_retired_by_id` 按 id 回查索引）。

覆盖（R1–R4）：
  R1 复现序列：写 v1/v2 → demoted → archived → search / recall / search_rrf /
     `_candidates` 与 timeline / anchors / consistency 候选面（scanned 读数）
     均不返回 v2，v1 照常返回；R1.11 图扩展/因果路不绕过；R1.12 会话续接
     注入面（要点摘要 + 未解问题正文）；R1.13 续接包台账段（活跃目标 + 任务卡）；
  R2 不误剔：converged 与 demoted（**降权轴**）仍返回；**缺 lifecycle 键**
     节点照常返回（fail-open）；
  R3 退役不删除：archived 期间 `cg.get` 可得、`op=audit` 面可得；
     `set_state(archived→active)` 后读面（含续接面）重新可见；
  R4 面完整性：read/recall/search/route 全链（含 `mcp_server._cg_call`
     抽查一层）+ `op=session` 全链 archived 不出现。

运行：python -X utf8 -m md_cg.test_lifecycle_retire_leak
"""
from __future__ import annotations

import os
import shutil
import tempfile

from . import lifecycle, stg
from . import chain as _chain
from . import scrub as _scrub
from . import mcp_server
from . import tasks as _tasks
from .mdcg import MdCG
from .mdcos import MdCGOS

_root = tempfile.mkdtemp(prefix="mdcg_retire_")
cg = MdCGOS(_root)

_ok = 0
_fail = []

#: 查询串（固定字面量，逐字出现在各节点正文里——词面命中不靠猜测）。
Q = "退役泄漏守卫查询槽位"


def _body(tag, verdict):
    """CCG 六要素完整的节点正文（缺要素会被判 BLINDSPOT，污染可见性读数）。"""
    return ("# 功能名：退役纪律守卫·%s\n"
            "# 生效条件：隔离 temp root 内执行退役纪律守卫序列时\n"
            "# 子功能：①登记被测事实 ②退役后的读面/时空面可见性读数\n"
            "# 执行：cg.add 一次（退役节点另经 set_state 逐级降级）\n"
            "# 验证方式：读面 search/recall/search_rrf 与 stg 面的可见性断言\n"
            "# 不适用条件：在役真实记忆库内执行\n"
            "正文：%s = %s" % (tag, Q, verdict))


def check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("[ok] " + name)
    else:
        _fail.append(name)
        print("[FAIL] %s  · %s" % (name, str(detail)[:240]))


def _search_ids(q=Q):
    res, _meta = cg.search(q, k=50, record=False)
    return {str(n.get("id")) for n, _s, _q in res}


def _rrf_ids(q=Q):
    """RRF 路（`cg.recall` 缺省走的就是它）——含图扩展/因果路。"""
    res, _meta = cg.search_rrf(q, k=50, record=False)
    return {str(r[0].get("id")) for r in res}


def _recall_ids(q=Q):
    pack = cg.recall(q, budget_tokens=4000, k=50)
    return {str(it.get("id")) for it in (pack.get("pack") or [])}


def _entry_nid(e):
    """索引条目 → 节点 id：条目**不带 id 键**（只带 path），按文件名取
    （与 `MdCGOS._path_graph` 的 `e["path"].split("/")[-1][:-3]` 同口径）。"""
    p = str((e or {}).get("path") or "")
    return p.replace("\\", "/").split("/")[-1][:-3]


def _cand_ids():
    """读面单点 `_candidates` 的候选池 id 集合（cg 全部读 op 的公共候选面）。"""
    return {_entry_nid(e) for e in cg._candidates()}


def _tl():
    return stg.timeline(cg, limit=10 ** 6, max_scan=10 ** 9)


def _an():
    return stg.anchors(cg, time_window=[1.0, 10.0 ** 11], limit=10 ** 6,
                       max_scan=10 ** 9)


def _co():
    return stg.consistency(cg, limit=10 ** 6, max_scan=10 ** 9)


def _tl_ids(rep=None):
    rep = _tl() if rep is None else rep
    return {str(it.get("id")) for it in (rep.get("items") or [])}


def _an_ids(rep=None):
    rep = _an() if rep is None else rep
    return {str(it.get("id")) for it in (rep.get("items") or [])}


def _scan_subset_ids():
    """索引子集分支（`_scan(nodes=...)`）：第 3 层 flag 开时的取数面。"""
    pairs = list((cg.index.get("nodes") or {}).items())
    return {str(n.get("id")) for n in stg._scan(cg, nodes=pairs)}


def _fm(nid):
    return ((cg.get(nid) or {}).get("frontmatter")) or {}


def _idx(nid):
    return (cg.index.get("nodes") or {}).get(nid) or {}


def _subgraph_children():
    """结构面正查表（`subgraph.children_index`：parent_id → [child_id...]）。"""
    from . import subgraph as _sg
    return _sg.children_index(cg)


# ------------------------------------------------------------ R1 复现序列
n1 = cg.add("rl_v1", _body("旧事实 v1", "甲地（初始登记）"), layer="knowledge",
            verification_basis="test", importance=0.4)
n2 = cg.add("rl_v2", _body("新事实 v2（与 v1 矛盾）", "乙地（订正：甲地作废）"),
            layer="knowledge", verification_basis="test", importance=0.4)

check("R1.0 写入后两节点都在读面与时空面（前提成立，非空断言）",
      n1 in _search_ids() and n2 in _search_ids()
      and n1 in _tl_ids() and n2 in _tl_ids(),
      (sorted(_search_ids()), sorted(_tl_ids())))

scanned_tl_before = _tl().get("scanned")
scanned_co_before = _co().get("scanned")

_r1 = cg.set_state(n2, "demoted", reason="守卫：先降权", actor="test")
_r2 = cg.set_state(n2, "archived", reason="守卫：归档", actor="test")
check("R1.1 退役走合法迁移表（demoted→archived）且状态落盘为 archived",
      _r1.get("ok") and _r2.get("ok")
      and lifecycle.state_of(_fm(n2)) == "archived", (_r1, _r2, _fm(n2)))

check("R1.2 退役后 cg 读面 search 不返回 v2、v1 照常返回",
      n2 not in _search_ids() and n1 in _search_ids(), sorted(_search_ids()))
check("R1.3 退役后 cg 读面 recall（预算装包，走 RRF）不返回 v2、v1 照常返回",
      n2 not in _recall_ids() and n1 in _recall_ids(), sorted(_recall_ids()))
check("R1.4 退役后 cg 读面 search_rrf 不返回 v2、v1 照常返回",
      n2 not in _rrf_ids() and n1 in _rrf_ids(), sorted(_rrf_ids()))
check("R1.5 退役后 _candidates 候选池不含 v2（读面单点）、含 v1",
      n2 not in _cand_ids() and n1 in _cand_ids(), sorted(_cand_ids()))
check("R1.6 退役后 stg.timeline 不返回 v2、v1 照常返回",
      n2 not in _tl_ids() and n1 in _tl_ids(), sorted(_tl_ids()))
check("R1.7 退役后 stg.anchors 不返回 v2、v1 照常返回",
      n2 not in _an_ids() and n1 in _an_ids(), sorted(_an_ids()))

scanned_tl_after = _tl().get("scanned")
scanned_co_after = _co().get("scanned")
check("R1.8 stg 候选遍历读数随退役下降（timeline scanned 少 1）",
      scanned_tl_after == scanned_tl_before - 1,
      (scanned_tl_before, scanned_tl_after))
check("R1.9 consistency 候选面同点覆盖（scanned 少 1——archived 不进候选）",
      scanned_co_after == scanned_co_before - 1,
      (scanned_co_before, scanned_co_after))
check("R1.10 索引子集分支（_scan(nodes=...) 第 3 层取数面）逐位一致——不因取数面漏过滤",
      n2 not in _scan_subset_ids() and n1 in _scan_subset_ids(),
      sorted(_scan_subset_ids()))

# ------------------------------------------------------------ R2 不误剔
n3 = cg.add("rl_converged", _body("已定型 converged", "丙地"),
            layer="knowledge", verification_basis="test", importance=0.4)
n4 = cg.add("rl_demoted", _body("已降权 demoted", "丁地"),
            layer="knowledge", verification_basis="test", importance=0.4)
cg.set_state(n3, "converged", reason="守卫：定型", actor="test")
cg.set_state(n4, "demoted", reason="守卫：降权", actor="test")

check("R2.1 converged（已定型=降权轴）仍参与默认检索",
      lifecycle.state_of(_fm(n3)) == "converged"
      and n3 in _cand_ids() and n3 in _search_ids() and n3 in _tl_ids(),
      (_fm(n3).get(lifecycle.STATE_FIELD), sorted(_search_ids())))
check("R2.2 demoted（已降权=降权轴）仍参与默认检索",
      lifecycle.state_of(_fm(n4)) == "demoted"
      and n4 in _cand_ids() and n4 in _search_ids() and n4 in _tl_ids(),
      (_fm(n4).get(lifecycle.STATE_FIELD), sorted(_search_ids())))

# 缺 lifecycle 键（旧库形态）：盘上 fm 与索引条目都摘掉该键
n5 = cg.add("rl_legacy", _body("旧库缺键形态", "戊地"), layer="knowledge",
            verification_basis="test", importance=0.4)
_node5 = cg.get(n5)
_fm5 = dict(_node5["frontmatter"])
_fm5.pop(lifecycle.STATE_FIELD, None)
cg._write_node(n5, os.path.join(cg.root, _node5["path"]), _fm5,
               _node5.get("content") or "")
(cg.index.get("nodes") or {}).get(n5, {}).pop(lifecycle.STATE_FIELD, None)
check("R2.3 旧库形态成立（fm 与索引条目均无 lifecycle 键）",
      lifecycle.STATE_FIELD not in _fm(n5)
      and lifecycle.STATE_FIELD not in _idx(n5), (_fm(n5), _idx(n5)))
check("R2.4 fail-open：缺 lifecycle 键的节点照常参与默认检索（存量零迁移）",
      n5 in _cand_ids() and n5 in _search_ids() and n5 in _tl_ids(),
      sorted(_search_ids()))
check("R2.5 is_archived 判据单点：缺键/非法值/非 dict → False；archived → True",
      lifecycle.is_archived({}) is False
      and lifecycle.is_archived({lifecycle.STATE_FIELD: "frozen"}) is False
      and lifecycle.is_archived(None) is False
      and lifecycle.is_archived({lifecycle.STATE_FIELD: "archived"}) is True
      and lifecycle.is_archived(_idx(n2)) is True
      and lifecycle.is_archived({lifecycle.STATE_FIELD: "demoted"}) is False)

# ------------------------------------------------------------ R3 退役不删除
_node2 = cg.get(n2) or {}
check("R3.1 archived 期间 cg.get 直读可得（frontmatter + 正文 + 文件仍在）",
      bool(_node2) and bool(_node2.get("content"))
      and os.path.exists(os.path.join(cg.root, _node2.get("path") or "")),
      _node2)
_aud = mcp_server._cg_call(cg, {"op": "audit", "node_id": n2})
check("R3.2 archived 期间 op=audit 审计面照常可达（不被退役闸拦住）",
      isinstance(_aud, dict) and not _aud.get("error"), _aud)
check("R3.3 显式恢复 archived→active 走合法迁移表且成功",
      cg.set_state(n2, "active", reason="守卫：显式恢复",
                   actor="test").get("ok")
      and lifecycle.state_of(_fm(n2)) == "active", _fm(n2))
check("R3.4 恢复后读面/时空面重新可见（退役可逆）",
      n2 in _cand_ids() and n2 in _search_ids() and n2 in _tl_ids()
      and n2 in _an_ids(), (sorted(_search_ids()), sorted(_tl_ids())))
# 复原到 archived，供 R4 用
cg.set_state(n2, "demoted", reason="守卫：复测降权", actor="test")
cg.set_state(n2, "archived", reason="守卫：复测归档", actor="test")

# ------------------------------------------------------------ R4 面完整性
_call_read = mcp_server._cg_call(cg, {"op": "read", "query": Q, "k": 50})
_call_recall = mcp_server._cg_call(cg, {"op": "read", "query": Q,
                                        "budget_tokens": 4000, "k": 50})
_call_route = mcp_server._cg_call(cg, {"op": "route", "intent": Q, "k": 50})
_read_ids = {str(r.get("node", {}).get("id"))
             for r in (_call_read.get("results") or [])}
_pack_ids = {str(it.get("id")) for it in (_call_recall.get("pack") or [])}
_route_ids = {str(k.get("id")) for k in (_call_route.get("knowledge") or [])}
check("R4.1 op=read（检索分支）全链：archived 不出现、v1 出现",
      n2 not in _read_ids and n1 in _read_ids,
      (_call_read.get("meta"), sorted(_read_ids)))
check("R4.2 op=read（预算召回分支→recall/RRF）全链：archived 不出现、v1 出现",
      n2 not in _pack_ids and n1 in _pack_ids,
      (_call_recall.get("meta"), sorted(_pack_ids)))
check("R4.3 op=route 全链：archived 不出现、v1 出现",
      n2 not in _route_ids and n1 in _route_ids,
      (_call_route.get("meta"), sorted(_route_ids)))
check("R4.4 直读面（read+node_id 分支）不受限：archived 仍可显式取回",
      mcp_server._cg_call(cg, {"op": "read", "node_id": n2}) is not None)
check("R4.5 四条读面口径同源（都经 _candidates 单点）",
      n2 not in _cand_ids() and n2 not in _search_ids()
      and n2 not in _rrf_ids() and n2 not in _recall_ids())

# ------------------------------------------------------------ R1.11 图扩展/因果路不绕过读面
# `MdCGSecure.search_rrf` 的二次过滤注释宣称「图扩展会绕过 _candidates」——
# 本腿坐实：graph/chain 两路的扩散目标**受 entries 约束**（`_path_graph` 的
# by_id、`_path_chain` 的 allowed 都取自 `_candidates`），故 archived 目标
# 进不了融合池。判据分两段：先证「扩展真的能到达目标」（非空断言，反空转），
# 再证「目标退役后到达不了」。
g1 = cg.add("rl_graph_v1", _body("图扩展种子", "己地"), layer="knowledge",
            verification_basis="test", importance=0.4,
            edges=[{"target": "rl_graph_v2", "type": "derived_from"}])
g2 = cg.add("rl_graph_v2", _body("图扩展目标（待退役）", "庚地"),
            layer="knowledge", verification_basis="test", importance=0.4)


def _graph_ids():
    res, _meta = cg.search_rrf(Q, k=50, record=False,
                               paths=("lexical", "graph", "chain"))
    return {str(r[0].get("id")) for r in res}


check("R1.11a 前提：graph/chain 扩散确实能到达边目标（非空断言，防本腿空转）",
      g1 in _graph_ids() and g2 in _graph_ids(), sorted(_graph_ids()))
cg.set_state(g2, "demoted", reason="守卫：图路降权", actor="test")
cg.set_state(g2, "archived", reason="守卫：图路归档", actor="test")
check("R1.11b 目标退役后图扩展路不返回它、种子照常返回（图扩展不绕过 _candidates）",
      g2 not in _graph_ids() and g1 in _graph_ids(), sorted(_graph_ids()))

# ------------------------------------------------------------ R1.12 会话续接注入面（复核打回补）
# 独立复核 2026-10-06：`cg(op=session, action=recall)` 自持取数面（不经 _candidates），
# 修前把 archived 节点的要点摘要与未解问题正文照旧回给调用方——同属「退役不参与
# 默认注入」的遗漏出口。本腿两段：先证在役时确能回出（非空断言，反空转），再证
# 退役后回不出；并留一条在役对照（防「一刀切全清空」的假绿）。
_SN = "sess_retire_guard"


def _sess_pack(session=_SN):
    return cg.session_recall(session=session, limit=50, recent_limit=50,
                             budget_tokens=20000)


def _sess_ids(p=None):
    p = _sess_pack() if p is None else p
    ids = {str(n.get("id")) for n in (p.get("notes") or [])}
    ids |= {str(u.get("id")) for u in (p.get("unresolved") or [])}
    ids |= {str(g.get("id")) for g in (p.get("goals") or [])}
    ids |= {str(t.get("id")) for t in ((p.get("tasks") or {}).get("active") or [])}
    ids |= {str(t.get("id")) for t in ((p.get("tasks") or {}).get("done") or [])}
    return ids


_note1 = cg.session_note("守卫会话要点甲：退役后不应再回给调用方",
                         session=_SN, importance=0.6)["id"]
_note2 = cg.session_note("守卫会话要点乙：仍在役（对照，须照常回出）",
                         session=_SN, importance=0.6)["id"]
_unr1 = cg.add_unresolved("守卫未解问题：退役后是否仍被注入？",
                          known_clues="守卫线索", goal="守卫目标")
check("R1.12a 前提：会话要点与未解问题都确在续接包里（非空断言，防本腿空转）",
      {_note1, _note2, _unr1} <= _sess_ids(), sorted(_sess_ids()))
for _nid in (_note1, _unr1):
    cg.set_state(_nid, "demoted", reason="守卫：续接面降权", actor="test")
    cg.set_state(_nid, "archived", reason="守卫：续接面归档", actor="test")
check("R1.12b 退役后续接包不再回该要点与未解问题（注入面剔除）；在役对照仍在",
      _sess_ids().isdisjoint({_note1, _unr1}) and _note2 in _sess_ids(),
      sorted(_sess_ids()))
cg.set_state(_note1, "active", reason="守卫：续接面恢复", actor="test")
check("R3.5 恢复后续接包重新回该要点（退役可逆，同面）",
      _note1 in _sess_ids(), sorted(_sess_ids()))
cg.set_state(_note1, "demoted", reason="守卫：复测降权", actor="test")
cg.set_state(_note1, "archived", reason="守卫：复测归档", actor="test")

# ------------------------------------------------- R1.13 续接包台账段（复核打回补）
# 独立复核 2026-10-06 第二轮回执：同一续接包中 notes/未解段已剔而 goals/tasks 段
# 仍把 archived 节点注回调用方（与本文件 §5 判据字面冲突）。本腿三段：前提（真能
# 带回）→ 退役后剔除（含 `*_total` 口径）→ 恢复后重新带回；并留在役对照防假绿。
_goal1 = cg.add_goal("守卫目标甲：退役后不应再进续接包", priority=0.4)
_goal2 = cg.add_goal("守卫目标乙：仍在役（对照）", priority=0.3)
_task1 = _tasks.upsert(cg, "守卫任务卡甲", plan="退役后不应再进续接包")["node_id"]
_task2 = _tasks.upsert(cg, "守卫任务卡乙", plan="仍在役（对照）")["node_id"]


def _pack_ledger(p=None):
    p = _sess_pack() if p is None else p
    ids = {str(g.get("id")) for g in (p.get("goals") or [])}
    ids |= {str(t.get("id"))
            for t in ((p.get("tasks") or {}).get("active") or [])}
    return ids, (p.get("tasks") or {})


check("R1.13a 前提：活跃目标与任务卡都确在续接包里（非空断言，防本腿空转）",
      {_goal1, _goal2, _task1, _task2} <= _pack_ledger()[0],
      sorted(_pack_ledger()[0]))
# 任务卡以 importance=0.8 建（tasks.DEFAULT_IMPORTANCE）⇒ 自动 protected——
# 受保护节点降级须显式 override=True（lifecycle 的「保护 = 不可遗忘」）；这里
# 顺带把退役结果断言出来，避免「退役没成功却当成已退役」的假绿。
_led_ret = []
for _nid in (_goal1, _task1):
    _led_ret.append(cg.set_state(_nid, "demoted", reason="守卫：台账段降权",
                                 actor="test", override=True))
    _led_ret.append(cg.set_state(_nid, "archived", reason="守卫：台账段归档",
                                 actor="test", override=True))
check("R1.13b0 台账两节点退役成功（任务卡默认 protected，降级走 override=True）",
      all(r.get("ok") for r in _led_ret)
      and all(lifecycle.state_of(_fm(_n)) == "archived"
              for _n in (_goal1, _task1)), _led_ret)
_led_ids, _led_tasks = _pack_ledger()
check("R1.13b 退役后台账段不再回该目标与任务卡；在役对照仍在；total 取剔除后计数",
      _led_ids.isdisjoint({_goal1, _task1})
      and {_goal2, _task2} <= _led_ids
      and _led_tasks.get("active_total") == 1
      and _led_tasks.get("done_total") == 0,
      (sorted(_led_ids), _led_tasks.get("active_total"),
       _led_tasks.get("done_total")))
check("R1.13c 管理面不受限对照：cg(op=goal/task, action=list) 仍可见 archived 台账",
      any(g.get("id") == _goal1 for g in
          (mcp_server._cg_call(cg, {"op": "goal", "action": "list"})
           .get("goals") or []))
      and any(t.get("id") == _task1 for t in
              (mcp_server._cg_call(cg, {"op": "task", "action": "list"})
               .get("tasks") or [])),
      mcp_server._cg_call(cg, {"op": "goal", "action": "list"}))
cg.set_state(_goal1, "active", reason="守卫：台账段恢复", actor="test")
check("R3.6 恢复后台账段重新回该目标（退役可逆，同面）",
      _goal1 in _pack_ledger()[0], sorted(_pack_ledger()[0]))
cg.set_state(_goal1, "demoted", reason="守卫：复测降权", actor="test")
cg.set_state(_goal1, "archived", reason="守卫：复测归档", actor="test")
# ------------------------------------------------------------ R4.6 会话续接面全链抽查
_call_sess = mcp_server._cg_call(cg, {"op": "session", "action": "recall",
                                      "session": _SN, "limit": 50,
                                      "recent_limit": 50,
                                      "budget_tokens": 20000})
_sess_call_ids = {str(n.get("id")) for n in (_call_sess.get("notes") or [])}
_sess_call_ids |= {str(u.get("id"))
                   for u in (_call_sess.get("unresolved") or [])}
check("R4.6 op=session（action=recall）全链：archived 要点/未解问题不出现、在役对照出现",
      _sess_call_ids.isdisjoint({_note1, _unr1}) and _note2 in _sess_call_ids,
      sorted(_sess_call_ids))

# ------------------------------------------- R5 基类 MdCG.search（2026-10-06 接线）
# 边界四条第 1 面（运维文档 §九.5 登记的已知未覆盖面）：plain `MdCG` 实例
# （白箱 KB / 离线脚本 / 测试）的默认检索面此前未接判据——同序列下 MdCG 命中
# `['a_v1','a_v2']` 而 MdCGOS 只命中 `['a_v1']` 的取证。现按「默认读面必须消费
# 判据」接线；本腿：在役对照（converged 降权轴仍参与）→ archived 剔除。
def _base_ids():
    r = MdCG(_root).search(Q, k=50, record=False)
    res = r[0] if isinstance(r, tuple) else r
    return {str(n.get("id")) for n, *_ in (res or [])}


_b5 = _base_ids()
check("R5.1 基类面：archived（rl_v2）不出现、v1 出现",
      n2 not in _b5 and n1 in _b5, sorted(_b5))
check("R5.2 基类面不误剔：converged（rl_converged）仍参与（降权轴）",
      n3 in _b5, sorted(_b5))

# ------------------------------------------- R6 因果链面（2026-10-06 接线）
# 边界四条第 2 面：`chain.adjacency` 无 lifecycle 判据 ⇒ `cg(op=causal,
# action=chain)` 扩散进 archived（取证：链里出现归档 b_tgt）。接线后缺省
# `skip_archived=True` 剔除退役节点出边与指向退役目标的边；维护面
# （scrub 去污染抽查）显式 `skip_archived=False` 保留全量（面的判据分工）。
# 另钉一条本批实证的缓存缺口：归档发生在链**已建**之后（缓存已热）也必须
# 生效——`lifecycle.set_state` 现在补了 `chain.invalidate_cache` 单点。
_c6_seed = cg.add("rl_c6_seed", _body("因果链种子", "辛地"), layer="knowledge",
                  verification_basis="test", importance=0.4,
                  edges=[{"target": "rl_c6_tgt", "relation_type": "causal",
                          "confidence": 0.9}])
_c6_tgt = cg.add("rl_c6_tgt", _body("因果链目标（待退役）", "壬地"),
                 layer="knowledge", verification_basis="test", importance=0.4)


def _c6_has(rep):
    return any("rl_c6_tgt" in (c.get("nodes") or []) for c in (rep or []))


check("R6.0 前提：因果链在役时确实扩散到目标（非空断言，防本腿空转）",
      _c6_has(cg.causal_chain("rl_c6_seed")), cg.causal_chain("rl_c6_seed"))
cg.set_state(_c6_tgt, "demoted", reason="守卫：链面降权", actor="test")
cg.set_state(_c6_tgt, "archived", reason="守卫：链面归档", actor="test")
check("R6.1 目标退役后因果链不扩散进它（缓存已热时亦生效——set_state 同点失效）",
      not _c6_has(cg.causal_chain("rl_c6_seed")), cg.causal_chain("rl_c6_seed"))
check("R6.2 维护面旁路：adjacency(skip_archived=False) 仍含退役边（scrub 全量口径）",
      any(t == "rl_c6_tgt" for t, _e in
          (_chain.adjacency(cg, skip_archived=False).get("rl_c6_seed") or [])))
check("R6.3 scrub 面经旁路取数同证（维护写面不受退役过滤约束）",
      any(t == "rl_c6_tgt" for t, _e in
          (_scrub._adjacency(cg).get("rl_c6_seed") or [])))
cg.set_state(_c6_tgt, "active", reason="守卫：链面恢复", actor="test")
check("R6.4 恢复后因果链重新扩散（退役可逆，同面）",
      _c6_has(cg.causal_chain("rl_c6_seed")), cg.causal_chain("rl_c6_seed"))
cg.set_state(_c6_tgt, "demoted", reason="守卫：复测降权", actor="test")
cg.set_state(_c6_tgt, "archived", reason="守卫：复测归档", actor="test")

# --------------------------------- R7 结构面（裁定：不接——定向面直读，钉住裁定）
# 边界四条第 3 面经使用者裁定（2026-10-06）**保持直读**：调用方给显式父/子
# id、返回 id 映射不回正文，属定向/结构面。本腿把裁定钉住——若未来有人
# "顺手接线"，R7.1 转红即提醒该行为已被裁定（改行为须先改裁定）。
_c7_parent = cg.add("rl_c7_parent", _body("结构面父节点", "癸地"),
                    layer="knowledge", verification_basis="test", importance=0.4,
                    subgraph={"nodes": ["rl_c7_child"]})
_c7_child = cg.add("rl_c7_child", _body("结构面子节点（待退役）", "子地"),
                   layer="knowledge", verification_basis="test", importance=0.4)
check("R7.0 前提：children_index 含该父→子映射（非空断言，防本腿空转）",
      "rl_c7_child" in (_subgraph_children().get("rl_c7_parent") or []),
      _subgraph_children())
cg.set_state(_c7_child, "demoted", reason="守卫：结构面降权", actor="test")
cg.set_state(_c7_child, "archived", reason="守卫：结构面归档", actor="test")
check("R7.1 子节点退役后 children_index 映射仍在（裁定：结构面直读不接判据）",
      "rl_c7_child" in (_subgraph_children().get("rl_c7_parent") or []),
      _subgraph_children())

print("=" * 58)
print("test_lifecycle_retire_leak: %d 通过 / %d 失败" % (_ok, len(_fail)))
if _fail:
    print("失败项：" + "、".join(_fail))
shutil.rmtree(cg.root, ignore_errors=True)
raise SystemExit(1 if _fail else 0)
