# -*- coding: utf-8 -*-
"""comment_gate · 代码符号「条件化注释」抽样闸门（计划四环之环二入口）。

**换对象不换机制**：复用 refine.py 的闸门范式（分层抽样 → 只读工单 → 人工裁决留痕 →
通过率放行），把处理对象从「node_ 前缀的记忆节点 CCG 字段缺口」换成
「code_ 前缀的代码符号注释缺口」。

候选判据（唯一、机械、不做语义猜测）：**代码节点且正文缺『生效条件』**。
依 Phase 0 契约，代码节点的生效条件只能来自源码人工声明——缺它即 BLINDSPOT
（缺证据），正是本闸门要治理的对象。落点按使用者裁决 q-0：写进源码、定义行紧邻的
井号注释（**两个窗口**，见 docs/mdcg/代码评审与条件化注释_契约_v0.1.md §三.2）。

本模块只做**候选池 / 工单 / 留痕 / 闸门**：不生成注释、不改任何节点。
生成与评审方式按 q-2（LLM 生成 + 人工抽检，复用 0.90 闸门）。

诚实边界（honest_limits 已随 SPEC 一并输出）：
· 分层抽样的**分配**沿用 refine.sample_ids 对 code_ 节点的口径（家族=大域），
  而非对候选池重新分配——故 sample_adequacy 会如实报出样本里的候选产出率；
  若产出率不足，应先扩大 n 或改用候选池重分配（已知待办，不在本片）。
"""
from __future__ import annotations

import json
import os
import time

from . import nodefile, refine

#: 放行阈值**唯一真源在 refine**（不在此处再定义一份，防口径漂移）
GATE_MIN_PASS_RATE = refine.GATE_MIN_PASS_RATE
SAMPLE_N = refine.SAMPLE_N
#: 本闸门自己的抽样种子（与 refine 的 g6-sample-v1 分离，样本可各自复算）
SAMPLE_SEED = "comment-gate-v1"
#: 代码节点 id 前缀（见 codeindex.node_id = code_ + sha1 前 12 位）
PREFIX = "code_"
LOG_NAME = "_comment_gate.jsonl"

#: 人工核对清单（与工单逐项对应；对照 refine.SPEC.review_items 的同构位置）
REVIEW_ITEMS = (
    "生效条件是否为**功能前置条件**（何种输入/状态下正确），而非索引元条件",
    "条件可否被机械复核（有输入/状态判据；不是「常用条件默认省略」）",
    "落点是否为源码定义行紧邻的井号注释（两窗口之一），且不覆盖既有实现说明",
    "公开仓合规：过第 14 条「内容政策 + 隐私」双清单（补写内容随源码公开）",
)

SPEC = {
    "goal": "为代码符号补写功能级生效条件注释，使其在检索侧可判（不再因缺证据恒 BLINDSPOT）",
    "target": "code_ 前缀节点中正文缺『生效条件』者",
    "landing": "源码定义行紧邻的井号注释（leading/body 两窗口，物理序合并）",
    "review_items": list(REVIEW_ITEMS),
    "gate": {"min_pass_rate": GATE_MIN_PASS_RATE, "basis": "人工核对忠实比例",
             "rule": "低于阈值不得扩批"},
    "honest_limits": [
        "本闸门只覆盖已索引的代码节点；未索引的源码不在面内（先跑 index_code）",
        "分层分配沿用 code_ 节点口径而非候选池，样本候选产出率由 sample_adequacy 如实上报",
        "不生成注释、不改节点：生成与评审属另一环节（LLM 生成 + 人工抽检）",
    ],
}


def _log_path(cg) -> str:
    return os.path.join(cg.root, LOG_NAME)


def is_candidate(cg, nid) -> bool:
    """候选判据：代码节点且正文缺『生效条件』（机械判据，唯一）。"""
    if not str(nid).startswith(PREFIX):
        return False
    node = cg.get(nid) or {}
    comp = nodefile.ccg_completeness(node.get("content") or "")
    return "生效条件" not in comp["required_present"]


