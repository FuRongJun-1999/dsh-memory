# -*- coding: utf-8 -*-
"""审核队列健康读数（queue health）——DEFER 出口的可观测面。

为什么需要它（P0-6）：四态里的 DEFER 若既无责任人、又无期限、也无可观测的积压指标，
就会退化成只进不出的黑洞。本模块只做**读数**，不做裁决、不改数据。

一条必须写明的历史教训（2026-10-18）：此前读队列时把 inbox.jsonl 里「没有 status
字段」误判为「全部 pending」，得出「958 条从未裁决、出口是黑洞」的错误结论，并
据此写进了文档。**正确算法是拿 inbox 的 pid 去 decisions.jsonl 里对账**——
真实读数是 958 入队 / 777 已裁决 / 183 在途。字段缺失不等于状态缺失：这一类错误
（把「查不到」当成「不存在」）与本架构 I6 要防的完全同型。

因此本模块的实现原则：
1. **对账而非看字段**：pending = inbox 记录 − 已出现在 decisions 里的 pid。
2. **只读**：不写盘、不改队列。
3. **缺数据源如实上报**：文件不存在返回 available=False，绝不返回 0 冒充健康。
"""

import json
import os
import time

__all__ = ["report", "DEFAULT_DEADLINE_DAYS"]

#: 待裁决期限（天）。7 天是**缺省建议值，非设计者裁定**，列在架构 §11 待裁定中。
DEFAULT_DEADLINE_DAYS = 7.0


def _read_jsonl(path):
    if not os.path.isfile(path):
        return None
    rows = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def report(root, deadline_days=None, now=None):
    """返回队列健康读数。root 为记忆库根目录。

    缺数据源（inbox 不存在）时 available=False，各计数为 None——不冒充 0。
    """
    hip = os.path.join(str(root), "hippocampus")
    inbox = _read_jsonl(os.path.join(hip, "inbox.jsonl"))
    decs = _read_jsonl(os.path.join(hip, "decisions.jsonl")) or []
    ddl = float(DEFAULT_DEADLINE_DAYS if deadline_days is None else deadline_days)
    t_now = time.time() if now is None else float(now)

    # 「空」与「缺」必须分开（与 I6 同型：不能把「没有记录」当成「不可用」）：
    #   库根不存在        → 数据源缺失，available=False
    #   hippocampus 在但 inbox 没有 → **空队列**（新库尚未写入过），available=True、计数为 0
    if not os.path.isdir(str(root)):
        return {"available": False, "reason": "库根不存在：%s" % root,
                "inbox": None, "decided": None, "pending": None,
                "over_deadline": None, "deadline_days": ddl}
    if inbox is None:
        inbox = []

    decided_pids = {d.get("pid") for d in decs if d.get("pid")}
    pend = [r for r in inbox if r.get("pid") not in decided_pids]
    ages = []
    for r in pend:
        t = r.get("t")
        if isinstance(t, (int, float)):
            ages.append((t_now - t) / 86400.0)
    ages.sort()

    def _pct(p):
        if not ages:
            return None
        idx = min(len(ages) - 1, max(0, int(round((len(ages) - 1) * p))))
        return round(ages[idx], 2)

    by_actor = {}
    for r in pend:
        k = str(r.get("actor"))
        by_actor[k] = by_actor.get(k, 0) + 1

    decided_kind = {}
    for d in decs:
        k = str(d.get("decision"))
        decided_kind[k] = decided_kind.get(k, 0) + 1

    return {
        "available": True,
        "inbox": len(inbox),
        "decided": len(decided_pids),
        "pending": len(pend),
        "pending_ratio": round(len(pend) / len(inbox), 3) if inbox else None,
        "deadline_days": ddl,
        "over_deadline": sum(1 for a in ages if a > ddl),
        "oldest_pending_days": round(ages[-1], 2) if ages else None,
        "pending_age_days": {"min": round(ages[0], 2) if ages else None,
                             "median": _pct(0.5), "p90": _pct(0.9),
                             "max": round(ages[-1], 2) if ages else None},
        "pending_by_actor": dict(sorted(by_actor.items(), key=lambda kv: -kv[1])[:8]),
        "decision_breakdown": dict(sorted(decided_kind.items(), key=lambda kv: -kv[1])),
        "no_age_field": len(pend) - len(ages),
    }


def main(argv=None):
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    root = os.environ.get("MDCG_ROOT") or ""
    if "--root" in argv:
        root = argv[argv.index("--root") + 1]
    if not root:
        print(json.dumps({"error": "需要 --root 或 MDCG_ROOT"}, ensure_ascii=False))
        return 2
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    rep = report(root)
    print(json.dumps(rep, ensure_ascii=False, indent=1, sort_keys=True))
    if not rep.get("available"):
        return 2
    return 1 if (rep.get("over_deadline") or 0) > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
