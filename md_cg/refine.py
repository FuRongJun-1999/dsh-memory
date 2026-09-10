# -*- coding: utf-8 -*-
"""G6：node_ 结构提炼 · 小样本抽检工单与扩批闸门（只读预演，纯标准库）。

缺口（G6）：`node_*`（P37 双子管线派生记忆）自带 `ccg_exempt=true`，正文只有
「功能名 / 生效条件」两行，`子功能 / 执行 / 不适用条件` 均未声明（实测 1324 条）。
若直接对全量跑归纳提炼（`consolidate.induce`），一旦**提炼口径**失准，就会把
模板化词面当成「共性条件」固化成概念节点，污染单一真相源。

裁定单条件 A：**先抽 20 条做提炼预演，人工核对提炼口径，绝不盲跑全量**。

本模块只做三件事（零 LLM、零第三方依赖，且**不改写任何节点**）：
  1. `plan`    —— 确定性分层抽样出 20 条工单（原文摘录 / 字段缺口 / 口径声明）；
  2. `preview` —— 在抽检样本上跑与 `consolidate.induce` **同源的**聚类口径，
                  输出候选概念 + 每条共性条件的可追溯来源 + **样本内文档频率**
                  （df 高 = 模板/通用水位线，不得当作区分性共性）；
  3. `apply`/`gate` —— 把抽检批次与人工裁决落 `_refine.jsonl` 留痕，并据此
                  计算「是否允许扩大批次」。

纪律与诚实边界：
  · 提炼执行仍由 `consolidate.induce` 承担（产出恒 `inferred`）；本模块不实现
    第二套提炼器，避免口径分叉——`preview` 复用同一套 `_jaccard/_common_terms`。
  · 抽检若取「20 条节点」，在库内实测**可能产不出候选**（`min_cluster=3` 时
    20 条随机样本 0 簇）；此时如实报 `candidates=0` 并**拒绝放行扩批**，
    由 `sample_adequacy` 提示「按候选为抽检单位」或上调样本量。
  · 人工裁决必须由库外人类给出；本模块只做算术与留痕，**不代替裁决**。
  · 共性条件的去模板判据只用**词面统计**，不做语义猜测（宁可漏判，不可误判）。
"""
from __future__ import annotations

import hashlib
import math
import os
import time

from . import consolidate, nodefile
from .fsutil import append_jsonl, read_jsonl
from .mdcos import MdCGOS

REFINE_LOG = "_refine.jsonl"

#: 抽检对象 id 前缀（P37 派生记忆）
PREFIX_DEFAULT = "node_"
#: 裁定单条件 A 规定的抽检条数
SAMPLE_N = 20
#: 抽样种子：同 seed ⇒ 同样本（可复算、可复核）
SAMPLE_SEED = "g6-sample-v1"

MIN_JACCARD = consolidate.INDUCE_MIN_JACCARD
MIN_CLUSTER = consolidate.INDUCE_MIN_CLUSTER
MAX_TERMS = consolidate.INDUCE_MAX_TERMS

#: 共性条件在**抽检样本**内的文档频率 ≥ 该值 → 判为模板/通用水位线，不具区分性
GENERIC_DF = 0.80
#: 工单正文摘录上限（超出即标 truncated；完整原文请 `cg read`）
EXCERPT_MAX = 4000
#: 扩批通过率闸门：人工核对「忠实」比例下限
GATE_MIN_PASS_RATE = 0.90

#: 样本量校准：目标产出候选数 / 有界爬坡上限（样本量非唯一杠杆，故设上限）
CALIBRATE_TARGET = 20
CALIBRATE_CAP = 200

#: 人工核对裁决键（与工单 review_items 一一对应）
VERDICT_KEYS = ("faithful", "added_info")

