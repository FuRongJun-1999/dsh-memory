# -*- coding: utf-8 -*-
"""核心闭环一致性测试（core loop conformance）——把 T 表从文档变成可执行断言。

与 md_cg.conformance 的分工（勿混）：
    md_cg.conformance       库**数据健康**不变量断言集（混层/重复/覆盖率，周期巡检）
    md_cg.conformance_core  **核心闭环**端到端行为断言（本模块）：写入→判定→落盘→回读

设计原则（外部评审 2026-10-18 建议，本实现采纳）：

1. **干净库上跑**：每次在临时空目录初始化，不碰生产库、不依赖任何环境变量。
2. **确定性**：输出 JSON 排序键、无时间戳、无随机 id；同一 fixture 连跑两次必须
   逐字节一致（sha256 相同）——这是「可复跑」KPI 的最小证据。
3. **缺口如实记**：尚未实现的能力标 known_gap，**不假装通过、也不伪装成失败**。
   已实现而行为不符的才是 fail。
4. **零 LLM**：全部确定性判据。

用法：
    python -X utf8 -m md_cg.conformance_core --json
    python -X utf8 -m md_cg.conformance_core --check-determinism
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import traceback

__all__ = ["run_fixture", "main"]

PASS, FAIL, GAP = "pass", "fail", "known_gap"

CS_LINE = ("# 条件空间：观测位置=conformance；观测工具=确定性脚本；"
           "存在约束=临时干净库")
GOOD_BODY = (
    "# 功能名：conformance 核心闭环样本\n"
    + CS_LINE + "\n"
    "# 生效条件：跑核心闭环 conformance 时\n"
    "# 子功能：①样本\n"
    "# 执行：略\n"
    "# 验证方式：本文脚本\n"
    "# 不适用条件：仅测试用\n"
    "依据：md_cg/condaccept.py 第10.1节\n"
)


def _steps():
    def s_clean_init(ctx):
        ok = os.path.isdir(ctx["root"])
        return (PASS if ok else FAIL), {"root_initialized": ok}

    def s_commit_full(ctx):
        r = ctx["write"](GOOD_BODY)
        ctx["good_id"] = r.get("id")
        v = r.get("verdict") or {}
        ok = (r.get("ok") is True and r.get("committed") is True
              and v.get("state") == "ACCEPT")
        return (PASS if ok else FAIL), {"committed": r.get("committed"),
                                        "verdict": v.get("state")}

    def s_formal_not_truth(ctx):
        r = ctx["write"](GOOD_BODY.replace("conformance 核心闭环样本", "形式真值解耦样本"))
        d = (r.get("verdict") or {}).get("detail") or {}
        ok = (d.get("acceptance") == "formal_pass"
              and d.get("verification_state") == "unverified")
        return (PASS if ok else FAIL), {"acceptance": d.get("acceptance"),
                                        "verification_state": d.get("verification_state")}

    def s_get_node(ctx):
        if not ctx.get("good_id"):
            return FAIL, {"error": "no node id"}
        try:
            node = ctx["cg"].get(ctx["good_id"])
            return (PASS if node is not None else FAIL), {"readable": node is not None}
        except Exception as exc:
            return FAIL, {"error": type(exc).__name__}

    def s_archive_not_delete(ctx):
        if not ctx.get("good_id"):
            return FAIL, {"error": "no node id"}
        try:
            from . import lifecycle
            lifecycle.set_state(ctx["cg"], ctx["good_id"], "archived",
                                reason="conformance")
            node = ctx["cg"].get(ctx["good_id"])
            return (PASS if node is not None else FAIL), {"archived_but_readable": node is not None}
        except Exception as exc:
            return FAIL, {"error": "%s: %s" % (type(exc).__name__, exc)}

    def s_supersede_semantics(ctx):
        """修订取代语义（2026-10-18 方案 A）：superseded 退出检索面但与 archived 可区分。"""
        from . import lifecycle
        ctx["cg"].add("n_old", "旧版本内容", layer="knowledge")
        ctx["cg"].add("n_new", "新版本内容", layer="knowledge")
        lifecycle.set_state(ctx["cg"], "n_old", "superseded", reason="被 n_new 取代")
        old = ctx["cg"].index["nodes"]["n_old"]
        new = ctx["cg"].index["nodes"]["n_new"]
        out = {
            "old_state": lifecycle.state_of(old),
            "old_retired": lifecycle.is_retired(old),
            "old_archived": lifecycle.is_archived(old),
            "new_retired": lifecycle.is_retired(new),
            "old_readable": ctx["cg"].get("n_old") is not None,
        }
        ok = (out["old_state"] == "superseded"
              and out["old_retired"] is True
              and out["old_archived"] is False      # 与 archived 可区分，未被混同
              and out["new_retired"] is False       # 新版不受影响
              and out["old_readable"] is True)      # 退役不删除
        return (PASS if ok else FAIL), out

    def s_audit_layer_not_self(ctx):
        """审核裁决审计记录不得落 self 层（2026-10-18 方案 A）。

        实测依据：改前 self 层 780 条里 769 条是这类审计记录（98.6%），而 self 属
        层保护（is_protected 恒真）——于是 sensitivity=secret 的裁决日志被"不可遗忘"
        永久占用自我层，任何自我认知分析都被淹没。

        两条断言：落 structural；**不受层保护**（审计痕迹不该"不可遗忘"）。
        """
        from . import protect
        rec = {
            "record_node_id": ctx["cg"]._audit_node_id("prop_conf0001", 1),
            "record_hash": "c" * 40, "pid": "prop_conf0001", "round": 1,
            "decision": "accept", "status": "accepted", "redteam_verdict": "absent",
            "issues": [], "verify_hash": None, "actor": "conformance", "t": 1792300000.0,
            "target_id": "n_target",
        }
        nid = ctx["cg"]._write_review_record(rec)
        node = ctx["cg"].get(nid) or {}
        fm = node.get("frontmatter") or {}
        is_p, _why = protect.is_protected_entry(fm)
        out = {"audit_node": nid, "layer": fm.get("layer"),
               "protected": is_p, "role": fm.get("role")}
        ok = (out["layer"] == "structural" and out["protected"] is False)
        return (PASS if ok else FAIL), out

    def s_self_surface_filter(ctx):
        """自我面过滤（方案 C）：审计痕迹被打标且可从自我面排除。

        三条：审计节点带 audit_trace 标签／self_surface 默认排除它／
        真实自我节点仍被包含。
        """
        from . import self_surface as ss
        rec = {
            "record_node_id": ctx["cg"]._audit_node_id("prop_conf0002", 1),
            "record_hash": "d" * 40, "pid": "prop_conf0002", "round": 1,
            "decision": "accept", "status": "accepted", "redteam_verdict": "absent",
            "issues": [], "verify_hash": None, "actor": "conformance", "t": 1792300000.0,
            "target_id": "",
        }
        audit_nid = ctx["cg"]._write_review_record(rec)
        audit_ent = ctx["cg"].index["nodes"].get(audit_nid) or {}
        # 存量情形：审计节点位于 self 层（769 条就是这样）——单造一条同形样本测过滤
        ctx["cg"].add("n_legacy_audit", "存量审计痕迹样本", layer="self",
                      tags=["audit", ss.AUDIT_TRACE_TAG])
        ctx["cg"].add("n_true_self", "真实自我锚点样本", layer="self")
        surface = ss.self_surface(ctx["cg"])
        surface_all = ss.self_surface(ctx["cg"], include_audit_trace=True)
        out = {
            "new_audit_tagged": ss.is_audit_trace(audit_ent),
            "new_audit_layer": audit_ent.get("layer"),
            "legacy_audit_has_tag": ss.is_audit_trace(
                ctx["cg"].index["nodes"].get("n_legacy_audit") or {}),
            "legacy_audit_excluded": "n_legacy_audit" not in surface,
            "legacy_audit_in_unfiltered": "n_legacy_audit" in surface_all,
            "true_self_included": "n_true_self" in surface,
        }
        ok = (out["new_audit_tagged"] is True
              and out["new_audit_layer"] == "structural"   # 源头已改，新记录不进 self
              and out["legacy_audit_has_tag"] is True
              and out["legacy_audit_excluded"] is True     # 存量在自我面被过滤
              and out["legacy_audit_in_unfiltered"] is True  # 不过滤时仍可见（可审计）
              and out["true_self_included"] is True)
        return (PASS if ok else FAIL), out

    def s_reject_no_cs(ctx):
        before = ctx["queue_len"]()
        r = ctx["write"]("# 功能名：无条件空间\n无出处。\n")
        after = ctx["queue_len"]()
        d = (r.get("verdict") or {}).get("detail") or {}
        ok = ((r.get("verdict") or {}).get("state") == "REJECT"
              and d.get("return_to") == "author" and after == before)
        return (PASS if ok else FAIL), {"verdict": (r.get("verdict") or {}).get("state"),
                                        "return_to": d.get("return_to"),
                                        "queue_unchanged": after == before}

    def s_reject_no_evidence(ctx):
        r = ctx["write"]("# 功能名：有C无出处\n" + CS_LINE + "\n裸断言没有出处。\n")
        v = (r.get("verdict") or {})
        ok = v.get("state") == "REJECT" and "V2" in str(v.get("evidence") or "")
        return (PASS if ok else FAIL), {"verdict": v.get("state"),
                                        "criterion": (v.get("detail") or {}).get("criterion")}

    def s_blindspot_not_accept(ctx):
        from . import condaccept
        v = condaccept.verify_work_done(
            {"content": GOOD_BODY, "condition_space": {"observation_position": "x",
                                                       "observation_tool": "y",
                                                       "existence_constraint": "z"},
             "evidence_ref": ["x"]},
            {"nid": "n_conf", "cg": None})
        ok = v["state"] != "ACCEPT"
        return (PASS if ok else FAIL), {"state": v["state"],
                                        "rule": "无cg时V4判不了→不得ACCEPT(I5)"}

    def s_accept_repeatable(ctx):
        a = ctx["write"](GOOD_BODY)
        b = ctx["write"](GOOD_BODY)
        sa = (a.get("verdict") or {}).get("state")
        sb = (b.get("verdict") or {}).get("state")
        return (PASS if sa == sb else FAIL), {"first": sa, "second": sb}

    def s_protected_predicates(ctx):
        """P1-7：钉住「受保护」的可判定谓词，并暴露七类与谓词不同集这个事实。

        文档已改为「七类=政策清单」，代码只认三条真源。本步既验证三条真源生效，
        也**如实断言**第四条不成立——未打保护位的 knowledge 节点不受保护。
        这是把「文档承诺 > 代码兑现」变成可见读数，而不是掩盖它。
        """
        from . import protect
        out = {}
        ctx["cg"].add("n_anchor", "锚点样本内容", layer="anchor")
        out["layer_protected"] = protect.is_protected(ctx["cg"], "n_anchor")[0]
        ctx["cg"].add("n_explicit", "显式保护样本", layer="knowledge",
                      protected=True, protection_reason="信任评估记录")
        out["explicit_protected"] = protect.is_protected(ctx["cg"], "n_explicit")[0]
        ctx["cg"].add("n_plain", "普通知识样本", layer="knowledge", importance=0.5)
        out["plain_protected"] = protect.is_protected(ctx["cg"], "n_plain")[0]
        ok = (out["layer_protected"] is True
              and out["explicit_protected"] is True
              and out["plain_protected"] is False)
        return (PASS if ok else FAIL), out

    def s_queue_health(ctx):
        """P0-6：DEFER 出口可观测——空库应给出「可用且为零」，缺数据源须如实报不可用。"""
        from . import queue_health
        rep = queue_health.report(ctx["root"])
        ok = (rep.get("available") is True and rep.get("pending") == 0
              and rep.get("over_deadline") == 0)
        return (PASS if ok else FAIL), {
            "available": rep.get("available"), "pending": rep.get("pending"),
            "over_deadline": rep.get("over_deadline")}
        # 注意：真实库的读数（958/775/183、零超期）不在此步断言——conformance 在
        # 临时干净库上跑，只验证「指标算得出、缺源不冒充 0」，不绑定生产数据。

    def s_anchor_verify(ctx):
        """I14：回执不得自带真值——原文不可读/已变，校验必须失败。

        四个正负对照（缺一不可）：
            正常生成 + 正常校验 → 通过
            篡改回执里的正文指纹 → 失败（回执不能自证）
            节点不存在 → 失败（**关键**：原文没了回执就必须倒）
            正文被改写 → 失败（回执绑定的是当时那份原文）
        """
        from . import anchor as anc
        ctx["cg"].add("n_anc", "锚定样本正文", layer="knowledge")
        made = anc.make_anchor(ctx["cg"], "n_anc", grantor="conformance")
        receipt = made.get("anchor") or {}
        out = {
            "anchor_has_no_content": "content" not in receipt,   # 回执不含正文
            "field_count": len([k for k in ("anchor_id", "node_id", "grantor",
                                            "grantee", "created_at", "state_digest",
                                            "content_hash") if k in receipt]),
        }
        out["verify_ok"] = anc.verify_anchor(ctx["cg"], made).get("ok")

        tampered = json.loads(json.dumps(made))
        tampered["anchor"]["content_hash"] = "0" * 64
        out["tampered_hash_reason"] = anc.verify_anchor(ctx["cg"], tampered).get("reason")

        ghost = json.loads(json.dumps(made))
        ghost["anchor"]["node_id"] = "n_does_not_exist"
        out["missing_node_reason"] = anc.verify_anchor(ctx["cg"], ghost).get("reason")

        ctx["cg"].add("n_anc", "锚定样本正文（已被改写）", layer="knowledge")
        out["changed_content_reason"] = anc.verify_anchor(ctx["cg"], made).get("reason")

        ok = (out["anchor_has_no_content"] is True
              and out["field_count"] == 7
              and out["verify_ok"] is True
              and out["tampered_hash_reason"] == "content_changed"
              and out["missing_node_reason"] == "missing_node"
              and out["changed_content_reason"] == "content_changed")
        return (PASS if ok else FAIL), out

    def s_verdict_schema(ctx):
        """接口形状：真实裁决必须符合 Verdict schema（issue #5 第 15 条）。

        与 interface_schema 的 golden 例子**共用同一份 schema**——文档、实现、
        测试三方引用同一个定义，避免各写一份口径（本仓已被这类漂移咬过多次）。
        """
        from . import interface_schema as sc

        bad = []
        for content, label in [
            (GOOD_BODY, "accept"),
            ("# 功能名：无C\n无出处。\n", "reject_no_cs"),
            ("# 功能名：裸\n" + CS_LINE + "\n没有出处。\n", "reject_no_ev"),
        ]:
            r = ctx["write"](content)
            v = r.get("verdict") or {}
            ok, errs = sc.validate(v, "verdict")
            if not ok:
                bad.append({"case": label, "errors": errs})
        golden = sc.check_golden()
        golden_fail = [g["name"] for g in golden if g["status"] == "fail"]
        ok = (not bad) and (not golden_fail)
        return (PASS if ok else FAIL), {
            "real_verdict_schema_violations": bad,
            "golden_failures": golden_fail,
            "golden_target_only": [g["name"] for g in golden if g["status"] == "target_only"],
        }

    def s_inv_write_trace(ctx):
        """不变量 I9 / I10 / I12 / I11-judge 面。

        I9  写入即留痕      写一条成功记录后，审计台账必须新增条目
        I10 committed=false 不得称已固化   REJECT 时 committed 必须为 False
        I12 moved_to 必须回显四态裁决      REJECT 的 moved_to 不得为空/与 verdict 脱节
        I11 judge 面        缺条件空间的 claim 在 judge 面不得 ACCEPT
        """
        from . import condaccept
        audit = os.path.join(ctx["root"], "_audit.jsonl")

        def audit_lines():
            if not os.path.isfile(audit):
                return 0
            with open(audit, "r", encoding="utf-8", errors="replace") as fh:
                return sum(1 for line in fh if line.strip())

        before = audit_lines()
        ok_write = ctx["write"](GOOD_BODY.replace("conformance 核心闭环样本", "留痕样本"))
        after = audit_lines()
        bad = ctx["write"]("# 功能名：无C\n无出处。\n")
        bv = bad.get("verdict") or {}
        out = {
            "audit_grew_on_write": after > before,
            "audit_before_after": [before, after],
            "reject_committed_false": bad.get("committed") is False,
            "reject_moved_to": bad.get("moved_to"),
            "reject_state": bv.get("state"),
            "moved_to_echoes_state": (bad.get("moved_to") not in (None, "")
                                      and bv.get("state") == "REJECT"),
        }
        # I11 judge 面：缺条件空间的 claim 不得 ACCEPT
        jv = condaccept.verify_work_done(
            {"content": "有出处依据：第10.1节", "condition_space": None},
            {"nid": "n_judge", "cg": None})
        out["judge_face_state"] = jv["state"]
        out["judge_face_not_accept"] = jv["state"] != "ACCEPT"
        ok = (out["audit_grew_on_write"] and out["reject_committed_false"]
              and out["moved_to_echoes_state"] and out["judge_face_not_accept"])
        return (PASS if ok else FAIL), out

    def s_inv_zero_llm(ctx):
        """不变量 I4 / I13。

        I4  judge 零 LLM：核心判定模块**不得 import 网络或 LLM 库**（AST 走查，
            比"跑两次结果一样"更强——后者证明确定性，前者证明结构上没有外部调用）。
        I13 不得代做可见面决策：接口上**不存在** inject/visibility 这类能力。
        """
        import ast
        from pathlib import Path as _P
        NET_LLM = {"requests", "httpx", "urllib", "urllib3", "socket",
                   "openai", "anthropic", "aiohttp", "http"}
        offenders = []
        for name in ("condgate", "condaccept", "anchor", "retrieve"):
            p = _P(os.path.dirname(os.path.abspath(__file__))) / (name + ".py")
            if not p.is_file():
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            mods = set()
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    mods |= {a.name.split(".")[0] for a in n.names}
                elif isinstance(n, ast.ImportFrom) and n.module:
                    mods.add(n.module.split(".")[0])
            if mods & NET_LLM:
                offenders.append({"module": name, "bad": sorted(mods & NET_LLM)})
        # I13：接口上不应存在可见面决策能力
        forbidden = [m for m in ("should_inject", "decide_visible", "inject_decision")
                     if hasattr(ctx["cg"], m)]
        out = {"net_or_llm_offenders": offenders, "visible_decision_api": forbidden}
        ok = (not offenders) and (not forbidden)
        return (PASS if ok else FAIL), out

    def s_inv_i2_i17(ctx):
        """I2 不完整时不得断言「没有」／ I17 投影不得自称权威。

        I2  ：completeness=False 且零命中时，hit_count 必须为 null（不能报 0）
        I17 ：content 被截断时必须显式声明（content_truncated + content_full_len），
              否则读者会把投影当原文——这正是「投影冒充权威」。
        """
        from . import retrieve as rv

        class Partial(object):
            """最小替身：检索返回空但标注不完整。"""
            index = {"nodes": {}}
            index_path = None

            def search(self, *a, **k):
                return [], {"completeness": False, "partial": True, "tier": "T1"}

            def get(self, nid):
                return None

        env = rv.retrieve(Partial(), "任意查询", k=3)
        out = {"partial_status": env.get("operation_status"),
               "partial_completeness": env.get("completeness"),
               "partial_hit_count": env.get("hit_count")}
        out["i2_ok"] = (env.get("completeness") is False
                        and env.get("hit_count") is None)

        # I17：长正文写入 → 检索命中时 content 必被截断，且必须声明
        long_body = GOOD_BODY + "扩展段落。" * 200
        ctx["write"](long_body.replace("conformance 核心闭环样本", "长正文截断样本"))
        env2 = rv.retrieve(ctx["cg"], "长正文截断样本", k=3)
        trunc = [i for i in env2.get("items", []) if i.get("content_truncated")]
        out["truncated_items"] = len(trunc)
        out["sample_full_len"] = trunc[0]["content_full_len"] if trunc else None
        out["sample_content_len"] = len(trunc[0]["content"]) if trunc else None
        out["i17_ok"] = bool(trunc) and (out["sample_full_len"] or 0) > (out["sample_content_len"] or 0)
        ok = out["i2_ok"] and out["i17_ok"]
        return (PASS if ok else FAIL), out

    def s_inv_i8_trace(ctx):
        """I8：无 _evolution 记录即未发生——状态变更必须留痕。

        对节点执行 superseded 迁移，断言两处痕迹都在：
            库级 _lifecycle.jsonl 追加了一条
            节点 frontmatter 的 state_history 记下了这次迁移
        """
        trace = os.path.join(ctx["root"], "_lifecycle.jsonl")

        def n_lines():
            if not os.path.isfile(trace):
                return 0
            with open(trace, "r", encoding="utf-8", errors="replace") as fh:
                return sum(1 for line in fh if line.strip())

        from . import lifecycle
        ctx["cg"].add("n_trace", "待迁移样本", layer="knowledge")
        before = n_lines()
        lifecycle.set_state(ctx["cg"], "n_trace", "superseded", reason="I8 conformance")
        after = n_lines()
        fm = ((ctx["cg"].get("n_trace") or {}).get("frontmatter") or {})
        hist = fm.get("state_history") or []
        out = {
            "audit_grew": after > before,
            "audit_before_after": [before, after],
            "state_history_len": len(hist),
            "has_transition": any(
                (isinstance(h, dict) and h.get("to") == "superseded")
                or (isinstance(h, str) and "superseded" in h) for h in hist),
        }
        ok = out["audit_grew"] and out["state_history_len"] > 0 and out["has_transition"]
        return (PASS if ok else FAIL), out

    def s_inv_envelope_i1(ctx):
        """不变量 I1：非 success 时 hit_count 必须为 null。

        构造一次真实失败（对已关闭/异常的库调 retrieve），断言 hit_count is None。
        若这里给出 0，调用方会把"故障"读成"没有"——这正是 I1 要防的。
        """
        from . import retrieve as rv

        class Boom(object):
            """最小替身：index 可用，search 必抛。"""
            index = {"nodes": {}}
            index_path = None

            def search(self, *a, **k):
                raise RuntimeError("injected failure")

            def get(self, nid):
                return None

        env = rv.retrieve(Boom(), "任意查询", k=3)
        out = {"status": env.get("operation_status"),
               "hit_count": env.get("hit_count"),
               "completeness": env.get("completeness")}
        ok = (out["status"] == "operation_error"
              and out["hit_count"] is None
              and out["completeness"] is False)
        return (PASS if ok else FAIL), out

    def s_gap_cs_not_indexed(ctx):
        """P0-5 的真正根因：condition_space 不在索引里，检索面拿不到。

        实测：索引条目 42 键不含该字段；生产库 31139 节点中索引带它者为 0。
        故「检索时给 legacy 结论标 BLINDSPOT」在装配层无法直接做——要么逐条读
        文件（31139 节点不可接受），要么把该字段写进索引（须权衡索引体积与迁移）。
        这是比「姿态未定义」更根本的一条，单列以免被前一条的进展掩盖。
        """
        ctx["cg"].add("n_idx", "索引字段探测", layer="knowledge", condition_space={
            "observation_position": "a", "observation_tool": "b",
            "time_window": [1, 2], "existence_constraint": "c"})
        ent = ctx["cg"].index["nodes"]["n_idx"]
        in_index = "condition_space" in ent
        fm_cs = ((ctx["cg"].get("n_idx") or {}).get("frontmatter") or {}).get("condition_space")
        return (PASS if in_index else GAP), {
            "condition_space_in_index": in_index,
            "condition_space_in_frontmatter": bool(fm_cs),
            "missing": None if in_index else
                       "condition_space 不进索引 → 检索面无法在装配层判定 legacy 姿态",
            "stock_needs_rebuild": True,   # 存量索引不含该字段，需一次 rebuild_index
            "t_ref": "P0-5 / T14"}

    def s_envelope(ctx):
        """取（retrieve）返回定型 Envelope，且符合 schema（issue #5 第 15 条）。

        五条：结构合 schema／命中带真实 qualification／legacy 节点被判 legacy_blindspot／
        空查询仍返回合法 Envelope／异常路径 hit_count 必须为 null（I1）。
        """
        from . import condgate as _gate
        from . import interface_schema as sc
        from . import retrieve as rv
        ctx["cg"].add("n_env_legacy", "信封样本：无条件空间的存量", layer="knowledge")
        env = rv.retrieve(ctx["cg"], "信封样本", k=5)
        ok_schema, errs = sc.validate(env, "envelope")
        legacy_items = [i for i in env.get("items", [])
                        if i.get("node_id") == "n_env_legacy"]
        empty = rv.retrieve(ctx["cg"], "", k=5)
        err_env = rv.retrieve(ctx["cg"], "x", k=1)
        out = {
            "schema_ok": ok_schema,
            "schema_errors": errs,
            "hit_count_type": type(env.get("hit_count")).__name__,
            "legacy_found": bool(legacy_items),
            "legacy_qualification": legacy_items[0]["qualification"] if legacy_items else None,
            "empty_query_status": empty.get("operation_status"),
            "empty_query_hit_count": empty.get("hit_count"),
            "has_snapshot": bool(env.get("snapshot_id")),
        }
        ok = (ok_schema
              and out["legacy_found"]
              and out["legacy_qualification"] == _gate.LEGACY_BLINDSPOT
              and out["empty_query_status"] == "success"
              and out["empty_query_hit_count"] == 0
              and out["has_snapshot"])
        return (PASS if ok else FAIL), out

    def s_revise_rollback(ctx):
        """修订与回滚闭环（2026-10-18 落地后，替代原 gap_revise + gap_rollback）。

        四条：CAS 不符必须 DEFER；新版落盘后旧版转 superseded；
        回滚使旧版复活、新版转被取代；全程不删除任何节点。
        """
        from . import revise as rv
        ctx["cg"].add("n_v1", "第一版内容", layer="knowledge")
        bad = rv.revise(ctx["cg"], "n_v1", GOOD_BODY.replace("conformance 核心闭环样本", "第二版"),
                        expect_state="archived")          # 故意给错的状态
        good = rv.revise(ctx["cg"], "n_v1", GOOD_BODY.replace("conformance 核心闭环样本", "第二版"),
                         expect_state="active")
        out = {
            "cas_mismatch_verdict": bad.get("verdict"),
            "revise_verdict": good.get("verdict"),
            "old_state_after": good.get("state_to"),
            "new_id_present": bool(good.get("new_id")),
            "token_present": bool(good.get("rollback_token")),
        }
        rb = rv.rollback(ctx["cg"], good.get("rollback_token") or {})
        out["rollback_verdict"] = rb.get("verdict")
        out["old_after_rollback"] = rb.get("state_old_after")
        out["new_after_rollback"] = rb.get("state_new_after")
        out["old_still_readable"] = ctx["cg"].get("n_v1") is not None
        ok = (out["cas_mismatch_verdict"] == "DEFER"
              and out["revise_verdict"] == "ACCEPT"
              and out["old_state_after"] == "superseded"
              and out["new_id_present"] and out["token_present"]
              and out["rollback_verdict"] == "ACCEPT"
              and out["old_after_rollback"] == "active"
              and out["new_after_rollback"] == "superseded"
              and out["old_still_readable"] is True)
        return (PASS if ok else FAIL), out

    def s_gap_revise(ctx):
        """四动作里的「改」整条未实现（外部 issue #5 核对后钉住）。

        revise / state_from / rollback_token 在代码里**全仓 0 命中**，而文档 §五
        给出了完整签名。这是最容易误导读者的一处：签名看起来像既有能力。
        """
        # 2026-10-18 已落地：md_cg/revise.py（revise + rollback）。
        # 本步骤保留为「能力存在性」守卫——若有人删掉该模块，这里会立刻转 GAP。
        from . import revise as _rv
        has = hasattr(_rv, "revise")
        return (PASS if has else GAP), {
            "missing": None if has else "revise 模块缺失（曾于 2026-10-18 落地）",
            "t_ref": "T11 / §五 实现状态表"}

    def s_gap_rollback(ctx):
        # 2026-10-18 已落地：rollback 在 md_cg/revise.py（不在 cg 上）。
        # 首版查的是 ctx["cg"].rollback，属**探针指错对象**——能力在而判据看错位置，
        # 会得到「未实现」的假结论（与记忆里那条「探针不纯」同型）。
        from . import revise as _rv
        has = hasattr(_rv, "rollback")
        return (PASS if has else GAP), {
            "missing": None if has else "rollback 模块缺失（曾于 2026-10-18 落地）",
            "t_ref": "T11"}

    def s_legacy_qualification(ctx):
        """P0-5 legacy 姿态：判定能力已在，检索面自动装配待接。

        姿态本身（可读、但不得 ACCEPT、不回填）已由 condgate.qualify 提供；
        尚未做的是把它接进 _emit 装配点（改 _emit 影响全部检索路径，须单独权衡）。
        本步骤如实区分这两件事，不把「判定有了」说成「已经标在结果上了」。
        """
        from . import condgate as gate
        # 直接 add 绕过写入闸，模拟一条「存量」：无条件空间
        ctx["cg"].add("n_legacy", "存量节点：没有条件空间", layer="knowledge")
        ctx["cg"].add("n_qualified", "合格节点：四维齐全", layer="knowledge",
                      condition_space={"observation_position": "a",
                                       "observation_tool": "b",
                                       "time_window": [1, 2],
                                       "existence_constraint": "c"})
        # 必须从 frontmatter 取——索引条目不含 condition_space（见 condgate.qualify）
        legacy_fm = (ctx["cg"].get("n_legacy") or {}).get("frontmatter") or {}
        # 首版拿 n_plain 当合格样本——它本就没有条件空间，判 legacy 是对的，
        # 于是「样本没资格」被误读成「判据失效」（与记忆里「探针不纯」同型）。
        new_fm = (ctx["cg"].get("n_qualified") or {}).get("frontmatter") or {}
        out = {
            "legacy_verdict": gate.qualify(legacy_fm),
            "qualified_verdict": gate.qualify(new_fm),
            "legacy_readable": ctx["cg"].get("n_legacy") is not None,
            "legacy_auto_annotated": False,
        }
        ok = (out["legacy_verdict"] == gate.LEGACY_BLINDSPOT
              and out["qualified_verdict"] == gate.QUALIFIED
              and out["legacy_readable"] is True)
        status = PASS if ok else FAIL
        return status, out

    return [
        ("clean_init", s_clean_init),
        ("commit_full", s_commit_full),
        ("formal_not_truth", s_formal_not_truth),
        ("get_node", s_get_node),
        ("archive_not_delete", s_archive_not_delete),
        ("supersede_semantics", s_supersede_semantics),
        ("audit_layer_not_self", s_audit_layer_not_self),
        ("self_surface_filter", s_self_surface_filter),
        ("reject_no_condition_space", s_reject_no_cs),
        ("reject_no_evidence", s_reject_no_evidence),
        ("blindspot_not_accept", s_blindspot_not_accept),
        ("accept_repeatable", s_accept_repeatable),
        ("protected_predicates", s_protected_predicates),
        ("queue_health_readable", s_queue_health),
        ("anchor_verify", s_anchor_verify),
        ("revise_rollback", s_revise_rollback),
        ("verdict_schema", s_verdict_schema),
        ("inv_write_trace", s_inv_write_trace),
        ("inv_zero_llm", s_inv_zero_llm),
        ("inv_i2_i17", s_inv_i2_i17),
        ("inv_i8_trace", s_inv_i8_trace),
        ("inv_envelope_i1", s_inv_envelope_i1),
        ("gap_cs_not_indexed", s_gap_cs_not_indexed),
        ("envelope", s_envelope),
        ("gap_revise", s_gap_revise),
        ("gap_rollback", s_gap_rollback),
        ("legacy_qualification", s_legacy_qualification),
    ]


def _make_ctx(root):
    from .mdcos import MdCGSecure
    from .security import Principal
    from .mcp_server import _cg_dispatch

    p = Principal(tenant="default", actor="conformance", clearance="internal",
                  can_write=True, role="designer",
                  ops_allow=("read", "write", "verify"), session="conformance",
                  auth_mode="direct")
    cg = MdCGSecure(str(root), principal=p, autoflush=0)

    def write(content):
        r = _cg_dispatch(cg, {"op": "write", "content": content,
                              "content_kind": "work_done", "layer": "knowledge",
                              "tags": ["conformance"]})
        return json.loads(r[0]["text"]) if isinstance(r, list) else r

    def queue_len():
        f = os.path.join(str(root), "hippocampus", "inbox.jsonl")
        if not os.path.isfile(f):
            return 0
        with open(f, "r", encoding="utf-8", errors="replace") as fh:
            return sum(1 for line in fh if line.strip())

    return {"cg": cg, "root": str(root), "write": write, "queue_len": queue_len}


def run_fixture(name="core_loop"):
    tmp = tempfile.mkdtemp(prefix="conf-core-")
    try:
        root = os.path.join(tmp, "mdcg")
        os.makedirs(root, exist_ok=True)
        ctx = _make_ctx(root)
        steps = []
        for step_name, fn in _steps():
            try:
                status, detail = fn(ctx)
            except Exception as exc:
                status = FAIL
                detail = {"error": "%s: %s" % (type(exc).__name__, exc),
                          "trace_tail": traceback.format_exc().strip().splitlines()[-1][:160]}
            steps.append({"step": step_name, "status": status, "detail": detail})
        summary = {PASS: 0, FAIL: 0, GAP: 0}
        for s in steps:
            summary[s["status"]] = summary.get(s["status"], 0) + 1
        doc = {"fixture": name, "steps": steps, "summary": summary}
        blob = json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1)
        doc["sha256"] = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
        return doc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    fixture, as_json, check_det = "core_loop", "--json" in argv, "--check-determinism" in argv
    if "--fixture" in argv:
        fixture = argv[argv.index("--fixture") + 1]
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    first = run_fixture(fixture)
    rc = 0 if first["summary"].get(FAIL, 0) == 0 else 1
    if check_det:
        second = run_fixture(fixture)
        same = first["sha256"] == second["sha256"]
        first["determinism"] = {"same_sha256": same, "first": first["sha256"],
                                "second": second["sha256"]}
        if not same:
            rc = 1
    if as_json:
        print(json.dumps(first, ensure_ascii=False, sort_keys=True, indent=1))
    else:
        for s in first["steps"]:
            print("  %-9s %-27s %s" % (s["status"], s["step"],
                                       json.dumps(s["detail"], ensure_ascii=False)[:88]))
        sm = first["summary"]
        print("")
        print("pass=%d fail=%d known_gap=%d sha256=%s"
              % (sm.get(PASS, 0), sm.get(FAIL, 0), sm.get(GAP, 0), first["sha256"]))
        if "determinism" in first:
            print("determinism: same_sha256=%s" % first["determinism"]["same_sha256"])
    return rc


if __name__ == "__main__":
    sys.exit(main())
