# -*- coding: utf-8 -*-
"""md_cg · 第 16 篇：自我状态层（薄自我 + 富索引）

理论出处（本仓原文）：
  · `docs/灵枢_自我层定义.md:6`：SELF 层 = 身份 + 价值观 + 图接口，
    不可遗忘、跨会话自动加载，且**是薄的**（不该变成事件仓库）。
  · 智能论 §十一：情绪 = 信息差二阶 d^2D/dt^2；§十：P_gap / P_trust；
    情感 = 信任二阶 d^2T/dt^2。

覆盖：
  A 薄卡建立：九项自我信息 → 当前值 + 指针；无数据不编造
  B 幂等刷新：状态未变不写盘
  C 版本链：version +1 / prev_state_hash / 留痕对齐
  D 派生自洽：情绪由 d2 推出，与 metacognition 一致
  E 信任面：verify 留痕 → P_trust / 情感
  F 五维索引：task/person/session/time/trust 反查详情（认知图连接，非搬运）
  G 关系：有向 / 双向 / 自环拒绝
  H 保护一致：状态卡可覆盖但不可遗忘；身份锚点两者皆禁
  I 篡改检测：绕过 refresh 改卡 → audit 报 log_tail_mismatch
  J 启动加载：bootstrap
  K MCP 入口 / L 自描述

运行：python -m md_cg.test_p16_self_state
"""
from __future__ import annotations

import tempfile

from .mdcos import MdCGOS
from .mdcg import STATE_ACCEPT, STATE_REJECT
from . import self_state as ss
from . import protect

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
    return [({"id": "x", "frontmatter": {}, "content": "", "path": "x"},
             1.0, {"state": state})]


S = "self:lingshu"
ALICE = "user:alice"


