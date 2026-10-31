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
#: 可用复核通道**声明**（逗号分隔 hive,subagent,team）。
#:
#: ⚠️ 边界（2026-10-27 修正）：本变量是**部署声明**，不是能力探测——
#: 为空只表示「没声明过」，**不等于**「没有子代理/蜂巢/团队」。曾经因为把这
#: 个空值当成能力盘点，对外误报「无子代理」，而实际 DSH 子代理通道可用。
#: 要判断真相请走 `probe_channels()`（只读声明）或由各端自己的探测，别用本变量的空值推断能力。
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


# 生效条件：显式调用时返回 {"declared": 声明的通道元组, "hint": 补齐指引}；纯读声明，不发起网络或进程调用。
def probe_channels(environ=None):
    """复核通道自检（**只读声明**，不做能力探测）。

    为什么不在这里探测子代理：本模块属大脑库、跨 harness 复用；子代理能力只有
    各端自己知道（DSH 侧有 `subagent` 工具、别的端可能是蜂巢/团队）。这里只
    如实回报「声明了什么」，并把「怎么补」写清楚——避免再出现「声明为空 →
    断言无能力」的错判（2026-10-27 实际发生过：对外误报「无子代理」，而
    DSH 子代理通道实测可用，一次只读任务跑通）。
    """
    declared = review_channels(environ)
    if declared:
        hinted = "已声明：" + ",".join(declared)
    else:
        hinted = ("未声明任何复核通道——若本端有子代理/蜂巢/团队，请设 "
                  "MDCG_REVIEW_CHANNELS=subagent,hive,team 后再 enforce；"
                  "声明缺失不等于能力缺失")
    return {"declared": declared, "hint": hinted}


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

#: issue #708（2026-10-28）：warn 档的**可观测性**。
#:
#: 病灶（报告人 Starrain08 实测）：`warn` 档只往子进程 stderr 写一行，而 DSH 不把子进程
#: stderr 转发进 `desktop-next.log` ⇒ 用户「完全看不到任何东西」，等于没有观察期，
#: 只能盲选要不要切 enforce。
#:
#: 修法（报告人建议 2）：**进程内计数 + 最近条目摘要**，经 `cg(op=info).write_gate` 可查。
#: 不依赖 stderr 转发，也不写盘（诊断面，零副作用）。
#: 有界：最多保留 WARN_RECENT_MAX 条，防长驻进程无限增长。
WARN_RECENT_MAX = 20
_warn_counts = {}      # {(layer, mode): 次数}
_warn_recent = []      # [(layer, tier, reason)]  最近若干条，无内容、无节点 id


def warn_record(layer, tier, reason):
    """记录一次「本该复核却按 warn 放行」——供 `cg(op=info)` 读出。"""
    key = (layer or "", tier)
    _warn_counts[key] = _warn_counts.get(key, 0) + 1
    _warn_recent.append((layer or "", tier, (reason or "")[:160]))
    if len(_warn_recent) > WARN_RECENT_MAX:
        del _warn_recent[:-WARN_RECENT_MAX]


def warn_report():
    """生效条件：恒返回可序列化 dict——`{mode, total, by_layer, recent}`。"""
    total = sum(_warn_counts.values())
    by_layer = {"%s@L%s" % k: v for k, v in sorted(_warn_counts.items())}
    return {"mode": gate_mode(),
            "total": total,
            "by_layer": by_layer,
            "recent": [{"layer": a, "tier": b, "reason": c}
                         for a, b, c in _warn_recent[-5:]],
            "hint": ("warn 档只记录不阻断；本计数为进程内累计，重启归零。"
                       if total else "尚无 warn 记录（要么没触发，要么闸为 off）。")}


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
                "reason": "未声明复核通道（MDCG_REVIEW_CHANNELS 为空）：按裁定只允许写情景层；该层需 "
                          + "/".join(need) + " 复核——自我人格偏移与失忆是毁灭性的，宁可拒写"}
    gap = missing_reviewers(tier, reviewers)
    if gap:
        return {"decision": "require_review", "tier": tier, "mode": m, "missing": gap,
                "reason": "该层需 " + "/".join(need) + " 复核，仍缺 " + "/".join(gap)}
    return {"decision": "allow", "tier": tier, "mode": m, "missing": [], "reason": "复核齐备"}

