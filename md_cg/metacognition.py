# -*- coding: utf-8 -*-
"""独立元认知（Metacognition）——观察自身认知过程的二阶单元。

理论出处（本仓原文，非外部知识）
------------------------------
· **情绪 = 信息差的二阶变化 d²D/dt²**（`docs/theory/智能的公理化基石.md` §十一，:412-510）：
      「情绪不是状态本身，而是状态变化的变化」。元认知正是对认知过程做
      二阶观测的单元：一阶 = 检索结果好坏，二阶 = 认知状态在如何变化。
· **情感 = 信任的二阶变化 d²T/dt²**（同文档 :469-508）。
· **五大单元**（同文档 :540-556）：反思单元=新 / 验证单元=稳。
      元认知是这两条通道的**外部观察者**，自身不产出裁决。
· **推论三 局部不可知**（同文档 :277-288）：
      「知道什么不知道，同样属于知识」——盲区地图是法定输出，不是失败记录。
· **信任 P_trust / P_gap**（同文档 :393-408）。
· **导航税**（`docs/theory/智能的认知过程.md`:84-86）：维持认知过程一致性需要显式
      状态记录——元认知就是付这笔税的单元。

独立性的三重含义（本模块的硬约束）
--------------------------------
1. **不参与裁决**：只读留痕与索引，**不写** confidence / 资格 / 召回打分。
   对齐 `consistency.py` L0 情绪通道纪律：「独立通道，不参与信任计算」。
2. **独立留痕**：`_metacognition.jsonl`（append-only，每条可审计）。
3. **独立入口**：`report` / `self_check` 可被 MCP / Agent 单独调用。

四个观测面
----------
    trace        信息差轨迹 D(t) → dD/dt（方向）→ d²D/dt²（情绪）
    calibration  自信校准：期望正确率 vs 实际验证通过率（过度自信/过度保守）
    blindspots   盲区地图：反复 BLINDSPOT 的查询邻域 + 未解问题
    trust        P_gap（信息差置信）+ P_trust（验证稳定置信）+ d²T/dt²（情感）

诚实边界
--------
· 所有指标都是**留痕的聚合**，不是对「智能」的断言；样本不足返回
  `insufficient_data`，不编造数值。
· 建议是**确定性模板**（非 LLM 生成），每条都带触发它的证据（可复核）。
· 元认知**不修改事实层**——它只建议，执行权归调用方 / verify / forgetting。
"""

from __future__ import annotations

import hashlib
import os
import time
from collections import Counter

from .fsutil import append_jsonl, read_jsonl
from .security import visible_to

LOG_FILE = "_metacognition.jsonl"

# ---- 阈值（全部可审计、可调）----
GAP_OVERCONFIDENT = 0.15     # 过度自信：期望 - 实际 > 此值
GAP_UNDERCONFIDENT = -0.15   # 过度保守：期望 - 实际 < 此值
BLINDSPOT_DENSE = 0.30       # 盲区密集：BLINDSPOT 占比 >= 此值
D_LOW = 0.10                 # P_gap：D_norm < 此值视为「信息差已收敛」
MIN_SAMPLES = 5              # 样本不足 → insufficient_data
D2_EMOTION = 0.05            # 二阶变化显著阈值
BINS = ((0.0, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01))
#: issue #121（2026-10-11）：越界 confidence 的**抽样可追**上限——返回体给计数 +
#: 最多这么多个被丢弃 id（全量列表会随库增长无界膨胀；计数面恒完整，故不静默）。
DROPPED_SAMPLE_MAX = 20


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

# 生效条件：形参 d2 与模块常量 D2_EMOTION 比较——d2 > D2_EMOTION 返回 "avoiding"，d2 < -D2_EMOTION 返回 "approaching"，其余（含 |d2| 不超过阈值）返回 "stable"；
def _emotion(d2: float) -> str:
    """情绪：d²D/dt² 的符号（智能论 §十一）。"""
    if d2 > D2_EMOTION:
        return "avoiding"        # 信息差加速扩大
    if d2 < -D2_EMOTION:
        return "approaching"     # 信息差加速收敛
    return "stable"


# 生效条件：形参 q 经 str(q or "") 小写并仅保留字母数字字符得到 s 后，s[:n]（n 默认 16，n 为 0 等使前缀为空的取值时前缀为空串）非空则返回该前缀，否则（q 为假值、无字母数字字符或 n 为 0）返回 "(empty)"；
def _key(q, n: int = 16) -> str:
    """查询归一化键（用于盲区聚合 / 相似匹配）。"""
    s = "".join(ch for ch in str(q or "").lower() if ch.isalnum())
    return s[:n] or "(empty)"


# 生效条件：形参 s 经 str(s or "") 并剔除 strip() 为空的字符后长度为 0 时返回 set()，长度为 1 时返回 {s}，长度 ≥2 时返回 {s[i:i+2] for i in range(len(s)-1)}；
def _bigrams(s) -> set:
    s = "".join(ch for ch in str(s or "") if ch.strip())
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


