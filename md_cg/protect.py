# -*- coding: utf-8 -*-
"""md_cg · 自我层 / 锚点层写保护（不可遗忘）

理论出处（全部来自本仓已有文档，非外部发明）：

  · `docs/mdcg/灵枢_自我层定义.md:6`
      SELF 层 = 身份 + 价值观 + 图接口，**不可遗忘**、跨会话自动加载。
      任何实例都能改写自我层 = 自我认知可被任意覆写，与「自我」定义冲突。
  · `docs/mdcg/认知图_MD目录方案_v0.1.md:53`
      `anchor/  # 锚点层（不可遗忘，保护）`
  · `docs/mdcg/认知图_MD目录方案_v0.1.md:412-416`
      「importance 提升（保护：不可遗忘记入 anchor/ 且**受保护标记**）」
  · `docs/mdcg/tool_table_v0.3.0.md:15`
      「importance_hint 可显式提示重要性（**≥0.7 触发不可遗忘保护**）」

三层保护（任一命中即受保护）：

  ┌ 1. 层保护      layer ∈ {self, anchor}
  ├ 2. 显式标记    frontmatter.protected == True
  └ 3. 重要性保护  importance ≥ 0.70（写入时自动打标）

**关键区分：不可遗忘 ≠ 不可覆盖。**
  · 不可遗忘（forget / 降级搬迁）：层保护 + protected 标记 + importance≥0.7 三者都拦。
    文档原话是「不可遗忘」「触发不可遗忘保护」——重点是**别弄丢**。
  · 不可覆盖（覆写同一 id）：只拦 层保护 + 显式 immutable 标记。
    因为 goal_*/fix_*/kp_* 这类 id 是内容派生、由系统自身幂等更新，
    若 importance≥0.7 就禁止覆写，会把正常的状态更新全部误伤。
    自我认知之所以不可篡改，靠的是 **self/anchor 层**这个强信号，
    而不是"重要性高"这个弱信号。

受保护节点的动作必须显式 `override=True`：动作前先把旧版本快照进
`_protected_history/<id>/<时间戳>.md`，并把「谁、何时、为何」记进
`_protected_audit.jsonl`——保护不等于黑箱。

注意：新建（索引中不存在的节点）不受限。保护的是「已有自我认知不被改/删」，
不是「禁止产生自我认知」，否则审计节点等正常写入会被误伤。
"""
import os
import time

from . import nodefile
from .fsutil import append_jsonl, atomic_write
from .security import DEFAULT_SENSITIVITY

PROTECTED_LAYERS = ("self", "anchor")
AUTO_PROTECT_IMPORTANCE = 0.70
HISTORY_DIR = "_protected_history"
AUDIT_FILE = "_protected_audit.jsonl"

# 索引条目里的**门控三键**（键集单点定义）：`_node_entry`（mdcg.py:1294-1298）与
# `_stage`（mdcg.py:1848-1851）恒落这三键，值可为 None ⇒「键不存在」不是
# 「未标记」的可靠判据（N213 同根，2026-09-28）。None = **索引未记录该标记**。
_GATE_UNKNOWN_KEYS = ("protected", "immutable", "self_state")


class ProtectionError(PermissionError):
    """受保护节点的写动作被拒绝。"""


# ---------------------------------------------------------------- 判定

