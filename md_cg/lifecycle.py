# -*- coding: utf-8 -*-
"""md_cg · 节点显式生命周期状态机（可学习优点 ②·显式状态机）

出处（pi）：
    运行操作 = 13 个**叶子显式状态机**（`session/types.ts:315-329`），drive 循环按
    `at` 分发；一轮无任何进展即抛 `SessionInvariantError`（`drive.ts:101-104`）
    ——非法迁移在**结构上不可能**，而不是靠调用方自觉。

灵枢现状（本模块要收口的四处散落状态）：
    · `writelimit._demote`  用 **tag** `tidy:converged` 记「同构聚合已定型」
    · `forgetting.reinforce` 用 **importance** 升降记「强化 / 弱化」
    · `protect`             用 **fm.protected** 记「不可遗忘」
    · `_evolution/ledger.md` 记账本
    四种载体各说各话：谁都能把已定型节点再降一次权、把归档节点悄悄覆写成新的，
    而**没有任何地方校验「这一步迁移合不合法」**。

本模块是该问题的唯一真源：状态集 `STATES` + 合法迁移表 `TRANSITIONS` + 单点裁决
`check()` + 单点推进 `set_state()`。口径：

  · 状态落 **frontmatter.lifecycle_state**（节点 md 是唯一真源）；索引快照带同名字
    段 →「免读文件可查」（`_index.json` 即可回答「这节点什么状态」）。
    **为何不叫 `state`**（对交接文档建议集的偏离，取证理由）：`state` 在 md_cg 内
    已被**裁决四态**（ACCEPT/REJECT/DEFER/BLINDSPOT）占用——`audit._verdict` 的返
    回体、`judge_qualification()` 的返回、`mdcos.search` 结果项、检索结果条目的
    `entry["state"]` 全都用它。若生命周期也叫 `state`，则同一外层结构里
    `entry["state"]`（裁决）与 `entry["frontmatter"]["state"]`（生命周期）并存，
    人类与 agent 读面必生歧义；本仓既有 `self_state` 即为同一动机的先例。
    故取 `lifecycle_state`：语义自明、零歧义。
  · 存量节点**缺 state 即视为 active**（`state_of` 的缺省），故不回填也能工作；
    `backfill()` 提供一次性回填（幂等、可 dry-run）。
  · **受保护节点豁免降级**：`protected`/`immutable` 节点不接受降级迁移，需
    `override=True` 显式放行——「保护 = 不可遗忘」在状态层的落点。
  · 非法迁移**拒绝**（负路由）：`check()` 返回 `(ok, code, reason)`，`set_state()`
    返回 `ok=False` + 机器可读 `error` 而不抛；写路径要硬拒用 `require_transition()`。
  · 永不删除：`archived` 只是状态，节点文件仍在（可逆、可审计）。
  · 幂等：同状态迁移是 no-op（不写盘、不留痕）——重复发起不会把历史刷爆。

状态语义（建议集，逐级降级 / 逐级回升）：
    active    正常：参与检索与写入面
    converged 已定型：同构聚合的成员（writelimit tidy 的落点）
    demoted   已降权：importance 被下调（forgetting 弱化的落点）
    archived  已归档：不再参与默认检索，但文件保留、可显式恢复
"""
from __future__ import annotations

import os
import time

from .fsutil import append_jsonl

#: 状态全集。顺序即「降级方向」：active → converged → demoted → archived。
STATES = ("active", "converged", "demoted", "archived")
#: frontmatter 字段名（索引快照同名透出）。刻意避开 `state`——见模块 docstring
#: 「为何不叫 state」：该名已被裁决四态占用，同名会让读面产生歧义。
STATE_FIELD = "lifecycle_state"
#: 迁移留痕字段（frontmatter 侧历史，滚动保留最近 HISTORY_KEEP 条）
HISTORY_FIELD = "state_history"
HISTORY_KEEP = 20
#: 状态迁移审计（append-only，与 _forgetting.jsonl / _maintain.jsonl 同风格）
AUDIT_FILE = "_lifecycle.jsonl"

#: 降级序位（用于「受保护豁免降级」的判定）
_RANK = {"active": 0, "converged": 1, "demoted": 2, "archived": 3}

#: 合法迁移表——**逐级降级、逐级回升**，不跳级：
#:   active   ⇄ converged        定型 / 定型撤销
#:   active    → demoted         直接弱化（forgetting 降权）
#:   converged → demoted        定型后再弱化
#:   demoted  ⇄ active           被强化回升 / 再弱化
#:   demoted   → archived        归档
#:   archived  → active          显式恢复
#: 刻意不收录的（即拒绝的）：active→archived（跳级归档）、archived→converged /
#: archived→demoted（跳级回落）、converged→archived（跳级归档）。
TRANSITIONS = frozenset({
    ("active", "converged"),
    ("active", "demoted"),
    ("converged", "active"),
    ("converged", "demoted"),
    ("demoted", "active"),
    ("demoted", "archived"),
    ("archived", "active"),
})


