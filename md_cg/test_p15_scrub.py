# -*- coding: utf-8 -*-
"""P15：记忆自净（`scrub.py`）——抽查 / 联想 / 去污染 / 校准偏差。

覆盖：分层抽样（可复现、风险层 + 对照组）→ 三路联想（关系链 / 子图 / 词法）
→ 污染体检（矛盾 / 过期 / 重复 / 孤立噪音 / 长期未验证）→ 去污染
（dry-run / weaken+demote / 幂等 / 保护跳过 / 永不删节点）→ 校准偏差
（gap → 偏置建议 → 可选写回）→ 挂载自维持循环 + MCP `op=scrub`。
"""
import json
import os
import shutil
import tempfile
import time

from . import scrub, sustain
from .fsutil import append_jsonl
from .mdcg import MdCG
from .mdcos import MdCGSecure
from .security import Principal

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f"  · {detail}" if detail else ""))


def _touch(cg, nid, days_ago=0.0, count=1):
    for _ in range(count):
        append_jsonl(cg.access_log,
                     {"t": time.time() - days_ago * 86400, "ids": [nid],
                      "tier": None})


def _set(cg, nid, **fm):
    """改写节点 frontmatter，并同步索引里受影响的快照字段。"""
    e = cg.index["nodes"][nid]
    node = cg.get(nid)
    f = dict(node["frontmatter"])
    f.update(fm)
    cg._write_node(nid, os.path.join(cg.root, e["path"]), f, node["content"])
    for k in ("created_at", "importance", "evidence_count"):
        if k in fm:
            e[k] = fm[k]


