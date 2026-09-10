# -*- coding: utf-8 -*-
"""位置权重矩阵（序标定）——「不同身份，参数偏好不同」。

理论出处（本仓原文，非外部知识）
--------------------------------
`docs/智能的公理化基石.md` §4.3：信任合成是
    P_trust = f(一致性, 位置可预测性, 版本对齐度)
其中 `版本对齐度` 已由 `theory` + `links.version_alignment` 提供，
`位置可预测性` 见 `predict`，`一致性` 见 `consistency`。本模块只补一件
此前缺失的东西：**三个分量在不同位置下的偏好序**。

六个位置分为**两类**（由功能身份决定，非人为指定）：

  · 认知视角（viewpoint）：设计者 / 反思 / 验证
    ——「思考的不同视角」，**三分量都涉及**，只标定主导，**不设零**。
  · 功能单元（functional）：记录 / 输出 / 维生
    ——功能需求决定，**身份即排除**：主导 + 明确排除一项（≈0）。

排除项可**推导**（派生律：功能身份 → 缺失分量），不是选出来的：

  · 记录单元**不猜**      → 不做预测 → 排除 位置可预测性
  · 输出单元**不记**      → 不复现对账 → 排除 一致性
  · 维生系统**不对外**    → 无外部协议 → 排除 版本对齐度

设计者定位（本轮裁决）：
  · **不参与日常评估**——它是元视角，思考总体规律；细节由反思/验证承担，
    否则要做全局细节整理，耗时极长。

可推导不变量（`invariants()` 逐条自检）
--------------------------------------
  1. **排除唯一**——每个分量恰被 **1** 个位置排除；因视角「3 项都涉及」，
     故每个分量的参与度 = **5/6**（不是 3/6）；
  2. **排除项只属功能单元**，且 A/B/C 各被排除一次；
  3. **视角主导 ↔ 功能单元排除**一一配对：
     设计者(A)↔维生、反思(B)↔记录、验证(C)↔输出。

诚实边界
--------
· 本模块只声明**序**（谁能压过谁），**不宣称数值**——与 `links.py` 的
  `UP_STEP`/`DECAY_DAYS` 同一纪律（文档 §4.3：「v0.1 只声明结构」）。
· `blend()` 里的权重是**占位值**（用序秩当量级），仅供仿真，标定属 v0.3。

零第三方依赖。
"""
from __future__ import annotations

import math
import os
import time

from .fsutil import append_jsonl, read_jsonl

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

#: 三个分量（顺序即 A/B/C，稳定，供外部按位引用）
COMPONENTS = ("version_alignment", "predictability", "consistency")

#: 分量中文名（日志/自描述用）
COMPONENT_LABELS = {
    "version_alignment": "版本对齐度",
    "predictability": "位置可预测性",
    "consistency": "一致性",
}

#: 位置类别
VIEWPOINT = "viewpoint"      # 认知视角：3 项都涉及，只标主导，不设零
FUNCTIONAL = "functional"    # 功能单元：主导 + 明确排除一项

#: 位置 → 权重序规格
#:   primary   主导分量（权重最高）
#:   secondary 次主导分量（功能单元的第二个偏好；视角为 None=另两项并列）
#:   excluded  被排除分量（≈0；仅功能单元有；视角为 None=不设零）
SPEC = {
    # ---- 认知视角（不参与日常评估者仅 designer）----
    "designer": {"class": VIEWPOINT, "primary": "version_alignment",
                 "secondary": None, "excluded": None},
    "reflect": {"class": VIEWPOINT, "primary": "predictability",
                "secondary": None, "excluded": None},
    "verify": {"class": VIEWPOINT, "primary": "consistency",
               "secondary": None, "excluded": None},
    # ---- 功能单元（身份即排除）----
    "record": {"class": FUNCTIONAL, "primary": "consistency",
               "secondary": "version_alignment", "excluded": "predictability"},
    "output": {"class": FUNCTIONAL, "primary": "predictability",
               "secondary": "version_alignment", "excluded": "consistency"},
    "sustain": {"class": FUNCTIONAL, "primary": "consistency",
                "secondary": "predictability", "excluded": "version_alignment"},
}

POSITION_ORDER = ("designer", "record", "reflect", "verify", "output", "sustain")

