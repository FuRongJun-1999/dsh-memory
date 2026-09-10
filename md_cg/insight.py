# -*- coding: utf-8 -*-
"""洞察条件层（P2 · insight）：洞见事件四件套。

对齐 `docs/tool_table_v0.3.0.md`（insight_record / insight_verify /
insight_report / insight_window）与 `docs/灵枢82工具_功能整理与迁移映射_v0.1.md`
§五 P2 缺口。

四件套
------
- ``record``  记录一条洞见事件 + C1–C8 条件快照（state=pending）
- ``verify``  用 V1/V2/V3 外部证据裁决 → verified / falsified；verified 重要度保底 0.9
- ``report``  CER 条件有效洞见率 + 2×SE 显著性 + 层状态 reliable/watch/degraded
- ``window``  开窗条件：C1 ≥ 0.6 ∧ 跨域 ∧ 低压力

诚实边界（写进返回值，不靠调用方自觉）
--------------------------------------
- 本层只做**结构性记账与统计**，不产生洞见正文——正文必须由调用方给出，
  缺失即报错，绝不臆造；
- 窗口开 ≠ 洞见有效：``window`` 只回答「条件是否具备」，有效性一律交由
  ``verify`` 的外部证据说话；
- 样本不足时 ``report`` 显式返回 ``insufficient`` 并**不给结论**（宁可不说）。

零第三方依赖。
"""
from __future__ import annotations

import hashlib
import math
import os
import time

from .fsutil import append_jsonl

INSIGHT_LOG = "_insight.jsonl"
INSIGHT_LAYER = "contextual"       # 条件层：低阶情境记录，不承担事实断言
TAG_EVENT = "insight_event"
TAG_VERIFIED = "insight_verified"
TAG_FALSIFIED = "insight_falsified"

STATE_PENDING = "pending"
STATE_VERIFIED = "verified"
STATE_FALSIFIED = "falsified"

C1_WINDOW_MIN = 0.6                # C1 可检索度开窗门槛
V1_MIN_EVIDENCE = 3                # V1（可检索/被引用）需 ≥3 条才成立
IMPORTANCE_FLOOR = 0.9             # verified 后的重要度保底（对齐工具表）
CER_MIN_SAMPLES = 20               # 样本 < 20 不判定层状态

PRESSURES = ("low", "medium", "high")
TONES = ("neutral", "curious", "defensive", "urgent")

# C1–C8 条件快照字段（顺序即编号，便于审计对读）
CONDITION_KEYS = ("retrievability", "outside_observer", "cross_domain",
                  "premise_questioned", "pressure", "continuity_turns",
                  "externalized", "tone")
V_TYPES = ("v1", "v2", "v3")
V_LABELS = {"v1": "可检索/被引用", "v2": "实践重复", "v3": "外部确证"}


# ---------------------------------------------------------------- 基础

def log_path(cg):
    return os.path.join(cg.root, INSIGHT_LOG)


def _append(cg, rec):
    """留痕（best-effort）：审计不该反过来打断主流程。"""
    try:
        append_jsonl(log_path(cg), rec)
    except Exception:                              # noqa: BLE001
        pass
    return rec


def _events(cg):
    """全部洞见事件节点 id（按 index 层标签粗筛，避免全量读盘）。"""
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    return [nid for nid, e in nodes.items()
            if TAG_EVENT in ((e or {}).get("tags") or [])]


def _read_event(cg, node_id):
    """读洞见事件节点；非事件节点（标签不符）返回 None。"""
    nid = str(node_id or "").strip()
    if not nid:
        return None
    try:
        node = cg.get(nid)
    except Exception:                              # noqa: BLE001
        return None
    if not node:
        return None
    fm = node.get("frontmatter") or {}
    if TAG_EVENT not in (fm.get("tags") or []):
        return None
    return node


# ---------------------------------------------------------------- 条件快照

def normalize(conditions=None):
    """C1–C8 归一化；**缺失项显式登记**而不是静默补默认值。"""
    raw = dict(conditions or {})
    missing = [k for k in CONDITION_KEYS if k not in raw]
    out = {}
    try:
        c1 = float(raw.get("retrievability", 0.0) or 0.0)
    except (TypeError, ValueError):
        c1 = 0.0
    out["retrievability"] = min(1.0, max(0.0, c1))
    out["outside_observer"] = bool(raw.get("outside_observer", False))
    cd = raw.get("cross_domain") or []
    if isinstance(cd, str):
        cd = [cd]
    out["cross_domain"] = sorted({str(x) for x in cd})
    out["premise_questioned"] = bool(raw.get("premise_questioned", False))
    pr = str(raw.get("pressure") or "medium").strip().lower()
    out["pressure"] = pr if pr in PRESSURES else "medium"
    try:
        out["continuity_turns"] = max(0, int(raw.get("continuity_turns") or 0))
    except (TypeError, ValueError):
        out["continuity_turns"] = 0
    out["externalized"] = bool(raw.get("externalized", False))
    tn = str(raw.get("tone") or "neutral").strip().lower()
    out["tone"] = tn if tn in TONES else "neutral"
    return {"conditions": out, "missing": missing}


