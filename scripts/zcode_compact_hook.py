#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zcode_compact_hook —— ZCode SessionStart 钩子（startup/resume/compact 三态）：
在会话开始或上下文压缩那一刻，自动把「灵枢接续包」注入会话。

定位（使用者 2026-10-06「我们取代 zcode 成为管理上下文的 harness 组件」）：
  zcode 的无历史截断 API（hook 只能**追加注入**），故 zcode 端做**等价效果**：
  · 压缩(compact)/新会话(startup)/恢复(resume) 触发点 → 自动注入
    ①本会话运行态窗口（近 10 轮对话，来自 `_recent`）
    ②工程接续（任务台账/活跃目标/未解——跨会话稳定段）
  · 完整原文另有全量 md 转写（scripts/export_zcode_transcript.py）+ 灵枢 doc_ref
    回读（cg(op=ref)）——模型需要时读回。
  · 会话 md 镜像（只留最近 10 轮、超长优先遗忘最旧）由 scripts/zcode_window_hook.py
    的 Stop 钩子每轮维护；本钩子在启动/恢复时也顺带刷新一次（二者单点共享）。

行为（fail-soft 硬纪律：**任何异常 → 空输出 + 退出 0，绝不阻断会话**）：
  · 先增量同步本会话真人轮（复用 scripts/sync_zcode_session.py 的单点逻辑）；
  · 再取 session_recall（recent_limit=10）拼注入文本；
  · stdout 输出 `{"additionalContext": "..."}`（ZCode hook 严格 schema：只此一键）。

用法（由 ZCode hook 以 process 形态拉起；也可手动喂输入自测）：
  echo '{}' | python -X utf8 scripts/zcode_compact_hook.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def _load_sync_module():
    """同目录单点复用（不复制第二份同步逻辑）。"""
    spec = importlib.util.spec_from_file_location(
        "sync_zcode_session", HERE / "sync_zcode_session.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _session_id(payload: dict) -> str:
    """会话 id：hook 载荷 > 环境变量 > 空（空则跳过注入）。"""
    for k in ("session_id", "sessionId"):
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return (os.environ.get("CLAUDE_SESSION_ID") or "").strip()


def _sync(sync_mod, sid: str) -> None:
    """增量同步本会话真人轮进窗口 + 刷新窗口 md 镜像与全量转写（全部尽力而为）。"""
    sync_mod.sync_to_window(sid)
    try:
        sync_mod.write_window_md(sid)
    except Exception:  # noqa: BLE001 —— 镜像刷新失败不阻断
        pass
    try:
        sync_mod.append_transcript(sid)
    except Exception:  # noqa: BLE001 —— 转写追加失败不阻断
        pass


def _build_context(sid: str, sync_mod=None) -> str:
    """接续包 → 注入文本（窗口近 10 轮 + 工程接续段；单点在 sync_zcode_session）。"""
    if sync_mod is None:
        sync_mod = _load_sync_module()
    return sync_mod.build_continuation_context(sid)


def _ack_compact(sync_mod, sid: str) -> None:
    """本钩子已注入接续包 ≈ 已履行「近 10 轮重建」职能——记录压缩确认位，
    防 UserPromptSubmit 钩子在同一压缩上重复注入（2026-10-06 重启后实测双注入）。"""
    con = sync_mod._open_db_ro()
    try:
        cts = sync_mod.latest_compact_ts(con, sid)
    finally:
        con.close()
    if not cts:
        return
    state = sync_mod.load_state()
    wst = state.setdefault("win|" + sid, {})
    if cts > int(wst.get("last_compact_ack") or 0):
        wst["last_compact_ack"] = cts
        sync_mod.save_state(state)


def main() -> int:
    payload = {}
    try:
        raw = sys.stdin.read()
        if raw.strip():
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                payload = {}
    except Exception:  # noqa: BLE001 —— 输入容错
        payload = {}
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    try:
        sys.path.insert(0, str(REPO))
        sid = _session_id(payload)
        if not sid:
            return 0                        # 无会话标识：静默（不猜）
        sync_mod = _load_sync_module()
        try:
            _sync(sync_mod, sid)
        except Exception:  # noqa: BLE001 —— 同步失败不阻断注入
            pass
        try:
            _ack_compact(sync_mod, sid)
        except Exception:  # noqa: BLE001 —— 确认位写入失败不阻断
            pass
        text = _build_context(sid, sync_mod)
        print(json.dumps({"additionalContext": text}, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001 —— 硬纪律：绝不阻断会话
        sys.stderr.write(f"[zcode_compact_hook] fail-soft: {type(e).__name__}: {e}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
