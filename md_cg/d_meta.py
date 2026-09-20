# -*- coding: utf-8 -*-
"""md_cg · D_meta 投影：边界压力向量（三代理，各自 [0,1]，**不合成单值**）

理论约束（智能论3.4 §2.7.0 DEV-002 / DEV-002a；工程方案
`docs/mdcg/D_meta_工程化方案_v0.2.md`）：

- DEV-002：`D_task` = 图上操作性距离；`D_meta` = 未被建模的现实总量。
  **两者对象不同、数值不互换**。本模块**不参与** `MdCG._compute_d`——
  `D_task` 口径零变更（"双 D 落盘"= 并列新增，不是打通）。
- DEV-002a：可新增 `D_meta` 投影链路，但不能并入 `D_task` 计算公式。
- 增定律 `d(D_meta)/dt ≥ 0`：本模块只**观测**压力与其趋势，不做"缩小"运算。
- **不合成单一数值**：任何把三代理加权成一个 `D_meta` 数的企图都违反
  DEV-002a。上层若需单值，只允许**指定单一代理**（见 `pressure()`）。

诚实边界（随代码同行，不可省略）：

1. 三代理只计「**已进入本系统、但未被消化**」的可观测量——**不是**「世界真实
   未发生的事件」，后者不可观测。全部数据来自**已落盘留痕与索引**，
   不重放检索、不读全库正文（热路径约束）。
2. 本模块是**叶子只读**模块：不 import `mdcg` / `mdcos`（防循环依赖），
   只依赖 `fsutil` 原语与注入的 `cg` 对象（duck-typing）；`metacognition`
   惰性导入（调用点内），理由同 `self_state._prediction_face`。
3. 只读：本模块**没有任何写路径**。

开关（三面隔离之一，方案 §2.1/§3）：

- `MDCG_D_META`：D_meta 计算总闸，**默认开启**；置 `0/false/off/no`
  显式回退（关闭计算 → 上层加分退化为 0，回到旧排序）。

三个代理的口径（各自 [0,1]，可核验、可复算）：

| 代理 | 口径 | 数据源（已落盘） |
|---|---|---|
| `events_pressure` | 窗口内新增未消化事件密度 = (近期事件条数 + 探索留痕条数) / (2×window) | `_recent.jsonl` + `_explore.jsonl` 尾部窗口 |
| `unmodeled_growth` | 0.5×存量饱和率 + 0.5×反思窗口未消化率（BLINDSPOT+DEFER 占比） | 索引 `rejected`/`unresolved` 层计数 + `_reflection.jsonl` 窗口 |
| `boundary_violation_rate` | 反思窗口内 (REJECT+BLINDSPOT) / 全部资格态 | `_reflection.jsonl` 窗口 `states` 分布 |

**query-relative 口径不在本模块**：`_neg_coverage` 之类的命中率需要
query+results 现场，留在 `MdCG.reflect`（彼处两者都有）。本模块口径
**库侧 query 无关**，故可在 `autonomy.proposals` 里"每轮一次、循环内复用"。
"""
from __future__ import annotations

import json
import os

from .fsutil import count_jsonl

# ---------------------------------------------------------------- 常量

_ENV_FLAG = "MDCG_D_META"
_FALSY = ("0", "false", "off", "no")
DEFAULT_WINDOW = 200

#: `rejected`/`unresolved` 存量的归一化饱和基准（达到即视为压力 1.0）。
STOCK_FULL = 100

EXPLORE_LOG = "_explore.jsonl"
RECENT_LOG = "_recent.jsonl"
REFLECTION_LOG = "_reflection.jsonl"

#: 未建模层（负记忆两类：失败/否决 + 未解问题）。
UNMODELED_LAYERS = ("rejected", "unresolved")

#: 资格四态（`judge_qualification` 的 states 取值域）。
JUDGE_STATES = ("ACCEPT", "REJECT", "DEFER", "BLINDSPOT")

PROXY_KEYS = ("events_pressure", "unmodeled_growth", "boundary_violation_rate")