def main():
    root = tempfile.mkdtemp(prefix="mdcg_p16_")
    cg = MdCGOS(root)

    # ---------- A. 薄卡建立 ----------
    print("\n[A] 薄自我：九项自我信息 → 当前值 + 指针（无数据不编造）")
    r0 = cg.self_state_refresh(S)
    st = cg.self_state_snapshot(S)
    check("A1 状态卡单例建立", st is not None and st["node_id"] == ss.state_node_id(S),
          str((st or {}).get("node_id")))
    check("A2 无反思留痕 → 情绪 unknown（不编造）",
          st["emotion"] == "unknown", f"emotion={st['emotion']}")
    check("A3 无验证留痕 → 情感 unknown（不编造）",
          st["affect"] == "unknown", f"affect={st['affect']}")
    check("A4 短期记忆只存摘要 + 指针",
          isinstance(st["short_term"], dict) and "ptr" in st["short_term"],
          str(st["short_term"]))
    check("A5 九项自我信息字段齐备",
          all(k in st for k in ("information_gap", "trust", "emotion",
                                "affect", "short_term", "importance_self",
                                "identity_ref", "relations", "prediction")),
          str(sorted(k for k in st if k in (
              "information_gap", "trust", "emotion", "affect", "short_term",
              "importance_self", "identity_ref", "relations", "prediction"))))
    check("A6 首次刷新 version=1", r0["state_version"] == 1,
          str(r0["state_version"]))

    # ---------- B. 幂等 ----------
    print("\n[B] 幂等刷新（状态未变不写盘）")
    r1 = cg.self_state_refresh(S)
    r2 = cg.self_state_refresh(S)
    check("B1 无新信息 → changed=False（幂等）",
          r1["changed"] is False, str(r1.get("note")))
    check("B2 再次刷新仍幂等", r2["changed"] is False, str(r2.get("note")))
    check("B3 幂等时不推进版本",
          cg.self_state_snapshot(S)["state_version"] == 1,
          str(cg.self_state_snapshot(S)["state_version"]))

    # ---------- C. 版本链 ----------
    print("\n[C] 版本链：version +1 / prev_state_hash / 留痕对齐")
    cg.reflect("自我层一致性", _r(STATE_ACCEPT))
    cg.reflect("自我层一致性", _r(STATE_ACCEPT))
    r3 = cg.self_state_refresh(S)
    check("C1 状态变化 → version+1", r3["state_version"] == 2,
          str(r3["state_version"]))
    check("C2 prev_state_hash == 上一版 hash",
          r3["prev_state_hash"] == r0["state_hash"],
          f"{r3['prev_state_hash']} vs {r0['state_hash']}")
    hist = cg.self_state_history(limit=5, subject=S)
    check("C3 留痕末条 hash == 卡 hash",
          hist[0]["state_hash"] == r3["state_hash"],
          f"{hist[0]['state_hash']} vs {r3['state_hash']}")
    check("C4 留痕版本递增",
          [h["version"] for h in hist[:3]] == [2, 1],
          str([h["version"] for h in hist[:3]]))

    # ---------- D. 派生自洽 ----------
    print("\n[D] 派生自洽：情绪 = d^2D/dt^2（与 metacognition 同口径）")
    st = cg.self_state_snapshot(S)
    tr = cg.metacognition_trace()
    check("D1 d2 有值 → emotion 非 unknown",
          st["information_gap"]["d2"] is not None
          and st["emotion"] != "unknown",
          f"d2={st['information_gap']['d2']} emotion={st['emotion']}")
    check("D2 卡上 emotion == metacognition.trace().emotion",
          st["emotion"] == tr["emotion"],
          f"{st['emotion']} vs {tr['emotion']}")

    # ---------- E. 信任面 ----------
    print("\n[E] 信任面：verify 留痕 → P_trust / 情感 d^2T/dt^2")
    for i in range(6):
        cg.add(f"ev{i}", f"# 功能：证据样本 {i}\n", layer="knowledge",
               importance=0.5)
        cg.verify(f"ev{i}", "实测通过", "confirmed")
    cg.self_state_refresh(S, force=True)
    st = cg.self_state_snapshot(S)
    check("E1 P_trust 由验证留痕算出",
          st["trust"]["p_trust"] is not None,
          f"p_trust={st['trust']['p_trust']}")
    check("E2 信任档入索引（low|mid|high）",
          st["trust"]["band"] in ("low", "mid", "high"),
          str(st["trust"]["band"]))
    check("E3 情感由 d^2T/dt^2 推出",
          st["affect"] != "unknown" or st["trust"]["d2t"] is None,
          f"d2t={st['trust']['d2t']} affect={st['affect']}")

    # ---------- F. 五维索引 ----------
    print("\n[F] 五维索引：具体任务/人物/会话/时间/信任 → 反查详情")
    cg.self_state_refresh(S, dimensions={
        "task": "自我层一致性", "person": ALICE, "session": "s-20260909"})
    check("F1 任务维度命中状态卡",
          any(x["node_id"] == ss.state_node_id(S)
              for x in cg.self_state_index("task", "自我层一致性")["items"]),
          str(cg.self_state_index("task", "自我层一致性")["count"]))
    check("F2 会话维度命中",
          cg.self_state_index("session", "s-20260909")["count"] >= 1,
          str(cg.self_state_index("session", "s-20260909")["count"]))
    # 具体详情节点留在原层，只带同名维度标签即可被索引到（薄自我不搬运内容）
    cg.add("detail_task_1", "# 功能名：任务详情\n# 生效条件：一致性审计时\n",
           layer="contextual", tags=["task:自我层一致性"], importance=0.6)
    idx = cg.self_state_index("task", "自我层一致性", with_content=True)
    check("F3 认知图连接：详情节点被同一索引反查到",
          idx["count"] >= 2
          and any(x["node_id"] == "detail_task_1" for x in idx["items"]),
          str([x["node_id"] for x in idx["items"]]))
    check("F4 时间维度自动登记",
          bool(cg.self_state_dimensions(S)["dimensions"].get("time")),
          str(cg.self_state_dimensions(S)["dimensions"].get("time")))
    check("F5 未知维度被拒",
          cg.self_state_index("mood", "x")["ok"] is False,
          str(cg.self_state_index("mood", "x")))

    # ---------- G. 关系 ----------
    print("\n[G] 关系：有向 / 双向 / 自环拒绝")
    g1 = cg.self_state_relate(S, ALICE, relation_type="collaborator",
                              strength=0.8)
    check("G1 写有向关系", g1["ok"] and len(g1["written"]) == 1, str(g1))
    check("G2 自环被拒",
          cg.self_state_relate(S, S)["ok"] is False,
          str(cg.self_state_relate(S, S)))
    g3 = cg.self_state_relate(ALICE, "agent:reviewer", reciprocal=True)
    check("G3 reciprocal 写双向", g3["ok"] and len(g3["written"]) == 2, str(g3))
    rels = cg.self_state_relations(S)
    check("G4 出度统计正确", len(rels) == 1 and rels[0]["to"] == ss._slug(ALICE),
          str([(r["from"], r["to"]) for r in rels]))
    cg.self_state_refresh(S, force=True)
    check("G5 关系度入薄卡",
          cg.self_state_snapshot(S)["relations"]["out"] == 1,
          str(cg.self_state_snapshot(S)["relations"]))

    # ---------- H. 保护一致 ----------
    print("\n[H] 保护一致：状态卡可覆盖但不可遗忘；身份锚点两者皆禁")
    nid = ss.state_node_id(S)
    imm, why = protect.is_immutable(cg, nid)
    check("H1 状态卡可覆盖（自我状态能演化）", imm is False, str(why))
    pro, _ = protect.is_protected(cg, nid)
    check("H2 状态卡不可遗忘", pro is True, "")
    cg.identity_anchor(S, "我是灵枢：认知图的操作者，自我层不可遗忘。")
    anchor_id = (cg.identity_profile(S) or {}).get("anchor", {}) or {}
    anchor_id = anchor_id.get("node_id")
    check("H3 身份锚点两者皆禁",
          bool(anchor_id) and protect.is_immutable(cg, anchor_id)[0] is True
          and protect.is_protected(cg, anchor_id)[0] is True,
          str(anchor_id))
    cg.self_state_refresh(S, force=True)
    check("H4 identity_ref 指向锚点",
          cg.self_state_snapshot(S)["identity_ref"] == anchor_id,
          f"{cg.self_state_snapshot(S)['identity_ref']} vs {anchor_id}")

    # ---------- I. 审计 ----------
    print("\n[I] 一致性审计：可重算，能抓到绕过 refresh 的改动")
    au = cg.self_state_audit(S)
    check("I1 健康态 verdict=consistent",
          au["verdict"] == "consistent",
          f"verdict={au['verdict']} issues={[i['code'] for i in au['issues']]}")
    # 绕过 refresh 直接覆写状态卡 → 卡上 state_hash 丢失 → 留痕不对齐
    cg.add(nid, "# 被外部改写的状态卡\n", layer="self",
           importance=1.0, override=True, self_state=True)
    au2 = cg.self_state_audit(S)
    check("I2 篡改被检出 log_tail_mismatch",
          any(i["code"] == "log_tail_mismatch" for i in au2["issues"]),
          str([i["code"] for i in au2["issues"]]))
    check("I3 篡改 → verdict=broken", au2["verdict"] == "broken",
          au2["verdict"])
    cg.self_state_refresh(S, force=True)          # 修复
    check("I4 refresh 后恢复一致",
          cg.self_state_audit(S)["verdict"] == "consistent",
          str([i["code"] for i in cg.self_state_audit(S)["issues"]]))

    # ---------- J. 启动加载 ----------
    print("\n[J] 跨会话加载（bootstrap）")
    boot = cg.self_state_bootstrap(S)
    check("J1 加载状态卡 + 关系 + 索引",
          boot["ok"] and boot["state"] is not None
          and boot["relations_count"] >= 1 and "task" in boot["dimensions"],
          f"rels={boot['relations_count']} dims={list(boot['dimensions'])}")
    check("J2 最近留痕可读", len(boot["recent_states"]) >= 1,
          str(len(boot["recent_states"])))

    # ---------- K. MCP 入口 ----------
    print("\n[K] MCP 入口（mdcg_self_state + cg op + health 面）")
    from . import mcp_server as ms
    m1 = ms._self_state_call(cg, {"action": "summary", "subject": S})
    check("K1 summary 一句话", m1["ok"] and S in m1["text"], str(m1["text"]))
    m2 = ms._self_state_call(cg, {"action": "index", "dim": "person",
                                  "value": ALICE})
    check("K2 index 按人物反查", m2["ok"] and m2["count"] >= 1,
          str(m2["count"]))
    m3 = ms._self_state_call(cg, {"action": "audit", "subject": S})
    check("K3 audit 可调用", "verdict" in m3, str(m3["verdict"]))
    check("K4 MCP 注册 mdcg_self_state",
          any(t["name"] == "mdcg_self_state" for t in ms.TOOLS))
    check("K5 cg op=self_state 路由",
          ms._cg_call(cg, {"op": "self_state",
                           "action": "catalog"}).get("module") == "self_state")
    check("K6 health 报告 self_state 面",
          "self_state" in cg.health_os().get("os", {}),
          str(cg.health_os().get("os", {}).get("self_state")))

    # ---------- L. 自描述 ----------
    print("\n[L] 自描述")
    cat = cg.self_state_catalog()
    check("L1 九项自我信息齐全", len(cat["self_info"]) == 9,
          str(sorted(cat["self_info"])))
    check("L2 五维索引齐全",
          set(cat["dimensions"]) == {"task", "person", "session", "time",
                                     "trust"},
          str(cat["dimensions"]))

    # ---------- M. 第九项：预测校准面（predict → self_state 闭环）----------
    print("\n[M] 预测校准面（预测 → 事实 → 误差 → 自我更新）")
    check("M1 自描述含 prediction 项", "prediction" in cat["self_info"],
          str(sorted(cat["self_info"])))
    check("M2 无预测留痕时诚实 unknown（不编造）",
          cg.self_state_summary(S).get("hit_rate") is None,
          str(cg.self_state_summary(S).get("hit_rate")))
    cg.add("p1", "# 功能名：预测源节点\n", layer="knowledge",
           verification_basis="test",
           edges=[{"target": "p2", "relation_type": "causal",
                   "confidence": 0.5}])
    cg.add("p2", "# 功能名：预测目标节点\n", layer="knowledge",
           verification_basis="test")
    fb = cg.predict_feedback("p2", actual_node_id="p2", hit=True)
    ss_fb = fb.get("self_state") or {}
    check("M3 feedback 回执含自我模型刷新", ss_fb.get("ok") is True,
          str(ss_fb))
    check("M4 命中率已回写自我模型（1.0）",
          cg.self_state_summary(S).get("hit_rate") == 1.0,
          str(cg.self_state_summary(S).get("hit_rate")))
    au_m = cg.self_state_audit(S)
    check("M5 闭环后无 prediction_drift（自我模型跟上预测表现）",
          not any(i.get("code") == "prediction_drift"
                  for i in au_m.get("issues") or []),
          str(au_m.get("issues")))

    print(f"\n{'=' * 60}\n通过 {PASS} / {PASS + FAIL}")
    if FAILS:
        print("失败：" + "、".join(FAILS))
    return FAIL == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
