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

**批次③（2026-10-02）**：变更单载荷在（动作类/目标/后像/理由/primitive/meta）
之上补三字段——`before`（前像，**执行时点**快照引用）· `impact`（执行时点影响面
读数）· `rollback`（可执行的回滚命令串）。三键在**提议时点**即占位（恒在键面，
取值 None/""——字段完备），由执行桥（`mdcos._mutation_execute`）在动作落盘前
经 `mutation_executed()` 补全为执行时点实值；回滚原语通用化与回滚实测在
`md_cg/rollback.py` + `md_cg/rollback_cli.py`（守卫 `test_mutation_rollback.py`）。

**批次④（2026-10-02，设计 §六/§七）**：**准入闸**——`settle()` 是生效面
（结算「实际生效档位」并冻结进进程级结算态）：`env MDCG_AUTONOMY=full` 而
准入读数（`md_cg/admission.py` 的 R1–R4）不满足 ⇒ `effective` **回落 confirm**
并在结算体 `alerts` 里逐条报「缺哪条读数」（另向 stderr 打一行启动面告警）
——**不静默降级**；`plan`/`confirm` 不受读数影响（零 IO、零告警）；非法 env
仍 fail-closed 抛 `AutonomyModeError`。

「不可选中」的落法（设计 §六 逐字）：
  · 准入闸作用于**经 env 选中 full** 的路径（`mode()` 读 env 后折算）；
  · `decide(mode_explicit=…)` 是**显式强制指定**（守卫/工具用；不经 env 键
    = 不属「选中」行为），不参与准入折算——生产热路径一律走 env 路径；
  · **未 settle（生效面未启用）时 `mode()` 与改动前逐位一致**（对拍）；
    结算只对「配置档位 = full」的进程态生效，且以 `settle` 的调用为界
    （触发频度由调用方控制：MCP 启动面/常驻巡检按需调用；`admission.gate`
    的读数有 TTL 缓存，见 `md_cg/admission.py`——热路径 `mode()`/`decide()`
    零 IO，不因准入闸增加任何每次调用的扫描）。

**补强批次（v1.1，2026-10-02）**：**结算异常语义 fail-closed**——`settle()`
对读数结算过程的一切异常**捕获并写「结算失败/不可判」态**（键 `error` 非空，
与「未调用过 settle」可区分；`alerts` 一并报「读数不可得」），向 stderr 打
一行告警——**不静默**；失败态的**有效档位**两格：
  · 此前**从未成功结算** ⇒ 回落 `confirm`——收口「数据面损坏（如溢出崩溃）
    + 未结算 ⇒ `mode()` 照常返回 full」的 fail-open（设计 §六「不满足不可
    选中/不静默降级」）；
  · 此前**已有成功结算** ⇒ 保持上一次成功结算的 effective（**不升不降**，
    既有对拍锚不得破；异常只是把结算态标记为失败/不可判，可随时重结算）。
`plan`/`confirm` 不受影响；**未调用过 settle 的进程 `mode()` 与改动前逐位
一致**；合法数据面下的结算与读数逐位不变。

**补强批次（v1.2，2026-10-03 · 步骤⑤补强）**：**E 面写盘前闸接线**——设计 §三
矩阵的 E 列在 plan 档是「允许（须命中计划步骤）」，而接入前**生产码**的
`decide()` 调用点只覆盖 A/B/C/D（plan 档 E 类动作照跑并写盘，实测 importance
0.5→0.57 落盘）。本批把 `decide(E_WEIGHT)` 接到 E 面的**写盘入口**——
`weights.recalc` / `freshness.recalc` / `lifecycle.set_state` /
`lifecycle.backfill` 的 apply 路径（位置＝既有资格面之后、任何盘面写入之前），
并立 `e_gate()` 为 E 面**唯一判定入口**、`forbidden_result()` 为统一的
fail-closed 返回体（带档位读数与可执行 hint、零写盘、不出单）。语义两格
（设计 §三 逐格）：plan 档无计划 ⇒ fail-closed；confirm/full ⇒ ALLOW、原链
**原样**（「confirm/full 全线逐位不变」是硬约束，非建议）。未接的 E 面入口
与理由（`lifecycle.stamp` 属 B 链 / 库层 `require_transition` 禁接线 /
分数类回滚面待裁）逐条登记在 `e_gate()` docstring——留池项据此从「E 面整体
未接线」**收窄**为「上述三处（各有面归属或待裁）」。

