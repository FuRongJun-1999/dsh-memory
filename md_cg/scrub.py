# -*- coding: utf-8 -*-
"""md_cg · 记忆自净（记忆 OS #5）：抽查 / 联想 / 去污染 / 校准偏差

自维持（`sustain.py`）解决「进程还活着」，本模块解决「记忆还干净」。
四件事构成一个闭环，挂在常驻循环上周期性跑：

① **记忆抽查（sample）**
   分层抽样而非随机抽样：风险层（陈旧 / 低置信 / 有反例 / 从未验证 / 孤立）
   + 对照组（高频 / 随机基线）。对照组是刻意的——只查「看起来有问题」的节点
   会形成确认偏差，永远发现不了「看起来没问题其实有问题」的记忆。
   `seed` 固定 → 同 seed 同样本（可复现、可审计，对齐本仓确定性白箱取向）。

② **联想（associate）**
   从抽样节点出发三路邻域合并：
     关系链（`chain.walk`，带条件序列）· 子图层级（`subgraph.expand`）
     · 词法近邻（bigram Jaccard）
   用途是找到「同族节点」——矛盾与重复只能在同族之间判定，孤立地看一个节点
   永远看不出它和谁冲突。

③ **去污染（audit → decontaminate）**
   确定性判据（只读、可解释）识别五类污染：
     `contradiction` 同族矛盾（同键不同值 / 极性相反且共享词）
     `expired`       时效过期（`valid_until` / `expires_at` 已过）
     `duplicate`     高冗余（`forgetting.redundancy` ≥ 合并阈值）
     `orphan_noise`  孤立噪音（零访问 + 低重要 + 情境层）
     `unverified`    长期未验证（knowledge 层且零证据）
   处置**只做可逆动作**且复用既有机制：
     · `weaken` → `cg.verify(verdict="weakened")`：反例 +1、置信 -0.15、
       跌破 0.2 自动降级（验证机制天然留痕，不另造一套）
     · `demote` → `cg._move_layer("contextual")`：降出可信层（走保护闸门）
     · `hint`   → 只给建议（合并 / 补证据需语义判断，不代劳）
   受保护节点（self/anchor/importance≥0.7/显式保护）**跳过**；**永不删除**。
   幂等：`_scrub.jsonl` 里已处理过的 (节点, 污染类型) 不重复动手。

④ **校准偏差（calibrate）**
   用「自报置信 vs 实测正确率」（`metacognition.calibration`）算全局 gap 与
   分桶偏差，给出偏置建议；`apply=True` 才写回（只动有证据的节点，保护节点跳过）。

所有动作留痕 `_scrub.jsonl`（payload-free：只记 id / 判据 / 动作，不记内容）。
零第三方依赖。
"""
from __future__ import annotations

import os
import random
import time

from . import forgetting, protect
from .fsutil import append_jsonl, read_jsonl
from .mdcg import bigrams

SCRUB_LOG = "_scrub.jsonl"

DEFAULT_SAMPLE = 12
DEFAULT_HOPS = 2
STALE_DAYS = 30.0            # 多久没被访问算「陈旧」
UNVERIFIED_DAYS = 14.0       # knowledge 层多久没验证算「长期未验证」
LOW_CONF = 0.35              # 低于此置信算「低置信」
ORPHAN_IMPORTANCE = 0.30     # 孤立噪音的重要度上限
MAX_ASSOC_SCAN = 600         # 词法近邻比对上限（全库扫描保护）
MAX_BINS_REPORT = 4
MAX_OFFSET = 0.15            # 校准偏置上限（一次最多挪这么多）
SELF_LAYERS = ("self", "anchor")

STRATA = ("stale", "low_conf", "disputed", "unverified", "orphan", "hot", "random")
STRATUM_WEIGHTS = {"stale": 0.20, "low_conf": 0.20, "disputed": 0.15,
                   "unverified": 0.15, "orphan": 0.10, "hot": 0.10,
                   "random": 0.10}

