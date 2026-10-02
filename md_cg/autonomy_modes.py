# -*- coding: utf-8 -*-
"""三档自治**档位单一入口**（设计 v0.2 §三/§四/§五 落码 · 批次②）。

为什么另立本模块：设计 §三 的硬约束①「**单一入口**」——档位是**一个** env 键
（`MDCG_AUTONOMY=plan|confirm|full`，缺省 `confirm`），由**一处**判据函数读取
与解释；不得各模块各读一份。形态照抄 `md_cg/sleep.py:84-170` 的 §4.7「env 表
单一真源」纪律：**改缺省只改本表**，所有读取点只经 `autonomy_env()` /
`mode()`，不得再写第二处字面量（守卫 `test_autonomy_modes.py` 把这条钉死：
全仓 `.py` 里带引号的 `MDCG_AUTONOMY` 只许出现在本模块的 `AUTONOMY_ENV_KEYS`）。

命名避坑：`md_cg/autonomy.py` **已被占用**（信息差驱动探索闭环，
`mdcos.py:3415` 的 `insight(act=explore)` 调用它）——本模块是另一个东西，
故用 `autonomy_modes.py`，且**不**复用 `autonomy` 的任何符号。

档位语义（设计 §三 裁决矩阵，逐格照抄）：

    动作                        计划模式          变更确认（缺省）   完全访问
    A 新增                      允许（须计划步骤） 允许              允许
    B 合并                      允许（须计划步骤） **需确认**         允许
    C 改写                      **需确认**        **需确认**         允许
    D 删除                      **需确认**        **需确认**         允许
    E 权重/生命周期              允许（须计划步骤） 允许              允许

判定函数 `decide(action_class)` 返回 `allow|confirm|forbid`（+可读 hint）：
「允许＝自动执行」「确认＝先出变更单、经裁定后才落」「禁止＝fail-closed 拒并给 hint」。

三条硬约束的落法（设计 §三）：
  ① 单一入口——本模块是**全仓唯一**读 `MDCG_AUTONOMY` 的地方；
  ② 纯加严——接线点一律在**既有资格闸通过之后**（写链在 audit/consistency/gated
     之后、落盘之前；遗忘合并闸在 writelimit/forgetting 裁决之后；删除在
     `protect.guard_forget` 之后），档位**不参与资格判定**，也不放宽任何既有判据；
  ③ 计划外零变更——计划模式下未命中计划步骤的动作 = `forbid`（fail-closed 带
     hint），不静默跳过。**本批计划输入面未落**：无计划（`plan=None`）时
     「须命中计划步骤」的 A/B/E 一律 forbid；C/D 在计划档走「需确认」，与
     变更确认档同格（矩阵如此，无需计划）。

非法 env 值：`mode()` **fail-closed 抛 `AutonomyModeError`**（hint 列合法值），
**不静默降级**到缺省档——静默降级会把「配置打错」变成「放权范围与预期不符」，
正是设计要消灭的那类不实。

本批**不做**（登记留池，交批次③）：前像/影响面/回滚命令/`_protected_history`
通用化；计划输入面；R1–R4 准入读数。
"""
from __future__ import annotations

import hashlib
import os

__all__ = [
    "AutonomyModeError", "AUTONOMY_ENV_DEFAULTS", "AUTONOMY_ENV_KEYS",
    "AUTONOMY_MODES", "DEFAULT_MODE", "ACTION_CLASSES", "ACTION_NAMES",
    "ALLOW", "CONFIRM", "FORBID", "PLAN_STEP", "MATRIX",
    "A_ADD", "B_MERGE", "C_REWRITE", "D_DELETE", "E_WEIGHT",
    "KIND_PROPOSAL", "KIND_MUTATION", "KIND_FIELD",
    "autonomy_env", "mode", "decide", "order_kind", "mutation_view",
    "mutation_payload", "mutation_dedup_key", "propose_mutation",
]

