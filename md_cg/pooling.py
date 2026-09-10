# -*- coding: utf-8 -*-
"""召回分池与降权（G8-§七）：让「索引/产物类节点」不再吃全局截断额度。

**缺口**：`search()` 的 T2/T3 用单条全局额度 `GLOBAL_CAP` 截断候选。库里有大量
**索引/产物类节点**（`code_` 代码索引、`doc_` 文档索引；真实库实测 1813 条，占知识层
约 30%）。它们词面上更容易命中查询词，于是在截断点**先把真正的知识节点挤掉**——
表现为「召回看起来有 20 条，但全是索引条目」。

**做法**：把截断额度**显式分池**（不是提高额度）：
  · 每个池有 `cap_ratio`（额度占比，**各池之和必须 == 1.0**）与 `weight`（打分乘数）；
  · 截断时按池各取其额度，池内保持原有排序；打分时按池乘 `weight`（降权是可复算的显式系数）。

**四条纪律（对齐 §七 硬约束）**
  1. **不隐性提高上限**：`cap_ratio` 之和必须恰为 1.0（`validate()` 校验，误差 1e-9），
     任一分池的额度都不来自「额外预算」；分池只重分配，不创造。空池的**未用额度**按
     池序回流给前序池（`backflow=True`）——搬的仍是这 `total` 之内的额度，总账不增。
  2. **降权必须显式可复算**：权重只写在 `WEIGHTS`（或调用方传入的表）里，不藏在打分公式；
     `plan()` 输出完整系数供 A/B 复算。
  3. **默认关闭**：`pools=None` 即**原行为**（`GLOBAL_CAP` 平截），不动默认参数——
     是否启用属载体侧决策；启用需显式传表。
  4. **口径先冻结再复测**：`measure()` / `compare()` 用同一口径（P95 `scanned` +
     截断率 + 截断损失率）在**同一查询集**上跑前/后，差值即副作用；
     `bench_queries()` 从索引确定性取样（自问自答 → 结果标 `proxy=true`，不当判定结论）。

零第三方依赖。
"""
from __future__ import annotations

import math
import os

POOL_KNOWLEDGE = "knowledge"
POOL_INDEX = "index"
POOL_NEGATIVE = "negative"
#: 池序固定 → 截断结果可复现（不依赖 dict 迭代顺序）
POOL_ORDER = (POOL_KNOWLEDGE, POOL_INDEX, POOL_NEGATIVE)

#: 索引/产物类节点的 id 前缀（§七 实测口径：code_ 代码索引 / doc_ 文档索引）
INDEX_PREFIXES = ("code_", "doc_")
#: 负记忆层（rejected/unresolved）：参与召回但应让位于事实/规则
NEG_LAYERS = ("rejected", "unresolved")

#: 显式权重表：cap_ratio 各池之和必须 == 1.0（不隐性提高上限）；weight 为打分乘数
WEIGHTS = {
    POOL_KNOWLEDGE: {"cap_ratio": 0.70, "weight": 1.00, "desc": "事实/规则，主召回池"},
    POOL_INDEX:     {"cap_ratio": 0.20, "weight": 0.60, "desc": "索引/产物（code_/doc_），降权"},
    POOL_NEGATIVE:  {"cap_ratio": 0.10, "weight": 0.90, "desc": "负记忆，参与但不压制正记忆"},
}

#: 载体侧总开关（默认关；`pools` 显式给出时优先于本变量）
ENV_SWITCH = "MDCG_POOLING"

_RATIO_EPS = 1e-9


class PoolError(ValueError):
    """分池配置非法（额度之和不为一 / 池名缺失 / 系数非正）。"""


# --------------------------------------------------------------------------
# 分类 / 校验 / 计划
# --------------------------------------------------------------------------

def resolve(pools):
    """把 `pools` 参数解成生效配置：None→关闭；True→内置表；dict→校验后副本。"""
    if pools is None or pools is False:
        return None
    if pools is True:
        pools = WEIGHTS
    return validate(pools)


def pool_of(node_id, entry=None) -> str:
    """节点归池（确定性、只看 id 前缀 / 层 / 标签，不读文件）。"""
    e = entry or {}
    if str(e.get("layer") or "") in NEG_LAYERS:
        return POOL_NEGATIVE
    nid = str(node_id or "")
    if nid.startswith(INDEX_PREFIXES):
        return POOL_INDEX
    tags = [str(t).lower() for t in (e.get("tags") or [])]
    if any(t in ("index", "artifact", "code_index", "doc_index") for t in tags):
        return POOL_INDEX
    return POOL_KNOWLEDGE