# 生效条件：以 src、dst、code、reason 四个实参构造时，父类 ValueError 消息由 f-string 拼成「非法状态迁移 src→dst（code）：reason」，并把四个值分别存为同名属性。
class TransitionError(ValueError):
    """非法生命周期迁移（写路径用 `require_transition` 直接抛这个）。"""

# 生效条件：接收 src、dst、code、reason 四个实参，调用 super().__init__ 传入 f"非法状态迁移 {src}→{dst}（{code}）：{reason}"，并将四者依次赋给 self.src、self.dst、self.code、self.reason。
    def __init__(self, src, dst, code, reason):
        super().__init__(f"非法状态迁移 {src}→{dst}（{code}）：{reason}")
        self.src, self.dst, self.code, self.reason = src, dst, code, reason


# ---------------------------------------------------------------- 纯函数裁决

# 生效条件：fm 非 dict 直接返回 "active"；fm 为 dict 时取 fm.get(STATE_FIELD)，该值属于 STATES 则原样返回，缺键或值不在 STATES 均返回 "active"。
def state_of(fm) -> str:
    """frontmatter → 状态；缺字段或未知值 → "active"（存量兼容，不猜测）。"""
    if not isinstance(fm, dict):
        return "active"
    s = fm.get(STATE_FIELD)
    return s if s in STATES else "active"


# 生效条件：按 _RANK.get(dst, 0) > _RANK.get(src, 0) 判定，src 或 dst 不在 _RANK 键中时该侧按 0 参与比较。
def is_downgrade(src: str, dst: str) -> bool:
    """是否向「更低」的状态迁移（active < converged < demoted < archived）。"""
    return _RANK.get(dst, 0) > _RANK.get(src, 0)


# 生效条件：src 不在 STATES 时先替换为 "active"；dst 不在 STATES 返回 False；替换后 src == dst 返回 True；否则返回 (src, dst) in TRANSITIONS 的布尔值。
def can_transition(src, dst) -> bool:
    """迁移是否合法（含幂等；未知 src 按 active 处理）。"""
    src = src if src in STATES else "active"
    if dst not in STATES:
        return False
    if src == dst:
        return True                     # 幂等：同状态是 no-op
    return (src, dst) in TRANSITIONS


# 生效条件：src 不在 STATES 时替换为 "active"；dst 不在 STATES 返回 (False, 'unknown_state', ...)；src == dst 返回 (True, 'noop', ...)；(src, dst) 不在 TRANSITIONS 返回 (False, 'illegal_transition', ...)；is_downgrade(src, dst) 且 protected 为真且 override 为假时返回 (False, 'protected', ...)；其余返回 (True, 'ok', f'{src}→{dst} 合法')。
def check(src, dst, protected: bool = False, override: bool = False):
    """迁移合法性裁决 → `(ok, code, reason)`。**唯一裁决点**（纯函数，无 IO）。

    code 取值：`ok` / `noop`（同状态，不写盘）/ `unknown_state` /
    `illegal_transition` / `protected`。
    """
    src = src if src in STATES else "active"
    if dst not in STATES:
        return False, "unknown_state", f"未知状态 {dst!r}（允许：{STATES}）"
    if src == dst:
        return True, "noop", "状态未变（幂等，不写盘）"
    if (src, dst) not in TRANSITIONS:
        legal = "、".join(f"{a}→{b}" for a, b in sorted(TRANSITIONS))
        return False, "illegal_transition", (
            f"{src}→{dst} 不在合法迁移表内（允许：{legal}）——"
            "降级与回升都须逐级，跨级迁移一律拒绝")
    if is_downgrade(src, dst) and protected and not override:
        return False, "protected", (
            f"受保护节点不接受降级迁移 {src}→{dst}（保护 = 不可遗忘）；"
            "确需降级请显式 override=True")
    return True, "ok", f"{src}→{dst} 合法"


# 生效条件：以 src、dst、protected、override 调 check 后，ok 为真时返回其 code，ok 为假时抛 TransitionError，抛出时 src 参数在 STATES 中则原样、否则替换为 "active"，dst、code、why 按源码透传。
def require_transition(src, dst, protected: bool = False, override: bool = False):
    """合法则返回 code，非法则抛 `TransitionError`（写路径的硬拒入口）。"""
    ok, code, why = check(src, dst, protected=protected, override=override)
    if not ok:
        raise TransitionError(src if src in STATES else "active", dst, code, why)
    return code