#: 提炼口径声明——人工核对的就是这份口径，不是某一次的输出
SPEC = {
    "method": "consolidate.induce 同源口径：bigram-jaccard 贪心聚类（确定性、零 LLM）",
    "min_cluster": MIN_CLUSTER,
    "min_jaccard": MIN_JACCARD,
    "fields": ["功能名", "生效条件", "子功能", "执行", "不适用条件"],
    "evidence": "inferred（未经验证，不得直接当事实使用）",
    "common_condition_source": "成员 positive_body 的词面统计（不做语义推断）",
    "review_items": [
        {"key": "faithful",
         "ask": "每条共性条件是否能在**全部**成员原文中原样找到"
                "（grounding_gap 为空即无缺口）"},
        {"key": "added_info",
         "ask": "概念是否引入了成员原文之外的词（外部知识/编造）——命中即整批否决"},
        {"key": "discriminating",
         "ask": "共性条件是否为区分性特征；df≥%.2f 的模板词不得充当共性"
                % GENERIC_DF},
        {"key": "member_consistency",
         "ask": "成员是否真属同一范畴（无强行拼团）"},
    ],
    "gate": {"min_pass_rate": GATE_MIN_PASS_RATE,
             "require_review_all": True,
             "fail_on_added_info": True},
    "honest_limits": [
        "本模块不执行提炼写入；扩批需 `consolidate.induce` 另开批次执行并留痕",
        "人工裁决由库外人类给出，本模块不代替裁决",
    ],
}

# ---- 通用工具 -------------------------------------------------------------

def _as_cg(x):
    return MdCGOS(x) if isinstance(x, str) else x


def _log_path(cg) -> str:
    root = cg.root if hasattr(cg, "root") else str(cg)
    return os.path.join(root, REFINE_LOG)


def _read_log(cg) -> list:
    return [r for r in (read_jsonl(_log_path(cg)) or [])
            if r.get("action") == "refine"]


def _entry(cg, nid):
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    return nodes.get(nid) or {}


def _family(cg, nid):
    """家族 = 节点所在 `cond_*` 目录名（无则 `(root)`）。"""
    p = str(_entry(cg, nid).get("path") or "").replace("\\", "/")
    d = os.path.basename(os.path.dirname(p))
    return d or "(root)"


def _sha(*parts) -> str:
    h = hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8"))
    return h.hexdigest()


def _pool(cg, prefix) -> tuple:
    """抽检池：id 以 prefix 开头、非受保护节点（与 induce 的池口径一致）。"""
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    ids, protected = [], 0
    for nid, e in nodes.items():
        if not str(nid).startswith(prefix):
            continue
        if (e or {}).get("protected"):
            protected += 1
            continue
        ids.append(nid)
    ids.sort()
    return ids, protected


def sample_ids(cg, n=None, seed=None, prefix=None) -> tuple:
    """确定性分层抽样（家族=层，家族内按 sha1(seed|id) 排序）。

    分层 + 最大余数分配：主家族按规模拿到多数名额，稀有家族亦保留席位（n 足够时）。
    返回 `(ids, meta)`；同 `seed` 必得同样本——抽检可复核、可复算。
    """
    n = SAMPLE_N if n is None else int(n)
    seed = seed or SAMPLE_SEED
    prefix = prefix or PREFIX_DEFAULT
    pool, protected = _pool(cg, prefix)
    fam = {}
    for nid in pool:
        fam.setdefault(_family(cg, nid), []).append(nid)
    meta = {"prefix": prefix, "seed": seed, "requested": int(n),
            "pool": len(pool), "skipped_protected": protected,
            "families": len(fam), "sampled": 0, "strata": {}}
    if not pool or n <= 0:
        return [], meta
    n = min(int(n), len(pool))
    names = sorted(fam)
    raw = {f: n * len(fam[f]) / float(len(pool)) for f in names}
    alloc = {f: int(math.floor(raw[f])) for f in names}
    rest = n - sum(alloc.values())
    for f in sorted(names, key=lambda x: (-(raw[x] - alloc[x]), x))[:rest]:
        alloc[f] += 1
    picked, strata = [], {}
    for f in names:
        k = int(alloc[f])
        if k <= 0:
            continue
        rank = sorted(fam[f], key=lambda x: _sha(seed, x))
        take = rank[:k]
        picked.extend(take)
        strata[f] = {"pool": len(fam[f]), "picked": len(take)}
    picked.sort()
    meta["sampled"] = len(picked)
    meta["strata"] = strata
    return picked, meta


