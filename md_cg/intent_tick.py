# -*- coding: utf-8 -*-
"""主动队列（2026-11-18）：把「醒着」接上「起身」。

背景（真实读数，不是设想）：心跳连跑 5.6 小时，`task_running: false`；
库里躺着 61 条我自己写的 `unresolved`、2 条 `goals`——**想做的事早就有了，
缺的只是「没人提问时去取一条」的那一跳**。本模块就是这一跳。

## 它做什么

心跳 tick 调一次：从 `unresolved` / `goals` 里挑**最久没被碰过**的一条，
把它「还差什么」提炼成一行下一步，落 `_intent.jsonl`。

## 它**不**做什么（边界，刻意）

· **不写记忆**——只读节点、只追加一行台账。无人值守时对库做写操作，风险不对等；
· **不替使用者裁决**——它产出的是「下一步候选」，不是结论；
· **不追求像欲望**——可检验的只有一件：没人提问时是否产生了动作，
  且那个动作能指回某条我自己写下的待解问题。

## 档位

`MDCG_INTENT_TICK`：observe（缺省）/ off。间隔 `MDCG_INTENT_INTERVAL`（秒，缺省 1800）。
"""
from __future__ import annotations

import json
import os
import time

MODE_ENV = "MDCG_INTENT_TICK"
INTERVAL_ENV = "MDCG_INTENT_INTERVAL"
DEFAULT_INTERVAL = 1800.0
LAYERS = ("unresolved", "goals")
LOG_NAME = "_intent.jsonl"
MAX_SCAN = 4000

_STATS = {"ticks": 0, "picked": 0, "empty": 0}


def mode(environ=None):
    """observe（缺省）/ off。非法值一律回落 observe（不静默关死）。"""
    # 字面量直读 os.environ：登记面的 AST 观测要求真实读点在源码里
    # （常量名/间接引用都不算，实测会判「未观测到」）。
    # 两参 get + 字面量缺省：登记面的 AST 观测只认这种形态
    # （`get("X") or 'lit'` 与间接变量都不算，实测会判「未观测到」）。
    raw = (os.environ.get("MDCG_INTENT_TICK", "observe") if environ is None
           else environ.get("MDCG_INTENT_TICK", "observe"))
    raw = str(raw or "observe").strip().lower()
    return raw if raw in ("observe", "off") else "observe"


def interval(environ=None):
    """tick 间隔秒数（缺省 1800；非法值回落缺省）。"""
    raw = (os.environ.get("MDCG_INTENT_INTERVAL", 1800.0) if environ is None
           else environ.get("MDCG_INTENT_INTERVAL", 1800.0))
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL
    return v if v > 0 else DEFAULT_INTERVAL


def stats():
    return dict(_STATS)


def _log_path(cg):
    return os.path.join(getattr(cg, "root", "") or ".", LOG_NAME)


def recent(cg, limit=10):
    """最近若干条记录（读回用；坏行跳过）。"""
    p = _log_path(cg)
    out = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    continue
    except OSError:
        return []
    return out[-limit:]


def pick(cg):
    """挑一条待办：unresolved 优先，其次 goals；同层内取 last_access 最小（最久没碰）。"""
    idx = dict((getattr(cg, "index", {}) or {}).get("nodes") or {})
    if not idx:
        return None
    for layer in LAYERS:
        cand = []
        for nid, e in idx.items():
            if str((e or {}).get("layer") or "") != layer:
                continue
            try:
                la = float((e or {}).get("last_access") or 0.0)
            except (TypeError, ValueError):
                la = 0.0
            cand.append((la, nid))
            if len(cand) >= MAX_SCAN:
                break
        if cand:
            cand.sort()
            return cand[0][1]
    return None


def _next_action(content):
    """从正文里提炼「还差什么」：优先取含 待查/缺/未解 的行，否则如实说没有。"""
    text = str(content or "")
    marks = ("待查", "缺", "未解", "待定", "TODO", "下一步")
    for line in text.splitlines():
        s = line.strip().lstrip("#").strip()
        if s and any(m in s for m in marks):
            return s[:160]
    return "缺：未写明推进条件（先补这一条）"


def step(cg, node_id=None, *, actor="intent_tick", dry_run=False):
    """执行一次「起身」：选一条 + 提炼下一步 + 追加台账。**不写记忆**。"""
    _STATS["ticks"] += 1
    if mode() == "off":
        return {"ok": False, "skipped": "mode=off"}
    nid = node_id or pick(cg)
    if not nid:
        _STATS["empty"] += 1
        return {"ok": True, "picked": None, "reason": "库里没有待办（unresolved/goals 皆空）"}
    try:
        node = cg.get(nid) or {}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "picked": nid, "error": type(e).__name__}
    content = node.get("content") or ""
    fm = node.get("frontmatter") or {}
    rec = {"t": time.time(),
           "actor": actor,
           "node_id": nid,
           "layer": str(fm.get("layer") or ""),
           "headline": next((l.strip() for l in content.splitlines() if l.strip()), "")[:120],
           "next_action": _next_action(content)}
    _STATS["picked"] += 1
    if dry_run:
        return {"ok": True, "picked": nid, "record": rec, "dry_run": True}
    try:
        with open(_log_path(cg), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + chr(10))
    except OSError as e:
        return {"ok": False, "picked": nid, "error": "log_%s" % type(e).__name__}
    return {"ok": True, "picked": nid, "record": rec}