def _landing(cg, nid) -> dict:
    """工单条目 → 源码落点（坐标 + 落点规则），供补写者直接定位。"""
    node = cg.get(nid) or {}
    fm = node.get("frontmatter") or {}
    ref = fm.get("code_ref") or {}
    return {
        "code_ref": {k: ref.get(k) for k in
                     ("path", "name", "kind", "lineno", "end", "lang", "precise")},
        "landing_rule": "定义行紧邻上方连续井号注释（leading）或定义行紧邻下方、体首语句之前（body）",
        "landing_note": "两窗口按源码物理行序合并；靠前者胜出（契约 §三.2）",
    }


def _item(cg, nid) -> dict:
    node = cg.get(nid) or {}
    content = node.get("content") or ""
    comp = nodefile.ccg_completeness(content)
    e = refine._entry(cg, nid)
    it = {
        "id": nid, "family": refine._family(cg, nid),
        "layer": e.get("layer"), "tags": list(e.get("tags") or []),
        "ccg_present": comp["present"],
        "ccg_missing": [m for m in nodefile.CCG_MARKS if m not in comp["present"]],
        "body_len": len(content),
        "source_sha": refine._sha(content)[:16],
    }
    it.update(_landing(cg, nid))
    return it


def candidates(cg, ids=None):
    """候选池（只读）→ (ids, meta)。"""
    if ids:
        pool = sorted({str(i) for i in ids if is_candidate(cg, i)})
        return pool, {"source": "explicit_ids", "pool": len(pool),
                      "requested": len(pool), "candidates": len(pool)}
    all_ids, protected = refine._pool(cg, PREFIX)
    cands = sorted(i for i in all_ids if is_candidate(cg, i))
    return cands, {"source": "scan", "prefix": PREFIX, "pool": len(all_ids),
                   "skipped_protected": protected, "candidates": len(cands)}


def plan(x, ids=None, n=None, seed=None) -> dict:
    """抽检工单（只读）：确定性样本 + 源码落点 + 口径声明 + 样本充分性。"""
    cg = refine._as_cg(x)
    seed = seed or SAMPLE_SEED
    n = SAMPLE_N if n is None else int(n)
    cands, cmeta = candidates(cg, ids=ids)
    if ids:
        sample = sorted(cands)
        smeta = {"pool": len(cands), "sampled": len(cands), "families": 0, "strata": {}}
    else:
        picked, smeta = refine.sample_ids(cg, n=n, seed=seed, prefix=PREFIX)
        sample = sorted(i for i in picked if is_candidate(cg, i))
    items = [_item(cg, nid) for nid in sample]
    strata = {}
    for it in items:
        s = strata.setdefault(it["family"], {"picked": 0, "missing_fields": {}})
        s["picked"] += 1
        for m in it["ccg_missing"]:
            s["missing_fields"][m] = s["missing_fields"].get(m, 0) + 1
    adequacy = {
        "sample_of_code_nodes": smeta.get("sampled", len(sample)),
        "candidates_in_sample": len(sample),
        "candidate_yield": round(len(sample) / float(smeta.get("sampled") or 1), 4),
        "note": "分配沿用 code_ 节点口径；产出率不足时应扩大 n 或改候选池重分配",
    }
    return {
        "root": cg.root, "dry_run": True, "readonly": True,
        "action": "comment_gate", "op": "maintain",
        "prefix": PREFIX, "seed": seed, "requested": n,
        "pool": cmeta, "sampled": len(items), "families": len(strata),
        "sample": sample, "sample_sha": refine._sha(*sample)[:16] if sample else "",
        "strata": strata, "items": items, "worklist": items,
        "spec": SPEC, "gate_rule": SPEC["gate"], "sample_adequacy": adequacy,
        "note": ("代码注释补写工单（只读）：供人工核对补写口径；"
                 "核对通过率未达阈值前不得扩批。本动作不改任何节点。"),
    }