本批**不做**（登记留池）：计划输入面（`plan=None` ⇒ plan 档 E 一律 fail-closed，
故 E 面的「命中计划步骤」分支仍待计划输入面接线）；准入闸的生产调用点接线
（启动面/常驻巡检调 `settle`——本批落生效面单点与守卫，接线由宿主按需调用）。
"""
from __future__ import annotations

import hashlib
import os
import sys
import time

__all__ = [
    "AutonomyModeError", "AUTONOMY_ENV_DEFAULTS", "AUTONOMY_ENV_KEYS",
    "AUTONOMY_MODES", "DEFAULT_MODE", "ACTION_CLASSES", "ACTION_NAMES",
    "ALLOW", "CONFIRM", "FORBID", "PLAN_STEP", "MATRIX",
    "A_ADD", "B_MERGE", "C_REWRITE", "D_DELETE", "E_WEIGHT",
    "KIND_PROPOSAL", "KIND_MUTATION", "KIND_FIELD",
    "autonomy_env", "mode", "decide",
    # 补强批次 v1.2：E 面写盘前闸（判定唯一入口 + 统一 fail-closed 返回体）
    "e_gate", "forbidden_result",
    "order_kind", "mutation_view",
    "mutation_payload", "mutation_executed", "mutation_dedup_key",
    "propose_mutation",
    # 批次④：准入闸生效面（设计 §六/§七）
    "MODE_CONFIRM", "MODE_FULL",
    "settle", "admission_state", "reset_settlement",
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
#: 阶梯两端的具名常量（从 AUTONOMY_MODES 派生——不另写第二处字面量）。
#: 批次④ 准入闸只作用于 MODE_FULL（设计 §六「该档不可选中」）；回落目标 = MODE_CONFIRM。
MODE_CONFIRM = AUTONOMY_MODES[1]
MODE_FULL = AUTONOMY_MODES[2]

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


# 生效条件：autonomy_env("mode") 去空白转小写后属 AUTONOMY_MODES 时返回该档位名；不属（含空串）时抛 AutonomyModeError（hint 列合法值）——不静默降级；本函数是「配置档位」的唯一解释点（env 原文），settle() 与 mode() 共用；
def _configured_mode(environ=None) -> str:
    """配置档位（env 原文解释；非法值 fail-closed，文案与旧 mode() 逐字一致）。"""
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


# 生效条件：恒返回「实际生效档位」——配置档位非 full（plan/confirm）时即配置档位（不受准入读数影响、零 IO）；配置档位为 full 且进程已由 settle() 结算（结算态 configured=full 且 effective 非空——含**结算失败态**，其 effective 按「未结算⇒confirm／已结算⇒保持上次」两格取值，见 settle）时返回结算的 effective（读数不满足/不可得 ⇒ MODE_CONFIRM＝设计 §六「该档不可选中」）；配置档位为 full 而未结算时返回 full（生效面未启用＝与改动前逐位一致）；environ 显式传参（非进程级 os.environ）时不参与准入折算；
def mode(environ=None) -> str:
    """当前**实际生效**档位（缺省 confirm；full 经准入闸，见 settle()）。

    非法值 fail-closed 抛 AutonomyModeError（不静默降级）。
    """
    m = _configured_mode(environ)
    if (m == MODE_FULL and environ is None
            and _SETTLEMENT["configured"] == MODE_FULL
            and _SETTLEMENT["effective"]):
        return _SETTLEMENT["effective"]
    return m


# ---- 批次④：准入闸生效面（设计 §六/§七） --------------------------------
#: 进程级结算态（生效面**唯一落点**）：settle() 写入；mode() / admission_state()
#: 只读。键集恒定（形态固定，便于守卫与宿主逐键读）。`error`（补强批次）：
#: None = 最近一次结算正常；非空 = 最近一次结算**失败/不可判**（读数不可得）
#: ——这是「结算失败态」与「未调用过 settle」（configured=None）的可区分标记。
_SETTLEMENT = {"configured": None, "effective": None, "settled": False,
               "admission": None, "alerts": [], "root": None, "t": 0.0,
               "error": None}


# 生效条件：text 为字符串时向 stderr 写一行；写失败静默吞掉（告警已在结算体 alerts/error 里，stderr 只是启动面可观测性增强；写失败不得影响结算本身）；
def _warn(text: str) -> None:
    """启动面告警单点（设计 §七「自动回落并在启动面告警」）。"""
    try:
        sys.stderr.write(text)
    except Exception:                                           # noqa: BLE001
        pass


# 生效条件：configured 档位经 _configured_mode(environ) 取 env 值（非法即 fail-closed 抛 AutonomyModeError）；configured 非 full 时零 IO 返回 {configured, effective=configured, settled=False, admission=None, alerts=[], error=None}；configured=full 时调 admission.gate(root 或 admission.default_root(), ttl, force) 结算——读数满足 ⇒ effective=full、alerts=[]；不满足（含不可判）⇒ effective=MODE_CONFIRM 且 alerts 逐条列出未过读数 {reading, ok, detail} 并向 stderr 打一行启动面告警；结算过程抛异常（读数不可得）⇒ 捕获不抛出、写失败态（error 非空 + alerts 一条「读数不可得」）——此前从未成功结算 ⇒ effective=MODE_CONFIRM（fail-closed，收口 fail-open）、已有成功结算 ⇒ 保持上次成功结算的 effective（不升不降）；所有分支的结算体（含 root/t/error）写入进程级 _SETTLEMENT 后原样返回；
def settle(environ=None, root=None, force=False, ttl=None) -> dict:
    """结算「实际生效档位」（准入闸生效面，设计 §六/§七）。

    env `MDCG_AUTONOMY=full` 而准入读数（`md_cg/admission.py` 的 R1–R4）
    不满足 ⇒ `effective` 回落 `confirm`，`alerts` 报「缺哪条读数」
    ——**不静默降级**；`plan`/`confirm` 不受读数影响（零 IO、零告警）；
    非法 env 仍 fail-closed 抛 `AutonomyModeError`。

    **结算失败/不可判（补强批次）**：读数结算过程抛异常（读数不可得）⇒
    **不抛出、不静默**——写失败态（`error` 非空 + `alerts` 一条「读数不可得」），
    有效档位两格：此前从未成功结算 ⇒ 回落 `confirm`（收口「未结算 + 崩溃 ⇒
    full 照常生效」的 fail-open）；此前已有成功结算 ⇒ 保持上一次成功结算的
    effective（不升不降，既有对拍锚）。告警一行打 stderr。

    调用面（触发频度）：由调用方按需调用——MCP 启动面一次、常驻巡检按
    TTL 周期可重调（读数缓存见 `admission.gate`）；热路径 `mode()` /
    `decide()` 只读结算态（零 IO），不因准入闸增加任何每次调用的扫描。
    """
    cfg = _configured_mode(environ)
    now = time.time()
    if cfg != MODE_FULL:
        out = {"configured": cfg, "effective": cfg, "settled": False,
               "admission": None, "alerts": [], "root": None, "t": now,
               "error": None}
        _SETTLEMENT.update(out)
        return out
    from . import admission as _adm        # 惰性 import：热路径 import 面不变
    try:
        r = _adm.gate(root if root is not None else _adm.default_root(),
                      ttl=ttl, force=force)
    except Exception as exc:                                # noqa: BLE001
        # 结算失败/不可判（补强批次）：读数不可得 ⇒ fail-closed、不静默。
        # 有效档位两格：从未成功结算 ⇒ confirm（收口「数据面损坏 + 未结算 ⇒
        # full」的 fail-open）；已有成功结算 ⇒ 保持上次 effective（不升不降）。
        prev = _SETTLEMENT["effective"] if _SETTLEMENT["settled"] else None
        eff = prev or MODE_CONFIRM
        if prev:
            tail = "实际生效档位保持上次成功结算的 %s（不升不降）" % eff
        else:
            tail = "已回落 %s" % eff
        err = "%s: %s" % (type(exc).__name__, exc)
        detail = ("读数不可得（结算过程异常 %s）——%s（不静默降级；"
                  "修好读数面后重新 settle 即可）。" % (err, tail))
        out = {"configured": cfg, "effective": eff, "settled": True,
               "admission": None,
               "alerts": [{"reading": "settle_error", "ok": None,
                           "detail": detail}],
               "root": root, "t": now, "error": err}
        _warn("[MdCG 三档自治] %s=%s 但结算失败/不可判：%s ——%s"
              "（不静默降级；读数详情：python -X utf8 -m md_cg.admission "
              "--root \"%s\"）。\n"
              % (AUTONOMY_ENV_KEYS["mode"], cfg, err, tail,
                 root if root is not None else "<default>"))
        _SETTLEMENT.update(out)
        return out
    if r["ok"]:
        out = {"configured": cfg, "effective": cfg, "settled": True,
               "admission": r, "alerts": [], "root": r["root"], "t": now,
               "error": None}
    else:
        alerts = [{"reading": rd["id"], "ok": rd["ok"], "detail": rd["detail"]}
                  for rd in r["readings"] if rd["ok"] is not True]
        out = {"configured": cfg, "effective": MODE_CONFIRM, "settled": True,
               "admission": r, "alerts": alerts, "root": r["root"], "t": now,
               "error": None}
        # 启动面告警（设计 §七「自动回落并在启动面告警」）——一行，可观测；
        # stderr 写失败不得影响结算本身（告警已在返回体 alerts 里）。
        _warn("[MdCG 三档自治] %s=%s 但准入读数不满足：缺 %s ——实际生效"
              "档位回落 %s（不静默降级；读数详情：python -X utf8 -m "
              "md_cg.admission --root \"%s\"）。\n"
              % (AUTONOMY_ENV_KEYS["mode"], cfg,
                 "、".join(a["reading"] for a in alerts),
                 MODE_CONFIRM, r["root"]))
    _SETTLEMENT.update(out)
    return out


# 生效条件：无入参；返回进程级结算态的快照副本（configured/effective/settled/admission/alerts/root/t/error，alerts 为列表副本）——只读零 IO，供宿主与守卫答「它今天够格吗」（error 非空 ⇒ 最近一次结算失败/不可判）；
def admission_state() -> dict:
    """最近一次 settle() 的结算体快照（含 alerts/error）——只读、零副作用。"""
    st = dict(_SETTLEMENT)
    st["alerts"] = list(st.get("alerts") or [])
    return st


# 生效条件：无入参；把进程级结算态复位为未结算（configured=None、effective=None、settled=False、admission=None、alerts=[]、root=None、t=0.0、error=None），无返回值（供测试/宿主重结算）；
def reset_settlement() -> None:
    """清结算态（mode() 回到「配置档位」旧行为）。"""
    _SETTLEMENT.update({"configured": None, "effective": None,
                        "settled": False, "admission": None, "alerts": [],
                        "root": None, "t": 0.0, "error": None})


# 生效条件：action_class 归一后属 ACTION_CLASSES（否则抛 ValueError）；plan 命中集 _plan_actions(plan) 为 None（无计划输入）时 A/B/E 判 forbid（带「计划输入面待后续批次」hint），非 None 时命中该动作类判 allow、否则 forbid（计划外零变更）；其余格按 MATRIX 原样返回 allow/confirm；返回 {"action","action_name","mode","decision","hint"}，decision ∈ ALLOW/CONFIRM/FORBID；
def decide(action_class, mode_explicit=None, plan=None, environ=None) -> dict:
    """§三 裁决矩阵判定：返回 allow | confirm | forbid（+ 可读 hint）。

    action_class  —— A/B/C/D/E（大小写不敏感；非法值抛 ValueError）。
    mode_explicit —— 显式档位；None（缺省）时**经唯一入口 `mode()` 读 env**
                     （非法 env 即 fail-closed 抛错；`mode()` 返回**实际生效
                     档位**——full 经准入闸折算，见 `settle()`，回落时本判定
                     按 confirm 档矩阵走）。形参刻意不叫 `mode`：
                    同名会遮蔽模块级唯一入口，`mode(environ)` 就成了对局部名的
                     调用——「单一入口」必须能被静态钉死（见守卫的定点变异）。
                     显式传值（含 mode_explicit="full"）是**强制指定**，不参与
                     准入折算（不经 env 键＝不属设计 §六 的「选中」行为）。
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