#: 参与**日常评估**的位置（设计者是元参照系，不入日常）
DAILY = ("record", "reflect", "verify", "output", "sustain")

#: 序秩（占位量级，仅仿真用）：主导 2 / 次主导 1 / 排除 0；视角另两项 = 1
RANK_PRIMARY = 2.0
RANK_SECONDARY = 1.0
RANK_EXCLUDED = 0.0


class WeightError(Exception):
    """未知位置 / 未知分量。"""


# --------------------------------------------------------------------------
# 基础查询
# --------------------------------------------------------------------------

def _spec(position: str) -> dict:
    s = SPEC.get(str(position or "").strip())
    if s is None:
        raise WeightError(f"未知位置：{position!r}（允许：{POSITION_ORDER}）")
    return s


def _comp(component: str) -> str:
    c = str(component or "").strip()
    if c not in COMPONENTS:
        raise WeightError(f"未知分量：{component!r}（允许：{COMPONENTS}）")
    return c


def is_viewpoint(position: str) -> bool:
    """是否认知视角（3 项都涉及，不设零）。"""
    return _spec(position)["class"] == VIEWPOINT


def is_functional(position: str) -> bool:
    """是否功能单元（身份即排除）。"""
    return _spec(position)["class"] == FUNCTIONAL


def in_daily_eval(position: str) -> bool:
    """是否参与日常评估（设计者=False，元参照系）。"""
    _spec(position)
    return position in DAILY


def dominant(position: str) -> str:
    """主导分量（权重最高者）。"""
    return _spec(position)["primary"]


def secondary(position: str):
    """次主导分量；视角返回 None（另两项并列、均 >0）。"""
    return _spec(position)["secondary"]


def excluded(position: str):
    """被排除分量（≈0）；视角返回 None（不设零）。"""
    return _spec(position)["excluded"]


# --------------------------------------------------------------------------
# 序比较（本模块的权威结论：只有序，没有数值）
# --------------------------------------------------------------------------

def rank(position: str, component: str) -> float:
    """分量在该位置的序秩（占位量级）：2 主导 / 1 参与 / 0 排除。"""
    s = _spec(position)
    c = _comp(component)
    if s["excluded"] == c:
        return RANK_EXCLUDED
    if s["primary"] == c:
        return RANK_PRIMARY
    return RANK_SECONDARY


def prefers(position: str, a: str, b: str):
    """该位置是否**严格**偏好 a 胜过 b。

    返回 True / False / None（None = 二者并列，无严格序）。
    """
    ra, rb = rank(position, a), rank(position, b)
    if ra == rb:
        return None
    return ra > rb


def order(position: str):
    """从高到低排列的分量（并列者按 COMPONENTS 稳定序）；排除项单独列出。"""
    _spec(position)
    ranked = sorted(COMPONENTS, key=lambda c: (-rank(position, c), COMPONENTS.index(c)))
    kept = [c for c in ranked if rank(position, c) > 0]
    exc = [c for c in ranked if rank(position, c) == 0]
    return {"preferred": kept, "excluded": exc,
            "primary": dominant(position), "secondary": secondary(position)}


def weights(position: str) -> dict:
    """占位数值权重（序秩归一化）；**未标定**，仅供仿真。"""
    _spec(position)
    raw = {c: rank(position, c) for c in COMPONENTS}
    total = sum(raw.values()) or 1.0
    return {c: round(raw[c] / total, 4) for c in COMPONENTS}


# --------------------------------------------------------------------------
# 合成（占位：f(一致性, 位置可预测性, 版本对齐度)）
# --------------------------------------------------------------------------

def blend(position: str, components: dict) -> dict:
    """按位置的权重合成单一信任标量。

    `components` 形如 {"version_alignment": 1.0, "predictability": 0.8,
    "consistency": 0.6}；缺省按 0 计。

    **数值未标定**：这里用序秩当量级，只保证「主导分量对结果影响最大」这
    一方向性事实。标定属路线图 v0.3。
    """
    s = _spec(position)
    w = weights(position)
    vals = {}
    for c in COMPONENTS:
        try:
            vals[c] = max(0.0, min(1.0, float(components.get(c, 0.0))))
        except (AttributeError, TypeError, ValueError):
            vals[c] = 0.0
    score = sum(w[c] * vals[c] for c in COMPONENTS)
    return {"position": position, "class": s["class"],
            "weights": w, "values": vals, "score": round(score, 4),
            "dominant": s["primary"],
            "note": "权重为占位序秩（未标定）；仅方向性结论可信"}