_TAIL_BLOCK = 1 << 16          # 尾部反向扫描块（64KiB）
_CACHE_MAX = 64                # 进程内缓存条目上限（超出即清空，无后台线程）
_CACHE = {}


# 生效条件：读取环境变量 MDCG_D_META（大小写不敏感、去首尾空白），其值属于 _FALSY 时返回 False，其余（含未设置）返回 True；
def _enabled() -> bool:
    """D_meta 计算总闸（默认开启）。"""
    return str(os.environ.get(_ENV_FLAG, "")).strip().lower() not in _FALSY


# 生效条件：path 不存在或不是文件、或 window<=0 时返回 []；否则从文件末尾按 _TAIL_BLOCK 分块反向读取，直到累计换行数超过 window 或到达文件头，再按行 json.loads 解析尾部 window 条非空记录（解析失败的行跳过、块首半截行跳过）；
def tail_jsonl(path: str, window: int) -> list:
    """只读 JSONL **尾部最多 window 条**（反向分块，避免全文件 IO）。

    与 `fsutil.read_jsonl` 的区别：不流式扫全文件，读盘量 ≈ O(window)。
    日志文件可能末尾无换行（写者被杀死），此时最后一行会被解析失败丢弃——
    与 `read_jsonl` 同语义（不猜内容）。
    """
    window = int(window)
    if window <= 0:
        return []
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    if size <= 0:
        return []
    data = b""
    pos = size
    try:
        with open(path, "rb") as f:
            while pos > 0 and data.count(b"\n") <= window:
                step = min(_TAIL_BLOCK, pos)
                pos -= step
                f.seek(pos)
                data = f.read(step) + data
    except OSError:
        return []
    out = []
    for raw in data.split(b"\n")[-(window + 1):]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw.decode("utf-8", "replace")))
        except ValueError:
            continue
    return out[-window:]


# 生效条件：cg.index 缺失或不是 dict 时返回 0；否则统计其 "nodes" 中各条目 layer 属于 UNMODELED_LAYERS 的条数（entry 非 dict 或 layer 缺失的条目不计）；
def _layer_stock(cg) -> int:
    """未建模存量：索引中 rejected / unresolved 两层的条目计数（零正文 IO）。"""
    idx = getattr(cg, "index", None)
    nodes = (idx or {}).get("nodes") if isinstance(idx, dict) else None
    if not nodes:
        return 0
    n = 0
    for e in nodes.values():
        if isinstance(e, dict) and e.get("layer") in UNMODELED_LAYERS:
            n += 1
    return n


# 生效条件：cg 的 reflection_log 属性缺失或为假值时回落 os.path.join(cg.root, REFLECTION_LOG)；该文件不存在时返回计数 0；
def _reflection_count(cg) -> int:
    path = getattr(cg, "reflection_log", "") or os.path.join(
        str(getattr(cg, "root", "") or ""), REFLECTION_LOG)
    try:
        return int(count_jsonl(path))
    except OSError:
        return 0


# 生效条件：惰性导入 metacognition 并取窗口内资格态分布；metacognition.trace 返回 ok 为假（无反思留痕）或抛异常时返回 {"total": 0, "states": {}}；
def _state_dist(cg, window: int) -> dict:
    """反思窗口内的资格态分布（复用 metacognition.trace，不重算）。"""
    try:
        from . import metacognition
        tr = metacognition.trace(cg, window=int(window))
    except Exception:                                      # noqa: BLE001
        return {"total": 0, "states": {}}
    if not tr.get("ok"):
        return {"total": 0, "states": {}}
    states = {k: int(v) for k, v in (tr.get("states") or {}).items()}
    return {"total": sum(states.values()), "states": states}


# 生效条件：给定 cg 与 window，返回窗口内新增未消化事件的密度代理（[0,1]），= min(1.0, (recent 尾部条数 + explore 尾部条数) / (2*window))；
def events_pressure(cg, window: int = DEFAULT_WINDOW) -> float:
    """代理一：未被建模的现实总量 → 窗口内新增未消化事件密度。"""
    window = max(1, int(window or DEFAULT_WINDOW))
    recent_path = (getattr(cg, "recent_log", "") or
                   os.path.join(str(getattr(cg, "root", "") or ""), RECENT_LOG))
    explore_path = os.path.join(str(getattr(cg, "root", "") or ""), EXPLORE_LOG)
    n = len(tail_jsonl(recent_path, window)) + len(tail_jsonl(explore_path,
                                                              window))
    return round(min(1.0, n / float(2 * window)), 4)