def _stats(verdicts) -> dict:
    """通过率（只认忠实/pass/True），阈值取 refine 唯一真源。"""
    vs = list(verdicts or [])
    okv = {True, "1", "true", "True", "pass", "PASS", "faithful", "忠实",
           "accept", "ACCEPT"}
    passed = 0
    for v in vs:
        if v in okv:
            passed += 1
        elif isinstance(v, dict) and v.get("verdict") in okv:
            passed += 1
    reviewed = len(vs)
    rate = (passed / float(reviewed)) if reviewed else 0.0
    allowed = reviewed > 0 and rate >= GATE_MIN_PASS_RATE
    return {"reviewed": reviewed, "passed": passed, "pass_rate": round(rate, 4),
            "min_pass_rate": GATE_MIN_PASS_RATE, "expand_allowed": allowed,
            "reason": ("" if allowed else
                       ("no_review" if reviewed == 0 else
                        "rate %.4f < %.2f" % (rate, GATE_MIN_PASS_RATE)))}


def apply(x, ids=None, n=None, seed=None, verdicts=None, actor=None, note=None,
          batch=None) -> dict:
    """落抽检批次 + 人工裁决到 _comment_gate.jsonl。**不改写任何节点**。"""
    cg = refine._as_cg(x)
    p = plan(cg, ids=ids, n=n, seed=seed)
    batch = batch or time.strftime("%Y%m%d-%H%M%S")
    stats = _stats(verdicts)
    rec = {"t": time.time(), "action": "comment_gate", "batch": batch, "actor": actor,
           "seed": p["seed"], "requested": p["requested"], "pool": p["pool"],
           "sampled": p["sampled"], "sample": p["sample"], "sample_sha": p["sample_sha"],
           "sample_adequacy": p["sample_adequacy"], "verdicts": list(verdicts or []),
           "gate": stats, "note": note}
    os.makedirs(cg.root, exist_ok=True)
    with open(_log_path(cg), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + chr(10))
    return {"ok": True, "action": "comment_gate", "op": "maintain", "batch": batch,
            "root": cg.root, "sampled": p["sampled"], "gate": stats, "log": LOG_NAME,
            "note": ("抽检留痕已落盘（未改任何节点）；" +
                     ("闸门放行扩批" if stats["expand_allowed"] else
                      "闸门未放行：" + stats["reason"]))}


def gate(x, batch=None) -> dict:
    """扩批闸门：读留痕复算通过率（不写盘）。"""
    cg = refine._as_cg(x)
    recs = []
    path = _log_path(cg)
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    recs.append(json.loads(line))
                except ValueError:
                    continue
    if batch:
        recs = [r for r in recs if r.get("batch") == batch]
    if not recs:
        return {"ok": True, "action": "comment_gate_gate", "op": "maintain",
                "root": cg.root, "batch": batch, "batches": 0,
                "expand_allowed": False, "reason": "no_batch"}
    rec = recs[-1]
    stats = _stats(rec.get("verdicts"))
    return {"ok": True, "action": "comment_gate_gate", "op": "maintain",
            "root": cg.root, "batch": rec.get("batch"),
            "batches": len({r.get("batch") for r in recs}), **stats}


def run(x, action, **kw) -> dict:
    """maintain op 分派入口（与 backfill.run 同形，便于 mcp_server 侧并列分派）。"""
    if action == "comment_gate":
        if kw.get("apply"):
            return apply(x, ids=kw.get("ids"), n=kw.get("n"), seed=kw.get("seed"),
                         verdicts=kw.get("verdicts"), actor=kw.get("actor"),
                         note=kw.get("note"), batch=kw.get("batch"))
        return plan(x, ids=kw.get("ids"), n=kw.get("n"), seed=kw.get("seed"))
    if action == "comment_gate_verdict":
        return gate(x, batch=kw.get("batch"))
    raise ValueError("未知 comment_gate action：%s（允许 comment_gate / "
                     "comment_gate_verdict）" % action)
