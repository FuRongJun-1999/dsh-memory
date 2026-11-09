# -*- coding: utf-8 -*-
"""inbox 终态机（C-11 2026-10-31）：proposal 从「待裁决」到「有归宿」。

四态（互斥、可复算）：
  · `accepted` 提案内容**已进主库**（`proposal.id` ∈ 索引节点）—— 事实判定，
    不靠人签、不靠时间；
  · `rejected` 裁决台账 `hippocampus/decisions.jsonl` 里有该 pid 的否决记录；
  · `expired`  超过 TTL（默认 7 天）仍未落库、未被裁决 —— 队列按时间自己清；
  · `pending`  以上都不成立，仍在等裁决（带 `due_t`：何时会自然过期）。

三条铁律（对齐矩阵 C-11 的验收与 §4 的刻线排除）：
  1. **只写自己的台账**：终态落 `hippocampus/inbox.state.jsonl`（append-only），
     **绝不写节点 frontmatter 的 `defer_state`**。`defer.py` 的口径是
     `defer_state ∈ {deferred, rejected}`，把已 ACCEPT 的 52 个 id 打成这两个值
     就是把活记忆做成「隐身」（列表/检索侧会被当待定过滤掉）。本模块因此
     **不 import defer、不写、不读节点正文**，只读索引快照与两份 jsonl。
  2. **幂等**：同一 pid 已有终态就不再写第二行；重跑只补新增的那几条。
  3. **只降不升**：`pending = 未终态数`，台账只追加 ⇒ pending 单调不增；
     任何一次重跑后的 pending 都不会比上一次大（除非有人往 inbox 追加新提案）。
"""
from __future__ import annotations

import json
import os
import time

#: 终态枚举（顺序即产出顺序，勿当优先级用；优先级在 `classify` 里显式写）
TERMINALS = ("accepted", "rejected", "expired")
PENDING = "pending"

#: 终态台账（相对数据根）
STATE_LOG = os.path.join("hippocampus", "inbox.state.jsonl")
INBOX = os.path.join("hippocampus", "inbox.jsonl")
DECISIONS = os.path.join("hippocampus", "decisions.jsonl")

DEFAULT_TTL_DAYS = 7.0
#: decisions.jsonl 里算「否决」的取值（现网实测只有 reject/noop 两种）
REJECT_WORDS = ("reject", "rejected", "deny", "denied", "refuse", "refused")


class TerminalError(Exception):
    """终态机错误（入参/文件形态不合预期）。"""


# --------------------------------------------------------------------------
# 读
# --------------------------------------------------------------------------

def _read_jsonl(path: str) -> list:
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                out.append(rec)
    return out


def _index_nodes(cg) -> dict:
    return (getattr(cg, "index", None) or {}).get("nodes") or {}


def load_state(root: str) -> dict:
    """已记终态：pid → 最后一次记录（append-only 台账，后写覆盖前写）。"""
    out = {}
    for rec in _read_jsonl(os.path.join(root, STATE_LOG)):
        pid = rec.get("pid")
        if pid:
            out[str(pid)] = rec
    return out


def proposals(root: str) -> list:
    """inbox 里的 proposal 行（原样，不做状态判定）。"""
    return _read_jsonl(os.path.join(root, INBOX))


def rejections(root: str) -> dict:
    """pid → 否决记录（取最后一条）。判定口径：decision/status 落在 REJECT_WORDS。"""
    out = {}
    for rec in _read_jsonl(os.path.join(root, DECISIONS)):
        pid = rec.get("pid")
        word = str(rec.get("decision") or rec.get("status") or "").lower()
        if pid and word in REJECT_WORDS:
            out[str(pid)] = rec
    return out


# --------------------------------------------------------------------------
# 判定（纯函数：给什么算什么，不读盘、不写盘）
# --------------------------------------------------------------------------

def classify(rows, *, nodes, rejected=None, recorded=None,
             ttl_days: float = DEFAULT_TTL_DAYS, now: float = None) -> dict:
    """把 inbox 行分成四态，返回逐条明细 + 汇总。

    `nodes` 是索引节点字典（只用来判「提案内容是否已落库」）；
    `rejected` 是 `rejections()` 的结果；`recorded` 是 `load_state()` 的结果。
    优先级：accepted > rejected > expired > pending（落库的事实最硬）。
    """
    ttl = float(ttl_days) * 86400.0
    now = time.time() if now is None else float(now)
    rejected = rejected or {}
    recorded = recorded or {}
    items = []
    seen = set()
    for row in rows:
        pid = str(row.get("pid") or "")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        nid = row.get("id")
        try:
            born = float(row.get("t") or 0.0)
        except (TypeError, ValueError):
            born = 0.0
        due = (born + ttl) if born else None
        st, why, ev = PENDING, "", None
        if nid and nid in nodes:
            st = "accepted"
            why = "提案内容已在主库索引里（id ∈ nodes）"
            ev = {"id": nid}
        elif pid in rejected:
            st = "rejected"
            rec = rejected[pid]
            why = f"裁决台账否决：{rec.get('decision') or rec.get('status')}｜{str(rec.get('reason') or '')[:80]}"
            ev = {"pid": pid, "decision": rec.get("decision"),
                  "record_node_id": rec.get("record_node_id")}
        elif due is not None and now > due:
            st = "expired"
            age = (now - born) / 86400.0
            why = f"超过 TTL {ttl_days:g} 天仍未落库/未被裁决（已存 {age:.1f} 天）"
            ev = {"age_days": round(age, 2), "due_t": due}
        else:
            age = ((now - born) / 86400.0) if born else None
            why = ("未落库、未被裁决，未到 TTL"
                   if due else "无 t 字段，无法计龄")
            ev = {"age_days": round(age, 2) if age is not None else None,
                  "due_t": due}
        rec = recorded.get(pid)
        items.append({"pid": pid, "id": nid, "kind": row.get("kind"),
                      "state": st, "why": why, "evidence": ev,
                      "recorded_state": (rec or {}).get("state"),
                      "t": born or None, "due_t": due})
    counts = {k: 0 for k in (PENDING,) + TERMINALS}
    for it in items:
        counts[it["state"]] += 1
    return {"items": items, "counts": counts, "total": len(items),
            "unique": len(seen), "ttl_days": float(ttl_days), "now": now,
            "duplicates": len(rows) - len(seen)}


