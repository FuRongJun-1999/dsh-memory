# -*- coding: utf-8 -*-
"""权重刷新与衰减（设计稿 §七 · P4）——**进主分数**的刷新/衰减乘子。

形态（§7.1 已裁）
-----------------
    score ← score × cred_factor(γ, Δt) × refresh(access_count, last_access)

落位（§7.2 已裁）：与「分池权重乘数」**同一乘子位**（`MdCG._score` 里
`raw = clamp(raw * pooling.weight_of(...))` 那一行）——**不新开乘子链**。
本模块只提供**乘子本体与读点**，接线在 `mdcg._score`。

**这条乘子影响哪些检索路**（读现场确认，2026-10-01）：唯一生效点是
`MdCG._score` ⇒ 走它的路全部受影响：
  · `MdCG.search` 的 T0–T3 各腿（桶内 LIKE / 全局 LIKE / 全局扫描）；
  · `MdCos._lexical`（`search_rrf` 的 **lexical** 路）与 `_path_bucket`
    （bucket 路）。
**不经** `_score` 的路因此**不受**本乘子影响：`entity`（恒 1.0）、`graph`
（种子分 × 0.5）、`chain`、`temporal`、`fuzzy`、`semantic`、`goal`。
Rust 侧同款：乘子只在 `sort_path(..., apply_freshness=true)` 生效，
而 `fuse` **只对 lexical 路**传 true（见 `rust/src/freshness.rs` 头注）。

核的唯一权威（硬约束）
----------------------
`md_cg/whitebox_kb/aeis_core/time_core.py` 的 `cred_factor` ——该模块 docstring
逐字点名「任何在本模块之外出现的衰减核实现（`exp(-t/τ)`、`×(1-factor)`、
EMA 保持率）都是 bug」。本模块**不写任何指数核**（`math.exp` 一次都不出现）。

γ 与 Δt 口径（§〇.3-12 已裁）
-----------------------------
· γ 缺省 = `ln2 / 30 天`（半衰期 30 天，与 `links.DECAY_DAYS` 同刻度）；
  **唯一读取点**是 `mdcos.temporal_gamma()`（P3-temporal 已落），本模块复用
  **不新建第二个 γ 读取点**（env `MDCG_TEMPORAL_GAMMA` 同时覆盖两条路）。
· Δt 取 `created_at`（写入时刻，主链必有）。
· **单位必须是「天」**：γ 是「每天」的速率，Δt 先 /86400 再喂；喂秒会让衰减
  快 86400 倍。单位常量与断言面见 `DT_UNIT` 与 `md_cg/test_p4_freshness.py`。

刷新参数**照抄**（不自行发明）
------------------------------
AEIS `consolidate_cycle(rehearsal_threshold=0.7, degrade_threshold=0.2,
gain=0.01)`（`md_cg/whitebox_kb/aeis_core/core.py:4801-4831`，docstring 逐字
「P1-4 巩固周期：高重要度演练（刷新访问）+ 低重要度降权 + 压缩候选标记」）：

  · 刷新：`importance ≥ 0.7` → 计入演练；且 `access_count % 10 == 0` → +gain；
  · 降权：`importance < 0.2` 且 `access_count ≤ 2` → −gain；
  · 跳过：`anchor`/`structure` 层、`protected`/`no_forget`（本模块同款跳过——
    受保护节点不因衰减穿越保护线，见 §7.3）。

floor（§7.3 · 移植隐患的第二道闸）
----------------------------------
AEIS 的 `decay_cycle` **无 floor**，而 md_cg 的保护判定是**即时读
`importance ≥ 0.70`**（`md_cg/protect.py:135-151`、`weights.IMPORTANCE_PROTECT`）
⇒ 衰减穿过 0.70 会让节点**自动失去保护**。故：

  · 衰减项带 floor（`SCORE_FLOOR`，与 P3-temporal 同值同源理由）；
  · **受保护节点**的衰减乘子另有下界 `IMPORTANCE_PROTECT / importance`，
    保证 `importance × 乘子 ≥ IMPORTANCE_PROTECT` **恒成立**——保护判定不可能
    被衰减翻转（推导见 `protected_floor`）；
  · 保留 `weights.recalc` 既有的「`after ≥ 0.70` 自动补写 `protected`」行为
    （本模块**不改** `weights.recalc`，只在守卫里断言其仍在位）。

语义边界（§7.3 末条，记忆里那条裁定）
-------------------------------------
**不可遗忘 ≠ 不可覆盖**。衰减属「降级/搬迁」族：
  · 降级**不得实现为删除记录**——`recalc(apply=True)` 只写
    `frontmatter.freshness_weight` 与 `freshness_state`，**从不删节点**；
  · 需要跨层降级时走既有 `_move_layer`（其内已调 `protect.guard_move`），
    **不新写搬迁路径**；受保护节点被移出保护层仍需显式 `override=True`
    （`guard_move` 原样语义）。

三件套（§7.4，与 `weights.recalc` 同款）
----------------------------------------
预演（`recalc(apply=False)`）→ 逐节点留痕（`_maintain.jsonl`，
`action="freshness"`，与 `weights` 的 `action="importance"` 同族）→ 反向
apply（`rollback`，读回 `before` 并再记一条 `freshness_rollback`）。
AEIS 侧**没有**预演与回滚（`consolidate_cycle`/`decay_cycle` 均无）——
这是移植时的**净增工作量**，不省。

零第三方依赖。
"""
from __future__ import annotations