def _item(cg, nid) -> dict:
    node = cg.get(nid) or {}
    fm = node.get("frontmatter") or {}
    content = node.get("content") or ""
    comp = nodefile.ccg_completeness(content)
    e = _entry(cg, nid)
    truncated = len(content) > EXCERPT_MAX
    return {
        "id": nid, "family": _family(cg, nid), "layer": e.get("layer"),
        "tags": list(e.get("tags") or []), "importance": e.get("importance"),
        "edges": len(fm.get("edges") or []),
        "ccg_exempt": bool(fm.get("ccg_exempt")),
        "ccg_present": comp["present"],
        "ccg_missing": [m for m in nodefile.CCG_MARKS if m not in comp["present"]],
        "comment": fm.get("comment"),
        "body": content[:EXCERPT_MAX], "body_len": len(content),
        "body_truncated": truncated,
        "source_sha": _sha(content)[:16],
    }


# ---- 预演：与 induce 同源的聚类口径 ---------------------------------------

def _cluster(cg, pool, min_jaccard, min_cluster) -> tuple:
    """贪心聚类（与 `consolidate.induce_memories` 同源）。返回 (cache, keys, groups)。"""
    from . import subgraph
    cache = {}
    for nid in pool:
        got = subgraph._node_terms_and_grams(cg, nid)
        if got and got.get("grams"):
            cache[nid] = got
    keys = sorted(cache)
    assigned, groups = set(), []
    for i, a in enumerate(keys):
        if a in assigned:
            continue
        ga = cache[a]["grams"]
        grp = [b for b in keys[i + 1:]
               if b not in assigned
               and consolidate._jaccard(ga, cache[b]["grams"]) >= float(min_jaccard)]
        if len(grp) + 1 < int(min_cluster):
            continue
        members = [a] + grp
        assigned.update(members)
        groups.append(members)
    return cache, keys, groups


def _term_df(cache, keys, terms) -> dict:
    """词面在抽检样本内的文档频率（不含语义推断）。"""
    df = {t: 0 for t in terms}
    if not terms:
        return df
    for k in keys:
        pos = set(cache[k]["pos"])
        for t in terms:
            if t in pos:
                df[t] += 1
    return df