# 生效条件：cg 具备可调用的 _maybe_reload_index 时先调一次（索引代际探活，异常静默）；随后对任意 cg、node_id 返回 `(cg.index 或其假值时的 {})["nodes"]`（该键缺失或假值时为 `{}`）中以 node_id 为键的值，索引无此键时返回 None。
def _entry(cg, node_id):
    """索引条目读取单点（判定前**代际探活**）。

    N213 同根（2026-09-28）：保护面的全部判据（_fm / is_protected / is_immutable
    / guard_write / guard_forget / guard_move / stats）都经由本函数直读**本进程
    内存索引**，而写面只有 `MdCG.add`（mdcg.py:1508）接了探活——删除（forget）、
    降级搬迁（_move_layer）、统计与角色视图等出口全都没有。他进程（serve 常驻、
    autoflush=1 只 flush 不 close）新盖的 immutable/protected 在陈旧条目上不存在
    → 判定「未标记」→ 受保护节点被静默覆写/删除/搬迁，无快照无审计。
    探活放在这里 = 保护面一次接线、全部出口同闸（签名未变时只有一次 stat +
    一次 listdir；重载是稀疏事件）。同理 `_resolve_target` 的探活在本函数外层
    成了冗余的一次廉价检查，保留不动。
    """
    _reload = getattr(cg, "_maybe_reload_index", None)
    if callable(_reload):
        try:
            _reload()
        except Exception:                 # noqa: BLE001 —— 探活失败不得阻断判定本身
            pass
    return ((getattr(cg, "index", None) or {}).get("nodes") or {}).get(node_id)


# 生效条件：cg 索引中无 node_id 条目时返回 None；有条目时先取 layer/importance（缺 importance 键回落 0.5）/protected/protection_reason/immutable/self_state/importance_source（issue50-e：缺键读 None），仅当条目缺 protected 或 immutable、或（缺 self_state 且条目 layer∈PROTECTED_LAYERS）、或（条目 layer∈PROTECTED_LAYERS 且 _GATE_UNKNOWN_KEYS 中任一键的值为 None）时再经 cg.get(node_id) 用 frontmatter 覆盖这些键（cg.get 抛异常或返回假值时保留索引值；layer 取 frontmatter.layer or 索引 layer，importance 缺键时回落索引 importance）。
def _fm(cg, node_id):
    """取判定所需的 frontmatter 字段；索引快照门控字段**未知**时回退读文件。"""
    e = _entry(cg, node_id)
    if e is None:
        return None
    fm = {
        "layer": e.get("layer"),
        "importance": e.get("importance", 0.5),
        "protected": e.get("protected"),
        "protection_reason": e.get("protection_reason"),
        "immutable": e.get("immutable"),
        "self_state": e.get("self_state"),
        # issue50-e：重要度来源进判定面（_node_entry/_stage 恒落该键，值可为
        # None ⇒「缺省来源」；老索引条目缺键时 .get() 同样得 None，等价缺省）。
        "importance_source": e.get("importance_source"),
    }
    # 回退读文件：索引快照缺字段时。self_state 只在受保护层（self/anchor）
    # 需要，回退代价被限制在少量节点上，不影响全量统计性能。
    _layer = str(e.get("layer") or "")
    need_fallback = ("protected" not in e or "immutable" not in e
                     or ("self_state" not in e
                         and _layer in PROTECTED_LAYERS))
    # N213 同根（2026-09-28）：`_node_entry`/`_stage` **恒落**这三键（值可为
    # None）⇒ 上面的「缺键」判据在本仓所有构造点恒假、第四个析取子句不可达，
    # `_fm` 100% 信任索引、**从不重读文件**；索引里的 None 被当「未标记」采信，
    # 而「只改文件、不进索引写日志」的门控写点（`protect.mark` 一类）在陈旧
    # 条目里正是 None → guard_write/guard_forget/guard_move 静默放行。
    # 值为 None 即「索引未记录该标记」，唯一权威是文件——但读盘有代价，
    # 只在**受保护层**（self/anchor，节点数极少；层保护本身已拦 不可覆盖/
    # 不可遗忘，None 决定的是 self_state 豁免与层间搬迁的细粒度判定）无条件
    # 回退；非受保护层由「门控写点必须进写日志」承担（`mark` 已随本批接线，
    # `add(immutable=True)` 本就经 _stage），故不付全池读盘代价。
    if not need_fallback and _layer in PROTECTED_LAYERS \
            and any(e.get(_k) is None for _k in _GATE_UNKNOWN_KEYS):
        need_fallback = True
    if need_fallback:
        try:
            node = cg.get(node_id)
        except Exception:
            node = None
        if node:
            f2 = node.get("frontmatter") or {}
            fm["protected"] = f2.get("protected")
            fm["protection_reason"] = f2.get("protection_reason")
            fm["immutable"] = f2.get("immutable")
            fm["self_state"] = f2.get("self_state")
            fm["layer"] = f2.get("layer") or fm["layer"]
            fm["importance"] = f2.get("importance", fm["importance"])
            fm["importance_source"] = f2.get("importance_source")
    return fm