# 污染类型 → (严重度, 处置动作)
CONTAMINATION = {
    "contradiction": ("high", ("weaken", "demote")),
    "expired": ("high", ("weaken", "demote")),
    "duplicate": ("medium", ("hint",)),
    "orphan_noise": ("low", ("weaken", "demote")),
    "unverified": ("info", ("hint",)),
}
SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1, "info": 0}


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------

def _nodes(cg) -> dict:
    return (getattr(cg, "index", None) or {}).get("nodes") or {}


def _fm_of(cg, nid, cache=None) -> dict:
    """取节点 frontmatter（带可选缓存）。不可读（缺密钥 / 已删）→ {}。"""
    if cache is not None and nid in cache:
        return cache[nid]
    node = None
    try:
        node = cg.get(nid)
    except Exception:
        node = None
    fm = (node or {}).get("frontmatter") or {}
    if cache is not None:
        cache[nid] = fm
    return fm


def _access(cg):
    """(访问次数, 最后访问时间)：读访问日志，未 compact 的也算。"""
    try:
        return cg.access_counts()
    except Exception:
        return {}, {}


def _adjacency(cg) -> dict:
    try:
        from . import chain
        return chain.adjacency(cg)
    except Exception:
        return {}


def _days(ts, now) -> float:
    try:
        ts = float(ts or 0)
    except (TypeError, ValueError):
        return 0.0
    return (now - ts) / 86400.0 if ts else 0.0


def _log(cg, op: str, **rec) -> dict:
    rec = dict(rec, t=time.time(), op=op)
    try:
        append_jsonl(os.path.join(cg.root, SCRUB_LOG), rec)
    except Exception:
        pass
    return rec


def _handled(cg) -> set:
    """已处置过的 (node_id, kind)：保证去污染幂等（审计即状态）。"""
    out = set()
    for rec in list(read_jsonl(os.path.join(cg.root, SCRUB_LOG))):
        if rec.get("op") == "decontaminate" and rec.get("ok"):
            out.add((rec.get("node_id"), rec.get("kind")))
    return out


# --------------------------------------------------------------------------
# ① 记忆抽查
# --------------------------------------------------------------------------

def _pool_candidates(cg, *, now, stale_days, unverified_days, max_reads=200):
    """构造各层候选池（不读文件的部分先用索引 + 访问日志）。"""
    nodes = _nodes(cg)
    counts, last = _access(cg)
    adj = _adjacency(cg)
    indeg = {}
    for _src, outs in adj.items():
        for tgt, _e in outs:
            indeg[tgt] = indeg.get(tgt, 0) + 1

    pools = {s: [] for s in STRATA}
    cache, reads = {}, 0
    for nid, e in nodes.items():
        layer = str(e.get("layer") or "")
        if layer in SELF_LAYERS:
            continue                              # 自我认知不抽查、不去污染
        created = float(e.get("created_at") or 0)
        age_d = _days(created, now)
        la = float(last.get(nid) or 0)
        acc = int(counts.get(nid) or 0)
        ev = int(e.get("evidence_count") or 0)
        deg = len(adj.get(nid) or []) + indeg.get(nid, 0)

        if la:
            if _days(la, now) >= stale_days:
                pools["stale"].append((nid, f"距上次访问 {_days(la, now):.0f} 天"))
        elif age_d >= stale_days:
            pools["stale"].append((nid, f"从未访问且已存在 {age_d:.0f} 天"))

        if acc >= 3:
            pools["hot"].append((nid, f"高频访问 {acc} 次"))

        if deg == 0 and layer == "contextual":
            pools["orphan"].append((nid, "无任何关系边（孤立）"))

        if ev <= 0 and layer == "knowledge" and age_d >= unverified_days:
            pools["unverified"].append((nid, f"knowledge 层 {age_d:.0f} 天零验证"))

        if ev > 0 and reads < int(max_reads):
            fm = _fm_of(cg, nid, cache)
            if fm:
                reads += 1
                neg = int(fm.get("negative_evidence") or 0)
                conf = float(fm.get("confidence", 0.6))
                if neg > 0:
                    pools["disputed"].append((nid, f"有 {neg} 条反例"))
                if conf < LOW_CONF:
                    pools["low_conf"].append((nid, f"置信 {conf:.2f}"))

        pools["random"].append((nid, "随机基线"))

    # 池内排序：风险优先（可复现），抽样时再按 seed 洗牌
    pools["stale"].sort(key=lambda x: (nodes.get(x[0], {}).get("created_at") or 0))
    pools["hot"].sort(key=lambda x: -(int(counts.get(x[0]) or 0)))
    pools["unverified"].sort(
        key=lambda x: (nodes.get(x[0], {}).get("created_at") or 0))
    pools["orphan"].sort(
        key=lambda x: float(nodes.get(x[0], {}).get("importance") or 0.5))
    pools["disputed"].sort(key=lambda x: -len(x[1]))
    pools["low_conf"].sort(key=lambda x: x[1])
    return pools