# 生效条件：形参 a、b 经 _bigrams 处理后任一结果为空集（如 a 或 b 为空、仅含空白字符）时返回 0.0，否则返回两集合交集大小除以并集大小；
def _jaccard(a, b) -> float:
    A, B = _bigrams(a), _bigrams(b)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


# 生效条件：形参 s 经 str(s or "").encode("utf-8") 取 sha1 十六进制前 8 位返回（空串也有确定值）；
def _digest(s) -> str:
    """不可逆摘要（#445：台账不落查询原文，只落摘要）。

    与 `scrub.py` 的 payload-free 留痕同口径（sha1 前 8 位）：审计面可判
    「两次是不是同一段查询」，但不持有原文。**不是**加密强度——短查询可被
    字典比对，故本摘要**只入台账**，读面（self_check/blindspots/history 的
    非授权读者）连摘要也不返回（只回 similarity/states/计数）。
    """
    return hashlib.sha1(str(s or "").encode("utf-8")).hexdigest()[:8]


# 生效条件：cg 无 principal 属性（纯 MdCGOS，无身份/密级模型）时返回 True；principal.can_admin 为真时返回 True（设计者=全局观测本职，与 consistency_history/_readable 同款豁免）；否则记录自带 sensitivity 缺失/为空时返回 False（fail-closed：密级不可判即不可读，与 consistency_history「升级前无 sensitivity 键的旧记录一律去原文」同口径），sensitivity 为真值时要求 cg._readable 可调用并委派 security.visible_to(cg, rec)（= cg._readable：clearance × 密级 ∧ 会话绑定；**有 principal 却无判据载体 ⇒ 不可证可见 ⇒ False**，判据异常同样按不可见）。
def _can_read_record(cg, rec) -> bool:
    """台账记录的读可见性**单点**（#445/#426-D）。

    台账（`_reflection.jsonl` / `_metacognition.jsonl`）的记录里没有节点
    `path`，因此**不能**复用 `_readable` 的「密级缺失 → 回读盘面」分支；本
    函数只做三件事：无身份模型不设限、设计者豁免、其余按记录自带密级走
    `security.visible_to`（复用既有单点，不另写一份 rank/会话判据）。

    为什么要自己再判一次 `callable`：`security.visible_to` 在**无钩子**时按
    「不设限」返回 True（那是给纯 MdCGOS 的口径）；本函数走到这一步时已确认
    **有** principal，此时「没有判据载体」不等于「无越权可言」，而是「不可证
    可见」——按 fail-closed 返回 False（与 `node_visible` 的缺席处置同向）。
    """
    p = getattr(cg, "principal", None)
    if p is None:
        return True                       # 无身份模型：无「越权」可言
    if getattr(p, "can_admin", False):
        return True
    if not isinstance(rec, dict):
        return False                      # 非对象行：密级不可判 ⇒ fail-closed
    sens = str((rec or {}).get("sensitivity") or "").strip().lower()
    if not sens:
        return False                      # 密级不可判 ⇒ fail-closed（宁可少读）
    if not callable(getattr(cg, "_readable", None)):
        return False                      # 有身份模型但无判据载体 ⇒ 不可证可见
    return visible_to(cg, rec)


# 生效条件：rec 为 dict/None；返回其副本，并把 query/query_digest/query_len 三键一并摘除后置 query_redacted=True（无 query 键时原样复制、不加标记）；
def _redact_query(rec) -> dict:
    """读面去原文：低权读者只回 similarity/states/计数，不回落原文（#445）。

    `query_digest` 一并摘除：摘要虽不可逆，但对短查询构成**确认型旁路**
    （猜一句、比一次摘要），故只在台账落盘、不在读面透出。
    """
    if not isinstance(rec, dict):
        return rec                        # 非对象行原样（无可摘的键面）
    out = dict(rec or {})
    if "query" in out or "query_digest" in out or "query_len" in out:
        out.pop("query", None)
        out.pop("query_digest", None)
        out.pop("query_len", None)
        out["query_redacted"] = True
    return out


# 生效条件：形参 rec 被复制并 setdefault("t", time.time()) 后，向 os.path.join(cg.root, LOG_FILE) 追加写入抛 OSError 时静默跳过，两类情形均返回补过 t 的 rec 副本；cg.principal 存在且 can_write 为假时**不写盘**（只算不留痕，#426-D D3：不可写身份不得持久追加台账）；写入前把 query 原文换成 query_digest（sha1 前 8 位）+ query_len，台账不落原文（#445）。
def _log(cg, rec: dict) -> dict:
    """独立留痕（append-only）。失败不阻塞主流程。"""
    rec = dict(rec)
    rec.setdefault("t", time.time())
    # #445：台账只落「键名 + 不可逆摘要」，查询原文留在调用方上下文。
    # 先摘再判写闸：本函数的返回值也不得携带原文（同一判据不因分支顺序漂移）。
    if "query" in rec:
        _q = rec.pop("query")
        rec["query_digest"] = _digest(_q)
        rec["query_len"] = len(str(_q or ""))
        rec["query_redacted"] = True
    # #426-D D3：无写权限的身份（无令牌访客等）不得经 self_check/report
    # 持久追加台账——修前访客 10 次 self_check 把台账灌大 60KB。
    _p = getattr(cg, "principal", None)
    if _p is not None and not getattr(_p, "can_write", True):
        return rec
    try:
