#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""designer.py · 设计者视角（元技能）命令行脚本

定位（《智能论3.4》1.4.1）：只做判定与归因，不执行操作、不裁决事实、不写认知图。
资格由条件证据裁决，不由相似度裁决（6章.2）；事实裁决归验证单元与 md_cg；写操作须由 agent 经 MCP 显式发起。

锚点：1.4.2 视角层次 / 3.1-3.2 条件空间四维 / 第〇章 白箱三问 / 6章.2 四态判定+导航税
      / 5.3 目标函数 π* / 附录22.3 三方条件空间+五失配维度 / 1.1.1 蒸馏

用法：
  python designer.py declare   --position <op|protocol|designer> [--space k=v ...] [--json]
  python designer.py judge     --query <text> [--conditions <json>] [--candidates <json>]
                               [--verification-path <json>] [--emit-mcp] [--json]
  python designer.py attribute --error <json> [--json]
  python designer.py distill   --failures <jsonl> [--out <path>] [--json]
  python designer.py probe     [--json]
  python designer.py selftest  --cases <path> [--json]
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from collections import OrderedDict, defaultdict

VERSION = "1.0"
THEORY = "《智能论3.4》"
FOUR_DIMS = ("观测位置", "观测工具", "时间窗口", "存在约束")
FIVE_MISMATCH = ("观测位置", "观测工具", "时间窗口", "存在约束", "条件边界")
STATES = ("ACCEPT", "REJECT", "DEFER", "BLINDSPOT")
DEFAULT_DMCG_HOME = r"d:\Program Files\2_ai\dsh-memory"

POSITION_MAP = OrderedDict([
    ("op", ("操作层", "我如何执行熵管理操作")),
    ("protocol", ("协议层", "协议的整体结构是什么、各部分如何配合")),
    ("designer", ("全局观测层", "协议为什么这样设计？它的存在条件是什么？")),
])
DIM_KEYWORDS = (
    ("观测位置", ("位置", "视角", "尺度", "谁观测", "观测者")),
    ("观测工具", ("工具", "方法", "测量", "检索", "相似度", "证据")),
    ("时间窗口", ("时间", "窗口", "过期", "时效", "快照", "周期")),
    ("存在约束", ("约束", "资源", "公理", "权限", "允许")),
    ("条件边界", ("边界", "迁移", "跨条件", "适用极限")),
)


def _stdout_utf8():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _load_json_arg(text, default):
    if text is None or text == "":
        return default
    if isinstance(text, (dict, list)):
        return text
    return json.loads(text)


def _as_list(value):
    if not value:
        return []
    return [value] if isinstance(value, str) else list(value)


def classify_dimension(text):
    """把失配描述归入五失配维度之一；未命中归入「条件边界」。"""
    text = text or ""
    for dim, kws in DIM_KEYWORDS:
        if any(kw in text for kw in kws):
            return dim
    return "条件边界"


def _dim_of_key(key):
    return key if key in FOUR_DIMS else classify_dimension(key)


def normalize_conditions(conditions):
    if not conditions:
        return {}
    if isinstance(conditions, str):
        conditions = json.loads(conditions)
    return dict(conditions)


# ---------------------------------------------------------------- 步骤 1：声明

def declare_core(position="designer", space=None):
    """条件空间声明：四维 + 有效范围 + 切换规则（3.1/3.2）。"""
    position = position or "designer"
    if position not in POSITION_MAP:
        raise SystemExit("未知 position：%s（可选 %s）" % (position, "/".join(POSITION_MAP)))
    layer, desc = POSITION_MAP[position]
    space = OrderedDict(space or {})
    space.setdefault("观测位置", "%s：%s" % (layer, desc))
    return OrderedDict([
        ("space_id", "designer-perspective@%s" % position),
        ("layer", layer),
        ("space", space),
        ("missing_dims", [d for d in FOUR_DIMS if not space.get(d)]),
        ("validity_range", "当前任务条件空间"),
        ("transition_rules", "D_norm>0.5 / P_trust<0.7 / 用户指令（3.3）"),
    ])


# ---------------------------------------------------------------- 步骤 2-3：白箱三问 + 四态

