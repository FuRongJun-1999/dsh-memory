# -*- coding: utf-8 -*-
"""hive MCP 入口 DoS 守卫：非 dict JSON / 非 dict params 不得崩掉常驻 server。

背景（2026-09-25 缺陷挖掘 v2-N16，独立子进程实跑取证）：
一行**非 dict JSON**（批量数组 / 裸 str / 裸 int / 裸 null——均为 JSON 合法值，
恶意客户端一行即可发出）或 **params 非 dict**（str/list/int）的 tools/call，
曾使常驻 MCP server 进程直接崩溃退出（DoS）：
  - main 循环的 try 只包 json.loads 的 ValueError，resp = _rpc(req) 在 try 外；
  - _rpc 内 req.get("method") 与 (req.get("params") or {}).get("name") 两处
    入口均无 isinstance 守卫——AttributeError 逐行杀进程；
  - 工具层 try 兜底只包工具执行（fn(args)），不包入口解析。
实抓 traceback：批量数组 → req.get('method') AttributeError 'list'；
params 为 str → (...).get('name') AttributeError 'str'。攻击行后追加的
合法 tools/list 探活无应答（server 已死，stdout 0 行、rc=1）。

修法（fail-closed）：_rpc 入口对非 dict req 回 id=null 的 -32600
Invalid Request、对 tools/call 的非 dict params 回 -32602 Invalid params
（不进工具）；main 循环把 _rpc 调用纳入 try 兜底（与工具层同款模板）——
入口未来演化再引入的异常也只回一行 -32603，不杀 server。

本测试把上述契约固化为机械断言：
  ① 单元面：_rpc 对七种攻击形态不抛异常、回正确错误码；
  ② 子进程面（复现实跑形态）：哑 env（临时 jobs 目录 + 不存在的 config）下
     逐攻击行 → 合法 tools/list 探活必须有应答、进程退出码 0；
  ③ 合法面零回归：initialize / tools/list / 未知方法 / 未知工具 / notification。

测试卫生：全程不触真实 serve（不发 spawn/poll/kill/restart/doctor）、
不触真实 jobs 目录与真实令牌（HIVE_JOBS_DIR/HIVE_CONFIG 指向临时目录）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from hive.hive_mcp import mcp_server as ms  # noqa: E402 —— REPO 须先入 sys.path

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  OK   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        FAILS.append(name)


# 非 dict JSON 攻击行（单行、合法 JSON、非 object）——批量数组是 JSON-RPC 2.0
# 规范明文允许客户端发出的形态；裸标量是 json.loads 的合法产物。
NONDICT_LINES = [
    ("batch_array", '[{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}]'),
    ("bare_str", '"boom"'),
    ("bare_int", "123"),
    ("bare_null", "null"),
]

# tools/call 的 params 非 dict 攻击（params 值直接放 dict 再 json.dumps）
NONDICT_PARAMS = [
    ("params_string", "x"),
    ("params_list", [1, 2]),
    ("params_int", 5),
]

_PROBE_RID = 777  # 攻击行后的合法探活请求 id


def _probe_env(tmp: str) -> dict:
    """哑 env：临时 jobs 目录 + 不存在的 config——绝不触真实 serve/令牌。"""
    env = dict(os.environ, PYTHONUTF8="1", PYTHONPATH=_REPO)
    env["HIVE_JOBS_DIR"] = os.path.join(tmp, "jobs")
    env["HIVE_CONFIG"] = os.path.join(tmp, "nonexistent_config.json")
    return env


def _probe_after(lines_in: list[str],
                 target_ids: "set[int] | None" = None) -> tuple[bool, bool, int, str]:
    """起隔离 server 子进程，顺序喂 lines_in，等目标 id 全部应答。

    返回 (探活有应答, 攻击行有错误响应行, 进程退出码, stderr 末 400 字)。
    旧缺陷形态：探活无应答（EOF）且 rc=1、stderr 含 AttributeError。
    target_ids 缺省 {_PROBE_RID}；夹击场景传多条合法 id（须全部应答）。
    """
    targets = target_ids or {_PROBE_RID}
    tmp = tempfile.mkdtemp(prefix="hive_entry_guard_")
    p = subprocess.Popen(
        [sys.executable, "-m", "hive.hive_mcp.mcp_server"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=_probe_env(tmp), shell=False, cwd=_REPO,
        text=True, encoding="utf-8", errors="replace",
    )
    out_lines: list[str] = []

    def _pump() -> None:
        for ln in p.stdout:  # 读到 EOF（进程死/关流）自然结束
            out_lines.append(ln.rstrip("\n"))

    pump = threading.Thread(target=_pump, daemon=True)
    pump.start()
    try:
        for ln in lines_in:
            p.stdin.write(ln + "\n")
        p.stdin.flush()
        # 等目标 id 全部应答或进程退出，上限 10s（防挂死守卫自身）
        deadline = time.time() + 10.0
        probed = False
        while time.time() < deadline and not probed:
            seen = {_safe_id(ln) for ln in out_lines}
            probed = targets <= seen
            if probed:
                break
            if p.poll() is not None:  # 进程已退（旧缺陷：崩在攻击行）
                break
            time.sleep(0.05)
        try:
            p.stdin.close()
        except OSError:
            pass
        try:
            rc = p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
            rc = -1
        err_tail = ""
        try:
            err_tail = (p.stderr.read() or "")[-400:]
        except Exception:  # noqa: BLE001 —— 诊断尾串，读不到就算了
            pass
        return probed, len(out_lines) > 0, rc, err_tail
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _safe_id(line: str):
    try:
        v = json.loads(line)
    except ValueError:
        return None
    return v.get("id") if isinstance(v, dict) else None


def main() -> int:
    print("① 单元面：_rpc 对七种攻击形态不抛异常、回正确错误码")
    for tag, raw in NONDICT_LINES:
        try:
            r = ms._rpc(json.loads(raw))
        except Exception as e:  # noqa: BLE001 —— 旧缺陷正是抛异常杀 server
            check(f"_rpc({tag}) 不抛异常", False, f"抛 {type(e).__name__}: {e}")
            continue
        check(f"_rpc({tag}) 回 -32600 且 id=null",
              isinstance(r, dict)
              and (r.get("error") or {}).get("code") == -32600
              and r.get("id") is None,
              f"got {json.dumps(r, ensure_ascii=False)[:200]}")
    for tag, bad in NONDICT_PARAMS:
        req = {"jsonrpc": "2.0", "id": 901, "method": "tools/call",
               "params": bad}
        try:
            r = ms._rpc(req)
        except Exception as e:  # noqa: BLE001
            check(f"_rpc(tools/call {tag}) 不抛异常", False,
                  f"抛 {type(e).__name__}: {e}")
            continue
        check(f"_rpc(tools/call {tag}) 回 -32602 且 id 回带",
              isinstance(r, dict)
              and (r.get("error") or {}).get("code") == -32602
              and r.get("id") == 901,
              f"got {json.dumps(r, ensure_ascii=False)[:200]}")

    print("② 子进程面：攻击行后合法探活必须有应答、退出码 0")
    for tag, raw in NONDICT_LINES:
        lines = [raw,
                 json.dumps({"jsonrpc": "2.0", "id": _PROBE_RID,
                             "method": "tools/list"})]
        probed, _, rc, err = _probe_after(lines)
        check(f"子进程 {tag} 后探活有应答且 rc=0", probed and rc == 0,
              f"probed={probed} rc={rc} stderr尾={err!r}")
    for tag, bad in NONDICT_PARAMS:
        lines = [json.dumps({"jsonrpc": "2.0", "id": 902,
                             "method": "tools/call", "params": bad}),
                 json.dumps({"jsonrpc": "2.0", "id": _PROBE_RID,
                             "method": "tools/list"})]
        probed, _, rc, err = _probe_after(lines)
        check(f"子进程 tools/call {tag} 后探活有应答且 rc=0",
              probed and rc == 0, f"probed={probed} rc={rc} stderr尾={err!r}")

    print("③ 合法面零回归（不触工具执行、不触 serve/jobs）")
    r = ms._rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    check("initialize 零回归",
          (r.get("result") or {}).get("serverInfo", {}).get("name")
          == "hive-mcp",
          f"got {json.dumps(r, ensure_ascii=False)[:200]}")
    r = ms._rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    check("tools/list 零回归（五工具）",
          isinstance((r.get("result") or {}).get("tools"), list)
          and len(r["result"]["tools"]) == 5,
          f"got {json.dumps(r, ensure_ascii=False)[:200]}")
    r = ms._rpc({"jsonrpc": "2.0", "id": 3, "method": "no/such"})
    check("未知方法仍 -32601", (r.get("error") or {}).get("code") == -32601)
    r = ms._rpc({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                 "params": {"name": "no_such_tool", "arguments": {}}})
    check("未知工具仍 -32602", (r.get("error") or {}).get("code") == -32602)
    r = ms._rpc({"jsonrpc": "2.0", "method": "notifications/initialized"})
    check("notification 仍返回 None", r is None)
    # 端到端合法定向：合法行混在攻击行中间仍逐行应答（两条合法 id 全应答）
    lines = ['"boom"',
             json.dumps({"jsonrpc": "2.0", "id": 5, "method": "tools/list"}),
             json.dumps({"jsonrpc": "2.0", "id": 903, "method": "tools/call",
                         "params": "x"}),
             json.dumps({"jsonrpc": "2.0", "id": 6, "method": "tools/list"})]
    probed, has_out, rc, err = _probe_after(lines, target_ids={5, 6})
    check("攻击行夹击下两条合法行均应答且 rc=0", probed and has_out and rc == 0,
          f"probed={probed} rc={rc} stderr尾={err!r}")

    print(f"\n结果: {len(FAILS)} fail")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
