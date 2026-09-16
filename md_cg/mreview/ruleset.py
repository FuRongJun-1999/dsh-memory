# -*- coding: utf-8 -*-
"""记忆评审流水线 · 级 3：D3 规则装配（确定性，零写入）。

真源：docs/记忆评审系统_立项设计与施工交接_20260915.md §3 第 3 级 + §5 D3。

**规则全落数据文件**（`rules/*.json`）——新增/调整规则**零代码改动**（Ghidra G2 吸收件：
把「规则」与「引擎」解耦，规则库可增删而引擎冻结）。引擎只提供**机械检查器注册表**：

==================== ==========================================================
检查器                语义（确定性、纯输入、可复算）
==================== ==========================================================
field_absent          条目字段为空 → 逐条 issue
evidence_zero         evidence_count==0 → 逐条 issue
field_ratio_below     包级字段覆盖率低于阈值 → 一条包级 issue
dup_hash_group        包内同 content_hash → 除首条外逐条 issue
template_flow_digits_only  包内正文骨架相同（只换数字）→ 除首条外逐条 issue
basis_licensed        来源执照——赛道与验证基底不相容（复用 crosscheck 判据）
==================== ==========================================================

机械检查在蜂巢 job **之前**本地跑完：LLM 只看机械无法裁决的语义问题（token 经济 + 可复算）。
规则 matcher 语义：`layer` / `tags_any` 表示「包内存在该类条目」→ 规则入包，
检查执行时按同一条件**过滤到该类条目**（绝不跨层套用）。
"""
from __future__ import annotations

import collections
import json
import os

from .. import crosscheck as CC
from .. import writelimit as WL

RULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules")
SEVERITIES = ("INFO", "WARN", "HIGH")
_BLANK = (None, "", "None", "[]", "{}")


def _blank(v) -> bool:
    if isinstance(v, (list, tuple, dict)):
        return not v
    return v is None or str(v).strip() in ("", "None")


def _as_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _issue(entry, rule, kind, field, evidence, severity=None) -> dict:
    return {"ref": entry.get("ref"), "node_id": entry.get("node_id"),
            "field": field, "issue_kind": kind, "evidence": evidence,
            "rule_id": rule["id"], "severity": severity or rule.get("severity") or "WARN"}


# ---------------------------- 机械检查器注册表 ----------------------------

def _chk_field_absent(entries, spec, rule):
    field = spec.get("field")
    return [_issue(e, rule, spec.get("issue_kind") or "missing_field", field,
                   "字段 %s 为空" % field) for e in entries if _blank(e.get(field))]


def _chk_evidence_zero(entries, spec, rule):
    return [_issue(e, rule, spec.get("issue_kind") or "missing_field", "evidence_count",
                   "evidence_count=0（无验证证据计数）")
            for e in entries if _as_int(e.get("evidence_count")) == 0]


def _chk_field_ratio_below(entries, spec, rule):
    field, thr = spec.get("field"), float(spec.get("ratio", 1.0))
    ratio = sum(1 for e in entries if not _blank(e.get(field))) / max(len(entries), 1)
    if ratio >= thr:
        return []
    return [{"ref": None, "node_id": None, "field": field, "issue_kind": "package_ratio",
             "evidence": "包内 %s 覆盖率 %.3f < %.3f（%d 条）" % (field, ratio, thr, len(entries)),
             "rule_id": rule["id"], "severity": rule.get("severity") or "INFO"}]


def _chk_dup_hash_group(entries, spec, rule):
    seen, out = {}, []
    for e in entries:
        h = str(e.get("content_hash") or "")
        if _blank(h) or h == "None":
            continue
        if h in seen:
            out.append(_issue(e, rule, "dup_content", "content_hash",
                              "同包内与 %s 同指纹 %s" % (seen[h], h)))
        else:
            seen[h] = e.get("ref")
    return out


def _chk_template_flow(entries, spec, rule):
    seen, out = {}, []
    for e in entries:
        sk = WL._skeleton(e.get("excerpt") or "")
        if not sk or len(sk) < WL.MIN_SKELETON:
            continue
        if sk in seen:
            out.append(_issue(e, rule, "template_flow", "content",
                              "同模板流水（去数字骨架与 %s 相同）：%s" % (seen[sk], sk[:40])))
        else:
            seen[sk] = e.get("ref")
    return out


def _chk_basis_licensed(entries, spec, rule):
    out = []
    for e in entries:
        basis = e.get("verification_basis")
        if _blank(basis):
            continue
        fm = {"layer": e.get("layer"), "tags": e.get("tags") or []}
        track = CC.classify_track(fm, e.get("excerpt") or "")
        if not CC.basis_licensed(track, basis):
            out.append(_issue(e, rule, "weak_source", "verification_basis",
                              "赛道 %s（政策 %s）不允许基底 %s；允许 %s"
                              % (track, CC.source_policy(track), basis,
                                 "/".join(CC.allowed_basis(track)))))
    return out


MECH_CHECKS = {
    "field_absent": _chk_field_absent,
    "evidence_zero": _chk_evidence_zero,
    "field_ratio_below": _chk_field_ratio_below,
    "dup_hash_group": _chk_dup_hash_group,
    "template_flow_digits_only": _chk_template_flow,
    "basis_licensed": _chk_basis_licensed,
}