def window(conditions=None):
    """开窗判定：C1 ≥ 0.6 ∧ 跨域（≥1 个域）∧ 低压力。

    返回逐闸门结果与阻塞项，便于调用方知道「差在哪」，而不是只拿到一个 bool。
    """
    n = normalize(conditions)
    c = n["conditions"]
    gates = {
        "c1_retrievable": c["retrievability"] >= C1_WINDOW_MIN,
        "cross_domain": bool(c["cross_domain"]),
        "low_pressure": c["pressure"] == "low",
    }
    blocked = [k for k, ok in gates.items() if not ok]
    return {"open": not blocked, "gates": gates, "blocked_by": blocked,
            "c1": c["retrievability"], "c1_min": C1_WINDOW_MIN,
            "conditions": c, "missing": n["missing"],
            "note": "开窗仅表示「条件具备」；是否有效一律由 verify 的外部证据裁决"}


def event_id(statement, ts=None):
    return "ins_%d_%s" % (int(ts or time.time()),
                          hashlib.sha1(str(statement or "").encode("utf-8")).hexdigest()[:8])


# ---------------------------------------------------------------- record

def record(cg, statement=None, conditions=None, category="", source="",
           tags=None, importance=0.5, node_id=None, actor=None, **extra):
    """记录一条洞见事件（pending）＋ C1–C8 条件快照。

    ``statement`` 必填：洞见正文由调用方给出，本层不臆造；缺正文直接报错。
    幂等：同一正文派生同一 id，重复调用不重复写盘。
    """
    statement = str(statement or "").strip()
    if not statement:
        raise ValueError("insight record 需要 statement：洞见正文由调用方给出，本层不臆造")
    w = window(conditions)
    nid = str(node_id or event_id(statement)).strip()
    existing = _read_event(cg, nid)
    if existing:
        fm = existing.get("frontmatter") or {}
        _append(cg, {"action": "record", "node_id": nid, "duplicate": True,
                     "actor": actor, "ts": time.time()})
        return {"ok": True, "action": "record", "node_id": nid,
                "state": fm.get("insight_state"), "window": w,
                "existed_before": True, "duplicate": True,
                "note": "同正文事件已存在，未重复写入（幂等）"}
    tg = [TAG_EVENT] + [str(t) for t in (tags or [])]
    if category:
        tg.append("insight_cat:%s" % category)
    body = statement if statement.endswith("\n") else statement + "\n"
    fm_extra = {
        "insight_state": STATE_PENDING,
        "insight_category": category,
        "insight_source": source,
        "insight_conditions": w["conditions"],
        "insight_missing": w["missing"],
        "insight_window_open": bool(w["open"]),
        "insight_statement": statement,
        "insight_evidence": [],
        "insight_history": [],
    }
    fm_extra.update(extra)
    cg.add(nid, body, layer=INSIGHT_LAYER, tags=tg,
           importance=float(importance), actor=actor, **fm_extra)
    _append(cg, {"action": "record", "node_id": nid, "category": category,
                 "source": source, "window_open": w["open"],
                 "blocked_by": w["blocked_by"], "missing": w["missing"],
                 "actor": actor, "ts": time.time()})
    return {"ok": True, "action": "record", "node_id": nid, "state": STATE_PENDING,
            "window": w, "existed_before": False, "duplicate": False,
            "note": "已记录为 pending；有效性待 verify 的外部证据裁决"}


# ---------------------------------------------------------------- verify

def _normalize_evidence(evidence=None, v_types=None):
    """证据归一化：接受 ``["ref", ...]`` / ``[{"type","ref","note"}]`` / ``v_types``。"""
    ev = evidence
    if isinstance(ev, (str, dict)):
        ev = [ev]
    out = []
    for item in (ev or []):
        if isinstance(item, dict):
            t = str(item.get("type") or "").strip().lower()
            out.append({"type": t if t in V_TYPES else "v1",
                        "ref": str(item.get("ref") or item.get("source") or ""),
                        "note": str(item.get("note") or "")})
        else:
            out.append({"type": "v1", "ref": str(item), "note": ""})
    for t in (v_types or []):
        t = str(t).strip().lower()
        if t in V_TYPES:
            out.append({"type": t, "ref": "", "note": ""})
    return out