import os
import time

from .fsutil import append_jsonl, read_jsonl
# `_maintain.jsonl` 与保护下限的**单一真源**在 weights（同族留痕共用一份文件名）
from .weights import (APPLY_DELTA, IMPORTANCE_PROTECT, MAINTAIN_LOG,
                      node_importance)
from .whitebox_kb.aeis_core import time_core as _tc

# --------------------------------------------------------------------------
# 参数（照抄 AEIS consolidate_cycle；出处见模块 docstring）
# --------------------------------------------------------------------------

#: AEIS `consolidate_cycle` 的三个既有取值 + 两个结构常数（逐字照抄，不发明）。
REFRESH_PARAMS = {
    "rehearsal_threshold": 0.7,   # importance ≥ 此值 → 高重要度演练（刷新）
    "degrade_threshold": 0.2,     # importance < 此值 且 access_count ≤ 2 → 降权
    "gain": 0.01,                 # 每档步长（AEIS 原有）
    "cycle": 10,                  # access_count % 10 == 0 才 +gain（AEIS 原有）
    "degrade_max_access": 2,      # 低重要度降权的访问数上限（AEIS 原有）
    "source": ("md_cg/whitebox_kb/aeis_core/core.py:4801-4831 "
               "consolidate_cycle(rehearsal_threshold=0.7, "
               "degrade_threshold=0.2, gain=0.01)"),
}

#: Δt 的单位（**最易错处**）：γ 是「每天」的速率，Δt 必须按天喂。
DT_UNIT = "day"
SECONDS_PER_DAY = 86400.0

#: Δt 的**粒度**：整日（向下取整）。为什么量化（本批的一处设计取舍，如实登记）：
#:   ① γ 的单位本来就是「天」（半衰期 30 天档），亚日精度对结果无信息量；
#:   ② 仓内有「同查询两轮结果逐位一致 / 可复算」的硬纪律
#:      （`md_cg/test_retr_score_once.py` D1b 就是这条断言）——不量化则分数随
#:      `time.time()` 逐轮微变，两轮比较恒不等；
#:   ③ 两侧（Python / Rust）各自取时钟，量化到同一「天」桶后跨语言同值，
#:      消除 ms 级时钟差带来的 6 位小数抖动风险。
#: 量化损失上界 = γ × 1 天 = ln2/30 ≈ 2.3%（即「同一天内不再区分」）。
DT_QUANTUM_DAYS = 1.0

#: 衰减项 floor：`cred_factor(gamma, dt, floor, ceil)` 的 floor。
#: 取值理由与 P3-temporal 同源（0.5**10 ≈ 9.77e-4 < 1e-3 —— 30 天半衰期下
#: 300 天 = 10 个半衰期后继续区分已无信息量）；floor 让**老节点/缺 created_at
#: 的节点**仍带非零分参与排序，而不是被乘成 0 后不可召回。
SCORE_FLOOR = 0.001