def whitebox_check(candidate, conditions, verification_path=None):
    """白箱三问（第〇章）。返回 (ok, missing_dim, detail)。"""
    evidence = _as_list(candidate.get("evidence") or conditions.get("anchors"))
    missing_dims = [d for d in FOUR_DIMS if not conditions.get(d)]
    vpath = _as_list(verification_path or candidate.get("verification_path"))
    detail = OrderedDict([
        ("依据什么", evidence),
        ("在什么条件下成立", {"missing_dims": missing_dims}),
        ("错了怎么办", vpath),
    ])
    if not evidence:
        return False, "观测工具", detail
    if missing_dims:
        return False, missing_dims[0], detail
    if not vpath:
        return False, "条件边界", detail
    return True, None, detail


def judge_core(query, conditions=None, candidates=None, verification_path=None):
    """四态资格裁决（6章.2）：先拒绝，后接受。"""
    conditions = normalize_conditions(conditions)
    candidates = list(candidates or [])
    missing_dims = [d for d in FOUR_DIMS if not conditions.get(d)]
    verdict, reason, missing_dim = None, "", None
    traces = []

    if not candidates:
        verdict = "BLINDSPOT"
        reason = "无候选路径：无法建立判断路径，停止猜测"
        missing_dim = missing_dims[0] if missing_dims else "条件边界"
    else:
        qualified, deferred, rejected = [], [], []
        for cand in candidates:
            cid = str(cand.get("id") or cand.get("name") or "candidate")
            conflicts = [na for na in (cand.get("not_applicable") or []) if na and na in query]
            trace = OrderedDict([("id", cid), ("conflicts", conflicts)])
            if conflicts:
                trace["verdict"] = "REJECT"
                rejected.append((cand, trace))
            else:
                unmet = [k for k, v in (cand.get("when") or {}).items()
                         if conditions.get(k) != v]
                trace["unmet_when"] = unmet
                if unmet:
                    trace["verdict"] = "DEFER"
                    deferred.append((cand, trace, unmet))
                else:
                    trace["verdict"] = "QUALIFIED"
                    qualified.append((cand, trace))
            traces.append(trace)

        if not qualified and not deferred and rejected:
            verdict = "REJECT"
            reason = "存在足以证明「不适用」的条件冲突：" + "; ".join(
                "%s←%s" % (t["id"], ",".join(t["conflicts"])) for _, t in rejected)
        elif not qualified:
            _, trace, unmet = deferred[0]
            verdict = "DEFER"
            missing_dim = _dim_of_key(unmet[0]) if unmet else (
                missing_dims[0] if missing_dims else "条件边界")
            reason = "候选存在但区分条件未定：%s 的 when 未满足 %s" % (trace["id"], unmet)
        elif len(qualified) > 1:
            dist = [(c, t) for c, t in qualified if c.get("distinguishing")]
            if len(dist) == 1:
                qualified = dist
            else:
                verdict = "DEFER"
                missing_dim = "条件边界"
                reason = "多个候选均合格且无唯一区分条件，继续递归补条件"

        if verdict is None:
            cand, trace = qualified[0]
            ok, wd, detail = whitebox_check(cand, conditions, verification_path)
            trace["whitebox"] = detail
            if ok:
                verdict = "ACCEPT"
                reason = "条件充分，获得执行资格（白箱三问齐备）"
            else:
                verdict = "DEFER"
                missing_dim = wd
                reason = "白箱三问未齐备（缺 %s），降级为 DEFER" % wd

    return OrderedDict([
        ("query", query), ("conditions", conditions), ("missing_dims", missing_dims),
        ("verdict", verdict), ("reason", reason), ("missing_dim", missing_dim),
        ("traces", traces),
    ])


