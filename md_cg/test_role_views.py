# -*- coding: utf-8 -*-
"""角色化读取视图（roleviews）验收：第四阶段计划批次 C（H4）。

T1 规则表守卫——WORK_ROLES 白名单字面一致 + content_kind 合法枚举
   + 三视图资格维度与计划 §4.1 规则表一致；
T2 matches 单点谓词判定矩阵（三视图 × 各类元数据）+ 非法 view fail-closed；
T3 库层 fail-closed——candidates/search/search_rrf/recall 四入口
   非法 view 一律 ValueError（不静默回落）；
T4 零行为变更（H4 核心）——view=None（缺省）与不传 view 逐位一致
   （同 id 同序同分）；
T5 三视图端到端——各自命中集不同；receipt 与 main 在 role 维度互补；
   无 role 的 code 节点三视图皆不可见（类型启发严格口径，bench 校准
   是法定修正通道）；
T6 缓存隔离——同 query 不同 view 不串味（缓存键含 view），同 view
   命中缓存且结果一致；
T7 Secure 层——_candidates 签名同步（kw 透传不炸）+ search_rrf
   全称量词断言（结果集全部满足视图资格，图扩展扩散路径不泄漏）；
T8 recall 双路径透传——use_rrf 两分支端到端 + fail-closed 贯通；
T9 MCP 透传面——源码断言（read/route 分支 view= + schema 登记项，
   与 test_hyperedge T1③④ 同口径，防「库层通了、工具面没接」）。

运行：python -m md_cg.test_role_views
"""

import os
import shutil
import sys
import tempfile
import traceback

from . import roleviews
from . import hotcache
from .mdcos import MdCGSecure, WORK_ROLES
from .security import Principal

_ok = 0
_bad = []


def _check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("  ok   %s" % name)
    else:
        _bad.append("%s %s" % (name, detail))
        print("  FAIL %s %s" % (name, detail))


def _src(name):
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, name), encoding="utf-8") as f:
        return f.read()


def _mk_cg(tmp):
    p = Principal(tenant="default", actor="t_roleviews", role="designer",
                  can_write=True, can_admin=True)
    return MdCGSecure(tempfile.mkdtemp(dir=tmp), principal=p)


# 混合语料：共享主题词「极光」（同 query 命中全体，视图过滤看差异）
_CORPUS = [
    # (nid, layer, content_kind, role, tail)
    ("rv_e1", "knowledge", "text", "user", "观测报告正文结论"),
    ("rv_e2", "knowledge", "work_done", None, "工作完成结论记录"),
    ("rv_e3", "knowledge", "ccg_marks", None, "判据面与环境陷阱"),
    ("rv_e4", "contextual", "text", None, "情境上下文补充"),
    ("rv_e5", "knowledge", "code", "command", "命令脚本片段"),
    ("rv_e6", "knowledge", "text", "tool-output", "工具输出记录"),
    ("rv_e7", "knowledge", "code", None, "无角色代码片段"),
]
# 各视图预期可见集（T5 断言依据，与 roleviews.matches 语义独立推导）
_EXPECT = {
    None: {"rv_e1", "rv_e2", "rv_e3", "rv_e4", "rv_e7"},
    "main": {"rv_e1", "rv_e2"},
    "verifier": {"rv_e1", "rv_e3", "rv_e4"},
    "receipt": {"rv_e5", "rv_e6"},
}


def _seed(cg):
    for nid, layer, ck, role, tail in _CORPUS:
        kw = {"layer": layer, "content_kind": ck}
        if role is not None:
            kw["role"] = role
        cg.add(nid, "极光 %s" % tail, **kw)


def _ids(res):
    return [r[0]["id"] for r in res]


def _nid_of_entry(e):
    """candidates 索引 entry 无顶层 id 键——nid 取 path 的 stem（*.md）。"""
    p = (e.get("path") or "").replace("\\", "/")
    return p.rsplit("/", 1)[-1][:-3] if p.endswith(".md") else p


def _collect_ids(o, acc=None):
    """递归收集容器里所有节点标识（id 或 path，不依赖 recall 返回键形）。"""
    if acc is None:
        acc = set()
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, str) and k == "id":
                acc.add(v)
            elif isinstance(v, str) and k == "path":
                acc.add(_nid_of_entry({"path": v}))
            else:
                _collect_ids(v, acc)
    elif isinstance(o, (list, tuple)):
        for it in o:
            _collect_ids(it, acc)
    return acc


