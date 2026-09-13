# -*- coding: utf-8 -*-
"""写路径收口测试：mdcg 边域三原语 + knowledge_points md 真源模式。

对应用户裁定「2.写md真源」——白箱工具写 md 语料的唯一正路：
- mdcg.append_edge / append_subgraph_node / set_edge_condition（边域窄原语）
- KnowledgePointSplitter(cg=...) md 真源模式 vs sqlite 旧路双模等价

运行: python -X utf8 -m md_cg.test_md_writepath
"""

import json
import os
import sqlite3
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from md_cg.mdcg import MdCG  # noqa: E402

_WB = os.path.join(_HERE, "whitebox_kb")
for _p in (_WB, os.path.join(_WB, "wisdom")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from knowledge_points import KnowledgePointSplitter  # noqa: E402
from md_access import MdConn  # noqa: E402

_PASS = 0
_FAIL = 0


def _ok(cond, label):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  PASS  {label}")
    else:
        _FAIL += 1
        print(f"  FAIL  {label}")
    return bool(cond)


def _make_card(cg, cid="card_test_1", name="物理基础"):
    content = ("1. 浮力: 浸在流体中的物体受到流体向上的托力\n"
               "2. 密度: 单位体积物质的质量")
    cg.add(cid, content, layer="knowledge", tags=["subject_card"],
           condition_space={"observation_position": "测试卡",
                            "observation_tool": "writepath 测试"},
           importance=0.7, confidence=0.9,
           state_attributes={"name": name, "domain": "physics",
                             "edu_level": "初中"},
           verification_basis="textbook")
    return content


def test_primitives(cg):
    print("== [1] mdcg 边域三原语 ==")
    cg.add("n_src", "源节点", layer="knowledge", tags=[],
           importance=0.5, confidence=0.6)
    # append_edge
    ok1 = cg.append_edge("n_src", {"target": "n_t", "relation_type": "causal",
                                   "confidence": 0.6, "verified": 0,
                                   "condition_space": {"a": 1}})
    _ok(ok1 is True, "append_edge 首次追加 True")
    node = cg.get("n_src")
    edges = (node.get("frontmatter") or {}).get("edges") or []
    _ok(len(edges) == 1 and edges[0]["target"] == "n_t",
        "落盘 fm.edges 含新边")
    entry = cg.index["nodes"].get("n_src") or {}
    _ok(len(entry.get("edges") or []) == 1, "索引 entry.edges 同步")
    _ok(cg.append_edge("n_src", {"target": "n_t", "relation_type": "causal",
                                 "confidence": 0.9}) is False,
        "append_edge 同 target 同关系去重 False")
    _ok(cg.append_edge("n_ghost", {"target": "x", "relation_type": "causal"})
        is False, "append_edge 不存在节点 False")
    # append_subgraph_node
    _ok(cg.append_subgraph_node("n_src", "n_child") is True,
        "append_subgraph_node 首次 True")
    _ok(cg.append_subgraph_node("n_src", "n_child") is False,
        "append_subgraph_node 去重 False")
    sg = (cg.get("n_src").get("frontmatter") or {}).get("subgraph") or {}
    _ok(sg.get("nodes") == ["n_child"], "落盘 subgraph.nodes 正确")
    _ok((cg.index["nodes"].get("n_src") or {}).get("subgraph") is not None,
        "索引 entry.subgraph 同步")
    # set_edge_condition
    ok2 = cg.set_edge_condition("n_src", "n_t", "causal",
                                {"observation_position": "新位置"})
    _ok(ok2 is True, "set_edge_condition 匹配 True")
    e0 = (cg.get("n_src").get("frontmatter").get("edges"))[0]
    _ok(e0["condition_space"] == {"observation_position": "新位置"},
        "condition_space 已更新")
    _ok(cg.set_edge_condition("n_src", "n_none", "causal", {}) is False,
        "set_edge_condition 无匹配 False")


def test_kp_md_mode(cg):
    print("== [2] knowledge_points md 真源模式 ==")
    content = _make_card(cg)
    sp = KnowledgePointSplitter(cg=cg)
    r = sp.split_card("card_test_1", "物理基础", "physics", "初中",
                      content, 0.7)
    _ok(r["added"] == 2 and r["skipped"] == 0,
        f"split_card 拆出 2 知识点（{r}）")
    kps = [nid for nid in cg.index["nodes"] if nid.startswith("kp_")]
    _ok(len(kps) == 2, "kp 节点已入索引")
    kp_fm = (cg.get(kps[0]).get("frontmatter") or {})
    sa = kp_fm.get("state_attributes") or {}
    _ok(sa.get("kind") == "knowledge_point"
        and sa.get("parent_card") == "card_test_1",
        "kp state_attributes 落盘")
    _ok("knowledge_point" in (kp_fm.get("tags") or [])
        and f"card:card_test_1" in (kp_fm.get("tags") or []),
        "kp tags 含 card 前缀关联")
    _ok(kp_fm.get("importance") == 0.63,
        f"kp importance=卡×0.9（{kp_fm.get('importance')}）")
    _ok(kp_fm.get("verification_basis") == "textbook",
        "kp verification_basis=textbook")
    cs = kp_fm.get("condition_space") or {}
    _ok("time_window" in cs and cs.get("observation_tool") == "学科知识卡拆分",
        "kp condition_space 落盘")
    # 层级边：卡 subgraph.nodes 含 kp
    card_fm = (cg.get("card_test_1").get("frontmatter") or {})
    subs = (card_fm.get("subgraph") or {}).get("nodes") or []
    _ok(sorted(subs) == sorted(kps), f"卡 subgraph.nodes 含 2 kp（{subs}）")
    # 幂等重跑
    r2 = sp.split_card("card_test_1", "物理基础", "physics", "初中",
                       content, 0.7)
    _ok(r2["added"] == 0 and r2["skipped"] == 2,
        f"幂等重跑 added=0 skipped=2（{r2}）")
    # find_points（走 MdConn，加载时 kp 已落盘）
    hits = sp.find_points("浮力")
    _ok(any(h["name"] == "浮力" for h in hits),
        f"find_points('浮力') 命中（{[h['name'] for h in hits]}）")
    return sp


def test_mdconn_edge_domain(cg, sp):
    print("== [3] MdConn 边域访问器 ==")
    md = sp._md_conn()
    _ok(md.children_of("card_test_1") and
        len(md.children_of("card_test_1")) == 2,
        "children_of 经 subgraph 落点读到 2 kp")
    _ok(md.has_edge("card_test_1", "whatever", "hierarchical") is False,
        "has_edge 层级边不在 fm.edges（落点=subgraph）如实 False")
    # causal 边走 fm.edges
    cg.append_edge("n_src2", {"target": "n_t2", "relation_type": "causal",
                              "confidence": 0.6}, ) if cg.get("n_src2") else None
    # 用测试专用节点验证 has_edge
    cg.add("n_a", "苹果是水果", layer="knowledge", tags=[],
           importance=0.5, confidence=0.6)
    cg.add("n_b", "苹果富含维生素并且内容更长一些", layer="knowledge", tags=[],
           importance=0.8, confidence=0.6)
    cg.append_edge("n_a", {"target": "n_b", "relation_type": "causal"})
    md.reload()  # 写入后刷新快照
    _ok(md.has_edge("n_a", "n_b", "causal") is True,
        "has_edge 经 fm.edges 读到 causal 边")
    _ok(md.has_edge("n_a", "n_x", "causal") is False, "has_edge 未命中 False")
    top = md.top_content_match("苹果", None)
    _ok(top == ("n_b",),
        f"top_content_match 高 importance 优先（{top}）")
    top2 = md.top_content_match("苹果", "n_b")
    _ok(top2 == ("n_a",), f"top_content_match exclude 生效（{top2}）")


def test_sqlite_legacy():
    print("== [4] sqlite 旧路（兜底）不破坏 ==")
    tmp = tempfile.mkdtemp(prefix="wbwp_sql_")
    db = os.path.join(tmp, "t.db")
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE nodes (id TEXT PRIMARY KEY, content TEXT, modality TEXT,"
        " spatial_coordinates TEXT, temporal_coordinate REAL, condition_space"
        " TEXT, importance REAL, confidence REAL, layer TEXT, access_count"
        " INTEGER, last_access REAL, created_at REAL, tags TEXT,"
        " semantic_coordinates TEXT, state_attributes TEXT, entity_id TEXT)")
    con.execute(
        "CREATE TABLE edges (id TEXT PRIMARY KEY, source_id TEXT, target_id"
        " TEXT, relation_type TEXT, condition_space TEXT, confidence REAL,"
        " weight REAL, verified INTEGER, created_at REAL, last_verified REAL,"
        " source_evidence TEXT)")
    con.commit()
    con.close()
    sp = KnowledgePointSplitter(db_path=db)
    content = _make_card.__doc__ or ""
    r = sp.split_card("card_sql_1", "化学基础", "chemistry", "高中",
                      "1. 摩尔: 物质的量的单位\n2. 阿伏伽德罗: 常数约为6.02e23",
                      0.7)
    _ok(r["added"] == 2, f"sqlite 模式 split_card added=2（{r}）")
    con = sqlite3.connect(db)
    n = con.execute("SELECT COUNT(*) FROM nodes WHERE layer='knowledge'"
                    ).fetchone()[0]
    e = con.execute("SELECT COUNT(*) FROM edges WHERE "
                    "relation_type='hierarchical'").fetchone()[0]
    _ok(n == 2 and e == 2, f"sqlite 落库 nodes={n} edges={e}")
    con.close()
    sp.close()


def test_pattern_md_mode():
    print("== [5] pattern_separation md 真源模式 ==")
    from pattern_separation import PatternSeparation
    tmp = tempfile.mkdtemp(prefix="wbwp_pat_")
    cg = MdCG(root=tmp)  # 独立 root：scan 全库扫描不受其他组节点干扰
    # 两个高相似知识层节点（标签差异 → separation_note 非空）
    cg.add("p_a", "苹果是一种常见的水果，富含维生素与水分", layer="knowledge",
           tags=["知识", "水果"], importance=0.5, confidence=0.6,
           condition_space={"observation_position": "水果观察"},
           state_attributes={"name": "苹果", "domain": "生物"})
    cg.add("p_b", "苹果是一种常见的水果，富含维生素和水分较多", layer="knowledge",
           tags=["知识", "坚果"], importance=0.5, confidence=0.6,
           condition_space={"observation_position": "水果观察"},
           state_attributes={"name": "苹果干", "domain": "生物"})
    ps = PatternSeparation(cg=cg)  # 纯 md 模式（engine=None）
    _ok(ps.store is None and ps.cg is cg, "纯 md 模式构造（无 engine）")
    r = ps.scan(limit=50)
    _ok(r.get("created") == 1 and r.get("scanned") == 1,
        f"scan 建一条分离边（{r}）")
    md = ps._md_conn()
    md.reload()  # scan 已显式 flush；同实例快照仍需刷新（正式语义）
    edges = md.edges_between("p_a", "p_b", "similar")
    _ok(len(edges) == 1, "edges_between 读到 similar 边")
    if edges:
        e = edges[0]
        cs = e.get("condition_space") or {}
        _ok(cs.get("observation_position") == "模式分离",
            "分离边 observation_position=模式分离")
        _ok("坚果" in (cs.get("existence_constraint") or ""),
            "差异注记含标签区分维度")
        _ok(e.get("source_evidence") == "inferred"
            and e.get("verified") == 0, "边形态对齐引擎默认（inferred/未验证）")
    _ok(md.edges_between("p_b", "p_a", "similar") == [],
        "edges_between 反向无命中（边是 a→b 出边）")
    # 幂等重跑：已存在 separation 边 → 走更新支路
    r2 = ps.scan(limit=50)
    _ok(r2.get("created") == 0 and r2.get("updated") == 1,
        f"幂等重跑走更新支路（{r2}）")


class _StubEngine:
    """最小信号源 stub：只供 causal 信号面（被拒路径清单）。

    causal md 模式的 engine 职责收窄为运行时信号消费——
    候选/边/追踪全在 md，sqlite 全家桶无须实例化（依赖面显式化）。
    """

    def __init__(self, paths):
        self._paths = paths

    def list_rejected_paths(self, status=None):
        return [p for p in self._paths
                if status is None or p.get("status") == status]


def test_causal_md_mode():
    print("== [6] causal_discover md 真源模式 ==")
    from causal_discover import CausalDiscoverer
    # update_tags 原语直测
    cg_ut = MdCG(root=tempfile.mkdtemp(prefix="wbwp_ut_"))
    cg_ut.add("ut_n", "update tags 测试节点", layer="contextual",
              tags=["a", "b"], importance=0.3)
    _ok(cg_ut.update_tags("ut_n", add=["c"], remove=["a"]) is True,
        "update_tags 增删 True")
    _ok(cg_ut.update_tags("ut_n", add=["c"]) is False,
        "update_tags 无实质变更 False（幂等）")
    _ok(cg_ut.update_tags("ghost", add=["x"]) is False,
        "update_tags 不存在节点 False")
    ft = (cg_ut.get("ut_n").get("frontmatter") or {}).get("tags")
    _ok(ft == ["b", "c"], f"update_tags 落盘保序（{ft}）")
    # causal md 端到端
    tmp = tempfile.mkdtemp(prefix="wbwp_causal_")
    cg = MdCG(root=tmp)
    eng = _StubEngine([{
        "path_type": "query",
        "description": "用户问「水为什么烧开」检索不到沸点知识",
        "reason": "翻译表缺沸点→沸腾映射", "status": "open",
        "evidence": "wbwp"}])
    cg.add("node_boil", "水的沸点在一标准大气压下为100摄氏度",
           layer="knowledge", importance=0.8, confidence=0.9,
           verification_basis="textbook")
    cd = CausalDiscoverer(eng, cg=cg)
    r = cd.discover(limit=3)
    cands = r.get("candidates") or []
    _ok(len(cands) >= 1, f"discover 产出候选（{len(cands)}）")
    cc_id = (cands[0] or {}).get("candidate_id") or ""
    node = cg.get(cc_id) if cc_id else None
    fm = (node or {}).get("frontmatter") or {}
    _ok(node is not None and fm.get("layer") == "contextual",
        f"候选节点入 md contextual 层（id={cc_id}）")
    ftags = fm.get("tags") or []
    _ok("causal_candidate" in ftags and "status:candidate_open" in ftags,
        "候选 tags 含 causal_candidate/open")
    n_before = len([k for k in cg.index["nodes"] if k.startswith("cc_")])
    cd.discover(limit=3)
    n_after = len([k for k in cg.index["nodes"] if k.startswith("cc_")])
    _ok(n_before == n_after, f"重复 discover 幂等不重建（{n_before}）")
    # 被拒路径置 consumed（信号源状态变更）
    eng._paths[0]["status"] = "consumed"
    r2 = cd.verify_candidates()
    _ok(r2.get("resolved") == 1, f"verify 因果确认 resolved=1（{r2}）")
    fm2 = ((cg.get(cc_id) or {}).get("frontmatter") or {})
    ftags2 = fm2.get("tags") or []
    _ok("status:causal_confirmed" in ftags2
        and "status:candidate_open" not in ftags2,
        "tag 状态迁移（open→confirmed）")
    md = cd._md_conn()
    md.reload()  # verify 内部 has_edge 已建快照，append 后须刷新（读面语义）
    edges = md.edges_between(cc_id, "node_boil", "causal")
    _ok(len(edges) == 1, "causal 边落盘（cc→target，「沸点」词命中）")
    if edges:
        e = edges[0]
        _ok(e.get("verified") == 0.6
            and e.get("source_evidence") == "extracted",
            "边形态 verified=0.6/extracted（对齐引擎语义）")
    r3 = cd.verify_candidates()
    _ok(r3.get("resolved") == 0 and r3.get("tracked") >= 1,
        f"幂等重跑 resolved=0（{r3}）")


def main():
    tmp = tempfile.mkdtemp(prefix="wbwp_md_")
    cg = MdCG(root=tmp)
    print(f"md 真源根: {tmp}")
    test_primitives(cg)
    sp = test_kp_md_mode(cg)
    test_mdconn_edge_domain(cg, sp)
    test_pattern_md_mode()
    test_causal_md_mode()
    cg.flush()
    # flush 后重开实例验证持久化
    cg2 = MdCG(root=tmp)
    sg = (cg2.get("card_test_1").get("frontmatter") or {}).get("subgraph")
    _ok(sg and len(sg.get("nodes") or []) == 2,
        "flush 后重开实例 subgraph 持久化")
    test_sqlite_legacy()
    print(f"\n==== 写路径收口测试: PASS {_PASS} / FAIL {_FAIL} ====")
    sys.exit(1 if _FAIL else 0)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
