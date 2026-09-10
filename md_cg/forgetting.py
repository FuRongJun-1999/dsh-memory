# -*- coding: utf-8 -*-
"""md_cg · 主动遗忘闸门（写入情景层前的三问筛选）

理论出处（全部来自本仓已有文档）：

  · `memory_score.md:12`
      J 判断引擎 9-10 档 = 「独立元认知 + **主动遗忘**」；灵枢正因「无主动遗忘」
      停在 8.0。→ 主动遗忘是 J 维上 9 分的门槛项，不是可选优化。
  · `docs/白箱智能系列·第五篇:174-180`
      「把经历兑换成结构…整理完之后记忆库变小了，但信息量反而更可用——
      噪音被扔掉了，骨架被留下。」
  · AEIS 工具表 `docs/tool_table_v0.3.0.md:15-19`
      `prefeed`（H1 新奇检测 → 高新奇输入当场强化编码）、
      `pattern_separation`（H3 扫描相似节点对）、
      `nightly_cleanup`（知识层夜间整理、无边孤岛降级）。
      本模块 = 这三件事的**写入侧前置版**：不等夜间整理，写之前就裁决。
  · `docs/智能的公理化基石.md:758-763` —— **诚实边界**
      「信息差与热力学熵之间只能进行结构类比，不应宣称数学同构」。
      故本模块一律称「自信息代理 / 惊奇度」，**不称香农熵**，也不做熵的物理断言。

三问 → 四态裁决（对齐白箱四态，落库动作分四种）：

    Q1 重复？    redundancy  = 新内容被既有同层节点覆盖的最大比例（bigram 覆盖率）
    Q2 重要？    importance  = 显式 hint 优先，否则启发式（新奇/来源/长度）
    Q3 惊奇？    self_info   = -log2(dup + ε)（bit，**代理量**，非香农熵）

    ACCEPT 写入      /  MERGE 并入既有（不新增，强化既有节点）
    DROP   丢弃      /  DEFER 待定（不写，留痕待复核）

裁决顺序（**顺序即语义**）：
    1) 重要度 ≥0.7            → ACCEPT（保护优先）
    2) 确定性内部产生 且 冗余 → DROP  ← 先于 MERGE：机器例行输出再"重复"也只是
                                        噪音，不该去强化既有记忆（否则例行日志
                                        会把普通记忆刷成高重要性）
    3) 冗余 ≥0.85             → MERGE ← 外部/未知来源的重复 = 又一次确认，强化
    4) 半重复 且 不重要       → DEFER
    5) 重要度 ≥0.30           → ACCEPT
    6) 新信息 ≥0.15           → ACCEPT
    7) 其余                   → DEFER

一切裁决都写进 `_forgetting.jsonl`（append-only），可审计：
「这条为什么没被记住」和「为什么被记住」同样有据可查。
"""
import hashlib
import json
import math
import os
import time

from . import nodefile
from .fsutil import append_jsonl, atomic_write, read_jsonl
from .mdcg import bigrams

# ---------------------------------------------------------------- 判据常量

DUP_MERGE = 0.85            # 重复度 ≥ 此值 → MERGE
DUP_DROP = 0.60             # 重复度 ≥ 此值 → 进入 DROP / DEFER 判据
NOVELTY_MIN = 0.15          # 新信息 < 此值 → 视为无新信息
IMPORTANCE_MIN = 0.30       # 重要度 < 此值 → 不予写入
PROTECT_IMPORTANCE = 0.70   # 对齐 tool_table：≥0.7 触发不可遗忘保护
MAX_BITS = 4.0              # 自信息归一化上限（dup=0 时 4.0 bit）
EPS = 0.0625                # 自信息平滑（避免 dup=0 时取 log(0)）
MAX_COMPARE = 240           # 单次重复检测最多比对的同层节点数（写入非热路径）