# #326-④：append_jsonl 不再上抛、以 False 报写失败——本处**仍容忍**（best-effort
# 簿记），但失败不再静默：源头已记 fsutil.APPEND_FAILURES + 有界 stderr 告警
# （B 面单点）。显式消费返回值：不留裸调用（守卫 AST 钉子会抓）。
        _ok = append_jsonl(os.path.join(cg.root, LOG_FILE), rec)
    except OSError:
        pass
    return rec


# 生效条件：形参 cg 的 reflection_log 属性缺失或为假值时回落到 os.path.join(cg.root, "_reflection.jsonl")，返回该路径 read_jsonl 结果中**读可见**的记录 list——逐条经 _can_read_record（无身份模型/设计者不设限；其余读者：缺 sensitivity 键 fail-closed 剔除、有密级经 security.visible_to 判 clearance × 会话绑定）；不可见记录**连计数都不进**（宁可少读）；
def _reflections(cg) -> list:
    """反思台账的**唯一读取点**（#445：可见性判据收在这里，不在各读面各写一份）。

    为什么把闸放在这里而不是各消费点：`_reflection.jsonl` 有**四个**读面——
    `trace` / `trust`（纯数值）、`blindspots` / `self_check`（带 query 文本）、
    `autonomy.proposals`（带 query 文本，经 `cg(op=insight, action=explore)`
    对 insight op 暴露）。修前只有前两者被逐面加过过滤，`autonomy` 直接读
    `_reflections` 原样把原文放进 `proposals[].query`（复核实测 role=output
    可读回属主查询原文）。判据放在**读取单点**，新读面自动继承；各消费点
    不再各写一份（本仓反复栽过的「同一判据两份」形态）。

    口径：`reflect()` 写台账时**恒不带 sensitivity 键**（md_cg/mdcg.py:5364-5375），
    故对非设计者这是**全量 fail-closed**——低权读者读不到任何反思记录（含
    trace/trust 的数值面）。这是刻意的「宁可少读」：记录密级不可判时，连
    「有几条、相似度多少」都是原文的派生信息（issue #445 已证模糊猜测可钓出
    原文）。设计者（can_admin）与纯 MdCGOS（无 principal）读数不变。
    """
    path = getattr(cg, "reflection_log", "") or os.path.join(
        cg.root, "_reflection.jsonl")
    return [r for r in read_jsonl(path) if _can_read_record(cg, r)]


# 生效条件：形参 cg 的 index 属性缺失或为假值、或其 "nodes" 键缺失、或该键值为假值（如空 dict）时返回 {}，否则返回该 "nodes" 值；
def _nodes(cg) -> dict:
    return (getattr(cg, "index", None) or {}).get("nodes") or {}


# 生效条件：形参 cg 的 get(nid) 为假值、或其结果缺 "frontmatter" 键、或该键值为假值时返回 {}，否则返回该 node 的 frontmatter；
def _fm(cg, nid) -> dict:
    node = cg.get(nid) or {}
    return node.get("frontmatter") or {}


# --------------------------------------------------------------------------
# 观测面 1：信息差轨迹（D / dD / d²D）
# --------------------------------------------------------------------------

# 生效条件：形参 cg 的反思留痕中不存在 d_curr 为 int/float 的记录时返回 ok=False/insufficient_data/n=0；否则按 window（默认 50，window 为假值 0 时取全部记录）截取尾部计算，返回 ok=True 及 d_current、d1、由 d1 与 ±0.01 判定的 trend（converging/diverging/flat）等字段；
def trace(cg, window: int = 50) -> dict:
    """信息差轨迹：D(t) → dD/dt（方向）→ d²D/dt²（情绪）。

    数据源：`_reflection.jsonl`（reflect() 的留痕），不新增计算负担。
    """
    recs = [r for r in _reflections(cg)
            if isinstance(r.get("d_curr"), (int, float))]
    if not recs:
        return {"ok": False, "reason": "insufficient_data", "n": 0,
                "note": "无反思留痕：先调用 reflect() 才有轨迹"}
    tail = recs[-int(window):] if window else recs
    ds = [float(r["d_curr"]) for r in tail]
    n = len(ds)
    d1 = (ds[-1] - ds[0]) / max(1, n - 1)
    d2 = float(tail[-1].get("d2") or 0.0)
    states = Counter()
    for r in tail:
        for k, v in (r.get("states") or {}).items():
            try:
                states[str(k)] += int(v or 0)
            except (TypeError, ValueError):
                continue
    total = sum(states.values()) or 1
    return {
        "ok": True, "n": n,
        "d_current": round(ds[-1], 4),
        "d_mean": round(sum(ds) / n, 4),
        "d_min": round(min(ds), 4),
        "d_max": round(max(ds), 4),
        "d1": round(d1, 4),
        "d2": round(d2, 4),
        "emotion": _emotion(d2),
        "trend": ("converging" if d1 < -0.01 else
                  "diverging" if d1 > 0.01 else "flat"),
        "states": dict(states),
        "state_rates": {k: round(v / total, 4) for k, v in states.items()},
        "d_series": [round(x, 4) for x in ds[-20:]],
    }