# 生效条件：src 取 state_of(fm)，prot 取 bool(fm.get("protected") or fm.get("immutable"))；check 返回 ok 假或 code == "noop" 时原样返回 (ok, code, why) 且不改 fm；否则把 dst 写入 fm[STATE_FIELD]，并把含 at/from/to/reason/actor 的新条目追加到由 fm.get(HISTORY_FIELD) or [] 复制的列表、截取末 HISTORY_KEEP 条写回 fm[HISTORY_FIELD]，返回 (True, code, why)。
def stamp(fm: dict, dst: str, reason: str = None, actor: str = None,
          override: bool = False):
    """在给定 frontmatter 上**就地**推进状态（无 IO）→ `(ok, code, why)`。

    与 `set_state()` 共用同一裁决点（`check`），供**需与其他字段同批落盘**的收
    口点使用——`writelimit` 的降权要一次写盘改 tags/importance/状态，`forgetting`
    的强化同理；否则状态得单独再写一次盘（同一节点两倍 IO）。
    合法且非幂等时写入 `STATE_FIELD` 并追加 `HISTORY_FIELD`；失败/幂等不动 fm。
    """
    src = state_of(fm)
    prot = bool(fm.get("protected") or fm.get("immutable"))
    ok, code, why = check(src, dst, protected=prot, override=override)
    if not ok or code == "noop":
        return ok, code, why
    fm[STATE_FIELD] = dst
    hist = list(fm.get(HISTORY_FIELD) or [])
    hist.append({"at": time.time(), "from": src, "to": dst,
                 "reason": reason, "actor": actor})
    fm[HISTORY_FIELD] = hist[-HISTORY_KEEP:]
    return True, code, why


# ---------------------------------------------------------------- 索引同步

# 生效条件：cg.index 非 dict 时静默 return；index 的 "nodes" 中查不到 node_id 时 return；否则把 fm.get(STATE_FIELD)（缺键即 None）写入该条目，cg._dirty 为 dict 时记入该条目并调用可调用的 cg.flush。
def _sync_index(cg, node_id, fm) -> None:
    """把 state 同步进索引快照（免读文件可查）；无索引实现时静默跳过。

    只同步 `state` 一个键：迁移历史已在 frontmatter 与 `_lifecycle.jsonl` 留痕，
    放进索引会让快照无谓膨胀。
    """
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


# ---------------------------------------------------------------- 推进 / 回填

# 生效条件：cg.get(node_id) 为假值返回 {'ok': False, 'error': 'node_not_found', ...}；否则以 state_of(fm) 作 src 调 stamp——stamp 不 ok 返回 ok=False + error=code，code == "noop" 返回 ok=True + changed=False；其余情况取 fm[HISTORY_FIELD][-1]["at"] 后写盘、_sync_index 并追加审计 JSONL（append_jsonl 抛异常被吞掉），返回 ok=True + changed=True。
def set_state(cg, node_id: str, dst: str, reason: str = None,
              actor: str = None, override: bool = False) -> dict:
    """推进一个节点的生命周期状态（**唯一推进入口**）。

    非法迁移不走异常而是返回 `{"ok": False, "error": <code>, ...}`（负路由：
    调用方自行决定降级处理；要硬拒请用 `require_transition`）。幂等迁移返回
    `changed=False` 且不写盘。返回体始终带 `from` / `to` / `code` 便于审计。
    """
    node = cg.get(node_id)
    if not node:
        return {"ok": False, "error": "node_not_found", "node_id": node_id}
    fm = dict(node.get("frontmatter") or {})
    src = state_of(fm)
    ok, code, why = stamp(fm, dst, reason=reason, actor=actor, override=override)
    base = {"node_id": node_id, "from": src, "to": dst, "code": code}
    if not ok:
        return {**base, "ok": False, "error": code, "reason": why}
    if code == "noop":
        return {**base, "ok": True, "changed": False, "reason": why}
    at = fm[HISTORY_FIELD][-1]["at"]
    cg._write_node(node_id, os.path.join(cg.root, node["path"]), fm,
                   node.get("content") or "")
    _sync_index(cg, node_id, fm)
    try:
        append_jsonl(os.path.join(cg.root, AUDIT_FILE), {
            "t": at, "action": "set_state", "node_id": node_id,
            "from": src, "to": dst, "reason": reason, "actor": actor,
            "override": bool(override)})
    except Exception:                    # 审计失败不阻断状态推进
        pass
    return {**base, "ok": True, "changed": True, "reason": why, "at": at}


# 生效条件：nodes 取 (cg.index or {}).get("nodes") or {}，遍历中缺 STATE_FIELD 或该值不在 STATES 的 nid 计入 missing（累计数达 limit 即 break，limit <= 0 时立即 break 使 missing 为空），apply 假值只返回 dry_run=True 的盘点结果，apply 为真时对每个 missing 中 cg.get 取不到的记入 failed、取到的把 state_of(fm) 显式写回 fm[STATE_FIELD] 并写盘与 _sync_index 后记入 done，返回 dry_run=False 的结果。
def backfill(cg, apply: bool = False, limit: int = 5000) -> dict:
    """存量回填：把缺 `state` 的节点显式补成 `active`（幂等）。

    缺字段本就按 active 解释（`state_of`），故回填**不是让功能工作的前提**，
    而是把「缺省」变成「显式」——索引/审计里从此可直接读到状态。
    `apply=False`（默认）只盘点。写不动（文件取不回）的节点进 `failed` 如实上报。
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
        fm[STATE_FIELD] = state_of(fm)   # 缺省 active → 显式落盘
        cg._write_node(nid, os.path.join(cg.root, node["path"]), fm,
                       node.get("content") or "")
        _sync_index(cg, nid, fm)
        done.append(nid)
    return {"ok": True, "dry_run": False, "scanned": len(nodes),
            "missing": len(missing), "backfilled": len(done),
            "planned": done[:50], "failed": failed[:20]}