#: 衰减乘子上限（乘子恒 ≤ 1.0：衰减只能降权，刷新项负责 > 1 的那半边）。
SCORE_CEIL = 1.0

#: 总开关（缺省开；=0 时乘子恒为 1.0 ⇒ 与改动前逐位一致，是「可回退」的
#: 第一道闸——第二道是三件套的 rollback）。
FRESHNESS_ENV = "MDCG_FRESHNESS"

#: 观测时刻的可复算冻结口（**只为守卫/探针的确定性**；未设 = `time.time()`）。
#: 有了它，两侧探针能在同一 `now` 上逐位比对乘子。
NOW_ENV = "MDCG_FRESHNESS_NOW"

#: 降级判定面（`recalc` 用）：乘子低于此值的节点标记 `freshness_state`
#: = "degraded"（**只标记，不删除**——见模块 docstring 的语义边界）。
DEMOTE_BELOW = 0.5


# 生效条件：environ（缺省 os.environ）里 FRESHNESS_ENV 为真值且归一后属 {"0","false","no","off"} 之外的值时返回 True；变量缺失/空串/命中关闭词表时返回 False；
def enabled(environ=None) -> bool:
    """刷新/衰减乘子是否生效（缺省**开**：§7.2「进主分数」）。"""
    raw = (environ or os.environ).get(FRESHNESS_ENV)
    if raw is None or str(raw).strip() == "":
        return True
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


# 生效条件：environ（缺省 os.environ）里 NOW_ENV 可 float() 解析时返回该浮点值；缺失/空串/不可解析时返回 time.time()；
def freshness_now(environ=None) -> float:
    """乘子用的「当前时刻」（unix 秒）。**单一读取点**（守卫与探针共用）。"""
    raw = (environ or os.environ).get(NOW_ENV)
    if raw:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return time.time()
    return time.time()


# 生效条件：gamma 非正或不可转 float 时回落 `mdcos.temporal_gamma()`；否则返回 float(gamma)；无 IO、无副作用；
def resolve_gamma(gamma=None) -> float:
    """γ 的解析（缺省回落 **P3 的同一读取点** `mdcos.temporal_gamma()`）。"""
    if gamma is not None:
        try:
            g = float(gamma)
            if g > 0:
                return g
        except (TypeError, ValueError):
            pass
    from .mdcos import temporal_gamma      # 懒导入：避免模块级循环依赖
    return temporal_gamma()


# --------------------------------------------------------------------------
# 核（一律经 time_core；本模块不写指数核）
# --------------------------------------------------------------------------

# 生效条件：gamma 与 dt_days（单位=天）任意可转 float 时，返回 time_core.cred_factor(gamma, dt_days, floor, ceil)；dt 非有限值（inf/nan）时同样交给 cred_factor（inf → 取 floor）；
def decay_factor(gamma: float, dt_days: float, floor: float = SCORE_FLOOR,
                 ceil: float = SCORE_CEIL) -> float:
    """时间衰减乘子 `e^(-γ·Δt)`（**核来自唯一权威** `time_core.cred_factor`）。

    ⚠ `dt_days` 的单位**必须**是「天」（`DT_UNIT`）；调用方负责换算，
    换算单点是 `entry_weight`（`(now - created_at) / SECONDS_PER_DAY`）。
    """
    if not enabled():
        return 1.0
    return _tc.cred_factor(float(gamma), float(dt_days), float(floor),
                           float(ceil))