def _t1_rules():
    print("\n【T1】规则表守卫（真源一致性）")
    _check("① receipt 白名单与 mdcos.WORK_ROLES 字面一致（防两处漂移）",
           roleviews.ROLE_VIEWS["receipt"]["roles"] == WORK_ROLES,
           "%r vs %r" % (roleviews.ROLE_VIEWS["receipt"]["roles"], WORK_ROLES))
    _check("② 视图名集合 = {main, verifier, receipt}",
           set(roleviews.ROLE_VIEWS) == {"main", "verifier", "receipt"},
           str(sorted(roleviews.ROLE_VIEWS)))
    from . import audit as audit_mod
    _check("③ main/verifier 的 content_kinds 均为合法枚举（⊆audit.CONTENT_KINDS）",
           set(roleviews.ROLE_VIEWS["main"]["content_kinds"])
           | set(roleviews.ROLE_VIEWS["verifier"]["content_kinds"])
           <= set(audit_mod.CONTENT_KINDS))
    _check("④ main 资格=text|work_done ∧ knowledge 层（计划 §4.1）",
           set(roleviews.ROLE_VIEWS["main"]["content_kinds"]) == {"text", "work_done"}
           and roleviews.ROLE_VIEWS["main"]["layers"] == ("knowledge",))
    _check("⑤ verifier 资格=ccg_marks|text ∧ knowledge|contextual 层（计划 §4.1）",
           set(roleviews.ROLE_VIEWS["verifier"]["content_kinds"]) == {"ccg_marks", "text"}
           and set(roleviews.ROLE_VIEWS["verifier"]["layers"])
           == {"knowledge", "contextual"})
    _check("⑥ include_work 旗标：main/verifier=False，receipt=True",
           roleviews.ROLE_VIEWS["main"]["include_work"] is False
           and roleviews.ROLE_VIEWS["verifier"]["include_work"] is False
           and roleviews.ROLE_VIEWS["receipt"]["include_work"] is True)
    _check("⑦ views() 返回排序稳定元组",
           roleviews.views() == ("main", "receipt", "verifier"),
           str(roleviews.views()))


def _t2_matches():
    print("\n【T2】matches 单点谓词判定矩阵")
    M = roleviews.matches
    cases = [
        # (fm, view, 期望, 说明)
        ({"layer": "knowledge", "content_kind": "text"}, "main", True,
         "text+knowledge 命中 main"),
        ({"layer": "knowledge", "content_kind": "work_done"}, "main", True,
         "work_done 命中 main"),
        ({"layer": "contextual", "content_kind": "text"}, "main", False,
         "contextual 层不在 main"),
        ({"layer": "knowledge", "content_kind": "code", "role": "command"},
         "main", False, "code 不在 main 类型集"),
        ({"layer": "knowledge", "content_kind": "text", "role": "tool-output"},
         "main", False, "工作角色在 main 一票否决"),
        ({"layer": "knowledge", "content_kind": "text", "role": "command"},
         "main", False, "command 角色在 main 一票否决"),
        ({"layer": "knowledge", "content_kind": "text"}, "verifier", True,
         "text+knowledge 命中 verifier"),
        ({"layer": "knowledge", "content_kind": "ccg_marks"}, "verifier", True,
         "marks 命中 verifier"),
        ({"layer": "contextual", "content_kind": "text"}, "verifier", True,
         "contextual+text 命中 verifier"),
        ({"layer": "contextual", "content_kind": "ccg_marks"}, "verifier", True,
         "contextual+marks 命中 verifier"),
        ({"layer": "knowledge", "content_kind": "work_done"}, "verifier", False,
         "work_done 不在 verifier 类型集"),
        ({"role": "command"}, "receipt", True, "command 命中 receipt 白名单"),
        ({"role": "tool-output"}, "receipt", True, "tool-output 命中 receipt"),
        ({"role": "edit"}, "receipt", True, "edit 命中 receipt"),
        ({"role": "user"}, "receipt", False, "普通角色不进 receipt"),
        ({"content_kind": "code"}, "receipt", False,
         "无 role 的 code 不进 receipt（类型启发严格口径）"),
        ({"layer": "knowledge"}, "main", True,
         "缺 content_kind 按 text 对待（fail-open 惯例）"),
        ({"layer": "knowledge", "content_kind": "ccg_marks"}, "main", False,
         "marks 不进 main"),
    ]
    for fm, view, exp, why in cases:
        got = M(fm, view)
        _check("matches(%s, %s)=%s · %s" % (fm, view, exp, why),
               got == exp, "got %r" % got)
    try:
        M({"layer": "knowledge"}, "bogus")
        _check("非法 view ValueError（fail-closed）", False, "未抛出")
    except ValueError:
        _check("非法 view ValueError（fail-closed）", True)
    except Exception as exc:  # noqa: BLE001
        _check("非法 view ValueError（fail-closed）", False, repr(exc))