# 生效条件：cg 索引无 node_id 条目（_fm 直接返回 None，不走回退读文件）时返回 (False, '')；有条目时按 layer∈PROTECTED_LAYERS 返回 (True, 层保护)；否则 protected is True 时返回 (True, protection_reason 或 '显式保护标记')；否则 importance（缺失/假值/float 转换异常一律按 0.0）≥AUTO_PROTECT_IMPORTANCE 且 importance_source 为 None（键缺省）或 'hint' 时返回 (True, 重要性保护)——issue50-e：'heuristic' 等显式非 hint 来源不得由分数触发；其余返回 (False, '')。
def is_protected(cg, node_id):
    """**不可遗忘**判定 → (是否受保护, 原因)。节点不存在返回 (False, "")。

    issue50-e（2026-10-02，使用者裁定「读面也只认显式来源」）：按分自动保护
    只对**缺省来源或显式 hint** 的分数生效。issue50-d 落盘了启发式真分
    （importance=0.7x + importance_source="heuristic"、不打保护位），若本
    判定不看来源，读面（遗忘/搬迁闸、protect.check、scrub 净化与 confidence
    校准的 skip 判定、stats 盘点）会把机器推断的分数重新认回受保护——写侧
    「只落分不打位」被读侧单方面推翻。边界：
    ① 键缺省（None）= 存量节点（既有 cg.add(importance=0.9) 直写、维护路径
      调分等从未有过该键）⇒ 行为一字不变——按「缺省即不认」会大规模改变
      既有保护面，禁止；
    ② "hint" = 显式声明（写侧对 hint 过线本就打位，按分分支只是其无位形态
      的兜底，语义不变）；
    ③ "heuristic" 及其它显式来源不得由分数触发——机器推断的重要度不构成
      不可遗忘的依据。层保护（PROTECTED_LAYERS）、fm.protected 位、
      is_immutable 一律不动；MERGE 强化（forgetting.reinforce 跨 0.7 置
      protected=True）是「重复确认」的显式动作，不经本分支，不受影响。
    """
    fm = _fm(cg, node_id)
    if fm is None:
        return False, ""
    layer = str(fm.get("layer") or "")
    if layer in PROTECTED_LAYERS:
        return True, f"层保护：{layer}（不可遗忘层）"
    if fm.get("protected") is True:
        return True, str(fm.get("protection_reason") or "显式保护标记")
    try:
        imp = float(fm.get("importance") or 0.0)
    except Exception:
        imp = 0.0
    # issue50-e（2026-10-02）：按分保护**只认缺省或显式 hint 来源**——
    # 语义与边界见 docstring ①②③；_fm 恒带 importance_source 键（缺省读
    # None），老索引条目缺键同样落 None ⇒ 存量按分保护一字不变。
    _src = fm.get("importance_source")
    if imp >= AUTO_PROTECT_IMPORTANCE and (_src is None or _src == "hint"):
        return True, f"重要性保护：importance={imp:.2f}≥{AUTO_PROTECT_IMPORTANCE}"
    return False, ""