def main():
    net = tempfile.mkdtemp(prefix="mdcg_p15_net_")
    os.environ["MDCG_SUSTAIN_DIR"] = net
    root = sroot = None
    try:
        # ---------- A. 记忆抽查 ----------
        print("\n[A] 记忆抽查（分层 + 可复现）")
        root = tempfile.mkdtemp(prefix="mdcg_p15_")
        cg = MdCG(root)
        cg.add("a", "# 功能名：甲\n# 执行：add\n\n超时：30s\n禁止并发写入")
        cg.add("b", "# 功能名：乙\n# 执行：add\n\n超时：60s\n应当并发写入")
        cg.add("c", "# 功能名：丙\n\n完全无关的另一个主题内容")
        cg.add("d", "# 功能名：丁\n\n第三种主题，用于孤立与陈旧")
        cg.add("e", "# 功能名：戊\n\n第五个节点")
        cg.add("f", "# 功能名：己\n\n第六个节点，用于补足抽样池")
        _touch(cg, "d", days_ago=40)          # 陈旧
        _touch(cg, "e", count=4)              # 高频

        s1 = scrub.sample(cg, 6, seed=7)
        check("A1 抽样返回条数", s1["n"] == 6 and len(s1["sample"]) == 6)
        check("A2 分层标签合法",
              all(x["stratum"] in scrub.STRATA for x in s1["sample"]))
        s2 = scrub.sample(cg, 6, seed=7)
        check("A3 同 seed 同样本（可复现）",
              [x["node_id"] for x in s1["sample"]]
              == [x["node_id"] for x in s2["sample"]])
        check("A4 不同 seed 仍返回满额", scrub.sample(cg, 6, seed=99)["n"] == 6)
        check("A5 陈旧节点入 stale 层",
              any(x["node_id"] == "d" and x["stratum"] == "stale"
                  for x in s1["sample"]))
        check("A6 高频节点入 hot 层（对照组）",
              any(x["node_id"] == "e" and x["stratum"] == "hot"
                  for x in s1["sample"]))
        sr = scrub.sample(cg, 4, strategy="random", seed=1)
        check("A7 random 策略只取随机层",
              sr["n"] == 4
              and all(x["stratum"] == "random" for x in sr["sample"]))
        rk = scrub.sample(cg, 4, strategy="risk", seed=1)
        check("A8 risk 策略不含对照层",
              all(x["stratum"] != "hot" for x in rk["sample"]))
        try:
            scrub.sample(cg, 1, strategy="nope")
            raised = False
        except ValueError:
            raised = True
        check("A9 未知策略报错", raised)
        check("A10 抽查只读（节点数不变）", len(cg.index["nodes"]) == 6)

        # ---------- B. 联想 ----------
        print("\n[B] 联想（关系链 / 子图 / 词法）")
        cg.add("chain_t", "# 功能名：链目标\n\n与甲有因果关系",
               edges=[{"target": "a", "relation_type": "causal",
                       "condition": "当 X 成立", "confidence": 0.9}])
        cg.add("p", "# 功能名：父\n\n子图父节点",
               subgraph={"nodes": ["a"], "edges": []})
        assoc_a = scrub.associate(cg, "a", hops=2, limit=20)
        rel = {r["node_id"]: r for r in assoc_a["related"]}
        check("B1 关系链命中（带条件）",
              "chain_t" in rel and rel["chain_t"]["via"] == "chain"
              and rel["chain_t"].get("condition") == "当 X 成立")
        check("B2 词法近邻命中（无边也联得上）",
              "b" in rel and rel["b"]["via"] == "lexical")
        check("B3 子图层级命中", "p" in rel and rel["p"]["via"] == "subgraph")
        ws = [r["weight"] for r in assoc_a["related"]]
        check("B4 权重降序", ws == sorted(ws, reverse=True))
        check("B5 by_via 统计", assoc_a["by_via"].get("chain", 0) >= 1
              and assoc_a["by_via"].get("lexical", 0) >= 1)
        check("B6 不含自身", all(r["node_id"] != "a"
                                for r in assoc_a["related"]))
        # ---------- C. 去污染 ----------
        print("\n[C] 去污染（体检 / dry-run / 可逆处置）")
        cg.add("exp1", "# 功能名：过期\n\n这条已过期", valid_until="2020-01-01")
        cg.add("noise", "# 功能名：噪音\n\n孤立低重要")
        cg._move_layer("noise", "contextual", reason="test")
        _set(cg, "noise", importance=0.1)
        cg.add("old1", "# 功能名：老知识\n\n从未验证的旧知识")
        _set(cg, "old1", created_at=time.time() - 20 * 86400)
        cg.add("dup1", "# 功能名：重复甲\n\n重复内容主体：超时参数是 30 秒")
        cg.add("dup2", "# 功能名：重复乙\n\n重复内容主体：超时参数是 30 秒")

        ids_c = ["a", "b", "exp1", "noise", "old1", "dup1"]
        rep = scrub.audit(cg, ids_c)
        kinds = {i["kind"] for i in rep["issues"]}
        check("C1 同键不同值 → contradiction（high）",
              "contradiction" in kinds
              and any(i["kind"] == "contradiction" and i["severity"] == "high"
                      for i in rep["issues"]))
        check("C2 时效过期 → expired",
              "expired" in kinds
              and any(i["node_id"] == "exp1" for i in rep["issues"]))
        check("C3 孤立噪音 → orphan_noise", "orphan_noise" in kinds)
        check("C4 长期未验证 → unverified", "unverified" in kinds)
        check("C5 高冗余 → duplicate", "duplicate" in kinds)
        check("C6 体检只读（节点数不变）", len(cg.index["nodes"]) == 13)
        check("C7 每条判据都可解释",
              bool(rep["issues"]) and all(i.get("detail")
                                          for i in rep["issues"]))

        conf0 = float(cg.get("a")["frontmatter"].get("confidence") or 0.6)
        lay0 = cg.get("a")["frontmatter"].get("layer")
        dry = scrub.decontaminate(cg, ["a"], dry_run=True)
        check("C8 dry-run 不改动",
              float(cg.get("a")["frontmatter"].get("confidence") or 0.6) == conf0
              and cg.get("a")["frontmatter"].get("layer") == lay0
              and all(not x["applied"] for x in dry["actions"]))
        check("C9 dry-run 给出计划动作",
              any(x.get("planned") for x in dry["actions"]))

        n_before = len(cg.index["nodes"])
        scrub.decontaminate(cg, ["a"], dry_run=False)
        fm_a = cg.get("a")["frontmatter"]
        check("C10 实修 weaken：置信下调 + 记反例",
              float(fm_a.get("confidence") or 1) < conf0
              and int(fm_a.get("negative_evidence") or 0) >= 1)
        check("C11 实修 demote：降级到情境层",
              fm_a.get("layer") == "contextual" and lay0 == "knowledge")
        check("C12 永不删除节点", len(cg.index["nodes"]) == n_before)
        again = scrub.decontaminate(cg, ["a"], dry_run=False)
        check("C13 幂等：重复处置被跳过",
              again["applied"] == 0 and again["skipped_done"] >= 1)
        hint = scrub.decontaminate(cg, ["dup1"], dry_run=False)
        check("C14 冗余只给建议不代劳",
              hint["hints"] >= 1
              and all(x["action"] == "hint" for x in hint["actions"]))
        check("C15 审计留痕",
              os.path.exists(os.path.join(root, "_scrub.jsonl"))
              and scrub.summary(cg)["decontaminated"] >= 1)

        cg.add("imp1", "# 功能名：重要\n# 执行：add\n\n超时：99s\n禁止并发写入",
               importance=0.9)
        prot_rep = scrub.decontaminate(cg, ["imp1"], dry_run=False)
        check("C16 受保护节点跳过（importance≥0.7）",
              prot_rep["skipped_protected"] >= 1
              and cg.get("imp1")["frontmatter"].get("layer") == "knowledge")
        # ---------- D. 校准偏差 ----------
        print("\n[D] 校准偏差（gap → 偏置 → 可选写回）")
        cro = tempfile.mkdtemp(prefix="mdcg_p15_cal_")
        cg2 = MdCG(cro)
        cg2.add("plain", "# 功能名：无证据\n\n没有任何验证记录")
        check("D1 无证据 → 数据不足", scrub.calibrate(cg2)["ok"] is False)

        for i in range(4):
            cg2.add(f"c{i}", f"# 功能名：校准{i}\n\n内容 {i}")
            cg2.verify(f"c{i}", "e1", "confirmed")
        for i in range(4, 8):
            cg2.add(f"c{i}", f"# 功能名：校准{i}\n\n内容 {i}")
            cg2.verify(f"c{i}", "e1", "weakened")
            cg2.verify(f"c{i}", "e2", "weakened")
        cal = scrub.calibrate(cg2)
        check("D2 有证据 → 可校准",
              cal["ok"] is True and cal["n_nodes"] >= 8)
        check("D3 过度自信 → gap>0", cal["gap"] > 0.05, f"gap={cal['gap']}")
        check("D4 建议负偏置（下调置信）", cal["suggested_offset"] < 0)
        c_before = float(cg2.get("c0")["frontmatter"].get("confidence"))
        scrub.calibrate(cg2, apply=False)
        check("D5 apply=False 不写回",
              float(cg2.get("c0")["frontmatter"].get("confidence")) == c_before)
        cg2.add("imp2", "# 功能名：保护\n\n重要节点", importance=0.9)
        cg2.verify("imp2", "e1", "confirmed")
        adj = scrub.calibrate(cg2, apply=True)
        check("D6 apply=True 写回偏置",
              adj["applied"] is True and adj["n_adjusted"] >= 8
              and float(cg2.get("c0")["frontmatter"]["confidence"]) < c_before)
        check("D7 保护节点跳过", adj["skipped_protected"] >= 1)
        check("D8 分桶偏差按幅值降序",
              cal["bins_bias"] == sorted(cal["bins_bias"],
                                         key=lambda x: -abs(x["bias"])))
        shutil.rmtree(cro, ignore_errors=True)

        # ---------- E. 挂载自维持 + MCP ----------
        print("\n[E] 挂载自维持循环与 MCP 接入")
        lp = sustain.SustainLoop(cg, "p15loop", beat_interval=0.05,
                                 heal_interval=0.05, scrub_interval=0.05,
                                 auto_scrub=False, d=net)
        lp.start()
        time.sleep(0.8)
        check("E1 常驻循环周期自净",
              lp.last_scrub is not None and lp.last_scrub["dry_run"] is True)
        check("E2 默认只巡检（不改节点）",
              lp.last_scrub["applied"] == 0 and lp.last_scrub["n_issues"] >= 1)
        check("E3 status 暴露自净字段",
              lp.status()["scrub_interval"] == 0.05
              and lp.status()["auto_scrub"] is False)
        lp.stop()
        check("E4 sustain.summary 含自净摘要",
              sustain.summary(cg)["scrub"]["sweeps"] >= 1)

        from .mcp_server import call_tool
        smp = call_tool(cg, "cg", {"op": "scrub", "action": "sample",
                                   "k": 3, "seed": 5})
        check("E5 MCP sample", smp["n"] == 3 and smp["seed"] == 5)
        au = call_tool(cg, "cg", {"op": "scrub", "action": "audit",
                                  "ids": ["b"]})
        check("E6 MCP audit", au["n_checked"] == 1 and "n_issues" in au)
        dc = call_tool(cg, "cg", {"op": "scrub", "action": "decontaminate",
                                  "ids": ["b"], "dry_run": True})
        check("E7 MCP decontaminate 默认 dry-run", dc["dry_run"] is True)
        cc = call_tool(cg, "cg", {"op": "scrub", "action": "calibrate"})
        check("E8 MCP calibrate", "suggested_offset" in cc)
        sw = call_tool(cg, "cg", {"op": "scrub", "action": "sweep",
                                  "k": 4, "seed": 2})
        check("E9 MCP sweep 默认只读",
              sw["dry_run"] is True and "sample" in sw
              and "calibration" in sw)
        cat = call_tool(cg, "cg", {"op": "scrub", "action": "catalog"})
        check("E10 MCP catalog", "decontaminate" in cat["actions"]
              and "contradiction" in cat["contamination"])
        hs = call_tool(cg, "cg", {"op": "scrub", "action": "history"})
        check("E11 MCP history", hs["n"] >= 1)
        sm = call_tool(cg, "cg", {"op": "scrub", "action": "summary"})
        check("E12 MCP summary", "sweeps" in sm)
        ast = call_tool(cg, "cg", {"op": "scrub", "action": "associate",
                                   "node_id": "a", "hops": 1})
        check("E13 MCP associate", ast["n"] >= 1)
    finally:
        os.environ.pop("MDCG_SUSTAIN_DIR", None)
        sustain.stop_all()
        for d in (net, root, sroot):
            if d:
                shutil.rmtree(d, ignore_errors=True)

    print(f"\n==== P15 结果：{PASS} 通过 / {FAIL} 失败 ====")
    return 1 if FAIL else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