# --------------------------------------------------------------------------
# 观测面 2：自信校准（期望正确率 vs 实际验证通过率）
# --------------------------------------------------------------------------

# 生效条件：形参 cg 的 index.nodes 中满足 evidence_count>0 且 frontmatter 的正例+负例>0 的节点计数 used，在 used >= int(max_scan)（默认 2000，max_scan 为 0 时立即 break 使 used=0）时截断——used 为 0 返回 ok=False/insufficient_data，否则按 used 与常量 MIN_SAMPLES、期望减实际的 gap 与 GAP_OVERCONFIDENT/GAP_UNDERCONFIDENT 判定 verdict（insufficient_data/overconfident/underconfident/calibrated）；
def calibration(cg, max_scan: int = 2000) -> dict:
    """自信校准：我说的可信吗？

    期望正确率 = 节点 confidence 均值；
    实际正确率 = Σ正例 / Σ(正例+负例)（来自 evidence_log 的聚合计数）。
    gap > 0 → 过度自信；gap < 0 → 过度保守。
    ECE = Σ(证据占比 × |桶内实际 - 桶内自信|)（期望校准误差）。
    """
    keys = [f"{lo:g}-{hi:g}" for lo, hi in BINS]
    buckets = {k: {"n": 0, "conf_sum": 0.0, "pos": 0, "neg": 0} for k in keys}
    exp_sum = 0.0
    used = 0
    total_pos = total_neg = 0
    # issue #121（2026-10-11）：**越界 confidence 不再静默丢弃**。
    # 修前：conf 落在 BINS 覆盖域（[0, 1.01)）之外的节点照计 used/exp_sum/
    # total_pos/total_neg（进分母），却因不落任何桶而对 ECE 分子零贡献 ⇒ ECE 被
    # 系统性低估；且 n_nodes 与 Σbins.n_nodes 对不上而无人报。
    # 现逐条记账并透出，**不变量**：n_nodes == Σbins.n_nodes + dropped。
    # 口径不变：越界节点照旧进 used/exp_sum/总证据（分母口径一字不改），
    # 只把「没进桶」这件事从静默变成可观测。
    dropped_count = 0
    dropped_ids = []
    for nid, e in _nodes(cg).items():
        if used >= int(max_scan):
            break
        if int(e.get("evidence_count") or 0) <= 0:
            continue
        fm = _fm(cg, nid)
        pos = int(fm.get("positive_evidence") or 0)
        neg = int(fm.get("negative_evidence") or 0)
        if pos + neg <= 0:
            continue
        conf = float(fm.get("confidence", 0.6))
        used += 1
        exp_sum += conf
        total_pos += pos
        total_neg += neg
        placed = False
        for lo, hi in BINS:
            if lo <= conf < hi:
                b = buckets[f"{lo:g}-{hi:g}"]
                b["n"] += 1
                b["conf_sum"] += conf
                b["pos"] += pos
                b["neg"] += neg
                placed = True
                break
        if not placed:
            # 越界（conf < 0 或 conf >= BINS 覆盖上界 1.01）：计 dropped 并抽样留 id。
            # 注意判据是 lo <= conf < hi，上界 1.01 已把 conf==1.0 正常覆盖。
            dropped_count += 1
            if len(dropped_ids) < DROPPED_SAMPLE_MAX:
                dropped_ids.append(nid)
    if used == 0:
        return {"ok": False, "reason": "insufficient_data", "n_nodes": 0,
                "dropped": 0, "out_of_range": 0, "dropped_ids": [],
                "dropped_ids_truncated": False,
                "note": "无带证据的节点：先 verify() 积累验证记录"}
    expected = exp_sum / used
    actual = total_pos / max(1, total_pos + total_neg)
    gap = expected - actual
    bins = []
    ece = 0.0
    total_ev = total_pos + total_neg
    for k in keys:
        b = buckets[k]
        if b["n"] == 0:
            continue
        n_ev = b["pos"] + b["neg"]
        conf_b = b["conf_sum"] / b["n"]
        acc_b = (b["pos"] / n_ev) if n_ev else None
        bins.append({"bin": k, "n_nodes": b["n"], "n_evidence": n_ev,
                     "confidence": round(conf_b, 4),
                     "accuracy": None if acc_b is None else round(acc_b, 4)})
        if n_ev and total_ev:
            ece += (n_ev / total_ev) * abs(conf_b - acc_b)
    if used < MIN_SAMPLES:
        verdict = "insufficient_data"
    elif gap > GAP_OVERCONFIDENT:
        verdict = "overconfident"
    elif gap < GAP_UNDERCONFIDENT:
        verdict = "underconfident"
    else:
        verdict = "calibrated"
    return {
        "ok": True, "n_nodes": used,
        # issue #121：可观测面——**越界丢弃**的计数与抽样 id（不静默）。
        # dropped 是不变量的加数项（今日唯一丢因即越界；将来新增丢因须并入此数）。
        "dropped": dropped_count,
        "out_of_range": dropped_count,
        "dropped_ids": list(dropped_ids),
        "dropped_ids_truncated": dropped_count > len(dropped_ids),
        "n_evidence": total_ev,
        "expected_accuracy": round(expected, 4),
        "actual_accuracy": round(actual, 4),
        "gap": round(gap, 4),
        "ece": round(ece, 4),
        "verdict": verdict,
        "bins": bins,
    }


