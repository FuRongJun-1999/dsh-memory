# -*- coding: utf-8 -*-
"""日桶 / 会话桶索引（bucketindex）——把「时间」与「会话身份」真正用起来。

实测现状（主库 34,218 节点，2026-11-09）：
  · `created_at` 覆盖 **100%**，按天聚集（09-29 有 2733 条、11-08 有 2516 条）；
  · `session` 覆盖 **99.4%**，但其中 **48% 是 `unattributed`**（无法归属）；
  · `bucket` 字段**不是**日桶/会话桶，而是**条件桶**（`cond_<topic>_<hash>`）——别混用。

所以两件事必须显式建出来：
  · **日桶** `day:YYYY-MM-DD`：由 `created_at` 确定性派生（不新增写入代价）；
  · **会话桶** `session:<sid>`：由 `frontmatter.session` 派生，`unattributed` 单独成桶不与他人合并。

索引文件（落库根目录，按需重建）：
  · `_days.json`     {day: [node_id, ...]}
  · `_sessions.json` {session: [node_id, ...]}

为什么用索引：查询期扫 34k 节点按日期过滤实测 **2–17 秒**（见 timeboost.scoped_recall 注释），
索引后是字典查找 + O(命中数) 取节点。
"""
from __future__ import annotations

import json
import os
import time

DAYS_FILE = "_days.json"
SESSIONS_FILE = "_sessions.json"
UNATTRIBUTED = "unattributed"


def day_of(ts):
    """epoch 秒 → 本地日期字符串；不可解析返回 None。"""
    try:
        return time.strftime("%Y-%m-%d", time.localtime(float(ts)))
    except (TypeError, ValueError, OSError):
        return None


def _fm(rec):
    if not isinstance(rec, dict):
        return {}
    fm = rec.get("frontmatter")
    return fm if isinstance(fm, dict) and fm else rec


def build(store, write=True):
    """从索引面重建两个桶。返回 {days, sessions, nodes, unattributed}。"""
    idx = getattr(store, "index", {}) or {}
    nodes = idx.get("nodes") or {}
    days = {}
    sessions = {}
    unattributed = 0
    for nid, rec in nodes.items():
        fm = _fm(rec)
        d = day_of(fm.get("created_at"))
        if d:
            days.setdefault(d, []).append(nid)
        sid = str(fm.get("session") or "") or UNATTRIBUTED
        if sid == UNATTRIBUTED:
            unattributed += 1
        sessions.setdefault(sid, []).append(nid)
    out = {"days": len(days), "sessions": len(sessions),
           "nodes": len(nodes), "unattributed": unattributed}
    if write:
        root = getattr(store, "root", None)
        if root:
            for name, data in ((DAYS_FILE, days), (SESSIONS_FILE, sessions)):
                path = os.path.join(root, name)
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
                    json.dump(data, fh, ensure_ascii=False)
                os.replace(tmp, path)
    return out


def _load(store, name):
    root = getattr(store, "root", None)
    if not root:
        return {}
    path = os.path.join(root, name)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def day_ids(store, day):
    return list(_load(store, DAYS_FILE).get(day) or ())


def session_ids(store, session):
    return list(_load(store, SESSIONS_FILE).get(str(session)) or ())


def all_days(store):
    """全部日桶键（升序未排序，调用方自行排序）。"""
    return list(_load(store, DAYS_FILE).keys())