# --------------------------------------------------------------------------
# 不变量自检（把上轮的三条结构约束落成可执行断言）
# --------------------------------------------------------------------------

def invariants() -> dict:
    """逐条自检结构约束，返回 {ok, checks{name: {ok, detail}}}。"""
    checks = {}

    # ① 排除唯一：每分量恰被 1 个位置排除 ⇒ 参与度 = 5/6
    part = {c: [p for p in POSITION_ORDER if rank(p, c) > 0] for c in COMPONENTS}
    exc_of = {c: [p for p in POSITION_ORDER if rank(p, c) == 0] for c in COMPONENTS}
    checks["excluded_exactly_once"] = {
        "ok": all(len(exc_of[c]) == 1 for c in COMPONENTS)
              and all(len(part[c]) == len(POSITION_ORDER) - 1 for c in COMPONENTS),
        "detail": {c: {"participants": len(part[c]), "excluded_by": exc_of[c]}
                   for c in COMPONENTS}}

    # ② 排除项只属功能单元，且每分量各被排除一次
    excs = {}
    for p in POSITION_ORDER:
        e = excluded(p)
        if e is None:
            continue
        excs.setdefault(e, []).append(p)
    only_functional = all(is_functional(p)
                          for vs in excs.values() for p in vs)
    both = all(len(excs.get(c) or []) == 1 for c in COMPONENTS)
    checks["exclusion_functional_only_once_each"] = {
        "ok": bool(excs) and only_functional and both,
        "detail": {c: excs.get(c, []) for c in COMPONENTS}}

    # ③ 视角主导 ↔ 功能单元排除 一一配对
    dom_pairs = {}          # 分量 → 视角
    for p in POSITION_ORDER:
        if is_viewpoint(p):
            dom_pairs.setdefault(dominant(p), []).append(p)
    pairing = {}
    for p in POSITION_ORDER:
        if not is_functional(p):
            continue
        e = excluded(p)
        if e and len(dom_pairs.get(e) or []) == 1:
            pairing[dom_pairs[e][0]] = p
    checks["viewpoint_dominant_pairs_unit_exclusion"] = {
        "ok": len(pairing) == 3,
        "detail": pairing}

    # ④ 功能单元恰有一个排除项；视角一个都没有
    checks["functional_excludes_exactly_one"] = {
        "ok": all(excluded(p) is not None for p in POSITION_ORDER
                  if is_functional(p))
              and all(excluded(p) is None for p in POSITION_ORDER
                      if is_viewpoint(p)),
        "detail": {p: excluded(p) for p in POSITION_ORDER}}

    # ⑤ 排除项序秩严格最低
    checks["excluded_is_lowest"] = {
        "ok": all(rank(p, excluded(p)) < rank(p, c)
                  for p in POSITION_ORDER if excluded(p)
                  for c in COMPONENTS if c != excluded(p)),
        "detail": "排除分量序秩 0，严格低于其余分量"}

    return {"ok": all(c["ok"] for c in checks.values()), "checks": checks}


# --------------------------------------------------------------------------
# 自描述
# --------------------------------------------------------------------------

def catalog() -> dict:
    """位置权重矩阵自描述（供 MCP / 文档对照验证）。"""
    return {
        "question": "不同身份，参数偏好不同",
        "components": {c: COMPONENT_LABELS[c] for c in COMPONENTS},
        "classes": {
            VIEWPOINT: "认知视角：3 项都涉及，只标主导，不设零",
            FUNCTIONAL: "功能单元：身份即排除（不猜/不记/不对外）",
        },
        "positions": {p: dict(SPEC[p]) for p in POSITION_ORDER},
        "daily_eval": list(DAILY),
        "meta_reference": [p for p in POSITION_ORDER if p not in DAILY],
        "derivation": {"record": "不猜 → 排除 位置可预测性",
                       "output": "不记 → 排除 一致性",
                       "sustain": "不对外 → 排除 版本对齐度"},
        "formula": "P_trust = f(一致性, 位置可预测性, 版本对齐度)",
        "honest_boundary": "只声明序，不宣称数值；blend() 权重为占位序秩",
    }


