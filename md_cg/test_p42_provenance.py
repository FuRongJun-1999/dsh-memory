# -*- coding: utf-8 -*-
"""G8 · 派生溯源（新增即建链 + 失败不阻断 + 悬空可检出）（P42 设计态验收）。

对照 `docs/认知图_G4-G8缺口裁定单_v0.1.md` §六 G8：节点拆并/派生后**血缘丢失**，
库根无 `_link.jsonl`、frontmatter 的派生字段全空，事后无从回答「这个节点从哪来」。
本项只对**新增**节点常态化建链（历史不回填），且立三条硬约束。

覆盖：
  ① 契约链：catalog/schema/描述暴露 derived_from/relation + link 的 derive_* 系列；
  ② 新增即建链：frontmatter 声明 + `_link.jsonl` 落边 + 索引带声明（巡检零读文件）；
  ③ 多父 / 关系名 / 自环与空端点丢弃（不产生无意义边）；
  ④ 历史不回填：无声明节点不建链，重建台账结果为空、不发明边；
  ⑤ 定义边界：provenance（派生血缘）≠ links（对端信任 P_trust）；
  ⑥ 悬空可检出：父/子端点不在索引内 → 只读检出（ok=False、readonly=True、不删边）；
  ⑦ 诊断集成：diagnose 报 provenance_dangling（info、fix=None、不翻转 ok）；
  ⑧ 硬约束：建链失败**不阻断写入**（节点照常落库 + .fail 降级留痕）；
  ⑨ 非法关系名回退默认值、仍不阻断写入；
  ⑩ 台账是派生物：删掉台账仍可由索引兜底检出；rebuild 按声明恢复（含救回漏写的边）；
  (11) MCP 接入：link derive/derive_dangling/derive_catalog/derive_rebuild + sustain provenance；
  (12) 巡检只读：check 前后节点逐字节不变、台账不被改动；
  (13) 未知 action 不静默成功。

独立临时根，重跑 ≡ 首跑。运行：python -m md_cg.test_p42_provenance
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile

from . import provenance as PV
from . import sustain
from .fsutil import read_jsonl
from .mdcg import MdCG
from .mcp_server import KERNEL_TOOLS, call_tool

PASS = FAIL = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  [FAIL] {label}")


def _digest(cg, nid):
    e = cg.index["nodes"][nid]
    with open(os.path.join(cg.root, e["path"]), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def main():
    print("md 认知图 P42 验收 · G8 派生溯源（新增即建链 + 失败不阻断 + 悬空可检出）")
    print("=" * 70)
    root = root2 = None
    try:
        # ================================================ 准备
        root = tempfile.mkdtemp(prefix="mdcg_p42_")
        cg = MdCG(root)
        # 历史节点：建库时没有声明过派生关系（模拟 G8 缺口实测状态）
        cg.add("n_hist", "# 功能名：历史\n# 生效条件：条件 H\n\n历史节点（无派生声明）。")
        cg.add("n_a", "# 功能名：甲\n# 生效条件：条件 A\n\n正文甲。")
        cg.add("n_b", "# 功能名：乙\n# 生效条件：条件 B\n\n正文乙。")
        cg.rebuild_index()

        # ------------------------------------------------ ① 契约链
        print("\n【1】契约链（防「能力在、入口无」）")
        tool = next(t for t in KERNEL_TOOLS if t["name"] == "cg")
        prop = tool["inputSchema"]["properties"]
        desc = tool["description"] + prop["op"]["description"] + prop["action"]["description"]
        ok("派生溯源" in desc and "derive_dangling" in desc,
           "①契约描述含派生溯源与 derive_dangling")
        for k in ("derived_from", "relation", "child", "parent", "ledger_only"):
            ok(k in prop, f"①schema 声明 {k}")
        cat = call_tool(cg, "cg", {"op": "link", "action": "derive_catalog"})
        ok(cat["discipline"] == {"incremental_only": True, "no_backfill": True,
                                 "never_block_write": True, "patrol_readonly": True},
           "①catalog 显式声明四条纪律")
        ok(cat["default_relation"] == PV.DEFAULT_RELATION
           and "derived_from" in cat["relations"], "①关系名枚举 + 默认值")
        ok("links.py" in cat["distinct_from"], "①与对端信任层显式区分")

        # ------------------------------------------------ ② 新增即建链
        print("\n【2】新增即建链（声明 → frontmatter + 台账 + 索引）")
        ok(not os.path.exists(PV.ledger_file(root)), "②建库初期无 _link.jsonl（缺口实测）")
        cg.add("n_child", "# 功能名：子\n# 生效条件：条件 C\n\n由甲派生。",
               derived_from="n_a", batch="b_p42", actor="tester")
        fm = cg.get("n_child")["frontmatter"]
        ok(fm.get("derived_from") == ["n_a"], "②frontmatter 落 derived_from（单一真相源）")
        ok(fm.get("derived_relation") == "derived_from", "②frontmatter 落关系名")
        led = PV.load(root)
        ok(len(led) == 1 and led[0]["child"] == "n_child"
           and led[0]["parent"] == "n_a" and led[0]["rel"] == "derived_from",
           "②台账落边（child/parent/rel）")
        ok(led[0].get("batch") == "b_p42" and led[0].get("actor") == "tester",
           "②台账留痕 batch/actor（可按批回溯）")
        ok(cg.index["nodes"]["n_child"].get("derived_from") == ["n_a"],
           "②索引带声明（巡检零读文件）")

        # ------------------------------------------------ ③ 多父/关系/自环
        print("\n【3】多父 / 关系名 / 无意义边丢弃")
        cg.add("n_multi", "# 功能名：多源\n# 生效条件：条件 M\n\n由甲乙派生。",
               derived_from=["n_a", "n_b"], relation="split_from")
        me = [e for e in PV.edges(root, child="n_multi")]
        ok(len(me) == 2 and {e["parent"] for e in me} == {"n_a", "n_b"},
           "③多父建 2 条边")
        ok(all(e["rel"] == "split_from" for e in me), "③关系名落 split_from")
        cg.add("n_self", "# 功能名：自环\n\n自己派生自己。", derived_from=["n_self"])
        ok(PV.edges(root, child="n_self") == [], "③自环被丢弃（不产生无意义边）")
        cg.add("n_none", "# 功能名：无源\n\n没声明来源。")
        ok(PV.edges(root, child="n_none") == [], "③未声明来源 → 不建边")

        # ------------------------------------------------ ④ 历史不回填
        print("\n【4】历史不回填（只重放声明，不发明边）")
        ok(PV.edges(root, child="n_hist") == [],
           "④历史节点（无声明）不建链")
        root2 = tempfile.mkdtemp(prefix="mdcg_p42_hist_")
        cg2 = MdCG(root2)
        cg2.add("h1", "# 功能名：历史一\n\n说明。")
        cg2.add("h2", "# 功能名：历史二\n\n说明。")
        rep = PV.rebuild_ledger(cg2, apply=False)
        ok(rep["edges"] == 0 and rep["written"] == 0,
           "④按 frontmatter 重建 → 0 条（历史声明为空，不伪造血缘）")
        ap = PV.rebuild_ledger(cg2, apply=True)
        ok(ap["written"] == 0 and PV.load(root2) == [],
           "④重建落盘也不产生边（历史不回填）")

        # ------------------------------------------------ ⑤ 定义边界
        print("\n【5】定义边界（≠ 对端信任 P_trust）")
        from . import links as LK
        ok(os.path.basename(LK.links_file()) != os.path.basename(PV.ledger_file(root)),
           "⑤两台账落盘文件不同（_links.json 信任层 / _link.jsonl 血缘层）")
        ok(LK.LINKS_FILE_ENV != PV.LEDGER_ENV, "⑤环境变量各自独立（不共享开关）")
        ok(PV.ledger_file(root, path="X") == "X", "⑤显式 path 优先于默认")

        # ------------------------------------------------ ⑥ 悬空可检出
        print("\n【6】悬空可检出（只读、不删边）")
        cg.add("n_ghost", "# 功能名：悬空\n\n来源已不存在。",
               derived_from=["ghost_missing"])
        cg.add("n_orph", "# 功能名：孤儿\n\n父节点即将被删。", derived_from=["n_b"])
        os.remove(os.path.join(root, cg.index["nodes"]["n_b"]["path"]))
        cg.rebuild_index()
        rep = call_tool(cg, "cg", {"op": "link", "action": "derive_dangling"})
        ok(rep["ok"] is False and rep["checked"] is True,
           "⑥检出悬空（ok=False 仅表示有悬空）")
        ok(rep["readonly"] is True, "⑥标只读")
        kinds = {(r["child"], tuple(r["missing"])) for r in rep["dangling"]}
        ok(("n_ghost", ("parent",)) in kinds, "⑥父端点缺失可检出")
        ok(("n_orph", ("parent",)) in kinds, "⑥父节点被删后可检出")
        ok(all("parent" in r["missing"] for r in rep["dangling"]),
           "⑥悬空归因显式给出 missing 端点")
        ok(len(PV.load(root)) > 0, "⑥检出过程未删任何边（只报告）")

        # ------------------------------------------------ ⑦ 诊断集成
        print("\n【7】诊断集成（报警不篡改）")
        dg = sustain.diagnose(cg)
        codes = {i["code"]: i for i in dg["issues"]}
        ok("provenance_dangling" in codes, "⑦diagnose 报 provenance_dangling")
        ok(codes["provenance_dangling"]["severity"] == "info"
           and codes["provenance_dangling"]["fix"] is None,
           "⑦info 级 + 无自动修复（不自动删边）")
        ok(dg["stats"]["provenance_dangling"] == rep["dangling_count"]
           and dg["stats"]["provenance_edges"] == rep["edges"],
           "⑦stats 与巡检口径一致")
        ok(dg["provenance"] is not None and dg["ok"] is True,
           "⑦悬空不翻转 ok（不触发自愈）")
        ok(sustain.summary(cg)["provenance"]["dangling"] == rep["dangling_count"],
           "⑦summary 含派生溯源摘要")

        # ------------------------------------------------ ⑧ 失败不阻断写入
        print("\n【8】硬约束：建链失败不阻断写入")
        orig_append = PV.append
        PV.append = lambda *a, **k: (_ for _ in ()).throw(
            PV.ProvenanceError("模拟磁盘故障"))
        try:
            nid = cg.add("n_fail", "# 功能名：失败\n\n建链会失败。",
                         derived_from=["n_a"], actor="tester")
            ok(nid == "n_fail" and "n_fail" in cg.index["nodes"],
               "⑧节点照常落库（写入未被阻断）")
            ok(cg.get("n_fail")["frontmatter"].get("derived_from") == ["n_a"],
               "⑧声明仍写进 frontmatter（不丢事实）")
            fail_recs = read_jsonl(PV.fail_log_file(root))
            ok(any(r.get("child") == "n_fail" and r.get("code") == "ledger_io"
                   for r in fail_recs),
               "⑧降级写 .fail 留痕（可事后补链）")
            ok(PV.edges(root, child="n_fail") == [], "⑧台账确实没写上（如实反映）")
        finally:
            PV.append = orig_append

        # ------------------------------------------------ ⑨ 非法关系名
        print("\n【9】非法关系名不阻断写入")
        cg.add("n_badrel", "# 功能名：非法关系\n\n关系名写错。",
               derived_from=["n_a"], relation="not_a_relation")
        br = PV.edges(root, child="n_badrel")
        ok(len(br) == 1 and br[0]["rel"] == PV.DEFAULT_RELATION,
           "⑨非法关系名回退默认值（不阻断、不落坏字段）")

        # ------------------------------------------------ ⑩ 台账是派生物
        print("\n【10】台账是派生物（可兜底、可重建）")
        os.remove(PV.ledger_file(root))
        rep2 = PV.check(cg)
        ok(rep2["ledger_exists"] is False and rep2["edges"] > 0,
           "⑩台账删除后仍由索引声明兜底（血缘不丢）")
        cg.add("n_child2", "# 功能名：子二\n\n由甲派生。", derived_from=["n_a"])
        run = PV.rebuild_ledger(cg, apply=True)
        ok(os.path.exists(PV.ledger_file(root)) and run["written"] == run["edges"],
           "⑩rebuild 按声明恢复台账")
        ok(PV.edges(root, child="n_fail") != [],
           "⑩重建顺带救回「建链失败」的声明边（不发明关系）")
        rb = call_tool(cg, "cg", {"op": "link", "action": "derive_rebuild"})
        ok(rb["dry_run"] is True and rb["written"] == 0, "⑩MCP rebuild 默认预演不动盘")

        # ------------------------------------------------ (11) MCP 接入
        print("\n【11】MCP 接入")
        ls = call_tool(cg, "cg", {"op": "link", "action": "derive", "child": "n_multi"})
        ok(ls["readonly"] is True and len(ls["edges"]) == 2, "(11)link derive 按 child 过滤")
        mp = call_tool(cg, "cg", {"op": "sustain", "action": "provenance"})
        ok(mp["checked"] is True and mp["dangling_count"] == rep["dangling_count"],
           "(11)sustain provenance 与 link derive_dangling 同源")
        w = call_tool(cg, "mdcg_remember", {
            "node_id": "n_mcp", "content": "# 功能名：MCP\n\n经 MCP 写入。",
            "derived_from": "n_a,n_b", "relation": "merged_from",
            "consistency": False, "batch": "b_mcp"})
        edges = PV.edges(root, child="n_mcp")
        ok(w.get("ok") is True and len(edges) == 2,
           "(11)write 路径 derived_from='a,b' 拆分为 2 条边")
        ok(all(e["rel"] == "merged_from" for e in edges), "(11)MCP 关系名透传")

        # ------------------------------------------------ (12) 巡检只读
        print("\n【12】巡检只读（不改节点、不动台账）")
        before = {nid: _digest(cg, nid) for nid in cg.index["nodes"]}
        led_before = open(PV.ledger_file(root), "rb").read()
        for _ in range(2):
            call_tool(cg, "cg", {"op": "link", "action": "derive_dangling"})
            call_tool(cg, "cg", {"op": "sustain", "action": "provenance"})
        after = {nid: _digest(cg, nid) for nid in cg.index["nodes"]}
        ok(before == after, "(12)节点逐字节不变")
        ok(open(PV.ledger_file(root), "rb").read() == led_before,
           "(12)台账未被巡检改动")

        # ------------------------------------------------ (13) 未知 action
        print("\n【13】未知 action 不静默成功")
        try:
            call_tool(cg, "cg", {"op": "link", "action": "derive_x"})
            ok(False, "(13)必须报错")
        except ValueError as e:
            ok("未知 action" in str(e), "(13)未知 action 报错")
    finally:
        for d in (root, root2):
            if d:
                shutil.rmtree(d, ignore_errors=True)

    print("\n" + "=" * 70)
    print(f"P42 结果：PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        print("未通过：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