def validate(pools) -> dict:
    """校验并归一化权重表（**硬约束：额度之和必须恰为 1.0**）。"""
    if not isinstance(pools, dict):
        raise PoolError(f"分池表必须是 dict，得到 {type(pools).__name__}")
    missing = [p for p in POOL_ORDER if p not in pools]
    if missing:
        raise PoolError(f"分池表缺池：{missing}（必须齐备 {list(POOL_ORDER)}）")
    out, total = {}, 0.0
    for p in POOL_ORDER:
        spec = pools[p] or {}
        if not isinstance(spec, dict):
            raise PoolError(f"池 {p} 的配置必须是 dict")
        try:
            ratio = float(spec.get("cap_ratio"))
            weight = float(spec.get("weight", 1.0))
        except (TypeError, ValueError):
            raise PoolError(f"池 {p} 的 cap_ratio/weight 必须是数字")
        if ratio <= 0:
            raise PoolError(f"池 {p} 的 cap_ratio 必须 > 0（得到 {ratio}）")
        if weight <= 0:
            raise PoolError(f"池 {p} 的 weight 必须 > 0（得到 {weight}）")
        out[p] = {"cap_ratio": ratio, "weight": weight,
                  "desc": spec.get("desc") or WEIGHTS[p]["desc"]}
        total += ratio
    if abs(total - 1.0) > _RATIO_EPS:
        raise PoolError(f"cap_ratio 之和必须恰为 1.0（得到 {total:.9f}）"
                        f"——分池只重分配额度，不得隐性提高上限")
    return out


def caps(total: int, pools) -> dict:
    """按比例分配额度；**各池额度之和恰等于 total**。

    先每池保底 1（否则小额度下某一池会被完全饿死），余下按比例用
    **最大余数法**分配、同余数按池序 → 结果确定可复现；总账恒等于 total。
    额度太小（< 池数）时无法每池保底，全部给主池。
    """
    total = int(total)
    if total <= 0:
        return {p: 0 for p in POOL_ORDER}
    if total < len(POOL_ORDER):
        return {p: (total if p == POOL_KNOWLEDGE else 0) for p in POOL_ORDER}
    out = {p: 1 for p in POOL_ORDER}
    left = total - len(POOL_ORDER)
    raw = {p: left * float(pools[p]["cap_ratio"]) for p in POOL_ORDER}
    for p in POOL_ORDER:
        out[p] += int(math.floor(raw[p]))
    rem = total - sum(out.values())
    if rem > 0:                            # 余数优先给「小数部分最大」的池
        order = sorted(POOL_ORDER,
                       key=lambda p: (-(raw[p] - math.floor(raw[p])),
                                      POOL_ORDER.index(p)))
        for p in order[:min(rem, len(order))]:
            out[p] += 1
    return out


def plan(total: int, pools=None) -> dict:
    """分池计划（供审计 / A/B 复算）：额度 + 系数 + 是否启用。"""
    cfg = resolve(pools)
    if not cfg:
        return {"enabled": False, "total": int(total),
                "note": "分池关闭 → 原行为（GLOBAL_CAP 平截）"}
    c = caps(total, cfg)
    return {"enabled": True, "total": int(total), "caps": c,
            "weights": {p: cfg[p]["weight"] for p in POOL_ORDER},
            "cap_ratio": {p: cfg[p]["cap_ratio"] for p in POOL_ORDER},
            "cap_sum": sum(c.values()),
            "index_prefixes": list(INDEX_PREFIXES)}


def weight_of(node_id, entry=None, pools=None) -> float:
    """节点的打分乘数（未启用分池 → 1.0，保证原行为）。"""
    cfg = resolve(pools)
    if not cfg:
        return 1.0
    return float(cfg[pool_of(node_id, entry)]["weight"])


def allocate(docs, total: int, *, pools=None, key_of=None) -> list:
    """分池截断（只要结果；需要各池实取数用 `take()`）。未启用 → 平截（原行为）。

    `key_of(doc)` 需返回 `(node_id, entry)`；缺省则视 doc 为 `(id, entry)` 元组。
    输出顺序恒为「池序 + 池内原序」（与 `POOL_ORDER` 绑定，可复现）。
    """
    return take(docs, total, pools=pools, key_of=key_of)[0]


