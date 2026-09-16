# -*- coding: utf-8 -*-
"""M1 机械层自测：候选生成 → 捆绑 → 规则装配（确定性、零写入）。

真源：docs/记忆评审系统_立项设计与施工交接_20260915.md §3 前三级 / §5 D3 / §6。
纪律（吸取 test_p27【9】教训）：**自备数据源**——主测面 = tempfile 合成库；
真源库仅在**存在时**做集成复核（不存在即 SKIP，外部 clone 下同样全绿）。

覆盖：A 级1 四源/分源开关/同口径交叉核对/轮巡不重不漏/确定性
      B 级2 模板一包一评/包号确定性/降级/正文回读/切分/血缘/主题
      C 级3 规则库加载与非法库 fail-closed/matcher 语义/六检查器/数据化零代码改动
      D CLI run/--out/--full/零写入   E 集成:真源存在才跑（审计基线口径）

运行：python -m md_cg.test_mr_m1
"""
from __future__ import annotations

import collections
import hashlib
import io
import json
import os
import sys
import tempfile
import shutil
from contextlib import redirect_stdout

from . import conformance as CF
from .mreview import __main__ as CLI
from .mreview import bundle as BD
from .mreview import candidates as CD
from .mreview import ruleset as RS

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


def mkroot(root, nodes, *, access=(), inbox=(), decisions=(), forgetting=(),
           contents=None, write_files=True):
    """合成认知图根：索引 + 闸门三日志 + 节点盘文件。"""
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "_index.json"), "w", encoding="utf-8") as f:
        json.dump({"nodes": nodes}, f, ensure_ascii=False)
    hp = os.path.join(root, "hippocampus")
    os.makedirs(hp, exist_ok=True)
    for name, rows in (("inbox.jsonl", inbox), ("decisions.jsonl", decisions)):
        with open(os.path.join(hp, name), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(root, CF.ACCESS_LOG), "w", encoding="utf-8") as f:
        for r in access:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(root, CD.FORGET_LOG), "w", encoding="utf-8") as f:
        for r in forgetting:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if write_files:
        for r in nodes.values():
            if not r.get("path"):
                continue
            p = os.path.join(root, r["path"])
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write((contents or {}).get(r["id"], r.get("content", "")))
    return root


# 运行态目录：由常驻进程（MCP server 等）按自身节拍 flush 增量日志，与 M1 无关。
# 取证（第4条）：静置 6s 真源无变化，跑 M1 前后 _index_log/ 无新文件、逐字节不变；
# 目录内文件名带写入者 pid（14916/16072/20184/6708），非本进程 pid。
VOLATILE_DIRS = ("_index_log",)


def snapshot(root, *, exclude_dirs=()):
    """记忆数据面指纹；exclude_dirs 只用于剔除运行态目录（排除面显式、有据）。"""
    ex = set(exclude_dirs)
    out = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in ex]
        for fn in fns:
            p = os.path.join(dp, fn)
            with open(p, "rb") as f:
                out[os.path.relpath(p, root)] = hashlib.md5(f.read()).hexdigest()
    return out


def _diff(before, after):
    ch = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    return "改=%s 增=%s 删=%s" % (ch[:5], sorted(set(after) - set(before))[:5],
                                sorted(set(before) - set(after))[:5])


# 引擎默认 issue_kind（规则 JSON 未显式声明 issue_kind 时的契约值）
_DEFAULT_KIND = {"field_absent": "missing_field", "evidence_zero": "missing_field",
                 "field_ratio_below": "package_ratio", "dup_hash_group": "dup_content",
                 "template_flow_digits_only": "template_flow", "basis_licensed": "weak_source"}


def declared_kinds():
    """规则库声明的 issue_kind 全集——机械分类不得越出此界。"""
    ks = set()
    for r in RS.load_rules()["rules"]:
        for s in (r.get("mechanical") or []):
            ks.add(s.get("issue_kind") or _DEFAULT_KIND.get(s.get("check"), s.get("check")))
    return ks


def rows_of(bundles):
    return [e for b in bundles for e in b["entries"]]