def _t3_failclosed(cg):
    print("\n【T3】库层 fail-closed（四入口非法 view）")
    for name, fn in [
        ("_candidates", lambda: cg._candidates(view="bogus")),
        ("search", lambda: cg.search("极光", view="bogus")),
        ("search_rrf", lambda: cg.search_rrf("极光", view="bogus")),
        ("recall/non-rrf", lambda: cg.recall("极光", budget_tokens=200,
                                             use_rrf=False, view="bogus")),
        ("recall/rrf", lambda: cg.recall("极光", budget_tokens=200,
                                         view="bogus")),
    ]:
        try:
            fn()
            _check("%s 非法 view ValueError" % name, False, "未抛出")
        except ValueError:
            _check("%s 非法 view ValueError" % name, True)
        except Exception as exc:  # noqa: BLE001
            _check("%s 非法 view ValueError" % name, False, repr(exc))


def _t4_zero_drift(cg):
    print("\n【T4】零行为变更（view=None ≡ 不传 view，逐位）")
    a, _ma = cg.search("极光")
    b, _mb = cg.search("极光", view=None)
    _check("search：同 id 同序同分",
           [(x[0]["id"], round(x[1], 9)) for x in a]
           == [(x[0]["id"], round(x[1], 9)) for x in b])
    ra, _mra = cg.search_rrf("极光")
    rb, _mrb = cg.search_rrf("极光", view=None)
    _check("search_rrf：同 id 同序同分",
           [(x[0]["id"], round(x[1], 9)) for x in ra]
           == [(x[0]["id"], round(x[1], 9)) for x in rb])
    ca = cg._candidates()
    cb = cg._candidates(view=None)
    _check("_candidates：同 id 同序",
           [_nid_of_entry(x) for x in ca] == [_nid_of_entry(x) for x in cb])
    m1 = cg.recall("极光", budget_tokens=4000)
    m2 = cg.recall("极光", budget_tokens=4000, view=None)
    _check("recall：结构同型", type(m1) is type(m2) and bool(m1) == bool(m2))


def _t5_views(cg):
    print("\n【T5】三视图端到端（候选层 + search 面）")
    for view, exp in _EXPECT.items():
        if view is None:
            continue
        got = {_nid_of_entry(e) for e in cg._candidates(view=view)}
        _check("candidates(view=%s) 命中集 %s" % (view, sorted(exp)),
               got == exp, "got %s" % sorted(got))
        res, _meta = cg.search("极光", k=20, view=view)
        got_s = set(_ids(res))
        _check("search(view=%s) 命中集一致" % view, got_s == exp,
               "got %s" % sorted(got_s))
    # receipt 与 main 在 role 维度互补（本语料：工作角色 ↔ 非工作角色不重叠）
    main_set = {_nid_of_entry(e) for e in cg._candidates(view="main")}
    rec_set = {_nid_of_entry(e) for e in cg._candidates(view="receipt")}
    _check("main × receipt 在 role 维度互斥", not (main_set & rec_set),
           "交集 %s" % sorted(main_set & rec_set))
    # 无 role 的 code 节点三视图皆不可见（类型启发严格口径，bench 校准通道）
    _check("rv_e7（无 role 的 code）三视图皆不可见",
           all("rv_e7" not in {_nid_of_entry(e) for e in cg._candidates(view=v)}
               for v in ("main", "verifier", "receipt")))


