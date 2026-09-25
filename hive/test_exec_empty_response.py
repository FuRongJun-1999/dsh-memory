# -*- coding: utf-8 -*-
"""蜂巢执行器空包假成功守卫（v2 N7 复测成立，2026-09-25 修复）。

背景：网关故障回 200 + 空/缺 choices（或 content=null）时——
  - 无 tools 单发路径（call_llm）曾无条件 ok=true + EXIT_OK 落盘
    （content 兜底成 ""，:1542-1548 无条件 out.update(ok=True)）；
  - 工具路径强制终答分支（超轮次后不带 tools 的一次请求）同样无
    _empty_turn 防护（对照轮内防护在位）→ forced_final=true + content=""
    的「成功」result 流入下游合并/续跑链；
  - content=null 穿透 .get("content", "") 落 None（key 存在 default 不触发）。
_empty_turn（docstring 明言「不冒充有效终答」）曾仅工具轮内一处调用。

修法（fail-closed/诚实失败）：call_llm 与强制终答分支对空助手轮统一回
{"_error": …}，main 的 _error 落盘通道写 ok=false + EXIT_API（与工具链
失败同协议）；content=null 经 _empty_turn 归入空轮（不再穿透）。
本测试把「空包不得记成功」固化为机械断言：
  [A] 单元面 call_llm 四形态（choices=[]/缺键/content=""/content=null）
  [B] 单元面 run_with_tools 强制终答分支（对照：轮内防护零回归）
  [C] 端到端子进程（本地 http.server mock 200+空 choices、哑令牌、
      临时 job 目录，python hive/exec.py <job_dir>——复现实跑形态；
      对照组正常 content 仍 rc=0+ok=true，证修复不误伤）

运行：python -X utf8 -m hive.test_exec_empty_response   （退出码 0 = 全绿）
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_spec = importlib.util.spec_from_file_location(
    "hive_exec_guard", os.path.join(_HERE, "exec.py"))
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok] {name}")
        return
    FAIL += 1
    print(f"  [FAIL] {name}  {detail}")


_SPEC = {"model": "mock-model", "user_prompt": "hi", "timeout_s": 5}

TOOL_CALL_RESP = {  # 模型要求调一个不存在的工具（执行面诚实报错、无副作用）
    "choices": [{"message": {"content": "", "tool_calls": [
        {"id": "c1", "type": "function",
         "function": {"name": "nope", "arguments": "{}"}}]}}]}


# ---------------------------------------------------------------- [A] 单元面
print("[A] call_llm：空包四形态不得冒充成功")
with mock.patch.dict(os.environ, {"HIVE_API_KEY": "dummy"}):
    for tag, resp in [
        ("choices=[]", {"choices": []}),
        ("缺 choices 键", {}),
        ("content 空串", {"choices": [{"message": {"content": ""}}]}),
        ("content=null", {"choices": [{"message": {"content": None}}]}),
    ]:
        with mock.patch.object(ex, "_post_chat", return_value=resp):
            out = ex.call_llm(dict(_SPEC), [{"role": "user", "content": "q"}])
        check(f"A {tag} → _error（不冒充成功）", "_error" in out,
              f"got {json.dumps(out, ensure_ascii=False)[:200]}")
    ok_resp = {"choices": [{"message": {"content": "正常终答"}}],
               "usage": {"total_tokens": 5}, "model": "mock-model"}
    with mock.patch.object(ex, "_post_chat", return_value=ok_resp):
        out = ex.call_llm(dict(_SPEC), [{"role": "user", "content": "q"}])
    check("A 正常 content 零回归（无 _error、content/usage 原样）",
          "_error" not in out and out.get("content") == "正常终答"
          and out.get("usage", {}).get("total_tokens") == 5
          and out.get("model") == "mock-model",
          f"got {json.dumps(out, ensure_ascii=False)[:200]}")

# ---------------------------------------------------------------- [B] 工具路
print("[B] run_with_tools：强制终答分支空包不得 forced_final 假成功")
MSG = [{"role": "user", "content": "q"}]


def _tools_spec(rounds: int) -> dict:
    return {**_SPEC, "tools": ["read_file"], "max_tool_rounds": rounds}


def _run_tool(seq):
    with mock.patch.dict(os.environ, {"HIVE_API_KEY": "dummy"}), \
            mock.patch.object(ex, "_post_chat",
                              side_effect=lambda b, t: seq.pop(0)):
        return ex.run_with_tools(_tools_spec(1), [m.copy() for m in MSG],
                                 "job_g", job_dir=None)


out = _run_tool([{"choices": []}])
check("B 轮内空包既有防护零回归（_error 空助手轮）",
      "_error" in out and "空助手轮" in out["_error"],
      f"got {json.dumps(out, ensure_ascii=False)[:200]}")
out = _run_tool([TOOL_CALL_RESP, TOOL_CALL_RESP, {"choices": []}])
check("B 强制终答空包 → _error（不得 forced_final+content=\"\" 假成功）",
      "_error" in out and "空助手轮" in out["_error"]
      and not out.get("forced_final"),
      f"got {json.dumps(out, ensure_ascii=False)[:300]}")
out = _run_tool([TOOL_CALL_RESP, TOOL_CALL_RESP,
                 {"choices": [{"message": {"content": "强制终答正常文本"}}]}])
check("B 强制终答有 content 零回归（forced_final=true 且非空）",
      "_error" not in out and out.get("forced_final") is True
      and out.get("content") == "强制终答正常文本",
      f"got {json.dumps(out, ensure_ascii=False)[:300]}")

# ---------------------------------------------------------------- [C] 端到端
print("[C] 端到端子进程：mock 网关 200+空包（哑令牌、临时 job 目录）")


class _Handler(BaseHTTPRequestHandler):
    mode = "empty"  # empty | null | ok | toolloop

    def do_POST(self):  # noqa: N802 —— http.server 约定
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        if self.mode == "toolloop":
            payload = TOOL_CALL_RESP if body.get("tools") else {"choices": []}
        elif self.mode == "null":
            payload = {"choices": [{"message": {"content": None}}]}
        elif self.mode == "ok":
            payload = {"choices": [{"message": {"content": "正常终答"}}],
                       "usage": {"total_tokens": 5}}
        else:
            payload = {"choices": []}
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # noqa: N802 —— 静默访问日志
        pass


def _run_exec(mode: str, spec: dict) -> tuple:
    """起 mock 网关 + 跑 exec.py 子进程，返回 (rc, result dict)。"""
    _Handler.mode = mode
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    tmp = tempfile.mkdtemp(prefix="hive_exec_guard_")
    try:
        job = os.path.join(tmp, "job")
        os.makedirs(job)
        with open(os.path.join(job, "spec.json"), "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False)
        env = dict(os.environ, PYTHONUTF8="1",
                   HIVE_API_KEY="dummy",
                   HIVE_API_BASE=f"http://127.0.0.1:{srv.server_address[1]}")
        r = subprocess.run([sys.executable, os.path.join(_HERE, "exec.py"), job],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env, shell=False,
                           cwd=_REPO, timeout=60)
        try:
            with open(os.path.join(job, "result.json"), encoding="utf-8") as f:
                result = json.load(f)
        except (OSError, ValueError):
            result = {}
        return r.returncode, result
    finally:
        srv.shutdown()
        srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True)


rc, res = _run_exec("empty", dict(_SPEC))
check("C1 单发路空包：rc!=0 且 ok=false 且 error 提及空（旧缺陷 rc=0+ok=true）",
      rc != 0 and res.get("ok") is False and "空" in (res.get("error") or ""),
      f"rc={rc} result={json.dumps(res, ensure_ascii=False)[:200]}")
rc, res = _run_exec("null", dict(_SPEC))
check("C2 单发路 content=null：rc!=0 且 ok=false（不再穿透落 None）",
      rc != 0 and res.get("ok") is False,
      f"rc={rc} result={json.dumps(res, ensure_ascii=False)[:200]}")
rc, res = _run_exec("toolloop",
                    {**_SPEC, "tools": ["read_file"], "max_tool_rounds": 1})
check("C3 工具路强制终答空包：rc!=0 且 ok=false（旧缺陷 forced_final 假成功）",
      rc != 0 and res.get("ok") is False
      and res.get("forced_final") is None,
      f"rc={rc} result={json.dumps(res, ensure_ascii=False)[:200]}")
rc, res = _run_exec("ok", dict(_SPEC))
check("C4 对照组正常 content：rc=0 且 ok=true（修复不误伤正常路）",
      rc == 0 and res.get("ok") is True
      and res.get("content") == "正常终答",
      f"rc={rc} result={json.dumps(res, ensure_ascii=False)[:200]}")

print(f"\n结果: {PASS} pass / {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