# 生效条件：cg 索引无 node_id 条目时返回 (False, '')；有条目时若 self_state is True 一律返回 (False, '')（自我状态豁免）；否则 layer∈PROTECTED_LAYERS 返回 (True, 层保护)；否则 immutable is True 返回 (True, protection_reason 或 '显式不可覆盖标记')；其余返回 (False, '')。
def is_immutable(cg, node_id):
    """**不可覆盖**判定 → (是否不可篡改, 原因)。比不可遗忘更窄，只认强信号。

    例外：自我状态卡（frontmatter.self_state is True）**必须可覆盖**——
    自我状态本来就要随认知演化而更新，冻结它等于自我认知停止生长。
    但它仍然 is_protected（不可遗忘），这是「不可遗忘 ≠ 不可覆盖」的延伸。
    身份锚点不设此豁免，依旧两者皆禁。
    """
    fm = _fm(cg, node_id)
    if fm is None:
        return False, ""
    if fm.get("self_state") is True:
        return False, ""
    layer = str(fm.get("layer") or "")
    if layer in PROTECTED_LAYERS:
        return True, f"层保护：{layer}（不可篡改层）"
    if fm.get("immutable") is True:
        return True, str(fm.get("protection_reason") or "显式不可覆盖标记")
    return False, ""


# ---------------------------------------------------------------- 留痕

# 生效条件：对任意 cg、action、node_id、reason（actor/snapshot 缺省为 None）都构造含 t/action/node_id/reason/actor/snapshot 的 rec 并返回，同时尝试追加写入 cg.root 下的 AUDIT_FILE，该写入抛出的任何异常被吞掉且不影响返回值。
def _audit(cg, action, node_id, reason, actor=None, snapshot=None):
    rec = {"t": time.time(), "action": action, "node_id": node_id,
           "reason": reason, "actor": actor, "snapshot": snapshot}
    try:
        append_jsonl(os.path.join(cg.root, AUDIT_FILE), rec)
    except Exception:
        pass
    return rec


