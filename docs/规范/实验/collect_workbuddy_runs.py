# -*- coding: utf-8 -*-
"""采集 WorkBuddy 会话 JSONL 与元数据（实验 runner 的取数端）。

用法：
  python docs/规范/实验/collect_workbuddy_runs.py --since 1792389000000 --out .tmp/workbuddy_exp/runs
  python docs/规范/实验/collect_workbuddy_runs.py --session <id> --out .tmp/workbuddy_exp/runs

只读 workbuddy.db 与 projects/*.jsonl，不修改任何 WorkBuddy 状态。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

WB = Path(os.environ.get("WORKBUDDY_HOME", Path.home() / ".workbuddy"))
DB = WB / "workbuddy.db"
PROJECTS = WB / "projects"


def norm_cwd(cwd: str) -> str:
    s = cwd.replace(":", "-").replace("/", "-").replace("\\", "-")
    return s.strip("-").lower()


def find_jsonl(session_id: str, cwd: str) -> Path | None:
    direct = PROJECTS / norm_cwd(cwd) / f"{session_id}.jsonl"
    if direct.exists():
        return direct
    hits = list(PROJECTS.rglob(f"{session_id}.jsonl"))
    return hits[0] if hits else None


def load_sessions(since: int | None = None, session_id: str | None = None) -> list[dict]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    q = "select id,title,cwd,model,permission_mode,status,created_at,updated_at,last_activity_at,thought_level,source_mode from sessions"
    rows = [dict(r) for r in con.execute(q)]
    con.close()
    if session_id:
        rows = [r for r in rows if r["id"] == session_id]
    elif since is not None:
        rows = [r for r in rows if (r.get("created_at") or 0) >= since]
    rows.sort(key=lambda r: r.get("created_at") or 0)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=int, default=None, help="epoch ms，只取该时刻后创建的会话")
    ap.add_argument("--session", default=None, help="只取指定 session id")
    ap.add_argument("--out", required=True, help="输出目录")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = load_sessions(args.since, args.session)
    manifest = []
    for r in rows:
        jp = find_jsonl(r["id"], r.get("cwd") or "")
        item = dict(r)
        item["jsonl"] = str(jp) if jp else None
        if jp:
            dst = out / f"{r['id']}.jsonl"
            if jp.resolve() != dst.resolve():
                shutil.copy2(jp, dst)
            item["snapshot"] = str(dst)
        manifest.append(item)
        print(json.dumps(item, ensure_ascii=False))
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"# collected {len(manifest)} session(s) -> {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