# 来源类型 → 权重（确定性内部产生 = 低权；外部惊奇 = 高权）
SOURCE_WEIGHT = {
    "external_surprising": 1.00,
    "unknown": 0.60,
    "self_generated": 0.50,
    "internal_deterministic": 0.25,
}
EXTERNAL_ROLES = ("user",)
INTERNAL_ROLES = ("command", "tool-output", "edit", "system")
# 注意：文科的 textbook/public_kb **不在此列**——它们是「权威来源表述一致」，
# 不是「内部确定性产生」，故仍按外部来源计权（见 source_kind）。
DETERMINISTIC_BASIS = ("data", "measurement", "compiler", "test", "formal_proof")

LOG_FILE = "_forgetting.jsonl"


# ---------------------------------------------------------------- 三问

def source_kind(role=None, verification_basis=None):
    """Q3 的来源面：内部确定性产生 vs 外部惊奇来源。"""
    r = str(role or "").strip().lower()
    vb = str(verification_basis or "").strip().lower()
    if r in EXTERNAL_ROLES:
        return "external_surprising"
    if r in INTERNAL_ROLES:
        return "internal_deterministic"
    if vb in DETERMINISTIC_BASIS:
        return "internal_deterministic"
    if r in ("assistant", "agent"):
        return "self_generated"
    return "unknown"


def _coverage(new_grams, body_grams):
    if not new_grams:
        return 0.0
    return len(new_grams & body_grams) / float(len(new_grams))


# CCG 五要素的固定标签：所有节点都一样，属**模板骨架而非内容**。
# 不剥离它们，任何两条记忆都会因共享 `# 功能名：`/`# 生效条件：` 而虚高重复度
# （实测：两条毫不相关的记忆 dup≈0.33，全部来自模板）。故重复检测只看"值"。
_TEMPLATE_LABELS = ("功能名", "生效条件", "子功能", "执行", "验证方式", "不适用条件")


def payload(content):
    """剥离 CCG 固定标签后的**内容骨架**（保留字段值，丢弃字段名与标记）。"""
    out = []
    for line in (content or "").splitlines():
        s = line.strip()
        if s.startswith("#"):
            s = s.lstrip("#").strip()
            for lab in _TEMPLATE_LABELS:
                if s.startswith(lab):
                    s = s[len(lab):].lstrip("：: ").strip()
                    break
        if s:
            out.append(s)
    return "".join(out)


def redundancy(cg, content, layer="contextual", exclude=None, limit=MAX_COMPARE):
    """Q1 重复？——新内容被既有同层节点覆盖的最大比例。"""
    new = bigrams(payload(content))
    best = {"max": 0.0, "with": None, "jaccard": 0.0, "compared": 0}
    if not new:
        return best
    nodes = ((getattr(cg, "index", None) or {}).get("nodes") or {})
    n = 0
    for nid in list(nodes.keys()):
        if nid == exclude:
            continue
        if layer and str(nodes[nid].get("layer") or "") != layer:
            continue
        try:
            node = cg.get(nid)
        except Exception:
            node = None
        if not node:
            continue
        body = bigrams(payload(node.get("content") or ""))
        if not body:
            continue
        n += 1
        cov = _coverage(new, body)
        if cov > best["max"]:
            best = {"max": cov, "with": nid,
                    "jaccard": len(new & body) / float(len(new | body) or 1),
                    "compared": n}
        if n >= limit:
            break
    best["compared"] = n
    return best


def self_information(dup):
    """Q3 的自信息代理：I = -log2(min(1, dup + ε))，单位 bit。

    注意：dup 是「被既有记忆覆盖率」的估计，不是概率模型的真实 P(x)，
    因此这是**结构类比的代理量**（见模块 docstring 的诚实边界）。
    """
    p = min(1.0, max(0.0, float(dup)) + EPS)
    return -math.log(p, 2.0)