def emit_mcp_calls(result):
    """建议调用的 mdcg_* 工具（参数取自 mcp_server.py 实际 schema；写操作需显式确认）。"""
    query, verdict = result["query"], result["verdict"]
    missing_dim = result["missing_dim"]
    calls = [
        {"tool": "mdcg_metacognition", "mode": "read",
         "arguments": {"action": "self_check", "query": query},
         "why": "回答前自检：该直接答还是先补条件"},
        {"tool": "mdcg_search", "mode": "read", "arguments": {"query": query},
         "why": "四态资格判定 + T0–T3 阶梯，核对条件证据"},
    ]
    if verdict == "BLINDSPOT":
        calls += [
            {"tool": "mdcg_metacognition", "mode": "read",
             "arguments": {"action": "blindspots"},
             "why": "盲区地图：反复 BLINDSPOT 的查询邻域 + 未解问题"},
            {"tool": "mdcg_predict", "mode": "read",
             "arguments": {"action": "routes", "blindspot_id": "<盲区邻域键>"},
             "why": "盲区驱动候选未来（声明不可预测则拒绝生成）"},
        ]
    elif verdict == "DEFER":
        calls += [
            {"tool": "mdcg_flywheel", "mode": "write",
             "arguments": {"error_report": {"query": query, "expected_state": "ACCEPT",
                                            "actual_state": "DEFER",
                                            "missing": missing_dim or ""}},
             "why": "误差→unresolved→补条件（写操作，须显式确认）"},
            {"tool": "mdcg_unresolved", "mode": "write",
             "arguments": {"question": query, "known_clues": "缺失维度=%s" % (missing_dim or "")},
             "why": "登记未解问题（写操作，须显式确认）"},
        ]
    elif verdict == "REJECT":
        calls.append({"tool": "mdcg_rejected", "mode": "write",
                      "arguments": {"hypothesis": query, "reason": result["reason"]},
                      "why": "负记忆：防重复踩坑（写操作，须显式确认）"})
    elif verdict == "ACCEPT":
        calls.append({"tool": "mdcg_verify", "mode": "write",
                      "arguments": {"node_id": "<节点 id>", "evidence": "<外部证据>",
                                    "verdict": "confirmed|weakened|falsified"},
                      "why": "事实裁决归验证单元（写操作，须显式确认）"})
    return calls


def render_verdict(result, emit_mcp=False):
    c = result["conditions"]
    lines = ["[判定单]",
             "条件空间：" + " | ".join(
                 "%s=%s" % (d, c.get(d) or "<未声明>") for d in FOUR_DIMS)]
    wb = next((t["whitebox"] for t in result["traces"] if "whitebox" in t), None)
    if wb:
        lines.append("白箱三问：依据=%s | 条件=%s | 错后=%s" % (
            wb["依据什么"] or "<缺>",
            "齐备" if not wb["在什么条件下成立"]["missing_dims"]
            else "缺" + ",".join(wb["在什么条件下成立"]["missing_dims"]),
            wb["错了怎么办"] or "<缺>"))
    else:
        lines.append("白箱三问：<未进入（裁决为 %s）>" % result["verdict"])
    lines.append("裁决：%s" % result["verdict"])
    lines.append("依据：%s" % result["reason"])
    if result["missing_dim"]:
        lines.append("缺失维度：%s" % result["missing_dim"])
    lines.append("验证路径：<由操作层或 MCP 裁决>")
    if emit_mcp:
        lines.append("建议调用（md_cg）：")
        lines.append(json.dumps(emit_mcp_calls(result), ensure_ascii=False, indent=2))
    return "\n".join(lines)


# ---------------------------------------------------------------- 步骤 5：归因 / 蒸馏

def attribute_core(error):
    """条件层归因：三方条件空间失配 + 五失配维度定位（附录22.3）。"""
    error = dict(error or {})
    missing = error.get("missing", "")
    dim = error.get("dimension") or classify_dimension(missing)
    if dim not in FIVE_MISMATCH:
        dim = "条件边界"
    return OrderedDict([
        ("query", error.get("query", "")),
        ("triple", OrderedDict([
            ("任务真实条件", error.get("expected_state") or "<未声明>"),
            ("模型感知条件", error.get("actual_state") or "<未声明>"),
            ("机制声明条件", missing or "<未声明>"),
        ])),
        ("mismatch_dim", dim),
        ("layer", "条件层（根因）"),
        ("symptom_layer", "行为层（症状）"),
        ("discipline", "当%s未对齐时，先补条件再执行；适用条件：%s" % (dim, missing or "<待补>")),
        ("verification_path", "用验证基底检验该纪律能否稳定解释误差（附录22.3）"),
    ])