# --------------------------------------------------------------------------
# 观测面 3：盲区地图（我知道我不知道什么）
# --------------------------------------------------------------------------

# 生效条件：形参 cg 的反思留痕由 _reflections 给出（**已按读可见性过滤**——单点在读取面，本函数不另写第二份判据），再按 window（默认 200，window 为 0 时切片 [0:] 取全部）截尾，聚合其中 BLINDSPOT/DEFER 计数非零且 query 非空的记录（计数转换失败则跳过该条）；返回 ok=True，items 与 unresolved 各取前 int(limit)（limit 默认 20，limit 为 0 时两项均为空列表），unresolved_count 为未截断的完整计数；
def blindspots(cg, limit: int = 20, window: int = 200) -> dict:
    """盲区地图：反复 BLINDSPOT / DEFER 的查询邻域 + 未解问题清单。

    智能论推论三：盲区不是失败记录，是知识。因此按**邻域聚合**输出，
    可直接驱动 unresolved 层建节点（补条件）。

    #445：items 里的 `query` 是调用方查询原文——可见性判据在 `_reflections`
    （台账唯一读取点），不可见记录连计数都不进（宁可少读）。无身份模型
    （纯 MdCGOS）与设计者不受限，既有调用方读数不变。
    """
    recs = _reflections(cg)[-int(window):]
    agg = {}
    for r in recs:
        st = r.get("states") or {}
        try:
            bad = int(st.get("BLINDSPOT") or 0)
            defer = int(st.get("DEFER") or 0)
        except (TypeError, ValueError):
            continue
        if not bad and not defer:
            continue
        q = str(r.get("query") or "").strip()
        if not q:
            continue
        k = _key(q)
        a = agg.setdefault(k, {"query": q, "blindspot": 0, "defer": 0,
                               "samples": 0, "last_t": 0.0})
        a["blindspot"] += bad
        a["defer"] += defer
        a["samples"] += 1
        a["last_t"] = max(a["last_t"], float(r.get("t") or 0.0))
    items = sorted(agg.values(),
                   key=lambda x: (-x["blindspot"], -x["defer"], -x["last_t"]))
    unresolved = []
    for nid, e in _nodes(cg).items():
        if e.get("layer") == "unresolved":
            unresolved.append({"node_id": nid,
                               "content": str((cg.get(nid) or {}).get("content") or "")[:200]})
    return {
        "ok": True,
        "n_queries": len(agg),
        "items": items[:int(limit)],
        "unresolved": unresolved[:int(limit)],
        "unresolved_count": len(unresolved),
    }


# --------------------------------------------------------------------------
# 观测面 4：信任（P_gap / P_trust / 情感）
# --------------------------------------------------------------------------

# 生效条件：形参 events 为假值（空容器）时返回 0.0，否则返回其中等于 "confirmed" 的元素个数除以 events 长度；
def _rate(events) -> float:
    if not events:
        return 0.0
    return sum(1 for v in events if v == "confirmed") / len(events)