def preview(x, ids=None, n=None, seed=None, prefix=None,
            min_jaccard=None, min_cluster=None, require_conditions=True) -> dict:
    """提炼预演（只读）：抽样 → 同源聚类 → 共性条件 + 来源 + 泛化度标记。"""
    cg = _as_cg(x)
    min_j = MIN_JACCARD if min_jaccard is None else float(min_jaccard)
    min_c = MIN_CLUSTER if min_cluster is None else int(min_cluster)
    if ids:
        pool = sorted({str(i) for i in ids})
        meta = {"prefix": prefix or PREFIX_DEFAULT, "seed": seed or SAMPLE_SEED,
                "requested": len(pool), "pool": len(pool),
                "skipped_protected": 0, "families": 0, "sampled": len(pool),
                "strata": {}, "explicit_ids": True}
    else:
        pool, meta = sample_ids(cg, n=n, seed=seed, prefix=prefix)

    cache, keys, groups = _cluster(cg, pool, min_j, min_c)
    base = max(1, len(keys))
    cands, skipped_no_cond, all_terms = [], 0, set()
    for members in groups:
        common = consolidate._common_terms([cache[m]["pos"] for m in members])
        if require_conditions and not common:
            skipped_no_cond += 1
            continue
        neg = consolidate._union_terms([cache[m]["neg"] for m in members])
        all_terms.update(common)
        cands.append({"concept_id": consolidate._concept_id(members),
                      "members": members, "size": len(members),
                      "common_conditions": common,
                      "non_applicable": neg})

    df = _term_df(cache, keys, sorted(all_terms))
    for c in cands:
        members = c["members"]
        src = {t: [m for m in members if t in cache[m]["pos"]]
               for t in c["common_conditions"]}
        gap = [t for t, ms in src.items() if len(ms) < len(members)]
        generic = [{"term": t, "df": df.get(t, 0),
                    "ratio": round(df.get(t, 0) / float(base), 4)}
                   for t in c["common_conditions"]
                   if df.get(t, 0) / float(base) >= GENERIC_DF]
        c.update({
            "condition_sources": src,
            "grounding_gap": gap,
            "generic_conditions": generic,
            "discriminating": [t for t in c["common_conditions"]
                               if df.get(t, 0) / float(base) < GENERIC_DF],
            "reason": ("%d 条记忆内容相近且共享条件「%s」→ 归纳为概念"
                       % (len(members),
                          "、".join(c["common_conditions"][:MAX_TERMS]) or "无")),
        })
    generic_only = sum(1 for c in cands if not c["discriminating"])
    adequacy = "ok" if cands else "insufficient"
    return {
        "root": cg.root, "dry_run": True, "readonly": True,
        "action": "refine_preview", "op": "maintain",
        "prefix": meta["prefix"], "seed": meta["seed"],
        "requested": meta["requested"], "pool": meta["pool"],
        "skipped_protected": meta["skipped_protected"],
        "families": meta["families"], "strata": meta["strata"],
        "sampled": meta["sampled"], "sample": pool,
        "indexed": len(keys), "min_cluster": min_c, "min_jaccard": min_j,
        "require_conditions": bool(require_conditions),
        "clusters": len(cands), "candidates": cands,
        "skipped_no_condition": skipped_no_cond,
        "candidates_generic_only": generic_only,
        "df_basis": "sampled", "generic_df_threshold": GENERIC_DF,
        "sample_adequacy": adequacy,
        "note": ("预演：未写盘、未改任何节点；候选供人工核对提炼口径"
                 if cands else
                 "抽检样本不足以产出候选（样本量或抽检单位需校准），不得据此扩批"),
    }


# ---- 工单 ---------------------------------------------------------------

def plan(x, ids=None, n=None, seed=None, prefix=None,
         min_jaccard=None, min_cluster=None) -> dict:
    """抽检工单（只读）：确定性样本 + 原文摘录 + 字段缺口 + 口径声明 + 预演。"""
    cg = _as_cg(x)
    prefix = prefix or PREFIX_DEFAULT
    seed = seed or SAMPLE_SEED
    if ids:
        sample = sorted({str(i) for i in ids})
        real_pool, skipped, families = len(sample), 0, 0
    else:
        sample, meta = sample_ids(cg, n=n, seed=seed, prefix=prefix)
        real_pool, skipped, families = (meta["pool"], meta["skipped_protected"],
                                        meta["families"])
    items = [_item(cg, nid) for nid in sample]
    pv = preview(cg, ids=sample, prefix=prefix,
                 min_jaccard=min_jaccard, min_cluster=min_cluster)
    strata = {}
    for it in items:
        k = it["family"]
        s = strata.setdefault(k, {"picked": 0, "missing_fields": {},
                                  "ccg_exempt": 0})
        s["picked"] += 1
        if it["ccg_exempt"]:
            s["ccg_exempt"] += 1
        for m in it["ccg_missing"]:
            s["missing_fields"][m] = s["missing_fields"].get(m, 0) + 1
    return {
        "root": cg.root, "dry_run": True, "readonly": True,
        "action": "refine", "op": "maintain",
        "prefix": prefix, "seed": seed,
        "requested": n if n is not None else (len(sample) if ids else SAMPLE_N),
        "pool": real_pool, "skipped_protected": skipped,
        "sampled": len(items), "families": families,
        "sample": sample, "sample_sha": _sha(*sample)[:16],
        "strata": strata, "items": items,
        "worklist": items, "spec": SPEC,
        "preview": {"clusters": pv["clusters"], "candidates": pv["candidates"],
                    "min_cluster": pv["min_cluster"],
                    "min_jaccard": pv["min_jaccard"],
                    "skipped_no_condition": pv["skipped_no_condition"],
                    "candidates_generic_only": pv["candidates_generic_only"],
                    "sample_adequacy": pv["sample_adequacy"],
                    "df_basis": pv["df_basis"],
                    "generic_df_threshold": pv["generic_df_threshold"]},
        "gate_rule": SPEC["gate"],
        "note": ("抽检工单（只读）：供人工核对提炼口径；核对通过前不得扩批。"
                 "行 `apply=true` 只落抽检留痕，不改任何节点。"),
    }