def importance_score(hint, novelty, kind, content):
    """Q2 重要？——显式 hint 优先，否则启发式（对齐 longterm_snapshot 四因子简化版）。"""
    if hint is not None:
        try:
            return {"score": round(max(0.0, min(1.0, float(hint))), 4),
                    "from": "hint"}
        except (TypeError, ValueError):
            pass
    lf = min(1.0, len(content or "") / 200.0)
    s = (0.5 * novelty
         + 0.3 * SOURCE_WEIGHT.get(kind, SOURCE_WEIGHT["unknown"])
         + 0.2 * lf)
    return {"score": round(max(0.0, min(1.0, s)), 4), "from": "heuristic"}


def assess(cg, content, layer="contextual", role=None, verification_basis=None,
           importance_hint=None, node_id=None):
    """三问 → 四态裁决。返回完整判据（可审计，不只给结论）。"""
    kind = source_kind(role, verification_basis)
    red = redundancy(cg, content, layer=layer, exclude=node_id)
    novelty = round(1.0 - red["max"], 4)
    bits = round(self_information(red["max"]), 4)
    imp = importance_score(importance_hint, novelty, kind, content)
    entropy = {
        "source_kind": kind,
        "novelty": novelty,
        "self_information_bits": bits,
        "normalized": round(min(1.0, bits / MAX_BITS), 4),
        "duplicate_with": red["with"],
        "duplicate_ratio": round(red["max"], 4),
        "compared": red["compared"],
    }

    if imp["score"] >= PROTECT_IMPORTANCE:
        verdict, why = "ACCEPT", (f"重要度 {imp['score']:.2f}≥{PROTECT_IMPORTANCE}"
                                 f"（触发不可遗忘保护）")
    elif kind == "internal_deterministic" and red["max"] >= DUP_DROP:
        verdict, why = "DROP", (f"确定性内部产生且冗余 {red['max']:.2f}≥{DUP_DROP}"
                               f"（低熵噪音，不编码）")
    elif red["max"] >= DUP_MERGE:
        verdict, why = "MERGE", (f"重复度 {red['max']:.2f}≥{DUP_MERGE}"
                                f"（并入 {red['with']}，强化既有）")
    elif red["max"] >= DUP_DROP and imp["score"] < IMPORTANCE_MIN:
        verdict, why = "DEFER", (f"半重复 {red['max']:.2f}∈[{DUP_DROP},{DUP_MERGE})"
                                f" 且重要度 {imp['score']:.2f}<{IMPORTANCE_MIN}"
                                f"（待定复核）")
    elif imp["score"] >= IMPORTANCE_MIN:
        verdict, why = "ACCEPT", f"重要度 {imp['score']:.2f}≥{IMPORTANCE_MIN}"
    elif novelty >= NOVELTY_MIN:
        verdict, why = "ACCEPT", f"新信息 {novelty:.2f}≥{NOVELTY_MIN}"
    else:
        verdict, why = "DEFER", "重要度与新信息均不足判据（待定）"

    return {"verdict": verdict, "reason": why, "redundancy": red,
            "importance": imp, "entropy": entropy}


# ---------------------------------------------------------------- 落库动作

def log(cg, rec):
    """裁决留痕（append-only）。DROP/DEFER 也留痕——否则遗忘变黑箱。"""
    try:
        append_jsonl(os.path.join(cg.root, LOG_FILE), rec)
    except Exception:
        pass
    return rec