# 生效条件：给定存量 stock 与资格态分布 dist，返回未建模信号增长的归一化代理（[0,1]），= min(1.0, 0.5*min(1.0, stock/STOCK_FULL) + 0.5*((BLINDSPOT+DEFER)/max(1,total)))；
def unmodeled_growth(stock: int, dist: dict) -> float:
    """代理二：未建模信号持续增长 → 存量饱和率 + 反思窗口未消化率 的均值。"""
    stock_rate = min(1.0, max(0, int(stock)) / float(STOCK_FULL))
    states = (dist or {}).get("states") or {}
    total = int((dist or {}).get("total") or 0)
    bad = 0
    for k in ("BLINDSPOT", "DEFER"):
        try:
            bad += int(states.get(k) or 0)
        except (TypeError, ValueError):
            continue
    return round(min(1.0, 0.5 * stock_rate + 0.5 * bad / float(max(1, total))), 4)


# 生效条件：给定资格态分布 dist，返回边界违反速率代理（[0,1]），= (REJECT+BLINDSPOT)/max(1,total)（无分布即 0.0）；
def boundary_violation_rate(dist: dict) -> float:
    """代理三：边界违反速率 → 反思窗口内 REJECT/BLINDSPOT 占比。"""
    states = (dist or {}).get("states") or {}
    total = int((dist or {}).get("total") or 0)
    bad = 0
    for k in ("REJECT", "BLINDSPOT"):
        try:
            bad += int(states.get(k) or 0)
        except (TypeError, ValueError):
            continue
    return round(bad / float(max(1, total)), 4)


# 生效条件：cg 必需；MDCG_D_META 属于 _FALSY 时三代理恒 0.0、enabled=False 且 note 声明已回退；否则按 (root, 反思条数, 存量, recent 条数, explore 条数, window) 查进程内缓存，未命中则计算三代理并回填（缓存超 _CACHE_MAX 条即清空），返回含四键（三代理 + enabled/window/note）；query/results 仅透传留痕于 note（本轮口径为库侧 query 无关，不计入数值）；
def compute(cg, query=None, results=None, window: int = DEFAULT_WINDOW,
            now=None) -> dict:
    """边界压力向量（三代理各自 [0,1]，**不合成单一 D_meta 数值**）。

    返回：`{"events_pressure", "unmodeled_growth", "boundary_violation_rate",
    "enabled", "window", "note"}`。

    - `enabled=False`（`MDCG_D_META` 显式关闭）时三值为 0.0 且 `note` 声明已回退。
    - `query` / `results` 为**接口对称性**保留：query-relative 的 `_neg_coverage`
      命中留 `reflect`（彼处有现场）；本模块口径库侧 query 无关，
      故可在 `proposals` 每轮一次、循环内复用。
    - 纯读 + 进程内缓存（key 含两日志条数），无写路径、无后台线程、无网络。
    """
    window = max(1, int(window or DEFAULT_WINDOW))
    if not _enabled():
        return {"events_pressure": 0.0, "unmodeled_growth": 0.0,
                "boundary_violation_rate": 0.0, "enabled": False,
                "window": window,
                "note": ("MDCG_D_META 已显式关闭：D_meta 计算回退，三代理恒 0.0"
                         "（上层加分退化 → 旧排序）")}
    root = str(getattr(cg, "root", "") or "")
    refl_n = _reflection_count(cg)
    stock = _layer_stock(cg)
    recent_path = (getattr(cg, "recent_log", "") or
                   os.path.join(root, RECENT_LOG))
    explore_path = os.path.join(root, EXPLORE_LOG)
    recent_n = count_jsonl(recent_path)
    explore_n = count_jsonl(explore_path)
    key = (root, refl_n, stock, recent_n, explore_n, window)
    hit = _CACHE.get(key)
    if hit is None:
        dist = _state_dist(cg, window)
        hit = {
            "events_pressure": events_pressure(cg, window=window),
            "unmodeled_growth": unmodeled_growth(stock, dist),
            "boundary_violation_rate": boundary_violation_rate(dist),
        }
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.clear()
        _CACHE[key] = hit
    note = ("边界压力向量：三代理各自 [0,1]、**不合成单值**（DEV-002a）；"
            "只计「进入系统但未被消化」的事件，不是世界真实未发生事件；"
            "不参与 _compute_d（D_task 口径零变更）")
    if query is not None:
        note += "；query 已透传（本轮口径为库侧 query 无关，不计入数值）"
    return {
        "events_pressure": hit["events_pressure"],
        "unmodeled_growth": hit["unmodeled_growth"],
        "boundary_violation_rate": hit["boundary_violation_rate"],
        "enabled": True, "window": window,
        "note": note,
    }


