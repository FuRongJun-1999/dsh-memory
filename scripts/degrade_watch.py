#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""#996 外部退化守卫 · 回合级空回合扫描器（只读会话日志）。

# 功能名：degrade_watch —— 从会话日志里离线数「空回合」，把卡死型与完成型分开报
# 生效条件：本机能读到 DSH 会话日志（session*.jsonl.zstd 或其解压后的 jsonl）；
#           判据阈值来自 md_cg/degrade_guard.py（本文件不另立一套）
# 子功能：
#   ① 只读扫描：解压日志帧、按 turn 聚合（正文只数 text 块，思考只数 reasoning 块）；
#   ② 主判据：md_cg.degrade_guard.blank_turn（思考 ≥200 且正文 0 且该回合无工具调用）；
#   ③ 附加限定：**只认 reason.kind == "completed" 的回合**——
#      2026-11-24 实测（主会话 1052 回合）5 个「空回合」全部是 aborted/error/interrupted，
#      不加这条限定就会把「被打断的正常回合」报成退化；
#   ④ 分型：思考尾部出现完成语（写好了/已完成/…）⇒ 完成型，否则 ⇒ 卡死型；
#   ⑤ 伴随特征：md_cg.degrade_guard.nag_runs（单独用有 60% 误报，只作佐证）；
#   ⑥ 告警出口：--alerts 追加 JSONL（只写计数与回合号，**不写任何正文**）。
# 执行：python -X utf8 scripts/degrade_watch.py [--root DIR ...] [--alerts PATH] [--json] [--tail-mb N]
# 验证方式：scripts/test_degrade_watch.py（合成会话夹具：卡死型红 / 完成型分型 / 被打断不误报 / 无正文不误报）
# 不适用条件：
#   · 不判「内容对不对」——只看形态；
#   · 不做干预：本进程无法把话塞回被守卫的会话，只告警；
#   · 无 zstandard 且日志为压缩帧 ⇒ exit 2（fail-closed，绝不静默报 0）；
#   · 非 DSH 会话日志格式（无 turn/end 事件）⇒ 该文件跳过并计数，不计入分母。

退出码：0 = 无卡死型空回合；1 = 检出卡死型空回合（该报警了）；2 = 环境错误（fail-closed）。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

try:  # 判据权威唯一：#996 的阈值只在 md_cg/degrade_guard.py 里定义
    from md_cg.degrade_guard import blank_turn, nag_runs, BLANK_TURN_MIN_THINK
except Exception as _e:  # pragma: no cover - 环境缺包时 fail-closed
    sys.stderr.write("degrade_watch: 无法导入判据模块 md_cg.degrade_guard（%s）\n" % _e)
    raise SystemExit(2)

try:
    import zstandard as _zstd
except Exception:  # pragma: no cover
    _zstd = None

