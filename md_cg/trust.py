# -*- coding: utf-8 -*-
"""md_cg · 可验证记忆单元（验证态状态机 + 依赖图 + 双时间轴）

把「可信度」从散文式描述，变成**显式、可查询、可传播、可输出**的结构化状态。
三件事：

1. **验证态持续化**——`verification_state` ∈ (unverified / verified /
   expired / doubted / rechecking)，随验证动作与依赖变动**流转**，不是一次性
   布尔开关；状态落 `frontmatter.verification_state`（节点 md 是唯一真源），
   索引快照同名透出（免读文件可查）。
2. **依赖声明与失效传播**——单元显式声明它依赖谁（`depends_on`）；被依赖单元
   被修改/证伪时，**直接下游立即同步标为 doubted**（一跳，低成本）；**多跳**
   交由 `propagate()` 后台巡检重算，不阻塞写入与查询。
3. **双时间轴**——既有「何时不再成立」（`valid_until`）之外补「何时开始成立」
   （`valid_from`），使时效区间可判定：未生效 / 生效中 / 已过期。

与 `lifecycle.py` 刻意分层（同构实现、**正交语义**，禁跨套复用常量）：
  · `lifecycle.py` = 节点**生命周期**（active/converged/demoted/archived）；
  · 本模块        = 节点**验证态**（unverified/verified/expired/doubted/rechecking）。
两者都是「单点裁决 + 单点推进 + 硬拒入口」，但状态集不共享、`_RANK` 不共享。

与 `provenance.py` 刻意分层：
  · `provenance.py` = 节点**派生血缘**（「它由谁派生」，`_link.jsonl`）；
  · 本模块          = 节点**依赖与证据强度**（「它靠谁成立、现在还成不成立」，
    `_trust.jsonl`）。血缘是既成事实，依赖是可失效假设——不可混用。

三条纪律（对齐 G8 裁定与 lifecycle 口径）：
  1. **台账失败降级不阻断写**——`mark_dependents()` 永不抛，写不进只留痕告警；
  2. **历史不回填**——存量缺 `verification_state` 视为 `unverified`，`backfill()`
     只在显式调用时把「缺省」变「显式」；
  3. **巡检只读**——`patrol()` 检出悬空依赖/过期节点但**不自动改状态、不删节点**。

命名避让（既有先例）：字段**不叫 `state`**——该名已被裁决四态
（ACCEPT/REJECT/DEFER/BLINDSPOT）占用，`lifecycle_state` 的先例同此动机。

零第三方依赖（D-005）。
"""
from __future__ import annotations

import os
import time

from .fsutil import append_jsonl, read_jsonl

#: 验证态全集。语义：
#:   unverified  未验证（默认；存量缺字段即视为它）
#:   verified    已验证（有验证方式与证据，且依赖未动）
#:   doubted     存疑（**依赖的地基动了**——异常的新定义）
#:   rechecking  重新验证中（复核进行态）
#:   expired     已过期（超出时效区间，或证据整体失效）
STATES = ("unverified", "verified", "doubted", "rechecking", "expired")

#: frontmatter 字段名（索引快照同名透出）。刻意避开 `state`——与 lifecycle 同动机。
STATE_FIELD = "verification_state"
#: 验证履历字段（frontmatter 侧历史，滚动保留最近 HISTORY_KEEP 条）
HISTORY_FIELD = "verification_history"
HISTORY_KEEP = 20
#: 依赖声明字段（CCG「子功能」槽的落字段）
DEPS_FIELD = "depends_on"
#: 双时间轴（**效力时间**）字段。2026-09-19 阶段一：规范名迁移到
#: `effective_from` / `effective_until`（**新写入落规范键**），历史名
#: `valid_from` / `valid_until` 保留为**读取侧回落别名**（存量不迁移、零破坏）。
FROM_FIELD = "valid_from"
UNTIL_FIELD = "valid_until"
#: 规范名（新写入落此；读取时优先于同名族旧键）
EFFECTIVE_FROM_FIELD = "effective_from"
EFFECTIVE_UNTIL_FIELD = "effective_until"
#: 信念时间（体系**何时确认此条**）：取代/审核的锚。
#: **不是效力语义**——它既不是「已结束」也不是「尚未开始」，
#: 故绝不并入 `scrub._EXPIRY_KEYS`（已结束族）或 `scrub._NOT_YET_KEYS`（未生效族）。
BELIEVED_FIELD = "believed_at"
#: 过期时刻（写盘冗余：由 `effective_until` 派生落盘，供审计/对账直读）。
EXPIRED_FIELD = "expired_at"

#: 端点取值优先级（**规范键优先、别名回落**，2026-09-19 阶段一）。
#: 与 `scrub._NOT_YET_KEYS` / `scrub._EXPIRY_KEYS` 同键族——两处共用同一套别名，
#: 任一侧新增键须同步另一侧（交叉守卫测试 test_validity_filter 守住）。
FROM_ALIASES = (EFFECTIVE_FROM_FIELD, FROM_FIELD, "valid_since", "starts_at")
UNTIL_ALIASES = (EFFECTIVE_UNTIL_FIELD, UNTIL_FIELD,
                 "expires_at", "expire_at", "expiry", "deadline")
#: 验证态迁移审计（append-only，与 _lifecycle.jsonl / _maintain.jsonl 同风格）
AUDIT_FILE = "_trust.jsonl"

#: 降级序位（用于「受保护豁免降级」判定）。verified 最高，doubted/expired 更低。
_RANK = {"verified": 0, "rechecking": 1, "unverified": 1, "doubted": 2, "expired": 3}

