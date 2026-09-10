# -*- coding: utf-8 -*-
"""md_cg · 自我层 / 锚点层写保护（不可遗忘）

理论出处（全部来自本仓已有文档，非外部发明）：

  · `docs/灵枢_自我层定义.md:6`
      SELF 层 = 身份 + 价值观 + 图接口，**不可遗忘**、跨会话自动加载。
      任何实例都能改写自我层 = 自我认知可被任意覆写，与「自我」定义冲突。
  · `docs/认知图_MD目录方案_v0.1.md:53`
      `anchor/  # 锚点层（不可遗忘，保护）`
  · `docs/认知图_MD目录方案_v0.1.md:412-416`
      「importance 提升（保护：不可遗忘记入 anchor/ 且**受保护标记**）」
  · `docs/tool_table_v0.3.0.md:15`
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

PROTECTED_LAYERS = ("self", "anchor")
AUTO_PROTECT_IMPORTANCE = 0.70
HISTORY_DIR = "_protected_history"
AUDIT_FILE = "_protected_audit.jsonl"


class ProtectionError(PermissionError):
    """受保护节点的写动作被拒绝。"""


# ---------------------------------------------------------------- 判定

def _entry(cg, node_id):
    return ((getattr(cg, "index", None) or {}).get("nodes") or {}).get(node_id)


def _fm(cg, node_id):
    """取判定所需的 frontmatter 字段；索引快照缺 protected 时回退读文件。"""
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
    }
    # 回退读文件：索引快照缺字段时。self_state 只在受保护层（self/anchor）
    # 需要，回退代价被限制在少量节点上，不影响全量统计性能。
    need_fallback = ("protected" not in e or "immutable" not in e
                     or ("self_state" not in e
                         and str(e.get("layer") or "") in PROTECTED_LAYERS))
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
    return fm


def is_protected(cg, node_id):
    """**不可遗忘**判定 → (是否受保护, 原因)。节点不存在返回 (False, "")。"""
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
    if imp >= AUTO_PROTECT_IMPORTANCE:
        return True, f"重要性保护：importance={imp:.2f}≥{AUTO_PROTECT_IMPORTANCE}"
    return False, ""


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

def _audit(cg, action, node_id, reason, actor=None, snapshot=None):
    rec = {"t": time.time(), "action": action, "node_id": node_id,
           "reason": reason, "actor": actor, "snapshot": snapshot}
    try:
        append_jsonl(os.path.join(cg.root, AUDIT_FILE), rec)
    except Exception:
        pass
    return rec


def snapshot(cg, node_id):
    """把节点当前版本快照进 `_protected_history/<id>/<ts>.md`，返回相对路径。"""
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
    return os.path.relpath(p, cg.root).replace("\\", "/")


def history(cg, node_id):
    """受保护节点的历史版本列表（按时间升序）。"""
    d = os.path.join(cg.root, HISTORY_DIR, node_id)
    if not os.path.isdir(d):
        return []
    out = [f for f in os.listdir(d) if f.endswith(".md")]
    out.sort()
    return [f"{HISTORY_DIR}/{node_id}/{f}" for f in out]


# ---------------------------------------------------------------- 守卫

def _allow(cg, node_id, why, action, override, actor):
    snap = snapshot(cg, node_id)
    rec = _audit(cg, action, node_id, why, actor, snap)
    return {"override": True, "reason": why, "snapshot": snap, "audit": rec}


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


def guard_forget(cg, node_id, override=False, actor=None):
    """删除前的守卫。受保护节点 = 不可遗忘。"""
    prot, why = is_protected(cg, node_id)
    if not prot:
        return None
    if override:
        return _allow(cg, node_id, why, "override_forget", override, actor)
    raise ProtectionError(
        f"节点 {node_id} 不可遗忘（{why}）；删除需显式 override=True")


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


def mark(cg, node_id, reason):
    """给节点打上 `protected=True` 标记（写回 frontmatter，不动 content）。"""
    try:
        node = cg.get(node_id)
    except Exception:
        node = None
    if not node:
        return None
    fm = node.get("frontmatter") or {}
    fm["protected"] = True
    fm["protection_reason"] = reason
    cg._write_node(node_id, os.path.join(cg.root, node["path"]),
                   fm, node.get("content") or "")
    e = _entry(cg, node_id)
    if e is not None:
        e["protected"] = True
        e["protection_reason"] = reason
    return {"node_id": node_id, "protected": True, "reason": reason}


def stats(cg):
    """保护面盘点：不可遗忘数 / 不可覆盖数 / 分层分布 / 自动保护命中数。"""
    nodes = ((getattr(cg, "index", None) or {}).get("nodes") or {})
    by_layer, ids, auto, immutable = {}, [], 0, []
    for nid in nodes:
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
