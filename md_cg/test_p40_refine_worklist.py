# -*- coding: utf-8 -*-
"""G6 · node_ 结构提炼抽检工单与扩批闸门（P40 设计态验收）。

对照 `docs/认知图_G4-G8缺口裁定单_v0.1.md` §四 G6：`node_*`（P37 派生记忆）
自带 `ccg_exempt=true`，只声明「功能名 / 生效条件」，`子功能/执行/不适用条件` 全缺。
条件 A 要求**先抽 20 条做提炼预演、人工核对提炼口径，绝不盲跑全量**。

覆盖：①契约链 ②plan 只读 ③工单结构 ④同源口径 ⑤预演 grounded+模板词标记
⑥样本不足不产候选 ⑦确定性 ⑧闸门关闭 ⑨闸门放行 ⑩闸门否决 ⑪不改节点
⑫权限分档 ⑬样本量校准 ⑭未知 action。

独立临时根，重跑 ≡ 首跑。运行：python -m md_cg.test_p40_refine_worklist
"""
from __future__ import annotations

import os
import shutil
import tempfile

from . import consolidate as C
from . import refine as rf
from . import tokens
from .mdcos import MdCGOS
from .mcp_server import KERNEL_TOOLS, call_tool
from .security import AccessDenied, Principal

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


def denied(fn, label):
    try:
        fn()
    except AccessDenied:
        ok(True, label)
        return
    ok(False, label)


#: 与 P37 派生记忆同型：有「功能名/生效条件」，缺「子功能/执行/不适用条件」
TEMPLATE = ("# 功能名：感知单元\n"
            "# 生效条件：载体/位置：感知系统；时间：2026-01-01 00:00～"
            "2026-01-01 01:00（UTC）；方法：感官输入；约束：协议实例运行中\n"
            "协议实例在感知系统中完成一次观测，产出结构化记录。\n")


def _seed_root(root, n=30):
    cg = MdCGOS(root)
    for i in range(n):
        cg.add("node_dup_%02d" % i, TEMPLATE, layer="knowledge", tags=["p37"])
    cg.add("note_out", "情境笔记，不在抽检前缀内。\n", layer="contextual",
           tags=["note"])
    cg.flush()
    cg.rebuild_index()
    return cg


def _write_layer():
    s = tokens.role_spec("reflection")
    return Principal(tenant="default", actor="writer", clearance="internal",
                     can_write=True, can_admin=False, role="reflect",
                     layers_allow=s["layers_allow"], ops_allow=s["ops_allow"])


def _p(cg, **kw):
    return call_tool(cg, "cg", {"op": "maintain", **kw})