# 生效条件：vec 为 dict 且其 key（缺省 "unmodeled_growth"）的值为 int/float 时返回裁剪到 [0,1] 的 float，否则返回 0.0；
def pressure(vec, key: str = "unmodeled_growth") -> float:
    """取**单一指定代理**作单值用途（禁止三代理加权合成，DEV-002a）。"""
    if not isinstance(vec, dict):
        return 0.0
    v = vec.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return 0.0
    return round(max(0.0, min(1.0, float(v))), 4)


# 生效条件：prev 或 cur 为假值时返回 None；否则返回三代理的逐字段差（cur-prev，round 4）字典；
def diff(prev, cur) -> dict:
    """逐字段差（供 `reflect` 落 `d_meta_delta`；首条无前值时返回 None）。"""
    if not prev or not cur:
        return None
    out = {}
    for k in PROXY_KEYS:
        try:
            out[k] = round(float(cur.get(k) or 0.0) - float(prev.get(k) or 0.0), 4)
        except (TypeError, ValueError):
            out[k] = 0.0
    return out


# 生效条件：不适用（无必需形参与分支），恒定返回本模块的自描述 dict（module/role/theory/proxies/constraints/knobs）；
def catalog() -> dict:
    """自描述：三代理口径、诚实边界与开关（防文档与实现漂移）。"""
    return {
        "module": "d_meta",
        "role": "D_meta 结构性投影（边界压力向量，三代理各自 [0,1]，不合成单值）",
        "theory": {
            "dev_002": "D_task=图上操作性距离；D_meta=未被建模的现实总量——不互换",
            "dev_002a": "可新增投影链路，不得并入 _compute_d；不得加权合成单值",
            "increasing": "d(D_meta)/dt ≥ 0 → 只观测趋势，不做缩小运算",
            "boundary": "审美/创造/非任务探索不由 ΔD·σ(Gain) 定价 → 只做排序加分",
        },
        "proxies": {
            "events_pressure": "窗口内新增未消化事件密度（_recent + _explore 尾窗）",
            "unmodeled_growth": ("0.5×存量饱和率（rejected+unresolved / %d）"
                                 " + 0.5×反思窗口未消化率（BLINDSPOT+DEFER）"
                                 % STOCK_FULL),
            "boundary_violation_rate": "反思窗口内 (REJECT+BLINDSPOT)/全部资格态",
        },
        "default_proxy_for_single_value": "unmodeled_growth",
        "knobs": {"env_gate": _ENV_FLAG, "default_enabled": True,
                  "default_window": DEFAULT_WINDOW,
                  "stock_full": STOCK_FULL},
        "constraints": [
            "只读：无写路径；不 import mdcg / mdcos（叶子模块，防循环依赖）",
            "不参与 _compute_d（D_task 口径零变更）",
            "不合成单一 D_meta 数值（DEV-002a）；单值只允许指定单一代理",
            "代理只计「进入系统但未被消化」的事件，不是世界真实未发生事件",
        ],
        "faces": ["compute", "pressure", "diff", "tail_jsonl", "catalog"],
    }