def verify(cg, node_id=None, evidence=None, v_types=None, verdict=None,
           actor=None, note=""):
    """用 V1/V2/V3 外部证据裁决洞见事件。

    判定规则（先声明后判定，避免「有证据就算过」）：
      · 显式 ``verdict``（verified/falsified）→ 直接采信（证伪只能由此路径产生）；
      · V3 外部确证 或 V2 实践重复 → verified；
      · V1 可检索/被引用 需 **≥ V1_MIN_EVIDENCE 条** 才成立；
      · 其余（无证据 / V1 不足）→ **保持 pending 并给出原因**，不判定。
    verified 后：重要度保底 0.9（``IMPORTANCE_FLOOR``）并置保护位。
    """
    node = _read_event(cg, node_id)
    if not node:
        raise ValueError("不是有效的洞见事件节点：%r" % (node_id,))
    fm = dict(node.get("frontmatter") or {})
    ev = _normalize_evidence(evidence, v_types)
    kinds = {e["type"] for e in ev}
    explicit = str(verdict or "").strip().lower() or None
    if explicit is not None and explicit not in (STATE_VERIFIED, STATE_FALSIFIED):
        raise ValueError("verdict 只能是 verified / falsified / None：%r" % (verdict,))

    final, reason = explicit, ""
    if final is None:
        if "v3" in kinds:
            final, reason = STATE_VERIFIED, "V3 外部确证"
        elif "v2" in kinds:
            final, reason = STATE_VERIFIED, "V2 实践重复"
        elif sum(1 for e in ev if e["type"] == "v1") >= V1_MIN_EVIDENCE:
            final, reason = STATE_VERIFIED, "V1 可检索/被引用 ≥ %d 条" % V1_MIN_EVIDENCE
        elif ev:
            reason = ("仅 V1 证据且不足 %d 条：不判定，保持 pending"
                      % V1_MIN_EVIDENCE)
        else:
            reason = "无外部证据：不判定，保持 pending（窗口开不等于有效）"
    if final is None:
        _append(cg, {"action": "verify", "node_id": node_id, "state": STATE_PENDING,
                     "decided": False, "reason": reason, "evidence": ev,
                     "actor": actor, "ts": time.time()})
        return {"ok": True, "action": "verify", "node_id": node_id,
                "state": STATE_PENDING, "decided": False, "reason": reason,
                "evidence": ev, "importance": fm.get("importance"),
                "note": "未达判定门槛，保持 pending"}

    hist = list(fm.get("insight_history") or [])
    hist.append({"ts": time.time(), "from": fm.get("insight_state"),
                 "to": final, "reason": reason or "显式裁决",
                 "actor": actor, "note": note})
    fm["insight_state"] = final
    fm["insight_evidence"] = list(fm.get("insight_evidence") or []) + ev
    fm["insight_history"] = hist
    fm["insight_reason"] = reason or "显式裁决"
    tg = [t for t in (fm.get("tags") or []) if t not in (TAG_VERIFIED, TAG_FALSIFIED)]
    if final == STATE_VERIFIED:
        tg.append(TAG_VERIFIED)
        fm["importance"] = max(float(fm.get("importance") or 0.0), IMPORTANCE_FLOOR)
        fm["protected"] = True
        fm["protection_reason"] = "insight_verified"
        fm["verification_basis"] = "data"
    else:
        tg.append(TAG_FALSIFIED)
    fm["tags"] = tg
    cg._write_node(node_id, os.path.join(cg.root, node["path"]), fm,
                   node.get("content") or "")
    ent = ((getattr(cg, "index", None) or {}).get("nodes") or {}).get(node_id)
    if isinstance(ent, dict):
        ent["importance"] = fm.get("importance")
        ent["tags"] = list(tg)
        ent["insight_state"] = final
    _append(cg, {"action": "verify", "node_id": node_id, "state": final,
                 "decided": True, "reason": reason or "显式裁决",
                 "evidence": ev, "importance": fm.get("importance"),
                 "actor": actor, "ts": time.time()})
    return {"ok": True, "action": "verify", "node_id": node_id, "state": final,
            "decided": True, "reason": reason or "显式裁决", "evidence": ev,
            "evidence_count": len(fm["insight_evidence"]),
            "importance": fm.get("importance"),
            "protected": bool(fm.get("protected")),
            "note": "verified 后重要度保底 %s 并置保护位" % IMPORTANCE_FLOOR}