# 生效条件：access_count 与 last_access 任意（不可转数值按 0 处理）、importance 任意可转 float；按 REFRESH_PARAMS 的三档判定返回 1.0+gain / 1.0−gain / 1.0；
def refresh_factor(access_count=0, last_access=0, importance=0.0) -> float:
    """访问刷新/降权乘子（**门槛与步长照抄 AEIS** `consolidate_cycle`）。

    判定序（与 AEIS 同序同门）：

      1. **刷新**：`importance ≥ rehearsal_threshold` 且 `access_count % 10 == 0`
         且 `last_access > 0`（真的被访问过）→ `1 + gain`；
      2. **降权**：`importance < degrade_threshold` 且
         `access_count ≤ degrade_max_access` → `1 − gain`；
      3. 其余 → `1.0`。

    `last_access > 0` 这一条是本模块对 AEIS 的唯一补足：AEIS 的 `% 10 == 0`
    在**从未被访问**（`access_count == 0`）时也为真——照抄原样会让「刚写、
    从未调用的高重要度节点」白拿一次刷新。加此闸后「未被调用」只能不刷新，
    不会反被奖励（语义仍与 §7.1「被经常调用的记忆其权重被刷新」一致）。
    """
    if not enabled():
        return 1.0
    p = REFRESH_PARAMS
    try:
        ac = int(float(access_count or 0))
        la = float(last_access or 0)
        imp = float(importance or 0.0)
    except (TypeError, ValueError):
        return 1.0
    if imp >= p["rehearsal_threshold"] and la > 0 and ac % p["cycle"] == 0:
        return 1.0 + p["gain"]
    if imp < p["degrade_threshold"] and ac <= p["degrade_max_access"]:
        return 1.0 - p["gain"]
    return 1.0


# 生效条件：entry 为可取 protected / importance 的映射；protected 为假值时返回 SCORE_FLOOR；为真值时返回 max(SCORE_FLOOR, min(1.0, IMPORTANCE_PROTECT / importance))（importance 不可转数值或 ≤0 时按 1.0 处理）；
def protected_floor(entry) -> float:
    """受保护节点的**衰减乘子下界**（§7.3 的第二道闸）。

    推导（为什么是 `IMPORTANCE_PROTECT / importance`）：
      md_cg 的保护判定是**即时读** `importance ≥ IMPortANCE_PROTECT(0.70)`
      （`protect.py` / `weights.py`）。衰减乘子 `m ≤ 1` 会让
      `importance × m < 0.70` ⇒ 节点**自动失去保护**（AEIS 移植的隐患）。
      取 `m ≥ 0.70 / importance`，则 `importance × m ≥ 0.70` **恒成立**——
      保护判定不可能被衰减翻转。
      下界被夹到 ≤ 1.0：`importance < 0.70` 的受保护节点（人工 `protect.mark`）
      乘子取 1.0（不衰减），同样不损失保护。
    """
    e = entry or {}
    if not e.get("protected"):
        return SCORE_FLOOR
    try:
        imp = float(e.get("importance") or 0.0)
    except (TypeError, ValueError):
        imp = 0.0
    if imp <= 0:
        imp = 1.0
    return max(SCORE_FLOOR, min(1.0, IMPORTANCE_PROTECT / imp))


# 生效条件：entry 为可取 created_at / access_count / last_access / importance / protected 的映射；fm 为真值时上述五个键优先取自 fm（缺键回落 entry）；now 为假值（None）时取 freshness_now()；无条件返回 (乘子, 依据 dict)——乘子 = decay_factor(gamma, |now-created_at|/86400, protected_floor(取数后的映射), SCORE_CEIL) × refresh_factor(...)；created_at 缺失/不可转数值/≤0 时 dt_days 取 inf（判「距参照无穷远」，由 floor 兜住）；
def entry_weight(entry, now=None, gamma=None, fm=None) -> tuple:
    """索引条目 → 分数乘子 `(乘子, 依据)`（**检索期唯一取数点**，免读文件）。

    `entry` 直接来自索引快照（`_node_entry` 已落 `created_at` /
    `access_count` / `last_access`）——**不读盘**（§7.2 卡点一）。

    `fm` 为可选覆盖源（写面刚落的 frontmatter 可能比索引条目新）：只为
    避免在热路径上拷贝 dict 而设，取数优先级 `fm > entry > 缺省`。
    """
    e = entry or {}
    keys = ("created_at", "access_count", "last_access", "importance",
            "protected")
    if fm is not None:
        src = {k: (fm.get(k) if fm.get(k) is not None else e.get(k))
               for k in keys}
    else:
        src = {k: e.get(k) for k in keys}
    if not enabled():
        return 1.0, {"disabled": True}
    g = resolve_gamma(gamma)
    ref = freshness_now() if now is None else float(now)
    try:
        created = float(src.get("created_at") or 0.0)
    except (TypeError, ValueError):
        created = 0.0
    if created <= 0:
        dt_days = float("inf")          # 无写入时刻：不猜测，判无穷远
    else:
        # **单位=天**：86400 秒/天，显式换算（γ 是每天速率）
        dt_days = abs(ref - created) / SECONDS_PER_DAY
        # **粒度=整日**（向下取整）：保证「同查询两轮逐位一致」（不随 wall clock
        # 微变）且两侧跨语言同值。详见 DT_QUANTUM_DAYS 的说明。
        dt_days = float(int(dt_days / DT_QUANTUM_DAYS)) * DT_QUANTUM_DAYS
    floor = protected_floor(src)
    d = decay_factor(g, dt_days, floor, SCORE_CEIL)
    r = refresh_factor(src.get("access_count"), src.get("last_access"),
                       src.get("importance"))
    return d * r, {"gamma": g, "dt_days": dt_days, "unit": DT_UNIT,
                   "decay": d, "refresh": r, "floor": floor,
                   "protected": bool(src.get("protected"))}


