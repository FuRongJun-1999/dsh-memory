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

    def s_gap_anchor(ctx):
        has = hasattr(ctx["cg"], "verify_anchor") or hasattr(ctx["cg"], "verifyAnchor")
        return (PASS if has else GAP), {
            "missing": None if has else "verifyAnchor（I14 回执校验）未实现",
            "t_ref": "T7"}

    def s_gap_revise(ctx):
        """四动作里的「改」整条未实现（外部 issue #5 核对后钉住）。

        revise / state_from / rollback_token 在代码里**全仓 0 命中**，而文档 §五
        给出了完整签名。这是最容易误导读者的一处：签名看起来像既有能力。
        """
        has = hasattr(ctx["cg"], "revise")
        return (PASS if has else GAP), {
            "missing": None if has else "revise（四动作之「改」）未实现；state_from/rollback_token 亦无",
            "t_ref": "T11 / §五 实现状态表"}

    def s_gap_rollback(ctx):
        has = hasattr(ctx["cg"], "rollback")
        return (PASS if has else GAP), {
            "missing": None if has else "rollback（前像恢复）未实现", "t_ref": "T11"}

    def s_gap_legacy(ctx):
        return GAP, {
            "missing": "检索面未按 condition_space 缺失打 BLINDSPOT / legacy 标记",
            "t_ref": "T14",
            "note": "P0-5 未实现：检索面当前不区分有无条件空间"}

    return [
        ("clean_init", s_clean_init),
        ("commit_full", s_commit_full),
        ("formal_not_truth", s_formal_not_truth),
        ("get_node", s_get_node),
        ("archive_not_delete", s_archive_not_delete),
        ("reject_no_condition_space", s_reject_no_cs),
        ("reject_no_evidence", s_reject_no_evidence),
        ("blindspot_not_accept", s_blindspot_not_accept),
        ("accept_repeatable", s_accept_repeatable),
        ("protected_predicates", s_protected_predicates),
        ("queue_health_readable", s_queue_health),
        ("gap_anchor_verify", s_gap_anchor),
        ("gap_revise", s_gap_revise),
        ("gap_rollback", s_gap_rollback),
        ("gap_legacy_retrieve", s_gap_legacy),
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