# ---- §三「单一入口」：env 表的**单一真源** --------------------------------
# 纪律：**改缺省只改这里**；读取点只经 `autonomy_env()` / `mode()`。
AUTONOMY_ENV_DEFAULTS = {
    "mode": "confirm",       # 缺省档 = 变更确认（设计 §〇.2 裁定①）
}
#: 各键的 env 名（**全仓唯一的字面量落点**——守卫按此 grep 钉死）。
AUTONOMY_ENV_KEYS = {
    "mode": "MDCG_AUTONOMY",
}
#: 合法档位（顺序即「计划 → 变更确认 → 完全访问」的放权阶梯，设计 §七）。
AUTONOMY_MODES = ("plan", "confirm", "full")
#: 缺省档位的具名常量（= 真源表取值，不另写第二处字面量）。
DEFAULT_MODE = AUTONOMY_ENV_DEFAULTS["mode"]

# ---- 动作类（设计 §一 五类，一手普查口径） --------------------------------
A_ADD = "A"           # 新增节点
B_MERGE = "B"         # 合并（新内容并入既有节点）
C_REWRITE = "C"       # 改写（既有节点就地改）
D_DELETE = "D"        # 删除（软删）
E_WEIGHT = "E"        # 权重与生命周期
ACTION_CLASSES = (A_ADD, B_MERGE, C_REWRITE, D_DELETE, E_WEIGHT)
ACTION_NAMES = {A_ADD: "新增", B_MERGE: "合并", C_REWRITE: "改写",
                D_DELETE: "删除", E_WEIGHT: "权重/生命周期"}

# ---- 判定值 ---------------------------------------------------------------
ALLOW = "allow"       # 自动执行（与改动前逐位一致）
CONFIRM = "confirm"   # 先出变更单，经裁决 accept 后才落
FORBID = "forbid"     # fail-closed 拒，带可执行 hint
#: 矩阵**内部**格标记：该格语义是「允许（须命中计划中的步骤）」——不是判定值，
#: `decide` 会把它按计划命中情况折算成 ALLOW/FORBID（见 decide）。
PLAN_STEP = "plan_step"

#: §三 裁决矩阵（**唯一真源**）：mode → 动作类 → 判定/格标记。
MATRIX = {
    "plan":    {A_ADD: PLAN_STEP, B_MERGE: PLAN_STEP, C_REWRITE: CONFIRM,
                D_DELETE: CONFIRM, E_WEIGHT: PLAN_STEP},
    "confirm": {A_ADD: ALLOW, B_MERGE: CONFIRM, C_REWRITE: CONFIRM,
                D_DELETE: CONFIRM, E_WEIGHT: ALLOW},
    "full":    {A_ADD: ALLOW, B_MERGE: ALLOW, C_REWRITE: ALLOW,
                D_DELETE: ALLOW, E_WEIGHT: ALLOW},
}

# ---- 变更单（设计 §四：复用既有审核队列，靠类型字段区分） ------------------
#: 队列条目类型字段（**落 rec 顶层**）。取值见下；**缺键 = proposal**（存量
#: 条目零迁移：老记录没有这个键，一律按原有提案语义读）。
KIND_FIELD = "kind"
KIND_PROPOSAL = "proposal"   # 原有：新写入未获 ACCEPT 的提案
KIND_MUTATION = "mutation"   # 本批新增：对既有记忆的 B/C/D 变更单
#: 变更单载荷的落点（propose 的既有任意槽 `extra`，沿用 issue50-b 的
#: `extra.defer_reason` 先例——不新增第二套队列字段族）。**为什么不放 rec
#: 顶层**：顶层 `kind` 是设计 §四 明文的「类型字段」（读取面/统计面共用），
#: 而动作类/目标/后像/理由是**单条变更单的业务载荷**，塞顶层会与既有读取方
#: （`_brief` 取 content、accept 分支取 tags/condition_space）抢键名。
MUTATION_SLOT = "mutation"


class AutonomyModeError(ValueError):
    """档位 env 非法（fail-closed：报错 + hint 列合法值，不静默降级）。"""


# 生效条件：name 为 AUTONOMY_ENV_DEFAULTS 的键时按 AUTONOMY_ENV_KEYS[name] 从 environ（缺省 os.environ）取名取值，缺键（None）时回落真源缺省；返回**原始字符串**（不做解释——解释归 mode()）；name 非表内键时抛 KeyError（拼错键名即编程错误，不静默回落）；
def autonomy_env(name: str, environ=None) -> str:
    """§三 env 表的唯一读取出口（原始字面量）。"""
    env = os.environ if environ is None else environ
    v = env.get(AUTONOMY_ENV_KEYS[name])
    return AUTONOMY_ENV_DEFAULTS[name] if v is None else str(v)