def _bucketize(docs, total: int, cfg, key_of, backflow: bool):
    """归池 + 分额 + 回流 → `(buckets, quota)`（`take` 与 `cut_report` 共用）。"""
    quota = caps(total, cfg)
    buckets = {p: [] for p in POOL_ORDER}
    for d in docs:
        nid, entry = key_of(d) if key_of else d
        buckets[pool_of(nid, entry)].append(d)
    if backflow:
        left = total - sum(min(len(buckets[p]), quota[p]) for p in POOL_ORDER)
        for p in POOL_ORDER:
            if left <= 0:
                break
            room = len(buckets[p]) - min(len(buckets[p]), quota[p])
            if room <= 0:
                continue
            add = min(room, left)
            quota[p] += add
            left -= add
    return buckets, quota


def take(docs, total: int, *, pools=None, key_of=None, backflow: bool = True):
    """分池截断并**回报各池实取数** → `(picked, taken)`。

    `backflow=True`：空池/候选不足的**未用额度按池序回流给更靠前的池**
    （knowledge ← index ← negative）。回流只搬「本来就没用掉的」额度，
    各池实取之和 **恒 ≤ total**，总账不增——不是隐性加预算，且规则显式、
    结果确定（同一输入必然同一输出）。
    """
    docs = list(docs or [])
    cfg = resolve(pools)
    if not cfg:
        return docs[:int(total)], {}     # 未启用 → 不报池账（别把平截伪装成分池）
    picked, report = cut_report(docs, total, pools=pools, key_of=key_of,
                               backflow=backflow)
    return picked, report["taken"]


def cut_report(docs, total: int, *, pools=None, key_of=None,
               backflow: bool = True):
    """同 `take`，但回报**完整池账** → `(picked, report)`。

    `report = {enabled, total, quota, cands, taken, lost}`：`cands` 为各池
    截断前候选数、`quota` 为计划额度（含回流）、`taken` 实取、`lost` 被挤掉
    （`max(0, cands - taken)`）。关闭态返回 `{enabled: False}`——不伪造池账。
    """
    docs = list(docs or [])
    total = int(total)
    cfg = resolve(pools)
    if not cfg:
        return docs[:total], {"enabled": False}
    buckets, quota = _bucketize(docs, total, cfg, key_of, backflow)
    picked, taken, cands, lost = [], {}, {}, {}
    for p in POOL_ORDER:
        got = buckets[p][:quota[p]]
        picked.extend(got)
        taken[p] = len(got)
        cands[p] = len(buckets[p])
        lost[p] = max(0, len(buckets[p]) - len(got))
    return picked, {"enabled": True, "total": total, "quota": dict(quota),
                    "cands": cands, "taken": taken, "lost": lost}


def cut(docs, total: int, *, pools=None) -> list:
    """检索 T2/T3 截断点专用：`docs = [(entry, fm, content)]`（只取结果）。"""
    return take(docs, total, pools=pools, key_of=doc_key)[0]


def record_audit(stat: dict, report) -> dict:
    """把 `cut_report` 的池账落进检索 `stat`（**关闭态不写** → 不伪造池账）。

    落 `pool_taken` / `pool_cands` / `pool_lost` 三个键，供 `_emit` 组装审计面。
    """
    if report and report.get("enabled"):
        stat["pool_taken"] = dict(report["taken"])
        stat["pool_cands"] = dict(report["cands"])
        stat["pool_lost"] = dict(report["lost"])
    return stat


def doc_key(d):
    """检索文档三元组 `(entry, fm, content)` → `(node_id, entry)`。"""
    return (d[1].get("id") or d[0]["path"]), d[0]


# --------------------------------------------------------------------------
# 口径冻结与复测（只读）
# --------------------------------------------------------------------------

def _pct(xs, q):
    """分位数（最近秩法，确定性；零依赖）。"""
    xs = sorted(float(x) for x in xs)
    if not xs:
        return 0.0
    idx = max(0, min(len(xs) - 1, int(math.ceil(q * len(xs))) - 1))
    return xs[idx]