# ---------------------------- 规则库加载 ----------------------------

def load_rules(rules_dir=None) -> dict:
    """读 `rules/*.json`。格式非法/字段缺失/id 重复 → 抛 ValueError（不静默降级）。"""
    d = rules_dir or RULES_DIR
    files = sorted(f for f in os.listdir(d) if f.endswith(".json")) if os.path.isdir(d) else []
    rules, ids = [], {}
    for fn in files:
        with open(os.path.join(d, fn), encoding="utf-8") as f:
            doc = json.load(f)
        for r in doc.get("rules") or []:
            miss = [k for k in ("id", "matcher", "severity") if k not in r]
            if miss:
                raise ValueError("规则库 %s：规则缺字段 %s（%s）" % (fn, miss, r.get("id")))
            if r["severity"] not in SEVERITIES:
                raise ValueError("规则库 %s：severity=%s 非法（%s）" % (fn, r["severity"], r["id"]))
            if r["id"] in ids:
                raise ValueError("规则 id 重复：%s（%s / %s）" % (r["id"], ids[r["id"]], fn))
            ids[r["id"]] = fn
            for spec in list(r.get("mechanical") or []):
                if spec.get("check") not in MECH_CHECKS:
                    raise ValueError("规则库 %s：未知机械检查 %s（%s）"
                                     % (fn, spec.get("check"), r["id"]))
            rules.append(r)
    return {"rules_dir": d, "files": files, "rules": rules, "count": len(rules)}


def _match(rule, ctx) -> tuple:
    """matcher 语义：包内**存在**该类条目即入包（执行时按同条件过滤）。"""
    m = rule.get("matcher") or {}
    if m.get("layer") and not (ctx["layers"] & set(m["layer"])):
        return False, "包内无 %s 层条目" % "/".join(m["layer"])
    if m.get("tags_any") and not (ctx["tag_prefixes"] & set(m["tags_any"])):
        return False, "包内无 %s 标签" % "/".join(m["tags_any"])
    return True, "matcher 命中"


def _scope(entries, rule) -> list:
    m = rule.get("matcher") or {}
    if m.get("layer"):
        want = set(m["layer"])
        return [e for e in entries if str(e.get("layer")) in want]
    return list(entries)


def _as_rules(rules, rules_dir=None) -> list:
    """规则入参防呆：None→读规则库；{"rules":[...]}→取内层；列表→原样。

    仿 cg/stg「op 必填」防呆：传错形态时给出明确入口，而非静默 AttributeError。
    """
    if rules is None:
        return load_rules(rules_dir)["rules"]
    if isinstance(rules, dict):
        if "rules" not in rules:
            raise ValueError("规则入参 dict 缺少 rules 键（应为规则列表或 load_rules 结果）")
        return list(rules.get("rules") or [])
    return list(rules)


def assemble(pkg: dict, *, rules=None, rules_dir=None) -> dict:
    """单个待评包 → 规则集 + 机械检查结果 + 待 LLM 检查清单。"""
    rl = _as_rules(rules, rules_dir)
    entries = pkg.get("entries") or []
    ctx = {"layers": {str(e.get("layer") or "") for e in entries},
           "tag_prefixes": {str(t).split(":", 1)[0] for e in entries
                            for t in (e.get("tags") or [])}}
    matched, mech, llm = [], [], []
    for rule in rl:
        ok, why = _match(rule, ctx)
        if not ok:
            continue
        scoped = _scope(entries, rule)
        matched.append({"id": rule["id"], "title": rule.get("title"),
                        "severity": rule.get("severity"), "why": why,
                        "scope": len(scoped), "remedy": rule.get("remedy")})
        for spec in rule.get("mechanical") or []:
            mech += MECH_CHECKS[spec["check"]](scoped, spec, rule)
        for spec in rule.get("llm") or []:
            llm.append({"rule_id": rule["id"], "check": spec.get("check"),
                        "question": spec.get("question"),
                        "expect": spec.get("expect"),
                        "scope_refs": [e.get("ref") for e in scoped][:200]})
    cnt = collections.Counter(i["issue_kind"] for i in mech)
    return {"bundle_id": pkg.get("bundle_id"), "group_kind": pkg.get("group_kind"),
            "group_key": pkg.get("group_key"), "size": len(entries),
            "matched": matched, "mechanical": mech, "llm": llm,
            "mechanical_by_kind": dict(cnt),
            "mechanical_flagged": len({i.get("ref") for i in mech if i.get("ref")})}


def assemble_all(result: dict, *, rules=None, rules_dir=None) -> dict:
    """全部包装配 + 汇总（包级统计供 M2 spec 与 M4 量化复跑）。"""
    rl = _as_rules(rules, rules_dir)
    out = [assemble(p, rules=rl) for p in result.get("bundles") or []]
    kinds = collections.Counter()
    for a in out:
        kinds.update(a["mechanical_by_kind"])
    return {"packages": out, "stats": {
        "bundles": len(out),
        "mechanical_total": sum(len(a["mechanical"]) for a in out),
        "mechanical_by_kind": dict(kinds),
        "llm_checks": sum(len(a["llm"]) for a in out),
        "rules": [r["id"] for r in rl]},
        "bundles_input": result.get("stats")}
