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


def _attempts(cg):
    """从台账统计每个节点的**尝试次数**与**最近尝试时间**（只读账本，坏行跳过）。"""
    seen = {}
    p = _log_path(cg)
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                nid = str(d.get("node_id") or "")
                if not nid:
                    continue
                t = float(d.get("t") or 0.0)
                cur = seen.get(nid) or (0, 0.0)
                seen[nid] = (cur[0] + 1, max(cur[1], t))
    except OSError:
        pass
    return seen


def pick(cg):
    """挑一条待办：**按「试过最少的优先，同等试过则最久没碰的优先」**。

    2026-11-19 修（用户夜里发现的问题）：此前只按 `last_access` 最小挑，而
    `step` 从不更新它 ⇒ **同一个节点被无限重复捡起**（实测一夜 14 条全是同一道题）。
    现改为读台账计次：试得少的先上，试过同样多的按最早那次往后排。
    这样队列会**往前走**，而不是原地踩。
    """
    idx = dict((getattr(cg, "index", {}) or {}).get("nodes") or {})
    if not idx:
        return None
    seen = _attempts(cg)
    for layer in LAYERS:
        cand = []
        for nid, e in idx.items():
            if str((e or {}).get("layer") or "") != layer:
                continue
            n, last_try = seen.get(nid, (0, 0.0))
            try:
                la = float((e or {}).get("last_access") or 0.0)
            except (TypeError, ValueError):
                la = 0.0
            cand.append((n, last_try, la, nid))
            if len(cand) >= MAX_SCAN:
                break
        if cand:
            cand.sort()
            return cand[0][3]
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


def brief(cg, node_id=None):
    """把「这一跳该想什么」整理成一段可读的思考简报（**只读，不写台账**）。

    用途（2026-11-19 使用者提议）：心跳的机械部分只负责**挑题**；
    真正的思考由我在前台做——所以它要把题目连同边界递给我，而不是替我下结论。
    """
    nid = node_id or pick(cg)
    if not nid:
        return {"ok": True, "node_id": None, "brief": "库里没有待办，这一跳没有题。"}
    try:
        node = cg.get(nid) or {}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "node_id": nid, "error": type(e).__name__}
    content = str(node.get("content") or "")
    fm = node.get("frontmatter") or {}
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    head = lines[0] if lines else ""
    seen = _attempts(cg).get(nid, (0, 0.0))
    parts = [
        "题：%s" % head[:120],
        "层：%s | 重要度：%s | 试过：%d 次" % (fm.get("layer"), fm.get("importance"), seen[0]),
        "还差什么（机械提炼）：%s" % _next_action(content),
    ]
    body = [l for l in lines[1:8]]
    if body:
        parts.append("原文节选：" + " / ".join(b[:60] for b in body[:4]))
    return {"ok": True, "node_id": nid, "layer": fm.get("layer"),
            "attempts": seen[0], "brief": "\n".join(parts)}


def cli(argv=None):
    """前台触发入口（使用者提议）：`python -m md_cg.intent_tick --peek|--once`。"""
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo not in sys.path:
        sys.path.insert(0, repo)
    from md_cg.mdcos import MdCGOS
    root = os.environ.get("MDCG_ROOT") or r"D:/program/AEIS/data/mdcg"
    cg = MdCGOS(root, actor="dsh端")
    if "--once" in args:
        r = step(cg, actor="foreground")
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    b = brief(cg)
    print(b.get("brief"))
    return 0 if b.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(cli())
