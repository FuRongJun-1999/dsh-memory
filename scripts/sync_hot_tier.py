# -*- coding: utf-8 -*-
"""每晚同步：重建本地热层 + 把当天短期记忆整理成摘要写入总库。

用法（缺省全是「先看别写」）：
  python -X utf8 scripts/sync_hot_tier.py --root D:/program/AEIS/data/mdcg
  python -X utf8 scripts/sync_hot_tier.py --root ... --write      # 才真正写摘要节点
  python -X utf8 scripts/sync_hot_tier.py --root ... --dry-digest # 只打印摘要文本

两件事：
  ① 重建 `_hot/`（本地热层：self/anchor + 近 7 天情景 + 高重要度知识）；
  ② 把**当天**的短期记忆整理成一条摘要，写入总库（contextual 层，幂等 id = `digest_YYYYMMDD`）。

为什么摘要只写 contextual：知识层有准入闸（#749/#913/#914），日摘不是知识；
标 `regenerable` 便于 regenerate/heal 重放；同一日期重复运行**不产生第二条**。

回滚：`cg forget --node_id digest_YYYYMMDD`（软删，可 restore）。
"""
from __future__ import annotations

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import hottier  # noqa: E402


def _day_bounds(now: float):
    lt = time.localtime(now)
    start = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    return start, start + 86400


def collect_day(cg, start: float, end: float, max_items: int = 200):
    """取当天 contextual 条目（按时间正序），用于整理摘要。"""
    nodes = (getattr(cg, "index", {}) or {}).get("nodes") or {}
    rows = []
    for nid, e in nodes.items():
        if str((e or {}).get("layer") or "") != "contextual":
            continue
        ts = float((e or {}).get("t") or (e or {}).get("created_at") or 0.0)
        if not (start <= ts < end):
            continue
        rows.append((ts, nid))
    rows.sort()
    rows = rows[:max_items]
    items = []
    for ts, nid in rows:
        try:
            node = cg.get(nid) or {}
        except Exception:
            continue
        body = " ".join(str(node.get("content") or "").split())
        if body:
            items.append((ts, nid, body[:120]))
    return items


def digest_text(day: str, items) -> str:
    if not items:
        return ""
    head = "# 日摘 · %s（短期记忆整理）" % day
    lines = [head, "", "- 条目数：%d" % len(items), "- 时间范围：%s ~ %s" % (
        time.strftime("%H:%M", time.localtime(items[0][0])),
        time.strftime("%H:%M", time.localtime(items[-1][0]))),
        ""]
    for _ts, nid, body in items[:40]:
        lines.append("- `%s` %s" % (nid, body))
    if len(items) > 40:
        lines.append("- …另有 %d 条未列出" % (len(items) - 40))
    return "\n".join(lines)


def write_digest(cg, day: str, text: str) -> dict:
    """幂等写入：同日同 id，不覆盖已有（已存在则跳过，返回 existing）。"""
    nid = "digest_" + day
    try:
        exists = bool(cg.get(nid))
    except Exception:
        exists = False
    if exists:
        return {"node_id": nid, "skipped": True, "reason": "同日摘要已存在"}
    cg.add(nid, text, layer="contextual",
           tags=["daily-digest", "regenerable", "shortterm"],
           importance=0.5, verification_basis="data")
    return {"node_id": nid, "skipped": False}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="认知图根（生产库路径）")
    ap.add_argument("--write", action="store_true", help="真正写入摘要节点（缺省只报告）")
    ap.add_argument("--dry-digest", action="store_true", help="只打印摘要文本")
    ap.add_argument("--days", type=int, default=hottier.RECENT_DAYS)
    ap.add_argument("--max-items", type=int, default=200)
    a = ap.parse_args()

    from md_cg.mdcos import MdCGOS
    t0 = time.time()
    cg = MdCGOS(a.root, actor="sync_hot_tier")
    print("[1/2] 重建热层 …")
    meta = hottier.build(cg, recent_days=a.days)
    print("      nodes=%s tokens=%s truncated=%s layers=%s (%.1fs)"
          % (meta["nodes"], meta["tokens"], meta["truncated"], meta["layers"], time.time() - t0))

    print("[2/2] 当天短期记忆整理 …")
    start, end = _day_bounds(time.time())
    day = time.strftime("%Y%m%d", time.localtime(start))
    items = collect_day(cg, start, end, max_items=a.max_items)
    text = digest_text(day, items)
    if not items:
        print("      当天没有可整理的短期记忆（跳过）")
        return 0
    print("      条目 %d 条，摘要 %d 字" % (len(items), len(text)))
    if a.dry_digest:
        print("---- 摘要预览 ----")
        print(text)
        return 0
    if not a.write:
        print("      （未加 --write：只报告，不写总库）")
        return 0
    res = write_digest(cg, day, text)
    print("      写入结果：%s" % res)
    return 0


if __name__ == "__main__":
    sys.exit(main())