def _quota(n: int, strategy: str) -> dict:
    if strategy == "random":
        return {"random": int(n)}
    weights = dict(STRATUM_WEIGHTS)
    if strategy == "risk":
        weights.pop("hot", None)
        weights.pop("random", None)
    total = sum(weights.values()) or 1.0
    out, used = {}, 0
    for s in STRATA:
        if s in weights:
            k = int(round(int(n) * weights[s] / total))
            out[s] = k
            used += k
    rest = int(n) - used
    if rest:
        key = "random" if "random" in out else "stale"
        out[key] = out.get(key, 0) + rest
    return out


def _pick(pool, k: int, seed, stratum: str):
    """从池中取 k 个：风险最高的 3k 个入池，再按 seed 稳定洗牌。"""
    if k <= 0 or not pool:
        return []
    cand = list(pool)
    if len(cand) > k * 3:
        cand = cand[:k * 3]
    random.Random(f"{seed}:{stratum}").shuffle(cand)
    return cand[:k]


def sample(cg, n: int = DEFAULT_SAMPLE, *, strategy: str = "stratified",
           seed=None, stale_days: float = STALE_DAYS,
           unverified_days: float = UNVERIFIED_DAYS,
           max_reads: int = 200) -> dict:
    """分层抽查记忆，返回带分层标签的样本。

    strategy：`stratified`（默认，风险层 + 对照组）· `risk`（只查风险层）
    · `random`（纯随机基线）。seed 固定 → 同样本可复现。
    """
    strategy = str(strategy or "stratified").lower()
    if strategy not in ("stratified", "risk", "random"):
        raise ValueError(f"未知抽样策略：{strategy}（stratified|risk|random）")
    now = time.time()
    seed = 0 if seed is None else seed
    pools = _pool_candidates(cg, now=now, stale_days=stale_days,
                             unverified_days=unverified_days,
                             max_reads=max_reads)
    quota = _quota(n, strategy)
    picked, seen = [], set()
    for s in STRATA:
        for nid, reason in _pick(pools.get(s), quota.get(s, 0), seed, s):
            if nid in seen:
                continue
            seen.add(nid)
            picked.append({"node_id": nid, "stratum": s, "reason": reason})
    # 风险层不够时用随机池补足（先剔除已选，避免跳过造成不满额）
    if len(picked) < int(n):
        rest = [x for x in pools["random"] if x[0] not in seen]
        for nid, reason in _pick(rest, int(n) - len(picked), seed,
                                 "random-fill"):
            seen.add(nid)
            picked.append({"node_id": nid, "stratum": "random",
                           "reason": reason})
    return {"ok": True, "strategy": strategy, "seed": seed, "n": len(picked),
            "strata": {s: len(pools.get(s) or []) for s in STRATA},
            "sample": picked, "t": now}


# --------------------------------------------------------------------------
# ② 联想
# --------------------------------------------------------------------------

