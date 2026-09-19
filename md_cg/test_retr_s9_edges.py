# -*- coding: utf-8 -*-
"""S9 三元组反查原语探针（阶段二 4.2，脚本式，exit code 定成败）。

用法：python -X utf8 -m md_cg.test_retr_s9_edges
覆盖：
- 纯函数：ordering/aggregation 封闭枚举、按轴取边窗（边只有观察轴 `t`）、
  模式分叉、端点摘要（索引级零读盘）
- 谓词反查：child / parent / relation / batch 与 `edges()` 同源同义
- 时间条件：缺省轴 = observed（**与 search 缺省 effective 有意不同**）、
  observed fail-closed（缺 `t` 剔除并计入 axis_missing）、
  effective 在边上 fail-open（如实 no-op，不是静默错答）
- 排序 / 分页 / 聚合：聚合基于**分页前全集**（分页不漂移）
- fail-closed 清单：非法枚举 / offset<0 / limit<=0 / limit>上限 /
  非法 relation / 孤算子 / 逆序窗 / 非法轴
- 零回归：`provenance.edges()` 逐位不变；反查**不写盘**（台账字节不变）

语料（6 条固定边 + 1 条索引兜底边）：
  写路径 3：a1→p1(derived_from) a2→p1(extracted_from) a3→p2(merged_from)
  显式 t 3：e1→p1 t=1000 batch=b1 / e2→p1 t=2000 batch=b1 / e3→p2 t=3000 batch=b2 refined_from
  索引兜底 1：ghost→p2（台账行被摘除 → 只能从 frontmatter 恢复，**无 t**）
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import fsutil, provenance                        # noqa: E402
from md_cg.mdcg import MdCG                                 # noqa: E402

passed = 0
failed = 0
T = "阿尔法 三元组 反查 探针"
#: 写路径 3 条边的真实写入时刻（time.time()）远大于显式 t（1000~3000）
_NOW = ("a1", "a2", "a3")


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + detail)


def _raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    except Exception:                                       # noqa: BLE001
        return False
    return False


def _ids(res):
    return [e.get("child") for e in res["edges"]]


def _build(root):
    cg = MdCG(root)
    for nid in ("p1", "p2"):
        cg.add(nid, T, "knowledge")
    cg.add("a1", T, "knowledge", derived_from=["p1"])
    cg.add("a2", T, "knowledge", derived_from=["p1"], relation="extracted_from")
    cg.add("a3", T, "knowledge", derived_from=["p2"], relation="merged_from")
    cg.flush()
    # 显式 t 的 3 条边（record() 不接 t，直接 make_edge + append）
    provenance.append(root, [
        provenance.make_edge("e1", "p1", relation="derived_from",
                             batch="b1", actor="t-actor", t=1000.0),
        provenance.make_edge("e2", "p1", relation="derived_from",
                             batch="b1", actor="t-actor", t=2000.0),
        provenance.make_edge("e3", "p2", relation="refined_from",
                             batch="b2", actor="t-actor", t=3000.0),
    ])
    return cg


def _strip_ledger(root, child):
    """摘掉某个 child 的台账行 → 该边只能由 frontmatter（索引）恢复。"""
    p = provenance.ledger_file(root)
    rows = [r for r in fsutil.read_jsonl(p) if r.get("child") != child]
    fsutil.atomic_write(p, "".join(
        json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n"
        for r in rows))


def main():
    # ================= 1) 纯函数层 =================
    check("ordering 归一：None/空白 → desc；大小写归一；未知抛 ProvenanceError",
          provenance._ordering_of(None) == "desc"
          and provenance._ordering_of("  ") == "desc"
          and provenance._ordering_of("ASC") == "asc"
          and _raises(provenance.ProvenanceError,
                      lambda: provenance._ordering_of("up")),
          str(provenance.ORDERINGS))

    check("aggregation 归一：None/空白 → None（不聚合）；大小写归一；未知抛错",
          provenance._aggregation_of(None) is None
          and provenance._aggregation_of("BY_PARENT") == "by_parent"
          and _raises(provenance.ProvenanceError,
                      lambda: provenance._aggregation_of("by_actor")),
          str(provenance.AGGREGATIONS))

    check("边取窗：observed 用 t（单点窗）；缺 t 不可判定；effective 一律不可判定",
          provenance._edge_window({"t": 100}, "observed") == (100.0, 100.0, False)
          and provenance._edge_window({}, "observed") == (None, None, True)
          and provenance._edge_window({"t": 100}, "effective") == (None, None, True))

    check("模式分叉：无算子=overlap；任一端算子=endpoint",
          provenance._mode_of(None, None) == "overlap"
          and provenance._mode_of("gte", None) == "endpoint"
          and provenance._mode_of(None, "lte") == "endpoint")

    # ================= 2) 建库 + 基线 =================
    root = tempfile.mkdtemp(prefix="retr_s9_")
    cg = _build(root)
    ledger_bytes = open(provenance.ledger_file(root), "rb").read()

    d = provenance._node_digest(cg, "p1")
    check("端点摘要：在索引内 present=True 且带 layer；缺失 present=False（不猜）",
          d.get("present") is True and d.get("layer") == "knowledge"
          and provenance._node_digest(cg, "no_such")["present"] is False,
          str(d))

    r0 = provenance.find_edges(cg)
    check("基线：无过滤 → total=6 / matched=6 / returned=6、只读、默认 desc + limit 50",
          r0["ok"] is True and r0["readonly"] is True and r0["op"] == "edges"
          and r0["total"] == 6 and r0["matched"] == 6 and r0["returned"] == 6
          and r0["ordering"] == "desc" and r0["limit"] == 50 and r0["offset"] == 0,
          str({k: r0[k] for k in ("total", "matched", "returned", "limit")}))
    check("基线：默认排序 desc → 写路径边（真实 t）在前、显式 t 边倒序在后",
          set(_ids(r0)[:3]) == set(_NOW)
          and _ids(r0)[3:] == ["e3", "e2", "e1"], str(_ids(r0)))
    check("基线：未启用时间条件 → 审计块 applied=False 且不虚报 dropped",
          (r0["time_filter"] or {}).get("applied") is False
          and (r0["time_filter"] or {}).get("dropped") == 0
          and r0["aggregates"] is None and r0["nodes_expanded"] is False,
          str(r0["time_filter"]))

    # ================= 3) 谓词反查（与 edges() 同源同义）=================
    check("按任意端 / 谓词 / 批次反查：child / parent / relation / batch 各自等值过滤",
          provenance.find_edges(cg, child="a1")["total"] == 1
          and provenance.find_edges(cg, parent="p1")["total"] == 4
          and provenance.find_edges(cg, relation="derived_from")["total"] == 3
          and provenance.find_edges(cg, batch="b1")["total"] == 2
          and provenance.find_edges(cg, parent="p1",
                                    relation="derived_from")["total"] == 3,
          "%s/%s" % (provenance.find_edges(cg, parent="p1")["total"],
                     provenance.find_edges(cg, relation="derived_from")["total"]))
    check("复合谓词：child+parent+relation 三键同时约束（交集语义）",
          provenance.find_edges(cg, child="e1", parent="p1",
                                relation="derived_from")["total"] == 1
          and provenance.find_edges(cg, parent="p1",
                                    relation="merged_from")["total"] == 0)

    # ================= 4) 时间条件（缺省轴 observed）=================
    rt = provenance.find_edges(cg, start_time=2500, end_time=3500)
    check("缺省轴=observed（**不是** search 的 effective）：窗内只剩 e3、窗外全部剔除",
          _ids(rt) == ["e3"] and rt["matched"] == 1 and rt["total"] == 6,
          str(_ids(rt)))
    check("时间审计块：axis/mode/applied 正确，dropped + matched == total（可复算）",
          rt["time_filter"]["axis"] == "observed"
          and rt["time_filter"]["mode"] == "overlap"
          and rt["time_filter"]["applied"] is True
          and rt["time_filter"]["dropped"] == 5
          and rt["time_filter"]["dropped"] + rt["matched"] == rt["total"],
          str(rt["time_filter"]))

    re_ = provenance.find_edges(cg, start_time=2000, start_operator="gte")
    check("端点模式：单端 gte 只筛起点侧（e1 剔除、e2/e3 与写路径边保留）",
          "e1" not in _ids(re_) and "e2" in _ids(re_) and "e3" in _ids(re_)
          and re_["matched"] == 5 and re_["time_filter"]["mode"] == "endpoint"
          and re_["time_filter"]["dropped"] == 1
          and re_["time_filter"]["start_operator"] == "gte",
          str(_ids(re_)))

    ra = provenance.find_edges(cg, time_axis="effective",
                               start_time=2500, end_time=3500)
    check("边在效力轴无字段 → fail-open 如实 no-op（dropped=0 且 applied=True，不冒充过滤成功）",
          ra["matched"] == 6 and ra["time_filter"]["axis"] == "effective"
          and ra["time_filter"]["dropped"] == 0
          and ra["time_filter"]["applied"] is True,
          str(ra["time_filter"]))

    # ================= 5) 排序 / 分页 / 聚合 =================
    rasc = provenance.find_edges(cg, ordering="asc")
    check("排序 asc：显式 t 边正序在前（t 全序），与 desc 严格互反",
          _ids(rasc)[:3] == ["e1", "e2", "e3"]
          and _ids(rasc) == list(reversed(_ids(r0))), str(_ids(rasc)))

    rpg = provenance.find_edges(cg, limit=2, offset=1)
    check("分页：limit/offset 作用于排序后序列（offset=1 limit=2 → 取第 2、3 位）",
          rpg["returned"] == 2 and rpg["matched"] == 6
          and _ids(rpg) == _ids(r0)[1:3], str(_ids(rpg)))

    rag = provenance.find_edges(cg, aggregation="by_parent", limit=1)
    check("聚合 by_parent：基于**分页前全集**分桶（p1=4 / p2=2，limit 不缩水计数）",
          rag["returned"] == 1 and rag["aggregation"] == "by_parent"
          and [(b["key"], b["count"]) for b in rag["aggregates"]]
          == [("p1", 4), ("p2", 2)],
          str(rag["aggregates"]))
    check("聚合 by_relation / by_child：谓词分布与逐 child 计数正确",
          [(b["key"], b["count"]) for b in
           provenance.find_edges(cg, aggregation="by_relation")["aggregates"]]
          == [("derived_from", 3), ("extracted_from", 1), ("merged_from", 1),
              ("refined_from", 1)]
          and all(b["count"] == 1 for b in provenance.find_edges(
              cg, aggregation="by_child")["aggregates"]))

    rex = provenance.find_edges(cg, expand_nodes=True, child="e1")
    check("expand：端点摘要 present 与索引一致（p1 在库 / e1 只是台账 child 不在库）；边为副本不污染源",
          len(rex["edges"]) == 1
          and rex["edges"][0]["parent_node"]["present"] is True
          and rex["edges"][0]["child_node"]["present"] is False
          and rex["nodes_expanded"] is True
          and "child_node" not in provenance.all_edges(cg)[0],
          str(rex["edges"][0].get("child_node")))

    # ================= 6) 索引兜底边（无 t）与 observed 策略联动 =================
    cg.add("ghost", T, "knowledge", derived_from=["p2"])
    _strip_ledger(root, "ghost")
    rg = provenance.find_edges(cg)
    ghost = [e for e in rg["edges"] if e.get("child") == "ghost"]
    check("台账缺行的边由索引恢复（origin=index、无 t 字段）——反查覆盖台账 ∪ 索引",
          len(ghost) == 1 and ghost[0].get("origin") == "index"
          and "t" not in ghost[0] and rg["total"] == 7, str(ghost))

    rgt = provenance.find_edges(cg, start_time=2500, end_time=3500)
    check("观察轴 fail-closed：无 t 的索引兜底边不可判定 → 剔除并计入 axis_missing",
          rgt["matched"] == 1 and rgt["time_filter"]["axis_missing"] == 1
          and rgt["time_filter"]["dropped"] == 6
          and rgt["time_filter"]["dropped"] + rgt["matched"] == rgt["total"] == 7,
          str(rgt["time_filter"]))

    # ================= 7) fail-closed 清单 =================
    P = provenance.ProvenanceError
    check("入参 fail-closed：非法 ordering / aggregation / relation",
          _raises(P, lambda: provenance.find_edges(cg, ordering="up"))
          and _raises(P, lambda: provenance.find_edges(cg, aggregation="by_actor"))
          and _raises(P, lambda: provenance.find_edges(cg, relation="bogus")))
    check("分页 fail-closed：offset<0 / limit<=0 / limit>上限（0 不当「全部」）",
          _raises(P, lambda: provenance.find_edges(cg, offset=-1))
          and _raises(P, lambda: provenance.find_edges(cg, limit=0))
          and _raises(P, lambda: provenance.find_edges(cg, limit=501)),
          "MAX=%s" % provenance.MAX_FIND_LIMIT)
    check("时间误用 fail-closed（复用 trust.check_time_args 唯一校验点）：孤算子 / 逆序 / 非法轴",
          _raises(P, lambda: provenance.find_edges(cg, start_operator="gte"))
          and _raises(P, lambda: provenance.find_edges(cg, start_time=3000,
                                                       end_time=1000))
          and _raises(P, lambda: provenance.find_edges(cg, time_axis="believed"))
          and _raises(P, lambda: provenance.find_edges(cg, start_time=1000,
                                                       time_axis="believed")))

    # ================= 8) 零回归 + 只读性 =================
    legacy = provenance.edges(root)
    check("零回归：provenance.edges()（台账口径）逐位不变——写入顺序、6 条，新原语未改动它",
          len(legacy) == 6
          and [e.get("child") for e in legacy]
          == ["a1", "a2", "a3", "e1", "e2", "e3"],
          str([e.get("child") for e in legacy]))
    check("口径分层：edges()=台账only(6) vs all_edges()=台账∪索引(7)，差异只在索引兜底边",
          len(provenance.all_edges(cg)) == 7
          and {e.get("child") for e in provenance.all_edges(cg)}
          - {e.get("child") for e in legacy} == {"ghost"})
    # 台账在 §6 被有意摘行，故此处**重新快照**再比较（对比 §2 快照是错的）
    snap = open(provenance.ledger_file(root), "rb").read()
    provenance.find_edges(cg, expand_nodes=True, aggregation="by_relation")
    provenance.find_edges(cg, start_time=1000, end_time=9000)
    provenance.find_edges(cg, limit=3, offset=2, ordering="asc")
    check("只读性：全部反查调用后台账字节不变（含 expand / 聚合 / 时间路径）",
          open(provenance.ledger_file(root), "rb").read() == snap and len(snap) > 0,
          "ledger=%s" % provenance.ledger_file(root))

    print("\ntest_retr_s9: %d 通过 / %d 失败" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