# --------------------------------------------------------------------------
# 迁移（唯一写点：追加终态台账）
# --------------------------------------------------------------------------

def migrate(cg, *, ttl_days: float = DEFAULT_TTL_DAYS, apply: bool = True,
            actor: str = "lineage", now: float = None, root: str = None) -> dict:
    """把新判定的终态追加进 `inbox.state.jsonl`；`apply=False` 只预演。

    返回 {before_pending, after_pending, written, skipped, counts, items,
          log_path, log_bytes, monotonic}。
    `monotonic` == True 表示 after_pending <= before_pending（队列只降不升）。
    """
    root = root or cg.root
    rows = proposals(root)
    nodes = _index_nodes(cg)
    rejected = rejections(root)
    recorded = load_state(root)
    rep = classify(rows, nodes=nodes, rejected=rejected, recorded=recorded,
                   ttl_days=ttl_days, now=now)
    before_pending = rep["counts"][PENDING]
    log_path = os.path.join(root, STATE_LOG)
    to_write = []
    for it in rep["items"]:
        if it["state"] == PENDING:
            continue
        prev = recorded.get(it["pid"])
        if prev and prev.get("state") == it["state"]:
            continue            # 已记同一终态 ⇒ 幂等跳过
        to_write.append({"t": time.time(), "pid": it["pid"], "id": it.get("id"),
                         "kind": it.get("kind"), "state": it["state"],
                         "why": it["why"], "evidence": it.get("evidence"),
                         "prev_state": (prev or {}).get("state"),
                         "ttl_days": float(ttl_days), "actor": actor,
                         "schema": 1})
    if apply and to_write:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            for rec in to_write:
                f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
    after = load_state(root)
    after_pending = sum(1 for it in rep["items"]
                        if (after.get(it["pid"]) or {}).get("state") is None)
    recorded_before = sum(1 for it in rep["items"] if it["pid"] in recorded)
    recorded_after = sum(1 for it in rep["items"] if it["pid"] in after)
    return {"root": root, "applied": bool(apply),
            "before_pending": before_pending,
            "after_pending": after_pending,
            "before_unrecorded": rep["total"] - recorded_before,
            "after_unrecorded": rep["total"] - recorded_after,
            "recorded": recorded_after,
            "written": len(to_write) if apply else 0,
            "would_write": len(to_write),
            "skipped_idempotent": sum(1 for it in rep["items"]
                                      if it["state"] != PENDING
                                      and (recorded.get(it["pid"]) or {}).get("state")
                                      == it["state"]),
            "counts": rep["counts"], "total": rep["total"],
            "duplicates": rep["duplicates"],
            "monotonic": after_pending <= before_pending,
            "log_path": log_path,
            "log_bytes": (os.path.getsize(log_path)
                          if os.path.exists(log_path) else 0),
            "items": rep["items"]}


def summary(cg, *, ttl_days: float = DEFAULT_TTL_DAYS, now: float = None,
            root: str = None) -> dict:
    """只读盘点：不写任何文件。`pending` 与台账里已记的终态合并后给出。

    两个分母别混：
      · `pending`    语义上还在等裁决（索引里没落库、台账没否决、没到期）；
      · `unrecorded` 台账里**还没有任何终态记录**的行 —— 终态机要收口的审计缺口。
    迁移的资金流向就是把 unrecorded 从「inbox 行数」压到「真正 pending 数」。
    """
    root = root or cg.root
    rec = load_state(root)
    rows = proposals(root)
    rep = classify(rows, nodes=_index_nodes(cg),
                   rejected=rejections(root), recorded=rec,
                   ttl_days=ttl_days, now=now)
    recorded_n = sum(1 for r in rows if str(r.get("pid")) in rec)
    return {"total": rep["total"], "counts": rep["counts"],
            "ttl_days": rep["ttl_days"],
            "terminal": sum(rep["counts"][k] for k in TERMINALS),
            "pending": rep["counts"][PENDING],
            "recorded": recorded_n, "unrecorded": rep["total"] - recorded_n,
            "duplicates": rep["duplicates"],
            "items": rep["items"]}


def check_accepted_defer_none(cg, *, recorded=None, root: str = None) -> dict:
    """**刻线守卫**：已 ACCEPT（已落库）的 proposal 对应的节点，`defer_state`
    必须仍是 None —— 谁把终态做成写节点 frontmatter，这里立刻报红。"""
    root = root or cg.root
    nodes = _index_nodes(cg)
    recorded = recorded if recorded is not None else load_state(root)
    acc = [r for r in proposals(root) if r.get("id") in nodes]
    bad = []
    for row in acc:
        nid = row.get("id")
        e = nodes.get(nid) or {}
        st = e.get("defer_state")
        if st not in (None, ""):
            bad.append({"id": nid, "pid": row.get("pid"), "defer_state": st})
    return {"accepted": len(acc), "defer_state_not_none": len(bad),
            "ok": not bad, "bad": bad[:10],
            "note": ("accepted = 提案 id 已在主库索引里；这些是活记忆，"
                     "defer_state 必须保持 None（defer.py 的 deferred/rejected "
                     "会被列表与检索当待定过滤）")}
