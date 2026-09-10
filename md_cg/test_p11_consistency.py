# -*- coding: utf-8 -*-
"""md_cg · 第 11 篇：节点间自动冲突检测（三级决策：情绪 → 反思 → 递归反思）

理论出处（本仓原文）：
  · 情绪 = 信息差二阶变化 d²D/dt²（`docs/智能的公理化基石.md` §十一）
    —— L0，独立通道，**不参与信任计算**
  · 反题 = 预测与事实冲突（同文档 :529，条件论七操作）—— L1 条件级冲突检测
  · 递归受深度/节点数/循环/信息增益门槛约束（同文档 :273）—— L2 递归反思
  · 四态路由 ACCEPT/REJECT/DEFER/BLINDSPOT（同文档 :721）
  · 知识飞轮：误差 → 补条件 → 结构更新（同文档 :725）
  · 纪律四要素同构（`docs/工作纪律_认知图条目_v1.1.json`）

覆盖：
  A L0 情绪通道：三态 / 二阶差分 / 不参与信任计算
  B L1 反思四态：ACCEPT / 自否定 REJECT / 违反纪律 REJECT / 条件互斥 DEFER / BLINDSPOT
  C L2 递归反思：沿边收敛 / 增益门槛停搜 / 深度上限 / 循环不爆炸
  D 冲突自动触发飞轮（落 unresolved）
  E 写入接入：add(consistency) 抛错 / defer 不落盘 / record 放行 / 闸门叠加
  F 留痕 / 统计 / 自描述 / health 面

运行：python -m md_cg.test_p11_consistency
"""
from __future__ import annotations

import tempfile

from .mdcos import MdCGOS
from . import consistency

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