def bench_queries(cg, n: int = 50) -> list:
    """从索引**确定性**取样查询词（按 id 排序等距抽，取节点标题行）。

    自问自答 → 结果只作**代理指标**（`proxy=true`），不得当判定结论。
    """
    ids = sorted((cg.index.get("nodes") or {}).keys())
    if not ids:
        return []
    step = max(1, len(ids) // max(1, int(n)))
    out = []
    for nid in ids[::step][:max(1, int(n))]:
        entry = cg.index["nodes"][nid]
        try:
            _fm, content = cg._read(entry)
        except Exception:                              # noqa: BLE001
            continue
        if not content:
            continue
        line = ""
        for raw in content.splitlines():
            if raw.strip().startswith("#"):
                line = raw.strip()
                break
        q = line.split("：", 1)[-1].strip() if "：" in line else line.lstrip("# ").strip()
        if q:
            out.append(q)
    return out


#: 复测差值覆盖的口径字段（前两组=系统成本口径；后两组=结果构成口径）。
#: 注意：P95/截断率是**分池不敏感**口径（分池在 GLOBAL_CAP 之内重分配，
#: 「候选数 > cap」事件不变 → 差值恒 0）；必须同时看 `index_share`/`pool_lost_rate`
#: 这类**敏感**口径，否则复测会「跑完却归因不到副作用」（见 §七·执行证据）。
DELTA_KEYS = ("p95_scanned", "p50_scanned", "mean_candidates",
              "truncation_rate", "truncation_loss",
              "index_share", "knowledge_share", "pool_lost_rate")


def _mean(xs):
    return (sum(xs) / len(xs)) if xs else 0.0


def _pool_counts(res) -> dict:
    """结果集的归池构成（对分池**敏感**的口径：索引类是否吃满召回）。"""
    out = {}
    for r in res or []:
        node = r[0] or {}
        p = pool_of(node.get("id"), node.get("frontmatter"))
        out[p] = out.get(p, 0) + 1
    return out


def measure(cg, queries=None, *, k: int = 20, pools=None, judge: bool = False,
            n_queries: int = 50) -> dict:
    """同口径跑一遍（**只读**）：系统成本口径 + 结果构成口径 + 池级截断损失。

    系统成本口径：P95/中位 `scanned`、**全局**截断率与截断损失率
    （截断率 = 候选数 > 全局额度 的查询占比；损失率 = 被截掉候选/候选总数均值）。
    结果构成口径：返回结果里索引/知识/负记忆池占比均值
    （**对分池敏感**——分池的意义就是改变入榜构成，成本口径看不出来）。
    池级截断损失 `pool_lost_rate`：各池 `被挤掉 / 候选` 的均值，**仅在启用态可得**，
    关闭态诚实为 `None`（关闭时不存在「池」这一层，不编造 0）。
    `record=False`：不污染访问计数（复测不产生副作用）。
    """
    qs = list(queries) if queries else bench_queries(cg, n=n_queries)
    scanned, trunc, loss, cands, tiers = [], [], [], [], {}
    idx, kn, neg, pooled_lost = [], [], [], []
    for q in qs:
        try:
            res, meta = cg.search(q, k=int(k), record=False, judge=judge,
                                  pools=pools)
        except Exception:                              # noqa: BLE001
            continue
        pre = meta.get("pre_cap")
        cap = meta.get("cap")
        if pre is None:
            pre, cap = (meta.get("candidates") or 0), (meta.get("cap") or 0)
        scanned.append(meta.get("scanned") or 0)
        cands.append(pre or 0)
        tiers[meta.get("tier")] = tiers.get(meta.get("tier"), 0) + 1
        if cap and pre > cap:
            trunc.append(1)
            loss.append(float(pre - cap) / float(pre))
        else:
            trunc.append(0)
            loss.append(0.0)
        pc = _pool_counts(res)
        tot = sum(pc.values())
        if tot:
            idx.append(pc.get(POOL_INDEX, 0) / tot)
            kn.append(pc.get(POOL_KNOWLEDGE, 0) / tot)
            neg.append(pc.get(POOL_NEGATIVE, 0) / tot)
        pl = meta.get("pools") or {}
        if pl.get("lost") and pl.get("cands"):
            d = sum(pl["cands"].values())
            if d:
                pooled_lost.append(sum(pl["lost"].values()) / d)
    n = len(scanned)
    return {"ok": True, "readonly": True, "proxy": True,
            "n_queries": n, "k": int(k),
            "pools": plan(meta_cap(cg), pools),
            "p95_scanned": _pct(scanned, 0.95),
            "p50_scanned": _pct(scanned, 0.50),
            "mean_candidates": _mean(cands),
            "truncation_rate": _mean(trunc),
            "truncation_loss": _mean(loss),
            "index_share": _mean(idx),
            "knowledge_share": _mean(kn),
            "negative_share": _mean(neg),
            "pool_lost_rate": _mean(pooled_lost) if pooled_lost else None,
            "tiers": tiers,
            "note": ("查询集自索引确定性取样（自问自答）→ proxy 指标；"
                     "P95/truncation_* 为分池不敏感口径（差值恒 0 属正常），"
                     "分池生效看 index_share / pool_lost_rate；"
                     "同口径前后对比只看方向与幅度，不当绝对结论")}


def meta_cap(cg) -> int:
    """读当前全局额度（避免硬编码漂移）。"""
    from . import mdcg
    return int(getattr(mdcg, "GLOBAL_CAP", 0) or 0)


def compare(cg, queries=None, *, k: int = 20, pools=None, n_queries: int = 50) -> dict:
    """§七 要求的「同口径复测」：关闭态 vs 启用态 一并给出 + 差值 + 副作用归因。"""
    qs = list(queries) if queries else bench_queries(cg, n=n_queries)
    before = measure(cg, qs, k=k, pools=None, n_queries=n_queries)
    after = measure(cg, qs, k=k, pools=(WEIGHTS if pools is None else pools),
                    n_queries=n_queries)
    delta = {key: round(after[key] - before[key], 6)
             for key in DELTA_KEYS
             if isinstance(before.get(key), (int, float))
             and isinstance(after.get(key), (int, float))}
    zero_keys = [k2 for k2, v in delta.items() if v == 0]
    return {"ok": True, "readonly": True, "n_queries": len(qs), "k": int(k),
            "before": before, "after": after, "delta": delta,
            "pool_plan": after["pools"],
            # 口径敏感性自检：分池不敏感的口径（系统成本）差值恒 0 是**正常**的，
            # 不报出来的话，复测看起来「毫无变化」会被误读为「改造无效」。
            "insensitive_keys": zero_keys,
            "sensitive_keys": [k2 for k2 in delta if k2 not in zero_keys],
            "attribution": ("index_share 下降=索引/产物类不再吃满召回（收益）；"
                            "pool_lost_rate 下降=各池被挤掉的候选变少（收益，仅启用态）；"
                            "p95/p50_scanned 上升=分池让更多候选进入打分（代价）；"
                            "全局 truncation_* 对分池不敏感、差值恒 0，不代表改造无效，"
                            "只说明该口径测不到池内重分配")}


def catalog() -> dict:
    """自描述（供 MCP / 人工核对）。"""
    return {"layer": "召回分池与降权（§七）",
            "pools": list(POOL_ORDER),
            "weights": {p: dict(WEIGHTS[p]) for p in POOL_ORDER},
            # 用 round 收掉二进制浮点噪声（0.7+0.2+0.1 == 0.9999999999999999）
            "cap_ratio_sum": round(sum(WEIGHTS[p]["cap_ratio"] for p in POOL_ORDER), 12),
            "index_prefixes": list(INDEX_PREFIXES),
            "neg_layers": list(NEG_LAYERS),
            "default": "off（pools=None → 原 GLOBAL_CAP 平截，不改默认参数）",
            "discipline": {"no_hidden_budget": "cap_ratio 之和必须 == 1.0",
                           "explicit_weights": "降权系数只来自显式表，可 A/B 复算",
                           "opt_in": "默认关闭，启用需显式传表",
                           "measured_first": "先冻结 P95/截断率，再同口径复测",
                           "caliber_sensitivity": ("复测口径须自检对改造敏感："
                                                   "P95/全局截断率对分池不敏感（差值恒 0），"
                                                   "须并看 index_share / pool_lost_rate")},
            "backflow": ("空池未用额度按池序回流前序池；总账恒 ≤ total，"
                         "taken 字段回报各池实取数"),
            "env": {ENV_SWITCH: "设为 1 时 search/mdcg_search 默认启用内置分池表"},
            }


def from_env(pools=None):
    """载体侧开关：`pools` 显式给出时优先；否则读 `MDCG_POOLING`（默认关）。"""
    if pools is not None and pools is not False:
        return pools
    v = (os.environ.get(ENV_SWITCH) or "").strip().lower()
    if v in ("1", "on", "true", "yes", "y"):
        return True
    return None
