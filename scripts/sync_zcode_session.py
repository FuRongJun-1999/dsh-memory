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
import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path

ZCODE_DB = Path.home() / ".zcode" / "cli" / "db" / "db.sqlite"
STATE_FILE = Path.home() / ".mdcg" / "zcode_sync.json"
SYNC_TAG = "zcode-window"

# 「只维护最后 10 条，超长优先遗忘最旧历史」（使用者 2026-10-06）
WINDOW_LIMIT = 10
WINDOW_TAIL_SCAN = 600   # 尾扫消息条数（每轮低开销；够覆盖 ≥10 轮）


def _data_root() -> Path:
    """数据区根（转写与窗口镜像的父目录；**不落本机绝对字面量**——门禁 check_local_paths）：
    ① env `MDCG_DATA_ROOT`（zcode 侧 MCP 配置有此键）→ ② mdcg 库根的父目录 → ③ 家目录 `.mdcg`。
    """
    env = os.environ.get("MDCG_DATA_ROOT")
    if env:
        return Path(env)
    try:
        return Path(_resolve_root()).parent
    except Exception:  # noqa: BLE001
        return Path.home() / ".mdcg"


def transcript_root() -> Path:
    """全量转写落点根（持久、仓外；与 dsh-log-transcripts 同级先例）。"""
    return _data_root() / "zcode-log-transcripts"


def window_root() -> Path:
    """会话 md 镜像落点根（只留最近 10 轮；Stop 钩子每轮刷新）。"""
    return _data_root() / "zcode-session-window"


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


def extract_turns(con, sid: str, max_turns: int, scan_limit: int | None = None):
    """提取「真人轮」：realUser 消息 + 同 turnId 的 assistant 最终文本。

    返回升序 [(turn_id, created_ms, user_text, assistant_text), ...]（只含完整轮）。
    scan_limit 非空时只扫**尾部 N 条消息**（每轮钩子低开销调用；全量调用保持缺省 None）。
    """
    if scan_limit:
        cur = con.execute(
            "SELECT id, sequence, data FROM message WHERE session_id=? "
            "ORDER BY sequence DESC LIMIT ?", (sid, int(scan_limit)))
        rows = list(reversed(cur.fetchall()))
    else:
        cur = con.execute(
            "SELECT id, sequence, data FROM message WHERE session_id=? ORDER BY sequence",
            (sid,))
        rows = cur.fetchall()
    turns = []
    pending = None            # 当前待填的轮
    for mid, seq, data in rows:
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


def _resolve_root() -> str:
    """库根解析单点（**与 zcode MCP 服务端同源，防双库分叉**）：
    ① env `MDCG_ROOT` → ② `~/.zcode/cli/config.json` 里 mcp.servers.mdcg 的 env.MDCG_ROOT
    → ③ `md_cg.datapath.mdcg_root()` 缺省。
    背景：本机 `mdcg_root()` 缺省解析到 C 盘 profile 遗留根，而 zcode 侧 MCP 服务的是
    配置里声明的 AEIS 数据区库根（`mcp.servers.mdcg` 的 `env.MDCG_ROOT`）——钩子脚本
    若走缺省会读写**非权威库**（2026-10-06 实测抓出）。
    """
    env = os.environ.get("MDCG_ROOT")
    if env:
        return env
    try:
        cfg = Path.home() / ".zcode" / "cli" / "config.json"
        d = json.loads(cfg.read_text(encoding="utf-8"))
        v = (((d.get("mcp") or {}).get("servers") or {}).get("mdcg")
             or {}).get("env", {}).get("MDCG_ROOT")
        if isinstance(v, str) and v.strip():
            return v.strip()
    except Exception:  # noqa: BLE001 —— 配置缺失即回退缺省
        pass
    from md_cg.datapath import mdcg_root
    return mdcg_root()