def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def associate(cg, node_id: str, *, hops: int = DEFAULT_HOPS, limit: int = 30,
              lexical: bool = True, min_sim: float = 0.25,
              max_scan: int = MAX_ASSOC_SCAN) -> dict:
    """三路邻域联想：关系链 + 子图层级 + 词法近邻。

    返回按权重降序的 `related`；每条带 `via`（哪一路发现）与 `weight`，
    便于审计「为什么把这两个节点算作同族」。
    """
    related = {}

    def put(nid, via, weight, depth=1, **extra):
        if not nid or nid == node_id:
            return
        rec = {"node_id": nid, "via": via, "weight": round(float(weight), 4),
               "depth": int(depth)}
        rec.update(extra)
        cur = related.get(nid)
        if cur is None or rec["weight"] > cur["weight"]:
            related[nid] = rec

    # 联想是双向的：同族既可能是「我指向的」也可能是「指向我的」，
    # 故关系链同时沿出边与入边展开（`chain_t --causal--> a` 也要能从 a 找到）。
    try:
        from . import chain
        for direction in ("out", "in"):
            for c in chain.walk(cg, node_id,
                                relation_types=chain.CHAIN_TYPES_DEFAULT,
                                max_depth=int(hops), max_chains=200,
                                include_hierarchy=True, direction=direction):
                for i, h in enumerate(c.get("hops") or [], 1):
                    put(h["to"], "chain",
                        float(h.get("weight") or 1.0) * (0.8 ** (i - 1)),
                        depth=i, relation_type=h.get("relation_type"),
                        condition=h.get("condition") or "")
    except Exception:
        pass

    # 子图层级：向下展开子树 + 向上追溯祖先（父边唯一，逐级上溯）。
    try:
        from . import subgraph
        ex = subgraph.expand(cg, node_id, max_depth=int(hops))
        for nid, path in (ex.get("paths") or {}).items():
            d = str(path).count("/")
            put(nid, "subgraph", 1.0 / (1 + d), depth=d)
        pmap = subgraph.parents_index(cg)
        cur, d = node_id, 0
        while d < int(hops):
            ps = pmap.get(cur) or []
            if not ps:
                break
            d += 1
            for pid in ps:
                put(pid, "subgraph", 1.0 / (1 + d), depth=d)
            cur = ps[0]
    except Exception:
        pass

    if lexical:
        base = None
        try:
            base = cg.get(node_id)
        except Exception:
            base = None
        bg = bigrams((base or {}).get("content") or "")
        if bg:
            cands = []
            for i, nid in enumerate(_nodes(cg)):
                if i >= int(max_scan):
                    break
                if nid == node_id or nid in related:
                    continue
                try:
                    node = cg.get(nid)
                except Exception:
                    node = None
                b2 = bigrams((node or {}).get("content") or "")
                sim = _jaccard(bg, b2)
                if sim >= min_sim:
                    cands.append((sim, nid))
            cands.sort(key=lambda x: (-x[0], x[1]))
            for sim, nid in cands[:int(limit)]:
                put(nid, "lexical", sim, depth=1, similarity=round(sim, 4))

    items = sorted(related.values(), key=lambda r: (-r["weight"], r["node_id"]))
    by_via = {}
    for r in items:
        by_via[r["via"]] = by_via.get(r["via"], 0) + 1
    return {"ok": True, "node_id": node_id, "n": len(items),
            "related": items[:int(limit)], "by_via": by_via}


# --------------------------------------------------------------------------
# ③ 去污染：确定性判据
# --------------------------------------------------------------------------

_EXPIRY_KEYS = ("valid_until", "expires_at", "expire_at", "expiry", "deadline")
_SKIP_KEYS = ("功能名", "执行", "条件", "来源", "标签", "状态", "备注", "标题",
              "描述", "name", "id", "title", "layer", "tags", "说明")
_NEG_WORDS = ("禁止", "不得", "不要", "不能", "切勿", "避免", "不应", "不可")
_POS_WORDS = ("应当", "建议", "必须", "需要", "可以", "允许", "推荐", "宜")