def calibrate(x, target=None, cap=None, n0=None, seed=None, prefix=None,
              min_jaccard=None, min_cluster=None) -> dict:
    """样本量校准（只读）：20 条起步有界爬坡，直到产出 `target` 个候选或触顶。

    目的是回答「20 条工单为什么交不出候选」，并给出**有界**的替代样本量；
    若爬坡到顶仍无候选、或候选共性条件全为高 df 模板词，则如实报
    `blocked` 并指出真正的瓶颈是**提炼口径**而非样本量——不得据此扩批。
    """
    cg = _as_cg(x)
    target = CALIBRATE_TARGET if target is None else int(target)
    cap = CALIBRATE_CAP if cap is None else int(cap)
    n = min(SAMPLE_N if n0 is None else int(n0), cap)
    steps, chosen, pool = [], None, None
    while True:
        pv = preview(cg, n=n, seed=seed, prefix=prefix,
                     min_jaccard=min_jaccard, min_cluster=min_cluster)
        pool = pv["pool"]
        step = {"n": n, "sampled": pv["sampled"], "clusters": pv["clusters"],
                "candidates_generic_only": pv["candidates_generic_only"],
                "discriminating_terms": sorted(
                    {t for c in pv["candidates"] for t in c["discriminating"]})[:12]}
        steps.append(step)
        if pv["clusters"] >= target:
            chosen = step
            break
        top = min(cap, pool or cap)
        if n >= top:
            break
        n = min(n * 2, top)
    blocked = chosen is None
    saw_clusters = any(s["clusters"] for s in steps)
    total_c = sum(s["clusters"] for s in steps)
    gen_only = sum(s["candidates_generic_only"] for s in steps)
    if not blocked:
        rec = ("抽检样本量校准为 n=%d（产出 %d 个候选）；仍须人工核对提炼口径，"
               "核对通过前不得扩批" % (chosen["n"], chosen["clusters"]))
    else:
        parts = ["爬坡至 cap=%d 仍只产出 %d 个候选（< target=%d），样本量不足以"
                 "直接支撑抽检" % (cap, steps[-1]["clusters"], target)]
        if saw_clusters:
            if gen_only >= total_c:
                parts.append("且已产出候选的共性条件**全部**为高 df 模板词（无区分性）")
            else:
                parts.append("且候选中 %d/%d 的共性条件全为高 df 模板词，"
                             "其余『区分性』项形如整行条件文本（含时间戳），"
                             "属归一化缺失导致的伪区分性" % (gen_only, total_c))
        parts.append("须先修正提炼口径（剔除模板词 + 归一化/裁剪整行文本）"
                     "或以「候选」为抽检单位重新校准；当前状态不得扩批")
        rec = "；".join(parts)
    return {"ok": True, "action": "refine_calibrate", "op": "maintain",
            "root": cg.root, "dry_run": True, "readonly": True,
            "target": target, "cap": cap, "pool": pool,
            "steps": steps, "chosen": chosen, "blocked": blocked,
            "sample_adequacy": "ok" if not blocked else "insufficient",
            "recommend": rec, "note": "只读校准：未写盘、未改任何节点。"}