def count_completed_turns(con, sid: str) -> int:
    """本会话**已完成**真人轮数（有真人提问且有同回合助手回复；末轮未完成不计）。"""
    cur = con.execute(
        "SELECT COUNT(*) FROM message WHERE session_id=? "
        "AND json_extract(data,'$.anchor.origin')='realUser'", (sid,))
    n = int(cur.fetchone()[0] or 0)
    if n <= 0:
        return 0
    row = con.execute(
        "SELECT data FROM message WHERE session_id=? "
        "AND json_extract(data,'$.anchor.origin')='realUser' "
        "ORDER BY sequence DESC LIMIT 1", (sid,)).fetchone()
    tid = None
    try:
        tid = (json.loads(row[0]).get("anchor") or {}).get("turnId") if row else None
    except Exception:  # noqa: BLE001
        tid = None
    if tid:
        has = con.execute(
            "SELECT 1 FROM message WHERE session_id=? "
            "AND json_extract(data,'$.anchor.turnId')=? "
            "AND json_extract(data,'$.role')='assistant' LIMIT 1", (sid, tid)).fetchone()
        if not has:
            n -= 1
    return n


def latest_compact_ts(con, sid: str) -> int:
    """最近一次上下文压缩的时刻（compact_summary 消息 time.created；无则 0）。

    结构性判据（json_extract semantics.kind）——不按文本子串，免受消息正文提及污染。
    """
    cur = con.execute(
        "SELECT data FROM message WHERE session_id=? AND data LIKE '%compact_summary%' "
        "ORDER BY sequence DESC LIMIT 40", (sid,))
    best = 0
    for (d,) in cur.fetchall():
        try:
            m = json.loads(d)
        except ValueError:
            continue
        if ((m.get("semantics") or {}).get("kind")) == "compact_summary":
            best = max(best, int((m.get("time") or {}).get("created") or 0))
            break
    return best


def _render_turn(t: dict) -> str:
    parts = ["**我说：**", "", t["user"].strip(), "", "**ZCode说：**", "",
             (t.get("assistant") or "").strip(), "", "---", ""]
    return "\n".join(parts)


def append_transcript(sid: str, con=None, root=None) -> int:
    """全量 md 转写增量追加（真人轮；水位分键 `transcript|session`）。返回新增轮数。"""
    own = con is None
    if own:
        con = _open_db_ro()
    try:
        turns = extract_turns(con, sid, 10 ** 6, scan_limit=WINDOW_TAIL_SCAN)
    finally:
        if own:
            con.close()
    state = load_state()
    key = "transcript|" + sid
    sst = state.setdefault(key, {})
    last_t = int(sst.get("last_turn_created") or 0)
    fresh = [t for t in turns if int(t.get("t") or 0) > last_t]
    if not fresh:
        return 0
    root = Path(root) if root is not None else transcript_root()
    root.mkdir(parents=True, exist_ok=True)
    out = root / f"{sid}.md"
    if not out.exists():
        out.write_text(
            f"# ZCode 会话转录：{sid}\n\n"
            f"> 导出器：scripts/export_zcode_transcript.py（增量追加；只收真人轮与其回合最终回复）\n"
            f"> 回读：灵枢 `cg(op=ref)` 按区间读回本文件原文\n\n---\n", encoding="utf-8")
    with open(out, "a", encoding="utf-8", newline="\n") as f:
        for t in fresh:
            f.write(_render_turn(t))
    sst["last_turn_created"] = int(fresh[-1].get("t") or 0)
    save_state(state)
    return len(fresh)


def write_window_md(sid: str, con=None, limit: int = WINDOW_LIMIT) -> Path:
    """会话 md 镜像：**只保留最近 limit 轮**（超长优先遗忘最旧）；原子写。返回落点路径。"""
    own = con is None
    if own:
        con = _open_db_ro()
    try:
        turns = extract_turns(con, sid, limit, scan_limit=WINDOW_TAIL_SCAN)
        total = count_completed_turns(con, sid)
    finally:
        if own:
            con.close()
    start = max(1, total - len(turns) + 1)
    lines = [
        f"# ZCode 会话窗口镜像：{sid}",
        "",
        f"> 维护：scripts/zcode_window_hook.py（Stop 钩子每轮刷新）｜**只保留最近 {limit} 轮**，超长优先遗忘最旧",
        f"> 更新：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}｜本窗 {len(turns)} 轮（轮 {start}–{total}）",
        f"> 完整原文：zcode-log-transcripts/{sid}.md 与灵枢 _recent 窗口（cg(op=recent) / session_recall）",
        "", "---", ""]
    for i, t in enumerate(turns, start=start):
        ts = int(t.get("t") or 0)
        human = datetime.datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M:%S") if ts else "?"
        lines += [f"## 轮 {i} · {human}", "", "**我说：**", "", (t.get("user") or "").strip(), "",
                  "**ZCode说：**", "", (t.get("assistant") or "").strip(), "", "---", ""]
    wroot = window_root()
    wroot.mkdir(parents=True, exist_ok=True)
    out = wroot / f"{sid}.md"
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    os.replace(tmp, out)
    return out