def _to_ts(v):
    """宽松时间解析：秒级时间戳 / ISO / `YYYY-MM-DD`。无法识别 → None。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        return f if f > 1e8 else None
    s = str(v or "").strip()
    if not s:
        return None
    for fmt, n in (("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d %H:%M:%S", 19),
                   ("%Y-%m-%d", 10)):
        try:
            return time.mktime(time.strptime(s[:n], fmt))
        except ValueError:
            continue
    try:
        f = float(s)
        return f if f > 1e8 else None
    except ValueError:
        return None


def _kv_pairs(content) -> dict:
    """抽 `键：值` 对（中文/英文冒号），跳过结构字段。"""
    out = {}
    for raw in (content or "").splitlines():
        line = raw.strip().lstrip("#").strip()
        if not line:
            continue
        for sep in ("：", ":"):
            if sep in line:
                k, _, v = line.partition(sep)
                k, v = k.strip(), v.strip()
                if 2 <= len(k) <= 12 and v and k not in _SKIP_KEYS:
                    out.setdefault(k, v)
                break
    return out


def _polarity(content) -> int:
    c = content or ""
    return (-1 if any(w in c for w in _NEG_WORDS) else 0) + \
           (1 if any(w in c for w in _POS_WORDS) else 0)


def _expired(fm, now):
    for k in _EXPIRY_KEYS:
        if k in fm:
            ts = _to_ts(fm.get(k))
            if ts is not None and ts < now:
                return k, fm.get(k)
    return None


def _contradiction(cg, content, related, max_compare=10):
    """与同族节点比对：同键不同值 / 极性相反且共享 bigram。"""
    kv_a = _kv_pairs(content)
    bg_a, pol_a = bigrams(content or ""), _polarity(content)
    for r in (related or [])[:int(max_compare)]:
        oid = r["node_id"]
        try:
            onode = cg.get(oid)
        except Exception:
            onode = None
        if not onode:
            continue
        oc = onode.get("content") or ""
        kv_b = _kv_pairs(oc)
        for k in sorted(set(kv_a) & set(kv_b)):
            if kv_a[k] != kv_b[k]:
                return {"with": oid, "via": r.get("via"),
                        "why": f"同键不同值：{k}={kv_a[k]} vs {kv_b[k]}"}
        bg_b = bigrams(oc)
        if pol_a * _polarity(oc) < 0 and bg_a and bg_b:
            shared = bg_a & bg_b
            ratio = len(shared) / max(1, min(len(bg_a), len(bg_b)))
            if len(shared) >= 3 and ratio >= 0.15:
                return {"with": oid, "via": r.get("via"),
                        "why": "极性相反且共享内容：" + "、".join(
                            sorted(shared)[:5])}
    return None


def audit(cg, node_ids=None, *, hops: int = 1, min_severity: str = "info",
          limit=None, unverified_days: float = UNVERIFIED_DAYS,
          lexical: bool = True, min_sim: float = 0.15) -> dict:
    """对指定节点（默认全库）做污染体检。**只读**，不改动任何节点。"""
    nodes = _nodes(cg)
    ids = list(nodes.keys()) if node_ids is None else (
        [node_ids] if isinstance(node_ids, str) else list(node_ids))
    if limit:
        ids = ids[:int(limit)]
    counts, _last = _access(cg)
    adj = _adjacency(cg)
    indeg = {}
    for _src, outs in adj.items():
        for tgt, _e in outs:
            indeg[tgt] = indeg.get(tgt, 0) + 1
    now = time.time()
    issues, checked = [], 0

    for nid in ids:
        e = nodes.get(nid)
        if not e:
            continue
        layer = str(e.get("layer") or "")
        if layer in SELF_LAYERS:
            continue
        try:
            node = cg.get(nid)
        except Exception:
            node = None
        if not node:
            continue
        checked += 1
        fm = node.get("frontmatter") or {}
        content = node.get("content") or ""
        age_d = _days(fm.get("created_at") or e.get("created_at"), now)

        def add(kind, detail, **extra):
            sev, actions = CONTAMINATION[kind]
            if SEVERITY_ORDER.get(sev, 0) < SEVERITY_ORDER.get(min_severity, 0):
                return
            rec = {"node_id": nid, "layer": layer, "kind": kind,
                   "severity": sev, "detail": detail, "fix": list(actions)}
            rec.update(extra)
            issues.append(rec)

        hit = _expired(fm, now)
        if hit:
            add("expired", f"时效已过：{hit[0]}={hit[1]}", evidence=hit[0])

        if (layer == "knowledge" and age_d >= unverified_days
                and int(e.get("evidence_count") or 0) <= 0):
            add("unverified", f"knowledge 层 {age_d:.0f} 天零验证")

        if ((len(adj.get(nid) or []) + indeg.get(nid, 0)) == 0
                and layer == "contextual"
                and int(counts.get(nid) or 0) == 0
                and float(fm.get("importance") or e.get("importance") or 0.5)
                < ORPHAN_IMPORTANCE):
            add("orphan_noise", "孤立且零访问、低重要（情境噪音）")

        try:
            red = forgetting.redundancy(cg, content, layer=layer, exclude=nid)
        except Exception:
            red = None
        if red and float(red.get("max") or 0) >= float(forgetting.DUP_MERGE):
            add("duplicate", f"冗余 {red['max']:.2f}（与 {red.get('with')}）",
                duplicate_with=red.get("with"))

        rel = associate(cg, nid, hops=max(1, int(hops)), limit=10,
                        lexical=lexical, min_sim=min_sim)["related"]
        bad = _contradiction(cg, content, rel)
        if bad:
            add("contradiction", bad["why"], conflict_with=bad.get("with"))

    by_kind = {}
    for i in issues:
        by_kind[i["kind"]] = by_kind.get(i["kind"], 0) + 1
    high = sum(1 for i in issues if i["severity"] == "high")
    med = sum(1 for i in issues if i["severity"] == "medium")
    return {"ok": not (high or med), "n_checked": checked,
            "n_issues": len(issues), "issues": issues, "by_kind": by_kind,
            "stats": {"checked": checked, "high": high, "medium": med,
                      "low": sum(1 for i in issues if i["severity"] == "low")},
            "t": now}


def _weaken(cg, nid, kind, detail, times=1):
    res = None
    for _ in range(max(1, int(times))):
        res = cg.verify(nid, f"scrub:{kind}:{str(detail)[:120]}", "weakened")
    return res


def decontaminate(cg, node_ids=None, *, kinds=None, dry_run: bool = True,
                  min_severity: str = "medium", hops: int = 1, actor=None,
                  override: bool = False, weaken_times: int = 1,
                  demote: bool = True) -> dict:
    """按体检结果处置污染。**默认 dry_run**；实修只做可逆动作。

    动作：`weaken`（verify weakened → 反例+1、置信-0.15、跌破 0.2 自动降级）、
    `demote`（降级到情境层）、`hint`（只建议，不改）。保护节点跳过；永不删除。
    """
    rep = audit(cg, node_ids, hops=hops, min_severity=min_severity)
    handled = _handled(cg)
    actions = []
    n_applied = n_prot = n_done = n_hint = 0

    for issue in rep["issues"]:
        nid, kind = issue["node_id"], issue["kind"]
        if kinds and kind not in kinds:
            continue
        if kind in ("duplicate", "unverified"):
            n_hint += 1
            actions.append({"node_id": nid, "kind": kind, "action": "hint",
                            "detail": issue["detail"], "applied": False})
            continue
        if (nid, kind) in handled:
            n_done += 1
            actions.append({"node_id": nid, "kind": kind, "action": "skip",
                            "detail": "已处置过（幂等）", "applied": False})
            continue
        prot, why = protect.is_protected(cg, nid)
        if prot and not override:
            n_prot += 1
            actions.append({"node_id": nid, "kind": kind,
                            "action": "skip_protected", "detail": why,
                            "applied": False})
            continue
        if dry_run:
            actions.append({"node_id": nid, "kind": kind,
                            "action": "planned",
                            "planned": list(CONTAMINATION[kind][1]),
                            "detail": issue["detail"], "applied": False})
            continue

        done = []
        try:
            _weaken(cg, nid, kind, issue["detail"], weaken_times)
            done.append("weaken")
        except Exception as exc:                          # noqa: BLE001
            done.append(f"weaken_failed:{type(exc).__name__}")
        if demote and issue["severity"] in ("high", "low"):
            try:
                fm = _fm_of(cg, nid, None)
                if str(fm.get("layer") or "") != "contextual":
                    cg._move_layer(nid, "contextual", reason=f"scrub:{kind}")
                    done.append("demote")
            except Exception as exc:                      # noqa: BLE001
                done.append(f"demote_failed:{type(exc).__name__}")
        n_applied += 1
        _log(cg, "decontaminate", node_id=nid, kind=kind, ok=True,
             actions=done, severity=issue["severity"], actor=actor)
        actions.append({"node_id": nid, "kind": kind, "action": "applied",
                        "done": done, "detail": issue["detail"],
                        "applied": True})

    if not dry_run:
        _log(cg, "decontaminate_batch", ok=True, applied=n_applied,
             skipped_protected=n_prot, skipped_done=n_done, hints=n_hint,
             actor=actor)
    return {"ok": True, "dry_run": dry_run, "n_issues": rep["n_issues"],
            "applied": n_applied, "skipped_protected": n_prot,
            "skipped_done": n_done, "hints": n_hint, "actions": actions,
            "audit": rep, "t": time.time()}


# --------------------------------------------------------------------------
# ④ 校准偏差
# --------------------------------------------------------------------------

def _apply_offset(cg, offset, *, override=False, min_evidence=1):
    nodes = _nodes(cg)
    adjusted = skipped = 0
    for nid, e in nodes.items():
        if str(e.get("layer") or "") in SELF_LAYERS:
            skipped += 1
            continue
        if int(e.get("evidence_count") or 0) < int(min_evidence):
            continue
        prot, _why = protect.is_protected(cg, nid)
        if prot and not override:
            skipped += 1
            continue
        try:
            node = cg.get(nid)
        except Exception:
            node = None
        if not node:
            continue
        fm = node.get("frontmatter") or {}
        old = float(fm.get("confidence", 0.6))
        new = round(max(0.0, min(0.99, old + float(offset))), 4)
        if abs(new - old) < 1e-9:
            continue
        fm["confidence"] = new
        fm["calibration"] = {"t": time.time(), "offset": round(float(offset), 4),
                             "from": old, "to": new}
        try:
            cg._write_node(nid, os.path.join(cg.root, e["path"]), fm,
                           node.get("content") or "")
            adjusted += 1
        except Exception:                                 # noqa: BLE001
            pass
    return adjusted, skipped


def calibrate(cg, *, apply: bool = False, override: bool = False, actor=None,
              max_offset: float = MAX_OFFSET, min_evidence: int = 1) -> dict:
    """校准偏差：自报置信 vs 实测正确率 → 偏置建议（`apply=True` 才写回）。"""
    from . import metacognition
    cal = metacognition.calibration(cg)
    if not cal.get("ok"):
        return {"ok": False, "reason": cal.get("reason") or "insufficient_data",
                "calibration": cal, "applied": False, "n_adjusted": 0,
                "hint": "先 verify() 积累证据，校准才有样本"}
    gap = float(cal.get("gap") or 0.0)
    offset = round(max(-float(max_offset), min(float(max_offset), -gap)), 4)
    bins_bias = []
    for b in cal.get("bins") or []:
        if b.get("accuracy") is None:
            continue
        bins_bias.append({"bin": b["bin"], "n_nodes": b["n_nodes"],
                          "confidence": b["confidence"],
                          "accuracy": b["accuracy"],
                          "bias": round(float(b["confidence"])
                                        - float(b["accuracy"]), 4)})
    bins_bias.sort(key=lambda x: -abs(x["bias"]))
    adjusted = skipped = 0
    if apply and abs(offset) > 1e-9:
        adjusted, skipped = _apply_offset(cg, offset, override=override,
                                          min_evidence=min_evidence)
        _log(cg, "calibrate", ok=True, offset=offset, gap=gap,
             adjusted=adjusted, actor=actor)
    blind = 0
    try:
        blind = int(metacognition.blindspots(cg, limit=1)
                    .get("unresolved_count") or 0)
    except Exception:
        pass
    return {"ok": True, "verdict": cal.get("verdict"), "gap": gap,
            "expected_accuracy": cal.get("expected_accuracy"),
            "actual_accuracy": cal.get("actual_accuracy"),
            "ece": cal.get("ece"), "n_nodes": cal.get("n_nodes"),
            "suggested_offset": offset, "applied": bool(apply),
            "n_adjusted": adjusted, "skipped_protected": skipped,
            "bins_bias": bins_bias[:MAX_BINS_REPORT], "blindspots": blind,
            "hint": ("整体偏过度自信" if gap > 0.05 else
                     "整体偏保守" if gap < -0.05 else "校准良好")}


# --------------------------------------------------------------------------
# 一轮完整自净 + 审计
# --------------------------------------------------------------------------

def sweep(cg, *, n: int = DEFAULT_SAMPLE, seed=None, dry_run: bool = True,
          hops: int = DEFAULT_HOPS, strategy: str = "stratified",
          apply_calibration: bool = False, actor=None) -> dict:
    """一轮自净闭环：抽查 → 联想 → 体检 → 去污染 → 校准偏差。"""
    smp = sample(cg, n, strategy=strategy, seed=seed)
    ids = [s["node_id"] for s in smp["sample"]]
    assoc = {}
    for nid in ids[:8]:
        assoc[nid] = [r["node_id"] for r in associate(
            cg, nid, hops=hops, lexical=False, limit=5)["related"]]
    dec = decontaminate(cg, ids, dry_run=dry_run, hops=hops, actor=actor)
    rep = dec["audit"]
    cal = calibrate(cg, apply=apply_calibration, actor=actor)
    hi = [i for i in rep["issues"] if i["severity"] in ("high", "medium")]
    out = {"ok": not hi, "dry_run": dry_run, "n_high_medium": len(hi),
           "sample": smp, "associate": assoc, "audit": rep,
           "decontaminate": dec, "calibration": cal, "t": time.time()}
    _log(cg, "sweep", n_sample=smp["n"], n_issues=rep["n_issues"],
         n_high_medium=len(hi), applied=dec["applied"], dry_run=dry_run,
         calibration=(cal.get("verdict") if cal.get("ok")
                      else cal.get("reason")))
    return out


def history(cg, limit: int = 100) -> dict:
    recs = list(read_jsonl(os.path.join(cg.root, SCRUB_LOG)))
    return {"n": len(recs), "records": recs[-int(limit):]}


def summary(cg) -> dict:
    """给 health_os / 自维持循环用的只读摘要。"""
    recs = list(read_jsonl(os.path.join(cg.root, SCRUB_LOG)))
    sweeps = [r for r in recs if r.get("op") == "sweep"]
    decs = [r for r in recs if r.get("op") == "decontaminate" and r.get("ok")]
    last = sweeps[-1] if sweeps else None
    return {"sweeps": len(sweeps), "decontaminated": len(decs),
            "last_sweep": ({"t": last.get("t"),
                            "n_issues": last.get("n_issues"),
                            "n_high_medium": last.get("n_high_medium"),
                            "applied": last.get("applied"),
                            "dry_run": last.get("dry_run"),
                            "calibration": last.get("calibration")}
                           if last else None)}


def catalog() -> dict:
    return {"actions": ["sample", "associate", "audit", "decontaminate",
                        "calibrate", "sweep", "history", "summary", "catalog"],
            "strata": list(STRATA),
            "contamination": {k: {"severity": v[0], "actions": list(v[1])}
                              for k, v in CONTAMINATION.items()},
            "thresholds": {"stale_days": STALE_DAYS,
                           "unverified_days": UNVERIFIED_DAYS,
                           "low_conf": LOW_CONF,
                           "orphan_importance": ORPHAN_IMPORTANCE,
                           "max_offset": MAX_OFFSET}}