# A 组语料：knowledge 4（k1 三缺、k3/k4 同指纹）、contextual 1、self 1（legacy 边）
A_NODES = {
    "k1": node("k1", role=None, evidence_count=0, verification_basis="", tags=["doc:note"]),
    "k2": node("k2", role="knowledge-card", evidence_count=2, verification_basis="test"),
    "k3": node("k3", role="knowledge-card", evidence_count=1, verification_basis="test",
               content_hash="dup"),
    "k4": node("k4", role="knowledge-card", evidence_count=1, verification_basis="test",
               content_hash="dup"),
    "c1": node("c1", layer="contextual"),
    "s1": node("s1", layer="self", importance=0.9,
               edges=[{"type": "part_of", "target": "k2"}]),
}
A_ACCESS = ({"t": 1, "ids": ["k2", "c1"], "tier": "core"},)
TMPL = "# 功能名：批次%d收官记忆\n\n内容各不相同 %d"


def _count(items, kind):
    return sum(1 for i in items if i.get("issue_kind") == kind)


# ---------------------------- A 级 1：候选生成 ----------------------------

def phase_a(tmp):
    print("[A] 级 1 候选生成")
    rA = mkroot(os.path.join(tmp, "a"), dict(A_NODES), access=A_ACCESS)
    nodesA = dict(A_NODES)

    gen = CD.generate(rA, nodes=nodesA, now=0.0, patrol_offset=0)
    kinds = {c["key"]: c["issue_kinds"] for c in gen["candidates"]}
    ok(gen["by_source"]["assertion"] > 0 and gen["total"] > 0, "A1 断言源产出候选")
    ok({"missing_field", "mixed_layer", "unanalyzed"} <= set(kinds.get("k1", [])),
       f"A2 k1 三问题聚合一条候选（实得 {kinds.get('k1')}）")
    ok("dup_content" in kinds.get("k3", []) and "dup_content" in kinds.get("k4", []),
       "A3 同指纹两条都进候选")

    items = CD._assertion_items(nodesA)
    kn = {n: r for n, r in nodesA.items() if str(r.get("layer")) == "knowledge"}
    cov = CF._coverage_metrics(nodesA)
    n_role = _count([i for i in items if "role" in i["evidence"]], "missing_field")
    n_ev = _count([i for i in items if "evidence_count" in i["evidence"]], "missing_field")
    ok(n_role == round((1 - cov["role_ratio_kn"]) * len(kn)),
       f"A4 role 条目数 == 覆盖率反推（实得 {n_role}）")
    ok(n_ev == round((1 - cov["evidence_ratio_kn"]) * len(kn)),
       f"A5 evidence 条目数 == 覆盖率反推（实得 {n_ev}）")
    ok(_count(items, "mixed_layer") == cov["mixed_layer"],
       "A6 混层条目数 == conformance.stratum.mixed_ratio 分子")
    ok(_count(items, "dup_content") == CF._dup_metrics(nodesA)["nodes"],
       "A7 重复条目数 == conformance.dup 涉及节点数")
    ok(_count(items, "unanalyzed") == CF.unanalyzed(nodesA)["count"],
       "A8 unanalyzed 条目数 == conformance 派生判据")
    ok(_count(items, "unanalyzed") == 3,
       f"A9 unanalyzed 全库口径展开=3（实得 {_count(items, 'unanalyzed')}）")

    only = CD.generate(rA, sources=("assertion",), nodes=nodesA, now=0.0)
    ok(set(only["by_source"]) == {"assertion"}, "A10 分源开关生效（只跑断言源）")

    cold = CD.generate(rA, sources=("cold",), nodes=nodesA, now=0.0, cold_limit=10)
    cids = {c["node_id"] for c in cold["candidates"]}
    ok("s1" in cids and "k2" not in cids and "c1" not in cids,
       f"A11 冷节点=未触达且 importance≥0.6（实得 {sorted(cids)}）")
    ok(all(c["issue_kinds"] == ["cold"] for c in cold["candidates"]), "A12 冷节点候选仅带 cold")

    p8 = {f"p{i}": node(f"p{i}", importance=0.5) for i in range(8)}
    w0, w1 = CD._patrol_items(p8, 2, 0), CD._patrol_items(p8, 2, 1)
    s0, s1 = {x["node_id"] for x in w0}, {x["node_id"] for x in w1}
    ok(len(s0) == 2 and len(s1) == 2 and not (s0 & s1), "A13 轮巡相邻窗口不重")
    ok({x["node_id"] for x in CD._patrol_items(p8, 2, 0)} == s0, "A14 轮巡同 offset 可复现")
    ok({x["node_id"] for x in CD._patrol_items(p8, 2, 4)} == s0,
       "A15 轮巡整除时环绕回起点（窗口不重不漏闭合）")
    ok(len({x["node_id"] for x in CD._patrol_items(p8, 3, 2)}) == 3,
       "A16 轮巡非整除窗口内不重（环绕补足）")
    ok(all(x["node_id"] in p8 for x in CD._patrol_items(p8, 2, 1)), "A17 轮巡条目不越界")

    rD = mkroot(os.path.join(tmp, "defer"), dict(A_NODES), access=A_ACCESS,
                inbox=[{"pid": "p1", "id": "k1", "layer": "knowledge",
                        "content": "提案正文", "tags": ["doc:x"], "payload_hash": "h1"},
                       {"pid": "p2", "id": "k2", "layer": "knowledge"}],
                decisions=[{"pid": "p2", "decision": "accept"}],
                forgetting=[{"verdict": "DEFER", "node_id": "ghost", "reason": "证据不足"},
                            {"verdict": "DEFER", "node_id": "k2", "reason": "冲突"},
                            {"verdict": "DROP", "node_id": "k3", "reason": "无关"}])
    dq = CD.generate(rD, sources=("defer_queue",), nodes=dict(A_NODES), now=0.0)
    pids = {c.get("proposal_id") for c in dq["candidates"]}
    ok("p1" in pids and "p2" not in pids,
       f"A18 被 decisions 覆盖的提案不入候选（实得 {sorted(x for x in pids if x)}）")
    ok(any(c["node_id"] == "k2" and c["origin"] == "node" for c in dq["candidates"]),
       "A19 遗忘日志 DEFER 且节点在库 → 入候选")
    ok(any(s["reason"] == "node_not_landed" for s in dq["skipped"]),
       "A20 未落盘 DEFER 计入 skipped 不冒充候选")
    ok("k3" not in {c["node_id"] for c in dq["candidates"]}, "A21 非 DEFER 裁决不入候选")

    g1 = CD.generate(rA, nodes=nodesA, now=0.0, patrol_offset=0)
    g2 = CD.generate(rA, nodes=nodesA, now=0.0, patrol_offset=0)
    ok([c["key"] for c in g1["candidates"]] == [c["key"] for c in g2["candidates"]],
       "A22 候选顺序确定性")
    ok(json.dumps(g1, ensure_ascii=False, sort_keys=True)
       == json.dumps(g2, ensure_ascii=False, sort_keys=True), "A23 候选全量逐字节确定")
    pri = [c["priority"] for c in g1["candidates"]]
    ok(pri == sorted(pri), "A24 候选按优先级排序（assertion<defer<cold<patrol）")

    wr = CD.generate(rA, nodes=nodesA, now=0.0, with_report=True)
    rep = CF.check(rA, check_paths=False)
    ok(wr["assertions"]["verdict"] == rep["verdict"], "A25 with_report verdict 与 conformance 同源")
    ok(wr["report"] == CF.metrics_of(rep), "A26 with_report 指标与 metrics_of 同源")
    ok(set(CD.SOURCES) == {"assertion", "defer_queue", "cold", "patrol"}, "A27 四源齐备")
    ok("report" not in gen and "report" in wr, "A28 报告 opt-in（默认不产出）")