# ---- 留痕与扩批闸门 ------------------------------------------------------

def _verdict_stats(verdicts, candidates) -> dict:
    ids = [c.get("concept_id") for c in candidates if c.get("concept_id")]
    seen, faithful, added = set(), 0, 0
    for v in verdicts or []:
        if not isinstance(v, dict):
            continue
        cid = v.get("concept_id")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        faithful += 1 if v.get("faithful") else 0
        added += 1 if v.get("added_info") else 0
    reviewed = len(seen)
    rate = (faithful / float(reviewed)) if reviewed else 0.0
    expand, reason = False, "no_candidates"
    if ids:
        if reviewed < len(ids):
            reason = "awaiting_human_review"
        elif added:
            reason = "added_info_detected"
        elif rate < GATE_MIN_PASS_RATE:
            reason = "faithful_rate_below_gate"
        else:
            reason = "ok"
            expand = True
    return {"candidates": len(ids), "reviewed": reviewed,
            "faithful": faithful, "added_info": added,
            "faithful_rate": round(rate, 4),
            "min_pass_rate": GATE_MIN_PASS_RATE,
            "expand_allowed": expand, "reason": reason}


def apply(x, batch=None, actor=None, verdicts=None, note=None,
          ids=None, n=None, seed=None, prefix=None,
          min_jaccard=None, min_cluster=None) -> dict:
    """落抽检批次 + 人工裁决到 `_refine.jsonl`。**不改写任何节点**。"""
    cg = _as_cg(x)
    p = plan(cg, ids=ids, n=n, seed=seed, prefix=prefix,
             min_jaccard=min_jaccard, min_cluster=min_cluster)
    batch = batch or time.strftime("%Y%m%d-%H%M%S")
    cands = p["preview"]["candidates"]
    stats = _verdict_stats(verdicts, cands)
    record = {
        "t": time.time(), "action": "refine", "batch": batch, "actor": actor,
        "prefix": p["prefix"], "seed": p["seed"], "requested": p["requested"],
        "pool": p["pool"], "sampled": p["sampled"],
        "sample": p["sample"], "sample_sha": p["sample_sha"],
        "sample_adequacy": p["preview"]["sample_adequacy"],
        "min_cluster": p["preview"].get("min_cluster"),
        "candidates": [{"concept_id": c["concept_id"], "members": c["members"],
                        "common_conditions": c["common_conditions"],
                        "grounding_gap": c["grounding_gap"],
                        "discriminating": c["discriminating"]}
                       for c in cands],
        "verdicts": list(verdicts or []), "gate": stats, "note": note,
    }
    append_jsonl(_log_path(cg), record)
    rep = {"ok": True, "action": "refine", "op": "maintain", "batch": batch,
           "root": cg.root, "sampled": record["sampled"],
           "candidates": stats["candidates"], "reviewed": stats["reviewed"],
           "gate": stats, "log": REFINE_LOG,
           "note": ("抽检留痕已落盘（未改任何节点）；"
                    + ("闸门放行扩批（仍需另开 induce 批次并留痕）"
                       if stats["expand_allowed"] else
                       "闸门未放行：" + stats["reason"]))}
    return rep


