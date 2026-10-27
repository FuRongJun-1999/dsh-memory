# -*- coding: utf-8 -*-
# 功能名：分层写入严格度闸（情景层可放宽 · 知识/结构/自我逐层加严 · 复核证据要求）
# 生效条件：MDCG_WRITE_GATE=warn|enforce 时经 security.require_layer_write 生效；off（缺省）时完全不介入
# 子功能：①LAYER_TIERS 四档严格度 ②REQUIRED_REVIEWERS 每档所需复核单元 ③review_channels() 读可用复核通道（hive/subagent/team）④decide_write() 产出 allow/require_review/deny ⑤无任何复核通道时仅情景类层（tier 0）可直写，其余 deny
# 执行：写入路径 → require_layer_write → decide_write(layer, reviewers, channels, mode) → off 放行 / warn 记录并放行 / enforce 阻断
# 验证方式：md_cg/test_writegate_tiers.py（四档矩阵、无通道放宽、单通道不足、双单元齐备、自我层需人工、warn 不阻断、enforce 阻断、off 不介入）
# 不适用条件：不做「复核证据真伪」校验（本层只认声明与单元归属，真伪由蜂巢/子代理侧签章承接）；不改 PROTECTED_LAYERS 的不可遗忘/不可覆盖语义
"""分层写入严格度闸（2026-10-27 使用者裁定）。

裁定原话：「记忆写入是要有，但是得经过复核。至于放宽的写入情况，则应该是没有子代理
可以用，且没有蜂巢，智能体团队功能时。可以写入情景层。知识，结构，自我层，一层要比
一层严格。自我人格的偏移，失忆，是毁灭性的。」

与既有闸门的分工：
  · `PROTECTED_LAYERS`（protect.py）管「已存在的受保护节点不许改/不许删」；
  · 本模块管「新写/覆写某层时，要不要先过复核」——两者正交，互不替代；
  · `can_write` / `layers_allow` / `clearance` 仍是硬权限；本模块只在有写权限
    的前提下，再按层追加**程序性**要求。

三档开关（MDCG_WRITE_GATE）：off（缺省，零介入）/ warn（记录并放行）/ enforce（阻断）。
"""
import os

#: 环境开关名（off|warn|enforce；非法值按 off 处理并告警一次）。
GATE_ENV = "MDCG_WRITE_GATE"
#: 可用复核通道声明（逗号分隔 hive,subagent,team）。空 ⇒ 视为无复核能力。
CHANNELS_ENV = "MDCG_REVIEW_CHANNELS"

#: 层级严格度：数字越大越严。
LAYER_TIERS = {
    "contextual": 0,   # 情景层：现场记录，丢了不毁灭
    "goals": 0,        # 目标槽：可重建的行动项
    "unresolved": 0,   # 未解问题：待办线索
    "rejected": 0,     # 负记忆：被证伪的假设
    "knowledge": 1,    # 知识层：跨会话复用的事实与结论
    "structural": 2,   # 结构层：规则、契约、判据面
    "self": 3,         # 自我层：人格/身份/状态（偏移=毁灭性）
    "anchor": 3,       # 锚点层：不可遗忘的身份锚（失忆=毁灭性）
}

#: 每档在「有复核通道」时必须具备的复核单元；tier 3 额外要求人工裁定。
REQUIRED_REVIEWERS = {
    0: (),
    1: ("reflect",),
    2: ("reflect", "verify"),
    3: ("reflect", "verify", "human"),
}

_warned = {"mode": False}


# 生效条件：environ 缺省取 os.environ；归一化后属 off/warn/enforce 时原样返回，非法值返回 off 并首次告警。
def gate_mode(environ=None):
    """当前闸档位（off / warn / enforce）。非法值 fail-open 到 off 并告警一次。"""
    env = os.environ if environ is None else environ
    raw = str(env.get(GATE_ENV) or "off").strip().lower()
    if raw in ("off", "warn", "enforce"):
        return raw
    if not _warned["mode"]:
        _warned["mode"] = True
        import sys
        sys.stderr.write("[writegate] %s=%r 非法（只认 off/warn/enforce），按 off 处理" % (GATE_ENV, raw))
    return "off"


# 生效条件：environ 缺省取 os.environ；解析 MDCG_REVIEW_CHANNELS，返回去重后的小写通道名元组（空段忽略）。
def review_channels(environ=None):
    """可用复核通道：hive / subagent / team（声明式，便于测试与显式部署）。"""
    env = os.environ if environ is None else environ
    raw = str(env.get(CHANNELS_ENV) or "")
    out = []
    for part in raw.replace(";", ",").split(","):
        name = part.strip().lower()
        if name and name not in out:
            out.append(name)
    return tuple(out)


# 生效条件：layer 为假值时按 knowledge 处理；返回 LAYER_TIERS 档位，未知层按 2 保守处理。
def tier_of(layer):
    """层 → 严格档位。未知层按 2 保守处理（宁严不松）。"""
    return LAYER_TIERS.get(str(layer or "knowledge"), 2)


# 生效条件：tier 为档位、reviewers 为复核单元可迭代；返回缺失的必需单元列表（tier 3 的 human 表示人工裁定）；按小写比较。
def missing_reviewers(tier, reviewers):
    """该档位还缺哪些复核单元（空列表＝齐备）。"""
    need = REQUIRED_REVIEWERS.get(tier, ())
    if not need:
        return []
    have = {str(r).strip().lower() for r in (reviewers or ())}
    return [unit for unit in need if unit not in have]


# 生效条件：layer/reviewers 传入，channels 与 mode 缺省从环境读取；产出 decision=allow|require_review|deny 及 tier/mode/missing/reason；mode=off 时恒 allow。
def decide_write(layer, reviewers=None, channels=None, mode=None, environ=None):
    """写入前判定：allow | require_review | deny。

    判定顺序（先看通道、再看证据——通道缺失是能力问题，证据缺失是程序问题）：
      1. mode=off ⇒ allow（零介入）；
      2. 无任何复核通道：tier 0 ⇒ allow（使用者裁定的放宽通道：没有子代理、
         没有蜂巢、没有智能体团队时只准写情景层）；tier ≥1 ⇒ deny；
      3. 有通道：缺必需复核单元 ⇒ require_review；齐备 ⇒ allow。
    """
    m = gate_mode(environ) if mode is None else str(mode)
    chans = review_channels(environ) if channels is None else tuple(channels)
    tier = tier_of(layer)
    need = REQUIRED_REVIEWERS.get(tier, ())
    if m == "off":
        return {"decision": "allow", "tier": tier, "mode": m, "missing": [], "reason": "闸未启用"}
    if not chans:
        if tier == 0:
            return {"decision": "allow", "tier": tier, "mode": m, "missing": [], "reason": "无复核通道，情景层按裁定放宽直写"}
        return {"decision": "deny", "tier": tier, "mode": m, "missing": list(need),
                "reason": "无复核通道（无子代理/无蜂巢/无智能体团队）：只允许写情景层；该层需 "
                          + "/".join(need) + " 复核——自我人格偏移与失忆是毁灭性的，宁可拒写"}
    gap = missing_reviewers(tier, reviewers)
    if gap:
        return {"decision": "require_review", "tier": tier, "mode": m, "missing": gap,
                "reason": "该层需 " + "/".join(need) + " 复核，仍缺 " + "/".join(gap)}
    return {"decision": "allow", "tier": tier, "mode": m, "missing": [], "reason": "复核齐备"}