def distill_core(rows):
    """失败集合 → 带适用条件的可复用纪律（1.1.1）。"""
    groups = defaultdict(list)
    for row in rows:
        dim = row.get("dimension") or classify_dimension(row.get("missing", ""))
        groups[dim if dim in FIVE_MISMATCH else "条件边界"].append(row)
    items = []
    for dim, rs in groups.items():
        symptom = rs[0].get("symptom") or rs[0].get("missing") or "同类失败"
        items.append(OrderedDict([
            ("rule", "当%s未声明/未对齐时，%s 会重复发生" % (dim, symptom)),
            ("missing", dim),
            ("change", "补 %s 的声明" % dim),
            ("kind", "condition_gap"),
            ("evidence", "%d 条失败（家族：%s）" % (len(rs), symptom)),
            ("source", "manual"),
            ("when", "任务进入 %s 相关判断前" % dim),
        ]))
    return items


def render_distill(items):
    lines = ["# 蒸馏纪律（失败资产化）", "",
             "> 失败 → 根因（条件层）→ 可复用纪律（带适用条件）→ 注入 → 不再犯（1.1.1）", ""]
    for i, it in enumerate(items, 1):
        lines += ["## %d. %s" % (i, it["missing"]), "",
                  "- **规律**：%s" % it["rule"],
                  "- **适用条件**：%s" % it["when"],
                  "- **补条件**：%s" % it["change"],
                  "- **证据**：%s" % it["evidence"],
                  "- **账本建议**：`mdcg_evolution(action=record, rule=..., missing=..., "
                  "kind=condition_gap, evidence=...)`", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------- probe / selftest

def probe_mdcg():
    """探测 md_cg 认知图可用性（只读 import，不实例化、不写库）。"""
    bases = [os.environ.get("DMCG_HOME"), DEFAULT_DMCG_HOME]
    for base in bases:
        if not base:
            continue
        base = os.path.abspath(base)
        if not os.path.isdir(os.path.join(base, "md_cg")):
            continue
        if base not in sys.path:
            sys.path.insert(0, base)
        try:
            mod = importlib.import_module("md_cg.mdcos")
            return OrderedDict([("available", True), ("base", base),
                                ("module", mod.__name__),
                                ("has_mdcos", hasattr(mod, "MdCGOS")),
                                ("mode", "read-only")])
        except Exception as exc:
            return OrderedDict([("available", False), ("base", base),
                                ("error", str(exc)), ("mode", "degraded")])
    return OrderedDict([("available", False), ("base", None), ("mode", "degraded"),
                        ("error", "未找到 md_cg（可设 DMCG_HOME 指向 dsh-memory 根目录）")])


def run_cases(cases):
    results = []
    for case in cases:
        cid, kind = case.get("id", "?"), case.get("kind", "")
        inp, exp = case.get("input") or {}, case.get("expect") or {}
        ok, detail, got = True, "", {}
        if kind == "declare":
            got = declare_core(inp.get("position", "designer"), inp.get("space"))
            if "dims_complete" in exp:
                ok = (not got["missing_dims"]) == bool(exp["dims_complete"])
            if "observation_position_contains" in exp:
                ok = ok and exp["observation_position_contains"] in got["space"].get("观测位置", "")
            detail = "missing_dims=%s" % got["missing_dims"]
        elif kind in ("judge", "verify"):
            got = judge_core(inp.get("query", ""), inp.get("conditions"),
                             inp.get("candidates"), inp.get("verification_path"))
            if "state" in exp:
                ok = got["verdict"] == exp["state"]
            if exp.get("missing_dim"):
                ok = ok and got["missing_dim"] == exp["missing_dim"]
            if exp.get("require_verification_path"):
                ok = ok and bool(inp.get("verification_path"))
            if exp.get("require_missing_dim"):
                ok = ok and bool(got["missing_dim"])
            detail = "verdict=%s missing_dim=%s" % (got["verdict"], got["missing_dim"])
        elif kind == "missing":
            got = attribute_core(inp.get("error") or inp)
            if "missing_dim" in exp:
                ok = got["mismatch_dim"] == exp["missing_dim"]
            detail = "mismatch_dim=%s" % got["mismatch_dim"]
        else:
            ok, detail = False, "unknown kind: %s" % kind
        results.append(OrderedDict([("id", cid), ("kind", kind),
                                    ("ok", bool(ok)), ("detail", detail)]))
    return results


# ---------------------------------------------------------------- CLI

def _parse_space(items):
    space = OrderedDict()
    for it in items or []:
        if "=" not in it:
            raise SystemExit("--space 需为 k=v：%s" % it)
        key, value = it.split("=", 1)
        space[key.strip()] = value.strip()
    return space


def _build_parser():
    ap = argparse.ArgumentParser(prog="designer.py", description="设计者视角（元技能）命令行脚本")
    ap.add_argument("--version", action="version", version="designer.py %s" % VERSION)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("declare", help="声明条件空间（四维）")
    p.add_argument("--position", default="designer", choices=list(POSITION_MAP))
    p.add_argument("--space", action="append", metavar="k=v")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("judge", help="四态资格裁决 + 白箱三问")
    p.add_argument("--query", required=True)
    p.add_argument("--conditions", default="")
    p.add_argument("--candidates", default="")
    p.add_argument("--verification-path", dest="verification_path", default="")
    p.add_argument("--emit-mcp", action="store_true")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("attribute", help="失败条件层归因")
    p.add_argument("--error", required=True)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("distill", help="失败集合蒸馏为带适用条件的纪律")
    p.add_argument("--failures", required=True)
    p.add_argument("--out", default="")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("probe", help="探测 md_cg 认知图可用性（只读）")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("selftest", help="运行认知能力验收用例集")
    p.add_argument("--cases", required=True)
    p.add_argument("--json", action="store_true")
    return ap


def main(argv=None):
    _stdout_utf8()
    args = _build_parser().parse_args(argv)

    if args.cmd == "declare":
        out = declare_core(args.position, _parse_space(args.space))
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print("[条件空间声明] %s（%s）" % (out["space_id"], out["layer"]))
            for d in FOUR_DIMS:
                print("  %s：%s" % (d, out["space"].get(d) or "<未声明>"))
            print("  有效范围：%s" % out["validity_range"])
            print("  切换规则：%s" % out["transition_rules"])
            if out["missing_dims"]:
                print("  [缺失] %s" % "、".join(out["missing_dims"]))
        return 0

    if args.cmd == "judge":
        result = judge_core(args.query, _load_json_arg(args.conditions, {}),
                            _load_json_arg(args.candidates, []),
                            _load_json_arg(args.verification_path, []))
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json
              else render_verdict(result, emit_mcp=args.emit_mcp))
        return 0

    if args.cmd == "attribute":
        out = attribute_core(_load_json_arg(args.error, {}))
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print("[归因] %s" % out["query"])
            for k, v in out["triple"].items():
                print("  %s：%s" % (k, v))
            print("  失配维度：%s（%s）" % (out["mismatch_dim"], out["layer"]))
            print("  可复用纪律：%s" % out["discipline"])
            print("  验证路径：%s" % out["verification_path"])
        return 0

    if args.cmd == "distill":
        with open(args.failures, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        items = distill_core(rows)
        text = render_distill(items)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
        print(json.dumps(items, ensure_ascii=False, indent=2) if args.json else text)
        return 0

    if args.cmd == "probe":
        out = probe_mdcg()
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print("[md_cg 探测] available=%s mode=%s base=%s"
                  % (out["available"], out["mode"], out.get("base")))
            if out.get("error"):
                print("  error=%s" % out["error"])
        return 0

    if args.cmd == "selftest":
        with open(args.cases, encoding="utf-8") as fh:
            cases = [json.loads(line) for line in fh if line.strip()]
        results = run_cases(cases)
        passed = sum(1 for r in results if r["ok"])
        total = len(results)
        rate = (100.0 * passed / total) if total else 0.0
        if args.json:
            print(json.dumps({"passed": passed, "total": total,
                              "rate": round(rate, 2), "results": results},
                             ensure_ascii=False, indent=2))
        else:
            for r in results:
                print("%s %-14s [%-8s] %s" % ("PASS" if r["ok"] else "FAIL",
                                              r["id"], r["kind"], r["detail"]))
            print("\n通过率：%d/%d = %.1f%%" % (passed, total, rate))
        return 0 if passed == total else 1

    _build_parser().print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