def main():
    root = tempfile.mkdtemp(prefix="mdcg_p11_")
    cg = MdCGOS(root)

    # 既有结构：条件节点 + 纪律节点 + 无条件节点
    cg.add("k_offline",
           "# 功能：离线批处理\n# 生效条件：离线环境\n# 不适用条件：生产环境\n",
           layer="knowledge", tags=["batch"],
           non_applicable_conditions=["生产环境"], importance=0.4)
    cg.add("discipline_prod", "# 功能：生产纪律\n# 执行：禁止删除生产数据\n",
           layer="self", tags=["discipline"],
           non_applicable_conditions=["删除生产数据"], importance=0.5)
    cg.add("k_plain", "普通笔记，没有任何条件声明。", layer="knowledge",
           importance=0.3)
    cg.add("c_plain", "情景笔记，也没有条件声明。", layer="contextual",
           importance=0.3)

    # ---------- A. L0 情绪通道 ----------
    print("\n[A] L0 情绪通道（信息差二阶变化 d²D/dt²，§十一）")
    em = consistency.emotional_bias(0.1)
    check("低冲突 → approaching（信息差收敛）",
          em["bias"] == "approaching", str(em))
    check("高冲突 → avoiding（信息差扩大）",
          consistency.emotional_bias(0.9)["bias"] == "avoiding")
    check("二阶差分：冲突强度上升 → avoiding",
          consistency.emotional_bias(0.5, 0.2)["bias"] == "avoiding",
          str(consistency.emotional_bias(0.5, 0.2)))
    check("二阶差分：冲突强度回落 → 非 avoiding",
          consistency.emotional_bias(0.5, 0.6)["bias"] != "avoiding")
    check("情绪通道独立，不参与信任计算（§十一 强制）",
          "不参与信任" in em["note"], em["note"])

    # ---------- B. L1 反思四态 ----------
    print("\n[B] L1 反思（反题检测 → 四态路由）")
    r = cg.check_consistency("这是一条全新的普通记录，与既有结构无关。",
                             layer="knowledge")
    check("B1 无冲突 → ACCEPT", r["verdict"] == "ACCEPT", r["reason"])

    r = cg.check_consistency("删除生产数据", layer="self")
    check("B2 违反纪律 → REJECT（正文命中 negative.reject）",
          r["verdict"] == "REJECT"
          and any(c["type"] == "discipline" for c in r["conflicts"]),
          r["reason"])

    r = cg.check_consistency("# 功能：X\n# 生效条件：删除生产数据\n",
                             non_applicable_conditions=["删除生产数据"],
                             layer="knowledge")
    check("B3 自否定 → REJECT（自己的负条件排除自己的正条件）",
          r["verdict"] == "REJECT"
          and any(c["type"] == "self_negation" for c in r["conflicts"]),
          r["reason"])

    r = cg.check_consistency("# 功能：生产批处理\n# 生效条件：生产环境\n",
                             layer="knowledge")
    check("B4 条件互斥 → DEFER（新适用条件落在既有不适用区）",
          r["verdict"] == "DEFER" and r["conflict_strength"] >= consistency.CLASH_LOW,
          f'{r["verdict"]}/{r["conflict_strength"]}')

    r = cg.check_consistency("# 功能：某情景\n# 生效条件：某个特殊条件\n",
                             layer="contextual")
    check("B5 无可比对条件 → BLINDSPOT（不假装确定）",
          r["verdict"] == "BLINDSPOT", r["reason"])

    # ---------- C. L2 递归反思 ----------
    print("\n[C] L2 递归反思（:273 深度/节点/循环/增益门槛）")
    cg.add("e_conf", "# 功能：冲突源\n# 生效条件：条件A\n", layer="contextual",
           edges=[{"to": "s_disc"}], importance=0.4, override=True)
    cg.add("s_disc", "# 功能：区分节点\n", layer="structural",
           non_applicable_conditions=["生产环境"], importance=0.4)
    r = cg.check_consistency(
        "# 功能：待检\n# 生效条件：生产环境\n",
        non_applicable_conditions=["条件A"], layer="contextual", depth=3)
    rec = r.get("recursion") or {}
    check("C1 沿关系边两跳找到区分条件 → resolved",
          rec.get("stopped_by") == "resolved" and bool(rec.get("resolved_by")),
          str(rec))

    cg.add("e_conf", "# 功能：冲突源\n# 生效条件：条件A\n", layer="contextual",
           edges=[], importance=0.4, override=True)
    r = cg.check_consistency(
        "# 功能：待检\n# 生效条件：某条件\n",
        non_applicable_conditions=["条件A"], layer="contextual", depth=3)
    rec = r.get("recursion") or {}
    check("C2 增益门槛：候选空间不减少即停搜（:273）",
          rec.get("stopped_by") in ("gain_below_threshold", "frontier_exhausted"),
          str(rec))

    cg.add("e_conf", "# 功能：冲突源\n# 生效条件：条件A\n", layer="contextual",
           edges=[{"to": "s_disc"}], importance=0.4, override=True)
    r = cg.check_consistency(
        "# 功能：待检\n# 生效条件：生产环境\n",
        non_applicable_conditions=["条件A"], layer="contextual", depth=1)
    rec = r.get("recursion") or {}
    check("C3 深度上限受约束（depth=1 不越界）",
          rec.get("depth", 99) <= 1, str(rec))

    cg.add("l1", "# 功能：环1\n# 生效条件：条件A\n", layer="contextual",
           edges=[{"to": "l2"}], importance=0.4)
    cg.add("l2", "# 功能：环2\n# 生效条件：条件A\n", layer="contextual",
           edges=[{"to": "l1"}], importance=0.4)
    r = cg.check_consistency("# 功能：待检\n",
                             non_applicable_conditions=["条件A"],
                             layer="contextual", depth=3)
    rec = r.get("recursion") or {}
    check("C4 循环检测：环不导致无限展开",
          0 < rec.get("nodes_visited", 0) <= consistency.MAX_NODES, str(rec))

    # ---------- D. 冲突自动触发飞轮 ----------
    print("\n[D] 冲突自动触发飞轮（误差 → 补条件 → 结构更新，:725）")
    r = cg.check_consistency("# 功能：生产批处理\n# 生效条件：生产环境\n",
                             layer="knowledge", auto_flywheel=True)
    check("D1 冲突自动投递飞轮并返回 unresolved_id",
          bool(r.get("unresolved_id")), str(r.get("unresolved_id")))
    un = [n for n, e in (cg.index.get("nodes") or {}).items()
          if e.get("layer") == "unresolved"]
    check("D2 飞轮落 unresolved 条目", len(un) >= 1, str(un[:3]))

    # ---------- E. 写入接入 ----------
    print("\n[E] 写入接入（信息的修改必须与已有规则校验）")
    nid = cg.add("ok_1", "完全无关的一条新记录", layer="knowledge",
                 consistency=True)
    fm = (cg.get("ok_1") or {}).get("frontmatter") or {}
    check("E1 无冲突写入成功且留痕判定",
          bool(nid) and (fm.get("consistency") or {}).get("verdict") == "ACCEPT",
          str(fm.get("consistency")))

    try:
        cg.add("bad_1", "删除生产数据", layer="self", consistency=True)
        check("E2 违反纪律写入被拒（ConsistencyError）", False, "未抛错")
    except consistency.ConsistencyError as e:
        check("E2 违反纪律写入被拒（ConsistencyError）",
              e.verdict == "REJECT", e.reason)

    out = cg.add("bad_2", "删除生产数据", layer="self", consistency=True,
                 on_conflict="defer")
    check("E3 on_conflict=defer 不落盘",
          out is None and cg.get("bad_2") is None, str(out))

    cg.add("bad_3", "删除生产数据", layer="self", consistency=True,
           on_conflict="record")
    fm3 = (cg.get("bad_3") or {}).get("frontmatter") or {}
    check("E4 on_conflict=record 记录后放行",
          (fm3.get("consistency") or {}).get("verdict") == "REJECT",
          str(fm3.get("consistency")))

    cg.remember_gated("g_1", "删除生产数据", layer="self", consistency=True)
    check("E5 遗忘闸门叠加冲突检测：冲突内容不落盘",
          cg.get("g_1") is None, str(cg.get("g_1")))

    # ---------- F. 留痕 / 统计 / 自描述 ----------
    print("\n[F] 留痕 / 统计 / 自描述")
    vs = {x.get("verdict") for x in cg.consistency_history(limit=200)}
    check("F1 留痕覆盖四态",
          {"ACCEPT", "REJECT", "DEFER", "BLINDSPOT"} <= vs, str(sorted(vs)))
    st = cg.consistency_stats()
    check("F2 统计按判定/情绪分布",
          st["records"] > 0 and st["by_verdict"].get("REJECT", 0) > 0,
          str(st["by_verdict"]))
    cat = cg.consistency_catalog()
    check("F3 自描述三级 + 四态",
          set(cat["levels"]) == {"L0_emotion", "L1_reflect",
                                 "L2_recursive_reflect"}
          and cat["levels"]["L1_reflect"]["verdicts"] == list(consistency.VERDICTS),
          str(list(cat["levels"])))
    check("F4 自描述标注情绪通道不参与信任",
          "不参与信任" in cat["levels"]["L0_emotion"]["constraint"])
    check("F5 诚实边界声明（非语义蕴含证明）",
          "非语义蕴含" in cat["honest_boundary"], cat["honest_boundary"])
    hh = cg.health_os()
    check("F6 health 报告 consistency 面",
          "consistency" in hh.get("os", {}),
          str(hh.get("os", {}).get("consistency"))[:90])

    print(f"\n==== P11 结果：{PASS} 通过 / {FAIL} 失败 ====")
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    return FAIL == 0


if __name__ == "__main__":
    import sys
    # 用 reconfigure 而非「包一层 TextIOWrapper」：后者在 stdout 被重定向到文件时
    # 会在解释器退出阶段丢缓冲，CI 里会看不到失败原因。
    # 本用例原先缺这一步：Windows 默认 gbk 控制台下打印「d²D/dt²」的 ²(U+00B2)
    # 直接 UnicodeEncodeError，崩在**第一条断言之前**，输出只剩 725 字节——
    # 于是「P11 通过」这件事从未被真正执行过，也从未被任何人看见。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(0 if main() else 1)
