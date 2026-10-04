# -*- coding: utf-8 -*-
"""L5 证据审计面：只读组装器（路线 C）——「现值＋出处链＋两存/备择＋盲区＋退役史」。

多主体世界模型对齐 v0.1 §4 路线 C：「给节点 id 输出『现值＋出处链＋两存/备择＋
盲区＋退役史』。**纯读、零写路径改动**」。命名约束（设计稿复核修订）：**不得
复用 `view` 参数名**（已被 roleviews 占用，mdcos._candidates 的 view 面）。

五面数据源（全部只读）：
  · 现值       —— `cg.get` 的 fm + 正文（层/生命态/验证态/时效/A1 检验强度/
                 A2 幽灵标记/归属面）；
  · 出处链     —— fm.derived_from（血缘）+ fm.edges（它引用谁）+ **反查**
                 索引条目 edges（谁引用它，内存扫描免读盘）+ provenance 台账
                 `_link.jsonl` 相关行；
  · 两存/备择   —— `cg.check_consistency(..., auto_flywheel=False, exclude=<自身>)`
                 的**只读复用**（与写入链同一判据）：同条件空间分歧/对照数/
                 截断如实透出（「两存之为默认、冲突一等」的可见化）；
  · 盲区       —— negative/positive evidence 计数、非适用条件、A2 幽灵标记、
                 trust.validity 判定（未生效/已过期/未知）、verification_state；
  · 退役史     —— fm.state_history / fm.verification_history（lifecycle/trust
                 的既有 HISTORY_FIELD 快照）+ `evolution.history` 台账。

成本如实：备择面复用一致性检查，大库上有候选截断（截断计数如实带出，hint
与写入面同款）；本组装器**不落盘、不改任何状态**。超出 cap 的面截断并计数。
"""
from __future__ import annotations

import os

__all__ = ["build"]

#: 各面截断上限（超限计数并如实带出 truncated）。
DEFAULT_CAP = 8


def _readable_guard(cg):
    """读隔离谓词（与 linkref.known_ids 同口径）：不可调用时全放行。"""
    fn = getattr(cg, "_readable", None)
    return fn if callable(fn) else (lambda _e: True)


def _referenced_by(cg, node_id, cap):
    """反查：谁引用了本节点（索引条目 edges 的内存扫描；免读盘）。

    **读隔离**（2026-10-05 复核 R3）：扫描按 `cg._readable` 过滤——不可读
    节点的 id 与其引用关系不得经本面泄漏（与 linkref.known_ids /
    evolution.entries 同口径：「不可见即不存在」）。
    """
    # H-4 纪律（test_h4_sustain_snapshot G1a）：从 cg.index 取回的 nodes
    # 须先取**快照**再迭代——并发写者 flush 时裸迭代会撞「字典变更」。
    _live = (getattr(cg, "index", None) or {}).get("nodes") or {}
    nodes = dict(_live)
    guard = _readable_guard(cg)
    out, total = [], 0
    for nid, e in nodes.items():
        if nid == node_id:
            continue
        try:
            if not guard(e):
                continue
        except Exception:                                 # noqa: BLE001 —— fail-closed
            continue
        for ed in (e.get("edges") or []):
            if str(ed.get("target")) == node_id:
                total += 1
                if len(out) < cap:
                    out.append({"from": nid, "relation": ed.get("relation_type"),
                                "confidence": ed.get("confidence"),
                                "source": ed.get("source")})
                break
    return {"items": out, "total": total, "truncated": total > len(out)}


def _link_rows(cg, node_id, cap):
    """provenance 台账（`_link.jsonl`）里与本节点相关的行。

    **schema 对齐 provenance.make_edge**（2026-10-05 复核 R1 修）：真字段是
    `child/parent/rel/t/actor`（原实现按 `target/source/relation/at` 匹配
    ⇒ 恒读空，整面死）。「与本节点相关」＝ child==本节点（它派生自谁）或
    parent==本节点（谁派生自它）。

    **行级读隔离**（2026-10-05 复验 R4 修）：行是否可见取决于**另一端**——
    「不可见即不存在」的口径下，verify 身份不得经本面看到不可读 secret
    节点的 id 与其派生关系（复验实证：修复前与 designer 视角逐位相同）。
    另一端条目不在索引或不可读 ⇒ **整行不出**（fail-closed，与
    `_referenced_by` 的 guard 同口径；自身端必可读——本函数只在本节点
    已可读[build 的 cg.get 成功]之后被调用）。
    """
    try:
        from . import provenance
        path = provenance.ledger_file(getattr(cg, "root", None))
    except Exception:                                     # noqa: BLE001
        return {"items": [], "total": 0, "truncated": False}
    if not path or not os.path.exists(path):
        return {"items": [], "total": 0, "truncated": False}
    _live = (getattr(cg, "index", None) or {}).get("nodes") or {}
    nodes = dict(_live)                    # H-4 快照纪律（迭代前取快照）
    guard = _readable_guard(cg)
    out, total = [], 0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    import json
                    rec = json.loads(line)
                except Exception:                         # noqa: BLE001
                    continue
                if not isinstance(rec, dict):
                    continue
                c, p = str(rec.get("child")), str(rec.get("parent"))
                if c == node_id:
                    other = p
                elif p == node_id:
                    other = c
                else:
                    continue
                e_other = nodes.get(other)
                if e_other is None:
                    continue                       # 另一端不在索引（含已删）→ 不出
                try:
                    if not guard(e_other):
                        continue                   # 另一端不可读 → 整行不出
                except Exception:                  # noqa: BLE001 —— fail-closed
                    continue
                total += 1
                if len(out) < cap:
                    out.append({k: rec.get(k) for k in
                                ("child", "parent", "rel", "t", "actor", "note")})
    except Exception:                                     # noqa: BLE001 —— 只读面不抛
        pass
    return {"items": out, "total": total, "truncated": total > len(out)}


