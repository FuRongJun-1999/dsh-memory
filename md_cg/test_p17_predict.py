# -*- coding: utf-8 -*-
"""md_cg · 第 17 篇：生成式预测 + 因果推理

理论出处（对齐 AEIS 原 MCP 服务）：
  · `docker/aeis_context/prediction.py`（PREDICTION-COMPLETION-PLAN-REV1-20260813-001）
    四通道预测引擎的通道 3（生成式·因果路线图）+ 通道 4（语义式，经因果过滤门）
  · `md_cg/chain.py`：causal = 条件依赖因果（A 是 B 成立的条件），链 = 条件序列

覆盖：
  A D-001 局部路径生成 + uncertainty_bound（候选未来，非必然未来）
  B D-002 伪因果过滤门（因果链 / 共同父节点 / 拒绝纯语义邻近）
  C D-003 局部线性近似 + extrapolation_validity（smooth/jump/unknown）
  D D-004 T_pred 四维评分（trend .40 / boundary .20 / verification .25 / balance .15）
  E D-005 AttentionPolicy 适配 + 降级
  F D-006 命中率动态校准（命中 → 边 +0.05；未命中 → rejected）
  G 盲区驱动（unresolved / 不可预测声明拒绝生成）
  H 因果路径推理（可达性 = 伪因果防护的完整语义）
  I MCP 入口（mdcg_predict / mdcg_causal / cg op=predict|causal）
  J 自描述

运行：python -m md_cg.test_p17_predict
"""
from __future__ import annotations

import tempfile

from .mdcos import MdCGOS
from . import predict
from . import chain

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


class _Pol:
    """D-005 AttentionPolicy 适配器（duck-typed get_weights）。"""

    def __init__(self, weights):
        self._w = weights

    def get_weights(self):
        return dict(self._w)


def _edge_conf(cg, src, tgt):
    for t, e in chain.adjacency(cg).get(src) or []:
        if t == tgt:
            try:
                return float(e.get("confidence", 1.0))
            except (TypeError, ValueError):
                return 1.0
    return None


def _find_route(routes, path):
    for r in routes:
        if r["path"] == path:
            return r
    return None


