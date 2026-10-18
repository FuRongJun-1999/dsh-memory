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
            "t_ref": "P0-5 / T14"}

    def s_gap_envelope(ctx):
        """Envelope 尚未定型（issue #5 第 15 条后半）：目标态契约未落地。"""
        from . import interface_schema as sc
        has = hasattr(ctx["cg"], "retrieve_envelope") or hasattr(ctx["cg"], "envelope")
        return (PASS if has else GAP), {
            "missing": None if has else "Envelope 结构未落地（retrieve 仍返回检索包，非定型信封）",
            "schema_defined": "envelope" in sc._SCHEMAS,
            "t_ref": "issue#5-15"}

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
        ("reject_no_condition_space", s_reject_no_cs),
        ("reject_no_evidence", s_reject_no_evidence),
        ("blindspot_not_accept", s_blindspot_not_accept),
        ("accept_repeatable", s_accept_repeatable),
        ("protected_predicates", s_protected_predicates),
        ("queue_health_readable", s_queue_health),
        ("anchor_verify", s_anchor_verify),
        ("revise_rollback", s_revise_rollback),
        ("verdict_schema", s_verdict_schema),
        ("gap_cs_not_indexed", s_gap_cs_not_indexed),
        ("gap_envelope", s_gap_envelope),
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