# 生效条件：cg.get(node_id) 抛异常或返回假值时返回 None；否则在 cg.root/HISTORY_DIR/node_id 下以时间戳命名写入当前 frontmatter 与 content，_write_node 抛异常时返回 None，成功则追加一条 action="snapshot" 的审计（_audit，actor 取 cg.actor）并返回相对 cg.root 且以 '/' 分隔的路径。
def snapshot(cg, node_id):
    """把节点当前版本快照进 `_protected_history/<id>/<ts>.md`，返回相对路径。

    N228（2026-09-28）：本函数此前**全文零审计**——而它是**落盘写入**（写
    `_protected_history/`，且这些快照是后续 override 快照链的基线）。经工具面
    `mdcg_protect(action="snapshot")`（此前只要求粗粒度 write）任何 can_write
    角色都能在自己可读的节点上制造未审计磁盘写入（实测 `_audit.jsonl` 条数
    8→8 不变）。本批两条收口：① 工具面 op 要求对齐规范出口（protect 面在
    `cg(op="protect")` 上级为 designer 专属）；② 快照成功即留痕（本函数内，
    两条入口——工具面与 `guard_*` 的 `_allow`——都覆盖；`_allow` 路径会有
    「snapshot + 具体守卫动作」两条审计，属如实记录而非重复计数）。
    """
    try:
        node = cg.get(node_id)
    except Exception:
        node = None
    if not node:
        return None
    d = os.path.join(cg.root, HISTORY_DIR, node_id)
    os.makedirs(d, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    p = os.path.join(d, f"{ts}.md")
    try:
        cg._write_node(node.get("id"), p, node.get("frontmatter") or {},
                       node.get("content") or "")
    except Exception:
        return None
    rel = os.path.relpath(p, cg.root).replace("\\", "/")
    _audit(cg, "snapshot", node_id, "显式快照（%s）" % rel,
           actor=getattr(cg, "actor", None), snapshot=rel)
    return rel


# 生效条件：cg.get(node_id) 抛异常或返回假值时返回 None（与 snapshot 同口径——目标不存在＝动作不会发生，由调用方按既有错误路径处理）；否则在 cg.root/HISTORY_DIR/node_id 下以「秒级时间戳-微秒后缀」命名写入当前 frontmatter 与 content（写盘形态与 snapshot 逐位一致：同目录、同 nodefile 序列化、同 _write_node 封装钩子），_write_node 抛异常时返回 None，成功则追加一条 action="preimage" 的审计（reason 交代动作类与 pid）并返回相对 cg.root 且以 '/' 分隔的路径；
def snapshot_preimage(cg, node_id, action="", pid=None, reason="", actor=None):
    """执行时点前像（设计 §四「回滚原语通用化」：快照面推广为一切 C/D/B）。

    与 `snapshot()` 的关系（**面复用、语义泛化**，既有行为一字不动）：
    `_protected_history/<id>/` + `_protected_audit.jsonl` 这一对从「仅受保护节点」
    推广为「一切 C/D/B 动作」的**前像面**——本函数是新入口，`snapshot()` /
    `guard_*` 的既有形态（文件名 `%Y%m%d-%H%M%S.md`、审计 action="snapshot"、
    reason「显式快照（rel）」、覆盖路径快照数）**不改一行**（守卫钉死）。
    两条差别都是为「执行时点前像」的场景补强：
      · 文件名带微秒后缀——同一节点的多个变更单可能在**同一秒**内先后执行，
        秒级名会互相覆盖（探针实测：同秒二次 snapshot 返回同一路径）——前像
        被后来的前像踩掉，早先那张的回滚句柄就指向错误时点的内容；
      · 审计 action="preimage" 且 reason 交代动作类/pid——回滚与 §七 R3 读数
        （「存在实测回滚记录」）要能把「变更单前像」与既有显式快照区分开。

    为什么前像必须在**执行时点**拍（设计 §四 明文）：变更单在提议时点构造，
    从提议到 accept 之间目标可能被第三方改动——回滚必须撤销**本变更本身**，
    而不是一并抹掉第三方改动。故由执行桥（`mdcos._mutation_execute`）在动作
    原语落盘**之前**拍摄，作为载荷 `before` 字段（执行时点快照引用）。

    边界（如实）：加密库（覆写了 `_seal_content` 的实例）里本文件的密文层
    因每次封装熵不同**不保证逐字节可复现**——前像的语义是「明文内容 + 结构
    的可恢复」，逐字节比对在非加密库（含一切守卫合成库）上成立（探针实测）。
    """
    try:
        node = cg.get(node_id)
    except Exception:
        node = None
    if not node:
        return None
    d = os.path.join(cg.root, HISTORY_DIR, node_id)
    os.makedirs(d, exist_ok=True)
    ts = (time.strftime("%Y%m%d-%H%M%S", time.localtime())
          + "-%06d" % (time.time_ns() // 1000 % 1000000))
    p = os.path.join(d, f"{ts}.md")
    try:
        cg._write_node(node.get("id"), p, node.get("frontmatter") or {},
                       node.get("content") or "")
    except Exception:
        return None
    rel = os.path.relpath(p, cg.root).replace("\\", "/")
    _audit(cg, "preimage", node_id,
           reason or ("执行时点前像（动作类 %s，pid=%s）"
                      % (action or "?", pid or "?")),
           actor=actor if actor is not None else getattr(cg, "actor", None),
           snapshot=rel)
    return rel


# 生效条件：cg.root/HISTORY_DIR/node_id 不是目录时返回 []；是目录时返回该目录下以 .md 结尾（不递归）的文件按名称排序后的 `HISTORY_DIR/node_id/文件名` 列表，无匹配文件则列表为空。
def history(cg, node_id):
    """受保护节点的历史版本列表（按时间升序）。"""
    d = os.path.join(cg.root, HISTORY_DIR, node_id)
    if not os.path.isdir(d):
        return []
    out = [f for f in os.listdir(d) if f.endswith(".md")]
    out.sort()
    return [f"{HISTORY_DIR}/{node_id}/{f}" for f in out]


# ---------------------------------------------------------------- 守卫

# 生效条件：对任意 cg、node_id、why、action、override、actor 都无条件返回 {'override': True, 'reason': why, 'snapshot': snapshot(...) 的结果, 'audit': _audit(cg, action, node_id, why, actor, snap) 的结果}，override 形参本身不改变返回内容。
def _allow(cg, node_id, why, action, override, actor):
    snap = snapshot(cg, node_id)
    rec = _audit(cg, action, node_id, why, actor, snap)
    return {"override": True, "reason": why, "snapshot": snap, "audit": rec}


# 生效条件：is_immutable(cg, node_id) 为假（含 self_state is True、layer 不在 PROTECTED_LAYERS 且 immutable 非 True 的情形）时返回 None；为真时 override 取真值则返回 _allow(..., 'override_write', override, actor)，否则抛出 ProtectionError；layer 形参不参与该判定。
def guard_write(cg, node_id, layer=None, override=False, actor=None):
    """覆盖既有节点前的守卫（只认**不可覆盖**信号）。

    新节点 / 未标记 immutable 的节点直接放行（返回 None）。
    importance≥0.7 只保证「不可遗忘」，不阻断系统自身的幂等更新。
    """
    prot, why = is_immutable(cg, node_id)
    if not prot:
        return None
    if override:
        return _allow(cg, node_id, why, "override_write", override, actor)
    raise ProtectionError(
        f"节点 {node_id} 受写保护（{why}）；覆盖需显式 override=True")


# 生效条件：is_protected(cg, node_id) 为假时返回 None；为真时 override 取真值则返回 _allow(..., 'override_forget', override, actor)，否则抛出 ProtectionError。
def guard_forget(cg, node_id, override=False, actor=None):
    """删除前的守卫。受保护节点 = 不可遗忘。"""
    prot, why = is_protected(cg, node_id)
    if not prot:
        return None
    if override:
        return _allow(cg, node_id, why, "override_forget", override, actor)
    raise ProtectionError(
        f"节点 {node_id} 不可遗忘（{why}）；删除需显式 override=True")


# 生效条件：is_protected(cg, node_id) 为假时返回 None；为真且 to_layer∈PROTECTED_LAYERS（保护层间互搬）时也返回 None；为真且 to_layer 不在 PROTECTED_LAYERS 时，override 取真值则返回 _allow(..., 'override_move', override, actor)，否则抛出 ProtectionError。
def guard_move(cg, node_id, to_layer, override=False, actor=None):
    """降级/搬迁前的守卫：受保护节点不得被移出保护层。"""
    prot, why = is_protected(cg, node_id)
    if not prot:
        return None
    if to_layer in PROTECTED_LAYERS:
        return None                       # 保护层之间互搬仍受保护，放行
    if override:
        return _allow(cg, node_id, why, "override_move", override, actor)
    raise ProtectionError(
        f"节点 {node_id} 受写保护（{why}）；降级移出保护层需显式 override=True")


# 生效条件：cg 具备可调用的 _maybe_reload_index 时先调一次；层取形参 layer、索引条目 layer、节点 frontmatter layer 中首个真值（皆假值回落 "knowledge"，与 require_layer_write 缺省同口径）；敏感度取形参 sensitivity、索引条目 sensitivity、节点 frontmatter sensitivity 中首个真值（皆假值回落 security.DEFAULT_SENSITIVITY）；返回 (层, 敏感度) 二元组。
def _resolve_target(cg, node_id, layer=None, sensitivity=None):
    """既有节点写面的「层 / 敏感度」解析**单点**（不设第二份口径）。

    索引代际探活（N195 同族）：写面直读本进程内存索引，他进程刚写入/搬迁的节点
    在本进程索引中不存在、或层位陈旧 → 解析出的层不是真层，层闸会**静默失效**
    （「越权改 knowledge」被当成「同层正当写」放行）。故进入判定前先探活一次
    （签名未变时只有一次 stat）。
    """
    _reload = getattr(cg, "_maybe_reload_index", None)
    if callable(_reload):
        _reload()
    e = _entry(cg, node_id) or {}
    _layer = layer or e.get("layer")
    _sens = sensitivity or e.get("sensitivity")
    if not _layer or not _sens:
        try:
            node = cg.get(node_id)
        except Exception:                     # noqa: BLE001 —— 读面失败不阻断判据本身
            node = None
        if node:
            f = node.get("frontmatter") or {}
            _layer = _layer or f.get("layer")
            _sens = _sens or f.get("sensitivity")
    return _layer or "knowledge", _sens or DEFAULT_SENSITIVITY


# 生效条件：经 _resolve_target 解析出节点真层与敏感度后，cg.principal 非 None 且具备 require_layer_write 时调 principal.require_layer_write(layer, sensitivity)（越权抛 AccessDenied），返回解析出的层；cg 无 principal（裸 MdCG）时不做任何判定。
def require_layer(cg, node_id, layer=None, sensitivity=None, actor=None):
    """既有节点写面的 **principal 层闸**单点（不含引擎级保护闸）。

    N209（2026-09-28，同族未接线的相邻写面入口）：「只有 `falsified` 一态接了
    层闸」之外的三条写面全程只认管理位/保护位、**不认层白名单**——
    `MdCGSecure.verify` 的 confirmed/weakened 分支直写被验证节点本体
    （`md_cg/mdcg.py:3502`）、`trust.set_state`（验证态唯一推进入口 ⇒ 依赖者
    `mark_dependents` 与 `set_verification` 两条写路，`md_cg/trust.py:697-698`）、
    `MdCG._move_layer`（降级搬迁 = 源层一次删除写 + 目标层一次新增写，
    `md_cg/mdcg.py` 的 `MdCG._move_layer`）。后果：持 verify 令牌（`layers_allow` 仅
    rejected/contextual、forbidden 明列「knowledge/self/anchor 层」）即可改写
    knowledge 层节点本体、把 self 层依赖者置 doubted、把 knowledge 节点搬出层。
    层闸口径与 `MdCGSecure.add`/`add_rejected` 一致（`md_cg/mdcos.py:3889`/`:3898`）。
    """
    _layer, _sens = _resolve_target(cg, node_id, layer=layer,
                                    sensitivity=sensitivity)
    p = getattr(cg, "principal", None)
    if p is not None and hasattr(p, "require_layer_write"):
        p.require_layer_write(_layer, _sens)
    return _layer


# 生效条件：先经 require_layer(cg, node_id, layer, sensitivity) 做 principal 层闸（越权抛 AccessDenied），再委托 guard_write(cg, node_id, layer=解析层, override=override, actor=actor) 并返回其结果。
def guard_overwrite(cg, node_id, layer=None, sensitivity=None,
                    override=False, actor=None):
    """既有节点**覆写**前的统一双闸：principal 层写权限 + 引擎级写保护。

    N197/N208（2026-09-28）：「同一身份对**同层**的 `add` 已被
    `require_layer_write` 拒绝，但直调 `cg._write_node` 的写面照样落盘」——
    层闸被同一库的两条出口口径不一致地绕开。与 N131（review 队列 merge 面）
    同序同错型：principal 层写闸在先（对照 `MdCGSecure.add` :3889），引擎级
    `guard_write` 在后（对照 `MdCG.add` :1509）。任何覆写**既有节点**的写面都
    必须先过这里，否则 self/anchor 层与 immutable 节点被无痕覆写：不抛错、不落
    `_protected_history` 快照、不写 `_protected_audit.jsonl`。

    索引代际探活（N195 同族）：写面直读本进程内存索引，他进程刚置的保护位在本
    进程索引中不存在 → `is_immutable` 的 `_entry` 得 None → 判 False，两道闸
    会**同时静默失效**。故进入判定前先探活一次（签名未变时只有一次 stat）；
    解析与层闸由 `require_layer` 同一单点承担。
    """
    _layer = require_layer(cg, node_id, layer=layer, sensitivity=sensitivity)
    return guard_write(cg, node_id, layer=_layer, override=override, actor=actor)


# 生效条件：cg.get(node_id) 抛异常或返回假值时返回 {'ok': False, 'error': 'node_not_found', 'node_id': node_id}（负路由，形态对齐 trust.set_state:692）；否则把 protected=True 与 protection_reason=reason 写入 cg.root 下 node["path"]（该键缺失即抛 KeyError）对应的 frontmatter 并保持原 content，随后门条目存在时同步其 protected/protection_reason 并把该条目并入索引写日志（_dirty 标脏 + flush，失败静默），返回 {'node_id': node_id, 'protected': True, 'reason': reason}。
def mark(cg, node_id, reason):
    """给节点打上 `protected=True` 标记（写回 frontmatter，不动 content）。

    节点不存在时返回**负路由** `{"ok": False, "error": "node_not_found",
    "node_id": node_id}`（与 `trust.set_state` 的不存在分支逐键同形），
    不再裸返回 None（H9④ 前）：None 与「成功」在调用方眼里都非 dict，
    `mcp_server._protect_call` 直接把它序列化成 `null` 回给 MCP 客户端
    ——不存在的 node_id 被读成「打标成功」，而 `_write_node` 从未发生。
    调用方分流：失败看 `r.get("ok") is False` / `"error" in r`，
    成功路径的返回键**不变**（node_id / protected / reason，无 ok 键）。
    """
    try:
        node = cg.get(node_id)
    except Exception:
        node = None
    if not node:
        return {"ok": False, "error": "node_not_found", "node_id": node_id}
    fm = node.get("frontmatter") or {}
    fm["protected"] = True
    fm["protection_reason"] = reason
    cg._write_node(node_id, os.path.join(cg.root, node["path"]),
                   fm, node.get("content") or "")
    e = _entry(cg, node_id)
    if e is not None:
        e["protected"] = True
        e["protection_reason"] = reason
        # N213 同根（2026-09-28）：保护位是**门控字段**，只改内存条目 + 文件而
        # 不进索引写日志 ⇒ 他进程（以及本进程 compact 前的重载）把该节点当
        # 「未标记」→ guard_forget / guard_move 静默放行。与 add 同口径：
        # `_dirty[nid] = e` 标脏（**不走 _stage**——它会重复累加该桶计数）
        # 并 flush，使日志成为跨进程可见的代际载体。日志化失败不阻断打标本身
        # （文件已改，下一次 compact/rebuild 的 _scan_nodes 会带上该标记）。
        _dirty = getattr(cg, "_dirty", None)
        if isinstance(_dirty, dict):
            _dirty[node_id] = e
            _flush = getattr(cg, "flush", None)
            if callable(_flush):
                try:
                    _flush()
                except Exception:         # noqa: BLE001 —— 落账失败不阻断打标
                    pass
    return {"node_id": node_id, "protected": True, "reason": reason}


# 生效条件：遍历 cg.index.nodes（或其假值时的空字典）的每个键，对 is_protected 为真的节点计入 ids 并按 layer（缺失/假值记为 '?'）累加 by_layer，其中原因串含 "importance=" 或以 "重要性保护" 开头的计入 auto_by_importance，对 is_immutable 为真的计入 immutable_ids，返回含 protected_count/immutable_count/by_layer/auto_by_importance/ids/immutable_ids 的字典。
def stats(cg):
    """保护面盘点：不可遗忘数 / 不可覆盖数 / 分层分布 / 自动保护命中数。"""
    nodes = ((getattr(cg, "index", None) or {}).get("nodes") or {})
    by_layer, ids, auto, immutable = {}, [], 0, []
    for nid in list(nodes):
        prot, why = is_protected(cg, nid)
        if prot:
            ids.append(nid)
            layer = str(nodes[nid].get("layer") or "?")
            by_layer[layer] = by_layer.get(layer, 0) + 1
            if "importance=" in why or why.startswith("重要性保护"):
                auto += 1
        imm, _ = is_immutable(cg, nid)
        if imm:
            immutable.append(nid)
    return {"protected_count": len(ids), "immutable_count": len(immutable),
            "by_layer": by_layer, "auto_by_importance": auto, "ids": ids,
            "immutable_ids": immutable}