# 生效条件：autonomy_env("mode") 去空白转小写后属 AUTONOMY_MODES 时返回该档位名；不属（含空串）时抛 AutonomyModeError（hint 列合法值）——不静默降级；
def mode(environ=None) -> str:
    """当前自治档位（缺省 confirm）。非法值 fail-closed 报错。"""
    raw = autonomy_env("mode", environ)
    m = (raw or "").strip().lower()
    if m not in AUTONOMY_MODES:
        raise AutonomyModeError(
            "非法档位 %s=%r：允许值 %s（缺省 %s）。"
            "本次动作 fail-closed 未执行——不静默降级到缺省档"
            "（静默降级会让「配置打错」伪装成「放权范围与预期不符」）。"
            "改正环境变量后重试即可。"
            % (AUTONOMY_ENV_KEYS["mode"], raw, "|".join(AUTONOMY_MODES),
               DEFAULT_MODE))
    return m


# 生效条件：action_class 归一后属 ACTION_CLASSES（否则抛 ValueError）；plan 命中集 _plan_actions(plan) 为 None（无计划输入）时 A/B/E 判 forbid（带「计划输入面待后续批次」hint），非 None 时命中该动作类判 allow、否则 forbid（计划外零变更）；其余格按 MATRIX 原样返回 allow/confirm；返回 {"action","action_name","mode","decision","hint"}，decision ∈ ALLOW/CONFIRM/FORBID；
def decide(action_class, mode_explicit=None, plan=None, environ=None) -> dict:
    """§三 裁决矩阵判定：返回 allow | confirm | forbid（+ 可读 hint）。

    action_class  —— A/B/C/D/E（大小写不敏感；非法值抛 ValueError）。
    mode_explicit —— 显式档位；None（缺省）时**经唯一入口 `mode()` 读 env**
                     （非法 env 即 fail-closed 抛错）。形参刻意不叫 `mode`：
                    同名会遮蔽模块级唯一入口，`mode(environ)` 就成了对局部名的
                     调用——「单一入口」必须能被静态钉死（见守卫的定点变异）。
    plan          —— 计划（**本批只落最小判定语义**）：None = 无计划输入；
                     可给动作类集合（可迭代，元素为 "A"/"B"… 或含 "action" 键的
                     映射）。计划模式下 A/B/E 只有在命中计划步骤时才 allow。

    调用方**必须**只看 `decision`，不得自行比较档位名（否则就是各读一份）。
    """
    act = str(action_class or "").strip().upper()
    if act not in ACTION_CLASSES:
        raise ValueError("未知动作类：%r（允许：%s）"
                         % (action_class, "/".join(ACTION_CLASSES)))
    m = mode(environ) if mode_explicit is None else _norm_mode(mode_explicit)
    cell = MATRIX[m][act]
    out = {"action": act, "action_name": ACTION_NAMES[act], "mode": m,
           "decision": cell, "hint": ""}
    if cell == PLAN_STEP:
        steps = _plan_actions(plan)
        if steps is None:
            return _with(out, FORBID,
                         "计划模式（%s=plan）：动作类 %s（%s）须命中计划中的步骤，"
                             "但本次没有计划可依——fail-closed 未执行、未出变更单。"
                         "计划模式需先提供计划（计划输入面待后续批次）。"
                         % (AUTONOMY_ENV_KEYS["mode"], act, ACTION_NAMES[act]))
        if act in steps:
            return _with(out, ALLOW, "")
        return _with(out, FORBID,
                     "计划外零变更（设计 §三 硬约束③）：动作类 %s（%s）不在"
                     "本次计划里——fail-closed 未执行。要执行请把该动作类写进"
                     "计划，或改用 %s=%s/%s。"
                     % (act, ACTION_NAMES[act], AUTONOMY_ENV_KEYS["mode"],
                        "confirm", "full"))
    if cell == CONFIRM:
        return _with(out, CONFIRM,
                     "变更确认档（%s=%s）：动作类 %s（%s）需先出变更单，"
                     "经裁决 accept 后才落盘——本次未落盘。"
                     "裁决入口：python -m md_cg.review_cli list 后 accept/reject，"
                     "或 cg(op=review, pid=<pid>, decision=accept|reject, "
                     "reason=<理由>)。"
                     % (AUTONOMY_ENV_KEYS["mode"], m, act, ACTION_NAMES[act]))
    return _with(out, ALLOW, "")