# --------------------------------------------------------------------------
# 三件套：预演 / 逐节点留痕 / 反向 apply（与 weights.recalc 同款）
# --------------------------------------------------------------------------

# 生效条件：cg.index["nodes"] 为 dict 时按 layer 过滤、limit 为真值才截断；dry-run 只出报表；apply=True 时逐节点把乘子（round 6）写入 frontmatter.freshness_weight 与 freshness_components，乘子 < DEMOTE_BELOW 时另写 freshness_state="degraded"（**只标记，不删记录**），乘子下降且 demote_layer 给定时经 cg._move_layer（内含 protect.guard_move）搬迁；每条 append_jsonl(action="freshness") 后 rebuild_index；返回报表 dict；
def recalc(cg, layer=None, limit=None, apply=False, min_delta=APPLY_DELTA,
           actor="maintain", dry_run_samples=10, now=None, demote_layer=None):
    """刷新/衰减权重的重算（**可预演 + 逐节点留痕 + 可回滚**）。

    apply=False（默认）只出报表，**零写盘**。
    apply=True 逐节点改写 `frontmatter.freshness_weight`；每节点一条
    `_maintain.jsonl`（`action="freshness"`，与 `weights` 的 `importance`
    同族），并提供 `rollback` 反向应用。

    ⚠ 本函数**从不删除节点**（§7.3「降级不得实现为删除记录」）：降级只落
    `freshness_state="degraded"` 标记；要搬迁层位时给出 `demote_layer`，
    走既有 `_move_layer`（其内已调 `protect.guard_move`，受保护节点需显式
    `override`）——不新写第二条搬迁路径。
    """
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    ids = [nid for nid, e in list(nodes.items())
           if not layer or e.get("layer") == layer]
    ids.sort()
    if limit:
        ids = ids[:int(limit)]
    ref = freshness_now() if now is None else float(now)
    batch = time.strftime("%Y%m%d-%H%M%S")
    planned, samples = [], []
    before_sum = after_sum = 0.0
    changed = unchanged = skipped = 0
    by_layer = {}
    for nid in ids:
        e = nodes.get(nid) or {}
        w, why = entry_weight(e, now=ref)
        before = float(e.get("freshness_weight") or 1.0)
        before_sum += before
        after_sum += w
        lay = e.get("layer") or "?"
        bl = by_layer.setdefault(lay, {"nodes": 0, "changed": 0})
        bl["nodes"] += 1
        if abs(w - before) < float(min_delta):
            unchanged += 1
            continue
        changed += 1
        bl["changed"] += 1
        plan = {"node_id": nid, "layer": lay, "batch": batch,
                "before": round(before, 6), "after": round(w, 6),
                "delta": round(w - before, 6), "why": why,
                "protected": bool(e.get("protected")),
                # 降级判定（只标记）：低于阈值即为 degraded 候选
                "degrade": bool(w < DEMOTE_BELOW)}
        planned.append(plan)
        if len(samples) < int(dry_run_samples):
            samples.append(plan)
    written, degraded = 0, 0
    if apply:
        if demote_layer:
            bind_move_layer(cg)         # 跨层降级走既有 _move_layer（现绑）
        for plan in planned:
            nid = plan["node_id"]
            node = cg.get(nid)
            if not node:
                skipped += 1
                continue
            fm = node.get("frontmatter") or {}
            fm["freshness_weight"] = plan["after"]
            fm["freshness_source"] = "freshness_recalc"
            fm["freshness_components"] = plan["why"]
            if plan["degrade"]:
                # **降级 = 标记**（不是删除记录）：节点与正文原样保留
                fm["freshness_state"] = "degraded"
                degraded += 1
            path = os.path.join(cg.root, (nodes.get(nid) or {}).get("path")
                                or node.get("path") or f"{nid}.md")
            cg._write_node(nid, path, fm, node.get("content") or "")
            e = nodes.get(nid)
            if e is not None:
                e["freshness_weight"] = plan["after"]
                e["freshness_state"] = fm.get("freshness_state")
            rec = {"t": time.time(), "action": "freshness", "batch": batch,
                   "id": nid, "layer": plan["layer"],
                   "before": plan["before"], "after": plan["after"],
                   "delta": plan["delta"], "degrade": plan["degrade"],
                   "why": plan["why"], "actor": actor}
            append_jsonl(os.path.join(cg.root, MAINTAIN_LOG), rec)
            written += 1
            # 跨层降级：走后缀既有 `_move_layer`（内含 protect.guard_move）
            if demote_layer and plan["degrade"] and _move_layer is not None:
                try:
                    _move_layer(nid, demote_layer,
                                reason=f"freshness degraded (w={plan['after']})")
                except Exception as exc:            # noqa: BLE001
                    plan["move_error"] = f"{type(exc).__name__}: {exc}"
        if written and hasattr(cg, "rebuild_index"):
            cg.rebuild_index()
    n = max(1, len(ids))
    return {
        "ok": True, "action": "freshness", "dry_run": not apply, "batch": batch,
        "nodes_scanned": len(ids), "changed": changed, "unchanged": unchanged,
        "skipped": skipped, "written": written, "degraded": degraded,
        "min_delta": float(min_delta), "now": ref,
        "gamma": resolve_gamma(), "unit": DT_UNIT,
        "avg_before": round(before_sum / n, 4),
        "avg_after": round(after_sum / n, 4),
        "by_layer": dict(by_layer), "samples": samples, "log": MAINTAIN_LOG,
        "note": ("dry-run：未写盘；apply=True 才写 freshness_weight"
                 if not apply else
                 f"已写 {written} 个节点（降级标记 {degraded}）；"
                 f"回滚见 rollback(batch={batch})"),
    }


