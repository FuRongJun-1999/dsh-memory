# -*- coding: utf-8 -*-
"""桶作用域召回（bucketscope）——日桶 / 会话桶的**召回侧**落地。

两类桶的定死口径（实测主库 34,218 节点，2026-11-09）：
  · **日桶** = `created_at` 的本地日期，`day:YYYY-MM-DD`。83 个桶；查询 5ms（索引）vs 2–17s（全扫）。
  · **会话桶** = `frontmatter.session`，`session:<sid>`。631 个桶；**72% 是 `unattributed`**——
    这类节点的会话身份不可知，**只按日桶走**，绝不与他人合并（合并会把无关内容塞进同一上下文）。

两条边界（都是实测教训）：
  1. **日桶不能当「那天只写了这些」**：主库 2026-11-08 有 14,217 条（多日批量写入挤到同一天），
     所以日桶召回必须**再按查询词过滤**，不能整桶直接塞给模型。
  2. 会话桶同理：最大真实会话 3,026 条，整桶塞不进去。

故本模块只做**受控召回**：桶内按查询词面筛选 → 取前 cap 条 → 以 0 分追加（不抢名次）。
"""
from __future__ import annotations

import re

from . import bucketindex as _bi

#: 单次桶召回上限（与 recent_tail 同一量级，避免撑爆预算）。
CAP = 8


def _terms(q):
    return [t.lower() for t in re.split(r"[\s,，、;；。！？:：()（）\[\]【】]+", q or "")
            if len(t) >= 2]


#: 桶内扫描预算：桶可能上万条（主库 2026-11-08 有 14,217 条），逐条读盘会拖到秒级；
#: 实测 14k 桶全扫 2.9s、预算 800 条约 0.2s。故按**id 序**取前 MAX_SCAN 条（确定性、可复算），
#: 代价是桶内覆盖不全——这是「快」与「全」的显式取舍，不是静默降级。
MAX_SCAN = 800


def _pick(store, ids, terms, cap):
    """桶内按词面命中筛选（确定性）：命中词数降序，同分按 id；取前 cap。"""
    scored = []
    for nid in list(ids)[:MAX_SCAN]:
        node = store.get(nid)
        if not node:
            continue
        text = str(node.get("content") or "").lower()
        hits = sum(1 for t in terms if t in text)
        if hits:
            scored.append((-hits, nid, node))
    scored.sort()
    return [(node, 0.0, {"reason": "bucket_scope"}, []) for _h, _nid, node in scored[:cap]]


def day_scope(store, query, day, cap=CAP):
    """日桶召回：day 桶内按查询词筛选。索引缺失返回 None（调用方据此区分「无桶」与「空桶」）。"""
    ids = _bi.day_ids(store, day)
    if not ids:
        return None
    return _pick(store, ids, _terms(query), cap)


def session_scope(store, query, session, cap=CAP):
    """会话桶召回；`unattributed` 明确拒绝（会话身份不可知，不冒充）。"""
    sid = str(session or "")
    if not sid or sid == _bi.UNATTRIBUTED:
        return None
    ids = _bi.session_ids(store, sid)
    if not ids:
        return None
    return _pick(store, ids, _terms(query), cap)