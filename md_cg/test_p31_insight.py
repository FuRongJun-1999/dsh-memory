# -*- coding: utf-8 -*-
"""洞察条件层 + 情景重构 + 归纳聚类 + 盲区学习（P31 · P2 工程缺口验收）。

对照 docs §五 P2：新增 insight op（window/record/verify/list/report/
reconstruct/learn/outlook）与 consolidate.induce。验收覆盖：
  ① op 契约链：ALL_OPS == 工具 schema，insight 已授权且按 action 分级
  ② 开窗条件：C1 ≥ 0.6 ∧ 跨域 ∧ 低压力，逐闸门给出阻塞项
  ③ 洞见记账：record 缺正文报错 / 幂等 / pending；verify 无证据不判定
  ④ 证据裁决：V1 不足保持 pending，V3 / 显式裁决落 verified|falsified，
     verified 后重要度保底 0.9 且置保护位
  ⑤ CER 报告：样本 < 20 显式 insufficient 不给结论；样本足则 CER + 2×SE
  ⑥ 结构洞察：outlook 只做结构描述与差距定位，不判有效性
  ⑦ 情景重构：线索不足 → blindspot（不编造）；锚点齐 → 合成共同条件空间；
     apply 落 inferred scene 节点且幂等
  ⑧ 归纳聚类：无共同条件默认拒绝生成；apply 生成概念节点 + 对称 inferred 边；
     幂等；放宽 require_conditions 才允许无共同条件下成团
  ⑨ 盲区学习：未知 blindspot 不编造；unknowable 不生成路线；
     carried/unresolved 落 gap_hint 待补线索且幂等
  ⑩ 权限分档：output 可读不可记；写层可记账不可批量落库；guest 整 op 被拒

诚实纪律：归纳 / 重构产物一律标 inferred（非事实断言）；证据不足拒绝裁决或生成。
独立临时根，重跑 ≡ 首跑。

运行：python -m md_cg.test_p31_insight
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

from . import consolidate, insight, predict, subgraph, tokens
from .mdcos import MdCGOS
from .mcp_server import KERNEL_TOOLS, call_tool
from .security import AccessDenied, Principal

PASS = FAIL = 0
FAILS = []

# ---- 洞察条件层夹具 -------------------------------------------------------
STMT_MAIN = "离线环境下应优先选择本地缓存实现，避免远程调用放大延迟"
# C1–C8 全量条件（8 项齐 → missing 为空）
C1_OK = {"retrievability": 0.8, "outside_observer": True,
         "cross_domain": ["存储", "网络"], "premise_questioned": True,
         "pressure": "low", "continuity_turns": 3, "externalized": True,
         "tone": "curious"}
C1_BAD = {"retrievability": 0.3, "cross_domain": ["存储"], "pressure": "high"}

# ---- 归纳夹具：内容相近 + 共享「生效条件」 ---------------------------------
IND_A = ("# 功能名：离线缓存策略甲\n# 生效条件：单机离线且无外部依赖\n"
         "# 子功能：在无网络时选择本地缓存实现\n# 执行：读取本地配置并建立缓存池\n"
         "# 不适用条件：分布式多租户在线服务\n")
IND_B = ("# 功能名：离线缓存策略乙\n# 生效条件：单机离线且无外部依赖\n"
         "# 子功能：在无网络时选择本地缓存实现\n# 执行：读取本地配置并建立缓存池\n"
         "# 不适用条件：分布式多租户在线服务\n")
IND_C = ("# 功能名：离线缓存策略丙\n# 生效条件：单机离线且无外部依赖\n"
         "# 子功能：在无网络时选择本地缓存实现\n# 执行：读取本地配置并建立缓存池\n"
         "# 不适用条件：分布式多租户在线服务\n")
# 内容同样相近，但「生效条件」各不相同 → 无共同条件，默认必须拒绝归纳
NO_A = ("# 功能名：日志采样器甲\n# 生效条件：机房甲内的访问流量\n"
        "# 子功能：按固定比例采样访问日志\n# 执行：随机丢弃超出比例的记录\n"
        "# 不适用条件：计费与审计场景\n")
NO_B = ("# 功能名：日志采样器乙\n# 生效条件：机房乙内的访问流量\n"
        "# 子功能：按固定比例采样访问日志\n# 执行：随机丢弃超出比例的记录\n"
        "# 不适用条件：计费与审计场景\n")
NO_C = ("# 功能名：日志采样器丙\n# 生效条件：机房丙内的访问流量\n"
        "# 子功能：按固定比例采样访问日志\n# 执行：随机丢弃超出比例的记录\n"
        "# 不适用条件：计费与审计场景\n")

# ---- 情景重构夹具：两条记忆共享同一生效条件 -------------------------------
REC_COMMON = "上下文接近上限且任务尚未完成"
REC_A = ("# 功能名：压缩前先落盘检查点甲\n# 生效条件：%s\n"
         "# 子功能：压缩前把会话状态写入检查点文件\n# 执行：写检查点后再压缩上下文\n"
         "# 不适用条件：一次性问答任务\n") % REC_COMMON
REC_B = ("# 功能名：压缩前先落盘检查点乙\n# 生效条件：%s\n"
         "# 子功能：压缩前把会话状态写入检查点文件\n# 执行：写检查点后再压缩上下文\n"
         "# 不适用条件：一次性问答任务\n") % REC_COMMON

# ---- 盲区学习夹具 ---------------------------------------------------------
LEARN_KB = ("# 功能名：离线缓存决策知识\n# 生效条件：单机离线环境\n"
            "# 子功能：提供离线时的缓存选型判据\n# 执行：比对候选实现并给出结论\n"
            "# 不适用条件：需要强一致分布式场景\n")
LEARN_ANCHOR = ("# 功能名：离线缓存锚点条目 zkv7\n# 生效条件：单机离线环境\n"
                "# 子功能：作为离线缓存话题的检索入口 zkv7\n"
                "# 执行：指向离线缓存决策知识\n# 不适用条件：在线服务\n")
LEARN_CTX = ("# 功能名：日志采样待验证终点\n# 生效条件：机房日志采样链路\n"
             "# 子功能：尚未形成可判定结论\n# 执行：待补\n# 不适用条件：离线单机\n")
LEARN_ANCHOR2 = ("# 功能名：日志采样链路锚点条目 zxc9\n# 生效条件：机房日志采样链路\n"
                 "# 子功能：作为日志采样话题的检索入口 zxc9\n"
                 "# 执行：指向待验证终点\n# 不适用条件：离线单机\n")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def _principal(role):
    s = tokens.role_spec(role)
    return Principal(tenant="default", actor=role, clearance="internal",
                     can_write=bool(s["can_write"]), can_admin=bool(s["can_admin"]),
                     role=role, layers_allow=s["layers_allow"],
                     ops_allow=s["ops_allow"])


def _denied(fn):
    try:
        fn()
        return False
    except AccessDenied:
        return True


def main():
    print("=" * 68)
    print("md 认知图 P31 验收 · 洞察/重构/归纳/盲区学习（P2）")
    print("=" * 68)
    tmp = tempfile.mkdtemp(prefix="mdcg_p31_")
    ROOT = os.path.join(tmp, "root")
    from . import corpus
    corpus.reset_root(ROOT)
    cg = MdCGOS(ROOT, actor="p31")
    cg.principal = Principal(tenant="default", actor="p31", clearance="internal",
                             can_write=True, can_admin=True, role="designer")
    try:
        # ---------------------------------------------- ① 契约链
        print("\n【1】op 契约链与分级授权")
        tool = next(t for t in KERNEL_TOOLS if t["name"] == "cg")
        declared = set(tool["inputSchema"]["properties"]["op"]["description"].split("|"))
        check("工具 op 枚举 == ALL_OPS（防漏改）", declared == set(tokens.ALL_OPS),
              f"diff={sorted(declared ^ set(tokens.ALL_OPS))}")
        check("insight 已进 ALL_OPS", "insight" in tokens.ALL_OPS)
        check("INSIGHT_ACTIONS 覆盖 P2",
              {"window", "record", "verify", "list", "report", "reconstruct",
               "learn", "outlook"} <= set(cg.INSIGHT_ACTIONS),
              str(cg.INSIGHT_ACTIONS))
        check("insight 已授权给写层/反思/校验/输出/维持",
              all("insight" in tokens.role_spec(r)["ops_allow"]
                  for r in ("record", "reflect", "verify", "output", "sustain")))
        check("guest 未获 insight",
              "insight" not in tokens.role_spec("guest")["ops_allow"])
        cat = call_tool(cg, "cg", {"op": "insight", "action": "catalog"})
        check("catalog 自描述条件与证据类型",
              cat.get("ok") and {"reconstruct", "learn"} <= set(cat["actions"])
              and len(cat["conditions"]) == 8 and set(cat["v_types"]) == {"v1", "v2", "v3"},
              str(cat.get("actions")))

        # ---------------------------------------------- ② 归纳聚类（干净池先行）
        print("\n【2】consolidate.induce 归纳聚类")
        for nid, body in (("ind_1", IND_A), ("ind_2", IND_B), ("ind_3", IND_C),
                          ("no_1", NO_A), ("no_2", NO_B), ("no_3", NO_C)):
            cg.add(nid, body, layer="contextual", importance=0.4,
                   verification_basis="other", actor="p31")
        dry = call_tool(cg, "cg", {"op": "consolidate", "action": "induce",
                                   "min_jaccard": 0.5})
        check("induce 预演只出提案、不写盘",
              dry.get("dry_run") is True and dry.get("written") == 0
              and bool(dry.get("concepts"))
              and all(str(c) not in cg.index["nodes"] for c in dry["concepts"]),
              str(dry.get("concepts")))
        ind_prop = [p for p in (dry.get("samples") or [])
                    if set(p.get("members") or []) >= {"ind_1", "ind_2", "ind_3"}]
        check("共同条件的相似记忆成团",
              bool(ind_prop), f"clusters={dry.get('clusters')}")
        check("提炼出共同生效条件",
              bool(ind_prop) and ind_prop[0].get("common_conditions")
              == ["%s" % "单机离线且无外部依赖"],
              str(ind_prop[0].get("common_conditions")) if ind_prop else "-")
        check("无共同条件默认拒绝生成（诚实纪律）",
              int(dry.get("skipped_no_condition") or 0) >= 1
              and not any(set(p.get("members") or []) & {"no_1", "no_2", "no_3"}
                          for p in (dry.get("samples") or [])),
              f"skipped_no_condition={dry.get('skipped_no_condition')}")

        app = call_tool(cg, "cg", {"op": "consolidate", "action": "induce",
                                   "min_jaccard": 0.5, "apply": True})
        cid = (app.get("concepts") or [None])[0]
        check("induce 落盘生成概念节点", app.get("written", 0) >= 1 and bool(cid),
              str(cid))
        cnode = (cg.get(cid) or {}) if cid else {}
        cfm = cnode.get("frontmatter") or {}
        check("概念节点标 inferred（非事实断言）",
              cfm.get("verification_basis") == "other"
              and {"concept", "induced"} <= set(cfm.get("tags") or []),
              str(cfm.get("tags")))
        check("概念节点记 induced_from 成员清单",
              set(cfm.get("induced_from") or []) == {"ind_1", "ind_2", "ind_3"},
              str(cfm.get("induced_from")))
        etargets = {e.get("target") for e in (cfm.get("edges") or [])}
        check("概念 → 成员写 generalizes 边",
              {"ind_1", "ind_2", "ind_3"} <= etargets, str(sorted(etargets)))
        mfm = (cg.get("ind_1") or {}).get("frontmatter") or {}
        check("成员 → 概念写 instance_of 边",
              mfm.get("induced_concept") == cid
              and cid in {e.get("target") for e in (mfm.get("edges") or [])},
              str(mfm.get("induced_concept")))
        check("induce 留痕 _maintain.jsonl",
              any(r.get("action") == "induce"
                  for r in consolidate._read_maintain(ROOT)))

        app2 = call_tool(cg, "cg", {"op": "consolidate", "action": "induce",
                                    "min_jaccard": 0.5, "apply": True})
        check("induce 幂等（重复 apply 不重写）",
              app2.get("written") == 0 and int(app2.get("skipped_existing") or 0) >= 1,
              f"written={app2.get('written')} skip={app2.get('skipped_existing')}")
        relax = call_tool(cg, "cg", {"op": "consolidate", "action": "induce",
                                     "min_jaccard": 0.5, "require_conditions": False})
        check("放宽 require_conditions 才允许无共同条件成团",
              any(set(p.get("members") or []) >= {"no_1", "no_2", "no_3"}
                  for p in (relax.get("samples") or [])))

        # ---------------------------------------------- ③ 开窗条件
        print("\n【3】insight.window 开窗条件")
        w_ok = call_tool(cg, "cg", {"op": "insight", "action": "window",
                                    "conditions": C1_OK})
        check("C1≥0.6 ∧ 跨域 ∧ 低压力 → 开窗",
              w_ok.get("open") is True and w_ok.get("blocked_by") == [],
              str(w_ok.get("gates")))
        w_bad = call_tool(cg, "cg", {"op": "insight", "action": "window",
                                     "conditions": C1_BAD})
        check("条件不足 → 开窗被拒并给出阻塞项",
              w_bad.get("open") is False
              and {"c1_retrievable", "low_pressure"} <= set(w_bad.get("blocked_by") or []),
              str(w_bad.get("blocked_by")))
        check("开窗不宣称有效性（写进 note）",
              "verify" in str(w_ok.get("note") or ""))

        # ---------------------------------------------- ④ 情景重构
        print("\n【4】insight.reconstruct 情景重构")
        cg.add("rec_a", REC_A, layer="contextual", importance=0.5,
               verification_basis="other", actor="p31")
        cg.add("rec_b", REC_B, layer="contextual", importance=0.5,
               verification_basis="other", actor="p31")
        blind = call_tool(cg, "cg", {"op": "insight", "action": "reconstruct",
                                     "clues": ["zqxwv yykb 0009137"]})
        check("线索不足 → blindspot（不编造）",
              blind.get("status") == "blindspot"
              and not blind.get("condition_space"),
              f"status={blind.get('status')}")
        rec = call_tool(cg, "cg", {"op": "insight", "action": "reconstruct",
                                   "ids": ["rec_a", "rec_b"]})
        cs = rec.get("condition_space") or {}
        check("锚点齐 → 合成共同条件空间",
              rec.get("status") == "reconstructed"
              and REC_COMMON in (cs.get("common") or []),
              str(cs.get("common")))
        check("重构声明为近似重建（非事件回放）",
              "非事件回放" in str(rec.get("note") or "")
              and rec.get("confidence") is not None,
              str(rec.get("note"))[:80])
        rec_w = call_tool(cg, "cg", {"op": "insight", "action": "reconstruct",
                                     "ids": ["rec_a", "rec_b"], "apply": True})
        sid = rec_w.get("scene_id")
        sfm = ((cg.get(sid) or {}).get("frontmatter") or {}) if sid else {}
        check("apply 落 scene 节点（inferred，非事实层）",
              rec_w.get("scene_written") is True and bool(sid)
              and sfm.get("layer") == "contextual"
              and {"scene", "reconstructed"} <= set(sfm.get("tags") or []),
              f"sid={sid} tags={sfm.get('tags')}")
        check("scene 记 reconstructed_from",
              set(sfm.get("reconstructed_from") or []) == {"rec_a", "rec_b"},
              str(sfm.get("reconstructed_from")))
        rec_w2 = call_tool(cg, "cg", {"op": "insight", "action": "reconstruct",
                                      "ids": ["rec_a", "rec_b"], "apply": True})
        check("重构幂等（同一批锚点不重写）",
              rec_w2.get("scene_written") is False and rec_w2.get("scene_id") == sid,
              f"sid={rec_w2.get('scene_id')}")

        # ---------------------------------------------- ⑤ 盲区学习
        print("\n【5】insight.learn 盲区学习闭环")
        cg.add("learn_kb", LEARN_KB, layer="knowledge", importance=0.7,
               verification_basis="data", actor="p31")
        cg.add("learn_anchor", LEARN_ANCHOR, layer="contextual", importance=0.5,
               verification_basis="other", actor="p31",
               edges=[{"target": "learn_kb", "relation_type": "causal",
                       "confidence": 0.9, "evidence": "declared"}])
        cg.add("learn_anchor2", LEARN_ANCHOR2, layer="contextual", importance=0.5,
               verification_basis="other", actor="p31",
               edges=[{"target": "learn_ctx", "relation_type": "causal",
                       "confidence": 0.9, "evidence": "declared"}])
        cg.add("learn_ctx", LEARN_CTX, layer="contextual", importance=0.4,
               verification_basis="other", actor="p31")
        cg.add("bs_resolved", "# 可预测性：predictable\n离线缓存锚点条目 zkv7",
               layer="unresolved", importance=0.3, actor="p31")
        cg.add("bs_unknowable", "# 可预测性：unknowable\n外部世界的结构性事实",
               layer="unresolved", importance=0.3, actor="p31")
        cg.add("bs_carried", "# 可预测性：predictable\n日志采样链路锚点条目 zxc9",
               layer="unresolved", importance=0.3, actor="p31")
        check("盲区描述 → 锚点（检索打分）",
              predict.anchor_from_description(cg, "离线缓存锚点条目 zkv7") == "learn_anchor"
              and predict.anchor_from_description(cg, "日志采样链路锚点条目 zxc9")
              == "learn_anchor2")
        nf = call_tool(cg, "cg", {"op": "insight", "action": "learn",
                                  "blindspot_id": "no_such_blindspot"})
        check("未知盲区不编造", nf.get("ok") is False and nf.get("status") == "not_found",
              str(nf.get("reason"))[:60])
        lr = call_tool(cg, "cg", {"op": "insight", "action": "learn"})
        steps = {s["blindspot_id"]: s for s in (lr.get("steps") or [])}
        check("未解问题进入学习闭环",
              {"bs_resolved", "bs_unknowable", "bs_carried"} <= set(steps),
              str(sorted(steps)))
        check("终态五态可判定且不越集",
              all(s.get("terminal") in ("unknowable", "no_anchor", "unresolved",
                                        "carried", "resolved") for s in steps.values()))
        check("可判定终点 → resolved",
              steps.get("bs_resolved", {}).get("terminal") == "resolved"
              and steps["bs_resolved"].get("terminal_node") == "learn_kb",
              str(steps.get("bs_resolved", {}).get("terminal")))
        check("unknowable 不生成路线（拒绝编造）",
              steps.get("bs_unknowable", {}).get("terminal") == "unknowable"
              and steps["bs_unknowable"].get("routes") == 0)
        check("未达可判定终点 → carried",
              steps.get("bs_carried", {}).get("terminal") in ("carried", "unresolved"),
              str(steps.get("bs_carried", {}).get("terminal")))
        lw = call_tool(cg, "cg", {"op": "insight", "action": "learn", "apply": True})
        gap = [nid for nid in lw.get("written") or []]
        check("carried/unresolved 落 gap_hint 待补线索",
              len(gap) == int(lw["summary"].get("carried", 0))
              + int(lw["summary"].get("unresolved", 0)) and len(gap) >= 1,
              f"written={gap}")
        gnode = (cg.get(gap[0]) or {}) if gap else {}
        gfm = gnode.get("frontmatter") or {}
        check("gap_hint 是线索而非事实（contextual + 显式非事实标注）",
              gfm.get("layer") == "contextual"
              and "gap_hint" in (gfm.get("tags") or [])
              and "非既有事实" in (gnode.get("content") or ""),
              str(gfm.get("tags")))
        # 回归防线：线索节点逐字抄了盲区描述，若不隔离会顶掉真实锚点，
        # 使「线索 → 0 路线 → 永远 unresolved」并让重复 learn 不再幂等。
        check("线索节点不劫持锚点解析（自我污染防护）",
              predict.anchor_from_description(
                  cg, (predict.find_blindspot(cg, "bs_resolved") or {}).get("description") or "")
              == "learn_anchor")
        lw2 = call_tool(cg, "cg", {"op": "insight", "action": "learn", "apply": True})
        check("盲区学习落库幂等（重复 apply 不新增线索）",
              lw2.get("written") == []
              and lw2["summary"] == lw["summary"], str(lw2.get("written")))

        # ---------------------------------------------- ⑥ 洞见记账与裁决
        print("\n【6】insight.record / verify")
        bad = None
        try:
            call_tool(cg, "cg", {"op": "insight", "action": "record"})
        except Exception as exc:                       # noqa: BLE001
            bad = exc
        check("record 缺正文直接报错（不臆造）", isinstance(bad, ValueError),
              type(bad).__name__)
        r1 = call_tool(cg, "cg", {"op": "insight", "action": "record",
                                  "statement": STMT_MAIN, "conditions": C1_OK,
                                  "category": "caching"})
        nid = r1.get("node_id")
        check("record 记为 pending 并快照条件",
              r1.get("state") == "pending" and r1.get("duplicate") is False
              and r1.get("window", {}).get("open") is True, str(nid))
        rec_fm = (cg.get(nid) or {}).get("frontmatter") or {}
        check("条件快照含 C1–C8 且无缺失",
              set(rec_fm.get("insight_conditions") or {}) == set(insight.CONDITION_KEYS)
              and rec_fm.get("insight_missing") == [], str(rec_fm.get("insight_missing")))
        r1b = call_tool(cg, "cg", {"op": "insight", "action": "record",
                                   "statement": STMT_MAIN, "conditions": C1_OK})
        check("record 同正文幂等", r1b.get("duplicate") is True
              and r1b.get("node_id") == nid)
        v0 = call_tool(cg, "cg", {"op": "insight", "action": "verify", "node_id": nid})
        check("无证据不判定（保持 pending）",
              v0.get("decided") is False and v0.get("state") == "pending",
              str(v0.get("reason"))[:50])
        v1 = call_tool(cg, "cg", {"op": "insight", "action": "verify",
                                  "node_id": nid, "v_types": ["v1"]})
        check("V1 不足门槛不判定", v1.get("decided") is False)
        v3 = call_tool(cg, "cg", {"op": "insight", "action": "verify",
                                  "node_id": nid, "v_types": ["v3"]})
        check("V3 外部确证 → verified + 重要度保底 + 保护位",
              v3.get("state") == "verified" and v3.get("importance") >= 0.9
              and v3.get("protected") is True, str(v3.get("reason")))
        v3fm = (cg.get(nid) or {}).get("frontmatter") or {}
        check("verified 后基底升为 data 且带 verified 标签",
              v3fm.get("verification_basis") == "data"
              and insight.TAG_VERIFIED in (v3fm.get("tags") or []))
        bad_v = None
        try:
            call_tool(cg, "cg", {"op": "insight", "action": "verify",
                                 "node_id": nid, "verdict": "maybe"})
        except Exception as exc:                       # noqa: BLE001
            bad_v = exc
        check("非法 verdict 报错", isinstance(bad_v, ValueError))
        r2 = call_tool(cg, "cg", {"op": "insight", "action": "record",
                                  "statement": "被外部证据证伪的洞见：所有缓存都应常驻内存"})
        vf = call_tool(cg, "cg", {"op": "insight", "action": "verify",
                                  "node_id": r2["node_id"], "verdict": "falsified"})
        check("显式证伪 → falsified",
              vf.get("state") == "falsified" and vf.get("decided") is True)
        lst = call_tool(cg, "cg", {"op": "insight", "action": "list",
                                   "state": "verified"})
        check("list 按状态过滤",
              lst.get("count", 0) >= 1
              and all(e["state"] == "verified" for e in lst.get("events") or []))

        # ---------------------------------------------- ⑦ CER 报告
        print("\n【7】insight.report CER（样本不足不判定）")
        rep0 = call_tool(cg, "cg", {"op": "insight", "action": "report"})
        check("样本不足 → insufficient 且不给结论",
              rep0.get("layer_state") == "insufficient" and rep0.get("cer") is None
              and rep0.get("decided") < rep0.get("sample_min"), str(rep0.get("decided")))
        for i in range(20):
            ri = call_tool(cg, "cg", {"op": "insight", "action": "record",
                                      "statement": f"P31 样本 {i}：需在离线条件下验证的分支 {i}",
                                      "conditions": C1_OK})
            call_tool(cg, "cg", {"op": "insight", "action": "verify",
                                 "node_id": ri["node_id"],
                                 "verdict": ("verified" if i < 16 else "falsified")})
        rep = call_tool(cg, "cg", {"op": "insight", "action": "report"})
        import math as _m
        exp_v, exp_f = 17, 5
        n = exp_v + exp_f
        p = exp_v / n
        se = _m.sqrt(p * (1 - p) / n)
        check("样本足 → CER = verified/(verified+falsified)",
              rep.get("decided") == n and abs(rep.get("cer") - round(p, 4)) < 1e-4
              and rep.get("verified") == exp_v and rep.get("falsified") == exp_f,
              f"cer={rep.get('cer')} decided={rep.get('decided')}")
        check("2×SE 显著性带",
              abs(rep.get("two_se") - round(2 * se, 4)) < 1e-4
              and rep.get("significant") is True, f"two_se={rep.get('two_se')}")
        check("合格样本 → layer_state=reliable",
              rep.get("layer_state") == "reliable", str(rep.get("layer_state")))

        # ---------------------------------------------- ⑧ 结构洞察
        print("\n【8】insight.outlook 结构洞察")
        ol = call_tool(cg, "cg", {"op": "insight", "action": "outlook"})
        check("D1 结构判断含分层/分位/保护率",
              ol.get("d1", {}).get("total", 0) > 0
              and "layers" in ol["d1"] and "importance" in ol["d1"]
              and "protected_rate" in ol["d1"], str(ol.get("d1", {}).get("total")))
        check("D2 趋势含洞见 CER 与 unresolved",
              ol.get("d2", {}).get("insight", {}).get("recorded", 0) >= 22
              and "unresolved_nodes" in ol["d2"], str(ol.get("d2", {}).get("insight")))
        check("建议可执行（带证据与建议调用）",
              isinstance(ol.get("suggestions"), list)
              and all({"priority", "action", "evidence", "call"} <= set(s)
                      for s in ol["suggestions"]), f"n={len(ol.get('suggestions') or [])}")
        check("outlook 不判有效性（写进 note）",
              "不判有效性" in str(ol.get("note") or ""))

        # ---------------------------------------------- ⑨ 权限分档
        print("\n【9】insight 按 action 分级授权")
        cg.principal = _principal("output")
        check("output 可读洞察",
              not _denied(lambda: call_tool(cg, "cg", {"op": "insight",
                                                       "action": "outlook"})))
        check("output 不可记洞见",
              _denied(lambda: call_tool(cg, "cg", {"op": "insight",
                                                   "action": "record",
                                                   "statement": "越权记录"})))
        check("output 不可批量重构落库",
              _denied(lambda: call_tool(cg, "cg", {"op": "insight",
                                                   "action": "reconstruct",
                                                   "ids": ["rec_a"], "apply": True})))
        cg.principal = _principal("record")
        check("写层可记可裁",
              not _denied(lambda: call_tool(cg, "cg", {"op": "insight",
                                                       "action": "record",
                                                       "statement": "写层记录"}))
              and not _denied(lambda: call_tool(cg, "cg", {"op": "insight",
                                                           "action": "list"})))
        check("写层不可批量学习落库",
              _denied(lambda: call_tool(cg, "cg", {"op": "insight",
                                                   "action": "learn", "apply": True})))
        cg.principal = _principal("guest")
        check("guest 整 op 被拒",
              _denied(lambda: call_tool(cg, "cg", {"op": "insight",
                                                   "action": "outlook"})))
        cg.principal = Principal(tenant="default", actor="p31", clearance="internal",
                                 can_write=True, can_admin=True, role="designer")

        # ---------------------------------------------- ⑩ 未知 action
        print("\n【10】未知 action 不静默成功")
        for op in ("insight", "consolidate"):
            b = None
            try:
                call_tool(cg, "cg", {"op": op, "action": "no_such_action"})
            except Exception as exc:                   # noqa: BLE001
                b = exc
            check(f"{op} 未知 action 抛错", b is not None, type(b).__name__)

    finally:
        try:
            cg.close()
        except Exception:                              # noqa: BLE001
            pass
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 68)
    print(f"结果：{PASS} 通过 / {FAIL} 失败")
    if FAILS:
        print("失败项：")
        for n in FAILS:
            print(f"  - {n}")
    print("=" * 68)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