def gate(x, batch=None) -> dict:
    """扩批闸门：读留痕复算通过率（不写盘）。"""
    cg = _as_cg(x)
    recs = _read_log(cg)
    if batch:
        recs = [r for r in recs if r.get("batch") == batch]
    if not recs:
        return {"ok": True, "action": "refine_gate", "op": "maintain",
                "root": cg.root, "batch": batch, "batches": 0,
                "expand_allowed": False, "reason": "no_batch"}
    rec = recs[-1]
    stats = _verdict_stats(rec.get("verdicts"), rec.get("candidates") or [])
    return {"ok": True, "action": "refine_gate", "op": "maintain",
            "root": cg.root, "batch": rec.get("batch"),
            "batches": len({r.get("batch") for r in recs}),
            "sampled": rec.get("sampled"),
            "sample_adequacy": rec.get("sample_adequacy"),
            "gate": stats, "expand_allowed": stats["expand_allowed"],
            "reason": stats["reason"],
            "note": ("闸门放行：可另开 induce 批次扩大提炼规模并逐批留痕"
                     if stats["expand_allowed"] else
                     "闸门未放行，禁止扩大批次；不得盲跑全量。")}


def history(x, limit=100, batch=None) -> dict:
    cg = _as_cg(x)
    recs = _read_log(cg)
    if batch:
        recs = [r for r in recs if r.get("batch") == batch]
    total = len(recs)
    if limit is not None and limit >= 0:
        recs = recs[-int(limit):]
    return {"root": cg.root, "total": total, "returned": len(recs),
            "action": "refine", "records": recs}


# ---- CLI（真实库抽检/预演用；MCP 侧走 maintain action） -------------------

def _main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description="G6 提炼抽检（默认只预演，不写盘）")
    ap.add_argument("root", help="认知图库根")
    ap.add_argument("--n", type=int, default=SAMPLE_N, help="抽检条数（默认 20）")
    ap.add_argument("--seed", default=SAMPLE_SEED, help="抽样种子（同 seed 同样本）")
    ap.add_argument("--prefix", default=PREFIX_DEFAULT, help="id 前缀（默认 node_）")
    ap.add_argument("--min-jaccard", type=float, default=None)
    ap.add_argument("--min-cluster", type=int, default=None)
    ap.add_argument("--preview", action="store_true", help="只出预演（不出工单正文）")
    ap.add_argument("--calibrate", action="store_true",
                    help="只做样本量校准（20 条起步有界爬坡）")
    ap.add_argument("--report", default=None, help="把汇总 JSON 另存一份")
    a = ap.parse_args(argv)
    if a.calibrate:
        rep = calibrate(a.root, seed=a.seed, prefix=a.prefix,
                        min_jaccard=a.min_jaccard, min_cluster=a.min_cluster)
        if a.report:
            with open(a.report, "w", encoding="utf-8") as f:
                json.dump(rep, f, ensure_ascii=False, indent=2)
        print(json.dumps({k: rep[k] for k in
                          ("target", "cap", "pool", "blocked",
                           "sample_adequacy", "recommend")},
                         ensure_ascii=False, indent=2))
        for s in rep["steps"]:
            print("  - n=%4d clusters=%2d generic_only=%2d discriminating=%s"
                  % (s["n"], s["clusters"], s["candidates_generic_only"],
                     s["discriminating_terms"][:6]))
        return 0
    fn = preview if a.preview else plan
    rep = fn(a.root, n=a.n, seed=a.seed, prefix=a.prefix,
             min_jaccard=a.min_jaccard, min_cluster=a.min_cluster)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
    pv = rep.get("preview") if "preview" in rep else rep
    thin = {k: rep.get(k) for k in ("action", "prefix", "seed", "requested",
                                    "pool", "sampled", "families")}
    thin.update({k: pv.get(k) for k in ("clusters", "sample_adequacy",
                                        "candidates_generic_only")})
    print(json.dumps(thin, ensure_ascii=False, indent=2))
    for c in (pv.get("candidates") or []):
        print("  - %s size=%d common=%s generic=%s gap=%s"
              % (c["concept_id"], c["size"], c["common_conditions"][:4],
                 [g["term"] for g in c.get("generic_conditions", [])],
                 c.get("grounding_gap")))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