# ---- 补强批次（v1.2）：E 面**写盘前**闸（设计 §三 plan 档 E「须命中计划步骤」） ----
# 为什么需要单点：E 类动作（权重与生命周期）的写盘入口散在三处模块
# （`weights.recalc` / `freshness.recalc` / `lifecycle.set_state|backfill`），
# 若各写一份档位判据就是「各模块各读一份」——违背设计 §三 硬约束①「单一入口」。
# 故判定经本函数（对 `decide` 的具名再出口），返回体与返回语义见下。

# 生效条件：恒返回 decide(E_WEIGHT, plan=plan, environ=environ) 的**原样体**（含 mode/action/action_name/decision/hint 五键，decision ∈ ALLOW/CONFIRM/FORBID）；plan 为 None（本批现状：计划输入面无接线）时 plan 档 E 判 FORBID（fail-closed 带 hint）；confirm/full 两档恒 ALLOW（与 E 列矩阵逐格一致 ⇒ 调用方原链原样）；environ 显式传参（非进程级 os.environ）时不参与准入折算（同 decide）；非法 env 值仍由 mode() fail-closed 抛 AutonomyModeError；本函数零 IO、零副作用；
def e_gate(plan=None, environ=None) -> dict:
    """E 类动作**写盘前**的档位判定（**唯一入口**：E 面各写盘入口共用）。

    调用方**只看 `decision`**：

      · `ALLOW`（confirm/full 两档；将来计划命中时亦同）⇒ **原链原样**——
        「confirm/full 全线逐位不变」是硬约束：本闸在放行分支不产生任何行为
        差异（不写盘、不出单、不加返回键）。
      · 其余（现状只有 plan 档无计划 ⇒ `FORBID`）⇒ 调 `forbidden_result()`
        早退：**不落盘、不出单、不静默**，带档位读数与可执行 hint。

    位置纪律（设计 §三 硬约束②「纯加严」）：调用点一律在**既有资格面之后、
    盘面写入之前**——档位**不参与**资格判定（非法生命周期迁移/受保护拒绝/
    节点不存在一律照旧先判、各回各的 error），也**不放宽**任何既有判据
    （放行分支＝返回 None 级别的「什么都不做」）。

    边界（如实登记：**未接闸**的 E 面入口与理由——留池项据此收窄）：
      · `lifecycle.stamp` —— **无 IO 纯函数**（就地改 fm 副本，落盘由调用方
        做），其两个调用方 `forgetting.reinforce` / `writelimit.converge_into`
        都属 **B 合并/趋同链**（B 已有自己的闸，plan 档先于此处 fail-closed）；
        在 E 闸里再拦一次＝用 E 判定去挡 B 动作，语义交叉且与 G 组「合并原语
        不含档位判据」的机制前提相抵。故不接。
      · `MdCG.add` 的 `lifecycle.require_transition` 面 —— **库层禁接线**
        （守卫 G 组结构判据钉死）：「accept 执行桥直调库层越过确认判定」正是
        建立在此前提上。
      · 分数类**回滚**面（`freshness.rollback` / `weights.rollback`）——回滚是
        「破坏可逆」准入读数（R3）与设计 §四 第 4 条的兑现面：在 plan 档拦
        回滚与设计语义相抵，属**设计面待裁**（不在本批自行扩面）。
    """
    return decide(E_WEIGHT, plan=plan, environ=environ)