def sync_to_window(sid: str, max_turns: int = 200) -> int:
    """增量同步本会话真人轮进灵枢运行态窗口（`_recent`）。返回新写入轮数。

    尾扫口径（每轮钩子低开销）；首次大回填用 CLI（--turns）走全量。
    """
    con = _open_db_ro()
    try:
        turns = extract_turns(con, sid, max_turns, scan_limit=WINDOW_TAIL_SCAN)
    finally:
        con.close()
    if not turns:
        return 0
    state = load_state()
    root = _resolve_root()
    key = os.path.normcase(os.path.abspath(root)) + "|" + sid
    sst = state.setdefault(key, {})
    last_t = int(sst.get("last_turn_created") or 0)
    fresh = [t for t in turns if int(t.get("t") or 0) > last_t]
    if not fresh:
        return 0
    from md_cg.mdcos import MdCGOS
    cg = MdCGOS(root)
    for t in fresh:
        meta = {"session": sid, "source": SYNC_TAG, "turn": t["turn"]}
        cg.remember_event("user", t["user"], tags=["zcode", SYNC_TAG], meta=meta, window=200)
        cg.remember_event("assistant", t["assistant"], tags=["zcode", SYNC_TAG], meta=meta, window=200)
        sst["last_turn_created"] = int(t.get("t") or 0)
    save_state(state)
    return len(fresh)


def build_continuation_context(sid: str, header: str | None = None) -> str:
    """接续包文本（窗口近 10 轮 + 工程接续段）。任何段缺即略；由调用方决定注入。"""
    from md_cg.mdcos import MdCGOS
    root = _resolve_root()
    cg = MdCGOS(root)
    # 预算 4000：实测（2026-10-06）在富库（unresolved 28 条 + 自我卡）下 1200 会把
    # recent 段整段裁空——「回取近 10 轮窗口」是接续包主载荷，必须保住（本函数调用侧
    # 还会再切片，最终注入文本有界）。
    pack = cg.session_recall(session=sid, recent_limit=10, budget_tokens=4000)
    lines = [header or "【灵枢接续包（自动注入：会话开始/压缩恢复）】",
             "以下为你错过的近期对话与在办事项（来自灵枢记忆系统；完整原文可用 cg(op=ref) 回读）。"]
    act = (pack.get("tasks") or {}).get("active") or []
    if act:
        lines.append("\n## 在办任务")
        for t in act[:5]:
            name = t.get("name") or t.get("id") or "?"
            lines.append(f"- {name}（{t.get('status', '?')}）")
    goals = pack.get("goals") or []
    if goals:
        lines.append("\n## 活跃目标")
        for g in goals[:3]:
            lines.append(f"- {g.get('goal_text') or g.get('text') or g}")
    recent = pack.get("recent") or []
    if recent:
        lines.append("\n## 本会话近期对话（近 10 条）")
        for e in recent:
            txt = str(e.get("text") or "").replace("\n", " ")
            if len(txt) > 120:
                txt = txt[:120] + "…"
            lines.append(f"- [{e.get('role')}] {txt}")
    unres = pack.get("unresolved") or []
    if unres:
        lines.append("\n## 未解问题")
        for u in unres[:3]:
            lines.append(f"- {str(u.get('question') or u.get('id') or u)[:100]}")
    return "\n".join(lines)


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