# ==========================================================================
# 结构重要性重算（maintain.importance）
# ==========================================================================
#
# 与上面的「位置权重矩阵」是**两件事**，不要混：
#   · 上面回答「不同身份偏好哪些信任分量」（序标定，作用于位置）；
#   · 下面回答「一个节点在认知图结构里该有多大重要性」（重算，作用于节点）。
#
# 三个**可测**分量（对齐计划：按覆盖度、冗余度、验证基底重排）：
#   coverage   覆盖度 —— 有多少节点指向/包含它（入度，结构中枢性）
#   redundancy 冗余度 —— 与同层节点内容哈希撞车的比例（越冗余越该降权）
#   basis      验证基底 —— 外部验证档位（formal_proof/compiler > test > measurement > data > other）
#
# 纪律：只改 `frontmatter.importance` 与索引快照，**不动正文**（减小 diff 与重写成本）；
# 全流程可预演（apply=False）、可留痕（`_maintain.jsonl`）、可回滚（rollback）。
# 性能：dry-run 不读任何节点文件（只用索引快照）；apply 只写「变动超阈值」的节点。

MAINTAIN_LOG = "_maintain.jsonl"

#: 验证基底 → 可信权重（枚举来自 nodefile.VERIFICATION_BASIS）
#: 文科来源一致性档（textbook/public_kb）低于可复现档、高于 other：
#: 教材/公开知识库是权威二手来源，但不是可复算证据。
BASIS_TRUST = {
    "formal_proof": 1.00,
    "compiler": 0.90,
    "test": 0.80,
    "measurement": 0.65,
    "textbook": 0.60,
    "data": 0.45,
    "public_kb": 0.40,
    "other": 0.25,
}
BASIS_TRUST_MISSING = 0.25

#: 三分量合成权重（占位量级，沿用「只声明序」纪律；分量序主导→次要）
IMPORTANCE_MIX = {"basis": 0.40, "coverage": 0.35, "redundancy": 0.25}
COV_SAT = 12.0              # 入度饱和点：约 12 条入边即视为覆盖满
IMPORTANCE_FLOOR = 0.10
IMPORTANCE_CEIL = 1.00
IMPORTANCE_PROTECT = 0.70   # ≥ 此值：保护下限（已保护/高危节点不被降破）
APPLY_DELTA = 0.05          # 变动小于此值不写盘（防 IO 放大）


def _targets(e: dict):
    """索引快照里的「出边目标」：edges ∪ subgraph.nodes（兼容 dict/str）。"""
    out = []
    for x in (e.get("edges") or []):
        if isinstance(x, dict):
            t = x.get("to") or x.get("target") or x.get("node") or x.get("id")
        else:
            t = x
        if t:
            out.append(str(t))
    sg = e.get("subgraph")
    raw = sg.get("nodes") if isinstance(sg, dict) else sg
    if isinstance(raw, (list, tuple)):
        for n in raw:
            nid = n.get("id") if isinstance(n, dict) else n
            if nid:
                out.append(str(nid))
    return out


def basis_trust(basis):
    """验证基底 → 可信权重；缺失/未知一律给最低档（不假装可信）。"""
    if basis is None:
        return BASIS_TRUST_MISSING
    return BASIS_TRUST.get(str(basis).strip().lower(), BASIS_TRUST_MISSING)


def coverage_index(cg) -> dict:
    """入度表：nid → 被多少节点指向（覆盖度，O(N) 免读文件）。"""
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    indeg = {nid: 0 for nid in nodes}
    for nid, e in nodes.items():
        for t in _targets(e):
            if t in indeg and t != nid:
                indeg[t] += 1
    return indeg