#: 合法迁移表。刻意不收录的（即拒绝的）：
#:   verified → unverified（回落未验证：证据已存在，只应「存疑」而非「清零」）
#:   doubted  → expired（跳级：存疑未经复核不得直接判过期）
#: 注：`unverified → doubted` **收录**——两条路都真实到达这里：①上游变动波及一个
#: 从未验证过的下游（「地基动了」对未验证者同样成立）；②未验证节点收到**负证据**
#: （证据削弱本身就是存疑的依据，比停在「未验证」更准确）。
TRANSITIONS = frozenset({
    ("unverified", "verified"),
    ("unverified", "doubted"),
    ("unverified", "rechecking"),
    ("unverified", "expired"),
    ("verified", "doubted"),
    ("verified", "rechecking"),
    ("verified", "expired"),
    ("doubted", "rechecking"),
    ("doubted", "verified"),
    ("rechecking", "verified"),
    ("rechecking", "doubted"),
    ("rechecking", "unverified"),
    ("rechecking", "expired"),
    ("expired", "rechecking"),
    ("expired", "verified"),
})

#: 依赖边上限（单节点直接下游数）；超出即拒收，防「依赖声明写成噪声」。
MAX_DEPS = 32
#: 多跳传播的节点上限（对齐 subgraph.MAX_NODES_DEFAULT 的量级）
MAX_NODES_DEFAULT = 500


class TrustError(Exception):
    """非法验证态迁移 / 依赖声明非法（写路径用 `require_transition` 直接抛）。"""

    def __init__(self, src, dst, code, reason):
        super().__init__(f"非法验证态迁移 {src}→{dst}（{code}）：{reason}")
        self.src, self.dst, self.code, self.reason = src, dst, code, reason


# ---------------------------------------------------------------- 纯函数裁决

def state_of(fm) -> str:
    """frontmatter → 验证态；缺字段或未知值 → "unverified"（存量兼容，不猜测）。"""
    if not isinstance(fm, dict):
        return "unverified"
    s = fm.get(STATE_FIELD)
    return s if s in STATES else "unverified"


def is_downgrade(src: str, dst: str) -> bool:
    """是否向「更低可信度」迁移（verified < unverified/rechecking < doubted < expired）。"""
    return _RANK.get(dst, 0) > _RANK.get(src, 0)


def can_transition(src, dst) -> bool:
    """迁移是否合法（含幂等；未知 src 按 unverified 处理）。"""
    src = src if src in STATES else "unverified"
    if dst not in STATES:
        return False
    if src == dst:
        return True                     # 幂等：同状态是 no-op
    return (src, dst) in TRANSITIONS


def check(src, dst, protected: bool = False, override: bool = False):
    """迁移合法性裁决 → `(ok, code, reason)`。**唯一裁决点**（纯函数，无 IO）。

    code 取值：`ok` / `noop`（同状态，不写盘）/ `unknown_state` /
    `illegal_transition` / `protected`。
    """
    src = src if src in STATES else "unverified"
    if dst not in STATES:
        return False, "unknown_state", f"未知验证态 {dst!r}（允许：{STATES}）"
    if src == dst:
        return True, "noop", "验证态未变（幂等，不写盘）"
    if (src, dst) not in TRANSITIONS:
        legal = "、".join(f"{a}→{b}" for a, b in sorted(TRANSITIONS))
        return False, "illegal_transition", (
            f"{src}→{dst} 不在合法迁移表内（允许：{legal}）——"
            "验证态只沿「验证/存疑/复核/过期」四条路径流转，跨级迁移一律拒绝")
    if is_downgrade(src, dst) and protected and not override:
        return False, "protected", (
            f"受保护节点不接受降级迁移 {src}→{dst}（保护 = 不可轻弃）；"
            "确需降级请显式 override=True")
    return True, "ok", f"{src}→{dst} 合法"


def require_transition(src, dst, protected: bool = False, override: bool = False):
    """合法则返回 code，非法则抛 `TrustError`（写路径的硬拒入口）。"""
    ok, code, why = check(src, dst, protected=protected, override=override)
    if not ok:
        raise TrustError(src if src in STATES else "unverified", dst, code, why)
    return code


def stamp(fm: dict, dst: str, reason: str = None, actor: str = None,
          evidence: str = None, method: str = None, trigger: str = None,
          override: bool = False):
    """在给定 frontmatter 上**就地**推进验证态（无 IO）→ `(ok, code, why)`。

    与 `set_state()` 共用同一裁决点（`check`），供**需与其他字段同批落盘**的
    收口点使用（写入时一次写盘改依赖/时间轴/验证态）。
    """
    src = state_of(fm)
    prot = bool(fm.get("protected") or fm.get("immutable"))
    ok, code, why = check(src, dst, protected=prot, override=override)
    if not ok or code == "noop":
        return ok, code, why
    fm[STATE_FIELD] = dst
    rec = {"at": time.time(), "from": src, "to": dst, "reason": reason,
           "actor": actor, "trigger": trigger}
    if method:
        rec["method"] = str(method)[:120]
    if evidence:
        rec["evidence"] = str(evidence)[:300]
    hist = list(fm.get(HISTORY_FIELD) or [])
    hist.append(rec)
    fm[HISTORY_FIELD] = hist[-HISTORY_KEEP:]
    if method:
        fm["verification_method"] = str(method)[:120]
    if evidence:
        fm["verification_evidence"] = str(evidence)[:300]
    fm["verified_at"] = rec["at"]
    return True, code, why


# ---------------------------------------------------------------- 双时间轴

