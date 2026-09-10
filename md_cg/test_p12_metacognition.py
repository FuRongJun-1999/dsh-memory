# -*- coding: utf-8 -*-
"""md_cg · 第 12 篇：独立元认知（观察自身认知的二阶单元）

理论出处（本仓原文）：
  · 情绪 = 信息差二阶变化 d²D/dt²（`docs/智能的公理化基石.md` §十一，:412-510）
  · 情感 = 信任二阶变化 d²T/dt²（同文档 :469-508）
  · 五大单元：元认知是反思/验证通道的**外部观察者**（同文档 :540-556）
  · 推论三「局部不可知」：盲区即知识（同文档 :277-288）
  · 信任 P_trust / P_gap（同文档 :393-408）
  · 导航税：显式状态记录（`docs/智能的认知过程.md`:84-86）

覆盖：
  A 轨迹：D(t) / dD/dt / d²D/dt² / 情绪 / 四态分布
  B 校准：期望 vs 实际 / gap / 分箱 / ECE / 确定性建议
  C 盲区：BLINDSPOT 邻域聚合 + unresolved 清单
  D 信任：P_gap / P_trust / 情感（d²T/dt²）
  E 报告：四观测面 + 建议带证据 + 独立留痕
  F 闸门：相似历史 → 建议分流 / 无历史 → no_prior
  G 独立性：不改 frontmatter / 不参与裁决
  H 留痕 / 自描述 / health 面

运行：python -m md_cg.test_p12_metacognition
"""
from __future__ import annotations

import json
import tempfile

from .mdcos import MdCGOS
from .mdcg import STATE_ACCEPT, STATE_REJECT, STATE_BLINDSPOT
from . import metacognition as mc

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


def _r(state):
    """构造一次检索结果（精确控制信息差 D：ACCEPT→0，其它→1）。"""
    return [({"id": "x", "frontmatter": {}, "content": "", "path": "x"},
             1.0, {"state": state})]


