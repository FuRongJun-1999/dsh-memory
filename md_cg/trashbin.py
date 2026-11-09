"""trash 保留期清扫（C-5 · 2026-10-31）。

遗忘（`MdCGSecure.forget`）把节点文件搬进 `trash/<id>.md` 并写 `_deletions.jsonl`，
所以「删了」之后正文副本仍留在盘上。本模块按保留期**真删**这些副本，并把清除
动作写成**无载荷**记录追加到 `_purge.jsonl`（只有 id / 字节数 / 时间 / 墓碑哈希，
一个正文字节都不写）。

策略（用户 2026-10-31 定）：保留 7 天后自动清。`MDCG_TRASH_KEEP_DAYS` 可调，
负数表示永不清理，0 表示下一次清扫立即清（供测试/负控）。

生效条件：`trash/` 下有 `<id>.md`，且该 id 在 `_deletions.jsonl` 里有删除时刻
（没有记录就回落到文件 mtime，并计入 `orphans`）。清完之后 `restore(force=True)`
只能返回 `body_purged`——墓碑仍可查、正文不可恢复。
"""

import json
import os
import time

KEEP_ENV = "MDCG_TRASH_KEEP_DAYS"
DEFAULT_KEEP_DAYS = 7.0
PURGE_LOG = "_purge.jsonl"
DELETIONS_LOG = "_deletions.jsonl"


def keep_days_default():
    raw = (os.environ.get(KEEP_ENV) or "").strip()
    if not raw:
        return DEFAULT_KEEP_DAYS
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_KEEP_DAYS


def _iter_jsonl(path):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


def deleted_at_map(root):
    """id → (删除时刻, 墓碑哈希)；同一 id 多次删除取最后一条。"""
    out = {}
    for rec in _iter_jsonl(os.path.join(root, DELETIONS_LOG)):
        nid = rec.get("id")
        if not nid:
            continue
        try:
            t = float(rec.get("t") or 0.0)
        except (TypeError, ValueError):
            t = 0.0
        out[str(nid)] = (t, rec.get("hash"))
    return out


def _append(path, rec):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")


def sweep(root, keep_days=None, dry_run=True, now=None):
    """按保留期清扫 `trash/`。返回读数字典（不抛异常）。"""
    kd = keep_days_default() if keep_days is None else float(keep_days)
    now = time.time() if now is None else float(now)
    rep = {"ok": True, "root": root, "keep_days": kd, "dry_run": bool(dry_run),
           "scanned": 0, "candidates": [], "purged": [], "purged_bytes": 0,
           "kept_recent": 0, "orphans": [], "errors": [], "skipped": None}
    if kd < 0:
        rep["skipped"] = "keep_days<0（永不清理）"
        return rep
    trash = os.path.join(root, "trash")
    if not os.path.isdir(trash):
        rep["skipped"] = "trash 目录不存在"
        return rep
    dmap = deleted_at_map(root)
    cutoff = now - kd * 86400.0
    purge_log = os.path.join(root, PURGE_LOG)
    for name in sorted(os.listdir(trash)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(trash, name)
        if not os.path.isfile(path):
            continue
        rep["scanned"] += 1
        nid = name[:-3]
        rec = dmap.get(nid)
        if rec is None:
            rep["orphans"].append(nid)
            try:
                ts = os.path.getmtime(path)
            except OSError:
                continue
            thash = None
        else:
            ts, thash = rec
            if not ts:
                try:
                    ts = os.path.getmtime(path)
                except OSError:
                    continue
        if ts > cutoff:
            rep["kept_recent"] += 1
            continue
        rep["candidates"].append(nid)
        if dry_run:
            continue
        try:
            nbytes = os.path.getsize(path)
            os.remove(path)
        except OSError as exc:
            rep["errors"].append({"id": nid, "error": str(exc)})
            continue
        rep["purged"].append(nid)
        rep["purged_bytes"] += nbytes
        _append(purge_log, {"t": now, "id": nid, "bytes": nbytes,
                            "keep_days": kd, "deleted_at": ts,
                            "tombstone": thash, "reason": "retention"})
    rep["ok"] = not rep["errors"]
    return rep