# ---------------------------- B 级 2：捆绑 ----------------------------

def _cand(key, tags=(), kinds=("cold",), content=""):
    return {"key": key, "node_id": key, "tags": list(tags),
            "issue_kinds": list(kinds), "evidence": [], "content": content}


def phase_b(tmp):
    print("[B] 级 2 捆绑")
    bnodes = {f"t{i}": node(f"t{i}", tags=["batch:report"]) for i in range(3)}
    bcands = [_cand(f"t{i}", ["batch:report"], content=TMPL % (i, i)) for i in range(3)]
    rB = mkroot(os.path.join(tmp, "b"), bnodes, access=())
    bd = BD.bundle(bcands, nodes=bnodes, root=rB)
    ok(len(bd["bundles"]) == 1 and bd["bundles"][0]["group_kind"] == "template",
       f"B1 同模板组一包一评（实得 {[b['group_kind'] for b in bd['bundles']]}）")
    ok(bd["bundles"][0]["size"] == 3, "B2 同模板三条并入一包")
    ok(bd["bundles"][0]["group_sig_kind"] == "strong", "B3 标签题命中强模板签名 t:")
    bd2 = BD.bundle(bcands, nodes=bnodes, root=rB)
    ok(json.dumps(bd, ensure_ascii=False, sort_keys=True)
       == json.dumps(bd2, ensure_ascii=False, sort_keys=True), "B4 包号与内容逐字节确定")
    ok(len({b["bundle_id"] for b in bd["bundles"]}) == len(bd["bundles"]), "B5 包号唯一")

    one = BD.bundle(bcands[:1], nodes=bnodes, root=rB)
    ok(len(one["bundles"]) == 1 and one["bundles"][0]["group_kind"] == "batch",
       "B6 单条模板组降级并入 batch（不误聚）")

    lnodes = {"l1": node("l1", branch_id="br1"), "l2": node("l2", branch_id="br1"),
              "l3": node("l3", branched_from="br1")}
    rL = mkroot(os.path.join(tmp, "lin"), lnodes, access=(), write_files=False)
    lbd = BD.bundle([_cand(k, content="") for k in lnodes], nodes=lnodes, root=rL)
    ok(len(lbd["bundles"]) == 1 and lbd["bundles"][0]["group_kind"] == "lineage",
       f"B7 同血缘成一组（实得 {[b['group_kind'] for b in lbd['bundles']]}）")

    tnodes = {"q1": node("q1", tags=["goal:alpha"]), "q2": node("q2", tags=["goal:beta"]),
              "q3": node("q3", tags=["vision:gamma"]), "q4": node("q4", tags=["vision:delta"])}
    rT = mkroot(os.path.join(tmp, "topic"), tnodes, access=(), write_files=False)
    tbd = BD.bundle([_cand(k, tnodes[k]["tags"], content="") for k in tnodes],
                    nodes=tnodes, root=rT)
    ok(len(tbd["bundles"]) == 2 and all(b["group_kind"] == "topic" for b in tbd["bundles"]),
       f"B8 不同主题前缀分属不同 topic 组（实得 {[b['group_kind'] for b in tbd['bundles']]}）")
    ok(sorted(tbd["stats"]["by_group_kind"].items()) == [("topic", 2)],
       f"B8b 同主题两条合包、异主题分属（实得 {tbd['stats']['by_group_kind']}）")

    big = {f"x{i}": node(f"x{i}") for i in range(60)}
    bigc = [_cand(k, content=TMPL % (i, i)) for i, k in enumerate(big)]
    rG = mkroot(os.path.join(tmp, "big"), big, access=())
    gb = BD.bundle(bigc, nodes=big, root=rG, max_per_bundle=50)
    ok(len(gb["bundles"]) == 2 and gb["stats"]["largest"] == 50,
       f"B9 超 max_per_bundle 切分（实得 {[b['size'] for b in gb['bundles']]}）")
    ok(sum(b["size"] for b in gb["bundles"]) == 60, "B10 切分后条目总数守恒")

    cnodes = {"z1": node("z1", content="盘上正文甲")}
    zbd = BD.bundle([_cand("z1", content="")], nodes=cnodes,
                    root=mkroot(os.path.join(tmp, "cont"), cnodes, access=()))
    ex = zbd["bundles"][0]["entries"][0]["excerpt"]
    ok(ex and "盘上正文甲" in ex, "B11 索引无正文时按 path 回读盘上正文")
    ok(zbd["content_missing"] == 0, "B12 回读成功 → content_missing=0")

    rN = mkroot(os.path.join(tmp, "nocont"), cnodes, access=(), write_files=False)
    nbd = BD.bundle([_cand("z1", content="")], nodes=cnodes, root=rN)
    ok(nbd["content_missing"] == 1 and nbd["bundles"][0]["entries"][0]["excerpt"] is None,
       "B13 读盘失败 → content_missing 如实计数、excerpt 置 None")

    e0 = zbd["bundles"][0]["entries"][0]
    ok({"ref", "node_id", "layer", "role", "evidence_count", "verification_basis",
        "issue_kinds"} <= set(e0), "B14 条目字段面含机械检查所需全部字段")
    ok(all(r in {c["key"] for c in bcands} for b in bd["bundles"] for r in b["refs"]),
       "B15 包内 refs ⊆ 候选集（不凭空造条目）")
    ok(bd["stats"]["bundles"] == len(bd["bundles"])
       and bd["stats"]["candidates"] == len(bcands), "B16 stats 与实际一致")