def reinforce(cg, node_id, delta=0.05):
    """MERGE 的落库动作：不新增节点，把「又一次见到」折算成既有节点的强化。

    重要性 +delta，merge_count +1；一旦跨过 0.7 自动打上保护标记
    （对齐「importance 提升（保护：不可遗忘…且受保护标记）」）。
    """
    try:
        node = cg.get(node_id)
    except Exception:
        node = None
    if not node:
        return None
    fm = node.get("frontmatter") or {}
    imp = min(1.0, float(fm.get("importance") or 0.5) + delta)
    fm["importance"] = imp
    fm["merge_count"] = int(fm.get("merge_count") or 0) + 1
    fm["last_merge_at"] = time.time()
    if imp >= PROTECT_IMPORTANCE:
        fm["protected"] = True
        fm["protection_reason"] = (f"importance={imp:.2f}≥{PROTECT_IMPORTANCE}"
                                   f"（重复强化）")
    cg._write_node(node_id, os.path.join(cg.root, node["path"]),
                   fm, node.get("content") or "")
    e = ((getattr(cg, "index", None) or {}).get("nodes") or {}).get(node_id)
    if e is not None:
        e["importance"] = imp
        if fm.get("protected"):
            e["protected"] = True
            e["protection_reason"] = fm["protection_reason"]
    return {"node_id": node_id, "importance": imp,
            "merge_count": fm["merge_count"], "protected": bool(fm.get("protected"))}


def history(cg, limit=100):
    """读取遗忘留痕（最近 limit 条）。"""
    p = os.path.join(cg.root, LOG_FILE)
    if not os.path.exists(p):
        return []
    out = []
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(__import__("json").loads(line))
                    except Exception:
                        continue
    except Exception:
        return []
    return out[-limit:]


def summary(cg):
    """遗忘留痕聚合（流式，不把全量日志读进内存）：总数 + 四态分布。"""
    p = os.path.join(cg.root, LOG_FILE)
    counts, total = {}, 0
    if not os.path.exists(p):
        return {"total": 0, "by_verdict": {}}
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    v = json.loads(line).get("verdict") or "?"
                except Exception:
                    continue
                counts[v] = counts.get(v, 0) + 1
                total += 1
    except Exception:
        return {"total": total, "by_verdict": counts}
    return {"total": total, "by_verdict": counts}


# ==========================================================================
# 长期记忆快照（maintain.longterm）
# ==========================================================================
#
# 目标：评估后**分层落盘**，形成可回溯的历史断面（哪一刻哪些记忆处于长期态）。
# 与上面写入侧闸门的分工：闸门管「这条要不要记」，快照管「记住的现在稳稳站在哪一层」。
#
# 性能纪律：全部判据来自**索引快照**（免读节点文件），流式写 JSONL，不全量载入内存。
# 4500+ 节点下 dry-run 为 O(N) 纯内存计算；apply 为顺序写文件。

MAINTAIN_LOG = "_maintain.jsonl"
LONGTERM_DIR = "_longterm"
LONGTERM_KEEP = 10                 # 保留最近 N 个断面（多了自动清理）
TIERS = ("longterm", "working", "candidate")
# 白箱可 ACCEPT 的基底档位；文科来源一致性档同样认账（否则「白箱判定已通过、
# 长期分层却视作未验证」自相矛盾）。
VERIFIED_BASES = ("formal_proof", "compiler", "test", "textbook", "public_kb")
TIER_WORKING = 0.40


def _tier_of(e: dict) -> str:
    """索引快照 → 分层：longterm（长期）/ working（工作）/ candidate（候选待评估）。"""
    imp = float(e.get("importance", 0.5) or 0.5)
    vb = e.get("verification_basis")
    ev = int(e.get("evidence_count", 0) or 0)
    if e.get("protected") or imp >= PROTECT_IMPORTANCE or (ev >= 3 and vb in VERIFIED_BASES):
        return "longterm"
    if imp >= TIER_WORKING or vb in VERIFIED_BASES:
        return "working"
    return "candidate"


def _is_island(e: dict) -> bool:
    """无边孤岛：既无出边也无子图声明（夜间整理的首要候选）。"""
    return (not (e.get("edges") or [])) and (not e.get("subgraph"))


def longterm_dir(cg) -> str:
    return os.path.join(cg.root, LONGTERM_DIR)


def current_path(cg) -> str:
    return os.path.join(longterm_dir(cg), "current.json")