#: 惰性持有的跨层降级入口（`MdCG._move_layer` 是实例方法：`recalc` 里现取）。
#: 这里保留模块级名字只为**可读性**（下方 `_bind_move_layer` 现绑）。
_move_layer = None


# 生效条件：cg 具备可调用的 _move_layer 时把 recalc 用的跨层降级入口绑定为该实例方法，返回 True；否则返回 False（降级只标记、不搬迁）；
def bind_move_layer(cg) -> bool:
    """把 `recalc(..., demote_layer=...)` 用的搬迁入口绑到实例方法上。

    为什么需要它：`recalc` 是**模块级函数**（与 `weights.recalc` 同构），而
    `_move_layer` 是实例方法。不新写第二条搬迁路径 ⇒ 只能绑既有那一条。
    """
    global _move_layer
    fn = getattr(cg, "_move_layer", None)
    _move_layer = fn if callable(fn) else None
    return _move_layer is not None


# 生效条件：cg.root/MAINTAIN_LOG 可读出 action=="freshness" 记录后，entry_ids 为真值时按记录 id 过滤；否则 batch 为真值时按 r.get("batch")==batch 过滤；否则取最后一条记录的 batch 再按其过滤；无记录返回 {"ok":False,"error":"no_records","reverted":0}，过滤后无记录返回 {"ok":False,"error":"batch_not_found",...}；对命中且 cg.get(nid) 为真的记录写回 rec.get("before") 到 frontmatter.freshness_weight（**只改这一列，不删节点**），若 reverted 且 cg 有 rebuild_index 则调用，最后 append_jsonl 写 action="freshness_rollback" 并返回 {"ok":True,"batch":batch,"reverted":reverted,"ids":ids}；
def rollback(cg, batch=None, entry_ids=None, actor="maintain"):
    """把刷新/衰减反向应用（三件套的第三件；AEIS 侧没有，属净增）。"""
    log_path = os.path.join(cg.root, MAINTAIN_LOG)
    records = [r for r in read_jsonl(log_path)
               if r.get("action") == "freshness"]
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
    for rec in records:
        nid = rec.get("id")
        node = cg.get(nid)
        if not node:
            continue
        fm = node.get("frontmatter") or {}
        fm["freshness_weight"] = rec.get("before")
        fm["freshness_source"] = "freshness_rollback"
        # 降级标记随回滚撤销（回到降级前状态）；**节点与正文一字不动**
        if not rec.get("degrade"):
            fm.pop("freshness_state", None)
        path = os.path.join(cg.root, (nodes.get(nid) or {}).get("path")
                            or node.get("path") or f"{nid}.md")
        cg._write_node(nid, path, fm, node.get("content") or "")
        e = nodes.get(nid)
        if e is not None:
            e["freshness_weight"] = rec.get("before")
        reverted += 1
        ids.append(nid)
    if reverted and hasattr(cg, "rebuild_index"):
        cg.rebuild_index()
    append_jsonl(log_path, {"t": time.time(), "action": "freshness_rollback",
                            "batch": batch, "reverted": reverted,
                            "actor": actor})
    return {"ok": True, "batch": batch, "reverted": reverted, "ids": ids}