def build(cg, node_id, cap=DEFAULT_CAP) -> dict:
    """组装五面只读视图。node_id 不存在 ⇒ {"ok": False, "error": "node_not_found"}。

    cap 防御（2026-10-05 复核 Y2）：非数/None 回落缺省、钳 [1, 64]——
    直调面与 MCP 面同语义（MCP 面的钳制在分发层，直调 API 不得裸抛 TypeError）。
    """
    try:
        cap = int(cap)
    except (TypeError, ValueError):
        cap = DEFAULT_CAP
    cap = max(1, min(64, cap))
    nid = str(node_id or "").strip()
    if not nid:
        return {"ok": False, "error": "node_not_found", "node_id": node_id}
    rec = cg.get(nid)
    if not rec:
        return {"ok": False, "error": "node_not_found", "node_id": nid}
    fm = rec.get("frontmatter") or {}
    content = rec.get("content") or ""
    from . import evolution, lifecycle, nodefile, trust

    # ---- 面一：现值 ----
    try:
        _validity = trust.validity(fm)
    except Exception as exc:                              # noqa: BLE001
        _validity = "%s: %s" % (type(exc).__name__, exc)
    present = {
        "layer": fm.get("layer"),
        "lifecycle_state": lifecycle.state_of(fm),
        "verification_state": trust.state_of(fm),
        "validity": _validity,
        "importance": fm.get("importance"),
        "sensitivity": fm.get("sensitivity"),
        "created_at": fm.get("created_at"),
        "tags": fm.get("tags"),
        "verification_basis": fm.get("verification_basis"),
        nodefile.CHECK_STRENGTH_FIELD: fm.get(nodefile.CHECK_STRENGTH_FIELD),
        nodefile.UNCERTAIN_REFS_FIELD: fm.get(nodefile.UNCERTAIN_REFS_FIELD),
        "writer": fm.get("writer"), "harness": fm.get("harness"),
        "session": fm.get("session"),
        "content_chars": len(content),
    }

    # ---- 面二：出处链 ----
    _edges = list(fm.get("edges") or [])
    sources = {
        "derived_from": fm.get("derived_from"),
        "derived_relation": fm.get("derived_relation"),
        "refers_to": {"items": _edges[:cap], "total": len(_edges),
                      "truncated": len(_edges) > cap},
        "referenced_by": _referenced_by(cg, nid, cap),
        "link_ledger": _link_rows(cg, nid, cap),
    }

    # ---- 面三：两存/备择（一致性只读复用；不建单、不落盘）----
    alternatives = {"comparable": None, "verdict": None, "conflicts": [],
                    "missing": [], "truncated": None, "scanned": None}
    try:
        # log_write=False（复核 R2 修）：只读消费面——判定照常、台账不写
        #（consistency.log 原为无条件追加，审计会变成隐式写）。
        cvd = cg.check_consistency(
            content, layer=fm.get("layer") or "knowledge",
            condition_space=fm.get("condition_space"),
            non_applicable_conditions=fm.get("non_applicable_conditions"),
            tags=fm.get("tags"), exclude=nid, auto_flywheel=False,
            log_write=False)
        if isinstance(cvd, dict):
            cf = list(cvd.get("conflicts") or [])
            alternatives = {
                "verdict": cvd.get("verdict"), "reason": cvd.get("reason"),
                "conflict_strength": cvd.get("conflict_strength"),
                "comparable": cvd.get("comparable"),
                "scanned": cvd.get("scanned"), "truncated": cvd.get("truncated"),
                "conflicts": cf[:cap],
                "conflicts_total": len(cf), "conflicts_truncated": len(cf) > cap,
                "missing": list(cvd.get("missing") or [])[:cap],
                "hint": cvd.get("hint"),
            }
    except Exception as exc:                              # noqa: BLE001 —— 只读面不抛
        alternatives["error"] = "%s: %s" % (type(exc).__name__, exc)

    # ---- 面四：盲区 ----
    blindspots = {
        "negative_evidence": fm.get("negative_evidence", 0),
        "positive_evidence": fm.get("positive_evidence", 0),
        "non_applicable_conditions": fm.get("non_applicable_conditions"),
        nodefile.UNCERTAIN_REFS_FIELD: fm.get(nodefile.UNCERTAIN_REFS_FIELD),
        "verification_state": trust.state_of(fm),
        "validity": _validity,
        "note": ("未决不进二值：DEFER/unresolved 痕迹在『两存/备择』与 "
                 "negative_evidence 面；本面只呈现，不下判断。"),
    }

    # ---- 面五：退役史 ----
    _sh = list(fm.get(lifecycle.HISTORY_FIELD) or [])
    _vh = list(fm.get(trust.HISTORY_FIELD) or [])
    _ev = []
    try:
        _ev = list((evolution.history(cg, nid, limit=cap) or {}).get("entries") or [])
    except Exception:                                     # noqa: BLE001
        pass
    history = {
        lifecycle.HISTORY_FIELD: _sh[-cap:],
        trust.HISTORY_FIELD: _vh[-cap:],
        "evolution": _ev[:cap],
        "totals": {lifecycle.HISTORY_FIELD: len(_sh),
                   trust.HISTORY_FIELD: len(_vh), "evolution_scanned": len(_ev)},
    }

    return {"ok": True, "node_id": nid, "cap": cap,
            "present": present, "sources": sources,
            "alternatives": alternatives, "blindspots": blindspots,
            "history": history}