def parse_time(value):
    """时间值 → epoch 秒；不可解析返回 None（**不猜测**）。

    接受：数字（epoch 秒）/ 日期或日期时间字符串（ISO 8601，宽松：空格分隔、
    `Z` 后缀、日期精度都容忍）。纯标准库实现。
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    t = s.replace("/", "-").replace("T", " ")
    if t.endswith("Z"):
        t = t[:-1].strip()
    fmts = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")
    for f in fmts:
        try:
            return time.mktime(time.strptime(t, f))
        except ValueError:
            continue
    return None


def first_endpoint(fm, keys):
    """按 `keys` 优先级取首个**可解析**端点 → `(epoch, key)`；全链无值 → `(None, None)`。

    单点定义「规范键优先、别名回落」的取值口径：某键**存在但不可解析**时继续回落
    （而非按 None 定案）——「写坏了的时间值」不得遮蔽同族另一个合法键。
    """
    if not isinstance(fm, dict):
        return None, None
    for k in keys:
        if k in fm:
            ts = parse_time(fm.get(k))
            if ts is not None:
                return ts, k
    return None, None


def validity(fm, now: float = None):
    """双时间轴判定 → `(kind, start, end)`。

    kind ∈ `unknown`（无时间轴约束）/ `not_yet`（未生效）/ `active`（生效中）/
    `expired`（已过期）。任一端点不可解析 → 该端点按 None 处理（不猜测、不误判）。

    端点取值（2026-09-19 阶段一）：**规范键优先、别名回落**——
    起点 `effective_from` > `valid_from` > `valid_since` > `starts_at`；
    终点 `effective_until` > `valid_until` > `expires_at` > `expire_at` > `expiry` > `deadline`。
    `believed_at`（信念时间）**不参与**本判定：它是「体系何时确认此条」（取代/审核的锚），
    不是效力端点——并入任一方向都会把「已确认」误判成「已生效/已失效」。
    """
    if not isinstance(fm, dict):
        return "unknown", None, None
    start, _sk = first_endpoint(fm, FROM_ALIASES)
    end, _ek = first_endpoint(fm, UNTIL_ALIASES)
    if start is None and end is None:
        return "unknown", None, None
    t = time.time() if now is None else float(now)
    if start is not None and t < start:
        return "not_yet", start, end
    if end is not None and t > end:
        return "expired", start, end
    return "active", start, end


def believed_at(fm) -> float:
    """信念时间（体系**何时确认此条**）→ epoch 秒；缺字段/不可解析 → None（不猜测）。

    用途：取代（supersede）/ 审核的排序锚——「谁更晚被确认」是判定新旧的正路；
    **不得**拿 `valid_from`/`valid_until` 代替（那是事实在任务世界里何时有效，
    与体系何时知道它无关）。
    """
    if not isinstance(fm, dict):
        return None
    return parse_time(fm.get(BELIEVED_FIELD))


def is_expired(fm, now: float = None) -> bool:
    """`validity` 的布尔快捷：是否「**已过期**」。

    只判 `expired`——`not_yet`（尚未生效）**不算**：两者语义相反
    （见 `scrub._NOT_YET_KEYS` 纪律「`valid_from` 绝不并入 `_EXPIRY_KEYS`」），
    「尚未开始」不等于「已失效」。无时间轴 / 端点不可解析 → False（不猜测、不误杀）。
    """
    return validity(fm, now=now)[0] == "expired"


def time_window_msg(fm, now: float = None) -> str:
    """时效判定的一句话（空串表示无时间轴约束）。**点名实际命中的键**（含别名）。"""
    kind, start, end = validity(fm, now=now)
    if kind == "unknown":
        return ""
    if kind == "not_yet":
        _ts, k = first_endpoint(fm, FROM_ALIASES)
        return f"未生效（{k or FROM_FIELD} 未到）"
    if kind == "expired":
        _ts, k = first_endpoint(fm, UNTIL_ALIASES)
        return f"已过期（{k or UNTIL_FIELD} 已过）"
    return "时效内"


# ---------------------------------------------------------------- 时间算子（阶段二 4.1）

#: 时间轴（**封闭枚举**）。两条轴物理隔离、语义不可互换（同 `believed_at` 的隔离纪律）：
#:   effective 效力轴——这条事实**何时开始/不再成立**（`effective_from/until` 及别名）
#:   observed  观察轴——这条记忆**何时被观测/事件何时发生**（`temporal` / `time_window`）
#: 不设**隐式**默认轴：入口在「启用时间算子但未指定轴」时回落 `effective`
#: （与既有 `validity=` 语义连续），但轴本身永远由调用方显式决定。
TIME_AXES = ("effective", "observed")

#: 时间算子（**封闭枚举**，拒收未知名）：候选轴端点 与 查询端点 的比较关系。
#: 缺省（不给 operator）= **区间重叠**语义，见 `window_match`。
TIME_OPERATORS = ("gt", "gte", "eq", "lte", "lt")

#: 观察轴字段名（与 `stg._interval` 同源口径，**不新增第二套解析**）。
OBSERVED_TIME_FIELD = "temporal"
OBSERVED_WINDOW_FIELD = "time_window"


def time_axis_of(axis) -> str:
    """轴名归一 → `"effective"` / `"observed"`；`None` → `"effective"`；
    其余（含 `"believed"`）→ `ValueError`（**fail-closed，不静默降级**）。

    与 `_stg_call`「不做签名推导——猜错会静默返回错误视图，比报错更贵」同风格：
    轴写错时必须报错，因为静默按另一条轴过滤会产出**无法复算**的结果集。
    """
    if axis is None:
        return "effective"
    a = str(axis).strip().lower()
    if a in TIME_AXES:
        return a
    raise ValueError(f"未知 time_axis {axis!r}（允许：{TIME_AXES}）")


def time_window_of(fm, axis: str = "effective"):
    """按轴取候选时间窗口 → `(start, end)`；不可判定 → `(None, None)`（不猜测）。

    · `effective`：效力轴，走 `first_endpoint(FROM_ALIASES/UNTIL_ALIASES)`
      （规范键优先、别名回落，与 `validity` **同源**）；
      缺字段/不可解析 → 该侧 `None`（= 无界，与 `validity` 的「不误判」口径一致）。
    · `observed`：观察轴，与 `stg._interval` **同源口径**——`temporal`（事件时刻）优先，
      缺失才回退 `condition_space.time_window`（观测窗）；任一端不可解析 → `(None, None)`
      （与 `_interval` 的「整体不可用」语义一致）。

    `believed_at` **永不参与**（`BELIEVED_FIELD` 不出现于任何轴）。
    """
    if not isinstance(fm, dict):
        return None, None
    if time_axis_of(axis) == "observed":
        t = fm.get(OBSERVED_TIME_FIELD)
        if t is not None:
            ts = parse_time(t)
            if ts is not None:
                return ts, ts
        # 兼容两种载体形态：**fm**（`condition_space.time_window`）与**索引扁平快照**
        # （`time_window` 平铺在 entry 上，见 `mdcg._scan_nodes`/`_stage`）。
        # 只读嵌套会让「按 entry 过滤」的路径永不命中（同类坑：S2 时间门控，
        # mdcg.py L639 已记「直接读 cs 会让门控永不生效」）。
        cs = fm.get("condition_space") or {}
        tw = fm.get(OBSERVED_WINDOW_FIELD)
        if tw is None and isinstance(cs, dict):
            tw = cs.get(OBSERVED_WINDOW_FIELD)
        if isinstance(tw, (list, tuple)) and len(tw) == 2:
            s, e = parse_time(tw[0]), parse_time(tw[1])
            if s is None or e is None:
                return None, None
            return s, e
        return None, None
    start, _sk = first_endpoint(fm, FROM_ALIASES)
    end, _ek = first_endpoint(fm, UNTIL_ALIASES)
    return start, end


def _op_ok(cand, q, op) -> bool:
    """单个端点比较；任一端不可解析 → False（缺字段的处置归**轴策略**，此处不猜测）。"""
    if cand is None or q is None:
        return False
    if op == "gt":
        return cand > q
    if op == "gte":
        return cand >= q
    if op == "eq":
        return cand == q
    if op == "lte":
        return cand <= q
    if op == "lt":
        return cand < q
    return False                      # 未知算子：入口已 fail-closed，此处保守拒


def window_match(cand_start, cand_end, q_start=None, q_end=None,
                 start_op: str = None, end_op: str = None) -> bool:
    """候选窗口与查询窗口是否匹配（§1.2 B1/B2 的**唯一实现点**，纯函数）。

    两种模式由「是否给 operator」**显式分叉**（不允许隐式混用——混用会产出
    「无法复算」的过滤，违反白箱）：

    · **重叠模式**（`start_op`/`end_op` 均为 `None`）：候选窗口与查询窗口有交集
      即命中（记忆窗口是**区间**不是点）。查询端点缺省 = 该侧**无界**（不隐含 now）。
    · **端点模式**（至少给一个 operator）：对**显式启用的侧**做 `op(cand端, q端)`；
      一侧未给 operator 但**给了该侧查询端点**时，用 B1 缺省（起点 `gte` / 终点 `lte`）；
      该侧查询端点也没有 → **不约束该侧**。

    「未给 operator 且未给查询端点 → 不约束」是刻意的：若一律回落到 B1 缺省再比较，
    `_op_ok(cand, None, op)` 恒伪，于是 `start_operator="gte" + start_time=T`
    （单端算子，合法调用）会静默返回**空集**——把「只筛起点」误答成「没有匹配」。
    端点模式下候选的该侧端点不可解析 → `False`（该侧无法比较，不猜）。

    候选窗口两端皆不可解析 → `False`（该节点「无时间轴可判」）——是否因此剔除
    由**轴的策略**决定（效力轴 fail-open / 观察轴 fail-closed，见候选过滤处）。
    """
    cs, ce = parse_time(cand_start), parse_time(cand_end)
    if cs is None and ce is None:
        return False
    qs, qe = parse_time(q_start), parse_time(q_end)
    if start_op is None and end_op is None:
        if qs is not None and ce is not None and ce < qs:
            return False
        if qe is not None and cs is not None and cs > qe:
            return False
        return True
    if start_op is not None or qs is not None:
        if not _op_ok(cs, qs, start_op or "gte"):
            return False
    if end_op is not None or qe is not None:
        if not _op_ok(ce, qe, end_op or "lte"):
            return False
    return True


def check_time_args(start_time=None, end_time=None, start_operator=None,
                    end_operator=None, time_axis=None):
    """时间算子入参 fail-closed 校验 → `(enabled, axis, why)`。

    **入口（`mdcg.search` / `entity_contexts`）与库层共用的唯一校验点**
    （避免两处各写一套、口径漂移）。三则误用一律拒（`why` 非空即应抛
    `ValueError`，不静默忽略——与 `_stg_call` 同风格）：

      1. 只给 operator 而不给对应的 `start_time`/`end_time`；
      2. `time_axis` 非 `{"effective","observed"}`（含 `"believed"`）；
      3. `start_time > end_time`。

    未启用（五参全 `None`）→ `(False, None, "")`（默认路径零变更）。
    """
    if time_axis is not None and str(time_axis).strip().lower() not in TIME_AXES:
        return False, None, (f"未知 time_axis {time_axis!r}（允许：{TIME_AXES}）——"
                             "轴必须显式且合法，静默按另一条轴过滤会产出无法复算的结果")
    for op, val, nm in ((start_operator, start_time, "start_operator/start_time"),
                        (end_operator, end_time, "end_operator/end_time")):
        if op is None:
            continue
        if str(op).strip().lower() not in TIME_OPERATORS:
            return False, None, (f"未知算子 {op!r}（允许：{TIME_OPERATORS}）")
        if val is None:
            return False, None, f"给了 {nm.split('/')[0]} 但缺 {nm.split('/')[1]}（不猜默认值）"
    s, e = parse_time(start_time), parse_time(end_time)
    if start_time is not None and s is None:
        return False, None, f"start_time 不可解析：{start_time!r}"
    if end_time is not None and e is None:
        return False, None, f"end_time 不可解析：{end_time!r}"
    if s is not None and e is not None and s > e:
        return False, None, f"start_time({s}) > end_time({e})：空窗口，拒绝"
    enabled = any(x is not None for x in (start_time, end_time,
                                          start_operator, end_operator))
    if not enabled:
        return False, None, ""
    return True, time_axis_of(time_axis), ""


def window_matches_node(fm, axis, q_start, q_end, start_op=None, end_op=None):
    """候选节点按轴取窗后做 `window_match` → `(matched, missing)`。

    `missing=True` 表示该节点在**该轴上不可判定**（窗口两端皆 `None`）——
    调用方据此执行轴策略：效力轴 fail-open（保留）、观察轴 fail-closed
    （剔除并计入 `axis_missing`）。策略按**保证强度**定，不按「一致好看」定：
    效力轴字段是可选声明，观察轴字段由写入侧保证存在。
    """
    cs, ce = time_window_of(fm, axis)
    if cs is None and ce is None:
        return False, True
    return window_match(cs, ce, q_start, q_end, start_op, end_op), False


def time_filter_meta(axis=None, mode="overlap", start=None, end=None,
                     start_operator=None, end_operator=None, dropped=0,
                     axis_missing=0, applied=False) -> dict:
    """`meta["time_filter"]` 审计块（**五键齐备**，可复算）：

    `dropped + 存活数 == 候选数` 由调用方保证；`axis_missing` 单独记账，
    使「观察轴缺字段被剔除」的条数可查（静默放行会把数据异常藏起来）。
    """
    return {"axis": axis, "mode": mode, "start": start, "end": end,
            "start_operator": start_operator, "end_operator": end_operator,
            "dropped": int(dropped), "axis_missing": int(axis_missing),
            "applied": bool(applied)}


def filter_by_time(entries, axis, q_start, q_end, start_op=None, end_op=None):
    """按轴过滤候选 → `(kept, dropped, axis_missing)`。**候选层唯一过滤点**。

    轴策略按**字段保证强度**定（不按「行为一致好看」定）：
      · `effective` 效力轴：`effective_from/until` 是**可选声明**（多数节点没有）
        → 不可判定一律 fail-open（保留）——否则「没写时效 = 被过滤掉」，
        会把沉默当否认；
      · `observed` 观察轴：`temporal` / `time_window` 由**写入侧保证**存在
        （add 缺省填观测窗）→ 不可判定一律 fail-closed（剔除并计入
        `axis_missing`，使数据异常可查而非静默放行）。
    """
    kept, dropped, missing = [], 0, 0
    for e in entries:
        m, miss = window_matches_node(e, axis, q_start, q_end, start_op, end_op)
        if miss:
            if axis == "observed":
                dropped += 1
                missing += 1
            else:
                kept.append(e)
            continue
        if m:
            kept.append(e)
        else:
            dropped += 1
    return kept, dropped, missing


# ---------------------------------------------------------------- 依赖声明

def as_deps(value) -> list:
    """把单值 / 序列 / 逗号串统一成**去重、排序**的节点 id 列表（上限 MAX_DEPS）。

    容错口径（写路径的入参形态不由本模块决定，收窄会误伤）：
      · `None` / 空串 / 纯空白项 → 丢弃（不是目标，也不是「声明了依赖」）；
      · 半角/全角逗号串 → 切分（`"a, b"` 与 `["a", "b"]` 等价）；
      · 排序的动机：依赖是**集合语义**（声明顺序不承载信息），排序让 fm 与
        索引快照对同一组依赖恒等——比较/去重/审计不再依赖声明顺序。
    """
    if value is None:
        return []
    items = list(value) if isinstance(value, (list, tuple, set)) else [value]
    out = []
    for x in items:
        if x is None:
            continue
        for s in str(x).replace("，", ",").split(","):
            s = s.strip()
            if s and s not in out:
                out.append(s)
    out.sort()
    return out[:MAX_DEPS]


def deps_of(cg, nid: str) -> list:
    """读某节点声明的依赖（**零读文件**：索引快照缺失才回读节点）。"""
    e = ((getattr(cg, "index", None) or {}).get("nodes") or {}).get(nid) or {}
    deps = as_deps(e.get(DEPS_FIELD))
    if deps:
        return deps
    node = cg.get(nid)
    if not node:
        return []
    return as_deps((node.get("frontmatter") or {}).get(DEPS_FIELD))


def invalidate_cache(cg) -> None:
    """作废反查缓存（写/删节点后调用；下次读时增量重建）。"""
    try:
        cg.__dict__.pop("_trust_dependents", None)
    except Exception:                                  # noqa: BLE001
        pass


def dependents_index(cg, refresh: bool = False) -> dict:
    """反查索引：`{被依赖节点: [依赖它的节点…]}`（「谁依赖我」）。

    缓存挂在 cg 实例上（与 `subgraph` 的缓存化做法同构）；`refresh=True` 强制重建。
    """
    if not refresh:
        cached = getattr(cg, "_trust_dependents", None)
        if isinstance(cached, dict):
            return cached
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    idx = {}
    for nid, e in nodes.items():
        for p in as_deps((e or {}).get(DEPS_FIELD)):
            idx.setdefault(p, []).append(nid)
    for k in idx:
        idx[k].sort()
    try:
        cg._trust_dependents = idx
    except Exception:                                  # noqa: BLE001
        pass
    return idx


def _record(cg, rec: dict) -> None:
    """台账追加（best-effort：失败静默，**绝不阻断写路径**）。"""
    try:
        append_jsonl(os.path.join(cg.root, AUDIT_FILE), rec)
    except Exception:                                  # noqa: BLE001
        pass


# ---------------------------------------------------------------- 推进

def _sync_index(cg, node_id, fm) -> None:
    """把验证态同步进索引快照（免读文件可查）；无索引实现时静默跳过。"""
    idx = getattr(cg, "index", None)
    if not isinstance(idx, dict):
        return
    e = (idx.get("nodes") or {}).get(node_id)
    if e is None:
        return
    e[STATE_FIELD] = fm.get(STATE_FIELD)
    dirty = getattr(cg, "_dirty", None)
    if isinstance(dirty, dict):
        dirty[node_id] = e
    flush = getattr(cg, "flush", None)
    if callable(flush):
        flush()


def set_state(cg, node_id: str, dst: str, reason: str = None, actor: str = None,
              evidence: str = None, method: str = None, trigger: str = None,
              override: bool = False) -> dict:
    """推进一个节点的验证态（**唯一推进入口**）。

    非法迁移不走异常而是返回 `{"ok": False, "error": <code>, ...}`（负路由）。
    幂等迁移返回 `changed=False` 且不写盘。
    """
    node = cg.get(node_id)
    if not node:
        return {"ok": False, "error": "node_not_found", "node_id": node_id}
    fm = dict(node.get("frontmatter") or {})
    src = state_of(fm)
    ok, code, why = stamp(fm, dst, reason=reason, actor=actor, evidence=evidence,
                          method=method, trigger=trigger, override=override)
    base = {"node_id": node_id, "from": src, "to": dst, "code": code}
    if not ok:
        return {**base, "ok": False, "error": code, "reason": why}
    if code == "noop":
        return {**base, "ok": True, "changed": False, "reason": why}
    at = fm[HISTORY_FIELD][-1]["at"]
    cg._write_node(node_id, os.path.join(cg.root, node["path"]), fm,
                   node.get("content") or "")
    _sync_index(cg, node_id, fm)
    _record(cg, {"t": at, "action": "set_state", "node_id": node_id,
                 "from": src, "to": dst, "reason": reason, "actor": actor,
                 "method": method, "trigger": trigger, "override": bool(override)})
    if fm.get(DEPS_FIELD):
        invalidate_cache(cg)
    return {**base, "ok": True, "changed": True, "reason": why, "at": at}


# ---------------------------------------------------------------- 失效传播

def mark_dependents(cg, node_id: str, reason: str = None, *, apply: bool = True,
                    actor: str = "system", trigger: str = None,
                    depth: int = 1, override: bool = False) -> dict:
    """**一跳同步传播**：把直接下游标为 `doubted`（异常的新定义）。

    根因口径：异常不再仅是「内容错」，而是「**它所依赖的地基动了**」——被依赖
    单元被修改/证伪时，直接下游立刻产生存疑标记，无需等全库巡检。

    **永不抛**（对齐 provenance G8 纪律：传播失败不得阻断写入）。`apply=False`
    只预演；同状态下游是 no-op（幂等，不写盘、不留痕）。
    """
    try:
        dep_map = dependents_index(cg)
        kids = list(dep_map.get(node_id, []))
        kids.sort()
        if not kids:
            return {"ok": True, "changed": 0, "dependents": [], "apply": bool(apply),
                    "reason": "no_dependents"}
        reason = reason or f"上游 {node_id} 变动"
        planned = [k for k in kids
                   if state_of((cg.index or {}).get("nodes", {}).get(k) or {})
                   != "doubted"]
        if not apply:
            return {"ok": True, "dry_run": True, "changed": 0,
                    "dependents": kids, "planned": len(planned)}
        done, skipped = [], []
        for k in kids:
            r = set_state(cg, k, "doubted", reason=reason, actor=actor,
                          trigger=trigger or f"dep_changed:{node_id}",
                          override=override)
            if r.get("ok") and r.get("changed"):
                done.append(k)
            elif r.get("ok"):
                skipped.append(k)          # 已是 doubted：幂等
            else:
                skipped.append(f"{k}({r.get('error')})")
        return {"ok": True, "changed": len(done), "dependents": kids,
                "updated": done, "skipped": skipped, "apply": True,
                "reason": reason}
    except Exception as exc:                               # noqa: BLE001
        _record(cg, {"t": time.time(), "action": "mark_dependents_degraded",
                     "node_id": node_id, "error": f"{type(exc).__name__}: {exc}",
                     "actor": actor})
        return {"ok": False, "degraded": True, "changed": 0,
                "error": f"{type(exc).__name__}: {exc}"}


def propagate(cg, *, apply: bool = False, max_nodes: int = MAX_NODES_DEFAULT,
              actor: str = "patrol") -> dict:
    """**多跳异步重算**（巡检面，不阻塞写入/查询）。

    BFS 从所有 `expired` / `rechecking` / 显式根源节点出发，把可达下游标
    `doubted`（**只降不升**：复核通过须由人显式 `set_state(verified)`）。
    默认 `apply=False` 只出报表；`max_nodes` 封顶防大库爆炸。

    `doubted` 中间节点的语义（2026-09-20 v14 缺陷 B 修复）：**穿过，但不重复
    标记**。已 doubted 说明它已被标记，无需再标（幂等）；但它**不是传播终点**
    ——「地基动了」的波及范围必须继续往其下游走。旧实现把 doubted 直接
    `continue`（当作终点），于是「先 `mark_dependents` 预演直接下游、再
    `propagate` 正式传播」这一最常见序列会使多跳传播**整体失效**
    （`reachable`/`updated` 全 0）且**无任何报错**。穿过的节点在
    `passed_doubted` 中如实透出（可审计）。

    **`reachable` / `updated` 的口径**（2026-09-20 v15-4 澄清，勿读成「波及集
    大小」）：两者计的是「本次**需要新标记**的节点数」——`apply=False` 时 =
    计划标记数（`planned` 的长度），`apply=True` 时 = 实际标记成功数（`done` 的
    长度）。**穿过的 `doubted` 中继不计入**（它早已被标记，本次幂等跳过）。故
    「本次的完整波及集」= `reachable`（或 `updated`）+ `passed_doubted`，只读
    前者会低估。`roots` 是传播起点（`expired`/`rechecking`），不属于波及集。
    """
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    dep_map = dependents_index(cg)
    roots = []
    for nid, e in nodes.items():
        st = (e or {}).get(STATE_FIELD)
        if st in ("expired", "rechecking"):
            roots.append(nid)
    roots.sort()
    seen, waves, passed = set(roots), [], set()
    frontier, depth = list(roots), 0
    while frontier and len(seen) < int(max_nodes):
        depth += 1
        nxt = []
        for nid in frontier:
            for k in dep_map.get(nid, []):
                if k in seen:
                    continue
                seen.add(k)
                if state_of(nodes.get(k) or {}) == "doubted":
                    passed.add(k)       # 穿过但不重复标记（不是终点）
                nxt.append(k)
                if len(seen) >= int(max_nodes):
                    break
        for k in nxt:
            if k in passed:
                continue                # 已 doubted：无需再标（幂等）
            waves.append({"node_id": k, "depth": depth,
                          "via": sorted(n for n in dep_map if k in dep_map[n]
                                        and n in seen)})
        frontier = nxt
    if not apply:
        return {"ok": True, "dry_run": True, "roots": roots[:50],
                "roots_count": len(roots), "reachable": len(waves),
                "planned": waves[:50], "passed_doubted": sorted(passed)[:20],
                "max_nodes": int(max_nodes),
                "note": "预演：未改盘；只降不升（复核须显式）"}
    done, skipped = [], []
    for w in waves:
        r = set_state(cg, w["node_id"], "doubted",
                      reason="多跳失效传播（上游时间轴/证据失效）",
                      actor=actor, trigger=f"propagate:d{w['depth']}")
        if r.get("ok") and r.get("changed"):
            done.append(w["node_id"])
        elif not r.get("ok"):
            skipped.append(f"{w['node_id']}({r.get('error')})")
    return {"ok": True, "dry_run": False, "roots": roots[:50],
            "roots_count": len(roots), "updated": done, "updated_count": len(done),
            "passed_doubted": sorted(passed)[:20],
            "skipped": skipped[:20], "max_nodes": int(max_nodes)}


# ---------------------------------------------------------------- 巡检 / 回填

# 生效条件：cg 传入即只读遍历 index 快照并返回悬空/未生效/已过期/存疑四类计数与样本，不写盘、不改状态、不抛（index 缺失按空库处理）；
def patrol(cg, *, limit: int = 20, now: float = None) -> dict:
    """只读巡检：悬空依赖 / 时间轴失效 / 存疑积压。**不改状态、不删节点**。

    命名纪律（负记忆，2026-09-19 实测）：本函数**不得叫 `check`**——裁决层已有
    `check(src, dst, ...)`（唯一裁决点）。同模块内同名二次定义会**静默遮蔽**前者，
    `stamp()` 随即调到巡检版并抛 `TypeError`（现场：`set_verification` 整条链断）。
    两者语义分属不同层次（纯函数裁决 vs 全库只读巡检），名字必须分开。
    """
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    known = set(nodes)
    dangling, expired, not_yet, doubted = [], [], [], []
    for nid, e in sorted(nodes.items()):
        for p in as_deps((e or {}).get(DEPS_FIELD)):
            if p not in known:
                dangling.append({"node_id": nid, "missing": p})
        st = (e or {}).get(STATE_FIELD)
        if st == "doubted":
            doubted.append(nid)
        # 时间轴按索引可判定字段粗判（精确判定需 fm，巡检读面只给候选）
        kind = _index_validity(e, now=now)
        if kind == "expired":
            expired.append(nid)
        elif kind == "not_yet":
            not_yet.append(nid)
    return {
        "ok": not dangling,
        "checked": True, "root": cg.root, "nodes": len(known),
        "dangling": dangling[:int(limit)], "dangling_count": len(dangling),
        "expired": expired[:int(limit)], "expired_count": len(expired),
        "not_yet": not_yet[:int(limit)], "not_yet_count": len(not_yet),
        "doubted": doubted[:int(limit)], "doubted_count": len(doubted),
        "readonly": True,
        "note": "只读巡检：悬空依赖/时效仅检出并报告，不自动改状态（处置由人/巡检动作发起）"}


def _index_validity(e, now: float = None) -> str:
    """索引快照口径的时效粗判（索引缺时间字段时返回 unknown，零读文件）。"""
    if not isinstance(e, dict):
        return "unknown"
    return validity(e, now=now)[0]


def backfill(cg, apply: bool = False, limit: int = 5000) -> dict:
    """存量回填：把缺 `verification_state` 的节点显式补成 `unverified`（幂等）。

    缺字段本就按 unverified 解释（`state_of`），故回填**不是让功能工作的前提**，
    而是把「缺省」变成「显式」——索引/审计里从此可直接读到验证态。默认只盘点。
    """
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    missing = []
    for nid, e in list(nodes.items()):
        if len(missing) >= limit:
            break
        if (e or {}).get(STATE_FIELD) in STATES:
            continue
        missing.append(nid)
    missing.sort()
    if not apply:
        return {"ok": True, "dry_run": True, "scanned": len(nodes),
                "missing": len(missing), "planned": missing[:50]}
    done, failed = [], []
    for nid in missing:
        node = cg.get(nid)
        if not node:
            failed.append(nid)
            continue
        fm = dict(node.get("frontmatter") or {})
        fm[STATE_FIELD] = state_of(fm)
        cg._write_node(nid, os.path.join(cg.root, node["path"]), fm,
                       node.get("content") or "")
        _sync_index(cg, nid, fm)
        done.append(nid)
    return {"ok": True, "dry_run": False, "scanned": len(nodes),
            "missing": len(missing), "backfilled": len(done),
            "planned": done[:50], "failed": failed[:20]}


def describe(cg, node_id: str, now: float = None) -> dict:
    """单节点验证态全貌（供 op=status / 状态头渲染）。只读、失败不抛。"""
    try:
        node = cg.get(node_id)
    except Exception:                                      # noqa: BLE001
        node = None
    e = ((getattr(cg, "index", None) or {}).get("nodes") or {}).get(node_id)
    if not node and not e:
        return {"ok": False, "error": "node_not_found", "node_id": node_id}
    fm = (node or {}).get("frontmatter") or {}
    deps = as_deps(fm.get(DEPS_FIELD)) or as_deps((e or {}).get(DEPS_FIELD))
    kind, start, end = validity(fm if fm else (e or {}), now=now)
    dep_map = dependents_index(cg)
    hist = list(fm.get(HISTORY_FIELD) or [])[-5:]
    return {"ok": True, "node_id": node_id,
            "verification_state": state_of(fm if fm else (e or {})),
            "verification_basis": fm.get("verification_basis"),
            "verification_method": fm.get("verification_method"),
            "verified_at": fm.get("verified_at"),
            "depends_on": deps,
            "depended_by": dep_map.get(node_id, []),
            "validity": {"kind": kind, "valid_from": fm.get(FROM_FIELD),
                         "valid_until": fm.get(UNTIL_FIELD),
                         "start": start, "end": end},
            "history": hist,
            "lifecycle_state": fm.get("lifecycle_state"),
            "protected": bool(fm.get("protected") or fm.get("immutable"))}


def summary(cg) -> dict:
    """轻量摘要（只读；失败不抛，避免拖垮 health / 常驻循环）。"""
    try:
        rep = patrol(cg, limit=3)
        return {"dangling": rep["dangling_count"], "expired": rep["expired_count"],
                "not_yet": rep["not_yet_count"], "doubted": rep["doubted_count"],
                "nodes": rep["nodes"], "sample": [
                    f"{r['node_id']}->?{r['missing']}" for r in rep["dangling"]]}
    except Exception:                                      # noqa: BLE001
        return {}


def load_ledger(cg, *, node_id: str = None, limit: int = None) -> list:
    """读验证态台账（跳过坏行；可按节点过滤）。"""
    path = os.path.join(cg.root, AUDIT_FILE)
    out = []
    for r in read_jsonl(path):
        if not isinstance(r, dict):
            continue
        if node_id and r.get("node_id") != node_id:
            continue
        out.append(r)
    return out[:int(limit)] if limit else out


def catalog(root: str = None) -> dict:
    """自描述（供 MCP catalog / 人工核对）。"""
    return {
        "layer": "可验证记忆单元",
        "question": "它还成不成立（验证态 + 依赖 + 时效）",
        "ledger": os.path.join(root, AUDIT_FILE) if root else AUDIT_FILE,
        "states": list(STATES),
        "state_field": STATE_FIELD,
        "history_field": HISTORY_FIELD,
        "deps_field": DEPS_FIELD,
        "time_fields": [FROM_FIELD, UNTIL_FIELD],
        "transitions": sorted(f"{a}→{b}" for a, b in TRANSITIONS),
        "max_deps": MAX_DEPS,
        "max_nodes_default": MAX_NODES_DEFAULT,
        "discipline": {"never_block_write": True, "no_backfill": True,
                       "patrol_readonly": True, "one_hop_sync": True,
                       "multi_hop_async": True, "only_downgrade": True},
        "distinct_from": ("lifecycle.py = 节点生命周期（lifecycle_state）；"
                          "provenance.py = 派生血缘（_link.jsonl）；"
                          "本层 = 验证态与依赖（verification_state/_trust.jsonl）"),
    }