# ---------------------------- C 级 3：规则装配 ----------------------------

def _mkpkg(entries, kind="batch"):
    return {"bundle_id": "bT", "group_kind": kind, "group_key": "g", "entries": entries}


def _entry(ref, layer="knowledge", role="knowledge-card", ev=1, basis="test",
           kinds=(), excerpt="", tags=(), chash=""):
    return {"ref": ref, "node_id": ref, "layer": layer, "role": role, "evidence_count": ev,
            "verification_basis": basis, "issue_kinds": list(kinds), "excerpt": excerpt,
            "content_hash": chash, "tags": list(tags), "importance": 0.5,
            "writer": "w", "session": "s"}


def phase_c(tmp):
    print("[C] 级 3 规则装配")
    rl = RS.load_rules()
    ids = [r["id"] for r in rl["rules"]]
    ok(rl["count"] == 7, f"C1 仓内规则库 7 条（实得 {rl['count']}）")
    ok(set(ids) == {"R-DUP-HASH-GROUP", "R-ROLE-MISSING", "R-EVIDENCE-ZERO",
                    "R-BASIS-MISSING", "R-BASIS-RATIO-PACKAGE", "R-BASIS-LICENSE",
                    "R-TEMPLATE-FLOW"}, f"C2 规则 id 集合正确（实得 {sorted(ids)}）")
    ok(all(r["severity"] in RS.SEVERITIES for r in rl["rules"]), "C3 severity 枚举合法")
    ok(sorted(RS.MECH_CHECKS) == ["basis_licensed", "dup_hash_group", "evidence_zero",
                                  "field_absent", "field_ratio_below",
                                  "template_flow_digits_only"],
       "C4 六检查器注册表齐备（引擎面冻结）")
    ok(all(r.get("title") for r in rl["rules"]), "C5 规则元信息齐备")

    bad = os.path.join(tmp, "badrules")
    os.makedirs(bad, exist_ok=True)

    def _bad(doc):
        for fn in os.listdir(bad):
            os.remove(os.path.join(bad, fn))
        with open(os.path.join(bad, "r.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        try:
            RS.load_rules(bad)
            return ""
        except ValueError as e:
            return str(e)

    m = _bad({"rules": [{"id": "X", "matcher": {}}]})
    ok("缺字段" in m, f"C6 规则缺 severity → ValueError 不静默降级（{m}）")
    m = _bad({"rules": [{"id": "X", "matcher": {}, "severity": "FATAL"}]})
    ok("severity" in m, "C7 severity 非法 → ValueError")
    m = _bad({"rules": [{"id": "X", "matcher": {}, "severity": "INFO"},
                        {"id": "X", "matcher": {}, "severity": "INFO"}]})
    ok("重复" in m, "C8 规则 id 重复 → ValueError")
    m = _bad({"rules": [{"id": "X", "matcher": {}, "severity": "INFO",
                         "mechanical": [{"check": "no_such_check"}]}]})
    ok("未知" in m, "C9 未知检查器 → ValueError（引擎白名单 fail-closed）")
    ok(_bad({"rules": []}) == "", "C10 空规则库不炸（容错）")

    # matcher / scope
    asm = RS.assemble(_mkpkg([_entry("a", role=None, ev=0)]), rules=rl)
    kinds = collections.Counter(i["issue_kind"] for i in asm["mechanical"])
    ok(kinds["missing_field"] >= 1, "C11 field_absent(role) 命中")
    ok(any(i.get("field") == "role" and i.get("rule_id") == "R-ROLE-MISSING"
           for i in asm["mechanical"]),
       "C12 issue 携带 field 与 rule_id 定位")
    ok(all(i["ref"] == "a" for i in asm["mechanical"]
           if i["issue_kind"] != "package_ratio"), "C13 条目级 issue 指回 ref")

    ctx = RS.assemble(_mkpkg([_entry("c", layer="contextual", role=None, ev=0)]), rules=rl)
    ok(not any(i["issue_kind"] == "missing_field" for i in ctx["mechanical"]),
       "C14 layer=knowledge 规则不跨层套用 contextual 条目")

    pkg = _mkpkg([_entry("d1", basis=""), _entry("d2", basis="test")])
    d = RS.assemble(pkg, rules=rl)
    ok(any(i["issue_kind"] == "package_ratio" and i.get("ref") is None
           for i in d["mechanical"]),
       "C15 field_ratio_below 产出包级 issue（ref=None）")

    dup = _mkpkg([_entry("e1", chash="H"), _entry("e2", chash="H"), _entry("e3", chash="H")])
    dd = RS.assemble(dup, rules=rl)
    n = sum(1 for i in dd["mechanical"] if i["issue_kind"] == "dup_content")
    ok(n == 2, f"C16 dup_hash_group 除首条外逐条（3 条同指纹 → 2，实得 {n}）")
    ok(any(i.get("ref") is not None and "e1" in i.get("evidence", "")
           for i in dd["mechanical"] if i["issue_kind"] == "dup_content"),
       "C17 重复 issue 证据点名组首，供 M2 一次裁决")
    ok(not any(i["issue_kind"] == "dup_content" for i in
               RS.assemble(_mkpkg([_entry("u1", chash="A"), _entry("u2", chash="B")]),
                           rules=rl)["mechanical"]),
       "C17b 指纹不同 → 不误报重复")

    tf = _mkpkg([_entry("f1", excerpt="# 功能名:批次1收官记忆\n证据 1 条"),
                 _entry("f2", excerpt="# 功能名:批次2收官记忆\n证据 2 条")])
    tt = RS.assemble(tf, rules=rl)
    ok(any(i["issue_kind"] == "template_flow" for i in tt["mechanical"]), "C18 去数字骨架相同 → 流水命中")
    tf2 = _mkpkg([_entry("f1", excerpt="# 功能名:批次1收官记忆"),
                  _entry("f2", excerpt="# 另一件事:完全不同正文结构")])
    ok(not any(i["issue_kind"] == "template_flow"
               for i in RS.assemble(tf2, rules=rl)["mechanical"]), "C19 骨架不同 → 不误报")

    sci = _mkpkg([_entry("g1", basis="textbook", tags=["数学"])])
    ok(any(i["issue_kind"] == "weak_source" for i in RS.assemble(sci, rules=rl)["mechanical"]),
       "C20 science 赛道 + textbook 基底 → 来源执照报 weak_source")
    hum = _mkpkg([_entry("g2", basis="textbook", tags=["文学"])])
    ok(not any(i["issue_kind"] == "weak_source"
               for i in RS.assemble(hum, rules=rl)["mechanical"]), "C21 humanities 同基底 → 不报")
    und = _mkpkg([_entry("g3", basis="textbook", tags=["zzz"])])
    ok(any(i["issue_kind"] == "weak_source" for i in RS.assemble(und, rules=rl)["mechanical"]),
       "C22 赛道未定 → 机械面一律报（crosscheck「一律不发放」语义，供 M2 复核）")

    # 规则数据化：新增一条自定义规则，引擎零改动即生效
    cust = os.path.join(tmp, "custrules")
    os.makedirs(cust, exist_ok=True)
    RS.load_rules()  # 预热
    src = RS.RULES_DIR
    shutil.copytree(src, cust, dirs_exist_ok=True)
    with open(os.path.join(cust, "zz_custom.json"), "w", encoding="utf-8") as f:
        json.dump({"spec_version": 1, "domain": "custom", "rules": [
            {"id": "R-CUSTOM-ROLE", "title": "自定规则", "severity": "INFO",
             "matcher": {"layer": ["knowledge"]},
             "mechanical": [{"check": "field_absent", "field": "role",
                             "issue_kind": "custom_role"}],
             "llm": [], "remedy": "noop"}]}, f, ensure_ascii=False)
    rl2 = RS.load_rules(cust)
    ok(rl2["count"] == 8, f"C23 规则库热加一条 → 8 条（实得 {rl2['count']}）")
    a2 = RS.assemble(_mkpkg([_entry("h1", role=None)]), rules=rl2)
    ok(any(i["issue_kind"] == "custom_role" for i in a2["mechanical"]),
       "C24 新规则零代码改动即生效（G2 数据化）")

    # assemble_all 汇总口径
    res = {"candidates": [{"key": "a"}, {"key": "b"}],
           "bundles": [{"bundle_id": "b1", "group_kind": "batch", "group_key": "g",
                        "entries": [_entry("a", role=None)]},
                       {"bundle_id": "b2", "group_kind": "batch", "group_key": "g",
                        "entries": [_entry("b", ev=0)]}],
           "stats": {}}
    allr = RS.assemble_all(res, rules=rl)
    tot = sum(len(p["mechanical"]) for p in allr["packages"])
    ok(allr["stats"]["mechanical_total"] == tot, "C25 assemble_all 汇总 == 各包之和")
    ok(allr["stats"]["llm_checks"] == sum(len(p["llm"]) for p in allr["packages"]),
       "C26 llm 计数同口径")
    ok(allr["packages"][0]["bundle_id"] == "b1"
       and allr["stats"]["bundles"] == 2, "C27 包序与包数稳定")
    ok(allr["stats"]["rules"] == [r["id"] for r in rl["rules"]],
       "C28 汇总内嵌生效规则清单（可复算）")
    ok(all(p["llm"] == [] or all("scope_refs" in c for c in p["llm"])
           for p in allr["packages"]), "C29 LLM 检查清单带 scope_refs 供 M2 圈定范围")
    ok(all(not p["matched"] or all({"id", "severity", "scope", "remedy"} <= set(m)
                                   for m in p["matched"]) for p in allr["packages"]),
       "C30 matched 记录规则命中理由/范围/处方")

    a_list = RS.assemble(_mkpkg([_entry("m1", role=None)]), rules=rl["rules"])
    a_dict = RS.assemble(_mkpkg([_entry("m1", role=None)]), rules=rl)
    ok(a_list == a_dict, "C31 rules 入参防呆：列表与 load_rules 结果等价")
    try:
        RS.assemble(_mkpkg([_entry("m2")]), rules={"count": 0})
        ok(False, "C32 规则入参形态错误 → 明确报错不静默")
    except ValueError as e:
        ok("rules" in str(e), "C32 规则入参形态错误 → 明确报错不静默")


# ---------------------------- D CLI ----------------------------

def phase_d(tmp):
    print("[D] CLI")
    rC = mkroot(os.path.join(tmp, "cli"), dict(A_NODES), access=A_ACCESS)
    d = CLI.run(rC)
    ok({"root", "candidates", "bundles", "bundle_stats", "assemble_stats",
        "mechanical_by_rule", "llm_checks"} <= set(d),
       f"D1 run 返回结构齐备（实得 {sorted(d)}）")
    ok(d["candidates"]["total"] > 0 and d["bundle_stats"]["bundles"] > 0,
       "D2 run 产出候选与包")
    ok(d["assemble_stats"]["mechanical_total"] >= 1 and d["mechanical_by_rule"],
       "D3 run 含规则装配结果（逐规则计数）")
    ok(d["bundle_stats"]["candidates"] == d["candidates"]["total"], "D4 捆绑条目数与候选同口径")

    out = os.path.join(tmp, "m1.json")
    rc = CLI.main(["--root", rC, "--out", out])
    ok(rc == 0, f"D5 main 正常退出码 0（实得 {rc}）")
    ok(os.path.exists(out), "D6 --out 落盘产物存在")
    with open(out, encoding="utf-8") as f:
        jd = json.load(f)
    ok(jd["candidates"]["total"] == d["candidates"]["total"], "D7 落盘内容与 run 同源")
    ok(not ({"candidates_full", "bundles_full", "packages_full"} & set(jd)),
       "D8 默认产物只含摘要不含逐条明细")

    s = io.StringIO()
    with redirect_stdout(s):
        CLI.main(["--root", rC, "--full", "--out", os.path.join(tmp, "full.json")])
    ok("机械检查" in s.getvalue() and "包" in s.getvalue(), "D9 摘要含机械聚合与包清单")
    with open(os.path.join(tmp, "full.json"), encoding="utf-8") as f:
        jf = json.load(f)
    ok({"candidates_full", "bundles_full", "packages_full"} <= set(jf),
       "D10 --full 追加三类明细")

    before = snapshot(rC)
    CD.generate(rC)
    BD.bundle(CD.generate(rC)["candidates"], root=rC)
    CLI.run(rC)
    ok(snapshot(rC) == before, "D11 全链路零写入（库指纹不变）")


# ---------------------------- E 集成（真源存在才跑） ----------------------------

def _real_root():
    cands = [os.environ.get("MDCG_ROOT")]
    try:
        from .datapath import mdcg_root
        cands.append(mdcg_root())
    except Exception:
        pass
    cands.append("D:/Program Files/2_ai/AEIS/data/mdcg")
    for r in cands:
        if r and os.path.exists(os.path.join(r, "_index.json")):
            return r
    return None


def phase_e():
    print("[E] 集成（真源存在才跑）")
    root = _real_root()
    if not root:
        print("  SKIP 真源库不可用（外部 clone 环境）——非失败")
        return
    before = snapshot(root, exclude_dirs=VOLATILE_DIRS)
    d = CLI.run(root, cold_limit=200)
    nodes = CF.load_index(root) or {}
    bb = d["bundle_stats"]
    ok(bb["candidates"] == d["candidates"]["total"] and bb["candidates"] > 0,
       "E1 捆绑条目数与候选同口径")
    ok(8000 <= d["candidates"]["total"] <= 20000,
       f"E2 真源欠账规模与基线 11195 同量级（实得 {d['candidates']['total']}）")
    ok(bb["bundles"] <= 3000, f"E3 包数在可评审规模内（实得 {bb['bundles']}）")
    ok(len(nodes) > 0 and d["candidates"]["total"] <= len(nodes) * 4,
       "E4 候选量级与真源节点数相容")
    asm = d["assemble_stats"]
    ok(asm["mechanical_total"] > 0, "E5 真源机械 issue 非空")
    ok(set(asm["mechanical_by_kind"]) <= declared_kinds(),
       f"E6 机械分类 ⊆ 规则库声明（实得 {sorted(asm['mechanical_by_kind'])}）")
    ok({"missing_field", "dup_content", "weak_source"} <= set(asm["mechanical_by_kind"]),
       f"E6b 真源三类核心 issue 必现（实得 {sorted(asm['mechanical_by_kind'])}）")
    ok(all(k in d["candidates"]["by_source"] for k in CD.SOURCES), "E7 四源统计齐备")
    rep = d.get("assertions") or {}
    ok(rep.get("verdict") in ("PASS", "WARN", "FAIL"),
       f"E8 断言集 verdict 合法（{rep.get('verdict')}）")
    ok(d["llm_checks"] and all(isinstance(t, (list, tuple)) and len(t) == 2
                               for t in d["llm_checks"]), "E9 LLM 待检清单可枚举（供 M2 排期）")
    after = snapshot(root, exclude_dirs=VOLATILE_DIRS)
    ok(after == before, "E10 真源只读（记忆数据面指纹不变，" + _diff(before, after) + "）")
    logs = (os.listdir(os.path.join(root, "_index_log"))
            if os.path.isdir(os.path.join(root, "_index_log")) else [])
    _pidpref = str(os.getpid()) + "-"
    ok(not any(s.startswith(_pidpref) for s in logs),
       "E10b M1 未在真源留下本进程增量日志（写入者归属外部）")

    # ---- E11~ 审计基线复现（§6 M1 验收口径）----
    # 基线（2026-09-15 审计 node_26b0973a）：混层 57.9% / role 空 99.99% /
    # evidence_count 仅 6 条 / 精确重复 90 条 / 欠账 11195。库在增长，用容差区间。
    cov = CF.metrics_of(CF.check(root, check_paths=False))
    kn = [k for k, v in nodes.items() if (v.get("layer") or "") == "knowledge"]
    ok(0.55 <= cov["mixed_ratio"] <= 0.62,
       f"E11 复现混层率 57.9%（实得 {cov['mixed_ratio']:.4f}）")
    ok(cov["role_ratio_kn"] < 0.001,
       f"E12 复现 role 近乎全空（有 role 占比 {cov['role_ratio_kn']:.6f}）")
    n_ev = sum(1 for k in kn if CF._as_int(nodes[k].get("evidence_count")) > 0)
    ok(n_ev == 6, f"E13 复现 evidence_count 仅 6 条（实得 {n_ev}）")
    ok(85 <= cov["dup_groups"] <= 105,
       f"E14 复现精确重复 ~90 组（实得 {cov['dup_groups']}）")
    ok(10000 <= len(kn) <= 13000,
       f"E15 复现 knowledge 存量 11195 量级（实得 {len(kn)}）")
    ok(cov["reach_ratio"] < 0.15,
       f"E16 复现召回率低（reach_ratio {cov['reach_ratio']:.4f}）")
    # 边界如实标注（不猜测、不硬凑）：基线「同模板冗余 233 条」无固化判据函数——实测两候选
    # 口径均不等（writelimit.template_signature 全量分组冗余 1949；本引擎 template_flow
    # 严格「只换数字」口径 13），故不纳入机械断言，留待 M3 定位模块抽样核对后固化。


# ---------------------------- main ----------------------------

def main():
    tmp = tempfile.mkdtemp(prefix="mrev_")
    try:
        for ph in (phase_a, phase_b, phase_c, phase_d):
            ph(tmp)
        phase_e()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n== M1 机械层自测：{PASS} 通过 / {FAIL} 失败 ==")
    if FAILS:
        for f in FAILS:
            print("  - " + f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

