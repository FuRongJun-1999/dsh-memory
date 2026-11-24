#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""degrade_watch 自证：#996 外部守卫的判据只认「completed 且空正文且无工具」，不误报被打断的回合。

# 功能名：test_degrade_watch —— 合成会话夹具上的红/绿/分型三态
# 生效条件：本机有 zstandard（缺则整跑 skip，exit 0，并在末尾注明）
# 子功能：
#   G1 卡死型：completed + 思考≥200 + 正文 0 + 无工具 ⇒ 检出、分型 dead、退出码 1
#   G2 完成型：同上但思考尾部有完成语 ⇒ 分型 done、退出码 0（不报「卡死」）
#   G3 被打断：reason=aborted + 思考≥200 + 正文 0 ⇒ **不检出**（2026-11-24 实测的误报源）
#   G4 有正文：completed + 正文非空 ⇒ 不检出
#   G5 告警出口：--alerts 写出的 JSONL 只含计数与回合号，**不含思考/正文**
# 执行：python -X utf8 scripts/test_degrade_watch.py
# 验证方式：本文件即验证（5 组断言），退出码 0 = 全通过
# 不适用条件：不验证真实会话语料上的阈值调优；不验证 zstandard 缺失路径
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPT = os.path.join(_HERE, "degrade_watch.py")

_FAIL = []


def ok(cond, label):
    print(("  [PASS] " if cond else "  [FAIL] ") + label)
    if not cond:
        _FAIL.append(label)


def _ev(kind, turn, *, thinking=None, body=None, tools=0, reason=None):
    if kind == "turn/end":
        return {"type": "turn/end", "data": {"turn": turn, "reason": {"kind": reason or "completed"}}}
    blocks = []
    if thinking is not None:
        blocks.append({"type": "reasoning", "text": thinking})
    if body:
        blocks.append({"type": "text", "text": body})
    for _ in range(tools):
        blocks.append({"type": "tool-call", "name": "noop", "arguments": "{}"})
    return {"type": "assistant/message", "data": {"turn": turn, "message": {"role": "assistant", "content": blocks}}}


def _write_session(root, name, events):
    import zstandard as zstd
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    payload = "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n"
    path = os.path.join(d, "session.v4.jsonl.zstd")
    with open(path, "wb") as fh:
        fh.write(zstd.ZstdCompressor().compress(payload.encode("utf-8")))
    return path


def _run(root, alerts=None):
    cmd = [sys.executable, "-X", "utf8", _SCRIPT, "--root", root, "--json"]
    if alerts:
        cmd += ["--alerts", alerts]
    p = subprocess.run(cmd, cwd=_REPO, capture_output=True, text=True, encoding="utf-8", errors="replace")
    data = json.loads((p.stdout or "").strip().splitlines()[-1]) if (p.stdout or "").strip() else {}
    return p.returncode, data, (p.stdout or "") + (p.stderr or "")


THINK_LOOP = "执行。\n\n时间：快。\n\n执行。\n\n写。\n\n执行。\n\n时间：快。\n\n" + ("再做一次。" * 40)
THINK_DONE = "写好了（320 → 1,135）。\n" + ("已经检查过边界。" * 30)


def main():
    try:
        import zstandard  # noqa: F401
    except Exception:
        print("SKIP：本机没有 zstandard，跳过（exit 0）")
        return 0

    tmp = tempfile.mkdtemp(prefix="degrade_watch_")
    try:
        # G1 卡死型
        root1 = os.path.join(tmp, "g1")
        _write_session(root1, "session-dead", [
            _ev("turn/start", 1),
            _ev("assistant/message", 1, thinking=THINK_LOOP),
            _ev("turn/end", 1, reason="completed"),
        ])
        rc, data, raw = _run(root1)
        ok(rc == 1, "G1 卡死型 ⇒ 退出码 1（实际 %d）" % rc)
        ok(data.get("total", {}).get("dead") == 1, "G1 分型 dead=1（实际 %s）" % data.get("total", {}).get("dead"))

        # G2 完成型
        root2 = os.path.join(tmp, "g2")
        _write_session(root2, "session-done", [
            _ev("turn/start", 1),
            _ev("assistant/message", 1, thinking=THINK_DONE),
            _ev("turn/end", 1, reason="completed"),
        ])
        rc, data, raw = _run(root2)
        ok(rc == 0, "G2 完成型 ⇒ 退出码 0（实际 %d）" % rc)
        ok(data.get("total", {}).get("done") == 1 and data.get("total", {}).get("dead") == 0,
           "G2 分型 done=1 / dead=0（实际 done=%s dead=%s）"
           % (data.get("total", {}).get("done"), data.get("total", {}).get("dead")))

        # G3 被打断
        root3 = os.path.join(tmp, "g3")
        _write_session(root3, "session-aborted", [
            _ev("turn/start", 1),
            _ev("assistant/message", 1, thinking=THINK_LOOP),
            _ev("turn/end", 1, reason="aborted"),
        ])
        rc, data, raw = _run(root3)
        ok(rc == 0 and data.get("total", {}).get("blank") == 0,
           "G3 被打断的回合不误报（blank=%s rc=%d）" % (data.get("total", {}).get("blank"), rc))

        # G4 有正文
        root4 = os.path.join(tmp, "g4")
        _write_session(root4, "session-text", [
            _ev("turn/start", 1),
            _ev("assistant/message", 1, thinking=THINK_LOOP, body="做完了三件事，都在下面。"),
            _ev("turn/end", 1, reason="completed"),
        ])
        rc, data, raw = _run(root4)
        ok(rc == 0 and data.get("total", {}).get("blank") == 0,
           "G4 有正文的回合不误报（blank=%s）" % data.get("total", {}).get("blank"))

        # G5 告警出口不含正文
        alerts = os.path.join(tmp, "alerts.jsonl")
        rc, data, raw = _run(root1, alerts=alerts)
        rows = [json.loads(l) for l in io.open(alerts, encoding="utf-8") if l.strip()] if os.path.isfile(alerts) else []
        dumped = json.dumps(rows, ensure_ascii=False)
        ok(len(rows) == 1, "G5 告警写出一行（实际 %d 行）" % len(rows))
        ok("执行。" not in dumped and "时间：快" not in dumped, "G5 告警不含任何正文/思考片段")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("结果：%d pass / %d fail" % (5 - len(_FAIL) if len(_FAIL) <= 5 else 0, len(_FAIL)))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