def redundancy_map(cg, layer=None) -> dict:
    """同层内容哈希撞车 → 冗余度 1.0，否则 0.0（精确冗余，O(N) 免读文件）。

    诚实边界：这是**精确冗余**（同一层出现完全相同的正文），不是语义近似冗余。
    语义近似由 `forgetting.redundancy`（bigram 覆盖）在写入侧单独负责。
    """
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    seen, out = {}, {}
    for nid, e in nodes.items():
        if layer and e.get("layer") != layer:
            continue
        h = e.get("content_hash") or ""
        if not h:
            out[nid] = 0.0
            continue
        key = (e.get("layer"), h)
        if key in seen:
            out[nid] = 1.0
            out[seen[key]] = 1.0
        else:
            seen[key] = nid
            out.setdefault(nid, 0.0)
    return out


def node_importance(cg, nid, indeg=None, red=None, entry=None):
    """单节点结构重要性分解（可审计：给出分量而非只给分）。"""
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    e = entry if entry is not None else nodes.get(nid)
    if e is None:
        return None
    indeg = indeg if indeg is not None else coverage_index(cg)
    red = red if red is not None else redundancy_map(cg, layer=e.get("layer"))
    d = int(indeg.get(nid, 0) or 0)
    cov = min(1.0, math.log1p(d) / math.log1p(COV_SAT))
    rr = max(0.0, min(1.0, float(red.get(nid, 0.0) or 0.0)))
    bt = basis_trust(e.get("verification_basis"))
    score = (IMPORTANCE_MIX["basis"] * bt
             + IMPORTANCE_MIX["coverage"] * cov
             + IMPORTANCE_MIX["redundancy"] * (1.0 - rr))
    protected = bool(e.get("protected"))
    floor = IMPORTANCE_PROTECT if protected else IMPORTANCE_FLOOR
    score = max(floor, min(IMPORTANCE_CEIL, score))
    return {"node_id": nid,
            "before": float(e.get("importance", 0.5) or 0.5),
            "after": round(score, 4),
            "components": {"coverage": round(cov, 4), "redundancy": round(rr, 4),
                           "basis_trust": round(bt, 4), "in_degree": d,
                           "verification_basis": e.get("verification_basis")},
            "protected": protected,
            "protected_floor": protected}


def recalc(cg, layer=None, limit=None, apply=False, min_delta=APPLY_DELTA,
           actor="maintain", dry_run_samples=10):
    """结构重要性重算：覆盖度 + 冗余度 + 验证基底 → 重排节点重要性。

    apply=False（默认）只出报表，不写盘（对应计划「可预演」）。
    apply=True 逐节点改写 `frontmatter.importance`，每批写一条 `_maintain.jsonl`
    （before/after/分量/actor），并提供 rollback 反向应用。
    """
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    indeg = coverage_index(cg)
    red = redundancy_map(cg, layer=layer)
    ids = [nid for nid, e in nodes.items()
           if not layer or e.get("layer") == layer]
    ids.sort()
    if limit:
        ids = ids[:int(limit)]
    t0 = time.time()
    planned, changed, unchanged, skipped = [], 0, 0, 0
    before_sum = after_sum = 0.0
    by_layer = {}
    batch = time.strftime("%Y%m%d-%H%M%S")
    samples = []
    for nid in ids:
        info = node_importance(cg, nid, indeg=indeg, red=red)
        if info is None:
            skipped += 1
            continue
        before, after = info["before"], info["after"]
        before_sum += before
        after_sum += after
        lay = (nodes.get(nid) or {}).get("layer") or "?"
        bl = by_layer.setdefault(lay, {"nodes": 0, "changed": 0,
                                       "avg_before": 0.0, "avg_after": 0.0})
        bl["nodes"] += 1
        if abs(after - before) < float(min_delta):
            unchanged += 1
            continue
        changed += 1
        bl["changed"] += 1
        plan = dict(info)
        plan["batch"] = batch
        plan["delta"] = round(after - before, 4)
        planned.append(plan)
        if len(samples) < int(dry_run_samples):
            samples.append(plan)
    for lay, bl in list(by_layer.items()):
        bl["avg_before"] = 0.0
        bl["avg_after"] = 0.0
    written = 0
    if apply:
        for plan in planned:
            nid = plan["node_id"]
            node = cg.get(nid)
            if not node:
                continue
            fm = node.get("frontmatter") or {}
            fm["importance"] = plan["after"]
            fm["importance_source"] = "recalc"
            fm["importance_components"] = plan["components"]
            if plan["after"] >= IMPORTANCE_PROTECT and not fm.get("protected"):
                fm["protected"] = True
                fm["protection_reason"] = (f"recalc importance={plan['after']:.2f}"
                                           f"≥{IMPORTANCE_PROTECT}")
            path = os.path.join(cg.root, (nodes.get(nid) or {}).get("path")
                                or node.get("path") or f"{nid}.md")
            cg._write_node(nid, path, fm, node.get("content") or "")
            e = nodes.get(nid)
            if e is not None:
                e["importance"] = plan["after"]
                if fm.get("protected"):
                    e["protected"] = True
                    e["protection_reason"] = fm["protection_reason"]
            rec = {"t": time.time(), "action": "importance", "batch": batch,
                   "id": nid, "layer": (e or {}).get("layer"),
                   "before": plan["before"], "after": plan["after"],
                   "delta": plan["delta"], "components": plan["components"],
                   "actor": actor}
            append_jsonl(os.path.join(cg.root, MAINTAIN_LOG), rec)
            written += 1
        if written and hasattr(cg, "rebuild_index"):
            cg.rebuild_index()          # 索引与盘面重新对齐，防内存/磁盘分叉
    n = max(1, len(ids))
    return {
        "ok": True, "action": "importance", "dry_run": not apply,
        "batch": batch, "nodes_scanned": len(ids), "changed": changed,
        "unchanged": unchanged, "skipped": skipped, "written": written,
        "min_delta": float(min_delta),
        "avg_before": round(before_sum / n, 4),
        "avg_after": round(after_sum / n, 4),
        "by_layer": {k: {"nodes": v["nodes"], "changed": v["changed"]}
                     for k, v in by_layer.items()},
        "samples": samples, "elapsed_ms": int((time.time() - t0) * 1000),
        "log": MAINTAIN_LOG,
        "note": ("dry-run：未写盘；apply=True 才改写 importance"
                 if not apply else
                 f"已改写 {written} 个节点；回滚见 rollback(batch={batch})"),
    }