def main():
    print("md 认知图 P40 验收 · G6 node_ 提炼抽检工单（只读预演 + 扩批闸门）")
    print("=" * 70)
    tmp = tempfile.mkdtemp(prefix="mdcg_p40_")
    ROOT = os.path.join(tmp, "root")
    try:
        from . import corpus
        corpus.reset_root(ROOT)
        cg = _seed_root(ROOT)
        cg.principal = Principal(tenant="default", actor="p40",
                                 clearance="private", can_write=True,
                                 can_admin=True, role="designer")
        acts = ("refine", "refine_gate", "refine_history", "refine_calibrate")

        print("\n【1】op 契约链（防漏改）")
        prop = next(t for t in KERNEL_TOOLS
                    if t["name"] == "cg")["inputSchema"]["properties"]
        desc = prop["action"]["description"]
        ok(all(a in desc for a in acts), "①4 个 refine action 已在 schema 声明")
        ok(all(k in prop for k in ("sample_n", "prefix", "verdicts")),
           "①sample_n/prefix/verdicts 参数已声明")
        ok(all(a in MdCGOS.MAINTAIN_ACTIONS for a in acts),
           "①4 个 action 已在 MAINTAIN_ACTIONS 注册")

        print("\n【2】plan 只读（不写盘 / 前缀内 20 条）")
        rep = _p(cg, action="refine")
        ok(rep.get("dry_run") is True and rep.get("readonly") is True,
           "②dry_run/readonly 标记")
        ok(rep.get("pool") == 30, f"②抽检池 30（实测 {rep.get('pool')}）")
        ok(rep.get("sampled") == 20, f"②抽检 20 条（实测 {rep.get('sampled')}）")
        ok(all(i["id"].startswith("node_") for i in rep["items"]),
           "②前缀外节点不纳入")
        ok(not os.path.exists(os.path.join(ROOT, rf.REFINE_LOG)),
           "②预演不写日志")

        print("\n【3】工单结构（原文 + 字段缺口 + 指纹 + 口径声明）")
        ok(len(rep["worklist"]) == 20, "③工单 20 条")
        it = rep["items"][0]
        ok(all(k in it for k in ("id", "family", "layer", "body", "body_len",
                                 "ccg_present", "ccg_missing", "source_sha")),
           "③工单条目字段齐备")
        ok("子功能" in it["ccg_missing"] and "执行" in it["ccg_missing"],
           "③如实登记缺失的 CCG 字段（不编造）")
        ok(it["body"].strip(), "③工单带原文（供人工核对）")
        ok(len(it["source_sha"]) == 16, "③来源指纹（可复核正文）")
        ok([r["key"] for r in rep["spec"]["review_items"]]
           == ["faithful", "added_info", "discriminating", "member_consistency"],
           "③口径声明含 4 项人工核对项")
        ok(rep["spec"]["evidence"].startswith("inferred"),
           "③产出证据档恒 inferred")

        print("\n【4】同源口径（不另起提炼器）")
        ok(rf.MIN_CLUSTER == C.INDUCE_MIN_CLUSTER
           and rf.MIN_JACCARD == C.INDUCE_MIN_JACCARD, "④聚类阈值取自 induce")

        print("\n【5】预演（grounded + 模板词标记）")
        pv = rep["preview"]
        ok(pv["clusters"] == 1, f"⑤产出 1 个候选（实测 {pv['clusters']}）")
        c0 = pv["candidates"][0]
        ok(c0["size"] == 20, f"⑤候选成员 20（实测 {c0['size']}）")
        ok(c0["grounding_gap"] == [], "⑤共性条件全成员可追溯（无忠实性缺口）")
        ok(all(len(v) == c0["size"] for v in c0["condition_sources"].values()),
           "⑤每条共性条件都有成员索引来源")
        ok(any(g["ratio"] >= rf.GENERIC_DF for g in c0["generic_conditions"]),
           "⑤高 df 模板词被标记 generic")
        ok(c0["discriminating"] == [], "⑤该候选无区分性共性")
        ok(pv["candidates_generic_only"] == 1, "⑤如实报「模板化」候选计数")

        print("\n【6】样本不足不产候选（<min_cluster 不成簇）")
        pv2 = rf.preview(cg, ids=sorted(rep["sample"])[:2])
        ok(pv2["clusters"] == 0, "⑥2 条 < min_cluster → 0 候选")
        ok(pv2["sample_adequacy"] == "insufficient", "⑥判 insufficient")

        print("\n【7】确定性（同 seed 同样本）")
        rep2 = _p(cg, action="refine")
        ok(rep["sample_sha"] == rep2["sample_sha"], "⑦同样本指纹")
        ok([c["concept_id"] for c in pv["candidates"]]
           == [c["concept_id"] for c in rep2["preview"]["candidates"]],
           "⑦同候选集")
        ok(rep["sample"] == rep2["sample"], "⑦同抽样序")

        print("\n【8】闸门（未审不放行）")
        g0 = _p(cg, action="refine_gate")
        ok(g0.get("expand_allowed") is False and g0.get("reason") == "no_batch",
           "⑧无留痕 → no_batch 且不放行")
        ap0 = _p(cg, action="refine", apply=True, batch="t-review")
        ok(ap0.get("reviewed") == 0
           and ap0["gate"]["reason"] == "awaiting_human_review",
           "⑧未审 → awaiting_human_review 且不放行")
        ok(os.path.exists(os.path.join(ROOT, rf.REFINE_LOG)), "⑧留痕已落盘")

        print("\n【9】闸门放行（全审 / 全忠实 / 无新增）")
        cids = [c["concept_id"] for c in pv["candidates"]]
        good = [{"concept_id": c, "faithful": True, "added_info": False}
                for c in cids]
        ap1 = _p(cg, action="refine", apply=True, batch="t-ok", verdicts=good)
        ok(ap1["gate"]["reviewed"] == len(cids), "⑨裁决全部候选")
        ok(ap1["gate"]["expand_allowed"] is True
           and ap1["gate"]["reason"] == "ok", "⑨通过率达标 → 放行扩批")
        g1 = _p(cg, action="refine_gate", batch="t-ok")
        ok(g1.get("expand_allowed") is True, "⑨gate 动作复算一致")

        print("\n【10】闸门否决（新增信息 / 忠实率不足）")
        bad = [{"concept_id": c, "faithful": True, "added_info": True}
               for c in cids]
        ap2 = _p(cg, action="refine", apply=True, batch="t-added", verdicts=bad)
        ok(ap2["gate"]["reason"] == "added_info_detected"
           and ap2["gate"]["expand_allowed"] is False, "⑩新增信息 → 整批否决")
        st = rf._verdict_stats(
            [{"concept_id": "a", "faithful": False, "added_info": False},
             {"concept_id": "b", "faithful": True, "added_info": False}],
            [{"concept_id": "a"}, {"concept_id": "b"}])
        ok(st["reason"] == "faithful_rate_below_gate"
           and st["expand_allowed"] is False, "⑩忠实率不足 → 拒放行")

        print("\n【11】apply 不改任何节点")
        nid = rep["items"][0]["id"]
        before = cg._read(cg.index["nodes"][nid])
        _p(cg, action="refine", apply=True, batch="t-immutable")
        cg.rebuild_index()
        after = cg._read(cg.index["nodes"][nid])
        ok(before[0] == after[0] and before[1] == after[1],
           "⑪frontmatter 与正文逐字节不变")
        hist = _p(cg, action="refine_history")
        ok(hist["total"] >= 4 and hist["returned"] >= 1, "⑪history 可回读留痕")
        ok("root" in hist, "⑪history 结构含 root")

        print("\n【12】权限分档（写层可看 / apply 需管理）")
        cg.principal = _write_layer()
        ok(isinstance(_p(cg, action="refine"), dict), "⑫写层可看工单")
        ok(isinstance(_p(cg, action="refine_gate"), dict), "⑫写层可看闸门")
        denied(lambda: _p(cg, action="refine", apply=True), "⑫写层不可 apply")
        cg.principal = Principal(tenant="default", actor="p40",
                                 clearance="private", can_write=True,
                                 can_admin=True, role="designer")

        print("\n【13】样本量校准（只读爬坡，如实归因）")
        cal = _p(cg, action="refine_calibrate")
        ok(cal.get("readonly") is True and cal["steps"][0]["n"] == 20,
           "⑬校准从 20 条起步")
        ok(isinstance(cal.get("blocked"), bool)
           and isinstance(cal.get("recommend"), str), "⑬如实报 blocked + 归因")
        ok("扩批" in cal["recommend"], "⑬归因指向「不得扩批」")

        print("\n【14】未知 action 不静默成功")
        try:
            _p(cg, action="refine_x")
            ok(False, "⑭未知 action 必须报错")
        except ValueError as e:
            ok("未知 action" in str(e), "⑭未知 action 报错")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 70)
    print(f"P40 结果：PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        print("未通过：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
