#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sync_zcode_session —— 把 ZCode 会话的「真实对话轮」增量同步进灵枢运行态窗口。

背景（使用者 2026-10-06「不止 dsh 端，zcode 端同样适用这个机制」）：
  zcode 的上下文压缩同样会丢早期对话；本脚本给 zcode 端补上与 DSH 插件同款的
  **短期滑动窗口**：从 zcode 会话库（`~/.zcode/cli/db/db.sqlite`）提取**真人轮**
  （`anchor.origin == "realUser"`）与其**回合最终回复**（同 `turnId` 的 assistant
  文本），增量写入灵枢的 `_recent` 运行态窗口（`cg.remember_event`）——
  压缩续接后即可用既有面回取（`cg(op=recent, action=list)` / `session_recall`）。

纪律（与 DSH 版机制同款）：
  · 只写**运行态窗口**（滚动淘汰、不进知识面、不占检索正排）——与「写入职责归
    LLM（知识面）」两轨独立；
  · 只取 **realUser**（真人在终端输入）——`synthetic`（系统提醒）/`backgroundResult`
    （后台回执）/workflow 子会话一律**不取**；
  · 增量水位落 `~/.mdcg/zcode_sync.json`（不经灵枢根面加文件）；重复运行幂等；
  · `--dry-run` 只打印不落盘。

用法：
  python -X utf8 scripts/sync_zcode_session.py                # 最近 30 轮 → 在役库
  python -X utf8 scripts/sync_zcode_session.py --turns 50
  python -X utf8 scripts/sync_zcode_session.py --dry-run
  python -X utf8 scripts/sync_zcode_session.py --session sess_xxx --root <隔离根>
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ZCODE_DB = Path.home() / ".zcode" / "cli" / "db" / "db.sqlite"
STATE_FILE = Path.home() / ".mdcg" / "zcode_sync.json"
SYNC_TAG = "zcode-window"


def _open_db_ro():
    uri = "file:%s?mode=ro" % ZCODE_DB.as_posix()
    return sqlite3.connect(uri, uri=True)


def latest_realuser_session(con) -> str:
    """最近的、含真人输入的会话（排除 workflow 子会话 sess_dwf-*）。"""
    cur = con.execute(
        "SELECT session_id, MAX(sequence) FROM message "
        "WHERE data LIKE '%\"realUser\"%' AND session_id NOT LIKE 'sess_dwf-%' "
        "GROUP BY session_id ORDER BY MAX(sequence) DESC LIMIT 1")
    row = cur.fetchone()
    return row[0] if row else ""


def extract_turns(con, sid: str, max_turns: int):
    """提取「真人轮」：realUser 消息 + 同 turnId 的 assistant 最终文本。

    返回升序 [(turn_id, created_ms, user_text, assistant_text), ...]（只含完整轮）。
    """
    turns = []
    cur = con.execute(
        "SELECT id, sequence, data FROM message WHERE session_id=? ORDER BY sequence",
        (sid,))
    pending = None            # 当前待填的轮
    for mid, seq, data in cur.fetchall():
        d = json.loads(data)
        role = d.get("role")
        anchor = d.get("anchor") or {}
        turn_id = anchor.get("turnId") or ""
        if role == "user" and anchor.get("origin") == "realUser":
            text = _text_of(con, mid)
            if text:
                if pending and pending.get("assistant"):
                    turns.append(pending)
                pending = {"turn": turn_id, "t": (d.get("time") or {}).get("created", 0),
                           "user": text, "assistant": None}
        elif role == "assistant" and pending and turn_id == pending["turn"]:
            text = _text_of(con, mid)
            if text:
                pending["assistant"] = text     # 同回合后者覆盖 = 最终回复
    if pending and pending.get("assistant"):
        turns.append(pending)
    return turns[-max_turns:]


def _text_of(con, mid: str) -> str:
    """一个 message 的 text parts 拼接（无 text part → 空串）。"""
    out = []
    for (pd,) in con.execute("SELECT data FROM part WHERE message_id=?", (mid,)).fetchall():
        try:
            p = json.loads(pd)
        except ValueError:
            continue
        if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str):
            out.append(p["text"])
    return "\n".join(out).strip()


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 —— 首次运行
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                          encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="zcode 会话真人轮 → 灵枢运行态窗口（增量同步）")
    ap.add_argument("--session", default=None, help="zcode 会话 id（缺省：最近含真人输入的会话）")
    ap.add_argument("--turns", type=int, default=30, help="首次同步的轮数上限（缺省 30）")
    ap.add_argument("--root", default=None, help="灵枢数据根（缺省 env MDCG_ROOT / 默认根）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将同步的轮，不落盘")
    a = ap.parse_args()

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, repo)

    con = _open_db_ro()
    sid = a.session or latest_realuser_session(con)
    if not sid:
        print("未找到含真人输入的 zcode 会话")
        return 1
    turns = extract_turns(con, sid, max(1, a.turns))
    print(f"会话: {sid}｜提取完整轮: {len(turns)}（上限 {a.turns}）")

    state = load_state()
    # 水位**按目标库分键**（隔离测试与在役互不污染）：normcase(root)|session
    if a.root:
        os.environ["MDCG_ROOT"] = a.root
        root = a.root
    else:
        from md_cg.datapath import mdcg_root
        root = mdcg_root()
    key = os.path.normcase(os.path.abspath(root)) + "|" + sid
    sst = state.setdefault(key, {})
    last_t = int(sst.get("last_turn_created") or 0)
    fresh = [t for t in turns if int(t.get("t") or 0) > last_t]
    print(f"水位 last_turn_created={last_t}｜本次增量轮: {len(fresh)}")
    for t in fresh[:3]:
        print(f"  · [{t['t']}] user={t['user'][:40]!r} … assistant={str(t['assistant'])[:40]!r}")
    if len(fresh) > 3:
        print(f"  · … 其余 {len(fresh) - 3} 轮")
    if a.dry_run:
        print("DRY-RUN：未落盘")
        return 0
    if not fresh:
        print("无新增轮，无需写入")
        return 0

    from md_cg.mdcos import MdCGOS
    cg = MdCGOS(root)
    written = 0
    for t in fresh:
        meta = {"session": sid, "source": SYNC_TAG, "turn": t["turn"]}
        cg.remember_event("user", t["user"], tags=["zcode", SYNC_TAG], meta=meta, window=200)
        cg.remember_event("assistant", t["assistant"], tags=["zcode", SYNC_TAG], meta=meta, window=200)
        written += 2
        sst["last_turn_created"] = int(t.get("t") or 0)
    save_state(state)
    print(f"写入完成：{written} 条事件（{len(fresh)} 轮 × 2）→ root={root or '(默认根)'}")
    print(f"回取：cg(op=recent, action=list) 或 session_recall 的 recent 段（meta.session={sid}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
