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
  · 真·「只保留 10 条」的硬窗属自研会话引擎（身体侧）原生能力，非本钩子职责。

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
    """增量同步本会话真人轮进窗口（尽力而为；失败不抛）。"""
    con = sync_mod._open_db_ro()
    turns = sync_mod.extract_turns(con, sid, 200)
    if not turns:
        return
    state = sync_mod.load_state()
    from md_cg.datapath import mdcg_root
    root = os.environ.get("MDCG_ROOT") or mdcg_root()
    key = os.path.normcase(os.path.abspath(root)) + "|" + sid
    sst = state.setdefault(key, {})
    last_t = int(sst.get("last_turn_created") or 0)
    fresh = [t for t in turns if int(t.get("t") or 0) > last_t]
    if not fresh:
        return
    from md_cg.mdcos import MdCGOS
    cg = MdCGOS(root)
    for t in fresh:
        meta = {"session": sid, "source": "zcode-window", "turn": t["turn"]}
        cg.remember_event("user", t["user"], tags=["zcode", "zcode-window"], meta=meta, window=200)
        cg.remember_event("assistant", t["assistant"], tags=["zcode", "zcode-window"], meta=meta, window=200)
        sst["last_turn_created"] = int(t.get("t") or 0)
    sync_mod.save_state(state)


def _build_context(sid: str) -> str:
    """接续包 → 注入文本（窗口近 10 轮 + 工程接续段；任何段缺即略）。"""
    from md_cg.datapath import mdcg_root
    from md_cg.mdcos import MdCGOS
    root = os.environ.get("MDCG_ROOT") or mdcg_root()
    cg = MdCGOS(root)
    pack = cg.session_recall(session=sid, recent_limit=10, budget_tokens=1200)
    lines = ["【灵枢接续包（自动注入：会话开始/压缩恢复）】",
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
        text = _build_context(sid)
        print(json.dumps({"additionalContext": text}, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001 —— 硬纪律：绝不阻断会话
        sys.stderr.write(f"[zcode_compact_hook] fail-soft: {type(e).__name__}: {e}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