def _t6_cache(cg):
    print("\n【T6】缓存隔离（view 进键）")
    hotcache.attach(cg)
    r1, _ = cg.search_rrf("极光", k=20, view="main")
    r2, _ = cg.search_rrf("极光", k=20, view="receipt")
    ids_main = set(_ids(r1))
    ids_rec = set(_ids(r2))
    _check("同 query 不同 view 结果互斥（不串味）",
           ids_main == _EXPECT["main"] and ids_rec == _EXPECT["receipt"],
           "main=%s receipt=%s" % (sorted(ids_main), sorted(ids_rec)))
    r3, m3 = cg.search_rrf("极光", k=20, view="main")
    _check("同 view 复用缓存且结果一致",
           m3.get("cached") is True
           and _ids(r3) == _ids(r1),
           "cached=%r" % m3.get("cached"))


def _t7_secure(cg):
    print("\n【T7】Secure 层（签名同步 + 扩散路径兜底）")
    out = cg._candidates(view="main")
    _check("Secure._candidates(view=...) kw 透传不炸（签名同步守卫）",
           isinstance(out, list)
           and {_nid_of_entry(e) for e in out} == _EXPECT["main"],
           "got %s" % sorted({_nid_of_entry(e) for e in out}))
    res, _meta = cg.search_rrf("极光", k=50, view="main")
    nodes = cg.index["nodes"]
    _check("search_rrf 全称量词：结果全部满足 main 资格（扩散路径不泄漏）",
           all(roleviews.matches(nodes[x[0]["id"]], "main") for x in res),
           str([x[0]["id"] for x in res
                if not roleviews.matches(nodes[x[0]["id"]], "main")]))
    res2, _meta2 = cg.search_rrf("极光", k=50, view="receipt")
    _check("search_rrf receipt 全称量词",
           all(roleviews.matches(nodes[x[0]["id"]], "receipt") for x in res2)
           and set(_ids(res2)) == _EXPECT["receipt"],
           str(sorted(set(_ids(res2)))))


def _t8_recall(cg):
    print("\n【T8】recall 双路径透传")
    out = cg.recall("极光", budget_tokens=4000, view="main")
    got = _collect_ids(out) & {nid for nid, *_ in _CORPUS}
    _check("recall(view=main) 结果全在 main 资格集", got == _EXPECT["main"],
           "got %s" % sorted(got))
    out2 = cg.recall("极光", budget_tokens=4000, view="receipt")
    got2 = _collect_ids(out2) & {nid for nid, *_ in _CORPUS}
    _check("recall(view=receipt) 结果全在 receipt 资格集",
           got2 == _EXPECT["receipt"], "got %s" % sorted(got2))


def _t9_mcp_surface():
    print("\n【T9】MCP 透传面（源码断言，与 test_hyperedge T1③④ 同口径）")
    src = _src("mcp_server.py")
    # route 分支为 kwarg 形态（cg.search(..., view=a.get("view"))），
    # read 分支为 _tkw dict 形态（"view": a.get("view")）——各恰 1 处，
    # 比 >= 合计更严：防未来重复注册或单分支漏接。
    _check("route 分支透传 view=a.get(\"view\")（kwarg 形态恰 1 处）",
           src.count('view=a.get("view")') == 1,
           "count=%d" % src.count('view=a.get("view")'))
    _check("read 分支透传 view（_tkw dict 形态恰 1 处）",
           src.count('"view": a.get("view")') == 1,
           "count=%d" % src.count('"view": a.get("view")'))
    _check("schema 登记 view 项（角色化读取视图）",
           'view=_p("string", "read/route 的角色化读取视图' in src)


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_roleviews_")
    try:
        cg = _mk_cg(tmp)
        _seed(cg)
        _t1_rules()
        _t2_matches()
        _t3_failclosed(cg)
        _t4_zero_drift(cg)
        _t5_views(cg)
        _t6_cache(cg)
        _t7_secure(cg)
        _t8_recall(cg)
        _t9_mcp_surface()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n==== roleviews 验收：%d ok / %d fail ====" % (_ok, len(_bad)))
    for b in _bad:
        print("  FAIL> %s" % b)
    return 1 if _bad else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(2)
