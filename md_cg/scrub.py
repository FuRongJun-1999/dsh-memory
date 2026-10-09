# -*- coding: utf-8 -*-
"""md_cg · 记忆自净（记忆 OS #5）：抽查 / 联想 / 去污染 / 校准偏差

自维持（`sustain.py`）解决「进程还活着」，本模块解决「记忆还干净」。
四件事构成一个闭环，挂在常驻循环上周期性跑：

① **记忆抽查（sample）**
   分层抽样而非随机抽样：风险层（陈旧 / 低置信 / 有反例 / 从未验证 / 孤立）
   + 对照组（高频 / 随机基线）。对照组是刻意的——只查「看起来有问题」的节点
   会形成确认偏差，永远发现不了「看起来没问题其实有问题」的记忆。
   `seed` 固定 → 同 seed 同样本（可复现、可审计，对齐本仓确定性白箱取向）。

**issue #66 的两条口径（2026-10-09 DSH 端落文档，zcode 端裁定「一甲二乙」）**：

* **seed（子项二·乙：可注入、默认仍 0）**：sample() 的 seed 本就是可注入参数
  （sample(..., seed=None)，:280 seed = 0 if seed is None else seed）——**不传即 0**，
  与既有读数逐字一致；显式传入才轮换。故「抽样面不轮换」不是缺陷，而是**默认取向**：
  可复现、可审计对齐确定性白箱。_pick 另有已核实结论（:252-255）：层内候选 <= k 时**全量抽取**，
  单节点分层每轮必中属**有意设计**（该层全部人口＝全量覆盖）；**seed 轮转只让大池层换人**，
  小分层恒中占少数名额，且账本上可由 already_handled 如实读出。
* **幂等账本（子项一·甲：维持现口径）**：_handled **只认 SCRUB_LOG 里 op=="decontaminate"
  且 ok 为真的「改过的单条记录」**——批量汇总只是**读数**，不是处置凭证。
  这是把「审计即状态」收窄成「**实际改动才是状态**」，属**刻意口径**，不是漏配：
  跑过一轮但没动的条目**下轮仍会报**，那是设计意图（持续观察），不是重复劳动。
  ⇒ 使用者若期望「跑过就不再报」，应改看 already_handled 读数，而非期望幂等名单增长。

**issue #67（2026-10-09 DSH 端）**：_pick 的 3k 截断**只对有序池成立**；对照组
（random 池，_pool_candidates 唯一不排序者）此前同样被截断 ⇒「随机基线」退化成
「索引前 3k 名」。现由 ordered 形参区分：风险层截断不变，对照组取全池。

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

from . import forgetting, nodefile, protect
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
    # 未生效（双时间轴另一侧，2026-09-19）：**不是错误**——只提示「此刻不适用」，
    # 故 severity=info、处置仅 hint（不 weaken / 不 demote / 不删）。
    "not_yet": ("info", ("hint",)),
    "duplicate": ("medium", ("hint",)),
    "orphan_noise": ("low", ("weaken", "demote")),
    "unverified": ("info", ("hint",)),
}
SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1, "info": 0}


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------

# 生效条件：当 cg 的 index 为真且其 "nodes" 为真时返回该值，否则（cg 无 index、index 为假值、缺 "nodes" 或 "nodes" 为假值）返回 {}；
def _nodes(cg) -> dict:
    return (getattr(cg, "index", None) or {}).get("nodes") or {}


# 生效条件：cg 与 nid 传入后，若 cache 非 None 且 nid 已在 cache 中则直接返回 cache[nid]（即使其值为假值）；否则尝试 cg.get(nid)，异常或返回假值时按空节点处理，再取其中的 "frontmatter" 真值，若为假值则用 {}；cache 非 None 时把结果写入 cache[nid] 后返回；
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


# 生效条件：cg.access_counts() 调用成功时返回其结果（访问次数, 最后访问时间）；调用抛出任何 Exception 时返回 ({}, {})；
def _access(cg):
    """(访问次数, 最后访问时间)：读访问日志，未 compact 的也算。"""
    try:
        return cg.access_counts()
    except Exception:
        return {}, {}


# 生效条件：`from . import chain` 成功且 chain.adjacency(cg, skip_archived=False) 正常返回时返回该 dict，导入或调用抛任何异常时返回 {}。
def _adjacency(cg) -> dict:
    try:
        from . import chain
        # 维护面全量口径（2026-10-06 退役接线批次）：去污染抽查是维护写面，
        # 退役节点仍可被抽查 ⇒ 显式旁路退役过滤（度数口径与接线前逐位一致）。
        return chain.adjacency(cg, skip_archived=False)
    except Exception:
        return {}


# 生效条件：float(ts or 0) 抛 TypeError/ValueError 时返回 0.0，转换后为 0（含 ts 为 0/空串/None 等假值）时返回 0.0，否则返回 (now - ts)/86400.0。
def _days(ts, now) -> float:
    try:
        ts = float(ts or 0)
    except (TypeError, ValueError):
        return 0.0
    return (now - ts) / 86400.0 if ts else 0.0


# 生效条件：调用即返回带 t 与 op 的 rec；写 append_jsonl(os.path.join(cg.root, SCRUB_LOG), rec) 抛任何异常都被吞掉，不影响返回值。
def _log(cg, op: str, **rec) -> dict:
    rec = dict(rec, t=time.time(), op=op)
    try:
        append_jsonl(os.path.join(cg.root, SCRUB_LOG), rec)
    except Exception:
        pass
    return rec


# 生效条件：仅当 read_jsonl(cg.root 下 SCRUB_LOG) 的记录 op=="decontaminate" 且 ok 为真时，把 (rec.get("node_id"), rec.get("kind")) 收进返回集合；无此类记录返回空集。
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

# 生效条件：当 cg 的节点/访问/邻接数据可取时，对每个「layer 不在 SELF_LAYERS」的节点（源码仅以 `if layer in SELF_LAYERS: continue` 排除，未要求 layer 非空）按 now、stale_days、unverified_days 判定入池——last 访问时间距今≥stale_days 时入 stale，last 为假值且 created_at 距今≥stale_days 时入 stale，访问计数 acc≥3 入 hot，邻接度 deg==0 且 layer=="contextual" 入 orphan，evidence_count≤0 且 layer=="knowledge" 且 age_d≥unverified_days 入 unverified，evidence_count>0 且 reads<int(max_reads) 且 _fm_of 返回非空前台时按 negative_evidence>0 入 disputed、按 confidence<LOW_CONF（confidence 缺键回落 0.6）入 low_conf（max_reads 为 0 时 int(max_reads)=0，reads<0 恒假，故 disputed/low_conf 不产生），每个节点无条件入 random 池，最后按各池 key 排序返回 pools（片段仅见排序段，未展示抽样阶段）；多分支无法一句话覆盖全部分支。
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


# 生效条件：strategy=="random" 时直接返回 {"random": int(n)}；strategy=="risk" 时按剔除 hot/random 后的 STRATUM_WEIGHTS 权重分配；其它策略名走全权重分配，两者都把 int(n) 余量补进已存在的 random 键否则补进 stale。
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


# 生效条件：k<=0 或 pool 为假值（空池）时返回 []；否则 ordered 为真时先取池前 k*3 项（风险优先窗口），ordered 为假时**不截断**（无序池＝对照组 random，见 issue #67），随后一律用 random.Random(f"{seed}:{stratum}") 稳定洗牌并返回前 k 项（池长不足窗口时对全池洗牌）。
def _pick(pool, k: int, seed, stratum: str, *, ordered: bool = True):
    """从池中取 k 个：风险最高的 3k 个入池，再按 seed 稳定洗牌。

    层内候选 ≤ k 时**全量抽取**——单节点分层（如 low_conf 全库 1 个）
    因此每轮必中：这是**有意设计**（该层全部人口 = 全量覆盖，风险优先
    持续观察），不是漏配轮转。issue #66 核实：seed 轮转只让大池层换人，
    小分层恒中占少数名额、且账本上可由 `already_handled` 如实读出。

    issue #67（2026-10-09 DSH 端）：**对照组（random 池）不得截断**。_pool_candidates
    只对六个风险层排序（stale/hot/unverified/orphan/disputed/low_conf），random 池
    是**唯一不排序**的池；对它取 [:k*3] 等于把「随机基线」变成「索引前 3k 名」——
    对照面既非随机、又恒看不到后段人口，抽样结论无从代表全库。故 ordered=False。
    风险层保持截断**不变**：那是「风险优先窗口」的有意设计，不属本 issue 面。
    """
    if k <= 0 or not pool:
        return []
    cand = list(pool)
    if ordered and len(cand) > k * 3:
        cand = cand[:k * 3]
    random.Random(f"{seed}:{stratum}").shuffle(cand)
    return cand[:k]


# 生效条件：strategy 经 str(strategy or "stratified").lower() 后属于 stratified/risk/random 时返回带分层标签的样本（seed 为 None 时取 0，n 为 0 时 picked 为空），否则抛 ValueError。
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
        for nid, reason in _pick(pools.get(s), quota.get(s, 0), seed, s,
                                 ordered=(s != "random")):
            if nid in seen:
                continue
            seen.add(nid)
            picked.append({"node_id": nid, "stratum": s, "reason": reason})
    # 风险层不够时用随机池补足（先剔除已选，避免跳过造成不满额）
    if len(picked) < int(n):
        rest = [x for x in pools["random"] if x[0] not in seen]
        for nid, reason in _pick(rest, int(n) - len(picked), seed,
                                 "random-fill", ordered=False):
            seen.add(nid)
            picked.append({"node_id": nid, "stratum": "random",
                           "reason": reason})
    return {"ok": True, "strategy": strategy, "seed": seed, "n": len(picked),
            "strata": {s: len(pools.get(s) or []) for s in STRATA},
            "sample": picked, "t": now}


# --------------------------------------------------------------------------
# ② 联想
# --------------------------------------------------------------------------

# 生效条件：a 或 b 为假值（空集）时返回 0.0，否则返回 len(a & b)/len(a | b)。
def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# 生效条件：对 node_id 汇总关系链（chain.walk 出边与入边，max_depth=int(hops)）、子图层级（subgraph.expand 命中项与父索引逐级上溯 int(hops) 层）以及 lexical 为真时的词法近邻（只在 _nodes 前 int(max_scan) 个节点内比 bigram、sim≥min_sim 者），返回按 weight 降序的 items[:int(limit)]。
def associate(cg, node_id: str, *, hops: int = DEFAULT_HOPS, limit: int = 30,
              lexical: bool = True, min_sim: float = 0.25,
              max_scan: int = MAX_ASSOC_SCAN) -> dict:
    """三路邻域联想：关系链 + 子图层级 + 词法近邻。

    返回按权重降序的 `related`；每条带 `via`（哪一路发现）与 `weight`，
    便于审计「为什么把这两个节点算作同族」。
    """
    related = {}

# 生效条件：nid 为真且 nid != node_id 时，构造 rec={'node_id':nid,'via':via,'weight':round(float(weight),4),'depth':int(depth)} 并并入 extra；仅当 related 中 nid 不存在或 rec['weight'] 大于已有 weight 时更新 related[nid]；nid 为假或等于 node_id 时直接返回；
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

# 已结束键族（2026-09-19 阶段一：补规范名 `effective_until` 与冗余时刻 `expired_at`）。
# 纪律：`believed_at`（信念时间）**两族都不入**——它既不是「已结束」也不是「尚未开始」，
# 而是「体系何时确认此条」的取代/审核锚。键族真源见 md_cg/trust.py（FROM_ALIASES/UNTIL_ALIASES），
# 两侧新增键须同步（交叉守卫 test_validity_filter）。
_EXPIRY_KEYS = ("effective_until", "valid_until", "expires_at", "expire_at",
                "expiry", "deadline", "expired_at")
_SKIP_KEYS = ("功能名", "执行", "条件", "来源", "标签", "状态", "备注", "标题",
              "描述", "name", "id", "title", "layer", "tags", "说明")
_NEG_WORDS = ("禁止", "不得", "不要", "不能", "切勿", "避免", "不应", "不可")
_POS_WORDS = ("应当", "建议", "必须", "需要", "可以", "允许", "推荐", "宜")


# 生效条件：v 为 bool 返回 None；v 为 int/float 时仅 f>1e8 返回 f 否则 None；str(v or "").strip() 为空返回 None；否则按 "%Y-%m-%dT%H:%M:%S"/"%Y-%m-%d %H:%M:%S"/"%Y-%m-%d" 依次取前 19/19/10 字符尝试解析，全失败后再试 float(s)，>1e8 返回否则 None，float 亦失败返回 None。
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


# 生效条件：对 (content or "").splitlines() 的每行去 # 后，先试中文全角 "："、无则试 ":"，切出的键长度在 2–12、值非空且键不在 _SKIP_KEYS 时以 setdefault 记录（每键只留首次出现），无合格行返回 {}。
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
                # CCG 六要素行（`# 功能名：` / `# 不适用条件：` …）是**逐节点声明**，
                # 不是可跨节点比对的断言值。把「不适用条件」当键会让语义无关的节点
                # 互为「同键不同值」矛盾（实测 12 抽样里 9 条 high 全是这类误报，
                # 且 apply 会把好节点 weaken+demote 并跨层移动文件）。
                if (2 <= len(k) <= 12 and v and k not in _SKIP_KEYS
                        and not nodefile.is_ccg_mark(k)):
                    out.setdefault(k, v)
                break
    return out


# 生效条件：c 取 content or ""，含 _NEG_WORDS 任一返回 -1 分量、含 _POS_WORDS 任一返回 +1 分量，结果为两者之和（都不含时为 0）。
def _polarity(content) -> int:
    c = content or ""
    return (-1 if any(w in c for w in _NEG_WORDS) else 0) + \
           (1 if any(w in c for w in _POS_WORDS) else 0)


# 生效条件：按 _EXPIRY_KEYS 顺序遍历 fm，返回首个满足「键在 fm 中且 _to_ts 非 None 且 ts<now」的 (k, fm.get(k))；该键解析为 None 或 ts≥now 时继续检查后续键，全不满足返回 None。
def _expired(fm, now):
    for k in _EXPIRY_KEYS:
        if k in fm:
            ts = _to_ts(fm.get(k))
            if ts is not None and ts < now:
                return k, fm.get(k)
    return None


# 未生效键（双时间轴的起点，2026-09-19 · 真源 md_cg/trust.py）。
# 纪律一：`valid_from` **绝不并入 `_EXPIRY_KEYS`**——两者语义相反（「尚未开始」vs
# 「已经结束」），并入会让「未来才生效」被误判为「已失效」并触发 weaken/demote。
# 纪律二：`believed_at`（信念时间）同上，**两族都不入**——第三类语义（体系何时确认）。
_NOT_YET_KEYS = ("valid_from", "valid_since", "effective_from", "starts_at")


# 生效条件：按 _NOT_YET_KEYS 顺序遍历 fm，返回首个满足「键在 fm 中且 _to_ts 非 None 且 ts>now」的 (k, fm.get(k))；全不满足返回 None。
def _not_yet(fm, now):
    """宽松判定「尚未生效」（与 `_expired` 同口径，方向相反）。"""
    for k in _NOT_YET_KEYS:
        if k in fm:
            ts = _to_ts(fm.get(k))
            if ts is not None and ts > now:
                return k, fm.get(k)
    return None


# 生效条件：对 content 取 kv_pairs、bigrams 和 polarity，遍历 related（若 related 为假值则视为空）的前 int(max_compare) 个 r，以 r["node_id"] 调 cg.get；若某 oid 节点可读非空，先在其 content 与 content 的共同键中找到值不同者并返回 {'with':oid,'via':r.get('via'),'why':'同键不同值：...'}；否则若极性乘积 <0 且双方 bigram 非空，且共享 bigram 数 >=3 且 ratio>=0.15，返回 {'with':oid,'via':r.get('via'),'why':'极性相反且共享内容：...'}；全部遍历完无命中则返回 None；
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


# 生效条件：ids 在 node_ids 为 None 时取索引全部键、为 str 时取单元素列表、否则取 list(node_ids)，limit 为真值时截断为前 int(limit) 个；跳过 layer 在 SELF_LAYERS 的节点和 cg.get 取不到正文的节点，对剩余每个节点按 min_severity 门限累加 expired/unverified/orphan_noise/duplicate/contradiction，返回 ok=无 high 且无 medium 的结果。
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

# 生效条件：kind 是 CONTAMINATION 的键（否则 KeyError）且 CONTAMINATION[kind] 取出的 sev 在 SEVERITY_ORDER 中的值（缺键按 0）不小于闭包变量 min_severity 在 SEVERITY_ORDER 中的值（缺键按 0）时，把 {node_id, layer, kind, severity, detail, fix} 用 **extra 覆盖更新后追加到闭包 issues；sev 的值更小则直接 return 不追加（该函数无返回值）。
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

        # 双时间轴另一侧（2026-09-19）：尚未生效**不是错误**——只提示「此刻不适用」，
        # 处置由 CONTAMINATION["not_yet"] 定为 info 级 + 仅 hint（不 weaken / 不 demote）。
        ny = _not_yet(fm, now)
        if ny:
            add("not_yet", f"尚未生效：{ny[0]}={ny[1]}", evidence=ny[0])

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


# 生效条件：循环 max(1, int(times)) 次调用 cg.verify(nid, "scrub:"+kind+":"+str(detail)[:120], "weakened")，返回最后一次调用结果（times≤0 时按 1 次执行）。
def _weaken(cg, nid, kind, detail, times=1):
    res = None
    for _ in range(max(1, int(times))):
        res = cg.verify(nid, f"scrub:{kind}:{str(detail)[:120]}", "weakened")
    return res


# 生效条件：kinds 为真且 issue 的 kind 不在其中则跳过；kind 为 duplicate/unverified 记 hint，已出现在 _handled 记 skip，protect.is_protected 为真且 override 为假记 skip_protected，dry_run 为真记 planned；仅 dry_run 为假时对余下 issue 执行 _weaken，并在 demote 为真、severity 为 high 或 low 且当前层非 contextual 时降级到 contextual，返回计数与 actions。
def decontaminate(cg, node_ids=None, *, kinds=None, dry_run: bool = True,
                  min_severity: str = "medium", hops: int = 1, actor=None,
                  override: bool = False, weaken_times: int = 1,
                  demote: bool = True) -> dict:
    """按体检结果处置污染。**默认 dry_run**；实修只做可逆动作。

    动作：`weaken`（verify weakened → 反例+1、置信-0.15、跌破 0.2 自动降级）、
    `demote`（降级到情境层）、`hint`（只建议，不改）。保护节点跳过；永不删除。

    读数口径（issue #66）：`already_handled` = 命中幂等名单（此前已处置过，
    旧键 `skipped_done` 即此含义——不是「检查并跳过」）；`planned_dry_run`
    = 本轮检查到、但本轮无任何处置动作（dry_run 登记计划未执行；实修恒 0）；
    两者与 `applied` / `skipped_protected` / `hints` 构成逐条去向的互斥分类
    （`checked_breakdown`，仅读数，不回喂 `_handled`）。
    """
    rep = audit(cg, node_ids, hops=hops, min_severity=min_severity)
    handled = _handled(cg)
    actions = []
    n_applied = n_prot = n_done = n_hint = n_planned = 0

    for issue in rep["issues"]:
        nid, kind = issue["node_id"], issue["kind"]
        if kinds and kind not in kinds:
            continue
        # 只给建议的动作必须按 CONTAMINATION 的**声明**判定，不能靠 kind 白名单：
        # `not_yet` 声明 fix=("hint",)，原实现只排除 duplicate/unverified，
        # 于是它会落到 _weaken 分支（实测 min_severity="info" 时 confidence
        # 0.6→0.45、negative_evidence 0→1），声明与实修不一致。
        _declared = CONTAMINATION.get(kind, (None, ()))[1]
        if kind in ("duplicate", "unverified") or _declared == ("hint",):
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
            n_planned += 1
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
                    # 层降级 = 生命周期降级（②）：状态同批推进（负路由，失败不抛）
                    _st = cg.set_state(nid, "demoted", reason=f"scrub:{kind}",
                                       actor=actor or "scrub")
                    done.append("demote" if _st.get("ok") else
                                f"demote_state:{_st.get('error')}")
            except Exception as exc:                      # noqa: BLE001
                done.append(f"demote_failed:{type(exc).__name__}")
        n_applied += 1
        _log(cg, "decontaminate", node_id=nid, kind=kind, ok=True,
             actions=done, severity=issue["severity"], actor=actor)
        actions.append({"node_id": nid, "kind": kind, "action": "applied",
                        "done": done, "detail": issue["detail"],
                        "applied": True})

    # 覆盖账（issue #66）：逐条去向的**互斥分类**（五键之和 = 本轮处置循环的
    # issue 条数，kinds 过滤者除外），**只用于读数**——不回喂 `_handled`
    # （幂等账本仍只认「改过」的单条记录，读法见 `_handled`）。
    #   applied           本轮实际执行了处置动作（weaken/demote）
    #   already_handled   命中幂等名单（此前已处置过）→「旧面孔」。
    #                     旧键 `skipped_done` 的**实际含义就是它**——不是「检查
    #                     过并跳过」，正名于此（旧键保留兼容，值恒等）。
    #   planned_dry_run = dry_run 下**本会处置、因 dry_run 未遂**（**≠「无需处置」**；
    #                     「无需处置」由 hint 一格承载）（原写「无任何处置动作」易误读，
    #                     计划未执行）→「本轮检查面」。实修恒 0：检查出的可
    #                     处置问题都会动手。它与 `already_handled` 语义相反：
    #                     一个数「本轮新检查」，一个数「此前已处置（幂等存量）」。
    #   protected         受保护跳过（`protect.is_protected` 拦下）
    #   hint              声明只给建议（duplicate/unverified/not_yet，不动手）
    breakdown = {"applied": n_applied, "already_handled": n_done,
                 "planned_dry_run": n_planned, "protected": n_prot,
                 "hint": n_hint}
    if not dry_run:
        _log(cg, "decontaminate_batch", ok=True, applied=n_applied,
             # 覆盖账（issue #66）：分类明细只读数不回喂 `_handled`；
             # `already_handled` 为 `skipped_done` 的正名（二者恒等）。
             already_handled=n_done, planned_dry_run=n_planned,
             skipped_protected=n_prot, skipped_done=n_done, hints=n_hint,
             checked_breakdown=breakdown, actor=actor)
    return {"ok": True, "dry_run": dry_run, "n_issues": rep["n_issues"],
            "applied": n_applied, "skipped_protected": n_prot,
            # 正名（issue #66）：`skipped_done` = 命中幂等名单，**非「检查并跳过」**；
            # 兼容键保留（值恒等），新读数请用 `already_handled`。
            "already_handled": n_done, "skipped_done": n_done,
            "planned_dry_run": n_planned,
            "hints": n_hint, "actions": actions,
            "checked_breakdown": breakdown,
            "audit": rep, "t": time.time()}


# --------------------------------------------------------------------------
# ④ 校准偏差
# --------------------------------------------------------------------------

# 生效条件：对 cg 中每个「layer 不在 SELF_LAYERS」且 evidence_count≥int(min_evidence)（min_evidence=0 时该比较恒假而不早退）的节点，若 protect.is_protected 为假或 override 为真，且 cg.get(nid) 未抛异常并返回真值节点，则先以节点真层/敏感度过 protect.guard_overwrite（层闸 + 保护闸，override 为真时先快照 + 审计，越权抛 AccessDenied 且整批中止），再取 fm.get("confidence", 0.6)（缺键才回落 0.6，键存在为 None/假值不回落）为 old，算出 round(max(0.0, min(0.99, old+float(offset))),4)，与 old 差<1e-9 时跳过，否则写 fm["confidence"] 与 fm["calibration"] 并调用 cg._write_node，成功后置 cg._dirty[nid]=e（**标脏**：推进读缓存代际与索引增量日志）并 adjusted+1（写回异常被吞掉不计数），返回 (adjusted, skipped)，其中 skipped 只累计「layer 属 SELF_LAYERS」或被 protect 拦下且非 override 的节点。
def _apply_offset(cg, offset, *, override=False, min_evidence=1, actor=None):
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
        # N222（2026-09-28，同族未接线写点）：本函数是 calibrate 落库动作，此前
        # 直调 `cg._write_node` 改写**全库** `layer∉(self,anchor)` 且
        # `evidence_count≥1` 节点的 confidence/calibration——不过 principal 层写
        # 白名单、不过引擎级保护闸、`override` 形参直通（含 importance≥0.7 的
        # 不可遗忘节点），无快照无审计。持 sustain 令牌（`tokens.py:190`
        # `layers_allow=('self',)`）即可改 knowledge 层节点置信度（实测
        # `n_adjusted=5`，0.8→0.95；`override=True` 再 +1）。落盘前统一过
        # `protect.guard_overwrite`：层/敏感度取**节点 fm 真值**（不信索引缓存），
        # 解析与层闸由 `protect.require_layer` 单点承担，越权即 AccessDenied
        # 整批中止（fail-closed，不静默跳过——否则越权面被伪装成「无可校准节点」）；
        # `override=True` 走同一闸的显式放行分支（快照 + `_protected_audit.jsonl`）。
        protect.guard_overwrite(cg, nid, layer=fm.get("layer"),
                                sensitivity=fm.get("sensitivity"),
                                override=override, actor=actor)
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
            # 标脏（N133 修复，对照先例 md_cg/mdcg.py 的 update_tags / verify
            # 直写分支 `self._dirty[node_id] = e`）：本函数原先写盘后**完全不
            # 碰索引**（条目字段集不含 confidence，无需同步），但正因如此
            # path_gen 不推进 ⇒ 读缓存（默认开）把写盘前的旧 fm 判新鲜——
            # 同进程「calibrate 后读」拿旧 confidence（其余两处同族写点
            # forgetting.reinforce / insight.verify 同批补标脏）。标脏同时
            # 让本写进 `_dirty → flush → _index_log` 重放。**不下沉进
            # `_write_node`**：该口另有「只对账索引不落盘」的调用方，下沉会
            # 凭空产生写入代际与自重载。
            _dirty = getattr(cg, "_dirty", None)
            if isinstance(_dirty, dict):
                _dirty[nid] = e
            adjusted += 1
        except Exception:                                 # noqa: BLE001
            pass
    return adjusted, skipped


# 生效条件：cg 和 apply/override/actor/max_offset/min_evidence 传入后，若 metacognition.calibration(cg) 返回 ok 假，则返回 {'ok':False,'reason':cal.get('reason') or 'insufficient_data',...}；若 ok 真，则用 gap=float(cal.get('gap') or 0.0) 和 max_offset 计算 offset=round(max(-max_offset,min(max_offset,-gap)),4)，对 cal.get('bins') or [] 中 accuracy 非 None 的 bin 生成 bins_bias 并排序；仅当 apply 为真且 abs(offset)>1e-9 时调用 _apply_offset(cg,offset,override=override,min_evidence=min_evidence) 并写日志，最后返回 ok True 及 verdict/gap/建议 offset 等字段；
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
                                          min_evidence=min_evidence,
                                          actor=actor)
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

# 生效条件：cg 与 n/seed/dry_run/hops/strategy/apply_calibration/actor 传入后，按 n 与 strategy、seed 调 sample；对 sample 结果前 8 个 node_id 按 hops 调 associate；按 dry_run/hops/actor 调 decontaminate；按 apply_calibration/actor 调 calibrate；若 decontaminate 的 audit.issues 中存在 severity 为 high 或 medium 的项则 out.ok 为 False，否则为 True，并返回含 sample/associate/audit/decontaminate/calibration/t 的 out；
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
         # 覆盖账（issue #66）：轮级读数也带逐条去向分类——dry_run 轮是常驻
         # 默认下**唯一的账**（批量记录仅在实修轮写），不带则「三个旧面孔 +
         # 一个新问题」与「四个全新问题」在 last_sweep 读数上不可区分。
         already_handled=dec["already_handled"],
         planned_dry_run=dec["planned_dry_run"],
         checked_breakdown=dec["checked_breakdown"],
         calibration=(cal.get("verdict") if cal.get("ok")
                      else cal.get("reason")))
    return out


# 生效条件：返回 cg.root 下 SCRUB_LOG 的全部记录条数 n 与 recs[-int(limit):]（limit=0 时切片为 recs[0:] 即返回全部记录）。
def history(cg, limit: int = 100) -> dict:
    recs = list(read_jsonl(os.path.join(cg.root, SCRUB_LOG)))
    return {"n": len(recs), "records": recs[-int(limit):]}


# 生效条件：读取 cg.root 下 SCRUB_LOG 的 JSONL 记录，过滤 op=="sweep" 得 sweeps、op=="decontaminate" 且 ok 为真得 decs、op=="decontaminate_batch" 且 ok 为真得 batches；last 为 sweeps 最后一项或 None；返回 {'sweeps':len(sweeps),'decontaminated':batches 的 applied 累计,'decontaminated_records':len(decs),'batches':len(batches),'last_sweep':last 的 t/n_issues/n_high_medium/applied/dry_run/already_handled/planned_dry_run/checked_breakdown/calibration 或 None}；
def summary(cg) -> dict:
    """给 health_os / 自维持循环用的只读摘要。

    `decontaminated`（issue #66 口径修正）= 批量汇总记录的**累计 applied 之和**
    ——「实际处置量」；原口径（`op="decontaminate"` 单条记录条数）另留
    `decontaminated_records`，`batches` 为批量轮数——三键并置，信息不丢。
    """
    recs = list(read_jsonl(os.path.join(cg.root, SCRUB_LOG)))
    sweeps = [r for r in recs if r.get("op") == "sweep"]
    decs = [r for r in recs if r.get("op") == "decontaminate" and r.get("ok")]
    batches = [r for r in recs if r.get("op") == "decontaminate_batch"
               and r.get("ok")]
    last = sweeps[-1] if sweeps else None
    return {"sweeps": len(sweeps),
            "decontaminated": sum(int(r.get("applied") or 0) for r in batches),
            "decontaminated_records": len(decs),
            "batches": len(batches),
            "last_sweep": ({"t": last.get("t"),
                            "n_issues": last.get("n_issues"),
                            "n_high_medium": last.get("n_high_medium"),
                            "applied": last.get("applied"),
                            "dry_run": last.get("dry_run"),
                            # 覆盖账（issue #66）：轮读数可区分「旧面孔/新检查」；
                            # 旧记录无此键 → None（向后兼容读数）。
                            "already_handled": last.get("already_handled"),
                            "planned_dry_run": last.get("planned_dry_run"),
                            "checked_breakdown": last.get("checked_breakdown"),
                            "calibration": last.get("calibration")}
                           if last else None)}


# 生效条件：无入参调用即返回固定的 actions 列表、STRATA 列表、CONTAMINATION 映射（每项取 severity 与 actions）与 STALE_DAYS/UNVERIFIED_DAYS/LOW_CONF/ORPHAN_IMPORTANCE/MAX_OFFSET 阈值字典。
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