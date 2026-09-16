# -*- coding: utf-8 -*-
"""conformance 断言集自测（Pi⑤）。

纪律（吸取 test_p27【9】教训）：**自备数据源，不依赖仓库外目录状态**——
外部 clone（无 docs/experiments、无真源库）下必须同样全绿。故：

* 主测面 = `tempfile` 内**合成库**（确定性、可注入缺陷）→ 验证「注入即检出」；
* 真源库只在**存在时**做一次集成基线复核（不存在则 SKIP，不报 FAIL）。

覆盖：
  A 合成库健康态 → verdict 判定 + strict 语义
  B 五条不变量 fail-closed：类型空间封闭 / 边目标可解析 / 索引↔盘一致 /
    层-目录一致 / 重复度上限（各注入缺陷一次）
  C 边键规范 / 边类型声明 → **WARN 非 FAIL**（读侧兼容，不冒充硬失败）
  D 健康指标 BLINDSPOT（样本不足时不冒充 PASS）
  E G3 unanalyzed 派生判据（四类排除）
  F 基线不劣化：劣化→FAIL、持平→ok
  G 零写入（跑一遍 check 后全库指纹逐字节不变）
  H CLI：坏库 BLINDSPOT 退出码 2 / FAIL 退出码 1 / --json / --baseline / --strict
  I G1 结构完整性（5 空间声明 + 方向分歧 + 文档滞后登记）
  J sustain 挂点（只读、异常不炸、status 透出）

运行：python -m md_cg.test_conformance
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout

from . import conformance as C

PASS = FAIL = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


# ---------------------------- 合成库 ----------------------------

def node(nid, layer="knowledge", **kw):
    rec = {"id": nid, "layer": layer, "path": f"{layer}/{nid}.md",
           "content": f"内容 {nid}", "content_hash": f"hash_{nid}", "tags": []}
    rec.update(kw)
    return rec


DEFAULT_ACCESS = ({"t": 1, "ids": ["n1", "n2"], "tier": "core"},)


def build(root, nodes, *, decisions=None, inbox=None, access=DEFAULT_ACCESS, audit=(),
          write_files=True):
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "_index.json"), "w", encoding="utf-8") as f:
        json.dump({"nodes": nodes}, f, ensure_ascii=False)
    hp = os.path.join(root, "hippocampus")
    os.makedirs(hp, exist_ok=True)
    for name, rows in (("decisions.jsonl", decisions), ("inbox.jsonl", inbox)):
        with open(os.path.join(hp, name), "w", encoding="utf-8") as f:
            for r in rows or []:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(root, "_access.log"), "w", encoding="utf-8") as f:
        for r in access:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(root, "_audit.jsonl"), "w", encoding="utf-8") as f:
        for r in audit:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if write_files:
        for r in nodes.values():
            if not r.get("path"):
                continue
            p = os.path.join(root, r["path"])
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(r.get("content", ""))
    return root


def dec(n, decision="accept"):
    return [{"pid": f"p{i}", "decision": decision} for i in range(n)]


def failing(rep):
    return [c["id"] for c in rep["checks"] if c["level"] == "FAIL" and not c["ok"]]


def warn_no(rep):
    return [c["id"] for c in rep["checks"] if c["level"] == "WARN" and not c["ok"]]


def level_of(rep, cid):
    return next((c["level"] for c in rep["checks"] if c["id"] == cid), None)


def snapshot(root):
    out = {}
    for dp, _, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            with open(p, "rb") as f:
                out[os.path.relpath(p, root)] = hashlib.md5(f.read()).hexdigest()
    return out


# 健康态：knowledge 层三节点 role/basis/evidence 齐备（判据=knowledge 层口径），
# 混层 1/3=33% < 60% 上限，access 覆盖 2/5=40% ≥ 30% 下限，闸门样本 25 ≥ 20
HEALTHY = {
    "n1": node("n1", tags=["doc:note"], role="knowledge-card",
               verification_basis="test", evidence_count=2),
    "n2": node("n2", role="knowledge-card", verification_basis="test",
               evidence_count=3, lifecycle_state="active"),
    "n3": node("n3", layer="contextual"),
    "n4": node("n4", layer="self"),
    "n5": node("n5", role="knowledge-card", verification_basis="textbook"),
}


def main():
    print("== test_conformance: 合成库主测面 ==")
    tmp = tempfile.mkdtemp(prefix="conf_")
    try:
        # ---------- A 健康态 ----------
        r1 = build(os.path.join(tmp, "healthy"), dict(HEALTHY), decisions=dec(25))
        rep = C.check(r1)
        ok(rep["verdict"] == "PASS", f"A1 健康库 verdict=PASS（实得 {rep['verdict']}）")
        ok(not failing(rep), f"A2 健康库无 FAIL（实得 {failing(rep)}）")
        ok(level_of(rep, "stratum.role_coverage") == "BLINDSPOT",
           "A3 样本不足 → 比率指标 BLINDSPOT")
        rep_s = C.check(r1, strict=True)
        ok(rep_s["verdict"] != "PASS", "A4 strict 下 BLINDSPOT 不算 PASS")
        ok(C.check(r1)["counts"] == rep["counts"], "A5 复跑确定性（计数一致）")

        # ---------- B 不变量 fail-closed ----------
        b1 = dict(HEALTHY)
        b1["bad"] = node("bad", layer="不存在的层")
        r2 = build(os.path.join(tmp, "b1"), b1, decisions=dec(25))
        rep = C.check(r2)
        ok("enum.layer.closed" in failing(rep), "B1 层越界 → FAIL enum.layer.closed")
        ok(rep["verdict"] == "FAIL", "B2 有 FAIL → verdict=FAIL")

        b2 = dict(HEALTHY)
        b2["n1"] = node("n1", edges=[{"relation_type": "part_of", "target": "ghost"}])
        r3 = build(os.path.join(tmp, "b2"), b2, decisions=dec(25))
        ok("edge.target.resolvable" in failing(C.check(r3)),
           "B3 悬空边 → FAIL edge.target.resolvable")

        b3 = dict(HEALTHY)
        b3["n1"] = node("n1", path="contextual/n1.md")          # layer=knowledge
        r4 = build(os.path.join(tmp, "b3"), b3, decisions=dec(25))
        ok("index.layer.dir.match" in failing(C.check(r4)),
           "B4 层-目录不一致 → FAIL index.layer.dir.match")

        b4 = dict(HEALTHY)
        b4["n5"] = node("n5", path="")                          # path 缺失
        r5 = build(os.path.join(tmp, "b4"), b4, decisions=dec(25))
        ok("index.path.present" in failing(C.check(r5)),
           "B5 path 缺失 → FAIL index.path.present")

        b5 = dict(HEALTHY)
        b5["n5"] = node("n5", path="knowledge/nowhere.md")      # 盘上不存在
        r6 = build(os.path.join(tmp, "b5"), b5, decisions=dec(25), write_files=False)
        ok("index.path.present" in failing(C.check(r6)),
           "B6 盘上文件不存在 → FAIL index.path.present")
        ok(not failing(C.check(r6, check_paths=False)),
           "B7 --no-path-check 跳过查盘后不报该 FAIL")

        b6 = dict(HEALTHY)
        for i in range(C.DUP_GROUP_MAX + 1):
            b6[f"d{i}"] = node(f"d{i}", content_hash="same")
        r7 = build(os.path.join(tmp, "b6"), b6, decisions=dec(25))
        ok("dup.content.no_blowup" in failing(C.check(r7)),
           f"B8 重复组 > {C.DUP_GROUP_MAX} → FAIL dup.content.no_blowup")

        # ---------- C 边键/边类型 = WARN ----------
        c1 = dict(HEALTHY)
        c1["n1"] = node("n1", edges=[{"type": "part_of", "target": "n2"},
                                     {"relation_type": "causal", "target": "n3"}])
        r8 = build(os.path.join(tmp, "c1"), c1, decisions=dec(25))
        rep = C.check(r8)
        ok(rep["edges"]["non_canonical"] == 1, "C1 legacy type 键计数 =1")
        ok(level_of(rep, "edge.key.canonical") == "WARN", "C2 边键规范判为 WARN")
        ok("edge.key.canonical" not in failing(rep), "C3 边键 legacy 不判 FAIL（读侧兼容）")
        ok("part_of" not in rep["g1"]["edge_type"]["undeclared_used"],
           "C4 已声明边类型不误报")

        c2 = dict(HEALTHY)
        c2["n1"] = node("n1", edges=[{"relation_type": "bogus_rel", "target": "n2"}])
        r9 = build(os.path.join(tmp, "c2"), c2, decisions=dec(25))
        rep = C.check(r9)
        ok("bogus_rel" in rep["g1"]["edge_type"]["undeclared_used"],
           "C5 未声明边类型被 G1 列出")
        ok(level_of(rep, "edge.rel.declared") == "WARN", "C6 未声明边类型判为 WARN")

        # ---------- D 数据源缺失 ----------
        r10 = os.path.join(tmp, "d1")
        build(r10, dict(HEALTHY), decisions=dec(25))
        os.remove(os.path.join(r10, "_access.log"))
        rep = C.check(r10)
        ok(level_of(rep, "reach.ratio") == "BLINDSPOT", "D1 触达日志缺失 → BLINDSPOT")
        ok(rep["reach"]["ratio"] is None, "D2 触达率如实置 None 不猜测")
        r11 = os.path.join(tmp, "d2")
        build(r11, dict(HEALTHY), decisions=[])
        ok(level_of(C.check(r11), "gate.sample") == "WARN", "D3 闸门样本不足 → WARN")

        # ---------- E G3 unanalyzed 派生 ----------
        e1 = {"u1": node("u1"),                                    # 三者皆空 → unanalyzed
              "u2": node("u2", verification_basis="test"),          # 有基底 → 非
              "u3": node("u3", evidence_count=2),                   # 有证据 → 非
              "u4": node("u4", lifecycle_state="converged")}        # 有状态 → 非
        r12 = build(os.path.join(tmp, "e1"), e1, decisions=dec(25))
        un = C.check(r12)["unanalyzed"]
        ok(un["count"] == 1 and un["sample"] == ["u1"],
           f"E1 unanalyzed 派生判据（实得 {un['count']}）")
        ok(C.check(r12)["coverage"]["nodes"] == 4, "E2 节点计数正确")

        # ---------- F 基线不劣化 ----------
        rep_ok = C.check(r1)
        m = C.metrics_of(rep_ok)
        base = {"metrics": dict(m)}
        ok(not [c for c in C.check(r1, baseline=base)["checks"]
                if c["id"].startswith("baseline.") and not c["ok"]],
           "F1 与自身基线比对不劣化")
        base_bad = {"metrics": dict(m, non_canonical=0, mixed_ratio=0.0, unanalyzed=0)}
        bad = [c["id"] for c in C.check(r8, baseline=base_bad)["checks"]
               if c["id"].startswith("baseline.") and not c["ok"]]
        ok("baseline.non_canonical" in bad, "F2 非规范边劣化 → FAIL 基线项")
        ok(all(c["id"] in m for c in [{"id": k} for k in
                                      ("mixed_ratio", "non_canonical", "dangling",
                                       "dup_groups", "unanalyzed")]),
           "F3 比对键 ⊆ metrics_of 输出（无键名漂移）")
        ok("reach_ratio" in m, "F4 触达率入基线存档")

        # ---------- G 零写入 ----------
        r13 = build(os.path.join(tmp, "g1"), dict(HEALTHY), decisions=dec(25))
        before = snapshot(r13)
        C.check(r13)
        C.check(r13, strict=True)
        C.report_summary(r13)
        after = snapshot(r13)
        ok(before == after, "G1 跑三遍后全库指纹逐字节不变（只读零写入）")

        # ---------- H CLI ----------
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc_bad = C.main(["--root", os.path.join(tmp, "nonexistent")])
        out = buf.getvalue()
        ok(rc_bad == 2, "H1 坏库退出码 2（BLINDSPOT 非 PASS）")
        ok("BLINDSPOT" in out and "缺失维度" in out, "H2 坏库输出含缺失维度提示")
        with redirect_stdout(io.StringIO()):
            rc_fail = C.main(["--root", r2])
        ok(rc_fail == 1, "H3 verdict=FAIL 退出码 1")
        jp = os.path.join(tmp, "out.json")
        bp = os.path.join(tmp, "base.json")
        with redirect_stdout(io.StringIO()):
            rc_ok = C.main(["--root", r1, "--json", jp, "--write-baseline", bp])
        ok(rc_ok == 0, "H4 健康库退出码 0")
        ok(json.load(open(jp, encoding="utf-8"))["verdict"] == "PASS", "H5 --json 落盘可用")
        ok("metrics" in json.load(open(bp, encoding="utf-8")), "H6 --write-baseline 落盘可用")
        with redirect_stdout(io.StringIO()):
            rc_cmp = C.main(["--root", r1, "--baseline", bp])
        ok(rc_cmp == 0, "H7 --baseline 比对通路可用")

        # ---------- I G1 结构 ----------
        sp = C.enum_spaces()
        ok(set(sp) == {"layer", "edge_type", "derived_relation",
                       "verification_basis", "lifecycle_state"},
           f"I1 五个类型空间齐备（实得 {sorted(sp)}）")
        ok(all(v["declared"] and v["source"] for v in sp.values()),
           "I2 每空间都有声明值 + 模块真源")
        ok("knowledge" in sp["layer"]["declared"], "I3 layer 真源含 knowledge")
        g1 = C.check(r1)["g1"]
        ok(set(("_direction_conflicts", "_verified_consistent", "_doc_code_drift",
                "_cross_space_overlap", "_new_type_touchpoints")) <= set(g1),
           "I4 G1 汇总字段齐备")
        ok(g1["role"]["declared"] is None and g1["role"]["closed"] is None,
           "I5 无真源空间（role）标 None→BLINDSPOT 不冒充封闭")
        ok("hierarchical" in [d["literal"] for d in g1["_direction_conflicts"]],
           "I6 方向口径分歧已登记")
        ok(sp["edge_type"]["declared"] and "part_of" in sp["edge_type"]["declared"],
           "I7 边类型真源可用")

        # ---------- J sustain 挂点 ----------
        from . import sustain as S
        ok(hasattr(S.SustainLoop, "_tick_conformance"), "J1 SustainLoop 有 conformance 挂点")
        loop = S.SustainLoop(type("CG", (), {"root": r1})(), name="t_conf", d=tmp)
        loop._tick_conformance()
        ok(loop.last_conformance["ok"] is True, "J2 挂点跑通且 ok=True")
        ok("last_conformance" in loop.status(), "J3 status 透出结论")
        loop2 = S.SustainLoop(type("CG", (), {"root": os.path.join(tmp, "nope")})(),
                              name="t_conf2", d=tmp)
        loop2._tick_conformance()
        ok(loop2.last_conformance["ok"] is False
           and loop2.last_conformance["verdict"] == "BLINDSPOT",
           "J4 坏库不抛异常、如实标 BLINDSPOT")
        ok(C.report_summary(os.path.join(tmp, "nope2"))["verdict"] == "BLINDSPOT",
           "J5 显式坏路径 report_summary 不炸且如实 BLINDSPOT")

        # ---------- 集成（真源存在才跑，缺失即 SKIP）----------
        real = "D:/Program Files/2_ai/AEIS/data/mdcg"
        if os.path.exists(os.path.join(real, "_index.json")):
            rp = C.check(real, check_paths=False)
            cv = rp["coverage"]
            print(f"  [集成] 真源 nodes={rp['nodes']} 混层比={cv['mixed_ratio'] * 100:.1f}%"
                  f" dir_mismatch={rp['paths']['layer_mismatch']}"
                  f" 闸门={rp['gate']['decisions_total']} verdict={rp['verdict']}")
            ok(rp["nodes"] > 5000, "K1 真源节点数 > 5000")
            ok(0.50 <= cv["mixed_ratio"] <= 0.65,
               f"K2 混层比复现 9-15 基线 58.4%（实得 {cv['mixed_ratio'] * 100:.1f}%）")
            ok(rp["paths"]["layer_mismatch"] == 0, "K3 层-目录一致 = 0（9-15 基线）")
            ok(rp["gate"]["decisions_total"] >= 100, "K4 闸门样本 ≥ 100")
            ok(cv["role_ratio"] < 0.10, "K5 role 覆盖率仍处治理区（<10%）")
        else:
            print("  [集成] SKIP 真源库不存在（外部 clone 正常情形）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nPASS={PASS} FAIL={FAIL}")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print("  -", f)
        return 1
    print("conformance 断言集自测全绿。")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