def main():
    root = tempfile.mkdtemp(prefix="mdcg_p12_")
    cg = MdCGOS(root)

    # ---------- A. 轨迹 ----------
    print("\n[A] 信息差轨迹（D / dD / d²D → 情绪，§十一）")
    tr0 = cg.metacognition_trace()
    check("A1 无留痕 → insufficient_data（不编造数值）",
          tr0["ok"] is False and tr0["reason"] == "insufficient_data", str(tr0))

    cg.reflect("缓存失效策略", _r(STATE_ACCEPT))
    cg.reflect("缓存失效策略", _r(STATE_ACCEPT))
    tr = cg.metacognition_trace()
    check("A2 命中 → D 收敛到 0", tr["d_current"] == 0.0, str(tr["d_current"]))
    check("A3 四态分布可读", "ACCEPT" in tr["states"], str(tr["states"]))

    cg.reflect("缓存失效策略", _r(STATE_REJECT))
    cg.reflect("缓存失效策略", _r(STATE_ACCEPT))
    tr = cg.metacognition_trace()
    check("A4 二阶差分识别收敛 → approaching",
          tr["emotion"] == "approaching",
          f'emotion={tr["emotion"]} d2={tr["d2"]}')
    check("A5 一阶方向 dD/dt 可算", isinstance(tr["d1"], float), str(tr["d1"]))

    # ---------- B. 校准 ----------
    print("\n[B] 自信校准（期望正确率 vs 实际验证通过率）")
    cal0 = cg.metacognition_calibration()
    check("B1 无证据 → insufficient_data", cal0["ok"] is False, str(cal0))

    for i in range(6):
        cg.add(f"v{i}", f"# 功能：验证样本 {i}\n", layer="knowledge",
               importance=0.5)
        cg.verify(f"v{i}", "实测通过", "confirmed")
    for i in range(3):
        cg.verify(f"v{i}", "反例", "weakened")

    cal = cg.metacognition_calibration()
    check("B2 期望/实际/gap 自洽",
          cal["ok"] and abs(cal["gap"] - (cal["expected_accuracy"]
                                          - cal["actual_accuracy"])) < 1e-6,
          str({k: cal[k] for k in ("expected_accuracy", "actual_accuracy", "gap")}))
    check("B3 ECE 非负", cal["ece"] >= 0, str(cal["ece"]))
    check("B4 分箱覆盖已观测区间", len(cal["bins"]) > 0, str(cal["bins"]))
    check("B5 判定 ∈ 四类",
          cal["verdict"] in ("calibrated", "overconfident", "underconfident",
                             "insufficient_data"), cal["verdict"])

    adv = mc._advise(
        {"ok": True, "d2": 0.0, "emotion": "stable", "state_rates": {}},
        {"verdict": "overconfident", "expected_accuracy": 0.8,
         "actual_accuracy": 0.5, "gap": 0.3},
        {"unresolved_count": 0}, {})
    check("B6 过度自信 → 建议抽查复核",
          any(a["code"] == "overconfident" for a in adv), str(adv))
    adv2 = mc._advise({"ok": False}, {"verdict": "calibrated"},
                      {"unresolved_count": 0}, {})
    check("B7 无轨迹 → 提示先积累留痕",
          any(a["code"] == "no_trace" for a in adv2), str(adv2))

    # ---------- C. 盲区 ----------
    print("\n[C] 盲区地图（推论三：局部不可知）")
    cg.reflect("量子纠缠退相干时间", _r(STATE_BLINDSPOT))
    cg.reflect("量子纠缠退相干时间", _r(STATE_BLINDSPOT))
    cg.reflect("另一个模糊问题", _r(STATE_BLINDSPOT))
    bs = cg.metacognition_blindspots()
    top = bs["items"][0] if bs["items"] else {}
    check("C1 盲区按邻域聚合", top.get("blindspot", 0) >= 2, str(top))
    check("C2 返回 unresolved 计数",
          "unresolved_count" in bs, str(bs["unresolved_count"]))

    # ---------- D. 信任 ----------
    print("\n[D] 信任（P_gap / P_trust / 情感 d²T/dt²）")
    tt = cg.metacognition_trust()
    check("D1 P_gap 可算", tt["p_gap"] is not None, str(tt["p_gap"]))
    check("D2 P_trust 来自验证留痕", tt["p_trust"] is not None, str(tt["p_trust"]))
    check("D3 情感取自二阶差分",
          tt["emotion"] in ("approaching", "avoiding", "stable"), str(tt["emotion"]))

    # ---------- E. 报告 ----------
    print("\n[E] 元认知报告（四观测面 + 建议）")
    rep = cg.metacognition_report()
    check("E1 四观测面齐全",
          all(k in rep for k in ("trace", "calibration", "blindspots", "trust")),
          str(list(rep)))
    check("E2 建议带 why/action（可复核）",
          bool(rep["advice"]) and all("why" in a and "action" in a
                                      for a in rep["advice"]),
          str([a["code"] for a in rep["advice"]]))
    check("E3 独立性声明", rep["independent"] is True and "不" in rep["note"],
          rep["note"][:40])

    # ---------- F. 闸门 ----------
    print("\n[F] 元认知闸门 self_check")
    sc = cg.self_check("量子纠缠退相干时间")
    check("F1 相似历史命中 → 建议声明盲区",
          sc["recommendation"] == "declare_blindspot" and sc["prior_attempts"] >= 2,
          str({k: sc[k] for k in ("prior_attempts", "recommendation", "warning")}))
    sc2 = cg.self_check("完全无关的全新问题 xyz")
    check("F2 无相似历史 → no_prior",
          sc2["warning"] == "no_prior"
          and sc2["recommendation"] == "search_then_decide",
          str(sc2["recommendation"]))
    check("F3 空查询被拒", cg.self_check("")["ok"] is False)

    # ---------- G. 独立性 ----------
    print("\n[G] 独立性（不参与裁决）")
    before = json.dumps(cg.get("v0")["frontmatter"], sort_keys=True,
                        ensure_ascii=False)
    cg.metacognition_report()
    cg.self_check("量子纠缠退相干时间")
    after = json.dumps(cg.get("v0")["frontmatter"], sort_keys=True,
                       ensure_ascii=False)
    check("G1 元认知不改节点 frontmatter", before == after)
    check("G2 独立性在自描述中声明",
          any(("不写" in c) or ("不参与" in c) for c in mc.catalog()["constraints"]),
          str(mc.catalog()["constraints"]))

    # ---------- H. 留痕 / 自描述 ----------
    print("\n[H] 留痕 / 自描述 / health 面")
    h = cg.metacognition_history()
    check("H1 留痕写入 _metacognition.jsonl", h["n"] > 0, str(h["n"]))
    check("H2 留痕含 report 与 self_check",
          {"report", "self_check"} <= {r.get("op") for r in h["records"]},
          str({r.get("op") for r in h["records"]}))
    cat = cg.metacognition_catalog()
    check("H3 自描述含四观测面 + 闸门",
          {"trace", "calibration", "blindspots", "trust", "self_check"}
          <= set(cat["faces"]), str(cat["faces"]))
    hh = cg.health_os()
    check("H4 health 报告 metacognition 面",
          "metacognition" in hh.get("os", {}),
          str(hh.get("os", {}).get("metacognition")))

    # MCP 入口冒烟（注册 + 两条 dispatch 路径）
    from . import mcp_server as ms
    check("H5 MCP 注册 mdcg_metacognition",
          any(t["name"] == "mdcg_metacognition" for t in ms.TOOLS))
    check("H6 cg op=metacognition 路由",
          ms._cg_call(cg, {"op": "metacognition",
                           "action": "catalog"}).get("module") == "metacognition")
    check("H7 mdcg_metacognition dispatch",
          ms._metacognition_call(cg, {"action": "trust"})["ok"] is True)

    print(f"\n==== P12 结果：{PASS} 通过 / {FAIL} 失败 ====")
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    return FAIL == 0


if __name__ == "__main__":
    import sys
    # 用 reconfigure 而非「包一层 TextIOWrapper」：后者在 stdout 被重定向到文件时
    # 会在解释器退出阶段丢缓冲，CI 里会看不到失败原因。
    # 本用例原先缺这一步：Windows 默认 gbk 控制台下打印「d²D/dt²」的 ²(U+00B2)
    # 直接 UnicodeEncodeError，崩在**第一条断言之前**，输出只剩 725 字节——
    # 于是「P12 通过」这件事从未被真正执行过，也从未被任何人看见。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(0 if main() else 1)