# ── issue #722 / 规范 v0.5：生效条件是否在描述「元数据」而非「什么时候该用」──
#
# ⚠️ 判据演进（2026-10-31，四次实测修正留痕，勿重蹈）：
#   ① 正向「所有词项都含元数据特征」→ 失败：含「源文档 a/b/c.md」时被 / 切成路径片段，all() 恒 False，
#      120 抽样元数据判出 0 条。
#   ② 反向「不含任何场景标志词」→ 失败：单字标志词「时」被「全时窗」误触发。
#   ⇒ **放弃自然语言启发式**，改用**结构化判据**：看槽标签。
#
# 结构化判据的依据：CCG「生效条件」若由 `condition_space` 四槽合成，必然带槽标签；
# 实测 14/20 的条件形如「载体/位置：…；时间：…；方法：…；约束：…」。
# 真正的"触发场景"（如 #722 报告人改写的「当他说"不想你被换掉"时」）**不会**带这些标签。
_SLOT_LABELS = ("载体/位置：", "载体/位置:", "载体=", "时间：", "时间:", "方法：", "方法:", "约束：", "约束:")


# 生效条件：cond_text 为假值时返回 False（无条件是另一类问题，不由本函数判）；
# 否则：若同时含**载体/位置**类槽标签与**约束/方法**类槽标签 ⇒ 判为元数据（四槽合成形态）。
# 只用于写入把关，**不参与判定**——实测证明"跳元数据词项"不能改善判定。
def cond_is_metadata(cond_text) -> bool:
    """生效条件是否在描述「元数据」（载体/路径/方法/约束），而非「什么时候该用」。

    实测背景（2026-10-31，全库 32842 抽样）：约 14/20 的条件是四槽合成形态
    `载体/位置：本地文档仓（大域=xxx）；时间：全时窗；方法：md…；约束：源文档 a/b.md`，
    **0 条**是「用户会怎么说」。

    判据（结构化，非词义猜测）：**同时**出现 `载体/位置` 类标签与 `约束`/`方法` 类标签。
    这样「当他说"不想你被换掉"时」这类真场景条件不会被误判（它没有槽标签）。
    """
    text = str(cond_text or "")
    if not text.strip():
        return False
    has_carrier = ("载体/位置：" in text or "载体/位置:" in text or "载体=" in text)
    has_other = any(k in text for k in ("时间：", "时间:", "方法：", "方法:", "约束：", "约束:"))
    return bool(has_carrier and has_other)


# ── issue #722 / 规范 v0.5 第四节：写入把关（warn 优先，不阻断）─────────
# 生效条件：content 为节点正文（str 或 None）时，取「# 生效条件」行判其是否为元数据；
# 无该行时返回 ok=True（无条件是另一类问题，见规范 v0.5「不适用条件 1」）。
# **不抛异常**：任何内部错误都返回 ok=True + error 字段（写入把关绝不阻断写入）。
def check_condition_quality(content) -> dict:
    """检查节点的「生效条件」是否为元数据（载体/路径/方法），而非触发场景。

    返回 {"ok": bool, "is_metadata": bool, "cond": str, "hint": str}。
    `ok=False` 仅表示"条件质量可疑"，**不表示写入应被拒绝**——
    按 v0.5 第四节，默认档是 `warn`（计数 + 提示），不是 enforce。
    """
    try:
        text = str(content or "")
        cond = ""
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("#") and "生效条件" in s:
                if "：" in s:
                    cond = s.split("：", 1)[1].strip()
                elif ":" in s:
                    cond = s.split(":", 1)[1].strip()
                break
        if not cond:
            return {"ok": True, "is_metadata": False, "cond": "", "hint": "无生效条件行"}
        meta = cond_is_metadata(cond)
        return {"ok": not meta, "is_metadata": meta, "cond": cond,
                "hint": ("生效条件在描述载体/路径/方法（元数据），不是在描述"
                         "「什么时候该用」——检索时它几乎不可能被自然问法命中"
                         "（实测库内 76.5% 节点如此）") if meta else ""}
    except Exception as exc:                       # noqa: BLE001 —— 把关绝不阻断
        return {"ok": True, "is_metadata": False, "cond": "",
                "hint": "检查失败（不影响写入）：%s: %s" % (type(exc).__name__, exc)}