def longterm_assess(cg, apply=False, out=None, layer=None, keep=LONGTERM_KEEP,
                    max_rows=None, force=False, actor="maintain"):
    """评估后分层落盘：生成一个可回溯的长期记忆断面。

    apply=False（默认）只出报表；apply=True 写 `_longterm/<ts>.jsonl` 并更新
    `current.json` 指针。幂等：断面内容相同则跳过重写（除非 force=True）。
    """
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    ids = sorted(nid for nid, e in nodes.items()
                 if not layer or e.get("layer") == layer)
    if max_rows:
        ids = ids[:int(max_rows)]
    tiers, by_layer, islands, digest = {}, {}, 0, hashlib.sha1()
    t0 = time.time()
    total = len(ids)
    for nid in ids:
        e = nodes.get(nid) or {}
        t = _tier_of(e)
        tiers[t] = tiers.get(t, 0) + 1
        lay = e.get("layer") or "?"
        bl = by_layer.setdefault(lay, {k: 0 for k in TIERS})
        bl[t] += 1
        if _is_island(e):
            islands += 1
        digest.update(f"{nid}:{e.get('importance')}:{t};".encode("utf-8"))
    snapshot_id = digest.hexdigest()[:12]
    ts = time.strftime("%Y%m%d-%H%M%S")
    rel = f"{LONGTERM_DIR}/{ts}-{snapshot_id}.jsonl"
    path = os.path.join(cg.root, rel)
    cur = None
    try:
        with open(current_path(cg), encoding="utf-8") as f:
            cur = json.load(f)
    except (OSError, ValueError):
        cur = None
    same = bool(cur and cur.get("snapshot_id") == snapshot_id
                and os.path.exists(os.path.join(cg.root, cur.get("path") or "")))
    written, pruned = 0, []
    if apply and not same:
        d = longterm_dir(cg)
        os.makedirs(d, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for nid in ids:
                e = nodes.get(nid) or {}
                row = {"t": time.time(), "id": nid, "layer": e.get("layer"),
                       "importance": e.get("importance"),
                       "tier": _tier_of(e),
                       "verification_basis": e.get("verification_basis"),
                       "evidence_count": e.get("evidence_count", 0),
                       "edges": len(e.get("edges") or []),
                       "island": _is_island(e),
                       "content_hash": e.get("content_hash")}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
        os.replace(tmp, path)
        atomic_write(current_path(cg), json.dumps(
            {"snapshot_id": snapshot_id, "ts": time.time(), "path": rel,
             "total": total, "tiers": tiers, "by_layer": by_layer,
             "islands": islands}, ensure_ascii=False))
        pruned = _prune(cg, keep)
        append_jsonl(os.path.join(cg.root, MAINTAIN_LOG), {
            "t": time.time(), "action": "longterm", "snapshot_id": snapshot_id,
            "path": rel, "total": total, "tiers": tiers, "actor": actor})
    return {
        "ok": True, "action": "longterm", "dry_run": not apply,
        "snapshot_id": snapshot_id, "path": rel, "same_as_current": same,
        "total": total, "tiers": tiers, "by_layer": by_layer,
        "islands": islands, "written": written, "pruned": pruned,
        "elapsed_ms": int((time.time() - t0) * 1000), "log": MAINTAIN_LOG,
        "note": ("dry-run：未写盘" if not apply else
                 (f"断面与 current 相同，跳过重写（id={snapshot_id}）" if same
                  else f"已写断面 {rel}（{written} 行）")),
    }


def _prune(cg, keep):
    """只保留最近 keep 个断面文件（按文件名时间前缀排序）。"""
    d = longterm_dir(cg)
    try:
        files = sorted(x for x in os.listdir(d) if x.endswith(".jsonl"))
    except OSError:
        return []
    removed = []
    for x in files[:-int(keep)] if int(keep) > 0 else []:
        try:
            os.remove(os.path.join(d, x))
            removed.append(x)
        except OSError:
            pass
    return removed


def longterm_list(cg, limit=20):
    """列出历史断面（新的在前）：{snapshot_id, path, ts, total, tiers}。"""
    d = longterm_dir(cg)
    out = []
    try:
        for x in sorted(os.listdir(d), reverse=True):
            if not x.endswith(".jsonl"):
                continue
            p = os.path.join(d, x)
            out.append({"file": x, "path": f"{LONGTERM_DIR}/{x}",
                        "bytes": os.path.getsize(p)})
            if len(out) >= int(limit):
                break
    except OSError:
        return []
    cur = None
    try:
        with open(current_path(cg), encoding="utf-8") as f:
            cur = json.load(f)
    except (OSError, ValueError):
        cur = None
    return {"current": cur, "snapshots": out}


def longterm_show(cg, snapshot_id=None):
    """读取某个断面的分层统计（不载全量行，只聚合）。"""
    d = longterm_dir(cg)
    target = None
    try:
        files = sorted(x for x in os.listdir(d) if x.endswith(".jsonl"))
    except OSError:
        return {"ok": False, "error": "no_snapshot"}
    for x in reversed(files):
        if snapshot_id is None or snapshot_id in x:
            target = x
            break
    if not target:
        return {"ok": False, "error": "snapshot_not_found", "snapshot_id": snapshot_id}
    tiers, by_layer, islands, n = {}, {}, 0, 0
    with open(os.path.join(d, target), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            n += 1
            t = r.get("tier") or "?"
            tiers[t] = tiers.get(t, 0) + 1
            lay = r.get("layer") or "?"
            by_layer.setdefault(lay, {k: 0 for k in TIERS})
            by_layer[lay][t] = by_layer[lay].get(t, 0) + 1
            if r.get("island"):
                islands += 1
    return {"ok": True, "file": target, "total": n, "tiers": tiers,
            "by_layer": by_layer, "islands": islands}


# ==========================================================================
# 海马体前馈（maintain.prefeed）
# ==========================================================================
#
# 写入**之前**的新奇检测：重复项并入既有（MERGE），而非新增；无关噪音丢弃；
# 有歧义的半重复留痕待复核。这是「写入侧前置」的落库动作，比夜间整理更早一步。

def prefeed(cg, content, layer="contextual", role=None, verification_basis=None,
            importance_hint=None, node_id=None):
    """前馈裁决（不写盘）：返回四态 + 判据，并留痕 `_forgetting.jsonl`。

    落库由调用方按 verdict 执行（ACCEPT 新增 / MERGE 强化 / DROP|DEFER 不写），
    使「裁决」与「落库」解耦——便于 dry-run 预演与单测。
    """
    vd = assess(cg, content, layer=layer, role=role,
                verification_basis=verification_basis,
                importance_hint=importance_hint, node_id=node_id)
    decision = {"ACCEPT": "write", "MERGE": "reinforce",
                "DROP": "discard", "DEFER": "defer"}.get(vd["verdict"], "defer")
    rec = {"kind": "prefeed", "layer": layer,
           "node_id": node_id or _prefeed_id(content),
           "verdict": vd["verdict"], "decision": decision,
           "reason": vd["reason"], "duplicate_with": vd["redundancy"]["with"],
           "duplicate_ratio": vd["redundancy"]["max"],
           "novelty": vd["entropy"]["novelty"],
           "self_information_bits": vd["entropy"]["self_information_bits"],
           "actor": getattr(cg, "actor", "unknown"), "t": time.time()}
    log(cg, rec)
    return {"ok": True, "action": "prefeed", **rec}


def _prefeed_id(content):
    return "pre_" + hashlib.sha1((content or "").encode("utf-8")).hexdigest()[:12]


def maintain_history(cg, limit=100, action=None):
    """维护留痕（`_maintain.jsonl` 最近 limit 条），可按 action 过滤。"""
    recs = list(read_jsonl(os.path.join(cg.root, MAINTAIN_LOG)))
    if action:
        recs = [r for r in recs if r.get("action") == action]
    return recs[-int(limit):]