# ---------------------------------------------------------------- list / report

def list_events(cg, state=None, limit=0):
    out = []
    for nid in _events(cg):
        node = _read_event(cg, nid)
        if not node:
            continue
        fm = node.get("frontmatter") or {}
        st = fm.get("insight_state")
        if state and st != state:
            continue
        out.append({"node_id": nid, "state": st,
                    "category": fm.get("insight_category"),
                    "importance": fm.get("importance"),
                    "window_open": bool(fm.get("insight_window_open")),
                    "created_at": fm.get("created_at"),
                    "evidence_count": len(fm.get("insight_evidence") or []),
                    "reason": fm.get("insight_reason")})
    out.sort(key=lambda x: x.get("created_at") or 0)
    return out[-int(limit):] if limit else out


def report(cg, window_days=None, now=None):
    """CER 条件有效洞见率报告（样本不足不判定）。

    CER = verified /（verified + falsified）；显著性带宽 = 2×SE，
    SE = sqrt(p(1-p)/n)。层状态：reliable / watch / degraded / insufficient。
    """
    now = float(now or time.time())
    events = list_events(cg)
    if window_days:
        lo = now - float(window_days) * 86400.0
        events = [e for e in events if (e.get("created_at") or 0) >= lo]
    n = len(events)
    verified = sum(1 for e in events if e["state"] == STATE_VERIFIED)
    falsified = sum(1 for e in events if e["state"] == STATE_FALSIFIED)
    pending = sum(1 for e in events if e["state"] == STATE_PENDING)
    open_windows = sum(1 for e in events if e["window_open"])
    denom = verified + falsified
    out = {"ok": True, "action": "report", "op": "insight",
           "window_days": window_days, "recorded": n,
           "verified": verified, "falsified": falsified, "pending": pending,
           "decided": denom, "window_open_count": open_windows,
           "window_open_rate": (round(open_windows / n, 4) if n else None),
           "sample_min": CER_MIN_SAMPLES, "cer": None, "se": None, "two_se": None,
           "significant": None, "layer_state": "insufficient", "note": ""}
    if denom < CER_MIN_SAMPLES:
        out["note"] = ("样本不足（已裁决 %d < %d）：按纪律不判定层状态，"
                       "避免小样本过拟合" % (denom, CER_MIN_SAMPLES))
        return out
    p = verified / denom
    se = math.sqrt(max(0.0, p * (1.0 - p)) / denom)
    out.update({"cer": round(p, 4), "se": round(se, 4),
                "two_se": round(2 * se, 4), "significant": bool(p > 2 * se)})
    if not out["significant"]:
        out["layer_state"] = "degraded" if p < 0.3 else "watch"
    else:
        out["layer_state"] = "reliable" if p >= 0.5 else "watch"
    out["note"] = ("CER = 已验证 /（已验证 + 已证伪）；2×SE 为显著性带宽；"
                   "reliable/watch/degraded 只描述条件层有效性趋势，不构成结论")
    return out


# ---------------------------------------------------------------- outlook

def _layer_of(entry):
    return str((entry or {}).get("layer") or "unknown")


def _quartiles(values):
    if not values:
        return {"min": None, "p50": None, "p90": None, "max": None}
    vs = sorted(values)
    def _q(f):
        i = min(len(vs) - 1, max(0, int(round(f * (len(vs) - 1)))))
        return round(vs[i], 4)
    return {"min": _q(0.0), "p50": _q(0.5), "p90": _q(0.9), "max": _q(1.0)}