def main():
    root = tempfile.mkdtemp(prefix="mdcg_p17_")
    cg = MdCGOS(root)

    # ---------- 图：a→b→c,d（因果/时序），p1→b,x（共同父节点），x 语义邻近 a ----------
    cg.add("a", "# 功能名：数据库连接池配置与超时参数\n"
                "# 生效条件：高并发时\n# 不适用条件：单机无并发\n",
           layer="knowledge", tags=["boundary"], importance=0.6,
           verification_basis="test",
           edges=[{"target": "b", "relation_type": "causal",
                   "condition": "需要 A 成立", "confidence": 0.8}])
    cg.add("b", "# 功能名：B 依赖 A 成立\n# 生效条件：A 可用\n",
           layer="knowledge", importance=0.6, verification_basis="test",
           edges=[{"target": "c", "relation_type": "causal",
                   "condition": "需要 B 成立", "confidence": 0.9},
                  {"target": "d", "relation_type": "sequential",
                   "condition": "随后执行", "confidence": 0.7}])
    cg.add("c", "# 功能名：C 依赖 B 成立\n",
           layer="knowledge", importance=0.6, verification_basis="test")
    cg.add("d", "# 功能名：D 在 B 之后执行\n",
           layer="knowledge", importance=0.6, verification_basis="test")
    cg.add("x", "# 功能名：数据库连接池配置与超时参数（近义描述）\n"
                "# 生效条件：高并发时\n",
           layer="knowledge", importance=0.6, verification_basis="test")
    cg.add("p1", "# 功能名：公共前提\n",
           layer="knowledge", importance=0.6, verification_basis="test",
           edges=[{"target": "b", "relation_type": "causal",
                   "condition": "公共前提", "confidence": 0.7},
                  {"target": "x", "relation_type": "causal",
                   "condition": "公共前提", "confidence": 0.7}])

    # ---------- A. D-001 局部路径生成 ----------
    print("\n[A] D-001 局部路径生成 + uncertainty_bound")
    res = cg.predict_routes(start_id="a", horizon=2, semantic=False)
    check("A1 生成成功", res["status"] == "ok" and res["start_id"] == "a",
          res["status"])
    check("A2 三条局部路线（a→b / a→b→c / a→b→d）",
          res["meta"]["n_routes"] == 3
          and all(_find_route(res["routes"], p) is not None
                  for p in (["a", "b"], ["a", "b", "c"], ["a", "b", "d"])),
          str([r["path"] for r in res["routes"]]))
    r_abc = _find_route(res["routes"], ["a", "b", "c"])
    check("A3 置信度为边置信度连乘（0.8×0.9=0.72）",
          r_abc and abs(r_abc["confidence"] - 0.72) < 1e-6,
          str(r_abc and r_abc["confidence"]))
    check("A4 uncertainty_bound 字段齐备",
          r_abc and set(r_abc["uncertainty_bound"]) == {
              "confidence", "lower", "upper", "method"},
          str(r_abc and sorted(r_abc["uncertainty_bound"])))
    check("A5 不确定带上下界 = conf ± (1-conf)/2",
          r_abc and abs(r_abc["uncertainty_bound"]["lower"] - 0.58) < 1e-6
          and abs(r_abc["uncertainty_bound"]["upper"] - 0.86) < 1e-6,
          str(r_abc and r_abc["uncertainty_bound"]))
    check("A6 明示「候选未来，非必然未来」",
          "候选未来" in res["meta"].get("note", ""), res["meta"].get("note"))
    res_big = cg.predict_routes(start_id="a", horizon=999, semantic=False)
    check("A7 horizon 硬上限裁剪", res_big["meta"]["horizon"] == predict.HORIZON_HARD,
          str(res_big["meta"]["horizon"]))
    check("A8 起点不存在 → start_not_found",
          cg.predict_routes(start_id="nope")["status"] == "start_not_found",
          cg.predict_routes(start_id="nope")["status"])

    # ---------- B. D-002 伪因果过滤门 ----------
    print("\n[B] D-002 伪因果过滤门（语义邻近须能说清关系）")
    ok, why = cg.causal_gate("a", "b")
    check("B1 因果/时序边直通", ok is True and why == "causal_link", why)
    ok, why = cg.causal_gate("b", "x")
    check("B2 共同父节点 → 结构模式豁免",
          ok is True and why == "structural_pattern", why)
    ok, why = cg.causal_gate("a", "x")
    check("B3 纯语义邻近 → 拒绝（伪因果）",
          ok is False and why == "rejected_semantic_only", why)
    res_sem = cg.predict_routes(start_id="a", horizon=1, semantic=True)
    check("B4 无策略时语义候选不进路线",
          _find_route(res_sem["routes"], ["a", "x"]) is None,
          str([r["path"] for r in res_sem["routes"]]))

    # ---------- C. D-003 外推有效性 ----------
    print("\n[C] D-003 局部线性近似 + extrapolation_validity")
    check("C1 单跳 → unknown",
          predict.extrapolation_validity({"confs": [0.8]}) == "unknown", "")
    check("C2 平滑衰减 → smooth",
          predict.extrapolation_validity({"confs": [0.9, 0.7]}) == "smooth", "")
    check("C3 跳变 → jump",
          predict.extrapolation_validity({"confs": [0.9, 0.4]}) == "jump", "")
    check("C4 路线带 extrapolation_validity 字段",
          "extrapolation_validity" in res["routes"][0],
          str(res["routes"][0].get("extrapolation_validity")))

    # ---------- D. D-004 T_pred 四维评分 ----------
    print("\n[D] D-004 T_pred 四维评分")
    sc = r_abc["score"]
    check("D1 四维 + composite 齐备",
          set(("trend", "boundary", "verification", "balance", "composite"))
          <= set(sc), str(sorted(sc)))
    check("D2 权重 = 0.40/0.20/0.25/0.15",
          abs(sc["weights"]["trend"] - 0.40) < 1e-9
          and abs(sc["weights"]["boundary"] - 0.20) < 1e-9
          and abs(sc["weights"]["verification"] - 0.25) < 1e-9
          and abs(sc["weights"]["balance"] - 0.15) < 1e-9,
          str(sc["weights"]))
    expect = (0.40 * sc["trend"] + 0.20 * sc["boundary"]
              + 0.25 * sc["verification"] + 0.15 * sc["balance"])
    check("D3 composite 可由四维复算",
          abs(sc["composite"] - round(expect, 4)) < 1e-6,
          f"{sc['composite']} vs {round(expect, 4)}")
    check("D4 排序键 composite 单调不增",
          all(res["routes"][i]["score"]["composite"]
              >= res["routes"][i + 1]["score"]["composite"]
              for i in range(len(res["routes"]) - 1)),
          str([r["score"]["composite"] for r in res["routes"]]))

    # ---------- E. D-005 AttentionPolicy 适配 + 降级 ----------
    print("\n[E] D-005 AttentionPolicy 适配器 + 降级")
    check("E1 无策略 → 偏好权重 0.0（降级）",
          predict.preference_weight(cg, "x") == 0.0,
          str(predict.preference_weight(cg, "x")))
    cg.attention_policy = _Pol({"x": 0.9})
    ok, why = cg.causal_gate("a", "x")
    check("E2 偏好权重 > 0.5 → 准入", ok is True and why == "preference_weight", why)
    res_pol = cg.predict_routes(start_id="a", horizon=1, semantic=True)
    check("E3 有策略时语义候选进路线（source=semantic_induced）",
          _find_route(res_pol["routes"], ["a", "x"]) is not None
          and _find_route(res_pol["routes"], ["a", "x"])["last_source"]
          == "semantic_induced",
          str([(r["path"], r["last_source"]) for r in res_pol["routes"]]))
    del cg.attention_policy

    # ---------- F. D-006 命中率动态校准 ----------
    print("\n[F] D-006 命中 → 边置信度 +0.05；未命中 → rejected")
    before = _edge_conf(cg, "a", "b")
    fb = cg.predict_feedback("b", actual_node_id="b", hit=True)
    after = _edge_conf(cg, "a", "b")
    check("F1 命中 → 因果边置信度 +0.05",
          fb["hit"] is True and before is not None and after is not None
          and abs(after - (before + predict.EDGE_BOOST)) < 1e-6,
          f"{before} → {after}")
    check("F2 boosted 报告被提升的源节点", "a" in (fb.get("boosted") or []),
          str(fb.get("boosted")))
    fb2 = cg.predict_feedback("b", actual_node_id="c", hit=False,
                              note="实际走了 C")
    check("F3 未命中 → 登记负记忆 rejected",
          fb2["hit"] is False and bool(fb2.get("rejected_id")),
          str(fb2.get("rejected_id")))
    check("F4 样本 < 50 → 不触发反思，阈值 = 基线",
          fb2["reflect"] is False
          and abs(fb2["threshold"] - predict.BASE_HIT_RATE) < 1e-9
          and fb2["samples"] < predict.MIN_SAMPLES,
          f"samples={fb2['samples']} threshold={fb2['threshold']}")
    st = cg.predict_stats(limit=5)
    check("F5 stats 统计调用/反馈/命中率",
          st["calls"] >= 4 and st["feedback_samples"] == 2 and st["hits"] == 1,
          f"calls={st['calls']} fb={st['feedback_samples']} hits={st['hits']}")

    # ---------- G. 盲区驱动 ----------
    print("\n[G] 盲区驱动（unresolved / 不可预测声明）")
    bs_unknown = cg.add_unresolved(
        "如何在没有历史数据时预测数据库容量 # 可预测性：unknowable")
    found = predict.find_blindspot(cg, bs_unknown)
    check("G1 find_blindspot 命中 unresolved",
          found is not None and found["kind"] == "unresolved",
          str(found and found["kind"]))
    check("G2 predictability 解析为 unknowable",
          predict.predictability(found) == "unknowable",
          predict.predictability(found))
    r_un = cg.predict_routes(blindspot_id=bs_unknown)
    check("G3 不可预测 → 拒绝生成路线（不编造）",
          r_un["status"] == "unpredictable" and r_un["routes"] == [],
          r_un["status"])
    bs_known = cg.add_unresolved("数据库连接池配置与超时参数")
    r_bs = cg.predict_routes(blindspot_id=bs_known, horizon=1)
    check("G4 可预测 → 由锚点生成路线",
          r_bs["status"] == "ok" and r_bs["meta"].get("anchor") == "a"
          and len(r_bs["routes"]) >= 1,
          f"status={r_bs['status']} anchor={r_bs['meta'].get('anchor')}")
    check("G5 盲区不存在 → blindspot_not_found",
          cg.predict_routes(blindspot_id="no_such_blindspot")["status"]
          == "blindspot_not_found", "")

    # ---------- H. 因果路径推理 ----------
    print("\n[H] 因果路径推理（可达性 = 伪因果防护的完整语义）")
    p = cg.causal_path("a", "c")
    check("H1 a→c 可达，路径 [a,b,c]",
          p["reachable"] is True and p["path"] == ["a", "b", "c"]
          and p["length"] == 2, str(p.get("path")))
    check("H2 每跳带条件（链 = 条件序列）",
          [c["condition"] for c in p["conditions"]]
          == ["需要 A 成立", "需要 B 成立"],
          str([c["condition"] for c in p["conditions"]]))
    p2 = cg.causal_path("c", "a")
    check("H3 方向性：c→a 不可达", p2["reachable"] is False, str(p2.get("path")))
    p3 = cg.causal_path("a", "x")
    check("H4 a→x 不可达（纯语义邻近不是因果）",
          p3["reachable"] is False, str(p3.get("note")))
    p4 = cg.causal_path("", "a")
    check("H5 缺参 → ok=False", p4["ok"] is False, str(p4.get("error")))
    ch = cg.causal_chain("a", max_depth=3)
    check("H6 causal_chain 沿因果链展开", bool(ch), str(type(ch).__name__))

    # ---------- I. MCP 入口 ----------
    print("\n[I] MCP 入口（mdcg_predict / mdcg_causal / cg op）")
    from . import mcp_server as ms
    check("I1 注册 mdcg_predict",
          any(t["name"] == "mdcg_predict" for t in ms.TOOLS), "")
    check("I2 注册 mdcg_causal",
          any(t["name"] == "mdcg_causal" for t in ms.TOOLS), "")
    m1 = ms._predict_call(cg, {"action": "routes", "start_id": "a",
                               "horizon": 1, "semantic": False})
    check("I3 mdcg_predict routes", m1["status"] == "ok" and m1["routes"], "")
    m2 = ms._predict_call(cg, {"action": "catalog"})
    check("I4 mdcg_predict catalog", m2["module"] == "predict", "")
    m3 = ms._causal_call(cg, {"action": "path", "a": "a", "b": "c"})
    check("I5 mdcg_causal path", m3["reachable"] is True, str(m3.get("path")))
    m4 = ms._causal_call(cg, {"action": "gate", "a": "a", "b": "b"})
    check("I6 mdcg_causal gate", m4["admitted"] is True, m4["reason"])
    m5 = ms._cg_call(cg, {"op": "predict", "action": "stats"})
    check("I7 cg op=predict", "hit_rate" in m5 and "dynamic" in m5, "")
    m6 = ms._cg_call(cg, {"op": "causal", "action": "catalog"})
    check("I8 cg op=causal", m6["module"] == "causal"
          and "causal" in m6["types"], str(m6.get("types")))
    m7 = ms._predict_call(cg, {"action": "feedback",
                               "predicted_node_id": "c",
                               "actual_node_id": "c"})
    check("I9 mdcg_predict feedback", m7["ok"] and m7["hit"] is True, "")

    # ---------- J. 自描述 ----------
    print("\n[J] 自描述")
    cat = cg.predict_catalog()
    check("J1 六条决策齐备",
          all(d in cat["decisions"] for d in
              ("D-001", "D-002", "D-003", "D-004", "D-005", "D-006")),
          str(sorted(cat["decisions"])))
    check("J2 标注与 AEIS 的三处差异",
          len(cat["differs_from_aeis"]) == 3, str(cat["differs_from_aeis"]))
    check("J3 四维权重和 = 1.0",
          abs(sum(cat["weights"].values()) - 1.0) < 1e-9, str(cat["weights"]))
    check("J4 校准参数对齐 D-006",
          cat["calibration"]["min_samples"] == predict.MIN_SAMPLES
          and abs(cat["calibration"]["edge_boost"] - 0.05) < 1e-9,
          str(cat["calibration"]))

    # ---------- K. 命中回写不得破坏源节点 frontmatter ----------
    print("\n[K] D-006 命中回写保留原 frontmatter（密级/模态/证据计数）")
    cg.add("m1", "# 功能名：被回写的因果源节点\n",
           layer="knowledge", sensitivity="public", modality="image",
           importance=0.5, verification_basis="test",
           edges=[{"target": "m2", "relation_type": "causal",
                   "condition": "需要 m1 成立", "confidence": 0.5}])
    cg.add("m2", "# 功能名：命中目标节点\n",
           layer="knowledge", importance=0.5, verification_basis="test")
    cg.predict_feedback("m2", actual_node_id="m2", hit=True)
    fm1 = (cg.get("m1") or {}).get("frontmatter") or {}
    check("K1 密级不被降级（public 保持）",
          fm1.get("sensitivity") == "public", str(fm1.get("sensitivity")))
    check("K2 模态不被重置为 text",
          fm1.get("modality") == "image", str(fm1.get("modality")))
    check("K3 边置信度确已 +0.05（0.5→0.55）",
          abs((_edge_conf(cg, "m1", "m2") or 0.0) - 0.55) < 1e-6,
          str(_edge_conf(cg, "m1", "m2")))

    print(f"\n{'=' * 60}\n通过 {PASS} / {PASS + FAIL}")
    if FAILS:
        print("失败：" + "、".join(FAILS))
    return FAIL == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