# 生效条件：m 去空白转小写后属 AUTONOMY_MODES 时原样返回该名，否则抛 AutonomyModeError（显式传参也要过同一合法值闸——档位名的合法值只有一处定义）；
def _norm_mode(m) -> str:
    s = (m or "").strip().lower()
    if s not in AUTONOMY_MODES:
        raise AutonomyModeError(
            "非法档位 %r：允许值 %s（缺省 %s）。"
            % (m, "|".join(AUTONOMY_MODES), DEFAULT_MODE))
    return s


# 生效条件：out 为 dict 时把 decision 与 hint 写入（hint 为假值也照写，保证键恒在）后返回同一 dict；
def _with(out: dict, decision: str, hint: str) -> dict:
    out["decision"] = decision
    out["hint"] = hint
    return out


# 生效条件：plan 为假值（None/空）时返回 None（＝无计划输入）；plan 为映射时取其 "actions" 键（缺则取 "steps" 里各步的 "action" 或 "actions" 键的并集）；plan 为可迭代时逐个取元素本身或其 "action" 键；全部归一为去空白大写后的动作类集合（不含 ACTION_CLASSES 的元素被丢弃）；
def _plan_actions(plan):
    """计划 → 允许的动作类集合；None/空 = 无计划输入（与「空计划」同判）。"""
    if not plan:
        return None
    items = None
    if isinstance(plan, dict):
        if plan.get("actions"):
            items = list(plan.get("actions"))
        elif plan.get("steps"):
            items = []
            for st in plan.get("steps") or []:
                if isinstance(st, dict):
                    items.extend(st.get("actions") or ([st["action"]]
                                                       if st.get("action")
                                                       else []))
                elif st:
                    items.append(st)
    elif isinstance(plan, str):
        items = [plan]
    else:
        try:
            items = list(plan)
        except TypeError:
            return None
    out = set()
    for it in items or []:
        if isinstance(it, dict):
            it = it.get("action") or it.get("actions") or ""
            if isinstance(it, (list, tuple, set)):
                out.update(str(x).strip().upper() for x in it)
                continue
        s = str(it or "").strip().upper()
        if s in ACTION_CLASSES:
            out.add(s)
    return out


# ---- 变更单：构造/读取/幂等（设计 §四） ------------------------------------

# 生效条件：rec 支持 .get 且 rec.get("kind") 为真值时返回其去空白值，否则返回 KIND_PROPOSAL（**存量条目无 kind 一律视为 proposal**，零迁移）；
def order_kind(rec) -> str:
    """队列条目类型（缺键 = proposal——存量零迁移）。"""
    try:
        k = str(rec.get(KIND_FIELD) or "").strip()
    except AttributeError:
        k = ""
    return k or KIND_PROPOSAL


# 生效条件：rec 支持 .get 时返回该变更单的载荷视图 {"kind","action","action_name","target","after","reason","primitive"}（非变更单返回 None；载荷缺失的键回落 None/空串）；本函数只读，不产生任何副作用；
def mutation_view(rec):
    """变更单的只读视图（非变更单返回 None）——显示面/执行桥共用同一取值口径。"""
    if order_kind(rec) != KIND_MUTATION:
        return None
    try:
        slot = (rec.get("extra") or {}).get(MUTATION_SLOT) or {}
    except AttributeError:
        slot = {}
    act = str(slot.get("action") or "").strip().upper()
    return {"kind": KIND_MUTATION,
            "action": act or None,
            "action_name": ACTION_NAMES.get(act) or "",
            "target": slot.get("target") or rec.get("id"),
            "after": slot.get("after") if slot.get("after") is not None
                     else rec.get("content"),
            "reason": slot.get("reason") or "",
            "primitive": slot.get("primitive") or "",
            "meta": dict(slot.get("meta") or {}),
            "raw": slot}