# 生效条件：dec 支持 .get 时返回新 dict {"ok":False,"error":"autonomy_forbidden","autonomy":{mode,action,action_name,decision}（四键取自 dec，缺键回落 None）,"hint":dec["hint"] 或 ""}，并把 **extra 的键值原样并入（各写盘面补自己的上下文键）；不落盘、不出单、不改任何状态；
def forbidden_result(dec, **extra) -> dict:
    """E 面写盘前 fail-closed 的**统一返回体**（不静默：带档位读数与可执行 hint）。

    键面固定：`ok=False` + `error="autonomy_forbidden"`（与写链/合并/删除三处
    fail-closed 出口同值——读面可按同一错误码归并）+ `autonomy`（档位/动作类/
    判定读数，形态同 `writepipe._gate_autonomy` 的 `_aut`）+ `hint`（来自
    `decide`，含「怎么改才能执行」的可执行指引）。
    """
    out = {"ok": False, "error": "autonomy_forbidden",
           "autonomy": {"mode": dec.get("mode"), "action": dec.get("action"),
                        "action_name": dec.get("action_name"),
                        "decision": dec.get("decision")},
           "hint": dec.get("hint") or ""}
    out.update(extra)
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


# 生效条件：rec 支持 .get 时返回该变更单的载荷视图 {"kind","action","action_name","target","after","reason","primitive","before","impact","rollback","meta"}（非变更单返回 None；载荷缺失的键回落 None/空串）；本函数只读，不产生任何副作用；
def mutation_view(rec):
    """变更单的只读视图（非变更单返回 None）——显示面/执行桥共用同一取值口径。

    `before`/`impact`/`rollback`（批次③）：三字段在提议时点即占键（取值
    None/""＝尚未执行），执行后由执行桥补全（见 `mutation_executed`）。
    """
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
            # 执行时点三字段（设计 §四，批次③）：提议时点为 None/""，执行后补全。
            "before": slot.get("before"),
            "impact": slot.get("impact"),
            "rollback": slot.get("rollback") or "",
            "meta": dict(slot.get("meta") or {}),
            "raw": slot}


