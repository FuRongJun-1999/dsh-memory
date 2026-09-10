# -*- coding: utf-8 -*-
"""md_cg · 第 8 篇：嵌套子图 + 关系链检索（结构 S / 检索 R 的补强）

覆盖：
  A 嵌套子图（结构）：引用式写入 / 递归展开 / 数据驱动深度 / 硬截断 /
     flatten 对称父子边 / 层级路径 / 树一致性（多父·环·悬空·自环）/ 根
  B 关系链（因果链＝条件链）：多跳 / 方向 / visited 剪枝 / 权重累积 /
     条件序列 / 排序 / 种子扩散打分 / 层级边参与
  C 检索接入：chain 路召回链下游 / provenance 带条件序列 / 默认路不受影响 /
     公开 API 面

运行：python -m md_cg.test_p8_subgraph_chain
"""
from __future__ import annotations

import tempfile

from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def ccg(title, cond="任意情境", sub="验收", exe="直接调用", verify="test", body=""):
    return (f"# 功能名：{title}\n"
            f"# 生效条件：{cond}\n"
            f"# 子功能：{sub}\n"
            f"# 执行：{exe}\n"
            f"# 验证方式：{verify}\n"
            f"# 不适用条件：无\n"
            f"{body or title}\n")


def main():
    root = tempfile.mkdtemp(prefix="mdcg_p8_")
    cg = MdCGOS(root)
    try:
        # ================= A. 嵌套子图 =================
        print("\n[A] 嵌套子图（结构要素可递归化）")
        cg.add("r", ccg("根", body="根节点"), subgraph=["a", "b"])
        cg.add("a", ccg("中间", body="中间节点"), subgraph=["a1"])
        cg.add("a1", ccg("叶一层", body="叶一层"), subgraph=["a1x"])
        cg.add("a1x", ccg("叶二层", body="叶二层"))
        cg.add("b", ccg("旁支", body="旁支节点"))

        check("subgraph 引用式写入并读回",
              (cg.get("r") or {}).get("frontmatter", {}).get("subgraph") == ["a", "b"])
        from . import subgraph as sg
        check("children 解析（声明式）", sg.children(cg, "r") == ["a", "b"], str(sg.children(cg, "r")))
        check("索引快照含 subgraph（免读文件）",
              "subgraph" in cg.index["nodes"].get("r", {}))

        ex = cg.subgraph_expand("r")                       # 数据驱动：展开到自然耗尽
        check("递归展开 5 节点", ex["n_nodes"] == 5, str(sorted(ex["nodes"])))
        check("层级路径正确",
              ex["paths"].get("a1x") == "r/a/a1/a1x", str(ex["paths"]))
        check("父子边 part_of 方向 child→parent",
              all(e["relation_type"] == "part_of" for e in ex["edges"]) and ex["n_edges"] == 4)
        check("自然耗尽不置 truncated", ex["truncated"] is False)

        ex1 = cg.subgraph_expand("r", max_depth=1)
        check("max_depth=1 硬截断且置 truncated",
              ex1["n_nodes"] == 3 and ex1["truncated"] is True, str(sorted(ex1["nodes"])))

        fl = cg.subgraph_flatten("r")
        check("flatten 生成对称父子边（4 对 → 8 条）", fl["n_edges"] == 8, str(fl["n_edges"]))
        rels = {e["relation_type"] for e in fl["edges"]}
        check("flatten 同时含 part_of / parent_of",
              rels == {"part_of", "parent_of"}, str(rels))
        check("roots 识别根节点", "r" in cg.subgraph_roots(), str(cg.subgraph_roots()))

        # 树一致性
        cg.add("m", ccg("第二父", body="第二父"), subgraph=["a"])          # 多父
        cg.add("x", ccg("环x", body="环x"), subgraph=["y"])                # 环
        cg.add("y", ccg("环y", body="环y"), subgraph=["x"])
        cg.add("d", ccg("悬空", body="悬空"), subgraph=["ghost"])          # 悬空
        cg.add("s", ccg("自环", body="自环"), subgraph=["s"])              # 自环
        val = cg.subgraph_validate(limit=50)
        issues = {i["issue"] for i in val["items"]}
        check("检出 multi_parent", "multi_parent" in issues, str(sorted(issues)))
        check("检出 cycle", "cycle" in issues, str(sorted(issues)))
        check("检出 dangling_child", "dangling_child" in issues, str(sorted(issues)))
        check("检出 self_loop", "self_loop" in issues, str(sorted(issues)))

        # ================= B. 因果链＝条件链 =================
        print("\n[B] 关系链（causal = 条件依赖因果；链 = 条件序列）")
        cg.add("db", ccg("数据库", cond="数据库已启动", body="数据库服务"),
               edges=[{"target": "svc", "relation_type": "causal",
                       "confidence": 0.9, "condition": "数据库在运行"}])
        # causal 方向 = 依赖方向（基础→应用）：db 是 svc 成立的条件
        cg.add("svc", ccg("服务层", cond="数据库在运行", body="服务层"),
               edges=[{"target": "api", "relation_type": "causal",
                       "confidence": 1.0, "condition": "服务在运行"}])
        cg.add("api", ccg("接口层", cond="服务在运行", body="接口层"))
        cg.add("job", ccg("定时任务", cond="服务在运行", body="定时任务"),
               edges=[{"target": "job2", "relation_type": "sequential",
                       "confidence": 1.0, "condition": "顺序执行"}])
        cg.add("job2", ccg("定时任务下一步", body="定时任务下一步"))

        chains = cg.causal_chain("db", max_depth=5)
        depths = sorted(c["depth"] for c in chains)
        check("多跳展开（db→svc→api 共 2 条链）", depths == [1, 2], str(depths))
        two = [c for c in chains if c["depth"] == 2][0]
        check("链节点序列正确", two["nodes"] == ["db", "svc", "api"], str(two["nodes"]))
        check("累积权重 = Π(类型base × 置信度)",
              abs(two["weight"] - (0.85 * 0.9) * (0.85 * 1.0)) < 1e-6, str(two["weight"]))
        check("条件序列逐跳标注",
              two["conditions"] == ["数据库在运行", "服务在运行"], str(two["conditions"]))
        check("只走 causal（不含 sequential）",
              all("job" not in c["nodes"] for c in chains))

        seq = cg.causal_chain("job", relation_types=("sequential",))
        check("relation_types 过滤生效",
              len(seq) == 1 and seq[0]["nodes"] == ["job", "job2"], str(seq))
        check("causal 过滤下不含 sequential 边",
              cg.causal_chain("job", relation_types=("causal",)) == [])

        back = cg.causal_chain("api", direction="in", relation_types=("causal",))
        check("direction=in 反向可达", any("db" in c["nodes"] for c in back))

        # 环不无限（visited 剪枝）
        cg.add("p", ccg("环p", body="环p"), edges=[{"target": "q", "relation_type": "causal"}])
        cg.add("q", ccg("环q", body="环q"), edges=[{"target": "p", "relation_type": "causal"}])
        cyc = cg.causal_chain("p", max_depth=10)
        check("visited 剪枝：环链不无限增长", all(c["depth"] <= 1 for c in cyc), str([c["depth"] for c in cyc]))

        ex_chain = cg.explain_chain("db")
        check("explain 输出「条件→结果」步骤",
              ex_chain["count"] >= 1 and ex_chain["chains"][0]["步骤"][0]["条件"] == "数据库在运行",
              str(ex_chain["chains"][0]["步骤"][0] if ex_chain["chains"] else None))

        # 节点生效条件回退（边无条件时用起点节点声明的条件）
        cg.add("z1", ccg("起点", cond="午夜窗口", body="起点"),
               edges=[{"target": "z2", "relation_type": "causal", "confidence": 1.0}])
        cg.add("z2", ccg("终点", body="终点"))
        zc = cg.causal_chain("z1")[0]
        check("边无条件 → 回退节点生效条件", zc["conditions"][0] == "午夜窗口", str(zc["conditions"]))

        from . import chain as ch
        best = ch.expand_from_seeds(cg, {"db": 1.0}, relation_types=("causal",),
                                    max_depth=5, decay=0.9)
        want = 1.0 * (0.85 * 0.9) * 0.9
        check("种子扩散打分 = 种子 × 链权 × decay^跳",
              abs(best["svc"]["score"] - want) < 1e-6, str(best.get("svc", {}).get("score")))

        # 层级边参与链
        hier = cg.causal_chain("r", relation_types=("part_of",), max_depth=2)
        check("层级 part_of 边参与链遍历",
              any("a" in c["nodes"] for c in hier), str([c["nodes"] for c in hier]))

        # ================= C. 检索接入 =================
        print("\n[C] 检索接入（chain 路 + 可审计 provenance）")
        results, meta = cg.search_rrf("数据库在运行",
                                      paths=("lexical", "entity", "chain"), k=8)
        got = [r[0].get("id") for r in results]
        check("chain 路召回链下游节点", ("svc" in got) or ("api" in got), str(got))
        prov = meta.get("provenance") or {}
        chained = [nid for nid, items in prov.items()
                   if any(p.get("path") == "chain" for p in items)]
        check("provenance 标注 chain 路", bool(chained), str(chained))
        with_cond = [p for items in prov.values() for p in items
                     if p.get("path") == "chain" and p.get("conditions")]
        check("provenance 带条件序列（可审计）",
              bool(with_cond) and any(p["conditions"] for p in with_cond), str(with_cond[:1]))

        _dr, dmeta = cg.search_rrf("数据库在运行", k=8)
        dpaths = set()
        for items in (dmeta.get("provenance") or {}).values():
            for p in items:
                dpaths.add(p.get("path"))
        check("默认检索路不含 chain（不改变既有基线）", "chain" not in dpaths, str(sorted(dpaths)))

        check("公开 API：subgraph_expand/flatten/validate/roots",
              all(hasattr(cg, n) for n in ("subgraph_expand", "subgraph_flatten",
                                           "subgraph_validate", "subgraph_roots")))
        check("公开 API：causal_chain/explain_chain",
              all(hasattr(cg, n) for n in ("causal_chain", "explain_chain")))
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n==== P8 结果：{PASS} 通过 / {FAIL} 失败 ====")
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