_MAGIC = b"\x28\xb5\x2f\xfd"
_DONE_PAT = re.compile(r"(写好了|已完成|完成了|做完了|搞定|收工)")
# 默认只认「家目录下的 .dsh/sessions」，可用 DSH_HOME 覆盖（不写死任何本机绝对路径）
_DEFAULT_ROOTS = (
    os.path.join(os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh"), "sessions"),
)


class DegradeEnvError(RuntimeError):
    """环境或压缩帧读取错误（fail-closed：main 返回退出码 2，不伪装为 0 或 1）。"""


def _zstd_decompress_tail(path, size, tail_mb):
    """从 zstd 日志尾部解压内容；尾窗无帧头或命中伪帧头时自动放大窗口至全文件。"""
    if _zstd is None:
        raise DegradeEnvError("日志是 zstd 压缩帧，但本机没有 zstandard 模块")
    tail_bytes = (int(tail_mb) * 1024 * 1024) if (tail_mb is not None and int(tail_mb) > 0) else size
    windows = []
    for cand in (tail_bytes, max(tail_bytes * 4, 16 << 20), size):
        w = min(size, max(1, cand))
        if w not in windows:
            windows.append(w)
    last_err = None
    for win in windows:
        start = max(0, size - win)
        with open(path, "rb") as fh:
            fh.seek(start)
            raw = fh.read()
        idx = raw.find(_MAGIC)
        if idx < 0:
            if win < size:
                continue
            raise DegradeEnvError("zstd 日志缺少有效帧头：%s" % path)
        try:
            return _zstd.ZstdDecompressor().stream_reader(io.BytesIO(raw[idx:])).read()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if win < size:
                continue
            raise DegradeEnvError("zstd 日志解压失败（%s）：%s" % (path, exc)) from exc
    raise DegradeEnvError("zstd 日志解压失败（%s）：%s" % (path, last_err))


def _iter_lines(path, tail_mb):
    """产出日志里的 JSON 行；压缩帧就地解压，尾部只读最后 tail_mb MB。"""
    size = os.path.getsize(path)
    if size <= 0:
        return
    with open(path, "rb") as fh:
        head = fh.read(4)
    is_zstd = (head == _MAGIC) or path.endswith(".zstd")
    if is_zstd:
        blob = _zstd_decompress_tail(path, size, tail_mb)
    else:
        tail_bytes = (int(tail_mb) * 1024 * 1024) if (tail_mb is not None and int(tail_mb) > 0) else size
        start = max(0, size - tail_bytes)
        with open(path, "rb") as fh:
            fh.seek(start)
            blob = fh.read()
        if _MAGIC in blob:
            blob = _zstd_decompress_tail(path, size, tail_mb)
        elif start > 0:
            # 尾部截断大概率落在某行中间：丢弃半截首行，防止整文件被 JSONDecodeError 静默跳过
            nl = blob.find(b"\n")
            if nl >= 0:
                blob = blob[nl + 1:]
            else:
                with open(path, "rb") as fh:
                    blob = fh.read()
    for line in blob.decode("utf-8", "replace").splitlines():
        if line.strip():
            yield line


def _iter_events(path, tail_mb):
    """逐行解析 JSON 对象事件；忽略截断残行与非 dict JSON 行，保留环境异常传播。"""
    for line in _iter_lines(path, tail_mb):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict):
            yield ev


def aggregate(events):
    """按 turn 聚合：{turn: {thinking, body_len, tool_calls, reason, nag}}（不存正文）。"""
    turns = {}
    for e in events:
        if not isinstance(e, dict):
            continue
        t = e.get("type")
        d = e.get("data")
        if not isinstance(d, dict):
            d = {}
        if t == "turn/end":
            rec = turns.setdefault(d.get("turn"), _new_turn())
            reason = d.get("reason")
            if isinstance(reason, dict) and reason.get("kind"):
                rec["reason"] = reason.get("kind")
        elif t == "assistant/message":
            rec = turns.setdefault(d.get("turn"), _new_turn())
            rec["msgs"] += 1
            msg = d.get("message")
            blocks = (msg.get("content") if isinstance(msg, dict) else None) or []
            if not isinstance(blocks, list):
                continue
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                kind = b.get("type")
                if kind == "text":
                    txt = b.get("text")
                    if isinstance(txt, str):
                        rec["body_len"] += len(txt)
                elif kind == "tool-call":
                    rec["tool_calls"] += 1
                elif kind == "reasoning":
                    rtxt = b.get("text") or b.get("reasoning") or ""
                    if isinstance(rtxt, str):
                        rec["thinking"] += rtxt
    for rec in turns.values():
        rec["nag"] = nag_runs(rec["thinking"])
    return turns


def _new_turn():
    return {"thinking": "", "body_len": 0, "tool_calls": 0, "reason": None, "msgs": 0, "nag": 0}