def rollback(cg, batch=None, entry_ids=None, actor="maintain"):
    """把重要性重算反向应用（bulk 改写的可回滚兑现）。

    batch 为空则回滚**最近一批**。返回 {ok, reverted, batch, ids}。
    """
    log_path = os.path.join(cg.root, MAINTAIN_LOG)
    records = [r for r in read_jsonl(log_path)
               if r.get("action") == "importance"]
    if not records:
        return {"ok": False, "error": "no_records", "reverted": 0}
    if entry_ids:
        want = {str(x) for x in entry_ids}
        records = [r for r in records if str(r.get("id")) in want]
    elif batch:
        records = [r for r in records if r.get("batch") == batch]
    else:
        batch = records[-1].get("batch")
        records = [r for r in records if r.get("batch") == batch]
    if not records:
        return {"ok": False, "error": "batch_not_found", "batch": batch,
                "reverted": 0}
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    reverted, ids = 0, []
    # 同一节点多条记录时以最早一条的 before 为准
    for rec in records:
        nid = rec.get("id")
        node = cg.get(nid)
        if not node:
            continue
        fm = node.get("frontmatter") or {}
        fm["importance"] = rec.get("before")
        fm["importance_source"] = "recalc_rollback"
        path = os.path.join(cg.root, (nodes.get(nid) or {}).get("path")
                            or node.get("path") or f"{nid}.md")
        cg._write_node(nid, path, fm, node.get("content") or "")
        e = nodes.get(nid)
        if e is not None:
            e["importance"] = rec.get("before")
        reverted += 1
        ids.append(nid)
    if reverted and hasattr(cg, "rebuild_index"):
        cg.rebuild_index()
    append_jsonl(log_path, {"t": time.time(), "action": "importance_rollback",
                            "batch": batch, "reverted": reverted, "actor": actor})
    return {"ok": True, "batch": batch, "reverted": reverted, "ids": ids}


def history(cg, limit=100, action=None):
    """维护留痕（最近 limit 条），可按 action 过滤。"""
    recs = list(read_jsonl(os.path.join(cg.root, MAINTAIN_LOG)))
    if action:
        recs = [r for r in recs if r.get("action") == action]
    return recs[-int(limit):]