# 生效条件：action_class 归一后属 ACTION_CLASSES（否则抛 ValueError），target 非空（否则抛 ValueError 且带 hint）；返回变更单载荷 dict——键：action/action_name/target/after/reason/primitive/before/impact/rollback/meta（meta 为可复现原动作所需的落盘参数副本，缺省空 dict；后三者为执行时点字段，提议时点占位 None/""）；
def mutation_payload(action_class, target, after="", reason="",
                     primitive="", meta=None, before=None, impact=None,
                     rollback=None) -> dict:
    """变更单载荷（**唯一构造点**：动作类+目标+后像+理由+复现参数+执行时点三字段）。

    执行时点三字段（设计 §四，批次③）——**键恒在**（提议时点即占位，
    取值 None/""），由执行桥在动作落盘前经 `mutation_executed()` 补全：

      · `before`   —— 前像（可回滚句柄）：**执行时点**快照的引用。
        提议时点**不拍**：从提议到 accept 之间目标可能被第三方改动，回滚必须
        撤销**本变更本身**、不抹第三方改动（设计 §四 明文）——前像必须反映
        「执行前一刻」的盘面，故由 `mdcos._mutation_execute` 在动作原语落盘
        之前调 `rollback.preimage()` 拍摄。
      · `impact`   —— 影响面：执行时点采集的读数（边/索引条目/聚合行）。
      · `rollback` —— 回滚命令：可执行的回滚命令串（`rollback.command_for`
        构造，形态 `python -X utf8 -m md_cg.rollback_cli --root <root> --pid <pid>`，
        守卫实测演练）。
    """
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
            "primitive": str(primitive or ""),
            # 执行时点三字段（键恒在；提议时点 = 未执行，占位 None/""）
            "before": before, "impact": impact,
            "rollback": str(rollback or ""),
            "meta": dict(meta or {})}


# 生效条件：payload 支持 dict() 复制（None/假值按空 dict 起底）时返回**新 dict**——原载荷逐键复制后补 kind=KIND_MUTATION 与 executed=True，并仅在实参非 None/非空时覆写 before/impact/rollback（缺省保留原载荷取值，不把 None 伪装成实值）；
def mutation_executed(payload, before=None, impact=None, rollback=None) -> dict:
    """执行时点补全（**唯一构造点**）：把前像/影响面/回滚命令并进载荷副本。

    为什么不原地改载荷：出单时载荷已随队列条目落盘（append-only）——执行记录
    里的补全形态是**新对象**，「提议时点载荷」与「执行时点载荷」两个事实都保留
    （外部对照时能看见「执行时点才知道的东西在执行时才出现」）。执行桥把本函数
    的返回值放进裁决返回体，`mdcos._record_decision` 再把它落进 decisions.jsonl
    的 rec["mutation"]——回滚命令（CLI）据此读回前像与动作类。
    """
    out = dict(payload or {})
    out["kind"] = KIND_MUTATION
    out["executed"] = True
    if before is not None:
        out["before"] = before
    if impact is not None:
        out["impact"] = impact
    if rollback:
        out["rollback"] = rollback
    return out


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
