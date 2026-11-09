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


def _pick(store, ids, terms, cap, validity=False, now=None):
    """桶内按词面命中筛选（确定性）：命中词数降序 → **时间降序** → id；取前 cap。

    【#842】排序键必须**在截断之前**含时间：早先只按 (-hits, nid) 排再截 cap，
    9 条同等命中 + cap=8 时被 id 序丢掉的那条可能正是最新的（后置的时间排序
    已经拿不回来）。现在把 created_at 提到截断前，截断即保留「同分里最新的」。

    【#843】validity=True 时必须在此处就过滤过期节点：桶补召回是**在候选检索
    之后**追加的，若不在源头过滤，调用方显式要求的「排除过期」会被补召回推翻。
    """
    scored = []
    for nid in list(ids)[:MAX_SCAN]:
        node = store.get(nid)
        if not node:
            continue
        if validity and _is_expired(node, now):
            continue
        text = str(node.get("content") or "").lower()
        hits = sum(1 for t in terms if t in text)
        if hits:
            scored.append((-hits, _recency_key(node), nid, node))
    scored.sort()
    return [(node, 0.0, {"reason": "bucket_scope"}, [])
            for _h, _r, _nid, node in scored[:cap]]


def day_scope(store, query, day, cap=CAP, validity=False, now=None):
    """日桶召回：day 桶内按查询词筛选。索引缺失返回 None（调用方据此区分「无桶」与「空桶」）。"""
    ids = _bi.day_ids(store, day)
    if not ids:
        return None
    return _pick(store, ids, _terms(query), cap, validity=validity, now=now)


def session_scope(store, query, session, cap=CAP, validity=False, now=None):
    """会话桶召回；`unattributed` 明确拒绝（会话身份不可知，不冒充）。"""
    sid = str(session or "")
    if not sid or sid == _bi.UNATTRIBUTED:
        return None
    ids = _bi.session_ids(store, sid)
    if not ids:
        return None
    return _pick(store, ids, _terms(query), cap, validity=validity, now=now)


#: 通用默认：桶作用域**默认开启**（日期 + 会话是记忆的基本坐标，不是可选优化）。
DEFAULT_ON = True
#: 桶召回默认条数（会话桶 + 日桶合计）。
DEFAULT_CAP = 8
#: 日桶回溯天数上限（从最近一天往回数，够覆盖「前几天说的」）。
DAY_LOOKBACK = 14


def _is_expired(node, now=None):
    """节点是否已过期（valid_until 早于 now）。

    判据与检索面一致：只认 frontmatter.valid_until（ISO 日期/时间），解析失败不算过期
    （宁放过不错杀——过期是显式字段，不是推断）。
    """
    fm = node.get("frontmatter") or {}
    until = fm.get("valid_until") or fm.get("validUntil")
    if not until:
        return False
    t = now if now is not None else time.time()
    raw = str(until).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime(raw[:19], fmt)) < float(t)
        except ValueError:
            continue
    return False


def _recency_key(node):
    """桶内排序键：created_at 降序（最近的在前）。"""
    fm = node.get("frontmatter") or {}
    try:
        return -float(fm.get("created_at") or fm.get("valid_from") or 0)
    except (TypeError, ValueError):
        return 0.0


def scope_recall(store, query, session, now, cap=DEFAULT_CAP, validity=False):
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
        picked = _pick(store, ids, terms, cap, validity=validity, now=now)
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
            picked = _pick(store, _bi.day_ids(store, day), terms, cap - len(out),
                           validity=validity, now=now)
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