def outlook(cg, window_days=None, sample_limit=8, recent_days=7, now=None):
    """结构洞察：D1 结构判断 + D2 盲区与趋势建议（只读）。

    D1 —— 关于**自身记忆结构**的判断：分层分布、重要度分位、保护率、验证基底
          分布、条件缺口（缺不适用条件）比例、近期增长。
    D2 —— 盲区与趋势建议：洞见层 CER 报告、未裁决堆积、unresolved/无锚点盲区、
          以及**可执行的下一步建议**（带证据与建议调用）。

    诚实边界：本函数只做**结构描述与差距定位**，不判有效性、不替调用方下结论；
    样本不足或指标缺失时返回 None / 显式缺口，而不是编一个数。
    """
    now = float(now or time.time())
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    total = len(nodes)
    layers, basis = {}, {}
    imps, protected, no_neg, recent = [], 0, 0, 0
    lo_recent = now - float(recent_days) * 86400.0
    hi_imp_unprotected = []
    for nid, e in nodes.items():
        e = e or {}
        layers[_layer_of(e)] = layers.get(_layer_of(e), 0) + 1
        b = str(e.get("verification_basis") or "unset")
        basis[b] = basis.get(b, 0) + 1
        try:
            iv = float(e.get("importance") or 0.0)
        except (TypeError, ValueError):
            iv = 0.0
        imps.append(iv)
        if e.get("protected"):
            protected += 1
        elif iv >= IMPORTANCE_FLOOR:
            hi_imp_unprotected.append(nid)
        if not e.get("has_neg_conditions"):
            no_neg += 1
        ca = e.get("created_at")
        if ca and float(ca) >= lo_recent:
            recent += 1

    events = list_events(cg)
    pending = sum(1 for x in events if x["state"] == STATE_PENDING)
    rep = report(cg, window_days=window_days, now=now)

    d1 = {
        "total": total,
        "layers": dict(sorted(layers.items(), key=lambda kv: (-kv[1], kv[0]))),
        "importance": _quartiles(imps),
        "protected": protected,
        "protected_rate": (round(protected / total, 4) if total else None),
        "verification_basis": dict(sorted(basis.items(), key=lambda kv: (-kv[1], kv[0]))),
        "missing_non_applicable": no_neg,
        "missing_non_applicable_rate": (round(no_neg / total, 4) if total else None),
        "recent_%dd" % int(recent_days): recent,
        "growth_%dd" % int(recent_days): (round(recent / total, 4) if total else None),
    }
    d2 = {
        "insight": {"recorded": rep["recorded"], "pending": rep["pending"],
                    "verified": rep["verified"], "falsified": rep["falsified"],
                    "cer": rep["cer"], "two_se": rep["two_se"],
                    "layer_state": rep["layer_state"], "sample_min": rep["sample_min"]},
        "unresolved_nodes": layers.get("unresolved", 0),
        "high_importance_unprotected": sorted(hi_imp_unprotected)[:sample_limit],
    }

    suggestions = []
    if basis.get("unset", 0):
        suggestions.append({"priority": "P0", "action": "补验证基底",
                            "evidence": "%d 个节点 verification_basis 缺失" % basis["unset"],
                            "call": 'cg(op="maintain", action="importance", apply=true)'})
    if hi_imp_unprotected:
        suggestions.append({"priority": "P0", "action": "给高重要度节点补保护/裁决",
                            "evidence": "%d 个高重要度节点未保护" % len(hi_imp_unprotected),
                            "call": 'cg(op="insight", action="verify", node_id=..., evidence=[...])'})
    if no_neg:
        suggestions.append({"priority": "P1", "action": "补不适用条件（提升可判定性）",
                            "evidence": "%d 个节点缺不适用条件" % no_neg,
                            "call": 'cg(op="maintain", action="importance", apply=true)'})
    if pending >= 3:
        suggestions.append({"priority": "P1", "action": "给堆积的洞见补外部证据",
                            "evidence": "%d 条 pending 洞见未裁决" % pending,
                            "call": 'cg(op="insight", action="list", state="pending")'})
    if layers.get("unresolved"):
        suggestions.append({"priority": "P1", "action": "把未决查询转入盲区学习闭环",
                            "evidence": "%d 条 unresolved" % layers["unresolved"],
                            "call": 'cg(op="insight", action="learn", apply=true)'})
    if layers.get("contextual", 0) > max(3, layers.get("knowledge", 0)):
        suggestions.append({"priority": "P2", "action": "归纳情境记忆为概念层",
                            "evidence": "contextual %d > knowledge %d"
                                        % (layers.get("contextual", 0),
                                           layers.get("knowledge", 0)),
                            "call": 'cg(op="consolidate", action="induce", apply=true)'})
    if rep["layer_state"] == "insufficient":
        suggestions.append({"priority": "P2", "action": "积累洞见样本后再判层状态",
                            "evidence": "已裁决 %d < %d" % (rep["decided"], rep["sample_min"]),
                            "call": 'cg(op="insight", action="report")'})

    return {"ok": True, "action": "outlook", "op": "insight",
            "d1": d1, "d2": d2, "suggestions": suggestions,
            "generated_at": now,
            "note": ("结构描述与差距定位，不判有效性；suggestions 按优先级给出，"
                     "需调用方自行执行并核对")}