def classify(turns):
    """返回 (汇总, 明细列表)。明细只含回合号与计数，不含正文。"""
    completed = {k: v for k, v in turns.items() if v["reason"] == "completed"}
    hits = []
    for k, v in sorted(completed.items(), key=lambda kv: str(kv[0])):
        if not blank_turn(v, min_think=BLANK_TURN_MIN_THINK):
            continue
        kind = "done" if _DONE_PAT.search(v["thinking"]) else "dead"
        hits.append({"turn": k, "kind": kind, "think_len": len(v["thinking"]),
                     "body_len": v["body_len"], "tool_calls": v["tool_calls"], "nag": v["nag"]})
    summary = {
        "turns": len(turns),
        "completed": len(completed),
        "skipped_reasons": sorted({str(v["reason"]) for v in turns.values() if v["reason"] != "completed"}),
        "blank": len(hits),
        "dead": sum(1 for h in hits if h["kind"] == "dead"),
        "done": sum(1 for h in hits if h["kind"] == "done"),
    }
    return summary, hits


def scan_file(path, tail_mb):
    turns = aggregate(_iter_events(path, tail_mb))
    if not turns:
        return None
    return classify(turns)


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--root", action="append", default=None, help="会话根目录（可重复）")
    ap.add_argument("--tail-mb", type=int, default=64, help="每个文件只读尾部 N MB（默认 64）")
    ap.add_argument("--alerts", default=None, help="追加告警 JSONL 的路径")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出全部读数")
    ap.add_argument("--quiet", action="store_true", help="只输出汇总行")
    args = ap.parse_args(argv)

    roots = args.root or [r for r in _DEFAULT_ROOTS if os.path.isdir(r)]
    if not roots:
        sys.stderr.write("degrade_watch: 找不到会话根目录（用 --root 指定）\n")
        return 2

    files = []
    for root in roots:
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                if fn.endswith(".jsonl.zstd") or fn.endswith(".jsonl"):
                    files.append(os.path.join(dirpath, fn))
    if not files:
        sys.stderr.write("degrade_watch: 会话根目录下没有日志文件\n")
        return 2

    results, total = [], {"turns": 0, "completed": 0, "blank": 0, "dead": 0, "done": 0}
    skipped = 0
    for path in sorted(files):
        try:
            r = scan_file(path, args.tail_mb)
        except (DegradeEnvError, RuntimeError, OSError) as exc:
            sys.stderr.write("degrade_watch: %s\n" % exc)
            return 2
        if r is None:
            skipped += 1
            continue
        summary, hits = r
        for k in ("turns", "completed", "blank", "dead", "done"):
            total[k] += summary[k]
        results.append({"session": os.path.basename(os.path.dirname(path)),
                        "file": os.path.basename(path), "summary": summary, "hits": hits})

    if args.json:
        sys.stdout.write(json.dumps({"total": total, "skipped": skipped, "sessions": results},
                                    ensure_ascii=False, sort_keys=True) + "\n")
    else:
        for r in results:
            s = r["summary"]
            print("%-30s 回合 %4d | completed %4d | 空回合 %2d（卡死 %2d / 完成 %2d）"
                  % (r["session"], s["turns"], s["completed"], s["blank"], s["dead"], s["done"]))
        if not args.quiet:
            print("合计：回合 %d | completed %d | 空回合 %d（卡死 %d / 完成 %d）| 跳过文件 %d"
                  % (total["turns"], total["completed"], total["blank"], total["dead"], total["done"], skipped))

    if args.alerts and total["blank"]:
        os.makedirs(os.path.dirname(os.path.abspath(args.alerts)) or ".", exist_ok=True)
        with io.open(args.alerts, "a", encoding="utf-8") as fh:
            for r in results:
                for h in r["hits"]:
                    fh.write(json.dumps({"ts": int(time.time()), "session": r["session"],
                                         "turn": h["turn"], "kind": h["kind"],
                                         "think_len": h["think_len"], "body_len": h["body_len"],
                                         "tool_calls": h["tool_calls"], "nag": h["nag"]},
                                        ensure_ascii=False, sort_keys=True) + "\n")

    return 1 if total["dead"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
