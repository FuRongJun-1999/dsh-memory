#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zcode_window_hook —— ZCode 会话窗口钩子（Stop / UserPromptSubmit 双面）。

背景（使用者 2026-10-06「我们取代 zcode 成为管理上下文的 harness 组件」）：
  「记忆系统在每次对话交互完后自动把对话保存为会话的 md 文件，只维护最后 10 条，
   超长优先遗忘最旧历史。以及每到 10 轮提醒一次调用 mdcg 写入记忆，读回确认。」

Stop（每轮交互完，**静默**）：
  · ①增量同步本会话真人轮进灵枢 `_recent` 窗口；
  · ②刷新全量 md 转写（zcode-log-transcripts/<sid>.md，增量追加）；
  · ③刷新会话 md 镜像（zcode-session-window/<sid>.md，**只留最近 10 轮**）。
  · 不输出任何 stdout——引擎对 Stop 钩子仅在 `decision=block`（请求续跑）时才消费
    additionalContexts，普通输出无意义；本钩子纯维护、绝不影响回合结局。

UserPromptSubmit（每次提示词提交前）：
  · **压缩重建**：最近一次上下文压缩（`compact_summary` 结构性判据）晚于上次自动
    注入时 → 注入「接续包」（近 10 轮窗口 + 工程接续段）重建上下文；
  · **逢十轮提醒**：已完成轮数 ≥10 且 %10==0 时注入一次间歇归档提醒（工作纪律
    第 16 条：六要素写入 mdcg + 读回确认），同一轮数不重复提醒；
  · 输出严格 schema `{"additionalContext": "..."}`（引擎 HookJSONOutput；无内容零输出）。

fail-soft 硬纪律：任何异常 → 不输出 + 退出 0，绝不阻断会话。
载荷：stdin JSON（`hookEventName` / `sessionId`）；env `CLAUDE_SESSION_ID` 兜底。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

#: 状态分键：win|{sid} → {"last_compact_ack": ms, "last_reminded_turn": n}
WINDOW_ACK_KEY = "win"
COMPACT_HEADER = "【灵枢接续包（自动注入：检测到上下文压缩——重建近 10 轮窗口）】"
REMINDER_TMPL = (
    "【灵枢·逢十轮提醒】本会话已完成 {n} 轮交互。按工作纪律第 16 条做一次**间歇归档**："
    "把本段（近 10 轮）的核心修改——内容/原因/位置/验证结论——按 CCG 六要素调用 mdcg "
    "写入记忆（cg op=write），写入后**读回确认**一次；不等任务收尾。")


def _load_sync_module():
    """同目录单点复用（不复制第二份同步/镜像逻辑）。"""
    spec = importlib.util.spec_from_file_location(
        "sync_zcode_session", HERE / "sync_zcode_session.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _payload() -> dict:
    try:
        raw = sys.stdin.read()
        if raw.strip():
            d = json.loads(raw)
            if isinstance(d, dict):
                return d
    except Exception:  # noqa: BLE001 —— 输入容错
        pass
    return {}


def _session_id(payload: dict) -> str:
    for k in ("sessionId", "session_id"):
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return (os.environ.get("CLAUDE_SESSION_ID")
            or os.environ.get("ZCODE_SESSION_ID") or "").strip()


def _event(payload: dict) -> str:
    for k in ("hookEventName", "hook_event_name", "event"):
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _stop(sync_mod, sid: str) -> None:
    """上一轮交互完的维护面（静默；三段各自 fail-soft）。"""
    for op in (lambda: sync_mod.sync_to_window(sid),
               lambda: sync_mod.append_transcript(sid),
               lambda: sync_mod.write_window_md(sid)):
        try:
            op()
        except Exception:  # noqa: BLE001 —— 维护失败不阻断
            pass


def _prompt(sync_mod, sid: str) -> str:
    """本轮提交前的注入面（压缩重建 + 逢十轮提醒）；返回注入文本（可为空串）。"""
    parts = []
    con = sync_mod._open_db_ro()
    try:
        state = sync_mod.load_state()
        wst = state.setdefault(WINDOW_ACK_KEY + "|" + sid, {})
        cts = sync_mod.latest_compact_ts(con, sid)
        if cts and cts > int(wst.get("last_compact_ack") or 0):
            parts.append(sync_mod.build_continuation_context(sid, header=COMPACT_HEADER))
            wst["last_compact_ack"] = cts
        n = sync_mod.count_completed_turns(con, sid)
        if n >= 10 and n % 10 == 0 and int(wst.get("last_reminded_turn") or 0) < n:
            parts.append(REMINDER_TMPL.format(n=n))
            wst["last_reminded_turn"] = n
        sync_mod.save_state(state)
    finally:
        con.close()
    return "\n\n".join(p for p in parts if p)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    payload = _payload()
    try:
        sid = _session_id(payload)
        event = _event(payload)
        if not sid or not event:
            return 0                          # 缺标识：静默（不猜）
        sys.path.insert(0, str(REPO))
        sync_mod = _load_sync_module()
        if event == "Stop":
            _stop(sync_mod, sid)
            return 0
        if event == "UserPromptSubmit":
            text = _prompt(sync_mod, sid)
            if text:
                print(json.dumps({"additionalContext": text}, ensure_ascii=False))
            return 0
        return 0
    except Exception as e:  # noqa: BLE001 —— 硬纪律：绝不阻断会话
        sys.stderr.write(f"[zcode_window_hook] fail-soft: {type(e).__name__}: {e}\n")
        return 0


if __name__ == "__main__":
    sys.exit(main())