# 生效条件：cg.root/MAINTAIN_LOG 可读出 JSONL 记录后，仅取 action=="freshness" 的记录并返回其尾部 int(limit) 条（limit 为 0 时返回全部）；
def history(cg, limit=100) -> list:
    """刷新/衰减留痕（最近 limit 条）。"""
    recs = [r for r in read_jsonl(os.path.join(cg.root, MAINTAIN_LOG))
            if r.get("action") == "freshness"]
    return recs[-int(limit):]


# 生效条件：无条件返回模块自描述 dict（公式 / 核出处 / γ 口径 / 单位 / floor / 参数出处 / 开关 / 三件套名），供守卫与文档对拍；
def catalog() -> dict:
    return {"formula": "score ← score × cred_factor(γ, Δt) × refresh(ac, la)",
            "core": "md_cg/whitebox_kb/aeis_core/time_core.py::cred_factor",
            "gamma_default": "ln2 / links.DECAY_DAYS(=30 天)",
            "dt_unit": DT_UNIT, "dt_source": "created_at",
            "score_floor": SCORE_FLOOR, "score_ceil": SCORE_CEIL,
            "refresh_params": dict(REFRESH_PARAMS),
            "protect_floor": "IMPORTANCE_PROTECT/importance（受保护节点）",
            "enabled_env": FRESHNESS_ENV, "now_env": NOW_ENV,
            "triplet": ["recalc(apply=False)", "_maintain.jsonl",
                        "rollback()"]}


# 生效条件：无条件返回模块自检 dict——核来自 time_core（本模块源码不含指数核调用）、单位常量为天、参数出处非空、weights 侧的保护下限可读；
def selfcheck() -> dict:
    """模块自检（守卫的第一条断言面）。"""
    src = open(os.path.abspath(__file__), encoding="utf-8").read()
    # 探针串拼接（不写字面量）：否则「检查用的字面量」本身会把检查判红
    needle = "math." + "exp("
    return {"core_is_time_core": "from .whitebox_kb.aeis_core import time_core"
            in src,
            "no_local_exp_core": needle not in src,
            "uses_cred_factor": "cred_factor" in src,
            "dt_unit": DT_UNIT,
            "params_source_set": bool(REFRESH_PARAMS.get("source")),
            "gain": REFRESH_PARAMS["gain"],
            "protect_floor": IMPORTANCE_PROTECT,
            "node_importance_available": callable(node_importance)}
