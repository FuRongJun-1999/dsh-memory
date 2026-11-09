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

import os
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


#: 通用默认：桶作用域**默认开启**（日期 + 会话是记忆的基本坐标，不是可选优化）。
DEFAULT_ON = True
#: 桶召回默认条数（会话桶 + 日桶合计）。
DEFAULT_CAP = 8
#: 日桶回溯天数上限（从最近一天往回数，够覆盖「前几天说的」）。
DAY_LOOKBACK = 14


def _recency_key(node):
    """桶内排序键：created_at 降序（最近的在前）。"""
    fm = node.get("frontmatter") or {}
    try:
        return -float(fm.get("created_at") or fm.get("valid_from") or 0)
    except (TypeError, ValueError):
        return 0.0


def scope_recall(store, query, session, now, cap=DEFAULT_CAP):
    """**默认口径**的桶作用域召回：会话桶优先 → 日桶按日期倒排 → 都按时间降序。

    使用者口径（2026-11-09）：
      「日期、会话是默认就应该开启的；会话优先使用会话桶，然后按日期倒排，
        优先取自己最近的。条件才是筛选方式。」

    故本函数与「重排」无关——它只**补召回**：返回的每条 score=0.0，
    不抢正排名次，但一定进入候选（调用方可按预算追加）。
    """
    terms = _terms(query)
    out = []
    seen = set()
    # ① 会话桶优先（自己的最近记录）
    sid = str(session or "")
    if sid and sid != _bi.UNATTRIBUTED:
        ids = _bi.session_ids(store, sid)
        picked = _pick(store, ids, terms, cap)
        for node, score, qual, prov in picked:
            qual = dict(qual)
            qual["bucket"] = "session"
            out.append((node, score, qual, prov))
            seen.add(node.get("id"))
    # ② 桶顺序：**范围选择优先**（状态追踪式共现推断），否则按日期倒排。
    #    MDCG_SCOPE_SELECT=1（缺省）→ 用 scopeselect 排序；=0 回落「最近优先」。
    #    依据：bench 实测共现推断时间桶 94.20%（字面无关），词面消融仅 90.76%。
    _ordered_days = None
    try:
        if os.environ.get("MDCG_SCOPE_SELECT", "1") != "0":
            from . import scopeselect as _ss      # noqa: PLC0415
            _picked = _ss.pick_scopes(store, query, session=session, limit=DAY_LOOKBACK)
            _ordered_days = [key for kind, key, _s in _picked if kind == "day"]
    except Exception:          # noqa: BLE001 —— 推断失败回落最近优先
        _ordered_days = None
    if not _ordered_days:
        _ordered_days = sorted(_bi.all_days(store), reverse=True)[:DAY_LOOKBACK]
    # ② 日桶按上述顺序取
    if len(out) < cap:
        days = _ordered_days
        for day in days:
            if len(out) >= cap:
                break
            picked = _pick(store, _bi.day_ids(store, day), terms, cap - len(out))
            for node, score, qual, prov in picked:
                if node.get("id") in seen:
                    continue
                qual = dict(qual)
                qual["bucket"] = "day:%s" % day
                out.append((node, score, qual, prov))
                seen.add(node.get("id"))
    # ③ 排序：**会话桶整体优先**，再按时间降序；日桶同样按时间降序。
    # 使用者口径「会话优先使用会话桶，然后按日期倒排」——只按时间排会让日桶插到会话前面（实测发生过）。
    def _key(it):
        bucket = ((it[2] or {}).get("bucket") or "")
        return (0 if bucket == "session" else 1, _recency_key(it[0]))
    out.sort(key=_key)
    return out[:cap]