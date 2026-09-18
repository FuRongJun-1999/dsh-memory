# -*- coding: utf-8 -*-
"""记忆评审流水线 · 级 1：候选生成（确定性，零写入）。

真源：docs/记忆评审系统_立项设计与施工交接_20260915.md §3 第 1 级。

四源（可单独关闭）：

* ``assertion``   断言集超限项的**条目级展开**——复用 conformance 的**同一判据函数**
  （`_coverage_metrics` / `unanalyzed` / `_dup_metrics` / `_edge_metrics`），
  保证「报告聚合数」与「条目清单」两个入口同口径（见 test_mr_m1 T4）。
* ``defer_queue`` 闸门待裁决提案（inbox 未被 decisions 覆盖）＋遗忘日志 DEFER 留痕；
  未落盘的 node_id 计入 ``skipped``，**如实上报不冒充候选**。
* ``cold``        access log 触达集合之外、且重要度不低的节点（久未触达者更值得评审）。
* ``patrol``      sha1(node_id) 排序切片轮巡（offset 决定窗口位置），多轮不重不漏。

纪律：零写入；输出顺序由 (优先级, node_id) 决定；每条候选必带证据。
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import time

from .. import conformance as CF
from ..datapath import mdcg_root

SOURCES = ("assertion", "defer_queue", "cold", "patrol")
_PRIORITY = {"assertion": 0, "defer_queue": 1, "cold": 2, "patrol": 3}
FORGET_LOG = "_forgetting.jsonl"
PATROL_EPOCH = 3600.0          # 轮巡窗口推进周期（秒）：默认每窗口周期轮转一格
COLD_IMPORTANCE_MIN = 0.6      # 冷节点抽样门槛（importance 解析失败按 0 计）


# 生效条件：path 不满足 os.path.exists(path) 时返回 []；否则逐行 strip 后跳过空行与 json.JSONDecodeError 行，返回成功 json.loads 的每行结果列表。
def _read_jsonl(path: str) -> list:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


# 生效条件：os.path.join(root, CF.ACCESS_LOG) 不存在时返回空集；否则逐行解析，rec.get("ids") 为 list/tuple 时仅加入其中真值元素的 str 形式，nid 取 rec.get("id") or rec.get("node_id") or rec.get("nid") 的真值并加入 str(nid)，最终返回 seen & set(nodes)（仅保留 nodes 键内的 id）。
def _touched(root: str, nodes: dict) -> set:
    """access log 触达集（与 conformance._reach_metrics 同一解析口径：ids / id / node_id / nid）。"""
    p = os.path.join(root, CF.ACCESS_LOG)
    seen = set()
    if not os.path.exists(p):
        return seen
    with open(p, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            got = rec.get("ids")
            if isinstance(got, (list, tuple)):
                seen.update(str(x) for x in got if x)
            nid = rec.get("id") or rec.get("node_id") or rec.get("nid")
            if nid:
                seen.add(str(nid))
    return seen & set(nodes)


# 生效条件：str(layer)=="knowledge" 的节点在 role 为假值、CF._as_int(evidence_count)==0、或 {"doc","code"} 命中 CF._tag_prefixes(r) 时分别产出 missing_field/mixed_layer；任意节点在 CF._as_int(evidence_count)==0 且无 CF._basis_of(r) 且 lifecycle_state 为假值时产出 unanalyzed；str(content_hash) 既非 "None" 也非 "" 且同指纹计数 >1 时该组内每个节点产出 dup_content；edges 为 list/tuple 时逐条处理其中的 dict 边，当该边所有真值键（CF.CANONICAL_EDGE_KEYS 与 "type"）中不含任一规范键时产出 edge_non_canonical 并停止该节点后续边。
def _assertion_items(nodes: dict) -> list:
    """断言集超限项 → 条目级（判据函数与 conformance 同源，不另立口径）。"""
    out = []
    kn = {nid: r for nid, r in nodes.items() if str(r.get("layer")) == "knowledge"}
    for nid, r in kn.items():
        if not r.get("role"):
            out.append({"node_id": nid, "issue_kind": "missing_field",
                        "evidence": "role 为空（口径=conformance.stratum.role_coverage，knowledge 层分母）"})
        if CF._as_int(r.get("evidence_count")) == 0:
            out.append({"node_id": nid, "issue_kind": "missing_field",
                        "evidence": "evidence_count=0（口径=conformance.stratum.evidence_coverage）"})
        if {"doc", "code"} & CF._tag_prefixes(r):
            out.append({"node_id": nid, "issue_kind": "mixed_layer",
                        "evidence": "knowledge 层带 doc/code 标签（口径=conformance.stratum.mixed_ratio）"})
    for nid, r in nodes.items():
        if (CF._as_int(r.get("evidence_count")) == 0 and not CF._basis_of(r)
                and not r.get("lifecycle_state")):
            out.append({"node_id": nid, "issue_kind": "unanalyzed",
                        "evidence": "无一维分析痕迹（口径=conformance.unanalyzed 派生判据）"})
    ch = collections.Counter(str(r.get("content_hash")) for r in nodes.values())
    dup = {h for h, c in ch.items() if c > 1 and h not in ("None", "")}
    if dup:
        for nid, r in nodes.items():
            h = str(r.get("content_hash"))
            if h in dup:
                out.append({"node_id": nid, "issue_kind": "dup_content",
                            "evidence": "content_hash 重复组 %s（%d 条同指纹；口径=conformance.dup.content)" % (h, ch[h])})
    for nid, r in nodes.items():
        es = r.get("edges") or []
        if not isinstance(es, (list, tuple)):
            continue
        for e in es:
            if not isinstance(e, dict):
                continue
            keys = [k for k in CF.CANONICAL_EDGE_KEYS + ("type",) if e.get(k)]
            if not any(k in CF.CANONICAL_EDGE_KEYS for k in keys):
                out.append({"node_id": nid, "issue_kind": "edge_non_canonical",
                            "evidence": "边键非规范：%s（口径=conformance.edge.key.canonical）"
                                        % ("+".join(keys) or "<无关系键>")})
                break
    return out


# 生效条件：当 root、nodes 给定，对 _read_jsonl(root/CF.INBOX_LOG) 解析出的 inbox 记录中 pid（str(r.get("pid") or "")）非空且不在 decisions 中 x.get("pid") 真值 str 集合的记录，生成 origin=proposal、issue_kind=gate_defer 条目，其中 layer 直接取 r.get("layer") 不回落、content 取 r.get("content") or ""、tags 取 r.get("tags") or []、content_hash 取 r.get("payload_hash") or ""、node_id 取 str(r.get("id") or "") or None；再对 _read_jsonl(root/FORGET_LOG) 中 str(r.get("verdict"))=="DEFER" 的记录，若 str(r.get("node_id") or "") 非空且该 nid 是 nodes 的键则加入 out，否则加入 skipped（source=defer_queue、reason=node_not_landed、detail 为 nid 或 str(r.get("reason"))）；返回 (out, skipped)；
def _defer_items(root: str, nodes: dict):
    """闸门待裁决提案 + 遗忘日志 DEFER 留痕。返回 (items, skipped)。"""
    ib = _read_jsonl(os.path.join(root, CF.INBOX_LOG))
    dc = _read_jsonl(os.path.join(root, CF.DECISION_LOG))
    done = {str(x.get("pid")) for x in dc if x.get("pid")}
    out, skipped = [], []
    for r in ib:
        pid = str(r.get("pid") or "")
        if not pid or pid in done:
            continue
        out.append({"node_id": str(r.get("id") or "") or None, "origin": "proposal",
                    "proposal_id": pid, "issue_kind": "gate_defer",
                    "layer": r.get("layer"), "content": r.get("content") or "",
                    "tags": r.get("tags") or [], "content_hash": r.get("payload_hash") or "",
                    "evidence": "闸门待裁决提案（inbox 中 %s 未被 decisions 覆盖）" % pid})
    for r in _read_jsonl(os.path.join(root, FORGET_LOG)):
        if str(r.get("verdict")) != "DEFER":
            continue
        nid = str(r.get("node_id") or "")
        if nid and nid in nodes:
            out.append({"node_id": nid, "issue_kind": "gate_defer",
                        "evidence": "遗忘闸门 DEFER 留痕：%s" % str(r.get("reason"))})
        else:
            skipped.append({"source": "defer_queue", "reason": "node_not_landed",
                            "detail": nid or str(r.get("reason"))})
    return out, skipped


# 生效条件：取 nodes 中不在 _touched(root, nodes) 触达集、且 importance 经 _imp 归一后 >= COLD_IMPORTANCE_MIN 的节点，按归一 importance 降序（同值按 node_id 升序）后取 [:int(limit)]；limit=0 得空列表，limit 为负则排除末尾 |limit| 条而非空返回（源码无 int(limit)<=0 早退）。
def _cold_items(root: str, nodes: dict, limit: int) -> list:
    seen = _touched(root, nodes)

# 生效条件：r 的 importance 为真值且 float() 可转换时返回其 float 值；importance 为假值（None/0/""）时回落 0.0；转换抛 TypeError 或 ValueError 时返回 0.0。
    def _imp(r):
        try:
            return float(r.get("importance") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    rows = [(nid, r) for nid, r in nodes.items() if nid not in seen]
    rows.sort(key=lambda kv: (-_imp(kv[1]), kv[0]))
    picked = [(nid, r) for nid, r in rows if _imp(r) >= COLD_IMPORTANCE_MIN][:int(limit)]
    return [{"node_id": nid, "issue_kind": "cold",
             "evidence": "access log 未触达（importance=%.2f，排名第 %d）" % (_imp(r), i + 1)}
            for i, (nid, r) in enumerate(picked)]


# 生效条件：int(window) <= 0 或 nodes 为假值时返回 []；否则按 sha1(nid.encode("utf-8")).hexdigest() 排序，从 (int(offset)*int(window)) % len(nodes) 起取 int(window) 条，不足时用头部元素环绕补足。
def _patrol_items(nodes: dict, window: int, offset: int) -> list:
    if int(window) <= 0 or not nodes:
        return []
    ordered = sorted(nodes, key=lambda nid: hashlib.sha1(nid.encode("utf-8")).hexdigest())
    n = len(ordered)
    start = (int(offset) * int(window)) % n
    picked = ordered[start:start + int(window)]
    if len(picked) < int(window):                       # 环绕补足：多轮不重不漏
        picked = picked + ordered[:int(window) - len(picked)]
    return [{"node_id": nid, "issue_kind": "patrol",
             "evidence": "轮巡窗口 #%d（窗口 %d 条，按 sha1(node_id) 排序切片）" % (int(offset), int(window))}
            for nid in picked]


# 生效条件：items 逐条以 node_id 为真时 key=str(node_id)、否则 key="pid:"+str(proposal_id) 聚合；首次建房时 node_id 为真则取 nodes.get(node_id) or {} 作 meta，tags 取 it.get("tags") or meta.get("tags") or []，evidence 每聚合记录最多 8 条；结果 sources 去重后为空则置 ["-"]，priority 取 _PRIORITY.get(s, 9) 的最小值，按 (priority, str(key)) 排序返回。
def _merge(items: list, nodes: dict) -> list:
    """按条目（节点/提案）聚合：一条候选 = 一个待评条目，多个问题挂在 issue_kinds 上。"""
    acc = {}
    for it in items:
        nid = it.get("node_id")
        key = str(nid) if nid else "pid:" + str(it.get("proposal_id"))
        rec = acc.get(key)
        if rec is None:
            meta = nodes.get(nid) or {} if nid else {}
            rec = acc[key] = {
                "key": key, "node_id": nid or None, "proposal_id": it.get("proposal_id") or None,
                "origin": it.get("origin") or "node",
                "layer": it.get("layer") or meta.get("layer"),
                "sources": [], "issue_kinds": [], "evidence": [],
                "content": it.get("content") or "",
                "tags": list(it.get("tags") or meta.get("tags") or []),
                "content_hash": it.get("content_hash") or str(meta.get("content_hash") or ""),
            }
        src = it.get("source")
        if src and src not in rec["sources"]:
            rec["sources"].append(src)
        ik = it.get("issue_kind")
        if ik and ik not in rec["issue_kinds"]:
            rec["issue_kinds"].append(ik)
        ev = it.get("evidence")
        if ev and len(rec["evidence"]) < 8:
            rec["evidence"].append(ev)
    out = list(acc.values())
    for r in out:
        r["sources"] = sorted(set(r["sources"])) or ["-"]
        r["priority"] = min(_PRIORITY.get(s, 9) for s in r["sources"])
        r["issue_kinds"] = sorted(r["issue_kinds"])
    out.sort(key=lambda r: (r["priority"], str(r["key"])))
    return out


# 生效条件：root 为假值（None/""）时回落 mdcg_root()；nodes 为 None 时用 CF.load_index(root) or {}；wanted 为 (sources or SOURCES) 与 SOURCES 的交集，按其中是否含 assertion/defer_queue/cold/patrol 分派取候选（cold 传 cold_limit，patrol 传 patrol_window 与偏移，patrol_offset 为 None 时偏移取 int((now if now is not None else time.time())//PATROL_EPOCH)）；limit 为真值时才把 merged 截到 int(limit)；with_report 为真值时补 CF.check(root, check_paths=False) 的指标与失败断言 id。
def generate(root=None, *, sources=SOURCES, nodes=None, limit=None, cold_limit=500,
             patrol_window=200, patrol_offset=None, with_report=False, now=None) -> dict:
    """四源候选生成。nodes 可注入（测试用合成库，免读真源）。"""
    root = root or mdcg_root()
    if nodes is None:
        nodes = CF.load_index(root) or {}   # load_index 直接返回 nodes 字典
    wanted = [s for s in SOURCES if s in (sources or SOURCES)]
    items, skipped, by_source = [], [], {}
    if "assertion" in wanted:
        got = _assertion_items(nodes)
        by_source["assertion"] = len(got)
        items += [dict(x, source="assertion") for x in got]
    if "defer_queue" in wanted:
        got, sk = _defer_items(root, nodes)
        by_source["defer_queue"] = len(got)
        items += [dict(x, source="defer_queue") for x in got]
        skipped += sk
    if "cold" in wanted:
        got = _cold_items(root, nodes, cold_limit)
        by_source["cold"] = len(got)
        items += [dict(x, source="cold") for x in got]
    if "patrol" in wanted:
        off = int(patrol_offset) if patrol_offset is not None \
            else int((now if now is not None else time.time()) // PATROL_EPOCH)
        got = _patrol_items(nodes, patrol_window, off)
        by_source["patrol"] = len(got)
        items += [dict(x, source="patrol") for x in got]
    merged = _merge(items, nodes)
    if limit:
        merged = merged[:int(limit)]
    rep = {"root": root, "generated_at": float(now if now is not None else time.time()),
           "sources": wanted, "by_source": by_source, "total_raw": len(items),
           "total": len(merged), "candidates": merged, "skipped": skipped}
    if with_report:
        rep0 = CF.check(root, check_paths=False)
        rep["report"] = CF.metrics_of(rep0)
        rep["assertions"] = {"verdict": rep0.get("verdict"), "counts": rep0.get("counts"),
                             "failed": [c.get("id") for c in rep0.get("checks") or []
                                        if not c.get("ok")]}
    return rep
