# -*- coding: utf-8 -*-
"""md_cg · 数据健康不变量断言集（Pi⑤）+ G1 类型空间正交性审计 + G3 unanalyzed 显式占位

把 2026-09-15 的一次性审计改写为**周期可复跑**的断言集（混层比例阈值 / 重复度阈值 /
字段覆盖率下限 / 闸门四态分布），挂 sustain 周期巡检；超阈值**只告警，不自动改数据**。

三条纪律：
1. **不变量 fail-closed**：类型空间封闭性 / 边键规范 / 边目标可解析 / 索引↔盘一致 /
   重复度不劣化——任一 FAIL = 库结构失真，须人工处置。
2. **健康指标只告警**：混层比 / role 覆盖率 / evidence 覆盖率 / 分析覆盖率 /
   闸门四态 / 触达率——低于靶值 WARN，不阻断、不改数据。
3. **缺数据源 → BLINDSPOT**（如实上报），绝不冒充 PASS。

G1（Ghidra 交接 §5.4）：输出各类型空间的「声明值 / 实测值 / 未声明已用 / 声明未用 /
跨空间重叠 / 方向口径分歧」——类型空间不封闭是写入侧漂移的前兆。

G3（同 §5.4）：unanalyzed 采用**派生断言**（不新增字段、零写入），判据
`evidence_count==0 ∧ verification_basis 空 ∧ lifecycle_state 空`。
不做字段级占位的理由：生命周期是单向降级轴，与分析覆盖正交，塞同一字段破坏正交性。

用法：
    python -m md_cg.conformance [--root R] [--json out.json] [--baseline b.json]
                               [--no-path-check] [--strict]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, deque

REPORT_VERSION = 1
INDEX_FILE = "_index.json"
ACCESS_LOG = "_access.log"
DECISION_LOG = os.path.join("hippocampus", "decisions.jsonl")
INBOX_LOG = os.path.join("hippocampus", "inbox.jsonl")
DEFAULT_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "mdcg")
#: _audit.jsonl 只读尾部窗口行数（append-only 全史可数十 MB，周期巡检不扫全史）
AUDIT_TAIL = 20000


# 生效条件：无入参，datapath.mdcg_root() 返回真值时返回该值，导入或调用抛异常、或返回假值（如空串）时返回模块常量 DEFAULT_ROOT；
def _default_root() -> str:
    """根解析沿用本仓约定：env `MDCG_ROOT` > `paths.json`（用户级，旧包内兼容读）
    > 用户级状态根 `data/mdcg`。

    走 `datapath.mdcg_root()`（兜底纪律：与其它工具同源解析，不另立一套）。
    """
    try:
        from .datapath import mdcg_root
        got = mdcg_root()
        if got:
            return got
    except Exception:                                       # noqa: BLE001
        pass
    return DEFAULT_ROOT

# 阈值口径 = 9-15 审计基线（2026-09-16 复跑实测：混层 6468/11076=58.4% / role 2.13% /
# verification_basis 60.3% / evidence 0.10% / dir_mismatch 0 / 闸门 142 条） + M4 治理靶值。
# 比率型阈值只表达「离靶多远」，不阻断任何写入。
# 注：触达率随 _access.log 滚动追加而单调增长，9-15 快照 7.0% → 09-16 实测 8.7%，
# 差异来自时间而非口径；故**不纳入基线不劣化比对**（日志轮转会误报）。
THRESHOLDS = {
    "stratum_ratio_max": 0.60,
    "stratum_target": 0.30,
    "role_coverage_min": 0.90,
    "evidence_coverage_min": 0.50,
    "analysis_coverage_min": 0.90,
    "reach_ratio_min": 0.30,
    "gate_sample_min": 20,
    # 样本下限：低于此值比率型指标不可判（如仓内自建语料），一律 BLINDSPOT 不冒充 PASS
    "min_nodes": 200,
}

#: 单一内容指纹的最大同组节点数（超过即「同模板批量写入」体征，须人工治理）
DUP_GROUP_MAX = 200

# 写侧规范边键。取证更正（2026-09-16）：subgraph.children_index:122 / parents_index:162
# 已含 `or e.get("type")` 容错，**读侧不忽略** legacy `type`（`subgraph` 内 normalize_edge
# 的 docstring 仍写「会被静默忽略」，属文档滞后于代码，已登记 DOC_CODE_DRIFT）。
# 仍记为规范项：chain.edge_rel 与 subgraph 双兼容是本库私约，非 md_cg 读侧（Rust 引擎 /
# 外部消费者）可能只读 relation_type。
CANONICAL_EDGE_KEYS = ("relation_type", "relation")
LAYER_DIRS = ("knowledge", "contextual", "self", "structural", "anchor",
              "rejected", "unresolved", "goals", "data", "trash")

# G1 静态登记：已取证的方向口径分歧（事实，非推断）
KNOWN_DIRECTION_CONFLICTS = [
    {"literal": "hierarchical",
     "conflict": "md_cg subgraph 视其为「本节点是子、target 是父」"
                 "（children_index:128）；白箱源库语义为 source 是父 —— 同名反义，"
                 "直接迁移整树倒置",
     "workaround": "migrate_wisdom_graph.SRC_REL_MAP 迁移时改写为 contains（语义等价）"},
]
# G1 静态登记：已核对**无**方向分歧的项（防止「看起来像冲突」被反复误报）
VERIFIED_CONSISTENT = [
    {"literal": "part_of / parent_of / contains",
     "verified": "children_index:128-135 与 parents_index:171-178 逐字对称、方向取反，自洽"},
]
# G1 已取证的**文档滞后于代码**实例（陈述与实现不符，非缺陷但会误导写侧）
DOC_CODE_DRIFT = [
    {"where": "subgraph.normalize_edge docstring:96",
     "claims": "「早期迁移器写的 type 会被静默忽略（subgraph 不兼容）」",
     "fact": "children_index:122 / parents_index:162 已含 `or e.get(\"type\")` 容错 —— "
             "读侧兼容，陈述已过期"},
]

# G1 静态登记：新增类型的散落点（回答「新增类型要不要改引擎」）
NEW_TYPE_TOUCHPOINTS = {
    "layer": ["mdcg.LAYERS", "mdcg.BUCKETED_LAYERS", "mdcg.NEG_MEMORY_MARKS",
              "nodefile(fm 契约)", "routing(bucket)", "MCP 工具面描述"],
    "edge_type": ["chain.EDGE_WEIGHTS", "subgraph(父子方向分支)",
                  "migrate_wisdom_graph.SRC_REL_MAP"],
}


# 生效条件：root 下 INDEX_FILE 可读且 JSON 顶层为 dict 并含 nodes 字典时返回该 nodes；不可读抛 OSError、JSON 非法抛 JSONDecodeError、nodes 非 dict 抛 ValueError；
def load_index(root: str) -> dict:
    """读索引快照（唯一必需数据源）；损坏即抛——断言集不建立在猜测上。"""
    with open(os.path.join(root, INDEX_FILE), encoding="utf-8") as f:
        raw = json.load(f)
    nodes = raw.get("nodes") if isinstance(raw, dict) else None
    if not isinstance(nodes, dict):
        raise ValueError(f"索引格式异常（缺 nodes 字典）: {root}/{INDEX_FILE}")
    return nodes


# 生效条件：path 不存在（os.path.exists 为假）时返回 []；存在时逐行解析，空行与 JSONDecodeError 行被跳过，返回可解析记录的列表（可能为 []）；
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


# 生效条件：rec 的 tags 缺失或为假值时按空列表处理，仅对含 ":" 的 tag 取首个冒号前的前缀构成集合并返回；无此类 tag 时返回空集合；
def _tag_prefixes(rec: dict) -> set:
    return {str(t).split(":", 1)[0] for t in (rec.get("tags") or []) if ":" in str(t)}


# 生效条件：r 的 verification_basis 为 list/tuple 时返回其真值元素的 str 列表；否则该值真值时返回 [str(b)]，缺失或为假值（None/空串/空容器）时返回 []；
def _basis_of(r: dict):
    b = r.get("verification_basis")
    if isinstance(b, (list, tuple)):
        return [str(x) for x in b if x]
    return [str(b)] if b else []


# 生效条件：无入参，返回 layer（取自导入的模块常量 LAYERS 的排序值）+ edge_type/derived_relation/verification_basis/lifecycle_state 五键声明值映射，后四键对应模块导入或属性取值失败、属性值为假值（空容器/None）时该键 declared=None；
def enum_spaces() -> dict:
    """各类型空间的声明值（模块真源取不到 → declared=None，报告标 BLINDSPOT）。"""
    from .mdcg import LAYERS
    spaces = {"layer": {"declared": sorted(LAYERS), "source": "mdcg.LAYERS"}}

# 生效条件：以 md_cg.<mod> 导入并 getattr(attr)（导入或取值抛异常则 val=None），把 {"declared": sorted(val) if val else None, "source": "<mod>.<attr>"} 写入片段外闭包变量 spaces 的 key 键（val 为假值时 declared=None），无返回值；
    def _grab(mod: str, attr: str, key: str):
        try:
            m = __import__(f"md_cg.{mod}", fromlist=[attr])
            val = getattr(m, attr, None)
        except Exception:                                  # noqa: BLE001
            val = None
        spaces[key] = {"declared": sorted(val) if val else None,
                       "source": f"{mod}.{attr}"}

    _grab("chain", "EDGE_WEIGHTS", "edge_type")
    _grab("provenance", "RELATIONS", "derived_relation")
    _grab("nodefile", "VERIFICATION_BASIS", "verification_basis")
    _grab("lifecycle", "STATES", "lifecycle_state")
    return spaces


# ---------------------------- 指标 ----------------------------

# 生效条件：对 nodes 各记录按 str(content_hash) 计数，content_hash 缺失被折成 "None"，返回出现次数 >1 且哈希不为 "None"/"" 的组数、涉及节点数与前 5 大组大小；
def _dup_metrics(nodes: dict) -> dict:
    ch = Counter(str(r.get("content_hash")) for r in nodes.values())
    groups = {h: c for h, c in ch.items() if c > 1 and h not in ("None", "")}
    return {"groups": len(groups), "nodes": sum(groups.values()),
            "largest": sorted(groups.values(), reverse=True)[:5]}


# 生效条件：对 nodes 中每个节点的 "edges" 真值且为 list/tuple 的边列表，仅遍历其中 dict 边；依据 CANONICAL_EDGE_KEYS 与 "type" 统计键组合、关系类型、总边数、非规范键样本（最多 5）和悬空边，返回汇总字典。
def _edge_metrics(nodes: dict) -> dict:
    types, key_mix = Counter(), Counter()
    total = dangling = with_edges = non_canonical = 0
    samples = []
    for nid, r in nodes.items():
        es = r.get("edges") or []
        if not isinstance(es, (list, tuple)) or not es:
            continue
        with_edges += 1
        for e in es:
            if not isinstance(e, dict):
                continue
            total += 1
            keys = [k for k in CANONICAL_EDGE_KEYS + ("type",) if e.get(k)]
            types[str(e.get("relation_type") or e.get("relation") or e.get("type"))] += 1
            key_mix["+".join(keys) if keys else "<无关系键>"] += 1
            if not any(k in CANONICAL_EDGE_KEYS for k in keys):
                non_canonical += 1
                if len(samples) < 5:
                    samples.append({"node": nid, "edge": dict(e)})
            tgt = e.get("target") or e.get("target_id")
            if tgt is None or str(tgt) not in nodes:
                dangling += 1
    return {"nodes_with_edges": with_edges, "total": total,
            "types": dict(types.most_common(20)), "key_mix": dict(key_mix.most_common(10)),
            "non_canonical": non_canonical, "dangling": dangling, "samples": samples}


# 生效条件：遍历 nodes 的值作为记录，path 经 str(r.get("path") or "") 为空即 missing++ 并 continue，不以记录含 layer/path 为前置；仅对非空 path 执行 layer 与 head 检查（layer 非空且 head != layer 且 head in LAYER_DIRS 时 layer_mismatch++），且 check_exists 为 True 时才对非空 path 以 os.path.join(root, rel) 判断不存在并计入 missing，最终返回 missing/layer_mismatch/samples 统计；。
def _path_metrics(root: str, nodes: dict, check_exists: bool) -> dict:
    missing = mismatch = 0
    samples = []
    for r in nodes.values():
        layer, p = str(r.get("layer") or ""), str(r.get("path") or "")
        if not p:
            missing += 1
            if len(samples) < 5:
                samples.append({"id": r.get("id"), "why": "path 缺失"})
            continue
        rel = p.replace("\\", "/")
        head = rel.split("/", 1)[0]
        if layer and head != layer and head in LAYER_DIRS:
            mismatch += 1
            if len(samples) < 5:
                samples.append({"id": r.get("id"), "path": p, "layer": layer})
        if check_exists and not os.path.exists(os.path.join(root, rel)):
            missing += 1
            if len(samples) < 5:
                samples.append({"id": r.get("id"), "path": p, "why": "文件不存在"})
    return {"missing": missing, "layer_mismatch": mismatch, "samples": samples}


# 生效条件：root 下 DECISION_LOG/INBOX_LOG 不存在时按空列表计，返回 decisions（decision 或 status 回落 "?" 的前 10 项）、decisions_total、inbox_pending=max(0, 收件数−决策数)、以及 _audit.jsonl 末尾 AUDIT_TAIL 行内 op 计数的前 6 项与尾窗元信息；
def _gate_metrics(root: str) -> dict:
    dec = _read_jsonl(os.path.join(root, DECISION_LOG))
    inbox = _read_jsonl(os.path.join(root, INBOX_LOG))
    ops = Counter()
    # _audit.jsonl 是 append-only 且可达数十 MB（真源 15.9MB / 7.4 万行）——
    # 只读尾部窗口（近 AUDIT_TAIL 行）取 op 分布，避免周期巡检在此处 O(全史)。
    audit = os.path.join(root, "_audit.jsonl")
    tail = []
    if os.path.exists(audit):
        with open(audit, encoding="utf-8", errors="replace") as f:
            tail = list(deque(f, maxlen=AUDIT_TAIL))
    for line in tail:
        if not line.strip():
            continue
        try:
            ops[str(json.loads(line).get("op"))] += 1
        except json.JSONDecodeError:
            continue
    return {"decisions": dict(Counter(str(r.get("decision") or r.get("status") or "?")
                                      for r in dec).most_common(10)),
            "decisions_total": len(dec),
            "inbox_pending": max(0, len(inbox) - len(dec)),
            "audit_ops": dict(ops.most_common(6)), "audit_tail_lines": len(tail),
            "audit_tail_window": AUDIT_TAIL}


# 生效条件：对 root 与 nodes，若 root/ACCESS_LOG 路径不存在则返回 {"distinct": None, "ratio": None, "lines": None}；否则逐行解析 JSON，当 "ids" 为 list 或 tuple 时把其中真值元素 str 后加入 seen，且当 "id"/"node_id"/"nid" 任一真值时把其 str 加入 seen，返回 distinct 为 seen 与 nodes 键交集数量、ratio 为 distinct/max(len(nodes),1)、lines 为非空行数。
def _reach_metrics(root: str, nodes: dict) -> dict:
    p = os.path.join(root, ACCESS_LOG)
    if not os.path.exists(p):
        return {"distinct": None, "ratio": None, "lines": None}
    seen, lines = set(), 0
    with open(p, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            lines += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            # 实际落盘形态：{"t":..., "ids":[<nid>,...], "tier":...}（_access.log 逐次追加）
            got = rec.get("ids")
            if isinstance(got, (list, tuple)):
                seen.update(str(x) for x in got if x)
            nid = rec.get("id") or rec.get("node_id") or rec.get("nid")
            if nid:
                seen.add(str(nid))
    hit = len(seen & set(nodes))
    return {"distinct": hit, "ratio": hit / max(len(nodes), 1), "lines": lines}


# 生效条件：对 nodes，筛出 layer 字符串为 "knowledge" 的 kn；mixed 为 kn 中标签前缀含 doc 或 code 的数量；返回全库 nodes 数与 knowledge 层数、mixed、mixed_ratio=mixed/max(len(kn),1)，以及全库口径 role_ratio/basis_ratio/evidence_ratio/state_ratio 和 knowledge 层口径 role_ratio_kn/basis_ratio_kn/evidence_ratio_kn。
def _coverage_metrics(nodes: dict) -> dict:
    """混层口径 + 字段覆盖率（9-15 审计基线口径，逐项可复现）。

    **分母口径取证（2026-09-16，关键）**：审计的「role 99.99% 为空」「evidence_count
    仅 6 条」是 **knowledge 层**分母；全库分母会摊薄成「role 2.13% / evidence 12 条」，
    把一个 99.99% 的空缺伪装成「还行」。故两类分母并存上报，**健康判据一律取
    knowledge 层口径**（`*_ratio_kn`），全库口径只作对照片段。
    """
    kn = [r for r in nodes.values() if str(r.get("layer")) == "knowledge"]
    mixed = sum(1 for r in kn if {"doc", "code"} & _tag_prefixes(r))
    n, nk = len(nodes), max(len(kn), 1)
    return {"nodes": n, "knowledge": len(kn), "mixed_layer": mixed,
            "mixed_ratio": mixed / nk,
            "role_ratio": sum(1 for r in nodes.values() if r.get("role")) / max(n, 1),
            "basis_ratio": sum(1 for r in nodes.values() if _basis_of(r)) / max(n, 1),
            "evidence_ratio": sum(1 for r in nodes.values()
                                  if _as_int(r.get("evidence_count")) > 0) / max(n, 1),
            "state_ratio": sum(1 for r in nodes.values()
                               if r.get("lifecycle_state")) / max(n, 1),
            # —— knowledge 层口径（= 审计原口径，判据用这组）——
            "role_ratio_kn": sum(1 for r in kn if r.get("role")) / nk,
            "basis_ratio_kn": sum(1 for r in kn if _basis_of(r)) / nk,
            "evidence_ratio_kn": sum(1 for r in kn
                                     if _as_int(r.get("evidence_count")) > 0) / nk}


# 生效条件：int(v) 转换成功时返回该整数；抛 TypeError/ValueError（如 None、非数字串）时返回 0；
def _as_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


# ---------------------------- G3 · unanalyzed 派生集合 ----------------------------

# 生效条件：仅当记录 _as_int(evidence_count)==0 且 verification_basis 为空且 lifecycle_state 为假值时计入 ids，返回 count、ratio=count/max(len(nodes),1) 与前 5 个 id 样本；
def unanalyzed(nodes: dict) -> dict:
    """G3：unanalyzed **派生**判据（不新增字段、零写入）。

    判据 = `evidence_count==0 ∧ verification_basis 空 ∧ lifecycle_state 空`
    —— 三者皆空 = 「无一维分析痕迹」，与「分析结论为负」不同（后者会留 basis）。

    不做字段级占位的理由（Ghidra 交接 §5.4）：
      * 生命周期是**单向降级轴**（active→converged→demoted→archived），与分析覆盖正交，
        塞进同一字段即破坏正交性；
      * **逃逸口已存在**——`verification_basis` 声明集里有 `other`（真源 273 条在用），
        「分析过但无法归类」有明确归宿，故「basis 为空」不再与「分析结论为空」混淆。
    """
    ids = [nid for nid, r in nodes.items()
           if _as_int(r.get("evidence_count")) == 0
           and not _basis_of(r)
           and not r.get("lifecycle_state")]
    return {"count": len(ids), "ratio": len(ids) / max(len(nodes), 1),
            "sample": ids[:5]}


# ---------------------------- G1 · 类型空间正交性审计 ----------------------------

# 生效条件：调用 _usage(nodes, edges) 时 edges 形参未被源码引用，对 nodes.values() 中每个节点 r，仅当 r.get("layer")、r.get("role")、r.get("derived_relation")、r.get("lifecycle_state") 为真值时分别以 str 值计入对应 Counter，_basis_of(r) 与 _tag_prefixes(r) 展开的元素分别计入 verification_basis 与 tag_prefix，再遍历各 r 的 r.get("edges") or [] 中 isinstance(e, dict) 的项按 edge_rel(e) 计数，最终 edge_type 仅保留键为真值的计数，返回 used 字典；
def _usage(nodes: dict, edges: dict) -> dict:
    """各类型空间的**实测**取值（与 enum_spaces 的声明值对照）。"""
    from .chain import edge_rel
    used = {
        "layer": Counter(str(r.get("layer")) for r in nodes.values() if r.get("layer")),
        "role": Counter(str(r.get("role")) for r in nodes.values() if r.get("role")),
        "verification_basis": Counter(b for r in nodes.values() for b in _basis_of(r)),
        "derived_relation": Counter(str(r.get("derived_relation"))
                                    for r in nodes.values() if r.get("derived_relation")),
        "lifecycle_state": Counter(str(r.get("lifecycle_state"))
                                   for r in nodes.values() if r.get("lifecycle_state")),
        "tag_prefix": Counter(p for r in nodes.values() for p in _tag_prefixes(r)),
    }
    rels = Counter()
    for r in nodes.values():
        for e in (r.get("edges") or []):
            if isinstance(e, dict):
                rels[edge_rel(e)] += 1
    used["edge_type"] = Counter({k: v for k, v in rels.items() if k})
    return used


# 生效条件：以 enum_spaces 的声明集与 _usage 的实测集逐空间对照（closed 仅在 declared 非 None 且无未声明已用时为 True），role 与 tag_prefix 两空间的 declared/closed 恒为 None，另附 _cross_space_overlap（字面量出现在 ≥2 空间或 layer∩tag_prefix）及 KNOWN_DIRECTION_CONFLICTS/VERIFIED_CONSISTENT/DOC_CODE_DRIFT/NEW_TYPE_TOUCHPOINTS 四个常量；
def _g1_audit(nodes: dict, edges: dict) -> dict:
    """G1：声明值 / 实测值 / 未声明已用 / 声明未用 / 跨空间重叠 / 方向口径分歧。"""
    spaces = enum_spaces()
    used = _usage(nodes, edges)
    out = {}
    for name, spec in spaces.items():
        dec = set(spec.get("declared") or [])
        u = set(used.get(name, {}).keys())
        out[name] = {
            "source": spec.get("source"),
            "declared": sorted(dec),
            "used": dict(used.get(name, {}).most_common(30)),
            "undeclared_used": sorted(u - dec),
            "declared_unused": sorted(dec - u),
            "closed": (spec.get("declared") is not None and not (u - dec)),
        }
    for name in ("role", "tag_prefix"):
        out[name] = {"source": None, "declared": None,
                     "used": dict(used.get(name, {}).most_common(30)),
                     "undeclared_used": sorted(used.get(name, {})),
                     "declared_unused": [], "closed": None}
    # 跨空间重叠：同一字面量出现在 ≥2 个空间 → 解析歧义风险
    owners = Counter()
    for name, spec in out.items():
        for lit in (spec.get("declared") or []):
            owners[str(lit)] += 1
    out["_cross_space_overlap"] = sorted(l for l, c in owners.items() if c > 1) + \
        sorted(set(used.get("layer", {})) & set(used.get("tag_prefix", {})))
    out["_direction_conflicts"] = KNOWN_DIRECTION_CONFLICTS
    out["_verified_consistent"] = VERIFIED_CONSISTENT
    out["_doc_code_drift"] = DOC_CODE_DRIFT
    out["_new_type_touchpoints"] = NEW_TYPE_TOUCHPOINTS
    return out


# ---------------------------- 断言集 ----------------------------

# 生效条件：四参齐备时返回 {"id": cid, "level": level, "ok": bool(ok), "detail": detail}，ok 经 bool() 归一为布尔；
def _ck(cid: str, level: str, ok: bool, detail: str) -> dict:
    return {"id": cid, "level": level, "ok": bool(ok), "detail": detail}


# 生效条件：调用 check(root, check_paths, baseline, strict) 时，root 原样传入 load_index 得 nodes，check_paths 原样传入 _path_metrics 并在 index.path.present 检查消息中当其为假时追加“（--no-path-check 未查盘）”，baseline 为真时追加 _regression 基线不劣化检查、为假（None 或空 dict）时跳过，n=len(nodes) 小于 THRESHOLDS["min_nodes"] 时 small 为真且使 _ratio 各项及 reach.ratio、stratum.mixed_ratio 在 val 为 None 或 small 为真时记 BLINDSPOT、否则记 WARN，最终 verdict 为 FAIL（存在 level="FAIL" 且 ok 为假）、否则 WARN（存在 level="WARN" 且 ok 为假，或 strict 为真且存在 level="BLINDSPOT"）、否则 PASS，返回含 REPORT_VERSION、t、elapsed_s、root 绝对路径、verdict、nodes、checks、counts、coverage、dup、edges、paths、gate、reach、unanalyzed、g1、protocol（=protocol.audit() 静态对账，恒追加四条 FAIL 级断言：op.declared 无未登记分支 / verb.implemented live 动词均有实现分支 / verb.reserved_clean 预留动词未被静默实现 / shape.declared 形状声明完备）、thresholds 的 dict；
def check(root: str, *, check_paths: bool = True,
          baseline: dict = None, strict: bool = False) -> dict:
    """跑一遍全部断言，返回报告 dict（零写入：不修任何数据、不落任何文件）。"""
    t0 = time.time()
    nodes = load_index(root)
    n = len(nodes)
    small = n < THRESHOLDS["min_nodes"]
    cov = _coverage_metrics(nodes)
    edges = _edge_metrics(nodes)
    paths = _path_metrics(root, nodes, check_paths)
    gate = _gate_metrics(root)
    reach = _reach_metrics(root, nodes)
    un = unanalyzed(nodes)
    g1 = _g1_audit(nodes, edges)
    dup = _dup_metrics(nodes)
    checks = []
    T = THRESHOLDS

    # ---- 不变量（fail-closed）----
    for space, use_key in (("layer", "layer"), ("verification_basis", "verification_basis"),
                           ("derived_relation", "derived_relation"),
                           ("lifecycle_state", "lifecycle_state")):
        spec = g1[space]
        undecl = spec["undeclared_used"]
        checks.append(_ck(f"enum.{space}.closed", "FAIL", not undecl,
                          f"声明源={spec['source']}；未声明已用={undecl or '无'}"))
    checks.append(_ck("edge.rel.declared", "WARN",
                      not g1["edge_type"]["undeclared_used"],
                      f"未声明边类型={g1['edge_type']['undeclared_used'] or '无'}"
                      "（读侧退化为 chain.DEFAULT_EDGE_WEIGHT=0.50，不炸但权重失真）"))
    checks.append(_ck("edge.key.canonical", "WARN", edges["non_canonical"] == 0,
                      f"非规范键边 {edges['non_canonical']}/{edges['total']}"
                      f"（写侧规范={CANONICAL_EDGE_KEYS}；md_cg 读侧兼容 type，"
                      "非 md_cg 读侧不兼容——存量债，判据=不劣化）"))
    checks.append(_ck("edge.target.resolvable", "FAIL", edges["dangling"] == 0,
                      f"悬空边 {edges['dangling']}/{edges['total']}（图断裂）"))
    checks.append(_ck("index.path.present", "FAIL", paths["missing"] == 0,
                      f"path 缺失/文件不存在 {paths['missing']}"
                      + ("" if check_paths else "（--no-path-check 未查盘）")))
    checks.append(_ck("index.layer.dir.match", "FAIL", paths["layer_mismatch"] == 0,
                      f"层-目录不一致 {paths['layer_mismatch']}（9-15 基线=0）"))
    top_dup = dup["largest"][0] if dup["largest"] else 0
    checks.append(_ck("dup.content.no_blowup", "FAIL", top_dup <= DUP_GROUP_MAX,
                      f"内容指纹重复组 {dup['groups']} / 涉及节点 {dup['nodes']}"
                      f" / 最大组 {dup['largest'][:3]}（最大组上限 {DUP_GROUP_MAX}）"))

    # ---- 健康指标（只告警）----
# 生效条件：val 为 None 或片段外闭包布尔 small 为真（small、n、T 均未在本片段定义）时追加 level="BLINDSPOT" 项；否则追加 level="WARN"、ok=(val>=low) 的项；两分支均无返回值；
    def _ratio(cid, val, low, name):
        if small or val is None:
            checks.append(_ck(cid, "BLINDSPOT", True,
                              f"{name} 不可判（样本 {n} < {T['min_nodes']} / 数据源缺失）"))
            return
        checks.append(_ck(cid, "WARN", val >= low, f"{name}={val * 100:.1f}%（下限 {low:.0%}）"))

    mr = None if small else cov["mixed_ratio"]
    checks.append(_ck("stratum.mixed_ratio",
                      "BLINDSPOT" if mr is None else "WARN",
                      mr is None or mr <= T["stratum_ratio_max"],
                      "混层比（knowledge 中 doc∪code 标签）=N/A（样本不足）" if mr is None else
                      f"混层比（knowledge 中 doc∪code 标签）={mr * 100:.1f}%"
                      f"（上限 {T['stratum_ratio_max']:.0%}，治理靶 {T['stratum_target']:.0%}）"))
    _ratio("stratum.role_coverage", cov["role_ratio_kn"], T["role_coverage_min"],
           "role 覆盖率[knowledge]")
    _ratio("stratum.evidence_coverage", cov["evidence_ratio_kn"],
           T["evidence_coverage_min"], "evidence 覆盖率[knowledge]")
    _ratio("analysis.coverage", 1 - un["ratio"], T["analysis_coverage_min"],
           f"分析覆盖率（非 unanalyzed；unanalyzed={un['count']}）")
    _ratio("reach.ratio", None if small else reach["ratio"], T["reach_ratio_min"], "触达率")
    checks.append(_ck("gate.sample", "WARN",
                      gate["decisions_total"] >= T["gate_sample_min"],
                      f"闸门裁决样本 {gate['decisions_total']} 条 {gate['decisions']}"
                      f"（下限 {T['gate_sample_min']}）"))

    # ---- 记忆动词协议 v1 静态对账（声明 ↔ MCP 面实现，纯源码事实、不连库）----
    # 与 G1 的分工：G1 对账**数据值域**，这里对账**动词面**——两者都是
    # 「声明了没做 / 做了没说」的前置红灯，属结构性不变量（FAIL 级，fail-closed）。
    from . import protocol as _proto
    pa = _proto.audit()
    checks.append(_ck("protocol.op.extension_surface", "WARN", True,
                      f"协议 v{pa['protocol_version']} 冻结面={pa['declared']}"
                      f"（live {len(pa['live'])} / reserved {len(pa['reserved'])}）；"
                      f"MCP 面另有 {len(pa['extension_ops'])} 个扩展 op 不属协议面"
                      f"（文档一致性由 cogmap 门禁承担）"))
    checks.append(_ck("protocol.verb.implemented", "FAIL",
                      not pa["missing_impl"],
                      f"声明为 live 的动词 {pa['live']} 均有实现分支"
                      if not pa["missing_impl"] else
                      f"声明为 live 却无实现分支：{pa['missing_impl']}"))
    checks.append(_ck("protocol.verb.reserved_clean", "FAIL",
                      not pa["reserved_leaked"],
                      f"reserved 动词 {pa['reserved']} 未出现实现分支"
                      if not pa["reserved_leaked"] else
                      f"reserved 动词被静默实现（须先改 status=live）："
                      f"{pa['reserved_leaked']}"))
    checks.append(_ck("protocol.shape.declared", "FAIL",
                      not pa["shape_errors"],
                      f"{len(pa['declared'])} 个动词形状声明完备"
                      if not pa["shape_errors"] else
                      f"形状声明不完整：{pa['shape_errors']}"))

    # ---- 基线不劣化（有 baseline 时才可判）----
    if baseline:
        checks += _regression({"mixed_ratio": cov["mixed_ratio"],
                               "non_canonical": edges["non_canonical"],
                               "dangling": edges["dangling"],
                               "dup_groups": dup["groups"],
                               "unanalyzed": un["count"]}, baseline)

    fails = [c for c in checks if c["level"] == "FAIL" and not c["ok"]]
    warns = [c for c in checks if c["level"] == "WARN" and not c["ok"]]
    blind = [c for c in checks if c["level"] == "BLINDSPOT"]
    v = "FAIL" if fails else ("WARN" if (warns or (strict and blind)) else "PASS")
    return {"report_version": REPORT_VERSION, "t": t0, "elapsed_s": round(time.time() - t0, 2),
            "root": os.path.abspath(root), "verdict": v,
            "nodes": n, "checks": checks,
            "counts": {"fail": len(fails), "warn": len(warns), "blindspot": len(blind),
                       "total": len(checks)},
            "coverage": cov, "dup": dup, "edges": edges, "paths": paths,
            "gate": gate, "reach": reach, "unanalyzed": un, "g1": g1,
            "protocol": pa, "thresholds": T}


# 生效条件：对 cur 各键，baseline（或其 metrics）缺失、该键在基线为 None 或 cur 值为 None 时跳过；否则以 val > b+1e-9 判劣化，产出 level 恒为 "FAIL"、ok=not worse 的检查项；
def _regression(cur: dict, baseline: dict) -> list:
    """与基线比对：单调量只准不变或改善（重复度/悬空/非规范键/混层/unanalyzed）。

    只收**单调有害量**（越大越坏）；触达率等随运行时间自然增长的量不进比对，
    否则日志轮转即误报。
    """
    base = (baseline or {}).get("metrics") or {}
    out = []
    for key, val in cur.items():
        b = base.get(key)
        if b is None or val is None:
            continue
        worse = val > b + 1e-9
        out.append(_ck(f"baseline.{key}", "FAIL", not worse,
                       f"现值 {val:.4f} vs 基线 {b:.4f}"
                       + ("（劣化）" if worse else "（未劣化）")))
    return out


# 生效条件：rep 含 coverage/edges/dup/unanalyzed/gate/reach 子字典与 nodes 键时（全部按下标取值，缺键即抛 KeyError）返回扁平指标映射；
def metrics_of(rep: dict) -> dict:
    """抽成可比对的扁平指标（--baseline 的写入面）。"""
    return {"mixed_ratio": rep["coverage"]["mixed_ratio"],
            "non_canonical": rep["edges"]["non_canonical"],
            "dangling": rep["edges"]["dangling"],
            "dup_groups": rep["dup"]["groups"],
            "unanalyzed": rep["unanalyzed"]["count"],
            "nodes": rep["nodes"],
            "role_ratio": rep["coverage"]["role_ratio"],
            "basis_ratio": rep["coverage"]["basis_ratio"],
            "evidence_ratio": rep["coverage"]["evidence_ratio"],
            "role_ratio_kn": rep["coverage"]["role_ratio_kn"],
            "evidence_ratio_kn": rep["coverage"]["evidence_ratio_kn"],
            "reach_ratio": rep["reach"]["ratio"],
            "gate_decisions": rep["gate"]["decisions_total"]}


# ---------------------------- 报告 ----------------------------

# 生效条件：rep 各键齐备（按下标取值，任一键缺失抛 KeyError）时拼接为多行文本，reach.ratio 为 None 时渲染 "N/A"，g1 中以 "_" 开头的键在遍历中被跳过；
def render(rep: dict) -> str:
    L = []
    a = L.append
    a(f"== conformance v{rep['report_version']} · {rep['root']}")
    a(f"   verdict: {rep['verdict']}   nodes={rep['nodes']}   "
      f"checks={rep['counts']['total']} (fail {rep['counts']['fail']} / "
      f"warn {rep['counts']['warn']} / blindspot {rep['counts']['blindspot']})")
    a("\n-- 断言集（FAIL=fail-closed 不变量 / WARN=健康指标只告警）--")
    for c in rep["checks"]:
        mark = {"FAIL": "!!", "WARN": " ?", "BLINDSPOT": " ~"}.get(c["level"], " .")
        ok = "ok " if c["ok"] else "NO "
        a(f"  [{mark}] {ok}{c['id']}: {c['detail']}")
    c = rep["coverage"]
    a(f"\n-- 口径复核（9-15 基线）--")
    a(f"  nodes={c['nodes']} knowledge={c['knowledge']} 混层={c['mixed_layer']}"
      f" ({c['mixed_ratio'] * 100:.1f}%)")
    a(f"  dir_mismatch={rep['paths']['layer_mismatch']} path_missing={rep['paths']['missing']}")
    a(f"  覆盖率[knowledge 层·判据口径] role={c['role_ratio_kn'] * 100:.3f}%"
      f" basis={c['basis_ratio_kn'] * 100:.1f}% evidence={c['evidence_ratio_kn'] * 100:.3f}%")
    a(f"  覆盖率为对照[全库口径] role={c['role_ratio'] * 100:.2f}%"
      f" basis={c['basis_ratio'] * 100:.1f}% evidence={c['evidence_ratio'] * 100:.2f}%"
      f" state={c['state_ratio'] * 100:.1f}%")
    a(f"  重复 content_hash 组={rep['dup']['groups']} 节点={rep['dup']['nodes']}"
      f" 最大组={rep['dup']['largest'][:3]}")
    a(f"  边 total={rep['edges']['total']} 非规范键={rep['edges']['non_canonical']}"
      f" 悬空={rep['edges']['dangling']} 类型={rep['edges']['types']}")
    r = rep["reach"]
    a(f"  触达 distinct={r['distinct']} ratio="
      + ("N/A" if r['ratio'] is None else f"{r['ratio'] * 100:.1f}%") + f" log_lines={r['lines']}")
    a(f"  闸门 decisions={rep['gate']['decisions_total']} {rep['gate']['decisions']}"
      f" inbox_pending={rep['gate']['inbox_pending']}")
    a(f"  审计 op（尾窗 {rep['gate']['audit_tail_lines']}"
      f"/{rep['gate']['audit_tail_window']} 行）={rep['gate']['audit_ops']}")
    a(f"  G3 unanalyzed 派生={rep['unanalyzed']['count']}"
      f" ({rep['unanalyzed']['ratio'] * 100:.1f}%)")
    pr = rep.get("protocol") or {}
    if pr:
        a("\n-- 记忆动词协议 v1 静态对账 --")
        a(f"  {pr['doc']}  frozen={pr['frozen']}  ok={pr['ok']}")
        a(f"  声明={pr['declared']}")
        a(f"  live={pr['live']}  reserved={pr['reserved']}（未实现即如实登记，不冒充）")
        a(f"  MCP 面 op 分支={len(pr['actual'])} 个，其中扩展能力面"
          f"（不属协议 v1）{len(pr['extension_ops'])} 个")
        if pr["errors"]:
            for e in pr["errors"]:
                a(f"  !! {e}")
    a("\n-- G1 类型空间正交性 --")
    for name, spec in rep["g1"].items():
        if name.startswith("_"):
            continue
        a(f"  [{name}] 源={spec['source']} 封闭={spec['closed']}")
        a(f"      实测={spec['used']}")
        if spec["undeclared_used"]:
            a(f"      ★未声明已用={spec['undeclared_used']}")
        if spec["declared_unused"]:
            a(f"      声明未用={spec['declared_unused']}")
    a(f"  跨空间重叠={rep['g1']['_cross_space_overlap'] or '无'}")
    a(f"  方向口径分歧={[d['literal'] for d in rep['g1']['_direction_conflicts']]}")
    a(f"  已核对无分歧={[d['literal'] for d in rep['g1']['_verified_consistent']]}")
    a(f"  文档滞后于代码={[d['where'] for d in rep['g1']['_doc_code_drift']]}")
    a(f"  新增类型触点={rep['g1']['_new_type_touchpoints']}")
    return "\n".join(L)


# 生效条件：传入对象可写属性时执行赋值 sustain_module.conformance_summary = report_summary，无返回值（None）；
def register_sustain(sustain_module) -> None:               # pragma: no cover
    """挂点说明（供 sustain 侧最小侵入调用）。

    周期巡检**不加新 tick**：`_tick_tidy()` 已是「contextual 存量治理」的
    读侧巡检，本断言集复用同一节奏（tidy_interval），由 `report_summary(cg)`
    只取结论不落盘——避免为只读检查新增后台周期与 env 开关。
    """
    sustain_module.conformance_summary = report_summary


# 生效条件：root 依次取 cg_or_root.root 属性、cg_or_root 本身、_default_root()（前者为假值即回落，故 0/空串会继续回落）；check 抛异常时返回 ok=False、verdict="BLINDSPOT"、error，否则返回 ok=(verdict!="FAIL") 与 fail/warn/blindspot/failed_ids/t；
def report_summary(cg_or_root) -> dict:
    """给常驻循环用的**轻量**结论（不渲染全文、不写盘）：verdict + 计数。"""
    root = getattr(cg_or_root, "root", None) or cg_or_root or _default_root()
    try:
        rep = check(root, check_paths=False)
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "verdict": "BLINDSPOT", "error": f"{type(e).__name__}: {e}"}
    return {"ok": rep["verdict"] != "FAIL", "verdict": rep["verdict"],
            "fail": rep["counts"]["fail"], "warn": rep["counts"]["warn"],
            "blindspot": rep["counts"]["blindspot"],
            "failed_ids": [c["id"] for c in rep["checks"]
                           if c["level"] == "FAIL" and not c["ok"]],
            "t": rep["t"]}


# 生效条件：argv 为 None 时 argparse 从 sys.argv 取值，--root 缺失或为假值回落 _default_root()；check 抛 OSError/ValueError（如索引不可读）时打印 BLINDSPOT 并返回 2，否则按 --write-baseline/--json 写盘后返回 0（verdict≠"FAIL"）或 1（"FAIL"）；
def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m md_cg.conformance",
                                description="数据健康不变量断言集（只读，零写入）")
    p.add_argument("--root", default=None,
                   help="认知图根（默认 MDCG_ROOT > paths.json > 用户级状态根 data/mdcg）")
    p.add_argument("--json", dest="json_out", default=None)
    p.add_argument("--baseline", default=None, help="基线报告 json（比对不劣化）")
    p.add_argument("--write-baseline", default=None, help="把本次指标写成新基线")
    p.add_argument("--no-path-check", action="store_true", help="不查盘上文件是否存在")
    p.add_argument("--strict", action="store_true", help="BLINDSPOT 也视为非 PASS")
    a = p.parse_args(argv)

    root = a.root or _default_root()
    baseline = None
    if a.baseline:
        with open(a.baseline, encoding="utf-8") as f:
            baseline = json.load(f)
    try:
        rep = check(root, check_paths=not a.no_path_check,
                    baseline=baseline, strict=a.strict)
    except (OSError, ValueError) as e:
        # 数据源不可读 = BLINDSPOT（如实上报），绝不打印「通过」
        print(f"== conformance v{REPORT_VERSION} · {os.path.abspath(root)}")
        print(f"   verdict: BLINDSPOT —— 索引不可读: {type(e).__name__}: {e}")
        print(f"   缺失维度: 数据源（{INDEX_FILE}）；修复后重跑，勿以本结果为「通过」。")
        return 2
    print(render(rep))
    if a.write_baseline:
        with open(a.write_baseline, "w", encoding="utf-8") as f:
            json.dump({"report_version": REPORT_VERSION, "t": rep["t"],
                       "root": rep["root"], "metrics": metrics_of(rep)},
                      f, ensure_ascii=False, indent=2)
        print(f"\n  基线已写入: {a.write_baseline}")
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2, default=str)
        print(f"  报告已写入: {a.json_out}")
    return 0 if rep["verdict"] != "FAIL" else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())