# 生效条件：形参 cg 的反思留痕中 d_curr 为数值的序列按 window（默认 100，window 为 0 时切片 [0:] 取全部）截尾得 p_gap（截尾结果为空则为 None）；取自 evidence_count>0 的节点的验证事件（扫描数受 int(max_scan) 上限、默认 2000，按 window 同样规则截尾）为空时返回 p_trust=None/emotion=None 分支，否则按三段 confirmed 通过率差返回 d1、d2、emotion 与 verdicts；
def trust(cg, window: int = 100, max_scan: int = 2000) -> dict:
    """P_gap（信息差置信）+ P_trust（验证稳定置信）+ d²T/dt²（情感）。

    P_gap   = 近期反思中 D_norm < D_LOW 的比例（信息差已收敛 = 有把握）；
    P_trust = 近期验证事件中 confirmed 的占比（智能论 §十）；
    d²T/dt² = 三段验证通过率差的二阶差分（情感 = 信任的二阶变化）。
    """
    recs = _reflections(cg)
    ds = [float(r["d_curr"]) for r in recs
          if isinstance(r.get("d_curr"), (int, float))]
    recent_d = ds[-int(window):]
    p_gap = (round(sum(1 for d in recent_d if d < D_LOW) / len(recent_d), 4)
             if recent_d else None)

    events = []
    used = 0
    for nid, e in _nodes(cg).items():
        if used >= int(max_scan):
            break
        if int(e.get("evidence_count") or 0) <= 0:
            continue
        used += 1
        for ev in (_fm(cg, nid).get("evidence_log") or []):
            if isinstance(ev, dict) and ev.get("verdict"):
                events.append((float(ev.get("t") or 0.0), str(ev["verdict"])))
    events.sort()
    tail = events[-int(window):] if window else events
    n = len(tail)
    if not n:
        return {"ok": True, "p_gap": p_gap, "p_trust": None,
                "emotion": None, "n_events": 0,
                "note": "无验证留痕：先 verify() 才有信任轨迹"}
    verdicts = [v for _, v in tail]
    p_trust = round(_rate(verdicts), 4)
    seg = max(1, n // 3)
    s1 = _rate(verdicts[:seg])
    s2 = _rate(verdicts[seg:2 * seg]) if n > seg else s1
    s3 = _rate(verdicts[2 * seg:]) if n > 2 * seg else s2
    d1 = s2 - s1
    d2 = (s3 - s2) - (s2 - s1)
    return {
        "ok": True,
        "p_gap": p_gap,
        "p_trust": p_trust,
        "d1": round(d1, 4),
        "d2": round(d2, 4),
        "emotion": _emotion(d2),
        "n_events": n,
        "verdicts": dict(Counter(verdicts)),
    }


# --------------------------------------------------------------------------
# 自报告：汇总 + 确定性建议
# --------------------------------------------------------------------------

# 生效条件：形参 tr.get("ok") 为假时产出 no_trace；否则按 tr["d2"] > D2_EMOTION 产出 diverging、state_rates["BLINDSPOT"] >= BLINDSPOT_DENSE 产出 blindspot_dense；再按 cal 的 verdict 为 overconfident/underconfident 与 bs.get("unresolved_count", 0) > 0 各自追加；全部未触发时返回单条 stable（形参 tt 在函数体内未被使用）；
def _advise(tr, cal, bs, tt) -> list:
    """确定性建议（非 LLM）：每条都带触发它的证据，可复核。"""
    out = []
    if not tr.get("ok"):
        out.append({"code": "no_trace",
                    "why": "无反思留痕，无法评估认知轨迹",
                    "action": "先调用 reflect() 积累轨迹"})
    else:
        rates = tr.get("state_rates") or {}
        if tr["d2"] > D2_EMOTION:
            out.append({"code": "diverging",
                        "why": f"信息差加速扩大 d²D/dt²={tr['d2']}（emotion={tr['emotion']}）",
                        "action": "回到最近一次 DEFER 的缺失条件，先补条件再扩张"})
        if float(rates.get("BLINDSPOT") or 0) >= BLINDSPOT_DENSE:
            out.append({"code": "blindspot_dense",
                        "why": f"BLINDSPOT 占比 {rates.get('BLINDSPOT')} >= {BLINDSPOT_DENSE}",
                        "action": "为高频盲区邻域建 unresolved 节点，驱动补条件"})
    verdict = cal.get("verdict")
    if verdict == "overconfident":
        out.append({"code": "overconfident",
                    "why": (f"期望正确率 {cal['expected_accuracy']} > 实际 "
                            f"{cal['actual_accuracy']}（gap {cal['gap']}）"),
                    "action": "对高 confidence 节点抽查复核；verify(weakened) 会触发降级"})
    elif verdict == "underconfident":
        out.append({"code": "underconfident",
                    "why": (f"期望正确率 {cal['expected_accuracy']} < 实际 "
                            f"{cal['actual_accuracy']}（gap {cal['gap']}）"),
                    "action": "自信偏低：可适度提升已验证节点的召回权重"})
    if bs.get("unresolved_count", 0) > 0:
        out.append({"code": "open_questions",
                    "why": f"unresolved 层有 {bs['unresolved_count']} 个未解问题",
                    "action": "按 blindspots.items 的顺序优先补条件"})
    if not out:
        out.append({"code": "stable",
                    "why": "轨迹 / 校准 / 盲区 / 信任均在阈值内",
                    "action": "维持当前策略"})
    return out


# 生效条件：给定 cg 与透传给 trace 的 window（默认 50）时恒定返回 ok=True 且含 trace/calibration/blindspots/trust/advice 的 rec，并以 op="report" 写一条留痕后返回该 rec；
def report(cg, window: int = 50) -> dict:
    """完整元认知报告（四观测面 + 确定性建议），并独立留痕。"""
    tr = trace(cg, window=window)
    cal = calibration(cg)
    bs = blindspots(cg)
    tt = trust(cg)
    advice = _advise(tr, cal, bs, tt)
    rec = {
        "ok": True,
        "trace": tr,
        "calibration": cal,
        "blindspots": bs,
        "trust": tt,
        "advice": advice,
        "independent": True,
        "note": "元认知只观察不改事实：confidence / 资格 / 召回打分均未被本模块修改",
    }
    _log(cg, {
        "op": "report",
        "n_reflections": tr.get("n"),
        "d_current": tr.get("d_current"),
        "emotion": tr.get("emotion"),
        "calibration_verdict": cal.get("verdict"),
        "gap": cal.get("gap"),
        "unresolved_count": bs.get("unresolved_count"),
        "p_trust": tt.get("p_trust"),
        "advice": [a["code"] for a in advice],
    })
    return rec


# 生效条件：形参 query 经 str(query or "").strip() 为空（含 None、空串、纯空白）时返回 {'ok': False, 'reason': 'empty_query'}；相似历史（_jaccard 得分 >= min_sim，默认 0.25，排序后取前 int(k)，k 默认 5、k 为 0 时为空）为空时返回 ok=True/warning="no_prior"；否则按 BLINDSPOT/DEFER/ACCEPT 计数与 max(1, n//2) 及 prior_d<0.5 判定，返回带 warning/recommendation 的 out；
def self_check(cg, query: str, k: int = 5, min_sim: float = 0.25) -> dict:
    """元认知闸门：回答之前先自问「我对这件事的认知状态如何」。

    不是检索，而是**对检索的预期**：历史相似查询的轨迹决定了这次该
    直接答、先补条件、还是预先声明盲区。
    """
    q = str(query or "").strip()
    if not q:
        return {"ok": False, "reason": "empty_query"}
    sims = []
    for r in _reflections(cg):
        rq = str(r.get("query") or "")
        if not rq:
            continue
        s = _jaccard(q, rq)
        if s >= min_sim:
            sims.append((s, r))
    sims.sort(key=lambda x: (-x[0], -float(x[1].get("t") or 0)))
    sims = sims[:int(k)]
    hist = []
    bad = defer = acc = 0
    ds = []
    for s, r in sims:
        st = r.get("states") or {}
        b = int(st.get("BLINDSPOT") or 0)
        d = int(st.get("DEFER") or 0)
        a = int(st.get("ACCEPT") or 0)
        bad += b
        defer += d
        acc += a
        if isinstance(r.get("d_curr"), (int, float)):
            ds.append(float(r["d_curr"]))
        # #445：可见性判据在 `_reflections`（台账唯一读取点）——走到这里的
        # 记录**都已通过** `_can_read_record`，故原文可原样回给读者；不可见
        # 记录根本不进 sims（连 similarity/计数都不回：对短查询，相似度与
        # 条数本身就是原文的派生信息，issue #445 已证模糊猜测可钓出全文）。
        hist.append({"query": r.get("query"), "similarity": round(s, 4),
                     "d_curr": r.get("d_curr"), "states": st,
                     "t": r.get("t")})
    n = len(hist)
    if n == 0:
        rec = {"ok": True, "query": q, "prior_attempts": 0,
               "similar_history": [],
               "expected_confidence": None,
               "warning": "no_prior",
               "recommendation": "search_then_decide",
               "note": "无相似历史：按四态判定正常检索"}
        _log(cg, {"op": "self_check", "query": q, "prior_attempts": 0,
                  "recommendation": rec["recommendation"]})
        return rec
    prior_d = sum(ds) / len(ds) if ds else None
    exp_conf = None if prior_d is None else round(max(0.0, 1.0 - prior_d), 4)
    warning = None
    if bad >= max(1, n // 2):
        warning = "blindspot_likely"
        rec_code = "declare_blindspot"
    elif defer >= max(1, n // 2):
        warning = "conditions_missing"
        rec_code = "defer_and_supply_conditions"
    elif acc >= max(1, n // 2) and (prior_d is None or prior_d < 0.5):
        rec_code = "answer"
    else:
        rec_code = "search_then_decide"
    out = {
        "ok": True, "query": q,
        "prior_attempts": n,
        "similar_history": hist,
        "prior_d": None if prior_d is None else round(prior_d, 4),
        "expected_confidence": exp_conf,
        "prior_blindspot": bad,
        "prior_defer": defer,
        "prior_accept": acc,
        "warning": warning,
        "recommendation": rec_code,
    }
    _log(cg, {"op": "self_check", "query": q, "prior_attempts": n,
              "prior_d": out["prior_d"], "warning": warning,
              "recommendation": rec_code})
    return out


# --------------------------------------------------------------------------
# 留痕查询 / 自描述
# --------------------------------------------------------------------------

# 生效条件：形参 limit（默认 100）为真时取 read_jsonl(os.path.join(cg.root, LOG_FILE)) 的尾部 int(limit) 条，limit 为 0 等假值时保留全部记录；逐条按 _can_read_record 过滤——可见记录原样返回，不可见记录经 _redact_query 去原文（query/query_digest/query_len 摘除并置 query_redacted=True）；返回 ok=True 与倒序的 records；
def history(cg, limit: int = 100) -> dict:
    """元认知留痕（倒序，最新在前）。

    #426-D：`_metacognition.jsonl` 是全库共享台账，修前 history 整行倒序返回，
    无令牌访客可读到属主 self_check 的查询原文。现按读可见性单点
    `_can_read_record` 过滤：无身份模型/设计者原样；其余读者对缺 sensitivity
    键（升级前旧记录）与超密级记录一律去原文。
    """
    recs = list(read_jsonl(os.path.join(cg.root, LOG_FILE)))
    if limit:
        recs = recs[-int(limit):]
    recs = [r if _can_read_record(cg, r) else _redact_query(r) for r in recs]
    return {"ok": True, "n": len(recs), "records": recs[::-1]}


# 生效条件：给定 cg 时恒定返回含 n_reflections（tr.get("n", 0)）、d_current、emotion、calibration、p_trust、p_gap 的 dict，字段分别取自对 trace(window=20)、calibration、trust(window=50) 的调用结果，缺键按其 .get 回落；
def summary(cg) -> dict:
    """一句话元认知状态（供 health / OS 面板使用）。"""
    tr = trace(cg, window=20)
    cal = calibration(cg)
    tt = trust(cg, window=50)
    return {
        "n_reflections": tr.get("n", 0),
        "d_current": tr.get("d_current"),
        "emotion": tr.get("emotion"),
        "calibration": cal.get("verdict"),
        "p_trust": tt.get("p_trust"),
        "p_gap": tt.get("p_gap"),
    }


# 生效条件：cg 必需、window 缺省 200；恒转调 d_meta.compute(cg, window=window) 并原样返回其 dict（三代理 + enabled/window/note），d_meta 导入或计算抛异常时返回 {"ok": False, "error": "类型名: 消息"}（不返回编造数值、不写任何状态）；
def d_meta_face(cg, window: int = 200) -> dict:
    """D_meta 观测面（边界压力向量）：三代理各自 [0,1]，**不合成单值**。

    智能论3.4 §2.7.0 DEV-002/002a：`D_meta` ≠ `D_task`（不参与 `_compute_d`）；
    三代理分别观测「进入系统但未被消化」的事件，不是「世界真实未发生的事件」。
    独立性：只读留痕与索引，不写 confidence / 资格 / 召回打分；`MDCG_D_META=0`
    时三值恒 0.0 且 note 声明已回退（显式回退留痕，不是缺键）。
    """
    try:
        from . import d_meta
        return d_meta.compute(cg, window=window)
    except Exception as exc:                               # noqa: BLE001
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}


# 生效条件：无入参且无分支，恒定返回含 module/role/theory/faces/constraints 及由模块常量 GAP_OVERCONFIDENT、GAP_UNDERCONFIDENT、BLINDSPOT_DENSE、D_LOW、MIN_SAMPLES 构成的 thresholds 的静态 dict；
def catalog() -> dict:
    """自描述：元认知的观测面与独立性约束。"""
    return {
        "module": "metacognition",
        "role": "观察自身认知过程的二阶单元（不参与裁决）",
        "theory": {
            "emotion": "d²D/dt²（智能论 §十一）",
            "feeling": "d²T/dt²（同）",
            "units": "五大单元中的反思/验证之外部观察者（§十三）",
            "blindspot": "推论三：局部不可知，盲区即知识",
            "trust": "P_trust / P_gap（§十）",
        },
        "faces": ["trace", "calibration", "blindspots", "trust", "report",
                  "self_check", "d_meta"],
        "constraints": [
            "只读留痕与索引，不写 confidence / 资格 / 召回打分",
            "独立留痕 _metacognition.jsonl（append-only）",
            "建议为确定性模板，非 LLM 生成，每条带证据",
        ],
        "thresholds": {
            "gap_overconfident": GAP_OVERCONFIDENT,
            "gap_underconfident": GAP_UNDERCONFIDENT,
            "blindspot_dense": BLINDSPOT_DENSE,
            "d_low": D_LOW,
            "min_samples": MIN_SAMPLES,
        },
    }