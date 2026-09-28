# -*- coding: utf-8 -*-
"""test_dsh_log_index_shape —— N218 非对象 JSON 行 fail-closed 记账守卫

背景（2026-09-28 缺陷 N218，medium；v24 报告 N206「日志消费面」的相邻入口）：
  scripts/dsh_log_index.py 的 parse_session_log 对非对象 JSON 行未按同函数既有
  fail-closed 纪律记账（:283-285 已有 lines_json_error 计数）即 `.get`：一行
  `null`/`[]`/`123`/`"x"` 解析合法却在 `o.get("type")` 抛 AttributeError——异常
  逃出 main（主循环 try 只有 finally、无 except）⇒ 整轮摄取中断：stdout 全空、
  无 TOTAL 汇总、该行之后的会话不再处理、stderr 只有栈无告警。zstd 压缩 JSONL
  一行即触发、无需凭据。次生腿=内层值非对象同型（data=[1] / data 为字符串 /
  data.message 为字符串 / inserted[].source 为字符串），只修顶层不闭合。

守卫断言面（合成 zstd 日志、哑正文、临时目录）：
  L1 单元：8+ 形态逐行调用 parse_session_log 不抛异常（修前 null 首行即 AttributeError）
  L2 单元：坏行**之后**的正常消息仍被收集（不中断、不丢正文）
  L3 单元：顶层非对象 5 形态逐个计入 lines_not_object；内层形态计入 lines_bad_shape
  L4 CLI：`--dry-run` exit 0（修前 exit 1）+ stdout 非空含 TOTAL（修前 0 行）
  L5 CLI：坏行之后的会话 s2 仍被摄取（修前 s2 行 0 条）
  L6 CLI：stderr 有显式告警（修前只有栈）
  L7 CLI：单会话合成日志（仅一行 null）→ 仍 exit 0 且产出该会话行

运行：python -X utf8 scripts/test_dsh_log_index_shape.py
"""
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

_SCRIPT = os.path.join(HERE, "scripts", "dsh_log_index.py")

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail)[:400])


def _load_mod():
    spec = importlib.util.spec_from_file_location("dsh_log_shape_guard", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_SESSION = {"type": "session", "id": "S1", "createdAt": 1700000000000,
            "cwd": "/tmp/ws", "agentPreset": "p"}

#: 12 种形态：5 顶层非对象 + 7 内层/类型非法（修复前 4 种崩、其余亦无记账）
_BAD_LINES = [
    "null", "[]", "123", '"x"', "true",
    json.dumps({"type": ["a"], "data": {}}),
    json.dumps({"type": "user/message", "data": [1]}),
    json.dumps({"type": "user/message", "data": "str"}),
    json.dumps({"type": "assistant/message", "data": {"message": "str"}}),
    json.dumps({"type": "system/message", "data": {"message": 7}}),
    json.dumps({"type": "agent/inbox/spliced",
                "data": {"inserted": {"a": 1}}}),
    json.dumps({"type": "agent/inbox/spliced",
                "data": {"inserted": [{"id": "z", "source": "str",
                                       "content": [{"type": "text",
                                                    "text": "nope"}]}]}}),
]


def _user_msg(mid, text):
    return {"type": "user/message",
            "data": {"id": mid, "content": [{"type": "text", "text": text}]}}


def _write_log(root, ws, sid, lines):
    import zstandard as zstd
    d = os.path.join(root, ws, sid)
    os.makedirs(d, exist_ok=True)
    raw = "\n".join(x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
                    for x in lines) + "\n"
    with open(os.path.join(d, "session.v4.jsonl.zstd"), "wb") as fh:
        fh.write(zstd.ZstdCompressor().compress(raw.encode("utf-8")))
    return os.path.join(d, "session.v4.jsonl.zstd")


def unit(mod, tmp):
    print("[1] 单元：非对象/形态非法行不抛异常、不中断、逐项记账")
    log = _write_log(tmp, "ws", "u1",
                     [_SESSION] + _BAD_LINES + [_user_msg("m1", "AFTER-BODY")])
    try:
        parsed = mod.parse_session_log(log)
        err = None
    except Exception as exc:  # noqa: BLE001
        parsed, err = None, "%s: %s" % (type(exc).__name__, exc)
    check("L1 parse_session_log 不抛异常（修前 null 首行即 AttributeError）",
          err is None, err)
    if parsed is None:
        return
    st = parsed["stats"]
    check("L2 坏行之后的正常消息仍被收集",
          [m["text"] for m in parsed["msgs"]] == ["AFTER-BODY"],
          parsed["msgs"])
    check("L3 顶层非对象 5 形态计入 lines_not_object",
          st["lines_not_object"] == 5, st["lines_not_object"])
    check("L3 内层/类型非法计入 lines_bad_shape（7 项）",
          st["lines_bad_shape"] == 7, st["lines_bad_shape"])
    check("L3 计数与行数自洽（12 行坏行全部落账）",
          st["lines_not_object"] + st["lines_bad_shape"] == len(_BAD_LINES),
          (st["lines_not_object"], st["lines_bad_shape"]))
    check("L3 坏行不影响总行数与既有 json_error 口径",
          st["lines_total"] == 1 + len(_BAD_LINES) + 1
          and st["lines_json_error"] == 0,
          (st["lines_total"], st["lines_json_error"]))


def _run(args, cwd=HERE):
    return subprocess.run(
        [sys.executable, "-X", "utf8", _SCRIPT] + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=dict(os.environ, PYTHONUTF8="1"), cwd=cwd, timeout=600)


def cli(tmp):
    print("[2] CLI：整轮摄取不中断（修前 stdout 全空、exit 1）")
    root = os.path.join(tmp, "sessions")
    os.makedirs(root, exist_ok=True)
    _write_log(root, "ws", "s1",
               [_SESSION] + _BAD_LINES + [_user_msg("m1", "body s1")])
    _write_log(root, "ws", "s2",
               [dict(_SESSION, id="S2", createdAt=1700000001000),
                _user_msg("m2", "body s2")])
    got = _run(["--sessions-root", root, "--dry-run"])
    out = (got.stdout or "")
    err = (got.stderr or "")
    check("L4 exit 0（修前 exit 1）", got.returncode == 0,
          "rc=%s err=%s" % (got.returncode, err[-300:]))
    check("L4 stdout 非空且含 TOTAL（修前 0 行）",
          "TOTAL" in out, out[-400:])
    check("L5 坏行之后的会话 s2 仍被摄取（修前 0 条）",
          '"session": "s2"' in out, out[:600])
    check("L6 stderr 有显式告警（修前只有栈）",
          "WARNING" in err and "非对象" in err, err[-300:])
    check("L6 stderr 无 traceback", "Traceback" not in err, err[-300:])

    print("[3] CLI：仅一行 null 的退化日志")
    solo = os.path.join(tmp, "solo")
    os.makedirs(solo, exist_ok=True)
    _write_log(solo, "ws", "s1", ["null"])
    got = _run(["--sessions-root", solo, "--dry-run"])
    out = (got.stdout or "")
    check("L7 退化日志仍 exit 0 并产出会话行",
          got.returncode == 0 and "TOTAL" in out, (got.returncode, out[-300:]))


def main():
    global passed, failed
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        import zstandard                        # noqa: F401
    except ImportError:
        print("  [SKIP] 缺依赖 zstandard，整份守卫跳过")
        return 0
    mod = _load_mod()
    tmp = tempfile.mkdtemp(prefix="n218_guard_")
    try:
        unit(mod, tmp)
        cli(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