# 生效条件：action_class 归一后属 ACTION_CLASSES（否则抛 ValueError），target 非空（否则抛 ValueError 且带 hint）；返回变更单载荷 dict——键：action/action_name/target/after/reason/primitive/meta（meta 为可复现原动作所需的落盘参数副本，缺省空 dict）；
def mutation_payload(action_class, target, after="", reason="",
                     primitive="", meta=None) -> dict:
    """变更单载荷（**唯一构造点**：动作类+目标+后像+理由+复现参数）。"""
    act = str(action_class or "").strip().upper()
    if act not in ACTION_CLASSES:
        raise ValueError("未知动作类：%r（允许：%s）"
                         % (action_class, "/".join(ACTION_CLASSES)))
    tgt = str(target or "").strip()
    if not tgt:
        raise ValueError("变更单缺目标节点 id：动作类 %s 的变更单必须指名目标"
                         "（无目标即无法复核、无法回滚）——fail-closed 拒绝出单。" % act)
    return {"action": act, "action_name": ACTION_NAMES[act], "target": tgt,
            "after": "" if after is None else after, "reason": str(reason or ""),
            "primitive": str(primitive or ""), "meta": dict(meta or {})}


# 生效条件：target 非空（否则抛 ValueError）时，对「动作类 + 目标 + 后像」三者的规范化拼接取 sha1 前 32 位十六进制返回；同（动作类+目标+后像）恒得同键、任一不同即得不同键（幂等对账键，形状沿用 propose 的 payload_hash）；
def mutation_dedup_key(action_class, target, after) -> str:
    """变更单幂等键：**同（动作类+目标+后像）重复提议不长第二条**。

    为什么不能沿用 propose 的 `_sig(content)`：它是**内容**签名，不带目标——
    「同一份新正文并入节点 X」与「并入节点 Y」会撞成同一条（第二条被幂等
    对账吃掉、或裁决到错的目标）。故键面显式含动作类与目标；形状仍是 sha1
    十六进制（与 payload_hash 同形，`_inbox_phash_index`/`_cascade_dedup`
    照旧按字符串比对，无需认识本键的构造）。
    """
    tgt = str(target or "").strip()
    if not tgt:
        raise ValueError("变更单缺目标节点 id：幂等键无法构造——fail-closed。")
    act = str(action_class or "").strip().upper()
    text = "%s\x1f%s\x1f%s" % (act, tgt, after if after is not None else "")
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:32]


# 生效条件：cg 具可调用的 propose、target 非空时，按 mutation_payload 组载荷、按 mutation_dedup_key 组幂等键，调**既有入队单点** cg.propose（kind=KIND_MUTATION、内容=后像、携带载荷进 extra[MUTATION_SLOT]），返回 propose 的结果（info 为真时为字典，否则为 pid 字符串）；
def propose_mutation(cg, action_class, target, after="", reason="",
                     layer="knowledge", sensitivity=None, primitive="",
                     meta=None, info=False, extra=None, payload=None, **kw):
    """把一张变更单交给**既有入队单点** `cg.propose`（设计 §四：不新建第二套队列）。

    载荷落 `extra[MUTATION_SLOT]`（沿用 `extra.defer_reason` 先例）；类型字段
    `kind` 落 rec 顶层（设计 §四 明文的类型字段）。目标 id 同时占 propose 的
    既有 `node_id` 槽、后像占 `content` 槽，故 `review_list` 等既有读取面
    不用认识本模块也能看到「改哪个节点、改成什么」。

    payload —— 已构造好的载荷（调用方若是先建载荷再出单，可传入以免构造两遍；
    缺省 None 时按上面的具名参数现构造）。
    """
    pay = payload or mutation_payload(action_class, target, after=after,
                                      reason=reason, primitive=primitive,
                                      meta=meta)
    ex = dict(extra or {})
    ex.update(kw)
    ex[MUTATION_SLOT] = pay
    return cg.propose(pay["target"], pay["after"], layer=layer,
                      sensitivity=sensitivity, kind=KIND_MUTATION,
                      dedup_key=mutation_dedup_key(pay["action"], pay["target"],
                                                   pay["after"]),
                      info=info, **ex)
